"""Autenticación en la frontera HTTP.

Demuestra la semántica de errores exigida:

- falta el token, está mal formado, es inválido o expiró → ``401``;
- la identidad es válida pero el perfil no está habilitado → ``403``;
- el proveedor de identidad falla → ``503``, nunca ``401``.
"""

import httpx
import pytest

from elsa.adapters.fake_auth import ENGINEER_ID, FakeAuthAdapter
from elsa.adapters.fake_materials_identity import FakeMaterialsIdentityAdapter
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.ports.materials_identity import MaterialsProfile
from tests.conftest import ADMIN_TOKEN, ENGINEER_TOKEN, auth_header

pytestmark = pytest.mark.anyio

PROTECTED = "/api/v1/me"


async def test_request_without_token_is_unauthorized(api: httpx.AsyncClient) -> None:
    response = await api.get(PROTECTED)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["error"]["request_id"]


@pytest.mark.parametrize(
    "header",
    [
        "fake-token-engineer",
        "Basic fake-token-engineer",
        "Bearer",
        "Bearer    ",
        "Token fake-token-engineer",
    ],
)
async def test_malformed_authorization_header_is_unauthorized(
    api: httpx.AsyncClient, header: str
) -> None:
    response = await api.get(PROTECTED, headers={"Authorization": header})

    assert response.status_code == 401


async def test_unknown_token_is_unauthorized(api: httpx.AsyncClient) -> None:
    response = await api.get(PROTECTED, headers=auth_header("forged-token"))

    assert response.status_code == 401


async def test_identity_provider_outage_is_service_unavailable(
    api: httpx.AsyncClient, auth_adapter: FakeAuthAdapter
) -> None:
    """Un fallo técnico nunca se transforma en «usuario inválido»."""
    auth_adapter.unavailable = True

    response = await api.get(PROTECTED, headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "identity_provider_unavailable"


async def test_materials_outage_is_service_unavailable(
    api: httpx.AsyncClient, materials_identity: FakeMaterialsIdentityAdapter
) -> None:
    materials_identity.unavailable = True

    response = await api.get(PROTECTED, headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "identity_provider_unavailable"


async def test_disabled_materials_profile_is_rejected(
    api: httpx.AsyncClient,
    materials_identity: FakeMaterialsIdentityAdapter,
    permissions: InMemoryPermissionsRepository,
) -> None:
    """Aunque tenga permisos en ELSA, un perfil inactivo en Materiales no entra."""
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment=None, actor=ENGINEER_ID
    )
    materials_identity.set_profile(
        MaterialsProfile(user_id=ENGINEER_ID, display_name="Ingeniero", is_active=False)
    )

    response = await api.get(PROTECTED, headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"


async def test_user_without_materials_profile_is_rejected(
    api: httpx.AsyncClient, materials_identity: FakeMaterialsIdentityAdapter
) -> None:
    materials_identity._profiles.clear()  # noqa: SLF001 - fake de test

    response = await api.get(PROTECTED, headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_disabled"


async def test_valid_identity_without_elsa_account_is_forbidden(
    api: httpx.AsyncClient,
) -> None:
    """DEFAULT DENY: identidad correcta, pero ELSA no la conoce."""
    response = await api.get(PROTECTED, headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "elsa_access_denied"


async def test_me_returns_only_safe_information(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    await permissions.grant_permission(
        subject=ENGINEER_ID,
        domain="mantenimiento",
        equipment="tampella",
        actor=ENGINEER_ID,
        display_name="Ingeniero de prueba",
    )

    response = await api.get(PROTECTED, headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "external_user_id": ENGINEER_ID,
        "display_name": "Ingeniero de prueba",
        "is_active": True,
        "is_admin": False,
        "scopes": [{"domain": "mantenimiento", "equipment": "tampella"}],
    }
    # Ni el token ni ningún secreto viajan de vuelta.
    assert ENGINEER_TOKEN not in response.text
    assert ADMIN_TOKEN not in response.text
    assert "token" not in response.text.lower()


async def test_disabled_elsa_account_is_forbidden(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment=None, actor=ENGINEER_ID
    )
    await permissions.set_account_active(subject=ENGINEER_ID, is_active=False, actor=ENGINEER_ID)

    response = await api.get(PROTECTED, headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "elsa_access_denied"
