"""Almacenamiento privado sobre el sistema de archivos local (DEV).

Adaptador del puerto ``artifact_storage`` pensado para desarrollo y para la
prueba de aceptación privada. La raíz es configurable y debe estar **fuera
del repositorio**: los archivos que guarda son información interna de planta
y no pueden acabar en Git ni quedar expuestos por un servidor web.

Decisiones que el adaptador impone y no delega:

- **Escritura atómica.** Se escribe en un temporal del mismo directorio y se
  renombra con ``os.replace``. Un fallo a mitad de camino deja el temporal,
  nunca un artefacto truncado que después se leería como evidencia válida.
- **Sin sobrescritura.** El archivo definitivo se crea con ``O_EXCL``; si la
  clave ya existe, se rechaza. Dos subidas simultáneas del mismo contenido
  compiten en el sistema de archivos, no en una comprobación previa que
  ambas pasarían.
- **La clave no sale de su raíz.** Se valida antes de tocar el disco: una
  clave con ``..`` o absoluta se rechaza aunque el llamador se haya
  equivocado.

Las operaciones de disco se ejecutan en un hilo aparte
(``anyio.to_thread``) para no bloquear el bucle de eventos.
"""

import errno
import logging
import os
import tempfile
from pathlib import Path

import anyio.to_thread

from elsa.ports.artifact_storage import (
    ArtifactAlreadyExistsError,
    ArtifactNotFoundError,
    ArtifactStorageUnavailableError,
    StoredArtifact,
    sha256_hex,
)

_logger = logging.getLogger("elsa.storage.local")

# Permisos restrictivos: solo el usuario que corre el backend. La evidencia
# técnica no es legible para el resto de la máquina.
_DIRECTORY_MODE = 0o700
_FILE_MODE = 0o600


def _error_label(exc: OSError) -> str:
    """Nombre del error del sistema para el log, sin exponer la ruta."""
    if exc.errno is None:
        return type(exc).__name__
    return errno.errorcode.get(exc.errno, type(exc).__name__)


class LocalArtifactStorage:
    """Artefactos privados en un directorio del sistema de archivos."""

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).expanduser().resolve()

    @property
    def root(self) -> Path:
        return self._root

    # -----------------------------------------------------------------
    # Resolución segura de claves
    # -----------------------------------------------------------------

    def _resolve(self, key: str) -> Path:
        """Traduce una clave a una ruta dentro de la raíz, o falla.

        Se rechaza antes de tocar el disco todo lo que pudiera salir de la
        raíz: rutas absolutas, segmentos ``..``, separadores del sistema y
        bytes nulos.
        """
        if not key or key.startswith("/") or "\\" in key or "\x00" in key:
            raise ValueError(f"invalid artifact key: {key!r}")
        parts = key.split("/")
        if any(part in ("", ".", "..") for part in parts):
            raise ValueError(f"invalid artifact key: {key!r}")
        candidate = (self._root / key).resolve()
        # Defensa final: incluso si la validación anterior dejara pasar algo,
        # la ruta resuelta tiene que seguir colgando de la raíz.
        if candidate != self._root and self._root not in candidate.parents:
            raise ValueError(f"the artifact key escapes the storage root: {key!r}")
        return candidate

    # -----------------------------------------------------------------
    # Puerto
    # -----------------------------------------------------------------

    async def put(self, key: str, data: bytes) -> StoredArtifact:
        path = self._resolve(key)
        await anyio.to_thread.run_sync(self._write_atomically, path, data)
        return StoredArtifact(key=key, sha256=sha256_hex(data), byte_size=len(data))

    def _write_atomically(self, path: Path, data: bytes) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=_DIRECTORY_MODE)
        except OSError as exc:
            raise ArtifactStorageUnavailableError(
                "the artifact storage root is not writable"
            ) from exc

        # El temporal vive en el directorio de destino para que el renombrado
        # final sea atómico (mismo sistema de archivos).
        descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, _FILE_MODE)
            # `O_EXCL` sobre el destino: si otra escritura ganó la carrera,
            # esta falla en vez de reemplazar evidencia ya guardada.
            try:
                final = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, _FILE_MODE)
            except FileExistsError:
                raise ArtifactAlreadyExistsError(f"artifact already stored: {path.name}") from None
            os.close(final)
            os.replace(temporary, path)
        except (ArtifactAlreadyExistsError, ArtifactStorageUnavailableError):
            temporary.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            _logger.warning("artifact storage write failed", extra={"error": type(exc).__name__})
            raise ArtifactStorageUnavailableError("could not write the artifact") from None

    async def get(self, key: str) -> bytes:
        path = self._resolve(key)
        return await anyio.to_thread.run_sync(self._read, path)

    @staticmethod
    def _read(path: Path) -> bytes:
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise ArtifactNotFoundError(f"no artifact stored at {path.name}") from None
        except OSError as exc:
            _logger.warning("artifact storage read failed", extra={"error": type(exc).__name__})
            raise ArtifactStorageUnavailableError("could not read the artifact") from None

    async def exists(self, key: str) -> bool:
        path = self._resolve(key)
        return await anyio.to_thread.run_sync(path.is_file)

    async def check_health(self) -> None:
        await anyio.to_thread.run_sync(self._probe)

    def _probe(self) -> None:
        """Comprueba que la raíz existe y acepta escrituras."""
        try:
            self._root.mkdir(parents=True, exist_ok=True, mode=_DIRECTORY_MODE)
            probe = self._root / ".elsa-write-probe"
            descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
            os.close(descriptor)
            probe.unlink(missing_ok=True)
        except OSError as exc:
            # `EACCES`, `ENOSPC`, un montaje caído: todos significan lo mismo
            # para el llamador, que el almacenamiento no está operativo.
            _logger.warning(
                "artifact storage is not writable",
                extra={"error": _error_label(exc)},
            )
            raise ArtifactStorageUnavailableError(
                "the artifact storage root is not writable"
            ) from None
