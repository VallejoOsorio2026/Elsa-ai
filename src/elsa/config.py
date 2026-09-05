"""Configuración de la aplicación.

Toda la configuración entra por variables de entorno con prefijo ``ELSA_``
(ver ``.env.example`` y ``docs/environment-variables.md``). La carga es tipada
y se valida al arranque: si falta una variable obligatoria o un valor es
inválido, la aplicación falla de forma clara con ``ConfigurationError`` antes
de aceptar tráfico.
"""

from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Environment(StrEnum):
    """Ambientes lógicos del proyecto (regla 13 de CLAUDE.md)."""

    DEV = "DEV"
    TEST = "TEST"


class ConfigurationError(RuntimeError):
    """Configuración ausente o inválida detectada al arranque."""


class Settings(BaseSettings):
    """Configuración validada de ELSA.

    Campos sin valor por defecto son obligatorios: su ausencia impide el
    arranque. Ningún campo contiene secretos en este bloque.
    """

    model_config = SettingsConfigDict(
        env_prefix="ELSA_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Environment
    """Selector de ambiente lógico: DEV o TEST. Obligatorio."""

    cors_origins: Annotated[list[str], NoDecode]
    """Orígenes CORS permitidos, separados por coma. Explícitos, sin comodines."""

    log_level: str = "INFO"
    """Nivel de log de la aplicación."""

    debug: bool = False
    """Sube la verbosidad de logs. Prohibido fuera de DEV; nunca expone trazas."""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _forbid_wildcard_origins(cls, origins: list[str]) -> list[str]:
        if not origins:
            raise ValueError("at least one explicit origin is required")
        for origin in origins:
            if "*" in origin:
                raise ValueError(f"wildcard origins are not allowed: {origin!r}")
            if not origin.startswith(("http://", "https://")):
                raise ValueError(f"origin must include an http(s) scheme: {origin!r}")
        return origins

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"log level must be one of {sorted(_LOG_LEVELS)}, got {value!r}")
        return level

    @model_validator(mode="after")
    def _forbid_debug_outside_dev(self) -> "Settings":
        if self.debug and self.env is not Environment.DEV:
            raise ValueError("debug mode is only allowed in the DEV environment")
        return self


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    """Carga y valida la configuración.

    Las variables de entorno reales tienen prioridad sobre ``env_file``.
    Lanza :class:`ConfigurationError` con un mensaje legible (una línea por
    variable afectada) si la configuración es inválida.
    """
    try:
        # `_env_file` es un kwarg de runtime de BaseSettings que la firma
        # sintetizada por mypy no declara.
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as exc:
        raise ConfigurationError(_format_validation_error(exc)) from None


def _format_validation_error(exc: ValidationError) -> str:
    prefix = Settings.model_config.get("env_prefix", "")
    lines = ["Invalid application configuration:"]
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "settings"
        variable = f"{prefix}{loc}".upper()
        lines.append(f"  - {variable}: {error['msg']}")
    lines.append("See .env.example and docs/environment-variables.md.")
    return "\n".join(lines)
