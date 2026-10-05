"""Contrato del protocolo Render ↔ PC1 V1 (ADR 0030).

Solo datos sintéticos y ninguna red: el protocolo es estructura, no ejecución.
"""

import ast
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from elsa.api.v1.assistant import AskRequest, AttachmentDeclaration
from elsa.relay import protocol
from elsa.relay.protocol import (
    ALLOWED_TRANSITIONS,
    AskParams,
    Cancel,
    CancelEffect,
    ErrorCode,
    ErrorMessage,
    Heartbeat,
    Operation,
    Register,
    Request,
    RequestState,
    Response,
    can_transition,
    cancel_effect,
    parse_message,
)

TOKEN = "synthetic-user-access-token"
NODE_ID = "pc1-pilot"
SESSION_ID = UUID("11111111-1111-4111-8111-111111111111")
REQUEST_ID = UUID("22222222-2222-4222-8222-222222222222")
CREATED = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
EXPIRES = CREATED + timedelta(seconds=150)


def _node(**extra: Any) -> dict[str, Any]:
    return {"node_id": NODE_ID, "node_session_id": SESSION_ID, **extra}


def _request_data(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = _node(
        request_id=REQUEST_ID,
        operation="assistant.ask",
        params={"domain": "mantenimiento", "asset": "synthetic-asset", "question": "Consulta"},
        user_access_token=TOKEN,
        created_at=CREATED,
        expires_at=EXPIRES,
    )
    data.update(overrides)
    return data


def _request(**overrides: Any) -> Request:
    return Request.model_validate(_request_data(**overrides))


# --- Versionado -----------------------------------------------------------


def test_v1_is_the_default_and_a_string() -> None:
    assert protocol.PROTOCOL_VERSION == "1"
    assert Register.model_validate(_node()).protocol_version == "1"


@pytest.mark.parametrize("version", ["2", "0", "", "1.0", 1, 2, None])
def test_unknown_or_non_string_versions_are_rejected(version: object) -> None:
    with pytest.raises(ValidationError):
        Register.model_validate(_node(protocol_version=version))


# --- Campos extra y cierre ------------------------------------------------


def test_unknown_fields_are_rejected_in_every_message() -> None:
    cases: list[tuple[type[Any], dict[str, Any]]] = [
        (Register, _node()),
        (Heartbeat, _node()),
        (Request, _request_data()),
        (Response, _node(request_id=REQUEST_ID, result={})),
        (ErrorMessage, _node(code="LOCAL_ERROR")),
        (Cancel, _node(request_id=REQUEST_ID)),
    ]
    for model, data in cases:
        with pytest.raises(ValidationError):
            model.model_validate({**data, "surprise": "x"})


def test_nested_params_reject_unknown_fields() -> None:
    params = {"domain": "d", "asset": "a", "question": "q", "surprise": 1}
    with pytest.raises(ValidationError):
        _request(params=params)


def test_models_are_immutable() -> None:
    message = Register.model_validate(_node())
    with pytest.raises(ValidationError):
        message.node_id = "other"


# --- Nodo y sesión --------------------------------------------------------


@pytest.mark.parametrize("node_id", ["pc1-pilot", "A", "node_1.v2", "a" * 64])
def test_valid_node_ids(node_id: str) -> None:
    assert Register.model_validate(_node(node_id=node_id)).node_id == node_id


@pytest.mark.parametrize(
    "node_id",
    ["", "a" * 65, "has space", "pc1/pilot", "pc1:pilot", "user@host", "pc1\n", "ñandú"],
)
def test_invalid_node_ids_are_rejected(node_id: str) -> None:
    with pytest.raises(ValidationError):
        Register.model_validate(_node(node_id=node_id))


def test_node_session_id_must_be_a_uuid() -> None:
    assert Register.model_validate(_node()).node_session_id == SESSION_ID
    for bad in ["not-a-uuid", "123", 7]:
        with pytest.raises(ValidationError):
            Register.model_validate(_node(node_session_id=bad))


def test_request_id_must_be_a_uuid_and_is_preserved_across_the_correlation() -> None:
    request = _request()
    response = Response(
        node_id=request.node_id,
        node_session_id=request.node_session_id,
        request_id=request.request_id,
        result={"ok": True},
    )
    error = ErrorMessage(
        node_id=request.node_id,
        node_session_id=request.node_session_id,
        request_id=request.request_id,
        code=ErrorCode.TIMEOUT,
    )
    cancel = Cancel(
        node_id=request.node_id,
        node_session_id=request.node_session_id,
        request_id=request.request_id,
    )
    assert {response.request_id, error.request_id, cancel.request_id} == {REQUEST_ID}
    with pytest.raises(ValidationError):
        _request(request_id="1")
    assert isinstance(uuid4(), UUID)


# --- Mensajes -------------------------------------------------------------


def test_every_message_type_is_valid_and_carries_its_discriminant() -> None:
    assert Register.model_validate(_node()).message_type == "register"
    assert Heartbeat.model_validate(_node()).message_type == "heartbeat"
    assert _request().message_type == "request"
    assert Response.model_validate(_node(request_id=REQUEST_ID, result={})).message_type == (
        "response"
    )
    assert ErrorMessage.model_validate(_node(code="PROTOCOL_ERROR")).message_type == "error"
    assert Cancel.model_validate(_node(request_id=REQUEST_ID)).message_type == "cancel"


def test_a_message_cannot_claim_another_type() -> None:
    with pytest.raises(ValidationError):
        Register.model_validate(_node(message_type="heartbeat"))


def test_message_type_values_match_the_enum() -> None:
    assert {member.value for member in protocol.MessageType} == {
        "register",
        "heartbeat",
        "request",
        "response",
        "error",
        "cancel",
    }


# --- Operaciones ----------------------------------------------------------


def test_assistant_ask_is_the_only_operation() -> None:
    assert {op.value for op in Operation} == {"assistant.ask"}
    assert _request().operation is Operation.ASSISTANT_ASK


@pytest.mark.parametrize("operation", ["assistant.understanding", "GET /api/v1/me", "", "exec"])
def test_arbitrary_operations_are_rejected(operation: str) -> None:
    with pytest.raises(ValidationError):
        _request(operation=operation)


# --- Token del usuario ----------------------------------------------------


def test_the_token_is_hidden_from_repr_and_str() -> None:
    request = _request()
    assert TOKEN not in repr(request)
    assert TOKEN not in str(request)


def test_the_token_is_hidden_from_the_normal_dumps() -> None:
    request = _request()
    assert TOKEN not in str(request.model_dump())
    assert TOKEN not in str(request.model_dump(mode="json"))
    assert TOKEN not in request.model_dump_json()


def test_the_explicit_wire_representation_carries_the_real_token() -> None:
    wire = _request().to_wire_dict()
    assert wire["user_access_token"] == TOKEN


def test_wire_dict_round_trips_through_json_to_an_equal_request() -> None:
    request = _request()
    restored = Request.model_validate_json(json.dumps(request.to_wire_dict()))
    assert restored == request
    assert restored.user_access_token.get_secret_value() == TOKEN


def test_the_token_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        _request(user_access_token="")


# --- Tiempos --------------------------------------------------------------


def test_utc_aware_timestamps_are_accepted_with_z_or_zero_offset() -> None:
    from_z = Request.model_validate_json(
        json.dumps({**_request().to_wire_dict(), "created_at": "2026-01-01T12:00:00Z"})
    )
    assert from_z.created_at == CREATED
    zero = _request(created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(0))))
    assert zero.created_at == CREATED


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _request(created_at=datetime(2026, 1, 1, 12, 0))
    with pytest.raises(ValidationError):
        _request(expires_at=datetime(2026, 1, 1, 12, 5))


