"""Almacenamiento vectorial sobre PostgreSQL con pgvector.

La pieza que justifica este adaptador es `search`: el filtro de autorización
y el orden por distancia viven en **la misma consulta**. No hay un camino por
el que se recuperen vecinos globales y se filtren después en Python, porque
ese camino es exactamente lo que la regla 3 prohíbe y lo que ADR 0013 §6
razona que el índice no puede sostener por sí solo.
"""

import contextlib
import logging
from collections.abc import Iterator, Sequence
from typing import Any

import asyncpg

from elsa.core.authorization import Scope
from elsa.ports.documents import (
    ChunkProvenance,
    DocumentChunkRecord,
    DocumentRecord,
    DocumentSectionRecord,
    DocumentVersionRecord,
)
from elsa.ports.knowledge import KnowledgeUnavailableError
from elsa.ports.vectors import (
    ActiveModelError,
    EmbeddingModelRecord,
    EmbeddingModelSpec,
    EmbeddingRunRecord,
    EmbeddingRunStatus,
    ModelState,
    PendingEmbedding,
    ScoredChunk,
    VectorIntegrityError,
)

_logger = logging.getLogger(__name__)

# Espacio propio para el lock de activación, distinto del documental.
_ACTIVATION_LOCK = 0x454C5356


@contextlib.contextmanager
def _database_errors() -> Iterator[None]:
    try:
        yield
    # `InterfaceError` no desciende de `PostgresError`: es lo que asyncpg
    # lanza con un pool ya cerrado, y sin nombrarlo escaparía sin traducir.
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError) as error:
        _logger.warning("vector store failure", extra={"error": type(error).__name__})
        raise KnowledgeUnavailableError("the ELSA vector store is unavailable") from None


def _vector(values: Sequence[float]) -> str:
    """pgvector acepta el literal `[1,2,3]`; asyncpg no conoce el tipo."""
    return "[" + ",".join(repr(float(v)) for v in values) + "]"


def _model(row: Any) -> EmbeddingModelRecord:
    return EmbeddingModelRecord(
        id=str(row["id"]),
        spec=EmbeddingModelSpec(
            family=row["family"],
            model_id=row["model_id"],
            revision=row["revision"],
            dimension=row["dimension"],
            normalized=row["normalized"],
            composition_template=row["composition_template"],
            runtime=row["runtime"],
            document_prefix=row["document_prefix"],
            query_prefix=row["query_prefix"],
            similarity=row["similarity"],
            notes=row["notes"],
        ),
        state=ModelState(row["state"]),
        registered_by=str(row["registered_by"]),
        registered_at=row["registered_at"],
        activated_at=row["activated_at"],
        retired_at=row["retired_at"],
    )


def _run(row: Any) -> EmbeddingRunRecord:
    return EmbeddingRunRecord(
        id=str(row["id"]),
        model_id=str(row["model_id"]),
        status=EmbeddingRunStatus(row["status"]),
        trigger_source=row["trigger_source"],
        started_by=str(row["started_by"]),
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        total_chunks=row["total_chunks"],
        generated=row["generated"],
        reused=row["reused"],
        failed=row["failed"],
        failure_kind=row["failure_kind"],
        failure_message=row["failure_message"],
        request_id=row["request_id"],
    )


_MODEL_COLUMNS = (
    "id, family, model_id, revision, dimension, normalized, similarity, "
    "document_prefix, query_prefix, composition_template, runtime, state, "
    "registered_by, registered_at, activated_at, retired_at, notes"
)

# Recuperación exacta. Todo ocurre aquí dentro, y el orden importa:
#
#   1. el modelo activo acota qué vectores existen para la consulta;
#   2. el alcance autorizado acota qué documentos son visibles, con la
#      semántica de `core.authorization.covers`: un permiso sin equipo cubre
#      todo su dominio, uno con equipo cubre solo ese equipo;
#   3. la versión tiene que estar publicada;
#   4. y solo entonces se ordena por distancia.
#
# El `limit` se aplica sobre el conjunto ya filtrado, así que los `k` que
# salen son los `k` mejores **de lo autorizado**, no los `k` mejores del
# corpus recortados después.
_SEARCH = """
select
  r.*,
  c  as chunk,
  v  as version,
  d  as document,
  s  as section,
  r.embedding <=> $1::vector as distance
from elsa.chunk_embedding_retrieval as r
join elsa.document_chunks   as c on c.id = r.chunk_id
join elsa.document_versions as v on v.id = r.version_id
join elsa.documents         as d on d.id = r.document_id
left join elsa.document_sections as s on s.id = c.section_id
where r.model_id = $2
  and r.version_state = 'published'
  and exists (
    select 1 from unnest($3::text[], $4::text[]) as allowed(domain, equipment)
    where r.scope_domain = allowed.domain
      and (allowed.equipment is null or r.scope_equipment = allowed.equipment))
order by distance, c.ordinal, c.id
limit $5
"""


class PostgresVectorStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(
        cls, dsn: str, *, min_size: int = 1, max_size: int = 10, timeout_seconds: float = 30.0
    ) -> "PostgresVectorStore":
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
    async def _transaction(self) -> Any:
        with _database_errors():
            async with self._pool.acquire() as conn, conn.transaction():
                yield conn

    # ---------------------------------------------------------------- modelos

    async def register_model(self, spec: EmbeddingModelSpec, *, actor: str) -> EmbeddingModelRecord:
        async with self._transaction() as conn:
            try:
                row = await conn.fetchrow(
                    "insert into elsa.embedding_models "
                    "(family, model_id, revision, dimension, normalized, similarity, "
                    " document_prefix, query_prefix, composition_template, runtime, "
                    " registered_by, notes) "
                    "values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) "
                    f"returning {_MODEL_COLUMNS}",
                    spec.family,
                    spec.model_id,
                    spec.revision,
                    spec.dimension,
                    spec.normalized,
                    spec.similarity,
                    spec.document_prefix,
                    spec.query_prefix,
                    spec.composition_template,
                    spec.runtime,
                    actor,
                    spec.notes,
                )
            except asyncpg.UniqueViolationError as error:
                raise VectorIntegrityError(
                    "this vector space is already registered: same model, revision, "
                    "dimension, prefixes, template and normalisation"
                ) from error
            except asyncpg.CheckViolationError as error:
                raise VectorIntegrityError(str(error).split("\n")[0]) from error
        return _model(row)

    async def get_model(self, model_id: str) -> EmbeddingModelRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_MODEL_COLUMNS} from elsa.embedding_models where id = $1", model_id
            )
        return None if row is None else _model(row)

    async def find_model(self, spec: EmbeddingModelSpec) -> EmbeddingModelRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_MODEL_COLUMNS} from elsa.embedding_models "
                "where model_id=$1 and revision=$2 and dimension=$3 and document_prefix=$4 "
                "  and query_prefix=$5 and composition_template=$6 and normalized=$7",
                spec.model_id,
                spec.revision,
                spec.dimension,
                spec.document_prefix,
                spec.query_prefix,
                spec.composition_template,
                spec.normalized,
            )
        return None if row is None else _model(row)

    async def list_models(self) -> tuple[EmbeddingModelRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_MODEL_COLUMNS} from elsa.embedding_models order by registered_at, id"
            )
        return tuple(_model(row) for row in rows)

    async def get_active_model(self) -> EmbeddingModelRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_MODEL_COLUMNS} from elsa.embedding_models where state = 'active'"
            )
        return None if row is None else _model(row)

    async def activate_model(self, *, model_id: str, actor: str) -> EmbeddingModelRecord:
        """Una sola transacción cambia cuál es el modelo activo.

        El lock serializa dos activaciones concurrentes; el índice único
        parcial es el respaldo que la base impone aunque el lock fallara.
        """
        async with self._transaction() as conn:
            await conn.execute("select pg_advisory_xact_lock($1)", _ACTIVATION_LOCK)
            current = await conn.fetchrow(
                "select id, state, retired_at from elsa.embedding_models where id = $1 for update",
                model_id,
            )
            if current is None:
                raise ActiveModelError(f"unknown embedding model: {model_id}")
            if current["retired_at"] is not None:
                raise ActiveModelError("a retired model cannot be activated again")
            if current["state"] == ModelState.ACTIVE.value:
                row = await conn.fetchrow(
                    f"select {_MODEL_COLUMNS} from elsa.embedding_models where id = $1", model_id
                )
                return _model(row)
            # Desactivar el anterior y activar el nuevo, en la misma
            # transacción: en ningún instante visible hay dos activos ni
            # ninguno. Los vectores del anterior **no se tocan**: volver atrás
            # es activar otra vez, no regenerar (ADR 0013 §5).
            await conn.execute(
                "update elsa.embedding_models "
                "set state='registered', activated_at=null where state='active'"
            )
            row = await conn.fetchrow(
                "update elsa.embedding_models set state='active', activated_at=now() "
                f"where id=$1 returning {_MODEL_COLUMNS}",
                model_id,
            )
        _logger.info("embedding model activated", extra={"model_id": model_id, "actor": actor})
        return _model(row)

    async def retire_model(self, *, model_id: str, actor: str) -> EmbeddingModelRecord:
        async with self._transaction() as conn:
            await conn.execute("select pg_advisory_xact_lock($1)", _ACTIVATION_LOCK)
            row = await conn.fetchrow(
                "update elsa.embedding_models "
                "set state='retired', activated_at=null, retired_at=now() "
                f"where id=$1 returning {_MODEL_COLUMNS}",
                model_id,
            )
            if row is None:
                raise ActiveModelError(f"unknown embedding model: {model_id}")
        _logger.info("embedding model retired", extra={"model_id": model_id, "actor": actor})
        return _model(row)

    # --------------------------------------------------------------- corridas

    async def start_run(
        self,
        *,
        model_id: str,
        started_by: str,
        trigger_source: str = "manual",
        total_chunks: int = 0,
        request_id: str | None = None,
    ) -> EmbeddingRunRecord:
        async with self._transaction() as conn:
            try:
                row = await conn.fetchrow(
                    "insert into elsa.embedding_runs "
                    "(model_id, started_by, trigger_source, total_chunks, request_id) "
                    "values ($1,$2,$3,$4,$5) returning *",
                    model_id,
                    started_by,
                    trigger_source,
                    total_chunks,
                    request_id,
                )
            except asyncpg.ForeignKeyViolationError as error:
                raise VectorIntegrityError(f"unknown embedding model: {model_id}") from error
        return _run(row)

    async def finish_run(
        self, *, run_id: str, generated: int, reused: int, failed: int = 0
    ) -> EmbeddingRunRecord:
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                "update elsa.embedding_runs set status='completed', finished_at=now(), "
                "generated=$2, reused=$3, failed=$4 where id=$1 and status='running' "
                "returning *",
                run_id,
                generated,
                reused,
                failed,
            )
            if row is None:
                raise VectorIntegrityError(f"run {run_id} is not running")
        return _run(row)

    async def fail_run(
        self, *, run_id: str, failure_kind: str, failure_message: str
    ) -> EmbeddingRunRecord:
        async with self._transaction() as conn:
            row = await conn.fetchrow(
                "update elsa.embedding_runs set status='failed', finished_at=now(), "
                "failure_kind=$2, failure_message=$3 where id=$1 and status='running' "
                "returning *",
                run_id,
                failure_kind,
                failure_message,
            )
            if row is None:
                raise VectorIntegrityError(f"run {run_id} is not running")
        return _run(row)

    async def get_run(self, run_id: str) -> EmbeddingRunRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                "select * from elsa.embedding_runs where id = $1", run_id
            )
        return None if row is None else _run(row)

    # --------------------------------------------------------------- vectores

    async def store_embeddings(
        self, *, run_id: str, embeddings: Sequence[PendingEmbedding]
    ) -> tuple[int, int]:
        """Escribe los vectores de una corrida, en **una sola transacción**.

        O entran todos o no entra ninguno: un fallo a mitad no puede dejar la
        corrida diciendo que generó más de lo que hay.
        """
        if not embeddings:
            return (0, 0)
        generated = reused = 0
        async with self._transaction() as conn:
            run = await conn.fetchrow(
                "select model_id, status from elsa.embedding_runs where id=$1 for update", run_id
            )
            if run is None:
                raise VectorIntegrityError(f"unknown embedding run: {run_id}")
            if run["status"] != EmbeddingRunStatus.RUNNING.value:
                raise VectorIntegrityError(f"run {run_id} is not running")
            model_id = run["model_id"]
            dimension = await conn.fetchval(
                "select dimension from elsa.embedding_models where id=$1", model_id
            )
            for item in embeddings:
                existing = await conn.fetchval(
                    "select embedded_sha256 from elsa.document_chunk_embeddings "
                    "where chunk_id=$1 and model_id=$2",
                    item.chunk_id,
                    model_id,
                )
                # Idempotencia por el hash del texto embebido: mismo chunk,
                # mismo texto compuesto, mismo modelo → no se recalcula.
                if existing == item.embedded_sha256:
                    reused += 1
                    continue
                try:
                    await conn.execute(
                        "insert into elsa.document_chunk_embeddings "
                        "(chunk_id, model_id, version_id, run_id, dimension, embedding, "
                        " embedded_sha256, content_sha256) "
                        "values ($1,$2,$3,$4,$5,$6::vector,$7,$8) "
                        "on conflict (chunk_id, model_id) do update set "
                        "  version_id=excluded.version_id, run_id=excluded.run_id, "
                        "  embedding=excluded.embedding, "
                        "  embedded_sha256=excluded.embedded_sha256, "
                        "  content_sha256=excluded.content_sha256, "
                        "  created_at=now(), state='current'",
                        item.chunk_id,
                        model_id,
                        item.version_id,
                        run_id,
                        dimension,
                        _vector(item.embedding),
                        item.embedded_sha256,
                        item.content_sha256,
                    )
                except (
                    asyncpg.CheckViolationError,
                    asyncpg.ForeignKeyViolationError,
                    asyncpg.DataError,
                ) as error:
                    raise VectorIntegrityError(str(error).split("\n")[0]) from error
                generated += 1
        return (generated, reused)

    async def stale_chunks(
        self, *, model_id: str, expected: Sequence[tuple[str, str]]
    ) -> tuple[str, ...]:
        if not expected:
            return ()
        with _database_errors():
            rows = await self._pool.fetch(
                "select w.chunk_id from unnest($2::uuid[], $3::text[]) as w(chunk_id, sha) "
                "left join elsa.document_chunk_embeddings e "
                "  on e.chunk_id = w.chunk_id and e.model_id = $1 "
                "where e.chunk_id is null or e.embedded_sha256 is distinct from w.sha",
                model_id,
                [c for c, _ in expected],
                [s for _, s in expected],
            )
        return tuple(str(row["chunk_id"]) for row in rows)

    # ------------------------------------------------------------ recuperación

    async def search(
        self,
        *,
        query_embedding: Sequence[float],
        scopes: Sequence[Scope],
        limit: int = 10,
    ) -> tuple[ScoredChunk, ...]:
        if not scopes or limit <= 0:
            return ()
        active = await self.get_active_model()
        if active is None:
            raise ActiveModelError("no embedding model is active: retrieval is unavailable")
        if len(query_embedding) != active.spec.dimension:
            raise VectorIntegrityError(
                f"query vector has {len(query_embedding)} dimensions, "
                f"the active model has {active.spec.dimension}"
            )
        with _database_errors():
            rows = await self._pool.fetch(
                _SEARCH,
                _vector(query_embedding),
                active.id,
                [s.domain for s in scopes],
                [s.equipment for s in scopes],
                limit,
            )
        return tuple(
            ScoredChunk(
                provenance=ChunkProvenance(
                    chunk=_document_record(DocumentChunkRecord, row["chunk"]),
                    version=_document_record(DocumentVersionRecord, row["version"]),
                    document=_document_record(
                        DocumentRecord, row["document"], asset_code=row["scope_equipment"]
                    ),
                    section=(
                        None
                        if row["section"] is None
                        else _document_record(DocumentSectionRecord, row["section"])
                    ),
                    source_sha256=row["source_sha256"],
                    source_storage_key=row["source_storage_key"],
                ),
                distance=float(row["distance"]),
                model_id=str(row["model_id"]),
            )
            for row in rows
        )

    async def check_health(self) -> None:
        with _database_errors():
            await self._pool.fetchval("select 1")


def _document_record[T](cls: type[T], row: Any, **extra: Any) -> T:
    """Reconstruye un registro documental desde una fila compuesta.

    Reutiliza la conversión del adaptador documental: el modelo de datos de la
    procedencia es suyo, y duplicarlo aquí dejaría dos verdades.
    """
    from elsa.adapters.postgres_documents import _record

    return _record(cls, row, **extra)
