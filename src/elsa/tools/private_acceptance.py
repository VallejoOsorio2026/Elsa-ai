"""Prueba de aceptación privada contra los archivos reales.

Ejecuta la ingesta completa —XLSX de Ingeniería, HTM de SAP y
reconciliación— sobre archivos que viven **fuera del repositorio**, y
escribe un reporte de conteos en una ruta ignorada por Git.

    uv run python -m elsa.tools.private_acceptance \\
        --engineering "<ruta del xlsx>" \\
        --sap "<ruta del htm>" \\
        --out "<ruta del reporte>"

Contrato de salida, que es lo que decide si el bloque pasa o no:

- **0** — las dos fuentes obligatorias se procesaron y ``errors`` está
  vacío. Puede haber ``warnings``: un plano sin asociar o una fórmula sin
  evaluar son cosas que una persona debe mirar, no fallos del proceso.
- **1** — aceptación fallida. Alguna fuente obligatoria no pudo procesarse,
  o quedó cualquier entrada en ``errors``. El reporte se escribe igualmente,
  porque es el material con el que se diagnostica.
- **2** — no se pudo ni intentar: falta un archivo de entrada o el reporte
  no se puede escribir.

No existe el éxito parcial. Un reporte con ``errors`` **nunca** termina en
0, para que no pueda confundirse con una aceptación aprobada.

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
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from elsa.adapters.local_artifact_storage import LocalArtifactStorage
from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.postgres_knowledge import PostgresKnowledgeRepository
from elsa.ingestion.errors import IngestionError
from elsa.ports.artifact_storage import (
    ArtifactStoragePort,
    ArtifactStorageUnavailableError,
    sha256_hex,
)
from elsa.ports.knowledge import (
    KnowledgeRepositoryPort,
    KnowledgeUnavailableError,
    VersionState,
)
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
    # Obligatoria: sin el snapshot de SAP no hay reconciliación, y una
    # aceptación que se salta media prueba no es una aceptación.
    parser.add_argument("--sap", required=True, type=Path, help="Ruta del HTM exportado de SAP")
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Ruta del reporte")
    # Obligatoria: el activo lo nombra quien ejecuta la prueba. Un valor por
    # defecto convertía a Tampella en el equipo que la herramienta da por
    # supuesto, y esta herramienta va a servir para cualquier otro.
    parser.add_argument(
        "--asset-code", required=True, help="Codigo del activo, p. ej. el que use la planta"
    )
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


def _collect_warnings(stage: str, stats: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Traduce los avisos guardados en la importación a entradas del reporte."""
    raw = stats.get("warnings") or {}
    if not isinstance(raw, Mapping):
        return []
    return [
        {"stage": stage, "code": str(code), "count": int(count)}
        for code, count in sorted(raw.items())
    ]


def _merge_warning(
    report: dict[str, Any], *, stage: str, code: str, count: int, message: str
) -> None:
    """Añade un aviso, o enriquece el que ya exista con ese mismo código."""
    for warning in report["warnings"]:
        if warning["stage"] == stage and warning["code"] == code:
            warning["count"] = count
            warning["message"] = message
            return
    report["warnings"].append({"stage": stage, "code": code, "count": count, "message": message})


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
        except (ArtifactStorageUnavailableError, KnowledgeUnavailableError) as exc:
            # Un fallo de infraestructura no es un archivo inválido, pero
            # tampoco es un éxito: se distingue en el reporte y falla igual.
            report["errors"].append(
                {"stage": "engineering", "kind": "infrastructure", "message": str(exc)}
            )
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
        if record is not None:
            report["warnings"].extend(_collect_warnings("engineering", record.stats))

        pending = report["engineering"]["drawings_pending_association"]
        if pending:
            # Un plano sin asociación cierta no es un fallo, pero tampoco
            # puede pasar desapercibido: alguien tiene que asociarlo a mano.
            # El parser ya emite este código; aquí solo se le añade el conteo
            # y el texto para una persona, sin duplicar la entrada.
            _merge_warning(
                report,
                stage="engineering",
                code="drawing_association_pending",
                count=pending,
                message=(
                    f"{pending} drawing artifact(s) require manual association: "
                    "the link to a drawing number is never guessed."
                ),
            )

        sap_bytes = args.sap.read_bytes()
        report["sap"] = {"sha256": sha256_hex(sap_bytes), "bytes": len(sap_bytes)}
        try:
            snapshot = await service.ingest_sap_snapshot(asset=asset, data=sap_bytes, actor=_ACTOR)
        except IngestionError as exc:
            report["errors"].append({"stage": "sap", "kind": exc.kind, "message": str(exc)})
            # Conteos por etapa: permiten saber DÓNDE falló el parseo de un
            # archivo que no puede compartirse, sin ver nada de su contenido.
            if exc.diagnostics:
                report["sap_parser_diagnostics"] = dict(exc.diagnostics)
            return report
        except (ArtifactStorageUnavailableError, KnowledgeUnavailableError) as exc:
            report["errors"].append({"stage": "sap", "kind": "infrastructure", "message": str(exc)})
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
        sap_record = await repository.get_import(snapshot.import_id)
        if sap_record is not None:
            report["warnings"].extend(_collect_warnings("sap", sap_record.stats))
        if sap_record is not None:
            # También en el caso correcto: sirve de trazabilidad de qué vio el
            # parser, y sigue siendo solo conteos.
            diagnostics = sap_record.stats.get("parser_diagnostics")
            if isinstance(diagnostics, Mapping):
                report["sap_parser_diagnostics"] = dict(diagnostics)

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


