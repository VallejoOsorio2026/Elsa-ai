"""Contrato del puerto OCR, verificado con el adaptador fake."""

import pytest

from elsa.adapters.fake_ocr import FakeOCRAdapter
from elsa.ports.ocr import OCRPort, OCRResult, UnsupportedDocumentError

pytestmark = pytest.mark.anyio


@pytest.fixture
def port() -> OCRPort:
    return FakeOCRAdapter()


def test_fake_adapter_satisfies_the_port(port: OCRPort) -> None:
    assert isinstance(port, OCRPort)


async def test_extracts_pages_from_plain_text(port: OCRPort) -> None:
    content = b"page one\x0cpage two"

    result = await port.extract_text(content, content_type="text/plain")

    assert isinstance(result, OCRResult)
    assert [page.number for page in result.pages] == [1, 2]
    assert result.pages[0].text == "page one"
    assert result.text == "page one\n\npage two"


async def test_extraction_is_deterministic(port: OCRPort) -> None:
    content = b"stable content"

    first = await port.extract_text(content, content_type="text/plain")
    second = await port.extract_text(content, content_type="text/plain")

    assert first == second


async def test_unsupported_content_type_raises(port: OCRPort) -> None:
    with pytest.raises(UnsupportedDocumentError):
        await port.extract_text(b"%PDF-1.7", content_type="application/pdf")
