"""Garantías que solo PostgreSQL puede demostrar.

Aquí no se prueba lógica de aplicación sino lo que el **esquema** impide,
incluso frente a un backend que se equivoque o a dos procesos simultáneos:
una sola versión publicada, un NPR coherente, un rechazo sin motivo, una
validación que alguien intente borrar y dos publicaciones a la vez.

Se ejecutan contra una instancia local y efímera. Nunca contra Supabase.
"""

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal

import asyncpg
import pytest

from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.postgres_knowledge import PostgresKnowledgeRepository
from elsa.adapters.postgres_permissions import PostgresPermissionsRepository
from elsa.core.review import ReviewDecision, ReviewSubject
from elsa.ingestion.model import ParsedBomRow
from elsa.ports.knowledge import (
    EngineeringVersionInput,
    ImportKind,
    KnowledgeUnavailableError,
    NotPublishableError,
    ResolvedBomRow,
    TechnicalAssetRecord,
    VersionState,
)
from elsa.ports.permissions import AdminOperation
from elsa.services.ingestion import DuplicateImport, IngestionService
from tests import db
from tests.fixtures_sources import engineering_workbook

pytestmark = pytest.mark.anyio

ACTOR = "aaaaaaaa-0000-4000-8000-000000000001"
REVIEWER = "bbbbbbbb-0000-4000-8000-000000000002"


@pytest.fixture
async def url() -> str:
    value = db.database_url()
    if value is None:
        pytest.skip(db.SKIP_REASON)
    await db.reset_database(value)
    return value


@pytest.fixture
async def repository(url: str) -> AsyncIterator[PostgresKnowledgeRepository]:
    postgres = await PostgresKnowledgeRepository.connect(url, min_size=2, max_size=6)
    try:
        yield postgres
    finally:
        await postgres.close()


