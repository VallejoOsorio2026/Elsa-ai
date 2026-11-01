# Cierre formal — O1.2: runner local mínimo, sin Claude real y sin push automático

- **Fecha:** 2026-11-01. El PR funcional #60 se abrió a las 22:37:35 UTC y se fusionó a las
  22:43:23 UTC.
- **Estado:** cierre formal de O1.2, **efectivo cuando este documento quede integrado en `main` con
  el CI obligatorio en verde** (ver «Regla de continuidad»).
- **Qué cierra:** el subbloque **O1.2** del bloque O1 (orquestación semiautomática ChatGPT ↔ GitHub ↔
  Claude Code). Deja un runner local que valida una especificación, trabaja en una copia aparte,
  comprueba por Git lo que cambió un ejecutor, ejecuta controles fijos, genera evidencia sanitizada,
  hace commits solo locales y se detiene.
- **Qué NO cierra:** **no cierra O1.** No hay ejecutor real: la consola solo ofrece uno que no cambia
  nada. No se ejecutó Claude Code sin supervisión, ni `run` sobre el repositorio real. El runner no
  publica ramas ni lee CI. Ver §20.
- **Prerrequisitos:** O1-A y O1.1
  ([`o1-1-contrato-y-preparacion-cierre.md`](o1-1-contrato-y-preparacion-cierre.md)).
- **Decisión técnica:** [ADR 0036](adr/0036-orquestacion-semiautomatica-de-bloques.md), sin cambios.
  Operación: [`orchestration/README.md`](orchestration/README.md), §10. Especificación:
  [`orchestration/work/O1.2.md`](orchestration/work/O1.2.md).
- **Marcas de afirmación** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**,
  **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Sanitización:** este documento no contiene secretos, tokens, claves, cadenas de conexión, rutas de
  perfil de usuario ni datos de planta. Los tokens de las pruebas son sintéticos y no se reproducen.

---

## 1. Objetivo

Disponer de un runner local determinista para las tareas mecánicas de preparación y verificación de un
bloque, sin usar todavía Claude Code real sin supervisión.

## 2. Alcance

**Entró:** `scripts/orchestrator.py` (`validate`, `run`, `status`, `cleanup`),
`scripts/Start-ElsaBlock.ps1`, el ejecutor falso, pruebas unitarias, de integración, solo de Windows y de
ensayo, el ajuste de `pyproject.toml` para `mypy` y pytest, el manual y las Partes A y B.

**Quedó fuera (explícito):**

| Qué | Dónde queda |
|---|---|
| Claude real, `claude -p` y configuración sin supervisión | O1.3 |
| Publicar la rama, leer CI y dar el enlace del PR desde el runner | O1.4 |
| Ajuste de la Skill `elsa-release` | O1.4 |
| `PROJECT_HISTORY_AND_CURRENT_STATE.md` y `HANDOVER_AND_CONTINUITY_MAP.md` | O1.5 |
| Corregir las 3 pruebas que fallan en Windows | Bloque aparte (§20) |
| `src/elsa`, `uv.lock`, `ci.yml`, `CLAUDE.md`, `.claude/`, Render, Supabase, SAP | No se tocan |

## 3. Estado inicial

**HECHO MEDIDO:** `main` limpio y sincronizado en `594cf8fd64eb18fff6eb6055e4fb4306450e8a96`, con
`origin` igual al repositorio autorizado. De la carpeta externa solo existía `worktrees\o1-1`, vacía.

