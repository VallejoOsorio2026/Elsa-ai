"""El runner contra Git de verdad, en repositorios temporales y con origen local.

Nada aquí llama a Claude, a GitHub, a Render, a Supabase ni a SAP. El ejecutor y
el escáner son falsos a propósito, pero Git, los procesos y los plazos son reales.
Los tests marcados ``windows_only`` ejercitan el Job Object: no corren en el CI
de Linux y se ejecutan y reportan en Windows.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import orchestrator
import pytest
from orchestrator import (
    Gate,
    Reason,
    Result,
    RunnerConfig,
    RunnerLock,
    RunReport,
    Spec,
    cleanup_block,
    run_block,
    run_process,
    status_worktrees,
    validate_block,
)

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only mechanism")

FAKE_EXECUTOR = Path(__file__).resolve().parent / "fake_orchestrator_executor.py"
BLOCK = "T1.1"
BRANCH = "claude/t1-1-prueba"

_FAKE_PRECOMMIT = textwrap.dedent(
    """
    import pathlib, subprocess, sys
    here = pathlib.Path(__file__).parent
    mode = (here / "mode.txt").read_text(encoding="utf-8").strip()
    cached = ["git", "diff", "--cached"]
    staged = subprocess.run([*cached, "--name-only"], capture_output=True, text=True)
    diff = subprocess.run(cached, capture_output=True, text=True)
    with open(here / "calls.log", "a", encoding="utf-8") as log:
        log.write(" ".join(sys.argv[1:]) + " | " + ",".join(staged.stdout.split()) + "\\n")
    if mode == "skip":
        print("Detect hardcoded secrets....(no files to check)Skipped")
        sys.exit(0)
    if mode == "error":
        print("An unexpected error has occurred")
        sys.exit(3)
    if mode == "leak" or "ghp_" in diff.stdout:
        print("Detect hardcoded secrets....Failed")
        print("Finding: token = REDACTED")
        print("leaks found: 1")
        sys.exit(1)
    print("Detect hardcoded secrets....Passed")
    """
)


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return done.stdout.strip()


@dataclass(frozen=True)
class FakeExecutor:
    scenario: str
    heartbeat: str = ""
    kind: str = "fake"

    def command(self, worktree: Path, spec_path: str) -> tuple[str, ...] | None:
        return (sys.executable, str(FAKE_EXECUTOR), self.scenario, self.heartbeat)


class Sandbox:
    """Un origen local, un clon principal y una carpeta externa, todo temporal."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.origin = root / "origin.git"
        self.repo = root / "repo"
        self.external = root / "ext"
        self.tools = root / "tools"
        self.tools.mkdir()
        (self.tools / "pre_commit_fake.py").write_text(_FAKE_PRECOMMIT, encoding="utf-8")
        self.set_scanner("pass")

        subprocess.run(
            ["git", "init", "--quiet", "--bare", "--initial-branch=main", str(self.origin)],
            check=True,
        )
        subprocess.run(
            ["git", "init", "--quiet", "--initial-branch=main", str(self.repo)], check=True
        )
        for key, value in (
            ("user.name", "Sandbox"),
            ("user.email", "sandbox@example.invalid"),
            ("commit.gpgsign", "false"),
            ("core.autocrlf", "false"),
            ("core.safecrlf", "false"),
        ):
            _git(self.repo, "config", key, value)
        _git(self.repo, "remote", "add", "origin", str(self.origin))
        for path, content in {
            "README.md": "# repo\n",
            "docs/existing.md": "existente\n",
            "pyproject.toml": '[project]\nname = "x"\ndependencies = []\n',
            "uv.lock": "version = 1\n",
            ".gitignore": "ignored.txt\n__pycache__/\n.pytest_cache/\n",
        }.items():
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "--quiet", "-m", "chore: initial")
        _git(self.repo, "push", "--quiet", "-u", "origin", "main")
        self.write_hook(0)
        self.base = _git(self.repo, "rev-parse", "HEAD")
        self.config = RunnerConfig(
            repo_root=self.repo,
            external_root=self.external,
            expected_origin=str(self.origin),
            tool_python=Path(sys.executable),
            precommit_command=(sys.executable, str(self.tools / "pre_commit_fake.py")),
            code_gates=(Gate("ok", (sys.executable, "-c", "pass"), 60.0),),
            executor_timeout_seconds=60.0,
            kill_wait_seconds=10.0,
            extra_env={"GIT_ALLOW_PROTOCOL": "file"},
        )
        orchestrator.ensure_external_dirs(self.config)

    def write_hook(self, exit_code: int) -> None:
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8", newline="\n")
        hook.chmod(0o755)

    def set_scanner(self, mode: str) -> None:
        (self.tools / "mode.txt").write_text(mode, encoding="utf-8")

    def scanner_calls(self) -> list[str]:
        path = self.tools / "calls.log"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def write_spec(
        self,
        block: str = BLOCK,
        *,
        branch: str = BRANCH,
        allowed: str = "[docs/**, scripts/rehearsal_probe.py, pyproject.toml, uv.lock]",
        forbidden: str = "[]",
    ) -> Path:
        path = self.external / "inbox" / f"{block}.md"
        path.write_text(
            f"---\nid: {block}\ntitle: Bloque de prueba\nbase: main\nbranch: {branch}\n"
            f"allowed_paths: {allowed}\nforbidden_paths: {forbidden}\ntimeout_minutes: 1\n"
            "stop_conditions: [una]\nhuman_gates: [merge]\n---\n\n"
            "## Objetivo\n\nx\n\n## Dentro del alcance\n\nx\n\n## Fuera del alcance\n\nx\n\n"
            "## Criterios de aceptación\n\nx\n",
            encoding="utf-8",
            newline="\n",
        )
        return path

    @property
    def worktree(self) -> Path:
        return self.external / "worktrees" / "t1-1"

    def origin_refs(self) -> str:
        return _git(self.origin, "for-each-ref", "--format=%(refname) %(objectname)")

    def main_state(self) -> tuple[str, str, str, str]:
        return (
            _git(self.repo, "rev-parse", "HEAD"),
            _git(self.repo, "symbolic-ref", "HEAD"),
            _git(self.repo, "status", "--porcelain", "--untracked-files=all"),
            _git(self.repo, "rev-parse", "refs/heads/main"),
        )

    def run(self, executor: orchestrator.Executor | None = None, **changes: Any) -> RunReport:
        config = replace(self.config, **changes) if changes else self.config
        return run_block(config, BLOCK, executor=executor, confirm=lambda _spec: True)


