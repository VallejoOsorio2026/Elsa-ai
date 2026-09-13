"""Un ``llama-server`` de mentira que habla HTTP de verdad.

Se podría probar el adaptador con ``httpx.MockTransport`` y quedaría más
corto, pero se perdería justo lo que hay que comprobar: que lo que sale por
el socket es lo que creemos. Con un transporte simulado nunca se serializa
nada, así que una petición mal formada, un cuerpo que no es JSON o un plazo
que no se respeta pasan desapercibidos. Aquí hay un servidor escuchando en un
puerto efímero de loopback, y el adaptador le habla como le hablaría a
llama.cpp.

Y hay una segunda razón, que es la importante: **este servidor guarda el
cuerpo crudo de cada petición**. Eso convierte «la evidencia de otro activo
nunca llega al modelo» en algo que se puede comprobar mirando los bytes que
salieron de ELSA, en vez de en una afirmación sobre lo que hace el código.

No se imita todo llama.cpp: solo ``/health`` y ``/v1/chat/completions``, que
son los dos caminos que usa el adaptador, con la forma de respuesta que
documenta llama.cpp para esa versión.
"""

import json
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Self

__all__ = ["FakeLlamaServer", "RecordedRequest", "closed_port_url", "completion_body"]


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    """Lo que el servidor recibió, sin interpretar."""

    path: str
    raw_body: str

    @property
    def payload(self) -> dict[str, Any]:
        return dict(json.loads(self.raw_body))

    def messages(self) -> list[dict[str, str]]:
        return list(self.payload.get("messages", []))

    def role(self, role: str) -> str:
        """Todo el contenido enviado con ese rol, concatenado."""
        return "\n".join(m.get("content", "") for m in self.messages() if m.get("role") == role)

    def contains(self, needle: str) -> bool:
        """Si el texto aparece **en cualquier parte** del cuerpo enviado.

        Deliberadamente sobre el cuerpo crudo y no sobre los mensajes ya
        interpretados: lo que importa es si el dato salió de la máquina, no
        en qué campo iba.
        """
        return needle in self.raw_body


def completion_body(content: str, *, model: str = "phi-4-mini-instruct") -> dict[str, Any]:
    """Una respuesta con la forma que devuelve ``/v1/chat/completions``."""
    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "model": model,
        "usage": {"prompt_tokens": 128, "completion_tokens": 32, "total_tokens": 160},
        "timings": {"prompt_per_second": 90.0, "predicted_per_second": 20.0},
    }


@dataclass
class FakeLlamaServer:
    """Servidor controlable. Cada campo declara un fallo que hay que probar."""

    responses: Sequence[dict[str, Any] | str] = ()
    """Cuerpos a devolver, en orden. Agotada la lista, se repite el último."""

    delay_seconds: float = 0.0
    """Retraso antes de contestar. Sirve para provocar el plazo vencido."""

    status_code: int = 200
    """Estado de ``/v1/chat/completions``. Distinto de 200 = rechazo."""

    health_status: int = 200
    """200 = listo; 503 = todavía cargando los pesos."""

    raw_body: str | None = None
    """Cuerpo literal, para devolver algo que no es JSON."""

    requests: list[RecordedRequest] = field(default_factory=list)
    max_concurrent: int = 0
    """Máximo de peticiones que estuvieron en vuelo a la vez."""

    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _in_flight: int = 0
    _served: int = 0

    # -----------------------------------------------------------------
    # Ciclo de vida
    # -----------------------------------------------------------------

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def start(self) -> None:
        handler = _build_handler(self)
        # Puerto 0: lo elige el sistema. Fijar uno haría que dos pruebas en
        # paralelo se pisaran, y que la suite fallara según qué más corra en
        # la máquina.
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise AssertionError("the fake llama-server is not running")
        host, port = self._server.server_address[:2]
        # `server_address` está tipado de forma genérica; con AF_INET siempre
        # es (str, int), pero se normaliza para que el tipador no adivine.
        return f"http://{host!s}:{int(port)}"

    # -----------------------------------------------------------------
    # Lo que recibió
    # -----------------------------------------------------------------

    @property
    def generation_requests(self) -> list[RecordedRequest]:
        return [request for request in self.requests if request.path.endswith("chat/completions")]

    @property
    def called(self) -> bool:
        return bool(self.generation_requests)

    def last(self) -> RecordedRequest:
        requests = self.generation_requests
        if not requests:
            raise AssertionError("the fake llama-server was never asked to generate")
        return requests[-1]

    def sent_anywhere(self, needle: str) -> bool:
        """Si el texto salió de ELSA en **alguna** petición."""
        return any(request.contains(needle) for request in self.requests)

    # -----------------------------------------------------------------
    # Uso interno del manejador
    # -----------------------------------------------------------------

    def _next_body(self) -> tuple[str, str]:
        """Devuelve ``(cuerpo, content_type)`` para la siguiente respuesta."""
        if self.raw_body is not None:
            return self.raw_body, "text/plain"
        if not self.responses:
            return json.dumps(completion_body("")), "application/json"
        index = min(self._served, len(self.responses) - 1)
        self._served += 1
        chosen = self.responses[index]
        if isinstance(chosen, str):
            return chosen, "text/plain"
        return json.dumps(chosen), "application/json"

    def _enter(self) -> None:
        with self._lock:
            self._in_flight += 1
            self.max_concurrent = max(self.max_concurrent, self._in_flight)

    def _leave(self) -> None:
        with self._lock:
            self._in_flight -= 1


def _build_handler(server: FakeLlamaServer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: object) -> None:
            """Silencio: la suite no es un registro de acceso."""

        def do_GET(self) -> None:  # noqa: N802 - nombre impuesto por la librería
            if self.path != "/health":
                self._send(404, json.dumps({"error": "not found"}), "application/json")
                return
            body = (
                json.dumps({"status": "ok"})
                if server.health_status == 200
                else json.dumps({"error": {"code": 503, "message": "Loading model"}})
            )
            self._send(server.health_status, body, "application/json")

        def do_POST(self) -> None:  # noqa: N802 - nombre impuesto por la librería
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8")
            with server._lock:
                server.requests.append(RecordedRequest(path=self.path, raw_body=raw))

            server._enter()
            try:
                if server.delay_seconds:
                    time.sleep(server.delay_seconds)
                body, content_type = server._next_body()
                self._send(server.status_code, body, content_type)
            finally:
                server._leave()

        def _send(self, status: int, body: str, content_type: str) -> None:
            encoded = body.encode("utf-8")
            try:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError):
                # El cliente se fue: es exactamente lo que pasa cuando vence
                # el plazo. No es un fallo del servidor y no debe ensuciar la
                # salida de la prueba que lo provocó a propósito.
                pass

    return Handler


def closed_port_url() -> str:
    """URL de un puerto de loopback donde con certeza no escucha nadie.

    Se abre un socket, se pide al sistema un puerto libre y se cierra. Es más
    fiable que elegir un número «que seguro está libre»: en la máquina de
    otro puede no estarlo, y entonces la prueba del servidor apagado estaría
    hablando con algo.
    """
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}"
