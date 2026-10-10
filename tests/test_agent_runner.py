"""Ciclo de vida del agente de PC1 contra un relay y una ELSA simulados (ADR 0032).

Sin red real ni sueños largos: el relay simulado hace un *long poll* de
milisegundos, las esperas del agente (backoff, ritmo del poll, reintentos de
``/result``) pasan por un ``sleep`` inyectado que las registra, y ELSA se
retiene con un ``asyncio.Event`` para probar lo que ocurre mientras trabaja.
"""

import ast
import asyncio
import gc
import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import JsonValue, SecretStr

import elsa.agent as agent_package
from elsa.agent.__main__ import main, run_agent
from elsa.agent.config import AgentConfig, AgentSettings
from elsa.agent.local_client import ElsaLocalClient, LocalSuccess
from elsa.agent.relay_client import RelayClient, encode_message
from elsa.agent.runner import (
    BACKOFF_MAX_SECONDS,
    EXIT_CRASH,
    EXIT_FATAL,
    MIN_EMPTY_POLL_SECONDS,
    REPLY_QUEUE_MAX,
    NodeAgent,
)
from elsa.relay.auth import NODE_TOKEN_HEADER
from elsa.relay.protocol import Cancel, Request, Response
from elsa.relay.service import MAX_RESPONSE_WIRE_BYTES, _wire_size
from tests.agent_fakes import (
    ATTACHMENT_NAME,
    LOCAL_BASE,
    NODE_ID,
    NODE_TOKEN,
    QUESTION,
    RELAY_BASE,
    RESULT_TEXT,
    USER_TOKEN,
    FakeLocalElsa,
    FakeRelay,
    SleepRecorder,
    error_body,
    make_request,
    wait_until,
)

pytestmark = pytest.mark.anyio

STALE = httpx.Response(409, json=error_body("stale_session"))
NOT_PENDING = httpx.Response(409, json=error_body("request_not_pending"))


@pytest.fixture
def relay() -> FakeRelay:
    return FakeRelay()


@pytest.fixture
def elsa() -> FakeLocalElsa:
    return FakeLocalElsa()


@pytest.fixture
def sleeps() -> SleepRecorder:
    return SleepRecorder()


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def agent_logs() -> Iterator[_ListHandler]:
    """Registros de ``elsa.agent`` aunque ``configure_logging`` corte la propagación."""
    handler = _ListHandler()
    logger = logging.getLogger("elsa.agent")
    previous = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


def _events(handler: _ListHandler) -> list[str]:
    return [str(getattr(record, "event", "")) for record in handler.records]


def _build(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    **options: Any,
) -> NodeAgent:
    return NodeAgent(
        node_id=NODE_ID,
        relay=RelayClient(
            RELAY_BASE,
            SecretStr(NODE_TOKEN),
            poll_timeout_seconds=1.0,
            transport=relay.transport,
        ),
        local=ElsaLocalClient(LOCAL_BASE, transport=elsa.transport),
        sleep=sleeps,
        jitter=lambda: 1.0,
        **options,
    )


@asynccontextmanager
async def _running(agent: NodeAgent) -> AsyncIterator["asyncio.Task[int]"]:
    task = asyncio.create_task(agent.run())
    try:
        yield task
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _registered(relay: FakeRelay, agent: NodeAgent) -> UUID:
    await wait_until(lambda: agent.session_id is not None and len(relay.polls) > 0)
    assert agent.session_id is not None
    return agent.session_id


def _results(relay: FakeRelay) -> dict[str, list[dict[str, Any]]]:
    by_request: dict[str, list[dict[str, Any]]] = {}
    for item in relay.results:
        by_request.setdefault(item["request_id"], []).append(item)
    return by_request


def _other_tasks() -> set["asyncio.Task[Any]"]:
    """Tareas vivas que no son del test ni del runner de anyio."""
    return {
        task
        for task in asyncio.all_tasks()
        if task is not asyncio.current_task()
        and not getattr(task.get_coro(), "__qualname__", "").startswith("TestRunner.")
    }


# ---------------------------------------------------------------------------
# Flujo feliz y separación de credenciales
# ---------------------------------------------------------------------------


