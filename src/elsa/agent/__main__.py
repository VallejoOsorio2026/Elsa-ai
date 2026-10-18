"""Arranque del agente de PC1 (ADR 0032)::

    uv run python -m elsa.agent [--env-file RUTA]

Los parámetros no sensibles se leen del entorno y del archivo indicado
(``.env`` por defecto). El token del nodo **solo** se acepta desde la variable
de entorno del proceso ``ELSA_AGENT_NODE_TOKEN``.

Códigos de salida: ``0`` al detenerse con Ctrl+C (o Ctrl+Break en Windows); ``2``
si la configuración no es válida o el relay rechaza la credencial o el protocolo
(no se reintenta en bucle); cualquier otro valor es un fallo inesperado.

En Windows, ``SIGBREAK`` sigue el mismo camino que Ctrl+C. Es la única señal que
el supervisor del Modo ELSA puede enviar a este proceso en concreto (ADR 0034
§7); sin este manejador, la acción por defecto lo terminaría sin ejecutar los
``finally`` del agente.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from collections.abc import Sequence
from types import FrameType

import httpx

from elsa.agent.config import AgentConfig, AgentConfigurationError, load_agent_config
from elsa.agent.local_client import ElsaLocalClient
from elsa.agent.relay_client import RelayClient
from elsa.agent.runner import EXIT_FATAL, EXIT_OK, NodeAgent
from elsa.logging import configure_logging


async def run_agent(
    config: AgentConfig,
    *,
    relay_transport: httpx.AsyncBaseTransport | None = None,
    local_transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """Construye los clientes y el agente, y corre hasta terminar."""
    settings = config.settings
    relay = RelayClient(
        settings.relay_url,
        config.node_token,
        poll_timeout_seconds=settings.poll_timeout_seconds,
        transport=relay_transport,
    )
    local = ElsaLocalClient(settings.local_base_url, transport=local_transport)
    agent = NodeAgent(
        node_id=settings.node_id,
        relay=relay,
        local=local,
        max_concurrency=settings.max_concurrency,
        max_queued=settings.max_queued,
        local_timeout_seconds=settings.local_timeout_seconds,
        poll_timeout_seconds=settings.poll_timeout_seconds,
    )
    try:
        return await agent.run()
    finally:
        await relay.aclose()
        await local.aclose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m elsa.agent",
        description="Agente de PC1: conecta ELSA local con el relay de Render (solo saliente).",
    )
    parser.add_argument(
        "--env-file",
        default=".env",
        help=(
            "archivo con los parámetros NO sensibles (por defecto .env); "
            "ELSA_AGENT_NODE_TOKEN solo se acepta desde el entorno del proceso"
        ),
    )
    return parser


def _break_as_interrupt(signum: int, frame: FrameType | None) -> None:
    """Trata ``SIGBREAK`` como Ctrl+C.

    Dentro de ``asyncio.run`` el manejador de SIGINT es el del runner, que cancela
    la tarea principal: los ``finally`` del agente y de ``run_agent`` se ejecutan
    y ``asyncio.run`` termina con ``KeyboardInterrupt``. Fuera de él, el
    manejador por defecto lanza ``KeyboardInterrupt`` directamente.
    """
    handler = signal.getsignal(signal.SIGINT)
    if callable(handler):
        handler(signal.SIGINT, frame)
    else:
        raise KeyboardInterrupt


def install_break_handler() -> bool:
    """Instala el manejador de ``SIGBREAK`` si existe (solo Windows)."""
    sigbreak = getattr(signal, "SIGBREAK", None)
    if sigbreak is None:
        return False
    signal.signal(sigbreak, _break_as_interrupt)
    return True


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    install_break_handler()
    try:
        config = load_agent_config(args.env_file)
    except AgentConfigurationError as exc:
        print(exc, file=sys.stderr)
        return EXIT_FATAL
    configure_logging(config.settings.log_level)
    # Las líneas de httpx incluirían rutas y estados de cada poll: fuera.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        return asyncio.run(run_agent(config))
    except KeyboardInterrupt:
        return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
