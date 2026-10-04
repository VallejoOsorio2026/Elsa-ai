"""Adaptador HTTPS/PostgREST de la fachada de Materiales (nivel UNIT / mock).

Todo aquí es **local**: el transporte es un ``httpx.MockTransport``. Estas
pruebas demuestran routing, mapeo, errores y seguridad. **No** demuestran
autenticación real, conectividad, el ACL de Materiales ni inventario real: eso
es de la prueba física.
"""

import ast
import json
import logging
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from elsa.adapters.supabase_materials import SupabaseMaterialsGateway
from elsa.core.capability_outcomes import CapabilityCallStatus, CapabilityOutcome
from elsa.core.coverage_policy import InventoryCoverageState
from elsa.ports.materials import (
    MaterialLookupRequest,
    MaterialsContractViolationError,
    MaterialsPort,
)

pytestmark = pytest.mark.anyio

BASE = "https://materials.example.test/rest/v1/rpc"
API_KEY = "sb_publishable_TESTKEY0123456789"
TOKEN = "eyJ.TEST-USER-JWT.signature"

DESCRIPTOR: dict[str, Any] = {
    "contract_version": "1",
    "operations": [
        {
            "name": "lookup_material_by_code",
            "transport_binding": "/rest/v1/rpc/elsa_v1_lookup_material_by_code",
            "deprecated": False,
        },
        {
            "name": "get_inventory_status",
            "transport_binding": "/rest/v1/rpc/elsa_v1_get_inventory_status",
            "deprecated": False,
        },
        {
            "name": "get_contract_descriptor",
            "transport_binding": "/rest/v1/rpc/elsa_v1_get_contract_descriptor",
            "deprecated": False,
        },
    ],
    "unsupported_fields": ["inventory.extracted_at"],
}

INVENTORY = {
    "version_number": 7,
    "loaded_at": "2026-01-10T03:00:00+00:00",
    "row_count": 1000,
    "source_file_label": None,
    "extracted_at": None,
}
COVERAGE = {
    "state": "UNKNOWN",
    "observed_scope": None,
    "expected_scope": None,
    "missing_scope": None,
    "scope_kind": None,
    "declared_at": None,
}


def derived(value: Any, rule: str = "RN-030") -> dict[str, Any]:
    return {"value": value, "rule_reference": rule, "rule_verifiable": False}


def matched_body(
    code: str = "1234567", *, match_origin: str = "EXACT_MATERIAL_CODE"
) -> dict[str, Any]:
    return {
        "contract_version": "1",
        "call_status": "OK",
        "inventory": INVENTORY,
        "coverage": COVERAGE,
        "results": [
            {
                "requested_code": code,
                "outcome": "MATCHED",
                "absence": None,
                "material": {
                    "code": code,
                    "descripcion": "RODAMIENTO DE PRUEBA",
                    "unidad": "UN",
                    "material_antiguo": None,
                    "total_disponible": derived(Decimal("6.500")),
                    "total_comprometido": derived(1),
                    "dado_de_baja": derived(False, "RN-034"),
                    "stock_locations": [
                        {
                            "centro": "C1",
                            "almacen": "A1",
                            "ubicacion": "EST-01",
                            "ambito": "molino",
                            "disponible": Decimal("4.5"),
                            "comprometido": 0,
                        },
                        {
                            "centro": "C2",
                            "almacen": "A2",
                            "ubicacion": None,
                            "ambito": "remoto",
                            "disponible": 2,
                            "comprometido": 1,
                        },
                    ],
                },
                "match": {"match_origin": match_origin},
                "attribution": {
                    "capability": "get_material_availability",
                    "source": "materiales",
                    "source_version": {
                        "version_number": 7,
                        "loaded_at": "2026-01-10T03:00:00+00:00",
                    },
                    "contract_version": "1",
                    "read_at": "2026-10-04T15:00:00+00:00",
                    "match_origin": match_origin,
                },
            }
        ],
    }


