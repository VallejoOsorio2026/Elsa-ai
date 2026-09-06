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

from collections.abc import Sequence
from dataclasses import dataclass

from elsa.core.normalization import normalize_text
from elsa.core.understanding import CHECKLIST
from elsa.ports.contributions import ChecklistAnswer, ContributionRecord, ContributionState

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ContributionRuleError",
    "InvalidTransitionError",
    "NotSubmittableError",
    "SubmitCheck",
    "check_submittable",
    "ensure_submittable",
    "validate_transition",
]


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
