"""Tests de la agregación de salud (regla 14: degradado, no caído)."""

from elsa.core.health import (
    DependencyReport,
    DependencyStatus,
    SystemStatus,
    aggregate,
)


def _report(name: str, status: DependencyStatus, *, critical: bool) -> DependencyReport:
    return DependencyReport(name=name, status=status, critical=critical)


def test_all_ok_is_ok() -> None:
    reports = (
        _report("database", DependencyStatus.OK, critical=True),
        _report("llm", DependencyStatus.OK, critical=False),
    )
    assert aggregate(reports) is SystemStatus.OK


def test_non_critical_down_degrades_but_does_not_take_system_down() -> None:
    reports = (
        _report("database", DependencyStatus.OK, critical=True),
        _report("llm", DependencyStatus.DOWN, critical=False),
    )
    assert aggregate(reports) is SystemStatus.DEGRADED


def test_critical_down_takes_system_down() -> None:
    reports = (
        _report("database", DependencyStatus.DOWN, critical=True),
        _report("llm", DependencyStatus.OK, critical=False),
    )
    assert aggregate(reports) is SystemStatus.DOWN


def test_critical_not_configured_only_degrades() -> None:
    reports = (_report("database", DependencyStatus.NOT_CONFIGURED, critical=True),)
    assert aggregate(reports) is SystemStatus.DEGRADED
