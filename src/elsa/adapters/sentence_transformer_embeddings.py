"""Adaptador productivo para modelos compatibles con SentenceTransformers.

Tres decisiones que este adaptador encarna, y que no son detalles:

**Nada del modelo está codificado aquí.** `model_id`, revisión, dimensión,
normalización, dispositivo y los dos prefijos vienen de la configuración. BGE-M3
es el primer modelo que se habilitará, no un supuesto estructural: cambiar a
EmbeddingGemma cuando su licencia se valide es configuración, no código
(ADR 0015).

**El modelo se carga la primera vez que se usa, no al construir.** ELSA arranca
en Render Free, donde no caben ni los pesos ni la CPU para cargarlos
(ADR 0013 §8). Construir este adaptador no debe descargar ni cargar nada; si
nadie llama a `embed_*`, el modelo nunca se carga.

**La dimensión se verifica contra la declarada, en cada llamada.** Un vector de
otra medida pertenece a otro espacio vectorial. No se trunca ni se rellena.
"""

import asyncio
import logging
from collections.abc import Sequence
from typing import Any

from elsa.ports.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingDimensionError,
    EmbeddingModelDescriptor,
    InferenceError,
    ModelUnavailableError,
)

_logger = logging.getLogger(__name__)

# Una referencia móvil no identifica un espacio vectorial: lo que se descargue
# mañana puede no ser lo que se midió (ADR 0013 §2).
_MOVING_REFERENCES = frozenset({"main", "master", "head", "latest", ""})


class SentenceTransformerEmbeddings:
    """Puerto de embeddings servido por `sentence-transformers`."""

    def __init__(
        self,
        *,
        model_id: str,
        revision: str,
        dimension: int,
        normalized: bool = True,
        document_prefix: str = "",
        query_prefix: str = "",
        composition_template: str = "context-v1",
        family: str = "",
        device: str = "cpu",
        batch_size: int = 16,
        trust_remote_code: bool = False,
    ) -> None:
        if revision.strip().lower() in _MOVING_REFERENCES:
            raise EmbeddingConfigurationError(
                f"revision {revision!r} is a moving reference: a production model must pin "
                "a concrete commit or digest (ADR 0013 §2)"
            )
        if dimension < 1:
            raise EmbeddingConfigurationError("dimension must be a positive integer")
        if batch_size < 1:
            raise EmbeddingConfigurationError("batch size must be a positive integer")
        self._descriptor = EmbeddingModelDescriptor(
            model_id=model_id,
            revision=revision,
            dimension=dimension,
            normalized=normalized,
            composition_template=composition_template,
            runtime="sentence-transformers",
            family=family or model_id.split("/")[0].lower(),
            document_prefix=document_prefix,
            query_prefix=query_prefix,
        )
        self._device = device
        self._batch_size = batch_size
        self._trust_remote_code = trust_remote_code
        self._model: Any = None
        self._lock = asyncio.Lock()

    def describe(self) -> EmbeddingModelDescriptor:
        return self._descriptor

    @property
    def batch_size(self) -> int:
        return self._batch_size

    async def _load(self) -> Any:
        """Carga perezosa y una sola vez, aunque llamen dos corrutinas a la vez."""
        if self._model is not None:
            return self._model
        async with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as error:
                raise ModelUnavailableError(
                    "sentence-transformers is not installed: this deployment cannot run a "
                    "local embedding model (install the 'embeddings' extra)"
                ) from error
            try:
                # `trust_remote_code` explícito: descargar y ejecutar código
                # arbitrario del repositorio del modelo no puede ser un
                # descuido, y por defecto no se hace.
                model = await asyncio.to_thread(
                    SentenceTransformer,
                    self._descriptor.model_id,
                    revision=self._descriptor.revision,
                    device=self._device,
                    trust_remote_code=self._trust_remote_code,
                )
            except Exception as error:  # noqa: BLE001 - la causa la da el mensaje
                raise ModelUnavailableError(
                    f"could not load {self._descriptor.model_id} "
                    f"at revision {self._descriptor.revision}: {type(error).__name__}"
                ) from error
            self._model = model
            _logger.info(
                "embedding model loaded",
                extra={
                    "model_id": self._descriptor.model_id,
                    "revision": self._descriptor.revision,
                    "device": self._device,
                },
            )
            return model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts, self._descriptor.document_prefix)

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed(texts, self._descriptor.query_prefix)

    async def _embed(self, texts: Sequence[str], prefix: str) -> list[list[float]]:
        if not texts:
            return []
        model = await self._load()
        prepared = [f"{prefix}{text}" for text in texts]
        try:
            raw = await asyncio.to_thread(
                model.encode,
                prepared,
                batch_size=self._batch_size,
                normalize_embeddings=self._descriptor.normalized,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        except Exception as error:  # noqa: BLE001 - se traduce al error del puerto
            raise InferenceError(
                f"{self._descriptor.model_id} failed while embedding "
                f"{len(texts)} texts: {type(error).__name__}"
            ) from error
        vectors = [[float(value) for value in row] for row in raw]
        expected = self._descriptor.dimension
        for index, vector in enumerate(vectors):
            if len(vector) != expected:
                raise EmbeddingDimensionError(
                    f"{self._descriptor.model_id} emitted {len(vector)} dimensions for text "
                    f"{index}, but the configured model declares {expected}. The vector is not "
                    "truncated or padded: it belongs to a different vector space"
                )
        return vectors
