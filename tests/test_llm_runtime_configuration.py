"""Configuración del runtime de generación y arranque de FastAPI sin modelo.

Dos garantías que este bloque tiene que poder demostrar, y que no se ven en
ninguna prueba del adaptador:

1. **FastAPI arranca sin Phi.** El modelo vive en `llama-server`, un proceso
   aparte. Si el arranque del backend dependiera de él, el sistema dejaría de
   funcionar parcialmente con el LLM caído (regla 9 de CLAUDE.md) y Render
   —donde no hay ni GPU ni pesos— no podría levantar nada.
2. **Una configuración mal declarada falla rápido y claro.** Un runtime mal
   configurado que fallara en la primera consulta sería indistinguible de un
   modelo apagado, y se diagnosticaría mal.
"""

import ast
import pathlib

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from elsa.adapters.llama_cpp_llm import LlamaCppAdapter
from elsa.config import ConfigurationError, Environment, LLMBackend, Settings, load_settings
from elsa.container import Container
from elsa.core.health import DependencyStatus
from elsa.main import create_app
from elsa.ports.llm import LLMConfigurationError, LLMUnavailableError
from tests.conftest import make_test_settings
from tests.fake_llama_server import FakeLlamaServer, closed_port_url

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------
# Por defecto no hay motor, y eso no es un fallo
# ---------------------------------------------------------------------


def test_the_runtime_is_disabled_by_default() -> None:
    """Un clon limpio no puede exigir varios gigas de pesos (regla 24)."""
    settings = make_test_settings()

    assert settings.llm_backend is LLMBackend.DISABLED
    assert Container(settings).llm is None


def test_asking_for_the_runtime_without_one_is_unavailability_not_a_crash() -> None:
    container = Container(make_test_settings())

    with pytest.raises(LLMUnavailableError) as error:
        container.require_llm()

    assert "ELSA_LLM_BACKEND" in str(error.value)


async def test_health_declares_the_runtime_as_not_configured() -> None:
    reports = {r.name: r for r in await Container(make_test_settings()).health_reports()}

    assert reports["llm"].status is DependencyStatus.NOT_CONFIGURED
    assert reports["llm"].critical is False


# ---------------------------------------------------------------------
# Con el motor configurado
# ---------------------------------------------------------------------


def test_the_settings_to_adapter_mapping_lives_in_one_place() -> None:
    """El contenedor y la herramienta comparten el mismo factory.

    Dos raíces de composición es correcto; dos copias del mapeo no: añadir un
    parámetro obligaría a tocar ambas y solo una está cubierta por pruebas.
    """
    from elsa.container import build_llm_adapter
    from elsa.tools.llm_runtime import build_llm

    settings = make_test_settings(
        llm_backend=LLMBackend.LLAMA_CPP,
        llm_base_url="http://127.0.0.1:9090",
        llm_timeout_seconds=45.0,
        llm_health_timeout_seconds=3.0,
        llm_concurrency=2,
    )

    from_container = Container(settings).llm
    from_factory = build_llm_adapter(settings)
    from_tool = build_llm(settings)

    assert isinstance(from_container, LlamaCppAdapter)
    assert from_factory is not None
    for built in (from_container, from_factory, from_tool):
        assert built.base_url == "http://127.0.0.1:9090"
        assert built.timeout_seconds == 45.0
        assert built.health_timeout_seconds == 3.0
        assert built.concurrency == 2


def test_the_container_builds_the_adapter_from_the_configuration() -> None:
    settings = make_test_settings(
        llm_backend=LLMBackend.LLAMA_CPP,
        llm_base_url="http://127.0.0.1:9090",
        llm_model="phi-4-mini-instruct",
        llm_timeout_seconds=45.0,
        llm_concurrency=2,
    )

    llm = Container(settings).llm

    assert isinstance(llm, LlamaCppAdapter)
    assert llm.base_url == "http://127.0.0.1:9090"
    assert llm.model == "phi-4-mini-instruct"
    assert llm.timeout_seconds == 45.0
    assert llm.concurrency == 2


