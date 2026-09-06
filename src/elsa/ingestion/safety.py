"""Validación de seguridad del paquete XLSX, previa a interpretarlo.

Un ``.xlsx`` es un ZIP. Aceptarlo por su extensión y entregárselo a una
librería es confiar en que el archivo es lo que dice ser. Este módulo revisa
la estructura **antes** de que ningún parser lea contenido, y rechaza lo que
no encaje.

Qué se comprueba y por qué:

- **Tamaño.** Un límite explícito, aplicado sobre los bytes recibidos.
- **Firma real.** Los primeros bytes tienen que ser los de un ZIP; la
  extensión no cuenta como prueba de nada.
- **Rutas internas.** Una entrada absoluta, con ``..`` o con separadores del
  sistema podría escribir fuera del destino si alguien extrajera el paquete.
  Aquí no se extrae nada al disco, pero se rechaza igual: la validación no
  debe depender de que el resto del código siga siendo prudente.
- **Expansión.** Un ZIP de pocos kilobytes puede declarar gigabytes. Se
  limita el total descomprimido y la relación de compresión por entrada.
- **Macros.** ``xl/vbaProject.bin`` es un libro con macros. Este bloque
  acepta ``.xlsx``; un ``.xlsm`` renombrado se rechaza por su contenido, no
  por su nombre.
- **Forma OpenXML.** Sin ``[Content_Types].xml`` y sin ``xl/workbook.xml``
  no es un libro de Excel.

Enlaces externos y conexiones de datos **no se rechazan pero tampoco se
siguen**: se avisa de su presencia y el parser abre el libro descartándolos.
Nada en esta ingesta hace una petición de red inducida por el archivo.
"""

import zipfile
from dataclasses import dataclass
from io import BytesIO

from elsa.ingestion.errors import (
    ArchiveTooLargeError,
    FileTooLargeError,
    MacroEnabledWorkbookError,
    NotAnOpenXmlFileError,
    UnsafeArchiveEntryError,
)
from elsa.ingestion.model import IngestionWarning

__all__ = ["ArchiveLimits", "XlsxInspection", "inspect_xlsx"]

_ZIP_MAGIC = b"PK\x03\x04"

_CONTENT_TYPES_ENTRY = "[Content_Types].xml"
_WORKBOOK_ENTRY = "xl/workbook.xml"
_VBA_ENTRY = "xl/vbaProject.bin"

# Prefijos legítimos de un paquete OpenXML. Cualquier otro se avisa: no
# convierte el archivo en peligroso, pero sí en inesperado.
_EXPECTED_PREFIXES = ("_rels/", "docProps/", "xl/", "customXml/")

# Extensiones que no tienen ninguna razón para viajar dentro de un libro.
_FORBIDDEN_SUFFIXES = (".exe", ".dll", ".bat", ".cmd", ".com", ".js", ".vbs", ".ps1", ".sh")

_EXTERNAL_LINK_PREFIX = "xl/externalLinks/"
_CONNECTIONS_ENTRY = "xl/connections.xml"


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    """Límites aplicados al paquete. Configurables por ambiente."""

    max_bytes: int = 25 * 1024 * 1024
    max_uncompressed_bytes: int = 200 * 1024 * 1024
    max_entries: int = 5_000
    max_compression_ratio: int = 200
    """Relación máxima descomprimido/comprimido de una entrada.

    El XML de una hoja comprime muchísimo, así que el umbral es alto a
    propósito: sirve para detectar una bomba, no para juzgar un archivo
    grande y legítimo.
    """


@dataclass(frozen=True, slots=True)
class XlsxInspection:
    """Resultado de revisar el paquete."""

    entry_names: tuple[str, ...]
    uncompressed_bytes: int
    warnings: tuple[IngestionWarning, ...]

    @property
    def has_external_links(self) -> bool:
        return any(name.startswith(_EXTERNAL_LINK_PREFIX) for name in self.entry_names)


