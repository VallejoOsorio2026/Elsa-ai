"""«Esto es lo que entendí»: extracción determinística sobre el texto del aporte.

No hay modelo de lenguaje aquí tampoco. Lo que hace este módulo es buscar,
**literalmente**, referencias del BOM publicado dentro del texto que escribió
la persona, y proponerlas como campos estructurados que ella puede corregir.

Por qué así y no con un modelo: el resultado de esta extracción es lo que un
revisor va a leer para decidir si algo entra en el conocimiento del equipo.
Una inferencia plausible pero equivocada —un componente que nadie mencionó,
un código que se parece a otro— es más peligrosa que un campo vacío, porque
llega revestida de autoridad. Aquí, si un campo tiene valor, es porque esa
cadena está en el texto.

Todo lo extraído es **editable**. La extracción propone; la persona decide;
ambas cosas se guardan.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from elsa.core.normalization import canonical_sap_code, normalize_key, normalize_text
from elsa.core.retrieval import Query, candidates_from, parse_query, search

__all__ = [
    "CHECKLIST",
    "ChecklistItem",
    "ExtractedField",
    "extract",
    "extraction_source",
]


@dataclass(frozen=True, slots=True)
class ExtractedField:
    """Un campo propuesto por la extracción."""

    key: str
    label: str
    detected: str | None
    kind: str = "text"
    matched_in_bom: bool = False
    hint: str | None = None
    """Qué debe escribir la persona si el campo quedó vacío."""


@dataclass(frozen=True, slots=True)
class ChecklistItem:
    """Una pregunta de la guía que acompaña al aporte."""

    key: str
    question: str
    hint: str
    required: bool = False


# La guía no es un formulario: es lo que un ingeniero con experiencia
# preguntaría antes de dar por buena una observación de planta. Solo dos
# puntos son obligatorios, los que sin respuesta hacen inútil el aporte.
CHECKLIST: tuple[ChecklistItem, ...] = (
    ChecklistItem(
        key="que_paso",
        question="¿Qué observaste exactamente?",
        hint="El hecho, no la conclusión. «Ruido metálico al arrancar», no «está dañado».",
        required=True,
    ),
    ChecklistItem(
        key="donde",
        question="¿En qué parte del equipo?",
        hint="Subsistema, componente o código de material, si lo tienes a mano.",
        required=True,
    ),
    ChecklistItem(
        key="cuando",
        question="¿Cuándo ocurrió y con qué frecuencia?",
        hint="Fecha aproximada y si es la primera vez o se repite.",
    ),
    ChecklistItem(
        key="condiciones",
        question="¿En qué condiciones se presenta?",
        hint="Carga, velocidad, temperatura, arranque o régimen estable.",
    ),
    ChecklistItem(
        key="accion",
        question="¿Qué se hizo o qué recomiendas?",
        hint="La intervención aplicada, o la que propones y por qué.",
    ),
    ChecklistItem(
        key="evidencia",
        question="¿Hay evidencia de apoyo?",
        hint="Fotos, medición, número de orden. Adjúntala si la tienes.",
    ),
)


def extract(
    text: str,
    *,
    asset_name: str,
    bom_items: Sequence[object] = (),
    failure_modes: Sequence[object] = (),
) -> tuple[ExtractedField, ...]:
    """Propone campos estructurados a partir del texto y del BOM publicado.

    ``bom_items`` y ``failure_modes`` son los registros publicados del
    equipo. Sin ellos la extracción sigue funcionando: simplemente no puede
    decir si lo mencionado existe en el conocimiento aprobado.
    """
    clean = normalize_text(text) or ""
    query = parse_query(clean)

    components = _match_components(query, bom_items)
    subsystems = _match_subsystems(clean, bom_items)
    codes, unknown_codes = _split_codes(query, bom_items)
    modes = _match_failure_modes(query, failure_modes)

    return (
        ExtractedField(
            key="equipo",
            label="Equipo",
            detected=asset_name,
            matched_in_bom=True,
            hint="El equipo del alcance en el que estás trabajando.",
        ),
        ExtractedField(
            key="subsistemas",
            label="Subsistemas mencionados",
            detected=", ".join(subsystems) or None,
            kind="list",
            matched_in_bom=bool(subsystems),
            hint="Ninguno de los subsistemas del BOM publicado aparece en tu texto.",
        ),
        ExtractedField(
            key="componentes",
            label="Componentes reconocidos en el BOM publicado",
            detected=", ".join(components) or None,
            kind="list",
            matched_in_bom=bool(components),
            hint="No reconocí ningún componente del BOM. Escríbelo como lo llames en planta.",
        ),
        ExtractedField(
            key="codigos_sap",
            label="Códigos de material del BOM",
            detected=", ".join(codes) or None,
            kind="list",
            matched_in_bom=bool(codes),
            hint="No mencionaste ningún código que esté en el BOM publicado.",
        ),
        ExtractedField(
            key="codigos_desconocidos",
            label="Códigos mencionados que NO están en el BOM",
            detected=", ".join(unknown_codes) or None,
            kind="list",
            matched_in_bom=False,
            hint="Ninguno. Todos los códigos que escribiste existen en el BOM publicado.",
        ),
        ExtractedField(
            key="modos_falla",
            label="Modos de falla del AMEF relacionados",
            detected=", ".join(modes) or None,
            kind="list",
            matched_in_bom=bool(modes),
            hint="Tu texto no coincide con ningún modo de falla ya registrado.",
        ),
        ExtractedField(
            key="resumen",
            label="Resumen en una frase",
            detected=None,
            kind="text",
            hint="Escríbelo tú: una frase que un compañero entienda sin contexto.",
        ),
    )


def _names(records: Sequence[object], attribute: str) -> list[str]:
    """Nombres únicos y no vacíos de un atributo, conservando el orden."""
    found: list[str] = []
    for record in records:
        value = getattr(record, attribute, None)
        if isinstance(value, str) and value and value not in found:
            found.append(value)
    return found


def _match_components(query: Query, bom_items: Sequence[object]) -> list[str]:
    if not bom_items:
        return []
    matches = search(
        query,
        candidates_from(bom_items, text_fields=("component_name",), code_field="sap_code"),
        limit=8,
    )
    return _names([match.payload for match in matches], "component_name")


def _match_failure_modes(query: Query, modes: Sequence[object]) -> list[str]:
    if not modes:
        return []
    matches = search(
        query,
        candidates_from(modes, text_fields=("failure_mode", "effect", "cause")),
        limit=5,
    )
    return _names([match.payload for match in matches], "failure_mode")


def _match_subsystems(text: str, bom_items: Sequence[object]) -> list[str]:
    """Un subsistema coincide por su nombre completo, no por palabras sueltas.

    «Sección de prensas» y «sección de secado» comparten «sección»: emparejar
    por término suelto asignaría el aporte al subsistema equivocado.
    """
    haystack = normalize_key(text) or ""
    found: list[str] = []
    for name in _names(bom_items, "subsystem_name"):
        key = normalize_key(name)
        if key and key in haystack:
            found.append(name)
    return found


def _split_codes(query: Query, bom_items: Sequence[object]) -> tuple[list[str], list[str]]:
    """Separa los códigos mencionados entre los que existen y los que no.

    Un código que no está en el BOM no es un error del que lo escribió: puede
    ser un material nuevo, o un código de otro sistema. Se muestra aparte
    para que el revisor lo mire, no se descarta.
    """
    mentioned = list(query.codes)
    if not mentioned:
        return [], []
    known = {
        canonical_sap_code(getattr(item, "sap_code", None))
        for item in bom_items
        if getattr(item, "sap_code", None)
    }
    inside = [code for code in mentioned if code in known]
    outside = [code for code in mentioned if code not in known]
    return inside, outside


def extraction_source(text: str | None, answers: Sequence[object] = ()) -> str:
    """Todo lo que la persona escribió, junto, para buscar en ello.

    La extracción no mira solo el relato: las respuestas de la guía son
    igual de suyas, y a menudo es en «¿en qué parte del equipo?» donde
    aparece el nombre del componente. Buscar solo en el relato dejaría fuera
    justo el campo pensado para nombrarlo.

    No se inventa nada al juntarlas: sigue siendo texto escrito por la
    persona, y la búsqueda sobre él sigue siendo literal.
    """
    pieces = [normalize_text(text)]
    pieces.extend(normalize_text(getattr(answer, "answer", None)) for answer in answers)
    return " ".join(piece for piece in pieces if piece)
