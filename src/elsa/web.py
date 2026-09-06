"""Servido de la interfaz web del piloto.

El piloto **no tiene proceso de compilación**: son archivos estáticos que el
propio backend publica. Esa decisión es deliberada — el criterio de
aceptación del proyecto es que un clon limpio levante el servidor siguiendo
solo el README, y una cadena de build de JavaScript añadiría un requisito
más a una máquina de planta.

Se publican exactamente dos árboles, ambos de solo lectura:

- ``web/`` — la aplicación (HTML, CSS, JS).
- ``assets/brand/`` — el logotipo PAPELSA, en ``/brand``.

Nada más. El resto del repositorio (``.env``, migraciones, código) queda
fuera del alcance del servidor de archivos.
"""

import logging
from pathlib import Path

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

_logger = logging.getLogger("elsa.web")

# src/elsa/web.py -> src/elsa -> src -> raíz del repositorio
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

WEB_ROOT = _PROJECT_ROOT / "web"
BRAND_ROOT = _PROJECT_ROOT / "assets" / "brand"


def mount_web_ui(app: FastAPI) -> bool:
    """Publica la interfaz estática. Devuelve si quedó montada.

    Se llama **después** de registrar los routers: Starlette resuelve las
    rutas en orden, así que ``/api/...`` se atiende antes de que el montaje
    de la raíz vea la petición.
    """
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

    app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")
    _logger.info("web UI mounted", extra={"path": str(WEB_ROOT)})
    return True
