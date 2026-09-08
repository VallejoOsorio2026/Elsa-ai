"""La herramienta de aceptación documental reporta lo que hay que revisar.

Su contrato de salida es lo que decide si el bloque pasa, así que se prueba
como cualquier otra cosa que toma una decisión: con documentos sintéticos
conocidos y comprobando el código de salida, no solo el contenido.
"""

import json
from pathlib import Path

import pytest

from elsa.tools.document_acceptance import main
from tests import fixtures_documents as fx

pytestmark = pytest.mark.anyio


def write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def run(
    tmp_path: Path, text: str, *extra: str, second: str | None = None
) -> tuple[int, dict[str, object]]:
    source = write(tmp_path, "manual.md", text)
    out = tmp_path / "reporte.json"
    argv = ["--input", str(source), "--out", str(out), "--title", "Manual de ejemplo"]
    if second is not None:
        argv += ["--second", str(write(tmp_path, "manual-v2.md", second))]
    argv += [
        "--target-tokens",
        "60",
        "--max-tokens",
        "120",
        "--min-tokens",
        "10",
        "--overlap-tokens",
        "10",
        *extra,
    ]
    code = main(argv)
    report = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    return code, report


# ---------------------------------------------------------------------
# Contrato de salida
# ---------------------------------------------------------------------


def test_a_good_document_is_accepted(tmp_path: Path) -> None:
    code, report = run(tmp_path, fx.MANUAL_V1)

    assert code == 0
    assert report["errors"] == []


def test_an_invalid_document_fails_and_still_writes_the_report(tmp_path: Path) -> None:
    """El reporte es el material con el que se diagnostica: se escribe igual."""
    code, report = run(tmp_path, fx.EMPTY_DOCUMENT)

    assert code == 1
    assert report["errors"]
    assert report["validation"]["blocking"] == ["empty_document", "no_chunks"]


def test_a_missing_input_cannot_even_be_attempted(tmp_path: Path) -> None:
    code = main(
        ["--input", str(tmp_path / "no-existe.md"), "--out", str(tmp_path / "reporte.json")]
    )

    assert code == 2


def test_warnings_alone_do_not_fail_the_acceptance(tmp_path: Path) -> None:
    """Un chunk sobredimensionado es algo que una persona debe mirar, no un
    fallo del proceso."""
    code, report = run(tmp_path, fx.INDIVISIBLE_STEP)

    assert code == 0
    assert report["warnings"]["chunk_oversized"] == 1
    assert report["totals"]["oversized_chunks"] == 1


# ---------------------------------------------------------------------
# Qué reporta
# ---------------------------------------------------------------------


def test_the_report_lists_sections_with_their_tree_and_pages(tmp_path: Path) -> None:
    _, report = run(tmp_path, fx.MANUAL_V1)

    sections = report["sections"]
    by_path = {section["path"]: section for section in sections}

    assert by_path["1.3.2"]["title"] == "Inspeccion"
    assert by_path["1.3.2"]["number_label"] == "3.2"
    assert by_path["1.3.2"]["parent_path"] == "1.3"
    assert by_path["1.3.2"]["depth"] == 3
    assert by_path["1.3.2"]["page_start"] == 1


