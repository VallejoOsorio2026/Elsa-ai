"""Lectura del HTM exportado de SAP.

El archivo representa *cómo se ve el BOM en SAP en una fecha determinada*.
No es autoridad sobre nada: una diferencia con el BOM de Ingeniería es
evidencia de una desviación, no prueba de que SAP tenga razón.

El archivo se trata como **dato, nunca como página**. No se renderiza en un
navegador, no se ejecuta JavaScript, no se interpreta CSS y no se descarga
ni un solo recurso de los que mencione. El análisis se hace con
``html.parser`` de la biblioteca estándar, que es un analizador léxico puro:
no tiene motor de scripts ni cliente HTTP, así que no hay nada que
deshabilitar. El contenido de ``<script>`` y ``<style>`` se descarta al
leerlo, y la presencia de cualquiera de los dos se reporta como aviso.

La estructura se reconoce **semánticamente**, por los rótulos de las
columnas y de los campos, nunca por identificadores de fila del tipo
``l0006002``: esos cambian entre exportaciones y atarse a ellos haría que el
parser dejara de funcionar sin avisar.

Si la estructura no se reconoce con confianza suficiente, se falla de forma
segura: la importación no se publica, el original se conserva y el
administrador recibe una explicación. Publicar una interpretación dudosa
sería peor que no publicar nada.
"""

import logging
import re
from datetime import date
from html.parser import HTMLParser

from elsa.core.normalization import (
    normalize_key,
    normalize_quantity,
    normalize_sap_code,
    normalize_text,
)
from elsa.ingestion.errors import UnrecognizedFormatError
from elsa.ingestion.model import IngestionWarning, ParsedSapItem, ParsedSapSnapshot

_logger = logging.getLogger("elsa.ingestion.htm")

__all__ = ["parse_sap_snapshot"]

# Etiquetas cuyo contenido textual se descarta por completo.
_IGNORED_CONTENT_TAGS = frozenset({"script", "style"})

# Atributos que pueden traer una dirección. No se resuelve ninguno; solo se
# mira si existen para poder avisar de que el archivo las trae.
_REFERENCE_ATTRIBUTES = frozenset({"src", "href", "background", "data", "action", "codebase"})

_REMOTE_REFERENCE = re.compile(r"^\s*(?:[a-z][a-z0-9+.-]*:)?//|^\s*(?:https?|ftp|file|data):", re.I)


