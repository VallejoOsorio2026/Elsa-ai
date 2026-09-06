"""Lectura del XLSX aprobado por Ingeniería.

Todos los datos de estos fixtures son inventados: ni los códigos, ni los
subsistemas, ni las descripciones corresponden a ningún equipo real.
"""

from decimal import Decimal
from typing import Any

import pytest

from elsa.ingestion.engineering_xlsx import parse_engineering_workbook
from elsa.ingestion.errors import MissingSheetError
from elsa.ingestion.model import ParsedEngineeringBom
from tests.fixtures_xlsx import BOM_HEADERS, build_workbook, minimal_png, with_embedded_image

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


def _sheets() -> dict[str, list[list[Any]]]:
    return {
        "BOM": [
            ["Lista de materiales aprobada"],
            [],
            BOM_HEADERS,
            [
                "1",
                "Accionamiento",
                "Rodamiento ficticio",
                "10000001",
                "Rodamiento de prueba",
                2,
                "UN",
                "MOD-A",
                "PL-001",
                "R-01",
                "Si",
                "Critico",
                4,
                1,
                3,
                "nota",
            ],
            [
                "2",
                "Accionamiento",
                "Sello sin codigo",
                None,
                "Sello de prueba",
                "1,5",
                "UN",
                "MOD-B",
                "PL-001",
                "R-02",
                "No",
                "Normal",
                2,
                0,
                1,
                "",
            ],
            [
                "3",
                "Bastidor",
                "Tornillo ficticio",
                "10000002",
                "Tornillo",
                "=1+1",
                "UN",
                "MOD-C",
                "PL-002",
                "R-03",
                "Si",
                "Normal",
                10,
                2,
                5,
                "",
            ],
        ],
        "Plano Despiece": [["Plano", "PL-002"]],
        "Tablas de Opciones (BOM)": [
            ["Estrategia de inventario", "Actualizar BOM"],
            ["Critico", "Si"],
            ["Normal", "No"],
        ],
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
            ["Valor", "Criterio", "Desde", "Hasta"],
            [1, "Sin efecto", 0, 1],
            [10, "Catastrofico", 9, 10],
            ["Ocurrencia"],
            ["Valor", "Criterio"],
            [1, "Remota"],
            ["Detección"],
            ["Valor", "Criterio"],
            [10, "Nula"],
        ],
    }


@pytest.fixture
def parsed() -> ParsedEngineeringBom:
    workbook = with_embedded_image(
        build_workbook(_sheets()), sheet_name="Plano Despiece", image=minimal_png(9, 4)
    )
    return parse_engineering_workbook(workbook)


def test_every_expected_sheet_is_detected(parsed: ParsedEngineeringBom) -> None:
    assert "BOM" in parsed.sheets_detected
    assert "AMEF" in parsed.sheets_detected
    assert "Valoración SOD" in parsed.sheets_detected


def test_bom_rows_are_read_past_the_title_rows(parsed: ParsedEngineeringBom) -> None:
    """La fila de encabezados se busca; no se asume que sea la primera."""
    assert len(parsed.bom_rows) == 3
    assert parsed.bom_rows[0].component_name == "Rodamiento ficticio"
    assert parsed.bom_rows[0].source_row == 4


def test_a_component_without_a_sap_code_is_kept(parsed: ParsedEngineeringBom) -> None:
    """No tener código SAP no lo hace menos real ni menos necesario."""
    row = parsed.bom_rows[1]

    assert row.sap_code is None
    assert row.component_name == "Sello sin codigo"
    assert row.quantity == Decimal("1.5")


def test_drawing_and_reference_are_preserved(parsed: ParsedEngineeringBom) -> None:
    assert parsed.bom_rows[0].assembly_drawing == "PL-001"
    assert parsed.bom_rows[0].drawing_reference == "R-01"


def test_a_formula_is_never_evaluated(parsed: ParsedEngineeringBom) -> None:
    """Se conserva tal cual y se deja sin valor numérico."""
    row = parsed.bom_rows[2]

    assert row.quantity is None
    assert row.quantity_original == "=1+1"
    assert "formula_not_evaluated" in {warning.code for warning in parsed.warnings}


def test_inventory_columns_are_preserved_as_source_data(parsed: ParsedEngineeringBom) -> None:
    """Son el stock de esa fuente en esa fecha, no el stock actual de SAP."""
    row = parsed.bom_rows[0]

    assert row.inventory_strategy == "Critico"
    assert (row.stock_max, row.stock_min, row.source_stock) == (
        Decimal(4),
        Decimal(1),
        Decimal(3),
    )


def test_embedded_images_are_extracted_with_their_hash(parsed: ParsedEngineeringBom) -> None:
    image = parsed.drawing_images[0]

    assert image.sheet_name == "Plano Despiece"
    assert image.anchor == "C5"
    assert (image.width_px, image.height_px) == (9, 4)
    assert len(image.sha256) == 64
    assert image.content.startswith(b"\x89PNG")


def test_an_image_is_tied_to_a_drawing_only_when_unambiguous(
    parsed: ParsedEngineeringBom,
) -> None:
    image = parsed.drawing_images[0]

    assert image.drawing_number == "PL-002"
    assert image.association_rule == "unique_drawing_number_in_sheet"


