"""Configuración del agente de PC1: fail-closed y sin filtrar valores (ADR 0032)."""

from pathlib import Path

import pytest

from elsa.agent.config import (
    MIN_NODE_TOKEN_LENGTH,
    NODE_TOKEN_ENV,
    AgentConfigurationError,
    load_agent_config,
)

NODE_TOKEN = "synthetic-node-token-0123456789abcdef"
RELAY_URL = "https://relay.example.test"

_AGENT_VARS = (
    "ELSA_AGENT_RELAY_URL",
    "ELSA_AGENT_NODE_ID",
    "ELSA_AGENT_NODE_TOKEN",
    "ELSA_AGENT_LOCAL_BASE_URL",
    "ELSA_AGENT_LOCAL_TIMEOUT_SECONDS",
    "ELSA_AGENT_POLL_TIMEOUT_SECONDS",
    "ELSA_AGENT_MAX_CONCURRENCY",
    "ELSA_AGENT_MAX_QUEUED",
    "ELSA_AGENT_LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """La máquina del desarrollador no debe influir en estos tests."""
    for name in _AGENT_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELSA_AGENT_RELAY_URL", RELAY_URL)
    monkeypatch.setenv("ELSA_AGENT_NODE_ID", "pc1-pilot")
    monkeypatch.setenv(NODE_TOKEN_ENV, NODE_TOKEN)


def _error(env_file: Path | None = None) -> str:
    with pytest.raises(AgentConfigurationError) as excinfo:
        load_agent_config(env_file)
    return str(excinfo.value)


@pytest.mark.usefixtures("valid_environment")
def test_defaults_are_loopback_and_bounded() -> None:
    config = load_agent_config(None)
    settings = config.settings
    assert settings.relay_url == RELAY_URL
    assert settings.local_base_url == "http://127.0.0.1:8000"
    assert settings.max_concurrency == 1
    assert settings.max_queued == 4
    assert settings.poll_timeout_seconds == 35.0
    assert settings.local_timeout_seconds == 110.0
    assert config.node_token.get_secret_value() == NODE_TOKEN


@pytest.mark.usefixtures("valid_environment")
def test_node_token_is_masked_in_every_representation() -> None:
    config = load_agent_config(None)
    assert NODE_TOKEN not in repr(config)
    assert NODE_TOKEN not in str(config)
    assert NODE_TOKEN not in repr(config.settings)


def test_required_values_are_reported_by_variable_name() -> None:
    message = _error()
    assert "ELSA_AGENT_RELAY_URL" in message
    assert "ELSA_AGENT_NODE_ID" in message


@pytest.mark.usefixtures("valid_environment")
def test_missing_node_token_prevents_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(NODE_TOKEN_ENV)
    assert NODE_TOKEN_ENV in _error()


@pytest.mark.usefixtures("valid_environment")
@pytest.mark.parametrize(
    "token",
    [
        "short",
        "x" * (MIN_NODE_TOKEN_LENGTH - 1),
        "with space " + "x" * MIN_NODE_TOKEN_LENGTH,
        "tab\t" + "x" * MIN_NODE_TOKEN_LENGTH,
        "ñ" * MIN_NODE_TOKEN_LENGTH,
    ],
)
def test_weak_or_malformed_node_tokens_are_rejected_without_echo(
    monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    monkeypatch.setenv(NODE_TOKEN_ENV, token)
    message = _error()
    assert NODE_TOKEN_ENV in message
    assert token not in message


@pytest.mark.usefixtures("valid_environment")
def test_node_token_in_the_configuration_file_prevents_start(tmp_path: Path) -> None:
    """El secreto solo se acepta desde el entorno del proceso, nunca de un archivo."""
    env_file = tmp_path / ".env"
    env_file.write_text(f"{NODE_TOKEN_ENV}=file-token-{'x' * 40}\n", encoding="utf-8")
    message = _error(env_file)
    assert "must not be stored in the configuration file" in message
    assert "file-token" not in message


def test_node_token_only_in_the_file_is_never_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"ELSA_AGENT_RELAY_URL={RELAY_URL}\nELSA_AGENT_NODE_ID=pc1-pilot\n"
        f"{NODE_TOKEN_ENV}={'y' * 40}\n",
        encoding="utf-8",
    )
    with pytest.raises(AgentConfigurationError):
        load_agent_config(env_file)


@pytest.mark.usefixtures("valid_environment")
def test_non_sensitive_values_can_come_from_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ELSA_AGENT_NODE_ID")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ELSA_AGENT_NODE_ID=pc1-from-file\nELSA_AGENT_MAX_QUEUED=2\n", encoding="utf-8"
    )
    config = load_agent_config(env_file)
    assert config.settings.node_id == "pc1-from-file"
    assert config.settings.max_queued == 2
    assert config.node_token.get_secret_value() == NODE_TOKEN


@pytest.mark.usefixtures("valid_environment")
@pytest.mark.parametrize(
    "url",
    [
        "http://relay.example.test",
        "https://user:pass@relay.example.test",
        "https://relay.example.test/api",
        "https://relay.example.test/?x=1",
        "https://relay.example.test/#frag",
        "https://",
        "relay.example.test",
    ],
)
def test_relay_url_must_be_plain_https(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("ELSA_AGENT_RELAY_URL", url)
    message = _error()
    assert "ELSA_AGENT_RELAY_URL" in message
    assert "pass" not in message


@pytest.mark.usefixtures("valid_environment")
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://192.168.1.20:8000",
        "http://10.0.0.5:8000",
        "http://0.0.0.0:8000",
        "http://elsa.example.test:8000",
        "https://127.0.0.1:8000",
        "http://user:secret@127.0.0.1:8000",
        "http://127.0.0.1:8000/api",
        "http://127.0.0.1:8000/?next=http://evil.test",
        "http://127.0.0.1:notaport",
    ],
)
def test_local_url_must_be_a_literal_loopback_address(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setenv("ELSA_AGENT_LOCAL_BASE_URL", url)
    message = _error()
    assert "ELSA_AGENT_LOCAL_BASE_URL" in message
    assert "secret" not in message


@pytest.mark.usefixtures("valid_environment")
@pytest.mark.parametrize(
    ("url", "normalized"),
    [
        ("http://127.0.0.1:8000/", "http://127.0.0.1:8000"),
        ("http://127.0.0.2:9000", "http://127.0.0.2:9000"),
        ("http://[::1]:8000", "http://[::1]:8000"),
    ],
)
def test_loopback_addresses_are_accepted(
    monkeypatch: pytest.MonkeyPatch, url: str, normalized: str
) -> None:
    monkeypatch.setenv("ELSA_AGENT_LOCAL_BASE_URL", url)
    assert load_agent_config(None).settings.local_base_url == normalized


@pytest.mark.usefixtures("valid_environment")
@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("ELSA_AGENT_NODE_ID", "pc1 pilot"),
        ("ELSA_AGENT_NODE_ID", "x" * 65),
        ("ELSA_AGENT_MAX_CONCURRENCY", "0"),
        ("ELSA_AGENT_MAX_CONCURRENCY", "5"),
        ("ELSA_AGENT_MAX_QUEUED", "-1"),
        ("ELSA_AGENT_MAX_QUEUED", "17"),
        ("ELSA_AGENT_LOCAL_TIMEOUT_SECONDS", "0"),
        ("ELSA_AGENT_LOCAL_TIMEOUT_SECONDS", "301"),
        ("ELSA_AGENT_LOCAL_TIMEOUT_SECONDS", "nan"),
        ("ELSA_AGENT_POLL_TIMEOUT_SECONDS", "61"),
        ("ELSA_AGENT_POLL_TIMEOUT_SECONDS", "inf"),
        ("ELSA_AGENT_LOG_LEVEL", "VERBOSE"),
    ],
)
def test_out_of_range_values_prevent_start(
    monkeypatch: pytest.MonkeyPatch, variable: str, value: str
) -> None:
    monkeypatch.setenv(variable, value)
    assert variable in _error()


@pytest.mark.usefixtures("valid_environment")
@pytest.mark.parametrize("variable", ["ELSA_AGENT_LOCAL_BASE_URL", "ELSA_AGENT_RELAY_URL"])
def test_invalid_url_errors_never_echo_credentials(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    """`urlsplit` rechaza este netloc con un mensaje que lo repetiría entero."""
    scheme = "http" if "LOCAL" in variable else "https"
    monkeypatch.setenv(variable, f"{scheme}://u:SyntheticPw123＃@127.0.0.1:8000")
    message = _error()
    assert variable in message
    assert "SyntheticPw123" not in message
