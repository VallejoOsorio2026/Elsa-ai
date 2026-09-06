"""API administrativa mínima de ELSA.

Lo justo para poder demostrar el modelo de autorización de extremo a extremo:
declarar el primer administrador, otorgar y revocar permisos, habilitar y
deshabilitar usuarios, transferir la administración y leer la auditoría.

**No es el Centro de Control.** Ese llegará en un bloque posterior con su
propia interfaz y su propio alcance.

Todo endpoint de este router exige ser administrador de ELSA, salvo el
bootstrap, que existe precisamente porque todavía no hay ninguno.
"""

import hmac
import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, field_validator

from elsa.api.deps import (
    VerifiedIdentity,
    get_knowledge,
    get_permissions,
    get_settings,
    require_admin,
    verified_identity,
)
from elsa.api.errors import ApiError
from elsa.config import Settings
from elsa.core.authorization import InvalidScopeError, Principal, normalize_scope_value
from elsa.logging import get_request_id
from elsa.ports.knowledge import (
    AssetAlreadyExistsError,
    KnowledgeRepositoryPort,
    KnowledgeUnavailableError,
)
from elsa.ports.permissions import (
    AccountNotFoundError,
    BootstrapAlreadyCompletedError,
    ElsaAccount,
    PermissionGrant,
    PermissionsRepositoryPort,
    PermissionsUnavailableError,
    ReviewerGrant,
    UnknownDomainError,
)

_logger = logging.getLogger("elsa.api.admin")

BOOTSTRAP_TOKEN_HEADER = "X-Bootstrap-Token"

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------
# Modelos
# ---------------------------------------------------------------------


class ScopeBody(BaseModel):
    """Alcance sobre el que se otorga o revoca un permiso."""

    domain: str
    equipment: str | None = None

    @field_validator("domain", "equipment")
    @classmethod
    def _normalize(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return normalize_scope_value(value)
        except InvalidScopeError as exc:
            raise ValueError(str(exc)) from None


class GrantBody(ScopeBody):
    """Alcance a otorgar, con el nombre visible del usuario si se conoce."""

    display_name: str | None = None


class StatusBody(BaseModel):
    is_active: bool


class AdminFlagBody(BaseModel):
    is_admin: bool


class AccountView(BaseModel):
    external_user_id: str
    display_name: str | None
    is_active: bool
    is_admin: bool


class GrantView(BaseModel):
    id: str
    external_user_id: str
    domain: str
    equipment: str | None
    granted_by: str
    granted_at: str
    revoked_by: str | None = None
    revoked_at: str | None = None


class AccountDetail(BaseModel):
    account: AccountView
    grants: list[GrantView]
    reviewer_grants: list[GrantView] = []


class AssetBody(BaseModel):
    """Alta de un Activo Técnico. El alcance es ``(domain, code)``."""

    code: str
    name: str
    domain: str
    description: str | None = None

    @field_validator("code", "domain")
    @classmethod
    def _normalize_scope(cls, value: str) -> str:
        try:
            return normalize_scope_value(value)
        except InvalidScopeError as exc:
            raise ValueError(str(exc)) from None


class AssetView(BaseModel):
    id: str
    code: str
    name: str
    domain: str
    description: str | None = None
    is_active: bool


class BootstrapResponse(BaseModel):
    created: bool
    """Verdadero si esta llamada declaró al administrador; falso si ya lo era."""

    account: AccountView


class AuditView(BaseModel):
    actor_external_user_id: str | None
    subject_external_user_id: str
    operation: str
    scope_domain: str | None
    scope_equipment: str | None
    request_id: str | None
    occurred_at: str


def _account_view(account: ElsaAccount) -> AccountView:
    return AccountView(
        external_user_id=account.external_user_id,
        display_name=account.display_name,
        is_active=account.is_active,
        is_admin=account.is_admin,
    )


def _reviewer_view(grant: ReviewerGrant) -> GrantView:
    return GrantView(
        id=grant.id,
        external_user_id=grant.external_user_id,
        domain=grant.domain,
        equipment=grant.equipment,
        granted_by=grant.granted_by,
        granted_at=grant.granted_at.isoformat(),
        revoked_by=grant.revoked_by,
        revoked_at=None if grant.revoked_at is None else grant.revoked_at.isoformat(),
    )


def _grant_view(grant: PermissionGrant) -> GrantView:
    return GrantView(
        id=grant.id,
        external_user_id=grant.external_user_id,
        domain=grant.domain,
        equipment=grant.equipment,
        granted_by=grant.granted_by,
        granted_at=grant.granted_at.isoformat(),
        revoked_by=grant.revoked_by,
        revoked_at=None if grant.revoked_at is None else grant.revoked_at.isoformat(),
    )


def _unavailable() -> ApiError:
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "The authorization store is temporarily unavailable.",
        code="permissions_store_unavailable",
    )


