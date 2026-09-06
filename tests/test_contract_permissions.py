"""Contrato del puerto de permisos.

La misma batería corre contra los dos adaptadores: el de memoria (DEV y
tests) y el de PostgreSQL (Supabase ELSA). Si divergen, uno de los dos falla
aquí: el adaptador de memoria no puede volverse una ficción cómoda.
"""

from collections.abc import AsyncIterator

import pytest

from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.adapters.postgres_permissions import PostgresPermissionsRepository
from elsa.ports.permissions import (
    AccountNotFoundError,
    AdminOperation,
    BootstrapAlreadyCompletedError,
    PermissionsRepositoryPort,
    UnknownDomainError,
)
from tests import db

pytestmark = pytest.mark.anyio

ADMIN = "aaaaaaaa-0000-4000-8000-000000000001"
USER = "bbbbbbbb-0000-4000-8000-000000000002"
OTHER = "cccccccc-0000-4000-8000-000000000003"


@pytest.fixture(params=["memory", "postgres"])
async def repository(request: pytest.FixtureRequest) -> AsyncIterator[PermissionsRepositoryPort]:
    if request.param == "memory":
        yield InMemoryPermissionsRepository()
        return

    url = db.database_url()
    if url is None:
        pytest.skip(db.SKIP_REASON)
    await db.reset_database(url)
    postgres = await PostgresPermissionsRepository.connect(url, min_size=1, max_size=2)
    try:
        yield postgres
    finally:
        await postgres.close()


# ---------------------------------------------------------------------
# Default deny y lectura
# ---------------------------------------------------------------------


async def test_unknown_user_has_no_account_and_no_grants(
    repository: PermissionsRepositoryPort,
) -> None:
    assert await repository.get_account(USER) is None
    assert await repository.list_active_grants(USER) == ()


async def test_initial_domains_are_available(repository: PermissionsRepositoryPort) -> None:
    domains = await repository.list_domains()

    assert "mantenimiento" in domains
    assert "materiales" in domains


# ---------------------------------------------------------------------
# Otorgar y revocar
# ---------------------------------------------------------------------


async def test_granting_creates_the_account_and_the_grant(
    repository: PermissionsRepositoryPort,
) -> None:
    grant = await repository.grant_permission(
        subject=USER,
        domain="mantenimiento",
        equipment="tampella",
        actor=ADMIN,
        display_name="Ingeniero",
    )

    assert grant.domain == "mantenimiento"
    assert grant.equipment == "tampella"
    assert grant.granted_by == ADMIN
    assert grant.is_active

    account = await repository.get_account(USER)
    assert account is not None
    assert account.is_active is True
    assert account.is_admin is False
    assert [(g.domain, g.equipment) for g in await repository.list_active_grants(USER)] == [
        ("mantenimiento", "tampella")
    ]


async def test_scope_values_are_normalized(repository: PermissionsRepositoryPort) -> None:
    """Los alcances son dato: `Tampella` y `tampella` son el mismo equipo."""
    grant = await repository.grant_permission(
        subject=USER, domain="  Mantenimiento ", equipment="TAMPELLA", actor=ADMIN
    )

    assert (grant.domain, grant.equipment) == ("mantenimiento", "tampella")


async def test_granting_twice_is_idempotent(repository: PermissionsRepositoryPort) -> None:
    first = await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment="tampella", actor=ADMIN
    )
    second = await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment="tampella", actor=ADMIN
    )

    assert first.id == second.id
    assert len(await repository.list_active_grants(USER)) == 1


async def test_domain_grant_and_equipment_grant_coexist(
    repository: PermissionsRepositoryPort,
) -> None:
    await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment=None, actor=ADMIN
    )
    await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment="tampella", actor=ADMIN
    )

    assert len(await repository.list_active_grants(USER)) == 2


async def test_unknown_domain_is_rejected(repository: PermissionsRepositoryPort) -> None:
    with pytest.raises(UnknownDomainError):
        await repository.grant_permission(
            subject=USER, domain="inexistente", equipment=None, actor=ADMIN
        )


async def test_revoking_removes_the_grant_and_keeps_its_history(
    repository: PermissionsRepositoryPort,
) -> None:
    await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment="tampella", actor=ADMIN
    )

    revoked = await repository.revoke_permission(
        subject=USER, domain="mantenimiento", equipment="tampella", actor=OTHER
    )

    assert revoked is not None
    assert revoked.revoked_by == OTHER
    assert revoked.revoked_at is not None
    assert revoked.granted_by == ADMIN
    assert await repository.list_active_grants(USER) == ()


async def test_revoking_a_missing_grant_returns_none(
    repository: PermissionsRepositoryPort,
) -> None:
    assert (
        await repository.revoke_permission(
            subject=USER, domain="mantenimiento", equipment=None, actor=ADMIN
        )
        is None
    )


async def test_revoking_the_domain_does_not_revoke_the_equipment(
    repository: PermissionsRepositoryPort,
) -> None:
    await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment=None, actor=ADMIN
    )
    await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment="tampella", actor=ADMIN
    )

    await repository.revoke_permission(
        subject=USER, domain="mantenimiento", equipment=None, actor=ADMIN
    )

    remaining = await repository.list_active_grants(USER)
    assert [(g.domain, g.equipment) for g in remaining] == [("mantenimiento", "tampella")]


