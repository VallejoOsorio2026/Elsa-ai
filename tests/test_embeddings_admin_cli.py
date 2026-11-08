"""Las negativas de `embeddings_admin` ocurren antes de conectar a ninguna base.

No necesitan PostgreSQL ni ningún modelo: lo que se prueba es que un UUID mal
escrito, un Ctrl+Z sin motivo, una configuración inválida o DEV contra una
base remota se rechazan sin abrir una sola conexión.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from elsa.config import ConfigurationError, Environment
from elsa.tools import embeddings_admin
from elsa.tools.embeddings_admin import EXIT_REFUSED, build_parser, main

ACTOR = "aaaaaaaa-0000-4000-8000-000000000001"
MODEL = "bbbbbbbb-0000-4000-8000-000000000002"
REMOTE = "postgresql://elsa@db.example.test:5432/elsa"
LOOPBACK = "postgresql://elsa@127.0.0.1:5432/elsa"


def fake_settings(env: Environment, url: str | None) -> Any:
    return SimpleNamespace(env=env, database_url=None if url is None else SecretStr(url))


@pytest.fixture
def no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    async def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the CLI connected to a database it should have refused")

    monkeypatch.setattr(embeddings_admin.PostgresVectorStore, "connect", refuse)
    monkeypatch.setattr(embeddings_admin.PostgresDocumentRepository, "connect", refuse)


@pytest.mark.parametrize("value", ["juan", "", "aaaaaaaa-0000"])
def test_identifiers_must_be_uuids(value: str) -> None:
    for argv in (
        ["deactivate", "--model", MODEL, "--actor", value, "--reason", "x"],
        ["activate", "--model", value, "--actor", ACTOR],
        ["reconcile-run", "--run", value, "--actor", ACTOR, "--reason", "x"],
        ["generate", "--model", MODEL, "--version", value, "--actor", ACTOR],
    ):
        with pytest.raises(SystemExit):
            build_parser().parse_args(argv)


def test_the_ctrl_z_of_an_activation_requires_a_reason() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["deactivate", "--model", MODEL, "--actor", ACTOR])
    args = build_parser().parse_args(
        ["deactivate", "--model", MODEL, "--actor", ACTOR, "--reason", "Ctrl+Z"]
    )
    assert (args.model, args.actor, args.reason) == (MODEL, ACTOR, "Ctrl+Z")


@pytest.mark.parametrize(
    "argv",
    [
        ["deactivate", "--model", MODEL, "--actor", ACTOR, "--reason", "x"],
        ["activate", "--model", MODEL, "--actor", ACTOR],
        ["register", "--actor", ACTOR],
        ["generate", "--model", MODEL, "--version", MODEL, "--actor", ACTOR],
        ["reconcile-run", "--run", MODEL, "--actor", ACTOR, "--reason", "x"],
    ],
)
def test_dev_never_writes_to_a_remote_database(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, no_connection: None
) -> None:
    monkeypatch.setattr(
        embeddings_admin, "load_settings", lambda: fake_settings(Environment.DEV, REMOTE)
    )
    assert main(argv) == EXIT_REFUSED


def test_the_loopback_and_test_cases_are_allowed_to_write() -> None:
    embeddings_admin._require_writable(fake_settings(Environment.DEV, LOOPBACK))
    embeddings_admin._require_writable(fake_settings(Environment.TEST, REMOTE))


def test_an_invalid_configuration_is_reported_without_a_trace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_connection: None
) -> None:
    def broken() -> None:
        raise ConfigurationError("ELSA_DEBUG must be false outside DEV")

    monkeypatch.setattr(embeddings_admin, "load_settings", broken)
    assert main(["status"]) == EXIT_REFUSED
    err = capsys.readouterr().err
    assert "configuración inválida" in err and "Traceback" not in err


def test_a_missing_database_url_is_refused(
    monkeypatch: pytest.MonkeyPatch, no_connection: None
) -> None:
    monkeypatch.setattr(
        embeddings_admin, "load_settings", lambda: fake_settings(Environment.TEST, None)
    )
    assert main(["deactivate", "--model", MODEL, "--actor", ACTOR, "--reason", "x"]) == (
        EXIT_REFUSED
    )


def test_reconciliation_demands_a_minimum_idle_time(
    monkeypatch: pytest.MonkeyPatch, no_connection: None
) -> None:
    monkeypatch.setattr(
        embeddings_admin, "load_settings", lambda: fake_settings(Environment.TEST, REMOTE)
    )
    argv = ["reconcile-run", "--run", MODEL, "--actor", ACTOR, "--reason", "x"]
    assert main([*argv, "--idle-minutes", str(embeddings_admin.MIN_IDLE_MINUTES - 1)]) == (
        EXIT_REFUSED
    )
