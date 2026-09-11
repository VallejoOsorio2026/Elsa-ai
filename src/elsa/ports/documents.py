"""Puerto del conocimiento documental de ELSA.

Única vía por la que el backend lee y escribe documentos, versiones,
ejecuciones de ingesta, secciones y chunks.

Es el gemelo documental de :mod:`elsa.ports.knowledge` y sigue sus mismas
reglas, porque los problemas son los mismos:

- Un archivo ya ingerido se reconoce por su hash y no genera una versión
  duplicada.
- Una ingesta fallida **no toca la última versión publicada**.
- Solo hay una versión publicada por documento, y publicar es atómico.
- Una versión nueva nunca reemplaza sola a la publicada.
- Nada se sobrescribe: publicar marca la anterior como reemplazada.

Y una regla propia de este bloque:

- **Los chunks solo se leen por alcance.** :meth:`list_published_chunks`
  exige la lista de alcances autorizados como argumento obligatorio. No
  existe una lectura masiva de chunks sin alcance, de modo que la fase de
  recuperación no *puede* escribirse recuperando primero y filtrando
  después. La regla 4 de ``CLAUDE.md`` deja así de depender de que alguien
  se acuerde.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from elsa.core.authorization import Scope
from elsa.core.versioning import ChangeKind
from elsa.documents.model import ChunkKind, DocumentStructure
from elsa.ports.knowledge import (
    DuplicateSourceError,
    KnowledgeUnavailableError,
    NotPublishableError,
)

__all__ = [
    "ChunkProvenance",
    "DocumentAlreadyExistsError",
    "DocumentIntegrityError",
    "VersionConflictError",
    "DocumentChunkRecord",
    "DocumentIngestionRunRecord",
    "DocumentNotFoundError",
    "DocumentRecord",
    "DocumentRepositoryPort",
    "DocumentSectionRecord",
    "DocumentSourceKind",
    "DocumentVersionEventRecord",
    "DocumentVersionInput",
    "DocumentVersionRecord",
    "DocumentVersionState",
    "DuplicateSourceError",
    "IngestionRunStatus",
    "KnowledgeUnavailableError",
    "NotPublishableError",
    "VersionEvent",
    "VersionNotFoundError",
]


# ---------------------------------------------------------------------
# Errores propios
# ---------------------------------------------------------------------


class DocumentNotFoundError(Exception):
    """No existe ese documento."""


class DocumentAlreadyExistsError(Exception):
    """Ya existe un documento con ese código en ese dominio."""


class VersionNotFoundError(Exception):
    """No existe esa versión o esa ejecución de ingesta."""


class DocumentIntegrityError(ValueError):
    """Documento, corrida, original o estructura no corresponden entre sí."""


class VersionConflictError(DocumentIntegrityError):
    """La corrida ya produjo una versión con otra operación de escritura."""


# ---------------------------------------------------------------------
# Enumeraciones (reflejan las restricciones de la migración)
# ---------------------------------------------------------------------


class DocumentSourceKind(StrEnum):
    """Qué clase de documento es.

    Determina qué se espera de él y cómo se revisa, no cómo se chunkea: el
    chunking lo decide la estructura del archivo, no su etiqueta.
    """

    MANUAL = "manual"
    PROCEDURE = "procedure"
    INSTRUCTION = "instruction"
    TECHNICAL_NOTE = "technical_note"
    APPROVED_NARRATIVE = "approved_narrative"
    """Conocimiento narrativo de la planta ya validado. Llega en fases posteriores."""


class IngestionRunStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentVersionState(StrEnum):
    """Mismos estados que una versión del BOM, y por el mismo motivo.

    ``received`` y ``processing`` pertenecen a la ingesta, no a la versión:
    una versión solo existe si el chunking terminó.
    """

    PENDING_VALIDATION = "pending_validation"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class VersionEvent(StrEnum):
    """Transiciones registradas en el historial de una versión."""

    CREATED = "created"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


# ---------------------------------------------------------------------
# Registros de lectura
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentRecord:
    """Identidad estable de un documento, por encima de sus versiones.

    El documento es «el manual de lubricación del equipo X»; sus versiones
    son las ediciones de ese manual. Si la identidad fuera la versión, cada
    edición nueva rompería toda referencia anterior.

    ``asset_id`` puede ser nulo: hay documentación que aplica a un dominio
    entero y no a un activo concreto (un procedimiento general de bloqueo y
    etiquetado, por ejemplo). Su alcance es entonces el dominio completo.
    """

    id: str
    domain: str
    code: str
    title: str
    source_kind: DocumentSourceKind
    asset_id: str | None = None
    asset_code: str | None = None
    language: str | None = None
    description: str | None = None
    is_active: bool = True
    created_at: datetime | None = None

    @property
    def scope(self) -> Scope:
        """Alcance de autorización del documento: el mismo modelo del Bloque 1."""
        return Scope(domain=self.domain, equipment=self.asset_code)


@dataclass(frozen=True, slots=True)
class DocumentIngestionRunRecord:
    """Una ejecución de ingesta documental y cómo terminó.

    ``stats`` guarda **solo conteos y códigos**: nunca una línea del
    documento. Un revisor puede ver que hubo tres chunks sobredimensionados
    sin que el registro revele nada de un manual interno.
    """

    id: str
    document_id: str
    source_artifact_id: str
    status: IngestionRunStatus
    started_by: str
    started_at: datetime
    failure_kind: str | None = None
    failure_message: str | None = None
    request_id: str | None = None
    finished_at: datetime | None = None
    stats: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DocumentVersionRecord:
    """Una versión de un documento: su contenido en un momento dado."""

    id: str
    document_id: str
    run_id: str
    source_artifact_id: str
    version_number: int
    state: DocumentVersionState
    content_sha256: str
    """Hash de los bytes originales."""

    structure_sha256: str
    """Hash de la estructura producida (secciones y chunks).

    Dos versiones con el mismo ``content_sha256`` pero distinto
    ``structure_sha256`` significan que cambió el extractor o la política, no
    el documento. Sin los dos hashes esa diferencia sería invisible.
    """

    chunking_profile: str
    chunking_parameters: Mapping[str, object]
    extractor: str
    extractor_version: str
    created_at: datetime
    published_at: datetime | None = None
    published_by: str | None = None
    superseded_at: datetime | None = None
    section_count: int = 0
    chunk_count: int = 0


@dataclass(frozen=True, slots=True)
class DocumentSectionRecord:
    id: str
    version_id: str
    ordinal: int
    path: str
    depth: int
    title: str
    parent_id: str | None = None
    parent_path: str | None = None
    number_label: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    is_preamble: bool = False


@dataclass(frozen=True, slots=True)
class DocumentChunkRecord:
    id: str
    version_id: str
    ordinal: int
    structural_key: str
    content: str
    content_sha256: str
    kind: ChunkKind
    section_id: str | None = None
    section_path: str | None = None
    section_title: str | None = None
    index_in_section: int = 0
    heading_trail: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    block_start: int | None = None
    block_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    token_estimate: int = 0
    char_length: int = 0
    overlap_chars: int = 0
    boundary_reason: str = "structure"
    oversized: bool = False
    warnings: tuple[str, ...] = ()
    change_kind: ChangeKind | None = None
    """Cómo cambió respecto de la versión publicada. ``None`` sin versión previa."""


@dataclass(frozen=True, slots=True)
class DocumentVersionEventRecord:
    """Una transición del ciclo de vida. El historial no se modifica ni se borra."""

    id: str
    seq: int
    version_id: str
    event: VersionEvent
    actor: str
    occurred_at: datetime
    reason: str | None = None
    request_id: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkProvenance:
    """Todo lo necesario para reconstruir de dónde salió un chunk.

    Es el contrato de evidencia del bloque. Si algo de esto falta, el chunk
    no puede sostener una respuesta: no se podría decir de qué documento
    viene, de qué versión, si esa versión está publicada ni quién tiene
    derecho a verla.
    """

    chunk: DocumentChunkRecord
    document: DocumentRecord
    version: DocumentVersionRecord
    section: DocumentSectionRecord | None
    source_sha256: str
    source_storage_key: str
    """Dónde están los bytes originales, en el almacenamiento privado."""

    @property
    def scope(self) -> Scope:
        """Alcance que hay que autorizar para poder leer este chunk."""
        return self.document.scope

    @property
    def is_published(self) -> bool:
        return self.version.state is DocumentVersionState.PUBLISHED

    def citation(self) -> str:
        """Referencia legible por una persona, sin el texto del chunk.

        Es lo que se muestra junto a una respuesta y lo que un ingeniero usa
        para ir al documento y comprobarlo.
        """
        parts = [f"{self.document.title} v{self.version.version_number}"]
        if self.section is not None:
            label = self.section.number_label
            parts.append(f"{label} {self.section.title}" if label else self.section.title)
        if self.chunk.page_start is not None:
            if self.chunk.page_end and self.chunk.page_end != self.chunk.page_start:
                parts.append(f"pp. {self.chunk.page_start}-{self.chunk.page_end}")
            else:
                parts.append(f"p. {self.chunk.page_start}")
        return " · ".join(parts)


# ---------------------------------------------------------------------
# Entrada de escritura
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DocumentVersionInput:
    """Todo lo que compone una versión, para escribirla de una sola vez.

    Guardar una versión no es «insertar filas»: entra entera o no entra. Una
    versión con la mitad de sus chunks sería una mentira sobre lo que dice el
    documento, y la recuperación no tendría forma de notarlo.
    """

    document_id: str
    run_id: str
    source_artifact_id: str
    content_sha256: str
    structure: DocumentStructure
    extractor: str
    extractor_version: str
    changes: Mapping[str, ChangeKind] = field(default_factory=dict)
    """Clasificación de cada chunk frente a la versión publicada, por clave."""

    stats: Mapping[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------
# Puerto
# ---------------------------------------------------------------------


@runtime_checkable
class DocumentRepositoryPort(Protocol):
    """Lectura y escritura del conocimiento documental de ELSA."""

    # -- Documentos ---------------------------------------------------

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
        """Crea el documento. Lanza :class:`DocumentAlreadyExistsError` si ya existe."""
        ...

    async def get_document(self, *, domain: str, code: str) -> DocumentRecord | None: ...

    async def get_document_by_id(self, document_id: str) -> DocumentRecord | None: ...

    async def list_documents(
        self, *, domain: str | None = None, asset_code: str | None = None
    ) -> tuple[DocumentRecord, ...]: ...

    # -- Ingesta ------------------------------------------------------

    async def find_run_by_source(self, sha256: str) -> DocumentIngestionRunRecord | None:
        """Ingesta previa de ese archivo exacto, si la hubo."""
        ...

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
        """Registra el archivo y abre la ingesta, en una transacción.

        Lanza :class:`DuplicateSourceError` si ese contenido ya está
        registrado. La unicidad la impone el almacén, no una comprobación
        previa: dos peticiones simultáneas con el mismo archivo pasan las dos
        por la comprobación y solo una puede sobrevivir al registro.
        """
        ...

    async def fail_ingestion_run(
        self,
        *,
        run_id: str,
        failure_kind: str,
        failure_message: str,
        stats: Mapping[str, object] | None = None,
    ) -> DocumentIngestionRunRecord:
        """Cierra la ingesta como fallida. No toca la versión publicada."""
        ...

    async def get_ingestion_run(self, run_id: str) -> DocumentIngestionRunRecord | None: ...

    async def list_ingestion_runs(
        self, document_id: str, *, limit: int = 50
    ) -> tuple[DocumentIngestionRunRecord, ...]: ...

    # -- Versiones ----------------------------------------------------

    async def store_version(
        self, data: DocumentVersionInput, *, actor: str, request_id: str | None = None
    ) -> DocumentVersionRecord:
        """Escribe la versión entera —secciones y chunks— en una transacción.

        La versión entra siempre como ``pending_validation``: nunca se
        publica sola.

        Una corrida produce como máximo una versión. Repetir los mismos
        campos persistibles, stats, actor y request_id devuelve la versión
        existente en su estado actual, sin eventos ni timestamps nuevos.
        Los campos transitorios de extracción no forman parte de esa igualdad.
        Reutilizar la corrida con otros datos lanza VersionConflictError.
        Documento, corrida, original y hash deben corresponder; una combinación
        incompatible lanza DocumentIntegrityError sin escrituras parciales.
        """
        ...

    async def get_version(self, version_id: str) -> DocumentVersionRecord | None: ...

    async def list_versions(self, document_id: str) -> tuple[DocumentVersionRecord, ...]: ...

    async def get_published_version(self, document_id: str) -> DocumentVersionRecord | None: ...

    async def list_sections(self, version_id: str) -> tuple[DocumentSectionRecord, ...]: ...

    async def list_chunks(self, version_id: str) -> tuple[DocumentChunkRecord, ...]: ...

    async def get_chunk_provenance(self, chunk_id: str) -> ChunkProvenance | None:
        """Reconstruye la procedencia completa de un chunk."""
        ...

    async def set_version_state(
        self,
        *,
        version_id: str,
        state: DocumentVersionState,
        actor: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> DocumentVersionRecord:
        """Aprueba o rechaza una versión que aún no está publicada.

        Rechazar exige un motivo no vacío; de lo contrario NotPublishableError.
        """
        ...

    async def publish_version(
        self, *, version_id: str, actor: str, request_id: str | None = None
    ) -> DocumentVersionRecord:
        """Publica la versión y marca la anterior como reemplazada.

        Atómico: dos publicaciones simultáneas no pueden dejar dos versiones
        vigentes ni ninguna. Lanza :class:`NotPublishableError` si la versión
        no está aprobada.
        """
        ...

    async def list_version_events(
        self, version_id: str
    ) -> tuple[DocumentVersionEventRecord, ...]: ...

    # -- Lectura por alcance ------------------------------------------

    async def list_published_chunks(
        self, *, scopes: Sequence[Scope], limit: int = 100
    ) -> tuple[ChunkProvenance, ...]:
        """Chunks de las versiones **publicadas** que caen dentro de ``scopes``.

        ``scopes`` es obligatorio y no admite comodín. Con una lista vacía se
        devuelve vacío, que es la respuesta correcta para quien no tiene
        ningún permiso: recuperar y luego ocultar sería exactamente lo que la
        regla 4 prohíbe.

        Esto **no es búsqueda semántica**: no hay embeddings ni ranking en
        este bloque. Es la lectura por alcance sobre la que esa fase se
        construirá.
        """
        ...

    async def check_health(self) -> None:
        """Lanza :class:`KnowledgeUnavailableError` si el almacén no responde."""
        ...
