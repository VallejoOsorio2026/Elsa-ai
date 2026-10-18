"""``assistant.ask`` en modo RELAY con el relay real de D2.2 (D2.4, ADR 0033).

El nodo es un guion que llama a ``register``/``poll``/``accept_result`` del
:class:`~elsa.relay.service.RelayService` real, sin agente ni ELSA local: así
cada respuesta del nodo —buena, mala o maliciosa— es exactamente la que el test
decide. El extremo a extremo con el agente real está en
``test_assistant_relay_end_to_end.py``.

En la app pública el conocimiento, los permisos, la identidad de Materiales y el
inventario son **trampas**: cualquier uso hace fallar el test. Es la prueba de
que Render no ejecuta nada local en RELAY.

Ni Render, ni PC1, ni Materiales, ni Supabase, ni Internet.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Iterator, MutableMapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from elsa.adapters.fake_auth import FakeAuthAdapter
from elsa.api.v1 import assistant, assistant_relay
from elsa.api.v1.assistant import AskResponse
from elsa.api.v1.assistant_relay import RELAY_HOP_HEADER, public_error_for
from elsa.container import Container
from elsa.logging import JsonFormatter
from elsa.main import create_app
from elsa.ports.knowledge import KnowledgeRepositoryPort
from elsa.ports.materials import MaterialsPort
from elsa.ports.materials_identity import MaterialsIdentityPort
from elsa.ports.permissions import PermissionsRepositoryPort
from elsa.relay.auth import NODE_TOKEN_HEADER, hash_node_token
from elsa.relay.protocol import (
    Cancel,
    ErrorCode,
    ErrorMessage,
    Heartbeat,
    Register,
    Request,
    Response,
)
from elsa.relay.service import RelayService
from elsa.relay.store import RelayFailure
from tests.agent_fakes import NODE_ID, NODE_TOKEN
from tests.conftest import ENGINEER_TOKEN, auth_header, make_test_settings

pytestmark = pytest.mark.anyio

DOMAIN = "mantenimiento"
ASSET = "tampella"
ASK_PATH = f"/api/v1/assistant/{DOMAIN}/{ASSET}/ask"
QUESTION = "synthetic-relay-question-7f3a"
RESULT_MARKER = "synthetic-relay-result-91c2"
DETAIL_MARKER = "local:synthetic-internal-detail-5d0e"
ATTACHMENT_NAME = "synthetic-relay-attachment-44b1.pdf"


# ---------------------------------------------------------------------
# App pública en RELAY, con trampas en todo lo local
# ---------------------------------------------------------------------


class Tripwire:
    """Doble que falla al primer uso y deja constancia de qué se intentó."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.touched: list[str] = []

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("_"):
            raise AttributeError(attr)
        self.touched.append(attr)
        raise AssertionError(f"{self.name}.{attr} must not be used in relay mode")


@dataclass
class PublicApp:
    app: FastAPI
    relay: RelayService
    auth: FakeAuthAdapter
    tripwires: list[Tripwire]
    inventory_calls: list[str] = field(default_factory=list)

    def local_work(self) -> list[str]:
        return [f"{trap.name}.{name}" for trap in self.tripwires for name in trap.touched] + [
            f"materials_inventory({count})" for count in self.inventory_calls
        ]


def relay_settings(**overrides: object) -> Any:
    values: dict[str, Any] = {
        "assistant_execution_mode": "relay",
        "relay_enabled": True,
        "relay_node_id": NODE_ID,
        "relay_node_token_sha256": SecretStr(hash_node_token(NODE_TOKEN)),
        "relay_node_ttl_seconds": 5.0,
        "relay_long_poll_seconds": 0.05,
        "relay_request_ttl_seconds": 5.0,
    }
    values.update(overrides)
    return make_test_settings(**values)


def build_public_app(auth: FakeAuthAdapter | None = None, **overrides: object) -> PublicApp:
    """Render en RELAY: relay real y trampas en conocimiento, permisos y Materiales."""
    settings = relay_settings(**overrides)
    knowledge = Tripwire("knowledge")
    permissions = Tripwire("permissions")
    identity = Tripwire("materials_identity")
    auth = auth or FakeAuthAdapter()
    calls: list[str] = []

    def inventory(_token: str) -> MaterialsPort:
        calls.append("called")
        raise AssertionError("materials inventory must not be used in relay mode")

    container = Container(
        settings,
        auth=auth,
        materials_identity=cast(MaterialsIdentityPort, identity),
        materials_inventory=inventory,
        permissions=cast(PermissionsRepositoryPort, permissions),
        knowledge=cast(KnowledgeRepositoryPort, knowledge),
    )
    app = create_app(settings, container)
    relay = container.relay
    assert isinstance(relay, RelayService)
    return PublicApp(app, relay, auth, [knowledge, permissions, identity], calls)


