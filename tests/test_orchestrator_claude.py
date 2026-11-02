"""El contrato del ejecutor Claude real, sin Claude real: corre también en CI.

Un Claude falso habla el mismo `stream-json` como proceso de verdad. Las pruebas con la
versión real, que consumen uso y solo corren a mano, están en
``test_orchestrator_claude_live.py``.
"""

from __future__ import annotations

import ast
import json
import sys
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import orchestrator
import pytest
from orchestrator import (
    CLAUDE_FROZEN_FLAGS,
    CLAUDE_READ_ONLY_GIT,
    FORBIDDEN_CLAUDE_OPTIONS,
    BlockedError,
    Change,
    ClaudeExecutor,
    Reason,
    Result,
    RunReport,
    Spec,
    build_claude_argv,
    check_claude_init,
    check_claude_report,
    check_git_trace,
    run_block,
    validate_claude_argv,
    validate_docs_only_spec,
    validate_structured_output,
)

from tests.test_orchestrator_integration import Sandbox, _git

FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"
RUNNER_PATH = Path(orchestrator.__file__)
BLOCK = "T1.1"
ALLOWED = "[docs/permitido.md]"

GOOD_INIT: dict[str, Any] = {
    "type": "system",
    "subtype": "init",
    "uuid": "u",
    "session_id": "s",
    "cwd": "c",
    "original_cwd": "c",
    "powershell_path": "powershell.exe",
    **orchestrator.CLAUDE_INIT_FIXED_VALUES,
    "claude_code_version": orchestrator.CLAUDE_VERSION,
    "permissionMode": "dontAsk",
    "tools": ["Edit", "Glob", "Grep", "Read", "StructuredOutput", "Write"],
    "mcp_servers": [],
    "additional_directories": [],
    "skills": [],
    "slash_commands": [],
    "agents": ["claude", "Explore", "general-purpose", "Plan"],
    "plugins": [
        {
            "name": "cc-plugin-agents-md",
            "path": "builtin",
            "source": "cc-plugin-agents-md@builtin",
        },
        {
            "name": "cc-plugin-plugin-authoring",
            "path": "builtin",
            "source": "cc-plugin-plugin-authoring@builtin",
        },
    ],
    "apiKeySource": "none",
    "model": "claude-sonnet-5-5",
}
GOOD_OUTPUT = {
    "result": "done",
    "files_changed": ["docs/a.md"],
    "blocked": False,
    "reason": "ok_code",
}


def _spec(*allowed: str) -> Spec:
    return Spec(
        id=BLOCK,
        title="x",
        base="main",
        branch="claude/t1-1",
        allowed_paths=allowed or ("docs/permitido.md",),
        forbidden_paths=(),
        timeout_minutes=1,
        stop_conditions=(),
        human_gates=(),
        raw=b"",
        sha256="0" * 64,
    )


def _argv() -> list[str]:
    return build_claude_argv(("claude",), _spec(), "00000000-0000-0000-0000-000000000000")


def _option(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


# --- Comando --------------------------------------------------------------------------------


@pytest.mark.parametrize("flag", CLAUDE_FROZEN_FLAGS)
def test_command_always_freezes_capabilities(flag: str) -> None:
    assert flag in _argv()


def test_command_uses_the_authorized_mode_tools_and_model() -> None:
    argv = _argv()
    assert _option(argv, "--permission-mode") == "dontAsk"
    assert _option(argv, "--permission-prompts") == "none"
    assert _option(argv, "--tools") == "Read,Edit,Write,Glob,Grep"
    assert _option(argv, "--model") == "sonnet"
    assert "--no-session-persistence" in argv


def test_command_has_no_forbidden_option() -> None:
    assert not set(_argv()) & FORBIDDEN_CLAUDE_OPTIONS
    assert "--settings" in FORBIDDEN_CLAUDE_OPTIONS


def test_write_permission_uses_edit_rules_never_write_rules() -> None:
    allowed = _option(_argv(), "--allowedTools").split(",")
    assert allowed == ["Read", "Glob", "Grep", "Edit(docs/permitido.md)"]


def test_env_denial_covers_all_eight_case_variants() -> None:
    rules = _option(_argv(), "--disallowedTools").split(",")
    assert len(rules) == 40
    assert "Read(**/.eNv*)" in rules and "Grep(**/.ENv*)" in rules


@pytest.mark.parametrize("name", [".env", ".ENV", ".Env"])
@pytest.mark.parametrize("tool", ["Read", "Edit", "Write", "Glob", "Grep"])
def test_env_files_are_denied_in_every_case_variant(tool: str, name: str) -> None:
    assert f"{tool}(**/{name}*)" in _option(_argv(), "--disallowedTools").split(",")


def test_prompt_does_not_carry_the_specification_contents() -> None:
    spec = replace(_spec(), raw=b"contenido-que-no-debe-viajar", title="titulo-que-no-debe-viajar")
    joined = " ".join(build_claude_argv(("claude",), spec, "s"))
    assert "contenido-que-no-debe-viajar" not in joined
    assert "titulo-que-no-debe-viajar" not in joined


@pytest.mark.parametrize("option", sorted(FORBIDDEN_CLAUDE_OPTIONS))
def test_validator_refuses_every_forbidden_option(option: str) -> None:
    with pytest.raises(BlockedError) as caught:
        validate_claude_argv([*_argv(), option, "x"])
    assert caught.value.reason is Reason.CLAUDE_UNSAFE_COMMAND


def test_validator_refuses_settings_written_with_equals() -> None:
    with pytest.raises(BlockedError):
        validate_claude_argv([*_argv(), "--settings=x.json"])


@pytest.mark.parametrize("flag", [*CLAUDE_FROZEN_FLAGS, "--no-session-persistence"])
def test_validator_requires_every_frozen_flag(flag: str) -> None:
    argv = [token for token in _argv() if token != flag]
    with pytest.raises(BlockedError) as caught:
        validate_claude_argv(argv)
    assert caught.value.reason is Reason.CLAUDE_UNSAFE_COMMAND


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--permission-mode", "bypassPermissions"),
        ("--permission-prompts", "host"),
        ("--tools", "Bash,Read"),
        ("--tools", "default"),
        ("--model", "opus"),
    ],
)
def test_validator_requires_the_exact_values(option: str, value: str) -> None:
    argv = _argv()
    argv[argv.index(option) + 1] = value
    with pytest.raises(BlockedError):
        validate_claude_argv(argv)


