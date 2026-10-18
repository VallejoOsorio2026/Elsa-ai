"""Preflight del perfil PC1 (ADR 0034 §3 y §10). Sin red y sin procesos."""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from elsa.agent.config import NODE_TOKEN_ENV
from elsa.config import AssistantExecutionMode
from elsa.pc1.preflight import PreflightError, check_port_free, check_profile

FAKE_TOKEN = "pc1-preflight-fake-token-" + "k" * 24
RELAY_URL = "https://relay.example.test"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for key in list(os.environ):
        if key.startswith("ELSA_"):
            monkeypatch.delenv(key)
    yield
    os.environ.pop(NODE_TOKEN_ENV, None)


def _env_file(tmp_path: Path, **overrides: str | None) -> Path:
    values: dict[str, str | None] = {
        "ELSA_ENV": "DEV",
        "ELSA_CORS_ORIGINS": "http://127.0.0.1:8000",
        "ELSA_AGENT_RELAY_URL": RELAY_URL,
        "ELSA_AGENT_NODE_ID": "pc1-test",
        "ELSA_AGENT_LOCAL_BASE_URL": "http://127.0.0.1:8000",
    }
    values.update(overrides)
    path = tmp_path / "pc1.env"
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items() if value is not None),
        encoding="utf-8",
    )
    return path


def _fail(env_file: Path, read_secret: object = None) -> PreflightError:
    with pytest.raises(PreflightError) as excinfo:
        check_profile(env_file, read_secret)  # type: ignore[arg-type]
    return excinfo.value


def _never_prompt() -> str:
    raise AssertionError("the token must not be requested")


# ---------------------------------------------------------------------------
# Configuración válida
# ---------------------------------------------------------------------------


def test_a_valid_pc1_configuration_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    profile = check_profile(_env_file(tmp_path), _never_prompt)
    assert profile.port == 8000
    assert profile.settings.assistant_execution_mode is AssistantExecutionMode.LOCAL
    assert profile.settings.relay_enabled is False
    assert profile.agent.settings.relay_url == RELAY_URL
    assert profile.agent.node_token.get_secret_value() == FAKE_TOKEN


def test_the_port_comes_from_the_agent_local_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    env_file = _env_file(tmp_path, ELSA_AGENT_LOCAL_BASE_URL="http://127.0.0.1:8123")
    assert check_profile(env_file).port == 8123


# ---------------------------------------------------------------------------
# Perfil PC1
# ---------------------------------------------------------------------------


def test_incomplete_elsa_configuration_is_rejected_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    error = _fail(_env_file(tmp_path, ELSA_ENV=None))
    assert "ELSA_ENV" in error.variables


def test_incomplete_agent_configuration_is_rejected_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    error = _fail(_env_file(tmp_path, ELSA_AGENT_RELAY_URL=None))
    assert error.variables == ("ELSA_AGENT_RELAY_URL",)


def test_relay_execution_mode_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    # Sin relay habilitado, ELSA ya rechaza el modo relay al cargar.
    error = _fail(_env_file(tmp_path, ELSA_ASSISTANT_EXECUTION_MODE="relay"))
    assert "ELSA_ASSISTANT_EXECUTION_MODE" in error.variables


def test_relay_execution_mode_is_rejected_even_with_a_valid_relay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    env_file = _env_file(
        tmp_path,
        ELSA_ASSISTANT_EXECUTION_MODE="relay",
        ELSA_RELAY_ENABLED="true",
        ELSA_RELAY_NODE_ID="pc1-test",
        ELSA_RELAY_NODE_TOKEN_SHA256="0" * 64,
    )
    error = _fail(env_file)
    assert error.variables == ("ELSA_ASSISTANT_EXECUTION_MODE", "ELSA_RELAY_ENABLED")


def test_an_enabled_local_relay_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    env_file = _env_file(
        tmp_path,
        ELSA_RELAY_ENABLED="true",
        ELSA_RELAY_NODE_ID="pc1-test",
        ELSA_RELAY_NODE_TOKEN_SHA256="0" * 64,
    )
    assert _fail(env_file).variables == ("ELSA_RELAY_ENABLED",)


