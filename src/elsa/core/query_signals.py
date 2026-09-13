"""Detección determinista de señales exactas en una consulta.

**No interviene ningún modelo.** Un código SAP, una referencia de rodamiento o
un número de norma se reconocen con una regla, no con una predicción: si un
identificador se resolviera con un LLM, la respuesta a «¿qué es el SAP-4471?»
dependería de la temperatura del muestreo.

Por qué hace falta separarlos del canal léxico: la configuración `spanish` de
PostgreSQL **parte los códigos**. `to_tsvector('spanish', 'SAP-4471')` produce
`'sap'` y `'-4471'`, de modo que la búsqueda de texto encontraría cualquier
chunk que hable de SAP y cualquiera que mencione 4471, mezclados. Para un
identificador eso no es recuperación, es ruido: hay que buscarlo literal.
"""

import re
from dataclasses import dataclass

__all__ = ["QuerySignals", "detect_signals"]

# Un candidato a identificador: empieza por alfanumérico y admite los
# separadores habituales de códigos técnicos. La decisión de si **es** un
# identificador la toma `_is_identifier`, no esta expresión.
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_MIN_LENGTH = 3


def _is_identifier(token: str) -> bool:
    """Un identificador mezcla letras y dígitos; una palabra o una cifra, no.

    `SAP-4471`, `P-200`, `6205-2RS` e `ISO-4406` lo son. `rodamiento` no lo es
    —no tiene dígitos— y `500` tampoco —es una cantidad, y tratarla como código
    haría que «cada 500 horas» arrastrara cualquier chunk con un 500.
    """
    if len(token) < _MIN_LENGTH:
        return False
    stripped = token.strip("._/-")
    if len(stripped) < _MIN_LENGTH:
        return False
    return any(c.isdigit() for c in stripped) and any(c.isalpha() for c in stripped)


@dataclass(frozen=True, slots=True)
class QuerySignals:
    """Lo que se pudo reconocer de la consulta sin interpretar su sentido."""

    identifiers: tuple[str, ...]
    """Códigos y referencias, en el orden en que aparecen y sin repetir."""

    @property
    def has_exact_signal(self) -> bool:
        return bool(self.identifiers)


def detect_signals(query: str) -> QuerySignals:
    seen: dict[str, None] = {}
    for match in _TOKEN.finditer(query):
        token = match.group().strip("._/-")
        if _is_identifier(token):
            seen.setdefault(token, None)
    return QuerySignals(identifiers=tuple(seen))