@pytest.mark.parametrize(
    "extra",
    [
        ["--permission-mode=bypassPermissions"],
        ["--safe-mode=false"],
        ["--safe-mode"],
        ["--permission-mode", "dontAsk"],
        ["--allowed-tools", "Edit(**)"],
        ["--permission-prompt-tool", "x"],
        ["--debug-file", "x"],
        ["--unknown"],
    ],
)
def test_validator_is_a_closed_list(extra: list[str]) -> None:
    with pytest.raises(BlockedError) as caught:
        validate_claude_argv([*_argv(), *extra])
    assert caught.value.reason is Reason.CLAUDE_UNSAFE_COMMAND


@pytest.mark.parametrize("option", ["--disallowedTools", "--json-schema", "--output-format"])
def test_validator_requires_exact_deny_rules_schema_and_format(option: str) -> None:
    argv = _argv()
    argv[argv.index(option) + 1] = "otro"
    with pytest.raises(BlockedError):
        validate_claude_argv(argv)


@pytest.mark.parametrize(
    "rules",
    [
        "Write(docs/a.md)",
        "Read,Write",
        "Read,Edit",
        "Read,Edit(**)",
        "Read,Edit(docs/*)",
        "Read,Bash(git *)",
        "Read,Bash",
        "Read,WebFetch",
    ],
)
def test_validator_refuses_broad_or_write_rules(rules: str) -> None:
    argv = _argv()
    argv[argv.index("--allowedTools") + 1] = rules
    with pytest.raises(BlockedError):
        validate_claude_argv(argv)


# --- Especificación documental --------------------------------------------------------------


@pytest.mark.parametrize("path", ["docs/a.md", "docs/x/y.md", "README.md"])
def test_docs_only_spec_accepts_exact_documents(path: str) -> None:
    validate_docs_only_spec(_spec(path))


@pytest.mark.parametrize(
    "path", ["docs/**", "docs/*.md", "scripts/x.py", "src/a.md", "docs/a.txt", "tests/a.py", "x.md"]
)
def test_docs_only_spec_refuses_anything_else(path: str) -> None:
    with pytest.raises(BlockedError) as caught:
        validate_docs_only_spec(_spec(path))
    assert caught.value.detail == "claude_docs_only"


@pytest.mark.parametrize(
    "path",
    [
        "docs/node_modules/x.md",
        "docs/bower_components/x.md",
        "docs/vendor/x.md",
        "docs/env/lib/x.md",
        "docs/venv/x.md",
        "docs/foo-1.0.dist-info/x.md",
    ],
)
def test_docs_only_spec_refuses_paths_gitleaks_would_not_scan(path: str) -> None:
    with pytest.raises(BlockedError) as caught:
        validate_docs_only_spec(_spec(path))
    assert caught.value.detail == "claude_path_not_scanned"


@pytest.mark.parametrize("path", ["docs/adr./x.md", "docs/NUL.md", "docs/a b.md "])
def test_docs_only_spec_refuses_unsafe_names(path: str) -> None:
    with pytest.raises(BlockedError):
        validate_docs_only_spec(_spec(path))


def test_docs_only_spec_limits_the_number_of_paths() -> None:
    with pytest.raises(BlockedError):
        validate_docs_only_spec(_spec(*(f"docs/{n}.md" for n in range(6))))


# --- Primer evento --------------------------------------------------------------------------


