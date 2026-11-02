"""El contrato del runner: lo que se puede fijar sin lanzar ningún proceso.

La integración con Git real y el ejecutor falso están en
``test_orchestrator_integration.py``.
"""

from __future__ import annotations

import ast
import inspect
import os
import sys
from pathlib import Path
from typing import IO

import orchestrator
import pytest
from orchestrator import (
    ALWAYS_FORBIDDEN,
    BlockedError,
    Change,
    GateRecord,
    Reason,
    Result,
    RunnerConfig,
    RunReport,
    Spec,
    check_scope,
    gate_profile,
    is_unsafe_path,
    matches_any,
    parse_executor_output,
    parse_spec,
    render_evidence,
    scrub_text,
    validate_block_id,
    validate_branch_name,
    validate_evidence_text,
    validate_git_args,
    validate_path_pattern,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "orchestrator.py"
WRAPPER_PATH = REPO_ROOT / "scripts" / "Start-ElsaBlock.ps1"
TEMPLATE_PATH = REPO_ROOT / "docs" / "orchestration" / "SPEC_TEMPLATE.md"

# Se construye por partes para que el escáner no lo tome por un secreto real.
FAKE_TOKEN = "ghp_" + "a1B2c3D4" * 4 + "e5F6"


def _spec_text(**overrides: object) -> str:
    fields: dict[str, object] = {
        "id": "T1.1",
        "title": "Prueba",
        "base": "main",
        "branch": "claude/t1-1-prueba",
        "allowed_paths": "[docs/**]",
        "forbidden_paths": "[]",
        "timeout_minutes": 5,
        "stop_conditions": "[una condicion]",
        "human_gates": "[hacer el merge]",
    }
    fields.update(overrides)
    head = "\n".join(f"{key}: {value}" for key, value in fields.items() if value is not None)
    return (
        f"---\n{head}\n---\n\n# Título\n\n## Objetivo\n\nx\n\n## Dentro del alcance\n\nx\n\n"
        "## Fuera del alcance\n\nx\n\n## Criterios de aceptación\n\nx\n"
    )


def _parse(**overrides: object) -> Spec:
    return parse_spec(_spec_text(**overrides).encode("utf-8"), "T1.1")


def _assert_blocked(reason: Reason, detail: str | None = None):
    class _Check:
        def __enter__(self) -> None:
            return None

        def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
            assert isinstance(exc, BlockedError), f"expected BlockedError, got {exc!r}"
            assert exc.reason is reason
            if detail is not None:
                assert exc.detail == detail
            return True

    return _Check()


# --- Especificación -------------------------------------------------------------------------


def test_valid_spec_is_parsed() -> None:
    spec = _parse()
    assert spec.id == "T1.1"
    assert spec.branch == "claude/t1-1-prueba"
    assert spec.allowed_paths == ("docs/**",)
    assert len(spec.sha256) == 64


def test_versioned_template_satisfies_the_contract() -> None:
    assert parse_spec(TEMPLATE_PATH.read_bytes(), "O0.0").id == "O0.0"


@pytest.mark.parametrize(
    "field_name", ["commands", "command", "run", "script", "hooks", "executor", "env", "shell"]
)
def test_spec_cannot_declare_commands(field_name: str) -> None:
    with _assert_blocked(Reason.INVALID_SPEC, "unknown_field"):
        _parse(**{field_name: "[rm -rf x]"})


@pytest.mark.parametrize("missing", sorted(orchestrator.SPEC_FIELDS))
def test_every_field_is_required(missing: str) -> None:
    with pytest.raises(BlockedError) as caught:
        _parse(**{missing: None})
    assert caught.value.reason is Reason.INVALID_SPEC


@pytest.mark.parametrize(
    ("raw", "detail"),
    [
        (b"sin cabecera\n", "front_matter"),
        (b"---\nid: T1.1\n", "front_matter"),
        (b"---\n- lista\n---\n", "front_matter"),
        (b"---\nid: [\n---\n", "yaml"),
        (b"---\nid: T1.1\nid: T1.1\n---\n", "yaml"),
        (b"---\nid: !!python/object/apply:os.system [x]\n---\n", "yaml"),
        (b"\xff\xfe no utf8", "encoding"),
        (b"nul\0byte", "size_or_binary"),
    ],
)
def test_malformed_spec_is_rejected(raw: bytes, detail: str) -> None:
    with _assert_blocked(Reason.INVALID_SPEC, detail):
        parse_spec(raw, "T1.1")


def test_oversized_spec_is_rejected() -> None:
    with _assert_blocked(Reason.INVALID_SPEC, "size_or_binary"):
        parse_spec(b"x" * (orchestrator.MAX_SPEC_BYTES + 1), "T1.1")


def test_spec_tolerates_bom_and_crlf() -> None:
    raw = b"\xef\xbb\xbf" + _spec_text().replace("\n", "\r\n").encode("utf-8")
    assert parse_spec(raw, "T1.1").id == "T1.1"


def test_id_must_match_file_name() -> None:
    with _assert_blocked(Reason.INVALID_SPEC, "id_mismatch"):
        parse_spec(_spec_text().encode("utf-8"), "T9.9")


def test_missing_section_is_rejected() -> None:
    text = _spec_text().replace("## Objetivo", "## Otra cosa")
    with _assert_blocked(Reason.INVALID_SPEC, "missing_section"):
        parse_spec(text.encode("utf-8"), "T1.1")


@pytest.mark.parametrize("value", [0, 121, -1, "true", '"5"', 1.5])
def test_timeout_must_be_a_bounded_integer(value: object) -> None:
    with _assert_blocked(Reason.INVALID_SPEC, "timeout_minutes"):
        _parse(timeout_minutes=value)


@pytest.mark.parametrize("base", ["master", "develop", "origin/main", "refs/heads/main"])
def test_only_main_is_accepted_as_base(base: str) -> None:
    with _assert_blocked(Reason.NOT_ON_BASE):
        _parse(base=base)


@pytest.mark.parametrize(
    "pattern",
    [".claude/**", "CLAUDE.md", "supabase/x.sql", "render.yaml", ".env", "src/.env.local"],
)
def test_spec_cannot_allow_an_always_forbidden_path(pattern: str) -> None:
    with _assert_blocked(Reason.INVALID_SPEC, "allowed_path_always_forbidden"):
        _parse(allowed_paths=f"['{pattern}']")


@pytest.mark.parametrize(
    "text",
    [
        '"con \\e[1A escape"',
        '"con \\r retorno"',
        '"con \\u202e bidi"',
        '"con \\x85 c1"',
        '"con \\n salto"',
        "x" * 301,
    ],
)
def test_free_text_rejects_control_characters(text: str) -> None:
    for field_name, value in (
        ("title", text),
        ("stop_conditions", f"[{text}]"),
        ("human_gates", f"[{text}]"),
    ):
        with pytest.raises(BlockedError) as caught:
            _parse(**{field_name: value})
        assert caught.value.reason is Reason.INVALID_SPEC


def test_allowed_paths_cannot_be_empty() -> None:
    with _assert_blocked(Reason.INVALID_SPEC, "allowed_paths"):
        _parse(allowed_paths="[]")


# --- Identificador y rama -------------------------------------------------------------------


@pytest.mark.parametrize("block_id", ["O1.2", "T0.1", "D2.7", "B5.0.m1"])
def test_valid_block_ids(block_id: str) -> None:
    assert validate_block_id(block_id) == block_id


@pytest.mark.parametrize(
    "block_id", ["", "o1.2", "../x", "O1/2", "O1\\2", "O1..2", "CON", "NUL.1", "O" * 25, 1.2, None]
)
def test_invalid_block_ids(block_id: object) -> None:
    with _assert_blocked(Reason.INVALID_BLOCK_ID):
        validate_block_id(block_id)


@pytest.mark.parametrize("branch", ["claude/o1-2", "claude/o1-2-runner", "claude/o1-2-a-b-3"])
def test_valid_branches(branch: str) -> None:
    assert validate_branch_name(branch, "O1.2") == branch


@pytest.mark.parametrize(
    "branch",
    [
        "main",
        "master",
        "origin/main",
        "refs/heads/main",
        "HEAD",
        "claude/main",
        "claude/o1-3",
        "claude/o1-2/../main",
        "claude/o1-2..x",
        "claude/o1-2@{0}",
        "claude/O1-2",
        "claude/o1-2-",
        "-claude/o1-2",
        "feat/o1-2",
        "",
        None,
    ],
)
def test_invalid_branches(branch: object) -> None:
    with _assert_blocked(Reason.INVALID_BRANCH):
        validate_branch_name(branch, "O1.2")


# --- Rutas ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "pattern", ["*", "**", "**/*", "*/**", "/abs", "a/", "a//b", "../x", "a/../b", "a\\b", "C:/x"]
)
def test_invalid_path_patterns(pattern: str) -> None:
    with pytest.raises(BlockedError) as caught:
        validate_path_pattern(pattern)
    assert caught.value.reason is Reason.INVALID_SPEC


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("docs/a.md", "docs/**", True),
        ("docs/x/y/a.md", "docs/**", True),
        ("docsy/a.md", "docs/**", False),
        ("docs/a.md", "docs/*.md", True),
        ("docs/x/a.md", "docs/*.md", False),
        ("x/.env", "**/.env*", True),
        (".env.local", "**/.env*", True),
        ("x/y/.gitignore", "**/.gitignore", True),
        ("DOCS/A.MD", "docs/**", True),
        ("CLAUDE.md", "claude.md", True),
    ],
)
def test_glob_matching(path: str, pattern: str, expected: bool) -> None:
    assert matches_any(path, (pattern,)) is expected


