"""Tests de carga y validación de configuración."""

import pytest

from elsa.config import ConfigurationError, Environment, load_settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Elimina toda variable ELSA_* del ambiente para partir de cero."""
    import os

    for key in list(os.environ):
        if key.startswith("ELSA_"):
            monkeypatch.delenv(key)


def test_missing_required_variables_fail_clearly() -> None:
    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    message = str(excinfo.value)
    assert "ELSA_ENV" in message
    assert "ELSA_CORS_ORIGINS" in message
    assert "Invalid application configuration" in message


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173, http://localhost:3000")
    monkeypatch.setenv("ELSA_LOG_LEVEL", "debug")

    settings = load_settings(env_file=None)

    assert settings.env is Environment.DEV
    assert settings.cors_origins == ["http://localhost:5173", "http://localhost:3000"]
    assert settings.log_level == "DEBUG"
    assert settings.debug is False


def test_invalid_environment_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSA_ENV", "PRODUCTION")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_ENV" in str(excinfo.value)


def test_wildcard_cors_origin_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "*")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "wildcard" in str(excinfo.value)


def test_origin_without_scheme_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "localhost:5173")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "scheme" in str(excinfo.value)


def test_debug_is_forbidden_outside_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSA_ENV", "TEST")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_DEBUG", "true")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "debug" in str(excinfo.value).lower()


def test_invalid_log_level_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_LOG_LEVEL", "LOUD")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_LOG_LEVEL" in str(excinfo.value)
