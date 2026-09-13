"""El adaptador de llama.cpp, contra un servidor HTTP real en loopback.

Lo que se prueba aquí es la frontera: qué sale por el socket, qué se hace con
lo que vuelve, y qué se hace cuando no vuelve nada. La política de respuesta
—citas, estados, suficiencia— es del Bloque 4.4 y se prueba en sus archivos;
este adaptador no debe tener opinión sobre eso.
"""

import asyncio
import re
import uuid

import httpx
import pytest

from elsa.adapters.llama_cpp_llm import (
    CHAT_COMPLETIONS_PATH,
    LlamaCppAdapter,
    is_loopback,
)
from elsa.core.context_builder import build_context
from elsa.core.generation_policy import SYSTEM_PROMPT, build_messages
from elsa.ports.llm import (
    ChatMessage,
    LLMConfigurationError,
    LLMPort,
    LLMTimeoutError,
    LLMUnavailableError,
)
from tests.fake_llama_server import FakeLlamaServer, closed_port_url, completion_body
from tests.fixtures_evidence import make_evidence, make_evidence_set, make_provenance

pytestmark = pytest.mark.anyio

CONVERSATION = (
    ChatMessage(role="system", content=SYSTEM_PROMPT),
    ChatMessage(role="user", content="PREGUNTA\n¿Cada cuánto se lubrica?"),
)

# Un identificador con la forma que usa ELSA internamente para chunks y
# peticiones. No tiene por qué aparecer en una respuesta.
A_UUID = str(uuid.uuid4())
_UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)


def adapter(server: FakeLlamaServer, **overrides: object) -> LlamaCppAdapter:
    options: dict[str, object] = {
        "base_url": server.base_url,
        "model": "phi-4-mini-instruct",
        "timeout_seconds": 10.0,
        "max_output_tokens": 512,
        "concurrency": 1,
    }
    options.update(overrides)
    return LlamaCppAdapter(**options)  # type: ignore[arg-type]


# ---------------------------------------------------------------------
# El adaptador cumple el puerto y compone bien la petición
# ---------------------------------------------------------------------


async def test_the_adapter_satisfies_the_port() -> None:
    with FakeLlamaServer(responses=[completion_body("ok")]) as server:
        instance = adapter(server)
        try:
            assert isinstance(instance, LLMPort)
        finally:
            await instance.aclose()


async def test_the_request_reaches_the_chat_completions_endpoint() -> None:
    """Caso 1: la petición se construye con la interfaz real de llama.cpp."""
    with FakeLlamaServer(responses=[completion_body("El par es de 45 N·m [E1].")]) as server:
        instance = adapter(server, max_output_tokens=256, temperature=0.0)
        try:
            result = await instance.complete(CONVERSATION, max_tokens=1024)
        finally:
            await instance.aclose()

    request = server.last()
    assert request.path == CHAT_COMPLETIONS_PATH
    payload = request.payload
    assert payload["model"] == "phi-4-mini-instruct"
    assert payload["stream"] is False
    assert payload["temperature"] == 0.0
    # El techo del runtime gana sobre lo que pida el servicio: es el que
    # protege el tiempo de la máquina.
    assert payload["max_tokens"] == 256
    assert [m["role"] for m in request.messages()] == ["system", "user"]
    assert result.content == "El par es de 45 N·m [E1]."
    assert result.model == "phi-4-mini-instruct"
    assert result.input_tokens == 128
    assert result.output_tokens == 32


async def test_the_system_prompt_arrives_untouched() -> None:
    """Caso 2: las instrucciones del 4.4 llegan al runtime, literales.

    Si el adaptador recortara, resumiera o fusionara el mensaje de sistema,
    las reglas de fundamentación que el Bloque 4.4 da por puestas dejarían de
    estar puestas, y nada más en el camino lo notaría.
    """
    with FakeLlamaServer(responses=[completion_body("ok")]) as server:
        instance = adapter(server)
        try:
            await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()

    assert server.last().role("system") == SYSTEM_PROMPT


