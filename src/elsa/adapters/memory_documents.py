"""Repositorio documental en memoria.

Implementación completa del puerto ``documents``, no un doble simplificado.
Hace cumplir las mismas invariantes que la migración impone en PostgreSQL
—una sola versión publicada por documento, unicidad del hash del original,
historial de transiciones inmodificable— porque un adaptador que las relajara
dejaría pasar en los tests exactamente los errores que el esquema existe
para impedir.

Todas las escrituras están bajo un mismo cerrojo: una versión entra entera o
no entra. No persiste nada: al reiniciar el proceso se pierde todo, y por eso
la configuración solo la permite en DEV.
"""

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from elsa.core.authorization import Scope
from elsa.ports.documents import (
    ChunkProvenance,
    DocumentAlreadyExistsError,
    DocumentChunkRecord,
    DocumentIngestionRunRecord,
    DocumentNotFoundError,
    DocumentRecord,
    DocumentSectionRecord,
    DocumentSourceKind,
    DocumentVersionEventRecord,
    DocumentVersionInput,
    DocumentVersionRecord,
    DocumentVersionState,
    DuplicateSourceError,
    IngestionRunStatus,
    NotPublishableError,
    VersionEvent,
    VersionNotFoundError,
)

__all__ = ["InMemoryDocumentRepository"]


def _now() -> datetime:
    return datetime.now(UTC)


def _identifier() -> str:
    return str(uuid.uuid4())


class _Source:
    """Metadato del archivo original. Los bytes viven en el almacenamiento."""

    __slots__ = ("byte_size", "content_type", "id", "original_filename", "sha256", "storage_key")

    def __init__(
        self,
        *,
        identifier: str,
        sha256: str,
        byte_size: int,
        storage_key: str,
        original_filename: str | None,
        content_type: str | None,
    ) -> None:
        self.id = identifier
        self.sha256 = sha256
        self.byte_size = byte_size
        self.storage_key = storage_key
        self.original_filename = original_filename
        self.content_type = content_type


