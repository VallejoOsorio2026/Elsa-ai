"""Adaptador del puerto LLM contra un ``llama-server`` local.

    ELSA → HTTP localhost → llama-server (proceso aparte) → Phi-4-mini GGUF

**El modelo no vive dentro de este proceso.** Python habla por HTTP con un
servidor que ya tiene los pesos cargados en memoria y en VRAM. Esa separación
no es un detalle de despliegue, es lo que hace que el bloque funcione en PC1:
cargar un GGUF cuantizado cuesta segundos y varios gigas, y hacerlo en cada
consulta —lo que pasaría al invocar ``llama-cli``— convertiría una respuesta
de dos segundos en una de treinta. También es lo que permite que FastAPI
arranque sin modelo: aquí solo se abre un cliente HTTP.

**Qué interfaz se usa y por qué.** ``llama-server`` expone dos caminos para
generar: ``/completion``, que recibe el prompt ya formateado, y
``/v1/chat/completions``, que recibe roles y aplica la plantilla de conversación
que el propio GGUF declara en sus metadatos. Se usa el segundo. Phi-4-mini
delimita sus turnos con marcas propias (``<|system|>``, ``<|user|>``,
``<|end|>``); reproducirlas a mano aquí significaría codificar el formato de un
modelo concreto dentro de ELSA y equivocarse en silencio el día que se cambie
de modelo —el servidor no avisa, simplemente genera peor—. Que la plantilla la
aplique quien lee el archivo es la única versión de esto que sobrevive a un
cambio de modelo.

Ser compatible con el esquema de OpenAI **no introduce ningún proveedor
comercial**: es el formato de petición que implementa llama.cpp, servido desde
127.0.0.1. No hay clave, no hay cuenta y no sale un byte de la máquina.

**Este adaptador no interpreta la respuesta.** No busca citas, no decide
estados y no reescribe el texto: lo entrega tal cual llegó. Quien verifica los
marcadores y decide ANSWERED / PARTIAL / NO_EVIDENCE / ERROR es
:mod:`elsa.services.grounded_generation`, igual que con cualquier otro
adaptador (ADR 0017). Lo único que este módulo traduce son los fallos de
transporte a las excepciones del puerto.
"""

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from elsa.ports.llm import (
    ChatMessage,
    ChatResult,
    LLMConfigurationError,
    LLMTimeoutError,
    LLMUnavailableError,
)

_logger = logging.getLogger(__name__)

__all__ = [
    "CHAT_COMPLETIONS_PATH",
    "DEFAULT_BASE_URL",
    "GenerationMetrics",
    "HEALTH_PATH",
    "LOOPBACK_HOSTS",
    "LlamaCppAdapter",
    "is_loopback",
]

DEFAULT_BASE_URL = "http://127.0.0.1:8080"
"""Valor por defecto de ``llama-server``: loopback, puerto 8080."""

CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
HEALTH_PATH = "/health"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]", "0:0:0:0:0:0:0:1"})
"""Nombres que significan «esta máquina y nadie más».

``0.0.0.0`` **no** está en la lista a propósito: no es una dirección de
destino, es «escucha en todas las interfaces», que es exactamente lo que este
bloque no quiere que ocurra sin una decisión explícita.
"""


def is_loopback(url: str) -> bool:
    """Si la URL apunta a la propia máquina."""
    host = (urlsplit(url).hostname or "").lower()
    return host in LOOPBACK_HOSTS


@dataclass(frozen=True, slots=True)
class GenerationMetrics:
    """Lo mínimo para dimensionar el runtime, no un sistema de observabilidad.

    Se registra por generación porque son los números que deciden si PC1
    aguanta: cuánto se tarda, cuántos tokens salen y a qué ritmo. Van al log
    y los devuelve el adaptador a quien los pida; no entran en la respuesta
    que ve un ingeniero.
    """

    duration_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None
    tokens_per_second: float | None
    queued_seconds: float
    """Cuánto se esperó por el semáforo de concurrencia antes de pedir nada."""


