"""Adaptador determinista del puerto de embeddings, para pruebas.

Determinista entre procesos y plataformas: deriva el vector del SHA-256 del
texto, no de `hash()`, que está aleatorizado por proceso.

**Asimétrico a propósito**, igual que el puerto: un pasaje y una consulta
recorren caminos distintos y producen vectores distintos aunque el texto sea
el mismo. Un fake simétrico dejaría pasar en las pruebas exactamente el error
que el puerto existe para evitar.
"""

import hashlib
import math
from collections.abc import Sequence

from elsa.ports.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingModelDescriptor,
)

_MAX_DIMENSION = 4096


class FakeEmbeddingsAdapter:
    def __init__(
        self,
        dimension: int = 8,
        *,
        model_id: str = "fake/deterministic",
        revision: str = "fake-0001",
        document_prefix: str = "passage: ",
        query_prefix: str = "query: ",
        composition_template: str = "context-v1",
    ) -> None:
        if dimension < 1 or dimension > _MAX_DIMENSION:
            raise EmbeddingConfigurationError(
                f"fake embeddings support dimensions between 1 and {_MAX_DIMENSION}"
            )
        self._descriptor = EmbeddingModelDescriptor(
            model_id=model_id,
            revision=revision,
            dimension=dimension,
            normalized=True,
            composition_template=composition_template,
            runtime="fake",
            family="fake",
            document_prefix=document_prefix,
            query_prefix=query_prefix,
        )

    def describe(self) -> EmbeddingModelDescriptor:
        return self._descriptor

    @property
    def dimension(self) -> int:
        return self._descriptor.dimension

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        prefix = self._descriptor.document_prefix
        return [self._embed_one(f"{prefix}{text}") for text in texts]

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        prefix = self._descriptor.query_prefix
        return [self._embed_one(f"{prefix}{text}") for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        dimension = self._descriptor.dimension
        raw: list[float] = []
        counter = 0
        # Se extiende el material del hash hasta cubrir la dimensión pedida,
        # en vez de limitar la dimensión a 32 bytes: el adaptador real produce
        # 768 o 1024, y las pruebas tienen que poder usar esas medidas.
        while len(raw) < dimension:
            digest = hashlib.sha256(f"{counter}\x1e{text}".encode()).digest()
            raw.extend(byte / 127.5 - 1.0 for byte in digest)
            counter += 1
        vector = raw[:dimension]
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]
