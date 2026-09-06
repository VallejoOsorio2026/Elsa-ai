"""Export de SAP con los registros repartidos en varios ``<nobr>``.

Es la forma que el parser no soportaba: SAP no dibuja un renglón como una
cadena, sino que lo reparte en fragmentos con iconos intercalados y usa
``<br>`` como frontera. Tratar ``</nobr>`` como fin de renglón partía cada
registro en tantos trozos como columnas tenía, y ninguno se reconocía.

Todo el contenido es inventado (`MAT-FAKE-001`, `LOC-FAKE-001`).
"""

from datetime import date
from decimal import Decimal

import pytest

from elsa.ingestion.errors import UnrecognizedFormatError
from elsa.ingestion.model import ParsedSapSnapshot
from elsa.ingestion.sap_htm import parse_sap_snapshot
from tests.fixtures_sap_export import (
    EQUIPMENT_CODE,
    FRAGMENTED_EXPORT,
    LOCATION,
    MATERIAL_CODES,
    build_export,
    equipment_line,
    material_line,
    metadata_lines,
)


@pytest.fixture
def snapshot() -> ParsedSapSnapshot:
    return parse_sap_snapshot(FRAGMENTED_EXPORT)


# ---------------------------------------------------------------------
# Estructura fragmentada
# ---------------------------------------------------------------------