@pytest.fixture
def sandbox(tmp_path: Path) -> Iterator[Sandbox]:
    box = Sandbox(tmp_path)
    box.write_spec()
    yield box


def _blocked(report: RunReport, reason: Reason) -> None:
    assert report.result is Result.BLOCKED, report
    assert report.reason is reason, report


# --- Recorrido correcto ---------------------------------------------------------------------


def test_no_change_run_is_verified_with_local_commits_only(sandbox: Sandbox) -> None:
    before = sandbox.main_state()
    origin_before = sandbox.origin_refs()
    report = sandbox.run()
    assert report.result is Result.VERIFIED_LOCAL
    assert report.executor_kind == "no_change"
    assert report.profile == "none"
    assert sandbox.main_state() == before
    assert sandbox.origin_refs() == origin_before
    log = _git(sandbox.worktree, "log", "--format=%s", f"{sandbox.base}..HEAD").splitlines()
    assert log == [
        f"docs(orchestration): add run evidence for {BLOCK}",
        f"docs(orchestration): add approved spec for {BLOCK}",
    ]
    assert _git(sandbox.worktree, "symbolic-ref", "HEAD") == f"refs/heads/{BRANCH}"
    assert _git(sandbox.worktree, "status", "--porcelain") == ""


def test_new_branch_tracks_nothing(sandbox: Sandbox) -> None:
    assert sandbox.run().result is Result.VERIFIED_LOCAL
    done = subprocess.run(
        ["git", "config", "--get", f"branch.{BRANCH}.remote"], cwd=sandbox.repo, capture_output=True
    )
    assert done.returncode == 1


def test_allowed_docs_edit_uses_the_docs_profile(sandbox: Sandbox) -> None:
    gate = Gate("must_not_run", (sys.executable, "-c", "raise SystemExit(1)"), 60.0)
    report = sandbox.run(FakeExecutor("edit_allowed"), code_gates=(gate,))
    assert report.result is Result.VERIFIED_LOCAL, report
    assert report.profile == "docs"
    assert [c.path for c in report.changes] == ["docs/fake-edit.md"]
    assert [g.name for g in report.gates] == ["git_diff_check"]
    assert (sandbox.worktree / "docs/fake-edit.md").exists()
    assert report.content_commit


def test_code_edit_runs_every_fixed_gate(sandbox: Sandbox) -> None:
    gates = (
        Gate("first", (sys.executable, "-c", "pass"), 60.0),
        Gate("second", (sys.executable, "-c", "pass"), 60.0),
    )
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=gates)
    assert report.result is Result.VERIFIED_LOCAL, report
    assert report.profile == "code"
    assert [g.name for g in report.gates] == ["git_diff_check", "first", "second"]


def test_deleting_an_allowed_file_is_recorded(sandbox: Sandbox) -> None:
    report = sandbox.run(FakeExecutor("delete_allowed"))
    assert report.result is Result.VERIFIED_LOCAL, report
    assert [(c.status, c.path) for c in report.changes] == [("D", "docs/existing.md")]


def test_secrets_are_scanned_three_times_over_staged_content(sandbox: Sandbox) -> None:
    assert sandbox.run(FakeExecutor("edit_allowed")).result is Result.VERIFIED_LOCAL
    calls = sandbox.scanner_calls()
    assert [call.split(" | ")[0] for call in calls] == ["run gitleaks"] * 3
    assert f"docs/orchestration/work/{BLOCK}.md" in calls[0]
    assert "docs/fake-edit.md" in calls[1]
    assert f"docs/orchestration/runs/{BLOCK}.md" in calls[2]


def test_metadata_change_in_pyproject_is_allowed(sandbox: Sandbox) -> None:
    report = sandbox.run(FakeExecutor("edit_pyproject_meta"))
    assert report.result is Result.VERIFIED_LOCAL, report


# --- Evidencia ------------------------------------------------------------------------------


def test_evidence_is_committed_and_sanitized(sandbox: Sandbox) -> None:
    report = sandbox.run(FakeExecutor("edit_allowed"))
    assert report.result is Result.VERIFIED_LOCAL
    evidence = (sandbox.worktree / f"docs/orchestration/runs/{BLOCK}.md").read_text(
        encoding="utf-8"
    )
    assert report.spec_commit in evidence
    assert report.content_commit in evidence
    assert report.spec_sha256 in evidence
    assert "`verified_local`" in evidence
    assert "docs/fake-edit.md" in evidence
    assert str(sandbox.root) not in evidence
    assert sandbox.root.as_posix() not in evidence
    assert ":\\" not in evidence


def test_blocked_run_leaves_no_evidence_in_the_branch(sandbox: Sandbox) -> None:
    report = sandbox.run(FakeExecutor("edit_out_of_scope"))
    _blocked(report, Reason.SCOPE_VIOLATION)
    assert not (sandbox.worktree / f"docs/orchestration/runs/{BLOCK}.md").exists()
    assert report.run_dir is not None
    local = (report.run_dir / "report.md").read_text(encoding="utf-8")
    assert "`scope_violation`" in local


