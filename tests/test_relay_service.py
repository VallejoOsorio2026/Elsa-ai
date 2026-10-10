"""Relay Render–PC1 (D2.2): store, service, autenticación del nodo y configuración.

Todo con un nodo simulado: ninguna red, ningún PC1, datos sintéticos. El reloj
se inyecta; las pruebas con tiempo real usan milisegundos.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr, ValidationError

from elsa.relay.auth import NodeCredentialVerifier, hash_node_token
from elsa.relay.protocol import (
    AskParams,
    AttachmentMeta,
    Cancel,
    CancelEffect,
    ErrorCode,
    ErrorMessage,
    Heartbeat,
    Register,
    Request,
    Response,
)
from elsa.relay.service import (
    MAX_USER_TOKEN_CHARS,
    RelayPolicy,
    RelayService,
    RequestNotPendingError,
    ResponseTooLargeError,
    StaleSessionError,
)
from elsa.relay.store import RelayFailure
from tests.conftest import make_test_settings

pytestmark = pytest.mark.anyio

NODE_ID = "pc1-pilot"
USER_TOKEN = SecretStr("synthetic-user-access-token")
QUESTION = "synthetic-sensitive-question"
RESULT_TEXT = "synthetic-sensitive-result"
SESSION_A = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
SESSION_B = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def make_service(clock: FakeClock | None = None, **policy: Any) -> tuple[RelayService, FakeClock]:
    clock = clock or FakeClock()
    values: dict[str, Any] = {
        "node_id": NODE_ID,
        "node_ttl_seconds": 45.0,
        "long_poll_seconds": 0.05,
        "request_ttl_seconds": 120.0,
        "max_pending": 16,
    }
    values.update(policy)
    return RelayService(RelayPolicy(**values), clock=clock), clock


def make_real_time_service(**policy: Any) -> RelayService:
    """Reloj real: para las pruebas que dependen de los deadlines asíncronos."""
    service, _ = make_service(clock=FakeClock(), **policy)
    return RelayService(service.policy, clock=lambda: datetime.now(UTC))


def params(question: str = QUESTION) -> AskParams:
    return AskParams(domain="mantenimiento", asset="tampella", question=question)


def register(service: RelayService, session: UUID = SESSION_A) -> None:
    service.register(Register(node_id=NODE_ID, node_session_id=session))


def heartbeat(session: UUID = SESSION_A) -> Heartbeat:
    return Heartbeat(node_id=NODE_ID, node_session_id=session)


def response(request_id: UUID, session: UUID = SESSION_A) -> Response:
    return Response(
        node_id=NODE_ID,
        node_session_id=session,
        request_id=request_id,
        result={"message": RESULT_TEXT},
    )


def node_error(
    request_id: UUID, session: UUID = SESSION_A, code: ErrorCode = ErrorCode.LOCAL_ERROR
) -> ErrorMessage:
    return ErrorMessage(
        node_id=NODE_ID,
        node_session_id=session,
        request_id=request_id,
        code=code,
        detail="synthetic failure",
    )


async def settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def start_submit(service: RelayService, **kwargs: Any) -> "asyncio.Task[Any]":
    return asyncio.create_task(service.submit(params(), USER_TOKEN, **kwargs))


async def poll_request(service: RelayService, session: UUID = SESSION_A) -> Request:
    message = await service.poll(heartbeat(session))
    assert isinstance(message, Request)
    return message


def assert_clean(service: RelayService) -> None:
    """Nada retenido: ni solicitudes, ni cola, ni cancels, ni esperas de poll."""
    store = service.store
    assert store.pending_count == 0
    assert store.queue_length == 0
    assert store.cancel_backlog == 0
    assert not service._poll_waiters  # noqa: SLF001


# ---------------------------------------------------------------------------
# Camino feliz y fallos básicos
# ---------------------------------------------------------------------------


async def test_end_to_end_with_simulated_node() -> None:
    service, _ = make_service()
    register(service)
    task = start_submit(service)
    await settle()

    request = await poll_request(service)
    assert request.node_session_id == SESSION_A
    assert request.params.question == QUESTION
    # El token llega al nodo por la representación de transporte, y solo ahí.
    assert request.to_wire_dict()["user_access_token"] == "synthetic-user-access-token"

    service.accept_result(response(request.request_id))
    outcome = await asyncio.wait_for(task, 1)

    assert isinstance(outcome, Response)
    assert outcome.request_id == request.request_id
    assert outcome.result == {"message": RESULT_TEXT}
    assert_clean(service)


async def test_offline_node_fails_immediately() -> None:
    service, _ = make_service()
    outcome = await asyncio.wait_for(service.submit(params(), USER_TOKEN), 1)
    assert outcome == RelayFailure(ErrorCode.LOCAL_UNAVAILABLE, "the local node is offline")
    assert_clean(service)


async def test_node_goes_offline_when_ttl_elapses_and_poll_revives_it() -> None:
    service, clock = make_service()
    register(service)
    assert service.is_online()

    clock.advance(46)
    assert not service.is_online()
    assert isinstance(await service.submit(params(), USER_TOKEN), RelayFailure)

    assert await service.poll(heartbeat()) is None  # el poll es la señal de vida
    assert service.is_online()


async def test_error_from_node_becomes_a_failure_with_its_code() -> None:
    service, _ = make_service()
    register(service)
    task = start_submit(service)
    await settle()
    request = await poll_request(service)

    service.accept_result(node_error(request.request_id, code=ErrorCode.FORBIDDEN))
    outcome = await asyncio.wait_for(task, 1)

    assert outcome == RelayFailure(ErrorCode.FORBIDDEN, "synthetic failure")
    assert_clean(service)


# ---------------------------------------------------------------------------
# Sesiones
# ---------------------------------------------------------------------------


async def test_stale_session_response_is_rejected_and_nothing_is_replayed() -> None:
    service, _ = make_service()
    register(service, SESSION_A)
    task = start_submit(service)
    await settle()
    request = await poll_request(service, SESSION_A)

    register(service, SESSION_B)  # la sesión A queda invalidada

    # Lo despachado a A falla explícitamente; no se reejecuta.
    outcome = await asyncio.wait_for(task, 1)
    assert isinstance(outcome, RelayFailure)
    assert outcome.code is ErrorCode.LOCAL_UNAVAILABLE

    with pytest.raises(StaleSessionError):
        service.accept_result(response(request.request_id, SESSION_A))
    with pytest.raises(StaleSessionError):
        await service.poll(heartbeat(SESSION_A))
    # Y la sesión B no recibe la solicitud vieja.
    assert await service.poll(heartbeat(SESSION_B)) is None
    assert_clean(service)


async def test_queued_requests_survive_register_but_never_reuse_the_old_session() -> None:
    service, _ = make_service()
    register(service, SESSION_A)
    task = start_submit(service)
    await settle()  # en cola, sin despachar

    register(service, SESSION_B)
    request = await poll_request(service, SESSION_B)

    assert request.node_session_id == SESSION_B
    assert request.node_session_id != SESSION_A
    service.accept_result(response(request.request_id, SESSION_B))
    assert isinstance(await asyncio.wait_for(task, 1), Response)
    assert_clean(service)


async def test_registering_the_same_session_again_does_not_fail_in_flight_work() -> None:
    service, _ = make_service()
    register(service, SESSION_A)
    task = start_submit(service)
    await settle()
    request = await poll_request(service)

    register(service, SESSION_A)
    service.accept_result(response(request.request_id))

    assert isinstance(await asyncio.wait_for(task, 1), Response)


async def test_unknown_session_is_rejected() -> None:
    service, _ = make_service()
    with pytest.raises(StaleSessionError):
        await service.poll(heartbeat(SESSION_A))
    register(service, SESSION_A)
    with pytest.raises(StaleSessionError):
        await service.poll(heartbeat(SESSION_B))


# ---------------------------------------------------------------------------
# Correlación, duplicados, at-most-once
# ---------------------------------------------------------------------------


async def test_duplicate_response_is_rejected_without_double_resolution() -> None:
    service, _ = make_service()
    register(service)
    task = start_submit(service)
    await settle()
    request = await poll_request(service)

    service.accept_result(response(request.request_id))
    first = await asyncio.wait_for(task, 1)
    with pytest.raises(RequestNotPendingError):
        service.accept_result(node_error(request.request_id))
    with pytest.raises(RequestNotPendingError):
        service.accept_result(response(request.request_id))

    assert isinstance(first, Response)
    assert_clean(service)


async def test_unknown_request_id_is_rejected() -> None:
    service, _ = make_service()
    register(service)
    with pytest.raises(RequestNotPendingError):
        service.accept_result(response(uuid4()))


async def test_a_dispatched_request_is_never_delivered_twice() -> None:
    service, _ = make_service()
    register(service)
    task = start_submit(service)
    await settle()
    request = await poll_request(service)

    # El nodo "se desconecta" y vuelve a preguntar: no hay replay.
    assert await service.poll(heartbeat()) is None
    assert await service.poll(heartbeat()) is None

    service.accept_result(response(request.request_id))
    await asyncio.wait_for(task, 1)


async def test_concurrent_polls_deliver_each_request_exactly_once() -> None:
    service, _ = make_service()
    register(service)
    tasks = [start_submit(service) for _ in range(3)]
    await settle()

    messages = await asyncio.gather(*(service.poll(heartbeat()) for _ in range(8)))
    delivered = [m.request_id for m in messages if isinstance(m, Request)]

    assert len(delivered) == 3
    assert len(set(delivered)) == 3
    for request_id in delivered:
        service.accept_result(response(request_id))
    outcomes = await asyncio.wait_for(asyncio.gather(*tasks), 1)
    assert all(isinstance(o, Response) for o in outcomes)
    assert_clean(service)


async def test_user_token_is_dropped_once_dispatched() -> None:
    service, _ = make_service()
    register(service)
    task = start_submit(service)
    await settle()
    (entry,) = list(service.store._pending.values())  # noqa: SLF001
    assert entry.user_access_token is not None

    request = await poll_request(service)
    assert entry.user_access_token is None

    service.accept_result(response(request.request_id))
    await asyncio.wait_for(task, 1)


# ---------------------------------------------------------------------------
# Expiración y caída del nodo
# ---------------------------------------------------------------------------


async def test_request_expiry_with_injected_clock_blocks_late_response() -> None:
    service, clock = make_service()
    register(service)
    task = start_submit(service)
    await settle()
    request = await poll_request(service)
    # El nodo sigue vivo (poll), pero la solicitud supera su plazo.
    clock.advance(30)
    assert await service.poll(heartbeat()) is None
    clock.advance(30)
    assert await service.poll(heartbeat()) is None
    clock.advance(61)
    service.enforce_deadlines()

    outcome = await asyncio.wait_for(task, 1)
    assert isinstance(outcome, RelayFailure)
    assert outcome.code is ErrorCode.TIMEOUT
    with pytest.raises(RequestNotPendingError):
        service.accept_result(response(request.request_id))
    assert_clean(service)


async def test_queued_request_expires_in_real_time_without_any_other_call() -> None:
    service = make_real_time_service(request_ttl_seconds=0.1)
    register(service)

    outcome = await asyncio.wait_for(service.submit(params(), USER_TOKEN), 2)

    assert isinstance(outcome, RelayFailure)
    assert outcome.code is ErrorCode.TIMEOUT
    assert_clean(service)


async def test_node_ttl_fails_in_flight_work_without_any_other_operation() -> None:
    service = make_real_time_service(node_ttl_seconds=0.15, long_poll_seconds=0.05)
    register(service)
    task = start_submit(service)
    await settle()
    request = await poll_request(service)

    # Nadie vuelve a llamar: el propio deadline asíncrono del que espera dispara.
    outcome = await asyncio.wait_for(task, 2)

    assert isinstance(outcome, RelayFailure)
    assert outcome.code is ErrorCode.LOCAL_UNAVAILABLE
    with pytest.raises(RequestNotPendingError):
        service.accept_result(response(request.request_id))
    assert_clean(service)


async def test_polling_while_working_keeps_the_in_flight_request_alive() -> None:
    service = make_real_time_service(node_ttl_seconds=0.3, long_poll_seconds=0.05)
    register(service)
    task = start_submit(service)
    await settle()
    request = await poll_request(service)

    for _ in range(8):  # ~0.4 s > TTL, pero el nodo sigue haciendo poll
        assert await service.poll(heartbeat()) is None
    assert not task.done()

    service.accept_result(response(request.request_id))
    assert isinstance(await asyncio.wait_for(task, 1), Response)


# ---------------------------------------------------------------------------
# Capacidad y límites
# ---------------------------------------------------------------------------


async def test_capacity_rejects_the_next_request_without_disturbing_the_pending() -> None:
    service, _ = make_service(max_pending=2)
    register(service)
    first, second = start_submit(service), start_submit(service)
    await settle()

    rejected = await asyncio.wait_for(service.submit(params(), USER_TOKEN), 1)

    assert rejected == RelayFailure(ErrorCode.LOCAL_UNAVAILABLE, "the relay is at capacity")
    assert service.store.pending_count == 2
    assert not first.done()
    assert not second.done()
    for _ in range(2):
        request = await poll_request(service)
        service.accept_result(response(request.request_id))
    outcomes = await asyncio.wait_for(asyncio.gather(first, second), 1)
    assert all(isinstance(o, Response) for o in outcomes)
    assert_clean(service)


async def test_oversized_user_token_is_rejected() -> None:
    service, _ = make_service()
    register(service)
    token = SecretStr("x" * (MAX_USER_TOKEN_CHARS + 1))
    outcome = await service.submit(params(), token)
    assert isinstance(outcome, RelayFailure)
    assert outcome.code is ErrorCode.INVALID_REQUEST
    assert_clean(service)


async def test_oversized_request_wire_is_rejected() -> None:
    service, _ = make_service()
    register(service)
    big = AskParams(
        domain="mantenimiento",
        asset="tampella",
        question=QUESTION,
        attachments=[
            AttachmentMeta(filename="f" * 255, byte_size=1, content_type="c" * 255)
            for _ in range(60)
        ],
    )
    outcome = await service.submit(big, USER_TOKEN)
    assert isinstance(outcome, RelayFailure)
    assert outcome.code is ErrorCode.INVALID_REQUEST
    assert_clean(service)


async def test_oversized_response_fails_the_request_explicitly() -> None:
    service, _ = make_service()
    register(service)
    task = start_submit(service)
    await settle()
    request = await poll_request(service)
    huge = Response(
        node_id=NODE_ID,
        node_session_id=SESSION_A,
        request_id=request.request_id,
        result={"blob": "x" * (300 * 1024)},
    )

    with pytest.raises(ResponseTooLargeError):
        service.accept_result(huge)

    outcome = await asyncio.wait_for(task, 1)
    assert isinstance(outcome, RelayFailure)
    assert outcome.code is ErrorCode.LOCAL_ERROR
    assert_clean(service)


async def test_duplicate_request_id_is_rejected() -> None:
    service, _ = make_service()
    register(service)
    rid = uuid4()
    first = start_submit(service, request_id=rid)
    await settle()

    outcome = await service.submit(params(), USER_TOKEN, request_id=rid)

    assert outcome == RelayFailure(ErrorCode.DUPLICATE_REQUEST)
    request = await poll_request(service)
    service.accept_result(response(request.request_id))
    await asyncio.wait_for(first, 1)


# ---------------------------------------------------------------------------
# Cancelación
# ---------------------------------------------------------------------------


async def test_cancel_queued_removes_it_before_dispatch() -> None:
    service, _ = make_service()
    register(service)
    rid = uuid4()
    task = start_submit(service, request_id=rid)
    await settle()

    assert service.cancel(rid) is CancelEffect.ALLOWED

    outcome = await asyncio.wait_for(task, 1)
    assert outcome == RelayFailure(ErrorCode.CANCELLED)
    assert await service.poll(heartbeat()) is None
    assert_clean(service)


async def test_cancel_dispatched_notifies_the_node_best_effort() -> None:
    service, _ = make_service()
    register(service)
    task = start_submit(service)
    await settle()
    request = await poll_request(service)

    assert service.cancel(request.request_id) is CancelEffect.ATTEMPT

    outcome = await asyncio.wait_for(task, 1)
    assert outcome == RelayFailure(ErrorCode.CANCELLED)
    message = await service.poll(heartbeat())
    assert isinstance(message, Cancel)
    assert message.request_id == request.request_id
    assert message.node_session_id == SESSION_A
    with pytest.raises(RequestNotPendingError):
        service.accept_result(response(request.request_id))
    assert_clean(service)


async def test_cancelling_the_caller_releases_the_request() -> None:
    service, _ = make_service()
    register(service)
    task = start_submit(service)
    await settle()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert_clean(service)


async def test_cancel_of_unknown_request_is_not_applicable() -> None:
    service, _ = make_service()
    assert service.cancel(uuid4()) is CancelEffect.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Logs sanitizados
# ---------------------------------------------------------------------------


async def test_logs_never_contain_tokens_questions_or_results(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    service, clock = make_service(request_ttl_seconds=0.5)
    register(service, SESSION_A)

    ok = start_submit(service)
    await settle()
    request = await poll_request(service)
    service.accept_result(response(request.request_id))
    await ok

    failed = start_submit(service)
    await settle()
    request = await poll_request(service)
    service.accept_result(node_error(request.request_id))
    await failed

    expired = start_submit(service)
    await settle()
    clock.advance(1)  # supera el TTL de la solicitud; el nodo sigue dentro del suyo
    service.enforce_deadlines()
    await expired

    late = start_submit(service)
    await settle()
    request = await poll_request(service)
    register(service, SESSION_B)
    await late
    with pytest.raises(StaleSessionError):
        service.accept_result(response(request.request_id, SESSION_A))
    clock.advance(100)
    await service.submit(params(), USER_TOKEN)

    text = "\n".join(
        f"{record.getMessage()} {sorted(record.__dict__.items(), key=str)}"
        for record in caplog.records
    )
    for secret in (
        "synthetic-user-access-token",
        "synthetic-node-token",
        QUESTION,
        RESULT_TEXT,
        "synthetic failure",
    ):
        assert secret not in text
    events = {getattr(r, "event", None) for r in caplog.records}
    assert {
        "node_registered",
        "node_session_replaced",
        "request_queued",
        "request_dispatched",
        "request_completed",
        "request_failed",
        "request_expired",
        "stale_session",
        "node_offline",
    } <= events


# ---------------------------------------------------------------------------
# Autenticación del nodo
# ---------------------------------------------------------------------------


def test_verifier_accepts_current_and_previous_and_rejects_the_rest() -> None:
    current, previous = "synthetic-node-token", "synthetic-node-token-old"
    verifier = NodeCredentialVerifier(NODE_ID, hash_node_token(current), hash_node_token(previous))

    assert verifier.verify_token(current)
    assert verifier.verify_token(previous)
    assert not verifier.verify_token("synthetic-node-token-wrong")
    assert not verifier.verify_token("")
    assert not verifier.verify_token(None)
    assert verifier.node_id_matches(NODE_ID)
    assert not verifier.node_id_matches("another-node")


def test_verifier_without_previous_hash_rejects_the_old_token() -> None:
    verifier = NodeCredentialVerifier(NODE_ID, hash_node_token("synthetic-node-token"))
    assert not verifier.verify_token("synthetic-node-token-old")


# ---------------------------------------------------------------------------
# Configuración fail-closed
# ---------------------------------------------------------------------------

_HASH = hash_node_token("synthetic-node-token")


def test_relay_is_disabled_by_default() -> None:
    settings = make_test_settings()
    assert settings.relay_enabled is False


def test_enabled_with_complete_configuration_is_valid() -> None:
    settings = make_test_settings(
        relay_enabled=True,
        relay_node_id=NODE_ID,
        relay_node_token_sha256=SecretStr(_HASH),
        relay_node_token_sha256_previous=SecretStr(hash_node_token("synthetic-node-token-old")),
    )
    assert settings.relay_enabled is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"relay_node_id": None},
        {"relay_node_token_sha256": None},
        {"relay_node_id": "no valid/id"},
        {"relay_node_token_sha256": SecretStr("not-a-sha256")},
        {"relay_node_token_sha256": SecretStr(_HASH.upper())},
        {"relay_node_token_sha256_previous": SecretStr("short")},
        {"relay_long_poll_seconds": 45.0},
        {"relay_long_poll_seconds": 60.0},
        {"relay_node_ttl_seconds": 0.0},
        {"relay_request_ttl_seconds": -1.0},
        {"relay_max_pending": 0},
    ],
)
def test_enabled_with_incomplete_or_invalid_configuration_fails(
    overrides: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "relay_enabled": True,
        "relay_node_id": NODE_ID,
        "relay_node_token_sha256": SecretStr(_HASH),
    }
    values.update(overrides)
    with pytest.raises(ValidationError) as excinfo:
        make_test_settings(**values)
    assert _HASH not in str(excinfo.value)


def test_a_blank_hash_counts_as_missing() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(
            relay_enabled=True,
            relay_node_id=NODE_ID,
            relay_node_token_sha256=SecretStr("   "),
        )
