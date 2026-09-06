"""Export de SAP en su forma fragmentada, construido pieza a pieza.

Reproduce la **forma estructural** del export real y nada de su contenido:
todos los identificadores, descripciones y ubicaciones son inventados y se
reconocen a simple vista como tales (`MAT-FAKE-001`, `LOC-FAKE-001`).

La forma que reproduce, y que es lo que el parser tiene que soportar:

- ningún ``<table>``;
- un registro repartido en **varios** ``<nobr>``;
- ``<br>`` como frontera del registro;
- ``&nbsp;`` en abundancia, incluida la indentación;
- iconos ``<img>`` intercalados entre fragmentos;
- etiqueta y valor de metadata en fragmentos distintos;
- identificadores HTML arbitrarios que no significan nada.
"""

from typing import Any

__all__ = [
    "EQUIPMENT_CODE",
    "FRAGMENTED_EXPORT",
    "LOCATION",
    "MATERIAL_CODES",
    "build_export",
    "equipment_line",
    "material_line",
    "metadata_lines",
]

LOCATION = "LOC-FAKE-001"
EQUIPMENT_CODE = "EQ-FAKE-001"
MATERIAL_CODES = ("MAT-FAKE-001", "MAT-FAKE-002")

# Espacio duro, tal como lo emite SAP.
NBSP = "&nbsp;"


def _indent(width: int) -> str:
    """Sangría hecha con espacio duro, como en el archivo real."""
    return f'<nobr id="i{width}">{NBSP * width}</nobr>'


def metadata_lines(
    *,
    location: str = LOCATION,
    description: str = "Conjunto ficticio",
    valid_from: str = "01.01.2026",
) -> str:
    """Cabecera con etiqueta y valor en fragmentos separados."""
    return (
        f'<nobr id="m1">Ubic.t&eacute;cn.</nobr><nobr id="m2">:</nobr>'
        f'<nobr id="m3">{location}</nobr><br>\n'
        f'<nobr id="m4">Denominaci&oacute;n</nobr>'
        f'<nobr id="m5">{NBSP * 2}{description}</nobr><br>\n'
        f'<nobr id="m6">V&aacute;lido de</nobr><nobr id="m7">{NBSP * 2}{valid_from}</nobr><br>\n'
    )


def equipment_line(
    code: str = EQUIPMENT_CODE,
    description: str = "Subconjunto ficticio",
    *,
    indent: int = 2,
    icon_attribute: str = "title",
    icon_value: str = "Equipo",
) -> str:
    """Un equipo hijo: icono entre fragmentos, sin cantidad ni unidad."""
    return (
        f"{_indent(indent)}"
        f'<img src="/sap/public/icono-ficticio-a.gif" {icon_attribute}="{icon_value}">'
        f'<nobr id="e1">{code}</nobr>'
        f'<nobr id="e2">{NBSP * 2}{description}</nobr><br>\n'
    )


def material_line(
    code: str,
    description: str,
    quantity: str,
    unit: str,
    *,
    indent: int = 4,
    icon_attribute: str = "title",
    icon_value: str = "Material",
) -> str:
    """Un material con **cada campo en su propio fragmento**."""
    return (
        f"{_indent(indent)}"
        f'<img src="/sap/public/icono-ficticio-b.gif" {icon_attribute}="{icon_value}">'
        f'<nobr id="f1">{code}</nobr>'
        f'<nobr id="f2">{NBSP * 2}{description}</nobr>'
        f'<nobr id="f3">{NBSP * 2}{quantity}</nobr>'
        f'<nobr id="f4">{NBSP * 2}{unit}</nobr><br>\n'
    )


def build_export(body: str, *, head: str = "", charset: str = "utf-8") -> bytes:
    """Envuelve el cuerpo en un documento completo."""
    document = (
        f'<html><head><meta charset="{charset}">{head}</head><body>'
        f'<font face="Courier New" size="2">\n{body}</font></body></html>'
    )
    return document.encode(charset)


def _default_body() -> str:
    return (
        metadata_lines()
        + f'<nobr id="blank">{NBSP}</nobr><br>\n'
        + equipment_line()
        + material_line(MATERIAL_CODES[0], "Repuesto ficticio A", "2", "UN")
        + material_line(MATERIAL_CODES[1], "Repuesto ficticio B", "10", "KG")
    )


FRAGMENTED_EXPORT: bytes = build_export(_default_body())


def export_with(**overrides: Any) -> bytes:
    """Export por defecto con el cuerpo sustituido."""
    body: str = overrides.get("body") or _default_body()
    return build_export(body)