async def test_happy_path_register_poll_execute_respond(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        request = make_request(session)
        relay.push_request(request)
        await wait_until(lambda: len(relay.results) == 1)
        await wait_until(lambda: agent.active_jobs == 0)

    [registered] = relay.registers
    assert registered["message_type"] == "register"
    assert UUID(registered["node_session_id"]) == session
    assert all(UUID(p["node_session_id"]) == session for p in relay.polls)

    [result] = relay.results
    assert result["message_type"] == "response"
    assert result["request_id"] == str(request.request_id)
    assert result["node_session_id"] == str(session)
    assert result["result"] == {"message": RESULT_TEXT, "is_generated": False}
    [local_call] = elsa.requests
    assert local_call.raw_path == "/api/v1/assistant/mantenimiento/tampella/ask"


async def test_node_token_never_reaches_elsa_and_user_token_never_reaches_render(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session))
        await wait_until(lambda: len(relay.results) == 1)

    for sent in relay.requests:
        assert sent.headers[NODE_TOKEN_HEADER.lower()] == NODE_TOKEN
        assert "authorization" not in sent.headers
        assert USER_TOKEN not in str(sent.headers)
        assert USER_TOKEN.encode() not in sent.body
        assert NODE_TOKEN.encode() not in sent.body
    for sent in elsa.requests:
        assert sent.headers["authorization"] == f"Bearer {USER_TOKEN}"
        assert NODE_TOKEN not in str(sent.headers)
        assert NODE_TOKEN.encode() not in sent.body


# ---------------------------------------------------------------------------
# Poll durante la ejecución, concurrencia y ritmo
# ---------------------------------------------------------------------------


async def test_polling_continues_while_elsa_is_working(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    elsa.hold()
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session))
        await elsa.started.wait()
        polls_when_started = len(relay.polls)
        await wait_until(lambda: len(relay.polls) >= polls_when_started + 3)
        assert relay.results == []  # ELSA sigue trabajando
        assert len(elsa.requests) == 1
        elsa.release()
        await wait_until(lambda: len(relay.results) == 1)
    assert relay.results[0]["message_type"] == "response"


async def test_execution_and_admission_are_bounded(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    elsa.hold()
    agent = _build(relay, elsa, sleeps, max_concurrency=1, max_queued=2)
    async with _running(agent):
        session = await _registered(relay, agent)
        requests = [make_request(session) for _ in range(5)]
        for request in requests:
            relay.push_request(request)
        await wait_until(lambda: len(relay.results) == 2)

        # 1 ejecutando + 2 en espera; los 2 restantes se rechazaron sin tareas nuevas.
        assert agent.active_jobs == 3
        assert len(elsa.requests) == 1
        assert len(_other_tasks()) <= 1 + 1 + 2 + 3  # run, respuestas, poll+señal, trabajos
        busy = {r["request_id"] for r in relay.results}
        assert busy == {str(r.request_id) for r in requests[3:]}
        assert all(r["code"] == "LOCAL_UNAVAILABLE" for r in relay.results)
        assert all(r["detail"] == "agent:busy" for r in relay.results)

        elsa.release()
        await wait_until(lambda: len(relay.results) == 5)
        await wait_until(lambda: agent.active_jobs == 0)
    assert len(elsa.requests) == 3
    responses = [r for r in relay.results if r["message_type"] == "response"]
    assert {r["request_id"] for r in responses} == {str(r.request_id) for r in requests[:3]}


async def test_immediate_replies_use_a_bounded_queue_and_never_spawn_tasks(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
) -> None:
    elsa.hold()
    gate = asyncio.Event()

    async def stuck(request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return httpx.Response(200, json={"accepted": True})

    relay.result_steps.append(stuck)
    agent = _build(relay, elsa, sleeps, max_concurrency=1, max_queued=0)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session))  # ocupa la única plaza
        await elsa.started.wait()
        overflow = REPLY_QUEUE_MAX + 4
        for _ in range(1 + overflow):  # 1 queda atascado en el trabajador
            relay.push_request(make_request(session))
        await wait_until(lambda: _events(agent_logs).count("request_rejected") == 1 + overflow)

        assert agent.pending_replies == REPLY_QUEUE_MAX
        assert _events(agent_logs).count("reply_dropped") == overflow - REPLY_QUEUE_MAX
        assert len(_other_tasks()) <= 1 + 1 + 2 + 1
        gate.set()
        elsa.release()
        await wait_until(lambda: agent.pending_replies == 0 and agent.active_jobs == 0)


