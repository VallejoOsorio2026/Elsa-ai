"""Siembra de datos **sintéticos** para la demostración del Bloque 3.

Ningún dato de este módulo procede de la Planta Molino Barbosa. Los códigos
SAP, las descripciones y los modos de falla están inventados para poder
enseñar la interfaz sin sacar información real de PAPELSA.

Tres salvaguardas impiden que esto contamine un ambiente serio:

1. Solo se ejecuta si ``ELSA_DEMO_SEED`` está activo.
2. Solo se ejecuta en el ambiente DEV.
3. Solo se ejecuta sobre adaptadores **en memoria**. Si los permisos o el
   conocimiento apuntan a PostgreSQL, la siembra se salta y lo registra.
   Escribir datos de demostración en una base real sería indistinguible de
   un dato de planta al día siguiente.
"""

import logging
from decimal import Decimal

from elsa.adapters.fake_auth import ADMIN_ID, ENGINEER_ID, OTHER_REVIEWER_ID, REVIEWER_ID
from elsa.adapters.fake_materials_identity import FakeMaterialsIdentityAdapter
from elsa.adapters.memory_contributions import InMemoryContributionsRepository
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.config import Environment, Settings
from elsa.ingestion.model import ParsedBomRow, ParsedFailureMode
from elsa.ports.knowledge import (
    AssetAlreadyExistsError,
    EngineeringVersionInput,
    ImportKind,
    ResolvedBomRow,
    VersionState,
)
from elsa.ports.materials_identity import MaterialsProfile

_logger = logging.getLogger("elsa.demo.seed")

DOMAIN = "mantenimiento"
ASSET_CODE = "tampella"
ASSET_NAME = "Máquina de papel Tampella"

SEED_ACTOR = "demo-seed"

# Nombre visible de cada persona del piloto. Se usa en los dos sitios que
# deben coincidir: el perfil de Materiales y la cuenta de ELSA.
DISPLAY_NAMES = {
    ENGINEER_ID: "Ingeniero de mantenimiento (demo)",
    REVIEWER_ID: "Revisora técnica (demo)",
    OTHER_REVIEWER_ID: "Segundo revisor (demo)",
    ADMIN_ID: "Administradora (demo)",
}

# Personas del piloto. Los identificadores son los del adaptador fake de
# autenticación: la demostración usa la misma cadena de confianza que el
# resto de la API, no un atajo paralelo.
ENGINEER = ENGINEER_ID
ADMIN = ADMIN_ID
REVIEWER = REVIEWER_ID
OTHER_REVIEWER = OTHER_REVIEWER_ID

# BOM sintético. Suficiente para que la búsqueda literal del piloto tenga
# algo que encontrar, y deliberadamente pequeño.
_BOM: tuple[dict[str, object], ...] = (
    {
        "position": "10",
        "subsystem_name": "Sección de prensas",
        "component_name": "Rodamiento rodillo prensa inferior",
        "sap_code": "SYN-100001",
        "technical_description": "Rodamiento de rodillos a rótula, eje 220 mm (dato sintético)",
        "quantity": Decimal("2"),
        "unit": "UN",
        "assembly_drawing": "SYN-PL-001",
        "drawing_reference": "SYN-PL-001-A",
    },
    {
        "position": "20",
        "subsystem_name": "Sección de prensas",
        "component_name": "Camisa rodillo prensa superior",
        "sap_code": "SYN-100002",
        "technical_description": "Camisa de caucho, dureza 92 ShA (dato sintético)",
        "quantity": Decimal("1"),
        "unit": "UN",
        "assembly_drawing": "SYN-PL-001",
        "drawing_reference": "SYN-PL-001-B",
    },
    {
        "position": "30",
        "subsystem_name": "Sección de secado",
        "component_name": "Junta rotativa de vapor",
        "sap_code": "SYN-100003",
        "technical_description": "Junta rotativa autosoportada 2 pulgadas (dato sintético)",
        "quantity": Decimal("6"),
        "unit": "UN",
        "assembly_drawing": "SYN-PL-002",
        "drawing_reference": "SYN-PL-002-A",
    },
    {
        "position": "40",
        "subsystem_name": "Sección de secado",
        "component_name": "Purgador de condensado",
        "sap_code": "SYN-100004",
        "technical_description": "Purgador termodinámico DN25 (dato sintético)",
        "quantity": Decimal("12"),
        "unit": "UN",
        "assembly_drawing": "SYN-PL-002",
        "drawing_reference": None,
    },
    {
        "position": "50",
        "subsystem_name": "Accionamiento principal",
        "component_name": "Acople elástico motor-reductor",
        "sap_code": "SYN-100005",
        "technical_description": "Acople de garras con elastómero (dato sintético)",
        "quantity": Decimal("1"),
        "unit": "UN",
        "assembly_drawing": "SYN-PL-003",
        "drawing_reference": "SYN-PL-003-A",
    },
    {
        "position": "60",
        "subsystem_name": "Accionamiento principal",
        "component_name": "Reductor principal",
        "sap_code": "SYN-100006",
        "technical_description": "Reductor de ejes paralelos i=12,5 (dato sintético)",
        "quantity": Decimal("1"),
        "unit": "UN",
        "assembly_drawing": "SYN-PL-003",
        "drawing_reference": None,
    },
    {
        "position": "70",
        "subsystem_name": "Sistema de lubricación",
        "component_name": "Bomba de aceite de lubricación",
        "sap_code": "SYN-100007",
        "technical_description": "Bomba de engranajes 40 L/min (dato sintético)",
        "quantity": Decimal("2"),
        "unit": "UN",
        "assembly_drawing": "SYN-PL-004",
        "drawing_reference": "SYN-PL-004-A",
    },
    {
        "position": "80",
        "subsystem_name": "Sistema de lubricación",
        "component_name": "Filtro de aceite en línea",
        "sap_code": "SYN-100008",
        "technical_description": "Filtro dúplex 10 micras (dato sintético)",
        "quantity": Decimal("4"),
        "unit": "UN",
        "assembly_drawing": "SYN-PL-004",
        "drawing_reference": None,
    },
)

