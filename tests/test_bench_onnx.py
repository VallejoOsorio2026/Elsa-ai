"""Pruebas del banco experimental de ONNX. **Sin cargar BGE-M3 real.**

Ninguna prueba descarga pesos, abre una sesión de ONNX Runtime ni necesita
numpy: el adaptador está partido para que la sesión sea la única pieza que
conoce esas dependencias, y aquí se sustituye por una falsa. Lo que se
comprueba es justamente lo que un modelo real no comprobaría por ti —que el
pooling es el correcto, que no se asume `outputs[0]`, que un vector inservible
se rechaza— porque con el modelo real esos fallos producen números plausibles
en vez de un error.
"""

import json
import math
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest

from elsa.bench.adapters.onnx import (
    LocalTokenizer,
    OnnxEmbedder,
    OnnxGraphError,
    OnnxInputSpec,
    OnnxModelPaths,
    OnnxOutput,
    OnnxVectorError,
    TokenizedText,
)
from elsa.bench.corpus import build_corpus
from elsa.bench.goldenset import load_golden_set
from elsa.bench.model import BenchCorpus, GoldenSet
from elsa.bench.onnx_experiment import (
    CAPTURE_SCHEMA,
    PINNED_REVISION,
    Capture,
    TextRecord,
    compare,
    decode_vector,
    encode_vector,
    render_markdown,
)
from elsa.bench.ports import BenchmarkEmbedder, ModelUnavailableError

DIMENSION = 4


# ---------------------------------------------------------------------
# Dobles
# ---------------------------------------------------------------------


@dataclass
class FakeTokenizer:
    """Un identificador por palabra, más `<s>` y `</s>`. Determinista."""

    pad_id: int | None = 1
    max_length: int = 16

    def encode_one(self, text: str) -> TokenizedText:
        words = text.split()
        ids = (0, *(1000 + len(word) for word in words), 2)[: self.max_length]
        return TokenizedText(
            text_sha256=f"sha-of:{text}",
            input_ids=ids,
            attention_mask=tuple(1 for _ in ids),
            truncated=len(ids) >= self.max_length,
        )

    def describe(self) -> Mapping[str, object]:
        return {"max_length": self.max_length, "pad_id": self.pad_id, "truncation": "right"}


class FakeSession:
    """Sesión que devuelve estados por token deterministas.

    Registra lo que recibió para que las pruebas puedan afirmar qué entradas se
    alimentaron de verdad, que es donde vive la mitad de los errores posibles.
    """

    def __init__(
        self,
        *,
        inputs: Sequence[str] = ("input_ids", "attention_mask"),
        outputs: Sequence[str] = ("last_hidden_state",),
        dimension: int = DIMENSION,
        cls_vector: Sequence[float] | None = None,
        extra: Sequence[OnnxOutput] = (),
    ) -> None:
        self._inputs = tuple(inputs)
        self._outputs = tuple(outputs)
        self._dimension = dimension
        self._cls_vector = None if cls_vector is None else tuple(cls_vector)
        self._extra = tuple(extra)
        self.calls: list[dict[str, Any]] = []

    def input_specs(self) -> tuple[OnnxInputSpec, ...]:
        return tuple(OnnxInputSpec(name=name, onnx_type="tensor(int64)") for name in self._inputs)

    def output_names(self) -> tuple[str, ...]:
        return self._outputs

    def describe(self) -> Mapping[str, object]:
        return {"runtime": "fake", "runtime_version": "0", "execution_provider": "fake"}

    def run(
        self,
        feeds: Mapping[str, Sequence[Sequence[int]]],
        *,
        only: str | None = None,
    ) -> tuple[OnnxOutput, ...]:
        self.calls.append(
            {"feeds": {k: [list(r) for r in v] for k, v in feeds.items()}, "only": only}
        )
        rows = feeds["input_ids"]
        batch, width = len(rows), len(rows[0])
        flat: list[float] = []
        for index in range(batch):
            for position in range(width):
                if position == 0:
                    # El CLS lleva el valor util; el resto de posiciones llevan
                    # basura reconocible. Si el pooling no fuera CLS, o mezclara
                    # posiciones, el vector saldria con -99 dentro.
                    # El valor por defecto depende del texto y nunca es cero:
                    # un CLS de norma cero lo rechaza el adaptador, que es
                    # justo lo que otra prueba comprueba a proposito.
                    flat.extend(
                        self._cls_vector
                        if self._cls_vector is not None
                        else [float(sum(rows[index]) + 1), *([1.0] * (self._dimension - 1))]
                    )
                else:
                    flat.extend([-99.0] * self._dimension)
        states = OnnxOutput(
            name="last_hidden_state", shape=(batch, width, self._dimension), values=flat
        )
        produced = (*self._extra, states)
        if only is not None:
            return tuple(item for item in produced if item.name == only)
        return produced


