"""Métricas de recuperación, globales y **por eje**.

Un promedio global oculta exactamente lo que hay que ver: un modelo
excelente en consultas narrativas y nulo en códigos da una media aceptable y
es inservible para media planta. Todo lo que se calcula aquí se reporta
también desglosado.

Dos decisiones que cambian cómo se leen los números:

- **Los ejes diagnósticos no puntúan.** Los códigos los resolverá el canal
  léxico o estructurado del Bloque 4.3, no el vector. Se miden, se reportan
  y se excluyen de la puntuación principal del modelo denso: dejar que
  decidan el ganador sería elegir por el eje equivocado.
- **Las consultas sin respuesta esperada no entran en el promedio.** No
  tienen acierto posible, así que promediarlas solo diluiría el resultado.
  Se miden aparte, por su tasa de abstención: qué fracción del ranking
  devuelve algo por debajo de un umbral cuando no hay nada que devolver.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from elsa.bench.model import GoldenQuery, GoldenSet

__all__ = ["AxisScore", "QueryResult", "Scoreboard", "score_run"]

# Profundidades que se reportan. `10` es la mayor, y fija cuántos resultados
# tiene que devolver un recuperador para que las métricas sean calculables.
RECALL_DEPTHS: tuple[int, ...] = (1, 3, 5, 10)


@dataclass(frozen=True, slots=True)
class QueryResult:
    """Lo que un recuperador devolvió para una consulta, en orden."""

    query_id: str
    ranked: tuple[str, ...]
    scores: tuple[float, ...] = ()

    def top(self, depth: int) -> tuple[str, ...]:
        return self.ranked[:depth]


def _recall_at(query: GoldenQuery, ranked: Sequence[str], depth: int) -> float:
    """Fracción de los chunks relevantes que aparece en los primeros ``depth``.

    Se usa la fracción y no «acertó/no acertó» porque una consulta puede
    tener varios pasajes válidos —prosa y tabla del mismo apartado— y
    devolver solo uno no es lo mismo que devolver los dos.
    """
    if not query.relevant:
        return 0.0
    found = sum(1 for chunk_id in ranked[:depth] if chunk_id in query.relevant)
    return found / min(len(query.relevant), depth) if depth else 0.0


def _precision_at(query: GoldenQuery, ranked: Sequence[str], depth: int) -> float:
    if not depth:
        return 0.0
    return sum(1 for chunk_id in ranked[:depth] if chunk_id in query.relevant) / depth


def _reciprocal_rank(query: GoldenQuery, ranked: Sequence[str], depth: int = 10) -> float:
    for position, chunk_id in enumerate(ranked[:depth], start=1):
        if chunk_id in query.relevant:
            return 1.0 / position
    return 0.0


def _ndcg_at(query: GoldenQuery, ranked: Sequence[str], depth: int = 10) -> float:
    """nDCG con relevancia graduada (2 responde, 1 parcial)."""
    if not query.relevant:
        return 0.0
    gain = 0.0
    for position, chunk_id in enumerate(ranked[:depth], start=1):
        grade = query.relevant.get(chunk_id, 0)
        if grade:
            gain += (2**grade - 1) / math.log2(position + 1)
    ideal = 0.0
    for position, grade in enumerate(sorted(query.relevant.values(), reverse=True)[:depth], 1):
        ideal += (2**grade - 1) / math.log2(position + 1)
    return gain / ideal if ideal else 0.0


def _confusion_rate(query: GoldenQuery, ranked: Sequence[str], depth: int = 5) -> float | None:
    """Fracción de los primeros ``depth`` que la consulta marcó como error.

    **No es una medida de autorización.** Dice si el ranking denso confunde
    dos activos que hablan parecido o dos versiones del mismo documento; el
    aislamiento real lo impone el filtro de la consulta, que este banco no
    aplica a propósito para poder medir la confusión.
    """
    if not query.must_not_retrieve:
        return None
    forbidden = set(query.must_not_retrieve)
    return sum(1 for chunk_id in ranked[:depth] if chunk_id in forbidden) / depth


@dataclass(frozen=True, slots=True)
class AxisScore:
    label: str
    """Valor del eje, o ``primary`` para el agregado que puntúa."""

    queries: int
    recall: Mapping[int, float]
    mrr_at_10: float
    ndcg_at_10: float
    precision_at_5: float
    confusion_at_5: float | None = None

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "label": self.label,
            "queries": self.queries,
            **{f"recall@{k}": round(v, 4) for k, v in sorted(self.recall.items())},
            "mrr@10": round(self.mrr_at_10, 4),
            "ndcg@10": round(self.ndcg_at_10, 4),
            "p@5": round(self.precision_at_5, 4),
        }
        if self.confusion_at_5 is not None:
            data["confusion@5"] = round(self.confusion_at_5, 4)
        return data


@dataclass(frozen=True, slots=True)
class Scoreboard:
    """Resultado completo: puntuación principal, ejes y diagnósticos."""

    primary: AxisScore
    """Agregado de las consultas que puntúan: con respuesta y no diagnósticas."""

    per_axis: tuple[AxisScore, ...] = ()
    diagnostic: tuple[AxisScore, ...] = ()
    abstention_rate: float | None = None
    """De las consultas sin respuesta, fracción cuyo primer resultado quedó
    por debajo del umbral de abstención. Más alto es mejor."""

    unanswered_queries: int = 0
    notes: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "primary": self.primary.as_dict(),
            "per_axis": [score.as_dict() for score in self.per_axis],
            "diagnostic": [score.as_dict() for score in self.diagnostic],
            "abstention": {
                "queries": self.unanswered_queries,
                "rate": None if self.abstention_rate is None else round(self.abstention_rate, 4),
            },
            "notes": list(self.notes),
        }


def _aggregate(
    label: str, queries: Sequence[GoldenQuery], results: Mapping[str, QueryResult]
) -> AxisScore:
    recall = {
        depth: sum(_recall_at(q, results[q.id].ranked, depth) for q in queries) / len(queries)
        for depth in RECALL_DEPTHS
    }
    confusions = [
        rate for q in queries if (rate := _confusion_rate(q, results[q.id].ranked)) is not None
    ]
    return AxisScore(
        label=label,
        queries=len(queries),
        recall=recall,
        mrr_at_10=sum(_reciprocal_rank(q, results[q.id].ranked) for q in queries) / len(queries),
        ndcg_at_10=sum(_ndcg_at(q, results[q.id].ranked) for q in queries) / len(queries),
        precision_at_5=sum(_precision_at(q, results[q.id].ranked, 5) for q in queries)
        / len(queries),
        confusion_at_5=sum(confusions) / len(confusions) if confusions else None,
    )


def score_run(
    golden: GoldenSet,
    results: Mapping[str, QueryResult],
    *,
    abstention_threshold: float = 0.35,
) -> Scoreboard:
    """Calcula el marcador completo a partir de los rankings devueltos.

    ``abstention_threshold`` se compara contra la puntuación del primer
    resultado de una consulta sin respuesta esperada. Es un umbral del
    **banco**, no del modelo: sirve para comparar candidatos entre sí, no
    para fijar un corte de producción.

    Y solo compara candidatos **en la misma escala**. El coseno sobre
    vectores normalizados está acotado a [-1, 1]; BM25 no está acotado, así
    que un umbral fijo le exige otra cosa. Entre los tres candidatos densos
    el número es comparable; contra la línea léxica no lo es, y el informe
    lo dice donde aparece.
    """
    missing = [query.id for query in golden.queries if query.id not in results]
    if missing:
        raise ValueError(f"the retriever returned nothing for: {sorted(missing)}")

    notes: list[str] = []
    scored = golden.scored
    if not scored:
        raise ValueError("the golden set has no scoring queries")

    per_axis: list[AxisScore] = []
    diagnostic: list[AxisScore] = []
    for axis, queries in golden.by_axis().items():
        answerable = tuple(q for q in queries if q.expects_an_answer)
        if not answerable:
            continue
        score = _aggregate(axis.value, answerable, results)
        (diagnostic if queries[0].is_diagnostic else per_axis).append(score)

    unanswered = tuple(q for q in golden.queries if not q.expects_an_answer)
    abstention = None
    if unanswered:
        abstained = 0
        for query in unanswered:
            result = results[query.id]
            best = result.scores[0] if result.scores else 1.0
            if best < abstention_threshold:
                abstained += 1
        abstention = abstained / len(unanswered)
        notes.append(
            f"abstention measured over {len(unanswered)} queries with no expected answer, "
            f"threshold {abstention_threshold}"
        )
        notes.append(
            "abstention is only comparable between retrievers on the same score scale: "
            "cosine over normalised vectors is bounded to [-1, 1] while BM25 is not, so a "
            "fixed threshold means different things for each"
        )

    notes.append(
        "diagnostic axes are excluded from the primary score: exact codes are for the "
        "lexical or structured channel of block 4.3, not for the dense vector"
    )
    notes.append(
        "confusion@5 measures ranking confusability, never authorisation: isolation is "
        "enforced by the query filter, which this benchmark deliberately does not apply"
    )

    return Scoreboard(
        primary=_aggregate("primary", scored, results),
        per_axis=tuple(per_axis),
        diagnostic=tuple(diagnostic),
        abstention_rate=abstention,
        unanswered_queries=len(unanswered),
        notes=tuple(notes),
    )
