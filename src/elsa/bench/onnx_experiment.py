"""Experimento de equivalencia PyTorch ↔ ONNX FP32 para BGE-M3. **Fase 1.**

Responde una sola pregunta, y no la da por contestada de antemano:

    ¿ONNX Runtime FP32 reproduce el espacio vectorial que hoy produce
    PyTorch/SentenceTransformers para `BAAI/bge-m3`, o produce otro?

Mismo `model_id` y misma `revision` **no** implican los mismos vectores. Por
eso esto no es una comprobación con un umbral: es una **caracterización**. La
primera entrega mide la diferencia y la describe; decidir qué diferencia es
aceptable viene después, con los números delante.

## Cómo está partido, y por qué

El experimento tiene dos fases porque **los dos runtimes no pueden estar
cargados a la vez**: PC1 tiene 8 GB y ya hay un Phi residente. Cada `capture`
carga **un** runtime, escribe sus vectores en un artefacto y termina; `compare`
no carga ninguno.

    capture --runtime pytorch  →  captura-pytorch.json
    capture --runtime onnx     →  captura-onnx.json
    compare captura-pytorch.json captura-onnx.json  →  comparacion.json + .md

Ese corte no es solo de memoria: obliga a que la comparación se haga sobre
artefactos persistidos y auditables, no sobre dos objetos vivos en el mismo
proceso.

## Lo que este módulo NO hace

No toca PostgreSQL, no registra ningún modelo, no genera vectores productivos,
no activa nada y no lee la configuración de ELSA. El almacenamiento vectorial
de producción **no participa en esta fase**. Tampoco existe todavía un
adaptador productivo de ONNX: lo que hay aquí es un candidato de banco.

## Identidad del artefacto

`RunMetadata.identity()` del banco histórico **no incluye el runtime**: dos
corridas del mismo modelo con motores distintos declararían la misma
identidad. Es el mismo punto ciego que tiene el registro productivo, y por eso
este experimento **no reutiliza esa identidad**: escribe la suya, que sí
distingue runtime, versión del runtime, precisión y proveedor de ejecución.
"""

import argparse
import base64
import hashlib
import json
import math
import os
import platform
import statistics
import sys
import time
from array import array
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from elsa.bench.adapters.sentence_transformers import CANDIDATES, SentenceTransformerEmbedder
from elsa.bench.corpus import build_corpus
from elsa.bench.goldenset import load_golden_set
from elsa.bench.metrics import QueryResult, score_run
from elsa.bench.model import BenchCorpus, GoldenSet
from elsa.bench.retrievers import DenseRetriever
from elsa.documents.composition import COMPOSITION_TEMPLATE

__all__ = [
    "CAPTURE_SCHEMA",
    "COMPARISON_SCHEMA",
    "PINNED_REVISION",
    "Capture",
    "TextRecord",
    "build_parser",
    "capture_onnx",
    "capture_pytorch",
    "compare",
    "main",
    "render_markdown",
]

CAPTURE_SCHEMA = "elsa-onnx-experiment-capture/1"
COMPARISON_SCHEMA = "elsa-onnx-experiment-comparison/1"

#: Revisión inmutable de `BAAI/bge-m3` con la que se ejecuta la fase 1.
#:
#: El banco histórico declara `main` en `CANDIDATES`, que es una referencia
#: **móvil**: lo que se descargue mañana puede no ser lo que se midió. Aquí se
#: fija el commit, y `CANDIDATES` no se toca —cambiarlo alteraría el banco que
#: produjo ADR 0015—.
PINNED_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"

_DIMENSION = 1024


