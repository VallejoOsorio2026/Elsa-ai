"""Cliente de la ELSA local: ``assistant.ask`` y nada más (ADR 0032 §2.2).

La única llamada posible es ``POST /api/v1/assistant/{domain}/{asset}/ask``
contra la base loopback configurada. Render no aporta host, puerto, URL,
método, cabeceras ni ruta: solo los parámetros tipados del protocolo.

Ruta segura (ADR 0030, consecuencia 6). ``domain`` y ``asset`` no tienen
charset contractual y no se les impone uno. Se rechaza lo que cambiaría el
endpoint —``.``, ``..``, separadores ``/`` o ``\\``, caracteres de control,
también tras decodificar porcentajes—, cada valor se codifica como un único
segmento y se comprueba que la ruta que ``httpx`` va a enviar es exactamente
la construida.

Autenticación: el token temporal del usuario viaja en ``Authorization:
Bearer``, que es lo que lee ELSA (``deps.bearer_token``). La autoridad sigue
siendo ELSA: aquí no se interpreta el JWT.

Los errores se traducen a ``ErrorCode`` con un ``detail`` fijo de este
módulo. De la respuesta de ELSA solo se copia su ``error.code`` si está en una
lista blanca; nunca el cuerpo, una traza ni el texto de una excepción.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib.parse import quote, unquote

import httpx
from pydantic import JsonValue

from elsa.relay.protocol import ErrorCode, Request
from elsa.relay.service import MAX_RESPONSE_WIRE_BYTES

__all__ = [
    "ASK_PATH_PREFIX",
    "ElsaLocalClient",
    "LocalFailure",
    "LocalOutcome",
    "LocalSuccess",
    "UnsafePathSegmentError",
    "build_ask_path",
]

ASK_PATH_PREFIX = "/api/v1/assistant"
_ERROR_BODY_MAX_BYTES = 8 * 1024
_CONNECT_TIMEOUT_SECONDS = 2.0

_FORWARDED_LOCAL_CODES = frozenset(
    {
        "account_disabled",
        "asset_not_found",
        "attachments_too_large",
        "bad_request",
        "forbidden",
        "identity_provider_unavailable",
        "insufficient_permissions",
        "invalid_token",
        "knowledge_store_unavailable",
        "not_found",
        "payload_too_large",
        "service_unavailable",
        "too_many_attachments",
        "too_many_requests",
        "unauthorized",
        "validation_error",
    }
)
"""Códigos estables de ELSA que pueden viajar en ``detail`` como ``local:<code>``."""


class UnsafePathSegmentError(ValueError):
    """``domain`` o ``asset`` cambiaría el endpoint llamado."""


@dataclass(frozen=True)
class LocalSuccess:
    result: dict[str, JsonValue]


@dataclass(frozen=True)
class LocalFailure:
    code: ErrorCode
    detail: str


LocalOutcome = LocalSuccess | LocalFailure


def _is_unsafe(candidate: str) -> bool:
    if candidate in ("", ".", ".."):
        return True
    if "/" in candidate or "\\" in candidate:
        return True
    return any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in candidate)


def _check_segment(value: str) -> None:
    decoded = unquote(value)
    for candidate in (value, value.strip(), decoded, decoded.strip()):
        if _is_unsafe(candidate):
            raise UnsafePathSegmentError("unsafe path segment")


def build_ask_path(domain: str, asset: str) -> str:
    """Ruta fija de ``assistant.ask`` con ``domain`` y ``asset`` como un segmento cada uno."""
    _check_segment(domain)
    _check_segment(asset)
    return f"{ASK_PATH_PREFIX}/{quote(domain, safe='')}/{quote(asset, safe='')}/ask"


async def _read_capped(response: httpx.Response, limit: int) -> bytes | None:
    """Lee el cuerpo por trozos; ``None`` en cuanto supera ``limit``."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite number")


