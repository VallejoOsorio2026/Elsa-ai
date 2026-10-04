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

Además, y **solo** cuando la pregunta trae un código exacto sin ambigüedad
(:mod:`elsa.core.material_code`), la respuesta suma un bloque
``availability`` con la disponibilidad que Materiales devuelve **en vivo**.
Es aditivo: no sustituye ni altera la búsqueda sobre el BOM, y si Materiales
no responde, el bloque lo declara y el resto de la respuesta sigue igual.
Los hechos del bloque salen del contrato de Materiales; nada aquí los redacta
un modelo ni los completa.
"""

import logging

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from elsa.api.deps import bearer_token, get_container, get_knowledge, get_settings
from elsa.api.errors import ApiError
from elsa.api.v1.technical import resolve_asset
from elsa.config import Settings
from elsa.container import Container
from elsa.core.capability_outcomes import (
    UNBOUNDED_CLAIM_REFUSAL_MESSAGE,
    CapabilityCallStatus,
    CapabilityOutcome,
    UncomposableOutcomeError,
    interpret_inventory_lookup,
)
from elsa.core.coverage_policy import InventoryCoverageState
from elsa.core.material_code import (
    EXPECTED_MATERIALS_CONTRACT_VERSION,
    CodeDetectionKind,
    detect_exact_material_code,
)
from elsa.core.retrieval import Match, candidates_from, parse_query, search
from elsa.ports.knowledge import (
    BomItemRecord,
    FailureModeRecord,
    KnowledgeRepositoryPort,
    TechnicalAssetRecord,
)
from elsa.ports.materials import (
    MaterialLookupRequest,
    MaterialsContractViolationError,
    MaterialsLookupResult,
    MaterialsPort,
)

_logger = logging.getLogger("elsa.api.assistant")

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


class StockLocationEvidence(BaseModel):
    """Una fila del material en el inventario. Sus campos proceden de la misma fila."""

    center: str
    warehouse: str
    location: str | None = None
    """Opaca: se muestra sin interpretar. Nula significa «llegó sin ubicación»."""
    scope: str
    available: str
    committed: str


class MaterialFactsEvidence(BaseModel):
    """Lo que Materiales devolvió sobre el código.

    Descripción, unidad y código antiguo son agregados por campo: no se
    garantiza que provengan de la misma fila, y por eso no se presentan como tal.
    """

    code: str
    description: str | None = None
    unit: str | None = None
    old_code: str | None = None
    total_available: str
    total_committed: str
    totals_rule: str
    """Regla de Materiales que produjo los totales: no son dato crudo de SAP."""
    marked_for_discontinuation: bool
    """Señal de riesgo de Materiales. Acompaña al hecho; no lo oculta ni lo degrada."""
    locations: list[StockLocationEvidence] = Field(default_factory=list)


class AvailabilityProvenance(BaseModel):
    source: str
    capability: str
    contract_version: str
    inventory_version: int
    loaded_at: str
    """Cuándo terminó la carga en Materiales. No es la fecha de extracción de SAP."""
    read_at: str
    """Cuándo preguntó ELSA."""
    match_origin: str
    coverage_state: str


class AvailabilityBlock(BaseModel):
    """Disponibilidad viva de un código exacto, con su procedencia y sus límites."""

    status: str
    """``matched`` · ``not_returned`` · ``no_active_inventory`` · ``unavailable`` ·
    ``rejected`` · ``contract_error`` · ``ambiguous_code``."""
    message: str
    requested_code: str | None = None
    answer_status: str | None = None
    warnings: list[str] = Field(default_factory=list)
    material: MaterialFactsEvidence | None = None
    provenance: AvailabilityProvenance | None = None
    scope_note: str | None = None


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
    availability: AvailabilityBlock | None = None
    """Solo cuando la pregunta trae un código exacto. Aditivo: nunca altera el BOM."""


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


def get_materials(
    token: str = Depends(bearer_token),
    container: Container = Depends(get_container),
) -> MaterialsPort:
    """Puerto de inventario atado al token **de esta petición**.

    Se crea en cada petición y nada compartido lo conserva: el JWT vive en este
    objeto solo mientras dura la respuesta.
    """
    return container.materials_inventory(token)


@router.post("/ask", response_model=AskResponse)
async def ask(
    payload: AskRequest,
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
    settings: Settings = Depends(get_settings),
    materials: MaterialsPort = Depends(get_materials),
) -> AskResponse:
    """Busca la pregunta en el BOM publicado y, si trae un código exacto, en Materiales."""
    response = await _answer_from_published_knowledge(payload, asset_record, knowledge, settings)
    detection = detect_exact_material_code(payload.question)
    if detection.kind is CodeDetectionKind.NOT_APPLICABLE:
        return response
    if detection.kind is CodeDetectionKind.AMBIGUOUS:
        response.availability = AvailabilityBlock(
            status="ambiguous_code",
            message=(
                "Tu pregunta menciona más de un código de material. Consulto la disponibilidad "
                "de un solo código a la vez: pregunta por uno y lo consulto."
            ),
        )
        return response
    assert detection.code is not None  # noqa: S101 - SINGLE siempre lleva código
    response.availability = await _live_availability(
        materials,
        detection.code,
        other_facts_available=bool(response.components or response.failure_modes),
    )
    return response


async def _answer_from_published_knowledge(
    payload: AskRequest,
    asset_record: TechnicalAssetRecord,
    knowledge: KnowledgeRepositoryPort,
    settings: Settings,
) -> AskResponse:
    """La respuesta de siempre: búsqueda literal sobre el BOM y el AMEF publicados."""
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


# ---------------------------------------------------------------------
# Disponibilidad viva en Materiales
# ---------------------------------------------------------------------

_SESSION_REJECTED_MESSAGE = (
    "Materiales no aceptó tu sesión para esta consulta. Inicia sesión de nuevo. "
    "No es una ausencia de información."
)
_FORBIDDEN_MESSAGE = (
    "Materiales no autorizó esta consulta con tu sesión. No es una ausencia de información."
)
_REJECTED_MESSAGE = (
    "Materiales rechazó la sesión o el perfil no está activo allí. No se muestra ningún "
    "dato de inventario."
)
_CONTRACT_ERROR_MESSAGE = (
    "La respuesta de Materiales no cumple el contrato acordado, así que no la muestro. "
    "Es un fallo técnico, no una ausencia de información."
)

_STATUS_NAMES = {
    (CapabilityCallStatus.OK, CapabilityOutcome.MATCHED): "matched",
    (CapabilityCallStatus.OK, CapabilityOutcome.NOT_RETURNED): "not_returned",
    (CapabilityCallStatus.NO_ACTIVE_INVENTORY, None): "no_active_inventory",
    (CapabilityCallStatus.UNAVAILABLE, None): "unavailable",
}


async def _live_availability(
    materials: MaterialsPort, code: str, *, other_facts_available: bool
) -> AvailabilityBlock:
    """Consulta el código **tal cual** y traduce el resultado sin añadirle nada."""
    request = MaterialLookupRequest(
        contract_version=EXPECTED_MATERIALS_CONTRACT_VERSION, material_code=code
    )
    try:
        result = await materials.lookup_material_by_code(request)
        return _availability_from(
            materials, result, code, other_facts_available=other_facts_available
        )
    except (MaterialsContractViolationError, UncomposableOutcomeError):
        _logger.warning("materials response rejected", extra={"category": "contract"})
        return AvailabilityBlock(
            status="contract_error", message=_CONTRACT_ERROR_MESSAGE, requested_code=code
        )


def _availability_from(
    materials: MaterialsPort,
    result: MaterialsLookupResult,
    code: str,
    *,
    other_facts_available: bool,
) -> AvailabilityBlock:
    if result.call_status is CapabilityCallStatus.REJECTED:
        # Se resuelve antes de componer: no hay política de respuesta para esto.
        return AvailabilityBlock(status="rejected", message=_REJECTED_MESSAGE, requested_code=code)

    interpreted = interpret_inventory_lookup(
        result.as_capability_result(), other_facts_available=other_facts_available
    )
    block = AvailabilityBlock(
        status=_STATUS_NAMES[(result.call_status, result.outcome)],
        message=interpreted.message,
        requested_code=code,
        answer_status=interpreted.status.value,
        warnings=[warning.value for warning in interpreted.warnings],
    )

    if result.call_status is CapabilityCallStatus.UNAVAILABLE:
        failure = getattr(materials, "last_failure", None)
        if failure == "auth_401":
            block.message = _SESSION_REJECTED_MESSAGE
        elif failure == "forbidden":
            block.message = _FORBIDDEN_MESSAGE
        return block

    if result.coverage is not None and result.coverage.state is InventoryCoverageState.UNKNOWN:
        # Alcance desconocido: se dice, y no se disfraza de completo ni de incompleto.
        block.scope_note = UNBOUNDED_CLAIM_REFUSAL_MESSAGE

    if result.material is not None and result.attribution is not None:
        facts = result.material
        attribution = result.attribution
        block.material = MaterialFactsEvidence(
            code=facts.code,
            description=facts.descripcion,
            unit=facts.unidad,
            old_code=facts.material_antiguo,
            total_available=str(facts.total_disponible.value),
            total_committed=str(facts.total_comprometido.value),
            totals_rule=facts.total_disponible.rule_reference,
            marked_for_discontinuation=facts.dado_de_baja.value,
            locations=[
                StockLocationEvidence(
                    center=location.centro,
                    warehouse=location.almacen,
                    location=location.ubicacion,
                    scope=location.ambito,
                    available=str(location.disponible),
                    committed=str(location.comprometido),
                )
                for location in facts.stock_locations
            ],
        )
        block.provenance = AvailabilityProvenance(
            source=attribution.source,
            capability=attribution.capability,
            contract_version=attribution.contract_version,
            inventory_version=attribution.source_version.version_number,
            loaded_at=attribution.source_version.loaded_at.isoformat(),
            read_at=attribution.read_at.isoformat(),
            match_origin=attribution.match_origin.value,
            coverage_state=(
                result.coverage.state.value if result.coverage is not None else "unknown"
            ),
        )
    return block