async def test_evidence_markers_survive_the_wire() -> None:
    """Caso 3: el contexto llega sin perder sus marcadores.

    Un marcador que se pierda en el transporte deja al modelo citando algo
    que el verificador no puede resolver, y la respuesta acaba degradada por
    un fallo de serialización.
    """
    context = build_context(
        make_evidence_set(
            *(
                make_evidence(
                    make_provenance(chunk_id=f"chunk-{n}", content=f"Pasaje número {n}."),
                    rank=n,
                )
                for n in (1, 2, 3)
            )
        )
    )
    messages = build_messages("¿Cada cuánto se lubrica el rodamiento?", context)

    with FakeLlamaServer(responses=[completion_body("Cada 500 horas [E1].")]) as server:
        instance = adapter(server)
        try:
            await instance.complete(messages)
        finally:
            await instance.aclose()

    sent = server.last().role("user")
    # Los marcadores viajan como los compone el Context Builder: abriendo y
    # cerrando la valla de cada evidencia. Comprobar las dos mitades es lo
    # que detecta un truncado a medio bloque.
    for marker in ("E1", "E2", "E3"):
        assert f"EVIDENCIA {marker} " in sent
        assert f"FIN EVIDENCIA {marker} " in sent
    assert context.render() in sent


async def test_the_answer_is_returned_verbatim_for_the_validator() -> None:
    """Caso 4 (mitad del adaptador): la cita llega intacta a quien la resuelve.

    Resolver `[E1]` contra la procedencia real es del Bloque 4.4. Lo que este
    adaptador tiene que garantizar es que no toca el texto: ni reordena, ni
    normaliza, ni «arregla» un marcador.
    """
    raw = "El apriete es 45 N·m [E2]. El intervalo es de 500 horas [E1]."
    with FakeLlamaServer(responses=[completion_body(raw)]) as server:
        instance = adapter(server)
        try:
            result = await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()

    assert result.content == raw


async def test_the_adapter_adds_no_identifier_of_its_own() -> None:
    """Caso 17: nada de UUID ni de ruido interno en una salida normal."""
    with FakeLlamaServer(responses=[completion_body("Cada 500 horas [E1].")]) as server:
        instance = adapter(server)
        try:
            result = await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()

    assert not _UUID_PATTERN.search(result.content)
    assert result.content == "Cada 500 horas [E1]."


async def test_an_identifier_coming_from_the_model_is_not_invented_by_us() -> None:
    """Si el UUID viene del modelo, viene del modelo: aquí no se filtra.

    Limpiar la salida sería reescribir lo que dijo el modelo, y entonces la
    verificación de citas estaría mirando un texto distinto del generado. El
    filtrado de lo que ve un ingeniero es del validador, no del transporte.
    """
    with FakeLlamaServer(responses=[completion_body(f"Ver {A_UUID} [E1].")]) as server:
        instance = adapter(server)
        try:
            result = await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()

    assert A_UUID in result.content


# ---------------------------------------------------------------------
# Fallos del runtime
# ---------------------------------------------------------------------


async def test_a_timeout_is_reported_as_a_timeout() -> None:
    """Caso 6: llama-server tarda de más → error de plazo, no de contenido."""
    with FakeLlamaServer(responses=[completion_body("tarde")], delay_seconds=2.0) as server:
        instance = adapter(server, timeout_seconds=0.25)
        try:
            with pytest.raises(LLMTimeoutError):
                await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()


async def test_a_stopped_server_is_reported_as_unavailable() -> None:
    """Caso 7: llama-server apagado → indisponible, controlado."""
    instance = LlamaCppAdapter(base_url=closed_port_url(), model="phi-4-mini-instruct")
    try:
        with pytest.raises(LLMUnavailableError) as error:
            await instance.complete(CONVERSATION)
    finally:
        await instance.aclose()

    assert not isinstance(error.value, LLMTimeoutError)


# ---------------------------------------------------------------------
# Qué plazo vencido es cuál
# ---------------------------------------------------------------------
#
# `httpx.ConnectTimeout` hereda de `httpx.TimeoutException`, así que un
# `except TimeoutException` puesto antes se los traga a los dos. La diferencia
# importa: vencer **estableciendo la conexión** es el runtime apagado —en
# Windows un puerto cerrado deja el SYN sin contestar en vez de rechazarlo, y
# es lo que `closed_port_url()` produce allí de forma consistente— mientras que
# vencer **esperando la respuesta** es el runtime lento. El primero se arregla
# arrancando `llama-server`; el segundo, revisando el plazo o el tamaño de la
# generación.
#
# Aquí se inyecta el cliente HTTP porque la excepción concreta la elige el
# sistema operativo: en Linux el mismo puerto cerrado da `ConnectError`, y una
# prueba que dependiera de eso comprobaría el kernel de la máquina, no la
# traducción del adaptador. Lo que se fija es el contrato: dada esta excepción
# de httpx, esta excepción del puerto.


