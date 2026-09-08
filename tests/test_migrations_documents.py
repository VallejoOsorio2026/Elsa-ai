"""El esquema documental garantiza por sí mismo lo que el código promete.

Corren contra un PostgreSQL real (nunca el Supabase de producción: en CI es
un contenedor efímero). Comprueban lo que la base tiene que impedir aunque
el código Python tuviera un fallo: dos versiones publicadas del mismo
documento, un chunk que mezcle dos versiones, un historial reescribible.
"""

from collections.abc import AsyncIterator

import asyncpg
import pytest

from tests import db

pytestmark = pytest.mark.anyio

ACTOR = "aaaaaaaa-0000-4000-8000-000000000001"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64

# Bloque 4: conocimiento documental. La lista es explícita a propósito: una
# tabla nueva que nadie declara aquí es una tabla que nadie revisó.
DOCUMENT_TABLES = {
    "documents",
    "document_ingestion_runs",
    "document_versions",
    "document_sections",
    "document_chunks",
    "document_version_events",
}


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


async def make_document(
    connection: asyncpg.Connection, *, code: str = "manual-ejemplo", asset: str | None = None
) -> str:
    asset_id = None
    if asset is not None:
        asset_id = await connection.fetchval(
            "insert into elsa.technical_assets (code, name, domain) "
            "values ($1, 'Activo de ejemplo', 'mantenimiento') returning id",
            asset,
        )
    return str(
        await connection.fetchval(
            "insert into elsa.documents (domain, asset_id, code, title, source_kind) "
            "values ('mantenimiento', $1, $2, 'Manual de ejemplo', 'manual') returning id",
            asset_id,
            code,
        )
    )


async def make_version(
    connection: asyncpg.Connection,
    document_id: str,
    *,
    number: int,
    digest: str,
    state: str = "pending_validation",
) -> str:
    artifact_id = await connection.fetchval(
        "insert into elsa.source_artifacts "
        "(kind, sha256, byte_size, storage_key, uploaded_by) "
        "values ('document_markdown', $1, 100, $2, $3) returning id",
        digest,
        f"document_source/{digest}",
        ACTOR,
    )
    run_id = await connection.fetchval(
        "insert into elsa.document_ingestion_runs "
        "(document_id, source_artifact_id, status, started_by) "
        "values ($1, $2, 'completed', $3) returning id",
        document_id,
        artifact_id,
        ACTOR,
    )
    published = "now()" if state == "published" else "null"
    actor = f"'{ACTOR}'::uuid" if state == "published" else "null"
    return str(
        await connection.fetchval(
            "insert into elsa.document_versions "
            "(document_id, run_id, source_artifact_id, version_number, state, "
            " content_sha256, structure_sha256, chunking_profile, extractor, "
            " extractor_version, published_at, published_by) "
            f"values ($1, $2, $3, $4, $5, $6, $6, 'structural-v1', 'structured_text', '1', "
            f"{published}, {actor}) returning id",
            document_id,
            run_id,
            artifact_id,
            number,
            state,
            digest,
        )
    )


# ---------------------------------------------------------------------
# Estructura
# ---------------------------------------------------------------------


async def test_the_migration_creates_the_expected_tables(
    connection: asyncpg.Connection,
) -> None:
    rows = await connection.fetch("select tablename from pg_tables where schemaname = 'elsa'")

    assert DOCUMENT_TABLES <= {row["tablename"] for row in rows}


async def test_row_level_security_is_enabled_on_the_new_tables(
    connection: asyncpg.Connection,
) -> None:
    """Defensa en profundidad: sin políticas, nadie sin BYPASSRLS ve filas."""
    rows = await connection.fetch(
        "select tablename, rowsecurity from pg_tables "
        "where schemaname = 'elsa' and tablename = any($1::text[])",
        sorted(DOCUMENT_TABLES),
    )

    assert len(rows) == len(DOCUMENT_TABLES)
    assert all(row["rowsecurity"] for row in rows)


async def test_the_block_4_migration_builds_on_the_earlier_schema(
    connection: asyncpg.Connection,
) -> None:
    """Un documento apunta al catálogo de dominios del Bloque 1.

    Autorizar un documento es autorizar un alcance que ya existía; no hay un
    segundo modelo de permisos.
    """
    referenced = await connection.fetch(
        "select target.relname from pg_constraint c "
        "join pg_class target on target.oid = c.confrelid "
        "where c.conrelid = 'elsa.documents'::regclass and c.contype = 'f'"
    )

    assert {row["relname"] for row in referenced} == {"knowledge_domains", "technical_assets"}