# ---------------------------------------------------------------------
# Artefacto de captura
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TextRecord:
    """Un texto, cómo se tokenizó y qué vector salió.

    El vector viaja como `float32` crudo en base64, no como lista de decimales:
    un `repr` de coma flotante y su lectura de vuelta introducirían una
    diferencia propia del formato, justo del tamaño de lo que aquí se mide.
    """

    id: str
    kind: str
    text_sha256: str
    prefixed_text_sha256: str
    token_count: int
    input_ids: tuple[int, ...]
    attention_mask: tuple[int, ...]
    input_ids_sha256: str
    attention_mask_sha256: str
    truncated: bool
    dimension: int
    norm_before: float
    norm_after: float
    vector: tuple[float, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "text_sha256": self.text_sha256,
            "prefixed_text_sha256": self.prefixed_text_sha256,
            "token_count": self.token_count,
            "input_ids": list(self.input_ids),
            "attention_mask": list(self.attention_mask),
            "input_ids_sha256": self.input_ids_sha256,
            "attention_mask_sha256": self.attention_mask_sha256,
            "truncated": self.truncated,
            "dimension": self.dimension,
            "norm_before": self.norm_before,
            "norm_after": self.norm_after,
            "vector_f32_b64": encode_vector(self.vector),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TextRecord":
        return cls(
            id=str(raw["id"]),
            kind=str(raw["kind"]),
            text_sha256=str(raw["text_sha256"]),
            prefixed_text_sha256=str(raw["prefixed_text_sha256"]),
            token_count=int(raw["token_count"]),
            input_ids=tuple(int(value) for value in raw["input_ids"]),
            attention_mask=tuple(int(value) for value in raw["attention_mask"]),
            input_ids_sha256=str(raw["input_ids_sha256"]),
            attention_mask_sha256=str(raw["attention_mask_sha256"]),
            truncated=bool(raw["truncated"]),
            dimension=int(raw["dimension"]),
            norm_before=float(raw["norm_before"]),
            norm_after=float(raw["norm_after"]),
            vector=decode_vector(str(raw["vector_f32_b64"])),
        )


@dataclass(frozen=True, slots=True)
class Capture:
    """Todo lo que produjo **un** runtime en **una** pasada."""

    manifest: Mapping[str, Any]
    documents: tuple[TextRecord, ...]
    queries: tuple[TextRecord, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": CAPTURE_SCHEMA,
            "manifest": dict(self.manifest),
            "documents": [record.as_dict() for record in self.documents],
            "queries": [record.as_dict() for record in self.queries],
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Capture":
        schema = raw.get("schema")
        if schema != CAPTURE_SCHEMA:
            raise ValueError(f"unknown capture schema {schema!r}; expected {CAPTURE_SCHEMA!r}")
        return cls(
            manifest=dict(raw["manifest"]),
            documents=tuple(TextRecord.from_dict(item) for item in raw["documents"]),
            queries=tuple(TextRecord.from_dict(item) for item in raw["queries"]),
        )

    @classmethod
    def read(cls, path: Path) -> "Capture":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def encode_vector(vector: Sequence[float]) -> str:
    return base64.b64encode(array("f", vector).tobytes()).decode("ascii")


def decode_vector(payload: str) -> tuple[float, ...]:
    values = array("f")
    values.frombytes(base64.b64decode(payload))
    return tuple(values)


# ---------------------------------------------------------------------
# Manifiesto
# ---------------------------------------------------------------------


def _sha256_of_file(path: Path, *, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def _artifact_entry(path: Path | None, *, hash_it: bool) -> dict[str, object] | None:
    if path is None or not path.is_file():
        return None
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256_of_file(path) if hash_it else None,
    }


def _base_manifest(
    *,
    runtime_details: Mapping[str, object],
    corpus: BenchCorpus,
    golden: GoldenSet,
    revision: str,
    document_prefix: str,
    query_prefix: str,
    artifacts: Mapping[str, object],
) -> dict[str, object]:
    """Con qué se produjo la captura. Sin esto un vector no significa nada."""
    identity = {
        "model_id": "BAAI/bge-m3",
        "revision": revision,
        "runtime": runtime_details.get("runtime"),
        "runtime_version": runtime_details.get("runtime_version"),
        "precision": runtime_details.get("precision"),
        "execution_provider": runtime_details.get("execution_provider"),
        "pooling": runtime_details.get("pooling"),
        "normalization": runtime_details.get("normalization"),
        "dimension": _DIMENSION,
        "document_prefix": document_prefix,
        "query_prefix": query_prefix,
        "composition_template": COMPOSITION_TEMPLATE,
        "corpus_fingerprint": corpus.fingerprint,
        "golden_fingerprint": golden.fingerprint,
    }
    return {
        # La identidad sí distingue runtime, a diferencia de
        # `RunMetadata.identity()`. Ver el docstring del módulo.
        "identity": identity,
        "identity_sha256": hashlib.sha256(
            json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "runtime_details": dict(runtime_details),
        "artifacts": dict(artifacts),
        "environment": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or platform.machine(),
            "python": sys.version.split()[0],
            "numpy": _numpy_version(),
        },
        "scope": (
            "Experimental Phase 1 (FP32). Not an approved production runtime; no vector "
            "space is registered and no production embedding is generated."
        ),
    }


def _numpy_version() -> str | None:
    try:
        import numpy
    except ImportError:
        return None
    return str(numpy.__version__)


# ---------------------------------------------------------------------
# Captura: PyTorch / SentenceTransformers (referencia)
# ---------------------------------------------------------------------


def _bge_spec(revision: str) -> Any:
    """La ficha de BGE-M3 del banco, con la revisión fijada.

    Se copia en vez de editar `CANDIDATES`: esa constante es la que produjo
    las cifras de ADR 0015 y cambiarla haría incomparables las corridas
    históricas.
    """
    spec = next(item for item in CANDIDATES if item.key == "bge-m3")
    return replace(spec, revision=revision)


def _reference_model(embedder: SentenceTransformerEmbedder) -> Any:
    """El `SentenceTransformer` que el adaptador del banco ya cargó.

    Se alcanza el atributo interno a propósito y una sola vez: la alternativa
    sería cargar el modelo **otra** vez para poder tokenizar, y en una máquina
    de 8 GB duplicar 2,3 GB de pesos es exactamente lo que este bloque intenta
    evitar. El adaptador del banco no se modifica.
    """
    model = getattr(embedder, "_model", None)
    if model is None:  # pragma: no cover - defensivo
        raise RuntimeError("the benchmark adapter did not expose a loaded model")
    return model


def _tokenize_with_reference(model: Any, text: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Los identificadores que **el propio modelo de referencia** alimenta.

    Se usa `model.tokenize`, no un tokenizador construido aparte: lo que hay
    que comparar contra ONNX es lo que PyTorch realmente procesó, no una
    reconstrucción plausible de ello.
    """
    features = model.tokenize([text])
    ids_tensor = features.get("input_ids")
    if ids_tensor is None:
        raise RuntimeError("the reference tokenizer did not produce 'input_ids'")
    ids = tuple(int(value) for value in ids_tensor[0].tolist())
    mask_tensor = features.get("attention_mask")
    mask = (
        tuple(int(value) for value in mask_tensor[0].tolist())
        if mask_tensor is not None
        else tuple(1 for _ in ids)
    )
    return ids, mask


def capture_pytorch(
    corpus: BenchCorpus,
    golden: GoldenSet,
    *,
    revision: str = PINNED_REVISION,
    device: str = "cpu",
    batch_size: int = 1,
) -> Capture:
    """Carga **solo** SentenceTransformers y captura la referencia."""
    spec = _bge_spec(revision)
    started = time.perf_counter()
    embedder = SentenceTransformerEmbedder(spec, device=device, batch_size=batch_size)
    load_seconds = time.perf_counter() - started
    model = _reference_model(embedder)

    import sentence_transformers

    runtime_details: dict[str, object] = {
        "runtime": "sentence-transformers",
        "runtime_version": str(sentence_transformers.__version__),
        "precision": "fp32",
        "execution_provider": f"torch:{device}",
        "pooling": "cls",
        "normalization": "l2",
        "batch_size": batch_size,
        "max_seq_length": int(getattr(model, "max_seq_length", 0)) or None,
        "torch_version": _torch_version(),
        "load_seconds": round(load_seconds, 3),
    }

    documents = _capture_reference_side(
        model,
        embedder,
        kind="document",
        prefix=spec.document_prefix,
        items=[(chunk.chunk_id, chunk.embedded_text or chunk.content) for chunk in corpus.chunks],
    )
    queries = _capture_reference_side(
        model,
        embedder,
        kind="query",
        prefix=spec.query_prefix,
        items=[(query.id, query.text) for query in golden.queries],
    )
    manifest = _base_manifest(
        runtime_details=runtime_details,
        corpus=corpus,
        golden=golden,
        revision=revision,
        document_prefix=spec.document_prefix,
        query_prefix=spec.query_prefix,
        artifacts={"source": "huggingface cache (local)", "note": "weights are not hashed here"},
    )
    return Capture(manifest=manifest, documents=documents, queries=queries)


def _torch_version() -> str | None:
    module = sys.modules.get("torch")
    return None if module is None else str(module.__version__)


def _capture_reference_side(
    model: Any,
    embedder: SentenceTransformerEmbedder,
    *,
    kind: str,
    prefix: str,
    items: Sequence[tuple[str, str]],
) -> tuple[TextRecord, ...]:
    """Dos pasadas a propósito: la normalizada y la cruda.

    El vector que se compara es el que produce el adaptador del banco con su
    normalización propia —es decir, exactamente la referencia de ADR 0015—.
    `norm_before` sale de una segunda pasada sin normalizar. Calcular la norma
    a partir del vector ya normalizado daría 1,0 y no diría nada; normalizar a
    mano el crudo para ahorrarse una pasada cambiaría la referencia por una
    reconstrucción.
    """
    texts = [text for _, text in items]
    embed = embedder.embed_documents if kind == "document" else embedder.embed_queries
    normalized = embed(texts)
    raw = _encode_unnormalized(model, [prefix + text for text in texts])

    records: list[TextRecord] = []
    for index, (identifier, text) in enumerate(items):
        prefixed = prefix + text
        ids, mask = _tokenize_with_reference(model, prefixed)
        vector = tuple(float(value) for value in normalized[index])
        before = math.sqrt(math.fsum(value * value for value in raw[index]))
        records.append(
            TextRecord(
                id=identifier,
                kind=kind,
                text_sha256=_sha256_of_text(text),
                prefixed_text_sha256=_sha256_of_text(prefixed),
                token_count=len(ids),
                input_ids=ids,
                attention_mask=mask,
                input_ids_sha256=_sha256_of_ints(ids),
                attention_mask_sha256=_sha256_of_ints(mask),
                truncated=len(ids) >= int(getattr(model, "max_seq_length", 0) or 0) > 0,
                dimension=len(vector),
                norm_before=before,
                norm_after=math.sqrt(math.fsum(value * value for value in vector)),
                vector=vector,
            )
        )
    return tuple(records)


def _encode_unnormalized(model: Any, texts: Sequence[str]) -> list[list[float]]:
    vectors = model.encode(
        list(texts),
        batch_size=1,
        normalize_embeddings=False,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return [[float(value) for value in row] for row in vectors]


# ---------------------------------------------------------------------
# Captura: ONNX Runtime (candidato)
# ---------------------------------------------------------------------


def capture_onnx(
    corpus: BenchCorpus,
    golden: GoldenSet,
    *,
    paths: Any,
    revision: str = PINNED_REVISION,
    batch_size: int = 1,
    threads: int | None = None,
    hash_weights: bool = True,
) -> Capture:
    """Carga **solo** ONNX Runtime y captura el candidato."""
    from elsa.bench.adapters.onnx import OnnxEmbedder

    spec = _bge_spec(revision)
    started = time.perf_counter()
    embedder = OnnxEmbedder.from_local_files(
        paths,
        model_name=spec.model_name,
        revision=revision,
        dimension=_DIMENSION,
        document_prefix=spec.document_prefix,
        query_prefix=spec.query_prefix,
        batch_size=batch_size,
        threads=threads,
    )
    load_seconds = time.perf_counter() - started

    documents = _capture_onnx_side(
        embedder,
        kind="document",
        prefix=spec.document_prefix,
        items=[(chunk.chunk_id, chunk.embedded_text or chunk.content) for chunk in corpus.chunks],
    )
    queries = _capture_onnx_side(
        embedder,
        kind="query",
        prefix=spec.query_prefix,
        items=[(query.id, query.text) for query in golden.queries],
    )
    runtime_details = {**embedder.runtime_details(), "load_seconds": round(load_seconds, 3)}
    manifest = _base_manifest(
        runtime_details=runtime_details,
        corpus=corpus,
        golden=golden,
        revision=revision,
        document_prefix=spec.document_prefix,
        query_prefix=spec.query_prefix,
        artifacts={
            "model": _artifact_entry(paths.model, hash_it=hash_weights),
            "external_data": _artifact_entry(paths.external_data, hash_it=hash_weights),
            "tokenizer": _artifact_entry(paths.tokenizer, hash_it=True),
            "sentence_bert_config": _artifact_entry(paths.sentence_bert_config, hash_it=True),
            "tokenizer_config": _artifact_entry(paths.tokenizer_config, hash_it=True),
        },
    )
    return Capture(manifest=manifest, documents=documents, queries=queries)


def _capture_onnx_side(
    embedder: Any, *, kind: str, prefix: str, items: Sequence[tuple[str, str]]
) -> tuple[TextRecord, ...]:
    texts = [text for _, text in items]
    encode = embedder.encode_documents if kind == "document" else embedder.encode_queries
    diagnostics = encode(texts)
    records: list[TextRecord] = []
    for (identifier, text), result in zip(items, diagnostics, strict=True):
        token = result.tokenized
        records.append(
            TextRecord(
                id=identifier,
                kind=kind,
                text_sha256=_sha256_of_text(text),
                prefixed_text_sha256=token.text_sha256,
                token_count=token.length,
                input_ids=token.input_ids,
                attention_mask=token.attention_mask,
                input_ids_sha256=token.input_ids_sha256,
                attention_mask_sha256=token.attention_mask_sha256,
                truncated=token.truncated,
                dimension=len(result.vector),
                norm_before=result.norm_before,
                norm_after=result.norm_after,
                vector=result.vector,
            )
        )
    return tuple(records)


# ---------------------------------------------------------------------
# Comparación
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CapturedEmbedder:
    """Sirve vectores ya capturados para poder reutilizar `DenseRetriever`.

    No carga nada y no embebe nada: existe para que la comparación use el
    **mismo** recuperador y las **mismas** métricas que el banco histórico,
    en vez de una reimplementación que podría diferir sin que se note.
    """

    model_name: str
    revision: str
    dimension: int
    runtime: str

    def describe(self) -> "_CapturedEmbedder":
        return self

    @property
    def normalized(self) -> bool:
        return True

    @property
    def document_prefix(self) -> str:
        return ""

    @property
    def query_prefix(self) -> str:
        return ""

    @property
    def device(self) -> str:
        return "cpu"

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError("a captured runtime does not embed new text")

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError("a captured runtime does not embed new text")


def _pairwise(left: Sequence[float], right: Sequence[float]) -> dict[str, float]:
    """Cuatro lecturas de la misma diferencia, en float64 sobre fuentes float32.

    El coseno dice si el ranking va a cambiar; el error absoluto dice cuánto se
    movió cada componente. Reportar solo uno de los dos deja siempre una
    pregunta sin responder.
    """
    if len(left) != len(right):
        raise ValueError(f"vectors of different dimension: {len(left)} vs {len(right)}")
    dot = math.fsum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(math.fsum(a * a for a in left))
    right_norm = math.sqrt(math.fsum(b * b for b in right))
    deltas = [abs(a - b) for a, b in zip(left, right, strict=True)]
    return {
        "cosine": dot / (left_norm * right_norm) if left_norm and right_norm else 0.0,
        "mean_absolute_error": math.fsum(deltas) / len(deltas),
        "max_absolute_error": max(deltas),
        "l2_distance": math.sqrt(math.fsum((a - b) ** 2 for a, b in zip(left, right, strict=True))),
    }


def _summarise(pairs: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    if not pairs:
        return {}
    summary: dict[str, object] = {"pairs": len(pairs)}
    for metric in ("cosine", "mean_absolute_error", "max_absolute_error", "l2_distance"):
        values = [float(pair[metric]) for pair in pairs]
        summary[metric] = {
            "min": min(values),
            "mean": statistics.fmean(values),
            "median": statistics.median(values),
            "max": max(values),
        }
    worst = min(pairs, key=lambda pair: float(pair["cosine"]))
    summary["worst_by_cosine"] = {
        "id": worst["id"],
        "kind": worst["kind"],
        "cosine": worst["cosine"],
        "max_absolute_error": worst["max_absolute_error"],
        "token_count": worst["token_count"],
    }
    worst_error = max(pairs, key=lambda pair: float(pair["max_absolute_error"]))
    summary["worst_by_absolute_error"] = {
        "id": worst_error["id"],
        "kind": worst_error["kind"],
        "cosine": worst_error["cosine"],
        "max_absolute_error": worst_error["max_absolute_error"],
        "token_count": worst_error["token_count"],
    }
    return summary


def _check_preconditions(reference: Capture, candidate: Capture) -> dict[str, object]:
    """Antes de comparar nada: ¿son comparables?

    Si el corpus, el conjunto dorado, los prefijos o el texto exacto difieren,
    las diferencias de vector no significan lo que parecen. Esto lo detecta y
    detiene, en vez de producir un número que nadie podría interpretar.
    """
    left = dict(reference.manifest["identity"])
    right = dict(candidate.manifest["identity"])
    comparable_keys = (
        "model_id",
        "revision",
        "dimension",
        "document_prefix",
        "query_prefix",
        "composition_template",
        "corpus_fingerprint",
        "golden_fingerprint",
    )
    mismatched = {
        key: [left.get(key), right.get(key)]
        for key in comparable_keys
        if left.get(key) != right.get(key)
    }

    text_mismatches: list[str] = []
    for side in ("documents", "queries"):
        by_id = {record.id: record for record in getattr(candidate, side)}
        for record in getattr(reference, side):
            other = by_id.get(record.id)
            if other is None:
                text_mismatches.append(f"{record.id}: missing in the candidate capture")
            elif other.prefixed_text_sha256 != record.prefixed_text_sha256:
                text_mismatches.append(f"{record.id}: the embedded text differs")

    return {
        "identity_mismatches": mismatched,
        "text_mismatches": text_mismatches,
        "comparable": not mismatched and not text_mismatches,
        "runtimes": [left.get("runtime"), right.get("runtime")],
    }


def _tokenization_report(reference: Capture, candidate: Capture) -> dict[str, object]:
    """Equivalencia de tokenización, token a token.

    Es la primera explicación posible de una diferencia de vector, y la más
    barata de descartar: si los identificadores difieren, lo que falla no es el
    runtime sino la entrada, y comparar encoders no tiene sentido todavía.
    """
    differences: list[dict[str, object]] = []
    compared = 0
    for side in ("documents", "queries"):
        by_id = {record.id: record for record in getattr(candidate, side)}
        for record in getattr(reference, side):
            other = by_id.get(record.id)
            if other is None:
                continue
            compared += 1
            if (
                record.input_ids == other.input_ids
                and record.attention_mask == other.attention_mask
            ):
                continue
            differences.append(
                {
                    "id": record.id,
                    "kind": record.kind,
                    "reference_length": record.token_count,
                    "candidate_length": other.token_count,
                    "reference_input_ids_sha256": record.input_ids_sha256,
                    "candidate_input_ids_sha256": other.input_ids_sha256,
                    "reference_special_tokens": _edges(record.input_ids),
                    "candidate_special_tokens": _edges(other.input_ids),
                    "reference_truncated": record.truncated,
                    "candidate_truncated": other.truncated,
                    "first_divergent_position": _first_difference(
                        record.input_ids, other.input_ids
                    ),
                    "attention_mask_differs": record.attention_mask != other.attention_mask,
                }
            )
    return {
        "compared": compared,
        "identical": len(differences) == 0,
        "differing": len(differences),
        "differences": differences[:20],
    }


def _edges(ids: Sequence[int]) -> list[int] | None:
    return [ids[0], ids[-1]] if ids else None


def _first_difference(left: Sequence[int], right: Sequence[int]) -> int | None:
    for position, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            return position
    return min(len(left), len(right)) if len(left) != len(right) else None


def _rank_with(capture: Capture, corpus: BenchCorpus, golden: GoldenSet) -> dict[str, QueryResult]:
    """Rankea con vectores del **mismo** runtime, nunca cruzados.

    Los vectores se reordenan por identificador contra el corpus y el conjunto
    dorado en vez de confiar en el orden del archivo: un artefacto reordenado
    produciría un ranking plausible y equivocado.
    """
    documents = {record.id: record.vector for record in capture.documents}
    queries = {record.id: record.vector for record in capture.queries}
    missing_docs = [chunk.chunk_id for chunk in corpus.chunks if chunk.chunk_id not in documents]
    missing_queries = [query.id for query in golden.queries if query.id not in queries]
    if missing_docs or missing_queries:
        raise ValueError(
            "the capture does not cover the whole benchmark; "
            f"missing chunks: {missing_docs[:5]}, missing queries: {missing_queries[:5]}"
        )
    identity = dict(capture.manifest["identity"])
    embedder = _CapturedEmbedder(
        model_name=f"{identity.get('model_id')}[{identity.get('runtime')}]",
        revision=str(identity.get("revision")),
        dimension=int(identity.get("dimension") or _DIMENSION),
        runtime=str(identity.get("runtime")),
    )
    retriever = DenseRetriever(embedder)
    return retriever.precomputed(
        corpus,
        golden,
        [list(documents[chunk.chunk_id]) for chunk in corpus.chunks],
        [list(queries[query.id]) for query in golden.queries],
    )


def _retrieval_report(
    reference: Capture, candidate: Capture, corpus: BenchCorpus, golden: GoldenSet
) -> dict[str, object]:
    left = _rank_with(reference, corpus, golden)
    right = _rank_with(candidate, corpus, golden)

    per_query: list[dict[str, object]] = []
    top1_changes = 0
    order_changes = 0
    membership_changes = 0
    for query in golden.queries:
        a, b = left[query.id], right[query.id]
        entered = [cid for cid in b.ranked if cid not in a.ranked]
        left_out = [cid for cid in a.ranked if cid not in b.ranked]
        top1 = a.ranked[:1] != b.ranked[:1]
        order = a.ranked != b.ranked
        top1_changes += int(top1)
        order_changes += int(order)
        membership_changes += int(bool(entered or left_out))
        per_query.append(
            {
                "query_id": query.id,
                "axis": query.axis.value,
                "top1_changed": top1,
                "order_changed": order,
                "entered_top10": entered,
                "left_top10": left_out,
                # Sin redondear: el objeto de este artefacto es poder ver
                # diferencias que un `round(..., 6)` borraría.
                "reference": _ranking(a),
                "candidate": _ranking(b),
                "relevant_positions": {
                    chunk_id: {
                        "reference": _position(a.ranked, chunk_id),
                        "candidate": _position(b.ranked, chunk_id),
                    }
                    for chunk_id in sorted(query.relevant)
                },
            }
        )

    return {
        "scoreboards": {
            "reference": score_run(golden, left).as_dict(),
            "candidate": score_run(golden, right).as_dict(),
        },
        "summary": {
            "queries": len(golden.queries),
            "top1_changed": top1_changes,
            "order_changed": order_changes,
            "top10_membership_changed": membership_changes,
        },
        "per_query": per_query,
    }


def _ranking(result: QueryResult) -> list[dict[str, object]]:
    return [
        {"rank": position, "chunk_id": chunk_id, "score": result.scores[position - 1]}
        for position, chunk_id in enumerate(result.ranked, start=1)
        if position <= len(result.scores)
    ]


def _position(ranked: Sequence[str], chunk_id: str) -> int | None:
    return ranked.index(chunk_id) + 1 if chunk_id in ranked else None


def compare(
    reference: Capture,
    candidate: Capture,
    corpus: BenchCorpus,
    golden: GoldenSet,
) -> dict[str, Any]:
    """Compara dos capturas. No carga ningún modelo."""
    preconditions = _check_preconditions(reference, candidate)
    report: dict[str, Any] = {
        "schema": COMPARISON_SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reference_manifest": dict(reference.manifest),
        "candidate_manifest": dict(candidate.manifest),
        "preconditions": preconditions,
        "tokenization": _tokenization_report(reference, candidate),
    }
    if not preconditions["comparable"]:
        report["vectors"] = None
        report["retrieval"] = None
        report["verdict"] = (
            "NOT COMPARABLE: the two captures do not describe the same input. "
            "Vector and retrieval comparison were not computed."
        )
        return report

    pairs: list[dict[str, object]] = []
    for side in ("documents", "queries"):
        by_id = {record.id: record for record in getattr(candidate, side)}
        for record in getattr(reference, side):
            other = by_id[record.id]
            pairs.append(
                {
                    "id": record.id,
                    "kind": record.kind,
                    "token_count": record.token_count,
                    "reference_norm_before": record.norm_before,
                    "candidate_norm_before": other.norm_before,
                    "norm_before_absolute_difference": abs(record.norm_before - other.norm_before),
                    **_pairwise(record.vector, other.vector),
                }
            )
    report["vectors"] = {
        "per_text": pairs,
        "summary": _summarise(pairs),
        "documents_summary": _summarise([p for p in pairs if p["kind"] == "document"]),
        "queries_summary": _summarise([p for p in pairs if p["kind"] == "query"]),
    }
    report["retrieval"] = _retrieval_report(reference, candidate, corpus, golden)
    report["verdict"] = (
        "CHARACTERISED: this phase measures the difference; it does not approve a runtime. "
        "No acceptance threshold is applied here on purpose."
    )
    return report


# ---------------------------------------------------------------------
# Informe legible
# ---------------------------------------------------------------------


def render_markdown(report: Mapping[str, Any]) -> str:
    """Resumen legible. El artefacto numérico sigue siendo el JSON."""
    lines = [
        "# Experimento ONNX FP32 — Fase 1",
        "",
        "**Control experimental, no runtime productivo aprobado.** Esta fase",
        "caracteriza la diferencia entre PyTorch y ONNX Runtime; no aplica",
        "ningun umbral de aceptacion y no habilita nada.",
        "",
        f"- generado: {report.get('generated_at')}",
    ]
    reference = dict(report["reference_manifest"])["identity"]
    candidate = dict(report["candidate_manifest"])["identity"]
    lines += [
        f"- referencia: `{reference['runtime']}` @ `{reference['revision']}`",
        f"- candidato: `{candidate['runtime']}` @ `{candidate['revision']}`",
        "",
        "## Precondiciones",
        "",
    ]
    preconditions = dict(report["preconditions"])
    lines.append(f"- comparables: **{'si' if preconditions['comparable'] else 'NO'}**")
    for key, value in dict(preconditions["identity_mismatches"]).items():
        lines.append(f"- difiere `{key}`: {value[0]!r} vs {value[1]!r}")
    for problem in list(preconditions["text_mismatches"])[:10]:
        lines.append(f"- texto: {problem}")

    tokenization = dict(report["tokenization"])
    lines += [
        "",
        "## Tokenizacion",
        "",
        f"- textos comparados: {tokenization['compared']}",
        f"- identicos: **{'si' if tokenization['identical'] else 'NO'}**"
        f" ({tokenization['differing']} difieren)",
    ]
    for difference in list(tokenization["differences"])[:5]:
        lines.append(
            f"  - `{difference['id']}`: {difference['reference_length']} vs "
            f"{difference['candidate_length']} tokens, primera divergencia en "
            f"{difference['first_divergent_position']}"
        )

    vectors = report.get("vectors")
    if not vectors:
        lines += ["", "## Vectores", "", "No se compararon: las capturas no son comparables."]
        return "\n".join(lines) + "\n"

    summary = dict(dict(vectors)["summary"])
    lines += [
        "",
        "## Vectores",
        "",
        "| metrica | min | media | mediana | max |",
        "|---|---|---|---|---|",
    ]
    for metric in ("cosine", "mean_absolute_error", "max_absolute_error", "l2_distance"):
        cell = dict(summary[metric])
        lines.append(
            f"| {metric} | {cell['min']:.9g} | {cell['mean']:.9g} | "
            f"{cell['median']:.9g} | {cell['max']:.9g} |"
        )
    worst = dict(summary["worst_by_cosine"])
    lines += [
        "",
        f"Peor caso por coseno: `{worst['id']}` ({worst['kind']}, "
        f"{worst['token_count']} tokens) → coseno {worst['cosine']:.9g}.",
    ]

    retrieval = dict(report["retrieval"])
    counters = dict(retrieval["summary"])
    lines += [
        "",
        "## Recuperacion",
        "",
        f"- consultas: {counters['queries']}",
        f"- cambio el primer resultado: **{counters['top1_changed']}**",
        f"- cambio el orden del top-10: **{counters['order_changed']}**",
        f"- cambio la composicion del top-10: **{counters['top10_membership_changed']}**",
        "",
        "| metrica | referencia | candidato |",
        "|---|---|---|",
    ]
    left = dict(dict(retrieval["scoreboards"])["reference"])["primary"]
    right = dict(dict(retrieval["scoreboards"])["candidate"])["primary"]
    for key in ("recall@1", "recall@3", "recall@5", "recall@10", "mrr@10", "ndcg@10", "p@5"):
        lines.append(f"| {key} | {dict(left)[key]} | {dict(right)[key]} |")
    lines += ["", f"{report.get('verdict')}", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------


def _sha256_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_of_ints(values: Sequence[int]) -> str:
    return hashlib.sha256(",".join(str(int(v)) for v in values).encode("ascii")).hexdigest()


def _load_benchmark() -> tuple[BenchCorpus, GoldenSet]:
    corpus = build_corpus()
    return corpus, load_golden_set(corpus)


def _paths_from_args(args: argparse.Namespace) -> Any:
    from elsa.bench.adapters.onnx import OnnxModelPaths

    if args.snapshot is None:
        raise SystemExit("--snapshot is required: this experiment never downloads anything")
    paths = OnnxModelPaths.from_snapshot(Path(args.snapshot), onnx_subdir=args.onnx_subdir)
    if args.onnx_model:
        paths = replace(paths, model=Path(args.onnx_model))
    if args.tokenizer:
        paths = replace(paths, tokenizer=Path(args.tokenizer))
    return paths


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m elsa.bench.onnx_experiment",
        description=(
            "Fase 1 del experimento ONNX: caracteriza la diferencia entre BGE-M3 sobre "
            "PyTorch y sobre ONNX Runtime FP32. No integra nada en produccion."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    inventory = sub.add_parser(
        "inventory", help="dice que archivos del snapshot estan presentes; no descarga nada"
    )
    inventory.add_argument("--snapshot", required=True)
    inventory.add_argument("--onnx-subdir", default="onnx")

    capture = sub.add_parser("capture", help="carga UN runtime y escribe su captura")
    capture.add_argument("--runtime", choices=("pytorch", "onnx"), required=True)
    capture.add_argument("--out", required=True)
    capture.add_argument("--revision", default=PINNED_REVISION)
    capture.add_argument("--batch-size", type=int, default=1)
    capture.add_argument("--device", default="cpu", help="solo para el runtime pytorch")
    capture.add_argument("--snapshot", default=None, help="solo para el runtime onnx")
    capture.add_argument("--onnx-subdir", default="onnx")
    capture.add_argument("--onnx-model", default=None)
    capture.add_argument("--tokenizer", default=None)
    capture.add_argument("--threads", type=int, default=None)
    capture.add_argument(
        "--no-hash-weights",
        action="store_true",
        help="omite el sha256 de los pesos (son GB y tarda); queda registrado como nulo",
    )
    capture.add_argument(
        "--allow-network",
        action="store_true",
        help="no fija HF_HUB_OFFLINE=1. Por defecto la captura corre sin red",
    )

    compare_cmd = sub.add_parser("compare", help="compara dos capturas; no carga ningun modelo")
    compare_cmd.add_argument("reference")
    compare_cmd.add_argument("candidate")
    compare_cmd.add_argument("--out", required=True, help="ruta del JSON; el .md va al lado")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "inventory":
        from elsa.bench.adapters.onnx import OnnxModelPaths

        paths = OnnxModelPaths.from_snapshot(Path(args.snapshot), onnx_subdir=args.onnx_subdir)
        print(paths.inventory().render())
        return 0 if paths.inventory().complete else 1

    if args.command == "capture":
        if not args.allow_network:
            # La captura no descarga nada. Fijarlo en el entorno del proceso lo
            # vuelve comprobable en vez de ser una promesa del README.
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        corpus, golden = _load_benchmark()
        if args.runtime == "pytorch":
            capture = capture_pytorch(
                corpus,
                golden,
                revision=args.revision,
                device=args.device,
                batch_size=args.batch_size,
            )
        else:
            capture = capture_onnx(
                corpus,
                golden,
                paths=_paths_from_args(args),
                revision=args.revision,
                batch_size=args.batch_size,
                threads=args.threads,
                hash_weights=not args.no_hash_weights,
            )
        destination = Path(args.out)
        capture.write(destination)
        identity = dict(capture.manifest["identity"])
        print(f"captura escrita: {destination}")
        print(f"  runtime: {identity['runtime']} ({identity['precision']})")
        print(f"  identidad: {capture.manifest['identity_sha256']}")
        print(f"  documentos: {len(capture.documents)}  consultas: {len(capture.queries)}")
        return 0

    corpus, golden = _load_benchmark()
    report = compare(
        Capture.read(Path(args.reference)), Capture.read(Path(args.candidate)), corpus, golden
    )
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown = destination.with_suffix(".md")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    print(f"comparacion escrita: {destination}")
    print(f"resumen: {markdown}")
    print(report["verdict"])
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
