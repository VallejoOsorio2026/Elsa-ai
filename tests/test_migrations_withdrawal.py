"""La migración de la retirada de publicaciones (ADR 0038) y su reversión.

Corren contra un PostgreSQL real (en CI, un contenedor efímero). Comprueban
que el evento `withdrawn` exige motivo por la base y no solo por el código,
que la migración es idempotente, y que el rollback revierte limpio mientras
nadie ha retirado nada, pero **se niega** —sin borrar historial— en cuanto
existe una retirada.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest

from tests import db
from tests.test_migrations_documents import ACTOR, HASH_A, make_document, make_version

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parent.parent / "supabase"
MIGRATION = ROOT / "migrations" / "20261103010000_allow_document_publication_withdrawal.sql"
ROLLBACK = ROOT / "rollback" / "20261103010000_rollback.sql"


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


async def _version(connection: asyncpg.Connection) -> str:
    document_id = await make_document(connection)
    return await make_version(connection, document_id, number=1, digest=HASH_A)


async def _event(
    connection: asyncpg.Connection, version_id: str, event: str, reason: str | None
) -> None:
    await connection.execute(
        "insert into elsa.document_version_events (version_id, event, actor, reason) "
        "values ($1, $2, $3, $4)",
        version_id,
        event,
        ACTOR,
        reason,
    )


async def _events(connection: asyncpg.Connection) -> list[tuple[str, str | None]]:
    rows = await connection.fetch(
        "select event, reason from elsa.document_version_events order by seq"
    )
    return [(row["event"], row["reason"]) for row in rows]


async def test_a_withdrawal_needs_a_reason_from_the_schema(
    connection: asyncpg.Connection,
) -> None:
    version_id = await _version(connection)
    for reason in (None, "", "   "):
        with pytest.raises(asyncpg.CheckViolationError):
            await _event(connection, version_id, "withdrawn", reason)
    await _event(connection, version_id, "withdrawn", "publicada por error")
    # Lo que ya valía sigue valiendo, y lo desconocido sigue rechazado.
    await _event(connection, version_id, "published", None)
    with pytest.raises(asyncpg.CheckViolationError):
        await _event(connection, version_id, "rejected", None)
    with pytest.raises(asyncpg.CheckViolationError):
        await _event(connection, version_id, "deleted", "no existe")
    assert await _events(connection) == [
        ("withdrawn", "publicada por error"),
        ("published", None),
    ]


async def test_the_migration_can_be_applied_twice(connection: asyncpg.Connection) -> None:
    version_id = await _version(connection)
    await _event(connection, version_id, "withdrawn", "motivo")
    await connection.execute(MIGRATION.read_text(encoding="utf-8"))
    assert await _events(connection) == [("withdrawn", "motivo")]


async def test_the_rollback_is_clean_while_nothing_was_withdrawn(
    connection: asyncpg.Connection,
) -> None:
    version_id = await _version(connection)
    await _event(connection, version_id, "created", None)

    await connection.execute(ROLLBACK.read_text(encoding="utf-8"))

    with pytest.raises(asyncpg.CheckViolationError):
        await _event(connection, version_id, "withdrawn", "motivo")
    with pytest.raises(asyncpg.CheckViolationError):
        await _event(connection, version_id, "rejected", None)
    assert await _events(connection) == [("created", None)]

    # Y la migración vuelve a aplicarse sobre el esquema revertido.
    await connection.execute(MIGRATION.read_text(encoding="utf-8"))
    await _event(connection, version_id, "withdrawn", "motivo")
    assert await _events(connection) == [("created", None), ("withdrawn", "motivo")]


async def test_the_rollback_refuses_once_a_withdrawal_exists(
    connection: asyncpg.Connection,
) -> None:
    version_id = await _version(connection)
    await _event(connection, version_id, "published", None)
    await _event(connection, version_id, "withdrawn", "Ctrl+Z")
    before = await _events(connection)

    with pytest.raises(asyncpg.RaiseError, match="rollback refused"):
        await connection.execute(ROLLBACK.read_text(encoding="utf-8"))
    # El guion abrió su propia transacción; el error la deja abortada y nada
    # de lo que venía después llegó a ejecutarse.
    await connection.execute("rollback")

    assert await _events(connection) == before
    # Las restricciones siguen siendo las de la migración.
    await _event(connection, version_id, "withdrawn", "otra retirada")
    with pytest.raises(asyncpg.CheckViolationError):
        await _event(connection, version_id, "withdrawn", "")
