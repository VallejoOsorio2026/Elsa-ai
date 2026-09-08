"""El chunking respeta la estructura y se repite exactamente.

Estas pruebas son el contrato del Bloque 4.1: definen qué se puede partir,
qué no, dónde hay solape y qué hace el chunker con un documento que no
encaja en sus límites.
"""

import pytest

from elsa.adapters.structured_text_extractor import StructuredTextExtractor
from elsa.documents.chunking import chunk_document
from elsa.documents.model import ChunkingPolicy, ChunkKind, DocumentStructure, estimate_tokens
from elsa.ports.document_extraction import BlockKind
from tests import fixtures_documents as fx

pytestmark = pytest.mark.anyio

# Límites pequeños a propósito: fuerzan los cortes con documentos legibles.
SMALL = ChunkingPolicy(
    name="test-small", target_tokens=60, max_tokens=120, min_tokens=10, overlap_tokens=10
)


async def structure(text: str, policy: ChunkingPolicy = SMALL) -> DocumentStructure:
    extractor = StructuredTextExtractor()
    extracted = await extractor.extract(fx.encoded(text), content_type="text/markdown")
    return chunk_document(extracted, document_title="Documento sintetico", policy=policy)


# ---------------------------------------------------------------------
# Secciones
# ---------------------------------------------------------------------


async def test_the_section_tree_reproduces_the_document() -> None:
    result = await structure(fx.MANUAL_V1)

    tree = [
        (section.path, section.depth, section.number_label, section.title)
        for section in result.sections
    ]

    assert tree == [
        ("1", 1, None, "Manual de ejemplo del equipo de laboratorio"),
        ("1.1", 2, "1", "Alcance"),
        ("1.2", 2, "2", "Seguridad"),
        ("1.3", 2, "3", "Procedimiento de revision"),
        ("1.3.1", 3, "3.1", "Desmontaje"),
        ("1.3.2", 3, "3.2", "Inspeccion"),
        ("1.4", 2, "4", "Registro"),
    ]


async def test_a_section_path_does_not_depend_on_the_printed_numbering() -> None:
    """Un manual sin numerar necesita igualmente una dirección única."""
    result = await structure("# Titulo\n\n## Alcance\n\ntexto\n\n## Seguridad\n\ntexto\n")

    assert [section.path for section in result.sections] == ["1", "1.1", "1.2"]
    assert all(section.number_label is None for section in result.sections)


async def test_content_before_the_first_heading_is_kept_and_reported() -> None:
    result = await structure("Texto de portada sin titulo previo.\n\n# Uno\n\ntexto\n")

    preamble = result.sections[0]

    assert preamble.is_preamble
    assert preamble.path == "0"
    assert preamble.title == "Documento sintetico"
    assert "content_before_first_heading" in result.warning_counts()
    assert any(chunk.section_path == "0" for chunk in result.chunks)


async def test_a_skipped_heading_level_is_reported() -> None:
    result = await structure("# Uno\n\n### Tres\n\ntexto\n")

    assert "heading_level_skipped" in result.warning_counts()


# ---------------------------------------------------------------------
# Reglas de corte
# ---------------------------------------------------------------------


async def test_a_chunk_never_mixes_two_sections() -> None:
    result = await structure(fx.MANUAL_V1)

    for chunk in result.chunks:
        assert chunk.section_path is not None
        section = next(s for s in result.sections if s.path == chunk.section_path)
        assert chunk.section_title == section.title


async def test_a_table_gets_its_own_chunk_and_is_not_mixed_with_prose() -> None:
    result = await structure(fx.MANUAL_V1)

    table_chunks = [chunk for chunk in result.chunks if ChunkKind.TABLE in (chunk.kind,)]
    mixed = [chunk for chunk in result.chunks if chunk.kind is ChunkKind.MIXED]

    # La tabla del manual va con su pie —que es parte de la tabla— y con
    # nada más: ningún párrafo de la sección entra en ese chunk.
    assert len(table_chunks) + len(mixed) >= 1
    table = next(c for c in result.chunks if "Medida nominal" in c.content)
    assert "Revisar el desgaste" not in table.content


