"""Recuperación híbrida del Bloque 4.3, contra PostgreSQL 16 real.

Corpus sintético, construido para que cada canal tenga algo que aportar y para
que el aislamiento por alcance se pueda probar con un caso incómodo: el pasaje
**semánticamente mejor** pertenece a un activo que el usuario no puede ver.
"""

from collections.abc import AsyncIterator

import asyncpg
import pytest

from elsa.adapters.fake_embeddings import FakeEmbeddingsAdapter
from elsa.adapters.postgres_documents import PostgresDocumentRepository
from elsa.adapters.postgres_lexical import PostgresLexicalSearch
from elsa.adapters.postgres_vectors import PostgresVectorStore
from elsa.core.authorization import Scope
from elsa.core.query_signals import detect_signals
from elsa.documents.composition import compose_for_embedding
from elsa.ports.documents import DocumentSourceKind, DocumentVersionState
from elsa.ports.evidence import Channel, EvidenceStrength, LexicalSearchPort
from elsa.ports.vectors import EmbeddingModelSpec, PendingEmbedding
from elsa.services.hybrid_retrieval import RRF_K, HybridRetrievalService
from tests import db
from tests.test_document_repository import ACTOR, service, version_input

pytestmark = pytest.mark.anyio

DIMENSION = 32

# Dos activos del mismo dominio. El manual de `asset-b` contiene la frase más
# parecida a una de las consultas, a propósito: es la trampa del caso 9.
MANUAL_A = """# Manual de la prensa P-200

## 1. Lubricación

El rodamiento SAP-4471 se lubrica cada 500 horas de operación.

## 2. Apriete

El par de apriete de los tornillos de la tapa es de 45 N·m.

## 3. Balineras

Las balineras del eje principal se revisan en cada parada mayor.
"""

MANUAL_B = """# Manual de la bomba B-310

## 1. Lubricación de rodamientos

Para lubricar el rodamiento hay que aplicar grasa cada 500 horas de operación.

## 2. Referencia

El rodamiento de la bomba es el SAP-9902.
"""


@pytest.fixture
async def stack() -> AsyncIterator[
    tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch]
]:
    url = db.database_url()
    if url is None:
        pytest.skip(db.SKIP_REASON)
    await db.reset_database(url)
    conn = await asyncpg.connect(url)
    try:
        await conn.execute(
            "insert into elsa.knowledge_domains (code,label) values ('laboratorio','Lab')"
        )
        await conn.execute(
            "insert into elsa.technical_assets (code,name,domain) values "
            "('asset-a','Prensa','mantenimiento'),('asset-b','Bomba','mantenimiento'),"
            "('asset-c','Balanza','laboratorio')"
        )
    finally:
        await conn.close()
    documents = await PostgresDocumentRepository.connect(url, min_size=2, max_size=4)
    vectors = await PostgresVectorStore.connect(url, min_size=2, max_size=4)
    lexical = await PostgresLexicalSearch.connect(url, min_size=1, max_size=4)
    try:
        yield documents, vectors, lexical
    finally:
        await lexical.close()
        await vectors.close()
        await documents.close()


async def publish(
    repo: PostgresDocumentRepository,
    code: str,
    asset: str,
    text: str,
    *,
    domain: str = "mantenimiento",
) -> str:
    doc = await repo.create_document(
        domain=domain,
        code=code,
        title=code,
        source_kind=DocumentSourceKind.MANUAL,
        asset_code=asset,
        language="es",
    )
    data = await version_input(repo, doc, text)
    version = await repo.store_version(data, actor=ACTOR)
    await service(repo).approve(version_id=version.id, actor=ACTOR)
    await service(repo).publish(version_id=version.id, actor=ACTOR)
    return version.id


