"""Verifica que los artefactos prohibidos no puedan versionarse.

Usa ``git check-ignore`` contra el árbol real. Se omite si no hay git o el
directorio no es un repositorio (p. ej. un tarball del código).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_PATHS = [
    ".env",
    ".env.local",
    "manual-tampella.pdf",
    "docs/manuales/manual.pdf",
    "plano-general.dwg",
    "plano.dxf",
    "export-sap.xlsx",
    "ih06.xls",
    "model-weights.gguf",
    "model.safetensors",
    "model.onnx",
    "data/dataset.csv",
    "dataset.parquet",
    "backup.dump",
    "elsa.sql.gz",
    "database.bak",
    # Estado local efímero del CLI de Supabase.
    "supabase/.temp/cli-latest",
    "supabase/.temp/project-ref",
]

ALLOWED_PATHS = [
    ".env.example",
    "supabase/migrations/20260101000000_example.sql",
    # Las migraciones son la única autoridad del esquema (ADR 0001): ignorar
    # `supabase/.temp/` no puede arrastrar consigo `supabase/migrations/`.
    "supabase/migrations/20260905020000_create_elsa_authorization_model.sql",
]


def _git_available() -> bool:
    if shutil.which("git") is None:
        return False
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(not _git_available(), reason="requires a git work tree")


def _is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", path],
        cwd=REPO_ROOT,
    )
    return result.returncode == 0


@pytest.mark.parametrize("path", FORBIDDEN_PATHS)
def test_forbidden_artifacts_are_ignored(path: str) -> None:
    assert _is_ignored(path), f"{path} must be ignored by .gitignore"


@pytest.mark.parametrize("path", ALLOWED_PATHS)
def test_required_files_are_not_ignored(path: str) -> None:
    assert not _is_ignored(path), f"{path} must be versionable"
