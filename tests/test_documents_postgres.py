"""Transacciones y concurrencia verificadas en PostgreSQL 16 real."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import asyncpg
import pytest

from elsa.adapters.memory_documents import InMemoryDocumentRepository
from elsa.adapters.postgres_documents import PostgresDocumentRepository
from elsa.core.authorization import Scope
from elsa.ports.documents import (
    DocumentIntegrityError,
    DocumentVersionState,
    KnowledgeUnavailableError,
    NotPublishableError,
    VersionEvent,
)
from tests import db
from tests import fixtures_documents as fx
from tests.test_document_repository import ACTOR, OTHER, document, service, version_input

pytestmark = pytest.mark.anyio


@pytest.fixture
async def postgres() -> AsyncIterator[PostgresDocumentRepository]:
    url = db.database_url()
    if url is None:
        pytest.skip(db.SKIP_REASON)
    await db.reset_database(url)
    conn = await asyncpg.connect(url)
    try:
        assert 160000 <= int(await conn.fetchval("show server_version_num")) < 170000
        await conn.execute(
            "insert into elsa.technical_assets (code,name,domain) values "
            "('asset-a','A','mantenimiento')"
        )
    finally:
        await conn.close()
    repo = await PostgresDocumentRepository.connect(url, min_size=2, max_size=6)
    try:
        yield repo
    finally:
        await repo.close()


async def counts() -> dict[str, int]:
    conn = await asyncpg.connect(db.database_url())
    try:
        return {
            table: await conn.fetchval(f"select count(*) from elsa.{table}")
            for table in (
                "documents",
                "source_artifacts",
                "document_ingestion_runs",
                "document_versions",
                "document_sections",
                "document_chunks",
                "document_version_events",
            )
        }
    finally:
        await conn.close()


async def test_sql_failure_after_version_sections_and_chunk_rolls_back(
    postgres: PostgresDocumentRepository,
) -> None:
    doc = await document(postgres)
    data = await version_input(postgres, doc)
    before = await counts()
    run = await postgres.get_ingestion_run(data.run_id)
    assert len(data.structure.chunks) > 1
    # El último INSERT viola una CHECK real, después de guardar la versión,
    # sus secciones y los chunks anteriores. No se modifica el esquema.
    bad = replace(data.structure.chunks[-1], boundary_reason="invalid")
    invalid = replace(
        data, structure=replace(data.structure, chunks=(*data.structure.chunks[:-1], bad))
    )
    with pytest.raises(KnowledgeUnavailableError):
        await postgres.store_version(invalid, actor=ACTOR)
    assert await counts() == before
    assert await postgres.get_ingestion_run(data.run_id) == run
    version = await postgres.store_version(data, actor=ACTOR)
    assert version.version_number == 1
    assert len(await postgres.list_chunks(version.id)) == len(data.structure.chunks)


async def test_event_failure_rolls_back_entire_version(
    postgres: PostgresDocumentRepository,
) -> None:
    doc = await document(postgres)
    data = await version_input(postgres, doc)
    before = await counts()
    run = await postgres.get_ingestion_run(data.run_id)
    # UUID inválido al escribir el evento final: ya se escribió/cerró todo
    # lo anterior en la transacción, que debe revertirse también por error Python.
    with pytest.raises(ValueError):
        await postgres.store_version(data, actor="invalid-uuid")
    assert await counts() == before
    assert await postgres.get_ingestion_run(data.run_id) == run


async def test_publication_failure_preserves_old_version_and_history(
    postgres: PostgresDocumentRepository,
) -> None:
    doc = await document(postgres)
    first = await postgres.store_version(await version_input(postgres, doc), actor=ACTOR)
    svc = service(postgres)
    await svc.approve(version_id=first.id, actor=ACTOR)
    published = await svc.publish(version_id=first.id, actor=ACTOR)
    second = await postgres.store_version(
        await version_input(postgres, doc, fx.MANUAL_V2), actor=ACTOR
    )
    second = await svc.approve(version_id=second.id, actor=ACTOR)
    before = await counts()
    history = await postgres.list_version_events(first.id)
    with pytest.raises(ValueError):
        await svc.publish(version_id=second.id, actor="invalid-uuid")
    assert await counts() == before
    assert await postgres.get_published_version(doc.id) == published
    assert await postgres.get_version(second.id) == second
    assert await postgres.list_version_events(first.id) == history


async def test_concurrent_numbering_and_publication_across_pools(
    postgres: PostgresDocumentRepository,
) -> None:
    doc = await document(postgres)
    inputs = [
        await version_input(postgres, doc, fx.MANUAL_V1 + f"\nRevision {i}") for i in range(4)
    ]
    other = await PostgresDocumentRepository.connect(db.database_url() or "", min_size=2)
    try:
        repos = [postgres, other, postgres, other]
        versions = await asyncio.gather(
            *(r.store_version(data, actor=ACTOR) for r, data in zip(repos, inputs, strict=True))
        )
        assert sorted(v.version_number for v in versions) == [1, 2, 3, 4]
        for v in versions:
            await service(postgres).approve(version_id=v.id, actor=ACTOR)
        await asyncio.gather(
            *(
                r.publish_version(version_id=v.id, actor=ACTOR)
                for r, v in zip(repos, versions, strict=True)
            )
        )
        stored = await postgres.list_versions(doc.id)
        assert sum(v.state is DocumentVersionState.PUBLISHED for v in stored) == 1
        assert sum(v.state is DocumentVersionState.SUPERSEDED for v in stored) == 3
        published = await postgres.get_published_version(doc.id)
        assert published
        assert {p.version.id for p in await postgres.list_published_chunks(scopes=[doc.scope])} == {
            published.id
        }
        for v in stored:
            events = [e.event for e in await postgres.list_version_events(v.id)]
            expected = [VersionEvent.CREATED, VersionEvent.APPROVED, VersionEvent.PUBLISHED]
            if v.state is DocumentVersionState.SUPERSEDED:
                expected.append(VersionEvent.SUPERSEDED)
            assert events == expected
    finally:
        await other.close()


async def test_same_version_cannot_be_published_twice_concurrently(
    postgres: PostgresDocumentRepository,
) -> None:
    doc = await document(postgres)
    version = await postgres.store_version(await version_input(postgres, doc), actor=ACTOR)
    await service(postgres).approve(version_id=version.id, actor=ACTOR)
    results = await asyncio.gather(
        *(postgres.publish_version(version_id=version.id, actor=ACTOR) for _ in range(2)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, NotPublishableError) for r in results) == 1
    assert [e.event for e in await postgres.list_version_events(version.id)].count(
        VersionEvent.PUBLISHED
    ) == 1


async def test_wrong_asset_domain_and_storage_collision_are_explicit(
    postgres: PostgresDocumentRepository,
) -> None:
    before = await counts()
    with pytest.raises(DocumentIntegrityError):
        await document(postgres, domain="other", asset="asset-a")
    with pytest.raises(DocumentIntegrityError):
        await document(postgres, asset="missing")
    assert await counts() == before
    doc = await document(postgres)
    data = await version_input(postgres, doc)
    before = await counts()
    with pytest.raises(DocumentIntegrityError):
        await postgres.start_ingestion_run(
            document_id=doc.id,
            sha256="f" * 64,
            byte_size=10,
            storage_key=f"document_source/{data.content_sha256}",
            uploaded_by=ACTOR,
        )
    assert await counts() == before


async def test_reconnect_reconstructs_every_record(postgres: PostgresDocumentRepository) -> None:
    doc = await document(postgres)
    data = await version_input(postgres, doc)
    version = await postgres.store_version(data, actor=ACTOR)
    chunks = await postgres.list_chunks(version.id)
    sections = await postgres.list_sections(version.id)
    events = await postgres.list_version_events(version.id)
    provenance = await postgres.get_chunk_provenance(chunks[0].id)
    other = await PostgresDocumentRepository.connect(db.database_url() or "")
    try:
        assert await other.get_document_by_id(doc.id) == doc
        assert await other.get_version(version.id) == version
        assert await other.list_chunks(version.id) == chunks
        assert await other.list_sections(version.id) == sections
        assert await other.list_version_events(version.id) == events
        assert await other.get_chunk_provenance(chunks[0].id) == provenance
        assert await other.store_version(data, actor=ACTOR) == version
    finally:
        await other.close()


async def test_memory_postgres_observable_parity(postgres: PostgresDocumentRepository) -> None:
    async def flow(repo: Any) -> Any:
        doc = await document(repo)
        svc = service(repo)
        first = await svc.ingest(
            document=doc,
            content=fx.MANUAL_V1.encode(),
            content_type="text/markdown",
            filename="test.md",
            actor=ACTOR,
        )
        assert isinstance(first, IngestedVersion)
        await svc.approve(version_id=first.version.id, actor=ACTOR, comment="checked")
        await svc.publish(version_id=first.version.id, actor=ACTOR)
        second = await svc.ingest(
            document=doc,
            content=fx.MANUAL_V2.encode(),
            content_type="text/markdown",
            filename="test.md",
            actor=OTHER,
        )
        assert isinstance(second, IngestedVersion)
        prior = await repo.list_published_chunks(scopes=[Scope("mantenimiento", "asset-a")])
        await svc.reject(version_id=second.version.id, actor=OTHER, reason="check")
        await svc.approve(version_id=second.version.id, actor=OTHER)
        await svc.publish(version_id=second.version.id, actor=OTHER)

        def content(value: Any) -> dict[str, Any]:
            from dataclasses import asdict

            # Solo IDs generados y relojes difieren entre almacenes. Las
            # relaciones se prueban por separado, sin ocultar datos del dominio.
            return {
                k: v
                for k, v in asdict(value).items()
                if k
                not in {
                    "id",
                    "document_id",
                    "version_id",
                    "run_id",
                    "source_artifact_id",
                    "asset_id",
                    "parent_id",
                    "section_id",
                    "created_at",
                    "published_at",
                    "superseded_at",
                    "occurred_at",
                    "started_at",
                    "finished_at",
                }
            }

        versions = await repo.list_versions(doc.id)
        return {
            "document": content(doc),
            "versions": [content(v) for v in versions],
            "runs": [content(r) for r in await repo.list_ingestion_runs(doc.id)],
            "sections": [[content(s) for s in await repo.list_sections(v.id)] for v in versions],
            "chunks": [[content(c) for c in await repo.list_chunks(v.id)] for v in versions],
            "events": [
                [content(e) for e in await repo.list_version_events(v.id)] for v in versions
            ],
            "previous_published": [(p.version.version_number, p.chunk.content) for p in prior],
            "published": [
                (
                    p.version.version_number,
                    p.chunk.content,
                    p.source_sha256,
                    p.source_storage_key,
                    p.citation(),
                )
                for p in await repo.list_published_chunks(scopes=[doc.scope])
            ],
            "changes": dict(second.changes),
        }

    assert await flow(InMemoryDocumentRepository()) == await flow(postgres)
