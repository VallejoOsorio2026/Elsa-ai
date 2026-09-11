"""Tests de carga y validación de configuración."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from elsa.config import ConfigurationError, Environment, load_settings
from tests.conftest import make_test_settings


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


# ---------------------------------------------------------------------
# Variables opcionales declaradas sin valor
#
# Copiar `.env.example` a `.env` deja líneas como `ELSA_AUTH_JWKS_URL=`.
# Eso significa «no configurada», no «cadena vacía»: de lo contrario la
# plantilla no sería copiable y un secreto vacío pasaría por secreto válido.
# ---------------------------------------------------------------------

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


def test_the_env_example_template_loads_as_is() -> None:
    """Criterio permanente: copiar la plantilla debe bastar para arrancar.

    Es la regresión del fallo real encontrado en validación: `cp .env.example
    .env` abortaba el arranque porque las variables opcionales venían
    declaradas sin valor.
    """
    settings = load_settings(env_file=ENV_EXAMPLE)

    assert settings.env is Environment.DEV
    assert settings.auth_jwks_url is None
    assert settings.auth_jwt_issuer is None
    assert settings.auth_jwt_secret is None
    assert settings.bootstrap_admin_token is None
    assert settings.database_url is None


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_blank_jwks_url_falls_back_to_the_derived_one(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    _supabase_env(monkeypatch, ELSA_AUTH_JWKS_URL=blank)

    settings = load_settings(env_file=None)

    assert settings.auth_jwks_url is None
    assert settings.jwks_url == "https://project.supabase.co/auth/v1/.well-known/jwks.json"


def test_an_explicit_jwks_url_wins_over_the_derived_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _supabase_env(monkeypatch, ELSA_AUTH_JWKS_URL="https://other.example/jwks.json")

    settings = load_settings(env_file=None)

    assert settings.jwks_url == "https://other.example/jwks.json"


@pytest.mark.parametrize("malformed", ["esto-no-es-una-url", "ftp://project/jwks.json", "/"])
def test_a_non_blank_malformed_jwks_url_is_still_rejected(
    monkeypatch: pytest.MonkeyPatch, malformed: str
) -> None:
    """Tolerar el vacío no puede aflojar la validación de una URL escrita mal."""
    _supabase_env(monkeypatch, ELSA_AUTH_JWKS_URL=malformed)

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_AUTH_JWKS_URL" in str(excinfo.value)


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_issuer_falls_back_to_the_derived_one(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    _supabase_env(monkeypatch, ELSA_AUTH_JWT_ISSUER=blank)

    settings = load_settings(env_file=None)

    assert settings.auth_jwt_issuer is None
    assert settings.jwt_issuer == "https://project.supabase.co/auth/v1"


def test_an_explicit_issuer_wins_over_the_derived_one(monkeypatch: pytest.MonkeyPatch) -> None:
    _supabase_env(monkeypatch, ELSA_AUTH_JWT_ISSUER="https://other.example/auth/v1")

    settings = load_settings(env_file=None)

    assert settings.jwt_issuer == "https://other.example/auth/v1"


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_materials_url_is_reported_as_missing(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """El error debe ser «falta la variable», no «'' no tiene esquema http»."""
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_AUTH_PROVIDER", "supabase")
    monkeypatch.setenv("ELSA_MATERIALS_SUPABASE_URL", blank)
    monkeypatch.setenv("ELSA_MATERIALS_API_KEY", "publishable")

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    message = str(excinfo.value)
    assert "ELSA_MATERIALS_SUPABASE_URL is required" in message
    assert "http(s) scheme" not in message


def test_asymmetric_verification_needs_no_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """ES256 es lo que firma Materiales hoy: no debe exigir secreto simétrico."""
    _supabase_env(monkeypatch, ELSA_AUTH_JWT_ALGORITHMS="ES256")

    settings = load_settings(env_file=None)

    assert settings.auth_jwt_algorithms == ["ES256"]
    assert settings.auth_jwt_secret is None


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_jwt_secret_does_not_satisfy_a_symmetric_algorithm(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """Un secreto vacío no es un secreto: HS256 debe seguir fallando."""
    _supabase_env(monkeypatch, ELSA_AUTH_JWT_ALGORITHMS="HS256", ELSA_AUTH_JWT_SECRET=blank)

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_AUTH_JWT_SECRET" in str(excinfo.value)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_database_url_does_not_satisfy_the_postgres_backend(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    _supabase_env(monkeypatch, ELSA_PERMISSIONS_BACKEND="postgres", ELSA_DATABASE_URL=blank)

    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env_file=None)
    assert "ELSA_DATABASE_URL" in str(excinfo.value)


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_bootstrap_token_disables_the_bootstrap(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """Invariante de seguridad: sin valor real, el bootstrap queda deshabilitado."""
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_BOOTSTRAP_ADMIN_TOKEN", blank)

    settings = load_settings(env_file=None)

    assert settings.bootstrap_admin_token is None


def test_a_real_bootstrap_token_is_kept_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un token real no se recorta ni se altera; solo no debe filtrarse."""
    monkeypatch.setenv("ELSA_ENV", "DEV")
    monkeypatch.setenv("ELSA_CORS_ORIGINS", "http://localhost:5173")
    monkeypatch.setenv("ELSA_BOOTSTRAP_ADMIN_TOKEN", "un-token-de-un-solo-uso")

    settings = load_settings(env_file=None)

    assert settings.bootstrap_admin_token is not None
    assert settings.bootstrap_admin_token.get_secret_value() == "un-token-de-un-solo-uso"
    assert "un-token-de-un-solo-uso" not in repr(settings)


# ---------------------------------------------------------------------
# Chunking documental (Bloque 4.1)
# ---------------------------------------------------------------------


def test_the_chunking_policy_comes_from_configuration() -> None:
    settings = make_test_settings(
        document_chunk_profile="planta-v2",
        document_chunk_target_tokens=200,
        document_chunk_max_tokens=400,
        document_chunk_min_tokens=20,
        document_chunk_overlap_tokens=30,
        document_chunk_chars_per_token=3,
    )

    policy = settings.chunking_policy

    assert policy.name == "planta-v2"
    assert policy.target_tokens == 200
    assert policy.max_tokens == 400
    assert policy.overlap_tokens == 30
    assert policy.chars_per_token == 3


def test_incoherent_chunking_limits_stop_the_application() -> None:
    """El techo por debajo del objetivo produciría chunks imposibles."""
    with pytest.raises(ValidationError):
        make_test_settings(document_chunk_target_tokens=500, document_chunk_max_tokens=100)


def test_an_overlap_as_large_as_the_target_is_rejected() -> None:
    """Un solape del tamaño del chunk repetiría el contenido entero."""
    with pytest.raises(ValidationError):
        make_test_settings(document_chunk_target_tokens=300, document_chunk_overlap_tokens=300)


def test_chunking_limits_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        make_test_settings(document_chunk_chars_per_token=0)
    with pytest.raises(ValidationError):
        make_test_settings(document_chunk_overlap_tokens=-1)
