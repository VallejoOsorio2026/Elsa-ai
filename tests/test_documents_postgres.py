"""Garantías del adaptador documental que solo PostgreSQL puede dar.

Lo que se prueba aquí no es el contrato del puerto —eso está en
`test_contract_documents.py`, contra los dos adaptadores— sino lo que
depende de tener una base de datos real: que una escritura a medias no deja
rastro, que dos peticiones simultáneas no se pisan, y que las restricciones
del esquema afloran como errores del dominio y no como detalles internos.

Se omiten si no está definida ``ELSA_TEST_DATABASE_URL``.
"""

import asyncio
import dataclasses
from collections.abc import AsyncIterator

import asyncpg
import pytest

from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.postgres_documents import AssetNotFoundError, PostgresDocumentRepository
from elsa.adapters.structured_text_extractor import StructuredTextExtractor
from elsa.documents.chunking import chunk_document
from elsa.documents.model import ChunkingPolicy
from elsa.ports.documents import (
    DocumentRecord,
    DocumentSourceKind,
    DocumentVersionInput,
    DocumentVersionState,
    KnowledgeUnavailableError,
)
from elsa.services.document_ingestion import DocumentIngestionService, IngestedVersion
from tests import db
from tests import fixtures_documents as fx

pytestmark = pytest.mark.anyio

ACTOR = "11111111-0000-4000-8000-000000000001"
POLICY = ChunkingPolicy(
    name="pg", target_tokens=60, max_tokens=120, min_tokens=10, overlap_tokens=10
)


@pytest.fixture
async def repository() -> AsyncIterator[PostgresDocumentRepository]:
    url = db.database_url()
    if url is None:
        pytest.skip(db.SKIP_REASON)
    await db.reset_database(url)
    connection = await asyncpg.connect(url)
    for code, domain in (("equipo-a", "mantenimiento"), ("equipo-mat", "materiales")):
        await connection.execute(
            "insert into elsa.technical_assets (code, name, domain) values ($1, $2, $3)",
            code,
            f"Activo {code}",
            domain,
        )
    await connection.close()

    store = await PostgresDocumentRepository.connect(url, min_size=1, max_size=6)
    try:
        yield store
    finally:
        await store.close()


async def make_document(
    repository: PostgresDocumentRepository, *, code: str = "manual", asset: str | None = "equipo-a"
) -> DocumentRecord:
    return await repository.create_document(
        domain="mantenimiento",
        code=code,
        title="Manual de ejemplo",
        source_kind=DocumentSourceKind.MANUAL,
        asset_code=asset,
    )


def service(repository: PostgresDocumentRepository) -> DocumentIngestionService:
    return DocumentIngestionService(
        repository=repository,
        storage=InMemoryArtifactStorage(),
        extractor=StructuredTextExtractor(),
        policy=POLICY,
    )


async def ingest(
    repository: PostgresDocumentRepository, document: DocumentRecord, text: str
) -> IngestedVersion:
    result = await service(repository).ingest(
        document=document,
        content=fx.encoded(text),
        content_type="text/markdown",
        filename="manual.md",
        actor=ACTOR,
    )
    assert isinstance(result, IngestedVersion)
    return result


# ---------------------------------------------------------------------
# Atomicidad
# ---------------------------------------------------------------------


async def test_a_version_that_fails_midway_leaves_no_trace(
    repository: PostgresDocumentRepository,
) -> None:
    """Una versión con la mitad de sus chunks sería una mentira sobre el
    documento, y la recuperación no tendría forma de notarlo."""
    document = await make_document(repository)
    run = await repository.start_ingestion_run(
        document_id=document.id,
        sha256="a" * 64,
        byte_size=100,
        storage_key="k/a",
        uploaded_by=ACTOR,
        content_type="text/markdown",
    )
    extracted = await StructuredTextExtractor().extract(
        fx.encoded(fx.MANUAL_V1), content_type="text/markdown"
    )
    structure = chunk_document(extracted, document_title=document.title, policy=POLICY)
    # Un chunk vacío viola `ck_chunk_content_present`, a mitad de la escritura.
    poisoned = dataclasses.replace(structure.chunks[3], content="   ")
    broken = dataclasses.replace(
        structure, chunks=structure.chunks[:3] + (poisoned,) + structure.chunks[4:]
    )

    with pytest.raises(KnowledgeUnavailableError):
        await repository.store_version(
            DocumentVersionInput(
                document_id=document.id,
                run_id=run.id,
                source_artifact_id=run.source_artifact_id,
                content_sha256="a" * 64,
                structure=broken,
                extractor="structured_text",
                extractor_version="1",
            ),
            actor=ACTOR,
        )

    assert await repository.list_versions(document.id) == ()
    # Ni la versión, ni sus secciones, ni el cierre de la corrida.
    still_open = await repository.get_ingestion_run(run.id)
    assert still_open is not None
    assert still_open.status.value == "received"
    assert still_open.finished_at is None


async def test_a_failed_store_does_not_touch_the_published_version(
    repository: PostgresDocumentRepository,
) -> None:
    document = await make_document(repository)
    first = await ingest(repository, document, fx.MANUAL_V1)
    await service(repository).approve(version_id=first.version.id, actor=ACTOR)
    await service(repository).publish(version_id=first.version.id, actor=ACTOR)

    run = await repository.start_ingestion_run(
        document_id=document.id,
        sha256="b" * 64,
        byte_size=100,
        storage_key="k/b",
        uploaded_by=ACTOR,
    )
    extracted = await StructuredTextExtractor().extract(
        fx.encoded(fx.MANUAL_V2), content_type="text/markdown"
    )
    structure = chunk_document(extracted, document_title=document.title, policy=POLICY)
    broken = dataclasses.replace(
        structure, chunks=(dataclasses.replace(structure.chunks[0], content=" "),)
    )

    with pytest.raises(KnowledgeUnavailableError):
        await repository.store_version(
            DocumentVersionInput(
                document_id=document.id,
                run_id=run.id,
                source_artifact_id=run.source_artifact_id,
                content_sha256="b" * 64,
                structure=broken,
                extractor="structured_text",
                extractor_version="1",
            ),
            actor=ACTOR,
        )

    published = await repository.get_published_version(document.id)
    assert published is not None
    assert published.id == first.version.id
    assert len(await repository.list_chunks(published.id)) > 0


