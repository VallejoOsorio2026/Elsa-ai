"""La migración vectorial, verificada contra PostgreSQL 16 con pgvector real.

Lo que se comprueba aquí es del esquema, no del adaptador: reversión,
reaplicación, aislamiento y privilegios. Un adaptador correcto sobre un
esquema abierto seguiría estando abierto.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest

from tests import db

pytestmark = pytest.mark.anyio

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "supabase"
    / "migrations"
    / "20260913010000_create_vector_storage_model.sql"
)
ROLLBACK = (
    Path(__file__).resolve().parent.parent / "supabase" / "rollback" / "20260913010000_rollback.sql"
)
VECTOR_TABLES = ("embedding_models", "embedding_runs", "document_chunk_embeddings")


@pytest.fixture
async def connection() -> AsyncIterator[asyncpg.Connection]:
    url = db.database_url()
    if url is None:
        pytest.skip(db.SKIP_REASON)
    await db.reset_database(url)
    conn = await asyncpg.connect(url)
    try:
        yield conn
    finally:
        await conn.close()


async def tables(connection: asyncpg.Connection) -> set[str]:
    rows = await connection.fetch(
        "select tablename from pg_tables where schemaname = 'elsa' and tablename = any($1::text[])",
        list(VECTOR_TABLES),
    )
    return {row["tablename"] for row in rows}


async def test_the_migration_creates_the_vector_model(connection: asyncpg.Connection) -> None:
    assert await tables(connection) == set(VECTOR_TABLES)
    assert (
        await connection.fetchval("select count(*) from pg_extension where extname = 'vector'") == 1
    )


async def test_the_vector_column_declares_no_dimension_so_models_can_coexist(
    connection: asyncpg.Connection,
) -> None:
    """`vector(N)` ataría el esquema a un candidato; ADR 0015 no lo permite aún."""
    declared = await connection.fetchval(
        "select format_type(a.atttypid, a.atttypmod) from pg_attribute a "
        "where a.attrelid = 'elsa.document_chunk_embeddings'::regclass "
        "  and a.attname = 'embedding'"
    )
    assert declared == "vector"


async def test_no_ann_index_is_created(connection: asyncpg.Connection) -> None:
    """El piloto busca de forma exacta (ADR 0013 §6). HNSW e IVFFlat no entran."""
    indexes = await connection.fetch(
        "select indexdef from pg_indexes where schemaname = 'elsa' "
        "  and tablename = 'document_chunk_embeddings'"
    )
    joined = " ".join(row["indexdef"].lower() for row in indexes)
    assert "hnsw" not in joined and "ivfflat" not in joined


async def test_row_level_security_is_enabled_without_policies(
    connection: asyncpg.Connection,
) -> None:
    rows = await connection.fetch(
        "select c.relname, c.relrowsecurity, "
        "  (select count(*) from pg_policies p "
        "    where p.schemaname = 'elsa' and p.tablename = c.relname) as policies "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'elsa' and c.relname = any($1::text[])",
        list(VECTOR_TABLES),
    )
    assert len(rows) == len(VECTOR_TABLES)
    for row in rows:
        assert row["relrowsecurity"], row["relname"]
        assert row["policies"] == 0, row["relname"]


async def test_the_retrieval_view_runs_with_the_callers_privileges(
    connection: asyncpg.Connection,
) -> None:
    """Sin `security_invoker`, la vista se saltaría el RLS de sus tablas base."""
    options = await connection.fetchval(
        "select c.reloptions from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'elsa' and c.relname = 'chunk_embedding_retrieval'"
    )
    assert options is not None and "security_invoker=true" in options


async def test_nothing_is_granted_to_anon_or_authenticated(
    connection: asyncpg.Connection,
) -> None:
    assert (
        await connection.fetchval(
            "select count(*) from information_schema.role_table_grants "
            "where table_schema = 'elsa' and grantee in ('anon', 'authenticated')"
        )
        == 0
    )


async def test_rollback_removes_the_vectors_and_keeps_the_documents(
    connection: asyncpg.Connection,
) -> None:
    """La reversión no toca el modelo documental: los chunks siguen ahí."""
    documents_before = await connection.fetchval(
        "select count(*) from pg_tables where schemaname = 'elsa' "
        "  and tablename in ('documents', 'document_versions', 'document_chunks')"
    )

    await connection.execute(ROLLBACK.read_text())
    assert await tables(connection) == set()
    assert (
        await connection.fetchval(
            "select count(*) from pg_tables where schemaname = 'elsa' "
            "  and tablename in ('documents', 'document_versions', 'document_chunks')"
        )
        == documents_before
    )

    await connection.execute(MIGRATION.read_text())
    assert await tables(connection) == set(VECTOR_TABLES)


async def test_the_migration_can_be_applied_twice(connection: asyncpg.Connection) -> None:
    """Una migración que solo corre sobre una base virgen no es reproducible."""
    await connection.execute(MIGRATION.read_text())
    assert await tables(connection) == set(VECTOR_TABLES)