def test_observed_init_is_accepted() -> None:
    check_claude_init(GOOD_INIT)


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("claude_code_version", "2.1.317", "version"),
        ("permissionMode", "acceptEdits", "permission_mode"),
        ("permissionMode", None, "permission_mode"),
        ("tools", [*GOOD_INIT["tools"], "Bash"], "tools"),
        ("tools", [*GOOD_INIT["tools"], "PowerShell"], "tools"),
        ("tools", [*GOOD_INIT["tools"], "WebFetch"], "tools"),
        ("tools", [*GOOD_INIT["tools"], "WebSearch"], "tools"),
        ("tools", [*GOOD_INIT["tools"], "Task"], "tools"),
        ("tools", ["Read"], "tools"),
        ("tools", None, "tools"),
        ("mcp_servers", [{"name": "x"}], "mcp"),
        ("mcp_servers", None, "mcp"),
        ("additional_directories", ["C:/x"], "additional_directories"),
        ("additional_directories", None, "additional_directories"),
        ("skills", ["debug"], "skills"),
        ("skills", None, "skills"),
        ("slash_commands", ["debug"], "slash_commands"),
        ("agents", [*GOOD_INIT["agents"], "otro"], "agents"),
        ("agents", ["claude"], "agents"),
        ("plugins", [*GOOD_INIT["plugins"], {"source": "otro@builtin"}], "plugins"),
        ("plugins", [{"source": "cc-plugin-agents-md@otro"}, GOOD_INIT["plugins"][1]], "plugins"),
        ("model", "claude-opus-5-5", "model"),
        ("plugins", [], "plugins"),
        ("apiKeySource", "ANTHROPIC_API_KEY", "api_key_source"),
        ("output_style", "otro", "output_style"),
        ("view_mode", "otro", "view_mode"),
        ("fast_mode_state", "on", "fast_mode_state"),
        ("ultrathink_available", True, "ultrathink_available"),
        ("capabilities", ["otra"], "capabilities"),
    ],
)
def test_any_unexpected_capability_stops(field: str, value: object, detail: str) -> None:
    with pytest.raises(BlockedError) as caught:
        check_claude_init({**GOOD_INIT, field: value})
    assert caught.value.reason is Reason.CLAUDE_CAPABILITY_MISMATCH
    assert caught.value.detail == detail


def test_first_event_fields_are_a_closed_list() -> None:
    assert set(GOOD_INIT) == orchestrator.CLAUDE_INIT_FIELDS
    for extra in ("hooks", "messaging_socket_path", "terminal_slash_commands"):
        with pytest.raises(BlockedError) as caught:
            check_claude_init({**GOOD_INIT, extra: "x"})
        assert caught.value.detail == "fields"
    for missing in orchestrator.CLAUDE_INIT_FIELDS:
        without = {key: value for key, value in GOOD_INIT.items() if key != missing}
        with pytest.raises(BlockedError) as caught:
            check_claude_init(without)
        assert caught.value.detail == "fields"


def test_later_init_events_are_watched_during_the_run(tmp_path: Path) -> None:
    log = tmp_path / "executor.log"
    good = {**GOOD_INIT, "cwd": str(tmp_path), "original_cwd": str(tmp_path)}
    line = json.dumps(good).encode() + b"\n"
    log.write_bytes(line)
    watcher = orchestrator._ClaudeInitWatcher(log, "s", tmp_path)
    assert watcher() is False
    assert watcher.seen
    # Una línea a medias no se da por perdida: espera a la vuelta siguiente.
    bad = json.dumps({**good, "tools": ["Bash"]}).encode() + b"\n"
    with open(log, "ab") as handle:
        handle.write(bad[:20])
    assert watcher() is False
    with open(log, "ab") as handle:
        handle.write(bad[20:])
    assert watcher() is True
    assert watcher.error is not None
    assert watcher.error.detail == "tools"


def _watcher_on(tmp_path: Path, data: bytes) -> orchestrator._ClaudeInitWatcher:
    log = tmp_path / "executor.log"
    log.write_bytes(data)
    return orchestrator._ClaudeInitWatcher(log, "s", tmp_path)


def _good_init_line(tmp_path: Path) -> str:
    return json.dumps({**GOOD_INIT, "cwd": str(tmp_path), "original_cwd": str(tmp_path)})


def test_init_hidden_behind_other_output_stops(tmp_path: Path) -> None:
    line = _good_init_line(tmp_path)
    watcher = _watcher_on(tmp_path, f"{line}\naviso sin salto {line}\n".encode())
    assert watcher() is True
    assert watcher.error is not None
    assert watcher.error.detail == "unreadable_init"


def test_separators_inside_a_text_do_not_split_an_event(tmp_path: Path) -> None:
    # JSON admite U+2028 sin escapar; `splitlines` lo tomaría por un fin de línea.
    good = {**GOOD_INIT, "cwd": str(tmp_path), "original_cwd": str(tmp_path)}
    bad = {**good, "tools": ["Bash"], "uuid": "a\u2028b"}
    text = json.dumps(bad, ensure_ascii=False)
    assert orchestrator._stream_events(f"{text}\n".encode())[0]["uuid"] == "a\u2028b"
    watcher = _watcher_on(tmp_path, f"{json.dumps(good)}\n{text}\n".encode())
    assert watcher() is True
    assert watcher.error is not None
    assert watcher.error.detail == "tools"


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"plugins": ["x"]}, "plugins"),
        ({"tools": ["Read", 1]}, "TypeError"),
    ],
)
def test_malformed_init_is_a_stop_not_an_internal_error(
    tmp_path: Path, change: dict[str, Any], detail: str
) -> None:
    good = {**GOOD_INIT, "cwd": str(tmp_path), "original_cwd": str(tmp_path)}
    watcher = _watcher_on(tmp_path, json.dumps({**good, **change}).encode() + b"\n")
    assert watcher() is True
    assert watcher.error is not None
    assert watcher.error.detail == detail