def test_executor_output_does_not_reach_logs_with_known_secrets(sandbox: Sandbox) -> None:
    report = sandbox.run(FakeExecutor("prints_token"))
    assert report.result is Result.VERIFIED_LOCAL, report
    assert report.run_dir is not None
    token = "ghp_" + "b" * 36
    for path in report.run_dir.iterdir():
        assert token not in path.read_text(encoding="utf-8", errors="replace"), path.name
    evidence = (sandbox.worktree / f"docs/orchestration/runs/{BLOCK}.md").read_text(
        encoding="utf-8"
    )
    assert token not in evidence


def test_console_prints_no_raw_output(sandbox: Sandbox, capsys: pytest.CaptureFixture[str]) -> None:
    report = sandbox.run(FakeExecutor("prints_token"))
    orchestrator._report_outcome(report)
    assert "ghp_" not in capsys.readouterr().out


# --- Validaciones iniciales -----------------------------------------------------------------


def test_wrong_origin_is_refused(sandbox: Sandbox) -> None:
    _blocked(sandbox.run(expected_origin="https://example.invalid/x.git"), Reason.WRONG_ORIGIN)
    assert not sandbox.worktree.exists()


def test_wrong_repository_root_is_refused(sandbox: Sandbox) -> None:
    nested = sandbox.repo / "docs"
    _blocked(sandbox.run(repo_root=nested), Reason.WRONG_REPOSITORY)


def test_launch_from_a_linked_worktree_is_refused(sandbox: Sandbox, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    _git(sandbox.repo, "worktree", "add", "--quiet", "-b", "other", str(linked))
    _blocked(sandbox.run(repo_root=linked), Reason.LAUNCHED_FROM_LINKED_WORKTREE)


def test_wrong_base_branch_is_refused(sandbox: Sandbox) -> None:
    _git(sandbox.repo, "switch", "--quiet", "-c", "feature")
    _blocked(sandbox.run(), Reason.NOT_ON_BASE)


def test_dirty_working_tree_is_refused(sandbox: Sandbox) -> None:
    (sandbox.repo / "untracked.md").write_text("x", encoding="utf-8")
    _blocked(sandbox.run(), Reason.DIRTY_WORKING_TREE)
    assert not sandbox.worktree.exists()


def test_local_head_ahead_of_origin_is_refused(sandbox: Sandbox) -> None:
    _git(sandbox.repo, "commit", "--quiet", "--allow-empty", "-m", "chore: local")
    _blocked(sandbox.run(), Reason.HEAD_MISALIGNED)


def test_remote_ahead_of_local_is_refused(sandbox: Sandbox, tmp_path: Path) -> None:
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "--quiet", str(sandbox.origin), str(other)], check=True)
    _git(other, "config", "user.name", "x")
    _git(other, "config", "user.email", "x@example.invalid")
    _git(other, "commit", "--quiet", "--allow-empty", "-m", "chore: remote")
    _git(other, "push", "--quiet", "origin", "main")
    _blocked(sandbox.run(), Reason.REMOTE_MISALIGNED)


def test_unreachable_remote_is_refused(sandbox: Sandbox) -> None:
    sandbox.origin.rename(sandbox.origin.with_name("moved.git"))
    _blocked(sandbox.run(), Reason.REMOTE_UNREACHABLE)


def test_missing_hook_is_refused(sandbox: Sandbox) -> None:
    (sandbox.repo / ".git" / "hooks" / "pre-commit").unlink()
    _blocked(sandbox.run(), Reason.HOOK_MISSING)


def test_overridden_hooks_path_is_refused(sandbox: Sandbox) -> None:
    _git(sandbox.repo, "config", "core.hooksPath", "elsewhere")
    _blocked(sandbox.run(), Reason.HOOKS_PATH_OVERRIDDEN)


def test_empty_hooks_path_is_refused(sandbox: Sandbox) -> None:
    _git(sandbox.repo, "config", "core.hooksPath", "")
    _blocked(sandbox.run(), Reason.HOOKS_PATH_OVERRIDDEN)


def test_missing_spec_is_refused(sandbox: Sandbox) -> None:
    (sandbox.external / "inbox" / f"{BLOCK}.md").unlink()
    _blocked(sandbox.run(), Reason.SPEC_NOT_FOUND)


def test_invalid_spec_with_commands_is_refused_before_touching_anything(sandbox: Sandbox) -> None:
    path = sandbox.external / "inbox" / f"{BLOCK}.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("---\n\n", "commands: [x]\n---\n\n", 1),
        encoding="utf-8",
    )
    report = sandbox.run()
    _blocked(report, Reason.INVALID_SPEC)
    assert report.detail == "unknown_field"
    assert not sandbox.worktree.exists()


def test_spec_already_versioned_is_refused(sandbox: Sandbox) -> None:
    target = sandbox.repo / "docs/orchestration/work" / f"{BLOCK}.md"
    target.parent.mkdir(parents=True)
    target.write_text("x\n", encoding="utf-8")
    _blocked(sandbox.run(), Reason.SPEC_ALREADY_USED)


def test_existing_local_branch_is_refused(sandbox: Sandbox) -> None:
    _git(sandbox.repo, "branch", BRANCH)
    _blocked(sandbox.run(), Reason.BRANCH_EXISTS)
    assert not sandbox.worktree.exists()


def test_existing_remote_branch_is_refused(sandbox: Sandbox) -> None:
    _git(sandbox.origin, "branch", BRANCH, "main")
    _blocked(sandbox.run(), Reason.BRANCH_EXISTS)


