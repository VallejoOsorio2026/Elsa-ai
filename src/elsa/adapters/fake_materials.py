"""Adaptador fake del puerto de Materiales (determinista, para tests).

Los registros son sintéticos y genéricos a propósito: no representan datos
reales de Tampella ni la estructura de IH06 / IW13.
"""

from collections.abc import Iterable

from elsa.ports.materials import Material

_DEFAULT_MATERIALS: tuple[Material, ...] = (
    Material(code="FAKE-0001", description="Fake bearing for contract tests"),
    Material(code="FAKE-0002", description="Fake seal for contract tests"),
    Material(code="FAKE-0003", description="Fake bolt for contract tests"),
)


class FakeMaterialsAdapter:
    """Consulta un catálogo fijo en memoria, sin tocar el sistema real."""

    def __init__(self, materials: Iterable[Material] | None = None) -> None:
        self._materials = tuple(_DEFAULT_MATERIALS if materials is None else materials)

    async def get_material(self, code: str) -> Material | None:
        return next((material for material in self._materials if material.code == code), None)

    async def search_materials(self, query: str, *, limit: int = 10) -> list[Material]:
        needle = query.lower()
        matches = [
            material
            for material in self._materials
            if needle in material.code.lower() or needle in material.description.lower()
        ]
        return matches[:limit]
