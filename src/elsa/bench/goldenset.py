"""Carga y **validación** del conjunto dorado.

La validación no es un extra. Un conjunto dorado que apunta a un chunk que
ya no existe —porque el corpus cambió, o porque el chunker cambió de
política— produce métricas que parecen correctas y son basura: la consulta
no puede acertar nunca y el modelo aparenta ser peor de lo que es. Aquí eso
falla ruidosamente en vez de puntuar mal en silencio.
"""

import json
from pathlib import Path

from elsa.bench.model import Axis, BenchCorpus, Difficulty, GoldenQuery, GoldenSet, MatchKind

__all__ = ["GOLDEN_PATH", "GoldenSetError", "load_golden_set"]

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "bench" / "golden" / "queries.json"


class GoldenSetError(Exception):
    """El conjunto dorado no es coherente con el corpus."""


def load_golden_set(corpus: BenchCorpus, path: Path | None = None) -> GoldenSet:
    """Lee el conjunto dorado y comprueba que cada expectativa exista.

    Se valida contra el corpus **ya troceado**, no contra el texto fuente:
    lo que las consultas referencian son chunks, y un chunk solo existe
    después de trocear.
    """
    raw = json.loads((path or GOLDEN_PATH).read_text(encoding="utf-8"))
    known = {chunk.chunk_id for chunk in corpus.chunks}

    queries: list[GoldenQuery] = []
    seen: set[str] = set()
    problems: list[str] = []

    for entry in raw["queries"]:
        identifier = entry["id"]
        if identifier in seen:
            problems.append(f"{identifier}: repeated query id")
        seen.add(identifier)

        for chunk_id in list(entry["relevant"]) + list(entry["must_not_retrieve"]):
            if chunk_id not in known:
                problems.append(f"{identifier}: unknown chunk {chunk_id!r}")

        for chunk_id, grade in entry["relevant"].items():
            if grade not in (1, 2):
                problems.append(f"{identifier}: grade for {chunk_id!r} must be 1 or 2")

        overlap = set(entry["relevant"]) & set(entry["must_not_retrieve"])
        if overlap:
            problems.append(f"{identifier}: {sorted(overlap)} both expected and forbidden")

        if not entry["rationale"].strip():
            problems.append(f"{identifier}: an expectation without a written reason")

        queries.append(
            GoldenQuery(
                id=identifier,
                text=entry["text"],
                axis=Axis(entry["axis"]),
                match_kind=MatchKind(entry["match_kind"]),
                difficulty=Difficulty(entry["difficulty"]),
                rationale=entry["rationale"],
                relevant=dict(entry["relevant"]),
                must_not_retrieve=tuple(entry["must_not_retrieve"]),
            )
        )

    if problems:
        raise GoldenSetError(
            "the golden set is not coherent with the corpus:\n  " + "\n  ".join(problems)
        )
    return GoldenSet(queries=tuple(queries))
