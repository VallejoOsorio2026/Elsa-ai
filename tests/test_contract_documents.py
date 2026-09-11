"""Contrato del repositorio documental, contra los **dos** adaptadores.

Cada prueba de este archivo corre dos veces: una contra el adaptador en
memoria y otra contra PostgreSQL real, con las migraciones del repositorio
aplicadas desde cero. Las mismas entradas tienen que producir los mismos
resultados funcionales.

Por qué el mismo archivo y no dos: un doble en memoria solo vale si se
comporta como el almacén real. Si las dos implementaciones se prueban por
separado, la que se usa en los tests acaba aceptando lo que la de producción
rechaza, y el fallo aparece en producción. Aquí no pueden divergir sin que
una de las dos ejecuciones se ponga en rojo.

Las pruebas de PostgreSQL se **omiten** si no está definida
``ELSA_TEST_DATABASE_URL``; un verde sin esa variable no prueba el esquema.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

import asyncpg
import pytest

from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.memory_documents import InMemoryDocumentRepository
from elsa.adapters.postgres_documents import PostgresDocumentRepository
from elsa.adapters.structured_text_extractor import StructuredTextExtractor
from elsa.core.authorization import Principal, Scope
from elsa.core.document_access import readable_scopes
from elsa.core.versioning import ChangeKind
from elsa.documents.model import ChunkingPolicy
from elsa.ports.documents import (
    DocumentAlreadyExistsError,
    DocumentNotFoundError,
    DocumentRecord,
    DocumentRepositoryPort,
    DocumentSourceKind,
    DocumentVersionState,
    DuplicateSourceError,
    NotPublishableError,
    VersionEvent,
    VersionNotFoundError,
)
from elsa.services.document_ingestion import (
    DocumentIngestionError,
    DocumentIngestionService,
    DuplicateDocumentSource,
    IngestedVersion,
)
from tests import db
from tests import fixtures_documents as fx

pytestmark = pytest.mark.anyio

ACTOR = "11111111-0000-4000-8000-000000000001"
OTHER_ACTOR = "22222222-0000-4000-8000-000000000002"

POLICY = ChunkingPolicy(
    name="contract", target_tokens=60, max_tokens=120, min_tokens=10, overlap_tokens=10
)


@dataclass
class Harness:
    """El repositorio bajo prueba y lo que hace falta para prepararlo.

    ``seed_asset`` existe porque un activo técnico es una fila real en
    PostgreSQL y nada en memoria. Es la única asimetría del montaje; todo lo
    que se prueba después es idéntico para los dos.
    """

    name: str
    repository: DocumentRepositoryPort
    seed_asset: Callable[[str, str], Awaitable[None]]


@pytest.fixture(params=["memory", "postgres"])
async def harness(request: pytest.FixtureRequest) -> AsyncIterator[Harness]:
    if request.param == "memory":

        async def noop(code: str, domain: str) -> None:
            """En memoria no hay catálogo de activos que sembrar."""

        yield Harness("memory", InMemoryDocumentRepository(), noop)
        return

    url = db.database_url()
    if url is None:
        pytest.skip(db.SKIP_REASON)
    await db.reset_database(url)
    connection = await asyncpg.connect(url)

    async def seed(code: str, domain: str) -> None:
        await connection.execute(
            "insert into elsa.technical_assets (code, name, domain) values ($1, $2, $3) "
            "on conflict (code) do nothing",
            code,
            f"Activo {code}",
            domain,
        )

    repository = await PostgresDocumentRepository.connect(url, min_size=1, max_size=4)
    try:
        yield Harness("postgres", repository, seed)
    finally:
        await repository.close()
        await connection.close()


def service(repository: DocumentRepositoryPort) -> DocumentIngestionService:
    return DocumentIngestionService(
        repository=repository,
        storage=InMemoryArtifactStorage(),
        extractor=StructuredTextExtractor(),
        policy=POLICY,
    )


async def make_document(
    harness: Harness, *, code: str = "manual-ejemplo", asset: str | None = "equipo-a"
) -> DocumentRecord:
    if asset is not None:
        await harness.seed_asset(asset, "mantenimiento")
    return await harness.repository.create_document(
        domain="mantenimiento",
        code=code,
        title="Manual de ejemplo",
        source_kind=DocumentSourceKind.MANUAL,
        asset_code=asset,
    )


async def ingest(
    harness: Harness, document: DocumentRecord, text: str
) -> IngestedVersion | DuplicateDocumentSource:
    return await service(harness.repository).ingest(
        document=document,
        content=fx.encoded(text),
        content_type="text/markdown",
        filename="manual.md",
        actor=ACTOR,
    )


async def publish(harness: Harness, version_id: str) -> None:
    svc = service(harness.repository)
    await svc.approve(version_id=version_id, actor=ACTOR)
    await svc.publish(version_id=version_id, actor=ACTOR)


# ---------------------------------------------------------------------
# Documentos
# ---------------------------------------------------------------------


async def test_the_adapter_satisfies_the_port(harness: Harness) -> None:
    assert isinstance(harness.repository, DocumentRepositoryPort)


async def test_a_document_can_be_created_and_read_back(harness: Harness) -> None:
    created = await make_document(harness)

    by_code = await harness.repository.get_document(domain="mantenimiento", code="manual-ejemplo")
    by_id = await harness.repository.get_document_by_id(created.id)

    assert by_code is not None and by_id is not None
    assert by_code.id == created.id == by_id.id
    assert by_code.title == "Manual de ejemplo"
    assert by_code.source_kind is DocumentSourceKind.MANUAL
    assert by_code.asset_code == "equipo-a"
    assert by_code.scope == Scope(domain="mantenimiento", equipment="equipo-a")


async def test_a_document_code_is_unique_within_its_domain(harness: Harness) -> None:
    await make_document(harness, code="repetido")

    with pytest.raises(DocumentAlreadyExistsError):
        await make_document(harness, code="repetido")


async def test_a_document_may_apply_to_a_whole_domain(harness: Harness) -> None:
    document = await make_document(harness, code="bloqueo-general", asset=None)

    assert document.asset_code is None
    assert document.scope == Scope(domain="mantenimiento", equipment=None)


async def test_documents_are_listed_in_a_stable_order(harness: Harness) -> None:
    await make_document(harness, code="zeta")
    await make_document(harness, code="alfa", asset=None)

    listed = await harness.repository.list_documents()

    assert [document.code for document in listed] == ["alfa", "zeta"]


async def test_documents_can_be_filtered_by_asset(harness: Harness) -> None:
    await make_document(harness, code="del-equipo-a", asset="equipo-a")
    await make_document(harness, code="del-equipo-b", asset="equipo-b")

    listed = await harness.repository.list_documents(asset_code="equipo-b")

    assert [document.code for document in listed] == ["del-equipo-b"]


async def test_an_unknown_document_is_none_not_an_error(harness: Harness) -> None:
    assert await harness.repository.get_document(domain="mantenimiento", code="no-existe") is None


# ---------------------------------------------------------------------
# Corridas de ingesta
# ---------------------------------------------------------------------


async def test_an_ingestion_run_is_opened_and_completed(harness: Harness) -> None:
    document = await make_document(harness)

    result = await ingest(harness, document, fx.MANUAL_V1)

    assert isinstance(result, IngestedVersion)
    run = await harness.repository.get_ingestion_run(result.run.id)
    assert run is not None
    assert run.status.value == "completed"
    assert run.finished_at is not None
    assert run.stats["chunks"] == len(result.structure.chunks)


async def test_a_run_cannot_be_opened_for_an_unknown_document(harness: Harness) -> None:
    with pytest.raises(DocumentNotFoundError):
        await harness.repository.start_ingestion_run(
            document_id="00000000-0000-4000-8000-0000000000ff",
            sha256="a" * 64,
            byte_size=10,
            storage_key="k/1",
            uploaded_by=ACTOR,
        )


async def test_the_same_file_cannot_open_two_runs(harness: Harness) -> None:
    """La idempotencia es del contenido, no de quién lo sube."""
    document = await make_document(harness)
    await harness.repository.start_ingestion_run(
        document_id=document.id,
        sha256="b" * 64,
        byte_size=10,
        storage_key="k/b",
        uploaded_by=ACTOR,
        content_type="text/markdown",
    )

    with pytest.raises(DuplicateSourceError):
        await harness.repository.start_ingestion_run(
            document_id=document.id,
            sha256="b" * 64,
            byte_size=10,
            storage_key="k/b2",
            uploaded_by=OTHER_ACTOR,
            content_type="text/markdown",
        )


async def test_a_failed_run_records_why(harness: Harness) -> None:
    document = await make_document(harness)
    run = await harness.repository.start_ingestion_run(
        document_id=document.id,
        sha256="c" * 64,
        byte_size=10,
        storage_key="k/c",
        uploaded_by=ACTOR,
    )

    failed = await harness.repository.fail_ingestion_run(
        run_id=run.id, failure_kind="parse", failure_message="ilegible", stats={"errores": 1}
    )

    assert failed.status.value == "failed"
    assert failed.failure_kind == "parse"
    assert failed.finished_at is not None
    assert (await harness.repository.list_ingestion_runs(document.id))[0].id == run.id


async def test_runs_are_listed_newest_first(harness: Harness) -> None:
    document = await make_document(harness)
    for index in range(3):
        await harness.repository.start_ingestion_run(
            document_id=document.id,
            sha256=f"{index}" * 64,
            byte_size=10,
            storage_key=f"k/{index}",
            uploaded_by=ACTOR,
        )

    runs = await harness.repository.list_ingestion_runs(document.id)

    assert len(runs) == 3
    assert [run.started_at for run in runs] == sorted(
        (run.started_at for run in runs), reverse=True
    )


# ---------------------------------------------------------------------
# Versiones, secciones y chunks
# ---------------------------------------------------------------------


async def test_a_version_arrives_pending_validation_with_all_its_parts(
    harness: Harness,
) -> None:
    document = await make_document(harness)

    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    stored = await harness.repository.get_version(result.version.id)
    sections = await harness.repository.list_sections(result.version.id)
    chunks = await harness.repository.list_chunks(result.version.id)

    assert stored is not None
    assert stored.state is DocumentVersionState.PENDING_VALIDATION
    assert stored.version_number == 1
    assert stored.published_at is None
    assert stored.section_count == len(sections) == len(result.structure.sections)
    assert stored.chunk_count == len(chunks) == len(result.structure.chunks)


async def test_the_version_records_what_produced_it(harness: Harness) -> None:
    document = await make_document(harness)
    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    stored = await harness.repository.get_version(result.version.id)

    assert stored is not None
    assert stored.extractor == "structured_text"
    assert stored.extractor_version == "1"
    assert stored.chunking_profile == "contract"
    assert stored.chunking_parameters["target_tokens"] == 60
    assert stored.structure_sha256 == result.structure.structure_sha256
    assert len(stored.content_sha256) == 64


async def test_sections_keep_their_tree_and_their_order(harness: Harness) -> None:
    document = await make_document(harness)
    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    sections = await harness.repository.list_sections(result.version.id)

    assert [section.ordinal for section in sections] == list(range(len(sections)))
    by_path = {section.path: section for section in sections}
    assert by_path["1.3.2"].title == "Inspeccion"
    assert by_path["1.3.2"].number_label == "3.2"
    assert by_path["1.3.2"].parent_path == "1.3"
    assert by_path["1.3.2"].depth == 3
    # El padre se enlaza por identificador, no solo por ruta.
    assert by_path["1.3.2"].parent_id == by_path["1.3"].id


async def test_chunks_keep_their_order_hashes_and_metadata(harness: Harness) -> None:
    document = await make_document(harness)
    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    chunks = await harness.repository.list_chunks(result.version.id)

    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert [chunk.structural_key for chunk in chunks] == [
        chunk.structural_key for chunk in result.structure.chunks
    ]
    assert [chunk.content_sha256 for chunk in chunks] == [
        chunk.content_sha256 for chunk in result.structure.chunks
    ]
    for stored, produced in zip(chunks, result.structure.chunks, strict=True):
        assert stored.content == produced.content
        assert stored.kind is produced.kind
        assert stored.heading_trail == produced.heading_trail
        assert (stored.page_start, stored.page_end) == (produced.page_start, produced.page_end)
        assert (stored.char_start, stored.char_end) == (produced.char_start, produced.char_end)
        assert stored.token_estimate == produced.token_estimate
        assert stored.overlap_chars == produced.overlap_chars
        assert stored.boundary_reason == produced.boundary_reason
        assert stored.oversized == produced.oversized
        assert stored.warnings == produced.warnings


async def test_chunking_stays_deterministic_through_persistence(harness: Harness) -> None:
    """Persistir y releer no puede cambiar un solo hash."""
    one = await make_document(harness, code="uno", asset="equipo-a")
    two = await make_document(harness, code="dos", asset="equipo-b")

    first = await ingest(harness, one, fx.MANUAL_V1)
    second = await ingest(harness, two, fx.MANUAL_V1 + "\n")
    assert isinstance(first, IngestedVersion) and isinstance(second, IngestedVersion)

    stored_first = await harness.repository.list_chunks(first.version.id)
    stored_second = await harness.repository.list_chunks(second.version.id)

    assert [chunk.content_sha256 for chunk in stored_first] == [
        chunk.content_sha256 for chunk in stored_second
    ]
    versions = (
        await harness.repository.get_version(first.version.id),
        await harness.repository.get_version(second.version.id),
    )
    assert versions[0] is not None and versions[1] is not None
    assert versions[0].structure_sha256 == versions[1].structure_sha256


async def test_a_failed_ingestion_stores_no_version(harness: Harness) -> None:
    document = await make_document(harness)

    with pytest.raises(DocumentIngestionError) as error:
        await service(harness.repository).ingest(
            document=document,
            content=fx.encoded(fx.EMPTY_DOCUMENT),
            content_type="text/markdown",
            filename="vacio.md",
            actor=ACTOR,
        )

    assert error.value.failure_kind == "parse"
    assert await harness.repository.list_versions(document.id) == ()
    run = await harness.repository.get_ingestion_run(error.value.run_id or "")
    assert run is not None and run.status.value == "failed"


# ---------------------------------------------------------------------
# Ciclo de vida
# ---------------------------------------------------------------------


async def test_a_version_cannot_be_published_without_approval(harness: Harness) -> None:
    document = await make_document(harness)
    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    with pytest.raises(NotPublishableError):
        await harness.repository.publish_version(version_id=result.version.id, actor=ACTOR)


async def test_publishing_supersedes_the_previous_version(harness: Harness) -> None:
    document = await make_document(harness)
    first = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await publish(harness, first.version.id)
    second = await ingest(harness, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)
    await publish(harness, second.version.id)

    versions = await harness.repository.list_versions(document.id)
    states = {version.version_number: version.state for version in versions}
    current = await harness.repository.get_published_version(document.id)

    assert states == {
        1: DocumentVersionState.SUPERSEDED,
        2: DocumentVersionState.PUBLISHED,
    }
    assert current is not None and current.version_number == 2
    assert current.published_by == ACTOR
    assert current.published_at is not None


async def test_a_new_version_does_not_replace_the_published_one(harness: Harness) -> None:
    document = await make_document(harness)
    first = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await publish(harness, first.version.id)

    await ingest(harness, document, fx.MANUAL_V2)

    current = await harness.repository.get_published_version(document.id)
    assert current is not None and current.version_number == 1


async def test_only_one_version_is_published_at_a_time(harness: Harness) -> None:
    document = await make_document(harness)
    for text in (fx.MANUAL_V1, fx.MANUAL_V2, fx.MANUAL_V1 + "\n\n"):
        result = await ingest(harness, document, text)
        assert isinstance(result, IngestedVersion)
        await publish(harness, result.version.id)

    versions = await harness.repository.list_versions(document.id)
    published = [v for v in versions if v.state is DocumentVersionState.PUBLISHED]

    assert len(versions) == 3
    assert len(published) == 1
    assert published[0].version_number == 3


async def test_a_published_version_cannot_change_state_directly(harness: Harness) -> None:
    document = await make_document(harness)
    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)
    await publish(harness, result.version.id)

    with pytest.raises(NotPublishableError):
        await harness.repository.set_version_state(
            version_id=result.version.id,
            state=DocumentVersionState.REJECTED,
            actor=ACTOR,
            reason="ya no vale",
        )


async def test_rejecting_requires_a_reason(harness: Harness) -> None:
    """Una decisión que cierra el trabajo de alguien tiene que decir por qué."""
    document = await make_document(harness)
    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    with pytest.raises(ValueError):
        await harness.repository.set_version_state(
            version_id=result.version.id,
            state=DocumentVersionState.REJECTED,
            actor=ACTOR,
            reason="   ",
        )


async def test_a_rejected_version_leaves_the_published_one_alone(harness: Harness) -> None:
    document = await make_document(harness)
    first = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await publish(harness, first.version.id)
    second = await ingest(harness, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)

    await harness.repository.set_version_state(
        version_id=second.version.id,
        state=DocumentVersionState.REJECTED,
        actor=ACTOR,
        reason="faltan planos",
    )

    current = await harness.repository.get_published_version(document.id)
    assert current is not None and current.version_number == 1


async def test_the_lifecycle_leaves_a_trail(harness: Harness) -> None:
    document = await make_document(harness)
    first = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await publish(harness, first.version.id)
    second = await ingest(harness, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)
    await publish(harness, second.version.id)

    trail_one = await harness.repository.list_version_events(first.version.id)
    trail_two = await harness.repository.list_version_events(second.version.id)

    assert [event.event for event in trail_one] == [
        VersionEvent.CREATED,
        VersionEvent.APPROVED,
        VersionEvent.PUBLISHED,
        VersionEvent.SUPERSEDED,
    ]
    assert [event.event for event in trail_two] == [
        VersionEvent.CREATED,
        VersionEvent.APPROVED,
        VersionEvent.PUBLISHED,
    ]
    assert all(event.actor == ACTOR for event in trail_one)
    assert [event.seq for event in trail_one] == sorted(event.seq for event in trail_one)


async def test_an_unknown_version_is_reported_as_missing(harness: Harness) -> None:
    missing = "00000000-0000-4000-8000-0000000000aa"

    assert await harness.repository.get_version(missing) is None
    with pytest.raises(VersionNotFoundError):
        await harness.repository.publish_version(version_id=missing, actor=ACTOR)


# ---------------------------------------------------------------------
# Comparación entre versiones
# ---------------------------------------------------------------------


async def test_the_first_version_is_entirely_new(harness: Harness) -> None:
    document = await make_document(harness)
    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    chunks = await harness.repository.list_chunks(result.version.id)

    assert result.change_counts()["new"] == len(chunks)
    assert all(chunk.change_kind is ChangeKind.NEW for chunk in chunks)


async def test_a_second_version_distinguishes_what_changed(harness: Harness) -> None:
    document = await make_document(harness)
    first = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await publish(harness, first.version.id)

    second = await ingest(harness, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)

    chunks = await harness.repository.list_chunks(second.version.id)
    kinds = [chunk.change_kind for chunk in chunks]

    assert second.change_counts()["unchanged"] > 0
    assert second.change_counts()["modified"] > 0
    assert kinds.count(ChangeKind.UNCHANGED) == second.change_counts()["unchanged"]
    assert kinds.count(ChangeKind.MODIFIED) == second.change_counts()["modified"]


async def test_a_chunk_never_mixes_two_versions(harness: Harness) -> None:
    document = await make_document(harness)
    first = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await publish(harness, first.version.id)
    second = await ingest(harness, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)

    old = await harness.repository.list_chunks(first.version.id)
    new = await harness.repository.list_chunks(second.version.id)

    assert {chunk.version_id for chunk in old} == {first.version.id}
    assert {chunk.version_id for chunk in new} == {second.version.id}
    assert any("0,10 mm" in chunk.content for chunk in old)
    assert all("0,10 mm" not in chunk.content for chunk in new)


async def test_re_ingesting_the_same_file_creates_no_version(harness: Harness) -> None:
    document = await make_document(harness)
    first = await ingest(harness, document, fx.MANUAL_V1)
    second = await ingest(harness, document, fx.MANUAL_V1)

    assert isinstance(first, IngestedVersion)
    assert isinstance(second, DuplicateDocumentSource)
    assert second.existing_run_id == first.run.id
    assert len(await harness.repository.list_versions(document.id)) == 1


# ---------------------------------------------------------------------
# Procedencia
# ---------------------------------------------------------------------


async def test_a_chunk_reconstructs_its_whole_provenance(harness: Harness) -> None:
    document = await make_document(harness)
    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)
    await publish(harness, result.version.id)
    chunks = await harness.repository.list_chunks(result.version.id)

    provenance = await harness.repository.get_chunk_provenance(chunks[2].id)

    assert provenance is not None
    assert provenance.document.code == "manual-ejemplo"
    assert provenance.version.version_number == 1
    assert provenance.version.state is DocumentVersionState.PUBLISHED
    assert provenance.is_published
    assert provenance.section is not None
    assert provenance.section.path == chunks[2].section_path
    assert provenance.scope == Scope(domain="mantenimiento", equipment="equipo-a")
    assert len(provenance.source_sha256) == 64
    assert provenance.source_storage_key
    assert "Manual de ejemplo v1" in provenance.citation()


async def test_every_chunk_can_reach_its_source(harness: Harness) -> None:
    document = await make_document(harness)
    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)

    for chunk in await harness.repository.list_chunks(result.version.id):
        provenance = await harness.repository.get_chunk_provenance(chunk.id)
        assert provenance is not None
        assert provenance.section is not None
        assert provenance.chunk.page_start is not None
        assert provenance.chunk.char_start is not None


async def test_an_unknown_chunk_has_no_provenance(harness: Harness) -> None:
    assert (
        await harness.repository.get_chunk_provenance("00000000-0000-4000-8000-0000000000bb")
        is None
    )


# ---------------------------------------------------------------------
# Autorización y aislamiento
# ---------------------------------------------------------------------


async def engineer(*scopes: Scope) -> Principal:
    return Principal(
        external_user_id=ACTOR,
        display_name=None,
        is_active=True,
        is_admin=False,
        scopes=scopes,
    )


async def two_published_documents(harness: Harness) -> None:
    for code, asset, text in (
        ("manual-a", "equipo-a", fx.MANUAL_V1),
        ("manual-b", "equipo-b", fx.MANUAL_V1 + "\n"),
    ):
        document = await make_document(harness, code=code, asset=asset)
        result = await ingest(harness, document, text)
        assert isinstance(result, IngestedVersion)
        await publish(harness, result.version.id)


async def test_chunks_are_only_readable_within_an_authorised_scope(
    harness: Harness,
) -> None:
    await two_published_documents(harness)
    principal = await engineer(Scope(domain="mantenimiento", equipment="equipo-a"))
    documents = await harness.repository.list_documents()

    scopes = readable_scopes(principal, documents)
    found = await harness.repository.list_published_chunks(scopes=scopes, limit=500)

    assert scopes == (Scope(domain="mantenimiento", equipment="equipo-a"),)
    assert found
    assert {provenance.document.code for provenance in found} == {"manual-a"}


async def test_a_domain_wide_scope_covers_every_asset(harness: Harness) -> None:
    """Un permiso de dominio cubre el dominio y cualquiera de sus equipos."""
    await two_published_documents(harness)

    found = await harness.repository.list_published_chunks(
        scopes=[Scope(domain="mantenimiento")], limit=500
    )

    assert {provenance.document.code for provenance in found} == {"manual-a", "manual-b"}


async def test_without_any_permission_nothing_is_retrieved(harness: Harness) -> None:
    await two_published_documents(harness)

    assert await harness.repository.list_published_chunks(scopes=()) == ()


async def test_a_scope_from_another_domain_retrieves_nothing(harness: Harness) -> None:
    await two_published_documents(harness)

    found = await harness.repository.list_published_chunks(
        scopes=[Scope(domain="materiales")], limit=500
    )

    assert found == ()


async def test_only_published_versions_are_retrievable(harness: Harness) -> None:
    document = await make_document(harness)
    result = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(result, IngestedVersion)
    scopes = [Scope(domain="mantenimiento", equipment="equipo-a")]

    assert await harness.repository.list_published_chunks(scopes=scopes) == ()

    await publish(harness, result.version.id)

    assert await harness.repository.list_published_chunks(scopes=scopes, limit=500)


async def test_a_superseded_version_stops_being_retrievable(harness: Harness) -> None:
    document = await make_document(harness)
    first = await ingest(harness, document, fx.MANUAL_V1)
    assert isinstance(first, IngestedVersion)
    await publish(harness, first.version.id)
    second = await ingest(harness, document, fx.MANUAL_V2)
    assert isinstance(second, IngestedVersion)
    await publish(harness, second.version.id)

    found = await harness.repository.list_published_chunks(
        scopes=[Scope(domain="mantenimiento", equipment="equipo-a")], limit=500
    )

    assert {provenance.version.version_number for provenance in found} == {2}


async def test_the_retrieval_order_is_the_same_in_both_stores(harness: Harness) -> None:
    """`limit` tiene que recortar lo mismo en los dos almacenes."""
    await two_published_documents(harness)

    found = await harness.repository.list_published_chunks(
        scopes=[Scope(domain="mantenimiento")], limit=500
    )
    limited = await harness.repository.list_published_chunks(
        scopes=[Scope(domain="mantenimiento")], limit=3
    )

    keys = [(p.document.code, p.version.version_number, p.chunk.ordinal) for p in found]
    assert keys == sorted(keys)
    assert [p.chunk.id for p in limited] == [p.chunk.id for p in found[:3]]


async def test_the_store_reports_that_it_is_reachable(harness: Harness) -> None:
    await harness.repository.check_health()
