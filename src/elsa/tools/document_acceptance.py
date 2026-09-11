"""Prueba de aceptación determinística de la ingesta documental.

Ejecuta la ingesta completa —extracción, seccionado, chunking, validación,
comparación entre versiones y publicación— sobre un documento y escribe un
reporte con todo lo que hace falta para decidir si el bloque pasa:

    uv run python -m elsa.tools.document_acceptance \\
        --input "<ruta del documento>" \\
        --second "<ruta de la version 2>" \\
        --out "<ruta del reporte>"

Contrato de salida, que es lo que decide si el bloque pasa o no:

- **0** — el documento se procesó, la validación no encontró nada bloqueante
  y ``errors`` está vacío. Puede haber ``warnings``: un chunk
  sobredimensionado o una tabla partida son cosas que una persona debe
  mirar, no fallos del proceso.
- **1** — aceptación fallida. El documento no pudo procesarse, la validación
  lo rechazó, o quedó cualquier entrada en ``errors``. El reporte se escribe
  igualmente, porque es el material con el que se diagnostica.
- **2** — no se pudo ni intentar: falta el archivo de entrada o el reporte no
  se puede escribir.

No existe el éxito parcial. Un reporte con ``errors`` **nunca** termina en 0,
para que no pueda confundirse con una aceptación aprobada.

## Qué reporta

Secciones detectadas con su árbol, chunks con su orden y su clave
estructural, páginas, títulos, hashes, metadata, avisos y la reconstrucción
de la procedencia de cada chunk. Además comprueba dos cosas que no se ven
mirando el resultado:

- **Idempotencia**: procesa el documento dos veces y compara las huellas.
- **Reconstrucción**: verifica que los desplazamientos de cada chunk
  apuntan a texto real del documento original.

## Qué no lleva el reporte

**El texto de los chunks no se incluye por defecto.** Los títulos y la
metadata sí, porque sin ellos el reporte no sirve para aceptar nada; el
contenido no, porque un reporte de un manual interno filtrado por accidente
revelaría el manual entero. ``--include-text`` lo añade de forma explícita y
el propio reporte deja constancia de que lo lleva.

Reglas que esta herramienta respeta, igual que su equivalente estructurada
(``elsa.tools.private_acceptance``):

- **Los documentos no se copian al repositorio.** Se leen desde su ruta.
- **Nada se publica en ningún sitio real.** Todo ocurre en adaptadores en
  memoria: no se toca ningún Supabase ni ningún almacenamiento persistente.

Ver ``docs/document-acceptance.md``.
"""

import argparse
import asyncio
import json
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.memory_documents import InMemoryDocumentRepository
from elsa.adapters.structured_text_extractor import StructuredTextExtractor
from elsa.core.authorization import Principal
from elsa.core.document_access import readable_scopes
from elsa.documents.chunking import chunk_document
from elsa.documents.model import ChunkingPolicy, DocumentStructure
from elsa.ports.document_extraction import ExtractedDocument
from elsa.ports.documents import DocumentRecord, DocumentSourceKind
from elsa.services.document_ingestion import (
    DocumentIngestionError,
    DocumentIngestionService,
    DuplicateDocumentSource,
    IngestedVersion,
)

# Actor sintético: esta herramienta no autentica a nadie ni necesita hacerlo.
_ACTOR = str(uuid.uuid5(uuid.NAMESPACE_URL, "elsa/document-acceptance"))

_DEFAULT_OUT = Path("acceptance/documento.json")

