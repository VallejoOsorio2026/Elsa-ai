"""Selección de evidencia y construcción del contexto que ve el modelo.

Entra un :class:`EvidenceSet` **ya autorizado** por la recuperación híbrida y
sale un bloque de texto con marcadores estables. Aquí no se consulta nada, no
se decide ningún permiso y no se llama a ningún modelo: es una función del
conjunto de evidencia, y por eso dos corridas con la misma entrada producen el
mismo contexto carácter a carácter.

Tres cosas que este módulo garantiza, y que el resto del bloque da por hechas:

- **Cada pieza conserva su procedencia.** El marcador `E1` no es un número
  suelto: apunta a un :class:`Evidence` concreto, y de ahí sale la cita. Un
  contexto que perdiera ese vínculo produciría respuestas incitables.
- **Nada se cuenta dos veces.** El mismo pasaje, o dos pasajes con contenido
  idéntico, ocupan una sola entrada. Pagar dos veces el mismo texto es
  gastar presupuesto en no añadir información.
- **El documento no puede romper el formato.** El contenido va dentro de una
  valla delimitada, y cualquier intento de cerrarla desde dentro se neutraliza
  antes de componer. Es la primera de las dos defensas contra la inyección
  documental; la otra es que la evidencia viaja siempre como mensaje de
  usuario, nunca como instrucción de sistema.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from elsa.ports.evidence import Evidence, EvidenceSet

__all__ = [
    "BuiltContext",
    "ContextItem",
    "DEFAULT_BUDGET_CHARS",
    "DEFAULT_MAX_ITEMS",
    "build_context",
    "marker_for",
    "neutralise_fences",
]

DEFAULT_BUDGET_CHARS = 6000
"""Presupuesto en caracteres, no en tokens.

