"""Contrato del puerto de embeddings: documento y consulta por caminos distintos."""

import pytest

from elsa.adapters.fake_embeddings import FakeEmbeddingsAdapter
from elsa.ports.embeddings import EmbeddingConfigurationError, EmbeddingsPort

pytestmark = pytest.mark.anyio


@pytest.fixture
def port() -> EmbeddingsPort:
    return FakeEmbeddingsAdapter(dimension=8)


async def test_the_port_describes_the_vector_space_without_loading_anything(
    port: EmbeddingsPort,
) -> None:
    descriptor = port.describe()

    assert descriptor.dimension == 8 and descriptor.normalized
    assert descriptor.composition_template == "context-v1"
    assert descriptor.revision and descriptor.revision != "main"


async def test_one_vector_per_text_in_the_same_order(port: EmbeddingsPort) -> None:
    vectors = await port.embed_documents(["first text", "second text"])

    assert len(vectors) == 2
    assert all(len(vector) == port.describe().dimension for vector in vectors)
    assert vectors[0] != vectors[1]
    assert await port.embed_documents([]) == []


async def test_the_same_text_always_produces_the_same_vector(port: EmbeddingsPort) -> None:
    assert await port.embed_documents(["same text"]) == await port.embed_documents(["same text"])
    assert await port.embed_queries(["same text"]) == await port.embed_queries(["same text"])


async def test_a_passage_and_a_question_do_not_take_the_same_path(port: EmbeddingsPort) -> None:
    """La asimetría es el contrato, no un detalle del adaptador.

    Con un modelo real, pasaje y consulta llevan instrucciones distintas.
    Embeber una pregunta por el camino del pasaje mide peor **sin fallar**,
    así que el contrato exige que los dos caminos sean distinguibles.
    """
    as_document = await port.embed_documents(["par de apriete del rodamiento"])
    as_query = await port.embed_queries(["par de apriete del rodamiento"])

    assert as_document != as_query


async def test_an_impossible_dimension_is_refused(port: EmbeddingsPort) -> None:
    with pytest.raises(EmbeddingConfigurationError):
        FakeEmbeddingsAdapter(dimension=0)
