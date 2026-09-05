"""Contrato del puerto de autenticación, verificado con el adaptador fake."""

import pytest

from elsa.adapters.fake_auth import ENGINEER_ID, FakeAuthAdapter
from elsa.ports.auth import (
    AuthenticatedUser,
    AuthPort,
    IdentityProviderUnavailableError,
    InvalidTokenError,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def port() -> AuthPort:
    return FakeAuthAdapter()


def test_fake_adapter_satisfies_the_port(port: AuthPort) -> None:
    assert isinstance(port, AuthPort)


async def test_valid_token_yields_identity(port: AuthPort) -> None:
    user = await port.verify_token("fake-token-engineer")

    assert isinstance(user, AuthenticatedUser)
    assert user.id == ENGINEER_ID
    assert user.claims["role"] == "engineer"


async def test_verification_is_deterministic(port: AuthPort) -> None:
    first = await port.verify_token("fake-token-admin")
    second = await port.verify_token("fake-token-admin")

    assert first == second


async def test_unknown_token_raises_invalid_token(port: AuthPort) -> None:
    with pytest.raises(InvalidTokenError):
        await port.verify_token("forged-token")


async def test_provider_failure_is_not_an_invalid_token() -> None:
    """Un fallo técnico nunca se confunde con credenciales inválidas."""
    port: AuthPort = FakeAuthAdapter(unavailable=True)

    with pytest.raises(IdentityProviderUnavailableError):
        await port.verify_token("fake-token-engineer")
