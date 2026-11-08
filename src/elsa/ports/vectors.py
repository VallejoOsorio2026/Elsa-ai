"""Puerto del almacenamiento vectorial de ELSA.

La lógica de negocio habla con este puerto, nunca con pgvector ni con un
cliente concreto (regla 6). Lo que el puerto fija, y no es negociable en el
adaptador:

- **Generar no activa.** `store_embeddings` escribe vectores; `activate_model`
  es una operación aparte y atómica (ADR 0013 §5).
- **La recuperación exige los alcances autorizados como argumento.** No existe
  una forma de escribirla que recupere vecinos globales y filtre después: eso
  es la regla 3 de `CLAUDE.md`, hecha inevitable por la firma.
- **El modelo de embeddings nunca decide permisos.** El puerto no le pasa
  identidad ni alcance al modelo: el alcance entra en la consulta.
"""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from elsa.core.authorization import Scope
from elsa.ports.documents import ChunkProvenance

__all__ = [
    "ActiveModelError",
    "EmbeddingModelEvent",
    "EmbeddingModelEventRecord",
    "EmbeddingModelRecord",
    "EmbeddingModelSpec",
    "EmbeddingRunRecord",
    "EmbeddingRunStatus",
    "IneligibleVersionError",
    "ModelState",
    "RunReconciliationError",
    "ScoredChunk",
    "VectorIntegrityError",
    "VectorStorePort",
]


class ModelState(StrEnum):
    REGISTERED = "registered"
    ACTIVE = "active"
    RETIRED = "retired"


class EmbeddingRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EmbeddingModelEvent(StrEnum):
    """Transiciones registradas en el historial del modelo activo (ADR 0039)."""

    ACTIVATED = "activated"
    DEACTIVATED = "deactivated"
    RETIRED = "retired"
    RUN_RECONCILED = "run_reconciled"


class VectorIntegrityError(ValueError):
    """El vector no encaja con el modelo, el chunk o su versión."""


class ActiveModelError(Exception):
    """No se puede activar, o no hay un modelo activo con el que recuperar."""


class IneligibleVersionError(ValueError):
    """La versión documental no admite embeddings: solo `approved` o `published` (ADR 0013 §7)."""


class RunReconciliationError(Exception):
    """La corrida no puede cerrarse a mano: no está en marcha, o no lleva parada lo suficiente."""


@dataclass(frozen=True, slots=True)
class EmbeddingModelSpec:
    """Todo lo que define un espacio vectorial reproducible.

    Dos modelos que difieran en **cualquiera** de estos campos son espacios
    distintos, y sus vectores no son comparables entre sí.
    """

    family: str
    model_id: str
    revision: str
    dimension: int
    normalized: bool
    composition_template: str
    runtime: str
    document_prefix: str = ""
    query_prefix: str = ""
    similarity: str = "cosine"
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingModelRecord:
    id: str
    spec: EmbeddingModelSpec
    state: ModelState
    registered_by: str
    registered_at: datetime
    activated_at: datetime | None = None
    retired_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.state is ModelState.ACTIVE


@dataclass(frozen=True, slots=True)
class EmbeddingRunRecord:
    id: str
    model_id: str
    status: EmbeddingRunStatus
    trigger_source: str
    started_by: str
    started_at: datetime
    finished_at: datetime | None = None
    total_chunks: int = 0
    generated: int = 0
    reused: int = 0
    failed: int = 0
    failure_kind: str | None = None
    failure_message: str | None = None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class EmbeddingModelEventRecord:
    id: str
    seq: int
    event: EmbeddingModelEvent
    model_id: str
    actor: str
    occurred_at: datetime
    previous_model_id: str | None = None
    run_id: str | None = None
    reason: str | None = None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class PendingEmbedding:
    """Un vector listo para escribirse, con el hash del texto que lo produjo."""

    chunk_id: str
    version_id: str
    embedding: Sequence[float]
    embedded_sha256: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ScoredChunk:
    """Un chunk recuperado, con su distancia y su procedencia citable."""

    provenance: ChunkProvenance
    distance: float
    model_id: str

    @property
    def similarity(self) -> float:
        """Similitud coseno. El adaptador entrega distancia; esto la invierte."""
        return 1.0 - self.distance


