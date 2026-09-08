"""Ciclo de vida documental: ingestar, validar, comparar, activar.

Lo que se prueba aquí no es que el código corra, sino que las promesas del
bloque se sostienen: una versión nueva no reemplaza sola a la publicada, una
ingesta fallida no destruye la última versión válida, y nadie lee un chunk de
un activo que no tiene autorizado.
"""

from collections.abc import AsyncIterator

import pytest

from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.memory_documents import InMemoryDocumentRepository
from elsa.adapters.structured_text_extractor import StructuredTextExtractor
from elsa.core.authorization import Principal, Scope
from elsa.core.document_access import may_read, readable, readable_scopes
from elsa.core.versioning import ChangeKind
from elsa.documents.model import ChunkingPolicy
from elsa.ports.documents import (
    DocumentRecord,
    DocumentRepositoryPort,
    DocumentSourceKind,
    DocumentVersionState,
    NotPublishableError,
    VersionEvent,
)
from elsa.services.document_ingestion import (
    DocumentIngestionError,
    DocumentIngestionService,
    DuplicateDocumentSource,
    IngestedVersion,
)
from tests import fixtures_documents as fx

pytestmark = pytest.mark.anyio

ACTOR = "11111111-0000-4000-8000-000000000001"
POLICY = ChunkingPolicy(
    name="test-small", target_tokens=60, max_tokens=120, min_tokens=10, overlap_tokens=10
)


@pytest.fixture
def repository() -> InMemoryDocumentRepository:
    return InMemoryDocumentRepository()


@pytest.fixture
def service(repository: InMemoryDocumentRepository) -> DocumentIngestionService:
    return DocumentIngestionService(
        repository=repository,
        storage=InMemoryArtifactStorage(),
        extractor=StructuredTextExtractor(),
        policy=POLICY,
    )


@pytest.fixture
async def document(repository: InMemoryDocumentRepository) -> AsyncIterator[DocumentRecord]:
    yield await repository.create_document(
        domain="mantenimiento",
        code="manual-ejemplo",
        title="Manual de ejemplo",
        source_kind=DocumentSourceKind.MANUAL,
        asset_code="equipo-ejemplo",
    )


async def ingest(
    service: DocumentIngestionService, document: DocumentRecord, text: str
) -> IngestedVersion | DuplicateDocumentSource:
    return await service.ingest(
        document=document,
        content=fx.encoded(text),
        content_type="text/markdown",
        filename="manual.md",
        actor=ACTOR,
    )


# ---------------------------------------------------------------------
# Contrato del puerto
# ---------------------------------------------------------------------


def test_the_memory_repository_satisfies_its_port(
    repository: InMemoryDocumentRepository,
) -> None:
    assert isinstance(repository, DocumentRepositoryPort)


# ---------------------------------------------------------------------
# Ingesta
# ---------------------------------------------------------------------


async def test_a_new_version_arrives_pending_validation_never_published(
    service: DocumentIngestionService, document: DocumentRecord
) -> None:
    result = await ingest(service, document, fx.MANUAL_V1)

    assert isinstance(result, IngestedVersion)
    assert result.version.state is DocumentVersionState.PENDING_VALIDATION
    assert result.version.version_number == 1
    assert result.version.published_at is None


async def test_the_version_records_what_produced_it(
    service: DocumentIngestionService, document: DocumentRecord
) -> None:
    """Sin el extractor y la política, dos versiones no son comparables."""
    result = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    assert result.version.extractor == "structured_text"
    assert result.version.extractor_version == "1"
    assert result.version.chunking_profile == "test-small"
    assert result.version.chunking_parameters["target_tokens"] == 60
    assert len(result.version.content_sha256) == 64
    assert len(result.version.structure_sha256) == 64