def test_the_report_lists_chunks_in_order_with_hashes_and_metadata(
    tmp_path: Path,
) -> None:
    _, report = run(tmp_path, fx.MANUAL_V1)

    chunks = report["chunks"]

    assert [chunk["ordinal"] for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert len(chunk["content_sha256"]) == 64
        assert chunk["structural_key"]
        assert chunk["section_title"]
        assert chunk["heading_trail"]
        assert chunk["page_start"] is not None
        assert chunk["kind"]


def test_the_report_counts_the_blocks_the_extractor_recognised(tmp_path: Path) -> None:
    _, report = run(tmp_path, fx.MANUAL_V1)

    kinds = report["extraction"]["blocks_by_kind"]

    assert kinds["heading"] == 7
    assert kinds["step"] == 3
    assert kinds["warning"] == 1
    assert kinds["table"] == 1


def test_the_report_records_the_policy_that_produced_it(tmp_path: Path) -> None:
    """Dos versiones chunkeadas con límites distintos no son comparables."""
    _, report = run(tmp_path, fx.MANUAL_V1)

    assert report["policy"]["target_tokens"] == 60
    assert report["policy"]["max_tokens"] == 120


def test_pages_survive_a_page_break(tmp_path: Path) -> None:
    _, report = run(tmp_path, fx.CROSS_PAGE)

    assert report["extraction"]["pages"] == 2
    crossing = [
        chunk for chunk in report["chunks"] if chunk["page_start"] == 1 and chunk["page_end"] == 2
    ]
    assert crossing


def test_a_split_table_is_reported_as_such(tmp_path: Path) -> None:
    _, report = run(tmp_path, fx.LONG_TABLE_WITH_HEADER)

    tables = [chunk for chunk in report["chunks"] if chunk["kind"] == "table"]

    assert len(tables) > 1
    assert all("table_split" in chunk["warnings"] for chunk in tables)


# ---------------------------------------------------------------------
# Comprobaciones que no se ven mirando el resultado una vez
# ---------------------------------------------------------------------


def test_the_report_proves_the_run_is_deterministic(tmp_path: Path) -> None:
    _, report = run(tmp_path, fx.MANUAL_V1)

    determinism = report["determinism"]

    assert determinism["identical"] is True
    assert determinism["identical_chunk_hashes"] is True


def test_two_runs_produce_the_same_report(tmp_path: Path) -> None:
    """Si dos ejecuciones difirieran, el chunking dependería de algo que no
    está en el documento."""
    first = run(tmp_path / "a", fx.MANUAL_V1)
    second = run(tmp_path / "b", fx.MANUAL_V1)

    assert first[1]["structure_sha256"] == second[1]["structure_sha256"]
    assert first[1]["chunks"] == second[1]["chunks"]
    assert first[1]["sections"] == second[1]["sections"]


def test_the_report_proves_every_chunk_reaches_its_source(tmp_path: Path) -> None:
    _, report = run(tmp_path, fx.MANUAL_V1)

    provenance = report["provenance"]

    assert provenance["chunks"] > 0
    assert provenance["with_complete_provenance"] == provenance["chunks"]
    assert provenance["pointing_back_at_the_source"] == provenance["chunks"]
    assert provenance["sample_citations"]


def test_the_report_states_the_scope_that_must_be_authorised(tmp_path: Path) -> None:
    code, report = run(tmp_path, fx.MANUAL_V1, "--asset-code", "equipo-ejemplo")

    assert code == 0
    assert report["authorization"]["required_scope"] == {
        "domain": "mantenimiento",
        "equipment": "equipo-ejemplo",
    }
    assert report["authorization"]["readable_without_permission"] == []
    assert report["authorization"]["readable_with_permission"] == ["mantenimiento/equipo-ejemplo"]


# ---------------------------------------------------------------------
# Versión 1 contra versión 2
# ---------------------------------------------------------------------


def test_the_second_version_reports_what_changed(tmp_path: Path) -> None:
    code, report = run(tmp_path, fx.MANUAL_V1, second=fx.MANUAL_V2)

    second = report["second_version"]

    assert code == 0
    assert second["ingested"] is True
    assert second["version_number"] == 2
    assert second["changes"]["unchanged"] > 0
    assert second["changes"]["modified"] > 0


def test_the_second_version_does_not_replace_the_published_one(tmp_path: Path) -> None:
    _, report = run(tmp_path, fx.MANUAL_V1, second=fx.MANUAL_V2)

    assert report["lifecycle"]["version_number"] == 1
    assert report["second_version"]["state"] == "pending_validation"
    assert report["second_version"]["published_version_after_ingest"] == 1


def test_an_identical_second_version_is_reported_as_a_duplicate(tmp_path: Path) -> None:
    """Reingerir el mismo archivo no crea una versión, y una prueba que
    pretendía comparar dos versiones distintas no puede pasar por ello."""
    code, report = run(tmp_path, fx.MANUAL_V1, second=fx.MANUAL_V1)

    assert code == 1
    assert report["second_version"]["duplicate"] is True


# ---------------------------------------------------------------------
# El reporte no filtra el documento
# ---------------------------------------------------------------------


def test_the_report_carries_no_document_text_by_default(tmp_path: Path) -> None:
    """Un reporte de un manual interno filtrado por accidente no puede
    revelar el manual."""
    _, report = run(tmp_path, fx.MANUAL_V1)

    assert report["includes_document_text"] is False
    assert all("content" not in chunk for chunk in report["chunks"])
    body = json.dumps(report, ensure_ascii=False)
    assert "bloquear y etiquetar" not in body
    assert "0,05 mm" not in body


def test_including_the_text_is_explicit_and_declared(tmp_path: Path) -> None:
    _, report = run(tmp_path, fx.MANUAL_V1, "--include-text")

    assert report["includes_document_text"] is True
    assert all("content" in chunk for chunk in report["chunks"])
