"""Almacenamiento de artefactos en memoria.

Adaptador determinista del puerto ``artifact_storage`` para los tests y para
un arranque en DEV sin tocar el disco. No persiste nada: al terminar el
proceso, los artefactos desaparecen.

Reproduce exactamente las garantías que la ingesta espera del puerto —no
sobrescribe, valida la clave, sabe fallar— para que un test que pasa aquí
signifique algo sobre el adaptador real.
"""

from elsa.ports.artifact_storage import (
    ArtifactAlreadyExistsError,
    ArtifactNotFoundError,
    ArtifactStorageUnavailableError,
    StoredArtifact,
    sha256_hex,
)


class InMemoryArtifactStorage:
    """Artefactos privados en un diccionario en memoria."""

    def __init__(self, *, available: bool = True) -> None:
        self._items: dict[str, bytes] = {}
        # Permite a los tests comprobar que un almacenamiento caído produce
        # 503 y no un éxito fingido.
        self.available = available

    def _check_available(self) -> None:
        if not self.available:
            raise ArtifactStorageUnavailableError("the artifact storage is unavailable")

    @staticmethod
    def _validate(key: str) -> str:
        if not key or key.startswith("/") or "\\" in key or "\x00" in key:
            raise ValueError(f"invalid artifact key: {key!r}")
        if any(part in ("", ".", "..") for part in key.split("/")):
            raise ValueError(f"invalid artifact key: {key!r}")
        return key

    async def put(self, key: str, data: bytes) -> StoredArtifact:
        self._check_available()
        self._validate(key)
        if key in self._items:
            raise ArtifactAlreadyExistsError(f"artifact already stored: {key}")
        self._items[key] = data
        return StoredArtifact(key=key, sha256=sha256_hex(data), byte_size=len(data))

    async def get(self, key: str) -> bytes:
        self._check_available()
        self._validate(key)
        try:
            return self._items[key]
        except KeyError:
            raise ArtifactNotFoundError(f"no artifact stored at {key}") from None

    async def exists(self, key: str) -> bool:
        self._check_available()
        return self._validate(key) in self._items

    async def check_health(self) -> None:
        self._check_available()