**HECHO DEL REPOSITORIO:** O1.1 cerrado formalmente (PR #58 y #59). ADR 0036 aceptado.

## 4. Trabajo realizado

1. Copia de implementación `o1-2-impl`, sin seguimiento de rama.
2. Especificación O1.2 y configuración de `pyproject.toml`.
3. Runner, lanzador y ejecutor falso.
4. Pruebas: unitarias, integración con Git real, solo de Windows y ensayo.
5. Primera línea base: aparecieron 3 fallas ajenas en Windows. **Parada y decisión de Juan** (§5).
6. Lista fija de 3 omisiones y demostración de las fallas sobre `main` limpio.
7. Parte A: encontró defectos reales del runner, ya corregidos (§13).
8. Revisión con `security-reviewer` y correcciones dentro del alcance (§8).
9. Suite completa, Parte A final, `pre-commit` y `git diff --check`.
10. Commits, push de la rama y CI.
11. Juan: creación y merge del PR #60, y sincronización de `main`.
12. Parte B en el repositorio real.
13. Retirada segura de la copia de implementación y este cierre.

## 5. Decisiones

| Decisión | Quién | Motivo |
|---|---|---|
| **DECISIÓN TOMADA:** cambiar `pyproject.toml` solo para cubrir `scripts/` con `mypy` y pytest | Juan | El runner debe revisarse como el resto; sin dependencias nuevas |
| **DECISIÓN TOMADA:** el runner puede hacer commits locales en su rama | Juan | Sin ellos no habría nada que O1.4 pudiera publicar |
| **DECISIÓN TOMADA:** sin `git branch -D`; prueba real en repositorio desechable y `validate` en el real | Juan | Rediseño de la decisión 3 |
| **DECISIÓN TOMADA:** omitir en Windows exactamente 3 pruebas, por identificador exacto | Juan | Fallan también sobre `main` limpio; es una excepción a `elsa-testing` con condiciones (§8) |
| **DECISIÓN TOMADA:** el control `mypy` usa `--platform linux` | Claude Code; consta en `O1.2.md` | `src/elsa/bench/runner.py` da 3 errores en Windows y `src/elsa` queda fuera. Es lo que hace CI |
| **DECISIÓN TOMADA:** `state\` guarda solo el lock | Claude Code | El ADR 0036 §4 prohíbe un archivo de estado aparte |
| **DECISIÓN TOMADA:** el resultado es `verified_local`, sin estado nuevo | Claude Code | `PR_READY` exige publicar, y O1.2 no publica |
| **DECISIÓN TOMADA:** el ejecutor no puede commitear | Claude Code | Lo escaneado es exactamente lo que entra |
| **DECISIÓN TOMADA:** controles con el `.venv` principal y `PYTHONPATH` a la copia | Claude Code | El runner no debe instalar librerías; un control verifica de dónde se carga `elsa` |
| **DECISIÓN TOMADA:** el runner no importa `elsa`, aunque repite patrones de `elsa.pc1` | Claude Code y Juan | O1 es tooling, no producto |

**No apareció ninguna contradicción con el ADR 0036, que no se modificó.**

## 6. Pruebas

| Tipo | Dónde corre | Resultado |
|---|---|---|
| Unitarias | Windows y CI | **HECHO MEDIDO:** 302 aprobadas |
| Integración con Git real | Windows y CI | **HECHO MEDIDO:** dentro de la suite completa; ver §8 |
| Solo Windows: 50 arranques suspendidos, muerte del runner | Windows | **HECHO MEDIDO:** aprobadas |
| Parte A | Windows, con `ELSA_O1_REHEARSAL=1` | **HECHO MEDIDO:** 4 aprobadas |
| Suite completa | Windows, con las 3 omisiones | **HECHO MEDIDO:** ver §8 |
| Parte B | Windows, repositorio real | **HECHO MEDIDO:** `validated`, foto idéntica |
| CI | Linux | **HECHO MEDIDO:** `success` en rama y merge |

**No se ejecutó:** `claude -p`, Claude real sin supervisión, `run` sobre el repositorio real, push o
merge desde el runner, ni los tests de PostgreSQL en local; estos últimos los corre CI.

## 7. Comandos relevantes

```bash
.\scripts\Start-ElsaBlock.ps1 -Action Validate -Block T0.1
.\scripts\Start-ElsaBlock.ps1 -Action Status
```

Parte A, desde la copia de trabajo y con el Python del clon principal, en PowerShell:

```bash
$env:ELSA_O1_REHEARSAL='1'; $env:PYTHONPATH="$PWD\src"; & <clon>\.venv\Scripts\python.exe -m pytest tests/test_orchestrator_rehearsal.py -v -s
```

Pruebas enfocadas y controles de cierre:

```bash
python -m pytest tests/test_orchestrator.py tests/test_orchestrator_integration.py -q
python -m ruff check .
python -m ruff format --check .
python -m mypy --platform linux
python -m pre_commit run --all-files
git diff --check
```

Limpieza de la copia de implementación, tras el merge:

```bash
git worktree remove <carpeta>
git branch -d claude/o1-2-runner-local-minimo
```

## 8. Resultados

**HECHO MEDIDO**, las 3 fallas sobre `main` limpio (`594cf8f`, 0 líneas en `git status`, antes y
después):

```text
=== bench, 3 runs ===
FAILED tests/test_bench_harness.py::test_a_run_records_what_produced_it - Ass...
FAILED tests/test_bench_harness.py::test_peak_memory_is_measured_where_the_posix_api_exists
2 failed, 2 warnings in 0.44s
(idéntico en las 3 corridas)

=== ctrl-c, until first failure, max 60 ===
attempt 59 FAILED
E   assert 26837.343 < 26837.343
FAILED tests/test_pc1_supervisor.py::test_a_real_ctrl_c_reaches_only_the_supervisor_which_stops_in_order
passes=58 fails=1
```

| Prueba omitida en Windows | Causa conocida | Cómo falla |
|---|---|---|
| `tests/test_bench_harness.py::test_a_run_records_what_produced_it` | `_windows_peak_rss_mb` devuelve `None` y la prueba exige una cifra | Siempre |
| `tests/test_bench_harness.py::test_peak_memory_is_measured_where_the_posix_api_exists` | Exige el módulo `resource`, solo POSIX | Siempre |
| `tests/test_pc1_supervisor.py::test_a_real_ctrl_c_reaches_only_the_supervisor_which_stops_in_order` | Compara con `<` dos marcas de reloj que en Windows pueden coincidir | Intermitente; 1 de 59 en esta medición |

Las condiciones de Juan se cumplen así: lista fija en `WINDOWS_KNOWN_TEST_FAILURES`, solo en Windows,
sin patrones, declarada en cada informe, con CI sin omisiones (`ci.yml` no excluye ninguna), con el
bloque detenido si el número omitido no es exactamente 3 o si aparece otra falla.

**HECHO MEDIDO**, Parte A (repositorio desechable):

```text
tests/test_orchestrator_rehearsal.py::test_part_a_no_change PASSED
tests/test_orchestrator_rehearsal.py::test_part_a_allowed_edit_with_real_gates
gate git_diff_check: exit=0 0.0s
gate package_origin: exit=0 0.2s
gate ruff_check: exit=0 1.2s
gate ruff_format: exit=0 0.8s
gate mypy: exit=0 109.6s
gate pytest: exit=0 196.8s 2143 passed, 231 skipped, 3 deselected, 3 warnings
PASSED
tests/test_orchestrator_rehearsal.py::test_part_a_fake_token_is_detected_by_real_gitleaks PASSED
tests/test_orchestrator_rehearsal.py::test_part_a_real_repository_is_identical PASSED
4 passed, 2 warnings in 378.67s (0:06:18)
```

**HECHO MEDIDO**, Parte B (repositorio real, `c6a54ec`):

```text
Resultado: validated
exit=0

--compare--
IDENTICAL byte a byte
head:       c6a54eca0d3cdead2630e365ba917ef03b12dcaa
head_ref:   refs/heads/main
status:     (vacío)
ref_count:  83
t0_branch_local: (vacío)   t0_branch_remote: (vacío)
worktrees:  5
```

La foto compara `HEAD`, `origin/main`, referencias, estado, lista de copias, configuración, `hooks/`,
`info/` y las ramas de GitHub. Sin rama, sin copia, sin commit, sin push y sin merge.

**HECHO MEDIDO**, última suite completa en Windows, con las 3 omisiones:

```text
1 failed, 2552 passed, 236 skipped, 3 deselected, 3 warnings in 755.01s (0:12:35)
FAILED tests/test_orchestrator_integration.py::test_executor_scenarios_are_blocked[repoints_git_file-repo_invariant_broken]
```

La falla era del ejecutor falso, que no podía reescribir el `.git` oculto en Windows. Se corrigió y se
repitió solo ese escenario:

```text
1 passed, 108 deselected, 2 warnings in 6.10s
```

**La suite local completa no se repitió tras esa corrección**, que solo tocó el ejecutor falso. CI corrió
el código final completo.

Motivos de las omisiones de esa suite: 207 motivos de PostgreSQL, 4 de la Parte A, que corre aparte, 1 por
falta de permiso para crear enlaces simbólicos en esta cuenta y 1 exclusivo de POSIX.

**HECHO MEDIDO**, controles sobre el código final:

```text
ruff check:            All checks passed!
ruff format --check:   378 files already formatted
mypy --platform linux: Success: no issues found in 260 source files
mypy Windows, runner y sus tests: Success: no issues found in 5 source files
pre-commit --all-files: Passed en todos, incluido "Detect hardcoded secrets"
git diff --check:      exit=0
uv.lock, src/, .github/, CLAUDE.md, .claude/, docs/adr/ en el diff: 0
```

**HECHO MEDIDO**, CI:

```text
930fae8 (rama):  Lint, types and tests success | Secret scan (gitleaks) success
c6a54ec (merge): Lint, types and tests success | Secret scan (gitleaks) success
```

**Límite de esta evidencia:** los logs de CI exigen iniciar sesión (HTTP 403), así que no se leyeron sus
conteos. **HECHO DEL REPOSITORIO:** `ci.yml` no excluye ninguna prueba, y un test exige que fuera de Windows
no se omita ninguna.

**Revisión de seguridad** (`security-reviewer`, solo lectura): sin hallazgos bloqueantes para O1.2.

| Corregido en O1.2 | Motivo |
|---|---|
| Git por ruta absoluta, y lanzador sin cambiar de carpeta | En Windows, `git` a secas buscaría antes en la carpeta actual |
| Caracteres de control rechazados en la especificación y en nombres | Podrían falsear la pantalla de aprobación |
| Secretos limpiados del título, del informe local y de la consola; logs limpiados también ante Ctrl+C | El texto libre se mostraba antes de escanearlo |
| `core.hooksPath` vacío rechazado | Desactivaría los hooks en silencio |
| Número exacto de omitidas | `--deselect` también omite lo que empiece igual |
| Proceso posiblemente huérfano bloquea en todos los caminos | Solo lo hacía con el ejecutor |
| `hooks/` e `info/` en la foto, y verificación del `.git` de la copia | Un hook o `info/attributes` podían pasar sin detectarse |
| Binarios y `gitleaks:allow` rechazados | Gitleaks no los revisaría |
| Enlaces y junctions detectados en toda la copia; `Cleanup` se niega si los hay | Podrían sacar la evidencia de la copia o afectar al borrado |
| Bloqueados `ruff.toml`, `pytest.ini`, `mypy.ini`, `conftest.py` y similares, y cambios en `[tool]` | Podrían neutralizar los controles |
| Validación estricta de los argumentos de Git y de la forma de `commit` | Git acepta abreviaturas como `--no-verif` |

## 9. Métricas

| Métrica | Valor | Método |
|---|---|---|
| `scripts/orchestrator.py` | 2.274 líneas (estimado: 700–900) | `git diff --stat` |
| Diff del PR #60 | 9 archivos, +5.001 / −9 | `git diff --stat` |
| Pruebas unitarias | 302 | pytest |
| Duración de la suite en Windows | 12 min 35 s; línea base sin las pruebas del runner: 3 min 42 s | pytest |
| Duración de la Parte A | 6 min 18 s | pytest |
| Arranques suspendidos sin escape | 50 de 50 | Test `windows_only` |
| PR #60, de apertura a merge | 5 min 48 s | Marcas de tiempo de la API |

**El ahorro de pasos manuales no se midió.** Corresponde a O1.5.

## 10. Aportes de Claude Code

| Sesión | Qué hizo | Quién revisó |
|---|---|---|
| `bb23d2bc-80dc-4076-9953-97eebc08161d` | Auditoría O1.2-A, implementación, pruebas, Partes A y B y este cierre | Juan autorizó cada etapa, creó y fusionó el PR #60 |
| Subagente `security-reviewer`, dentro de esa sesión | Revisión de seguridad de solo lectura | Claude Code aplicó lo que cabía en el alcance |

El identificador se verificó por la existencia de la transcripción local. El subagente no se registra con
un identificador verificable propio en este documento.

## 11. Aportes de Codex

Nada que registrar. Los worktrees `A`, `B` y `Elsa-ai-4-1b`, de trabajo anterior, no se tocaron.

## 12. Operaciones manuales y de PowerShell

Registradas como **medidas por Juan**: creación del PR #60, merge del PR #60 y sincronización de `main` en la
carpeta principal.

Ejecutadas por Claude Code fuera del repositorio versionado: `inbox\T0.1.md`, que se conserva; `logs\t0-1\` y
`state\runner.lock`, creados por la Parte B; y la copia `o1-2-cierre`.

## 13. Incidentes

1. **Fallas ajenas en Windows.** La suite ya fallaba sobre `main` limpio. Era una condición de parada: se
   detuvo el trabajo y decidió Juan. **Pendiente** (§20).
2. **`mypy` fallaba en Windows** por 3 errores ya existentes en `src/elsa/bench/runner.py`, por lo que el
   control habría bloqueado siempre. Se alineó con CI (§5).
3. **Los hooks reales crean cachés.** La Parte A falló la primera vez con `ignored_file_present`: el runner
   tomaba por sospechosa la caché de un hook. Solo se detectó con hooks reales. Corregido.
4. **Evidencia duplicada.** La Parte A también mostró una etapa de escaneo repetida. Corregido.
5. **Acentos mal mostrados.** El lanzador no tenía la marca de codificación de los demás scripts, y PowerShell
   5.1 mostraba mal sus mensajes. Corregido y fijado por un test.
6. **Nombre de test.** Un test con «onedrive» en su nombre activaba la protección de carpeta sincronizada, por
   su carpeta temporal. Se renombró.
7. **`.git` oculto.** Causa de la única falla de la última suite (§8).
8. **`main` local atrasado tras el merge.** Se detuvo el trabajo porque traer los cambios era un `pull`. Juan
   sincronizó.
9. **Carpeta residual.** `worktrees\o1-1` sigue vacía desde O1.1. El runner la lista como «sin registrar».
10. **Estimación.** El runner triplicó las líneas estimadas por los casos de ataque y el control de procesos.

## 14. Git

Se creó una copia de implementación, una rama de implementación y una de cierre. Sin force push, sin
`reset --hard`, sin `git clean`, sin `branch -D` y sin `worktree prune`. La rama de implementación se publicó a
mano, no desde el runner.

Limpieza medida:

```text
git worktree remove <copia>: exit=0, sin --force
git branch -d claude/o1-2-runner-local-minimo: Deleted branch (was 930fae8), exit=0
```

La rama remota `claude/o1-2-runner-local-minimo` se conserva; Claude Code no borra ramas remotas.

## 15. Ramas

| Rama | Estado |
|---|---|
| `claude/o1-2-runner-local-minimo` | Fusionada por el PR #60; borrada en local con `-d`; se conserva en GitHub |
| `claude/o1-2-cierre` | Este cierre |

## 16. Commits

| Commit | Contenido |
|---|---|
| `7e1f5a9` | Especificación O1.2 |
| `be7ba1f` | Configuración de `mypy` y pytest |
| `f6162d2` | Runner y lanzador |
| `a5078db` | Ejecutor falso y pruebas |
| `930fae8` | Manual |
| `c6a54ec` | Merge del PR #60 en `main` |

El commit de este cierre consta en su propio PR.

## 17. Pull requests

| PR | Estado | CI |
|---|---|---|
| [#60](https://github.com/VallejoOsorio2026/Elsa-ai/pull/60) | Fusionado por Juan | Los dos checks obligatorios en `success` |
| PR de este cierre | Lo crea y fusiona Juan | Debe quedar en verde (ver «Regla de continuidad») |

## 18. Migraciones

No aplica: ninguna escrita ni aplicada. Sin SQLite, PostgreSQL, Redis ni otra base de datos.

## 19. Estado operacional final

| Pieza | Estado |
|---|---|
| Runner local | **En `main`.** `Validate` demostrada en el repositorio real |
| `Run` | Demostrado solo en repositorios desechables |
| Ejecutor real | **No existe.** La consola solo ofrece uno que no cambia nada |
| Control de procesos | Demostrado con procesos Python. **No demostrado con Claude Code real** |
| ELSA funcional | Sin cambios en `src/elsa` |

**INFERENCIA:** Render despliega desde `main`, así que los merges de este bloque pueden haber disparado un
despliegue sin cambios funcionales. No se verificó en Render.

## 20. Pendientes

| Pendiente | Responsable |
|---|---|
| **PENDIENTE, bloque aparte:** corregir las 3 pruebas que fallan en Windows y vaciar `WINDOWS_KNOWN_TEST_FAILURES` | Juan decide cuándo; toca `src/elsa/bench` y tests |
| **PENDIENTE, bloque aparte:** los 3 errores de `mypy` en Windows en `src/elsa/bench/runner.py` | Con el anterior |
| **PENDIENTE, O1.3:** primer `run` real, que debe ser un cambio pequeño que termine en PR para que `git branch -d` funcione tras el merge | Juan autoriza |
| **PENDIENTE, O1.3:** demostrar que el control de procesos alcanza el árbol real de Claude Code | O1.3 |
| **PENDIENTE, O1.3:** aceptar o no el riesgo de aislamiento: un ejecutor real corre con el usuario de Windows | Juan |
| **PENDIENTE, O1.3:** vigilar la configuración global de Git (`core.fsmonitor`, `core.hooksPath`) | O1.3 |
| **PENDIENTE, O1.3:** lista de exclusiones por ruta de gitleaks, que no se anuló | O1.3 |
| **PENDIENTE, O1.3:** `.pyc` y cachés envenenados en las carpetas toleradas | O1.3 |
| **PENDIENTE, O1.3:** una edición que conserve tamaño y fecha no se ve en `git diff` | O1.3 |
| **PENDIENTE, O1.3:** limpieza parcial de secretos en los logs: nunca se versionan | O1.3 |
| **PENDIENTE:** un bloque que solo borra archivos probablemente termine en `secret_scan_skipped`; se detiene y no pasa de largo. Sin probar | O1.3 |
| **PENDIENTE:** decidir si el repositorio sigue público, y si `.env` se sincroniza con la nube | Juan, aparte |
| **PENDIENTE:** retirar `inbox\T0.1.md` y la carpeta vacía `worktrees\o1-1` | Juan, si lo desea; no afectan a nada |
| **PENDIENTE:** el resto de O1, de O1.3 a O1.5 | Requiere autorización de Juan (regla 20) |

## 21. Siguiente bloque

**O1.3 — Claude real y prueba de bloqueo**, solo si Juan lo autoriza. Es el punto de decisión de O1: si no se
demuestra que merge, push, lectura de `.env` y edición externa quedan bloqueados, O1 se detiene y se conserva lo
construido hasta aquí.

---

## Criterios de cierre

| Criterio | Resultado |
|---|---|
| Runner, lanzador y ejecutor falso implementados | **Cumplido** |
| Solo ejecutor falso; sin Claude real | **Cumplido** |
| Pruebas unitarias e integración local | **Cumplido** (§8, con su salvedad) |
| Pruebas Windows de procesos y lock | **Cumplido** |
| Timeout mata hijos y nietos, según alcance demostrado | **Cumplido** con procesos Python |
| Worktrees ajenos y `main` intactos | **Cumplido** |
| Diff fuera de alcance, rutas prohibidas, índice y `HEAD` | **Cumplido** |
| Gitleaks real integrado | **Cumplido** |
| Evidencia sanitizada | **Cumplido** |
| Comandos desde la especificación prohibidos | **Cumplido** |
| Sin push, merge, force, `reset --hard`, `git clean` ni `branch -D` | **Cumplido** |
| Sin dependencias nuevas | **Cumplido** |
| Parte A | **Cumplido** |
| PR funcional con CI verde | **Cumplido** |
| Parte B con repositorio idéntico | **Cumplido** |
| Documento de cierre | **Este documento** |
| Segundo PR con CI verde y merge aprobado por Juan | **Se cumple al fusionar este cierre** |
| `main` limpio y sincronizado | **Se verifica al fusionar este cierre** |

## Regla de continuidad

O1.2 queda cerrado solo cuando este documento esté en `main` con los checks obligatorios en verde y `main` limpio
y sincronizado. Aun después, O1.3 requiere autorización explícita de Juan.

## Veredicto

**O1.2 cumple su alcance.** El runner existe, se detiene ante cada caso probado y valida el repositorio real sin
cambiarlo. **No demuestra nada sobre un ejecutor real:** eso le corresponde a O1.3.