def test_line_too_deep_to_parse_is_a_stop_not_an_internal_error(tmp_path: Path) -> None:
    deep = b'{"a":' * 200_000 + b"1" + b"}" * 200_000 + b"\n"
    watcher = _watcher_on(tmp_path, deep)
    assert watcher() is True
    assert watcher.error is not None
    assert watcher.error.detail == "RecursionError"


def test_log_beyond_the_reading_limit_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    line = _good_init_line(tmp_path)
    monkeypatch.setattr(orchestrator, "MAX_EXECUTOR_OUTPUT_BYTES", len(line))
    watcher = _watcher_on(tmp_path, f"{line}\n{line}\n".encode())
    assert watcher() is True
    assert watcher.error is not None
    assert watcher.error.detail == "log_too_large"


def test_unreadable_log_is_a_stop_not_an_internal_error(tmp_path: Path) -> None:
    watcher = orchestrator._ClaudeInitWatcher(tmp_path / "no_existe", "s", tmp_path)
    assert watcher() is True
    assert watcher.error is not None
    assert watcher.error.detail == "FileNotFoundError"


def test_session_and_folder_of_the_first_event_must_match(tmp_path: Path) -> None:
    good = {**GOOD_INIT, "session_id": "s", "cwd": str(tmp_path), "original_cwd": str(tmp_path)}
    check_claude_init(good, session_id="s", cwd=tmp_path)
    with pytest.raises(BlockedError) as caught:
        check_claude_init(good, session_id="otra", cwd=tmp_path)
    assert caught.value.detail == "session"
    with pytest.raises(BlockedError) as caught:
        check_claude_init(good, session_id="s", cwd=tmp_path / "otra")
    assert caught.value.detail == "cwd"


# --- Comandos Git internos ------------------------------------------------------------------


def _trace(*commands: str) -> str:
    return "".join(f"12:00:00.0 git.c:476  trace: built-in: {command}\n" for command in commands)


def test_observed_git_commands_are_accepted() -> None:
    check_git_trace(_trace(*sorted(CLAUDE_READ_ONLY_GIT)))


@pytest.mark.parametrize(
    "command",
    [
        "git push origin main",
        "git fetch",
        "git commit -m x",
        "git reset --hard",
        "git clean -fd",
        "git merge x",
        "git checkout main",
        "git credential fill",
        "git config user.name otro",
        "git status",
        "git status --short",
        "git log",
        "git remote add x y",
    ],
)
def test_any_other_git_command_stops(command: str) -> None:
    with pytest.raises(BlockedError) as caught:
        check_git_trace(_trace("git version", command))
    assert caught.value.reason is Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED


def test_exec_and_run_command_trace_lines_also_count() -> None:
    with pytest.raises(BlockedError):
        check_git_trace("12:00 run-command.c:1  trace: run_command: git push\n")
    with pytest.raises(BlockedError):
        check_git_trace("12:00 exec-cmd.c:1  trace: exec: git-remote-https x\n")


def test_harmless_trace_lines_are_ignored_but_unknown_ones_stop() -> None:
    harmless = "12:00 exec-cmd.c:1  trace: resolved executable dir: C:/Git/mingw64/bin\n"
    check_git_trace(harmless + _trace("git version"))
    with pytest.raises(BlockedError) as caught:
        check_git_trace(_trace("git version") + "12:00 git.c:1  trace: alias expansion: x => y\n")
    assert caught.value.reason is Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED
    with pytest.raises(BlockedError) as caught:
        check_git_trace(harmless)
    assert caught.value.reason is Reason.CLAUDE_GIT_TRACE_MISSING


def test_prompt_asks_for_the_final_newline_the_hooks_require() -> None:
    assert "salto de línea" in _argv()[_argv().index("-p") + 1]


def test_line_without_trace_marker_stops() -> None:
    with pytest.raises(BlockedError) as caught:
        check_git_trace(_trace("git version") + "otra cosa\n")
    assert caught.value.detail == "unknown_trace_line"


def test_empty_trace_stops() -> None:
    with pytest.raises(BlockedError) as caught:
        check_git_trace("")
    assert caught.value.reason is Reason.CLAUDE_GIT_TRACE_MISSING


# --- Salida estructurada --------------------------------------------------------------------


def test_valid_structured_output() -> None:
    assert validate_structured_output(GOOD_OUTPUT) == GOOD_OUTPUT


