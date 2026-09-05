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


# ---------------------------------------------------------------------
# Identidad y autorización (Bloque 1)
# ---------------------------------------------------------------------


def _supabase_env(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_AUTH_PROVIDER", "supabase")
    monkeypatch.setenv("ELSA_MATERIALS_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("ELSA_MATERIALS_API_KEY", "publishable-key-is-public-by-design")
    for key, value in extra.items():
        monkeypatch.setenv(key, value)


def test_fake_auth_provider_is_rejected_outside_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSA_ENV", "TEST")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_AUTH_PROVIDER", "fake")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "fake authentication provider" in str(excinfo.value)


def test_memory_permissions_backend_is_rejected_outside_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELSA_ENV", "TEST")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_AUTH_PROVIDER", "supabase")
    monkeypatch.setenv("ELSA_MATERIALS_SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("ELSA_MATERIALS_API_KEY", "publishable")
    monkeypatch.setenv("ELSA_PERMISSIONS_BACKEND", "memory")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "in-memory permissions backend" in str(excinfo.value)


def test_supabase_provider_requires_the_materials_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_AUTH_PROVIDER", "supabase")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_MATERIALS_SUPABASE_URL" in str(excinfo.value)


def test_supabase_provider_requires_the_materials_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_AUTH_PROVIDER", "supabase")
    monkeypatch.setenv("ELSA_MATERIALS_SUPABASE_URL", "https://project.supabase.co")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_MATERIALS_API_KEY" in str(excinfo.value)


def test_symmetric_algorithm_requires_the_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _supabase_env(monkeypatch, ELSA_AUTH_JWT_ALGORITHMS="HS256")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_AUTH_JWT_SECRET" in str(excinfo.value)


def test_symmetric_algorithm_is_accepted_with_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _supabase_env(
        monkeypatch,
        ELSA_AUTH_JWT_ALGORITHMS="HS256",
        ELSA_AUTH_JWT_SECRET="only-in-the-environment",
    )

    settings = load_settings(env_file=None)

    assert settings.auth_jwt_algorithms == ["HS256"]
    assert settings.auth_jwt_secret is not None


@pytest.mark.parametrize("algorithm", ["none", "NONE", "RS128", "notanalgorithm"])
def test_unsupported_algorithms_are_rejected(
    monkeypatch: pytest.MonkeyPatch, algorithm: str
) -> None:
    _supabase_env(monkeypatch, ELSA_AUTH_JWT_ALGORITHMS=algorithm)

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_AUTH_JWT_ALGORITHMS" in str(excinfo.value)


def test_urls_are_derived_from_the_materials_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _supabase_env(monkeypatch)

    settings = load_settings(env_file=None)

    assert settings.jwks_url == ("https://project.supabase.co/auth/v1/.well-known/jwks.json")
    assert settings.jwt_issuer == "https://project.supabase.co/auth/v1"
    assert settings.materials_profiles_url == "https://project.supabase.co/rest/v1/perfiles"


def test_postgres_backend_requires_a_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _supabase_env(monkeypatch, ELSA_PERMISSIONS_BACKEND="postgres")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_DATABASE_URL" in str(excinfo.value)


def test_plain_http_identity_provider_is_rejected_outside_dev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ELSA_ENV", "TEST")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "https://elsa-ai.link")
    monkeypatch.setenv("ELSA_AUTH_PROVIDER", "supabase")
    monkeypatch.setenv("ELSA_MATERIALS_SUPABASE_URL", "http://project.supabase.co")
    monkeypatch.setenv("ELSA_MATERIALS_API_KEY", "publishable")
    monkeypatch.setenv("ELSA_PERMISSIONS_BACKEND", "postgres")
    monkeypatch.setenv("ELSA_DATABASE_URL", "postgresql://user:pass@host/db")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "https" in str(excinfo.value)


def test_negative_limits_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_RATE_LIMIT_REQUESTS_PER_MINUTE", "-1")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_RATE_LIMIT_REQUESTS_PER_MINUTE" in str(excinfo.value)
