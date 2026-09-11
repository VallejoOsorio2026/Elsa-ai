"""Recuperadores, adaptadores, informe y aislamiento del banco.

El banco tiene que ser ejecutable y reproducible **sin red y sin GPU**: es la
única forma de que corra en CI y de que dos personas obtengan el mismo
informe. Eso es lo que se comprueba aquí.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path

import pytest

from elsa.bench.adapters.hashing import HashingEmbedder
from elsa.bench.adapters.sentence_transformers import (
    CANDIDATES,
    CandidateSpec,
    SentenceTransformerEmbedder,
)
from elsa.bench.corpus import build_corpus
from elsa.bench.goldenset import load_golden_set
from elsa.bench.model import BenchCorpus, GoldenSet
from elsa.bench.ports import BenchmarkEmbedder, ModelUnavailableError
from elsa.bench.report import comparison_fingerprint, render_json, render_markdown
from elsa.bench.retrievers import DenseRetriever, LexicalRetriever, TrigramRetriever
from elsa.bench.runner import run_dense, run_retriever
from elsa.tools.embedding_benchmark import main


@pytest.fixture(scope="module")
def corpus() -> BenchCorpus:
    return build_corpus()


@pytest.fixture(scope="module")
def golden(corpus: BenchCorpus) -> GoldenSet:
    return load_golden_set(corpus)


# ---------------------------------------------------------------------
# Adaptadores
# ---------------------------------------------------------------------


def test_the_control_satisfies_the_benchmark_interface() -> None:
    assert isinstance(HashingEmbedder(), BenchmarkEmbedder)


def test_the_control_is_deterministic() -> None:
    """Sin esto, dos corridas del banco darían métricas distintas."""
    first = HashingEmbedder().embed_documents(["par de apriete de la tapa"])
    second = HashingEmbedder().embed_documents(["par de apriete de la tapa"])

    assert first == second


def test_the_control_declares_that_it_is_not_a_model() -> None:
    description = HashingEmbedder().describe()

    assert "control" in description.model_name
    assert description.runtime == "pure-python"


def test_every_required_candidate_is_declared() -> None:
    keys = {spec.key for spec in CANDIDATES}

    assert keys == {"bge-m3", "qwen3-0.6b", "embeddinggemma-300m"}


def test_each_candidate_declares_its_own_document_and_query_prefixes() -> None:
    """Medir los tres con el mismo trato favorecería al que no usa prefijos."""
    by_key = {spec.key: spec for spec in CANDIDATES}

    assert by_key["bge-m3"].document_prefix == ""
    assert by_key["bge-m3"].query_prefix == ""
    assert by_key["embeddinggemma-300m"].document_prefix.startswith("title:")
    assert by_key["embeddinggemma-300m"].query_prefix.startswith("task:")
    # Qwen3 es instruction-aware: instruccion en la consulta, pasaje en crudo.
    assert by_key["qwen3-0.6b"].document_prefix == ""
    assert "Instruct:" in by_key["qwen3-0.6b"].query_prefix


def test_embeddinggemma_is_measurable_but_not_production_eligible() -> None:
    """Medir no habilita: la licencia sigue pendiente de validación (D1)."""
    by_key = {spec.key: spec for spec in CANDIDATES}

    assert by_key["embeddinggemma-300m"].production_eligible is False
    assert by_key["bge-m3"].production_eligible is True
    assert by_key["qwen3-0.6b"].production_eligible is True


def test_a_missing_dependency_leaves_the_candidate_unmeasured() -> None:
    """Sin medir no se descarta ni se elige; y no se sustituye por MTEB."""
    spec = CandidateSpec(
        key="inexistente",
        model_name="no/existe",
        revision="main",
        expected_dimension=8,
        document_prefix="",
        query_prefix="",
        normalize=True,
        license_name="-",
        production_eligible=False,
    )

    with pytest.raises(ModelUnavailableError):
        SentenceTransformerEmbedder(spec)


# ---------------------------------------------------------------------
# Recuperadores
# ---------------------------------------------------------------------


def test_the_baselines_answer_every_query(corpus: BenchCorpus, golden: GoldenSet) -> None:
    for retriever in (LexicalRetriever(), TrigramRetriever()):
        results = retriever.run(corpus, golden)

        assert set(results) == {query.id for query in golden.queries}
        assert all(result.query_id for result in results.values())


def test_ranking_ties_break_deterministically(corpus: BenchCorpus, golden: GoldenSet) -> None:
    """Sin desempate estable, dos corridas darían métricas distintas."""
    first = LexicalRetriever().run(corpus, golden)
    second = LexicalRetriever().run(corpus, golden)

    assert {k: v.ranked for k, v in first.items()} == {k: v.ranked for k, v in second.items()}


def test_the_dense_retriever_never_embeds_a_passage_as_a_query(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """Es el error que mediría mal a dos de los tres candidatos."""
    seen: dict[str, list[str]] = {"documents": [], "queries": []}

    class Spy(HashingEmbedder):
        def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
            seen["documents"].extend(texts)
            return super().embed_documents(texts)

        def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
            seen["queries"].extend(texts)
            return super().embed_queries(texts)

    DenseRetriever(Spy()).run(corpus, golden)

    assert seen["documents"] == [chunk.content for chunk in corpus.chunks]
    assert seen["queries"] == [query.text for query in golden.queries]


def test_the_lexical_baseline_beats_the_control_on_codes(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """Cordura del arnés: una busqueda por palabras tiene que ganar en códigos."""
    lexical = run_retriever(LexicalRetriever(), corpus, golden)
    control = run_dense(HashingEmbedder(), corpus, golden)

    lexical_codes = next(s for s in lexical.scoreboard.diagnostic if s.label == "codes")
    control_codes = next(s for s in control.scoreboard.diagnostic if s.label == "codes")
    assert lexical_codes.recall[5] >= control_codes.recall[5]


# ---------------------------------------------------------------------
# Corridas y metadatos
# ---------------------------------------------------------------------


def test_a_run_records_what_produced_it(corpus: BenchCorpus, golden: GoldenSet) -> None:
    """Un número sin modelo, revisión, dimensión y prefijos no es un resultado."""
    run = run_dense(HashingEmbedder(), corpus, golden)

    meta = run.metadata
    assert meta.model_name and meta.revision and meta.dimension
    assert meta.runtime == "pure-python"
    assert meta.corpus_fingerprint == corpus.fingerprint
    assert meta.golden_fingerprint == golden.fingerprint
    assert meta.corpus_embed_seconds is not None
    assert meta.query_latency_p50_ms is not None
    assert meta.query_latency_p95_ms is not None
    assert meta.peak_rss_mb is not None
    assert meta.cpu


def test_the_run_identity_excludes_the_machine(corpus: BenchCorpus, golden: GoldenSet) -> None:
    """Lo que depende del hardware no puede entrar en una comparación."""
    identity = run_dense(HashingEmbedder(), corpus, golden).metadata.identity()

    assert "corpus_fingerprint" in identity
    for machine_field in ("cpu", "ram_gb", "peak_rss_mb", "started_at", "gpu"):
        assert machine_field not in identity


# ---------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------


def test_two_identical_runs_produce_the_same_comparison(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """La **parte comparable** es identica; la de coste depende de la maquina.

    El informe mezcla las dos a proposito —quien lo lee quiere ver calidad y
    coste juntos— pero solo la de calidad entra en la huella. Afirmar que el
    Markdown entero es identico byte a byte seria falso: los tiempos varian
    entre corridas, y un test que lo exigiera pasaria por casualidad.
    """
    first = [run_retriever(LexicalRetriever(), corpus, golden)]
    second = [run_retriever(LexicalRetriever(), corpus, golden)]

    assert comparison_fingerprint(first) == comparison_fingerprint(second)
    # Todo lo anterior a la seccion de coste tiene que coincidir exactamente.
    quality = render_markdown(first).split("## 5. Coste y hardware")[0]
    assert quality == render_markdown(second).split("## 5. Coste y hardware")[0]
    assert first[0].scoreboard.as_dict() == second[0].scoreboard.as_dict()


def test_the_report_names_the_unmeasured_candidates(corpus: BenchCorpus, golden: GoldenSet) -> None:
    runs = [run_retriever(LexicalRetriever(), corpus, golden)]
    unmeasured = [{"model": "BAAI/bge-m3", "reason": "huggingface.co bloqueado"}]

    markdown = render_markdown(runs, unmeasured=unmeasured)
    payload = json.loads(render_json(runs, unmeasured=unmeasured))

    assert "SIN MEDIR" in markdown
    assert "BAAI/bge-m3" in markdown
    assert "no se descarta ni se elige" in markdown
    assert payload["unmeasured_candidates"] == unmeasured


def test_the_report_states_that_codes_do_not_decide(corpus: BenchCorpus, golden: GoldenSet) -> None:
    markdown = render_markdown([run_retriever(LexicalRetriever(), corpus, golden)])

    assert "no** entran en la puntuación principal" in markdown
    assert "confusabilidad" in markdown
    assert "nunca autorización" in markdown


# ---------------------------------------------------------------------
# El banco no entra al camino productivo
# ---------------------------------------------------------------------


def test_the_productive_code_does_not_import_the_benchmark() -> None:
    """Regla del bloque: los embeddings no se integran al flujo real todavía."""
    root = Path(__file__).resolve().parent.parent / "src" / "elsa"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        relative = path.relative_to(root)
        if relative.parts[0] in ("bench", "tools"):
            continue
        if "elsa.bench" in path.read_text(encoding="utf-8"):
            offenders.append(str(relative))

    assert offenders == [], f"el runtime importa el banco: {offenders}"


def test_the_benchmark_needs_neither_postgres_nor_pgvector() -> None:
    """4.2.a mide; no persiste. Sin base de datos y sin columna vectorial.

    Se inspecciona el **código**, no la prosa: este mismo paquete explica en
    sus docstrings que no toca pgvector, y una busqueda de subcadenas daría
    un falso positivo con su propia documentación. Los módulos se parsean y
    se miran las importaciones y las cadenas literales.
    """
    import ast

    root = Path(__file__).resolve().parent.parent / "src" / "elsa" / "bench"
    forbidden_modules = {"asyncpg", "psycopg", "psycopg2", "pgvector", "sqlalchemy"}
    sql = re.compile(
        r"\b(insert\s+into|create\s+table|create\s+extension|select\s+.*\sfrom)\b", re.I
    )
    vector_type = re.compile(r"\bvector\(\s*\d+\s*\)")

    imports: set[str] = set()
    literals: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.append(node.value)

    assert not imports & forbidden_modules, f"el banco importa {imports & forbidden_modules}"
    # Las docstrings son literales tambien, asi que se excluyen las de modulo
    # y funcion mirando solo cadenas cortas, que es donde viviria un SQL real.
    code_strings = [value for value in literals if len(value) < 400]
    offenders = [value for value in code_strings if sql.search(value) or vector_type.search(value)]
    assert offenders == [], f"el banco contiene SQL o tipos vectoriales: {offenders}"


def test_the_cli_runs_without_network_or_models(tmp_path: Path) -> None:
    """Si el banco no corre sin red, no corre en CI y no lo ejecuta nadie."""
    code = main(["--out", str(tmp_path / "salida")])

    assert code == 0
    payload = json.loads((tmp_path / "salida" / "informe.json").read_text(encoding="utf-8"))
    assert len(payload["runs"]) == 3
    assert {item["model"] for item in payload["unmeasured_candidates"]} == {
        spec.model_name for spec in CANDIDATES
    }
    assert (tmp_path / "salida" / "informe.md").read_text(encoding="utf-8")


def test_the_cli_is_reproducible(tmp_path: Path) -> None:
    main(["--out", str(tmp_path / "a")])
    main(["--out", str(tmp_path / "b")])

    first = json.loads((tmp_path / "a" / "informe.json").read_text(encoding="utf-8"))
    second = json.loads((tmp_path / "b" / "informe.json").read_text(encoding="utf-8"))

    assert first["comparison_fingerprint"] == second["comparison_fingerprint"]


def test_an_unknown_candidate_is_refused(tmp_path: Path) -> None:
    assert main(["--out", str(tmp_path / "x"), "--candidates", "no-existe"]) == 2
