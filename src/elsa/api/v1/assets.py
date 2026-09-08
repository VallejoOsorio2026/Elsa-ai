"""Qué equipos puede consultar quien pregunta.

Existe para que la interfaz **no tenga que suponer** sobre qué activo está
trabajando. Hasta ahora el frontend daba por hecho el equipo del piloto; eso
sirve en una demostración y es falso en cuanto haya un segundo equipo, una
segunda planta o un usuario con otro alcance.

La lista sale del cruce entre los activos existentes y los permisos de la
persona. El catálogo de activos no es conocimiento técnico —es la lista de
qué equipos hay—, así que enumerarlo y después filtrar no rompe la regla de
autorizar antes de recuperar: lo que nunca se devuelve, ni se llega a leer,
es el contenido de un activo no autorizado.
"""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from elsa.api.deps import current_principal, get_knowledge
from elsa.api.errors import ApiError
from elsa.core.authorization import Principal, Scope, authorize
from elsa.ports.knowledge import KnowledgeRepositoryPort, KnowledgeUnavailableError

router = APIRouter(prefix="/assets", tags=["assets"])


class AssetView(BaseModel):
    """Un equipo sobre el que esta persona tiene alcance."""

    code: str
    name: str
    domain: str


@router.get("", response_model=list[AssetView])
async def list_authorized_assets(
    principal: Principal = Depends(current_principal),
    knowledge: KnowledgeRepositoryPort = Depends(get_knowledge),
) -> list[AssetView]:
    """Equipos que esta persona puede consultar, ordenados por nombre.

    Una lista vacía es una respuesta legítima: significa que la cuenta está
    activa pero todavía no tiene ningún alcance concedido.
    """
    try:
        assets = await knowledge.list_assets()
    except KnowledgeUnavailableError:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The knowledge store is temporarily unavailable.",
            code="knowledge_store_unavailable",
        ) from None

    allowed = [
        AssetView(code=asset.code, name=asset.name, domain=asset.domain)
        for asset in assets
        if asset.is_active
        and authorize(principal, Scope(domain=asset.domain, equipment=asset.code)).allowed
    ]
    return sorted(allowed, key=lambda asset: (asset.domain, asset.name))
