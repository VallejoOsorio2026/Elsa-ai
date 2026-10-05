"""Protocolo lógico Render ↔ PC1, versión 1 (ADR 0030).

Este módulo es **solo contrato**: tipos, enums, constantes y validadores
pequeños. No hace I/O, no abre conexiones, no lee variables de entorno y no
consulta el reloj. Render (relay) y el agente de PC1 importan **esta** única
definición, para que ninguno invente un formato por su cuenta.

Tres propiedades que no son decoración:

- **No es un proxy genérico.** Un ``Request`` nombra una operación de una
  lista cerrada (:class:`Operation`) con parámetros propios de esa operación.
  No existe ningún campo ``url``, ``method`` ni ``headers``: Render no puede
  ordenar al nodo «haz GET/POST a cualquier sitio». El agente reconstruye la
  llamada local a partir de la operación.
- **Cerrado por defecto.** Todos los modelos rechazan campos desconocidos y
  una versión de protocolo desconocida. Ampliar el contrato exige un campo
  explícito o una versión nueva.
- **El token del usuario no se filtra por accidente.** Es un ``SecretStr``:
  ``repr``, ``str``, ``model_dump()`` y ``model_dump_json()`` lo enmascaran.
  Solo :meth:`Request.to_wire_dict` lo revela, porque es el payload de
  transporte. **Su resultado no se imprime ni se registra jamás.**

La credencial **permanente del nodo** no es parte de ningún mensaje: pertenece
al transporte (D2.2/D2.3). Tampoco hay tiempos de sistema: la decisión de si un
mensaje ya expiró es del relay o del agente, que pasan el instante; aquí solo
se valida la coherencia estructural.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    SecretStr,
    StrictInt,
    model_validator,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "ASK_ATTACHMENT_CONTENT_TYPE_MAX_LENGTH",
    "ASK_ATTACHMENT_FILENAME_MAX_LENGTH",
    "ASK_QUESTION_MAX_LENGTH",
    "ASK_QUESTION_MIN_LENGTH",
    "ERROR_DETAIL_MAX_LENGTH",
    "NODE_ID_PATTERN",
    "PROTOCOL_VERSION",
    "AskParams",
    "AttachmentMeta",
    "Cancel",
    "CancelEffect",
    "ErrorCode",
    "ErrorMessage",
    "Heartbeat",
    "MessageType",
    "NodeId",
    "Operation",
    "ProtocolModel",
    "Register",
    "Request",
    "RequestState",
    "Response",
    "can_transition",
    "cancel_effect",
]

PROTOCOL_VERSION: Literal["1"] = "1"
"""Versión del protocolo, **string**. Una versión desconocida se rechaza; no hay
negociación automática (falla cerrado)."""

NODE_ID_PATTERN = r"^[A-Za-z0-9._-]{1,64}$"
"""Identidad **configurada deliberadamente** del nodo: opaca, estable, no secreta
y de longitud acotada. Nunca el hostname, el usuario de Windows, la MAC, la IP ni
un correo."""

# Límites de ``assistant.ask``. Se alinean con ``AskRequest`` y
# ``AttachmentDeclaration`` de ``elsa.api.v1.assistant``; este módulo no puede
# importarlos (arrastran FastAPI y los puertos), así que un test compara ambos y
# falla si divergen.
ASK_QUESTION_MIN_LENGTH = 1
ASK_QUESTION_MAX_LENGTH = 2000
ASK_ATTACHMENT_FILENAME_MAX_LENGTH = 255
ASK_ATTACHMENT_CONTENT_TYPE_MAX_LENGTH = 255

ERROR_DETAIL_MAX_LENGTH = 200
"""Tope del ``detail`` de un error. El productor lo sanea: sin trazas, rutas
físicas, secretos ni ``repr`` de excepciones."""


class MessageType(StrEnum):
    """Tipo lógico de mensaje. Es el discriminante de cada modelo."""

    REGISTER = "register"
    HEARTBEAT = "heartbeat"
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"
    CANCEL = "cancel"


class Operation(StrEnum):
    """Lista **cerrada** de operaciones que el nodo ejecuta.

    Una operación nueva es un cambio de contrato: se añade aquí de forma
    explícita (y, según compatibilidad, con una versión nueva del protocolo).
    """

    ASSISTANT_ASK = "assistant.ask"


class ErrorCode(StrEnum):
    """Códigos de error cerrados."""

    INVALID_REQUEST = "INVALID_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    LOCAL_UNAVAILABLE = "LOCAL_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    LOCAL_ERROR = "LOCAL_ERROR"
    CANCELLED = "CANCELLED"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    """Un ``request_id`` ya procesado en la sesión activa del nodo. Sostiene la
    semántica at-most-once; es más preciso que ``INVALID_REQUEST``."""


class RequestState(StrEnum):
    """Estado conceptual de una solicitud (lo lleva el relay, no viaja en el cable)."""

    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


ALLOWED_TRANSITIONS: dict[RequestState, frozenset[RequestState]] = {
    RequestState.QUEUED: frozenset(
        {RequestState.DISPATCHED, RequestState.EXPIRED, RequestState.CANCELLED}
    ),
    RequestState.DISPATCHED: frozenset(
        {
            RequestState.RUNNING,
            RequestState.COMPLETED,
            RequestState.FAILED,
            RequestState.EXPIRED,
            RequestState.CANCELLED,
        }
    ),
    RequestState.RUNNING: frozenset(
        {
            RequestState.COMPLETED,
            RequestState.FAILED,
            RequestState.EXPIRED,
            RequestState.CANCELLED,
        }
    ),
    RequestState.COMPLETED: frozenset(),
    RequestState.FAILED: frozenset(),
    RequestState.EXPIRED: frozenset(),
    RequestState.CANCELLED: frozenset(),
}
"""Transiciones permitidas. Los estados terminales no tienen salida. No hay
camino de vuelta a ``queued``: una solicitud en vuelo **no se reejecuta**."""


def can_transition(current: RequestState, target: RequestState) -> bool:
    """Indica si pasar de ``current`` a ``target`` está permitido."""
    return target in ALLOWED_TRANSITIONS[current]


class CancelEffect(StrEnum):
    """Qué significa cancelar según el estado. La cancelación es *best effort*."""

    ALLOWED = "allowed"
    """``queued``: se retira de la cola."""
    ATTEMPT = "attempt"
    """``dispatched``: puede intentarse."""
    BEST_EFFORT = "best_effort"
    """``running``: no se promete que lo ya iniciado pueda abortarse."""
    TOO_LATE = "too_late"
    """``completed`` o ``failed``."""
    NOT_APPLICABLE = "not_applicable"
    """``expired`` o ``cancelled``."""


_CANCEL_EFFECTS: dict[RequestState, CancelEffect] = {
    RequestState.QUEUED: CancelEffect.ALLOWED,
    RequestState.DISPATCHED: CancelEffect.ATTEMPT,
    RequestState.RUNNING: CancelEffect.BEST_EFFORT,
    RequestState.COMPLETED: CancelEffect.TOO_LATE,
    RequestState.FAILED: CancelEffect.TOO_LATE,
    RequestState.EXPIRED: CancelEffect.NOT_APPLICABLE,
    RequestState.CANCELLED: CancelEffect.NOT_APPLICABLE,
}


def cancel_effect(state: RequestState) -> CancelEffect:
    """Efecto contractual de pedir la cancelación en ``state``."""
    return _CANCEL_EFFECTS[state]


def _require_utc(value: datetime) -> datetime:
    """Exige un instante con zona horaria **y en UTC** (offset cero explícito).

    Una sola regla: se aceptan ``Z`` o ``+00:00``; un instante naïve o con otro
    offset se rechaza, en vez de normalizarlo en silencio.
    """
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamps must be timezone-aware and in UTC (offset 0)")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
NodeId = Annotated[str, Field(pattern=NODE_ID_PATTERN)]


class _ClosedModel(BaseModel):
    """Sin campos extra e inmutable. Base de los modelos anidados."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProtocolModel(_ClosedModel):
    """Base de los mensajes: cerrada y con versión explícita."""

    protocol_version: Literal["1"] = PROTOCOL_VERSION


