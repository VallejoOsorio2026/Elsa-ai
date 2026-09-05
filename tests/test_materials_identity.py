"""Consulta del perfil propio en el PostgREST de Materiales.

Comprueba que ELSA usa el JWT del propio usuario (sin credencial de servicio
de Materiales) y que distingue "no habilitado" de "Materiales no responde".
"""

from collections.abc import Callable

import httpx
import pytest

from elsa.adapters.supabase_materials_identity import SupabaseMaterialsIdentityAdapter
from elsa.ports.auth import IdentityProviderUnavailableError, InvalidTokenError

pytestmark = pytest.mark.anyio

PROFILES_URL = "https://project.supabase.co/rest/v1/perfiles"
API_KEY = "sb_publishable_is_public_by_design"
USER_ID = "11111111-1111-4111-8111-111111111111"
TOKEN = "the-user-own-jwt"


def build_adapter(
    handler: Callable[[httpx.Request], httpx.Response],
) -> SupabaseMaterialsIdentityAdapter:
    return SupabaseMaterialsIdentityAdapter(
        profiles_url=PROFILES_URL,
        api_key=API_KEY,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        timeout_seconds=2.0,
    )


async def test_active_profile_is_returned() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": USER_ID, "nombre": "Ingeniera", "activo": True}])

    profile = await build_adapter(handler).get_own_profile(USER_ID, access_token=TOKEN)

    assert profile is not None
    assert profile.user_id == USER_ID
    assert profile.display_name == "Ingeniera"
    assert profile.is_active is True


async def test_disabled_profile_is_reported_as_inactive() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": USER_ID, "nombre": "X", "activo": False}])

    profile = await build_adapter(handler).get_own_profile(USER_ID, access_token=TOKEN)

    assert profile is not None
    assert profile.is_active is False


async def test_the_request_uses_the_user_own_token_and_the_public_key() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["apikey"] = request.headers["apikey"]
        seen["authorization"] = request.headers["Authorization"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json=[{"id": USER_ID, "nombre": None, "activo": True}])

    await build_adapter(handler).get_own_profile(USER_ID, access_token=TOKEN)

    assert seen["apikey"] == API_KEY
    assert seen["authorization"] == f"Bearer {TOKEN}"
    assert f"id=eq.{USER_ID}" in seen["url"]
    # Solo se piden las columnas necesarias para autorizar.
    assert "select=id%2Cnombre%2Cactivo" in seen["url"] or "select=id,nombre,activo" in seen["url"]


async def test_missing_profile_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    assert await build_adapter(handler).get_own_profile(USER_ID, access_token=TOKEN) is None


async def test_rls_denial_is_treated_as_no_profile() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "permission denied"})

    assert await build_adapter(handler).get_own_profile(USER_ID, access_token=TOKEN) is None


async def test_rejected_token_is_an_invalid_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid claim"})

    with pytest.raises(InvalidTokenError):
        await build_adapter(handler).get_own_profile(USER_ID, access_token=TOKEN)


async def test_server_error_is_an_availability_problem() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(IdentityProviderUnavailableError):
        await build_adapter(handler).get_own_profile(USER_ID, access_token=TOKEN)


async def test_network_failure_is_an_availability_problem() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("materials is unreachable", request=request)

    with pytest.raises(IdentityProviderUnavailableError):
        await build_adapter(handler).get_own_profile(USER_ID, access_token=TOKEN)


async def test_unexpected_payload_is_an_availability_problem() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    with pytest.raises(IdentityProviderUnavailableError):
        await build_adapter(handler).get_own_profile(USER_ID, access_token=TOKEN)
