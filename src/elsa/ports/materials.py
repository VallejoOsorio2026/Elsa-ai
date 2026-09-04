"""Puerto de integración con el Asistente de Materiales.

Materiales sigue siendo propietario de su inventario (~65.000 registros);
ELSA consulta a través de este puerto y no duplica datos (regla 6 de
CLAUDE.md).

La estructura de ``Material`` es deliberadamente mínima: el contrato real
con Materiales se definirá en el bloque de integración, sin asumir la
estructura de IH06 / IW13.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class Material:
    """Referencia mínima a un material del inventario de Materiales."""

    code: str
    description: str


class MaterialsUnavailableError(Exception):
    """El servicio de Materiales no está disponible."""


@runtime_checkable
class MaterialsPort(Protocol):
    """Consulta de materiales del inventario, sin duplicarlo en ELSA."""

    async def get_material(self, code: str) -> Material | None:
        """Devuelve el material con ese código, o ``None`` si no existe."""
        ...

    async def search_materials(self, query: str, *, limit: int = 10) -> list[Material]:
        """Busca materiales por texto libre; a lo sumo ``limit`` resultados."""
        ...
