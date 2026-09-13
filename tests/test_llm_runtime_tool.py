"""La herramienta de operación del runtime, ejercitada de punta a punta.

Es la que se ejecuta en PC1 para dar el bloque por bueno, así que no puede
ser código sin probar: si `demo` se rompiera, el día de la validación real no
habría forma de distinguir un fallo de la herramienta de un fallo del modelo.

La generación con Phi es de PC1; aquí el runtime es el servidor falso, que
habla el mismo HTTP.
"""

import argparse

import pytest

from elsa.config import LLMBackend
from elsa.ports.documents import DocumentVersionState
from elsa.ports.llm import LLMConfigurationError
from elsa.tools.llm_runtime import build_llm, build_parser, synthetic_evidence_set
from tests.conftest import make_test_settings
from tests.fake_llama_server import FakeLlamaServer, closed_port_url, completion_body

pytestmark = pytest.mark.anyio


def parse(*argv: str) -> argparse.Namespace:
    return build_parser().parse_args(argv)


# ---------------------------------------------------------------------
# Evidencia sintética
# ---------------------------------------------------------------------


def test_the_synthetic_corpus_is_published_and_fully_traceable() -> None:
    """Sin procedencia completa un pasaje no puede sostener una cita.

    Y sin estar publicado no debería llegar al modelo: la demostración tiene
    que cumplir las mismas reglas que el corpus real, o estaría demostrando
    otra cosa.
    """
    evidence = synthetic_evidence_set()

    assert len(evidence) >= 2
    for item in evidence:
        assert item.provenance.is_published
        assert item.provenance.version.state is DocumentVersionState.PUBLISHED
        assert item.provenance.document.code
        assert item.citation()


def test_the_synthetic_corpus_lives_in_one_scope() -> None:
    """Una sola pareja dominio/equipo: la demostración no prueba aislamiento."""
    scopes = {item.scope for item in synthetic_evidence_set()}

    assert len(scopes) == 1


def test_the_synthetic_corpus_carries_no_real_plant_data() -> None:
    """Regla 12: ni un dato de PAPELSA en el repositorio.

    Los códigos llevan `DEMO` dentro a propósito, para que nadie confunda una
    salida de esta herramienta con un dato de planta al leerla meses después.
    """
    for item in synthetic_evidence_set():
        assert "DEMO" in item.provenance.document.code
        assert "DEMO" in item.provenance.chunk.content


# ---------------------------------------------------------------------
# Construcción del adaptador
# ---------------------------------------------------------------------


def test_the_tool_refuses_to_run_without_a_configured_runtime() -> None:
    with pytest.raises(LLMConfigurationError) as error:
        build_llm(make_test_settings())

    assert "ELSA_LLM_BACKEND" in str(error.value)


# ---------------------------------------------------------------------
# check / health
# ---------------------------------------------------------------------


