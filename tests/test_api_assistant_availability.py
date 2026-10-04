"""El chat suma la disponibilidad viva de Materiales **sin alterar** el BOM.

Nivel INTEGRATION MOCK: el endpoint completo (autenticación, permisos, BOM,
adaptador real) contra un ``httpx.MockTransport`` que hace de Materiales. Prueba
routing, mapeo, errores y seguridad. **No** prueba autenticación real,
conectividad ni inventario real: eso es de la prueba física.
"""

import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from elsa.adapters.fake_auth import FakeAuthAdapter
from elsa.adapters.fake_materials_identity import FakeMaterialsIdentityAdapter
from elsa.adapters.memory_abuse_guard import InMemoryAbuseGuard
from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.adapters.memory_contributions import InMemoryContributionsRepository
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.memory_permissions import InMemoryPermissionsRepository
from elsa.adapters.supabase_materials import BoundMaterials, SupabaseMaterialsGateway
from elsa.config import Settings
from elsa.container import Container
from elsa.core.capability_outcomes import asserts_complete_coverage, asserts_nonexistence
from elsa.demo.seed import ASSET_CODE, DOMAIN, seed_demo_data
from elsa.main import create_app
from tests.conftest import ENGINEER_TOKEN, auth_header, make_test_settings
from tests.test_materials_http_adapter import (
    API_KEY,
    BASE,
    Recorder,
    encode,
    lookup_recorder,
    matched_body,
    not_returned_body,
    raising,
)

pytestmark = pytest.mark.anyio

ASK = f"/api/v1/assistant/{DOMAIN}/{ASSET_CODE}/ask"
CODE_QUESTION = "¿Qué disponibilidad tiene el material 1234567?"


class Harness:
    """Una app con el adaptador real de Materiales sobre un transporte simulado."""

    def __init__(self, client: httpx.AsyncClient, recorder: Recorder, tokens: list[str]) -> None:
        self.client = client
        self.recorder = recorder
        self.tokens = tokens

    async def ask(self, question: str, token: str = ENGINEER_TOKEN) -> httpx.Response:
        return await self.client.post(ASK, json={"question": question}, headers=auth_header(token))

    def lookups(self) -> list[httpx.Request]:
        return [r for r in self.recorder.requests if r.url.path.endswith("lookup_material_by_code")]


@pytest.fixture
def recorder() -> Recorder:
    return lookup_recorder(lambda request: encode(matched_body(_sent_code(request))))


def _sent_code(request: httpx.Request) -> str:
    import json

    code = json.loads(request.content)["p_material_code"]
    assert isinstance(code, str)
    return code


