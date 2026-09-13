"""Integración productiva del motor de embeddings (Bloque 4.2.a etapa C).

Casi todo se prueba con el adaptador determinista: lo que está bajo prueba es
el cableado —composición, idempotencia, corridas, activación y filtrado—, no la
calidad de ningún modelo, que ya se midió en 4.2.a y no se vuelve a medir.
"""

from collections.abc import AsyncIterator, Sequence

import asyncpg
import pytest
from fastapi.testclient import TestClient

from elsa.adapters.fake_embeddings import FakeEmbeddingsAdapter
from elsa.adapters.postgres_documents import PostgresDocumentRepository
from elsa.adapters.postgres_vectors import PostgresVectorStore
from elsa.adapters.sentence_transformer_embeddings import SentenceTransformerEmbeddings
from elsa.core.authorization import Scope
from elsa.documents.composition import compose_for_embedding
from elsa.ports.documents import DocumentVersionState
from elsa.ports.embeddings import (
    EmbeddingConfigurationError,
    EmbeddingDimensionError,
    EmbeddingModelDescriptor,
    ModelUnavailableError,
)
from elsa.ports.vectors import EmbeddingModelSpec, EmbeddingRunStatus, ModelState
from elsa.services.embedding_generation import EmbeddingGenerationService
from elsa.services.semantic_retrieval import SemanticRetrievalService
from tests import db
from tests import fixtures_documents as fx
from tests.test_document_repository import ACTOR, document, service, version_input

pytestmark = pytest.mark.anyio

DIMENSION = 16


def spec_of(adapter: FakeEmbeddingsAdapter) -> EmbeddingModelSpec:
    d = adapter.describe()
    return EmbeddingModelSpec(
        family=d.family,
        model_id=d.model_id,
        revision=d.revision,
        dimension=d.dimension,
        normalized=d.normalized,
        composition_template=d.composition_template,
        runtime=d.runtime,
        document_prefix=d.document_prefix,
        query_prefix=d.query_prefix,
    )


@pytest.fixture
async def stack() -> AsyncIterator[tuple[PostgresDocumentRepository, PostgresVectorStore]]:
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
            "('asset-a','A','mantenimiento'),('asset-b','B','mantenimiento'),"
            "('asset-c','C','laboratorio')"
        )
    finally:
        await conn.close()
    documents = await PostgresDocumentRepository.connect(url, min_size=2, max_size=4)
    vectors = await PostgresVectorStore.connect(url, min_size=2, max_size=4)
    try:
        yield documents, vectors
    finally:
        await vectors.close()
        await documents.close()


async def publish(
    repo: PostgresDocumentRepository,
    code: str,
    *,
    domain: str = "mantenimiento",
    asset: str | None = "asset-a",
    text: str = fx.MANUAL_V1,
) -> str:
    doc = await document(repo, code, domain=domain, asset=asset)
    data = await version_input(repo, doc, text + f"\nDocumento {code}")
    version = await repo.store_version(data, actor=ACTOR)
    await service(repo).approve(version_id=version.id, actor=ACTOR)
    await service(repo).publish(version_id=version.id, actor=ACTOR)
    return version.id


def generation(
    documents: PostgresDocumentRepository,
    vectors: PostgresVectorStore,
    adapter: FakeEmbeddingsAdapter,
    *,
    batch_size: int = 4,
) -> EmbeddingGenerationService:
    return EmbeddingGenerationService(
        documents=documents, vectors=vectors, embeddings=adapter, batch_size=batch_size
    )


# ------------------------------------------------ configuración del adaptador


def test_a_moving_revision_is_refused_as_a_production_identity() -> None:
    """`main` no identifica unos pesos: lo de mañana puede no ser lo medido."""
    for moving in ("main", "master", "latest", ""):
        with pytest.raises(EmbeddingConfigurationError):
            SentenceTransformerEmbeddings(model_id="BAAI/bge-m3", revision=moving, dimension=1024)


def test_the_configuration_reproduces_the_prefixes_of_each_model() -> None:
    """Nada del modelo está codificado: EmbeddingGemma se habilita por config."""
    gemma = SentenceTransformerEmbeddings(
        model_id="google/embeddinggemma-300m",
        revision="9d1e2f0",
        dimension=768,
        document_prefix="title: none | text: ",
        query_prefix="task: search result | query: ",
    )
    bge = SentenceTransformerEmbeddings(model_id="BAAI/bge-m3", revision="c2b0a4f", dimension=1024)

    assert gemma.describe().query_prefix == "task: search result | query: "
    assert gemma.describe().dimension == 768 and gemma.describe().family == "google"
    assert bge.describe().document_prefix == "" and bge.describe().dimension == 1024
    # Describir no carga el modelo: ninguna de las dos descargó nada.
    assert gemma.describe().runtime == "sentence-transformers"


