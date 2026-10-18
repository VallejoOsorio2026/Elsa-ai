"""Usuario → Render (RELAY) → relay D2.2 → agente D2.3 → ELSA local (LOCAL) → usuario.

Todo con componentes reales del repositorio y todo en memoria (D2.4, ADR 0033):

- **App pública**: ``create_app`` en modo RELAY con el ``RelayService`` real.
  Conocimiento, permisos, identidad de Materiales e inventario son trampas que
  fallan al primer uso: Render no ejecuta nada local.
- **Agente real** :class:`~elsa.agent.runner.NodeAgent`, que habla con la app
  pública por ``httpx.ASGITransport`` y con ELSA local por otro.
- **ELSA local**: la app de pruebas en modo LOCAL con el conocimiento sintético
  publicado. La pregunta no trae código de material: Materiales no participa.

Ni Render, ni PC1, ni Materiales, ni Supabase, ni Internet.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from elsa.adapters.fake_auth import ENGINEER_ID, FakeAuthAdapter
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.agent.local_client import ElsaLocalClient
from elsa.agent.relay_client import RelayClient
from elsa.agent.runner import NodeAgent
from elsa.demo.seed import ASSET_CODE, DOMAIN, seed_demo_data
from elsa.ports.auth import AuthenticatedUser
from elsa.relay.auth import NODE_TOKEN_HEADER
from elsa.relay.protocol import Register
from tests.agent_fakes import LOCAL_BASE, NODE_ID, NODE_TOKEN, RELAY_BASE
from tests.conftest import ENGINEER_TOKEN, auth_header, make_test_settings
from tests.test_api_assistant_relay import (
    LogLines,
    PublicApp,
    assert_no_orphans,
    build_public_app,
    capture_elsa_logs,
)

pytestmark = pytest.mark.anyio

QUESTION = "rodamiento prensa"
ASK_PATH = f"/api/v1/assistant/{DOMAIN}/{ASSET_CODE}/ask"
ATTACHMENT_NAME = "synthetic-e2e-attachment-6a2f.pdf"
ASK_BODY = {"question": QUESTION, "attachments": [{"filename": ATTACHMENT_NAME, "byte_size": 3}]}

PUBLIC_ONLY_TOKEN = "fake-token-public-only"
"""Lo acepta Render y ELSA local no: el JWT válido en un lado y no en el otro."""

NO_PROFILE_TOKEN = "fake-token-no-materials-profile"
"""Lo aceptan ambos, pero el usuario no tiene perfil en el Materiales de PC1."""

_ENGINEER = AuthenticatedUser(
    id=ENGINEER_ID,
    email="engineer@example.test",
    claims={"role": "engineer"},
    session_id="00000000-0000-4000-8000-0000000000a1",
)

_EXTRA_USER = AuthenticatedUser(
    id="00000000-0000-4000-8000-0000000000ff",
    email="no.profile@example.test",
    claims={"role": "engineer"},
    session_id="00000000-0000-4000-8000-0000000000fe",
)


# ---------------------------------------------------------------------
# Las tres piezas
# ---------------------------------------------------------------------


@pytest.fixture
def auth_adapter() -> FakeAuthAdapter:
    """El de ELSA local (sustituye al de ``conftest``): conoce también al usuario sin perfil."""
    return FakeAuthAdapter({ENGINEER_TOKEN: _ENGINEER, NO_PROFILE_TOKEN: _EXTRA_USER})


def _public_auth() -> FakeAuthAdapter:
    return FakeAuthAdapter(
        {ENGINEER_TOKEN: _ENGINEER, NO_PROFILE_TOKEN: _EXTRA_USER, PUBLIC_ONLY_TOKEN: _ENGINEER}
    )


@pytest.fixture
def public() -> PublicApp:
    return build_public_app(auth=_public_auth())


@pytest.fixture
async def local_app(
    app: FastAPI,
    permissions: InMemoryPermissionsRepository,
    knowledge: InMemoryKnowledgeRepository,
) -> FastAPI:
    """ELSA de PC1: la app de pruebas en modo LOCAL con el conocimiento publicado."""
    await seed_demo_data(
        permissions=permissions, knowledge=knowledge, settings=make_test_settings(demo_seed=True)
    )
    return app


Hook = Callable[[httpx.Request], Awaitable[None]]


@dataclass
class Recording(httpx.AsyncBaseTransport):
    """Transporte que deja pasar al ASGI real, graba cada petición y permite intervenir."""

    inner: httpx.AsyncBaseTransport
    before: Hook | None = None
    replace: Callable[[httpx.Request], httpx.Response] | None = None
    sent: list[httpx.Request] = field(default_factory=list)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.sent.append(request)
        if self.before is not None:
            await self.before(request)
        if self.replace is not None:
            return self.replace(request)
        return await self.inner.handle_async_request(request)

    def asks(self) -> list[httpx.Request]:
        return [request for request in self.sent if request.url.path.endswith("/ask")]


@pytest.fixture
def to_render(public: PublicApp) -> Recording:
    return Recording(httpx.ASGITransport(app=public.app))


@pytest.fixture
def to_local(local_app: FastAPI) -> Recording:
    return Recording(httpx.ASGITransport(app=local_app))


@pytest.fixture
def logs(public: PublicApp, local_app: FastAPI) -> Iterator[LogLines]:
    with capture_elsa_logs() as sink:
        yield sink


async def _until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        assert loop.time() < deadline, "condition not reached in time"
        await asyncio.sleep(0.01)


@pytest.fixture
async def agent(
    public: PublicApp, to_render: Recording, to_local: Recording
) -> AsyncIterator[NodeAgent]:
    node = NodeAgent(
        node_id=NODE_ID,
        relay=RelayClient(
            RELAY_BASE, SecretStr(NODE_TOKEN), poll_timeout_seconds=2.0, transport=to_render
        ),
        local=ElsaLocalClient(LOCAL_BASE, transport=to_local),
        min_empty_poll_seconds=0.01,
    )
    task = asyncio.create_task(node.run())
    await _until(public.relay.is_online)
    try:
        yield node
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


@pytest.fixture
async def user(public: PublicApp) -> AsyncIterator[httpx.AsyncClient]:
    """El navegador: solo conoce la ruta pública de siempre."""
    transport = httpx.ASGITransport(app=public.app)
    async with httpx.AsyncClient(transport=transport, base_url="https://render.test") as client:
        yield client


async def _ask(
    user: httpx.AsyncClient, token: str = ENGINEER_TOKEN, **headers: str
) -> httpx.Response:
    return await asyncio.wait_for(
        user.post(
            ASK_PATH,
            json=ASK_BODY,
            headers={**auth_header(token), **headers},
        ),
        10,
    )


# ---------------------------------------------------------------------
# Camino feliz
# ---------------------------------------------------------------------


async def test_a_public_question_travels_to_pc1_and_back(
    public: PublicApp,
    agent: NodeAgent,
    user: httpx.AsyncClient,
    local_app: FastAPI,
    to_render: Recording,
    to_local: Recording,
) -> None:
    response = await _ask(user)

    assert response.status_code == 200
    body = response.json()
    assert body["asset"] == ASSET_CODE
    assert body["components"], "the seeded component should be found"

    # Lo mismo que respondería ELSA local si se le preguntara directamente.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=local_app), base_url="http://127.0.0.1:8000"
    ) as direct:
        local = await direct.post(
            ASK_PATH,
            json=ASK_BODY,
            headers=auth_header(ENGINEER_TOKEN),
        )
    assert local.status_code == 200
    assert body == local.json()

    # Render no ejecutó nada local.
    assert public.local_work() == []
    # El mismo token llegó a PC1; el del nodo no salió del canal del relay.
    [sent] = to_local.asks()
    assert sent.headers["authorization"] == f"Bearer {ENGINEER_TOKEN}"
    assert sent.headers["x-elsa-relay-hop"] == "1"
    assert NODE_TOKEN_HEADER.lower() not in sent.headers
    assert NODE_TOKEN not in str(sent.headers)
    for request in to_render.sent:
        assert request.headers[NODE_TOKEN_HEADER.lower()] == NODE_TOKEN
        assert ENGINEER_TOKEN not in str(request.headers)
        assert ENGINEER_TOKEN.encode() not in request.content
    assert public.relay.store.pending_count == 0


# ---------------------------------------------------------------------
# PC1 fuera de línea
# ---------------------------------------------------------------------


async def test_without_pc1_the_user_gets_an_explicit_failure_and_nothing_runs_here(
    public: PublicApp, user: httpx.AsyncClient, to_local: Recording
) -> None:
    response = await _ask(user)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "local_node_unavailable"
    assert public.local_work() == []
    assert to_local.asks() == []
    assert public.relay.store.pending_count == 0


# ---------------------------------------------------------------------
# Autenticación en Render y autorización en PC1
# ---------------------------------------------------------------------


async def test_an_invalid_public_token_never_reaches_pc1(
    agent: NodeAgent, user: httpx.AsyncClient, to_local: Recording
) -> None:
    response = await _ask(user, token="fake-token-nobody")

    assert response.status_code == 401
    assert to_local.asks() == []


@pytest.mark.parametrize(
    ("token", "status_code", "code"),
    [
        (PUBLIC_ONLY_TOKEN, 401, "unauthorized"),
        (NO_PROFILE_TOKEN, 403, "account_disabled"),
    ],
)
async def test_pc1_rejections_reach_the_user_without_leaking_the_token(
    public: PublicApp,
    agent: NodeAgent,
    user: httpx.AsyncClient,
    to_local: Recording,
    logs: LogLines,
    token: str,
    status_code: int,
    code: str,
) -> None:
    response = await _ask(user, token=token)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert len(to_local.asks()) == 1, "Render authenticated it; PC1 rejected it"
    assert token not in response.text
    assert token not in logs.text()
    assert public.local_work() == []


async def test_a_scope_outside_the_users_permissions_is_a_403_from_pc1(
    public: PublicApp, agent: NodeAgent, user: httpx.AsyncClient, to_local: Recording
) -> None:
    response = await asyncio.wait_for(
        user.post(
            f"/api/v1/assistant/{DOMAIN}/no-existe/ask",
            json={"question": QUESTION},
            headers=auth_header(ENGINEER_TOKEN),
        ),
        10,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_permissions"
    assert len(to_local.asks()) == 1
    assert public.local_work() == []


# ---------------------------------------------------------------------
# Respuesta inválida del nodo
# ---------------------------------------------------------------------


async def test_an_incompatible_node_answer_never_reaches_the_user(
    agent: NodeAgent, user: httpx.AsyncClient, to_local: Recording
) -> None:
    marker = "synthetic-foreign-payload-3e8d"
    to_local.replace = lambda _request: httpx.Response(200, json={"payload": marker, "ok": True})

    response = await _ask(user)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "local_node_invalid_response"
    assert marker not in response.text


# ---------------------------------------------------------------------
# Cancelación, pérdida de sesión y plazo
# ---------------------------------------------------------------------


async def test_cancelling_the_public_request_cancels_the_call_in_pc1(
    public: PublicApp,
    agent: NodeAgent,
    user: httpx.AsyncClient,
    to_render: Recording,
    to_local: Recording,
) -> None:
    entered = asyncio.Event()
    gate = asyncio.Event()

    async def hold(_request: httpx.Request) -> None:
        entered.set()
        await gate.wait()

    to_local.before = hold
    before = asyncio.all_tasks()
    post = asyncio.create_task(_ask(user))
    await asyncio.wait_for(entered.wait(), 5)

    post.cancel()
    with suppress(asyncio.CancelledError):
        await post

    await _until(lambda: agent.active_jobs == 0)
    assert public.relay.store.pending_count == 0
    assert not [r for r in to_render.sent if r.url.path.endswith("/result")]
    assert len(to_local.asks()) == 1
    gate.set()
    await asyncio.sleep(0)
    assert_no_orphans(before)


async def test_a_lost_session_fails_the_request_without_replay_and_the_agent_recovers(
    public: PublicApp, agent: NodeAgent, user: httpx.AsyncClient, to_local: Recording
) -> None:
    entered = asyncio.Event()
    gate = asyncio.Event()
    old_session = agent.session_id

    async def hold_first(_request: httpx.Request) -> None:
        if not entered.is_set():
            entered.set()
            await gate.wait()

    to_local.before = hold_first
    post = asyncio.create_task(_ask(user))
    await asyncio.wait_for(entered.wait(), 5)

    # Otra sesión toma el nodo: la del agente queda vieja con la solicitud en vuelo.
    public.relay.register(Register(node_id=NODE_ID, node_session_id=uuid4()))
    failed = await asyncio.wait_for(post, 5)
    gate.set()

    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "local_node_unavailable"

    def recovered() -> bool:
        session = public.relay.store.session
        return (
            agent.session_id not in (None, old_session)
            and session is not None
            and session.session_id == agent.session_id
        )

    await _until(recovered)
    await _until(lambda: agent.active_jobs == 0)
    assert len(to_local.asks()) == 1, "the in-flight request must not be replayed"

    again = await _ask(user)
    assert again.status_code == 200
    assert len(to_local.asks()) == 2


async def test_a_slow_pc1_ends_in_a_timeout_without_replay(
    public: PublicApp, user: httpx.AsyncClient, to_render: Recording, to_local: Recording
) -> None:
    """ELSA local no contesta: el agente corta en su plazo y nadie la reintenta.

    El plazo local se acorta a 0,3 s; el del relay sigue siendo mayor, como en
    producción (110 s < 120 s), así que gana el del agente.
    """
    gate = asyncio.Event()

    async def never(_request: httpx.Request) -> None:
        await gate.wait()

    to_local.before = never
    node = NodeAgent(
        node_id=NODE_ID,
        relay=RelayClient(
            RELAY_BASE, SecretStr(NODE_TOKEN), poll_timeout_seconds=2.0, transport=to_render
        ),
        local=ElsaLocalClient(LOCAL_BASE, transport=to_local),
        local_timeout_seconds=0.3,
        min_empty_poll_seconds=0.01,
    )
    task = asyncio.create_task(node.run())
    try:
        await _until(public.relay.is_online)
        response = await _ask(user)

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "local_node_timeout"
        assert public.relay.store.pending_count == 0
        await _until(lambda: node.active_jobs == 0)
        assert len(to_local.asks()) == 1
        assert public.local_work() == []
    finally:
        gate.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------
# Recursión: una ELSA de PC1 configurada por error en RELAY
# ---------------------------------------------------------------------


async def test_a_pc1_misconfigured_in_relay_mode_cannot_send_the_question_back(
    public: PublicApp, user: httpx.AsyncClient
) -> None:
    misconfigured = build_public_app()  # «ELSA local» en RELAY, con su propio relay
    to_local = Recording(httpx.ASGITransport(app=misconfigured.app))
    node = NodeAgent(
        node_id=NODE_ID,
        relay=RelayClient(
            RELAY_BASE,
            SecretStr(NODE_TOKEN),
            poll_timeout_seconds=2.0,
            transport=Recording(httpx.ASGITransport(app=public.app)),
        ),
        local=ElsaLocalClient(LOCAL_BASE, transport=to_local),
        min_empty_poll_seconds=0.01,
    )
    task = asyncio.create_task(node.run())
    try:
        await _until(public.relay.is_online)
        response = await _ask(user)
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "local_node_unavailable"
    assert len(to_local.asks()) == 1, "the hop was rejected, not forwarded"
    assert misconfigured.relay.store.pending_count == 0
    assert misconfigured.local_work() == []
    assert public.local_work() == []


# ---------------------------------------------------------------------
# Logs de las tres piezas
# ---------------------------------------------------------------------


async def test_logs_correlate_render_relay_and_pc1_without_sensitive_data(
    agent: NodeAgent, user: httpx.AsyncClient, logs: LogLines
) -> None:
    response = await _ask(user, **{"X-Request-ID": "e2e-corr-0001"})
    assert response.status_code == 200
    result_text = response.json()["components"][0]["description"]
    assert result_text

    [relayed] = logs.events("assistant_relayed")
    assert relayed["request_id"] == "e2e-corr-0001"
    relay_id = relayed["relay_request_id"]
    accepted = [e for e in logs.events("request_accepted") if e.get("request_id") == relay_id]
    assert accepted, "the agent logs the same relay request id"
    local_access = [
        line
        for line in logs.lines
        if '"request completed"' in line and f'"request_id": "{relay_id}"' in line
    ]
    assert local_access, "ELSA local logs the relay request id it received"

    text = logs.text()
    for secret in (
        ENGINEER_TOKEN,
        NODE_TOKEN,
        "Bearer",
        "Authorization",
        QUESTION,
        ATTACHMENT_NAME,
        result_text,
    ):
        assert secret not in text, f"{secret!r} leaked into the logs"