_CONTENT_TYPES = {
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".text": "text/plain",
}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="document-acceptance",
        description="Ingesta documental de aceptacion, con reporte determinístico.",
    )
    parser.add_argument("--input", required=True, type=Path, help="Ruta del documento")
    parser.add_argument(
        "--second",
        type=Path,
        help="Segunda version del mismo documento, para comparar v1 contra v2",
    )
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT, help="Ruta del reporte")
    parser.add_argument(
        "--title", default="Documento de aceptacion", help="Titulo del documento en ELSA"
    )
    parser.add_argument("--domain", default="mantenimiento")
    parser.add_argument(
        "--asset-code",
        help="Codigo del activo al que aplica. Sin el, el documento aplica al dominio.",
    )
    parser.add_argument(
        "--source-kind",
        default=DocumentSourceKind.MANUAL.value,
        choices=[kind.value for kind in DocumentSourceKind],
    )
    parser.add_argument("--target-tokens", type=int, default=ChunkingPolicy().target_tokens)
    parser.add_argument("--max-tokens", type=int, default=ChunkingPolicy().max_tokens)
    parser.add_argument("--min-tokens", type=int, default=ChunkingPolicy().min_tokens)
    parser.add_argument("--overlap-tokens", type=int, default=ChunkingPolicy().overlap_tokens)
    parser.add_argument(
        "--include-text",
        action="store_true",
        help="Incluye el texto de cada chunk. El reporte pasa a contener el documento.",
    )
    return parser.parse_args(argv)


def _content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "text/plain")


async def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    """Ejecuta la aceptación y devuelve el reporte y el código de salida."""
    report: dict[str, Any] = {
        "tool": "document-acceptance",
        "includes_document_text": bool(args.include_text),
        "errors": [],
        "warnings": {},
    }
    errors: list[str] = report["errors"]

    try:
        content = args.input.read_bytes()
    except OSError as error:
        report["errors"].append(f"the input document could not be read: {error.strerror}")
        return report, 2

    policy = ChunkingPolicy(
        name="acceptance",
        target_tokens=args.target_tokens,
        max_tokens=args.max_tokens,
        min_tokens=args.min_tokens,
        overlap_tokens=args.overlap_tokens,
    )
    repository = InMemoryDocumentRepository()
    extractor = StructuredTextExtractor()
    service = DocumentIngestionService(
        repository=repository,
        storage=InMemoryArtifactStorage(),
        extractor=extractor,
        policy=policy,
    )

    document = await repository.create_document(
        domain=args.domain,
        code="acceptance",
        title=args.title,
        source_kind=DocumentSourceKind(args.source_kind),
        asset_code=args.asset_code,
    )

    report["policy"] = policy.parameters()
    report["input"] = {
        "filename": args.input.name,
        "content_type": _content_type(args.input),
        "bytes": len(content),
    }

    try:
        first = await service.ingest(
            document=document,
            content=content,
            content_type=_content_type(args.input),
            filename=args.input.name,
            actor=_ACTOR,
        )
    except DocumentIngestionError as error:
        report["errors"].append(f"{error.failure_kind}: {error}")
        if error.report is not None:
            report["validation"] = _validation(error)
        return report, 1

    if isinstance(first, DuplicateDocumentSource):
        report["errors"].append("the document was reported as already ingested")
        return report, 1

    extracted = await extractor.extract(
        content, content_type=_content_type(args.input), filename=args.input.name
    )
    report.update(_describe(first, extracted, policy, include_text=args.include_text))
    report["determinism"] = _determinism(extracted, first, document, policy)
    report["provenance"] = await _provenance(repository, first, extracted, errors)
    report["authorization"] = _authorization(document)

    await service.approve(version_id=first.version.id, actor=_ACTOR)
    published = await service.publish(version_id=first.version.id, actor=_ACTOR)
    report["lifecycle"] = {
        "version_number": published.version_number,
        "state": published.state.value,
        "published": True,
        "events": [
            event.event.value for event in await repository.list_version_events(published.id)
        ],
    }

    if args.second is not None:
        report["second_version"] = await _second_version(
            service, repository, document, args, errors
        )

    report["warnings"] = dict(first.structure.warning_counts())
    return report, 1 if errors else 0


def _validation(error: DocumentIngestionError) -> dict[str, Any]:
    assert error.report is not None  # noqa: S101 - solo se llama cuando lo hay
    return {
        "valid": error.report.is_valid,
        "blocking": [issue.code for issue in error.report.blocking],
        "issues": error.report.counts(),
    }


