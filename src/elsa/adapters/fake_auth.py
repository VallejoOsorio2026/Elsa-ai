"""Adaptador fake del puerto de autenticación (determinista, para tests)."""

from collections.abc import Mapping

from elsa.ports.auth import AuthenticatedUser, InvalidTokenError

_DEFAULT_USERS: dict[str, AuthenticatedUser] = {
    "fake-token-engineer": AuthenticatedUser(
        id="fake-user-0001",
        email="engineer@example.test",
        claims={"role": "engineer"},
    ),
    "fake-token-admin": AuthenticatedUser(
        id="fake-user-0002",
        email="admin@example.test",
        claims={"role": "admin"},
    ),
}


class FakeAuthAdapter:
    """Verifica tokens contra un mapa fijo en memoria.

    Mismo token de entrada, misma identidad de salida; cualquier token fuera
    del mapa lanza :class:`InvalidTokenError`.
    """

    def __init__(self, users: Mapping[str, AuthenticatedUser] | None = None) -> None:
        self._users = dict(_DEFAULT_USERS if users is None else users)

    async def verify_token(self, token: str) -> AuthenticatedUser:
        try:
            return self._users[token]
        except KeyError:
            raise InvalidTokenError("token is not valid") from None