def test_non_utc_offsets_are_rejected_not_silently_normalised() -> None:
    plus_two = timezone(timedelta(hours=2))
    with pytest.raises(ValidationError):
        _request(created_at=datetime(2026, 1, 1, 14, 0, tzinfo=plus_two))


def test_expires_at_must_be_after_created_at() -> None:
    with pytest.raises(ValidationError):
        _request(expires_at=CREATED)
    with pytest.raises(ValidationError):
        _request(expires_at=CREATED - timedelta(seconds=1))


def test_validation_does_not_depend_on_the_system_clock() -> None:
    # Un mensaje con fechas de hace años o del futuro lejano es estructuralmente válido:
    # decidir si «ya expiró» es del relay/agente.
    old = datetime(2001, 1, 1, tzinfo=UTC)
    assert _request(created_at=old, expires_at=old + timedelta(seconds=1))
    far = datetime(2999, 1, 1, tzinfo=UTC)
    assert _request(created_at=far, expires_at=far + timedelta(seconds=1))


# --- Errores --------------------------------------------------------------


def test_error_codes_are_a_closed_set() -> None:
    assert {code.value for code in ErrorCode} == {
        "INVALID_REQUEST",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "LOCAL_UNAVAILABLE",
        "TIMEOUT",
        "LOCAL_ERROR",
        "CANCELLED",
        "PROTOCOL_ERROR",
        "DUPLICATE_REQUEST",
    }
    for code in ErrorCode:
        assert ErrorMessage.model_validate(_node(code=code.value)).code is code