@pytest.mark.parametrize(
    "value",
    [
        None,
        "texto",
        [],
        {},
        {"result": "done"},
        {**GOOD_OUTPUT, "command": "x"},
        {**GOOD_OUTPUT, "result": "otro"},
        {**GOOD_OUTPUT, "reason": "texto libre con espacios"},
        {**GOOD_OUTPUT, "reason": "A" * 65},
        {**GOOD_OUTPUT, "reason": 3},
        {**GOOD_OUTPUT, "files_changed": "docs/a.md"},
        {**GOOD_OUTPUT, "files_changed": [1]},
        {**GOOD_OUTPUT, "blocked": "false"},
        {**GOOD_OUTPUT, "blocked": 0},
        {**GOOD_OUTPUT, "blocked": True},
        {"result": "blocked", "files_changed": [], "blocked": False, "reason": "x"},
    ],
)
def test_invalid_structured_output(value: object) -> None:
    with pytest.raises(BlockedError) as caught:
        validate_structured_output(value)
    assert caught.value.reason is Reason.INVALID_STRUCTURED_OUTPUT


def test_declared_files_must_match_git() -> None:
    check_claude_report(GOOD_OUTPUT, [Change("docs/a.md", "A")])
    check_claude_report(
        {**GOOD_OUTPUT, "files_changed": ["docs\\a.md"]}, [Change("docs/a.md", "A")]
    )
    check_claude_report(
        {**GOOD_OUTPUT, "files_changed": ["./docs/a.md"]}, [Change("docs/a.md", "A")]
    )
    for declared in ([], ["docs/b.md"], ["docs/a.md", "docs/b.md"]):
        with pytest.raises(BlockedError) as caught:
            check_claude_report(
                {**GOOD_OUTPUT, "files_changed": declared}, [Change("docs/a.md", "A")]
            )
        assert caught.value.reason is Reason.CLAUDE_REPORT_MISMATCH


# --- Entorno --------------------------------------------------------------------------------


def test_claude_environment_is_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDECODE",
        "AI_AGENT",
        "GITHUB_TOKEN",
        "ELSA_NODE_TOKEN",
        "SUPABASE_SERVICE_ROLE_KEY",
        "PYTHONPATH",
        "GIT_DIR",
        "HTTPS_PROXY",
    ):
        monkeypatch.setenv(name, "valor")
    config = orchestrator.RunnerConfig(
        repo_root=tmp_path,
        external_root=tmp_path / "ext",
        expected_origin="x",
        tool_python=Path(sys.executable),
    )
    env = orchestrator.build_claude_env(config, tmp_path / "trace", tmp_path / "tmp")
    assert not {
        n
        for n in env
        if "ANTHROPIC" in n
        or n in ("CLAUDECODE", "AI_AGENT", "PYTHONPATH", "GIT_DIR", "HTTPS_PROXY")
    }
    assert not {n for n in env if "TOKEN" in n or "KEY_0" not in n and n.endswith("KEY")}
    assert env["GIT_TRACE"] == str(tmp_path / "trace")
    assert env["TEMP"] == str(tmp_path / "tmp")
    assert env["GIT_CONFIG_KEY_0"] == "credential.helper" and env["GIT_CONFIG_VALUE_0"] == ""
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_OPTIONAL_LOCKS"] == "0"


@pytest.mark.parametrize(
    ("name", "value", "passes"),
    [
        ("HTTPS_PROXY", "http://127.0.0.1:9", True),
        ("FAKE_CLAUDE_X", "1", True),
        ("HTTPS_PROXY", "http://example.invalid:9", False),
        ("ANTHROPIC_BASE_URL", "http://127.0.0.1:9", False),
        ("NODE_OPTIONS", "x", False),
        ("PATH", "x", False),
        ("GIT_TRACE", "x", False),
        ("GIT_CONFIG_VALUE_0", "manager", False),
    ],
)
def test_extra_env_cannot_change_the_closed_environment(
    tmp_path: Path, name: str, value: str, passes: bool
) -> None:
    config = orchestrator.RunnerConfig(
        repo_root=tmp_path,
        external_root=tmp_path / "ext",
        expected_origin="x",
        tool_python=Path(sys.executable),
        extra_env={name: value},
    )
    env = orchestrator.build_claude_env(config, tmp_path / "trace", tmp_path / "tmp")
    assert (env.get(name) == value) is passes


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/VallejoOsorio2026/Elsa-ai.git",
        "https://github.com/VallejoOsorio2026/Elsa-ai",
        "https://github.com/vallejoosorio2026/elsa-ai/",
        "git@github.com:VallejoOsorio2026/Elsa-ai.git",
        "ssh://git@github.com/VallejoOsorio2026/Elsa-ai.git",
        "https://www.github.com/VallejoOsorio2026/Elsa-ai.git",
        "https://user@github.com/VallejoOsorio2026/Elsa-ai.git",
        "https://user:clave@github.com/VallejoOsorio2026/Elsa-ai.git",
        "https://github.com:443/VallejoOsorio2026/Elsa-ai.git",
        "git://github.com/VallejoOsorio2026/Elsa-ai.git",
        "ssh://git@ssh.github.com:443/VallejoOsorio2026/Elsa-ai.git",
        "https://github.com//VallejoOsorio2026//Elsa-ai.git/",
        "git@github.com-work:VallejoOsorio2026/Elsa-ai.git",
        "https://user:p@ss@github.com/VallejoOsorio2026/Elsa-ai.git",
        "https://otro.example/VallejoOsorio2026/Elsa-ai.git",
    ],
)
def test_every_spelling_of_the_real_origin_is_refused(tmp_path: Path, url: str) -> None:
    config = orchestrator.RunnerConfig(
        repo_root=tmp_path,
        external_root=tmp_path / "ext",
        expected_origin=url,
        tool_python=Path(sys.executable),
    )
    with pytest.raises(BlockedError) as caught:
        orchestrator.ensure_not_real_repository(config)
    assert caught.value.reason is Reason.REAL_REPO_NOT_AUTHORIZED


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/otra/Elsa-ai.git",
        "https://github.com/VallejoOsorio2026/Otro.git",
        "C:/desechable/origin.git",
        "C:\\desechable\\origin.git",
        "/tmp/desechable/origin.git",
    ],
)
def test_other_origins_are_not_the_real_one(url: str) -> None:
    real = orchestrator.normalized_origin(orchestrator.EXPECTED_ORIGIN)
    assert orchestrator.normalized_origin(url) != real


