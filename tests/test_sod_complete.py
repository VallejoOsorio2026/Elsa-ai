"""Tablas S/O/D completas: las tres dimensiones con todos sus niveles.

El defecto que cubren estos tests es de **pérdida silenciosa**: las tres
dimensiones se detectaban, pero se importaban menos criterios de los que la
hoja contenía y nada lo advertía.

Los diez niveles por dimensión son datos de estos fixtures y criterio de
aceptación del archivo piloto, **no** una regla del parser: el parser importa
las filas válidas que encuentre, sean las que sean.
"""

from collections import Counter
from typing import Any

import pytest

from elsa.ingestion.engineering_xlsx import parse_engineering_workbook
from elsa.ingestion.model import ParsedEngineeringBom
from tests.fixtures_xlsx import BOM_HEADERS, build_workbook

LEVELS = 10

BOM: list[list[Any]] = [
    BOM_HEADERS,
    ["1", "A", "Pieza ficticia", "90000001", "d", 1, "UN", "m", "PL-1", "R-1", "", "", 1, 1, 1, ""],
]

AMEF: list[list[Any]] = [
    [
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
        "Obs",
    ],
    [
        "A",
        "Pieza ficticia",
        "90000001",
        "Desgaste",
        "Vibracion",
        "Fatiga",
        7,
        3,
        4,
        999,
        "Revisar",
        "Mensual",
        "Cambiar",
        "",
    ],
]

# Descripciones que contienen palabras que también nombran columnas de escala.
# Antes se tragaban la fila entera y con ella sus criterios.
TRICKY = {
    1: "Rango muy bajo",
    2: "Grado menor",
    3: "Nivel medio",
    4: "Valor alto",
    5: "Indice critico",
}


def _label(level: int) -> str:
    return TRICKY.get(level, f"Criterio {level}")


def stacked(headings: tuple[str, str, str], *, scale_column: str = "Valor") -> list[list[Any]]:
    """Las tres tablas una debajo de otra."""
    rows: list[list[Any]] = []
    for heading in headings:
        rows.append([heading])
        rows.append([scale_column, "Criterio"])
        rows.extend([level, _label(level)] for level in range(1, LEVELS + 1))
    return rows


def side_by_side(headings: tuple[str, str, str]) -> list[list[Any]]:
    """Las tres tablas una al lado de otra, en columnas."""
    rows: list[list[Any]] = [
        [headings[0], None, headings[1], None, headings[2], None],
        ["Valor", "Criterio", "Valor", "Criterio", "Valor", "Criterio"],
    ]
    rows.extend(
        [level, _label(level), level, _label(level), level, _label(level)]
        for level in range(1, LEVELS + 1)
    )
    return rows


def _parse(sod: list[list[Any]]) -> ParsedEngineeringBom:
    return parse_engineering_workbook(
        build_workbook({"BOM": BOM, "AMEF": AMEF, "Valoración SOD": sod})
    )


SPANISH = ("Severidad", "Ocurrencia", "Detección")
ENGLISH = ("Severity", "Occurrence", "Detection")
INITIALS = ("Calificación (S)", "Calificación (O)", "Calificación (D)")
SYNONYMS = ("Gravedad", "Probabilidad de ocurrencia", "Detección")


@pytest.mark.parametrize(
    ("name", "sod"),
    [
        ("stacked, spanish", stacked(SPANISH)),
        ("stacked, english", stacked(ENGLISH)),
        ("stacked, initials", stacked(INITIALS)),
        ("stacked, synonyms", stacked(SYNONYMS)),
        ("stacked, scale column named 'Nivel'", stacked(SPANISH, scale_column="Nivel")),
        ("side by side, spanish", side_by_side(SPANISH)),
        ("side by side, initials", side_by_side(INITIALS)),
    ],
)
def test_every_layout_yields_all_three_full_tables(name: str, sod: list[list[Any]]) -> None:
    """Diez niveles por dimensión, treinta criterios, en cualquier disposición."""
    parsed = _parse(sod)

    counts = Counter(criterion.dimension for criterion in parsed.sod_criteria)
    assert counts["severity"] == LEVELS, name
    assert counts["occurrence"] == LEVELS, name
    assert counts["detection"] == LEVELS, name
    assert len(parsed.sod_criteria) == LEVELS * 3, name


