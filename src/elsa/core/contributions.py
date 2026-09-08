"""Reglas de dominio de los aportes de conocimiento.

Lógica pura: sin base de datos, sin FastAPI. Aquí viven las dos decisiones
que no pueden quedar dispersas por la aplicación.

**El ciclo de vida.** Un aporte solo avanza por transiciones declaradas. La
que no está en la tabla no ocurre, y en particular no hay ninguna que lleve
de ``PENDING`` a publicado: aprobar un aporte lo marca como válido, no lo
convierte en conocimiento vigente. Esa segunda puerta la abre la publicación
de una versión, igual que con el BOM de Ingeniería.

**Qué puede enviarse.** Un aporte sin contenido no es un aporte. La guía
tiene dos preguntas obligatorias —qué observaste y dónde— porque sin ellas
el revisor no puede decidir nada y el aporte solo genera trabajo.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from elsa.core.normalization import normalize_key, normalize_text
from elsa.core.understanding import CHECKLIST
from elsa.ports.contributions import ChecklistAnswer, ContributionRecord, ContributionState

__all__ = [
    "ALLOWED_TRANSITIONS",
    "MAX_TITLE_LENGTH",
    "ContributionRuleError",
    "InvalidTransitionError",
    "NotSubmittableError",
    "SubmitCheck",
    "check_submittable",
    "derive_title",
    "ensure_submittable",
    "is_placeholder_title",
    "neutral_title",
    "validate_transition",
]

MAX_TITLE_LENGTH = 90
"""Longitud a la que se recorta un título derivado.

