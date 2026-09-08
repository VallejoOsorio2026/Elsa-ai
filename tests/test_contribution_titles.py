"""El título del aporte se compone, no se inventa."""

from elsa.core.contributions import (
    MAX_TITLE_LENGTH,
    derive_title,
    is_placeholder_title,
    neutral_title,
)
from elsa.ports.contributions import ChecklistAnswer, Normalization


def _norm(key: str, value: str | None) -> Normalization:
    return Normalization(key=key, label=key, detected=value, value=value)


def _answer(key: str, answer: str | None) -> ChecklistAnswer:
    return ChecklistAnswer(key=key, question=key, answer=answer)


# -- Qué cuenta como marcador ------------------------------------------


def test_an_empty_title_is_a_placeholder() -> None:
    assert is_placeholder_title("") is True
    assert is_placeholder_title("   ") is True
    assert is_placeholder_title(None) is True


def test_a_generic_word_with_a_number_is_a_placeholder() -> None:
    """«Prueba 1» deja la cola de revisión llena de renglones iguales."""
    for title in ("Prueba 1", "prueba", "Test 2", "TEST", "nota 3", "Demo", "aporte 12"):
        assert is_placeholder_title(title) is True, title


def test_a_title_that_says_something_is_respected() -> None:
    """El filtro es literal y corto: no puede tragarse un título real."""
    for title in (
        "Prueba de vibración en la prensa",
        "Ruido en el rodamiento inferior",
        "Test de estanqueidad del sello",
        "Fuga",
    ):
        assert is_placeholder_title(title) is False, title


# -- Composición --------------------------------------------------------


def test_a_component_and_an_observation_make_the_title() -> None:
    title = derive_title(
        normalizations=[_norm("componentes", "Rodamiento rodillo prensa inferior")],
        checklist=[_answer("que_paso", "Ruido metálico al arrancar la sección")],
    )
    assert title == "Rodamiento rodillo prensa inferior — Ruido metálico al arrancar la sección"


def test_only_the_first_component_is_used() -> None:
    """Una lista entera no cabe y no ayuda a distinguir el aporte."""
    title = derive_title(
        normalizations=[_norm("componentes", "Junta rotativa de vapor, Purgador de condensado")],
    )
    assert title == "Junta rotativa de vapor"


def test_the_subsystem_serves_when_there_is_no_component() -> None:
    title = derive_title(normalizations=[_norm("subsistemas", "Sección de secado")])
    assert title == "Sección de secado"


def test_the_summary_serves_when_the_guide_is_empty() -> None:
    title = derive_title(
        normalizations=[
            _norm("componentes", "Reductor principal"),
            _norm("resumen", "Vibración creciente en la primera etapa"),
        ],
    )
    assert title == "Reductor principal — Vibración creciente en la primera etapa"


def test_a_long_observation_is_cut_at_the_first_sentence() -> None:
    title = derive_title(
        normalizations=[_norm("componentes", "Filtro de aceite")],
        checklist=[
            _answer("que_paso", "Se colmató el filtro. Lo cambiamos el martes por la tarde.")
        ],
    )
    assert title == "Filtro de aceite — Se colmató el filtro"


def test_a_title_never_exceeds_the_readable_length() -> None:
    title = derive_title(
        normalizations=[
            _norm("componentes", "Rodamiento de rodillos a rótula del rodillo inferior")
        ],
        checklist=[_answer("que_paso", "x" * 400)],
    )
    assert title is not None
    assert len(title) <= MAX_TITLE_LENGTH + 1  # el carácter de elisión


def test_no_material_means_no_invented_title() -> None:
    """Sin datos no se afirma nada sobre el aporte."""
    assert derive_title() is None
    assert derive_title(normalizations=[_norm("componentes", None)]) is None
    assert derive_title(checklist=[_answer("que_paso", "   ")]) is None


def test_the_neutral_label_distinguishes_without_asserting() -> None:
    assert neutral_title(1) == "Aporte técnico 1"
    assert neutral_title(7) == "Aporte técnico 7"
