"""Recuperación híbrida: tres canales, una fusión explícita.

    consulta → señales exactas → exacto ∥ léxico ∥ semántico → RRF → evidencia

**El aislamiento vive en cada canal, no después de fusionar.** Los tres reciben
los alcances autorizados y los aplican en su propia consulta SQL. Nunca se
recupera de todo el corpus para filtrar al fusionar: un pasaje prohibido no
llega a entrar en la fusión, y por tanto no puede desplazar a uno permitido ni
aparecer por un fallo de la última etapa (regla 3, ADR 0014).

**Por qué RRF y no una suma de puntuaciones.** `ts_rank_cd` y la distancia
coseno no son comparables: no comparten escala, ni rango, ni significado. Una
suma ponderada obligaría a inventar los pesos y a recalibrarlos cada vez que
cambie el modelo. Reciprocal Rank Fusion usa solo la **posición** en cada
canal, que sí es comparable, y es reproducible sin parámetros ajustados a
nuestro conjunto dorado.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from elsa.core.authorization import Scope
from elsa.core.query_signals import detect_signals
from elsa.ports.documents import ChunkProvenance
from elsa.ports.embeddings import EmbeddingsPort
from elsa.ports.evidence import (
    Channel,
    ChannelHit,
    Evidence,
    EvidenceSet,
    EvidenceStrength,
    LexicalSearchPort,
)
from elsa.ports.vectors import ActiveModelError, VectorStorePort

_logger = logging.getLogger(__name__)

__all__ = ["HybridRetrievalService", "RRF_K"]

# El valor convencional de la propuesta original de RRF (Cormack et al., 2009),
# y el que usan la mayoría de implementaciones. Se deja fijo y declarado en vez
# de ajustarlo contra nuestro conjunto dorado: 67 consultas no bastan para
# calibrar un hiperparámetro sin sobreajustar, y un 60 documentado es más
# defendible que un número elegido porque subía el Recall.
RRF_K = 60


@dataclass
class _Accumulator:
    provenance: ChunkProvenance
    hits: list[ChannelHit]
    score: float = 0.0


class HybridRetrievalService:
    def __init__(
        self,
        *,
        lexical: LexicalSearchPort,
        vectors: VectorStorePort,
        embeddings: EmbeddingsPort,
        rrf_k: int = RRF_K,
    ) -> None:
        self._lexical = lexical
        self._vectors = vectors
        self._embeddings = embeddings
        self._rrf_k = rrf_k

    async def search(
        self,
        *,
        query: str,
        scopes: Sequence[Scope],
        limit: int = 10,
        per_channel_limit: int | None = None,
    ) -> EvidenceSet:
        """Recupera evidencia autorizada de los tres canales y la fusiona.

        `scopes` es obligatorio y sin valor por defecto: sin alcances no se
        devuelve «todo», se devuelve nada.
        """
        if not query.strip() or not scopes or limit <= 0:
            return EvidenceSet((), EvidenceStrength.NONE, (), ())

        depth = per_channel_limit or max(limit * 2, 10)
        signals = detect_signals(query)
        queried: list[Channel] = []
        ranked: dict[Channel, list[tuple[ChunkProvenance, float]]] = {}

        if signals.has_exact_signal:
            queried.append(Channel.EXACT)
            ranked[Channel.EXACT] = list(
                await self._lexical.search_exact(
                    identifiers=signals.identifiers, scopes=scopes, limit=depth
                )
            )

        queried.append(Channel.LEXICAL)
        ranked[Channel.LEXICAL] = list(
            await self._lexical.search_lexical(query=query, scopes=scopes, limit=depth)
        )

        semantic = await self._semantic(query, scopes, depth)
        if semantic is not None:
            queried.append(Channel.SEMANTIC)
            ranked[Channel.SEMANTIC] = semantic

        evidence = self._fuse(ranked, limit)
        return EvidenceSet(
            evidence=evidence,
            strength=_strength(evidence),
            channels_queried=tuple(queried),
            identifiers_detected=signals.identifiers,
        )

    async def _semantic(
        self, query: str, scopes: Sequence[Scope], depth: int
    ) -> list[tuple[ChunkProvenance, float]] | None:
        """El canal semántico, o `None` si no hay modelo activo.

        Que falte el modelo no puede tumbar la recuperación entera: los códigos
        y los nombres exactos tienen que seguir encontrándose. Se degrada a dos
        canales y se declara cuáles respondieron.
        """
        try:
            vectors = await self._embeddings.embed_queries([query])
            found = await self._vectors.search(
                query_embedding=vectors[0], scopes=scopes, limit=depth
            )
        except ActiveModelError:
            _logger.info("semantic channel unavailable: no active embedding model")
            return None
        # La distancia se invierte a similitud solo para reportarla: la fusión
        # usa la posición, nunca este número.
        return [(hit.provenance, hit.similarity) for hit in found]

    def _fuse(
        self, ranked: dict[Channel, list[tuple[ChunkProvenance, float]]], limit: int
    ) -> tuple[Evidence, ...]:
        """Reciprocal Rank Fusion: `Σ 1 / (k + posición)` sobre los canales.

        El mismo chunk encontrado por dos canales **no se duplica**: se suma su
        aportación y se conserva la posición que le dio cada uno.
        """
        merged: dict[str, _Accumulator] = {}
        for channel, results in ranked.items():
            for index, (provenance, score) in enumerate(results, start=1):
                entry = merged.setdefault(
                    provenance.chunk.id, _Accumulator(provenance=provenance, hits=[])
                )
                entry.hits.append(ChannelHit(channel=channel, rank=index, score=score))
                entry.score += 1.0 / (self._rrf_k + index)

        # Una coincidencia exacta inequívoca no puede quedar por debajo de una
        # señal semántica mediocre: si el chunk contiene literalmente el código
        # que se preguntó, encabeza. Es la razón de que el canal exacto exista.
        def order(entry: _Accumulator) -> tuple[int, float, str]:
            exact = any(hit.channel is Channel.EXACT for hit in entry.hits)
            return (0 if exact else 1, -entry.score, entry.provenance.chunk.id)

        ordered = sorted(merged.values(), key=order)
        return tuple(
            Evidence(
                provenance=entry.provenance,
                hits=tuple(sorted(entry.hits, key=lambda h: h.channel.value)),
                fused_score=round(entry.score, 6),
                rank=position,
            )
            for position, entry in enumerate(ordered[:limit], start=1)
        )


def _strength(evidence: Sequence[Evidence]) -> EvidenceStrength:
    """Cuánta evidencia hay, sin inventar un umbral numérico.

    Se apoya en dos hechos observables y no en una puntuación calibrada, que
    esta etapa no puede justificar: si hubo coincidencia literal del
    identificador preguntado, o si canales independientes coincidieron en el
    mismo pasaje. La política de responder o callar es del bloque de RAG.
    """
    if not evidence:
        return EvidenceStrength.NONE
    best = evidence[0]
    if best.has_exact_match or best.found_by_multiple_channels:
        return EvidenceStrength.SUFFICIENT
    return EvidenceStrength.WEAK
