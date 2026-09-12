"""Las métricas del banco calculan lo que dicen calcular.

Se prueban contra rankings construidos a mano, con el resultado esperado
calculado aparte. Una métrica mal implementada no falla: puntúa mal, y
elegiría el modelo equivocado sin que nadie lo notase.
"""

import pytest

from elsa.bench.metrics import QueryResult, score_run
from elsa.bench.model import Axis, Difficulty, GoldenQuery, GoldenSet, MatchKind


def query(
    identifier: str,
    axis: Axis = Axis.NARRATIVE,
    relevant: dict[str, int] | None = None,
    forbidden: tuple[str, ...] = (),
) -> GoldenQuery:
    return GoldenQuery(
        id=identifier,
        text="consulta de prueba",
        axis=axis,
        match_kind=MatchKind.SEMANTIC,
        difficulty=Difficulty.EASY,
        rationale="motivo de prueba suficientemente largo",
        relevant=relevant if relevant is not None else {"a": 2},
        must_not_retrieve=forbidden,
    )


def ranked(identifier: str, *chunks: str, scores: tuple[float, ...] = ()) -> QueryResult:
    return QueryResult(query_id=identifier, ranked=chunks, scores=scores)


def test_a_perfect_ranking_scores_one() -> None:
    golden = GoldenSet(queries=(query("q1", relevant={"a": 2}),))

    board = score_run(golden, {"q1": ranked("q1", "a", "b", "c")})

    assert board.primary.recall[1] == 1.0
    assert board.primary.mrr_at_10 == 1.0
    assert board.primary.ndcg_at_10 == 1.0


def test_a_ranking_that_misses_scores_zero() -> None:
    golden = GoldenSet(queries=(query("q1", relevant={"a": 2}),))

    board = score_run(golden, {"q1": ranked("q1", "x", "y", "z")})

    assert board.primary.recall[1] == 0.0
    assert board.primary.recall[10] == 0.0
    assert board.primary.mrr_at_10 == 0.0


def test_the_reciprocal_rank_follows_the_position() -> None:
    golden = GoldenSet(queries=(query("q1", relevant={"a": 2}),))

    third = score_run(golden, {"q1": ranked("q1", "x", "y", "a")})

    assert third.primary.mrr_at_10 == pytest.approx(1 / 3)


def test_recall_counts_every_relevant_chunk() -> None:
    """Una consulta puede tener prosa y tabla; devolver una sola no es igual."""
    golden = GoldenSet(queries=(query("q1", relevant={"a": 2, "b": 2}),))

    half = score_run(golden, {"q1": ranked("q1", "a", "x", "y")})
    both = score_run(golden, {"q1": ranked("q1", "a", "b", "y")})

    assert half.primary.recall[3] == pytest.approx(0.5)
    assert both.primary.recall[3] == pytest.approx(1.0)


def test_ndcg_rewards_putting_the_better_answer_first() -> None:
    golden = GoldenSet(queries=(query("q1", relevant={"a": 2, "b": 1}),))

    good = score_run(golden, {"q1": ranked("q1", "a", "b")})
    worse = score_run(golden, {"q1": ranked("q1", "b", "a")})

    assert good.primary.ndcg_at_10 > worse.primary.ndcg_at_10
    assert good.primary.ndcg_at_10 == pytest.approx(1.0)


def test_precision_at_five_penalises_noise() -> None:
    golden = GoldenSet(queries=(query("q1", relevant={"a": 2}),))

    board = score_run(golden, {"q1": ranked("q1", "a", "x", "y", "z", "w")})

    assert board.primary.precision_at_5 == pytest.approx(0.2)


def test_diagnostic_axes_are_kept_out_of_the_primary_score() -> None:
    """Los códigos se miden y se reportan, pero no deciden."""
    golden = GoldenSet(
        queries=(
            query("nar", Axis.NARRATIVE, {"a": 2}),
            query("cod", Axis.CODES, {"b": 2}),
        )
    )
    results = {
        "nar": ranked("nar", "a"),
        "cod": ranked("cod", "zzz"),  # falla del todo
    }

    board = score_run(golden, results)

    assert board.primary.queries == 1
    assert board.primary.recall[1] == 1.0
    assert [score.label for score in board.diagnostic] == ["codes"]
    assert board.diagnostic[0].recall[1] == 0.0


def test_confusion_is_reported_and_named_as_confusability() -> None:
    """No es autorización: el aislamiento lo impone el filtro de la consulta."""
    golden = GoldenSet(queries=(query("act", Axis.ASSET_CONFUSION, {"a": 2}, forbidden=("mal",)),))

    board = score_run(golden, {"act": ranked("act", "mal", "a", "x", "y", "z")})

    axis = next(score for score in board.per_axis if score.label == "asset_confusion")
    assert axis.confusion_at_5 == pytest.approx(0.2)
    assert any("confusability" in note for note in board.notes)
    assert any("never authorisation" in note for note in board.notes)


def test_queries_without_an_answer_are_measured_as_abstention() -> None:
    golden = GoldenSet(
        queries=(
            query("nar", Axis.NARRATIVE, {"a": 2}),
            query("nul", Axis.NO_ANSWER, {}),
        )
    )
    results = {
        "nar": ranked("nar", "a", scores=(0.9,)),
        "nul": ranked("nul", "x", scores=(0.1,)),  # puntuación baja: se abstiene
    }

    board = score_run(golden, results)

    assert board.unanswered_queries == 1
    assert board.abstention_rate == 1.0
    assert board.primary.queries == 1


def test_a_confident_answer_to_an_unanswerable_query_is_not_abstention() -> None:
    golden = GoldenSet(
        queries=(query("nar", Axis.NARRATIVE, {"a": 2}), query("nul", Axis.NO_ANSWER, {}))
    )
    results = {
        "nar": ranked("nar", "a", scores=(0.9,)),
        "nul": ranked("nul", "x", scores=(0.99,)),
    }

    board = score_run(golden, results)

    assert board.abstention_rate == 0.0


def test_a_retriever_that_skips_a_query_fails_loudly() -> None:
    """Un hueco silencioso puntuaría como un cero y parecería un mal modelo."""
    golden = GoldenSet(queries=(query("q1"), query("q2")))

    with pytest.raises(ValueError, match="q2"):
        score_run(golden, {"q1": ranked("q1", "a")})


def test_the_scoreboard_serialises_deterministically() -> None:
    golden = GoldenSet(queries=(query("q1", relevant={"a": 2}),))

    first = score_run(golden, {"q1": ranked("q1", "a")})
    second = score_run(golden, {"q1": ranked("q1", "a")})

    assert first.as_dict() == second.as_dict()
    assert first.primary.recall[1] == 1.0
