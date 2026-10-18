"""Procesos propiedad del supervisor (ADR 0034 §6 y §7).

Los hijos son scripts ``python -c`` inofensivos. Los tests marcados ``win32``
ejercitan el Job Object y ``CTRL_BREAK_EVENT``: no corren en el CI de Linux y se
ejecutan y reportan en Windows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from elsa.pc1.processes import ChildSpec, OwnedProcess, StopOutcome, create_job_object, launch

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only mechanism")

# Un hijo que avisa en su log de que ya instaló sus señales y espera.
_SLEEPER = textwrap.dedent(
    """
    import signal, sys, time
    mode = sys.argv[1]
    if mode == "ignore":
        sig = getattr(signal, "SIGBREAK", signal.SIGINT)
        signal.signal(sig, signal.SIG_IGN)
    elif mode == "graceful":
        def stop(signum, frame):
            print("cleanup", flush=True)
            sys.exit(0)
        signal.signal(getattr(signal, "SIGBREAK", signal.SIGINT), stop)
    print("ready", flush=True)
    # Esperas cortas: en Windows `time.sleep` solo lo interrumpe SIGINT, y el
    # manejador de SIGBREAK no correría hasta que terminara la espera.
    for _ in range(1200):
        time.sleep(0.1)
    """
)

_ENV_REPORT = textwrap.dedent(
    """
    import json, os
    print(json.dumps({k: os.environ.get(k) for k in ("PC1_VISIBLE", "PC1_HIDDEN")}), flush=True)
    """
)


def _spec(tmp_path: Path, name: str, *args: str, env: dict[str, str] | None = None) -> ChildSpec:
    return ChildSpec(
        name=name,
        argv=(sys.executable, "-c", *args),
        env=dict(os.environ) if env is None else env,
        cwd=tmp_path,
        log_path=tmp_path / f"{name}.log",
    )


def _wait_for_line(path: Path, line: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and line in path.read_text(encoding="utf-8", errors="replace"):
            return
        time.sleep(0.05)
    raise AssertionError(f"{line!r} not seen in {path.name}")


def test_launch_runs_the_exact_argv_with_the_exact_environment(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PC1_VISIBLE"] = "yes"
    env.pop("PC1_HIDDEN", None)
    spec = _spec(tmp_path, "env-report", _ENV_REPORT, env=env)
    child = launch(spec, None)
    assert child.wait(20)
    assert child.argv == spec.argv
    report = json.loads(spec.log_path.read_text(encoding="utf-8").strip())
    assert report == {"PC1_VISIBLE": "yes", "PC1_HIDDEN": None}


def test_child_output_goes_to_its_log(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    child = launch(_spec(tmp_path, "talker", "print('to-the-log')"), None)
    assert child.wait(20)
    assert "to-the-log" in (tmp_path / "talker.log").read_text(encoding="utf-8")
    assert "to-the-log" not in capfd.readouterr().out


def test_a_child_that_honours_the_stop_signal_stops_gracefully(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "graceful", _SLEEPER, "graceful")
    child = launch(spec, None)
    _wait_for_line(spec.log_path, "ready")
    assert child.stop(graceful_timeout=15) is StopOutcome.GRACEFUL
    assert child.returncode() == 0
    _wait_for_line(spec.log_path, "cleanup")


def test_force_is_used_only_after_the_graceful_timeout(tmp_path: Path) -> None:
    spec = _spec(tmp_path, "stubborn", _SLEEPER, "ignore")
    child = launch(spec, None)
    _wait_for_line(spec.log_path, "ready")
    started = time.monotonic()
    assert child.stop(graceful_timeout=1.0) is StopOutcome.FORCED
    assert time.monotonic() - started >= 1.0
    assert child.returncode() is not None


def test_stopping_an_exited_child_sends_nothing(tmp_path: Path) -> None:
    child = launch(_spec(tmp_path, "quick", "pass"), None)
    assert child.wait(20)
    assert child.stop(graceful_timeout=1) is StopOutcome.ALREADY_EXITED


def test_stopping_an_owned_child_never_touches_a_foreign_process(tmp_path: Path) -> None:
    # Un proceso ajeno: no lo lanzó `launch`, así que no hay OwnedProcess para él.
    foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    try:
        spec = _spec(tmp_path, "own", _SLEEPER, "plain")
        own = launch(spec, None)
        _wait_for_line(spec.log_path, "ready")
        assert own.stop(graceful_timeout=10) in (StopOutcome.GRACEFUL, StopOutcome.FORCED)
        assert foreign.poll() is None
    finally:
        foreign.kill()
        foreign.wait(10)


def test_a_failed_job_assignment_terminates_the_owned_child(tmp_path: Path) -> None:
    class BrokenJob:
        def assign(self, pid: int) -> None:
            raise OSError("assignment refused")

        def close(self) -> None:
            pass

    started: list[OwnedProcess] = []
    original = OwnedProcess.__init__

    def record(self: OwnedProcess, name: str, popen: subprocess.Popen[bytes]) -> None:
        original(self, name, popen)
        started.append(self)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(OwnedProcess, "__init__", record)
        with pytest.raises(OSError):
            launch(_spec(tmp_path, "orphan-risk", _SLEEPER, "plain"), BrokenJob())
    assert len(started) == 1 and started[0].returncode() is not None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX has no job object")
def test_posix_has_no_job_object() -> None:
    assert create_job_object() is None


# ---------------------------------------------------------------------------
# Solo Windows
# ---------------------------------------------------------------------------


def _windows_process_exits(pid: int, timeout_ms: int) -> bool:
    """Consulta por handle si un PID terminó. Solo lee: nunca termina nada."""
    import ctypes
    from ctypes import wintypes

    # `getattr`: `ctypes.WinDLL` solo existe en Windows y mypy también corre en Linux.
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)  # noqa: B009
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    synchronize = 0x00100000
    handle = kernel32.OpenProcess(synchronize, False, pid)
    if not handle:
        return True  # ya no existe
    try:
        return bool(kernel32.WaitForSingleObject(handle, timeout_ms) == 0)
    finally:
        kernel32.CloseHandle(handle)


@windows_only
def test_closing_the_job_object_terminates_its_children(tmp_path: Path) -> None:
    job = create_job_object()
    assert job is not None
    spec = _spec(tmp_path, "in-job", _SLEEPER, "plain")
    child = launch(spec, job)
    _wait_for_line(spec.log_path, "ready")
    assert child.returncode() is None
    job.close()
    assert child.wait(10)


@windows_only
def test_children_do_not_outlive_a_killed_supervisor(tmp_path: Path) -> None:
    """Un supervisor terminado a la fuerza no deja hijos huérfanos (y no es graceful)."""
    supervisor_code = textwrap.dedent(
        f"""
        import sys, time
        from pathlib import Path
        from elsa.pc1.processes import ChildSpec, create_job_object, launch
        job = create_job_object()
        child = launch(
            ChildSpec("grandchild", (sys.executable, "-c", {_SLEEPER!r}, "plain"),
                      dict(__import__("os").environ), Path({str(tmp_path)!r}),
                      Path({str(tmp_path / "grandchild.log")!r})),
            job,
        )
        print(child.pid, flush=True)
        time.sleep(120)
        """
    )
    supervisor = subprocess.Popen(
        [sys.executable, "-c", supervisor_code], stdout=subprocess.PIPE, text=True
    )
    try:
        assert supervisor.stdout is not None
        grandchild_pid = int(supervisor.stdout.readline().strip())
        _wait_for_line(tmp_path / "grandchild.log", "ready")
        assert not _windows_process_exits(grandchild_pid, 0)
        supervisor.kill()  # TerminateProcess: sin ningún código de limpieza
        supervisor.wait(10)
        assert _windows_process_exits(grandchild_pid, 10_000)
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
        if supervisor.stdout is not None:
            supervisor.stdout.close()


@windows_only
def test_ctrl_break_reaches_only_the_childs_own_group(tmp_path: Path) -> None:
    sibling_spec = _spec(tmp_path, "sibling", _SLEEPER, "graceful")
    target_spec = _spec(tmp_path, "target", _SLEEPER, "graceful")
    sibling, target = launch(sibling_spec, None), launch(target_spec, None)
    try:
        _wait_for_line(sibling_spec.log_path, "ready")
        _wait_for_line(target_spec.log_path, "ready")
        assert target.stop(graceful_timeout=15) is StopOutcome.GRACEFUL
        _wait_for_line(target_spec.log_path, "cleanup")
        assert sibling.returncode() is None
    finally:
        sibling.stop(graceful_timeout=15)
