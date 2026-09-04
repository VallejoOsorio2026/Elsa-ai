"""Puerto del modelo de lenguaje.

El proveedor concreto (local / autohospedado) está abierto; la lógica de
negocio solo conoce esta interfaz. El LLM nunca decide permisos ni crea
hechos sin evidencia recuperada (reglas 3 y 5 de CLAUDE.md).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """Mensaje de una conversación con el modelo."""

    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class ChatResult:
    """Respuesta del modelo, con metadatos de uso cuando estén disponibles."""

    content: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMUnavailableError(Exception):
    """El modelo no está disponible; el sistema debe degradarse, no caer."""


@runtime_checkable
class LLMPort(Protocol):
    """Generación de texto a partir de una conversación."""

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> ChatResult:
        """Genera la siguiente respuesta del asistente.

        Lanza :class:`LLMUnavailableError` si el modelo no responde.
        """
        ...