def test_existing_worktree_folder_is_never_reused(sandbox: Sandbox) -> None:
    sandbox.worktree.mkdir(parents=True)
    _blocked(sandbox.run(), Reason.WORKTREE_EXISTS)
    assert _git(sandbox.repo, "branch", "--list", BRANCH) == ""


def test_external_root_inside_the_repository_is_refused(sandbox: Sandbox) -> None:
    _blocked(sandbox.run(external_root=sandbox.repo / "ext"), Reason.UNSAFE_EXTERNAL_ROOT)


def test_external_root_in_a_synced_folder_is_refused(sandbox: Sandbox, tmp_path: Path) -> None:
    _blocked(sandbox.run(external_root=tmp_path / "OneDrive" / "x"), Reason.UNSAFE_EXTERNAL_ROOT)


def test_invalid_block_id_touches_nothing(sandbox: Sandbox) -> None:
    report = run_block(sandbox.config, "../evil", confirm=lambda _s: True)
    _blocked(report, Reason.INVALID_BLOCK_ID)
    assert report.run_dir is None


def test_not_approved_creates_nothing(sandbox: Sandbox) -> None:
    seen: list[Spec] = []

    def deny(spec: Spec) -> bool:
        seen.append(spec)
        return False

    report = run_block(sandbox.config, BLOCK, confirm=deny)
    _blocked(report, Reason.NOT_APPROVED)
    assert seen[0].sha256 == report.spec_sha256
    assert not sandbox.worktree.exists()
    assert _git(sandbox.repo, "branch", "--list", BRANCH) == ""


def test_console_approval_needs_the_exact_phrase(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = orchestrator.validate_spec(sandbox.config, BLOCK)
    for answer, expected in (
        (f"APROBAR {BLOCK}", True),
        ("aprobar T1.1", False),
        ("APROBAR", False),
        ("yes", False),
        ("", False),
    ):
        monkeypatch.setattr("builtins.input", lambda _prompt, a=answer: a)
        assert orchestrator._console_confirm(spec) is expected

    def closed(_prompt: str) -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    assert orchestrator._console_confirm(spec) is False


# --- El ejecutor no se cree: se comprueba ---------------------------------------------------


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        ("edit_out_of_scope", Reason.SCOPE_VIOLATION),
        ("lies_success", Reason.SCOPE_VIOLATION),
        ("rename_out_of_scope", Reason.SCOPE_VIOLATION),
        ("edit_forbidden", Reason.FORBIDDEN_PATH),
        ("error_exit", Reason.EXECUTOR_FAILED),
        ("declares_blocked", Reason.EXECUTOR_BLOCKED),
        ("invalid_output", Reason.INVALID_EXECUTOR_OUTPUT),
        ("extra_field_output", Reason.INVALID_EXECUTOR_OUTPUT),
        ("empty_output", Reason.INVALID_EXECUTOR_OUTPUT),
        ("dirty_index", Reason.INDEX_TAMPERED),
        ("assume_unchanged", Reason.INDEX_TAMPERED),
        ("commits", Reason.HEAD_MOVED),
        ("switches_branch", Reason.HEAD_MOVED),
        ("edits_spec", Reason.SPEC_TAMPERED),
        ("moves_other_ref", Reason.REPO_INVARIANT_BROKEN),
        ("edits_shared_config", Reason.REPO_INVARIANT_BROKEN),
        ("ignored_file", Reason.IGNORED_FILE_PRESENT),
        ("embedded_repo", Reason.UNSAFE_FILE_MODE),
        ("edit_pyproject_deps", Reason.DEPENDENCY_CHANGE),
        ("edit_pyproject_tool", Reason.DEPENDENCY_CHANGE),
        ("repoints_git_file", Reason.REPO_INVARIANT_BROKEN),
        ("plants_info_attributes", Reason.REPO_INVARIANT_BROKEN),
        ("plants_post_commit_hook", Reason.REPO_INVARIANT_BROKEN),
        ("writes_binary", Reason.SECRET_SCAN_EVADED),
        ("writes_allow_marker", Reason.SECRET_SCAN_EVADED),
        ("link_in_cache", Reason.UNSAFE_FILE_MODE),
        ("edit_lock", Reason.DEPENDENCY_CHANGE),
    ],
)
def test_executor_scenarios_are_blocked(sandbox: Sandbox, scenario: str, reason: Reason) -> None:
    origin_before = sandbox.origin_refs()
    head_before = sandbox.main_state()[0]
    report = sandbox.run(FakeExecutor(scenario))
    _blocked(report, reason)
    assert sandbox.main_state()[0] == head_before
    assert sandbox.origin_refs() == origin_before
    assert report.worktree == sandbox.worktree
    assert not report.content_commit


def test_tool_cache_left_during_the_run_is_tolerated_and_not_committed(sandbox: Sandbox) -> None:
    report = sandbox.run(FakeExecutor("cache_file"))
    assert report.result is Result.VERIFIED_LOCAL, report
    assert report.changes == []
    assert ".pytest_cache" not in _git(sandbox.worktree, "ls-files")


def test_spec_level_forbidden_path_is_blocked(sandbox: Sandbox) -> None:
    sandbox.write_spec(forbidden="[docs/secret-plan.md]")
    _blocked(sandbox.run(FakeExecutor("edit_spec_forbidden")), Reason.FORBIDDEN_PATH)


def test_real_symlink_is_blocked(sandbox: Sandbox, tmp_path: Path) -> None:
    try:
        (tmp_path / "probe-link").symlink_to(tmp_path)
    except OSError:
        pytest.skip("this account cannot create symbolic links")
    _blocked(sandbox.run(FakeExecutor("symlink")), Reason.UNSAFE_FILE_MODE)


