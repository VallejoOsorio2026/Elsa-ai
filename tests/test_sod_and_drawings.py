"""Criterios S/O/D y asociación de planos.

Las distribuciones que se prueban aquí son las que la plantilla real puede
tener; los valores son inventados. Los dos primeros grupos fallaban antes de
la corrección de aceptación: uno perdía una dimensión entera en silencio y el
otro no avisaba de los planos sin asociar.
"""

from typing import Any

import pytest

from elsa.ingestion.engineering_xlsx import parse_engineering_workbook
from elsa.ingestion.model import ParsedEngineeringBom
from tests.fixtures_xlsx import BOM_HEADERS, build_workbook, minimal_png, with_embedded_image

BOM: list[list[Any]] = [
    BOM_HEADERS,
    [
        "1",
        "Accionamiento",
        "Pieza ficticia",
        "90000001",
        "d",
        1,
        "UN",
        "MOD-A",
        "PL-001",
        "R-01",
        "Si",
        "N",
        1,
        1,
        1,
        "",
    ],
]

STACKED: list[list[Any]] = [
    ["Severidad"],
    ["Valor", "Criterio"],
    [1, "Sin efecto"],
    [10, "Catastrofico"],
    ["Ocurrencia"],
    ["Valor", "Criterio"],
    [1, "Remota"],
    [10, "Muy alta"],
    ["Detección"],
    ["Valor", "Criterio"],
    [1, "Casi segura"],
    [10, "Nula"],
]

SIDE_BY_SIDE: list[list[Any]] = [
    ["Severidad", None, "Ocurrencia", None, "Detección"],
    ["Valor", "Criterio", "Valor", "Criterio", "Valor", "Criterio"],
    [1, "Sin efecto", 1, "Remota", 1, "Casi segura"],
    [10, "Catastrofico", 10, "Muy alta", 10, "Nula"],
]

INITIALS: list[list[Any]] = [
    ["Calificación (S)"],
    ["Valor", "Criterio"],
    [1, "Sin efecto"],
    [10, "Catastrofico"],
    ["Calificación (O)"],
    ["Valor", "Criterio"],
    [1, "Remota"],
    [10, "Muy alta"],
    ["Calificación (D)"],
    ["Valor", "Criterio"],
    [1, "Casi segura"],
    [10, "Nula"],
]

SYNONYMS: list[list[Any]] = [
    ["Gravedad"],
    ["Nivel", "Criterio"],
    [1, "Sin efecto"],
    [10, "Catastrofico"],
    ["Probabilidad de ocurrencia"],
    ["Nivel", "Criterio"],
    [1, "Remota"],
    [10, "Muy alta"],
    ["Detección"],
    ["Nivel", "Criterio"],
    [1, "Casi segura"],
    [10, "Nula"],
]