@pytest.fixture
async def harness(
    recorder: Recorder,
    settings: Settings,
    auth_adapter: FakeAuthAdapter,
    materials_identity: FakeMaterialsIdentityAdapter,
    permissions: InMemoryPermissionsRepository,
    abuse_guard: InMemoryAbuseGuard,
    knowledge: InMemoryKnowledgeRepository,
    artifact_storage: InMemoryArtifactStorage,
    contributions: InMemoryContributionsRepository,
) -> AsyncIterator[Harness]:
    gateway = SupabaseMaterialsGateway(
        rpc_base_url=BASE,
        api_key=API_KEY,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(recorder)),
        timeout_seconds=8.0,
    )
    tokens: list[str] = []

    def factory(token: str) -> BoundMaterials:
        tokens.append(token)
        return gateway.for_token(token)

    container = Container(
        settings,
        auth=auth_adapter,
        materials_identity=materials_identity,
        materials_inventory=factory,
        permissions=permissions,
        abuse_guard=abuse_guard,
        knowledge=knowledge,
        artifact_storage=artifact_storage,
        contributions=contributions,
    )
    app: FastAPI = create_app(settings, container)
    await seed_demo_data(
        permissions=permissions, knowledge=knowledge, settings=make_test_settings(demo_seed=True)
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield Harness(client, recorder, tokens)


def route(recorder: Recorder, lookup: Callable[[httpx.Request], httpx.Response]) -> None:
    recorder.routes["elsa_v1_lookup_material_by_code"] = lookup


# ----------------------------------------------------------------------
# Camino feliz
# ----------------------------------------------------------------------


async def test_a_code_question_returns_live_availability(harness: Harness) -> None:
    response = await harness.ask(CODE_QUESTION)

    assert response.status_code == 200
    block = response.json()["availability"]
    assert block["status"] == "matched"
    assert block["requested_code"] == "1234567"
    material = block["material"]
    assert material["code"] == "1234567"
    assert material["total_available"] == "6.500"
    # Multiubicación sin colapsar, y la ubicación ausente se conserva como ausente.
    assert [row["center"] for row in material["locations"]] == ["C1", "C2"]
    assert material["locations"][1]["location"] is None
    provenance = block["provenance"]
    assert provenance["source"] == "materiales"
    assert provenance["contract_version"] == "1"
    assert provenance["inventory_version"] == 7
    assert provenance["match_origin"] == "exact_material_code"
    assert provenance["coverage_state"] == "unknown"
    # La cobertura desconocida se dice; no se disfraza de completa.
    assert block["scope_note"]
    assert not asserts_complete_coverage(block["scope_note"])


async def test_a_bare_code_is_enough(harness: Harness) -> None:
    body = (await harness.ask("1234567")).json()

    assert body["availability"]["status"] == "matched"


async def test_the_lookup_uses_the_token_of_that_request_only(harness: Harness) -> None:
    await harness.ask(CODE_QUESTION)

    assert harness.tokens == [ENGINEER_TOKEN]
    (lookup,) = harness.lookups()
    assert lookup.headers["Authorization"] == f"Bearer {ENGINEER_TOKEN}"
    assert lookup.headers["apikey"] == API_KEY


@pytest.mark.parametrize("code", ["000123", "0000001234567"])
async def test_leading_zeros_reach_materials_untouched(harness: Harness, code: str) -> None:
    body = (await harness.ask(f"disponibilidad del material {code}")).json()

    (lookup,) = harness.lookups()
    import json

    assert json.loads(lookup.content)["p_material_code"] == code
    assert body["availability"]["requested_code"] == code


# ----------------------------------------------------------------------
# Routing: sin código exacto no hay llamada
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "question",
    ["rodamiento SKF", "rodamiento prensa", "SYN-100003", "stock de 12345", "llave mixta"],
)
async def test_free_text_is_never_sent_to_materials(harness: Harness, question: str) -> None:
    response = await harness.ask(question)

    assert response.status_code == 200
    assert response.json()["availability"] is None
    assert harness.recorder.requests == []


async def test_several_codes_are_ambiguous_and_nothing_is_sent(harness: Harness) -> None:
    body = (await harness.ask("stock de 1234567 y 1234568")).json()

    assert body["availability"]["status"] == "ambiguous_code"
    assert harness.recorder.requests == []


async def test_authentication_is_required_before_anything_is_sent(harness: Harness) -> None:
    response = await harness.client.post(ASK, json={"question": CODE_QUESTION})

    assert response.status_code == 401
    assert harness.recorder.requests == []


# ----------------------------------------------------------------------
# El BOM no cambia
# ----------------------------------------------------------------------


async def test_the_bom_answer_is_identical_with_and_without_the_live_block(
    harness: Harness,
) -> None:
    """Con Materiales caído o sin código, el resto de la respuesta es el mismo."""
    question = "rodamiento prensa stock 1234567"
    with_block = (await harness.ask(question)).json()
    route(harness.recorder, raising(httpx.ConnectError("down")))
    degraded = (await harness.ask(question)).json()
    plain = (await harness.ask("rodamiento prensa")).json()

    assert with_block["availability"]["status"] == "matched"
    assert degraded["availability"]["status"] == "unavailable"
    for key in ("components", "failure_modes", "published", "source", "engine", "is_generated"):
        assert with_block[key] == degraded[key]
    assert plain["availability"] is None
    assert plain["components"] == with_block["components"]
    assert plain["is_generated"] is False


