"""Fake de la fachada contractual Materiales–ELSA (determinista, para tests).

**Esto no es un adaptador.** No habla con Materiales, no elige transporte y
no implementa ninguna regla de negocio: es la **especificación ejecutable**
del contrato que ELSA espera, para que la suite completa pueda comprobar la
forma sin red, sin datos reales y sin proveedor (ADR 0021 §18, regla 24 de
``CLAUDE.md``).

Qué **no** hace, y es deliberado:

- **No agrega.** Los totales y las ubicaciones llegan como fixtures ya
  formados. Reproducir aquí la agregación de Materiales duplicaría una
  lógica que es suya (regla 4) y, peor, convertiría este archivo en una
  segunda implementación con la que comparar la primera.
- **No calcula vigencia ni cobertura.** La metadata se entrega tal como se
  declaró en el escenario. `requires_fresh_inventory` y los avisos de
  vigencia son M4 operativo, que sigue abierto y no se adelanta aquí.
- **No busca.** No hay ranking, ni similitud, ni normalización: el lookup
  exacto compara con lo que el escenario declara, y nada más.

Los registros son sintéticos y genéricos a propósito: no representan datos
reales de Tampella ni la estructura de IH06 / IW13 (regla 12).
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from elsa.core.capability_outcomes import CapabilityCallStatus, CapabilityOutcome
from elsa.core.coverage_policy import InventoryCoverageState
from elsa.ports.materials import (
    ContractDescriptor,
    ContractOperation,
    DerivedValue,
    InventoryCoverage,
    InventoryStatusResult,
    InventoryVersion,
    MatchOrigin,
    MaterialAbsence,
    MaterialAttribution,
    MaterialFacts,
    MaterialLookupRequest,
    MaterialsLookupResult,
    StockLocation,
)

__all__ = [
    "DEFAULT_CONTRACT_VERSION",
    "DEFAULT_INVENTORY",
    "DEFAULT_MATERIALS",
    "FakeMaterialsFacade",
    "FakeMaterialRecord",
    "scenario",
]

DEFAULT_CONTRACT_VERSION = "1"
"""Versión que este fake dice hablar. Es una **cadena**, no un entero: permite
cambios compatibles sin renumerar (ADR 0021 §15)."""

_FIXED_NOW = datetime(2026, 1, 15, 10, 30, tzinfo=UTC)
"""Reloj congelado. Sin esto el fake no sería determinista y ``read_at``
cambiaría en cada ejecución, que es exactamente lo que una prueba de
contrato no puede permitirse."""

DEFAULT_INVENTORY = InventoryVersion(
    version_number=17,
    loaded_at=datetime(2026, 1, 10, 3, 0, tzinfo=UTC),
    row_count=54_494,
    source_file_label="fake-export-0001",
    # `extracted_at` se queda en su único valor posible en V1. No se pasa
    # explícitamente para que quede claro que no es una elección de este
    # fake, sino del contrato (ADR 0027 §7).
)
"""Vigencia por defecto. Las cifras son sintéticas y no describen ninguna
carga real."""

DEFAULT_COVERAGE = InventoryCoverage(state=InventoryCoverageState.UNKNOWN)
"""**`UNKNOWN` es el estado disponible hoy**, y no es un error (ADR 0023 §6).