def test_descriptions_naming_a_scale_column_do_not_swallow_their_row() -> None:
    """Regresión directa del defecto: «Rango muy bajo» tragaba la fila."""
    parsed = _parse(stacked(SPANISH))

    labels = {criterion.label for criterion in parsed.sod_criteria}
    assert TRICKY[1] in labels
    assert TRICKY[3] in labels


def test_auxiliary_columns_do_not_cost_criteria() -> None:
    rows: list[list[Any]] = []
    for heading in SPANISH:
        rows.append([heading, None, None])
        rows.append(["Valor", "Criterio", "Notas"])
        rows.extend([level, _label(level), None] for level in range(1, LEVELS + 1))

    assert len(_parse(rows).sod_criteria) == LEVELS * 3


def test_blank_rows_between_blocks_do_not_cost_criteria() -> None:
    rows: list[list[Any]] = []
    for heading in SPANISH:
        rows.append([heading])
        rows.append(["Valor", "Criterio"])
        rows.extend([level, _label(level)] for level in range(1, LEVELS + 1))
        rows.append([None, None])

    assert len(_parse(rows).sod_criteria) == LEVELS * 3


def test_a_merged_title_above_the_tables_does_not_cost_criteria() -> None:
    rows: list[list[Any]] = [["Valoración SOD", None, None], [None, None, None]]
    rows.extend(stacked(SPANISH))

    assert len(_parse(rows).sod_criteria) == LEVELS * 3


def test_the_dimensions_do_not_need_the_same_geometry() -> None:
    """Una tabla con columna auxiliar y otra sin ella conviven."""
    rows: list[list[Any]] = [["Severidad", None], ["Valor", "Criterio"]]
    rows.extend([level, _label(level)] for level in range(1, LEVELS + 1))
    rows.append(["Ocurrencia", None, None])
    rows.append(["Tasa", "Valor", "Criterio"])
    rows.extend([0.01 * level, level, _label(level)] for level in range(1, LEVELS + 1))
    rows.append(["Detección"])
    rows.append(["Nivel", "Criterio"])
    rows.extend([level, _label(level)] for level in range(1, LEVELS + 1))

    counts = Counter(criterion.dimension for criterion in _parse(rows).sod_criteria)

    assert counts == {"severity": LEVELS, "occurrence": LEVELS, "detection": LEVELS}


def test_rows_carrying_numbers_but_no_scale_are_reported() -> None:
    """Si la hoja tiene más niveles de los importados, tiene que verse."""
    rows: list[list[Any]] = [["Severidad"], ["Valor", "Criterio"]]
    rows.extend([level, _label(level)] for level in range(1, LEVELS + 1))
    rows.append([99.5, "Fuera de escala"])
    rows.append(["Ocurrencia"])
    rows.append(["Valor", "Criterio"])
    rows.extend([level, _label(level)] for level in range(1, LEVELS + 1))
    rows.append(["Detección"])
    rows.append(["Valor", "Criterio"])
    rows.extend([level, _label(level)] for level in range(1, LEVELS + 1))

    parsed = _parse(rows)

    assert "sod_rows_not_imported" in {warning.code for warning in parsed.warnings}


def test_a_dimension_that_yields_nothing_is_never_silent() -> None:
    rows: list[list[Any]] = [["Severidad"], ["Valor", "Criterio"], [1, "Sin efecto"]]
    rows.append(["Ocurrencia"])
    rows.append(["Rango", "Criterio"])
    rows.append(["1 de 1000", "Remota"])
    rows.append(["Detección"])
    rows.append(["Valor", "Criterio"])
    rows.append([1, "Casi segura"])

    parsed = _parse(rows)

    codes = {warning.code for warning in parsed.warnings}
    assert "sod_dimension_without_criteria" in codes
    assert "sod_dimension_missing" in codes


def test_a_sheet_with_no_recognisable_heading_warns() -> None:
    rows: list[list[Any]] = [["Tabla sin titulo"], ["Valor", "Criterio"], [1, "Algo"]]

    parsed = _parse(rows)

    assert "sod_dimension_unknown" in {warning.code for warning in parsed.warnings}
    assert parsed.sod_criteria == ()


def test_the_amef_and_its_rpn_do_not_regress() -> None:
    parsed = _parse(stacked(SPANISH))

    assert len(parsed.failure_modes) == 1
    assert parsed.failure_modes[0].rpn == 84
