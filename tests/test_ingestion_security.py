"""Controles de seguridad de la ingesta a través de la API.

Comprueban lo que el sistema **no** debe hacer: aceptar un archivo enorme,
confiar en el nombre que trae, registrar contenido técnico en los logs o
fingir que guardó evidencia que no guardó.
"""

import logging
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from elsa.adapters.fake_auth import ADMIN_ID, REVIEWER_ID, FakeAuthAdapter
from elsa.adapters.fake_materials_identity import FakeMaterialsIdentityAdapter
from elsa.adapters.memory_abuse_guard import InMemoryAbuseGuard
from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.container import Container
from elsa.main import create_app
from elsa.ports.knowledge import TechnicalAssetRecord
from tests.conftest import REVIEWER_TOKEN, auth_header, make_test_settings
from tests.fixtures_sources import engineering_workbook

pytestmark = pytest.mark.anyio

DOMAIN = "mantenimiento"
ASSET = "tampella"
BASE = f"/api/v1/technical/{DOMAIN}/{ASSET}"
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture
async def asset(
    permissions: InMemoryPermissionsRepository, knowledge: InMemoryKnowledgeRepository
) -> TechnicalAssetRecord:
    await permissions.bootstrap_admin(subject=ADMIN_ID)
    await permissions.grant_permission(
        subject=REVIEWER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )
    await permissions.grant_reviewer(
        subject=REVIEWER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )
    return await knowledge.create_asset(code=ASSET, name="Activo de prueba", domain=DOMAIN)


def _file(data: bytes, name: str) -> dict[str, Any]:
    return {"file": (name, data, XLSX_TYPE)}


@pytest.mark.parametrize(
    "filename",
    [
        "../../../etc/passwd",
        "..\\..\\windows\\system32\\evil.xlsx",
        "/absolute/path/bom.xlsx",
        "bom\x00.xlsx",
        "a" * 400 + ".xlsx",
        "<script>alert(1)</script>.xlsx",
    ],
)
async def test_a_hostile_filename_never_reaches_the_storage(
    api: httpx.AsyncClient,
    asset: TechnicalAssetRecord,
    artifact_storage: InMemoryArtifactStorage,
    filename: str,
) -> None:
    """La clave se deriva del contenido, no del nombre que trae el archivo."""
    response = await api.post(
        f"{BASE}/engineering-bom",
        files=_file(engineering_workbook(), filename),
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 200
    keys = artifact_storage.stored_keys()
    assert keys
    for key in keys:
        assert ".." not in key
        assert not key.startswith("/")
        assert "\x00" not in key
        assert "script" not in key


async def test_an_upload_over_the_limit_is_refused(
    settings: Any,
    auth_adapter: FakeAuthAdapter,
    materials_identity: FakeMaterialsIdentityAdapter,
    permissions: InMemoryPermissionsRepository,
    knowledge: InMemoryKnowledgeRepository,
    artifact_storage: InMemoryArtifactStorage,
    abuse_guard: InMemoryAbuseGuard,
) -> None:
    small_limit = make_test_settings(ingestion_max_upload_bytes=2048)
    container = Container(
        small_limit,
        auth=auth_adapter,
        materials_identity=materials_identity,
        permissions=permissions,
        abuse_guard=abuse_guard,
        knowledge=knowledge,
        artifact_storage=artifact_storage,
    )
    app: FastAPI = create_app(small_limit, container)
    await permissions.bootstrap_admin(subject=ADMIN_ID)
    await permissions.grant_permission(
        subject=REVIEWER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )
    await permissions.grant_reviewer(
        subject=REVIEWER_ID, domain=DOMAIN, equipment=ASSET, actor=ADMIN_ID
    )
    await knowledge.create_asset(code=ASSET, name="Activo", domain=DOMAIN)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            f"{BASE}/engineering-bom",
            files=_file(engineering_workbook(), "bom.xlsx"),
            headers=auth_header(REVIEWER_TOKEN),
        )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"
    # Nada se guardó: no se acepta a medias lo que se rechaza.
    assert artifact_storage.stored_keys() == ()


async def test_a_storage_failure_returns_503_and_stores_nothing(
    api: httpx.AsyncClient,
    asset: TechnicalAssetRecord,
    artifact_storage: InMemoryArtifactStorage,
    knowledge: InMemoryKnowledgeRepository,
) -> None:
    """Un almacenamiento caído no se disfraza de éxito."""
    artifact_storage.available = False

    response = await api.post(
        f"{BASE}/engineering-bom",
        files=_file(engineering_workbook(), "bom.xlsx"),
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "artifact_storage_unavailable"
    assert await knowledge.list_versions(asset.id) == ()


async def test_no_technical_content_reaches_the_logs(
    api: httpx.AsyncClient,
    asset: TechnicalAssetRecord,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Los logs llevan conteos y motivos, nunca códigos ni descripciones."""
    with caplog.at_level(logging.DEBUG, logger="elsa"):
        await api.post(
            f"{BASE}/engineering-bom",
            files=_file(engineering_workbook(), "bom.xlsx"),
            headers=auth_header(REVIEWER_TOKEN),
        )

    logged = "\n".join(f"{record.getMessage()} {record.__dict__}" for record in caplog.records)
    assert "10000001" not in logged
    assert "Rodamiento ficticio" not in logged
    assert "PL-001" not in logged


async def test_a_rejected_file_does_not_echo_its_content(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    secret = b"CONTENIDO-INTERNO-QUE-NO-DEBE-VOLVER"

    response = await api.post(
        f"{BASE}/engineering-bom",
        files=_file(secret, "bom.xlsx"),
        headers=auth_header(REVIEWER_TOKEN),
    )

    assert response.status_code == 422
    assert "CONTENIDO-INTERNO" not in response.text
    assert "Traceback" not in response.text


async def test_the_bootstrap_token_never_appears_in_a_response(
    api: httpx.AsyncClient, asset: TechnicalAssetRecord
) -> None:
    response = await api.get(f"{BASE}/versions", headers=auth_header(REVIEWER_TOKEN))

    assert "bootstrap" not in response.text.lower()