# ---------------------------------------------------------------------
# Bootstrap del primer administrador
# ---------------------------------------------------------------------


@router.post("/bootstrap", response_model=BootstrapResponse)
async def bootstrap_admin(
    request: Request,
    verified: VerifiedIdentity = Depends(verified_identity),
    settings: Settings = Depends(get_settings),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
) -> BootstrapResponse:
    """Declara al primer administrador de ELSA.

    Requisitos, todos simultáneos:

    - un JWT válido de Materiales, con perfil activo: el UUID administrado
      es el del usuario **realmente autenticado**, nunca uno escrito a mano;
    - el token de bootstrap (``ELSA_BOOTSTRAP_ADMIN_TOKEN``) en la cabecera
      ``X-Bootstrap-Token``. Sin esa variable, o declarada sin valor, el
      endpoint está deshabilitado;
    - que ELSA no tenga todavía ningún otro administrador.

    Es idempotente: repetirlo con el mismo usuario no cambia nada y no
    vuelve a auditar. Después, la administración se otorga y se transfiere
    por la API administrativa, y puede haber varios administradores.
    """
    configured = settings.bootstrap_admin_token
    presented = request.headers.get(BOOTSTRAP_TOKEN_HEADER, "")
    # Un único código de error para "deshabilitado" y "token incorrecto":
    # no se confirma al solicitante si el mecanismo está activo.
    #
    # `configured` nunca puede ser un secreto vacío: la configuración traduce
    # `ELSA_BOOTSTRAP_ADMIN_TOKEN=` a ausencia. Aun así se descarta aquí la
    # cabecera vacía, para que ninguna comparación pueda resultar verdadera
    # por tratarse de dos cadenas vacías. La comparación de tokens reales
    # sigue siendo en tiempo constante.
    if (
        configured is None
        or not presented
        or not hmac.compare_digest(presented, configured.get_secret_value())
    ):
        _logger.warning(
            "bootstrap rejected",
            extra={
                "user_id": verified.user.id,
                "request_id": get_request_id(request),
                "configured": configured is not None,
            },
        )
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            "Bootstrap is not allowed.",
            code="bootstrap_not_allowed",
        )

    try:
        account, created = await permissions.bootstrap_admin(
            subject=verified.user.id,
            display_name=verified.profile.display_name,
            request_id=get_request_id(request),
        )
    except BootstrapAlreadyCompletedError:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "ELSA already has an administrator.",
            code="bootstrap_already_completed",
        ) from None
    except PermissionsUnavailableError:
        raise _unavailable() from None

    if created:
        _logger.warning(
            "first ELSA administrator declared",
            extra={"user_id": account.external_user_id, "request_id": get_request_id(request)},
        )
    return BootstrapResponse(created=created, account=_account_view(account))


# ---------------------------------------------------------------------
# Gestión de usuarios y permisos
# ---------------------------------------------------------------------


@router.get("/users/{user_id}", response_model=AccountDetail)
async def read_account(
    user_id: uuid.UUID,
    _admin: Principal = Depends(require_admin),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
) -> AccountDetail:
    subject = str(user_id)
    try:
        account = await permissions.get_account(subject)
        grants = () if account is None else await permissions.list_active_grants(subject)
        reviewer = () if account is None else await permissions.list_active_reviewer_grants(subject)
    except PermissionsUnavailableError:
        raise _unavailable() from None
    if account is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, "Unknown ELSA account.", code="account_not_found")
    return AccountDetail(
        account=_account_view(account),
        grants=[_grant_view(grant) for grant in grants],
        reviewer_grants=[_reviewer_view(grant) for grant in reviewer],
    )


