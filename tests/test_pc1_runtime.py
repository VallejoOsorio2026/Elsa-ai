"""Directorio de runtime del Modo ELSA: bloqueo, estado y logs (ADR 0034 §6, §11)."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

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
    write_state,
)

FAKE_TOKEN = "pc1-runtime-test-token-" + "q" * 24

_HOLD_LOCK = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from elsa.pc1.runtime import InstanceLock
    lock = InstanceLock(Path(sys.argv[1]))
    if not lock.acquire():
        print("busy", flush=True)
        sys.exit(3)
    print("held", flush=True)
    if sys.argv[2] == "hold":
        time.sleep(60)
    """
)


@pytest.fixture
def paths(tmp_path: Path) -> RuntimePaths:
    runtime = RuntimePaths(tmp_path / "ELSA" / "mode")
    runtime.ensure()
    return runtime


def _state(**overrides: object) -> RuntimeState:
    values: dict[str, object] = {
        "phase": Phase.RUNNING,
        "supervisor_pid": 4242,
        "started_at": "2026-10-18T10:00:00+00:00",
        "heartbeat_at": "2026-10-18T10:00:05+00:00",
        "elsa_port": 8000,
        "elsa_pid": 4343,
        "elsa_alive": True,
        "elsa_readiness": "ready_degraded",
        "degraded_dependencies": ("transcription",),
        "agent_pid": 4444,
        "agent_alive": True,
    }
    values.update(overrides)
    return RuntimeState(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Directorio
# ---------------------------------------------------------------------------


def test_runtime_dir_lives_under_localappdata(tmp_path: Path) -> None:
    assert default_runtime_dir({"LOCALAPPDATA": str(tmp_path)}) == tmp_path / "ELSA" / "mode"


@pytest.mark.parametrize("value", [None, "", "relative\\path"])
def test_runtime_dir_fails_closed_without_an_absolute_localappdata(value: str | None) -> None:
    environ = {} if value is None else {"LOCALAPPDATA": value}
    with pytest.raises(RuntimeDirectoryError):
        default_runtime_dir(environ)


# ---------------------------------------------------------------------------
# Instancia única
# ---------------------------------------------------------------------------


def test_a_second_acquisition_is_refused_while_the_first_is_held(paths: RuntimePaths) -> None:
    first, second = InstanceLock(paths.lock), InstanceLock(paths.lock)
    assert first.acquire()
    try:
        assert not second.acquire()
        assert not second.held
    finally:
        first.release()
    assert second.acquire()
    second.release()


def test_the_lock_covers_a_real_byte_of_the_file(paths: RuntimePaths) -> None:
    with InstanceLock(paths.lock) as lock:
        assert lock.acquire()
        assert paths.lock.stat().st_size >= 1


def test_another_process_cannot_take_a_held_lock(paths: RuntimePaths) -> None:
    with InstanceLock(paths.lock) as lock:
        assert lock.acquire()
        other = subprocess.run(
            [sys.executable, "-c", _HOLD_LOCK, str(paths.lock), "once"],
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert other.returncode == 3
    assert other.stdout.strip() == "busy"


def test_the_lock_is_released_when_its_owner_process_dies(paths: RuntimePaths) -> None:
    holder = subprocess.Popen(
        [sys.executable, "-c", _HOLD_LOCK, str(paths.lock), "hold"],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        assert not InstanceLock(paths.lock).acquire()
        holder.kill()  # un supervisor que muere sin limpiar nada
        holder.wait(timeout=10)
    finally:
        if holder.poll() is None:
            holder.kill()
        if holder.stdout is not None:
            holder.stdout.close()
    # En un venv de Windows, `holder` es el lanzador: el intérprete que retiene el
    # bloqueo muere justo después, cuando lo termina el lanzador. El sistema libera
    # el bloqueo al morir ese proceso; se espera a que ocurra, con un plazo.
    lock = InstanceLock(paths.lock)
    deadline = time.monotonic() + 10
    while not lock.acquire():
        assert time.monotonic() < deadline, "the lock was not released by the OS"
        time.sleep(0.05)
    lock.release()


# ---------------------------------------------------------------------------
# Estado
# ---------------------------------------------------------------------------


def test_state_round_trips(paths: RuntimePaths) -> None:
    state = _state()
    write_state(paths.state, state)
    assert read_state(paths.state) == state


def test_state_write_is_atomic_and_leaves_no_temporary_file(paths: RuntimePaths) -> None:
    write_state(paths.state, _state(phase=Phase.STARTING))
    write_state(paths.state, _state(phase=Phase.STOPPING))
    assert read_state(paths.state) == _state(phase=Phase.STOPPING)
    assert sorted(p.name for p in paths.root.iterdir()) == ["logs", "state.json"]


def test_state_only_contains_allow_listed_operational_fields(paths: RuntimePaths) -> None:
    write_state(paths.state, _state())
    data = json.loads(paths.state.read_text(encoding="utf-8"))
    assert set(data) == {
        "schema_version",
        "phase",
        "supervisor_pid",
        "started_at",
        "heartbeat_at",
        "elsa_port",
        "elsa_pid",
        "elsa_alive",
        "elsa_readiness",
        "degraded_dependencies",
        "agent_pid",
        "agent_alive",
    }
    assert "token" not in paths.state.read_text(encoding="utf-8").lower()


def test_unknown_fields_in_a_state_file_never_reach_the_reader(paths: RuntimePaths) -> None:
    data = _state().to_json()
    data["node_token"] = FAKE_TOKEN
    data["degraded_dependencies"] = ["transcription", "Bearer abc def", FAKE_TOKEN]
    paths.state.write_text(json.dumps(data), encoding="utf-8")
    state = read_state(paths.state)
    assert state is not None
    assert state.degraded_dependencies == ("transcription",)
    assert FAKE_TOKEN not in repr(state)


@pytest.mark.parametrize(
    "content",
    ["", "not json", "[]", '{"schema_version": 99}', '{"schema_version": 1, "phase": "x"}'],
)
def test_an_unreadable_state_file_reads_as_no_state(paths: RuntimePaths, content: str) -> None:
    paths.state.write_text(content, encoding="utf-8")
    assert read_state(paths.state) is None


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("elsa_port", 0),
        ("elsa_port", 65536),
        ("elsa_port", 2**40),
        ("elsa_port", True),
        ("supervisor_pid", 0),
        ("supervisor_pid", -1),
        ("elsa_pid", -5),
        ("agent_pid", "4444"),
    ],
)
def test_out_of_range_ports_and_pids_read_as_no_state(
    paths: RuntimePaths, field_name: str, value: object
) -> None:
    data = _state().to_json()
    data[field_name] = value
    paths.state.write_text(json.dumps(data), encoding="utf-8")
    assert read_state(paths.state) is None


def test_missing_state_reads_as_no_state(paths: RuntimePaths) -> None:
    assert read_state(paths.state) is None


def test_clean_stale_removes_state_and_stop_request(paths: RuntimePaths) -> None:
    write_state(paths.state, _state())
    paths.stop_request.write_text("", encoding="utf-8")
    assert clean_stale(paths)
    assert not paths.state.exists()
    assert not paths.stop_request.exists()
    assert not clean_stale(paths)


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


def test_rotation_keeps_only_the_current_and_the_previous_log(paths: RuntimePaths) -> None:
    for generation in ("first", "second", "third"):
        rotate_logs(paths)
        paths.log("agent").write_text(generation, encoding="utf-8")
    rotate_logs(paths)
    assert sorted(p.name for p in paths.logs.iterdir()) == ["agent.prev.log"]
    assert (paths.logs / "agent.prev.log").read_text(encoding="utf-8") == "third"
