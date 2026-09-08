"""Búsqueda literal sobre el conocimiento publicado.

Esto **no es RAG y no hay modelo de lenguaje**. Es una búsqueda por
coincidencia de términos sobre el BOM y el AMEF ya publicados, escrita para
que el piloto pueda demostrar el recorrido completo —pregunta, permiso,
recuperación, evidencia— sin fingir una capacidad que todavía no existe.

Dos propiedades la hacen honesta:

- **Es explicable.** Cada resultado dice *qué* términos coincidieron. Quien
  lee la respuesta puede juzgar si la coincidencia significa algo, en vez de
  confiar en una puntuación opaca.
- **No infiere.** Si ningún término coincide, no hay resultado. El sistema
  dice que no encontró nada; no aproxima, no parafrasea y no completa.

Cuando llegue el motor real, esta capa se sustituye por el puerto
correspondiente y la interfaz no cambia: lo que devuelve ya son evidencias
con su procedencia.
"""

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from elsa.core.normalization import canonical_sap_code, normalize_key

__all__ = [
    "MIN_TERM_LENGTH",
    "RELATIVE_FLOOR",
    "Candidate",
    "Match",
    "Query",
    "parse_query",
    "search",
]

MIN_TERM_LENGTH = 3
"""Longitud mínima de un término buscable.

Por debajo de tres letras casi todo coincide con casi todo y el resultado
deja de significar nada.
"""

RELATIVE_FLOOR = 0.4
"""Fracción de la mejor puntuación por debajo de la cual se descarta.

Un resultado que puntúa menos de un 40 % del mejor no es una alternativa:
es ruido que comparte una palabra genérica. Devolverlo al lado del bueno
obliga a quien lee a descartarlo, y en una lista de repuestos eso es
trabajo —y riesgo— que el sistema puede ahorrarle.

El umbral es relativo, no absoluto: cuando todos los candidatos puntúan
parecido —porque la pregunta es genérica— ninguno queda por debajo del 40 %
del mejor y se devuelven todos. Solo recorta cuando hay un ganador claro.
"""

# Palabras que aparecen en casi cualquier pregunta y no discriminan nada.
# La lista es corta a propósito: filtrar de más esconde intención.
_STOPWORDS = frozenset(
    """
    cual cuales cuando cuanto cuantos cuanta cuantas como donde porque que quien
    para por con sin del las los una unos unas the and dame dime muestra muestrame
    busca buscar necesito quiero tiene tienen hay esta estan son sobre equipo
    maquina informacion datos favor puede puedes
    """.split()
)

# Un código de material: alfanumérico, con al menos un dígito y longitud
# suficiente para no confundirse con una palabra corta.
_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9\-_/]{3,}$")
_TOKEN_PATTERN = re.compile(r"[a-z0-9\-_/]+")


@dataclass(frozen=True, slots=True)
class Query:
    """Una pregunta descompuesta en lo que realmente se puede buscar."""

    raw: str
    terms: tuple[str, ...]
    """Términos normalizados, sin acentos, sin palabras vacías."""

    codes: tuple[str, ...]
    """Términos que tienen forma de código de material, en forma canónica."""

    @property
    def is_searchable(self) -> bool:
        return bool(self.terms or self.codes)


@dataclass(frozen=True, slots=True)
class Candidate[T]:
    """Un registro publicado, reducido a lo que se puede buscar en él.

    ``payload`` viaja sin tocarse: quien llama recupera su propio registro
    sin que esta capa tenga que conocer su forma.
    """

    payload: T
    text: str
    """Texto ya normalizado donde se buscan los términos."""

    code: str | None = None
    """Código de material en forma canónica, si el registro tiene uno."""


@dataclass(frozen=True, slots=True)
class Match[T]:
    """Un candidato que coincidió, con la razón de la coincidencia."""

    payload: T
    score: float
    matched_terms: tuple[str, ...]
    matched_code: str | None = None
    matched_phrase: str | None = None
    """La secuencia más larga de términos de la pregunta hallada tal cual.

    Es lo que separa «rodamiento rodillo prensa inferior» de un renglón que
    solo comparte «prensa»: no coinciden las mismas palabras, coinciden en
    el mismo orden.
    """

    @property
    def is_exact_code(self) -> bool:
        """Cierto si la coincidencia fue por código de material.

        Un código coincidente es una identificación, no un parecido: merece
        tratarse distinto de un término suelto que aparece en una
        descripción.
        """
        return self.matched_code is not None


def parse_query(text: str) -> Query:
    """Descompone la pregunta en términos y códigos buscables."""
    normalized = normalize_key(text) or ""
    tokens = _TOKEN_PATTERN.findall(normalized)

    terms: list[str] = []
    codes: list[str] = []
    for token in tokens:
        if _looks_like_code(token):
            canonical = canonical_sap_code(token.upper())
            if canonical is not None and canonical not in codes:
                codes.append(canonical)
            continue
        if len(token) < MIN_TERM_LENGTH or token in _STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)

    return Query(raw=text, terms=tuple(terms), codes=tuple(codes))


