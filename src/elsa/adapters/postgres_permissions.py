"""Repositorio de permisos sobre Supabase ELSA (PostgreSQL).

Accede con la credencial de servicio del backend, que nunca sale de él
(ADR 0002). Todas las escrituras administrativas ocurren dentro de una
transacción junto con su entrada de auditoría: o quedan ambas, o ninguna.
Una auditoría que puede perderse mientras el cambio persiste no es
auditoría.

El esquema lo definen las migraciones versionadas bajo
``supabase/migrations/``; este adaptador no crea ni altera estructura.
"""

import contextlib
import logging
import uuid
from collections.abc import Iterator
from typing import Any

import asyncpg

from elsa.core.authorization import normalize_scope_value
from elsa.ports.permissions import (
    AccountNotFoundError,
    AdminOperation,
    AuditEntry,
    BootstrapAlreadyCompletedError,
    ElsaAccount,
    PermissionGrant,
    PermissionsUnavailableError,
    ReviewerGrant,
    UnknownDomainError,
)

_logger = logging.getLogger("elsa.permissions.postgres")

# Clave del cerrojo consultivo que serializa el bootstrap del primer
# administrador entre procesos.
_BOOTSTRAP_LOCK_KEY = 5150122308143240001

_ACCOUNT_COLUMNS = "external_user_id, display_name, is_active, is_admin"
_GRANT_COLUMNS = (
    "id, external_user_id, domain, equipment, granted_by, granted_at, revoked_by, revoked_at"
)
_REVIEWER_COLUMNS = (
    "id, external_user_id, domain, equipment, granted_by, granted_at, revoked_by, revoked_at"
)
_AUDIT_COLUMNS = (
    "actor_external_user_id, subject_external_user_id, operation, "
    "scope_domain, scope_equipment, request_id, occurred_at"
)

_INSERT_AUDIT = """
insert into elsa.admin_audit_log (
    actor_external_user_id, subject_external_user_id, operation,
    scope_domain, scope_equipment, request_id
) values ($1, $2, $3, $4, $5, $6)
"""


@contextlib.contextmanager
def _database_errors() -> Iterator[None]:
    """Traduce fallos técnicos de la base a un error de disponibilidad (503)."""
    try:
        yield
    except (asyncpg.PostgresError, OSError, TimeoutError) as exc:
        _logger.warning("permissions store failure", extra={"error": type(exc).__name__})
        raise PermissionsUnavailableError("the ELSA permissions store is unavailable") from None


def _as_uuid(value: str) -> uuid.UUID:
    return uuid.UUID(value)


