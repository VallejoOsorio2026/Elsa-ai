"""Contrato del puerto de reranking, verificado con el adaptador fake."""

import pytest

from elsa.adapters.fake_reranker import FakeRerankerAdapter
from elsa.ports.reranker import RerankerPort

pytestmark = pytest.mark.anyio

DOCUMENTS = (
    "unrelated text about paper rolls",
    "bearing replacement procedure for the press section",
    "lubrication schedule",
)


@pytest.fixture
def port() -> RerankerPort:
    return FakeRerankerAdapter()


def test_fake_adapter_satisfies_the_port(port: RerankerPort) -> None:
    assert isinstance(port, RerankerPort)


async def test_results_are_sorted_by_descending_score(port: RerankerPort) -> None:
    ranked = await port.rerank("bearing replacement", DOCUMENTS)

    assert len(ranked) == len(DOCUMENTS)
    scores = [item.score for item in ranked]
    assert scores == sorted(scores, reverse=True)
    assert ranked[0].index == 1  # el documento que menciona "bearing replacement"
    assert all(0 <= item.index < len(DOCUMENTS) for item in ranked)


async def test_top_k_limits_the_results(port: RerankerPort) -> None:
    ranked = await port.rerank("bearing", DOCUMENTS, top_k=2)

    assert len(ranked) == 2


async def test_reranking_is_deterministic(port: RerankerPort) -> None:
    first = await port.rerank("lubrication schedule", DOCUMENTS)
    second = await port.rerank("lubrication schedule", DOCUMENTS)

    assert first == second
