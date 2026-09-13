"""Herramienta de operación del motor de embeddings.

Cinco comandos, para ejecutarse desde una máquina con acceso a los pesos —no
desde el servicio web, que en Render Free no puede cargar un modelo
(ADR 0013 §8):

    register   registra la configuración real de un modelo
    generate   embebe los chunks de una versión documental
    activate   elige qué modelo participa en la recuperación
    status     modelos registrados y últimas corridas
    search     una búsqueda de prueba, con alcances explícitos

**`generate` no activa** y **`activate` no genera**: son comandos distintos
porque son decisiones distintas (ADR 0013 §5).

La autenticación de HuggingFace, si un modelo la exige, se toma del entorno
estándar (`HF_TOKEN`). Aquí no se incrusta ningún token, ni se pide por
argumento: un token en la línea de comandos acaba en el historial del shell.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence

from elsa.adapters.postgres_documents import PostgresDocumentRepository
from elsa.adapters.postgres_vectors import PostgresVectorStore
from elsa.adapters.sentence_transformer_embeddings import SentenceTransformerEmbeddings
from elsa.config import Settings, load_settings
from elsa.core.authorization import Scope
from elsa.ports.embeddings import EmbeddingConfigurationError, EmbeddingsPort
from elsa.ports.vectors import EmbeddingModelSpec
from elsa.services.embedding_generation import EmbeddingGenerationService
from elsa.services.semantic_retrieval import SemanticRetrievalService


def build_embeddings(settings: Settings) -> EmbeddingsPort:
    """Construye el adaptador productivo desde la configuración.

    Falla explícitamente si falta lo que define el espacio vectorial. No hay
    valores por defecto para el modelo, la revisión ni la dimensión: adivinar
    cualquiera de los tres produciría un índice que nadie puede reproducir.
    """
    missing = [
        name
        for name, value in (
            ("ELSA_EMBEDDINGS_MODEL_ID", settings.embeddings_model_id),
            ("ELSA_EMBEDDINGS_REVISION", settings.embeddings_revision),
            ("ELSA_EMBEDDINGS_DIMENSION", settings.embeddings_dimension),
        )
        if value is None
    ]
    if missing:
        raise EmbeddingConfigurationError(
            "the embedding model is not configured; missing: " + ", ".join(missing)
        )
    assert settings.embeddings_model_id is not None
    assert settings.embeddings_revision is not None
    assert settings.embeddings_dimension is not None
    return SentenceTransformerEmbeddings(
        model_id=settings.embeddings_model_id,
        revision=settings.embeddings_revision,
        dimension=settings.embeddings_dimension,
        normalized=settings.embeddings_normalized,
        document_prefix=settings.embeddings_document_prefix,
        query_prefix=settings.embeddings_query_prefix,
        composition_template=settings.embeddings_composition_template,
        family=settings.embeddings_family,
        device=settings.embeddings_device,
        batch_size=settings.embeddings_batch_size,
        trust_remote_code=settings.embeddings_trust_remote_code,
    )


def _spec_from(embeddings: EmbeddingsPort) -> EmbeddingModelSpec:
    d = embeddings.describe()
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
        similarity=d.similarity,
    )


def _database_url(settings: Settings) -> str:
    if settings.database_url is None:
        raise EmbeddingConfigurationError("ELSA_DATABASE_URL is not configured")
    return settings.database_url.get_secret_value()


async def _register(settings: Settings, args: argparse.Namespace) -> int:
    embeddings = build_embeddings(settings)
    spec = _spec_from(embeddings)
    store = await PostgresVectorStore.connect(_database_url(settings))
    try:
        existing = await store.find_model(spec)
        if existing is not None:
            print(f"ya registrado: {existing.id} ({existing.state})")
            return 0
        model = await store.register_model(spec, actor=args.actor)
    finally:
        await store.close()
    print(f"registrado: {model.id}")
    print(f"  {model.spec.model_id} @ {model.spec.revision}, {model.spec.dimension} dimensiones")
    print(f"  estado: {model.state} — registrar NO activa; usa `activate` cuando corresponda")
    return 0


async def _generate(settings: Settings, args: argparse.Namespace) -> int:
    embeddings = build_embeddings(settings)
    documents = await PostgresDocumentRepository.connect(_database_url(settings))
    store = await PostgresVectorStore.connect(_database_url(settings))
    try:
        service = EmbeddingGenerationService(
            documents=documents,
            vectors=store,
            embeddings=embeddings,
            batch_size=settings.embeddings_batch_size,
        )
        outcome = await service.generate_for_version(
            model_id=args.model,
            version_id=args.version,
            actor=args.actor,
            trigger_source=args.trigger,
        )
    finally:
        await store.close()
        await documents.close()
    print(f"corrida {outcome.run.id}: {outcome.run.status}")
    print(
        f"  chunks={outcome.considered} generados={outcome.generated} reutilizados={outcome.reused}"
    )
    print("  generar NO activa: el modelo activo no ha cambiado")
    return 0


async def _activate(settings: Settings, args: argparse.Namespace) -> int:
    store = await PostgresVectorStore.connect(_database_url(settings))
    try:
        model = await store.activate_model(model_id=args.model, actor=args.actor)
    finally:
        await store.close()
    print(f"activo: {model.id} — {model.spec.model_id} @ {model.spec.revision}")
    return 0


async def _status(settings: Settings, args: argparse.Namespace) -> int:
    store = await PostgresVectorStore.connect(_database_url(settings))
    try:
        models = await store.list_models()
        active = await store.get_active_model()
    finally:
        await store.close()
    if not models:
        print("no hay ningún modelo registrado")
        return 0
    print(f"{'estado':<12} {'dim':>5}  modelo @ revisión")
    for model in models:
        mark = "ACTIVO" if model.is_active else model.state
        print(
            f"{mark:<12} {model.spec.dimension:>5}  {model.spec.model_id} @ {model.spec.revision}"
        )
    print()
    print(
        "recuperación: "
        + ("sin modelo activo — no disponible" if active is None else f"usa {active.spec.model_id}")
    )
    return 0


async def _search(settings: Settings, args: argparse.Namespace) -> int:
    embeddings = build_embeddings(settings)
    store = await PostgresVectorStore.connect(_database_url(settings))
    try:
        service = SemanticRetrievalService(vectors=store, embeddings=embeddings)
        found = await service.search(
            question=args.question, scopes=_scopes(args.scope), limit=args.limit
        )
    finally:
        await store.close()
    if not found:
        print("sin resultados dentro de los alcances autorizados")
        return 0
    for rank, hit in enumerate(found, start=1):
        p = hit.provenance
        print(f"{rank:>2}. similitud={hit.similarity:.4f}  {p.citation()}")
        print(f"    {p.chunk.content[:120].replace(chr(10), ' ')}")
    return 0


def _scopes(raw: Sequence[str]) -> list[Scope]:
    """`dominio` o `dominio:equipo`. Sin alcances no se recupera nada."""
    scopes: list[Scope] = []
    for item in raw:
        domain, _, equipment = item.partition(":")
        scopes.append(Scope(domain.strip(), equipment.strip() or None))
    return scopes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elsa-embeddings", description="Operación del motor de embeddings de ELSA."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="Registra el modelo configurado. NO lo activa")
    register.add_argument("--actor", required=True, help="UUID de quien registra")
    register.set_defaults(run=_register)

    generate = sub.add_parser("generate", help="Embebe los chunks de una versión. NO activa")
    generate.add_argument("--model", required=True, help="UUID del modelo registrado")
    generate.add_argument("--version", required=True, help="UUID de la versión documental")
    generate.add_argument("--actor", required=True)
    generate.add_argument(
        "--trigger", default="manual", help="manual|ingestion|model_change|backfill"
    )
    generate.set_defaults(run=_generate)

    activate = sub.add_parser("activate", help="Elige el modelo de la recuperación productiva")
    activate.add_argument("--model", required=True)
    activate.add_argument("--actor", required=True)
    activate.set_defaults(run=_activate)

    status = sub.add_parser("status", help="Modelos registrados y cuál está activo")
    status.set_defaults(run=_status)

    search = sub.add_parser("search", help="Búsqueda de prueba, con alcances explícitos")
    search.add_argument("question")
    search.add_argument(
        "--scope",
        action="append",
        required=True,
        metavar="DOMINIO[:EQUIPO]",
        help="Alcance autorizado. Repetible. Sin alcances no se recupera nada",
    )
    search.add_argument("--limit", type=int, default=10)
    search.set_defaults(run=_search)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    try:
        return int(asyncio.run(args.run(settings, args)))
    except EmbeddingConfigurationError as error:
        print(f"configuración inválida: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - la CLI reporta, no propaga trazas
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
