"""Adaptador de transcripción **simulada**.

Existe porque el piloto necesita el recorrido completo —grabar, revisar,
corregir, enviar— antes de que haya motor de voz a texto. Lo que no hace es
fingir que transcribió.

Decisión deliberada: **no inventa contenido técnico**. Un texto verosímil
sobre rodamientos y presiones, generado sin haber oído nada, es exactamente
el error que este proyecto no puede cometer: alguien lo leería, lo aprobaría
y quedaría como conocimiento del equipo. Devuelve un marcador de posición
que nadie puede confundir con habla reconocida, y deja que la persona
escriba lo que dijo.

El audio que acompaña al marcador **sí es real**: se grabó y se guardó. Lo
único ausente es el reconocimiento.
"""

from elsa.ports.transcription import TranscriptionResult

ENGINE = "simulated"

PLACEHOLDER = (
    "[TRANSCRIPCIÓN SIMULADA] Todavía no hay motor de voz a texto conectado, "
    "así que este texto no proviene de tu audio: es un marcador de posición. "
    "El audio sí se grabó y se guardó. Escribe aquí lo que dijiste para que "
    "quede como aporte."
)


class SimulatedTranscriptionAdapter:
    """Devuelve un marcador declarado como simulado. No reconoce nada."""

    async def transcribe(
        self,
        audio: bytes,
        *,
        content_type: str | None = None,
        duration_seconds: float | None = None,
    ) -> TranscriptionResult:
        return TranscriptionResult(
            text=PLACEHOLDER,
            engine=ENGINE,
            is_simulated=True,
            language="es",
        )