def not_returned_body(code: str = "9999999", *, authoritative: bool = False) -> dict[str, Any]:
    return {
        "contract_version": "1",
        "call_status": "OK",
        "inventory": INVENTORY,
        "coverage": COVERAGE,
        "results": [
            {
                "requested_code": code,
                "outcome": "NOT_RETURNED",
                "absence": {
                    "reason": "NOT_RETURNED_BY_SOURCE",
                    "authoritative": authoritative,
                    "basis": "La fuente respondió y no devolvió este código.",
                },
                "material": None,
                "match": None,
                "attribution": None,
            }
        ],
    }


def encode(body: Any) -> httpx.Response:
    """JSON como lo emite PostgREST: ``Decimal`` como número, con sus ceros."""
    text = json.dumps(body, default=lambda value: f"@@{value}@@")
    text = re.sub(r'"@@([0-9.]+)@@"', lambda found: found.group(1), text)
    return httpx.Response(200, content=text.encode(), headers={"content-type": "application/json"})


class Recorder:
    """Responde por operación y recuerda cada petición recibida."""

    def __init__(self, routes: dict[str, Callable[[httpx.Request], httpx.Response]]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        operation = request.url.path.rsplit("/", 1)[-1]
        return self.routes[operation](request)

    def operations(self) -> list[str]:
        return [request.url.path.rsplit("/", 1)[-1] for request in self.requests]


def ok_descriptor(_request: httpx.Request) -> httpx.Response:
    return encode(DESCRIPTOR)


def make_gateway(recorder: Recorder, *, timeout: float = 8.0) -> SupabaseMaterialsGateway:
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    return SupabaseMaterialsGateway(
        rpc_base_url=BASE, api_key=API_KEY, http_client=client, timeout_seconds=timeout
    )


def lookup_recorder(lookup: Callable[[httpx.Request], httpx.Response]) -> Recorder:
    return Recorder(
        {
            "elsa_v1_get_contract_descriptor": ok_descriptor,
            "elsa_v1_lookup_material_by_code": lookup,
            "elsa_v1_get_inventory_status": lambda _r: encode(
                {
                    "contract_version": "1",
                    "call_status": "OK",
                    "inventory": INVENTORY,
                    "coverage": COVERAGE,
                }
            ),
        }
    )


def request_for(code: str) -> MaterialLookupRequest:
    return MaterialLookupRequest(contract_version="1", material_code=code)


# ----------------------------------------------------------------------
# Transporte: URL, cabeceras, cuerpo, plazo
# ----------------------------------------------------------------------


async def test_the_lookup_sends_the_exact_request_to_the_right_rpc() -> None:
    recorder = lookup_recorder(lambda _r: encode(matched_body("000123")))
    bound = make_gateway(recorder).for_token(TOKEN)

    await bound.lookup_material_by_code(request_for("000123"))

    descriptor_call, lookup_call = recorder.requests
    assert descriptor_call.url == f"{BASE}/elsa_v1_get_contract_descriptor"
    assert json.loads(descriptor_call.content) == {}

    assert lookup_call.method == "POST"
    assert lookup_call.url == f"{BASE}/elsa_v1_lookup_material_by_code"
    assert lookup_call.headers["apikey"] == API_KEY
    assert lookup_call.headers["Authorization"] == f"Bearer {TOKEN}"
    assert lookup_call.headers["Content-Type"] == "application/json"
    # El código viaja como cadena exacta: ni 123, ni "123", ni relleno.
    assert json.loads(lookup_call.content) == {
        "p_contract_version": "1",
        "p_material_code": "000123",
    }


async def test_the_timeout_comes_from_configuration() -> None:
    seen: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        return encode(DESCRIPTOR if request.url.path.endswith("descriptor") else matched_body())

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    gateway = SupabaseMaterialsGateway(
        rpc_base_url=BASE, api_key=API_KEY, http_client=client, timeout_seconds=2.0
    )
    await gateway.for_token(TOKEN).lookup_material_by_code(request_for("1234567"))

    assert seen and all(timeout["read"] == 2.0 for timeout in seen)


@pytest.mark.parametrize("code", ["000123", "1234567", " 123", "123 ", "0", "00000000000000"])
async def test_codes_are_sent_literally(code: str) -> None:
    recorder = lookup_recorder(lambda _r: encode(not_returned_body(code)))
    bound = make_gateway(recorder).for_token(TOKEN)

    await bound.lookup_material_by_code(request_for(code))

    assert json.loads(recorder.requests[-1].content)["p_material_code"] == code


# ----------------------------------------------------------------------
# Respuestas del contrato
# ----------------------------------------------------------------------


async def test_a_match_preserves_every_stock_location_and_provenance() -> None:
    recorder = lookup_recorder(lambda _r: encode(matched_body()))
    bound = make_gateway(recorder).for_token(TOKEN)

    result = await bound.lookup_material_by_code(request_for("1234567"))

    assert result.call_status is CapabilityCallStatus.OK
    assert result.outcome is CapabilityOutcome.MATCHED
    assert result.contract_version == "1"
    assert result.inventory is not None
    assert result.inventory.version_number == 7
    assert result.inventory.row_count == 1000
    assert result.inventory.extracted_at is None
    assert result.coverage is not None
    assert result.coverage.state is InventoryCoverageState.UNKNOWN

    assert result.material is not None
    assert result.material.code == "1234567"
    # Multiubicación: dos filas, sin colapsar ni sumar entre sí.
    assert len(result.material.stock_locations) == 2
    first, second = result.material.stock_locations
    assert (first.centro, first.disponible, first.ubicacion) == ("C1", Decimal("4.5"), "EST-01")
    assert (second.centro, second.disponible, second.ubicacion) == ("C2", Decimal("2"), None)
    assert result.material.total_disponible.value == Decimal("6.500")
    assert result.material.total_disponible.rule_reference == "RN-030"

    assert result.attribution is not None
    assert result.attribution.match_origin.value == "exact_material_code"
    assert result.attribution.source == "materiales"
    assert result.attribution.contract_version == "1"


async def test_not_returned_is_a_non_authoritative_absence() -> None:
    recorder = lookup_recorder(lambda _r: encode(not_returned_body("9999999")))
    bound = make_gateway(recorder).for_token(TOKEN)

    result = await bound.lookup_material_by_code(request_for("9999999"))

    assert result.outcome is CapabilityOutcome.NOT_RETURNED
    assert result.material is None
    assert result.absence is not None
    assert result.absence.authoritative is False
    # Cobertura desconocida: no se disfraza de completa ni de incompleta.
    assert result.coverage is not None
    assert result.coverage.state is InventoryCoverageState.UNKNOWN


async def test_an_authoritative_absence_is_a_contract_violation() -> None:
    recorder = lookup_recorder(lambda _r: encode(not_returned_body(authoritative=True)))
    bound = make_gateway(recorder).for_token(TOKEN)

    with pytest.raises(MaterialsContractViolationError):
        await bound.lookup_material_by_code(request_for("9999999"))


@pytest.mark.parametrize("call_status", ["REJECTED", "NO_ACTIVE_INVENTORY"])
async def test_calls_without_a_successful_answer_carry_no_payload(call_status: str) -> None:
    body = {"contract_version": "1", "call_status": call_status, "results": []}
    recorder = lookup_recorder(lambda _r: encode(body))
    bound = make_gateway(recorder).for_token(TOKEN)

    result = await bound.lookup_material_by_code(request_for("1234567"))

    assert result.call_status.value == call_status.lower()
    assert result.material is None and result.absence is None and result.outcome is None


async def test_a_fuzzy_match_origin_is_a_contract_violation() -> None:
    recorder = lookup_recorder(lambda _r: encode(matched_body(match_origin="SIMILAR_TEXT")))
    bound = make_gateway(recorder).for_token(TOKEN)

    with pytest.raises(MaterialsContractViolationError):
        await bound.lookup_material_by_code(request_for("1234567"))


async def test_an_echo_that_differs_from_the_sent_code_is_a_violation() -> None:
    recorder = lookup_recorder(lambda _r: encode(matched_body("123")))
    bound = make_gateway(recorder).for_token(TOKEN)

    with pytest.raises(MaterialsContractViolationError):
        await bound.lookup_material_by_code(request_for("000123"))


async def test_inventory_status_is_available() -> None:
    bound = make_gateway(lookup_recorder(lambda _r: encode(matched_body()))).for_token(TOKEN)

    status = await bound.get_inventory_status()

    assert status.call_status is CapabilityCallStatus.OK
    assert status.inventory is not None and status.inventory.version_number == 7


# ----------------------------------------------------------------------
# Versión del contrato y descriptor
# ----------------------------------------------------------------------


@pytest.mark.parametrize("version", [1, 1.0, "1.0", "2", None])
async def test_a_response_with_another_contract_version_is_rejected(version: Any) -> None:
    body = matched_body()
    body["contract_version"] = version
    bound = make_gateway(lookup_recorder(lambda _r: encode(body))).for_token(TOKEN)

    with pytest.raises(MaterialsContractViolationError):
        await bound.lookup_material_by_code(request_for("1234567"))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(contract_version="2"),
        lambda d: d.update(contract_version=1),
        lambda d: d.update(operations=d["operations"][:2]),
        lambda d: d["operations"][0].update(deprecated=True),
        lambda d: d["operations"][0].update(transport_binding="/rest/v1/rpc/other"),
    ],
)
async def test_an_incompatible_descriptor_fails_closed(
    mutation: Callable[[dict[str, Any]], Any],
) -> None:
    descriptor = json.loads(json.dumps(DESCRIPTOR))
    mutation(descriptor)
    recorder = Recorder(
        {
            "elsa_v1_get_contract_descriptor": lambda _r: encode(descriptor),
            "elsa_v1_lookup_material_by_code": lambda _r: encode(matched_body()),
        }
    )
    bound = make_gateway(recorder).for_token(TOKEN)

    with pytest.raises(MaterialsContractViolationError):
        await bound.lookup_material_by_code(request_for("1234567"))

    # Falla cerrado: el lookup ni siquiera se intenta.
    assert recorder.operations() == ["elsa_v1_get_contract_descriptor"]


