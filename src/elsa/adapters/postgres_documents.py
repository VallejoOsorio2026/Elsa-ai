"""Repositorio documental sobre Supabase ELSA (PostgreSQL).

Implementación real de ``DocumentRepositoryPort``. Accede con la credencial
de servicio del backend, que nunca sale de él (ADR 0002). El esquema lo
definen las migraciones versionadas bajo ``supabase/migrations/``; este
adaptador **no crea ni altera estructura**.

Tres decisiones gobiernan el archivo, y son las mismas que las de
``postgres_knowledge.py`` porque el problema es el mismo:

- **Las operaciones compuestas son una transacción.** Guardar una versión
  escribe la versión, sus secciones, sus chunks y el cierre de la ejecución
  de ingesta. O queda todo o no queda nada: una versión con la mitad de sus
  chunks sería una mentira sobre lo que dice el documento, y la recuperación
  no tendría forma de notarlo.
- **La concurrencia la resuelve la base, no el proceso.** Numerar una
  versión y publicar toman un cerrojo consultivo sobre el documento, de modo
  que dos peticiones simultáneas se serializan aunque vengan de dos
  instancias del backend. Un cerrojo en memoria de Python no protegería nada
  en cuanto haya más de un proceso.
- **La base es la única verdad.** Este adaptador no cachea nada entre
  llamadas. No hay un segundo estado en memoria que pueda divergir.

Sobre la procedencia: se reconstruye con **joins explícitos**, no leyendo
``elsa.document_chunk_provenance``. No es desconfianza hacia la vista —que
desde el Bloque 4.1 declara ``security_invoker = true``— sino que la vista no
expone todas las columnas del chunk (``char_length``, ``overlap_chars``,
``boundary_reason``, ``index_in_section``…), así que no basta para
reconstruir el registro completo del puerto. La vista sigue existiendo para
diagnóstico y para consultas de operación.
"""

import contextlib
import json
import logging
import uuid
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import asyncpg

from elsa.core.authorization import Scope
from elsa.core.versioning import ChangeKind
from elsa.documents.model import ChunkKind
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
    KnowledgeUnavailableError,
    NotPublishableError,
    VersionEvent,
    VersionNotFoundError,
)

__all__ = ["AssetNotFoundError", "PostgresDocumentRepository"]

_logger = logging.getLogger("elsa.documents.postgres")

# Espacio de cerrojos consultivos propio del conocimiento documental. El
# primer argumento separa este uso del que hace `postgres_knowledge`, para
# que un documento y un activo con claves parecidas no se bloqueen entre sí.
_DOCUMENT_LOCK_SPACE = 0x454C5344

# Clases de original que pertenecen a este bloque. La restricción
# `ck_source_artifact_kind` admite además las del Bloque 2, que no son
# documentos y no deben aparecer en ninguna consulta de aquí.
_DOCUMENT_ARTIFACT_KINDS = ("document_text", "document_markdown", "document_pdf")

_DOCUMENT_COLUMNS = (
    "d.id, d.domain, d.asset_id, d.code, d.title, d.source_kind, d.language, "
    "d.description, d.is_active, d.created_at, asset.code as asset_code"
)
_DOCUMENT_FROM = (
    "from elsa.documents d left join elsa.technical_assets asset on asset.id = d.asset_id"
)
_RUN_COLUMNS = (
    "id, document_id, source_artifact_id, status, failure_kind, failure_message, "
    "request_id, started_by, started_at, finished_at, stats"
)
_VERSION_COLUMNS = (
    "id, document_id, run_id, source_artifact_id, version_number, state, content_sha256, "
    "structure_sha256, chunking_profile, chunking_parameters, extractor, extractor_version, "
    "section_count, chunk_count, created_at, published_at, published_by, superseded_at"
)
_SECTION_COLUMNS = (
    "id, version_id, parent_id, ordinal, path, parent_path, depth, title, number_label, "
    "page_start, page_end, char_start, char_end, is_preamble"
)
_CHUNK_COLUMNS = (
    "id, version_id, section_id, ordinal, structural_key, index_in_section, content, "
    "content_sha256, kind, section_path, section_title, heading_trail, page_start, page_end, "
    "block_start, block_end, char_start, char_end, token_estimate, char_length, "
    "overlap_chars, boundary_reason, oversized, change_kind, warnings"
)
_EVENT_COLUMNS = "id, seq, version_id, event, actor, reason, request_id, occurred_at"


