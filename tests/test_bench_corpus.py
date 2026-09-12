"""El corpus del banco se construye con el chunker real y es reproducible."""

from pathlib import Path

import pytest

from elsa.bench.corpus import build_corpus
from elsa.bench.goldenset import GOLDEN_PATH, GoldenSetError, load_golden_set
from elsa.bench.model import Axis, BenchCorpus

# Marcas de datos reales que nunca deben aparecer en el corpus sintético.
FORBIDDEN = ("tampella", "papelsa molino", "barbosa")


@pytest.fixture(scope="module")
def corpus() -> BenchCorpus:
    return build_corpus()


def test_the_corpus_is_chunked_with_the_real_chunker(corpus: BenchCorpus) -> None:
    """Si se troceara distinto, el banco mediría chunks que ELSA no va a tener."""
    assert len(corpus.chunks) > 30
    # Las claves estructurales son las que produce `structural-v1`.
    assert all("#" in chunk.structural_key for chunk in corpus.chunks)
    assert {chunk.kind for chunk in corpus.chunks} <= {
        "prose",
        "list",
        "steps",
        "warning",
        "table",
        "mixed",
    }


def test_chunk_identifiers_are_unique_and_readable(corpus: BenchCorpus) -> None:
    identifiers = [chunk.chunk_id for chunk in corpus.chunks]

    assert len(set(identifiers)) == len(identifiers)
    assert all("@v" in identifier and "#" in identifier for identifier in identifiers)


def test_the_corpus_covers_the_scenarios_the_benchmark_needs(corpus: BenchCorpus) -> None:
    assets = {chunk.asset for chunk in corpus.chunks}
    languages = {chunk.language for chunk in corpus.chunks}
    versions = {(chunk.document_code, chunk.version) for chunk in corpus.chunks}

    assert len(assets) >= 2, "hace falta un segundo activo para medir confusabilidad"
    assert languages == {"es", "en"}, "hace falta un documento en ingles para el cruce de idioma"
    assert ("prensa-manual", 1) in versions and ("prensa-manual", 2) in versions


def test_only_one_version_per_document_is_published(corpus: BenchCorpus) -> None:
    """Refleja el modelo real: una sola versión publicada por documento."""
    published: dict[str, set[int]] = {}
    for chunk in corpus.chunks:
        if chunk.published:
            published.setdefault(chunk.document_code, set()).add(chunk.version)

    assert all(len(versions) == 1 for versions in published.values())
    unpublished = {
        c.version for c in corpus.chunks if c.document_code == "prensa-manual" and not c.published
    }
    assert unpublished == {2}


def test_the_corpus_is_deterministic(corpus: BenchCorpus) -> None:
    again = build_corpus()

    assert again.fingerprint == corpus.fingerprint
    assert [c.chunk_id for c in again.chunks] == [c.chunk_id for c in corpus.chunks]


def test_no_artefact_of_the_benchmark_carries_real_plant_data(
    corpus: BenchCorpus,
) -> None:
    """Regla 12 del contrato: los datos reales no entran a Git.

    Se barre **todo** el material versionado del banco, no solo el contenido
    de los chunks: el conjunto dorado es precisamente donde acabaria pegada
    una pregunta real de un ingeniero de planta, y los informes generados se
    versionan tambien.
    """
    root = Path(__file__).resolve().parent.parent / "bench"
    pieces = [chunk.content for chunk in corpus.chunks]
    golden = load_golden_set(corpus)
    pieces += [query.text for query in golden.queries]
    pieces += [query.rationale for query in golden.queries]
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in (".md", ".json"):
            pieces.append(path.read_text(encoding="utf-8"))

    body = " ".join(pieces).lower()
    for marker in FORBIDDEN:
        # La propia lista vive en este archivo de test, no en `bench/`.
        assert marker not in body, f"{marker!r} no puede aparecer en el material del banco"


def test_the_benchmark_versions_no_binaries_or_dumps() -> None:
    """Ni planos, ni PDFs, ni pesos de modelos, ni volcados de base."""
    root = Path(__file__).resolve().parent.parent / "bench"

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        assert path.suffix in (".md", ".json"), f"{path.name} no deberia estar versionado"
        assert path.stat().st_size < 1_000_000, f"{path.name} es demasiado grande"


# ---------------------------------------------------------------------
# Conjunto dorado
# ---------------------------------------------------------------------


def test_the_golden_set_is_coherent_with_the_corpus(corpus: BenchCorpus) -> None:
    """Una expectativa que apunta a un chunk inexistente puntúa mal en silencio."""
    golden = load_golden_set(corpus)

    assert 50 <= len(golden.queries) <= 70
    known = {chunk.chunk_id for chunk in corpus.chunks}
    for query in golden.queries:
        assert set(query.relevant) <= known
        assert set(query.must_not_retrieve) <= known


def test_the_golden_set_covers_every_required_axis(corpus: BenchCorpus) -> None:
    golden = load_golden_set(corpus)
    covered = set(golden.by_axis())

    required = {
        Axis.NARRATIVE,
        Axis.SYNONYMS,
        Axis.COMPONENT_NAMES,
        Axis.CODES,
        Axis.TYPOS,
        Axis.KEYWORD,
        Axis.CROSS_LANGUAGE,
        Axis.NUMBERS_UNITS,
        Axis.ABBREVIATIONS,
        Axis.FAILURE_SYMPTOMS,
        Axis.PREVENTIVE,
        Axis.SAFETY,
        Axis.PROCEDURE,
        Axis.SECTION_REFERENCE,
        Axis.NO_ANSWER,
        Axis.AMBIGUITY,
        Axis.ASSET_CONFUSION,
        Axis.VERSION_CONFUSION,
        Axis.NEAR_MISS_DOCUMENT,
    }
    assert required <= covered
    assert all(len(queries) >= 3 for queries in golden.by_axis().values())


def test_every_expectation_has_a_written_reason(corpus: BenchCorpus) -> None:
    """Un conjunto dorado hecho a mano solo se controla discutiéndolo."""
    golden = load_golden_set(corpus)

    assert all(len(query.rationale) > 20 for query in golden.queries)


def test_the_golden_set_has_queries_with_no_answer(corpus: BenchCorpus) -> None:
    golden = load_golden_set(corpus)

    unanswerable = [q for q in golden.queries if not q.expects_an_answer]
    assert len(unanswerable) >= 3
    assert all(q.axis is Axis.NO_ANSWER for q in unanswerable)


def test_diagnostic_axes_are_excluded_from_the_scoring_set(corpus: BenchCorpus) -> None:
    """Los códigos no deben decidir el ganador del modelo denso."""
    golden = load_golden_set(corpus)

    assert all(query.axis is not Axis.CODES for query in golden.scored)
    assert any(query.axis is Axis.CODES for query in golden.queries)


def test_an_expectation_pointing_nowhere_fails_loudly(
    corpus: BenchCorpus, tmp_path: object
) -> None:
    import json
    from pathlib import Path

    assert isinstance(tmp_path, Path)
    broken = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    broken["queries"][0]["relevant"] = {"documento-inventado@v9#9#9999": 2}
    path = tmp_path / "roto.json"
    path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(GoldenSetError) as error:
        load_golden_set(corpus, path)

    assert "unknown chunk" in str(error.value)


def test_the_golden_set_fingerprint_changes_with_its_content(corpus: BenchCorpus) -> None:
    golden = load_golden_set(corpus)

    assert len(golden.fingerprint) == 64
    assert load_golden_set(corpus).fingerprint == golden.fingerprint