def build(
    session: FakeSession,
    *,
    dimension: int = DIMENSION,
    document_prefix: str = "",
    query_prefix: str = "",
    batch_size: int = 1,
) -> OnnxEmbedder:
    return OnnxEmbedder(
        session,
        FakeTokenizer(),
        model_name="BAAI/bge-m3",
        revision=PINNED_REVISION,
        dimension=dimension,
        document_prefix=document_prefix,
        query_prefix=query_prefix,
        batch_size=batch_size,
    )


# ---------------------------------------------------------------------
# Contrato y pooling
# ---------------------------------------------------------------------


def test_the_adapter_satisfies_the_benchmark_interface() -> None:
    assert isinstance(build(FakeSession()), BenchmarkEmbedder)


def test_the_order_of_the_texts_is_preserved_across_batches() -> None:
    """El banco cruza vectores con chunks por posición: reordenar los rompe."""
    embedder = build(FakeSession(), batch_size=2)
    texts = ["a", "bb ccc", "d", "ee", "f"]

    records = embedder.encode_documents(texts)

    assert len(records) == len(texts)
    assert [record.tokenized.text_sha256 for record in records] == [
        f"sha-of:{text}" for text in texts
    ]


def test_cls_pooling_takes_the_first_position_and_not_another() -> None:
    """Las demás posiciones llevan -99: si se colaran, el vector lo diría."""
    embedder = build(FakeSession(cls_vector=(1.0, 0.0, 0.0, 0.0)))

    [record] = embedder.encode_documents(["dos palabras mas"])

    assert record.vector == pytest.approx((1.0, 0.0, 0.0, 0.0))
    assert all(value >= 0.0 for value in record.vector)


def test_the_vector_is_normalised_in_l2_and_reports_both_norms() -> None:
    embedder = build(FakeSession(cls_vector=(3.0, 4.0, 0.0, 0.0)))

    [record] = embedder.encode_documents(["uno"])

    assert record.norm_before == pytest.approx(5.0)
    assert record.norm_after == pytest.approx(1.0, abs=1e-6)
    assert record.vector == pytest.approx((0.6, 0.8, 0.0, 0.0))


def test_the_document_and_query_prefixes_are_applied_per_operation() -> None:
    session = FakeSession()
    embedder = build(session, document_prefix="DOC:", query_prefix="Q:")

    document = embedder.encode_documents(["x"])[0]
    query = embedder.encode_queries(["x"])[0]

    assert document.tokenized.text_sha256 == "sha-of:DOC:x"
    assert query.tokenized.text_sha256 == "sha-of:Q:x"


# ---------------------------------------------------------------------
# Selección de la salida
# ---------------------------------------------------------------------


def test_outputs_zero_is_never_assumed_to_be_the_right_output() -> None:
    """`pooler_output` es plausible y es de **otro** espacio vectorial."""
    pooler = OnnxOutput(name="pooler_output", shape=(1, DIMENSION), values=[7.0] * DIMENSION)
    session = FakeSession(outputs=("pooler_output", "last_hidden_state"), extra=(pooler,))
    embedder = build(session)

    [record] = embedder.encode_documents(["uno"])

    assert embedder.runtime_details()["selected_output"] == "last_hidden_state"
    assert record.vector != pytest.approx((0.5, 0.5, 0.5, 0.5))


