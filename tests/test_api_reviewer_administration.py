"""Administración de la capacidad de Revisor Técnico y de los activos."""

import httpx
import pytest

from elsa.adapters.fake_auth import ADMIN_ID, ENGINEER_ID, REVIEWER_ID
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from tests.conftest import ADMIN_TOKEN, ENGINEER_TOKEN, REVIEWER_TOKEN, auth_header

pytestmark = pytest.mark.anyio

DOMAIN = "mantenimiento"
ASSET = "tampella"
ADMIN = "/api/v1/admin"


@pytest.fixture
async def bootstrapped(permissions: InMemoryPermissionsRepository) -> None:
    await permissions.bootstrap_admin(subject=ADMIN_ID, display_name="Administradora")


async def test_only_an_administrator_may_grant_the_reviewer_capability(
    api: httpx.AsyncClient, bootstrapped: None, permissions: InMemoryPermissionsRepository
) -> None:
    await permissions.grant_permission(
        subject=REVIEWER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )
    await permissions.grant_reviewer(
        subject=REVIEWER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )

    response = await api.post(
        f"{ADMIN}/users/{ENGINEER_ID}/reviewer",
        json={"domain": DOMAIN, "equipment": ASSET},
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 403


async def test_a_reviewer_cannot_grant_itself_more_scope(
    api: httpx.AsyncClient, bootstrapped: None, permissions: InMemoryPermissionsRepository
) -> None:
    """Un revisor no administra seguridad ni se amplía el alcance."""
    await permissions.grant_reviewer(
        subject=REVIEWER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )

    response = await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer",
        json={"domain": DOMAIN},
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 403


async def test_an_administrator_grants_the_reviewer_capability(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    response = await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer",
        json={"domain": DOMAIN, "equipment": ASSET, "display_name": "Revisor"},
        headers=auth_header(ADMIN_TOKEN),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["domain"] == DOMAIN
    assert body["equipment"] == ASSET
    assert body["revoked_at"] is None


async def test_granting_the_reviewer_capability_is_idempotent(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    payload = {"domain": DOMAIN, "equipment": ASSET}
    first = await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer", json=payload, headers=auth_header(ADMIN_TOKEN)
    )

    second = await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer", json=payload, headers=auth_header(ADMIN_TOKEN)
    )

    assert second.json()["id"] == first.json()["id"]


async def test_an_administrator_revokes_the_reviewer_capability(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer",
        json={"domain": DOMAIN, "equipment": ASSET},
        headers=auth_header(ADMIN_TOKEN),
    )

    response = await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer/revoke",
        json={"domain": DOMAIN, "equipment": ASSET},
        headers=auth_header(ADMIN_TOKEN),
    )

    assert response.status_code == 200
    assert response.json()["revoked_at"] is not None


async def test_revoking_a_capability_that_was_never_granted_is_not_found(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    response = await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer/revoke",
        json={"domain": DOMAIN, "equipment": ASSET},
        headers=auth_header(ADMIN_TOKEN),
    )

    assert response.status_code == 404


async def test_grants_and_revocations_are_audited(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer",
        json={"domain": DOMAIN, "equipment": ASSET},
        headers=auth_header(ADMIN_TOKEN),
    )
    await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer/revoke",
        json={"domain": DOMAIN, "equipment": ASSET},
        headers=auth_header(ADMIN_TOKEN),
    )

    audit = (await api.get(f"{ADMIN}/audit", headers=auth_header(ADMIN_TOKEN))).json()

    operations = [entry["operation"] for entry in audit]
    assert "reviewer_granted" in operations
    assert "reviewer_revoked" in operations
    granted = next(entry for entry in audit if entry["operation"] == "reviewer_granted")
    assert granted["actor_external_user_id"] == ADMIN_ID
    assert granted["scope_equipment"] == ASSET


async def test_the_account_detail_lists_reviewer_capabilities(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer",
        json={"domain": DOMAIN, "equipment": ASSET},
        headers=auth_header(ADMIN_TOKEN),
    )

    detail = (
        await api.get(f"{ADMIN}/users/{REVIEWER_ID}", headers=auth_header(ADMIN_TOKEN))
    ).json()

    assert detail["reviewer_grants"][0]["equipment"] == ASSET


async def test_a_reviewer_capability_over_an_unknown_domain_is_refused(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    response = await api.post(
        f"{ADMIN}/users/{REVIEWER_ID}/reviewer",
        json={"domain": "dominio-inexistente"},
        headers=auth_header(ADMIN_TOKEN),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_domain"


# ---------------------------------------------------------------------
# Activos técnicos
# ---------------------------------------------------------------------


async def test_an_administrator_creates_a_technical_asset(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    response = await api.post(
        f"{ADMIN}/assets",
        json={"code": "TAMPELLA", "name": "Tampella", "domain": DOMAIN},
        headers=auth_header(ADMIN_TOKEN),
    )

    assert response.status_code == 201
    assert response.json()["code"] == "tampella"


async def test_the_model_accepts_more_than_one_asset(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    """El modelo es genérico: Tampella es el primer caso, no una excepción."""
    for code in ("tampella", "otra-maquina"):
        response = await api.post(
            f"{ADMIN}/assets",
            json={"code": code, "name": code.title(), "domain": DOMAIN},
            headers=auth_header(ADMIN_TOKEN),
        )
        assert response.status_code == 201


async def test_a_duplicate_asset_code_is_refused(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    payload = {"code": "tampella", "name": "Tampella", "domain": DOMAIN}
    await api.post(f"{ADMIN}/assets", json=payload, headers=auth_header(ADMIN_TOKEN))

    response = await api.post(f"{ADMIN}/assets", json=payload, headers=auth_header(ADMIN_TOKEN))

    assert response.status_code == 409


async def test_an_asset_in_an_unknown_domain_is_refused(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    response = await api.post(
        f"{ADMIN}/assets",
        json={"code": "x1", "name": "X", "domain": "inexistente"},
        headers=auth_header(ADMIN_TOKEN),
    )

    assert response.status_code == 422


async def test_a_non_administrator_cannot_create_an_asset(
    api: httpx.AsyncClient, bootstrapped: None
) -> None:
    response = await api.post(
        f"{ADMIN}/assets",
        json={"code": "x1", "name": "X", "domain": DOMAIN},
        headers=auth_header(ENGINEER_TOKEN),
    )

    assert response.status_code == 403
