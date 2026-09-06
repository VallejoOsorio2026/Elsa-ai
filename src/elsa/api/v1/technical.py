"""API de gobierno del conocimiento técnico (Revisor Técnico).

Endpoints protegidos para cargar fuentes, consultar importaciones y
versiones, revisar, publicar y reconciliar. Todos exigen, en este orden:

1. permiso de lectura sobre el alcance (``RequireScope``, del Bloque 1);
2. capacidad de Revisor Técnico sobre ese mismo alcance
   (``RequireReviewer``).

Revisar exige poder leer, pero poder leer no habilita a revisar. Un
administrador pasa ambos filtros, porque conserva capacidad global de
intervención.

**No hay interfaz aquí.** Esto es API; el Centro de Control visual llegará
en un bloque posterior.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, Path, Request, UploadFile, status
from pydantic import BaseModel, Field

from elsa.api.deps import (
    RequireReviewer,
    RequireScope,
    get_ingestion_service,
    get_knowledge,
)
from elsa.api.errors import ApiError
from elsa.core.authorization import Principal
from elsa.core.review import (
    MissingReasonError,
    ReviewDecision,
    ReviewerCapability,
    ReviewSubject,
    validate_decision,
)
from elsa.ingestion.errors import IngestionError
from elsa.logging import get_request_id
from elsa.ports.artifact_storage import ArtifactStorageUnavailableError
from elsa.ports.knowledge import (
    EngineeringVersionRecord,
    ImportRecord,
    KnowledgeRepositoryPort,
    KnowledgeUnavailableError,
    NotPublishableError,
    ReviewRecord,
    SubjectNotFoundError,
    TechnicalAssetRecord,
    VersionState,
)
from elsa.services.ingestion import DuplicateImport, IngestionService

_logger = logging.getLogger("elsa.api.technical")

router = APIRouter(prefix="/technical/{domain}/{asset}", tags=["technical"])

# Se lee en trozos para poder abortar en cuanto se supera el límite, en vez
# de cargar en memoria un archivo enorme y rechazarlo después.
_CHUNK = 1024 * 1024

_HTTP_BY_FAILURE = {
    "file": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "parse": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "ambiguity": status.HTTP_409_CONFLICT,
}
_CODE_BY_FAILURE = {
    "file": "invalid_source_file",
    "parse": "unreadable_source_file",
    "ambiguity": "ambiguous_source_data",
}


# ---------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------


class ImportView(BaseModel):
    id: str
    kind: str
    status: str
    started_at: str
    finished_at: str | None = None
    failure_kind: str | None = None
    failure_message: str | None = None
    stats: dict[str, object] = Field(default_factory=dict)


class VersionView(BaseModel):
    id: str
    version_number: int
    state: str
    created_at: str
    published_at: str | None = None
    superseded_at: str | None = None


class BomItemView(BaseModel):
    """Renglón visto por un revisor: incluye el detalle interno."""

    id: str
    source_row: int
    component_id: str | None
    position: str | None
    subsystem_name: str | None
    component_name: str | None
    sap_code: str | None
    sap_code_original: str | None
    technical_description: str | None
    quantity: str | None
    quantity_original: str | None
    unit: str | None
    assembly_drawing: str | None
    drawing_reference: str | None
    inventory_strategy: str | None
    match_rule: str | None
    match_confidence: str
    change_kind: str | None


class FailureModeView(BaseModel):
    id: str
    source_row: int
    component_id: str | None
    component_name: str | None
    sap_code: str | None
    failure_mode: str | None
    effect: str | None
    cause: str | None
    severity: int | None
    occurrence: int | None
    detection: int | None
    rpn: int | None
    action: str | None
    preventive_plan: str | None
    corrective_action: str | None


class DrawingImageView(BaseModel):
    id: str
    sha256: str
    association_status: str
    drawing_number: str | None
    association_rule: str | None
    sheet_name: str | None
    anchor: str | None
    width_px: int | None
    height_px: int | None


class VersionDetail(BaseModel):
    version: VersionView
    items: list[BomItemView]
    failure_modes: list[FailureModeView]
    drawings: list[DrawingImageView]
    latest_review: "ReviewView | None" = None


class SnapshotView(BaseModel):
    id: str
    captured_at: str
    functional_location: str | None
    description: str | None
    valid_from: str | None
    materials: int
    equipments: int


class ReconciliationItemView(BaseModel):
    classification: str
    sap_code: str | None
    component_id: str | None
    engineering_quantity: str | None
    sap_quantity: str | None
    engineering_unit: str | None
    sap_unit: str | None
    engineering_description: str | None
    sap_description: str | None
    detail: dict[str, str] = Field(default_factory=dict)


class ReconciliationView(BaseModel):
    id: str
    version_id: str
    snapshot_id: str
    created_at: str
    stats: dict[str, int] = Field(default_factory=dict)


class ReconciliationDetail(BaseModel):
    run: ReconciliationView
    items: list[ReconciliationItemView]


class ReviewView(BaseModel):
    id: str
    subject_kind: str
    subject_id: str
    decision: str
    comment: str | None
    reviewer: str
    decided_at: str
    reverts_review_id: str | None = None
    inherited_from_id: str | None = None


class DecisionBody(BaseModel):
    """Aprobar admite comentario; rechazar exige motivo."""

    decision: ReviewDecision
    comment: str | None = None


class RevertBody(BaseModel):
    """Revertir siempre exige motivo."""

    comment: str


class ReconciliationRequest(BaseModel):
    snapshot_id: uuid.UUID
    version_id: uuid.UUID | None = None
    """Por omisión, la versión publicada vigente."""


class ImportAccepted(BaseModel):
    import_id: str | None = None
    version_id: str | None = None
    snapshot_id: str | None = None
    duplicate: bool = False
    """Verdadero si ese archivo exacto ya se había importado."""


# ---------------------------------------------------------------------
# Apoyo
# ---------------------------------------------------------------------


def _decimal(value: object) -> str | None:
    return None if value is None else str(value)


def _unavailable(message: str, code: str) -> ApiError:
    return ApiError(status.HTTP_503_SERVICE_UNAVAILABLE, message, code=code)


def _not_found(message: str, code: str) -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, message, code=code)


async def resolve_asset(
    domain: str = Path(...),
    asset: str = Path(...),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> TechnicalAssetRecord:
    """Carga el activo de la ruta y comprueba que vive en ese dominio.

    Un activo de otro dominio se trata como inexistente: quien pregunta ya
    superó la autorización de *su* dominio, y confirmarle que el activo
    existe en otro sería filtrar información del modelo.
    """
    try:
        record = await knowledge.get_asset(asset.strip().lower())
    except KnowledgeUnavailableError:
        raise _unavailable(
            "The knowledge store is temporarily unavailable.", "knowledge_store_unavailable"
        ) from None
    if record is None or record.domain != domain.strip().lower() or not record.is_active:
        raise _not_found("Unknown technical asset.", "asset_not_found")
    return record


async def _read_upload(upload: UploadFile, limit: int) -> bytes:
    """Lee el archivo subido sin pasar del límite configurado."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise ApiError(
                status.HTTP_413_CONTENT_TOO_LARGE,
                "The uploaded file is too large.",
                code="file_too_large",
            )
        chunks.append(chunk)
    if total == 0:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The uploaded file is empty.",
            code="invalid_source_file",
        )
    return b"".join(chunks)


