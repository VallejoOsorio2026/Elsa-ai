"""Runner local de bloques de trabajo (ADR 0036, O1.2).

Una orden, un bloque, y termina. No es un servicio ni forma parte del producto:
no importa ``elsa`` aunque repita patrones de ``elsa.pc1``.

- **Prohibido por defecto.** Los comandos salen de este archivo, nunca de la
  especificación, y todos pasan por :func:`run_process`.
- **Git es la fuente de verdad.** Lo que diga un ejecutor sobre sus cambios no
  se usa: el alcance se comprueba preguntándole a Git.
- **Solo commits locales.** Este archivo no publica, no fusiona y no borra a la
  fuerza. Los subcomandos de Git admitidos son una lista cerrada.
- **Ejecutor real solo por código.** La consola usa :class:`NoChangeExecutor`.
  :class:`ClaudeExecutor` solo se inyecta desde código, se niega a trabajar sobre
  el repositorio real y se limita a documentación (ADR 0037).
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import traceback
import unicodedata
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import IO, Any, Protocol

import yaml

RUNNER_VERSION = "1"
EXPECTED_ORIGIN = "https://github.com/VallejoOsorio2026/Elsa-ai.git"
BASE_BRANCH = "main"

EXIT_OK = 0
EXIT_BLOCKED = 2
EXIT_USAGE = 3
EXIT_LOCK_BUSY = 4

MAX_SPEC_BYTES = 64 * 1024
MAX_CHANGED_FILES = 500
MAX_FILE_BYTES = 500 * 1024
MAX_EXECUTOR_OUTPUT_BYTES = 20 * 1024 * 1024
MAX_SCRUB_BYTES = 5 * 1024 * 1024
MAX_LOG_TAIL_BYTES = 1024 * 1024
MAX_SPEC_TEXT_LENGTH = 300
MAX_TIMEOUT_MINUTES = 120

GIT_TIMEOUT_SECONDS = 60.0
COMMIT_TIMEOUT_SECONDS = 300.0
SECRET_SCAN_TIMEOUT_SECONDS = 180.0
KILL_WAIT_SECONDS = 10.0
_POLL_SECONDS = 0.1
_SETTLE_SECONDS = 0.5

SPEC_DIR = "docs/orchestration/work"
EVIDENCE_DIR = "docs/orchestration/runs"

# Rutas que un bloque orquestado nunca toca. Lo prohibido siempre gana.
ALWAYS_FORBIDDEN = (
    "supabase/**",
    "render.yaml",
    ".github/**",
    "**/.env*",
    "**/.claude/**",
    "**/CLAUDE.md",
    "**/.gitignore",
    "**/.gitattributes",
    ".pre-commit-config.yaml",
    ".gitleaks*",
    ".gitmodules",
    ".mcp.json",
    ".python-version",
    "uv.toml",
    "**/ruff.toml",
    "**/.ruff.toml",
    "**/pytest.ini",
    "**/tox.ini",
    "**/setup.cfg",
    "**/mypy.ini",
    "**/.mypy.ini",
    "**/conftest.py",
    "scripts/orchestrator.py",
    "scripts/Start-ElsaBlock.ps1",
    "tests/*orchestrator*",
    "tests/fake_claude.py",
    "docs/adr/**",
    "**/.credentials.json",
    f"{SPEC_DIR}/**",
    f"{EVIDENCE_DIR}/**",
)

# Solo se pueden cambiar si la especificación las nombra exactamente.
DECLARE_ONLY = ("pyproject.toml", "uv.lock")

# Pruebas que ya fallan en Windows también sobre `main` limpio, ajenas a este runner.
# Lista exacta y aprobada por Juan: nada de patrones. Solo se omiten en Windows, CI las
# sigue ejecutando en Linux, y cualquier otra falla detiene el bloque. Corregir su causa
# es un pendiente de un bloque aparte: cuando se corrija, esta lista debe quedar vacía.
WINDOWS_KNOWN_TEST_FAILURES: Mapping[str, str] = {
    "tests/test_bench_harness.py::test_a_run_records_what_produced_it": (
        "_windows_peak_rss_mb de elsa.bench devuelve None y la prueba exige una cifra"
    ),
    "tests/test_bench_harness.py::test_peak_memory_is_measured_where_the_posix_api_exists": (
        "la prueba exige el módulo resource, que solo existe en POSIX"
    ),
    "tests/test_pc1_supervisor.py::"
    "test_a_real_ctrl_c_reaches_only_the_supervisor_which_stops_in_order": (
        "intermitente: compara con < dos marcas de reloj que en Windows pueden coincidir"
    ),
}

# Claude Code real (ADR 0037). Todo lo que sigue se midió en esta versión exacta, y
# no vale para otra: una versión distinta detiene el bloque.
CLAUDE_VERSION = "2.1.316"
CLAUDE_MODEL = "sonnet"
CLAUDE_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")
# Claude real nunca recibe consola (ADR 0037, §4): en O1.3.4, `Bash(<comando exacto>)` dejó
# pasar otros comandos y también encadenarlos. Esta lista se escribe aparte, a propósito: si
# alguien cambia `CLAUDE_TOOLS`, el comando, el primer evento y la importación se detienen igual.
_CLAUDE_FILE_TOOLS = frozenset({"Read", "Edit", "Write", "Glob", "Grep"})
_CLAUDE_OBSERVED_ONLY_TOOLS = frozenset({"StructuredOutput"})
if not set(CLAUDE_TOOLS) <= _CLAUDE_FILE_TOOLS:
    raise RuntimeError("ClaudeExecutor only accepts file tools: no console (ADR 0037)")
CLAUDE_FROZEN_FLAGS = (
    "--safe-mode",
    "--restricted",
    "--strict-mcp-config",
    "--disable-slash-commands",
)
# Lo que debe declarar el primer evento. `StructuredOutput` lo añade `--json-schema`.
CLAUDE_EXPECTED_TOOLS = sorted(("Edit", "Glob", "Grep", "Read", "StructuredOutput", "Write"))
CLAUDE_EXPECTED_AGENTS = sorted(("claude", "Explore", "general-purpose", "Plan"))
CLAUDE_EXPECTED_PLUGINS = sorted(("cc-plugin-agents-md", "cc-plugin-plugin-authoring"))
# Los 27 campos del primer evento con estas opciones: un campo nuevo o ausente detiene el
# bloque. Sin comparar su valor, solo `uuid` y `powershell_path`, que cambian por ejecución
# o por máquina. De `model` basta el prefijo, porque `sonnet` es un alias.
CLAUDE_INIT_FIELDS = frozenset(
    {
        "type",
        "subtype",
        "uuid",
        "session_id",
        "cwd",
        "original_cwd",
        "powershell_path",
        "claude_code_version",
        "permissionMode",
        "tools",
        "mcp_servers",
        "additional_directories",
        "skills",
        "slash_commands",
        "agents",
        "plugins",
        "apiKeySource",
        "model",
        "analytics_disabled",
        "capabilities",
        "fast_mode_disabled_reason",
        "fast_mode_state",
        "output_style",
        "per_turn_effort_active",
        "product_feedback_disabled",
        "ultrathink_available",
        "view_mode",
    }
)
CLAUDE_INIT_FIXED_VALUES: Mapping[str, object] = {
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
}
# Nada de esto puede aparecer nunca en el comando. `--settings` encabeza la lista: con
# `-p`, un archivo inválido se ignora en silencio (medido en O1.3.1).
FORBIDDEN_CLAUDE_OPTIONS = frozenset(
    {
        "--settings",
        "--setting-sources",
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        "--add-dir",
        "--mcp-config",
        "--plugin-dir",
        "--plugin-url",
        "--agent",
        "--agents",
        "--file",
        "--chrome",
        "--bare",
        "--bg",
        "--background",
        "--resume",
        "-r",
        "--continue",
        "-c",
        "--worktree",
        "-w",
        "--cloud",
        "--remote-control",
        "--teleport",
        "--system-prompt",
        "--append-system-prompt",
        "--managed-settings",
    }
)
CLAUDE_ENV_ALLOWLIST = (
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "HOME",
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "SYSTEMROOT",
    "SYSTEMDRIVE",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "USERNAME",
    "OS",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "LANG",
)
# Los comandos de Git que Claude Code lanza por su cuenta, observados en 39 ejecuciones.
# Todos de lectura. Cualquier otro, por inocente que parezca, detiene el bloque.
CLAUDE_READ_ONLY_GIT = frozenset(
    {
        "git version",
        "git status --short --ignore-submodules=dirty",
        "git log --oneline -n 5",
        "git config user.name",
        "git remote",
        "git remote get-url origin",
        "git remote get-url --push origin",
        "git config --get remote.origin.url",
        "git ls-files --error-unmatch -- ':(icase).claude/settings.local.json'",
    }
)
CLAUDE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "result": {"type": "string", "enum": ["done", "blocked"]},
        "files_changed": {"type": "array", "items": {"type": "string"}},
        "blocked": {"type": "boolean"},
        "reason": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,63}$"},
    },
    "required": ["result", "files_changed", "blocked", "reason"],
}
CLAUDE_MAX_ALLOWED_PATHS = 5
CLAUDE_INIT_TIMEOUT_SECONDS = 60.0
CLAUDE_USER_SETTINGS_ALLOWED = frozenset({"autoUpdatesChannel", "tui"})
# Otro archivo de usuario que 2.1.316 puede leer como configuración (visto en el binario).
CLAUDE_USER_ALTERNATE_SETTINGS = ("cowork_settings.json",)
# Configuración administrada que 2.1.316 sigue aplicando con `--safe-mode` y `--restricted`.
# Rutas y claves leídas del binario instalado, no supuestas. Se niega su presencia, sin leerla.
CLAUDE_MANAGED_DIRS: Mapping[str, Path] = {
    "win32": Path(r"C:\Program Files\ClaudeCode"),
    "darwin": Path("/Library/Application Support/ClaudeCode"),
}
CLAUDE_MANAGED_DIR_OTHER = Path("/etc/claude-code")
CLAUDE_POLICY_KEY = r"SOFTWARE\Policies\ClaudeCode"
# La configuración administrada remota solo deja rastro en su caché local.
CLAUDE_REMOTE_SETTINGS_FILES = (
    "remote-settings.json",
    "policy-limits.json",
    "remote-settings-consent.json",
    "remote-settings-helper-consent",
)
# Lo único que puede haber en el `.claude/` del proyecto: su efecto se ve en el primer evento,
# que exige `skills` vacío y la lista exacta de agentes.
CLAUDE_PROJECT_DIRS_ALLOWED = frozenset({"agents", "skills"})
# Rutas que gitleaks excluye por defecto: un secreto ahí pasaría los escaneos.
_GITLEAKS_EXCLUDED_PATH_RE = re.compile(
    r"(?i)(^|/)(node_modules|bower_components|vendor|v?env|virtualenv|lib(64)?|python)/"
    r"|\.dist-info/"
)
_CLAUDE_BARE_OPTIONS = frozenset({*CLAUDE_FROZEN_FLAGS, "--verbose", "--no-session-persistence"})
_CLAUDE_VALUE_OPTIONS = frozenset(
    {
        "-p",
        "--model",
        "--output-format",
        "--json-schema",
        "--session-id",
        "--permission-mode",
        "--permission-prompts",
        "--tools",
        "--allowedTools",
        "--disallowedTools",
    }
)
_CLAUDE_READ_RULES = frozenset({"Read", "Glob", "Grep"})
_CLAUDE_EDIT_RULE_RE = re.compile(r"Edit\([A-Za-z0-9._/\-]+\)")

# Directorios ignorados que los controles de calidad pueden dejar.
ALLOWED_CACHE_DIRS = frozenset({".pytest_cache", ".ruff_cache", ".mypy_cache", "__pycache__"})

SPEC_FIELDS = frozenset(
    {
        "id",
        "title",
        "base",
        "branch",
        "allowed_paths",
        "forbidden_paths",
        "timeout_minutes",
        "stop_conditions",
        "human_gates",
    }
)
SPEC_SECTIONS = ("Objetivo", "Dentro del alcance", "Fuera del alcance", "Criterios de aceptación")

_ID_RE = re.compile(r"[A-Z][A-Za-z0-9]*(?:\.[A-Za-z0-9]+)*")
_PATTERN_RE = re.compile(r"[A-Za-z0-9._\-/*]+")
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_EXECUTOR_REASON_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)

# Límite declarado: es una limpieza de patrones conocidos, no una garantía.
_SECRET_PATTERNS = (
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bsb_secret_[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S
    ),
    re.compile(r"postgres(?:ql)?://[^\s:/]+:[^\s@]+@\S+", re.I),
    re.compile(
        r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|service_role)\b"
        r"[\"']?\s*[:=]\s*[\"']?[^\s\"']{4,}"
    ),
)

_ENV_ALLOWLIST = frozenset(
    {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "WINDIR",
        "COMSPEC",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "HOME",
        "USER",
        "USERNAME",
        "LOGNAME",
        "LOCALAPPDATA",
        "APPDATA",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "COMMONPROGRAMFILES",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "OS",
        "LANG",
        "LC_ALL",
    }
)

# Programas que este runner nunca lanza en O1.2.
_FORBIDDEN_PROGRAMS = frozenset({"claude", "gh"})
_GIT_TRACE_RE = re.compile(r"\btrace: (.*)$")
_GIT_TRACE_COMMAND_RE = re.compile(r"(?:built-in|exec|run_command): (.*)$")
_GIT_TRACE_HARMLESS = ("resolved executable dir: ",)
# Ni el esquema, ni el usuario, ni el anfitrión o su alias, ni el puerto cambian de qué
# repositorio se habla: solo cuenta la ruta.
_ORIGIN_RE = re.compile(r"^(?:[a-z][a-z0-9+.\-]*://)?(?:[^/]*@)?[^:/@]+(?::\d+)?[:/]+(.+)$")
# Una línea que no se pudo leer y parece un `init` no se da por inofensiva.
_UNREADABLE_INIT_RE = re.compile(r'"subtype"\s*:\s*"init"')

_ALLOWED_GIT_COMMANDS = frozenset(
    {
        "add",
        "branch",
        "check-ref-format",
        "commit",
        "config",
        "diff",
        "for-each-ref",
        "ls-files",
        "ls-remote",
        "remote",
        "rev-parse",
        "show",
        "show-ref",
        "status",
        "symbolic-ref",
        "worktree",
        "write-tree",
    }
)
_ALLOWED_GIT_SUBCOMMANDS = {
    "branch": frozenset({"-d"}),
    "config": frozenset({"--get"}),
    "remote": frozenset({"get-url"}),
    "worktree": frozenset({"add", "list", "remove"}),
}
FORBIDDEN_GIT_TOKENS = frozenset(
    {
        "--force",
        "-f",
        "-D",
        "--hard",
        "--no-verify",
        "-n",
        "--amend",
        "--mirror",
        "--delete",
        "--exec",
        "--upload-pack",
        "--receive-pack",
    }
)


class Reason(StrEnum):
    """Motivos de parada. En inglés porque van a los logs (CLAUDE.md §3)."""

    INVALID_BLOCK_ID = "invalid_block_id"
    LOCK_BUSY = "lock_busy"
    UNSAFE_EXTERNAL_ROOT = "unsafe_external_root"
    SPEC_NOT_FOUND = "spec_not_found"
    INVALID_SPEC = "invalid_spec"
    SPEC_ALREADY_USED = "spec_already_used"
    WRONG_REPOSITORY = "wrong_repository"
    WRONG_ORIGIN = "wrong_origin"
    LAUNCHED_FROM_LINKED_WORKTREE = "launched_from_linked_worktree"
    NOT_ON_BASE = "not_on_base"
    DIRTY_WORKING_TREE = "dirty_working_tree"
    HEAD_MISALIGNED = "head_misaligned"
    REMOTE_UNREACHABLE = "remote_unreachable"
    REMOTE_MISALIGNED = "remote_misaligned"
    INVALID_BRANCH = "invalid_branch"
    BRANCH_EXISTS = "branch_exists"
    HOOK_MISSING = "hook_missing"
    HOOKS_PATH_OVERRIDDEN = "hooks_path_overridden"
    WORKTREE_EXISTS = "worktree_exists"
    WORKTREE_FAILED = "worktree_failed"
    NOT_APPROVED = "not_approved"
    EXECUTOR_FAILED = "executor_failed"
    EXECUTOR_TIMEOUT = "executor_timeout"
    EXECUTOR_BLOCKED = "executor_blocked"
    EXECUTOR_OUTPUT_TOO_LARGE = "executor_output_too_large"
    EXECUTOR_LEFT_PROCESSES = "executor_left_processes"
    INVALID_EXECUTOR_OUTPUT = "invalid_executor_output"
    ORPHAN_SUSPECTED = "orphan_suspected"
    PROCESS_CONTROL_FAILED = "process_control_failed"
    HEAD_MOVED = "head_moved"
    SPEC_TAMPERED = "spec_tampered"
    INDEX_TAMPERED = "index_tampered"
    REPO_INVARIANT_BROKEN = "repo_invariant_broken"
    IGNORED_FILE_PRESENT = "ignored_file_present"
    UNSAFE_PATH = "unsafe_path"
    UNSAFE_FILE_MODE = "unsafe_file_mode"
    FORBIDDEN_PATH = "forbidden_path"
    SCOPE_VIOLATION = "scope_violation"
    TOO_MANY_CHANGES = "too_many_changes"
    FILE_TOO_LARGE = "file_too_large"
    DEPENDENCY_CHANGE = "dependency_change"
    SECRET_DETECTED = "secret_detected"
    SECRET_SCAN_SKIPPED = "secret_scan_skipped"
    SECRET_SCAN_FAILED = "secret_scan_failed"
    SECRET_SCAN_EVADED = "secret_scan_evaded"
    QUALITY_GATE_FAILED = "quality_gate_failed"
    QUALITY_GATE_TIMEOUT = "quality_gate_timeout"
    GATE_MODIFIED_TREE = "gate_modified_tree"
    COMMIT_FAILED = "commit_failed"
    EVIDENCE_REJECTED = "evidence_rejected"
    GIT_FAILED = "git_failed"
    GIT_TIMEOUT = "git_timeout"
    CLEANUP_REFUSED = "cleanup_refused"
    NOTHING_TO_CLEAN = "nothing_to_clean"
    CLAUDE_NOT_FOUND = "claude_not_found"
    CLAUDE_VERSION_MISMATCH = "claude_version_mismatch"
    CLAUDE_INIT_MISSING = "claude_init_missing"
    CLAUDE_CAPABILITY_MISMATCH = "claude_capability_mismatch"
    CLAUDE_UNSAFE_COMMAND = "claude_unsafe_command"
    CLAUDE_GIT_TRACE_MISSING = "claude_git_trace_missing"
    CLAUDE_GIT_COMMAND_NOT_ALLOWED = "claude_git_command_not_allowed"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    CLAUDE_REPORT_MISMATCH = "claude_report_mismatch"
    CODE_PROFILE_FORBIDDEN = "code_profile_forbidden"
    REAL_REPO_NOT_AUTHORIZED = "real_repo_not_authorized"
    CLAUDE_USER_SETTINGS_UNEXPECTED = "claude_user_settings_unexpected"
    CLAUDE_PROJECT_SETTINGS_PRESENT = "claude_project_settings_present"
    CLAUDE_PROJECT_MCP_PRESENT = "claude_project_mcp_present"
    CLAUDE_MANAGED_SETTINGS_PRESENT = "claude_managed_settings_present"
    DAMAGE_CHECK_FAILED = "damage_check_failed"
    INTERRUPTED = "interrupted"
    INTERNAL_ERROR = "internal_error"


MESSAGES: Mapping[Reason, str] = {
    Reason.INVALID_BLOCK_ID: "El identificador del bloque no es válido.",
    Reason.LOCK_BUSY: "Ya hay otra ejecución del runner en esta máquina.",
    Reason.UNSAFE_EXTERNAL_ROOT: "La carpeta externa no es segura: está en OneDrive o en el repo.",
    Reason.SPEC_NOT_FOUND: "No se encontró la especificación en la bandeja.",
    Reason.INVALID_SPEC: "La especificación no cumple el contrato.",
    Reason.SPEC_ALREADY_USED: "Ya existe una especificación con ese identificador en el repo.",
    Reason.WRONG_REPOSITORY: "El runner no está en la raíz del repositorio esperado.",
    Reason.WRONG_ORIGIN: "El remoto origin no es el repositorio autorizado.",
    Reason.LAUNCHED_FROM_LINKED_WORKTREE: "El runner debe lanzarse desde el clon principal.",
    Reason.NOT_ON_BASE: "El clon principal no está en la rama base.",
    Reason.DIRTY_WORKING_TREE: "El clon principal tiene cambios sin commitear.",
    Reason.HEAD_MISALIGNED: "HEAD no coincide con origin/main.",
    Reason.REMOTE_UNREACHABLE: "No se pudo consultar el remoto. Sin confirmarlo no se empieza.",
    Reason.REMOTE_MISALIGNED: "El main local no coincide con el main del remoto.",
    Reason.INVALID_BRANCH: "La rama no cumple el formato claude/<id>.",
    Reason.BRANCH_EXISTS: "La rama de trabajo ya existe. No se reutiliza.",
    Reason.HOOK_MISSING: "Falta el hook de pre-commit en el clon.",
    Reason.HOOKS_PATH_OVERRIDDEN: "core.hooksPath está configurado: no se garantizan los hooks.",
    Reason.WORKTREE_EXISTS: "La carpeta de la copia de trabajo ya existe. No se reutiliza.",
    Reason.WORKTREE_FAILED: "No se pudo crear la copia de trabajo.",
    Reason.NOT_APPROVED: "La especificación no fue aprobada.",
    Reason.EXECUTOR_FAILED: "El ejecutor terminó con error.",
    Reason.EXECUTOR_TIMEOUT: "El ejecutor superó su tiempo límite y se terminó.",
    Reason.EXECUTOR_BLOCKED: "El ejecutor declaró un bloqueo.",
    Reason.EXECUTOR_OUTPUT_TOO_LARGE: "El ejecutor produjo demasiada salida y se terminó.",
    Reason.EXECUTOR_LEFT_PROCESSES: "El ejecutor dejó procesos vivos; se terminaron.",
    Reason.INVALID_EXECUTOR_OUTPUT: "La salida del ejecutor no cumple el contrato.",
    Reason.ORPHAN_SUSPECTED: "Pueden quedar procesos vivos tras la terminación. Revíselo a mano.",
    Reason.PROCESS_CONTROL_FAILED: "No se pudo poner el proceso bajo control.",
    Reason.HEAD_MOVED: "HEAD o la rama cambiaron: el ejecutor no puede commitear.",
    Reason.SPEC_TAMPERED: "La especificación cambió durante la ejecución.",
    Reason.INDEX_TAMPERED: "El índice de Git fue manipulado.",
    Reason.REPO_INVARIANT_BROKEN: "El repositorio principal cambió durante la ejecución.",
    Reason.IGNORED_FILE_PRESENT: "Hay archivos ignorados en la copia de trabajo.",
    Reason.UNSAFE_PATH: "Hay un nombre de archivo no seguro.",
    Reason.UNSAFE_FILE_MODE: "Hay un enlace simbólico, submódulo o repositorio anidado.",
    Reason.FORBIDDEN_PATH: "Se cambió una ruta prohibida.",
    Reason.SCOPE_VIOLATION: "Se cambió una ruta fuera del alcance permitido.",
    Reason.TOO_MANY_CHANGES: "Demasiados archivos cambiados.",
    Reason.FILE_TOO_LARGE: "Un archivo supera el tamaño permitido.",
    Reason.DEPENDENCY_CHANGE: "Cambian dependencias o configuración de las herramientas.",
    Reason.SECRET_DETECTED: "Gitleaks detectó un posible secreto.",
    Reason.SECRET_SCAN_SKIPPED: "El escaneo de secretos se omitió. Se considera un fallo.",
    Reason.SECRET_SCAN_FAILED: "El escaneo de secretos no se pudo completar.",
    Reason.SECRET_SCAN_EVADED: "Hay un binario o un marcador que el escaneo no revisaría.",
    Reason.QUALITY_GATE_FAILED: "Un control de calidad falló.",
    Reason.QUALITY_GATE_TIMEOUT: "Un control de calidad superó su tiempo límite.",
    Reason.GATE_MODIFIED_TREE: "Un control de calidad modificó la copia de trabajo.",
    Reason.COMMIT_FAILED: "El commit falló, por ejemplo por un hook.",
    Reason.EVIDENCE_REJECTED: "La evidencia no pasó la validación de sanitización.",
    Reason.GIT_FAILED: "Un comando de Git falló.",
    Reason.GIT_TIMEOUT: "Un comando de Git superó su tiempo límite.",
    Reason.CLEANUP_REFUSED: "Git rechazó retirar la copia de trabajo. No se fuerza.",
    Reason.NOTHING_TO_CLEAN: "No hay copia de trabajo de este bloque.",
    Reason.CLAUDE_NOT_FOUND: "No se encontró Claude Code.",
    Reason.CLAUDE_VERSION_MISMATCH: "La versión de Claude Code no es la validada.",
    Reason.CLAUDE_INIT_MISSING: "No se pudo verificar qué capacidades recibió Claude Code.",
    Reason.CLAUDE_CAPABILITY_MISMATCH: "Claude Code recibió una capacidad inesperada.",
    Reason.CLAUDE_UNSAFE_COMMAND: "El comando de Claude Code incumple el contrato.",
    Reason.CLAUDE_GIT_TRACE_MISSING: "No hay registro de los comandos Git de Claude Code.",
    Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED: "Claude Code lanzó un comando Git no observado antes.",
    Reason.INVALID_STRUCTURED_OUTPUT: "La salida estructurada de Claude no cumple el contrato.",
    Reason.CLAUDE_REPORT_MISMATCH: "Lo que Claude declara no coincide con lo que dice Git.",
    Reason.CODE_PROFILE_FORBIDDEN: "El ejecutor real solo puede cambiar documentación.",
    Reason.REAL_REPO_NOT_AUTHORIZED: "El ejecutor real no está autorizado en el repositorio real.",
    Reason.CLAUDE_USER_SETTINGS_UNEXPECTED: "La configuración de usuario no es la validada.",
    Reason.CLAUDE_PROJECT_SETTINGS_PRESENT: "Hay configuración de Claude en el proyecto.",
    Reason.CLAUDE_PROJECT_MCP_PRESENT: "Hay configuración MCP en el proyecto.",
    Reason.CLAUDE_MANAGED_SETTINGS_PRESENT: "Hay configuración administrada de Claude Code.",
    Reason.DAMAGE_CHECK_FAILED: "No se pudo completar la revisión de daños tras la parada.",
    Reason.INTERRUPTED: "Ejecución interrumpida por el operador.",
    Reason.INTERNAL_ERROR: "Error interno del runner. Detalle en los logs locales.",
}


class BlockedError(Exception):
    """Detiene el recorrido. ``detail`` nunca lleva contenido de archivos ni salidas."""

    def __init__(self, reason: Reason, detail: str = "") -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.detail = detail


class Result(StrEnum):
    VALIDATED = "validated"
    VERIFIED_LOCAL = "verified_local"
    BLOCKED = "blocked"


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate:
    """Un control de calidad. Sus argumentos solo salen de este archivo o de un test."""

    name: str
    argv: tuple[str, ...]
    timeout: float
    omitted_tests: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunnerConfig:
    """Todo lo que varía entre producción y tests. La consola solo usa :func:`default_config`."""

    repo_root: Path
    external_root: Path
    expected_origin: str
    tool_python: Path
    precommit_command: tuple[str, ...] = ()
    code_gates: tuple[Gate, ...] | None = None
    executor_timeout_seconds: float | None = None
    max_executor_output: int = MAX_EXECUTOR_OUTPUT_BYTES
    kill_wait_seconds: float = KILL_WAIT_SECONDS
    extra_env: Mapping[str, str] = field(default_factory=dict)
    claude_home: Path | None = None
    claude_managed_dir: Path | None = None

    @property
    def inbox(self) -> Path:
        return self.external_root / "inbox"

    @property
    def worktrees(self) -> Path:
        return self.external_root / "worktrees"

    @property
    def logs(self) -> Path:
        return self.external_root / "logs"

    @property
    def state(self) -> Path:
        return self.external_root / "state"

    def scanner_command(self) -> tuple[str, ...]:
        return self.precommit_command or (str(self.tool_python), "-m", "pre_commit")

    def gates(self) -> tuple[Gate, ...]:
        return self.code_gates if self.code_gates is not None else default_code_gates(self)


def default_config() -> RunnerConfig:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not home:
        raise BlockedError(Reason.UNSAFE_EXTERNAL_ROOT, "no_user_profile")
    return RunnerConfig(
        repo_root=Path(__file__).resolve().parents[1],
        external_root=Path(home) / "elsa-o1",
        expected_origin=EXPECTED_ORIGIN,
        tool_python=Path(sys.executable),
    )


def default_code_gates(config: RunnerConfig, platform: str = sys.platform) -> tuple[Gate, ...]:
    python = str(config.tool_python)
    omitted = tuple(WINDOWS_KNOWN_TEST_FAILURES) if platform == "win32" else ()
    deselect = [argument for test in omitted for argument in ("--deselect", test)]
    # El `.venv` tiene `elsa` instalada apuntando al clon principal: sin este
    # control, las pruebas podrían pasar contra el código equivocado.
    package_origin = (
        "import pathlib, sys, elsa; "
        "origin = pathlib.Path(elsa.__file__).resolve(); "
        "root = pathlib.Path.cwd().resolve() / 'src'; "
        "sys.exit(0 if origin.is_relative_to(root) else 1)"
    )
    return (
        Gate("package_origin", (python, "-c", package_origin), 60.0),
        Gate("ruff_check", (python, "-m", "ruff", "check", "."), 120.0),
        Gate("ruff_format", (python, "-m", "ruff", "format", "--check", "."), 120.0),
        # Igual que CI, que corre en Linux: `elsa.bench` no tipa en Windows sin esto.
        Gate("mypy", (python, "-m", "mypy", "--platform", "linux"), 900.0),
        Gate("pytest", (python, "-m", "pytest", "-q", *deselect), 1800.0, omitted),
    )


def build_env(config: RunnerConfig, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Lista de permitidos: una variable que no esté aquí no llega a ningún hijo."""
    env = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in _ENV_ALLOWLIST and value
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUTF8"] = "1"
    env.update(config.extra_env)
    if extra:
        env.update(extra)
    return env


