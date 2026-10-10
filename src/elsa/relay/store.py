"""Estado en memoria del relay Render–PC1 (ADR 0031).

Es **síncrono, sin I/O y sin reloj propio**: cada método recibe el instante.
Esa es la garantía de atomicidad del piloto: en un único bucle de eventos no
hay ``await`` dentro de ningún método, así que una mutación no se entrelaza con
otra. Las esperas (poll, ``submit``) viven en :mod:`elsa.relay.service`.

Reglas que este módulo hace cumplir:

- Una solicitud ``queued`` **no pertenece a ninguna sesión**: el ``Request``
  protocolario se materializa al despacharla. Un ``REGISTER`` nuevo conserva
  las vigentes y jamás reutiliza el ``node_session_id`` antiguo.
- **At-most-once**: tras ``dispatched`` una solicitud no vuelve a la cola.
- Toda salida (éxito, error, timeout, cancelación, reemplazo de sesión) pasa
  por :meth:`InMemoryRelayStore.finish`, que retira la solicitud, descarta el
  token del usuario y resuelve a quien espera **exactamente una vez**.
- El token del usuario se descarta **en cuanto se despacha**: ya no hace falta
  en Render.
- **Un ``node_session_id`` es de un solo uso.** Una sesión vencida por TTL o
  reemplazada queda retirada y su id se recuerda mientras viva el proceso:
  ni ``poll``, ni ``result`` ni ``register`` pueden revivirla. Solo un id
  nuevo crea una sesión válida. Un reinicio de Render pierde este historial,
  igual que el resto del estado.

Limitación aceptada del piloto: todo vive en la memoria del proceso. Un
reinicio pierde sesión y solicitudes en vuelo; solo se admite una instancia.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from pydantic import SecretStr

from elsa.relay.protocol import (
    AskParams,
    ErrorCode,
    RequestState,
    Response,
    can_transition,
)

__all__ = [
    "InMemoryRelayStore",
    "NodeSession",
    "PendingRequest",
    "RelayCapacityError",
    "RelayFailure",
    "StaleSessionError",
]


@dataclass(frozen=True)
class RelayFailure:
    """Fallo lógico de una solicitud, tal como lo ve quien hizo ``submit``.

    No es un ``ErrorMessage`` del cable: ese exige ``node_session_id`` y un
    fallo de Render (nodo offline, capacidad) puede no tener sesión alguna.
    ``detail`` es corto y fijo de nuestra parte, o el saneado del nodo.
    """

    code: ErrorCode
    detail: str | None = None


class RelayCapacityError(Exception):
    """Se alcanzó el máximo de solicitudes vivas."""


class StaleSessionError(Exception):
    """La sesión del mensaje no es la vigente: desconocida, vencida o ya usada."""


@dataclass
class NodeSession:
    node_id: str
    session_id: UUID
    last_seen: datetime


@dataclass(eq=False)
class PendingRequest:
    request_id: UUID
    params: AskParams
    user_access_token: SecretStr | None
    created_at: datetime
    expires_at: datetime
    waiter: asyncio.Future[Response | RelayFailure]
    dispatched_signal: asyncio.Future[None]
    state: RequestState = RequestState.QUEUED
    session_id: UUID | None = None
    """``None`` mientras está en cola; la sesión activa al despacharla."""
    dispatched_at: datetime | None = None


class InMemoryRelayStore:
    def __init__(self, *, max_pending: int) -> None:
        self._max_pending = max_pending
        self._pending: dict[UUID, PendingRequest] = {}
        self._queue: deque[UUID] = deque()
        self._cancels: deque[UUID] = deque()
        self._session: NodeSession | None = None
        self._used_sessions: set[UUID] = set()
        """Todo ``node_session_id`` visto en la vida del proceso (un solo uso)."""

    # -- consulta -------------------------------------------------------

    @property
    def session(self) -> NodeSession | None:
        return self._session

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def queue_length(self) -> int:
        return len(self._queue)

    @property
    def cancel_backlog(self) -> int:
        return len(self._cancels)

    def get(self, request_id: UUID) -> PendingRequest | None:
        return self._pending.get(request_id)

    def is_online(self, now: datetime, ttl: timedelta) -> bool:
        session = self._session
        return session is not None and now - session.last_seen < ttl

    def next_deadline(self, entry: PendingRequest, ttl: timedelta, now: datetime) -> datetime:
        """Primer instante en que ``entry`` debe fallar por tiempo.

        En vuelo cuenta también la vigencia del nodo. Es lo que permite
        despertar al que espera sin que llegue otra operación.
        """
        deadline = entry.expires_at
        if entry.state is RequestState.DISPATCHED:
            session = self._session
            if session is None or session.session_id != entry.session_id:
                return now
            deadline = min(deadline, session.last_seen + ttl)
        return deadline

    # -- sesión ---------------------------------------------------------

    def register(self, node_id: str, session_id: UUID, now: datetime) -> list[PendingRequest]:
        """Crea o reemplaza la sesión. Devuelve las solicitudes en vuelo fallidas.

        - El mismo ``session_id`` de la sesión **vigente** solo refresca (un
          reintento del REGISTER cuya respuesta se perdió).
        - Un ``session_id`` ya usado y no vigente (vencido o reemplazado) se
          rechaza con :class:`StaleSessionError`: el nodo debe generar uno nuevo.
        - Uno nuevo invalida el anterior: lo despachado a la sesión vieja
          **falla** (nunca se reejecuta) y sus cancels se descartan. Las
          ``queued`` se conservan.

        El llamador retira antes las sesiones vencidas
        (:meth:`retire_if_expired`).
        """
        current = self._session
        if current is not None and current.session_id == session_id:
            current.last_seen = now
            return []
        if session_id in self._used_sessions:
            raise StaleSessionError
        failed = self._fail_dispatched("the node session was replaced")
        self._cancels.clear()
        self._session = NodeSession(node_id=node_id, session_id=session_id, last_seen=now)
        self._used_sessions.add(session_id)
        return failed

    def retire_if_expired(self, now: datetime, ttl: timedelta) -> list[PendingRequest]:
        """Retira la sesión si ``last_seen`` superó el TTL. Devuelve lo fallado.

        La sesión retirada no vuelve: su id queda usado y las solicitudes
        despachadas a ella fallan. Las ``queued`` esperan una sesión nueva.
        """
        session = self._session
        if session is None or now - session.last_seen < ttl:
            return []
        failed = self._fail_dispatched("the node went offline")
        self._cancels.clear()
        self._session = None
        return failed

    def touch(self, session_id: UUID, now: datetime, ttl: timedelta) -> bool:
        """Refresca ``last_seen``. ``False`` si no es la sesión vigente **y viva**.

        Una sesión vencida no se refresca nunca: refrescarla la resucitaría.
        """
        session = self._session
        if session is None or session.session_id != session_id:
            return False
        if now - session.last_seen >= ttl:
            return False
        session.last_seen = now
        return True

    def _fail_dispatched(self, detail: str) -> list[PendingRequest]:
        failed: list[PendingRequest] = []
        for entry in list(self._pending.values()):
            if entry.state is RequestState.DISPATCHED:
                finished = self.finish(
                    entry.request_id,
                    RequestState.FAILED,
                    RelayFailure(ErrorCode.LOCAL_UNAVAILABLE, detail),
                )
                if finished is not None:
                    failed.append(finished)
        return failed

    # -- ciclo de vida de las solicitudes -------------------------------

    def add(self, entry: PendingRequest) -> None:
        if len(self._pending) >= self._max_pending:
            raise RelayCapacityError
        self._pending[entry.request_id] = entry
        self._queue.append(entry.request_id)

    def pop_queued(self, now: datetime) -> tuple[PendingRequest | None, list[PendingRequest]]:
        """Saca la siguiente solicitud vigente y la marca ``dispatched``.

        Devuelve también las que se encontraron vencidas (ya finalizadas). Se
        despacha solo a la sesión activa, y el token del usuario lo conserva
        el llamador solo el tiempo de construir el mensaje: se descarta en
        :meth:`scrub_token`.
        """
        session = self._session
        expired: list[PendingRequest] = []
        while self._queue:
            request_id = self._queue.popleft()
            entry = self._pending.get(request_id)
            if entry is None or entry.state is not RequestState.QUEUED:
                continue
            if now >= entry.expires_at:
                finished = self.finish(
                    request_id, RequestState.EXPIRED, RelayFailure(ErrorCode.TIMEOUT)
                )
                if finished is not None:
                    expired.append(finished)
                continue
            if session is None:
                self._queue.appendleft(request_id)
                return None, expired
            entry.state = RequestState.DISPATCHED
            entry.session_id = session.session_id
            entry.dispatched_at = now
            if not entry.dispatched_signal.done():
                entry.dispatched_signal.set_result(None)
            return entry, expired
        return None, expired

    def scrub_token(self, entry: PendingRequest) -> None:
        """Render deja de conservar el token del usuario una vez despachado."""
        entry.user_access_token = None

    def enqueue_cancel(self, request_id: UUID) -> None:
        self._cancels.append(request_id)

    def pop_cancel(self) -> UUID | None:
        return self._cancels.popleft() if self._cancels else None

    def finish(
        self,
        request_id: UUID,
        state: RequestState,
        outcome: Response | RelayFailure,
    ) -> PendingRequest | None:
        """Cierra una solicitud. Única vía de salida; ``None`` si ya no vive."""
        entry = self._pending.get(request_id)
        if entry is None or not can_transition(entry.state, state):
            return None
        del self._pending[request_id]
        if request_id in self._queue:
            self._queue.remove(request_id)
        entry.state = state
        entry.user_access_token = None
        if not entry.waiter.done():
            entry.waiter.set_result(outcome)
        return entry

    def expire_entry(
        self, entry: PendingRequest, now: datetime, ttl: timedelta
    ) -> PendingRequest | None:
        """Falla ``entry`` si ya venció su plazo o cayó el nodo que lo tenía."""
        if entry.request_id not in self._pending:
            return None
        if now >= entry.expires_at:
            return self.finish(
                entry.request_id, RequestState.EXPIRED, RelayFailure(ErrorCode.TIMEOUT)
            )
        if entry.state is RequestState.DISPATCHED:
            session = self._session
            alive = (
                session is not None
                and session.session_id == entry.session_id
                and now - session.last_seen < ttl
            )
            if not alive:
                return self.finish(
                    entry.request_id,
                    RequestState.FAILED,
                    RelayFailure(ErrorCode.LOCAL_UNAVAILABLE, "the node went offline"),
                )
        return None

    def expire_due(self, now: datetime, ttl: timedelta) -> list[PendingRequest]:
        finished = [self.expire_entry(entry, now, ttl) for entry in list(self._pending.values())]
        return [entry for entry in finished if entry is not None]