RATE_BEFORE_SCALE: list[list[Any]] = [
    ["Severidad"],
    ["Valor", "Criterio"],
    [1, "Sin efecto"],
    [10, "Catastrofico"],
    ["Ocurrencia"],
    ["Tasa de falla", "Valor", "Criterio"],
    [0.01, 1, "Remota"],
    [0.5, 10, "Muy alta"],
    ["Detección"],
    ["Valor", "Criterio"],
    [1, "Casi segura"],
    [10, "Nula"],
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
        "Observaciones",
    ],
    [
        "Accionamiento",
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


def _parse(sod: list[list[Any]]) -> ParsedEngineeringBom:
    return parse_engineering_workbook(
        build_workbook({"BOM": BOM, "AMEF": AMEF, "Valoración SOD": sod})
    )


@pytest.mark.parametrize(
    ("name", "sod"),
    [
        ("stacked", STACKED),
        ("side by side", SIDE_BY_SIDE),
        ("initials", INITIALS),
        ("synonyms", SYNONYMS),
        ("rate before the scale", RATE_BEFORE_SCALE),
    ],
)
def test_every_reasonable_layout_yields_the_three_dimensions(
    name: str, sod: list[list[Any]]
) -> None:
    """El defecto real perdía una dimensión según cómo estuviera dispuesta."""
    parsed = _parse(sod)

    assert {criterion.dimension for criterion in parsed.sod_criteria} == {
        "severity",
        "occurrence",
        "detection",
    }, name


def test_severity_criteria_keep_their_scale_and_label() -> None:
    parsed = _parse(STACKED)

    severity = [c for c in parsed.sod_criteria if c.dimension == "severity"]
    assert {c.scale_value for c in severity} == {1, 10}
    assert severity[0].label == "Sin efecto"


def test_occurrence_is_read_from_the_declared_scale_column() -> None:
    """Con una tasa delante, «el primer número de la fila» no es la escala."""
    parsed = _parse(RATE_BEFORE_SCALE)

    occurrence = [c for c in parsed.sod_criteria if c.dimension == "occurrence"]
    assert {c.scale_value for c in occurrence} == {1, 10}


def test_side_by_side_tables_do_not_mix_their_labels() -> None:
    parsed = _parse(SIDE_BY_SIDE)

    occurrence = [c for c in parsed.sod_criteria if c.dimension == "occurrence"]
    assert {c.label for c in occurrence} == {"Remota", "Muy alta"}


def test_a_dimension_without_readable_values_warns_instead_of_vanishing() -> None:
    """Quedarse callado ahí era el defecto: la dimensión desaparecía."""
    unreadable: list[list[Any]] = [
        ["Severidad"],
        ["Valor", "Criterio"],
        [1, "Sin efecto"],
        ["Ocurrencia"],
        ["Rango", "Criterio"],
        ["1 de 1000", "Remota"],
        ["Detección"],
        ["Valor", "Criterio"],
        [1, "Casi segura"],
    ]

    parsed = _parse(unreadable)

    codes = {warning.code for warning in parsed.warnings}
    assert "sod_dimension_without_criteria" in codes
    assert "sod_dimension_missing" in codes
    assert "occurrence" not in {c.dimension for c in parsed.sod_criteria}


def test_the_rpn_still_comes_from_the_backend() -> None:
    """La corrección de S/O/D no puede alterar el NPR determinístico."""
    parsed = _parse(STACKED)

    assert parsed.failure_modes[0].rpn == 84
    assert "rpn_recomputed" in {warning.code for warning in parsed.warnings}


# ---------------------------------------------------------------------
# Planos
# ---------------------------------------------------------------------


def _workbook_with_image(drawing_rows: list[list[Any]]) -> bytes:
    sheets: dict[str, list[list[Any]]] = {
        "BOM": [
            BOM_HEADERS,
            [
                "1",
                "A",
                "Pieza ficticia",
                "90000001",
                "d",
                1,
                "UN",
                "m",
                "PL-001",
                "R-01",
                "",
                "",
                1,
                1,
                1,
                "",
            ],
            [
                "2",
                "A",
                "Otra pieza",
                "90000002",
                "d",
                1,
                "UN",
                "m",
                "PL-002",
                "R-02",
                "",
                "",
                1,
                1,
                1,
                "",
            ],
        ],
        "Plano Despiece": drawing_rows,
        "Valoración SOD": STACKED,
    }
    return with_embedded_image(
        build_workbook(sheets), sheet_name="Plano Despiece", image=minimal_png(8, 5)
    )


def test_a_drawing_with_a_single_candidate_is_associated() -> None:
    parsed = parse_engineering_workbook(_workbook_with_image([["Plano", "PL-002"]]))

    image = parsed.drawing_images[0]
    assert image.drawing_number == "PL-002"
    assert image.association_rule == "unique_drawing_number_in_sheet"


def test_a_drawing_with_two_candidates_is_never_guessed() -> None:
    parsed = parse_engineering_workbook(
        _workbook_with_image([["Plano", "PL-001"], ["Plano", "PL-002"]])
    )

    assert parsed.drawing_images[0].drawing_number is None
    assert parsed.drawing_images[0].association_rule is None


def test_an_unassociated_drawing_always_raises_a_warning() -> None:
    """Extraer el plano y callarse era el defecto: nadie sabía que faltaba."""
    parsed = parse_engineering_workbook(
        _workbook_with_image([["Plano", "PL-001"], ["Plano", "PL-002"]])
    )

    warning = next(w for w in parsed.warnings if w.code == "drawing_association_pending")
    assert "1 image(s)" == warning.location


def test_an_image_with_no_candidate_at_all_is_still_kept_as_evidence() -> None:
    parsed = parse_engineering_workbook(_workbook_with_image([["Plano", "PL-999"]]))

    assert len(parsed.drawing_images) == 1
    assert parsed.drawing_images[0].drawing_number is None
    assert parsed.drawing_images[0].sha256
