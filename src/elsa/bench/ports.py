"""Interfaz de evaluación del banco. **No es el puerto productivo.**

`elsa.ports.embeddings` es el puerto que usará el flujo real de ELSA. Este
es otro, a propósito:

- Distingue **documento** de **consulta**. No es un detalle: BGE-M3 no pide
  prefijo, EmbeddingGemma exige `title: none | text:` para el pasaje y
  `task: search result | query:` para la consulta, y Qwen3-Embedding es
  *instruction-aware*. Un banco que embebiera las dos cosas igual mediría
  mal a dos de los tres candidatos, y el error favorecería sistemáticamente
  al que no usa prefijos.
- Obliga a declarar con qué se midió (`describe`). Un número sin modelo,
  revisión, dimensión, normalización y prefijos no es un resultado: es un
  número.
- No le importa la latencia al runtime, y aquí sí.

Fundir las dos interfaces habría atado el runtime a las necesidades de un
banco de pruebas.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

__all__ = ["BenchmarkEmbedder", "EmbedderDescription", "ModelUnavailableError"]


class ModelUnavailableError(Exception):
    """El modelo no se pudo cargar: falta la dependencia o los pesos.

    Se distingue de cualquier otro fallo porque tiene una consecuencia
    concreta en el informe: ese candidato queda **sin medir**, y sin medir no
    se descarta ni se elige. No se sustituye por una puntuación pública.
    """


class EmbedderDescription(Protocol):
    """Lo que un adaptador tiene que poder decir de sí mismo."""

    @property
    def model_name(self) -> str: ...
    @property
    def revision(self) -> str: ...
    @property
    def dimension(self) -> int: ...
    @property
    def normalized(self) -> bool: ...
    @property
    def document_prefix(self) -> str: ...
    @property
    def query_prefix(self) -> str: ...
    @property
    def runtime(self) -> str: ...
    @property
    def device(self) -> str: ...


@runtime_checkable
class BenchmarkEmbedder(Protocol):
    """Un candidato medible.

    Las dos operaciones son distintas y no se pueden intercambiar: pasar un
    pasaje por `embed_queries` mediría el modelo con el prefijo equivocado.
    """

    def describe(self) -> EmbedderDescription: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectores de pasajes, con el prefijo o instrucción de documento."""
        ...

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectores de consultas, con el prefijo o instrucción de consulta."""
        ...
