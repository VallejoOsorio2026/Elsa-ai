"""Supervisor del Modo ELSA (ADR 0034 §4–§9).

Arranca ELSA local, espera a que esté lista, arranca el agente y vigila a los
dos hasta que se pide la parada o uno de ellos termina. El orden es fijo:

```text
START: ELSA local → readiness → agente → gracia → EN MARCHA
STOP:  agente → ELSA local
```

- El agente **nunca** se arranca si ELSA no está lista; un arranque fallido
  detiene lo que ese intento inició.
- Si un hijo termina en ejecución, se detiene el otro y el supervisor termina.
  No hay reinicio automático.
- Solo se detienen los procesos lanzados aquí, por su handle.
- Readiness es un hecho local. Nada de lo que dice el supervisor afirma
  conexión con Render.

Los mensajes al operador son fijos y en español. Los logs de los hijos nunca se
muestran; ante un fallo se indica la ruta del log.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
import signal
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from elsa.agent.config import NODE_TOKEN_ENV
from elsa.pc1.preflight import LOOPBACK_BIND, Pc1Profile
from elsa.pc1.processes import (
    ChildSpec,
    OwnedProcess,
    ProcessJob,
    StopOutcome,
    create_job_object,
    launch,
)
from elsa.pc1.runtime import Phase, RuntimePaths, RuntimeState, clean_stale, write_state

__all__ = [
    "AGENT_NAME",
    "ELSA_NAME",
    "EXIT_ALREADY_RUNNING",
    "EXIT_CONFIG",
    "EXIT_FAILED",
    "EXIT_OK",
    "NOT_READY",
    "READY_PATH",
    "RELAY_NOT_VERIFIED",
    "Readiness",
    "ReadinessLevel",
    "Supervisor",
    "Timings",
    "agent_command",
    "agent_environment",
    "describe_readiness",
    "elsa_command",
    "elsa_environment",
    "probe_readiness",
]

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CONFIG = 2
EXIT_ALREADY_RUNNING = 3

ELSA_NAME = "elsa-local"
AGENT_NAME = "agent"
READY_PATH = "/api/v1/health/ready"
RELAY_NOT_VERIFIED = "Relay Render: conectividad NO VERIFICADA"

_MAX_READY_BYTES = 64 * 1024
_DEPENDENCY_NAME = re.compile(r"[a-z0-9_.-]{1,40}")
_PINNED_ELSA_ENV = {
    # Lo validado es lo que se ejecuta, aunque el archivo cambie entre medias.
    "ELSA_ASSISTANT_EXECUTION_MODE": "local",
    "ELSA_RELAY_ENABLED": "false",
    "ELSA_DEBUG": "false",
}

_logger = logging.getLogger("elsa.pc1")


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


class ReadinessLevel(StrEnum):
    READY = "ready"
    READY_DEGRADED = "ready_degraded"
    NOT_READY = "not_ready"


@dataclass(frozen=True)
class Readiness:
    level: ReadinessLevel
    degraded: tuple[str, ...] = ()
    """Nombres de dependencias que no están ``ok``. Nunca su ``detail``."""
    critical_down: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.level is not ReadinessLevel.NOT_READY


NOT_READY = Readiness(ReadinessLevel.NOT_READY)


def _names(
    dependencies: Mapping[str, object], keep: Callable[[Mapping[str, object]], bool]
) -> tuple[str, ...]:
    return tuple(
        name
        for name, report in dependencies.items()
        if isinstance(report, dict) and _DEPENDENCY_NAME.fullmatch(name) and keep(report)
    )


def probe_readiness(port: int, expected_environment: str | None, timeout: float = 3.0) -> Readiness:
    """Consulta ``/health/ready`` de ELSA local por loopback, sin proxies.

    - 200 + ``ok`` → LISTA; 200 + ``degraded`` → LISTA CON DEGRADACIONES NO
      CRÍTICAS; cualquier otra cosa (503, sin conexión, cuerpo inesperado,
      ambiente distinto) → NO LISTA.
    - ``expected_environment=None`` omite la comprobación del ambiente
      (``status``, que no carga la configuración).
    """
    connection = http.client.HTTPConnection(LOOPBACK_BIND, port, timeout=timeout)
    try:
        connection.request("GET", READY_PATH, headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(_MAX_READY_BYTES + 1)
        status = response.status
    except (OSError, http.client.HTTPException):
        return NOT_READY
    finally:
        connection.close()
    if len(body) > _MAX_READY_BYTES:
        return NOT_READY
    try:
        data = json.loads(body)
    except ValueError:
        return NOT_READY
    if not isinstance(data, dict):
        return NOT_READY
    dependencies = data.get("dependencies")
    if not isinstance(dependencies, dict):
        dependencies = {}
    critical_down = _names(
        dependencies, lambda r: r.get("critical") is True and r.get("status") == "down"
    )
    environment_ok = expected_environment is None or data.get("environment") == expected_environment
    if status == 200 and environment_ok:
        if data.get("status") == "ok":
            return Readiness(ReadinessLevel.READY)
        if data.get("status") == "degraded":
            degraded = _names(dependencies, lambda r: r.get("status") != "ok")
            return Readiness(ReadinessLevel.READY_DEGRADED, degraded=degraded)
    return Readiness(ReadinessLevel.NOT_READY, critical_down=critical_down)


def describe_readiness(readiness: Readiness) -> str:
    if readiness.level is ReadinessLevel.READY:
        return "LISTA"
    if readiness.level is ReadinessLevel.READY_DEGRADED:
        detail = f" ({', '.join(readiness.degraded)})" if readiness.degraded else ""
        return f"LISTA CON DEGRADACIONES NO CRÍTICAS{detail}"
    if readiness.critical_down:
        return f"NO LISTA (dependencias críticas caídas: {', '.join(readiness.critical_down)})"
    return "NO LISTA"


# ---------------------------------------------------------------------------
# Comandos y entornos de los hijos
# ---------------------------------------------------------------------------


def elsa_command(port: int) -> tuple[str, ...]:
    """uvicorn con el bind fijo en loopback. Sin access log (lleva la query)."""
    return (
        sys.executable,
        "-m",
        "uvicorn",
        "elsa.main:create_app",
        "--factory",
        "--host",
        LOOPBACK_BIND,
        "--port",
        str(port),
        "--no-access-log",
        "--no-proxy-headers",
        "--timeout-graceful-shutdown",
        "10",
    )


def agent_command(env_file: Path) -> tuple[str, ...]:
    """El agente de D2.3. El token **no** va aquí: va en su entorno."""
    return (sys.executable, "-m", "elsa.agent", "--env-file", str(env_file))


def elsa_environment(base: Mapping[str, str]) -> dict[str, str]:
    """Copia del entorno **sin** el token del nodo, con el perfil PC1 fijado."""
    env = dict(base)
    env.pop(NODE_TOKEN_ENV, None)
    env.update(_PINNED_ELSA_ENV)
    return env


def agent_environment(base: Mapping[str, str], node_token: str) -> dict[str, str]:
    env = dict(base)
    env[NODE_TOKEN_ENV] = node_token
    return env


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


class ChildProcess(Protocol):
    name: str

    @property
    def pid(self) -> int: ...

    def returncode(self) -> int | None: ...

    def stop(self, graceful_timeout: float) -> StopOutcome: ...


Launcher = Callable[[ChildSpec, ProcessJob | None], ChildProcess]
Probe = Callable[[], Readiness]
Reporter = Callable[[str], None]


@dataclass(frozen=True)
class Timings:
    ready_timeout: float = 120.0
    ready_poll: float = 1.0
    agent_grace: float = 5.0
    watch_interval: float = 1.0
    health_interval: float = 5.0
    agent_stop: float = 10.0
    elsa_stop: float = 20.0


@dataclass(frozen=True)
class ChildCommands:
    elsa: tuple[str, ...]
    agent: tuple[str, ...]


def _launch_owned(spec: ChildSpec, job: ProcessJob | None) -> ChildProcess:
    child: OwnedProcess = launch(spec, job)
    return child


@contextmanager
def _ignoring_interrupts() -> Iterator[None]:
    """Un segundo Ctrl+C no interrumpe la parada ordenada a medias."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Supervisor:
    """Una ejecución del Modo ELSA. Requiere el bloqueo de instancia ya tomado."""

    def __init__(
        self,
        *,
        profile: Pc1Profile,
        paths: RuntimePaths,
        cwd: Path,
        reporter: Reporter,
        environ: Mapping[str, str] | None = None,
        commands: ChildCommands | None = None,
        launcher: Launcher = _launch_owned,
        probe: Probe | None = None,
        job_factory: Callable[[], ProcessJob | None] = create_job_object,
        timings: Timings | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self._profile = profile
        self._paths = paths
        self._cwd = cwd
        self._report = reporter
        self._environ = os.environ if environ is None else environ
        env_file = profile.env_file if profile.env_file is not None else cwd / ".env"
        self._commands = commands or ChildCommands(
            elsa=elsa_command(profile.port), agent=agent_command(env_file)
        )
        self._launcher = launcher
        environment = profile.settings.env.value
        self._probe = probe or (lambda: probe_readiness(profile.port, environment))
        self._job_factory = job_factory
        self._timings = timings or Timings()
        self._clock = clock
        self._sleep = sleep
        self._now = now
        self._job: ProcessJob | None = None
        self._elsa: ChildProcess | None = None
        self._agent: ChildProcess | None = None
        self._phase = Phase.STARTING
        self._readiness: Readiness = NOT_READY
        self._started_at = now()

    # -- ciclo de vida ------------------------------------------------------

    def run(self) -> int:
        _logger.info("supervisor_started", extra={"port": self._profile.port})
        code = EXIT_FAILED
        try:
            code = self._start_and_watch()
        except KeyboardInterrupt:
            _logger.info("stop_requested", extra={"source": "ctrl_c"})
            self._report("Parada solicitada con Ctrl+C.")
            code = EXIT_OK
        finally:
            self._shutdown()
            _logger.info("supervisor_stopped", extra={"exit_code": code})
        return code

    def _start_and_watch(self) -> int:
        try:
            self._job = self._job_factory()
        except OSError:
            self._report("No se pudo preparar el control de procesos de Windows (Job Object).")
            return EXIT_FAILED
        self._write_state()
        self._report(f"Iniciando ELSA local en {LOOPBACK_BIND}:{self._profile.port}...")
        self._elsa = self._start_child(ELSA_NAME, self._commands.elsa, self._elsa_env())
        if self._elsa is None:
            return EXIT_FAILED
        readiness = self._wait_for_elsa(self._elsa)
        if readiness is None:
            return EXIT_OK  # parada pedida durante el arranque
        if not readiness.ready:
            return EXIT_FAILED
        self._report(f"ELSA LOCAL: {describe_readiness(readiness)}")

        self._report("Iniciando el agente de PC1...")
        self._agent = self._start_child(AGENT_NAME, self._commands.agent, self._agent_env())
        if self._agent is None:
            return EXIT_FAILED
        survived = self._agent_survives_grace(self._elsa, self._agent)
        if survived is None:
            return EXIT_OK
        if not survived:
            return EXIT_FAILED

        self._phase = Phase.RUNNING
        self._write_state()
        self._report_running()
        return self._watch(self._elsa, self._agent)

    def _start_child(
        self, name: str, argv: tuple[str, ...], env: dict[str, str]
    ) -> ChildProcess | None:
        spec = ChildSpec(
            name=name, argv=argv, env=env, cwd=self._cwd, log_path=self._paths.log(name)
        )
        try:
            child = self._launcher(spec, self._job)
        except OSError:
            _logger.error("child_start_failed", extra={"child": name})
            self._report(f"No se pudo iniciar {self._label(name)}. Log: {spec.log_path}")
            return None
        _logger.info("child_started", extra={"child": name, "pid": child.pid})
        self._write_state()
        return child

    def _wait_for_elsa(self, elsa: ChildProcess) -> Readiness | None:
        started = self._clock()
        deadline = started + self._timings.ready_timeout
        while True:
            if self._stop_requested():
                return None
            code = elsa.returncode()
            if code is not None:
                self._child_exited(ELSA_NAME, code, starting=True)
                return NOT_READY
            readiness = self._probe()
            if readiness.ready and elsa.returncode() is None:
                self._readiness = readiness
                _logger.info(
                    "elsa_ready",
                    extra={
                        "readiness": readiness.level.value,
                        "seconds": round(self._clock() - started, 1),
                    },
                )
                self._write_state()
                return readiness
            if self._clock() >= deadline:
                self._readiness = readiness
                _logger.error(
                    "elsa_not_ready", extra={"critical_down": list(readiness.critical_down)}
                )
                self._report(
                    f"ELSA LOCAL: {describe_readiness(readiness)}. No quedó lista en "
                    f"{self._timings.ready_timeout:.0f} s; el agente no se inicia. "
                    f"Log: {self._paths.log(ELSA_NAME)}"
                )
                return readiness
            self._sleep(self._timings.ready_poll)

    def _agent_survives_grace(self, elsa: ChildProcess, agent: ChildProcess) -> bool | None:
        deadline = self._clock() + self._timings.agent_grace
        while self._clock() < deadline:
            if self._stop_requested():
                return None
            for name, child in ((AGENT_NAME, agent), (ELSA_NAME, elsa)):
                code = child.returncode()
                if code is not None:
                    self._child_exited(name, code, starting=True)
                    return False
            self._sleep(self._timings.watch_interval)
        return True

    def _watch(self, elsa: ChildProcess, agent: ChildProcess) -> int:
        next_health = self._clock() + self._timings.health_interval
        while True:
            if self._stop_requested():
                return EXIT_OK
            for name, child in ((AGENT_NAME, agent), (ELSA_NAME, elsa)):
                code = child.returncode()
                if code is not None:
                    self._phase = Phase.DEGRADED
                    self._write_state()
                    self._child_exited(name, code, starting=False)
                    return EXIT_FAILED
            if self._clock() >= next_health:
                self._check_health()
                next_health = self._clock() + self._timings.health_interval
            self._sleep(self._timings.watch_interval)

    def _check_health(self) -> None:
        readiness = self._probe()
        phase = Phase.RUNNING if readiness.ready else Phase.DEGRADED
        if phase is not self._phase:
            _logger.warning("phase_changed", extra={"phase": phase.value})
            if phase is Phase.DEGRADED:
                self._report(f"Modo ELSA: DEGRADADO. ELSA LOCAL: {describe_readiness(readiness)}")
            else:
                self._report(f"Modo ELSA: EN MARCHA. ELSA LOCAL: {describe_readiness(readiness)}")
        self._phase = phase
        self._readiness = readiness
        self._write_state()

    def _shutdown(self) -> None:
        with _ignoring_interrupts():
            children = [c for c in (self._agent, self._elsa) if c is not None]
            if children:
                self._phase = Phase.STOPPING
                self._write_state()
                self._report("Deteniendo Modo ELSA...")
            for child, timeout in (
                (self._agent, self._timings.agent_stop),
                (self._elsa, self._timings.elsa_stop),
            ):
                if child is None:
                    continue
                outcome = child.stop(timeout)
                _logger.info("child_stopped", extra={"child": child.name, "outcome": outcome.value})
                if outcome is StopOutcome.FORCED:
                    self._report(
                        f"{self._label(child.name)} no respondió a la parada ordenada en "
                        f"{timeout:.0f} s; se forzó su cierre."
                    )
            if self._job is not None:
                self._job.close()
                self._job = None
            clean_stale(self._paths)
            self._agent = self._elsa = None
            self._report("Modo ELSA detenido.")

    # -- apoyo --------------------------------------------------------------

    def _stop_requested(self) -> bool:
        if self._paths.stop_request.exists():
            _logger.info("stop_requested", extra={"source": "stop_command"})
            self._report("Parada solicitada desde «Detener Modo ELSA».")
            return True
        return False

    def _child_exited(self, name: str, code: int, *, starting: bool) -> None:
        _logger.error(
            "child_exited", extra={"child": name, "exit_code": code, "starting": starting}
        )
        when = "durante el arranque" if starting else "inesperadamente"
        self._report(
            f"{self._label(name)} terminó {when} (código {code}). Modo ELSA se detiene. "
            f"Log: {self._paths.log(name)}"
        )

    @staticmethod
    def _label(name: str) -> str:
        return "ELSA local" if name == ELSA_NAME else "El agente de PC1"

    def _elsa_env(self) -> dict[str, str]:
        return elsa_environment(self._environ)

    def _agent_env(self) -> dict[str, str]:
        return agent_environment(self._environ, self._profile.agent.node_token.get_secret_value())

    def _report_running(self) -> None:
        agent_pid = self._agent.pid if self._agent is not None else None
        elsa_pid = self._elsa.pid if self._elsa is not None else None
        self._report(
            "\n".join(
                [
                    "",
                    "Modo ELSA: EN MARCHA",
                    f"  ELSA local  : proceso activo (PID {elsa_pid}) · "
                    f"{LOOPBACK_BIND}:{self._profile.port} · {describe_readiness(self._readiness)}",
                    f"  Agente PC1  : proceso activo (PID {agent_pid})",
                    f"  {RELAY_NOT_VERIFIED}",
                    "",
                    "Deje esta ventana abierta. Para detener: Ctrl+C aquí o Stop-ElsaMode.ps1.",
                    f"Logs: {self._paths.logs}",
                ]
            )
        )

    def _write_state(self) -> None:
        elsa, agent = self._elsa, self._agent
        write_state(
            self._paths.state,
            RuntimeState(
                phase=self._phase,
                supervisor_pid=os.getpid(),
                started_at=self._started_at,
                heartbeat_at=self._now(),
                elsa_port=self._profile.port,
                elsa_pid=elsa.pid if elsa is not None else None,
                elsa_alive=elsa is not None and elsa.returncode() is None,
                elsa_readiness=self._readiness.level.value if elsa is not None else None,
                degraded_dependencies=self._readiness.degraded,
                agent_pid=agent.pid if agent is not None else None,
                agent_alive=agent is not None and agent.returncode() is None,
            ),
        )
