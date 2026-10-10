"""Cliente HTTPS del relay de Render: register, poll y result (ADR 0031/0032).

Solo sabe hablar las tres rutas de nodo de D2.2 con mensajes del protocolo
V1. No decide nada: clasifica cada respuesta en un :class:`RelayOutcome` y el
agente actúa en consecuencia.

- La credencial del nodo viaja **solo** en la cabecera ``X-Elsa-Node-Token``.
  Nunca va en la URL ni en el cuerpo, y este cliente nunca envía
  ``Authorization`` (el token del usuario no sale hacia Render).
- Sin redirecciones (se llevarían la cabecera del nodo) ni proxy de entorno.
- Los cuerpos se serializan aquí, compactos y en UTF-8 sin escapar: lo que
  el relay mide (ADR 0031 §4) es exactamente lo que se envía.
- Las respuestas se leen **por trozos y con tope**. Una respuesta ilegible
  (gzip roto, JSON anidado sin fin, números absurdos) se clasifica como
  fallo transitorio: nunca tumba ni cuelga al agente.
- Lo que llega por poll entra por ``parse_message`` y se exige que sea un
  ``Request`` o un ``Cancel`` del nodo y de la sesión vigentes; cualquier
  otra cosa se descarta sin ejecutarla ni responderla.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from elsa.relay.auth import NODE_TOKEN_HEADER
from elsa.relay.protocol import (
    Cancel,
    Heartbeat,
    ProtocolModel,
    Register,
    Request,
    parse_message,
)

__all__ = [
    "NODE_ROUTE_PREFIX",
    "PollReply",
    "RegisterReply",
    "RelayClient",
    "RelayOutcome",
    "encode_message",
]

NODE_ROUTE_PREFIX = "/api/v1/relay/node"
COMPRESSED_BODY = "compressed_body"
"""Error de diagnóstico: el relay (o un proxy) respondió comprimido pese a
``Accept-Encoding: identity``. El cuerpo se rechaza sin leerlo."""
INVALID_BODY = "invalid_body"
"""Error de diagnóstico: cuerpo sin comprimir pero ilegible o fuera de contrato."""

_logger = logging.getLogger("elsa.agent.relay")
_POLL_BODY_MAX_BYTES = 32 * 1024
"""Un ``REQUEST`` cabe en 16 KiB (ADR 0031 §4) más la envoltura."""
_CONTROL_BODY_MAX_BYTES = 4 * 1024
_CONTROL_TIMEOUT_SECONDS = 10.0


class RelayOutcome(StrEnum):
    OK = "ok"
    STALE = "stale_session"
    """La sesión no es la vigente: hay que registrar una nueva."""
    NOT_PENDING = "request_not_pending"
    """``/result``: ya aceptado (ACK perdido), expirado o cancelado."""
    AUTH = "auth_failed"
    """401/403: la credencial del nodo no vale. Fatal."""
    NOT_FOUND = "not_found"
    """404: relay deshabilitado o URL equivocada. Fatal."""
    PROTOCOL = "protocol_rejected"
    """413/422 u otro 4xx: desajuste de protocolo o de tamaño."""
    TRANSIENT = "transient"
    """Red, timeout, 5xx, 429 o respuesta ilegible: se reintenta con espera."""


@dataclass(frozen=True)
class RegisterReply:
    outcome: RelayOutcome
    http_status: int | None = None
    error: str | None = None
    long_poll_seconds: float | None = None


@dataclass(frozen=True)
class PollReply:
    outcome: RelayOutcome
    http_status: int | None = None
    error: str | None = None
    message: Request | Cancel | None = None
    discarded: bool = False
    """Llegó algo, pero no era un mensaje válido para este nodo y esta sesión."""


def encode_message(message: ProtocolModel) -> bytes:
    """Cuerpo del cable de un mensaje que **no** lleva el token del usuario."""
    return json.dumps(
        message.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _error_code(raw: bytes | None) -> str | None:
    if not raw:
        return None
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else None


def _classify(status: int, raw: bytes | None) -> RelayOutcome:
    if status == 200:
        return RelayOutcome.OK
    if status == 409:
        code = _error_code(raw)
        if code == RelayOutcome.STALE.value:
            return RelayOutcome.STALE
        if code == RelayOutcome.NOT_PENDING.value:
            return RelayOutcome.NOT_PENDING
        return RelayOutcome.PROTOCOL
    if status in (401, 403):
        return RelayOutcome.AUTH
    if status == 404:
        return RelayOutcome.NOT_FOUND
    if status == 429 or status >= 500:
        return RelayOutcome.TRANSIENT
    return RelayOutcome.PROTOCOL


def _is_compressed(response: httpx.Response) -> bool:
    encoding = response.headers.get("content-encoding", "identity").strip().lower()
    return encoding not in ("", "identity")


async def _read_capped(response: httpx.Response, limit: int) -> bytes | None:
    """Lee el cuerpo, ya sin comprimir, con tope; ``None`` si lo supera."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _json_object(raw: bytes | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    return body if isinstance(body, dict) else None