@pytest.fixture
def public() -> PublicApp:
    return build_public_app()


@pytest.fixture
async def user(public: PublicApp) -> AsyncIterator[httpx.AsyncClient]:
    """Cliente que no es un navegador: sin ``Origin`` ni CORS de por medio."""
    transport = httpx.ASGITransport(app=public.app)
    async with httpx.AsyncClient(transport=transport, base_url="https://render.test") as client:
        yield client


# ---------------------------------------------------------------------
# Nodo guionizado sobre el RelayService real
# ---------------------------------------------------------------------


@dataclass
class ScriptedNode:
    relay: RelayService
    session_id: UUID = field(default_factory=uuid4)

    def register(self) -> "ScriptedNode":
        self.relay.register(Register(node_id=NODE_ID, node_session_id=self.session_id))
        return self

    async def next_message(self, timeout: float = 3.0) -> Request | Cancel:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = await self.relay.poll(
                Heartbeat(node_id=NODE_ID, node_session_id=self.session_id)
            )
            if message is not None:
                return message
        raise AssertionError("the relay never handed a message to the node")

    async def next_request(self) -> Request:
        message = await self.next_message()
        assert isinstance(message, Request)
        return message

    def respond(self, request: Request, result: dict[str, Any]) -> None:
        self.relay.accept_result(
            Response(
                node_id=NODE_ID,
                node_session_id=self.session_id,
                request_id=request.request_id,
                result=result,
            )
        )

    def fail(self, request: Request, code: ErrorCode, detail: str | None) -> None:
        self.relay.accept_result(
            ErrorMessage(
                node_id=NODE_ID,
                node_session_id=self.session_id,
                request_id=request.request_id,
                code=code,
                detail=detail,
            )
        )


@pytest.fixture
def node(public: PublicApp) -> ScriptedNode:
    return ScriptedNode(public.relay).register()


def answer(**overrides: Any) -> dict[str, Any]:
    """Una ``AskResponse`` válida del activo pedido, como la serializa ELSA local.

    ``overrides`` se aplica **después** de serializar, sin validar: así se
    construyen también las respuestas inválidas de un nodo defectuoso.
    """
    values: dict[str, Any] = {
        "asset": ASSET,
        "asset_name": "Tampella",
        "domain": DOMAIN,
        "published": True,
        "source": "BOM de Ingeniería aprobado, versión 1",
        "message": RESULT_MARKER,
        "terms": ["rodamiento"],
    }
    return AskResponse.model_validate(values).model_dump(mode="json") | overrides


def ask_body(**extra: Any) -> dict[str, Any]:
    return {"question": QUESTION, **extra}


async def ask_through(
    user: httpx.AsyncClient,
    node: ScriptedNode,
    reply: Any,
    *,
    path: str = ASK_PATH,
    body: dict[str, Any] | None = None,
) -> tuple[httpx.Response, Request]:
    """POST público; el nodo recibe el ``Request`` y contesta con ``reply(request)``."""
    post = asyncio.create_task(
        user.post(path, json=body or ask_body(), headers=auth_header(ENGINEER_TOKEN))
    )
    request = await node.next_request()
    reply(request)
    return await post, request


@dataclass
class LogLines:
    lines: list[str] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join(self.lines)

    def events(self, name: str) -> list[dict[str, Any]]:
        parsed = [json.loads(line) for line in self.lines]
        return [entry for entry in parsed if entry.get("event") == name]


class CollectJsonLines(logging.Handler):
    """Formatea cada registro al emitirse, con el ``request_id`` de su contexto."""

    def __init__(self, sink: LogLines) -> None:
        super().__init__(logging.DEBUG)
        self.setFormatter(JsonFormatter())
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.lines.append(self.format(record))


@contextmanager
def capture_elsa_logs() -> Iterator[LogLines]:
    """Líneas JSON del logger ``elsa`` tal como saldrían. Tras crear las apps:
    ``create_app`` reinicia los handlers de ese logger."""
    sink = LogLines()
    handler = CollectJsonLines(sink)
    logger = logging.getLogger("elsa")
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield sink
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


@pytest.fixture
def logs(public: PublicApp) -> Iterator[LogLines]:
    with capture_elsa_logs() as sink:
        yield sink


