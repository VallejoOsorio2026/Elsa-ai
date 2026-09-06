"""Clasificación de cambios entre versiones y comparación con SAP."""

from decimal import Decimal

from elsa.core.reconciliation import (
    EngineeringEntry,
    ReconciliationClass,
    ReconciliationEntry,
    SapEntry,
    reconcile,
    summarize,
)
from elsa.core.versioning import ChangeKind, VersionedItem, classify_versions, fingerprint

# ---------------------------------------------------------------------
# Versionado
# ---------------------------------------------------------------------


def _item(key: str, **values: object) -> VersionedItem:
    return VersionedItem(key=key, fingerprint=fingerprint(values))


def test_without_a_previous_version_everything_is_new() -> None:
    diff = classify_versions([], [_item("c1", quantity=Decimal(1))])

    assert diff.changes["c1"] is ChangeKind.NEW


def test_an_unchanged_row_keeps_its_validation() -> None:
    previous = [_item("c1", quantity=Decimal(2), name="Rodamiento")]
    current = [_item("c1", quantity=Decimal("2.00"), name="Rodamiento")]

    diff = classify_versions(previous, current)

    assert diff.changes["c1"] is ChangeKind.UNCHANGED
    assert diff.inheritable == ("c1",)


def test_a_changed_row_returns_to_review() -> None:
    previous = [_item("c1", quantity=Decimal(2))]
    current = [_item("c1", quantity=Decimal(3))]

    diff = classify_versions(previous, current)

    assert diff.changes["c1"] is ChangeKind.MODIFIED
    assert "c1" in diff.requires_review


def test_a_row_that_disappears_is_retired_not_deleted() -> None:
    diff = classify_versions([_item("c1", quantity=Decimal(1))], [])

    assert diff.retired == ("c1",)


def test_counts_cover_every_classification() -> None:
    diff = classify_versions(
        [_item("c1", q=1), _item("c9", q=1)],
        [_item("c1", q=2), _item("c3", q=1)],
    )

    assert diff.counts() == {"new": 1, "modified": 1, "unchanged": 0, "retired": 1}


def test_the_fingerprint_does_not_depend_on_key_order() -> None:
    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})


def test_different_field_splits_produce_different_fingerprints() -> None:
    """Separadores no imprimibles evitan colisiones por concatenación."""
    assert fingerprint({"a": "x", "b": "y"}) != fingerprint({"a": "xy", "b": ""})


# ---------------------------------------------------------------------
# Reconciliación
# ---------------------------------------------------------------------


def _sides() -> tuple[list[EngineeringEntry], list[SapEntry]]:
    engineering = [
        EngineeringEntry("e1", sap_code="10000001", component_id="c1", quantity=Decimal(2)),
        EngineeringEntry("e2", sap_code="10000002", component_id="c2", quantity=Decimal(10)),
        EngineeringEntry("e3", sap_code="10000003", component_id="c3", quantity=Decimal(1)),
        EngineeringEntry("e4", sap_code=None, component_id="c4", quantity=Decimal(5)),
        EngineeringEntry("e5", sap_code="10000005", component_id="c5", quantity=Decimal(1)),
        EngineeringEntry("e6", sap_code="10000005", component_id="c6", quantity=Decimal(1)),
    ]
    sap = [
        SapEntry("s1", sap_code="000000000010000001", quantity=Decimal(2)),
        SapEntry("s2", sap_code="10000002", quantity=Decimal(7)),
        SapEntry("s4", sap_code="10000009", quantity=Decimal(3)),
        SapEntry("s5", sap_code="10000005", quantity=Decimal(2)),
        SapEntry("sE", sap_code="EQ-1", entry_kind="equipment"),
    ]
    return engineering, sap


def _by_class(classification: ReconciliationClass) -> list[ReconciliationEntry]:
    engineering, sap = _sides()
    return [
        entry for entry in reconcile(engineering, sap) if entry.classification is classification
    ]


def test_same_material_and_quantity_is_a_match() -> None:
    matches = _by_class(ReconciliationClass.MATCH)

    assert len(matches) == 1
    assert matches[0].bom_item_id == "e1"


def test_same_material_different_quantity_keeps_both_values() -> None:
    entry = _by_class(ReconciliationClass.QUANTITY_DIFFERENCE)[0]

    assert entry.engineering_quantity == Decimal(10)
    assert entry.sap_quantity == Decimal(7)


def test_a_material_only_in_engineering_is_reported() -> None:
    assert [e.sap_code for e in _by_class(ReconciliationClass.ENGINEERING_ONLY)] == ["10000003"]


def test_a_material_only_in_sap_is_reported() -> None:
    assert [e.sap_code for e in _by_class(ReconciliationClass.SAP_ONLY)] == ["10000009"]


def test_a_repeated_material_is_a_structural_difference() -> None:
    """No se empareja «el primero con el primero»: sería inventar."""
    entries = _by_class(ReconciliationClass.DUPLICATE_OR_STRUCTURAL_DIFFERENCE)

    assert len(entries) == 3
    assert entries[0].detail["engineering_rows"] == "2"


def test_a_component_without_a_sap_code_is_unresolved_not_a_discrepancy() -> None:
    entry = _by_class(ReconciliationClass.UNRESOLVED)[0]

    assert entry.detail["reason"] == "engineering_item_without_sap_code"
    assert entry.bom_item_id == "e4"


def test_child_equipments_are_excluded_from_the_bom_comparison() -> None:
    engineering, sap = _sides()

    entries = reconcile(engineering, sap)

    assert all(entry.sap_code != "EQ-1" for entry in entries)


def test_a_missing_quantity_cannot_be_compared() -> None:
    entries = reconcile(
        [EngineeringEntry("e1", sap_code="1", quantity=None)],
        [SapEntry("s1", sap_code="1", quantity=Decimal(1))],
    )

    assert entries[0].classification is ReconciliationClass.UNRESOLVED
    assert entries[0].detail["reason"] == "missing_quantity"


def test_reconciliation_never_mutates_its_inputs() -> None:
    engineering, sap = _sides()
    before = (list(engineering), list(sap))

    reconcile(engineering, sap)

    assert (engineering, sap) == before


def test_reconciliation_is_deterministic() -> None:
    engineering, sap = _sides()

    assert reconcile(engineering, sap) == reconcile(engineering, sap)


def test_summary_counts_every_classification() -> None:
    engineering, sap = _sides()

    totals = summarize(reconcile(engineering, sap))

    assert totals["match"] == 1
    assert totals["quantity_difference"] == 1
    assert totals["duplicate_or_structural_difference"] == 3
