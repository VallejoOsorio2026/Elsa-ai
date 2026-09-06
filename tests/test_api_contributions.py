"""El recorrido del aporte: capacidad, borrador, envío y revisión."""

from collections.abc import AsyncIterator

import httpx
import pytest

from elsa.adapters.memory_contributions import InMemoryContributionsRepository
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.demo.seed import ASSET_CODE, DOMAIN, seed_demo_data
from tests.conftest import (
    ADMIN_TOKEN,
    ENGINEER_TOKEN,
    OTHER_REVIEWER_TOKEN,
    REVIEWER_TOKEN,
    auth_header,
    make_test_settings,
)

pytestmark = pytest.mark.anyio

BASE = f"/api/v1/contributions/{DOMAIN}/{ASSET_CODE}"


@pytest.fixture
async def seeded(
    api: httpx.AsyncClient,
    permissions: InMemoryPermissionsRepository,
    knowledge: InMemoryKnowledgeRepository,
    contributions: InMemoryContributionsRepository,
) -> AsyncIterator[httpx.AsyncClient]:
    await seed_demo_data(
        permissions=permissions,
        knowledge=knowledge,
        contributions=contributions,
        settings=make_test_settings(demo_seed=True),
    )
    yield api


async def _create(
    client: httpx.AsyncClient,
    token: str = ENGINEER_TOKEN,
    *,
    title: str = "Ruido en la prensa",
    audio: bytes | None = b"\x00audio-real",
    duration: float = 12.5,
    attachments: list[tuple[str, bytes]] | None = None,
) -> httpx.Response:
    files: list[tuple[str, tuple[str, bytes, str]]] = []
    if audio is not None:
        files.append(("audio", ("nota.webm", audio, "audio/webm")))
    for name, data in attachments or []:
        files.append(("attachments", (name, data, "application/octet-stream")))
    return await client.post(
        BASE,
        data={"title": title, "audio_duration_seconds": str(duration)},
        files=files or None,
        headers=auth_header(token),
    )


async def _answer_required(
    client: httpx.AsyncClient, contribution_id: str, token: str = ENGINEER_TOKEN
) -> httpx.Response:
    return await client.patch(
        f"{BASE}/{contribution_id}",
        json={
            "checklist": [
                {"key": "que_paso", "answer": "Ruido metálico al arrancar", "checked": True},
                {"key": "donde", "answer": "Rodamiento rodillo prensa inferior", "checked": True},
            ]
        },
        headers=auth_header(token),
    )


# -- Capacidad ---------------------------------------------------------


async def test_capability_separates_reading_contributing_and_reviewing(
    seeded: httpx.AsyncClient,
) -> None:
    engineer = (await seeded.get(f"{BASE}/capability", headers=auth_header(ENGINEER_TOKEN))).json()
    assert engineer["can_contribute"] is True
    assert engineer["can_review"] is False

    reviewer = (await seeded.get(f"{BASE}/capability", headers=auth_header(REVIEWER_TOKEN))).json()
    assert reviewer["can_contribute"] is True
    assert reviewer["can_review"] is True


async def test_capability_declares_the_simulated_transcription(
    seeded: httpx.AsyncClient,
) -> None:
    body = (await seeded.get(f"{BASE}/capability", headers=auth_header(ENGINEER_TOKEN))).json()
    assert body["transcription_is_simulated"] is True


async def test_capability_publishes_the_checklist_and_limits(
    seeded: httpx.AsyncClient,
) -> None:
    body = (await seeded.get(f"{BASE}/capability", headers=auth_header(ENGINEER_TOKEN))).json()
    required = [item["key"] for item in body["checklist"] if item["required"]]
    assert required == ["que_paso", "donde"]
    assert body["max_attachments"] == 5
    assert body["max_audio_seconds"] == 300


async def test_contributing_requires_the_contributor_capability(
    seeded: httpx.AsyncClient,
    contributions: InMemoryContributionsRepository,
) -> None:
    """Poder leer el equipo no habilita para añadirle conocimiento."""
    await contributions.set_contributor(
        "00000000-0000-4000-8000-000000000001",
        domain=DOMAIN,
        asset_code=ASSET_CODE,
        enabled=False,
    )
    response = await _create(seeded)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "contributor_scope_denied"