def _ingestion_error(exc: IngestionError, request: Request) -> ApiError:
    """Traduce un fallo de ingesta sin filtrar contenido del archivo."""
    _logger.info(
        "ingestion rejected",
        extra={"failure_kind": exc.kind, "request_id": get_request_id(request)},
    )
    return ApiError(
        _HTTP_BY_FAILURE.get(exc.kind, status.HTTP_422_UNPROCESSABLE_CONTENT),
        str(exc),
        code=_CODE_BY_FAILURE.get(exc.kind, "invalid_source_file"),
    )


def _import_view(record: ImportRecord) -> ImportView:
    return ImportView(
        id=record.id,
        kind=record.kind.value,
        status=record.status.value,
        started_at=record.started_at.isoformat(),
        finished_at=None if record.finished_at is None else record.finished_at.isoformat(),
        failure_kind=record.failure_kind,
        failure_message=record.failure_message,
        stats=dict(record.stats),
    )


def _version_view(version: EngineeringVersionRecord) -> VersionView:
    return VersionView(
        id=version.id,
        version_number=version.version_number,
        state=version.state.value,
        created_at=version.created_at.isoformat(),
        published_at=None if version.published_at is None else version.published_at.isoformat(),
        superseded_at=(
            None if version.superseded_at is None else version.superseded_at.isoformat()
        ),
    )


