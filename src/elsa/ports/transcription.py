"""Puerto de voz a texto.

El motor de transcripción es una dependencia reemplazable (CLAUDE.md §5): un
servicio local, un modelo autohospedado o un proveedor externo. La lógica de
ELSA no debe saber cuál está conectado.

El campo que importa de este puerto no es el texto: es ``is_simulated``. Un
ingeniero que lee una transcripción tiene que poder distinguir entre lo que
el sistema oyó de verdad y un marcador de posición. Por eso el resultado
lleva siempre esa bandera, la interfaz la muestra y la revisión la conserva.
Un adaptador que devuelva ``is_simulated=False`` está afirmando que
transcribió audio de verdad.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "TranscriptionResult",
    "TranscriptionPort",
    "TranscriptionUnavailableError",
]


class TranscriptionUnavailableError(Exception):
    """El motor de transcripción no está disponible."""


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """Lo que devolvió el motor, con su procedencia."""

    text: str
    engine: str
    """Identificador estable del motor que produjo el texto."""

    is_simulated: bool
    """Cierto si el texto **no** proviene de reconocer el audio.

    Nunca se calcula ni se infiere: lo declara el adaptador.
    """

    language: str | None = None


@runtime_checkable
class TranscriptionPort(Protocol):
    """Convierte audio en texto."""

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str | None = None,
        duration_seconds: float | None = None,
    ) -> TranscriptionResult:
        """Transcribe el audio. Lanza :class:`TranscriptionUnavailableError`."""
        ...
