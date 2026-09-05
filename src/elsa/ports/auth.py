"""Puerto de autenticación.

La identidad proviene del Supabase del Asistente de Materiales (ADR 0002):
el backend recibe un JWT, lo verifica a través de este puerto y aplica los
permisos propios de ELSA. El verificador real (JWKS o secreto simétrico)
vivirá detrás de este puerto para que cambiarlo afecte a un solo archivo.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Identidad verificada extraída de un token válido."""

    id: str
    email: str | None = None
    claims: dict[str, str] = field(default_factory=dict)


class InvalidTokenError(Exception):
    """El token es inválido, está expirado o no es verificable."""


@runtime_checkable
class AuthPort(Protocol):
    """Verificación de identidad. No decide permisos: eso es del backend."""

    async def verify_token(self, token: str) -> AuthenticatedUser:
        """Verifica un JWT y devuelve la identidad.

        Lanza :class:`InvalidTokenError` si el token no es válido.
        """
        ...
