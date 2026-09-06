"""Puerto de control de abuso.

Primera protección configurable de ELSA. **No** cubre el bloqueo de cuenta
por contraseñas fallidas: eso es responsabilidad del Supabase de Materiales.

Lo que sí cubre, todo por usuario ya autenticado:

- máximo de solicitudes por minuto,
- máximo de solicitudes simultáneas,
- máximo de sesiones ELSA simultáneas (solo si el token trae un
  identificador de sesión fiable),
- tiempo de inactividad tras el cual una sesión deja de contar.

Nunca se almacena el JWT: la clave de control es el UUID del usuario y, como
mucho, el identificador de sesión que el propio token declara.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class AbusePolicy:
    """Parámetros configurables del control de abuso. ``0`` = sin límite."""

    requests_per_minute: int = 60
    max_concurrent_requests: int = 5
    max_sessions_per_user: int = 0
    session_idle_timeout_seconds: int = 1800


class LimitKind(StrEnum):
    """Límite que se alcanzó."""

    REQUESTS_PER_MINUTE = "requests_per_minute"
    CONCURRENT_REQUESTS = "concurrent_requests"
    SESSIONS = "sessions"


@dataclass(frozen=True, slots=True)
class LimitVerdict:
    """Resultado de pedir permiso para atender una solicitud."""

    allowed: bool
    kind: LimitKind | None = None
    retry_after_seconds: int | None = None


@runtime_checkable
class AbuseGuardPort(Protocol):
    """Admisión de solicitudes por usuario."""

    async def acquire(self, *, user_id: str, session_id: str | None = None) -> LimitVerdict:
        """Reserva una ranura para atender una solicitud del usuario."""
        ...

    async def release(self, *, user_id: str, session_id: str | None = None) -> None:
        """Libera la ranura reservada por :meth:`acquire`."""
        ...
