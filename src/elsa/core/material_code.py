"""Cuándo una pregunta pide la disponibilidad de **un código exacto**.

Decide solo si hay un código identificado sin ambigüedad. **No lo transforma**:
lo que devuelve es la subcadena tal como el usuario la escribió, porque el
lookup de Materiales es exacto y la representación de frontera es la cadena
decimal sin agregar ni quitar ceros, sin ``strip`` y sin conversión numérica
(M3-A, ADR 0024 §8). ``"000123"`` sigue siendo ``"000123"``.

Es deliberadamente conservador. Una consulta viva a Materiales es un hecho que
se le entrega a quien va a actuar sobre un equipo, así que ante la duda no se
pregunta: la búsqueda literal sobre el BOM publicado sigue funcionando igual.

- Un código es una corrida de 6 a 18 dígitos ASCII que no forma parte de otra
  palabra ni de un número con separadores (``SYN-100003``, ``1.500000``).
- Solo cuenta si la pregunta lo pide: trae una palabra de inventario
  (material, código, disponibilidad, stock…) o el mensaje es solo el código.
- Más de un código distinto es ambiguo y no se consulta ninguno: V1 es unitario
  y elegir uno por el usuario sería adivinar.

No se detectan códigos alfanuméricos: el dominio observado del Piloto Tampella
es numérico (ADR 0024 §10) y buscar texto libre como código está prohibido
(ADR 0021 §2).
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "EXPECTED_MATERIALS_CONTRACT_VERSION",
    "CodeDetection",
    "CodeDetectionKind",
    "detect_exact_material_code",
]

EXPECTED_MATERIALS_CONTRACT_VERSION = "1"
"""Versión del contrato de Materiales que ELSA declara esperar (ADR 0021 §15.3).

Es una **cadena**: ``1``, ``1.0`` y ``"1.0"`` no son esta versión. Vive aquí, y
no en el adaptador, para que la capa HTTP la use sin importar un adaptador.
"""

MIN_CODE_DIGITS = 6
MAX_CODE_DIGITS = 18

# Dígitos ASCII, sin letras, guiones, barras, puntos ni comas pegados: así
# «SYN-100003», «A1234567» o «1.500000» no se confunden con un código.
_CODE = re.compile(
    rf"(?<![A-Za-z0-9_\-/.,])[0-9]{{{MIN_CODE_DIGITS},{MAX_CODE_DIGITS}}}(?![A-Za-z0-9_\-/])"
)

# Palabras que convierten la pregunta en una consulta de inventario. Se
# comparan sobre una copia sin acentos; el código nunca pasa por ahí.
_INVENTORY_WORDS = frozenset(
    "material materiales codigo codigos disponibilidad disponible stock "
    "existencia existencias inventario".split()
)
_WORD = re.compile(r"[a-z]+")


class CodeDetectionKind(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    """No hay un código exacto que consultar. No se llama a Materiales."""

    SINGLE = "single"
    """Un único código identificado. Se puede consultar."""

    AMBIGUOUS = "ambiguous"
    """Varios códigos distintos. No se consulta ninguno."""


@dataclass(frozen=True, slots=True)
class CodeDetection:
    kind: CodeDetectionKind
    code: str | None = None
    """El código **tal cual se escribió**. Solo con :attr:`CodeDetectionKind.SINGLE`."""


_NOT_APPLICABLE = CodeDetection(CodeDetectionKind.NOT_APPLICABLE)


def detect_exact_material_code(text: str) -> CodeDetection:
    """Busca un código exacto en la pregunta original, sin normalizarla."""
    found = _CODE.findall(text)
    if not found:
        return _NOT_APPLICABLE

    # El orden de aparición se conserva; repetir el mismo código no lo hace ambiguo.
    distinct = list(dict.fromkeys(found))
    if not (_asks_about_inventory(text) or _is_only_the_code(text, distinct)):
        return _NOT_APPLICABLE
    if len(distinct) > 1:
        return CodeDetection(CodeDetectionKind.AMBIGUOUS)
    return CodeDetection(CodeDetectionKind.SINGLE, distinct[0])


def _asks_about_inventory(text: str) -> bool:
    folded = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(char for char in folded if not unicodedata.combining(char))
    return any(word in _INVENTORY_WORDS for word in _WORD.findall(plain))


def _is_only_the_code(text: str, codes: list[str]) -> bool:
    """El mensaje es el código y, a lo sumo, signos de puntuación alrededor."""
    if len(codes) != 1:
        return False
    return text.strip(" \t\r\n¿?¡!.,;:\"'()").strip() == codes[0]
