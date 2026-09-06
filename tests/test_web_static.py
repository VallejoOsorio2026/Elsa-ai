"""La interfaz se sirve desde el backend sin exponer el repositorio."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from elsa.container import Container
from elsa.main import create_app
from elsa.web import BRAND_ROOT, WEB_ROOT
from tests.conftest import make_test_settings


def test_the_interface_is_served_under_its_own_prefix(client: TestClient) -> None:
    response = client.get("/app/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ELSA" in response.text


def test_the_bare_address_redirects_to_the_interface(client: TestClient) -> None:
    response = client.get("/", follow_redirects=False)
    assert response.status_code in {307, 308}
    assert response.headers["location"] == "/app/"


def test_the_api_is_never_shadowed_by_the_static_mount(client: TestClient) -> None:
    assert client.get("/api/v1/session/context").status_code == 200
    assert client.get("/api/v1/health/live").status_code == 200


def test_a_route_added_after_startup_is_still_reachable(app: FastAPI) -> None:
    """La razón de montar en `/app` y no en `/`.

    Un montaje en la raíz atrapa todo lo que no se registró antes que él, así
    que un endpoint añadido después quedaría muerto en silencio. Este test
    fija esa garantía para quien continúe el proyecto.
    """

    @app.get("/api/v1/_late")
    async def _late() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        assert client.get("/api/v1/_late").status_code == 200


def test_the_brand_assets_are_published(client: TestClient) -> None:
    response = client.get("/brand/papelsa-logotipo-color.svg")
    assert response.status_code == 200
    assert "svg" in response.headers["content-type"]
    # Los colores del manual llegan intactos al navegador.
    assert "#006975" in response.text
    assert "#A9C23F" in response.text


def test_every_brand_asset_referenced_by_the_interface_exists() -> None:
    """Un logotipo roto incumple el manual en silencio; mejor que falle aquí."""
    for name in (
        "papelsa-logotipo-color.svg",
        "papelsa-logotipo-blanco.svg",
        "papelsa-simbolo-color.svg",
    ):
        assert (BRAND_ROOT / name).is_file(), name


def test_repository_files_are_not_reachable(client: TestClient) -> None:
    """Solo se publican `web/` y `assets/brand/`. Nada más."""
    for path in (
        "/CLAUDE.md",
        "/.env",
        "/pyproject.toml",
        "/app/../CLAUDE.md",
        "/app/../../etc/passwd",
    ):
        assert client.get(path).status_code == 404, path


def test_path_traversal_is_refused(client: TestClient) -> None:
    response = client.get("/brand/../../CLAUDE.md")
    assert response.status_code in {307, 400, 404}
    assert "CLAUDE.md" not in response.text


def test_the_interface_can_be_switched_off() -> None:
    settings = make_test_settings(web_ui_enabled=False)
    app = create_app(settings, Container(settings))
    with TestClient(app) as client:
        assert client.get("/app/").status_code == 404
        assert client.get("/", follow_redirects=False).status_code == 404
        assert client.get("/api/v1/session/context").status_code == 200


def test_the_web_root_is_inside_the_repository() -> None:
    assert WEB_ROOT.name == "web"
    assert (WEB_ROOT / "index.html").is_file()