class LlamaCppAdapter:
    """Habla con un ``llama-server`` ya arrancado. No carga ningún modelo."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str,
        timeout_seconds: float = 120.0,
        max_output_tokens: int = 512,
        temperature: float = 0.0,
        concurrency: int = 1,
        allow_remote: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        base = base_url.strip()
        if not base.startswith(("http://", "https://")):
            raise LLMConfigurationError(f"the llama-server URL needs an http(s) scheme: {base!r}")
        base = base.rstrip("/")
        if not urlsplit(base).hostname:
            raise LLMConfigurationError(f"the llama-server URL has no host: {base!r}")
        if not allow_remote and not is_loopback(base):
            # El servidor no tiene autenticación porque no la necesita
            # mientras solo escuche en loopback. Apuntarlo a otra máquina
            # cambia esa premisa entera, así que no puede ser un descuido de
            # configuración: hay que declararlo.
            raise LLMConfigurationError(
                f"the llama-server URL must be loopback ({base!r} is not); "
                "it has no authentication, so exposing it is an explicit decision"
            )
        if not model.strip():
            raise LLMConfigurationError("the logical model identifier cannot be empty")
        if timeout_seconds <= 0:
            raise LLMConfigurationError("the llama-server timeout must be greater than zero")
        if max_output_tokens <= 0:
            raise LLMConfigurationError("the maximum output tokens must be greater than zero")
        if temperature < 0:
            raise LLMConfigurationError("the temperature cannot be negative")
        if concurrency < 1:
            raise LLMConfigurationError("the concurrency must be at least one")

        self._base_url = base
        self._model = model.strip()
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._concurrency = concurrency
        # Un semáforo, no una cola: `llama-server` sirve tantas peticiones a
        # la vez como ranuras se le pidieran al arrancar (`--parallel`), y
        # cada ranura reparte el mismo contexto. Mandarle más peticiones
        # simultáneas que ranuras no acelera nada —las encola él— y además
        # reparte la VRAM de una tarjeta de 4 GB entre generaciones que
        # compiten. Se limita aquí para que el límite sea el mismo número
        # que se le pasó al servidor y esté declarado en un sitio.
        self._gate = asyncio.Semaphore(concurrency)
        self._http = http_client or httpx.AsyncClient()
        self._owns_http = http_client is None
        self.last_metrics: GenerationMetrics | None = None

    # -----------------------------------------------------------------
    # Identidad y ciclo de vida
    # -----------------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def model(self) -> str:
        return self._model

    @property
    def concurrency(self) -> int:
        return self._concurrency

    @property
    def timeout_seconds(self) -> float:
        return self._timeout_seconds

    async def aclose(self) -> None:
        """Cierra el cliente HTTP si lo creó este adaptador."""
        if self._owns_http:
            await self._http.aclose()

    # -----------------------------------------------------------------
    # Salud
    # -----------------------------------------------------------------

    async def check_health(self) -> None:
        """Comprueba que el servidor responde y tiene el modelo cargado.

        ``llama-server`` responde 503 mientras carga los pesos, que en PC1
        tarda segundos. Un 503 es «todavía no», no «no hay nadie»: se
        distingue en el mensaje porque la acción es distinta —esperar, no
        arrancar—, pero las dos son indisponibilidad para quien pregunta.
        """
        try:
            response = await self._http.get(
                f"{self._base_url}{HEALTH_PATH}", timeout=self._timeout_seconds
            )
        except httpx.TimeoutException as error:
            raise LLMTimeoutError(f"llama-server did not answer {HEALTH_PATH} in time") from error
        except httpx.HTTPError as error:
            raise LLMUnavailableError(f"llama-server is not reachable at {self._base_url}") from (
                error
            )
        if response.status_code == 503:
            raise LLMUnavailableError("llama-server is still loading the model")
        if response.status_code != 200:
            raise LLMUnavailableError(
                f"llama-server answered {HEALTH_PATH} with HTTP {response.status_code}"
            )

    # -----------------------------------------------------------------
    # Generación
    # -----------------------------------------------------------------

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> ChatResult:
        """Genera la respuesta del asistente. No la interpreta.

        ``max_tokens`` llega del servicio; el techo del runtime se aplica
        además aquí, porque es el que protege la máquina: una salida larga
        en PC1 no es un gasto de dinero, es un minuto de espera y un
        ventilador. El menor de los dos gana.
        """
        payload = self._request_payload(messages, max_tokens=max_tokens, temperature=temperature)

        queue_started = time.monotonic()
        async with self._gate:
            started = time.monotonic()
            queued = started - queue_started
            data = await self._post(payload)
            duration = time.monotonic() - started

        content, model, prompt_tokens, completion_tokens = _read_completion(data, self._model)
        metrics = GenerationMetrics(
            duration_seconds=duration,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            tokens_per_second=_tokens_per_second(data, completion_tokens, duration),
            queued_seconds=queued,
        )
        self.last_metrics = metrics
        _logger.info(
            "llama-server generation finished",
            extra={
                "llm_model": model,
                "llm_duration_seconds": round(metrics.duration_seconds, 3),
                "llm_queued_seconds": round(metrics.queued_seconds, 3),
                "llm_prompt_tokens": metrics.prompt_tokens,
                "llm_completion_tokens": metrics.completion_tokens,
                "llm_tokens_per_second": (
                    None
                    if metrics.tokens_per_second is None
                    else round(metrics.tokens_per_second, 2)
                ),
            },
        )
        # El contenido se devuelve literal. Si viene vacío, vacío se entrega:
        # convertirlo aquí en una disculpa redactada sería inventar una
        # respuesta, y decidir qué significa una salida vacía es del
        # servicio, que es quien sabe qué evidencia había detrás.
        return ChatResult(
            content=content,
            model=model,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
        )

    def _request_payload(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        """Arma el cuerpo de la petición sin tocar el contenido de los mensajes.

        Los mensajes viajan **tal cual los compuso la política de generación**:
        el mensaje de sistema con las reglas de ELSA y el de usuario con la
        pregunta y el bloque de evidencias, con sus marcadores ``[E1]``,
        ``[E2]``. Aquí no se recorta, no se fusiona, no se reordena y no se
        añade ningún texto propio. Cualquiera de esas cosas rompería la
        separación instrucción/dato que sostiene el Bloque 4.4, o dejaría al
        modelo citando marcadores que ya no corresponden a nada.
        """
        # El puerto declara `temperature=0.0` por defecto y ELSA nunca pide
        # otra cosa: la configuración del runtime es la que manda. Un llamante
        # que pida explícitamente un valor distinto de cero lo obtiene; pedir
        # cero es pedir el comportamiento por defecto, que es el configurado
        # —y que en el MVP también es cero—.
        effective_temperature = temperature if temperature > 0 else self._temperature
        return {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "temperature": effective_temperature,
            "max_tokens": min(max_tokens, self._max_output_tokens),
            "stream": False,
            # Reutilizar la caché del prompt entre peticiones es gratis aquí:
            # el mensaje de sistema es idéntico en todas y es la parte más
            # cara de procesar. No cambia la salida, solo evita recalcularla.
            "cache_prompt": True,
        }

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Manda la petición y traduce cualquier fallo al contrato del puerto."""
        url = f"{self._base_url}{CHAT_COMPLETIONS_PATH}"
        try:
            response = await self._http.post(url, json=payload, timeout=self._timeout_seconds)
        except httpx.TimeoutException as error:
            raise LLMTimeoutError(
                f"llama-server did not answer within {self._timeout_seconds}s"
            ) from error
        except httpx.HTTPError as error:
            raise LLMUnavailableError(f"llama-server is not reachable at {self._base_url}") from (
                error
            )

        if response.status_code != 200:
            # El cuerpo del error se registra pero no viaja en la excepción:
            # puede traer la ruta del GGUF en disco y el mensaje acaba en un
            # log de aplicación (regla 14).
            _logger.error(
                "llama-server rejected the generation request",
                extra={"llm_status": response.status_code, "llm_body": response.text[:500]},
            )
            raise LLMUnavailableError(f"llama-server answered HTTP {response.status_code}")

        try:
            data = response.json()
        except ValueError as error:
            raise LLMUnavailableError("llama-server answered with a body that is not JSON") from (
                error
            )
        if not isinstance(data, dict):
            raise LLMUnavailableError("llama-server answered with an unexpected JSON shape")
        return data


