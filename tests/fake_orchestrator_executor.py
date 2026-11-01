"""Un ejecutor de mentira para probar el runner, lanzado como proceso de verdad.

Con un doble en memoria no se podría comprobar lo que importa: que el plazo mata
de verdad un proceso y a sus hijos, y que un ejecutor que miente no engaña al
runner. No llama a Claude, no usa la red y solo toca su carpeta de trabajo.

Uso: ``python fake_orchestrator_executor.py <escenario> [archivo_de_latido]``.
"""

from __future__ import annotations

import json
import os
import secrets
import string
import subprocess
import sys
import time
from pathlib import Path

ALLOWED_FILE = "docs/fake-edit.md"
ALLOWED_CODE_FILE = "scripts/rehearsal_probe.py"
OUT_OF_SCOPE_FILE = "other/out-of-scope.md"
FORBIDDEN_FILE = "CLAUDE.md"
IGNORED_FILE = "ignored.txt"


def _report(status: str = "done", reason: str | None = None) -> None:
    print(json.dumps({"status": status, "reason_code": reason}), flush=True)


def _write(path: str, content: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="\n")


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _common_dir() -> Path:
    output = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], check=True, capture_output=True, text=True
    )
    return Path(output.stdout.strip()).resolve()


def _heartbeat_forever(path: str) -> None:
    count = 0
    while True:
        count += 1
        Path(path).write_text(str(count), encoding="utf-8")
        time.sleep(0.05)


def _spawn_grandchild(path: str) -> subprocess.Popen[bytes]:
    code = (
        "import pathlib, time\n"
        "count = 0\n"
        "while True:\n"
        "    count += 1\n"
        f"    pathlib.Path({path!r}).write_text(str(count), encoding='utf-8')\n"
        "    time.sleep(0.05)\n"
    )
    return subprocess.Popen([sys.executable, "-c", code])