def assert_no_orphans(before: set[asyncio.Task[Any]]) -> None:
    current = asyncio.current_task()
    leftover = {task for task in asyncio.all_tasks() - before if task is not current}
    assert leftover == set(), f"orphan tasks: {leftover}"


_ROUTE_TASKS = frozenset({"_wait_for_disconnect", "RelayService.submit"})


def route_tasks() -> list[str]:
    """Tareas vivas de la ruta RELAY: la de ``submit`` y la del vigilante."""
    names = (getattr(task.get_coro(), "__qualname__", "") for task in asyncio.all_tasks())
    return sorted(name for name in names if name in _ROUTE_TASKS)


def assert_no_route_tasks_left() -> None:
    """Ni ``submit`` ni el vigilante siguen vivos. Sirve con un agente real
    corriendo, cuyo long poll siempre está en vuelo y no es de la ruta."""
    assert route_tasks() == []


# ---------------------------------------------------------------------
# Composición: un solo router por modo
# ---------------------------------------------------------------------


def _ask_operation(app: FastAPI) -> str:
    """Función que atiende la ruta, según el esquema OpenAPI (una sola operación)."""
    operation = app.openapi()["paths"]["/api/v1/assistant/{domain}/{asset}/ask"]["post"]
    return str(operation["operationId"])


def test_relay_mode_mounts_only_the_relay_route(public: PublicApp) -> None:
    assert _ask_operation(public.app).startswith("ask_via_relay_")


def test_local_mode_mounts_only_the_historical_route_and_needs_no_relay(app: FastAPI) -> None:
    assert _ask_operation(app).startswith("ask_api_")
    assert app.state.container.relay is None


def test_local_mode_with_the_relay_enabled_still_answers_locally() -> None:
    app = create_app(relay_settings(assistant_execution_mode="local"))

    assert _ask_operation(app).startswith("ask_api_")
    assert isinstance(app.state.container.relay, RelayService)


# ---------------------------------------------------------------------
# Camino feliz y no ejecución local
# ---------------------------------------------------------------------


async def test_the_node_answer_reaches_the_user_and_nothing_runs_here(
    public: PublicApp,
    user: httpx.AsyncClient,
    node: ScriptedNode,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the local assistant logic must not run in relay mode")

    monkeypatch.setattr(assistant, "_answer_from_published_knowledge", forbidden)
    monkeypatch.setattr(assistant, "_live_availability", forbidden)
    before = asyncio.all_tasks()
    expected = answer()

    response, request = await ask_through(
        user,
        node,
        lambda req: node.respond(req, expected),
        path="/api/v1/assistant/Mantenimiento/TAMPELLA/ask",
        body=ask_body(attachments=[{"filename": ATTACHMENT_NAME, "byte_size": 10}]),
    )

    assert response.status_code == 200
    assert response.json() == expected
    assert request.params.domain == DOMAIN
    assert request.params.asset == ASSET
    assert request.params.question == QUESTION
    assert [item.filename for item in request.params.attachments] == [ATTACHMENT_NAME]
    assert request.user_access_token.get_secret_value() == ENGINEER_TOKEN
    assert public.local_work() == []
    assert public.relay.store.pending_count == 0
    await asyncio.sleep(0)
    assert_no_orphans(before)


async def test_permissions_are_not_decided_here_a_403_only_comes_from_pc1(
    public: PublicApp, user: httpx.AsyncClient, node: ScriptedNode
) -> None:
    allowed, _ = await ask_through(user, node, lambda req: node.respond(req, answer()))
    denied, _ = await ask_through(
        user,
        node,
        lambda req: node.fail(req, ErrorCode.FORBIDDEN, "local:insufficient_permissions"),
    )

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "insufficient_permissions"
    assert public.local_work() == []


# ---------------------------------------------------------------------
# Rechazos antes de submit
# ---------------------------------------------------------------------


@pytest.fixture
def submissions(public: PublicApp, monkeypatch: pytest.MonkeyPatch) -> list[object]:
    calls: list[object] = []
    original = public.relay.submit

    async def spy(*args: Any, **kwargs: Any) -> Response | RelayFailure:
        calls.append(args)
        return await original(*args, **kwargs)

    monkeypatch.setattr(public.relay, "submit", spy)
    return calls


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, auth_header("not-a-known-token")],
    ids=["missing", "not-bearer", "invalid"],
)
async def test_an_invalid_user_is_rejected_before_submit(
    public: PublicApp,
    user: httpx.AsyncClient,
    node: ScriptedNode,
    submissions: list[object],
    headers: dict[str, str],
) -> None:
    response = await user.post(ASK_PATH, json=ask_body(), headers=headers)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert submissions == []
    assert public.relay.store.pending_count == 0


