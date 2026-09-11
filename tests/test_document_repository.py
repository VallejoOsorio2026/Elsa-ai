"""Contrato compartido: cada caso se ejecuta en memoria y PostgreSQL real."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import asdict, replace
from typing import Any
from uuid import uuid4

import asyncpg
import pytest

from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.memory_documents import InMemoryDocumentRepository
from elsa.adapters.postgres_documents import PostgresDocumentRepository
from elsa.adapters.structured_text_extractor import StructuredTextExtractor
from elsa.core.authorization import Scope
from elsa.core.versioning import ChangeKind
from elsa.documents.chunking import chunk_document
from elsa.ports.artifact_storage import sha256_hex
from elsa.ports.documents import (
    DocumentAlreadyExistsError,
    DocumentIntegrityError,
    DocumentNotFoundError,
    DocumentRecord,
    DocumentRepositoryPort,
    DocumentSourceKind,
    DocumentVersionInput,
    DocumentVersionState,
    DuplicateSourceError,
    IngestionRunStatus,
    NotPublishableError,
    VersionConflictError,
    VersionEvent,
    VersionNotFoundError,
)
from elsa.services.document_ingestion import (
    DocumentIngestionService,
    DuplicateDocumentSource,
    IngestedVersion,
)
from tests import db
from tests import fixtures_documents as fx

pytestmark = pytest.mark.anyio
ACTOR = "aaaaaaaa-0000-4000-8000-000000000001"
OTHER = "bbbbbbbb-0000-4000-8000-000000000002"


@pytest.fixture(params=["memory", "postgres"])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[DocumentRepositoryPort]:
    if request.param == "memory":
        yield InMemoryDocumentRepository()
        return
    url = db.database_url()
    if url is None:
        pytest.skip(db.SKIP_REASON)
    await db.reset_database(url)
    conn = await asyncpg.connect(url)
    try:
        assert 160000 <= int(await conn.fetchval("show server_version_num")) < 170000
        await conn.execute(
            "insert into elsa.knowledge_domains (code,label) values ('laboratorio','Laboratorio')"
        )
        await conn.execute(
            "insert into elsa.technical_assets (code,name,domain) values "
            "('asset-a','A','mantenimiento'),('asset-b','B','mantenimiento'),"
            "('asset-c','C','laboratorio')"
        )
    finally:
        await conn.close()
    repo = await PostgresDocumentRepository.connect(url, min_size=2, max_size=6)
    try:
        yield repo
    finally:
        await repo.close()


async def document(
    repo: DocumentRepositoryPort,
    code: str = "manual-a",
    *,
    domain: str = "mantenimiento",
    asset: str | None = "asset-a",
) -> DocumentRecord:
    return await repo.create_document(
        domain=domain,
        code=code,
        title=code,
        source_kind=DocumentSourceKind.MANUAL,
        asset_code=asset,
        language="es",
        description="Sintético",
    )


def service(repo: DocumentRepositoryPort) -> DocumentIngestionService:
    return DocumentIngestionService(
        repository=repo, storage=InMemoryArtifactStorage(), extractor=StructuredTextExtractor()
    )


async def version_input(
    repo: DocumentRepositoryPort, doc: DocumentRecord, text: str = fx.MANUAL_V1
) -> DocumentVersionInput:
    content = text.encode()
    digest = sha256_hex(content)
    extracted = await StructuredTextExtractor().extract(
        content, content_type="text/markdown", filename="test.md"
    )
    structure = chunk_document(extracted, document_title=doc.title)
    run = await repo.start_ingestion_run(
        document_id=doc.id,
        sha256=digest,
        byte_size=len(content),
        storage_key=f"document_source/{digest}",
        uploaded_by=ACTOR,
        original_filename="test.md",
        content_type="text/markdown",
        request_id="start",
    )
    return DocumentVersionInput(
        document_id=doc.id,
        run_id=run.id,
        source_artifact_id=run.source_artifact_id,
        content_sha256=digest,
        structure=structure,
        extractor=extracted.extractor,
        extractor_version=extracted.extractor_version,
        changes={c.structural_key: ChangeKind.NEW for c in structure.chunks},
        stats={"chunks": len(structure.chunks), "warnings": {"example": 1}},
    )


async def test_documents_and_absent_records(repository: DocumentRepositoryPort) -> None:
    doc = await document(repository)
    assert isinstance(repository, DocumentRepositoryPort)
    assert await repository.get_document(domain=doc.domain, code=doc.code) == doc
    assert await repository.get_document_by_id(doc.id) == doc
    assert doc.asset_id and doc.created_at and doc.is_active
    with pytest.raises(DocumentAlreadyExistsError):
        await document(repository)
    missing = str(uuid4())
    assert await repository.get_document(domain=doc.domain, code="missing") is None
    assert await repository.get_document_by_id(missing) is None
    assert await repository.get_ingestion_run(missing) is None
    assert await repository.get_version(missing) is None
    assert await repository.get_chunk_provenance(missing) is None
    assert await repository.get_published_version(doc.id) is None
    assert await repository.list_documents(domain=doc.domain, asset_code="asset-b") == ()
    assert await repository.list_versions(missing) == ()
    assert await repository.list_chunks(missing) == ()
    assert await repository.list_sections(missing) == ()
    assert await repository.list_version_events(missing) == ()
    with pytest.raises(VersionNotFoundError):
        await repository.publish_version(version_id=missing, actor=ACTOR)
    with pytest.raises(DocumentNotFoundError):
        await repository.start_ingestion_run(
            document_id=missing,
            sha256="a" * 64,
            byte_size=10,
            storage_key="missing",
            uploaded_by=ACTOR,
        )
    await repository.check_health()


async def test_runs_timestamps_failure_and_duplicate_source(
    repository: DocumentRepositoryPort,
) -> None:
    doc = await document(repository)
    data = await version_input(repository, doc)
    run = await repository.get_ingestion_run(data.run_id)
    assert run is not None
    assert run.status is IngestionRunStatus.RECEIVED and run.finished_at is None
    assert run.started_by == ACTOR and run.request_id == "start"
    assert run.started_at.tzinfo is not None
    assert await repository.find_run_by_source(data.content_sha256) == run
    failed = await repository.fail_ingestion_run(
        run_id=run.id,
        failure_kind="parse",
        failure_message="synthetic failure",
        stats={"errors": 1},
    )
    assert failed.status is IngestionRunStatus.FAILED
    assert failed.finished_at and failed.finished_at >= run.started_at
    assert failed.started_at == run.started_at and failed.failure_kind == "parse"
    assert failed.failure_message == "synthetic failure" and failed.stats == {"errors": 1}
    assert await repository.get_ingestion_run(run.id) == failed
    assert await repository.list_ingestion_runs(doc.id) == (failed,)
    with pytest.raises(DuplicateSourceError) as error:
        await repository.start_ingestion_run(
            document_id=doc.id,
            sha256=data.content_sha256,
            byte_size=10,
            storage_key="different",
            uploaded_by=ACTOR,
            content_type="text/plain",
        )
    assert error.value.existing_import_id == run.id
    assert len(await repository.list_ingestion_runs(doc.id)) == 1


async def test_retry_is_identical_even_after_publication(
    repository: DocumentRepositoryPort,
) -> None:
    doc = await document(repository)
    data = await version_input(repository, doc)
    first = await repository.store_version(data, actor=ACTOR, request_id="create")
    saved_run = await repository.get_ingestion_run(data.run_id)
    events = await repository.list_version_events(first.id)
    assert await repository.store_version(data, actor=ACTOR, request_id="create") == first
    assert await repository.get_ingestion_run(data.run_id) == saved_run
    assert await repository.list_version_events(first.id) == events
    await service(repository).approve(version_id=first.id, actor=ACTOR)
    published = await service(repository).publish(version_id=first.id, actor=ACTOR)
    events = await repository.list_version_events(first.id)
    assert await repository.store_version(data, actor=ACTOR, request_id="create") == published
    assert await repository.list_version_events(first.id) == events
    assert await repository.list_versions(doc.id) == (published,)
    assert saved_run and saved_run.status is IngestionRunStatus.COMPLETED
    assert saved_run.finished_at and saved_run.finished_at >= saved_run.started_at


@pytest.mark.parametrize(
    "field",
    [
        "hash",
        "source",
        "document",
        "extractor",
        "policy",
        "stats",
        "chunk_text",
        "page",
        "changes",
        "actor",
        "request_id",
    ],
)
async def test_conflicting_retry_has_no_writes(
    repository: DocumentRepositoryPort, field: str
) -> None:
    doc = await document(repository)
    data = await version_input(repository, doc)
    original = await repository.store_version(data, actor=ACTOR, request_id="create")
    before = (
        await repository.get_ingestion_run(data.run_id),
        await repository.list_chunks(original.id),
        await repository.list_sections(original.id),
        await repository.list_version_events(original.id),
    )
    changed = data
    actor, request_id = ACTOR, "create"
    if field == "hash":
        changed = replace(data, content_sha256="f" * 64)
    elif field == "source":
        changed = replace(data, source_artifact_id=str(uuid4()))
    elif field == "document":
        other = await document(repository, "other")
        changed = replace(data, document_id=other.id)
    elif field == "extractor":
        changed = replace(data, extractor_version="other")
    elif field == "policy":
        changed = replace(
            data,
            structure=replace(data.structure, policy=replace(data.structure.policy, name="other")),
        )
    elif field == "stats":
        changed = replace(data, stats={"chunks": 99})
    elif field in {"chunk_text", "page"}:
        chunk = data.structure.chunks[0]
        chunk = replace(
            chunk, **({"content": "different"} if field == "chunk_text" else {"page_end": 900})
        )
        changed = replace(
            data, structure=replace(data.structure, chunks=(chunk, *data.structure.chunks[1:]))
        )
    elif field == "changes":
        changed = replace(data, changes={})
    elif field == "actor":
        actor = OTHER
    else:
        request_id = "other"
    with pytest.raises(VersionConflictError):
        await repository.store_version(changed, actor=actor, request_id=request_id)
    assert await repository.list_versions(doc.id) == (original,)
    assert before == (
        await repository.get_ingestion_run(data.run_id),
        await repository.list_chunks(original.id),
        await repository.list_sections(original.id),
        await repository.list_version_events(original.id),
    )


@pytest.mark.parametrize("reason", ["", " ", "\t\r\n", "\u00a0"])
async def test_blank_rejection_fails_before_persistence(
    repository: DocumentRepositoryPort, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = await document(repository)
    data = await version_input(repository, doc)
    version = await repository.store_version(data, actor=ACTOR)
    events = await repository.list_version_events(version.id)
    with pytest.raises(NotPublishableError):
        await repository.set_version_state(
            version_id=version.id, state=DocumentVersionState.REJECTED, actor=ACTOR, reason=reason
        )

    async def never_persist(**kwargs: Any) -> Any:
        pytest.fail("service called persistence with a blank rejection")

    monkeypatch.setattr(repository, "set_version_state", never_persist)
    with pytest.raises(NotPublishableError):
        await service(repository).reject(version_id=version.id, actor=ACTOR, reason=reason)
    assert await repository.get_version(version.id) == version
    assert await repository.list_version_events(version.id) == events


@pytest.mark.parametrize("context", ["same", "asset", "domain"])
@pytest.mark.parametrize("mix", ["run", "source", "hash"])
async def test_provenance_mismatch_rolls_back(
    repository: DocumentRepositoryPort, context: str, mix: str
) -> None:
    a = await document(repository)
    b = await document(
        repository,
        "manual-b",
        domain="laboratorio" if context == "domain" else "mantenimiento",
        asset={"same": "asset-a", "asset": "asset-b", "domain": "asset-c"}[context],
    )
    da = await version_input(repository, a)
    db_input = await version_input(repository, b, fx.MANUAL_V2)
    if mix == "run":
        invalid = replace(da, document_id=b.id)
    elif mix == "source":
        invalid = replace(
            db_input, source_artifact_id=da.source_artifact_id, content_sha256=da.content_sha256
        )
    else:
        invalid = replace(db_input, content_sha256=da.content_sha256)
    before = await repository.get_ingestion_run(invalid.run_id)
    with pytest.raises(DocumentIntegrityError):
        await repository.store_version(invalid, actor=ACTOR)
    assert await repository.list_versions(a.id) == await repository.list_versions(b.id) == ()
    assert await repository.get_ingestion_run(invalid.run_id) == before
    good = await repository.store_version(db_input, actor=ACTOR)
    assert good.version_number == 1


async def test_lifecycle_history_provenance_and_scope_isolation(
    repository: DocumentRepositoryPort,
) -> None:
    docs = [
        await document(repository),
        await document(repository, "b", asset="asset-b"),
        await document(repository, "c", domain="laboratorio", asset="asset-c"),
        await document(repository, "general", asset=None),
    ]
    svc = service(repository)
    first_data = await version_input(repository, docs[0])
    first = await repository.store_version(first_data, actor=ACTOR, request_id="create")
    with pytest.raises(NotPublishableError):
        await svc.publish(version_id=first.id, actor=ACTOR)
    for i, doc in enumerate(docs):
        version = (
            first
            if i == 0
            else await repository.store_version(
                await version_input(repository, doc, fx.MANUAL_V1 + f"\nSynthetic {i}"), actor=ACTOR
            )
        )
        await svc.approve(
            version_id=version.id, actor=ACTOR, comment="checked", request_id="approve"
        )
        await svc.publish(version_id=version.id, actor=ACTOR, request_id="publish")
    chunks = await repository.list_chunks(first.id)
    sections = await repository.list_sections(first.id)
    assert len(chunks) == first.chunk_count and len(sections) == first.section_count
    assert [s.ordinal for s in sections] == list(range(len(sections)))
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    by_id = {s.id: s for s in sections}
    for source, section in zip(first_data.structure.sections, sections, strict=True):
        for name in (
            "path",
            "parent_path",
            "depth",
            "title",
            "number_label",
            "page_start",
            "page_end",
            "char_start",
            "char_end",
            "is_preamble",
        ):
            assert getattr(source, name) == getattr(section, name)
        assert section.version_id == first.id
        if section.parent_id:
            assert by_id[section.parent_id].path == section.parent_path
    for source_chunk, chunk in zip(first_data.structure.chunks, chunks, strict=True):
        for name, value in asdict(chunk).items():
            if name not in {"id", "version_id", "section_id", "change_kind"}:
                assert value == getattr(source_chunk, name)
        assert chunk.change_kind is ChangeKind.NEW
        provenance = await repository.get_chunk_provenance(chunk.id)
        assert provenance and provenance.is_published and provenance.document == docs[0]
        assert chunk.section_id is not None
        assert provenance.chunk == chunk and provenance.section == by_id[chunk.section_id]
        assert provenance.source_sha256 == first_data.content_sha256
        assert provenance.source_storage_key == f"document_source/{first_data.content_sha256}"
        assert provenance.version.run_id == first_data.run_id and provenance.citation()
    assert await repository.list_published_chunks(scopes=[]) == ()
    assert await repository.list_published_chunks(scopes=[Scope("mantenimiento", "missing")]) == ()
    assert await repository.list_published_chunks(scopes=[docs[0].scope], limit=0) == ()
    allowed = await repository.list_published_chunks(scopes=[docs[0].scope, docs[0].scope])
    assert {p.chunk.id for p in allowed} == {c.id for c in chunks}
    assert len(allowed) == len(chunks)
    assert {
        p.document.id for p in await repository.list_published_chunks(scopes=[docs[3].scope])
    } == {docs[3].id}
    second_data = await version_input(repository, docs[0], fx.MANUAL_V2)
    second = await repository.store_version(second_data, actor=ACTOR)
    still_published = await repository.get_published_version(docs[0].id)
    assert still_published is not None and still_published.id == first.id
    assert {
        p.version.id for p in await repository.list_published_chunks(scopes=[docs[0].scope])
    } == {first.id}
    await svc.reject(version_id=second.id, actor=ACTOR, reason="needs review", request_id="reject")
    await svc.approve(version_id=second.id, actor=OTHER)
    published = await svc.publish(version_id=second.id, actor=OTHER)
    assert await repository.get_published_version(docs[0].id) == published
    historical = await repository.get_chunk_provenance(chunks[0].id)
    assert historical and historical.version.state is DocumentVersionState.SUPERSEDED
    assert historical.version.published_by == ACTOR and historical.version.superseded_at
    assert {
        p.version.id for p in await repository.list_published_chunks(scopes=[docs[0].scope])
    } == {second.id}
    assert all(c.version_id == second.id for c in await repository.list_chunks(second.id))
    events = await repository.list_version_events(first.id)
    assert [e.event for e in events] == [
        VersionEvent.CREATED,
        VersionEvent.APPROVED,
        VersionEvent.PUBLISHED,
        VersionEvent.SUPERSEDED,
    ]
    assert [e.seq for e in events] == sorted(e.seq for e in events)
    assert events == await repository.list_version_events(first.id)
    assert all(e.occurred_at.tzinfo is not None for e in events)
    assert [e.event for e in await repository.list_version_events(second.id)] == [
        VersionEvent.CREATED,
        VersionEvent.REJECTED,
        VersionEvent.APPROVED,
        VersionEvent.PUBLISHED,
    ]


async def test_concurrent_identical_store_and_source(repository: DocumentRepositoryPort) -> None:
    doc = await document(repository)
    data = await version_input(repository, doc)
    versions = await asyncio.gather(
        *(repository.store_version(data, actor=ACTOR) for _ in range(4))
    )
    assert len({v.id for v in versions}) == 1
    assert len(await repository.list_version_events(versions[0].id)) == 1
    results = await asyncio.gather(
        *(
            repository.start_ingestion_run(
                document_id=doc.id,
                sha256="f" * 64,
                byte_size=10,
                storage_key="concurrent",
                uploaded_by=ACTOR,
            )
            for _ in range(4)
        ),
        return_exceptions=True,
    )
    assert sum(isinstance(r, DuplicateSourceError) for r in results) == 3
    assert len(await repository.list_ingestion_runs(doc.id)) == 2


async def test_ingestion_service_deduplicates_and_compares(
    repository: DocumentRepositoryPort,
) -> None:
    doc = await document(repository)
    svc = service(repository)
    args: dict[str, Any] = dict(
        document=doc,
        content=fx.MANUAL_V1.encode(),
        content_type="text/markdown",
        filename="test.md",
        actor=ACTOR,
    )
    first = await svc.ingest(**args)
    assert isinstance(first, IngestedVersion)
    duplicate = await svc.ingest(**args)
    assert (
        isinstance(duplicate, DuplicateDocumentSource) and duplicate.existing_run_id == first.run.id
    )
    await svc.approve(version_id=first.version.id, actor=ACTOR)
    await svc.publish(version_id=first.version.id, actor=ACTOR)
    second = await svc.ingest(**{**args, "content": fx.MANUAL_V2.encode()})
    assert isinstance(second, IngestedVersion)
    assert ChangeKind.MODIFIED in second.changes.values()
    assert ChangeKind.UNCHANGED in second.changes.values()
    still_published = await repository.get_published_version(doc.id)
    assert still_published is not None and still_published.id == first.version.id


async def test_closed_runs_preserve_their_outcome(repository: DocumentRepositoryPort) -> None:
    doc = await document(repository)
    data = await version_input(repository, doc)
    version = await repository.store_version(data, actor=ACTOR)
    completed = await repository.get_ingestion_run(data.run_id)
    with pytest.raises(DocumentIntegrityError):
        await repository.fail_ingestion_run(
            run_id=data.run_id, failure_kind="parse", failure_message="late failure"
        )
    assert await repository.get_ingestion_run(data.run_id) == completed
    assert await repository.store_version(data, actor=ACTOR) == version
    failed_data = await version_input(repository, doc, fx.MANUAL_V2)
    failed = await repository.fail_ingestion_run(
        run_id=failed_data.run_id, failure_kind="parse", failure_message="original failure"
    )
    with pytest.raises(DocumentIntegrityError):
        await repository.store_version(failed_data, actor=ACTOR)
    with pytest.raises(DocumentIntegrityError):
        await repository.fail_ingestion_run(
            run_id=failed.id, failure_kind="database", failure_message="late failure"
        )
    assert await repository.get_ingestion_run(failed.id) == failed
    assert await repository.list_versions(doc.id) == (version,)


async def test_superseded_version_is_historical(repository: DocumentRepositoryPort) -> None:
    doc = await document(repository)
    svc = service(repository)
    data = await version_input(repository, doc)
    first = await repository.store_version(data, actor=ACTOR)
    await svc.approve(version_id=first.id, actor=ACTOR)
    await svc.publish(version_id=first.id, actor=ACTOR)
    second = await repository.store_version(
        await version_input(repository, doc, fx.MANUAL_V2), actor=OTHER
    )
    await svc.approve(version_id=second.id, actor=OTHER)
    published = await svc.publish(version_id=second.id, actor=OTHER)
    historical = await repository.get_version(first.id)
    history = await repository.list_version_events(first.id)
    for state in (DocumentVersionState.APPROVED, DocumentVersionState.REJECTED):
        with pytest.raises(NotPublishableError):
            await repository.set_version_state(
                version_id=first.id, state=state, actor=ACTOR, reason="late review"
            )
    with pytest.raises(NotPublishableError):
        await svc.publish(version_id=first.id, actor=ACTOR)
    assert await repository.store_version(data, actor=ACTOR) == historical
    assert await repository.list_version_events(first.id) == history
    assert await repository.get_published_version(doc.id) == published


async def test_storage_key_collision_preserves_original(repository: DocumentRepositoryPort) -> None:
    doc = await document(repository)
    data = await version_input(repository, doc)
    before = await repository.list_ingestion_runs(doc.id)
    with pytest.raises(DocumentIntegrityError):
        await repository.start_ingestion_run(
            document_id=doc.id,
            sha256="f" * 64,
            byte_size=10,
            storage_key=f"document_source/{data.content_sha256}",
            uploaded_by=ACTOR,
        )
    assert await repository.list_ingestion_runs(doc.id) == before
    assert await repository.find_run_by_source("f" * 64) is None
    version = await repository.store_version(data, actor=ACTOR)
    chunk = (await repository.list_chunks(version.id))[0]
    provenance = await repository.get_chunk_provenance(chunk.id)
    assert provenance and provenance.source_sha256 == data.content_sha256


async def test_limits_and_order_do_not_depend_on_ingestion_order(
    repository: DocumentRepositoryPort,
) -> None:
    first = await document(repository)
    second = await document(repository, "manual-b")
    # Se crean A,B y se ingieren B,A: el orden de lectura no debe invertirse.
    for i, doc in enumerate((second, first)):
        data = await version_input(repository, doc, fx.MANUAL_V1 + f"\nOrder {i}")
        version = await repository.store_version(data, actor=ACTOR)
        await service(repository).approve(version_id=version.id, actor=ACTOR)
        await service(repository).publish(version_id=version.id, actor=ACTOR)
    for limit in (0, -1):
        assert await repository.list_ingestion_runs(first.id, limit=limit) == ()
        assert await repository.list_published_chunks(scopes=[first.scope], limit=limit) == ()
    # El reloj puede empatar en Windows; en ese caso el contrato desempata por id.
    ordered = sorted((first, second), key=lambda d: (d.created_at, d.id))
    limited = await repository.list_published_chunks(scopes=[first.scope], limit=1)
    assert len(limited) == 1 and limited[0].document.id == ordered[0].id
    all_chunks = await repository.list_published_chunks(scopes=[first.scope])
    assert [p.document.id for p in all_chunks] == sorted(
        [p.document.id for p in all_chunks], key=lambda id: id != ordered[0].id
    )


@pytest.mark.parametrize("invalid_part", ["section_parent", "chunk_section", "chunk_ordinal"])
async def test_invalid_structure_has_no_partial_writes(
    repository: DocumentRepositoryPort, invalid_part: str
) -> None:
    doc = await document(repository)
    data = await version_input(repository, doc)
    sections = list(data.structure.sections)
    chunks = list(data.structure.chunks)
    if invalid_part == "section_parent":
        sections[-1] = replace(sections[-1], parent_path="missing")
    elif invalid_part == "chunk_section":
        chunks[-1] = replace(chunks[-1], section_path="missing")
    else:
        chunks[-1] = replace(chunks[-1], ordinal=chunks[0].ordinal)
    invalid = replace(
        data, structure=replace(data.structure, sections=tuple(sections), chunks=tuple(chunks))
    )
    run = await repository.get_ingestion_run(data.run_id)
    with pytest.raises(DocumentIntegrityError):
        await repository.store_version(invalid, actor=ACTOR)
    assert await repository.get_ingestion_run(data.run_id) == run
    assert await repository.list_versions(doc.id) == ()
    valid = await repository.store_version(data, actor=ACTOR)
    assert valid.version_number == 1
    assert len(await repository.list_version_events(valid.id)) == 1
