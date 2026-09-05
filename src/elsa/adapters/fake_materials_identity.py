"""Adaptador fake del puerto ``materials_identity`` (determinista, para tests).

Sustituye la consulta al PostgREST de Materiales por un mapa en memoria.
Permite simular las tres situaciones que el backend debe distinguir: perfil
activo, perfil inactivo y fuente de identidad caída.
"""

from collections.abc import Mapping

from elsa.ports.auth import IdentityProviderUnavailableError
from elsa.ports.materials_identity import MaterialsProfile


class FakeMaterialsIdentityAdapter:
    """Devuelve perfiles desde un mapa fijo, sin red."""

    def __init__(
        self,
        profiles: Mapping[str, MaterialsProfile] | None = None,
        *,
        unavailable: bool = False,
    ) -> None:
        self._profiles = dict(profiles or {})
        self.unavailable = unavailable
        """Si es verdadero, cada consulta simula una caída de Materiales."""

    def set_profile(self, profile: MaterialsProfile) -> None:
        self._profiles[profile.user_id] = profile

    async def get_own_profile(self, user_id: str, *, access_token: str) -> MaterialsProfile | None:
        if self.unavailable:
            raise IdentityProviderUnavailableError("materials is unavailable (fake)")
        return self._profiles.get(user_id)
