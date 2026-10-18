"""``assistant.ask`` en modo RELAY: la pregunta se responde en PC1 (ADR 0033).

Misma ruta y mismos modelos que :mod:`elsa.api.v1.assistant`, que sigue siendo
el modo LOCAL. Solo uno de los dos routers se monta, según
``ELSA_ASSISTANT_EXECUTION_MODE``; el navegador no nota la diferencia.

Lo que hace este proceso, y nada más:

1. **Rechaza la reentrada.** Una petición con ``X-Elsa-Relay-Hop`` la mandó un
   agente: si llegó aquí, alguien configuró en ``relay`` la ELSA de PC1. Se
   rechaza antes de autenticar, venga de donde venga; no depende de CORS.
2. **Autentica** (JWT y control de abuso). No autoriza: cuenta, permisos,
   alcance, activo, conocimiento y Materiales los decide ELSA local con el
   mismo token. Todo 403 de permisos procede de PC1.
3. **Valida la forma** de ``domain`` y ``asset``. Un valor mal formado es un
   ``422``, no un 403: aquí no se decide ningún permiso.
4. **Somete** la pregunta al :class:`~elsa.relay.service.RelayService` de este
   mismo proceso, sin HTTP intermedio, y espera. Si el navegador se desconecta,
   la espera se cancela y el relay avisa al agente.
5. **Valida** el resultado contra :class:`AskResponse` antes de devolverlo.

**Sin respaldo local.** Esta ruta no tiene en su firma conocimiento, permisos
ni Materiales: si PC1 no responde, el usuario recibe un error explícito y
Render no ejecuta nada en su lugar.

Seguridad de los logs: identificadores, resultado, código y duración. Nunca el
token, la pregunta, los adjuntos, el resultado ni el ``detail`` del nodo.
"""

import asyncio
import logging
import time
from collections.abc import Coroutine
from typing import Any
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, Path, Request, status
from pydantic import SecretStr, ValidationError

from elsa.api.deps import admitted_identity, bearer_token, get_container
from elsa.api.errors import ApiError
from elsa.api.v1.assistant import AskRequest, AskResponse
from elsa.container import Container
from elsa.core.authorization import InvalidScopeError, normalize_scope_value
from elsa.ports.auth import AuthenticatedUser
from elsa.relay.protocol import AskParams, AttachmentMeta, ErrorCode, Response
from elsa.relay.service import RelayService
from elsa.relay.store import RelayFailure

_logger = logging.getLogger("elsa.api.assistant_relay")

router = APIRouter(prefix="/assistant/{domain}/{asset}", tags=["assistant"])

RELAY_HOP_HEADER = "X-Elsa-Relay-Hop"
"""La pone el agente de PC1 en cada llamada a ELSA local. Debe coincidir con
``elsa.agent.local_client.RELAY_HOP_HEADER`` (un test lo comprueba)."""

_NODE_UNAVAILABLE_MESSAGE = (
    "ELSA local (PC1) is not available right now. The question was not answered "
    "elsewhere; try again later."
)

_UNAUTHORIZED_HEADERS = {"WWW-Authenticate": "Bearer"}

# ``detail`` del nodo → (estado, código, mensaje). El ``detail`` solo elige la
# fila: nunca se copia a la respuesta. Lo que no está en la lista va al valor
# por defecto de su ``ErrorCode``.
_Row = tuple[int, str, str]