_FAILURE_MODES: tuple[dict[str, object], ...] = (
    {
        "subsystem_name": "Sección de prensas",
        "component_name": "Rodamiento rodillo prensa inferior",
        "sap_code": "SYN-100001",
        "failure_mode": "Desgaste por contaminación del lubricante",
        "effect": "Vibración creciente y parada no programada de la sección",
        "cause": "Ingreso de agua al alojamiento por sello deteriorado",
        "severity": 8,
        "occurrence": 4,
        "detection": 3,
        "action": "Ruta de vibraciones mensual y cambio de sello anual",
        "preventive_plan": "PM-SYN-01",
    },
    {
        "subsystem_name": "Sección de secado",
        "component_name": "Junta rotativa de vapor",
        "sap_code": "SYN-100003",
        "failure_mode": "Fuga de vapor por cara de sello",
        "effect": "Pérdida de eficiencia térmica y riesgo de quemadura",
        "cause": "Desalineación del cabezal por dilatación",
        "severity": 7,
        "occurrence": 5,
        "detection": 2,
        "action": "Inspección termográfica trimestral",
        "preventive_plan": "PM-SYN-02",
    },
    {
        "subsystem_name": "Accionamiento principal",
        "component_name": "Reductor principal",
        "sap_code": "SYN-100006",
        "failure_mode": "Picadura en dentado de primera etapa",
        "effect": "Ruido, pérdida de par y avería mayor si progresa",
        "cause": "Aceite fuera de especificación",
        "severity": 9,
        "occurrence": 2,
        "detection": 5,
        "action": "Análisis de aceite semestral",
        "preventive_plan": "PM-SYN-03",
    },
)


def should_seed(settings: Settings) -> bool:
    """Decide si la siembra sintética procede en este ambiente."""
    return settings.demo_seed and settings.env is Environment.DEV


async def seed_demo_data(
    *,
    permissions: object,
    knowledge: object,
    settings: Settings,
    materials_identity: object = None,
    contributions: object = None,
) -> bool:
    """Siembra permisos y conocimiento sintéticos. Devuelve si sembró.

    Se niega a escribir sobre cualquier almacén que no sea el de memoria.
    """
    if not should_seed(settings):
        return False
    if not isinstance(permissions, InMemoryPermissionsRepository) or not isinstance(
        knowledge, InMemoryKnowledgeRepository
    ):
        _logger.warning(
            "demo seed skipped: it only runs against in-memory stores, "
            "never against a real database"
        )
        return False

    # Sin perfil vigente en Materiales, la cadena de confianza rechaza a la
    # persona antes de mirar sus permisos. La demostración usa esa misma
    # cadena, así que sus identidades también tienen que existir allí.
    if isinstance(materials_identity, FakeMaterialsIdentityAdapter):
        _seed_identities(materials_identity)

    await _seed_permissions(permissions)
    await _seed_knowledge(knowledge)
    if isinstance(contributions, InMemoryContributionsRepository):
        await _seed_contributors(contributions)
    _logger.info("synthetic demo data seeded", extra={"asset": ASSET_CODE, "domain": DOMAIN})
    return True


