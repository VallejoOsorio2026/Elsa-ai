"""API administrativa: bootstrap, grant/revoke, estado, administración y auditoría."""

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from elsa.adapters.fake_auth import ADMIN_ID, ENGINEER_ID
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.api.v1.admin import BOOTSTRAP_TOKEN_HEADER
from elsa.config import Settings
from elsa.container import Container
from elsa.main import create_app
from tests.conftest import ADMIN_TOKEN, ENGINEER_TOKEN, auth_header, make_test_settings

pytestmark = pytest.mark.anyio

BOOTSTRAP_SECRET = "bootstrap-secret-only-in-the-environment"
GRANTS = f"/api/v1/admin/users/{ENGINEER_ID}/grants"


@pytest.fixture
def settings() -> Settings:
    return make_test_settings(bootstrap_admin_token=SecretStr(BOOTSTRAP_SECRET))


@pytest.fixture
def bootstrap_header() -> dict[str, str]:
    return {BOOTSTRAP_TOKEN_HEADER: BOOTSTRAP_SECRET}


@pytest.fixture
async def admin(api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository) -> str:
    """Deja declarado el primer administrador y devuelve su UUID."""
    await permissions.bootstrap_admin(subject=ADMIN_ID, display_name="Administradora")
    return ADMIN_ID


# ---------------------------------------------------------------------
# Bootstrap del primer administrador
# ---------------------------------------------------------------------


