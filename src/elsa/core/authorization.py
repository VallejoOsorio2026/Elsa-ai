"""Decisión de autorización de ELSA.

Este módulo es la única autoridad que decide si un usuario puede acceder a
un alcance. No conoce HTTP, ni la base de datos, ni el LLM: recibe una
identidad ya resuelta y un alcance requerido, y devuelve una decisión.

Reglas (CLAUDE.md, reglas 3 y 4; Bloque 1):

- **DEFAULT DENY**: sin permiso explícito y sin ser administrador, se niega.
- El administrador de ELSA tiene acceso total.
- Un permiso de dominio completo (``equipment is None``) cubre cualquier
  equipo de ese dominio.
- Un permiso limitado a un equipo **solo** habilita ese equipo: no cubre el
  dominio completo ni otro equipo.
- La decisión se toma **antes** de recuperar conocimiento. El LLM nunca
  participa en ella.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

# Mismo formato que las restricciones `ck_domain_code_normalized` y
# `ck_equipment_normalized` de la migración: el valor normalizado es
# idéntico en el código y en la base.
_SCOPE_VALUE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class InvalidScopeError(ValueError):
    """El valor de dominio o equipo no tiene un formato aceptable."""


def normalize_scope_value(value: str) -> str:
    """Normaliza un dominio o equipo a su forma canónica.

    Los alcances son **dato**, no constantes de código: ``Tampella``,
    ``tampella`` y `` TAMPELLA `` designan el mismo equipo y se almacenan
    y comparan como ``tampella``.
    """
    normalized = value.strip().lower()
    if not _SCOPE_VALUE_PATTERN.fullmatch(normalized):
        raise InvalidScopeError(
            "scope values must be 1-64 characters of a-z, 0-9, '_' or '-', "
            "starting with a letter or digit"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class Scope:
    """Alcance de conocimiento: dominio y, opcionalmente, equipo.

    Es el primer tramo de la jerarquía prevista
    (dominio → planta → área → equipo → tipo de información). Los niveles
    restantes se añadirán como campos adicionales sin cambiar el
    significado de los existentes.
    """

    domain: str
    equipment: str | None = None

    @classmethod
    def parse(cls, domain: str, equipment: str | None = None) -> "Scope":
        """Construye un alcance normalizando sus valores."""
        return cls(
            domain=normalize_scope_value(domain),
            equipment=None if equipment is None else normalize_scope_value(equipment),
        )


@dataclass(frozen=True, slots=True)
class Principal:
    """Identidad ya resuelta y lista para autorizar.

    Se construye solo tras verificar el token y comprobar el perfil en
    Materiales; ``is_active`` refleja el estado de la cuenta **en ELSA**.
    """

    external_user_id: str
    display_name: str | None
    is_active: bool
    is_admin: bool
    scopes: tuple[Scope, ...] = ()
    session_id: str | None = None


class DenialReason(StrEnum):
    """Motivo por el que se negó el acceso (para logs y auditoría)."""

    ACCOUNT_INACTIVE = "account_inactive"
    NO_MATCHING_GRANT = "no_matching_grant"


@dataclass(frozen=True, slots=True)
class AccessDecision:
    """Resultado de evaluar un alcance para una identidad."""

    allowed: bool
    reason: DenialReason | None = None
    matched_scope: Scope | None = None
    via_admin: bool = False


def covers(granted: Scope, required: Scope) -> bool:
    """Indica si un permiso otorgado cubre el alcance requerido."""
    if granted.domain != required.domain:
        return False
    if granted.equipment is None:
        # Permiso de dominio completo: cubre el dominio y cualquier equipo.
        return True
    # Permiso limitado a un equipo: solo cubre exactamente ese equipo.
    return granted.equipment == required.equipment


def authorize(principal: Principal, required: Scope) -> AccessDecision:
    """Decide si ``principal`` puede acceder a ``required``.

    Niega por defecto: solo devuelve ``allowed=True`` si el usuario está
    activo y es administrador o tiene un permiso que cubre el alcance.
    """
    if not principal.is_active:
        return AccessDecision(allowed=False, reason=DenialReason.ACCOUNT_INACTIVE)

    if principal.is_admin:
        return AccessDecision(allowed=True, matched_scope=required, via_admin=True)

    for granted in principal.scopes:
        if covers(granted, required):
            return AccessDecision(allowed=True, matched_scope=granted)

    return AccessDecision(allowed=False, reason=DenialReason.NO_MATCHING_GRANT)
