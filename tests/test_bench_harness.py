"""Recuperadores, adaptadores, informe y aislamiento del banco.

El banco tiene que ser ejecutable y reproducible **sin red y sin GPU**: es la
única forma de que corra en CI y de que dos personas obtengan el mismo
informe. Eso es lo que se comprueba aquí.
"""

import importlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from unittest import mock

import pytest

from elsa.bench import runner
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
from elsa.bench.retrievers import (
    DenseRetriever,
    LexicalRetriever,
    TrigramRetriever,
    fuse_rankings,
)
from elsa.bench.runner import run_dense, run_fusion, run_retriever
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

    # Y lo que se embebe como pasaje es el texto **compuesto**, no el
    # contenido en crudo: es lo que produccion va a embeber.
    assert seen["documents"] == [chunk.embedded_text for chunk in corpus.chunks]
    assert seen["queries"] == [query.text for query in golden.queries]
    assert all(" › " in text for text in seen["documents"])


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
    """Regla del bloque: los embeddings no se integran al flujo real todavía.

    Se resuelven las importaciones con `ast`, absolutas y relativas: buscar la
    subcadena `elsa.bench` dejaría pasar un `from ..bench.ports import ...`
    desde `services/`, que es exactamente el import que no debe existir.

    La exclusión es la herramienta del banco y nada más. `src/elsa/tools/`
    completo seria demasiado ancho: un modulo futuro colocado ahi podria
    importar el banco sin que salte nada.
    """
    import ast

    root = Path(__file__).resolve().parent.parent / "src" / "elsa"
    allowed = {Path("bench"), Path("tools/embedding_benchmark.py")}
    offenders: list[str] = []

    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if any(relative == item or item in relative.parents for item in allowed):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.startswith("elsa.bench") for alias in node.names):
                    offenders.append(f"{relative}: import {node.names[0].name}")
            elif isinstance(node, ast.ImportFrom):
                absolute = (node.module or "").startswith("elsa.bench")
                # Un import relativo desde `elsa/x/y.py` con level=2 sube a
                # `elsa`, asi que `from ..bench import ...` apunta al banco.
                relative_to_bench = node.level > 0 and (node.module or "").split(".")[0] == "bench"
                if absolute or relative_to_bench:
                    offenders.append(f"{relative}: from {'.' * node.level}{node.module}")

    assert offenders == [], f"el runtime importa el banco: {offenders}"


def test_importing_the_application_does_not_pull_in_the_benchmark() -> None:
    """Ni siquiera de forma transitiva: se comprueba sobre `sys.modules`."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import elsa.main, sys; print([m for m in sys.modules if m.startswith('elsa.bench')])",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == "[]", result.stdout


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


# ---------------------------------------------------------------------------
# Portabilidad: el banco tiene que arrancar donde no existe `resource`.
#
# `resource` es POSIX. En Windows no existe, y un `import` incondicional hacía
# fallar incluso `--help`, antes de ejecutar nada.
# ---------------------------------------------------------------------------


def test_peak_memory_is_measured_where_the_posix_api_exists() -> None:
    """En Linux se sigue midiendo, exactamente como antes."""
    assert runner.resource is not None
    measured = runner._peak_rss_mb()

    assert isinstance(measured, float) and measured > 0


def test_peak_memory_is_reported_as_unavailable_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin `resource` y sin la API de Windows, el dato falta; no revienta."""
    monkeypatch.setattr(runner, "resource", None)
    monkeypatch.setattr(runner, "_windows_peak_rss_mb", lambda: None)

    assert runner._peak_rss_mb() is None