def _local_error_code(raw: bytes | None) -> str | None:
    if not raw:
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and code in _FORWARDED_LOCAL_CODES else None


def _failure_for_status(status: int, local_code: str | None) -> LocalFailure:
    def detail(default: str) -> str:
        return f"local:{local_code}" if local_code else f"local:{default}"

    if status in (400, 413, 422):
        return LocalFailure(ErrorCode.INVALID_REQUEST, detail("invalid_request"))
    if status == 404:
        return LocalFailure(ErrorCode.INVALID_REQUEST, detail("asset_not_found"))
    if status == 401:
        return LocalFailure(ErrorCode.UNAUTHORIZED, detail("unauthorized"))
    if status == 403:
        return LocalFailure(ErrorCode.FORBIDDEN, detail("forbidden"))
    if status == 429:
        return LocalFailure(ErrorCode.LOCAL_UNAVAILABLE, detail("too_many_requests"))
    if status == 503:
        return LocalFailure(ErrorCode.LOCAL_UNAVAILABLE, detail("unavailable"))
    return LocalFailure(ErrorCode.LOCAL_ERROR, "local:http_error")


def _parse_success(raw: bytes | None) -> LocalOutcome:
    if raw is None:
        return LocalFailure(ErrorCode.LOCAL_ERROR, "local:response_too_large")
    try:
        body = json.loads(raw, parse_constant=_reject_constant)
    except ValueError:
        return LocalFailure(ErrorCode.LOCAL_ERROR, "local:invalid_response")
    if not isinstance(body, dict):
        return LocalFailure(ErrorCode.LOCAL_ERROR, "local:invalid_response")
    return LocalSuccess(result=body)


class ElsaLocalClient:
    """Llama a ``assistant.ask`` en la ELSA local. Sin cabeceras por defecto."""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        # Sin proxy de entorno ni redirecciones: el tráfico no sale de loopback.
        self._http = httpx.AsyncClient(
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            timeout=httpx.Timeout(None, connect=_CONNECT_TIMEOUT_SECONDS),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _url(self, request: Request) -> httpx.URL:
        path = build_ask_path(request.params.domain, request.params.asset)
        url = httpx.URL(self._base_url + path)
        # Defensa en profundidad: si httpx normalizara la ruta, no se llama.
        if url.raw_path.decode("ascii") != path:
            raise UnsafePathSegmentError("the path was normalized")
        return url

    async def ask(self, request: Request, *, deadline: float) -> LocalOutcome:
        """Ejecuta la solicitud antes de ``deadline`` (reloj del bucle de eventos).

        ``asyncio.CancelledError`` se propaga: es la cancelación *best effort*.
        """
        try:
            url = self._url(request)
        except UnsafePathSegmentError:
            return LocalFailure(ErrorCode.INVALID_REQUEST, "agent:invalid_path_segment")
        params = request.params
        body = json.dumps(
            {
                "question": params.question,
                "attachments": [item.model_dump(mode="json") for item in params.attachments],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {request.user_access_token.get_secret_value()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Request-ID": str(request.request_id),
        }
        try:
            async with asyncio.timeout_at(deadline):
                async with self._http.stream("POST", url, content=body, headers=headers) as resp:
                    if resp.status_code == 200:
                        return _parse_success(await _read_capped(resp, MAX_RESPONSE_WIRE_BYTES))
                    raw = await _read_capped(resp, _ERROR_BODY_MAX_BYTES)
                    return _failure_for_status(resp.status_code, _local_error_code(raw))
        except TimeoutError:
            return LocalFailure(ErrorCode.TIMEOUT, "local:timeout")
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return LocalFailure(ErrorCode.LOCAL_UNAVAILABLE, "local:unreachable")
        except httpx.TimeoutException:
            return LocalFailure(ErrorCode.TIMEOUT, "local:timeout")
        except httpx.TransportError:
            return LocalFailure(ErrorCode.LOCAL_ERROR, "local:transport_error")
        finally:
            del headers