async def test_fast_empty_polls_are_paced(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    for _ in range(5):
        relay.poll_steps.append(httpx.Response(200, json={"message": None}))
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        await wait_until(lambda: len(sleeps.delays) >= 5)
    assert all(0 < d <= MIN_EMPTY_POLL_SECONDS for d in sleeps.delays[:5])
    assert all(d > MIN_EMPTY_POLL_SECONDS * 0.5 for d in sleeps.delays[:5])


async def test_discarded_poll_messages_are_paced_and_never_executed(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    foreign = dict(make_request(uuid4()).to_wire_dict())
    for _ in range(3):
        relay.poll_steps.append(httpx.Response(200, json={"message": foreign}))
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        await wait_until(lambda: len(sleeps.delays) >= 3)
    assert elsa.requests == []
    assert relay.results == []


async def test_duplicate_request_is_ignored_without_reply(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
) -> None:
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        request = make_request(session)
        relay.push_request(request)
        await wait_until(lambda: len(relay.results) == 1)
        relay.push_request(request)
        await wait_until(lambda: "duplicate_request_ignored" in _events(agent_logs))
    assert len(elsa.requests) == 1
    assert len(relay.results) == 1


# ---------------------------------------------------------------------------
# Expiración y ruta segura
# ---------------------------------------------------------------------------


async def test_expired_request_is_not_executed(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session, ttl_seconds=1.0))
        await wait_until(lambda: len(relay.results) == 1)
    [result] = relay.results
    assert (result["code"], result["detail"]) == ("TIMEOUT", "agent:expired_before_execution")
    assert elsa.requests == []


async def test_request_that_expires_while_queued_is_not_executed(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
) -> None:
    now = [datetime.now(UTC)]
    elsa.hold()
    agent = _build(relay, elsa, sleeps, clock=lambda: now[0])
    async with _running(agent):
        session = await _registered(relay, agent)
        first, second = make_request(session), make_request(session, ttl_seconds=30)
        relay.push_request(first)
        relay.push_request(second)
        await wait_until(lambda: agent.active_jobs == 2)
        now[0] += timedelta(seconds=40)  # solo el segundo vence mientras espera turno
        elsa.release()
        await wait_until(lambda: agent.active_jobs == 0)
    assert len(elsa.requests) == 1
    # El primero se entrega; del segundo no se transmite nada: ya venció.
    assert list(_results(relay)) == [str(first.request_id)]
    assert "result_undelivered" in _events(agent_logs)


async def test_no_result_is_transmitted_after_expiry(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
) -> None:
    """Tampoco el primer envío: un resultado vencido no viaja."""
    now = [datetime.now(UTC)]
    elsa.hold()
    agent = _build(relay, elsa, sleeps, clock=lambda: now[0])
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session, ttl_seconds=30))
        await elsa.started.wait()
        now[0] += timedelta(seconds=31)
        elsa.release()
        await wait_until(lambda: "result_undelivered" in _events(agent_logs))
        await wait_until(lambda: agent.active_jobs == 0)
    assert len(elsa.requests) == 1
    assert relay.results == []


async def test_local_call_never_outlives_the_request(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    elsa.hold()
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session, ttl_seconds=2.15))
        await wait_until(lambda: len(relay.results) == 1)
    [result] = relay.results
    assert (result["code"], result["detail"]) == ("TIMEOUT", "local:timeout")
    assert elsa.cancelled == 1


@pytest.mark.parametrize(("domain", "asset"), [("mantenimiento", ".."), ("..", "x"), ("a/b", "c")])
async def test_unsafe_paths_are_rejected_without_calling_elsa(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder, domain: str, asset: str
) -> None:
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session, domain=domain, asset=asset))
        await wait_until(lambda: len(relay.results) == 1)
    [result] = relay.results
    assert (result["code"], result["detail"]) == ("INVALID_REQUEST", "agent:invalid_path_segment")
    assert elsa.requests == []


# ---------------------------------------------------------------------------
# Resultados locales
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "code"),
    [
        (httpx.Response(401, json=error_body("invalid_token")), "UNAUTHORIZED"),
        (httpx.Response(403, json=error_body("insufficient_permissions")), "FORBIDDEN"),
        (httpx.Response(404, json=error_body("asset_not_found")), "INVALID_REQUEST"),
        (httpx.Response(500), "LOCAL_ERROR"),
        (httpx.ConnectError("refused"), "LOCAL_UNAVAILABLE"),
        (httpx.Response(200, content=b"{not json"), "LOCAL_ERROR"),
    ],
)
async def test_local_failures_become_error_messages(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    step: httpx.Response | Exception,
    code: str,
) -> None:
    elsa.steps.append(step)
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session))
        await wait_until(lambda: len(relay.results) == 1)
        await wait_until(lambda: agent.active_jobs == 0)
    [result] = relay.results
    assert result["message_type"] == "error"
    assert result["code"] == code


