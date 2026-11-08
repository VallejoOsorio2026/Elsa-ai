"""Herramienta de operación del motor de embeddings.

Comandos, para ejecutarse desde una máquina con acceso a los pesos —no desde
el servicio web, que en Render Free no puede cargar un modelo (ADR 0013 §8):

    register       registra la configuración real de un modelo
    generate       embebe los chunks de una versión `approved` o `published`
    activate       elige qué modelo participa en la recuperación
    deactivate     el Ctrl+Z de `activate`: deja ningún modelo activo, con motivo
    status         modelos registrados, cuál está activo y su historial
    runs           corridas, y cuáles siguen `running`
    reconcile-run  cierra a mano una corrida abandonada por un proceso muerto
    search         una búsqueda de prueba, con alcances explícitos

**`generate` no activa** y **`activate` no genera**: son comandos distintos
porque son decisiones distintas (ADR 0013 §5). Cada cambio del modelo activo
queda en `elsa.embedding_model_events` (ADR 0039).

Dos negativas antes de conectar: `--actor`, `--model`, `--version` y `--run`
tienen que ser UUID, y desde DEV no se escribe en una base remota, que es la
de TEST (regla 8).

La autenticación de HuggingFace, si un modelo la exige, se toma del entorno
estándar (`HF_TOKEN`). Aquí no se incrusta ningún token, ni se pide por
argumento: un token en la línea de comandos acaba en el historial del shell.
"""

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID

from elsa.adapters.postgres_documents import PostgresDocumentRepository
from elsa.adapters.postgres_lexical import PostgresLexicalSearch
from elsa.adapters.postgres_vectors import PostgresVectorStore
from elsa.adapters.sentence_transformer_embeddings import SentenceTransformerEmbeddings
from elsa.config import ConfigurationError, Environment, Settings, load_settings
from elsa.core.authorization import Scope
from elsa.ports.embeddings import EmbeddingConfigurationError, EmbeddingsPort
from elsa.ports.knowledge import KnowledgeUnavailableError
from elsa.ports.vectors import EmbeddingModelSpec, EmbeddingRunStatus
from elsa.services.embedding_generation import EmbeddingGenerationService
from elsa.services.hybrid_retrieval import HybridRetrievalService
from elsa.services.semantic_retrieval import SemanticRetrievalService

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# Una corrida viva confirma un lote cada pocos segundos; diez minutos sin
# escribir nada es el mínimo para afirmar que su proceso ya no corre.
MIN_IDLE_MINUTES = 10


class RefusedError(Exception):
    """La operación se niega antes de conectar: nada se escribe."""


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


def _require_writable(settings: Settings) -> None:
    """DEV solo escribe en un PostgreSQL de loopback; uno remoto es el de TEST."""
    host = urlsplit(_database_url(settings)).hostname
    if settings.env is Environment.DEV and host not in _LOOPBACK_HOSTS:
        raise RefusedError(
            "DEV only writes to a loopback database; a remote database belongs to TEST"
        )


async def _register(settings: Settings, args: argparse.Namespace) -> int:
    _require_writable(settings)
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
    _require_writable(settings)
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
    _require_writable(settings)
    store = await PostgresVectorStore.connect(_database_url(settings))
    try:
        model = await store.activate_model(
            model_id=args.model, actor=args.actor, reason=args.reason, request_id=args.request_id
        )
    finally:
        await store.close()
    print(f"activo: {model.id} — {model.spec.model_id} @ {model.spec.revision}")
    print("  para deshacerlo: `deactivate` con este modelo y un motivo")
    return 0


async def _deactivate(settings: Settings, args: argparse.Namespace) -> int:
    _require_writable(settings)
    store = await PostgresVectorStore.connect(_database_url(settings))
    try:
        model = await store.deactivate_model(
            model_id=args.model, actor=args.actor, reason=args.reason, request_id=args.request_id
        )
    finally:
        await store.close()
    print(f"desactivado: {model.id} — {model.spec.model_id} @ {model.spec.revision}")
    print("  ningún modelo activo; vectores conservados, se reactiva con `activate`")
    return 0


