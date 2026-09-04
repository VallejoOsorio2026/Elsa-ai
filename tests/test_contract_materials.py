"""Contrato del puerto de Materiales, verificado con el adaptador fake."""

import pytest

from elsa.adapters.fake_materials import FakeMaterialsAdapter
from elsa.ports.materials import Material, MaterialsPort

pytestmark = pytest.mark.anyio


@pytest.fixture
def port() -> MaterialsPort:
    return FakeMaterialsAdapter()


def test_fake_adapter_satisfies_the_port(port: MaterialsPort) -> None:
    assert isinstance(port, MaterialsPort)


async def test_known_code_returns_material(port: MaterialsPort) -> None:
    material = await port.get_material("FAKE-0001")

    assert isinstance(material, Material)
    assert material.code == "FAKE-0001"


async def test_unknown_code_returns_none(port: MaterialsPort) -> None:
    assert await port.get_material("MISSING-9999") is None


async def test_search_matches_description_and_respects_limit(port: MaterialsPort) -> None:
    matches = await port.search_materials("fake", limit=2)

    assert len(matches) == 2
    assert all(isinstance(material, Material) for material in matches)


async def test_search_is_deterministic(port: MaterialsPort) -> None:
    first = await port.search_materials("seal")
    second = await port.search_materials("seal")

    assert first == second
    assert [material.code for material in first] == ["FAKE-0002"]
