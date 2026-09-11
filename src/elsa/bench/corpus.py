"""Construcción del corpus del banco con el chunker real de ELSA.

Se trocea con `structural-v1`, el mismo chunker y la misma política que usa
la ingesta (`elsa.documents.chunking`). No con un troceo de juguete: lo que
se mide tiene que ser el chunk que ELSA va a tener, o el banco mide otra
cosa.
"""

import asyncio
import json
from pathlib import Path

from elsa.adapters.structured_text_extractor import StructuredTextExtractor
from elsa.bench.model import BenchChunk, BenchCorpus
from elsa.documents.chunking import chunk_document
from elsa.documents.composition import compose_for_embedding
from elsa.documents.model import ChunkingPolicy

__all__ = ["CORPUS_ROOT", "build_corpus"]

CORPUS_ROOT = Path(__file__).resolve().parents[3] / "bench" / "corpus-sintetico"


def build_corpus(root: Path | None = None, policy: ChunkingPolicy | None = None) -> BenchCorpus:
    """Lee el manifiesto y trocea cada documento declarado."""
    return asyncio.run(build_corpus_async(root, policy))


async def build_corpus_async(
    root: Path | None = None, policy: ChunkingPolicy | None = None
) -> BenchCorpus:
    directory = root or CORPUS_ROOT
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    extractor = StructuredTextExtractor()
    active = policy or ChunkingPolicy()

    chunks: list[BenchChunk] = []
    for entry in manifest["documents"]:
        content = (directory / entry["file"]).read_bytes()
        extracted = await extractor.extract(
            content, content_type="text/markdown", filename=entry["file"]
        )
        structure = chunk_document(extracted, document_title=entry["title"], policy=active)
        for chunk in structure.chunks:
            # Se embebe el texto **compuesto**, no el contenido en crudo: es
            # lo que producción va a embeber, y medir otra cosa elegiría el
            # modelo con una entrada que nunca se va a usar.
            composed = compose_for_embedding(
                content=chunk.content,
                document_title=entry["title"],
                heading_trail=chunk.heading_trail,
            )
            chunks.append(
                BenchChunk(
                    chunk_id=f"{entry['code']}@v{entry['version']}#{chunk.structural_key}",
                    document_code=entry["code"],
                    document_title=entry["title"],
                    domain=entry["domain"],
                    asset=entry["asset"],
                    version=entry["version"],
                    published=entry["published"],
                    language=entry["language"],
                    structural_key=chunk.structural_key,
                    section_path=chunk.section_path,
                    section_title=chunk.section_title,
                    page_start=chunk.page_start,
                    kind=chunk.kind.value,
                    content=chunk.content,
                    embedded_text=composed.text,
                    embedded_sha256=composed.embedded_sha256,
                )
            )
    return BenchCorpus(chunks=tuple(chunks))
