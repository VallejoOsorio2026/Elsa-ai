"""Constructores de evidencia sintética, sin base de datos.

Las piezas del RAG —selección de contexto, verificación de citas, política de
estado— son funciones de la evidencia que reciben, así que se prueban con
evidencia construida a mano. Montar PostgreSQL para comprobar que un texto
duplicado no se cuenta dos veces sería confundir dos preguntas distintas.

Las pruebas que sí necesitan la base están en `test_rag_end_to_end.py`: allí lo
que se comprueba es justamente que el aislamiento sobrevive al camino completo.
"""

import hashlib
from datetime import UTC, datetime

from elsa.ports.documents import (
    ChunkKind,
    ChunkProvenance,
    DocumentChunkRecord,
    DocumentRecord,
    DocumentSectionRecord,
    DocumentSourceKind,
    DocumentVersionRecord,
    DocumentVersionState,
)
from elsa.ports.evidence import (
    Channel,
    ChannelHit,
    Evidence,
    EvidenceSet,
    EvidenceStrength,
)

_CREATED = datetime(2026, 1, 1, tzinfo=UTC)


def make_provenance(
    *,
    chunk_id: str = "chunk-1",
    content: str = "El rodamiento SAP-4471 se lubrica cada 500 horas.",
    document_code: str = "MAN-P200",
    document_title: str = "Manual de la prensa P-200",
    domain: str = "mantenimiento",
    asset_code: str | None = "asset-a",
    version_number: int = 1,
    state: DocumentVersionState = DocumentVersionState.PUBLISHED,
    section_title: str | None = "Lubricación",
    section_label: str | None = "1",
    page_start: int | None = 3,
    page_end: int | None = 3,
) -> ChunkProvenance:
    """Una procedencia completa: sin ella un chunk no puede sostener nada."""
    document = DocumentRecord(
        id=f"doc-{document_code}",
        domain=domain,
        code=document_code,
        title=document_title,
        source_kind=DocumentSourceKind.MANUAL,
        asset_code=asset_code,
        language="es",
    )
    version = DocumentVersionRecord(
        id=f"ver-{document_code}-{version_number}",
        document_id=document.id,
        run_id="run-1",
        source_artifact_id="art-1",
        version_number=version_number,
        state=state,
        content_sha256="0" * 64,
        structure_sha256="1" * 64,
        chunking_profile="structural-v1",
        chunking_parameters={},
        extractor="structured-text",
        extractor_version="1",
        created_at=_CREATED,
    )
    section = None
    if section_title is not None:
        section = DocumentSectionRecord(
            id=f"sec-{chunk_id}",
            version_id=version.id,
            ordinal=1,
            path="1",
            depth=1,
            title=section_title,
            number_label=section_label,
        )
    chunk = DocumentChunkRecord(
        id=chunk_id,
        version_id=version.id,
        ordinal=1,
        structural_key="1#0001",
        content=content,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        kind=ChunkKind.PROSE,
        section_id=None if section is None else section.id,
        section_title=section_title,
        page_start=page_start,
        page_end=page_end,
        char_length=len(content),
    )
    return ChunkProvenance(
        chunk=chunk,
        document=document,
        version=version,
        section=section,
        source_sha256="2" * 64,
        source_storage_key=f"private/{document_code}.pdf",
    )


def make_evidence(
    provenance: ChunkProvenance | None = None,
    *,
    rank: int = 1,
    channels: tuple[Channel, ...] = (Channel.LEXICAL,),
    fused_score: float = 0.016393,
) -> Evidence:
    provenance = provenance or make_provenance()
    return Evidence(
        provenance=provenance,
        hits=tuple(
            ChannelHit(channel=channel, rank=rank, score=1.0) for channel in sorted(set(channels))
        ),
        fused_score=fused_score,
        rank=rank,
    )


def make_evidence_set(
    *evidence: Evidence,
    strength: EvidenceStrength | None = None,
    channels_queried: tuple[Channel, ...] = (Channel.LEXICAL,),
    identifiers: tuple[str, ...] = (),
) -> EvidenceSet:
    """Reproduce la regla de fuerza del servicio híbrido cuando no se fija.

    Se deriva en vez de fijarse por defecto para que una prueba no declare
    accidentalmente «suficiente» una evidencia que el retrieval real habría
    marcado débil.
    """
    if strength is None:
        if not evidence:
            strength = EvidenceStrength.NONE
        elif evidence[0].has_exact_match or evidence[0].found_by_multiple_channels:
            strength = EvidenceStrength.SUFFICIENT
        else:
            strength = EvidenceStrength.WEAK
    return EvidenceSet(
        evidence=tuple(evidence),
        strength=strength,
        channels_queried=channels_queried,
        identifiers_detected=identifiers,
    )