Contar tokens exige el tokenizador del proveedor, y el proveedor todavía no
está decidido (ADR 0003). Un presupuesto en caracteres es conservador,
independiente del modelo y exacto; cuando haya proveedor, se traduce.
"""

DEFAULT_MAX_ITEMS = 8

_FENCE = "-----"
_OPEN = "{fence} EVIDENCIA {marker} {fence}"
_CLOSE = "{fence} FIN EVIDENCIA {marker} {fence}"

# Una línea que se parezca a nuestra valla. No se busca «texto sospechoso» en
# general —eso daría falsos positivos sobre prosa técnica legítima— sino
# exactamente la forma que permitiría cerrar el bloque antes de tiempo y colar
# lo que sigue como si fuera otra cosa.
_FENCE_LIKE = re.compile(
    r"^[ \t]*-{3,}[ \t]*(?:FIN[ \t]+)?EVIDENCIA\b.*$", re.IGNORECASE | re.MULTILINE
)

# Separadores de línea que un lector trata como salto y `str.split("\n")` no.
# Sin normalizarlos, una valla precedida de `\r` o de U+2028 se ve como línea
# propia para el modelo y es invisible para la detección.
_LINE_BREAKS = re.compile(r"\r\n|[\r\x0b\x0c\x85\u2028\u2029]")

# Espacios que no son `[ \t]`. Sangrar la valla con un NBSP la escondería del
# patrón sin dejar de parecer una sangría.
_ODD_SPACES = re.compile(r"[\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]")

_FLATTEN = re.compile(r"\s+")


def marker_for(position: int) -> str:
    """`E1`, `E2`, … La posición empieza en 1 y sigue el orden del ranking."""
    return f"E{position}"


def neutralise_fences(text: str) -> str:
    """Desactiva las líneas que imitan la valla, sin borrar nada.

    Se aplica a **todo lo que no escribimos nosotros**: el contenido de los
    documentos y también la pregunta del usuario. Quien pregunta puede
    redactar un bloque de evidencia entero y bien formado, y si se insertara
    crudo el modelo lo leería como una evidencia más —con un marcador que
    luego resolvería contra procedencia real—. La neutralización tiene que
    cubrir los dos lados, no solo el documento.

    Primero se normalizan los separadores de línea y los espacios raros, para
    que la valla no se pueda esconder tras un `\r` o un NBSP. Después se
    sustituyen los guiones iniciales por puntos medios: la línea sigue siendo
    legible para el modelo y para una persona, pero deja de ser una valla.

    **No se censura texto.** Un pasaje mutilado por precaución sería un pasaje
    que el ingeniero no puede comprobar contra su documento.
    """
    text = _LINE_BREAKS.sub("\n", text)
    text = _ODD_SPACES.sub(" ", text)
    if not _FENCE_LIKE.search(text):
        return text
    return "\n".join(
        re.sub(r"^([ \t]*)-{3,}", r"\1···", line) if _FENCE_LIKE.match(line) else line
        for line in text.split("\n")
    )


@dataclass(frozen=True, slots=True)
class ContextItem:
    """Una evidencia tal y como entra al contexto, con su marcador."""

    marker: str
    evidence: Evidence
    content: str
    """Contenido ya neutralizado y, si hizo falta, recortado."""

    truncated: bool = False

    @property
    def header(self) -> str:
        """Procedencia legible. Sin UUID: el modelo no los necesita."""
        provenance = self.evidence.provenance
        document = provenance.document
        parts = [provenance.citation(), f"dominio: {document.domain}"]
        if document.asset_code:
            parts.append(f"activo: {document.asset_code}")
        parts.append("canales: " + ", ".join(channel.value for channel in self.evidence.channels))
        # El título del documento y el del apartado salen de un archivo que
        # alguien subió: si llevaran un salto de línea o una valla, la
        # cabecera partiría el bloque en dos desde dentro. Se aplana a una
        # línea y se neutraliza igual que el contenido.
        return _FLATTEN.sub(" ", neutralise_fences(" · ".join(parts))).strip()

    def render(self) -> str:
        open_line = _OPEN.format(fence=_FENCE, marker=self.marker)
        close_line = _CLOSE.format(fence=_FENCE, marker=self.marker)
        body = self.content + ("\n[…pasaje recortado…]" if self.truncated else "")
        return f"{open_line}\n{self.header}\n\n{body}\n{close_line}"


@dataclass(frozen=True, slots=True)
class BuiltContext:
    """El contexto completo, con lo que costó construirlo."""

    items: tuple[ContextItem, ...]
    retrieved: int
    """Cuántas evidencias llegaron de la recuperación."""

    dropped: int
    """Cuántas quedaron fuera **por no caber**. Los duplicados no cuentan aquí.

    La diferencia importa para avisar: no entrar por presupuesto es perder
    información recuperada; no entrar por ser el mismo texto que otra pieza no
    pierde nada, porque no había nada distinto que citar.
    """

    characters: int
    budget: int
    truncated: bool = False
    duplicates: int = 0
    """Cuántas se descartaron por repetir chunk o contenido."""

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self) -> Iterator[ContextItem]:
        return iter(self.items)

    @property
    def is_empty(self) -> bool:
        return not self.items

    def by_marker(self) -> Mapping[str, ContextItem]:
        return {item.marker: item for item in self.items}

    def markers(self) -> tuple[str, ...]:
        return tuple(item.marker for item in self.items)

    def chunk_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence.provenance.chunk.id for item in self.items)

    def render(self) -> str:
        """El bloque que se le entrega al modelo, sin instrucciones."""
        return "\n\n".join(item.render() for item in self.items)


def build_context(
    evidence: EvidenceSet | Sequence[Evidence],
    *,
    budget_chars: int = DEFAULT_BUDGET_CHARS,
    max_items: int = DEFAULT_MAX_ITEMS,
) -> BuiltContext:
    """Compone el contexto a partir de evidencia ya autorizada.

    El orden es el del ranking y **no se reordena**: la recuperación ya decidió
    que una coincidencia exacta encabeza, y rehacerlo aquí sería tener dos
    autoridades sobre lo mismo.

    El recorte es determinista: se admiten piezas enteras mientras quepan y se
    para en la primera que no cabe. La única excepción es que la primera pieza
    por sí sola exceda el presupuesto, y entonces entra recortada y marcada
    —devolver un contexto vacío teniendo evidencia sería peor—. En ambos casos
    la procedencia se conserva íntegra: lo que se recorta es el texto, nunca
    la capacidad de citar de dónde salió.
    """
    candidates = list(evidence.evidence if isinstance(evidence, EvidenceSet) else evidence)
    retrieved = len(candidates)
    if budget_chars <= 0 or max_items <= 0:
        return BuiltContext(
            items=(),
            retrieved=retrieved,
            dropped=retrieved,
            characters=0,
            budget=max(budget_chars, 0),
        )

    items: list[ContextItem] = []
    seen_chunks: set[str] = set()
    seen_content: set[str] = set()
    used = 0
    duplicates = 0
    truncated_any = False

    for candidate in candidates:
        if len(items) >= max_items:
            break
        chunk = candidate.provenance.chunk
        # Dos llaves distintas y las dos necesarias: el mismo chunk puede
        # llegar una sola vez, pero dos chunks distintos pueden traer texto
        # idéntico —una tabla repetida entre versiones, por ejemplo— y pagar
        # el segundo no añade nada que citar.
        if chunk.id in seen_chunks or chunk.content_sha256 in seen_content:
            duplicates += 1
            continue

        content = neutralise_fences(chunk.content)
        item = ContextItem(marker=marker_for(len(items) + 1), evidence=candidate, content=content)
        cost = len(item.render())

        if used + cost > budget_chars:
            if items:
                break
            # Nada entró todavía y esta pieza no cabe: entra recortada.
            overflow = used + cost - budget_chars
            keep = max(len(content) - overflow, 0)
            if keep == 0:
                break
            item = ContextItem(
                marker=item.marker,
                evidence=candidate,
                content=content[:keep],
                truncated=True,
            )
            cost = len(item.render())
            truncated_any = True

        items.append(item)
        seen_chunks.add(chunk.id)
        seen_content.add(chunk.content_sha256)
        used += cost

    return BuiltContext(
        items=tuple(items),
        retrieved=retrieved,
        dropped=retrieved - len(items) - duplicates,
        duplicates=duplicates,
        characters=used,
        budget=budget_chars,
        truncated=truncated_any,
    )
