"""Repositorio de conocimiento técnico en memoria (determinista, DEV y tests).

Implementa la misma semántica que el repositorio PostgreSQL y pasa la misma
batería de tests de contrato. No persiste nada: al reiniciar el proceso se
pierde, por eso solo se permite en DEV.

Las garantías que aquí se programan a mano —una sola versión publicada,
publicación atómica, archivo duplicado detectado, validaciones que solo se
añaden— son las mismas que en PostgreSQL impone el esquema. Que existan dos
veces no es duplicación ociosa: es lo que permite que un test que corre sin
base de datos siga significando algo sobre el comportamiento real.
"""

import asyncio
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

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


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(tz=UTC)


class InMemoryKnowledgeRepository:
    """Conocimiento técnico de ELSA en memoria."""

    def __init__(self) -> None:
        self._assets: dict[str, TechnicalAssetRecord] = {}
        self._subsystems: dict[tuple[str, str], tuple[str, str]] = {}
        self._components: dict[str, ComponentRecord] = {}
        self._identifiers: list[tuple[str, MatchCandidate]] = []
        self._artifacts: dict[tuple[str, str], str] = {}
        self._imports: dict[str, ImportRecord] = {}
        self._versions: dict[str, EngineeringVersionRecord] = {}
        self._items: dict[str, list[BomItemRecord]] = {}
        self._failure_modes: dict[str, list[FailureModeRecord]] = {}
        self._sod: dict[str, list[SodCriterionRecord]] = {}
        self._options: dict[str, list[Any]] = {}
        self._drawings: dict[str, list[DrawingImageRecord]] = {}
        self._snapshots: dict[str, SapSnapshotRecord] = {}
        self._snapshot_items: dict[str, list[SapSnapshotItemRecord]] = {}
        self._runs: dict[str, ReconciliationRunRecord] = {}
        self._run_items: dict[str, list[ReconciliationItemRecord]] = {}
        self._reviews: list[ReviewRecord] = []
        # Serializa las escrituras compuestas, igual que la transacción y el
        # cerrojo consultivo hacen en PostgreSQL.
        self._lock = asyncio.Lock()

    # -----------------------------------------------------------------
    # Activos
    # -----------------------------------------------------------------

    async def list_assets(self) -> tuple[TechnicalAssetRecord, ...]:
        return tuple(sorted(self._assets.values(), key=lambda asset: asset.code))

    async def get_asset(self, code: str) -> TechnicalAssetRecord | None:
        return self._assets.get(code)

    async def create_asset(
        self,
        *,
        code: str,
        name: str,
        domain: str,
        description: str | None = None,
    ) -> TechnicalAssetRecord:
        async with self._lock:
            if code in self._assets:
                raise AssetAlreadyExistsError(code)
            asset = TechnicalAssetRecord(
                id=_new_id(), code=code, name=name, domain=domain, description=description
            )
            self._assets[code] = asset
            return asset

    def _asset_by_id(self, asset_id: str) -> TechnicalAssetRecord | None:
        return next((a for a in self._assets.values() if a.id == asset_id), None)

    # -----------------------------------------------------------------
    # Ingesta
    # -----------------------------------------------------------------

    async def find_import_by_source(self, *, kind: str, sha256: str) -> ImportRecord | None:
        artifact_id = self._artifacts.get((kind, sha256))
        if artifact_id is None:
            return None
        return next(
            (
                record
                for record in self._imports.values()
                if record.source_artifact_id == artifact_id
            ),
            None,
        )

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
        async with self._lock:
            key = (artifact_kind, sha256)
            if key in self._artifacts:
                existing = await self.find_import_by_source(kind=artifact_kind, sha256=sha256)
                raise DuplicateSourceError(
                    "this exact file has already been imported",
                    existing_import_id=None if existing is None else existing.id,
                )
            artifact_id = _new_id()
            self._artifacts[key] = artifact_id
            record = ImportRecord(
                id=_new_id(),
                asset_id=asset_id,
                source_artifact_id=artifact_id,
                kind=kind,
                status=ImportStatus.PROCESSING,
                started_by=uploaded_by,
                started_at=_now(),
                request_id=request_id,
            )
            self._imports[record.id] = record
            return record

    async def fail_import(
        self,
        *,
        import_id: str,
        failure_kind: str,
        failure_message: str,
        actor: str,
        request_id: str | None = None,
    ) -> ImportRecord:
        async with self._lock:
            record = self._imports.get(import_id)
            if record is None:
                raise SubjectNotFoundError(import_id)
            failed = ImportRecord(
                id=record.id,
                asset_id=record.asset_id,
                source_artifact_id=record.source_artifact_id,
                kind=record.kind,
                status=ImportStatus.FAILED,
                started_by=record.started_by,
                started_at=record.started_at,
                failure_kind=failure_kind,
                failure_message=failure_message,
                request_id=record.request_id,
                finished_at=_now(),
                stats=record.stats,
            )
            self._imports[import_id] = failed
            return failed

    def _complete_import(self, import_id: str, stats: Mapping[str, object]) -> None:
        record = self._imports[import_id]
        self._imports[import_id] = ImportRecord(
            id=record.id,
            asset_id=record.asset_id,
            source_artifact_id=record.source_artifact_id,
            kind=record.kind,
            status=ImportStatus.COMPLETED,
            started_by=record.started_by,
            started_at=record.started_at,
            request_id=record.request_id,
            finished_at=_now(),
            stats=dict(stats),
        )

    async def get_import(self, import_id: str) -> ImportRecord | None:
        return self._imports.get(import_id)

    async def list_imports(self, asset_id: str, *, limit: int = 50) -> tuple[ImportRecord, ...]:
        records = sorted(
            (record for record in self._imports.values() if record.asset_id == asset_id),
            key=lambda record: record.started_at,
            reverse=True,
        )
        return tuple(records[:limit])

    # -----------------------------------------------------------------
    # Componentes
    # -----------------------------------------------------------------

    async def component_entries(self, asset_id: str) -> tuple[tuple[str, MatchCandidate], ...]:
        return tuple(
            (component_id, candidate)
            for component_id, candidate in self._identifiers
            if self._components[component_id].asset_id == asset_id
        )

    async def list_components(self, asset_id: str) -> tuple[ComponentRecord, ...]:
        return tuple(
            component for component in self._components.values() if component.asset_id == asset_id
        )

    def _ensure_subsystem(self, asset_id: str, name: str | None) -> tuple[str | None, str | None]:
        if name is None:
            return None, None
        key = (asset_id, name.strip().lower())
        existing = self._subsystems.get(key)
        if existing is None:
            existing = (_new_id(), name)
            self._subsystems[key] = existing
        return existing

    # -----------------------------------------------------------------
    # Versiones
    # -----------------------------------------------------------------

    async def store_engineering_version(
        self, data: EngineeringVersionInput, *, actor: str, request_id: str | None = None
    ) -> EngineeringVersionRecord:
        async with self._lock:
            numbers = [
                version.version_number
                for version in self._versions.values()
                if version.asset_id == data.asset_id
            ]
            version = EngineeringVersionRecord(
                id=_new_id(),
                asset_id=data.asset_id,
                import_id=data.import_id,
                source_artifact_id=data.source_artifact_id,
                version_number=(max(numbers) + 1) if numbers else 1,
                state=VersionState.PENDING_VALIDATION,
                created_at=_now(),
            )

            items: list[BomItemRecord] = []
            for resolved in data.rows:
                row = resolved.row
                subsystem_id, subsystem_name = self._ensure_subsystem(
                    data.asset_id, row.subsystem_name
                )
                component_id = resolved.component_id
                if component_id is None and not resolved.ambiguous:
                    # Componente nuevo: UUID propio y permanente, que no
                    # depende del código SAP ni del nombre ni del plano.
                    component_id = _new_id()
                    self._components[component_id] = ComponentRecord(
                        id=component_id,
                        asset_id=data.asset_id,
                        subsystem_id=subsystem_id,
                        subsystem_name=subsystem_name,
                    )
                if component_id is not None:
                    self._identifiers.append(
                        (
                            component_id,
                            MatchCandidate(
                                subsystem_name=row.subsystem_name,
                                component_name=row.component_name,
                                sap_code=row.sap_code,
                                assembly_drawing=row.assembly_drawing,
                                drawing_reference=row.drawing_reference,
                                model_reference=row.model_reference,
                            ),
                        )
                    )
                items.append(
                    BomItemRecord(
                        id=_new_id(),
                        version_id=version.id,
                        source_row=row.source_row,
                        component_id=component_id,
                        subsystem_name=row.subsystem_name,
                        position=row.position,
                        component_name=row.component_name,
                        sap_code=row.sap_code,
                        sap_code_original=row.sap_code_original,
                        technical_description=row.technical_description,
                        quantity=row.quantity,
                        quantity_original=row.quantity_original,
                        unit=row.unit,
                        model_reference=row.model_reference,
                        assembly_drawing=row.assembly_drawing,
                        drawing_reference=row.drawing_reference,
                        bom_update_flag=row.bom_update_flag,
                        inventory_strategy=row.inventory_strategy,
                        stock_max=row.stock_max,
                        stock_min=row.stock_min,
                        source_stock=row.source_stock,
                        remarks=row.remarks,
                        match_rule=resolved.match_rule,
                        match_confidence=resolved.match_confidence,
                        change_kind=resolved.change_kind,
                        extra=dict(row.extra),
                    )
                )

            by_code = {
                item.sap_code: item.component_id
                for item in items
                if item.sap_code and item.component_id
            }
            failure_modes = [
                FailureModeRecord(
                    id=_new_id(),
                    version_id=version.id,
                    source_row=mode.source_row,
                    component_id=by_code.get(mode.sap_code) if mode.sap_code else None,
                    subsystem_name=mode.subsystem_name,
                    component_name=mode.component_name,
                    sap_code=mode.sap_code,
                    failure_mode=mode.failure_mode,
                    effect=mode.effect,
                    cause=mode.cause,
                    severity=mode.severity,
                    occurrence=mode.occurrence,
                    detection=mode.detection,
                    # Siempre el calculado, nunca el que trajera el archivo.
                    rpn=mode.rpn,
                    action=mode.action,
                    preventive_plan=mode.preventive_plan,
                    corrective_action=mode.corrective_action,
                    remarks=mode.remarks,
                    match_rule="sap_code" if mode.sap_code in by_code else None,
                    match_confidence="strong" if mode.sap_code in by_code else "unresolved",
                )
                for mode in data.failure_modes
            ]

            self._versions[version.id] = version
            self._items[version.id] = items
            self._failure_modes[version.id] = failure_modes
            self._sod[version.id] = [
                SodCriterionRecord(
                    id=_new_id(),
                    version_id=version.id,
                    dimension=criterion.dimension,
                    source_row=criterion.source_row,
                    scale_value=criterion.scale_value,
                    label=criterion.label,
                    description=criterion.description,
                    range_low=criterion.range_low,
                    range_high=criterion.range_high,
                )
                for criterion in data.sod_criteria
            ]
            self._options[version.id] = list(data.option_rows)
            self._drawings[version.id] = [
                DrawingImageRecord(
                    id=_new_id(),
                    version_id=version.id,
                    derived_artifact_id=_new_id(),
                    storage_key=data.drawing_storage_keys.get(image.sha256, ""),
                    sha256=image.sha256,
                    association_status="resolved" if image.is_associated else "pending_review",
                    drawing_number=image.drawing_number,
                    association_rule=image.association_rule,
                    sheet_name=image.sheet_name,
                    anchor=image.anchor,
                    width_px=image.width_px,
                    height_px=image.height_px,
                )
                for image in data.drawing_images
            ]
            self._complete_import(
                data.import_id,
                {
                    "bom_items": len(items),
                    "failure_modes": len(failure_modes),
                    "sod_criteria": len(data.sod_criteria),
                    "drawing_images": len(data.drawing_images),
                },
            )
            return version

    async def get_version(self, version_id: str) -> EngineeringVersionRecord | None:
        return self._versions.get(version_id)

    async def list_versions(self, asset_id: str) -> tuple[EngineeringVersionRecord, ...]:
        return tuple(
            sorted(
                (v for v in self._versions.values() if v.asset_id == asset_id),
                key=lambda version: version.version_number,
                reverse=True,
            )
        )

    async def get_published_version(self, asset_id: str) -> EngineeringVersionRecord | None:
        return next(
            (
                version
                for version in self._versions.values()
                if version.asset_id == asset_id and version.state is VersionState.PUBLISHED
            ),
            None,
        )

    async def list_version_items(self, version_id: str) -> tuple[BomItemRecord, ...]:
        return tuple(self._items.get(version_id, ()))

    async def list_failure_modes(self, version_id: str) -> tuple[FailureModeRecord, ...]:
        return tuple(self._failure_modes.get(version_id, ()))

    async def list_sod_criteria(self, version_id: str) -> tuple[SodCriterionRecord, ...]:
        return tuple(self._sod.get(version_id, ()))

    async def list_drawing_images(self, version_id: str) -> tuple[DrawingImageRecord, ...]:
        return tuple(self._drawings.get(version_id, ()))

    def _replace_version(self, version: EngineeringVersionRecord, **changes: Any) -> None:
        values = {
            "id": version.id,
            "asset_id": version.asset_id,
            "import_id": version.import_id,
            "source_artifact_id": version.source_artifact_id,
            "version_number": version.version_number,
            "state": version.state,
            "created_at": version.created_at,
            "published_at": version.published_at,
            "published_by": version.published_by,
            "superseded_at": version.superseded_at,
        }
        values.update(changes)
        self._versions[version.id] = EngineeringVersionRecord(**values)  # type: ignore[arg-type]

    async def set_version_state(
        self, *, version_id: str, state: VersionState
    ) -> EngineeringVersionRecord:
        async with self._lock:
            version = self._versions.get(version_id)
            if version is None:
                raise SubjectNotFoundError(version_id)
            self._replace_version(version, state=state)
            return self._versions[version_id]

    async def publish_version(
        self, *, version_id: str, actor: str, request_id: str | None = None
    ) -> EngineeringVersionRecord:
        async with self._lock:
            version = self._versions.get(version_id)
            if version is None:
                raise SubjectNotFoundError(version_id)
            if version.state is VersionState.PUBLISHED:
                return version
            if version.state is not VersionState.APPROVED:
                raise NotPublishableError(
                    f"a version in state {version.state.value!r} cannot be published"
                )

            current = await self.get_published_version(version.asset_id)
            if current is not None:
                # La anterior no se borra: queda reemplazada y consultable.
                self._replace_version(current, state=VersionState.SUPERSEDED, superseded_at=_now())
            self._replace_version(
                version,
                state=VersionState.PUBLISHED,
                published_at=_now(),
                published_by=actor,
            )
            return self._versions[version_id]

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
        async with self._lock:
            record = SapSnapshotRecord(
                id=_new_id(),
                asset_id=asset_id,
                import_id=import_id,
                source_artifact_id=source_artifact_id,
                captured_at=_now(),
                functional_location=snapshot.functional_location,
                description=snapshot.description,
                valid_from=snapshot.valid_from,
            )
            self._snapshots[record.id] = record
            self._snapshot_items[record.id] = [
                SapSnapshotItemRecord(
                    id=_new_id(),
                    snapshot_id=record.id,
                    source_row=item.source_row,
                    entry_kind=item.entry_kind,
                    position=item.position,
                    sap_code=item.sap_code,
                    description=item.description,
                    quantity=item.quantity,
                    quantity_original=item.quantity_original,
                    unit=item.unit,
                    parent_path=item.parent_path,
                    depth=item.depth,
                    extra=dict(item.extra),
                )
                for item in snapshot.items
            ]
            self._complete_import(
                import_id,
                {
                    "materials": len(snapshot.materials),
                    "equipments": len(snapshot.equipments),
                },
            )
            return record

    async def get_snapshot(self, snapshot_id: str) -> SapSnapshotRecord | None:
        return self._snapshots.get(snapshot_id)

    async def list_snapshots(self, asset_id: str) -> tuple[SapSnapshotRecord, ...]:
        return tuple(
            sorted(
                (s for s in self._snapshots.values() if s.asset_id == asset_id),
                key=lambda snapshot: snapshot.captured_at,
                reverse=True,
            )
        )

    async def list_snapshot_items(self, snapshot_id: str) -> tuple[SapSnapshotItemRecord, ...]:
        return tuple(self._snapshot_items.get(snapshot_id, ()))

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
        async with self._lock:
            stats: dict[str, int] = {}
            for entry in entries:
                stats[entry.classification.value] = stats.get(entry.classification.value, 0) + 1
            run = ReconciliationRunRecord(
                id=_new_id(),
                asset_id=asset_id,
                version_id=version_id,
                snapshot_id=snapshot_id,
                created_by=actor,
                created_at=_now(),
                stats=stats,
            )
            self._runs[run.id] = run
            self._run_items[run.id] = [
                ReconciliationItemRecord(
                    id=_new_id(),
                    run_id=run.id,
                    classification=entry.classification.value,
                    bom_item_id=entry.bom_item_id,
                    snapshot_item_id=entry.snapshot_item_id,
                    component_id=entry.component_id,
                    sap_code=entry.sap_code,
                    engineering_quantity=entry.engineering_quantity,
                    sap_quantity=entry.sap_quantity,
                    engineering_unit=entry.engineering_unit,
                    sap_unit=entry.sap_unit,
                    engineering_description=entry.engineering_description,
                    sap_description=entry.sap_description,
                    detail=dict(entry.detail),
                )
                for entry in entries
            ]
            return run

    async def get_reconciliation(self, run_id: str) -> ReconciliationRunRecord | None:
        return self._runs.get(run_id)

    async def list_reconciliations(self, asset_id: str) -> tuple[ReconciliationRunRecord, ...]:
        return tuple(
            sorted(
                (run for run in self._runs.values() if run.asset_id == asset_id),
                key=lambda run: run.created_at,
                reverse=True,
            )
        )

    async def list_reconciliation_items(self, run_id: str) -> tuple[ReconciliationItemRecord, ...]:
        return tuple(self._run_items.get(run_id, ()))

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
        async with self._lock:
            review = ReviewRecord(
                id=_new_id(),
                seq=len(self._reviews) + 1,
                asset_id=asset_id,
                subject_kind=subject_kind,
                subject_id=subject_id,
                decision=decision,
                reviewer=reviewer,
                decided_at=_now(),
                comment=comment,
                subject_version_id=subject_version_id,
                reverts_review_id=reverts_review_id,
                inherited_from_id=inherited_from_id,
                request_id=request_id,
            )
            # Solo se añade. Nada de lo anterior se toca.
            self._reviews.append(review)
            return review

    async def get_review(self, review_id: str) -> ReviewRecord | None:
        return next((review for review in self._reviews if review.id == review_id), None)

    async def latest_review(
        self, *, subject_kind: ReviewSubject, subject_id: str
    ) -> ReviewRecord | None:
        matching = [
            review
            for review in self._reviews
            if review.subject_kind is subject_kind and review.subject_id == subject_id
        ]
        return matching[-1] if matching else None

    async def list_reviews(
        self, *, asset_id: str, subject_id: str | None = None, limit: int = 100
    ) -> tuple[ReviewRecord, ...]:
        matching = [
            review
            for review in reversed(self._reviews)
            if review.asset_id == asset_id
            and (subject_id is None or review.subject_id == subject_id)
        ]
        return tuple(matching[:limit])

    async def check_health(self) -> None:
        return None
