"""Chunking estructural y determinístico.

## Por qué no se corta cada N caracteres

Cortar cada N caracteres es trivial de implementar y destruye exactamente lo
que hace útil a un manual de mantenimiento: parte el paso 4 de un
procedimiento en dos, separa una advertencia del trabajo al que se refiere y
deja media tabla sin encabezado. La recuperación devuelve entonces trozos
que parecen respuestas y no lo son.

Aquí el corte lo decide **la estructura del documento** y solo cuando la
estructura no basta interviene el tamaño.

## Reglas, en el orden en que mandan

1. **Una sección no se mezcla con otra.** Un chunk pertenece a una sola
   sección; el cambio de título es siempre un corte.
2. **Una tabla es una unidad.** Ocupa su propio chunk y no se mezcla con
   prosa. Si no cabe, se parte por filas —nunca a mitad de fila— y el
   encabezado se repite en cada trozo.
3. **Una advertencia no se parte ni se queda huérfana.** Abre siempre un
   chunk, de modo que viaja con el texto al que precede y nunca cierra uno
   como último renglón suelto.
4. **Un paso numerado no se parte.** El orden y el número son parte del
   significado.
5. **Un pie acompaña a su figura.** Se queda con el bloque anterior mientras
   quepa.
6. Dentro de esos límites se agrupa hasta ``target_tokens``.
7. Solo si una unidad sola supera ``max_tokens`` se parte por frases, y solo
   ahí hay solape.

## Determinismo

La misma entrada y la misma política producen los mismos chunks, con los
mismos hashes, en cualquier máquina. No se consultan relojes, no se generan
identificadores y no se recorre ningún diccionario cuyo orden importe. Es lo
que permite reprocesar un documento para comprobar que nada cambió, y lo que
hace que reimportar un archivo idéntico no cree una versión nueva.
"""

import re

from elsa.documents.model import (
    ChunkingPolicy,
    ChunkKind,
    DocumentChunk,
    DocumentSection,
    DocumentStructure,
    content_hash,
    estimate_tokens,
    normalize_text,
)
from elsa.documents.sectioning import SectionDraft, build_sections
from elsa.ingestion.model import IngestionWarning
from elsa.ports.document_extraction import BlockKind, ExtractedBlock, ExtractedDocument

__all__ = ["chunk_document"]

_SENTENCE_END = re.compile(r"(?<=[.:;!?])\s+")

_STRUCTURE = "structure"
_SIZE = "size"


