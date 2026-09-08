"""El extractor reconoce la estructura del documento, no solo su texto.

Todo lo que se prueba aquí usa documentos **sintéticos**: la forma de un
manual técnico sin un solo dato de planta.
"""

import pytest

from elsa.adapters.structured_text_extractor import StructuredTextExtractor
from elsa.ports.document_extraction import (
    BlockKind,
    DocumentExtractionPort,
    ExtractedDocument,
    UnsupportedDocumentError,
)
from tests import fixtures_documents as fx

pytestmark = pytest.mark.anyio


@pytest.fixture
def extractor() -> StructuredTextExtractor:
    return StructuredTextExtractor()


async def extract(extractor: StructuredTextExtractor, text: str) -> ExtractedDocument:
    return await extractor.extract(fx.encoded(text), content_type="text/markdown")


def test_the_extractor_satisfies_its_port(extractor: StructuredTextExtractor) -> None:
    assert isinstance(extractor, DocumentExtractionPort)


def test_it_declares_what_it_can_read(extractor: StructuredTextExtractor) -> None:
    assert extractor.supports("text/markdown")
    assert extractor.supports("text/plain; charset=utf-8")
    assert extractor.supports("application/octet-stream", "manual.md")
    assert not extractor.supports("application/pdf")


async def test_a_pdf_is_refused_instead_of_guessed(
    extractor: StructuredTextExtractor,
) -> None:
    """Sin OCR ni motor de PDF, la respuesta correcta es «no sé leerlo».

    Devolver el poco texto que se pueda arrancar de un PDF sería inventar un
    documento incompleto y presentarlo como completo.
    """
    with pytest.raises(UnsupportedDocumentError):
        await extractor.extract(b"%PDF-1.7", content_type="application/pdf", filename="m.pdf")


async def test_a_binary_renamed_to_text_is_refused(
    extractor: StructuredTextExtractor,
) -> None:
    with pytest.raises(UnsupportedDocumentError):
        await extractor.extract(fx.NOT_TEXT, content_type="text/plain", filename="manual.txt")


async def test_headings_keep_their_depth_and_printed_number(
    extractor: StructuredTextExtractor,
) -> None:
    document = await extract(extractor, fx.MANUAL_V1)

    headings = [(block.level, block.number_label, block.text) for block in document.headings]

    assert (2, "1", "Alcance") in headings
    assert (3, "3.1", "Desmontaje") in headings
    # El número impreso se separa del título: `3.1` no forma parte del nombre.
    assert all(not title.startswith("3.1") for _, _, title in headings)


async def test_every_structural_kind_is_recognised(
    extractor: StructuredTextExtractor,
) -> None:
    document = await extract(extractor, fx.MANUAL_V1)

    kinds = {block.kind for block in document.blocks}

    assert kinds == {
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.WARNING,
        BlockKind.LIST_ITEM,
        BlockKind.STEP,
        BlockKind.TABLE,
        BlockKind.CAPTION,
    }


async def test_steps_keep_their_order_and_number(
    extractor: StructuredTextExtractor,
) -> None:
    document = await extract(extractor, fx.MANUAL_V1)

    steps = [block for block in document.blocks if block.kind is BlockKind.STEP]

    assert [block.number_label for block in steps] == ["1", "2", "3"]
    assert [block.ordinal for block in steps] == sorted(block.ordinal for block in steps)


async def test_a_table_keeps_its_rows_and_its_header(
    extractor: StructuredTextExtractor,
) -> None:
    document = await extract(extractor, fx.MANUAL_V1)

    table = next(block for block in document.blocks if block.kind is BlockKind.TABLE)

    assert table.header_rows == 1
    assert table.rows[0] == ("Componente", "Medida nominal", "Tolerancia")
    assert len(table.rows) == 4
    # La fila separadora de Markdown es sintaxis, no un dato.
    assert all(set(row) != {"---"} for row in table.rows)


async def test_a_table_without_a_header_marker_is_reported(
    extractor: StructuredTextExtractor,
) -> None:
    """No se supone que la primera fila sean rótulos.

    Si se supusiera, al partir una tabla larga se repetiría una fila de
    datos haciéndola pasar por encabezado en cada trozo.
    """
    document = await extract(
        extractor,
        "# Doc\n\n## 1. Tabla\n\n| XX-001 | Pieza | 2 |\n| XX-002 | Pieza | 3 |\n",
    )

    table = next(block for block in document.blocks if block.kind is BlockKind.TABLE)

    assert table.header_rows == 0
    assert "table_without_header_marker" in {w.code for w in document.warnings}


async def test_a_paragraph_that_crosses_a_page_stays_whole(
    extractor: StructuredTextExtractor,
) -> None:
    """Un avance de página es frontera de página, no de párrafo."""
    document = await extract(extractor, fx.CROSS_PAGE)

    paragraph = next(
        block
        for block in document.blocks
        if block.kind is BlockKind.PARAGRAPH and "eje" in block.text
    )

    assert document.page_count == 2
    assert paragraph.page_start == 1
    assert paragraph.page_end == 2
    assert paragraph.pages == (1, 2)
    assert "sostiene el sello" in paragraph.text


async def test_content_after_the_page_break_belongs_to_the_next_page(
    extractor: StructuredTextExtractor,
) -> None:
    document = await extract(extractor, fx.CROSS_PAGE)

    last = next(block for block in document.blocks if "galgas" in block.text)

    assert last.page_start == 2


async def test_offsets_point_back_at_the_source_text(
    extractor: StructuredTextExtractor,
) -> None:
    """Sin esto, un chunk no puede demostrar de dónde salió."""
    document = await extract(extractor, fx.MANUAL_V1)

    for block in document.blocks:
        assert 0 <= block.char_start < block.char_end <= len(document.text)
        assert document.text[block.char_start : block.char_end].strip()


async def test_blocks_are_numbered_without_gaps(
    extractor: StructuredTextExtractor,
) -> None:
    document = await extract(extractor, fx.MANUAL_V1)

    assert [block.ordinal for block in document.blocks] == list(range(len(document.blocks)))


async def test_an_empty_document_is_reported_not_invented(
    extractor: StructuredTextExtractor,
) -> None:
    document = await extract(extractor, fx.EMPTY_DOCUMENT)

    assert document.blocks == ()
    assert "empty_document" in {w.code for w in document.warnings}


async def test_extraction_is_deterministic(extractor: StructuredTextExtractor) -> None:
    first = await extract(extractor, fx.MANUAL_V1)
    second = await extract(extractor, fx.MANUAL_V1)

    assert [(b.ordinal, b.kind, b.text, b.char_start) for b in first.blocks] == [
        (b.ordinal, b.kind, b.text, b.char_start) for b in second.blocks
    ]


async def test_the_extraction_records_which_engine_produced_it(
    extractor: StructuredTextExtractor,
) -> None:
    """Cambiar de motor cambia el resultado aunque el archivo sea el mismo."""
    document = await extract(extractor, fx.MANUAL_V1)

    assert document.extractor == "structured_text"
    assert document.extractor_version == "1"
