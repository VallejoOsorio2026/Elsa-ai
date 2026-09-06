"""Ingesta de fuentes técnicas, de extremo a extremo.

Une lo que hasta ahora estaba separado a propósito: el almacenamiento
privado, los parsers, el emparejamiento de componentes, la comparación con
la versión publicada y el repositorio. Aquí se decide **el orden** de esos
pasos y qué ocurre cuando uno falla.

El orden importa y no es arbitrario:

1. Se calcula el SHA-256 del archivo **antes de mirarlo**. Es la huella del
   original y la base de la idempotencia.
2. Se comprueba si ese archivo exacto ya se importó. Reimportarlo no crea
   una versión nueva.
3. Se guardan los bytes en el almacenamiento privado. Si el almacenamiento
   no responde, no se registra nada: fingir que el archivo está guardado
   sería perder evidencia sin que nadie se entere.
4. Se abre la importación en la base. La unicidad del contenido la impone la
   base, no la comprobación del paso 2: dos peticiones simultáneas con el
   mismo archivo pasan las dos por el paso 2 y solo una sobrevive al 4.
5. Se interpreta el archivo. Cualquier fallo cierra la importación como
   fallida, con su tipo, y **no toca la última versión publicada**.
6. Se resuelve la identidad de cada renglón y se clasifica el cambio.
7. Se escribe la versión entera, en una transacción.

Una versión recién importada entra siempre como ``pending_validation``.
Nunca se publica sola.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from elsa.core.matching import ComponentIndex, MatchCandidate, match_component
from elsa.core.reconciliation import (
    EngineeringEntry,
    ReconciliationEntry,
    SapEntry,
    reconcile,
)
from elsa.core.versioning import ChangeKind, VersionedItem, classify_versions, fingerprint
from elsa.ingestion.engineering_xlsx import parse_engineering_workbook
from elsa.ingestion.errors import IngestionError
from elsa.ingestion.model import IngestionWarning, ParsedBomRow, ParsedEngineeringBom
from elsa.ingestion.safety import ArchiveLimits
from elsa.ingestion.sap_htm import parse_sap_snapshot
from elsa.ports.artifact_storage import (
    ArtifactAlreadyExistsError,
    ArtifactStoragePort,
    sha256_hex,
    storage_key,
)
from elsa.ports.knowledge import (
    BomItemRecord,
    DuplicateSourceError,
    EngineeringVersionInput,
    EngineeringVersionRecord,
    ImportKind,
    ImportRecord,
    KnowledgeRepositoryPort,
    ReconciliationRunRecord,
    ResolvedBomRow,
    SapSnapshotRecord,
    TechnicalAssetRecord,
)

_logger = logging.getLogger("elsa.services.ingestion")

__all__ = ["DuplicateImport", "IngestionService", "row_fingerprint", "warning_counts"]

_ENGINEERING_ARTIFACT = "engineering_bom_xlsx"
_SAP_ARTIFACT = "sap_bom_htm"


@dataclass(frozen=True, slots=True)
class DuplicateImport:
    """Se subió un archivo ya importado; se devuelve el original."""

    existing_import_id: str | None


def warning_counts(warnings: Sequence[IngestionWarning]) -> dict[str, int]:
    """Avisos del parser agrupados por código.

    Lo que se persiste son **códigos estables y conteos**, no mensajes ni
    contenido del archivo: ``formula_not_evaluated: 3`` le dice a un revisor
    que hubo tres fórmulas sin evaluar sin revelar ninguna celda.
    """
    counts: dict[str, int] = {}
    for warning in warnings:
        counts[warning.code] = counts.get(warning.code, 0) + 1
    return counts


def row_fingerprint(row: ParsedBomRow) -> str:
    """Huella de los datos técnicos de un renglón.

    Define qué cuenta como «el dato cambió» a efectos de validación. Se
    incluyen los datos técnicos —qué es la pieza, cuántas, de qué plano— y
    se **excluyen** los de inventario (``Max``, ``Min``, ``Stock Actual``).

    La exclusión es deliberada: el stock que traía la hoja es una foto del
    inventario en la fecha de esa fuente, no un hecho técnico sobre el
    componente. Si entrara en la huella, cada actualización de existencias
    reabriría la validación de renglones que técnicamente no cambiaron, y un
    revisor que aprueba ruido termina aprobando sin mirar. Los valores se
    conservan igualmente en la versión.
    """
    return fingerprint(
        {
            "position": row.position,
            "subsystem": row.subsystem_name,
            "component": row.component_name,
            "sap_code": row.sap_code,
            "description": row.technical_description,
            "quantity": row.quantity,
            "unit": row.unit,
            "model": row.model_reference,
            "drawing": row.assembly_drawing,
            "drawing_reference": row.drawing_reference,
            "inventory_strategy": row.inventory_strategy,
        }
    )


def _stored_fingerprint(item: BomItemRecord) -> str:
    """Misma huella, calculada sobre un renglón ya almacenado."""
    return fingerprint(
        {
            "position": item.position,
            "subsystem": item.subsystem_name,
            "component": item.component_name,
            "sap_code": item.sap_code,
            "description": item.technical_description,
            "quantity": item.quantity,
            "unit": item.unit,
            "model": item.model_reference,
            "drawing": item.assembly_drawing,
            "drawing_reference": item.drawing_reference,
            "inventory_strategy": item.inventory_strategy,
        }
    )


class IngestionService:
    """Casos de uso de ingesta y reconciliación."""

    def __init__(
        self,
        knowledge: KnowledgeRepositoryPort,
        storage: ArtifactStoragePort,
        *,
        limits: ArchiveLimits | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._storage = storage
        self._limits = limits or ArchiveLimits()

    # -----------------------------------------------------------------
    # BOM de Ingeniería
    # -----------------------------------------------------------------

    async def ingest_engineering_bom(
        self,
        *,
        asset: TechnicalAssetRecord,
        data: bytes,
        actor: str,
        original_filename: str | None = None,
        request_id: str | None = None,
    ) -> EngineeringVersionRecord | DuplicateImport:
        """Importa el XLSX aprobado por Ingeniería como una versión nueva."""
        digest = sha256_hex(data)
        duplicate = await self._knowledge.find_import_by_source(
            kind=_ENGINEERING_ARTIFACT, sha256=digest
        )
        if duplicate is not None:
            _logger.info("duplicate engineering source ignored", extra={"import_id": duplicate.id})
            return DuplicateImport(existing_import_id=duplicate.id)

        key = storage_key(_ENGINEERING_ARTIFACT, digest)
        await self._store_original(key, data)

        try:
            record = await self._knowledge.start_import(
                asset_id=asset.id,
                kind=ImportKind.ENGINEERING_BOM,
                sha256=digest,
                byte_size=len(data),
                storage_key=key,
                uploaded_by=actor,
                original_filename=original_filename,
                content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                request_id=request_id,
            )
        except DuplicateSourceError as exc:
            # Otra petición ganó la carrera entre la comprobación y el
            # registro. No es un error: el archivo ya está importado.
            return DuplicateImport(existing_import_id=exc.existing_import_id)

        try:
            parsed = parse_engineering_workbook(data, limits=self._limits)
        except IngestionError as exc:
            await self._knowledge.fail_import(
                import_id=record.id,
                failure_kind=exc.kind,
                failure_message=str(exc),
                actor=actor,
                request_id=request_id,
            )
            raise

        return await self._store_version(
            asset=asset,
            record=record,
            parsed=parsed,
            actor=actor,
            request_id=request_id,
        )

    async def _store_version(
        self,
        *,
        asset: TechnicalAssetRecord,
        record: ImportRecord,
        parsed: ParsedEngineeringBom,
        actor: str,
        request_id: str | None,
    ) -> EngineeringVersionRecord:
        index = ComponentIndex.build(
            [
                (component_id, candidate)
                for component_id, candidate in await self._knowledge.component_entries(asset.id)
            ]
        )
        resolved = self._resolve_rows(parsed.bom_rows, index)
        resolved = await self._classify_changes(asset, resolved, parsed.bom_rows)
        keys = await self._store_drawings(parsed)

        return await self._knowledge.store_engineering_version(
            EngineeringVersionInput(
                asset_id=asset.id,
                import_id=record.id,
                source_artifact_id=record.source_artifact_id,
                rows=resolved,
                failure_modes=parsed.failure_modes,
                sod_criteria=parsed.sod_criteria,
                option_rows=parsed.option_rows,
                drawing_images=parsed.drawing_images,
                drawing_storage_keys=keys,
                warning_counts=warning_counts(parsed.warnings),
            ),
            actor=actor,
            request_id=request_id,
        )

    @staticmethod
    def _resolve_rows(rows: Sequence[ParsedBomRow], index: ComponentIndex) -> list[ResolvedBomRow]:
        """Decide la identidad de cada renglón, sin fusionar nada dudoso."""
        resolved: list[ResolvedBomRow] = []
        for row in rows:
            result = match_component(
                MatchCandidate(
                    subsystem_name=row.subsystem_name,
                    component_name=row.component_name,
                    sap_code=row.sap_code,
                    assembly_drawing=row.assembly_drawing,
                    drawing_reference=row.drawing_reference,
                    model_reference=row.model_reference,
                ),
                index,
            )
            resolved.append(
                ResolvedBomRow(
                    row=row,
                    component_id=result.component_id,
                    ambiguous=result.ambiguous,
                    match_rule=result.rule,
                    match_confidence=result.confidence.value,
                )
            )
        return resolved

    async def _classify_changes(
        self,
        asset: TechnicalAssetRecord,
        resolved: list[ResolvedBomRow],
        rows: Sequence[ParsedBomRow],
    ) -> list[ResolvedBomRow]:
        """Marca cada renglón como nuevo, modificado o sin cambio.

        Se compara contra la última versión **publicada**, no contra la
        última importada: una versión que aún no se publicó no es referencia
        de nada.
        """
        published = await self._knowledge.get_published_version(asset.id)
        previous: list[VersionedItem] = []
        if published is not None:
            previous = [
                VersionedItem(key=item.component_id, fingerprint=_stored_fingerprint(item))
                for item in await self._knowledge.list_version_items(published.id)
                if item.component_id is not None
            ]

        current = [
            VersionedItem(key=entry.component_id, fingerprint=row_fingerprint(row))
            for entry, row in zip(resolved, rows, strict=True)
            if entry.component_id is not None
        ]
        diff = classify_versions(previous, current)

        classified: list[ResolvedBomRow] = []
        for entry in resolved:
            if entry.component_id is None:
                # Sin identidad estable no hay con qué comparar: es nuevo, o
                # está pendiente de que una persona resuelva la ambigüedad.
                change = None if entry.ambiguous else ChangeKind.NEW.value
            else:
                change = diff.changes.get(entry.component_id, ChangeKind.NEW).value
            classified.append(
                ResolvedBomRow(
                    row=entry.row,
                    component_id=entry.component_id,
                    ambiguous=entry.ambiguous,
                    match_rule=entry.match_rule,
                    match_confidence=entry.match_confidence,
                    change_kind=change,
                )
            )
        return classified

    async def _store_drawings(self, parsed: ParsedEngineeringBom) -> dict[str, str]:
        """Guarda las imágenes de plano y devuelve SHA-256 → clave."""
        keys: dict[str, str] = {}
        for image in parsed.drawing_images:
            key = storage_key("drawing_image", image.sha256)
            await self._store_original(key, image.content)
            keys[image.sha256] = key
        return keys

    async def _store_original(self, key: str, data: bytes) -> None:
        """Guarda unos bytes, tolerando que ya estén guardados.

        La clave se deriva del contenido, así que encontrarla ocupada
        significa que esos mismos bytes ya están ahí. Es un reintento, no una
        colisión, y no hay nada que reescribir.
        """
        try:
            await self._storage.put(key, data)
        except ArtifactAlreadyExistsError:
            return

    # -----------------------------------------------------------------
    # Snapshot de SAP
    # -----------------------------------------------------------------

    async def ingest_sap_snapshot(
        self,
        *,
        asset: TechnicalAssetRecord,
        data: bytes,
        actor: str,
        original_filename: str | None = None,
        request_id: str | None = None,
    ) -> SapSnapshotRecord | DuplicateImport:
        """Importa un HTM exportado de SAP como snapshot histórico.

        El snapshot no reemplaza ni modifica el BOM de Ingeniería publicado:
        se guarda al lado, para poder compararlos.
        """
        digest = sha256_hex(data)
        duplicate = await self._knowledge.find_import_by_source(kind=_SAP_ARTIFACT, sha256=digest)
        if duplicate is not None:
            return DuplicateImport(existing_import_id=duplicate.id)

        key = storage_key(_SAP_ARTIFACT, digest)
        await self._store_original(key, data)

        try:
            record = await self._knowledge.start_import(
                asset_id=asset.id,
                kind=ImportKind.SAP_SNAPSHOT,
                sha256=digest,
                byte_size=len(data),
                storage_key=key,
                uploaded_by=actor,
                original_filename=original_filename,
                content_type="text/html",
                request_id=request_id,
            )
        except DuplicateSourceError as exc:
            return DuplicateImport(existing_import_id=exc.existing_import_id)

        try:
            snapshot = parse_sap_snapshot(data)
        except IngestionError as exc:
            await self._knowledge.fail_import(
                import_id=record.id,
                failure_kind=exc.kind,
                failure_message=str(exc),
                actor=actor,
                request_id=request_id,
            )
            raise

        return await self._knowledge.store_sap_snapshot(
            asset_id=asset.id,
            import_id=record.id,
            source_artifact_id=record.source_artifact_id,
            snapshot=snapshot,
            actor=actor,
            request_id=request_id,
        )

    # -----------------------------------------------------------------
    # Reconciliación
    # -----------------------------------------------------------------

    async def reconcile_published_bom(
        self,
        *,
        asset: TechnicalAssetRecord,
        version_id: str,
        snapshot_id: str,
        actor: str,
        request_id: str | None = None,
    ) -> ReconciliationRunRecord:
        """Compara una versión publicada con un snapshot y guarda el resultado.

        No modifica ninguna de las dos fuentes. Un snapshot posterior produce
        una corrida nueva, que es como se demuestra que una discrepancia
        cambió o desapareció.
        """
        items = await self._knowledge.list_version_items(version_id)
        snapshot_items = await self._knowledge.list_snapshot_items(snapshot_id)

        entries: tuple[ReconciliationEntry, ...] = reconcile(
            [
                EngineeringEntry(
                    item_id=item.id,
                    sap_code=item.sap_code,
                    component_id=item.component_id,
                    quantity=item.quantity,
                    unit=item.unit,
                    description=item.technical_description or item.component_name,
                )
                for item in items
            ],
            [
                SapEntry(
                    item_id=item.id,
                    sap_code=item.sap_code,
                    quantity=item.quantity,
                    unit=item.unit,
                    description=item.description,
                    entry_kind=item.entry_kind,
                )
                for item in snapshot_items
            ],
        )
        return await self._knowledge.store_reconciliation(
            asset_id=asset.id,
            version_id=version_id,
            snapshot_id=snapshot_id,
            entries=entries,
            actor=actor,
            request_id=request_id,
        )
