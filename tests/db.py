"""Apoyo para los tests que necesitan una base PostgreSQL real.

Se activan solo si existe ``ELSA_TEST_DATABASE_URL``; sin ella se omiten, de
modo que ``uv run pytest`` sigue funcionando en un clon limpio sin base de
datos. **Nunca** apunta al Supabase real: en CI es un contenedor de
PostgreSQL efímero (ver ``.github/workflows/ci.yml``).

Aplicar las migraciones desde el propio repositorio es también la prueba de
que el esquema es reproducible a partir de los archivos versionados
(ADR 0001).
"""

import os
from pathlib import Path

import asyncpg

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "supabase" / "migrations"

ENV_VARIABLE = "ELSA_TEST_DATABASE_URL"

SKIP_REASON = (
    f"requires a PostgreSQL database; set {ENV_VARIABLE} "
    "(e.g. postgresql://user@127.0.0.1:5432/elsa_test)"
)


def database_url() -> str | None:
    """URL de la base de pruebas, o ``None`` si no está configurada."""
    return os.environ.get(ENV_VARIABLE) or None


def migration_files() -> list[Path]:
    """Migraciones en el orden en que deben aplicarse (por timestamp)."""
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


async def reset_database(url: str) -> None:
    """Deja la base en el estado exacto que producen las migraciones."""
    connection = await asyncpg.connect(url)
    try:
        await connection.execute("drop schema if exists elsa cascade")
        for migration in migration_files():
            await connection.execute(migration.read_text(encoding="utf-8"))
    finally:
        await connection.close()