async def embed(
    documents: PostgresDocumentRepository,
    vectors: PostgresVectorStore,
    adapter: FakeEmbeddingsAdapter,
    model_id: str,
    version_id: str,
) -> None:
    chunks = await documents.list_chunks(version_id)
    version = await documents.get_version(version_id)
    assert version is not None
    doc = await documents.get_document_by_id(version.document_id)
    assert doc is not None
    run = await vectors.start_run(model_id=model_id, started_by=ACTOR)
    composed = [
        compose_for_embedding(
            content=c.content, document_title=doc.title, heading_trail=c.heading_trail
        )
        for c in chunks
    ]
    texts = [c.text for c in composed]
    produced = await adapter.embed_documents(texts)
    await vectors.store_embeddings(
        run_id=run.id,
        embeddings=[
            PendingEmbedding(
                chunk_id=chunk.id,
                version_id=version_id,
                embedding=vector,
                embedded_sha256=text.embedded_sha256,
                content_sha256=chunk.content_sha256,
            )
            for chunk, text, vector in zip(chunks, composed, produced, strict=True)
        ],
    )
    await vectors.finish_run(run_id=run.id, generated=len(chunks), reused=0)


async def ready(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
    *,
    activate: bool = True,
) -> tuple[HybridRetrievalService, str]:
    documents, vectors, lexical = stack
    adapter = FakeEmbeddingsAdapter(dimension=DIMENSION)
    d = adapter.describe()
    model = await vectors.register_model(
        EmbeddingModelSpec(
            family=d.family,
            model_id=d.model_id,
            revision=d.revision,
            dimension=d.dimension,
            normalized=d.normalized,
            composition_template=d.composition_template,
            runtime=d.runtime,
            document_prefix=d.document_prefix,
            query_prefix=d.query_prefix,
        ),
        actor=ACTOR,
    )
    for code, asset, text in (
        ("manual-a", "asset-a", MANUAL_A),
        ("manual-b", "asset-b", MANUAL_B),
    ):
        version_id = await publish(documents, code, asset, text)
        await embed(documents, vectors, adapter, model.id, version_id)
    if activate:
        await vectors.activate_model(model_id=model.id, actor=ACTOR)
    assert isinstance(lexical, LexicalSearchPort)
    return (
        HybridRetrievalService(lexical=lexical, vectors=vectors, embeddings=adapter),
        model.id,
    )


ALL_MAINTENANCE = [Scope("mantenimiento", None)]
ONLY_A = [Scope("mantenimiento", "asset-a")]


# ------------------------------------------------------- 1-2 canal exacto


def test_identifiers_are_detected_without_any_model() -> None:
    """Caso 14: un código no depende de un LLM, se reconoce con una regla."""
    signals = detect_signals("¿cada cuánto se lubrica el SAP-4471 de la P-200?")

    assert signals.identifiers == ("SAP-4471", "P-200")
    assert signals.has_exact_signal
    # Una cantidad no es un código: «cada 500 horas» no debe arrastrar todo.
    assert detect_signals("cada 500 horas").identifiers == ()
    assert detect_signals("¿cómo se lubrica el rodamiento?").identifiers == ()


