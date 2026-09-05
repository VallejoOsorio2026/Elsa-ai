"""Fixtures compartidas de la suite.

Los tests construyen la configuración y los adaptadores de forma explícita
(sin depender de ``.env``, del ambiente de la máquina ni de ningún servicio
externo), de modo que la suite es hermética en cualquier clon limpio y en CI.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elsa.adapters.fake_auth import ADMIN_ID, ENGINEER_ID, FakeAuthAdapter
from elsa.adapters.fake_materials_identity import FakeMaterialsIdentityAdapter
from elsa.adapters.memory_abuse_guard import InMemoryAbuseGuard
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.config import AuthProvider, Environment, PermissionsBackend, Settings
from elsa.container import Container
from elsa.main import create_app
from elsa.ports.abuse import AbusePolicy
from elsa.ports.materials_identity import MaterialsProfile

ENGINEER_TOKEN = "fake-token-engineer"
ADMIN_TOKEN = "fake-token-admin"


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make_test_settings(
    *,
    env: Environment = Environment.DEV,
    cors_origins: list[str] | None = None,
    log_level: str = "INFO",
    debug: bool = False,
    **overrides: object,
) -> Settings:
    values: dict[str, object] = {
        "_env_file": None,
        "env": env,
        "cors_origins": cors_origins or ["http://localhost:5173"],
        "log_level": log_level,
        "debug": debug,
        "auth_provider": AuthProvider.FAKE,
        "permissions_backend": PermissionsBackend.MEMORY,
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


@pytest.fixture
def settings() -> Settings:
    return make_test_settings()


@pytest.fixture
def permissions() -> InMemoryPermissionsRepository:
    return InMemoryPermissionsRepository()


@pytest.fixture
def auth_adapter() -> FakeAuthAdapter:
    return FakeAuthAdapter()


@pytest.fixture
def materials_identity() -> FakeMaterialsIdentityAdapter:
    """Ambos usuarios fake existen y están activos en Materiales."""
    return FakeMaterialsIdentityAdapter(
        {
            ENGINEER_ID: MaterialsProfile(
                user_id=ENGINEER_ID, display_name="Ingeniero de prueba", is_active=True
            ),
            ADMIN_ID: MaterialsProfile(
                user_id=ADMIN_ID, display_name="Administradora de prueba", is_active=True
            ),
        }
    )


@pytest.fixture
def abuse_guard() -> InMemoryAbuseGuard:
    """Límites amplios: los tests de control de abuso traen los suyos."""
    return InMemoryAbuseGuard(AbusePolicy(requests_per_minute=1000, max_concurrent_requests=0))


@pytest.fixture
def container(
    settings: Settings,
    auth_adapter: FakeAuthAdapter,
    materials_identity: FakeMaterialsIdentityAdapter,
    permissions: InMemoryPermissionsRepository,
    abuse_guard: InMemoryAbuseGuard,
) -> Container:
    return Container(
        settings,
        auth=auth_adapter,
        materials_identity=materials_identity,
        permissions=permissions,
        abuse_guard=abuse_guard,
    )


@pytest.fixture
def app(settings: Settings, container: Container) -> FastAPI:
    return create_app(settings, container)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Cliente asíncrono contra la app en memoria.

    Comparte el bucle de eventos con el test, de modo que las fixtures
    pueden preparar el estado del repositorio y luego llamar a la API.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