@pytest.mark.parametrize("code", ["NOT_FOUND", "local_error", "", "TEAPOT"])
def test_invented_error_codes_are_rejected(code: str) -> None:
    with pytest.raises(ValidationError):
        ErrorMessage.model_validate(_node(code=code))


def test_error_detail_is_bounded_and_request_id_is_optional() -> None:
    assert ErrorMessage.model_validate(_node(code="PROTOCOL_ERROR")).request_id is None
    with pytest.raises(ValidationError):
        ErrorMessage.model_validate(
            _node(code="LOCAL_ERROR", detail="x" * (protocol.ERROR_DETAIL_MAX_LENGTH + 1))
        )


def test_error_has_no_transport_status_field() -> None:
    # El protocolo no se acopla al HTTP local: el consumidor traduce ErrorCode.
    assert "local_status" not in ErrorMessage.model_fields
    with pytest.raises(ValidationError):
        ErrorMessage.model_validate(_node(code="FORBIDDEN", local_status=403))


# --- Respuesta: JSON contractual -----------------------------------------


def test_response_result_accepts_nested_json_and_round_trips() -> None:
    result = {"message": "ok", "items": [1, 2.5, None, True, {"a": ["b"]}]}
    response = Response.model_validate(_node(request_id=REQUEST_ID, result=result))
    assert Response.model_validate_json(response.model_dump_json()) == response


@pytest.mark.parametrize("value", [object(), {1, 2}, b"bytes", datetime(2026, 1, 1)])
def test_response_result_rejects_non_json_values(value: object) -> None:
    with pytest.raises(ValidationError):
        Response.model_validate(_node(request_id=REQUEST_ID, result={"x": value}))


def test_response_result_must_be_an_object() -> None:
    for bad in [[1], "text", 3, None]:
        with pytest.raises(ValidationError):
            Response.model_validate(_node(request_id=REQUEST_ID, result=bad))


# --- Parámetros de assistant.ask ------------------------------------------


def test_ask_limits_are_aligned_with_the_existing_endpoint() -> None:
    question = AskRequest.model_fields["question"]
    limits = {type(m).__name__: m for m in question.metadata}
    assert limits["MinLen"].min_length == protocol.ASK_QUESTION_MIN_LENGTH
    assert limits["MaxLen"].max_length == protocol.ASK_QUESTION_MAX_LENGTH
    filename = AttachmentDeclaration.model_fields["filename"].metadata[0]
    content_type = AttachmentDeclaration.model_fields["content_type"].metadata[0]
    assert filename.max_length == protocol.ASK_ATTACHMENT_FILENAME_MAX_LENGTH
    assert content_type.max_length == protocol.ASK_ATTACHMENT_CONTENT_TYPE_MAX_LENGTH
    assert set(AskParams.model_fields) - {"domain", "asset"} == set(AskRequest.model_fields)


def test_question_bounds_are_enforced_exactly() -> None:
    def params(question: str) -> dict[str, Any]:
        return {"domain": "d", "asset": "a", "question": question}

    assert _request(params=params("q")).params.question == "q"
    assert _request(params=params("q" * 2000))
    for bad in ["", "q" * 2001]:
        with pytest.raises(ValidationError):
            _request(params=params(bad))


def test_domain_and_asset_only_need_to_be_non_empty() -> None:
    # El endpoint actual no impone charset a la ruta: el contrato no inventa uno.
    odd = {"domain": "Mantenimiento ", "asset": "Tampella-01", "question": "q"}
    assert _request(params=odd).params.asset == "Tampella-01"
    for field in ("domain", "asset"):
        with pytest.raises(ValidationError):
            _request(params={**odd, field: ""})