class _NodeScoped(ProtocolModel):
    node_id: NodeId
    node_session_id: UUID
    """Nuevo en cada arranque o reconexión lógica del agente; no se persiste.
    Distingue sesiones y permite rechazar respuestas tardías."""


class Register(_NodeScoped):
    """El nodo se anuncia al iniciar una sesión. Sin capacidades ni datos del PC."""

    message_type: Literal[MessageType.REGISTER] = MessageType.REGISTER


class Heartbeat(_NodeScoped):
    """El nodo sigue vivo. No es telemetría."""

    message_type: Literal[MessageType.HEARTBEAT] = MessageType.HEARTBEAT


class AttachmentMeta(_ClosedModel):
    """Metadatos de un adjunto declarado. **Nunca** los bytes del archivo."""

    filename: str = Field(max_length=ASK_ATTACHMENT_FILENAME_MAX_LENGTH)
    byte_size: StrictInt = Field(ge=0)
    content_type: str | None = Field(
        default=None, max_length=ASK_ATTACHMENT_CONTENT_TYPE_MAX_LENGTH
    )


class AskParams(_ClosedModel):
    """Lo necesario para reconstruir ``POST /assistant/{domain}/{asset}/ask``.

    ``domain`` y ``asset`` son strings de ruta: el endpoint actual no les impone
    charset (``resolve_asset`` solo hace ``strip().lower()``), así que aquí solo
    se exige que no estén vacíos. Endurecerlos queda para D2.4; el agente deberá
    codificarlos como **un único segmento de ruta**.
    """

    domain: str = Field(min_length=1)
    asset: str = Field(min_length=1)
    question: str = Field(min_length=ASK_QUESTION_MIN_LENGTH, max_length=ASK_QUESTION_MAX_LENGTH)
    attachments: list[AttachmentMeta] = Field(default_factory=list)


