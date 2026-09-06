"""Contrato de la prueba de aceptación privada.

Lo que se comprueba aquí no es qué extrae, sino **cuándo dice que pasó**.
La aceptación existe para decidir si el bloque está bien; si un reporte con
errores puede terminar en 0, deja de servir para eso.

Los archivos son sintéticos y viven en `tmp_path`, nunca en el repositorio.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from elsa.tools.private_acceptance import (
    EXIT_ACCEPTANCE_FAILED,
    EXIT_CANNOT_RUN,
    EXIT_OK,
    main,
)
from tests.fixtures_sap_export import FRAGMENTED_EXPORT, STRUCTURE_TREE_EXPORT
from tests.fixtures_sources import engineering_workbook, sap_export


@pytest.fixture
def sources(tmp_path: Path) -> dict[str, Path]:
    engineering = tmp_path / "bom.xlsx"
    engineering.write_bytes(engineering_workbook())
    sap = tmp_path / "export.HTM"
    sap.write_bytes(sap_export())
    return {"engineering": engineering, "sap": sap, "out": tmp_path / "reporte.json"}


def _run(sources: dict[str, Path], **overrides: Path) -> int:
    paths = {**sources, **overrides}
    return main(
        [
            "--engineering",
            str(paths["engineering"]),
            "--sap",
            str(paths["sap"]),
            "--out",
            str(paths["out"]),
            "--artifact-root",
            str(paths["out"].parent / "artifacts"),
        ]
    )


def _report(sources: dict[str, Path]) -> dict[str, Any]:
    content: dict[str, Any] = json.loads(sources["out"].read_text(encoding="utf-8"))
    return content


def test_two_valid_sources_pass(sources: dict[str, Path]) -> None:
    assert _run(sources) == EXIT_OK
    report = _report(sources)
    assert report["verdict"] == "passed"
    assert report["errors"] == []


def test_a_passing_run_still_reports_its_warnings(sources: dict[str, Path]) -> None:
    """Warnings y aceptación correcta no se excluyen."""
    _run(sources)

    report = _report(sources)
    assert report["warnings"]
    assert report["verdict"] == "passed"


def test_the_report_carries_counts_and_never_content(sources: dict[str, Path]) -> None:
    _run(sources)

    report = _report(sources)
    assert report["engineering"]["components"] > 0
    assert report["sap"]["materials"] > 0
    assert report["reconciliation"]
    # Ninguna descripción ni ningún código individual viaja en el reporte.
    serialised = json.dumps(report)
    assert "Rodamiento" not in serialised


def test_an_unreadable_sap_source_fails_the_acceptance(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    broken = tmp_path / "roto.HTM"
    broken.write_bytes(b"<html><body><p>sin estructura</p></body></html>")

    assert _run(sources, sap=broken) == EXIT_ACCEPTANCE_FAILED
    assert _report(sources)["verdict"] == "failed"


def test_an_unreadable_engineering_source_fails_the_acceptance(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    broken = tmp_path / "roto.xlsx"
    broken.write_bytes(b"no soy un libro de excel")

    assert _run(sources, engineering=broken) == EXIT_ACCEPTANCE_FAILED


def test_a_failed_acceptance_still_writes_the_report_for_diagnosis(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    """El reporte de un fallo es justamente el material del diagnóstico."""
    broken = tmp_path / "roto.HTM"
    broken.write_bytes(b"<html><body><p>sin estructura</p></body></html>")

    _run(sources, sap=broken)

    report = _report(sources)
    assert report["errors"][0]["stage"] == "sap"
    assert report["errors"][0]["kind"] == "parse"


def test_any_error_prevents_a_successful_exit(sources: dict[str, Path], tmp_path: Path) -> None:
    """No existe el éxito parcial."""
    broken = tmp_path / "roto.HTM"
    broken.write_bytes(b"<html><body><p>sin estructura</p></body></html>")

    code = _run(sources, sap=broken)

    assert code != EXIT_OK
    assert _report(sources)["errors"] != []


def test_the_sap_source_is_obligatory(sources: dict[str, Path]) -> None:
    """Omitirla terminaba en 0 y daba media prueba por aprobada."""
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "--engineering",
                str(sources["engineering"]),
                "--out",
                str(sources["out"]),
            ]
        )

    assert raised.value.code != EXIT_OK


def test_a_missing_input_file_cannot_run(sources: dict[str, Path], tmp_path: Path) -> None:
    assert _run(sources, engineering=tmp_path / "no-existe.xlsx") == EXIT_CANNOT_RUN


def test_an_unwritable_report_path_cannot_run(sources: dict[str, Path], tmp_path: Path) -> None:
    occupied = tmp_path / "soy-un-archivo"
    occupied.write_bytes(b"x")

    assert _run(sources, out=occupied / "dentro" / "reporte.json") == EXIT_CANNOT_RUN


def test_the_real_sources_are_never_copied_into_the_repository(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    """Todo lo que produce la aceptación queda bajo la ruta indicada."""
    _run(sources)

    produced = {path for path in tmp_path.rglob("*") if path.is_file()}
    assert produced
    assert all(str(path).startswith(str(tmp_path)) for path in produced)


# ---------------------------------------------------------------------
# Diagnóstico estructural del parser SAP
# ---------------------------------------------------------------------


def test_a_failed_sap_parse_reports_where_it_stopped(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    """Sin esto no hay forma de diagnosticar un archivo que no puede compartirse."""
    broken = tmp_path / "roto.HTM"
    broken.write_bytes(b"<html><body><nobr>Informe sin estructura</nobr><br></body></html>")

    _run(sources, sap=broken)

    diagnostics = _report(sources)["sap_parser_diagnostics"]
    assert diagnostics["logical_lines_built"] >= 1
    assert diagnostics["parsed_material_records"] == 0


def test_a_successful_run_also_reports_the_diagnostics(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    fragmented = tmp_path / "fragmentado.HTM"
    fragmented.write_bytes(FRAGMENTED_EXPORT)

    assert _run(sources, sap=fragmented) == EXIT_OK

    diagnostics = _report(sources)["sap_parser_diagnostics"]
    assert diagnostics["parsed_material_records"] == 2
    assert diagnostics["parsed_equipment_records"] == 1


def test_the_diagnostics_never_carry_technical_content(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    fragmented = tmp_path / "fragmentado.HTM"
    fragmented.write_bytes(FRAGMENTED_EXPORT)
    _run(sources, sap=fragmented)

    diagnostics = _report(sources)["sap_parser_diagnostics"]

    assert all(isinstance(value, int) for value in diagnostics.values())
    serialised = json.dumps(diagnostics)
    assert "LOC-FAKE" not in serialised
    assert "MAT-FAKE" not in serialised


def test_the_fragmented_export_reaches_reconciliation(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    """El formato real llega hasta el final del flujo, no solo al parser."""
    fragmented = tmp_path / "fragmentado.HTM"
    fragmented.write_bytes(FRAGMENTED_EXPORT)

    assert _run(sources, sap=fragmented) == EXIT_OK

    report = _report(sources)
    assert report["sap"]["materials"] == 2
    assert report["sap"]["equipments"] == 1
    assert report["sap"]["functional_location_present"] is True
    assert sum(report["reconciliation"].values()) > 0


def test_the_structure_tree_export_reaches_reconciliation(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    """La forma completa del árbol llega hasta el final del flujo."""
    tree = tmp_path / "arbol.HTM"
    tree.write_bytes(STRUCTURE_TREE_EXPORT)

    assert _run(sources, sap=tree) == EXIT_OK

    report = _report(sources)
    assert report["sap"]["materials"] == 3
    assert report["sap"]["equipments"] == 2
    assert report["sap"]["functional_location_present"] is True
    assert report["sap"]["valid_from"] is not None
    assert sum(report["reconciliation"].values()) > 0
    assert report["errors"] == []


def test_the_diagnostics_separate_line_classes(sources: dict[str, Path], tmp_path: Path) -> None:
    """Metadata, raíz y conectores no son candidatos técnicos."""
    tree = tmp_path / "arbol.HTM"
    tree.write_bytes(STRUCTURE_TREE_EXPORT)
    _run(sources, sap=tree)

    diagnostics = _report(sources)["sap_parser_diagnostics"]

    assert diagnostics["metadata_lines"] >= 1
    assert diagnostics["root_lines"] == 1
    assert diagnostics["connector_lines"] >= 1
    assert diagnostics["candidate_records"] == 5
    assert diagnostics["unresolved_records"] == 0