async def test_an_unavailable_identity_provider_is_a_503_before_submit(
    public: PublicApp, user: httpx.AsyncClient, node: ScriptedNode, submissions: list[object]
) -> None:
    public.auth.unavailable = True

    response = await user.post(ASK_PATH, json=ask_body(), headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "identity_provider_unavailable"
    assert submissions == []


@pytest.mark.parametrize("value", ["1", "0", "", "yes"])
@pytest.mark.parametrize("with_token", [True, False])
async def test_the_relay_hop_header_blocks_reentry_from_any_client(
    public: PublicApp,
    user: httpx.AsyncClient,
    node: ScriptedNode,
    submissions: list[object],
    value: str,
    with_token: bool,
) -> None:
    headers = {RELAY_HOP_HEADER: value}
    if with_token:
        headers.update(auth_header(ENGINEER_TOKEN))

    response = await user.post(ASK_PATH, json=ask_body(), headers=headers)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "local_node_unavailable"
    assert submissions == []
    assert public.local_work() == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/assistant/mante%20nimiento/tampella/ask",
        "/api/v1/assistant/mantenimiento/tam.pella/ask",
        "/api/v1/assistant/mantenimiento/-tampella/ask",
        f"/api/v1/assistant/mantenimiento/{'a' * 65}/ask",
    ],
)
async def test_a_malformed_scope_is_a_422_not_a_permission_decision(
    user: httpx.AsyncClient, node: ScriptedNode, submissions: list[object], path: str
) -> None:
    response = await user.post(path, json=ask_body(), headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert submissions == []


async def test_the_ask_request_limits_apply_before_submit(
    user: httpx.AsyncClient, node: ScriptedNode, submissions: list[object]
) -> None:
    response = await user.post(
        ASK_PATH, json={"question": "x" * 2001}, headers=auth_header(ENGINEER_TOKEN)
    )

    assert response.status_code == 422
    assert submissions == []


# ---------------------------------------------------------------------
# PC1 fuera de línea: fallo explícito, inmediato y sin respaldo
# ---------------------------------------------------------------------


async def test_an_offline_node_fails_at_once_without_any_fallback(
    public: PublicApp, user: httpx.AsyncClient
) -> None:
    started = time.monotonic()

    response = await user.post(ASK_PATH, json=ask_body(), headers=auth_header(ENGINEER_TOKEN))

    assert time.monotonic() - started < 1.0
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "local_node_unavailable"
    assert "ELSA local (PC1) is not available" in response.json()["error"]["message"]
    assert public.local_work() == []
    assert public.relay.store.pending_count == 0


# ---------------------------------------------------------------------
# Errores del nodo → error público, sin detail interno
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "detail", "status_code", "public_code"),
    [
        (ErrorCode.UNAUTHORIZED, "local:unauthorized", 401, "unauthorized"),
        (ErrorCode.UNAUTHORIZED, DETAIL_MARKER, 401, "unauthorized"),
        (ErrorCode.FORBIDDEN, "local:account_disabled", 403, "account_disabled"),
        (ErrorCode.FORBIDDEN, "local:insufficient_permissions", 403, "insufficient_permissions"),
        (ErrorCode.FORBIDDEN, "local:forbidden", 403, "forbidden"),
        (ErrorCode.FORBIDDEN, DETAIL_MARKER, 403, "forbidden"),
        (ErrorCode.INVALID_REQUEST, "local:asset_not_found", 404, "asset_not_found"),
        (ErrorCode.INVALID_REQUEST, "local:not_found", 404, "asset_not_found"),
        (ErrorCode.INVALID_REQUEST, "local:too_many_attachments", 422, "too_many_attachments"),
        (ErrorCode.INVALID_REQUEST, "local:attachments_too_large", 422, "attachments_too_large"),
        (ErrorCode.INVALID_REQUEST, "agent:invalid_path_segment", 422, "validation_error"),
        (ErrorCode.INVALID_REQUEST, DETAIL_MARKER, 422, "validation_error"),
        (ErrorCode.LOCAL_UNAVAILABLE, "local:too_many_requests", 429, "too_many_requests"),
        (
            ErrorCode.LOCAL_UNAVAILABLE,
            "local:identity_provider_unavailable",
            503,
            "identity_provider_unavailable",
        ),
        (
            ErrorCode.LOCAL_UNAVAILABLE,
            "local:knowledge_store_unavailable",
            503,
            "knowledge_store_unavailable",
        ),
        (ErrorCode.LOCAL_UNAVAILABLE, "agent:busy", 503, "local_node_unavailable"),
        (ErrorCode.LOCAL_UNAVAILABLE, DETAIL_MARKER, 503, "local_node_unavailable"),
        (ErrorCode.TIMEOUT, "local:timeout", 503, "local_node_timeout"),
        (ErrorCode.LOCAL_ERROR, DETAIL_MARKER, 503, "local_node_error"),
        (ErrorCode.PROTOCOL_ERROR, DETAIL_MARKER, 503, "local_node_error"),
        (ErrorCode.DUPLICATE_REQUEST, None, 503, "local_node_error"),
        (ErrorCode.CANCELLED, None, 503, "request_cancelled"),
    ],
)
async def test_node_errors_map_to_public_errors_without_the_internal_detail(
    user: httpx.AsyncClient,
    node: ScriptedNode,
    logs: LogLines,
    code: ErrorCode,
    detail: str | None,
    status_code: int,
    public_code: str,
) -> None:
    response, _ = await ask_through(user, node, lambda req: node.fail(req, code, detail))

    assert response.status_code == status_code
    error = response.json()["error"]
    assert error["code"] == public_code
    assert set(error) == {"code", "message", "request_id"}
    if detail is not None:
        assert detail not in response.text
        assert detail not in logs.text()
    if status_code == 401:
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_every_error_code_has_a_public_translation() -> None:
    for code in ErrorCode:
        error = public_error_for(RelayFailure(code, DETAIL_MARKER))
        assert DETAIL_MARKER not in error.message
        assert error.code