@pytest.mark.parametrize(
    "path",
    [
        "a:b.md",
        "file.md:stream",
        "CLAUDE~1.MD",
        "docs/a.md.",
        "docs/a.md ",
        "docs\\a.md",
        "/abs.md",
        ".git/config",
        "x/.GIT/config",
        "../x",
        "a/./b",
        "con.md",
        "x/NUL",
        "a\x01b",
        "cafe\u0301.md",
        "bad\udc80.md",
        "a`b.md",
        "a\x7fb.md",
        "a\x85b.md",
        "a\u202eb.md",
        "",
    ],
)
def test_unsafe_paths(path: str) -> None:
    assert is_unsafe_path(path)


@pytest.mark.parametrize("path", ["docs/a.md", "src/.hidden/x.py", "café.md", "a-b_c.d.txt"])
def test_safe_paths(path: str) -> None:
    assert not is_unsafe_path(path)


def _scoped(*allowed: str, forbidden: tuple[str, ...] = ()) -> Spec:
    return Spec(
        id="T1.1",
        title="x",
        base="main",
        branch="claude/t1-1",
        allowed_paths=allowed,
        forbidden_paths=forbidden,
        timeout_minutes=1,
        stop_conditions=(),
        human_gates=(),
        raw=b"",
        sha256="0" * 64,
    )