def _review_view(review: ReviewRecord) -> ReviewView:
    return ReviewView(
        id=review.id,
        subject_kind=review.subject_kind.value,
        subject_id=review.subject_id,
        decision=review.decision.value,
        comment=review.comment,
        reviewer=review.reviewer,
        decided_at=review.decided_at.isoformat(),
        reverts_review_id=review.reverts_review_id,
        inherited_from_id=review.inherited_from_id,
    )


# ---------------------------------------------------------------------
# Carga de fuentes
# ---------------------------------------------------------------------


@router.post("/engineering-bom", response_model=ImportAccepted)
async def upload_engineering_bom(
    request: Request,
    file: UploadFile,
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    capability: ReviewerCapability = Depends(RequireReviewer()),
    service: IngestionService = Depends(get_ingestion_service),
) -> ImportAccepted:
    """Carga el XLSX aprobado por Ingeniería como una versión nueva.

    La versión entra siempre pendiente de validación: cargar no publica.
    Reimportar el mismo archivo devuelve la importación original en vez de
    crear una versión duplicada.
    """
    settings = request.app.state.settings
    data = await _read_upload(file, settings.ingestion_max_upload_bytes)

    try:
        result = await service.ingest_engineering_bom(
            asset=asset_record,
            data=data,
            actor=capability.external_user_id,
            original_filename=file.filename,
            request_id=get_request_id(request),
        )
    except IngestionError as exc:
        raise _ingestion_error(exc, request) from None
    except ArtifactStorageUnavailableError:
        # No se finge éxito: sin almacenamiento no hay evidencia guardada.
        raise _unavailable(
            "The private artifact storage is temporarily unavailable.",
            "artifact_storage_unavailable",
        ) from None
    except KnowledgeUnavailableError:
        raise _unavailable(
            "The knowledge store is temporarily unavailable.", "knowledge_store_unavailable"
        ) from None

    if isinstance(result, DuplicateImport):
        return ImportAccepted(import_id=result.existing_import_id, duplicate=True)
    return ImportAccepted(import_id=result.import_id, version_id=result.id)


@router.post("/sap-snapshots", response_model=ImportAccepted)
async def upload_sap_snapshot(
    request: Request,
    file: UploadFile,
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    capability: ReviewerCapability = Depends(RequireReviewer()),
    service: IngestionService = Depends(get_ingestion_service),
) -> ImportAccepted:
    """Carga un HTM exportado de SAP como snapshot histórico.

    El snapshot **no** reemplaza al BOM de Ingeniería publicado ni lo
    modifica: queda al lado, para poder compararlos.
    """
    settings = request.app.state.settings
    data = await _read_upload(file, settings.ingestion_max_upload_bytes)

    try:
        result = await service.ingest_sap_snapshot(
            asset=asset_record,
            data=data,
            actor=capability.external_user_id,
            original_filename=file.filename,
            request_id=get_request_id(request),
        )
    except IngestionError as exc:
        raise _ingestion_error(exc, request) from None
    except ArtifactStorageUnavailableError:
        raise _unavailable(
            "The private artifact storage is temporarily unavailable.",
            "artifact_storage_unavailable",
        ) from None
    except KnowledgeUnavailableError:
        raise _unavailable(
            "The knowledge store is temporarily unavailable.", "knowledge_store_unavailable"
        ) from None

    if isinstance(result, DuplicateImport):
        return ImportAccepted(import_id=result.existing_import_id, duplicate=True)
    return ImportAccepted(import_id=result.import_id, snapshot_id=result.id)


