"""La composición `context-v1` del texto que se embebe.

Es función pura: sin base de datos, sin reloj y sin estado. Lo que se prueba
es que el texto que va al modelo lleva su contexto delante, que la plantilla
entra en la identidad del hash, y que dos chunks casi idénticos de activos
distintos dejan de ser casi idénticos al componerlos — que es la razón de
que la composición exista.
"""

from elsa.documents.composition import COMPOSITION_TEMPLATE, compose_for_embedding


def test_the_context_goes_in_front_of_the_content() -> None:
    composed = compose_for_embedding(
        content="El par de apriete es de 45 N·m.",
        document_title="Manual de la prensa",
        heading_trail=("Manual de la prensa", "Par de apriete"),
    )

    assert composed.text == (
        "Manual de la prensa › Par de apriete › El par de apriete es de 45 N·m."
    )
    assert composed.template == COMPOSITION_TEMPLATE


def test_the_document_title_is_not_repeated_when_the_trail_already_has_it() -> None:
    """El chunker pone el `# título` como sección raíz; duplicarlo delante de
    cada chunk solo añadiría ruido idéntico a todo el corpus."""
    composed = compose_for_embedding(
        content="texto",
        document_title="Manual de la prensa",
        heading_trail=("Manual de la prensa",),
    )

    assert composed.text == "Manual de la prensa › texto"


def test_missing_context_degrades_to_the_content() -> None:
    assert compose_for_embedding(content="texto").text == "texto"
    assert compose_for_embedding(content="texto", document_title="   ").text == "texto"
    assert compose_for_embedding(content="texto", heading_trail=("", "  ")).text == "texto"


def test_composition_disambiguates_two_assets_that_talk_alike() -> None:
    """Es la razón de ser de la plantilla.

    «El par de apriete es de 45 N·m» es casi idéntico en el manual de la
    prensa y en el de la bomba; sin contexto, sus vectores quedarían
    prácticamente en el mismo sitio.
    """
    shared = "El par de apriete de los tornillos es de 45 N·m."
    press = compose_for_embedding(
        content=shared, document_title="Manual de la prensa", heading_trail=("Par de apriete",)
    )
    pump = compose_for_embedding(
        content=shared, document_title="Manual de la bomba", heading_trail=("Par de apriete",)
    )

    assert press.text != pump.text
    assert press.embedded_sha256 != pump.embedded_sha256


def test_the_hash_is_deterministic() -> None:
    first = compose_for_embedding(content="texto", document_title="Doc")
    second = compose_for_embedding(content="texto", document_title="Doc")

    assert first.embedded_sha256 == second.embedded_sha256
    assert len(first.embedded_sha256) == 64


def test_the_template_is_part_of_the_identity() -> None:
    """Cambiar la plantilla invalida los vectores, y el hash tiene que decirlo.

    El mismo contenido compuesto con otra plantilla es otra entrada para el
    modelo: si diera el mismo hash, nadie sabría que hay que re-embeberlo.
    """
    from dataclasses import replace

    composed = compose_for_embedding(content="texto", document_title="Doc")
    other = replace(composed, template="context-v2")

    assert other.text == composed.text
    assert other.embedded_sha256 != composed.embedded_sha256


def test_whitespace_does_not_change_the_hash() -> None:
    """El texto se normaliza antes de hashearlo: un espacio de más en el
    manual no puede obligar a re-embeber el corpus."""
    tight = compose_for_embedding(content="a b", document_title="Doc")
    loose = compose_for_embedding(content="a    b", document_title="Doc")

    assert tight.embedded_sha256 == loose.embedded_sha256
