"""Modelo de salud del sistema.

Hace cumplible la regla 14 de CLAUDE.md ("el sistema funciona parcialmente
cuando el LLM está fuera de servicio"): cada dependencia reporta su estado
por separado y el estado global distingue *degradado* (dependencias no
críticas ausentes o caídas) de *caído* (una dependencia crítica caída).

Quién reporta qué lo decide el *composition root*
(:meth:`elsa.container.Container.health_reports`); aquí solo viven los tipos
y la regla de agregación.
"""

from dataclasses import dataclass
from enum import StrEnum


class DependencyStatus(StrEnum):
    """Estado individual de una dependencia externa."""

    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"
    NOT_CONFIGURED = "not_configured"


class SystemStatus(StrEnum):
    """Estado agregado del sistema."""

    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass(frozen=True, slots=True)
class DependencyReport:
    """Estado de una dependencia, con su criticidad."""

    name: str
    status: DependencyStatus
    critical: bool
    detail: str | None = None


def aggregate(reports: tuple[DependencyReport, ...]) -> SystemStatus:
    """Agrega estados individuales al estado global.

    Solo una dependencia crítica *caída* tumba el sistema. Una dependencia
    no configurada (situación esperada mientras no exista su adaptador real)
    degrada el sistema pero no lo tumba.
    """
    if any(report.critical and report.status is DependencyStatus.DOWN for report in reports):
        return SystemStatus.DOWN
    if any(report.status is not DependencyStatus.OK for report in reports):
        return SystemStatus.DEGRADED
    return SystemStatus.OK