def _decode(data: bytes) -> str:
    """Decodifica el archivo respetando la codificación que declare.

    Los exportes de SAP llegan en UTF-8, en UTF-16 o en Windows-1252 según la
    versión y el idioma del sistema. Se busca primero una marca de orden de
    bytes, después una declaración ``charset`` y, si nada de eso aparece, se
    prueba UTF-8 y se termina en Windows-1252, que acepta cualquier byte.
    Nunca se falla por codificación: perder el archivo por una tilde sería
    absurdo.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")

    head = data[:4096].lower()
    match = re.search(rb"charset\s*=\s*[\"']?\s*([a-z0-9_\-]+)", head)
    if match:
        try:
            return data.decode(match.group(1).decode("ascii"), errors="replace")
        except (LookupError, UnicodeDecodeError):
            pass
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


class _TableReader(HTMLParser):
    """Extrae tablas como texto plano, sin ejecutar ni seguir nada."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self.saw_script = False
        self.remote_references: set[str] = set()

        self._open_tables: list[list[list[str]]] = []
        self._cell: list[str] | None = None
        self._ignore_depth = 0

    # -- Estructura ---------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _IGNORED_CONTENT_TAGS:
            self.saw_script = True
            self._ignore_depth += 1
            return
        self._record_references(attrs)
        # Los exportes de SAP omiten con frecuencia las etiquetas de cierre.
        # Abrir una celda, una fila o una tabla cierra implícitamente la celda
        # en curso; sin esto, un archivo sin `</td>` perdería todo su
        # contenido en silencio, que es la peor forma de fallar.
        if tag in ("table", "tr", "td", "th"):
            self._close_cell()
        if tag == "table":
            self._open_tables.append([])
        elif tag == "tr" and self._open_tables:
            self._open_tables[-1].append([])
        elif tag in ("td", "th"):
            if self._open_tables and not self._open_tables[-1]:
                # Una celda sin `<tr>` explícito: SAP a veces los omite.
                self._open_tables[-1].append([])
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record_references(attrs)
        if tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORED_CONTENT_TAGS:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if tag in ("td", "th"):
            self._close_cell()
        elif tag == "tr":
            self._close_cell()
        elif tag == "table":
            self._close_cell()
            if self._open_tables:
                self.tables.append(self._open_tables.pop())

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            # Contenido de `<script>` o `<style>`: se descarta, no se guarda
            # ni se interpreta.
            return
        if self._cell is not None:
            self._cell.append(data)

    def close(self) -> None:
        super().close()
        # Un archivo malformado puede quedarse sin cerrar sus tablas. Lo que
        # se alcanzó a leer sigue siendo utilizable.
        self._close_cell()
        while self._open_tables:
            self.tables.append(self._open_tables.pop())

    # -- Apoyo --------------------------------------------------------

    def _close_cell(self) -> None:
        if self._cell is None:
            return
        text = normalize_text("".join(self._cell)) or ""
        if self._open_tables and self._open_tables[-1]:
            self._open_tables[-1][-1].append(text)
        self._cell = None

    def _record_references(self, attrs: list[tuple[str, str | None]]) -> None:
        """Anota las direcciones externas que declara el archivo. No las abre."""
        for name, value in attrs:
            if name.lower() in _REFERENCE_ATTRIBUTES and value and _REMOTE_REFERENCE.match(value):
                self.remote_references.add(value.split("?", 1)[0][:120])


# --- Reconocimiento semántico ----------------------------------------

_METADATA_LABELS: dict[str, tuple[str, ...]] = {
    "functional_location": (
        "ubicacion tecnica",
        "ubic. tecnica",
        "ubic.tecnica",
        "functional location",
        "funct. location",
    ),
    "description": ("denominacion", "descripcion", "description", "texto breve"),
    "valid_from": ("valido de", "valida de", "valid from", "vigente desde", "fecha"),
}

_COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "position": ("pos", "posicion", "item", "no", "num"),
    "sap_code": (
        "material",
        "numero de material",
        "nro material",
        "material number",
        "componente",
        "component",
    ),
    "description": (
        "denominacion",
        "descripcion",
        "texto breve",
        "texto breve de material",
        "description",
        "object description",
    ),
    "quantity": ("cantidad", "ctd", "ctd.", "qty", "quantity", "cant"),
    "unit": ("um", "u.m.", "unidad", "unidad de medida", "uom", "base unit"),
    "equipment": (
        "equipo",
        "equipment",
        "objeto tecnico",
        "numero de equipo",
        "equipo inferior",
    ),
    "level": ("nivel", "level", "niv", "niv."),
    "item_category": ("ctg", "categoria", "clase de item", "item category", "ctg.item"),
}


def _header_key(value: object) -> str | None:
    """Clave de comparación de un rótulo, sin su puntuación decorativa.

    SAP abrevia con punto (``Pos.``, ``Ctd.``, ``U.M.``) y a veces cierra con
    dos puntos. Esa puntuación no distingue una columna de otra, así que se
    retira en los dos lados de la comparación: en el sinónimo y en el rótulo
    leído del archivo.
    """
    key = normalize_key(value)
    if key is None:
        return None
    return key.strip(" .:;-") or None


_COLUMN_INDEX: dict[str, str] = {}
for _field, _synonyms in _COLUMN_SYNONYMS.items():
    for _synonym in _synonyms:
        _key = _header_key(_synonym)
        if _key is not None:
            _COLUMN_INDEX.setdefault(_key, _field)