def _repo_with_origin(tmp_path: Path, *urls: tuple[str, ...]) -> orchestrator.RunnerConfig:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    for args in urls:
        _git(repo, "remote", *args)
    return orchestrator.RunnerConfig(
        repo_root=repo,
        external_root=tmp_path / "ext",
        expected_origin="https://github.com/otra/Elsa-ai.git",
        tool_python=Path(sys.executable),
    )


@pytest.mark.parametrize(
    "urls",
    [
        [("add", "origin", orchestrator.EXPECTED_ORIGIN)],
        [("add", "origin", "git@github.com:VallejoOsorio2026/Elsa-ai.git")],
        [
            ("add", "origin", "https://github.com/otra/Elsa-ai.git"),
            ("set-url", "--push", "origin", orchestrator.EXPECTED_ORIGIN),
        ],
        [
            ("add", "origin", "https://github.com/otra/Elsa-ai.git"),
            ("set-url", "--add", "origin", orchestrator.EXPECTED_ORIGIN),
        ],
    ],
)
def test_git_is_asked_whatever_the_configuration_says(
    tmp_path: Path, urls: list[tuple[str, ...]]
) -> None:
    config = _repo_with_origin(tmp_path, *urls)
    with pytest.raises(BlockedError) as caught:
        orchestrator.ensure_not_real_repository(config)
    assert caught.value.reason is Reason.REAL_REPO_NOT_AUTHORIZED


def test_origin_without_url_is_refused(tmp_path: Path) -> None:
    config = _repo_with_origin(tmp_path, ("add", "origin", "https://github.com/otra/x.git"))
    _git(config.repo_root, "config", "--unset", "remote.origin.url")
    with pytest.raises(BlockedError) as caught:
        orchestrator.ensure_not_real_repository(config)
    assert caught.value.detail == "origin_unreadable"


def test_repository_without_origin_is_refused(tmp_path: Path) -> None:
    config = _repo_with_origin(tmp_path)
    with pytest.raises(BlockedError) as caught:
        orchestrator.ensure_not_real_repository(config)
    assert caught.value.detail == "origin_unreadable"


def test_other_repository_passes_the_guard(tmp_path: Path) -> None:
    config = _repo_with_origin(tmp_path, ("add", "origin", "https://github.com/otra/Elsa-ai.git"))
    orchestrator.ensure_not_real_repository(config)


def _home(tmp_path: Path, **files: str) -> orchestrator.RunnerConfig:
    for name, text in files.items():
        (tmp_path / f"{name}.json").write_text(text, encoding="utf-8")
    return orchestrator.RunnerConfig(
        repo_root=tmp_path,
        external_root=tmp_path / "ext",
        expected_origin="x",
        tool_python=Path(sys.executable),
        claude_home=tmp_path,
    )


def test_measured_user_settings_are_accepted(tmp_path: Path) -> None:
    orchestrator.check_claude_user_settings(_home(tmp_path))
    orchestrator.check_claude_user_settings(
        _home(tmp_path, settings='{"autoUpdatesChannel": "latest", "tui": {}}')
    )


@pytest.mark.parametrize(
    "text",
    [
        '{"hooks": {}}',
        '{"permissions": {"allow": ["Edit"]}}',
        '{"env": {"X": "y"}}',
        '{"apiKeyHelper": "x"}',
        "no json",
        "[]",
    ],
)
def test_other_user_settings_stop(tmp_path: Path, text: str) -> None:
    with pytest.raises(BlockedError) as caught:
        orchestrator.check_claude_user_settings(_home(tmp_path, settings=text))
    assert caught.value.reason is Reason.CLAUDE_USER_SETTINGS_UNEXPECTED


