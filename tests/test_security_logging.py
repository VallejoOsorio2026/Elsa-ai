"""El JWT y la cabecera ``Authorization`` nunca aparecen en los logs.

La comprobación se hace sobre la salida **serializada** de los logs, que es
lo que realmente acaba en el sistema de trazas, no sobre el mensaje suelto.
"""

import json
import logging
from collections.abc import Iterator

import httpx
import pytest
from pydantic import SecretStr

from elsa.adapters.fake_auth import ADMIN_ID, ENGINEER_ID
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.logging import JsonFormatter
from tests.conftest import ENGINEER_TOKEN, auth_header, make_test_settings

pytestmark = pytest.mark.anyio

# Un token con pinta de JWT real, para que la búsqueda sea significativa.
TOKEN_LIKE_A_JWT = (
    "eyJhbGciOiJSUzI1NiIsImtpZCI6ImtleS0xIn0."
    "eyJzdWIiOiIxMTExMTExMS0xMTExLTQxMTEtODExMS0xMTExMTExMTExMTEifQ."
    "c2lnbmF0dXJlLXRoYXQtc2hvdWxkLW5ldmVyLWJlLWxvZ2dlZA"
)


class CapturingHandler(logging.Handler):
    """Guarda cada registro ya formateado como JSON, igual que en producción."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JsonFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def captured_logs() -> Iterator[CapturingHandler]:
    handler = CapturingHandler()
    logger = logging.getLogger("elsa")
    previous_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


async def test_a_rejected_token_never_reaches_the_logs(
    api: httpx.AsyncClient, captured_logs: CapturingHandler
) -> None:
    response = await api.get("/api/v1/me", headers=auth_header(TOKEN_LIKE_A_JWT))

    assert response.status_code == 401
    assert captured_logs.lines, "the request should have produced log records"
    assert TOKEN_LIKE_A_JWT not in captured_logs.text
    # Tampoco la firma por separado, ni la cabecera completa.
    assert TOKEN_LIKE_A_JWT.rsplit(".", maxsplit=1)[-1] not in captured_logs.text
    assert "authorization" not in captured_logs.text.lower()


async def test_an_accepted_token_never_reaches_the_logs(
    api: httpx.AsyncClient,
    permissions: InMemoryPermissionsRepository,
    captured_logs: CapturingHandler,
) -> None:
    await permissions.grant_permission(
        subject=ENGINEER_ID, domain="mantenimiento", equipment=None, actor=ADMIN_ID
    )

    response = await api.get("/api/v1/me", headers=auth_header(ENGINEER_TOKEN))

    assert response.status_code == 200
    assert ENGINEER_TOKEN not in captured_logs.text
    assert "Bearer" not in captured_logs.text


async def test_the_access_line_records_no_headers_or_query_string(
    api: httpx.AsyncClient, captured_logs: CapturingHandler
) -> None:
    await api.get("/api/v1/me", params={"access_token": TOKEN_LIKE_A_JWT})

    access_lines = [
        json.loads(line)
        for line in captured_logs.lines
        if json.loads(line)["logger"] == "elsa.access"
    ]

    assert access_lines
    for line in access_lines:
        assert line["path"] == "/api/v1/me"
        assert TOKEN_LIKE_A_JWT not in json.dumps(line)


def test_secrets_from_the_configuration_are_not_printed() -> None:
    """``SecretStr`` impide que la configuración se imprima con sus valores."""
    settings = make_test_settings(
        bootstrap_admin_token=SecretStr("super-secret-bootstrap"),
        database_url=SecretStr("postgresql://user:password@host/db"),
    )

    rendered = repr(settings) + str(settings)

    assert "super-secret-bootstrap" not in rendered
    assert "password" not in rendered