async def _runs(settings: Settings, args: argparse.Namespace) -> int:
    store = await PostgresVectorStore.connect(_database_url(settings))
    try:
        status = EmbeddingRunStatus(args.status) if args.status else None
        runs = await store.list_runs(status=status, limit=args.limit)
    finally:
        await store.close()
    if not runs:
        print("no hay corridas")
        return 0
    now = datetime.now(UTC)
    for run in runs:
        minutes = int((now - run.started_at).total_seconds() // 60)
        print(
            f"{run.status.value:<10} {run.id}  modelo={run.model_id}  hace {minutes} min  "
            f"chunks={run.total_chunks} generados={run.generated} reutilizados={run.reused}"
        )
    return 0


async def _reconcile_run(settings: Settings, args: argparse.Namespace) -> int:
    _require_writable(settings)
    if args.idle_minutes < MIN_IDLE_MINUTES:
        raise RefusedError(f"--idle-minutes must be at least {MIN_IDLE_MINUTES}")
    store = await PostgresVectorStore.connect(_database_url(settings))
    try:
        run = await store.reconcile_run(
            run_id=args.run_id,
            actor=args.actor,
            reason=args.reason,
            idle_minutes=args.idle_minutes,
            request_id=args.request_id,
        )
    finally:
        await store.close()
    print(f"corrida {run.id}: {run.status.value}")
    print("  los vectores ya confirmados se conservan; repetir `generate` los reutiliza")
    return 0


async def _status(settings: Settings, args: argparse.Namespace) -> int:
    store = await PostgresVectorStore.connect(_database_url(settings))
    try:
        models = await store.list_models()
        active = await store.get_active_model()
        events = await store.list_model_events(limit=1000)
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
    if events:
        print()
        print("historial (últimos 10):")
        for event in events[-10:]:
            print(
                f"  {event.occurred_at:%Y-%m-%d %H:%M:%S} {event.event.value:<15} "
                f"modelo={event.model_id}" + (f"  motivo: {event.reason}" if event.reason else "")
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


async def _hybrid(settings: Settings, args: argparse.Namespace) -> int:
    """Recuperación híbrida: exacto + léxico + semántico, fusionados por RRF."""
    embeddings = build_embeddings(settings)
    url = _database_url(settings)
    store = await PostgresVectorStore.connect(url)
    lexical = await PostgresLexicalSearch.connect(url)
    try:
        service = HybridRetrievalService(lexical=lexical, vectors=store, embeddings=embeddings)
        found = await service.search(
            query=args.question, scopes=_scopes(args.scope), limit=args.limit
        )
    finally:
        await lexical.close()
        await store.close()

    canales = ", ".join(c.value for c in found.channels_queried) or "ninguno"
    print(f"canales consultados: {canales}")
    if found.identifiers_detected:
        print(f"identificadores detectados: {', '.join(found.identifiers_detected)}")
    print(f"evidencia: {found.strength.value}")
    if found.is_empty:
        print("sin resultados dentro de los alcances autorizados")
        return 0
    print()
    for item in found.evidence:
        marcas = " + ".join(f"{hit.channel.value}#{hit.rank}({hit.score:.4f})" for hit in item.hits)
        print(f"{item.rank:>2}. rrf={item.fused_score:.6f}  [{marcas}]")
        print(f"    {item.citation()}")
        print(f"    {item.provenance.chunk.content[:140].replace(chr(10), ' ')}")
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
    register.add_argument("--actor", required=True, type=_uuid, help="UUID de quien registra")
    register.set_defaults(run=_register)

    generate = sub.add_parser(
        "generate", help="Embebe los chunks de una versión approved o published. NO activa"
    )
    generate.add_argument("--model", required=True, type=_uuid, help="UUID del modelo registrado")
    generate.add_argument(
        "--version", required=True, type=_uuid, help="UUID de la versión documental"
    )
    generate.add_argument("--actor", required=True, type=_uuid)
    generate.add_argument(
        "--trigger", default="manual", help="manual|ingestion|model_change|backfill"
    )
    generate.set_defaults(run=_generate)

    activate = sub.add_parser("activate", help="Elige el modelo de la recuperación productiva")
    activate.add_argument("--model", required=True, type=_uuid)
    activate.add_argument("--actor", required=True, type=_uuid)
    activate.add_argument("--reason", default=None)
    activate.add_argument("--request-id", default=None)
    activate.set_defaults(run=_activate)

    deactivate = sub.add_parser(
        "deactivate", help="Ctrl+Z de activate: deja ningún modelo activo. No borra nada"
    )
    deactivate.add_argument("--model", required=True, type=_uuid, help="UUID del modelo activo")
    deactivate.add_argument("--actor", required=True, type=_uuid)
    deactivate.add_argument("--reason", required=True)
    deactivate.add_argument("--request-id", default=None)
    deactivate.set_defaults(run=_deactivate)

    status = sub.add_parser("status", help="Modelos registrados, cuál está activo y su historial")
    status.set_defaults(run=_status)

    runs = sub.add_parser("runs", help="Corridas de embedding. Solo lectura")
    runs.add_argument("--status", choices=[s.value for s in EmbeddingRunStatus], default=None)
    runs.add_argument("--limit", type=int, default=20)
    runs.set_defaults(run=_runs)

    reconcile = sub.add_parser(
        "reconcile-run",
        help="Cierra a mano una corrida abandonada: ningún proceso vivo la mantiene y lleva parada",
    )
    # `dest` explícito: `args.run` es la función del comando.
    reconcile.add_argument("--run", dest="run_id", required=True, type=_uuid)
    reconcile.add_argument("--actor", required=True, type=_uuid)
    reconcile.add_argument("--reason", required=True)
    reconcile.add_argument("--idle-minutes", type=int, default=30)
    reconcile.add_argument("--request-id", default=None)
    reconcile.set_defaults(run=_reconcile_run)

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

    hybrid = sub.add_parser(
        "hybrid-search",
        help="Recuperación híbrida: exacto + léxico + semántico, fusionados por RRF",
    )
    hybrid.add_argument("question")
    hybrid.add_argument(
        "--scope",
        action="append",
        required=True,
        metavar="DOMINIO[:EQUIPO]",
        help="Alcance autorizado. Repetible. Sin alcances no se recupera nada",
    )
    hybrid.add_argument("--limit", type=int, default=10)
    hybrid.set_defaults(run=_hybrid)
    return parser


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a UUID: {value!r}") from None


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = load_settings()
    except ConfigurationError as error:
        print(f"configuración inválida: {error}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        return int(asyncio.run(args.run(settings, args)))
    except EmbeddingConfigurationError as error:
        print(f"configuración inválida: {error}", file=sys.stderr)
        return EXIT_REFUSED
    except RefusedError as error:
        print(f"no se ejecuta: {error}", file=sys.stderr)
        return EXIT_REFUSED
    except KnowledgeUnavailableError:
        print("la base de datos no está disponible", file=sys.stderr)
        return EXIT_FAILED
    except Exception as error:  # noqa: BLE001 - la CLI reporta, no propaga trazas
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
