"""Almacenamiento privado de artefactos, local y en memoria.

Ambos adaptadores deben dar las mismas garantías, así que la mayoría de los
tests se ejecutan contra los dos.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest

from elsa.adapters.local_artifact_storage import LocalArtifactStorage
from elsa.adapters.memory_artifact_storage import InMemoryArtifactStorage
from elsa.ports.artifact_storage import (
    ArtifactAlreadyExistsError,
    ArtifactNotFoundError,
    ArtifactStoragePort,
    ArtifactStorageUnavailableError,
    sha256_hex,
    storage_key,
)

pytestmark = pytest.mark.anyio

KEY = storage_key("engineering_bom_xlsx", sha256_hex(b"contenido"))


@pytest.fixture(params=["local", "memory"])
def storage(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[ArtifactStoragePort]:
    if request.param == "local":
        yield LocalArtifactStorage(tmp_path / "artifacts")
    else:
        yield InMemoryArtifactStorage()


async def test_a_stored_artifact_can_be_read_back(storage: ArtifactStoragePort) -> None:
    stored = await storage.put(KEY, b"contenido")

    assert stored.sha256 == sha256_hex(b"contenido")
    assert stored.byte_size == 9
    assert await storage.get(KEY) == b"contenido"
    assert await storage.exists(KEY) is True


async def test_storing_over_an_existing_key_is_refused(storage: ArtifactStoragePort) -> None:
    """La evidencia no se reemplaza en silencio."""
    await storage.put(KEY, b"contenido")

    with pytest.raises(ArtifactAlreadyExistsError):
        await storage.put(KEY, b"otro contenido")

    assert await storage.get(KEY) == b"contenido"


async def test_reading_a_missing_artifact_fails_clearly(storage: ArtifactStoragePort) -> None:
    with pytest.raises(ArtifactNotFoundError):
        await storage.get(KEY)


@pytest.mark.parametrize(
    "key",
    ["", "/etc/passwd", "../escape", "a/../../b", "a//b", "back\\slash", "null\x00byte"],
)
async def test_keys_that_could_escape_the_root_are_refused(
    storage: ArtifactStoragePort, key: str
) -> None:
    with pytest.raises(ValueError):
        await storage.put(key, b"x")


async def test_the_key_is_derived_from_the_content_not_the_filename() -> None:
    """Un nombre hostil nunca llega al sistema de archivos."""
    digest = sha256_hex(b"x")

    key = storage_key("drawing_image", digest)

    assert key == f"drawing_image/{digest[:2]}/{digest}"


def test_a_malformed_digest_is_refused() -> None:
    with pytest.raises(ValueError):
        storage_key("drawing_image", "not-a-digest")


async def test_a_healthy_local_root_is_writable(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path / "created-on-demand")

    await storage.check_health()

    assert (tmp_path / "created-on-demand").is_dir()


async def test_an_unusable_local_root_reports_unavailable(tmp_path: Path) -> None:
    """Un almacenamiento caído se declara caído; no se finge éxito.

    La raíz se hace inservible apuntándola a un archivo normal en vez de a un
    directorio. Se prefiere a retirar permisos porque la suite puede correr
    como root, y root escribe igual sobre un directorio sin permisos: el test
    pasaría sin comprobar nada.
    """
    occupied = tmp_path / "soy-un-archivo"
    occupied.write_bytes(b"x")
    storage = LocalArtifactStorage(occupied / "inside")

    with pytest.raises(ArtifactStorageUnavailableError):
        await storage.check_health()


async def test_a_write_to_an_unusable_local_root_fails_instead_of_succeeding(
    tmp_path: Path,
) -> None:
    occupied = tmp_path / "soy-un-archivo"
    occupied.write_bytes(b"x")
    storage = LocalArtifactStorage(occupied / "inside")

    with pytest.raises(ArtifactStorageUnavailableError):
        await storage.put(KEY, b"contenido")


async def test_an_unavailable_memory_storage_reports_unavailable() -> None:
    storage = InMemoryArtifactStorage(available=False)

    with pytest.raises(ArtifactStorageUnavailableError):
        await storage.put(KEY, b"x")


async def test_the_local_adapter_leaves_no_partial_file_behind(tmp_path: Path) -> None:
    storage = LocalArtifactStorage(tmp_path)
    await storage.put(KEY, b"contenido")

    files = sorted(path.name for path in (tmp_path / KEY).parent.iterdir())

    assert files == [KEY.rsplit("/", 1)[1]]
