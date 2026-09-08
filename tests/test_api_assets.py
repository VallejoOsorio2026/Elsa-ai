"""La lista de equipos sale de los permisos, no de una suposición."""

from collections.abc import AsyncIterator

import httpx
import pytest

from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.demo.seed import ASSET_CODE, DOMAIN, ENGINEER, seed_demo_data
from tests.conftest import ADMIN_TOKEN, ENGINEER_TOKEN, auth_header, make_test_settings

pytestmark = pytest.mark.anyio

ASSETS = "/api/v1/assets"


@pytest.fixture
async def seeded(
    api: httpx.AsyncClient,
    permissions: InMemoryPermissionsRepository,
    knowledge: InMemoryKnowledgeRepository,
) -> AsyncIterator[httpx.AsyncClient]:
    await seed_demo_data(
        permissions=permissions,
        knowledge=knowledge,
        settings=make_test_settings(demo_seed=True),
    )
    yield api


async def test_listing_requires_authentication(seeded: httpx.AsyncClient) -> None:
    assert (await seeded.get(ASSETS)).status_code == 401


async def test_only_the_authorised_assets_are_listed(
    seeded: httpx.AsyncClient,
    knowledge: InMemoryKnowledgeRepository,
) -> None:
    """Un equipo sin alcance no aparece: ni su nombre ni su existencia."""
    await knowledge.create_asset(
        code="caldera",
        name="Caldera de recuperación",
        domain=DOMAIN,
        description="Otro equipo del mismo dominio.",
    )
    body = (await seeded.get(ASSETS, headers=auth_header(ENGINEER_TOKEN))).json()
    assert [asset["code"] for asset in body] == [ASSET_CODE]


async def test_a_domain_wide_grant_covers_every_asset_of_that_domain(
    seeded: httpx.AsyncClient,
    knowledge: InMemoryKnowledgeRepository,
) -> None:
    await knowledge.create_asset(code="caldera", name="Caldera de recuperación", domain=DOMAIN)
    body = (await seeded.get(ASSETS, headers=auth_header(ADMIN_TOKEN))).json()
    assert {asset["code"] for asset in body} == {ASSET_CODE, "caldera"}


async def test_the_list_is_ordered_by_name(
    seeded: httpx.AsyncClient,
    knowledge: InMemoryKnowledgeRepository,
) -> None:
    await knowledge.create_asset(code="caldera", name="Caldera", domain=DOMAIN)
    await knowledge.create_asset(code="zaranda", name="Zaranda", domain=DOMAIN)
    names = [
        asset["name"]
        for asset in (await seeded.get(ASSETS, headers=auth_header(ADMIN_TOKEN))).json()
    ]
    assert names == sorted(names)


async def test_no_scope_means_an_empty_list_not_an_error(
    seeded: httpx.AsyncClient,
    permissions: InMemoryPermissionsRepository,
) -> None:
    """Cuenta activa sin alcance: respuesta legítima, no un fallo."""
    grants = await permissions.list_active_grants(ENGINEER)
    for grant in grants:
        await permissions.revoke_permission(
            subject=ENGINEER, domain=grant.domain, equipment=grant.equipment, actor="test"
        )
    response = await seeded.get(ASSETS, headers=auth_header(ENGINEER_TOKEN))
    assert response.status_code == 200
    assert response.json() == []


async def test_the_response_carries_no_internal_identifiers(
    seeded: httpx.AsyncClient,
) -> None:
    body = (await seeded.get(ASSETS, headers=auth_header(ENGINEER_TOKEN))).json()
    assert set(body[0]) == {"code", "name", "domain"}
