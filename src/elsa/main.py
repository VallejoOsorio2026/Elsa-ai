"""Punto de entrada de la aplicación FastAPI.

Arranque local (patrón *factory*: la app se construye al arrancar, no al
importar el módulo)::

    uv run uvicorn elsa.main:create_app --factory --reload

La configuración se valida al crear la aplicación: si falta una variable
obligatoria, el proceso termina con un ``ConfigurationError`` legible antes
de aceptar tráfico.
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from elsa import __version__
from elsa.api.errors import register_error_handlers
from elsa.api.v1.health import router as health_router
from elsa.config import Environment, Settings, load_settings
from elsa.logging import RequestContextMiddleware, configure_logging

API_V1_PREFIX = "/api/v1"

_logger = logging.getLogger("elsa.main")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Construye la aplicación con su configuración validada.

    ``settings`` explícito existe para los tests; en producción se carga del
    ambiente (y de ``.env`` si está presente).
    """
    if settings is None:
        settings = load_settings()

    configure_logging("DEBUG" if settings.debug else settings.log_level)

    # La documentación interactiva solo se expone en DEV.
    is_dev = settings.env is Environment.DEV
    app = FastAPI(
        title="ELSA API",
        version=__version__,
        docs_url="/docs" if is_dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if is_dev else None,
    )
    app.state.settings = settings

    # CORS explícito por ambiente, sin comodines (CLAUDE.md, sección 6).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)
    app.include_router(health_router, prefix=API_V1_PREFIX)

    _logger.info("application configured", extra={"environment": settings.env.value})
    return app