def _seed_identities(identity: FakeMaterialsIdentityAdapter) -> None:
    """Da de alta las personas del piloto en la fuente de identidad fake."""
    for user_id, display_name in DISPLAY_NAMES.items():
        identity.set_profile(
            MaterialsProfile(user_id=user_id, display_name=display_name, is_active=True)
        )


async def _seed_permissions(permissions: InMemoryPermissionsRepository) -> None:
    """Cuatro personas con capacidades distintas, para poder enseñar los límites."""
    # Ingeniero de mantenimiento: lee el equipo. No revisa.
    await permissions.grant_permission(
        subject=ENGINEER,
        domain=DOMAIN,
        equipment=ASSET_CODE,
        actor=SEED_ACTOR,
        display_name=DISPLAY_NAMES[ENGINEER],
    )
    # Revisor técnico: lee y además valida lo que otros aportan.
    await permissions.grant_permission(
        subject=REVIEWER,
        domain=DOMAIN,
        equipment=ASSET_CODE,
        actor=SEED_ACTOR,
        display_name=DISPLAY_NAMES[REVIEWER],
    )
    await permissions.grant_reviewer(
        subject=REVIEWER,
        domain=DOMAIN,
        equipment=ASSET_CODE,
        actor=SEED_ACTOR,
    )
    # Segundo revisor: existe para poder demostrar que una decisión la puede
    # revertir otra persona con el mismo alcance.
    await permissions.grant_permission(
        subject=OTHER_REVIEWER,
        domain=DOMAIN,
        equipment=ASSET_CODE,
        actor=SEED_ACTOR,
        display_name=DISPLAY_NAMES[OTHER_REVIEWER],
    )
    await permissions.grant_reviewer(
        subject=OTHER_REVIEWER,
        domain=DOMAIN,
        equipment=ASSET_CODE,
        actor=SEED_ACTOR,
    )
    # Administradora: cuenta activa y bandera de administración.
    await permissions.grant_permission(
        subject=ADMIN,
        domain=DOMAIN,
        equipment=None,
        actor=SEED_ACTOR,
        display_name=DISPLAY_NAMES[ADMIN],
    )
    await permissions.set_account_admin(subject=ADMIN, is_admin=True, actor=SEED_ACTOR)


async def _seed_contributors(contributions: InMemoryContributionsRepository) -> None:
    """Habilita para aportar a quienes trabajan el equipo.

    La administradora no aparece: pasa por ser administradora, igual que en
    la revisión. Consultar, aportar y revisar siguen siendo tres capacidades
    distintas, y esta siembra las reparte para poder enseñar la diferencia.
    """
    for subject in (ENGINEER, REVIEWER, OTHER_REVIEWER):
        await contributions.set_contributor(
            subject, domain=DOMAIN, asset_code=ASSET_CODE, enabled=True
        )


async def _seed_knowledge(knowledge: InMemoryKnowledgeRepository) -> None:
    """Crea el activo y publica una versión sintética del BOM."""
    try:
        asset = await knowledge.create_asset(
            code=ASSET_CODE,
            name=ASSET_NAME,
            domain=DOMAIN,
            description="Activo de demostración con datos sintéticos.",
        )
    except AssetAlreadyExistsError:
        existing = await knowledge.get_asset(ASSET_CODE)
        if existing is None:  # pragma: no cover - imposible por construcción
            raise
        asset = existing

    if await knowledge.get_published_version(asset.id) is not None:
        return

    record = await knowledge.start_import(
        asset_id=asset.id,
        kind=ImportKind.ENGINEERING_BOM,
        sha256="0" * 64,
        byte_size=0,
        storage_key="demo/synthetic-bom",
        uploaded_by=SEED_ACTOR,
        original_filename="bom-sintetico-demo.xlsx",
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    rows = [
        ResolvedBomRow(row=ParsedBomRow(source_row=index + 2, **entry))  # type: ignore[arg-type]
        for index, entry in enumerate(_BOM)
    ]
    modes = [
        ParsedFailureMode(source_row=index + 2, **entry)  # type: ignore[arg-type]
        for index, entry in enumerate(_FAILURE_MODES)
    ]

    version = await knowledge.store_engineering_version(
        EngineeringVersionInput(
            asset_id=asset.id,
            import_id=record.id,
            source_artifact_id=record.source_artifact_id,
            rows=rows,
            failure_modes=modes,
        ),
        actor=SEED_ACTOR,
    )
    await knowledge.set_version_state(version_id=version.id, state=VersionState.APPROVED)
    await knowledge.publish_version(version_id=version.id, actor=SEED_ACTOR)
