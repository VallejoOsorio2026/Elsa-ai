"""API de consulta del conocimiento técnico publicado.

Lo que ve un ingeniero de planta. Tres diferencias deliberadas respecto de
la API de revisión:

- **Solo conocimiento publicado.** Una versión pendiente o rechazada no
  existe para este endpoint. Nadie debe operar un equipo con una lista que
  todavía no validó nadie.
- **Sin identificadores internos.** El UUID del componente, el de la
  versión, el de la importación y el de la reconciliación no aparecen. Son
  la mecánica interna del sistema; a quien va a cambiar un rodamiento le
  sirven el plano, la referencia y el código SAP.
- **Discrepancias como advertencia, no como informe.** Si la comparación
  contra SAP encontró diferencias, se avisa de que las hay. El detalle
  —qué dice Ingeniería, qué dice SAP, en qué renglón— es material de
  revisión técnica, no de consulta operativa.

La autorización es la del Bloque 1, sin cambios: ``RequireScope`` decide
antes de recuperar nada.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from elsa.api.deps import RequireScope, get_knowledge
from elsa.api.v1.technical import resolve_asset
from elsa.core.authorization import Principal
from elsa.ports.knowledge import KnowledgeRepositoryPort, TechnicalAssetRecord

router = APIRouter(prefix="/knowledge/{domain}/{asset}", tags=["knowledge"])

# Clasificaciones que no son coincidencia. Sirven para contar advertencias,
# no para exponer el detalle.
_DISCREPANCIES = frozenset(
    {
        "engineering_only",
        "sap_only",
        "quantity_difference",
        "duplicate_or_structural_difference",
        "unresolved",
    }
)


class PublishedComponentView(BaseModel):
    """Un renglón del BOM publicado, en los términos de quien lo consulta."""

    position: str | None = None
    subsystem: str | None = None
    component: str | None = None
    sap_code: str | None = None
    description: str | None = None
    quantity: str | None = None
    unit: str | None = None
    drawing: str | None = None
    drawing_reference: str | None = None
    model_reference: str | None = None


class PublishedFailureModeView(BaseModel):
    subsystem: str | None = None
    component: str | None = None
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


class KnowledgeWarning(BaseModel):
    """Advertencia comprensible, sin detalle administrativo."""

    code: str
    message: str


class AssetKnowledgeView(BaseModel):
    asset: str
    name: str
    domain: str
    published: bool
    source: str | None = None
    """Descripción legible de la fuente y su versión."""

    published_at: str | None = None
    components: int = 0
    subsystems: int = 0
    warnings: list[KnowledgeWarning] = Field(default_factory=list)


def _no_published_version() -> KnowledgeWarning:
    return KnowledgeWarning(
        code="no_published_bom",
        message=(
            "This asset has no published engineering BOM yet. Nothing has been validated, "
            "so nothing is shown."
        ),
    )


async def _discrepancy_warning(
    knowledge: KnowledgeRepositoryPort, asset_id: str, version_id: str
) -> KnowledgeWarning | None:
    """Avisa de que la última comparación con SAP encontró diferencias.

    Se cuentan, no se detallan. Que exista una desviación es relevante para
    quien va a intervenir el equipo; cuál es exactamente y quién tiene razón
    es trabajo de revisión técnica.
    """
    runs = await knowledge.list_reconciliations(asset_id)
    latest = next((run for run in runs if run.version_id == version_id), None)
    if latest is None:
        return None
    total = sum(count for name, count in latest.stats.items() if name in _DISCREPANCIES)
    if total == 0:
        return None
    return KnowledgeWarning(
        code="sap_differences_reported",
        message=(
            f"The last comparison against SAP found {total} line(s) that do not match the "
            "approved engineering BOM. What is shown here is the approved BOM. Check with "
            "technical review before ordering or replacing parts."
        ),
    )


@router.get("", response_model=AssetKnowledgeView)
async def read_asset(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _principal: Principal = Depends(RequireScope(equipment_param="asset")),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> AssetKnowledgeView:
    """Resumen del activo y de su BOM publicado vigente."""
    published = await knowledge.get_published_version(asset_record.id)
    if published is None:
        return AssetKnowledgeView(
            asset=asset_record.code,
            name=asset_record.name,
            domain=asset_record.domain,
            published=False,
            warnings=[_no_published_version()],
        )

    items = await knowledge.list_version_items(published.id)
    warnings = []
    discrepancy = await _discrepancy_warning(knowledge, asset_record.id, published.id)
    if discrepancy is not None:
        warnings.append(discrepancy)

    return AssetKnowledgeView(
        asset=asset_record.code,
        name=asset_record.name,
        domain=asset_record.domain,
        published=True,
        source=f"Approved engineering BOM, version {published.version_number}",
        published_at=None if published.published_at is None else published.published_at.isoformat(),
        components=len(items),
        subsystems=len({item.subsystem_name for item in items if item.subsystem_name}),
        warnings=warnings,
    )


@router.get("/components", response_model=list[PublishedComponentView])
async def list_components(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _principal: Principal = Depends(RequireScope(equipment_param="asset")),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> list[PublishedComponentView]:
    """Componentes del BOM publicado.

    Un componente sin código SAP se devuelve igual: no tener código no lo
    hace menos real ni menos necesario para mantener el equipo.
    """
    published = await knowledge.get_published_version(asset_record.id)
    if published is None:
        return []
    return [
        PublishedComponentView(
            position=item.position,
            subsystem=item.subsystem_name,
            component=item.component_name,
            sap_code=item.sap_code,
            description=item.technical_description,
            quantity=None if item.quantity is None else str(item.quantity),
            unit=item.unit,
            drawing=item.assembly_drawing,
            drawing_reference=item.drawing_reference,
            model_reference=item.model_reference,
        )
        for item in await knowledge.list_version_items(published.id)
    ]


@router.get("/failure-modes", response_model=list[PublishedFailureModeView])
async def list_failure_modes(
    asset_record: TechnicalAssetRecord = Depends(resolve_asset),
    _principal: Principal = Depends(RequireScope(equipment_param="asset")),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> list[PublishedFailureModeView]:
    """AMEF publicado, con el NPR calculado por el backend."""
    published = await knowledge.get_published_version(asset_record.id)
    if published is None:
        return []
    return [
        PublishedFailureModeView(
            subsystem=mode.subsystem_name,
            component=mode.component_name,
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
        )
        for mode in await knowledge.list_failure_modes(published.id)
    ]