def test_a_run_without_memory_measurement_still_produces_its_report(
    corpus: BenchCorpus, golden: GoldenSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Lo que decide el ganador no depende de poder medir la memoria.

    `peak_rss_mb` es dato de máquina y queda fuera de `identity()`, así que una
    corrida sin esa medición sigue siendo comparable con una que sí la tiene.
    """
    monkeypatch.setattr(runner, "resource", None)
    monkeypatch.setattr(runner, "_windows_peak_rss_mb", lambda: None)
    run = run_dense(HashingEmbedder(), corpus, golden)

    assert run.metadata.peak_rss_mb is None
    assert run.scoreboard.primary.queries > 0
    assert "peak_rss_mb" not in run.metadata.identity()
    assert "—" in render_markdown([run])


def test_the_benchmark_imports_where_resource_does_not_exist() -> None:
    """Simula Windows: `import resource` falla y el módulo debe cargar igual.

    Es lo que hacía fallar `--help` en Windows, así que se comprueba el módulo
    de la herramienta, que es el punto de entrada real.
    """
    blocked = dict.fromkeys(
        [name for name in sys.modules if name.startswith(("elsa.bench", "elsa.tools"))]
    )
    with mock.patch.dict(sys.modules, {**blocked, "resource": None}):
        for name in list(blocked):
            sys.modules.pop(name, None)
        module = importlib.import_module("elsa.tools.embedding_benchmark")

        assert module.main is not None
        assert importlib.import_module("elsa.bench.runner").resource is None


# ---------------------------------------------------------------------------
# Fusión RRF en el banco: el mismo método y la misma constante que producción,
# sobre rankings ya calculados.
# ---------------------------------------------------------------------------


def test_fusion_reuses_rankings_instead_of_running_the_retrievers_again(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """Fusionar no puede costar otra pasada de inferencia.

    `fuse_rankings` recibe posiciones ya calculadas. Si fusionar reejecutara
    los canales, medir el híbrido con un modelo real costaría el doble y
    podría dar otro resultado.
    """
    lexical = run_retriever(LexicalRetriever(), corpus, golden)
    dense = run_dense(HashingEmbedder(), corpus, golden)

    fused = fuse_rankings([lexical.results, dense.results], golden, k=60)

    assert set(fused) == set(lexical.results)
    # Cada canal aporta 1/(k+posición); un chunk que ambos ponen primero suma
    # 2/61. Se comprueba la fórmula, no un número copiado.
    common = next(
        (
            q
            for q in golden.queries
            if lexical.results[q.id].ranked[:1] == dense.results[q.id].ranked[:1]
            and lexical.results[q.id].ranked
        ),
        None,
    )
    if common is not None:
        assert fused[common.id].scores[0] == pytest.approx(2 / 61, abs=1e-9)


def test_a_fused_run_keeps_the_corpus_golden_and_template_fingerprints(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """Una corrida fusionada tiene que ser comparable con sus canales."""
    lexical = run_retriever(LexicalRetriever(), corpus, golden)
    dense = run_dense(HashingEmbedder(), corpus, golden)

    fused = run_fusion([lexical, dense], golden, corpus)

    assert fused.metadata.corpus_fingerprint == corpus.fingerprint
    assert fused.metadata.golden_fingerprint == golden.fingerprint
    assert fused.metadata.composition_template == lexical.metadata.composition_template
    assert "fusion-rrf(" in fused.metadata.retriever
    # El nombre compone desde `model_name`, que es lo que el informe muestra.
    assert lexical.metadata.model_name in fused.metadata.retriever
    assert dense.metadata.model_name in fused.metadata.retriever
    assert "k=60" in fused.metadata.retriever
    assert fused.scoreboard.primary.queries == lexical.scoreboard.primary.queries
    # La fusión no carga ni embebe nada: no inventa tiempos de coste.
    assert fused.metadata.load_seconds is None
    assert fused.metadata.corpus_embed_seconds is None


def test_fusion_needs_at_least_two_runs(corpus: BenchCorpus, golden: GoldenSet) -> None:
    lexical = run_retriever(LexicalRetriever(), corpus, golden)

    with pytest.raises(ValueError, match="at least two"):
        run_fusion([lexical], golden, corpus)


def test_the_cli_reports_each_channel_separately_and_then_the_fusion(
    tmp_path: Path,
) -> None:
    """`--fusion` añade la corrida fusionada **sin** ocultar sus componentes.

    Un número fusionado sin sus canales al lado no se puede leer: no se sabría
    si la fusión ayudó o estorbó.
    """
    assert main(["--fusion", "--out", str(tmp_path)]) == 0

    report = json.loads((tmp_path / "informe.json").read_text(encoding="utf-8"))
    names = [run["metadata"]["retriever"] for run in report["runs"]]

    assert "lexical-bm25" in names
    assert any(n.startswith("dense:") for n in names)
    fused = [n for n in names if n.startswith("fusion-rrf(")]
    assert len(fused) == 1
    # El nombre dice qué se fusionó, para que el informe se lea solo.
    assert "lexical-bm25" in fused[0]
    # Y va después de sus componentes.
    assert names.index(fused[0]) > names.index("lexical-bm25")

    identities = {
        (
            run["metadata"]["corpus_fingerprint"],
            run["metadata"]["golden_fingerprint"],
            run["metadata"]["composition_template"],
        )
        for run in report["runs"]
    }
    assert len(identities) == 1
    assert {run["scoreboard"]["primary"]["queries"] for run in report["runs"]} == {59}


def test_the_cli_refuses_to_fuse_without_the_lexical_baseline(tmp_path: Path) -> None:
    """RRF(BM25 + denso) sin BM25 no es lo que el informe diría que es."""
    assert main(["--fusion", "--skip-baselines", "--out", str(tmp_path)]) == 2


# ---------------------------------------------------------------------------
# Observabilidad del informe: sin rankings persistidos, un promedio no dice
# qué consulta se degradó, y una fusión no se puede auditar sin reejecutar.
# ---------------------------------------------------------------------------


def test_rankings_survive_serialisation_keeping_order_and_scores(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    run = run_retriever(LexicalRetriever(), corpus, golden)
    restored = json.loads(json.dumps(run.as_dict()))

    by_query = {entry["query_id"]: entry for entry in restored["rankings"]}
    assert set(by_query) == set(run.results)
    for query_id, result in run.results.items():
        ranked = by_query[query_id]["ranked"]
        # El orden es el del recuperador, no el de un diccionario.
        assert [row["chunk_id"] for row in ranked] == list(result.ranked)
        assert [row["rank"] for row in ranked] == list(range(1, len(result.ranked) + 1))
        for position, row in enumerate(ranked):
            if position < len(result.scores):
                assert row["score"] == pytest.approx(result.scores[position], abs=1e-6)


def test_the_golden_set_is_written_once_and_carries_what_each_query_expects(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """El texto y lo esperado viven una vez; los rankings solo cruzan por id."""
    run = run_retriever(LexicalRetriever(), corpus, golden)
    report = json.loads(render_json([run], golden=golden))

    assert len(report["golden"]["queries"]) == len(golden.queries)
    entry = report["golden"]["queries"][0]
    assert {"id", "text", "axis", "must_retrieve", "must_not_retrieve"} <= set(entry)
    assert report["golden"]["fingerprint"] == golden.fingerprint
    # No se repite por corrida: el ranking solo lleva identificadores.
    assert set(report["runs"][0]["rankings"][0]) == {"query_id", "ranked"}


def test_two_fusions_have_different_auditable_identities(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """Sin esto, ambas aparecían como `fusion-rrf(k=60)` y no se distinguían."""
    lexical = run_retriever(LexicalRetriever(), corpus, golden)
    trigram = run_retriever(TrigramRetriever(), corpus, golden)
    dense = run_dense(HashingEmbedder(), corpus, golden)

    first = run_fusion([lexical, dense], golden, corpus)
    second = run_fusion([trigram, dense], golden, corpus)

    assert first.metadata.model_name != second.metadata.model_name
    assert first.metadata.model_name == (
        f"fusion-rrf({lexical.metadata.model_name}+{dense.metadata.model_name},k=60)"
    )
    # El nombre auditable es el que sale en el Markdown, no solo en el JSON.
    markdown = render_markdown([first, second])
    assert first.metadata.model_name in markdown
    assert second.metadata.model_name in markdown


def test_a_fusion_reports_abstention_as_not_calibrated_never_as_a_number(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """El umbral 0,35 no significa nada sobre una suma de recíprocos."""
    lexical = run_retriever(LexicalRetriever(), corpus, golden)
    dense = run_dense(HashingEmbedder(), corpus, golden)
    fused = run_fusion([lexical, dense], golden, corpus)

    assert fused.scoreboard.abstention_rate is None
    assert any("NOT calibrated" in note for note in fused.scoreboard.notes)
    assert json.loads(json.dumps(fused.as_dict()))["scoreboard"]["abstention"]["rate"] is None
    assert "N/A — no calibrada" in render_markdown([fused])
    # Y el comportamiento de siempre se conserva donde el umbral sí aplica.
    assert dense.scoreboard.abstention_rate is not None


def test_aggregate_metrics_and_fingerprints_are_unchanged_by_the_new_fields(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """Añadir observabilidad no puede mover una sola métrica."""
    run = run_retriever(LexicalRetriever(), corpus, golden)
    versioned = json.loads(Path("bench/resultados/informe.json").read_text(encoding="utf-8"))
    stored = next(
        r for r in versioned["runs"] if r["metadata"]["retriever"] == run.metadata.retriever
    )

    assert run.scoreboard.as_dict() == stored["scoreboard"]
    assert run.metadata.corpus_fingerprint == stored["metadata"]["corpus_fingerprint"]
    assert run.metadata.golden_fingerprint == stored["metadata"]["golden_fingerprint"]
    assert run.metadata.composition_template == stored["metadata"]["composition_template"]


def test_a_saved_report_is_enough_to_compare_channels_query_by_query(
    tmp_path: Path,
) -> None:
    """La prueba de fuego: reconstruir la comparación leyendo solo el archivo.

    Si esto pasa, auditar una fusión ya no exige volver a ejecutar el modelo.
    """
    assert main(["--fusion", "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "informe.json").read_text(encoding="utf-8"))

    expected = {q["id"]: set(q["must_retrieve"]) for q in report["golden"]["queries"]}
    rankings = {
        run["metadata"]["model_name"]: {
            entry["query_id"]: [row["chunk_id"] for row in entry["ranked"]]
            for entry in run["rankings"]
        }
        for run in report["runs"]
    }
    lexical = rankings["lexical-bm25"]
    fusion = next(name for name in rankings if name.startswith("fusion-rrf("))

    # Se reconstruye, solo con el archivo, dónde quedó lo esperado en cada canal.
    compared = 0
    for query_id, wanted in expected.items():
        if not wanted:
            continue
        for name in (("lexical-bm25"), fusion):
            ranked = rankings[name][query_id]
            position = next((i for i, c in enumerate(ranked, 1) if c in wanted), None)
            assert position is None or position >= 1
        compared += 1
    assert compared > 0
    assert set(lexical) == set(rankings[fusion])
    assert (
        (tmp_path / "diagnostico.md")
        .read_text(encoding="utf-8")
        .startswith("# Diagnóstico por consulta")
    )