def _reject_unsafe_name(name: str) -> None:
    """Rechaza una ruta interna que no debería existir en un paquete."""
    if not name or name.startswith("/") or "\\" in name or "\x00" in name:
        raise UnsafeArchiveEntryError("the package contains an entry with an unsafe path")
    if any(part in ("..", ".") for part in name.split("/")):
        raise UnsafeArchiveEntryError("the package contains a path traversal entry")
    # Una ruta absoluta de Windows (`C:\...`) ya cae por el separador, pero
    # `C:/...` no, y también apunta fuera del paquete.
    if len(name) > 1 and name[1] == ":":
        raise UnsafeArchiveEntryError("the package contains an absolute path entry")
    if name.lower().endswith(_FORBIDDEN_SUFFIXES):
        raise UnsafeArchiveEntryError("the package contains an executable entry")


def inspect_xlsx(data: bytes, limits: ArchiveLimits | None = None) -> XlsxInspection:
    """Revisa el paquete y devuelve lo que se sabe de él sin interpretarlo.

    Lanza una subclase de
    :class:`~elsa.ingestion.errors.FileRejectedError` si el archivo no puede
    aceptarse. No lee ninguna celda ni descomprime al disco.
    """
    limits = limits or ArchiveLimits()

    if len(data) > limits.max_bytes:
        raise FileTooLargeError(
            f"the file exceeds the maximum accepted size of {limits.max_bytes} bytes"
        )
    if not data:
        raise NotAnOpenXmlFileError("the file is empty")
    if not data.startswith(_ZIP_MAGIC):
        # Cubre a la vez la extensión falsa y el archivo truncado por el
        # principio: en ambos casos no es un paquete OpenXML.
        raise NotAnOpenXmlFileError("the file is not an OpenXML package")

    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
    except zipfile.BadZipFile:
        # Un ZIP truncado o corrupto llega hasta aquí: la firma estaba bien
        # pero el directorio central no.
        raise NotAnOpenXmlFileError("the file is not a readable ZIP package") from None

    if len(infos) > limits.max_entries:
        raise ArchiveTooLargeError(f"the package declares more than {limits.max_entries} entries")

    total_uncompressed = 0
    names: list[str] = []
    for info in infos:
        _reject_unsafe_name(info.filename)
        names.append(info.filename)
        total_uncompressed += info.file_size
        if total_uncompressed > limits.max_uncompressed_bytes:
            raise ArchiveTooLargeError("the package expands beyond the maximum accepted size")
        if info.compress_size > 0:
            ratio = info.file_size // info.compress_size
            if ratio > limits.max_compression_ratio:
                raise ArchiveTooLargeError(
                    "the package contains an entry with an implausible compression ratio"
                )

    entry_names = tuple(names)

    if _VBA_ENTRY in entry_names:
        raise MacroEnabledWorkbookError(
            "the workbook contains macros; this block only accepts .xlsx files"
        )
    if _CONTENT_TYPES_ENTRY not in entry_names or _WORKBOOK_ENTRY not in entry_names:
        raise NotAnOpenXmlFileError("the package is not an Excel workbook")

    warnings: list[IngestionWarning] = []
    if any(name.startswith(_EXTERNAL_LINK_PREFIX) for name in entry_names):
        warnings.append(
            IngestionWarning(
                code="external_links_present",
                message=(
                    "The workbook declares external links. They are recorded but never "
                    "resolved: no request is made to any address the file mentions."
                ),
            )
        )
    if _CONNECTIONS_ENTRY in entry_names:
        warnings.append(
            IngestionWarning(
                code="external_connections_present",
                message=(
                    "The workbook declares external data connections. They are neither "
                    "opened nor refreshed."
                ),
            )
        )
    unexpected = sorted(
        {
            name.split("/", 1)[0]
            for name in entry_names
            if name != _CONTENT_TYPES_ENTRY and not name.startswith(_EXPECTED_PREFIXES)
        }
    )
    if unexpected:
        warnings.append(
            IngestionWarning(
                code="unexpected_package_entries",
                message=(
                    "The package contains entries outside the usual OpenXML layout. "
                    "They are not read."
                ),
                location=", ".join(unexpected[:5]),
            )
        )

    return XlsxInspection(
        entry_names=entry_names,
        uncompressed_bytes=total_uncompressed,
        warnings=tuple(warnings),
    )
