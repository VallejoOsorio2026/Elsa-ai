"""Sondas de autorización.

Endpoints protegidos que demuestran la cadena completa sin recuperar nada:
uno exige permiso sobre un **dominio** y otro sobre **dominio + equipo**.

No son endpoints de RAG ni de conocimiento: existen para poder verificar de
forma observable que la autorización ocurre **antes** de cualquier
recuperación, y desaparecerán cuando los endpoints reales los sustituyan.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from elsa.api.deps import RequireScope
from elsa.core.authorization import Principal

router = APIRouter(prefix="/access", tags=["access"])


class AccessGranted(BaseModel):
    """Confirmación de que el alcance solicitado está autorizado."""

    granted: bool
    domain: str
    equipment: str | None = None
    external_user_id: str
    via_admin: bool


@router.get("/{domain}", response_model=AccessGranted)
async def access_domain(
    domain: str,
    principal: Principal = Depends(RequireScope()),
) -> AccessGranted:
    """Requiere permiso sobre el dominio completo."""
    return AccessGranted(
        granted=True,
        domain=domain.strip().lower(),
        external_user_id=principal.external_user_id,
        via_admin=principal.is_admin,
    )


@router.get("/{domain}/{equipment}", response_model=AccessGranted)
async def access_domain_equipment(
    domain: str,
    equipment: str,
    principal: Principal = Depends(RequireScope(equipment_param="equipment")),
) -> AccessGranted:
    """Requiere permiso sobre ese equipo dentro del dominio."""
    return AccessGranted(
        granted=True,
        domain=domain.strip().lower(),
        equipment=equipment.strip().lower(),
        external_user_id=principal.external_user_id,
        via_admin=principal.is_admin,
    )