def test_local_user_settings_stop(tmp_path: Path) -> None:
    (tmp_path / "settings.local.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BlockedError):
        orchestrator.check_claude_user_settings(_home(tmp_path))


# --- Solo una ruta puede lanzar Claude ------------------------------------------------------


def test_only_the_claude_route_can_launch_claude() -> None:
    callers: list[str] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            for keyword in node.keywords:
                if (
                    keyword.arg == "allow_claude"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    callers.append(self.stack[-1])
            self.generic_visit(node)

    Visitor().visit(ast.parse(RUNNER_PATH.read_text(encoding="utf-8")))
    assert sorted(callers) == ["check_claude_version", "run_claude_executor"]


def test_console_does_not_offer_the_real_executor() -> None:
    parser = orchestrator.build_parser()
    for action in ("run-claude", "runclaude", "claude"):
        with pytest.raises(SystemExit):
            parser.parse_args([action, BLOCK])
    assert orchestrator.main(["run", BLOCK, "--executor=claude"]) == orchestrator.EXIT_USAGE


def test_real_repository_is_refused_before_anything_happens(tmp_path: Path) -> None:
    config = orchestrator.RunnerConfig(
        repo_root=tmp_path / "repo",
        external_root=tmp_path / "ext",
        expected_origin=orchestrator.EXPECTED_ORIGIN,
        tool_python=Path(sys.executable),
    )
    (tmp_path / "repo").mkdir()
    report = run_block(config, BLOCK, executor=ClaudeExecutor(), confirm=lambda _s: True)
    assert report.result is Result.BLOCKED
    assert report.reason is Reason.REAL_REPO_NOT_AUTHORIZED


# --- Recorrido completo con Claude falso ----------------------------------------------------


class ClaudeSandbox(Sandbox):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.record = root / "claude-record.jsonl"

    def executor(self, scenario: str) -> ClaudeExecutor:
        return ClaudeExecutor(
            argv_prefix=(sys.executable, str(FAKE_CLAUDE), scenario, str(self.record))
        )

    def run_claude(self, scenario: str, **changes: Any) -> RunReport:
        config = replace(self.config, claude_home=self.root / "claude-home", **changes)
        return run_block(config, BLOCK, executor=self.executor(scenario), confirm=lambda _s: True)


@pytest.fixture
def box(tmp_path: Path) -> Iterator[ClaudeSandbox]:
    sandbox = ClaudeSandbox(tmp_path)
    sandbox.write_spec(allowed=ALLOWED)
    yield sandbox


def _blocked(report: RunReport, reason: Reason) -> None:
    assert report.result is Result.BLOCKED, report
    assert report.reason is reason, report


def test_documentary_change_is_verified_with_local_commits_only(box: ClaudeSandbox) -> None:
    origin_before = box.origin_refs()
    report = box.run_claude("success")
    assert report.result is Result.VERIFIED_LOCAL, report
    assert report.executor_kind == "claude"
    assert report.executor_version == orchestrator.CLAUDE_VERSION
    assert report.profile == "docs"
    assert [c.path for c in report.changes] == ["docs/permitido.md"]
    assert box.origin_refs() == origin_before
    evidence = (box.worktree / f"docs/orchestration/runs/{BLOCK}.md").read_text(encoding="utf-8")
    assert "`claude`" in evidence and report.executor_session in evidence


def test_real_flags_reach_the_process_and_settings_never_do(box: ClaudeSandbox) -> None:
    assert box.run_claude("success").result is Result.VERIFIED_LOCAL
    calls = [json.loads(line) for line in box.record.read_text(encoding="utf-8").splitlines()]
    main = next(c for c in calls if "--version" not in c["args"])
    for flag in CLAUDE_FROZEN_FLAGS:
        assert flag in main["args"]
    assert "--settings" not in main["args"]
    assert not {n for n in main["env"] if "ANTHROPIC" in n or "TOKEN" in n}


def test_backslash_in_declared_files_is_normalized(box: ClaudeSandbox) -> None:
    assert box.run_claude("success_backslash").result is Result.VERIFIED_LOCAL


def test_no_change_is_accepted(box: ClaudeSandbox) -> None:
    report = box.run_claude("no_change")
    assert report.result is Result.VERIFIED_LOCAL, report
    assert report.profile == "none"


@pytest.mark.parametrize(
    "scenario",
    [
        "extra_tool",
        "missing_tool",
        "mcp_server",
        "additional_directory",
        "skill",
        "slash_command",
        "extra_agent",
        "extra_plugin",
        "permission_mode",
        "api_key",
        "init_version",
        "plugin_other_source",
        "other_model",
        "other_session",
        "other_cwd",
    ],
)
def test_unexpected_capability_kills_the_process_at_once(box: ClaudeSandbox, scenario: str) -> None:
    started = time.monotonic()
    report = box.run_claude(scenario)
    _blocked(report, Reason.CLAUDE_CAPABILITY_MISMATCH)
    assert time.monotonic() - started < 60
    assert report.executor_duration < 30


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        ("wrong_version", Reason.CLAUDE_VERSION_MISMATCH),
        ("version_changes", Reason.CLAUDE_VERSION_MISMATCH),
        ("no_init", Reason.CLAUDE_INIT_MISSING),
        ("no_trace", Reason.CLAUDE_GIT_TRACE_MISSING),
        ("git_push", Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED),
        ("git_write_variant", Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED),
        ("declares_blocked", Reason.EXECUTOR_BLOCKED),
        ("lies_about_files", Reason.CLAUDE_REPORT_MISMATCH),
        ("claims_other_file", Reason.CLAUDE_REPORT_MISMATCH),
        ("out_of_scope", Reason.SCOPE_VIOLATION),
        ("code_edit", Reason.SCOPE_VIOLATION),
        ("commits", Reason.HEAD_MOVED),
        ("no_structured", Reason.INVALID_STRUCTURED_OUTPUT),
        ("extra_field", Reason.INVALID_STRUCTURED_OUTPUT),
        ("free_text_reason", Reason.INVALID_STRUCTURED_OUTPUT),
        ("incoherent", Reason.INVALID_STRUCTURED_OUTPUT),
        ("no_result", Reason.EXECUTOR_FAILED),
        ("is_error", Reason.EXECUTOR_FAILED),
        ("exit_error", Reason.EXECUTOR_FAILED),
        ("token", Reason.SECRET_DETECTED),
        ("uppercase_md", Reason.CODE_PROFILE_FORBIDDEN),
        ("second_init", Reason.CLAUDE_CAPABILITY_MISMATCH),
        ("second_init_buried", Reason.CLAUDE_CAPABILITY_MISMATCH),
        ("unknown_init_field", Reason.CLAUDE_CAPABILITY_MISMATCH),
        ("other_output_style", Reason.CLAUDE_CAPABILITY_MISMATCH),
        ("other_result_session", Reason.CLAUDE_CAPABILITY_MISMATCH),
        ("blocked_after_planting_hook", Reason.REPO_INVARIANT_BROKEN),
        ("exit_after_planting_hook", Reason.REPO_INVARIANT_BROKEN),
        ("blocked_after_out_of_scope", Reason.SCOPE_VIOLATION),
        ("exit_after_push", Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED),
        ("unknown_trace_line", Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED),
    ],
)
def test_claude_scenarios_are_blocked(box: ClaudeSandbox, scenario: str, reason: Reason) -> None:
    head_before = box.main_state()[0]
    origin_before = box.origin_refs()
    report = box.run_claude(scenario)
    _blocked(report, reason)
    assert box.main_state()[0] == head_before
    assert box.origin_refs() == origin_before
    assert not report.content_commit


