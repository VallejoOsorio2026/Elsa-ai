"""Puerto del conocimiento técnico de ELSA.

Única vía por la que el backend lee y escribe activos técnicos,
componentes, versiones del BOM de Ingeniería, snapshots de SAP,
reconciliaciones y validaciones.

Las operaciones son **agregadas y atómicas** a propósito. Guardar una
versión del BOM no es «insertar filas»: es una operación que entra entera o
no entra, porque una versión a medias sería una mentira sobre lo que
Ingeniería aprobó. Lo mismo vale para publicar. Por eso el puerto no expone
un ``insert_item``: expone ``store_engineering_version``.

Reglas que el puerto hace cumplibles:

- Un archivo ya importado se reconoce por su hash y no genera una versión
  duplicada.
- Una importación fallida no toca la última versión publicada.
- Solo hay una versión publicada vigente por activo, y publicar es atómico.
- Un snapshot de SAP nunca se convierte en BOM publicado.
- Ninguna validación se borra: revertir añade un registro.
- La reconciliación no modifica ninguna de las dos fuentes.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from elsa.core.matching import MatchCandidate
from elsa.core.reconciliation import ReconciliationEntry
from elsa.core.review import ReviewDecision, ReviewSubject
from elsa.ingestion.model import (
    ParsedBomRow,
    ParsedDrawingImage,
    ParsedFailureMode,
    ParsedOptionRow,
    ParsedSapSnapshot,
    ParsedSodCriterion,
)

__all__ = [
    "AssetAlreadyExistsError",
    "AssetNotFoundError",
    "BomItemRecord",
    "ComponentRecord",
    "DrawingImageRecord",
    "DuplicateSourceError",
    "EngineeringVersionInput",
    "EngineeringVersionRecord",
    "FailureModeRecord",
    "ImportKind",
    "ImportRecord",
    "ImportStatus",
    "KnowledgeRepositoryPort",
    "KnowledgeUnavailableError",
    "NotPublishableError",
    "ReconciliationItemRecord",
    "ReconciliationRunRecord",
    "ResolvedBomRow",
    "ReviewRecord",
    "SapSnapshotItemRecord",
    "SapSnapshotRecord",
    "SodCriterionRecord",
    "SourceArtifactRecord",
    "SubjectNotFoundError",
    "TechnicalAssetRecord",
    "VersionState",
]


# ---------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------


class KnowledgeUnavailableError(Exception):
    """El almacén de conocimiento no responde → 503."""


class AssetNotFoundError(Exception):
    """No existe ese activo técnico."""


class AssetAlreadyExistsError(Exception):
    """Ya existe un activo con ese código."""


class SubjectNotFoundError(Exception):
    """No existe la versión, importación, snapshot o validación indicada."""


class DuplicateSourceError(Exception):
    """Ese archivo exacto ya se importó antes.

    Lleva la importación original para poder devolverla en vez de crear una
    versión duplicada por un doble clic o un reintento de red.
    """

    def __init__(self, message: str, existing_import_id: str | None = None) -> None:
        super().__init__(message)
        self.existing_import_id = existing_import_id


class NotPublishableError(Exception):
    """La versión no cumple los criterios para publicarse."""


# ---------------------------------------------------------------------
# Enumeraciones (reflejan las restricciones de la migración)
# ---------------------------------------------------------------------


class ImportKind(StrEnum):
    ENGINEERING_BOM = "engineering_bom"
    SAP_SNAPSHOT = "sap_snapshot"


class ImportStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class VersionState(StrEnum):
    PENDING_VALIDATION = "pending_validation"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


# ---------------------------------------------------------------------
# Registros de lectura
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TechnicalAssetRecord:
    """Activo Técnico. ``(domain, code)`` es su alcance de autorización."""

    id: str
    code: str
    name: str
    domain: str
    description: str | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class ComponentRecord:
    """Identidad interna del componente. El UUID no cambia nunca."""

    id: str
    asset_id: str
    subsystem_id: str | None = None
    subsystem_name: str | None = None
    retired_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class SourceArtifactRecord:
    """Metadato del archivo original. Los bytes están en el almacenamiento."""

    id: str
    kind: str
    sha256: str
    byte_size: int
    storage_key: str
    uploaded_by: str
    uploaded_at: datetime
    original_filename: str | None = None
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class ImportRecord:
    """Una ejecución de ingesta y cómo terminó."""

    id: str
    asset_id: str
    source_artifact_id: str
    kind: ImportKind
    status: ImportStatus
    started_by: str
    started_at: datetime
    failure_kind: str | None = None
    failure_message: str | None = None
    request_id: str | None = None
    finished_at: datetime | None = None
    stats: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EngineeringVersionRecord:
    """Una versión histórica del BOM de Ingeniería."""

    id: str
    asset_id: str
    import_id: str
    source_artifact_id: str
    version_number: int
    state: VersionState
    created_at: datetime
    published_at: datetime | None = None
    published_by: str | None = None
    superseded_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class BomItemRecord:
    """Un renglón almacenado del BOM de Ingeniería."""

    id: str
    version_id: str
    source_row: int
    component_id: str | None = None
    subsystem_name: str | None = None
    position: str | None = None
    component_name: str | None = None
    sap_code: str | None = None
    sap_code_original: str | None = None
    technical_description: str | None = None
    quantity: Decimal | None = None
    quantity_original: str | None = None
    unit: str | None = None
    model_reference: str | None = None
    assembly_drawing: str | None = None
    drawing_reference: str | None = None
    bom_update_flag: str | None = None
    inventory_strategy: str | None = None
    stock_max: Decimal | None = None
    stock_min: Decimal | None = None
    source_stock: Decimal | None = None
    remarks: str | None = None
    match_rule: str | None = None
    match_confidence: str = "unresolved"
    change_kind: str | None = None
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FailureModeRecord:
    """Un renglón del AMEF. ``rpn`` siempre lo calculó el backend."""

    id: str
    version_id: str
    source_row: int
    component_id: str | None = None
    subsystem_name: str | None = None
    component_name: str | None = None
    sap_code: str | None = None
    failure_mode: str | None = None
    effect: str | None = None
    cause: str | None = None
    severity: int | None = None
    occurrence: int | None = None
    detection: int | None = None
    rpn: int | None = None
    action: str | None = None
    preventive_plan: str | None = None
    corrective_action: str | None = None
    remarks: str | None = None
    match_rule: str | None = None
    match_confidence: str = "unresolved"
    change_kind: str | None = None


@dataclass(frozen=True, slots=True)
class SodCriterionRecord:
    id: str
    version_id: str
    dimension: str
    source_row: int
    scale_value: int | None = None
    label: str | None = None
    description: str | None = None
    range_low: Decimal | None = None
    range_high: Decimal | None = None


@dataclass(frozen=True, slots=True)
class DrawingImageRecord:
    """Evidencia gráfica conservada, no interpretada."""

    id: str
    version_id: str
    derived_artifact_id: str
    storage_key: str
    sha256: str
    association_status: str
    drawing_id: str | None = None
    drawing_number: str | None = None
    association_rule: str | None = None
    sheet_name: str | None = None
    anchor: str | None = None
    width_px: int | None = None
    height_px: int | None = None


@dataclass(frozen=True, slots=True)
class SapSnapshotRecord:
    """Cómo se veía SAP en una fecha. Nunca sustituye al BOM publicado."""

    id: str
    asset_id: str
    import_id: str
    source_artifact_id: str
    captured_at: datetime
    functional_location: str | None = None
    description: str | None = None
    valid_from: date | None = None


@dataclass(frozen=True, slots=True)
class SapSnapshotItemRecord:
    id: str
    snapshot_id: str
    source_row: int
    entry_kind: str
    position: str | None = None
    sap_code: str | None = None
    description: str | None = None
    quantity: Decimal | None = None
    quantity_original: str | None = None
    unit: str | None = None
    parent_path: str | None = None
    depth: int = 0
    extra: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReconciliationRunRecord:
    id: str
    asset_id: str
    version_id: str
    snapshot_id: str
    created_by: str
    created_at: datetime
    stats: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReconciliationItemRecord:
    id: str
    run_id: str
    classification: str
    bom_item_id: str | None = None
    snapshot_item_id: str | None = None
    component_id: str | None = None
    sap_code: str | None = None
    engineering_quantity: Decimal | None = None
    sap_quantity: Decimal | None = None
    engineering_unit: str | None = None
    sap_unit: str | None = None
    engineering_description: str | None = None
    sap_description: str | None = None
    detail: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReviewRecord:
    """Una validación. Nunca se modifica ni se borra."""

    id: str
    seq: int
    asset_id: str
    subject_kind: ReviewSubject
    subject_id: str
    decision: ReviewDecision
    reviewer: str
    decided_at: datetime
    comment: str | None = None
    subject_version_id: str | None = None
    reverts_review_id: str | None = None
    inherited_from_id: str | None = None
    request_id: str | None = None


# ---------------------------------------------------------------------
# Entradas de escritura
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolvedBomRow:
    """Un renglón parseado con su decisión de identidad ya tomada.

    - ``component_id`` con valor: se reconoció un componente existente.
    - ``component_id`` nulo y ``ambiguous`` falso: se creará un componente
      nuevo con un UUID propio.
    - ``ambiguous`` verdadero: **no se crea ni se enlaza nada**. El renglón
      se guarda sin componente y queda pendiente de revisión. Crear un
      componente aquí bifurcaría en silencio la identidad de uno que ya
      existe.
    """

    row: ParsedBomRow
    """El renglón tal como lo devolvió el parser."""

    component_id: str | None = None
    ambiguous: bool = False
    match_rule: str | None = None
    match_confidence: str = "unresolved"
    change_kind: str | None = None


@dataclass(frozen=True, slots=True)
class EngineeringVersionInput:
    """Todo lo que compone una versión, para escribirla de una sola vez."""

    asset_id: str
    import_id: str
    source_artifact_id: str
    rows: Sequence[ResolvedBomRow]
    failure_modes: Sequence[ParsedFailureMode] = ()
    sod_criteria: Sequence[ParsedSodCriterion] = ()
    option_rows: Sequence[ParsedOptionRow] = ()
    drawing_images: Sequence[ParsedDrawingImage] = ()
    drawing_storage_keys: Mapping[str, str] = field(default_factory=dict)
    """SHA-256 de cada imagen → clave con la que quedó guardada."""


# ---------------------------------------------------------------------
# Puerto
# ---------------------------------------------------------------------


@runtime_checkable
class KnowledgeRepositoryPort(Protocol):
    """Lectura y escritura del conocimiento técnico de ELSA."""

    # -- Activos ------------------------------------------------------

    async def list_assets(self) -> tuple[TechnicalAssetRecord, ...]: ...

    async def get_asset(self, code: str) -> TechnicalAssetRecord | None: ...

    async def create_asset(
        self,
        *,
        code: str,
        name: str,
        domain: str,
        description: str | None = None,
    ) -> TechnicalAssetRecord:
        """Crea un activo. Lanza :class:`AssetAlreadyExistsError` si ya existe."""
        ...

    # -- Ingesta ------------------------------------------------------

    async def find_import_by_source(self, *, kind: str, sha256: str) -> ImportRecord | None:
        """Importación previa de ese archivo exacto, si la hubo.

        Es el mecanismo de idempotencia: el mismo contenido no vuelve a
        producir una versión.
        """
        ...

    async def start_import(
        self,
        *,
        asset_id: str,
        kind: ImportKind,
        sha256: str,
        byte_size: int,
        storage_key: str,
        uploaded_by: str,
        original_filename: str | None = None,
        content_type: str | None = None,
        request_id: str | None = None,
    ) -> ImportRecord:
        """Registra el archivo y abre la importación, en una transacción.

        Lanza :class:`DuplicateSourceError` si ese contenido ya está
        registrado, incluso si dos peticiones llegan a la vez: la unicidad
        la impone la base, no una comprobación previa.
        """
        ...

    async def fail_import(
        self,
        *,
        import_id: str,
        failure_kind: str,
        failure_message: str,
        actor: str,
        request_id: str | None = None,
    ) -> ImportRecord:
        """Cierra la importación como fallida. No toca la versión publicada."""
        ...

    async def get_import(self, import_id: str) -> ImportRecord | None: ...

    async def list_imports(self, asset_id: str, *, limit: int = 50) -> tuple[ImportRecord, ...]: ...

    # -- Componentes --------------------------------------------------

    async def component_entries(self, asset_id: str) -> tuple[tuple[str, MatchCandidate], ...]:
        """Evidencia observada por componente, para construir el índice."""
        ...

    async def list_components(self, asset_id: str) -> tuple[ComponentRecord, ...]: ...

    # -- Versiones de Ingeniería --------------------------------------

    async def store_engineering_version(
        self, data: EngineeringVersionInput, *, actor: str, request_id: str | None = None
    ) -> EngineeringVersionRecord:
        """Escribe la versión completa en una sola transacción.

        Crea los componentes nuevos, los subsistemas que falten y todos los
        renglones. Si algo falla, no queda nada: una versión a medias sería
        peor que ninguna.
        """
        ...

    async def get_version(self, version_id: str) -> EngineeringVersionRecord | None: ...

    async def list_versions(self, asset_id: str) -> tuple[EngineeringVersionRecord, ...]: ...

    async def get_published_version(self, asset_id: str) -> EngineeringVersionRecord | None: ...

    async def list_version_items(self, version_id: str) -> tuple[BomItemRecord, ...]: ...

    async def list_failure_modes(self, version_id: str) -> tuple[FailureModeRecord, ...]: ...

    async def list_sod_criteria(self, version_id: str) -> tuple[SodCriterionRecord, ...]: ...

    async def list_drawing_images(self, version_id: str) -> tuple[DrawingImageRecord, ...]: ...

    async def set_version_state(
        self, *, version_id: str, state: VersionState
    ) -> EngineeringVersionRecord:
        """Cambia el estado de una versión que aún no está publicada."""
        ...

    async def publish_version(
        self, *, version_id: str, actor: str, request_id: str | None = None
    ) -> EngineeringVersionRecord:
        """Publica la versión y marca la anterior como reemplazada.

        Atómico y serializado: dos publicaciones simultáneas no pueden dejar
        dos versiones vigentes ni ninguna. Lanza
        :class:`NotPublishableError` si la versión no está aprobada.
        """
        ...

    # -- Snapshots de SAP ---------------------------------------------

    async def store_sap_snapshot(
        self,
        *,
        asset_id: str,
        import_id: str,
        source_artifact_id: str,
        snapshot: ParsedSapSnapshot,
        actor: str,
        request_id: str | None = None,
    ) -> SapSnapshotRecord:
        """Guarda el snapshot completo. Nunca altera el BOM publicado."""
        ...

    async def get_snapshot(self, snapshot_id: str) -> SapSnapshotRecord | None: ...

    async def list_snapshots(self, asset_id: str) -> tuple[SapSnapshotRecord, ...]: ...

    async def list_snapshot_items(self, snapshot_id: str) -> tuple[SapSnapshotItemRecord, ...]: ...

    # -- Reconciliación -----------------------------------------------

    async def store_reconciliation(
        self,
        *,
        asset_id: str,
        version_id: str,
        snapshot_id: str,
        entries: Sequence[ReconciliationEntry],
        actor: str,
        request_id: str | None = None,
    ) -> ReconciliationRunRecord:
        """Guarda una corrida de reconciliación. No modifica las fuentes."""
        ...

    async def get_reconciliation(self, run_id: str) -> ReconciliationRunRecord | None: ...

    async def list_reconciliations(self, asset_id: str) -> tuple[ReconciliationRunRecord, ...]: ...

    async def list_reconciliation_items(
        self, run_id: str
    ) -> tuple[ReconciliationItemRecord, ...]: ...

    # -- Validaciones -------------------------------------------------

    async def record_review(
        self,
        *,
        asset_id: str,
        subject_kind: ReviewSubject,
        subject_id: str,
        decision: ReviewDecision,
        reviewer: str,
        comment: str | None = None,
        subject_version_id: str | None = None,
        reverts_review_id: str | None = None,
        inherited_from_id: str | None = None,
        request_id: str | None = None,
    ) -> ReviewRecord:
        """Añade una validación. Nunca modifica ni borra las anteriores."""
        ...

    async def get_review(self, review_id: str) -> ReviewRecord | None: ...

    async def latest_review(
        self, *, subject_kind: ReviewSubject, subject_id: str
    ) -> ReviewRecord | None:
        """Validación vigente de un sujeto: la más reciente que se registró."""
        ...

    async def list_reviews(
        self, *, asset_id: str, subject_id: str | None = None, limit: int = 100
    ) -> tuple[ReviewRecord, ...]: ...

    async def check_health(self) -> None:
        """Lanza :class:`KnowledgeUnavailableError` si el almacén no responde."""
        ...