_BY_DETAIL: dict[ErrorCode, dict[str, _Row]] = {
    ErrorCode.FORBIDDEN: {
        "local:account_disabled": (
            status.HTTP_403_FORBIDDEN,
            "account_disabled",
            "This user is not enabled in the identity source.",
        ),
        "local:insufficient_permissions": (
            status.HTTP_403_FORBIDDEN,
            "insufficient_permissions",
            "Access to this scope is not allowed.",
        ),
    },
    ErrorCode.INVALID_REQUEST: {
        "local:asset_not_found": (
            status.HTTP_404_NOT_FOUND,
            "asset_not_found",
            "Unknown technical asset.",
        ),
        "local:not_found": (
            status.HTTP_404_NOT_FOUND,
            "asset_not_found",
            "Unknown technical asset.",
        ),
        "local:too_many_attachments": (
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "too_many_attachments",
            "The message has more attachments than allowed.",
        ),
        "local:attachments_too_large": (
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "attachments_too_large",
            "The attachments of the message exceed the allowed size.",
        ),
    },
    ErrorCode.LOCAL_UNAVAILABLE: {
        "local:too_many_requests": (
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too_many_requests",
            "Too many requests.",
        ),
        "local:identity_provider_unavailable": (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "identity_provider_unavailable",
            "The identity provider is temporarily unavailable.",
        ),
        "local:knowledge_store_unavailable": (
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "knowledge_store_unavailable",
            "The knowledge store is temporarily unavailable.",
        ),
    },
}

_LOCAL_NODE_ERROR: _Row = (
    status.HTTP_503_SERVICE_UNAVAILABLE,
    "local_node_error",
    "ELSA local could not answer this question.",
)

_BY_CODE: dict[ErrorCode, _Row] = {
    ErrorCode.UNAUTHORIZED: (
        status.HTTP_401_UNAUTHORIZED,
        "unauthorized",
        "The token is not valid.",
    ),
    ErrorCode.FORBIDDEN: (
        status.HTTP_403_FORBIDDEN,
        "forbidden",
        "Access is not allowed.",
    ),
    ErrorCode.INVALID_REQUEST: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "validation_error",
        "Request validation failed.",
    ),
    ErrorCode.LOCAL_UNAVAILABLE: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "local_node_unavailable",
        _NODE_UNAVAILABLE_MESSAGE,
    ),
    ErrorCode.TIMEOUT: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "local_node_timeout",
        "ELSA local did not answer in time. The question was not retried; you can ask again.",
    ),
    ErrorCode.LOCAL_ERROR: _LOCAL_NODE_ERROR,
    ErrorCode.PROTOCOL_ERROR: _LOCAL_NODE_ERROR,
    ErrorCode.DUPLICATE_REQUEST: _LOCAL_NODE_ERROR,
    ErrorCode.CANCELLED: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "request_cancelled",
        "The question was cancelled before ELSA local answered.",
    ),
}


def public_error_for(failure: RelayFailure) -> ApiError:
    """Traduce un fallo del relay al error público. ``detail`` nunca sale."""
    row = _BY_DETAIL.get(failure.code, {}).get(failure.detail or "") or _BY_CODE[failure.code]
    status_code, code, message = row
    headers = dict(_UNAUTHORIZED_HEADERS) if status_code == status.HTTP_401_UNAUTHORIZED else None
    return ApiError(status_code, message, code=code, headers=headers)


def _node_unavailable() -> ApiError:
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        _NODE_UNAVAILABLE_MESSAGE,
        code="local_node_unavailable",
    )


def _invalid_node_response() -> ApiError:
    return ApiError(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "ELSA local returned an answer that does not match the contract, so it is not shown.",
        code="local_node_invalid_response",
    )


def _validation_error() -> ApiError:
    return ApiError(
        status.HTTP_422_UNPROCESSABLE_CONTENT, "Request validation failed.", code="validation_error"
    )


def validate_node_result(result: dict[str, Any], *, domain: str, asset: str) -> AskResponse:
    """El resultado opaco del nodo, solo si cumple :class:`AskResponse` y es del activo pedido."""
    try:
        answer = AskResponse.model_validate(result, strict=True)
    except ValidationError:
        raise _invalid_node_response() from None
    if answer.domain != domain or answer.asset != asset:
        raise _invalid_node_response()
    return answer


