"""Contrato del puerto de conocimiento técnico.

La misma batería corre contra los dos adaptadores: el de memoria (DEV y
tests) y el de PostgreSQL (Supabase ELSA). Si divergen, uno de los dos falla
aquí: el adaptador de memoria no puede volverse una ficción cómoda.
"""

from collections.abc import AsyncIterator
from decimal import Decimal

import pytest

from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.postgres_knowledge import PostgresKnowledgeRepository
from elsa.core.review import ReviewDecision, ReviewSubject
from elsa.ingestion.model import ParsedBomRow
from elsa.ports.knowledge import (
    AssetAlreadyExistsError,
    DuplicateSourceError,
    EngineeringVersionInput,
    EngineeringVersionRecord,
    ImportKind,
    ImportRecord,
    ImportStatus,
    KnowledgeRepositoryPort,
    NotPublishableError,
    ResolvedBomRow,
    TechnicalAssetRecord,
    VersionState,
)
from elsa.services.ingestion import DuplicateImport, IngestionService
from tests import db
from tests.fixtures_sources import engineering_workbook, sap_export

pytestmark = pytest.mark.anyio

ACTOR = "aaaaaaaa-0000-4000-8000-000000000001"
OTHER_ACTOR = "bbbbbbbb-0000-4000-8000-000000000002"
DIGEST = "a" * 64


@pytest.fixture(params=["memory", "postgres"])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[KnowledgeRepositoryPort]:
    if request.param == "memory":
        yield InMemoryKnowledgeRepository()
        return

    url = db.database_url()
    if url is None:
        pytest.skip(db.SKIP_REASON)
    await db.reset_database(url)
    postgres = await PostgresKnowledgeRepository.connect(url, min_size=1, max_size=3)
    try:
        yield postgres
    finally:
        await postgres.close()


@pytest.fixture
async def asset(repository: KnowledgeRepositoryPort) -> TechnicalAssetRecord:
    return await repository.create_asset(
        code="tampella", name="Activo de prueba", domain="mantenimiento"
    )


@pytest.fixture
def service(repository: KnowledgeRepositoryPort) -> IngestionService:
    return IngestionService(repository, InMemoryArtifactStorage())


# ---------------------------------------------------------------------
# Activos
# ---------------------------------------------------------------------