async def test_response_over_the_wire_limit_becomes_a_local_error(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    payload = {"message": "x" * (MAX_RESPONSE_WIRE_BYTES - 40)}
    assert len(json.dumps(payload).encode()) <= MAX_RESPONSE_WIRE_BYTES
    elsa.steps.append(httpx.Response(200, json=payload))
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session))
        await wait_until(lambda: len(relay.results) == 1)
    [result] = relay.results
    assert (result["code"], result["detail"]) == ("LOCAL_ERROR", "local:response_too_large")


# ---------------------------------------------------------------------------
# CANCEL
# ---------------------------------------------------------------------------


async def test_cancel_before_execution_withdraws_the_request(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    elsa.hold()
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        first, second = make_request(session), make_request(session)
        relay.push_request(first)
        relay.push_request(second)
        await wait_until(lambda: agent.active_jobs == 2)
        relay.push(
            Cancel(
                node_id=NODE_ID, node_session_id=session, request_id=second.request_id
            ).model_dump(mode="json")
        )
        await wait_until(lambda: agent.active_jobs == 1)
        elsa.release()
        await wait_until(lambda: len(relay.results) == 1 and agent.active_jobs == 0)
    assert len(elsa.requests) == 1
    assert list(_results(relay)) == [str(first.request_id)]


async def test_cancel_during_execution_closes_the_local_call(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    elsa.hold()
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        request = make_request(session)
        relay.push_request(request)
        await elsa.started.wait()
        relay.push(
            Cancel(
                node_id=NODE_ID, node_session_id=session, request_id=request.request_id
            ).model_dump(mode="json")
        )
        await wait_until(lambda: elsa.cancelled == 1 and agent.active_jobs == 0)
        polls = len(relay.polls)
        await wait_until(lambda: len(relay.polls) > polls)
    assert relay.results == []


@pytest.mark.parametrize("known", [True, False])
async def test_cancel_after_completion_or_unknown_is_ignored(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
    known: bool,
) -> None:
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        request = make_request(session)
        relay.push_request(request)
        await wait_until(lambda: len(relay.results) == 1 and agent.active_jobs == 0)
        target = request.request_id if known else uuid4()
        relay.push(
            Cancel(node_id=NODE_ID, node_session_id=session, request_id=target).model_dump(
                mode="json"
            )
        )
        await wait_until(lambda: "cancel_ignored" in _events(agent_logs))
    assert len(relay.results) == 1
    assert len(elsa.requests) == 1


# ---------------------------------------------------------------------------
# Sesiones y reconexión
# ---------------------------------------------------------------------------


async def test_stale_session_cancels_work_and_registers_a_new_id_without_replay(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    elsa.hold()
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        first_session = await _registered(relay, agent)
        relay.push_request(make_request(first_session))
        await elsa.started.wait()
        relay.poll_steps.append(STALE)
        await wait_until(lambda: len(relay.registers) == 2)
        await wait_until(lambda: agent.active_jobs == 0 and elsa.cancelled == 1)
        second_session = relay.session_ids[1]
        assert second_session != first_session
        await wait_until(
            lambda: any(UUID(p["node_session_id"]) == second_session for p in relay.polls)
        )
        elsa.release()
        polls = len(relay.polls)
        await wait_until(lambda: len(relay.polls) > polls + 2)
    assert len(elsa.requests) == 1  # nunca se reejecutó
    assert relay.results == []  # el resultado de la sesión vieja nunca se envía


async def test_relay_restart_leads_to_a_fresh_session_that_keeps_working(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        await _registered(relay, agent)
        relay.poll_steps.append(STALE)  # Render reinició: no conoce la sesión
        await wait_until(lambda: len(relay.registers) == 2 and agent.session_id is not None)
        new_session = relay.session_ids[1]
        await wait_until(lambda: agent.session_id == new_session)
        relay.push_request(make_request(new_session))
        await wait_until(lambda: len(relay.results) == 1)
    assert relay.results[0]["node_session_id"] == str(new_session)
    assert len(set(relay.session_ids)) == 2


async def test_lost_register_reply_is_retried_with_the_same_id(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    relay.register_steps.extend([httpx.ReadError("lost"), httpx.Response(503)])
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        await _registered(relay, agent)
    assert len(relay.registers) == 3
    assert len(set(relay.session_ids)) == 1
    assert sleeps.delays[:2] == [1.0, 2.0]


async def test_stale_register_generates_a_new_id(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    relay.register_steps.append(STALE)
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
    first, second = relay.session_ids
    assert first != second == session


async def test_network_failures_back_off_with_a_ceiling_and_reset_on_success(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    failures: list[httpx.Response | Exception] = [httpx.ConnectError("down")] * 4
    failures += [httpx.Response(502)] * 3 + [httpx.Response(429)]
    relay.poll_steps.extend(failures)
    relay.poll_steps.append(httpx.Response(200, json={"message": None}))
    relay.poll_steps.append(httpx.ConnectError("down again"))
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        await wait_until(lambda: len(relay.polls) >= 11)
    backoffs = sleeps.delays[:8]
    assert backoffs == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]
    assert max(sleeps.delays) <= BACKOFF_MAX_SECONDS
    # Tras el éxito (ritmo del poll vacío), el siguiente fallo vuelve a 1 s.
    assert sleeps.delays[9] == 1.0
    assert len(relay.registers) == 1


@pytest.mark.parametrize(
    ("where", "response"),
    [
        ("register", httpx.Response(401, json=error_body("unauthorized"))),
        ("register", httpx.Response(403)),
        ("register", httpx.Response(404, json=error_body("not_found"))),
        ("register", httpx.Response(422, json=error_body("validation_error"))),
        ("poll", httpx.Response(401, json=error_body("unauthorized"))),
        ("poll", httpx.Response(413, json=error_body("payload_too_large"))),
    ],
)
async def test_configuration_failures_stop_the_agent_without_retrying(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
    where: str,
    response: httpx.Response,
) -> None:
    getattr(relay, f"{where}_steps").append(response)
    agent = _build(relay, elsa, sleeps)
    code = await asyncio.wait_for(agent.run(), 3)
    assert code == EXIT_FATAL
    assert len(relay.registers) == 1
    assert len(relay.polls) == (1 if where == "poll" else 0)
    assert sleeps.delays == []
    assert {"relay_auth_failed", "relay_misconfigured"} & set(_events(agent_logs))
    assert _other_tasks() == set()


async def test_node_auth_failure_on_result_stops_the_agent(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    relay.result_steps.append(httpx.Response(401, json=error_body("unauthorized")))
    agent = _build(relay, elsa, sleeps)
    task = asyncio.create_task(agent.run())
    session = await _registered(relay, agent)
    relay.push_request(make_request(session))
    assert await asyncio.wait_for(task, 3) == EXIT_FATAL
    assert len(relay.results) == 1
    assert _other_tasks() == set()


# ---------------------------------------------------------------------------
# Entrega del resultado: ACK perdido y reintentos acotados
# ---------------------------------------------------------------------------


async def test_lost_ack_is_retried_without_reexecuting(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
) -> None:
    # Render acepta el primer envío pero la respuesta HTTP se pierde.
    relay.result_steps.extend([httpx.ReadError("ack lost"), NOT_PENDING])
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session))
        await wait_until(lambda: "result_not_pending" in _events(agent_logs))
        await wait_until(lambda: agent.active_jobs == 0)
    assert len(elsa.requests) == 1
    first, second = relay.results
    assert first == second
    assert 0.5 in sleeps.delays


async def test_result_is_transmitted_at_most_four_times(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
) -> None:
    relay.result_steps.extend([httpx.Response(503)] * 6)
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session))
        await wait_until(lambda: "result_undelivered" in _events(agent_logs))
        await wait_until(lambda: agent.active_jobs == 0)
    assert len(relay.results) == 4
    assert len({json.dumps(r, sort_keys=True) for r in relay.results}) == 1
    retry_delays = [d for d in sleeps.delays if d in (0.5, 1.0, 2.0)]
    assert retry_delays[:3] == [0.5, 1.0, 2.0]
    assert len(elsa.requests) == 1


async def test_stale_session_on_result_triggers_a_new_session(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    relay.result_steps.append(STALE)
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session))
        await wait_until(lambda: len(relay.registers) == 2)
    assert len(relay.results) == 1
    assert len(set(relay.session_ids)) == 2
    assert len(elsa.requests) == 1


# ---------------------------------------------------------------------------
# Limpieza, secretos y fronteras
# ---------------------------------------------------------------------------


async def test_shutdown_cancels_everything_and_keeps_no_request(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    elsa.hold()
    agent = _build(relay, elsa, sleeps)
    task = asyncio.create_task(agent.run())
    session = await _registered(relay, agent)
    ids = set()
    for _ in range(3):
        request = make_request(session)
        ids.add(request.request_id)
        relay.push_request(request)
    del request
    await wait_until(lambda: agent.active_jobs == 3)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    assert agent.active_jobs == 0
    assert agent.pending_replies == 0
    assert agent.session_id is None
    assert elsa.cancelled == 1
    assert _other_tasks() == set()
    gc.collect()
    alive = [o for o in gc.get_objects() if isinstance(o, Request) and o.request_id in ids]
    assert alive == []


async def test_finished_requests_are_not_retained(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    elsa.steps.append(httpx.Response(500))
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        ok, failing = make_request(session), make_request(session)
        ids = {ok.request_id, failing.request_id}
        relay.push_request(failing)
        relay.push_request(ok)
        del ok, failing
        await wait_until(lambda: len(relay.results) == 2 and agent.active_jobs == 0)
        gc.collect()
        alive = [o for o in gc.get_objects() if isinstance(o, Request) and o.request_id in ids]
        assert alive == []


async def test_logs_never_contain_secrets_or_payloads(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    from elsa.relay.protocol import AttachmentMeta

    elsa.steps.append(httpx.Response(403, json=error_body("insufficient_permissions")))
    relay.result_steps.append(httpx.ReadError("ack lost"))
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        attachments = [AttachmentMeta(filename=ATTACHMENT_NAME, byte_size=1)]
        relay.push_request(make_request(session, attachments=attachments))
        relay.push_request(make_request(session, attachments=attachments))
        await wait_until(lambda: len(relay.results) >= 3 and agent.active_jobs == 0)

    records = agent_logs.records + caplog.records
    assert records
    text = "\n".join(
        f"{record.getMessage()} {sorted(record.__dict__.items(), key=str)}" for record in records
    )
    for secret in (
        NODE_TOKEN,
        USER_TOKEN,
        "Bearer",
        QUESTION,
        RESULT_TEXT,
        ATTACHMENT_NAME,
        "local:",
        "agent:",
        "insufficient_permissions",
    ):
        assert secret not in text
    assert {"node_registered", "request_accepted", "result_delivered"} <= set(_events(agent_logs))


def test_agent_package_respects_its_boundaries() -> None:
    """Solo saliente y sin depender de la app: lo comprueba el código, no una promesa.

    Comprueba los imports **directos** del paquete. De los módulos del relay y
    de ELSA solo se admiten los nombres concretos que el agente necesita: el
    contrato, la cabecera del nodo, los límites del cable y el formateador de
    logs. Importar ``RelayService`` o la configuración de ELSA haría fallar
    este test.
    """
    allowed_names: dict[str, set[str] | None] = {
        "elsa.relay.protocol": None,  # el contrato completo
        "elsa.relay.auth": {"NODE_TOKEN_HEADER"},
        "elsa.relay.service": {
            "MAX_ERROR_WIRE_BYTES",
            "MAX_REQUEST_WIRE_BYTES",
            "MAX_RESPONSE_WIRE_BYTES",
        },
        "elsa.logging": {"configure_logging"},
    }
    forbidden = ("fastapi", "uvicorn", "http.server", "socketserver", "subprocess", "socket")
    package = Path(agent_package.__file__).parent
    for source in package.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden), f"{source.name}: {alias.name}"
                    assert not alias.name.startswith("elsa"), f"{source.name}: {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                assert not module.startswith(forbidden), f"{source.name}: {module}"
                if module.startswith("elsa") and not module.startswith("elsa.agent"):
                    assert module in allowed_names, f"{source.name} imports {module}"
                    allowed = allowed_names[module]
                    imported = {alias.name for alias in node.names}
                    assert allowed is None or imported <= allowed, (
                        f"{source.name} imports {imported - (allowed or set())} from {module}"
                    )
            if isinstance(node, ast.Attribute):
                assert node.attr not in ("start_server", "create_server"), source.name


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------


def test_main_refuses_to_start_without_configuration(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    for name in ("ELSA_AGENT_RELAY_URL", "ELSA_AGENT_NODE_ID", "ELSA_AGENT_NODE_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--env-file", str(tmp_path / "missing.env")]) == EXIT_FATAL
    assert "ELSA_AGENT_RELAY_URL" in capsys.readouterr().err


async def test_run_agent_wires_the_configuration_and_stops_on_bad_credentials(
    relay: FakeRelay, elsa: FakeLocalElsa
) -> None:
    relay.register_steps.append(httpx.Response(401, json=error_body("unauthorized")))
    settings = AgentSettings(
        _env_file=None,  # type: ignore[call-arg]
        relay_url=RELAY_BASE,
        node_id=NODE_ID,
    )
    config = AgentConfig(settings=settings, node_token=SecretStr(NODE_TOKEN))
    code = await asyncio.wait_for(
        run_agent(config, relay_transport=relay.transport, local_transport=elsa.transport), 3
    )
    assert code == EXIT_FATAL
    [sent] = relay.requests
    assert sent.raw_path == "/api/v1/relay/node/register"
    assert sent.headers[NODE_TOKEN_HEADER.lower()] == NODE_TOKEN


# ---------------------------------------------------------------------------
# Revisión pre-PR: renovación con espera, una sola transición, fallos de
# serialización, tamaño en bytes y arranque con el token en archivo
# ---------------------------------------------------------------------------


async def test_repeated_stale_sessions_back_off_and_register_200_does_not_reset(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    """Dos agentes con el mismo nodo se reemplazarían sin freno: aquí hay espera."""
    for _ in range(6):
        relay.poll_steps.append(STALE)
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        await wait_until(lambda: len(relay.registers) == 7)
        await wait_until(lambda: len(relay.polls) >= 8)
    # Cada renovación espera, y REGISTER 200 no reinicia el contador.
    assert sleeps.delays[:6] == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]
    assert len(set(relay.session_ids)) == 7


async def test_backoff_resets_only_after_a_successful_poll(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    relay.poll_steps.extend([STALE, STALE])
    relay.poll_steps.append(httpx.Response(200, json={"message": None}))
    relay.poll_steps.append(STALE)
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        await wait_until(lambda: len(relay.registers) == 4)
    # 1 s, 2 s; poll OK (ritmo de poll vacío); y el siguiente stale vuelve a 1 s.
    assert sleeps.delays[0:2] == [1.0, 2.0]
    assert sleeps.delays[2] <= MIN_EMPTY_POLL_SECONDS  # ritmo del poll vacío
    assert sleeps.delays[3] == 1.0


async def test_concurrent_stale_on_poll_and_result_renews_exactly_once(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    gate = asyncio.Event()
    blocked = {"poll": False, "result": False}

    async def stale_after_gate(kind: str) -> httpx.Response:
        blocked[kind] = True
        await gate.wait()
        return httpx.Response(409, json=error_body("stale_session"))

    async def result_step(request: httpx.Request) -> httpx.Response:
        return await stale_after_gate("result")

    async def poll_step(request: httpx.Request) -> httpx.Response:
        return await stale_after_gate("poll")

    relay.result_steps.append(result_step)
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session_a = await _registered(relay, agent)
        relay.push_request(make_request(session_a))
        await wait_until(lambda: blocked["result"])
        relay.poll_steps.append(poll_step)
        await wait_until(lambda: blocked["poll"])
        gate.set()  # poll y result responden stale a la vez
        await wait_until(lambda: len(relay.registers) == 2)
        session_b = relay.session_ids[1]
        await wait_until(
            lambda: sum(UUID(p["node_session_id"]) == session_b for p in relay.polls) >= 3
        )
    assert session_b != session_a
    assert len(relay.registers) == 2  # A → B, una sola vez
    assert agent.session_id is None  # el agente se detuvo limpio
    assert len(relay.results) == 1  # el resultado de A nunca viaja con B
    assert relay.results[0]["node_session_id"] == str(session_a)
    assert len(elsa.requests) == 1


async def test_unencodable_result_degrades_to_a_sanitized_error(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    elsa.steps.append(
        httpx.Response(200, content=f'{{"message": "{RESULT_TEXT} \\ud800"}}'.encode())
    )
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        relay.push_request(make_request(session))
        await wait_until(lambda: len(relay.results) == 1 and agent.active_jobs == 0)
    gc.collect()  # una excepción sin recoger se reportaría al destruir la tarea
    [result] = relay.results
    assert (result["code"], result["detail"]) == ("LOCAL_ERROR", "local:invalid_response")
    assert "result_encoding_failed" in _events(agent_logs)
    text = "\n".join(
        f"{r.getMessage()} {sorted(r.__dict__.items(), key=str)}"
        for r in agent_logs.records + caplog.records
    )
    assert RESULT_TEXT not in text
    assert "never retrieved" not in text


async def test_unexpected_error_stops_the_agent_without_leaking_its_text(
    relay: FakeRelay,
    elsa: FakeLocalElsa,
    sleeps: SleepRecorder,
    agent_logs: _ListHandler,
) -> None:
    async def explode(request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"unexpected {NODE_TOKEN} {USER_TOKEN}")

    relay.poll_steps.append(explode)
    agent = _build(relay, elsa, sleeps)
    assert await asyncio.wait_for(agent.run(), 3) == EXIT_CRASH
    assert "agent_crashed" in _events(agent_logs)
    text = " ".join(f"{sorted(r.__dict__.items(), key=str)}" for r in agent_logs.records)
    assert NODE_TOKEN not in text and USER_TOKEN not in text
    assert _other_tasks() == set()


def test_response_size_is_counted_in_utf8_bytes_like_the_relay(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    agent = _build(relay, elsa, sleeps)
    job_session, job_request = uuid4(), uuid4()

    from elsa.agent.runner import _Job

    job = _Job(request_id=job_request, session_id=job_session)
    # Por debajo del límite: el cuerpo es exactamente lo que mide el relay.
    small: dict[str, JsonValue] = {"m": "ñ€😀" * 1000}
    body = agent._encode(job, LocalSuccess(small))
    message = Response(
        node_id=NODE_ID, node_session_id=job_session, request_id=job_request, result=small
    )
    assert body == encode_message(message)
    assert len(body) == _wire_size(message.model_dump(mode="json"))

    # Menos caracteres que el límite, pero más bytes UTF-8: no cabe.
    big: dict[str, JsonValue] = {"m": "ñ" * (MAX_RESPONSE_WIRE_BYTES // 2 + 10)}
    assert len(json.dumps(big, ensure_ascii=False)) < MAX_RESPONSE_WIRE_BYTES
    rejected = json.loads(agent._encode(job, LocalSuccess(big)))
    assert (rejected["code"], rejected["detail"]) == ("LOCAL_ERROR", "local:response_too_large")


async def test_cancelled_request_is_released_without_waiting_for_the_gc(
    relay: FakeRelay, elsa: FakeLocalElsa, sleeps: SleepRecorder
) -> None:
    elsa.hold()
    agent = _build(relay, elsa, sleeps)
    async with _running(agent):
        session = await _registered(relay, agent)
        request = make_request(session)
        rid = request.request_id
        relay.push_request(request)
        del request
        await elsa.started.wait()
        gc.collect()
        gc.disable()
        try:
            relay.push(
                Cancel(node_id=NODE_ID, node_session_id=session, request_id=rid).model_dump(
                    mode="json"
                )
            )
            await wait_until(lambda: agent.active_jobs == 0 and elsa.cancelled == 1)
            await asyncio.sleep(0.01)
            alive = [o for o in gc.get_objects() if isinstance(o, Request) and o.request_id == rid]
        finally:
            gc.enable()
    assert alive == []


def test_main_refuses_a_node_token_in_the_env_file_even_with_one_in_the_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    env_file = tmp_path / "agent.env"
    env_file.write_text(
        f"ELSA_AGENT_RELAY_URL={RELAY_BASE}\nELSA_AGENT_NODE_ID={NODE_ID}\n"
        f"ELSA_AGENT_NODE_TOKEN=file-{'z' * 40}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ELSA_AGENT_NODE_TOKEN", NODE_TOKEN)
    assert main(["--env-file", str(env_file)]) == EXIT_FATAL
    err = capsys.readouterr().err
    assert "must not be stored in the configuration file" in err
    assert "zzzz" not in err and NODE_TOKEN not in err