def _git_env(config: RunnerConfig, *, literal_paths: bool = False) -> dict[str, str]:
    extra = {
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "GIT_OPTIONAL_LOCKS": "0",
        # Sin mantenimiento en segundo plano sobre un repositorio compartido.
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "gc.auto",
        "GIT_CONFIG_VALUE_0": "0",
        "GIT_CONFIG_KEY_1": "maintenance.auto",
        "GIT_CONFIG_VALUE_1": "false",
    }
    if literal_paths:
        extra["GIT_LITERAL_PATHSPECS"] = "1"
    return build_env(config, extra)


# ---------------------------------------------------------------------------
# Procesos: toda ejecución pasa por `run_process`
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    timed_out: bool
    output_exceeded: bool
    left_processes: bool
    orphan_suspected: bool
    duration: float
    aborted: bool = False


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _CREATE_SUSPENDED = 0x00000004
    _CREATE_NO_WINDOW = 0x08000000
    _JOB_OBJECT_BASIC_ACCOUNTING_CLASS = 1
    _JOB_OBJECT_EXTENDED_LIMIT_CLASS = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _PROCESS_TERMINATE = 0x0001
    _PROCESS_SET_QUOTA = 0x0100
    _PROCESS_SUSPEND_RESUME = 0x0800

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll = ctypes.WinDLL("ntdll")
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    _kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    _ntdll.NtResumeProcess.restype = ctypes.c_long

    def _last_error() -> OSError:
        return ctypes.WinError(ctypes.get_last_error())

    class _ProcessTree:
        """Un proceso y todos sus descendientes, dentro de un Job Object propio.

        El hijo nace suspendido y solo se reanuda tras entrar al job: así no hay
        ventana en la que pueda lanzar un nieto que quede fuera. El job no permite
        salir de él y termina todo al cerrarse su último handle, también si el
        runner muere. Un proceso creado a través de otro servicio de Windows sí
        queda fuera: eso no se puede garantizar desde aquí.
        """

        def __init__(
            self,
            argv: Sequence[str],
            cwd: Path,
            env: Mapping[str, str],
            stdout: IO[bytes],
            stderr: IO[bytes] | int,
        ) -> None:
            handle = _kernel32.CreateJobObjectW(None, None)
            if not handle:
                raise _last_error()
            self._handle: int | None = handle
            try:
                info = _ExtendedLimitInformation()
                info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                if not _kernel32.SetInformationJobObject(
                    handle,
                    _JOB_OBJECT_EXTENDED_LIMIT_CLASS,
                    ctypes.byref(info),
                    ctypes.sizeof(info),
                ):
                    raise _last_error()
                self.popen = subprocess.Popen(
                    list(argv),
                    cwd=cwd,
                    env=dict(env),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    creationflags=(
                        _CREATE_SUSPENDED | subprocess.CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW
                    ),
                )
                try:
                    self._assign_and_resume(self.popen.pid)
                except BaseException:
                    self.popen.kill()
                    self.popen.wait()
                    raise
            except BaseException:
                self.close()
                raise

        def _assign_and_resume(self, pid: int) -> None:
            process = _kernel32.OpenProcess(
                _PROCESS_SET_QUOTA | _PROCESS_TERMINATE | _PROCESS_SUSPEND_RESUME, False, pid
            )
            if not process:
                raise _last_error()
            try:
                if not _kernel32.AssignProcessToJobObject(self._handle, process):
                    raise _last_error()
                status = _ntdll.NtResumeProcess(process)
                if status != 0:
                    raise OSError(f"NtResumeProcess failed with status {status:#x}")
            finally:
                _kernel32.CloseHandle(process)

        def active_processes(self) -> int:
            if self._handle is None:
                return 0
            info = _BasicAccountingInformation()
            if not _kernel32.QueryInformationJobObject(
                self._handle,
                _JOB_OBJECT_BASIC_ACCOUNTING_CLASS,
                ctypes.byref(info),
                ctypes.sizeof(info),
                None,
            ):
                raise _last_error()
            return int(info.ActiveProcesses)

        def terminate(self) -> None:
            if self._handle is not None:
                _kernel32.TerminateJobObject(self._handle, 1)

        def close(self) -> None:
            handle, self._handle = self._handle, None
            if handle is not None:
                _kernel32.CloseHandle(handle)

