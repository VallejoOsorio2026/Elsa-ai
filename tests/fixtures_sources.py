"""Fuentes sintéticas compartidas por los tests de API.

Todo es inventado: ni los códigos, ni los subsistemas, ni las ubicaciones
técnicas corresponden a ningún equipo real de PAPELSA.
"""

from typing import Any

from tests.fixtures_xlsx import BOM_HEADERS, build_workbook, with_embedded_image

AMEF_HEADERS = [
    "Subsistema",
    "Componente",
    "Código SAP",
    "Modo de falla",
    "Efecto",
    "Causa",
    "S",
    "O",
    "D",
    "NPR",
    "Acción a tomar",
    "Plan preventivo",
    "Acción correctiva",
    "Observaciones",
]


def bom_row(
    position: str,
    subsystem: str,
    component: str,
    sap_code: str | None,
    quantity: Any,
    drawing: str = "PL-001",
    reference: str = "R-01",
    model: str = "MOD-A",
) -> list[Any]:
    return [
        position,
        subsystem,
        component,
        sap_code,
        f"Descripcion de {component}",
        quantity,
        "UN",
        model,
        drawing,
        reference,
        "Si",
        "Critico",
        4,
        1,
        3,
        "",
    ]


def engineering_workbook(rows: list[list[Any]] | None = None, *, with_image: bool = True) -> bytes:
    """Libro de Ingeniería completo y sintético."""
    sheets: dict[str, list[list[Any]]] = {
        "BOM": [
            BOM_HEADERS,
            *(
                rows
                if rows is not None
                else [
                    bom_row("1", "Accionamiento", "Rodamiento ficticio", "10000001", 2),
                    bom_row("2", "Accionamiento", "Sello sin codigo", None, 1, reference="R-02"),
                    bom_row(
                        "3",
                        "Bastidor",
                        "Tornillo ficticio",
                        "10000002",
                        10,
                        drawing="PL-002",
                        reference="R-03",
                        model="MOD-C",
                    ),
                ]
            ),
        ],
        "Plano Despiece": [["Plano", "PL-002"]],
        "AMEF": [
            AMEF_HEADERS,
            [
                "Accionamiento",
                "Rodamiento ficticio",
                "10000001",
                "Desgaste",
                "Vibracion",
                "Falta de lubricacion",
                7,
                3,
                4,
                999,
                "Lubricar",
                "Mensual",
                "Cambiar",
                "",
            ],
        ],
        "Valoración SOD": [
            ["Severidad"],
            ["Valor", "Criterio"],
            [1, "Sin efecto"],
            [10, "Catastrofico"],
        ],
    }
    workbook = build_workbook(sheets)
    if with_image:
        workbook = with_embedded_image(workbook, sheet_name="Plano Despiece")
    return workbook


SAP_EXPORT = """<html><head><meta charset="utf-8"></head><body>
<table><tr><td>Ubicaci&oacute;n t&eacute;cnica</td><td>MB-FICTICIA-01</td></tr>
<tr><td>Denominaci&oacute;n</td><td>Activo de prueba</td></tr>
<tr><td>V&aacute;lido de</td><td>15.03.2026</td></tr></table>
<table><tr><th>Pos.</th><th>Material</th><th>Denominaci&oacute;n</th><th>Ctd.</th>
    <th>U.M.</th></tr>
<tr><td>0010</td><td>000000000010000001</td><td>Rodamiento ficticio</td><td>3</td>
    <td>UN</td></tr>
<tr><td>0020</td><td>10000099</td><td>Pieza solo en SAP</td><td>1</td><td>UN</td></tr></table>
<table><tr><th>Equipo</th><th>Denominaci&oacute;n</th></tr>
<tr><td>EQ-0001</td><td>Reductor ficticio</td></tr></table>
</body></html>"""


def sap_export(text: str | None = None) -> bytes:
    return (text if text is not None else SAP_EXPORT).encode("utf-8")