def test_scope_accepts_allowed_paths() -> None:
    check_scope([Change("docs/a.md", "M", "100644")], _scoped("docs/**"))


def test_scope_rejects_anything_not_allowed() -> None:
    with _assert_blocked(Reason.SCOPE_VIOLATION):
        check_scope([Change("other/a.md", "A")], _scoped("docs/**"))


def test_forbidden_wins_over_allowed() -> None:
    with _assert_blocked(Reason.FORBIDDEN_PATH):
        check_scope([Change("docs/x.md", "M")], _scoped("docs/**", forbidden=("docs/x.md",)))


@pytest.mark.parametrize(
    "path",
    [
        "supabase/migrations/0001.sql",
        "render.yaml",
        ".github/workflows/ci.yml",
        ".env",
        "docs/.env.production",
        ".claude/settings.json",
        "CLAUDE.md",
        ".gitignore",
        "docs/.gitignore",
        ".gitattributes",
        ".pre-commit-config.yaml",
        ".gitleaks.toml",
        ".gitmodules",
        ".mcp.json",
        ".python-version",
        "uv.toml",
        "ruff.toml",
        "src/.ruff.toml",
        "pytest.ini",
        "docs/tox.ini",
        "setup.cfg",
        "mypy.ini",
        "tests/conftest.py",
        "docs/CLAUDE.md",
        "docs/.claude/x.md",
        "scripts/orchestrator.py",
        "scripts/Start-ElsaBlock.ps1",
        "tests/test_orchestrator.py",
        "tests/fake_claude.py",
        "docs/adr/0001-x.md",
        ".credentials.json",
        "docs/.credentials.json",
        "docs/orchestration/work/T1.1.md",
        "docs/orchestration/runs/T1.1.md",
    ],
)
def test_always_forbidden_paths_cannot_be_changed(path: str) -> None:
    with _assert_blocked(Reason.FORBIDDEN_PATH):
        check_scope([Change(path, "M")], _scoped("docs/**", "**/*.md"))
    assert matches_any(path, ALWAYS_FORBIDDEN)