async def test_the_descriptor_is_checked_once_and_shared_between_users() -> None:
    recorder = lookup_recorder(lambda _r: encode(matched_body()))
    gateway = make_gateway(recorder)

    await gateway.for_token("token-user-a").lookup_material_by_code(request_for("1234567"))
    await gateway.for_token("token-user-b").lookup_material_by_code(request_for("1234567"))

    assert recorder.operations().count("elsa_v1_get_contract_descriptor") == 1
    # Cada lookup viajó con el token de su propio usuario.
    lookups = [r for r in recorder.requests if r.url.path.endswith("lookup_material_by_code")]
    assert [r.headers["Authorization"] for r in lookups] == [
        "Bearer token-user-a",
        "Bearer token-user-b",
    ]


# ----------------------------------------------------------------------
# Fallos técnicos: nunca son una ausencia
# ----------------------------------------------------------------------


def raising(error: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise error

    return handler


@pytest.mark.parametrize(
    ("handler", "category"),
    [
        (raising(httpx.ReadTimeout("slow")), "timeout"),
        (raising(httpx.ConnectError("dns")), "network"),
        (lambda _r: httpx.Response(401), "auth_401"),
        (lambda _r: httpx.Response(403, json={"code": "42501"}), "forbidden"),
        (lambda _r: httpx.Response(429), "http_429"),
        (lambda _r: httpx.Response(400), "http_400"),
        (lambda _r: httpx.Response(404), "http_404"),
        (lambda _r: httpx.Response(503), "http_503"),
    ],
)
async def test_technical_failures_are_unavailable_never_an_absence(
    handler: Callable[[httpx.Request], httpx.Response], category: str
) -> None:
    bound = make_gateway(lookup_recorder(handler)).for_token(TOKEN)

    result = await bound.lookup_material_by_code(request_for("1234567"))

    assert result.call_status is CapabilityCallStatus.UNAVAILABLE
    assert result.outcome is None and result.absence is None and result.material is None
    assert bound.last_failure == category


async def test_a_failing_descriptor_degrades_instead_of_assuming_the_version() -> None:
    recorder = Recorder(
        {
            "elsa_v1_get_contract_descriptor": lambda _r: httpx.Response(503),
            "elsa_v1_lookup_material_by_code": lambda _r: encode(matched_body()),
        }
    )
    bound = make_gateway(recorder).for_token(TOKEN)

    result = await bound.lookup_material_by_code(request_for("1234567"))

    assert result.call_status is CapabilityCallStatus.UNAVAILABLE
    assert recorder.operations() == ["elsa_v1_get_contract_descriptor"]


@pytest.mark.parametrize(
    "content",
    [b"not json", b"[]", b"{}", b'{"contract_version": "1", "call_status": "OK"}'],
)
async def test_an_unreadable_or_incomplete_body_is_a_contract_violation(content: bytes) -> None:
    recorder = lookup_recorder(lambda _r: httpx.Response(200, content=content))
    bound = make_gateway(recorder).for_token(TOKEN)

    with pytest.raises(MaterialsContractViolationError):
        await bound.lookup_material_by_code(request_for("1234567"))


async def test_a_missing_required_field_is_a_contract_violation() -> None:
    body = matched_body()
    del body["results"][0]["material"]["total_disponible"]
    bound = make_gateway(lookup_recorder(lambda _r: encode(body))).for_token(TOKEN)

    with pytest.raises(MaterialsContractViolationError):
        await bound.lookup_material_by_code(request_for("1234567"))


# ----------------------------------------------------------------------
# Seguridad
# ----------------------------------------------------------------------


def test_the_bound_object_implements_the_port() -> None:
    bound = make_gateway(Recorder({})).for_token(TOKEN)
    assert isinstance(bound, MaterialsPort)


def test_each_request_gets_its_own_bound_object() -> None:
    gateway = make_gateway(Recorder({}))
    assert gateway.for_token(TOKEN) is not gateway.for_token(TOKEN)


async def test_shared_state_never_holds_the_token_or_inventory() -> None:
    recorder = lookup_recorder(lambda _r: encode(matched_body()))
    gateway = make_gateway(recorder)

    await gateway.for_token(TOKEN).lookup_material_by_code(request_for("1234567"))

    # Todo lo que el adaptador compartido y su caché conservan, como texto.
    shared = repr(vars(gateway)) + repr(gateway._descriptor)
    assert TOKEN not in shared
    assert "RODAMIENTO" not in shared and "stock_locations" not in shared
    assert gateway._descriptor is not None
    assert gateway._descriptor.descriptor.contract_version == "1"


@pytest.mark.parametrize(
    "handler",
    [
        lambda _r: encode(matched_body()),
        lambda _r: httpx.Response(401),
        lambda _r: httpx.Response(200, content=b"{broken"),
        raising(httpx.ConnectError("boom")),
    ],
)
async def test_logs_never_contain_the_token_the_key_or_the_body(
    handler: Callable[[httpx.Request], httpx.Response], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    bound = make_gateway(lookup_recorder(handler)).for_token(TOKEN)

    try:
        await bound.lookup_material_by_code(request_for("1234567"))
    except MaterialsContractViolationError:
        pass

    logged = caplog.text + repr([record.__dict__ for record in caplog.records])
    assert TOKEN not in logged
    assert API_KEY not in logged
    assert "Bearer" not in logged
    assert "RODAMIENTO" not in logged


def test_the_adapter_uses_no_service_credentials_or_passwords() -> None:
    """Revisa el código, no la prosa: los docstrings pueden nombrar lo que prohíben."""
    path = (
        Path(__file__).resolve().parents[1] / "src" / "elsa" / "adapters" / "supabase_materials.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    words: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                words.append(node.value)
        elif isinstance(node, ast.Name):
            words.append(node.id)
        elif isinstance(node, ast.Attribute):
            words.append(node.attr)
        elif isinstance(node, ast.alias):
            words.append(node.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            words.append(node.module)
    code = " ".join(words).lower()
    for forbidden in ("service_role", "sb_secret", "password", "grant_type", "asyncpg", "psycopg"):
        assert forbidden not in code, forbidden