async def test_health_is_ok_when_llama_server_answers() -> None:
    with FakeLlamaServer(health_status=200) as server:
        container = Container(
            make_test_settings(llm_backend=LLMBackend.LLAMA_CPP, llm_base_url=server.base_url)
        )
        try:
            reports = {r.name: r for r in await container.health_reports()}
        finally:
            await container.aclose()

    assert reports["llm"].status is DependencyStatus.OK
    assert reports["llm"].detail is not None
    assert "phi-4-mini-instruct" in reports["llm"].detail


async def test_health_is_down_but_not_critical_when_llama_server_is_stopped() -> None:
    """El motor caído degrada el sistema; no lo tumba."""
    container = Container(
        make_test_settings(llm_backend=LLMBackend.LLAMA_CPP, llm_base_url=closed_port_url())
    )
    try:
        reports = {r.name: r for r in await container.health_reports()}
    finally:
        await container.aclose()

    assert reports["llm"].status is DependencyStatus.DOWN
    assert reports["llm"].critical is False


# ---------------------------------------------------------------------
# Caso 16: FastAPI arranca sin cargar el modelo
# ---------------------------------------------------------------------


def test_fastapi_starts_with_the_runtime_switched_off() -> None:
    settings = make_test_settings()
    with TestClient(create_app(settings, Container(settings))) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        body = client.get("/api/v1/health/ready").json()

    assert body["dependencies"]["llm"]["status"] == "not_configured"


def test_fastapi_starts_even_though_llama_server_is_not_running() -> None:
    """El arranque no comprueba el modelo, así que no puede depender de él."""
    settings = make_test_settings(llm_backend=LLMBackend.LLAMA_CPP, llm_base_url=closed_port_url())
    with TestClient(create_app(settings, Container(settings))) as client:
        assert client.get("/api/v1/health/live").status_code == 200
        response = client.get("/api/v1/health/ready")

    # Degradado, no caído: el motor de generación no es crítico.
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["llm"]["status"] == "down"


def test_starting_the_application_sends_nothing_to_llama_server() -> None:
    """Arrancar no precalienta el modelo ni reserva una ranura.

    Una comprobación de salud en el arranque parecería inofensiva, pero
    acabaría bloqueando el despliegue mientras `llama-server` carga los pesos
    —segundos en PC1— y ataría el ciclo de vida de la aplicación al del
    modelo, que es justo lo que este bloque separa.
    """
    with FakeLlamaServer(health_status=200) as server:
        settings = make_test_settings(
            llm_backend=LLMBackend.LLAMA_CPP, llm_base_url=server.base_url
        )
        with TestClient(create_app(settings, Container(settings))):
            pass

        assert server.requests == []


def test_the_web_application_never_reads_the_gguf_path() -> None:
    """La ruta del modelo es de los scripts de arranque, no de la aplicación.

    Se comprueba por AST y no leyendo el código a ojo: el día que alguien
    añada «solo para comprobar que el archivo existe» un acceso a
    `llm_model_path` en el arranque, esta prueba lo dice antes de que el
    servicio web empiece a depender de que los pesos estén en disco.
    """
    watched = (
        "src/elsa/main.py",
        "src/elsa/container.py",
        "src/elsa/adapters/llama_cpp_llm.py",
        "src/elsa/services/grounded_generation.py",
    )
    for name in watched:
        tree = ast.parse(pathlib.Path(name).read_text(encoding="utf-8"))
        attributes = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]
        assert "llm_model_path" not in attributes, name
        assert "llama_server_path" not in attributes, name


