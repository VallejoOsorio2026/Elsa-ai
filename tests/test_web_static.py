"""La interfaz se sirve desde el backend sin exponer el repositorio."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from elsa import web as elsa_web
from elsa.container import Container
from elsa.main import create_app
from elsa.web import brand_root, web_root
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
    brand = brand_root()
    assert brand is not None
    for name in (
        "papelsa-logotipo-color.svg",
        "papelsa-logotipo-blanco.svg",
        "papelsa-simbolo-color.svg",
    ):
        assert (brand / name).is_file(), name


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
    root = web_root()
    assert root is not None
    assert root.name == "web"
    assert (root / "index.html").is_file()


def test_the_interface_is_found_from_the_working_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Segunda vía de búsqueda, la que salva el despliegue.

    Si el paquete se instalara copiado en `site-packages` en vez de en modo
    editable, la ruta relativa al paquete apuntaría dentro del entorno
    virtual y la interfaz desaparecería sin que nada fallara. Buscar también
    bajo el directorio de trabajo lo evita.
    """
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "index.html").write_text("<p>demo</p>", encoding="utf-8")
    (tmp_path / "assets" / "brand").mkdir(parents=True)

    monkeypatch.setattr(elsa_web, "_PACKAGE_ROOT", tmp_path / "no-existe")
    monkeypatch.chdir(tmp_path)

    assert elsa_web.web_root() == tmp_path / "web"
    assert elsa_web.brand_root() == tmp_path / "assets" / "brand"


def test_a_missing_interface_is_reported_not_guessed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(elsa_web, "_PACKAGE_ROOT", tmp_path / "no-existe")
    monkeypatch.chdir(tmp_path)
    assert elsa_web.web_root() is None

    settings = make_test_settings()
    app = create_app(settings, Container(settings))
    with TestClient(app) as client:
        # La API sigue en pie aunque la interfaz no esté.
        assert client.get("/api/v1/health/live").status_code == 200
        assert client.get("/app/").status_code == 404
