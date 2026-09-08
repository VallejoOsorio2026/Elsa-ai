"""Extractor estructural de documentos de texto plano y Markdown.

Es el primer adaptador del puerto ``document_extraction`` y el único de este
bloque. Lee texto —no PDF, no imágenes, no OCR— y reconoce las unidades que
el chunking necesita respetar: títulos, párrafos, listas, pasos numerados,
advertencias, tablas y pies.

Por qué texto y no PDF todavía: la fase de aceptación de este bloque se
demuestra con documentos sintéticos, y un extractor de PDF añade una
dependencia y una fuente de indeterminismo (dos versiones de la librería
ordenan los bloques distinto) antes de que exista nada que consuma los
chunks. El puerto queda listo para que el adaptador de PDF entre sin tocar
el chunking.

## Convenciones que reconoce

| Marca | Se lee como |
|---|---|
| `#` … `######` | Título, con su profundidad |
| `\\f` (avance de página) | Frontera de página, **no** de párrafo |
| `- `, `* `, `• ` | Elemento de lista |
| `1. `, `2) `, `3.- ` | Paso numerado |
| `> …` o una línea que empieza por `ADVERTENCIA`, `PELIGRO`… | Advertencia |
| `\\| a \\| b \\|` | Fila de tabla |
| `Figura 3`, `Tabla 2`… | Pie |
| Línea en blanco | Fin de bloque |

El avance de página merece explicación. En el texto que produce cualquier
extractor de PDF, `\\f` marca dónde termina una página. Tratarlo como una
línea en blanco parte en dos todo párrafo que cruce de página, y entonces la
mitad de una frase queda en un chunk y la otra mitad en otro. Aquí un `\\f`
**avanza la página y no cierra nada**; solo una línea realmente vacía cierra
un bloque.
"""

import re
import unicodedata

from elsa.ingestion.model import IngestionWarning
from elsa.ports.document_extraction import (
    BlockKind,
    ExtractedBlock,
    ExtractedDocument,
    UnsupportedDocumentError,
)

__all__ = ["StructuredTextExtractor"]

_SUPPORTED_CONTENT_TYPES = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        "text/x-rst",
    }
)

_SUPPORTED_SUFFIXES = (".txt", ".md", ".markdown", ".text")

# Orden deliberado: se prueba UTF-8 primero porque es lo que produce
# cualquier herramienta moderna, y Windows-1252 al final porque acepta
# cualquier byte y por tanto nunca falla (decodificaría basura como texto).
_ENCODINGS = ("utf-8-sig", "utf-8", "utf-16", "cp1252")

_HEADING = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*#*$")
_HEADING_NUMBER = re.compile(r"^(?P<label>\d+(?:\.\d+)*)[.)]?\s+(?P<title>.+)$")
_STEP = re.compile(r"^(?P<label>\d{1,3})(?:\.-|[.)])\s+(?P<text>.+)$")
_LIST_ITEM = re.compile(r"^[-*•·]\s+(?P<text>.+)$")
_TABLE_ROW = re.compile(r"^\|.*\|$")
_TABLE_SEPARATOR_CELL = re.compile(r"^:?-{2,}:?$")
_BLOCKQUOTE = re.compile(r"^>\s?(?P<text>.*)$")
_CAPTION = re.compile(
    r"^(?:figura|fig\.|tabla|cuadro|plano|imagen|esquema)\s+\d+", re.IGNORECASE | re.UNICODE
)
_WARNING_KEYWORD = re.compile(
    r"^[¡!]*\s*(?:advertencia|precaucion|peligro|atencion|aviso|cuidado"
    r"|warning|caution|danger|nota\s+importante)\b",
)
_WHITESPACE = re.compile(r"\s+")


def _fold(value: str) -> str:
    """Minúsculas sin acentos, para reconocer rótulos escritos de cualquier forma."""
    decomposed = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


class _Line:
    """Una línea del documento con su posición y su página."""

    __slots__ = ("content", "end", "is_page_break", "page_end", "page_start", "start")

    def __init__(
        self,
        content: str,
        start: int,
        end: int,
        page_start: int,
        page_end: int,
        is_page_break: bool,
    ) -> None:
        self.content = content
        self.start = start
        self.end = end
        self.page_start = page_start
        self.page_end = page_end
        self.is_page_break = is_page_break

    @property
    def is_blank(self) -> bool:
        return not self.content.strip()


