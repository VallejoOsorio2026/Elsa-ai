"""Generación de embeddings documentales: del chunk al vector persistido.

El camino completo, y cada paso está donde debe:

    chunk → `context-v1` → `embedded_sha256` → ¿hace falta? → modelo → persistencia

Tres reglas que este servicio hace cumplir y que no puede saltarse ningún
llamador:

- **Generar no activa.** Este servicio escribe vectores y cierra la corrida.
  Qué modelo participa en la recuperación es una decisión administrativa
  aparte (ADR 0013 §5).
- **Lo que no cambió no se recalcula.** El `embedded_sha256` del texto
  compuesto decide qué hace falta, sin releer el documento (ADR 0013 §4).
- **Una corrida interrumpida queda `failed`, no a medias.** Un fallo se
  registra con su motivo; nunca se cierra como completada.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from elsa.documents.composition import compose_for_embedding
from elsa.ports.documents import DocumentRepositoryPort
from elsa.ports.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingsPort,
)
from elsa.ports.vectors import (
    EmbeddingRunRecord,
    PendingEmbedding,
    VectorStorePort,
)

_logger = logging.getLogger(__name__)

__all__ = ["EmbeddingGenerationService", "GenerationOutcome"]


@dataclass(frozen=True, slots=True)
class GenerationOutcome:
    run: EmbeddingRunRecord
    generated: int
    reused: int
    considered: int


class EmbeddingGenerationService:
    def __init__(
        self,
        *,
        documents: DocumentRepositoryPort,
        vectors: VectorStorePort,
        embeddings: EmbeddingsPort,
        batch_size: int = 16,
    ) -> None:
        if batch_size < 1:
            raise EmbeddingConfigurationError("batch size must be a positive integer")
        self._documents = documents
        self._vectors = vectors
        self._embeddings = embeddings
        self._batch_size = batch_size

    async def generate_for_version(
        self,
        *,
        model_id: str,
        version_id: str,
        actor: str,
        trigger_source: str = "manual",
        request_id: str | None = None,
    ) -> GenerationOutcome:
        """Embebe los chunks de una versión bajo el modelo indicado.

        El modelo tiene que estar **registrado**, y su identidad tiene que
        coincidir con la del adaptador: embeber con un modelo y anotarlo como
        otro produciría un índice que miente sobre su propio espacio vectorial.
        """
        model = await self._vectors.get_model(model_id)
        if model is None:
            raise EmbeddingConfigurationError(f"unknown embedding model: {model_id}")
        self._assert_same_vector_space(model)

        chunks = await self._documents.list_chunks(version_id)
        document_title = await self._document_title(version_id)
        composed = {
            chunk.id: compose_for_embedding(
                content=chunk.content,
                document_title=document_title,
                heading_trail=chunk.heading_trail,
            )
            for chunk in chunks
        }
        # Se le pregunta al repositorio vectorial, no se supone: él sabe qué
        # hay guardado y con qué hash.
        stale = set(
            await self._vectors.stale_chunks(
                model_id=model_id,
                expected=[(chunk.id, composed[chunk.id].embedded_sha256) for chunk in chunks],
            )
        )
        pending = [chunk for chunk in chunks if chunk.id in stale]

        run = await self._vectors.start_run(
            model_id=model_id,
            started_by=actor,
            trigger_source=trigger_source,
            total_chunks=len(chunks),
            request_id=request_id,
        )
        generated = reused = 0
        try:
            for batch in _batched(pending, self._batch_size):
                texts = [composed[chunk.id].text for chunk in batch]
                vectors = await self._embeddings.embed_documents(texts)
                written, skipped = await self._vectors.store_embeddings(
                    run_id=run.id,
                    embeddings=[
                        PendingEmbedding(
                            chunk_id=chunk.id,
                            version_id=chunk.version_id,
                            embedding=vector,
                            embedded_sha256=composed[chunk.id].embedded_sha256,
                            content_sha256=chunk.content_sha256,
                        )
                        for chunk, vector in zip(batch, vectors, strict=True)
                    ],
                )
                generated += written
                reused += skipped
        except Exception as error:
            # La corrida no se queda «en marcha» ni se cierra como completada:
            # queda fallida, con el motivo, y lo que se escribió antes sigue
            # siendo válido —cada lote es su propia transacción.
            await self._vectors.fail_run(
                run_id=run.id,
                failure_kind=_failure_kind(error),
                failure_message=f"{type(error).__name__}: {error}",
            )
            _logger.warning(
                "embedding run failed",
                extra={"run_id": run.id, "model_id": model_id, "error": type(error).__name__},
            )
            raise

        reused += len(chunks) - len(pending)
        finished = await self._vectors.finish_run(run_id=run.id, generated=generated, reused=reused)
        return GenerationOutcome(
            run=finished, generated=generated, reused=reused, considered=len(chunks)
        )

    def _assert_same_vector_space(self, model: object) -> None:
        descriptor = self._embeddings.describe()
        spec = getattr(model, "spec", None)
        if spec is None:  # pragma: no cover - defensivo
            return
        mismatches = [
            name
            for name in (
                "model_id",
                "revision",
                "dimension",
                "normalized",
                "composition_template",
                "document_prefix",
                "query_prefix",
            )
            if getattr(spec, name) != getattr(descriptor, name)
        ]
        if mismatches:
            raise EmbeddingConfigurationError(
                "the configured adapter does not produce the registered vector space; "
                f"differs in: {', '.join(mismatches)}"
            )

    async def _document_title(self, version_id: str) -> str | None:
        version = await self._documents.get_version(version_id)
        if version is None:
            return None
        document = await self._documents.get_document_by_id(version.document_id)
        return None if document is None else document.title


def _batched[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def _failure_kind(error: Exception) -> str:
    from elsa.ports.embeddings import (
        EmbeddingDimensionError,
        InferenceError,
        ModelUnavailableError,
    )
    from elsa.ports.knowledge import KnowledgeUnavailableError
    from elsa.ports.vectors import VectorIntegrityError

    if isinstance(error, ModelUnavailableError):
        return "model"
    if isinstance(error, EmbeddingDimensionError | EmbeddingConfigurationError):
        return "model"
    if isinstance(error, InferenceError):
        return "model"
    if isinstance(error, KnowledgeUnavailableError | VectorIntegrityError):
        return "database"
    if isinstance(error, TimeoutError):
        return "timeout"
    return "unknown"