def test_a_deletion_counts_like_any_other_change() -> None:
    with _assert_blocked(Reason.SCOPE_VIOLATION):
        check_scope([Change("other/a.md", "D", "000000")], _scoped("docs/**"))


def test_declare_only_paths_need_their_exact_name() -> None:
    with _assert_blocked(Reason.SCOPE_VIOLATION):
        check_scope([Change("pyproject.toml", "M")], _scoped("*.toml"))
    check_scope([Change("pyproject.toml", "M")], _scoped("pyproject.toml"))


@pytest.mark.parametrize("mode", ["120000", "160000"])
def test_symlinks_and_submodules_are_rejected(mode: str) -> None:
    with _assert_blocked(Reason.UNSAFE_FILE_MODE):
        check_scope([Change("docs/a", "A", mode)], _scoped("docs/**"))


def test_embedded_repository_is_rejected() -> None:
    with _assert_blocked(Reason.UNSAFE_FILE_MODE):
        check_scope([Change("docs/nested/", "A")], _scoped("docs/**"))


def test_too_many_changes_are_rejected() -> None:
    changes = [Change(f"docs/{n}.md", "A") for n in range(orchestrator.MAX_CHANGED_FILES + 1)]
    with _assert_blocked(Reason.TOO_MANY_CHANGES):
        check_scope(changes, _scoped("docs/**"))


@pytest.mark.parametrize(
    ("paths", "profile"),
    [
        ([], "none"),
        (["docs/a.md", "README.md"], "docs"),
        (["docs/a.txt"], "code"),
        (["src/a.py"], "code"),
        (["docs/a.md", "src/a.py"], "code"),
        (["other.md"], "code"),
    ],
)
def test_gate_profile_comes_from_the_real_diff(paths: list[str], profile: str) -> None:
    assert gate_profile([Change(path, "M") for path in paths]) == profile


# --- Git: lista cerrada ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ("push", "origin", "main"),
        ("push",),
        ("merge", "x"),
        ("rebase", "main"),
        ("pull",),
        ("fetch",),
        ("reset", "--hard"),
        ("clean", "-fd"),
        ("checkout", "main"),
        ("switch", "main"),
        ("stash",),
        ("gc",),
        ("update-ref", "refs/heads/main", "x"),
        ("worktree", "prune"),
        ("worktree", "move", "a", "b"),
        ("branch", "-D", "x"),
        ("branch", "--delete", "--force", "x"),
        ("branch", "x"),
        ("remote", "add", "x", "y"),
        ("remote", "set-url", "origin", "y"),
        ("config", "core.hooksPath", "x"),
        ("commit", "--no-verify", "-m", "x"),
        ("commit", "-n", "-m", "x"),
        ("commit", "--amend", "-m", "x"),
        ("commit", "--no-verif", "-m", "x"),
        ("commit", "-nm", "x"),
        ("commit", "-m", "x", "--allow-empty"),
        ("worktree", "remove", "--forc", "x"),
        ("worktree", "remove", "--force", "x"),
        ("worktree", "remove", "-f", "x"),
        ("worktree", "add", "--force", "x"),
        ("ls-remote", "--upload-pack=x", "origin"),
        ("-c", "core.hooksPath=x", "commit"),
        (),
    ],
)
def test_git_commands_outside_the_closed_list_are_refused(args: tuple[str, ...]) -> None:
    with pytest.raises(BlockedError) as caught:
        validate_git_args(args)
    assert caught.value.reason is Reason.GIT_FAILED