def _read_completion(
    data: dict[str, Any], fallback_model: str
) -> tuple[str, str, int | None, int | None]:
    """Extrae texto, modelo y uso, o declara la respuesta inválida.

    Una respuesta sin ``choices`` utilizable no es una respuesta vacía: es un
    contrato roto. Se distinguen porque el servicio trata la primera como
    fallo técnico del proveedor y la segunda ya tiene su propio control.
    """
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMUnavailableError("llama-server answered without any choice")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMUnavailableError("llama-server answered with an unexpected choice shape")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LLMUnavailableError("llama-server answered without a message")
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        raise LLMUnavailableError("llama-server answered with a non-textual content")

    model = data.get("model")
    raw_usage = data.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    return (
        content,
        model if isinstance(model, str) and model.strip() else fallback_model,
        _as_int(usage.get("prompt_tokens")),
        _as_int(usage.get("completion_tokens")),
    )


def _tokens_per_second(
    data: dict[str, Any], completion_tokens: int | None, duration: float
) -> float | None:
    """Ritmo de generación, preferiendo el que mide el propio servidor.

    ``llama-server`` publica ``timings.predicted_per_second``, que mide solo
    la fase de generación. El cálculo de aquí incluye además la lectura del
    prompt y la red, así que da un número menor; se usa como respaldo cuando
    el servidor no informa, y no se mezclan.
    """
    timings = data.get("timings")
    if isinstance(timings, dict):
        measured = timings.get("predicted_per_second")
        if isinstance(measured, int | float) and measured > 0:
            return float(measured)
    if completion_tokens and duration > 0:
        return completion_tokens / duration
    return None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
