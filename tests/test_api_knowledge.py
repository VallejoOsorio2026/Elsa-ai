"""API de consulta del conocimiento publicado (usuario normal)."""

from typing import Any

import httpx
import pytest

from elsa.adapters.fake_auth import ADMIN_ID, ENGINEER_ID, REVIEWER_ID
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.ports.knowledge import TechnicalAssetRecord
from tests.conftest import ENGINEER_TOKEN, REVIEWER_TOKEN, auth_header
from tests.fixtures_sources import engineering_workbook, sap_export

pytestmark = pytest.mark.anyio

DOMAIN = "mantenimiento"
ASSET = "tampella"
BASE = f"/api/v1/technical/{DOMAIN}/{ASSET}"
PUBLIC = f"/api/v1/knowledge/{DOMAIN}/{ASSET}"

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
async def asset(
    permissions: InMemoryPermissionsRepository, knowledge: InMemoryKnowledgeRepository
) -> TechnicalAssetRecord:
    await permissions.bootstrap_admin(subject=ADMIN_ID)
    for subject in (ENGINEER_ID, REVIEWER_ID):
        await permissions.grant_permission(
            subject=subject, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
        )
    await permissions.grant_reviewer(
        subject=REVIEWER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )
    return await knowledge.create_asset(code=ASSET, name="Activo de prueba", domain=DOMAIN)


async def _publish(api: httpx.AsyncClient) -> dict[str, Any]:
    body = (
        await api.post(
            f"{BASE}/engineering-bom",
            files={"file": ("bom.xlsx", engineering_workbook(), XLSX_TYPE)},
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()
    await api.post(
        f"{BASE}/versions/{body['version_id']}/review",
        json={"decision": "approved"},
        headers=auth_header(REVIEWER_TOKEN),
    )
    await api.post(
        f"{BASE}/versions/{body['version_id']}/publish", headers=auth_header(REVIEWER_TOKEN)
    )
    result: dict[str, Any] = body
    return result


async def test_a_user_without_permission_is_denied(
    api: httpx.AsyncClient,
    asset: TechnicalAssetRecord,
    permissions: InMemoryPermissionsRepository,
) -> None:
    await permissions.revoke_permission(
        subject=ENGINEER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )

    response = await api.get(PUBLIC, headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 403


async def test_nothing_is_shown_before_anything_is_published(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    """Nadie debe operar un equipo con una lista que no validó nadie."""
    summary = (await api.get(PUBLIC, headers=auth_header(ENGINEER_TOKEN))).json()

    assert summary["published"] is False
    assert summary["warnings"][0]["code"] == "no_published_bom"
    components = (await api.get(f"{PUBLIC}/components", headers=auth_header(ENGINEER_TOKEN))).json()
    assert components == []


async def test_a_pending_version_is_not_visible_to_a_normal_user(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    await api.post(
        f"{BASE}/engineering-bom",
        files={"file": ("bom.xlsx", engineering_workbook(), XLSX_TYPE)},
        headers=auth_header(REVIEWER_TOKEN),
    )

    summary = (await api.get(PUBLIC, headers=auth_header(ENGINEER_TOKEN))).json()

    assert summary["published"] is False


async def test_the_published_bom_is_served(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    await _publish(api)

    components = (await api.get(f"{PUBLIC}/components", headers=auth_header(ENGINEER_TOKEN))).json()

    assert len(components) == 3
    assert components[0]["component"] == "Rodamiento ficticio"
    assert components[0]["quantity"] == "2"
    assert components[0]["drawing"] == "PL-001"


async def test_internal_identifiers_are_never_exposed(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    """Al de planta le sirven el plano y el código, no los UUID."""
    await _publish(api)

    components = (await api.get(f"{PUBLIC}/components", headers=auth_header(ENGINEER_TOKEN))).json()

    forbidden = {"component_id", "id", "version_id", "import_id", "match_rule", "change_kind"}
    assert forbidden.isdisjoint(set(components[0]))


async def test_a_component_without_a_sap_code_is_still_served(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    await _publish(api)

    components = (await api.get(f"{PUBLIC}/components", headers=auth_header(ENGINEER_TOKEN))).json()

    assert any(component["sap_code"] is None for component in components)


async def test_published_failure_modes_carry_the_computed_rpn(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    await _publish(api)

    modes = (await api.get(f"{PUBLIC}/failure-modes", headers=auth_header(ENGINEER_TOKEN))).json()

    assert modes[0]["rpn"] == 84


async def test_sap_differences_appear_as_a_warning_not_as_a_report(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    """Se avisa de que hay desviaciones; el detalle es de revisión técnica."""
    await _publish(api)
    snapshot = (
        await api.post(
            f"{BASE}/sap-snapshots",
            files={"file": ("export.htm", sap_export(), "text/html")},
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()
    await api.post(
        f"{BASE}/reconciliations",
        json={"snapshot_id": snapshot["snapshot_id"]},
        headers=auth_header(REVIEWER_TOKEN),
    )

    summary = (await api.get(PUBLIC, headers=auth_header(ENGINEER_TOKEN))).json()

    warning = summary["warnings"][0]
    assert warning["code"] == "sap_differences_reported"
    assert "10000001" not in warning["message"]


async def test_a_normal_user_cannot_reach_the_reconciliation_detail(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    await _publish(api)

    response = await api.get(f"{BASE}/reconciliations", headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code in (403, 405, 404)
