"""Comparación determinística entre el BOM de Ingeniería y un snapshot SAP.

La reconciliación es una **capa separada**. No toca el BOM publicado ni el
snapshot: los lee, los compara y guarda ambos valores uno al lado del otro.
Ninguna fuente se corrige para «hacerlas coincidir», y ninguna discrepancia
se resuelve sola.

Esto es deliberado. Que Ingeniería diga 2 y SAP diga 3 significa que hay una
desviación; no dice cuál de los dos números es correcto. Puede que SAP esté
mal alimentado, puede que el Excel esté desactualizado, puede que alguien
cambiara la máquina. Elegir automáticamente convertiría una pregunta abierta
en un hecho falso, y el hecho falso sobreviviría a la persona que podía
detectarlo.

Clasificaciones:

- ``match``: mismo material, misma cantidad.
- ``quantity_difference``: mismo material, cantidad distinta.
- ``engineering_only``: Ingeniería lo declara y SAP no lo muestra.
- ``sap_only``: SAP lo muestra y el BOM aprobado no lo declara.
- ``duplicate_or_structural_difference``: el material aparece varias veces
  en algún lado; la correspondencia renglón a renglón no es única.
- ``unresolved``: no hay forma automática de relacionarlos, típicamente
  porque el componente no tiene código SAP o porque falta una cantidad. Un
  componente sin código SAP **sigue siendo válido**: simplemente no puede
  compararse contra SAP sin intervención humana.

Solo participan los materiales del snapshot. Los equipos hijos describen la
estructura del activo, no su lista de materiales, y compararlos produciría
discrepancias inventadas.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from elsa.core.normalization import canonical_sap_code

__all__ = [
    "EngineeringEntry",
    "ReconciliationClass",
    "ReconciliationEntry",
    "SapEntry",
    "reconcile",
    "summarize",
]


class ReconciliationClass(StrEnum):
    """Coincide con ``ck_reconciliation_classification`` de la migración."""

    MATCH = "match"
    ENGINEERING_ONLY = "engineering_only"
    SAP_ONLY = "sap_only"
    QUANTITY_DIFFERENCE = "quantity_difference"
    DUPLICATE_OR_STRUCTURAL_DIFFERENCE = "duplicate_or_structural_difference"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class EngineeringEntry:
    """Un renglón del BOM de Ingeniería publicado."""

    item_id: str
    sap_code: str | None = None
    component_id: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class SapEntry:
    """Un renglón del snapshot de SAP."""

    item_id: str
    sap_code: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    description: str | None = None
    entry_kind: str = "material"


@dataclass(frozen=True, slots=True)
class ReconciliationEntry:
    """Un resultado de la comparación, con ambos lados conservados."""

    classification: ReconciliationClass
    bom_item_id: str | None = None
    snapshot_item_id: str | None = None
    component_id: str | None = None
    sap_code: str | None = None
    engineering_quantity: Decimal | None = None
    sap_quantity: Decimal | None = None
    engineering_unit: str | None = None
    sap_unit: str | None = None
    engineering_description: str | None = None
    sap_description: str | None = None
    detail: dict[str, str] = field(default_factory=dict)


def _same_quantity(left: Decimal, right: Decimal) -> bool:
    """Compara cantidades por valor, no por representación."""
    return left == right


def _engineering_entry(
    item: EngineeringEntry,
    classification: ReconciliationClass,
    **detail: str,
) -> ReconciliationEntry:
    return ReconciliationEntry(
        classification=classification,
        bom_item_id=item.item_id,
        component_id=item.component_id,
        sap_code=item.sap_code,
        engineering_quantity=item.quantity,
        engineering_unit=item.unit,
        engineering_description=item.description,
        detail=dict(detail),
    )


def _sap_entry(
    item: SapEntry, classification: ReconciliationClass, **detail: str
) -> ReconciliationEntry:
    return ReconciliationEntry(
        classification=classification,
        snapshot_item_id=item.item_id,
        sap_code=item.sap_code,
        sap_quantity=item.quantity,
        sap_unit=item.unit,
        sap_description=item.description,
        detail=dict(detail),
    )


def reconcile(
    engineering: Sequence[EngineeringEntry], sap: Sequence[SapEntry]
) -> tuple[ReconciliationEntry, ...]:
    """Compara ambos lados y devuelve un resultado por renglón.

    El resultado es determinístico: los mismos datos de entrada producen
    siempre la misma salida, en el mismo orden.
    """
    results: list[ReconciliationEntry] = []

    engineering_by_code: dict[str, list[EngineeringEntry]] = {}
    for item in engineering:
        code = canonical_sap_code(item.sap_code)
        if code is None:
            # Un componente sin código SAP es válido, pero no tiene con qué
            # emparejarse en SAP. No es una discrepancia: es una relación no
            # resoluble automáticamente.
            results.append(
                _engineering_entry(
                    item,
                    ReconciliationClass.UNRESOLVED,
                    reason="engineering_item_without_sap_code",
                )
            )
            continue
        engineering_by_code.setdefault(code, []).append(item)

    sap_by_code: dict[str, list[SapEntry]] = {}
    for sap_item in sap:
        # Los equipos hijos no son renglones del BOM.
        if sap_item.entry_kind != "material":
            continue
        code = canonical_sap_code(sap_item.sap_code)
        if code is None:
            results.append(
                _sap_entry(
                    sap_item,
                    ReconciliationClass.UNRESOLVED,
                    reason="sap_item_without_material_code",
                )
            )
            continue
        sap_by_code.setdefault(code, []).append(sap_item)

    for code in sorted(set(engineering_by_code) | set(sap_by_code)):
        left = engineering_by_code.get(code, [])
        right = sap_by_code.get(code, [])

        if left and not right:
            results.extend(
                _engineering_entry(item, ReconciliationClass.ENGINEERING_ONLY) for item in left
            )
            continue
        if right and not left:
            results.extend(_sap_entry(item, ReconciliationClass.SAP_ONLY) for item in right)
            continue

        if len(left) != 1 or len(right) != 1:
            # El material aparece repetido en algún lado. Emparejar «el
            # primero con el primero» sería inventar una correspondencia, así
            # que se declara la diferencia estructural y se conservan todos
            # los renglones implicados.
            detail = {
                "engineering_rows": str(len(left)),
                "sap_rows": str(len(right)),
            }
            results.extend(
                _engineering_entry(
                    item, ReconciliationClass.DUPLICATE_OR_STRUCTURAL_DIFFERENCE, **detail
                )
                for item in left
            )
            results.extend(
                _sap_entry(item, ReconciliationClass.DUPLICATE_OR_STRUCTURAL_DIFFERENCE, **detail)
                for item in right
            )
            continue

        engineering_match, sap_match = left[0], right[0]
        if engineering_match.quantity is None or sap_match.quantity is None:
            classification = ReconciliationClass.UNRESOLVED
            detail = {"reason": "missing_quantity"}
        elif _same_quantity(engineering_match.quantity, sap_match.quantity):
            classification = ReconciliationClass.MATCH
            detail = {}
        else:
            classification = ReconciliationClass.QUANTITY_DIFFERENCE
            detail = {}

        results.append(
            ReconciliationEntry(
                classification=classification,
                bom_item_id=engineering_match.item_id,
                snapshot_item_id=sap_match.item_id,
                component_id=engineering_match.component_id,
                sap_code=engineering_match.sap_code,
                engineering_quantity=engineering_match.quantity,
                sap_quantity=sap_match.quantity,
                engineering_unit=engineering_match.unit,
                sap_unit=sap_match.unit,
                engineering_description=engineering_match.description,
                sap_description=sap_match.description,
                detail=detail,
            )
        )

    return tuple(results)


def summarize(entries: Sequence[ReconciliationEntry]) -> dict[str, int]:
    """Conteos por clasificación, aptos para ``reconciliation_runs.stats``."""
    totals = {classification.value: 0 for classification in ReconciliationClass}
    for entry in entries:
        totals[entry.classification.value] += 1
    return totals
