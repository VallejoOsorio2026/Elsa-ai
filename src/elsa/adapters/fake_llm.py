"""Adaptador fake del puerto LLM (determinista, para tests)."""

from collections.abc import Sequence

from elsa.ports.llm import ChatMessage, ChatResult

MODEL_NAME = "fake-llm"


class FakeLLMAdapter:
    """Responde con un eco determinista del último mensaje del usuario.

    No genera contenido: sirve para probar el flujo sin ningún modelo real.
    """

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> ChatResult:
        last_user = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        content = f"[{MODEL_NAME}] {last_user}"[:max_tokens]
        return ChatResult(
            content=content,
            model=MODEL_NAME,
            input_tokens=sum(len(message.content.split()) for message in messages),
            output_tokens=len(content.split()),
        )
