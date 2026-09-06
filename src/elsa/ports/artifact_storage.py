"""Puerto de almacenamiento privado de artefactos.

Los bytes de un archivo original —el XLSX aprobado por Ingeniería, el HTM
exportado de SAP— y los derivados que salen de él —las imágenes de plano
embebidas— **no viven en PostgreSQL ni en Git**. Viven detrás de este
puerto, y la base de datos guarda solo su metadato y su hash.

La separación existe por tres razones: los archivos son información interna
de planta que el repositorio (potencialmente público) nunca debe contener,
pesan más de lo que conviene mover en una fila, y el destino final —
sistema de archivos privado hoy, bucket privado de Supabase Storage
mañana— es una decisión que todavía no está tomada. Cambiarla debe afectar
a un adaptador, no a la ingesta.

Reglas que el puerto hace cumplibles:

- **La clave la genera el sistema.** El nombre que traía el archivo nunca es
  su identificador: puede venir con rutas, con caracteres hostiles o
  repetido.
- **Escribir no sobrescribe.** Guardar sobre una clave existente es un
  error explícito, no un reemplazo silencioso de evidencia.
- **Un fallo del almacenamiento no se disfraza de éxito.** Si el backend no
  responde, la operación falla con
  :class:`ArtifactStorageUnavailableError` y el llamador responde 503; el
  metadato nunca queda registrado como si el archivo estuviera guardado.
"""

import hashlib
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = [
    "ArtifactAlreadyExistsError",
    "ArtifactNotFoundError",
    "ArtifactStoragePort",
    "ArtifactStorageUnavailableError",
    "StoredArtifact",
    "sha256_hex",
    "storage_key",
]


class ArtifactStorageUnavailableError(Exception):
    """El almacenamiento privado no está disponible → 503."""


class ArtifactAlreadyExistsError(Exception):
    """Ya hay un artefacto bajo esa clave. Nunca se sobrescribe."""


class ArtifactNotFoundError(Exception):
    """No existe artefacto bajo esa clave."""


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Resultado de guardar un artefacto."""

    key: str
    sha256: str
    byte_size: int


def sha256_hex(data: bytes) -> str:
    """SHA-256 en hexadecimal minúsculo del contenido exacto recibido."""
    return hashlib.sha256(data).hexdigest()


def storage_key(prefix: str, digest: str) -> str:
    """Clave determinística y generada por el sistema.

    Se deriva del hash, no del nombre del archivo: el mismo contenido cae
    siempre en la misma clave (lo que hace idempotente reintentar una
    subida) y ningún nombre hostil llega jamás al sistema de archivos.

    Los dos primeros caracteres del hash forman un nivel intermedio para no
    dejar decenas de miles de entradas en un solo directorio.
    """
    if not digest or len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
        raise ValueError("the digest must be a lowercase hexadecimal SHA-256")
    if not prefix or not prefix.replace("_", "").replace("-", "").isalnum():
        raise ValueError("the prefix must be alphanumeric")
    return f"{prefix}/{digest[:2]}/{digest}"


@runtime_checkable
class ArtifactStoragePort(Protocol):
    """Almacenamiento privado de bytes, direccionado por clave."""

    async def put(self, key: str, data: bytes) -> StoredArtifact:
        """Guarda ``data`` bajo ``key`` de forma atómica.

        Lanza :class:`ArtifactAlreadyExistsError` si la clave ya existe: la
        evidencia no se reemplaza. Lanza
        :class:`ArtifactStorageUnavailableError` si el backend falla.
        """
        ...

    async def get(self, key: str) -> bytes:
        """Devuelve los bytes guardados, o lanza :class:`ArtifactNotFoundError`."""
        ...

    async def exists(self, key: str) -> bool:
        """Indica si la clave ya tiene contenido."""
        ...

    async def check_health(self) -> None:
        """Comprueba que el backend responde y es escribible.

        Lanza :class:`ArtifactStorageUnavailableError` si no lo está.
        """
        ...
