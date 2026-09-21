"""Los scripts de operación del runtime dicen lo que creemos que dicen.

`Stop-ElsaLlm.ps1` solo se ejecuta en Windows y la integración corre en
Linux, así que su comportamiento no se puede observar aquí. Lo que sí se
puede fijar son las propiedades que costaron una medición en PC1:

- `llama-server` se arranca oculto y sin ventana, de modo que
  `CloseMainWindow()` devuelve `False` sin enviar nada. Si su resultado se
  descarta, el script espera el timeout completo para nada: 20,59 s medidos
  antes de la corrección, 1,12 s después.
- El registro y el log solo se borran cuando el proceso desapareció de
  verdad. Borrarlos antes de comprobarlo deja un llama-server huérfano sin
  rastro de qué PID era.

Estos tests fijan esas propiedades, no la redacción del script.
"""

import re
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "Stop-ElsaLlm.ps1"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8-sig")

CLOSE_CAPTURE = re.compile(r"\$(\w+)\s*=\s*\$process\.CloseMainWindow\(\)")
TIMEOUT_WAIT = "$process.WaitForExit($TimeoutSeconds * 1000)"
FORCED_CLOSE = "Stop-Process -Id $process.Id -Force"


def _guarded_block(header: str) -> str:
    """Devuelve el cuerpo del bloque `{ ... }` que abre justo tras `header`."""
    open_brace = SCRIPT.index("{", SCRIPT.index(header) + len(header))
    depth = 0
    for index in range(open_brace, len(SCRIPT)):
        if SCRIPT[index] == "{":
            depth += 1
        elif SCRIPT[index] == "}":
            depth -= 1
            if depth == 0:
                return SCRIPT[open_brace + 1 : index]
    raise AssertionError(f"el bloque de {header!r} no se cierra")


def test_the_close_request_result_is_captured() -> None:
    assert "CloseMainWindow() | Out-Null" not in SCRIPT, (
        "descartar el resultado de CloseMainWindow() reintroduce la espera inútil"
    )
    assert CLOSE_CAPTURE.search(SCRIPT), "el resultado de CloseMainWindow() debe guardarse"


def test_the_timeout_is_only_waited_when_the_close_request_was_sent() -> None:
    match = CLOSE_CAPTURE.search(SCRIPT)
    assert match is not None
    flag = match.group(1)

    assert SCRIPT.count(TIMEOUT_WAIT) == 1, "la espera del timeout aparece una sola vez"
    assert TIMEOUT_WAIT in _guarded_block(f"if (${flag})"), (
        "la espera del timeout solo tiene sentido si CloseMainWindow() devolvió True"
    )


def test_the_forced_close_does_not_depend_on_having_a_window() -> None:
    match = CLOSE_CAPTURE.search(SCRIPT)
    assert match is not None

    assert FORCED_CLOSE in SCRIPT
    assert FORCED_CLOSE not in _guarded_block(f"if (${match.group(1)})"), (
        "sin ventana principal hay que forzar el cierre igualmente"
    )


def test_nothing_is_cleaned_up_before_confirming_the_process_is_gone() -> None:
    recheck = SCRIPT.rindex("Get-Process -Id $record.ProcessId")
    pid_file_removal = SCRIPT.rindex("Remove-Item -LiteralPath $PidFile -Force")
    log_removal = SCRIPT.rindex("Clear-RuntimeLog -Keep:$KeepLog")
    done = SCRIPT.rindex("Detenido.")

    assert SCRIPT.rindex(FORCED_CLOSE) < recheck, (
        "el proceso se vuelve a comprobar después de forzar el cierre"
    )
    assert "throw" in SCRIPT[recheck:pid_file_removal], (
        "si el proceso sigue vivo, el script falla en vez de limpiar"
    )
    assert recheck < pid_file_removal < log_removal < done


def test_the_identity_checks_survive() -> None:
    for guard in (
        "Test-Path -LiteralPath $PidFile",
        "$record.ProcessId",
        "$process.StartTime.ToString('o') -ne $record.StartTime",
        "$process.ProcessName -ne 'llama-server'",
        "$process.Path -ne $record.ExecutablePath",
    ):
        assert guard in SCRIPT, f"falta la validación {guard!r}"