class PostgresPermissionsRepository:
    """Modelo de autorización de ELSA persistido en Supabase ELSA."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(
        cls,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 10,
        timeout_seconds: float = 10.0,
    ) -> "PostgresPermissionsRepository":
        """Abre el pool de conexiones. La cadena nunca se registra."""
        with _database_errors():
            pool = await asyncpg.create_pool(
                dsn,
                min_size=min_size,
                max_size=max_size,
                command_timeout=timeout_seconds,
            )
        if pool is None:  # pragma: no cover - asyncpg solo devuelve None sin `loop`
            raise PermissionsUnavailableError("could not create the connection pool")
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    # -----------------------------------------------------------------
    # Lectura
    # -----------------------------------------------------------------

    async def get_account(self, external_user_id: str) -> ElsaAccount | None:
        with _database_errors():
            row = await self._pool.fetchrow(
                f"select {_ACCOUNT_COLUMNS} from elsa.accounts where external_user_id = $1",
                _as_uuid(external_user_id),
            )
        return None if row is None else _account(row)

    async def list_active_grants(self, external_user_id: str) -> tuple[PermissionGrant, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_GRANT_COLUMNS} from elsa.permission_grants "
                "where external_user_id = $1 and revoked_at is null "
                "order by domain, equipment nulls first",
                _as_uuid(external_user_id),
            )
        return tuple(_grant(row) for row in rows)

    async def list_domains(self) -> tuple[str, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                "select code from elsa.knowledge_domains where is_active order by code"
            )
        return tuple(str(row["code"]) for row in rows)

    async def count_admins(self) -> int:
        with _database_errors():
            value = await self._pool.fetchval(
                "select count(*) from elsa.accounts where is_admin and is_active"
            )
        return int(value or 0)

    async def list_audit_entries(
        self,
        *,
        subject: str | None = None,
        limit: int = 50,
    ) -> tuple[AuditEntry, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_AUDIT_COLUMNS} from elsa.admin_audit_log "
                "where ($1::uuid is null or subject_external_user_id = $1) "
                "order by occurred_at desc, id desc limit $2",
                None if subject is None else _as_uuid(subject),
                limit,
            )
        return tuple(_audit_entry(row) for row in rows)

    async def list_active_reviewer_grants(self, external_user_id: str) -> tuple[ReviewerGrant, ...]:
        with _database_errors():
            rows = await self._pool.fetch(
                f"select {_REVIEWER_COLUMNS} from elsa.reviewer_grants "
                "where external_user_id = $1 and revoked_at is null "
                "order by domain, equipment nulls first",
                _as_uuid(external_user_id),
            )
        return tuple(_reviewer_grant(row) for row in rows)

    async def check_health(self) -> None:
        with _database_errors():
            await self._pool.fetchval("select 1")

    # -----------------------------------------------------------------
    # Escritura
    # -----------------------------------------------------------------

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
        scope_domain = normalize_scope_value(domain)
        scope_equipment = None if equipment is None else normalize_scope_value(equipment)
        subject_id, actor_id = _as_uuid(subject), _as_uuid(actor)

        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                known = await connection.fetchval(
                    "select 1 from elsa.knowledge_domains where code = $1 and is_active",
                    scope_domain,
                )
                if known is None:
                    raise UnknownDomainError(f"unknown knowledge domain: {scope_domain!r}")

                await self._ensure_account(
                    connection,
                    subject=subject_id,
                    display_name=display_name,
                    actor=actor_id,
                    request_id=request_id,
                )

                existing = await connection.fetchrow(
                    f"select {_GRANT_COLUMNS} from elsa.permission_grants "
                    "where external_user_id = $1 and domain = $2 "
                    "and equipment is not distinct from $3 and revoked_at is null",
                    subject_id,
                    scope_domain,
                    scope_equipment,
                )
                if existing is not None:
                    return _grant(existing)

                row = await connection.fetchrow(
                    "insert into elsa.permission_grants "
                    "(external_user_id, domain, equipment, granted_by) "
                    f"values ($1, $2, $3, $4) returning {_GRANT_COLUMNS}",
                    subject_id,
                    scope_domain,
                    scope_equipment,
                    actor_id,
                )
                await connection.execute(
                    _INSERT_AUDIT,
                    actor_id,
                    subject_id,
                    AdminOperation.GRANT_PERMISSION.value,
                    scope_domain,
                    scope_equipment,
                    request_id,
                )
                assert row is not None  # noqa: S101 - `returning` siempre devuelve fila
                return _grant(row)

    async def revoke_permission(
        self,
        *,
        subject: str,
        domain: str,
        equipment: str | None,
        actor: str,
        request_id: str | None = None,
    ) -> PermissionGrant | None:
        scope_domain = normalize_scope_value(domain)
        scope_equipment = None if equipment is None else normalize_scope_value(equipment)
        subject_id, actor_id = _as_uuid(subject), _as_uuid(actor)

        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                row = await connection.fetchrow(
                    "update elsa.permission_grants set revoked_at = now(), revoked_by = $4 "
                    "where external_user_id = $1 and domain = $2 "
                    "and equipment is not distinct from $3 and revoked_at is null "
                    f"returning {_GRANT_COLUMNS}",
                    subject_id,
                    scope_domain,
                    scope_equipment,
                    actor_id,
                )
                if row is None:
                    return None
                await connection.execute(
                    _INSERT_AUDIT,
                    actor_id,
                    subject_id,
                    AdminOperation.REVOKE_PERMISSION.value,
                    scope_domain,
                    scope_equipment,
                    request_id,
                )
                return _grant(row)

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
        scope_domain = normalize_scope_value(domain)
        scope_equipment = None if equipment is None else normalize_scope_value(equipment)
        subject_id, actor_id = _as_uuid(subject), _as_uuid(actor)

        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                known = await connection.fetchval(
                    "select 1 from elsa.knowledge_domains where code = $1 and is_active",
                    scope_domain,
                )
                if known is None:
                    raise UnknownDomainError(f"unknown knowledge domain: {scope_domain!r}")

                await self._ensure_account(
                    connection,
                    subject=subject_id,
                    display_name=display_name,
                    actor=actor_id,
                    request_id=request_id,
                )

                existing = await connection.fetchrow(
                    f"select {_REVIEWER_COLUMNS} from elsa.reviewer_grants "
                    "where external_user_id = $1 and domain = $2 "
                    "and equipment is not distinct from $3 and revoked_at is null",
                    subject_id,
                    scope_domain,
                    scope_equipment,
                )
                if existing is not None:
                    return _reviewer_grant(existing)

                row = await connection.fetchrow(
                    "insert into elsa.reviewer_grants "
                    "(external_user_id, domain, equipment, granted_by) "
                    f"values ($1, $2, $3, $4) returning {_REVIEWER_COLUMNS}",
                    subject_id,
                    scope_domain,
                    scope_equipment,
                    actor_id,
                )
                await connection.execute(
                    _INSERT_AUDIT,
                    actor_id,
                    subject_id,
                    AdminOperation.REVIEWER_GRANTED.value,
                    scope_domain,
                    scope_equipment,
                    request_id,
                )
                assert row is not None  # noqa: S101 - `returning` siempre devuelve fila
                return _reviewer_grant(row)

    async def revoke_reviewer(
        self,
        *,
        subject: str,
        domain: str,
        equipment: str | None,
        actor: str,
        request_id: str | None = None,
    ) -> ReviewerGrant | None:
        scope_domain = normalize_scope_value(domain)
        scope_equipment = None if equipment is None else normalize_scope_value(equipment)
        subject_id, actor_id = _as_uuid(subject), _as_uuid(actor)

        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                # La fila no se borra: se marca revocada. El historial de
                # validaciones que firmó este revisor sigue siendo atribuible.
                row = await connection.fetchrow(
                    "update elsa.reviewer_grants set revoked_at = now(), revoked_by = $4 "
                    "where external_user_id = $1 and domain = $2 "
                    "and equipment is not distinct from $3 and revoked_at is null "
                    f"returning {_REVIEWER_COLUMNS}",
                    subject_id,
                    scope_domain,
                    scope_equipment,
                    actor_id,
                )
                if row is None:
                    return None
                await connection.execute(
                    _INSERT_AUDIT,
                    actor_id,
                    subject_id,
                    AdminOperation.REVIEWER_REVOKED.value,
                    scope_domain,
                    scope_equipment,
                    request_id,
                )
                return _reviewer_grant(row)

    async def set_account_active(
        self,
        *,
        subject: str,
        is_active: bool,
        actor: str,
        request_id: str | None = None,
    ) -> ElsaAccount:
        return await self._update_flag(
            subject=subject,
            actor=actor,
            column="is_active",
            value=is_active,
            operation=AdminOperation.ENABLE_USER if is_active else AdminOperation.DISABLE_USER,
            request_id=request_id,
        )

    async def set_account_admin(
        self,
        *,
        subject: str,
        is_admin: bool,
        actor: str,
        request_id: str | None = None,
    ) -> ElsaAccount:
        return await self._update_flag(
            subject=subject,
            actor=actor,
            column="is_admin",
            value=is_admin,
            operation=AdminOperation.PROMOTE_ADMIN if is_admin else AdminOperation.DEMOTE_ADMIN,
            request_id=request_id,
        )

    async def bootstrap_admin(
        self,
        *,
        subject: str,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> tuple[ElsaAccount, bool]:
        subject_id = _as_uuid(subject)

        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                # Serializa el bootstrap entre procesos: dos peticiones
                # simultáneas no pueden crear dos "primeros" administradores.
                await connection.execute("select pg_advisory_xact_lock($1)", _BOOTSTRAP_LOCK_KEY)

                current = await connection.fetchrow(
                    f"select {_ACCOUNT_COLUMNS} from elsa.accounts where external_user_id = $1",
                    subject_id,
                )
                if current is not None and current["is_admin"] and current["is_active"]:
                    return _account(current), False

                others = await connection.fetchval(
                    "select count(*) from elsa.accounts "
                    "where is_admin and is_active and external_user_id <> $1",
                    subject_id,
                )
                if int(others or 0) > 0:
                    raise BootstrapAlreadyCompletedError("ELSA already has an administrator")

                row = await connection.fetchrow(
                    "insert into elsa.accounts "
                    "(external_user_id, display_name, is_active, is_admin) "
                    "values ($1, $2, true, true) "
                    "on conflict (external_user_id) do update set "
                    "is_active = true, is_admin = true, "
                    "display_name = coalesce(excluded.display_name, elsa.accounts.display_name) "
                    f"returning {_ACCOUNT_COLUMNS}",
                    subject_id,
                    display_name,
                )
                await connection.execute(
                    _INSERT_AUDIT,
                    subject_id,
                    subject_id,
                    AdminOperation.BOOTSTRAP_ADMIN.value,
                    None,
                    None,
                    request_id,
                )
                assert row is not None  # noqa: S101 - `returning` siempre devuelve fila
                return _account(row), True

    # -----------------------------------------------------------------
    # Interno
    # -----------------------------------------------------------------

    async def _ensure_account(
        self,
        connection: asyncpg.Connection,
        *,
        subject: uuid.UUID,
        display_name: str | None,
        actor: uuid.UUID,
        request_id: str | None,
    ) -> None:
        created = await connection.fetchval(
            "insert into elsa.accounts (external_user_id, display_name) values ($1, $2) "
            "on conflict (external_user_id) do nothing returning external_user_id",
            subject,
            display_name,
        )
        if created is not None:
            await connection.execute(
                _INSERT_AUDIT,
                actor,
                subject,
                AdminOperation.CREATE_ACCOUNT.value,
                None,
                None,
                request_id,
            )

    async def _update_flag(
        self,
        *,
        subject: str,
        actor: str,
        column: str,
        value: bool,
        operation: AdminOperation,
        request_id: str | None,
    ) -> ElsaAccount:
        subject_id, actor_id = _as_uuid(subject), _as_uuid(actor)

        with _database_errors():
            async with self._pool.acquire() as connection, connection.transaction():
                # `column` procede de un literal del propio módulo, nunca de
                # entrada del usuario: no hay superficie de inyección.
                row = await connection.fetchrow(
                    f"update elsa.accounts set {column} = $2 where external_user_id = $1 "
                    f"and {column} is distinct from $2 returning {_ACCOUNT_COLUMNS}",
                    subject_id,
                    value,
                )
                if row is not None:
                    await connection.execute(
                        _INSERT_AUDIT,
                        actor_id,
                        subject_id,
                        operation.value,
                        None,
                        None,
                        request_id,
                    )
                    return _account(row)

                unchanged = await connection.fetchrow(
                    f"select {_ACCOUNT_COLUMNS} from elsa.accounts where external_user_id = $1",
                    subject_id,
                )
                if unchanged is None:
                    raise AccountNotFoundError(subject)
                return _account(unchanged)


def _account(row: Any) -> ElsaAccount:
    return ElsaAccount(
        external_user_id=str(row["external_user_id"]),
        display_name=row["display_name"],
        is_active=bool(row["is_active"]),
        is_admin=bool(row["is_admin"]),
    )


def _grant(row: Any) -> PermissionGrant:
    return PermissionGrant(
        id=str(row["id"]),
        external_user_id=str(row["external_user_id"]),
        domain=str(row["domain"]),
        equipment=row["equipment"],
        granted_by=str(row["granted_by"]),
        granted_at=row["granted_at"],
        revoked_by=None if row["revoked_by"] is None else str(row["revoked_by"]),
        revoked_at=row["revoked_at"],
    )


def _audit_entry(row: Any) -> AuditEntry:
    actor = row["actor_external_user_id"]
    return AuditEntry(
        actor_external_user_id=None if actor is None else str(actor),
        subject_external_user_id=str(row["subject_external_user_id"]),
        operation=AdminOperation(row["operation"]),
        scope_domain=row["scope_domain"],
        scope_equipment=row["scope_equipment"],
        request_id=row["request_id"],
        occurred_at=row["occurred_at"],
    )


def _reviewer_grant(row: Any) -> ReviewerGrant:
    return ReviewerGrant(
        id=str(row["id"]),
        external_user_id=str(row["external_user_id"]),
        domain=str(row["domain"]),
        equipment=row["equipment"],
        granted_by=str(row["granted_by"]),
        granted_at=row["granted_at"],
        revoked_by=None if row["revoked_by"] is None else str(row["revoked_by"]),
        revoked_at=row["revoked_at"],
    )