def adapter_raising(error: Exception) -> tuple[LlamaCppAdapter, httpx.AsyncClient]:
    """Un adaptador cuyo transporte falla siempre con `error`.

    Devuelve también el cliente porque lo cierra quien lo crea: el adaptador
    solo cierra el suyo propio.
    """

    def _fail(request: httpx.Request) -> httpx.Response:
        raise error

    client = httpx.AsyncClient(transport=httpx.MockTransport(_fail))
    instance = LlamaCppAdapter(
        base_url="http://127.0.0.1:8080",
        model="phi-4-mini-instruct",
        http_client=client,
    )
    return instance, client


async def test_a_connect_timeout_is_unavailable_and_not_a_timeout() -> None:
    """El runtime apagado es indisponibilidad aunque el socket venza el plazo."""
    instance, client = adapter_raising(httpx.ConnectTimeout("timed out"))
    try:
        with pytest.raises(LLMUnavailableError) as error:
            await instance.complete(CONVERSATION)
    finally:
        await client.aclose()

    assert not isinstance(error.value, LLMTimeoutError)


async def test_a_read_timeout_is_reported_as_a_timeout() -> None:
    """Conectó y se quedó esperando: eso sí es un plazo vencido."""
    instance, client = adapter_raising(httpx.ReadTimeout("timed out"))
    try:
        with pytest.raises(LLMTimeoutError):
            await instance.complete(CONVERSATION)
    finally:
        await client.aclose()


async def test_health_treats_a_connect_timeout_as_unavailable() -> None:
    """El sondeo hace la misma distinción que la generación."""
    instance, client = adapter_raising(httpx.ConnectTimeout("timed out"))
    try:
        with pytest.raises(LLMUnavailableError) as error:
            await instance.check_health()
    finally:
        await client.aclose()

    assert not isinstance(error.value, LLMTimeoutError)


async def test_health_treats_a_read_timeout_as_a_timeout() -> None:
    instance, client = adapter_raising(httpx.ReadTimeout("timed out"))
    try:
        with pytest.raises(LLMTimeoutError):
            await instance.check_health()
    finally:
        await client.aclose()


async def test_an_http_error_is_reported_as_unavailable() -> None:
    """Caso 8: un 500 del runtime es un fallo técnico, no una respuesta."""
    with FakeLlamaServer(status_code=500, raw_body='{"error":"context overflow"}') as server:
        instance = adapter(server)
        try:
            with pytest.raises(LLMUnavailableError) as error:
                await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()

    assert "500" in str(error.value)


async def test_the_upstream_error_body_never_travels_in_the_exception() -> None:
    """El cuerpo del error puede traer rutas de disco: se queda en el log."""
    body = '{"error":"failed to load C:/modelos/phi-4-mini-instruct-Q4_K_M.gguf"}'
    with FakeLlamaServer(status_code=500, raw_body=body) as server:
        instance = adapter(server)
        try:
            with pytest.raises(LLMUnavailableError) as error:
                await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()

    assert "gguf" not in str(error.value)
    assert "C:/modelos" not in str(error.value)


