"""Supervisor del Modo ELSA (ADR 0034 §4–§9).

Tres niveles, todos sin red externa:

- **Unitarios** con hijos, sonda, reloj y job falsos: orden de arranque y parada,
  readiness, rollback, fallos en ejecución, Ctrl+C y ``stop.request``.
- **Sonda de readiness** contra un servidor HTTP local en un hilo.
- **Integración** con procesos reales: un ELSA falso (servidor HTTP en
  loopback) y un agente falso, lanzados y detenidos por el supervisor de verdad.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import textwrap
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import SecretStr

from elsa.agent.config import NODE_TOKEN_ENV, AgentConfig, AgentSettings
from elsa.config import load_settings
from elsa.pc1.preflight import Pc1Profile
from elsa.pc1.processes import ChildSpec, ProcessJob, StopOutcome
from elsa.pc1.runtime import Phase, RuntimePaths, RuntimeState, read_state, write_state
from elsa.pc1.supervisor import (
    AGENT_NAME,
    ELSA_NAME,
    EXIT_FAILED,
    EXIT_OK,
    NOT_READY,
    RELAY_NOT_VERIFIED,
    ChildCommands,
    Readiness,
    ReadinessLevel,
    Supervisor,
    Timings,
    agent_command,
    describe_readiness,
    elsa_command,
    elsa_environment,
    probe_readiness,
)

FAKE_TOKEN = "pc1-supervisor-fake-token-" + "s" * 24
READY = Readiness(ReadinessLevel.READY)
READY_DEGRADED = Readiness(ReadinessLevel.READY_DEGRADED, degraded=("transcription",))
DOWN = Readiness(ReadinessLevel.NOT_READY, critical_down=("auth",))
FORBIDDEN_WORDS = ("CONNECTED", "ONLINE", "CONECTADO")


# ---------------------------------------------------------------------------
# Perfil
# ---------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_profile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, port: int = 8000) -> Pc1Profile:
    for key in list(os.environ):
        if key.startswith("ELSA_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", f"http://127.0.0.1:{port}")
    agent = AgentSettings(
        _env_file=None,  # type: ignore[call-arg]
        relay_url="https://relay.example.test",
        node_id="pc1-test",
        local_base_url=f"http://127.0.0.1:{port}",
    )
    return Pc1Profile(
        settings=load_settings(None),
        agent=AgentConfig(settings=agent, node_token=SecretStr(FAKE_TOKEN)),
        port=port,
        env_file=tmp_path / ".env",
    )


@pytest.fixture
def paths(tmp_path: Path) -> RuntimePaths:
    runtime = RuntimePaths(tmp_path / "runtime")
    runtime.ensure()
    return runtime


# ---------------------------------------------------------------------------
# Falsos
# ---------------------------------------------------------------------------


@dataclass
class World:
    """Reloj, eventos y ganchos compartidos por los falsos."""

    paths: RuntimePaths
    now: float = 0.0
    events: list[str] = field(default_factory=list)
    hooks: list[tuple[float, Callable[[], None]]] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    states: list[Phase] = field(default_factory=list)
    """Cada fase que el supervisor escribe en state.json, en orden."""

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        due = [hook for hook in self.hooks if hook[0] <= self.now]
        self.hooks = [hook for hook in self.hooks if hook[0] > self.now]
        for _, action in due:
            action()

    def at(self, moment: float, action: Callable[[], None]) -> None:
        self.hooks.append((moment, action))

    def request_stop(self) -> None:
        self.paths.stop_request.write_text("", encoding="utf-8")


class FakeChild:
    def __init__(self, name: str, pid: int, world: World) -> None:
        self.name = name
        self._pid = pid
        self._world = world
        self.exit_code: int | None = None
        self.stop_outcome = StopOutcome.GRACEFUL
        self.stop_timeout: float | None = None

    @property
    def pid(self) -> int:
        return self._pid

    def returncode(self) -> int | None:
        return self.exit_code

    def stop(self, graceful_timeout: float) -> StopOutcome:
        self._world.events.append(f"stop:{self.name}")
        self.stop_timeout = graceful_timeout
        if self.exit_code is not None:
            return StopOutcome.ALREADY_EXITED
        self.exit_code = 0
        return self.stop_outcome


class FakeLauncher:
    def __init__(self, world: World) -> None:
        self._world = world
        self.specs: dict[str, ChildSpec] = {}
        self.children: dict[str, FakeChild] = {}
        self.failing: set[str] = set()
        self.on_start: dict[str, Callable[[FakeChild], None]] = {}

    def __call__(self, spec: ChildSpec, job: ProcessJob | None) -> FakeChild:
        self._world.events.append(f"start:{spec.name}")
        if spec.name in self.failing:
            raise OSError("cannot start")
        child = FakeChild(spec.name, 1000 + len(self.children), self._world)
        self.specs[spec.name] = spec
        self.children[spec.name] = child
        if spec.name in self.on_start:
            self.on_start[spec.name](child)
        return child


class FakeJob:
    def __init__(self, world: World) -> None:
        self._world = world
        self.closed = False

    def assign(self, pid: int) -> None:
        pass

    def close(self) -> None:
        self._world.events.append("job:closed")
        self.closed = True


class FakeProbe:
    """Devuelve las respuestas en orden; la última se repite."""

    def __init__(self, world: World, *answers: Readiness) -> None:
        self._world = world
        self.answers = list(answers)

    def __call__(self) -> Readiness:
        self._world.events.append("probe")
        if len(self.answers) > 1:
            return self.answers.pop(0)
        return self.answers[0]


@dataclass
class Harness:
    world: World
    launcher: FakeLauncher
    probe: FakeProbe
    job: FakeJob
    supervisor: Supervisor

    def run(self) -> int:
        return self.supervisor.run()

    def child(self, name: str) -> FakeChild:
        return self.launcher.children[name]


@pytest.fixture
def harness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, paths: RuntimePaths
) -> Callable[..., Harness]:
    def build(*answers: Readiness) -> Harness:
        world = World(paths)

        def recording_write(path: Path, state: RuntimeState) -> None:
            world.states.append(state.phase)
            write_state(path, state)

        monkeypatch.setattr("elsa.pc1.supervisor.write_state", recording_write)
        launcher = FakeLauncher(world)
        probe = FakeProbe(world, *(answers or (READY_DEGRADED,)))
        job = FakeJob(world)
        supervisor = Supervisor(
            profile=make_profile(monkeypatch, tmp_path),
            paths=paths,
            cwd=tmp_path,
            reporter=world.messages.append,
            environ={"PATH": "x", NODE_TOKEN_ENV: FAKE_TOKEN, "ELSA_RELAY_ENABLED": "true"},
            launcher=launcher,
            probe=probe,
            job_factory=lambda: job,
            timings=Timings(ready_timeout=30, agent_grace=5, health_interval=5),
            clock=world.clock,
            sleep=world.sleep,
        )
        return Harness(world, launcher, probe, job, supervisor)

    return build


def _assert_no_connectivity_claims(messages: list[str]) -> None:
    text = "\n".join(messages).upper()
    for word in FORBIDDEN_WORDS:
        assert word not in text


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------


def test_elsa_starts_first_and_the_agent_only_after_readiness(
    harness: Callable[..., Harness],
) -> None:
    h = harness(NOT_READY, NOT_READY, READY_DEGRADED)
    h.world.at(20, h.world.request_stop)
    assert h.run() == EXIT_OK
    events = h.world.events
    assert events[0] == f"start:{ELSA_NAME}"
    agent_start = events.index(f"start:{AGENT_NAME}")
    assert events[1:agent_start] == ["probe", "probe", "probe"]
    assert events[-3:] == [f"stop:{AGENT_NAME}", f"stop:{ELSA_NAME}", "job:closed"]


def test_ready_ok_is_reported_as_ready(harness: Callable[..., Harness]) -> None:
    h = harness(READY)
    h.world.at(20, h.world.request_stop)
    assert h.run() == EXIT_OK
    assert "ELSA LOCAL: LISTA" in h.world.messages


def test_ready_with_non_critical_degradations_still_starts_the_agent(
    harness: Callable[..., Harness],
) -> None:
    h = harness(READY_DEGRADED)
    h.world.at(20, h.world.request_stop)
    assert h.run() == EXIT_OK
    assert "ELSA LOCAL: LISTA CON DEGRADACIONES NO CRÍTICAS (transcription)" in h.world.messages
    assert f"start:{AGENT_NAME}" in h.world.events
    assert Phase.RUNNING in h.world.states


def test_running_summary_never_claims_relay_connectivity(harness: Callable[..., Harness]) -> None:
    h = harness(READY)
    h.world.at(20, h.world.request_stop)
    h.run()
    summary = next(m for m in h.world.messages if "Modo ELSA: EN MARCHA" in m)
    assert RELAY_NOT_VERIFIED in summary
    _assert_no_connectivity_claims(h.world.messages)


def test_elsa_that_never_gets_ready_is_rolled_back_without_the_agent(
    harness: Callable[..., Harness],
) -> None:
    h = harness(DOWN)
    assert h.run() == EXIT_FAILED
    assert f"start:{AGENT_NAME}" not in h.world.events
    assert h.world.events[-2:] == [f"stop:{ELSA_NAME}", "job:closed"]
    message = next(m for m in h.world.messages if "No quedó lista" in m)
    assert "NO LISTA (dependencias críticas caídas: auth)" in message
    assert str(h.world.paths.log(ELSA_NAME)) in message


def test_unreachable_elsa_is_not_ready(harness: Callable[..., Harness]) -> None:
    h = harness(NOT_READY)
    assert h.run() == EXIT_FAILED
    assert f"start:{AGENT_NAME}" not in h.world.events
    assert any("ELSA LOCAL: NO LISTA." in m for m in h.world.messages)


def test_elsa_exiting_before_readiness_never_starts_the_agent(
    harness: Callable[..., Harness],
) -> None:
    h = harness(NOT_READY)
    h.world.at(3, lambda: setattr(h.child(ELSA_NAME), "exit_code", 1))
    assert h.run() == EXIT_FAILED
    assert f"start:{AGENT_NAME}" not in h.world.events
    assert any("ELSA local terminó durante el arranque (código 1)" in m for m in h.world.messages)


def test_a_ready_answer_from_a_dead_elsa_is_not_trusted(harness: Callable[..., Harness]) -> None:
    h = harness(READY)
    h.launcher.on_start[ELSA_NAME] = lambda child: setattr(child, "exit_code", 1)
    assert h.run() == EXIT_FAILED
    assert f"start:{AGENT_NAME}" not in h.world.events


def test_an_agent_dying_during_its_grace_period_rolls_everything_back(
    harness: Callable[..., Harness],
) -> None:
    h = harness(READY)
    h.launcher.on_start[AGENT_NAME] = lambda child: setattr(child, "exit_code", 2)
    assert h.run() == EXIT_FAILED
    assert h.world.events[-3:] == [f"stop:{AGENT_NAME}", f"stop:{ELSA_NAME}", "job:closed"]
    assert any(
        "El agente de PC1 terminó durante el arranque (código 2)" in m for m in h.world.messages
    )
    assert Phase.RUNNING not in h.world.states


def test_an_agent_that_cannot_be_launched_rolls_elsa_back(
    harness: Callable[..., Harness],
) -> None:
    h = harness(READY)
    h.launcher.failing.add(AGENT_NAME)
    assert h.run() == EXIT_FAILED
    assert h.world.events[-2:] == [f"stop:{ELSA_NAME}", "job:closed"]


def test_without_a_job_object_nothing_is_launched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, paths: RuntimePaths
) -> None:
    world = World(paths)
    launcher = FakeLauncher(world)

    def broken_job() -> ProcessJob | None:
        raise OSError("no job")

    supervisor = Supervisor(
        profile=make_profile(monkeypatch, tmp_path),
        paths=paths,
        cwd=tmp_path,
        reporter=world.messages.append,
        launcher=launcher,
        probe=FakeProbe(world, READY),
        job_factory=broken_job,
        clock=world.clock,
        sleep=world.sleep,
    )
    assert supervisor.run() == EXIT_FAILED
    assert launcher.children == {}


# ---------------------------------------------------------------------------
# Ejecución
# ---------------------------------------------------------------------------


def test_an_agent_dying_while_running_stops_elsa_without_restarting(
    harness: Callable[..., Harness],
) -> None:
    h = harness(READY)
    h.world.at(30, lambda: setattr(h.child(AGENT_NAME), "exit_code", 1))
    assert h.run() == EXIT_FAILED
    assert h.world.events.count(f"start:{AGENT_NAME}") == 1
    assert h.world.events[-3:] == [f"stop:{AGENT_NAME}", f"stop:{ELSA_NAME}", "job:closed"]
    assert any("El agente de PC1 terminó inesperadamente (código 1)" in m for m in h.world.messages)
    assert Phase.DEGRADED in h.world.states


def test_elsa_dying_while_running_stops_the_agent(harness: Callable[..., Harness]) -> None:
    h = harness(READY)
    h.world.at(30, lambda: setattr(h.child(ELSA_NAME), "exit_code", 3))
    assert h.run() == EXIT_FAILED
    assert h.world.events.count(f"start:{ELSA_NAME}") == 1
    assert h.child(AGENT_NAME).stop_timeout is not None
    assert any("ELSA local terminó inesperadamente (código 3)" in m for m in h.world.messages)


def test_losing_readiness_degrades_without_stopping_and_recovers(
    harness: Callable[..., Harness],
) -> None:
    h = harness(READY, DOWN, DOWN, READY)
    h.world.at(60, h.world.request_stop)
    assert h.run() == EXIT_OK
    phases = h.world.states
    first_degraded = phases.index(Phase.DEGRADED)
    assert Phase.RUNNING in phases[:first_degraded]
    assert Phase.RUNNING in phases[first_degraded:]
    assert any("Modo ELSA: DEGRADADO" in m for m in h.world.messages)
    assert h.world.events.count(f"start:{AGENT_NAME}") == 1


def test_the_heartbeat_is_refreshed_while_running(harness: Callable[..., Harness]) -> None:
    beats: list[str] = []
    h = harness(READY)
    ticks = iter(f"2026-10-18T10:00:{second:02d}+00:00" for second in range(60))
    h.supervisor._now = lambda: next(ticks)

    def capture() -> None:
        state = read_state(h.world.paths.state)
        assert state is not None
        beats.append(state.heartbeat_at)

    for moment in (12, 22, 32):
        h.world.at(moment, capture)
    h.world.at(40, h.world.request_stop)
    h.run()
    assert len(set(beats)) == 3


# ---------------------------------------------------------------------------
# Parada
# ---------------------------------------------------------------------------


def test_a_stop_request_stops_the_agent_before_elsa(harness: Callable[..., Harness]) -> None:
    h = harness(READY)
    h.world.at(20, h.world.request_stop)
    assert h.run() == EXIT_OK
    assert h.child(AGENT_NAME).stop_timeout == 10.0
    assert h.child(ELSA_NAME).stop_timeout == 20.0
    assert h.world.events.index(f"stop:{AGENT_NAME}") < h.world.events.index(f"stop:{ELSA_NAME}")
    assert not h.world.paths.state.exists()
    assert not h.world.paths.stop_request.exists()
    assert h.job.closed
    assert h.world.messages[-1] == "Modo ELSA detenido."


def test_ctrl_c_while_running_stops_in_order(harness: Callable[..., Harness]) -> None:
    h = harness(READY)

    def interrupt() -> None:
        raise KeyboardInterrupt

    h.world.at(20, interrupt)
    assert h.run() == EXIT_OK
    assert h.world.events[-3:] == [f"stop:{AGENT_NAME}", f"stop:{ELSA_NAME}", "job:closed"]
    assert "Parada solicitada con Ctrl+C." in h.world.messages


def test_ctrl_c_during_startup_never_starts_the_agent(harness: Callable[..., Harness]) -> None:
    h = harness(NOT_READY)

    def interrupt() -> None:
        raise KeyboardInterrupt

    h.world.at(3, interrupt)
    assert h.run() == EXIT_OK
    assert f"start:{AGENT_NAME}" not in h.world.events
    assert h.world.events[-2:] == [f"stop:{ELSA_NAME}", "job:closed"]


def test_a_stop_request_during_startup_never_starts_the_agent(
    harness: Callable[..., Harness],
) -> None:
    h = harness(NOT_READY)
    h.world.at(3, h.world.request_stop)
    assert h.run() == EXIT_OK
    assert f"start:{AGENT_NAME}" not in h.world.events


def test_a_forced_stop_is_reported_as_forced(harness: Callable[..., Harness]) -> None:
    h = harness(READY)
    h.launcher.on_start[ELSA_NAME] = lambda child: setattr(
        child, "stop_outcome", StopOutcome.FORCED
    )
    h.world.at(20, h.world.request_stop)
    h.run()
    assert any("ELSA local no respondió a la parada ordenada" in m for m in h.world.messages)


# ---------------------------------------------------------------------------
# Secretos y comandos
# ---------------------------------------------------------------------------


def test_only_the_agent_receives_the_node_token_and_never_through_argv(
    harness: Callable[..., Harness],
) -> None:
    h = harness(READY)
    h.world.at(20, h.world.request_stop)
    h.run()
    elsa, agent = h.launcher.specs[ELSA_NAME], h.launcher.specs[AGENT_NAME]
    assert NODE_TOKEN_ENV not in elsa.env
    assert agent.env[NODE_TOKEN_ENV] == FAKE_TOKEN
    for spec in (elsa, agent):
        assert all(FAKE_TOKEN not in arg for arg in spec.argv)


def test_the_elsa_child_runs_the_pc1_profile_whatever_the_environment_says(
    harness: Callable[..., Harness],
) -> None:
    h = harness(READY)
    h.world.at(20, h.world.request_stop)
    h.run()
    env = h.launcher.specs[ELSA_NAME].env
    assert env["ELSA_ASSISTANT_EXECUTION_MODE"] == "local"
    assert env["ELSA_RELAY_ENABLED"] == "false"  # el entorno de prueba decía "true"
    assert env["ELSA_DEBUG"] == "false"


def test_the_state_file_never_holds_the_token(harness: Callable[..., Harness]) -> None:
    snapshots: list[str] = []
    h = harness(READY)
    h.world.at(15, lambda: snapshots.append(h.world.paths.state.read_text(encoding="utf-8")))
    h.world.at(20, h.world.request_stop)
    h.run()
    assert snapshots and all(FAKE_TOKEN not in snap for snap in snapshots)


def test_default_commands_bind_loopback_and_carry_no_secret(tmp_path: Path) -> None:
    command = elsa_command(8123)
    assert command[command.index("--host") + 1] == "127.0.0.1"
    assert command[command.index("--port") + 1] == "8123"
    assert "--no-access-log" in command
    assert "0.0.0.0" not in command
    assert agent_command(tmp_path / ".env")[1:4] == ("-m", "elsa.agent", "--env-file")


def test_elsa_environment_removes_the_token_explicitly() -> None:
    env = elsa_environment({NODE_TOKEN_ENV: FAKE_TOKEN, "KEEP": "1"})
    assert NODE_TOKEN_ENV not in env and env["KEEP"] == "1"


# ---------------------------------------------------------------------------
# Sonda de readiness
# ---------------------------------------------------------------------------


class _ReadyHandler(http.server.BaseHTTPRequestHandler):
    status_code = 200
    body: bytes = b""

    def do_GET(self) -> None:  # noqa: N802 - nombre impuesto por http.server
        self.send_response(self.status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


@pytest.fixture
def ready_server() -> Iterator[Callable[[int, object], int]]:
    servers: list[http.server.HTTPServer] = []

    def serve(status_code: int, payload: object) -> int:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        handler = type("Handler", (_ReadyHandler,), {"status_code": status_code, "body": body})
        server = http.server.HTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return int(server.server_address[1])

    yield serve
    for server in servers:
        server.shutdown()
        server.server_close()


def _health(status: str, **dependencies: dict[str, object]) -> dict[str, object]:
    return {"status": status, "environment": "DEV", "dependencies": dependencies}


def test_probe_200_ok_is_ready(ready_server: Callable[[int, object], int]) -> None:
    port = ready_server(200, _health("ok", auth={"status": "ok", "critical": True}))
    assert probe_readiness(port, "DEV") == READY
    assert describe_readiness(READY) == "LISTA"


def test_probe_200_degraded_is_ready_with_names_only(
    ready_server: Callable[[int, object], int],
) -> None:
    payload = _health(
        "degraded",
        auth={"status": "ok", "critical": True},
        transcription={"status": "degraded", "critical": False, "detail": "SECRET-DETAIL"},
        embeddings={"status": "not_configured", "critical": False, "detail": "x"},
    )
    readiness = probe_readiness(ready_server(200, payload), "DEV")
    assert readiness.level is ReadinessLevel.READY_DEGRADED
    assert readiness.degraded == ("transcription", "embeddings")
    text = describe_readiness(readiness)
    assert text == "LISTA CON DEGRADACIONES NO CRÍTICAS (transcription, embeddings)"
    assert "SECRET-DETAIL" not in text


def test_probe_503_is_not_ready_with_the_critical_names(
    ready_server: Callable[[int, object], int],
) -> None:
    payload = _health("down", auth={"status": "down", "critical": True, "detail": "SECRET"})
    readiness = probe_readiness(ready_server(503, payload), "DEV")
    assert readiness == DOWN
    assert describe_readiness(readiness) == "NO LISTA (dependencias críticas caídas: auth)"


def test_probe_without_a_listener_is_not_ready() -> None:
    assert probe_readiness(free_port(), "DEV", timeout=1) == NOT_READY


@pytest.mark.parametrize(
    "payload",
    [b"not json", b"[]", json.dumps(_health("ok")).encode().replace(b"DEV", b"TEST")],
)
def test_probe_with_an_unexpected_answer_is_not_ready(
    ready_server: Callable[[int, object], int], payload: bytes
) -> None:
    assert probe_readiness(ready_server(200, payload), "DEV") == NOT_READY


def test_probe_without_an_expected_environment_skips_that_check(
    ready_server: Callable[[int, object], int],
) -> None:
    port = ready_server(200, {"status": "ok", "environment": "TEST", "dependencies": {}})
    assert probe_readiness(port, None) == READY


def test_probe_rejects_an_oversized_answer(ready_server: Callable[[int, object], int]) -> None:
    payload = _health("ok") | {"padding": "x" * (70 * 1024)}
    assert probe_readiness(ready_server(200, payload), "DEV") == NOT_READY


# ---------------------------------------------------------------------------
# Integración con procesos reales
# ---------------------------------------------------------------------------

FAKE_ELSA = textwrap.dedent(
    """
    import http.server, json, os, signal, sys, time
    port = int(sys.argv[1])
    print(json.dumps({
        "token_in_env": "ELSA_AGENT_NODE_TOKEN" in os.environ,
        "mode": os.environ.get("ELSA_ASSISTANT_EXECUTION_MODE"),
        "relay_enabled": os.environ.get("ELSA_RELAY_ENABLED"),
    }), flush=True)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({
                "status": "degraded", "environment": "DEV",
                "dependencies": {"transcription": {
                    "status": "degraded", "critical": False, "detail": "simulated",
                }},
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 0.1
    stopping = []
    signal.signal(getattr(signal, "SIGBREAK", signal.SIGINT), lambda *a: stopping.append(1))
    while not stopping:
        server.handle_request()
    server.server_close()
    print(json.dumps({"cleanup": time.monotonic()}), flush=True)
    """
)

FAKE_AGENT = textwrap.dedent(
    """
    import json, os, signal, time
    print(json.dumps({"token_in_env": "ELSA_AGENT_NODE_TOKEN" in os.environ}), flush=True)
    stopping = []
    signal.signal(getattr(signal, "SIGBREAK", signal.SIGINT), lambda *a: stopping.append(1))
    while not stopping:
        time.sleep(0.05)
    print(json.dumps({"cleanup": time.monotonic()}), flush=True)
    """
)


def fake_commands(port: int) -> ChildCommands:
    return ChildCommands(
        elsa=(sys.executable, "-c", FAKE_ELSA, str(port)),
        agent=(sys.executable, "-c", FAKE_AGENT),
    )


def log_records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def all_runtime_text(paths: RuntimePaths) -> str:
    return "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in paths.root.rglob("*")
        if p.is_file()
    )


def test_real_processes_start_in_order_and_stop_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, paths: RuntimePaths
) -> None:
    port = free_port()
    profile = make_profile(monkeypatch, tmp_path, port)
    messages: list[str] = []
    seen_states: list[str] = []

    def reporter(message: str) -> None:
        messages.append(message)
        if "Modo ELSA: EN MARCHA" in message:
            seen_states.append(paths.state.read_text(encoding="utf-8"))
            paths.stop_request.write_text("", encoding="utf-8")

    environ = dict(os.environ)
    environ[NODE_TOKEN_ENV] = FAKE_TOKEN
    supervisor = Supervisor(
        profile=profile,
        paths=paths,
        cwd=tmp_path,
        reporter=reporter,
        environ=environ,
        commands=fake_commands(port),
        timings=Timings(ready_timeout=30, ready_poll=0.1, agent_grace=0.5, watch_interval=0.1),
    )
    assert supervisor.run() == EXIT_OK

    elsa_log = log_records(paths.log(ELSA_NAME))
    agent_log = log_records(paths.log(AGENT_NAME))
    assert elsa_log[0] == {"token_in_env": False, "mode": "local", "relay_enabled": "false"}
    assert agent_log[0] == {"token_in_env": True}
    # Agente primero, ELSA después: el agente terminó su limpieza antes.
    agent_cleanup, elsa_cleanup = agent_log[-1]["cleanup"], elsa_log[-1]["cleanup"]
    assert isinstance(agent_cleanup, float) and isinstance(elsa_cleanup, float)
    assert agent_cleanup < elsa_cleanup
    # Nada quedó escuchando y el estado se limpió.
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
    assert not paths.state.exists()
    assert seen_states and FAKE_TOKEN not in seen_states[0]
    assert FAKE_TOKEN not in all_runtime_text(paths)
    assert FAKE_TOKEN not in "\n".join(messages)
    _assert_no_connectivity_claims(messages)