# Una tabla es de datos si su fila de encabezados reconoce al menos estas
# columnas. Con una sola, cualquier tabla de maquetación pasaría por tabla de
# datos.
_MIN_RECOGNISED_COLUMNS = 2

_DATE_PATTERNS = (
    (re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$"), (2, 1, 0)),
    (re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$"), (0, 1, 2)),
)


def _parse_date(value: str | None) -> date | None:
    """Interpreta una fecha en los formatos que exporta SAP, o ``None``."""
    text = normalize_text(value)
    if text is None:
        return None
    for pattern, (year, month, day) in _DATE_PATTERNS:
        match = pattern.match(text)
        if match:
            try:
                return date(
                    int(match.group(year + 1)),
                    int(match.group(month + 1)),
                    int(match.group(day + 1)),
                )
            except ValueError:
                return None
    return None


def _map_header(row: list[str]) -> dict[str, int]:
    """Columnas reconocidas de una posible fila de encabezados."""
    mapping: dict[str, int] = {}
    for position, cell in enumerate(row):
        key = _header_key(cell)
        if key is None:
            continue
        field = _COLUMN_INDEX.get(key)
        if field is None:
            # Igual que en el XLSX: el rótulo real suele traer aclaraciones.
            candidates = {
                candidate
                for synonym, candidate in _COLUMN_INDEX.items()
                if len(synonym) >= 4 and (synonym in key or key in synonym)
            }
            field = candidates.pop() if len(candidates) == 1 else None
        if field is not None and field not in mapping:
            mapping[field] = position
    return mapping


def _extract_metadata(tables: list[list[list[str]]]) -> dict[str, str]:
    """Busca los campos de cabecera por su rótulo, en cualquier tabla.

    SAP los coloca a veces en celdas contiguas (``Ubicación técnica`` |
    ``MB-01``) y a veces en una sola celda separados por dos puntos. Se
    aceptan ambas formas; ninguna depende de la posición en el documento.
    """
    found: dict[str, str] = {}
    for table in tables:
        for row in table:
            for position, cell in enumerate(row):
                label = _header_key(cell.split(":", 1)[0] if ":" in cell else cell)
                if label is None:
                    continue
                for field, labels in _METADATA_LABELS.items():
                    if field in found:
                        continue
                    if not any(label == _header_key(name) for name in labels):
                        continue
                    value = None
                    if ":" in cell:
                        value = normalize_text(cell.split(":", 1)[1])
                    if value is None and position + 1 < len(row):
                        value = normalize_text(row[position + 1])
                    if value is not None:
                        found[field] = value
    return found


def _cell(row: list[str], columns: dict[str, int], field: str) -> str | None:
    """Valor de una columna reconocida en un renglón, o ``None``."""
    index = columns.get(field)
    if index is None or index >= len(row):
        return None
    return normalize_text(row[index])


def _classify(row: list[str], columns: dict[str, int], has_material_column: bool) -> str | None:
    """Decide si un renglón es un material o un equipo/objeto técnico.

    La distinción es estructural, no cosmética: comparar un equipo hijo
    contra un material del BOM inventaría una discrepancia en cada
    reconciliación.
    """
    if _cell(row, columns, "sap_code"):
        return "material"
    if _cell(row, columns, "equipment"):
        return "equipment"
    # Una tabla sin columna de material cuyo renglón trae descripción es una
    # lista de objetos técnicos.
    if not has_material_column and _cell(row, columns, "description"):
        return "equipment"
    return None


def _build_item(
    row: list[str],
    columns: dict[str, int],
    *,
    source_row: int,
    entry_kind: str,
    parent_path: str | None,
) -> ParsedSapItem:
    """Construye un renglón del snapshot a partir de una fila reconocida."""
    raw_quantity = _cell(row, columns, "quantity")
    level = normalize_quantity(_cell(row, columns, "level"))
    equipment_code = _cell(row, columns, "equipment")

    extra: dict[str, str] = {}
    category = _cell(row, columns, "item_category")
    if category:
        extra["item_category"] = category
    # Un material colgado de un equipo hijo conserva de cuál: es contexto
    # jerárquico, no un segundo código de material.
    if equipment_code and entry_kind == "material":
        extra["equipment"] = equipment_code

    identifier = _cell(row, columns, "sap_code") if entry_kind == "material" else equipment_code
    return ParsedSapItem(
        source_row=source_row,
        entry_kind=entry_kind,
        position=_cell(row, columns, "position"),
        sap_code=normalize_sap_code(identifier),
        description=_cell(row, columns, "description"),
        quantity=normalize_quantity(raw_quantity),
        quantity_original=raw_quantity,
        unit=_cell(row, columns, "unit"),
        parent_path=parent_path,
        depth=int(level) if level is not None and level >= 0 else 0,
        extra=extra,
    )


def parse_sap_snapshot(data: bytes) -> ParsedSapSnapshot:
    """Interpreta el HTM exportado de SAP.

    Lanza :class:`~elsa.ingestion.errors.UnrecognizedFormatError` si no
    encuentra ninguna tabla de datos reconocible.
    """
    reader = _TableReader()
    # `html.parser` tolera HTML malformado por diseño: analiza lo que puede y
    # sigue. Es exactamente lo que se quiere aquí.
    reader.feed(_decode(data))
    reader.close()

    warnings: list[IngestionWarning] = []
    if reader.saw_script:
        warnings.append(
            IngestionWarning(
                code="script_content_ignored",
                message=(
                    "The file contains script or style blocks. Their content is discarded: "
                    "the file is parsed as data and never rendered."
                ),
            )
        )
    if reader.remote_references:
        warnings.append(
            IngestionWarning(
                code="remote_references_ignored",
                message=(
                    "The file references external resources. None of them is requested: "
                    "the parser makes no network call induced by the file."
                ),
                location=f"{len(reader.remote_references)} reference(s)",
            )
        )

    metadata = _extract_metadata(reader.tables)

    items: list[ParsedSapItem] = []
    source_row = 0
    for table in reader.tables:
        for header_position, candidate in enumerate(table):
            columns = _map_header(candidate)
            if len(columns) < _MIN_RECOGNISED_COLUMNS:
                continue
            has_material = "sap_code" in columns

            for row in table[header_position + 1 :]:
                if not any(normalize_text(value) for value in row):
                    continue
                entry_kind = _classify(row, columns, has_material)
                if entry_kind is None:
                    continue
                source_row += 1
                items.append(
                    _build_item(
                        row,
                        columns,
                        source_row=source_row,
                        entry_kind=entry_kind,
                        parent_path=metadata.get("functional_location"),
                    )
                )
            # La fila de encabezados de esta tabla ya se usó: las siguientes
            # filas son datos, no otro encabezado.
            break

    if not items:
        raise UnrecognizedFormatError(
            "no recognisable SAP BOM table was found; the export format is not understood"
        )

    if "valid_from" not in metadata:
        warnings.append(
            IngestionWarning(
                code="missing_valid_from",
                message="The export does not state a 'valid from' date.",
            )
        )
    if "functional_location" not in metadata:
        warnings.append(
            IngestionWarning(
                code="missing_functional_location",
                message="The export does not state a functional location.",
            )
        )

    _logger.info(
        "sap snapshot parsed",
        extra={
            "items": len(items),
            "materials": sum(1 for item in items if item.entry_kind == "material"),
            "equipments": sum(1 for item in items if item.entry_kind == "equipment"),
        },
    )
    return ParsedSapSnapshot(
        functional_location=metadata.get("functional_location"),
        description=metadata.get("description"),
        valid_from=_parse_date(metadata.get("valid_from")),
        items=tuple(items),
        warnings=tuple(warnings),
    )
