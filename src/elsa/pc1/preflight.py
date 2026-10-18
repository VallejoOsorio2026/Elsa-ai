"""Preflight del perfil PC1 (ADR 0034 §3 y §10).

Antes de arrancar nada se valida, con las mismas funciones que usan ELSA y el
agente al arrancar (sin duplicar sus reglas):

1. la configuración de ELSA (``load_settings``) y el perfil PC1: modo
   ``local``, relay propio deshabilitado y debug apagado;
2. los parámetros no sensibles del agente, el host local **exacto**
   ``127.0.0.1`` y un puerto explícito;
3. el token del nodo: del entorno del proceso o, si falta y hay consola, de un
   prompt oculto. Antes de pedirlo, ``load_agent_config`` ya comprobó que el
   token **no** está en el archivo (fail-closed de D2.3). Un token pedido por el
   prompt **no** se escribe en ``os.environ``: queda en el perfil (``SecretStr``)
   y el supervisor lo pone solo en el entorno del hijo agente;
4. que el puerto local esté libre.

Los errores son :class:`PreflightError` con un mensaje fijo y, como mucho, los
**nombres** de las variables afectadas: nunca un valor, nunca ``str(exc)``.
"""

from __future__ import annotations

import re
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from elsa.agent.config import (
    NODE_TOKEN_ENV,
    AgentConfig,
    AgentConfigurationError,
    AgentSettings,
    _node_token_from_environment,
    load_agent_config,
)
from elsa.config import AssistantExecutionMode, ConfigurationError, Settings, load_settings

__all__ = [
    "LOCAL_URL_ENV",
    "LOOPBACK_BIND",
    "Pc1Profile",
    "PreflightError",
    "check_port_free",
    "check_profile",
]

LOOPBACK_BIND = "127.0.0.1"
"""Única dirección en la que escucha ELSA de PC1. No es configurable."""
LOCAL_URL_ENV = "ELSA_AGENT_LOCAL_BASE_URL"

_MISSING_TOKEN = f"{NODE_TOKEN_ENV} is required and must be set in the process environment."
_ELSA_LINE = re.compile(r"^\s+- (ELSA_[A-Z0-9_]+):", re.MULTILINE)
_ELSA_NAME = re.compile(r"\bELSA_[A-Z0-9_]+\b")
_AGENT_NAME = re.compile(r"\bELSA_AGENT_[A-Z0-9_]+\b")

ReadSecret = Callable[[], str]


