"""Rechazo de paquetes XLSX que no deberían aceptarse.

Todo lo que hay aquí ocurre **antes** de leer una sola celda: el archivo se
juzga por su estructura, nunca por su extensión.
"""

import io
import zipfile

import pytest

from elsa.ingestion.errors import (
    ArchiveTooLargeError,
    FileRejectedError,
    FileTooLargeError,
    MacroEnabledWorkbookError,
    NotAnOpenXmlFileError,
    UnsafeArchiveEntryError,
)
from elsa.ingestion.safety import ArchiveLimits, inspect_xlsx
from tests.fixtures_xlsx import BOM_HEADERS, build_workbook

_MINIMAL = [("[Content_Types].xml", "<x/>"), ("xl/workbook.xml", "<x/>")]


def _zip(entries: list[tuple[str, str]], compress: bool = False) -> bytes:
    buffer = io.BytesIO()
    mode = zipfile.ZIP_DEFLATED if compress else zipfile.ZIP_STORED
    with zipfile.ZipFile(buffer, "w", mode) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return buffer.getvalue()


def test_a_real_workbook_is_accepted() -> None:
    inspection = inspect_xlsx(build_workbook({"BOM": [BOM_HEADERS]}))

    assert "[Content_Types].xml" in inspection.entry_names
    assert inspection.warnings == ()


@pytest.mark.parametrize(
    "payload",
    [b"", b"not a zip at all", b"PK\x03\x04truncated"],
    ids=["empty", "fake extension", "truncated"],
)
def test_anything_that_is_not_an_openxml_package_is_rejected(payload: bytes) -> None:
    """La extensión no es prueba de nada: manda la estructura real."""
    with pytest.raises(NotAnOpenXmlFileError):
        inspect_xlsx(payload)


def test_a_workbook_without_a_workbook_part_is_rejected() -> None:
    with pytest.raises(NotAnOpenXmlFileError):
        inspect_xlsx(_zip([("[Content_Types].xml", "<x/>")]))


def test_macros_are_rejected_by_content_not_by_extension() -> None:
    """Un `.xlsm` renombrado a `.xlsx` se detecta igual."""
    with pytest.raises(MacroEnabledWorkbookError):
        inspect_xlsx(_zip([*_MINIMAL, ("xl/vbaProject.bin", "MZ")]))


@pytest.mark.parametrize(
    "name",
    ["../escape.xml", "/absolute.xml", "xl/../../escape.xml", "C:/windows/evil.xml"],
)
def test_path_traversal_entries_are_rejected(name: str) -> None:
    with pytest.raises(UnsafeArchiveEntryError):
        inspect_xlsx(_zip([*_MINIMAL, (name, "x")]))


@pytest.mark.parametrize("name", ["xl/payload.exe", "xl/macro.vbs", "docProps/run.sh"])
def test_executable_entries_are_rejected(name: str) -> None:
    with pytest.raises(UnsafeArchiveEntryError):
        inspect_xlsx(_zip([*_MINIMAL, (name, "MZ")]))


def test_a_decompression_bomb_is_rejected() -> None:
    """Unos kilobytes comprimidos que declaran mucho más al expandirse.

    El límite del test es pequeño a propósito para que la suite siga siendo
    rápida: lo que se comprueba es que la expansión declarada se mide antes
    de descomprimir nada, no la magnitud concreta del umbral.
    """
    payload = _zip([*_MINIMAL, ("xl/bomb.xml", "A" * 8_000_000)], compress=True)
    assert len(payload) < 100_000

    with pytest.raises(ArchiveTooLargeError):
        inspect_xlsx(payload, ArchiveLimits(max_uncompressed_bytes=1_000_000))


def test_a_file_over_the_size_limit_is_rejected() -> None:
    with pytest.raises(FileTooLargeError):
        inspect_xlsx(build_workbook({"BOM": [BOM_HEADERS]}), ArchiveLimits(max_bytes=10))


def test_too_many_entries_are_rejected() -> None:
    entries = [*_MINIMAL, *[(f"xl/part{i}.xml", "x") for i in range(20)]]

    with pytest.raises(FileRejectedError):
        inspect_xlsx(_zip(entries), ArchiveLimits(max_entries=5))


def test_external_links_are_reported_but_never_resolved() -> None:
    """Se avisa de que existen; no se abre ninguna dirección."""
    payload = _zip([*_MINIMAL, ("xl/externalLinks/externalLink1.xml", "<x/>")])

    codes = {warning.code for warning in inspect_xlsx(payload).warnings}

    assert "external_links_present" in codes


def test_external_data_connections_are_reported_but_never_opened() -> None:
    payload = _zip([*_MINIMAL, ("xl/connections.xml", "<x/>")])

    codes = {warning.code for warning in inspect_xlsx(payload).warnings}

    assert "external_connections_present" in codes


def test_unexpected_entries_are_reported_and_not_read() -> None:
    payload = _zip([*_MINIMAL, ("weird/extra.xml", "<x/>")])

    codes = {warning.code for warning in inspect_xlsx(payload).warnings}

    assert "unexpected_package_entries" in codes
