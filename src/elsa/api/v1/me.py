"""``GET /api/v1/me``: quién soy y qué puedo consultar.

Devuelve exclusivamente información segura: identificador externo, nombre,
estado, si es administrador y los alcances autorizados. **Nunca** devuelve
tokens, secretos, claves ni datos del proveedor de identidad más allá del
nombre visible.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from elsa.api.deps import current_principal
from elsa.core.authorization import Principal

router = APIRouter(tags=["identity"])


class ScopeView(BaseModel):
    """Alcance autorizado. ``equipment`` vacío significa el dominio completo."""

    domain: str
    equipment: str | None = None


class MeResponse(BaseModel):
    """Vista segura de la identidad y la autorización efectivas."""

    external_user_id: str
    display_name: str | None
    is_active: bool
    is_admin: bool
    scopes: list[ScopeView]


@router.get("/me", response_model=MeResponse)
async def me(principal: Principal = Depends(current_principal)) -> MeResponse:
    return MeResponse(
        external_user_id=principal.external_user_id,
        display_name=principal.display_name,
        is_active=principal.is_active,
        is_admin=principal.is_admin,
        scopes=[
            ScopeView(domain=scope.domain, equipment=scope.equipment) for scope in principal.scopes
        ],
    )
