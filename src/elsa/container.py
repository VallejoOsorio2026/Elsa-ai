"""Composición de adaptadores a partir de la configuración.

Único lugar del proyecto donde se decide qué adaptador concreto implementa
cada puerto. La lógica de negocio y la capa HTTP solo conocen los puertos
(CLAUDE.md, sección 5).

También es el único lugar que toca recursos con ciclo de vida (cliente HTTP
y pool de conexiones): se abren en :meth:`Container.start` y se cierran en
:meth:`Container.aclose`, ambos invocados por el *lifespan* de FastAPI.
"""

import logging

import httpx

from elsa.adapters.fake_auth import FakeAuthAdapter
from elsa.adapters.fake_materials_identity import FakeMaterialsIdentityAdapter
from elsa.adapters.jwks import JwksCache
from elsa.adapters.local_artifact_storage import LocalArtifactStorage
from elsa.adapters.memory_abuse_guard import InMemoryAbuseGuard
from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.adapters.postgres_knowledge import PostgresKnowledgeRepository
from elsa.adapters.postgres_permissions import PostgresPermissionsRepository
from elsa.adapters.supabase_auth import SupabaseJwtAuthAdapter
from elsa.adapters.supabase_materials_identity import SupabaseMaterialsIdentityAdapter
from elsa.config import ArtifactStorageBackend, AuthProvider, PermissionsBackend, Settings
from elsa.core.health import DependencyReport, DependencyStatus
from elsa.ports.abuse import AbuseGuardPort, AbusePolicy
from elsa.ports.artifact_storage import ArtifactStoragePort, ArtifactStorageUnavailableError
from elsa.ports.auth import AuthPort, IdentityProviderUnavailableError
from elsa.ports.knowledge import KnowledgeRepositoryPort, KnowledgeUnavailableError
from elsa.ports.materials_identity import MaterialsIdentityPort
from elsa.ports.permissions import PermissionsRepositoryPort, PermissionsUnavailableError

_logger = logging.getLogger("elsa.container")

# Dependencias todavía sin adaptador real. No son deuda técnica: es el
# diseño previsto (ADR 0003). Ninguna es crítica para operar.
_PLANNED_DEPENDENCIES: tuple[str, ...] = ("llm", "embeddings", "ocr", "reranker", "materials")

_FAKE_DETAIL = "fake adapter (DEV only)"
_PLANNED_DETAIL = "no adapter configured yet (planned for a later block)"


