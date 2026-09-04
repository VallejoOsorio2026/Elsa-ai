"""Tests del health check en dos niveles."""

from fastapi.testclient import TestClient

EXPECTED_DEPENDENCIES = {
    "database",
    "auth",
    "llm",
    "embeddings",
    "ocr",
    "reranker",
    "materials",
}


def test_liveness_responds_ok(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_degraded_with_unconfigured_dependencies(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["environment"] == "TEST"
    assert set(body["dependencies"]) == EXPECTED_DEPENDENCIES
    for dependency in body["dependencies"].values():
        assert dependency["status"] == "not_configured"


def test_readiness_declares_criticality_per_dependency(client: TestClient) -> None:
    body = client.get("/api/v1/health/ready").json()

    assert body["dependencies"]["database"]["critical"] is True
    assert body["dependencies"]["llm"]["critical"] is False
