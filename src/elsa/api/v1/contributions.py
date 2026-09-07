"""Aportes de conocimiento: grabar, revisar lo entendido, enviar y validar.

Recorrido completo del Bloque 3, con tres fronteras que no se cruzan:

- **Consultar no es aportar.** ``RequireContributor`` exige una capacidad
  propia, además del permiso de lectura del Bloque 1.
- **Aportar no es publicar.** Un aporte enviado queda ``pending`` y no
  aparece en la consulta del equipo. Aprobarlo tampoco lo publica: lo marca
  como válido y ahí se detiene este bloque.
- **Lo simulado se declara.** El audio se graba y se guarda de verdad; el
  texto, mientras no haya motor de voz, es un marcador de posición o lo que
  la persona escriba. La bandera viaja con el aporte hasta la revisión.

Sobre los límites: el número de adjuntos y el tamaño total se comprueban
aquí leyendo los bytes reales. La **duración** del audio, en cambio, la
declara el navegador: sin decodificar el archivo en el servidor no se puede
verificar, y decodificarlo exigiría una dependencia de medios que este
bloque no introduce. Lo que sí se comprueba de verdad es el tamaño en bytes.
Queda anotado como límite conocido.
"""

import logging

from fastapi import APIRouter, Depends, File, Form, Path, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from elsa.api.deps import (
    RequireContributor,
    RequireReviewer,
    RequireScope,
    get_artifact_storage,
    get_container,
    get_contributions,
    get_knowledge,
    get_settings,
    get_transcription,
    reviewer_capability,
)
from elsa.api.errors import ApiError
from elsa.api.v1.technical import resolve_asset
from elsa.config import Settings
from elsa.container import Container
from elsa.core.authorization import Principal, Scope
from elsa.core.contributions import (
    ContributionRuleError,
    NotSubmittableError,
    check_submittable,
    derive_title,
    ensure_submittable,
    is_placeholder_title,
    neutral_title,
)
from elsa.core.normalization import normalize_text
from elsa.core.review import ReviewerCapability, can_review
from elsa.core.understanding import CHECKLIST, extract
from elsa.logging import get_request_id
from elsa.ports.artifact_storage import (
    ArtifactAlreadyExistsError,
    ArtifactStoragePort,
    ArtifactStorageUnavailableError,
    sha256_hex,
    storage_key,
)
from elsa.ports.contributions import (
    ChecklistAnswer,
    ContributionAttachment,
    ContributionAudio,
    ContributionRecord,
    ContributionsRepositoryPort,
    ContributionState,
    Normalization,
)
from elsa.ports.knowledge import KnowledgeRepositoryPort, TechnicalAssetRecord
from elsa.ports.transcription import TranscriptionPort, TranscriptionUnavailableError

_logger = logging.getLogger("elsa.api.contributions")

router = APIRouter(prefix="/contributions/{domain}/{asset}", tags=["contributions"])

_CHUNK = 512 * 1024
_MAX_TITLE = 160


# ---------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------


class ChecklistItemView(BaseModel):
    key: str
    question: str
    hint: str
    required: bool


class CapabilityView(BaseModel):
    """Qué puede hacer quien pregunta, en este alcance."""

    domain: str
    asset: str
    can_read: bool = True
    can_contribute: bool
    can_review: bool
    checklist: list[ChecklistItemView]
    max_attachments: int
    max_attachment_bytes: int
    max_audio_seconds: int
    transcription_is_simulated: bool
    pending_count: int = 0
    """Aportes esperando revisión. Cero si quien pregunta no revisa."""


class NormalizationView(BaseModel):
    key: str
    label: str
    detected: str | None = None
    value: str | None = None
    kind: str = "text"
    matched_in_bom: bool = False
    edited: bool = False


class NormalizationInput(BaseModel):
    key: str = Field(max_length=64)
    value: str | None = Field(default=None, max_length=2000)


class ChecklistAnswerView(BaseModel):
    key: str
    question: str
    answer: str | None = None
    checked: bool = False


class ChecklistAnswerInput(BaseModel):
    key: str = Field(max_length=64)
    answer: str | None = Field(default=None, max_length=2000)
    checked: bool = False


class AttachmentView(BaseModel):
    id: str
    filename: str
    byte_size: int
    content_type: str | None = None


