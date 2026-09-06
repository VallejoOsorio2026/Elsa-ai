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

SAP exporta estas listas de dos formas distintas y aquí se admiten las dos:

- **Como tabla HTML.** Cada renglón es un ``<tr>``. Es el caso sencillo.
- **Como lista monoespaciada.** No hay ``<table>`` en absoluto: el export es
  una sucesión de ``<nobr>…</nobr><br>`` dentro de una fuente de ancho fijo,
  donde las columnas se dibujan alineando espacios y el tipo de cada renglón
  se indica con un icono. Es lo que produce la exportación de lista de SAP, y
  un parser que exija ``<table>`` no ve absolutamente nada en él.

Se intenta primero la lectura como tabla; si no produce ningún renglón, se
interpreta el documento como líneas. Las dos rutas comparten el mismo modelo
de salida y las mismas reglas de seguridad.

Si la estructura no se reconoce con confianza suficiente, se falla de forma
segura: la importación no se publica, el original se conserva y el
administrador recibe una explicación. Publicar una interpretación dudosa
sería peor que no publicar nada.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _SapLine:
    """Una línea lógica del export, con lo que se sabe de ella.

    ``text`` conserva los espacios interiores **sin colapsar**: en un export
    monoespaciado la alineación es la única señal de dónde empieza y termina
    cada columna, así que normalizar espacios aquí destruiría la estructura.
    """

    number: int
    indent: int
    text: str
    markers: tuple[str, ...]

    @property
    def fields(self) -> list[str]:
        """Campos separados por dos o más espacios.

        Una descripción lleva espacios simples; una separación de columnas
        lleva dos o más. Es la convención de toda lista de ancho fijo.
        """
        stripped = self.text.strip()
        return [] if not stripped else re.split(r"\s{2,}", stripped)


# Etiquetas que cierran una línea lógica. `br` es la habitual; los cierres de
# bloque se incluyen porque un export mal formado puede omitir el `br`.
_LINE_BREAK_TAGS = frozenset({"br", "nobr", "tr", "p", "div", "li", "pre", "h1", "h2", "h3"})