def _describe(
    result: IngestedVersion,
    extracted: ExtractedDocument,
    policy: ChunkingPolicy,
    *,
    include_text: bool,
) -> dict[str, Any]:
    structure = result.structure
    blocks_by_kind: dict[str, int] = {}
    for block in extracted.blocks:
        blocks_by_kind[block.kind.value] = blocks_by_kind.get(block.kind.value, 0) + 1

    chunks_per_section: dict[str, int] = {}
    for chunk in structure.chunks:
        key = chunk.section_path or ""
        chunks_per_section[key] = chunks_per_section.get(key, 0) + 1

    return {
        "extraction": {
            "extractor": extracted.extractor,
            "extractor_version": extracted.extractor_version,
            "pages": extracted.page_count,
            "blocks": len(extracted.blocks),
            "blocks_by_kind": dict(sorted(blocks_by_kind.items())),
        },
        "structure_sha256": structure.structure_sha256,
        "totals": {
            "sections": len(structure.sections),
            "chunks": len(structure.chunks),
            "tokens": sum(chunk.token_estimate for chunk in structure.chunks),
            "oversized_chunks": sum(1 for chunk in structure.chunks if chunk.oversized),
            "chunks_with_overlap": sum(1 for chunk in structure.chunks if chunk.overlap_chars),
        },
        "validation": {
            "valid": result.report.is_valid,
            "blocking": [issue.code for issue in result.report.blocking],
            "issues": result.report.counts(),
        },
        "changes": result.change_counts(),
        "sections": [
            {
                "ordinal": section.ordinal,
                "path": section.path,
                "parent_path": section.parent_path,
                "depth": section.depth,
                "number_label": section.number_label,
                "title": section.title,
                "page_start": section.page_start,
                "page_end": section.page_end,
                "is_preamble": section.is_preamble,
                "chunks": chunks_per_section.get(section.path, 0),
            }
            for section in structure.sections
        ],
        "chunks": [_chunk(chunk, policy, include_text=include_text) for chunk in structure.chunks],
    }


def _chunk(chunk: Any, policy: ChunkingPolicy, *, include_text: bool) -> dict[str, Any]:
    described = {
        "ordinal": chunk.ordinal,
        "structural_key": chunk.structural_key,
        "section_path": chunk.section_path,
        "section_title": chunk.section_title,
        "heading_trail": list(chunk.heading_trail),
        "index_in_section": chunk.index_in_section,
        "kind": chunk.kind.value,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "block_start": chunk.block_start,
        "block_end": chunk.block_end,
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "token_estimate": chunk.token_estimate,
        "char_length": chunk.char_length,
        "overlap_chars": chunk.overlap_chars,
        "boundary_reason": chunk.boundary_reason,
        "oversized": chunk.oversized,
        "over_max_tokens": chunk.token_estimate > policy.max_tokens,
        "content_sha256": chunk.content_sha256,
        "warnings": list(chunk.warnings),
    }
    if include_text:
        described["content"] = chunk.content
    return described


def _determinism(
    extracted: ExtractedDocument,
    result: IngestedVersion,
    document: DocumentRecord,
    policy: ChunkingPolicy,
) -> dict[str, Any]:
    """Vuelve a chunkear lo ya extraído y compara las huellas.

    Es la comprobación que no se puede hacer mirando el resultado una sola
    vez: dos ejecuciones que den huellas distintas significan que algo del
    chunking depende de un valor que no está en el documento.
    """
    repeated: DocumentStructure = chunk_document(
        extracted, document_title=document.title, policy=policy
    )
    return {
        "structure_sha256": result.structure.structure_sha256,
        "repeated_structure_sha256": repeated.structure_sha256,
        "identical": repeated.structure_sha256 == result.structure.structure_sha256,
        "identical_chunk_hashes": [chunk.content_sha256 for chunk in repeated.chunks]
        == [chunk.content_sha256 for chunk in result.structure.chunks],
    }


