"""Parte A de la prueba real de O1.2: el runner, de verdad, en un repositorio desechable.

Se omite salvo en Windows y con ``ELSA_O1_REHEARSAL=1``. A diferencia de la
integración, aquí son reales Git, pre-commit, gitleaks, ruff, mypy y pytest. Lo
único falso es el ejecutor. La copia y su origen viven en la carpeta temporal de
pytest: no se usa la red, no se publica nada y el repositorio real debe quedar
idéntico, cosa que el propio test comprueba.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import orchestrator
import pytest
import yaml
from orchestrator import Reason, Result, RunnerConfig, run_block

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("ELSA_O1_REHEARSAL") != "1",
    reason="manual rehearsal: needs Windows and ELSA_O1_REHEARSAL=1",
)

FAKE_EXECUTOR = Path(__file__).resolve().parent / "fake_orchestrator_executor.py"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return done.stdout.strip()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"


def _real_repository() -> Path:
    here = Path(__file__).resolve().parent
    return Path(_git(here, "rev-parse", "--path-format=absolute", "--git-common-dir")).parent


def _real_snapshot(repo: Path) -> dict[str, str]:
    """Todo lo que el ensayo no debe tocar del repositorio real, incluido GitHub."""
    return {
        "head": _git(repo, "rev-parse", "HEAD"),
        "head_ref": _git(repo, "symbolic-ref", "HEAD"),
        "status": _git(repo, "status", "--porcelain", "--untracked-files=all"),
        "refs": _git(repo, "for-each-ref", "--format=%(refname) %(objectname)"),
        "worktrees": _git(repo, "worktree", "list", "--porcelain"),
        "config": _file_sha(repo / ".git" / "config"),
        "hook": _file_sha(repo / ".git" / "hooks" / "pre-commit"),
        "remote": _git(repo, "ls-remote", "origin"),
    }


def _assert_hooks_are_cached(repo: Path) -> None:
    """Sin descargas: si la caché no tiene los hooks, el ensayo falla aquí."""
    config = yaml.safe_load((repo / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    database = Path.home() / ".cache" / "pre-commit" / "db.db"
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        cached = {(r, v) for r, v in connection.execute("select repo, ref from repos")}
    finally:
        connection.close()
    for entry in config["repos"]:
        assert (entry["repo"], entry["rev"]) in cached, "pre-commit hook is not cached"


@dataclass(frozen=True)
class FakeExecutor:
    scenario: str
    heartbeat: str = ""
    kind: str = "fake"

    def command(self, worktree: Path, spec_path: str) -> tuple[str, ...] | None:
        return (sys.executable, str(FAKE_EXECUTOR), self.scenario, self.heartbeat)


def _write_spec(config: RunnerConfig, block: str) -> None:
    slug = orchestrator.block_slug(block)
    (config.inbox / f"{block}.md").write_text(
        f"---\nid: {block}\ntitle: Ensayo del runner\nbase: main\nbranch: claude/{slug}-rehearsal\n"
        "allowed_paths: [docs/fake-edit.md, scripts/rehearsal_probe.py]\nforbidden_paths: []\n"
        "timeout_minutes: 5\nstop_conditions: [una]\nhuman_gates: [merge]\n---\n\n"
        "## Objetivo\n\nEnsayo.\n\n## Dentro del alcance\n\nEnsayo.\n\n"
        "## Fuera del alcance\n\nTodo lo demás.\n\n## Criterios de aceptación\n\nEnsayo.\n",
        encoding="utf-8",
        newline="\n",
    )


@pytest.fixture(scope="module")
def disposable(tmp_path_factory: pytest.TempPathFactory) -> RunnerConfig:
    real = _real_repository()
    _assert_hooks_are_cached(real)
    root = tmp_path_factory.mktemp("o1-rehearsal")
    origin = root / "origin.git"
    work = root / "work"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", "--no-hardlinks", str(real), str(origin)], check=True
    )
    subprocess.run(["git", "clone", "--quiet", str(origin), str(work)], check=True)
    _git(work, "config", "user.name", "ELSA rehearsal")
    _git(work, "config", "user.email", "rehearsal@example.invalid")
    # El hook solo se instala en esta copia, con los hooks que ya están en la caché.
    subprocess.run([sys.executable, "-m", "pre_commit", "install"], cwd=work, check=True)
    config = RunnerConfig(
        repo_root=work,
        external_root=root / "ext",
        expected_origin=_git(work, "remote", "get-url", "origin"),
        tool_python=Path(sys.executable),
    )
    orchestrator.ensure_external_dirs(config)
    return config


@pytest.fixture(scope="module")
def real_before() -> dict[str, str]:
    return _real_snapshot(_real_repository())


def test_part_a_no_change(disposable: RunnerConfig, real_before: dict[str, str]) -> None:
    _write_spec(disposable, "T9.1")
    origin_before = _git(disposable.repo_root, "ls-remote", "origin")
    report = run_block(disposable, "T9.1", confirm=lambda _spec: True)
    assert report.result is Result.VERIFIED_LOCAL, report
    assert report.profile == "none"
    assert [stage for stage, _ in report.secret_scans] == ["specification", "evidence"]
    assert _git(disposable.repo_root, "ls-remote", "origin") == origin_before


def test_part_a_allowed_edit_with_real_gates(
    disposable: RunnerConfig, real_before: dict[str, str]
) -> None:
    _write_spec(disposable, "T9.2")
    report = run_block(
        disposable, "T9.2", executor=FakeExecutor("edit_allowed_code"), confirm=lambda _spec: True
    )
    assert report.result is Result.VERIFIED_LOCAL, report
    assert report.profile == "code"
    names = [gate.name for gate in report.gates]
    assert names == [
        "git_diff_check",
        "package_origin",
        "ruff_check",
        "ruff_format",
        "mypy",
        "pytest",
    ]
    assert all(gate.returncode == 0 for gate in report.gates)
    assert set(report.omitted_tests) == set(orchestrator.WINDOWS_KNOWN_TEST_FAILURES)
    print()
    for gate in report.gates:
        print(f"gate {gate.name}: exit={gate.returncode} {gate.duration:.1f}s {gate.summary}")


def test_part_a_fake_token_is_detected_by_real_gitleaks(
    disposable: RunnerConfig, real_before: dict[str, str], tmp_path: Path
) -> None:
    _write_spec(disposable, "T9.3")
    token_file = tmp_path / "token"
    report = run_block(
        disposable,
        "T9.3",
        executor=FakeExecutor("writes_token", str(token_file)),
        confirm=lambda _spec: True,
    )
    assert report.result is Result.BLOCKED
    assert report.reason is Reason.SECRET_DETECTED, report
    assert not report.content_commit
    token = token_file.read_text(encoding="utf-8")
    assert report.run_dir is not None
    for path in report.run_dir.iterdir():
        assert token not in path.read_text(encoding="utf-8", errors="replace"), path.name
    assert report.worktree is not None
    assert token not in _git(report.worktree, "log", "--all", "-p", "--format=%H")


def test_part_a_real_repository_is_identical(
    disposable: RunnerConfig, real_before: dict[str, str]
) -> None:
    """Va al final del archivo a propósito: compara con la foto del principio."""
    assert _real_snapshot(_real_repository()) == real_before