@pytest.fixture
async def connection(url: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(url)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def asset(repository: PostgresKnowledgeRepository) -> TechnicalAssetRecord:
    return await repository.create_asset(
        code="tampella", name="Activo de prueba", domain="mantenimiento"
    )


async def _version(
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
    digest: str,
) -> str:
    record = await repository.start_import(
        asset_id=asset.id,
        kind=ImportKind.ENGINEERING_BOM,
        sha256=digest,
        byte_size=10,
        storage_key=f"engineering_bom_xlsx/{digest[:2]}/{digest}",
        uploaded_by=ACTOR,
    )
    version = await repository.store_engineering_version(
        EngineeringVersionInput(
            asset_id=asset.id,
            import_id=record.id,
            source_artifact_id=record.source_artifact_id,
            rows=[
                ResolvedBomRow(
                    row=ParsedBomRow(
                        source_row=2,
                        subsystem_name="Accionamiento",
                        component_name="Pieza ficticia",
                        sap_code="10000001",
                        quantity=Decimal(1),
                        assembly_drawing="PL-001",
                        drawing_reference="R-01",
                    ),
                    change_kind="new",
                )
            ],
        ),
        actor=ACTOR,
    )
    await repository.set_version_state(version_id=version.id, state=VersionState.APPROVED)
    return version.id


# ---------------------------------------------------------------------
# Restricciones del esquema
# ---------------------------------------------------------------------


async def test_the_schema_allows_a_single_published_version_per_asset(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    """No «improbable»: imposible."""
    first = await _version(repository, asset, "a" * 64)
    await repository.publish_version(
        version_id=first.id if hasattr(first, "id") else first, actor=ACTOR
    )
    second = await _version(repository, asset, "b" * 64)

    with pytest.raises(asyncpg.UniqueViolationError):
        await connection.execute(
            "update elsa.engineering_bom_versions set state = 'published' where id = $1",
            second,
        )


async def test_the_schema_rejects_an_incoherent_rpn(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    version = await _version(repository, asset, "a" * 64)

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.failure_modes "
            "(version_id, source_row, severity, occurrence, detection, rpn) "
            "values ($1, 99, 2, 3, 4, 999)",
            version,
        )


async def test_the_schema_accepts_a_coherent_rpn(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    version = await _version(repository, asset, "a" * 64)

    await connection.execute(
        "insert into elsa.failure_modes "
        "(version_id, source_row, severity, occurrence, detection, rpn) "
        "values ($1, 99, 2, 3, 4, 24)",
        version,
    )


async def test_the_schema_rejects_a_rejection_without_a_reason(
    connection: asyncpg.Connection, asset: TechnicalAssetRecord
) -> None:
    """La capa HTTP puede equivocarse; la base no."""
    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.reviews (asset_id, subject_kind, subject_id, decision, reviewer) "
            "values ($1, 'bom_item', gen_random_uuid(), 'rejected', $2)",
            asset.id,
            REVIEWER,
        )


async def test_the_schema_accepts_an_approval_without_a_comment(
    connection: asyncpg.Connection, asset: TechnicalAssetRecord
) -> None:
    await connection.execute(
        "insert into elsa.reviews (asset_id, subject_kind, subject_id, decision, reviewer) "
        "values ($1, 'bom_item', gen_random_uuid(), 'approved', $2)",
        asset.id,
        REVIEWER,
    )


async def test_validations_can_never_be_updated_or_deleted(
    connection: asyncpg.Connection, asset: TechnicalAssetRecord
) -> None:
    """Un registro que puede reescribirse no es auditoría."""
    await connection.execute(
        "insert into elsa.reviews (asset_id, subject_kind, subject_id, decision, reviewer) "
        "values ($1, 'bom_item', gen_random_uuid(), 'approved', $2)",
        asset.id,
        REVIEWER,
    )

    with pytest.raises(asyncpg.PostgresError):
        await connection.execute("update elsa.reviews set comment = 'cambiado'")
    with pytest.raises(asyncpg.PostgresError):
        await connection.execute("delete from elsa.reviews")

    assert await connection.fetchval("select count(*) from elsa.reviews") == 1


async def test_the_schema_rejects_a_resolved_drawing_without_a_drawing(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    """Una asociación «resuelta» tiene que apuntar a un plano real."""
    version = await _version(repository, asset, "a" * 64)
    artifact = await connection.fetchval("select id from elsa.source_artifacts limit 1")
    derived = await connection.fetchval(
        "insert into elsa.derived_artifacts "
        "(source_artifact_id, kind, sha256, byte_size, storage_key) "
        "values ($1, 'drawing_image', $2, 10, 'k1') returning id",
        artifact,
        "c" * 64,
    )

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.drawing_images "
            "(version_id, derived_artifact_id, association_status) values ($1, $2, 'resolved')",
            version,
            derived,
        )


async def test_the_schema_rejects_an_out_of_range_sod_value(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    version = await _version(repository, asset, "a" * 64)

    with pytest.raises(asyncpg.CheckViolationError):
        await connection.execute(
            "insert into elsa.sod_criteria (version_id, dimension, scale_value, source_row) "
            "values ($1, 'severity', 42, 1)",
            version,
        )


async def test_the_schema_rejects_an_unknown_reconciliation_class(
    connection: asyncpg.Connection, asset: TechnicalAssetRecord
) -> None:
    with pytest.raises(asyncpg.PostgresError):
        await connection.execute(
            "insert into elsa.reconciliation_items (run_id, classification, bom_item_id) "
            "values (gen_random_uuid(), 'inventada', gen_random_uuid())"
        )


async def test_the_same_file_cannot_be_registered_twice(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    await _version(repository, asset, "a" * 64)

    with pytest.raises(asyncpg.UniqueViolationError):
        await connection.execute(
            "insert into elsa.source_artifacts "
            "(kind, sha256, byte_size, storage_key, uploaded_by) "
            "values ('engineering_bom_xlsx', $1, 10, 'otra-clave', $2)",
            "a" * 64,
            ACTOR,
        )


# ---------------------------------------------------------------------
# Transacciones y concurrencia
# ---------------------------------------------------------------------


async def test_a_failed_version_write_leaves_nothing_behind(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    """Una versión a medias sería peor que ninguna."""
    record = await repository.start_import(
        asset_id=asset.id,
        kind=ImportKind.ENGINEERING_BOM,
        sha256="d" * 64,
        byte_size=10,
        storage_key="engineering_bom_xlsx/dd/" + "d" * 64,
        uploaded_by=ACTOR,
    )
    broken = ResolvedBomRow(
        # Dos renglones con la misma fila de origen violan `unique
        # (version_id, source_row)` en mitad de la escritura.
        row=ParsedBomRow(source_row=1, component_name="Pieza"),
        change_kind="new",
    )

    # Un fallo de integridad a mitad de la escritura se traduce a
    # indisponibilidad y deshace la transacción entera. Lo que importa aquí
    # es lo segundo: no queda media versión.
    with pytest.raises(KnowledgeUnavailableError):
        await repository.store_engineering_version(
            EngineeringVersionInput(
                asset_id=asset.id,
                import_id=record.id,
                source_artifact_id=record.source_artifact_id,
                rows=[broken, broken],
            ),
            actor=ACTOR,
        )

    assert await connection.fetchval("select count(*) from elsa.engineering_bom_versions") == 0
    assert await connection.fetchval("select count(*) from elsa.engineering_bom_items") == 0
    assert await connection.fetchval("select count(*) from elsa.components") == 0


async def test_two_simultaneous_publications_leave_a_single_current_version(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    """El cerrojo consultivo serializa; el índice parcial garantiza."""
    first = await _version(repository, asset, "a" * 64)
    second = await _version(repository, asset, "b" * 64)

    results = await asyncio.gather(
        repository.publish_version(version_id=first, actor=ACTOR),
        repository.publish_version(version_id=second, actor=ACTOR),
        return_exceptions=True,
    )

    assert not any(isinstance(result, BaseException) for result in results), results
    published = await connection.fetchval(
        "select count(*) from elsa.engineering_bom_versions where state = 'published'"
    )
    assert published == 1


async def test_two_simultaneous_uploads_of_the_same_file_create_one_import(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    service = IngestionService(repository, InMemoryArtifactStorage())
    workbook = engineering_workbook()

    results = await asyncio.gather(
        service.ingest_engineering_bom(asset=asset, data=workbook, actor=ACTOR),
        service.ingest_engineering_bom(asset=asset, data=workbook, actor=ACTOR),
        return_exceptions=True,
    )

    assert not any(isinstance(result, BaseException) for result in results), results
    assert sum(isinstance(result, DuplicateImport) for result in results) == 1
    versions = await connection.fetchval("select count(*) from elsa.engineering_bom_versions")
    assert versions == 1


async def test_two_simultaneous_version_writes_get_distinct_numbers(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    results = await asyncio.gather(
        _version(repository, asset, "a" * 64),
        _version(repository, asset, "b" * 64),
        return_exceptions=True,
    )

    assert not any(isinstance(result, BaseException) for result in results), results
    numbers = await connection.fetch(
        "select version_number from elsa.engineering_bom_versions order by version_number"
    )
    assert [row["version_number"] for row in numbers] == [1, 2]


async def test_a_rejected_version_cannot_be_published(
    repository: PostgresKnowledgeRepository, asset: TechnicalAssetRecord
) -> None:
    version = await _version(repository, asset, "a" * 64)
    await repository.set_version_state(version_id=version, state=VersionState.REJECTED)

    with pytest.raises(NotPublishableError):
        await repository.publish_version(version_id=version, actor=ACTOR)


# ---------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------


async def test_the_lifecycle_is_audited_without_technical_content(
    connection: asyncpg.Connection,
    repository: PostgresKnowledgeRepository,
    asset: TechnicalAssetRecord,
) -> None:
    version = await _version(repository, asset, "a" * 64)
    await repository.record_review(
        asset_id=asset.id,
        subject_kind=ReviewSubject.ENGINEERING_BOM_VERSION,
        subject_id=version,
        decision=ReviewDecision.APPROVED,
        reviewer=REVIEWER,
        comment="revisado contra el plano de despiece",
    )
    await repository.publish_version(version_id=version, actor=ACTOR)

    rows = await connection.fetch("select operation, details from elsa.admin_audit_log")

    operations = {row["operation"] for row in rows}
    assert AdminOperation.SOURCE_UPLOADED.value in operations
    assert AdminOperation.IMPORT_COMPLETED.value in operations
    assert AdminOperation.VALIDATION_APPROVED.value in operations
    assert AdminOperation.BOM_PUBLISHED.value in operations
    # El comentario del revisor puede contener detalle técnico: no se audita.
    assert all("plano de despiece" not in str(row["details"]) for row in rows)


async def test_a_reviewer_grant_survives_the_reviewer_being_revoked(
    url: str, connection: asyncpg.Connection
) -> None:
    """Revocar conserva la fila: el historial nunca queda huérfano."""
    permissions = await PostgresPermissionsRepository.connect(url, min_size=1, max_size=2)
    try:
        await permissions.grant_reviewer(
            subject=REVIEWER, domain="mantenimiento", equipment="tampella", actor=ACTOR
        )
        await permissions.revoke_reviewer(
            subject=REVIEWER, domain="mantenimiento", equipment="tampella", actor=ACTOR
        )

        assert await permissions.list_active_reviewer_grants(REVIEWER) == ()
        total = await connection.fetchval("select count(*) from elsa.reviewer_grants")
        assert total == 1
    finally:
        await permissions.close()


async def test_a_reviewer_can_be_granted_again_after_being_revoked(
    url: str, connection: asyncpg.Connection
) -> None:
    permissions = await PostgresPermissionsRepository.connect(url, min_size=1, max_size=2)
    try:
        await permissions.grant_reviewer(
            subject=REVIEWER, domain="mantenimiento", equipment="tampella", actor=ACTOR
        )
        await permissions.revoke_reviewer(
            subject=REVIEWER, domain="mantenimiento", equipment="tampella", actor=ACTOR
        )
        await permissions.grant_reviewer(
            subject=REVIEWER, domain="mantenimiento", equipment="tampella", actor=ACTOR
        )

        assert len(await permissions.list_active_reviewer_grants(REVIEWER)) == 1
        assert await connection.fetchval("select count(*) from elsa.reviewer_grants") == 2
    finally:
        await permissions.close()