def test_attachments_carry_only_declared_metadata() -> None:
    attachment = {"filename": "informe.pdf", "byte_size": 1024, "content_type": "application/pdf"}
    request = _request(
        params={"domain": "d", "asset": "a", "question": "q", "attachments": [attachment]}
    )
    assert request.params.attachments[0].byte_size == 1024
    for bad in [
        {**attachment, "content": "AAAA"},
        {**attachment, "byte_size": -1},
        {**attachment, "byte_size": "1024"},
        {**attachment, "filename": "f" * 256},
    ]:
        with pytest.raises(ValidationError):
            _request(params={"domain": "d", "asset": "a", "question": "q", "attachments": [bad]})


# --- Seguridad contractual: no es un proxy genérico ----------------------


FORBIDDEN_FIELD_NAMES = {
    "url",
    "uri",
    "method",
    "headers",
    "header",
    "query",
    "query_params",
    "path",
    "host",
    "body",
    "authorization",
    "service_role",
    "node_secret",
    "node_token",
    "node_credential",
    "secret",
    "password",
}


def _all_models() -> list[type[Any]]:
    return [
        Register,
        Heartbeat,
        Request,
        AskParams,
        protocol.AttachmentMeta,
        Response,
        ErrorMessage,
        Cancel,
    ]


def test_no_model_declares_a_proxy_or_secret_field() -> None:
    for model in _all_models():
        assert not FORBIDDEN_FIELD_NAMES & set(model.model_fields), model.__name__


@pytest.mark.parametrize("field", sorted({"url", "method", "headers", "query", "path"}))
def test_a_request_cannot_carry_proxy_fields(field: str) -> None:
    with pytest.raises(ValidationError):
        _request(**{field: "x"})
    with pytest.raises(ValidationError):
        _request(params={"domain": "d", "asset": "a", "question": "q", field: "x"})


@pytest.mark.parametrize("field", ["node_secret", "service_role", "authorization"])
def test_node_secret_service_role_and_authorization_are_not_part_of_any_message(
    field: str,
) -> None:
    cases: list[tuple[type[Any], dict[str, Any]]] = [
        (Register, _node()),
        (Heartbeat, _node()),
        (Request, _request_data()),
        (Response, _node(request_id=REQUEST_ID, result={})),
        (ErrorMessage, _node(code="LOCAL_ERROR")),
        (Cancel, _node(request_id=REQUEST_ID)),
    ]
    for model, data in cases:
        with pytest.raises(ValidationError):
            model.model_validate({**data, field: "x"})


def test_the_only_secret_typed_field_is_the_user_token() -> None:
    secrets = {
        (model.__name__, name)
        for model in _all_models()
        for name, info in model.model_fields.items()
        if "SecretStr" in repr(info.annotation)
    }
    assert secrets == {("Request", "user_access_token")}


def test_protocol_module_has_no_io_or_network_imports() -> None:
    source = Path(protocol.__file__).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {
        "httpx",
        "fastapi",
        "requests",
        "asyncio",
        "socket",
        "os",
        "subprocess",
        "elsa",
        "starlette",
        "asyncpg",
    }
    assert not imported & forbidden
    assert "datetime.now" not in source and ".utcnow(" not in source


# --- Round trip -----------------------------------------------------------


def test_every_message_round_trips_through_json_without_loss() -> None:
    messages: list[Any] = [
        Register.model_validate(_node()),
        Heartbeat.model_validate(_node()),
        Response.model_validate(_node(request_id=REQUEST_ID, result={"a": [1, {"b": None}]})),
        ErrorMessage.model_validate(
            _node(request_id=REQUEST_ID, code="LOCAL_ERROR", detail="fallo")
        ),
        Cancel.model_validate(_node(request_id=REQUEST_ID)),
    ]
    for message in messages:
        assert message.__class__.model_validate_json(message.model_dump_json()) == message


# --- Estados, transiciones y cancelación ---------------------------------


def test_states_are_the_documented_set() -> None:
    assert {state.value for state in RequestState} == {
        "queued",
        "dispatched",
        "running",
        "completed",
        "failed",
        "expired",
        "cancelled",
    }
    assert set(ALLOWED_TRANSITIONS) == set(RequestState)