def test_oversized_file_is_blocked(sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "MAX_FILE_BYTES", 2)
    _blocked(sandbox.run(FakeExecutor("edit_allowed")), Reason.FILE_TOO_LARGE)


def test_excessive_executor_output_is_cut(sandbox: Sandbox) -> None:
    report = sandbox.run(FakeExecutor("flood_output"), max_executor_output=256 * 1024)
    _blocked(report, Reason.EXECUTOR_OUTPUT_TOO_LARGE)
    assert report.executor_duration < 30


# --- Timeout y procesos ---------------------------------------------------------------------


def _assert_stopped(heartbeat: Path, wait: float = 0.5) -> None:
    """Un latido que deja de cambiar demuestra que el proceso murió, en cualquier sistema."""
    first = heartbeat.read_text(encoding="utf-8")
    time.sleep(wait)
    assert heartbeat.read_text(encoding="utf-8") == first


def _wait_for_file(path: Path, seconds: float = 20.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size:
            return
        time.sleep(0.02)
    raise AssertionError(f"{path.name} was not written")


def test_executor_timeout_kills_the_process(sandbox: Sandbox, tmp_path: Path) -> None:
    heartbeat = tmp_path / "beat"
    report = sandbox.run(FakeExecutor("timeout_hang", str(heartbeat)), executor_timeout_seconds=3.0)
    _blocked(report, Reason.EXECUTOR_TIMEOUT)
    assert report.executor_duration < 20
    _assert_stopped(heartbeat)


def test_executor_timeout_kills_child_and_grandchild(sandbox: Sandbox, tmp_path: Path) -> None:
    heartbeat = tmp_path / "beat"
    report = sandbox.run(
        FakeExecutor("hang_with_grandchild", str(heartbeat)), executor_timeout_seconds=3.0
    )
    _blocked(report, Reason.EXECUTOR_TIMEOUT)
    _wait_for_file(heartbeat)
    _assert_stopped(heartbeat)


def test_background_process_left_by_the_executor_is_killed(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    heartbeat = tmp_path / "beat"
    report = sandbox.run(FakeExecutor("leaves_background", str(heartbeat)))
    _blocked(report, Reason.EXECUTOR_LEFT_PROCESSES)
    if heartbeat.exists():
        _assert_stopped(heartbeat)


def test_run_process_refuses_forbidden_programs(tmp_path: Path) -> None:
    with open(tmp_path / "out", "wb") as out:
        for program in ("claude", "gh", "C:\\x\\claude.exe", "/usr/bin/gh"):
            with pytest.raises(orchestrator.BlockedError) as caught:
                run_process([program], cwd=tmp_path, env={}, timeout=1.0, stdout=out)
            assert caught.value.reason is Reason.PROCESS_CONTROL_FAILED


def test_run_process_reports_a_clean_exit(tmp_path: Path) -> None:
    with open(tmp_path / "out", "wb") as out:
        result = run_process(
            [sys.executable, "-c", "print('hola')"],
            cwd=tmp_path,
            env=orchestrator.build_env(_bare_config(tmp_path)),
            timeout=30.0,
            stdout=out,
        )
    assert result.returncode == 0
    assert not result.timed_out
    assert not result.left_processes
    assert not result.orphan_suspected
    assert "hola" in (tmp_path / "out").read_text(encoding="utf-8")


def _bare_config(tmp_path: Path) -> RunnerConfig:
    return RunnerConfig(
        repo_root=tmp_path,
        external_root=tmp_path / "ext",
        expected_origin="x",
        tool_python=Path(sys.executable),
    )


_SPAWNS_AT_ONCE = textwrap.dedent(
    """
    import subprocess, sys
    code = '''
    import pathlib, sys, time
    count = 0
    while True:
        count += 1
        pathlib.Path(sys.argv[1]).write_text(str(count), encoding='utf-8')
        time.sleep(0.02)
    '''
    subprocess.Popen([sys.executable, '-c', code, sys.argv[1]])
    subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)']).wait()
    """
)


@windows_only
def test_suspended_start_leaves_no_escape_when_repeated(tmp_path: Path) -> None:
    """Cada intento lanza un nieto lo antes posible. Ninguno puede quedar fuera del job."""
    env = orchestrator.build_env(_bare_config(tmp_path))
    for attempt in range(50):
        heartbeat = tmp_path / f"beat-{attempt}"
        with open(tmp_path / "out", "wb") as out:
            result = run_process(
                [sys.executable, "-c", _SPAWNS_AT_ONCE, str(heartbeat)],
                cwd=tmp_path,
                env=env,
                timeout=1.5,
                stdout=out,
            )
        assert result.timed_out, attempt
        assert not result.orphan_suspected, attempt
        if heartbeat.exists():
            _assert_stopped(heartbeat, wait=0.1)


_RUNNER_THAT_DIES = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    import orchestrator

    child = '''
    import pathlib, subprocess, sys, time
    beat = "pathlib.Path(sys.argv[1]).write_text(str(time.time()), encoding='utf-8')"
    code = f"import pathlib, sys, time\\\\nwhile True:\\\\n    {beat}\\\\n    time.sleep(0.02)"
    subprocess.Popen([sys.executable, '-c', code, sys.argv[1]]).wait()
    '''
    with open(sys.argv[3], 'wb') as out:
        orchestrator.run_process(
            [sys.executable, '-c', child, sys.argv[2]],
            cwd=Path(sys.argv[4]),
            env=dict(__import__('os').environ),
            timeout=600.0,
            stdout=out,
        )
    """
)


@windows_only
def test_runner_death_kills_the_whole_tree(tmp_path: Path) -> None:
    """Si el runner muere sin avisar, el sistema operativo termina a sus descendientes."""
    heartbeat = tmp_path / "beat"
    runner = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _RUNNER_THAT_DIES,
            str(Path(orchestrator.__file__).parent),
            str(heartbeat),
            str(tmp_path / "out"),
            str(tmp_path),
        ]
    )
    try:
        _wait_for_file(heartbeat, 30.0)
    finally:
        # Mata también al intérprete real: en un venv de Windows, python.exe es un lanzador.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(runner.pid)], capture_output=True)
        runner.wait()
    time.sleep(1.0)
    _assert_stopped(heartbeat)


# --- Lock -----------------------------------------------------------------------------------


def test_active_lock_blocks_a_second_run(sandbox: Sandbox) -> None:
    lock = RunnerLock(sandbox.config.state / "runner.lock")
    assert lock.acquire()
    try:
        report = sandbox.run()
    finally:
        lock.release()
    _blocked(report, Reason.LOCK_BUSY)
    assert not sandbox.worktree.exists()
    assert sandbox.run().result is Result.VERIFIED_LOCAL


def test_lock_is_released_after_a_blocked_run(sandbox: Sandbox) -> None:
    _blocked(sandbox.run(FakeExecutor("error_exit")), Reason.EXECUTOR_FAILED)
    lock = RunnerLock(sandbox.config.state / "runner.lock")
    assert lock.acquire()
    lock.release()


_LOCK_HOLDER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    sys.path.insert(0, sys.argv[1])
    import orchestrator
    lock = orchestrator.RunnerLock(Path(sys.argv[2]))
    assert lock.acquire()
    Path(sys.argv[3]).write_text('held', encoding='utf-8')
    time.sleep(600)
    """
)


def test_lock_from_another_process_blocks_and_is_freed_when_it_dies(sandbox: Sandbox) -> None:
    marker = sandbox.root / "held"
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _LOCK_HOLDER,
            str(Path(orchestrator.__file__).parent),
            str(sandbox.config.state / "runner.lock"),
            str(marker),
        ]
    )
    try:
        _wait_for_file(marker, 30.0)
        _blocked(sandbox.run(), Reason.LOCK_BUSY)
    finally:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(holder.pid)], capture_output=True)
        else:
            holder.kill()
        holder.wait()
    time.sleep(0.5)
    lock = RunnerLock(sandbox.config.state / "runner.lock")
    assert lock.acquire()
    lock.release()


