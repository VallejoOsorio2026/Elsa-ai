"""Adaptador fake del puerto de autenticación (determinista, para tests).

Los identificadores son UUID reales porque el modelo de ELSA referencia el
``auth.users.id`` de Materiales: un fake con identificadores de otra forma
escondería errores que el adaptador real sí produciría.

Solo se permite en DEV (ver ``elsa.config``): en cualquier otro ambiente la
aplicación se niega a arrancar con este adaptador.
"""

from collections.abc import Mapping

from elsa.ports.auth import (
    AuthenticatedUser,
    IdentityProviderUnavailableError,
    InvalidTokenError,
)

ENGINEER_ID = "00000000-0000-4000-8000-000000000001"
ADMIN_ID = "00000000-0000-4000-8000-000000000002"
# Dos revisores técnicos: hacen falta dos para poder comprobar que una
# validación puede revertirla otra persona con alcance equivalente.
REVIEWER_ID = "00000000-0000-4000-8000-000000000003"
OTHER_REVIEWER_ID = "00000000-0000-4000-8000-000000000004"

_DEFAULT_USERS: dict[str, AuthenticatedUser] = {
    "fake-token-engineer": AuthenticatedUser(
        id=ENGINEER_ID,
        email="engineer@example.test",
        claims={"role": "engineer"},
        session_id="00000000-0000-4000-8000-0000000000a1",
    ),
    "fake-token-admin": AuthenticatedUser(
        id=ADMIN_ID,
        email="admin@example.test",
        claims={"role": "admin"},
        session_id="00000000-0000-4000-8000-0000000000a2",
    ),
    "fake-token-reviewer": AuthenticatedUser(
        id=REVIEWER_ID,
        email="reviewer@example.test",
        claims={"role": "reviewer"},
        session_id="00000000-0000-4000-8000-0000000000a3",
    ),
    "fake-token-other-reviewer": AuthenticatedUser(
        id=OTHER_REVIEWER_ID,
        email="other.reviewer@example.test",
        claims={"role": "reviewer"},
        session_id="00000000-0000-4000-8000-0000000000a4",
    ),
}


class FakeAuthAdapter:
    """Verifica tokens contra un mapa fijo en memoria.

    Mismo token de entrada, misma identidad de salida; cualquier token fuera
    del mapa lanza :class:`InvalidTokenError`. Con ``unavailable`` activo
    simula una caída del proveedor de identidad, que el backend debe
    distinguir de unas credenciales inválidas.
    """

    def __init__(
        self,
        users: Mapping[str, AuthenticatedUser] | None = None,
        *,
        unavailable: bool = False,
    ) -> None:
        self._users = dict(_DEFAULT_USERS if users is None else users)
        self.unavailable = unavailable

    async def verify_token(self, token: str) -> AuthenticatedUser:
        if self.unavailable:
            raise IdentityProviderUnavailableError("identity provider is unavailable (fake)")
        try:
            return self._users[token]
        except KeyError:
            raise InvalidTokenError("token is not valid") from None