def test_a_graph_without_per_token_states_stops_the_run() -> None:
    class OnlyPooled(FakeSession):
        def run(
            self, feeds: Mapping[str, Sequence[Sequence[int]]], *, only: str | None = None
        ) -> tuple[OnnxOutput, ...]:
            return (OnnxOutput(name="sentence_embedding", shape=(1, DIMENSION), values=[1.0] * 4),)

    with pytest.raises(OnnxGraphError, match="per-token states"):
        build(OnlyPooled()).encode_documents(["uno"])


def test_two_candidate_outputs_stop_the_run_instead_of_guessing() -> None:
    class Ambiguous(FakeSession):
        def run(
            self, feeds: Mapping[str, Sequence[Sequence[int]]], *, only: str | None = None
        ) -> tuple[OnnxOutput, ...]:
            width = len(feeds["input_ids"][0])
            values = [0.5] * (width * DIMENSION)
            return (
                OnnxOutput(name="hidden_a", shape=(1, width, DIMENSION), values=values),
                OnnxOutput(name="hidden_b", shape=(1, width, DIMENSION), values=values),
            )

    with pytest.raises(OnnxGraphError, match="several outputs"):
        build(Ambiguous()).encode_documents(["uno"])


def test_the_selected_output_and_its_reason_are_recorded() -> None:
    embedder = build(FakeSession())
    embedder.encode_documents(["uno"])

    details = embedder.runtime_details()

    assert details["selected_output"] == "last_hidden_state"
    assert "verified shape" in str(details["selected_output_reason"])
    assert details["pooling"] == "cls"
    assert details["normalization"] == "l2"
    assert details["precision"] == "fp32"


# ---------------------------------------------------------------------
# Entradas del grafo
# ---------------------------------------------------------------------


def test_token_type_ids_are_not_sent_when_the_graph_does_not_declare_them() -> None:
    session = FakeSession(inputs=("input_ids", "attention_mask"))

    build(session).encode_documents(["uno"])

    assert set(session.calls[0]["feeds"]) == {"input_ids", "attention_mask"}


def test_token_type_ids_are_sent_as_zeros_when_the_graph_declares_them() -> None:
    session = FakeSession(inputs=("input_ids", "attention_mask", "token_type_ids"))

    build(session).encode_documents(["dos palabras"])

    feeds = session.calls[0]["feeds"]
    assert feeds["token_type_ids"] == [[0] * len(feeds["input_ids"][0])]


def test_an_input_the_adapter_cannot_build_stops_the_run() -> None:
    session = FakeSession(inputs=("input_ids", "attention_mask", "position_ids"))

    with pytest.raises(OnnxGraphError, match="position_ids"):
        build(session).encode_documents(["uno"])


def test_a_graph_without_input_ids_stops_the_run() -> None:
    session = FakeSession(inputs=("pixel_values",))

    with pytest.raises(OnnxGraphError):
        build(session).encode_documents(["uno"])


# ---------------------------------------------------------------------
# Relleno
# ---------------------------------------------------------------------


def test_mixed_lengths_without_a_declared_pad_id_stop_the_run() -> None:
    session = FakeSession()
    embedder = OnnxEmbedder(
        session,
        FakeTokenizer(pad_id=None),
        model_name="BAAI/bge-m3",
        revision=PINNED_REVISION,
        dimension=DIMENSION,
        batch_size=2,
    )

    with pytest.raises(OnnxGraphError, match="pad token id"):
        embedder.encode_documents(["uno", "dos palabras aqui"])


def test_padding_uses_the_declared_pad_id_and_masks_it() -> None:
    session = FakeSession()

    build(session, batch_size=2).encode_documents(["uno", "dos palabras"])

    feeds = session.calls[0]["feeds"]
    assert feeds["input_ids"][0][-1] == 1
    assert feeds["attention_mask"][0][-1] == 0
    assert feeds["attention_mask"][1][-1] == 1


