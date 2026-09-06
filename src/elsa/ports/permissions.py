"""Puerto del modelo de autorización de ELSA.

Materiales dice **quién** eres; ELSA decide **qué** puedes consultar. Este
puerto es la única vía por la que el backend lee y modifica esa decisión.

Reglas que el puerto hace cumplibles:

- **DEFAULT DENY**: sin cuenta activa y sin permiso explícito no hay acceso;
  la única excepción es el administrador de ELSA.
- La autorización efectiva es **por usuario**, no por rol heredado de
  Materiales.
- Otorgar y revocar dejan traza de **quién** y **cuándo**, y generan una
  entrada de auditoría en la misma operación.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class AdminOperation(StrEnum):
    """Operaciones administrativas auditadas.

    Coincide con la restricción ``ck_audit_operation`` de la migración.
    """

    BOOTSTRAP_ADMIN = "bootstrap_admin"
    CREATE_ACCOUNT = "create_account"
    GRANT_PERMISSION = "grant_permission"
    REVOKE_PERMISSION = "revoke_permission"
    ENABLE_USER = "enable_user"
    DISABLE_USER = "disable_user"
    PROMOTE_ADMIN = "promote_admin"
    DEMOTE_ADMIN = "demote_admin"

    # Bloque 2: gobierno del conocimiento técnico.
    REVIEWER_GRANTED = "reviewer_granted"
    REVIEWER_REVOKED = "reviewer_revoked"
    SOURCE_UPLOADED = "source_uploaded"
    IMPORT_COMPLETED = "import_completed"
    IMPORT_FAILED = "import_failed"
    VALIDATION_APPROVED = "validation_approved"
    VALIDATION_REJECTED = "validation_rejected"
    VALIDATION_REVERTED = "validation_reverted"
    BOM_PUBLISHED = "bom_published"
    RECONCILIATION_CREATED = "reconciliation_created"


@dataclass(frozen=True, slots=True)
class ElsaAccount:
    """Cuenta de ELSA asociada a un usuario externo de Materiales."""

    external_user_id: str
    display_name: str | None
    is_active: bool
    is_admin: bool


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    """Permiso otorgado a un usuario sobre un alcance.

    ``equipment`` a ``None`` significa el dominio completo.
    """

    id: str
    external_user_id: str
    domain: str
    equipment: str | None
    granted_by: str
    granted_at: datetime
    revoked_by: str | None = None
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class ReviewerGrant:
    """Capacidad de Revisor Técnico otorgada a un usuario sobre un alcance.

    Tiene la misma forma que :class:`PermissionGrant` porque responde a la
    misma pregunta —¿sobre qué puede actuar esta persona?— pero es una
    capacidad **distinta**: leer conocimiento y validarlo son cosas
    separadas, y tener permiso de lectura no convierte a nadie en revisor.

    ``equipment`` a ``None`` significa todo el dominio.
    """

    id: str
    external_user_id: str
    domain: str
    equipment: str | None
    granted_by: str
    granted_at: datetime
    revoked_by: str | None = None
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """Entrada de la auditoría de cambios administrativos."""

    actor_external_user_id: str | None
    subject_external_user_id: str
    operation: AdminOperation
    scope_domain: str | None
    scope_equipment: str | None
    request_id: str | None
    occurred_at: datetime


class PermissionsUnavailableError(Exception):
    """La base de permisos de ELSA no está disponible → 503."""


class UnknownDomainError(Exception):
    """El dominio no existe en el catálogo de ELSA."""


class AccountNotFoundError(Exception):
    """No existe cuenta de ELSA para ese usuario externo."""


class BootstrapAlreadyCompletedError(Exception):
    """Ya existe al menos un administrador; el bootstrap no aplica."""


@runtime_checkable
class PermissionsRepositoryPort(Protocol):
    """Lectura y escritura del modelo de autorización de ELSA."""

    async def get_account(self, external_user_id: str) -> ElsaAccount | None:
        """Cuenta de ELSA del usuario, o ``None`` si no está asociado."""
        ...

    async def list_active_grants(self, external_user_id: str) -> tuple[PermissionGrant, ...]:
        """Permisos vigentes (no revocados) del usuario."""
        ...

    async def list_domains(self) -> tuple[str, ...]:
        """Códigos de los dominios de conocimiento activos."""
        ...

    async def count_admins(self) -> int:
        """Número de administradores activos de ELSA."""
        ...

    async def grant_permission(
        self,
        *,
        subject: str,
        domain: str,
        equipment: str | None,
        actor: str,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> PermissionGrant:
        """Otorga un permiso, creando la cuenta si aún no existe.

        Idempotente: si ya existe un permiso vigente idéntico lo devuelve
        sin duplicarlo ni volver a auditarlo. Lanza
        :class:`UnknownDomainError` si el dominio no está en el catálogo.
        """
        ...

    async def revoke_permission(
        self,
        *,
        subject: str,
        domain: str,
        equipment: str | None,
        actor: str,
        request_id: str | None = None,
    ) -> PermissionGrant | None:
        """Revoca un permiso vigente; ``None`` si no había ninguno."""
        ...

    async def set_account_active(
        self,
        *,
        subject: str,
        is_active: bool,
        actor: str,
        request_id: str | None = None,
    ) -> ElsaAccount:
        """Activa o desactiva la cuenta dentro de ELSA."""
        ...

    async def set_account_admin(
        self,
        *,
        subject: str,
        is_admin: bool,
        actor: str,
        request_id: str | None = None,
    ) -> ElsaAccount:
        """Otorga o retira la administración de ELSA."""
        ...

    async def bootstrap_admin(
        self,
        *,
        subject: str,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> tuple[ElsaAccount, bool]:
        """Declara al primer administrador de ELSA.

        Devuelve la cuenta y si esta invocación fue la que lo creó
        (``False`` cuando ya era administrador: la operación es
        idempotente). Lanza :class:`BootstrapAlreadyCompletedError` si ya
        hay otro administrador distinto del solicitante.
        """
        ...

    async def list_audit_entries(
        self,
        *,
        subject: str | None = None,
        limit: int = 50,
    ) -> tuple[AuditEntry, ...]:
        """Entradas de auditoría, de la más reciente a la más antigua."""
        ...

    async def list_active_reviewer_grants(self, external_user_id: str) -> tuple[ReviewerGrant, ...]:
        """Capacidades de revisor vigentes del usuario."""
        ...

    async def grant_reviewer(
        self,
        *,
        subject: str,
        domain: str,
        equipment: str | None,
        actor: str,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> ReviewerGrant:
        """Habilita a un usuario como Revisor Técnico sobre un alcance.

        Idempotente, como :meth:`grant_permission`. Solo un administrador
        debe llegar hasta aquí: la comprobación la hace la capa HTTP.
        """
        ...

    async def revoke_reviewer(
        self,
        *,
        subject: str,
        domain: str,
        equipment: str | None,
        actor: str,
        request_id: str | None = None,
    ) -> ReviewerGrant | None:
        """Deshabilita a un revisor; ``None`` si no estaba habilitado.

        La capacidad se pierde de inmediato, pero las validaciones que ya
        firmó permanecen: borrarlas dejaría aprobaciones sin responsable.
        """
        ...

    async def check_health(self) -> None:
        """Comprueba la disponibilidad del almacén de permisos.

        Lanza :class:`PermissionsUnavailableError` si no responde.
        """
        ...
