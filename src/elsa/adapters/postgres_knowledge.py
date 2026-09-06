"""Repositorio de conocimiento técnico sobre Supabase ELSA (PostgreSQL).

Accede con la credencial de servicio del backend, que nunca sale de él
(ADR 0002). El esquema lo definen las migraciones versionadas bajo
``supabase/migrations/``; este adaptador no crea ni altera estructura.

Dos decisiones gobiernan el archivo:

- **Las operaciones compuestas son una transacción.** Guardar una versión
  del BOM crea componentes, subsistemas, renglones, AMEF, criterios y
  planos, y cierra la importación. O queda todo o no queda nada: una versión
  a medias sería una afirmación falsa sobre lo que Ingeniería aprobó.
- **La concurrencia la resuelve la base, no el proceso.** Publicar toma un
  cerrojo consultivo sobre el activo, de modo que dos publicaciones
  simultáneas se serializan aunque vengan de dos instancias del backend. Un
  cerrojo en memoria de Python no protegería nada en cuanto haya más de un
  proceso.
"""

import contextlib
import json
import logging
import uuid
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import asyncpg

from elsa.core.matching import MatchCandidate
from elsa.core.reconciliation import ReconciliationEntry
from elsa.core.review import ReviewDecision, ReviewSubject
from elsa.ingestion.model import ParsedSapSnapshot
from elsa.ports.knowledge import (
    AssetAlreadyExistsError,
    BomItemRecord,
    ComponentRecord,
    DrawingImageRecord,
    DuplicateSourceError,
    EngineeringVersionInput,
    EngineeringVersionRecord,
    FailureModeRecord,
    ImportKind,
    ImportRecord,
    ImportStatus,
    KnowledgeUnavailableError,
    NotPublishableError,
    ReconciliationItemRecord,
    ReconciliationRunRecord,
    ReviewRecord,
    SapSnapshotItemRecord,
    SapSnapshotRecord,
    SodCriterionRecord,
    SubjectNotFoundError,
    TechnicalAssetRecord,
    VersionState,
)
from elsa.ports.permissions import AdminOperation

_logger = logging.getLogger("elsa.knowledge.postgres")

# Espacio de cerrojos consultivos de la publicación. El primer argumento
# separa este uso de cualquier otro cerrojo del proyecto.
_PUBLISH_LOCK_SPACE = 0x454C5341

_ASSET_COLUMNS = "id, code, name, domain, description, is_active"
_IMPORT_COLUMNS = (
    "id, asset_id, source_artifact_id, kind, status, failure_kind, failure_message, "
    "request_id, started_by, started_at, finished_at, stats"
)
_VERSION_COLUMNS = (
    "id, asset_id, import_id, source_artifact_id, version_number, state, created_at, "
    "published_at, published_by, superseded_at"
)
_ITEM_COLUMNS = (
    "id, version_id, component_id, source_row, position, subsystem_name, component_name, "
    "sap_code, sap_code_original, technical_description, quantity, quantity_original, unit, "
    "model_reference, assembly_drawing, drawing_reference, bom_update_flag, "
    "inventory_strategy, stock_max, stock_min, source_stock, remarks, match_rule, "
    "match_confidence, change_kind, extra"
)
_AMEF_COLUMNS = (
    "id, version_id, component_id, source_row, subsystem_name, component_name, sap_code, "
    "failure_mode, effect, cause, severity, occurrence, detection, rpn, action, "
    "preventive_plan, corrective_action, remarks, match_rule, match_confidence, change_kind"
)
_SOD_COLUMNS = (
    "id, version_id, dimension, scale_value, label, description, range_low, range_high, source_row"
)
_SNAPSHOT_COLUMNS = (
    "id, asset_id, import_id, source_artifact_id, functional_location, description, "
    "valid_from, captured_at"
)
_SNAPSHOT_ITEM_COLUMNS = (
    "id, snapshot_id, source_row, entry_kind, position, sap_code, description, quantity, "
    "quantity_original, unit, parent_path, depth, extra"
)
_RUN_COLUMNS = "id, asset_id, version_id, snapshot_id, created_by, created_at, stats"
_RUN_ITEM_COLUMNS = (
    "id, run_id, classification, bom_item_id, snapshot_item_id, component_id, sap_code, "
    "engineering_quantity, sap_quantity, engineering_unit, sap_unit, "
    "engineering_description, sap_description, detail"
)
_REVIEW_COLUMNS = (
    "id, seq, asset_id, subject_kind, subject_id, subject_version_id, decision, comment, "
    "reviewer, decided_at, reverts_review_id, inherited_from_id, request_id"
)

_INSERT_ITEM = """
insert into elsa.engineering_bom_items (
    version_id, component_id, subsystem_id, source_row, position, subsystem_name,
    component_name, sap_code, sap_code_original, technical_description, quantity,
    quantity_original, unit, model_reference, assembly_drawing, drawing_reference,
    bom_update_flag, inventory_strategy, stock_max, stock_min, source_stock, remarks,
    match_rule, match_confidence, change_kind, extra
) values (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13,
    $14, $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26
)
"""

_INSERT_AUDIT = """
insert into elsa.admin_audit_log (
    actor_external_user_id, subject_external_user_id, operation,
    scope_domain, scope_equipment, request_id, details
) values ($1, $2, $3, $4, $5, $6, $7)
"""


@contextlib.contextmanager
def _database_errors() -> Iterator[None]:
    """Traduce fallos técnicos de la base a un error de disponibilidad (503)."""
    try:
        yield
    except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
        _logger.warning("knowledge store failure", extra={"error": type(exc).__name__})
        raise KnowledgeUnavailableError("the ELSA knowledge store is unavailable") from None