class _LineReader(HTMLParser):
    """Extrae el documento como líneas de texto, sin ejecutar ni seguir nada.

    Es el mismo analizador léxico pasivo que usa la ruta de tablas: no hay
    motor de scripts ni cliente HTTP que deshabilitar. Los iconos se anotan
    como *marcadores* (su ``title``, su ``alt`` o el nombre del archivo) para
    poder distinguir un material de un equipo, pero **no se descarga
    ninguno**.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[_SapLine] = []
        self.saw_script = False
        self.remote_references: set[str] = set()

        self._buffer: list[str] = []
        self._markers: list[str] = []
        self._ignore_depth = 0

    # -- Estructura ---------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _IGNORED_CONTENT_TAGS:
            self.saw_script = True
            self._ignore_depth += 1
            return
        self._record_references(attrs)
        if tag == "img":
            self._record_marker(attrs)
        if tag in _LINE_BREAK_TAGS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record_references(attrs)
        if tag == "img":
            self._record_marker(attrs)
        elif tag == "br":
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORED_CONTENT_TAGS:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if tag in _LINE_BREAK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            # Contenido de `<script>` o `<style>`: se descarta.
            return
        # Los espacios interiores se conservan; solo se unifica el espacio
        # duro, que en el export cumple exactamente la función del normal.
        self._buffer.append(data.replace("\xa0", " "))

    def close(self) -> None:
        super().close()
        self._flush()

    # -- Apoyo --------------------------------------------------------

    def _flush(self) -> None:
        text = "".join(self._buffer).replace("\r", "").replace("\n", " ")
        markers = tuple(self._markers)
        self._buffer = []
        self._markers = []
        if not text.strip() and not markers:
            return
        self.lines.append(
            _SapLine(
                number=len(self.lines) + 1,
                indent=len(text) - len(text.lstrip(" ")),
                text=text.rstrip(),
                markers=markers,
            )
        )

    def _record_marker(self, attrs: list[tuple[str, str | None]]) -> None:
        """Anota qué dice el icono, sin pedirlo a ninguna parte.

        Se prefiere el texto declarado (``title``, ``alt``) al nombre del
        archivo: atarse solo a un nombre concreto como ``s_b_matl.gif`` haría
        que el parser dejara de distinguir tipos en cuanto SAP renombrara sus
        iconos.
        """
        values = dict(attrs)
        for attribute in ("title", "alt"):
            value = values.get(attribute)
            if value and value.strip():
                self._markers.append(value.strip().lower())
                return
        source = values.get("src")
        if source:
            self._markers.append(source.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower())

    def _record_references(self, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.lower() in _REFERENCE_ATTRIBUTES and value and _REMOTE_REFERENCE.match(value):
                self.remote_references.add(value.split("?", 1)[0][:120])


# Vocabulario de los marcadores. Se comparan por subcadena porque el texto
# real varía («Material», «Componente material», «s_b_matl»).
_MATERIAL_MARKERS = ("material", "matl", "componente", "component")
_EQUIPMENT_MARKERS = ("equipo", "equipment", "equi", "objeto tecnico", "technical object")
# Una ubicación técnica es un objeto técnico, no un material: en el modelo de
# ELSA solo hay dos tipos, y le corresponde `equipment`.
_LOCATION_MARKERS = ("ubicacion", "ubic", "floc", "funcloc", "func")


def _type_from_markers(markers: Sequence[str]) -> str | None:
    """Tipo declarado por los iconos de la línea, si lo declaran."""
    for marker in markers:
        key = normalize_key(marker) or ""
        if any(token in key for token in _MATERIAL_MARKERS):
            return "material"
        if any(token in key for token in _EQUIPMENT_MARKERS):
            return "equipment"
        if any(token in key for token in _LOCATION_MARKERS):
            return "equipment"
    return None


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
        "objeto",
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

# En la ruta de líneas hace falta más evidencia que en la de tablas: allí un
# `<tr>` ya separa cabecera de datos, aquí no hay nada que las separe salvo
# su contenido.
_MIN_HEADER_COLUMNS = 3

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


def _label_key(value: object) -> str | None:
    """Clave de comparación de un rótulo de cabecera del export.

    Además de lo que hace :func:`_header_key`, retira los puntos interiores.
    SAP abrevia los rótulos con punto y sin espacio (``Ubic.técn.``), de modo
    que dejarlos dentro obligaría a enumerar cada abreviatura exacta. Se
    aplica a los dos lados de la comparación, así que sinónimo y rótulo leído
    se normalizan igual.
    """
    key = normalize_key(value)
    if key is None:
        return None
    return " ".join(key.replace(".", "").replace(":", "").split()) or None


# Rótulos de cabecera del export, en las variantes que SAP produce según el
# idioma y el ancho disponible.
_LINE_LABELS: dict[str, tuple[str, ...]] = {
    "functional_location": (
        "ubic.técn.",
        "ubic. técn.",
        "ubicación técnica",
        "ubicacion tecnica",
        "functional location",
        "funct. location",
        "ubic.tecnica",
    ),
    "description": ("denominación", "descripción", "description", "texto breve", "denom."),
    "valid_from": ("válido de", "valida de", "válida de", "valid from", "vigente desde"),
}


def _line_metadata(lines: Sequence[_SapLine]) -> dict[str, str]:
    """Busca los campos de cabecera entre las líneas del export.

    Una misma línea puede llevar varios pares rótulo/valor separados por
    columnas (``Ubic.técn.  MB-01   Denominación  Molino``), así que se
    recorren los campos por parejas. También se acepta ``Rótulo: valor``
    dentro de un solo campo.
    """
    found: dict[str, str] = {}
    for line in lines:
        fields = line.fields
        for position, field in enumerate(fields):
            label_part, _, inline_value = field.partition(":")
            label = _label_key(label_part)
            if label is None:
                continue
            for name, synonyms in _LINE_LABELS.items():
                if name in found:
                    continue
                if not any(label == _label_key(synonym) for synonym in synonyms):
                    continue
                value = normalize_text(inline_value)
                if value is None and position + 1 < len(fields):
                    value = normalize_text(fields[position + 1])
                if value is not None:
                    found[name] = value
    return found


def _header_meaning(line: _SapLine) -> list[str | None] | None:
    """Significado de cada campo de una fila de rótulos, o ``None``.

    Devuelve una lista paralela a ``line.fields``: en cada posición, el campo
    del modelo que ese rótulo designa, o ``None`` si no se reconoce.

    Se prefiere esto a cortar los renglones por la posición de carácter de
    cada rótulo. El corte por posición parece más fiel a una lista de ancho
    fijo, pero se rompe entero en cuanto la cabecera y los datos no arrancan
    exactamente en la misma columna —cosa que ocurre, por ejemplo, cuando los
    renglones llevan sangría jerárquica y la cabecera no—, y lo hace en
    silencio: no falla, devuelve valores cortados por la mitad.
    """
    fields = line.fields
    columns = _map_header(fields)
    if len(columns) < _MIN_RECOGNISED_COLUMNS:
        return None
    # Una línea de cabecera es casi toda rótulos; una de metadatos alterna
    # rótulo y valor, así que reconoce como mucho la mitad de sus campos.
    # Sin esta distinción, `Ubic.técn. | MB-01 | Denominación | Molino` pasa
    # por cabecera —«Denominación» es a la vez rótulo de campo y de columna—
    # y desplaza la cabecera real a la zona de datos.
    if len(columns) < _MIN_HEADER_COLUMNS and len(columns) != len(fields):
        return None
    meaning: list[str | None] = [None] * len(fields)
    for name, index in columns.items():
        if 0 <= index < len(meaning):
            meaning[index] = name
    return meaning


def _record_from_header(
    fields: Sequence[str], meaning: Sequence[str | None]
) -> dict[str, str | None]:
    """Interpreta un renglón cuyos campos se corresponden con los rótulos."""
    record: dict[str, str | None] = {}
    for value, name in zip(fields, meaning, strict=True):
        if name is not None:
            record[name] = normalize_text(value)
    return record


_CODE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\-]{1,39}$")
_UNIT_PATTERN = re.compile(r"^[A-Za-z]{1,4}$")


def _looks_like_code(value: str) -> bool:
    """Indica si un campo puede ser el identificador del renglón.

    Se exige al menos un dígito: los números de material y los de equipo
    siempre los llevan, y sin ese requisito una línea de totales o un rótulo
    suelto («Total», «Suma») pasaría por identificador y produciría un
    renglón inventado.
    """
    return bool(_CODE_PATTERN.match(value)) and any(char.isdigit() for char in value)


# Un nivel jerárquico es un entero pequeño; un código de material no lo es.
_MAX_LEVEL = 99


def _record_from_fields(fields: Sequence[str]) -> dict[str, str | None]:
    """Interpreta un renglón sin cabecera, por su forma.

    Se usa cuando el export no trae una fila de rótulos reconocible. Las
    reglas son estructurales y deterministas, no adivinatorias: el nivel es
    un entero pequeño al principio, la unidad es un token corto de letras al
    final, la cantidad es el número que la precede y el resto es descripción.
    Lo que no encaje queda en ``None`` y el renglón se marca como
    incompleto, nunca se rellena por conjetura.
    """
    remaining = list(fields)
    level: str | None = None
    if remaining and remaining[0].isdigit() and int(remaining[0]) <= _MAX_LEVEL:
        level = remaining.pop(0)

    # El identificador se toma ANTES que la cantidad. Un código de material es
    # un número, así que buscar primero «el último campo numérico» se lo lleva
    # por delante en cuanto la cantidad no es legible, y el renglón entero se
    # pierde por no tener identificador.
    code: str | None = None
    if remaining and _looks_like_code(remaining[0]):
        code = remaining.pop(0)

    unit: str | None = None
    if remaining and _UNIT_PATTERN.match(remaining[-1]):
        unit = remaining.pop()

    quantity: str | None = None
    for index in range(len(remaining) - 1, -1, -1):
        if normalize_quantity(remaining[index]) is not None:
            quantity = remaining.pop(index)
            break

    return {
        "level": level,
        "position": None,
        "sap_code": code,
        "description": normalize_text(" ".join(remaining)),
        "quantity": quantity,
        "unit": unit,
        "equipment": None,
        "item_category": None,
    }


def _items_from_lines(
    lines: Sequence[_SapLine], metadata: dict[str, str]
) -> tuple[list[ParsedSapItem], list[IngestionWarning]]:
    """Interpreta un export sin tablas como renglones de BOM.

    Se busca primero una fila de rótulos; si existe, manda ella y los
    renglones se cortan por sus tramos de columna. Si no existe, cada renglón
    se interpreta por su forma y por el icono que declara su tipo.
    """
    meaning: list[str | None] | None = None
    header_number = 0
    for line in lines:
        candidate = _header_meaning(line)
        if candidate is not None:
            meaning = candidate
            header_number = line.number
            break

    items: list[ParsedSapItem] = []
    unrecognised = 0
    incomplete = 0
    # Cadena de padres por nivel, para poder decir de qué cuelga cada renglón.
    parents: dict[int, str] = {}
    indents: list[int] = []

    for line in lines:
        if line.number <= header_number or not line.text.strip():
            continue
        fields = line.fields
        # La cabecera manda cuando el renglón tiene exactamente sus mismos
        # campos; si no coincide, el renglón se interpreta por su forma. Que
        # el número de campos difiera es normal —una columna vacía no deja
        # separador— y no es motivo para descartar el renglón.
        record = (
            _record_from_header(fields, meaning)
            if meaning is not None and len(fields) == len(meaning)
            else _record_from_fields(fields)
        )
        code = normalize_text(record.get("sap_code")) or normalize_text(record.get("equipment"))
        description = normalize_text(record.get("description"))
        quantity_text = normalize_text(record.get("quantity"))
        unit = normalize_text(record.get("unit"))

        entry_kind = _type_from_markers(line.markers)
        if entry_kind is None and code is not None:
            # Sin icono, la evidencia estructural decide: en una lista de BOM
            # solo los materiales llevan cantidad y unidad de medida; un
            # objeto técnico aparece sin ellas.
            if quantity_text is not None and unit is not None:
                entry_kind = "material"
            elif description is not None:
                entry_kind = "equipment"

        if entry_kind is None or code is None:
            # Puede ser un título, una línea de separación o un renglón cuya
            # estructura no se reconoce. No se inventa nada; se cuenta.
            if code is not None or (description is not None and len(line.fields) > 2):
                unrecognised += 1
            continue

        level_text = normalize_text(record.get("level"))
        if level_text is not None and level_text.isdigit():
            depth = int(level_text)
        else:
            if line.indent not in indents:
                indents.append(line.indent)
                indents.sort()
            depth = indents.index(line.indent)

        extra: dict[str, str] = {}
        category = normalize_text(record.get("item_category"))
        if category:
            extra["item_category"] = category
        parent = parents.get(depth - 1)
        if parent:
            extra["parent_code"] = parent
        parents[depth] = code
        for deeper in [key for key in parents if key > depth]:
            del parents[deeper]

        quantity = normalize_quantity(quantity_text)
        if entry_kind == "material" and (quantity is None or unit is None):
            # Un material sin cantidad legible sigue siendo evidencia válida,
            # pero no puede compararse contra Ingeniería sin intervención.
            incomplete += 1

        items.append(
            ParsedSapItem(
                source_row=len(items) + 1,
                entry_kind=entry_kind,
                position=normalize_text(record.get("position")),
                sap_code=normalize_sap_code(code),
                description=description,
                quantity=quantity,
                quantity_original=quantity_text,
                unit=unit,
                parent_path=metadata.get("functional_location"),
                depth=depth,
                extra=extra,
            )
        )

    warnings: list[IngestionWarning] = []
    if unrecognised:
        warnings.append(
            IngestionWarning(
                code="unrecognised_lines",
                message=(
                    "Some lines of the export could not be interpreted as BOM records and "
                    "were not imported. They are reported rather than guessed."
                ),
                location=f"{unrecognised} line(s)",
            )
        )
    if incomplete:
        warnings.append(
            IngestionWarning(
                code="incomplete_material_lines",
                message=(
                    "Some material lines have no readable quantity or unit. They are kept as "
                    "evidence but cannot be compared against engineering without review."
                ),
                location=f"{incomplete} line(s)",
            )
        )
    return items, warnings


def parse_sap_snapshot(data: bytes) -> ParsedSapSnapshot:
    """Interpreta el HTM exportado de SAP.

    Intenta primero leerlo como tabla y, si no produce ningún renglón, lo
    interpreta como lista monoespaciada. Lanza
    :class:`~elsa.ingestion.errors.UnrecognizedFormatError` si ninguna de las
    dos rutas reconoce nada.
    """
    text = _decode(data)

    tables = _TableReader()
    # `html.parser` tolera HTML malformado por diseño: analiza lo que puede y
    # sigue. Es exactamente lo que se quiere aquí.
    tables.feed(text)
    tables.close()

    reader = _LineReader()
    reader.feed(text)
    reader.close()

    warnings: list[IngestionWarning] = []
    if tables.saw_script or reader.saw_script:
        warnings.append(
            IngestionWarning(
                code="script_content_ignored",
                message=(
                    "The file contains script or style blocks. Their content is discarded: "
                    "the file is parsed as data and never rendered."
                ),
            )
        )
    references = tables.remote_references | reader.remote_references
    if references:
        warnings.append(
            IngestionWarning(
                code="remote_references_ignored",
                message=(
                    "The file references external resources. None of them is requested: "
                    "the parser makes no network call induced by the file."
                ),
                location=f"{len(references)} reference(s)",
            )
        )

    # Los metadatos pueden venir en una tabla de cabecera o sueltos entre las
    # líneas. Lo que diga la tabla manda, por ser la forma más estructurada.
    metadata = {**_line_metadata(reader.lines), **_extract_metadata(tables.tables)}

    items = _items_from_tables(tables.tables, metadata)
    if not items:
        items, line_warnings = _items_from_lines(reader.lines, metadata)
        warnings.extend(line_warnings)

    if not items:
        raise UnrecognizedFormatError(
            "no recognisable SAP BOM records were found, neither as a table nor as a "
            "monospaced list; the export format is not understood"
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


def _items_from_tables(
    tables: list[list[list[str]]], metadata: dict[str, str]
) -> list[ParsedSapItem]:
    """Renglones leídos de tablas HTML, cuando el export las trae."""
    items: list[ParsedSapItem] = []
    source_row = 0
    for table in tables:
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
    return items
