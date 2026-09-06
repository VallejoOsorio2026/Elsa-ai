"""Árbol de estructura de SAP, con la forma completa del export real.

Es la forma que quedaba bloqueada: cada renglón lleva delante los trazos del
árbol y un símbolo en la tipografía ``SAPDings``, y los materiales **no traen
icono de material**. El trazo ocupaba el primer campo, la extracción del
identificador fallaba y el renglón entero se descartaba.

Todo el contenido es inventado (`FAKE0001`, `LOC-FAKE-100`).
"""

from datetime import date
from decimal import Decimal

import pytest

from elsa.ingestion.errors import UnrecognizedFormatError
from elsa.ingestion.model import ParsedSapSnapshot
from elsa.ingestion.sap_htm import parse_sap_snapshot
from tests.fixtures_sap_export import (
    STRUCTURE_TREE_EXPORT,
    TREE_EQUIPMENT_CODES,
    TREE_LOCATION,
    TREE_MATERIAL_CODES,
    build_export,
    structure_tree_export,
    tree_equipment_line,
    tree_material_line,
    tree_metadata_line,
    tree_root_line,
)


@pytest.fixture
def snapshot() -> ParsedSapSnapshot:
    return parse_sap_snapshot(STRUCTURE_TREE_EXPORT)


# ---------------------------------------------------------------------
# Resultado del mini-export completo
# ---------------------------------------------------------------------


def test_the_tree_export_yields_its_materials_and_equipments(
    snapshot: ParsedSapSnapshot,
) -> None:
    assert len(snapshot.materials) == 3
    assert len(snapshot.equipments) == 2