def _looks_like_code(token: str) -> bool:
    """Un token es código si mezcla dígitos y tiene forma de referencia."""
    if not _CODE_PATTERN.match(token):
        return False
    has_digit = any(char.isdigit() for char in token)
    if not has_digit:
        return False
    # Una palabra corriente con un número pegado (`prensa2`) no es un código;
    # se exige o bien todo dígitos, o bien un separador, o bien mayoría de
    # dígitos.
    if token.isdigit():
        return True
    if any(sep in token for sep in "-_/"):
        return True
    digits = sum(char.isdigit() for char in token)
    return digits * 2 >= len(token)


def _term_weights(
    terms: Sequence[str], candidates: Sequence[Candidate[object]]
) -> dict[str, float]:
    """Peso de cada término por lo específico que es en este conjunto.

    Un término que aparece en casi todos los registros no distingue nada:
    «prensa» está en el nombre y en el subsistema de media máquina, mientras
    que «rodamiento» señala un renglón concreto. Es la fórmula clásica de
    frecuencia inversa, calculada sobre los candidatos que hay delante —no
    hay modelo, ni corpus externo, ni entrenamiento.

    Un término presente en **todos** los candidatos pesa exactamente cero:
    no aporta información para elegir entre ellos.
    """
    total = len(candidates)
    weights: dict[str, float] = {}
    for term in terms:
        frequency = sum(1 for candidate in candidates if term in candidate.text)
        weights[term] = math.log(total / frequency) if frequency and total else 0.0

    # Si ningún término discrimina —caso de un solo candidato, o de una
    # pregunta cuyos términos están en todos— se vuelve a contar términos,
    # que al menos ordena por cobertura.
    if not any(weights.values()):
        return dict.fromkeys(terms, 1.0)
    return weights


def _longest_phrase(terms: Sequence[str], text: str) -> tuple[int, str | None]:
    """Secuencia contigua más larga de términos de la pregunta dentro del texto.

    Se buscan las secuencias en el orden en que se escribieron, de la más
    larga a la más corta, y se devuelve la primera que aparezca literalmente.
    """
    for length in range(len(terms), 1, -1):
        for start in range(len(terms) - length + 1):
            phrase = " ".join(terms[start : start + length])
            if phrase in text:
                return length, phrase
    return 0, None


def search[T](
    query: Query,
    candidates: Iterable[Candidate[T]],
    *,
    limit: int = 10,
) -> tuple[Match[T], ...]:
    """Devuelve los candidatos que coinciden, de mejor a peor.

    La puntuación combina tres señales, todas deterministas y explicables:

    1. **Coincidencia de código.** Identifica el registro en vez de
       parecerse a él, así que domina sobre cualquier combinación de
       términos.
    2. **Especificidad de los términos coincidentes.** Ver
       :func:`_term_weights`.
    3. **Frase.** Términos que aparecen contiguos y en el mismo orden que en
       la pregunta pesan más que los mismos términos dispersos.

    Después se descarta lo que puntúe por debajo de :data:`RELATIVE_FLOOR`
    respecto del mejor resultado. Una coincidencia exacta de código nunca se
    descarta.
    """
    if not query.is_searchable:
        return ()

    pool = tuple(candidates)
    weights = _term_weights(query.terms, pool)
    total_weight = sum(weights.values())
    top_weight = max(weights.values(), default=1.0)

    matches: list[Match[T]] = []
    for candidate in pool:
        has_code = candidate.code is not None and candidate.code in query.codes
        matched_code = candidate.code if has_code else None
        matched_terms = tuple(term for term in query.terms if term in candidate.text)
        if matched_code is None and not matched_terms:
            continue

        score = sum(weights[term] for term in matched_terms)

        phrase_length, phrase = _longest_phrase(query.terms, candidate.text)
        if phrase_length >= 2:
            score += (phrase_length - 1) * top_weight

        # El código suma por encima de cualquier combinación de términos, de
        # forma que un acierto exacto nunca queda por debajo de un parecido.
        if matched_code is not None:
            score += total_weight + (len(query.terms) + 1) * top_weight

        matches.append(
            Match(
                payload=candidate.payload,
                score=score,
                matched_terms=matched_terms,
                matched_code=matched_code,
                matched_phrase=phrase if phrase_length >= 2 else None,
            )
        )

    if not matches:
        return ()

    matches.sort(key=lambda match: (-match.score, -len(match.matched_terms)))
    floor = matches[0].score * RELATIVE_FLOOR
    kept = [match for match in matches if match.is_exact_code or match.score >= floor]
    return tuple(kept[:limit])


def build_text(*parts: object) -> str:
    """Une los campos buscables de un registro en un texto normalizado."""
    pieces: list[str] = []
    for part in parts:
        key = normalize_key(part)
        if key:
            pieces.append(key)
    return " ".join(pieces)


def candidates_from[T](
    records: Sequence[T],
    *,
    text_fields: Sequence[str],
    code_field: str | None = None,
) -> tuple[Candidate[T], ...]:
    """Construye candidatos leyendo atributos por nombre."""
    built: list[Candidate[T]] = []
    for record in records:
        text = build_text(*(getattr(record, field, None) for field in text_fields))
        code = None if code_field is None else canonical_sap_code(getattr(record, code_field, None))
        built.append(Candidate(payload=record, text=text, code=code))
    return tuple(built)
