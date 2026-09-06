"""Cadena de confianza de la API.

Orden obligatorio, sin excepciones:

1. **Autenticar**: leer ``Authorization: Bearer``, verificar el JWT contra
   el proveedor de identidad (Materiales).
2. **Admitir**: aplicar el control de abuso sobre el usuario ya identificado.
3. **Comprobar identidad vigente**: el perfil debe seguir activo en la
   fuente autoritativa (Materiales).
4. **Autorizar**: la cuenta debe existir y estar activa en ELSA, y el
   permiso debe cubrir el alcance solicitado.

Solo después de eso el endpoint hace su trabajo. Nunca se recupera nada para
después ocultarlo: una fuente no autorizada no llega a entrar en el conjunto
de recuperación.

Semántica de errores:

- ``401`` falta el token, está mal formado, es inválido o está expirado.
- ``403`` la identidad es válida pero el acceso está prohibido.
- ``429`` se alcanzó un límite del control de abuso.
- ``503`` una dependencia necesaria (identidad o permisos) no responde.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fastapi import Depends, Request, status

from elsa.api.errors import ApiError
from elsa.config import Settings
from elsa.container import Container
from elsa.core.authorization import (
    InvalidScopeError,
    Principal,
    Scope,
    authorize,
    normalize_scope_value,
)
from elsa.core.review import ReviewerCapability, build_capability, can_review
from elsa.ingestion.safety import ArchiveLimits
from elsa.logging import get_request_id
from elsa.ports.artifact_storage import ArtifactStoragePort
from elsa.ports.auth import (
    AuthenticatedUser,
    IdentityProviderUnavailableError,
    InvalidTokenError,
)
from elsa.ports.contributions import ContributionsRepositoryPort, ContributionsUnavailableError
from elsa.ports.knowledge import KnowledgeRepositoryPort, KnowledgeUnavailableError
from elsa.ports.materials_identity import MaterialsProfile
from elsa.ports.permissions import PermissionsRepositoryPort, PermissionsUnavailableError
from elsa.ports.transcription import TranscriptionPort
from elsa.services.ingestion import IngestionService

_logger = logging.getLogger("elsa.api.auth")

_BEARER_PREFIX = "bearer "
_AUTH_CHALLENGE = {"WWW-Authenticate": "Bearer"}


def get_container(request: Request) -> Container:
    """Adaptadores de esta ejecución. Punto único de sustitución en tests."""
    container: Container = request.app.state.container
    return container


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _unauthorized(message: str = "Authentication is required.") -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        message,
        code="unauthorized",
        headers=dict(_AUTH_CHALLENGE),
    )


def _forbidden(message: str, code: str) -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, message, code=code)


def _unavailable(message: str, code: str) -> ApiError:
    return ApiError(status.HTTP_503_SERVICE_UNAVAILABLE, message, code=code)


async def bearer_token(request: Request) -> str:
    """Extrae el token del encabezado ``Authorization``.

    El valor no se registra jamás, ni completo ni truncado.
    """
    header = request.headers.get("Authorization")
    if not header:
        raise _unauthorized()
    if not header.lower().startswith(_BEARER_PREFIX):
        raise _unauthorized("The Authorization header must use the Bearer scheme.")
    token = header[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise _unauthorized("The Bearer token is empty.")
    return token


async def authenticated_identity(
    token: str = Depends(bearer_token),
    container: Container = Depends(get_container),
) -> AuthenticatedUser:
    """Verifica el JWT y devuelve la identidad emitida por Materiales."""
    try:
        return await container.auth.verify_token(token)
    except InvalidTokenError:
        raise _unauthorized("The token is not valid.") from None
    except IdentityProviderUnavailableError:
        # Fallo técnico del proveedor: nunca se disfraza de credencial
        # inválida.
        raise _unavailable(
            "The identity provider is temporarily unavailable.",
            code="identity_provider_unavailable",
        ) from None


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    """Identidad autenticada y todavía vigente en Materiales."""

    user: AuthenticatedUser
    profile: MaterialsProfile
    token: str


async def verified_identity(
    request: Request,
    token: str = Depends(bearer_token),
    identity: AuthenticatedUser = Depends(authenticated_identity),
    container: Container = Depends(get_container),
) -> AsyncIterator[VerifiedIdentity]:
    """Aplica el control de abuso y comprueba el perfil en Materiales.

    Es la base común de todo endpoint autenticado, incluido el bootstrap,
    que todavía no tiene cuenta de ELSA sobre la que autorizar.
    """
    verdict = await container.abuse_guard.acquire(
        user_id=identity.id,
        session_id=identity.session_id,
    )
    if not verdict.allowed:
        headers = (
            {"Retry-After": str(verdict.retry_after_seconds)}
            if verdict.retry_after_seconds is not None
            else None
        )
        _logger.info(
            "request rejected by the abuse guard",
            extra={"user_id": identity.id, "limit": verdict.kind},
        )
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests.",
            code="too_many_requests",
            headers=headers,
        )

    try:
        profile = await _materials_profile(request, identity, token, container)
        yield VerifiedIdentity(user=identity, profile=profile, token=token)
    finally:
        await container.abuse_guard.release(
            user_id=identity.id,
            session_id=identity.session_id,
        )


async def _materials_profile(
    request: Request,
    identity: AuthenticatedUser,
    token: str,
    container: Container,
) -> MaterialsProfile:
    try:
        profile = await container.materials_identity.get_own_profile(
            identity.id, access_token=token
        )
    except InvalidTokenError:
        raise _unauthorized("The token is not valid.") from None
    except IdentityProviderUnavailableError:
        raise _unavailable(
            "The identity provider is temporarily unavailable.",
            code="identity_provider_unavailable",
        ) from None

    if profile is None or not profile.is_active:
        _logger.info(
            "access denied: the profile is missing or disabled in Materiales",
            extra={"user_id": identity.id, "request_id": get_request_id(request)},
        )
        raise _forbidden(
            "This user is not enabled in the identity source.",
            code="account_disabled",
        )
    return profile


async def current_principal(
    request: Request,
    verified: VerifiedIdentity = Depends(verified_identity),
    container: Container = Depends(get_container),
) -> Principal:
    """Resuelve la identidad vigente en un sujeto autorizable de ELSA."""
    permissions = _permissions(container)
    user_id = verified.user.id
    try:
        account = await permissions.get_account(user_id)
        grants = () if account is None else await permissions.list_active_grants(user_id)
    except PermissionsUnavailableError:
        raise _unavailable(
            "The authorization store is temporarily unavailable.",
            code="permissions_store_unavailable",
        ) from None

    # DEFAULT DENY: sin cuenta en ELSA, o desactivada, no hay acceso.
    if account is None or not account.is_active:
        _logger.info(
            "access denied: no active ELSA account",
            extra={"user_id": user_id, "request_id": get_request_id(request)},
        )
        raise _forbidden("This user has no active ELSA account.", code="elsa_access_denied")

    return Principal(
        external_user_id=account.external_user_id,
        display_name=account.display_name or verified.profile.display_name,
        is_active=account.is_active,
        is_admin=account.is_admin,
        scopes=tuple(Scope(domain=grant.domain, equipment=grant.equipment) for grant in grants),
        session_id=verified.user.session_id,
    )


def _permissions(container: Container) -> PermissionsRepositoryPort:
    try:
        return container.require_permissions()
    except PermissionsUnavailableError:
        raise _unavailable(
            "The authorization store is temporarily unavailable.",
            code="permissions_store_unavailable",
        ) from None


def get_permissions(
    container: Container = Depends(get_container),
) -> PermissionsRepositoryPort:
    """Repositorio de permisos, o 503 si todavía no está conectado."""
    return _permissions(container)


class RequireScope:
    """Dependencia que exige un alcance concreto antes del endpoint.

    Los valores del alcance se leen de la ruta: son **dato**, no constantes
    de código. Un valor con formato inválido se rechaza como 403, sin
    revelar si existe o no.
    """

    def __init__(self, *, domain_param: str = "domain", equipment_param: str | None = None) -> None:
        self._domain_param = domain_param
        self._equipment_param = equipment_param

    async def __call__(
        self,
        request: Request,
        principal: Principal = Depends(current_principal),
    ) -> Principal:
        try:
            domain = normalize_scope_value(str(request.path_params[self._domain_param]))
            equipment = (
                None
                if self._equipment_param is None
                else normalize_scope_value(str(request.path_params[self._equipment_param]))
            )
        except (InvalidScopeError, KeyError):
            raise _forbidden(
                "Access to this scope is not allowed.", "insufficient_permissions"
            ) from None

        required = Scope(domain=domain, equipment=equipment)
        decision = authorize(principal, required)
        if not decision.allowed:
            _logger.info(
                "access denied",
                extra={
                    "user_id": principal.external_user_id,
                    "domain": required.domain,
                    "equipment": required.equipment,
                    "reason": decision.reason,
                    "request_id": get_request_id(request),
                },
            )
            raise _forbidden("Access to this scope is not allowed.", "insufficient_permissions")
        return principal


async def require_admin(principal: Principal = Depends(current_principal)) -> Principal:
    """Exige que el sujeto sea administrador de ELSA."""
    if not principal.is_admin:
        raise _forbidden("Administrator privileges are required.", "insufficient_permissions")
    return principal


# ---------------------------------------------------------------------
# Conocimiento técnico (Bloque 2)
# ---------------------------------------------------------------------


def get_knowledge(
    container: Container = Depends(get_container),
) -> KnowledgeRepositoryPort:
    """Repositorio de conocimiento, o 503 si todavía no está conectado."""
    try:
        return container.require_knowledge()
    except KnowledgeUnavailableError:
        raise _unavailable(
            "The knowledge store is temporarily unavailable.",
            code="knowledge_store_unavailable",
        ) from None


def get_artifact_storage(
    container: Container = Depends(get_container),
) -> ArtifactStoragePort:
    """Almacenamiento privado de artefactos."""
    return container.artifact_storage


def get_ingestion_service(
    container: Container = Depends(get_container),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> IngestionService:
    """Servicio de ingesta con los límites configurados para este ambiente."""
    settings = container.settings
    return IngestionService(
        knowledge,
        container.artifact_storage,
        limits=ArchiveLimits(
            max_bytes=settings.ingestion_max_upload_bytes,
            max_uncompressed_bytes=settings.ingestion_max_uncompressed_bytes,
            max_entries=settings.ingestion_max_archive_entries,
        ),
    )


async def reviewer_capability(
    principal: Principal = Depends(current_principal),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
) -> ReviewerCapability:
    """Capacidades de revisor **vigentes** de quien hace la petición.

    Se resuelven en cada petición, no se cachean: deshabilitar a un revisor
    tiene que surtir efecto de inmediato, sin esperar a que expire nada.
    """
    try:
        grants = await permissions.list_active_reviewer_grants(principal.external_user_id)
    except PermissionsUnavailableError:
        raise _unavailable(
            "The authorization store is temporarily unavailable.",
            code="permissions_store_unavailable",
        ) from None
    return build_capability(
        principal,
        [Scope(domain=grant.domain, equipment=grant.equipment) for grant in grants],
    )


class RequireReviewer:
    """Exige capacidad de Revisor Técnico sobre el alcance de la ruta.

    Se aplica **después** de :class:`RequireScope`: revisar exige además
    poder leer. Un administrador pasa siempre, porque conserva capacidad
    global de intervención.
    """

    def __init__(self, *, domain_param: str = "domain", asset_param: str = "asset") -> None:
        self._domain_param = domain_param
        self._asset_param = asset_param

    async def __call__(
        self,
        request: Request,
        capability: ReviewerCapability = Depends(reviewer_capability),
    ) -> ReviewerCapability:
        try:
            required = Scope(
                domain=normalize_scope_value(str(request.path_params[self._domain_param])),
                equipment=normalize_scope_value(str(request.path_params[self._asset_param])),
            )
        except (InvalidScopeError, KeyError):
            raise _forbidden(
                "Technical review is not allowed for this scope.", "reviewer_scope_denied"
            ) from None

        if not can_review(capability, required):
            _logger.info(
                "review denied",
                extra={
                    "user_id": capability.external_user_id,
                    "domain": required.domain,
                    "equipment": required.equipment,
                    "request_id": get_request_id(request),
                },
            )
            raise _forbidden(
                "Technical review is not allowed for this scope.", "reviewer_scope_denied"
            )
        return capability


# ---------------------------------------------------------------------
# Aportes de conocimiento (Bloque 3)
# ---------------------------------------------------------------------


def get_contributions(
    container: Container = Depends(get_container),
) -> ContributionsRepositoryPort:
    """Almacén de aportes, o 503 si todavía no está conectado."""
    contributions = container.contributions
    if contributions is None:  # pragma: no cover - el contenedor siempre lo compone
        raise _unavailable(
            "The contributions store is temporarily unavailable.",
            code="contributions_store_unavailable",
        )
    return contributions


def get_transcription(container: Container = Depends(get_container)) -> TranscriptionPort:
    """Motor de voz a texto seleccionado para esta ejecución."""
    return container.transcription


class RequireContributor:
    """Exige capacidad de **aportar** sobre el alcance de la ruta.

    Aportar no es consultar. Alguien puede tener permiso para leer el
    conocimiento de un equipo y no estar habilitado para añadirle nada: lo
    que entra al conocimiento técnico de una planta pasa por una lista
    explícita, no por el hecho de tener acceso.

    Se aplica **después** de ``RequireScope``: no se puede aportar sobre un
    alcance que ni siquiera se puede leer. Un administrador pasa, porque
    conserva capacidad global de intervención, igual que en la revisión.
    """

    def __init__(self, *, domain_param: str = "domain", asset_param: str = "asset") -> None:
        self._domain_param = domain_param
        self._asset_param = asset_param

    async def __call__(
        self,
        request: Request,
        principal: Principal = Depends(current_principal),
        contributions: ContributionsRepositoryPort = Depends(get_contributions),
    ) -> Principal:
        try:
            domain = normalize_scope_value(str(request.path_params[self._domain_param]))
            asset = normalize_scope_value(str(request.path_params[self._asset_param]))
        except (InvalidScopeError, KeyError):
            raise _forbidden(
                "Contributing to this scope is not allowed.", "contributor_scope_denied"
            ) from None

        if principal.is_admin:
            return principal

        try:
            allowed = await contributions.is_contributor(
                principal.external_user_id, domain=domain, asset_code=asset
            )
        except ContributionsUnavailableError:
            raise _unavailable(
                "The contributions store is temporarily unavailable.",
                code="contributions_store_unavailable",
            ) from None

        if not allowed:
            _logger.info(
                "contribution denied",
                extra={
                    "user_id": principal.external_user_id,
                    "domain": domain,
                    "equipment": asset,
                    "request_id": get_request_id(request),
                },
            )
            raise _forbidden(
                "Contributing to this scope is not allowed.", "contributor_scope_denied"
            )
        return principal
