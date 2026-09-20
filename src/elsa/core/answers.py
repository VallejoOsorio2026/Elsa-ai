"""Contrato de la respuesta fundamentada de ELSA.

Una respuesta de ELSA no es un texto: es un texto **más** el rastro de en qué
se apoya. Un ingeniero que va a intervenir un equipo necesita poder ir al
documento y comprobarlo, así que la cita no es un adorno del mensaje sino
parte del contrato.

Tres separaciones que el resto del bloque da por hechas:

- **Estado ≠ suficiencia.** `status` dice qué pudo hacer el sistema;
  `sufficiency` dice cuánto respaldo tenía. Un fallo del proveedor y una
  ausencia de evidencia son cosas distintas y no deben confundirse nunca
  (un `ERROR` no es un «no hay nada»).
- **Cita ≠ identificador interno.** `Citation` lleva lo que una persona usa
  para encontrar el pasaje —documento, versión, apartado, página— y **ningún
  UUID**. Los identificadores internos viven en `AnswerAudit`, que es para el
  log y para quien opera, no para la respuesta normal.
- **Marcador ≠ referencia.** El modelo cita `[E1]`; quien resuelve `E1`
  contra la procedencia real es el backend. El modelo nunca escribe el
  nombre de un documento y espera que se le crea.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "AnswerAudit",
    "AnswerStatus",
    "AnswerWarning",
    "Citation",
    "GroundedAnswer",
    "Sufficiency",
]


class AnswerStatus(StrEnum):
    """Qué pudo hacer el sistema con la pregunta."""

    ANSWERED = "answered"
    """Hubo evidencia, el modelo respondió y todas sus citas son reales."""

    PARTIAL = "partial"
    """Se responde, pero con respaldo incompleto. El aviso dice por qué."""

    NO_EVIDENCE = "no_evidence"
    """Nada autorizado que responda. **No es un fallo**: es una respuesta."""

    ERROR = "error"
    """Fallo técnico: el proveedor no respondió, expiró o devolvió vacío.

    Deliberadamente distinto de :attr:`NO_EVIDENCE`. Decirle a un ingeniero
    «no hay información» cuando en realidad se cayó el modelo es la peor de
    las dos mentiras posibles: le hace concluir que el dato no existe.
    """


class Sufficiency(StrEnum):
    """Cuánto respaldo tenía la respuesta, en términos cualitativos.

    **No sale de un umbral numérico.** ADR 0016 dejó cerrado que RRF no tiene
    umbral de abstención calibrado y que no se invente uno; esto se deriva de
    señales observables: si hubo evidencia, si hubo coincidencia literal del
    identificador, si canales independientes coincidieron, y si el modelo fue
    capaz de citar evidencia real.
    """

    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class AnswerWarning(StrEnum):
    """Por qué una respuesta no es plena. Se acumulan; no se excluyen."""

    NO_CITATIONS = "no_citations"
    """El modelo afirmó algo sin citar una sola evidencia."""

    INVALID_CITATION = "invalid_citation"
    """Citó un marcador que no se le entregó. La cita se descarta."""

    WEAK_EVIDENCE = "weak_evidence"
    """Un solo canal, sin coincidencia exacta ni refuerzo entre canales."""

    MODEL_DECLARED_INSUFFICIENT = "model_declared_insufficient"
    """El propio modelo declaró que la evidencia no responde la pregunta."""

    CONTEXT_TRUNCATED = "context_truncated"
    """Un pasaje no cabía entero en el presupuesto y se recortó."""

    EVIDENCE_DROPPED = "evidence_dropped"
    """Evidencia autorizada que **no cupo** en el presupuesto de contexto.

    No se levanta por descartar duplicados: repetir el mismo texto no aporta
    nada que citar, así que dejarlo fuera no pierde información y avisar de
    ello haría creer al operador que sí.
    """

    CAPABILITY_UNAVAILABLE = "capability_unavailable"
    """Una capacidad necesaria no respondió. **No es una ausencia de dato.**

    Lo que falló fue el camino hacia la fuente, no la fuente: decir «no hay
    información» aquí haría concluir que el dato no está, cuando lo cierto
    es que no se pudo mirar.
    """

    INVENTORY_UNAVAILABLE = "inventory_unavailable"
    """No había versión de inventario activa sobre la que consultar.

    Distinto de :attr:`CAPABILITY_UNAVAILABLE`: la fuente respondió, pero no
    tenía nada vigente con lo que contestar. Tampoco es una ausencia.
    """

    CODE_NOT_FOUND_IN_SOURCE = "code_not_found_in_source"
    """La fuente respondió correctamente y no devolvió el código pedido.

    **No significa que el material no exista.** Mientras la fuente no
    garantice que su ausencia es autoritativa, esto solo dice lo que se
    observó, no lo que pasa en la realidad.
    """

    COVERAGE_UNKNOWN = "coverage_unknown"
    """La cobertura del inventario **no se puede determinar**.

    Nadie ha declarado qué ámbito cubre el snapshot consultado, así que la
    respuesta se atribuye a lo que esa fuente devolvió y nunca al mundo
    (ADR 0021 §7.5, ADR 0023 §10.2.2).
    """

    COVERAGE_INCOMPLETE = "coverage_incomplete"
    """Se **demuestra** que falta un ámbito esperado, y es relevante.

    Distinto de :attr:`COVERAGE_UNKNOWN` y **no intercambiable con él**:
    afirmar incompletitud sin evidencia sería el mismo error en espejo.
    `UNKNOWN` no se presenta como `INCOMPLETE` (ADR 0021 §13.2).
    """


@dataclass(frozen=True, slots=True)
class Citation:
    """Una referencia verificable, resuelta por el backend.

    Todo lo que hay aquí sale de la procedencia real del chunk. El modelo no
    aporta ninguno de estos campos: solo el `marker`, y solo para señalar
    cuál de las evidencias que se le dieron está usando.
    """

    marker: str
    document_code: str
    document_title: str
    version_number: int
    domain: str
    asset_code: str | None = None
    section: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    reference: str = ""
    """Cita legible, tal y como la compone la procedencia del documento."""


@dataclass(frozen=True, slots=True)
class AnswerAudit:
    """Rastro técnico. **No es para el usuario normal.**

    Lleva los identificadores internos que la respuesta no debe enseñar, para
    que un operador pueda reconstruir qué se recuperó y qué se le mandó al
    modelo sin que esos UUID acaben en la pantalla de un ingeniero.
    """

    llm_called: bool
    model: str | None = None
    request_id: str | None = None
    evidence_retrieved: int = 0
    evidence_in_context: int = 0
    context_characters: int = 0
    chunk_ids: tuple[str, ...] = ()
    channels_queried: tuple[str, ...] = ()
    identifiers_detected: tuple[str, ...] = ()
    invalid_markers: tuple[str, ...] = ()
    error_code: str | None = None
    """`llm_unavailable`, `llm_timeout` o `llm_empty_response`."""


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    """Lo que devuelve el servicio de generación fundamentada."""

    status: AnswerStatus
    answer: str
    sufficiency: Sufficiency
    citations: tuple[Citation, ...] = ()
    warnings: tuple[AnswerWarning, ...] = ()
    audit: AnswerAudit = field(default_factory=lambda: AnswerAudit(llm_called=False))

    @property
    def is_grounded(self) -> bool:
        """Hay texto y al menos una cita real que lo respalde."""
        return bool(self.answer.strip()) and bool(self.citations)

    def has(self, warning: AnswerWarning) -> bool:
        return warning in self.warnings


def order_warnings(warnings: Sequence[AnswerWarning]) -> tuple[AnswerWarning, ...]:
    """Avisos sin repetir y en orden estable, para que dos corridas coincidan."""
    seen: list[AnswerWarning] = []
    for warning in AnswerWarning:
        if warning in warnings and warning not in seen:
            seen.append(warning)
    return tuple(seen)