def test_nothing_is_left_unresolved(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.diagnostics["unresolved_records"] == 0


def test_a_material_is_imported_without_any_material_icon(
    snapshot: ParsedSapSnapshot,
) -> None:
    """Los materiales del árbol real no llevan icono de material."""
    assert snapshot.diagnostics["icon_material_signals"] == 0
    assert [item.sap_code for item in snapshot.materials] == list(TREE_MATERIAL_CODES)


def test_an_equipment_is_imported_from_its_icon(snapshot: ParsedSapSnapshot) -> None:
    """Uno declara el tipo en `title` y el otro en `alt`."""
    assert snapshot.diagnostics["icon_equipment_signals"] == 2
    assert [item.sap_code for item in snapshot.equipments] == list(TREE_EQUIPMENT_CODES)


def test_an_icon_outside_nobr_still_belongs_to_its_line(
    snapshot: ParsedSapSnapshot,
) -> None:
    """El `<img>` es hermano de los `<nobr>`, no hijo."""
    body = tree_metadata_line() + tree_equipment_line("EQ-FAKE-900", "EQUIPO FICTICIO")

    other = parse_sap_snapshot(build_export(body))

    assert other.diagnostics["icon_equipment_signals"] == 1
    assert len(other.equipments) == 1


# ---------------------------------------------------------------------
# Clases de línea
# ---------------------------------------------------------------------


def test_the_asset_root_is_not_imported_as_a_bom_row(snapshot: ParsedSapSnapshot) -> None:
    """La raíz declara material y equipo a la vez: no es un renglón del BOM."""
    assert snapshot.diagnostics["root_lines"] == 1
    assert all(item.sap_code != TREE_LOCATION for item in snapshot.items)


def test_a_connector_line_is_not_imported(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.diagnostics["connector_lines"] == 1


def test_metadata_lines_are_not_technical_candidates(
    snapshot: ParsedSapSnapshot,
) -> None:
    assert snapshot.diagnostics["metadata_lines"] == 2


def test_candidates_count_only_technical_rows(snapshot: ParsedSapSnapshot) -> None:
    """Contar cabeceras, raíz y conectores ocultaba cuántos fallaban de verdad."""
    diagnostics = snapshot.diagnostics

    assert diagnostics["candidate_records"] == 5
    assert diagnostics["candidate_records"] == (
        diagnostics["parsed_material_records"]
        + diagnostics["parsed_equipment_records"]
        + diagnostics["unresolved_records"]
    )
    assert diagnostics["logical_lines_built"] > diagnostics["candidate_records"]


# ---------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------


def test_two_metadata_fields_on_one_line_are_both_read(
    snapshot: ParsedSapSnapshot,
) -> None:
    assert snapshot.functional_location == TREE_LOCATION
    assert snapshot.valid_from == date(2026, 1, 1)


def test_the_description_is_read_from_its_own_line(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.description == "ACTIVO FICTICIO"


def test_every_detected_label_gets_a_value(snapshot: ParsedSapSnapshot) -> None:
    """La diferencia entre ambos conteos delata un rótulo sin valor."""
    assert (
        snapshot.diagnostics["metadata_values_resolved"]
        == snapshot.diagnostics["metadata_labels_detected"]
    )


def test_a_label_and_its_value_on_consecutive_lines_are_paired() -> None:
    body = (
        "<nobr>Ubic.t&eacute;cn.</nobr><br>\n"
        "<nobr>LOC-FAKE-500</nobr><br>\n"
        + tree_material_line("FAKE9001", "PIEZA FICTICIA&nbsp;&nbsp;&nbsp;2&nbsp;&nbsp;UN")
    )

    other = parse_sap_snapshot(build_export(body))

    assert other.functional_location == "LOC-FAKE-500"


def test_a_separator_fragment_between_label_and_value_is_skipped() -> None:
    body = (
        "<nobr>Ubic.t&eacute;cn.</nobr><nobr>:</nobr><nobr>LOC-FAKE-600</nobr><br>\n"
        + tree_material_line("FAKE9002", "PIEZA FICTICIA&nbsp;&nbsp;&nbsp;2&nbsp;&nbsp;UN")
    )

    other = parse_sap_snapshot(build_export(body))

    assert other.functional_location == "LOC-FAKE-600"


# ---------------------------------------------------------------------
# SAPDings y trazos del árbol
# ---------------------------------------------------------------------


def test_a_sapdings_symbol_is_never_taken_for_a_code(snapshot: ParsedSapSnapshot) -> None:
    """El `0` del árbol es un glifo, no un dato."""
    assert all(item.sap_code not in ("0", "4") for item in snapshot.items)


def test_a_sapdings_symbol_is_never_taken_for_a_quantity(
    snapshot: ParsedSapSnapshot,
) -> None:
    quantities = {item.quantity for item in snapshot.materials}

    assert Decimal(0) not in quantities
    assert quantities == {Decimal(8), Decimal(28), Decimal("1.5")}


def test_a_sapdings_symbol_is_never_taken_for_a_description(
    snapshot: ParsedSapSnapshot,
) -> None:
    assert all("0" != (item.description or "") for item in snapshot.items)


def test_a_tree_marker_is_never_taken_for_a_field(snapshot: ParsedSapSnapshot) -> None:
    for item in snapshot.items:
        assert "|" not in (item.sap_code or "")
        assert not (item.description or "").startswith("|")


# ---------------------------------------------------------------------
# Identificador, cantidad y unidad
# ---------------------------------------------------------------------


def test_a_numeric_code_is_never_consumed_as_the_quantity(
    snapshot: ParsedSapSnapshot,
) -> None:
    numeric = next(item for item in snapshot.materials if item.sap_code == "90001234")

    assert numeric.quantity == Decimal(28)


def test_an_alphanumeric_identifier_is_read(snapshot: ParsedSapSnapshot) -> None:
    assert "MAT-FAKE-200" in {item.sap_code for item in snapshot.materials}


def test_numbers_inside_the_description_are_not_the_quantity(
    snapshot: ParsedSapSnapshot,
) -> None:
    """«REPUESTO FICTICIO 123 ABC» conserva sus números."""
    first = snapshot.materials[0]

    assert "123" in (first.description or "")
    assert first.quantity == Decimal(8)


def test_quantity_and_unit_come_from_the_right_end_of_the_payload(
    snapshot: ParsedSapSnapshot,
) -> None:
    """Descripción, estado, cantidad y unidad comparten un solo fragmento."""
    first = snapshot.materials[0]

    assert first.quantity == Decimal(8)
    assert first.unit == "UN"


def test_a_decimal_quantity_is_read(snapshot: ParsedSapSnapshot) -> None:
    third = next(item for item in snapshot.materials if item.sap_code == "MAT-FAKE-200")

    assert third.quantity == Decimal("1.5")
    assert third.unit == "KG"


def test_the_unit_is_whatever_the_file_says(snapshot: ParsedSapSnapshot) -> None:
    """Nada está fijado a una unidad concreta."""
    assert {item.unit for item in snapshot.materials} == {"UN", "PZA", "KG"}


def test_a_quantity_and_unit_split_across_fragments_are_read() -> None:
    body = tree_metadata_line() + (
        "<nobr>&nbsp;&nbsp;</nobr><nobr>|---</nobr><nobr>FAKE9003</nobr>"
        "<nobr>&nbsp;PIEZA FICTICIA</nobr><nobr>&nbsp;&nbsp;7</nobr>"
        "<nobr>&nbsp;&nbsp;ST</nobr><br>"
    )

    other = parse_sap_snapshot(build_export(body))

    assert other.materials[0].quantity == Decimal(7)
    assert other.materials[0].unit == "ST"


# ---------------------------------------------------------------------
# Seguridad
# ---------------------------------------------------------------------


def test_active_content_is_reported_and_never_executed(
    snapshot: ParsedSapSnapshot,
) -> None:
    codes = {warning.code for warning in snapshot.warnings}

    assert "script_content_ignored" in codes
    assert "remote_references_ignored" in codes
    assert all("atacante" not in (item.description or "") for item in snapshot.items)


def test_the_same_export_without_hostile_content_parses_identically(
    snapshot: ParsedSapSnapshot,
) -> None:
    clean = parse_sap_snapshot(structure_tree_export(hostile=False))

    assert [item.sap_code for item in clean.items] == [item.sap_code for item in snapshot.items]


def test_arbitrary_html_identifiers_change_nothing(snapshot: ParsedSapSnapshot) -> None:
    renamed = STRUCTURE_TREE_EXPORT.decode("utf-8").replace('id="t', 'id="l0060')

    other = parse_sap_snapshot(renamed.encode("utf-8"))

    assert [item.sap_code for item in other.items] == [item.sap_code for item in snapshot.items]


def test_unclosed_tags_are_tolerated(snapshot: ParsedSapSnapshot) -> None:
    broken = STRUCTURE_TREE_EXPORT.decode("utf-8").replace("</nobr>", "")

    other = parse_sap_snapshot(broken.encode("utf-8"))

    assert len(other.materials) == len(snapshot.materials)


def test_a_checkbox_control_contributes_no_field(snapshot: ParsedSapSnapshot) -> None:
    """El `<input type="checkbox">` que precede a cada material no es un dato."""
    assert all(item.description != "on" for item in snapshot.items)


def test_the_root_line_alone_produces_no_records() -> None:
    """Sin ningún renglón técnico, el export no aporta nada que importar."""
    body = tree_metadata_line() + tree_root_line()

    with pytest.raises(UnrecognizedFormatError) as raised:
        parse_sap_snapshot(build_export(body))

    assert raised.value.diagnostics["root_lines"] == 1
    assert raised.value.diagnostics["candidate_records"] == 0