async def test_a_long_table_is_split_by_rows_repeating_the_header() -> None:
    result = await structure(fx.LONG_TABLE_WITH_HEADER)

    tables = [chunk for chunk in result.chunks if chunk.kind is ChunkKind.TABLE]

    assert len(tables) > 1
    for chunk in tables:
        assert chunk.content.startswith("Codigo | Denominacion | Cantidad")
        assert "table_split" in chunk.warnings
        # Nunca a mitad de fila: cada renglón tiene sus tres columnas.
        for line in chunk.content.split("\n"):
            assert line.count("|") == 2


async def test_a_warning_opens_a_chunk_and_is_never_split() -> None:
    """Una advertencia a medias, o al final de un chunk que nadie lee entero,
    es peor que ninguna advertencia."""
    result = await structure(fx.MANUAL_V1)

    warning_chunk = next(chunk for chunk in result.chunks if "ADVERTENCIA" in chunk.content)

    assert warning_chunk.content.startswith("ADVERTENCIA")
    assert "lesiones graves" in warning_chunk.content


async def test_numbered_steps_are_never_cut_in_half() -> None:
    result = await structure(fx.MANUAL_V1)

    steps = [chunk for chunk in result.chunks if chunk.kind is ChunkKind.STEPS]

    assert steps
    for chunk in steps:
        for line in chunk.content.split("\n"):
            assert line[0].isdigit()
            assert line.rstrip().endswith(".")


async def test_an_indivisible_unit_that_is_too_large_is_reported_not_butchered() -> None:
    result = await structure(fx.INDIVISIBLE_STEP)

    oversized = [chunk for chunk in result.chunks if chunk.oversized]

    assert len(oversized) == 1
    assert oversized[0].kind is ChunkKind.STEPS
    assert "indivisible_unit_too_large" in oversized[0].warnings
    assert result.warning_counts()["chunk_oversized"] == 1


async def test_long_prose_is_split_by_sentences() -> None:
    result = await structure(fx.LONG_SECTION)

    assert len(result.chunks) > 1
    for chunk in result.chunks:
        assert chunk.token_estimate <= SMALL.max_tokens
        assert not chunk.oversized


# ---------------------------------------------------------------------
# Solape
# ---------------------------------------------------------------------


async def test_overlap_only_appears_where_size_forced_the_cut() -> None:
    result = await structure(fx.LONG_SECTION)

    assert result.chunks[0].overlap_chars == 0
    assert all(chunk.overlap_chars > 0 for chunk in result.chunks[1:])
    assert all(chunk.boundary_reason == "size" for chunk in result.chunks[1:])


async def test_a_structural_cut_carries_no_overlap() -> None:
    """El documento ya dice que ahí cambia el tema; repetir texto solo lo
    duplicaría en el índice."""
    result = await structure(fx.MANUAL_V1)

    for chunk in result.chunks:
        if chunk.boundary_reason == "structure":
            assert chunk.overlap_chars == 0


async def test_overlap_can_be_switched_off() -> None:
    policy = ChunkingPolicy(
        name="no-overlap", target_tokens=60, max_tokens=120, min_tokens=10, overlap_tokens=0
    )

    result = await structure(fx.LONG_SECTION, policy)

    assert all(chunk.overlap_chars == 0 for chunk in result.chunks)


# ---------------------------------------------------------------------
# Trazabilidad
# ---------------------------------------------------------------------


async def test_every_chunk_can_reconstruct_where_it_came_from() -> None:
    result = await structure(fx.MANUAL_V1)

    for chunk in result.chunks:
        assert chunk.section_path is not None
        assert chunk.section_title
        assert chunk.heading_trail
        assert chunk.page_start is not None and chunk.page_end is not None
        assert chunk.block_start is not None and chunk.block_end is not None
        assert chunk.char_start is not None and chunk.char_end is not None
        assert chunk.char_start < chunk.char_end
        assert len(chunk.content_sha256) == 64


async def test_pages_are_preserved_across_a_page_break() -> None:
    result = await structure(fx.CROSS_PAGE)

    crossing = next(chunk for chunk in result.chunks if "sostiene el sello" in chunk.content)

    assert (crossing.page_start, crossing.page_end) == (1, 2)


async def test_chunks_are_numbered_in_reading_order_without_gaps() -> None:
    result = await structure(fx.MANUAL_V1)

    assert [chunk.ordinal for chunk in result.chunks] == list(range(len(result.chunks)))
    assert len({chunk.structural_key for chunk in result.chunks}) == len(result.chunks)