class InMemoryDocumentRepository:
    """Almacén documental no persistente. Solo DEV y tests."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._documents: dict[str, DocumentRecord] = {}
        self._sources: dict[str, _Source] = {}
        self._source_by_hash: dict[str, str] = {}
        self._runs: dict[str, DocumentIngestionRunRecord] = {}
        self._versions: dict[str, DocumentVersionRecord] = {}
        self._sections: dict[str, list[DocumentSectionRecord]] = {}
        self._chunks: dict[str, list[DocumentChunkRecord]] = {}
        self._events: list[DocumentVersionEventRecord] = []

    # -----------------------------------------------------------------
    # Documentos
    # -----------------------------------------------------------------

    async def create_document(
        self,
        *,
        domain: str,
        code: str,
        title: str,
        source_kind: DocumentSourceKind,
        asset_code: str | None = None,
        language: str | None = None,
        description: str | None = None,
    ) -> DocumentRecord:
        async with self._lock:
            if any(
                document.domain == domain and document.code == code
                for document in self._documents.values()
            ):
                raise DocumentAlreadyExistsError(f"document {code!r} already exists in {domain!r}")
            record = DocumentRecord(
                id=_identifier(),
                domain=domain,
                code=code,
                title=title,
                source_kind=source_kind,
                asset_id=None
                if asset_code is None
                else str(uuid.uuid5(uuid.NAMESPACE_OID, asset_code)),
                asset_code=asset_code,
                language=language,
                description=description,
                created_at=_now(),
            )
            self._documents[record.id] = record
            return record

    async def get_document(self, *, domain: str, code: str) -> DocumentRecord | None:
        return next(
            (
                document
                for document in self._documents.values()
                if document.domain == domain and document.code == code
            ),
            None,
        )

    async def get_document_by_id(self, document_id: str) -> DocumentRecord | None:
        return self._documents.get(document_id)

    async def list_documents(
        self, *, domain: str | None = None, asset_code: str | None = None
    ) -> tuple[DocumentRecord, ...]:
        documents = [
            document
            for document in self._documents.values()
            if (domain is None or document.domain == domain)
            and (asset_code is None or document.asset_code == asset_code)
        ]
        return tuple(sorted(documents, key=lambda document: (document.domain, document.code)))

    # -----------------------------------------------------------------
    # Ingesta
    # -----------------------------------------------------------------

    async def find_run_by_source(self, sha256: str) -> DocumentIngestionRunRecord | None:
        source_id = self._source_by_hash.get(sha256)
        if source_id is None:
            return None
        return next(
            (run for run in self._runs.values() if run.source_artifact_id == source_id), None
        )

    async def start_ingestion_run(
        self,
        *,
        document_id: str,
        sha256: str,
        byte_size: int,
        storage_key: str,
        uploaded_by: str,
        original_filename: str | None = None,
        content_type: str | None = None,
        request_id: str | None = None,
    ) -> DocumentIngestionRunRecord:
        async with self._lock:
            if document_id not in self._documents:
                raise DocumentNotFoundError(document_id)
            existing = self._source_by_hash.get(sha256)
            if existing is not None:
                previous = next(
                    (run for run in self._runs.values() if run.source_artifact_id == existing),
                    None,
                )
                raise DuplicateSourceError(
                    "this exact file has already been ingested",
                    existing_import_id=None if previous is None else previous.id,
                )
            source = _Source(
                identifier=_identifier(),
                sha256=sha256,
                byte_size=byte_size,
                storage_key=storage_key,
                original_filename=original_filename,
                content_type=content_type,
            )
            self._sources[source.id] = source
            self._source_by_hash[sha256] = source.id
            run = DocumentIngestionRunRecord(
                id=_identifier(),
                document_id=document_id,
                source_artifact_id=source.id,
                status=IngestionRunStatus.RECEIVED,
                started_by=uploaded_by,
                started_at=_now(),
                request_id=request_id,
            )
            self._runs[run.id] = run
            return run

    async def fail_ingestion_run(
        self,
        *,
        run_id: str,
        failure_kind: str,
        failure_message: str,
        stats: Mapping[str, object] | None = None,
    ) -> DocumentIngestionRunRecord:
        async with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise VersionNotFoundError(run_id)
            # Cerrar como fallida no toca ninguna versión: la publicada sigue
            # publicada y la anterior sigue siendo la última válida.
            updated = DocumentIngestionRunRecord(
                id=run.id,
                document_id=run.document_id,
                source_artifact_id=run.source_artifact_id,
                status=IngestionRunStatus.FAILED,
                started_by=run.started_by,
                started_at=run.started_at,
                failure_kind=failure_kind,
                failure_message=failure_message,
                request_id=run.request_id,
                finished_at=_now(),
                stats=dict(stats or {}),
            )
            self._runs[run.id] = updated
            return updated

    async def get_ingestion_run(self, run_id: str) -> DocumentIngestionRunRecord | None:
        return self._runs.get(run_id)

    async def list_ingestion_runs(
        self, document_id: str, *, limit: int = 50
    ) -> tuple[DocumentIngestionRunRecord, ...]:
        runs = [run for run in self._runs.values() if run.document_id == document_id]
        runs.sort(key=lambda run: run.started_at, reverse=True)
        return tuple(runs[:limit])

    # -----------------------------------------------------------------
    # Versiones
    # -----------------------------------------------------------------

    async def store_version(
        self, data: DocumentVersionInput, *, actor: str, request_id: str | None = None
    ) -> DocumentVersionRecord:
        async with self._lock:
            if data.document_id not in self._documents:
                raise DocumentNotFoundError(data.document_id)
            run = self._runs.get(data.run_id)
            if run is None:
                raise VersionNotFoundError(data.run_id)

            existing = [
                version
                for version in self._versions.values()
                if version.document_id == data.document_id
            ]
            number = max((version.version_number for version in existing), default=0) + 1

            version = DocumentVersionRecord(
                id=_identifier(),
                document_id=data.document_id,
                run_id=data.run_id,
                source_artifact_id=data.source_artifact_id,
                version_number=number,
                state=DocumentVersionState.PENDING_VALIDATION,
                content_sha256=data.content_sha256,
                structure_sha256=data.structure.structure_sha256,
                chunking_profile=data.structure.policy.name,
                chunking_parameters=dict(data.structure.policy.parameters()),
                extractor=data.extractor,
                extractor_version=data.extractor_version,
                created_at=_now(),
                section_count=len(data.structure.sections),
                chunk_count=len(data.structure.chunks),
            )

            # Las secciones llegan en orden de lectura, asi que el padre
            # siempre esta ya registrado cuando se procesa un hijo.
            section_ids: dict[str, str] = {}
            sections: list[DocumentSectionRecord] = []
            for section in data.structure.sections:
                identifier = _identifier()
                section_ids[section.path] = identifier
                sections.append(
                    DocumentSectionRecord(
                        id=identifier,
                        version_id=version.id,
                        ordinal=section.ordinal,
                        path=section.path,
                        depth=section.depth,
                        title=section.title,
                        parent_id=(
                            None
                            if section.parent_path is None
                            else section_ids.get(section.parent_path)
                        ),
                        parent_path=section.parent_path,
                        number_label=section.number_label,
                        page_start=section.page_start,
                        page_end=section.page_end,
                        char_start=section.char_start,
                        char_end=section.char_end,
                        is_preamble=section.is_preamble,
                    )
                )

            chunks = [
                DocumentChunkRecord(
                    id=_identifier(),
                    version_id=version.id,
                    ordinal=chunk.ordinal,
                    structural_key=chunk.structural_key,
                    content=chunk.content,
                    content_sha256=chunk.content_sha256,
                    kind=chunk.kind,
                    section_id=(
                        None if chunk.section_path is None else section_ids.get(chunk.section_path)
                    ),
                    section_path=chunk.section_path,
                    section_title=chunk.section_title,
                    index_in_section=chunk.index_in_section,
                    heading_trail=chunk.heading_trail,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    block_start=chunk.block_start,
                    block_end=chunk.block_end,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    token_estimate=chunk.token_estimate,
                    char_length=chunk.char_length,
                    overlap_chars=chunk.overlap_chars,
                    boundary_reason=chunk.boundary_reason,
                    oversized=chunk.oversized,
                    warnings=chunk.warnings,
                    change_kind=data.changes.get(chunk.structural_key),
                )
                for chunk in data.structure.chunks
            ]

            self._versions[version.id] = version
            self._sections[version.id] = sections
            self._chunks[version.id] = chunks
            self._runs[run.id] = DocumentIngestionRunRecord(
                id=run.id,
                document_id=run.document_id,
                source_artifact_id=run.source_artifact_id,
                status=IngestionRunStatus.COMPLETED,
                started_by=run.started_by,
                started_at=run.started_at,
                request_id=run.request_id,
                finished_at=_now(),
                stats=dict(data.stats),
            )
            self._record(version.id, VersionEvent.CREATED, actor, None, request_id)
            return version

    async def get_version(self, version_id: str) -> DocumentVersionRecord | None:
        return self._versions.get(version_id)

    async def list_versions(self, document_id: str) -> tuple[DocumentVersionRecord, ...]:
        versions = [
            version for version in self._versions.values() if version.document_id == document_id
        ]
        return tuple(sorted(versions, key=lambda version: version.version_number))

    async def get_published_version(self, document_id: str) -> DocumentVersionRecord | None:
        return next(
            (
                version
                for version in self._versions.values()
                if version.document_id == document_id
                and version.state is DocumentVersionState.PUBLISHED
            ),
            None,
        )

    async def list_sections(self, version_id: str) -> tuple[DocumentSectionRecord, ...]:
        return tuple(self._sections.get(version_id, ()))

    async def list_chunks(self, version_id: str) -> tuple[DocumentChunkRecord, ...]:
        return tuple(self._chunks.get(version_id, ()))

    async def get_chunk_provenance(self, chunk_id: str) -> ChunkProvenance | None:
        for version_id, chunks in self._chunks.items():
            for chunk in chunks:
                if chunk.id == chunk_id:
                    return self._provenance(version_id, chunk)
        return None

    async def set_version_state(
        self,
        *,
        version_id: str,
        state: DocumentVersionState,
        actor: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> DocumentVersionRecord:
        async with self._lock:
            version = self._versions.get(version_id)
            if version is None:
                raise VersionNotFoundError(version_id)
            if version.state is DocumentVersionState.PUBLISHED:
                raise NotPublishableError("a published version cannot change state directly")
            # Solo las dos decisiones que toma una persona. `published` tiene
            # su propia operacion porque ademas reemplaza a la anterior, y
            # `superseded` no lo decide nadie: es consecuencia de publicar.
            if state not in (DocumentVersionState.APPROVED, DocumentVersionState.REJECTED):
                raise NotPublishableError(
                    f"a version cannot be moved to {state.value} through this operation"
                )
            updated = self._replace(version, state=state)
            self._versions[version_id] = updated
            self._record(version_id, VersionEvent(state.value), actor, reason, request_id)
            return updated

    async def publish_version(
        self, *, version_id: str, actor: str, request_id: str | None = None
    ) -> DocumentVersionRecord:
        async with self._lock:
            version = self._versions.get(version_id)
            if version is None:
                raise VersionNotFoundError(version_id)
            if version.state is not DocumentVersionState.APPROVED:
                # Publicar sin aprobar saltaría la validación entera. El
                # estado no es decoración: es el permiso para publicar.
                raise NotPublishableError(
                    f"only an approved version can be published; this one is {version.state.value}"
                )
            moment = _now()
            for other in list(self._versions.values()):
                if (
                    other.document_id == version.document_id
                    and other.id != version_id
                    and other.state is DocumentVersionState.PUBLISHED
                ):
                    self._versions[other.id] = self._replace(
                        other, state=DocumentVersionState.SUPERSEDED, superseded_at=moment
                    )
                    self._record(other.id, VersionEvent.SUPERSEDED, actor, None, request_id)
            published = self._replace(
                version,
                state=DocumentVersionState.PUBLISHED,
                published_at=moment,
                published_by=actor,
            )
            self._versions[version_id] = published
            self._record(version_id, VersionEvent.PUBLISHED, actor, None, request_id)
            return published

    async def list_version_events(self, version_id: str) -> tuple[DocumentVersionEventRecord, ...]:
        return tuple(event for event in self._events if event.version_id == version_id)

    # -----------------------------------------------------------------
    # Lectura por alcance
    # -----------------------------------------------------------------

    async def list_published_chunks(
        self, *, scopes: Sequence[Scope], limit: int = 100
    ) -> tuple[ChunkProvenance, ...]:
        if not scopes:
            return ()
        allowed = set(scopes)
        results: list[ChunkProvenance] = []
        for version in sorted(self._versions.values(), key=lambda v: v.version_number):
            if version.state is not DocumentVersionState.PUBLISHED:
                continue
            document = self._documents[version.document_id]
            if document.scope not in allowed:
                continue
            for chunk in self._chunks.get(version.id, ()):
                results.append(self._provenance(version.id, chunk))
                if len(results) >= limit:
                    return tuple(results)
        return tuple(results)

    async def check_health(self) -> None:
        return None

    # -----------------------------------------------------------------
    # Interno
    # -----------------------------------------------------------------

    def _provenance(self, version_id: str, chunk: DocumentChunkRecord) -> ChunkProvenance:
        version = self._versions[version_id]
        document = self._documents[version.document_id]
        section = next(
            (
                candidate
                for candidate in self._sections.get(version_id, ())
                if candidate.id == chunk.section_id
            ),
            None,
        )
        source = self._sources[version.source_artifact_id]
        return ChunkProvenance(
            chunk=chunk,
            document=document,
            version=version,
            section=section,
            source_sha256=source.sha256,
            source_storage_key=source.storage_key,
        )

    def _record(
        self,
        version_id: str,
        event: VersionEvent,
        actor: str,
        reason: str | None,
        request_id: str | None,
    ) -> None:
        self._events.append(
            DocumentVersionEventRecord(
                id=_identifier(),
                seq=len(self._events) + 1,
                version_id=version_id,
                event=event,
                actor=actor,
                occurred_at=_now(),
                reason=reason,
                request_id=request_id,
            )
        )

    @staticmethod
    def _replace(
        version: DocumentVersionRecord,
        *,
        state: DocumentVersionState | None = None,
        published_at: datetime | None = None,
        published_by: str | None = None,
        superseded_at: datetime | None = None,
    ) -> DocumentVersionRecord:
        return DocumentVersionRecord(
            id=version.id,
            document_id=version.document_id,
            run_id=version.run_id,
            source_artifact_id=version.source_artifact_id,
            version_number=version.version_number,
            state=state or version.state,
            content_sha256=version.content_sha256,
            structure_sha256=version.structure_sha256,
            chunking_profile=version.chunking_profile,
            chunking_parameters=version.chunking_parameters,
            extractor=version.extractor,
            extractor_version=version.extractor_version,
            created_at=version.created_at,
            published_at=published_at or version.published_at,
            published_by=published_by or version.published_by,
            superseded_at=superseded_at or version.superseded_at,
            section_count=version.section_count,
            chunk_count=version.chunk_count,
        )
