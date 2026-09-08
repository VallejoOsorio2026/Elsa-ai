"""El blueprint de despliegue dice lo que creemos que dice.

`render.yaml` no es documentación: es lo que Render ejecuta. Un cambio
descuidado ahí puede desplegar el ambiente equivocado, dejar de servir la
interfaz o meter un secreto en un archivo versionado, y nada de eso fallaría
hasta el día de la demostración.

Estos tests fijan las propiedades que hacen que el despliegue sea seguro y
reproducible, no su redacción.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

BLUEPRINT = Path(__file__).resolve().parents[1] / "render.yaml"


@pytest.fixture(scope="module")
def service() -> dict[str, Any]:
    data: Any = yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))
    services = data["services"]
    assert len(services) == 1, "el blueprint declara un único servicio"
    service: dict[str, Any] = dict(services[0])
    return service


def _env(service: dict[str, Any]) -> dict[str, str]:
    return {item["key"]: item["value"] for item in service["envVars"]}


def test_the_blueprint_declares_a_web_service(service: dict[str, Any]) -> None:
    assert service["type"] == "web"
    assert service["runtime"] == "python"


def test_the_demo_deploys_dev_never_test(service: dict[str, Any]) -> None:
    """DEV es lo correcto aquí, y TEST sería una mentira además de un fallo.

    La demostración se apoya en adaptadores en memoria que la configuración
    solo permite en DEV. Declarar TEST no la haría más seria: impediría
    arrancar por falta de Supabase y PostgreSQL reales.
    """
    assert _env(service)["ELSA_ENV"] == "DEV"


def test_the_demo_data_is_synthetic(service: dict[str, Any]) -> None:
    assert _env(service)["ELSA_DEMO_SEED"] == "true"


def test_the_blueprint_contains_no_secrets(service: dict[str, Any]) -> None:
    """Ningún secreto se versiona (CLAUDE.md §6).

    Se comprueba sobre el archivo entero, no solo sobre las variables: un
    secreto pegado en un comentario está igual de expuesto.
    """
    text = BLUEPRINT.read_text(encoding="utf-8").lower()
    for forbidden in (
        "elsa_database_url",
        "elsa_auth_jwt_secret",
        "elsa_bootstrap_admin_token",
        "elsa_materials_api_key",
        "service_role",
        "supabase.co",
        "postgresql://",
    ):
        assert forbidden not in text, forbidden

    # Y ninguna variable trae un valor con pinta de credencial.
    for key, value in _env(service).items():
        assert "secret" not in key.lower(), key
        assert "token" not in key.lower(), key
        assert len(value) < 200, key


def test_no_supabase_is_connected(service: dict[str, Any]) -> None:
    """La demostración no toca el proyecto real de nadie."""
    declared = set(_env(service))
    assert declared.isdisjoint(
        {
            "ELSA_MATERIALS_SUPABASE_URL",
            "ELSA_MATERIALS_API_KEY",
            "ELSA_DATABASE_URL",
            "ELSA_AUTH_PROVIDER",
            "ELSA_PERMISSIONS_BACKEND",
        }
    )


def test_the_start_command_binds_the_port_render_assigns(
    service: dict[str, Any],
) -> None:
    start = str(service["startCommand"])
    assert "--host 0.0.0.0" in start, "el proxy de Render no llega por la loopback"
    assert "--port $PORT" in start, "el puerto lo asigna Render"


def test_the_start_command_trusts_the_render_proxy(service: dict[str, Any]) -> None:
    """Sin esto uvicorn se cree en texto plano detrás del TLS de Render.

    Las redirecciones absolutas saldrían como `http://`, y un contexto no
    seguro deja al navegador sin micrófono, que es medio piloto.
    """
    assert "--forwarded-allow-ips" in str(service["startCommand"])


def test_the_build_installs_exactly_what_the_lock_pins(
    service: dict[str, Any],
) -> None:
    build = str(service["buildCommand"])
    assert "uv sync" in build
    assert "--frozen" in build, "sin --frozen el despliegue no es reproducible"
    assert "--no-dev" in build, "pytest y ruff no pintan nada en un servidor"


def test_the_health_check_answers_what_render_will_ask(
    service: dict[str, Any], client: TestClient
) -> None:
    """Se pide de verdad, que es lo que va a hacer Render.

    Comprobarlo contra una lista de rutas escrita a mano no demostraría nada:
    lo que importa es que ese path devuelva 200 sin autenticación.
    """
    path = str(service["healthCheckPath"])
    response = client.get(path)
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_the_health_check_is_liveness_not_readiness(service: dict[str, Any]) -> None:
    """Readiness informa `degraded` a propósito en esta demostración.

    Los adaptadores son fake y el motor de voz es simulado, así que
    `/health/ready` dice `degraded` con toda la razón. Usarla como sonda haría
    que Render reiniciara en bucle un servicio que funciona como se espera.
    """
    assert str(service["healthCheckPath"]).endswith("/live")


def test_the_demo_deploys_the_pilot_branch(service: dict[str, Any]) -> None:
    """`main` todavía no tiene la interfaz: desplegarla daría una API pelada."""
    assert service["branch"] not in {None, "", "main"}


def test_the_declared_origin_is_https_and_explicit(service: dict[str, Any]) -> None:
    origins = _env(service)["ELSA_CORS_ORIGINS"]
    assert origins.startswith("https://")
    assert "*" not in origins