def test_terminal_states_have_no_exit_and_nothing_returns_to_queued() -> None:
    for terminal in (
        RequestState.COMPLETED,
        RequestState.FAILED,
        RequestState.EXPIRED,
        RequestState.CANCELLED,
    ):
        assert ALLOWED_TRANSITIONS[terminal] == frozenset()
    assert all(RequestState.QUEUED not in targets for targets in ALLOWED_TRANSITIONS.values())


def test_the_happy_path_and_the_forbidden_shortcuts() -> None:
    assert can_transition(RequestState.QUEUED, RequestState.DISPATCHED)
    assert can_transition(RequestState.DISPATCHED, RequestState.RUNNING)
    assert can_transition(RequestState.RUNNING, RequestState.COMPLETED)
    assert not can_transition(RequestState.QUEUED, RequestState.COMPLETED)
    assert not can_transition(RequestState.COMPLETED, RequestState.RUNNING)
    assert not can_transition(RequestState.RUNNING, RequestState.DISPATCHED)


def test_cancellation_semantics_by_state() -> None:
    assert cancel_effect(RequestState.QUEUED) is CancelEffect.ALLOWED
    assert cancel_effect(RequestState.DISPATCHED) is CancelEffect.ATTEMPT
    assert cancel_effect(RequestState.RUNNING) is CancelEffect.BEST_EFFORT
    assert cancel_effect(RequestState.COMPLETED) is CancelEffect.TOO_LATE
    assert cancel_effect(RequestState.FAILED) is CancelEffect.TOO_LATE
    assert cancel_effect(RequestState.EXPIRED) is CancelEffect.NOT_APPLICABLE
    assert cancel_effect(RequestState.CANCELLED) is CancelEffect.NOT_APPLICABLE


# --- Revisión: endurecimiento --------------------------------------------


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_response_result_rejects_non_finite_numbers(value: float) -> None:
    for result in ({"x": value}, {"x": [1, {"y": value}]}):
        with pytest.raises(ValidationError):
            Response.model_validate(_node(request_id=REQUEST_ID, result=result))


def test_response_result_keeps_finite_numbers_without_loss() -> None:
    result = {"a": 1, "b": 2.5, "c": [0.0, -1], "d": None}
    response = Response.model_validate(_node(request_id=REQUEST_ID, result=result))
    assert json.loads(response.model_dump_json())["result"] == result


def test_parse_message_routes_each_wire_message_by_its_type() -> None:
    wires: list[tuple[type[Any], Any]] = [
        (Register, Register.model_validate(_node())),
        (Heartbeat, Heartbeat.model_validate(_node())),
        (Request, _request()),
        (Response, Response.model_validate(_node(request_id=REQUEST_ID, result={}))),
        (ErrorMessage, ErrorMessage.model_validate(_node(code="TIMEOUT"))),
        (Cancel, Cancel.model_validate(_node(request_id=REQUEST_ID))),
    ]
    for model, message in wires:
        raw = (
            json.dumps(message.to_wire_dict())
            if isinstance(message, Request)
            else message.model_dump_json()
        )
        parsed = parse_message(raw)
        assert type(parsed) is model
        assert parsed == message


def test_parse_message_requires_the_type_tag_so_register_and_heartbeat_are_not_ambiguous() -> None:
    untagged = json.dumps({"protocol_version": "1", **_node(node_session_id=str(SESSION_ID))})
    with pytest.raises(ValidationError):
        parse_message(untagged)
    with pytest.raises(ValidationError):
        parse_message(json.dumps({**json.loads(untagged), "message_type": "teapot"}))
    with pytest.raises(ValidationError):
        parse_message("not json")


def test_parse_message_rejects_unknown_versions_and_extra_fields() -> None:
    register = json.loads(Register.model_validate(_node()).model_dump_json())
    with pytest.raises(ValidationError):
        parse_message(json.dumps({**register, "protocol_version": "2"}))
    with pytest.raises(ValidationError):
        parse_message(json.dumps({**register, "url": "http://example.invalid"}))


def test_transition_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        ALLOWED_TRANSITIONS[RequestState.COMPLETED] = frozenset({RequestState.RUNNING})  # type: ignore[index]


def test_dispatched_can_finish_without_a_running_signal() -> None:
    # V1 no tiene un mensaje que anuncie `running`: el relay no lo ve en el cable.
    assert can_transition(RequestState.DISPATCHED, RequestState.COMPLETED)
    assert can_transition(RequestState.DISPATCHED, RequestState.FAILED)
