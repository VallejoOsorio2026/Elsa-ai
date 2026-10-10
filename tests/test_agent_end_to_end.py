"""Agente de PC1 de extremo a extremo, sin red real (D2.3).

- **Relay real de D2.2**: la app de ELSA con ``ELSA_RELAY_ENABLED`` y el
  :class:`~elsa.relay.service.RelayService` de verdad, servidos por
  ``httpx.ASGITransport``. El «navegador» es una llamada a
  ``RelayService.submit``, como hará D2.4.
- **ELSA local real**: la app de ELSA con autenticación fake y conocimiento
  sintético sembrado, también en memoria. La pregunta no trae código de
  material, así que Materiales no participa.

Ni Render, ni Materiales, ni Supabase, ni Internet.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.agent.local_client import ElsaLocalClient
from elsa.agent.relay_client import RelayClient
from elsa.agent.runner import NodeAgent
from elsa.demo.seed import ASSET_CODE, DOMAIN, seed_demo_data
from elsa.main import create_app
from elsa.relay.auth import hash_node_token
from elsa.relay.protocol import AskParams, CancelEffect, ErrorCode, Response
from elsa.relay.service import RelayService
from elsa.relay.store import RelayFailure
from tests.agent_fakes import LOCAL_BASE, NODE_ID, NODE_TOKEN, RELAY_BASE
from tests.conftest import ENGINEER_TOKEN, make_test_settings

pytestmark = pytest.mark.anyio

QUESTION = "rodamiento prensa"


Hook = Callable[[httpx.Request], Awaitable[None]]


@dataclass
class _Interposed(httpx.AsyncBaseTransport):
    """Transporte que deja pasar al ASGI real y permite intervenir antes/después."""

    inner: httpx.AsyncBaseTransport
    before: Hook | None = None
    after: Callable[[httpx.Request, httpx.Response], Awaitable[None]] | None = None
    paths: list[str] = field(default_factory=list)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        if self.before is not None:
            await self.before(request)
        response = await self.inner.handle_async_request(request)
        if self.after is not None:
            await self.after(request, response)
        return response


@pytest.fixture
def relay_app() -> FastAPI:
    return create_app(
        make_test_settings(
            relay_enabled=True,
            relay_node_id=NODE_ID,
            relay_node_token_sha256=SecretStr(hash_node_token(NODE_TOKEN)),
            relay_node_ttl_seconds=5.0,
            relay_long_poll_seconds=0.05,
            relay_request_ttl_seconds=10.0,
        )
    )


@pytest.fixture
def relay_service(relay_app: FastAPI) -> RelayService:
    service = relay_app.state.container.relay
    assert isinstance(service, RelayService)
    return service


@pytest.fixture
async def local_app(
    app: FastAPI,
    permissions: InMemoryPermissionsRepository,
    knowledge: InMemoryKnowledgeRepository,
) -> FastAPI:
    """La ELSA local: la app de pruebas con el conocimiento sintético publicado."""
    await seed_demo_data(
        permissions=permissions,
        knowledge=knowledge,
        settings=make_test_settings(demo_seed=True),
    )
    return app


@pytest.fixture
def relay_transport(relay_app: FastAPI) -> _Interposed:
    return _Interposed(httpx.ASGITransport(app=relay_app))


@pytest.fixture
def local_transport(local_app: FastAPI) -> _Interposed:
    return _Interposed(httpx.ASGITransport(app=local_app))


@pytest.fixture
async def agent(
    relay_transport: _Interposed,
    local_transport: _Interposed,
    relay_service: RelayService,
) -> AsyncIterator[NodeAgent]:
    node = NodeAgent(
        node_id=NODE_ID,
        relay=RelayClient(
            RELAY_BASE,
            SecretStr(NODE_TOKEN),
            poll_timeout_seconds=2.0,
            transport=relay_transport,
        ),
        local=ElsaLocalClient(LOCAL_BASE, transport=local_transport),
        min_empty_poll_seconds=0.01,
    )
    task = asyncio.create_task(node.run())
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 3
    while not relay_service.is_online():
        assert loop.time() < deadline, "the agent never registered"
        await asyncio.sleep(0.01)
    try:
        yield node
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def _ask_paths(transport: _Interposed) -> list[str]:
    return [path for path in transport.paths if path.endswith("/ask")]


async def test_question_travels_relay_agent_elsa_and_back(
    agent: NodeAgent, relay_service: RelayService, local_transport: _Interposed
) -> None:
    outcome = await asyncio.wait_for(
        relay_service.submit(
            AskParams(domain=DOMAIN, asset=ASSET_CODE, question=QUESTION),
            SecretStr(ENGINEER_TOKEN),
        ),
        5,
    )
    assert isinstance(outcome, Response)
    assert outcome.result["asset"] == ASSET_CODE
    assert outcome.result["is_generated"] is False
    assert outcome.result["components"], "the seeded component should be found"
    assert _ask_paths(local_transport) == [f"/api/v1/assistant/{DOMAIN}/{ASSET_CODE}/ask"]


@pytest.mark.parametrize(
    ("asset", "token", "expected"),
    [
        # ELSA autoriza el alcance antes de resolver el activo (regla 3): un activo
        # fuera de los permisos del usuario es 403, no 404.
        (
            "no-existe",
            ENGINEER_TOKEN,
            RelayFailure(ErrorCode.FORBIDDEN, "local:insufficient_permissions"),
        ),
        (
            ASSET_CODE,
            "fake-token-nobody",
            RelayFailure(ErrorCode.UNAUTHORIZED, "local:unauthorized"),
        ),
        (
            "..",
            ENGINEER_TOKEN,
            RelayFailure(ErrorCode.INVALID_REQUEST, "agent:invalid_path_segment"),
        ),
    ],
)
async def test_local_rejections_reach_the_submitter_as_protocol_errors(
    agent: NodeAgent,
    relay_service: RelayService,
    local_transport: _Interposed,
    asset: str,
    token: str,
    expected: RelayFailure,
) -> None:
    outcome = await asyncio.wait_for(
        relay_service.submit(
            AskParams(domain=DOMAIN, asset=asset, question=QUESTION), SecretStr(token)
        ),
        5,
    )
    assert isinstance(outcome, RelayFailure)
    assert outcome.code is expected.code
    assert outcome == expected
    if asset == "..":
        assert _ask_paths(local_transport) == []


async def test_cancel_from_the_relay_stops_the_local_call(
    relay_service: RelayService,
    relay_transport: _Interposed,
    local_transport: _Interposed,
    agent: NodeAgent,
) -> None:
    gate = asyncio.Event()
    entered = asyncio.Event()

    async def hold(request: httpx.Request) -> None:
        entered.set()
        await gate.wait()

    local_transport.before = hold
    rid = uuid4()
    submitted = asyncio.create_task(
        relay_service.submit(
            AskParams(domain=DOMAIN, asset=ASSET_CODE, question=QUESTION),
            SecretStr(ENGINEER_TOKEN),
            request_id=rid,
        )
    )
    await asyncio.wait_for(entered.wait(), 5)
    assert relay_service.cancel(rid) is CancelEffect.ATTEMPT
    outcome = await asyncio.wait_for(submitted, 5)
    assert outcome == RelayFailure(ErrorCode.CANCELLED)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 3
    while agent.active_jobs:
        assert loop.time() < deadline, "the local call was not cancelled"
        await asyncio.sleep(0.01)
    gate.set()
    assert not [p for p in relay_transport.paths if p.endswith("/result")]


async def test_lost_ack_does_not_reexecute_and_the_user_gets_one_answer(
    relay_service: RelayService,
    relay_transport: _Interposed,
    local_transport: _Interposed,
    agent: NodeAgent,
) -> None:
    lost = {"done": False}

    async def lose_first_result_ack(request: httpx.Request, response: httpx.Response) -> None:
        if request.url.path.endswith("/result") and not lost["done"]:
            lost["done"] = True
            await response.aread()  # Render ya lo procesó
            raise httpx.ReadError("ack lost")

    relay_transport.after = lose_first_result_ack
    outcome = await asyncio.wait_for(
        relay_service.submit(
            AskParams(domain=DOMAIN, asset=ASSET_CODE, question=QUESTION),
            SecretStr(ENGINEER_TOKEN),
        ),
        5,
    )
    assert isinstance(outcome, Response)

    loop = asyncio.get_running_loop()
    deadline = loop.time() + 3
    while len([p for p in relay_transport.paths if p.endswith("/result")]) < 2:
        assert loop.time() < deadline, "the result was not retransmitted"
        await asyncio.sleep(0.01)
    while agent.active_jobs:
        assert loop.time() < deadline
        await asyncio.sleep(0.01)
    assert len(_ask_paths(local_transport)) == 1
    assert len([p for p in relay_transport.paths if p.endswith("/result")]) == 2
