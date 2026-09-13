"""Verificación estructural de que una respuesta se apoya en su evidencia.

Lo que se puede comprobar sin entender el texto es **de dónde dice apoyarse**,
y eso basta para impedir el fallo más caro: que el modelo invente un documento,
una página o un apartado. El modelo no escribe referencias, escribe marcadores;
aquí se resuelven contra la procedencia real y lo que no corresponde a una
evidencia entregada se descarta.

Lo que este módulo **no** hace, y conviene que quede dicho: no juzga si el
texto es cierto ni si la evidencia realmente responde la pregunta. Eso exige
entender el contenido, y fingir que una comprobación estructural lo cubre
sería peor que no tenerla.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from elsa.core.answers import Citation
from elsa.core.context_builder import BuiltContext, ContextItem

__all__ = [
    "ABSTENTION_SENTINEL",
    "GroundingReport",
    "check_grounding",
    "citation_from",
    "extract_markers",
    "visible_answer",
]

ABSTENTION_SENTINEL = "SIN_EVIDENCIA_SUFICIENTE"
"""Lo que el modelo escribe cuando la evidencia no responde la pregunta.

Un centinela literal y no una frase libre: distinguir «no puedo responder» de
«no citó nada» por la redacción sería adivinar, y las dos cosas exigen
tratamientos distintos.
"""

_MARKER = re.compile(r"\[(E\d+)\]")


def extract_markers(text: str) -> tuple[str, ...]:
    """Marcadores citados, sin repetir y en orden de aparición."""
    seen: list[str] = []
    for match in _MARKER.finditer(text):
        marker = match.group(1)
        if marker not in seen:
            seen.append(marker)
    return tuple(seen)


def citation_from(item: ContextItem) -> Citation:
    """Convierte una pieza del contexto en una cita verificable.

    Todos los campos salen de la procedencia. **Ningún UUID**: lo que va aquí
    es lo que una persona usa para abrir el documento y comprobarlo.
    """
    provenance = item.evidence.provenance
    document = provenance.document
    section = provenance.section
    label: str | None = None
    if section is not None:
        label = section.title
        if section.number_label:
            label = f"{section.number_label} {section.title}".strip()
    return Citation(
        marker=item.marker,
        document_code=document.code,
        document_title=document.title,
        version_number=provenance.version.version_number,
        domain=document.domain,
        asset_code=document.asset_code,
        section=label,
        page_start=provenance.chunk.page_start,
        page_end=provenance.chunk.page_end,
        reference=provenance.citation(),
    )


@dataclass(frozen=True, slots=True)
class GroundingReport:
    """Qué citó el modelo, qué de eso era real y qué se inventó."""

    citations: tuple[Citation, ...]
    invalid_markers: tuple[str, ...]
    declared_insufficient: bool
    has_text: bool

    @property
    def is_grounded(self) -> bool:
        return self.has_text and bool(self.citations) and not self.invalid_markers

    @property
    def cited_nothing(self) -> bool:
        return self.has_text and not self.citations and not self.declared_insufficient


def check_grounding(answer: str, context: BuiltContext) -> GroundingReport:
    """Resuelve los marcadores de la respuesta contra el contexto entregado.

    Un marcador que no se entregó no se corrige ni se aproxima al más
    parecido: se descarta y se reporta. Aproximarlo produciría exactamente la
    cita falsa que esto existe para impedir.
    """
    by_marker = context.by_marker()
    citations: list[Citation] = []
    invalid: list[str] = []
    for marker in extract_markers(answer):
        item = by_marker.get(marker)
        if item is None:
            invalid.append(marker)
        else:
            citations.append(citation_from(item))
    return GroundingReport(
        citations=tuple(citations),
        invalid_markers=tuple(invalid),
        declared_insufficient=ABSTENTION_SENTINEL in answer,
        has_text=bool(_strip_sentinel(answer).strip()),
    )


_SENTINEL_RUN = re.compile(re.escape(ABSTENTION_SENTINEL) + r"\s*[:;,.\-]*\s*")


def _strip_sentinel(answer: str) -> str:
    """Quita el centinela y la puntuación que lo introducía.

    Sin lo segundo quedarían dos puntos huérfanos donde estaba el token, que
    es peor que no haberlo quitado: parece un error de redacción nuestro.
    """
    return _SENTINEL_RUN.sub("", answer)


def visible_answer(answer: str, invalid_markers: Sequence[str]) -> str:
    """El texto que se muestra, limpio de lo que es protocolo interno.

    Se quitan dos cosas, por motivos distintos:

    - **Los marcadores inválidos.** Dejarlos enseñaría al ingeniero una cita
      que no existe; quitarlos es lo único que mantiene la promesa de que toda
      referencia visible es verificable.
    - **El centinela de insuficiencia.** `SIN_EVIDENCIA_SUFICIENTE` es cómo el
      modelo nos avisa, no cómo se le habla a una persona. La señal no se
      pierde: viaja en `status` y en el aviso correspondiente.

    En ninguno de los dos casos se oculta que pasó: el aviso va en `warnings`.
    """
    text = answer
    for marker in invalid_markers:
        text = text.replace(f"[{marker}]", "")
    text = _strip_sentinel(text)
    text = re.sub(r"^[\s:;.,-]+", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()