async def test_re_ingesting_the_same_file_does_not_create_a_version(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    first = await ingest(service, document, fx.MANUAL_V1)
    second = await ingest(service, document, fx.MANUAL_V1)

    assert isinstance(first, IngestedVersion)
    assert isinstance(second, DuplicateDocumentSource)
    assert second.existing_run_id == first.run.id
    assert len(await repository.list_versions(document.id)) == 1


async def test_ingestion_is_idempotent_down_to_the_hashes(
    service: DocumentIngestionService, repository: InMemoryDocumentRepository
) -> None:
    """El mismo documento en dos documentos distintos produce la misma
    estructura: el chunking no depende de nada externo al archivo."""
    one = await repository.create_document(
        domain="mantenimiento",
        code="uno",
        title="Manual de ejemplo",
        source_kind=DocumentSourceKind.MANUAL,
        asset_code="equipo-a",
    )
    two = await repository.create_document(
        domain="mantenimiento",
        code="dos",
        title="Manual de ejemplo",
        source_kind=DocumentSourceKind.MANUAL,
        asset_code="equipo-b",
    )

    first = await ingest(service, one, fx.MANUAL_V1)
    # El mismo contenido byte a byte ya estaría registrado, así que se
    # cambia una línea irrelevante para poder ingerirlo en el segundo.
    assert isinstance(first, IngestedVersion)
    second = await ingest(service, two, fx.MANUAL_V1 + "\n")
    assert isinstance(second, IngestedVersion)

    assert first.structure.structure_sha256 == second.structure.structure_sha256


async def test_an_unreadable_document_fails_without_creating_a_version(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    with pytest.raises(DocumentIngestionError) as error:
        await service.ingest(
            document=document,
            content=fx.NOT_TEXT,
            content_type="text/plain",
            filename="manual.txt",
            actor=ACTOR,
        )

    assert error.value.failure_kind == "file"
    assert await repository.list_versions(document.id) == ()
    run = await repository.get_ingestion_run(error.value.run_id or "")
    assert run is not None and run.status.value == "failed"


async def test_an_empty_document_is_rejected_by_validation(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    with pytest.raises(DocumentIngestionError) as error:
        await ingest(service, document, fx.EMPTY_DOCUMENT)

    assert error.value.failure_kind == "parse"
    assert error.value.report is not None
    assert {issue.code for issue in error.value.report.blocking} == {"empty_document", "no_chunks"}
    assert await repository.list_versions(document.id) == ()


async def test_a_failed_ingestion_never_destroys_the_published_version(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    """Es la promesa que hace seguro reintentar sobre un documento en uso."""
    first = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await service.approve(version_id=first.version.id, actor=ACTOR)
    published = await service.publish(version_id=first.version.id, actor=ACTOR)

    with pytest.raises(DocumentIngestionError):
        await ingest(service, document, fx.EMPTY_DOCUMENT)

    still = await repository.get_published_version(document.id)
    assert still is not None
    assert still.id == published.id
    assert still.state is DocumentVersionState.PUBLISHED
    assert len(await repository.list_chunks(still.id)) > 0


# ---------------------------------------------------------------------
# Publicación
# ---------------------------------------------------------------------


async def test_a_version_cannot_be_published_without_being_approved(
    service: DocumentIngestionService, document: DocumentRecord
) -> None:
    result = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    with pytest.raises(NotPublishableError):
        await service.publish(version_id=result.version.id, actor=ACTOR)


async def test_publishing_supersedes_the_previous_version(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    first = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await service.approve(version_id=first.version.id, actor=ACTOR)
    await service.publish(version_id=first.version.id, actor=ACTOR)

    second = await ingest(service, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)
    await service.approve(version_id=second.version.id, actor=ACTOR)
    await service.publish(version_id=second.version.id, actor=ACTOR)

    versions = await repository.list_versions(document.id)
    states = {version.version_number: version.state for version in versions}

    assert states == {
        1: DocumentVersionState.SUPERSEDED,
        2: DocumentVersionState.PUBLISHED,
    }
    current = await repository.get_published_version(document.id)
    assert current is not None and current.version_number == 2


async def test_a_new_version_does_not_replace_the_published_one_by_itself(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    first = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await service.approve(version_id=first.version.id, actor=ACTOR)
    await service.publish(version_id=first.version.id, actor=ACTOR)

    await ingest(service, document, fx.MANUAL_V2)

    current = await repository.get_published_version(document.id)
    assert current is not None and current.version_number == 1


async def test_a_rejected_version_leaves_the_published_one_in_place(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    first = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await service.approve(version_id=first.version.id, actor=ACTOR)
    await service.publish(version_id=first.version.id, actor=ACTOR)

    second = await ingest(service, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)
    await service.reject(version_id=second.version.id, actor=ACTOR, reason="faltan planos")

    current = await repository.get_published_version(document.id)
    assert current is not None and current.version_number == 1


async def test_the_lifecycle_leaves_a_trail(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    """Quién activó qué y cuándo es parte de la trazabilidad, no un lujo."""
    first = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await service.approve(version_id=first.version.id, actor=ACTOR)
    await service.publish(version_id=first.version.id, actor=ACTOR)

    events = await repository.list_version_events(first.version.id)

    assert [event.event for event in events] == [
        VersionEvent.CREATED,
        VersionEvent.APPROVED,
        VersionEvent.PUBLISHED,
    ]
    assert all(event.actor == ACTOR for event in events)


# ---------------------------------------------------------------------
# Comparación entre versiones
# ---------------------------------------------------------------------


async def test_the_first_version_is_entirely_new(
    service: DocumentIngestionService, document: DocumentRecord
) -> None:
    result = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    counts = result.change_counts()

    assert counts["new"] == len(result.structure.chunks)
    assert counts["modified"] == 0
    assert counts["unchanged"] == 0


async def test_a_second_version_distinguishes_what_changed(
    service: DocumentIngestionService, document: DocumentRecord
) -> None:
    """Revalidar de cero lo que no cambió termina en aprobaciones en bloque;
    heredar la validación de lo que sí cambió sería mucho peor."""
    first = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await service.approve(version_id=first.version.id, actor=ACTOR)
    await service.publish(version_id=first.version.id, actor=ACTOR)

    second = await ingest(service, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)

    counts = second.change_counts()

    assert counts["unchanged"] > 0
    assert counts["new"] + counts["modified"] > 0
    # Las secciones que no se tocaron conservan su clasificación.
    unchanged = [key for key, kind in second.changes.items() if kind is ChangeKind.UNCHANGED]
    assert any(key.startswith("1.1#") for key in unchanged)


async def test_a_chunk_never_mixes_information_from_two_versions(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    first = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await service.approve(version_id=first.version.id, actor=ACTOR)
    await service.publish(version_id=first.version.id, actor=ACTOR)
    second = await ingest(service, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)

    old = await repository.list_chunks(first.version.id)
    new = await repository.list_chunks(second.version.id)

    assert {chunk.version_id for chunk in old} == {first.version.id}
    assert {chunk.version_id for chunk in new} == {second.version.id}
    # La tolerancia vieja no aparece en ningún chunk de la versión nueva.
    assert any("0,10 mm" in chunk.content for chunk in old)
    assert all("0,10 mm" not in chunk.content for chunk in new)
    assert any("0,08 mm" in chunk.content for chunk in new)


# ---------------------------------------------------------------------
# Procedencia
# ---------------------------------------------------------------------


async def test_a_chunk_can_reconstruct_its_whole_provenance(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    result = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)
    chunks = await repository.list_chunks(result.version.id)

    provenance = await repository.get_chunk_provenance(chunks[3].id)

    assert provenance is not None
    assert provenance.document.code == "manual-ejemplo"
    assert provenance.version.version_number == 1
    assert provenance.section is not None
    assert provenance.scope == Scope(domain="mantenimiento", equipment="equipo-ejemplo")
    assert len(provenance.source_sha256) == 64
    assert provenance.source_storage_key
    assert not provenance.is_published
    assert "Manual de ejemplo v1" in provenance.citation()


# ---------------------------------------------------------------------
# Autorización antes de recuperar
# ---------------------------------------------------------------------


async def test_chunks_are_only_readable_within_an_authorised_scope(
    service: DocumentIngestionService, repository: InMemoryDocumentRepository
) -> None:
    one = await repository.create_document(
        domain="mantenimiento",
        code="manual-a",
        title="Manual A",
        source_kind=DocumentSourceKind.MANUAL,
        asset_code="equipo-a",
    )
    two = await repository.create_document(
        domain="mantenimiento",
        code="manual-b",
        title="Manual B",
        source_kind=DocumentSourceKind.MANUAL,
        asset_code="equipo-b",
    )
    for document, text in ((one, fx.MANUAL_V1), (two, fx.MANUAL_V1 + "\n")):
        result = await ingest(service, document, text)
        assert isinstance(result, IngestedVersion)
        await service.approve(version_id=result.version.id, actor=ACTOR)
        await service.publish(version_id=result.version.id, actor=ACTOR)

    engineer = Principal(
        external_user_id=ACTOR,
        display_name=None,
        is_active=True,
        is_admin=False,
        scopes=(Scope(domain="mantenimiento", equipment="equipo-a"),),
    )
    documents = await repository.list_documents()
    scopes = readable_scopes(engineer, documents)

    found = await repository.list_published_chunks(scopes=scopes)

    assert scopes == (Scope(domain="mantenimiento", equipment="equipo-a"),)
    assert found
    assert {provenance.document.code for provenance in found} == {"manual-a"}


async def test_without_any_permission_nothing_is_retrieved(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    """Recuperar y luego ocultar es exactamente lo que la regla 4 prohíbe."""
    result = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)
    await service.approve(version_id=result.version.id, actor=ACTOR)
    await service.publish(version_id=result.version.id, actor=ACTOR)

    stranger = Principal(
        external_user_id="22222222-0000-4000-8000-000000000002",
        display_name=None,
        is_active=True,
        is_admin=False,
    )
    documents = await repository.list_documents()

    assert readable(stranger, documents) == ()
    assert readable_scopes(stranger, documents) == ()
    assert await repository.list_published_chunks(scopes=()) == ()


async def test_only_published_versions_are_retrievable(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    """Una versión pendiente de validación no es conocimiento todavía."""
    result = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    scopes = (Scope(domain="mantenimiento", equipment="equipo-ejemplo"),)

    assert await repository.list_published_chunks(scopes=scopes) == ()

    await service.approve(version_id=result.version.id, actor=ACTOR)
    await service.publish(version_id=result.version.id, actor=ACTOR)

    assert await repository.list_published_chunks(scopes=scopes)


async def test_a_superseded_version_stops_being_retrievable(
    service: DocumentIngestionService,
    document: DocumentRecord,
    repository: InMemoryDocumentRepository,
) -> None:
    first = await ingest(service, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await service.approve(version_id=first.version.id, actor=ACTOR)
    await service.publish(version_id=first.version.id, actor=ACTOR)
    second = await ingest(service, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)
    await service.approve(version_id=second.version.id, actor=ACTOR)
    await service.publish(version_id=second.version.id, actor=ACTOR)

    scopes = (Scope(domain="mantenimiento", equipment="equipo-ejemplo"),)
    found = await repository.list_published_chunks(scopes=scopes, limit=1000)

    assert {provenance.version.version_number for provenance in found} == {2}


async def test_a_domain_wide_document_needs_no_asset(
    repository: InMemoryDocumentRepository,
) -> None:
    """Un procedimiento general de bloqueo y etiquetado no cuelga de un equipo."""
    general = await repository.create_document(
        domain="mantenimiento",
        code="bloqueo-etiquetado",
        title="Procedimiento general",
        source_kind=DocumentSourceKind.PROCEDURE,
    )

    assert general.asset_code is None
    assert general.scope == Scope(domain="mantenimiento", equipment=None)

    engineer = Principal(
        external_user_id=ACTOR,
        display_name=None,
        is_active=True,
        is_admin=False,
        scopes=(Scope(domain="mantenimiento"),),
    )
    limited = Principal(
        external_user_id=ACTOR,
        display_name=None,
        is_active=True,
        is_admin=False,
        scopes=(Scope(domain="mantenimiento", equipment="equipo-a"),),
    )

    assert may_read(engineer, general).allowed
    # Un permiso de un solo equipo no alcanza a la documentación del dominio.
    assert not may_read(limited, general).allowed
