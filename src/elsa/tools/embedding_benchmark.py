"""Banco de pruebas para elegir el modelo de embeddings (Bloque 4.2.a).

    uv run python -m elsa.tools.embedding_benchmark --out bench/resultados

Corre el conjunto dorado sintético contra las líneas base léxicas, el control
determinista y los candidatos densos que se puedan cargar, y escribe un
informe comparativo reproducible en JSON y en Markdown.

Por defecto **no intenta descargar nada**: las líneas base y el control
corren siempre y en cualquier máquina, también en CI. Los candidatos reales
se piden explícitamente:

    uv run python -m elsa.tools.embedding_benchmark --candidates bge-m3,qwen3-0.6b

Un candidato que no se pueda cargar queda registrado como **sin medir**, con
el motivo. No se sustituye por su puntuación pública: un número de MTEB y una
medición sobre este corpus no son comparables, y tratarlos como si lo fueran
es exactamente cómo se elige mal un modelo.

Requisitos para medir los candidatos reales, que este repositorio **no**
declara como dependencia porque el runtime de ELSA no los necesita:

    uv pip install "sentence-transformers>=3.0"

y acceso de red a `huggingface.co`.
"""

import argparse
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from elsa.bench.adapters.hashing import HashingEmbedder
from elsa.bench.adapters.sentence_transformers import (
    CANDIDATES,
    SentenceTransformerEmbedder,
)
from elsa.bench.corpus import build_corpus
from elsa.bench.goldenset import GoldenSetError, load_golden_set
from elsa.bench.ports import ModelUnavailableError
from elsa.bench.report import render_json, render_markdown
from elsa.bench.retrievers import LexicalRetriever, TrigramRetriever
from elsa.bench.runner import BenchmarkRun, run_dense, run_retriever

_DEFAULT_OUT = Path("bench/resultados")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="embedding-benchmark",
        description="Banco de pruebas del modelo de embeddings de ELSA.",
    )
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Directorio del informe")
    parser.add_argument(
        "--candidates",
        default="",
        help=(
            "Candidatos densos a medir, separados por coma. "
            f"Disponibles: {', '.join(spec.key for spec in CANDIDATES)}. "
            "Vacio = solo lineas base y control."
        ),
    )
    parser.add_argument("--device", default="cpu", help="Dispositivo de los candidatos densos")
    parser.add_argument(
        "--skip-baselines",
        action="store_true",
        help="No correr las lineas base lexicas (no recomendado: son la referencia)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)

    corpus = build_corpus()
    try:
        golden = load_golden_set(corpus)
    except GoldenSetError as error:
        print(str(error), file=sys.stderr)
        return 2

    runs: list[BenchmarkRun] = []
    unmeasured: list[dict[str, str]] = []

    if not args.skip_baselines:
        runs.append(run_retriever(LexicalRetriever(), corpus, golden))
        runs.append(run_retriever(TrigramRetriever(), corpus, golden))

    runs.append(
        run_dense(
            HashingEmbedder(),
            corpus,
            golden,
            notes=("control determinista: no es un modelo y no compite con ninguno",),
        )
    )

    requested = [key.strip() for key in args.candidates.split(",") if key.strip()]
    known = {spec.key: spec for spec in CANDIDATES}
    for key in requested:
        spec = known.get(key)
        if spec is None:
            print(f"unknown candidate {key!r}; known: {sorted(known)}", file=sys.stderr)
            return 2
        try:
            # La carga se cronometra aparte: decide si cabe arrancar el modelo
            # en una PC de ingenieria, que es una pregunta distinta de cuanto
            # cuesta embeber el corpus.
            began = time.perf_counter()
            embedder = SentenceTransformerEmbedder(spec, device=args.device)
            load_seconds = round(time.perf_counter() - began, 3)
        except ModelUnavailableError as error:
            unmeasured.append({"model": spec.model_name, "reason": str(error)})
            continue
        notes = [spec.notes, *embedder.notes]
        if not spec.production_eligible:
            notes.append(
                "measured but NOT eligible for production until its licence is formally "
                "validated for corporate use (decision D1)"
            )
        runs.append(
            run_dense(
                embedder,
                corpus,
                golden,
                load_seconds=load_seconds,
                notes=tuple(n for n in notes if n),
            )
        )

    for spec in CANDIDATES:
        if spec.key not in requested and not any(
            run.metadata.model_name == spec.model_name for run in runs
        ):
            unmeasured.append({"model": spec.model_name, "reason": "not requested in this run"})

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "informe.json").write_text(
        render_json(runs, unmeasured=unmeasured), encoding="utf-8"
    )
    (args.out / "informe.md").write_text(
        render_markdown(runs, unmeasured=unmeasured), encoding="utf-8"
    )

    print(
        f"corridas={len(runs)} sin_medir={len(unmeasured)} "
        f"chunks={len(corpus.chunks)} consultas={len(golden.queries)} informe={args.out}"
    )
    for run in runs:
        primary = run.scoreboard.primary
        print(
            f"  {run.metadata.model_name:30s} R@1={primary.recall[1]:.3f} "
            f"R@5={primary.recall[5]:.3f} MRR@10={primary.mrr_at_10:.3f}"
        )
    for item in unmeasured:
        print(f"  SIN MEDIR {item['model']}: {item['reason']}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - punto de entrada
    raise SystemExit(main())
