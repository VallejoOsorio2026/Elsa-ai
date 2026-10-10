"""Cliente de la ELSA local: ruta segura, autenticación y traducción de errores."""

import asyncio
from uuid import uuid4

import httpx
import pytest

from elsa.agent.local_client import (
    ElsaLocalClient,
    LocalFailure,
    LocalSuccess,
    UnsafePathSegmentError,
    build_ask_path,
)
from elsa.relay.protocol import AttachmentMeta, ErrorCode
from elsa.relay.service import MAX_RESPONSE_WIRE_BYTES
from tests.agent_fakes import (
    ATTACHMENT_NAME,
    LOCAL_BASE,
    NODE_TOKEN,
    QUESTION,
    RESULT_TEXT,
    USER_TOKEN,
    FakeLocalElsa,
    error_body,
    make_request,
)
from tests.fake_llama_server import closed_port_url

pytestmark = pytest.mark.anyio

SESSION = uuid4()


@pytest.fixture
def elsa() -> FakeLocalElsa:
    return FakeLocalElsa()


@pytest.fixture
async def client(elsa: FakeLocalElsa) -> ElsaLocalClient:
    return ElsaLocalClient(LOCAL_BASE, transport=elsa.transport)


def _deadline(seconds: float = 5.0) -> float:
    return asyncio.get_running_loop().time() + seconds


# ---------------------------------------------------------------------------
# Ruta segura
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        ".",
        "..",
        " .. ",
        "/",
        "a/b",
        "a\\b",
        "%2F",
        "a%2fb",
        "%2e%2e",
        "%2E",
        "%5c",
        "tab\tasset",
        "nul\x00",
        "del\x7f",
        "%00",
        "   ",
    ],
)
def test_unsafe_segments_are_rejected(value: str) -> None:
    with pytest.raises(UnsafePathSegmentError):
        build_ask_path(value, "tampella")
    with pytest.raises(UnsafePathSegmentError):
        build_ask_path("mantenimiento", value)


@pytest.mark.parametrize(
    ("asset", "segment"),
    [
        ("tampella", "tampella"),
        ("Prensa 2", "Prensa%202"),
        ("válvula", "v%C3%A1lvula"),
        ("a?b#c", "a%3Fb%23c"),
        ("100%", "100%25"),
        ("...", "..."),
        ("a.b", "a.b"),
    ],
)
def test_valid_assets_travel_as_a_single_encoded_segment(asset: str, segment: str) -> None:
    assert build_ask_path("mantenimiento", asset) == (
        f"/api/v1/assistant/mantenimiento/{segment}/ask"
    )


async def test_unsafe_request_never_reaches_elsa(
    client: ElsaLocalClient, elsa: FakeLocalElsa
) -> None:
    outcome = await client.ask(make_request(SESSION, asset=".."), deadline=_deadline())
    assert outcome == LocalFailure(ErrorCode.INVALID_REQUEST, "agent:invalid_path_segment")
    assert elsa.requests == []


async def test_the_request_is_exactly_assistant_ask(
    client: ElsaLocalClient, elsa: FakeLocalElsa
) -> None:
    request = make_request(
        SESSION,
        asset="Prensa 2",
        attachments=[AttachmentMeta(filename=ATTACHMENT_NAME, byte_size=10)],
    )
    outcome = await client.ask(request, deadline=_deadline())

    assert outcome == LocalSuccess({"message": RESULT_TEXT, "is_generated": False})
    [sent] = elsa.requests
    assert sent.method == "POST"
    assert sent.raw_path == "/api/v1/assistant/mantenimiento/Prensa%202/ask"
    assert sent.headers["authorization"] == f"Bearer {USER_TOKEN}"
    assert sent.headers["x-request-id"] == str(request.request_id)
    assert sent.json == {
        "question": QUESTION,
        "attachments": [{"filename": ATTACHMENT_NAME, "byte_size": 10, "content_type": None}],
    }
    # Nada del nodo llega a ELSA.
    assert "x-elsa-node-token" not in sent.headers
    assert NODE_TOKEN not in str(sent.headers) and NODE_TOKEN.encode() not in sent.body


