"""Adaptador fake del puerto OCR (determinista, para tests)."""

from elsa.ports.ocr import OCRPage, OCRResult, UnsupportedDocumentError

SUPPORTED_CONTENT_TYPES = frozenset({"text/plain"})

# Separador de páginas en el texto plano de entrada (form feed).
_PAGE_SEPARATOR = "\x0c"


class FakeOCRAdapter:
    """Simula la extracción de texto sobre documentos ``text/plain``.

    Interpreta el form feed (``\\x0c``) como salto de página. Cualquier otro
    ``content_type`` lanza :class:`UnsupportedDocumentError`, igual que haría
    un motor real ante un formato no soportado.
    """

    async def extract_text(self, content: bytes, *, content_type: str) -> OCRResult:
        if content_type not in SUPPORTED_CONTENT_TYPES:
            raise UnsupportedDocumentError(f"content type not supported: {content_type!r}")
        text = content.decode("utf-8", errors="replace")
        pages = tuple(
            OCRPage(number=index, text=page_text.strip())
            for index, page_text in enumerate(text.split(_PAGE_SEPARATOR), start=1)
        )
        return OCRResult(pages=pages)