@pytest.mark.parametrize(
    "args",
    [
        ("status", "--porcelain=v1"),
        ("add", "--", "docs/a.md"),
        ("commit", "-m", "chore: x"),
        ("worktree", "add", "--no-track", "-b", "claude/x", "p", "sha"),
        ("worktree", "remove", "p"),
        ("worktree", "list", "--porcelain"),
        ("branch", "-d", "claude/x"),
        ("ls-remote", "origin", "refs/heads/main"),
    ],
)
def test_git_commands_in_the_closed_list_are_accepted(args: tuple[str, ...]) -> None:
    validate_git_args(args)


# --- El código fuente no contiene otros caminos ---------------------------------------------


def _runner_tree() -> ast.Module:
    return ast.parse(RUNNER_PATH.read_text(encoding="utf-8"))


def _constants_outside_denylists() -> set[str]:
    denylists = {"FORBIDDEN_GIT_TOKENS", "_FORBIDDEN_PROGRAMS"}
    tree = _runner_tree()
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in denylists for target in node.targets
        ):
            skipped.update(id(child) for child in ast.walk(node))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skipped
    }


@pytest.mark.parametrize(
    "token",
    [
        "push",
        "merge",
        "rebase",
        "pull",
        "fetch",
        "reset",
        "clean",
        "prune",
        "--force",
        "-f",
        "-D",
        "--hard",
        "--no-verify",
        "--amend",
        "gh",
        "Bash",
        "PowerShell",
        "WebFetch",
        "WebSearch",
        "Task",
    ],
)
def test_runner_source_has_no_forbidden_argument(token: str) -> None:
    assert token not in _constants_outside_denylists()


def test_runner_only_imports_a_closed_list_of_modules() -> None:
    allowed = {
        "__future__",
        "argparse",
        "collections",
        "ctypes",
        "dataclasses",
        "datetime",
        "enum",
        "fcntl",
        "hashlib",
        "itertools",
        "json",
        "msvcrt",
        "os",
        "pathlib",
        "re",
        "signal",
        "subprocess",
        "sys",
        "tempfile",
        "time",
        "tomllib",
        "traceback",
        "typing",
        "unicodedata",
        "uuid",
        # Solo para ver si existen las claves de política de Claude Code (ADR 0037).
        "winreg",
        "yaml",
    }
    imported: set[str] = set()
    for node in ast.walk(_runner_tree()):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported <= allowed, imported - allowed
    assert not imported & {"elsa", "httpx", "urllib", "socket", "requests", "shutil", "asyncpg"}


def test_all_processes_start_in_the_process_tree() -> None:
    popens: list[str] = []
    forbidden_calls: list[str] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.classes: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self.classes.append(node.name)
            self.generic_visit(node)
            self.classes.pop()

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                name = f"{func.value.id}.{func.attr}"
                if name == "subprocess.Popen":
                    popens.append(self.classes[-1] if self.classes else "module")
                if name in {"subprocess.run", "subprocess.call", "subprocess.check_output"}:
                    forbidden_calls.append(name)
                if name in {"os.system", "os.popen", "os.startfile", "os.spawnl"}:
                    forbidden_calls.append(name)
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    forbidden_calls.append("shell=")
            self.generic_visit(node)

    Visitor().visit(_runner_tree())
    assert popens == ["_ProcessTree", "_ProcessTree"]
    assert forbidden_calls == []


def test_console_offers_no_way_to_choose_executor_or_skip_approval() -> None:
    parser = orchestrator.build_parser()
    for action in ("validate", "run", "cleanup"):
        with pytest.raises(SystemExit):
            parser.parse_args([action])
        assert parser.parse_args([action, "T1.1"]).block == "T1.1"
    for extra in ("--executor=x", "--yes", "--force", "--repo=x", "--root=x", "--config=x"):
        assert orchestrator.main(["run", "T1.1", extra]) == orchestrator.EXIT_USAGE


