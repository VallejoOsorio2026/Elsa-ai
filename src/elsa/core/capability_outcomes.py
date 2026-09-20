"""Cómo se lee el resultado de una capacidad, y qué **no** puede concluirse.

Esto **no es** la integración con Materiales: no hay aquí HTTP, ni SQL, ni
JWT, ni inventario, ni representación de un código SAP. Es la política del
**consumidor**: dado un resultado ya obtenido, qué estado de respuesta
permite emitir y con qué palabras.

La regla que sostiene el módulo entero es una sola:

    que una fuente no devuelva algo no significa que ese algo no exista.

Suena obvia escrita, y es exactamente la que se pierde en la práctica,
porque los tres motivos por los que una consulta vuelve vacía se parecen
mucho al mirarlos desde el final:

- **la fuente no respondió** — fallo técnico;
- **la fuente no tenía nada vigente que consultar** — tampoco miró;
- **la fuente respondió y no devolvió el código** — miró, y no estaba
  *en lo que miró*.

Solo el tercero es una ausencia, y aun así es una ausencia **no
autoritativa** mientras M8 siga abierto (ADR 0020 §12, ADR 0021 §8). Los
otros dos no son ausencias en absoluto: decirle «no hay información» a un
ingeniero que va a intervenir un equipo le hace concluir que el dato no
está, y actuar en consecuencia. Esa conclusión sería nuestra, no suya.

Los valores de `CapabilityCallStatus` y `CapabilityOutcome` reproducen la
semántica que ADR 0021 §5 y §6 ya fijaron para el contrato con Materiales.
**Aquí son la lectura del consumidor**, no una implementación de la fachada
ni un adaptador: cuando la fachada exista, traducirá su respuesta a estos
valores, y esta política seguirá sin saber de dónde vinieron.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from elsa.core.answers import AnswerStatus, AnswerWarning, order_warnings

__all__ = [
    "CAPABILITY_UNAVAILABLE_MESSAGE",
    "INVENTORY_UNAVAILABLE_MESSAGE",
    "SOURCE_DID_NOT_RETURN_MESSAGE",
    "UNBOUNDED_CLAIM_REFUSAL_MESSAGE",
    "CapabilityCallStatus",
    "CapabilityOutcome",
    "InterpretedOutcome",
    "InventoryLookupResult",
    "UncomposableOutcomeError",
    "asserts_complete_coverage",
    "asserts_nonexistence",
    "interpret_inventory_lookup",
]


class CapabilityCallStatus(StrEnum):
    """Si la fuente pudo responder. Semántica de ADR 0021 §5."""

    OK = "ok"
    """Respondió sobre una versión de inventario activa."""

    NO_ACTIVE_INVENTORY = "no_active_inventory"
    """No hay versión activa. **No es ausencia**: no hubo dónde mirar."""

    UNAVAILABLE = "unavailable"
    """Fallo técnico: red, tiempo agotado, error del servidor."""

    REJECTED = "rejected"
    """Autorización. Se resuelve antes de componer; no llega hasta aquí."""


class CapabilityOutcome(StrEnum):
    """Qué hizo la fuente con el código pedido. Semántica de ADR 0021 §6."""

    MATCHED = "matched"
    """Lo devolvió."""

    NOT_RETURNED = "not_returned"
    """Respondió correctamente y **no** lo devolvió.

    Se llama `NOT_RETURNED` y no `NOT_FOUND` a propósito: «no encontrado»
    sugiere que se buscó en todas partes. Esto dice lo que ocurrió.
    """


@dataclass(frozen=True, slots=True)
class InventoryLookupResult:
    """Resultado de una consulta de inventario, tal como llega al consumidor."""

    call_status: CapabilityCallStatus
    outcome: CapabilityOutcome | None = None
    absence_is_authoritative: bool = False
    """Si la fuente **garantiza** que lo que no devuelve no existe.

    Falso siempre mientras M8 siga abierto. Ninguna fuente lo garantiza hoy.
    """


@dataclass(frozen=True, slots=True)
class InterpretedOutcome:
    """Lo que la política autoriza a emitir a partir de un resultado."""

    status: AnswerStatus
    warnings: tuple[AnswerWarning, ...]
    message: str


class UncomposableOutcomeError(Exception):
    """El resultado no puede componerse como respuesta, y no se adivina.

    Se prefiere fallar a inventar un estado: un resultado que esta política
    no sabe leer no puede convertirse en un `NO_EVIDENCE` por descarte, que
    es justo el error que el módulo existe para impedir.
    """


# ----------------------------------------------------------------------
# Redacción segura
# ----------------------------------------------------------------------

SOURCE_DID_NOT_RETURN_MESSAGE = (
    "La fuente consultada no devolvió el material solicitado. Este resultado no "
    "permite concluir que el material no exista: solo dice lo que esa fuente "
    "devolvió."
)

CAPABILITY_UNAVAILABLE_MESSAGE = (
    "No pude consultar el inventario porque la fuente no respondió. Es un fallo "
    "técnico, no una ausencia de información."
)

INVENTORY_UNAVAILABLE_MESSAGE = (
    "La fuente de inventario no tiene una versión activa que consultar, así que "
    "la consulta no llegó a hacerse. No es una ausencia de información."
)

_ANSWERED_MESSAGE = "La fuente consultada devolvió el material solicitado."

UNBOUNDED_CLAIM_REFUSAL_MESSAGE = (
    "Consulté el inventario cargado en Materiales y puedo hablar únicamente de lo "
    "que esa fuente devolvió en esta consulta. No puedo concluir nada sobre el "
    "resto de la empresa: el alcance que ese inventario cubre no está declarado."
)

# Afirmaciones de inexistencia como hecho. La guarda busca **estas**, no las
# palabras sueltas que las componen: prohibir «existe» dejaría sin forma de
# explicar honestamente una ausencia no autoritativa.
_DENIAL_PATTERNS = (
    r"\b(?:el|ese|este|dicho)?\s*material\s+no\s+existe\b",
    r"\bno\s+existe\s+(?:el|ese|este|dicho)\s+\w+",
    r"\bno\s+est[aá]\s+creado\b",
    r"\bno\s+est[aá]\s+registrado\s+en\s+sap\b",
    r"\bno\s+figura\s+en\s+sap\b",
    r"\bno\s+existe\s+en\s+sap\b",
)

# Marcas de que la frase habla de lo que **no se puede concluir**, no de un
# hecho. Una frase con marca de salvedad no es una afirmación.
_HEDGE_PATTERNS = (
    r"\bno\s+permite\s+concluir\b",
    r"\bno\s+se\s+puede\s+concluir\b",
    r"\bno\s+significa\s+que\b",
    r"\bno\s+implica\s+que\b",
    r"\bno\s+quiere\s+decir\s+que\b",
)

_DENIALS = tuple(re.compile(pattern) for pattern in _DENIAL_PATTERNS)
_HEDGES = tuple(re.compile(pattern) for pattern in _HEDGE_PATTERNS)
_SENTENCE_SPLIT = re.compile(r"[.;\n]+")


def asserts_nonexistence(text: str) -> bool:
    """Si el texto afirma, como hecho, que algo no existe.

    Se mira **frase a frase**: una salvedad al final no legitima una
    afirmación anterior, y una afirmación al final no queda disculpada por
    una salvedad previa.

    Lo que NO hace, a propósito: prohibir vocabulario. «Este resultado no
    permite concluir si el material existe» contiene «existe» y es
    exactamente lo que queremos poder decir.
    """
    for sentence in _SENTENCE_SPLIT.split(text.lower()):
        if any(hedge.search(sentence) for hedge in _HEDGES):
            continue
        if any(denial.search(sentence) for denial in _DENIALS):
            return True
    return False


# Afirmaciones que cuantifican sobre un universo cuyo alcance nadie declaró
# (Clase 2 de ADR 0023 §9). Se buscan **frases**, no palabras: prohibir
# «todos» o «ningún» dejaría sin forma de acotar una respuesta a su fuente.
_COVERAGE_CLAIM_PATTERNS = (
    # «no hay / no tenemos / no queda … en ningún almacén»
    r"\bno\s+(?:hay|haya|tenemos|queda|quedan|existen?)\b[^.;]*?\ben\s+ning[uú]n(?:a)?\s+"
    r"(?:almac[eé]n|almacenes|bodega|dep[oó]sito|sede|centro|planta|parte|lado|sitio)\b",
    # «el material no está en ninguna bodega»
    r"\bno\s+est[aá]\s+(?:en\s+)?ning[uú]n(?:a)?\s+"
    r"(?:almac[eé]n|bodega|dep[oó]sito|sede|centro|planta)\b",
    # «estos son todos los materiales que tenemos»
    r"\btodos\s+los\s+(?:materiales|c[oó]digos|repuestos|art[ií]culos|[ií]tems)\b"
    r"[^.;]*?\b(?:que\s+(?:tenemos|hay|existen|manejamos)|"
    r"de\s+la\s+(?:empresa|compa[ñn][ií]a|planta)|del\s+inventario)\b",
    # «en todos los almacenes», «en toda la empresa»
    r"\ben\s+tod(?:os|as)\s+(?:los|las)\s+"
    r"(?:almacenes|bodegas|dep[oó]sitos|sedes|centros|plantas)\b",
    r"\ben\s+tod[ao]\s+la\s+(?:empresa|compa[ñn][ií]a|planta|organizaci[oó]n)\b",
    # «el inventario completo», «la cobertura es total»
    r"\binventario\s+(?:completo|total|[ií]ntegro)\b",
    r"\bcobertura\s+(?:es\s+)?(?:completa|total)\b",
    # «no existe en el inventario de la empresa»
    r"\bno\s+existe\s+en\s+el\s+inventario\b",
)

# Marcas de que la frase habla del **desconocimiento** del alcance, que es
# justo lo que ELSA debe poder decir en voz alta.
_COVERAGE_HEDGE_PATTERNS = (
    r"\bno\s+puedo\s+(?:afirmar|concluir|saber|decir|hablar)\b",
    r"\bno\s+s[eé]\s+(?:qu[eé]|si|cu[aá]l)\b",
    r"\bse\s+desconoce\b",
    r"\bno\s+est[aá]\s+declarad[oa]\b",
    r"\bnadie\s+(?:ha\s+)?demostr",
)

_COVERAGE_CLAIMS = tuple(re.compile(pattern) for pattern in _COVERAGE_CLAIM_PATTERNS)
_COVERAGE_HEDGES = _HEDGES + tuple(re.compile(pattern) for pattern in _COVERAGE_HEDGE_PATTERNS)


def asserts_complete_coverage(text: str) -> bool:
    """Si el texto afirma algo que solo sería cierto con cobertura completa.

    Es a la cobertura lo que :func:`asserts_nonexistence` es a la
    inexistencia, y se construye igual: frase a frase, con salvedades, y
    **sin prohibir vocabulario**. «Estos son todos los elementos del BOM
    publicado» es una afirmación acotada a una fuente propia de ELSA y debe
    seguir siendo decible; «estos son todos los materiales que tenemos»
    cuantifica sobre un universo que nadie ha delimitado y no.

    Una atribución **no** es una salvedad: «según el inventario cargado, no
    hay en ningún almacén» sigue siendo una afirmación de Clase 2, porque
    ninguna acotación vuelve verdadera una afirmación universal sobre un
    universo desconocido (ADR 0023 §9).
    """
    for sentence in _SENTENCE_SPLIT.split(text.lower()):
        if any(hedge.search(sentence) for hedge in _COVERAGE_HEDGES):
            continue
        if any(claim.search(sentence) for claim in _COVERAGE_CLAIMS):
            return True
    return False


# ----------------------------------------------------------------------
# La política
# ----------------------------------------------------------------------


def interpret_inventory_lookup(
    result: InventoryLookupResult, *, other_facts_available: bool
) -> InterpretedOutcome:
    """Traduce un resultado de inventario en estado, avisos y mensaje.

    `other_facts_available` dice si el resto de la respuesta se sostiene sin
    esta capacidad. Es lo que separa degradar de fallar: con otros hechos
    útiles la respuesta es parcial; sin ellos, no hay respuesta que dar.

    **No se crea ningún `AnswerStatus` nuevo** (ADR 0017): los cuatro
    existentes bastan.
    """
    if result.call_status is CapabilityCallStatus.REJECTED:
        raise UncomposableOutcomeError(
            "an authorisation rejection is resolved by the trust chain, never composed"
        )

    if result.call_status is CapabilityCallStatus.UNAVAILABLE:
        return _degraded(
            AnswerWarning.CAPABILITY_UNAVAILABLE,
            CAPABILITY_UNAVAILABLE_MESSAGE,
            other_facts_available=other_facts_available,
        )

    if result.call_status is CapabilityCallStatus.NO_ACTIVE_INVENTORY:
        return _degraded(
            AnswerWarning.INVENTORY_UNAVAILABLE,
            INVENTORY_UNAVAILABLE_MESSAGE,
            other_facts_available=other_facts_available,
        )

    if result.outcome is CapabilityOutcome.MATCHED:
        # La degradación por vigencia y por cobertura (ADR 0021 §11 y §12)
        # no vive aquí: depende del plan, no del resultado, y llega con su
        # propio paso.
        return InterpretedOutcome(
            status=AnswerStatus.ANSWERED, warnings=(), message=_ANSWERED_MESSAGE
        )

    if result.outcome is CapabilityOutcome.NOT_RETURNED:
        if result.absence_is_authoritative:
            raise UncomposableOutcomeError(
                "an authoritative absence cannot be emitted while M8 remains open"
            )
        # Sin nada más que responder es `NO_EVIDENCE`; junto a otros hechos
        # resueltos, la respuesta existe y solo le falta esta parte.
        status = AnswerStatus.PARTIAL if other_facts_available else AnswerStatus.NO_EVIDENCE
        return InterpretedOutcome(
            status=status,
            warnings=order_warnings([AnswerWarning.CODE_NOT_FOUND_IN_SOURCE]),
            message=SOURCE_DID_NOT_RETURN_MESSAGE,
        )

    raise UncomposableOutcomeError("a successful call must carry an outcome")


def _degraded(
    warning: AnswerWarning, message: str, *, other_facts_available: bool
) -> InterpretedOutcome:
    """Ni `NO_EVIDENCE` ni silencio: no se pudo mirar, y eso se dice."""
    status = AnswerStatus.PARTIAL if other_facts_available else AnswerStatus.ERROR
    return InterpretedOutcome(status=status, warnings=order_warnings([warning]), message=message)