def test_debug_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    assert _fail(_env_file(tmp_path, ELSA_DEBUG="true")).variables == ("ELSA_DEBUG",)


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://127.0.0.2:8000",
        "http://[::1]:8000",
        "http://127.0.0.1",
        "http://192.168.1.20:8000",
    ],
)
def test_a_local_url_other_than_literal_127_0_0_1_with_a_port_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    error = _fail(_env_file(tmp_path, ELSA_AGENT_LOCAL_BASE_URL=url))
    assert error.variables == ("ELSA_AGENT_LOCAL_BASE_URL",)


def test_a_relay_url_without_https_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    env_file = _env_file(tmp_path, ELSA_AGENT_RELAY_URL="http://relay.example.test")
    assert _fail(env_file).variables == ("ELSA_AGENT_RELAY_URL",)


# ---------------------------------------------------------------------------
# Token del nodo
# ---------------------------------------------------------------------------


def test_a_missing_token_without_a_console_fails_closed(tmp_path: Path) -> None:
    error = _fail(_env_file(tmp_path), None)
    assert error.variables == (NODE_TOKEN_ENV,)
    assert NODE_TOKEN_ENV not in os.environ


def test_a_missing_token_is_requested_once_through_the_hidden_prompt(tmp_path: Path) -> None:
    calls: list[int] = []

    def prompt() -> str:
        calls.append(1)
        return FAKE_TOKEN

    profile = check_profile(_env_file(tmp_path), prompt)
    assert calls == [1]
    assert profile.agent.node_token.get_secret_value() == FAKE_TOKEN
    # Solo en el entorno de este proceso, del que lo hereda el hijo agente.
    assert os.environ[NODE_TOKEN_ENV] == FAKE_TOKEN


def test_an_invalid_prompted_token_is_rejected_and_not_kept(tmp_path: Path) -> None:
    error = _fail(_env_file(tmp_path), lambda: "short")
    assert error.variables == (NODE_TOKEN_ENV,)
    assert NODE_TOKEN_ENV not in os.environ
    assert "short" not in str(error)


def test_a_token_in_the_file_fails_closed_before_any_prompt(tmp_path: Path) -> None:
    env_file = _env_file(tmp_path, ELSA_AGENT_NODE_TOKEN=FAKE_TOKEN)
    error = _fail(env_file, _never_prompt)
    assert error.variables == (NODE_TOKEN_ENV,)
    assert "archivo" in error.message


def test_a_token_in_the_file_fails_closed_even_with_one_in_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    env_file = _env_file(tmp_path, ELSA_AGENT_NODE_TOKEN="file-" + "z" * 40)
    assert _fail(env_file, _never_prompt).variables == (NODE_TOKEN_ENV,)


def test_an_invalid_agent_configuration_is_reported_before_the_prompt(tmp_path: Path) -> None:
    env_file = _env_file(tmp_path, ELSA_AGENT_LOCAL_BASE_URL="http://localhost:8000")
    assert _fail(env_file, _never_prompt).variables == ("ELSA_AGENT_LOCAL_BASE_URL",)


def test_an_invalid_elsa_configuration_is_reported_before_the_prompt(tmp_path: Path) -> None:
    assert _fail(_env_file(tmp_path, ELSA_DEBUG="true"), _never_prompt).variables == ("ELSA_DEBUG",)


def test_messages_never_repeat_configured_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secretish = "user:pa55word@relay.example.test"
    monkeypatch.setenv(NODE_TOKEN_ENV, FAKE_TOKEN)
    cases = [
        _env_file(tmp_path, ELSA_AGENT_RELAY_URL=f"https://{secretish}"),
        _env_file(tmp_path, ELSA_CORS_ORIGINS=f"http://{secretish}/x?y=1"),
        _env_file(tmp_path, ELSA_AGENT_NODE_TOKEN=FAKE_TOKEN),
    ]
    for env_file in cases:
        text = str(_fail(env_file))
        assert "pa55word" not in text
        assert FAKE_TOKEN not in text


# ---------------------------------------------------------------------------
# Puerto
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_a_free_port_passes() -> None:
    check_port_free(_free_port())


def test_a_port_held_by_an_unknown_process_fails_closed_and_is_left_alone() -> None:
    foreign = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        foreign.bind(("127.0.0.1", 0))
        foreign.listen()
        port = int(foreign.getsockname()[1])
        with pytest.raises(PreflightError) as excinfo:
            check_port_free(port)
        assert excinfo.value.variables == ("ELSA_AGENT_LOCAL_BASE_URL",)
        # El listener ajeno sigue intacto y aceptando conexiones.
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            pass
    finally:
        foreign.close()