async def test_an_unavailable_model_fails_explicitly_instead_of_returning_nothing() -> None:
    """Un modelo que no se puede cargar es un error, no una lista vacía."""
    adapter = SentenceTransformerEmbeddings(
        model_id="elsa/does-not-exist", revision="0000000", dimension=8
    )

    with pytest.raises(ModelUnavailableError):
        await adapter.embed_documents(["texto"])


async def test_a_wrong_dimension_is_refused_never_truncated_or_padded() -> None:
    class Lying:
        """Emite 4 dimensiones diciendo que produce 8."""

        def encode(self, texts: list[str], **_: object) -> list[list[float]]:
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    adapter = SentenceTransformerEmbeddings(model_id="fake/liar", revision="0000001", dimension=8)
    adapter._model = Lying()  # noqa: SLF001 - se evita descargar un modelo real

    with pytest.raises(EmbeddingDimensionError):
        await adapter.embed_documents(["texto"])


# -------------------------------------------------------------- generación


async def test_generation_embeds_the_composed_text_not_the_raw_chunk(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
) -> None:
    """Producción embebe lo mismo que midió el banco: `context-v1`."""
    documents, vectors = stack
    adapter = FakeEmbeddingsAdapter(dimension=DIMENSION)
    model = await vectors.register_model(spec_of(adapter), actor=ACTOR)
    version_id = await publish(documents, "manual-a")

    outcome = await generation(documents, vectors, adapter).generate_for_version(
        model_id=model.id, version_id=version_id, actor=ACTOR
    )
    assert outcome.generated == outcome.considered > 0

    chunks = await documents.list_chunks(version_id)
    version = await documents.get_version(version_id)
    assert version is not None
    doc = await documents.get_document_by_id(version.document_id)
    assert doc is not None
    expected = compose_for_embedding(
        content=chunks[0].content,
        document_title=doc.title,
        heading_trail=chunks[0].heading_trail,
    )
    conn = await asyncpg.connect(db.database_url())
    try:
        stored = await conn.fetchval(
            "select embedded_sha256 from elsa.document_chunk_embeddings where chunk_id=$1",
            chunks[0].id,
        )
    finally:
        await conn.close()
    assert stored == expected.embedded_sha256


async def test_an_unchanged_chunk_is_reused_and_a_changed_one_is_re_embedded(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
) -> None:
    documents, vectors = stack
    adapter = FakeEmbeddingsAdapter(dimension=DIMENSION)
    model = await vectors.register_model(spec_of(adapter), actor=ACTOR)
    version_id = await publish(documents, "manual-a")
    service_ = generation(documents, vectors, adapter)

    first = await service_.generate_for_version(
        model_id=model.id, version_id=version_id, actor=ACTOR
    )
    second = await service_.generate_for_version(
        model_id=model.id, version_id=version_id, actor=ACTOR
    )
    assert first.generated > 0 and second.generated == 0
    assert second.reused == second.considered

    # Otra versión, con texto distinto: sus chunks sí hay que embeberlos.
    other = await publish(documents, "manual-b", asset="asset-b", text=fx.MANUAL_V2)
    third = await service_.generate_for_version(model_id=model.id, version_id=other, actor=ACTOR)
    assert third.generated == third.considered > 0


async def test_a_different_model_produces_an_independent_vector_space(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
) -> None:
    documents, vectors = stack
    small = FakeEmbeddingsAdapter(dimension=DIMENSION, model_id="fake/small", revision="r1")
    large = FakeEmbeddingsAdapter(dimension=64, model_id="fake/large", revision="r2")
    first = await vectors.register_model(spec_of(small), actor=ACTOR)
    second = await vectors.register_model(spec_of(large), actor=ACTOR)
    version_id = await publish(documents, "manual-a")

    await generation(documents, vectors, small).generate_for_version(
        model_id=first.id, version_id=version_id, actor=ACTOR
    )
    await generation(documents, vectors, large).generate_for_version(
        model_id=second.id, version_id=version_id, actor=ACTOR
    )

    conn = await asyncpg.connect(db.database_url())
    try:
        rows = await conn.fetch(
            "select dimension, count(*) as n from elsa.document_chunk_embeddings "
            "group by dimension order by dimension"
        )
    finally:
        await conn.close()
    assert [row["dimension"] for row in rows] == [DIMENSION, 64]
    assert rows[0]["n"] == rows[1]["n"] > 0


async def test_embedding_with_a_model_that_is_not_the_registered_one_is_refused(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
) -> None:
    """Anotar un vector como de otro modelo produciría un índice que miente."""
    documents, vectors = stack
    registered = FakeEmbeddingsAdapter(dimension=DIMENSION, model_id="fake/a", revision="r1")
    different = FakeEmbeddingsAdapter(dimension=DIMENSION, model_id="fake/b", revision="r2")
    model = await vectors.register_model(spec_of(registered), actor=ACTOR)
    version_id = await publish(documents, "manual-a")

    with pytest.raises(EmbeddingConfigurationError):
        await generation(documents, vectors, different).generate_for_version(
            model_id=model.id, version_id=version_id, actor=ACTOR
        )


async def test_a_failing_run_ends_as_failed_and_never_as_completed(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
) -> None:
    documents, vectors = stack

    class Breaks(FakeEmbeddingsAdapter):
        async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
            raise ModelUnavailableError("synthetic failure")

    adapter = Breaks(dimension=DIMENSION)
    model = await vectors.register_model(spec_of(adapter), actor=ACTOR)
    version_id = await publish(documents, "manual-a")

    with pytest.raises(ModelUnavailableError):
        await generation(documents, vectors, adapter).generate_for_version(
            model_id=model.id, version_id=version_id, actor=ACTOR
        )

    conn = await asyncpg.connect(db.database_url())
    try:
        run = await conn.fetchrow("select status, failure_kind from elsa.embedding_runs")
    finally:
        await conn.close()
    assert run["status"] == EmbeddingRunStatus.FAILED.value
    assert run["failure_kind"] == "model"


async def test_generating_does_not_activate_anything(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
) -> None:
    documents, vectors = stack
    adapter = FakeEmbeddingsAdapter(dimension=DIMENSION)
    model = await vectors.register_model(spec_of(adapter), actor=ACTOR)
    version_id = await publish(documents, "manual-a")

    await generation(documents, vectors, adapter).generate_for_version(
        model_id=model.id, version_id=version_id, actor=ACTOR
    )

    assert await vectors.get_active_model() is None
    stored = await vectors.get_model(model.id)
    assert stored is not None and stored.state is ModelState.REGISTERED

    activated = await vectors.activate_model(model_id=model.id, actor=ACTOR)
    assert activated.state is ModelState.ACTIVE


# ---------------------------------------------------------------- consulta


async def ready(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
    *,
    codes: tuple[tuple[str, str | None, str], ...] = (("manual-a", "asset-a", "mantenimiento"),),
) -> tuple[SemanticRetrievalService, FakeEmbeddingsAdapter]:
    documents, vectors = stack
    adapter = FakeEmbeddingsAdapter(dimension=DIMENSION)
    model = await vectors.register_model(spec_of(adapter), actor=ACTOR)
    for code, asset, domain in codes:
        version_id = await publish(documents, code, domain=domain, asset=asset)
        await generation(documents, vectors, adapter).generate_for_version(
            model_id=model.id, version_id=version_id, actor=ACTOR
        )
    await vectors.activate_model(model_id=model.id, actor=ACTOR)
    return SemanticRetrievalService(vectors=vectors, embeddings=adapter), adapter


async def test_a_query_takes_the_query_path_and_keeps_full_provenance(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
) -> None:
    retrieval, _ = await ready(stack)

    found = await retrieval.search(
        question="¿cuál es el par de apriete?",
        scopes=[Scope("mantenimiento", "asset-a")],
        limit=5,
    )
    assert found
    p = found[0].provenance
    assert p.document.code == "manual-a" and p.version.state is DocumentVersionState.PUBLISHED
    assert p.chunk.content and p.source_sha256 and p.source_storage_key
    assert p.citation()
    assert [hit.distance for hit in found] == sorted(hit.distance for hit in found)


async def test_scopes_are_mandatory_and_an_empty_question_returns_nothing(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
) -> None:
    retrieval, _ = await ready(stack)

    assert await retrieval.search(question="algo", scopes=[]) == ()
    assert await retrieval.search(question="  ", scopes=[Scope("mantenimiento", None)]) == ()
    assert (
        await retrieval.search(question="algo", scopes=[Scope("mantenimiento", None)], limit=0)
        == ()
    )


async def test_a_domain_permission_covers_its_assets_and_an_asset_permission_does_not(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
) -> None:
    retrieval, _ = await ready(
        stack,
        codes=(
            ("manual-a", "asset-a", "mantenimiento"),
            ("manual-b", "asset-b", "mantenimiento"),
            ("manual-lab", "asset-c", "laboratorio"),
        ),
    )

    whole_domain = await retrieval.search(
        question="par de apriete", scopes=[Scope("mantenimiento", None)], limit=50
    )
    assert {hit.provenance.document.code for hit in whole_domain} == {"manual-a", "manual-b"}

    one_asset = await retrieval.search(
        question="par de apriete", scopes=[Scope("mantenimiento", "asset-a")], limit=50
    )
    assert {hit.provenance.document.code for hit in one_asset} == {"manual-a"}

    other_domain = await retrieval.search(
        question="par de apriete", scopes=[Scope("laboratorio", None)], limit=50
    )
    assert {hit.provenance.document.code for hit in other_domain} == {"manual-lab"}


async def test_only_the_active_model_answers_and_unpublished_versions_never_do(
    stack: tuple[PostgresDocumentRepository, PostgresVectorStore],
) -> None:
    documents, vectors = stack
    retrieval, adapter = await ready(stack)

    # Una segunda versión, embebida pero sin publicar, no puede aparecer.
    doc = await documents.get_document(domain="mantenimiento", code="manual-a")
    assert doc is not None
    draft = await documents.store_version(
        await version_input(documents, doc, fx.MANUAL_V2), actor=ACTOR
    )
    model = await vectors.get_active_model()
    assert model is not None
    await generation(documents, vectors, adapter).generate_for_version(
        model_id=model.id, version_id=draft.id, actor=ACTOR
    )

    found = await retrieval.search(
        question="par de apriete", scopes=[Scope("mantenimiento", None)], limit=50
    )
    assert found
    assert all(hit.provenance.version.id != draft.id for hit in found)
    assert all(hit.provenance.version.state is DocumentVersionState.PUBLISHED for hit in found)

    # Retirado el modelo activo, la recuperación se rechaza en vez de responder.
    await vectors.retire_model(model_id=model.id, actor=ACTOR)
    from elsa.ports.vectors import ActiveModelError

    with pytest.raises(ActiveModelError):
        await retrieval.search(question="par", scopes=[Scope("mantenimiento", None)])


# --------------------------------------------------- arranque y aislamiento


def test_fastapi_starts_and_serves_without_any_embedding_runtime(
    client: TestClient,
) -> None:
    """Render Free no puede cargar un modelo, así que ELSA no debe intentarlo.

    Se bloquea `sentence_transformers` como si no estuviera instalado y se
    ejercita la aplicación real: si alguien cableara el motor al arranque,
    esto fallaría en vez de responder.
    """
    import sys
    from unittest import mock

    with mock.patch.dict(sys.modules, {"sentence_transformers": None, "torch": None}):
        assert client.get("/api/v1/health/live").status_code == 200


def test_the_web_application_does_not_import_the_embedding_runtime() -> None:
    """El motor está desacoplado de FastAPI: no basta con no usarlo, no se importa."""
    import ast
    import pathlib

    roots = ("elsa.main", "elsa.web", "elsa.container", "elsa.api")
    offenders: list[str] = []
    for path in pathlib.Path("src/elsa").rglob("*.py"):
        module = ".".join(path.relative_to("src").with_suffix("").parts)
        if not module.startswith(roots):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(
                name.startswith(("sentence_transformers", "torch"))
                or name.endswith("sentence_transformer_embeddings")
                for name in names
            ):
                offenders.append(f"{module} imports {names}")
    assert offenders == []


def test_nothing_in_the_embedding_path_depends_on_rag_or_an_llm() -> None:
    """La etapa C recupera evidencia. Generar respuestas es el Bloque 4.3."""
    import ast
    import pathlib

    watched = (
        "src/elsa/services/embedding_generation.py",
        "src/elsa/services/semantic_retrieval.py",
        "src/elsa/adapters/sentence_transformer_embeddings.py",
        "src/elsa/ports/embeddings.py",
    )
    for name in watched:
        tree = ast.parse(pathlib.Path(name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            assert not any("llm" in m.lower() or "rag" in m.lower() for m in modules), name


def test_the_descriptor_carries_everything_needed_to_reproduce_the_space() -> None:
    descriptor: EmbeddingModelDescriptor = FakeEmbeddingsAdapter(dimension=DIMENSION).describe()

    for field in (
        "model_id",
        "revision",
        "dimension",
        "normalized",
        "composition_template",
        "runtime",
        "family",
        "document_prefix",
        "query_prefix",
        "similarity",
    ):
        assert getattr(descriptor, field) is not None