def test_default_executor_changes_nothing_and_starts_no_process() -> None:
    executor = orchestrator.NoChangeExecutor()
    assert executor.command(Path("."), "x") is None
    source = inspect.getsource(orchestrator.main)
    assert "executor" not in source


def test_default_config_points_to_the_authorized_repository() -> None:
    config = orchestrator.default_config()
    assert config.expected_origin == "https://github.com/VallejoOsorio2026/Elsa-ai.git"
    assert config.repo_root == REPO_ROOT
    assert config.external_root.name == "elsa-o1"
    assert config.code_gates is None
    assert config.executor_timeout_seconds is None
    assert not config.extra_env


# --- Salida del ejecutor --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b'{"status": "done", "reason_code": null}\n', ("done", None)),
        (
            b'ruido\n{"status": "blocked", "reason_code": "needs_human"}\n\n',
            ("blocked", "needs_human"),
        ),
    ],
)
def test_valid_executor_output(data: bytes, expected: tuple[str, str | None]) -> None:
    assert parse_executor_output(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\n\n",
        b"no es json",
        b"[1]",
        b'{"status": "done"}',
        b'{"status": "done", "reason_code": null, "command": "x"}',
        b'{"status": "ok", "reason_code": null}',
        b'{"status": "done", "reason_code": "Texto libre con espacios"}',
        b'{"status": "done", "reason_code": 3}',
    ],
)
def test_invalid_executor_output(data: bytes) -> None:
    with _assert_blocked(Reason.INVALID_EXECUTOR_OUTPUT):
        parse_executor_output(data)


# --- Entorno, secretos y evidencia ----------------------------------------------------------


def _config(tmp_path: Path, **overrides: object) -> RunnerConfig:
    values: dict[str, object] = {
        "repo_root": tmp_path / "repo",
        "external_root": tmp_path / "ext",
        "expected_origin": "x",
        "tool_python": Path("python"),
    }
    values.update(overrides)
    return RunnerConfig(**values)  # type: ignore[arg-type]


def test_environment_is_an_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "GITHUB_TOKEN",
        "ELSA_NODE_TOKEN",
        "SUPABASE_SERVICE_ROLE_KEY",
        "ANTHROPIC_API_KEY",
        "DATABASE_URL",
        "ELSA_TEST_DATABASE_URL",
        "AWS_SECRET_ACCESS_KEY",
        "PYTHONPATH",
        "GIT_DIR",
    ):
        monkeypatch.setenv(name, "valor")
    monkeypatch.setenv("PATH", "visible")
    env = orchestrator.build_env(_config(tmp_path))
    assert env["PATH"] == "visible"
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert not {"GITHUB_TOKEN", "ELSA_NODE_TOKEN", "ANTHROPIC_API_KEY", "GIT_DIR"} & set(env)
    assert not {name for name in env if "TOKEN" in name or "SECRET" in name or "KEY" in name}


@pytest.mark.parametrize(
    "secret",
    [
        FAKE_TOKEN,
        "github_pat_" + "a" * 30,
        "sk-" + "a" * 30,
        "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12,
        "-----BEGIN " + "PRIVATE KEY-----\nabc\n-----END " + "PRIVATE KEY-----",
        "postgresql://user:" + "clave" + "@host/db",
        "password=" + "clave1234",
        "API_KEY: " + "clave1234",
        "service_role=" + "clave1234",
        'password="' + 'clave1234"',
        '"token": "' + 'clave1234"',
        "sb_secret_" + "a" * 20,
        "AKIA" + "A" * 16,
        "Bearer " + "a" * 30,
    ],
)
def test_known_secret_patterns_are_scrubbed(secret: str) -> None:
    assert secret not in scrub_text(f"antes {secret} después")
    assert "[REDACTED]" in scrub_text(f"antes {secret} después")