def _as_uuid(value: str | None) -> uuid.UUID | None:
    return None if value is None else uuid.UUID(value)


def _json(value: Mapping[str, Any] | None) -> str:
    """Serializa a JSON. Solo se guardan conteos y claves, nunca contenido."""
    return json.dumps(dict(value or {}), default=str)


def _loads(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        parsed: dict[str, Any] = json.loads(value)
        return parsed
    return dict(value)


def _lock_key(asset_id: uuid.UUID) -> int:
    """Clave del cerrojo consultivo derivada del activo.

    Se toman 31 bits del UUID para que quepa en el ``int4`` que espera
    ``pg_advisory_xact_lock``. Una colisión solo serializaría de más dos
    activos distintos, nunca de menos.
    """
    return asset_id.int % 0x7FFFFFFF


class PostgresKnowledgeRepository:
    """Conocimiento técnico de ELSA persistido en Supabase ELSA."""

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
    ) -> "PostgresKnowledgeRepository":
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
    # Activos
    # -----------------------------------------------------------------

    async def list_assets(self) -> tuple[TechnicalAssetRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_ASSET_COLUMNS} from elsa.technical_assets order by code"
            )
        return tuple(_asset(row) for row in rows)

    async def get_asset(self, code: str) -> TechnicalAssetRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_ASSET_COLUMNS} from elsa.technical_assets where code = $1", code
            )
        return None if row is None else _asset(row)

    async def create_asset(
        self, *, code: str, name: str, domain: str, description: str | None = None
    ) -> TechnicalAssetRecord:
        with _database_errors():
            try:
                row = await self._pool.fetchrow(
                    "insert into elsa.technical_assets (code, name, domain, description) "
                    f"values ($1, $2, $3, $4) returning {_ASSET_COLUMNS}",
                    code,
                    name,
                    domain,
                    description,
                )
            except asyncpg.UniqueViolationError:
                raise AssetAlreadyExistsError(code) from None
        assert row is not None  # noqa: S101 - `returning` siempre devuelve fila
        return _asset(row)

    # -----------------------------------------------------------------
    # Ingesta
    # -----------------------------------------------------------------

    async def find_import_by_source(self, *, kind: str, sha256: str) -> ImportRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select i.{', i.'.join(_IMPORT_COLUMNS.split(', '))} from elsa.imports i "
                "join elsa.source_artifacts a on a.id = i.source_artifact_id "
                "where a.kind = $1 and a.sha256 = $2 "
                "order by i.started_at limit 1",
                kind,
                sha256,
            )
        return None if row is None else _import(row)

    async def start_import(
        self,
        *,
        asset_id: str,
        kind: ImportKind,
        sha256: str,
        byte_size: int,
        storage_key: str,
        uploaded_by: str,
        original_filename: str | None = None,
        content_type: str | None = None,
        request_id: str | None = None,
    ) -> ImportRecord:
        artifact_kind = (
            "engineering_bom_xlsx" if kind is ImportKind.ENGINEERING_BOM else "sap_bom_htm"
        )
        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                try:
                    artifact = await connection.fetchrow(
                        "insert into elsa.source_artifacts "
                        "(kind, sha256, byte_size, original_filename, content_type, "
                        " storage_key, uploaded_by) "
                        "values ($1, $2, $3, $4, $5, $6, $7) returning id",
                        artifact_kind,
                        sha256,
                        byte_size,
                        original_filename,
                        content_type,
                        storage_key,
                        _as_uuid(uploaded_by),
                    )
                except asyncpg.UniqueViolationError:
                    # La unicidad la impone la base: dos peticiones con el
                    # mismo archivo llegan hasta aquí y solo una sobrevive.
                    existing = await self.find_import_by_source(kind=artifact_kind, sha256=sha256)
                    raise DuplicateSourceError(
                        "this exact file has already been imported",
                        existing_import_id=None if existing is None else existing.id,
                    ) from None

                assert artifact is not None  # noqa: S101
                row = await connection.fetchrow(
                    "insert into elsa.imports "
                    "(source_artifact_id, asset_id, kind, status, request_id, started_by) "
                    f"values ($1, $2, $3, 'processing', $4, $5) returning {_IMPORT_COLUMNS}",
                    artifact["id"],
                    _as_uuid(asset_id),
                    kind.value,
                    request_id,
                    _as_uuid(uploaded_by),
                )
                await connection.execute(
                    _INSERT_AUDIT,
                    _as_uuid(uploaded_by),
                    _as_uuid(uploaded_by),
                    AdminOperation.SOURCE_UPLOADED.value,
                    None,
                    None,
                    request_id,
                    _json({"sha256": sha256, "kind": artifact_kind}),
                )
                assert row is not None  # noqa: S101
                return _import(row)

    async def fail_import(
        self,
        *,
        import_id: str,
        failure_kind: str,
        failure_message: str,
        actor: str,
        request_id: str | None = None,
    ) -> ImportRecord:
        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                row = await connection.fetchrow(
                    "update elsa.imports set status = 'failed', failure_kind = $2, "
                    "failure_message = $3, finished_at = now() "
                    f"where id = $1 returning {_IMPORT_COLUMNS}",
                    _as_uuid(import_id),
                    failure_kind,
                    failure_message,
                )
                if row is None:
                    raise SubjectNotFoundError(import_id)
                await connection.execute(
                    _INSERT_AUDIT,
                    _as_uuid(actor),
                    _as_uuid(actor),
                    AdminOperation.IMPORT_FAILED.value,
                    None,
                    None,
                    request_id,
                    _json({"import_id": import_id, "failure_kind": failure_kind}),
                )
                return _import(row)

    async def get_import(self, import_id: str) -> ImportRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_IMPORT_COLUMNS} from elsa.imports where id = $1", _as_uuid(import_id)
            )
        return None if row is None else _import(row)

    async def list_imports(self, asset_id: str, *, limit: int = 50) -> tuple[ImportRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_IMPORT_COLUMNS} from elsa.imports where asset_id = $1 "
                "order by started_at desc limit $2",
                _as_uuid(asset_id),
                limit,
            )
        return tuple(_import(row) for row in rows)

    # -----------------------------------------------------------------
    # Componentes
    # -----------------------------------------------------------------

    async def component_entries(self, asset_id: str) -> tuple[tuple[str, MatchCandidate], ...]:
        """Evidencia observada por componente, tal como quedó en los renglones."""
        with _database_errors():
            rows = await self._pool.fetch(
                "select distinct i.component_id, i.subsystem_name, i.component_name, "
                "  i.sap_code, i.assembly_drawing, i.drawing_reference, i.model_reference "
                "from elsa.engineering_bom_items i "
                "join elsa.engineering_bom_versions v on v.id = i.version_id "
                "where v.asset_id = $1 and i.component_id is not null",
                _as_uuid(asset_id),
            )
        return tuple(
            (
                str(row["component_id"]),
                MatchCandidate(
                    subsystem_name=row["subsystem_name"],
                    component_name=row["component_name"],
                    sap_code=row["sap_code"],
                    assembly_drawing=row["assembly_drawing"],
                    drawing_reference=row["drawing_reference"],
                    model_reference=row["model_reference"],
                ),
            )
            for row in rows
        )

    async def list_components(self, asset_id: str) -> tuple[ComponentRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                "select c.id, c.asset_id, c.subsystem_id, s.name as subsystem_name, c.retired_at "
                "from elsa.components c left join elsa.subsystems s on s.id = c.subsystem_id "
                "where c.asset_id = $1 order by c.created_at",
                _as_uuid(asset_id),
            )
        return tuple(
            ComponentRecord(
                id=str(row["id"]),
                asset_id=str(row["asset_id"]),
                subsystem_id=None if row["subsystem_id"] is None else str(row["subsystem_id"]),
                subsystem_name=row["subsystem_name"],
                retired_at=row["retired_at"],
            )
            for row in rows
        )

    # -----------------------------------------------------------------
    # Versiones de Ingeniería
    # -----------------------------------------------------------------

    async def store_engineering_version(
        self, data: EngineeringVersionInput, *, actor: str, request_id: str | None = None
    ) -> EngineeringVersionRecord:
        asset_uuid = uuid.UUID(data.asset_id)
        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                # Serializa la numeración de versiones del activo: dos
                # importaciones simultáneas no pueden reclamar el mismo número.
                await connection.execute(
                    "select pg_advisory_xact_lock($1, $2)",
                    _PUBLISH_LOCK_SPACE,
                    _lock_key(asset_uuid),
                )
                next_number = await connection.fetchval(
                    "select coalesce(max(version_number), 0) + 1 "
                    "from elsa.engineering_bom_versions where asset_id = $1",
                    asset_uuid,
                )
                version = await connection.fetchrow(
                    "insert into elsa.engineering_bom_versions "
                    "(asset_id, import_id, source_artifact_id, version_number, state) "
                    "values ($1, $2, $3, $4, 'pending_validation') "
                    f"returning {_VERSION_COLUMNS}",
                    asset_uuid,
                    _as_uuid(data.import_id),
                    _as_uuid(data.source_artifact_id),
                    next_number,
                )
                assert version is not None  # noqa: S101
                version_id = version["id"]

                subsystems: dict[str, uuid.UUID] = {}
                components_by_code: dict[str, uuid.UUID] = {}

                for resolved in data.rows:
                    row = resolved.row
                    subsystem_id = await self._ensure_subsystem(
                        connection, asset_uuid, row.subsystem_name, subsystems
                    )
                    component_id = _as_uuid(resolved.component_id)
                    if component_id is None and not resolved.ambiguous:
                        # Componente nuevo: UUID interno permanente que no
                        # depende del código SAP, del nombre ni del plano.
                        component_id = await connection.fetchval(
                            "insert into elsa.components (asset_id, subsystem_id) "
                            "values ($1, $2) returning id",
                            asset_uuid,
                            subsystem_id,
                        )
                    if component_id is not None:
                        await self._record_identifiers(
                            connection, asset_uuid, component_id, resolved.row
                        )
                        if row.sap_code:
                            components_by_code.setdefault(row.sap_code, component_id)

                    await connection.execute(
                        _INSERT_ITEM,
                        version_id,
                        component_id,
                        subsystem_id,
                        row.source_row,
                        row.position,
                        row.subsystem_name,
                        row.component_name,
                        row.sap_code,
                        row.sap_code_original,
                        row.technical_description,
                        row.quantity,
                        row.quantity_original,
                        row.unit,
                        row.model_reference,
                        row.assembly_drawing,
                        row.drawing_reference,
                        row.bom_update_flag,
                        row.inventory_strategy,
                        row.stock_max,
                        row.stock_min,
                        row.source_stock,
                        row.remarks,
                        resolved.match_rule,
                        resolved.match_confidence,
                        resolved.change_kind,
                        _json(dict(row.extra)),
                    )

                await self._store_failure_modes(
                    connection, version_id, data.failure_modes, components_by_code
                )
                await self._store_sod(connection, version_id, data.sod_criteria)
                await self._store_options(connection, version_id, data.option_rows)
                await self._store_drawings(connection, version_id, asset_uuid, data)

                stats = {
                    "bom_items": len(data.rows),
                    "failure_modes": len(data.failure_modes),
                    "sod_criteria": len(data.sod_criteria),
                    "drawing_images": len(data.drawing_images),
                }
                await connection.execute(
                    "update elsa.imports set status = 'completed', finished_at = now(), "
                    "stats = $2 where id = $1",
                    _as_uuid(data.import_id),
                    _json(stats),
                )
                await connection.execute(
                    _INSERT_AUDIT,
                    _as_uuid(actor),
                    _as_uuid(actor),
                    AdminOperation.IMPORT_COMPLETED.value,
                    None,
                    None,
                    request_id,
                    _json({"import_id": data.import_id, **{k: str(v) for k, v in stats.items()}}),
                )
                return _version(version)

    @staticmethod
    async def _ensure_subsystem(
        connection: Any,
        asset_id: uuid.UUID,
        name: str | None,
        cache: dict[str, uuid.UUID],
    ) -> uuid.UUID | None:
        if name is None:
            return None
        code = " ".join(name.strip().lower().split())
        if code in cache:
            return cache[code]
        subsystem_id = await connection.fetchval(
            "insert into elsa.subsystems (asset_id, code, name) values ($1, $2, $3) "
            "on conflict (asset_id, code) do update set name = elsa.subsystems.name "
            "returning id",
            asset_id,
            code,
            name,
        )
        cache[code] = subsystem_id
        result: uuid.UUID = subsystem_id
        return result

    @staticmethod
    async def _record_identifiers(
        connection: Any, asset_id: uuid.UUID, component_id: uuid.UUID, row: Any
    ) -> None:
        """Acumula los alias observados. Nunca sustituyen a la identidad."""
        observed: list[tuple[str, str]] = []
        if row.sap_code:
            observed.append(("sap_code", row.sap_code))
        if row.assembly_drawing and row.drawing_reference:
            observed.append(
                ("drawing_reference", f"{row.assembly_drawing}|{row.drawing_reference}")
            )
        if row.model_reference:
            observed.append(("part_number", row.model_reference))
        if row.component_name:
            observed.append(("name", row.component_name))

        for kind, value in observed:
            await connection.execute(
                "insert into elsa.component_identifiers "
                "(component_id, asset_id, kind, value, value_original) "
                "values ($1, $2, $3, $4, $5) "
                "on conflict (component_id, kind, value) "
                "do update set last_seen_at = now()",
                component_id,
                asset_id,
                kind,
                value.strip().lower(),
                value,
            )

    @staticmethod
    async def _store_failure_modes(
        connection: Any,
        version_id: uuid.UUID,
        modes: Sequence[Any],
        components_by_code: dict[str, uuid.UUID],
    ) -> None:
        for mode in modes:
            component_id = components_by_code.get(mode.sap_code) if mode.sap_code else None
            await connection.execute(
                "insert into elsa.failure_modes (version_id, component_id, source_row, "
                "subsystem_name, component_name, sap_code, failure_mode, effect, cause, "
                "severity, occurrence, detection, rpn, action, preventive_plan, "
                "corrective_action, remarks, match_rule, match_confidence) "
                "values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)",
                version_id,
                component_id,
                mode.source_row,
                mode.subsystem_name,
                mode.component_name,
                mode.sap_code,
                mode.failure_mode,
                mode.effect,
                mode.cause,
                mode.severity,
                mode.occurrence,
                mode.detection,
                # Siempre el NPR calculado por el backend, nunca el del archivo.
                mode.rpn,
                mode.action,
                mode.preventive_plan,
                mode.corrective_action,
                mode.remarks,
                "sap_code" if component_id is not None else None,
                "strong" if component_id is not None else "unresolved",
            )

    @staticmethod
    async def _store_sod(connection: Any, version_id: uuid.UUID, criteria: Sequence[Any]) -> None:
        for criterion in criteria:
            await connection.execute(
                "insert into elsa.sod_criteria (version_id, dimension, scale_value, label, "
                "description, range_low, range_high, source_row) "
                "values ($1,$2,$3,$4,$5,$6,$7,$8) "
                "on conflict (version_id, dimension, source_row) do nothing",
                version_id,
                criterion.dimension,
                criterion.scale_value,
                criterion.label,
                criterion.description,
                criterion.range_low,
                criterion.range_high,
                criterion.source_row,
            )

    @staticmethod
    async def _store_options(
        connection: Any, version_id: uuid.UUID, options: Sequence[Any]
    ) -> None:
        for option in options:
            await connection.execute(
                "insert into elsa.option_tables (version_id, table_name, option_value, "
                "description, source_row) values ($1,$2,$3,$4,$5) "
                "on conflict (version_id, table_name, source_row) do nothing",
                version_id,
                option.table_name,
                option.option_value,
                option.description,
                option.source_row,
            )

    @staticmethod
    async def _store_drawings(
        connection: Any,
        version_id: uuid.UUID,
        asset_id: uuid.UUID,
        data: EngineeringVersionInput,
    ) -> None:
        for image in data.drawing_images:
            key = data.drawing_storage_keys.get(image.sha256)
            if key is None:
                # Sin clave de almacenamiento no hay evidencia que referenciar.
                continue
            derived_id = await connection.fetchval(
                "insert into elsa.derived_artifacts (source_artifact_id, kind, sha256, "
                "byte_size, content_type, storage_key) values ($1,'drawing_image',$2,$3,$4,$5) "
                "on conflict (storage_key) do update set storage_key = "
                "elsa.derived_artifacts.storage_key returning id",
                _as_uuid(data.source_artifact_id),
                image.sha256,
                len(image.content),
                image.content_type,
                key,
            )
            drawing_id = None
            if image.drawing_number is not None:
                drawing_id = await connection.fetchval(
                    "insert into elsa.drawings (asset_id, number) values ($1, $2) "
                    "on conflict (asset_id, number) do update set number = "
                    "elsa.drawings.number returning id",
                    asset_id,
                    image.drawing_number,
                )
            await connection.execute(
                "insert into elsa.drawing_images (version_id, derived_artifact_id, drawing_id, "
                "sheet_name, anchor, width_px, height_px, association_status, association_rule) "
                "values ($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                version_id,
                derived_id,
                drawing_id,
                image.sheet_name,
                image.anchor,
                image.width_px,
                image.height_px,
                "resolved" if drawing_id is not None else "pending_review",
                image.association_rule,
            )

    async def get_version(self, version_id: str) -> EngineeringVersionRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_VERSION_COLUMNS} from elsa.engineering_bom_versions where id = $1",
                _as_uuid(version_id),
            )
        return None if row is None else _version(row)

    async def list_versions(self, asset_id: str) -> tuple[EngineeringVersionRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_VERSION_COLUMNS} from elsa.engineering_bom_versions "
                "where asset_id = $1 order by version_number desc",
                _as_uuid(asset_id),
            )
        return tuple(_version(row) for row in rows)

    async def get_published_version(self, asset_id: str) -> EngineeringVersionRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_VERSION_COLUMNS} from elsa.engineering_bom_versions "
                "where asset_id = $1 and state = 'published'",
                _as_uuid(asset_id),
            )
        return None if row is None else _version(row)

    async def list_version_items(self, version_id: str) -> tuple[BomItemRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_ITEM_COLUMNS} from elsa.engineering_bom_items "
                "where version_id = $1 order by source_row",
                _as_uuid(version_id),
            )
        return tuple(_item(row) for row in rows)

    async def list_failure_modes(self, version_id: str) -> tuple[FailureModeRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_AMEF_COLUMNS} from elsa.failure_modes "
                "where version_id = $1 order by source_row",
                _as_uuid(version_id),
            )
        return tuple(_failure_mode(row) for row in rows)

    async def list_sod_criteria(self, version_id: str) -> tuple[SodCriterionRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_SOD_COLUMNS} from elsa.sod_criteria "
                "where version_id = $1 order by dimension, source_row",
                _as_uuid(version_id),
            )
        return tuple(
            SodCriterionRecord(
                id=str(row["id"]),
                version_id=str(row["version_id"]),
                dimension=str(row["dimension"]),
                source_row=int(row["source_row"]),
                scale_value=row["scale_value"],
                label=row["label"],
                description=row["description"],
                range_low=row["range_low"],
                range_high=row["range_high"],
            )
            for row in rows
        )

    async def list_drawing_images(self, version_id: str) -> tuple[DrawingImageRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                "select di.id, di.version_id, di.derived_artifact_id, da.storage_key, "
                "  da.sha256, di.drawing_id, d.number as drawing_number, "
                "  di.association_status, di.association_rule, di.sheet_name, di.anchor, "
                "  di.width_px, di.height_px "
                "from elsa.drawing_images di "
                "join elsa.derived_artifacts da on da.id = di.derived_artifact_id "
                "left join elsa.drawings d on d.id = di.drawing_id "
                "where di.version_id = $1 order by di.created_at",
                _as_uuid(version_id),
            )
        return tuple(
            DrawingImageRecord(
                id=str(row["id"]),
                version_id=str(row["version_id"]),
                derived_artifact_id=str(row["derived_artifact_id"]),
                storage_key=str(row["storage_key"]),
                sha256=str(row["sha256"]),
                association_status=str(row["association_status"]),
                drawing_id=None if row["drawing_id"] is None else str(row["drawing_id"]),
                drawing_number=row["drawing_number"],
                association_rule=row["association_rule"],
                sheet_name=row["sheet_name"],
                anchor=row["anchor"],
                width_px=row["width_px"],
                height_px=row["height_px"],
            )
            for row in rows
        )

    async def set_version_state(
        self, *, version_id: str, state: VersionState
    ) -> EngineeringVersionRecord:
        with _database_errors():
            row = await self._pool.fetchrow(
                "update elsa.engineering_bom_versions set state = $2 "
                f"where id = $1 and state <> 'published' returning {_VERSION_COLUMNS}",
                _as_uuid(version_id),
                state.value,
            )
        if row is None:
            raise SubjectNotFoundError(version_id)
        return _version(row)

    async def publish_version(
        self, *, version_id: str, actor: str, request_id: str | None = None
    ) -> EngineeringVersionRecord:
        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                current = await connection.fetchrow(
                    f"select {_VERSION_COLUMNS} from elsa.engineering_bom_versions where id = $1",
                    _as_uuid(version_id),
                )
                if current is None:
                    raise SubjectNotFoundError(version_id)
                asset_uuid = current["asset_id"]
                # El cerrojo se toma después de conocer el activo y antes de
                # decidir nada: dos publicaciones del mismo activo se
                # serializan aquí, vengan del proceso que vengan.
                await connection.execute(
                    "select pg_advisory_xact_lock($1, $2)",
                    _PUBLISH_LOCK_SPACE,
                    _lock_key(asset_uuid),
                )
                current = await connection.fetchrow(
                    f"select {_VERSION_COLUMNS} from elsa.engineering_bom_versions where id = $1",
                    _as_uuid(version_id),
                )
                assert current is not None  # noqa: S101
                state = VersionState(current["state"])
                if state is VersionState.PUBLISHED:
                    return _version(current)
                if state is not VersionState.APPROVED:
                    raise NotPublishableError(
                        f"a version in state {state.value!r} cannot be published"
                    )

                # La anterior no se borra: queda reemplazada y consultable.
                await connection.execute(
                    "update elsa.engineering_bom_versions set state = 'superseded', "
                    "superseded_at = now() where asset_id = $1 and state = 'published'",
                    asset_uuid,
                )
                row = await connection.fetchrow(
                    "update elsa.engineering_bom_versions set state = 'published', "
                    "published_at = now(), published_by = $2 "
                    f"where id = $1 returning {_VERSION_COLUMNS}",
                    _as_uuid(version_id),
                    _as_uuid(actor),
                )
                await connection.execute(
                    _INSERT_AUDIT,
                    _as_uuid(actor),
                    _as_uuid(actor),
                    AdminOperation.BOM_PUBLISHED.value,
                    None,
                    None,
                    request_id,
                    _json({"version_id": version_id}),
                )
                assert row is not None  # noqa: S101
                return _version(row)

    # -----------------------------------------------------------------
    # Snapshots de SAP
    # -----------------------------------------------------------------

    async def store_sap_snapshot(
        self,
        *,
        asset_id: str,
        import_id: str,
        source_artifact_id: str,
        snapshot: ParsedSapSnapshot,
        actor: str,
        request_id: str | None = None,
    ) -> SapSnapshotRecord:
        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                row = await connection.fetchrow(
                    "insert into elsa.sap_bom_snapshots (asset_id, import_id, "
                    "source_artifact_id, functional_location, description, valid_from) "
                    f"values ($1,$2,$3,$4,$5,$6) returning {_SNAPSHOT_COLUMNS}",
                    _as_uuid(asset_id),
                    _as_uuid(import_id),
                    _as_uuid(source_artifact_id),
                    snapshot.functional_location,
                    snapshot.description,
                    snapshot.valid_from,
                )
                assert row is not None  # noqa: S101
                for item in snapshot.items:
                    await connection.execute(
                        "insert into elsa.sap_snapshot_items (snapshot_id, source_row, "
                        "entry_kind, position, sap_code, description, quantity, "
                        "quantity_original, unit, parent_path, depth, extra) "
                        "values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)",
                        row["id"],
                        item.source_row,
                        item.entry_kind,
                        item.position,
                        item.sap_code,
                        item.description,
                        item.quantity,
                        item.quantity_original,
                        item.unit,
                        item.parent_path,
                        item.depth,
                        _json(dict(item.extra)),
                    )
                stats = {
                    "materials": len(snapshot.materials),
                    "equipments": len(snapshot.equipments),
                }
                await connection.execute(
                    "update elsa.imports set status = 'completed', finished_at = now(), "
                    "stats = $2 where id = $1",
                    _as_uuid(import_id),
                    _json(stats),
                )
                await connection.execute(
                    _INSERT_AUDIT,
                    _as_uuid(actor),
                    _as_uuid(actor),
                    AdminOperation.IMPORT_COMPLETED.value,
                    None,
                    None,
                    request_id,
                    _json({"import_id": import_id, **{k: str(v) for k, v in stats.items()}}),
                )
                return _snapshot(row)

    async def get_snapshot(self, snapshot_id: str) -> SapSnapshotRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_SNAPSHOT_COLUMNS} from elsa.sap_bom_snapshots where id = $1",
                _as_uuid(snapshot_id),
            )
        return None if row is None else _snapshot(row)

    async def list_snapshots(self, asset_id: str) -> tuple[SapSnapshotRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_SNAPSHOT_COLUMNS} from elsa.sap_bom_snapshots "
                "where asset_id = $1 order by captured_at desc",
                _as_uuid(asset_id),
            )
        return tuple(_snapshot(row) for row in rows)

    async def list_snapshot_items(self, snapshot_id: str) -> tuple[SapSnapshotItemRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_SNAPSHOT_ITEM_COLUMNS} from elsa.sap_snapshot_items "
                "where snapshot_id = $1 order by source_row",
                _as_uuid(snapshot_id),
            )
        return tuple(
            SapSnapshotItemRecord(
                id=str(row["id"]),
                snapshot_id=str(row["snapshot_id"]),
                source_row=int(row["source_row"]),
                entry_kind=str(row["entry_kind"]),
                position=row["position"],
                sap_code=row["sap_code"],
                description=row["description"],
                quantity=row["quantity"],
                quantity_original=row["quantity_original"],
                unit=row["unit"],
                parent_path=row["parent_path"],
                depth=int(row["depth"]),
                extra=_loads(row["extra"]),
            )
            for row in rows
        )

    # -----------------------------------------------------------------
    # Reconciliación
    # -----------------------------------------------------------------

    async def store_reconciliation(
        self,
        *,
        asset_id: str,
        version_id: str,
        snapshot_id: str,
        entries: Sequence[ReconciliationEntry],
        actor: str,
        request_id: str | None = None,
    ) -> ReconciliationRunRecord:
        stats: dict[str, int] = {}
        for entry in entries:
            stats[entry.classification.value] = stats.get(entry.classification.value, 0) + 1

        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                row = await connection.fetchrow(
                    "insert into elsa.reconciliation_runs (asset_id, version_id, snapshot_id, "
                    "created_by, stats) values ($1,$2,$3,$4,$5) "
                    "on conflict (version_id, snapshot_id) do update set stats = excluded.stats "
                    f"returning {_RUN_COLUMNS}",
                    _as_uuid(asset_id),
                    _as_uuid(version_id),
                    _as_uuid(snapshot_id),
                    _as_uuid(actor),
                    _json(stats),
                )
                assert row is not None  # noqa: S101
                # Recalcular el mismo par produce el mismo resultado; los
                # renglones anteriores se reemplazan por los recién
                # calculados, que son idénticos por ser determinístico.
                await connection.execute(
                    "delete from elsa.reconciliation_items where run_id = $1", row["id"]
                )
                for entry in entries:
                    await connection.execute(
                        "insert into elsa.reconciliation_items (run_id, classification, "
                        "bom_item_id, snapshot_item_id, component_id, sap_code, "
                        "engineering_quantity, sap_quantity, engineering_unit, sap_unit, "
                        "engineering_description, sap_description, detail) "
                        "values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)",
                        row["id"],
                        entry.classification.value,
                        _as_uuid(entry.bom_item_id),
                        _as_uuid(entry.snapshot_item_id),
                        _as_uuid(entry.component_id),
                        entry.sap_code,
                        entry.engineering_quantity,
                        entry.sap_quantity,
                        entry.engineering_unit,
                        entry.sap_unit,
                        entry.engineering_description,
                        entry.sap_description,
                        _json(dict(entry.detail)),
                    )
                await connection.execute(
                    _INSERT_AUDIT,
                    _as_uuid(actor),
                    _as_uuid(actor),
                    AdminOperation.RECONCILIATION_CREATED.value,
                    None,
                    None,
                    request_id,
                    _json({"run_id": str(row["id"]), **{k: str(v) for k, v in stats.items()}}),
                )
                return _run(row)

    async def get_reconciliation(self, run_id: str) -> ReconciliationRunRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_RUN_COLUMNS} from elsa.reconciliation_runs where id = $1",
                _as_uuid(run_id),
            )
        return None if row is None else _run(row)

    async def list_reconciliations(self, asset_id: str) -> tuple[ReconciliationRunRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_RUN_COLUMNS} from elsa.reconciliation_runs "
                "where asset_id = $1 order by created_at desc",
                _as_uuid(asset_id),
            )
        return tuple(_run(row) for row in rows)

    async def list_reconciliation_items(self, run_id: str) -> tuple[ReconciliationItemRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_RUN_ITEM_COLUMNS} from elsa.reconciliation_items "
                "where run_id = $1 order by classification, sap_code nulls last",
                _as_uuid(run_id),
            )
        return tuple(
            ReconciliationItemRecord(
                id=str(row["id"]),
                run_id=str(row["run_id"]),
                classification=str(row["classification"]),
                bom_item_id=None if row["bom_item_id"] is None else str(row["bom_item_id"]),
                snapshot_item_id=(
                    None if row["snapshot_item_id"] is None else str(row["snapshot_item_id"])
                ),
                component_id=None if row["component_id"] is None else str(row["component_id"]),
                sap_code=row["sap_code"],
                engineering_quantity=row["engineering_quantity"],
                sap_quantity=row["sap_quantity"],
                engineering_unit=row["engineering_unit"],
                sap_unit=row["sap_unit"],
                engineering_description=row["engineering_description"],
                sap_description=row["sap_description"],
                detail=_loads(row["detail"]),
            )
            for row in rows
        )

    # -----------------------------------------------------------------
    # Validaciones
    # -----------------------------------------------------------------

    async def record_review(
        self,
        *,
        asset_id: str,
        subject_kind: ReviewSubject,
        subject_id: str,
        decision: ReviewDecision,
        reviewer: str,
        comment: str | None = None,
        subject_version_id: str | None = None,
        reverts_review_id: str | None = None,
        inherited_from_id: str | None = None,
        request_id: str | None = None,
    ) -> ReviewRecord:
        operations = {
            ReviewDecision.APPROVED: AdminOperation.VALIDATION_APPROVED,
            ReviewDecision.REJECTED: AdminOperation.VALIDATION_REJECTED,
            ReviewDecision.REVERTED: AdminOperation.VALIDATION_REVERTED,
        }
        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                # Solo se inserta. La tabla prohíbe UPDATE y DELETE por
                # trigger, así que ninguna validación anterior puede alterarse
                # ni siquiera desde aquí.
                row = await connection.fetchrow(
                    "insert into elsa.reviews (asset_id, subject_kind, subject_id, "
                    "subject_version_id, decision, comment, reviewer, reverts_review_id, "
                    "inherited_from_id, request_id) "
                    f"values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) returning {_REVIEW_COLUMNS}",
                    _as_uuid(asset_id),
                    subject_kind.value,
                    _as_uuid(subject_id),
                    _as_uuid(subject_version_id),
                    decision.value,
                    comment,
                    _as_uuid(reviewer),
                    _as_uuid(reverts_review_id),
                    _as_uuid(inherited_from_id),
                    request_id,
                )
                assert row is not None  # noqa: S101
                await connection.execute(
                    _INSERT_AUDIT,
                    _as_uuid(reviewer),
                    _as_uuid(reviewer),
                    operations[decision].value,
                    None,
                    None,
                    request_id,
                    # Nunca el comentario: puede contener detalle técnico.
                    _json({"subject_kind": subject_kind.value, "subject_id": subject_id}),
                )
                return _review(row)

    async def get_review(self, review_id: str) -> ReviewRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_REVIEW_COLUMNS} from elsa.reviews where id = $1", _as_uuid(review_id)
            )
        return None if row is None else _review(row)

    async def latest_review(
        self, *, subject_kind: ReviewSubject, subject_id: str
    ) -> ReviewRecord | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_REVIEW_COLUMNS} from elsa.reviews "
                "where subject_kind = $1 and subject_id = $2 order by seq desc limit 1",
                subject_kind.value,
                _as_uuid(subject_id),
            )
        return None if row is None else _review(row)

    async def list_reviews(
        self, *, asset_id: str, subject_id: str | None = None, limit: int = 100
    ) -> tuple[ReviewRecord, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_REVIEW_COLUMNS} from elsa.reviews where asset_id = $1 "
                "and ($2::uuid is null or subject_id = $2) order by seq desc limit $3",
                _as_uuid(asset_id),
                _as_uuid(subject_id),
                limit,
            )
        return tuple(_review(row) for row in rows)

    async def check_health(self) -> None:
        with _database_errors():
            await self._pool.fetchval("select 1")


