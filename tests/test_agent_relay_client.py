"""Cliente HTTPS del relay: clasificación, separación de credenciales y topes."""

from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from elsa.agent.relay_client import RelayClient, RelayOutcome, encode_message
from elsa.relay.auth import NODE_TOKEN_HEADER
from elsa.relay.protocol import Cancel, ErrorCode, ErrorMessage, Heartbeat, Register, Request
from tests.agent_fakes import (
    NODE_ID,
    NODE_PATH,
    NODE_TOKEN,
    RELAY_BASE,
    USER_TOKEN,
    FakeRelay,
    error_body,
    make_request,
)

pytestmark = pytest.mark.anyio

SESSION = uuid4()
OTHER_SESSION = uuid4()


@pytest.fixture
def relay() -> FakeRelay:
    return FakeRelay()


@pytest.fixture
async def client(relay: FakeRelay) -> RelayClient:
    return RelayClient(
        RELAY_BASE, SecretStr(NODE_TOKEN), poll_timeout_seconds=1.0, transport=relay.transport
    )


def _heartbeat(session: UUID = SESSION) -> Heartbeat:
    return Heartbeat(node_id=NODE_ID, node_session_id=session)


async def test_register_poll_and_result_use_fixed_routes_and_node_header_only(
    client: RelayClient, relay: FakeRelay
) -> None:
    reply = await client.register(Register(node_id=NODE_ID, node_session_id=SESSION))
    assert reply.outcome is RelayOutcome.OK
    assert reply.long_poll_seconds == 25.0

    relay.push_request(make_request(SESSION))
    polled = await client.poll(_heartbeat())
    assert isinstance(polled.message, Request)
    assert polled.message.user_access_token.get_secret_value() == USER_TOKEN

    error = ErrorMessage(
        node_id=NODE_ID,
        node_session_id=SESSION,
        request_id=polled.message.request_id,
        code=ErrorCode.LOCAL_ERROR,
    )
    assert await client.send_result(encode_message(error)) is RelayOutcome.OK

    assert [r.raw_path for r in relay.requests] == [
        f"{NODE_PATH}/register",
        f"{NODE_PATH}/poll",
        f"{NODE_PATH}/result",
    ]
    for sent in relay.requests:
        assert sent.method == "POST"
        assert sent.headers[NODE_TOKEN_HEADER.lower()] == NODE_TOKEN
        assert "authorization" not in sent.headers
        assert NODE_TOKEN.encode() not in sent.body
        assert NODE_TOKEN not in sent.raw_path
        assert USER_TOKEN.encode() not in sent.body
        assert USER_TOKEN not in str(sent.headers)


@pytest.mark.parametrize(
    ("status", "body", "outcome"),
    [
        (401, error_body("unauthorized"), RelayOutcome.AUTH),
        (403, None, RelayOutcome.AUTH),
        (404, error_body("not_found"), RelayOutcome.NOT_FOUND),
        (409, error_body("stale_session"), RelayOutcome.STALE),
        (409, error_body("request_not_pending"), RelayOutcome.NOT_PENDING),
        (409, error_body("conflict"), RelayOutcome.PROTOCOL),
        (413, error_body("payload_too_large"), RelayOutcome.PROTOCOL),
        (422, error_body("validation_error"), RelayOutcome.PROTOCOL),
        (429, None, RelayOutcome.TRANSIENT),
        (500, None, RelayOutcome.TRANSIENT),
        (503, None, RelayOutcome.TRANSIENT),
        (302, None, RelayOutcome.PROTOCOL),
    ],
)
async def test_http_statuses_are_classified(
    client: RelayClient,
    relay: FakeRelay,
    status: int,
    body: dict[str, object] | None,
    outcome: RelayOutcome,
) -> None:
    headers = {"location": "https://evil.test/"} if status == 302 else None
    relay.result_steps.append(httpx.Response(status, json=body, headers=headers))
    relay.poll_steps.append(httpx.Response(status, json=body, headers=headers))
    relay.register_steps.append(httpx.Response(status, json=body, headers=headers))
    assert await client.send_result(b"{}") is outcome
    assert (await client.poll(_heartbeat())).outcome is outcome
    assert (
        await client.register(Register(node_id=NODE_ID, node_session_id=SESSION))
    ).outcome is outcome
    assert len(relay.requests) == 3  # ninguna redirección seguida


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("down"),
        httpx.ReadTimeout("slow"),
        httpx.ReadError("ack lost"),
        httpx.RemoteProtocolError("broken"),
    ],
)
async def test_transport_failures_are_transient(
    client: RelayClient, relay: FakeRelay, error: Exception
) -> None:
    relay.result_steps.append(error)
    relay.poll_steps.append(error)
    assert await client.send_result(b"{}") is RelayOutcome.TRANSIENT
    reply = await client.poll(_heartbeat())
    assert reply.outcome is RelayOutcome.TRANSIENT
    assert reply.error == type(error).__name__


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"<html>proxy error</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, content=b'{"message": "' + b"x" * (40 * 1024) + b'"}'),
    ],
)
async def test_unreadable_poll_bodies_are_transient(
    client: RelayClient, relay: FakeRelay, response: httpx.Response
) -> None:
    relay.poll_steps.append(response)
    reply = await client.poll(_heartbeat())
    assert reply.outcome is RelayOutcome.TRANSIENT
    assert reply.message is None


async def test_empty_poll_carries_no_message(client: RelayClient) -> None:
    reply = await client.poll(_heartbeat())
    assert reply.outcome is RelayOutcome.OK
    assert reply.message is None and not reply.discarded


async def test_cancel_for_the_current_session_is_delivered(
    client: RelayClient, relay: FakeRelay
) -> None:
    rid = uuid4()
    relay.push(
        Cancel(node_id=NODE_ID, node_session_id=SESSION, request_id=rid).model_dump(mode="json")
    )
    reply = await client.poll(_heartbeat())
    assert isinstance(reply.message, Cancel)
    assert reply.message.request_id == rid


@pytest.mark.parametrize(
    "message",
    [
        dict(make_request(OTHER_SESSION).to_wire_dict()),
        {**make_request(SESSION).to_wire_dict(), "node_id": "other-node"},
        {**make_request(SESSION).to_wire_dict(), "operation": "shell.exec"},
        {**make_request(SESSION).to_wire_dict(), "url": "http://evil.test/"},
        {**make_request(SESSION).to_wire_dict(), "protocol_version": "2"},
        Register(node_id=NODE_ID, node_session_id=SESSION).model_dump(mode="json"),
        {"message_type": "request"},
        "not an object",
    ],
)
async def test_messages_not_for_this_node_and_session_are_discarded(
    client: RelayClient, relay: FakeRelay, message: object
) -> None:
    relay.poll_steps.append(httpx.Response(200, json={"message": message}))
    reply = await client.poll(_heartbeat())
    assert reply.outcome is RelayOutcome.OK
    assert reply.discarded
    assert reply.message is None


async def test_transport_failure_never_exposes_exception_text(
    client: RelayClient, relay: FakeRelay
) -> None:
    relay.register_steps.append(httpx.ConnectError(f"cannot reach with {NODE_TOKEN}"))
    reply = await client.register(Register(node_id=NODE_ID, node_session_id=SESSION))
    assert reply.outcome is RelayOutcome.TRANSIENT
    assert reply.error == "ConnectError"
    assert NODE_TOKEN not in repr(reply)
