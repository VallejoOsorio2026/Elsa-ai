"""Reglas compartidas de persistencia documental, sin acceso a infraestructura."""

import uuid
from collections.abc import Sequence
from dataclasses import asdict

from elsa.ports.documents import (
    DocumentChunkRecord,
    DocumentIngestionRunRecord,
    DocumentIntegrityError,
    DocumentSectionRecord,
    DocumentVersionEventRecord,
    DocumentVersionInput,
    DocumentVersionRecord,
    DocumentVersionState,
    NotPublishableError,
    VersionConflictError,
)


def require_reason(reason: str | None) -> None:
    if reason is None or not reason.strip():
        raise NotPublishableError("rejecting a version requires a nonblank reason")


def validate_transition(
    current: DocumentVersionState, target: DocumentVersionState, reason: str | None
) -> None:
    if current is DocumentVersionState.PUBLISHED:
        raise NotPublishableError("a published version cannot change state directly")
    if target not in (DocumentVersionState.APPROVED, DocumentVersionState.REJECTED):
        raise NotPublishableError("only approval or rejection is allowed here")
    if target is DocumentVersionState.REJECTED:
        require_reason(reason)


def require_publishable(state: DocumentVersionState) -> None:
    if state is not DocumentVersionState.APPROVED:
        raise NotPublishableError("only an approved version can be published")


def validate_source(
    data: DocumentVersionInput, run: DocumentIngestionRunRecord, source_sha256: str | None
) -> None:
    if (
        data.document_id != run.document_id
        or data.source_artifact_id != run.source_artifact_id
        or data.content_sha256 != source_sha256
    ):
        raise DocumentIntegrityError("document, run, original and hash must correspond")


def content_records(
    data: DocumentVersionInput, version_id: str
) -> tuple[list[DocumentSectionRecord], list[DocumentChunkRecord]]:
    paths: set[str] = set()
    for ordinal, section in enumerate(data.structure.sections):
        if (
            section.ordinal != ordinal
            or section.path in paths
            or (section.parent_path is not None and section.parent_path not in paths)
        ):
            raise DocumentIntegrityError("invalid section order or parent")
        paths.add(section.path)
    keys: set[str] = set()
    for ordinal, chunk in enumerate(data.structure.chunks):
        if (
            chunk.ordinal != ordinal
            or chunk.structural_key in keys
            or (chunk.section_path is not None and chunk.section_path not in paths)
        ):
            raise DocumentIntegrityError("invalid chunk order or section")
        keys.add(chunk.structural_key)
    # Las secciones llegan en orden de lectura, asi que el padre
    # siempre esta ya registrado cuando se procesa un hijo.
    section_ids: dict[str, str] = {}
    sections: list[DocumentSectionRecord] = []
    for section in data.structure.sections:
        identifier = str(uuid.uuid4())
        section_ids[section.path] = identifier
        sections.append(
            DocumentSectionRecord(
                id=identifier,
                version_id=version_id,
                ordinal=section.ordinal,
                path=section.path,
                depth=section.depth,
                title=section.title,
                parent_id=(
                    None if section.parent_path is None else section_ids[section.parent_path]
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
            id=str(uuid.uuid4()),
            version_id=version_id,
            ordinal=chunk.ordinal,
            structural_key=chunk.structural_key,
            content=chunk.content,
            content_sha256=chunk.content_sha256,
            kind=chunk.kind,
            section_id=(None if chunk.section_path is None else section_ids[chunk.section_path]),
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

    return sections, chunks


def _section_content(section: DocumentSectionRecord) -> dict[str, object]:
    return {k: v for k, v in asdict(section).items() if k not in {"id", "version_id", "parent_id"}}


def _chunk_content(chunk: DocumentChunkRecord) -> dict[str, object]:
    return {k: v for k, v in asdict(chunk).items() if k not in {"id", "version_id", "section_id"}}


def validate_retry(
    data: DocumentVersionInput,
    version: DocumentVersionRecord,
    run: DocumentIngestionRunRecord,
    sections: Sequence[DocumentSectionRecord],
    chunks: Sequence[DocumentChunkRecord],
    created: DocumentVersionEventRecord,
    *,
    actor: str,
    request_id: str | None,
) -> None:
    expected_sections, expected_chunks = content_records(data, version.id)
    if (
        (
            data.document_id,
            data.run_id,
            data.source_artifact_id,
            data.content_sha256,
            data.structure.structure_sha256,
            data.structure.policy.name,
            dict(data.structure.policy.parameters()),
            data.extractor,
            data.extractor_version,
        )
        != (
            version.document_id,
            version.run_id,
            version.source_artifact_id,
            version.content_sha256,
            version.structure_sha256,
            version.chunking_profile,
            dict(version.chunking_parameters),
            version.extractor,
            version.extractor_version,
        )
        or dict(data.stats) != dict(run.stats)
        or (actor, request_id) != (created.actor, created.request_id)
        or [_section_content(s) for s in expected_sections]
        != [_section_content(s) for s in sections]
        or [_chunk_content(c) for c in expected_chunks] != [_chunk_content(c) for c in chunks]
    ):
        raise VersionConflictError("the ingestion run already stores a different operation")