def test_an_export_with_no_table_at_all_is_parsed(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.diagnostics["html_tables_seen"] == 0
    assert len(snapshot.items) == 3


def test_a_record_split_across_several_fragments_is_reassembled(
    snapshot: ParsedSapSnapshot,
) -> None:
    """Cada campo viene en su propio `<nobr>`: código, texto, cantidad y UM."""
    assert snapshot.diagnostics["nobr_fragments_seen"] > len(snapshot.items) * 3
    material = snapshot.materials[0]
    assert material.sap_code == MATERIAL_CODES[0]
    assert material.description == "Repuesto ficticio A"
    assert material.quantity == Decimal(2)
    assert material.unit == "UN"


def test_fragments_are_grouped_up_to_the_line_break(snapshot: ParsedSapSnapshot) -> None:
    """Tantos registros como `<br>` con contenido, no como `</nobr>`."""
    assert snapshot.diagnostics["logical_lines_built"] == 6
    assert snapshot.diagnostics["br_boundaries_seen"] > 6


def test_an_export_that_uses_only_nobr_without_br_still_parses() -> None:
    """Sin un solo `<br>`, el cierre de `<nobr>` sí delimita el renglón."""
    body = (
        "<nobr>Ubic.t&eacute;cn.&nbsp;&nbsp;LOC-FAKE-002</nobr>"
        '<nobr>&nbsp;&nbsp;<img title="Material">MAT-FAKE-009&nbsp;&nbsp;'
        "Pieza ficticia&nbsp;&nbsp;3&nbsp;&nbsp;UN</nobr>"
    )

    snapshot = parse_sap_snapshot(build_export(body))

    assert snapshot.functional_location == "LOC-FAKE-002"
    assert snapshot.materials[0].quantity == Decimal(3)


# ---------------------------------------------------------------------
# Espaciado
# ---------------------------------------------------------------------


def test_non_breaking_spaces_become_field_separators(snapshot: ParsedSapSnapshot) -> None:
    """`&nbsp;&nbsp;` separa columnas igual que dos espacios normales."""
    assert snapshot.materials[0].description == "Repuesto ficticio A"


def test_indentation_made_of_non_breaking_spaces_drives_the_hierarchy(
    snapshot: ParsedSapSnapshot,
) -> None:
    """La sangría se mide antes de colapsar espacios; si no, se pierde."""
    assert snapshot.equipments[0].depth == 0
    assert all(item.depth == 1 for item in snapshot.materials)


def test_a_deeper_indentation_produces_a_deeper_level() -> None:
    body = (
        metadata_lines()
        + equipment_line(indent=2)
        + material_line("MAT-FAKE-010", "Pieza ficticia", "1", "UN", indent=8)
    )

    snapshot = parse_sap_snapshot(build_export(body))

    assert snapshot.materials[0].depth > snapshot.equipments[0].depth


# ---------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------


def test_metadata_split_across_fragments_is_read(snapshot: ParsedSapSnapshot) -> None:
    """Etiqueta, separador y valor en tres `<nobr>` distintos."""
    assert snapshot.functional_location == LOCATION


def test_the_description_is_read(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.description == "Conjunto ficticio"


def test_the_valid_from_date_is_read(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.valid_from == date(2026, 1, 1)


def test_metadata_inside_a_single_fragment_is_also_read() -> None:
    body = (
        "<nobr>Ubic.t&eacute;cn.&nbsp;&nbsp;LOC-FAKE-003</nobr><br>"
        + equipment_line()
        + material_line("MAT-FAKE-011", "Pieza ficticia", "1", "UN")
    )

    snapshot = parse_sap_snapshot(build_export(body))

    assert snapshot.functional_location == "LOC-FAKE-003"


# ---------------------------------------------------------------------
# Clasificación por icono
# ---------------------------------------------------------------------


def test_a_material_is_recognised_from_the_icon_title(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.diagnostics["icon_material_signals"] == 2
    assert len(snapshot.materials) == 2


def test_an_equipment_is_recognised_from_the_icon_title(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.diagnostics["icon_equipment_signals"] == 1
    assert snapshot.equipments[0].sap_code == EQUIPMENT_CODE


def test_a_material_is_recognised_from_the_icon_alt() -> None:
    body = metadata_lines() + material_line(
        "MAT-FAKE-012", "Pieza ficticia", "5", "UN", icon_attribute="alt"
    )

    snapshot = parse_sap_snapshot(build_export(body))

    assert len(snapshot.materials) == 1


def test_an_equipment_is_recognised_from_the_icon_alt() -> None:
    body = metadata_lines() + equipment_line(icon_attribute="alt")

    snapshot = parse_sap_snapshot(build_export(body))

    assert len(snapshot.equipments) == 1


def test_the_image_filename_alone_never_overrides_a_declared_title() -> None:
    """El recurso se llama «matl» pero declara Equipo: manda lo declarado."""
    body = metadata_lines() + (
        '<nobr>&nbsp;&nbsp;</nobr><img src="/sap/s_b_matl.gif" title="Equipo">'
        "<nobr>EQ-FAKE-777</nobr><nobr>&nbsp;&nbsp;Subconjunto ficticio</nobr><br>"
    )

    snapshot = parse_sap_snapshot(build_export(body))

    assert len(snapshot.equipments) == 1
    assert len(snapshot.materials) == 0


def test_a_line_declaring_both_types_is_the_asset_root_and_is_not_imported() -> None:
    """Llevar las dos señales a la vez identifica la raíz del activo.

    La raíz es material y objeto técnico al mismo tiempo, así que no es un
    renglón del BOM y no se importa como tal. Antes se trataba como una
    contradicción entre iconos; el efecto práctico era el mismo —no se
    importaba— pero el diagnóstico la contaba como un registro técnico que no
    se supo resolver, que es justamente lo que no es.
    """
    body = metadata_lines() + (
        '<nobr>&nbsp;&nbsp;</nobr><img title="Material"><img title="Equipo">'
        "<nobr>MAT-FAKE-013</nobr><nobr>&nbsp;&nbsp;Pieza ficticia</nobr>"
        "<nobr>&nbsp;&nbsp;1</nobr><nobr>&nbsp;&nbsp;UN</nobr><br>"
        + material_line("MAT-FAKE-014", "Pieza ficticia", "1", "UN")
    )

    snapshot = parse_sap_snapshot(build_export(body))

    assert all(item.sap_code != "MAT-FAKE-013" for item in snapshot.items)
    assert snapshot.diagnostics["root_lines"] == 1
    assert snapshot.diagnostics["unresolved_records"] == 0


# ---------------------------------------------------------------------
# Campos
# ---------------------------------------------------------------------


def test_the_code_is_never_consumed_as_the_quantity() -> None:
    """Regresión: un código numérico se llevaba el papel de cantidad."""
    body = metadata_lines() + (
        '<nobr>&nbsp;&nbsp;</nobr><img title="Material">'
        "<nobr>90000001</nobr><nobr>&nbsp;&nbsp;Pieza ficticia</nobr>"
        "<nobr>&nbsp;&nbsp;s/d</nobr><br>"
    )

    snapshot = parse_sap_snapshot(build_export(body))

    assert snapshot.materials[0].sap_code == "90000001"
    assert snapshot.materials[0].quantity is None


def test_a_decimal_quantity_is_read() -> None:
    body = metadata_lines() + material_line("MAT-FAKE-015", "Pieza ficticia", "1,5", "KG")

    snapshot = parse_sap_snapshot(build_export(body))

    assert snapshot.materials[0].quantity == Decimal("1.5")


def test_the_hierarchy_is_kept_when_it_can_be_proved(snapshot: ParsedSapSnapshot) -> None:
    assert all(item.extra["parent_code"] == EQUIPMENT_CODE for item in snapshot.materials)


def test_an_unprovable_parent_is_reported_and_the_record_kept() -> None:
    """El material vale aunque su padre no pueda identificarse."""
    body = metadata_lines() + material_line("MAT-FAKE-016", "Pieza ficticia", "1", "UN", indent=6)

    snapshot = parse_sap_snapshot(build_export(body))

    assert len(snapshot.materials) == 1
    assert "parent_code" not in snapshot.materials[0].extra


# ---------------------------------------------------------------------
# Robustez y seguridad
# ---------------------------------------------------------------------


def test_arbitrary_html_identifiers_change_nothing(snapshot: ParsedSapSnapshot) -> None:
    renamed = FRAGMENTED_EXPORT.decode("utf-8").replace('id="', 'id="l00600')

    other = parse_sap_snapshot(renamed.encode("utf-8"))

    assert [item.sap_code for item in other.items] == [item.sap_code for item in snapshot.items]


def test_unclosed_tags_are_tolerated(snapshot: ParsedSapSnapshot) -> None:
    broken = FRAGMENTED_EXPORT.decode("utf-8").replace("</nobr>", "")

    other = parse_sap_snapshot(broken.encode("utf-8"))

    assert len(other.materials) == len(snapshot.materials)


def test_empty_fragments_and_blank_lines_are_ignored(snapshot: ParsedSapSnapshot) -> None:
    assert all(item.sap_code for item in snapshot.items)


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>fetch('http://atacante.invalido/x')</script>",
        '<iframe src="https://remoto.invalido/marco"></iframe>',
        '<img src="http://remoto.invalido/pixel.gif">',
        '<link rel="stylesheet" href="https://remoto.invalido/x.css">',
        '<a href="javascript:alert(1)">x</a>',
    ],
)
def test_active_content_is_never_executed_and_never_fetched(hostile: str) -> None:
    body = (
        hostile
        + metadata_lines()
        + equipment_line()
        + material_line("MAT-FAKE-017", "Pieza ficticia", "1", "UN")
    )

    snapshot = parse_sap_snapshot(build_export(body))

    assert len(snapshot.materials) == 1
    assert all("atacante" not in (item.description or "") for item in snapshot.items)


def test_scripts_are_reported_as_ignored() -> None:
    body = (
        "<script>alert(1)</script>"
        + metadata_lines()
        + material_line("MAT-FAKE-018", "Pieza ficticia", "1", "UN")
    )

    snapshot = parse_sap_snapshot(build_export(body))

    assert "script_content_ignored" in {w.code for w in snapshot.warnings}


# ---------------------------------------------------------------------
# Diagnóstico
# ---------------------------------------------------------------------


def test_the_diagnostics_report_every_stage(snapshot: ParsedSapSnapshot) -> None:
    for stage in (
        "nobr_fragments_seen",
        "br_boundaries_seen",
        "logical_lines_built",
        "candidate_records",
        "parsed_material_records",
        "parsed_equipment_records",
        "unresolved_records",
    ):
        assert stage in snapshot.diagnostics, stage


def test_the_diagnostics_are_only_counts(snapshot: ParsedSapSnapshot) -> None:
    """Sirven para diagnosticar un archivo que no puede compartirse."""
    assert all(isinstance(value, int) for value in snapshot.diagnostics.values())
    serialised = str(snapshot.diagnostics)
    assert LOCATION not in serialised
    assert all(code not in serialised for code in MATERIAL_CODES)


def test_a_failed_parse_still_carries_the_diagnostics() -> None:
    """Sin ellos no hay forma de saber en qué etapa se detuvo."""
    with pytest.raises(UnrecognizedFormatError) as raised:
        parse_sap_snapshot(build_export("<nobr>Informe sin estructura</nobr><br>"))

    assert raised.value.diagnostics["logical_lines_built"] == 1
    assert raised.value.diagnostics["parsed_material_records"] == 0