async def test_check_reports_the_configuration_without_calling_the_runtime(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with FakeLlamaServer() as server:
        settings = make_test_settings(
            llm_backend=LLMBackend.LLAMA_CPP, llm_base_url=server.base_url
        )
        args = parse("check")

        base_url = server.base_url
        assert await args.run(settings, args) == 0
        assert server.requests == []

    out = capsys.readouterr().out
    assert "llama_cpp" in out
    assert base_url in out
    # La ruta del GGUF depende de la máquina y aquí no está declarada.
    assert "no declarado" in out


async def test_check_says_plainly_when_there_is_no_runtime(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = parse("check")

    assert await args.run(make_test_settings(), args) == 0
    assert "no hay runtime" in capsys.readouterr().out


async def test_health_reports_a_ready_runtime(capsys: pytest.CaptureFixture[str]) -> None:
    with FakeLlamaServer(health_status=200) as server:
        settings = make_test_settings(
            llm_backend=LLMBackend.LLAMA_CPP, llm_base_url=server.base_url
        )
        args = parse("health")

        assert await args.run(settings, args) == 0

    assert "listo" in capsys.readouterr().out


async def test_health_fails_when_the_runtime_is_stopped(
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = make_test_settings(
        llm_backend=LLMBackend.LLAMA_CPP,
        llm_base_url=closed_port_url(),
        llm_timeout_seconds=2.0,
    )
    args = parse("health")

    assert await args.run(settings, args) == 1
    assert "no disponible" in capsys.readouterr().err


# ---------------------------------------------------------------------
# demo: contexto real, verificación real
# ---------------------------------------------------------------------


async def test_demo_travels_the_real_service_not_a_copy_of_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`demo` pasa por `GroundedGenerationService`, no por una copia suya.

    Lo que se comprueba en PC1 no es que el modelo conteste, sino que el
    sistema completo hace con esa respuesta lo que promete. Si este comando
    reimplementara la política, diría que todo está bien mientras producción
    hace otra cosa. Por eso la salida trae el estado y el `request_id` que
    decide el servicio real.
    """
    answer = "Se lubrica cada 500 horas de operación con grasa NLGI 2 [E1]."
    with FakeLlamaServer(responses=[completion_body(answer)]) as server:
        settings = make_test_settings(
            llm_backend=LLMBackend.LLAMA_CPP, llm_base_url=server.base_url
        )
        args = parse("demo", "¿cada cuánto se lubrica el rodamiento?", "--request-id", "pc1-001")

        assert await args.run(settings, args) == 0
        sent = server.last().role("user")

    out = capsys.readouterr().out
    assert "SINTÉTICA" in out
    assert "estado         : answered" in out
    assert "[E1] Manual de la prensa de demostración v1 · 3 Lubricación · p. 12" in out
    assert "pc1-001" in out
    # El contexto lo compuso el Context Builder real, con su valla.
    assert "----- EVIDENCIA E1 -----" in sent


async def test_demo_reports_a_citation_the_model_invented(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """El comando no maquilla: si el modelo cita `[E9]`, lo dice.

    Es el motivo de que `demo` verifique en vez de limitarse a imprimir la
    salida cruda: en PC1 hay que poder ver si Phi está inventando citas.
    """
    with FakeLlamaServer(responses=[completion_body("El par es de 45 N·m [E9].")]) as server:
        settings = make_test_settings(
            llm_backend=LLMBackend.LLAMA_CPP, llm_base_url=server.base_url
        )
        args = parse("demo", "¿cuál es el par de apriete?")

        assert await args.run(settings, args) == 0

    out = capsys.readouterr().out
    assert "citas inventadas y descartadas: E9" in out
    # Y el marcador inventado no aparece en el texto que se muestra: eso lo
    # hace `visible_answer`, que es del servicio. Reimplementar el camino aquí
    # se saltaba ese borrado y enseñaba la cita falsa.
    assert "[E9]" not in out.split("citas inventadas")[0]
    assert "estado         : partial" in out


async def test_demo_reports_a_stopped_runtime_as_error_not_as_missing_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Con el runtime apagado, el comando dice lo mismo que diría el sistema.

    Y eso incluye no llamarlo «no encontré información»: al pasar por el
    servicio real, el runtime caído produce `ERROR` con su código de auditoría
    y las evidencias siguen citadas.
    """
    settings = make_test_settings(
        llm_backend=LLMBackend.LLAMA_CPP,
        llm_base_url=closed_port_url(),
        llm_timeout_seconds=2.0,
    )
    args = parse("demo", "¿cada cuánto se lubrica?")

    assert await args.run(settings, args) == 1
    out = capsys.readouterr().out
    assert "estado         : error" in out
    assert "error          : llm_unavailable" in out
    assert "no_evidence" not in out
    # Se le llamó y no contestó. Decir «no se llamó» aquí sugeriría una
    # abstención, que es justo la confusión que el bloque evita.
    assert "modelo         : sin respuesta del runtime" in out
    # Regla 9: lo recuperado se entrega aunque el modelo no esté.
    assert "[E1]" in out


# ---------------------------------------------------------------------
# La CLI exige lo que no puede suponer
# ---------------------------------------------------------------------


def test_ask_requires_explicit_scopes() -> None:
    """Sin alcances no se recupera nada: tampoco desde la línea de comandos."""
    with pytest.raises(SystemExit):
        parse("ask", "¿cada cuánto se lubrica?")


def test_ask_accepts_repeated_scopes() -> None:
    args = parse(
        "ask", "¿cada cuánto?", "--scope", "mantenimiento:asset-a", "--scope", "laboratorio"
    )

    assert args.scope == ["mantenimiento:asset-a", "laboratorio"]
