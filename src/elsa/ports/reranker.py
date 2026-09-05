"""Puerto de reranking.

Reordena documentos candidatos por relevancia frente a una consulta. El
modelo concreto (candidato: BGE reranker) está abierto.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class RankedDocument:
    """Referencia a un documento de entrada con su puntaje de relevancia."""

    index: int
    """Posición del documento en la secuencia de entrada."""

    score: float
    """Relevancia; mayor es más relevante."""


@runtime_checkable
class RerankerPort(Protocol):
    """Reordenamiento de candidatos por relevancia."""

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_k: int | None = None,
    ) -> list[RankedDocument]:
        """Devuelve los documentos ordenados por ``score`` descendente.

        Si ``top_k`` es ``None`` devuelve todos; si no, a lo sumo ``top_k``.
        """
        ...