def test_batch_size_one_never_pads() -> None:
    session = FakeSession()

    build(session, batch_size=1).encode_documents(["uno", "dos palabras aqui"])

    for call in session.calls:
        assert all(mask == [1] * len(mask) for mask in call["feeds"]["attention_mask"])


# ---------------------------------------------------------------------
# Vectores inservibles
# ---------------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_component_is_rejected(bad: float) -> None:
    session = FakeSession(cls_vector=(1.0, bad, 0.0, 0.0))

    with pytest.raises(OnnxVectorError, match="non-finite"):
        build(session).encode_documents(["uno"])


def test_a_zero_norm_vector_is_rejected() -> None:
    session = FakeSession(cls_vector=(0.0, 0.0, 0.0, 0.0))

    with pytest.raises(OnnxVectorError, match="zero norm"):
        build(session).encode_documents(["uno"])


def test_a_different_dimension_is_never_truncated_or_padded() -> None:
    """Otra dimensión es otro espacio vectorial, no un vector que recortar."""
    session = FakeSession(dimension=DIMENSION + 3)

    with pytest.raises(OnnxGraphError, match="per-token states"):
        build(session).encode_documents(["uno"])


# ---------------------------------------------------------------------
# Snapshot local: nada se descarga
# ---------------------------------------------------------------------


def test_the_inventory_reports_what_is_missing_without_raising(tmp_path: Path) -> None:
    paths = OnnxModelPaths.from_snapshot(tmp_path)

    inventory = paths.inventory()

    assert inventory.complete is False
    assert inventory.as_dict()["model"]["present"] is False
    assert "model.onnx" in inventory.render()


def test_a_missing_snapshot_names_every_missing_file(tmp_path: Path) -> None:
    paths = OnnxModelPaths.from_snapshot(tmp_path)

    with pytest.raises(ModelUnavailableError) as error:
        paths.require()

    message = str(error.value)
    assert "model.onnx" in message
    assert "tokenizer.json" in message
    assert "sentence_bert_config.json" in message
    assert "nothing is downloaded automatically" in message


def test_a_snapshot_without_a_declared_max_length_stops_the_run(tmp_path: Path) -> None:
    """Adivinar el truncamiento es exactamente la divergencia que se busca."""
    (tmp_path / "onnx").mkdir()
    (tmp_path / "onnx" / "model.onnx").write_bytes(b"not a real model")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (tmp_path / "sentence_bert_config.json").write_text("{}", encoding="utf-8")

    with pytest.raises(OnnxGraphError, match="max_seq_length"):
        LocalTokenizer.from_paths(OnnxModelPaths.from_snapshot(tmp_path))


# ---------------------------------------------------------------------
# Aislamiento: ni PyTorch, ni red
# ---------------------------------------------------------------------


