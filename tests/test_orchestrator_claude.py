"""El contrato del ejecutor Claude real, sin Claude real: corre también en CI.

Un Claude falso habla el mismo `stream-json` como proceso de verdad. Las pruebas con la
versión real, que consumen uso y solo corren a mano, están en
``test_orchestrator_claude_live.py``.
"""

from __future__ import annotations

import ast
import hashlib
import json
import sys
import time
from collections.abc import Iterator
from dataclasses import fields, replace
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
        ("tools", [*GOOD_INIT["tools"], "Bash"], "not_a_file_tool"),
        ("tools", [*GOOD_INIT["tools"], "PowerShell"], "not_a_file_tool"),
        ("tools", [*GOOD_INIT["tools"], "WebFetch"], "not_a_file_tool"),
        ("tools", [*GOOD_INIT["tools"], "WebSearch"], "not_a_file_tool"),
        ("tools", [*GOOD_INIT["tools"], "Task"], "not_a_file_tool"),
        ("tools", ["Read"], "tools"),
        ("tools", ["Read", "Read", "Edit", "Glob", "Grep", "Write"], "tools"),
        ("tools", None, "not_a_file_tool"),
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
    assert watcher.error.detail == "not_a_file_tool"


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
    assert watcher.error.detail == "not_a_file_tool"


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"plugins": ["x"]}, "plugins"),
        ({"tools": ["Read", 1]}, "not_a_file_tool"),
        ({"agents": ["Read", 1]}, "TypeError"),
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
    assert watcher.error.reason is Reason.EXECUTOR_OUTPUT_TOO_LARGE
    assert watcher.error.detail == "log_too_large"


def test_capability_seen_before_the_reading_limit_keeps_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = {**GOOD_INIT, "cwd": str(tmp_path), "original_cwd": str(tmp_path)}
    bad = json.dumps({**good, "tools": ["Bash"]})
    monkeypatch.setattr(orchestrator, "MAX_EXECUTOR_OUTPUT_BYTES", len(bad) + 1)
    watcher = _watcher_on(tmp_path, f"{bad}\n{bad}\n".encode())
    assert watcher() is True
    assert watcher.error is not None
    assert watcher.error.reason is Reason.CLAUDE_CAPABILITY_MISMATCH
    assert watcher.error.detail == "not_a_file_tool"


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
        config = replace(
            self.config,
            claude_home=self.root / "claude-home",
            claude_managed_dir=self.root / "managed",
            **changes,
        )
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


