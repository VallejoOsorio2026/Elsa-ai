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
- **Una corrida interrumpida no queda a medias.** Un fallo la cierra como
  `failed`, con su motivo; un Ctrl+C o una cancelación, como `cancelled`.
  Nunca se cierra como completada. Si el proceso muere sin poder cerrarla, se
  concilia a mano después (`reconcile_run`, ADR 0039).

Y una cuarta, que decide **antes** de escribir nada: solo se embeben versiones
`approved` o `published` (ADR 0013 §7). Una versión pendiente, rechazada o
reemplazada se niega sin abrir ninguna corrida.
"""

import asyncio
import logging
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass

from elsa.documents.composition import compose_for_embedding
from elsa.ports.documents import DocumentRepositoryPort, DocumentVersionState
from elsa.ports.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingsPort,
)
from elsa.ports.vectors import (
    EmbeddingRunRecord,
    IneligibleVersionError,
    PendingEmbedding,
    VectorStorePort,
)

_logger = logging.getLogger(__name__)

__all__ = ["EMBEDDABLE_STATES", "EmbeddingGenerationService", "GenerationOutcome"]

# ADR 0013 §7: `approved` se embebe antes de publicar para validar el índice
# nuevo; la recuperación productiva sigue exigiendo `published`.
EMBEDDABLE_STATES = frozenset({DocumentVersionState.APPROVED, DocumentVersionState.PUBLISHED})


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

        version = await self._documents.get_version(version_id)
        if version is None:
            raise IneligibleVersionError(f"unknown document version: {version_id}")
        if version.state not in EMBEDDABLE_STATES:
            raise IneligibleVersionError(
                f"version {version_id} is {version.state.value}: only approved or published "
                "versions are embedded (ADR 0013 §7)"
            )

        chunks = await self._documents.list_chunks(version_id)
        document = await self._documents.get_document_by_id(version.document_id)
        document_title = None if document is None else document.title
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
            # La prueba de vida de la corrida: mientras este proceso la tiene,
            # `reconcile_run` se niega a cerrarla (ADR 0039).
            async with self._vectors.run_guard(run.id):
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
                reused += len(chunks) - len(pending)
                finished = await self._vectors.finish_run(
                    run_id=run.id, generated=generated, reused=reused
                )
        except (asyncio.CancelledError, KeyboardInterrupt) as error:
            # Ctrl+C o cancelación de la tarea: no es un fallo del modelo ni de
            # la base. La corrida queda `cancelled` y los lotes ya confirmados
            # siguen siendo válidos; repetir reutiliza lo que ya existe.
            await _close_quietly(
                self._vectors.cancel_run(
                    run_id=run.id, message=f"interrupted: {type(error).__name__}"
                ),
                run.id,
            )
            raise
        except Exception as error:
            # La corrida no se queda «en marcha» ni se cierra como completada:
            # queda fallida, con el motivo, y lo que se escribió antes sigue
            # siendo válido —cada lote es su propia transacción.
            await _close_quietly(
                self._vectors.fail_run(
                    run_id=run.id,
                    failure_kind=_failure_kind(error),
                    failure_message=f"{type(error).__name__}: {error}",
                ),
                run.id,
            )
            _logger.warning(
                "embedding run failed",
                extra={"run_id": run.id, "model_id": model_id, "error": type(error).__name__},
            )
            raise

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


async def _close_quietly(closing: Awaitable[object], run_id: str) -> None:
    """Cierra la corrida sin tapar el error original.

    Si cerrarla también falla —la base se ha caído, que suele ser la causa—, la
    corrida queda `running` y se concilia después a mano (ADR 0039). Lo que el
    llamador ve es el error que interrumpió la generación, no este.
    """
    try:
        await closing
    except Exception as error:  # noqa: BLE001 - el error que importa es el original
        _logger.warning(
            "embedding run left running: it must be reconciled",
            extra={"run_id": run_id, "error": type(error).__name__},
        )


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