class _Pending:
    """Bloque en construcción."""

    __slots__ = ("header_rows", "kind", "level", "lines", "number_label", "rows")

    def __init__(self, kind: BlockKind) -> None:
        self.kind = kind
        self.lines: list[_Line] = []
        self.level: int | None = None
        self.number_label: str | None = None
        self.rows: list[tuple[str, ...]] = []
        self.header_rows = 0


class StructuredTextExtractor:
    """Adaptador de :class:`~elsa.ports.document_extraction.DocumentExtractionPort`.

    Determinístico por construcción: no consulta relojes, no genera
    identificadores y no depende del orden de ningún diccionario. Los mismos
    bytes producen siempre los mismos bloques.
    """

    name = "structured_text"
    version = "1"

    def supports(self, content_type: str, filename: str | None = None) -> bool:
        if content_type.split(";")[0].strip().lower() in _SUPPORTED_CONTENT_TYPES:
            return True
        if filename is None:
            return False
        return filename.lower().endswith(_SUPPORTED_SUFFIXES)

    async def extract(
        self,
        content: bytes,
        *,
        content_type: str,
        filename: str | None = None,
    ) -> ExtractedDocument:
        if not self.supports(content_type, filename):
            raise UnsupportedDocumentError(
                f"the structured text extractor cannot read {content_type!r}; "
                "no OCR or PDF engine is configured in this block"
            )
        text = _decode(content)
        warnings: list[IngestionWarning] = []
        blocks = _blocks(text, warnings)
        if not blocks:
            warnings.append(
                IngestionWarning(
                    code="empty_document",
                    message="the document produced no readable block",
                )
            )
        return ExtractedDocument(
            text=text,
            blocks=blocks,
            page_count=1 + text.count("\f"),
            content_type=content_type,
            extractor=self.name,
            extractor_version=self.version,
            warnings=tuple(warnings),
        )


def _decode(content: bytes) -> str:
    """Decodifica y normaliza los saltos de línea, sin tocar los de página.

    Un byte nulo es la señal de que esto no es texto: un binario renombrado
    a ``.txt`` se rechaza aquí y no llega a ningún parser.
    """
    if b"\x00" in content.replace(b"\x00\x00", b"") and not content.startswith(
        (b"\xff\xfe", b"\xfe\xff")
    ):
        raise UnsupportedDocumentError("the file contains NUL bytes: it is not a text document")
    for encoding in _ENCODINGS:
        try:
            decoded = content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        return decoded.replace("\r\n", "\n").replace("\r", "\n")
    raise UnsupportedDocumentError("the file could not be decoded as text")


def _lines(text: str) -> list[_Line]:
    """Corta el texto en líneas conservando desplazamientos y páginas."""
    result: list[_Line] = []
    page = 1
    offset = 0
    for raw in text.split("\n"):
        start = offset
        end = offset + len(raw)
        page_start = page
        # Un `\f` dentro de la línea deja el contenido posterior en la página
        # siguiente. La página de inicio se toma tras los avances que
        # preceden al primer carácter con contenido.
        leading_breaks = len(raw) - len(raw.lstrip("\f"))
        page_start = page + leading_breaks
        page += raw.count("\f")
        content = raw.replace("\f", "")
        result.append(
            _Line(
                content=content,
                start=start,
                end=end,
                page_start=page_start,
                page_end=page,
                is_page_break="\f" in raw,
            )
        )
        offset = end + 1
    return result


