"""Puerto de autenticación.

La identidad proviene del Supabase del Asistente de Materiales (ADR 0002):
el backend recibe un JWT, lo verifica a través de este puerto y aplica los
permisos propios de ELSA. El verificador real (JWKS o secreto simétrico)
vive detrás de este puerto para que cambiarlo afecte a un solo archivo.

Distinción obligatoria (CLAUDE.md y semántica de errores del Bloque 1):

- :class:`InvalidTokenError` es un problema de **credenciales** → 401.
- :class:`IdentityProviderUnavailableError` es un fallo **técnico** del
  proveedor de identidad → 503. Nunca se convierte en "usuario inválido".
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Identidad verificada extraída de un token válido.

    Contiene lo mínimo necesario para autorizar. Nunca guarda el token.
    """

    id: str
    """UUID del usuario en el Supabase Auth de Materiales (claim ``sub``)."""

    email: str | None = None

    claims: dict[str, str] = field(default_factory=dict)
    """Claims adicionales de interés, ya normalizados a texto."""

    session_id: str | None = None
    """Identificador de sesión del proveedor, si el token lo trae."""

    expires_at: datetime | None = None
    """Expiración del token (claim ``exp``), en UTC."""


class InvalidTokenError(Exception):
    """El token es inválido, está expirado o no es verificable → 401."""


class IdentityProviderUnavailableError(Exception):
    """El proveedor de identidad no responde o falla → 503.

    No es un problema de credenciales: convertirlo en 401 mentiría al
    cliente y ocultaría una incidencia de operación.
    """


@runtime_checkable
class AuthPort(Protocol):
    """Verificación de identidad. No decide permisos: eso es del backend."""

    async def verify_token(self, token: str) -> AuthenticatedUser:
        """Verifica un JWT y devuelve la identidad.

        Lanza :class:`InvalidTokenError` si el token no es válido y
        :class:`IdentityProviderUnavailableError` si no se pudo comprobar
        por un fallo técnico.
        """
        ...