async def test_there_is_no_vector_column_yet(connection: asyncpg.Connection) -> None:
    """El Bloque 4.1 no decide la dimensión del embedding.

    Declararla ahora obligaría a migrar la tabla entera al elegir el modelo.
    """
    rows = await connection.fetch(
        "select column_name, data_type from information_schema.columns "
        "where table_schema = 'elsa' and table_name = 'document_chunks'"
    )
    names = {row["column_name"] for row in rows}

    assert "embedding" not in names
    assert all(row["data_type"] != "vector" for row in rows)


# ---------------------------------------------------------------------
# Alcance y aislamiento
# ---------------------------------------------------------------------


async def test_a_document_cannot_belong_to_an_asset_of_another_domain(
    connection: asyncpg.Connection,
) -> None:
    """Sin esta restricción, el alcance de autorización mentiría."""
    await connection.execute(
        "insert into elsa.technical_assets (code, name, domain) "
        "values ('equipo-materiales', 'Activo', 'materiales')"
    )
    asset_id = await connection.fetchval(
        "select id from elsa.technical_assets where code = 'equipo-materiales'"
    )

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await connection.execute(
            "insert into elsa.documents (domain, asset_id, code, title, source_kind) "
            "values ('mantenimiento', $1, 'manual', 'Manual', 'manual')",
            asset_id,
        )


async def test_a_document_may_apply_to_a_whole_domain(
    connection: asyncpg.Connection,
) -> None:
    """Un procedimiento general de bloqueo no cuelga de ningún equipo."""
    document_id = await make_document(connection, code="bloqueo-etiquetado")

    asset = await connection.fetchval(
        "select asset_id from elsa.documents where id = $1", document_id
    )

    assert asset is None


async def test_document_codes_are_unique_within_a_domain(
    connection: asyncpg.Connection,
) -> None:
    await make_document(connection, code="manual-ejemplo")

    with pytest.raises(asyncpg.UniqueViolationError):
        await make_document(connection, code="manual-ejemplo")


async def test_document_codes_must_be_normalised(connection: asyncpg.Connection) -> None:
    """Los códigos son dato, no constantes: se comparan en su forma canónica."""
    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.documents (domain, code, title, source_kind) "
            "values ('mantenimiento', 'Manual Ejemplo', 'Manual', 'manual')"
        )


# ---------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------


async def test_only_one_published_version_per_document(
    connection: asyncpg.Connection,
) -> None:
    """Imposible, no improbable: lo impone un índice parcial."""
    document_id = await make_document(connection)
    await make_version(connection, document_id, number=1, digest=HASH_A, state="published")

    with pytest.raises(asyncpg.UniqueViolationError):
        await make_version(connection, document_id, number=2, digest=HASH_B, state="published")


async def test_two_documents_can_each_have_a_published_version(
    connection: asyncpg.Connection,
) -> None:
    one = await make_document(connection, code="manual-uno")
    two = await make_document(connection, code="manual-dos")

    await make_version(connection, one, number=1, digest=HASH_A, state="published")
    await make_version(connection, two, number=1, digest=HASH_B, state="published")

    total = await connection.fetchval(
        "select count(*) from elsa.document_versions where state = 'published'"
    )
    assert total == 2


async def test_a_published_version_must_record_who_published_it(
    connection: asyncpg.Connection,
) -> None:
    document_id = await make_document(connection)
    run_and_artifact = await make_version(connection, document_id, number=1, digest=HASH_A)

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "update elsa.document_versions set state = 'published' where id = $1",
            run_and_artifact,
        )


async def test_the_same_file_cannot_be_registered_twice(
    connection: asyncpg.Connection,
) -> None:
    """La idempotencia la impone la base, no una comprobación previa que dos
    peticiones simultáneas podrían pasar a la vez."""
    document_id = await make_document(connection)
    await make_version(connection, document_id, number=1, digest=HASH_A)

    with pytest.raises(asyncpg.UniqueViolationError):
        await make_version(connection, document_id, number=2, digest=HASH_A)


async def test_version_numbers_are_unique_per_document(
    connection: asyncpg.Connection,
) -> None:
    document_id = await make_document(connection)
    await make_version(connection, document_id, number=1, digest=HASH_A)

    with pytest.raises(asyncpg.UniqueViolationError):
        await make_version(connection, document_id, number=1, digest=HASH_B)