# ---------------------------------------------------------------------
# Conversión de filas
# ---------------------------------------------------------------------


def _asset(row: Any) -> TechnicalAssetRecord:
    return TechnicalAssetRecord(
        id=str(row["id"]),
        code=str(row["code"]),
        name=str(row["name"]),
        domain=str(row["domain"]),
        description=row["description"],
        is_active=bool(row["is_active"]),
    )


def _import(row: Any) -> ImportRecord:
    return ImportRecord(
        id=str(row["id"]),
        asset_id=str(row["asset_id"]),
        source_artifact_id=str(row["source_artifact_id"]),
        kind=ImportKind(row["kind"]),
        status=ImportStatus(row["status"]),
        started_by=str(row["started_by"]),
        started_at=row["started_at"],
        failure_kind=row["failure_kind"],
        failure_message=row["failure_message"],
        request_id=row["request_id"],
        finished_at=row["finished_at"],
        stats=_loads(row["stats"]),
    )


def _version(row: Any) -> EngineeringVersionRecord:
    return EngineeringVersionRecord(
        id=str(row["id"]),
        asset_id=str(row["asset_id"]),
        import_id=str(row["import_id"]),
        source_artifact_id=str(row["source_artifact_id"]),
        version_number=int(row["version_number"]),
        state=VersionState(row["state"]),
        created_at=row["created_at"],
        published_at=row["published_at"],
        published_by=None if row["published_by"] is None else str(row["published_by"]),
        superseded_at=row["superseded_at"],
    )


