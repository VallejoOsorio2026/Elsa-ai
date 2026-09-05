"""Adaptador real del puerto ``materials_identity``.

Consulta el perfil **propio** del usuario en el PostgREST de Materiales
usando su propio JWT. La política RLS ``perfil_propio_lectura`` de aquel
proyecto autoriza exactamente esa lectura (``id = auth.uid()``), de modo que
ELSA no necesita —ni debe tener— una credencial de servicio de Materiales.

La cabecera ``apikey`` lleva la clave publicable de Materiales, que es
pública por diseño: sin una sesión válida no devuelve ninguna fila.

El token del usuario viaja en la cabecera ``Authorization`` de esta llamada y
en ningún otro sitio: no se registra, no se guarda y no se devuelve.
"""

import logging

import httpx

from elsa.ports.auth import IdentityProviderUnavailableError, InvalidTokenError
from elsa.ports.materials_identity import MaterialsProfile

_logger = logging.getLogger("elsa.identity.materials")

# Solo lo necesario para autorizar. El rol de Materiales no se lee: los
# permisos de ELSA no dependen de él.
_SELECTED_COLUMNS = "id,nombre,activo"


class SupabaseMaterialsIdentityAdapter:
    """Lectura del perfil propio en el Supabase de Materiales."""

    def __init__(
        self,
        *,
        profiles_url: str,
        api_key: str,
        http_client: httpx.AsyncClient,
        timeout_seconds: float,
    ) -> None:
        self._url = profiles_url
        self._api_key = api_key
        self._http = http_client
        self._timeout = timeout_seconds

    async def get_own_profile(self, user_id: str, *, access_token: str) -> MaterialsProfile | None:
        try:
            response = await self._http.get(
                self._url,
                params={
                    "id": f"eq.{user_id}",
                    "select": _SELECTED_COLUMNS,
                    "limit": "1",
                },
                headers={
                    "apikey": self._api_key,
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            _logger.warning("materials profile lookup failed", extra={"error": type(exc).__name__})
            raise IdentityProviderUnavailableError("could not reach the identity source") from None

        if response.status_code == httpx.codes.UNAUTHORIZED:
            # La fuente autoritativa rechaza el token: es un problema de
            # credenciales, no una incidencia técnica.
            raise InvalidTokenError("the token was rejected by the identity source")

        if response.status_code == httpx.codes.FORBIDDEN:
            # RLS no autoriza la lectura: para ELSA equivale a no tener perfil.
            return None

        if response.status_code != httpx.codes.OK:
            _logger.warning(
                "materials profile lookup returned an unexpected status",
                extra={"status_code": response.status_code},
            )
            raise IdentityProviderUnavailableError("the identity source returned an error")

        try:
            rows = response.json()
        except ValueError:
            raise IdentityProviderUnavailableError("the identity source returned no JSON") from None

        if not isinstance(rows, list) or not rows:
            return None

        row = rows[0]
        if not isinstance(row, dict):
            raise IdentityProviderUnavailableError("the identity source returned an unexpected row")

        name = row.get("nombre")
        return MaterialsProfile(
            user_id=user_id,
            display_name=name if isinstance(name, str) else None,
            is_active=row.get("activo") is True,
        )