def test_version_is_checked_before_launching_anything(box: ClaudeSandbox) -> None:
    _blocked(box.run_claude("wrong_version"), Reason.CLAUDE_VERSION_MISMATCH)
    calls = box.record.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1 and "--version" in calls[0]


def test_code_profile_is_forbidden_even_if_scope_allowed_it(box: ClaudeSandbox) -> None:
    box.write_spec(allowed="[docs/permitido.md, scripts/nuevo.py]")
    report = box.run_claude("code_edit")
    _blocked(report, Reason.INVALID_SPEC)
    assert report.detail == "claude_docs_only"


def test_non_documentary_spec_is_refused_before_creating_anything(box: ClaudeSandbox) -> None:
    box.write_spec(allowed="[docs/**]")
    _blocked(box.run_claude("success"), Reason.INVALID_SPEC)
    assert not box.worktree.exists()
    assert _git(box.repo, "branch", "--list", "claude/t1-1-prueba") == ""


def test_missing_first_event_is_cut_after_its_own_deadline(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orchestrator, "CLAUDE_INIT_TIMEOUT_SECONDS", 2.0)
    report = box.run_claude("no_init_hang")
    _blocked(report, Reason.CLAUDE_INIT_MISSING)
    assert report.executor_duration < 30


def test_unexpected_user_settings_stop_before_launching(box: ClaudeSandbox) -> None:
    home = box.root / "claude-home"
    home.mkdir()
    (home / "settings.json").write_text('{"hooks": {}}', encoding="utf-8")
    _blocked(box.run_claude("success"), Reason.CLAUDE_USER_SETTINGS_UNEXPECTED)
    assert not box.record.exists()


def test_timeout_kills_a_hanging_claude(box: ClaudeSandbox) -> None:
    report = box.run_claude("hang", executor_timeout_seconds=3.0)
    _blocked(report, Reason.EXECUTOR_TIMEOUT)
    assert report.executor_duration < 20


def test_timeout_kills_a_child_of_claude(box: ClaudeSandbox, tmp_path: Path) -> None:
    heartbeat = tmp_path / "beat"
    report = box.run_claude(
        "hang_with_child",
        executor_timeout_seconds=3.0,
        extra_env={**box.config.extra_env, "FAKE_CLAUDE_HEARTBEAT": str(heartbeat)},
    )
    _blocked(report, Reason.EXECUTOR_TIMEOUT)
    assert heartbeat.exists()
    first = heartbeat.read_text(encoding="utf-8")
    time.sleep(0.5)
    assert heartbeat.read_text(encoding="utf-8") == first


def test_excessive_output_is_cut(box: ClaudeSandbox) -> None:
    report = box.run_claude("flood", max_executor_output=256 * 1024)
    _blocked(report, Reason.EXECUTOR_OUTPUT_TOO_LARGE)


def test_logs_do_not_keep_known_secrets(box: ClaudeSandbox) -> None:
    report = box.run_claude("token")
    _blocked(report, Reason.SECRET_DETECTED)
    assert report.run_dir is not None
    token = "ghp_" + "d" * 36
    for path in report.run_dir.iterdir():
        if path.is_file():
            assert token not in path.read_text(encoding="utf-8", errors="replace"), path.name