def test_log_is_scrubbed_even_when_the_run_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(argv: object, *, stdout: IO[bytes], **kwargs: object) -> None:
        stdout.write(f"token = {FAKE_TOKEN}".encode())
        stdout.flush()
        raise KeyboardInterrupt

    monkeypatch.setattr(orchestrator, "run_process", interrupted)
    log_path = tmp_path / "gate.log"
    with pytest.raises(KeyboardInterrupt):
        orchestrator._run_logged(
            _config(tmp_path), ["x"], cwd=tmp_path, env={}, timeout=1.0, log_path=log_path
        )
    assert FAKE_TOKEN not in log_path.read_text(encoding="utf-8")


def test_git_in_the_current_folder_or_the_repository_is_never_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = "git.exe" if sys.platform == "win32" else "git"
    repo = tmp_path / "repo"
    good = tmp_path / "good"
    relative = tmp_path / "relative"
    for folder in (repo, good, relative):
        folder.mkdir()
        (folder / name).write_text("x", encoding="utf-8")
    monkeypatch.chdir(relative)
    monkeypatch.setenv("PATH", os.pathsep.join([".", "", str(repo), str(good)]))
    assert orchestrator.find_git(_config(tmp_path, repo_root=repo)) == str(good / name)


def test_missing_git_is_a_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with _assert_blocked(Reason.GIT_FAILED, "git_not_found"):
        orchestrator.find_git(_config(tmp_path))


def _report() -> RunReport:
    return RunReport(
        block_id="T1.1",
        title="Prueba",
        spec_sha256="0" * 64,
        branch="claude/t1-1",
        base_sha="1" * 40,
        spec_commit="2" * 40,
        content_commit="3" * 40,
        tree="4" * 40,
        executor_kind="fake",
        executor_returncode=0,
        executor_status="done",
        changes=[Change("docs/a.md", "M")],
        profile="code",
        gates=[GateRecord("pytest", 0, 1.5, "3 passed, 1 skipped")],
        secret_scans=[("changes", "aprobado")],
        result=Result.VERIFIED_LOCAL,
    )


def test_evidence_has_the_required_fields(tmp_path: Path) -> None:
    text = render_evidence(_report())
    for expected in (
        "T1.1",
        "0" * 64,
        "claude/t1-1",
        "1" * 40,
        "2" * 40,
        "3" * 40,
        "4" * 40,
        "`fake`",
        "`M` `docs/a.md`",
        "`code`",
        "3 passed, 1 skipped",
        "`changes`: aprobado",
        "`verified_local`",
        "Sin push, sin PR y sin merge.",
    ):
        assert expected in text
    validate_evidence_text(text, _config(tmp_path))


@pytest.mark.parametrize(
    "dangerous",
    [
        "C:\\Users\\alguien\\x",
        "C:/Users/alguien/x",
        "/home/alguien/x",
        "/Users/alguien/x",
        "%USERPROFILE%\\x",
        FAKE_TOKEN,
        "password=" + "clave1234",
    ],
)
def test_evidence_with_paths_or_secrets_is_rejected(tmp_path: Path, dangerous: str) -> None:
    report = _report()
    report.title = dangerous
    with _assert_blocked(Reason.EVIDENCE_REJECTED):
        validate_evidence_text(render_evidence(report), _config(tmp_path))


def test_evidence_rejects_the_configured_private_roots(tmp_path: Path) -> None:
    config = _config(tmp_path, external_root=Path("rel/ext"), repo_root=Path("rel/repo"))
    with _assert_blocked(Reason.EVIDENCE_REJECTED):
        validate_evidence_text("ver rel/ext/logs", config)


EXACT_WINDOWS_OMISSIONS = {
    "tests/test_bench_harness.py::test_a_run_records_what_produced_it",
    "tests/test_bench_harness.py::test_peak_memory_is_measured_where_the_posix_api_exists",
    "tests/test_pc1_supervisor.py::"
    "test_a_real_ctrl_c_reaches_only_the_supervisor_which_stops_in_order",
}


def test_windows_omissions_are_exactly_the_three_approved_tests() -> None:
    assert set(orchestrator.WINDOWS_KNOWN_TEST_FAILURES) == EXACT_WINDOWS_OMISSIONS
    assert all(orchestrator.WINDOWS_KNOWN_TEST_FAILURES.values())


