"""Herramienta de operación del conocimiento documental persistente.

Ocho comandos, para ejecutarse desde la máquina de operación —PC1, hoy—
contra la base que indique la configuración::

    status           activos, documentos y versiones por código (solo lectura)
    create-asset     crea un activo técnico
    create-document  crea la identidad de un documento
    ingest           ingiere un archivo como versión pendiente de validación
    approve          aprueba una versión
    reject           rechaza una versión, con motivo
    publish          publica una versión aprobada
    withdraw         retira una publicación, con motivo: el Ctrl+Z de `publish`

**Cada transición es un comando aparte.** `ingest` no aprueba, `approve` no
publica, y no hay ningún atajo que haga dos cosas a la vez: cargar no publica
y aprobar no publica (regla 16). Lo que decide una persona lo ejecuta esa
persona, comando a comando, y queda en el historial con su `--actor`.

Tres negativas que esta herramienta impone antes de escribir nada:

- **Sin almacén de artefactos en memoria.** La base guardaría la clave de unos
  bytes que desaparecen al terminar el proceso: una versión cuya fuente ya no
  existe es evidencia que nadie puede verificar.
- **Sin DEV contra una base remota.** DEV trabaja con una base local; una base
  remota es la de TEST, y ningún ambiente comparte base con otro (regla 8).
  Las escrituras desde DEV solo se aceptan contra un PostgreSQL de loopback.
- **Solo texto y Markdown.** Es lo que el extractor actual sabe leer; un PDF se
  rechaza antes de abrirlo.

`--actor` es el UUID de quien ejecuta. No se autentica: quien opera esta
herramienta tiene ya la credencial de la base, igual que con
:mod:`elsa.tools.embeddings_admin`. La cadena de conexión nunca se imprime.
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from elsa.adapters.local_artifact_storage import LocalArtifactStorage
from elsa.adapters.postgres_documents import PostgresDocumentRepository
from elsa.adapters.postgres_knowledge import PostgresKnowledgeRepository
from elsa.adapters.structured_text_extractor import StructuredTextExtractor
from elsa.config import (
    ArtifactStorageBackend,
    ConfigurationError,
    Environment,
    Settings,
    load_settings,
)
from elsa.documents.model import ChunkingPolicy
from elsa.ports.artifact_storage import ArtifactStoragePort, StoredArtifact
from elsa.ports.documents import (
    DocumentAlreadyExistsError,
    DocumentIntegrityError,
    DocumentRecord,
    DocumentRepositoryPort,
    DocumentSourceKind,
    DocumentVersionRecord,
    NotPublishableError,
    VersionNotFoundError,
)
from elsa.ports.knowledge import (
    AssetAlreadyExistsError,
    KnowledgeRepositoryPort,
    KnowledgeUnavailableError,
)
from elsa.services.document_ingestion import (
    DocumentIngestionError,
    DocumentIngestionService,
    DuplicateDocumentSource,
)

__all__ = [
    "MAX_SOURCE_BYTES",
    "Stores",
    "ToolConfig",
    "build_parser",
    "main",
    "run",
]

MAX_SOURCE_BYTES = 5 * 1024 * 1024
"""Un manual en texto plano ocupa kilobytes. Algo mayor no es un documento de
esta etapa, y leerlo entero para descubrirlo ya sería un riesgo."""

_CONTENT_TYPES = {".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain"}
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2


class RefusedError(Exception):
    """La herramienta se niega a ejecutar: nada se ha escrito."""


@dataclass(frozen=True, slots=True)
class ToolConfig:
    """Lo único de la configuración que esta herramienta necesita."""

    is_dev: bool
    database_url: str | None
    artifact_storage_local: bool
    artifact_storage_root: Path | None
    policy: ChunkingPolicy

    @classmethod
    def from_settings(cls, settings: Settings) -> "ToolConfig":
        return cls(
            is_dev=settings.env is Environment.DEV,
            database_url=(
                None if settings.database_url is None else settings.database_url.get_secret_value()
            ),
            artifact_storage_local=(
                settings.artifact_storage_backend is ArtifactStorageBackend.LOCAL
            ),
            artifact_storage_root=settings.artifact_storage_root,
            policy=settings.chunking_policy,
        )


@dataclass
class Stores:
    """Los almacenes con los que trabaja un comando."""

    documents: DocumentRepositoryPort
    assets: KnowledgeRepositoryPort
    storage: ArtifactStoragePort | None
    closers: tuple[Callable[[], Awaitable[None]], ...] = ()

    async def close(self) -> None:
        for close in self.closers:
            await close()


StoresFactory = Callable[[ToolConfig, bool], Awaitable[Stores]]


async def postgres_stores(config: ToolConfig, with_storage: bool) -> Stores:
    """Los adaptadores reales: PostgreSQL y almacenamiento en disco."""
    if config.database_url is None:
        raise RefusedError("ELSA_DATABASE_URL is not configured")
    storage: ArtifactStoragePort | None = None
    if with_storage:
        assert config.artifact_storage_root is not None  # noqa: S101 - validado antes
        storage = LocalArtifactStorage(config.artifact_storage_root)
    documents = await PostgresDocumentRepository.connect(config.database_url, max_size=2)
    try:
        assets = await PostgresKnowledgeRepository.connect(config.database_url, max_size=2)
    except Exception:
        await documents.close()
        raise
    return Stores(
        documents=documents,
        assets=assets,
        storage=storage,
        closers=(documents.close, assets.close),
    )


# ---------------------------------------------------------------------
# Negativas previas a cualquier escritura
# ---------------------------------------------------------------------


def _is_loopback(url: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host in _LOOPBACK_HOSTS


def _require_writable(config: ToolConfig) -> None:
    if config.database_url is None:
        raise RefusedError("ELSA_DATABASE_URL is not configured")
    if config.is_dev and not _is_loopback(config.database_url):
        raise RefusedError(
            "DEV only writes to a loopback database; a remote database belongs to TEST "
            "(set ELSA_ENV=TEST for this process)"
        )


def _require_local_storage(config: ToolConfig) -> None:
    if not config.artifact_storage_local or config.artifact_storage_root is None:
        raise RefusedError(
            "ingestion needs ELSA_ARTIFACT_STORAGE_BACKEND=local and ELSA_ARTIFACT_STORAGE_ROOT: "
            "in-memory sources would vanish while the database keeps their key"
        )


def _content_type(path: Path) -> str:
    content_type = _CONTENT_TYPES.get(path.suffix.lower())
    if content_type is None:
        allowed = ", ".join(sorted(_CONTENT_TYPES))
        raise RefusedError(f"unsupported file type {path.suffix!r}; allowed: {allowed}")
    return content_type


def _read_source(path: Path) -> bytes:
    if not path.is_file():
        raise RefusedError(f"source file not found: {path.name}")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise RefusedError(f"source file exceeds {MAX_SOURCE_BYTES} bytes: {path.name}")
    return path.read_bytes()


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a UUID: {value!r}") from None


# ---------------------------------------------------------------------
# Comandos
# ---------------------------------------------------------------------


def _version_line(version: DocumentVersionRecord) -> str:
    return f"v{version.version_number} {version.state.value} {version.id}"


async def _status(stores: Stores, config: ToolConfig, args: argparse.Namespace) -> int:
    for code in args.asset:
        asset = await stores.assets.get_asset(code)
        if asset is None:
            print(f"activo {code}: ausente")
        else:
            print(f"activo {code}: presente (dominio {asset.domain}, id {asset.id})")

    documents: list[DocumentRecord] = []
    if args.document:
        for code in args.document:
            document = await stores.documents.get_document(domain=args.domain, code=code)
            if document is None:
                print(f"documento {args.domain}/{code}: ausente")
            else:
                documents.append(document)
    else:
        documents = list(await stores.documents.list_documents(domain=args.domain))
        if not documents and not args.asset:
            print(f"dominio {args.domain}: sin documentos")

    for document in documents:
        scope = document.asset_code or "(todo el dominio)"
        print(f"documento {document.domain}/{document.code}: presente (activo {scope})")
        for version in await stores.documents.list_versions(document.id):
            chunks = await stores.documents.list_chunks(version.id)
            print(f"  {_version_line(version)} chunks={len(chunks)}")
    return EXIT_OK


async def _create_asset(stores: Stores, config: ToolConfig, args: argparse.Namespace) -> int:
    try:
        asset = await stores.assets.create_asset(
            code=args.code, name=args.name, domain=args.domain, description=args.description
        )
    except AssetAlreadyExistsError:
        print(f"el activo {args.code} ya existe: no se crea ni se renombra", file=sys.stderr)
        return EXIT_FAILED
    print(f"activo creado: {asset.code} (dominio {asset.domain}, id {asset.id})")
    return EXIT_OK


async def _create_document(stores: Stores, config: ToolConfig, args: argparse.Namespace) -> int:
    if args.asset is not None:
        asset = await stores.assets.get_asset(args.asset)
        if asset is None or asset.domain != args.domain:
            print(f"el activo {args.asset} no existe en el dominio {args.domain}", file=sys.stderr)
            return EXIT_FAILED
    try:
        document = await stores.documents.create_document(
            domain=args.domain,
            code=args.code,
            title=args.title,
            source_kind=DocumentSourceKind(args.source_kind),
            asset_code=args.asset,
            language=args.language,
        )
    except DocumentAlreadyExistsError:
        print(f"el documento {args.domain}/{args.code} ya existe", file=sys.stderr)
        return EXIT_FAILED
    print(f"documento creado: {document.domain}/{document.code} (id {document.id})")
    return EXIT_OK


async def _ingest(stores: Stores, config: ToolConfig, args: argparse.Namespace) -> int:
    assert stores.storage is not None  # noqa: S101 - el comando la pide
    document = await stores.documents.get_document(domain=args.domain, code=args.document)
    if document is None:
        print(f"el documento {args.domain}/{args.document} no existe", file=sys.stderr)
        return EXIT_FAILED
    service = DocumentIngestionService(
        repository=stores.documents,
        storage=stores.storage,
        extractor=StructuredTextExtractor(),
        policy=config.policy,
    )
    try:
        outcome = await service.ingest(
            document=document,
            content=args.content,
            content_type=args.content_type,
            filename=args.file.name,
            actor=args.actor,
            request_id=args.request_id,
        )
    except DocumentIngestionError as error:
        print(f"ingesta fallida ({error.failure_kind}): {error}", file=sys.stderr)
        return EXIT_FAILED
    if isinstance(outcome, DuplicateDocumentSource):
        print(
            f"ese archivo ya se ingirió (ejecución {outcome.existing_run_id}): "
            "no se creó ninguna versión"
        )
        return EXIT_OK
    counts = ", ".join(f"{kind}={total}" for kind, total in outcome.change_counts().items())
    print(f"versión creada: {_version_line(outcome.version)}")
    print(f"  chunks={len(outcome.structure.chunks)} cambios: {counts}")
    print("  ingerir NO aprueba ni publica: usa `approve` y después `publish`")
    return EXIT_OK


async def _approve(stores: Stores, config: ToolConfig, args: argparse.Namespace) -> int:
    service = _lifecycle(stores)
    version = await service.approve(
        version_id=args.version, actor=args.actor, comment=args.comment, request_id=args.request_id
    )
    print(f"aprobada: {_version_line(version)}")
    print("  aprobar NO publica: usa `publish` cuando corresponda")
    return EXIT_OK


async def _reject(stores: Stores, config: ToolConfig, args: argparse.Namespace) -> int:
    service = _lifecycle(stores)
    version = await service.reject(
        version_id=args.version, actor=args.actor, reason=args.reason, request_id=args.request_id
    )
    print(f"rechazada: {_version_line(version)}")
    print("  rechazar no retira la versión publicada, si la hay, ni borra datos")
    return EXIT_OK


async def _publish(stores: Stores, config: ToolConfig, args: argparse.Namespace) -> int:
    service = _lifecycle(stores)
    version = await service.publish(
        version_id=args.version, actor=args.actor, request_id=args.request_id
    )
    print(f"publicada: {_version_line(version)}")
    print("  para deshacerlo: `withdraw` con esta versión y un motivo")
    return EXIT_OK


async def _withdraw(stores: Stores, config: ToolConfig, args: argparse.Namespace) -> int:
    service = _lifecycle(stores)
    version = await service.withdraw(
        version_id=args.version, actor=args.actor, reason=args.reason, request_id=args.request_id
    )
    print(f"publicación retirada: {_version_line(version)}")
    print("  ya no se recupera; no se borró nada y se vuelve a publicar con `publish`")
    return EXIT_OK


def _lifecycle(stores: Stores) -> DocumentIngestionService:
    """El servicio, para las transiciones; no lee ni guarda artefactos."""
    return DocumentIngestionService(
        repository=stores.documents,
        storage=_NoStorage(),
        extractor=StructuredTextExtractor(),
    )


class _NoStorage:
    """Las transiciones no tocan bytes; si alguna lo intentara, falla aquí."""

    async def put(self, key: str, data: bytes) -> StoredArtifact:
        raise RuntimeError("lifecycle commands never write artifacts")

    async def get(self, key: str) -> bytes:
        raise RuntimeError("lifecycle commands never read artifacts")

    async def exists(self, key: str) -> bool:
        raise RuntimeError("lifecycle commands never read artifacts")

    async def check_health(self) -> None:
        raise RuntimeError("lifecycle commands never read artifacts")


# ---------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Command:
    run: Callable[[Stores, ToolConfig, argparse.Namespace], Awaitable[int]]
    writes: bool
    needs_storage: bool = False


_COMMANDS = {
    "status": _Command(_status, writes=False),
    "create-asset": _Command(_create_asset, writes=True),
    "create-document": _Command(_create_document, writes=True),
    "ingest": _Command(_ingest, writes=True, needs_storage=True),
    "approve": _Command(_approve, writes=True),
    "reject": _Command(_reject, writes=True),
    "publish": _Command(_publish, writes=True),
    "withdraw": _Command(_withdraw, writes=True),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="elsa-documents",
        description="Operación del conocimiento documental de ELSA. Cada transición es un comando.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="Activos, documentos y versiones. Solo lectura")
    status.add_argument("--domain", required=True)
    status.add_argument("--asset", action="append", default=[], help="Código de activo")
    status.add_argument("--document", action="append", default=[], help="Código de documento")

    asset = sub.add_parser("create-asset", help="Crea un activo técnico")
    asset.add_argument("--domain", required=True)
    asset.add_argument("--code", required=True)
    asset.add_argument("--name", required=True)
    asset.add_argument("--description", default=None)

    document = sub.add_parser("create-document", help="Crea la identidad de un documento")
    document.add_argument("--domain", required=True)
    document.add_argument("--code", required=True)
    document.add_argument("--title", required=True)
    document.add_argument(
        "--source-kind", required=True, choices=[kind.value for kind in DocumentSourceKind]
    )
    document.add_argument("--asset", default=None, help="Código del activo; sin él, el dominio")
    document.add_argument("--language", default=None)

    ingest = sub.add_parser("ingest", help="Ingiere un archivo. NO aprueba ni publica")
    ingest.add_argument("--domain", required=True)
    ingest.add_argument("--document", required=True, help="Código del documento")
    ingest.add_argument("--file", required=True, type=Path)
    ingest.add_argument("--actor", required=True, type=_uuid, help="UUID de quien ingiere")
    ingest.add_argument("--request-id", default=None)

    approve = sub.add_parser("approve", help="Aprueba una versión. NO publica")
    approve.add_argument("--version", required=True, type=_uuid)
    approve.add_argument("--actor", required=True, type=_uuid)
    approve.add_argument("--comment", default=None)
    approve.add_argument("--request-id", default=None)

    reject = sub.add_parser("reject", help="Rechaza una versión, con motivo")
    reject.add_argument("--version", required=True, type=_uuid)
    reject.add_argument("--actor", required=True, type=_uuid)
    reject.add_argument("--reason", required=True)
    reject.add_argument("--request-id", default=None)

    publish = sub.add_parser("publish", help="Publica una versión aprobada")
    publish.add_argument("--version", required=True, type=_uuid)
    publish.add_argument("--actor", required=True, type=_uuid)
    publish.add_argument("--request-id", default=None)

    withdraw = sub.add_parser("withdraw", help="Retira una publicación, con motivo. No borra nada")
    withdraw.add_argument("--version", required=True, type=_uuid)
    withdraw.add_argument("--actor", required=True, type=_uuid)
    withdraw.add_argument("--reason", required=True)
    withdraw.add_argument("--request-id", default=None)
    return parser


async def run(
    argv: Sequence[str],
    config: ToolConfig,
    open_stores: StoresFactory = postgres_stores,
) -> int:
    """Ejecuta un comando. Las negativas ocurren antes de conectar."""
    args = build_parser().parse_args(argv)
    command = _COMMANDS[args.command]
    try:
        if command.writes:
            _require_writable(config)
        if command.needs_storage:
            _require_local_storage(config)
            args.content_type = _content_type(args.file)
            args.content = _read_source(args.file)
    except RefusedError as error:
        print(f"no se ejecuta: {error}", file=sys.stderr)
        return EXIT_REFUSED

    try:
        stores = await open_stores(config, command.needs_storage)
    except RefusedError as error:
        print(f"no se ejecuta: {error}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        return await command.run(stores, config, args)
    except (NotPublishableError, VersionNotFoundError, DocumentIntegrityError) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_FAILED
    finally:
        await stores.close()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        config = ToolConfig.from_settings(load_settings())
    except ConfigurationError as error:
        print(f"configuración inválida: {error}", file=sys.stderr)
        return EXIT_REFUSED
    try:
        return asyncio.run(run(sys.argv[1:] if argv is None else argv, config))
    except KnowledgeUnavailableError:
        print("la base de datos no está disponible", file=sys.stderr)
        return EXIT_FAILED
    except Exception as error:  # noqa: BLE001 - la CLI reporta, no propaga trazas
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
