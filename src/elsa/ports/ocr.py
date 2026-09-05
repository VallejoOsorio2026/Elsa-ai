"""Puerto de OCR / extracción de texto de documentos.

El motor concreto (Docling vs PaddleOCR) está abierto. El resultado se
estructura por páginas para conservar trazabilidad de evidencias.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class OCRPage:
    """Texto extraído de una página (numerada desde 1)."""

    number: int
    text: str


@dataclass(frozen=True, slots=True)
class OCRResult:
    """Resultado completo de la extracción."""

    pages: tuple[OCRPage, ...]

    @property
    def text(self) -> str:
        """Texto plano completo, páginas separadas por doble salto de línea."""
        return "\n\n".join(page.text for page in self.pages)


class UnsupportedDocumentError(Exception):
    """El tipo de documento no es procesable por el motor configurado."""


@runtime_checkable
class OCRPort(Protocol):
    """Extracción de texto a partir del contenido binario de un documento."""

    async def extract_text(self, content: bytes, *, content_type: str) -> OCRResult:
        """Extrae el texto de un documento.

        Lanza :class:`UnsupportedDocumentError` si ``content_type`` no está
        soportado por el adaptador.
        """
        ...