async def test_an_existing_material_code_still_finds_its_component(harness: Harness) -> None:
    body = (await harness.ask("SYN-100003")).json()

    assert body["components"][0]["matched_code"] == "SYN-100003"
    assert body["availability"] is None


# ----------------------------------------------------------------------
# Fallos: se declaran, y el BOM sigue respondiendo
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("handler", "status", "fragment"),
    [
        (raising(httpx.ReadTimeout("slow")), "unavailable", "fallo técnico"),
        (raising(httpx.ConnectError("dns")), "unavailable", "fallo técnico"),
        (lambda _r: httpx.Response(401), "unavailable", "no aceptó tu sesión"),
        (lambda _r: httpx.Response(403), "unavailable", "no autorizó"),
        (lambda _r: httpx.Response(503), "unavailable", "fallo técnico"),
        (lambda _r: httpx.Response(200, content=b"{broken"), "contract_error", "contrato"),
    ],
)
async def test_failures_are_declared_and_never_become_an_absence(
    harness: Harness,
    handler: Callable[[httpx.Request], httpx.Response],
    status: str,
    fragment: str,
) -> None:
    route(harness.recorder, handler)

    response = await harness.ask(CODE_QUESTION)

    assert response.status_code == 200
    block = response.json()["availability"]
    assert block["status"] == status
    assert fragment in block["message"]
    assert block["material"] is None
    assert not asserts_nonexistence(block["message"])
    assert response.json()["components"] is not None


async def test_an_incompatible_contract_version_is_not_shown(harness: Harness) -> None:
    bad = matched_body("1234567")
    bad["contract_version"] = "2"
    route(harness.recorder, lambda _r: encode(bad))

    block = (await harness.ask(CODE_QUESTION)).json()["availability"]

    assert block["status"] == "contract_error"
    assert block["material"] is None


async def test_rejected_calls_show_no_inventory(harness: Harness) -> None:
    body: dict[str, Any] = {"contract_version": "1", "call_status": "REJECTED", "results": []}
    route(harness.recorder, lambda _r: encode(body))

    block = (await harness.ask(CODE_QUESTION)).json()["availability"]

    assert block["status"] == "rejected"
    assert block["material"] is None and block["provenance"] is None


async def test_no_active_inventory_is_not_an_absence(harness: Harness) -> None:
    body: dict[str, Any] = {
        "contract_version": "1",
        "call_status": "NO_ACTIVE_INVENTORY",
        "results": [],
    }
    route(harness.recorder, lambda _r: encode(body))

    block = (await harness.ask(CODE_QUESTION)).json()["availability"]

    assert block["status"] == "no_active_inventory"
    assert "no es una ausencia" in block["message"].lower()
    assert not asserts_nonexistence(block["message"])


async def test_not_returned_never_says_the_material_does_not_exist(harness: Harness) -> None:
    route(harness.recorder, lambda _r: encode(not_returned_body("1234567")))

    block = (await harness.ask(CODE_QUESTION)).json()["availability"]

    assert block["status"] == "not_returned"
    assert block["material"] is None
    assert "no devolvió" in block["message"]
    assert not asserts_nonexistence(block["message"])
    assert block["scope_note"]  # cobertura desconocida: sigue declarada


# ----------------------------------------------------------------------
# Seguridad
# ----------------------------------------------------------------------


async def test_the_token_never_appears_in_the_response_or_the_logs(
    harness: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    response = await harness.ask(CODE_QUESTION)
    route(harness.recorder, lambda _r: httpx.Response(401))
    failing = await harness.ask(CODE_QUESTION)

    for body in (response.text, failing.text):
        assert ENGINEER_TOKEN not in body
        assert API_KEY not in body
    logged = caplog.text + repr([record.__dict__ for record in caplog.records])
    assert ENGINEER_TOKEN not in logged
    assert API_KEY not in logged
