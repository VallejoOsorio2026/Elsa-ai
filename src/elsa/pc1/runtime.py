"""Directorio de runtime del Modo ELSA: bloqueo, estado y petición de parada.

Todo vive en ``%LOCALAPPDATA%\\ELSA\\mode\\``, fuera del repositorio:

- ``supervisor.lock``: bloqueo del sistema operativo retenido durante toda la
  vida del supervisor. Si el proceso muere, el sistema lo libera, así que el
  bloqueo nunca queda «stale».
- ``state.json``: fase, PIDs **informativos**, puerto, readiness y latido. Un
  esquema cerrado: solo se escriben y se leen los campos de :class:`RuntimeState`.
  Ningún comando detiene un proceso por un PID leído de aquí.
- ``stop.request``: la petición de parada que crea ``stop`` y atiende el
  supervisor.
- ``logs\\``: log actual y anterior de cada componente.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import IO, Any

__all__ = [
    "LOG_NAMES",
    "STATE_SCHEMA_VERSION",
    "InstanceLock",
    "Phase",
    "RuntimeDirectoryError",
    "RuntimePaths",
    "RuntimeState",
    "clean_stale",
    "default_runtime_dir",
    "read_state",
    "rotate_logs",
    "write_state",
]

STATE_SCHEMA_VERSION = 1
LOG_NAMES = ("supervisor", "elsa-local", "agent")
_DEPENDENCY_NAME = re.compile(r"[a-z0-9_.-]{1,40}")
_MAX_STATE_BYTES = 16 * 1024


class RuntimeDirectoryError(Exception):
    """No hay un directorio de runtime utilizable. El mensaje no incluye rutas."""


class Phase(StrEnum):
    """Fase que escribe el supervisor. ``DETENIDO`` no se escribe: es no tener supervisor."""

    STARTING = "starting"
    RUNNING = "running"
    DEGRADED = "degraded"
    STOPPING = "stopping"


def default_runtime_dir(environ: dict[str, str] | None = None) -> Path:
    """``%LOCALAPPDATA%\\ELSA\\mode``. Sin ``LOCALAPPDATA`` absoluto, falla cerrado."""
    env = os.environ if environ is None else environ
    base = env.get("LOCALAPPDATA", "")
    if not base or not Path(base).is_absolute():
        raise RuntimeDirectoryError("LOCALAPPDATA is not set to an absolute path.")
    return Path(base) / "ELSA" / "mode"


@dataclass(frozen=True)
class RuntimePaths:
    root: Path

    @property
    def lock(self) -> Path:
        return self.root / "supervisor.lock"

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def stop_request(self) -> Path:
        return self.root / "stop.request"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def log(self, name: str) -> Path:
        return self.logs / f"{name}.log"

    def ensure(self) -> None:
        self.logs.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Bloqueo de instancia única
# ---------------------------------------------------------------------------


class InstanceLock:
    """Bloqueo exclusivo y no bloqueante sobre el primer byte de un archivo.

    Cada instancia abre su propio handle: dos instancias, del mismo proceso o de
    procesos distintos, se excluyen entre sí. El handle queda abierto mientras
    el bloqueo está tomado.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: IO[bytes] | None = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        handle = open(self._path, "a+b")  # noqa: SIM115 - debe quedar abierto
        try:
            # `msvcrt.locking` bloquea un rango desde la posición actual: el
            # archivo debe tener al menos ese byte para bloquear un rango real.
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if not _try_lock(handle):
                handle.close()
                return False
        except BaseException:
            handle.close()
            raise
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            _unlock(handle)
        finally:
            handle.close()

    def __enter__(self) -> InstanceLock:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


if sys.platform == "win32":
    import msvcrt

    def _try_lock(handle: IO[bytes]) -> bool:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(handle: IO[bytes]) -> None:
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(handle: IO[bytes]) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeState:
    """Lo único que se escribe en ``state.json``. Sin secretos por construcción."""

    phase: Phase
    supervisor_pid: int
    started_at: str
    heartbeat_at: str
    elsa_port: int
    elsa_pid: int | None = None
    elsa_alive: bool = False
    elsa_readiness: str | None = None
    degraded_dependencies: tuple[str, ...] = field(default_factory=tuple)
    agent_pid: int | None = None
    agent_alive: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "phase": self.phase.value,
            "supervisor_pid": self.supervisor_pid,
            "started_at": self.started_at,
            "heartbeat_at": self.heartbeat_at,
            "elsa_port": self.elsa_port,
            "elsa_pid": self.elsa_pid,
            "elsa_alive": self.elsa_alive,
            "elsa_readiness": self.elsa_readiness,
            "degraded_dependencies": list(self.degraded_dependencies),
            "agent_pid": self.agent_pid,
            "agent_alive": self.agent_alive,
        }


def write_state(path: Path, state: RuntimeState) -> None:
    """Escritura atómica: archivo temporal en el mismo directorio y ``os.replace``."""
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(json.dumps(state.to_json(), indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("not an integer")
    return value


def read_state(path: Path) -> RuntimeState | None:
    """Lee el estado. Ausente, ilegible o fuera de esquema → ``None``.

    Cualquier campo que no esté en el esquema se ignora: nada de lo que no
    escribió el supervisor llega a la salida.
    """
    try:
        if path.stat().st_size > _MAX_STATE_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != STATE_SCHEMA_VERSION:
            return None
        names = data.get("degraded_dependencies", [])
        if not isinstance(names, list):
            return None
        supervisor_pid = _optional_int(data["supervisor_pid"])
        elsa_port = _optional_int(data["elsa_port"])
        if supervisor_pid is None or elsa_port is None:
            return None
        readiness = data.get("elsa_readiness")
        if readiness is not None and not isinstance(readiness, str):
            return None
        started_at, heartbeat_at = data["started_at"], data["heartbeat_at"]
        if not isinstance(started_at, str) or not isinstance(heartbeat_at, str):
            return None
        return RuntimeState(
            phase=Phase(data["phase"]),
            supervisor_pid=supervisor_pid,
            started_at=started_at,
            heartbeat_at=heartbeat_at,
            elsa_port=elsa_port,
            elsa_pid=_optional_int(data.get("elsa_pid")),
            elsa_alive=data.get("elsa_alive") is True,
            elsa_readiness=readiness,
            degraded_dependencies=tuple(
                name for name in names if isinstance(name, str) and _DEPENDENCY_NAME.fullmatch(name)
            ),
            agent_pid=_optional_int(data.get("agent_pid")),
            agent_alive=data.get("agent_alive") is True,
        )
    except (OSError, ValueError, KeyError, TypeError, UnicodeDecodeError):
        return None


def clean_stale(paths: RuntimePaths) -> bool:
    """Borra ``state.json`` y ``stop.request`` residuales. **Solo con el bloqueo tomado.**

    No toca ningún proceso: los PIDs del estado residual no se usan para nada.
    Devuelve si había algo que limpiar.
    """
    found = False
    for path in (paths.state, paths.state.with_name(f"{paths.state.name}.tmp"), paths.stop_request):
        if path.exists():
            path.unlink()
            found = True
    return found


def rotate_logs(paths: RuntimePaths) -> None:
    """Conserva solo el log actual y el anterior de cada componente."""
    paths.ensure()
    for name in LOG_NAMES:
        current = paths.log(name)
        if current.exists():
            os.replace(current, paths.logs / f"{name}.prev.log")