def test_an_ambiguous_image_is_left_pending_review() -> None:
    """Con dos planos posibles en la hoja no se elige ninguno."""
    sheets = _sheets()
    sheets["Plano Despiece"] = [["Plano", "PL-001"], ["Plano", "PL-002"]]
    workbook = with_embedded_image(build_workbook(sheets), sheet_name="Plano Despiece")

    parsed = parse_engineering_workbook(workbook)

    assert parsed.drawing_images[0].drawing_number is None
    assert "drawing_association_pending" in {w.code for w in parsed.warnings}


def test_amef_is_extracted(parsed: ParsedEngineeringBom) -> None:
    mode = parsed.failure_modes[0]

    assert mode.failure_mode == "Desgaste"
    assert (mode.severity, mode.occurrence, mode.detection) == (7, 3, 4)


def test_rpn_is_computed_by_the_backend_not_read_from_the_file(
    parsed: ParsedEngineeringBom,
) -> None:
    """El archivo decía 999; manda S x O x D = 84."""
    assert parsed.failure_modes[0].rpn == 84
    assert "rpn_recomputed" in {warning.code for warning in parsed.warnings}


def test_rpn_is_absent_when_a_factor_is_missing() -> None:
    sheets = _sheets()
    sheets["AMEF"] = [
        AMEF_HEADERS,
        [
            "Accionamiento",
            "Pieza",
            "10000001",
            "Falla",
            "Efecto",
            "Causa",
            7,
            None,
            4,
            "",
            "",
            "",
            "",
            "",
        ],
    ]

    parsed = parse_engineering_workbook(build_workbook(sheets))

    assert parsed.failure_modes[0].rpn is None


def test_sod_criteria_are_extracted_per_dimension(parsed: ParsedEngineeringBom) -> None:
    dimensions = {criterion.dimension for criterion in parsed.sod_criteria}

    assert dimensions == {"severity", "occurrence", "detection"}
    severity = [c for c in parsed.sod_criteria if c.dimension == "severity"]
    assert {c.scale_value for c in severity} == {1, 10}
    assert severity[0].range_low == Decimal(0)


def test_option_tables_are_preserved_as_versioned_data(parsed: ParsedEngineeringBom) -> None:
    values = {(option.table_name, option.option_value) for option in parsed.option_rows}

    assert ("Estrategia de inventario", "Critico") in values


def test_a_workbook_without_a_bom_sheet_is_rejected() -> None:
    with pytest.raises(MissingSheetError):
        parse_engineering_workbook(build_workbook({"Otra": [["a", "b"]]}))


def test_missing_optional_sheets_are_reported_not_fatal() -> None:
    workbook = build_workbook(
        {
            "BOM": [
                BOM_HEADERS,
                ["1", "A", "B", "1000", "d", 1, "UN", "m", "PL", "R", "", "", 1, 1, 1, ""],
            ]
        }
    )

    parsed = parse_engineering_workbook(workbook)

    codes = {(warning.code, warning.location) for warning in parsed.warnings}
    assert ("missing_sheet", "amef") in codes
    assert ("missing_sheet", "sod") in codes
    assert len(parsed.bom_rows) == 1


def test_unknown_columns_are_preserved_instead_of_discarded() -> None:
    headers = [*BOM_HEADERS, "Columna inventada"]
    workbook = build_workbook(
        {
            "BOM": [
                headers,
                ["1", "A", "B", "1000", "d", 1, "UN", "m", "PL", "R", "", "", 1, 1, 1, "", "dato"],
            ]
        }
    )

    parsed = parse_engineering_workbook(workbook)

    assert parsed.bom_rows[0].extra["Columna inventada"] == "dato"
    assert "unknown_columns" in {warning.code for warning in parsed.warnings}


def test_headers_with_extra_wording_still_match() -> None:
    """`Cantidad (UN)` sigue siendo la columna de cantidad."""
    headers = list(BOM_HEADERS)
    headers[headers.index("Cantidad")] = "Cantidad (UN)"
    workbook = build_workbook(
        {
            "BOM": [
                headers,
                ["1", "A", "B", "1000", "d", 5, "UN", "m", "PL", "R", "", "", 1, 1, 1, ""],
            ]
        }
    )

    parsed = parse_engineering_workbook(workbook)

    assert parsed.bom_rows[0].quantity == Decimal(5)


def test_unicode_content_survives_the_round_trip() -> None:
    workbook = build_workbook(
        {
            "BOM": [
                BOM_HEADERS,
                [
                    "1",
                    "Cañería",
                    'Válvula ½" ficticia',
                    "1000",
                    "Ø25",
                    1,
                    "UN",
                    "m",
                    "PL",
                    "R",
                    "",
                    "",
                    1,
                    1,
                    1,
                    "—",
                ],
            ]
        }
    )

    parsed = parse_engineering_workbook(workbook)

    assert parsed.bom_rows[0].component_name == 'Válvula ½" ficticia'
    assert parsed.bom_rows[0].subsystem_name == "Cañería"


def test_blank_rows_are_skipped() -> None:
    workbook = build_workbook(
        {
            "BOM": [
                BOM_HEADERS,
                ["1", "A", "B", "1000", "d", 1, "UN", "m", "PL", "R", "", "", 1, 1, 1, ""],
                [None] * len(BOM_HEADERS),
                ["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
            ]
        }
    )

    assert len(parse_engineering_workbook(workbook).bom_rows) == 1