# ---------------------------------------------------------------------
# Concurrencia
# ---------------------------------------------------------------------


async def test_two_simultaneous_versions_do_not_claim_the_same_number(
    repository: PostgresDocumentRepository,
) -> None:
    """El cerrojo consultivo serializa la numeración entre procesos."""
    document = await make_document(repository)
    runs = []
    for index in range(2):
        runs.append(
            await repository.start_ingestion_run(
                document_id=document.id,
                sha256=f"{index}" * 64,
                byte_size=100,
                storage_key=f"k/{index}",
                uploaded_by=ACTOR,
            )
        )
    extracted = await StructuredTextExtractor().extract(
        fx.encoded(fx.MANUAL_V1), content_type="text/markdown"
    )
    structure = chunk_document(extracted, document_title=document.title, policy=POLICY)

    await asyncio.gather(
        *(
            repository.store_version(
                DocumentVersionInput(
                    document_id=document.id,
                    run_id=run.id,
                    source_artifact_id=run.source_artifact_id,
                    content_sha256=f"{index}" * 64,
                    structure=structure,
                    extractor="structured_text",
                    extractor_version="1",
                ),
                actor=ACTOR,
            )
            for index, run in enumerate(runs)
        )
    )

    versions = await repository.list_versions(document.id)
    assert sorted(version.version_number for version in versions) == [1, 2]


async def test_simultaneous_publications_leave_exactly_one_published(
    repository: PostgresDocumentRepository,
) -> None:
    document = await make_document(repository)
    first = await ingest(repository, document, fx.MANUAL_V1)
    second = await ingest(repository, document, fx.MANUAL_V2)
    for version in (first, second):
        await repository.set_version_state(
            version_id=version.version.id, state=DocumentVersionState.APPROVED, actor=ACTOR
        )

    await asyncio.gather(
        repository.publish_version(version_id=first.version.id, actor=ACTOR),
        repository.publish_version(version_id=second.version.id, actor=ACTOR),
        return_exceptions=True,
    )

    versions = await repository.list_versions(document.id)
    published = [v for v in versions if v.state is DocumentVersionState.PUBLISHED]
    assert len(published) == 1


# ---------------------------------------------------------------------
# Integridad del esquema, vista desde el adaptador
# ---------------------------------------------------------------------


async def test_a_document_cannot_hang_off_an_unknown_asset(
    repository: PostgresDocumentRepository,
) -> None:
    with pytest.raises(AssetNotFoundError):
        await make_document(repository, code="huerfano", asset="no-existe")


async def test_a_document_cannot_hang_off_an_asset_of_another_domain(
    repository: PostgresDocumentRepository,
) -> None:
    """Si pudiera, el alcance de autorización mentiría."""
    with pytest.raises(AssetNotFoundError):
        await make_document(repository, code="cruzado", asset="equipo-mat")


async def test_sections_and_chunks_belong_to_the_same_version(
    repository: PostgresDocumentRepository,
) -> None:
    document = await make_document(repository)
    first = await ingest(repository, document, fx.MANUAL_V1)
    await service(repository).approve(version_id=first.version.id, actor=ACTOR)
    await service(repository).publish(version_id=first.version.id, actor=ACTOR)
    second = await ingest(repository, document, fx.MANUAL_V2)

    for version in (first, second):
        sections = {s.id for s in await repository.list_sections(version.version.id)}
        chunks = await repository.list_chunks(version.version.id)
        assert {c.version_id for c in chunks} == {version.version.id}
        assert all(c.section_id in sections for c in chunks)


async def test_the_adapter_never_writes_outside_its_own_tables(
    repository: PostgresDocumentRepository,
) -> None:
    """La ingesta documental no toca el conocimiento estructurado."""
    url = db.database_url()
    assert url is not None
    document = await make_document(repository)
    await ingest(repository, document, fx.MANUAL_V1)

    connection = await asyncpg.connect(url)
    try:
        for table in (
            "engineering_bom_versions",
            "engineering_bom_items",
            "sap_bom_snapshots",
            "failure_modes",
            "sod_criteria",
            "components",
            "imports",
            "reviews",
        ):
            assert await connection.fetchval(f"select count(*) from elsa.{table}") == 0
    finally:
        await connection.close()


async def test_the_store_reports_when_it_is_gone(
    repository: PostgresDocumentRepository,
) -> None:
    """Un fallo de infraestructura se traduce, no se filtra."""
    await repository.check_health()
    await repository.close()

    with pytest.raises(KnowledgeUnavailableError):
        await repository.check_health()


# ---------------------------------------------------------------------
# Composición
# ---------------------------------------------------------------------


async def test_the_container_selects_the_store_by_configuration() -> None:
    """`memory` en DEV, PostgreSQL cuando los permisos van a PostgreSQL.

    El documental sigue el mismo selector que el conocimiento técnico y los
    permisos: los tres viven en la misma base.
    """
    from elsa.adapters.memory_documents import InMemoryDocumentRepository
    from elsa.container import Container
    from tests.conftest import make_test_settings

    container = Container(make_test_settings())

    assert isinstance(container.documents, InMemoryDocumentRepository)
    assert container.require_documents() is container.documents