async def test_the_heading_trail_is_metadata_not_content() -> None:
    """Anteponer el título al texto cambiaría el hash del contenido y haría
    imposible saber qué decía el documento exactamente."""
    result = await structure(fx.MANUAL_V1)

    chunk = next(c for c in result.chunks if c.section_path == "1.1")

    assert chunk.heading_trail == ("Manual de ejemplo del equipo de laboratorio", "Alcance")
    assert not chunk.content.startswith("Alcance")


async def test_the_heading_trail_carries_the_whole_ancestry() -> None:
    """Solo el par entero identifica de qué se habla: «Inspeccion» a secas
    aparece en media docena de manuales."""
    result = await structure(fx.MANUAL_V1)

    chunk = next(c for c in result.chunks if c.section_path == "1.3.2")

    assert chunk.heading_trail == (
        "Manual de ejemplo del equipo de laboratorio",
        "Procedimiento de revision",
        "Inspeccion",
    )


# ---------------------------------------------------------------------
# Determinismo
# ---------------------------------------------------------------------


async def test_the_same_document_produces_the_same_chunks_and_hashes() -> None:
    first = await structure(fx.MANUAL_V1)
    second = await structure(fx.MANUAL_V1)

    assert first.structure_sha256 == second.structure_sha256
    assert [chunk.content_sha256 for chunk in first.chunks] == [
        chunk.content_sha256 for chunk in second.chunks
    ]


async def test_changing_the_policy_changes_the_structure_hash() -> None:
    """Dos versiones chunkeadas con límites distintos no son comparables, y
    la huella tiene que decirlo."""
    default = await structure(fx.MANUAL_V1, ChunkingPolicy())
    small = await structure(fx.MANUAL_V1, SMALL)

    assert default.structure_sha256 != small.structure_sha256


async def test_a_changed_document_changes_the_structure_hash() -> None:
    first = await structure(fx.MANUAL_V1)
    second = await structure(fx.MANUAL_V2)

    assert first.structure_sha256 != second.structure_sha256


async def test_an_empty_document_produces_nothing_and_says_so() -> None:
    result = await structure(fx.EMPTY_DOCUMENT)

    assert result.chunks == ()
    assert result.sections == ()
    assert "empty_document" in result.warning_counts()


# ---------------------------------------------------------------------
# Política
# ---------------------------------------------------------------------


def test_the_policy_refuses_incoherent_limits() -> None:
    with pytest.raises(ValueError):
        ChunkingPolicy(target_tokens=400, max_tokens=100)
    with pytest.raises(ValueError):
        ChunkingPolicy(target_tokens=400, overlap_tokens=400)
    with pytest.raises(ValueError):
        ChunkingPolicy(chars_per_token=0)


def test_the_token_estimate_is_stable_and_documented() -> None:
    assert estimate_tokens("", chars_per_token=4) == 0
    assert estimate_tokens("abcd", chars_per_token=4) == 1
    assert estimate_tokens("abcde", chars_per_token=4) == 2
    # Los espacios de más no cuentan: el texto se normaliza antes de medir.
    assert estimate_tokens("a     b", chars_per_token=4) == estimate_tokens(
        "a b", chars_per_token=4
    )


def test_the_policy_fingerprint_covers_every_parameter() -> None:
    base = ChunkingPolicy()

    assert base.fingerprint() == ChunkingPolicy().fingerprint()
    assert base.fingerprint() != ChunkingPolicy(overlap_tokens=0).fingerprint()
    assert set(base.parameters()) == {
        "name",
        "target_tokens",
        "max_tokens",
        "min_tokens",
        "overlap_tokens",
        "chars_per_token",
        "keep_tables_whole",
    }


async def test_headings_are_not_content() -> None:
    """El título define la sección; no se repite dentro del chunk."""
    extractor = StructuredTextExtractor()
    extracted = await extractor.extract(fx.encoded(fx.MANUAL_V1), content_type="text/markdown")

    headings = {block.text for block in extracted.blocks if block.kind is BlockKind.HEADING}
    result = chunk_document(extracted, document_title="Documento sintetico", policy=SMALL)

    for chunk in result.chunks:
        assert chunk.content not in headings
