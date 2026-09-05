"""Caché de claves públicas (JWKS) del proveedor de identidad.

Verificación asimétrica local: ELSA descarga el conjunto de claves públicas
del proyecto de Materiales y comprueba la firma sin llamar a nadie por cada
petición. Ninguna clave privada interviene aquí.

Rotación de claves: si llega un token firmado con un ``kid`` que no está en
la caché, se vuelve a descargar el JWKS. Ese refresco tiene un tiempo mínimo
de espera configurable para que un token forjado con un ``kid`` inventado no
pueda provocar una descarga por petición.
"""

import asyncio
import logging
import time
from collections.abc import Callable

import httpx
from jwt import PyJWK, PyJWKSet
from jwt.exceptions import PyJWKSetError

from elsa.ports.auth import IdentityProviderUnavailableError, InvalidTokenError

_logger = logging.getLogger("elsa.auth.jwks")


class JwksCache:
    """Conjunto de claves públicas con caché, refresco y rotación."""

    def __init__(
        self,
        url: str,
        *,
        http_client: httpx.AsyncClient,
        cache_seconds: int,
        min_refresh_seconds: int,
        timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._http = http_client
        self._cache_seconds = cache_seconds
        self._min_refresh_seconds = min_refresh_seconds
        self._timeout = timeout_seconds
        self._clock = clock
        self._lock = asyncio.Lock()
        self._keyset: PyJWKSet | None = None
        self._fetched_at: float | None = None
        self._last_attempt_at: float | None = None

    async def get_key(self, kid: str | None) -> PyJWK:
        """Devuelve la clave pública con ese ``kid``.

        Lanza :class:`InvalidTokenError` si el ``kid`` no existe ni siquiera
        tras refrescar, y :class:`IdentityProviderUnavailableError` si no hay
        ninguna clave utilizable porque el proveedor no responde.
        """
        if kid is None:
            raise InvalidTokenError("token does not identify a signing key")

        async with self._lock:
            cached = self._find(kid)
            if cached is not None and self._is_fresh():
                return cached

            if self._may_fetch():
                try:
                    await self._fetch()
                except IdentityProviderUnavailableError:
                    # Con una clave usable en caché seguimos sirviendo: la
                    # indisponibilidad del JWKS no debe invalidar tokens
                    # legítimos ya verificables.
                    if cached is not None:
                        return cached
                    raise

            key = self._find(kid)
            if key is not None:
                return key
            if self._keyset is None:
                raise IdentityProviderUnavailableError("no signing keys available")
            raise InvalidTokenError("token signed with an unknown key")

    async def check_health(self) -> None:
        """Comprueba que el JWKS es alcanzable (o está en caché vigente)."""
        async with self._lock:
            if self._keyset is not None and self._is_fresh():
                return
            await self._fetch()

    def _is_fresh(self) -> bool:
        if self._fetched_at is None:
            return False
        return (self._clock() - self._fetched_at) < self._cache_seconds

    def _may_fetch(self) -> bool:
        if self._last_attempt_at is None:
            return True
        return (self._clock() - self._last_attempt_at) >= self._min_refresh_seconds

    def _find(self, kid: str) -> PyJWK | None:
        if self._keyset is None:
            return None
        for key in self._keyset.keys:
            if key.key_id == kid:
                return key
        return None

    async def _fetch(self) -> None:
        self._last_attempt_at = self._clock()
        try:
            response = await self._http.get(self._url, timeout=self._timeout)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            # El detalle técnico va al log del servidor, nunca al cliente.
            _logger.warning(
                "jwks fetch failed",
                extra={"error": type(exc).__name__},
            )
            raise IdentityProviderUnavailableError("could not fetch the signing keys") from None

        try:
            keyset = PyJWKSet.from_dict(payload)
        except (PyJWKSetError, AttributeError, TypeError) as exc:
            _logger.warning("jwks payload is not usable", extra={"error": type(exc).__name__})
            raise IdentityProviderUnavailableError("the signing key set is not usable") from None

        self._keyset = keyset
        self._fetched_at = self._clock()
        _logger.info("jwks refreshed", extra={"key_count": len(keyset.keys)})
