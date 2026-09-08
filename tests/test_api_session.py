"""El contexto de sesión dice lo justo y nada más."""

from fastapi.testclient import TestClient

from elsa.config import AuthProvider, Environment
from elsa.container import Container
from elsa.main import create_app
from tests.conftest import make_test_settings


def test_context_is_public(client: TestClient) -> None:
    """Se responde sin token: el navegador lo necesita antes de identificarse."""
    response = client.get("/api/v1/session/context")
    assert response.status_code == 200


def test_context_publishes_the_server_limits(client: TestClient) -> None:
    limits = client.get("/api/v1/session/context").json()["limits"]
    assert limits["max_attachments"] == 5
    assert limits["max_attachment_bytes"] == 50 * 1024 * 1024
    assert limits["max_audio_seconds"] == 300


def test_demo_identities_are_offered_in_dev_with_the_fake_provider(client: TestClient) -> None:
    body = client.get("/api/v1/session/context").json()
    assert body["demo_mode"] is True
    tokens = {identity["token"] for identity in body["demo_identities"]}
    assert tokens == {
        "fake-token-engineer",
        "fake-token-reviewer",
        "fake-token-other-reviewer",
        "fake-token-admin",
    }


def test_demo_identities_are_not_offered_outside_the_demo() -> None:
    """Con identidad real no hay atajo de acceso, ni siquiera en DEV."""
    settings = make_test_settings(
        env=Environment.DEV,
        auth_provider=AuthProvider.SUPABASE,
        materials_supabase_url="https://materials.example.test",
        materials_api_key="publishable-key",
    )
    app = create_app(settings, Container(settings))
    with TestClient(app) as client:
        body = client.get("/api/v1/session/context").json()
    assert body["demo_mode"] is False
    assert body["demo_identities"] == []


def test_context_never_exposes_secrets(client: TestClient) -> None:
    raw = client.get("/api/v1/session/context").text
    for forbidden in ("database_url", "secret", "bootstrap", "password"):
        assert forbidden not in raw.lower()