async def test_the_upstream_error_body_never_reaches_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Del error del runtime se registran etiquetas, no su texto.

    Los errores de `llama-server` traen a menudo la ruta del GGUF y, en fallos
    de validación del prompt, fragmentos del propio prompt — que aquí es el
    bloque de evidencias de planta. `docs/security.md` prohíbe ese contenido
    en el log de aplicación, y el log de aplicación es justo donde acabaría.
    """
    body = (
        '{"error":{"code":500,"type":"server_error",'
        '"message":"failed to load C:/modelos/phi.gguf: el rodamiento SAP-4471"}}'
    )
    with caplog.at_level("ERROR"), FakeLlamaServer(status_code=500, raw_body=body) as server:
        instance = adapter(server)
        try:
            with pytest.raises(LLMUnavailableError):
                await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()

    record = next(r for r in caplog.records if "rejected the generation" in r.message)
    assert record.llm_status == 500  # type: ignore[attr-defined]
    # El tipo y el código sí: son etiquetas cerradas y sirven para diagnosticar.
    assert record.llm_error_type == "server_error"  # type: ignore[attr-defined]
    assert record.llm_error_code == "500"  # type: ignore[attr-defined]
    # El mensaje libre, no.
    assert not hasattr(record, "llm_body")
    logged = str(record.__dict__)
    assert "SAP-4471" not in logged
    assert "C:/modelos" not in logged


async def test_a_body_that_is_not_json_is_reported_as_unavailable() -> None:
    with FakeLlamaServer(raw_body="<html>proxy error</html>") as server:
        instance = adapter(server)
        try:
            with pytest.raises(LLMUnavailableError):
                await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()


async def test_a_response_without_choices_is_reported_as_unavailable() -> None:
    """Una respuesta sin `choices` es un contrato roto, no una respuesta vacía."""
    with FakeLlamaServer(responses=[{"model": "phi", "usage": {}}]) as server:
        instance = adapter(server)
        try:
            with pytest.raises(LLMUnavailableError):
                await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()


async def test_an_empty_content_is_delivered_as_empty() -> None:
    """Caso 9: el adaptador no decide qué significa una salida vacía.

    La entrega vacía y el servicio la convierte en ERROR con su propio
    código. Fabricar aquí un texto de disculpa sería inventar una respuesta.
    """
    with FakeLlamaServer(responses=[completion_body("")]) as server:
        instance = adapter(server)
        try:
            result = await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()

    assert result.content == ""


async def test_a_null_content_is_treated_as_empty() -> None:
    body = completion_body("")
    body["choices"][0]["message"]["content"] = None
    with FakeLlamaServer(responses=[body]) as server:
        instance = adapter(server)
        try:
            result = await instance.complete(CONVERSATION)
        finally:
            await instance.aclose()

    assert result.content == ""


# ---------------------------------------------------------------------
# Salud
# ---------------------------------------------------------------------


async def test_health_passes_when_the_model_is_loaded() -> None:
    with FakeLlamaServer(health_status=200) as server:
        instance = adapter(server)
        try:
            await instance.check_health()
        finally:
            await instance.aclose()


async def test_health_fails_while_the_model_is_still_loading() -> None:
    with FakeLlamaServer(health_status=503) as server:
        instance = adapter(server)
        try:
            with pytest.raises(LLMUnavailableError) as error:
                await instance.check_health()
        finally:
            await instance.aclose()

    assert "loading" in str(error.value)


async def test_the_health_probe_has_its_own_short_deadline() -> None:
    """`/health/ready` es público y en serie: no puede heredar 120 s.

    Con el plazo de generación, un runtime colgado —no caído, que rechaza al
    instante— retendría un worker dos minutos por petición anónima, y encima
    por una dependencia declarada no crítica.
    """
    with FakeLlamaServer(delay_seconds=2.0) as server:
        instance = adapter(server, timeout_seconds=120.0, health_timeout_seconds=0.25)
        assert instance.timeout_seconds == 120.0
        assert instance.health_timeout_seconds == 0.25
        try:
            # El servidor falso retrasa las generaciones, no `/health`, así que
            # lo que se comprueba aquí es que los dos plazos son distintos y
            # que el sondeo usa el suyo.
            await instance.check_health()
        finally:
            await instance.aclose()


def test_a_health_deadline_of_zero_is_refused() -> None:
    with pytest.raises(LLMConfigurationError) as error:
        LlamaCppAdapter(
            base_url="http://127.0.0.1:8080",
            model="phi-4-mini-instruct",
            health_timeout_seconds=0.0,
        )

    assert "health probe timeout" in str(error.value)


async def test_health_fails_when_nobody_listens() -> None:
    instance = LlamaCppAdapter(base_url=closed_port_url(), model="phi-4-mini-instruct")
    try:
        with pytest.raises(LLMUnavailableError):
            await instance.check_health()
    finally:
        await instance.aclose()


# ---------------------------------------------------------------------
# Límites operativos
# ---------------------------------------------------------------------


async def test_concurrency_one_never_overlaps_two_generations() -> None:
    """Caso 18: la concurrencia declarada es la que llega al servidor.

    Con una sola ranura en `llama-server`, mandarle dos generaciones a la vez
    no acelera nada y reparte 4 GB de VRAM entre dos trabajos que compiten.
    El límite se comprueba en el servidor, contando cuántas peticiones
    estuvieron en vuelo a la vez, no leyendo el código del adaptador.
    """
    with FakeLlamaServer(responses=[completion_body("ok")], delay_seconds=0.2) as server:
        instance = adapter(server, concurrency=1, timeout_seconds=10.0)
        try:
            await asyncio.gather(*(instance.complete(CONVERSATION) for _ in range(4)))
        finally:
            await instance.aclose()

    assert len(server.generation_requests) == 4
    assert server.max_concurrent == 1


async def test_a_higher_concurrency_lets_generations_overlap() -> None:
    """El límite es el configurado, no un uno cableado."""
    with FakeLlamaServer(responses=[completion_body("ok")], delay_seconds=0.2) as server:
        instance = adapter(server, concurrency=3, timeout_seconds=10.0)
        try:
            await asyncio.gather(*(instance.complete(CONVERSATION) for _ in range(3)))
        finally:
            await instance.aclose()

    assert server.max_concurrent > 1


async def test_the_timeout_is_configurable() -> None:
    """Caso 19: un plazo mayor deja pasar lo que un plazo menor corta."""
    with FakeLlamaServer(responses=[completion_body("a tiempo")], delay_seconds=0.4) as server:
        strict = adapter(server, timeout_seconds=0.1)
        try:
            with pytest.raises(LLMTimeoutError):
                await strict.complete(CONVERSATION)
        finally:
            await strict.aclose()

        patient = adapter(server, timeout_seconds=10.0)
        try:
            result = await patient.complete(CONVERSATION)
        finally:
            await patient.aclose()

    assert result.content == "a tiempo"


async def test_basic_metrics_are_returned_per_call() -> None:
    """Métricas mínimas: lo que hace falta para dimensionar PC1.

    Se devuelven, no se guardan en el adaptador. Un `last_metrics` compartido
    solo sería correcto con una generación a la vez: en cuanto la concurrencia
    sube, quien lo leyera obtendría las cifras de la última que terminó
    presentadas como si fueran las suyas.
    """
    with FakeLlamaServer(responses=[completion_body("ok")]) as server:
        instance = adapter(server)
        try:
            _, metrics = await instance.complete_with_metrics(CONVERSATION)
        finally:
            await instance.aclose()

    assert metrics.duration_seconds > 0
    assert metrics.prompt_tokens == 128
    assert metrics.completion_tokens == 32
    # El servidor informa su propio ritmo de generación y se prefiere ese.
    assert metrics.tokens_per_second == 20.0


async def test_tokens_per_second_falls_back_to_measured_time() -> None:
    body = completion_body("ok")
    del body["timings"]
    with FakeLlamaServer(responses=[body]) as server:
        instance = adapter(server)
        try:
            _, metrics = await instance.complete_with_metrics(CONVERSATION)
        finally:
            await instance.aclose()

    assert metrics.tokens_per_second is not None and metrics.tokens_per_second > 0


async def test_metrics_belong_to_their_own_call() -> None:
    """Dos generaciones a la vez no se pisan las cifras.

    El servidor devuelve un uso distinto en cada respuesta; cada llamada tiene
    que recibir el suyo, no el de la que terminó última.
    """
    first = completion_body("primera")
    first["usage"] = {"prompt_tokens": 10, "completion_tokens": 11}
    second = completion_body("segunda")
    second["usage"] = {"prompt_tokens": 20, "completion_tokens": 22}

    with FakeLlamaServer(responses=[first, second], delay_seconds=0.1) as server:
        instance = adapter(server, concurrency=2, timeout_seconds=10.0)
        try:
            results = await asyncio.gather(
                instance.complete_with_metrics(CONVERSATION),
                instance.complete_with_metrics(CONVERSATION),
            )
        finally:
            await instance.aclose()

    by_content = {result.content: metrics for result, metrics in results}
    assert by_content["primera"].completion_tokens == 11
    assert by_content["segunda"].completion_tokens == 22


async def test_a_shared_http_client_is_not_closed_by_the_adapter() -> None:
    """Quien abre el cliente lo cierra. El contenedor comparte el suyo."""
    async with httpx.AsyncClient() as shared:
        with FakeLlamaServer(responses=[completion_body("ok")]) as server:
            instance = adapter(server, http_client=shared)
            await instance.complete(CONVERSATION)
            await instance.aclose()
            assert not shared.is_closed


# ---------------------------------------------------------------------
# Configuración inválida (caso 15, en la frontera del adaptador)
# ---------------------------------------------------------------------


def test_a_non_loopback_url_is_refused_by_default() -> None:
    """`llama-server` no lleva autenticación: sacarlo de loopback se declara."""
    with pytest.raises(LLMConfigurationError) as error:
        LlamaCppAdapter(base_url="http://10.0.0.5:8080", model="phi-4-mini-instruct")

    assert "loopback" in str(error.value)


def test_listening_on_every_interface_is_not_loopback() -> None:
    """`0.0.0.0` no es «esta máquina»: es «todas las interfaces»."""
    assert not is_loopback("http://0.0.0.0:8080")
    with pytest.raises(LLMConfigurationError):
        LlamaCppAdapter(base_url="http://0.0.0.0:8080", model="phi-4-mini-instruct")


def test_remote_opt_in_is_rejected_even_in_the_adapter() -> None:
    with pytest.raises(LLMConfigurationError, match="loopback"):
        LlamaCppAdapter(model="phi", base_url="http://192.168.1.40:8080", allow_remote=True)


def test_loopback_names_are_recognised() -> None:
    assert is_loopback("http://127.0.0.1:8080")
    assert is_loopback("http://localhost:8080")
    assert is_loopback("http://[::1]:8080")
    assert not is_loopback("http://192.168.1.40:8080")


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"base_url": "127.0.0.1:8080"}, "scheme"),
        ({"model": "   "}, "identifier"),
        ({"timeout_seconds": 0.0}, "timeout"),
        ({"max_output_tokens": 0}, "output tokens"),
        ({"temperature": -1.0}, "temperature"),
        ({"concurrency": 0}, "concurrency"),
    ],
)
def test_invalid_runtime_options_fail_loudly(overrides: dict[str, object], expected: str) -> None:
    """Caso 15: mal configurado falla al construir, no al generar.

    Un runtime mal declarado que fallara en la primera consulta sería
    indistinguible de un modelo caído, y se diagnosticaría mal.
    """
    options: dict[str, object] = {
        "base_url": "http://127.0.0.1:8080",
        "model": "phi-4-mini-instruct",
    }
    options.update(overrides)
    with pytest.raises(LLMConfigurationError) as error:
        LlamaCppAdapter(**options)  # type: ignore[arg-type]

    assert expected in str(error.value)


async def test_environment_proxy_never_receives_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    with FakeLlamaServer(responses=[completion_body("local")]) as server:
        with FakeLlamaServer(responses=[completion_body("proxy")]) as proxy:
            monkeypatch.setenv("HTTP_PROXY", proxy.base_url)
            monkeypatch.setenv("ALL_PROXY", proxy.base_url)
            monkeypatch.setenv("NO_PROXY", "")
            llm = adapter(server)
            try:
                result = await llm.complete(CONVERSATION)
            finally:
                await llm.aclose()
            assert result.content == "local"
            assert not proxy.requests


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:bad",
        "http://127.0.0.1:65536",
        "http://user:secret@127.0.0.1",
        "http://127.0.0.1?host=remote",
    ],
)
def test_invalid_origin_fails_before_http(url: str) -> None:
    with pytest.raises(LLMConfigurationError):
        LlamaCppAdapter(model="phi", base_url=url)


@pytest.mark.parametrize("field", ["timeout_seconds", "health_timeout_seconds", "temperature"])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_nonfinite_runtime_parameters_are_rejected(field: str, value: float) -> None:
    with pytest.raises(LLMConfigurationError):
        LlamaCppAdapter(model="phi", **{field: value})  # type: ignore[arg-type]
