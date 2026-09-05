"""Contrato del puerto LLM, verificado con el adaptador fake."""

import pytest

from elsa.adapters.fake_llm import FakeLLMAdapter
from elsa.ports.llm import ChatMessage, ChatResult, LLMPort

pytestmark = pytest.mark.anyio

CONVERSATION = (
    ChatMessage(role="system", content="You are ELSA."),
    ChatMessage(role="user", content="Explain the maintenance plan."),
)


@pytest.fixture
def port() -> LLMPort:
    return FakeLLMAdapter()


def test_fake_adapter_satisfies_the_port(port: LLMPort) -> None:
    assert isinstance(port, LLMPort)


async def test_completion_returns_typed_result(port: LLMPort) -> None:
    result = await port.complete(CONVERSATION)

    assert isinstance(result, ChatResult)
    assert result.model == "fake-llm"
    assert "Explain the maintenance plan." in result.content


async def test_completion_is_deterministic(port: LLMPort) -> None:
    first = await port.complete(CONVERSATION)
    second = await port.complete(CONVERSATION)

    assert first == second


async def test_max_tokens_bounds_the_output(port: LLMPort) -> None:
    result = await port.complete(CONVERSATION, max_tokens=10)

    assert len(result.content) <= 10
