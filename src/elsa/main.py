"""Punto de entrada de la aplicación FastAPI.

Arranque local (patrón *factory*: la app se construye al arrancar, no al
importar el módulo)::

    uv run uvicorn elsa.main:create_app --factory --reload

La configuración se valida al crear la aplicación: si falta una variable
obligatoria, el proceso termina con un ``ConfigurationError`` legible antes
de aceptar tráfico. Los adaptadores concretos se eligen en
:class:`elsa.container.Container`, único lugar donde se decide qué
implementa cada puerto.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from elsa import __version__
from elsa.api.errors import register_error_handlers
from elsa.api.v1.access import router as access_router
from elsa.api.v1.admin import router as admin_router
from elsa.api.v1.assistant import router as assistant_router
from elsa.api.v1.health import router as health_router
from elsa.api.v1.knowledge import router as knowledge_router
from elsa.api.v1.me import router as me_router
from elsa.api.v1.session import router as session_router
from elsa.api.v1.technical import router as technical_router
from elsa.config import Environment, Settings, load_settings
from elsa.container import Container
from elsa.demo.seed import seed_demo_data
from elsa.logging import RequestContextMiddleware, configure_logging
from elsa.web import mount_web_ui

API_V1_PREFIX = "/api/v1"

_logger = logging.getLogger("elsa.main")


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """Construye la aplicación con su configuración validada.

    ``settings`` y ``container`` explícitos existen para los tests; en
    producción se cargan del ambiente (y de ``.env`` si está presente).
    """
    if settings is None:
        settings = load_settings()

    configure_logging("DEBUG" if settings.debug else settings.log_level)

    resolved_container = container if container is not None else Container(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await resolved_container.start()
        await seed_demo_data(
            permissions=resolved_container.permissions,
            knowledge=resolved_container.knowledge,
            materials_identity=resolved_container.materials_identity,
            settings=settings,
        )
        try:
            yield
        finally:
            await resolved_container.aclose()

    # La documentación interactiva solo se expone en DEV.
    is_dev = settings.env is Environment.DEV
    app = FastAPI(
        title="ELSA API",
        version=__version__,
        docs_url="/docs" if is_dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if is_dev else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.container = resolved_container

    # CORS explícito por ambiente, sin comodines (CLAUDE.md, sección 6).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Bootstrap-Token"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_error_handlers(app)
    app.include_router(health_router, prefix=API_V1_PREFIX)
    app.include_router(me_router, prefix=API_V1_PREFIX)
    app.include_router(access_router, prefix=API_V1_PREFIX)
    app.include_router(admin_router, prefix=API_V1_PREFIX)
    app.include_router(knowledge_router, prefix=API_V1_PREFIX)
    app.include_router(technical_router, prefix=API_V1_PREFIX)
    app.include_router(session_router, prefix=API_V1_PREFIX)
    app.include_router(assistant_router, prefix=API_V1_PREFIX)

    # El montaje estático va al final a propósito: Starlette resuelve las
    # rutas en orden y el montaje de la raíz atrapa todo lo que llegue sin
    # dueño. Registrado antes, se tragaría la API.
    if settings.web_ui_enabled:
        mount_web_ui(app)

    _logger.info(
        "application configured",
        extra={
            "environment": settings.env.value,
            "auth_provider": settings.auth_provider.value,
            "permissions_backend": settings.permissions_backend.value,
        },
    )
    return app
