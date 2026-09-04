"""Tests del formato de error estándar de la API."""

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_not_found_uses_standard_error_format(client: TestClient) -> None:
    response = client.get("/api/v1/nope")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["message"]
    assert body["error"]["request_id"]


def test_validation_error_reports_safe_details(app: FastAPI) -> None:
    @app.get("/api/v1/_echo")
    async def echo(number: int) -> dict[str, int]:
        return {"number": number}

    client = TestClient(app)
    response = client.get("/api/v1/_echo", params={"number": "not-a-number"})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    fields = [detail["field"] for detail in body["error"]["details"]]
    assert "query.number" in fields


def test_unexpected_error_does_not_leak_internals(app: FastAPI) -> None:
    @app.get("/api/v1/_boom")
    async def boom() -> None:
        raise RuntimeError("sensitive internal detail")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/_boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert body["error"]["message"] == "An internal error occurred."
    assert "sensitive internal detail" not in response.text
    assert "Traceback" not in response.text