@router.post("/users/{user_id}/grants", response_model=GrantView)
async def grant_permission(
    request: Request,
    user_id: uuid.UUID,
    body: GrantBody,
    admin: Principal = Depends(require_admin),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
) -> GrantView:
    """Otorga un permiso directamente al usuario, creando su cuenta si hace falta."""
    try:
        grant = await permissions.grant_permission(
            subject=str(user_id),
            domain=body.domain,
            equipment=body.equipment,
            actor=admin.external_user_id,
            display_name=body.display_name,
            request_id=get_request_id(request),
        )
    except UnknownDomainError:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Unknown knowledge domain.",
            code="unknown_domain",
        ) from None
    except PermissionsUnavailableError:
        raise _unavailable() from None
    return _grant_view(grant)


@router.post("/users/{user_id}/grants/revoke", response_model=GrantView)
async def revoke_permission(
    request: Request,
    user_id: uuid.UUID,
    body: ScopeBody,
    admin: Principal = Depends(require_admin),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
) -> GrantView:
    """Revoca un permiso vigente. A partir de aquí ese conocimiento queda vedado."""
    try:
        grant = await permissions.revoke_permission(
            subject=str(user_id),
            domain=body.domain,
            equipment=body.equipment,
            actor=admin.external_user_id,
            request_id=get_request_id(request),
        )
    except PermissionsUnavailableError:
        raise _unavailable() from None
    if grant is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "There is no active grant for that scope.",
            code="grant_not_found",
        )
    return _grant_view(grant)


@router.post("/users/{user_id}/status", response_model=AccountView)
async def set_status(
    request: Request,
    user_id: uuid.UUID,
    body: StatusBody,
    admin: Principal = Depends(require_admin),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
) -> AccountView:
    """Habilita o deshabilita la cuenta **dentro de ELSA**."""
    try:
        account = await permissions.set_account_active(
            subject=str(user_id),
            is_active=body.is_active,
            actor=admin.external_user_id,
            request_id=get_request_id(request),
        )
    except AccountNotFoundError:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "Unknown ELSA account.", code="account_not_found"
        ) from None
    except PermissionsUnavailableError:
        raise _unavailable() from None
    return _account_view(account)


@router.post("/users/{user_id}/admin", response_model=AccountView)
async def set_admin(
    request: Request,
    user_id: uuid.UUID,
    body: AdminFlagBody,
    admin: Principal = Depends(require_admin),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
) -> AccountView:
    """Otorga o retira la administración de ELSA.

    Permite tener varios administradores y transferir la administración a
    otra persona. Retirarse a uno mismo la administración cuando no queda
    ningún otro administrador dejaría el sistema sin gobierno, así que se
    rechaza.
    """
    subject = str(user_id)
    try:
        if not body.is_admin:
            remaining = await permissions.count_admins()
            current = await permissions.get_account(subject)
            if current is not None and current.is_admin and remaining <= 1:
                raise ApiError(
                    status.HTTP_409_CONFLICT,
                    "ELSA would be left without an administrator.",
                    code="last_administrator",
                )
        account = await permissions.set_account_admin(
            subject=subject,
            is_admin=body.is_admin,
            actor=admin.external_user_id,
            request_id=get_request_id(request),
        )
    except AccountNotFoundError:
        raise ApiError(
            status.HTTP_404_NOT_FOUND, "Unknown ELSA account.", code="account_not_found"
        ) from None
    except PermissionsUnavailableError:
        raise _unavailable() from None
    return _account_view(account)


