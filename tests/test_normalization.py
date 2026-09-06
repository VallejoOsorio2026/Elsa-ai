"""Normalización determinística de los valores de una fuente."""

from decimal import Decimal

import pytest

from elsa.core.normalization import (
    canonical_sap_code,
    normalize_key,
    normalize_quantity,
    normalize_sap_code,
    normalize_text,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("  hola   mundo ", "hola mundo"), ("", None), ("   ", None), (None, None), (12, "12")],
)
def test_text_collapses_whitespace_and_treats_blank_as_absent(
    value: object, expected: str | None
) -> None:
    assert normalize_text(value) == expected


def test_key_ignores_case_and_accents() -> None:
    assert normalize_key(" Válvula  PRINCIPAL ") == normalize_key("valvula principal")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("2,5", Decimal("2.5")),
        ("1.000.000", Decimal("1000000")),
        ("-3", Decimal("-3")),
        (7, Decimal(7)),
        (2.5, Decimal("2.5")),
    ],
)
def test_quantity_separator_rule_is_deterministic(value: object, expected: Decimal) -> None:
    assert normalize_quantity(value) == expected


@pytest.mark.parametrize("value", ["=A1*2", "=SUMA(A1:A9)", "abc", "", None, True])
def test_quantity_is_none_when_not_interpretable(value: object) -> None:
    """Una fórmula no se evalúa nunca: es contenido no confiable."""
    assert normalize_quantity(value) is None


def test_sap_code_from_float_drops_the_spreadsheet_decimal() -> None:
    assert normalize_sap_code(10023456.0) == "10023456"


def test_sap_code_with_real_decimals_is_not_a_code() -> None:
    assert normalize_sap_code(1.5) is None


def test_canonical_code_ignores_sap_display_padding() -> None:
    """El mismo material en el Excel y en el HTM debe compararse igual."""
    assert canonical_sap_code("000000000010023456") == canonical_sap_code("10023456")


def test_canonical_code_keeps_leading_zeros_when_alphanumeric() -> None:
    """En un código alfanumérico un cero inicial puede ser significativo."""
    assert canonical_sap_code("A0012") == "A0012"


def test_canonical_code_of_all_zeros_is_not_empty() -> None:
    assert canonical_sap_code("0000") == "0"