async def _provenance(
    repository: InMemoryDocumentRepository,
    result: IngestedVersion,
    extracted: ExtractedDocument,
    errors: list[str],
) -> dict[str, Any]:
    """Comprueba que cada chunk puede volver hasta el texto que lo produjo."""
    stored = await repository.list_chunks(result.version.id)
    complete = 0
    reconstructed = 0
    citations: list[str] = []

    for chunk in stored:
        provenance = await repository.get_chunk_provenance(chunk.id)
        if provenance is None:
            errors.append(f"chunk {chunk.structural_key} has no reconstructable provenance")
            continue
        if all(
            value is not None
            for value in (
                provenance.section,
                chunk.section_path,
                chunk.page_start,
                chunk.char_start,
                chunk.char_end,
            )
        ):
            complete += 1
        if (
            chunk.char_start is not None
            and chunk.char_end is not None
            and extracted.text[chunk.char_start : chunk.char_end].strip()
        ):
            reconstructed += 1
        if len(citations) < 3:
            citations.append(provenance.citation())

    if complete != len(stored):
        errors.append(f"{len(stored) - complete} chunks are missing part of their provenance")
    if reconstructed != len(stored):
        errors.append(f"{len(stored) - reconstructed} chunks do not point back at the source text")

    return {
        "chunks": len(stored),
        "with_complete_provenance": complete,
        "pointing_back_at_the_source": reconstructed,
        "sample_citations": citations,
    }


def _authorization(document: DocumentRecord) -> dict[str, Any]:
    """Deja constancia del alcance que hay que autorizar antes de recuperar."""
    stranger = Principal(external_user_id=_ACTOR, display_name=None, is_active=True, is_admin=False)
    holder = Principal(
        external_user_id=_ACTOR,
        display_name=None,
        is_active=True,
        is_admin=False,
        scopes=(document.scope,),
    )
    return {
        "required_scope": {
            "domain": document.scope.domain,
            "equipment": document.scope.equipment,
        },
        "readable_without_permission": [
            f"{scope.domain}/{scope.equipment or '*'}"
            for scope in readable_scopes(stranger, [document])
        ],
        "readable_with_permission": [
            f"{scope.domain}/{scope.equipment or '*'}"
            for scope in readable_scopes(holder, [document])
        ],
    }


async def _second_version(
    service: DocumentIngestionService,
    repository: InMemoryDocumentRepository,
    document: DocumentRecord,
    args: argparse.Namespace,
    errors: list[str],
) -> dict[str, Any]:
    """Ingiere la versión 2 y reporta qué cambió respecto de la publicada."""
    try:
        content = args.second.read_bytes()
    except OSError as error:
        errors.append(f"the second version could not be read: {error.strerror}")
        return {"ingested": False}

    try:
        result = await service.ingest(
            document=document,
            content=content,
            content_type=_content_type(args.second),
            filename=args.second.name,
            actor=_ACTOR,
        )
    except DocumentIngestionError as error:
        errors.append(f"second version: {error.failure_kind}: {error}")
        return {"ingested": False}

    if isinstance(result, DuplicateDocumentSource):
        # Es una respuesta correcta si el archivo es idéntico, y un fallo de
        # la prueba si se pretendía comparar dos versiones distintas.
        errors.append("the second version is byte-identical to the first")
        return {"ingested": False, "duplicate": True}

    published = await repository.get_published_version(document.id)
    return {
        "ingested": True,
        "version_number": result.version.version_number,
        "state": result.version.state.value,
        "structure_sha256": result.structure.structure_sha256,
        "changes": result.change_counts(),
        # La versión nueva no reemplaza sola a la publicada: sigue siendo la 1.
        "published_version_after_ingest": None if published is None else published.version_number,
        "sections": len(result.structure.sections),
        "chunks": len(result.structure.chunks),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report, code = asyncio.run(run(args))
    except ValueError as error:
        # Límites de chunking incoherentes, por ejemplo.
        print(f"invalid arguments: {error}", file=sys.stderr)
        return 2

    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
            encoding="utf-8",
        )
    except OSError as error:
        print(f"the report could not be written: {error.strerror}", file=sys.stderr)
        return 2

    totals = report.get("totals", {})
    print(
        f"sections={totals.get('sections', 0)} chunks={totals.get('chunks', 0)} "
        f"errors={len(report['errors'])} report={args.out}"
    )
    for message in report["errors"]:
        print(f"  error: {message}", file=sys.stderr)
    return code


if __name__ == "__main__":  # pragma: no cover - punto de entrada
    raise SystemExit(main())
