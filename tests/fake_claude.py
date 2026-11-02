"""Un Claude Code de mentira que habla el mismo `stream-json`, lanzado como proceso real.

Los eventos imitan los observados con la versión real en O1.3.1 y O1.3.3. No usa la red
ni llama a ningún modelo. Uso: ``python fake_claude.py <escenario> <registro> <argumentos>``.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

VERSION = "2.1.316"
ALLOWED_FILE = "docs/permitido.md"
INIT: dict[str, Any] = {
    "type": "system",
    "subtype": "init",
    "uuid": "00000000-0000-0000-0000-000000000000",
    "powershell_path": "powershell.exe",
    "analytics_disabled": True,
    "capabilities": [
        "interrupt_receipt_v1",
        "interrupt_cancel_queued_v1",
        "interrupt_send_now_v1",
        "interrupt_requeue_taken_v1",
        "msg_lifecycle_v1",
        "request_marker_lists_v1",
        "ask_user_question_unanswered_v1",
        "lifecycle_wakeup_source_v1",
        "sdk_mcp_tools_list_changed",
        "sdk_mcp_manifests",
        "mcp_read_resource_v1",
        "mcp_tool_ui_meta_v1",
        "ui_surface_v1",
        "mcp_call_result_not_for_model_v1",
    ],
    "fast_mode_disabled_reason": "sdk_opt_in_required",
    "fast_mode_state": "off",
    "output_style": "default",
    "per_turn_effort_active": True,
    "product_feedback_disabled": True,
    "ultrathink_available": False,
    "view_mode": "default",
    "claude_code_version": VERSION,
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
GIT_TRACE_OK = [
    "git version",
    "git status --short --ignore-submodules=dirty",
    "git log --oneline -n 5",
    "git config user.name",
    "git remote",
    "git ls-files --error-unmatch -- ':(icase).claude/settings.local.json'",
]
INIT_CHANGES: dict[str, tuple[str, Any]] = {
    "extra_tool": ("tools", [*INIT["tools"], "Bash"]),
    "unknown_init_field": ("hooks", ["x"]),
    "other_output_style": ("output_style", "otro"),
    "missing_tool": ("tools", ["Edit", "Glob", "Grep", "Read", "Write"]),
    "mcp_server": ("mcp_servers", [{"name": "x", "status": "connected"}]),
    "additional_directory": ("additional_directories", ["C:/otra"]),
    "skill": ("skills", ["debug"]),
    "slash_command": ("slash_commands", ["debug"]),
    "extra_agent": ("agents", [*INIT["agents"], "otro"]),
    "extra_plugin": ("plugins", [*INIT["plugins"], {"name": "otro", "source": "otro@builtin"}]),
    "plugin_other_source": (
        "plugins",
        [
            {"name": "cc-plugin-agents-md", "source": "cc-plugin-agents-md@otro"},
            INIT["plugins"][1],
        ],
    ),
    "other_model": ("model", "claude-opus-5-5"),
    "other_session": ("session_id", "otra"),
    "other_cwd": ("cwd", "C:/otra"),
    "permission_mode": ("permissionMode", "acceptEdits"),
    "api_key": ("apiKeySource", "ANTHROPIC_API_KEY"),
    "init_version": ("claude_code_version", "9.9.9"),
}


def emit(event: dict) -> None:
    print(json.dumps(event), flush=True)


def trace(*commands: str) -> None:
    path = os.environ.get("GIT_TRACE")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            for command in commands:
                handle.write(
                    f"12:00:00.000000 git.c:476               trace: built-in: {command}\n"
                )


SESSION: dict[str, str] = {}


def result(output: object, **extra: object) -> None:
    emit(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "structured_output": output,
            "session_id": SESSION.get("id"),
            **extra,
        }
    )


def write_allowed(text: str = "Prueba controlada.\n") -> None:
    Path(ALLOWED_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(ALLOWED_FILE).write_text(text, encoding="utf-8", newline="\n")


def ok_output(files: list[str] | None = None) -> dict:
    return {
        "result": "done",
        "files_changed": files if files is not None else [ALLOWED_FILE],
        "blocked": False,
        "reason": "done_ok",
    }


def main() -> int:
    scenario, record = sys.argv[1], Path(sys.argv[2])
    args = sys.argv[3:]
    with open(record, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"args": args, "env": sorted(os.environ)}) + "\n")
    if "--version" in args:
        calls = sum(
            1 for line in record.read_text(encoding="utf-8").splitlines() if "--version" in line
        )
        changed = scenario == "wrong_version" or (scenario == "version_changes" and calls > 1)
        print(f"{'9.9.9' if changed else VERSION} (Claude Code)", flush=True)
        return 0

    if scenario == "no_init_hang":
        time.sleep(600)
        return 0
    if scenario == "no_init":
        SESSION["id"] = args[args.index("--session-id") + 1]
        trace(*GIT_TRACE_OK)
        write_allowed()
        result(ok_output())
        return 0

    SESSION["id"] = args[args.index("--session-id") + 1]
    init: dict[str, Any] = {
        **copy.deepcopy(INIT),
        "session_id": SESSION["id"],
        "cwd": os.getcwd(),
        "original_cwd": os.getcwd(),
    }
    if scenario in INIT_CHANGES:
        key, value = INIT_CHANGES[scenario]
        init[key] = value
    emit({"type": "system", "subtype": "ui_invalidate"})
    emit(init)
    if scenario in INIT_CHANGES:
        # Si el runner no lo corta, este proceso seguiría haciendo daño.
        Path("docs").mkdir(exist_ok=True)
        time.sleep(600)
        return 0

    if scenario == "no_trace":
        write_allowed()
        result(ok_output())
        return 0
    if scenario == "git_push":
        trace(*GIT_TRACE_OK, "git push origin main")
        write_allowed()
        result(ok_output())
        return 0
    if scenario == "git_write_variant":
        trace(*GIT_TRACE_OK, "git status")
        write_allowed()
        result(ok_output())
        return 0

    trace(*GIT_TRACE_OK)
    if scenario in ("success", "version_changes"):
        write_allowed()
        result(ok_output())
    elif scenario == "success_backslash":
        write_allowed()
        result(ok_output(["docs\\permitido.md"]))
    elif scenario == "no_change":
        result(ok_output([]))
    elif scenario == "declares_blocked":
        result({"result": "blocked", "files_changed": [], "blocked": True, "reason": "needs_human"})
    elif scenario == "lies_about_files":
        write_allowed()
        result(ok_output([]))
    elif scenario == "claims_other_file":
        write_allowed()
        result(ok_output([ALLOWED_FILE, "docs/otro.md"]))
    elif scenario == "out_of_scope":
        write_allowed()
        Path("docs/fuera.md").write_text("fuera\n", encoding="utf-8")
        result(ok_output())
    elif scenario == "code_edit":
        Path("scripts").mkdir(exist_ok=True)
        Path("scripts/nuevo.py").write_text("VALUE = 1\n", encoding="utf-8")
        result(ok_output(["scripts/nuevo.py"]))
    elif scenario == "commits":
        write_allowed()
        subprocess.run(["git", "add", "--", ALLOWED_FILE], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "chore: x", "--no-verify"], check=True, capture_output=True
        )
        result(ok_output())
    elif scenario == "token":
        write_allowed('token = "ghp_' + "d" * 36 + '"\n')
        result(ok_output())
    elif scenario == "uppercase_md":
        Path("docs").mkdir(exist_ok=True)
        Path("docs/PERMITIDO.MD").write_text("x\n", encoding="utf-8", newline="\n")
        result(ok_output(["docs/PERMITIDO.MD"]))
    elif scenario == "second_init":
        write_allowed()
        emit({**init, "tools": [*init["tools"], "Bash"]})
        result(ok_output())
    elif scenario == "second_init_buried":
        write_allowed()
        emit({**init, "tools": [*init["tools"], "Bash"]})
        # Más que el final del log que se conserva: no debe depender de ese final.
        for _ in range(2200):
            emit({"type": "assistant", "message": "x" * 1024})
        result(ok_output())
    elif scenario == "other_result_session":
        write_allowed()
        result(ok_output(), session_id="otra")
    elif scenario == "blocked_after_planting_hook":
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], check=True, capture_output=True, text=True
        ).stdout.strip()
        Path(common, "hooks", "post-commit").write_text("#!/bin/sh\n", encoding="utf-8")
        result({"result": "blocked", "files_changed": [], "blocked": True, "reason": "needs_human"})
    elif scenario == "exit_after_planting_hook":
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], check=True, capture_output=True, text=True
        ).stdout.strip()
        Path(common, "hooks", "post-commit").write_text("#!/bin/sh\n", encoding="utf-8")
        return 3
    elif scenario == "blocked_after_out_of_scope":
        Path("docs/fuera.md").write_text("fuera\n", encoding="utf-8")
        result({"result": "blocked", "files_changed": [], "blocked": True, "reason": "needs_human"})
    elif scenario == "exit_after_push":
        trace("git push origin main")
        return 3
    elif scenario == "unknown_trace_line":
        path = os.environ["GIT_TRACE"]
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("linea que no es de traza\n")
        write_allowed()
        result(ok_output())
    elif scenario == "no_structured":
        write_allowed()
        result(None)
    elif scenario == "extra_field":
        write_allowed()
        result({**ok_output(), "command": "x"})
    elif scenario == "free_text_reason":
        write_allowed()
        result({**ok_output(), "reason": "texto libre con espacios"})
    elif scenario == "incoherent":
        write_allowed()
        result({**ok_output(), "blocked": True})
    elif scenario == "no_result":
        write_allowed()
    elif scenario == "is_error":
        emit({"type": "result", "subtype": "error", "is_error": True})
    elif scenario == "exit_error":
        return 3
    elif scenario == "hang":
        time.sleep(600)
    elif scenario == "hang_with_child":
        heartbeat = os.environ["FAKE_CLAUDE_HEARTBEAT"]
        code = (
            "import pathlib, time\n"
            "count = 0\n"
            "while True:\n"
            "    count += 1\n"
            f"    pathlib.Path({heartbeat!r}).write_text(str(count), encoding='utf-8')\n"
            "    time.sleep(0.05)\n"
        )
        subprocess.Popen([sys.executable, "-c", code]).wait()
    elif scenario == "flood":
        while True:
            print("x" * 1024, flush=False)
    else:
        print(f"unknown scenario: {scenario}", file=sys.stderr)
        return 64
    return 0


if __name__ == "__main__":
    sys.exit(main())
