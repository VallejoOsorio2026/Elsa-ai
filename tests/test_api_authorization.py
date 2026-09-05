"""Autorización de ELSA en la frontera HTTP.

Demuestra los criterios de éxito del bloque sobre las sondas de alcance:
permiso de dominio, permiso de equipo, alcance ajeno, administrador y
default deny.
"""

import httpx
import pytest

from elsa.adapters.fake_auth import ADMIN_ID, ENGINEER_ID
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from tests.conftest import ADMIN_TOKEN, ENGINEER_TOKEN, auth_header

pytestmark = pytest.mark.anyio

DOMAIN = "/api/v1/access/mantenimiento"
EQUIPMENT = "/api/v1/access/mantenimiento/tampella"
OTHER_EQUIPMENT = "/api/v1/access/mantenimiento/otro-equipo"
OTHER_DOMAIN = "/api/v1/access/materiales"


async def test_default_deny_without_any_grant(api: httpx.AsyncClient) -> None:
    response = await api.get(DOMAIN, headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "elsa_access_denied"


async def test_domain_grant_allows_the_domain_and_its_equipment(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment=None, actor=ADMIN_ID
    )

    domain_response = await api.get(DOMAIN, headers=auth_header(ENGINEER_TOKEN))
    equipment_response = await api.get(EQUIPMENT, headers=auth_header(ENGINEER_TOKEN))

    assert domain_response.status_code == 200
    assert domain_response.json()["granted"] is True
    assert domain_response.json()["via_admin"] is False
    assert equipment_response.status_code == 200


async def test_equipment_grant_allows_only_that_equipment(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    """Autorizado solo para un alcance: solo puede usar ese alcance."""
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment="tampella", actor=ADMIN_ID
    )

    allowed = await api.get(EQUIPMENT, headers=auth_header(ENGINEER_TOKEN))
    other_equipment = await api.get(OTHER_EQUIPMENT, headers=auth_header(ENGINEER_TOKEN))
    whole_domain = await api.get(DOMAIN, headers=auth_header(ENGINEER_TOKEN))
    other_domain = await api.get(OTHER_DOMAIN, headers=auth_header(ENGINEER_TOKEN))

    assert allowed.status_code == 200
    assert allowed.json()["equipment"] == "tampella"
    assert other_equipment.status_code == 403
    assert whole_domain.status_code == 403
    assert other_domain.status_code == 403
    assert other_equipment.json()["error"]["code"] == "insufficient_permissions"


async def test_scope_matching_is_case_insensitive(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    """`Tampella` es dato, no una constante: se compara normalizado."""
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment="tampella", actor=ADMIN_ID
    )

    response = await api.get(
        "/api/v1/access/Mantenimiento/TAMPELLA", headers=auth_header(ENGINEER_TOKEN)
    )

    assert response.status_code == 200


async def test_revoking_a_grant_blocks_further_access(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    """Perder un permiso impide nuevas recuperaciones de ese conocimiento."""
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment="tampella", actor=ADMIN_ID
    )
    assert (await api.get(EQUIPMENT, headers=auth_header(ENGINEER_TOKEN))).status_code == 200

    await permissions.revoke_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment="tampella", actor=ADMIN_ID
    )

    assert (await api.get(EQUIPMENT, headers=auth_header(ENGINEER_TOKEN))).status_code == 403


async def test_administrator_has_full_access(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    await permissions.bootstrap_admin(subject=ADMIN_ID)

    domain_response = await api.get(DOMAIN, headers=auth_header(ADMIN_TOKEN))
    equipment_response = await api.get(OTHER_EQUIPMENT, headers=auth_header(ADMIN_TOKEN))
    other_domain = await api.get(OTHER_DOMAIN, headers=auth_header(ADMIN_TOKEN))

    assert domain_response.status_code == 200
    assert domain_response.json()["via_admin"] is True
    assert equipment_response.status_code == 200
    assert other_domain.status_code == 200


async def test_disabled_administrator_loses_access(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    await permissions.bootstrap_admin(subject=ADMIN_ID)
    await permissions.set_account_active(subject=ADMIN_ID, is_active=False, actor=ADMIN_ID)

    response = await api.get(DOMAIN, headers=auth_header(ADMIN_TOKEN))

    assert response.status_code == 403


async def test_malformed_scope_values_are_denied_not_leaked(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment=None, actor=ADMIN_ID
    )

    response = await api.get(
        "/api/v1/access/mantenimiento/../secreto", headers=auth_header(ENGINEER_TOKEN)
    )

    assert response.status_code in (403, 404)


async def test_unauthenticated_scope_probe_is_unauthorized(api: httpx.AsyncClient) -> None:
    assert (await api.get(EQUIPMENT)).status_code == 401
