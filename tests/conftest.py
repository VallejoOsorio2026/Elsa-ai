"""Fixtures compartidas de la suite.

Los tests construyen la configuración de forma explícita (sin depender de
``.env`` ni del ambiente real de la máquina), de modo que la suite es
hermética en cualquier clon limpio.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elsa.config import Environment, Settings
from elsa.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make_test_settings(
    *,
    env: Environment = Environment.TEST,
    cors_origins: list[str] | None = None,
    log_level: str = "INFO",
    debug: bool = False,
) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        env=env,
        cors_origins=cors_origins or ["http://localhost:5173"],
        log_level=log_level,
        debug=debug,
    )


@pytest.fixture
def settings() -> Settings:
    return make_test_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)
