"""Comparación entre una versión del BOM y la anterior.

Cuando llega una versión nueva no todo cambió. Revalidar de cero cada
renglón obligaría al Revisor Técnico a repetir un trabajo ya hecho, y esa es
la clase de fricción que termina con la gente aprobando en bloque sin mirar.
Pero conservar una validación de un dato que sí cambió es peor: convertiría
una aprobación real en una aprobación falsa.

Este módulo traza esa línea de forma determinística. Cada renglón se
clasifica como:

- ``new``: no estaba en la versión publicada → requiere validación.
- ``modified``: estaba, y algún dato significativo cambió → **la validación
  anterior queda histórica** y el dato vuelve a revisión.
- ``unchanged``: estaba y no cambió nada significativo → la validación
  anterior puede heredarse, dejando constancia de que fue heredada.
- ``retired``: estaba y ya no está → se conserva la historia; ni el
  componente ni su evidencia se borran.

Qué cuenta como «dato significativo» lo decide la huella
(:func:`fingerprint`): si dos renglones producen la misma huella, son el
mismo dato a efectos de validación.
"""

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

__all__ = ["ChangeKind", "VersionDiff", "VersionedItem", "classify_versions", "fingerprint"]


class ChangeKind(StrEnum):
    """Cómo cambió un renglón respecto de la versión publicada.

    Coincide con ``ck_bom_item_change_kind`` de la migración.
    """

    NEW = "new"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"
    RETIRED = "retired"


def _canonical(value: object) -> str:
    """Representación estable de un valor para la huella."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        # `2` y `2.00` son la misma cantidad; normalizar evita que un cambio
        # de formato en la hoja se lea como un cambio técnico.
        return str(value.normalize())
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def fingerprint(values: Mapping[str, object]) -> str:
    """Huella determinística de los campos significativos de un renglón.

    Las claves se ordenan para que la huella no dependa del orden en que se
    construyó el diccionario, y los valores se separan con caracteres que no
    pueden aparecer en el contenido, para que dos combinaciones distintas no
    produzcan la misma cadena.
    """
    payload = "\x1f".join(f"{key}\x1e{_canonical(values[key])}" for key in sorted(values))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class VersionedItem:
    """Un renglón reducido a lo que hace falta para compararlo.

    ``key`` es la identidad estable del renglón entre versiones: el UUID del
    componente cuando se pudo emparejar. Un renglón sin componente resuelto
    no tiene identidad estable y, por definición, se trata como nuevo.
    """

    key: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class VersionDiff:
    """Resultado de comparar la versión entrante con la publicada."""

    changes: Mapping[str, ChangeKind]
    """Clasificación de cada renglón de la versión entrante, por ``key``."""

    retired: tuple[str, ...]
    """Renglones de la versión publicada que ya no aparecen."""

    @property
    def requires_review(self) -> tuple[str, ...]:
        """Renglones que un revisor tiene que mirar sí o sí."""
        return tuple(
            sorted(
                key
                for key, kind in self.changes.items()
                if kind in (ChangeKind.NEW, ChangeKind.MODIFIED)
            )
        )

    @property
    def inheritable(self) -> tuple[str, ...]:
        """Renglones cuya validación anterior puede reutilizarse."""
        return tuple(
            sorted(key for key, kind in self.changes.items() if kind is ChangeKind.UNCHANGED)
        )

    def counts(self) -> dict[str, int]:
        """Conteos por clasificación, aptos para ``imports.stats``."""
        totals = {kind.value: 0 for kind in ChangeKind}
        for kind in self.changes.values():
            totals[kind.value] += 1
        totals[ChangeKind.RETIRED.value] = len(self.retired)
        return totals


def classify_versions(
    previous: Sequence[VersionedItem] | Iterable[VersionedItem],
    current: Sequence[VersionedItem] | Iterable[VersionedItem],
) -> VersionDiff:
    """Clasifica los renglones entrantes contra los de la versión publicada.

    Sin versión anterior todo es ``new``: es exactamente lo que ocurre con la
    primera versión de un activo.
    """
    before = {item.key: item.fingerprint for item in previous}
    after = {item.key: item.fingerprint for item in current}

    changes: dict[str, ChangeKind] = {}
    for key, current_fingerprint in after.items():
        previous_fingerprint = before.get(key)
        if previous_fingerprint is None:
            changes[key] = ChangeKind.NEW
        elif previous_fingerprint == current_fingerprint:
            changes[key] = ChangeKind.UNCHANGED
        else:
            changes[key] = ChangeKind.MODIFIED

    retired = tuple(sorted(key for key in before if key not in after))
    return VersionDiff(changes=changes, retired=retired)