No es el límite de la API —ese es mayor— sino lo que cabe leerse de un
vistazo en una lista de revisión.
"""


class ContributionRuleError(Exception):
    """Una regla de dominio del aporte impide la operación."""


class InvalidTransitionError(ContributionRuleError):
    """El aporte no puede pasar de su estado actual al pedido."""


class NotSubmittableError(ContributionRuleError):
    """Falta contenido obligatorio para enviar el aporte a revisión."""

    def __init__(self, message: str, missing: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.missing = tuple(missing)


# Tabla completa. Un estado que no aparece como clave es terminal.
ALLOWED_TRANSITIONS: dict[ContributionState, frozenset[ContributionState]] = {
    ContributionState.DRAFT: frozenset({ContributionState.PENDING}),
    ContributionState.PENDING: frozenset({ContributionState.APPROVED, ContributionState.REJECTED}),
    # Un rechazo puede reconsiderarse: la decisión de una persona la puede
    # revertir otra con el mismo alcance, igual que en la revisión del BOM.
    ContributionState.REJECTED: frozenset({ContributionState.APPROVED}),
    ContributionState.APPROVED: frozenset({ContributionState.REJECTED}),
}

_REQUIRED_CHECKLIST_KEYS = tuple(item.key for item in CHECKLIST if item.required)
_QUESTION_BY_KEY = {item.key: item.question for item in CHECKLIST}


def validate_transition(current: ContributionState, target: ContributionState) -> None:
    """Comprueba que la transición está declarada."""
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransitionError(
            f"a contribution in state {current.value!r} cannot move to {target.value!r}"
        )


@dataclass(frozen=True, slots=True)
class SubmitCheck:
    """Resultado de comprobar si un aporte puede enviarse."""

    ok: bool
    missing: tuple[str, ...] = ()
    """Claves de la guía sin responder, más ``content`` si no hay nada que revisar."""

    reasons: tuple[str, ...] = ()
    """Explicación legible de cada carencia."""


def check_submittable(
    record: ContributionRecord, *, checklist: Sequence[ChecklistAnswer] | None = None
) -> SubmitCheck:
    """Dice si el aporte puede enviarse y, si no, exactamente qué falta.

    Devuelve el diagnóstico en vez de lanzar, para que la interfaz pueda
    señalar las casillas pendientes mientras se escribe.
    """
    answers = {answer.key: answer for answer in (checklist or record.checklist)}
    missing: list[str] = []
    reasons: list[str] = []

    has_audio = record.audio is not None
    has_text = bool(normalize_text(record.transcript_text))
    if not has_audio and not has_text:
        missing.append("content")
        reasons.append("Un aporte necesita al menos una nota de voz o un texto.")

    for key in _REQUIRED_CHECKLIST_KEYS:
        answer = answers.get(key)
        if answer is None or not normalize_text(answer.answer):
            missing.append(key)
            reasons.append(f"Falta responder: {_QUESTION_BY_KEY[key]}")

    return SubmitCheck(ok=not missing, missing=tuple(missing), reasons=tuple(reasons))


def ensure_submittable(
    record: ContributionRecord, *, checklist: Sequence[ChecklistAnswer] | None = None
) -> None:
    """Igual que :func:`check_submittable`, pero lanza si no se puede enviar."""
    result = check_submittable(record, checklist=checklist)
    if not result.ok:
        raise NotSubmittableError(" ".join(result.reasons), missing=result.missing)


# ---------------------------------------------------------------------
# Título del aporte
# ---------------------------------------------------------------------

# Palabras que una persona escribe cuando **no** ha puesto título: son
# marcadores, no descripciones. La lista es corta y literal a propósito.
# «Prueba de vibración» no está aquí y nunca lo estará: tiene más de una
# palabra y dice algo del aporte.
_PLACEHOLDER_TITLES = frozenset(
    """
    aporte aportes nota notas prueba pruebas test tests demo ejemplo
    titulo x xx xxx aaa asdf sin-titulo
    """.split()
)

_TRAILING_NUMBER = re.compile(r"[\s\-_#.]*\d+$")

# Cómo se corta una observación larga para el título: en el primer punto o
# salto de frase, y si no lo hay, en la última palabra que quepa.
_SENTENCE_END = re.compile(r"[.;\n]")


def is_placeholder_title(title: str | None) -> bool:
    """Si el título no dice nada del aporte.

    Vacío cuenta. También «Prueba 1», «test», «nota 3»: una palabra genérica
    con un número detrás es lo que se escribe para salir del paso, y deja la
    lista de revisión llena de renglones indistinguibles.
    """
    key = normalize_key(title)
    if key is None:
        return True
    return _TRAILING_NUMBER.sub("", key).strip() in _PLACEHOLDER_TITLES


def _shorten(text: str, limit: int) -> str:
    """Recorta sin partir palabras, prefiriendo el final de la primera frase."""
    clean = normalize_text(text) or ""
    end = _SENTENCE_END.search(clean)
    if end is not None and 0 < end.start() <= limit:
        clean = clean[: end.start()].strip()
    if len(clean) <= limit:
        return clean
    cut = clean[:limit].rsplit(" ", 1)[0].strip()
    return f"{cut or clean[:limit].strip()}…"


def _first_value(values: Sequence[str | None]) -> str | None:
    """Primer valor con contenido, y de una lista separada por comas, el primero."""
    for value in values:
        text = normalize_text(value)
        if text:
            return normalize_text(text.split(",")[0])
    return None


def neutral_title(sequence: int) -> str:
    """Rótulo numerado para cuando el aporte todavía no dice nada de sí mismo.

    Es preferible a inventar un asunto: distingue un aporte de otro sin
    afirmar nada sobre su contenido.
    """
    return f"Aporte técnico {sequence}"


def derive_title(
    *,
    normalizations: Sequence[object] = (),
    checklist: Sequence[ChecklistAnswer] = (),
) -> str | None:
    """Compone un título corto con lo que el propio aporte ya contiene.

    **No hay generación de texto**: se concatenan cadenas que la persona
    escribió o que la extracción literal reconoció en su texto. Devuelve
    ``None`` cuando no hay material, para que quien llama decida el rótulo de
    reserva (:func:`neutral_title`) en vez de recibir uno inventado aquí.
    """
    by_key = {getattr(item, "key", None): getattr(item, "value", None) for item in normalizations}
    answers = {answer.key: answer.answer for answer in checklist}

    subject = _first_value([by_key.get("componentes"), by_key.get("subsistemas")])
    observation = _first_value([answers.get("que_paso"), by_key.get("resumen")])

    if subject and observation:
        room = MAX_TITLE_LENGTH - len(subject) - 3
        if room >= 12:
            return f"{subject} — {_shorten(observation, room)}"
        return _shorten(subject, MAX_TITLE_LENGTH)
    if subject:
        return _shorten(subject, MAX_TITLE_LENGTH)
    if observation:
        return _shorten(observation, MAX_TITLE_LENGTH)
    return None
