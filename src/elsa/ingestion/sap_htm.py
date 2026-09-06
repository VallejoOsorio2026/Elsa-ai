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
class _Fragment:
    """Un trozo del documento: texto o icono.

    SAP no dibuja un renglón como una cadena: lo reparte en varios ``<nobr>``
    con iconos intercalados. Modelar el fragmento antes que la línea es lo que
    permite después reunirlos sin perder ni el orden ni la separación.
    """

    kind: str
    text: str = ""
    icon_title: str | None = None
    icon_alt: str | None = None
    icon_source: str | None = None

    @property
    def fields(self) -> list[str]:
        """Campos que aporta este fragmento.

        Un fragmento puede traer una columna entera (``"MAT-1  Pieza  2  UN"``)
        o un solo valor (``"2"``). Se parte por dos o más espacios, que es la
        separación de columnas; los espacios simples pertenecen al texto.
        """
        stripped = self.text.strip()
        return [] if not stripped else re.split(r"\s{2,}", stripped)


@dataclass(frozen=True, slots=True)
class _LogicalLine:
    """Un renglón visual completo, reunido a partir de sus fragmentos."""

    number: int
    fragments: tuple[_Fragment, ...]

    @property
    def text(self) -> str:
        """Texto concatenado, con la separación original intacta."""
        return "".join(fragment.text for fragment in self.fragments)

    @property
    def indent(self) -> int:
        """Espacios iniciales del renglón, **antes** de colapsar nada.

        Se mide sobre el texto crudo porque es la única evidencia de nivel
        jerárquico que trae un export sin columna de nivel. Normalizar
        espacios antes de medirla la destruiría.
        """
        text = self.text
        return len(text) - len(text.lstrip(" "))

    @property
    def fields(self) -> list[str]:
        """Campos del renglón, vengan de uno o de varios fragmentos."""
        values: list[str] = []
        for fragment in self.fragments:
            if fragment.kind == "text":
                values.extend(fragment.fields)
        return values

    @property
    def icons(self) -> tuple[_Fragment, ...]:
        return tuple(f for f in self.fragments if f.kind == "icon")

    @property
    def is_blank(self) -> bool:
        return not self.fields and not self.icons


# Etiquetas que cierran una línea lógica. `nobr` **no** está: cierra un
# fragmento, no un renglón. Tratarlo como frontera parte cada registro en
# tantos trozos como columnas tenga y ninguno se reconoce.
_LINE_BREAK_TAGS = frozenset({"br", "tr", "p", "div", "li", "pre", "h1", "h2", "h3"})