def main() -> int:
    scenario = sys.argv[1]
    heartbeat = sys.argv[2] if len(sys.argv) > 2 else ""

    if scenario == "success_no_change":
        _report()
    elif scenario == "edit_allowed":
        _write(ALLOWED_FILE, "# Edición permitida\n")
        _report()
    elif scenario == "edit_allowed_code":
        _write(ALLOWED_CODE_FILE, '"""Sonda del ensayo de O1.2."""\n\nVALUE = 1\n')
        _report()
    elif scenario == "delete_allowed":
        os.remove("docs/existing.md")
        _report()
    elif scenario == "rename_out_of_scope":
        Path("other").mkdir(exist_ok=True)
        os.replace("docs/existing.md", "other/moved.md")
        _report()
    elif scenario == "edit_out_of_scope":
        _write(OUT_OF_SCOPE_FILE, "fuera\n")
        _report()
    elif scenario == "edit_forbidden":
        _write(FORBIDDEN_FILE, "prohibido\n")
        _report()
    elif scenario == "edit_spec_forbidden":
        _write("docs/secret-plan.md", "prohibido por la especificación\n")
        _report()
    elif scenario == "lies_success":
        _write(OUT_OF_SCOPE_FILE, "miente\n")
        print(json.dumps({"status": "done", "reason_code": "no_changes"}), flush=True)
    elif scenario == "error_exit":
        return 3
    elif scenario == "declares_blocked":
        _report("blocked", "needs_human_decision")
    elif scenario == "invalid_output":
        print("esto no es JSON", flush=True)
    elif scenario == "extra_field_output":
        print(json.dumps({"status": "done", "reason_code": None, "run": "x"}), flush=True)
    elif scenario == "empty_output":
        pass
    elif scenario == "timeout_hang":
        _heartbeat_forever(heartbeat)
    elif scenario == "hang_with_grandchild":
        child = _spawn_grandchild(heartbeat)
        child.wait()
    elif scenario == "leaves_background":
        _spawn_grandchild(heartbeat)
        _report()
    elif scenario == "flood_output":
        line = "x" * 1024
        while True:
            print(line, flush=False)
    elif scenario == "dirty_index":
        _write(ALLOWED_FILE, "staged\n")
        _git("add", "--", ALLOWED_FILE)
        _report()
    elif scenario == "assume_unchanged":
        _git("update-index", "--assume-unchanged", "docs/existing.md")
        _write("docs/existing.md", "escondido\n")
        _report()
    elif scenario == "commits":
        _write(ALLOWED_FILE, "commit\n")
        _git("add", "--", ALLOWED_FILE)
        _git("commit", "-m", "chore: unauthorized commit")
        _report()
    elif scenario == "switches_branch":
        _git("switch", "-c", "claude/other-branch")
        _report()
    elif scenario == "edits_spec":
        target = next(Path("docs/orchestration/work").glob("*.md"))
        target.write_text(target.read_text(encoding="utf-8") + "\nmanipulada\n", encoding="utf-8")
        _report()
    elif scenario == "moves_other_ref":
        _git("branch", "unauthorized-branch")
        _report()
    elif scenario == "edits_shared_config":
        _git("config", "core.hooksPath", "elsewhere")
        _report()
    elif scenario == "ignored_file":
        _write(IGNORED_FILE, "escondido\n")
        _report()
    elif scenario == "cache_file":
        _write(".pytest_cache/x", "cache")
        _report()
    elif scenario == "symlink":
        Path("docs").mkdir(exist_ok=True)
        os.symlink("existing.md", "docs/link.md")
        _report()
    elif scenario == "embedded_repo":
        Path("docs/nested").mkdir(parents=True)
        subprocess.run(["git", "init", "--quiet"], cwd="docs/nested", check=True)
        _write("docs/nested/inner.md", "dentro\n")
        _report()
    elif scenario == "edit_pyproject_deps":
        text = Path("pyproject.toml").read_text(encoding="utf-8")
        _write("pyproject.toml", text.replace("dependencies = []", 'dependencies = ["x"]'))
        _report()
    elif scenario == "edit_pyproject_meta":
        text = Path("pyproject.toml").read_text(encoding="utf-8")
        _write("pyproject.toml", text.replace('name = "x"', 'name = "y"'))
        _report()
    elif scenario == "repoints_git_file":
        # Git lo marca como oculto en Windows, y un archivo oculto no se puede recrear.
        with open(".git", "r+", encoding="utf-8") as handle:
            handle.truncate(0)
            handle.write("gitdir: nowhere\n")
        _report()
    elif scenario == "plants_info_attributes":
        _write(str(_common_dir() / "info" / "attributes"), "* -diff\n")
        _report()
    elif scenario == "plants_post_commit_hook":
        _write(str(_common_dir() / "hooks" / "post-commit"), "#!/bin/sh\nexit 0\n")
        _report()
    elif scenario == "writes_binary":
        Path("docs").mkdir(exist_ok=True)
        Path(ALLOWED_FILE).write_bytes(b"abc\0def")
        _report()
    elif scenario == "writes_allow_marker":
        _write(ALLOWED_FILE, "valor # gitleaks" + ":allow\n")
        _report()
    elif scenario == "link_in_cache":
        Path(".pytest_cache").mkdir(exist_ok=True)
        if sys.platform == "win32":
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", r".pytest_cache\link", "docs"],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        else:
            os.symlink("../docs", ".pytest_cache/link")
        _report()
    elif scenario == "edit_pyproject_tool":
        text = Path("pyproject.toml").read_text(encoding="utf-8")
        _write("pyproject.toml", text + "\n[tool.fake]\nvalue = 1\n")
        _report()
    elif scenario == "edit_lock":
        _write("uv.lock", "changed\n")
        _report()
    elif scenario == "writes_token":
        token = "ghp_" + "".join(
            secrets.choice(string.ascii_letters + string.digits) for _ in range(36)
        )
        _write(ALLOWED_FILE, f'token = "{token}"\n')
        Path(heartbeat).write_text(token, encoding="utf-8")
        _report()
    elif scenario == "prints_token":
        token = "ghp_" + "b" * 36
        print(f"token = {token}", flush=True)
        _report()
    else:
        print(f"unknown scenario: {scenario}", file=sys.stderr)
        return 64
    return 0


if __name__ == "__main__":
    sys.exit(main())
