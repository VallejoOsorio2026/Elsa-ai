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


class LLMTimeoutError(LLMUnavailableError):
    """El modelo no respondió dentro del plazo.

    Es una forma de indisponibilidad —por eso hereda de
    :class:`LLMUnavailableError` y quien solo distinga «disponible o no»
    sigue funcionando sin cambios— pero se declara aparte porque no se
    diagnostica igual: un proveedor caído se arregla arrancándolo y un
    proveedor lento se arregla con más plazo, menos contexto o menos
    tokens de salida. Confundirlos en el rastro de auditoría borra justo
    el dato que distingue esas dos decisiones.
    """


class LLMConfigurationError(ValueError):
    """El runtime de generación está mal declarado.

    Se lanza **antes** de intentar hablar con nadie. Una URL inventada, un
    plazo negativo o una concurrencia de cero no son una indisponibilidad:
    son un error de configuración, y tienen que fallar de forma ruidosa en
    vez de disfrazarse de «el modelo no responde».
    """


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
