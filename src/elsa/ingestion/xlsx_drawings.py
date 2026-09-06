"""Extracción de las imágenes embebidas en un libro de Excel.

Las imágenes se leen **directamente del paquete OpenXML**, sin pasar por
ninguna librería de imágenes. La razón es deliberada: en este bloque el
plano es evidencia que se conserva, no información que se interpreta. No hay
OCR, no hay visión artificial y no hay decodificación del contenido gráfico.
Lo único que se hace con los bytes es guardarlos y calcular su hash.

Las dimensiones, cuando se declaran, se leen de la cabecera del formato
(PNG, JPEG, GIF, BMP). Si el formato no permite verificarlas sin decodificar
la imagen, quedan en ``None``: un tamaño inventado sería un dato falso sobre
un plano.

Para saber en qué hoja está cada imagen se recorre la cadena de relaciones
del paquete::

    workbook.xml → hoja → drawingN.xml → media/imageN.png

Si esa cadena no puede seguirse, la imagen se conserva igualmente sin hoja
asociada: perder la evidencia sería peor que no saber dónde estaba.
"""

import posixpath
import zipfile
from dataclasses import dataclass
from io import BytesIO

from defusedxml.ElementTree import fromstring
from openpyxl.utils import get_column_letter

__all__ = ["EmbeddedImage", "extract_embedded_images", "image_dimensions"]

_NS_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_XDR = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
_NS_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_R_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"

_CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".emf": "image/emf",
    ".wmf": "image/wmf",
    ".svg": "image/svg+xml",
}


@dataclass(frozen=True, slots=True)
class EmbeddedImage:
    """Una imagen del paquete, con lo que se sabe de su procedencia."""

    entry_name: str
    content: bytes
    content_type: str
    sheet_name: str | None
    anchor: str | None
    width_px: int | None
    height_px: int | None


# ---------------------------------------------------------------------
# Dimensiones sin decodificar la imagen
# ---------------------------------------------------------------------


