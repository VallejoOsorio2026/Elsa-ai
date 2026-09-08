"""Tests del health check en dos niveles."""

from fastapi.testclient import TestClient

EXPECTED_DEPENDENCIES = {
    "database",
    "auth",
    "artifact_storage",
    # El motor de voz a texto está conectado pero es simulado: aparece como
    # `degraded`, no como ausente. Ocultarlo dejaría la salud diciendo que
    # todo lo conectado funciona de verdad.
    "transcription",
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


def test_readiness_reports_degraded_with_fake_adapters(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["environment"] == "DEV"
    assert set(body["dependencies"]) == EXPECTED_DEPENDENCIES
    # Con adaptadores fake, auth y database son "degraded"; el resto sigue
    # sin adaptador real.
    assert body["dependencies"]["auth"]["status"] == "degraded"
    assert body["dependencies"]["database"]["status"] == "degraded"
    # El almacenamiento en memoria responde, pero pierde todo al reiniciar.
    assert body["dependencies"]["artifact_storage"]["status"] == "degraded"
    assert body["dependencies"]["llm"]["status"] == "not_configured"


def test_readiness_declares_criticality_per_dependency(client: TestClient) -> None:
    body = client.get("/api/v1/health/ready").json()

    assert body["dependencies"]["database"]["critical"] is True
    assert body["dependencies"]["llm"]["critical"] is False
