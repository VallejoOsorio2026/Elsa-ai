"""Operación del Modo ELSA: start, status y stop (ADR 0034 §2, §6–§9).

Sin red externa: los «supervisores vivos» son hilos que retienen el bloqueo y la
integración final usa los procesos falsos de ``test_pc1_supervisor``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from elsa.agent.config import NODE_TOKEN_ENV
from elsa.pc1 import __main__ as cli
from elsa.pc1.runtime import InstanceLock, Phase, RuntimePaths, RuntimeState, write_state
from elsa.pc1.supervisor import (
    EXIT_ALREADY_RUNNING,
    EXIT_CONFIG,
    EXIT_FAILED,
    EXIT_OK,
    RELAY_NOT_VERIFIED,
    Readiness,
    ReadinessLevel,
)
from tests.test_pc1_supervisor import (
    FAKE_AGENT,
    FAKE_ELSA,
    FORBIDDEN_WORDS,
    all_runtime_text,
    free_port,
    ready_server,  # noqa: F401 - fixture compartida
)

FAKE_TOKEN = "pc1-cli-fake-token-" + "c" * 28


@pytest.fixture
def paths(tmp_path: Path) -> RuntimePaths:
    return RuntimePaths(tmp_path / "LocalAppData" / "ELSA" / "mode")


@pytest.fixture
def out() -> list[str]:
    return []


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith("ELSA_"):
            monkeypatch.delenv(key)
    yield
    os.environ.pop(NODE_TOKEN_ENV, None)


def write_env(cwd: Path, port: int, **extra: str) -> None:
    values = {
        "ELSA_ENV": "DEV",
        "ELSA_CORS_ORIGINS": f"http://127.0.0.1:{port}",
        "ELSA_AGENT_RELAY_URL": "https://relay.example.test",
        "ELSA_AGENT_NODE_ID": "pc1-test",
        "ELSA_AGENT_LOCAL_BASE_URL": f"http://127.0.0.1:{port}",
        **extra,
    }
    (cwd / ".env").write_text("".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")


def running_state(port: int, *, phase: Phase = Phase.RUNNING, age: float = 0.0) -> RuntimeState:
    beat = (datetime.now(UTC) - timedelta(seconds=age)).isoformat(timespec="seconds")
    return RuntimeState(
        phase=phase,
        supervisor_pid=4242,
        started_at=beat,
        heartbeat_at=beat,
        elsa_port=port,
        elsa_pid=4343,
        elsa_alive=True,
        elsa_readiness="ready_degraded",
        degraded_dependencies=("transcription",),
        agent_pid=4444,
        agent_alive=True,
    )


def assert_honest(text: str) -> None:
    assert RELAY_NOT_VERIFIED in text
    for word in FORBIDDEN_WORDS:
        assert word not in text.upper()


@pytest.fixture
def live_supervisor(paths: RuntimePaths) -> Iterator[InstanceLock]:
    """Un supervisor vivo, a efectos del bloqueo: otro handle lo retiene."""
    paths.ensure()
    lock = InstanceLock(paths.lock)
    assert lock.acquire()
    yield lock
    lock.release()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_fails_closed_without_localappdata(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert cli.main(["status"]) == EXIT_CONFIG
    assert "%LOCALAPPDATA%" in capsys.readouterr().out


def test_main_status_uses_the_localappdata_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert cli.main(["status"]) == EXIT_OK
    assert "Modo ELSA: DETENIDO" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_without_a_supervisor_is_stopped(paths: RuntimePaths, out: list[str]) -> None:
    assert cli.status(paths, out.append) == EXIT_OK
    assert out[0].splitlines()[0] == "Modo ELSA: DETENIDO"
    assert_honest(out[0])


def test_status_reports_a_stale_state_without_touching_it(
    paths: RuntimePaths, out: list[str]
) -> None:
    paths.ensure()
    write_state(paths.state, running_state(8000))
    cli.status(paths, out.append)
    assert "Modo ELSA: DETENIDO" in out[0]
    assert "no fue limpio" in out[0]
    assert paths.state.exists()  # status es de solo lectura


def test_status_running_and_ready_with_degradations(
    paths: RuntimePaths,
    out: list[str],
    live_supervisor: InstanceLock,
    ready_server: Callable[[int, object], int],  # noqa: F811 - fixture importada
) -> None:
    port = ready_server(
        200,
        {
            "status": "degraded",
            "environment": "DEV",
            "dependencies": {"transcription": {"status": "degraded", "critical": False}},
        },
    )
    write_state(paths.state, running_state(port))
    cli.status(paths, out.append)
    lines = out[0].splitlines()
    assert lines[0] == "Modo ELSA: EN MARCHA"
    assert "proceso activo (PID 4343)" in lines[1]
    assert f"127.0.0.1:{port}" in lines[1]
    assert "LISTA CON DEGRADACIONES NO CRÍTICAS (transcription)" in lines[1]
    assert "proceso activo (PID 4444)" in lines[2]
    assert_honest(out[0])


def test_status_is_degraded_when_elsa_stops_answering(
    paths: RuntimePaths, out: list[str], live_supervisor: InstanceLock
) -> None:
    write_state(paths.state, running_state(free_port()))
    cli.status(paths, out.append)
    assert out[0].splitlines()[0] == "Modo ELSA: DEGRADADO"
    assert "NO LISTA" in out[0]
    assert_honest(out[0])


def test_status_is_degraded_when_elsa_answers_503(
    paths: RuntimePaths,
    out: list[str],
    live_supervisor: InstanceLock,
    ready_server: Callable[[int, object], int],  # noqa: F811 - fixture importada
) -> None:
    port = ready_server(
        503,
        {
            "status": "down",
            "environment": "DEV",
            "dependencies": {"auth": {"status": "down", "critical": True}},
        },
    )
    write_state(paths.state, running_state(port))
    cli.status(paths, out.append)
    assert out[0].splitlines()[0] == "Modo ELSA: DEGRADADO"
    assert "dependencias críticas caídas: auth" in out[0]


def test_status_is_degraded_when_the_supervisor_heartbeat_is_stale(
    paths: RuntimePaths, out: list[str], live_supervisor: InstanceLock
) -> None:
    write_state(paths.state, running_state(free_port(), age=60))
    cli.status(paths, out.append)
    assert out[0].splitlines()[0] == "Modo ELSA: DEGRADADO (el supervisor no responde)"


@pytest.mark.parametrize(
    ("phase", "label"),
    [
        (Phase.STARTING, "ARRANCANDO"),
        (Phase.STOPPING, "DETENIÉNDOSE"),
        (Phase.DEGRADED, "DEGRADADO"),
    ],
)
def test_status_shows_each_supervisor_phase(
    paths: RuntimePaths, out: list[str], live_supervisor: InstanceLock, phase: Phase, label: str
) -> None:
    write_state(paths.state, running_state(free_port(), phase=phase))
    cli.status(paths, out.append)
    assert out[0].splitlines()[0] == f"Modo ELSA: {label}"
    assert_honest(out[0])


def test_status_before_the_first_state_write_is_starting(
    paths: RuntimePaths, out: list[str], live_supervisor: InstanceLock
) -> None:
    cli.status(paths, out.append)
    assert out[0].splitlines()[0] == "Modo ELSA: ARRANCANDO"
    assert_honest(out[0])


def test_render_status_never_claims_connectivity(paths: RuntimePaths) -> None:
    for level in ReadinessLevel:
        for phase in Phase:
            text = cli.render_status(running_state(8000, phase=phase), Readiness(level), paths)
            assert_honest(text)


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_without_a_supervisor_does_nothing(paths: RuntimePaths, out: list[str]) -> None:
    assert cli.stop(paths, out.append) == EXIT_OK
    assert out == ["Modo ELSA no está en marcha."]


def test_stop_cleans_a_stale_state_without_signalling_its_pids(
    paths: RuntimePaths, out: list[str]
) -> None:
    # Un proceso ajeno vivo cuyo PID figura en un estado residual: no se toca.
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        paths.ensure()
        state = running_state(8000)
        write_state(
            paths.state,
            RuntimeState(**{**state.__dict__, "elsa_pid": foreign.pid, "agent_pid": foreign.pid}),
        )
        paths.stop_request.write_text("", encoding="utf-8")
        assert cli.stop(paths, out.append) == EXIT_OK
        assert "Se limpió un estado residual" in out[0]
        assert not paths.state.exists() and not paths.stop_request.exists()
        assert foreign.poll() is None
    finally:
        foreign.kill()
        foreign.wait(10)


def test_stop_asks_the_supervisor_and_waits_for_it(paths: RuntimePaths, out: list[str]) -> None:
    paths.ensure()
    held = threading.Event()
    asked = threading.Event()

    def supervisor() -> None:
        lock = InstanceLock(paths.lock)
        assert lock.acquire()
        held.set()
        while not paths.stop_request.exists():
            threading.Event().wait(0.05)
        asked.set()
        paths.stop_request.unlink()
        lock.release()

    thread = threading.Thread(target=supervisor)
    thread.start()
    assert held.wait(10)
    assert cli.stop(paths, out.append, timeout=20, poll=0.05) == EXIT_OK
    thread.join(10)
    assert asked.is_set()
    assert out[-1] == "Modo ELSA detenido."


def test_stop_reports_an_unresponsive_supervisor(
    paths: RuntimePaths, out: list[str], live_supervisor: InstanceLock
) -> None:
    now = [0.0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    assert cli.stop(paths, out.append, timeout=60, clock=lambda: now[0], sleep=sleep) == EXIT_FAILED
    assert "Cierre la ventana «Modo ELSA»" in out[-1]
    assert paths.stop_request.exists()  # sigue pedida; el supervisor puede atenderla aún


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


class RecordingSupervisor:
    calls: list[dict[str, object]] = []

    def __init__(self, **kwargs: object) -> None:
        paths = kwargs["paths"]
        assert isinstance(paths, RuntimePaths)
        self._paths = paths
        RecordingSupervisor.calls.append(kwargs)

    def run(self) -> int:
        RecordingSupervisor.calls[-1]["stop_request_at_run"] = self._paths.stop_request.exists()
        RecordingSupervisor.calls[-1]["state_at_run"] = self._paths.state.exists()
        return EXIT_OK


@pytest.fixture
def recording() -> Iterator[type[RecordingSupervisor]]:
    RecordingSupervisor.calls = []
    yield RecordingSupervisor


def test_start_refuses_a_second_instance(
    paths: RuntimePaths,
    out: list[str],
    tmp_path: Path,
    live_supervisor: InstanceLock,
    recording: type[RecordingSupervisor],
) -> None:
    code = cli.start(paths, tmp_path, out.append, supervisor_factory=recording)
    assert code == EXIT_ALREADY_RUNNING
    assert "ya está en marcha" in out[0]
    assert recording.calls == []


def test_start_cleans_stale_state_and_never_obeys_an_old_stop_request(
    paths: RuntimePaths,
    out: list[str],
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    recording: type[RecordingSupervisor],
) -> None:
    paths.ensure()
    write_state(paths.state, running_state(8000))
    paths.stop_request.write_text("", encoding="utf-8")
    write_env(tmp_path, free_port())
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    assert cli.start(paths, tmp_path, out.append, supervisor_factory=recording) == EXIT_OK
    assert "no fue limpio" in out[0]
    assert recording.calls[0]["stop_request_at_run"] is False
    assert recording.calls[0]["state_at_run"] is False


def test_start_with_invalid_configuration_starts_nothing(
    paths: RuntimePaths,
    out: list[str],
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    recording: type[RecordingSupervisor],
) -> None:
    write_env(tmp_path, free_port(), ELSA_ASSISTANT_EXECUTION_MODE="relay")
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    assert cli.start(paths, tmp_path, out.append, supervisor_factory=recording) == EXIT_CONFIG
    assert "ELSA_ASSISTANT_EXECUTION_MODE" in out[-1]
    assert recording.calls == []
    assert InstanceLock(paths.lock).acquire()  # el bloqueo se liberó


def test_start_without_token_and_without_console_fails_closed(
    paths: RuntimePaths,
    out: list[str],
    tmp_path: Path,
    clean_env: None,
    recording: type[RecordingSupervisor],
) -> None:
    write_env(tmp_path, free_port())
    code = cli.start(paths, tmp_path, out.append, read_secret=None, supervisor_factory=recording)
    assert code == EXIT_CONFIG
    assert NODE_TOKEN_ENV in out[-1]
    assert recording.calls == []


def test_start_with_the_port_taken_by_an_unknown_process_fails_closed(
    paths: RuntimePaths,
    out: list[str],
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    recording: type[RecordingSupervisor],
) -> None:
    import socket

    foreign = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        foreign.bind(("127.0.0.1", 0))
        foreign.listen()
        port = int(foreign.getsockname()[1])
        write_env(tmp_path, port)
        monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
        assert cli.start(paths, tmp_path, out.append, supervisor_factory=recording) == EXIT_FAILED
        assert f"127.0.0.1:{port} está ocupado" in out[-1]
        assert recording.calls == []
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass  # el proceso ajeno sigue intacto
    finally:
        foreign.close()


# ---------------------------------------------------------------------------
# Integración: start real con hijos falsos, status y un segundo start
# ---------------------------------------------------------------------------


def test_full_start_status_and_stop_with_real_processes(
    paths: RuntimePaths,
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = free_port()
    write_env(tmp_path, port)
    monkeypatch.setattr(
        "elsa.pc1.supervisor.elsa_command", lambda p: (sys.executable, "-c", FAKE_ELSA, str(p))
    )
    monkeypatch.setattr(
        "elsa.pc1.supervisor.agent_command", lambda f: (sys.executable, "-c", FAKE_AGENT)
    )
    output: list[str] = []
    observed: dict[str, object] = {}

    def reporter(message: str) -> None:
        output.append(message)
        if "Modo ELSA: EN MARCHA" in message and "status" not in observed:
            status_out: list[str] = []
            cli.status(paths, status_out.append)
            observed["status"] = status_out[0]
            second: list[str] = []
            observed["second_start"] = cli.start(paths, tmp_path, second.append)
            paths.stop_request.write_text("", encoding="utf-8")

    def prompt() -> str:
        return FAKE_TOKEN

    assert cli.start(paths, tmp_path, reporter, read_secret=prompt) == EXIT_OK

    status_text = observed["status"]
    assert isinstance(status_text, str)
    assert status_text.splitlines()[0] == "Modo ELSA: EN MARCHA"
    assert "LISTA CON DEGRADACIONES NO CRÍTICAS (transcription)" in status_text
    assert_honest(status_text)
    assert observed["second_start"] == EXIT_ALREADY_RUNNING
    assert output[-1] == "Modo ELSA detenido."
    assert not paths.state.exists()
    supervisor_log = paths.log("supervisor").read_text(encoding="utf-8")
    assert "child_started" in supervisor_log and "supervisor_stopped" in supervisor_log
    # El token no aparece en ningún archivo de runtime ni en ningún mensaje.
    assert FAKE_TOKEN not in all_runtime_text(paths)
    assert FAKE_TOKEN not in "\n".join(output) + status_text
