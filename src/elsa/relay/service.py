"""Servicio del relay Render–PC1 (ADR 0031).

Orquesta el :class:`~elsa.relay.store.InMemoryRelayStore`: valida límites,
decide la vigencia del nodo con un reloj inyectable, espera con *deadlines*
asíncronos y registra eventos sanitizados. No conoce HTTP.

Dos consumidores:

- **La API de nodo** (``elsa.api.v1.relay``) llama a :meth:`register`,
  :meth:`poll` y :meth:`accept_result` en nombre de PC1.
- **D2.4** llamará a :meth:`submit` con ``AskParams`` y el token temporal del
  usuario. No conoce ``node_session_id``: lo asigna el relay al despachar.

Seguridad de los logs: solo identificadores, estado, código y duración. Nunca
el token del nodo, el del usuario, la pregunta, el resultado, el ``detail`` de
un error ni ningún cuerpo del cable. ``Request.to_wire_dict()`` lo llama
únicamente la capa HTTP, al responder al nodo.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from pydantic import SecretStr

from elsa.config import Settings
from elsa.relay.protocol import (
    AskParams,
    Cancel,
    CancelEffect,
    ErrorCode,
    ErrorMessage,
    Heartbeat,
    Operation,
    Register,
    Request,
    RequestState,
    Response,
    cancel_effect,
)
from elsa.relay.store import (
    InMemoryRelayStore,
    PendingRequest,
    RelayCapacityError,
    RelayFailure,
)

__all__ = [
    "MAX_ERROR_WIRE_BYTES",
    "MAX_REQUEST_WIRE_BYTES",
    "MAX_RESPONSE_WIRE_BYTES",
    "MAX_USER_TOKEN_CHARS",
    "RelayPolicy",
    "RelayService",
    "RequestNotPendingError",
    "ResponseTooLargeError",
    "StaleSessionError",
]

MAX_USER_TOKEN_CHARS = 4096
MAX_REQUEST_WIRE_BYTES = 16 * 1024
MAX_RESPONSE_WIRE_BYTES = 256 * 1024
MAX_ERROR_WIRE_BYTES = 2 * 1024
"""Límites de tamaño del piloto, justificados en ADR 0031 §4."""

_MIN_WAIT_SECONDS = 0.001

_logger = logging.getLogger("elsa.relay")


class StaleSessionError(Exception):
    """La sesión del mensaje no es la vigente (desconocida o antigua)."""


class RequestNotPendingError(Exception):
    """``request_id`` desconocido, duplicado, expirado o de otra sesión."""


class ResponseTooLargeError(Exception):
    """La respuesta del nodo excede el límite; la solicitud ya se marcó fallida."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RelayPolicy:
    """Identidad, plazos y capacidad. Valores de partida del piloto (ADR 0031)."""

    node_id: str
    node_ttl_seconds: float = 45.0
    long_poll_seconds: float = 25.0
    request_ttl_seconds: float = 120.0
    max_pending: int = 16

    @classmethod
    def from_settings(cls, settings: Settings) -> RelayPolicy:
        assert settings.relay_node_id is not None  # noqa: S101 - garantizado por la configuración
        return cls(
            node_id=settings.relay_node_id,
            node_ttl_seconds=settings.relay_node_ttl_seconds,
            long_poll_seconds=settings.relay_long_poll_seconds,
            request_ttl_seconds=settings.relay_request_ttl_seconds,
            max_pending=settings.relay_max_pending,
        )


def _wire_size(payload: object) -> int:
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