# ---------------------------------------------------------------------
# Caso 15: una configuración inválida falla claramente
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"llm_base_url": "127.0.0.1:8080"}, "scheme"),
        ({"llm_base_url": "http://:8080"}, "host"),
        ({"llm_model": "  "}, "identifier"),
        ({"llm_timeout_seconds": 0.0}, "TIMEOUT"),
        ({"llm_health_timeout_seconds": 0.0}, "HEALTH_TIMEOUT"),
        ({"llm_temperature": -0.5}, "TEMPERATURE"),
        ({"llm_concurrency": 0}, "greater than zero"),
        ({"llm_context_tokens": 0}, "greater than zero"),
        ({"llm_max_output_tokens": 0}, "greater than zero"),
        # La ventana la comparten el prompt y la respuesta.
        ({"llm_context_tokens": 2048, "llm_max_output_tokens": 2048}, "smaller"),
    ],
)
def test_invalid_runtime_settings_are_rejected(overrides: dict[str, object], expected: str) -> None:
    with pytest.raises(ValidationError) as error:
        make_test_settings(**overrides)  # type: ignore[arg-type]

    assert expected in str(error.value)


def test_an_invalid_configuration_names_the_variable_in_the_startup_error(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El mensaje de arranque dice qué variable está mal, no «invalid input»."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ELSA_ENV=DEV\n"
        "ELSA_CORS_ORIGINS=http://localhost:5173\n"
        "ELSA_LLM_BACKEND=llama_cpp\n"
        "ELSA_LLM_BASE_URL=no-es-una-url\n",
        encoding="utf-8",
    )
    for variable in ("ELSA_LLM_BASE_URL", "ELSA_LLM_BACKEND"):
        monkeypatch.delenv(variable, raising=False)

    with pytest.raises(ConfigurationError) as error:
        load_settings(env_file)

    assert "ELSA_LLM_BASE_URL" in str(error.value)


def test_an_unknown_backend_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(llm_backend="ollama")


def test_a_non_loopback_runtime_stops_the_container() -> None:
    """Sacar `llama-server` de loopback no puede ser un descuido.

    No lleva autenticación y este bloque no se la añade: mientras solo
    escuche en 127.0.0.1 no la necesita. La configuración por sí sola no
    basta para exponerlo, hace falta declararlo.
    """
    settings = make_test_settings(
        llm_backend=LLMBackend.LLAMA_CPP, llm_base_url="http://192.168.1.40:8080"
    )

    with pytest.raises(LLMConfigurationError) as error:
        Container(settings)

    assert "loopback" in str(error.value)


def test_remote_opt_in_is_rejected_in_dev() -> None:
    with pytest.raises(ValidationError, match="ELSA_LLM_ALLOW_REMOTE"):
        make_test_settings(llm_allow_remote=True)


async def test_an_llm_adapter_that_cannot_be_probed_is_reported_as_a_double() -> None:
    """La salud pregunta por la capacidad de sondeo, no por la clase.

    Discriminar con `isinstance(..., LlamaCppAdapter)` obligaría a tocar el
    contenedor cada vez que apareciera otro runtime real —lo que ADR 0003
    quiere que no haga falta— y hasta entonces lo etiquetaría de fake.
    """
    from elsa.adapters.fake_llm import FakeLLMAdapter
    from elsa.ports.llm import ProbeableLLM

    fake = FakeLLMAdapter()
    assert not isinstance(fake, ProbeableLLM)

    reports = {r.name: r for r in await Container(make_test_settings(), llm=fake).health_reports()}

    assert reports["llm"].status is DependencyStatus.DEGRADED
    assert reports["llm"].critical is False


def test_the_mvp_defaults_are_the_ones_the_block_fixed() -> None:
    """Los valores del MVP están en la configuración, no en el código."""
    settings: Settings = make_test_settings(env=Environment.DEV)

    assert settings.llm_base_url == "http://127.0.0.1:8080"
    assert settings.llm_context_tokens == 2048
    assert settings.llm_temperature == 0.0
    assert settings.llm_concurrency == 1
    assert settings.llm_allow_remote is False
    # El sondeo de salud tiene su propio plazo, corto: `/health/ready` es
    # público y evalúa las dependencias en serie.
    assert settings.llm_health_timeout_seconds == 5.0
    assert settings.llm_health_timeout_seconds < settings.llm_timeout_seconds
    assert settings.llm_model_path is None
    assert settings.llama_server_path is None
