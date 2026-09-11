"""Composición determinista del texto que se embebe (`context-v1`).

Un chunk no se embebe en crudo. El texto que va al modelo lleva delante su
contexto —título del documento y rastro de títulos— porque sin él un pasaje
pierde de qué habla: «el par de apriete es de 45 N·m» es casi idéntico en el
manual de la prensa y en el de la bomba, y el vector de los dos quedaría
prácticamente en el mismo sitio.

Dos razones para que esto sea una plantilla **versionada** y no una
concatenación suelta en el sitio donde se use:

- **El banco tiene que medir lo que producción va a embeber.** Si el banco
  embebe `content` y producción embebe `título › sección › content`, el
  modelo se elige midiendo una entrada que nunca se va a usar. Es el error
  más caro posible de un banco de pruebas, porque no falla: mide otra cosa.
- **Cambiar la plantilla invalida los vectores.** Si el texto compuesto
  cambia, el vector guardado deja de corresponder al chunk aunque el chunk
  no se haya tocado. Por eso la plantilla se identifica (`context-v1`) y el
  texto compuesto se hashea (`embedded_sha256`): así se puede saber qué hay
  que re-embeber sin volver a leer el documento entero.

Función pura: sin base de datos, sin reloj y sin estado. Ver ADR 0013 §4 y
`docs/bloque-4-2-plan.md` §2.2.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from elsa.documents.model import normalize_text

__all__ = ["COMPOSITION_TEMPLATE", "ComposedText", "compose_for_embedding"]

COMPOSITION_TEMPLATE = "context-v1"

# Separador entre los tramos del contexto. Se eligió «›» y no un salto de
# línea porque el contexto es una sola ruta legible, y no un párrafo más que
# el modelo pudiera confundir con contenido del documento.
_TRAIL = " › "


@dataclass(frozen=True, slots=True)
class ComposedText:
    """El texto que se embebe, y su identidad."""

    template: str
    text: str

    @property
    def embedded_sha256(self) -> str:
        """Hash del texto compuesto **y** de la plantilla que lo produjo.

        La plantilla entra en el hash a propósito: el mismo contenido
        compuesto con otra plantilla es otra entrada para el modelo, y tiene
        que dar otro hash para que se sepa que hay que re-embeberlo.
        """
        payload = f"{self.template}\x1e{normalize_text(self.text)}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compose_for_embedding(
    *,
    content: str,
    document_title: str | None = None,
    heading_trail: Sequence[str] = (),
) -> ComposedText:
    """Compone el texto que va al modelo de embeddings.

    Forma: ``<título del documento> › <rastro de títulos> › <contenido>``.
    Los tramos vacíos se omiten, y el rastro no repite el título del
    documento cuando el chunker ya lo incluyó como raíz —cosa que hace,
    porque la sección raíz de un documento Markdown es su propio `# título`—
    para no duplicarlo delante de cada chunk del corpus.
    """
    parts: list[str] = []
    if document_title and document_title.strip():
        parts.append(document_title.strip())
    for heading in heading_trail:
        if not heading or not heading.strip():
            continue
        candidate = heading.strip()
        if parts and candidate == parts[-1]:
            continue
        parts.append(candidate)

    prefix = _TRAIL.join(parts)
    body = content.strip()
    text = f"{prefix}{_TRAIL}{body}" if prefix else body
    return ComposedText(template=COMPOSITION_TEMPLATE, text=text)