def test_interruption_is_reported_and_releases_the_lock(sandbox: Sandbox) -> None:
    def interrupted(_spec: Spec) -> bool:
        raise KeyboardInterrupt

    report = run_block(sandbox.config, BLOCK, confirm=interrupted)
    _blocked(report, Reason.INTERRUPTED)
    lock = RunnerLock(sandbox.config.state / "runner.lock")
    assert lock.acquire()
    lock.release()


def test_unexpected_error_is_reported_without_a_traceback_on_the_report(sandbox: Sandbox) -> None:
    def broken(_spec: Spec) -> bool:
        raise ValueError("internal detail")

    report = run_block(sandbox.config, BLOCK, confirm=broken)
    _blocked(report, Reason.INTERNAL_ERROR)
    assert report.run_dir is not None
    assert "internal detail" not in (report.run_dir / "report.md").read_text(encoding="utf-8")
    assert "internal detail" in (report.run_dir / "internal.log").read_text(encoding="utf-8")


# --- Secretos -------------------------------------------------------------------------------


def test_token_written_by_the_executor_is_detected_and_not_committed(
    sandbox: Sandbox, tmp_path: Path
) -> None:
    token_file = tmp_path / "token"
    report = sandbox.run(FakeExecutor("writes_token", str(token_file)))
    _blocked(report, Reason.SECRET_DETECTED)
    assert not report.content_commit
    token = token_file.read_text(encoding="utf-8")
    assert report.run_dir is not None
    for path in report.run_dir.iterdir():
        assert token not in path.read_text(encoding="utf-8", errors="replace"), path.name
    log = _git(sandbox.worktree, "log", "--all", "-p", "--format=%H")
    assert token not in log


def test_secret_in_the_specification_stops_before_the_executor(sandbox: Sandbox) -> None:
    sandbox.set_scanner("leak")
    report = sandbox.run(FakeExecutor("edit_allowed"))
    _blocked(report, Reason.SECRET_DETECTED)
    assert report.detail == "specification"
    assert not report.spec_commit
    assert not (sandbox.worktree / "docs/fake-edit.md").exists()


def test_skipped_scan_is_a_failure(sandbox: Sandbox) -> None:
    sandbox.set_scanner("skip")
    report = sandbox.run()
    _blocked(report, Reason.SECRET_SCAN_SKIPPED)
    assert report.secret_scans == [("specification", "omitido")]


def test_secret_in_the_title_does_not_reach_the_local_report_or_the_screen(
    sandbox: Sandbox, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    token = "ghp_" + "c" * 36
    path = sandbox.external / "inbox" / f"{BLOCK}.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("Bloque de prueba", f"token {token}"),
        encoding="utf-8",
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: f"APROBAR {BLOCK}")
    report = run_block(sandbox.config, BLOCK)
    _blocked(report, Reason.SECRET_DETECTED)
    assert report.run_dir is not None
    assert token not in (report.run_dir / "report.md").read_text(encoding="utf-8")
    assert token not in capsys.readouterr().out


def test_broken_scanner_is_a_failure(sandbox: Sandbox) -> None:
    sandbox.set_scanner("error")
    _blocked(sandbox.run(), Reason.SECRET_SCAN_FAILED)


def test_failing_commit_hook_stops_the_run(sandbox: Sandbox) -> None:
    sandbox.write_hook(1)
    report = sandbox.run()
    _blocked(report, Reason.COMMIT_FAILED)
    assert not report.spec_commit


