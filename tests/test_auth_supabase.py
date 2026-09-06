"""Verificación real del JWT emitido por Supabase (Materiales).

Cubre lo que el adaptador debe rechazar y lo que debe aceptar, incluida la
rotación de claves y la distinción entre "token inválido" y "proveedor de
identidad caído".

Las claves se generan en el propio test: no hay ninguna clave, secreto ni
token real en el repositorio.
"""

import base64
import json
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import jwt
import pytest

from elsa.adapters.jwks import JwksCache
from elsa.adapters.supabase_auth import SupabaseJwtAuthAdapter
from elsa.ports.auth import IdentityProviderUnavailableError, InvalidTokenError
from tests.keys import KeyPair

pytestmark = pytest.mark.anyio

ISSUER = "https://materials.example.test/auth/v1"
AUDIENCE = "authenticated"
JWKS_URL = "https://materials.example.test/auth/v1/.well-known/jwks.json"
SUBJECT = "11111111-1111-4111-8111-111111111111"


def make_claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    claims: dict[str, Any] = {
        "sub": SUBJECT,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 3600,
        "email": "ingeniero@example.test",
        "session_id": "22222222-2222-4222-8222-222222222222",
        "role": "authenticated",
    }
    claims.update(overrides)
    return {key: value for key, value in claims.items() if value is not None}


class JwksServer:
    """Servidor JWKS de prueba: cuenta peticiones y puede caerse."""

    def __init__(self, keys: list[KeyPair]) -> None:
        self.keys = list(keys)
        self.requests = 0
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        if self.down:
            raise httpx.ConnectError("jwks is unreachable", request=request)
        return httpx.Response(200, json={"keys": [key.jwk for key in self.keys]})


def build_adapter(
    server: JwksServer,
    *,
    algorithms: list[str] | None = None,
    audience: str | None = AUDIENCE,
    cache_seconds: int = 600,
    min_refresh_seconds: int = 60,
    clock: Callable[[], float] | None = None,
) -> SupabaseJwtAuthAdapter:
    http = httpx.AsyncClient(transport=httpx.MockTransport(server.handler))
    jwks = JwksCache(
        JWKS_URL,
        http_client=http,
        cache_seconds=cache_seconds,
        min_refresh_seconds=min_refresh_seconds,
        timeout_seconds=2.0,
        **({"clock": clock} if clock is not None else {}),
    )
    return SupabaseJwtAuthAdapter(
        algorithms=algorithms or ["RS256", "ES256"],
        issuer=ISSUER,
        audience=audience,
        leeway_seconds=0,
        jwks=jwks,
    )


@pytest.fixture
def signing_key() -> KeyPair:
    return KeyPair("key-1")


@pytest.fixture
def server(signing_key: KeyPair) -> JwksServer:
    return JwksServer([signing_key])


# ---------------------------------------------------------------------
# Aceptación
# ---------------------------------------------------------------------


async def test_valid_token_yields_the_expected_identity(
    signing_key: KeyPair, server: JwksServer
) -> None:
    adapter = build_adapter(server)

    identity = await adapter.verify_token(signing_key.sign(make_claims()))

    assert identity.id == SUBJECT
    assert identity.email == "ingeniero@example.test"
    assert identity.session_id == "22222222-2222-4222-8222-222222222222"
    assert identity.expires_at is not None


async def test_elliptic_curve_signature_is_accepted() -> None:
    key = KeyPair("key-ec", algorithm="ES256")
    adapter = build_adapter(JwksServer([key]))

    identity = await adapter.verify_token(key.sign(make_claims()))

    assert identity.id == SUBJECT


async def test_symmetric_secret_is_accepted_when_configured() -> None:
    adapter = SupabaseJwtAuthAdapter(
        algorithms=["HS256"],
        issuer=ISSUER,
        audience=AUDIENCE,
        leeway_seconds=0,
        symmetric_secret="a-secret-that-only-lives-in-the-environment",
    )
    token = jwt.encode(
        make_claims(), "a-secret-that-only-lives-in-the-environment", algorithm="HS256"
    )

    identity = await adapter.verify_token(token)

    assert identity.id == SUBJECT


async def test_audience_check_can_be_disabled(signing_key: KeyPair, server: JwksServer) -> None:
    adapter = build_adapter(server, audience=None)

    identity = await adapter.verify_token(signing_key.sign(make_claims(aud=None)))

    assert identity.id == SUBJECT


# ---------------------------------------------------------------------
# Rechazo (401)
# ---------------------------------------------------------------------


async def test_expired_token_is_rejected(signing_key: KeyPair, server: JwksServer) -> None:
    adapter = build_adapter(server)
    expired = make_claims(exp=int(time.time()) - 60, iat=int(time.time()) - 3600)

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token(signing_key.sign(expired))


async def test_wrong_signature_is_rejected(server: JwksServer) -> None:
    # Otra clave privada publicada bajo el mismo `kid` que la legítima.
    impostor = KeyPair("key-1")
    adapter = build_adapter(server)

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token(impostor.sign(make_claims()))


async def test_wrong_issuer_is_rejected(signing_key: KeyPair, server: JwksServer) -> None:
    adapter = build_adapter(server)

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token(signing_key.sign(make_claims(iss="https://evil.example")))