class AssetNotFoundError(Exception):
    """El activo técnico al que se quiere atar el documento no existe.

    En PostgreSQL el activo es una fila real y la clave foránea compuesta
    ``(asset_id, domain)`` impide atar un documento a un activo de otro
    dominio. Se comprueba antes para poder dar un mensaje que diga qué falta,
    en vez de dejar que aflore una violación de clave foránea.
    """


@contextlib.contextmanager
def _database_errors() -> Iterator[None]:
    """Traduce fallos técnicos de la base a un error de disponibilidad (503).

    Los errores que el dominio sí distingue —duplicado, no encontrado, no
    publicable— se lanzan antes de llegar aquí. Lo que queda es
    infraestructura: conexión caída, timeout, disco. El detalle interno no
    sale al cliente; solo el tipo de excepción llega al log.

    ``InterfaceError`` se captura aparte porque **no desciende de**
    ``PostgresError``: un pool cerrado o una conexión rota son errores del
    cliente, no del servidor, y sin nombrarlos se escaparían sin traducir
    justo cuando la base no está.
    """
    try:
        yield
    except (
        DocumentAlreadyExistsError,
        DocumentNotFoundError,
        DuplicateSourceError,
        NotPublishableError,
        VersionNotFoundError,
        AssetNotFoundError,
    ):
        raise
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError) as exc:
        _logger.warning("document store failure", extra={"error": type(exc).__name__})
        raise KnowledgeUnavailableError("the ELSA document store is unavailable") from None


def _as_uuid(value: str | None) -> uuid.UUID | None:
    return None if value is None else uuid.UUID(value)


def _json(value: Mapping[str, Any] | None) -> str:
    """Serializa a JSON. En `stats` solo hay conteos y códigos, nunca texto."""
    return json.dumps(dict(value or {}), default=str)


def _loads(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        parsed: dict[str, Any] = json.loads(value)
        return parsed
    return dict(value)


def _lock_key(document_id: uuid.UUID) -> int:
    """Clave del cerrojo consultivo derivada del documento.

    Se toman 31 bits del UUID para que quepa en el ``int4`` que espera
    ``pg_advisory_xact_lock``. Una colisión solo serializaría de más dos
    documentos distintos, nunca de menos.
    """
    return document_id.int % 0x7FFFFFFF


def _artifact_kind(content_type: str | None, filename: str | None) -> str:
    """Clase de original con la que se registra el archivo.

    El puerto habla de tipos MIME y el esquema de clases de artefacto; la
    traducción vive aquí y no en el dominio. Lo desconocido entra como
    ``document_text``, que es lo único que este bloque sabe leer.
    """
    media = (content_type or "").split(";")[0].strip().lower()
    name = (filename or "").lower()
    if media == "application/pdf" or name.endswith(".pdf"):
        return "document_pdf"
    if media in ("text/markdown", "text/x-markdown") or name.endswith((".md", ".markdown")):
        return "document_markdown"
    return "document_text"


# ---------------------------------------------------------------------
# Conversión de filas a registros del puerto
# ---------------------------------------------------------------------


def _document(row: asyncpg.Record) -> DocumentRecord:
    return DocumentRecord(
        id=str(row["id"]),
        domain=row["domain"],
        code=row["code"],
        title=row["title"],
        source_kind=DocumentSourceKind(row["source_kind"]),
        asset_id=None if row["asset_id"] is None else str(row["asset_id"]),
        asset_code=row["asset_code"],
        language=row["language"],
        description=row["description"],
        is_active=row["is_active"],
        created_at=row["created_at"],
    )


def _run(row: asyncpg.Record) -> DocumentIngestionRunRecord:
    return DocumentIngestionRunRecord(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        source_artifact_id=str(row["source_artifact_id"]),
        status=IngestionRunStatus(row["status"]),
        started_by=str(row["started_by"]),
        started_at=row["started_at"],
        failure_kind=row["failure_kind"],
        failure_message=row["failure_message"],
        request_id=row["request_id"],
        finished_at=row["finished_at"],
        stats=_loads(row["stats"]),
    )


def _version(row: asyncpg.Record) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        id=str(row["id"]),
        document_id=str(row["document_id"]),
        run_id=str(row["run_id"]),
        source_artifact_id=str(row["source_artifact_id"]),
        version_number=row["version_number"],
        state=DocumentVersionState(row["state"]),
        content_sha256=row["content_sha256"],
        structure_sha256=row["structure_sha256"],
        chunking_profile=row["chunking_profile"],
        chunking_parameters=_loads(row["chunking_parameters"]),
        extractor=row["extractor"],
        extractor_version=row["extractor_version"],
        created_at=row["created_at"],
        published_at=row["published_at"],
        published_by=None if row["published_by"] is None else str(row["published_by"]),
        superseded_at=row["superseded_at"],
        section_count=row["section_count"],
        chunk_count=row["chunk_count"],
    )


