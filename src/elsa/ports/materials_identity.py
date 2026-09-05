"""Puerto de perfil de identidad en Materiales.

Materiales es la **fuente autoritativa de identidad**: un token válido no
basta, el perfil del usuario debe seguir existiendo y estar activo allí
(columna ``activo`` de la tabla ``perfiles``). Este puerto expone
exclusivamente esa comprobación; el inventario de materiales sigue viviendo
detrás de :mod:`elsa.ports.materials`.

El adaptador real consulta el perfil **propio** del usuario usando su propio
JWT (la política RLS ``perfil_propio_lectura`` de Materiales lo permite), de
modo que ELSA nunca necesita una credencial de servicio de aquel proyecto.
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class MaterialsProfile:
    """Perfil mínimo del usuario en Materiales.

    Deliberadamente no incluye el rol de Materiales: los permisos de ELSA
    no dependen de los roles de aquel sistema (Bloque 1, autorización).
    """

    user_id: str
    display_name: str | None
    is_active: bool


@runtime_checkable
class MaterialsIdentityPort(Protocol):
    """Consulta del perfil propio en la fuente autoritativa de identidad."""

    async def get_own_profile(self, user_id: str, *, access_token: str) -> MaterialsProfile | None:
        """Devuelve el perfil del usuario, o ``None`` si no tiene perfil.

        Lanza :class:`elsa.ports.auth.InvalidTokenError` si la fuente
        rechaza el token, y
        :class:`elsa.ports.auth.IdentityProviderUnavailableError` si no
        respondió por un fallo técnico.
        """
        ...
