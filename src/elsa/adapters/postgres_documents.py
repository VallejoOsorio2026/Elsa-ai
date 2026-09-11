"""Persistencia documental PostgreSQL; solo backend, sin DDL ni permisos nuevos.

Las reglas viven en documents.persistence. El documento se bloquea antes de
numerar/publicar y la corrida antes de guardar/reintentar. Cada unidad lógica
incluye sus eventos y el cierre de ingesta en la misma transacción.
"""

import contextlib
import json
import logging
import uuid
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import fields
from typing import Any

import asyncpg

from elsa.core.authorization import Scope
from elsa.core.versioning import ChangeKind
from elsa.documents.model import ChunkKind
from elsa.documents.persistence import (
    content_records,
    require_open_run,
    require_publishable,
    validate_retry,
    validate_source,
    validate_transition,
)
from elsa.ports.documents import (
    ChunkProvenance,
    DocumentAlreadyExistsError,
    DocumentChunkRecord,
    DocumentIngestionRunRecord,
    DocumentIntegrityError,
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
    KnowledgeUnavailableError,
    VersionEvent,
    VersionNotFoundError,
)

_logger = logging.getLogger("elsa.documents.postgres")
_JSON_FIELDS = {"stats", "chunking_parameters"}
_UUID_FIELDS = {
    "id",
    "document_id",
    "version_id",
    "run_id",
    "source_artifact_id",
    "parent_id",
    "section_id",
    "asset_id",
    "started_by",
    "published_by",
    "actor",
}


def _record[T](cls: type[T], row: Any, **extra: Any) -> T:
    values = {f.name: row[f.name] for f in fields(cls) if f.name in row}  # type: ignore[arg-type]
    values.update(extra)
    for key, value in values.items():
        if key in _UUID_FIELDS and value is not None:
            values[key] = str(value)
        elif key in _JSON_FIELDS and isinstance(value, str):
            values[key] = json.loads(value)
        elif key in {"warnings", "heading_trail"}:
            values[key] = tuple(value)
    if cls is DocumentRecord:
        values["source_kind"] = DocumentSourceKind(values["source_kind"])
    elif cls is DocumentIngestionRunRecord:
        values["status"] = IngestionRunStatus(values["status"])
    elif cls is DocumentVersionRecord:
        values["state"] = DocumentVersionState(values["state"])
    elif cls is DocumentVersionEventRecord:
        values["event"] = VersionEvent(values["event"])
    elif cls is DocumentChunkRecord:
        values["kind"] = ChunkKind(values["kind"])
        if values["change_kind"] is not None:
            values["change_kind"] = ChangeKind(values["change_kind"])
    return cls(**values)


def _uuid(value: str) -> uuid.UUID:
    return uuid.UUID(value)


def _json(value: Mapping[str, object]) -> str:
    return json.dumps(dict(value), allow_nan=False)


@contextlib.contextmanager
def _database_errors():
    try:
        yield
    except (asyncpg.PostgresError, OSError, TimeoutError) as error:
        _logger.warning("document store failure", extra={"error": type(error).__name__})
        raise KnowledgeUnavailableError("the ELSA document store is unavailable") from None


_DOCUMENT = (
    "select d.*, a.code as asset_code from elsa.documents d "
    "left join elsa.technical_assets a on a.id=d.asset_id"
)
_PROVENANCE = """
select c as chunk, v as version, d as document, s as section,
       p.scope_equipment as asset_code, p.source_sha256, p.source_storage_key
from elsa.document_chunk_provenance p
join elsa.document_chunks c on c.id=p.chunk_id
join elsa.document_versions v on v.id=p.version_id
join elsa.documents d on d.id=p.document_id
left join elsa.document_sections s on s.id=p.section_id and s.version_id=v.id
"""


def _provenance(row: Any) -> ChunkProvenance:
    return ChunkProvenance(
        chunk=_record(DocumentChunkRecord, row["chunk"]),
        version=_record(DocumentVersionRecord, row["version"]),
        document=_record(DocumentRecord, row["document"], asset_code=row["asset_code"]),
        section=None if row["section"] is None else _record(DocumentSectionRecord, row["section"]),
        source_sha256=row["source_sha256"],
        source_storage_key=row["source_storage_key"],
    )


class PostgresDocumentRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(
        cls, dsn: str, *, min_size: int = 1, max_size: int = 10, timeout_seconds: float = 30.0
    ) -> "PostgresDocumentRepository":
        with _database_errors():
            pool = await asyncpg.create_pool(
                dsn, min_size=min_size, max_size=max_size, command_timeout=timeout_seconds
            )
        if pool is None:
            raise KnowledgeUnavailableError("could not create connection pool")
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    @contextlib.asynccontextmanager
    async def _transaction(self) -> AsyncIterator[Any]:
        with _database_errors():
            async with self._pool.acquire() as conn, conn.transaction():
                yield conn

    async def _rows(self, query: str, *args: Any) -> list[Any]:
        with _database_errors():
            return list(await self._pool.fetch(query, *args))

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
        async with self._transaction() as conn:
            asset_id = None
            if asset_code is not None:
                asset_id = await conn.fetchval(
                    "select id from elsa.technical_assets where code=$1 and domain=$2 for share",
                    asset_code,
                    domain,
                )
                if asset_id is None:
                    raise DocumentIntegrityError("asset must exist in the document domain")
            try:
                row = await conn.fetchrow(
                    "insert into elsa.documents "
                    "(domain,code,title,source_kind,asset_id,language,description) "
                    "values ($1,$2,$3,$4,$5,$6,$7) returning *",
                    domain,
                    code,
                    title,
                    source_kind.value,
                    asset_id,
                    language,
                    description,
                )
            except asyncpg.UniqueViolationError:
                raise DocumentAlreadyExistsError(code) from None
            return _record(DocumentRecord, row, asset_code=asset_code)

    async def get_document(self, *, domain: str, code: str) -> DocumentRecord | None:
        rows = await self._rows(_DOCUMENT + " where d.domain=$1 and d.code=$2", domain, code)
        return _record(DocumentRecord, rows[0]) if rows else None

    async def get_document_by_id(self, document_id: str) -> DocumentRecord | None:
        rows = await self._rows(_DOCUMENT + " where d.id=$1", _uuid(document_id))
        return _record(DocumentRecord, rows[0]) if rows else None

    async def list_documents(
        self, *, domain: str | None = None, asset_code: str | None = None
    ) -> tuple[DocumentRecord, ...]:
        rows = await self._rows(
            _DOCUMENT + " where ($1::text is null or d.domain=$1) "
            "and ($2::text is null or a.code=$2) order by d.domain,d.code",
            domain,
            asset_code,
        )
        return tuple(_record(DocumentRecord, row) for row in rows)

    async def find_run_by_source(self, sha256: str) -> DocumentIngestionRunRecord | None:
        rows = await self._rows(
            "select r.* from elsa.document_ingestion_runs r "
            "join elsa.source_artifacts a on a.id=r.source_artifact_id "
            "where a.sha256=$1 order by r.started_at,r.id limit 1",
            sha256,
        )
        return _record(DocumentIngestionRunRecord, rows[0]) if rows else None

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
        async with self._transaction() as conn:
            if not await conn.fetchval(
                "select id from elsa.documents where id=$1 for share", _uuid(document_id)
            ):
                raise DocumentNotFoundError(document_id)
            # Un hash documental es único incluso si cambia el MIME. El cerrojo
            # vive en PostgreSQL y cubre todos los procesos del adaptador.
            await conn.execute("select pg_advisory_xact_lock(hashtextextended($1, 4101))", sha256)
            previous = await conn.fetchrow(
                "select r.id from elsa.document_ingestion_runs r "
                "join elsa.source_artifacts a on a.id=r.source_artifact_id where a.sha256=$1",
                sha256,
            )
            if previous:
                raise DuplicateSourceError(
                    "this exact file has already been ingested",
                    existing_import_id=str(previous["id"]),
                )
            kind = {"text/markdown": "document_markdown", "application/pdf": "document_pdf"}.get(
                content_type or "", "document_text"
            )
            try:
                source_id = await conn.fetchval(
                    "insert into elsa.source_artifacts "
                    "(kind,sha256,byte_size,storage_key,uploaded_by,original_filename,content_type)"
                    " "
                    "values ($1,$2,$3,$4,$5,$6,$7) returning id",
                    kind,
                    sha256,
                    byte_size,
                    storage_key,
                    _uuid(uploaded_by),
                    original_filename,
                    content_type,
                )
            except asyncpg.UniqueViolationError as error:
                if error.constraint_name == "source_artifacts_kind_sha256_key":
                    raise DuplicateSourceError("the original is already registered") from None
                raise DocumentIntegrityError(
                    "source storage key already belongs to an original"
                ) from None
            row = await conn.fetchrow(
                "insert into elsa.document_ingestion_runs "
                "(document_id,source_artifact_id,started_by,request_id) values ($1,$2,$3,$4) "
                "returning *",
                _uuid(document_id),
                source_id,
                _uuid(uploaded_by),
                request_id,
            )
            return _record(DocumentIngestionRunRecord, row)

    async def get_ingestion_run(self, run_id: str) -> DocumentIngestionRunRecord | None:
        rows = await self._rows(
            "select * from elsa.document_ingestion_runs where id=$1", _uuid(run_id)
        )
        return _record(DocumentIngestionRunRecord, rows[0]) if rows else None

    async def list_ingestion_runs(
        self, document_id: str, *, limit: int = 50
    ) -> tuple[DocumentIngestionRunRecord, ...]:
        rows = await self._rows(
            "select * from elsa.document_ingestion_runs where document_id=$1 "
            "order by started_at desc,id limit $2",
            _uuid(document_id),
            max(0, limit),
        )
        return tuple(_record(DocumentIngestionRunRecord, row) for row in rows)

    async def fail_ingestion_run(
        self,
        *,
        run_id: str,
        failure_kind: str,
        failure_message: str,
        stats: Mapping[str, object] | None = None,
    ) -> DocumentIngestionRunRecord:
        async with self._transaction() as conn:
            run = await conn.fetchrow(
                "select * from elsa.document_ingestion_runs where id=$1 for update",
                _uuid(run_id),
            )
            if run is None:
                raise VersionNotFoundError(run_id)
            require_open_run(_record(DocumentIngestionRunRecord, run))
            row = await conn.fetchrow(
                "update elsa.document_ingestion_runs set status='failed',failure_kind=$2,"
                "failure_message=$3,stats=$4::jsonb,finished_at=clock_timestamp() where id=$1 "
                "returning *",
                _uuid(run_id),
                failure_kind,
                failure_message,
                _json(stats or {}),
            )
            return _record(DocumentIngestionRunRecord, row)

    async def store_version(
        self, data: DocumentVersionInput, *, actor: str, request_id: str | None = None
    ) -> DocumentVersionRecord:
        async with self._transaction() as conn:
            await self._lock_document(conn, data.document_id)
            run_row = await conn.fetchrow(
                "select * from elsa.document_ingestion_runs where id=$1 for update",
                _uuid(data.run_id),
            )
            if run_row is None:
                raise VersionNotFoundError(data.run_id)
            run = _record(DocumentIngestionRunRecord, run_row)
            old = await conn.fetchrow(
                "select * from elsa.document_versions where run_id=$1", _uuid(data.run_id)
            )
            if old:
                version = _record(DocumentVersionRecord, old)
                sections = await conn.fetch(
                    "select * from elsa.document_sections where version_id=$1 order by ordinal",
                    old["id"],
                )
                chunks = await conn.fetch(
                    "select * from elsa.document_chunks where version_id=$1 order by ordinal",
                    old["id"],
                )
                created = await conn.fetchrow(
                    "select * from elsa.document_version_events where version_id=$1 and "
                    "event='created' order by seq limit 1",
                    old["id"],
                )
                validate_retry(
                    data,
                    version,
                    run,
                    [_record(DocumentSectionRecord, s) for s in sections],
                    [_record(DocumentChunkRecord, c) for c in chunks],
                    _record(DocumentVersionEventRecord, created),
                    actor=actor,
                    request_id=request_id,
                )
                return version
            require_open_run(run)
            source = await conn.fetchrow(
                "select sha256 from elsa.source_artifacts where id=$1 for share",
                _uuid(data.source_artifact_id),
            )
            validate_source(data, run, None if source is None else source["sha256"])
            sections, chunks = content_records(data, str(uuid.uuid4()))
            number = await conn.fetchval(
                "select coalesce(max(version_number),0)+1 from elsa.document_versions where "
                "document_id=$1",
                _uuid(data.document_id),
            )
            row = await conn.fetchrow(
                "insert into elsa.document_versions (document_id,run_id,source_artifact_id,"
                "version_number,content_sha256,structure_sha256,chunking_profile,chunking_parameters,"
                "extractor,extractor_version,section_count,chunk_count) "
                "values ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12) returning *",
                _uuid(data.document_id),
                _uuid(data.run_id),
                _uuid(data.source_artifact_id),
                number,
                data.content_sha256,
                data.structure.structure_sha256,
                data.structure.policy.name,
                _json(data.structure.policy.parameters()),
                data.extractor,
                data.extractor_version,
                len(sections),
                len(chunks),
            )
            for section in sections:
                await self._insert_content(conn, "document_sections", section, row["id"])
            for chunk in chunks:
                await self._insert_content(conn, "document_chunks", chunk, row["id"])
            await conn.execute(
                "update elsa.document_ingestion_runs set status='completed',"
                "failure_kind=null,failure_message=null,finished_at=clock_timestamp(),"
                "stats=$2::jsonb where id=$1",
                _uuid(run.id),
                _json(data.stats),
            )
            await self._event(conn, row["id"], VersionEvent.CREATED, actor, None, request_id)
            return _record(DocumentVersionRecord, row)

    @staticmethod
    async def _insert_content(conn: Any, table: str, record: Any, version_id: uuid.UUID) -> None:
        # Nombres internos de dataclasses, nunca identificadores recibidos del usuario.
        names = [f.name for f in fields(record)]
        values = []
        for name in names:
            value = getattr(record, name)
            if name == "version_id":
                value = version_id
            elif name in _UUID_FIELDS and value is not None:
                value = _uuid(value)
            values.append(value)
        placeholders = ",".join(f"${i}" for i in range(1, len(names) + 1))
        await conn.execute(
            f"insert into elsa.{table} ({','.join(names)}) values ({placeholders})", *values
        )

    async def get_version(self, version_id: str) -> DocumentVersionRecord | None:
        rows = await self._rows(
            "select * from elsa.document_versions where id=$1", _uuid(version_id)
        )
        return _record(DocumentVersionRecord, rows[0]) if rows else None

    async def list_versions(self, document_id: str) -> tuple[DocumentVersionRecord, ...]:
        rows = await self._rows(
            "select * from elsa.document_versions where document_id=$1 order by version_number",
            _uuid(document_id),
        )
        return tuple(_record(DocumentVersionRecord, row) for row in rows)

    async def get_published_version(self, document_id: str) -> DocumentVersionRecord | None:
        rows = await self._rows(
            "select * from elsa.document_versions where document_id=$1 and state='published'",
            _uuid(document_id),
        )
        return _record(DocumentVersionRecord, rows[0]) if rows else None

    async def list_sections(self, version_id: str) -> tuple[DocumentSectionRecord, ...]:
        rows = await self._rows(
            "select * from elsa.document_sections where version_id=$1 order by ordinal",
            _uuid(version_id),
        )
        return tuple(_record(DocumentSectionRecord, row) for row in rows)

    async def list_chunks(self, version_id: str) -> tuple[DocumentChunkRecord, ...]:
        rows = await self._rows(
            "select * from elsa.document_chunks where version_id=$1 order by ordinal",
            _uuid(version_id),
        )
        return tuple(_record(DocumentChunkRecord, row) for row in rows)

    async def get_chunk_provenance(self, chunk_id: str) -> ChunkProvenance | None:
        rows = await self._rows(_PROVENANCE + " where p.chunk_id=$1", _uuid(chunk_id))
        return _provenance(rows[0]) if rows else None

    async def list_published_chunks(
        self, *, scopes: Sequence[Scope], limit: int = 100
    ) -> tuple[ChunkProvenance, ...]:
        if not scopes or limit <= 0:
            return ()
        rows = await self._rows(
            _PROVENANCE
            + """
            where p.version_state='published' and exists (
                select 1 from unnest($1::text[],$2::text[]) as allowed(domain,equipment)
                where p.scope_domain=allowed.domain
                  and p.scope_equipment is not distinct from allowed.equipment)
            order by v.version_number,d.created_at,d.id,c.ordinal limit $3
            """,
            [s.domain for s in scopes],
            [s.equipment for s in scopes],
            limit,
        )
        return tuple(_provenance(row) for row in rows)

    async def set_version_state(
        self,
        *,
        version_id: str,
        state: DocumentVersionState,
        actor: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> DocumentVersionRecord:
        async with self._transaction() as conn:
            row = await self._locked_version(conn, version_id)
            validate_transition(DocumentVersionState(row["state"]), state, reason)
            updated = await conn.fetchrow(
                "update elsa.document_versions set state=$2 where id=$1 returning *",
                row["id"],
                state.value,
            )
            await self._event(conn, row["id"], VersionEvent(state.value), actor, reason, request_id)
            return _record(DocumentVersionRecord, updated)

    async def publish_version(
        self, *, version_id: str, actor: str, request_id: str | None = None
    ) -> DocumentVersionRecord:
        async with self._transaction() as conn:
            row = await self._locked_version(conn, version_id)
            require_publishable(DocumentVersionState(row["state"]))
            moment = await conn.fetchval("select clock_timestamp()")
            previous = await conn.fetch(
                "update elsa.document_versions set state='superseded',superseded_at=$2 where "
                "document_id=$1 and state='published' returning id",
                row["document_id"],
                moment,
            )
            for old in previous:
                await self._event(conn, old["id"], VersionEvent.SUPERSEDED, actor, None, request_id)
            updated = await conn.fetchrow(
                "update elsa.document_versions set "
                "state='published',published_at=$2,published_by=$3 where id=$1 returning *",
                row["id"],
                moment,
                _uuid(actor),
            )
            await self._event(conn, row["id"], VersionEvent.PUBLISHED, actor, None, request_id)
            return _record(DocumentVersionRecord, updated)

    @staticmethod
    async def _lock_document(conn: Any, document_id: str) -> None:
        if not await conn.fetchval(
            "select id from elsa.documents where id=$1 for update", _uuid(document_id)
        ):
            raise DocumentNotFoundError(document_id)

    async def _locked_version(self, conn: Any, version_id: str) -> Any:
        document_id = await conn.fetchval(
            "select document_id from elsa.document_versions where id=$1", _uuid(version_id)
        )
        if document_id is None:
            raise VersionNotFoundError(version_id)
        await self._lock_document(conn, str(document_id))
        return await conn.fetchrow(
            "select * from elsa.document_versions where id=$1 for update", _uuid(version_id)
        )

    @staticmethod
    async def _event(
        conn: Any,
        version_id: uuid.UUID,
        event: VersionEvent,
        actor: str,
        reason: str | None,
        request_id: str | None,
    ) -> None:
        await conn.execute(
            "insert into elsa.document_version_events "
            "(version_id,event,actor,reason,request_id) values ($1,$2,$3,$4,$5)",
            version_id,
            event.value,
            _uuid(actor),
            reason,
            request_id,
        )

    async def list_version_events(self, version_id: str) -> tuple[DocumentVersionEventRecord, ...]:
        rows = await self._rows(
            "select * from elsa.document_version_events where version_id=$1 order by seq",
            _uuid(version_id),
        )
        return tuple(_record(DocumentVersionEventRecord, row) for row in rows)

    async def check_health(self) -> None:
        await self._rows("select 1 from elsa.documents limit 1")
