"""Construcción del árbol de secciones a partir de los bloques extraídos.

Un manual no es una tira de texto: es un árbol de títulos con contenido
colgando de cada nodo. Reconstruir ese árbol antes de chunkear es lo que
permite que un chunk sepa decir «esto sale de 3.2 Lubricación, páginas 14 a
15» en vez de «esto sale del carácter 18.402».

La dirección de cada sección se calcula por **posición en el árbol**, no por
la numeración que el documento imprima. Los manuales reales tienen títulos
sin numerar, numeraciones que se repiten entre capítulos y saltos de
numeración; la posición, en cambio, siempre existe y siempre es única. La
numeración impresa se conserva aparte porque es como la gente se refiere a
la sección al hablar.
"""

from dataclasses import dataclass

from elsa.documents.model import DocumentSection
from elsa.ingestion.model import IngestionWarning
from elsa.ports.document_extraction import BlockKind, ExtractedBlock

__all__ = ["SectionDraft", "build_sections"]

_PREAMBLE_PATH = "0"


@dataclass(frozen=True, slots=True)
class SectionDraft:
    """Una sección con los bloques de contenido que le pertenecen.

    Solo los propios: los de las subsecciones pertenecen a esas. Si el
    contenido de los hijos colgara también del padre, el mismo texto se
    chunkearía dos veces y la recuperación devolvería duplicados.
    """

    section: DocumentSection
    blocks: tuple[ExtractedBlock, ...]


def build_sections(
    blocks: tuple[ExtractedBlock, ...],
    *,
    document_title: str,
    warnings: list[IngestionWarning] | None = None,
) -> tuple[SectionDraft, ...]:
    """Agrupa los bloques bajo el título que los encabeza.

    El contenido anterior al primer título no se descarta ni se cuelga de
    una sección que no lo contiene: se le da una sección de preámbulo
    (``path`` ``0``, profundidad ``0``) que declara lo que es. Un manual
    empieza a menudo con el alcance y las condiciones de seguridad, y esa es
    exactamente la parte que no puede perderse.
    """
    collected: list[IngestionWarning] = warnings if warnings is not None else []

    drafts: list[_Draft] = []
    stack: list[tuple[int, str]] = []
    child_counts: dict[str, int] = {}
    previous_level: int | None = None
    current: _Draft | None = None

    for block in blocks:
        if block.kind is not BlockKind.HEADING:
            if current is None:
                current = _Draft(
                    ordinal=len(drafts),
                    path=_PREAMBLE_PATH,
                    parent_path=None,
                    depth=0,
                    title=document_title,
                    number_label=None,
                    is_preamble=True,
                    heading_block=None,
                )
                drafts.append(current)
                collected.append(
                    IngestionWarning(
                        code="content_before_first_heading",
                        message="the document opens with content before any heading",
                        location=f"block:{block.ordinal}",
                    )
                )
            current.blocks.append(block)
            continue

        level = block.level or 1
        if previous_level is not None and level > previous_level + 1:
            collected.append(
                IngestionWarning(
                    code="heading_level_skipped",
                    message=f"heading depth jumps from {previous_level} to {level}",
                    location=f"block:{block.ordinal}",
                )
            )
        previous_level = level

        while stack and stack[-1][0] >= level:
            stack.pop()
        parent_path = stack[-1][1] if stack else None
        parent_key = parent_path or ""
        child_counts[parent_key] = child_counts.get(parent_key, 0) + 1
        index = child_counts[parent_key]
        path = f"{parent_path}.{index}" if parent_path is not None else str(index)
        stack.append((level, path))

        current = _Draft(
            ordinal=len(drafts),
            path=path,
            parent_path=parent_path,
            depth=len(stack),
            title=block.text,
            number_label=block.number_label,
            is_preamble=False,
            heading_block=block,
        )
        drafts.append(current)

    for draft in drafts:
        if not draft.blocks and not _has_children(draft.path, drafts):
            collected.append(
                IngestionWarning(
                    code="section_without_content",
                    message="the heading opens a section with no content of its own",
                    location=f"section:{draft.path}",
                )
            )

    return tuple(draft.build() for draft in drafts)


def _has_children(path: str, drafts: list["_Draft"]) -> bool:
    return any(draft.parent_path == path for draft in drafts)


class _Draft:
    """Sección en construcción."""

    __slots__ = (
        "blocks",
        "depth",
        "heading_block",
        "is_preamble",
        "number_label",
        "ordinal",
        "parent_path",
        "path",
        "title",
    )

    def __init__(
        self,
        *,
        ordinal: int,
        path: str,
        parent_path: str | None,
        depth: int,
        title: str,
        number_label: str | None,
        is_preamble: bool,
        heading_block: ExtractedBlock | None,
    ) -> None:
        self.ordinal = ordinal
        self.path = path
        self.parent_path = parent_path
        self.depth = depth
        self.title = title
        self.number_label = number_label
        self.is_preamble = is_preamble
        self.heading_block = heading_block
        self.blocks: list[ExtractedBlock] = []

    def build(self) -> SectionDraft:
        spanning = list(self.blocks)
        if self.heading_block is not None:
            spanning.insert(0, self.heading_block)

        pages = [page for block in spanning for page in block.pages]
        return SectionDraft(
            section=DocumentSection(
                ordinal=self.ordinal,
                path=self.path,
                parent_path=self.parent_path,
                depth=self.depth,
                title=self.title,
                number_label=self.number_label,
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
                block_start=spanning[0].ordinal if spanning else None,
                block_end=spanning[-1].ordinal if spanning else None,
                char_start=spanning[0].char_start if spanning else None,
                char_end=spanning[-1].char_end if spanning else None,
                is_preamble=self.is_preamble,
            ),
            blocks=tuple(self.blocks),
        )
