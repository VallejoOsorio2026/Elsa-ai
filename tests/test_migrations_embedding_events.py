"""La migración del historial del modelo activo (ADR 0039) y su reversión.

Corren contra un PostgreSQL real (en CI, un contenedor efímero; nunca el
Supabase del proyecto). Comprueban que la forma de cada evento la impone la
base, que el historial no se reescribe, que la migración es idempotente, y
que el rollback revierte limpio mientras no hay eventos pero **se niega**
—sin borrar nada— en cuanto existe uno.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import asyncpg
import pytest

from tests import db

pytestmark = pytest.mark.anyio

ACTOR = "aaaaaaaa-0000-4000-8000-000000000001"
ROOT = Path(__file__).resolve().parent.parent / "supabase"
MIGRATION = ROOT / "migrations" / "20261108010000_create_embedding_model_events.sql"
ROLLBACK = ROOT / "rollback" / "20261108010000_rollback.sql"
VECTOR_ROLLBACK = ROOT / "rollback" / "20260913010000_rollback.sql"


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


async def make_model(connection: asyncpg.Connection, revision: str = "r1") -> str:
    return str(
        await connection.fetchval(
            "insert into elsa.embedding_models "
            "(family, model_id, revision, dimension, normalized, composition_template, "
            " runtime, registered_by) "
            "values ('fake', 'fake/model', $1, 8, true, 'context-v1', 'fake', $2) returning id",
            revision,
            ACTOR,
        )
    )


async def make_run(connection: asyncpg.Connection, model_id: str) -> str:
    return str(
        await connection.fetchval(
            "insert into elsa.embedding_runs (model_id, started_by) values ($1, $2) returning id",
            model_id,
            ACTOR,
        )
    )


async def add_event(
    connection: asyncpg.Connection,
    event: str,
    model_id: str,
    *,
    previous: str | None = None,
    run_id: str | None = None,
    reason: str | None = None,
) -> None:
    await connection.execute(
        "insert into elsa.embedding_model_events "
        "(event, model_id, previous_model_id, run_id, actor, reason) "
        "values ($1, $2, $3, $4, $5, $6)",
        event,
        model_id,
        previous,
        run_id,
        ACTOR,
        reason,
    )


async def events(connection: asyncpg.Connection) -> list[tuple[str, str | None]]:
    rows = await connection.fetch(
        "select event, reason from elsa.embedding_model_events order by seq"
    )
    return [(row["event"], row["reason"]) for row in rows]


async def exists(connection: asyncpg.Connection) -> bool:
    return bool(await connection.fetchval("select to_regclass('elsa.embedding_model_events')"))


async def test_the_table_is_closed_by_rls_and_append_only(connection: asyncpg.Connection) -> None:
    row = await connection.fetchrow(
        "select c.relrowsecurity, "
        "  (select count(*) from pg_policies p where p.schemaname = 'elsa' "
        "     and p.tablename = 'embedding_model_events') as policies "
        "from pg_class c where c.oid = 'elsa.embedding_model_events'::regclass"
    )
    assert row["relrowsecurity"] and row["policies"] == 0

    model = await make_model(connection)
    await add_event(connection, "activated", model)
    with pytest.raises(asyncpg.PostgresError):
        await connection.execute("update elsa.embedding_model_events set reason = 'x'")
    with pytest.raises(asyncpg.PostgresError):
        await connection.execute("delete from elsa.embedding_model_events")
    assert await events(connection) == [("activated", None)]


async def test_the_schema_enforces_the_shape_of_each_event(
    connection: asyncpg.Connection,
) -> None:
    model = await make_model(connection)
    other = await make_model(connection, revision="r2")
    run = await make_run(connection, model)

    await add_event(connection, "activated", model)
    await add_event(connection, "activated", other, previous=model)
    await add_event(connection, "deactivated", other, reason="Ctrl+Z")
    await add_event(connection, "retired", other)
    await add_event(connection, "run_reconciled", model, run_id=run, reason="proceso muerto")

    refused = [
        {"event": "deleted", "model_id": model, "reason": "no existe"},
        {"event": "deactivated", "model_id": model},  # sin motivo
        {"event": "deactivated", "model_id": model, "reason": "   "},
        {"event": "run_reconciled", "model_id": model, "reason": "sin corrida"},
        {"event": "run_reconciled", "model_id": model, "run_id": run},  # sin motivo
        {"event": "activated", "model_id": model, "previous": model},  # anterior = nuevo
        {"event": "activated", "model_id": model, "run_id": run},
        {"event": "deactivated", "model_id": model, "previous": other, "reason": "x"},
    ]
    for case in refused:
        event, model_id = case.pop("event"), case.pop("model_id")
        with pytest.raises(asyncpg.CheckViolationError):
            await add_event(connection, event, model_id, **case)
    assert len(await events(connection)) == 5


async def test_the_migration_can_be_applied_twice_without_touching_history(
    connection: asyncpg.Connection,
) -> None:
    model = await make_model(connection)
    await add_event(connection, "activated", model)
    await connection.execute(MIGRATION.read_text(encoding="utf-8"))
    assert await events(connection) == [("activated", None)]


async def test_the_rollback_is_clean_while_there_are_no_events(
    connection: asyncpg.Connection,
) -> None:
    await connection.execute(ROLLBACK.read_text(encoding="utf-8"))
    assert not await exists(connection)
    # Y la migración vuelve a aplicarse sobre el esquema revertido.
    await connection.execute(MIGRATION.read_text(encoding="utf-8"))
    assert await exists(connection)


async def test_the_rollback_refuses_once_an_event_exists(
    connection: asyncpg.Connection,
) -> None:
    model = await make_model(connection)
    await add_event(connection, "activated", model)
    await add_event(connection, "deactivated", model, reason="Ctrl+Z")
    before = await events(connection)

    with pytest.raises(asyncpg.RaiseError, match="rollback refused"):
        await connection.execute(ROLLBACK.read_text(encoding="utf-8"))
    # El guion abrió su propia transacción; el error la deja abortada.
    await connection.execute("rollback")
    assert await exists(connection)
    assert await events(connection) == before


async def test_the_vector_rollback_cannot_run_before_this_one(
    connection: asyncpg.Connection,
) -> None:
    """Las claves foráneas fijan el orden: primero se revierte el historial."""
    model = await make_model(connection)
    with pytest.raises(asyncpg.DependentObjectsStillExistError):
        await connection.execute(VECTOR_ROLLBACK.read_text(encoding="utf-8"))
    # Una consulta múltiple sin control de transacción explícito es una sola
    # transacción implícita: el fallo no deja nada a medias.
    assert await exists(connection)
    assert await connection.fetchval(
        "select count(*) from elsa.embedding_models where id = $1", model
    )
