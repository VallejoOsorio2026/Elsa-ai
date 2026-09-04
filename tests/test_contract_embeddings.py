"""Contrato del puerto de embeddings, verificado con el adaptador fake."""

import pytest

from elsa.adapters.fake_embeddings import FakeEmbeddingsAdapter
from elsa.ports.embeddings import EmbeddingsPort

pytestmark = pytest.mark.anyio


@pytest.fixture
def port() -> EmbeddingsPort:
    return FakeEmbeddingsAdapter(dimension=8)


def test_fake_adapter_satisfies_the_port(port: EmbeddingsPort) -> None:
    assert isinstance(port, EmbeddingsPort)


async def test_one_vector_per_text_with_declared_dimension(port: EmbeddingsPort) -> None:
    vectors = await port.embed(["first text", "second text"])

    assert len(vectors) == 2
    assert all(len(vector) == port.dimension for vector in vectors)
    assert all(-1.0 <= value <= 1.0 for vector in vectors for value in vector)


async def test_embedding_is_deterministic(port: EmbeddingsPort) -> None:
    first = await port.embed(["same text"])
    second = await port.embed(["same text"])

    assert first == second


async def test_different_texts_produce_different_vectors(port: EmbeddingsPort) -> None:
    vectors = await port.embed(["one text", "a completely different text"])

    assert vectors[0] != vectors[1]