async def test_a_run_produces_at_most_one_version(connection: asyncpg.Connection) -> None:
    document_id = await make_document(connection)
    version_id = await make_version(connection, document_id, number=1, digest=HASH_A)
    run_id = await connection.fetchval(
        "select run_id from elsa.document_versions where id = $1", version_id
    )
    artifact_id = await connection.fetchval(
        "select source_artifact_id from elsa.document_versions where id = $1", version_id
    )

    with pytest.raises(asyncpg.UniqueViolationError):
        await connection.execute(
            "insert into elsa.document_versions "
            "(document_id, run_id, source_artifact_id, version_number, content_sha256, "
            " structure_sha256, chunking_profile, extractor, extractor_version) "
            "values ($1, $2, $3, 2, $4, $4, 'structural-v1', 'structured_text', '1')",
            document_id,
            run_id,
            artifact_id,
            HASH_B,
        )


async def test_a_failed_run_must_say_why(connection: asyncpg.Connection) -> None:
    document_id = await make_document(connection)
    artifact_id = await connection.fetchval(
        "insert into elsa.source_artifacts (kind, sha256, byte_size, storage_key, uploaded_by) "
        "values ('document_markdown', $1, 10, 'k', $2) returning id",
        HASH_C,
        ACTOR,
    )

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.document_ingestion_runs "
            "(document_id, source_artifact_id, status, started_by) "
            "values ($1, $2, 'failed', $3)",
            document_id,
            artifact_id,
            ACTOR,
        )


# ---------------------------------------------------------------------
# Chunks
# ---------------------------------------------------------------------


async def test_a_chunk_cannot_point_at_a_section_of_another_version(
    connection: asyncpg.Connection,
) -> None:
    """Sin esto la procedencia mentiría sin que nada fallara."""
    document_id = await make_document(connection)
    first = await make_version(connection, document_id, number=1, digest=HASH_A)
    second = await make_version(connection, document_id, number=2, digest=HASH_B)
    section_id = await connection.fetchval(
        "insert into elsa.document_sections (version_id, ordinal, path, depth, title) "
        "values ($1, 0, '1', 1, 'Alcance') returning id",
        first,
    )

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await connection.execute(
            "insert into elsa.document_chunks "
            "(version_id, section_id, ordinal, structural_key, content, content_sha256, kind) "
            "values ($1, $2, 0, '1#0000', 'texto', $3, 'prose')",
            second,
            section_id,
            HASH_C,
        )


async def test_a_chunk_address_is_unique_within_its_version(
    connection: asyncpg.Connection,
) -> None:
    document_id = await make_document(connection)
    version_id = await make_version(connection, document_id, number=1, digest=HASH_A)
    insert = (
        "insert into elsa.document_chunks "
        "(version_id, ordinal, structural_key, content, content_sha256, kind) "
        "values ($1, $2, '1#0000', 'texto', $3, 'prose')"
    )
    await connection.execute(insert, version_id, 0, HASH_B)

    with pytest.raises(asyncpg.UniqueViolationError):
        await connection.execute(insert, version_id, 1, HASH_C)


async def test_the_same_address_may_exist_in_two_versions(
    connection: asyncpg.Connection,
) -> None:
    """Es exactamente cómo se compara una versión con la anterior."""
    document_id = await make_document(connection)
    first = await make_version(connection, document_id, number=1, digest=HASH_A)
    second = await make_version(connection, document_id, number=2, digest=HASH_B)
    insert = (
        "insert into elsa.document_chunks "
        "(version_id, ordinal, structural_key, content, content_sha256, kind) "
        "values ($1, 0, '1#0000', 'texto', $2, 'prose')"
    )

    await connection.execute(insert, first, HASH_C)
    await connection.execute(insert, second, HASH_C)

    total = await connection.fetchval("select count(*) from elsa.document_chunks")
    assert total == 2


async def test_an_empty_chunk_is_rejected(connection: asyncpg.Connection) -> None:
    document_id = await make_document(connection)
    version_id = await make_version(connection, document_id, number=1, digest=HASH_A)

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.document_chunks "
            "(version_id, ordinal, structural_key, content, content_sha256, kind) "
            "values ($1, 0, '1#0000', '   ', $2, 'prose')",
            version_id,
            HASH_B,
        )


async def test_a_structural_cut_cannot_carry_overlap(
    connection: asyncpg.Connection,
) -> None:
    """La regla del solape vive también en el esquema, no solo en el chunker."""
    document_id = await make_document(connection)
    version_id = await make_version(connection, document_id, number=1, digest=HASH_A)

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.document_chunks "
            "(version_id, ordinal, structural_key, content, content_sha256, kind, "
            " boundary_reason, overlap_chars) "
            "values ($1, 0, '1#0000', 'texto', $2, 'prose', 'structure', 40)",
            version_id,
            HASH_B,
        )