def chunk_document(
    extracted: ExtractedDocument,
    *,
    document_title: str,
    policy: ChunkingPolicy | None = None,
) -> DocumentStructure:
    """Secciona y chunkea un documento ya extraído."""
    active = policy or ChunkingPolicy()
    warnings: list[IngestionWarning] = list(extracted.warnings)

    drafts = build_sections(extracted.blocks, document_title=document_title, warnings=warnings)

    chunks: list[DocumentChunk] = []
    for draft in drafts:
        chunks.extend(_chunk_section(draft, active, len(chunks)))

    return DocumentStructure(
        sections=tuple(draft.section for draft in drafts),
        chunks=tuple(chunks),
        policy=active,
        warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------
# Unidades indivisibles
# ---------------------------------------------------------------------


class _Unit:
    """Un trozo de contenido que el chunking trata como una pieza."""

    __slots__ = (
        "attach_previous",
        "block",
        "boundary_before",
        "isolate",
        "kind",
        "splittable",
        "text",
        "tokens",
    )

    def __init__(
        self,
        *,
        kind: ChunkKind,
        text: str,
        block: ExtractedBlock,
        tokens: int,
        isolate: bool = False,
        boundary_before: bool = False,
        splittable: bool = False,
        attach_previous: bool = False,
    ) -> None:
        self.kind = kind
        self.text = text
        self.block = block
        self.tokens = tokens
        self.isolate = isolate
        self.boundary_before = boundary_before
        self.splittable = splittable
        self.attach_previous = attach_previous


def _render(block: ExtractedBlock) -> str:
    """Texto del bloque tal y como entra en un chunk.

    Los pasos conservan su número y las listas su viñeta. Un procedimiento
    cuyo chunk dice «apretar los pernos» sin decir que es el paso 4 obliga a
    volver al PDF para saber cuándo se hace; conservar la marca cuesta dos
    caracteres y evita esa vuelta.
    """
    if block.kind is BlockKind.STEP and block.number_label:
        return f"{block.number_label}. {block.text}"
    if block.kind is BlockKind.LIST_ITEM:
        return f"- {block.text}"
    return block.text


def _units(blocks: tuple[ExtractedBlock, ...], policy: ChunkingPolicy) -> list[_Unit]:
    units: list[_Unit] = []
    for block in blocks:
        text = _render(block)
        tokens = estimate_tokens(text, chars_per_token=policy.chars_per_token)
        if block.kind is BlockKind.TABLE:
            units.append(
                _Unit(
                    kind=ChunkKind.TABLE,
                    text=text,
                    block=block,
                    tokens=tokens,
                    isolate=policy.keep_tables_whole,
                )
            )
        elif block.kind is BlockKind.WARNING:
            units.append(
                _Unit(
                    kind=ChunkKind.WARNING,
                    text=text,
                    block=block,
                    tokens=tokens,
                    boundary_before=True,
                )
            )
        elif block.kind is BlockKind.STEP:
            units.append(_Unit(kind=ChunkKind.STEPS, text=text, block=block, tokens=tokens))
        elif block.kind is BlockKind.LIST_ITEM:
            units.append(_Unit(kind=ChunkKind.LIST, text=text, block=block, tokens=tokens))
        elif block.kind is BlockKind.CAPTION:
            units.append(
                _Unit(
                    kind=ChunkKind.PROSE,
                    text=text,
                    block=block,
                    tokens=tokens,
                    attach_previous=True,
                )
            )
        else:
            units.append(
                _Unit(
                    kind=ChunkKind.PROSE,
                    text=text,
                    block=block,
                    tokens=tokens,
                    splittable=True,
                )
            )
    return units


# ---------------------------------------------------------------------
# Empaquetado
# ---------------------------------------------------------------------


class _Draft:
    """Chunk en construcción, antes de conocer su posición global."""

    __slots__ = (
        "blocks",
        "boundary_reason",
        "kinds",
        "overlap_chars",
        "oversized",
        "text",
        "warnings",
    )

    def __init__(
        self,
        *,
        text: str,
        blocks: tuple[ExtractedBlock, ...],
        kinds: tuple[ChunkKind, ...],
        boundary_reason: str,
        oversized: bool = False,
        warnings: tuple[str, ...] = (),
        overlap_chars: int = 0,
    ) -> None:
        self.text = text
        self.blocks = blocks
        self.kinds = kinds
        self.boundary_reason = boundary_reason
        self.oversized = oversized
        self.warnings = warnings
        self.overlap_chars = overlap_chars

    @property
    def kind(self) -> ChunkKind:
        unique = set(self.kinds)
        if len(unique) == 1:
            return next(iter(unique))
        return ChunkKind.MIXED

    def tokens(self, policy: ChunkingPolicy) -> int:
        return estimate_tokens(self.text, chars_per_token=policy.chars_per_token)


def _chunk_section(
    draft: SectionDraft, policy: ChunkingPolicy, first_ordinal: int
) -> list[DocumentChunk]:
    units = _units(draft.blocks, policy)
    drafts = _pack(units, policy)
    drafts = _merge_small(drafts, policy)
    drafts = _apply_overlap(drafts, policy)
    return _materialise(drafts, draft.section, first_ordinal, policy)


def _pack(units: list[_Unit], policy: ChunkingPolicy) -> list[_Draft]:
    drafts: list[_Draft] = []
    current: list[_Unit] = []
    reason = _STRUCTURE

    def flush(next_reason: str) -> None:
        nonlocal current, reason
        if current:
            drafts.append(
                _Draft(
                    text="\n".join(unit.text for unit in current),
                    blocks=tuple(unit.block for unit in current),
                    kinds=tuple(unit.kind for unit in current),
                    boundary_reason=reason,
                )
            )
            current = []
            reason = next_reason

    for unit in units:
        if unit.isolate:
            flush(_STRUCTURE)
            table_drafts = _split_table(unit, policy, reason)
            drafts.extend(table_drafts)
            reason = _STRUCTURE
            continue

        # El pie de una tabla es parte de la tabla: dice que columnas son
        # esas y de que conjunto hablan. Separarlo deja un chunk con una
        # frase suelta y una tabla que ya no se sabe de que es.
        if unit.attach_previous and not current and drafts and ChunkKind.TABLE in drafts[-1].kinds:
            previous = drafts[-1]
            combined = f"{previous.text}\n{unit.text}"
            if estimate_tokens(combined, chars_per_token=policy.chars_per_token) <= (
                policy.max_tokens
            ):
                drafts[-1] = _Draft(
                    text=combined,
                    blocks=previous.blocks + (unit.block,),
                    kinds=previous.kinds + (unit.kind,),
                    boundary_reason=previous.boundary_reason,
                    oversized=previous.oversized,
                    warnings=previous.warnings,
                    overlap_chars=previous.overlap_chars,
                )
                continue

        if unit.boundary_before and current:
            flush(_STRUCTURE)

        if unit.tokens > policy.max_tokens:
            flush(_STRUCTURE)
            pieces = _split_prose(unit, policy, reason)
            drafts.extend(pieces)
            reason = _SIZE if len(pieces) > 1 else _STRUCTURE
            continue

        accumulated = sum(item.tokens for item in current)
        if current and accumulated + unit.tokens > policy.target_tokens:
            # Un pie de figura se queda con su figura mientras no rompa el
            # techo duro: separarlo deja una línea suelta que no dice de qué
            # habla.
            if not (unit.attach_previous and accumulated + unit.tokens <= policy.max_tokens):
                flush(_SIZE)

        current.append(unit)

    flush(_STRUCTURE)
    return drafts


def _split_table(unit: _Unit, policy: ChunkingPolicy, reason: str) -> list[_Draft]:
    """Parte una tabla por filas, repitiendo su encabezado.

    Solo si no cabe entera. Una tabla técnica partida a mitad de fila, o sin
    los rótulos de sus columnas, deja de ser información y pasa a ser ruido.
    """
    block = unit.block
    if unit.tokens <= policy.max_tokens or not block.rows:
        return [
            _Draft(
                text=unit.text,
                blocks=(block,),
                kinds=(ChunkKind.TABLE,),
                boundary_reason=reason,
                oversized=unit.tokens > policy.max_tokens,
                warnings=("chunk_oversized",) if unit.tokens > policy.max_tokens else (),
            )
        ]

    header = block.rows[: block.header_rows]
    body = block.rows[block.header_rows :]
    header_text = "\n".join(" | ".join(row) for row in header)
    header_tokens = estimate_tokens(header_text, chars_per_token=policy.chars_per_token)

    pieces: list[_Draft] = []
    batch: list[tuple[str, ...]] = []
    batch_tokens = 0

    def emit(is_first: bool) -> None:
        nonlocal batch, batch_tokens
        if not batch:
            return
        rows = list(header) + batch
        text = "\n".join(" | ".join(row) for row in rows)
        tokens = estimate_tokens(text, chars_per_token=policy.chars_per_token)
        pieces.append(
            _Draft(
                text=text,
                blocks=(block,),
                kinds=(ChunkKind.TABLE,),
                boundary_reason=reason if is_first else _STRUCTURE,
                oversized=tokens > policy.max_tokens,
                warnings=("table_split",)
                + (("chunk_oversized",) if tokens > policy.max_tokens else ()),
            )
        )
        batch = []
        batch_tokens = 0

    for row in body:
        row_tokens = estimate_tokens(" | ".join(row), chars_per_token=policy.chars_per_token)
        if batch and header_tokens + batch_tokens + row_tokens > policy.target_tokens:
            emit(not pieces)
        batch.append(row)
        batch_tokens += row_tokens
    emit(not pieces)

    return pieces


def _split_prose(unit: _Unit, policy: ChunkingPolicy, reason: str) -> list[_Draft]:
    """Parte una unidad demasiado grande por frases, y solo si no queda otra.

    Una unidad que no es prosa —un paso, un elemento de lista, una
    advertencia— **no se parte**: se emite entera y se marca como
    sobredimensionada, para que una persona decida qué hacer con ella. Partir
    un paso de un procedimiento por la mitad produce dos instrucciones
    falsas donde había una verdadera.
    """
    if not unit.splittable:
        return [
            _Draft(
                text=unit.text,
                blocks=(unit.block,),
                kinds=(unit.kind,),
                boundary_reason=reason,
                oversized=True,
                warnings=("chunk_oversized", "indivisible_unit_too_large"),
            )
        ]

    sentences = [part for part in _SENTENCE_END.split(unit.text) if part.strip()]
    pieces: list[_Draft] = []
    batch: list[str] = []
    batch_tokens = 0

    def emit(is_first: bool) -> None:
        nonlocal batch, batch_tokens
        if not batch:
            return
        text = " ".join(batch)
        tokens = estimate_tokens(text, chars_per_token=policy.chars_per_token)
        pieces.append(
            _Draft(
                text=text,
                blocks=(unit.block,),
                kinds=(unit.kind,),
                boundary_reason=reason if is_first else _SIZE,
                oversized=tokens > policy.max_tokens,
                warnings=("chunk_oversized",) if tokens > policy.max_tokens else (),
            )
        )
        batch = []
        batch_tokens = 0

    for sentence in sentences:
        tokens = estimate_tokens(sentence, chars_per_token=policy.chars_per_token)
        if batch and batch_tokens + tokens > policy.target_tokens:
            emit(not pieces)
        if tokens > policy.max_tokens:
            emit(not pieces)
            for fragment in _split_words(sentence, policy):
                batch = [fragment]
                batch_tokens = estimate_tokens(fragment, chars_per_token=policy.chars_per_token)
                emit(not pieces)
            continue
        batch.append(sentence)
        batch_tokens += tokens
    emit(not pieces)

    return pieces or [
        _Draft(
            text=unit.text,
            blocks=(unit.block,),
            kinds=(unit.kind,),
            boundary_reason=reason,
            oversized=True,
            warnings=("chunk_oversized",),
        )
    ]


def _split_words(sentence: str, policy: ChunkingPolicy) -> list[str]:
    """Última salida: cortar una frase interminable por palabras enteras.

    Nunca a mitad de palabra. Un código de material partido en dos deja de
    ser buscable, que es justo lo contrario de lo que se pretende.
    """
    budget = policy.target_tokens * policy.chars_per_token
    fragments: list[str] = []
    current: list[str] = []
    length = 0
    for word in sentence.split():
        addition = len(word) + (1 if current else 0)
        if current and length + addition > budget:
            fragments.append(" ".join(current))
            current = []
            length = 0
            addition = len(word)
        current.append(word)
        length += addition
    if current:
        fragments.append(" ".join(current))
    return fragments


def _merge_small(drafts: list[_Draft], policy: ChunkingPolicy) -> list[_Draft]:
    """Fusiona un chunk demasiado pequeño con el anterior de su sección.

    No se fusiona nunca hacia una tabla ni desde una advertencia: en ambos
    casos la separación es estructural y significa algo.
    """
    if policy.min_tokens <= 0:
        return drafts
    merged: list[_Draft] = []
    for draft in drafts:
        if not merged:
            merged.append(draft)
            continue
        previous = merged[-1]
        combined = previous.tokens(policy) + draft.tokens(policy)
        blocked = (
            ChunkKind.TABLE in previous.kinds
            or ChunkKind.TABLE in draft.kinds
            or draft.kinds[:1] == (ChunkKind.WARNING,)
            or previous.oversized
            or draft.oversized
        )
        if (
            draft.tokens(policy) < policy.min_tokens
            and not blocked
            and combined <= policy.max_tokens
        ):
            merged[-1] = _Draft(
                text=f"{previous.text}\n{draft.text}",
                blocks=previous.blocks + draft.blocks,
                kinds=previous.kinds + draft.kinds,
                boundary_reason=previous.boundary_reason,
                oversized=False,
                warnings=tuple(dict.fromkeys(previous.warnings + draft.warnings)),
            )
            continue
        merged.append(draft)
    return merged


def _apply_overlap(drafts: list[_Draft], policy: ChunkingPolicy) -> list[_Draft]:
    """Añade solape solo donde el corte lo provocó el tamaño.

    En un corte estructural el documento ya dice que ahí cambia el tema;
    repetir texto solo duplicaría contenido en el índice sin añadir nada.
    """
    if policy.overlap_tokens <= 0:
        return drafts
    result: list[_Draft] = []
    for index, draft in enumerate(drafts):
        # Solo entre prosa. Una lista o un procedimiento se cortan por
        # elemento, y un elemento ya es una unidad completa: repetirlo no
        # aporta continuidad, solo lo duplica en el indice.
        if (
            index == 0
            or draft.boundary_reason != _SIZE
            or ChunkKind.PROSE not in draft.kinds
            or ChunkKind.PROSE not in drafts[index - 1].kinds
        ):
            result.append(draft)
            continue
        tail = _tail(normalize_text(drafts[index - 1].text), policy)
        if not tail:
            result.append(draft)
            continue
        result.append(
            _Draft(
                text=f"{tail} {draft.text}",
                blocks=draft.blocks,
                kinds=draft.kinds,
                boundary_reason=draft.boundary_reason,
                oversized=draft.oversized,
                warnings=draft.warnings,
                overlap_chars=len(tail) + 1,
            )
        )
    return result


def _tail(text: str, policy: ChunkingPolicy) -> str:
    """Cola del chunk anterior: frases completas dentro del presupuesto."""
    budget = policy.overlap_tokens * policy.chars_per_token
    sentences = [part for part in _SENTENCE_END.split(text) if part.strip()]
    picked: list[str] = []
    length = 0
    for sentence in reversed(sentences):
        addition = len(sentence) + (1 if picked else 0)
        if picked and length + addition > budget:
            break
        if not picked and len(sentence) > budget:
            words = sentence.split()
            fragment: list[str] = []
            size = 0
            for word in reversed(words):
                addition = len(word) + (1 if fragment else 0)
                if fragment and size + addition > budget:
                    break
                fragment.insert(0, word)
                size += addition
            return " ".join(fragment)
        picked.insert(0, sentence)
        length += addition
    return " ".join(picked)


# ---------------------------------------------------------------------
# Materialización
# ---------------------------------------------------------------------


def _materialise(
    drafts: list[_Draft],
    section: DocumentSection,
    first_ordinal: int,
    policy: ChunkingPolicy,
) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for index, draft in enumerate(drafts):
        pages = [page for block in draft.blocks for page in block.pages]
        text = normalize_text(draft.text)
        chunks.append(
            DocumentChunk(
                ordinal=first_ordinal + index,
                structural_key=f"{section.path}#{index:04d}",
                content=text,
                content_sha256=content_hash(text),
                kind=draft.kind,
                section_path=section.path,
                section_ordinal=section.ordinal,
                section_title=section.title,
                index_in_section=index,
                heading_trail=(section.title,),
                page_start=min(pages) if pages else section.page_start,
                page_end=max(pages) if pages else section.page_end,
                block_start=min(block.ordinal for block in draft.blocks) if draft.blocks else None,
                block_end=max(block.ordinal for block in draft.blocks) if draft.blocks else None,
                char_start=min(block.char_start for block in draft.blocks)
                if draft.blocks
                else None,
                char_end=max(block.char_end for block in draft.blocks) if draft.blocks else None,
                token_estimate=estimate_tokens(text, chars_per_token=policy.chars_per_token),
                char_length=len(text),
                overlap_chars=draft.overlap_chars,
                boundary_reason=draft.boundary_reason,
                oversized=draft.oversized,
                warnings=draft.warnings,
            )
        )
    return chunks
