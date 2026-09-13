"""Evidencia recuperada: qué la encontró, dónde estaba y cómo citarla.

Este es el contrato de salida del Bloque 4.3. **No redacta nada**: entrega
pasajes autorizados con su procedencia y con el rastro de qué canal los trajo,
para que el bloque siguiente pueda citar y decidir. Componer una respuesta no
es de aquí.
"""

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from elsa.core.authorization import Scope
from elsa.ports.documents import ChunkProvenance

__all__ = [
    "Channel",
    "ChannelHit",
    "Evidence",
    "EvidenceRetrievalPort",
    "EvidenceSet",
    "EvidenceStrength",
    "LexicalSearchPort",
    "ScoredProvenance",
]


class Channel(StrEnum):
    """Por dónde se encontró un pasaje."""

    EXACT = "exact"
    """Coincidencia literal de un identificador. Determinista, sin modelo."""

    LEXICAL = "lexical"
    """Texto completo de PostgreSQL con la configuración `spanish`."""

    SEMANTIC = "semantic"
    """Vecino más cercano del vector de la consulta, búsqueda exacta."""


class EvidenceStrength(StrEnum):
    """Cuánta evidencia hay, no cuán cierta es la respuesta.

    Deliberadamente **no** hay un umbral numérico absoluto: fijarlo exigiría
    medirlo sobre consultas reales de planta, que todavía no existen, y un
    umbral inventado se acabaría citando como si estuviera calibrado. Lo que
    esta etapa entrega es la señal; la política de responder o abstenerse la
    fija el bloque de RAG con estos datos delante.
    """

    SUFFICIENT = "sufficient"
    """Hay coincidencia exacta, o varios canales coinciden en el mismo pasaje."""

    WEAK = "weak"
    """Un solo canal, sin refuerzo. Se entrega, marcado."""

    NONE = "none"
    """Ningún canal devolvió nada dentro del alcance autorizado."""


@dataclass(frozen=True, slots=True)
class ChannelHit:
    """Posición que un canal dio a un pasaje. El rango empieza en 1."""

    channel: Channel
    rank: int
    score: float
    """Puntuación **propia del canal**, incomparable entre canales."""


@dataclass(frozen=True, slots=True)
class Evidence:
    provenance: ChunkProvenance
    hits: tuple[ChannelHit, ...]
    fused_score: float
    rank: int

    @property
    def channels(self) -> tuple[Channel, ...]:
        return tuple(hit.channel for hit in self.hits)

    @property
    def found_by_multiple_channels(self) -> bool:
        return len({hit.channel for hit in self.hits}) > 1

    @property
    def has_exact_match(self) -> bool:
        return any(hit.channel is Channel.EXACT for hit in self.hits)

    @property
    def scope(self) -> Scope:
        return self.provenance.scope

    def citation(self) -> str:
        return self.provenance.citation()


@dataclass(frozen=True, slots=True)
class EvidenceSet:
    """Resultado completo de una recuperación, con su fuerza declarada."""

    evidence: tuple[Evidence, ...]
    strength: EvidenceStrength
    channels_queried: tuple[Channel, ...]
    identifiers_detected: tuple[str, ...]

    def __len__(self) -> int:
        return len(self.evidence)

    def __iter__(self) -> Iterator[Evidence]:
        return iter(self.evidence)

    @property
    def is_empty(self) -> bool:
        return not self.evidence

    def top(self, count: int) -> Sequence[Evidence]:
        return self.evidence[:count]


ScoredProvenance = tuple[ChunkProvenance, float]
"""Un pasaje con la puntuación **propia** del canal que lo encontró."""


@runtime_checkable
class EvidenceRetrievalPort(Protocol):
    """Recuperar evidencia autorizada para una consulta.

    Lo implementa el servicio híbrido del Bloque 4.3. Existe como puerto para
    que la capa de generación dependa del contrato y no de aquella clase: el
    RAG no debe saber si detrás hay tres canales, uno o cinco, y menos aún
    heredar sus dependencias de PostgreSQL para poder probarse.

    Los alcances entran por la firma y no tienen valor por defecto, igual que
    en los canales: quien recupera sin decir para quién, no recupera.
    """

    async def search(
        self, *, query: str, scopes: Sequence[Scope], limit: int = 10
    ) -> "EvidenceSet":
        """Evidencia autorizada, ya fusionada y ordenada."""
        ...


@runtime_checkable
class LexicalSearchPort(Protocol):
    """Canales exacto y léxico. El alcance es obligatorio en los dos.

    Igual que en el puerto vectorial, los alcances entran por la firma: no
    existe la variante que recupera de todo el corpus y filtra después.
    """

    async def search_exact(
        self, *, identifiers: Sequence[str], scopes: Sequence[Scope], limit: int = 10
    ) -> tuple[ScoredProvenance, ...]:
        """Pasajes que contienen literalmente alguno de los identificadores."""
        ...

    async def search_lexical(
        self, *, query: str, scopes: Sequence[Scope], limit: int = 10
    ) -> tuple[ScoredProvenance, ...]:
        """Pasajes cuyo texto responde a la consulta, con lematización."""
        ...
