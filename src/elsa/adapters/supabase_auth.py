"""Adaptador real del puerto ``auth``: JWT emitido por Supabase (Materiales).

Verifica criptográficamente el token, comprueba expiración, emisor y
audiencia, y rechaza cualquier algoritmo fuera de la lista configurada
(``none`` incluido, que ni siquiera es configurable).

Política de logs: ni el token ni la cabecera ``Authorization`` se registran
nunca, ni completos ni parciales. Los mensajes de error hacia el cliente son
genéricos; el motivo concreto queda en el log del servidor como nombre de
excepción, sin contenido del token.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import jwt
from jwt.exceptions import PyJWTError

from elsa.adapters.jwks import JwksCache
from elsa.ports.auth import (
    AuthenticatedUser,
    IdentityProviderUnavailableError,
    InvalidTokenError,
)

_logger = logging.getLogger("elsa.auth.supabase")

_SYMMETRIC_PREFIX = "HS"

# Claims exigidos en todo token. `sub` es la identidad; sin `exp` el token
# no caducaría nunca.
_REQUIRED_CLAIMS = ["exp", "sub", "iss"]


class SupabaseJwtAuthAdapter:
    """Verificador de los JWT emitidos por el Supabase de Materiales."""

    def __init__(
        self,
        *,
        algorithms: list[str],
        issuer: str | None,
        audience: str | None,
        leeway_seconds: int,
        jwks: JwksCache | None = None,
        symmetric_secret: str | None = None,
    ) -> None:
        self._algorithms = {algorithm.upper() for algorithm in algorithms}
        self._issuer = issuer
        self._audience = audience
        self._leeway = leeway_seconds
        self._jwks = jwks
        self._symmetric_secret = symmetric_secret

    async def verify_token(self, token: str) -> AuthenticatedUser:
        algorithm, key_id = self._read_header(token)
        key = await self._signing_key(algorithm, key_id)

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={
                    "require": list(_REQUIRED_CLAIMS),
                    "verify_aud": self._audience is not None,
                },
            )
        except PyJWTError as exc:
            _logger.info("token rejected", extra={"error": type(exc).__name__})
            raise InvalidTokenError("the token is not valid") from None

        return self._identity_from(claims)

    async def check_health(self) -> None:
        """Comprueba la disponibilidad del material de verificación."""
        if self._jwks is not None:
            await self._jwks.check_health()

    # -----------------------------------------------------------------
    # Interno
    # -----------------------------------------------------------------

    def _read_header(self, token: str) -> tuple[str, str | None]:
        try:
            header = jwt.get_unverified_header(token)
        except PyJWTError:
            raise InvalidTokenError("the token is not valid") from None

        algorithm = header.get("alg")
        if not isinstance(algorithm, str) or algorithm.upper() not in self._algorithms:
            # Cubre `none` y cualquier algoritmo no declarado en la
            # configuración, antes de tocar ninguna clave.
            _logger.info("token rejected", extra={"error": "UnexpectedAlgorithm"})
            raise InvalidTokenError("the token is not valid")

        key_id = header.get("kid")
        return algorithm.upper(), key_id if isinstance(key_id, str) else None

    async def _signing_key(self, algorithm: str, key_id: str | None) -> Any:
        if algorithm.startswith(_SYMMETRIC_PREFIX):
            if self._symmetric_secret is None:
                raise IdentityProviderUnavailableError("symmetric verification is not configured")
            return self._symmetric_secret
        if self._jwks is None:
            raise IdentityProviderUnavailableError("asymmetric verification is not configured")
        return (await self._jwks.get_key(key_id)).key

    def _identity_from(self, claims: dict[str, Any]) -> AuthenticatedUser:
        subject = claims.get("sub")
        if not isinstance(subject, str):
            raise InvalidTokenError("the token is not valid")
        try:
            # Las cuentas de ELSA referencian el UUID de `auth.users` de
            # Materiales; un `sub` que no lo sea no puede ser esa identidad.
            user_id = str(uuid.UUID(subject))
        except ValueError:
            _logger.info("token rejected", extra={"error": "SubjectIsNotAUuid"})
            raise InvalidTokenError("the token is not valid") from None

        email = claims.get("email")
        session = claims.get("session_id")
        expires_at = claims.get("exp")

        return AuthenticatedUser(
            id=user_id,
            email=email if isinstance(email, str) else None,
            session_id=session if isinstance(session, str) else None,
            expires_at=(
                datetime.fromtimestamp(expires_at, tz=UTC)
                if isinstance(expires_at, int | float)
                else None
            ),
        )