# -- Borrador ----------------------------------------------------------


async def test_a_new_contribution_is_a_draft_not_knowledge(
    seeded: httpx.AsyncClient,
) -> None:
    body = (await _create(seeded)).json()
    assert body["state"] == "draft"
    assert body["is_published_knowledge"] is False


async def test_the_transcript_is_marked_as_simulated(seeded: httpx.AsyncClient) -> None:
    """El audio es real; el texto no. Y se dice."""
    body = (await _create(seeded)).json()
    assert body["transcript_is_simulated"] is True
    assert body["transcript_engine"] == "simulated"
    assert "TRANSCRIPCIÓN SIMULADA" in body["transcript_text"]
    assert body["audio"]["byte_size"] > 0


async def test_a_simulated_transcript_produces_no_invented_findings(
    seeded: httpx.AsyncClient,
) -> None:
    """El marcador no se interpreta: extraer de él inventaría hallazgos."""
    body = (await _create(seeded)).json()
    detected = {item["key"]: item["detected"] for item in body["normalizations"]}
    assert detected["componentes"] is None
    assert detected["codigos_sap"] is None
    assert detected["equipo"] == "Máquina de papel Tampella"


async def test_editing_the_text_extracts_what_the_person_wrote(
    seeded: httpx.AsyncClient,
) -> None:
    created = (await _create(seeded)).json()
    body = (
        await seeded.patch(
            f"{BASE}/{created['id']}",
            json={
                "transcript_text": (
                    "El rodamiento del rodillo de la prensa inferior, SYN-100001, "
                    "hace ruido en la sección de prensas."
                )
            },
            headers=auth_header(ENGINEER_TOKEN),
        )
    ).json()
    detected = {item["key"]: item["detected"] for item in body["normalizations"]}
    assert "Rodamiento rodillo prensa inferior" in (detected["componentes"] or "")
    assert detected["codigos_sap"] == "SYN-100001"
    assert detected["subsistemas"] == "Sección de prensas"
    assert body["transcript_edited"] is True


async def test_a_code_outside_the_bom_is_shown_apart(seeded: httpx.AsyncClient) -> None:
    """Un código desconocido no se descarta: se separa para que lo mire el revisor."""
    created = (await _create(seeded)).json()
    body = (
        await seeded.patch(
            f"{BASE}/{created['id']}",
            json={"transcript_text": "Cambiamos el SYN-999999 de la prensa."},
            headers=auth_header(ENGINEER_TOKEN),
        )
    ).json()
    detected = {item["key"]: item["detected"] for item in body["normalizations"]}
    assert detected["codigos_desconocidos"] == "SYN-999999"
    assert detected["codigos_sap"] is None


async def test_a_manual_correction_survives_a_later_text_change(
    seeded: httpx.AsyncClient,
) -> None:
    """Corregir a mano y luego reescribir el texto no puede borrar la corrección."""
    created = (await _create(seeded)).json()
    await seeded.patch(
        f"{BASE}/{created['id']}",
        json={"normalizations": [{"key": "resumen", "value": "Ruido en prensa inferior"}]},
        headers=auth_header(ENGINEER_TOKEN),
    )
    body = (
        await seeded.patch(
            f"{BASE}/{created['id']}",
            json={"transcript_text": "Otro texto completamente distinto"},
            headers=auth_header(ENGINEER_TOKEN),
        )
    ).json()
    resumen = next(item for item in body["normalizations"] if item["key"] == "resumen")
    assert resumen["value"] == "Ruido en prensa inferior"
    assert resumen["edited"] is True


# -- Envío -------------------------------------------------------------