def test_importing_the_onnx_adapter_pulls_in_neither_torch_nor_sentence_transformers() -> None:
    """El objetivo del bloque es un runtime sin PyTorch residente.

    Se comprueba en un proceso limpio y sobre `sys.modules`: un import dentro
    de una función pasaría desapercibido en una revisión de código y no aquí.
    """
    script = (
        "import sys;"
        "import elsa.bench.adapters.onnx;"
        "bad=[n for n in ('torch','sentence_transformers','transformers') if n in sys.modules];"
        "print(','.join(bad))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "", f"el adaptador importa: {result.stdout.strip()}"


def test_the_adapter_never_opens_a_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the experimental ONNX adapter must not use the network")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    [record] = build(FakeSession()).encode_documents(["uno"])

    assert len(record.vector) == DIMENSION


# ---------------------------------------------------------------------
# Artefactos del experimento
# ---------------------------------------------------------------------


def test_a_vector_survives_the_round_trip_bit_for_bit() -> None:
    """Un `repr` decimal introduciría una diferencia del tamaño de lo medido.

    Se parte de valores que ya son representables en `float32` —los que el
    adaptador produce, porque normaliza y vuelve a float32— y se exige
    igualdad **exacta**, no aproximada.
    """
    vector = decode_vector(encode_vector((0.1, -0.2000001, 1234.5, 1.1754943508222875e-38)))

    restored = decode_vector(encode_vector(vector))

    assert restored == vector


def _record(
    identifier: str,
    kind: str,
    vector: tuple[float, ...],
    *,
    ids: tuple[int, ...] = (0, 5, 2),
) -> TextRecord:
    return TextRecord(
        id=identifier,
        kind=kind,
        text_sha256=f"t:{identifier}",
        prefixed_text_sha256=f"p:{identifier}",
        token_count=len(ids),
        input_ids=ids,
        attention_mask=tuple(1 for _ in ids),
        input_ids_sha256=f"i:{ids}",
        attention_mask_sha256="m",
        truncated=False,
        dimension=len(vector),
        norm_before=1.0,
        norm_after=1.0,
        vector=vector,
    )


def _capture(runtime: str, records: Sequence[TextRecord], **identity: object) -> Capture:
    base = {
        "model_id": "BAAI/bge-m3",
        "revision": PINNED_REVISION,
        "runtime": runtime,
        "dimension": 4,
        "document_prefix": "",
        "query_prefix": "",
        "composition_template": "context-v1",
        "corpus_fingerprint": "c",
        "golden_fingerprint": "g",
        "precision": "fp32",
    }
    base.update(identity)
    return Capture(
        manifest={"identity": base, "identity_sha256": "x"},
        documents=tuple(r for r in records if r.kind == "document"),
        queries=tuple(r for r in records if r.kind == "query"),
    )


def test_a_capture_survives_serialisation(tmp_path: Path) -> None:
    capture = _capture("onnxruntime", [_record("c1", "document", (1.0, 0.0, 0.0, 0.0))])
    destination = tmp_path / "captura.json"

    capture.write(destination)
    restored = Capture.read(destination)

    assert json.loads(destination.read_text(encoding="utf-8"))["schema"] == CAPTURE_SCHEMA
    assert restored.documents[0].vector == capture.documents[0].vector
    assert restored.documents[0].input_ids == capture.documents[0].input_ids


@pytest.fixture(scope="module")
def corpus() -> BenchCorpus:
    return build_corpus()


@pytest.fixture(scope="module")
def golden(corpus: BenchCorpus) -> GoldenSet:
    return load_golden_set(corpus)


def test_captures_of_different_text_are_refused_instead_of_compared(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """Comparar vectores de textos distintos produce un número ininterpretable."""
    left = _capture("sentence-transformers", [_record("c1", "document", (1.0, 0.0, 0.0, 0.0))])
    right = _capture("onnxruntime", [_record("c1", "document", (1.0, 0.0, 0.0, 0.0))])
    altered = Capture(
        manifest=right.manifest,
        documents=(replace(right.documents[0], prefixed_text_sha256="otro-texto"),),
        queries=(),
    )

    report = compare(left, altered, corpus, golden)

    assert report["preconditions"]["comparable"] is False
    assert report["vectors"] is None
    assert report["retrieval"] is None
    assert "NOT COMPARABLE" in str(report["verdict"])
    assert "no se compararon" in render_markdown(report).lower()


def test_a_different_corpus_fingerprint_is_refused(corpus: BenchCorpus, golden: GoldenSet) -> None:
    left = _capture("sentence-transformers", [_record("c1", "document", (1.0, 0.0, 0.0, 0.0))])
    right = _capture(
        "onnxruntime",
        [_record("c1", "document", (1.0, 0.0, 0.0, 0.0))],
        corpus_fingerprint="otro",
    )

    report = compare(left, right, corpus, golden)

    mismatches = report["preconditions"]["identity_mismatches"]
    assert "corpus_fingerprint" in mismatches


def test_a_tokenisation_difference_is_detected_and_located(
    corpus: BenchCorpus, golden: GoldenSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Una diferencia de tokenizacion NO invalida las precondiciones.

    El texto es el mismo; lo que cambia es como se troceo. Por eso la
    comparacion continua, y el bloque de tokenizacion es el que lo dice.
    """
    from elsa.bench import onnx_experiment

    monkeypatch.setattr(onnx_experiment, "_retrieval_report", lambda *a, **k: {"skipped": True})
    left = _capture(
        "sentence-transformers",
        [_record("c1", "document", (1.0, 0.0, 0.0, 0.0), ids=(0, 5, 7, 2))],
    )
    right = _capture(
        "onnxruntime",
        [_record("c1", "document", (1.0, 0.0, 0.0, 0.0), ids=(0, 5, 9, 2))],
    )

    report = compare(left, right, corpus, golden)

    tokenization = report["tokenization"]
    assert tokenization["identical"] is False
    assert tokenization["differing"] == 1
    difference = tokenization["differences"][0]
    assert difference["first_divergent_position"] == 2
    assert difference["reference_special_tokens"] == [0, 2]


def test_identical_vectors_report_no_difference(
    corpus: BenchCorpus, golden: GoldenSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    from elsa.bench import onnx_experiment

    vector = (0.5, 0.5, 0.5, 0.5)
    left = _capture("sentence-transformers", [_record("c1", "document", vector)])
    right = _capture("onnxruntime", [_record("c1", "document", vector)])
    # La recuperación necesita el corpus completo; aquí se mide solo el
    # bloque de vectores, así que se aísla.
    monkeypatch.setattr(onnx_experiment, "_retrieval_report", lambda *a, **k: {"skipped": True})

    report = compare(left, right, corpus, golden)

    summary = report["vectors"]["summary"]
    assert summary["cosine"]["min"] == pytest.approx(1.0)
    assert summary["max_absolute_error"]["max"] == 0.0


def test_a_partial_capture_cannot_produce_a_ranking(corpus: BenchCorpus, golden: GoldenSet) -> None:
    """Rankear con una captura incompleta daría un orden plausible y falso."""
    from elsa.bench.onnx_experiment import _rank_with

    capture = _capture("onnxruntime", [_record("c1", "document", (1.0, 0.0, 0.0, 0.0))])

    with pytest.raises(ValueError, match="does not cover the whole benchmark"):
        _rank_with(capture, corpus, golden)


def test_the_experiment_identity_distinguishes_the_runtime() -> None:
    """`RunMetadata.identity()` no lo hace, y ese es justo el riesgo del bloque."""
    from elsa.bench.model import RunMetadata

    historical = RunMetadata(
        retriever="dense",
        model_name="BAAI/bge-m3",
        revision=PINNED_REVISION,
        dimension=1024,
        normalized=True,
        document_prefix="",
        query_prefix="",
        runtime="sentence-transformers",
        device="cpu",
        corpus_fingerprint="c",
        golden_fingerprint="g",
    )
    other_runtime = replace(historical, runtime="onnxruntime")

    # El banco histórico las declararía idénticas: por eso el experimento
    # escribe su propia identidad en vez de reutilizar esta.
    assert historical.identity() == other_runtime.identity()

    left = _capture("sentence-transformers", [])
    right = _capture("onnxruntime", [])
    assert left.manifest["identity"] != right.manifest["identity"]


def test_the_ranking_never_mixes_vectors_of_two_runtimes() -> None:
    """Documentos de un runtime con consultas de otro no es una comparación.

    `_rank_with` recibe **una** captura, así que la mezcla no es posible por
    construcción. Esta prueba fija esa firma: si alguien la ampliara para
    aceptar dos, esto lo detendría.
    """
    import inspect

    from elsa.bench.onnx_experiment import _rank_with

    parameters = list(inspect.signature(_rank_with).parameters)
    assert parameters == ["capture", "corpus", "golden"]


def test_the_markdown_says_it_is_not_an_approved_runtime(
    corpus: BenchCorpus, golden: GoldenSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    from elsa.bench import onnx_experiment

    vector = (0.5, 0.5, 0.5, 0.5)
    monkeypatch.setattr(
        onnx_experiment,
        "_retrieval_report",
        lambda *a, **k: {
            "summary": {
                "queries": 1,
                "top1_changed": 0,
                "order_changed": 0,
                "top10_membership_changed": 0,
            },
            "scoreboards": {
                "reference": {"primary": _flat_primary()},
                "candidate": {"primary": _flat_primary()},
            },
        },
    )
    report = compare(
        _capture("sentence-transformers", [_record("c1", "document", vector)]),
        _capture("onnxruntime", [_record("c1", "document", vector)]),
        corpus,
        golden,
    )

    markdown = render_markdown(report)

    assert "no runtime productivo aprobado" in markdown
    assert "ningun umbral de aceptacion" in markdown


def _flat_primary() -> dict[str, object]:
    return {
        "recall@1": 1.0,
        "recall@3": 1.0,
        "recall@5": 1.0,
        "recall@10": 1.0,
        "mrr@10": 1.0,
        "ndcg@10": 1.0,
        "p@5": 0.2,
    }


def test_the_pairwise_metrics_are_the_four_the_block_asked_for() -> None:
    from elsa.bench.onnx_experiment import _pairwise

    result = _pairwise((1.0, 0.0), (0.0, 1.0))

    assert set(result) == {"cosine", "mean_absolute_error", "max_absolute_error", "l2_distance"}
    assert result["cosine"] == pytest.approx(0.0)
    assert result["l2_distance"] == pytest.approx(math.sqrt(2))


def _full_capture(
    runtime: str, corpus: BenchCorpus, golden: GoldenSet, *, jitter: float
) -> Capture:
    """Cubre el banco entero con vectores deterministas y separables.

    `jitter` desplaza una componente: con 0.0 los dos runtimes son idénticos,
    y con un valor pequeño se simula la diferencia numérica que el
    experimento real va a medir.
    """

    def vector(seed: str, index: int) -> tuple[float, ...]:
        base = [0.0] * 8
        base[index % 8] = 1.0
        base[(index + 3) % 8] = 0.5 + jitter
        return decode_vector(encode_vector(tuple(base)))

    documents = [
        _record(chunk.chunk_id, "document", vector(chunk.chunk_id, index), ids=(0, index + 5, 2))
        for index, chunk in enumerate(corpus.chunks)
    ]
    queries = [
        _record(query.id, "query", vector(query.id, index), ids=(0, index + 5, 2))
        for index, query in enumerate(golden.queries)
    ]
    return _capture(runtime, documents + queries, dimension=8)


def test_the_comparison_runs_over_the_whole_benchmark(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """Camino completo: precondiciones, vectores, ranking y métricas reales.

    Usa el `DenseRetriever` y el `score_run` del banco histórico sin tocarlos,
    que es el punto: las cifras del experimento tienen que salir del mismo
    código que produjo las de ADR 0015.
    """
    reference = _full_capture("sentence-transformers", corpus, golden, jitter=0.0)
    candidate = _full_capture("onnxruntime", corpus, golden, jitter=0.0)

    report = compare(reference, candidate, corpus, golden)

    assert report["preconditions"]["comparable"] is True
    assert report["vectors"]["summary"]["pairs"] == len(corpus.chunks) + len(golden.queries)
    assert report["vectors"]["summary"]["cosine"]["min"] == pytest.approx(1.0)
    retrieval = report["retrieval"]
    assert retrieval["summary"]["queries"] == len(golden.queries)
    assert retrieval["summary"]["top1_changed"] == 0
    assert retrieval["summary"]["order_changed"] == 0
    assert "primary" in retrieval["scoreboards"]["reference"]
    assert "no runtime productivo aprobado" in render_markdown(report)


def test_the_per_query_artifact_keeps_unrounded_scores(
    corpus: BenchCorpus, golden: GoldenSet
) -> None:
    """`BenchmarkRun.rankings()` redondea a 6 decimales; aquí eso borraría el dato."""
    reference = _full_capture("sentence-transformers", corpus, golden, jitter=0.0)
    candidate = _full_capture("onnxruntime", corpus, golden, jitter=1e-7)

    report = compare(reference, candidate, corpus, golden)

    per_query = report["retrieval"]["per_query"]
    scores = [entry["score"] for query in per_query for entry in query["candidate"]]
    assert scores, "el artefacto tiene que llevar las puntuaciones"
    assert any(round(score, 6) != score for score in scores)
