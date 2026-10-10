"""Configuración del agente de PC1 (ADR 0032).

Independiente de la configuración de ELSA: el agente no necesita
``ELSA_ENV`` ni ``ELSA_CORS_ORIGINS`` y ELSA ignora las variables
``ELSA_AGENT_*``. Se valida al arrancar y falla cerrado.

Dos orígenes distintos, a propósito:

- Los parámetros **no sensibles** (URLs, plazos, capacidad) se leen del
  entorno y, si existe, de un archivo ``.env``; el entorno manda.
- El **token del nodo** solo se acepta desde la variable de entorno del
  proceso (``ELSA_AGENT_NODE_TOKEN``). Si aparece en el archivo de
  configuración el agente **no arranca**: un secreto permanente no debe
  quedar escrito en disco junto al resto de la configuración.

Ningún mensaje de error repite el valor recibido: una URL mal escrita podría
llevar credenciales y el token es secreto.
"""

from __future__ import annotations

import ipaddress
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from elsa.relay.protocol import NODE_ID_PATTERN

__all__ = [
    "MIN_NODE_TOKEN_LENGTH",
    "NODE_TOKEN_ENV",
    "AgentConfig",
    "AgentConfigurationError",
    "AgentSettings",
    "load_agent_config",
]

ENV_PREFIX = "ELSA_AGENT_"
NODE_TOKEN_ENV = f"{ENV_PREFIX}NODE_TOKEN"
MIN_NODE_TOKEN_LENGTH = 32
"""Un secreto aleatorio de alta entropía (ADR 0031 §2); uno corto se rechaza."""
MAX_NODE_TOKEN_LENGTH = 512

_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


class AgentConfigurationError(Exception):
    """La configuración del agente no es válida. El mensaje no incluye valores."""


def _split(value: str) -> SplitResult:
    parts = urlsplit(value.strip())
    try:
        parts.port  # noqa: B018 - valida el puerto (lanza ValueError si no es numérico)
    except ValueError:
        raise ValueError("the port is not valid") from None
    if parts.username is not None or parts.password is not None:
        raise ValueError("must not include credentials")
    if parts.query or parts.fragment:
        raise ValueError("must not include a query or a fragment")
    if parts.path not in ("", "/"):
        raise ValueError("must not include a path; the agent builds the routes itself")
    if not parts.hostname:
        raise ValueError("must include a host")
    return parts


class AgentSettings(BaseSettings):
    """Parámetros no sensibles del agente. El token del nodo no está aquí."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    relay_url: str
    """Base HTTPS del relay de Render. Las rutas del nodo las añade el agente."""

    node_id: str = Field(pattern=NODE_ID_PATTERN)
    """Identidad configurada del nodo; debe coincidir con ``ELSA_RELAY_NODE_ID``."""

    local_base_url: str = "http://127.0.0.1:8000"
    """ELSA local. Solo ``http`` sobre una IP literal de loopback."""

    local_timeout_seconds: float = 110.0
    """Techo de una llamada a ELSA local; nunca va más allá de ``expires_at``."""

    poll_timeout_seconds: float = 35.0
    """Timeout de lectura de un poll; mayor que el long poll del relay (25 s)."""

    max_concurrency: int = 1
    """Llamadas simultáneas a ELSA local (alineado con ``llm_concurrency = 1``)."""

    max_queued: int = 4
    """Solicitudes admitidas que esperan turno. Las siguientes se rechazan."""

    log_level: str = "INFO"

    @field_validator("relay_url")
    @classmethod
    def _validate_relay_url(cls, value: str) -> str:
        parts = _split(value)
        if parts.scheme != "https":
            raise ValueError("must use https")
        return f"{parts.scheme}://{parts.netloc}"

    @field_validator("local_base_url")
    @classmethod
    def _validate_local_base_url(cls, value: str) -> str:
        parts = _split(value)
        if parts.scheme != "http":
            raise ValueError("must use http over loopback")
        try:
            address = ipaddress.ip_address(parts.hostname or "")
        except ValueError:
            # `localhost` u otro nombre: depende de la resolución de nombres.
            raise ValueError("the host must be a literal loopback IP address") from None
        if not address.is_loopback:
            raise ValueError("the host must be a literal loopback IP address")
        return f"{parts.scheme}://{parts.netloc}"

    @field_validator("local_timeout_seconds")
    @classmethod
    def _validate_local_timeout(cls, value: float) -> float:
        if not math.isfinite(value) or not 0 < value <= 300:
            raise ValueError("must be greater than 0 and at most 300")
        return value

    @field_validator("poll_timeout_seconds")
    @classmethod
    def _validate_poll_timeout(cls, value: float) -> float:
        if not math.isfinite(value) or not 0 < value <= 60:
            raise ValueError("must be greater than 0 and at most 60")
        return value

    @field_validator("max_concurrency")
    @classmethod
    def _validate_concurrency(cls, value: int) -> int:
        if not 1 <= value <= 4:
            raise ValueError("must be between 1 and 4")
        return value

    @field_validator("max_queued")
    @classmethod
    def _validate_queued(cls, value: int) -> int:
        if not 0 <= value <= 16:
            raise ValueError("must be between 0 and 16")
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in _LOG_LEVELS:
            raise ValueError(f"must be one of {sorted(_LOG_LEVELS)}")
        return level


class _TokenInFileProbe(BaseSettings):
    """Lee **solo** el archivo de configuración para detectar el token en él."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    node_token: str | None = None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (dotenv_settings,)


@dataclass(frozen=True)
class AgentConfig:
    """Configuración completa: parámetros no sensibles y token del nodo."""

    settings: AgentSettings
    node_token: SecretStr


def _node_token_from_environment(environ: Mapping[str, str]) -> SecretStr:
    raw = environ.get(NODE_TOKEN_ENV)
    if raw is None or raw == "":
        raise AgentConfigurationError(
            f"{NODE_TOKEN_ENV} is required and must be set in the process environment."
        )
    if not raw.isascii() or not raw.isprintable() or any(ch.isspace() for ch in raw):
        raise AgentConfigurationError(
            f"{NODE_TOKEN_ENV} must be printable ASCII without whitespace."
        )
    if not MIN_NODE_TOKEN_LENGTH <= len(raw) <= MAX_NODE_TOKEN_LENGTH:
        raise AgentConfigurationError(
            f"{NODE_TOKEN_ENV} must have between {MIN_NODE_TOKEN_LENGTH} and "
            f"{MAX_NODE_TOKEN_LENGTH} characters."
        )
    return SecretStr(raw)


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Invalid PC1 agent configuration:"]
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "settings"
        lines.append(f"  - {ENV_PREFIX}{loc}".upper() + f": {error['msg']}")
    lines.append("See .env.example and docs/environment-variables.md.")
    return "\n".join(lines)


def load_agent_config(env_file: str | Path | None = ".env") -> AgentConfig:
    """Carga y valida la configuración del agente. Falla cerrado.

    El token del nodo sale de ``os.environ`` y de nada más.
    """
    if env_file is not None:
        # `_env_file` es un kwarg de runtime de BaseSettings que mypy no ve.
        probe = _TokenInFileProbe(_env_file=env_file)  # type: ignore[call-arg]
        if probe.node_token is not None:
            raise AgentConfigurationError(
                f"{NODE_TOKEN_ENV} must not be stored in the configuration file; "
                "set it only in the process environment."
            )
    try:
        settings = AgentSettings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as exc:
        raise AgentConfigurationError(_format_validation_error(exc)) from None
    return AgentConfig(settings=settings, node_token=_node_token_from_environment(os.environ))