# --- Controles de calidad -------------------------------------------------------------------


def test_failing_gate_blocks_and_stops_the_following_ones(sandbox: Sandbox) -> None:
    gates = (
        Gate("fails", (sys.executable, "-c", "raise SystemExit(1)"), 60.0),
        Gate("never", (sys.executable, "-c", "pass"), 60.0),
    )
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=gates)
    _blocked(report, Reason.QUALITY_GATE_FAILED)
    assert report.detail == "fails"
    assert [g.name for g in report.gates] == ["git_diff_check", "fails"]
    assert not report.content_commit


def test_hanging_gate_times_out(sandbox: Sandbox) -> None:
    gates = (Gate("hangs", (sys.executable, "-c", "import time; time.sleep(600)"), 1.0),)
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=gates)
    _blocked(report, Reason.QUALITY_GATE_TIMEOUT)


def test_gate_that_modifies_a_file_blocks(sandbox: Sandbox) -> None:
    code = "open('docs/existing.md', 'a').write('modificado')"
    gates = (Gate("modifies", (sys.executable, "-c", code), 60.0),)
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=gates)
    _blocked(report, Reason.GATE_MODIFIED_TREE)


def test_gate_that_creates_a_file_blocks(sandbox: Sandbox) -> None:
    code = "open('docs/created.md', 'w').write('x')"
    gates = (Gate("creates", (sys.executable, "-c", code), 60.0),)
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=gates)
    _blocked(report, Reason.GATE_MODIFIED_TREE)


def test_gate_that_creates_an_ignored_file_blocks(sandbox: Sandbox) -> None:
    code = "open('ignored.txt', 'w').write('x')"
    gates = (Gate("hides", (sys.executable, "-c", code), 60.0),)
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=gates)
    _blocked(report, Reason.GATE_MODIFIED_TREE)


def test_gate_caches_are_tolerated(sandbox: Sandbox) -> None:
    code = "import os; os.makedirs('.pytest_cache'); open('.pytest_cache/x', 'w').write('x')"
    gates = (Gate("cache", (sys.executable, "-c", code), 60.0),)
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=gates)
    assert report.result is Result.VERIFIED_LOCAL, report


def test_gates_receive_the_copy_source_and_a_filtered_environment(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "no-debe-llegar")
    code = (
        "import os, sys; "
        "expected = os.path.join(os.getcwd(), 'src'); "
        "ok = os.environ['PYTHONPATH'] == expected and 'GITHUB_TOKEN' not in os.environ; "
        "sys.exit(0 if ok else 1)"
    )
    gates = (Gate("environment", (sys.executable, "-c", code), 60.0),)
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=gates)
    assert report.result is Result.VERIFIED_LOCAL, report


def _pytest_like_gate(omitted: int, printed: str) -> Gate:
    known = tuple(orchestrator.WINDOWS_KNOWN_TEST_FAILURES)[:omitted]
    return Gate("pytest", (sys.executable, "-c", f"print({printed!r})"), 60.0, known)


def test_omission_count_must_be_exact(sandbox: Sandbox) -> None:
    gate = _pytest_like_gate(2, "10 passed, 3 deselected in 1.00s")
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=(gate,))
    _blocked(report, Reason.QUALITY_GATE_FAILED)
    assert report.detail == "omission_count"


def test_matching_omission_count_passes(sandbox: Sandbox) -> None:
    gate = _pytest_like_gate(2, "10 passed, 2 deselected in 1.00s")
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=(gate,))
    assert report.result is Result.VERIFIED_LOCAL, report


def test_any_other_failure_still_blocks_when_tests_are_omitted(sandbox: Sandbox) -> None:
    """Una cuarta falla distinta debe detener el bloque, igual que cualquier otra."""
    known = next(iter(orchestrator.WINDOWS_KNOWN_TEST_FAILURES))
    gate = Gate("pytest", (sys.executable, "-c", "raise SystemExit(1)"), 60.0, (known,))
    report = sandbox.run(FakeExecutor("edit_allowed_code"), code_gates=(gate,))
    _blocked(report, Reason.QUALITY_GATE_FAILED)
    assert report.omitted_tests == (known,)


def test_default_gates_are_fixed_and_check_the_package_origin(sandbox: Sandbox) -> None:
    config = replace(sandbox.config, code_gates=None)
    gates = config.gates()
    assert [g.name for g in gates] == [
        "package_origin",
        "ruff_check",
        "ruff_format",
        "mypy",
        "pytest",
    ]
    assert all(g.argv[0] == sys.executable for g in gates)


# --- Solo lectura y ningún camino a publicar --------------------------------------------------


def test_validate_changes_nothing_in_the_repository(sandbox: Sandbox) -> None:
    before = sandbox.main_state()
    refs_before = _git(sandbox.repo, "for-each-ref")
    worktrees_before = _git(sandbox.repo, "worktree", "list", "--porcelain")
    origin_before = sandbox.origin_refs()
    report = validate_block(sandbox.config, BLOCK)
    assert report.result is Result.VALIDATED, report
    assert sandbox.main_state() == before
    assert _git(sandbox.repo, "for-each-ref") == refs_before
    assert _git(sandbox.repo, "worktree", "list", "--porcelain") == worktrees_before
    assert sandbox.origin_refs() == origin_before
    assert not sandbox.worktree.exists()
    assert sandbox.scanner_calls() == []


def test_validate_reports_problems_without_changing_anything(sandbox: Sandbox) -> None:
    (sandbox.repo / "untracked.md").write_text("x", encoding="utf-8")
    _blocked(validate_block(sandbox.config, BLOCK), Reason.DIRTY_WORKING_TREE)