@runtime_checkable
class VectorStorePort(Protocol):
    """Registro de modelos, corridas, vectores y recuperación exacta."""

    async def register_model(self, spec: EmbeddingModelSpec, *, actor: str) -> EmbeddingModelRecord:
        """Registra un espacio vectorial. Queda **inactivo**: generar no activa."""

    async def get_model(self, model_id: str) -> EmbeddingModelRecord | None: ...

    async def find_model(self, spec: EmbeddingModelSpec) -> EmbeddingModelRecord | None:
        """Busca por identidad del espacio vectorial, no por nombre."""

    async def list_models(self) -> tuple[EmbeddingModelRecord, ...]: ...

    async def get_active_model(self) -> EmbeddingModelRecord | None:
        """El único modelo que participa en la recuperación productiva."""

    async def activate_model(
        self,
        *,
        model_id: str,
        actor: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> EmbeddingModelRecord:
        """Cambia el modelo activo en **una sola transacción**, con su evento.

        No borra los vectores del anterior: volver atrás es activar otra vez,
        no regenerar nada (ADR 0013 §5). Activar el que ya está activo no
        escribe nada.
        """

    async def deactivate_model(
        self, *, model_id: str, actor: str, reason: str, request_id: str | None = None
    ) -> EmbeddingModelRecord:
        """El Ctrl+Z de `activate`: el modelo activo vuelve a `registered` (ADR 0039).

        Deja **ningún modelo activo**, conserva sus vectores y permite volver a
        activarlo. Exige el id del modelo que se cree activo y un motivo: si
        ese modelo no es el activo, o no hay ninguno, se niega sin escribir.
        """

    async def retire_model(
        self,
        *,
        model_id: str,
        actor: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> EmbeddingModelRecord:
        """Retirar es una decisión posterior, explícita e **irreversible**.

        No es un Ctrl+Z: un modelo retirado no vuelve a activarse. Retirar uno
        ya retirado no escribe nada.
        """

    async def list_model_events(
        self, *, model_id: str | None = None, limit: int = 100
    ) -> tuple[EmbeddingModelEventRecord, ...]:
        """El historial del modelo activo, en orden de ocurrencia."""

    async def start_run(
        self,
        *,
        model_id: str,
        started_by: str,
        trigger_source: str = "manual",
        total_chunks: int = 0,
        request_id: str | None = None,
    ) -> EmbeddingRunRecord: ...

    async def finish_run(
        self, *, run_id: str, generated: int, reused: int, failed: int = 0
    ) -> EmbeddingRunRecord: ...

    async def fail_run(
        self, *, run_id: str, failure_kind: str, failure_message: str
    ) -> EmbeddingRunRecord: ...

    async def cancel_run(self, *, run_id: str, message: str) -> EmbeddingRunRecord:
        """Cierra como `cancelled` una corrida interrumpida por el propio proceso."""

    async def get_run(self, run_id: str) -> EmbeddingRunRecord | None: ...

    async def list_runs(
        self, *, status: EmbeddingRunStatus | None = None, limit: int = 50
    ) -> tuple[EmbeddingRunRecord, ...]: ...

    def run_guard(self, run_id: str) -> AbstractAsyncContextManager[None]:
        """La prueba de vida de una corrida, mientras dura.

        Quien genera la mantiene abierta de principio a fin. Si su proceso o su
        conexión mueren, la base la suelta sola: es lo que `reconcile_run`
        consulta para saber que nadie sigue escribiendo.
        """

    async def reconcile_run(
        self,
        *,
        run_id: str,
        actor: str,
        reason: str,
        idle_minutes: int,
        request_id: str | None = None,
    ) -> EmbeddingRunRecord:
        """Cierra a mano una corrida que quedó `running` porque su proceso murió.

        Exige las dos condiciones: que **ninguna sesión** mantenga su
        `run_guard` y que lleve al menos `idle_minutes` sin escribir ningún
        vector. La antigüedad sola no prueba que el proceso terminó. La
        corrida pasa a `cancelled` y el cierre queda en el historial, con
        actor y motivo. Los vectores ya confirmados no se tocan.
        """

    async def store_embeddings(
        self, *, run_id: str, embeddings: Sequence[PendingEmbedding]
    ) -> tuple[int, int]:
        """Escribe los vectores de una corrida. Devuelve `(generados, reutilizados)`.

        **Idempotente por el hash del texto embebido**: si el chunk ya tiene un
        vector de este modelo con el mismo `embedded_sha256`, no se recalcula
        ni se reescribe. Si el hash cambió, la fila se reemplaza dentro de la
        misma transacción: el vector viejo de *ese* modelo deja de servir,
        mientras los de **otros** modelos siguen intactos.
        """

    async def stale_chunks(
        self, *, model_id: str, expected: Sequence[tuple[str, str]]
    ) -> tuple[str, ...]:
        """De `(chunk_id, embedded_sha256)`, cuáles hay que (re)generar.

        Un embedding está obsoleto si no existe para ese modelo o si su hash
        no coincide con el del texto que hoy se compondría (ADR 0013 §4).
        """

    async def search(
        self,
        *,
        query_embedding: Sequence[float],
        scopes: Sequence[Scope],
        limit: int = 10,
    ) -> tuple[ScoredChunk, ...]:
        """Recuperación vectorial **exacta** sobre lo que el alcance autoriza.

        Los alcances son obligatorios, y el filtro se aplica en la misma
        consulta que ordena por distancia: dominio → activo autorizado →
        versión publicada → chunk elegible → modelo activo. Nunca se traen
        vecinos globales para filtrarlos después (regla 3).
        """

    async def check_health(self) -> None: ...
