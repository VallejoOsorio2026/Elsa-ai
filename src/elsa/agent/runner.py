"""Ciclo de vida del agente de PC1 (ADR 0032).

Una sesión es un ``node_session_id`` nuevo, un ``REGISTER`` y un bucle de
poll. Mientras dura:

- **Un único poll en vuelo**, independiente de la ejecución local: la señal
  de vida no se interrumpe aunque ELSA tarde, y los ``Cancel`` llegan
  mientras se ejecuta (ADR 0031 §6).
- **Trabajo acotado.** Como mucho ``max_concurrency`` llamadas simultáneas a
  ELSA y ``max_concurrency + max_queued`` trabajos admitidos; cada trabajo es
  **una** tarea que ejecuta y luego entrega su resultado. Los rechazos
  inmediatos (ocupado, expirado al llegar, ruta insegura) **no crean
  tareas**: van a una cola acotada que atiende un único trabajador; si está
  llena, la respuesta se descarta y el relay vence la solicitud por TTL.
- **Sin busy loop.** Un poll vacío o descartado que vuelve antes de
  ``min_empty_poll_seconds`` espera hasta completarlo; los fallos de red o
  5xx, y cada renovación de sesión, esperan con backoff exponencial, jitter y
  techo. El contador de fallos solo vuelve a cero con un poll exitoso.
- **Una ejecución por solicitud.** ``assistant.ask`` se ejecuta una sola vez
  y su resultado, ya serializado, se transmite como mucho 4 veces (envío + 3
  reintentos), nunca después de ``expires_at``. La garantía at-most-once es
  del relay (nunca reencola lo despachado); el registro de ids vistos del
  agente es una **defensa secundaria** acotada (LRU por sesión).
- **Sesión retirada** (``stale_session``): se cancela su trabajo sin enviar
  nada, se olvidan sus ids y, tras esperar, se registra una sesión con id
  nuevo. Solo ``run`` registra: dos avisos simultáneos de sesión retirada
  producen una única transición. No hay replay.
- **Fallos de configuración** (401/403/404 y cualquier otro 4xx en
  register/poll): el agente termina con :data:`EXIT_FATAL` en vez de insistir.

Los logs solo llevan evento, identificadores, código, estado HTTP, intento y
duración: nunca tokens, pregunta, adjuntos, resultado ni ``detail``.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError

from elsa.agent.local_client import (
    ElsaLocalClient,
    LocalFailure,
    LocalOutcome,
    UnsafePathSegmentError,
    build_ask_path,
)
from elsa.agent.relay_client import PollReply, RelayClient, RelayOutcome, encode_message
from elsa.relay.protocol import (
    Cancel,
    ErrorCode,
    ErrorMessage,
    Heartbeat,
    Register,
    Request,
    Response,
)
from elsa.relay.service import MAX_RESPONSE_WIRE_BYTES

__all__ = [
    "BACKOFF_INITIAL_SECONDS",
    "BACKOFF_MAX_SECONDS",
    "DELIVERY_MARGIN_SECONDS",
    "EXIT_CRASH",
    "EXIT_FATAL",
    "EXIT_OK",
    "MIN_EMPTY_POLL_SECONDS",
    "REPLY_QUEUE_MAX",
    "RESULT_RETRY_DELAYS",
    "NodeAgent",
]

EXIT_OK = 0
EXIT_CRASH = 1
EXIT_FATAL = 2

RESULT_RETRY_DELAYS = (0.5, 1.0, 2.0)
"""Reintentos de ``/result``: con el envío inicial, como mucho 4 transmisiones."""
DELIVERY_MARGIN_SECONDS = 2.0
"""Tiempo reservado antes de ``expires_at`` para entregar el resultado."""
BACKOFF_INITIAL_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 30.0
MIN_EMPTY_POLL_SECONDS = 1.0
REPLY_QUEUE_MAX = 16
"""Rechazos inmediatos pendientes de entrega (``max_pending`` del relay)."""
SEEN_REQUESTS_MAX = 1024

_logger = logging.getLogger("elsa.agent")

Sleep = Callable[[float], Awaitable[None]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class _FatalError(Exception):
    def __init__(self, event: str) -> None:
        super().__init__(event)
        self.event = event


@dataclass(eq=False)
class _Job:
    request_id: UUID
    session_id: UUID
    task: asyncio.Task[None] | None = None


@dataclass(frozen=True)
class _Delivery:
    request_id: UUID
    session_id: UUID
    body: bytes
    """``Response``/``ErrorMessage`` serializado una sola vez. Nunca lleva tokens."""
    expires_at: datetime


def _fatal_event(outcome: RelayOutcome) -> str:
    return "relay_auth_failed" if outcome is RelayOutcome.AUTH else "relay_misconfigured"


class NodeAgent:
    def __init__(
        self,
        *,
        node_id: str,
        relay: RelayClient,
        local: ElsaLocalClient,
        max_concurrency: int = 1,
        max_queued: int = 4,
        local_timeout_seconds: float = 110.0,
        poll_timeout_seconds: float | None = None,
        clock: Callable[[], datetime] = _utc_now,
        sleep: Sleep = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        new_session_id: Callable[[], UUID] = uuid4,
        min_empty_poll_seconds: float = MIN_EMPTY_POLL_SECONDS,
    ) -> None:
        self._node_id = node_id
        self._relay = relay
        self._local = local
        self._capacity = max_concurrency + max_queued
        self._local_timeout = local_timeout_seconds
        self._poll_timeout = poll_timeout_seconds
        self._clock = clock
        self._sleep = sleep
        self._jitter = jitter
        self._new_session_id = new_session_id
        self._min_empty_poll = min_empty_poll_seconds

        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._jobs: dict[UUID, _Job] = {}
        self._seen: OrderedDict[UUID, None] = OrderedDict()
        self._replies: asyncio.Queue[_Delivery] = asyncio.Queue(maxsize=REPLY_QUEUE_MAX)
        self._session_id: UUID | None = None
        self._interrupt = asyncio.Event()
        self._renewal_requested = False
        self._fatal: str | None = None
        self._failures = 0

    # -- observabilidad para pruebas y logs --------------------------------

    @property
    def session_id(self) -> UUID | None:
        return self._session_id

    @property
    def active_jobs(self) -> int:
        return len(self._jobs)

    @property
    def pending_replies(self) -> int:
        return self._replies.qsize()

    # -- ciclo de vida ------------------------------------------------------

    async def run(self) -> int:
        """Corre hasta un fallo fatal (:data:`EXIT_FATAL`) o hasta ser cancelado.

        Un error inesperado termina con :data:`EXIT_CRASH` y se registra solo
        su tipo: su texto podría contener datos de la solicitud.
        """
        reply_worker = asyncio.create_task(self._reply_worker())
        self._log("agent_started")
        try:
            while True:
                await self._register_session()
                await self._poll_loop()
                await self._retire_session()
                # Renovar sin esperar convertiría un reemplazo mutuo (dos agentes
                # con el mismo nodo) en un vaivén register/409 sin freno.
                await self._backoff()
        except _FatalError as fatal:
            self._log(fatal.event, level=logging.ERROR)
            return EXIT_FATAL
        except Exception as exc:
            self._log("agent_crashed", level=logging.ERROR, error=type(exc).__name__)
            return EXIT_CRASH
        finally:
            await self._shutdown(reply_worker)
            self._log("agent_stopped")

    async def _register_session(self) -> None:
        self._session_id = self._new_session_id()
        self._renewal_requested = False
        self._interrupt.clear()
        while True:
            self._raise_if_fatal()
            reply = await self._relay.register(
                Register(node_id=self._node_id, node_session_id=self._session_id)
            )
            if reply.outcome is RelayOutcome.OK:
                # El contador de fallos no vuelve a cero aquí: solo con un poll OK.
                self._log("node_registered")
                if (
                    reply.long_poll_seconds is not None
                    and self._poll_timeout is not None
                    and reply.long_poll_seconds >= self._poll_timeout
                ):
                    self._log("poll_timeout_too_short", level=logging.WARNING)
                return
            if reply.outcome is RelayOutcome.STALE:
                # El id ya no es válido para el relay: nunca se revive.
                self._log("session_stale", level=logging.WARNING)
                self._session_id = self._new_session_id()
            elif reply.outcome is RelayOutcome.TRANSIENT:
                self._log(
                    "register_failed",
                    level=logging.WARNING,
                    http_status=reply.http_status,
                    error=reply.error,
                )
            else:
                raise _FatalError(_fatal_event(reply.outcome))
            await self._backoff()

    async def _poll_loop(self) -> None:
        """Vuelve cuando la sesión queda retirada; lanza ``_FatalError`` si es fatal."""
        loop = asyncio.get_running_loop()
        while True:
            self._raise_if_fatal()
            if self._renewal_requested:
                return
            assert self._session_id is not None  # noqa: S101 - fijado al registrar
            started = loop.time()
            reply = await self._poll_or_interrupt(
                Heartbeat(node_id=self._node_id, node_session_id=self._session_id)
            )
            if reply is None:
                continue
            if reply.outcome is RelayOutcome.OK:
                self._failures = 0
                received_request = self._dispatch(reply)
                # Este frame vive toda la sesión: no debe retener el Request (ni su token).
                del reply
                if not received_request:
                    await self._pace(started)
                continue
            if reply.outcome is RelayOutcome.STALE:
                self._log("session_stale", level=logging.WARNING)
                return
            if reply.outcome is RelayOutcome.TRANSIENT:
                self._log(
                    "poll_failed",
                    level=logging.WARNING,
                    http_status=reply.http_status,
                    error=reply.error,
                )
                await self._backoff()
                continue
            raise _FatalError(_fatal_event(reply.outcome))

    def _dispatch(self, reply: PollReply) -> bool:
        """Atiende lo que trajo un poll. ``True`` si era un ``Request``."""
        message = reply.message
        if isinstance(message, Request):
            self._admit(message)
            return True
        if isinstance(message, Cancel):
            self._cancel(message)
        elif reply.discarded:
            self._log("poll_message_discarded", level=logging.WARNING)
        return False

    async def _poll_or_interrupt(self, heartbeat: Heartbeat) -> PollReply | None:
        """Un poll que se abandona si una entrega señala sesión retirada o fallo fatal."""
        poll = asyncio.create_task(self._relay.poll(heartbeat))
        interrupt = asyncio.create_task(self._interrupt.wait())
        try:
            await asyncio.wait({poll, interrupt}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (poll, interrupt):
                if not task.done():
                    task.cancel()
            await asyncio.gather(poll, interrupt, return_exceptions=True)
        if poll.cancelled():
            return None
        return poll.result()

    async def _retire_session(self) -> None:
        old = self._session_id
        self._session_id = None  # las entregas en curso de la sesión vieja se detienen
        cancelled = await self._cancel_all_work()
        self._log("session_retired", node_session_id=old, cancelled=cancelled)

    async def _shutdown(self, reply_worker: asyncio.Task[None]) -> None:
        reply_worker.cancel()
        await asyncio.gather(reply_worker, return_exceptions=True)
        await self._cancel_all_work()
        self._session_id = None

    async def _cancel_all_work(self) -> int:
        tasks = [job.task for job in self._jobs.values() if job.task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._jobs.clear()
        self._seen.clear()
        while not self._replies.empty():
            self._replies.get_nowait()
        return len(tasks)

    # -- esperas ------------------------------------------------------------

    async def _backoff(self) -> None:
        base = min(BACKOFF_MAX_SECONDS, BACKOFF_INITIAL_SECONDS * 2**self._failures)
        self._failures = min(self._failures + 1, 16)
        await self._sleep(base * (0.5 + 0.5 * self._jitter()))

    async def _pace(self, started: float) -> None:
        elapsed = asyncio.get_running_loop().time() - started
        if elapsed < self._min_empty_poll:
            await self._sleep(self._min_empty_poll - elapsed)

    # -- señales desde las entregas ---------------------------------------

    def _raise_if_fatal(self) -> None:
        if self._fatal is not None:
            raise _FatalError(self._fatal)

    def _signal_fatal(self, event: str) -> None:
        if self._fatal is None:
            self._fatal = event
        self._interrupt.set()

    def _request_renewal(self, session_id: UUID) -> None:
        if session_id == self._session_id and not self._renewal_requested:
            self._renewal_requested = True
            self._interrupt.set()

    # -- admisión y cancelación ---------------------------------------------

    def _remember(self, request_id: UUID) -> None:
        self._seen[request_id] = None
        if len(self._seen) > SEEN_REQUESTS_MAX:
            self._seen.popitem(last=False)

    def _admit(self, request: Request) -> None:
        rid = request.request_id
        if rid in self._seen:
            self._log("duplicate_request_ignored", level=logging.WARNING, request_id=rid)
            return
        self._remember(rid)
        if (request.expires_at - self._clock()).total_seconds() <= DELIVERY_MARGIN_SECONDS:
            self._log("request_expired_on_arrival", level=logging.WARNING, request_id=rid)
            self._reply_error(request, ErrorCode.TIMEOUT, "agent:expired_before_execution")
            return
        try:
            build_ask_path(request.params.domain, request.params.asset)
        except UnsafePathSegmentError:
            self._reply_error(request, ErrorCode.INVALID_REQUEST, "agent:invalid_path_segment")
            return
        if len(self._jobs) >= self._capacity:
            self._reply_error(request, ErrorCode.LOCAL_UNAVAILABLE, "agent:busy")
            return
        assert self._session_id is not None  # noqa: S101 - solo se admite con sesión
        job = _Job(request_id=rid, session_id=self._session_id)
        self._jobs[rid] = job
        job.task = asyncio.create_task(self._run_job(job, request))
        self._log("request_accepted", request_id=rid)

    def _reply_error(self, request: Request, code: ErrorCode, detail: str) -> None:
        """Rechazo inmediato: a la cola acotada del trabajador, sin crear tareas."""
        self._log("request_rejected", request_id=request.request_id, error_code=code.value)
        assert self._session_id is not None  # noqa: S101
        delivery = _Delivery(
            request_id=request.request_id,
            session_id=self._session_id,
            body=self._error_body(request.request_id, self._session_id, code, detail),
            expires_at=request.expires_at,
        )
        try:
            self._replies.put_nowait(delivery)
        except asyncio.QueueFull:
            self._log("reply_dropped", level=logging.WARNING, request_id=request.request_id)

    def _cancel(self, message: Cancel) -> None:
        job = self._jobs.get(message.request_id)
        if job is None or job.task is None or job.task.done():
            self._log("cancel_ignored", request_id=message.request_id)
            return
        job.task.cancel()
        self._log("request_cancelled", request_id=message.request_id)

    # -- ejecución y entrega ------------------------------------------------

    async def _run_job(self, job: _Job, request: Request) -> None:
        """Ejecuta y entrega. Nunca termina con una excepción sin recoger."""
        loop = asyncio.get_running_loop()
        expires_at = request.expires_at
        try:
            async with self._semaphore:
                started = loop.time()
                outcome = await self._execute(request)
            # El token del usuario ya no hace falta: se suelta antes de entregar.
            del request
            self._log(
                "local_call_finished",
                request_id=job.request_id,
                error_code=outcome.code.value if isinstance(outcome, LocalFailure) else None,
                duration_ms=int((loop.time() - started) * 1000),
            )
            body = self._encode_safely(job, outcome)
            del outcome
            await self._deliver(_Delivery(job.request_id, job.session_id, body, expires_at))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Solo el tipo: el texto de la excepción podría llevar el resultado.
            self._log(
                "job_failed",
                level=logging.ERROR,
                request_id=job.request_id,
                error=type(exc).__name__,
            )
        finally:
            if self._jobs.get(job.request_id) is job:
                del self._jobs[job.request_id]
            # Rompe el ciclo tarea → excepción → frame → job → tarea, que
            # retendría el Request hasta la próxima recolección cíclica.
            job.task = None

    async def _execute(self, request: Request) -> LocalOutcome:
        remaining = (request.expires_at - self._clock()).total_seconds() - DELIVERY_MARGIN_SECONDS
        if remaining <= 0:
            return LocalFailure(ErrorCode.TIMEOUT, "agent:expired_before_execution")
        deadline = asyncio.get_running_loop().time() + min(self._local_timeout, remaining)
        try:
            return await self._local.ask(request, deadline=deadline)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._log(
                "local_call_crashed",
                level=logging.ERROR,
                request_id=request.request_id,
                error=type(exc).__name__,
            )
            return LocalFailure(ErrorCode.LOCAL_ERROR, "agent:internal_error")

    def _error_body(
        self, request_id: UUID, session_id: UUID, code: ErrorCode, detail: str
    ) -> bytes:
        return encode_message(
            ErrorMessage(
                node_id=self._node_id,
                node_session_id=session_id,
                request_id=request_id,
                code=code,
                detail=detail,
            )
        )

    def _encode(self, job: _Job, outcome: LocalOutcome) -> bytes:
        """Serializa el resultado una sola vez, dentro de los límites del relay."""
        if isinstance(outcome, LocalFailure):
            failure = outcome
        else:
            try:
                message = Response(
                    node_id=self._node_id,
                    node_session_id=job.session_id,
                    request_id=job.request_id,
                    result=outcome.result,
                )
            except ValidationError:
                failure = LocalFailure(ErrorCode.LOCAL_ERROR, "local:invalid_response")
            else:
                body = encode_message(message)
                if len(body) <= MAX_RESPONSE_WIRE_BYTES:
                    return body
                failure = LocalFailure(ErrorCode.LOCAL_ERROR, "local:response_too_large")
        return self._error_body(job.request_id, job.session_id, failure.code, failure.detail)

    def _encode_safely(self, job: _Job, outcome: LocalOutcome) -> bytes:
        """:meth:`_encode` que degrada cualquier fallo a un ``ErrorMessage`` saneado."""
        try:
            return self._encode(job, outcome)
        except Exception as exc:
            # p. ej. un surrogate suelto que UTF-8 no admite. Solo el tipo.
            self._log(
                "result_encoding_failed",
                level=logging.ERROR,
                request_id=job.request_id,
                error=type(exc).__name__,
            )
            return self._error_body(
                job.request_id, job.session_id, ErrorCode.LOCAL_ERROR, "local:invalid_response"
            )

    async def _deliver(self, delivery: _Delivery) -> None:
        """Transmite el mismo cuerpo hasta 4 veces. **Nunca** reejecuta la solicitud.

        Ninguna transmisión, tampoco la primera, ocurre después de ``expires_at``.
        """
        rid = delivery.request_id
        for attempt in range(len(RESULT_RETRY_DELAYS) + 1):
            if attempt:
                delay = RESULT_RETRY_DELAYS[attempt - 1]
                if self._clock() + timedelta(seconds=delay) >= delivery.expires_at:
                    break
                await self._sleep(delay)
            if self._clock() >= delivery.expires_at:
                break
            if delivery.session_id != self._session_id:
                self._log("result_discarded_stale", request_id=rid)
                return
            outcome = await self._relay.send_result(delivery.body)
            if outcome is RelayOutcome.OK:
                self._log("result_delivered", request_id=rid, attempt=attempt + 1)
                return
            if outcome is RelayOutcome.NOT_PENDING:
                # Ya aceptado (ACK perdido), expirado o cancelado: es seguro parar.
                self._log("result_not_pending", request_id=rid, attempt=attempt + 1)
                return
            if outcome is RelayOutcome.STALE:
                self._log("result_discarded_stale", request_id=rid)
                self._request_renewal(delivery.session_id)
                return
            if outcome in (RelayOutcome.AUTH, RelayOutcome.NOT_FOUND):
                self._signal_fatal(_fatal_event(outcome))
                return
            if outcome is RelayOutcome.PROTOCOL:
                self._log("result_rejected", level=logging.WARNING, request_id=rid)
                return
            self._log("result_retry", level=logging.WARNING, request_id=rid, attempt=attempt + 1)
        self._log("result_undelivered", level=logging.WARNING, request_id=rid)

    async def _reply_worker(self) -> None:
        while True:
            delivery = await self._replies.get()
            try:
                await self._deliver(delivery)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._log(
                    "reply_failed",
                    level=logging.ERROR,
                    request_id=delivery.request_id,
                    error=type(exc).__name__,
                )

    # -- logs ----------------------------------------------------------------

    def _log(self, event: str, *, level: int = logging.INFO, **fields: object) -> None:
        extra: dict[str, object] = {"event": event, "node_id": self._node_id}
        if "node_session_id" not in fields and self._session_id is not None:
            extra["node_session_id"] = str(self._session_id)
        for key, value in fields.items():
            if value is not None:
                extra[key] = str(value) if isinstance(value, UUID) else value
        _logger.log(level, event, extra=extra)