def _ask_params(domain: str, asset: str, payload: AskRequest) -> AskParams:
    """Forma de la solicitud. Un fallo aquí es estructural (``422``), no de permisos."""
    try:
        return AskParams(
            domain=normalize_scope_value(domain),
            asset=normalize_scope_value(asset),
            question=payload.question,
            attachments=[
                AttachmentMeta.model_validate(item.model_dump()) for item in payload.attachments
            ],
        )
    except (InvalidScopeError, ValidationError):
        raise _validation_error() from None


async def reject_relay_hop(request: Request) -> None:
    """Corta la reentrada: lo que trae la cabecera de salto viene de un agente."""
    if RELAY_HOP_HEADER in request.headers:
        _logger.warning("relay hop rejected", extra={"event": "relay_hop_rejected"})
        raise _node_unavailable()


def get_relay_service(container: Container = Depends(get_container)) -> RelayService:
    """El relay de este proceso. La configuración garantiza que existe en RELAY."""
    if container.relay is None:  # pragma: no cover - lo impide la configuración
        raise _node_unavailable()
    return container.relay


async def _wait_for_disconnect(request: Request) -> None:
    """Vuelve cuando el cliente se va. El cuerpo ya está leído: solo queda el aviso."""
    while (await request.receive())["type"] != "http.disconnect":
        pass


async def _submit_until_disconnect(
    request: Request,
    submission: Coroutine[Any, Any, Response | RelayFailure],
) -> Response | RelayFailure | None:
    """Espera el resultado o la desconexión, lo primero que ocurra.

    Una tarea de ``submit`` y una de vigilancia por petición, ninguna más. Si el
    cliente se va, cancelar ``submit`` dispara la cancelación propia del relay
    (D2.2). Ambas tareas se recogen siempre, también si esta petición se cancela.
    """
    submit_task = asyncio.create_task(submission)
    watcher = asyncio.create_task(_wait_for_disconnect(request))
    try:
        await asyncio.wait({submit_task, watcher}, return_when=asyncio.FIRST_COMPLETED)
        return submit_task.result() if submit_task.done() else None
    finally:
        submit_task.cancel()
        watcher.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(submit_task, watcher, return_exceptions=True)


@router.post("/ask", response_model=AskResponse)
async def ask_via_relay(
    payload: AskRequest,
    request: Request,
    domain: str = Path(...),
    asset: str = Path(...),
    _hop: None = Depends(reject_relay_hop),
    _identity: AuthenticatedUser = Depends(admitted_identity),
    token: str = Depends(bearer_token),
    relay: RelayService = Depends(get_relay_service),
) -> AskResponse:
    """Responde en PC1 la misma pregunta que el modo LOCAL respondería aquí."""
    params = _ask_params(domain, asset, payload)
    relay_request_id = uuid4()
    started = time.perf_counter()
    outcome = "cancelled"
    error: ApiError | None = None
    try:
        result = await _submit_until_disconnect(
            request, relay.submit(params, SecretStr(token), request_id=relay_request_id)
        )
        if result is None:
            outcome, error = (
                "client_disconnected",
                public_error_for(RelayFailure(ErrorCode.CANCELLED)),
            )
        elif isinstance(result, RelayFailure):
            outcome, error = result.code.value, public_error_for(result)
        else:
            try:
                answer = validate_node_result(
                    result.result, domain=params.domain, asset=params.asset
                )
            except ApiError as invalid:
                outcome, error = "invalid_response", invalid
            else:
                outcome = "ok"
                return answer
        raise error
    finally:
        _log_relayed(relay_request_id, outcome, error, started)


def _log_relayed(
    relay_request_id: UUID, outcome: str, error: ApiError | None, started: float
) -> None:
    """Un evento por pregunta: enlaza el ``request_id`` HTTP con el del relay."""
    extra: dict[str, object] = {
        "event": "assistant_relayed",
        "relay_request_id": str(relay_request_id),
        "outcome": outcome,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    if error is not None:
        extra["public_code"] = error.code
        extra["status_code"] = error.status_code
    elif outcome == "ok":
        extra["status_code"] = status.HTTP_200_OK
    _logger.info("assistant relayed", extra=extra)
