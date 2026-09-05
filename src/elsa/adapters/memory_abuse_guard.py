"""Control de abuso en memoria del proceso.

**Limitación conocida y deliberada:** el estado vive en el proceso. Con
varios trabajadores o varias réplicas, cada uno aplica sus propios contadores
y el límite efectivo se multiplica por el número de procesos. Es una defensa
contra el uso desmedido, no una garantía distribuida. La sustitución por un
almacén compartido (p. ej. Redis) es escribir otro adaptador de
:class:`elsa.ports.abuse.AbuseGuardPort`; nada más cambia.

Se documenta en ``docs/security.md`` en lugar de simular una protección que
todavía no existe.
"""

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Callable

from elsa.ports.abuse import AbusePolicy, LimitKind, LimitVerdict

_logger = logging.getLogger("elsa.abuse")

_WINDOW_SECONDS = 60.0


class InMemoryAbuseGuard:
    """Contadores por usuario dentro de un único proceso."""

    def __init__(
        self,
        policy: AbusePolicy,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._policy = policy
        self._clock = clock
        self._lock = asyncio.Lock()
        self._requests: dict[str, deque[float]] = {}
        self._concurrent: dict[str, int] = {}
        self._sessions: dict[str, dict[str, float]] = {}
        self._warned_about_sessions = False

    @property
    def policy(self) -> AbusePolicy:
        return self._policy

    async def acquire(self, *, user_id: str, session_id: str | None = None) -> LimitVerdict:
        async with self._lock:
            now = self._clock()

            sessions_verdict = self._check_sessions(user_id, session_id, now)
            if sessions_verdict is not None:
                return sessions_verdict

            window = self._requests.setdefault(user_id, deque())
            while window and (now - window[0]) >= _WINDOW_SECONDS:
                window.popleft()

            limit = self._policy.requests_per_minute
            if limit > 0 and len(window) >= limit:
                retry_after = max(1, math.ceil(_WINDOW_SECONDS - (now - window[0])))
                return LimitVerdict(
                    allowed=False,
                    kind=LimitKind.REQUESTS_PER_MINUTE,
                    retry_after_seconds=retry_after,
                )

            in_flight = self._concurrent.get(user_id, 0)
            if 0 < self._policy.max_concurrent_requests <= in_flight:
                return LimitVerdict(
                    allowed=False,
                    kind=LimitKind.CONCURRENT_REQUESTS,
                    retry_after_seconds=1,
                )

            window.append(now)
            self._concurrent[user_id] = in_flight + 1
            return LimitVerdict(allowed=True)

    async def release(self, *, user_id: str, session_id: str | None = None) -> None:
        async with self._lock:
            in_flight = self._concurrent.get(user_id, 0)
            if in_flight <= 1:
                self._concurrent.pop(user_id, None)
            else:
                self._concurrent[user_id] = in_flight - 1

    # -----------------------------------------------------------------
    # Interno
    # -----------------------------------------------------------------

    def _check_sessions(
        self,
        user_id: str,
        session_id: str | None,
        now: float,
    ) -> LimitVerdict | None:
        """Aplica el límite de sesiones simultáneas, si es aplicable."""
        maximum = self._policy.max_sessions_per_user
        if maximum <= 0:
            return None

        if session_id is None:
            # El token no declara sesión: no se inventa una. Se avisa una
            # vez y el límite queda sin aplicar, en lugar de fingirlo.
            if not self._warned_about_sessions:
                self._warned_about_sessions = True
                _logger.warning(
                    "session limit configured but tokens carry no session identifier; "
                    "the limit cannot be enforced"
                )
            return None

        active = self._sessions.setdefault(user_id, {})
        idle_timeout = self._policy.session_idle_timeout_seconds
        if idle_timeout > 0:
            for known, last_seen in list(active.items()):
                if (now - last_seen) >= idle_timeout:
                    del active[known]

        if session_id not in active and len(active) >= maximum:
            return LimitVerdict(allowed=False, kind=LimitKind.SESSIONS, retry_after_seconds=1)

        active[session_id] = now
        return None
