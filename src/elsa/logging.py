"""Logging estructurado en JSON con identificador de request.

El identificador viaja en un ``ContextVar`` que el middleware fija al inicio
de cada request, de modo que cualquier log emitido durante su atención lo
incluye automáticamente.

Política (ver ``docs/security.md``): los logs nunca contienen tokens,
secretos ni datos personales. Por eso la línea de acceso registra método,
ruta, estado y duración; nunca cabeceras, query strings ni cuerpos.
"""

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

# Formato aceptado para un request-id entrante; lo demás se descarta y se
# genera uno nuevo, para evitar valores arbitrarios en los logs.
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

# Atributos estándar de LogRecord que no se copian como campos extra.
_RESERVED_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_access_logger = logging.getLogger("elsa.access")


class JsonFormatter(logging.Formatter):
    """Serializa cada registro como una línea JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        if request_id is not None:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    """Configura el logger ``elsa`` con salida JSON a stderr.

    Es idempotente: reemplaza los handlers previos del logger para no
    duplicar líneas al recargar la aplicación.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("elsa")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Asigna un request-id a cada request y emite la línea de acceso.

    Acepta un ``X-Request-ID`` entrante si tiene formato válido (útil para
    trazar desde el frontend); si no, genera un UUID4. El identificador se
    devuelve siempre en la cabecera de la respuesta.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER, "")
        request_id = incoming if _REQUEST_ID_PATTERN.fullmatch(incoming) else str(uuid.uuid4())
        token = request_id_var.set(request_id)
        request.state.request_id = request_id
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            _access_logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)


def get_request_id(request: Request) -> str | None:
    """Devuelve el request-id fijado por el middleware, si existe."""
    return getattr(request.state, "request_id", None)
