"""Cuándo una pregunta pide un código exacto, y que el código nunca se toca."""

import pytest

from elsa.core.material_code import (
    EXPECTED_MATERIALS_CONTRACT_VERSION,
    CodeDetectionKind,
    detect_exact_material_code,
)


def test_the_expected_contract_version_is_the_string_one() -> None:
    assert EXPECTED_MATERIALS_CONTRACT_VERSION == "1"
    assert isinstance(EXPECTED_MATERIALS_CONTRACT_VERSION, str)


@pytest.mark.parametrize(
    ("question", "code"),
    [
        ("¿Qué disponibilidad tiene el material 1234567?", "1234567"),
        ("stock del código 1234567", "1234567"),
        ("hay existencias de 1234567?", "1234567"),
        ("INVENTARIO 1234567", "1234567"),
        ("1234567", "1234567"),
        ("  ¿1234567?  ", "1234567"),
        ("material 1234567 y de nuevo material 1234567", "1234567"),
    ],
)
def test_a_single_exact_code_is_detected(question: str, code: str) -> None:
    detection = detect_exact_material_code(question)

    assert detection.kind is CodeDetectionKind.SINGLE
    assert detection.code == code


@pytest.mark.parametrize("code", ["000123", "0000001234567", "000000000010023456", "100000"])
def test_the_code_is_returned_exactly_as_written(code: str) -> None:
    """Ceros iniciales incluidos: M3-A prohíbe quitarlos, añadirlos o rellenar."""
    for question in (f"disponibilidad del material {code}", code, f"stock {code}."):
        detection = detect_exact_material_code(question)

        assert detection.kind is CodeDetectionKind.SINGLE
        assert detection.code == code
        assert isinstance(detection.code, str)


@pytest.mark.parametrize(
    "question",
    [
        "rodamiento SKF",
        "llave mixta",
        "disponibilidad de rodamientos de la prensa",
        "material",
        "",
        # Sin palabra de inventario y con más texto: no se pregunta por nada vivo.
        "el rodamiento 1234567 de la prensa inferior hace ruido",
        # No tiene forma de código decimal exacto.
        "stock SYN-100003",
        "stock A1234567",
        "stock 1234567A",
        "stock 1234567-2",
        "stock 1234567/12",
        "stock 1.500000",
        "stock 12345",
        # Dígitos no ASCII.
        "stock ٧٠٢٤٩٩٧٠",
        # Demasiado largo para ser un material.
        "stock " + "1" * 19,
    ],
)
def test_text_without_an_exact_code_never_triggers_a_lookup(question: str) -> None:
    assert detect_exact_material_code(question).kind is CodeDetectionKind.NOT_APPLICABLE


def test_several_distinct_codes_are_ambiguous_and_none_is_chosen() -> None:
    detection = detect_exact_material_code("stock de los materiales 1234567 y 1234568")

    assert detection.kind is CodeDetectionKind.AMBIGUOUS
    assert detection.code is None


def test_two_spellings_of_the_same_number_are_two_codes() -> None:
    """``000123`` y ``0000123`` son cadenas distintas: no se declaran equivalentes."""
    detection = detect_exact_material_code("stock 0000123 y 00000123")

    assert detection.kind is CodeDetectionKind.AMBIGUOUS