# ---------------------------------------------------------------------------
# Traducción de resultados locales
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "code", "detail"),
    [
        (401, error_body("invalid_token"), ErrorCode.UNAUTHORIZED, "local:invalid_token"),
        (401, None, ErrorCode.UNAUTHORIZED, "local:unauthorized"),
        (
            403,
            error_body("insufficient_permissions"),
            ErrorCode.FORBIDDEN,
            "local:insufficient_permissions",
        ),
        (404, error_body("asset_not_found"), ErrorCode.INVALID_REQUEST, "local:asset_not_found"),
        (404, None, ErrorCode.INVALID_REQUEST, "local:asset_not_found"),
        (
            422,
            error_body("too_many_attachments"),
            ErrorCode.INVALID_REQUEST,
            "local:too_many_attachments",
        ),
        (400, None, ErrorCode.INVALID_REQUEST, "local:invalid_request"),
        (413, None, ErrorCode.INVALID_REQUEST, "local:invalid_request"),
        (
            429,
            error_body("too_many_requests"),
            ErrorCode.LOCAL_UNAVAILABLE,
            "local:too_many_requests",
        ),
        (
            503,
            error_body("knowledge_store_unavailable"),
            ErrorCode.LOCAL_UNAVAILABLE,
            "local:knowledge_store_unavailable",
        ),
        (500, error_body("internal_error"), ErrorCode.LOCAL_ERROR, "local:http_error"),
        (502, None, ErrorCode.LOCAL_ERROR, "local:http_error"),
        (307, None, ErrorCode.LOCAL_ERROR, "local:http_error"),
        (409, None, ErrorCode.LOCAL_ERROR, "local:http_error"),
    ],
)
async def test_local_statuses_map_to_protocol_errors(
    client: ElsaLocalClient,
    elsa: FakeLocalElsa,
    status: int,
    body: dict[str, object] | None,
    code: ErrorCode,
    detail: str,
) -> None:
    headers = {"location": "http://evil.test/"} if status == 307 else None
    elsa.steps.append(httpx.Response(status, json=body, headers=headers))
    outcome = await client.ask(make_request(SESSION), deadline=_deadline())
    assert outcome == LocalFailure(code, detail)
    assert len(elsa.requests) == 1  # sin seguir redirecciones


async def test_unknown_local_codes_and_bodies_are_never_forwarded(
    client: ElsaLocalClient, elsa: FakeLocalElsa
) -> None:
    elsa.steps.append(
        httpx.Response(403, json=error_body("secret-internal-code", "Traceback: C:\\secret"))
    )
    outcome = await client.ask(make_request(SESSION), deadline=_deadline())
    assert outcome == LocalFailure(ErrorCode.FORBIDDEN, "local:forbidden")


@pytest.mark.parametrize(
    "content",
    [b"not json", b"[1, 2]", b'"text"', b'{"value": NaN}', b'{"value": Infinity}'],
)
async def test_invalid_success_bodies_are_local_errors(
    client: ElsaLocalClient, elsa: FakeLocalElsa, content: bytes
) -> None:
    elsa.steps.append(httpx.Response(200, content=content))
    outcome = await client.ask(make_request(SESSION), deadline=_deadline())
    assert outcome == LocalFailure(ErrorCode.LOCAL_ERROR, "local:invalid_response")


async def test_oversized_local_response_is_cut_off(
    client: ElsaLocalClient, elsa: FakeLocalElsa
) -> None:
    huge = b'{"message": "' + b"x" * (MAX_RESPONSE_WIRE_BYTES + 1) + b'"}'
    elsa.steps.append(httpx.Response(200, content=huge))
    outcome = await client.ask(make_request(SESSION), deadline=_deadline())
    assert outcome == LocalFailure(ErrorCode.LOCAL_ERROR, "local:response_too_large")


async def test_connection_refused_means_elsa_is_unavailable() -> None:
    client = ElsaLocalClient(closed_port_url())
    try:
        outcome = await client.ask(make_request(SESSION), deadline=_deadline())
    finally:
        await client.aclose()
    assert outcome == LocalFailure(ErrorCode.LOCAL_UNAVAILABLE, "local:unreachable")


@pytest.mark.parametrize(
    ("error", "code", "detail"),
    [
        (httpx.ConnectError("refused"), ErrorCode.LOCAL_UNAVAILABLE, "local:unreachable"),
        (httpx.ConnectTimeout("slow"), ErrorCode.LOCAL_UNAVAILABLE, "local:unreachable"),
        (httpx.ReadTimeout("slow"), ErrorCode.TIMEOUT, "local:timeout"),
        (httpx.RemoteProtocolError("broken"), ErrorCode.LOCAL_ERROR, "local:transport_error"),
    ],
)
async def test_transport_failures_are_classified(
    client: ElsaLocalClient,
    elsa: FakeLocalElsa,
    error: Exception,
    code: ErrorCode,
    detail: str,
) -> None:
    elsa.steps.append(error)
    outcome = await client.ask(make_request(SESSION), deadline=_deadline())
    assert outcome == LocalFailure(code, detail)


async def test_the_deadline_bounds_the_local_call(
    client: ElsaLocalClient, elsa: FakeLocalElsa
) -> None:
    elsa.hold()
    outcome = await client.ask(make_request(SESSION), deadline=_deadline(0.05))
    assert outcome == LocalFailure(ErrorCode.TIMEOUT, "local:timeout")
    assert elsa.cancelled == 1  # la conexión local se cerró


async def test_cancellation_propagates_and_closes_the_local_call(
    client: ElsaLocalClient, elsa: FakeLocalElsa
) -> None:
    elsa.hold()
    task = asyncio.create_task(client.ask(make_request(SESSION), deadline=_deadline()))
    await elsa.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert elsa.cancelled == 1
