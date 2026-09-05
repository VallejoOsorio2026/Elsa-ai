"""Reglas puras de autorización: default deny, alcances y administración.

Estas reglas no dependen de HTTP ni de la base de datos, así que se prueban
directamente sobre el módulo que las decide.
"""

import pytest

from elsa.core.authorization import (
    DenialReason,
    InvalidScopeError,
    Principal,
    Scope,
    authorize,
    covers,
    normalize_scope_value,
)


def principal(
    *,
    is_admin: bool = False,
    is_active: bool = True,
    scopes: tuple[Scope, ...] = (),
) -> Principal:
    return Principal(
        external_user_id="11111111-1111-4111-8111-111111111111",
        display_name="Prueba",
        is_active=is_active,
        is_admin=is_admin,
        scopes=scopes,
    )


# ---------------------------------------------------------------------
# Normalización de alcances
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Tampella", "tampella"),
        ("  MANTENIMIENTO  ", "mantenimiento"),
        ("linea-2", "linea-2"),
        ("bomba_01", "bomba_01"),
    ],
)
def test_scope_values_are_normalized(raw: str, expected: str) -> None:
    assert normalize_scope_value(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "con espacio", "-empieza-con-guion", "acentuación", "../otro", "x" * 65],
)
def test_invalid_scope_values_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidScopeError):
        normalize_scope_value(raw)


# ---------------------------------------------------------------------
# Cobertura de un permiso sobre un alcance
# ---------------------------------------------------------------------


def test_domain_grant_covers_the_domain_and_any_equipment() -> None:
    granted = Scope("mantenimiento")

    assert covers(granted, Scope("mantenimiento"))
    assert covers(granted, Scope("mantenimiento", "tampella"))
    assert covers(granted, Scope("mantenimiento", "cualquier-otro"))


def test_equipment_grant_covers_only_that_equipment() -> None:
    granted = Scope("mantenimiento", "tampella")

    assert covers(granted, Scope("mantenimiento", "tampella"))
    assert not covers(granted, Scope("mantenimiento"))
    assert not covers(granted, Scope("mantenimiento", "otro"))
    assert not covers(granted, Scope("materiales", "tampella"))


# ---------------------------------------------------------------------
# Decisión
# ---------------------------------------------------------------------


def test_default_deny_without_grants() -> None:
    decision = authorize(principal(), Scope("mantenimiento"))

    assert decision.allowed is False
    assert decision.reason is DenialReason.NO_MATCHING_GRANT


def test_admin_is_allowed_everywhere() -> None:
    decision = authorize(principal(is_admin=True), Scope("materiales", "cualquier-equipo"))

    assert decision.allowed is True
    assert decision.via_admin is True


def test_inactive_account_is_denied_even_as_admin() -> None:
    decision = authorize(
        principal(is_admin=True, is_active=False), Scope("mantenimiento", "tampella")
    )

    assert decision.allowed is False
    assert decision.reason is DenialReason.ACCOUNT_INACTIVE


def test_a_matching_grant_is_reported() -> None:
    granted = Scope("mantenimiento", "tampella")

    decision = authorize(principal(scopes=(granted,)), Scope("mantenimiento", "tampella"))

    assert decision.allowed is True
    assert decision.via_admin is False
    assert decision.matched_scope == granted


def test_a_grant_on_another_domain_does_not_help() -> None:
    decision = authorize(
        principal(scopes=(Scope("materiales"),)), Scope("mantenimiento", "tampella")
    )

    assert decision.allowed is False
