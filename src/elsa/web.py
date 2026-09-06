"""Servido de la interfaz web del piloto.

El piloto **no tiene proceso de compilación**: son archivos estáticos que el
propio backend publica. Esa decisión es deliberada — el criterio de
aceptación del proyecto es que un clon limpio levante el servidor siguiendo
solo el README, y una cadena de build de JavaScript añadiría un requisito
más a una máquina de planta.

Se publican exactamente dos árboles, ambos de solo lectura:

- ``web/`` en ``/app`` — la aplicación (HTML, CSS, JS).
- ``assets/brand/`` en ``/brand`` — el logotipo PAPELSA.

Nada más. El resto del repositorio (``.env``, migraciones, código) queda
fuera del alcance del servidor de archivos.

**Por qué ``/app`` y no la raíz.** Un montaje en ``/`` atrapa toda ruta que
no haya sido registrada *antes* que él, así que cualquier endpoint añadido
después de construir la aplicación quedaría muerto sin previo aviso —un
fallo silencioso que aparecería en un bloque futuro y costaría encontrar.
Montar en un prefijo propio elimina esa dependencia del orden: la API nunca
puede quedar tapada. La raíz sigue funcionando para quien escriba la
dirección a secas: redirige a ``/app/``.
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

_logger = logging.getLogger("elsa.web")

# src/elsa/web.py -> src/elsa -> src -> raíz del repositorio
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

WEB_ROOT = _PROJECT_ROOT / "web"
BRAND_ROOT = _PROJECT_ROOT / "assets" / "brand"

UI_PREFIX = "/app"


def mount_web_ui(app: FastAPI) -> bool:
    """Publica la interfaz estática. Devuelve si quedó montada."""
    if not WEB_ROOT.is_dir():
        _logger.warning(
            "web UI not mounted: directory not found",
            extra={"path": str(WEB_ROOT)},
        )
        return False

    if BRAND_ROOT.is_dir():
        app.mount("/brand", StaticFiles(directory=BRAND_ROOT), name="brand")
    else:
        # Sin logotipo la interfaz sigue siendo utilizable, pero deja de
        # cumplir el manual de marca: se avisa en vez de fallar en silencio.
        _logger.warning(
            "brand assets not found; the interface will render without the logo",
            extra={"path": str(BRAND_ROOT)},
        )

    app.mount(UI_PREFIX, StaticFiles(directory=WEB_ROOT, html=True), name="web")

    @app.get("/", include_in_schema=False)
    async def _root() -> RedirectResponse:
        """La dirección a secas lleva a la aplicación."""
        return RedirectResponse(url=f"{UI_PREFIX}/")

    _logger.info("web UI mounted", extra={"path": str(WEB_ROOT), "prefix": UI_PREFIX})
    return True