# ---------------------------------------------------------------------
# Respuesta del nodo inválida o ajena: no cruza al usuario
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "result",
    [
        {"unexpected": RESULT_MARKER},
        answer(asset="otro-activo"),
        answer(domain="otro-dominio"),
        answer(published="true"),
        answer(components=RESULT_MARKER),
        answer(failure_modes=[{"rpn": "9", "failure_mode": RESULT_MARKER}]),
        answer(message=None),
    ],
    ids=[
        "foreign-shape",
        "other-asset",
        "other-domain",
        "coerced-bool",
        "wrong-list",
        "coerced-int",
        "missing-message",
    ],
)
async def test_an_invalid_node_result_never_reaches_the_user(
    public: PublicApp,
    user: httpx.AsyncClient,
    node: ScriptedNode,
    logs: LogLines,
    result: dict[str, Any],
) -> None:
    response, _ = await ask_through(user, node, lambda req: node.respond(req, result))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "local_node_invalid_response"
    assert RESULT_MARKER not in response.text
    assert RESULT_MARKER not in logs.text()
    assert public.relay.store.pending_count == 0


async def test_extra_fields_from_the_node_are_dropped_not_forwarded(
    user: httpx.AsyncClient, node: ScriptedNode
) -> None:
    """``AskResponse`` ignora campos extra: se descartan al validar y no cruzan.

    Se acepta así a propósito (no se cambia ``AskResponse``): tolera un desfase de
    versión entre PC1 y Render sin dejar pasar nada que el contrato no declare.
    """
    extra_marker = "synthetic-extra-field-0b7c"
    expected = answer()

    response, _ = await ask_through(
        user,
        node,
        lambda req: node.respond(req, expected | {"debug_trace": extra_marker, "x": [1]}),
    )

    assert response.status_code == 200
    assert response.json() == expected
    assert extra_marker not in response.text


