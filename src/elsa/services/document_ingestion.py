"""Ingesta documental, de extremo a extremo.

Une el almacenamiento privado, el extractor, el chunking, la validación, la
comparación con la versión publicada y el repositorio. Aquí se decide **el
orden** de esos pasos y qué ocurre cuando uno falla.

El orden es el mismo que el de la ingesta estructurada
(:mod:`elsa.services.ingestion`) y no es arbitrario:

1. Se calcula el SHA-256 del archivo **antes de mirarlo**. Es la huella del
   original y la base de la idempotencia.
2. Se comprueba si ese archivo exacto ya se ingirió. Reingerirlo no crea una
   versión nueva.
3. Se guardan los bytes en el almacenamiento privado. Si el almacenamiento
   no responde, no se registra nada: fingir que el archivo está guardado
   sería perder evidencia sin que nadie se entere.
4. Se abre la ejecución de ingesta. La unicidad del contenido la impone el
   almacén, no la comprobación del paso 2: dos peticiones simultáneas con el
   mismo archivo pasan las dos por el paso 2 y solo una sobrevive al 4.
5. Se **extrae** la estructura. Cualquier fallo cierra la ingesta como
   fallida, con su tipo, y no toca la última versión publicada.
6. Se **chunkea** de forma determinística.
7. Se **valida**. Un fallo bloqueante cierra la ingesta; los avisos se
   registran como conteos y siguen.
8. Se **compara** con la versión publicada: qué chunk es nuevo, cuál cambió
   y cuál sigue igual.
9. Se escribe la versión entera, en una transacción, como
   ``pending_validation``.

**Una versión nunca se publica sola.** Publicar es una operación aparte, la
toma una persona y reemplaza a la anterior de forma atómica. Un fallo en
cualquier paso deja intacta la última versión publicada: eso es lo que hace
seguro reintentar una ingesta sobre un documento que ya está en uso.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from elsa.core.versioning import ChangeKind, VersionedItem, classify_versions
from elsa.documents.chunking import chunk_document
from elsa.documents.model import ChunkingPolicy, DocumentStructure
from elsa.documents.persistence import require_reason
from elsa.documents.validation import ValidationReport, validate_structure
from elsa.ports.artifact_storage import (
    ArtifactAlreadyExistsError,
    ArtifactStoragePort,
    ArtifactStorageUnavailableError,
    sha256_hex,
    storage_key,
)
from elsa.ports.document_extraction import DocumentExtractionPort, UnsupportedDocumentError
from elsa.ports.documents import (
    DocumentIngestionRunRecord,
    DocumentRecord,
    DocumentRepositoryPort,
    DocumentVersionInput,
    DocumentVersionRecord,
    DocumentVersionState,
    DuplicateSourceError,
    KnowledgeUnavailableError,
)

_logger = logging.getLogger("elsa.services.document_ingestion")

__all__ = [
    "DocumentIngestionError",
    "DocumentIngestionService",
    "DuplicateDocumentSource",
    "IngestedVersion",
]

_ARTIFACT_PREFIX = "document_source"


class DocumentIngestionError(Exception):
    """La ingesta no pudo completarse.

    ``failure_kind`` distingue el tipo de fallo, porque «el archivo que
    subiste no se puede leer» y «el disco no responde» exigen respuestas
    distintas del administrador y códigos HTTP distintos.
    """

    def __init__(
        self,
        message: str,
        *,
        failure_kind: str,
        run_id: str | None = None,
        report: ValidationReport | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.run_id = run_id
        self.report = report


@dataclass(frozen=True, slots=True)
class DuplicateDocumentSource:
    """Se subió un archivo ya ingerido; se devuelve la ejecución original."""

    existing_run_id: str | None


@dataclass(frozen=True, slots=True)
class IngestedVersion:
    """Resultado de una ingesta que sí produjo una versión."""

    version: DocumentVersionRecord
    structure: DocumentStructure
    report: ValidationReport
    changes: Mapping[str, ChangeKind]
    run: DocumentIngestionRunRecord

    def change_counts(self) -> dict[str, int]:
        totals = {kind.value: 0 for kind in ChangeKind}
        for kind in self.changes.values():
            totals[kind.value] += 1
        return totals


class DocumentIngestionService:
    """Orquesta la ingesta y el ciclo de vida de un documento."""

    def __init__(
        self,
        *,
        repository: DocumentRepositoryPort,
        storage: ArtifactStoragePort,
        extractor: DocumentExtractionPort,
        policy: ChunkingPolicy | None = None,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._extractor = extractor
        self._policy = policy or ChunkingPolicy()

    @property
    def policy(self) -> ChunkingPolicy:
        return self._policy

    # -----------------------------------------------------------------
    # Ingesta
    # -----------------------------------------------------------------

    async def ingest(
        self,
        *,
        document: DocumentRecord,
        content: bytes,
        content_type: str,
        filename: str | None,
        actor: str,
        request_id: str | None = None,
    ) -> IngestedVersion | DuplicateDocumentSource:
        digest = sha256_hex(content)

        existing = await self._repository.find_run_by_source(digest)
        if existing is not None:
            _logger.info(
                "document source already ingested",
                extra={"document_id": document.id, "run_id": existing.id},
            )
            return DuplicateDocumentSource(existing_run_id=existing.id)

        key = storage_key(_ARTIFACT_PREFIX, digest)
        try:
            await self._storage.put(key, content)
        except ArtifactAlreadyExistsError:
            # Los bytes ya estaban: mismo contenido, misma clave. No es un
            # error, y volver a escribirlos no cambiaria nada.
            pass
        except ArtifactStorageUnavailableError as error:
            raise DocumentIngestionError(
                "the private artifact storage is not available",
                failure_kind="storage",
            ) from error

        try:
            run = await self._repository.start_ingestion_run(
                document_id=document.id,
                sha256=digest,
                byte_size=len(content),
                storage_key=key,
                uploaded_by=actor,
                original_filename=filename,
                content_type=content_type,
                request_id=request_id,
            )
        except DuplicateSourceError as error:
            return DuplicateDocumentSource(existing_run_id=error.existing_import_id)
        except KnowledgeUnavailableError as error:
            raise DocumentIngestionError(
                "the knowledge store is not available", failure_kind="database"
            ) from error

        try:
            extracted = await self._extractor.extract(
                content, content_type=content_type, filename=filename
            )
        except UnsupportedDocumentError as error:
            await self._fail(run.id, "file", str(error))
            raise DocumentIngestionError(str(error), failure_kind="file", run_id=run.id) from error
        except Exception as error:  # noqa: BLE001 - se traduce a un fallo de parseo
            await self._fail(run.id, "parse", "the document could not be read")
            raise DocumentIngestionError(
                "the document could not be read", failure_kind="parse", run_id=run.id
            ) from error

        structure = chunk_document(extracted, document_title=document.title, policy=self._policy)
        report = validate_structure(structure)
        if not report.is_valid:
            reasons = ", ".join(issue.code for issue in report.blocking)
            await self._fail(run.id, "parse", reasons, stats=report.counts())
            raise DocumentIngestionError(
                f"the document did not pass validation: {reasons}",
                failure_kind="parse",
                run_id=run.id,
                report=report,
            )

        changes = await self._compare(document.id, structure)

        stats: dict[str, object] = {
            "sections": len(structure.sections),
            "chunks": len(structure.chunks),
            "pages": extracted.page_count or 0,
            "warnings": report.counts(),
            "changes": _change_counts(changes),
        }

        version = await self._repository.store_version(
            DocumentVersionInput(
                document_id=document.id,
                run_id=run.id,
                source_artifact_id=run.source_artifact_id,
                content_sha256=digest,
                structure=structure,
                extractor=extracted.extractor,
                extractor_version=extracted.extractor_version,
                changes=changes,
                stats=stats,
            ),
            actor=actor,
            request_id=request_id,
        )
        _logger.info(
            "document version stored",
            extra={
                "document_id": document.id,
                "version_id": version.id,
                "sections": len(structure.sections),
                "chunks": len(structure.chunks),
            },
        )
        stored_run = await self._repository.get_ingestion_run(run.id)
        return IngestedVersion(
            version=version,
            structure=structure,
            report=report,
            changes=changes,
            run=stored_run or run,
        )

    # -----------------------------------------------------------------
    # Ciclo de vida
    # -----------------------------------------------------------------

    async def approve(
        self,
        *,
        version_id: str,
        actor: str,
        comment: str | None = None,
        request_id: str | None = None,
    ) -> DocumentVersionRecord:
        """Aprueba una versión. Aprobar **no** es publicar."""
        return await self._repository.set_version_state(
            version_id=version_id,
            state=DocumentVersionState.APPROVED,
            actor=actor,
            reason=comment,
            request_id=request_id,
        )

    async def reject(
        self, *, version_id: str, actor: str, reason: str, request_id: str | None = None
    ) -> DocumentVersionRecord:
        """Rechaza una versión. La publicada, si la hay, sigue publicada."""
        require_reason(reason)
        return await self._repository.set_version_state(
            version_id=version_id,
            state=DocumentVersionState.REJECTED,
            actor=actor,
            reason=reason,
            request_id=request_id,
        )

    async def publish(
        self, *, version_id: str, actor: str, request_id: str | None = None
    ) -> DocumentVersionRecord:
        """Activa la versión y reemplaza a la anterior, de forma atómica."""
        return await self._repository.publish_version(
            version_id=version_id, actor=actor, request_id=request_id
        )

    # -----------------------------------------------------------------
    # Interno
    # -----------------------------------------------------------------

    async def _compare(
        self, document_id: str, structure: DocumentStructure
    ) -> dict[str, ChangeKind]:
        """Clasifica cada chunk frente al de la versión publicada.

        Reutiliza la misma comparación del Bloque 2
        (:func:`elsa.core.versioning.classify_versions`): la identidad es la
        dirección estructural del chunk y la huella es el hash de su
        contenido. Un chunk que no cambió puede heredar su validación; uno
        que cambió vuelve a revisión.

        Sin versión publicada todo es ``new``, que es exactamente lo que
        ocurre con el primer documento que entra.
        """
        published = await self._repository.get_published_version(document_id)
        previous: list[VersionedItem] = []
        if published is not None:
            previous = [
                VersionedItem(key=chunk.structural_key, fingerprint=chunk.content_sha256)
                for chunk in await self._repository.list_chunks(published.id)
            ]
        current = [
            VersionedItem(key=chunk.structural_key, fingerprint=chunk.content_sha256)
            for chunk in structure.chunks
        ]
        return dict(classify_versions(previous, current).changes)

    async def _fail(
        self,
        run_id: str,
        failure_kind: str,
        message: str,
        stats: Mapping[str, object] | None = None,
    ) -> None:
        try:
            await self._repository.fail_ingestion_run(
                run_id=run_id,
                failure_kind=failure_kind,
                failure_message=message,
                stats=stats,
            )
        except KnowledgeUnavailableError:
            # El fallo original es el que importa; no se sustituye por el de
            # no haber podido registrarlo.
            _logger.warning("could not record the failed ingestion run", extra={"run_id": run_id})


def _change_counts(changes: Mapping[str, ChangeKind]) -> dict[str, int]:
    totals = {kind.value: 0 for kind in ChangeKind}
    for kind in changes.values():
        totals[kind.value] += 1
    return totals