class AudioView(BaseModel):
    byte_size: int
    duration_seconds: float
    content_type: str | None = None


class ContributionView(BaseModel):
    """Un aporte tal como lo ve su autor o un revisor."""

    id: str
    domain: str
    asset: str
    title: str
    title_is_generated: bool = False
    state: str
    is_published_knowledge: bool = False
    """Siempre falso en este bloque. Aprobar no publica."""

    author_id: str
    author_name: str | None = None
    created_at: str
    submitted_at: str | None = None
    decided_at: str | None = None
    decided_by: str | None = None
    decided_by_name: str | None = None
    decision_reason: str | None = None

    transcript_text: str
    transcript_is_simulated: bool
    transcript_engine: str | None = None
    transcript_edited: bool
    audio: AudioView | None = None
    attachments: list[AttachmentView] = Field(default_factory=list)
    normalizations: list[NormalizationView] = Field(default_factory=list)
    checklist: list[ChecklistAnswerView] = Field(default_factory=list)

    can_edit: bool = False
    can_submit: bool = False
    missing_to_submit: list[str] = Field(default_factory=list)
    missing_reasons: list[str] = Field(default_factory=list)


class UpdateDraftRequest(BaseModel):
    title: str | None = Field(default=None, max_length=_MAX_TITLE)
    transcript_text: str | None = Field(default=None, max_length=20000)
    normalizations: list[NormalizationInput] | None = None
    checklist: list[ChecklistAnswerInput] | None = None