async def test_an_unexpected_failure_is_a_generic_500_logged_as_internal_error(
    public: PublicApp, node: ScriptedNode, logs: LogLines, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic-internal-failure-text")

    monkeypatch.setattr(public.relay, "submit", broken)
    transport = httpx.ASGITransport(app=public.app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://render.test") as client:
        response = await client.post(ASK_PATH, json=ask_body(), headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "synthetic-internal-failure-text" not in response.text
    assert [entry["outcome"] for entry in logs.events("assistant_relayed")] == ["internal_error"]


async def test_a_failing_watcher_stops_the_wait_and_is_logged_without_its_text(
    public: PublicApp,
    user: httpx.AsyncClient,
    node: ScriptedNode,
    logs: LogLines,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken_watcher(_request: object) -> None:
        raise RuntimeError("synthetic-watcher-failure-text")

    monkeypatch.setattr(assistant_relay, "_wait_for_disconnect", broken_watcher)

    response = await user.post(ASK_PATH, json=ask_body(), headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "request_cancelled"
    assert public.relay.store.pending_count == 0
    [failed] = logs.events("disconnect_watcher_failed")
    assert failed["error"] == "RuntimeError"
    assert "synthetic-watcher-failure-text" not in logs.text()
    assert_no_route_tasks_left()


# ---------------------------------------------------------------------
# Cancelación: desconexión del cliente y cancelación de la petición
# ---------------------------------------------------------------------


def _raw_scope(body: bytes) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": ASK_PATH,
        "raw_path": ASK_PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"render.test"),
            (b"authorization", f"Bearer {ENGINEER_TOKEN}".encode()),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("203.0.113.10", 50000),
        "server": ("render.test", 443),
    }


async def test_a_client_disconnect_releases_the_request_and_sends_cancel(
    public: PublicApp, node: ScriptedNode, logs: LogLines
) -> None:
    body = json.dumps(ask_body()).encode()
    gone = asyncio.Event()
    delivered = False
    sent: list[MutableMapping[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    before = asyncio.all_tasks()
    call = asyncio.create_task(public.app(_raw_scope(body), receive, send))
    request = await node.next_request()
    assert public.relay.store.pending_count == 1
    assert route_tasks() == ["RelayService.submit", "_wait_for_disconnect"]

    gone.set()
    await asyncio.wait_for(call, timeout=3)

    cancel = await node.next_message()
    assert isinstance(cancel, Cancel)
    assert cancel.request_id == request.request_id
    assert public.relay.store.pending_count == 0
    assert_no_route_tasks_left()
    assert [entry["outcome"] for entry in logs.events("assistant_relayed")] == [
        "client_disconnected"
    ]
    assert public.local_work() == []
    await asyncio.sleep(0)
    assert_no_orphans(before)


async def test_cancelling_the_public_request_cancels_the_relay_request(
    public: PublicApp, user: httpx.AsyncClient, node: ScriptedNode
) -> None:
    before = asyncio.all_tasks()
    post = asyncio.create_task(
        user.post(ASK_PATH, json=ask_body(), headers=auth_header(ENGINEER_TOKEN))
    )
    request = await node.next_request()

    post.cancel()
    with suppress(asyncio.CancelledError):
        await post

    cancel = await node.next_message()
    assert isinstance(cancel, Cancel)
    assert cancel.request_id == request.request_id
    assert public.relay.store.pending_count == 0
    await asyncio.sleep(0)
    assert_no_orphans(before)


async def test_a_completed_request_leaves_no_watcher_or_submit_task(
    user: httpx.AsyncClient, node: ScriptedNode
) -> None:
    before = asyncio.all_tasks()

    for _ in range(3):
        response, _ = await ask_through(user, node, lambda req: node.respond(req, answer()))
        assert response.status_code == 200

    await asyncio.sleep(0)
    assert_no_orphans(before)


# ---------------------------------------------------------------------
# Logs: correlación sin datos sensibles
# ---------------------------------------------------------------------


async def test_logs_correlate_the_http_and_relay_ids_without_sensitive_data(
    user: httpx.AsyncClient, node: ScriptedNode, logs: LogLines
) -> None:
    post = asyncio.create_task(
        user.post(
            ASK_PATH,
            json=ask_body(attachments=[{"filename": ATTACHMENT_NAME, "byte_size": 1}]),
            headers={**auth_header(ENGINEER_TOKEN), "X-Request-ID": "http-corr-0001"},
        )
    )
    request = await node.next_request()
    node.respond(request, answer())
    response = await post

    assert response.status_code == 200
    relayed = logs.events("assistant_relayed")
    assert len(relayed) == 1
    assert relayed[0]["request_id"] == "http-corr-0001"
    assert relayed[0]["relay_request_id"] == str(request.request_id)
    assert relayed[0]["outcome"] == "ok"
    assert relayed[0]["status_code"] == 200
    queued = logs.events("request_queued")
    assert queued[0]["request_id"] == "http-corr-0001"
    assert queued[0]["relay_request_id"] == str(request.request_id)

    text = logs.text()
    for secret in (ENGINEER_TOKEN, NODE_TOKEN, "Bearer", QUESTION, ATTACHMENT_NAME, RESULT_MARKER):
        assert secret not in text
    assert NODE_TOKEN_HEADER not in text