def _section(row: asyncpg.Record) -> DocumentSectionRecord:
    return DocumentSectionRecord(
        id=str(row["id"]),
        version_id=str(row["version_id"]),
        ordinal=row["ordinal"],
        path=row["path"],
        depth=row["depth"],
        title=row["title"],
        parent_id=None if row["parent_id"] is None else str(row["parent_id"]),
        parent_path=row["parent_path"],
        number_label=row["number_label"],
        page_start=row["page_start"],
        page_end=row["page_end"],
        char_start=row["char_start"],
        char_end=row["char_end"],
        is_preamble=row["is_preamble"],
    )


def _chunk(row: asyncpg.Record) -> DocumentChunkRecord:
    return DocumentChunkRecord(
        id=str(row["id"]),
        version_id=str(row["version_id"]),
        ordinal=row["ordinal"],
        structural_key=row["structural_key"],
        content=row["content"],
        content_sha256=row["content_sha256"],
        kind=ChunkKind(row["kind"]),
        section_id=None if row["section_id"] is None else str(row["section_id"]),
        section_path=row["section_path"],
        section_title=row["section_title"],
        index_in_section=row["index_in_section"],
        heading_trail=tuple(row["heading_trail"] or ()),
        page_start=row["page_start"],
        page_end=row["page_end"],
        block_start=row["block_start"],
        block_end=row["block_end"],
        char_start=row["char_start"],
        char_end=row["char_end"],
        token_estimate=row["token_estimate"],
        char_length=row["char_length"],
        overlap_chars=row["overlap_chars"],
        boundary_reason=row["boundary_reason"],
        oversized=row["oversized"],
        warnings=tuple(row["warnings"] or ()),
        change_kind=None if row["change_kind"] is None else ChangeKind(row["change_kind"]),
    )


def _event(row: asyncpg.Record) -> DocumentVersionEventRecord:
    return DocumentVersionEventRecord(
        id=str(row["id"]),
        seq=row["seq"],
        version_id=str(row["version_id"]),
        event=VersionEvent(row["event"]),
        actor=str(row["actor"]),
        occurred_at=row["occurred_at"],
        reason=row["reason"],
        request_id=row["request_id"],
    )


# ---------------------------------------------------------------------
# Repositorio
# ---------------------------------------------------------------------


