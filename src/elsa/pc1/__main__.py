"""Operación del Modo ELSA en PC1 (ADR 0034)::

    python -m elsa.pc1 start    # en primer plano; Ctrl+C detiene en orden
    python -m elsa.pc1 status   # solo lectura
    python -m elsa.pc1 stop     # pide la parada al supervisor y espera

Se ejecuta desde la raíz del repositorio: ELSA y el agente leen el ``.env`` de
ese directorio, el mismo que valida el preflight.

Códigos de salida: ``0`` correcto; ``1`` el arranque o la parada fallaron (o el
nodo se detuvo por un fallo); ``2`` configuración o entorno inválidos; ``3`` ya
hay un Modo ELSA en marcha.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from elsa.logging import JsonFormatter
from elsa.pc1.preflight import (
    LOOPBACK_BIND,
    PreflightError,
    ReadSecret,
    check_port_free,
    check_profile,
)
from elsa.pc1.runtime import (
    InstanceLock,
    Phase,
    RuntimeDirectoryError,
    RuntimePaths,
    RuntimeState,
    clean_stale,
    default_runtime_dir,
    read_state,
    rotate_logs,
)
from elsa.pc1.supervisor import (
    EXIT_ALREADY_RUNNING,
    EXIT_CONFIG,
    EXIT_FAILED,
    EXIT_OK,
    NOT_READY,
    RELAY_NOT_VERIFIED,
    Readiness,
    Supervisor,
    describe_readiness,
    probe_readiness,
)

Output = Callable[[str], None]


class _Runnable(Protocol):
    def run(self) -> int: ...


HEARTBEAT_STALE_SECONDS = 20.0
STOP_TIMEOUT_SECONDS = 60.0
_PHASE_LABEL = {
    Phase.STARTING: "ARRANCANDO",
    Phase.RUNNING: "EN MARCHA",
    Phase.DEGRADED: "DEGRADADO",
    Phase.STOPPING: "DETENIÉNDOSE",
}


def _print(message: str) -> None:
    print(message, flush=True)


def _secret_prompt() -> ReadSecret | None:
    """Prompt oculto solo si hay una consola interactiva."""
    if sys.stdin is None or not sys.stdin.isatty():
        return None
    return lambda: getpass.getpass("Token del nodo (no se muestra al escribir): ")


def _attach_supervisor_log(path: Path) -> logging.Handler:
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("elsa.pc1")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return handler


def _detach_supervisor_log(handler: logging.Handler) -> None:
    logging.getLogger("elsa.pc1").removeHandler(handler)
    handler.close()


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def start(
    paths: RuntimePaths,
    cwd: Path,
    out: Output = _print,
    read_secret: ReadSecret | None = None,
    supervisor_factory: Callable[..., _Runnable] = Supervisor,
) -> int:
    paths.ensure()
    lock = InstanceLock(paths.lock)
    if not lock.acquire():
        out(
            "Modo ELSA ya está en marcha en este equipo. Consulte su estado con "
            "Get-ElsaModeStatus.ps1 o deténgalo con Stop-ElsaMode.ps1."
        )
        return EXIT_ALREADY_RUNNING
    handler: logging.Handler | None = None
    try:
        # Con el bloqueo tomado no hay otro supervisor: lo que quede es residual.
        # Un stop.request viejo nunca es una orden para esta instancia.
        if clean_stale(paths):
            out(
                "El último cierre de Modo ELSA no fue limpio. Se limpió su estado; "
                "no se detuvo ningún proceso."
            )
        rotate_logs(paths)
        handler = _attach_supervisor_log(paths.log("supervisor"))
        out("Comprobando la configuración...")
        try:
            profile = check_profile(cwd / ".env", read_secret)
        except PreflightError as exc:
            out(f"No se puede iniciar Modo ELSA. {exc}")
            return EXIT_CONFIG
        try:
            check_port_free(profile.port)
        except PreflightError as exc:
            out(f"No se puede iniciar Modo ELSA. {exc}")
            return EXIT_FAILED
        supervisor = supervisor_factory(profile=profile, paths=paths, cwd=cwd, reporter=out)
        return supervisor.run()
    except KeyboardInterrupt:
        out("Inicio cancelado. No se inició ningún proceso.")
        return EXIT_FAILED
    finally:
        if handler is not None:
            _detach_supervisor_log(handler)
        lock.release()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def _age_seconds(timestamp: str) -> float | None:
    try:
        moment = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return (datetime.now(UTC) - moment).total_seconds()


def _local_time(timestamp: str) -> str:
    try:
        return datetime.fromisoformat(timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return "desconocido"


def _process_line(alive: bool, pid: int | None) -> str:
    if pid is None:
        return "no iniciado"
    return f"proceso activo (PID {pid})" if alive else f"proceso terminado (PID {pid})"


def _supervisor_alive(paths: RuntimePaths) -> bool:
    lock = InstanceLock(paths.lock)
    if lock.acquire():
        lock.release()
        return False
    return True


def render_status(state: RuntimeState | None, readiness: Readiness, paths: RuntimePaths) -> str:
    """Estado de un supervisor vivo. Nunca afirma conexión con Render."""
    if state is None:
        return "\n".join(["Modo ELSA: ARRANCANDO", f"  {RELAY_NOT_VERIFIED}"])
    label = _PHASE_LABEL[state.phase]
    reason = ""
    age = _age_seconds(state.heartbeat_at)
    if age is None or age > HEARTBEAT_STALE_SECONDS:
        label, reason = "DEGRADADO", " (el supervisor no responde)"
    elif state.phase is Phase.RUNNING and not (
        readiness.ready and state.elsa_alive and state.agent_alive
    ):
        label = "DEGRADADO"
    return "\n".join(
        [
            f"Modo ELSA: {label}{reason}",
            f"  ELSA local  : {_process_line(state.elsa_alive, state.elsa_pid)} · "
            f"{LOOPBACK_BIND}:{state.elsa_port} · {describe_readiness(readiness)}",
            f"  Agente PC1  : {_process_line(state.agent_alive, state.agent_pid)}",
            f"  {RELAY_NOT_VERIFIED}",
            f"  Desde       : {_local_time(state.started_at)}",
            f"  Logs        : {paths.logs}",
        ]
    )


def status(paths: RuntimePaths, out: Output = _print) -> int:
    if not paths.root.exists() or not _supervisor_alive(paths):
        lines = ["Modo ELSA: DETENIDO", f"  {RELAY_NOT_VERIFIED}"]
        if paths.state.exists():
            lines.append("  El último cierre no fue limpio; el próximo inicio limpiará su estado.")
        out("\n".join(lines))
        return EXIT_OK
    state = read_state(paths.state)
    readiness = probe_readiness(state.elsa_port, None) if state is not None else NOT_READY
    out(render_status(state, readiness, paths))
    return EXIT_OK


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def stop(
    paths: RuntimePaths,
    out: Output = _print,
    timeout: float = STOP_TIMEOUT_SECONDS,
    poll: float = 0.5,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Pide la parada y espera. **No detiene ningún proceso por sí mismo.**"""
    if not paths.root.exists():
        out("Modo ELSA no está en marcha.")
        return EXIT_OK
    lock = InstanceLock(paths.lock)
    if lock.acquire():
        try:
            cleaned = clean_stale(paths)
        finally:
            lock.release()
        suffix = " Se limpió un estado residual; no se detuvo ningún proceso." if cleaned else ""
        out(f"Modo ELSA no está en marcha.{suffix}")
        return EXIT_OK
    paths.stop_request.write_text("", encoding="utf-8")
    out("Solicitando la parada de Modo ELSA (agente y después ELSA local)...")
    deadline = clock() + timeout
    while clock() < deadline:
        sleep(poll)
        if lock.acquire():
            try:
                clean_stale(paths)
            finally:
                lock.release()
            out("Modo ELSA detenido.")
            return EXIT_OK
    out(
        f"El supervisor no respondió en {timeout:.0f} s. Cierre la ventana «Modo ELSA»: "
        "al cerrarse, Windows termina sus procesos."
    )
    return EXIT_FAILED


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m elsa.pc1",
        description="Modo ELSA de PC1: ELSA local y agente, en orden y bajo un supervisor.",
    )
    parser.add_argument("command", choices=("start", "status", "stop"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        paths = RuntimePaths(default_runtime_dir())
    except RuntimeDirectoryError:
        _print("No se encontró la carpeta de datos locales del usuario (%LOCALAPPDATA%).")
        return EXIT_CONFIG
    if args.command == "start":
        return start(paths, Path.cwd(), read_secret=_secret_prompt())
    if args.command == "status":
        return status(paths)
    return stop(paths)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
