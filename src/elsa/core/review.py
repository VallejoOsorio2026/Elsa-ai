"""Reglas de la revisión técnica.

El **Revisor Técnico** es una capacidad separada de la de administrador.
Quien revisa conocimiento técnico responde por su exactitud; quien
administra responde por la seguridad y por quién entra al sistema. Son
responsabilidades distintas y se otorgan por separado: un revisor no
gestiona usuarios, no se concede permisos, no cambia la configuración global
y no revisa fuera de su alcance.

El administrador conserva capacidad global de intervención, porque alguien
tiene que poder desbloquear una situación en la que el revisor asignado ya
no está disponible.

Reglas de las decisiones, que este módulo hace cumplir antes de tocar nada:

- **Aprobar** admite comentario opcional.
- **Rechazar** exige motivo. Cerrar el trabajo de otra persona sin decir por
  qué convierte el rechazo en algo inapelable.
- **Revertir** exige motivo, por la misma razón, y además señala qué
  validación deshace.
- Una validación puede revertirla el mismo revisor (si sigue habilitado y
  conserva alcance), otro revisor con alcance equivalente, o un
  administrador.
- **Ninguna validación se borra.** Revertir crea un registro nuevo; el
  anterior permanece.

Una misma persona puede cargar y validar información si tiene ambas
capacidades: la separación que exige este bloque es entre revisar y
administrar, no entre cargar y revisar.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from elsa.core.authorization import Principal, Scope, covers

__all__ = [
    "ReviewDecision",
    "ReviewSubject",
    "ReviewerCapability",
    "can_review",
    "validate_decision",
]


class ReviewDecision(StrEnum):
    """Coincide con ``ck_review_decision`` de la migración."""

    APPROVED = "approved"
    REJECTED = "rejected"
    REVERTED = "reverted"


class ReviewSubject(StrEnum):
    """Qué se está validando. Coincide con ``ck_review_subject_kind``."""

    ENGINEERING_BOM_VERSION = "engineering_bom_version"
    BOM_ITEM = "bom_item"
    FAILURE_MODE = "failure_mode"
    DRAWING_IMAGE = "drawing_image"
    RECONCILIATION_ITEM = "reconciliation_item"


class MissingReasonError(ValueError):
    """Se intentó rechazar o revertir sin motivo."""


@dataclass(frozen=True, slots=True)
class ReviewerCapability:
    """Lo que una persona puede revisar en este momento.

    Se construye en cada petición a partir de las capacidades **vigentes**.
    Deshabilitar a un revisor surte efecto en la petición siguiente, sin
    tocar nada de lo que ya firmó.
    """

    external_user_id: str
    is_admin: bool = False
    scopes: tuple[Scope, ...] = ()

    @property
    def is_reviewer(self) -> bool:
        """Un administrador puede intervenir aunque no tenga capacidad propia."""
        return self.is_admin or bool(self.scopes)


def build_capability(principal: Principal, reviewer_scopes: Sequence[Scope]) -> ReviewerCapability:
    """Combina la identidad autorizada con sus capacidades de revisor."""
    return ReviewerCapability(
        external_user_id=principal.external_user_id,
        is_admin=principal.is_admin,
        scopes=tuple(reviewer_scopes),
    )


def can_review(capability: ReviewerCapability, required: Scope) -> bool:
    """Indica si esa persona puede revisar en ese alcance.

    Niega por defecto, igual que la autorización de lectura: una capacidad de
    revisor sobre un equipo **no** habilita otro equipo, ni el dominio
    completo.
    """
    if capability.is_admin:
        return True
    return any(covers(granted, required) for granted in capability.scopes)


def validate_decision(decision: ReviewDecision, comment: str | None) -> str | None:
    """Comprueba el motivo y devuelve el comentario normalizado.

    Lanza :class:`MissingReasonError` si falta un motivo obligatorio. La
    misma regla vive además como restricción en la base
    (``ck_review_reason_required``): la capa HTTP puede equivocarse, la base
    no.
    """
    normalized = None if comment is None else comment.strip() or None
    if decision in (ReviewDecision.REJECTED, ReviewDecision.REVERTED) and normalized is None:
        raise MissingReasonError(
            f"a reason is required to {decision.value.rstrip('ed')} a validation"
        )
    return normalized
