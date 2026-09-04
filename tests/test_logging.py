"""Tests del logging estructurado y la propagación del request-id."""

import json
import logging
import uuid

from fastapi.testclient import TestClient

from elsa.logging import REQUEST_ID_HEADER, JsonFormatter


def test_formatter_emits_valid_json_with_extra_fields() -> None:
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="elsa.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request completed",
        args=None,
        exc_info=None,
    )
    record.method = "GET"
    record.status_code = 200

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "elsa.test"
    assert payload["message"] == "request completed"
    assert payload["method"] == "GET"
    assert payload["status_code"] == 200


def test_every_response_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert uuid.UUID(request_id)


def test_valid_incoming_request_id_is_preserved(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={REQUEST_ID_HEADER: "frontend-trace-0001"},
    )

    assert response.headers[REQUEST_ID_HEADER] == "frontend-trace-0001"


def test_malformed_incoming_request_id_is_replaced(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health/live",
        headers={REQUEST_ID_HEADER: "bad id with spaces\tand tabs"},
    )

    request_id = response.headers[REQUEST_ID_HEADER]
    assert request_id != "bad id with spaces\tand tabs"
    assert uuid.UUID(request_id)