def test_flood_beyond_the_reading_limit_is_still_output_too_large(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    # En Linux, entre dos vueltas se escribe más que el tope de lectura: así falló la CI.
    monkeypatch.setattr(orchestrator, "MAX_EXECUTOR_OUTPUT_BYTES", 64 * 1024)
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


# --- Sin consola, por diseño (ADR 0037, §4) -------------------------------------------------

CONSOLE_NAMES = ["Bash", "PowerShell", "cmd", "shell", "bash", "Terminal", "Console"]


def _tool_names(argv: list[str]) -> list[str]:
    names = []
    for option in ("--tools", "--allowedTools", "--disallowedTools"):
        for rule in _option(argv, option).replace(" ", ",").split(","):
            names.append(rule.split("(", 1)[0])
    return names


def test_built_command_only_names_file_tools() -> None:
    argv = _argv()
    assert set(_tool_names(argv)) == {"Read", "Edit", "Write", "Glob", "Grep"}
    lowered = {token.lower() for token in argv}
    assert not lowered & {name.lower() for name in CONSOLE_NAMES}


@pytest.mark.parametrize("option", ["--tools", "--allowedTools", "--disallowedTools"])
@pytest.mark.parametrize(
    "rule",
    [
        "Bash",
        "PowerShell",
        "cmd",
        "shell",
        "bash",
        "Bash(git status)",
        "Bash(C:/Python314/python.exe x.py)",
        "PowerShell(Get-ChildItem)",
        "Task",
        "Agent",
        "WebFetch",
        "NotebookEdit",
        "mcp__x__y",
    ],
)
def test_validator_refuses_any_console_or_non_file_tool(option: str, rule: str) -> None:
    argv = _argv()
    index = argv.index(option) + 1
    for joined in (f"{argv[index]},{rule}", f"{argv[index]} {rule}"):
        bad = [*argv[:index], joined, *argv[index + 1 :]]
        with pytest.raises(BlockedError) as caught:
            validate_claude_argv(bad)
        assert caught.value.reason is Reason.CLAUDE_UNSAFE_COMMAND
        assert caught.value.detail == "not_a_file_tool"


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
def test_changing_the_tool_constant_cannot_add_a_console(
    monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    monkeypatch.setattr(orchestrator, "CLAUDE_TOOLS", (*orchestrator.CLAUDE_TOOLS, tool))
    with pytest.raises(BlockedError) as caught:
        _argv()
    assert caught.value.detail == "not_a_file_tool"


@pytest.mark.parametrize("tool", ["Bash", "PowerShell"])
def test_changing_the_expected_tools_cannot_accept_a_console(
    monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    # Lo que hizo la sonda de O1.3.4, fuera del repositorio: ya no basta.
    tools = sorted([*GOOD_INIT["tools"], tool])
    monkeypatch.setattr(orchestrator, "CLAUDE_EXPECTED_TOOLS", tools)
    with pytest.raises(BlockedError) as caught:
        check_claude_init({**GOOD_INIT, "tools": tools})
    assert caught.value.detail == "not_a_file_tool"


def test_runner_refuses_to_import_with_a_console_tool() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    original = 'CLAUDE_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")'
    assert source.count(original) == 1
    mutated = source.replace(original, original[:-1] + ', "Bash")')
    with pytest.raises(RuntimeError, match="no console"):
        exec(compile(mutated, "orchestrator_mutated", "exec"), {"__name__": "mutated"})


def test_executor_has_no_way_to_add_tools() -> None:
    assert {f.name for f in fields(ClaudeExecutor)} == {"argv_prefix", "kind"}


@pytest.mark.parametrize(
    "prefix",
    [
        ("claude", "--tools", "Bash"),
        ("claude", "--allowedTools=Bash"),
        ("claude", "-p", "x"),
        (),
    ],
)
def test_prefix_cannot_carry_options(prefix: tuple[str, ...]) -> None:
    with pytest.raises(BlockedError) as caught:
        build_claude_argv(prefix, _spec(), "00000000-0000-0000-0000-000000000000")
    assert caught.value.detail == "prefix_option"


def test_prefix_with_options_never_launches_claude(box: ClaudeSandbox) -> None:
    executor = ClaudeExecutor(
        argv_prefix=(sys.executable, str(FAKE_CLAUDE), "success", str(box.record), "--tools")
    )
    config = replace(
        box.config, claude_home=box.root / "claude-home", claude_managed_dir=box.root / "m"
    )
    report = run_block(config, BLOCK, executor=executor, confirm=lambda _s: True)
    _blocked(report, Reason.CLAUDE_UNSAFE_COMMAND)
    calls = box.record.read_text(encoding="utf-8").splitlines()
    assert all("--version" in call for call in calls)


def test_environment_never_names_another_managed_settings_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_MANAGED_SETTINGS_PATH", str(tmp_path))
    config = orchestrator.RunnerConfig(
        repo_root=tmp_path,
        external_root=tmp_path / "ext",
        expected_origin="x",
        tool_python=Path(sys.executable),
        extra_env={"CLAUDE_CODE_MANAGED_SETTINGS_PATH": str(tmp_path)},
    )
    env = orchestrator.build_claude_env(config, tmp_path / "trace", tmp_path / "tmp")
    assert {n for n in env if n.startswith("CLAUDE")} == {
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
    }


def test_managed_settings_option_is_forbidden() -> None:
    assert "--managed-settings" in FORBIDDEN_CLAUDE_OPTIONS


# --- Toda parada del ejecutor real revisa daños --------------------------------------------


def _interrupt_once_init_is_seen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ctrl+C donde de verdad llega: mientras el runner vigila a Claude."""
    original = orchestrator._ClaudeInitWatcher.__call__

    def interrupting(self: orchestrator._ClaudeInitWatcher) -> bool:
        stop = original(self)
        if self.seen:
            raise KeyboardInterrupt
        return stop

    monkeypatch.setattr(orchestrator._ClaudeInitWatcher, "__call__", interrupting)


def _fail_reading_the_log(monkeypatch: pytest.MonkeyPatch) -> None:
    original = orchestrator._run_logged

    def failing(config: Any, argv: list[str], **kwargs: Any) -> Any:
        done = original(config, argv, **kwargs)
        # Solo el log de Claude: el escaneo de secretos también pasa por aquí.
        if "--session-id" in argv:
            raise OSError("log unreadable")
        return done

    monkeypatch.setattr(orchestrator, "_run_logged", failing)


def _stopped(report: RunReport, reason: Reason, primary: Reason, damage: str) -> None:
    _blocked(report, reason)
    assert report.primary_reason is primary, report
    assert report.damage_check == damage, report
    if reason is not primary:
        assert report.detail == f"after_{primary.value}"
    assert report.run_dir is not None
    local = (report.run_dir / "report.md").read_text(encoding="utf-8")
    assert f"`{primary.value}`" in local and f"`{damage}`" in local


def test_ctrl_c_without_damage_keeps_its_reason(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _interrupt_once_init_is_seen(monkeypatch)
    _stopped(box.run_claude("hang"), Reason.INTERRUPTED, Reason.INTERRUPTED, "no_damage")


@pytest.mark.parametrize(
    ("scenario", "reason"),
    [
        ("hook_then_hang", Reason.REPO_INVARIANT_BROKEN),
        ("scope_then_hang", Reason.SCOPE_VIOLATION),
        ("push_then_hang", Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED),
    ],
)
def test_ctrl_c_still_runs_every_damage_check(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch, scenario: str, reason: Reason
) -> None:
    _interrupt_once_init_is_seen(monkeypatch)
    head_before = box.main_state()[0]
    report = box.run_claude(scenario)
    _stopped(report, reason, Reason.INTERRUPTED, reason.value)
    assert box.main_state()[0] == head_before


MISMATCH = Reason.CLAUDE_CAPABILITY_MISMATCH


@pytest.mark.parametrize(
    ("scenario", "reason", "primary"),
    [
        ("hook_then_malformed_init", Reason.REPO_INVARIANT_BROKEN, MISMATCH),
        ("hook_then_extra_tool", Reason.REPO_INVARIANT_BROKEN, MISMATCH),
        ("hook_then_second_init", Reason.REPO_INVARIANT_BROKEN, MISMATCH),
        ("scope_then_extra_field", Reason.SCOPE_VIOLATION, Reason.INVALID_STRUCTURED_OUTPUT),
        ("scope_then_no_structured", Reason.SCOPE_VIOLATION, Reason.INVALID_STRUCTURED_OUTPUT),
        ("scope_then_hang", Reason.SCOPE_VIOLATION, Reason.EXECUTOR_TIMEOUT),
    ],
)
def test_every_stop_runs_the_damage_checks(
    box: ClaudeSandbox, scenario: str, reason: Reason, primary: Reason
) -> None:
    report = box.run_claude(scenario, executor_timeout_seconds=5.0)
    _stopped(report, reason, primary, reason.value)


def test_output_too_large_runs_the_damage_checks(box: ClaudeSandbox) -> None:
    report = box.run_claude("scope_then_flood", max_executor_output=256 * 1024)
    _stopped(report, Reason.SCOPE_VIOLATION, Reason.EXECUTOR_OUTPUT_TOO_LARGE, "scope_violation")


def test_malformed_init_without_damage_keeps_its_reason(box: ClaudeSandbox) -> None:
    report = box.run_claude("malformed_init")
    _stopped(report, MISMATCH, MISMATCH, "no_damage")
    assert report.detail == "unreadable_init"


def test_declared_block_without_damage_keeps_its_reason(box: ClaudeSandbox) -> None:
    report = box.run_claude("declares_blocked")
    _stopped(report, Reason.EXECUTOR_BLOCKED, Reason.EXECUTOR_BLOCKED, "no_damage")


def test_error_reading_the_log_still_runs_the_damage_checks(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_reading_the_log(monkeypatch)
    report = box.run_claude("hook_then_success")
    _stopped(report, Reason.REPO_INVARIANT_BROKEN, Reason.INTERNAL_ERROR, "repo_invariant_broken")


def test_error_reading_the_log_without_damage_is_an_internal_error(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fail_reading_the_log(monkeypatch)
    _stopped(box.run_claude("success"), Reason.INTERNAL_ERROR, Reason.INTERNAL_ERROR, "no_damage")


def test_unreadable_trace_is_not_taken_as_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trace = tmp_path / "trace.log"
    trace.write_text("x", encoding="utf-8")

    def unreadable(*_args: Any, **_kwargs: Any) -> str:
        raise PermissionError("locked")

    monkeypatch.setattr(Path, "read_text", unreadable)
    text = orchestrator._read_claude_trace(trace)
    monkeypatch.undo()
    assert text == "unknown: trace unreadable"
    with pytest.raises(BlockedError) as caught:
        check_git_trace(text, require_commands=False)
    assert caught.value.reason is Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED


def test_damage_check_that_cannot_finish_is_its_own_stop(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(_git: Any) -> list[Change]:
        raise RuntimeError("cannot list changes")

    monkeypatch.setattr(orchestrator, "collect_changes", broken)
    report = box.run_claude("declares_blocked")
    _stopped(report, Reason.DAMAGE_CHECK_FAILED, Reason.EXECUTOR_BLOCKED, "damage_check_failed")


# --- Configuración de Claude: proyecto, local y administrada, por defecto denegada ---------


def _commit_to_main(box: ClaudeSandbox, files: dict[str, str]) -> None:
    for path, text in files.items():
        target = box.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
    _git(box.repo, "add", ".")
    _git(box.repo, "commit", "--quiet", "-m", "chore: x")
    _git(box.repo, "push", "--quiet", "origin", "main")


@pytest.mark.parametrize(
    ("files", "reason"),
    [
        ({".claude/settings.json": "{}"}, Reason.CLAUDE_PROJECT_SETTINGS_PRESENT),
        ({".claude/settings.local.json": "{}"}, Reason.CLAUDE_PROJECT_SETTINGS_PRESENT),
        ({".claude/hooks/x.sh": "x"}, Reason.CLAUDE_PROJECT_SETTINGS_PRESENT),
        ({".claude/commands/x.md": "x"}, Reason.CLAUDE_PROJECT_SETTINGS_PRESENT),
        ({".Claude/Settings.json": "{}"}, Reason.CLAUDE_PROJECT_SETTINGS_PRESENT),
        ({"docs/.claude/skills/x.md": "x"}, Reason.CLAUDE_PROJECT_SETTINGS_PRESENT),
        ({".mcp.json": "{}"}, Reason.CLAUDE_PROJECT_MCP_PRESENT),
        ({"docs/.mcp.json": "{}"}, Reason.CLAUDE_PROJECT_MCP_PRESENT),
    ],
)
def test_project_configuration_stops_before_launching(
    box: ClaudeSandbox, files: dict[str, str], reason: Reason
) -> None:
    _commit_to_main(box, files)
    _blocked(box.run_claude("success"), reason)
    assert not box.record.exists()


def test_project_agents_and_skills_are_accepted(box: ClaudeSandbox) -> None:
    _commit_to_main(box, {".claude/agents/x.md": "x\n", ".claude/skills/y/SKILL.md": "y\n"})
    assert box.run_claude("success").result is Result.VERIFIED_LOCAL


def _plain_git(tmp_path: Path) -> tuple[orchestrator.RunnerConfig, orchestrator.Git]:
    repo = tmp_path / "parent" / "repo"
    repo.mkdir(parents=True)
    _git(repo.parent, "init", "--quiet", str(repo))
    config = orchestrator.RunnerConfig(
        repo_root=repo,
        external_root=tmp_path / "ext",
        expected_origin="x",
        tool_python=Path(sys.executable),
        claude_home=tmp_path / "claude-home",
    )
    return config, orchestrator.Git(config, repo)


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        (".mcp.json", Reason.CLAUDE_PROJECT_MCP_PRESENT),
        (".claude/settings.json", Reason.CLAUDE_PROJECT_SETTINGS_PRESENT),
        (".claude/settings.local.json", Reason.CLAUDE_PROJECT_SETTINGS_PRESENT),
    ],
)
def test_configuration_in_an_enclosing_folder_also_stops(
    tmp_path: Path, path: str, reason: Reason
) -> None:
    config, git = _plain_git(tmp_path)
    target = tmp_path / "parent" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(BlockedError) as caught:
        orchestrator.check_claude_project_settings(config, git)
    assert caught.value.reason is reason
    assert caught.value.detail == "folder"


def test_untracked_project_settings_also_stop(tmp_path: Path) -> None:
    config, git = _plain_git(tmp_path)
    (git.cwd / ".claude").mkdir()
    (git.cwd / ".claude" / "settings.local.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BlockedError) as caught:
        orchestrator.check_claude_project_settings(config, git)
    assert caught.value.reason is Reason.CLAUDE_PROJECT_SETTINGS_PRESENT


def _managed_config(tmp_path: Path) -> orchestrator.RunnerConfig:
    return orchestrator.RunnerConfig(
        repo_root=tmp_path,
        external_root=tmp_path / "ext",
        expected_origin="x",
        tool_python=Path(sys.executable),
        claude_home=tmp_path / "claude-home",
        claude_managed_dir=tmp_path / "managed",
    )


def test_no_managed_configuration_passes(tmp_path: Path) -> None:
    orchestrator.check_claude_managed_settings(_managed_config(tmp_path))


@pytest.mark.parametrize(
    "entry", ["managed-settings.json", "managed-settings.d", "managed-mcp.json"]
)
def test_any_managed_folder_stops_without_reading_it(tmp_path: Path, entry: str) -> None:
    config = _managed_config(tmp_path)
    assert config.claude_managed_dir is not None
    config.claude_managed_dir.mkdir()
    (config.claude_managed_dir / entry).write_text("no se lee", encoding="utf-8")
    with pytest.raises(BlockedError) as caught:
        orchestrator.check_claude_managed_settings(config)
    assert caught.value.reason is Reason.CLAUDE_MANAGED_SETTINGS_PRESENT
    assert caught.value.detail == "managed_dir"


def test_policy_registry_keys_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "claude_policy_keys", lambda: ["HKLM"])
    with pytest.raises(BlockedError) as caught:
        orchestrator.check_claude_managed_settings(_managed_config(tmp_path))
    assert caught.value.detail == "policy_registry"


@pytest.mark.parametrize("name", orchestrator.CLAUDE_REMOTE_SETTINGS_FILES)
def test_remote_managed_cache_stops(tmp_path: Path, name: str) -> None:
    config = _managed_config(tmp_path)
    assert config.claude_home is not None
    config.claude_home.mkdir()
    (config.claude_home / name).write_text("{}", encoding="utf-8")
    with pytest.raises(BlockedError) as caught:
        orchestrator.check_claude_managed_settings(config)
    assert caught.value.detail == "remote_settings"


def test_managed_sources_are_the_ones_read_from_the_binary() -> None:
    assert orchestrator.CLAUDE_MANAGED_DIRS["win32"] == Path(r"C:\Program Files\ClaudeCode")
    assert orchestrator.CLAUDE_POLICY_KEY == r"SOFTWARE\Policies\ClaudeCode"


def test_registry_probe_is_empty_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator.sys, "platform", "linux")
    assert orchestrator.claude_policy_keys() == []


def test_alternate_user_settings_stop(tmp_path: Path) -> None:
    config = _managed_config(tmp_path)
    assert config.claude_home is not None
    config.claude_home.mkdir()
    (config.claude_home / "cowork_settings.json").write_text("{}", encoding="utf-8")
    with pytest.raises(BlockedError) as caught:
        orchestrator.check_claude_user_settings(config)
    assert caught.value.detail == "alternate_settings"


def test_managed_configuration_stops_before_launching(box: ClaudeSandbox) -> None:
    (box.root / "managed").mkdir()
    _blocked(box.run_claude("success"), Reason.CLAUDE_MANAGED_SETTINGS_PRESENT)
    assert not box.record.exists()


def test_remote_managed_cache_appearing_during_the_run_stops(box: ClaudeSandbox) -> None:
    home = box.root / "claude-home"
    home.mkdir()
    report = box.run_claude(
        "remote_settings_appear",
        extra_env={
            **box.config.extra_env,
            "FAKE_CLAUDE_REMOTE_SETTINGS": str(home / "remote-settings.json"),
        },
    )
    _blocked(report, Reason.CLAUDE_MANAGED_SETTINGS_PRESENT)
    assert not report.content_commit


# --- Correcciones de la revisión de seguridad de O1.3.5 -------------------------------------


def test_forbidden_git_command_outranks_configuration_after_a_stop(box: ClaudeSandbox) -> None:
    home = box.root / "claude-home"
    home.mkdir()
    report = box.run_claude(
        "push_then_remote_settings_appear",
        extra_env={
            **box.config.extra_env,
            "FAKE_CLAUDE_REMOTE_SETTINGS": str(home / "remote-settings.json"),
        },
    )
    _stopped(
        report,
        Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED,
        Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED,
        "claude_git_command_not_allowed",
    )


def test_real_claude_refuses_paths_meant_for_the_fake_one(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Si la barrera fallara, el test no debe llegar nunca a lanzar el Claude real.
    def never(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the real Claude must not be launched")

    monkeypatch.setattr(orchestrator, "claude_prefix", never)
    monkeypatch.setattr(orchestrator, "check_claude_version", never)
    monkeypatch.setattr(orchestrator, "claude_policy_keys", lambda: [])
    config = replace(
        box.config, claude_home=box.root / "claude-home", claude_managed_dir=box.root / "m"
    )
    report = run_block(config, BLOCK, executor=ClaudeExecutor(), confirm=lambda _s: True)
    _blocked(report, Reason.CLAUDE_UNSAFE_COMMAND)
    assert report.detail == "test_only_paths"


def test_a_second_ctrl_c_during_the_damage_check_is_reported(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted(_git: Any) -> list[Change]:
        raise KeyboardInterrupt

    monkeypatch.setattr(orchestrator, "collect_changes", interrupted)
    report = box.run_claude("declares_blocked")
    _blocked(report, Reason.INTERRUPTED)
    assert report.primary_reason is Reason.EXECUTOR_BLOCKED
    assert report.damage_check == "interrupted"
    assert report.run_dir is not None
    assert "`interrupted`" in (report.run_dir / "report.md").read_text(encoding="utf-8")


def test_trace_never_read_is_not_taken_as_clean(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Un segundo Ctrl+C justo cuando se iba a leer la traza.
    def interrupted(_path: Path) -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr(orchestrator, "_read_claude_trace", interrupted)
    report = box.run_claude("success")
    _stopped(
        report,
        Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED,
        Reason.INTERRUPTED,
        "claude_git_command_not_allowed",
    )


def test_a_tree_that_does_not_empty_after_a_stop_is_an_orphan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(orchestrator, "_wait_until_empty", lambda _tree, _seconds: False)

    def interrupt() -> bool:
        raise KeyboardInterrupt

    with open(tmp_path / "out.log", "wb") as out, pytest.raises(BlockedError) as caught:
        orchestrator.run_process(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=tmp_path,
            env=dict(orchestrator.build_env(_managed_config(tmp_path))),
            timeout=30.0,
            stdout=out,
            kill_wait=1.0,
            on_poll=interrupt,
        )
    assert caught.value.reason is Reason.ORPHAN_SUSPECTED
    assert caught.value.detail == "after_stop"
    assert isinstance(caught.value.__cause__, KeyboardInterrupt)


# --- Repositorio real: autorización de un solo uso (ADR 0037, §9) --------------------------

REAL_BRANCH = "claude/t1-1-prueba"


class RealBox:
    """El sandbox hace de repositorio real: solo cambia `EXPECTED_ORIGIN`, y solo en el test.

    El Claude real nunca se lanza: `claude_prefix` devuelve el Claude falso, y el ejecutor
    sigue siendo el real, sin prefijo, como en un run de verdad.
    """

    def __init__(self, box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch) -> None:
        self.box = box
        self.monkeypatch = monkeypatch
        self.config_checks = 0
        monkeypatch.setattr(orchestrator, "EXPECTED_ORIGIN", box.config.expected_origin)

        def configuration(_config: Any, _git: Any) -> None:
            # La configuración real de esta máquina no es la del test; su control tiene tests.
            self.config_checks += 1

        monkeypatch.setattr(orchestrator, "check_claude_configuration", configuration)

    @property
    def authorization_path(self) -> Path:
        return self.box.config.authorizations / f"{BLOCK}.json"

    @property
    def used_path(self) -> Path:
        return self.box.config.used_authorizations / f"{BLOCK}.json"

    def spec_sha256(self) -> str:
        raw = (self.box.config.inbox / f"{BLOCK}.md").read_bytes()
        return hashlib.sha256(raw).hexdigest()

    def authorize(self, *, drop: tuple[str, ...] = (), **changes: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema": orchestrator.REAL_RUN_AUTHORIZATION_SCHEMA,
            "block_id": BLOCK,
            "repository": "VallejoOsorio2026/Elsa-ai",
            "base_sha": _git(self.box.repo, "rev-parse", "HEAD"),
            "spec_sha256": self.spec_sha256(),
            "branch": REAL_BRANCH,
            "allowed_paths": ["docs/permitido.md"],
            "change": "add",
            "profile": "docs",
            "executor": "claude",
            "console": False,
        }
        data.update(changes)
        for name in drop:
            del data[name]
        self.write(json.dumps(data))
        return data

    def write(self, text: str) -> None:
        self.authorization_path.parent.mkdir(parents=True, exist_ok=True)
        self.authorization_path.write_text(text, encoding="utf-8")

    def run(self, scenario: str = "success", executor: ClaudeExecutor | None = None) -> RunReport:
        prefix = (sys.executable, str(FAKE_CLAUDE), scenario, str(self.box.record))
        self.monkeypatch.setattr(orchestrator, "claude_prefix", lambda _c, _e: prefix)
        return run_block(
            self.box.config,
            BLOCK,
            executor=executor or ClaudeExecutor(),
            confirm=lambda _s: True,
        )

    def nothing_created(self) -> None:
        assert not self.box.worktree.exists()
        assert _git(self.box.repo, "branch", "--list", REAL_BRANCH) == ""
        assert not self.box.record.exists()


@pytest.fixture
def real(box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch) -> RealBox:
    return RealBox(box, monkeypatch)


def test_real_repository_name_is_bound_to_the_expected_origin() -> None:
    assert orchestrator.normalized_origin(orchestrator.EXPECTED_ORIGIN) == (
        orchestrator.REAL_REPOSITORY.lower()
    )


def test_exact_authorization_reaches_verified_local_once(real: RealBox) -> None:
    head_before = real.box.main_state()
    origin_before = real.box.origin_refs()
    real.authorize()
    report = real.run()
    assert report.result is Result.VERIFIED_LOCAL, report
    assert report.real_run_authorized
    assert [(c.path, c.status) for c in report.changes] == [("docs/permitido.md", "A")]
    # Un solo uso: retirada antes de crear la copia, y fuera del repositorio.
    assert not real.authorization_path.exists() and real.used_path.exists()
    assert real.config_checks >= 2
    assert real.box.main_state() == head_before
    assert real.box.origin_refs() == origin_before
    evidence = (real.box.worktree / f"docs/orchestration/runs/{BLOCK}.md").read_text(
        encoding="utf-8"
    )
    assert "autorización de un solo uso, consumida" in evidence
    assert report.spec_sha256 in evidence


def test_without_authorization_the_real_repository_stays_closed(real: RealBox) -> None:
    _blocked(real.run(), Reason.REAL_REPO_NOT_AUTHORIZED)
    real.nothing_created()


def test_authorization_is_never_reused(real: RealBox) -> None:
    data = real.authorize()
    assert real.run().result is Result.VERIFIED_LOCAL
    # Aunque alguien vuelva a dejar la misma autorización, ese bloque ya la gastó.
    real.write(json.dumps(data))
    _blocked(real.run(), Reason.REAL_RUN_AUTHORIZATION_USED)


def test_a_stopped_run_still_spends_its_authorization(real: RealBox) -> None:
    real.authorize()
    _blocked(real.run("declares_blocked"), Reason.EXECUTOR_BLOCKED)
    assert real.used_path.exists()
    _blocked(real.run(), Reason.REAL_RUN_AUTHORIZATION_USED)


@pytest.mark.parametrize(
    ("changes", "detail"),
    [
        ({"base_sha": "0" * 40}, "base_sha"),
        ({"repository": "otro/Elsa-ai"}, "repository"),
        ({"repository": "VallejoOsorio2026/otro"}, "repository"),
        ({"spec_sha256": "0" * 64}, "spec_sha256"),
        ({"branch": "claude/t1-1-otra"}, "branch"),
        ({"allowed_paths": ["docs/permitido.md", "docs/otro.md"]}, "allowed_paths"),
        ({"allowed_paths": ["docs/**"]}, "allowed_paths"),
        ({"allowed_paths": ["docs/otro.md"]}, "allowed_paths"),
        ({"block_id": "T1.2"}, "block_id"),
    ],
)
def test_any_difference_with_the_run_stops_before_creating_anything(
    real: RealBox, changes: dict[str, Any], detail: str
) -> None:
    real.authorize(**changes)
    report = real.run()
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_MISMATCH)
    assert report.detail == detail
    real.nothing_created()
    assert real.authorization_path.exists() and not real.used_path.exists()


@pytest.mark.parametrize(
    ("changes", "drop", "detail"),
    [
        ({"console": True}, (), "console"),
        ({"console": 0}, (), "console"),
        ({"console": "false"}, (), "console"),
        ({"profile": "code"}, (), "profile"),
        ({"executor": "fake"}, (), "executor"),
        ({"change": "modify"}, (), "change"),
        ({"schema": "otro/1"}, (), "schema"),
        ({"branch": "main"}, (), "branch"),
        ({"base_sha": "HEAD"}, (), "base_sha"),
        ({"allowed_paths": []}, (), "allowed_paths"),
        ({"allowed_paths": "docs/permitido.md"}, (), "allowed_paths"),
        ({"tools": ["Bash"]}, (), "fields"),
        ({"allow_real_repo": True}, (), "fields"),
        ({}, ("console",), "fields"),
        ({}, ("base_sha",), "fields"),
    ],
)
def test_malformed_authorization_stops_before_creating_anything(
    real: RealBox, changes: dict[str, Any], drop: tuple[str, ...], detail: str
) -> None:
    real.authorize(drop=drop, **changes)
    report = real.run()
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_INVALID)
    assert report.detail == detail
    real.nothing_created()


@pytest.mark.parametrize(
    "text",
    [
        "no es json",
        "[]",
        '{"console": false, "console": true}',
        "x" * (orchestrator.MAX_AUTHORIZATION_BYTES + 1),
    ],
)
def test_unreadable_authorization_stops(real: RealBox, text: str) -> None:
    real.write(text)
    _blocked(real.run(), Reason.REAL_RUN_AUTHORIZATION_INVALID)
    real.nothing_created()


def test_fake_claude_never_works_on_the_real_repository(real: RealBox) -> None:
    real.authorize()
    report = real.run(executor=real.box.executor("success"))
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_MISMATCH)
    assert report.detail == "executor"
    real.nothing_created()


def test_authorization_only_adds_files(real: RealBox) -> None:
    real.box.write_spec(allowed="[docs/existing.md]")
    real.authorize(allowed_paths=["docs/existing.md"])
    report = real.run()
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_MISMATCH)
    assert report.detail == "path_exists"
    real.nothing_created()


def test_every_authorized_file_must_be_created(real: RealBox) -> None:
    real.box.write_spec(allowed="[docs/permitido.md, docs/segundo.md]")
    real.authorize(allowed_paths=["docs/permitido.md", "docs/segundo.md"])
    report = real.run()
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_MISMATCH)
    assert report.detail == "changes"
    assert not report.content_commit


def test_no_change_is_not_what_was_authorized(real: RealBox) -> None:
    real.authorize()
    report = real.run("no_change")
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_MISMATCH)
    assert report.detail == "changes"


def test_a_second_file_stops_the_authorized_run(real: RealBox) -> None:
    real.authorize()
    report = real.run("out_of_scope")
    _blocked(report, Reason.SCOPE_VIOLATION)
    assert not report.content_commit


def test_authorization_changed_after_validation_is_refused(real: RealBox) -> None:
    real.authorize()

    def tamper(_spec: Spec) -> bool:
        real.authorize(base_sha="1" * 40)
        return True

    report = run_block(real.box.config, BLOCK, executor=ClaudeExecutor(), confirm=tamper)
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_INVALID)
    assert report.detail == "changed"
    real.nothing_created()


def test_authorization_for_a_disposable_repository_is_refused(
    box: ClaudeSandbox, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_origin = orchestrator.EXPECTED_ORIGIN
    real = RealBox(box, monkeypatch)
    real.authorize()
    # Sin hacer pasar el sandbox por el repositorio real: la autorización no le corresponde.
    monkeypatch.setattr(orchestrator, "EXPECTED_ORIGIN", real_origin)
    report = real.run()
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_MISMATCH)
    assert report.detail == "repository"
    real.nothing_created()


def _authorization_for(
    config: orchestrator.RunnerConfig, spec: Spec, **changes: Any
) -> orchestrator.RealRunAuthorization:
    """Una autorización que coincide con `spec` y ya está gastada, como tras `consume`."""
    used = config.used_authorizations / f"{spec.id}.json"
    used.parent.mkdir(parents=True, exist_ok=True)
    if not used.exists():
        used.write_text("{}", encoding="utf-8")
    values: dict[str, Any] = {
        "block_id": spec.id,
        "repository": "VallejoOsorio2026/Elsa-ai",
        "base_sha": "0" * 40,
        "spec_sha256": spec.sha256,
        "branch": spec.branch,
        "allowed_paths": spec.allowed_paths,
        "path": config.authorizations / f"{spec.id}.json",
        "raw_sha256": "0" * 64,
        **changes,
    }
    return orchestrator.RealRunAuthorization(**values)


def _target(real: RealBox, spec: Spec, authorization: Any, commit: str = "") -> str:
    with pytest.raises(BlockedError) as caught:
        orchestrator.check_authorized_target(
            real.box.config, real.box.worktree, spec, ClaudeExecutor(), authorization, commit
        )
    assert caught.value.reason is Reason.REAL_RUN_AUTHORIZATION_MISMATCH
    return caught.value.detail


def test_claude_never_targets_the_main_clone(real: RealBox) -> None:
    spec = replace(_spec(), branch=REAL_BRANCH)
    authorization = _authorization_for(real.box.config, spec)
    with pytest.raises(BlockedError) as caught:
        orchestrator.check_authorized_target(
            real.box.config, real.box.repo, spec, ClaudeExecutor(), authorization, ""
        )
    assert caught.value.detail == "worktree"


def test_target_check_does_not_trust_its_caller(real: RealBox) -> None:
    # Una autorización construida a mano, o de otra especificación, tampoco abre nada.
    spec = replace(_spec(), branch=REAL_BRANCH)
    config = real.box.config
    for authorization, detail in (
        (_authorization_for(config, spec, spec_sha256="1" * 64), "spec_sha256"),
        (_authorization_for(config, spec, block_id="T1.2"), "block_id"),
        (_authorization_for(config, spec, allowed_paths=("docs/otro.md",)), "allowed_paths"),
        (_authorization_for(config, spec, branch="claude/t1-1-otra"), "branch"),
    ):
        assert _target(real, spec, authorization) == detail


def test_target_check_requires_a_spent_authorization(real: RealBox) -> None:
    spec = replace(_spec(), branch=REAL_BRANCH)
    authorization = _authorization_for(real.box.config, spec)
    authorization.path.parent.mkdir(parents=True, exist_ok=True)
    authorization.path.write_text("{}", encoding="utf-8")
    assert _target(real, spec, authorization) == "not_consumed"
    authorization.path.unlink()
    (real.box.config.used_authorizations / f"{spec.id}.json").unlink()
    assert _target(real, spec, authorization) == "not_consumed"


def test_claude_targets_only_its_branch_on_the_authorized_base(real: RealBox) -> None:
    real.authorize()
    report = real.run()
    assert report.result is Result.VERIFIED_LOCAL
    head = _git(real.box.worktree, "rev-parse", "HEAD")
    other = replace(_spec(), branch="claude/t1-1-otra")
    assert _target(real, other, _authorization_for(real.box.config, other)) == "branch"
    spec = replace(_spec(), branch=REAL_BRANCH)
    authorization = _authorization_for(real.box.config, spec, base_sha=report.base_sha)
    # Tras el run, HEAD ya no es el commit de la especificación, ni su padre la base.
    assert _target(real, spec, authorization, report.spec_commit) == "spec_commit"
    assert _target(real, spec, authorization, head) == "base_sha"


def test_target_check_refuses_another_executor(real: RealBox) -> None:
    spec = replace(_spec(), branch=REAL_BRANCH)
    with pytest.raises(BlockedError) as caught:
        orchestrator.check_authorized_target(
            real.box.config,
            real.box.worktree,
            spec,
            real.box.executor("success"),
            _authorization_for(real.box.config, spec),
            "",
        )
    assert caught.value.detail == "executor"


def test_authorization_that_is_not_a_file_stops(real: RealBox) -> None:
    real.authorization_path.mkdir(parents=True)
    report = real.run()
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_INVALID)
    assert report.detail == "not_a_file"
    real.nothing_created()


def test_authorization_removed_after_validation_stops(real: RealBox) -> None:
    real.authorize()

    def remove(_spec: Spec) -> bool:
        real.authorization_path.unlink()
        return True

    report = run_block(real.box.config, BLOCK, executor=ClaudeExecutor(), confirm=remove)
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_INVALID)
    assert report.detail == "unreadable"
    real.nothing_created()


def test_existing_file_with_other_case_is_not_new(real: RealBox) -> None:
    real.box.write_spec(allowed="[docs/Existing.md]")
    real.authorize(allowed_paths=["docs/Existing.md"])
    report = real.run()
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_MISMATCH)
    assert report.detail == "path_exists"


def test_authorized_mode_accepts_no_other_spelling_of_the_remote(real: RealBox) -> None:
    # Normalizar sirve para rechazar; para permitir, ni otro anfitrión.
    _git(real.box.repo, "config", "remote.origin.pushurl", "https://otro/VallejoOsorio2026/Elsa-ai")
    real.authorize()
    report = real.run()
    _blocked(report, Reason.REAL_RUN_AUTHORIZATION_MISMATCH)
    assert report.detail == "repository"
    real.nothing_created()


@pytest.mark.parametrize(
    ("scenario", "primary"),
    [("plant_then_success", None), ("plant_then_declares_blocked", Reason.EXECUTOR_BLOCKED)],
)
def test_anything_planted_in_the_runner_folders_stops(
    box: ClaudeSandbox, scenario: str, primary: Reason | None
) -> None:
    planted = box.config.authorizations / "T9.9.json"
    report = box.run_claude(
        scenario, extra_env={**box.config.extra_env, "FAKE_CLAUDE_PLANT": str(planted)}
    )
    _blocked(report, Reason.REPO_INVARIANT_BROKEN)
    assert report.detail.startswith("runner_folders") or report.detail.startswith("after_")
    assert report.primary_reason is primary
    assert not report.content_commit


def test_authorized_changes_must_be_exactly_the_new_files() -> None:
    authorization = orchestrator.RealRunAuthorization(
        block_id=BLOCK,
        repository="VallejoOsorio2026/Elsa-ai",
        base_sha="0" * 40,
        spec_sha256="0" * 64,
        branch=REAL_BRANCH,
        allowed_paths=("docs/permitido.md",),
        path=Path("x.json"),
        raw_sha256="0" * 64,
    )
    orchestrator.check_authorized_changes(authorization, [Change("docs/permitido.md", "A")])
    for changes in (
        [Change("docs/permitido.md", "M")],
        [Change("docs/permitido.md", "A"), Change("docs/otro.md", "A")],
        [],
    ):
        with pytest.raises(BlockedError):
            orchestrator.check_authorized_changes(authorization, changes)
