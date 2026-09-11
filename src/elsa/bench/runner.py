"""Ejecuta un recuperador sobre el conjunto dorado y mide también la operación.

La calidad y el coste se miden en la **misma** corrida a propósito: un
modelo que gana por dos puntos de recall y tarda seis veces más no es el
ganador, y separarlos en dos ejecuciones invita a compararlos como si fueran
independientes.
"""

import dataclasses
import platform
import resource
import time
from collections.abc import Sequence
from dataclasses import dataclass

from elsa.bench.metrics import QueryResult, Scoreboard, score_run
from elsa.bench.model import BenchCorpus, GoldenSet, RunMetadata
from elsa.bench.ports import BenchmarkEmbedder
from elsa.bench.retrievers import DenseRetriever, Retriever

__all__ = ["BenchmarkRun", "hardware_description", "run_dense", "run_retriever"]


@dataclass(frozen=True, slots=True)
class BenchmarkRun:
    metadata: RunMetadata
    scoreboard: Scoreboard
    results: dict[str, QueryResult]

    def as_dict(self) -> dict[str, object]:
        return {
            "metadata": dataclasses.asdict(self.metadata),
            "identity": dict(self.metadata.identity()),
            "scoreboard": self.scoreboard.as_dict(),
        }


def hardware_description() -> dict[str, object]:
    """CPU, RAM y GPU de esta máquina. Se registra, no se compara."""
    cpu = platform.processor() or platform.machine()
    model = ""
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    model = line.split(":", 1)[1].strip()
                    break
    except OSError:  # pragma: no cover - depende del sistema
        pass
    ram_gb = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemTotal"):
                    ram_gb = round(int(line.split()[1]) / 1024 / 1024, 1)
                    break
    except OSError:  # pragma: no cover
        pass
    return {"cpu": model or cpu, "ram_gb": ram_gb, "gpu": "none"}


def _peak_rss_mb() -> float:
    # `ru_maxrss` viene en kibibytes en Linux.
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return round(ordered[index], 2)


def run_retriever(
    retriever: Retriever,
    corpus: BenchCorpus,
    golden: GoldenSet,
    *,
    model_name: str | None = None,
    revision: str = "-",
    dimension: int = 0,
    normalized: bool = False,
    document_prefix: str = "",
    query_prefix: str = "",
    runtime: str = "pure-python",
    device: str = "cpu",
    notes: Sequence[str] = (),
) -> BenchmarkRun:
    """Corre cualquier recuperador, incluidas las líneas base léxicas."""
    hardware = hardware_description()
    started = time.time()
    began = time.perf_counter()
    results = retriever.run(corpus, golden)
    elapsed = time.perf_counter() - began

    metadata = RunMetadata(
        retriever=retriever.name,
        model_name=model_name or retriever.name,
        revision=revision,
        dimension=dimension,
        normalized=normalized,
        document_prefix=document_prefix,
        query_prefix=query_prefix,
        runtime=runtime,
        device=device,
        corpus_fingerprint=corpus.fingerprint,
        golden_fingerprint=golden.fingerprint,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        corpus_embed_seconds=round(elapsed, 3),
        peak_rss_mb=_peak_rss_mb(),
        cpu=str(hardware["cpu"]),
        ram_gb=hardware["ram_gb"] if isinstance(hardware["ram_gb"], float) else None,
        gpu=str(hardware["gpu"]),
        notes=tuple(notes),
    )
    return BenchmarkRun(metadata=metadata, scoreboard=score_run(golden, results), results=results)


def run_dense(
    embedder: BenchmarkEmbedder,
    corpus: BenchCorpus,
    golden: GoldenSet,
    *,
    notes: Sequence[str] = (),
) -> BenchmarkRun:
    """Corre un candidato denso midiendo carga, corpus y latencia de consulta.

    Las tres cosas se cronometran por separado porque responden preguntas
    distintas: la carga decide si cabe arrancarlo en una PC de ingeniería, el
    corpus decide cuánto cuesta re-embeber al cambiar de modelo, y la
    latencia de consulta es la única que el ingeniero nota.
    """
    description = embedder.describe()
    hardware = hardware_description()
    started = time.time()

    began = time.perf_counter()
    passages = embedder.embed_documents([chunk.content for chunk in corpus.chunks])
    corpus_seconds = time.perf_counter() - began

    latencies: list[float] = []
    query_vectors: list[list[float]] = []
    for query in golden.queries:
        tick = time.perf_counter()
        query_vectors.extend(embedder.embed_queries([query.text]))
        latencies.append((time.perf_counter() - tick) * 1000)

    retriever = DenseRetriever(embedder)
    results = retriever.precomputed(corpus, golden, passages, query_vectors)

    metadata = RunMetadata(
        retriever=retriever.name,
        model_name=description.model_name,
        revision=description.revision,
        dimension=description.dimension,
        normalized=description.normalized,
        document_prefix=description.document_prefix,
        query_prefix=description.query_prefix,
        runtime=description.runtime,
        device=description.device,
        corpus_fingerprint=corpus.fingerprint,
        golden_fingerprint=golden.fingerprint,
        started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        corpus_embed_seconds=round(corpus_seconds, 3),
        query_latency_p50_ms=_percentile(latencies, 0.50),
        query_latency_p95_ms=_percentile(latencies, 0.95),
        peak_rss_mb=_peak_rss_mb(),
        cpu=str(hardware["cpu"]),
        ram_gb=hardware["ram_gb"] if isinstance(hardware["ram_gb"], float) else None,
        gpu=str(hardware["gpu"]),
        notes=tuple(notes),
    )
    return BenchmarkRun(metadata=metadata, scoreboard=score_run(golden, results), results=results)
