"""Normalización determinística de los valores que llegan de una fuente.

Comparar valores técnicos exige decidir antes qué significa que dos valores
sean «el mismo». Este módulo toma esas decisiones una sola vez, en un lugar
sin dependencias, para que el emparejamiento de componentes y la
reconciliación no las improvisen cada uno a su manera.

Dos principios gobiernan el módulo:

- **Nunca se descarta el original.** Toda función devuelve la forma
  normalizada; el llamador conserva siempre el valor tal y como venía. Poder
  demostrarle a un ingeniero qué decía exactamente su archivo vale más que
  ahorrar una columna.
- **Ambigüedad significa ``None``, no una suposición.** Si un valor no puede
  interpretarse con certeza, se devuelve ``None`` y el dato queda pendiente
  de revisión humana. Adivinar una cantidad es inventar un hecho técnico.
"""

import unicodedata
from decimal import Decimal, InvalidOperation

__all__ = [
    "canonical_sap_code",
    "normalize_key",
    "normalize_quantity",
    "normalize_sap_code",
    "normalize_text",
]


def normalize_text(value: object) -> str | None:
    """Texto visible: recorta y colapsa espacios. Vacío es ``None``.

    Una celda vacía, una llena de espacios y una ausente significan lo mismo
    —«no hay dato»— y deben comportarse igual en toda la ingesta.
    """
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    collapsed = " ".join(text.split())
    return collapsed or None


def normalize_key(value: object) -> str | None:
    """Clave de comparación: minúsculas y sin acentos.

    ``Rodamiento Principal``, ``RODAMIENTO PRINCIPAL`` y ``rodamiento
    principal`` designan lo mismo y deben compararse igual. Se usa para
    nombres de subsistema y de hoja, **nunca** como prueba de identidad de un
    componente: dos componentes distintos pueden llamarse igual.
    """
    text = normalize_text(value)
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_sap_code(value: object) -> str | None:
    """Código SAP tal como se almacena: sin espacios y en mayúsculas.

    Un código puede llegar como texto (``"10023456"``) o como número, y en
    ese caso las hojas de cálculo lo entregan como flotante
    (``10023456.0``). Un código de material no tiene parte decimal, así que
    un flotante con parte decimal cero se escribe como entero; uno con
    decimales reales no es un código y se descarta.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != int(value):
            return None
        return str(int(value))
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            return None
        return str(int(value))
    text = normalize_text(value)
    if text is None:
        return None
    return text.replace(" ", "").upper()


def canonical_sap_code(value: object) -> str | None:
    """Forma canónica usada **solo para comparar** dos códigos SAP.

    SAP rellena los números de material con ceros a la izquierda al
    mostrarlos, de modo que el mismo material aparece como ``10023456`` en el
    Excel de Ingeniería y como ``000000000010023456`` en el HTM exportado.
    Tratarlos como códigos distintos produciría una discrepancia inventada en
    cada renglón.

    El relleno solo se retira cuando el código es **enteramente numérico**:
    ahí los ceros son presentación. En un código alfanumérico un cero inicial
    puede ser significativo, así que se respeta.

    Lo almacenado sigue siendo :func:`normalize_sap_code`; esta forma no
    sustituye al valor, solo lo empareja.
    """
    code = normalize_sap_code(value)
    if code is None:
        return None
    if code.isdigit():
        stripped = code.lstrip("0")
        # Un código de solo ceros conserva un cero: quedarse con la cadena
        # vacía lo convertiría en «sin código».
        return stripped or "0"
    return code


def normalize_quantity(value: object) -> Decimal | None:
    """Cantidad numérica, o ``None`` si el valor no es interpretable.

    Regla de separadores, fijada para que el resultado no dependa de la
    configuración regional de quien exportó el archivo:

    - Si aparecen coma y punto, **el último que aparece es el decimal** y el
      otro es separador de miles. Cubre ``1.234,56`` y ``1,234.56``.
    - Si solo hay comas, la coma es el separador decimal (convención local).
    - Si solo hay puntos y hay más de uno, son separadores de miles.

    Una fórmula (``=A1*2``) **no se evalúa**: es contenido no confiable y se
    devuelve ``None`` para que la fila quede pendiente de revisión.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))

    text = normalize_text(value)
    if text is None:
        return None
    # Las fórmulas del libro son contenido no confiable: no se ejecutan.
    if text.startswith("="):
        return None

    text = text.replace(" ", "").replace(" ", "")
    negative = text.startswith("-")
    if text and text[0] in "+-":
        text = text[1:]

    has_comma = "," in text
    has_dot = "." in text
    if has_comma and has_dot:
        decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal_separator == "," else ","
        text = text.replace(thousands, "").replace(decimal_separator, ".")
    elif has_comma:
        text = text.replace(",", ".") if text.count(",") == 1 else text.replace(",", "")
    elif text.count(".") > 1:
        text = text.replace(".", "")

    try:
        quantity = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return -quantity if negative else quantity
