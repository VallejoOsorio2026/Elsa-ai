"""Cliente HTTPS del relay: clasificación, separación de credenciales y topes."""

import gzip
import json
import logging
from collections.abc import Callable, Iterator
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


# ---------------------------------------------------------------------------
# Respuestas ilegibles del relay o de su proxy: clasificadas, nunca fatales
# ---------------------------------------------------------------------------


def _bad_gzip() -> httpx.Response:
    # Un stream: httpx descomprime al leer, como con una respuesta real.
    return httpx.Response(
        200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(b"not gzip at all")
    )


def _deep_json() -> httpx.Response:
    return httpx.Response(200, content=b'{"message": ' + b"[" * 30000 + b"]" * 30000 + b"}")


def _deep_error() -> httpx.Response:
    return httpx.Response(409, content=b'{"error": ' + b"[" * 3000 + b"]" * 3000 + b"}")


@pytest.mark.parametrize("make", [_bad_gzip, _deep_json, _deep_error])
async def test_unreadable_relay_replies_never_crash_the_client(
    client: RelayClient, relay: FakeRelay, make: Callable[[], httpx.Response]
) -> None:
    for steps in (relay.poll_steps, relay.result_steps, relay.register_steps):
        steps.append(make())
    poll = await client.poll(_heartbeat())
    result = await client.send_result(b"{}")
    register = await client.register(Register(node_id=NODE_ID, node_session_id=SESSION))
    if make is _deep_error:
        # Un 409 sin código legible no es stale ni not_pending: desajuste.
        assert poll.outcome is result is register.outcome is RelayOutcome.PROTOCOL
    elif make is _bad_gzip:
        # Se pidió identity: un cuerpo comprimido no se lee. El poll no trae nada;
        # register y result valen por su estado HTTP.
        assert poll.outcome is RelayOutcome.TRANSIENT and poll.message is None
        assert result is RelayOutcome.OK
        assert register.outcome is RelayOutcome.OK and register.long_poll_seconds is None
    else:
        # 200 con JSON ilegible: el poll no trae nada; register/result son 200.
        assert poll.outcome is RelayOutcome.TRANSIENT
        assert poll.message is None
        assert result is RelayOutcome.OK
        assert register.outcome is RelayOutcome.OK and register.long_poll_seconds is None


async def test_compressed_bodies_are_rejected_before_being_inflated(
    client: RelayClient, relay: FakeRelay
) -> None:
    """Una bomba gzip (64 MiB de ceros en ~64 KB) nunca se descomprime."""
    bomb = gzip.compress(b"\x00" * (64 * 1024 * 1024))
    relay.poll_steps.append(
        httpx.Response(200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(bomb))
    )
    reply = await client.poll(_heartbeat())
    assert reply.outcome is RelayOutcome.TRANSIENT
    assert reply.error == "compressed_body"
    [sent] = relay.requests
    assert sent.headers["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    "value",
    [10**400, 1e999, -5, 0, True, "25", None, [25]],
)
async def test_absurd_long_poll_values_are_ignored(
    client: RelayClient, relay: FakeRelay, value: object
) -> None:
    content = (
        b'{"status": "registered", "long_poll_seconds": '
        + (b"1e999" if value == 1e999 else json.dumps(value).encode())
        + b"}"
    )
    relay.register_steps.append(httpx.Response(200, content=content))
    reply = await client.register(Register(node_id=NODE_ID, node_session_id=SESSION))
    assert reply.outcome is RelayOutcome.OK
    assert reply.long_poll_seconds is None


# ---------------------------------------------------------------------------
# Diagnóstico de cuerpos comprimidos: distinguible y saneado
# ---------------------------------------------------------------------------


class _Records(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def relay_logs() -> Iterator[_Records]:
    handler = _Records()
    logger = logging.getLogger("elsa.agent.relay")
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _compressed(status: int, payload: bytes) -> httpx.Response:
    return httpx.Response(
        status,
        headers={"content-encoding": "gzip"},
        stream=httpx.ByteStream(gzip.compress(payload)),
    )


async def test_compressed_and_invalid_bodies_are_reported_differently(
    client: RelayClient, relay: FakeRelay
) -> None:
    relay.poll_steps.append(_compressed(200, b'{"message": null}'))
    relay.poll_steps.append(httpx.Response(200, content=b"<html>proxy error</html>"))
    compressed = await client.poll(_heartbeat())
    invalid = await client.poll(_heartbeat())
    assert (compressed.outcome, compressed.error) == (RelayOutcome.TRANSIENT, "compressed_body")
    assert (invalid.outcome, invalid.error) == (RelayOutcome.TRANSIENT, "invalid_body")
    assert compressed.http_status == invalid.http_status == 200


async def test_a_compressed_409_is_still_rejected_and_never_read_as_stale(
    client: RelayClient, relay: FakeRelay, relay_logs: _Records
) -> None:
    stale = json.dumps(error_body("stale_session")).encode()
    relay.poll_steps.append(_compressed(409, stale))
    relay.register_steps.append(_compressed(409, stale))
    relay.result_steps.append(_compressed(409, stale))

    poll = await client.poll(_heartbeat())
    register = await client.register(Register(node_id=NODE_ID, node_session_id=SESSION))
    result = await client.send_result(b"{}")

    for reply in (poll, register):
        assert reply.outcome is RelayOutcome.PROTOCOL  # no se lee: no puede ser STALE
        assert (reply.http_status, reply.error) == (409, "compressed_body")
    assert result is RelayOutcome.PROTOCOL

    rejected = [r for r in relay_logs.records if getattr(r, "event", None) == "relay_body_rejected"]
    assert [(r.endpoint, r.http_status, r.error_code) for r in rejected] == [  # type: ignore[attr-defined]
        ("poll", 409, "compressed_body"),
        ("register", 409, "compressed_body"),
        ("result", 409, "compressed_body"),
    ]
    text = " ".join(f"{r.getMessage()} {sorted(r.__dict__.items(), key=str)}" for r in rejected)
    for secret in (NODE_TOKEN, "stale_session", "content-encoding", "x-elsa-node-token"):
        assert secret not in text