class _LineReader(HTMLParser):
    """Reúne el documento en líneas lógicas, sin ejecutar ni seguir nada.

    Analizador léxico pasivo: no hay motor de scripts ni cliente HTTP que
    deshabilitar. Los iconos se anotan con lo que declaran (``title``,
    ``alt``) y con el nombre del recurso, pero **ninguno se descarga**.

    La frontera de renglón es ``<br>``. Un export que no use ``<br>`` en
    absoluto —los hay— se agrupa entonces por ``</nobr>``, que en ese caso sí
    delimita el renglón. La decisión se toma al final, cuando ya se sabe qué
    contiene el documento, en vez de suponerlo por adelantado.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[_LogicalLine] = []
        self.saw_script = False
        self.remote_references: set[str] = set()
        self.nobr_fragments = 0
        self.br_boundaries = 0

        self._fragments: list[_Fragment] = []
        self._boundaries: list[tuple[int, str]] = []
        self._buffer: list[str] = []
        self._ignore_depth = 0

    # -- Estructura ---------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _IGNORED_CONTENT_TAGS:
            self.saw_script = True
            self._ignore_depth += 1
            return
        self._record_references(attrs)
        if tag == "img":
            self._append_icon(attrs)
        elif tag == "nobr":
            self.nobr_fragments += 1
            self._close_text()
        elif tag in _LINE_BREAK_TAGS:
            self._boundary("br" if tag == "br" else "block")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._record_references(attrs)
        if tag == "img":
            self._append_icon(attrs)
        elif tag == "br":
            self._boundary("br")

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORED_CONTENT_TAGS:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if tag == "nobr":
            self._boundary("nobr")
        elif tag in _LINE_BREAK_TAGS:
            self._boundary("block")

    def handle_data(self, data: str) -> None:
        if self._ignore_depth:
            # Contenido de `<script>` o `<style>`: se descarta entero.
            return
        # El espacio duro cumple exactamente la función del normal en estos
        # exports; se unifica aquí para que la indentación se pueda medir.
        # Los espacios NO se colapsan: eso ocurre al extraer campos.
        self._buffer.append(data.replace("\xa0", " ").replace("\r", "").replace("\n", " "))

    def close(self) -> None:
        super().close()
        self._close_text()
        self._build_lines()

    # -- Apoyo --------------------------------------------------------

    def _close_text(self) -> None:
        text = "".join(self._buffer)
        self._buffer = []
        if text:
            self._fragments.append(_Fragment(kind="text", text=text))

    def _boundary(self, kind: str) -> None:
        self._close_text()
        if kind == "br":
            self.br_boundaries += 1
        self._boundaries.append((len(self._fragments), kind))

    def _append_icon(self, attrs: list[tuple[str, str | None]]) -> None:
        """Anota lo que el icono declara. No pide el recurso a ninguna parte."""
        self._close_text()
        values = dict(attrs)
        self._fragments.append(
            _Fragment(
                kind="icon",
                icon_title=(values.get("title") or "").strip() or None,
                icon_alt=(values.get("alt") or "").strip() or None,
                icon_source=(values.get("src") or "").strip() or None,
            )
        )

    def _build_lines(self) -> None:
        """Agrupa los fragmentos en renglones según la frontera que aplique."""
        kinds = {"br", "block"} if self.br_boundaries else {"nobr", "block"}
        cuts = sorted({index for index, kind in self._boundaries if kind in kinds})
        cuts = [cut for cut in cuts if 0 < cut < len(self._fragments)]

        groups: list[tuple[_Fragment, ...]] = []
        previous = 0
        for cut in [*cuts, len(self._fragments)]:
            group = tuple(self._fragments[previous:cut])
            if group:
                groups.append(group)
            previous = cut

        for group in groups:
            line = _LogicalLine(number=len(self.lines) + 1, fragments=group)
            # Un renglón en blanco separa bloques; no aporta nada que leer.
            if not line.is_blank:
                self.lines.append(line)

    def _record_references(self, attrs: list[tuple[str, str | None]]) -> None:
        for name, value in attrs:
            if name.lower() in _REFERENCE_ATTRIBUTES and value and _REMOTE_REFERENCE.match(value):
                self.remote_references.add(value.split("?", 1)[0][:120])


# Vocabulario de los iconos. Se compara por subcadena porque el texto real
# varía («Material», «Componente material», «s_b_matl»).
_MATERIAL_MARKERS = ("material", "matl", "componente", "component")
_EQUIPMENT_MARKERS = ("equipo", "equipment", "equi", "objeto tecnico", "technical object")
# Una ubicación técnica es un objeto técnico, no un material: en el modelo de
# ELSA solo hay dos tipos, y le corresponde `equipment`.
_LOCATION_MARKERS = ("ubicacion", "ubic", "floc", "funcloc", "func")


def _kind_of_marker(value: str | None) -> str | None:
    """Tipo que designa un texto de icono, o ``None`` si no designa ninguno."""
    key = normalize_key(value) or ""
    if not key:
        return None
    if any(token in key for token in _MATERIAL_MARKERS):
        return "material"
    if any(token in key for token in _EQUIPMENT_MARKERS):
        return "equipment"
    if any(token in key for token in _LOCATION_MARKERS):
        return "equipment"
    return None


def _type_from_icons(icons: Sequence[_Fragment]) -> tuple[str | None, bool]:
    """Tipo declarado por los iconos del renglón y si la evidencia es fuerte.

    Prioridad explícita:

    1. **Fuerte**: lo que el icono declara en ``title`` o ``alt``. Es texto
       puesto por SAP para describir el objeto, no un detalle de presentación.
    2. **Secundaria**: el nombre del archivo del icono. Sirve cuando no hay
       texto declarado, pero nunca decide por sí solo frente a un ``title``:
       atarse a ``s_b_matl.gif`` dejaría de funcionar en cuanto SAP renombrara
       sus recursos.

    Señales fuertes contradictorias (un icono dice Material y otro Equipo) no
    se resuelven: se devuelve ``None`` y el renglón queda sin tipo.
    """
    strong: set[str] = set()
    weak: set[str] = set()
    for icon in icons:
        for declared in (icon.icon_title, icon.icon_alt):
            kind = _kind_of_marker(declared)
            if kind is not None:
                strong.add(kind)
        if icon.icon_source:
            name = icon.icon_source.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            kind = _kind_of_marker(name)
            if kind is not None:
                weak.add(kind)

    if len(strong) == 1:
        return strong.pop(), True
    if strong:
        # Contradicción entre señales fuertes: no se elige ninguna.
        return None, True
    if len(weak) == 1:
        return weak.pop(), False
    return None, False


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


# Campos que solo separan una etiqueta de su valor y no son el valor.
_SEPARATOR_FIELDS = frozenset({":", "-", "=", "|", "."})


def _is_metadata_line(line: _LogicalLine) -> bool:
    """Indica si el renglón lleva un rótulo de cabecera.

    Sirve para no contar una línea de metadatos como un registro que no se
    supo interpretar: no es un renglón de BOM fallido, es otra cosa.
    """
    for field in line.fields:
        label = _label_key(field.partition(":")[0])
        if label is None:
            continue
        for synonyms in _LINE_LABELS.values():
            if any(label == _label_key(synonym) for synonym in synonyms):
                return True
    return False


def _line_metadata(lines: Sequence[_LogicalLine]) -> tuple[dict[str, str], int]:
    """Busca los campos de cabecera entre los renglones del export.

    Etiqueta y valor pueden estar en el mismo fragmento
    (``Ubic.técn.  LOC-1``), en fragmentos distintos
    (``<nobr>Ubic.técn.</nobr><nobr>LOC-1</nobr>``) o separados por un
    fragmento de puntuación (``<nobr>:</nobr>``). Al trabajar sobre los campos
    del renglón ya reunido, las tres formas se leen igual.

    Devuelve también cuántas etiquetas se reconocieron, para el diagnóstico.
    """
    found: dict[str, str] = {}
    detected = 0
    for line in lines:
        fields = line.fields
        for position, field in enumerate(fields):
            label_part, _, inline_value = field.partition(":")
            label = _label_key(label_part)
            if label is None:
                continue
            for name, synonyms in _LINE_LABELS.items():
                if not any(label == _label_key(synonym) for synonym in synonyms):
                    continue
                detected += 1
                if name in found:
                    continue
                value = normalize_text(inline_value)
                if value is None:
                    # El valor puede estar uno o más fragmentos más allá, con
                    # un separador suelto en medio.
                    for candidate in fields[position + 1 :]:
                        text = normalize_text(candidate)
                        if text is None or text in _SEPARATOR_FIELDS:
                            continue
                        value = text
                        break
                if value is not None:
                    found[name] = value
    return found, detected


def _header_meaning(line: _LogicalLine) -> list[str | None] | None:
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
    lines: Sequence[_LogicalLine], metadata: dict[str, str], diagnostics: dict[str, int]
) -> tuple[list[ParsedSapItem], list[IngestionWarning]]:
    """Interpreta un export sin tablas como renglones de BOM.

    Se busca primero una fila de rótulos; si existe, manda ella y los campos
    del renglón se leen por su posición. Si no existe, cada renglón se
    interpreta por su forma. El tipo lo decide el icono cuando lo declara.
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
    contradictory = 0
    unresolved_parent = 0
    # Cadena de padres por nivel, para poder decir de qué cuelga cada renglón.
    parents: dict[int, str] = {}
    indents: list[int] = []

    for line in lines:
        if line.number <= header_number or line.is_blank:
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

        entry_kind, strong = _type_from_icons(line.icons)
        if entry_kind == "material":
            diagnostics["icon_material_signals"] += 1
        elif entry_kind == "equipment":
            diagnostics["icon_equipment_signals"] += 1
        elif strong:
            # Iconos fuertes que se contradicen: no se elige ninguno.
            contradictory += 1

        if entry_kind is None and not strong and code is not None:
            # Sin icono utilizable decide la evidencia estructural: en una
            # lista de BOM solo los materiales llevan cantidad y unidad; un
            # objeto técnico aparece sin ellas.
            if quantity_text is not None and unit is not None:
                entry_kind = "material"
            elif description is not None:
                entry_kind = "equipment"

        if code is not None or description is not None:
            diagnostics["candidate_records"] += 1

        if entry_kind is None or code is None:
            # Puede ser un título, una línea de separación o un renglón cuya
            # estructura no se reconoce. No se inventa nada; se cuenta. Una
            # línea de cabecera no cuenta: no es un renglón de BOM fallido.
            if not _is_metadata_line(line) and (
                code is not None or (description is not None and len(fields) > 2)
            ):
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
        elif depth > 0:
            # El renglón es válido aunque su padre no pueda probarse. No se
            # descarta y tampoco se le inventa una relación.
            unresolved_parent += 1
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

    diagnostics["parsed_material_records"] = sum(
        1 for item in items if item.entry_kind == "material"
    )
    diagnostics["parsed_equipment_records"] = sum(
        1 for item in items if item.entry_kind == "equipment"
    )
    diagnostics["unresolved_records"] = unrecognised + contradictory

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
    if contradictory:
        warnings.append(
            IngestionWarning(
                code="contradictory_type_icons",
                message=(
                    "Some lines carry icons that declare conflicting types. The type is "
                    "left undecided rather than chosen."
                ),
                location=f"{contradictory} line(s)",
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
    if unresolved_parent:
        warnings.append(
            IngestionWarning(
                code="unresolved_hierarchy",
                message=(
                    "Some records are indented below a parent that could not be identified. "
                    "The record is kept; the relation is not invented."
                ),
                location=f"{unresolved_parent} record(s)",
            )
        )
    return items, warnings


def parse_sap_snapshot(data: bytes) -> ParsedSapSnapshot:
    """Interpreta el HTM exportado de SAP.

    Intenta primero leerlo como tabla y, si no produce ningún renglón, lo
    interpreta como líneas lógicas. Lanza
    :class:`~elsa.ingestion.errors.UnrecognizedFormatError` si ninguna de las
    dos rutas reconoce nada; la excepción lleva el diagnóstico estructural,
    para poder saber **en qué etapa** falló sin ver el contenido.
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

    metadata, labels_detected = _line_metadata(reader.lines)
    # Lo que diga una tabla de cabecera manda, por ser la forma más
    # estructurada de las dos.
    metadata = {**metadata, **_extract_metadata(tables.tables)}

    # Conteos, nunca contenido: ninguno de estos números revela un código, una
    # descripción ni una ubicación.
    diagnostics: dict[str, int] = {
        "nobr_fragments_seen": reader.nobr_fragments,
        "br_boundaries_seen": reader.br_boundaries,
        "logical_lines_built": len(reader.lines),
        "html_tables_seen": len(tables.tables),
        "metadata_labels_detected": labels_detected,
        "icon_material_signals": 0,
        "icon_equipment_signals": 0,
        "candidate_records": 0,
        "parsed_material_records": 0,
        "parsed_equipment_records": 0,
        "unresolved_records": 0,
    }

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

    items = _items_from_tables(tables.tables, metadata)
    if items:
        diagnostics["parsed_material_records"] = sum(
            1 for item in items if item.entry_kind == "material"
        )
        diagnostics["parsed_equipment_records"] = sum(
            1 for item in items if item.entry_kind == "equipment"
        )
        diagnostics["candidate_records"] = len(items)
    else:
        items, line_warnings = _items_from_lines(reader.lines, metadata, diagnostics)
        warnings.extend(line_warnings)

    if not items:
        raise UnrecognizedFormatError(
            "no recognisable SAP BOM records were found, neither as a table nor as a "
            "monospaced list; the export format is not understood",
            diagnostics=diagnostics,
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

    _logger.info("sap snapshot parsed", extra=dict(diagnostics))
    return ParsedSapSnapshot(
        functional_location=metadata.get("functional_location"),
        description=metadata.get("description"),
        valid_from=_parse_date(metadata.get("valid_from")),
        items=tuple(items),
        warnings=tuple(warnings),
        diagnostics=diagnostics,
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