EXIT_OK = 0
EXIT_ACCEPTANCE_FAILED = 1
EXIT_CANNOT_RUN = 2


def _summary(report: Mapping[str, Any]) -> str:
    """Resumen legible del reporte. Conteos y estados, nunca contenido."""
    lines: list[str] = []
    engineering = report.get("engineering", {})
    lines.append("  Ingeniería (XLSX)")
    for key in (
        "components",
        "components_with_sap_code",
        "components_without_sap_code",
        "components_unresolved",
        "subsystems",
        "failure_modes",
        "failure_modes_with_rpn",
        "drawings_extracted",
        "drawings_pending_association",
        "sod_criteria",
    ):
        if key in engineering:
            lines.append(f"    {key:32} {engineering[key]}")
    if "sod_dimensions" in engineering:
        lines.append(f"    {'sod_dimensions':32} {', '.join(engineering['sod_dimensions']) or '—'}")

    sap = report.get("sap")
    if sap:
        lines.append("  SAP (HTM)")
        for key in ("materials", "equipments", "valid_from"):
            if key in sap:
                lines.append(f"    {key:32} {sap[key]}")
        lines.append(
            f"    {'functional_location_present':32} {sap.get('functional_location_present')}"
        )

    reconciliation = report.get("reconciliation")
    if reconciliation:
        lines.append("  Reconciliación")
        for name, count in sorted(reconciliation.items()):
            lines.append(f"    {name:32} {count}")

    diagnostics = report.get("sap_parser_diagnostics")
    if diagnostics:
        # Solo conteos por etapa: dicen dónde se detuvo el parseo sin revelar
        # una sola línea del archivo.
        lines.append("  Diagnóstico del parser SAP")
        for name, count in diagnostics.items():
            lines.append(f"    {name:32} {count}")

    lines.append(f"  warnings: {len(report.get('warnings', []))}")
    for warning in report.get("warnings", []):
        lines.append(f"    - {warning['stage']}/{warning['code']}: {warning.get('count', 1)}")
    lines.append(f"  errors:   {len(report.get('errors', []))}")
    for error in report.get("errors", []):
        lines.append(f"    - {error['stage']}/{error['kind']}: {error.get('message', '')}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    for path in (args.engineering, args.sap):
        if not path.is_file():
            print(f"no existe el archivo: {path}", file=sys.stderr)
            return EXIT_CANNOT_RUN

    report = asyncio.run(_run(args))
    report["verdict"] = "failed" if report["errors"] else "passed"

    # El reporte se escribe pase lo que pase: si la aceptación falló, es
    # justamente el material con el que se diagnostica el fallo.
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        print(f"no se pudo escribir el reporte en {args.out}: {exc}", file=sys.stderr)
        print(_summary(report), file=sys.stderr)
        return EXIT_CANNOT_RUN

    # Por consola solo el resumen: nunca el contenido técnico.
    print(_summary(report))
    print(f"\nreporte completo en {args.out}")
    if report["errors"]:
        print("\nACEPTACIÓN FALLIDA: hay errores en una fuente obligatoria.", file=sys.stderr)
        return EXIT_ACCEPTANCE_FAILED
    print("\nACEPTACIÓN CORRECTA: ninguna fuente obligatoria falló.")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