def _blocks(text: str, warnings: list[IngestionWarning]) -> tuple[ExtractedBlock, ...]:
    """Reúne las líneas en bloques estructurales.

    Es una máquina de estados de una sola pasada: cada línea decide si
    continúa el bloque abierto o lo cierra y abre otro. Una sola pasada es lo
    que hace el resultado reproducible sin depender de en qué orden se
    miraron las cosas.
    """
    blocks: list[ExtractedBlock] = []
    pending: _Pending | None = None

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            block = _materialise(pending, len(blocks), warnings)
            if block is not None:
                blocks.append(block)
            pending = None

    for line in _lines(text):
        if line.is_blank:
            # Un avance de página no cierra nada: solo cambia de página. Una
            # línea realmente vacía sí cierra el bloque.
            if not line.is_page_break:
                flush()
            elif pending is not None:
                pending.lines.append(line)
            continue

        stripped = line.content.strip()

        heading = _HEADING.match(stripped)
        if heading is not None:
            flush()
            pending = _Pending(BlockKind.HEADING)
            pending.level = len(heading.group("hashes"))
            title = heading.group("title").strip()
            numbered = _HEADING_NUMBER.match(title)
            if numbered is not None:
                pending.number_label = numbered.group("label")
                title = numbered.group("title").strip()
            pending.lines.append(_replace_content(line, title))
            flush()
            continue

        if _TABLE_ROW.match(stripped):
            if pending is None or pending.kind is not BlockKind.TABLE:
                flush()
                pending = _Pending(BlockKind.TABLE)
            pending.lines.append(line)
            continue

        quote = _BLOCKQUOTE.match(stripped)
        if quote is not None:
            body = quote.group("text").strip()
            if pending is None or pending.kind is not BlockKind.WARNING:
                flush()
                pending = _Pending(BlockKind.WARNING)
            pending.lines.append(_replace_content(line, body))
            continue

        if _WARNING_KEYWORD.match(_fold(stripped)):
            flush()
            pending = _Pending(BlockKind.WARNING)
            pending.lines.append(line)
            continue

        step = _STEP.match(stripped)
        if step is not None:
            flush()
            pending = _Pending(BlockKind.STEP)
            pending.number_label = step.group("label")
            pending.lines.append(_replace_content(line, step.group("text").strip()))
            continue

        item = _LIST_ITEM.match(stripped)
        if item is not None:
            flush()
            pending = _Pending(BlockKind.LIST_ITEM)
            pending.lines.append(_replace_content(line, item.group("text").strip()))
            continue

        if _CAPTION.match(stripped):
            flush()
            pending = _Pending(BlockKind.CAPTION)
            pending.lines.append(line)
            continue

        # Texto corriente: continúa el bloque abierto si admite continuación.
        if pending is None or pending.kind is BlockKind.TABLE:
            flush()
            pending = _Pending(BlockKind.PARAGRAPH)
        pending.lines.append(line)

    flush()
    return tuple(blocks)


def _replace_content(line: _Line, content: str) -> _Line:
    """Misma línea con el contenido ya despojado de su marca.

    Los desplazamientos no cambian: siguen apuntando a la línea completa del
    documento original, marca incluida, que es lo que hay que poder mostrar.
    """
    return _Line(
        content=content,
        start=line.start,
        end=line.end,
        page_start=line.page_start,
        page_end=line.page_end,
        is_page_break=line.is_page_break,
    )


def _materialise(
    pending: _Pending, ordinal: int, warnings: list[IngestionWarning]
) -> ExtractedBlock | None:
    """Convierte el bloque en construcción en un bloque inmutable."""
    content_lines = [line for line in pending.lines if line.content.strip()]
    if not content_lines:
        return None

    char_start = content_lines[0].start
    char_end = content_lines[-1].end
    page_start = min(line.page_start for line in content_lines)
    page_end = max(line.page_end for line in content_lines)

    rows: tuple[tuple[str, ...], ...] = ()
    header_rows = 0
    if pending.kind is BlockKind.TABLE:
        rows, header_rows = _table_rows(content_lines, ordinal, warnings)
        if not rows:
            return None
        text = "\n".join(" | ".join(row) for row in rows)
    else:
        joined = " ".join(line.content.strip() for line in content_lines)
        text = _WHITESPACE.sub(" ", joined).strip()

    if not text:
        return None

    return ExtractedBlock(
        ordinal=ordinal,
        kind=pending.kind,
        text=text,
        char_start=char_start,
        char_end=char_end,
        page_start=page_start,
        page_end=page_end,
        level=pending.level,
        number_label=pending.number_label,
        rows=rows,
        header_rows=header_rows,
    )


def _table_rows(
    lines: list[_Line], ordinal: int, warnings: list[IngestionWarning]
) -> tuple[tuple[tuple[str, ...], ...], int]:
    """Filas de la tabla y cuántas de ellas son encabezado.

    El encabezado se reconoce por la fila separadora (``|---|---|``). Sin
    ella **no se supone ninguno**: dar por hecho que la primera fila son
    rótulos haría que, al partir una tabla larga, se repitiera como
    encabezado una fila de datos. Se avisa en su lugar.
    """
    rows: list[tuple[str, ...]] = []
    header_rows = 0
    separator_seen = False
    for line in lines:
        cells = tuple(cell.strip() for cell in line.content.strip().strip("|").split("|"))
        if cells and all(_TABLE_SEPARATOR_CELL.match(cell) for cell in cells if cell):
            if not separator_seen and rows:
                header_rows = len(rows)
                separator_seen = True
            continue
        rows.append(cells)
    if rows and not separator_seen:
        warnings.append(
            IngestionWarning(
                code="table_without_header_marker",
                message="the table declares no header row; it will not be repeated when split",
                location=f"block:{ordinal}",
            )
        )
    return tuple(rows), header_rows