async def test_a_revoked_grant_can_be_granted_again(
    repository: PermissionsRepositoryPort,
) -> None:
    first = await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment="tampella", actor=ADMIN
    )
    await repository.revoke_permission(
        subject=USER, domain="mantenimiento", equipment="tampella", actor=ADMIN
    )

    second = await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment="tampella", actor=ADMIN
    )

    assert second.id != first.id
    assert len(await repository.list_active_grants(USER)) == 1


# ---------------------------------------------------------------------
# Estado de la cuenta y administración
# ---------------------------------------------------------------------


async def test_disabling_and_enabling_an_account(repository: PermissionsRepositoryPort) -> None:
    await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment=None, actor=ADMIN
    )

    disabled = await repository.set_account_active(subject=USER, is_active=False, actor=ADMIN)
    assert disabled.is_active is False

    enabled = await repository.set_account_active(subject=USER, is_active=True, actor=ADMIN)
    assert enabled.is_active is True


async def test_status_change_on_a_missing_account_fails(
    repository: PermissionsRepositoryPort,
) -> None:
    with pytest.raises(AccountNotFoundError):
        await repository.set_account_active(subject=USER, is_active=False, actor=ADMIN)


async def test_administration_can_be_granted_and_transferred(
    repository: PermissionsRepositoryPort,
) -> None:
    await repository.bootstrap_admin(subject=ADMIN)
    await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment=None, actor=ADMIN
    )

    promoted = await repository.set_account_admin(subject=USER, is_admin=True, actor=ADMIN)
    assert promoted.is_admin is True
    assert await repository.count_admins() == 2

    demoted = await repository.set_account_admin(subject=ADMIN, is_admin=False, actor=USER)
    assert demoted.is_admin is False
    assert await repository.count_admins() == 1


# ---------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------


async def test_bootstrap_declares_the_first_administrator(
    repository: PermissionsRepositoryPort,
) -> None:
    account, created = await repository.bootstrap_admin(subject=ADMIN, display_name="Jefa")

    assert created is True
    assert account.is_admin is True
    assert account.is_active is True
    assert await repository.count_admins() == 1


async def test_bootstrap_is_idempotent(repository: PermissionsRepositoryPort) -> None:
    await repository.bootstrap_admin(subject=ADMIN)

    account, created = await repository.bootstrap_admin(subject=ADMIN)

    assert created is False
    assert account.is_admin is True
    assert await repository.count_admins() == 1


async def test_bootstrap_refuses_a_second_administrator(
    repository: PermissionsRepositoryPort,
) -> None:
    await repository.bootstrap_admin(subject=ADMIN)

    with pytest.raises(BootstrapAlreadyCompletedError):
        await repository.bootstrap_admin(subject=OTHER)


# ---------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------


async def test_every_administrative_change_is_audited(
    repository: PermissionsRepositoryPort,
) -> None:
    await repository.bootstrap_admin(subject=ADMIN)
    await repository.grant_permission(
        subject=USER,
        domain="mantenimiento",
        equipment="tampella",
        actor=ADMIN,
        request_id="req-0001",
    )
    await repository.revoke_permission(
        subject=USER, domain="mantenimiento", equipment="tampella", actor=ADMIN
    )
    await repository.set_account_active(subject=USER, is_active=False, actor=ADMIN)

    operations = [entry.operation for entry in await repository.list_audit_entries()]

    assert operations[:3] == [
        AdminOperation.DISABLE_USER,
        AdminOperation.REVOKE_PERMISSION,
        AdminOperation.GRANT_PERMISSION,
    ]
    assert AdminOperation.CREATE_ACCOUNT in operations
    assert AdminOperation.BOOTSTRAP_ADMIN in operations


async def test_audit_records_actor_subject_scope_and_request(
    repository: PermissionsRepositoryPort,
) -> None:
    await repository.grant_permission(
        subject=USER,
        domain="mantenimiento",
        equipment="tampella",
        actor=ADMIN,
        request_id="req-0002",
    )

    entries = await repository.list_audit_entries(subject=USER)
    granted = next(entry for entry in entries if entry.operation is AdminOperation.GRANT_PERMISSION)

    assert granted.actor_external_user_id == ADMIN
    assert granted.subject_external_user_id == USER
    assert granted.scope_domain == "mantenimiento"
    assert granted.scope_equipment == "tampella"
    assert granted.request_id == "req-0002"
    assert granted.occurred_at is not None


async def test_audit_can_be_filtered_by_subject(repository: PermissionsRepositoryPort) -> None:
    await repository.grant_permission(
        subject=USER, domain="mantenimiento", equipment=None, actor=ADMIN
    )
    await repository.grant_permission(
        subject=OTHER, domain="materiales", equipment=None, actor=ADMIN
    )

    entries = await repository.list_audit_entries(subject=OTHER)

    assert entries
    assert {entry.subject_external_user_id for entry in entries} == {OTHER}


async def test_health_check_passes(repository: PermissionsRepositoryPort) -> None:
    await repository.check_health()