class DecisionRequest(BaseModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------
# Conversión
# ---------------------------------------------------------------------


def _view(record: ContributionRecord, *, viewer_id: str, is_reviewer: bool) -> ContributionView:
    is_author = record.author_id == viewer_id
    can_edit = is_author and record.state is ContributionState.DRAFT
    check = check_submittable(record)
    return ContributionView(
        id=record.id,
        domain=record.domain,
        asset=record.asset_code,
        title=record.title,
        title_is_generated=record.title_is_generated,
        state=record.state.value,
        is_published_knowledge=record.is_published_knowledge,
        author_id=record.author_id,
        author_name=record.author_name,
        created_at=record.created_at.isoformat(),
        submitted_at=None if record.submitted_at is None else record.submitted_at.isoformat(),
        decided_at=None if record.decided_at is None else record.decided_at.isoformat(),
        decided_by=record.decided_by,
        decided_by_name=record.decided_by_name,
        decision_reason=record.decision_reason,
        transcript_text=record.transcript_text,
        transcript_is_simulated=record.transcript_is_simulated,
        transcript_engine=record.transcript_engine,
        transcript_edited=record.transcript_edited,
        audio=(
            None
            if record.audio is None
            else AudioView(
                byte_size=record.audio.byte_size,
                duration_seconds=record.audio.duration_seconds,
                content_type=record.audio.content_type,
            )
        ),
        attachments=[
            AttachmentView(
                id=item.id,
                filename=item.filename,
                byte_size=item.byte_size,
                content_type=item.content_type,
            )
            for item in record.attachments
        ],
        normalizations=[
            NormalizationView(
                key=item.key,
                label=item.label,
                detected=item.detected,
                value=item.value,
                kind=item.kind,
                matched_in_bom=item.matched_in_bom,
                edited=item.edited,
            )
            for item in record.normalizations
        ],
        checklist=[
            ChecklistAnswerView(
                key=item.key, question=item.question, answer=item.answer, checked=item.checked
            )
            for item in record.checklist
        ],
        can_edit=can_edit,
        can_submit=can_edit and check.ok,
        missing_to_submit=list(check.missing),
        missing_reasons=list(check.reasons),
    )


# ---------------------------------------------------------------------
# Ayudas
# ---------------------------------------------------------------------


def _not_found() -> ApiError:
    """Un aporte ajeno y uno inexistente se responden igual.

    Distinguirlos confirmaría que existe un aporte al que no se tiene
    acceso, que es información sobre el modelo que no toca dar.
    """
    return ApiError(status.HTTP_404_NOT_FOUND, "Unknown contribution.", code="not_found")


async def _read_upload(upload: UploadFile, *, limit: int, what: str) -> bytes:
    """Lee un archivo abortando en cuanto supera el límite."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise ApiError(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"The {what} exceeds the allowed size.",
                code="payload_too_large",
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _store(storage: ArtifactStoragePort, prefix: str, data: bytes) -> str:
    """Guarda los bytes y devuelve su clave.

    El almacén direcciona por contenido, así que dos aportes con el mismo
    archivo producen la misma clave. Que ya exista no es un conflicto: es
    deduplicación, y el contenido es idéntico por construcción, porque la
    clave sale de su SHA-256. Se reutiliza, igual que hace la ingesta.
    """
    key = storage_key(prefix, sha256_hex(data))
    try:
        await storage.put(key, data)
    except ArtifactAlreadyExistsError:
        return key
    except ArtifactStorageUnavailableError:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The private artifact storage is temporarily unavailable.",
            code="artifact_storage_unavailable",
        ) from None
    return key


async def _published_context(
    knowledge: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> tuple[tuple[object, ...], tuple[object, ...]]:
    """BOM y AMEF publicados, o vacíos si el equipo aún no tiene versión."""
    published = await knowledge.get_published_version(asset.id)
    if published is None:
        return (), ()
    return (
        await knowledge.list_version_items(published.id),
        await knowledge.list_failure_modes(published.id),
    )


def _initial_normalizations(
    text: str, *, asset: TechnicalAssetRecord, bom: object, modes: object
) -> tuple[Normalization, ...]:
    fields = extract(
        text,
        asset_name=asset.name,
        bom_items=bom,  # type: ignore[arg-type]
        failure_modes=modes,  # type: ignore[arg-type]
    )
    return tuple(
        Normalization(
            key=field.key,
            label=field.label,
            detected=field.detected,
            value=field.detected,
            kind=field.kind,
            matched_in_bom=field.matched_in_bom,
        )
        for field in fields
    )


def _initial_checklist() -> tuple[ChecklistAnswer, ...]:
    return tuple(ChecklistAnswer(key=item.key, question=item.question) for item in CHECKLIST)


def _resolve_title(
    record: ContributionRecord,
    *,
    payload_title: str | None,
    normalizations: list[Normalization] | None,
    checklist: list[ChecklistAnswer] | None,
) -> tuple[str | None, bool | None]:
    """Decide el título tras una edición del borrador.

    Tres casos, en este orden:

    1. La persona manda un título con contenido: manda ella, y a partir de
       ahí el título deja de recomponerse.
    2. La persona manda un marcador («Prueba 1») o lo deja vacío: se vuelve a
       componer con lo que haya.
    3. No manda título: solo se recompone si el actual lo compuso ELSA.
    """
    if payload_title is not None and not is_placeholder_title(payload_title):
        return normalize_text(payload_title), False

    should_regenerate = payload_title is not None or record.title_is_generated
    if not should_regenerate:
        return None, None

    # Sin material nuevo se conserva el rótulo que ya tenía: renumerarlo
    # cada vez que se guarda confundiría a quien lo está mirando.
    derived = derive_title(
        normalizations=normalizations if normalizations is not None else record.normalizations,
        checklist=checklist if checklist is not None else record.checklist,
    )
    return (derived or record.title, True)


async def _visible(
    contribution_id: str,
    *,
    contributions: ContributionsRepositoryPort,
    asset: TechnicalAssetRecord,
    principal: Principal,
    capability: ReviewerCapability,
) -> tuple[ContributionRecord, bool]:
    """Carga el aporte si quien pregunta puede verlo. Devuelve si es revisor."""
    record = await contributions.get(contribution_id)
    if record is None:
        raise _not_found()
    if record.domain != asset.domain or record.asset_code != asset.code:
        raise _not_found()

    is_reviewer = can_review(capability, Scope(domain=asset.domain, equipment=asset.code))
    if record.author_id != principal.external_user_id and not is_reviewer:
        raise _not_found()
    return record, is_reviewer


# ---------------------------------------------------------------------
# Capacidad
# ---------------------------------------------------------------------


@router.get("/capability", response_model=CapabilityView)
async def capability(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    principal: Principal = Depends(RequireScope(equipment_param="asset")),
    reviewer: ReviewerCapability = Depends(reviewer_capability),
    contributions: ContributionsRepositoryPort = Depends(get_contributions),
    container: Container = Depends(get_container),
    settings: Settings = Depends(get_settings),
) -> CapabilityView:
    """Qué puede hacer esta persona aquí. La interfaz dibuja a partir de esto.

    Ocultar un botón no autoriza nada —cada endpoint vuelve a comprobarlo—
    pero evita ofrecer lo que va a fallar.
    """
    scope = Scope(domain=asset_record.domain, equipment=asset_record.code)
    reviews = can_review(reviewer, scope)
    contributes = principal.is_admin or await contributions.is_contributor(
        principal.external_user_id, domain=asset_record.domain, asset_code=asset_record.code
    )

    pending = 0
    if reviews:
        pending = len(
            await contributions.list_by_state(
                domain=asset_record.domain,
                asset_code=asset_record.code,
                state=ContributionState.PENDING,
            )
        )

    return CapabilityView(
        domain=asset_record.domain,
        asset=asset_record.code,
        can_contribute=contributes,
        can_review=reviews,
        checklist=[
            ChecklistItemView(
                key=item.key, question=item.question, hint=item.hint, required=item.required
            )
            for item in CHECKLIST
        ],
        max_attachments=settings.contribution_max_attachments,
        max_attachment_bytes=settings.contribution_max_attachment_bytes,
        max_audio_seconds=settings.contribution_max_audio_seconds,
        transcription_is_simulated=container.transcription_is_simulated,
        pending_count=pending,
    )


# ---------------------------------------------------------------------
# Listados (antes que /{contribution_id}, o la ruta los capturaría)
# ---------------------------------------------------------------------


@router.get("/mine", response_model=list[ContributionView])
async def list_mine(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    principal: Principal = Depends(RequireScope(equipment_param="asset")),
    contributions: ContributionsRepositoryPort = Depends(get_contributions),
) -> list[ContributionView]:
    """Mis aportes en este equipo, del más reciente al más antiguo."""
    records = await contributions.list_by_author(
        principal.external_user_id,
        domain=asset_record.domain,
        asset_code=asset_record.code,
    )
    return [
        _view(record, viewer_id=principal.external_user_id, is_reviewer=False) for record in records
    ]


@router.get("/pending", response_model=list[ContributionView])
async def list_pending(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    principal: Principal = Depends(RequireScope(equipment_param="asset")),
    _reviewer: ReviewerCapability = Depends(RequireReviewer()),
    contributions: ContributionsRepositoryPort = Depends(get_contributions),
) -> list[ContributionView]:
    """Cola de revisión: aportes enviados y todavía sin decidir."""
    records = await contributions.list_by_state(
        domain=asset_record.domain,
        asset_code=asset_record.code,
        state=ContributionState.PENDING,
    )
    return [
        _view(record, viewer_id=principal.external_user_id, is_reviewer=True) for record in records
    ]


@router.get("/decided", response_model=list[ContributionView])
async def list_decided(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    principal: Principal = Depends(RequireScope(equipment_param="asset")),
    _reviewer: ReviewerCapability = Depends(RequireReviewer()),
    contributions: ContributionsRepositoryPort = Depends(get_contributions),
) -> list[ContributionView]:
    """Lo ya decidido, para poder revisar una decisión anterior."""
    approved = await contributions.list_by_state(
        domain=asset_record.domain,
        asset_code=asset_record.code,
        state=ContributionState.APPROVED,
    )
    rejected = await contributions.list_by_state(
        domain=asset_record.domain,
        asset_code=asset_record.code,
        state=ContributionState.REJECTED,
    )
    records = sorted(
        [*approved, *rejected],
        key=lambda item: item.decided_at or item.created_at,
        reverse=True,
    )
    return [
        _view(record, viewer_id=principal.external_user_id, is_reviewer=True) for record in records
    ]


# ---------------------------------------------------------------------
# Creación
# ---------------------------------------------------------------------


@router.post("", response_model=ContributionView, status_code=status.HTTP_201_CREATED)
async def create_contribution(
    request: Request,
    title: str = Form(default="", max_length=_MAX_TITLE),
    audio: UploadFile | None = File(default=None),
    audio_duration_seconds: float = Form(default=0.0),
    attachments: list[UploadFile] = File(default=[]),
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    principal: Principal = Depends(RequireContributor()),
    contributions: ContributionsRepositoryPort = Depends(get_contributions),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
    storage: ArtifactStoragePort = Depends(get_artifact_storage),
    transcription: TranscriptionPort = Depends(get_transcription),
    settings: Settings = Depends(get_settings),
) -> ContributionView:
    """Crea un borrador a partir de la nota de voz y los adjuntos.

    El aporte nace en ``draft``: se graba, se transcribe (o se marca como
    simulado), se propone una interpretación y la persona la corrige antes
    de enviarla. Nada de esto es todavía conocimiento.
    """
    real_attachments = [item for item in attachments if item.filename]
    if len(real_attachments) > settings.contribution_max_attachments:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"A contribution accepts at most {settings.contribution_max_attachments} attachments.",
            code="too_many_attachments",
        )
    if (
        audio_duration_seconds < 0
        or audio_duration_seconds > settings.contribution_max_audio_seconds
    ):
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"A voice note cannot exceed {settings.contribution_max_audio_seconds} seconds.",
            code="audio_too_long",
        )

    stored_audio: ContributionAudio | None = None
    transcript_text = ""
    is_simulated = True
    engine: str | None = None

    if audio is not None and audio.filename:
        data = await _read_upload(
            audio, limit=settings.contribution_max_attachment_bytes, what="voice note"
        )
        if data:
            key = await _store(storage, "contribution-audio", data)
            stored_audio = ContributionAudio(
                storage_key=key,
                byte_size=len(data),
                duration_seconds=audio_duration_seconds,
                content_type=audio.content_type,
            )
            try:
                result = await transcription.transcribe(
                    data,
                    content_type=audio.content_type,
                    duration_seconds=audio_duration_seconds,
                )
            except TranscriptionUnavailableError:
                raise ApiError(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    "The transcription engine is temporarily unavailable.",
                    code="transcription_unavailable",
                ) from None
            transcript_text = result.text
            is_simulated = result.is_simulated
            engine = result.engine

    stored_attachments: list[ContributionAttachment] = []
    budget = settings.contribution_max_attachment_bytes
    for item in real_attachments:
        data = await _read_upload(item, limit=budget, what="attachment")
        budget -= len(data)
        if budget < 0:
            raise ApiError(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "The attachments exceed the allowed total size.",
                code="payload_too_large",
            )
        key = await _store(storage, "contribution-file", data)
        stored_attachments.append(
            ContributionAttachment(
                id=key.rsplit("/", 1)[-1],
                filename=item.filename or "adjunto",
                byte_size=len(data),
                storage_key=key,
                content_type=item.content_type,
            )
        )

    bom, modes = await _published_context(knowledge, asset_record)

    # Un título como «Prueba 1» deja la cola de revisión llena de renglones
    # indistinguibles. Cuando el que llega es un marcador, ELSA compone uno
    # con lo que el aporte ya contiene; recién creado eso todavía es poco, y
    # el rótulo numerado es el fallback honesto.
    checklist = _initial_checklist()
    normalizations = _initial_normalizations(
        transcript_text if not is_simulated else "",
        asset=asset_record,
        bom=bom,
        modes=modes,
    )
    generated = is_placeholder_title(title)
    if generated:
        previous = await contributions.list_by_author(
            principal.external_user_id,
            domain=asset_record.domain,
            asset_code=asset_record.code,
        )
        resolved_title = derive_title(
            normalizations=normalizations, checklist=checklist
        ) or neutral_title(len(previous) + 1)
    else:
        resolved_title = normalize_text(title) or ""

    record = await contributions.create(
        domain=asset_record.domain,
        asset_code=asset_record.code,
        author_id=principal.external_user_id,
        author_name=principal.display_name,
        title=resolved_title,
        title_is_generated=generated,
        transcript_text=transcript_text,
        transcript_is_simulated=is_simulated,
        transcript_engine=engine,
        audio=stored_audio,
        attachments=stored_attachments,
        normalizations=normalizations,
        checklist=checklist,
    )
    _logger.info(
        "contribution drafted",
        extra={
            "user_id": principal.external_user_id,
            "domain": asset_record.domain,
            "equipment": asset_record.code,
            "request_id": get_request_id(request),
        },
    )
    return _view(record, viewer_id=principal.external_user_id, is_reviewer=False)


# ---------------------------------------------------------------------
# Detalle y edición
# ---------------------------------------------------------------------


@router.get("/{contribution_id}", response_model=ContributionView)
async def read_contribution(
    contribution_id: str = Path(...),
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    principal: Principal = Depends(RequireScope(equipment_param="asset")),
    reviewer: ReviewerCapability = Depends(reviewer_capability),
    contributions: ContributionsRepositoryPort = Depends(get_contributions),
) -> ContributionView:
    record, is_reviewer = await _visible(
        contribution_id,
        contributions=contributions,
        asset=asset_record,
        principal=principal,
        capability=reviewer,
    )
    return _view(record, viewer_id=principal.external_user_id, is_reviewer=is_reviewer)


@router.patch("/{contribution_id}", response_model=ContributionView)
async def update_contribution(
    payload: UpdateDraftRequest,
    contribution_id: str = Path(...),
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    principal: Principal = Depends(RequireContributor()),
    reviewer: ReviewerCapability = Depends(reviewer_capability),
    contributions: ContributionsRepositoryPort = Depends(get_contributions),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> ContributionView:
    """Corrige el borrador: título, texto, normalizaciones y guía.

    Cuando cambia el texto se vuelve a extraer la interpretación, pero
    **solo se sustituye lo que la persona no había tocado**: una corrección
    manual no se pierde porque después se reescriba el texto.
    """
    record, _ = await _visible(
        contribution_id,
        contributions=contributions,
        asset=asset_record,
        principal=principal,
        capability=reviewer,
    )
    if record.author_id != principal.external_user_id:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "Only the author can edit a contribution.",
            code="not_the_author",
        )

    normalizations: list[Normalization] | None = None
    transcript_edited: bool | None = None
    text = record.transcript_text
    if payload.transcript_text is not None:
        text = payload.transcript_text
        transcript_edited = True

    if payload.transcript_text is not None or payload.normalizations is not None:
        bom, modes = await _published_context(knowledge, asset_record)
        fresh = {
            item.key: item
            for item in _initial_normalizations(text, asset=asset_record, bom=bom, modes=modes)
        }
        overrides = {item.key: item.value for item in (payload.normalizations or [])}
        merged: list[Normalization] = []
        for previous in record.normalizations:
            proposal = fresh.get(previous.key, previous)
            if previous.key in overrides:
                value = normalize_text(overrides[previous.key])
            elif previous.edited:
                # La persona ya había corregido este campo: se respeta.
                value = previous.value
            else:
                value = proposal.detected
            merged.append(
                Normalization(
                    key=previous.key,
                    label=previous.label,
                    detected=proposal.detected,
                    value=value,
                    kind=previous.kind,
                    matched_in_bom=proposal.matched_in_bom,
                )
            )
        normalizations = merged

    checklist: list[ChecklistAnswer] | None = None
    if payload.checklist is not None:
        answers = {item.key: item for item in payload.checklist}
        checklist = [
            ChecklistAnswer(
                key=item.key,
                question=item.question,
                answer=(
                    normalize_text(answers[item.key].answer) if item.key in answers else item.answer
                ),
                checked=answers[item.key].checked if item.key in answers else item.checked,
            )
            for item in record.checklist
        ]

    # El título solo se recompone si lo compuso ELSA. Uno escrito por una
    # persona se respeta aunque después llegue mejor información: decidir por
    # ella cómo se llama su aporte no es ayudar.
    title, title_is_generated = _resolve_title(
        record,
        payload_title=payload.title,
        normalizations=normalizations,
        checklist=checklist,
    )

    try:
        updated = await contributions.update_draft(
            contribution_id,
            title=title,
            title_is_generated=title_is_generated,
            transcript_text=payload.transcript_text,
            transcript_edited=transcript_edited,
            normalizations=normalizations,
            checklist=checklist,
        )
    except ContributionRuleError as error:
        raise ApiError(
            status.HTTP_409_CONFLICT, str(error), code="contribution_not_editable"
        ) from None
    return _view(updated, viewer_id=principal.external_user_id, is_reviewer=False)


@router.post("/{contribution_id}/submit", response_model=ContributionView)
async def submit_contribution(
    request: Request,
    contribution_id: str = Path(...),
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    principal: Principal = Depends(RequireContributor()),
    reviewer: ReviewerCapability = Depends(reviewer_capability),
    contributions: ContributionsRepositoryPort = Depends(get_contributions),
) -> ContributionView:
    """Envía el borrador a revisión. Queda ``pending``, no publicado."""
    record, _ = await _visible(
        contribution_id,
        contributions=contributions,
        asset=asset_record,
        principal=principal,
        capability=reviewer,
    )
    if record.author_id != principal.external_user_id:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "Only the author can submit a contribution.",
            code="not_the_author",
        )
    try:
        ensure_submittable(record)
        updated = await contributions.submit(contribution_id)
    except NotSubmittableError as error:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(error),
            code="contribution_incomplete",
        ) from None
    except ContributionRuleError as error:
        raise ApiError(
            status.HTTP_409_CONFLICT, str(error), code="invalid_contribution_state"
        ) from None

    _logger.info(
        "contribution submitted for review",
        extra={
            "user_id": principal.external_user_id,
            "domain": asset_record.domain,
            "equipment": asset_record.code,
            "request_id": get_request_id(request),
        },
    )
    return _view(updated, viewer_id=principal.external_user_id, is_reviewer=False)


@router.post("/{contribution_id}/decision", response_model=ContributionView)
async def decide_contribution(
    payload: DecisionRequest,
    request: Request,
    contribution_id: str = Path(...),
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    principal: Principal = Depends(RequireScope(equipment_param="asset")),
    capability: ReviewerCapability = Depends(RequireReviewer()),
    contributions: ContributionsRepositoryPort = Depends(get_contributions),
) -> ContributionView:
    """Aprueba o rechaza un aporte.

    Aprobar **no publica**: marca el aporte como válido y lo deja listo para
    que una futura versión lo recoja. Un rechazo exige motivo; sin él, el
    autor no puede corregir nada.
    """
    record, _ = await _visible(
        contribution_id,
        contributions=contributions,
        asset=asset_record,
        principal=principal,
        capability=capability,
    )
    reason = normalize_text(payload.reason)
    if not payload.approve and not reason:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Rejecting a contribution requires a reason.",
            code="reason_required",
        )
    if record.author_id == principal.external_user_id and not principal.is_admin:
        # Nadie valida su propio aporte: la revisión existe para que otra
        # persona lo mire.
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "A contribution cannot be reviewed by its own author.",
            code="self_review_denied",
        )

    target = ContributionState.APPROVED if payload.approve else ContributionState.REJECTED
    try:
        updated = await contributions.decide(
            contribution_id,
            state=target,
            actor=principal.external_user_id,
            actor_name=principal.display_name,
            reason=reason,
        )
    except ContributionRuleError as error:
        raise ApiError(
            status.HTTP_409_CONFLICT, str(error), code="invalid_contribution_state"
        ) from None

    _logger.info(
        "contribution decided",
        extra={
            "user_id": principal.external_user_id,
            "domain": asset_record.domain,
            "equipment": asset_record.code,
            "decision": target.value,
            "request_id": get_request_id(request),
        },
    )
    return _view(updated, viewer_id=principal.external_user_id, is_reviewer=True)


@router.get("/{contribution_id}/audio")
async def read_audio(
    contribution_id: str = Path(...),
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    principal: Principal = Depends(RequireScope(equipment_param="asset")),
    reviewer: ReviewerCapability = Depends(reviewer_capability),
    contributions: ContributionsRepositoryPort = Depends(get_contributions),
    storage: ArtifactStoragePort = Depends(get_artifact_storage),
) -> Response:
    """Devuelve la nota de voz para escucharla.

    Pasa por la misma comprobación que el resto: solo el autor y quien pueda
    revisar el alcance. El audio de planta puede contener información
    interna, así que no se sirve desde un directorio estático.
    """
    record, _ = await _visible(
        contribution_id,
        contributions=contributions,
        asset=asset_record,
        principal=principal,
        capability=reviewer,
    )
    if record.audio is None:
        raise _not_found()
    try:
        data = await storage.get(record.audio.storage_key)
    except Exception:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The private artifact storage is temporarily unavailable.",
            code="artifact_storage_unavailable",
        ) from None
    return Response(
        content=data,
        media_type=record.audio.content_type or "application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )
