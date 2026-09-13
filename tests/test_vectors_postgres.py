"""Almacenamiento vectorial verificado contra PostgreSQL 16 con pgvector real.

Los embeddings son sintéticos y deterministas a propósito: lo que se prueba
aquí es la persistencia, la activación, la idempotencia y el filtrado de la
recuperación, no la calidad de ningún modelo — eso ya se midió en 4.2.a.
"""

import hashlib
import math
from collections.abc import AsyncIterator

import asyncpg
import pytest

from elsa.adapters.postgres_documents import PostgresDocumentRepository
from elsa.adapters.postgres_vectors import PostgresVectorStore
from elsa.core.authorization import Scope
from elsa.ports.documents import DocumentVersionState
from elsa.ports.knowledge import KnowledgeUnavailableError
from elsa.ports.vectors import (
    ActiveModelError,
    EmbeddingModelSpec,
    EmbeddingRunStatus,
    ModelState,
    PendingEmbedding,
    VectorIntegrityError,
    VectorStorePort,
)
from tests import db
from tests import fixtures_documents as fx
from tests.test_document_repository import ACTOR, document, service, version_input

pytestmark = pytest.mark.anyio

BGE = EmbeddingModelSpec(
    family="bge",
    model_id="BAAI/bge-m3",
    revision="c2b0a4f",
    dimension=1024,
    normalized=True,
    composition_template="context-v1",
    runtime="sentence-transformers",
)
GEMMA = EmbeddingModelSpec(
    family="gemma",
    model_id="google/embeddinggemma-300m",
    revision="9d1e2f0",
    dimension=768,
    normalized=True,
    composition_template="context-v1",
    runtime="sentence-transformers",
    document_prefix="title: none | text: ",
    query_prefix="task: search result | query: ",
)


def synthetic(seed: int, dimension: int) -> list[float]:
    """Vector normalizado y determinista. Mismo `seed`, mismo vector."""
    raw = [math.sin(seed * 0.7 + i * 0.013) for i in range(dimension)]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


def digest(marker: str) -> str:
    """SHA-256 determinista de una marca. El esquema exige 64 hex."""
    return hashlib.sha256(marker.encode()).hexdigest()


@pytest.fixture
async def store() -> AsyncIterator[PostgresVectorStore]:
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
    vectors = await PostgresVectorStore.connect(url, min_size=2, max_size=6)
    try:
        yield vectors
    finally:
        await vectors.close()


@pytest.fixture
async def documents() -> AsyncIterator[PostgresDocumentRepository]:
    url = db.database_url()
    if url is None:
        pytest.skip(db.SKIP_REASON)
    repo = await PostgresDocumentRepository.connect(url, min_size=2, max_size=4)
    try:
        yield repo
    finally:
        await repo.close()


async def published_chunks(
    repo: PostgresDocumentRepository, code: str, *, domain: str = "mantenimiento", asset: str | None
) -> tuple[str, list[tuple[str, str]]]:
    """Documento publicado; devuelve `(version_id, [(chunk_id, content_sha256)])`."""
    doc = await document(repo, code, domain=domain, asset=asset)
    data = await version_input(repo, doc, fx.MANUAL_V1 + f"\nDocumento {code}")
    version = await repo.store_version(data, actor=ACTOR)
    await service(repo).approve(version_id=version.id, actor=ACTOR)
    await service(repo).publish(version_id=version.id, actor=ACTOR)
    chunks = await repo.list_chunks(version.id)
    return version.id, [(c.id, c.content_sha256) for c in chunks]


async def embed_all(
    store: PostgresVectorStore,
    repo: PostgresDocumentRepository,
    spec: EmbeddingModelSpec,
    codes: tuple[tuple[str, str | None, str], ...] = (("manual-a", "asset-a", "mantenimiento"),),
    *,
    seed_base: int = 1,
) -> tuple[str, str]:
    """Registra el modelo, corre una ingesta de vectores y la cierra."""
    model = await store.find_model(spec) or await store.register_model(spec, actor=ACTOR)
    run = await store.start_run(model_id=model.id, started_by=ACTOR)
    pending: list[PendingEmbedding] = []
    seed = seed_base
    for code, asset, domain in codes:
        version_id, chunks = await published_chunks(repo, code, domain=domain, asset=asset)
        for chunk_id, content_sha in chunks:
            pending.append(
                PendingEmbedding(
                    chunk_id=chunk_id,
                    version_id=version_id,
                    embedding=synthetic(seed, spec.dimension),
                    embedded_sha256=digest(f"e{seed}"),
                    content_sha256=content_sha,
                )
            )
            seed += 1
    generated, reused = await store.store_embeddings(run_id=run.id, embeddings=pending)
    await store.finish_run(run_id=run.id, generated=generated, reused=reused)
    return model.id, run.id


# ---------------------------------------------------------------- 1-2 modelos


async def test_a_model_is_registered_inactive_because_generating_does_not_activate(
    store: PostgresVectorStore,
) -> None:
    assert isinstance(store, VectorStorePort)
    model = await store.register_model(BGE, actor=ACTOR)

    assert model.state is ModelState.REGISTERED and not model.is_active
    assert model.spec.dimension == 1024 and model.activated_at is None
    assert await store.get_active_model() is None
    assert await store.get_model(model.id) == model
    assert await store.find_model(BGE) == model


async def test_incompatible_or_duplicate_model_registrations_are_rejected(
    store: PostgresVectorStore,
) -> None:
    await store.register_model(BGE, actor=ACTOR)

    # El mismo espacio vectorial no se registra dos veces.
    with pytest.raises(VectorIntegrityError):
        await store.register_model(BGE, actor=ACTOR)

    # `main` es una referencia móvil: ADR 0013 §2 la prohíbe.
    with pytest.raises(VectorIntegrityError):
        await store.register_model(
            EmbeddingModelSpec(**{**vars_of(BGE), "revision": "main"}), actor=ACTOR
        )

    # Coseno exige vectores normalizados.
    with pytest.raises(VectorIntegrityError):
        await store.register_model(
            EmbeddingModelSpec(**{**vars_of(BGE), "revision": "aaa111", "normalized": False}),
            actor=ACTOR,
        )

    # Cambiar un prefijo es OTRO espacio vectorial, y sí se admite.
    other = await store.register_model(
        EmbeddingModelSpec(**{**vars_of(BGE), "query_prefix": "q: "}), actor=ACTOR
    )
    assert other.spec.query_prefix == "q: "


def vars_of(spec: EmbeddingModelSpec) -> dict[str, object]:
    return {
        f: getattr(spec, f)
        for f in (
            "family",
            "model_id",
            "revision",
            "dimension",
            "normalized",
            "composition_template",
            "runtime",
            "document_prefix",
            "query_prefix",
            "similarity",
            "notes",
        )
    }


async def test_a_registered_model_is_immutable_except_for_its_state(
    store: PostgresVectorStore,
) -> None:
    """Cambiar la revisión o un prefijo volvería mentira los vectores ya escritos."""
    model = await store.register_model(BGE, actor=ACTOR)
    conn = await asyncpg.connect(db.database_url())
    try:
        for column, value in (("revision", "otra"), ("query_prefix", "q: "), ("dimension", 512)):
            with pytest.raises(asyncpg.PostgresError):
                await conn.execute(
                    f"update elsa.embedding_models set {column} = $2 where id = $1",
                    model.id,
                    value,
                )
    finally:
        await conn.close()


# ------------------------------------------------------------- 3-5 corridas


async def test_a_run_records_what_it_produced(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    model_id, run_id = await embed_all(store, documents, BGE)
    run = await store.get_run(run_id)

    assert run is not None and run.status is EmbeddingRunStatus.COMPLETED
    assert run.model_id == model_id and run.generated > 0 and run.reused == 0
    assert run.finished_at is not None and run.started_by == ACTOR


async def test_a_run_cannot_be_started_for_an_unknown_model(store: PostgresVectorStore) -> None:
    with pytest.raises(VectorIntegrityError):
        await store.start_run(model_id="00000000-0000-4000-8000-000000000000", started_by=ACTOR)


async def test_embedding_the_same_text_twice_reuses_instead_of_recomputing(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    """Idempotencia por `embedded_sha256`: mismo texto, mismo modelo, no se recalcula."""
    model_id, _ = await embed_all(store, documents, BGE)
    version_id, chunks = await published_chunks(documents, "manual-b", asset="asset-b")
    second = await store.start_run(model_id=model_id, started_by=ACTOR)
    # La primera corrida ya escribió los chunks de manual-a con estos hashes.
    repeat = [
        PendingEmbedding(
            chunk_id=chunk_id,
            version_id=version_id,
            embedding=synthetic(500 + i, 1024),
            embedded_sha256=digest(f"e{500 + i}"),
            content_sha256=sha,
        )
        for i, (chunk_id, sha) in enumerate(chunks)
    ]
    generated, reused = await store.store_embeddings(run_id=second.id, embeddings=repeat)
    assert (generated, reused) == (len(chunks), 0)

    third = await store.start_run(model_id=model_id, started_by=ACTOR)
    generated, reused = await store.store_embeddings(run_id=third.id, embeddings=repeat)
    assert (generated, reused) == (0, len(chunks))


async def test_only_the_chunks_whose_text_changed_are_stale(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    model_id, _ = await embed_all(store, documents, BGE)
    conn = await asyncpg.connect(db.database_url())
    try:
        rows = await conn.fetch(
            "select chunk_id, embedded_sha256 from elsa.document_chunk_embeddings "
            "where model_id = $1 order by chunk_id",
            model_id,
        )
    finally:
        await conn.close()
    current = [(str(r["chunk_id"]), r["embedded_sha256"]) for r in rows]

    assert await store.stale_chunks(model_id=model_id, expected=current) == ()

    changed = [(current[0][0], digest("ff")), *current[1:]]
    assert await store.stale_chunks(model_id=model_id, expected=changed) == (current[0][0],)


# ------------------------------------------------- 6-7 cambio y coexistencia


async def test_two_models_of_different_dimensions_coexist_over_the_same_chunks(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    """768 y 1024 en la misma tabla: es lo que permite cambiar de modelo."""
    bge_id, _ = await embed_all(store, documents, BGE)
    version_id, chunks = await published_chunks(documents, "manual-b", asset="asset-b")
    gemma = await store.register_model(GEMMA, actor=ACTOR)
    run = await store.start_run(model_id=gemma.id, started_by=ACTOR)
    await store.store_embeddings(
        run_id=run.id,
        embeddings=[
            PendingEmbedding(
                chunk_id=chunk_id,
                version_id=version_id,
                embedding=synthetic(900 + i, 768),
                embedded_sha256=digest(f"g{900 + i}"),
                content_sha256=sha,
            )
            for i, (chunk_id, sha) in enumerate(chunks)
        ],
    )
    await store.finish_run(run_id=run.id, generated=len(chunks), reused=0)

    conn = await asyncpg.connect(db.database_url())
    try:
        sizes = await conn.fetch(
            "select dimension, count(*) as n, min(vector_dims(embedding)) as real_dim "
            "from elsa.document_chunk_embeddings group by dimension order by dimension"
        )
    finally:
        await conn.close()
    assert [(r["dimension"], r["real_dim"]) for r in sizes] == [(768, 768), (1024, 1024)]
    assert {str(r["dimension"]) for r in sizes} == {"768", "1024"}
    assert bge_id != gemma.id


async def test_a_vector_cannot_lie_about_its_dimension(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    """El esquema ata la dimensión al modelo; no depende del adaptador."""
    model = await store.register_model(GEMMA, actor=ACTOR)
    version_id, chunks = await published_chunks(documents, "manual-a", asset="asset-a")
    run = await store.start_run(model_id=model.id, started_by=ACTOR)

    with pytest.raises(VectorIntegrityError):
        await store.store_embeddings(
            run_id=run.id,
            embeddings=[
                PendingEmbedding(
                    chunk_id=chunks[0][0],
                    version_id=version_id,
                    embedding=synthetic(1, 1024),  # el modelo es de 768
                    embedded_sha256=digest("aa"),
                    content_sha256=chunks[0][1],
                )
            ],
        )


# --------------------------------------------------------- 8-10 activación


async def test_activation_is_explicit_and_at_most_one_model_is_active(
    store: PostgresVectorStore,
) -> None:
    bge = await store.register_model(BGE, actor=ACTOR)
    gemma = await store.register_model(GEMMA, actor=ACTOR)
    assert await store.get_active_model() is None

    activated = await store.activate_model(model_id=bge.id, actor=ACTOR)
    assert activated.is_active and activated.activated_at is not None
    active = await store.get_active_model()
    assert active is not None and active.id == bge.id

    # Registrar otro modelo no desactiva el activo.
    assert (await store.get_active_model()).id == bge.id  # type: ignore[union-attr]

    await store.activate_model(model_id=gemma.id, actor=ACTOR)
    active = await store.get_active_model()
    assert active is not None and active.id == gemma.id
    previous = await store.get_model(bge.id)
    assert previous is not None and previous.state is ModelState.REGISTERED

    conn = await asyncpg.connect(db.database_url())
    try:
        assert (
            await conn.fetchval("select count(*) from elsa.embedding_models where state='active'")
            == 1
        )
    finally:
        await conn.close()


async def test_rolling_back_an_activation_does_not_regenerate_anything(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    """Volver atrás es activar otra vez: los vectores del anterior siguen ahí."""
    bge_id, _ = await embed_all(store, documents, BGE)
    await store.activate_model(model_id=bge_id, actor=ACTOR)
    gemma = await store.register_model(GEMMA, actor=ACTOR)
    await store.activate_model(model_id=gemma.id, actor=ACTOR)

    conn = await asyncpg.connect(db.database_url())
    try:
        before = await conn.fetchval(
            "select count(*) from elsa.document_chunk_embeddings where model_id=$1", bge_id
        )
    finally:
        await conn.close()
    assert before > 0

    back = await store.activate_model(model_id=bge_id, actor=ACTOR)
    assert back.is_active

    conn = await asyncpg.connect(db.database_url())
    try:
        after = await conn.fetchval(
            "select count(*) from elsa.document_chunk_embeddings where model_id=$1", bge_id
        )
    finally:
        await conn.close()
    assert after == before


async def test_retrieval_without_an_active_model_is_refused_not_answered(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    """Un modelo inactivo no participa, y el sistema lo declara."""
    await embed_all(store, documents, BGE)

    with pytest.raises(ActiveModelError):
        await store.search(
            query_embedding=synthetic(1, 1024), scopes=[Scope("mantenimiento", "asset-a")]
        )


# ----------------------------------------------------- 11-16 recuperación


async def test_exact_search_ranks_by_distance_and_carries_full_provenance(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    model_id, _ = await embed_all(store, documents, BGE)
    await store.activate_model(model_id=model_id, actor=ACTOR)

    # La consulta es exactamente el vector del chunk sembrado con seed=1.
    found = await store.search(
        query_embedding=synthetic(1, 1024),
        scopes=[Scope("mantenimiento", "asset-a")],
        limit=5,
    )
    assert found
    best = found[0]
    assert best.distance == pytest.approx(0.0, abs=1e-6)
    assert best.similarity == pytest.approx(1.0, abs=1e-6)
    assert [s.distance for s in found] == sorted(s.distance for s in found)
    assert best.model_id == model_id

    p = best.provenance
    assert p.document.code == "manual-a" and p.document.domain == "mantenimiento"
    assert p.version.state is DocumentVersionState.PUBLISHED and p.version.version_number == 1
    assert p.chunk.content and p.chunk.ordinal >= 0
    assert p.chunk.page_start is not None and p.chunk.page_end is not None
    assert p.source_sha256 and p.source_storage_key
    assert p.scope == Scope("mantenimiento", "asset-a")
    assert p.citation()


async def test_an_unpublished_version_never_reaches_retrieval(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    model_id, _ = await embed_all(store, documents, BGE)
    await store.activate_model(model_id=model_id, actor=ACTOR)

    # Segunda versión del mismo documento: ingerida y embebida, sin publicar.
    doc = await documents.get_document(domain="mantenimiento", code="manual-a")
    assert doc is not None
    data = await version_input(documents, doc, fx.MANUAL_V2)
    draft = await documents.store_version(data, actor=ACTOR)
    chunks = await documents.list_chunks(draft.id)
    run = await store.start_run(model_id=model_id, started_by=ACTOR)
    await store.store_embeddings(
        run_id=run.id,
        embeddings=[
            PendingEmbedding(
                chunk_id=c.id,
                version_id=draft.id,
                embedding=synthetic(1, 1024),  # idéntico a la consulta
                embedded_sha256=digest(f"d{i}"),
                content_sha256=c.content_sha256,
            )
            for i, c in enumerate(chunks)
        ],
    )
    await store.finish_run(run_id=run.id, generated=len(chunks), reused=0)

    found = await store.search(
        query_embedding=synthetic(1, 1024),
        scopes=[Scope("mantenimiento", "asset-a")],
        limit=20,
    )
    assert found
    assert {s.provenance.version.id for s in found} == {
        s.provenance.version.id for s in found if s.provenance.version.id != draft.id
    }
    assert all(s.provenance.version.state is DocumentVersionState.PUBLISHED for s in found)


async def test_a_domain_permission_covers_every_asset_of_that_domain(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    model_id, _ = await embed_all(
        store,
        documents,
        BGE,
        (("manual-a", "asset-a", "mantenimiento"), ("manual-b", "asset-b", "mantenimiento")),
    )
    await store.activate_model(model_id=model_id, actor=ACTOR)

    found = await store.search(
        query_embedding=synthetic(1, 1024), scopes=[Scope("mantenimiento", None)], limit=50
    )
    assert {s.provenance.document.code for s in found} == {"manual-a", "manual-b"}


async def test_an_asset_permission_covers_only_that_asset(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    model_id, _ = await embed_all(
        store,
        documents,
        BGE,
        (("manual-a", "asset-a", "mantenimiento"), ("manual-b", "asset-b", "mantenimiento")),
    )
    await store.activate_model(model_id=model_id, actor=ACTOR)

    found = await store.search(
        query_embedding=synthetic(1, 1024), scopes=[Scope("mantenimiento", "asset-a")], limit=50
    )
    assert {s.provenance.document.code for s in found} == {"manual-a"}


async def test_another_domain_never_appears(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    model_id, _ = await embed_all(
        store,
        documents,
        BGE,
        (("manual-a", "asset-a", "mantenimiento"), ("manual-lab", "asset-c", "laboratorio")),
    )
    await store.activate_model(model_id=model_id, actor=ACTOR)

    assert await store.search(
        query_embedding=synthetic(1, 1024), scopes=[Scope("laboratorio", None)], limit=50
    )
    found = await store.search(
        query_embedding=synthetic(1, 1024), scopes=[Scope("mantenimiento", None)], limit=50
    )
    assert all(s.provenance.document.domain == "mantenimiento" for s in found)
    assert (
        await store.search(
            query_embedding=synthetic(1, 1024), scopes=[Scope("laboratorio", "asset-a")], limit=50
        )
        == ()
    )
    assert await store.search(query_embedding=synthetic(1, 1024), scopes=[], limit=50) == ()


# ------------------------------------------------ 17-18 integridad y fallos


async def test_a_partial_failure_leaves_no_half_written_run(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    """O entran todos los vectores o no entra ninguno."""
    model = await store.register_model(BGE, actor=ACTOR)
    version_id, chunks = await published_chunks(documents, "manual-a", asset="asset-a")
    run = await store.start_run(model_id=model.id, started_by=ACTOR)
    good = PendingEmbedding(
        chunk_id=chunks[0][0],
        version_id=version_id,
        embedding=synthetic(1, 1024),
        embedded_sha256=digest("a1"),
        content_sha256=chunks[0][1],
    )
    bad = PendingEmbedding(
        chunk_id=chunks[-1][0],
        version_id=version_id,
        embedding=synthetic(2, 512),  # dimensión que no es la del modelo
        embedded_sha256=digest("a2"),
        content_sha256=chunks[-1][1],
    )

    with pytest.raises(VectorIntegrityError):
        await store.store_embeddings(run_id=run.id, embeddings=[good, bad])

    conn = await asyncpg.connect(db.database_url())
    try:
        assert await conn.fetchval("select count(*) from elsa.document_chunk_embeddings") == 0
    finally:
        await conn.close()

    failed = await store.fail_run(
        run_id=run.id, failure_kind="model", failure_message="synthetic failure"
    )
    assert failed.status is EmbeddingRunStatus.FAILED
    with pytest.raises(VectorIntegrityError):
        await store.store_embeddings(run_id=run.id, embeddings=[good])


async def test_direct_sql_cannot_break_the_critical_relations(
    store: PostgresVectorStore, documents: PostgresDocumentRepository
) -> None:
    """La garantía es del esquema, así que se prueba sin pasar por el adaptador."""
    model_id, _ = await embed_all(store, documents, BGE)
    gemma = await store.register_model(GEMMA, actor=ACTOR)
    conn = await asyncpg.connect(db.database_url())
    try:
        row = await conn.fetchrow(
            "select chunk_id, version_id, run_id from elsa.document_chunk_embeddings limit 1"
        )
        other_version = await conn.fetchval(
            "select id from elsa.document_versions where id <> $1 limit 1", row["version_id"]
        )

        # Declarar una dimensión que no es la del modelo: Gemma es de 768.
        # El par (chunk, gemma) no existe aún, así que quien rechaza es la
        # clave foránea compuesta, no la primaria.
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "insert into elsa.document_chunk_embeddings "
                "(chunk_id, model_id, version_id, run_id, dimension, embedding, "
                " embedded_sha256, content_sha256) values ($1,$2,$3,$4,1024,$5::vector,$6,$6)",
                row["chunk_id"],
                gemma.id,
                row["version_id"],
                row["run_id"],
                "[" + ",".join(["0.1"] * 1024) + "]",
                digest("bb"),
            )
        # Un vector cuyo tamaño no es el que la fila declara.
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "insert into elsa.document_chunk_embeddings "
                "(chunk_id, model_id, version_id, run_id, dimension, embedding, "
                " embedded_sha256, content_sha256) values ($1,$2,$3,$4,768,$5::vector,$6,$6)",
                row["chunk_id"],
                gemma.id,
                row["version_id"],
                row["run_id"],
                "[" + ",".join(["0.1"] * 1024) + "]",
                digest("cc"),
            )
        # Un embedding que dice pertenecer a otra versión que su chunk.
        if other_version is not None:
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    "update elsa.document_chunk_embeddings set version_id=$1", other_version
                )
        # Un modelo no puede declararse activo sin fecha de activación.
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute(
                "update elsa.embedding_models set state='active' where id=$1", model_id
            )
        # Y dos modelos no pueden estar activos a la vez, aunque se escriba
        # por SQL directo: lo impide el índice único parcial.
        await conn.execute(
            "update elsa.embedding_models set state='active', activated_at=now() where id=$1",
            model_id,
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "update elsa.embedding_models set state='active', activated_at=now() "
                "where id=$1",
                gemma.id,
            )
    finally:
        await conn.close()


async def test_a_closed_pool_is_reported_as_unavailable(
    store: PostgresVectorStore,
) -> None:
    await store.check_health()
    await store.close()

    with pytest.raises(KnowledgeUnavailableError):
        await store.get_active_model()
