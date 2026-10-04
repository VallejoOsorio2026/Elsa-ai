"""Adaptador real de ``MaterialsPort``: fachada contractual V1 de Materiales.

Habla con las tres RPC publicadas por Materiales sobre HTTPS/PostgREST, con la
identidad del **propio usuario** y la clave publicable (pública por diseño). No
usa ``service_role``, no abre PostgreSQL y no hace login: el bearer es el JWT
que el usuario ya presentó a ELSA.

Dos piezas, con ciclos de vida distintos a propósito:

- :class:`SupabaseMaterialsGateway` es **compartida** por todo el proceso.
  Guarda el cliente HTTP, la configuración y la caché del descriptor. **Nunca
  recibe ni conserva un token.**
- :class:`BoundMaterials` se crea **por petición** con :meth:`for_token`, es la
  que implementa :class:`elsa.ports.materials.MaterialsPort` y es la única que
  tiene el JWT, en memoria y mientras dura esa petición.

La caché del descriptor contiene solo información contractual común (versión y
operaciones). Nunca identidad, token ni respuestas de inventario, y por eso
puede compartirse entre usuarios sin mezclar nada de ninguno.

El descriptor no puede sondearse sin sesión: el ACL de Materiales solo da
``EXECUTE`` a ``authenticated``. Se valida de forma perezosa, con el token de la
primera consulta, y **falla cerrado** ante una versión incompatible (ADR 0021
§15.3).

Política de fallos, alineada con ADR 0021 §5 y §14:

- red, plazo agotado, 401, 403, 429 y 5xx → ``UNAVAILABLE`` (fallo técnico, nunca
  una ausencia). La categoría queda en el log y en :attr:`BoundMaterials.last_failure`.
- JSON ilegible, campos que faltan, versión distinta de ``"1"``, eco de código
  distinto del enviado → :class:`MaterialsContractViolationError`.

El código llega **tal cual** y sale **tal cual** (M3-A, ADR 0024 §8): sin
``strip``, sin ceros, sin conversión numérica.
"""

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from elsa.core.capability_outcomes import CapabilityCallStatus, CapabilityOutcome
from elsa.core.coverage_policy import InventoryCoverageState
from elsa.core.material_code import EXPECTED_MATERIALS_CONTRACT_VERSION
from elsa.ports.materials import (
    AbsenceReason,
    ContractDescriptor,
    ContractOperation,
    DerivedValue,
    InventoryCoverage,
    InventoryStatusResult,
    InventoryVersion,
    MatchOrigin,
    MaterialAbsence,
    MaterialAttribution,
    MaterialFacts,
    MaterialLookupRequest,
    MaterialsContractViolationError,
    MaterialsLookupResult,
    StockLocation,
)

__all__ = ["BoundMaterials", "SupabaseMaterialsGateway"]

_logger = logging.getLogger("elsa.materials")

EXPECTED_CONTRACT_VERSION = EXPECTED_MATERIALS_CONTRACT_VERSION
"""La única versión que este adaptador sabe leer."""

_RPC_DESCRIPTOR = "elsa_v1_get_contract_descriptor"
_RPC_STATUS = "elsa_v1_get_inventory_status"
_RPC_LOOKUP = "elsa_v1_lookup_material_by_code"

_REQUIRED_OPERATIONS = {
    "lookup_material_by_code": "/rest/v1/rpc/" + _RPC_LOOKUP,
    "get_inventory_status": "/rest/v1/rpc/" + _RPC_STATUS,
    "get_contract_descriptor": "/rest/v1/rpc/" + _RPC_DESCRIPTOR,
}

_DESCRIPTOR_TTL_SECONDS = 600.0


