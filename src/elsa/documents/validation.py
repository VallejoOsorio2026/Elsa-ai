"""Validación de una estructura documental antes de guardarla.

Es el segundo paso del ciclo de vida —ingestar, **validar**, comparar,
publicar— y su regla es simple: distinguir lo que impide guardar una versión
de lo que solo exige que alguien la mire.

Un aviso no bloquea. Un manual con una tabla partida o con un salto de nivel
en sus títulos sigue siendo un manual útil, y rechazarlo obligaría a
«arreglar» el PDF que Ingeniería aprobó. Lo que sí bloquea es una versión que
no puede sostener ninguna evidencia: un documento del que no salió ni un
chunk no es conocimiento, es un archivo.
"""

from dataclasses import dataclass

from elsa.documents.model import DocumentStructure

__all__ = ["ValidationIssue", "ValidationReport", "validate_structure"]

# Motivos por los que una versión no puede existir. Todo lo demás avisa.
_BLOCKING = {
    "empty_document": "the document produced no readable content",
    "no_chunks": "the document produced no chunk",
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Un hallazgo de la validación.

    ``code`` es estable y comparable en tests y en la API; ``message`` es
    para una persona. Ninguno lleva contenido del documento.
    """

    code: str
    message: str
    blocking: bool
    count: int = 1


@dataclass(frozen=True, slots=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def blocking(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.blocking)

    @property
    def is_valid(self) -> bool:
        return not self.blocking

    def counts(self) -> dict[str, int]:
        """Códigos y conteos, aptos para ``stats``. Nunca contenido."""
        return {issue.code: issue.count for issue in self.issues}


def validate_structure(structure: DocumentStructure) -> ValidationReport:
    """Revisa la estructura producida y clasifica lo que encuentre."""
    counts = dict(structure.warning_counts())

    if not structure.chunks:
        counts.setdefault("no_chunks", 1)

    issues = [
        ValidationIssue(
            code=code,
            message=_BLOCKING.get(code, _describe(code)),
            blocking=code in _BLOCKING,
            count=count,
        )
        for code, count in sorted(counts.items())
    ]
    return ValidationReport(issues=tuple(issues))


def _describe(code: str) -> str:
    """Explicación en una línea de un aviso no bloqueante."""
    return {
        "chunk_oversized": "a chunk exceeds the configured ceiling and could not be split further",
        "indivisible_unit_too_large": "a step or a warning is too large to fit in one chunk",
        "table_split": "a table did not fit in one chunk and was split by rows",
        "table_without_header_marker": "a table declares no header row",
        "heading_level_skipped": "the heading depth jumps a level",
        "section_without_content": "a heading opens a section with no content of its own",
        "content_before_first_heading": "the document opens with content before any heading",
    }.get(code, "the extractor reported this condition")