class Request(_NodeScoped):
    """Solicitud ejecutable. Render → PC1.

    Entrega **at-most-once** por ``request_id`` dentro de la sesión activa del
    nodo: tras ``dispatched`` no se reenvía, y una desconexión con la solicitud
    en vuelo termina como fallo explícito, nunca como reejecución.
    """

    message_type: Literal[MessageType.REQUEST] = MessageType.REQUEST
    request_id: UUID
    operation: Literal[Operation.ASSISTANT_ASK]
    params: AskParams
    user_access_token: SecretStr = Field(min_length=1)
    """Credencial **temporal** del usuario, opaca para el protocolo. No es la
    credencial del nodo. Enmascarada en ``repr``/``str``/``model_dump``."""
    created_at: UtcDatetime
    expires_at: UtcDatetime

    @model_validator(mode="after")
    def _expires_after_created(self) -> Request:
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        return self

    def to_wire_dict(self) -> dict[str, JsonValue]:
        """Representación de **transporte**: incluye el token real.

        Es el único punto que revela el secreto. D2.2/D2.3 deben usarla
        deliberadamente para enviar el mensaje; su resultado **no se imprime ni
        se registra jamás**.
        """
        data: dict[str, JsonValue] = self.model_dump(mode="json")
        data["user_access_token"] = self.user_access_token.get_secret_value()
        return data


class Response(_NodeScoped):
    """Resultado exitoso. PC1 → Render.

    ``result`` es contenido JSON **opaco** (la respuesta ya producida por ELSA):
    el protocolo no interpreta inventario, BOM ni LLM. Su tamaño máximo queda
    PENDIENTE D2.2.
    """

    message_type: Literal[MessageType.RESPONSE] = MessageType.RESPONSE
    request_id: UUID
    result: dict[str, JsonValue]


class ErrorMessage(_NodeScoped):
    """Fallo de una solicitud o del protocolo. PC1 → Render (o Render → PC1)."""

    message_type: Literal[MessageType.ERROR] = MessageType.ERROR
    request_id: UUID | None = None
    """Ausente solo en errores que no pertenecen a una solicitud."""
    code: ErrorCode
    detail: str | None = Field(default=None, max_length=ERROR_DETAIL_MAX_LENGTH)
    """Saneado y acotado por el productor. Nunca trazas, rutas físicas, secretos
    ni ``repr`` de excepciones internas."""
    local_status: StrictInt | None = Field(default=None, ge=100, le=599)
    """Estado HTTP que devolvió ELSA local, si lo hubo; evita perder esa
    información al mapear a un ``ErrorCode``."""


class Cancel(_NodeScoped):
    """Pide cancelar una solicitud. Render → PC1. *Best effort* (:func:`cancel_effect`)."""

    message_type: Literal[MessageType.CANCEL] = MessageType.CANCEL
    request_id: UUID