async def test_an_exact_code_wins_over_a_merely_similar_passage(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 1: el chunk que contiene el código literal encabeza."""
    hybrid, _ = await ready(stack)

    found = await hybrid.search(
        query="¿qué mantenimiento lleva el SAP-4471?", scopes=ALL_MAINTENANCE
    )

    assert found.identifiers_detected == ("SAP-4471",)
    assert Channel.EXACT in found.channels_queried
    best = found.evidence[0]
    assert "SAP-4471" in best.provenance.chunk.content
    assert best.has_exact_match
    assert found.strength is EvidenceStrength.SUFFICIENT


async def test_an_exact_component_name_is_found(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 2: el nombre exacto del componente, por el canal léxico."""
    hybrid, _ = await ready(stack)

    found = await hybrid.search(query="par de apriete de los tornillos", scopes=ONLY_A)

    assert found.evidence
    assert "apriete" in found.evidence[0].provenance.chunk.content.lower()
    assert Channel.LEXICAL in found.evidence[0].channels


# ---------------------------------------------------- 3-4 léxico y semántico


async def test_a_lexical_query_finds_the_passage_by_its_words(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 3, con lematización española: «lubricar» encuentra «se lubrica»."""
    documents, vectors, lexical = stack
    await ready(stack)

    results = await lexical.search_lexical(query="lubricar rodamiento", scopes=ALL_MAINTENANCE)

    assert results
    assert any("lubrica" in p.chunk.content.lower() for p, _ in results)


async def test_a_paraphrase_is_served_by_the_semantic_channel(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 4: sin palabras en común, el canal denso es el que responde.

    «balinera» es el término de taller para «rodamiento». Aquí importa que el
    canal semántico **participe** y aporte candidatos que el léxico no da.
    """
    hybrid, _ = await ready(stack)

    found = await hybrid.search(query="revisión de balineras del eje", scopes=ONLY_A)

    assert Channel.SEMANTIC in found.channels_queried
    assert found.evidence
    assert any(Channel.SEMANTIC in e.channels for e in found.evidence)


# ------------------------------------------------------------- 5-6 fusión


async def test_a_chunk_found_by_two_channels_is_fused_once_keeping_both_ranks(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 5: sin duplicados, y se conserva la posición que dio cada canal."""
    hybrid, _ = await ready(stack)

    found = await hybrid.search(query="lubricación del rodamiento SAP-4471", scopes=ALL_MAINTENANCE)

    ids = [e.provenance.chunk.id for e in found.evidence]
    assert len(ids) == len(set(ids))
    multi = [e for e in found.evidence if e.found_by_multiple_channels]
    assert multi, "ningún chunk fue encontrado por más de un canal"
    for hit in multi[0].hits:
        assert hit.rank >= 1 and hit.channel in Channel
    assert len({hit.channel for hit in multi[0].hits}) == len(multi[0].hits)


async def test_the_fusion_is_reproducible_and_uses_the_documented_constant(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 6 y 16: mismo corpus y misma consulta, mismo ranking y mismo score."""
    hybrid, _ = await ready(stack)

    first = await hybrid.search(query="lubricación cada 500 horas", scopes=ALL_MAINTENANCE)
    second = await hybrid.search(query="lubricación cada 500 horas", scopes=ALL_MAINTENANCE)

    assert [(e.provenance.chunk.id, e.fused_score, e.rank) for e in first.evidence] == [
        (e.provenance.chunk.id, e.fused_score, e.rank) for e in second.evidence
    ]
    assert RRF_K == 60
    # RRF es `Σ 1/(k + posición)`: con un solo canal en posición 1, es 1/61.
    single = [e for e in first.evidence if len(e.hits) == 1]
    if single:
        hit = single[0].hits[0]
        assert single[0].fused_score == pytest.approx(1 / (RRF_K + hit.rank), abs=1e-6)


# --------------------------------------------------------- 7-9 aislamiento


async def test_a_domain_scope_covers_both_authorised_assets(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 7."""
    hybrid, _ = await ready(stack)

    found = await hybrid.search(
        query="lubricación del rodamiento", scopes=ALL_MAINTENANCE, limit=50
    )

    assert {e.provenance.document.code for e in found.evidence} == {"manual-a", "manual-b"}


async def test_an_asset_scope_excludes_the_other_asset_entirely(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 8: ni un solo pasaje de `asset-b`, por ningún canal."""
    hybrid, _ = await ready(stack)

    found = await hybrid.search(query="lubricación del rodamiento", scopes=ONLY_A, limit=50)

    assert found.evidence
    assert {e.provenance.document.code for e in found.evidence} == {"manual-a"}
    assert all(e.scope == Scope("mantenimiento", "asset-a") for e in found.evidence)


async def test_the_best_match_overall_never_enters_the_fusion_when_it_is_forbidden(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 9, el crítico.

    «Para lubricar el rodamiento hay que aplicar grasa cada 500 horas» está en
    el manual de `asset-b` y es la mejor coincidencia del corpus para esta
    consulta. Con permiso solo sobre `asset-a` **no puede aparecer**, y no
    porque se filtre al final: no llega a entrar en la fusión.

    Con el adaptador determinista quien la corona es el canal léxico, no el
    denso: un embedder basado en hash no produce similitud con sentido. Lo que
    esta prueba fija es que **ningún** canal deja pasar un pasaje prohibido,
    que es la garantía que importa; el orden semántico real se ejercita con
    BGE-M3 en PC1.
    """
    hybrid, _ = await ready(stack)
    question = "para lubricar el rodamiento hay que aplicar grasa cada 500 horas"

    # Con permiso de dominio, el pasaje de asset-b sí es el mejor: la trampa
    # existe de verdad, no es un caso vacío.
    permitted = await hybrid.search(query=question, scopes=ALL_MAINTENANCE, limit=50)
    assert permitted.evidence[0].provenance.document.code == "manual-b"

    restricted = await hybrid.search(query=question, scopes=ONLY_A, limit=50)
    assert all(e.provenance.document.code == "manual-a" for e in restricted.evidence)
    assert all("bomba" not in e.provenance.chunk.content.lower() for e in restricted.evidence)


# ------------------------------------------------- 10-13 estado y contrato


async def test_an_unpublished_version_is_excluded_from_every_channel(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 10."""
    documents, vectors, lexical = stack
    hybrid, model_id = await ready(stack)
    doc = await documents.get_document(domain="mantenimiento", code="manual-a")
    assert doc is not None
    draft = await documents.store_version(
        await version_input(documents, doc, MANUAL_A + "\n\n## 4. Secreto\n\nSAP-4471 revisión.\n"),
        actor=ACTOR,
    )
    adapter = FakeEmbeddingsAdapter(dimension=DIMENSION)
    await embed(documents, vectors, adapter, model_id, draft.id)

    found = await hybrid.search(query="SAP-4471", scopes=ALL_MAINTENANCE, limit=50)

    assert found.evidence
    assert all(e.provenance.version.id != draft.id for e in found.evidence)
    assert all(e.provenance.version.state is DocumentVersionState.PUBLISHED for e in found.evidence)


async def test_without_an_active_model_the_other_channels_still_answer(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 11: el canal denso no participa, y los códigos se siguen encontrando."""
    hybrid, _ = await ready(stack, activate=False)

    found = await hybrid.search(query="¿qué pasa con el SAP-4471?", scopes=ALL_MAINTENANCE)

    assert Channel.SEMANTIC not in found.channels_queried
    assert found.evidence and found.evidence[0].has_exact_match
    assert all(Channel.SEMANTIC not in e.channels for e in found.evidence)


async def test_every_result_carries_provenance_enough_to_cite_it(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 12."""
    hybrid, _ = await ready(stack)

    found = await hybrid.search(query="par de apriete", scopes=ALL_MAINTENANCE)

    assert found.evidence
    for item in found.evidence:
        p = item.provenance
        assert p.chunk.id and p.chunk.content and p.chunk.ordinal >= 0
        assert p.document.code and p.document.domain and p.document.title
        assert p.version.version_number >= 1
        assert p.source_sha256 and p.source_storage_key
        assert p.chunk.page_start is not None and p.chunk.page_end is not None
        assert item.citation()
        assert item.hits and item.fused_score > 0 and item.rank >= 1


async def test_a_query_without_scopes_opens_nothing(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 13: sin alcances no se devuelve «todo», se devuelve nada."""
    hybrid, _ = await ready(stack)

    empty = await hybrid.search(query="rodamiento", scopes=[])

    assert empty.is_empty and len(empty) == 0
    assert empty.strength is EvidenceStrength.NONE
    assert (await hybrid.search(query="   ", scopes=ALL_MAINTENANCE)).is_empty
    assert (await hybrid.search(query="rodamiento", scopes=ALL_MAINTENANCE, limit=0)).is_empty


# ------------------------------------------------- 15, 17-18 forma y límites


async def test_the_absence_of_evidence_is_stated_not_disguised(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore, PostgresLexicalSearch],
) -> None:
    """Caso 15: sin resultados se dice; no se devuelve lo mejor de nada."""
    hybrid, _ = await ready(stack)

    found = await hybrid.search(
        query="calibración de la balanza", scopes=[Scope("laboratorio", None)]
    )

    assert found.is_empty
    assert found.strength is EvidenceStrength.NONE
    assert found.channels_queried  # se consultó, simplemente no había nada


def test_no_approximate_index_and_no_dependency_on_rag_or_an_llm() -> None:
    """Casos 17 y 18, por AST y por texto del SQL."""
    import ast
    import pathlib

    watched = (
        "src/elsa/services/hybrid_retrieval.py",
        "src/elsa/adapters/postgres_lexical.py",
        "src/elsa/ports/evidence.py",
        "src/elsa/core/query_signals.py",
    )
    for name in watched:
        source = pathlib.Path(name).read_text(encoding="utf-8")
        lowered = source.lower()
        assert "hnsw" not in lowered and "ivfflat" not in lowered, name
        for node in ast.walk(ast.parse(source)):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            assert not any("llm" in m.lower() or "rag" in m.lower() for m in modules), name