class PostgresDocumentRepository:
    """Conocimiento documental de ELSA persistido en Supabase ELSA."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(
        cls,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
        timeout_seconds: float = 30.0,
    ) -> "PostgresDocumentRepository":
        """Abre el pool de conexiones. La cadena nunca se registra."""
        with _database_errors():
            pool = await asyncpg.create_pool(
                dsn, min_size=min_size, max_size=max_size, command_timeout=timeout_seconds
            )
        if pool is None:  # pragma: no cover - asyncpg solo devuelve None sin `loop`
            raise KnowledgeUnavailableError("could not create the connection pool")
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

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
        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                asset_id = None
                if asset_code is not None:
                    # El activo tiene que existir **en este dominio**. La
                    # clave foránea compuesta lo impondría igualmente, pero
                    # aflorando como violación de integridad; comprobarlo
                    # aquí permite decir qué falta.
                    asset_id = await connection.fetchval(
                        "select id from elsa.technical_assets where code = $1 and domain = $2",
                        asset_code,
                        domain,
                    )
                    if asset_id is None:
                        raise AssetNotFoundError(
                            f"no technical asset {asset_code!r} in domain {domain!r}"
                        )
                try:
                    row = await connection.fetchrow(
                        "insert into elsa.documents "
                        "(domain, asset_id, code, title, source_kind, language, description) "
                        "values ($1, $2, $3, $4, $5, $6, $7) returning id",
                        domain,
                        asset_id,
                        code,
                        title,
                        source_kind.value,
                        language,
                        description,
                    )
                except asyncpg.UniqueViolationError:
                    # La unicidad la impone `unique (domain, code)`, no una
                    # comprobación previa: dos peticiones simultáneas pasan
                    # las dos por la comprobación y solo una sobrevive aquí.
                    raise DocumentAlreadyExistsError(
                        f"document {code!r} already exists in {domain!r}"
                    ) from None
                assert row is not None  # noqa: S101 - `insert ... returning` siempre devuelve
                created = await connection.fetchrow(
                    f"select {_DOCUMENT_COLUMNS} {_DOCUMENT_FROM} where d.id = $1", row["id"]
                )
                assert created is not None  # noqa: S101
                return _document(created)

    async def get_document(self, *, domain: str, code: str) -> DocumentRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_DOCUMENT_COLUMNS} {_DOCUMENT_FROM} where d.domain = $1 and d.code = $2",
                domain,
                code,
            )
        return None if row is None else _document(row)

    async def get_document_by_id(self, document_id: str) -> DocumentRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_DOCUMENT_COLUMNS} {_DOCUMENT_FROM} where d.id = $1",
                _as_uuid(document_id),
            )
        return None if row is None else _document(row)

    async def list_documents(
        self, *, domain: str | None = None, asset_code: str | None = None
    ) -> tuple[DocumentRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_DOCUMENT_COLUMNS} {_DOCUMENT_FROM} "
                "where ($1::text is null or d.domain = $1) "
                "  and ($2::text is null or asset.code = $2) "
                "order by d.domain, d.code",
                domain,
                asset_code,
            )
        return tuple(_document(row) for row in rows)

    # -----------------------------------------------------------------
    # Ingesta
    # -----------------------------------------------------------------

    async def find_run_by_source(self, sha256: str) -> DocumentIngestionRunRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {', '.join('run.' + c for c in _RUN_COLUMNS.split(', '))} "
                "from elsa.document_ingestion_runs run "
                "join elsa.source_artifacts art on art.id = run.source_artifact_id "
                "where art.sha256 = $1 and art.kind = any($2::text[]) "
                "order by run.started_at limit 1",
                sha256,
                list(_DOCUMENT_ARTIFACT_KINDS),
            )
        return None if row is None else _run(row)

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
        document_uuid = _as_uuid(document_id)
        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                exists = await connection.fetchval(
                    "select 1 from elsa.documents where id = $1", document_uuid
                )
                if exists is None:
                    raise DocumentNotFoundError(document_id)

                previous = await connection.fetchrow(
                    "select run.id from elsa.document_ingestion_runs run "
                    "join elsa.source_artifacts art on art.id = run.source_artifact_id "
                    "where art.sha256 = $1 and art.kind = any($2::text[]) limit 1",
                    sha256,
                    list(_DOCUMENT_ARTIFACT_KINDS),
                )
                if previous is not None:
                    raise DuplicateSourceError(
                        "this exact file has already been ingested",
                        existing_import_id=str(previous["id"]),
                    )
                try:
                    artifact_id = await connection.fetchval(
                        "insert into elsa.source_artifacts "
                        "(kind, sha256, byte_size, storage_key, uploaded_by, "
                        " original_filename, content_type) "
                        "values ($1, $2, $3, $4, $5, $6, $7) returning id",
                        _artifact_kind(content_type, original_filename),
                        sha256,
                        byte_size,
                        storage_key,
                        _as_uuid(uploaded_by),
                        original_filename,
                        content_type,
                    )
                except asyncpg.UniqueViolationError:
                    # `unique (kind, sha256)` es el árbitro de la carrera:
                    # dos peticiones simultáneas con el mismo archivo pasan
                    # las dos por la comprobación anterior y solo una llega
                    # a registrar el original.
                    raise DuplicateSourceError(
                        "this exact file has already been ingested"
                    ) from None

                row = await connection.fetchrow(
                    "insert into elsa.document_ingestion_runs "
                    "(document_id, source_artifact_id, status, started_by, request_id) "
                    f"values ($1, $2, 'received', $3, $4) returning {_RUN_COLUMNS}",
                    document_uuid,
                    artifact_id,
                    _as_uuid(uploaded_by),
                    request_id,
                )
                assert row is not None  # noqa: S101
                return _run(row)

    async def fail_ingestion_run(
        self,
        *,
        run_id: str,
        failure_kind: str,
        failure_message: str,
        stats: Mapping[str, object] | None = None,
    ) -> DocumentIngestionRunRecord:
        with _database_errors():
            # Cerrar como fallida no toca ninguna versión: la publicada
            # sigue publicada y la anterior sigue siendo la última válida.
            row = await self._pool.fetchrow(
                "update elsa.document_ingestion_runs set status = 'failed', "
                "failure_kind = $2, failure_message = $3, finished_at = now(), stats = $4::jsonb "
                f"where id = $1 returning {_RUN_COLUMNS}",
                _as_uuid(run_id),
                failure_kind,
                failure_message,
                _json(stats),
            )
        if row is None:
            raise VersionNotFoundError(run_id)
        return _run(row)

    async def get_ingestion_run(self, run_id: str) -> DocumentIngestionRunRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_RUN_COLUMNS} from elsa.document_ingestion_runs where id = $1",
                _as_uuid(run_id),
            )
        return None if row is None else _run(row)

    async def list_ingestion_runs(
        self, document_id: str, *, limit: int = 50
    ) -> tuple[DocumentIngestionRunRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_RUN_COLUMNS} from elsa.document_ingestion_runs "
                "where document_id = $1 order by started_at desc limit $2",
                _as_uuid(document_id),
                limit,
            )
        return tuple(_run(row) for row in rows)

    # -----------------------------------------------------------------
    # Versiones
    # -----------------------------------------------------------------

    async def store_version(
        self, data: DocumentVersionInput, *, actor: str, request_id: str | None = None
    ) -> DocumentVersionRecord:
        """Escribe la versión entera —secciones y chunks— en una transacción.

        Entra siempre como ``pending_validation``: nunca se publica sola.
        """
        document_uuid = _as_uuid(data.document_id)
        assert document_uuid is not None  # noqa: S101 - el puerto exige el documento
        structure = data.structure

        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                exists = await connection.fetchval(
                    "select 1 from elsa.documents where id = $1", document_uuid
                )
                if exists is None:
                    raise DocumentNotFoundError(data.document_id)
                run_exists = await connection.fetchval(
                    "select 1 from elsa.document_ingestion_runs where id = $1",
                    _as_uuid(data.run_id),
                )
                if run_exists is None:
                    raise VersionNotFoundError(data.run_id)

                # Serializa la numeración de versiones del documento: dos
                # ingestas simultáneas no pueden reclamar el mismo número.
                await connection.execute(
                    "select pg_advisory_xact_lock($1, $2)",
                    _DOCUMENT_LOCK_SPACE,
                    _lock_key(document_uuid),
                )
                next_number = await connection.fetchval(
                    "select coalesce(max(version_number), 0) + 1 "
                    "from elsa.document_versions where document_id = $1",
                    document_uuid,
                )
                version = await connection.fetchrow(
                    "insert into elsa.document_versions "
                    "(document_id, run_id, source_artifact_id, version_number, state, "
                    " content_sha256, structure_sha256, chunking_profile, chunking_parameters, "
                    " extractor, extractor_version, section_count, chunk_count) "
                    "values ($1, $2, $3, $4, 'pending_validation', $5, $6, $7, $8::jsonb, "
                    "        $9, $10, $11, $12) "
                    f"returning {_VERSION_COLUMNS}",
                    document_uuid,
                    _as_uuid(data.run_id),
                    _as_uuid(data.source_artifact_id),
                    next_number,
                    data.content_sha256,
                    structure.structure_sha256,
                    structure.policy.name,
                    _json(structure.policy.parameters()),
                    data.extractor,
                    data.extractor_version,
                    len(structure.sections),
                    len(structure.chunks),
                )
                assert version is not None  # noqa: S101
                version_id = version["id"]

                # Las secciones llegan en orden de lectura, así que el padre
                # siempre está ya insertado cuando se procesa un hijo.
                section_ids: dict[str, uuid.UUID] = {}
                for section in structure.sections:
                    section_id = await connection.fetchval(
                        "insert into elsa.document_sections "
                        "(version_id, parent_id, ordinal, path, parent_path, depth, title, "
                        " number_label, page_start, page_end, char_start, char_end, is_preamble) "
                        "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13) "
                        "returning id",
                        version_id,
                        None
                        if section.parent_path is None
                        else section_ids.get(section.parent_path),
                        section.ordinal,
                        section.path,
                        section.parent_path,
                        section.depth,
                        section.title,
                        section.number_label,
                        section.page_start,
                        section.page_end,
                        section.char_start,
                        section.char_end,
                        section.is_preamble,
                    )
                    section_ids[section.path] = section_id

                await connection.executemany(
                    "insert into elsa.document_chunks "
                    "(version_id, section_id, ordinal, structural_key, index_in_section, "
                    " content, content_sha256, kind, section_path, section_title, heading_trail, "
                    " page_start, page_end, block_start, block_end, char_start, char_end, "
                    " token_estimate, char_length, overlap_chars, boundary_reason, oversized, "
                    " change_kind, warnings) "
                    "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, "
                    "        $16, $17, $18, $19, $20, $21, $22, $23, $24)",
                    [
                        (
                            version_id,
                            None
                            if chunk.section_path is None
                            else section_ids.get(chunk.section_path),
                            chunk.ordinal,
                            chunk.structural_key,
                            chunk.index_in_section,
                            chunk.content,
                            chunk.content_sha256,
                            chunk.kind.value,
                            chunk.section_path,
                            chunk.section_title,
                            list(chunk.heading_trail),
                            chunk.page_start,
                            chunk.page_end,
                            chunk.block_start,
                            chunk.block_end,
                            chunk.char_start,
                            chunk.char_end,
                            chunk.token_estimate,
                            chunk.char_length,
                            chunk.overlap_chars,
                            chunk.boundary_reason,
                            chunk.oversized,
                            None
                            if data.changes.get(chunk.structural_key) is None
                            else data.changes[chunk.structural_key].value,
                            list(chunk.warnings),
                        )
                        for chunk in structure.chunks
                    ],
                )

                await connection.execute(
                    "update elsa.document_ingestion_runs set status = 'completed', "
                    "finished_at = now(), stats = $2::jsonb where id = $1",
                    _as_uuid(data.run_id),
                    _json(data.stats),
                )
                await self._record(
                    connection, version_id, VersionEvent.CREATED, actor, None, request_id
                )
                return _version(version)

    async def get_version(self, version_id: str) -> DocumentVersionRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_VERSION_COLUMNS} from elsa.document_versions where id = $1",
                _as_uuid(version_id),
            )
        return None if row is None else _version(row)

    async def list_versions(self, document_id: str) -> tuple[DocumentVersionRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_VERSION_COLUMNS} from elsa.document_versions "
                "where document_id = $1 order by version_number",
                _as_uuid(document_id),
            )
        return tuple(_version(row) for row in rows)

    async def get_published_version(self, document_id: str) -> DocumentVersionRecord | None:
        with _database_errors():
            # `uq_published_document_version` garantiza que hay como mucho una.
            row = await self._pool.fetchrow(
                f"select {_VERSION_COLUMNS} from elsa.document_versions "
                "where document_id = $1 and state = 'published'",
                _as_uuid(document_id),
            )
        return None if row is None else _version(row)

    async def list_sections(self, version_id: str) -> tuple[DocumentSectionRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_SECTION_COLUMNS} from elsa.document_sections "
                "where version_id = $1 order by ordinal",
                _as_uuid(version_id),
            )
        return tuple(_section(row) for row in rows)

    async def list_chunks(self, version_id: str) -> tuple[DocumentChunkRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_CHUNK_COLUMNS} from elsa.document_chunks "
                "where version_id = $1 order by ordinal",
                _as_uuid(version_id),
            )
        return tuple(_chunk(row) for row in rows)

    async def set_version_state(
        self,
        *,
        version_id: str,
        state: DocumentVersionState,
        actor: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> DocumentVersionRecord:
        if state not in (DocumentVersionState.APPROVED, DocumentVersionState.REJECTED):
            # `published` tiene su propia operación porque además reemplaza a
            # la anterior, y `superseded` no lo decide nadie: es consecuencia
            # de publicar.
            raise NotPublishableError(
                f"a version cannot be moved to {state.value} through this operation"
            )
        if state is DocumentVersionState.REJECTED and not (reason or "").strip():
            # `ck_document_event_reason` lo impondría igualmente; comprobarlo
            # aquí da el mismo error que el adaptador en memoria.
            raise ValueError("rejecting a version requires a reason")

        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                current = await connection.fetchrow(
                    "select state from elsa.document_versions where id = $1 for update",
                    _as_uuid(version_id),
                )
                if current is None:
                    raise VersionNotFoundError(version_id)
                if current["state"] == DocumentVersionState.PUBLISHED.value:
                    raise NotPublishableError("a published version cannot change state directly")
                row = await connection.fetchrow(
                    "update elsa.document_versions set state = $2 where id = $1 "
                    f"returning {_VERSION_COLUMNS}",
                    _as_uuid(version_id),
                    state.value,
                )
                assert row is not None  # noqa: S101
                await self._record(
                    connection,
                    row["id"],
                    VersionEvent(state.value),
                    actor,
                    reason,
                    request_id,
                )
                return _version(row)

    async def publish_version(
        self, *, version_id: str, actor: str, request_id: str | None = None
    ) -> DocumentVersionRecord:
        """Publica la versión y marca la anterior como reemplazada.

        Atómico y serializado: el cerrojo consultivo sobre el documento hace
        que dos publicaciones simultáneas no puedan dejar dos versiones
        vigentes ni ninguna, aunque vengan de dos instancias del backend. El
        índice parcial ``uq_published_document_version`` es el respaldo.
        """
        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                current = await connection.fetchrow(
                    "select id, document_id, state from elsa.document_versions where id = $1",
                    _as_uuid(version_id),
                )
                if current is None:
                    raise VersionNotFoundError(version_id)
                await connection.execute(
                    "select pg_advisory_xact_lock($1, $2)",
                    _DOCUMENT_LOCK_SPACE,
                    _lock_key(current["document_id"]),
                )
                # Se relee bajo el cerrojo: entre la lectura anterior y aquí
                # otra transacción pudo haber cambiado el estado.
                state = await connection.fetchval(
                    "select state from elsa.document_versions where id = $1", current["id"]
                )
                if state != DocumentVersionState.APPROVED.value:
                    # Publicar sin aprobar saltaría la validación entera. El
                    # estado no es decoración: es el permiso para publicar.
                    raise NotPublishableError(
                        f"only an approved version can be published; this one is {state}"
                    )

                superseded = await connection.fetch(
                    "update elsa.document_versions set state = 'superseded', "
                    "superseded_at = now() "
                    "where document_id = $1 and id <> $2 and state = 'published' returning id",
                    current["document_id"],
                    current["id"],
                )
                for row in superseded:
                    await self._record(
                        connection, row["id"], VersionEvent.SUPERSEDED, actor, None, request_id
                    )

                published = await connection.fetchrow(
                    "update elsa.document_versions set state = 'published', "
                    "published_at = now(), published_by = $2 where id = $1 "
                    f"returning {_VERSION_COLUMNS}",
                    current["id"],
                    _as_uuid(actor),
                )
                assert published is not None  # noqa: S101
                await self._record(
                    connection, current["id"], VersionEvent.PUBLISHED, actor, None, request_id
                )
                return _version(published)

    async def list_version_events(self, version_id: str) -> tuple[DocumentVersionEventRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_EVENT_COLUMNS} from elsa.document_version_events "
                "where version_id = $1 order by seq",
                _as_uuid(version_id),
            )
        return tuple(_event(row) for row in rows)

    # -----------------------------------------------------------------
    # Procedencia y lectura por alcance
    # -----------------------------------------------------------------

    async def get_chunk_provenance(self, chunk_id: str) -> ChunkProvenance | None:
        with _database_errors():
            async with self._pool.acquire() as connection:
                chunk_row = await connection.fetchrow(
                    f"select {_CHUNK_COLUMNS} from elsa.document_chunks where id = $1",
                    _as_uuid(chunk_id),
                )
                if chunk_row is None:
                    return None
                return await self._provenance(connection, chunk_row)

    async def list_published_chunks(
        self, *, scopes: Sequence[Scope], limit: int = 100
    ) -> tuple[ChunkProvenance, ...]:
        """Chunks de las versiones **publicadas** que caen dentro de ``scopes``.

        El filtro de alcance va en el ``where``, no en Python. No es una
        optimización: es lo que hace que no exista un instante en el que el
        proceso tenga en memoria un chunk que la persona no puede leer. La
        regla 4 del contrato —permisos antes de recuperar— se cumple en la
        consulta misma.

        Con ``scopes`` vacío se devuelve vacío sin consultar nada, que es la
        respuesta correcta para quien no tiene ningún permiso.
        """
        if not scopes:
            return ()

        # Un alcance de dominio (`equipment is None`) cubre el dominio entero
        # y cualquiera de sus activos; uno de equipo cubre solo ese equipo.
        # Es exactamente `elsa.core.authorization.covers`, expresado en SQL.
        domains_wide = [scope.domain for scope in scopes if scope.equipment is None]
        pairs = [(scope.domain, scope.equipment) for scope in scopes if scope.equipment]

        with _database_errors():
            async with self._pool.acquire() as connection:
                rows = await connection.fetch(
                    f"select {', '.join('c.' + col for col in _CHUNK_COLUMNS.split(', '))} "
                    "from elsa.document_chunks c "
                    "join elsa.document_versions v on v.id = c.version_id "
                    "join elsa.documents d on d.id = v.document_id "
                    "left join elsa.technical_assets a on a.id = d.asset_id "
                    "where v.state = 'published' "
                    "  and ( d.domain = any($1::text[]) "
                    "        or (a.code is not null "
                    "            and (d.domain, a.code) "
                    "                in (select * from unnest($2::text[], $3::text[]))) ) "
                    "order by d.domain, d.code, v.version_number, c.ordinal "
                    "limit $4",
                    domains_wide,
                    [domain for domain, _ in pairs],
                    [equipment for _, equipment in pairs],
                    limit,
                )
                return tuple([await self._provenance(connection, row) for row in rows])

    async def check_health(self) -> None:
        """Lanza :class:`KnowledgeUnavailableError` si el almacén no responde."""
        with _database_errors():
            await self._pool.fetchval("select 1")

    # -----------------------------------------------------------------
    # Interno
    # -----------------------------------------------------------------

    async def _provenance(
        self, connection: asyncpg.Connection, chunk_row: asyncpg.Record
    ) -> ChunkProvenance:
        """Reconstruye la cadena chunk -> sección -> versión -> documento."""
        version_row = await connection.fetchrow(
            f"select {_VERSION_COLUMNS} from elsa.document_versions where id = $1",
            chunk_row["version_id"],
        )
        assert version_row is not None  # noqa: S101 - clave foránea obligatoria
        document_row = await connection.fetchrow(
            f"select {_DOCUMENT_COLUMNS} {_DOCUMENT_FROM} where d.id = $1",
            version_row["document_id"],
        )
        assert document_row is not None  # noqa: S101
        section_row = None
        if chunk_row["section_id"] is not None:
            section_row = await connection.fetchrow(
                f"select {_SECTION_COLUMNS} from elsa.document_sections where id = $1",
                chunk_row["section_id"],
            )
        artifact = await connection.fetchrow(
            "select sha256, storage_key from elsa.source_artifacts where id = $1",
            version_row["source_artifact_id"],
        )
        assert artifact is not None  # noqa: S101
        return ChunkProvenance(
            chunk=_chunk(chunk_row),
            document=_document(document_row),
            version=_version(version_row),
            section=None if section_row is None else _section(section_row),
            source_sha256=artifact["sha256"],
            source_storage_key=artifact["storage_key"],
        )

    @staticmethod
    async def _record(
        connection: asyncpg.Connection,
        version_id: uuid.UUID,
        event: VersionEvent,
        actor: str,
        reason: str | None,
        request_id: str | None,
    ) -> None:
        """Añade una fila al historial. La tabla es append-only por disparador."""
        await connection.execute(
            "insert into elsa.document_version_events "
            "(version_id, event, actor, reason, request_id) values ($1, $2, $3, $4, $5)",
            version_id,
            event.value,
            _as_uuid(actor),
            reason,
            request_id,
        )
