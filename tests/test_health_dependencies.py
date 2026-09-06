"""Readiness con el primer adaptador real: la autenticación es crítica."""

import httpx
import pytest
from fastapi.testclient import TestClient

from elsa.adapters.fake_materials_identity import FakeMaterialsIdentityAdapter
from elsa.adapters.jwks import JwksCache
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.adapters.supabase_auth import SupabaseJwtAuthAdapter
from elsa.container import Container
from elsa.main import create_app
from tests.conftest import make_test_settings
from tests.keys import KeyPair

JWKS_URL = "https://materials.example.test/auth/v1/.well-known/jwks.json"


def build_client(*, jwks_answers: bool) -> TestClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if not jwks_answers:
            raise httpx.ConnectError("jwks is unreachable", request=request)
        return httpx.Response(200, json={"keys": [KeyPair("key-1").jwk]})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = SupabaseJwtAuthAdapter(
        algorithms=["RS256"],
        issuer="https://materials.example.test/auth/v1",
        audience="authenticated",
        leeway_seconds=0,
        jwks=JwksCache(
            JWKS_URL,
            http_client=http,
            cache_seconds=600,
            min_refresh_seconds=0,
            timeout_seconds=1.0,
        ),
    )
    settings = make_test_settings()
    container = Container(
        settings,
        auth=auth,
        materials_identity=FakeMaterialsIdentityAdapter(),
        permissions=InMemoryPermissionsRepository(),
    )
    return TestClient(create_app(settings, container))


def test_liveness_survives_an_identity_provider_outage() -> None:
    """`/health/live` no depende de nada: no se rompe con el adaptador real."""
    client = build_client(jwks_answers=False)

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_is_down_when_the_identity_provider_is_unreachable() -> None:
    client = build_client(jwks_answers=False)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "down"
    assert body["dependencies"]["auth"]["status"] == "down"
    assert body["dependencies"]["auth"]["critical"] is True


def test_readiness_reports_auth_ok_when_the_provider_answers() -> None:
    client = build_client(jwks_answers=True)

    body = client.get("/api/v1/health/ready").json()

    assert body["dependencies"]["auth"]["status"] == "ok"


def test_readiness_is_down_without_a_permissions_store() -> None:
    client = build_client(jwks_answers=True)
    # Simula el estado previo a conectar el pool de Supabase ELSA.
    client.app.state.container.permissions = None  # type: ignore[attr-defined]

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json()["dependencies"]["database"]["status"] == "down"


@pytest.mark.anyio
async def test_protected_endpoints_are_unavailable_without_a_permissions_store() -> None:
    client = build_client(jwks_answers=True)
    client.app.state.container.permissions = None  # type: ignore[attr-defined]

    response = client.get("/api/v1/me", headers={"Authorization": "Bearer whatever"})

    # El token no es verificable con este adaptador, así que la primera
    # barrera que responde es la autenticación.
    assert response.status_code == 401
