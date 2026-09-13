"""Generación fundamentada: pregunta autorizada → evidencia → respuesta citable.

    pregunta + alcances → recuperación híbrida → contexto → LLM → verificación

El orden de esa línea es el contrato de seguridad del bloque y no es
negociable. La autorización y la recuperación ocurren **antes** de que exista
cualquier llamada al modelo, así que no hay ningún camino por el que el LLM
pueda influir en qué se recupera: recibe un contexto ya cerrado y su salida no
vuelve a entrar. Sin alcances no se pregunta a nadie, y sin evidencia tampoco
se llama al proveedor — abstenerse no cuesta una llamada.

La otra mitad del contrato es la de después: lo que el modelo devuelve no se
publica tal cual. Se resuelven sus marcadores contra la procedencia real, se
descarta lo que no corresponda a una evidencia entregada, y el estado final lo
decide este servicio a partir de hechos observables, nunca el modelo.
"""

import asyncio
import logging
from collections.abc import Sequence

from elsa.core.answers import (
    AnswerAudit,
    AnswerStatus,
    AnswerWarning,
    GroundedAnswer,
    Sufficiency,
    order_warnings,
)
from elsa.core.authorization import Scope
from elsa.core.context_builder import (
    DEFAULT_BUDGET_CHARS,
    DEFAULT_MAX_ITEMS,
    BuiltContext,
    build_context,
)
from elsa.core.generation_policy import build_messages
from elsa.core.grounding import (
    GroundingReport,
    check_grounding,
    citation_from,
    visible_answer,
)
from elsa.ports.evidence import EvidenceRetrievalPort, EvidenceSet, EvidenceStrength
from elsa.ports.llm import LLMPort, LLMUnavailableError

_logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_TIMEOUT_SECONDS", "GroundedGenerationService"]

DEFAULT_TIMEOUT_SECONDS = 30.0

_NO_EVIDENCE_MESSAGE = (
    "No encontré nada en la documentación publicada que tengas autorizada para "
    "responder eso. Eso no significa que el dato no exista en el equipo: significa "
    "que no está escrito en lo que puedo consultar."
)
_ERROR_MESSAGE = (
    "No pude redactar la respuesta porque el modelo de lenguaje no respondió. "
    "Es un fallo técnico, no una ausencia de información: vuelve a intentarlo. "
    "Los pasajes que sí encontré quedan citados abajo para que los consultes "
    "directamente."
)
_ERROR_MESSAGE_WITHOUT_EVIDENCE = (
    "No pude redactar la respuesta porque el modelo de lenguaje no respondió. "
    "Es un fallo técnico, no una ausencia de información: vuelve a intentarlo."
)


class GroundedGenerationService:
    """Orquesta recuperación, contexto, generación y verificación."""

    def __init__(
        self,
        *,
        retrieval: EvidenceRetrievalPort,
        llm: LLMPort,
        budget_chars: int = DEFAULT_BUDGET_CHARS,
        max_evidence: int = DEFAULT_MAX_ITEMS,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_tokens: int = 1024,
    ) -> None:
        self._retrieval = retrieval
        self._llm = llm
        self._budget_chars = budget_chars
        self._max_evidence = max_evidence
        self._timeout_seconds = timeout_seconds
        self._max_tokens = max_tokens

    async def answer(
        self,
        *,
        question: str,
        scopes: Sequence[Scope],
        request_id: str | None = None,
    ) -> GroundedAnswer:
        """Responde con evidencia autorizada, o declara por qué no puede.

        `scopes` es obligatorio y sin valor por defecto, igual que en la
        recuperación: sin alcances no se abre nada. Lo que llega aquí es lo
        que el usuario ya tiene autorizado; este servicio no lo amplía, no lo
        reinterpreta y no se lo pregunta al modelo.

        `request_id` **lo pasa quien llama**, y la capa HTTP debe hacerlo:
        es la única forma de cruzar después una respuesta con sus líneas de
        log. No se lee del contexto de `elsa.logging` a propósito — ese módulo
        importa Starlette, y traerlo aquí metería el framework web en la capa
        de servicios, que es justo lo que la regla 1 y el ADR 0003 impiden.
        """
        evidence = await self._retrieval.search(
            query=question, scopes=scopes, limit=self._max_evidence
        )
        context = build_context(
            evidence, budget_chars=self._budget_chars, max_items=self._max_evidence
        )

        if context.is_empty:
            # Abstenerse no cuesta una llamada al proveedor. Además evita el
            # caso peor: un modelo al que se le pide responder sin material
            # tiende a rellenar, que es justo lo que no queremos.
            return self._no_evidence(evidence, context, request_id)

        messages = build_messages(question, context)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result = await self._llm.complete(messages, max_tokens=self._max_tokens)
        except TimeoutError:
            return self._failure("llm_timeout", evidence, context, request_id)
        except LLMUnavailableError:
            return self._failure("llm_unavailable", evidence, context, request_id)

        if not result.content.strip():
            return self._failure(
                "llm_empty_response", evidence, context, request_id, model=result.model
            )

        report = check_grounding(result.content, context)
        return self._verified(result.content, report, evidence, context, request_id, result.model)

    # ------------------------------------------------------------------
    # Composición del resultado
    # ------------------------------------------------------------------

    def _verified(
        self,
        raw: str,
        report: GroundingReport,
        evidence: EvidenceSet,
        context: BuiltContext,
        request_id: str | None,
        model: str,
    ) -> GroundedAnswer:
        warnings: list[AnswerWarning] = list(_context_warnings(context))
        if report.invalid_markers:
            warnings.append(AnswerWarning.INVALID_CITATION)
            _logger.warning(
                "model cited markers that were never supplied",
                extra={"invalid_markers": list(report.invalid_markers), "request_id": request_id},
            )
        if report.declared_insufficient:
            warnings.append(AnswerWarning.MODEL_DECLARED_INSUFFICIENT)
        if report.cited_nothing:
            warnings.append(AnswerWarning.NO_CITATIONS)
        if evidence.strength is EvidenceStrength.WEAK:
            warnings.append(AnswerWarning.WEAK_EVIDENCE)

        text = visible_answer(raw, report.invalid_markers)
        status = _status_for(report, evidence)
        return GroundedAnswer(
            status=status,
            answer=text or _NO_EVIDENCE_MESSAGE,
            sufficiency=_sufficiency_for(report, evidence, status),
            citations=report.citations,
            warnings=order_warnings(warnings),
            audit=_audit(
                evidence,
                context,
                request_id,
                llm_called=True,
                model=model,
                invalid_markers=report.invalid_markers,
            ),
        )

    def _no_evidence(
        self, evidence: EvidenceSet, context: BuiltContext, request_id: str | None
    ) -> GroundedAnswer:
        return GroundedAnswer(
            status=AnswerStatus.NO_EVIDENCE,
            answer=_NO_EVIDENCE_MESSAGE,
            sufficiency=Sufficiency.INSUFFICIENT,
            warnings=order_warnings(_context_warnings(context)),
            audit=_audit(evidence, context, request_id, llm_called=False),
        )

    def _failure(
        self,
        code: str,
        evidence: EvidenceSet,
        context: BuiltContext,
        request_id: str | None,
        *,
        model: str | None = None,
    ) -> GroundedAnswer:
        """Un fallo del proveedor es `ERROR`, jamás `NO_EVIDENCE`.

        La distinción no es cosmética: un ingeniero que lee «no hay
        información» concluye que el dato no está documentado y actúa en
        consecuencia. Si lo que pasó es que se cayó el modelo, esa conclusión
        es falsa y la tomó por culpa nuestra.
        """
        _logger.error("grounded generation failed", extra={"code": code, "request_id": request_id})
        # Con el modelo caído sigue habiendo algo que entregar: los pasajes
        # autorizados que ya se recuperaron. Entregarlos es lo que hace que el
        # sistema funcione parcialmente en vez de no funcionar (regla 9), y
        # además es lo que el mensaje promete: prometerlo sin cumplirlo sería
        # peor que no prometerlo.
        citations = tuple(citation_from(item) for item in context)
        return GroundedAnswer(
            status=AnswerStatus.ERROR,
            answer=_ERROR_MESSAGE if citations else _ERROR_MESSAGE_WITHOUT_EVIDENCE,
            citations=citations,
            sufficiency=Sufficiency.INSUFFICIENT,
            warnings=order_warnings(_context_warnings(context)),
            audit=_audit(
                evidence,
                context,
                request_id,
                llm_called=True,
                model=model,
                error_code=code,
            ),
        )