def image_dimensions(data: bytes) -> tuple[int | None, int | None]:
    """Ancho y alto en píxeles leídos de la cabecera, o ``(None, None)``.

    Solo se interpretan los campos de cabecera que los formatos declaran de
    forma explícita. No se decodifica ningún píxel.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24 and data[12:16] == b"IHDR":
        return (
            int.from_bytes(data[16:20], "big"),
            int.from_bytes(data[20:24], "big"),
        )
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        if len(data) >= 10:
            return (
                int.from_bytes(data[6:8], "little"),
                int.from_bytes(data[8:10], "little"),
            )
        return (None, None)
    if data.startswith(b"BM") and len(data) >= 26:
        return (
            int.from_bytes(data[18:22], "little", signed=True),
            abs(int.from_bytes(data[22:26], "little", signed=True)),
        )
    if data.startswith(b"\xff\xd8"):
        return _jpeg_dimensions(data)
    return (None, None)


# Marcadores JPEG "Start Of Frame". Los excluidos (`\xc4`, `\xc8`, `\xcc`) no
# describen el tamaño del cuadro aunque caigan en el mismo rango.
_JPEG_SOF_MARKERS = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def _jpeg_dimensions(data: bytes) -> tuple[int | None, int | None]:
    """Recorre los segmentos JPEG hasta el que declara el tamaño."""
    offset = 2
    size = len(data)
    while offset + 3 < size:
        if data[offset] != 0xFF:
            return (None, None)
        marker = data[offset + 1]
        # Marcadores sin carga útil.
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        segment_length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        if segment_length < 2:
            return (None, None)
        if marker in _JPEG_SOF_MARKERS:
            if offset + 9 > size:
                return (None, None)
            return (
                int.from_bytes(data[offset + 7 : offset + 9], "big"),
                int.from_bytes(data[offset + 5 : offset + 7], "big"),
            )
        offset += 2 + segment_length
    return (None, None)


# ---------------------------------------------------------------------
# Relaciones del paquete
# ---------------------------------------------------------------------


def _read_relationships(archive: zipfile.ZipFile, part_name: str) -> dict[str, str]:
    """Mapa ``rId`` → ruta absoluta dentro del paquete, para una parte dada."""
    directory, filename = posixpath.split(part_name)
    rels_name = posixpath.join(directory, "_rels", f"{filename}.rels")
    try:
        raw = archive.read(rels_name)
    except KeyError:
        return {}
    try:
        root = fromstring(raw)
    except Exception:  # noqa: BLE001 - un .rels ilegible no debe abortar la ingesta
        return {}

    relationships: dict[str, str] = {}
    for element in root.iter(f"{_NS_REL}Relationship"):
        identifier = element.get("Id")
        target = element.get("Target")
        if identifier is None or target is None:
            continue
        # `External` apunta fuera del paquete. Se ignora sin excepción: nunca
        # se sigue un enlace que traiga el archivo.
        if (element.get("TargetMode") or "").lower() == "external":
            continue
        relationships[identifier] = _resolve_target(directory, target)
    return relationships


def _resolve_target(directory: str, target: str) -> str:
    """Resuelve el destino de una relación a una entrada del paquete.

    OPC admite las dos formas y Excel usa ambas según la parte: relativa a la
    parte que declara la relación (``../media/image1.png``) y absoluta
    respecto de la raíz del paquete (``/xl/worksheets/sheet1.xml``). Una
    barra inicial significa «desde la raíz», no «desde el sistema de
    archivos», así que unirla al directorio la borraría en silencio y la
    parte no se encontraría.
    """
    if target.startswith("/"):
        return posixpath.normpath(target).lstrip("/")
    return posixpath.normpath(posixpath.join(directory, target))


def _sheet_parts(archive: zipfile.ZipFile) -> dict[str, str]:
    """Mapa nombre de hoja → ruta de su XML."""
    try:
        root = fromstring(archive.read("xl/workbook.xml"))
    except (KeyError, Exception):  # noqa: B014 - cualquier fallo aquí solo pierde el nombre de hoja
        return {}
    relationships = _read_relationships(archive, "xl/workbook.xml")
    sheets: dict[str, str] = {}
    for element in root.iter(f"{_NS_MAIN}sheet"):
        name = element.get("name")
        target = relationships.get(element.get(_R_ID) or "")
        if name and target:
            sheets[name] = target
    return sheets


def _anchor_label(anchor_element: object) -> str | None:
    """Celda superior izquierda del anclaje, en notación ``B12``."""
    element = anchor_element
    from_element = element.find(f"{_NS_XDR}from")  # type: ignore[attr-defined]
    if from_element is None:
        return None
    column = from_element.findtext(f"{_NS_XDR}col")
    row = from_element.findtext(f"{_NS_XDR}row")
    if column is None or row is None:
        return None
    try:
        # El paquete cuenta filas y columnas desde cero.
        return f"{get_column_letter(int(column) + 1)}{int(row) + 1}"
    except (ValueError, TypeError):
        return None


def extract_embedded_images(data: bytes) -> tuple[EmbeddedImage, ...]:
    """Devuelve todas las imágenes embebidas del libro.

    El paquete ya debe haber pasado por
    :func:`~elsa.ingestion.safety.inspect_xlsx`: aquí se asume que las rutas
    internas son seguras.
    """
    images: list[EmbeddedImage] = []
    with zipfile.ZipFile(BytesIO(data)) as archive:
        entry_names = set(archive.namelist())
        media_entries = sorted(name for name in entry_names if name.startswith("xl/media/"))
        if not media_entries:
            return ()

        # Procedencia: media → (hoja, anclaje). Lo que no se pueda resolver
        # queda sin hoja, pero la imagen se conserva igual.
        provenance: dict[str, tuple[str | None, str | None]] = {}
        for source_sheet, sheet_part in _sheet_parts(archive).items():
            for drawing_part in _read_relationships(archive, sheet_part).values():
                if not drawing_part.startswith("xl/drawings/"):
                    continue
                drawing_rels = _read_relationships(archive, drawing_part)
                try:
                    drawing_root = fromstring(archive.read(drawing_part))
                except (KeyError, Exception):  # noqa: B014
                    continue
                for anchor in drawing_root:
                    blip = anchor.find(f".//{_NS_A}blip")
                    if blip is None:
                        continue
                    target = drawing_rels.get(blip.get(_R_EMBED) or "")
                    if target is not None:
                        provenance[target] = (source_sheet, _anchor_label(anchor))

        for entry_name in media_entries:
            content = archive.read(entry_name)
            if not content:
                continue
            suffix = posixpath.splitext(entry_name)[1].lower()
            sheet_name, anchor = provenance.get(entry_name, (None, None))
            width, height = image_dimensions(content)
            images.append(
                EmbeddedImage(
                    entry_name=entry_name,
                    content=content,
                    content_type=_CONTENT_TYPES.get(suffix, "application/octet-stream"),
                    sheet_name=sheet_name,
                    anchor=anchor,
                    width_px=width,
                    height_px=height,
                )
            )
    return tuple(images)