async def test_bootstrap_promotes_the_authenticated_user(
    api: httpx.AsyncClient, bootstrap_header: dict[str, str]
) -> None:
    """El UUID administrado es el del usuario autenticado, no uno escrito a mano."""
    response = await api.post(
        "/api/v1/admin/bootstrap",
        headers={**auth_header(ADMIN_TOKEN), **bootstrap_header},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["account"]["external_user_id"] == ADMIN_ID
    assert body["account"]["is_admin"] is True


async def test_bootstrap_is_idempotent(
    api: httpx.AsyncClient, bootstrap_header: dict[str, str]
) -> None:
    headers = {**auth_header(ADMIN_TOKEN), **bootstrap_header}
    await api.post("/api/v1/admin/bootstrap", headers=headers)

    response = await api.post("/api/v1/admin/bootstrap", headers=headers)

    assert response.status_code == 200
    assert response.json()["created"] is False


async def test_bootstrap_requires_the_configured_token(api: httpx.AsyncClient) -> None:
    response = await api.post(
        "/api/v1/admin/bootstrap",
        headers={**auth_header(ADMIN_TOKEN), BOOTSTRAP_TOKEN_HEADER: "wrong"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "bootstrap_not_allowed"


async def test_bootstrap_is_disabled_without_configuration(
    container: Container, bootstrap_header: dict[str, str]
) -> None:
    disabled = make_test_settings()
    app: FastAPI = create_app(disabled, container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/admin/bootstrap",
            headers={**auth_header(ADMIN_TOKEN), **bootstrap_header},
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "bootstrap_not_allowed"


async def test_bootstrap_requires_authentication(
    api: httpx.AsyncClient, bootstrap_header: dict[str, str]
) -> None:
    response = await api.post("/api/v1/admin/bootstrap", headers=bootstrap_header)

    assert response.status_code == 401


async def test_bootstrap_refuses_a_second_administrator(
    api: httpx.AsyncClient,
    bootstrap_header: dict[str, str],
    permissions: InMemoryPermissionsRepository,
) -> None:
    await permissions.bootstrap_admin(subject=ENGINEER_ID)

    response = await api.post(
        "/api/v1/admin/bootstrap",
        headers={**auth_header(ADMIN_TOKEN), **bootstrap_header},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "bootstrap_already_completed"


# ---------------------------------------------------------------------
# Otorgar y revocar
# ---------------------------------------------------------------------


async def test_only_administrators_can_grant(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment=None, actor=ADMIN_ID
    )

    response = await api.post(
        GRANTS,
        headers=auth_header(ENGINEER_TOKEN),
        json={"domain": "materiales"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_permissions"


async def test_grant_then_access_then_revoke_then_denied(
    api: httpx.AsyncClient, admin: str
) -> None:
    granted = await api.post(
        GRANTS,
        headers=auth_header(ADMIN_TOKEN),
        json={"domain": "mantenimiento", "equipment": "tampella"},
    )
    assert granted.status_code == 200
    assert granted.json()["equipment"] == "tampella"

    allowed = await api.get(
        "/api/v1/access/mantenimiento/tampella", headers=auth_header(ENGINEER_TOKEN)
    )
    assert allowed.status_code == 200

    revoked = await api.post(
        f"{GRANTS}/revoke",
        headers=auth_header(ADMIN_TOKEN),
        json={"domain": "mantenimiento", "equipment": "tampella"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["revoked_by"] == admin

    denied = await api.get(
        "/api/v1/access/mantenimiento/tampella", headers=auth_header(ENGINEER_TOKEN)
    )
    assert denied.status_code == 403


async def test_revoking_a_missing_grant_is_not_found(api: httpx.AsyncClient, admin: str) -> None:
    response = await api.post(
        f"{GRANTS}/revoke",
        headers=auth_header(ADMIN_TOKEN),
        json={"domain": "mantenimiento"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "grant_not_found"


async def test_unknown_domain_is_rejected(api: httpx.AsyncClient, admin: str) -> None:
    response = await api.post(
        GRANTS, headers=auth_header(ADMIN_TOKEN), json={"domain": "inexistente"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_domain"


async def test_malformed_scope_value_is_a_validation_error(
    api: httpx.AsyncClient, admin: str
) -> None:
    response = await api.post(
        GRANTS, headers=auth_header(ADMIN_TOKEN), json={"domain": "mante nimiento!"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------
# Estado y administración
# ---------------------------------------------------------------------


async def test_disabling_a_user_blocks_access(api: httpx.AsyncClient, admin: str) -> None:
    await api.post(GRANTS, headers=auth_header(ADMIN_TOKEN), json={"domain": "mantenimiento"})
    assert (
        await api.get("/api/v1/access/mantenimiento", headers=auth_header(ENGINEER_TOKEN))
    ).status_code == 200

    disabled = await api.post(
        f"/api/v1/admin/users/{ENGINEER_ID}/status",
        headers=auth_header(ADMIN_TOKEN),
        json={"is_active": False},
    )

    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False
    assert (
        await api.get("/api/v1/access/mantenimiento", headers=auth_header(ENGINEER_TOKEN))
    ).status_code == 403


async def test_administration_can_be_transferred(api: httpx.AsyncClient, admin: str) -> None:
    await api.post(GRANTS, headers=auth_header(ADMIN_TOKEN), json={"domain": "mantenimiento"})

    promoted = await api.post(
        f"/api/v1/admin/users/{ENGINEER_ID}/admin",
        headers=auth_header(ADMIN_TOKEN),
        json={"is_admin": True},
    )
    assert promoted.status_code == 200
    assert promoted.json()["is_admin"] is True

    # Ahora hay dos administradores y el primero puede retirarse.
    stepped_down = await api.post(
        f"/api/v1/admin/users/{ADMIN_ID}/admin",
        headers=auth_header(ADMIN_TOKEN),
        json={"is_admin": False},
    )
    assert stepped_down.status_code == 200
    assert stepped_down.json()["is_admin"] is False

    # Y el nuevo administrador conserva el acceso total.
    assert (
        await api.get("/api/v1/access/materiales", headers=auth_header(ENGINEER_TOKEN))
    ).status_code == 200


async def test_the_last_administrator_cannot_step_down(api: httpx.AsyncClient, admin: str) -> None:
    response = await api.post(
        f"/api/v1/admin/users/{ADMIN_ID}/admin",
        headers=auth_header(ADMIN_TOKEN),
        json={"is_admin": False},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_administrator"


async def test_unknown_account_is_not_found(api: httpx.AsyncClient, admin: str) -> None:
    missing = "dddddddd-0000-4000-8000-00000000000d"

    response = await api.get(f"/api/v1/admin/users/{missing}", headers=auth_header(ADMIN_TOKEN))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "account_not_found"


# ---------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------


async def test_grant_and_revoke_are_audited(api: httpx.AsyncClient, admin: str) -> None:
    await api.post(
        GRANTS,
        headers=auth_header(ADMIN_TOKEN),
        json={"domain": "mantenimiento", "equipment": "tampella"},
    )
    await api.post(
        f"{GRANTS}/revoke",
        headers=auth_header(ADMIN_TOKEN),
        json={"domain": "mantenimiento", "equipment": "tampella"},
    )

    response = await api.get(
        "/api/v1/admin/audit",
        headers=auth_header(ADMIN_TOKEN),
        params={"subject": ENGINEER_ID},
    )

    assert response.status_code == 200
    entries = response.json()
    operations = [entry["operation"] for entry in entries]
    assert operations[:2] == ["revoke_permission", "grant_permission"]

    granted = entries[1]
    assert granted["actor_external_user_id"] == admin
    assert granted["subject_external_user_id"] == ENGINEER_ID
    assert granted["scope_domain"] == "mantenimiento"
    assert granted["scope_equipment"] == "tampella"
    # El request-id enlaza la auditoría con los logs del servidor.
    assert granted["request_id"]


async def test_audit_requires_administration(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment=None, actor=ADMIN_ID
    )

    response = await api.get("/api/v1/admin/audit", headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 403