class PreflightError(Exception):
    """El nodo no puede arrancar. ``message`` es fijo; ``variables`` son solo nombres."""

    def __init__(self, message: str, variables: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.variables = variables

    def __str__(self) -> str:
        if not self.variables:
            return self.message
        return f"{self.message} Variables: {', '.join(self.variables)}."


@dataclass(frozen=True)
class Pc1Profile:
    """Configuración validada del nodo. El token está en ``agent.node_token`` (SecretStr)."""

    settings: Settings
    agent: AgentConfig
    port: int
    env_file: Path | None


def _unique(names: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(names))


def _elsa_settings(env_file: Path | None) -> Settings:
    try:
        return load_settings(env_file)
    except UnicodeDecodeError:
        # p. ej. un .env guardado como UTF-16 por Windows PowerShell 5.1.
        raise PreflightError(
            "El archivo de configuración no se puede leer como texto UTF-8."
        ) from None
    except ConfigurationError as exc:
        names: list[str] = []
        for line in str(exc).splitlines():
            match = _ELSA_LINE.match(line)
            if match is None:
                continue
            if match.group(1) == "ELSA_SETTINGS":
                # Error de modelo: el texto nombra las variables; el valor no se usa.
                names.extend(n for n in _ELSA_NAME.findall(line) if n != "ELSA_SETTINGS")
            else:
                names.append(match.group(1))
        raise PreflightError(
            "La configuración de ELSA está incompleta o no es válida.", _unique(names)
        ) from None


def _check_pc1_profile(settings: Settings) -> None:
    names = []
    if settings.assistant_execution_mode is not AssistantExecutionMode.LOCAL:
        names.append("ELSA_ASSISTANT_EXECUTION_MODE")
    if settings.relay_enabled:
        names.append("ELSA_RELAY_ENABLED")
    if settings.debug:
        names.append("ELSA_DEBUG")
    if names:
        raise PreflightError(
            "La configuración no corresponde al perfil PC1: ELSA debe estar en modo local, "
            "con el relay propio deshabilitado y sin debug.",
            tuple(names),
        )


def _agent_error(exc: AgentConfigurationError) -> PreflightError:
    text = str(exc)
    if "must not be stored in the configuration file" in text:
        return PreflightError(
            "El token del nodo está escrito en el archivo de configuración. Bórrelo del "
            "archivo: el token solo se acepta desde el entorno o por el prompt oculto.",
            (NODE_TOKEN_ENV,),
        )
    if "UTF-8" in text or "could not be read" in text:
        return PreflightError("El archivo de configuración no se puede leer como texto UTF-8.")
    if text.startswith(NODE_TOKEN_ENV):
        return PreflightError("El token del nodo no tiene un formato válido.", (NODE_TOKEN_ENV,))
    return PreflightError(
        "La configuración del agente está incompleta o no es válida.",
        _unique(_AGENT_NAME.findall(text)),
    )


def _local_port(local_base_url: str) -> int:
    parts = urlsplit(local_base_url)
    if parts.hostname != LOOPBACK_BIND or parts.port is None or not 1 <= parts.port <= 65535:
        raise PreflightError(
            f"La URL local del agente debe ser http://{LOOPBACK_BIND}:<puerto>, "
            "con esa dirección exacta y un puerto explícito entre 1 y 65535.",
            (LOCAL_URL_ENV,),
        )
    return parts.port


def _agent_config(env_file: Path | None, read_secret: ReadSecret | None) -> AgentConfig:
    try:
        config = load_agent_config(env_file)
    except AgentConfigurationError as exc:
        if str(exc) != _MISSING_TOKEN:
            raise _agent_error(exc) from None
    else:
        _local_port(config.settings.local_base_url)
        return config

    # Solo falta el token en el entorno: `load_agent_config` ya rechazó un archivo
    # con NUL o con el token, y validó los parámetros no sensibles. La URL local se
    # comprueba antes de pedir nada.
    settings = AgentSettings(_env_file=env_file)  # type: ignore[call-arg]
    _local_port(settings.local_base_url)
    if read_secret is None:
        raise PreflightError(
            "Falta el token del nodo y no hay consola para pedirlo.", (NODE_TOKEN_ENV,)
        )
    # Mismas reglas de formato que el agente, sin pasar por `os.environ`: el token
    # pedido no queda en el entorno del supervisor ni lo hereda ningún otro hijo.
    try:
        token = _node_token_from_environment({NODE_TOKEN_ENV: read_secret()})
    except AgentConfigurationError:
        raise PreflightError(
            "El token del nodo introducido no tiene un formato válido.", (NODE_TOKEN_ENV,)
        ) from None
    return AgentConfig(settings=settings, node_token=token)


def check_profile(env_file: Path | None, read_secret: ReadSecret | None = None) -> Pc1Profile:
    """Valida configuración y token. Falla cerrado con :class:`PreflightError`."""
    settings = _elsa_settings(env_file)
    _check_pc1_profile(settings)
    agent = _agent_config(env_file, read_secret)
    port = _local_port(agent.settings.local_base_url)
    return Pc1Profile(settings=settings, agent=agent, port=port, env_file=env_file)


def check_port_free(port: int) -> None:
    """Falla cerrado si algo escucha en ``127.0.0.1:port``. No identifica ni toca a nadie."""
    occupied = PreflightError(
        f"El puerto {LOOPBACK_BIND}:{port} está ocupado por otro programa. "
        "Modo ELSA no lo identifica ni lo detiene.",
        (LOCAL_URL_ENV,),
    )
    try:
        with socket.create_connection((LOOPBACK_BIND, port), timeout=0.5):
            raise occupied
    except OSError:
        pass  # nadie acepta conexiones: se comprueba también el bind
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == "win32":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((LOOPBACK_BIND, port))
    except OSError:
        raise occupied from None
    finally:
        sock.close()
