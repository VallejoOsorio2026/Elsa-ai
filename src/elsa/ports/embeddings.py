"""Puerto productivo de embeddings.

**Documento y consulta no se embeben igual.** BGE-M3 no usa prefijo;
EmbeddingGemma exige `title: none | text: ` delante del pasaje y
`task: search result | query: ` delante de la pregunta; Qwen3 es
*instruction-aware*. Un puerto con una sola operación simétrica obligaría a
elegir cuál de los dos usos queda mal servido, y el error no daría ninguna
señal: mediría peor sin fallar. Por eso el puerto tiene dos operaciones, y por
eso el banco de 4.2.a ya las distinguía.

El puerto **no conoce alcances ni permisos**, y no debe: la autorización la
aplica la consulta de recuperación (regla 3, ADR 0014). Aquí solo entra texto
y sale un vector.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "EmbeddingConfigurationError",
    "EmbeddingDimensionError",
    "EmbeddingModelDescriptor",
    "EmbeddingsPort",
    "InferenceError",
    "ModelUnavailableError",
]


class EmbeddingConfigurationError(ValueError):
    """La configuración no describe un espacio vectorial reproducible."""


class ModelUnavailableError(Exception):
    """El modelo no se pudo cargar: no está descargado, o falta autenticación."""


class EmbeddingDimensionError(ValueError):
    """El adaptador emitió una dimensión distinta de la declarada.

    Nunca se trunca ni se rellena: un vector de otra dimensión pertenece a
    otro espacio vectorial, y adaptarlo en silencio produciría un índice que
    parece correcto y ordena mal.
    """


class InferenceError(Exception):
    """El modelo estaba cargado y aun así falló al vectorizar."""


@dataclass(frozen=True, slots=True)
class EmbeddingModelDescriptor:
    """Identidad del espacio vectorial que produce un adaptador.

    Es lo que `embedding_models` necesita para reproducirlo, y lo que hace
    comparables dos corridas. `revision` tiene que ser un commit o digest
    concreto: `main` es una referencia móvil y ADR 0013 §2 la prohíbe.
    """

    model_id: str
    revision: str
    dimension: int
    normalized: bool
    composition_template: str
    runtime: str
    family: str
    document_prefix: str = ""
    query_prefix: str = ""
    similarity: str = "cosine"


@runtime_checkable
class EmbeddingsPort(Protocol):
    """Vectorización de pasajes y de consultas, por caminos distintos."""

    def describe(self) -> EmbeddingModelDescriptor:
        """Identidad del espacio vectorial. No carga el modelo."""
        ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectoriza pasajes ya compuestos, en el mismo orden de entrada."""
        ...

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Vectoriza consultas de usuario, en el mismo orden de entrada."""
        ...
