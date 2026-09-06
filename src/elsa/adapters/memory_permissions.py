"""Repositorio de permisos en memoria (determinista, DEV y tests).

Implementa exactamente la misma semántica que el repositorio PostgreSQL:
ambos pasan la misma batería de tests de contrato
(``tests/test_contract_permissions.py``). No persiste nada: al reiniciar el
proceso se pierde, por eso solo se permite en DEV.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from elsa.core.authorization import normalize_scope_value
from elsa.ports.permissions import (
    AccountNotFoundError,
    AdminOperation,
    AuditEntry,
    BootstrapAlreadyCompletedError,
    ElsaAccount,
    PermissionGrant,
    ReviewerGrant,
    UnknownDomainError,
)

_DEFAULT_DOMAINS: tuple[str, ...] = ("mantenimiento", "materiales")


class InMemoryPermissionsRepository:
    """Modelo de autorización de ELSA en memoria."""

    def __init__(self, domains: tuple[str, ...] = _DEFAULT_DOMAINS) -> None:
        self._domains = tuple(normalize_scope_value(domain) for domain in domains)
        self._accounts: dict[str, ElsaAccount] = {}
        self._grants: list[PermissionGrant] = []
        self._reviewers: list[ReviewerGrant] = []
        self._audit: list[AuditEntry] = []
        self._lock = asyncio.Lock()

    # -----------------------------------------------------------------
    # Lectura
    # -----------------------------------------------------------------

    async def get_account(self, external_user_id: str) -> ElsaAccount | None:
        return self._accounts.get(external_user_id)

    async def list_active_grants(self, external_user_id: str) -> tuple[PermissionGrant, ...]:
        return tuple(
            grant
            for grant in self._grants
            if grant.external_user_id == external_user_id and grant.is_active
        )

    async def list_domains(self) -> tuple[str, ...]:
        return self._domains

    async def count_admins(self) -> int:
        return sum(
            1 for account in self._accounts.values() if account.is_admin and account.is_active
        )

    async def list_audit_entries(
        self,
        *,
        subject: str | None = None,
        limit: int = 50,
    ) -> tuple[AuditEntry, ...]:
        entries = [
            entry
            for entry in reversed(self._audit)
            if subject is None or entry.subject_external_user_id == subject
        ]
        return tuple(entries[:limit])

    async def list_active_reviewer_grants(self, external_user_id: str) -> tuple[ReviewerGrant, ...]:
        return tuple(
            grant
            for grant in self._reviewers
            if grant.external_user_id == external_user_id and grant.is_active
        )

    async def check_health(self) -> None:
        return None

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
        if scope_domain not in self._domains:
            raise UnknownDomainError(f"unknown knowledge domain: {scope_domain!r}")

        async with self._lock:
            self._ensure_account(subject, display_name, actor, request_id)

            existing = self._find_active_grant(subject, scope_domain, scope_equipment)
            if existing is not None:
                return existing

            grant = PermissionGrant(
                id=str(uuid.uuid4()),
                external_user_id=subject,
                domain=scope_domain,
                equipment=scope_equipment,
                granted_by=actor,
                granted_at=datetime.now(tz=UTC),
            )
            self._grants.append(grant)
            self._record(
                actor=actor,
                subject=subject,
                operation=AdminOperation.GRANT_PERMISSION,
                domain=scope_domain,
                equipment=scope_equipment,
                request_id=request_id,
            )
            return grant

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

        async with self._lock:
            existing = self._find_active_grant(subject, scope_domain, scope_equipment)
            if existing is None:
                return None

            revoked = PermissionGrant(
                id=existing.id,
                external_user_id=existing.external_user_id,
                domain=existing.domain,
                equipment=existing.equipment,
                granted_by=existing.granted_by,
                granted_at=existing.granted_at,
                revoked_by=actor,
                revoked_at=datetime.now(tz=UTC),
            )
            self._grants[self._grants.index(existing)] = revoked
            self._record(
                actor=actor,
                subject=subject,
                operation=AdminOperation.REVOKE_PERMISSION,
                domain=scope_domain,
                equipment=scope_equipment,
                request_id=request_id,
            )
            return revoked

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
        if scope_domain not in self._domains:
            raise UnknownDomainError(f"unknown knowledge domain: {scope_domain!r}")

        async with self._lock:
            self._ensure_account(subject, display_name, actor, request_id)
            existing = self._find_active_reviewer(subject, scope_domain, scope_equipment)
            if existing is not None:
                return existing

            grant = ReviewerGrant(
                id=str(uuid.uuid4()),
                external_user_id=subject,
                domain=scope_domain,
                equipment=scope_equipment,
                granted_by=actor,
                granted_at=datetime.now(tz=UTC),
            )
            self._reviewers.append(grant)
            self._record(
                actor=actor,
                subject=subject,
                operation=AdminOperation.REVIEWER_GRANTED,
                domain=scope_domain,
                equipment=scope_equipment,
                request_id=request_id,
            )
            return grant

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

        async with self._lock:
            existing = self._find_active_reviewer(subject, scope_domain, scope_equipment)
            if existing is None:
                return None

            revoked = ReviewerGrant(
                id=existing.id,
                external_user_id=existing.external_user_id,
                domain=existing.domain,
                equipment=existing.equipment,
                granted_by=existing.granted_by,
                granted_at=existing.granted_at,
                revoked_by=actor,
                revoked_at=datetime.now(tz=UTC),
            )
            self._reviewers[self._reviewers.index(existing)] = revoked
            self._record(
                actor=actor,
                subject=subject,
                operation=AdminOperation.REVIEWER_REVOKED,
                domain=scope_domain,
                equipment=scope_equipment,
                request_id=request_id,
            )
            return revoked

    async def set_account_active(
        self,
        *,
        subject: str,
        is_active: bool,
        actor: str,
        request_id: str | None = None,
    ) -> ElsaAccount:
        async with self._lock:
            account = self._accounts.get(subject)
            if account is None:
                raise AccountNotFoundError(subject)
            if account.is_active == is_active:
                return account
            updated = ElsaAccount(
                external_user_id=account.external_user_id,
                display_name=account.display_name,
                is_active=is_active,
                is_admin=account.is_admin,
            )
            self._accounts[subject] = updated
            self._record(
                actor=actor,
                subject=subject,
                operation=(
                    AdminOperation.ENABLE_USER if is_active else AdminOperation.DISABLE_USER
                ),
                request_id=request_id,
            )
            return updated

    async def set_account_admin(
        self,
        *,
        subject: str,
        is_admin: bool,
        actor: str,
        request_id: str | None = None,
    ) -> ElsaAccount:
        async with self._lock:
            account = self._accounts.get(subject)
            if account is None:
                raise AccountNotFoundError(subject)
            if account.is_admin == is_admin:
                return account
            updated = ElsaAccount(
                external_user_id=account.external_user_id,
                display_name=account.display_name,
                is_active=account.is_active,
                is_admin=is_admin,
            )
            self._accounts[subject] = updated
            self._record(
                actor=actor,
                subject=subject,
                operation=(
                    AdminOperation.PROMOTE_ADMIN if is_admin else AdminOperation.DEMOTE_ADMIN
                ),
                request_id=request_id,
            )
            return updated

    async def bootstrap_admin(
        self,
        *,
        subject: str,
        display_name: str | None = None,
        request_id: str | None = None,
    ) -> tuple[ElsaAccount, bool]:
        async with self._lock:
            account = self._accounts.get(subject)
            if account is not None and account.is_admin and account.is_active:
                return account, False

            others = [
                other
                for other in self._accounts.values()
                if other.is_admin and other.is_active and other.external_user_id != subject
            ]
            if others:
                raise BootstrapAlreadyCompletedError("ELSA already has an administrator")

            promoted = ElsaAccount(
                external_user_id=subject,
                display_name=display_name or (account.display_name if account else None),
                is_active=True,
                is_admin=True,
            )
            self._accounts[subject] = promoted
            self._record(
                actor=subject,
                subject=subject,
                operation=AdminOperation.BOOTSTRAP_ADMIN,
                request_id=request_id,
            )
            return promoted, True

    # -----------------------------------------------------------------
    # Interno
    # -----------------------------------------------------------------

    def _ensure_account(
        self,
        subject: str,
        display_name: str | None,
        actor: str,
        request_id: str | None,
    ) -> ElsaAccount:
        account = self._accounts.get(subject)
        if account is not None:
            return account
        account = ElsaAccount(
            external_user_id=subject,
            display_name=display_name,
            is_active=True,
            is_admin=False,
        )
        self._accounts[subject] = account
        self._record(
            actor=actor,
            subject=subject,
            operation=AdminOperation.CREATE_ACCOUNT,
            request_id=request_id,
        )
        return account

    def _find_active_grant(
        self,
        subject: str,
        domain: str,
        equipment: str | None,
    ) -> PermissionGrant | None:
        for grant in self._grants:
            if (
                grant.external_user_id == subject
                and grant.domain == domain
                and grant.equipment == equipment
                and grant.is_active
            ):
                return grant
        return None

    def _find_active_reviewer(
        self,
        subject: str,
        domain: str,
        equipment: str | None,
    ) -> ReviewerGrant | None:
        for grant in self._reviewers:
            if (
                grant.external_user_id == subject
                and grant.domain == domain
                and grant.equipment == equipment
                and grant.is_active
            ):
                return grant
        return None

    def _record(
        self,
        *,
        actor: str | None,
        subject: str,
        operation: AdminOperation,
        domain: str | None = None,
        equipment: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self._audit.append(
            AuditEntry(
                actor_external_user_id=actor,
                subject_external_user_id=subject,
                operation=operation,
                scope_domain=domain,
                scope_equipment=equipment,
                request_id=request_id,
                occurred_at=datetime.now(tz=UTC),
            )
        )
