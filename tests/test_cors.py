"""Tests de CORS: orígenes explícitos, sin comodines."""

from fastapi.testclient import TestClient


def test_allowed_origin_is_echoed(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unknown_origin_gets_no_cors_headers(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={"Origin": "https://evil.example.com"},
    )

    assert "access-control-allow-origin" not in response.headers
