"""Puerto de embeddings.

El modelo concreto (EmbeddingGemma vs BGE-M3) está abierto; la dimensión la
declara el adaptador para que el esquema vectorial pueda validarse contra
ella cuando exista.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsPort(Protocol):
    """Vectorización de textos para búsqueda semántica."""

    @property
    def dimension(self) -> int:
        """Dimensión de los vectores que produce este modelo."""
        ...

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Devuelve un vector por texto, en el mismo orden de entrada."""
        ...
