"""Adaptador de LLM programable y determinista.

El fake de :mod:`elsa.adapters.fake_llm` hace eco del último mensaje y sirve
para comprobar que el flujo llega al proveedor. No sirve para probar el
Bloque 4.4, donde lo que hay que ejercitar es qué pasa cuando el modelo cita
bien, cuando cita una evidencia que no existe, cuando se declara insuficiente,
cuando devuelve vacío, cuando tarda de más y cuando se cae.

Este adaptador permite guionizar exactamente eso, sin red y sin modelo, y
además **registra lo que se le mandó**: así una prueba puede afirmar que no se
le llamó, o que lo que recibió no contiene el pasaje de un activo ajeno. Sin
ese registro, «la evidencia prohibida nunca llega al modelo» sería una
afirmación sin forma de comprobarse.
"""

import asyncio
from collections.abc import Sequence

from elsa.ports.llm import ChatMessage, ChatResult, LLMUnavailableError

__all__ = ["MODEL_NAME", "ScriptedLLMAdapter"]

MODEL_NAME = "scripted-llm"


class ScriptedLLMAdapter:
    """Devuelve respuestas preparadas, en orden, y guarda cada llamada."""

    def __init__(
        self,
        *responses: str,
        raises: BaseException | None = None,
        delay_seconds: float = 0.0,
        model: str = MODEL_NAME,
    ) -> None:
        self._responses = list(responses)
        self._raises = raises
        self._delay_seconds = delay_seconds
        self._model = model
        self.calls: list[tuple[ChatMessage, ...]] = []

    @property
    def called(self) -> bool:
        return bool(self.calls)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def last_messages(self) -> tuple[ChatMessage, ...]:
        if not self.calls:
            raise AssertionError("the model was never called")
        return self.calls[-1]

    def last_prompt(self) -> str:
        """Todo lo que se le mandó, concatenado. Para buscar en él."""
        return "\n".join(message.content for message in self.last_messages())

    def system_prompt(self) -> str:
        return "\n".join(m.content for m in self.last_messages() if m.role == "system")

    def user_prompt(self) -> str:
        return "\n".join(m.content for m in self.last_messages() if m.role == "user")

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> ChatResult:
        self.calls.append(tuple(messages))
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        if self._raises is not None:
            raise self._raises
        content = self._responses.pop(0) if self._responses else ""
        return ChatResult(
            content=content,
            model=self._model,
            input_tokens=sum(len(message.content.split()) for message in messages),
            output_tokens=len(content.split()),
        )


def unavailable(reason: str = "provider down") -> ScriptedLLMAdapter:
    """Un proveedor caído, para probar que se reporta como error técnico."""
    return ScriptedLLMAdapter(raises=LLMUnavailableError(reason))