else:

    class _ProcessTree:
        """POSIX, solo para los tests y CI: un grupo de procesos propio."""

        def __init__(
            self,
            argv: Sequence[str],
            cwd: Path,
            env: Mapping[str, str],
            stdout: IO[bytes],
            stderr: IO[bytes] | int,
        ) -> None:
            self.popen = subprocess.Popen(
                list(argv),
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )

        def active_processes(self) -> int:
            try:
                os.killpg(self.popen.pid, 0)
            except ProcessLookupError:
                return 0
            except PermissionError:
                return 1
            return 1

        def terminate(self) -> None:
            try:
                os.killpg(self.popen.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        def close(self) -> None:
            pass


def _check_program(argv: Sequence[str], *, allow_claude: bool = False) -> None:
    name = re.split(r"[\\/]", argv[0])[-1].rsplit(".", 1)[0].lower()
    if name in _FORBIDDEN_PROGRAMS and not (allow_claude and name == "claude"):
        raise BlockedError(Reason.PROCESS_CONTROL_FAILED, "forbidden_program")


def _wait_until_empty(tree: _ProcessTree, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while True:
        tree.popen.poll()
        if tree.active_processes() == 0:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.01)


def run_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    stdout: IO[bytes],
    stderr: IO[bytes] | int = subprocess.STDOUT,
    kill_wait: float = KILL_WAIT_SECONDS,
    max_output: int | None = None,
    on_poll: Callable[[], bool] | None = None,
    allow_claude: bool = False,
) -> ProcessResult:
    """Ejecuta un comando con plazo. La salida va a un archivo, nunca a una tubería.

    Con una tubería, un nieto vivo que la herede dejaría al runner esperando
    para siempre aunque el hijo ya hubiera terminado. ``on_poll`` permite cortar
    el proceso mientras corre, si devuelve verdadero.
    """
    _check_program(argv, allow_claude=allow_claude)
    started = time.monotonic()
    deadline = started + timeout
    try:
        tree = _ProcessTree(argv, cwd, env, stdout, stderr)
    except OSError as error:
        raise BlockedError(Reason.PROCESS_CONTROL_FAILED, type(error).__name__) from error
    timed_out = False
    output_exceeded = False
    aborted = False
    try:
        while True:
            try:
                tree.popen.wait(timeout=_POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() >= deadline:
                timed_out = True
                break
            if max_output is not None and os.fstat(stdout.fileno()).st_size > max_output:
                output_exceeded = True
                break
            if on_poll is not None and on_poll():
                aborted = True
                break
        left_processes = False
        if not timed_out and not output_exceeded and not aborted:
            left_processes = not _wait_until_empty(tree, _SETTLE_SECONDS)
        if timed_out or output_exceeded or aborted or left_processes:
            tree.terminate()
        orphan_suspected = not _wait_until_empty(tree, kill_wait)
        try:
            returncode: int | None = tree.popen.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            returncode = None
    except BaseException as error:
        tree.terminate()
        # Con Ctrl+C también: la revisión de daños no debe correr mientras el árbol aún escribe.
        # Si no se vacía, o no se sabe, eso pesa más; el motivo original queda encadenado.
        try:
            emptied = _wait_until_empty(tree, kill_wait)
        except OSError:
            emptied = False
        if not emptied:
            raise BlockedError(Reason.ORPHAN_SUSPECTED, "after_stop") from error
        raise
    finally:
        tree.close()
    return ProcessResult(
        returncode=returncode,
        timed_out=timed_out,
        output_exceeded=output_exceeded,
        left_processes=left_processes,
        orphan_suspected=orphan_suspected,
        duration=time.monotonic() - started,
        aborted=aborted,
    )


# ---------------------------------------------------------------------------
# Git: lista cerrada de subcomandos
# ---------------------------------------------------------------------------


def validate_git_args(args: Sequence[str]) -> None:
    """Rechaza cualquier comando de Git fuera de la lista cerrada de este runner."""
    if not args or args[0] not in _ALLOWED_GIT_COMMANDS:
        raise BlockedError(Reason.GIT_FAILED, "git_command_not_allowed")
    allowed_sub = _ALLOWED_GIT_SUBCOMMANDS.get(args[0])
    if allowed_sub is not None and (len(args) < 2 or args[1] not in allowed_sub):
        raise BlockedError(Reason.GIT_FAILED, "git_subcommand_not_allowed")
    if args[0] == "commit" and (len(args) != 3 or args[1] != "-m"):
        raise BlockedError(Reason.GIT_FAILED, "git_argument_not_allowed")
    for token in args[1:]:
        option = token.split("=", 1)[0]
        # Git acepta abreviaturas de las opciones largas, como `--no-verif`.
        abbreviated = (
            option.startswith("--")
            and len(option) > 2
            and any(forbidden.startswith(option) for forbidden in FORBIDDEN_GIT_TOKENS)
        )
        if option in FORBIDDEN_GIT_TOKENS or abbreviated:
            raise BlockedError(Reason.GIT_FAILED, "git_argument_not_allowed")


def _find_program(config: RunnerConfig, name: str) -> str | None:
    """Ruta absoluta. En Windows, un nombre a secas buscaría antes en la carpeta actual."""
    if sys.platform == "win32":
        name = f"{name}.exe"
    repo = os.path.normcase(os.path.realpath(config.repo_root))
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        if not folder or not os.path.isabs(folder):
            continue
        location = os.path.normcase(os.path.realpath(folder))
        if location == repo or location.startswith(repo + os.sep):
            continue
        candidate = os.path.join(folder, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def find_git(config: RunnerConfig) -> str:
    found = _find_program(config, "git")
    if found is None:
        raise BlockedError(Reason.GIT_FAILED, "git_not_found")
    return found


@dataclass(frozen=True)
class GitOutput:
    returncode: int
    stdout: bytes

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", "surrogateescape").strip()


class Git:
    """Git en una carpeta concreta. Es la única forma de llamar a Git en este archivo."""

    def __init__(self, config: RunnerConfig, cwd: Path, log_path: Path | None = None) -> None:
        self._config = config
        self.cwd = cwd
        self._log_path = log_path

    def run(
        self,
        *args: str,
        check: bool = True,
        literal_paths: bool = False,
        timeout: float = GIT_TIMEOUT_SECONDS,
    ) -> GitOutput:
        validate_git_args(args)
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            result = run_process(
                [find_git(self._config), *args],
                cwd=self.cwd,
                env=_git_env(self._config, literal_paths=literal_paths),
                timeout=timeout,
                stdout=out,
                stderr=err,
                kill_wait=self._config.kill_wait_seconds,
            )
            out.seek(0)
            stdout = out.read()
            err.seek(0)
            stderr = err.read()
        if result.timed_out:
            raise BlockedError(Reason.GIT_TIMEOUT, args[0])
        if result.orphan_suspected:
            raise BlockedError(Reason.ORPHAN_SUSPECTED, args[0])
        code = result.returncode if result.returncode is not None else -1
        if self._log_path is not None and code != 0:
            with open(self._log_path, "a", encoding="utf-8") as log:
                log.write(f"git {args[0]} exit={code}\n")
                log.write(scrub_text(stderr[-4000:].decode("utf-8", "replace")) + "\n")
        if check and code != 0:
            raise BlockedError(Reason.GIT_FAILED, args[0])
        return GitOutput(code, stdout)


def _split_nul(data: bytes) -> list[str]:
    return [item.decode("utf-8", "surrogateescape") for item in data.split(b"\0") if item]


# ---------------------------------------------------------------------------
# Sanitización
# ---------------------------------------------------------------------------


def scrub_text(text: str) -> str:
    """Sustituye patrones conocidos de secretos. Es parcial, por eso los logs no se versionan."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


def scrub_file(path: Path) -> None:
    if not path.exists():
        return
    with open(path, "rb") as handle:
        data = handle.read(MAX_SCRUB_BYTES)
    text = scrub_text(data.decode("utf-8", "replace"))
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


# ---------------------------------------------------------------------------
# Contrato de la especificación
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Spec:
    id: str
    title: str
    base: str
    branch: str
    allowed_paths: tuple[str, ...]
    forbidden_paths: tuple[str, ...]
    timeout_minutes: int
    stop_conditions: tuple[str, ...]
    human_gates: tuple[str, ...]
    raw: bytes
    sha256: str


class _StrictLoader(yaml.SafeLoader):
    """YAML seguro que además rechaza claves repetidas."""

    def construct_mapping(self, node: Any, deep: bool = False) -> Any:
        keys = [key.value for key, _ in node.value if isinstance(key, yaml.ScalarNode)]
        if len(keys) != len(set(keys)):
            raise yaml.YAMLError("duplicate key")
        return super().construct_mapping(node, deep)


def validate_block_id(block_id: object) -> str:
    if not isinstance(block_id, str) or len(block_id) > 24 or not _ID_RE.fullmatch(block_id):
        raise BlockedError(Reason.INVALID_BLOCK_ID)
    if block_id.split(".")[0].upper() in _WINDOWS_RESERVED:
        raise BlockedError(Reason.INVALID_BLOCK_ID)
    return block_id


def block_slug(block_id: str) -> str:
    return block_id.lower().replace(".", "-")


def validate_branch_name(branch: object, block_id: str) -> str:
    """Solo ``claude/<slug>`` o ``claude/<slug>-algo``. ``main`` y similares no encajan."""
    pattern = rf"claude/{re.escape(block_slug(block_id))}(?:-[a-z0-9]+)*"
    if not isinstance(branch, str) or len(branch) > 100 or not re.fullmatch(pattern, branch):
        raise BlockedError(Reason.INVALID_BRANCH)
    return branch


def validate_path_pattern(pattern: object) -> str:
    if not isinstance(pattern, str) or not pattern or len(pattern) > 200:
        raise BlockedError(Reason.INVALID_SPEC, "path_pattern")
    if not _PATTERN_RE.fullmatch(pattern) or pattern.startswith("/") or pattern.endswith("/"):
        raise BlockedError(Reason.INVALID_SPEC, "path_pattern")
    segments = pattern.split("/")
    if any(s in ("", ".", "..", ".git") for s in segments):
        raise BlockedError(Reason.INVALID_SPEC, "path_pattern")
    if all(set(s) <= {"*"} for s in segments):
        raise BlockedError(Reason.INVALID_SPEC, "path_pattern_too_broad")
    return pattern


def glob_regex(pattern: str) -> re.Pattern[str]:
    """``**`` cruza carpetas y ``*`` no. Sin distinguir mayúsculas, como NTFS."""
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append(r"(?:[^/]+/)*")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(r".*")
            index += 2
        elif pattern[index] == "*":
            parts.append(r"[^/]*")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts), re.IGNORECASE)


def matches_any(path: str, patterns: Sequence[str]) -> bool:
    return any(glob_regex(pattern).fullmatch(path) for pattern in patterns)


def _is_clean_text(value: object) -> bool:
    """Sin caracteres de control ni de formato: podrían falsear la pantalla de aprobación."""
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= MAX_SPEC_TEXT_LENGTH
        and not any(unicodedata.category(c) in ("Cc", "Cf") for c in value)
    )


def _string_list(value: object, name: str, *, allow_empty: bool = True) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise BlockedError(Reason.INVALID_SPEC, name)
    if not all(_is_clean_text(item) for item in value):
        raise BlockedError(Reason.INVALID_SPEC, name)
    return tuple(value)


def parse_spec(raw: bytes, expected_id: str) -> Spec:
    """Valida una especificación. Es lista cerrada: un campo desconocido la invalida."""
    if len(raw) > MAX_SPEC_BYTES or b"\0" in raw:
        raise BlockedError(Reason.INVALID_SPEC, "size_or_binary")
    try:
        text = raw.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError as error:
        raise BlockedError(Reason.INVALID_SPEC, "encoding") from error
    if not text.startswith("---\n"):
        raise BlockedError(Reason.INVALID_SPEC, "front_matter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise BlockedError(Reason.INVALID_SPEC, "front_matter")
    try:
        data = yaml.load(text[4:end], Loader=_StrictLoader)
    except yaml.YAMLError as error:
        raise BlockedError(Reason.INVALID_SPEC, "yaml") from error
    if not isinstance(data, dict):
        raise BlockedError(Reason.INVALID_SPEC, "front_matter")
    if set(data) - SPEC_FIELDS:
        raise BlockedError(Reason.INVALID_SPEC, "unknown_field")
    if SPEC_FIELDS - set(data):
        raise BlockedError(Reason.INVALID_SPEC, "missing_field")

    if data["id"] != expected_id:
        raise BlockedError(Reason.INVALID_SPEC, "id_mismatch")
    validate_block_id(data["id"])
    title = data["title"]
    if not _is_clean_text(title) or len(title) > 200:
        raise BlockedError(Reason.INVALID_SPEC, "title")
    if data["base"] != BASE_BRANCH:
        raise BlockedError(Reason.NOT_ON_BASE, "spec_base")
    branch = validate_branch_name(data["branch"], data["id"])
    allowed = _string_list(data["allowed_paths"], "allowed_paths", allow_empty=False)
    forbidden = _string_list(data["forbidden_paths"], "forbidden_paths")
    for pattern in (*allowed, *forbidden):
        validate_path_pattern(pattern)
    for pattern in allowed:
        # Una ruta bloqueada siempre no se puede pedir, ni con comodines.
        if matches_any(pattern.replace("**", "x").replace("*", "x"), ALWAYS_FORBIDDEN):
            raise BlockedError(Reason.INVALID_SPEC, "allowed_path_always_forbidden")
    minutes = data["timeout_minutes"]
    if type(minutes) is not int or not 1 <= minutes <= MAX_TIMEOUT_MINUTES:
        raise BlockedError(Reason.INVALID_SPEC, "timeout_minutes")
    stop_conditions = _string_list(data["stop_conditions"], "stop_conditions")
    human_gates = _string_list(data["human_gates"], "human_gates")

    body = text[end + 5 :]
    for section in SPEC_SECTIONS:
        if not re.search(rf"^##\s+{re.escape(section)}\s*$", body, re.MULTILINE):
            raise BlockedError(Reason.INVALID_SPEC, "missing_section")

    return Spec(
        id=data["id"],
        title=title,
        base=data["base"],
        branch=branch,
        allowed_paths=allowed,
        forbidden_paths=forbidden,
        timeout_minutes=minutes,
        stop_conditions=stop_conditions,
        human_gates=human_gates,
        raw=raw,
        sha256=hashlib.sha256(raw).hexdigest(),
    )


# ---------------------------------------------------------------------------
# Alcance: siempre desde lo que dice Git
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    path: str
    status: str
    mode: str | None = None


def is_unsafe_path(path: str) -> bool:
    """Nombres que NTFS o Git pueden interpretar distinto de como se leen."""
    if not path or path.startswith("/") or "\\" in path or ":" in path:
        return True
    if "`" in path or any(unicodedata.category(c) in ("Cc", "Cf", "Cs") for c in path):
        return True
    if unicodedata.normalize("NFC", path) != path:
        return True
    for segment in path.split("/"):
        if segment in ("", ".", "..") or segment.lower() == ".git":
            return True
        if segment.endswith((".", " ")) or re.search(r"~\d", segment):
            return True
        if segment.split(".")[0].upper() in _WINDOWS_RESERVED:
            return True
    return False


def check_scope(changes: Sequence[Change], spec: Spec) -> None:
    """Lo prohibido gana a lo permitido; lo que no esté permitido queda prohibido."""
    if len(changes) > MAX_CHANGED_FILES:
        raise BlockedError(Reason.TOO_MANY_CHANGES)
    for change in changes:
        # Git termina en `/` un repositorio anidado que no sabe listar por dentro.
        if change.mode in ("120000", "160000") or change.path.endswith("/"):
            raise BlockedError(Reason.UNSAFE_FILE_MODE)
        if is_unsafe_path(change.path):
            raise BlockedError(Reason.UNSAFE_PATH)
        if matches_any(change.path, ALWAYS_FORBIDDEN) or matches_any(
            change.path, spec.forbidden_paths
        ):
            raise BlockedError(Reason.FORBIDDEN_PATH, change.path)
        if change.path.lower() in DECLARE_ONLY and change.path not in spec.allowed_paths:
            raise BlockedError(Reason.SCOPE_VIOLATION, change.path)
        if not matches_any(change.path, spec.allowed_paths):
            raise BlockedError(Reason.SCOPE_VIOLATION, change.path)


def collect_changes(git: Git) -> list[Change]:
    """Cambios reales frente a HEAD, sin detección de renombrados: cada lado cuenta."""
    changes: list[Change] = []
    raw = git.run("diff", "--raw", "--no-renames", "--no-abbrev", "-z", "HEAD").stdout
    tokens = _split_nul(raw)
    for meta, path in zip(tokens[::2], tokens[1::2], strict=True):
        fields = meta.lstrip(":").split(" ")
        changes.append(Change(path=path, status=fields[4][0], mode=fields[1]))
    untracked = git.run("ls-files", "--others", "--exclude-standard", "-z").stdout
    changes.extend(Change(path=path, status="A") for path in _split_nul(untracked))
    return changes


def unexpected_ignored_files(git: Git) -> list[str]:
    """Un archivo ignorado no aparece en el diff: por eso se pregunta aparte.

    Las cachés de los hooks y de los controles sí se toleran: nunca entran a un
    commit, porque aquí cada archivo se añade por su nombre.
    """
    raw = git.run(
        "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"
    ).stdout
    return [
        entry
        for entry in _split_nul(raw)
        if not ALLOWED_CACHE_DIRS & set(entry.rstrip("/").split("/"))
    ]


def _has_reparse_points(root: Path) -> bool:
    """Busca enlaces y junctions en toda la copia, también en carpetas ignoradas."""
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in (*directories, *files):
            candidate = Path(folder) / name
            if candidate.is_symlink() or candidate.is_junction():
                return True
    return False


def _check_filesystem(worktree: Path, changes: Sequence[Change]) -> None:
    if _has_reparse_points(worktree):
        raise BlockedError(Reason.UNSAFE_FILE_MODE)
    for change in changes:
        if change.status == "D":
            continue
        target = worktree / change.path
        if target.is_file() and target.stat().st_size > MAX_FILE_BYTES:
            raise BlockedError(Reason.FILE_TOO_LARGE, change.path)


def _controlled_tables(text: str) -> dict[str, object]:
    data = tomllib.loads(text)
    project = data.get("project", {})
    return {
        "requires-python": project.get("requires-python"),
        "dependencies": project.get("dependencies"),
        "optional-dependencies": project.get("optional-dependencies"),
        "dependency-groups": data.get("dependency-groups"),
        "build-system": data.get("build-system"),
        # Desde aquí se podría desactivar un control: ruff, mypy o pytest.
        "tool": data.get("tool"),
    }


def check_dependencies_unchanged(git: Git, worktree: Path, changes: Sequence[Change]) -> None:
    """El `.venv` compartido no representaría otras dependencias, ni otros controles."""
    paths = {change.path.lower() for change in changes}
    if "uv.lock" in paths:
        raise BlockedError(Reason.DEPENDENCY_CHANGE, "uv.lock")
    if "pyproject.toml" not in paths:
        return
    try:
        before = _controlled_tables(git.run("show", "HEAD:pyproject.toml").text)
        after = _controlled_tables((worktree / "pyproject.toml").read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError) as error:
        raise BlockedError(Reason.DEPENDENCY_CHANGE, "pyproject.toml") from error
    if before != after:
        raise BlockedError(Reason.DEPENDENCY_CHANGE, "pyproject.toml")


# ---------------------------------------------------------------------------
# Fotos del repositorio principal
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoSnapshot:
    """Detecta si algo tocó el repositorio principal. Detecta; no impide."""

    head: str
    head_ref: str
    status: bytes
    refs: tuple[str, ...]
    worktrees: tuple[str, ...]
    config_sha: str
    hooks_sha: str
    info_sha: str


def _file_sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "absent"


def _directory_sha(path: Path) -> str:
    """Huella de una carpeta: nombres y contenido, en orden estable."""
    digest = hashlib.sha256()
    if path.is_dir():
        for item in sorted(p for p in path.rglob("*") if p.is_file()):
            digest.update(item.relative_to(path).as_posix().encode("utf-8", "surrogateescape"))
            digest.update(item.read_bytes())
    return digest.hexdigest()


def _same_path(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _parse_worktrees(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        entry: dict[str, str] = {}
        for line in block.splitlines():
            key, _, value = line.partition(" ")
            entry[key] = value
        if "worktree" in entry:
            entries.append(entry)
    return entries


def common_git_dir(git: Git) -> Path:
    return (git.cwd / git.run("rev-parse", "--git-common-dir").text).resolve()


def capture_snapshot(git: Git, own_branch: str, own_worktree: Path) -> RepoSnapshot:
    common = common_git_dir(git)
    refs = git.run("for-each-ref", "--format=%(refname) %(objectname)").text.splitlines()
    worktrees = _parse_worktrees(git.run("worktree", "list", "--porcelain").text)
    return RepoSnapshot(
        head=git.run("rev-parse", "HEAD").text,
        head_ref=git.run("symbolic-ref", "HEAD").text,
        status=git.run("status", "--porcelain=v1", "--untracked-files=all", "-z").stdout,
        refs=tuple(line for line in refs if not line.startswith(f"refs/heads/{own_branch} ")),
        worktrees=tuple(
            f"{os.path.normcase(os.path.realpath(entry['worktree']))} {entry.get('HEAD', '')} "
            f"{entry.get('branch', 'detached')}"
            for entry in worktrees
            if not _same_path(entry["worktree"], own_worktree)
        ),
        config_sha=_file_sha(common / "config"),
        # Otro hook correría dentro del commit del runner; `info/attributes` podría
        # marcar un archivo como binario y esconderlo del escaneo de secretos.
        hooks_sha=_directory_sha(common / "hooks"),
        info_sha=_directory_sha(common / "info"),
    )


# ---------------------------------------------------------------------------
# Lock
# ---------------------------------------------------------------------------


class RunnerLock:
    """Bloqueo del sistema operativo: si el runner muere, se libera solo."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle: IO[bytes] | None = None

    def acquire(self) -> bool:
        handle = open(self._path, "a+b")  # noqa: SIM115 - debe quedar abierto
        try:
            # `msvcrt.locking` bloquea un rango desde la posición actual: el
            # archivo debe tener al menos ese byte para bloquear un rango real.
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if not _try_lock(handle):
                handle.close()
                return False
        except BaseException:
            handle.close()
            raise
        self._handle = handle
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            handle.seek(0)
            _unlock(handle)
        finally:
            handle.close()


if sys.platform == "win32":
    import msvcrt

    def _try_lock(handle: IO[bytes]) -> bool:
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True

    def _unlock(handle: IO[bytes]) -> None:
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock(handle: IO[bytes]) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(handle: IO[bytes]) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def acquire_lock(config: RunnerConfig) -> RunnerLock:
    lock = RunnerLock(config.state / "runner.lock")
    if not lock.acquire():
        raise BlockedError(Reason.LOCK_BUSY)
    return lock


def release_lock(lock: RunnerLock) -> None:
    lock.release()


# ---------------------------------------------------------------------------
# Ejecutor
# ---------------------------------------------------------------------------


class Executor(Protocol):
    """Quién edita la copia de trabajo. En O1.2 no hay ninguno real."""

    @property
    def kind(self) -> str: ...

    def command(self, worktree: Path, spec_path: str) -> tuple[str, ...] | None: ...


class NoChangeExecutor:
    """El ejecutor de la consola en O1.2: no edita nada y no lanza ningún proceso."""

    kind = "no_change"

    def command(self, worktree: Path, spec_path: str) -> tuple[str, ...] | None:
        return None


@dataclass(frozen=True)
class ClaudeExecutor:
    """Claude Code real, sin consola y solo para documentación (ADR 0037).

    ``argv_prefix`` solo lo usan los tests, para lanzar un Claude falso. No es
    accesible desde la consola, y lo que se ejecuta nunca sale de la especificación.
    """

    argv_prefix: tuple[str, ...] = ()
    kind: str = "claude"

    def command(self, worktree: Path, spec_path: str) -> tuple[str, ...] | None:
        raise BlockedError(Reason.PROCESS_CONTROL_FAILED, "claude_uses_its_own_route")


def validate_docs_only_spec(spec: Spec) -> None:
    """Con ejecutor real: rutas exactas de documentación, sin comodines."""
    if len(spec.allowed_paths) > CLAUDE_MAX_ALLOWED_PATHS:
        raise BlockedError(Reason.INVALID_SPEC, "claude_too_many_paths")
    for path in spec.allowed_paths:
        documentary = path == "README.md" or (path.startswith("docs/") and path.endswith(".md"))
        if "*" in path or not documentary or is_unsafe_path(path):
            raise BlockedError(Reason.INVALID_SPEC, "claude_docs_only")
        if _GITLEAKS_EXCLUDED_PATH_RE.search(path):
            raise BlockedError(Reason.INVALID_SPEC, "claude_path_not_scanned")


def normalized_origin(url: str) -> str:
    """Dueño y repositorio. `git@alias:x/y.git` y `https://github.com/x/y` son el mismo."""
    text = url.strip().lower()
    found = _ORIGIN_RE.fullmatch(text)
    path = found.group(1) if found is not None else text
    return re.sub(r"/+", "/", path).strip("/").removesuffix(".git").rstrip("/")


def ensure_not_real_repository(config: RunnerConfig, cwd: Path | None = None) -> None:
    """El primer run real exige otro gate humano y un cambio deliberado de esta función.

    La configuración sola no dice dónde se está: también se le pregunta a Git, por las URL
    de lectura y de envío. Protege de un error, no de quien cambie el remoto a propósito.
    """
    real = normalized_origin(EXPECTED_ORIGIN)
    if normalized_origin(config.expected_origin) == real:
        raise BlockedError(Reason.REAL_REPO_NOT_AUTHORIZED)
    git = Git(config, cwd or config.repo_root)
    for extra in ((), ("--push",)):
        found = git.run("remote", "get-url", *extra, "--all", "origin", check=False)
        urls = found.text.splitlines()
        # Sin URL configurada, Git responde con éxito y repite el nombre del remoto.
        if found.returncode != 0 or not urls or "origin" in urls:
            raise BlockedError(Reason.REAL_REPO_NOT_AUTHORIZED, "origin_unreadable")
        if any(normalized_origin(url) == real for url in urls):
            raise BlockedError(Reason.REAL_REPO_NOT_AUTHORIZED)


def check_claude_user_settings(config: RunnerConfig) -> None:
    """`--settings` está prohibido, y el primer evento no muestra permisos ni hooks de usuario.

    Por eso se exige, antes de lanzar, que la configuración de usuario sea la ya medida.
    """
    home = _claude_home(config)
    if (home / "settings.local.json").exists():
        raise BlockedError(Reason.CLAUDE_USER_SETTINGS_UNEXPECTED, "settings_local")
    if any((home / name).exists() for name in CLAUDE_USER_ALTERNATE_SETTINGS):
        raise BlockedError(Reason.CLAUDE_USER_SETTINGS_UNEXPECTED, "alternate_settings")
    path = home / "settings.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise BlockedError(Reason.CLAUDE_USER_SETTINGS_UNEXPECTED, "unreadable") from error
    if not isinstance(data, dict) or set(data) - CLAUDE_USER_SETTINGS_ALLOWED:
        raise BlockedError(Reason.CLAUDE_USER_SETTINGS_UNEXPECTED, "unexpected_keys")


def _claude_home(config: RunnerConfig) -> Path:
    return config.claude_home or Path.home() / ".claude"


def claude_policy_keys() -> list[str]:
    """Claves de política de Claude Code en el registro. Solo se comprueba que existan.

    Una clave que no se pueda abrir tampoco se da por ausente.
    """
    if sys.platform != "win32":
        return []
    import winreg

    found = []
    for hive, name in ((winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                winreg.OpenKey(hive, CLAUDE_POLICY_KEY, 0, winreg.KEY_READ | view).Close()
            except FileNotFoundError:
                continue
            except OSError:
                found.append(f"{name}:unreadable")
                continue
            found.append(name)
    return found


def check_claude_managed_settings(config: RunnerConfig) -> None:
    """Lo administrado se aplica aunque `--safe-mode` y `--restricted` desactiven lo demás.

    No se valida su contenido: con que exista, el bloque se detiene. La administrada remota
    solo se detecta por su caché, por eso esto también se repite al terminar.
    """
    managed = config.claude_managed_dir or CLAUDE_MANAGED_DIRS.get(
        sys.platform, CLAUDE_MANAGED_DIR_OTHER
    )
    if os.path.lexists(managed):
        raise BlockedError(Reason.CLAUDE_MANAGED_SETTINGS_PRESENT, "managed_dir")
    if claude_policy_keys():
        raise BlockedError(Reason.CLAUDE_MANAGED_SETTINGS_PRESENT, "policy_registry")
    home = _claude_home(config)
    if any(os.path.lexists(home / name) for name in CLAUDE_REMOTE_SETTINGS_FILES):
        raise BlockedError(Reason.CLAUDE_MANAGED_SETTINGS_PRESENT, "remote_settings")


def check_claude_project_settings(config: RunnerConfig, git: Git) -> None:
    """La copia no puede traer configuración de Claude ni MCP, aunque `--restricted` la ignore.

    Se revisa todo lo que hay en la copia, versionado o no, y también las carpetas que la
    contienen. Que 2.1.316 lea esas carpetas no se midió: se niega igual.
    """
    for path in _split_nul(git.run("ls-files", "-z", "--cached", "--others").stdout):
        parts = path.lower().split("/")
        if parts[-1] == ".mcp.json":
            raise BlockedError(Reason.CLAUDE_PROJECT_MCP_PRESENT)
        if ".claude" in parts[:-1]:
            where = parts.index(".claude")
            if where != 0 or len(parts) < 3 or parts[1] not in CLAUDE_PROJECT_DIRS_ALLOWED:
                raise BlockedError(Reason.CLAUDE_PROJECT_SETTINGS_PRESENT)
    user_home = _claude_home(config)
    for folder in (git.cwd, *git.cwd.parents):
        if os.path.lexists(folder / ".mcp.json"):
            raise BlockedError(Reason.CLAUDE_PROJECT_MCP_PRESENT, "folder")
        settings = folder / ".claude"
        # La configuración de usuario ya tiene su propio control.
        if folder == Path.home() or _same_path(settings, user_home):
            continue
        if any(
            os.path.lexists(settings / name) for name in ("settings.json", "settings.local.json")
        ):
            raise BlockedError(Reason.CLAUDE_PROJECT_SETTINGS_PRESENT, "folder")


def check_claude_configuration(config: RunnerConfig, git: Git) -> None:
    """Toda la configuración que Claude Code podría cargar, por defecto denegada."""
    check_claude_user_settings(config)
    check_claude_managed_settings(config)
    check_claude_project_settings(config, git)


def claude_deny_rules() -> tuple[str, ...]:
    """`.env` en sus 8 variantes de mayúsculas. La copia no debe tenerlo, pero se niega igual."""
    names = ("." + "".join(letters) for letters in itertools.product("eE", "nN", "vV"))
    return tuple(f"{tool}(**/{name}*)" for name in names for tool in CLAUDE_TOOLS)


def build_claude_argv(prefix: Sequence[str], spec: Spec, session_id: str) -> list[str]:
    """El comando completo. `Edit(ruta)` también autoriza `Write`; `Write(ruta)` solo no."""
    allowed = ["Read", "Glob", "Grep", *(f"Edit({path})" for path in spec.allowed_paths)]
    prompt = (
        f"Lee {SPEC_DIR}/{spec.id}.md y haz exactamente lo que pide, y nada más. Solo puedes "
        "crear o cambiar las rutas permitidas que indica. Si algo te lo impide, no busques "
        "otro camino: detente y declara blocked. Todo archivo debe terminar en un salto de "
        "línea, sin espacios al final de las líneas. Responde con el esquema; en files_changed "
        "pon las rutas relativas que cambiaste, con barra normal, y en reason un código corto."
    )
    argv = [
        *prefix,
        "-p",
        prompt,
        "--model",
        CLAUDE_MODEL,
        "--output-format",
        "stream-json",
        "--verbose",
        "--json-schema",
        json.dumps(CLAUDE_SCHEMA),
        "--session-id",
        session_id,
        "--no-session-persistence",
        "--permission-mode",
        "dontAsk",
        "--permission-prompts",
        "none",
        *CLAUDE_FROZEN_FLAGS,
        "--tools",
        ",".join(CLAUDE_TOOLS),
        "--allowedTools",
        ",".join(allowed),
        "--disallowedTools",
        ",".join(claude_deny_rules()),
    ]
    validate_claude_argv(argv, len(prefix))
    return argv


def validate_claude_argv(argv: Sequence[str], prefix_length: int = 1) -> None:
    """Última barrera antes de lanzar. Lista cerrada: cada opción una vez y con su valor exacto."""
    # Por el prefijo no entra ninguna opción: solo nombra el programa.
    if prefix_length < 1 or any(token.startswith("-") for token in argv[:prefix_length]):
        raise BlockedError(Reason.CLAUDE_UNSAFE_COMMAND, "prefix_option")
    values: dict[str, str] = {}
    seen: set[str] = set()
    index = prefix_length
    while index < len(argv):
        token = argv[index]
        if token in seen:
            raise BlockedError(Reason.CLAUDE_UNSAFE_COMMAND, "repeated_option")
        seen.add(token)
        if token in _CLAUDE_BARE_OPTIONS:
            index += 1
        elif token in _CLAUDE_VALUE_OPTIONS and index + 1 < len(argv):
            values[token] = argv[index + 1]
            index += 2
        elif token.split("=", 1)[0] in FORBIDDEN_CLAUDE_OPTIONS:
            raise BlockedError(Reason.CLAUDE_UNSAFE_COMMAND, "forbidden_option")
        else:
            raise BlockedError(Reason.CLAUDE_UNSAFE_COMMAND, "unknown_option")
    if seen != _CLAUDE_BARE_OPTIONS | _CLAUDE_VALUE_OPTIONS:
        raise BlockedError(Reason.CLAUDE_UNSAFE_COMMAND, "missing_option")
    # Sin consola, con independencia de `CLAUDE_TOOLS`. Claude Code separa por comas o espacios.
    for option in ("--tools", "--allowedTools", "--disallowedTools"):
        for rule in re.split(r"[,\s]+", values[option].strip()):
            if rule.split("(", 1)[0] not in _CLAUDE_FILE_TOOLS:
                raise BlockedError(Reason.CLAUDE_UNSAFE_COMMAND, "not_a_file_tool")
    for option, expected in (
        ("--model", CLAUDE_MODEL),
        ("--output-format", "stream-json"),
        ("--json-schema", json.dumps(CLAUDE_SCHEMA)),
        ("--permission-mode", "dontAsk"),
        ("--permission-prompts", "none"),
        ("--tools", ",".join(CLAUDE_TOOLS)),
        ("--disallowedTools", ",".join(claude_deny_rules())),
    ):
        if values[option] != expected:
            raise BlockedError(Reason.CLAUDE_UNSAFE_COMMAND, "wrong_value")
    for rule in values["--allowedTools"].split(","):
        if rule not in _CLAUDE_READ_RULES and not _CLAUDE_EDIT_RULE_RE.fullmatch(rule):
            raise BlockedError(Reason.CLAUDE_UNSAFE_COMMAND, "broad_rule")


def build_claude_env(config: RunnerConfig, trace_path: Path, temp_dir: Path) -> dict[str, str]:
    """Lista cerrada: nada de `ANTHROPIC_*`, `CLAUDE*` ni tokens heredados.

    De `extra_env`, que solo fijan los tests, pasan únicamente las variables del Claude falso
    y un proxy local: lo demás podría cambiar a dónde habla Claude, o su traza.
    """
    env = {name: os.environ[name] for name in CLAUDE_ENV_ALLOWLIST if os.environ.get(name)}
    git_folder = str(Path(find_git(config)).parent)
    if sys.platform == "win32":
        system = os.environ.get("SYSTEMROOT", r"C:\Windows")
        folders = [rf"{system}\System32", system, rf"{system}\System32\Wbem", git_folder]
    else:
        folders = ["/usr/bin", "/bin", git_folder]
    env["PATH"] = os.pathsep.join(folders)
    env["TEMP"] = env["TMP"] = env["TMPDIR"] = str(temp_dir)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "never",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "",
            "GIT_TRACE": str(trace_path),
            "GIT_OPTIONAL_LOCKS": "0",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        }
    )
    for name, value in config.extra_env.items():
        local_proxy = name == "HTTPS_PROXY" and value.startswith("http://127.0.0.1:")
        if local_proxy or name.startswith("FAKE_CLAUDE_"):
            env[name] = value
    return env


def check_claude_init(
    init: Mapping[str, Any], *, session_id: str | None = None, cwd: Path | None = None
) -> None:
    """Compara el primer evento de forma exacta. Una capacidad inesperada lo detiene todo."""
    if set(init) != CLAUDE_INIT_FIELDS:
        raise BlockedError(Reason.CLAUDE_CAPABILITY_MISMATCH, "fields")
    # Antes que la comparación exacta, y sin depender de `CLAUDE_EXPECTED_TOOLS`: ninguna consola.
    tools = init.get("tools")
    allowed_tools = _CLAUDE_FILE_TOOLS | _CLAUDE_OBSERVED_ONLY_TOOLS
    if not isinstance(tools, list) or any(tool not in allowed_tools for tool in tools):
        raise BlockedError(Reason.CLAUDE_CAPABILITY_MISMATCH, "not_a_file_tool")
    checks: dict[str, tuple[object, object]] = {
        "version": (init.get("claude_code_version"), CLAUDE_VERSION),
        "permission_mode": (init.get("permissionMode"), "dontAsk"),
        "tools": (sorted(init.get("tools") or []), CLAUDE_EXPECTED_TOOLS),
        "mcp": (init.get("mcp_servers"), []),
        "additional_directories": (init.get("additional_directories"), []),
        "skills": (init.get("skills"), []),
        "slash_commands": (init.get("slash_commands"), []),
        "agents": (sorted(init.get("agents") or []), CLAUDE_EXPECTED_AGENTS),
        "plugins": (
            init.get("plugins"),
            [
                {"name": name, "path": "builtin", "source": f"{name}@builtin"}
                for name in CLAUDE_EXPECTED_PLUGINS
            ],
        ),
        "api_key_source": (init.get("apiKeySource"), "none"),
        "model": (str(init.get("model")).startswith("claude-sonnet"), True),
    }
    for name, expected in CLAUDE_INIT_FIXED_VALUES.items():
        checks[name] = (init.get(name), expected)
    if session_id is not None:
        checks["session"] = (init.get("session_id"), session_id)
    if cwd is not None and not all(
        _same_path(str(init.get(name)), cwd) for name in ("cwd", "original_cwd")
    ):
        raise BlockedError(Reason.CLAUDE_CAPABILITY_MISMATCH, "cwd")
    for name, (seen, expected) in checks.items():
        if seen != expected:
            raise BlockedError(Reason.CLAUDE_CAPABILITY_MISMATCH, name)


def _stream_lines(data: bytes) -> list[str]:
    """Solo por `\\n`: `splitlines` también parte en U+2028, válido dentro de un texto JSON."""
    return data.decode("utf-8", "replace").split("\n")


def _stream_event(line: str) -> dict[str, Any] | None:
    try:
        event = json.loads(line)
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def _stream_events(data: bytes) -> list[dict[str, Any]]:
    events = (_stream_event(line) for line in _stream_lines(data))
    return [event for event in events if event is not None]


class _ClaudeInitWatcher:
    """Revisa cada evento `init` mientras Claude corre, para cortarlo si no coincide."""

    def __init__(self, log_path: Path, session_id: str, cwd: Path) -> None:
        self._log_path = log_path
        self._session_id = session_id
        self._cwd = cwd
        self._deadline = time.monotonic() + CLAUDE_INIT_TIMEOUT_SECONDS
        self._offset = 0
        self.seen = False
        self.error: BlockedError | None = None

    def inspect(self, data: bytes) -> None:
        """Un segundo `init` tampoco puede traer otra cosa. Lo que no se pueda leer detiene."""
        try:
            for line in _stream_lines(data):
                event = _stream_event(line)
                if event is None:
                    if line and _UNREADABLE_INIT_RE.search(line):
                        self._fail("unreadable_init")
                elif event.get("type") == "system" and event.get("subtype") == "init":
                    self.seen = True
                    check_claude_init(event, session_id=self._session_id, cwd=self._cwd)
        except BlockedError as error:
            self.error = self.error or error
        except Exception as error:
            # Como `BlockedError`, para que pase por la revisión de daños.
            self._fail(type(error).__name__)

    def _fail(self, detail: str) -> None:
        self.error = self.error or BlockedError(Reason.CLAUDE_CAPABILITY_MISMATCH, detail)

    def __call__(self) -> bool:
        """Lee lo nuevo del log en cada vuelta. Una línea a medias espera a la siguiente."""
        try:
            with open(self._log_path, "rb") as log:
                log.seek(self._offset)
                data = log.read(MAX_EXECUTOR_OUTPUT_BYTES)
        except OSError as error:
            self._fail(type(error).__name__)
            return True
        complete = data[: data.rfind(b"\n") + 1]
        self._offset += len(complete)
        # Primero lo leído: una capacidad inesperada ahí sigue siendo el motivo.
        self.inspect(complete)
        # Lo que quedara detrás no se llegaría a leer: no se da por revisado. Es salida
        # excesiva, no una capacidad vista.
        if len(data) >= MAX_EXECUTOR_OUTPUT_BYTES:
            self.error = self.error or BlockedError(
                Reason.EXECUTOR_OUTPUT_TOO_LARGE, "log_too_large"
            )
            return True
        if not self.seen and time.monotonic() > self._deadline:
            self.error = BlockedError(Reason.CLAUDE_INIT_MISSING, "no_init_in_time")
        return self.error is not None


def check_git_trace(text: str, *, require_commands: bool = True) -> None:
    """Los comandos Git que lanzó Claude Code, comparados con la lista exacta.

    Cualquier línea que no se reconozca también detiene: lo prohibido por defecto.
    """
    commands = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        found = _GIT_TRACE_RE.search(line)
        if found is None:
            raise BlockedError(Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED, "unknown_trace_line")
        entry = found.group(1)
        if entry.startswith(_GIT_TRACE_HARMLESS):
            continue
        match = _GIT_TRACE_COMMAND_RE.match(entry)
        if match is None or match.group(1).strip() not in CLAUDE_READ_ONLY_GIT:
            raise BlockedError(Reason.CLAUDE_GIT_COMMAND_NOT_ALLOWED)
        commands += 1
    if require_commands and not commands:
        raise BlockedError(Reason.CLAUDE_GIT_TRACE_MISSING)


def validate_structured_output(value: object) -> dict[str, Any]:
    """Valida la forma. Lo que Claude diga nunca decide el resultado: Git manda."""
    fields = {"result", "files_changed", "blocked", "reason"}
    if not isinstance(value, dict) or set(value) != fields:
        raise BlockedError(Reason.INVALID_STRUCTURED_OUTPUT, "fields")
    if value["result"] not in ("done", "blocked") or type(value["blocked"]) is not bool:
        raise BlockedError(Reason.INVALID_STRUCTURED_OUTPUT, "result")
    if (value["result"] == "blocked") != value["blocked"]:
        raise BlockedError(Reason.INVALID_STRUCTURED_OUTPUT, "incoherent")
    paths = value["files_changed"]
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise BlockedError(Reason.INVALID_STRUCTURED_OUTPUT, "files_changed")
    reason = value["reason"]
    if not isinstance(reason, str) or not _EXECUTOR_REASON_RE.fullmatch(reason):
        raise BlockedError(Reason.INVALID_STRUCTURED_OUTPUT, "reason")
    return value


def check_claude_report(structured: Mapping[str, Any], changes: Sequence[Change]) -> None:
    declared = {
        str(path).replace("\\", "/").removeprefix("./") for path in structured["files_changed"]
    }
    if declared != {change.path for change in changes}:
        raise BlockedError(Reason.CLAUDE_REPORT_MISMATCH)


def parse_executor_output(data: bytes) -> tuple[str, str | None]:
    """Contrato: la última línea no vacía es JSON con ``status`` y ``reason_code``."""
    lines = [line for line in data.decode("utf-8", "replace").splitlines() if line.strip()]
    if not lines:
        raise BlockedError(Reason.INVALID_EXECUTOR_OUTPUT)
    try:
        payload = json.loads(lines[-1])
    except ValueError as error:
        raise BlockedError(Reason.INVALID_EXECUTOR_OUTPUT) from error
    if not isinstance(payload, dict) or set(payload) != {"status", "reason_code"}:
        raise BlockedError(Reason.INVALID_EXECUTOR_OUTPUT)
    status, reason = payload["status"], payload["reason_code"]
    if status not in ("done", "blocked"):
        raise BlockedError(Reason.INVALID_EXECUTOR_OUTPUT)
    if reason is not None and (
        not isinstance(reason, str) or not _EXECUTOR_REASON_RE.fullmatch(reason)
    ):
        raise BlockedError(Reason.INVALID_EXECUTOR_OUTPUT)
    return status, reason


# ---------------------------------------------------------------------------
# Informe
# ---------------------------------------------------------------------------


@dataclass
class GateRecord:
    name: str
    returncode: int | None
    duration: float
    summary: str = ""


@dataclass
class RunReport:
    block_id: str
    title: str = ""
    spec_sha256: str = ""
    branch: str = ""
    base_sha: str = ""
    spec_commit: str = ""
    content_commit: str = ""
    tree: str = ""
    executor_kind: str = ""
    executor_returncode: int | None = None
    executor_status: str = ""
    executor_duration: float = 0.0
    executor_version: str = ""
    executor_session: str = ""
    structured_output: dict[str, Any] | None = None
    changes: list[Change] = field(default_factory=list)
    profile: str = ""
    gates: list[GateRecord] = field(default_factory=list)
    omitted_tests: tuple[str, ...] = ()
    secret_scans: list[tuple[str, str]] = field(default_factory=list)
    result: Result = Result.BLOCKED
    reason: Reason | None = None
    detail: str = ""
    # Si el ejecutor real se detiene: por qué se detuvo, y qué encontró la revisión de daños.
    primary_reason: Reason | None = None
    damage_check: str = ""
    worktree: Path | None = None
    run_dir: Path | None = None
    # Solo para la revisión de daños. Nunca se escribe en la evidencia.
    claude_git_trace: str | None = field(default=None, repr=False)


def render_evidence(report: RunReport) -> str:
    """Se construye campo a campo. Nunca se copia la salida de un proceso."""
    lines = [
        f"# Evidencia de ejecución — {report.block_id}",
        "",
        f"Generada por `scripts/orchestrator.py`, versión {RUNNER_VERSION}. "
        "Sin push, sin PR y sin merge.",
        "",
        "## Identidad",
        "",
        f"- Bloque: `{report.block_id}`",
        f"- Título: {report.title}",
        f"- Huella de la especificación (SHA-256): `{report.spec_sha256}`",
        "",
        "## Git",
        "",
        f"- Rama: `{report.branch}`",
        f"- Commit base: `{report.base_sha}`",
        f"- Commit de la especificación: `{report.spec_commit}`",
        f"- Commit de los cambios: `{report.content_commit or 'sin cambios'}`",
        f"- Árbol verificado: `{report.tree or 'sin cambios'}`",
        "",
        "## Ejecutor",
        "",
        f"- Tipo: `{report.executor_kind}`",
        f"- Código de salida: `{report.executor_returncode}`",
        f"- Estado declarado: `{report.executor_status}`",
        f"- Duración: {report.executor_duration:.1f} s",
        *(
            [
                f"- Versión validada: `{report.executor_version}`",
                f"- Sesión, sin transcripción guardada: `{report.executor_session}`",
            ]
            if report.executor_version
            else []
        ),
        "",
        "## Alcance",
        "",
        f"- Archivos cambiados, según Git: {len(report.changes)}",
    ]
    lines.extend(f"  - `{change.status}` `{change.path}`" for change in report.changes)
    lines += ["", "## Controles", "", f"- Perfil: `{report.profile}`"]
    if report.gates:
        lines += ["", "| Control | Código | Duración | Resumen |", "|---|---|---|---|"]
        lines.extend(
            f"| `{gate.name}` | `{gate.returncode}` | {gate.duration:.1f} s | "
            f"{gate.summary or '—'} |"
            for gate in report.gates
        )
    if report.omitted_tests:
        lines += ["", "Pruebas omitidas en Windows, conocidas y declaradas:", ""]
        lines.extend(
            f"- `{test}`: {WINDOWS_KNOWN_TEST_FAILURES[test]}" for test in report.omitted_tests
        )
    lines += ["", "## Secretos", ""]
    lines.extend(f"- `{stage}`: {outcome}" for stage, outcome in report.secret_scans)
    if report.result is Result.VERIFIED_LOCAL:
        # Esta evidencia no puede citar su propio escaneo: si falla, su commit no existe.
        lines.append("- `evidence`: escaneada antes de este commit")
    lines += ["", "## Resultado", "", f"- Resultado: `{report.result.value}`"]
    if report.reason is not None:
        lines.append(f"- Motivo: `{report.reason.value}`")
    if report.primary_reason is not None:
        lines.append(f"- Motivo de la parada del ejecutor: `{report.primary_reason.value}`")
        lines.append(f"- Revisión de daños tras la parada: `{report.damage_check}`")
    lines.append("")
    return "\n".join(lines)


def validate_evidence_text(text: str, config: RunnerConfig) -> None:
    """Última barrera: sin rutas absolutas, sin rutas personales, sin secretos conocidos."""
    if re.search(r"[A-Za-z]:[\\/]|\\Users\\|/home/|/Users/|%USERPROFILE%", text):
        raise BlockedError(Reason.EVIDENCE_REJECTED, "absolute_path")
    for private in (config.external_root, config.repo_root):
        if str(private) in text or private.as_posix() in text:
            raise BlockedError(Reason.EVIDENCE_REJECTED, "absolute_path")
    if scrub_text(text) != text:
        raise BlockedError(Reason.EVIDENCE_REJECTED, "secret_pattern")


# ---------------------------------------------------------------------------
# Validaciones iniciales
# ---------------------------------------------------------------------------


def ensure_external_dirs(config: RunnerConfig) -> None:
    root = Path(os.path.realpath(config.external_root))
    repo = Path(os.path.realpath(config.repo_root))
    if root.is_relative_to(repo) or any("onedrive" in part.lower() for part in root.parts):
        raise BlockedError(Reason.UNSAFE_EXTERNAL_ROOT)
    for folder in (config.inbox, config.worktrees, config.logs, config.state):
        folder.mkdir(parents=True, exist_ok=True)


def validate_spec(config: RunnerConfig, block_id: str) -> Spec:
    path = config.inbox / f"{block_id}.md"
    if not path.is_file() or path.is_symlink():
        raise BlockedError(Reason.SPEC_NOT_FOUND)
    if path.stat().st_size > MAX_SPEC_BYTES:
        raise BlockedError(Reason.INVALID_SPEC, "size_or_binary")
    spec = parse_spec(path.read_bytes(), block_id)
    if (config.repo_root / SPEC_DIR / f"{block_id}.md").exists():
        raise BlockedError(Reason.SPEC_ALREADY_USED)
    return spec


def validate_repository(config: RunnerConfig, git: Git) -> Path:
    """Devuelve la carpeta común de Git, tras confirmar que este es el repositorio autorizado."""
    if not _same_path(git.run("rev-parse", "--show-toplevel").text, config.repo_root):
        raise BlockedError(Reason.WRONG_REPOSITORY)
    git_dir = (git.cwd / git.run("rev-parse", "--git-dir").text).resolve()
    common = common_git_dir(git)
    if not _same_path(git_dir, common):
        raise BlockedError(Reason.LAUNCHED_FROM_LINKED_WORKTREE)
    if git.run("remote", "get-url", "origin").text != config.expected_origin:
        raise BlockedError(Reason.WRONG_ORIGIN)
    if not (common / "hooks" / "pre-commit").is_file():
        raise BlockedError(Reason.HOOK_MISSING)
    # Git devuelve 1 si no existe. Un valor vacío también desactivaría los hooks.
    if git.run("config", "--get", "core.hooksPath", check=False).returncode != 1:
        raise BlockedError(Reason.HOOKS_PATH_OVERRIDDEN)
    return common


def validate_base(git: Git) -> str:
    """Devuelve el SHA base, si el clon, ``origin/main`` y el remoto coinciden."""
    if git.run("symbolic-ref", "--short", "HEAD", check=False).text != BASE_BRANCH:
        raise BlockedError(Reason.NOT_ON_BASE)
    if git.run("status", "--porcelain=v1", "--untracked-files=all", "-z").stdout:
        raise BlockedError(Reason.DIRTY_WORKING_TREE)
    head = git.run("rev-parse", "HEAD").text
    tracked = git.run("rev-parse", f"refs/remotes/origin/{BASE_BRANCH}", check=False).text
    if not _SHA_RE.fullmatch(head) or head != tracked:
        raise BlockedError(Reason.HEAD_MISALIGNED)
    remote = git.run("ls-remote", "origin", f"refs/heads/{BASE_BRANCH}", check=False)
    if remote.returncode != 0:
        raise BlockedError(Reason.REMOTE_UNREACHABLE)
    if remote.text.split("\t")[0] != head:
        raise BlockedError(Reason.REMOTE_MISALIGNED)
    return head


def validate_branch_available(git: Git, branch: str) -> None:
    if git.run("check-ref-format", "--branch", branch, check=False).returncode != 0:
        raise BlockedError(Reason.INVALID_BRANCH)
    if (
        git.run("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode
        == 0
    ):
        raise BlockedError(Reason.BRANCH_EXISTS)
    remote = git.run("ls-remote", "origin", f"refs/heads/{branch}", check=False)
    if remote.returncode != 0:
        raise BlockedError(Reason.REMOTE_UNREACHABLE)
    if remote.text:
        raise BlockedError(Reason.BRANCH_EXISTS)


def worktree_path(config: RunnerConfig, block_id: str) -> Path:
    """La ruta la calcula el código: nunca sale de la especificación."""
    return config.worktrees / block_slug(block_id)


def _validate_common(config: RunnerConfig, git: Git, block_id: str) -> tuple[Spec, str]:
    spec = validate_spec(config, block_id)
    validate_repository(config, git)
    base_sha = validate_base(git)
    validate_branch_available(git, spec.branch)
    if worktree_path(config, block_id).exists():
        raise BlockedError(Reason.WORKTREE_EXISTS)
    return spec, base_sha


# ---------------------------------------------------------------------------
# Copia de trabajo
# ---------------------------------------------------------------------------


def prepare_worktree(config: RunnerConfig, git: Git, spec: Spec, base_sha: str) -> Path:
    """Crea la copia y su rama desde el SHA verificado, sin seguimiento de ninguna rama."""
    path = worktree_path(config, spec.id)
    if not _same_path(path.parent, config.worktrees):
        raise BlockedError(Reason.WORKTREE_FAILED, "path_outside_root")
    added = git.run(
        "worktree", "add", "--no-track", "-b", spec.branch, str(path), base_sha, check=False
    )
    if added.returncode != 0:
        _rollback_worktree(git, path, spec.branch)
        raise BlockedError(Reason.WORKTREE_FAILED)
    return path


def _rollback_worktree(git: Git, path: Path, branch: str) -> None:
    entries = _parse_worktrees(git.run("worktree", "list", "--porcelain", check=False).text)
    if any(_same_path(entry["worktree"], path) for entry in entries):
        git.run("worktree", "remove", str(path), check=False)
    git.run("branch", "-d", branch, check=False)


def _stage(git: Git, paths: Sequence[str]) -> None:
    git.run("add", "--", *paths, literal_paths=True)


def _commit(git: Git, message: str) -> str:
    """Commit con hooks. No existe ninguna forma de saltárselos en este archivo."""
    committed = git.run("commit", "-m", message, check=False, timeout=COMMIT_TIMEOUT_SECONDS)
    if committed.returncode != 0:
        raise BlockedError(Reason.COMMIT_FAILED)
    return git.run("rev-parse", "HEAD").text


# ---------------------------------------------------------------------------
# Secretos y controles
# ---------------------------------------------------------------------------


def _run_logged(
    config: RunnerConfig,
    argv: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
    log_path: Path,
    on_poll: Callable[[], bool] | None = None,
    allow_claude: bool = False,
) -> tuple[ProcessResult, bytes]:
    """Ejecuta con log y devuelve su final. El log se limpia siempre, incluso con Ctrl+C."""
    try:
        with open(log_path, "wb") as log:
            result = run_process(
                argv,
                cwd=cwd,
                env=env,
                timeout=timeout,
                stdout=log,
                kill_wait=config.kill_wait_seconds,
                max_output=config.max_executor_output,
                on_poll=on_poll,
                allow_claude=allow_claude,
            )
        # Última pasada antes de limpiar: lo escrito desde la vuelta anterior.
        if on_poll is not None:
            on_poll()
        with open(log_path, "rb") as log:
            log.seek(0, os.SEEK_END)
            log.seek(max(0, log.tell() - MAX_LOG_TAIL_BYTES))
            tail = log.read()
    finally:
        scrub_file(log_path)
    return result, tail


def check_staged_content(git: Git) -> None:
    """Lo que gitleaks no revisaría: binarios y líneas marcadas para que las ignore."""
    for entry in _split_nul(git.run("diff", "--cached", "--numstat", "-z", "HEAD").stdout):
        if entry.startswith("-\t"):
            raise BlockedError(Reason.SECRET_SCAN_EVADED, "binary")
    if b"gitleaks:allow" in git.run("diff", "--cached", "HEAD").stdout:
        raise BlockedError(Reason.SECRET_SCAN_EVADED, "allow_marker")


def scan_secrets(
    config: RunnerConfig, worktree: Path, run_dir: Path, stage: str, report: RunReport
) -> None:
    """Gitleaks sobre lo que está en staging. Una omisión cuenta como fallo."""
    result, tail = _run_logged(
        config,
        [*config.scanner_command(), "run", "gitleaks"],
        cwd=worktree,
        env=build_env(config),
        timeout=SECRET_SCAN_TIMEOUT_SECONDS,
        log_path=run_dir / f"secrets-{stage}.log",
    )
    text = tail.decode("utf-8", "replace")
    if result.orphan_suspected:
        raise BlockedError(Reason.ORPHAN_SUSPECTED, stage)
    if result.timed_out or result.output_exceeded:
        report.secret_scans.append((stage, "timeout"))
        raise BlockedError(Reason.SECRET_SCAN_FAILED, stage)
    if "Skipped" in text:
        report.secret_scans.append((stage, "omitido"))
        raise BlockedError(Reason.SECRET_SCAN_SKIPPED, stage)
    if result.returncode == 0 and "Passed" in text:
        report.secret_scans.append((stage, "aprobado"))
        return
    if "leaks found" in text or "Finding:" in text:
        report.secret_scans.append((stage, "detectado"))
        raise BlockedError(Reason.SECRET_DETECTED, stage)
    report.secret_scans.append((stage, "fallido"))
    raise BlockedError(Reason.SECRET_SCAN_FAILED, stage)


def gate_profile(changes: Sequence[Change]) -> str:
    """Lo decide el diff real. Ante la duda, se ejecuta todo."""
    if not changes:
        return "none"
    for change in changes:
        path = change.path
        if not (path == "README.md" or (path.startswith("docs/") and path.endswith(".md"))):
            return "code"
    return "docs"


_PYTEST_SUMMARY_RE = re.compile(
    r"\b(\d+) (passed|failed|skipped|deselected|errors?|xfailed|xpassed|warnings?)\b"
)


def _pytest_summary(log_text: str) -> str:
    for line in reversed(log_text.splitlines()):
        if " in " in line and _PYTEST_SUMMARY_RE.search(line):
            return ", ".join(f"{n} {w}" for n, w in _PYTEST_SUMMARY_RE.findall(line))
    return ""


def run_quality_gates(
    config: RunnerConfig, git: Git, worktree: Path, run_dir: Path, report: RunReport
) -> None:
    """Comandos fijos, en orden. Se detiene en el primer fallo."""
    checked = git.run("diff", "--cached", "--check", "HEAD", check=False)
    report.gates.append(GateRecord("git_diff_check", checked.returncode, 0.0))
    if checked.returncode != 0:
        raise BlockedError(Reason.QUALITY_GATE_FAILED, "git_diff_check")
    if report.profile != "code":
        return
    env = build_env(config, {"PYTHONPATH": str(worktree / "src")})
    for gate in config.gates():
        report.omitted_tests = (*report.omitted_tests, *gate.omitted_tests)
        result, tail = _run_logged(
            config,
            gate.argv,
            cwd=worktree,
            env=env,
            timeout=gate.timeout,
            log_path=run_dir / f"gate-{gate.name}.log",
        )
        text = tail.decode("utf-8", "replace")
        summary = _pytest_summary(text) if gate.name == "pytest" else ""
        report.gates.append(GateRecord(gate.name, result.returncode, result.duration, summary))
        if result.orphan_suspected:
            raise BlockedError(Reason.ORPHAN_SUSPECTED, gate.name)
        if result.timed_out:
            raise BlockedError(Reason.QUALITY_GATE_TIMEOUT, gate.name)
        if result.returncode != 0 or result.output_exceeded:
            raise BlockedError(Reason.QUALITY_GATE_FAILED, gate.name)
        # `--deselect` también omite lo que empiece igual: el número debe ser exacto.
        expected = f"{len(gate.omitted_tests)} deselected"
        if gate.omitted_tests and expected not in summary.split(", "):
            raise BlockedError(Reason.QUALITY_GATE_FAILED, "omission_count")


def verify_tree_unchanged(git: Git, head: str, tree: str) -> None:
    """Lo que se probó debe ser exactamente lo que se va a commitear."""
    if git.run("rev-parse", "HEAD").text != head or git.run("write-tree").text != tree:
        raise BlockedError(Reason.GATE_MODIFIED_TREE)
    if git.run("diff", "--name-only", "-z").stdout:
        raise BlockedError(Reason.GATE_MODIFIED_TREE)
    if git.run("ls-files", "--others", "--exclude-standard", "-z").stdout:
        raise BlockedError(Reason.GATE_MODIFIED_TREE)
    if unexpected_ignored_files(git):
        raise BlockedError(Reason.GATE_MODIFIED_TREE)


# ---------------------------------------------------------------------------
# Recorrido
# ---------------------------------------------------------------------------


def run_executor(
    config: RunnerConfig,
    executor: Executor,
    spec: Spec,
    worktree: Path,
    run_dir: Path,
    report: RunReport,
) -> None:
    report.executor_kind = executor.kind
    if isinstance(executor, ClaudeExecutor):
        run_claude_executor(config, executor, spec, worktree, run_dir, report)
        return
    spec_path = f"{SPEC_DIR}/{spec.id}.md"
    command = executor.command(worktree, spec_path)
    if command is None:
        report.executor_status = "done"
        return
    timeout = config.executor_timeout_seconds or spec.timeout_minutes * 60.0
    result, tail = _run_logged(
        config,
        command,
        cwd=worktree,
        env=build_env(config),
        timeout=timeout,
        log_path=run_dir / "executor.log",
    )
    report.executor_returncode = result.returncode
    report.executor_duration = result.duration
    if result.orphan_suspected:
        raise BlockedError(Reason.ORPHAN_SUSPECTED)
    if result.timed_out:
        raise BlockedError(Reason.EXECUTOR_TIMEOUT)
    if result.output_exceeded:
        raise BlockedError(Reason.EXECUTOR_OUTPUT_TOO_LARGE)
    if result.left_processes:
        raise BlockedError(Reason.EXECUTOR_LEFT_PROCESSES)
    if result.returncode != 0:
        raise BlockedError(Reason.EXECUTOR_FAILED)
    status, reason = parse_executor_output(tail)
    report.executor_status = status
    if status == "blocked":
        raise BlockedError(Reason.EXECUTOR_BLOCKED, reason or "")


def claude_prefix(config: RunnerConfig, executor: ClaudeExecutor) -> tuple[str, ...]:
    if executor.argv_prefix:
        return executor.argv_prefix
    found = _find_program(config, "claude")
    if found is None:
        raise BlockedError(Reason.CLAUDE_NOT_FOUND)
    return (found,)


def check_claude_version(
    config: RunnerConfig, prefix: Sequence[str], env: Mapping[str, str], cwd: Path
) -> str:
    with tempfile.TemporaryFile() as out:
        result = run_process(
            [*prefix, "--version"],
            cwd=cwd,
            env=env,
            timeout=GIT_TIMEOUT_SECONDS,
            stdout=out,
            kill_wait=config.kill_wait_seconds,
            allow_claude=True,
        )
        out.seek(0)
        words = out.read(200).decode("utf-8", "replace").split()
    if result.orphan_suspected:
        raise BlockedError(Reason.ORPHAN_SUSPECTED, "version_check")
    if result.returncode != 0 or not words or words[0] != CLAUDE_VERSION:
        raise BlockedError(Reason.CLAUDE_VERSION_MISMATCH)
    return words[0]


def _read_claude_trace(path: Path) -> str:
    """Lo que no se pudo leer no se da por limpio: una línea desconocida detiene el bloque."""
    try:
        if not path.is_file():
            return ""
        if path.stat().st_size > MAX_LOG_TAIL_BYTES:
            return "unknown: trace too large"
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unknown: trace unreadable"


def run_claude_executor(
    config: RunnerConfig,
    executor: ClaudeExecutor,
    spec: Spec,
    worktree: Path,
    run_dir: Path,
    report: RunReport,
) -> None:
    # También aquí: esta función es pública, y estas dos barreras no dependen de quién llame.
    ensure_not_real_repository(config, worktree)
    validate_docs_only_spec(spec)
    # Las rutas de usuario y administrada solo se cambian para el Claude falso: el real lee
    # siempre las verdaderas, y los controles deben mirar esas.
    if not executor.argv_prefix and (config.claude_home or config.claude_managed_dir):
        raise BlockedError(Reason.CLAUDE_UNSAFE_COMMAND, "test_only_paths")
    worktree_git = Git(config, worktree, run_dir / "git.log")
    check_claude_configuration(config, worktree_git)
    prefix = claude_prefix(config, executor)
    trace_path = run_dir / "claude-git-trace.log"
    temp_dir = run_dir / "claude-tmp"
    temp_dir.mkdir(exist_ok=True)
    env = build_claude_env(config, trace_path, temp_dir)
    # Desde aquí Claude puede correr, ya con `--version`: una traza sin leer no es limpia.
    report.claude_git_trace = "unknown: trace not read"
    report.executor_version = check_claude_version(config, prefix, env, worktree)
    report.executor_session = str(uuid.uuid4())
    argv = build_claude_argv(prefix, spec, report.executor_session)
    log_path = run_dir / "executor.log"
    watcher = _ClaudeInitWatcher(log_path, report.executor_session, worktree)
    try:
        result, tail = _run_logged(
            config,
            argv,
            cwd=worktree,
            env=env,
            timeout=config.executor_timeout_seconds or spec.timeout_minutes * 60.0,
            log_path=log_path,
            on_poll=watcher,
            allow_claude=True,
        )
    finally:
        # Se lee antes de limpiar: la limpieza recorta y podría esconder una línea. Queda en
        # el informe también si se sale por Ctrl+C o por un error, para la revisión de daños.
        try:
            report.claude_git_trace = _read_claude_trace(trace_path)
        finally:
            scrub_file(trace_path)
    trace_text = report.claude_git_trace or ""
    report.executor_returncode = result.returncode
    report.executor_duration = result.duration
    # La última línea puede no terminar en salto de línea.
    watcher.inspect(tail)
    # Un comando Git prohibido pesa más que cualquier otro motivo de parada.
    check_git_trace(trace_text, require_commands=False)
    if result.orphan_suspected:
        raise BlockedError(Reason.ORPHAN_SUSPECTED)
    if watcher.error is not None:
        raise watcher.error
    if result.timed_out:
        raise BlockedError(Reason.EXECUTOR_TIMEOUT)
    if result.output_exceeded:
        raise BlockedError(Reason.EXECUTOR_OUTPUT_TOO_LARGE)
    if result.left_processes:
        raise BlockedError(Reason.EXECUTOR_LEFT_PROCESSES)
    if not watcher.seen:
        raise BlockedError(Reason.CLAUDE_INIT_MISSING)
    if result.returncode != 0:
        raise BlockedError(Reason.EXECUTOR_FAILED)
    check_claude_version(config, prefix, env, worktree)
    # La administrada remota solo se ve por su caché, que puede aparecer durante la ejecución.
    check_claude_configuration(config, worktree_git)
    check_git_trace(trace_text)
    final = next((e for e in reversed(_stream_events(tail)) if e.get("type") == "result"), None)
    if final is None or final.get("is_error"):
        raise BlockedError(Reason.EXECUTOR_FAILED, "no_result")
    if final.get("session_id") != report.executor_session:
        raise BlockedError(Reason.CLAUDE_CAPABILITY_MISMATCH, "result_session")
    report.structured_output = validate_structured_output(final.get("structured_output"))
    report.executor_status = report.structured_output["result"]
    if report.structured_output["blocked"]:
        raise BlockedError(Reason.EXECUTOR_BLOCKED, report.structured_output["reason"])


def verify_after_executor(
    git: Git,
    main_git: Git,
    spec: Spec,
    worktree: Path,
    spec_commit: str,
    snapshot: RepoSnapshot,
    git_dir: str,
) -> None:
    """Comprueba por su cuenta lo que el ejecutor haya hecho, sin preguntárselo."""
    # Con su `.git` apuntando a otro sitio, todo lo demás hablaría de otro repositorio.
    if git.run("rev-parse", "--absolute-git-dir", check=False).text != git_dir:
        raise BlockedError(Reason.REPO_INVARIANT_BROKEN, "git_dir")
    tip = main_git.run("rev-parse", f"refs/heads/{spec.branch}", check=False).text
    if tip != spec_commit:
        raise BlockedError(Reason.HEAD_MOVED)
    current_ref = git.run("symbolic-ref", "HEAD", check=False).text
    if (
        current_ref != f"refs/heads/{spec.branch}"
        or git.run("rev-parse", "HEAD").text != spec_commit
    ):
        raise BlockedError(Reason.HEAD_MOVED)
    spec_file = worktree / SPEC_DIR / f"{spec.id}.md"
    if not spec_file.is_file() or spec_file.read_bytes() != spec.raw:
        raise BlockedError(Reason.SPEC_TAMPERED)
    if git.run("diff", "--cached", "--name-only", "-z", "HEAD").stdout:
        raise BlockedError(Reason.INDEX_TAMPERED)
    # `assume-unchanged` y `skip-worktree` esconderían una edición del diff.
    for entry in _split_nul(git.run("ls-files", "-v", "-z").stdout):
        if not entry.startswith("H "):
            raise BlockedError(Reason.INDEX_TAMPERED)
    if capture_snapshot(main_git, spec.branch, worktree) != snapshot:
        raise BlockedError(Reason.REPO_INVARIANT_BROKEN)
    if unexpected_ignored_files(git):
        raise BlockedError(Reason.IGNORED_FILE_PRESENT)


def _stop_reason(stopped: BaseException) -> Reason:
    if isinstance(stopped, BlockedError):
        return stopped.reason
    if isinstance(stopped, KeyboardInterrupt):
        return Reason.INTERRUPTED
    return Reason.INTERNAL_ERROR


def _raise_if_damage_after_stop(
    config: RunnerConfig,
    git: Git,
    main_git: Git,
    spec: Spec,
    worktree: Path,
    report: RunReport,
    snapshot: RepoSnapshot,
    git_dir: str,
    stopped: BaseException,
) -> None:
    """Cualquier salida del ejecutor real pasa por aquí: una parada, Ctrl+C o un error.

    Conserva el motivo de la parada. Si encuentra un daño, ese daño es el motivo del bloque;
    si no, la parada sigue su curso con su motivo original.
    """
    primary = _stop_reason(stopped)
    report.primary_reason = primary
    try:
        # El orden de siempre: un daño en el repositorio pesa más que un comando Git prohibido,
        # este más que la configuración de Claude, y todo más que el motivo de la parada.
        verify_after_executor(git, main_git, spec, worktree, report.spec_commit, snapshot, git_dir)
        check_scope(collect_changes(git), spec)
        _check_filesystem(worktree, [])
        # Tras Ctrl+C o un error, la traza aún no se había revisado.
        if report.claude_git_trace is not None:
            check_git_trace(report.claude_git_trace, require_commands=False)
        check_claude_configuration(config, git)
    except BlockedError as damage:
        report.damage_check = damage.reason.value
        if damage.reason is primary:
            return
        raise BlockedError(damage.reason, f"after_{primary.value}") from stopped
    except KeyboardInterrupt:
        # Un segundo Ctrl+C corta la revisión: queda dicho que no terminó.
        report.damage_check = "interrupted"
        raise
    except Exception as error:
        # Sin poder revisar, no se puede decir que no hubo daño.
        report.damage_check = Reason.DAMAGE_CHECK_FAILED.value
        raise BlockedError(Reason.DAMAGE_CHECK_FAILED, f"after_{primary.value}") from error
    report.damage_check = "no_damage"


def write_sanitized_evidence(
    config: RunnerConfig, git: Git, worktree: Path, report: RunReport
) -> None:
    """Escribe la evidencia en la rama. Solo se llama si el resultado es ``verified_local``."""
    report.result = Result.VERIFIED_LOCAL
    text = render_evidence(report)
    validate_evidence_text(text, config)
    path = worktree / EVIDENCE_DIR / f"{report.block_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _pipeline(
    config: RunnerConfig,
    block_id: str,
    executor: Executor,
    confirm: Callable[[Spec], bool],
    run_dir: Path,
    report: RunReport,
) -> None:
    real_executor = isinstance(executor, ClaudeExecutor)
    if real_executor:
        ensure_not_real_repository(config)
    main_git = Git(config, config.repo_root, run_dir / "git.log")
    spec, base_sha = _validate_common(config, main_git, block_id)
    report.title = spec.title
    report.spec_sha256 = spec.sha256
    report.branch = spec.branch
    report.base_sha = base_sha
    if real_executor:
        validate_docs_only_spec(spec)
    if not confirm(spec):
        raise BlockedError(Reason.NOT_APPROVED)

    worktree = worktree_path(config, block_id)
    snapshot = capture_snapshot(main_git, spec.branch, worktree)
    prepare_worktree(config, main_git, spec, base_sha)
    report.worktree = worktree
    git = Git(config, worktree, run_dir / "git.log")
    git_dir = git.run("rev-parse", "--absolute-git-dir").text

    # La especificación se escanea y se commitea antes de que el ejecutor la vea.
    spec_rel = f"{SPEC_DIR}/{spec.id}.md"
    spec_file = worktree / spec_rel
    spec_file.parent.mkdir(parents=True, exist_ok=True)
    spec_file.write_bytes(spec.raw)
    _stage(git, [spec_rel])
    scan_secrets(config, worktree, run_dir, "specification", report)
    report.spec_commit = _commit(git, f"docs(orchestration): add approved spec for {spec.id}")

    try:
        run_executor(config, executor, spec, worktree, run_dir, report)
    except BaseException as stopped:
        if real_executor:
            # Ninguna salida excusa los controles, tampoco Ctrl+C o un error al leer el log:
            # un daño previo pesa más que el motivo de la parada.
            _raise_if_damage_after_stop(
                config, git, main_git, spec, worktree, report, snapshot, git_dir, stopped
            )
        raise
    verify_after_executor(git, main_git, spec, worktree, report.spec_commit, snapshot, git_dir)

    report.changes = collect_changes(git)
    check_scope(report.changes, spec)
    _check_filesystem(worktree, report.changes)
    check_dependencies_unchanged(git, worktree, report.changes)

    report.profile = gate_profile(report.changes)
    if real_executor:
        # `pytest` ejecutaría código escrito por Claude con el usuario de Windows.
        if report.profile == "code":
            raise BlockedError(Reason.CODE_PROFILE_FORBIDDEN)
        if report.structured_output is None:
            raise BlockedError(Reason.INVALID_STRUCTURED_OUTPUT, "missing")
        check_claude_report(report.structured_output, report.changes)
    if report.changes:
        # Cada archivo por su nombre: lo que no se revisó no puede entrar.
        _stage(git, [change.path for change in report.changes])
        report.tree = git.run("write-tree").text
        check_staged_content(git)
        scan_secrets(config, worktree, run_dir, "changes", report)
        run_quality_gates(config, git, worktree, run_dir, report)
        verify_tree_unchanged(git, report.spec_commit, report.tree)
        report.content_commit = _commit(git, f"chore({block_slug(spec.id)}): apply block changes")
        if git.run("rev-parse", "HEAD^{tree}").text != report.tree:
            raise BlockedError(Reason.GATE_MODIFIED_TREE)

    if capture_snapshot(main_git, spec.branch, worktree) != snapshot:
        raise BlockedError(Reason.REPO_INVARIANT_BROKEN)
    if _has_reparse_points(worktree):
        raise BlockedError(Reason.UNSAFE_FILE_MODE)

    write_sanitized_evidence(config, git, worktree, report)
    evidence_rel = f"{EVIDENCE_DIR}/{report.block_id}.md"
    _stage(git, [evidence_rel])
    scan_secrets(config, worktree, run_dir, "evidence", report)
    _commit(git, f"docs(orchestration): add run evidence for {spec.id}")

    if git.run("status", "--porcelain=v1", "--untracked-files=all", "-z").stdout:
        raise BlockedError(Reason.GATE_MODIFIED_TREE)


def _new_run_dir(config: RunnerConfig, block_id: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = config.logs / block_slug(block_id) / f"{stamp}-{os.getpid()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _record_internal_error(run_dir: Path) -> None:
    with open(run_dir / "internal.log", "a", encoding="utf-8") as log:
        log.write(scrub_text(traceback.format_exc()))


def _write_local_report(report: RunReport) -> None:
    """El informe de un bloque detenido queda fuera del repositorio."""
    if report.run_dir is None:
        return
    text = render_evidence(report)
    if report.detail:
        text += f"\n- Detalle: `{report.detail}`\n"
    (report.run_dir / "report.md").write_text(scrub_text(text), encoding="utf-8", errors="replace")


def _guarded(
    config: RunnerConfig,
    block_id: str,
    body: Callable[[Path, RunReport], None],
    success: Result,
) -> RunReport:
    """Una sola salida: lock, cuerpo, informe y liberación, pase lo que pase."""
    report = RunReport(block_id=str(block_id))
    try:
        validate_block_id(block_id)
        ensure_external_dirs(config)
        lock = acquire_lock(config)
    except BlockedError as error:
        report.reason, report.detail = error.reason, error.detail
        return report
    except OSError as error:
        report.reason, report.detail = Reason.INTERNAL_ERROR, type(error).__name__
        return report
    try:
        report.run_dir = _new_run_dir(config, block_id)
        body(report.run_dir, report)
        report.result = success
    except BlockedError as error:
        report.result = Result.BLOCKED
        report.reason, report.detail = error.reason, error.detail
    except KeyboardInterrupt:
        report.result = Result.BLOCKED
        report.reason = Reason.INTERRUPTED
    except Exception:
        report.result = Result.BLOCKED
        report.reason = Reason.INTERNAL_ERROR
        if report.run_dir is not None:
            _record_internal_error(report.run_dir)
    finally:
        try:
            _write_local_report(report)
        finally:
            release_lock(lock)
    return report


def run_block(
    config: RunnerConfig,
    block_id: str,
    *,
    executor: Executor | None = None,
    confirm: Callable[[Spec], bool] | None = None,
) -> RunReport:
    """Ejecuta un bloque y se detiene. Deja como mucho commits locales en su propia rama."""
    chosen = executor if executor is not None else NoChangeExecutor()
    approve = confirm if confirm is not None else _console_confirm

    def body(run_dir: Path, report: RunReport) -> None:
        _pipeline(config, block_id, chosen, approve, run_dir, report)

    return _guarded(config, block_id, body, Result.VERIFIED_LOCAL)


def validate_block(config: RunnerConfig, block_id: str) -> RunReport:
    """Solo lectura sobre el repositorio: no crea rama, ni copia, ni commit."""

    def body(run_dir: Path, report: RunReport) -> None:
        git = Git(config, config.repo_root, run_dir / "git.log")
        spec, base_sha = _validate_common(config, git, block_id)
        report.title = spec.title
        report.spec_sha256 = spec.sha256
        report.branch = spec.branch
        report.base_sha = base_sha

    return _guarded(config, block_id, body, Result.VALIDATED)


@dataclass(frozen=True)
class CleanupResult:
    removed_worktree: bool
    removed_branch: bool
    residual_directory: bool
    reason: Reason | None = None


def cleanup_block(config: RunnerConfig, block_id: str) -> CleanupResult:
    """Retira la copia de un bloque. Sin forzar nada: si Git se niega, se conserva."""
    try:
        validate_block_id(block_id)
        ensure_external_dirs(config)
        lock = acquire_lock(config)
    except BlockedError as error:
        return CleanupResult(False, False, False, error.reason)
    except OSError:
        return CleanupResult(False, False, False, Reason.INTERNAL_ERROR)
    try:
        git = Git(config, config.repo_root)
        path = worktree_path(config, block_id)
        entries = _parse_worktrees(git.run("worktree", "list", "--porcelain").text)
        entry = next((e for e in entries if _same_path(e["worktree"], path)), None)
        if entry is None:
            # Nunca toca una carpeta que Git no registre como copia de este bloque.
            return CleanupResult(False, False, path.exists(), Reason.NOTHING_TO_CLEAN)
        branch = entry.get("branch", "").removeprefix("refs/heads/")
        try:
            validate_branch_name(branch, block_id)
        except BlockedError:
            return CleanupResult(False, False, path.exists(), Reason.CLEANUP_REFUSED)
        # Retirar una copia con enlaces podría borrar lo que hay al otro lado.
        if _has_reparse_points(path):
            return CleanupResult(False, False, True, Reason.CLEANUP_REFUSED)
        removed = git.run("worktree", "remove", str(path), check=False)
        still_registered = any(
            _same_path(e["worktree"], path)
            for e in _parse_worktrees(git.run("worktree", "list", "--porcelain").text)
        )
        if still_registered:
            return CleanupResult(False, False, path.exists(), Reason.CLEANUP_REFUSED)
        # `-d` es el borrado seguro: Git se niega si la rama no está fusionada.
        branch_removed = git.run("branch", "-d", branch, check=False).returncode == 0
        return CleanupResult(
            removed_worktree=True,
            removed_branch=branch_removed,
            residual_directory=path.exists() or removed.returncode != 0,
        )
    except BlockedError as error:
        return CleanupResult(False, False, False, error.reason)
    finally:
        release_lock(lock)


@dataclass(frozen=True)
class WorktreeStatus:
    name: str
    registered: bool
    branch: str


def status_worktrees(config: RunnerConfig) -> list[WorktreeStatus]:
    """Solo lectura: las carpetas del runner, y si Git las reconoce."""
    if not config.worktrees.is_dir():
        return []
    git = Git(config, config.repo_root)
    entries = _parse_worktrees(git.run("worktree", "list", "--porcelain").text)
    statuses: list[WorktreeStatus] = []
    for folder in sorted(config.worktrees.iterdir()):
        entry = next((e for e in entries if _same_path(e["worktree"], folder)), None)
        branch = entry.get("branch", "").removeprefix("refs/heads/") if entry else ""
        statuses.append(WorktreeStatus(folder.name, entry is not None, branch))
    return statuses


# ---------------------------------------------------------------------------
# Consola: no ofrece elegir ejecutor, repositorio ni carpeta, ni saltarse la aprobación
# ---------------------------------------------------------------------------


def _print(message: str) -> None:
    print(message, flush=True)


def _console_confirm(spec: Spec) -> bool:
    # Aún no se ha escaneado: nada de texto libre sin limpiar en pantalla.
    _print(f"Bloque:     {spec.id} — {scrub_text(spec.title)}")
    _print(f"Rama:       {spec.branch}")
    _print(f"Tiempo:     {spec.timeout_minutes} min")
    _print(f"Huella:     {spec.sha256}")
    _print(f"Permitidas: {', '.join(spec.allowed_paths)}")
    _print(f"Prohibidas: {', '.join(spec.forbidden_paths) or 'solo las de siempre'}")
    _print("Paradas:")
    for condition in spec.stop_conditions:
        _print(f"  - {scrub_text(condition)}")
    _print("Gates humanos:")
    for gate in spec.human_gates:
        _print(f"  - {scrub_text(gate)}")
    try:
        answer = input(f"Escriba APROBAR {spec.id} para continuar: ")
    except EOFError:
        return False
    return answer.strip() == f"APROBAR {spec.id}"


def _report_outcome(report: RunReport) -> int:
    if report.result is not Result.BLOCKED:
        _print(f"Resultado: {report.result.value}")
        if report.result is Result.VERIFIED_LOCAL and report.worktree is not None:
            _print(f"Rama local: {report.branch}. Sin push, sin PR y sin merge.")
            _print(f"Copia de trabajo: {report.worktree}")
        return EXIT_OK
    reason = report.reason or Reason.INTERNAL_ERROR
    _print(f"Resultado: blocked ({reason.value})")
    _print(MESSAGES[reason])
    if report.run_dir is not None:
        _print(f"Logs locales: {report.run_dir}")
    if report.worktree is not None:
        _print("La copia de trabajo se conserva. Para retirarla: acción Cleanup.")
    return EXIT_LOCK_BUSY if reason is Reason.LOCK_BUSY else EXIT_BLOCKED


def _report_cleanup(result: CleanupResult) -> int:
    if result.reason is not None:
        _print(f"Resultado: {result.reason.value}")
        _print(MESSAGES[result.reason])
        return EXIT_LOCK_BUSY if result.reason is Reason.LOCK_BUSY else EXIT_BLOCKED
    _print("Copia de trabajo retirada.")
    if not result.removed_branch:
        _print("La rama se conserva: Git no confirma que sea seguro borrarla. No se fuerza.")
    if result.residual_directory:
        _print("Aviso: la carpeta sigue en disco. Puede que una consola la esté usando.")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orchestrator", description="Runner local de bloques de ELSA (ADR 0036)."
    )
    commands = parser.add_subparsers(dest="action", required=True)
    for name, help_text in (
        ("validate", "Comprueba sin cambiar el repositorio."),
        ("run", "Ejecuta el bloque tras aprobarlo. Solo commits locales."),
        ("cleanup", "Retira la copia de trabajo, sin forzar nada."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("block")
    commands.add_parser("status", help="Lista las copias de trabajo del runner.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as error:
        return EXIT_OK if error.code == 0 else EXIT_USAGE
    try:
        config = default_config()
    except BlockedError as error:
        _print(MESSAGES[error.reason])
        return EXIT_BLOCKED
    if args.action == "validate":
        return _report_outcome(validate_block(config, args.block))
    if args.action == "run":
        return _report_outcome(run_block(config, args.block))
    if args.action == "cleanup":
        return _report_cleanup(cleanup_block(config, args.block))
    try:
        statuses = status_worktrees(config)
    except BlockedError as error:
        _print(MESSAGES[error.reason])
        return EXIT_BLOCKED
    for item in statuses:
        state = f"registrada, rama {item.branch}" if item.registered else "sin registrar"
        _print(f"{item.name}: {state}")
    if not statuses:
        _print("No hay copias de trabajo del runner.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