def _item(row: Any) -> BomItemRecord:
    return BomItemRecord(
        id=str(row["id"]),
        version_id=str(row["version_id"]),
        source_row=int(row["source_row"]),
        component_id=None if row["component_id"] is None else str(row["component_id"]),
        subsystem_name=row["subsystem_name"],
        position=row["position"],
        component_name=row["component_name"],
        sap_code=row["sap_code"],
        sap_code_original=row["sap_code_original"],
        technical_description=row["technical_description"],
        quantity=row["quantity"],
        quantity_original=row["quantity_original"],
        unit=row["unit"],
        model_reference=row["model_reference"],
        assembly_drawing=row["assembly_drawing"],
        drawing_reference=row["drawing_reference"],
        bom_update_flag=row["bom_update_flag"],
        inventory_strategy=row["inventory_strategy"],
        stock_max=row["stock_max"],
        stock_min=row["stock_min"],
        source_stock=row["source_stock"],
        remarks=row["remarks"],
        match_rule=row["match_rule"],
        match_confidence=str(row["match_confidence"]),
        change_kind=row["change_kind"],
        extra=_loads(row["extra"]),
    )


def _failure_mode(row: Any) -> FailureModeRecord:
    return FailureModeRecord(
        id=str(row["id"]),
        version_id=str(row["version_id"]),
        source_row=int(row["source_row"]),
        component_id=None if row["component_id"] is None else str(row["component_id"]),
        subsystem_name=row["subsystem_name"],
        component_name=row["component_name"],
        sap_code=row["sap_code"],
        failure_mode=row["failure_mode"],
        effect=row["effect"],
        cause=row["cause"],
        severity=row["severity"],
        occurrence=row["occurrence"],
        detection=row["detection"],
        rpn=row["rpn"],
        action=row["action"],
        preventive_plan=row["preventive_plan"],
        corrective_action=row["corrective_action"],
        remarks=row["remarks"],
        match_rule=row["match_rule"],
        match_confidence=str(row["match_confidence"]),
        change_kind=row["change_kind"],
    )