Que el fake lo use por defecto no es pereza: es que ningún proveedor puede
respaldar hoy `observed_scope` con metadata de ingestión, y un fake que
devolviera `KNOWN_COMPLETE` por comodidad enseñaría a ELSA a esperar una
garantía que nadie da.
"""


class FakeMaterialRecord:
    """Un material del catálogo del fake, con los códigos que lo identifican.

    Guarda por separado el código actual y el antiguo porque el contrato
    distingue con qué coincidió la consulta: son dos hechos distintos, no
    dos formas del mismo (ADR 0025 §9).
    """

    __slots__ = ("facts", "old_code")

    def __init__(self, facts: MaterialFacts, *, old_code: str | None = None) -> None:
        self.facts = facts
        self.old_code = old_code


def _rule(value: object, reference: str, *, verifiable: bool = False) -> DerivedValue:
    """Envuelve un valor derivado con la regla que lo produjo (ADR 0021 §10.2).

    `verifiable` es falso por defecto a propósito: hoy ninguna de las
    funciones que aplican estas reglas está versionada en el repositorio de
    Materiales, de modo que ninguna prueba contractual del proveedor puede
    demostrarlas todavía. Declararlo así es decir la verdad sobre la fuente.
    """
    return DerivedValue(value=value, rule_reference=reference, rule_verifiable=verifiable)


DEFAULT_MATERIALS: tuple[FakeMaterialRecord, ...] = (
    FakeMaterialRecord(
        MaterialFacts(
            code="10000001",
            descripcion="Fake bearing for contract tests",
            unidad="UND",
            material_antiguo="OLD-0001",
            stock_locations=(
                StockLocation(
                    centro="C1",
                    almacen="A1",
                    ubicacion="EST-01",
                    ambito="molino",
                    disponible=Decimal("4"),
                    comprometido=Decimal("0"),
                ),
                StockLocation(
                    centro="C2",
                    almacen="A2",
                    ubicacion=None,  # DATO_DESCONOCIDO: la fila llegó sin ubicación
                    ambito="remoto",
                    disponible=Decimal("2"),
                    comprometido=Decimal("1"),
                ),
            ),
            total_disponible=_rule(Decimal("6"), "RN-030"),
            total_comprometido=_rule(Decimal("1"), "RN-030"),
            dado_de_baja=_rule(False, "RN-034"),
        ),
        old_code="OLD-0001",
    ),
    FakeMaterialRecord(
        MaterialFacts(
            code="10000002",
            # `descripcion` y `unidad` en nulo: VALOR_FACTUAL_AUSENTE, la
            # columna llegó vacía en todas las filas del grupo.
            descripcion=None,
            unidad=None,
            # `material_antiguo` en nulo: DATO_DESCONOCIDO. No hay código
            # antiguo, **o** el de origen estaba corrompido y se descartó, y
            # ambos casos son indistinguibles por diseño (ADR 0025 §10).
            material_antiguo=None,
            stock_locations=(
                StockLocation(
                    centro="C1",
                    almacen="A1",
                    ubicacion="EST-02",
                    ambito="molino",
                    disponible=Decimal("0"),
                    comprometido=Decimal("0"),
                ),
            ),
            total_disponible=_rule(Decimal("0"), "RN-030"),
            total_comprometido=_rule(Decimal("0"), "RN-030"),
            # Marcado para baja **con existencias en otra ubicación**: el
            # caso que prueba que la señal no oculta ni desprioriza nada.
            dado_de_baja=_rule(True, "RN-034"),
        ),
    ),
)


class FakeMaterialsFacade:
    """Responde como debería responder la fachada, sobre un catálogo fijo.

    El escenario se elige al construirlo, no por configuración global: cada
    prueba declara qué situación quiere y el fake la reproduce igual siempre.
    """

    def __init__(
        self,
        materials: Iterable[FakeMaterialRecord] | None = None,
        *,
        call_status: CapabilityCallStatus = CapabilityCallStatus.OK,
        contract_version: str = DEFAULT_CONTRACT_VERSION,
        inventory: InventoryVersion | None = None,
        coverage: InventoryCoverage | None = None,
        now: datetime = _FIXED_NOW,
    ) -> None:
        self._materials = tuple(DEFAULT_MATERIALS if materials is None else materials)
        self._call_status = call_status
        self._contract_version = contract_version
        self._inventory = DEFAULT_INVENTORY if inventory is None else inventory
        self._coverage = DEFAULT_COVERAGE if coverage is None else coverage
        self._now = now

    # -- operaciones del contrato -------------------------------------

    async def lookup_material_by_code(
        self, request: MaterialLookupRequest
    ) -> MaterialsLookupResult:
        """Coincidencia exacta por código actual o antiguo, o nada.

        **No hay degradación a similitud, y no puede haberla:** no se mira la
        descripción en ningún momento. El código que no coincide literalmente
        con un código del catálogo produce `NOT_RETURNED`, que es un hecho
        sobre lo que esta fuente devolvió, no sobre lo que existe.
        """
        if self._call_status is not CapabilityCallStatus.OK:
            return MaterialsLookupResult(call_status=self._call_status)

        found = self._find(request.material_code)
        if found is None:
            return MaterialsLookupResult(
                call_status=CapabilityCallStatus.OK,
                contract_version=self._contract_version,
                inventory=self._inventory,
                coverage=self._coverage,
                requested_code=request.material_code,
                outcome=CapabilityOutcome.NOT_RETURNED,
                absence=MaterialAbsence(),
            )

        record, match_origin = found
        return MaterialsLookupResult(
            call_status=CapabilityCallStatus.OK,
            contract_version=self._contract_version,
            inventory=self._inventory,
            coverage=self._coverage,
            requested_code=request.material_code,
            outcome=CapabilityOutcome.MATCHED,
            material=record.facts,
            attribution=MaterialAttribution(
                source_version=self._inventory,
                contract_version=self._contract_version,
                read_at=self._now,
                match_origin=match_origin,
            ),
        )

    async def get_inventory_status(self) -> InventoryStatusResult:
        if self._call_status is not CapabilityCallStatus.OK:
            return InventoryStatusResult(call_status=self._call_status)
        return InventoryStatusResult(
            call_status=CapabilityCallStatus.OK,
            contract_version=self._contract_version,
            inventory=self._inventory,
            coverage=self._coverage,
        )

    async def get_contract_descriptor(self) -> ContractDescriptor:
        """Declara versión y operaciones.

        El enlace de transporte es un rótulo inerte: **no se ha elegido
        ninguno**, y el fake no habla por una decisión que nadie ha tomado.
        """
        return ContractDescriptor(
            contract_version=self._contract_version,
            operations=(
                ContractOperation("lookup_material_by_code", transport_binding="fake"),
                ContractOperation("get_inventory_status", transport_binding="fake"),
                ContractOperation("get_contract_descriptor", transport_binding="fake"),
            ),
            unsupported_fields=("inventory.extracted_at",),
        )

    # -- interno -------------------------------------------------------

    def _find(self, code: str) -> tuple[FakeMaterialRecord, MatchOrigin] | None:
        """Coincidencia literal. Primero por código actual, después por antiguo.

        El orden importa y es el del contrato: un código que es el código
        actual de un material identifica ese material, aunque además sea el
        código antiguo de otro.
        """
        for record in self._materials:
            if record.facts.code == code:
                return record, MatchOrigin.EXACT_MATERIAL_CODE
        for record in self._materials:
            if record.old_code is not None and record.old_code == code:
                return record, MatchOrigin.OLD_MATERIAL_CODE
        return None


def scenario(status: CapabilityCallStatus) -> FakeMaterialsFacade:
    """Fachada que responde siempre con un estado de llamada dado.

    Atajo para las pruebas de los desenlaces que no son un hecho:
    `NO_ACTIVE_INVENTORY` y `UNAVAILABLE` son **resultados normales**, y
    escribirlos debe ser tan barato como escribir el caso feliz.
    """
    return FakeMaterialsFacade(call_status=status)