class Container:
    """Adaptadores elegidos para esta ejecución."""

    def __init__(
        self,
        settings: Settings,
        *,
        auth: AuthPort | None = None,
        materials_identity: MaterialsIdentityPort | None = None,
        permissions: PermissionsRepositoryPort | None = None,
        abuse_guard: AbuseGuardPort | None = None,
        knowledge: KnowledgeRepositoryPort | None = None,
        artifact_storage: ArtifactStoragePort | None = None,
    ) -> None:
        self.settings = settings
        self._http: httpx.AsyncClient | None = None
        self._postgres: PostgresPermissionsRepository | None = None
        self._postgres_knowledge: PostgresKnowledgeRepository | None = None
        self._overridden_permissions = permissions is not None
        self._overridden_knowledge = knowledge is not None

        self.abuse_guard: AbuseGuardPort = abuse_guard or InMemoryAbuseGuard(
            AbusePolicy(
                requests_per_minute=(
                    settings.rate_limit_requests_per_minute if settings.rate_limit_enabled else 0
                ),
                max_concurrent_requests=(
                    settings.rate_limit_max_concurrent_requests
                    if settings.rate_limit_enabled
                    else 0
                ),
                max_sessions_per_user=settings.max_sessions_per_user,
                session_idle_timeout_seconds=settings.session_idle_timeout_seconds,
            )
        )

        if auth is not None and materials_identity is not None:
            self.auth = auth
            self.materials_identity = materials_identity
        elif settings.auth_provider is AuthProvider.FAKE:
            self.auth = auth or FakeAuthAdapter()
            self.materials_identity = materials_identity or FakeMaterialsIdentityAdapter()
        else:
            self._http = httpx.AsyncClient()
            self.auth = auth or self._build_supabase_auth(settings, self._http)
            self.materials_identity = materials_identity or self._build_materials_identity(
                settings, self._http
            )

        self.permissions: PermissionsRepositoryPort | None = permissions
        if self.permissions is None and settings.permissions_backend is PermissionsBackend.MEMORY:
            self.permissions = InMemoryPermissionsRepository()

        # El conocimiento técnico vive en la misma base que los permisos, así
        # que sigue el mismo selector: no tendría sentido que uno fuera a
        # PostgreSQL y el otro a memoria.
        self.knowledge: KnowledgeRepositoryPort | None = knowledge
        if self.knowledge is None and settings.permissions_backend is PermissionsBackend.MEMORY:
            self.knowledge = InMemoryKnowledgeRepository()

        self.artifact_storage: ArtifactStoragePort = (
            artifact_storage or self._build_artifact_storage(settings)
        )

    # -----------------------------------------------------------------
    # Ciclo de vida
    # -----------------------------------------------------------------

    async def start(self) -> None:
        """Abre los recursos que requieren un bucle de eventos."""
        settings = self.settings
        if settings.permissions_backend is not PermissionsBackend.POSTGRES:
            return
        if self.permissions is not None and self.knowledge is not None:
            return
        assert settings.database_url is not None  # noqa: S101 - garantizado por la configuración

        if self.permissions is None:
            self._postgres = await PostgresPermissionsRepository.connect(
                settings.database_url.get_secret_value(),
                min_size=settings.database_pool_min_size,
                max_size=settings.database_pool_max_size,
            )
            self.permissions = self._postgres
            _logger.info("permissions store connected")

        if self.knowledge is None:
            self._postgres_knowledge = await PostgresKnowledgeRepository.connect(
                settings.database_url.get_secret_value(),
                min_size=settings.database_pool_min_size,
                max_size=settings.database_pool_max_size,
            )
            self.knowledge = self._postgres_knowledge
            _logger.info("knowledge store connected")

    async def aclose(self) -> None:
        """Cierra los recursos abiertos por :meth:`start`."""
        if self._postgres_knowledge is not None:
            await self._postgres_knowledge.close()
            self._postgres_knowledge = None
        if self._postgres is not None:
            await self._postgres.close()
            self._postgres = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def require_permissions(self) -> PermissionsRepositoryPort:
        """Devuelve el repositorio de permisos o falla como indisponible."""
        if self.permissions is None:
            raise PermissionsUnavailableError("the ELSA permissions store is not connected")
        return self.permissions

    def require_knowledge(self) -> KnowledgeRepositoryPort:
        """Devuelve el repositorio de conocimiento o falla como indisponible."""
        if self.knowledge is None:
            raise KnowledgeUnavailableError("the ELSA knowledge store is not connected")
        return self.knowledge

    @staticmethod
    def _build_artifact_storage(settings: Settings) -> ArtifactStoragePort:
        if settings.artifact_storage_backend is ArtifactStorageBackend.LOCAL:
            # La configuración garantiza la raíz para el backend local.
            assert settings.artifact_storage_root is not None  # noqa: S101
            return LocalArtifactStorage(settings.artifact_storage_root)
        return InMemoryArtifactStorage()

    # -----------------------------------------------------------------
    # Salud
    # -----------------------------------------------------------------

    async def health_reports(self) -> tuple[DependencyReport, ...]:
        """Estado por dependencia para ``/health/ready``."""
        reports = [
            await self._auth_report(),
            await self._database_report(),
            await self._storage_report(),
        ]
        reports.extend(
            DependencyReport(
                name=name,
                status=DependencyStatus.NOT_CONFIGURED,
                critical=False,
                detail=_PLANNED_DETAIL,
            )
            for name in _PLANNED_DEPENDENCIES
        )
        return tuple(reports)

    async def _auth_report(self) -> DependencyReport:
        # La autenticación es dependencia crítica: sin proveedor de
        # identidad accesible, ELSA no puede autorizar a nadie.
        if not isinstance(self.auth, SupabaseJwtAuthAdapter):
            return DependencyReport(
                name="auth",
                status=DependencyStatus.DEGRADED,
                critical=True,
                detail=_FAKE_DETAIL,
            )
        try:
            await self.auth.check_health()
        except IdentityProviderUnavailableError:
            return DependencyReport(
                name="auth",
                status=DependencyStatus.DOWN,
                critical=True,
                detail="the identity provider is not reachable",
            )
        return DependencyReport(name="auth", status=DependencyStatus.OK, critical=True)

    async def _database_report(self) -> DependencyReport:
        if self.permissions is None:
            return DependencyReport(
                name="database",
                status=DependencyStatus.DOWN,
                critical=True,
                detail="the permissions store is not connected",
            )
        if isinstance(self.permissions, InMemoryPermissionsRepository):
            return DependencyReport(
                name="database",
                status=DependencyStatus.DEGRADED,
                critical=True,
                detail="in-memory permissions store (DEV only)",
            )
        try:
            await self.permissions.check_health()
        except PermissionsUnavailableError:
            return DependencyReport(
                name="database",
                status=DependencyStatus.DOWN,
                critical=True,
                detail="the permissions store is not reachable",
            )
        return DependencyReport(name="database", status=DependencyStatus.OK, critical=True)

    async def _storage_report(self) -> DependencyReport:
        """El almacenamiento es crítico: sin él no se puede ingerir evidencia.

        Se marca ``degraded`` con el adaptador en memoria porque responde,
        pero pierde todo al reiniciar: es utilizable en DEV y nunca fuera.
        """
        if isinstance(self.artifact_storage, InMemoryArtifactStorage):
            return DependencyReport(
                name="artifact_storage",
                status=DependencyStatus.DEGRADED,
                critical=True,
                detail="in-memory artifact storage (DEV only)",
            )
        try:
            await self.artifact_storage.check_health()
        except ArtifactStorageUnavailableError:
            return DependencyReport(
                name="artifact_storage",
                status=DependencyStatus.DOWN,
                critical=True,
                detail="the private artifact storage is not writable",
            )
        return DependencyReport(
            name="artifact_storage", status=DependencyStatus.OK, critical=True
        )

    # -----------------------------------------------------------------
    # Construcción de adaptadores reales
    # -----------------------------------------------------------------

    @staticmethod
    def _build_supabase_auth(settings: Settings, http: httpx.AsyncClient) -> SupabaseJwtAuthAdapter:
        jwks_url = settings.jwks_url
        jwks = (
            None
            if jwks_url is None
            else JwksCache(
                jwks_url,
                http_client=http,
                cache_seconds=settings.auth_jwks_cache_seconds,
                min_refresh_seconds=settings.auth_jwks_min_refresh_seconds,
                timeout_seconds=settings.auth_timeout_seconds,
            )
        )
        secret = settings.auth_jwt_secret
        return SupabaseJwtAuthAdapter(
            algorithms=settings.auth_jwt_algorithms,
            issuer=settings.jwt_issuer,
            audience=settings.auth_jwt_audience,
            leeway_seconds=settings.auth_jwt_leeway_seconds,
            jwks=jwks,
            symmetric_secret=None if secret is None else secret.get_secret_value(),
        )

    @staticmethod
    def _build_materials_identity(
        settings: Settings, http: httpx.AsyncClient
    ) -> SupabaseMaterialsIdentityAdapter:
        profiles_url = settings.materials_profiles_url
        api_key = settings.materials_api_key
        # La configuración garantiza ambos valores para el proveedor real.
        assert profiles_url is not None and api_key is not None  # noqa: S101
        return SupabaseMaterialsIdentityAdapter(
            profiles_url=profiles_url,
            api_key=api_key,
            http_client=http,
            timeout_seconds=settings.auth_timeout_seconds,
        )
