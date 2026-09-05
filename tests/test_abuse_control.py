"""Control de abuso: límites por usuario y su reflejo en la API (429)."""

import httpx
import pytest

from elsa.adapters.fake_auth import ADMIN_ID, ENGINEER_ID
from elsa.adapters.memory_abuse_guard import InMemoryAbuseGuard
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.ports.abuse import AbusePolicy, LimitKind
from tests.conftest import ENGINEER_TOKEN, auth_header

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------
# Unidad
# ---------------------------------------------------------------------


async def test_requests_per_minute_is_enforced() -> None:
    guard = InMemoryAbuseGuard(AbusePolicy(requests_per_minute=2, max_concurrent_requests=0))

    assert (await guard.acquire(user_id="u")).allowed
    await guard.release(user_id="u")
    assert (await guard.acquire(user_id="u")).allowed
    await guard.release(user_id="u")

    verdict = await guard.acquire(user_id="u")

    assert verdict.allowed is False
    assert verdict.kind is LimitKind.REQUESTS_PER_MINUTE
    assert verdict.retry_after_seconds is not None and verdict.retry_after_seconds > 0


async def test_the_window_slides() -> None:
    now = [0.0]
    guard = InMemoryAbuseGuard(
        AbusePolicy(requests_per_minute=1, max_concurrent_requests=0),
        clock=lambda: now[0],
    )
    await guard.acquire(user_id="u")
    assert (await guard.acquire(user_id="u")).allowed is False

    now[0] += 61

    assert (await guard.acquire(user_id="u")).allowed is True


async def test_limits_are_per_user() -> None:
    guard = InMemoryAbuseGuard(AbusePolicy(requests_per_minute=1, max_concurrent_requests=0))
    await guard.acquire(user_id="one")

    assert (await guard.acquire(user_id="two")).allowed is True


async def test_concurrent_requests_are_capped() -> None:
    guard = InMemoryAbuseGuard(AbusePolicy(requests_per_minute=0, max_concurrent_requests=1))
    assert (await guard.acquire(user_id="u")).allowed is True

    blocked = await guard.acquire(user_id="u")
    assert blocked.allowed is False
    assert blocked.kind is LimitKind.CONCURRENT_REQUESTS

    await guard.release(user_id="u")
    assert (await guard.acquire(user_id="u")).allowed is True


async def test_zero_means_no_limit() -> None:
    guard = InMemoryAbuseGuard(AbusePolicy(requests_per_minute=0, max_concurrent_requests=0))

    for _ in range(50):
        assert (await guard.acquire(user_id="u")).allowed is True


async def test_simultaneous_sessions_are_capped_when_the_token_declares_one() -> None:
    guard = InMemoryAbuseGuard(
        AbusePolicy(requests_per_minute=0, max_concurrent_requests=0, max_sessions_per_user=2)
    )

    assert (await guard.acquire(user_id="u", session_id="s1")).allowed is True
    assert (await guard.acquire(user_id="u", session_id="s2")).allowed is True

    third = await guard.acquire(user_id="u", session_id="s3")

    assert third.allowed is False
    assert third.kind is LimitKind.SESSIONS


async def test_idle_sessions_stop_counting() -> None:
    now = [0.0]
    guard = InMemoryAbuseGuard(
        AbusePolicy(
            requests_per_minute=0,
            max_concurrent_requests=0,
            max_sessions_per_user=1,
            session_idle_timeout_seconds=100,
        ),
        clock=lambda: now[0],
    )
    await guard.acquire(user_id="u", session_id="s1")

    now[0] += 101

    assert (await guard.acquire(user_id="u", session_id="s2")).allowed is True


async def test_session_limit_is_not_faked_without_a_session_identifier() -> None:
    """Sin identificador de sesión en el token, el límite no se simula."""
    guard = InMemoryAbuseGuard(
        AbusePolicy(requests_per_minute=0, max_concurrent_requests=0, max_sessions_per_user=1)
    )

    assert (await guard.acquire(user_id="u", session_id=None)).allowed is True
    assert (await guard.acquire(user_id="u", session_id=None)).allowed is True


# ---------------------------------------------------------------------
# API
# ---------------------------------------------------------------------


@pytest.fixture
def abuse_guard() -> InMemoryAbuseGuard:
    return InMemoryAbuseGuard(AbusePolicy(requests_per_minute=2, max_concurrent_requests=0))


async def test_exceeding_the_rate_limit_returns_429(
    api: httpx.AsyncClient, permissions: InMemoryPermissionsRepository
) -> None:
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment=None, actor=ADMIN_ID
    )
    headers = auth_header(ENGINEER_TOKEN)

    assert (await api.get("/api/v1/me", headers=headers)).status_code == 200
    assert (await api.get("/api/v1/me", headers=headers)).status_code == 200

    throttled = await api.get("/api/v1/me", headers=headers)

    assert throttled.status_code == 429
    assert throttled.json()["error"]["code"] == "too_many_requests"
    assert int(throttled.headers["Retry-After"]) > 0


async def test_the_rate_limit_does_not_apply_before_authentication(
    api: httpx.AsyncClient,
) -> None:
    """Un token inválido sigue devolviendo 401, no 429."""
    for _ in range(5):
        response = await api.get("/api/v1/me", headers=auth_header("forged"))
        assert response.status_code == 401