@pytest.mark.parametrize("test_id", sorted(EXACT_WINDOWS_OMISSIONS))
def test_windows_omissions_name_real_tests_without_patterns(test_id: str) -> None:
    path, _, name = test_id.partition("::")
    assert not set(test_id) & set("*?[]")
    assert f"def {name}(" in (REPO_ROOT / path).read_text(encoding="utf-8")


def _pytest_gate(tmp_path: Path, platform: str) -> orchestrator.Gate:
    gates = orchestrator.default_code_gates(_config(tmp_path), platform=platform)
    return next(gate for gate in gates if gate.name == "pytest")


def test_only_windows_omits_tests(tmp_path: Path) -> None:
    linux = _pytest_gate(tmp_path, "linux")
    assert linux.omitted_tests == ()
    assert "--deselect" not in linux.argv


def test_windows_omits_each_test_by_its_exact_id_and_nothing_else(tmp_path: Path) -> None:
    gate = _pytest_gate(tmp_path, "win32")
    assert set(gate.omitted_tests) == EXACT_WINDOWS_OMISSIONS
    assert gate.argv.count("--deselect") == 3
    deselected = {gate.argv[i + 1] for i, arg in enumerate(gate.argv) if arg == "--deselect"}
    assert deselected == EXACT_WINDOWS_OMISSIONS
    for broad in ("-k", "-m", "--ignore", "--ignore-glob", "--continue-on-collection-errors"):
        assert broad not in gate.argv[2:]


def test_evidence_declares_omitted_tests_with_their_cause() -> None:
    report = _report()
    report.omitted_tests = tuple(sorted(EXACT_WINDOWS_OMISSIONS))
    text = render_evidence(report)
    for test_id, cause in orchestrator.WINDOWS_KNOWN_TEST_FAILURES.items():
        assert f"`{test_id}`: {cause}" in text


def test_evidence_without_omissions_does_not_mention_them() -> None:
    assert "omitidas" not in render_evidence(_report())


def test_every_reason_has_a_message() -> None:
    assert set(orchestrator.MESSAGES) == set(Reason)


def test_pytest_summary_is_read_from_the_last_line() -> None:
    log = "1 failed antes\n.....\n1000 passed, 20 skipped, 3 deselected in 12.00s\n"
    assert orchestrator._pytest_summary(log) == "1000 passed, 20 skipped, 3 deselected"
    assert orchestrator._pytest_summary("sin resumen") == ""


# --- Lanzador PowerShell --------------------------------------------------------------------


WRAPPER = WRAPPER_PATH.read_text(encoding="utf-8-sig")
# El código, sin la ayuda ni los comentarios: las reglas se fijan sobre lo que se ejecuta.
WRAPPER_CODE = "\n".join(
    line for line in WRAPPER.split("#>")[-1].splitlines() if not line.startswith("#")
)


def test_wrapper_uses_the_repository_python_without_uv_run() -> None:
    assert ".venv\\Scripts\\python.exe" in WRAPPER_CODE
    assert "uv run" not in WRAPPER_CODE
    assert "Set-StrictMode -Version Latest" in WRAPPER
    assert "$ErrorActionPreference = 'Stop'" in WRAPPER


def test_wrapper_has_the_same_encoding_as_the_other_scripts() -> None:
    # Sin esta marca, Windows PowerShell 5.1 lee mal los acentos de sus mensajes.
    assert WRAPPER_PATH.read_bytes().startswith(b"\xef\xbb\xbf")


def test_wrapper_declares_a_closed_list_of_actions_and_returns_the_exit_code() -> None:
    assert "[ValidateSet('Validate', 'Run', 'Status', 'Cleanup')]" in WRAPPER
    assert "$code = $LASTEXITCODE" in WRAPPER
    assert WRAPPER.rstrip().endswith("exit $code")


@pytest.mark.parametrize(
    "fragment",
    [
        "git push",
        "git merge",
        "claude",
        "--force",
        "-Force",
        "Remove-Item",
        "Invoke-Expression",
        "iex ",
    ],
)
def test_wrapper_has_no_dangerous_fragment(fragment: str) -> None:
    assert fragment.lower() not in WRAPPER_CODE.lower()