class RelayService:
    def __init__(
        self,
        policy: RelayPolicy,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._policy = policy
        self._clock = clock
        self._ttl = timedelta(seconds=policy.node_ttl_seconds)
        self._store = InMemoryRelayStore(max_pending=policy.max_pending)
        self._poll_waiters: set[asyncio.Future[None]] = set()

    # -- observabilidad interna (no es superficie pública) ---------------

    @property
    def policy(self) -> RelayPolicy:
        return self._policy

    @property
    def store(self) -> InMemoryRelayStore:
        return self._store

    def is_online(self) -> bool:
        return self._store.is_online(self._clock(), self._ttl)

    # -- lado nodo: register / poll / result ----------------------------

    def register(self, message: Register) -> None:
        now = self._clock()
        previous = self._store.session
        replaced = previous is not None and previous.session_id != message.node_session_id
        failed = self._store.register(message.node_id, message.node_session_id, now)
        if replaced:
            self._log("node_session_replaced", node_session_id=message.node_session_id)
        for entry in failed:
            self._log_finished("request_failed", entry, now)
        self._log("node_registered", node_session_id=message.node_session_id)
        self._wake_pollers()

    async def poll(self, message: Heartbeat) -> Request | Cancel | None:
        """Espera trabajo hasta ``long_poll_seconds``. También es la señal de vida.

        Devuelve primero un ``Cancel`` pendiente, luego la siguiente solicitud
        vigente (materializada con la sesión activa), o ``None`` al agotar la
        espera. Varios polls concurrentes son seguros: el despacho es atómico.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._policy.long_poll_seconds
        session_id = message.node_session_id
        while True:
            now = self._clock()
            if not self._store.touch(session_id, now):
                self._log("stale_session", node_session_id=session_id)
                raise StaleSessionError
            self._expire_all(now)

            cancelled_id = self._store.pop_cancel()
            if cancelled_id is not None:
                return Cancel(
                    node_id=self._policy.node_id,
                    node_session_id=session_id,
                    request_id=cancelled_id,
                )

            entry, expired = self._store.pop_queued(now)
            for item in expired:
                self._log_finished("request_expired", item, now)
            if entry is not None:
                return self._materialize(entry, session_id, now)

            remaining = deadline - loop.time()
            if remaining <= 0:
                return None
            waiter: asyncio.Future[None] = loop.create_future()
            self._poll_waiters.add(waiter)
            try:
                await asyncio.wait({waiter}, timeout=remaining)
            finally:
                self._poll_waiters.discard(waiter)
                if not waiter.done():
                    waiter.cancel()

    def accept_result(self, message: Response | ErrorMessage) -> None:
        """Correlaciona la respuesta del nodo con su solicitud.

        Rechaza (sin efecto sobre ninguna solicitud) sesión antigua, duplicado,
        ``request_id`` desconocido o expirado.
        """
        now = self._clock()
        if not self._store.touch(message.node_session_id, now):
            self._log("stale_session", node_session_id=message.node_session_id)
            raise StaleSessionError

        request_id = message.request_id
        entry = self._store.get(request_id) if request_id is not None else None
        if (
            request_id is None
            or entry is None
            or entry.state is not RequestState.DISPATCHED
            or entry.session_id != message.node_session_id
        ):
            self._log(
                "duplicate_response",
                node_session_id=message.node_session_id,
                relay_request_id=request_id,
            )
            raise RequestNotPendingError

        limit = MAX_RESPONSE_WIRE_BYTES if isinstance(message, Response) else MAX_ERROR_WIRE_BYTES
        if _wire_size(message.model_dump(mode="json")) > limit:
            self._fail(
                entry,
                RequestState.FAILED,
                RelayFailure(ErrorCode.LOCAL_ERROR, "the node reply exceeded the size limit"),
                "request_failed",
                now,
            )
            raise ResponseTooLargeError

        if isinstance(message, Response):
            finished = self._store.finish(request_id, RequestState.COMPLETED, message)
            if finished is not None:
                self._log_finished("request_completed", finished, now)
            return

        self._fail(
            entry,
            RequestState.FAILED,
            RelayFailure(message.code, message.detail),
            "request_failed",
            now,
        )

    # -- lado consumidor: submit / cancel -------------------------------

    async def submit(
        self,
        params: AskParams,
        user_access_token: SecretStr,
        *,
        request_id: UUID | None = None,
    ) -> Response | RelayFailure:
        """Somete ``assistant.ask`` al nodo y espera su resultado.

        - Nodo OFFLINE o capacidad agotada: falla de inmediato, sin cola.
        - Si quien espera es cancelado (el navegador se fue), la solicitud se
          cancela: no queda trabajo huérfano ni memoria retenida.
        """
        now = self._clock()
        self._expire_all(now)
        rid = request_id or uuid4()

        session = self._store.session
        if session is None or not self._store.is_online(now, self._ttl):
            self._log("node_offline", node_session_id=session.session_id if session else None)
            return RelayFailure(ErrorCode.LOCAL_UNAVAILABLE, "the local node is offline")
        if self._store.get(rid) is not None:
            return RelayFailure(ErrorCode.DUPLICATE_REQUEST)

        secret = user_access_token.get_secret_value()
        if not secret or len(secret) > MAX_USER_TOKEN_CHARS:
            return RelayFailure(ErrorCode.INVALID_REQUEST, "invalid user access token")

        expires_at = now + timedelta(seconds=self._policy.request_ttl_seconds)
        try:
            trial = Request(
                node_id=self._policy.node_id,
                node_session_id=session.session_id,
                request_id=rid,
                operation=Operation.ASSISTANT_ASK,
                params=params,
                user_access_token=user_access_token,
                created_at=now,
                expires_at=expires_at,
            )
        except ValueError:
            return RelayFailure(ErrorCode.INVALID_REQUEST, "the request is not valid")
        if _wire_size(trial.to_wire_dict()) > MAX_REQUEST_WIRE_BYTES:
            return RelayFailure(ErrorCode.INVALID_REQUEST, "the request exceeds the size limit")

        loop = asyncio.get_running_loop()
        entry = PendingRequest(
            request_id=rid,
            params=params,
            user_access_token=user_access_token,
            created_at=now,
            expires_at=expires_at,
            waiter=loop.create_future(),
            dispatched_signal=loop.create_future(),
        )
        try:
            self._store.add(entry)
        except RelayCapacityError:
            return RelayFailure(ErrorCode.LOCAL_UNAVAILABLE, "the relay is at capacity")
        self._log("request_queued", relay_request_id=rid, node_session_id=session.session_id)
        self._wake_pollers()

        try:
            return await self._wait(entry)
        except asyncio.CancelledError:
            self._cancel_entry(entry, self._clock())
            raise

    def cancel(self, request_id: UUID) -> CancelEffect:
        """Cancelación *best effort*. ``queued`` se retira; ``dispatched`` se avisa."""
        entry = self._store.get(request_id)
        if entry is None:
            return CancelEffect.NOT_APPLICABLE
        effect = cancel_effect(entry.state)
        self._cancel_entry(entry, self._clock())
        return effect

    def enforce_deadlines(self) -> None:
        """Aplica expiración y caída del nodo ahora. Idempotente."""
        self._expire_all(self._clock())

    # -- internos --------------------------------------------------------

    async def _wait(self, entry: PendingRequest) -> Response | RelayFailure:
        """Espera el resultado con deadlines propios, sin scheduler ni sweeps externos.

        Despierta en el primer instante en que la solicitud debe fallar:
        vencimiento propio o, en vuelo, ``last_seen + TTL`` del nodo. Si el nodo
        siguió haciendo poll el deadline se desplazó y se vuelve a esperar.
        """
        while not entry.waiter.done():
            now = self._clock()
            finished = self._store.expire_entry(entry, now, self._ttl)
            if finished is not None:
                self._log_expiry(finished, now)
                break
            deadline = self._store.next_deadline(entry, self._ttl, now)
            timeout = max((deadline - now).total_seconds(), _MIN_WAIT_SECONDS)
            waitables: set[asyncio.Future[Any]] = {entry.waiter}
            if entry.state is RequestState.QUEUED:
                waitables.add(entry.dispatched_signal)
            await asyncio.wait(waitables, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        return entry.waiter.result()

    def _materialize(self, entry: PendingRequest, session_id: UUID, now: datetime) -> Request:
        token = entry.user_access_token
        assert token is not None  # noqa: S101 - una solicitud en cola siempre lo conserva
        request = Request(
            node_id=self._policy.node_id,
            node_session_id=session_id,
            request_id=entry.request_id,
            operation=Operation.ASSISTANT_ASK,
            params=entry.params,
            user_access_token=token,
            created_at=entry.created_at,
            expires_at=entry.expires_at,
        )
        self._store.scrub_token(entry)
        self._log(
            "request_dispatched",
            node_session_id=session_id,
            relay_request_id=entry.request_id,
            state=RequestState.DISPATCHED.value,
        )
        return request

    def _cancel_entry(self, entry: PendingRequest, now: datetime) -> None:
        if entry.state is RequestState.DISPATCHED:
            self._store.enqueue_cancel(entry.request_id)
            self._wake_pollers()
        finished = self._store.finish(
            entry.request_id,
            RequestState.CANCELLED,
            RelayFailure(ErrorCode.CANCELLED),
        )
        if finished is not None:
            self._log_finished("request_failed", finished, now)

    def _fail(
        self,
        entry: PendingRequest,
        state: RequestState,
        failure: RelayFailure,
        event: str,
        now: datetime,
    ) -> None:
        finished = self._store.finish(entry.request_id, state, failure)
        if finished is not None:
            self._log_finished(event, finished, now)

    def _expire_all(self, now: datetime) -> None:
        self._note_node_offline(now)
        for finished in self._store.expire_due(now, self._ttl):
            self._log_expiry(finished, now)

    def _note_node_offline(self, now: datetime) -> None:
        session = self._store.session
        if (
            session is not None
            and not session.offline_noted
            and not self._store.is_online(now, self._ttl)
        ):
            session.offline_noted = True
            self._log("node_offline", node_session_id=session.session_id)

    def _log_expiry(self, finished: PendingRequest, now: datetime) -> None:
        # EXPIRED por plazo propio; FAILED por caída del nodo.
        event = "request_expired" if finished.state is RequestState.EXPIRED else "request_failed"
        self._log_finished(event, finished, now)

    def _wake_pollers(self) -> None:
        for waiter in self._poll_waiters:
            if not waiter.done():
                waiter.set_result(None)
        self._poll_waiters.clear()

    def _log_finished(self, event: str, entry: PendingRequest, now: datetime) -> None:
        self._log(
            event,
            relay_request_id=entry.request_id,
            node_session_id=entry.session_id,
            state=entry.state.value,
            duration_ms=int((now - entry.created_at).total_seconds() * 1000),
        )

    def _log(self, event: str, **fields: object) -> None:
        extra: dict[str, object] = {
            "event": event,
            "node_id": self._policy.node_id,
        }
        for key, value in fields.items():
            if value is not None:
                extra[key] = str(value) if isinstance(value, UUID) else value
        _logger.info(event, extra=extra)