def _finite_seconds(value: object) -> float | None:
    """Un número de segundos finito y positivo, o ``None``. Nunca lanza."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        seconds = float(value)
    except OverflowError:
        return None
    return seconds if math.isfinite(seconds) and seconds > 0 else None


class RelayClient:
    def __init__(
        self,
        base_url: str,
        node_token: SecretStr,
        *,
        poll_timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") + NODE_ROUTE_PREFIX
        self._node_token = node_token
        self._poll_timeout = httpx.Timeout(poll_timeout_seconds, connect=_CONTROL_TIMEOUT_SECONDS)
        self._http = httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(_CONTROL_TIMEOUT_SECONDS),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(
        self,
        endpoint: str,
        body: bytes,
        limit: int,
        timeout: httpx.Timeout | None = None,
    ) -> tuple[int | None, bytes | None, str | None]:
        """``(estado, cuerpo o None, error de diagnóstico)``.

        Se pide ``Accept-Encoding: identity`` y un cuerpo comprimido se rechaza
        **antes** de leerlo: lo que se lee son los bytes del cable y el tope no
        puede burlarse con una bomba gzip. El rechazo se registra con el estado
        HTTP y el código ``compressed_body``; nunca el cuerpo ni las cabeceras.
        """
        headers = {
            NODE_TOKEN_HEADER: self._node_token.get_secret_value(),
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        try:
            async with self._http.stream(
                "POST",
                f"{self._base_url}/{endpoint}",
                content=body,
                headers=headers,
                timeout=timeout or httpx.USE_CLIENT_DEFAULT,
            ) as response:
                if _is_compressed(response):
                    _logger.warning(
                        "relay_body_rejected",
                        extra={
                            "event": "relay_body_rejected",
                            "endpoint": endpoint,
                            "http_status": response.status_code,
                            "error_code": COMPRESSED_BODY,
                        },
                    )
                    return response.status_code, None, COMPRESSED_BODY
                return response.status_code, await _read_capped(response, limit), None
        except httpx.HTTPError as exc:
            # Red, timeout, o cuerpo ilegible (``DecodingError``). Solo el tipo:
            # el texto de la excepción no se registra ni se propaga.
            return None, None, type(exc).__name__
        finally:
            del headers

    async def register(self, message: Register) -> RegisterReply:
        status, raw, error = await self._post(
            "register", encode_message(message), _CONTROL_BODY_MAX_BYTES
        )
        if status is None:
            return RegisterReply(RelayOutcome.TRANSIENT, error=error)
        outcome = _classify(status, raw)
        if outcome is not RelayOutcome.OK:
            return RegisterReply(outcome, http_status=status, error=error)
        body = _json_object(raw)
        return RegisterReply(
            RelayOutcome.OK,
            http_status=status,
            long_poll_seconds=_finite_seconds(body.get("long_poll_seconds") if body else None),
        )

    async def poll(self, message: Heartbeat) -> PollReply:
        status, raw, error = await self._post(
            "poll", encode_message(message), _POLL_BODY_MAX_BYTES, self._poll_timeout
        )
        if status is None:
            return PollReply(RelayOutcome.TRANSIENT, error=error)
        outcome = _classify(status, raw)
        if outcome is not RelayOutcome.OK:
            return PollReply(outcome, http_status=status, error=error)
        body = _json_object(raw)
        if body is None or "message" not in body:
            return PollReply(
                RelayOutcome.TRANSIENT, http_status=status, error=error or INVALID_BODY
            )
        payload = body["message"]
        if payload is None:
            return PollReply(RelayOutcome.OK, http_status=status)
        try:
            parsed = parse_message(json.dumps(payload))
        except (ValidationError, TypeError, ValueError, RecursionError):
            return PollReply(RelayOutcome.OK, http_status=status, discarded=True)
        if (
            not isinstance(parsed, Request | Cancel)
            or parsed.node_id != message.node_id
            or parsed.node_session_id != message.node_session_id
        ):
            return PollReply(RelayOutcome.OK, http_status=status, discarded=True)
        return PollReply(RelayOutcome.OK, http_status=status, message=parsed)

    async def send_result(self, body: bytes) -> RelayOutcome:
        """Envía un ``Response``/``ErrorMessage`` ya serializado (ver :func:`encode_message`)."""
        status, raw, _ = await self._post("result", body, _CONTROL_BODY_MAX_BYTES)
        if status is None:
            return RelayOutcome.TRANSIENT
        return _classify(status, raw)
