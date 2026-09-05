"""Adaptador fake del puerto de embeddings (determinista, para tests)."""

import hashlib
from collections.abc import Sequence


class FakeEmbeddingsAdapter:
    """Deriva vectores del hash SHA-256 del texto.

    Determinista entre procesos y plataformas (no usa ``hash()``, que está
    aleatorizado por proceso). Textos iguales producen vectores iguales.
    """

    def __init__(self, dimension: int = 8) -> None:
        if dimension < 1 or dimension > 32:
            raise ValueError("fake embeddings support dimensions between 1 and 32")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Cada byte se normaliza al rango [-1.0, 1.0].
        return [byte / 127.5 - 1.0 for byte in digest[: self._dimension]]
