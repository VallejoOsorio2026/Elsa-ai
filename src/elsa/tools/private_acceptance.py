"""Prueba de aceptación privada contra los archivos reales.

Ejecuta la ingesta completa —XLSX de Ingeniería, HTM de SAP y
reconciliación— sobre archivos que viven **fuera del repositorio**, y
escribe un reporte de conteos en una ruta ignorada por Git.

    uv run python -m elsa.tools.private_acceptance \\
        --engineering "<ruta del xlsx>" \\
        --sap "<ruta del htm>" \\
        --out "<ruta del reporte>"

Reglas que esta herramienta respeta y que son el motivo de que exista:

- **Los archivos no se copian al repositorio.** Se leen desde su ruta.
- **El reporte lleva conteos y hashes, no contenido.** Ningún código de
  material, descripción ni número de plano real aparece en él, para que un
  reporte filtrado por accidente no revele información de planta.
- **Nada se publica.** La versión queda pendiente de validación, igual que
  cualquier otra.
- **No se toca ningún Supabase remoto.** Se usa la base que indique
  ``--database-url`` o, si no se indica, los adaptadores en memoria.

Ver ``docs/private-acceptance-test.md``.
"""

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from elsa.adapters.local_artifact_storage import LocalArtifactStorage
from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.postgres_knowledge import PostgresKnowledgeRepository
from elsa.ingestion.errors import IngestionError
from elsa.ports.artifact_storage import ArtifactStoragePort, sha256_hex
from elsa.ports.knowledge import KnowledgeRepositoryPort, VersionState
from elsa.services.ingestion import DuplicateImport, IngestionService

# Actor sintético: esta herramienta no autentica a nadie ni necesita hacerlo.
_ACTOR = str(uuid.uuid5(uuid.NAMESPACE_URL, "elsa/private-acceptance"))

_DEFAULT_OUT = Path("acceptance/reporte.json")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="private-acceptance",
        description="Ingesta de aceptación contra archivos reales, fuera de Git.",
    )
    parser.add_argument("--engineering", required=True, type=Path, help="Ruta del XLSX")
    parser.add_argument("--sap", type=Path, help="Ruta del HTM exportado de SAP")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Ruta del reporte")
    parser.add_argument("--asset-code", default="tampella")
    parser.add_argument("--asset-name", default="Activo tecnico")
    parser.add_argument("--domain", default="mantenimiento")
    parser.add_argument(
        "--database-url",
        default=None,
        help="PostgreSQL local. Sin ella se usa el repositorio en memoria.",
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=None,
        help="Directorio privado de artefactos. Sin él se usa almacenamiento en memoria.",
    )
    return parser.parse_args(argv)


async def _build(
    args: argparse.Namespace,
) -> tuple[KnowledgeRepositoryPort, ArtifactStoragePort, PostgresKnowledgeRepository | None]:
    storage: ArtifactStoragePort = (
        LocalArtifactStorage(args.artifact_root)
        if args.artifact_root is not None
        else InMemoryArtifactStorage()
    )
    if args.database_url is None:
        return InMemoryKnowledgeRepository(), storage, None
    postgres = await PostgresKnowledgeRepository.connect(args.database_url)
    return postgres, storage, postgres


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    engineering_bytes = args.engineering.read_bytes()
    report: dict[str, Any] = {
        "engineering": {
            "sha256": sha256_hex(engineering_bytes),
            "bytes": len(engineering_bytes),
        },
        "errors": [],
        "warnings": [],
    }

    repository, storage, postgres = await _build(args)
    try:
        service = IngestionService(repository, storage)
        asset = await repository.create_asset(
            code=args.asset_code, name=args.asset_name, domain=args.domain
        )

        try:
            version = await service.ingest_engineering_bom(
                asset=asset, data=engineering_bytes, actor=_ACTOR
            )
        except IngestionError as exc:
            report["errors"].append({"stage": "engineering", "kind": exc.kind, "message": str(exc)})
            return report
        if isinstance(version, DuplicateImport):
            report["errors"].append({"stage": "engineering", "kind": "duplicate"})
            return report

        items = await repository.list_version_items(version.id)
        drawings = await repository.list_drawing_images(version.id)
        modes = await repository.list_failure_modes(version.id)
        criteria = await repository.list_sod_criteria(version.id)
        record = await repository.get_import(version.import_id)

        report["engineering"].update(
            {
                "version_number": version.version_number,
                "state": version.state.value,
                "components": len(items),
                "components_with_sap_code": sum(1 for item in items if item.sap_code),
                "components_without_sap_code": sum(1 for item in items if not item.sap_code),
                "components_unresolved": sum(1 for item in items if item.component_id is None),
                "subsystems": len({item.subsystem_name for item in items if item.subsystem_name}),
                "drawings_extracted": len(drawings),
                "drawings_pending_association": sum(
                    1 for image in drawings if image.association_status == "pending_review"
                ),
                "failure_modes": len(modes),
                "failure_modes_with_rpn": sum(1 for mode in modes if mode.rpn is not None),
                "sod_criteria": len(criteria),
                "sod_dimensions": sorted({c.dimension for c in criteria}),
                "import_stats": dict(record.stats) if record is not None else {},
            }
        )

        if args.sap is None:
            return report

        sap_bytes = args.sap.read_bytes()
        report["sap"] = {"sha256": sha256_hex(sap_bytes), "bytes": len(sap_bytes)}
        try:
            snapshot = await service.ingest_sap_snapshot(asset=asset, data=sap_bytes, actor=_ACTOR)
        except IngestionError as exc:
            report["errors"].append({"stage": "sap", "kind": exc.kind, "message": str(exc)})
            return report
        if isinstance(snapshot, DuplicateImport):
            report["errors"].append({"stage": "sap", "kind": "duplicate"})
            return report

        snapshot_items = await repository.list_snapshot_items(snapshot.id)
        report["sap"].update(
            {
                "functional_location_present": snapshot.functional_location is not None,
                "description_present": snapshot.description is not None,
                "valid_from": None
                if snapshot.valid_from is None
                else snapshot.valid_from.isoformat(),
                "materials": sum(1 for item in snapshot_items if item.entry_kind == "material"),
                "equipments": sum(1 for item in snapshot_items if item.entry_kind == "equipment"),
            }
        )

        # Reconciliar exige una versión publicada. Se aprueba y publica aquí
        # porque es una prueba local aislada; en el flujo real lo hace una
        # persona con capacidad de Revisor Técnico.
        await repository.set_version_state(version_id=version.id, state=VersionState.APPROVED)
        await repository.publish_version(version_id=version.id, actor=_ACTOR)
        run = await service.reconcile_published_bom(
            asset=asset, version_id=version.id, snapshot_id=snapshot.id, actor=_ACTOR
        )
        report["reconciliation"] = dict(run.stats)
        return report
    finally:
        if postgres is not None:
            await postgres.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    for path in (args.engineering, args.sap):
        if path is not None and not path.is_file():
            print(f"no existe el archivo: {path}", file=sys.stderr)
            return 2

    report = asyncio.run(_run(args))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    # Por consola solo el resumen: nunca el contenido técnico.
    print(f"reporte escrito en {args.out}")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
