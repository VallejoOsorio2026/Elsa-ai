"""Chat piloto: preguntar sobre un equipo y recibir evidencias.

**No hay modelo de lenguaje detrás de este endpoint.** La respuesta se
construye con una búsqueda literal sobre el BOM y el AMEF publicados
(:mod:`elsa.core.retrieval`) y una plantilla fija. La interfaz lo declara y
la propia respuesta lo lleva marcado en ``engine`` e ``is_generated``.

Se hace así por una razón concreta: un ingeniero que va a intervenir un
equipo necesita saber si lo que lee es un dato aprobado o una redacción
automática. Mientras no exista el motor definitivo, el sistema dice
exactamente lo que hace.

Tres reglas de fondo:

- **Solo conocimiento publicado.** Una versión pendiente no se consulta
  aquí, igual que en :mod:`elsa.api.v1.knowledge`.
- **La autorización va antes de recuperar.** ``resolve_asset`` aplica
  ``RequireScope`` como sub-dependencia, así que nada se lee sin permiso.
- **Los adjuntos del chat no se leen ni se guardan.** Este endpoint no
  recibe archivos: solo su declaración, para poder validar los límites y
  responder que el camino del conocimiento es «Agregar conocimiento». Un
  adjunto de conversación nunca se convierte en conocimiento por sí solo.
"""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from elsa.api.deps import get_knowledge, get_settings
from elsa.api.errors import ApiError
from elsa.api.v1.technical import resolve_asset
from elsa.config import Settings
from elsa.core.retrieval import Match, candidates_from, parse_query, search
from elsa.ports.knowledge import (
    BomItemRecord,
    FailureModeRecord,
    KnowledgeRepositoryPort,
    TechnicalAssetRecord,
)

router = APIRouter(prefix="/assistant/{domain}/{asset}", tags=["assistant"])

ENGINE = "literal_search"
ENGINE_LABEL = "Búsqueda literal sobre el conocimiento publicado (sin modelo de lenguaje)"

_MAX_RESULTS = 8


class AttachmentDeclaration(BaseModel):
    """Un adjunto que el navegador dice tener. El archivo no se envía."""

    filename: str = Field(max_length=255)
    byte_size: int = Field(ge=0)
    content_type: str | None = Field(default=None, max_length=255)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    attachments: list[AttachmentDeclaration] = Field(default_factory=list)


class ComponentEvidence(BaseModel):
    """Un renglón publicado que coincidió, con el motivo de la coincidencia."""

    subsystem: str | None = None
    component: str | None = None
    sap_code: str | None = None
    description: str | None = None
    quantity: str | None = None
    unit: str | None = None
    drawing: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    matched_code: str | None = None


class FailureModeEvidence(BaseModel):
    subsystem: str | None = None
    component: str | None = None
    sap_code: str | None = None
    failure_mode: str | None = None
    effect: str | None = None
    cause: str | None = None
    rpn: int | None = None
    action: str | None = None
    matched_terms: list[str] = Field(default_factory=list)
    matched_code: str | None = None


class AskResponse(BaseModel):
    """Respuesta del piloto: siempre dice cómo se construyó."""

    asset: str
    asset_name: str
    domain: str

    engine: str = ENGINE
    engine_label: str = ENGINE_LABEL
    is_generated: bool = False
    """Falso siempre en el piloto: ningún texto lo redacta un modelo."""

    published: bool
    source: str | None = None
    message: str
    terms: list[str] = Field(default_factory=list)
    codes: list[str] = Field(default_factory=list)
    components: list[ComponentEvidence] = Field(default_factory=list)
    failure_modes: list[FailureModeEvidence] = Field(default_factory=list)
    attachment_note: str | None = None


def _validate_attachments(
    attachments: list[AttachmentDeclaration], settings: Settings
) -> str | None:
    """Aplica los límites en el servidor y explica qué pasa con los archivos.

    El navegador ya avisa, pero el que decide es el backend: un cliente
    modificado choca aquí igual.
    """
    if not attachments:
        return None
    if len(attachments) > settings.contribution_max_attachments:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"A message accepts at most {settings.contribution_max_attachments} attachments.",
            code="too_many_attachments",
        )
    total = sum(item.byte_size for item in attachments)
    if total > settings.contribution_max_attachment_bytes:
        limit_mb = settings.contribution_max_attachment_bytes // (1024 * 1024)
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The attachments of a message cannot exceed {limit_mb} MB in total.",
            code="attachments_too_large",
        )
    count = len(attachments)
    noun = "archivo adjunto" if count == 1 else "archivos adjuntos"
    return (
        f"Anoté {count} {noun} en la conversación. No los abrí ni los guardé: un adjunto "
        "de chat no se convierte en conocimiento. Para que forme parte del conocimiento "
        "del equipo, envíalo desde «Agregar conocimiento» y pasará por revisión."
    )