# ---------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------


@router.get("/imports", response_model=list[ImportView])
async def list_imports(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    _reviewer: ReviewerCapability = Depends(RequireReviewer()),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> list[ImportView]:
    return [_import_view(record) for record in await knowledge.list_imports(asset_record.id)]


@router.get("/versions", response_model=list[VersionView])
async def list_versions(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    _reviewer: ReviewerCapability = Depends(RequireReviewer()),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> list[VersionView]:
    """Todas las versiones, de la más reciente a la más antigua.

    Ninguna desaparece al publicarse otra: la anterior queda ``superseded``
    y sigue siendo consultable.
    """
    return [_version_view(version) for version in await knowledge.list_versions(asset_record.id)]


async def _load_version(
    knowledge: KnowledgeRepositoryPort, asset_record: TechnicalAssetRecord, version_id: uuid.UUID
) -> EngineeringVersionRecord:
    version = await knowledge.get_version(str(version_id))
    if version is None or version.asset_id != asset_record.id:
        raise _not_found("Unknown BOM version.", "version_not_found")
    return version


@router.get("/versions/{version_id}", response_model=VersionDetail)
async def read_version(
    version_id: uuid.UUID,
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    _reviewer: ReviewerCapability = Depends(RequireReviewer()),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> VersionDetail:
    """Detalle completo, con la razón de cada emparejamiento y cada cambio."""
    version = await _load_version(knowledge, asset_record, version_id)
    latest = await knowledge.latest_review(
        subject_kind=ReviewSubject.ENGINEERING_BOM_VERSION, subject_id=version.id
    )
    return VersionDetail(
        version=_version_view(version),
        items=[
            BomItemView(
                id=item.id,
                source_row=item.source_row,
                component_id=item.component_id,
                position=item.position,
                subsystem_name=item.subsystem_name,
                component_name=item.component_name,
                sap_code=item.sap_code,
                sap_code_original=item.sap_code_original,
                technical_description=item.technical_description,
                quantity=_decimal(item.quantity),
                quantity_original=item.quantity_original,
                unit=item.unit,
                assembly_drawing=item.assembly_drawing,
                drawing_reference=item.drawing_reference,
                inventory_strategy=item.inventory_strategy,
                match_rule=item.match_rule,
                match_confidence=item.match_confidence,
                change_kind=item.change_kind,
            )
            for item in await knowledge.list_version_items(version.id)
        ],
        failure_modes=[
            FailureModeView(
                id=mode.id,
                source_row=mode.source_row,
                component_id=mode.component_id,
                component_name=mode.component_name,
                sap_code=mode.sap_code,
                failure_mode=mode.failure_mode,
                effect=mode.effect,
                cause=mode.cause,
                severity=mode.severity,
                occurrence=mode.occurrence,
                detection=mode.detection,
                rpn=mode.rpn,
                action=mode.action,
                preventive_plan=mode.preventive_plan,
                corrective_action=mode.corrective_action,
            )
            for mode in await knowledge.list_failure_modes(version.id)
        ],
        drawings=[
            DrawingImageView(
                id=image.id,
                sha256=image.sha256,
                association_status=image.association_status,
                drawing_number=image.drawing_number,
                association_rule=image.association_rule,
                sheet_name=image.sheet_name,
                anchor=image.anchor,
                width_px=image.width_px,
                height_px=image.height_px,
            )
            for image in await knowledge.list_drawing_images(version.id)
        ],
        latest_review=None if latest is None else _review_view(latest),
    )


# ---------------------------------------------------------------------
# Revisión y publicación
# ---------------------------------------------------------------------


@router.post("/versions/{version_id}/review", response_model=ReviewView)
async def review_version(
    request: Request,
    version_id: uuid.UUID,
    body: DecisionBody,
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    capability: ReviewerCapability = Depends(RequireReviewer()),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> ReviewView:
    """Aprueba o rechaza una versión.

    Aprobar admite comentario; rechazar exige motivo. La validación queda
    atada a **esta** versión: si una posterior cambia el dato, esta
    aprobación pasa a ser histórica.
    """
    version = await _load_version(knowledge, asset_record, version_id)
    if body.decision is ReviewDecision.REVERTED:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Use the revert endpoint to undo a validation.",
            code="invalid_decision",
        )
    try:
        comment = validate_decision(body.decision, body.comment)
    except MissingReasonError as exc:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc), code="reason_required"
        ) from None

    review = await knowledge.record_review(
        asset_id=asset_record.id,
        subject_kind=ReviewSubject.ENGINEERING_BOM_VERSION,
        subject_id=version.id,
        decision=body.decision,
        reviewer=capability.external_user_id,
        comment=comment,
        subject_version_id=version.id,
        request_id=get_request_id(request),
    )
    await knowledge.set_version_state(
        version_id=version.id,
        state=(
            VersionState.APPROVED
            if body.decision is ReviewDecision.APPROVED
            else VersionState.REJECTED
        ),
    )
    return _review_view(review)


@router.post("/reviews/{review_id}/revert", response_model=ReviewView)
async def revert_review(
    request: Request,
    review_id: uuid.UUID,
    body: RevertBody,
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    capability: ReviewerCapability = Depends(RequireReviewer()),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> ReviewView:
    """Revierte una validación, exigiendo motivo.

    Puede hacerlo el mismo revisor si sigue habilitado, otro revisor con
    alcance equivalente, o un administrador: la comprobación de alcance ya la
    hizo ``RequireReviewer``. **Nada se borra**: se añade un registro que
    apunta a la validación que deshace.
    """
    try:
        comment = validate_decision(ReviewDecision.REVERTED, body.comment)
    except MissingReasonError as exc:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc), code="reason_required"
        ) from None

    original = await knowledge.get_review(str(review_id))
    if original is None or original.asset_id != asset_record.id:
        raise _not_found("Unknown validation.", "review_not_found")
    if original.decision is ReviewDecision.REVERTED:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "That validation is already a reversal.",
            code="already_reverted",
        )

    review = await knowledge.record_review(
        asset_id=asset_record.id,
        subject_kind=original.subject_kind,
        subject_id=original.subject_id,
        decision=ReviewDecision.REVERTED,
        reviewer=capability.external_user_id,
        comment=comment,
        subject_version_id=original.subject_version_id,
        reverts_review_id=original.id,
        request_id=get_request_id(request),
    )
    if original.subject_kind is ReviewSubject.ENGINEERING_BOM_VERSION:
        version = await knowledge.get_version(original.subject_id)
        if version is not None and version.state is not VersionState.PUBLISHED:
            # Deshacer la decisión devuelve la versión a revisión. Una versión
            # ya publicada no retrocede sola: se reemplaza publicando otra.
            await knowledge.set_version_state(
                version_id=version.id, state=VersionState.PENDING_VALIDATION
            )
    return _review_view(review)


@router.post("/versions/{version_id}/publish", response_model=VersionView)
async def publish_version(
    request: Request,
    version_id: uuid.UUID,
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    capability: ReviewerCapability = Depends(RequireReviewer()),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> VersionView:
    """Publica una versión aprobada y reemplaza a la vigente.

    Es atómico: no existe un instante en el que el activo tenga dos versiones
    vigentes o ninguna. La anterior no se borra, queda ``superseded``.
    """
    version = await _load_version(knowledge, asset_record, version_id)
    try:
        published = await knowledge.publish_version(
            version_id=version.id,
            actor=capability.external_user_id,
            request_id=get_request_id(request),
        )
    except NotPublishableError as exc:
        raise ApiError(status.HTTP_409_CONFLICT, str(exc), code="version_not_publishable") from None
    except SubjectNotFoundError:
        raise _not_found("Unknown BOM version.", "version_not_found") from None
    return _version_view(published)


@router.get("/reviews", response_model=list[ReviewView])
async def list_reviews(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    _reviewer: ReviewerCapability = Depends(RequireReviewer()),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> list[ReviewView]:
    """Historial completo de validaciones. Ninguna se borra jamás."""
    return [
        _review_view(review) for review in await knowledge.list_reviews(asset_id=asset_record.id)
    ]


# ---------------------------------------------------------------------
# Snapshots y reconciliación
# ---------------------------------------------------------------------


@router.get("/snapshots", response_model=list[SnapshotView])
async def list_snapshots(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    _reviewer: ReviewerCapability = Depends(RequireReviewer()),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> list[SnapshotView]:
    views: list[SnapshotView] = []
    for snapshot in await knowledge.list_snapshots(asset_record.id):
        items = await knowledge.list_snapshot_items(snapshot.id)
        views.append(
            SnapshotView(
                id=snapshot.id,
                captured_at=snapshot.captured_at.isoformat(),
                functional_location=snapshot.functional_location,
                description=snapshot.description,
                valid_from=None if snapshot.valid_from is None else snapshot.valid_from.isoformat(),
                materials=sum(1 for item in items if item.entry_kind == "material"),
                equipments=sum(1 for item in items if item.entry_kind == "equipment"),
            )
        )
    return views


@router.post("/reconciliations", response_model=ReconciliationView)
async def create_reconciliation(
    request: Request,
    body: ReconciliationRequest,
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    capability: ReviewerCapability = Depends(RequireReviewer()),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
    service: IngestionService = Depends(get_ingestion_service),
) -> ReconciliationView:
    """Compara una versión con un snapshot y guarda el resultado.

    Ninguna de las dos fuentes se modifica. Una discrepancia no se corrige
    sola: queda registrada con ambos valores para que una persona decida.
    """
    if body.version_id is not None:
        version = await _load_version(knowledge, asset_record, body.version_id)
    else:
        published = await knowledge.get_published_version(asset_record.id)
        if published is None:
            raise ApiError(
                status.HTTP_409_CONFLICT,
                "This asset has no published engineering BOM to compare against.",
                code="no_published_version",
            )
        version = published

    snapshot = await knowledge.get_snapshot(str(body.snapshot_id))
    if snapshot is None or snapshot.asset_id != asset_record.id:
        raise _not_found("Unknown SAP snapshot.", "snapshot_not_found")

    run = await service.reconcile_published_bom(
        asset=asset_record,
        version_id=version.id,
        snapshot_id=snapshot.id,
        actor=capability.external_user_id,
        request_id=get_request_id(request),
    )
    return ReconciliationView(
        id=run.id,
        version_id=run.version_id,
        snapshot_id=run.snapshot_id,
        created_at=run.created_at.isoformat(),
        stats=dict(run.stats),
    )


@router.get("/reconciliations/{run_id}", response_model=ReconciliationDetail)
async def read_reconciliation(
    run_id: uuid.UUID,
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _scope: Principal = Depends(RequireScope(equipment_param="asset")),
    _reviewer: ReviewerCapability = Depends(RequireReviewer()),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> ReconciliationDetail:
    """Detalle con el valor de Ingeniería y el de SAP, lado a lado."""
    run = await knowledge.get_reconciliation(str(run_id))
    if run is None or run.asset_id != asset_record.id:
        raise _not_found("Unknown reconciliation run.", "reconciliation_not_found")
    return ReconciliationDetail(
        run=ReconciliationView(
            id=run.id,
            version_id=run.version_id,
            snapshot_id=run.snapshot_id,
            created_at=run.created_at.isoformat(),
            stats=dict(run.stats),
        ),
        items=[
            ReconciliationItemView(
                classification=item.classification,
                sap_code=item.sap_code,
                component_id=item.component_id,
                engineering_quantity=_decimal(item.engineering_quantity),
                sap_quantity=_decimal(item.sap_quantity),
                engineering_unit=item.engineering_unit,
                sap_unit=item.sap_unit,
                engineering_description=item.engineering_description,
                sap_description=item.sap_description,
                detail=dict(item.detail),
            )
            for item in await knowledge.list_reconciliation_items(run.id)
        ],
    )
