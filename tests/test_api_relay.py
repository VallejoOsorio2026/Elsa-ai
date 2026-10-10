"""Endpoints de nodo del relay Render–PC1 (D2.2) con un nodo simulado.

Sin red real: ``httpx.ASGITransport`` contra la app en memoria.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from elsa.main import create_app
from elsa.relay.auth import NODE_TOKEN_HEADER, hash_node_token
from elsa.relay.protocol import AskParams, ErrorCode, Response
from elsa.relay.service import RelayService
from elsa.relay.store import RelayFailure
from tests.conftest import make_test_settings

pytestmark = pytest.mark.anyio

NODE_ID = "pc1-pilot"
NODE_TOKEN = "synthetic-node-token"
PREVIOUS_NODE_TOKEN = "synthetic-node-token-old"
USER_TOKEN = "synthetic-user-access-token"
QUESTION = "synthetic-sensitive-question"
RESULT_TEXT = "synthetic-sensitive-result"
SESSION_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SESSION_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

BASE = "/api/v1/relay/node"
AUTH = {NODE_TOKEN_HEADER: NODE_TOKEN}


def _app(**overrides: Any) -> FastAPI:
    values: dict[str, Any] = {
        "relay_enabled": True,
        "relay_node_id": NODE_ID,
        "relay_node_token_sha256": SecretStr(hash_node_token(NODE_TOKEN)),
        "relay_node_token_sha256_previous": SecretStr(hash_node_token(PREVIOUS_NODE_TOKEN)),
        "relay_node_ttl_seconds": 5.0,
        "relay_long_poll_seconds": 0.05,
        "relay_request_ttl_seconds": 5.0,
    }
    values.update(overrides)
    return create_app(make_test_settings(**values))


@pytest.fixture
def app() -> FastAPI:
    return _app()


@pytest.fixture
def relay(app: FastAPI) -> RelayService:
    service = app.state.container.relay
    assert isinstance(service, RelayService)
    return service


@pytest.fixture
async def node(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


def _msg(message_type: str, session: str = SESSION_A, **extra: Any) -> dict[str, Any]:
    return {
        "protocol_version": "1",
        "message_type": message_type,
        "node_id": NODE_ID,
        "node_session_id": session,
        **extra,
    }


async def _register(node: httpx.AsyncClient, session: str = SESSION_A) -> httpx.Response:
    return await node.post(f"{BASE}/register", json=_msg("register", session), headers=AUTH)


async def _submit(app: FastAPI, question: str = QUESTION) -> "asyncio.Task[Any]":
    service: RelayService = app.state.container.relay
    task = asyncio.create_task(
        service.submit(
            AskParams(domain="mantenimiento", asset="tampella", question=question),
            SecretStr(USER_TOKEN),
        )
    )
    for _ in range(5):
        await asyncio.sleep(0)
    return task


# ---------------------------------------------------------------------------
# Flujo completo
# ---------------------------------------------------------------------------


async def test_full_flow_through_http_with_a_simulated_node(
    node: httpx.AsyncClient, app: FastAPI, relay: RelayService
) -> None:
    registered = await _register(node)
    assert registered.status_code == 200
    assert registered.json() == {
        "status": "registered",
        "long_poll_seconds": 0.05,
        "node_ttl_seconds": 5.0,
    }

    task = await _submit(app)
    polled = await node.post(f"{BASE}/poll", json=_msg("heartbeat"), headers=AUTH)
    assert polled.status_code == 200
    request = polled.json()["message"]
    assert request["message_type"] == "request"
    assert request["operation"] == "assistant.ask"
    assert request["node_session_id"] == SESSION_A
    assert request["user_access_token"] == USER_TOKEN  # llega al nodo por el cable
    assert request["params"]["question"] == QUESTION
    # El mensaje no lleva nada que permita dirigir la llamada a otro sitio.
    assert not {"url", "host", "port", "method", "headers", "path"} & set(request)

    result = await node.post(
        f"{BASE}/result",
        json=_msg("response", request_id=request["request_id"], result={"message": RESULT_TEXT}),
        headers=AUTH,
    )
    assert result.status_code == 200
    assert result.json() == {"accepted": True}

    outcome = await asyncio.wait_for(task, 1)
    assert isinstance(outcome, Response)
    assert outcome.result == {"message": RESULT_TEXT}
    assert relay.store.pending_count == 0


async def test_poll_returns_an_empty_message_when_there_is_no_work(
    node: httpx.AsyncClient,
) -> None:
    await _register(node)
    polled = await node.post(f"{BASE}/poll", json=_msg("heartbeat"), headers=AUTH)
    assert polled.status_code == 200
    assert polled.json() == {"message": None}


async def test_node_error_reaches_the_submitter(node: httpx.AsyncClient, app: FastAPI) -> None:
    await _register(node)
    task = await _submit(app)
    polled = await node.post(f"{BASE}/poll", json=_msg("heartbeat"), headers=AUTH)
    rid = polled.json()["message"]["request_id"]

    sent = await node.post(
        f"{BASE}/result",
        json=_msg("error", request_id=rid, code="LOCAL_ERROR", detail="synthetic failure"),
        headers=AUTH,
    )

    assert sent.status_code == 200
    assert await asyncio.wait_for(task, 1) == RelayFailure(
        ErrorCode.LOCAL_ERROR, "synthetic failure"
    )


async def test_previous_token_is_accepted_during_rotation(node: httpx.AsyncClient) -> None:
    response = await node.post(
        f"{BASE}/register",
        json=_msg("register"),
        headers={NODE_TOKEN_HEADER: PREVIOUS_NODE_TOKEN},
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------


async def test_authentication_failures_are_indistinguishable_and_leak_nothing(
    node: httpx.AsyncClient,
) -> None:
    wrong_node = {**_msg("register"), "node_id": "another-node"}
    attempts = [
        await node.post(f"{BASE}/register", json=_msg("register")),
        await node.post(
            f"{BASE}/register",
            json=_msg("register"),
            headers={NODE_TOKEN_HEADER: "synthetic-node-token-wrong"},
        ),
        await node.post(f"{BASE}/register", json=wrong_node, headers=AUTH),
        await node.post(
            f"{BASE}/register",
            json=_msg("register"),
            headers={"Authorization": f"Bearer {USER_TOKEN}"},  # JWT de usuario: no vale
        ),
    ]

    bodies = []
    for response in attempts:
        assert response.status_code == 401
        body = response.json()["error"]
        body.pop("request_id", None)
        bodies.append(body)
        text = response.text
        for forbidden in (NODE_TOKEN, "wrong", hash_node_token(NODE_TOKEN), "Traceback"):
            assert forbidden not in text
    assert all(body == bodies[0] for body in bodies)


async def test_token_in_query_or_body_is_not_accepted(node: httpx.AsyncClient) -> None:
    in_query = await node.post(f"{BASE}/register?node_token={NODE_TOKEN}", json=_msg("register"))
    in_body = await node.post(
        f"{BASE}/register", json={**_msg("register"), "node_token": NODE_TOKEN}
    )
    assert in_query.status_code == 401
    assert in_body.status_code == 401


# ---------------------------------------------------------------------------
# Sesiones y correlación
# ---------------------------------------------------------------------------


async def test_poll_and_result_from_an_unknown_or_old_session_are_rejected(
    node: httpx.AsyncClient, app: FastAPI
) -> None:
    unknown = await node.post(f"{BASE}/poll", json=_msg("heartbeat"), headers=AUTH)
    assert unknown.status_code == 409
    assert unknown.json()["error"]["code"] == "stale_session"

    await _register(node, SESSION_A)
    task = await _submit(app)
    polled = await node.post(f"{BASE}/poll", json=_msg("heartbeat", SESSION_A), headers=AUTH)
    rid = polled.json()["message"]["request_id"]
    await _register(node, SESSION_B)

    late = await node.post(
        f"{BASE}/result",
        json=_msg("response", SESSION_A, request_id=rid, result={"message": RESULT_TEXT}),
        headers=AUTH,
    )
    assert late.status_code == 409
    assert late.json()["error"]["code"] == "stale_session"
    outcome = await asyncio.wait_for(task, 1)
    assert isinstance(outcome, RelayFailure)
    assert outcome.code is ErrorCode.LOCAL_UNAVAILABLE


async def test_duplicate_and_unknown_results_are_rejected(
    node: httpx.AsyncClient, app: FastAPI
) -> None:
    await _register(node)
    task = await _submit(app)
    polled = await node.post(f"{BASE}/poll", json=_msg("heartbeat"), headers=AUTH)
    rid = polled.json()["message"]["request_id"]
    body = _msg("response", request_id=rid, result={"message": RESULT_TEXT})

    first = await node.post(f"{BASE}/result", json=body, headers=AUTH)
    second = await node.post(f"{BASE}/result", json=body, headers=AUTH)
    unknown = await node.post(
        f"{BASE}/result", json={**body, "request_id": str(uuid4())}, headers=AUTH
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "request_not_pending"
    assert unknown.status_code == 409
    assert isinstance(await asyncio.wait_for(task, 1), Response)


# ---------------------------------------------------------------------------
# Protocolo y límites
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"protocol_version": "2"},
        {"unexpected_field": "x"},
        {"node_session_id": "not-a-uuid"},
        {"node_id": "bad node id/"},
        {"message_type": "heartbeat"},  # tipo equivocado para /register
    ],
)
async def test_invalid_protocol_messages_are_rejected_without_echo(
    node: httpx.AsyncClient, mutation: dict[str, Any]
) -> None:
    body = {**_msg("register"), **mutation}
    response = await node.post(f"{BASE}/register", json=body, headers=AUTH)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "details" not in error  # sin eco de campos ni valores recibidos
    assert "Traceback" not in response.text


async def test_malformed_json_is_rejected_without_echo(node: httpx.AsyncClient) -> None:
    response = await node.post(
        f"{BASE}/register",
        content=b'{"secret-looking-garbage": ',
        headers={**AUTH, "content-type": "application/json"},
    )
    assert response.status_code == 422
    assert "secret-looking-garbage" not in response.text


async def test_oversized_bodies_are_rejected(node: httpx.AsyncClient) -> None:
    await _register(node)
    big_control = await node.post(
        f"{BASE}/register",
        content=b"x" * 2048,
        headers={**AUTH, "content-type": "application/json"},
    )
    big_result = await node.post(
        f"{BASE}/result",
        content=b"x" * (300 * 1024),
        headers={**AUTH, "content-type": "application/json"},
    )
    assert big_control.status_code == 413
    assert big_result.status_code == 413


async def test_oversized_chunked_body_is_cut_off_while_streaming(
    node: httpx.AsyncClient,
) -> None:
    sent = 0

    async def endless() -> AsyncIterator[bytes]:
        nonlocal sent
        for _ in range(10_000):  # 10 MB si nadie lo cortara
            sent += 1
            yield b"x" * 1024

    response = await node.post(
        f"{BASE}/register",
        content=endless(),
        headers={**AUTH, "content-type": "application/json"},
    )

    assert response.status_code == 413
    # Se dejó de leer en cuanto superó el tope: no se consumió el flujo entero.
    assert sent < 10_000


async def test_no_generic_proxy_routes_exist(node: httpx.AsyncClient) -> None:
    for path in ("execute", "proxy", "fetch", "status"):
        response = await node.post(f"{BASE}/{path}", json={}, headers=AUTH)
        assert response.status_code in {404, 405}


# ---------------------------------------------------------------------------
# Relay deshabilitado
# ---------------------------------------------------------------------------


async def test_disabled_relay_exposes_no_routes_and_elsa_keeps_working() -> None:
    app = create_app(make_test_settings())
    assert app.state.container.relay is None
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for path in ("register", "poll", "result"):
            response = await client.post(f"{BASE}/{path}", json=_msg("register"), headers=AUTH)
            assert response.status_code == 404
            assert NODE_TOKEN not in response.text
        live = await client.get("/api/v1/health/live")
    assert live.status_code == 200


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


async def test_logs_never_contain_secrets_or_payloads(
    node: httpx.AsyncClient, app: FastAPI, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    await node.post(
        f"{BASE}/register", json=_msg("register"), headers={NODE_TOKEN_HEADER: "synthetic-bad"}
    )
    await _register(node)
    task = await _submit(app)
    polled = await node.post(f"{BASE}/poll", json=_msg("heartbeat"), headers=AUTH)
    rid = UUID(polled.json()["message"]["request_id"])
    await node.post(
        f"{BASE}/result",
        json=_msg("response", request_id=str(rid), result={"message": RESULT_TEXT}),
        headers=AUTH,
    )
    await node.post(
        f"{BASE}/result",
        json=_msg("response", request_id=str(rid), result={"message": RESULT_TEXT}),
        headers=AUTH,
    )
    await asyncio.wait_for(task, 1)

    text = "\n".join(
        f"{record.getMessage()} {sorted(record.__dict__.items(), key=str)}"
        for record in caplog.records
    )
    for secret in (
        NODE_TOKEN,
        "synthetic-bad",
        hash_node_token(NODE_TOKEN),
        USER_TOKEN,
        QUESTION,
        RESULT_TEXT,
    ):
        assert secret not in text
    events = {getattr(r, "event", None) for r in caplog.records}
    assert {"auth_failed", "node_registered", "request_dispatched", "duplicate_response"} <= events
