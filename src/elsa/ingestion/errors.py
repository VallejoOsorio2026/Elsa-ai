"""Errores de la ingesta, clasificados por naturaleza.

La clasificación no es decorativa: un administrador necesita distinguir «el
archivo que subiste no es un XLSX» de «el disco no responde», y la API
necesita devolver códigos distintos. Por eso cada error declara su
``kind``, que se guarda en ``elsa.imports.failure_kind`` y decide el estado
HTTP.

Ningún mensaje de estos errores contiene contenido técnico del archivo: se
muestran a quien subió el archivo y acaban en logs. Dicen qué está mal, no
qué decía la celda.
"""

from collections.abc import Mapping

__all__ = [
    "AmbiguousDataError",
    "ArchiveTooLargeError",
    "FileRejectedError",
    "IngestionError",
    "MacroEnabledWorkbookError",
    "MissingSheetError",
    "NotAnOpenXmlFileError",
    "ParseError",
    "UnrecognizedFormatError",
    "UnsafeArchiveEntryError",
]


class IngestionError(Exception):
    """Fallo durante la ingesta de una fuente.

    ``kind`` coincide con ``elsa.imports.failure_kind``.

    ``diagnostics`` lleva conteos estructurales de la etapa en la que se
    falló —cuántos fragmentos se vieron, cuántos renglones se construyeron,
    cuántos candidatos hubo—. Sirve para diagnosticar un archivo que no se
    puede compartir: son números, nunca contenido.
    """

    kind = "parse"

    def __init__(self, *args: object, diagnostics: Mapping[str, int] | None = None) -> None:
        super().__init__(*args)
        self.diagnostics: Mapping[str, int] = dict(diagnostics or {})


class FileRejectedError(IngestionError):
    """El archivo se rechaza antes de interpretarlo: forma, tamaño o estructura."""

    kind = "file"


class ParseError(IngestionError):
    """El archivo es aceptable pero su contenido no se puede interpretar."""

    kind = "parse"


class AmbiguousDataError(IngestionError):
    """El contenido admite más de una lectura y no se elige ninguna.

    Resolver una ambigüedad por cuenta propia sería inventar un hecho
    técnico; se detiene y se deja a revisión humana.
    """

    kind = "ambiguity"


# --- Rechazos concretos de archivo -----------------------------------


class FileTooLargeError(FileRejectedError):
    """El archivo supera el tamaño máximo aceptado."""


class NotAnOpenXmlFileError(FileRejectedError):
    """No es un paquete OpenXML válido, diga lo que diga su extensión."""


class MacroEnabledWorkbookError(FileRejectedError):
    """El libro contiene macros. Este bloque acepta ``.xlsx``, nunca ``.xlsm``."""


class UnsafeArchiveEntryError(FileRejectedError):
    """El paquete contiene una entrada con ruta o tipo inaceptable."""


class ArchiveTooLargeError(FileRejectedError):
    """El paquete se expande por encima del límite (bomba de descompresión)."""


# --- Fallos de interpretación ----------------------------------------


class MissingSheetError(ParseError):
    """Falta una hoja imprescindible para interpretar la fuente."""


class UnrecognizedFormatError(ParseError):
    """No se reconoce la estructura con confianza suficiente.

    Se prefiere fallar aquí, conservando el original, a publicar una
    interpretación dudosa.
    """
