"""Camino de consulta: pregunta del usuario → vector → recuperación autorizada.

Este servicio **no decide permisos y no puede hacerlo**: recibe los alcances ya
resueltos y se los pasa al repositorio vectorial, que los aplica dentro de la
misma consulta que ordena por distancia. El modelo de embeddings solo convierte
texto en un vector; no sabe quién pregunta ni qué puede ver (ADR 0014).

Tampoco genera respuestas. Devuelve evidencia recuperada con su procedencia:
qué se hace con ella es el Bloque 4.3, no este.
"""

import logging
from collections.abc import Sequence

from elsa.core.authorization import Scope
from elsa.ports.embeddings import EmbeddingsPort
from elsa.ports.vectors import ScoredChunk, VectorStorePort

_logger = logging.getLogger(__name__)

__all__ = ["SemanticRetrievalService"]


class SemanticRetrievalService:
    def __init__(self, *, vectors: VectorStorePort, embeddings: EmbeddingsPort) -> None:
        self._vectors = vectors
        self._embeddings = embeddings

    async def search(
        self, *, question: str, scopes: Sequence[Scope], limit: int = 10
    ) -> tuple[ScoredChunk, ...]:
        """Recupera los chunks autorizados más cercanos a la pregunta.

        `scopes` es obligatorio y no tiene valor por defecto: una recuperación
        sin alcances no devuelve «todo», devuelve nada. Es la regla 3 escrita
        en la firma, para que no dependa de que alguien se acuerde.
        """
        if not question.strip() or not scopes or limit <= 0:
            return ()
        # La consulta recorre `embed_queries`, no `embed_documents`: con un
        # modelo asimétrico son prefijos distintos, y confundirlos degrada la
        # recuperación sin dar ningún error.
        vectors = await self._embeddings.embed_queries([question])
        return await self._vectors.search(query_embedding=vectors[0], scopes=scopes, limit=limit)