async def test_an_asset_can_be_created_and_read_back(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    found = await repository.get_asset("tampella")

    assert found is not None
    assert found.id == asset.id
    assert found.domain == "mantenimiento"


async def test_the_model_holds_several_assets(repository: KnowledgeRepositoryPort) -> None:
    await repository.create_asset(code="uno", name="Uno", domain="mantenimiento")
    await repository.create_asset(code="dos", name="Dos", domain="mantenimiento")

    assert {a.code for a in await repository.list_assets()} == {"uno", "dos"}


async def test_a_duplicate_asset_code_is_refused(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    with pytest.raises(AssetAlreadyExistsError):
        await repository.create_asset(code="tampella", name="Otro", domain="mantenimiento")


async def test_an_unknown_asset_is_none(repository: KnowledgeRepositoryPort) -> None:
    assert await repository.get_asset("no-existe") is None


# ---------------------------------------------------------------------
# Importaciones
# ---------------------------------------------------------------------


async def _start_import(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord, digest: str = DIGEST
) -> ImportRecord:
    return await repository.start_import(
        asset_id=asset.id,
        kind=ImportKind.ENGINEERING_BOM,
        sha256=digest,
        byte_size=1024,
        storage_key=f"engineering_bom_xlsx/{digest[:2]}/{digest}",
        uploaded_by=ACTOR,
        original_filename="bom.xlsx",
    )


async def test_the_same_file_cannot_be_imported_twice(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    """La unicidad la impone el almacén, no una comprobación previa."""
    await _start_import(repository, asset)

    with pytest.raises(DuplicateSourceError):
        await _start_import(repository, asset)


async def test_a_previous_import_of_the_same_file_is_found(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    started = await _start_import(repository, asset)

    found = await repository.find_import_by_source(kind="engineering_bom_xlsx", sha256=DIGEST)

    assert found is not None
    assert found.id == started.id


async def test_a_failed_import_records_its_failure_kind(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    started = await _start_import(repository, asset)

    failed = await repository.fail_import(
        import_id=started.id,
        failure_kind="parse",
        failure_message="the sheet could not be read",
        actor=ACTOR,
    )

    assert failed.status is ImportStatus.FAILED
    assert failed.failure_kind == "parse"
    assert failed.finished_at is not None


# ---------------------------------------------------------------------
# Versiones
# ---------------------------------------------------------------------


def _row(source_row: int, sap_code: str | None, quantity: int) -> ResolvedBomRow:
    return ResolvedBomRow(
        row=ParsedBomRow(
            source_row=source_row,
            subsystem_name="Accionamiento",
            component_name=f"Pieza {source_row}",
            sap_code=sap_code,
            sap_code_original=sap_code,
            quantity=Decimal(quantity),
            quantity_original=str(quantity),
            unit="UN",
            assembly_drawing="PL-001",
            drawing_reference=f"R-{source_row:02d}",
            model_reference=f"MOD-{source_row}",
        ),
        change_kind="new",
    )


async def _store_version(
    repository: KnowledgeRepositoryPort,
    asset: TechnicalAssetRecord,
    *,
    digest: str = DIGEST,
    rows: list[ResolvedBomRow] | None = None,
) -> EngineeringVersionRecord:
    record = await _start_import(repository, asset, digest)
    return await repository.store_engineering_version(
        EngineeringVersionInput(
            asset_id=asset.id,
            import_id=record.id,
            source_artifact_id=record.source_artifact_id,
            rows=rows if rows is not None else [_row(2, "10000001", 2), _row(3, None, 1)],
        ),
        actor=ACTOR,
    )


async def test_a_stored_version_starts_pending_validation(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    version = await _store_version(repository, asset)

    assert version.state is VersionState.PENDING_VALIDATION
    assert version.version_number == 1


async def test_storing_a_version_completes_its_import(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    version = await _store_version(repository, asset)

    record = await repository.get_import(version.import_id)

    assert record is not None
    assert record.status is ImportStatus.COMPLETED
    assert record.stats["bom_items"] == 2


async def test_every_component_gets_a_permanent_internal_uuid(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    version = await _store_version(repository, asset)

    items = await repository.list_version_items(version.id)

    assert all(item.component_id is not None for item in items)
    assert len({item.component_id for item in items}) == 2


async def test_a_component_without_a_sap_code_is_valid(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    version = await _store_version(repository, asset)

    items = await repository.list_version_items(version.id)

    without_code = [item for item in items if item.sap_code is None]
    assert len(without_code) == 1
    assert without_code[0].component_id is not None


async def test_several_components_may_lack_a_sap_code(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    version = await _store_version(
        repository, asset, rows=[_row(2, None, 1), _row(3, None, 2), _row(4, None, 3)]
    )

    items = await repository.list_version_items(version.id)

    assert len(items) == 3
    assert all(item.sap_code is None and item.component_id is not None for item in items)


async def test_an_ambiguous_row_is_stored_without_a_component(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    """No se crea un componente nuevo: bifurcaría una identidad existente."""
    ambiguous = ResolvedBomRow(
        row=_row(2, "10000001", 1).row,
        ambiguous=True,
        match_rule="sap_code_ambiguous",
        match_confidence="unresolved",
    )

    version = await _store_version(repository, asset, rows=[ambiguous])
    items = await repository.list_version_items(version.id)

    assert items[0].component_id is None
    assert items[0].match_confidence == "unresolved"


async def test_versions_are_numbered_in_sequence(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    await _store_version(repository, asset, digest="a" * 64)
    second = await _store_version(repository, asset, digest="b" * 64)

    assert second.version_number == 2
    assert len(await repository.list_versions(asset.id)) == 2


# ---------------------------------------------------------------------
# Publicación
# ---------------------------------------------------------------------


async def test_an_unapproved_version_cannot_be_published(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    version = await _store_version(repository, asset)

    with pytest.raises(NotPublishableError):
        await repository.publish_version(version_id=version.id, actor=ACTOR)


async def test_publishing_makes_exactly_one_version_current(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    version = await _store_version(repository, asset)
    await repository.set_version_state(version_id=version.id, state=VersionState.APPROVED)

    published = await repository.publish_version(version_id=version.id, actor=ACTOR)

    assert published.state is VersionState.PUBLISHED
    current = await repository.get_published_version(asset.id)
    assert current is not None and current.id == published.id


async def test_publishing_a_second_version_supersedes_the_first(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    first = await _store_version(repository, asset, digest="a" * 64)
    await repository.set_version_state(version_id=first.id, state=VersionState.APPROVED)
    await repository.publish_version(version_id=first.id, actor=ACTOR)
    second = await _store_version(repository, asset, digest="b" * 64)
    await repository.set_version_state(version_id=second.id, state=VersionState.APPROVED)

    await repository.publish_version(version_id=second.id, actor=ACTOR)

    states = {v.version_number: v.state for v in await repository.list_versions(asset.id)}
    assert states == {1: VersionState.SUPERSEDED, 2: VersionState.PUBLISHED}


async def test_a_superseded_version_keeps_its_rows(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    """Nunca se sobrescribe una versión anterior."""
    first = await _store_version(repository, asset, digest="a" * 64)
    await repository.set_version_state(version_id=first.id, state=VersionState.APPROVED)
    await repository.publish_version(version_id=first.id, actor=ACTOR)
    second = await _store_version(repository, asset, digest="b" * 64, rows=[_row(2, "999", 1)])
    await repository.set_version_state(version_id=second.id, state=VersionState.APPROVED)
    await repository.publish_version(version_id=second.id, actor=ACTOR)

    items = await repository.list_version_items(first.id)

    assert len(items) == 2


async def test_publishing_twice_is_idempotent(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    version = await _store_version(repository, asset)
    await repository.set_version_state(version_id=version.id, state=VersionState.APPROVED)
    first = await repository.publish_version(version_id=version.id, actor=ACTOR)

    again = await repository.publish_version(version_id=version.id, actor=ACTOR)

    assert again.id == first.id
    assert again.state is VersionState.PUBLISHED


# ---------------------------------------------------------------------
# Validaciones
# ---------------------------------------------------------------------


async def test_a_validation_is_recorded_and_read_back(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    version = await _store_version(repository, asset)

    review = await repository.record_review(
        asset_id=asset.id,
        subject_kind=ReviewSubject.ENGINEERING_BOM_VERSION,
        subject_id=version.id,
        decision=ReviewDecision.APPROVED,
        reviewer=ACTOR,
        subject_version_id=version.id,
    )

    latest = await repository.latest_review(
        subject_kind=ReviewSubject.ENGINEERING_BOM_VERSION,
        subject_id=version.id,
    )
    assert latest is not None and latest.id == review.id


async def test_reverting_adds_a_record_and_keeps_the_original(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord
) -> None:
    version = await _store_version(repository, asset)
    original = await repository.record_review(
        asset_id=asset.id,
        subject_kind=ReviewSubject.ENGINEERING_BOM_VERSION,
        subject_id=version.id,
        decision=ReviewDecision.APPROVED,
        reviewer=ACTOR,
    )

    reverted = await repository.record_review(
        asset_id=asset.id,
        subject_kind=ReviewSubject.ENGINEERING_BOM_VERSION,
        subject_id=version.id,
        decision=ReviewDecision.REVERTED,
        reviewer=OTHER_ACTOR,
        comment="faltaba verificar el plano",
        reverts_review_id=original.id,
    )

    history = await repository.list_reviews(asset_id=asset.id)
    assert {entry.id for entry in history} == {original.id, reverted.id}
    latest = await repository.latest_review(
        subject_kind=ReviewSubject.ENGINEERING_BOM_VERSION,
        subject_id=version.id,
    )
    assert latest is not None and latest.decision is ReviewDecision.REVERTED


# ---------------------------------------------------------------------
# Snapshots y reconciliación, a través del servicio
# ---------------------------------------------------------------------


async def test_the_whole_pipeline_runs_on_both_adapters(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord, service: IngestionService
) -> None:
    version = await service.ingest_engineering_bom(
        asset=asset, data=engineering_workbook(), actor=ACTOR
    )
    assert not isinstance(version, DuplicateImport)
    await repository.set_version_state(version_id=version.id, state=VersionState.APPROVED)
    await repository.publish_version(version_id=version.id, actor=ACTOR)

    snapshot = await service.ingest_sap_snapshot(asset=asset, data=sap_export(), actor=ACTOR)
    assert not isinstance(snapshot, DuplicateImport)
    run = await service.reconcile_published_bom(
        asset=asset, version_id=version.id, snapshot_id=snapshot.id, actor=ACTOR
    )

    assert run.stats["quantity_difference"] == 1
    assert run.stats["sap_only"] == 1
    items = await repository.list_reconciliation_items(run.id)
    assert len(items) == sum(run.stats.values())


async def test_a_snapshot_is_kept_apart_from_the_published_bom(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord, service: IngestionService
) -> None:
    version = await service.ingest_engineering_bom(
        asset=asset, data=engineering_workbook(), actor=ACTOR
    )
    assert not isinstance(version, DuplicateImport)
    await repository.set_version_state(version_id=version.id, state=VersionState.APPROVED)
    await repository.publish_version(version_id=version.id, actor=ACTOR)

    await service.ingest_sap_snapshot(asset=asset, data=sap_export(), actor=ACTOR)

    published = await repository.get_published_version(asset.id)
    assert published is not None and published.id == version.id
    assert len(await repository.list_snapshots(asset.id)) == 1


async def test_reimporting_the_same_source_creates_no_new_version(
    repository: KnowledgeRepositoryPort, asset: TechnicalAssetRecord, service: IngestionService
) -> None:
    workbook = engineering_workbook()
    await service.ingest_engineering_bom(asset=asset, data=workbook, actor=ACTOR)

    again = await service.ingest_engineering_bom(asset=asset, data=workbook, actor=ACTOR)

    assert isinstance(again, DuplicateImport)
    assert len(await repository.list_versions(asset.id)) == 1
