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
    # Bloque 2: fuentes técnicas reales y todo lo que se deriva de ellas.
    "BOM Tampella.xlsx",
    "libro-con-macros.xlsm",
    "TAMPELLA_BOM.HTM",
    "BOM TAMPELLA.XLSX",
    "PLANO.DWG",
    "export-sap.htm",
    "export-sap.mhtml",
    ".artifacts/engineering_bom_xlsx/ab/abcdef",
    "artifacts/drawing_image/cd/cdef01",
    "private/original.bin",
    "acceptance/reporte-real.json",
    "reports/reconciliacion.json",
    # Volcados de Supabase previos a una reversión: contienen datos técnicos
    # internos. `*.sql` no puede ignorarse en bloque porque las migraciones
    # también lo son, de modo que se ignoran por prefijo de nombre.
    "respaldo-elsa-2026-09-06.sql",
    "backup-elsa.sql",
    "dump-elsa.sql",
]

ALLOWED_PATHS = [
    ".env.example",
    "supabase/migrations/20260101000000_example.sql",
    # Las migraciones son la única autoridad del esquema (ADR 0001): ignorar
    # `supabase/.temp/` no puede arrastrar consigo `supabase/migrations/`.
    "supabase/migrations/20260905020000_create_elsa_authorization_model.sql",
    "supabase/migrations/20260906010000_create_technical_knowledge_model.sql",
    # El guion de reversión es procedimiento documentado, no un volcado: se
    # versiona aunque su nombre termine en `.sql`.
    "supabase/rollback/20260906010000_rollback.sql",
    # Los fixtures de la suite son código, no archivos binarios: tienen que
    # poder versionarse.
    "tests/fixtures_xlsx.py",
    "tests/fixtures_sources.py",
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


# ---------------------------------------------------------------------
# Los fixtures son sintéticos
# ---------------------------------------------------------------------

# Prefijos con los que se inventan los códigos en los fixtures. Un código
# fuera de estos rangos en la suite es señal de que alguien pegó un dato de
# una fuente real.
SYNTHETIC_CODE_PREFIXES = ("10000", "90000", "EQ-", "PL-", "MOD-", "R-", "MB-")

FIXTURE_MODULES = ("tests/fixtures_xlsx.py", "tests/fixtures_sources.py")


@pytest.mark.parametrize("module", FIXTURE_MODULES)
def test_fixture_modules_are_versionable(module: str) -> None:
    """Los fixtures son código, no binarios: tienen que poder versionarse."""
    assert not _is_ignored(module)
    assert (REPO_ROOT / module).is_file()


def test_generated_fixtures_only_use_invented_identifiers() -> None:
    """Ningún código de los fixtures sale de los rangos inventados.

    No demuestra que no haya datos reales —eso lo garantiza que los fixtures
    se generen por código—, pero sí detecta el descuido más probable: pegar
    un renglón de la fuente real dentro de un test.
    """
    import re

    pattern = re.compile(r"\b\d{7,}\b")
    for module in FIXTURE_MODULES:
        content = (REPO_ROOT / module).read_text(encoding="utf-8")
        for code in pattern.findall(content):
            # SAP rellena los códigos con ceros a la izquierda al mostrarlos,
            # y los fixtures usan esa forma a propósito para comprobar que la
            # normalización la deshace. El relleno no cambia de qué rango es
            # el código.
            unpadded = code.lstrip("0") or "0"
            assert unpadded.startswith(SYNTHETIC_CODE_PREFIXES), (
                f"{module} contains {code!r}, which is outside the invented ranges"
            )