@pytest.mark.parametrize("scenario", ["edit_allowed", "edit_allowed_code", "edit_out_of_scope"])
def test_no_forbidden_command_is_ever_launched(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    calls: list[tuple[str, ...]] = []
    real = orchestrator.run_process

    def spy(argv: Sequence[str], **kwargs: Any) -> orchestrator.ProcessResult:
        calls.append(tuple(str(a) for a in argv))
        return real(argv, **kwargs)

    monkeypatch.setattr(orchestrator, "run_process", spy)
    origin_before = sandbox.origin_refs()
    sandbox.run(FakeExecutor(scenario))
    assert calls
    assert sandbox.origin_refs() == origin_before
    forbidden_sub = {"push", "merge", "rebase", "pull", "fetch", "reset", "clean", "prune"}
    forbidden_arg = {"--force", "-f", "-D", "--hard", "--no-verify", "--amend"}
    for call in calls:
        program = Path(call[0]).stem.lower()
        assert program in {"git", Path(sys.executable).stem.lower()}, call
        if program == "git":
            assert call[1] not in forbidden_sub, call
            assert not set(call) & forbidden_arg, call
            assert "prune" not in call, call


def test_other_worktrees_are_left_intact(sandbox: Sandbox, tmp_path: Path) -> None:
    other = tmp_path / "A"
    _git(sandbox.repo, "worktree", "add", "--quiet", "--detach", str(other), "HEAD")
    (other / "local-work.md").write_text("trabajo ajeno", encoding="utf-8")
    before = _git(other, "status", "--porcelain")
    assert sandbox.run(FakeExecutor("edit_allowed")).result is Result.VERIFIED_LOCAL
    assert cleanup_block(sandbox.config, BLOCK).removed_worktree
    assert _git(other, "status", "--porcelain") == before
    assert (other / "local-work.md").exists()
    assert str(other.resolve().as_posix()) in _git(sandbox.repo, "worktree", "list", "--porcelain")


# --- Limpieza segura --------------------------------------------------------------------------


def test_cleanup_removes_the_copy_and_keeps_an_unmerged_branch(sandbox: Sandbox) -> None:
    assert sandbox.run().result is Result.VERIFIED_LOCAL
    result = cleanup_block(sandbox.config, BLOCK)
    assert result.reason is None
    assert result.removed_worktree
    assert not result.removed_branch
    assert not sandbox.worktree.exists()
    assert _git(sandbox.repo, "branch", "--list", BRANCH).strip() == BRANCH


def test_cleanup_removes_a_branch_that_git_confirms_is_merged(sandbox: Sandbox) -> None:
    assert sandbox.run().result is Result.VERIFIED_LOCAL
    _git(sandbox.repo, "merge", "--quiet", "--ff-only", BRANCH)
    result = cleanup_block(sandbox.config, BLOCK)
    assert result.removed_worktree
    assert result.removed_branch
    assert _git(sandbox.repo, "branch", "--list", BRANCH) == ""


def test_cleanup_refuses_a_copy_with_pending_changes(sandbox: Sandbox) -> None:
    _blocked(sandbox.run(FakeExecutor("edit_out_of_scope")), Reason.SCOPE_VIOLATION)
    result = cleanup_block(sandbox.config, BLOCK)
    assert result.reason is Reason.CLEANUP_REFUSED
    assert not result.removed_worktree
    assert (sandbox.worktree / "other/out-of-scope.md").exists()


def test_cleanup_never_touches_an_unregistered_folder(sandbox: Sandbox) -> None:
    sandbox.worktree.mkdir(parents=True)
    (sandbox.worktree / "keep.txt").write_text("x", encoding="utf-8")
    result = cleanup_block(sandbox.config, BLOCK)
    assert result.reason is Reason.NOTHING_TO_CLEAN
    assert result.residual_directory
    assert (sandbox.worktree / "keep.txt").exists()


def test_cleanup_refuses_a_copy_with_a_link_and_keeps_its_target(sandbox: Sandbox) -> None:
    _blocked(sandbox.run(FakeExecutor("link_in_cache")), Reason.UNSAFE_FILE_MODE)
    result = cleanup_block(sandbox.config, BLOCK)
    assert result.reason is Reason.CLEANUP_REFUSED
    assert (sandbox.worktree / "docs/existing.md").exists()


def test_cleanup_reports_a_git_failure_without_a_traceback(sandbox: Sandbox) -> None:
    config = replace(sandbox.config, repo_root=sandbox.root / "does-not-exist")
    assert cleanup_block(config, BLOCK).reason is Reason.PROCESS_CONTROL_FAILED


def test_cleanup_with_a_held_lock_is_refused(sandbox: Sandbox) -> None:
    lock = RunnerLock(sandbox.config.state / "runner.lock")
    assert lock.acquire()
    try:
        assert cleanup_block(sandbox.config, BLOCK).reason is Reason.LOCK_BUSY
    finally:
        lock.release()


def test_status_lists_registered_and_unregistered_folders(sandbox: Sandbox) -> None:
    assert sandbox.run().result is Result.VERIFIED_LOCAL
    (sandbox.external / "worktrees" / "leftover").mkdir()
    statuses = {s.name: s for s in status_worktrees(sandbox.config)}
    assert statuses["t1-1"].registered
    assert statuses["t1-1"].branch == BRANCH
    assert not statuses["leftover"].registered


def test_a_blocked_id_cannot_be_rerun_until_cleaned(sandbox: Sandbox) -> None:
    _blocked(sandbox.run(FakeExecutor("error_exit")), Reason.EXECUTOR_FAILED)
    _blocked(sandbox.run(), Reason.BRANCH_EXISTS)
