"""Endpoints de nodo del relay Render–PC1 (D2.2, ADR 0031).

Solo los usa el agente de PC1. **No** son endpoints de usuario: no pasan por el
JWT del usuario ni por el control de abuso; se autentican con la credencial
propia del nodo (``X-Elsa-Node-Token``).

Orden fijo, de lo barato a lo caro y sin dar pistas a quien no se autentica:

1. credencial del nodo (cabecera) → ``401`` genérico;
2. cuerpo leído **en streaming con tope**, nunca entero para medirlo después
   → ``413``;
3. mensaje del protocolo V1 validado → ``422`` genérico, sin eco del cuerpo;
4. ``node_id`` igual al configurado → el mismo ``401`` del paso 1.

No hay ``/execute``, ``/proxy`` ni ``/fetch``: solo se aceptan los mensajes
tipados del protocolo, con la operación ``assistant.ask``. Las rutas solo se
montan con ``ELSA_RELAY_ENABLED=true``.
"""

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from elsa.api.errors import ApiError
from elsa.container import Container
from elsa.logging import get_request_id
from elsa.relay.auth import NODE_TOKEN_HEADER, NodeCredentialVerifier
from elsa.relay.protocol import (
    Cancel,
    ErrorMessage,
    Heartbeat,
    Register,
    Response,
    parse_message,
)
from elsa.relay.service import (
    MAX_RESPONSE_WIRE_BYTES,
    RelayService,
    RequestNotPendingError,
    ResponseTooLargeError,
    StaleSessionError,
)

router = APIRouter(prefix="/relay/node", tags=["relay"])

_logger = logging.getLogger("elsa.relay.api")

_CONTROL_BODY_MAX_BYTES = 1024
"""``Register`` y ``Heartbeat`` son diminutos (dos identificadores)."""

_RESULT_BODY_MAX_BYTES = MAX_RESPONSE_WIRE_BYTES + 1024
"""La respuesta más grande admitida más margen de envoltura."""

_NO_STORE = {"Cache-Control": "no-store"}


def _components(request: Request) -> tuple[RelayService, NodeCredentialVerifier]:
    container: Container = request.app.state.container
    if container.relay is None or container.relay_verifier is None:
        # Defensa en profundidad: el router solo se monta con el relay activo.
        raise ApiError(404, "Not Found", code="not_found")
    return container.relay, container.relay_verifier


def _unauthorized(request: Request) -> ApiError:
    _logger.warning(
        "auth_failed",
        extra={"event": "auth_failed", "http_request_id": get_request_id(request)},
    )
    return ApiError(401, "Invalid node credentials.", code="unauthorized")


async def _read_bounded(request: Request, limit: int) -> bytes:
    """Lee el cuerpo por trozos y corta en cuanto supera ``limit``."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, "Request body too large.", code="payload_too_large")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise ApiError(413, "Request body too large.", code="payload_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


async def _authenticated_message(request: Request, limit: int) -> tuple[RelayService, Any]:
    service, verifier = _components(request)
    if not verifier.verify_token(request.headers.get(NODE_TOKEN_HEADER)):
        raise _unauthorized(request)
    body = await _read_bounded(request, limit)
    try:
        message = parse_message(body)
    except ValidationError:
        # Sin detalle: el error de pydantic podría reproducir parte del cuerpo.
        raise ApiError(422, "Invalid protocol message.", code="validation_error") from None
    if not verifier.node_id_matches(message.node_id):
        raise _unauthorized(request)
    return service, message


def _wrong_type() -> ApiError:
    return ApiError(422, "Unexpected message type for this endpoint.", code="validation_error")


@router.post("/register")
async def register(request: Request) -> JSONResponse:
    service, message = await _authenticated_message(request, _CONTROL_BODY_MAX_BYTES)
    if not isinstance(message, Register):
        raise _wrong_type()
    try:
        service.register(message)
    except StaleSessionError:
        # Sesión vencida o ya usada: el nodo debe hacer REGISTER con un id nuevo.
        raise ApiError(409, "Node session is not current.", code="stale_session") from None
    return JSONResponse(
        {
            "status": "registered",
            "long_poll_seconds": service.policy.long_poll_seconds,
            "node_ttl_seconds": service.policy.node_ttl_seconds,
        },
        headers=_NO_STORE,
    )


@router.post("/poll")
async def poll(request: Request) -> JSONResponse:
    service, message = await _authenticated_message(request, _CONTROL_BODY_MAX_BYTES)
    if not isinstance(message, Heartbeat):
        raise _wrong_type()
    try:
        outgoing = await service.poll(message)
    except StaleSessionError:
        raise ApiError(409, "Node session is not current.", code="stale_session") from None

    payload: dict[str, Any] | None
    if outgoing is None:
        payload = None
    elif isinstance(outgoing, Cancel):
        payload = outgoing.model_dump(mode="json")
    else:
        # Representación de transporte deliberada: incluye el token del usuario.
        # Se entrega al nodo y no se registra.
        payload = dict(outgoing.to_wire_dict())
    return JSONResponse({"message": payload}, headers=_NO_STORE)


@router.post("/result")
async def result(request: Request) -> JSONResponse:
    service, message = await _authenticated_message(request, _RESULT_BODY_MAX_BYTES)
    if not isinstance(message, Response | ErrorMessage):
        raise _wrong_type()
    try:
        service.accept_result(message)
    except StaleSessionError:
        raise ApiError(409, "Node session is not current.", code="stale_session") from None
    except RequestNotPendingError:
        raise ApiError(409, "Request is not pending.", code="request_not_pending") from None
    except ResponseTooLargeError:
        raise ApiError(413, "Reply too large.", code="payload_too_large") from None
    return JSONResponse({"accepted": True}, headers=_NO_STORE)