async def test_submitting_without_the_required_answers_is_refused(
    seeded: httpx.AsyncClient,
) -> None:
    created = (await _create(seeded)).json()
    assert created["can_submit"] is False
    assert set(created["missing_to_submit"]) == {"que_paso", "donde"}

    response = await seeded.post(
        f"{BASE}/{created['id']}/submit", headers=auth_header(ENGINEER_TOKEN)
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "contribution_incomplete"


async def test_submitting_leaves_it_pending_not_published(
    seeded: httpx.AsyncClient,
) -> None:
    created = (await _create(seeded)).json()
    await _answer_required(seeded, created["id"])
    body = (
        await seeded.post(f"{BASE}/{created['id']}/submit", headers=auth_header(ENGINEER_TOKEN))
    ).json()
    assert body["state"] == "pending"
    assert body["is_published_knowledge"] is False
    assert body["submitted_at"] is not None


async def test_a_pending_contribution_does_not_reach_the_knowledge_query(
    seeded: httpx.AsyncClient,
) -> None:
    """Lo que nadie ha validado no se le enseña a quien va a intervenir."""
    before = (
        await seeded.get(
            f"/api/v1/knowledge/{DOMAIN}/{ASSET_CODE}", headers=auth_header(ENGINEER_TOKEN)
        )
    ).json()
    created = (await _create(seeded)).json()
    await _answer_required(seeded, created["id"])
    await seeded.post(f"{BASE}/{created['id']}/submit", headers=auth_header(ENGINEER_TOKEN))

    after = (
        await seeded.get(
            f"/api/v1/knowledge/{DOMAIN}/{ASSET_CODE}", headers=auth_header(ENGINEER_TOKEN)
        )
    ).json()
    assert after == before

    answer = (
        await seeded.post(
            f"/api/v1/assistant/{DOMAIN}/{ASSET_CODE}/ask",
            json={"question": "ruido metálico al arrancar"},
            headers=auth_header(ENGINEER_TOKEN),
        )
    ).json()
    assert answer["components"] == []


async def test_a_submitted_contribution_can_no_longer_be_edited(
    seeded: httpx.AsyncClient,
) -> None:
    created = (await _create(seeded)).json()
    await _answer_required(seeded, created["id"])
    await seeded.post(f"{BASE}/{created['id']}/submit", headers=auth_header(ENGINEER_TOKEN))

    response = await seeded.patch(
        f"{BASE}/{created['id']}",
        json={"title": "otro"},
        headers=auth_header(ENGINEER_TOKEN),
    )
    assert response.status_code == 409


# -- Revisión ----------------------------------------------------------


async def test_the_review_queue_is_only_for_reviewers(seeded: httpx.AsyncClient) -> None:
    assert (
        await seeded.get(f"{BASE}/pending", headers=auth_header(ENGINEER_TOKEN))
    ).status_code == 403
    assert (
        await seeded.get(f"{BASE}/pending", headers=auth_header(REVIEWER_TOKEN))
    ).status_code == 200


async def test_a_submitted_contribution_reaches_the_queue(seeded: httpx.AsyncClient) -> None:
    created = (await _create(seeded)).json()
    await _answer_required(seeded, created["id"])
    await seeded.post(f"{BASE}/{created['id']}/submit", headers=auth_header(ENGINEER_TOKEN))

    queue = (await seeded.get(f"{BASE}/pending", headers=auth_header(REVIEWER_TOKEN))).json()
    assert [item["id"] for item in queue] == [created["id"]]


async def test_nobody_reviews_their_own_contribution(seeded: httpx.AsyncClient) -> None:
    created = (await _create(seeded, REVIEWER_TOKEN)).json()
    await _answer_required(seeded, created["id"], REVIEWER_TOKEN)
    await seeded.post(f"{BASE}/{created['id']}/submit", headers=auth_header(REVIEWER_TOKEN))

    response = await seeded.post(
        f"{BASE}/{created['id']}/decision",
        json={"approve": True},
        headers=auth_header(REVIEWER_TOKEN),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "self_review_denied"

    # Otra persona con el mismo alcance sí puede.
    other = await seeded.post(
        f"{BASE}/{created['id']}/decision",
        json={"approve": True},
        headers=auth_header(OTHER_REVIEWER_TOKEN),
    )
    assert other.status_code == 200


async def test_rejecting_requires_a_reason(seeded: httpx.AsyncClient) -> None:
    """Sin motivo, el autor no puede corregir nada."""
    created = (await _create(seeded)).json()
    await _answer_required(seeded, created["id"])
    await seeded.post(f"{BASE}/{created['id']}/submit", headers=auth_header(ENGINEER_TOKEN))

    response = await seeded.post(
        f"{BASE}/{created['id']}/decision",
        json={"approve": False},
        headers=auth_header(REVIEWER_TOKEN),
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "reason_required"


async def test_approving_does_not_publish(seeded: httpx.AsyncClient) -> None:
    created = (await _create(seeded)).json()
    await _answer_required(seeded, created["id"])
    await seeded.post(f"{BASE}/{created['id']}/submit", headers=auth_header(ENGINEER_TOKEN))

    body = (
        await seeded.post(
            f"{BASE}/{created['id']}/decision",
            json={"approve": True},
            headers=auth_header(REVIEWER_TOKEN),
        )
    ).json()
    assert body["state"] == "approved"
    assert body["is_published_knowledge"] is False
    assert body["decided_by"] is not None

    published = (
        await seeded.get(
            f"/api/v1/knowledge/{DOMAIN}/{ASSET_CODE}/components",
            headers=auth_header(ENGINEER_TOKEN),
        )
    ).json()
    assert len(published) == 8  # el BOM sembrado, sin añadidos


# -- Visibilidad -------------------------------------------------------


async def test_a_contribution_from_someone_else_is_not_visible(
    seeded: httpx.AsyncClient,
) -> None:
    """Y se responde 404, no 403: confirmar que existe ya es filtrar."""
    created = (await _create(seeded, REVIEWER_TOKEN)).json()
    response = await seeded.get(f"{BASE}/{created['id']}", headers=auth_header(ENGINEER_TOKEN))
    assert response.status_code == 404


async def test_a_reviewer_can_open_any_contribution_of_the_scope(
    seeded: httpx.AsyncClient,
) -> None:
    created = (await _create(seeded)).json()
    response = await seeded.get(f"{BASE}/{created['id']}", headers=auth_header(REVIEWER_TOKEN))
    assert response.status_code == 200


async def test_mine_only_lists_my_own(seeded: httpx.AsyncClient) -> None:
    mine = (await _create(seeded)).json()
    await _create(seeded, REVIEWER_TOKEN)
    listed = (await seeded.get(f"{BASE}/mine", headers=auth_header(ENGINEER_TOKEN))).json()
    assert [item["id"] for item in listed] == [mine["id"]]


# -- Audio y adjuntos --------------------------------------------------


async def test_the_voice_note_can_be_played_back(seeded: httpx.AsyncClient) -> None:
    created = (await _create(seeded, audio=b"\x00sonido")).json()
    response = await seeded.get(
        f"{BASE}/{created['id']}/audio", headers=auth_header(ENGINEER_TOKEN)
    )
    assert response.status_code == 200
    assert response.content == b"\x00sonido"
    assert response.headers["cache-control"] == "no-store"


async def test_the_voice_note_is_not_public(seeded: httpx.AsyncClient) -> None:
    """El audio de planta no se sirve desde un directorio estático."""
    created = (await _create(seeded)).json()
    assert (await seeded.get(f"{BASE}/{created['id']}/audio")).status_code == 401


async def test_the_audio_duration_limit_is_enforced(seeded: httpx.AsyncClient) -> None:
    response = await _create(seeded, duration=301)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "audio_too_long"


async def test_the_attachment_count_is_enforced(seeded: httpx.AsyncClient) -> None:
    response = await _create(seeded, attachments=[(f"foto{index}.jpg", b"x") for index in range(6)])
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "too_many_attachments"


async def test_attachments_are_stored_with_the_contribution(
    seeded: httpx.AsyncClient,
) -> None:
    body = (await _create(seeded, attachments=[("plano.pdf", b"%PDF-fake")])).json()
    assert [item["filename"] for item in body["attachments"]] == ["plano.pdf"]
    assert body["attachments"][0]["byte_size"] == len(b"%PDF-fake")


async def test_an_admin_can_contribute_without_an_explicit_capability(
    seeded: httpx.AsyncClient,
) -> None:
    assert (await _create(seeded, ADMIN_TOKEN)).status_code == 201
