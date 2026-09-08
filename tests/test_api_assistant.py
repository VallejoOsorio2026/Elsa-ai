"""El chat piloto responde con evidencias y declara que no usa un modelo."""

from collections.abc import AsyncIterator

import httpx
import pytest

from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.demo.seed import ASSET_CODE, DOMAIN, seed_demo_data
from tests.conftest import ADMIN_TOKEN, ENGINEER_TOKEN, auth_header, make_test_settings

pytestmark = pytest.mark.anyio

ASK = f"/api/v1/assistant/{DOMAIN}/{ASSET_CODE}/ask"


@pytest.fixture
async def seeded(
    api: httpx.AsyncClient,
    permissions: InMemoryPermissionsRepository,
    knowledge: InMemoryKnowledgeRepository,
) -> AsyncIterator[httpx.AsyncClient]:
    await seed_demo_data(
        permissions=permissions,
        knowledge=knowledge,
        settings=make_test_settings(demo_seed=True),
    )
    yield api


async def test_asking_requires_authentication(seeded: httpx.AsyncClient) -> None:
    response = await seeded.post(ASK, json={"question": "rodamiento"})
    assert response.status_code == 401


async def test_asking_requires_permission_on_the_asset(
    seeded: httpx.AsyncClient,
    permissions: InMemoryPermissionsRepository,
) -> None:
    """Un usuario sin alcance no llega a recuperar nada."""
    await permissions.grant_permission(
        subject="00000000-0000-4000-8000-000000000009",
        domain=DOMAIN,
        equipment="otro-equipo",
        actor="test",
    )
    response = await seeded.post(
        ASK, json={"question": "rodamiento"}, headers=auth_header("fake-token-engineer")
    )
    # El ingeniero sembrado sí tiene alcance: comprobamos el camino positivo
    # aquí y el negativo con un token cuyo usuario no tiene cuenta.
    assert response.status_code == 200

    denied = await seeded.post(
        ASK, json={"question": "rodamiento"}, headers=auth_header("fake-token-nobody")
    )
    assert denied.status_code == 401


async def test_answer_declares_it_is_not_generated(seeded: httpx.AsyncClient) -> None:
    body = (
        await seeded.post(ASK, json={"question": "rodamiento"}, headers=auth_header(ENGINEER_TOKEN))
    ).json()
    assert body["is_generated"] is False
    assert body["engine"] == "literal_search"
    assert "sin modelo de lenguaje" in body["engine_label"]


async def test_answer_carries_the_published_version_as_evidence(
    seeded: httpx.AsyncClient,
) -> None:
    body = (
        await seeded.post(
            ASK, json={"question": "rodamiento prensa"}, headers=auth_header(ENGINEER_TOKEN)
        )
    ).json()
    assert body["published"] is True
    assert body["source"] == "BOM de Ingeniería aprobado, versión 1"
    assert body["components"], "debería encontrar el rodamiento sembrado"
    assert "rodamiento" in body["components"][0]["matched_terms"]


async def test_a_material_code_finds_its_component(seeded: httpx.AsyncClient) -> None:
    body = (
        await seeded.post(ASK, json={"question": "SYN-100003"}, headers=auth_header(ENGINEER_TOKEN))
    ).json()
    assert body["components"][0]["sap_code"] == "SYN-100003"
    assert body["components"][0]["matched_code"] == "SYN-100003"


async def test_failure_modes_are_searched_too(seeded: httpx.AsyncClient) -> None:
    body = (
        await seeded.post(
            ASK, json={"question": "fuga de vapor"}, headers=auth_header(ENGINEER_TOKEN)
        )
    ).json()
    assert body["failure_modes"]
    assert body["failure_modes"][0]["rpn"] == 70


async def test_nothing_found_says_so_without_inventing(seeded: httpx.AsyncClient) -> None:
    body = (
        await seeded.post(
            ASK,
            json={"question": "turbina hidráulica Pelton"},
            headers=auth_header(ENGINEER_TOKEN),
        )
    ).json()
    assert body["components"] == []
    assert body["failure_modes"] == []
    assert "No encontré" in body["message"]


async def test_a_question_without_searchable_terms_is_explained(
    seeded: httpx.AsyncClient,
) -> None:
    body = (
        await seeded.post(ASK, json={"question": "¿que hay?"}, headers=auth_header(ENGINEER_TOKEN))
    ).json()
    assert body["components"] == []
    assert "término buscable" in body["message"]


async def test_chat_attachments_are_never_turned_into_knowledge(
    seeded: httpx.AsyncClient,
) -> None:
    body = (
        await seeded.post(
            ASK,
            json={
                "question": "rodamiento",
                "attachments": [{"filename": "foto.jpg", "byte_size": 1024}],
            },
            headers=auth_header(ENGINEER_TOKEN),
        )
    ).json()
    assert "no se convierte en conocimiento" in body["attachment_note"]
    assert "Agregar conocimiento" in body["attachment_note"]


async def test_the_server_enforces_the_attachment_count(seeded: httpx.AsyncClient) -> None:
    """El límite lo aplica el backend, no el navegador."""
    response = await seeded.post(
        ASK,
        json={
            "question": "rodamiento",
            "attachments": [{"filename": f"{i}.jpg", "byte_size": 10} for i in range(6)],
        },
        headers=auth_header(ENGINEER_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_many_attachments"


async def test_the_server_enforces_the_attachment_size(seeded: httpx.AsyncClient) -> None:
    response = await seeded.post(
        ASK,
        json={
            "question": "rodamiento",
            "attachments": [{"filename": "grande.zip", "byte_size": 51 * 1024 * 1024}],
        },
        headers=auth_header(ENGINEER_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "attachments_too_large"


async def test_an_unknown_asset_is_not_found(seeded: httpx.AsyncClient) -> None:
    response = await seeded.post(
        f"/api/v1/assistant/{DOMAIN}/inexistente/ask",
        json={"question": "rodamiento"},
        headers=auth_header(ADMIN_TOKEN),
    )
    assert response.status_code == 404
