"""Las migraciones versionadas producen el esquema esperado.

Corren contra un PostgreSQL real (nunca el Supabase de producción: en CI es
un contenedor efímero). Verifican las garantías que el esquema debe dar por
sí mismo, con independencia del código Python: auditoría inmodificable, un
único permiso activo por alcance y RLS habilitado en todas las tablas.
"""

from collections.abc import AsyncIterator

import asyncpg
import pytest

from tests import db

pytestmark = pytest.mark.anyio

ADMIN = "aaaaaaaa-0000-4000-8000-000000000001"
USER = "bbbbbbbb-0000-4000-8000-000000000002"

ELSA_TABLES = {"accounts", "knowledge_domains", "permission_grants", "admin_audit_log"}


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


async def test_migrations_create_the_expected_tables(connection: asyncpg.Connection) -> None:
    rows = await connection.fetch("select tablename from pg_tables where schemaname = 'elsa'")

    assert {row["tablename"] for row in rows} == ELSA_TABLES


async def test_migrations_are_idempotent(connection: asyncpg.Connection) -> None:
    """Aplicarlas dos veces sobre la misma base no falla ni duplica datos."""
    for migration in db.migration_files():
        await connection.execute(migration.read_text(encoding="utf-8"))

    domains = await connection.fetchval("select count(*) from elsa.knowledge_domains")
    assert domains == 2


async def test_row_level_security_is_enabled_everywhere(
    connection: asyncpg.Connection,
) -> None:
    """Defensa en profundidad: sin políticas, nadie sin BYPASSRLS ve filas."""
    rows = await connection.fetch(
        "select tablename, rowsecurity from pg_tables where schemaname = 'elsa'"
    )

    assert rows
    assert all(row["rowsecurity"] for row in rows)


async def test_initial_domains_are_seeded(connection: asyncpg.Connection) -> None:
    rows = await connection.fetch("select code from elsa.knowledge_domains order by code")

    assert [row["code"] for row in rows] == ["mantenimiento", "materiales"]


async def test_scope_values_must_be_normalized(connection: asyncpg.Connection) -> None:
    await connection.execute("insert into elsa.accounts (external_user_id) values ($1)", USER)

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.permission_grants "
            "(external_user_id, domain, equipment, granted_by) "
            "values ($1, 'mantenimiento', 'Tampella', $2)",
            USER,
            ADMIN,
        )


async def test_only_one_active_grant_per_scope(connection: asyncpg.Connection) -> None:
    await connection.execute("insert into elsa.accounts (external_user_id) values ($1)", USER)
    insert = (
        "insert into elsa.permission_grants "
        "(external_user_id, domain, equipment, granted_by) values ($1, 'mantenimiento', $2, $3)"
    )
    await connection.execute(insert, USER, "tampella", ADMIN)

    with pytest.raises(asyncpg.UniqueViolationError):
        await connection.execute(insert, USER, "tampella", ADMIN)


async def test_only_one_active_domain_wide_grant(connection: asyncpg.Connection) -> None:
    """El permiso de dominio completo (equipment NULL) también es único."""
    await connection.execute("insert into elsa.accounts (external_user_id) values ($1)", USER)
    insert = (
        "insert into elsa.permission_grants (external_user_id, domain, granted_by) "
        "values ($1, 'mantenimiento', $2)"
    )
    await connection.execute(insert, USER, ADMIN)

    with pytest.raises(asyncpg.UniqueViolationError):
        await connection.execute(insert, USER, ADMIN)


async def test_a_revoked_grant_frees_the_scope(connection: asyncpg.Connection) -> None:
    await connection.execute("insert into elsa.accounts (external_user_id) values ($1)", USER)
    insert = (
        "insert into elsa.permission_grants (external_user_id, domain, granted_by) "
        "values ($1, 'mantenimiento', $2)"
    )
    await connection.execute(insert, USER, ADMIN)
    await connection.execute(
        "update elsa.permission_grants set revoked_at = now(), revoked_by = $1", ADMIN
    )

    await connection.execute(insert, USER, ADMIN)

    total = await connection.fetchval("select count(*) from elsa.permission_grants")
    assert total == 2


async def test_revocation_must_record_who_revoked(connection: asyncpg.Connection) -> None:
    await connection.execute("insert into elsa.accounts (external_user_id) values ($1)", USER)
    await connection.execute(
        "insert into elsa.permission_grants (external_user_id, domain, granted_by) "
        "values ($1, 'mantenimiento', $2)",
        USER,
        ADMIN,
    )

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute("update elsa.permission_grants set revoked_at = now()")


async def test_grants_require_a_known_domain(connection: asyncpg.Connection) -> None:
    await connection.execute("insert into elsa.accounts (external_user_id) values ($1)", USER)

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await connection.execute(
            "insert into elsa.permission_grants (external_user_id, domain, granted_by) "
            "values ($1, 'inexistente', $2)",
            USER,
            ADMIN,
        )


async def test_the_audit_log_cannot_be_updated_or_deleted(
    connection: asyncpg.Connection,
) -> None:
    """Un registro que puede reescribirse no es auditoría."""
    await connection.execute(
        "insert into elsa.admin_audit_log "
        "(actor_external_user_id, subject_external_user_id, operation) "
        "values ($1, $2, 'grant_permission')",
        ADMIN,
        USER,
    )

    with pytest.raises(asyncpg.PostgresError):
        await connection.execute("update elsa.admin_audit_log set operation = 'enable_user'")

    with pytest.raises(asyncpg.PostgresError):
        await connection.execute("delete from elsa.admin_audit_log")

    assert await connection.fetchval("select count(*) from elsa.admin_audit_log") == 1


async def test_unknown_audit_operations_are_rejected(connection: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.admin_audit_log (subject_external_user_id, operation) "
            "values ($1, 'do_whatever')",
            USER,
        )


async def test_updated_at_tracks_account_changes(connection: asyncpg.Connection) -> None:
    await connection.execute("insert into elsa.accounts (external_user_id) values ($1)", USER)
    before = await connection.fetchval(
        "select updated_at from elsa.accounts where external_user_id = $1", USER
    )

    await connection.execute(
        "update elsa.accounts set is_active = false where external_user_id = $1", USER
    )
    after = await connection.fetchval(
        "select updated_at from elsa.accounts where external_user_id = $1", USER
    )

    assert after >= before