def _context_warnings(context: BuiltContext) -> tuple[AnswerWarning, ...]:
    warnings: list[AnswerWarning] = []
    if context.truncated:
        warnings.append(AnswerWarning.CONTEXT_TRUNCATED)
    if context.dropped:
        warnings.append(AnswerWarning.EVIDENCE_DROPPED)
    return tuple(warnings)


def _status_for(report: GroundingReport, evidence: EvidenceSet) -> AnswerStatus:
    """El estado lo decide el servicio, con hechos, no el modelo.

    `ANSWERED` exige las tres cosas a la vez: que el modelo no haya declarado
    insuficiencia, que haya citado al menos una evidencia real, y que no haya
    citado ninguna que no se le diera. Basta que falle una para que la
    respuesta se entregue marcada como parcial.
    """
    if evidence.is_empty:
        return AnswerStatus.NO_EVIDENCE
    if report.declared_insufficient and not report.citations:
        return AnswerStatus.NO_EVIDENCE
    if report.is_grounded and not report.declared_insufficient:
        return AnswerStatus.ANSWERED
    return AnswerStatus.PARTIAL


def _sufficiency_for(
    report: GroundingReport, evidence: EvidenceSet, status: AnswerStatus
) -> Sufficiency:
    """Suficiencia cualitativa a partir de señales observables.

    Las señales son las que ADR 0016 dejó disponibles: que exista evidencia,
    que hubiera coincidencia literal del identificador o acuerdo entre canales
    —eso es lo que resume `EvidenceStrength`—, y que el modelo haya sido capaz
    de citar evidencia real. **Ninguna puntuación de RRF entra aquí**: no está
    calibrada y fingir que lo está sería inventar el umbral que aquel ADR
    prohíbe expresamente.
    """
    if status is AnswerStatus.NO_EVIDENCE or status is AnswerStatus.ERROR:
        return Sufficiency.INSUFFICIENT
    if (
        status is AnswerStatus.ANSWERED
        and evidence.strength is EvidenceStrength.SUFFICIENT
        and report.citations
    ):
        return Sufficiency.SUFFICIENT
    return Sufficiency.PARTIAL


def _audit(
    evidence: EvidenceSet,
    context: BuiltContext,
    request_id: str | None,
    *,
    llm_called: bool,
    model: str | None = None,
    invalid_markers: Sequence[str] = (),
    error_code: str | None = None,
) -> AnswerAudit:
    return AnswerAudit(
        llm_called=llm_called,
        model=model,
        request_id=request_id,
        evidence_retrieved=len(evidence),
        evidence_in_context=len(context),
        context_characters=context.characters,
        chunk_ids=context.chunk_ids(),
        channels_queried=tuple(channel.value for channel in evidence.channels_queried),
        identifiers_detected=evidence.identifiers_detected,
        invalid_markers=tuple(invalid_markers),
        error_code=error_code,
    )
