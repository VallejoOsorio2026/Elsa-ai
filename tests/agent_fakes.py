"""Relay y ELSA local simulados para las pruebas del agente de PC1 (D2.3).

Ninguno abre red: los dos son ``httpx.MockTransport`` que **graban** cada
petición tal como salió del agente (método, ruta cruda, cabeceras y cuerpo).
Eso permite comprobar sobre los bytes —no sobre una afirmación del código—
que el token del nodo nunca llega a ELSA, que el del usuario nunca llega a
Render y que la ruta local es exactamente la esperada.

Los valores son sintéticos y fáciles de buscar en logs y cuerpos.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr

from elsa.relay.protocol import AskParams, AttachmentMeta, Operation, Request

NODE_ID = "pc1-pilot"
NODE_TOKEN = "synthetic-node-token-0123456789abcdef"
USER_TOKEN = "synthetic-user-access-token"
QUESTION = "synthetic-sensitive-question"
RESULT_TEXT = "synthetic-sensitive-result"
ATTACHMENT_NAME = "synthetic-sensitive-attachment.pdf"
LOCAL_BASE = "http://127.0.0.1:8000"
RELAY_BASE = "https://relay.example.test"
NODE_PATH = "/api/v1/relay/node"


def make_request(
    session_id: UUID,
    *,
    request_id: UUID | None = None,
    domain: str = "mantenimiento",
    asset: str = "tampella",
    question: str = QUESTION,
    ttl_seconds: float = 60.0,
    now: datetime | None = None,
    attachments: list[AttachmentMeta] | None = None,
) -> Request:
    created = now or datetime.now(UTC)
    return Request(
        node_id=NODE_ID,
        node_session_id=session_id,
        request_id=request_id or uuid4(),
        operation=Operation.ASSISTANT_ASK,
        params=AskParams(
            domain=domain,
            asset=asset,
            question=question,
            attachments=attachments or [],
        ),
        user_access_token=SecretStr(USER_TOKEN),
        created_at=created - timedelta(seconds=1),
        expires_at=created + timedelta(seconds=ttl_seconds),
    )


def error_body(code: str, message: str = "synthetic error") -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


@dataclass(frozen=True)
class Recorded:
    method: str
    raw_path: str
    headers: dict[str, str]
    body: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.body)


Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]
Step = httpx.Response | Exception | Handler


async def _play(step: Step, request: httpx.Request) -> httpx.Response:
    if isinstance(step, httpx.Response):
        return step
    if isinstance(step, Exception):
        raise step
    return await step(request)


def _record(request: httpx.Request, body: bytes) -> Recorded:
    return Recorded(
        method=request.method,
        raw_path=request.url.raw_path.decode("ascii"),
        headers={key.lower(): value for key, value in request.headers.items()},
        body=body,
    )


class FakeLocalElsa:
    """ELSA local programable.

    Por defecto responde 200 con un ``AskResponse`` mínimo. ``hold()`` deja
    cada llamada esperando hasta ``release()`` para probar lo que ocurre
    mientras ELSA trabaja, sin dormir.
    """

    def __init__(self) -> None:
        self.requests: list[Recorded] = []
        self.steps: deque[Step] = deque()
        self.started = asyncio.Event()
        self.cancelled = 0
        self._gate: asyncio.Event | None = None

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def hold(self) -> None:
        self._gate = asyncio.Event()

    def release(self) -> None:
        if self._gate is not None:
            self._gate.set()

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        self.requests.append(_record(request, body))
        self.started.set()
        if self._gate is not None:
            try:
                await self._gate.wait()
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        if self.steps:
            return await _play(self.steps.popleft(), request)
        return httpx.Response(200, json={"message": RESULT_TEXT, "is_generated": False})


class FakeRelay:
    """Relay programable con *long poll* simulado y corto.

    - ``push(message)`` deja un mensaje (dict del cable) para el próximo poll.
    - ``register_steps`` / ``poll_steps`` / ``result_steps`` fuerzan respuestas
      (estado HTTP, excepción de transporte o función) antes del
      comportamiento por defecto.
    - Por defecto: register → 200; poll → el siguiente mensaje o, tras
      ``long_poll`` segundos, vacío; result → 200 ``accepted``.
    """

    def __init__(self, *, long_poll: float = 0.02) -> None:
        self.long_poll = long_poll
        self.requests: list[Recorded] = []
        self.registers: list[dict[str, Any]] = []
        self.polls: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.register_steps: deque[Step] = deque()
        self.poll_steps: deque[Step] = deque()
        self.result_steps: deque[Step] = deque()
        self._outbox: deque[dict[str, Any]] = deque()
        self._wake = asyncio.Event()

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def push(self, message: dict[str, Any]) -> None:
        self._outbox.append(message)
        self._wake.set()

    def push_request(self, request: Request) -> None:
        self.push(dict(request.to_wire_dict()))

    @property
    def session_ids(self) -> list[UUID]:
        return [UUID(item["node_session_id"]) for item in self.registers]

    async def _handle(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        recorded = _record(request, body)
        self.requests.append(recorded)
        endpoint = recorded.raw_path.rsplit("/", 1)[-1]
        if endpoint == "register":
            self.registers.append(recorded.json)
            if self.register_steps:
                return await _play(self.register_steps.popleft(), request)
            return httpx.Response(
                200,
                json={"status": "registered", "long_poll_seconds": 25.0, "node_ttl_seconds": 45.0},
            )
        if endpoint == "poll":
            self.polls.append(recorded.json)
            if self.poll_steps:
                return await _play(self.poll_steps.popleft(), request)
            return await self._long_poll()
        if endpoint == "result":
            self.results.append(recorded.json)
            if self.result_steps:
                return await _play(self.result_steps.popleft(), request)
            return httpx.Response(200, json={"accepted": True})
        return httpx.Response(404, json=error_body("not_found"))

    async def _long_poll(self) -> httpx.Response:
        if not self._outbox:
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), self.long_poll)
            except TimeoutError:
                pass
        message = self._outbox.popleft() if self._outbox else None
        return httpx.Response(200, json={"message": message})


@dataclass
class SleepRecorder:
    """Sustituto de ``asyncio.sleep`` que registra y no espera tiempo real."""

    delays: list[float] = field(default_factory=list)

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await asyncio.sleep(0)


async def wait_until(predicate: Callable[[], bool], timeout: float = 3.0) -> None:
    """Espera activa corta a una condición observable; falla si no llega."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.002)