def _component_evidence(match: Match[BomItemRecord]) -> ComponentEvidence:
    item = match.payload
    return ComponentEvidence(
        subsystem=item.subsystem_name,
        component=item.component_name,
        sap_code=item.sap_code,
        description=item.technical_description,
        quantity=None if item.quantity is None else str(item.quantity),
        unit=item.unit,
        drawing=item.assembly_drawing,
        matched_terms=list(match.matched_terms),
        matched_code=match.matched_code,
    )


def _failure_evidence(match: Match[FailureModeRecord]) -> FailureModeEvidence:
    mode = match.payload
    return FailureModeEvidence(
        subsystem=mode.subsystem_name,
        component=mode.component_name,
        sap_code=mode.sap_code,
        failure_mode=mode.failure_mode,
        effect=mode.effect,
        cause=mode.cause,
        rpn=mode.rpn,
        action=mode.action,
        matched_terms=list(match.matched_terms),
        matched_code=match.matched_code,
    )


def _quote(values: list[str]) -> str:
    return ", ".join(f"«{value}»" for value in values)


def _build_message(
    *,
    components: int,
    failure_modes: int,
    terms: list[str],
    codes: list[str],
    version_label: str,
) -> str:
    """Redacta la respuesta con una plantilla fija, no con un modelo."""
    looked_for = _quote(codes + terms)
    if components == 0 and failure_modes == 0:
        return (
            f"No encontré ningún renglón que contenga {looked_for} en {version_label}. "
            "Eso no significa que no exista en el equipo: significa que no está escrito "
            "en el conocimiento publicado. Si lo conoces, puedes aportarlo desde "
            "«Agregar conocimiento»."
        )
    partes = []
    if components:
        partes.append(f"{components} componente(s) del BOM")
        # El BOM publicado es la lista aprobada; decirlo evita que se lea
        # como un inventario en tiempo real.
    if failure_modes:
        partes.append(f"{failure_modes} modo(s) de falla del AMEF")
    return (
        f"Encontré {' y '.join(partes)} que contienen {looked_for} en {version_label}. "
        "Debajo está cada coincidencia con el término exacto que la produjo."
    )


@router.post("/ask", response_model=AskResponse)
async def ask(
    payload: AskRequest,
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
    settings: Settings = Depends(get_settings),
) -> AskResponse:
    """Busca la pregunta en el conocimiento publicado del equipo."""
    attachment_note = _validate_attachments(payload.attachments, settings)
    query = parse_query(payload.question)

    base = AskResponse(
        asset=asset_record.code,
        asset_name=asset_record.name,
        domain=asset_record.domain,
        published=False,
        message="",
        terms=list(query.terms),
        codes=list(query.codes),
        attachment_note=attachment_note,
    )

    published = await knowledge.get_published_version(asset_record.id)
    if published is None:
        base.message = (
            f"{asset_record.name} todavía no tiene un BOM publicado. No hay nada validado "
            "que consultar, así que no muestro nada. Un BOM sin revisar no es conocimiento."
        )
        return base

    version_label = f"la versión publicada {published.version_number} del BOM aprobado"
    base.published = True
    base.source = f"BOM de Ingeniería aprobado, versión {published.version_number}"

    if not query.is_searchable:
        base.message = (
            "No pude extraer ningún término buscable de tu pregunta. Escribe el nombre de "
            "un componente, un subsistema o un código de material; la búsqueda de este "
            "piloto es literal y necesita al menos una palabra concreta."
        )
        return base

    items = await knowledge.list_version_items(published.id)
    modes = await knowledge.list_failure_modes(published.id)

    component_matches = search(
        query,
        candidates_from(
            items,
            text_fields=(
                "component_name",
                "subsystem_name",
                "technical_description",
                "assembly_drawing",
                "drawing_reference",
                "position",
            ),
            code_field="sap_code",
        ),
        limit=_MAX_RESULTS,
    )
    failure_matches = search(
        query,
        candidates_from(
            modes,
            text_fields=(
                "failure_mode",
                "component_name",
                "subsystem_name",
                "effect",
                "cause",
                "action",
                "preventive_plan",
            ),
            code_field="sap_code",
        ),
        limit=_MAX_RESULTS,
    )

    base.components = [_component_evidence(match) for match in component_matches]
    base.failure_modes = [_failure_evidence(match) for match in failure_matches]
    base.message = _build_message(
        components=len(component_matches),
        failure_modes=len(failure_matches),
        terms=list(query.terms),
        codes=list(query.codes),
        version_label=version_label,
    )
    return base