def _snapshot(row: Any) -> SapSnapshotRecord:
    return SapSnapshotRecord(
        id=str(row["id"]),
        asset_id=str(row["asset_id"]),
        import_id=str(row["import_id"]),
        source_artifact_id=str(row["source_artifact_id"]),
        captured_at=row["captured_at"],
        functional_location=row["functional_location"],
        description=row["description"],
        valid_from=row["valid_from"],
    )


def _run(row: Any) -> ReconciliationRunRecord:
    return ReconciliationRunRecord(
        id=str(row["id"]),
        asset_id=str(row["asset_id"]),
        version_id=str(row["version_id"]),
        snapshot_id=str(row["snapshot_id"]),
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
        stats={key: int(value) for key, value in _loads(row["stats"]).items()},
    )


def _review(row: Any) -> ReviewRecord:
    return ReviewRecord(
        id=str(row["id"]),
        seq=int(row["seq"]),
        asset_id=str(row["asset_id"]),
        subject_kind=ReviewSubject(row["subject_kind"]),
        subject_id=str(row["subject_id"]),
        decision=ReviewDecision(row["decision"]),
        reviewer=str(row["reviewer"]),
        decided_at=row["decided_at"],
        comment=row["comment"],
        subject_version_id=(
            None if row["subject_version_id"] is None else str(row["subject_version_id"])
        ),
        reverts_review_id=(
            None if row["reverts_review_id"] is None else str(row["reverts_review_id"])
        ),
        inherited_from_id=(
            None if row["inherited_from_id"] is None else str(row["inherited_from_id"])
        ),
        request_id=row["request_id"],
    )