async def test_wrong_audience_is_rejected(signing_key: KeyPair, server: JwksServer) -> None:
    adapter = build_adapter(server)

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token(signing_key.sign(make_claims(aud="another-audience")))


async def test_unexpected_algorithm_is_rejected(server: JwksServer) -> None:
    # El adaptador solo acepta RS256/ES256: un HS256 firmado con el `kid`
    # público sería el ataque clásico de confusión de algoritmo.
    adapter = build_adapter(server, algorithms=["RS256"])
    token = jwt.encode(make_claims(), "whatever", algorithm="HS256", headers={"kid": "key-1"})

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token(token)


async def test_alg_none_is_rejected(server: JwksServer) -> None:
    adapter = build_adapter(server)

    def segment(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    unsigned = f"{segment({'alg': 'none', 'typ': 'JWT'})}.{segment(make_claims())}."

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token(unsigned)


async def test_malformed_token_is_rejected(server: JwksServer) -> None:
    adapter = build_adapter(server)

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token("this-is-not-a-jwt")


async def test_token_without_expiry_is_rejected(signing_key: KeyPair, server: JwksServer) -> None:
    adapter = build_adapter(server)

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token(signing_key.sign(make_claims(exp=None)))


async def test_subject_must_be_a_uuid(signing_key: KeyPair, server: JwksServer) -> None:
    adapter = build_adapter(server)

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token(signing_key.sign(make_claims(sub="not-a-uuid")))


async def test_token_without_key_id_is_rejected(server: JwksServer) -> None:
    adapter = build_adapter(server)
    key = KeyPair("ignored")
    token = jwt.encode(make_claims(), key.private, algorithm="RS256")

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token(token)


# ---------------------------------------------------------------------
# Rotación de claves y disponibilidad
# ---------------------------------------------------------------------


async def test_key_rotation_is_picked_up(signing_key: KeyPair, server: JwksServer) -> None:
    adapter = build_adapter(server, min_refresh_seconds=0)
    await adapter.verify_token(signing_key.sign(make_claims()))
    assert server.requests == 1

    rotated = KeyPair("key-2")
    server.keys.append(rotated)

    identity = await adapter.verify_token(rotated.sign(make_claims()))

    assert identity.id == SUBJECT
    assert server.requests == 2


async def test_unknown_key_does_not_refetch_within_the_cooldown(
    signing_key: KeyPair, server: JwksServer
) -> None:
    """Un `kid` inventado no puede provocar una descarga del JWKS por petición."""
    adapter = build_adapter(server, min_refresh_seconds=300)
    await adapter.verify_token(signing_key.sign(make_claims()))
    assert server.requests == 1

    forged = KeyPair("key-does-not-exist")
    for _ in range(3):
        with pytest.raises(InvalidTokenError):
            await adapter.verify_token(forged.sign(make_claims()))

    # Ninguna descarga adicional: el JWKS se pidió una sola vez.
    assert server.requests == 1


async def test_rotation_is_picked_up_once_the_cooldown_expires(
    signing_key: KeyPair, server: JwksServer
) -> None:
    """La espera mínima retrasa la rotación, no la impide."""
    now = [1000.0]
    adapter = build_adapter(server, min_refresh_seconds=60, clock=lambda: now[0])
    await adapter.verify_token(signing_key.sign(make_claims()))

    rotated = KeyPair("key-2")
    server.keys.append(rotated)

    with pytest.raises(InvalidTokenError):
        await adapter.verify_token(rotated.sign(make_claims()))

    now[0] += 61
    identity = await adapter.verify_token(rotated.sign(make_claims()))

    assert identity.id == SUBJECT


async def test_unreachable_jwks_is_not_an_invalid_token(server: JwksServer) -> None:
    server.down = True
    adapter = build_adapter(server)
    key = KeyPair("key-1")

    with pytest.raises(IdentityProviderUnavailableError):
        await adapter.verify_token(key.sign(make_claims()))


async def test_cached_keys_survive_a_jwks_outage(signing_key: KeyPair, server: JwksServer) -> None:
    """Con la clave ya en caché, una caída del JWKS no invalida tokens buenos."""
    now = [1000.0]
    adapter = build_adapter(server, cache_seconds=10, min_refresh_seconds=0, clock=lambda: now[0])
    await adapter.verify_token(signing_key.sign(make_claims()))

    server.down = True
    now[0] += 60  # la caché caduca, pero el JWKS ya no responde

    identity = await adapter.verify_token(signing_key.sign(make_claims()))

    assert identity.id == SUBJECT


async def test_health_check_reports_the_provider_outage(server: JwksServer) -> None:
    server.down = True
    adapter = build_adapter(server)

    with pytest.raises(IdentityProviderUnavailableError):
        await adapter.check_health()


async def test_health_check_passes_when_the_jwks_answers(server: JwksServer) -> None:
    adapter = build_adapter(server)

    await adapter.check_health()

    assert server.requests == 1


def test_subject_fixture_is_a_valid_uuid() -> None:
    assert str(uuid.UUID(SUBJECT)) == SUBJECT