class _Unavailable(Exception):
    """Fallo técnico de transporte. Se traduce a ``UNAVAILABLE``, nunca a ausencia."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True, slots=True)
class _CachedDescriptor:
    descriptor: ContractDescriptor
    fetched_at: float


class SupabaseMaterialsGateway:
    """Recursos compartidos de la fachada. No conoce a ningún usuario."""

    def __init__(
        self,
        *,
        rpc_base_url: str,
        api_key: str,
        http_client: httpx.AsyncClient,
        timeout_seconds: float,
    ) -> None:
        self._rpc_base_url = rpc_base_url.rstrip("/")
        self._api_key = api_key
        self._http = http_client
        self._timeout = timeout_seconds
        self._descriptor: _CachedDescriptor | None = None

    def for_token(self, access_token: str) -> "BoundMaterials":
        """Crea el objeto de **esta** petición. No se guarda en ninguna parte."""
        return BoundMaterials(self, access_token)

    # -----------------------------------------------------------------
    # Interno, usado por BoundMaterials
    # -----------------------------------------------------------------

    async def _call(self, operation: str, body: dict[str, str], token: str) -> Any:
        """Una RPC. Devuelve el JSON ya decodificado o lanza :class:`_Unavailable`."""
        started = time.monotonic()
        try:
            response = await self._http.post(
                f"{self._rpc_base_url}/{operation}",
                json=body,
                headers={
                    "apikey": self._api_key,
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            self._log_failure(operation, "timeout", None, started)
            raise _Unavailable("timeout") from None
        except httpx.HTTPError:
            self._log_failure(operation, "network", None, started)
            raise _Unavailable("network") from None

        status = response.status_code
        if status != httpx.codes.OK:
            category = {401: "auth_401", 403: "forbidden"}.get(status, f"http_{status}")
            self._log_failure(operation, category, status, started)
            raise _Unavailable(category)

        try:
            # `Decimal` en los decimales: las existencias no pasan por `float`.
            payload = json.loads(response.content, parse_float=Decimal)
        except ValueError:
            self._log_failure(operation, "contract", status, started)
            raise MaterialsContractViolationError("the response is not valid JSON") from None

        _logger.info(
            "materials rpc answered",
            extra={
                "operation": operation,
                "http_status": status,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            },
        )
        return payload

    @staticmethod
    def _log_failure(operation: str, category: str, status: int | None, started: float) -> None:
        _logger.warning(
            "materials rpc failed",
            extra={
                "operation": operation,
                "category": category,
                "http_status": status,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
            },
        )

    async def _ensure_descriptor(self, token: str) -> None:
        """Garantiza que el contrato declarado es compatible. Falla cerrado."""
        cached = self._descriptor
        if cached is not None and time.monotonic() - cached.fetched_at < _DESCRIPTOR_TTL_SECONDS:
            return
        payload = await self._call(_RPC_DESCRIPTOR, {}, token)
        descriptor = _guard(lambda: _parse_descriptor(payload))
        _check_descriptor(descriptor)
        self._descriptor = _CachedDescriptor(descriptor, time.monotonic())


class BoundMaterials:
    """Implementa :class:`MaterialsPort` para **una** petición y un token."""

    def __init__(self, gateway: SupabaseMaterialsGateway, access_token: str) -> None:
        self._gateway = gateway
        self._token = access_token
        self.last_failure: str | None = None
        """Categoría del último fallo técnico (``timeout``, ``auth_401``, …)."""

    async def lookup_material_by_code(
        self, request: MaterialLookupRequest
    ) -> MaterialsLookupResult:
        if request.contract_version != EXPECTED_CONTRACT_VERSION:
            raise MaterialsContractViolationError("only contract version '1' is supported")
        try:
            await self._gateway._ensure_descriptor(self._token)
            payload = await self._gateway._call(
                _RPC_LOOKUP,
                {
                    "p_contract_version": request.contract_version,
                    # El código viaja sin tocar: M3-A prohíbe trim, ceros y padding.
                    "p_material_code": request.material_code,
                },
                self._token,
            )
        except _Unavailable as exc:
            self.last_failure = exc.category
            return MaterialsLookupResult(call_status=CapabilityCallStatus.UNAVAILABLE)
        result = _guard(lambda: _parse_lookup(payload, request.material_code))
        _logger.info(
            "materials lookup interpreted",
            extra={
                "call_status": result.call_status.value,
                "outcome": result.outcome.value if result.outcome else None,
                "contract_version": result.contract_version,
                "match_origin": (
                    result.attribution.match_origin.value if result.attribution else None
                ),
                "source_version": (result.inventory.version_number if result.inventory else None),
            },
        )
        return result

    async def get_inventory_status(self) -> InventoryStatusResult:
        try:
            await self._gateway._ensure_descriptor(self._token)
            payload = await self._gateway._call(
                _RPC_STATUS, {"p_contract_version": EXPECTED_CONTRACT_VERSION}, self._token
            )
        except _Unavailable as exc:
            self.last_failure = exc.category
            return InventoryStatusResult(call_status=CapabilityCallStatus.UNAVAILABLE)
        return _guard(lambda: _parse_status(payload))

    async def get_contract_descriptor(self) -> ContractDescriptor:
        """El descriptor que declara la fuente. Un fallo técnico **no** se disfraza.

        Si no responde, la versión es desconocida (ADR 0021 §15.3): se propaga
        el fallo y quien llama declara el servicio degradado.
        """
        payload = await self._gateway._call(_RPC_DESCRIPTOR, {}, self._token)
        return _guard(lambda: _parse_descriptor(payload))


# ----------------------------------------------------------------------
# Interpretación del sobre contractual
# ----------------------------------------------------------------------


def _guard[T](parse: Callable[[], T]) -> T:
    """Convierte cualquier defecto de forma en una violación de contrato.

    El mensaje nunca incluye el contenido de la respuesta: puede traer datos de
    inventario y no debe acabar en un log.
    """
    try:
        return parse()
    except MaterialsContractViolationError:
        raise
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        raise MaterialsContractViolationError(
            "the response does not match the V1 contract"
        ) from None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterialsContractViolationError(message)


def _obj(value: Any) -> dict[str, Any]:
    _require(isinstance(value, dict), "expected a JSON object")
    return value


def _str(value: Any) -> str:
    _require(isinstance(value, str), "expected a string")
    return value


def _opt_str(value: Any) -> str | None:
    return None if value is None else _str(value)


def _int(value: Any) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), "expected an integer")
    return value


def _decimal(value: Any) -> Decimal:
    _require(
        isinstance(value, int | Decimal) and not isinstance(value, bool),
        "expected a number",
    )
    return Decimal(value)


def _bool(value: Any) -> bool:
    _require(isinstance(value, bool), "expected a boolean")
    return value


def _datetime(value: Any) -> datetime:
    return datetime.fromisoformat(_str(value))


def _call_status(body: dict[str, Any]) -> CapabilityCallStatus:
    return CapabilityCallStatus(_str(body["call_status"]).lower())


def _check_version(body: dict[str, Any]) -> str:
    version = body["contract_version"]
    # Cadena exacta: `1`, `1.0` y `"1.0"` no son la versión que se sabe leer.
    _require(
        isinstance(version, str) and version == EXPECTED_CONTRACT_VERSION,
        "unexpected contract version",
    )
    return version


def _parse_inventory(raw: Any) -> InventoryVersion:
    data = _obj(raw)
    return InventoryVersion(
        version_number=_int(data["version_number"]),
        loaded_at=_datetime(data["loaded_at"]),
        row_count=_int(data["row_count"]),
        source_file_label=_opt_str(data.get("source_file_label")),
        # `extracted_at` no se lee: V1 no lo transporta y lo declara en el descriptor.
    )


def _parse_coverage(raw: Any) -> InventoryCoverage:
    data = _obj(raw)

    def scope(key: str) -> tuple[str, ...] | None:
        value = data.get(key)
        if value is None:
            return None
        _require(isinstance(value, list), "expected a list")
        return tuple(_str(item) for item in value)

    declared = data.get("declared_at")
    return InventoryCoverage(
        state=InventoryCoverageState(_str(data["state"]).lower()),
        observed_scope=scope("observed_scope"),
        expected_scope=scope("expected_scope"),
        missing_scope=scope("missing_scope"),
        scope_kind=_opt_str(data.get("scope_kind")),
        declared_at=None if declared is None else _datetime(declared),
    )


def _derived[T](raw: Any, convert: Callable[[Any], T]) -> DerivedValue[T]:
    data = _obj(raw)
    return DerivedValue(
        value=convert(data["value"]),
        rule_reference=_str(data["rule_reference"]),
        rule_verifiable=_bool(data["rule_verifiable"]),
    )


def _parse_location(raw: Any) -> StockLocation:
    data = _obj(raw)
    return StockLocation(
        centro=_str(data["centro"]),
        almacen=_str(data["almacen"]),
        ambito=_str(data["ambito"]),
        disponible=_decimal(data["disponible"]),
        comprometido=_decimal(data["comprometido"]),
        ubicacion=_opt_str(data.get("ubicacion")),
    )


def _parse_material(raw: Any) -> MaterialFacts:
    data = _obj(raw)
    locations = data["stock_locations"]
    _require(isinstance(locations, list), "expected a list of stock locations")
    return MaterialFacts(
        code=_str(data["code"]),
        stock_locations=tuple(_parse_location(item) for item in locations),
        total_disponible=_derived(data["total_disponible"], _decimal),
        total_comprometido=_derived(data["total_comprometido"], _decimal),
        dado_de_baja=_derived(data["dado_de_baja"], _bool),
        descripcion=_opt_str(data.get("descripcion")),
        unidad=_opt_str(data.get("unidad")),
        material_antiguo=_opt_str(data.get("material_antiguo")),
    )


def _parse_lookup(payload: Any, sent_code: str) -> MaterialsLookupResult:
    body = _obj(payload)
    status = _call_status(body)

    if status is not CapabilityCallStatus.OK:
        # Sin llamada correcta no hay nada que afirmar, ni siquiera una ausencia.
        return MaterialsLookupResult(call_status=status)

    version = _check_version(body)
    inventory = _parse_inventory(body["inventory"])
    coverage = _parse_coverage(body["coverage"])

    results = body["results"]
    _require(isinstance(results, list) and len(results) == 1, "V1 answers exactly one result")
    entry = _obj(results[0])

    # Eco literal: si no coincide con lo enviado, la fuente respondió a otra pregunta.
    _require(entry["requested_code"] == sent_code, "the echoed code differs from the sent one")

    outcome = CapabilityOutcome(_str(entry["outcome"]).lower())
    if outcome is CapabilityOutcome.NOT_RETURNED:
        absence = _obj(entry["absence"])
        return MaterialsLookupResult(
            call_status=status,
            contract_version=version,
            inventory=inventory,
            coverage=coverage,
            requested_code=sent_code,
            outcome=outcome,
            absence=MaterialAbsence(
                reason=AbsenceReason(_str(absence["reason"]).lower()),
                basis=_str(absence["basis"]),
                authoritative=_bool(absence["authoritative"]),
            ),
        )

    attribution = _obj(entry["attribution"])
    source_version = _obj(attribution["source_version"])
    _require(
        _int(source_version["version_number"]) == inventory.version_number,
        "the attribution names a different inventory version",
    )
    match_origin = MatchOrigin.from_source(_str(_obj(entry["match"])["match_origin"]).lower())
    return MaterialsLookupResult(
        call_status=status,
        contract_version=version,
        inventory=inventory,
        coverage=coverage,
        requested_code=sent_code,
        outcome=outcome,
        material=_parse_material(entry["material"]),
        attribution=MaterialAttribution(
            source_version=inventory,
            contract_version=_check_version(attribution),
            read_at=_datetime(attribution["read_at"]),
            match_origin=match_origin,
        ),
    )


def _parse_status(payload: Any) -> InventoryStatusResult:
    body = _obj(payload)
    status = _call_status(body)
    if status is not CapabilityCallStatus.OK:
        return InventoryStatusResult(call_status=status)
    return InventoryStatusResult(
        call_status=status,
        contract_version=_check_version(body),
        inventory=_parse_inventory(body["inventory"]),
        coverage=_parse_coverage(body["coverage"]),
    )


def _parse_descriptor(payload: Any) -> ContractDescriptor:
    body = _obj(payload)
    operations = body["operations"]
    _require(isinstance(operations, list), "expected a list of operations")
    fields = body.get("unsupported_fields", [])
    _require(isinstance(fields, list), "expected a list")
    return ContractDescriptor(
        contract_version=_str(body["contract_version"]),
        operations=tuple(
            ContractOperation(
                name=_str(_obj(item)["name"]),
                transport_binding=_str(_obj(item)["transport_binding"]),
                deprecated=_bool(_obj(item)["deprecated"]),
            )
            for item in operations
        ),
        unsupported_fields=tuple(_str(item) for item in fields),
    )


def _check_descriptor(descriptor: ContractDescriptor) -> None:
    """El contrato declarado debe ser el que se sabe leer; si no, se cierra."""
    _require(
        descriptor.contract_version == EXPECTED_CONTRACT_VERSION,
        "the declared contract version is not compatible",
    )
    declared = {operation.name: operation for operation in descriptor.operations}
    for name, binding in _REQUIRED_OPERATIONS.items():
        operation = declared.get(name)
        _require(operation is not None, "the descriptor omits a required operation")
        assert operation is not None  # noqa: S101 - garantizado por _require
        _require(
            operation.transport_binding == binding and not operation.deprecated,
            "a required operation is bound elsewhere or deprecated",
        )