async def test_an_unknown_chunk_kind_is_rejected(connection: asyncpg.Connection) -> None:
    document_id = await make_document(connection)
    version_id = await make_version(connection, document_id, number=1, digest=HASH_A)

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.document_chunks "
            "(version_id, ordinal, structural_key, content, content_sha256, kind) "
            "values ($1, 0, '1#0000', 'texto', $2, 'lo-que-sea')",
            version_id,
            HASH_B,
        )


# ---------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------


async def test_the_lifecycle_history_cannot_be_rewritten(
    connection: asyncpg.Connection,
) -> None:
    """Un registro que puede reescribirse no es trazabilidad."""
    document_id = await make_document(connection)
    version_id = await make_version(connection, document_id, number=1, digest=HASH_A)
    await connection.execute(
        "insert into elsa.document_version_events (version_id, event, actor) "
        "values ($1, 'created', $2)",
        version_id,
        ACTOR,
    )

    with pytest.raises(asyncpg.PostgresError):
        await connection.execute("update elsa.document_version_events set event = 'published'")

    with pytest.raises(asyncpg.PostgresError):
        await connection.execute("delete from elsa.document_version_events")

    assert await connection.fetchval("select count(*) from elsa.document_version_events") == 1


async def test_rejecting_a_version_requires_a_reason(
    connection: asyncpg.Connection,
) -> None:
    """Una decisión que cierra el trabajo de alguien tiene que decir por qué."""
    document_id = await make_document(connection)
    version_id = await make_version(connection, document_id, number=1, digest=HASH_A)

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.document_version_events (version_id, event, actor) "
            "values ($1, 'rejected', $2)",
            version_id,
            ACTOR,
        )


# ---------------------------------------------------------------------
# Procedencia
# ---------------------------------------------------------------------


async def test_the_provenance_view_reconstructs_the_whole_chain(
    connection: asyncpg.Connection,
) -> None:
    document_id = await make_document(connection, asset="equipo-ejemplo")
    version_id = await make_version(
        connection, document_id, number=1, digest=HASH_A, state="published"
    )
    section_id = await connection.fetchval(
        "insert into elsa.document_sections "
        "(version_id, ordinal, path, depth, title, number_label, page_start, page_end) "
        "values ($1, 0, '1.2', 2, 'Lubricacion', '3.2', 14, 15) returning id",
        version_id,
    )
    await connection.execute(
        "insert into elsa.document_chunks "
        "(version_id, section_id, ordinal, structural_key, content, content_sha256, kind, "
        " page_start, page_end, heading_trail) "
        "values ($1, $2, 0, '1.2#0000', 'texto de ejemplo', $3, 'prose', 14, 15, "
        " array['Lubricacion']) ",
        version_id,
        section_id,
        HASH_B,
    )

    row = await connection.fetchrow("select * from elsa.document_chunk_provenance")

    assert row is not None
    assert row["document_code"] == "manual-ejemplo"
    assert row["version_number"] == 1
    assert row["version_state"] == "published"
    assert row["section_path"] == "1.2"
    assert row["section_number_label"] == "3.2"
    assert (row["page_start"], row["page_end"]) == (14, 15)
    assert row["source_sha256"] == HASH_A
    assert row["source_storage_key"]
    assert row["extractor"] == "structured_text"


async def test_the_provenance_view_exposes_the_scope_to_authorise(
    connection: asyncpg.Connection,
) -> None:
    """Es lo que permite filtrar por permiso en el mismo `where`, y no
    recuperar primero para ocultar después."""
    asset_document = await make_document(connection, code="manual-equipo", asset="equipo-a")
    domain_document = await make_document(connection, code="procedimiento-general")
    for index, document_id in enumerate((asset_document, domain_document)):
        digest = f"{index}" * 64
        version_id = await make_version(
            connection, document_id, number=1, digest=digest, state="published"
        )
        await connection.execute(
            "insert into elsa.document_chunks "
            "(version_id, ordinal, structural_key, content, content_sha256, kind) "
            "values ($1, 0, '1#0000', 'texto', $2, 'prose')",
            version_id,
            digest,
        )

    rows = await connection.fetch(
        "select document_code, scope_domain, scope_equipment "
        "from elsa.document_chunk_provenance order by document_code"
    )

    assert [(row["scope_domain"], row["scope_equipment"]) for row in rows] == [
        ("mantenimiento", "equipo-a"),
        ("mantenimiento", None),
    ]