@router.get("/audit", response_model=list[AuditView])
async def read_audit(
    _admin: Principal = Depends(require_admin),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
    subject: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[AuditView]:
    """Auditoría de cambios administrativos, de la más reciente a la más antigua."""
    try:
        entries = await permissions.list_audit_entries(
            subject=None if subject is None else str(subject),
            limit=limit,
        )
    except PermissionsUnavailableError:
        raise _unavailable() from None
    return [
        AuditView(
            actor_external_user_id=entry.actor_external_user_id,
            subject_external_user_id=entry.subject_external_user_id,
            operation=entry.operation.value,
            scope_domain=entry.scope_domain,
            scope_equipment=entry.scope_equipment,
            request_id=entry.request_id,
            occurred_at=entry.occurred_at.isoformat(),
        )
        for entry in entries
    ]


# ---------------------------------------------------------------------
# Revisor Técnico
# ---------------------------------------------------------------------


@router.post("/users/{user_id}/reviewer", response_model=GrantView)
async def grant_reviewer(
    request: Request,
    user_id: uuid.UUID,
    body: GrantBody,
    admin: Principal = Depends(require_admin),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
) -> GrantView:
    """Habilita a un usuario como Revisor Técnico sobre un alcance.

    Es una capacidad distinta de la de administrador: el revisor podrá
    validar conocimiento técnico, pero no gestionará usuarios, ni permisos,
    ni configuración. Solo un administrador llega aquí.
    """
    try:
        grant = await permissions.grant_reviewer(
            subject=str(user_id),
            domain=body.domain,
            equipment=body.equipment,
            actor=admin.external_user_id,
            display_name=body.display_name,
            request_id=get_request_id(request),
        )
    except UnknownDomainError:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Unknown knowledge domain.",
            code="unknown_domain",
        ) from None
    except PermissionsUnavailableError:
        raise _unavailable() from None
    _logger.info(
        "technical reviewer granted",
        extra={
            "user_id": str(user_id),
            "domain": grant.domain,
            "equipment": grant.equipment,
            "request_id": get_request_id(request),
        },
    )
    return _reviewer_view(grant)


@router.post("/users/{user_id}/reviewer/revoke", response_model=GrantView)
async def revoke_reviewer(
    request: Request,
    user_id: uuid.UUID,
    body: ScopeBody,
    admin: Principal = Depends(require_admin),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
) -> GrantView:
    """Deshabilita a un Revisor Técnico.

    La capacidad se pierde en la petición siguiente. Su historial de
    validaciones permanece intacto: borrarlo dejaría aprobaciones sin
    responsable, que es exactamente lo que una auditoría necesita saber.
    """
    try:
        grant = await permissions.revoke_reviewer(
            subject=str(user_id),
            domain=body.domain,
            equipment=body.equipment,
            actor=admin.external_user_id,
            request_id=get_request_id(request),
        )
    except PermissionsUnavailableError:
        raise _unavailable() from None
    if grant is None:
        raise ApiError(
            status.HTTP_404_NOT_FOUND,
            "That user is not an active reviewer for that scope.",
            code="reviewer_grant_not_found",
        )
    return _reviewer_view(grant)


# ---------------------------------------------------------------------
# Activos técnicos
# ---------------------------------------------------------------------


@router.post("/assets", response_model=AssetView, status_code=status.HTTP_201_CREATED)
async def create_asset(
    body: AssetBody,
    _admin: Principal = Depends(require_admin),
    permissions: PermissionsRepositoryPort = Depends(get_permissions),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> AssetView:
    """Da de alta un Activo Técnico.

    El modelo es genérico: Tampella será el primer caso, no una excepción
    programada. El dominio tiene que existir en el catálogo, porque
    ``(domain, code)`` es el alcance con el que después se autoriza.
    """
    try:
        domains = await permissions.list_domains()
    except PermissionsUnavailableError:
        raise _unavailable() from None
    if body.domain not in domains:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Unknown knowledge domain.",
            code="unknown_domain",
        )
    try:
        asset = await knowledge.create_asset(
            code=body.code, name=body.name, domain=body.domain, description=body.description
        )
    except AssetAlreadyExistsError:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            "A technical asset with that code already exists.",
            code="asset_already_exists",
        ) from None
    except KnowledgeUnavailableError:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The knowledge store is temporarily unavailable.",
            code="knowledge_store_unavailable",
        ) from None
    return AssetView(
        id=asset.id,
        code=asset.code,
        name=asset.name,
        domain=asset.domain,
        description=asset.description,
        is_active=asset.is_active,
    )
