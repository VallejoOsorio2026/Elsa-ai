"""Formato de error estándar de la API.

Toda respuesta de error tiene la forma::

    {
        "error": {
            "code": "not_found",
            "message": "...",
            "request_id": "...",
            "details": [...]        # opcional (errores de validación)
        }
    }

Nunca se filtran trazas internas al cliente: los errores no controlados se
registran con su traza en el log del servidor y devuelven un mensaje
genérico.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

from elsa.logging import REQUEST_ID_HEADER, get_request_id

_logger = logging.getLogger("elsa.api.errors")

_CODE_BY_STATUS = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_401_UNAUTHORIZED: "unauthorized",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_409_CONFLICT: "conflict",
    status.HTTP_422_UNPROCESSABLE_CONTENT: "validation_error",
    status.HTTP_429_TOO_MANY_REQUESTS: "too_many_requests",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "internal_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "service_unavailable",
}


class ErrorDetail(BaseModel):
    """Detalle puntual de un error de validación (seguro para el cliente)."""

    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    """Envoltura estándar de todos los errores de la API."""

    error: ErrorBody


def error_response(
    request: Request,
    status_code: int,
    message: str,
    *,
    code: str | None = None,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    """Construye una respuesta de error en el formato estándar."""
    request_id = get_request_id(request)
    body = ErrorResponse(
        error=ErrorBody(
            code=code or _CODE_BY_STATUS.get(status_code, f"http_{status_code}"),
            message=message,
            request_id=request_id,
            details=details,
        )
    )
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Registra los manejadores que imponen el formato estándar."""

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(request, exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            ErrorDetail(
                field=".".join(str(part) for part in error.get("loc", ())),
                message=str(error.get("msg", "invalid value")),
            )
            for error in exc.errors()
        ]
        return error_response(
            request,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Request validation failed.",
            details=details,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        _logger.exception(
            "unhandled error",
            extra={"request_id": get_request_id(request), "path": request.url.path},
        )
        return error_response(
            request,
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "An internal error occurred.",
        )
