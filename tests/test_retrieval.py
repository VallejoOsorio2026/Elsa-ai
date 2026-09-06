"""La búsqueda literal encuentra por término y por código, y no inventa."""

from elsa.core.retrieval import Candidate, candidates_from, parse_query, search


class _Row:
    def __init__(self, name: str, description: str = "", code: str | None = None) -> None:
        self.component_name = name
        self.technical_description = description
        self.sap_code = code


def test_parse_query_drops_stopwords_and_short_tokens() -> None:
    query = parse_query("¿Cuál es el rodamiento de la prensa?")
    assert "rodamiento" in query.terms
    assert "prensa" in query.terms
    # `cual`, `es`, `de`, `la` no discriminan nada.
    assert "cual" not in query.terms
    assert "es" not in query.terms


def test_parse_query_recognises_material_codes() -> None:
    query = parse_query("necesito el SYN-100001")
    assert query.codes == ("SYN-100001",)
    assert "syn-100001" not in query.terms


def test_parse_query_ignores_accents() -> None:
    assert parse_query("lubricación").terms == ("lubricacion",)


def test_a_word_with_a_digit_is_not_a_code() -> None:
    """`prensa2` es una palabra, no una referencia de material."""
    query = parse_query("prensa2")
    assert query.codes == ()
    assert query.terms == ("prensa2",)


def test_search_returns_the_matched_terms() -> None:
    rows = [_Row("Rodamiento rodillo prensa", "Rodamiento de rótula"), _Row("Filtro de aceite")]
    matches = search(
        parse_query("rodamiento prensa"),
        candidates_from(rows, text_fields=("component_name", "technical_description")),
    )
    assert len(matches) == 1
    assert set(matches[0].matched_terms) == {"rodamiento", "prensa"}


def test_search_without_matches_returns_nothing() -> None:
    """No se aproxima: sin coincidencia no hay resultado."""
    rows = [_Row("Filtro de aceite")]
    matches = search(
        parse_query("turbina hidráulica"),
        candidates_from(rows, text_fields=("component_name",)),
    )
    assert matches == ()


def test_an_exact_code_outranks_any_number_of_terms() -> None:
    rows = [
        _Row("Bomba de aceite de lubricación del sistema", code="SYN-999"),
        _Row("Filtro", code="SYN-100001"),
    ]
    matches = search(
        parse_query("SYN-100001 bomba aceite lubricacion sistema"),
        candidates_from(rows, text_fields=("component_name",), code_field="sap_code"),
    )
    assert matches[0].payload.sap_code == "SYN-100001"
    assert matches[0].is_exact_code


def test_sap_padding_does_not_break_the_match() -> None:
    """SAP rellena con ceros al mostrar; el mismo material debe emparejar."""
    rows = [_Row("Rodamiento", code="10023456")]
    matches = search(
        parse_query("000000000010023456"),
        candidates_from(rows, text_fields=("component_name",), code_field="sap_code"),
    )
    assert len(matches) == 1


def test_an_empty_question_is_not_searchable() -> None:
    assert not parse_query("¿que hay?").is_searchable


def test_search_respects_the_limit() -> None:
    rows = [_Row(f"Rodamiento {index}") for index in range(20)]
    matches = search(
        parse_query("rodamiento"),
        candidates_from(rows, text_fields=("component_name",)),
        limit=3,
    )
    assert len(matches) == 3


def test_candidate_text_is_normalised() -> None:
    candidate = candidates_from([_Row("Lubricación")], text_fields=("component_name",))[0]
    assert isinstance(candidate, Candidate)
    assert candidate.text == "lubricacion"
