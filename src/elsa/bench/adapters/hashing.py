"""Control determinista: embeddings por hash de n-gramas.

**No es un modelo y no compite con ninguno.** Es el suelo del banco: un
vector que solo captura coincidencia de caracteres, sin ninguna semántica.
Existe por tres razones concretas:

1. **Prueba que el banco funciona** sin descargar un gigabyte. Si las
   métricas de este control salen coherentes —alto en códigos, bajo en
   sinónimos— el arnés está midiendo lo que dice medir.
2. **Fija el suelo.** Un candidato denso que no supere claramente a esto en
   el eje de sinónimos no está aportando semántica.
3. **Hace el banco ejecutable en CI**, donde no hay ni red ni GPU.

Cualquier informe que lo incluya lo marca como control. Sustituir la
medición de un modelo real por este número sería exactamente lo que la
regla 21 de `CLAUDE.md` prohíbe.
"""

import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = ["HashingEmbedder"]

_WORD = re.compile(r"[0-9a-záéíóúüñ]+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class _Description:
    model_name: str
    revision: str
    dimension: int
    normalized: bool
    document_prefix: str
    query_prefix: str
    runtime: str
    device: str


class HashingEmbedder:
    """Proyecta n-gramas de caracteres en un espacio fijo por hash."""

    def __init__(self, dimension: int = 256, ngram: int = 4) -> None:
        self._dimension = dimension
        self._ngram = ngram

    def describe(self) -> _Description:
        return _Description(
            model_name="control-hashing-ngrams",
            revision=f"n{self._ngram}-d{self._dimension}",
            dimension=self._dimension,
            normalized=True,
            document_prefix="",
            query_prefix="",
            runtime="pure-python",
            device="cpu",
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        # El control no usa prefijos: no tiene con qué distinguirlos. Que las
        # dos operaciones existan igual es lo que mantiene el contrato.
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        folded = _fold(text)
        vector = [0.0] * self._dimension
        for token in _WORD.findall(folded):
            padded = f" {token} "
            for index in range(max(1, len(padded) - self._ngram + 1)):
                gram = padded[index : index + self._ngram]
                digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
                bucket = int.from_bytes(digest, "big") % self._dimension
                vector[bucket] += 1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
