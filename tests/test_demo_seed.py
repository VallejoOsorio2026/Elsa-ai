"""La siembra sintética se ejecuta donde debe y en ningún otro sitio."""

import pytest

from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.config import Environment, Settings
from elsa.demo.seed import ASSET_CODE, DOMAIN, ENGINEER, REVIEWER, seed_demo_data, should_seed
from tests.conftest import make_test_settings

pytestmark = pytest.mark.anyio


def _settings() -> Settings:
    return make_test_settings(demo_seed=True)


async def test_seed_is_off_by_default() -> None:
    assert should_seed(make_test_settings()) is False


async def test_seed_refuses_outside_dev() -> None:
    """La configuración impide siquiera declararla fuera de DEV."""
    with pytest.raises(Exception, match="only allowed in the DEV environment"):
        make_test_settings(env=Environment.TEST, demo_seed=True)


async def test_seed_publishes_a_synthetic_bom(
    permissions: InMemoryPermissionsRepository,
    knowledge: InMemoryKnowledgeRepository,
) -> None:
    seeded = await seed_demo_data(
        permissions=permissions, knowledge=knowledge, settings=_settings()
    )
    assert seeded is True

    asset = await knowledge.get_asset(ASSET_CODE)
    assert asset is not None and asset.domain == DOMAIN

    published = await knowledge.get_published_version(asset.id)
    assert published is not None
    items = await knowledge.list_version_items(published.id)
    assert len(items) == 8
    # Todos los códigos son sintéticos y se reconocen como tales.
    assert all(item.sap_code is not None and item.sap_code.startswith("SYN-") for item in items)


async def test_seed_grants_are_scoped_to_the_pilot_asset(
    permissions: InMemoryPermissionsRepository,
    knowledge: InMemoryKnowledgeRepository,
) -> None:
    await seed_demo_data(permissions=permissions, knowledge=knowledge, settings=_settings())

    grants = await permissions.list_active_grants(ENGINEER)
    assert [(grant.domain, grant.equipment) for grant in grants] == [(DOMAIN, ASSET_CODE)]

    # El ingeniero lee pero no revisa; la revisora sí.
    assert await permissions.list_active_reviewer_grants(ENGINEER) == ()
    assert len(await permissions.list_active_reviewer_grants(REVIEWER)) == 1


async def test_seed_is_idempotent(
    permissions: InMemoryPermissionsRepository,
    knowledge: InMemoryKnowledgeRepository,
) -> None:
    """Dos arranques no publican dos veces el mismo BOM."""
    await seed_demo_data(permissions=permissions, knowledge=knowledge, settings=_settings())
    await seed_demo_data(permissions=permissions, knowledge=knowledge, settings=_settings())

    asset = await knowledge.get_asset(ASSET_CODE)
    assert asset is not None
    assert len(await knowledge.list_versions(asset.id)) == 1


async def test_seed_never_writes_to_a_non_memory_store(
    knowledge: InMemoryKnowledgeRepository,
) -> None:
    """Datos de demostración en una base real serían indistinguibles de datos reales."""

    class _NotMemory:
        pass

    seeded = await seed_demo_data(
        permissions=_NotMemory(), knowledge=knowledge, settings=_settings()
    )
    assert seeded is False
