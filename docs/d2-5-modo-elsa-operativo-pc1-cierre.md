# Cierre formal — D2.5: Modo ELSA mínimo operativo en PC1

- **Fecha:** 2026-10-18 (UTC). El PR funcional #52 se abrió a las 17:52:22 UTC y se mergeó a
  las 17:55:43 UTC.
- **Estado:** cierre formal de D2.5, **efectivo cuando este documento quede integrado en
  `main` con el CI obligatorio en verde** (ver «Regla de continuidad»).
- **Qué cierra:** el subbloque **D2.5** del bloque D2 (acceso remoto seguro a ELSA). D2.5 deja
  una forma **operativa, local y controlada** de preparar el nodo PC1: un operador ejecuta
  START, STATUS y STOP, y un supervisor en primer plano arranca ELSA local (127.0.0.1, modo
  LOCAL, relay propio apagado), espera a que esté lista, arranca el agente de PC1 y detiene los
  dos en orden.
- **Qué NO cierra:** **no cierra D2.** No hay despliegue real de Render, conexión real
  Render ↔ PC1, token real del nodo, URL definitiva del relay, medición de latencia de Internet
  ni de timeouts de Render, prueba desde PAPELSA ni conectividad corporativa. Phi no participa
  en `assistant.ask`. **No hay acceso remoto funcionando.** Ver §20.
- **Prerrequisitos:** D2.1, D2.2, D2.3 y D2.4
  ([`d2-4-integracion-extremo-a-extremo-cierre.md`](d2-4-integracion-extremo-a-extremo-cierre.md)),
  los cuatro cerrados formalmente.
- **Identificador del bloque:** `D2` / `D2.5` es la nomenclatura de trabajo del proyecto. El
  nombre de este archivo lleva `d2-5` para que **no pueda leerse como el cierre de D2**.
- **Decisión técnica:** [ADR 0034](adr/0034-modo-elsa-operativo-pc1-pilot-0-1.md). Operación:
  [`pc1-modo-elsa-runbook.md`](pc1-modo-elsa-runbook.md).
- **Marcas de afirmación** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**,
  **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Sanitización:** este documento no contiene secretos, tokens, hashes de credenciales,
  correos, claves, cadenas de conexión, IP públicas, identificadores de usuario, rutas de perfil
  de usuario, cuerpos de solicitudes o respuestas reales, contenido de logs reales ni datos de
  planta (reglas 11 y 12). Los tokens usados en las pruebas son marcadores sintéticos y aquí no
  se reproducen.

---

## 1. Objetivo

Pasar de «tenemos componentes técnicos» (ELSA local y agente, cada uno arrancado a mano) a
«tenemos una forma operativa y controlada de levantar el nodo PC1», sin que el operador
necesite conocer uvicorn, módulos de Python, PIDs, puertos internos ni el orden de arranque o
parada:

```text
OPERADOR PC1 → Start-ElsaMode.ps1
   → preflight → ELSA local (127.0.0.1, LOCAL) → readiness → agente outbound-only
   → EN MARCHA (conectividad con Render NO VERIFICADA)
```

Con una operación igual de clara para el **estado** y la **parada**.

## 2. Alcance

**Entró (DECISIÓN TOMADA, microplan aprobado con D1–D9):**

- Supervisor Python en primer plano (`python -m elsa.pc1 start|status|stop`) y tres wrappers
  PowerShell (`Start-ElsaMode.ps1`, `Get-ElsaModeStatus.ps1`, `Stop-ElsaMode.ps1`).
- Preflight del perfil PC1, readiness, instancia única, estado de runtime, propiedad de
  procesos, Job Object de Windows, rollback, parada ordenada y logs.
- `SIGBREAK` ordenado en el agente de D2.3 (única modificación de código existente).
- ADR 0034, runbook del operador, `docs/environment-variables.md` y `docs/architecture.md`.

**Quedó fuera (explícito):**

- Render real, deploy, token real del nodo, URL definitiva del relay, red real, prueba desde
  PAPELSA.
- Phi/llama.cpp: el Modo ELSA no lo arranca, no lo detiene ni lo declara.
- Servicio de Windows, Task Scheduler, firewall, puertos públicos, port forwarding, VPN,
  túneles, privilegios de administrador.
- Cambios en protocolo V1, `RelayService`, ruta de D2.4, Materiales, Supabase, frontend, LLM y
  `render.yaml`.
- Reinicio automático de componentes.
- Base de datos, migraciones, Redis y dependencias nuevas.

## 3. Estado inicial

- **Rama base:** `main` en `f0884420cee9a9016fe933e70f00577223a7abc2` (merge del PR #51, cierre
  documental de D2.4), con CI de `main` en verde (run 39137716519).
- **HECHO DEL REPOSITORIO (auditoría del microplan):**
  - ELSA se arrancaba a mano (`uvicorn elsa.main:create_app --factory`, README) y se detenía con
    Ctrl+C; no existía lanzador ni estado de runtime para ELSA ni para el agente.
  - El agente (`python -m elsa.agent`) validaba su configuración y rechazaba el token en
    archivo, pero solo convertía Ctrl+C en salida ordenada: no atendía `SIGBREAK`.
  - `scripts/Start-ElsaLlm.ps1` / `Stop-ElsaLlm.ps1` gestionaban solo `llama-server`
    (`%LOCALAPPDATA%\ELSA\llm`) y no eran el Modo ELSA. `Stop-ElsaLlm.ps1` forzaba el cierre de
    inmediato porque el proceso no tiene ventana principal.
  - **No existía ningún «Modo E1» ejecutable.** «E1» solo aparece como escenario de evaluación
    de embeddings y como identificador de evidencia.
  - `/api/v1/health/ready` devuelve `degraded` siempre en la configuración actual (transcripción
    simulada, dependencias planificadas `not_configured`).
  - `assistant.ask` en modo LOCAL no usa el LLM.

## 4. Trabajo realizado

En orden, por unidades probadas antes de seguir:

1. **Gate D2.4 y microplan.** Gate verificado (documento en `main`, veredicto SÍ, CI verde). Se
   creó la rama `claude/d2-5-modo-elsa-operativo` y se entregó un microplan con 6
   inconsistencias reportadas antes de escribir código (§13). El responsable aprobó D1–D9 con
   ajustes.
2. **ADR 0034.**
3. **Runtime** (`src/elsa/pc1/runtime.py`): directorio, bloqueo, `state.json`, `stop.request`,
   rotación de logs.
4. **Preflight** (`preflight.py`).
5. **Procesos propios y Job Object** (`processes.py`).
6. **`SIGBREAK` del agente** (`src/elsa/agent/__main__.py`).
7. **Supervisor** (`supervisor.py`) y **CLI** (`__main__.py`).
8. **Wrappers PowerShell.**
9. **Documentación:** runbook, variables de entorno y arquitectura.
10. **Revisión integral pre-PR**, con 8 correcciones menores (§13).

### 4.1 Definición de Modo ELSA (HECHO DEL REPOSITORIO)

```text
Supervisor (ventana «Modo ELSA», primer plano)
 ├── ELSA local   uvicorn elsa.main:create_app --factory --host 127.0.0.1 --port N
 │                --no-access-log --no-proxy-headers --timeout-graceful-shutdown 10
 └── Agente PC1   python -m elsa.agent --env-file <raíz del repo>/.env   (outbound-only)
```

| Clase | Componentes |
|---|---|
| Obligatorios | Preflight, ELSA local, readiness, agente, instancia única, `state.json`, logs, START/STATUS/STOP |
| Opcionales | Ninguno |
| Fuera de D2.5 | Phi/llama-server, conectividad real con el relay, arranque automático |

### 4.2 START (HECHO DEL REPOSITORIO)

```text
lock → limpiar state.json y stop.request residuales → configuración → puerto
→ Job Object → ELSA local → readiness → agente → gracia (5 s) → EN MARCHA
```

El agente **jamás** se inicia antes de readiness. Un `stop.request` residual se borra con el
lock tomado y nunca se interpreta como orden para la instancia nueva. Los logs solo se rotan
cuando el preflight ya pasó.

### 4.3 Readiness (HECHO DEL REPOSITORIO)

| Respuesta de `GET /api/v1/health/ready` | Estado | ¿Arranca el agente? |
|---|---|---|
| 200, `status=ok` | **LISTA** | Sí |
| 200, `status=degraded` | **LISTA CON DEGRADACIONES NO CRÍTICAS** (solo nombres, nunca `detail`) | Sí |
| 503, sin conexión, body inválido, ambiente distinto | **NO LISTA** | No: rollback |

Para un 200, el hijo ELSA debe estar vivo **antes y después** de la respuesta. La sonda usa
`http.client` contra `127.0.0.1` (sin proxies del entorno). Ninguna salida afirma conexión con
Render: la línea del relay es siempre «**Relay Render: conectividad NO VERIFICADA**», y un test
comprueba que nunca aparecen `CONNECTED`, `ONLINE` ni `CONECTADO`.

### 4.4 STATUS (HECHO DEL REPOSITORIO)

Estados: **ARRANCANDO**, **EN MARCHA**, **DEGRADADO** (ELSA no responde o devuelve 503, un hijo
terminó y empieza la parada, o el latido del supervisor tiene más de 20 s), **DETENIÉNDOSE** y
**DETENIDO** (sin supervisor).

`status` es de solo lectura: no crea `supervisor.lock` si no existe, no modifica archivos y
tolera un `state.json` manipulado o inválido (puerto fuera de rango, fecha imposible) sin
traza. Para saber si hay supervisor intenta tomar el bloqueo y lo suelta al instante.

### 4.5 STOP (HECHO DEL REPOSITORIO)

- El comando `stop` externo **no mata procesos**: crea `stop.request` y espera hasta 60 s a que
  el supervisor libere el bloqueo. Ctrl+C en la ventana tiene el mismo efecto.
- El supervisor detiene **agente → ELSA**: `CTRL_BREAK_EVENT`, espera (10 s y 20 s) y, solo si
  vence el plazo, `kill` sobre **su propio handle**, informado al operador como cierre forzado.
- La parada es *best effort*: un paso fallido no impide los siguientes, y lo que no se pudiera
  detener en orden lo termina el cierre del Job Object.

### 4.6 Preflight y perfil PC1 (HECHO DEL REPOSITORIO)

Reutiliza `load_settings` y `load_agent_config` sin duplicar reglas. Falla cerrado, y nombra
variables sin repetir valores, si no se cumple:

| Requisito | Además |
|---|---|
| `ELSA_ASSISTANT_EXECUTION_MODE=local` | Se **fija** en el entorno del hijo ELSA |
| `ELSA_RELAY_ENABLED=false` | Se fija en el entorno del hijo ELSA |
| `ELSA_DEBUG=false` | Se fija en el entorno del hijo ELSA |
| `ELSA_AGENT_LOCAL_BASE_URL` con host exacto `127.0.0.1` y puerto 1–65535 | Única fuente del puerto de uvicorn |
| URL del relay `https`, token fuera del archivo | Reglas del agente de D2.3 |
| Puerto libre (conexión de prueba + bind exclusivo) | Ocupado por un proceso ajeno → fail-closed, sin identificarlo ni tocarlo |
| `.env` legible como UTF-8 | Un UTF-16 de PowerShell 5.1 → mensaje fijo |

No se crea ninguna variable de entorno nueva; bind `127.0.0.1` es constante.

### 4.7 Instancia única y estado de runtime (HECHO DEL REPOSITORIO)

- Runtime en `%LOCALAPPDATA%\ELSA\mode\`, fuera del repositorio y de OneDrive. Sin
  `LOCALAPPDATA` absoluto, falla cerrado: no hay fallback a `cwd`, repo ni `TEMP`.
- `supervisor.lock`: `msvcrt.locking` sobre el **byte 0 real** (se escribe si el archivo está
  vacío), con `seek(0)`, retenido toda la vida del supervisor. `fcntl.flock` en POSIX, solo para
  tests. Un segundo START sale con código 3.
- Con el lock libre: `state.json` y `stop.request` residuales se limpian **sin enviar ninguna
  señal** a los PIDs que contengan.
- `state.json`: escritura atómica, esquema cerrado por lista blanca, puerto 1–65535, PID > 0,
  sin secretos. Los PIDs son informativos: **nunca** conceden propiedad ni se usan para señalar.
  Si no puede escribirse (en Windows, `os.replace` falla mientras otro proceso lo tiene
  abierto), se registra y se sigue; nunca detiene el nodo.
- El latido se renueva durante ARRANCANDO (cada sondeo y durante la gracia), EN MARCHA (cada
  5 s) y DETENIÉNDOSE (al entrar y antes de cada espera de parada).

### 4.8 Propiedad de procesos y Job Object (HECHO DEL REPOSITORIO)

- Solo se actúa sobre `OwnedProcess`, que envuelve el `Popen` creado por el supervisor. No hay
  `os.kill(pid)`, `taskkill`, `Stop-Process`, búsqueda por nombre ni acción sobre el dueño de un
  puerto (verificado por las dos revisiones).
- Cada hijo nace con `CREATE_NEW_PROCESS_GROUP`: el Ctrl+C del operador llega solo al
  supervisor.
- Job Object (ctypes): `CreateJobObjectW`, `SetInformationJobObject` con
  `JOBOBJECT_EXTENDED_LIMIT_INFORMATION` y `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`,
  `AssignProcessToJobObject` y `CloseHandle`. Errores comprobados, handle no heredable, cierre
  idempotente. Si la asignación falla, el hijo se termina y el error se propaga.
- Si el supervisor muere de forma abrupta, el sistema termina los hijos. **No es un cierre
  ordenado**: solo garantiza que no queden huérfanos.
- **Lanzador del venv:** en Windows, `.venv\Scripts\python.exe` crea el intérprete real como
  hijo. La garantía no depende solo del PID del `Popen`: los tests verifican que el intérprete
  real queda **dentro** del Job Object y que muere tras el cierre forzado, el cierre del job y la
  muerte del supervisor.

### 4.9 SIGBREAK / CTRL_BREAK (HECHO DEL REPOSITORIO)

`src/elsa/agent/__main__.py` instala, **solo si `signal.SIGBREAK` existe**, un manejador que
sigue el mismo camino que Ctrl+C. Con un manejador de SIGINT invocable (el de `asyncio.run`)
cancela la tarea principal. Con `SIG_IGN` o `SIG_DFL` lanza `KeyboardInterrupt`, y `asyncio.run`
cancela las tareas al cerrar. En los tres casos se ejecutan los `finally` del agente. Ctrl+C,
los códigos de salida y Linux no cambian. Runner y protocolo intactos.

### 4.10 Rollback y fallos (HECHO DEL REPOSITORIO)

| Caso | Comportamiento |
|---|---|
| ELSA no llega a READY en 120 s, o termina antes | El agente no arranca; se detiene ELSA; salida 1 |
| El agente muere durante la gracia | Rollback completo |
| El agente o ELSA terminan en ejecución | DEGRADADO, se detiene el otro en orden, salida 1. **Sin reinicio automático** |
| 503 de ELSA en ejecución | DEGRADADO sin parar; vuelve a EN MARCHA si se recupera |
| Error interno inesperado | Parada en orden, mensaje fijo con la ruta de `supervisor.log`; se registra solo el tipo de error |
| Ctrl+C o fin de entrada en el prompt del token | «Inicio cancelado», nada arrancado |
| Carpeta de runtime inutilizable | Mensaje fijo, sin traza |

### 4.11 Secretos (HECHO DEL REPOSITORIO)

- `ELSA_AGENT_NODE_TOKEN` solo llega desde el entorno del proceso o desde `getpass`, y solo
  después de que `load_agent_config` comprobara que **no** está en el archivo.
- El token de `getpass` **no se escribe en `os.environ`**: se valida con las reglas de formato
  del agente y vive en el `SecretStr` del perfil del supervisor, y de ahí pasa al entorno
  construido para el hijo agente. No se afirma un borrado seguro de la memoria de Python.
- El hijo ELSA recibe una copia del entorno con la variable **eliminada explícitamente**.
- Nunca en argv, `.env`, `state.json`, logs, argumentos de PowerShell (los wrappers tienen
  `param()` vacío), mensajes ni documentación.

### 4.12 Logs (HECHO DEL REPOSITORIO)

`%LOCALAPPDATA%\ELSA\mode\logs\`: `supervisor.log` (JSON con eventos, PIDs, códigos y nombres),
`elsa-local.log` y `agent.log`, más el `.prev.log` del arranque anterior; no se guarda nada más.
La salida de los hijos nunca va a la consola. Ante un fallo el operador ve un mensaje fijo y la
ruta del log. Ante un error inesperado se registra solo el **tipo** de excepción, nunca
`str(exc)` ni `repr(exc)`.

### 4.13 Wrappers y runbook (HECHO DEL REPOSITORIO)

Los wrappers invocan `.venv\Scripts\python.exe -m elsa.pc1 …` (sin `uv run`: operar el nodo no
sincroniza dependencias ni toca la red). Si la política de PowerShell los bloquea, el fallback
documentado es exclusivamente:

```text
.venv\Scripts\python.exe -m elsa.pc1 start
.venv\Scripts\python.exe -m elsa.pc1 status
.venv\Scripts\python.exe -m elsa.pc1 stop
```

No se documenta `ExecutionPolicy Bypass` ni `Set-ExecutionPolicy`. El runbook está escrito para
un ingeniero: cómo iniciar, el estado, la parada, qué significan LISTA, LISTA CON DEGRADACIONES,
NO LISTA y NO VERIFICADA, qué hacer ante cada mensaje, dónde están los logs y qué no hacer.

### 4.14 Phi (HECHO DEL REPOSITORIO)

**PHI REQUERIDO POR D2.5 = NO.** `assistant.ask` en modo LOCAL no usa el LLM:
`Container.require_llm()` no se llama desde la API y `GroundedGenerationService` solo lo usa la
CLI `elsa.tools.llm_runtime`. El Modo ELSA no arranca, no detiene ni declara llama.cpp/Phi.

## 5. Decisiones

| # | Decisión | Motivo |
|---|---|---|
| D1 | Supervisor Python en primer plano + 3 wrappers PowerShell | Reutiliza la validación existente, propiedad por handle, testable con pytest, 0 dependencias |
| D2 | El perfil PC1 exige y fija `local`, relay apagado y debug apagado | Menos superficie; refuerza la prevención de recursión |
| D3 | Fallo de cualquier hijo → parada completa, sin reinicio automático | ELSA aislada no cumple el objetivo remoto; un fallo fatal del agente se repetiría |
| D4 | `SIGBREAK` ordenado en el agente | Única señal que el supervisor puede enviar a un hijo concreto en Windows |
| D5 | Job Object con `KILL_ON_JOB_CLOSE` | Impide huérfanos si el supervisor muere |
| D6 | Token solo del entorno o de `getpass` | Nunca en archivo ni en argv |
| D7 | Runtime en `%LOCALAPPDATA%\ELSA\mode\` | Convención existente, fuera del repo |
| D8 | Puerto derivado de `ELSA_AGENT_LOCAL_BASE_URL` | Una sola fuente; sin variables nuevas |
| D9 | Alcance de 20 archivos (16 creados + 4 modificados) | Aprobado; el cierre va en un PR documental aparte |

**DECISIÓN TOMADA** por el responsable al aprobar el microplan, con estos ajustes:

- 20 archivos funcionales y no 21;
- prohibido documentar el bypass de la política de PowerShell;
- se elimina del diseño la prueba manual contra un relay local;
- el token de `getpass` se comprueba después de verificar el archivo.

Arquitectónicamente relevante: **ADR 0034**.

## 6. Pruebas

**HECHO MEDIDO** en la máquina de trabajo (Windows 10) sobre `6e64b79`, que es el árbol
mergeado (§14):

- Tests nuevos:
  - `tests/test_pc1_runtime.py`
  - `tests/test_pc1_preflight.py`
  - `tests/test_pc1_processes.py`
  - `tests/test_pc1_supervisor.py`
  - `tests/test_pc1_cli.py`
  - los tests de `SIGBREAK` en `tests/test_agent_runner.py`
- Integración con **procesos reales** (ELSA falso como servidor HTTP en loopback y agente falso):
  orden de arranque y de parada, el token llega solo al agente y no aparece en argv, logs ni
  estado.
- **uvicorn real** de ELSA bajo el supervisor, con agente falso: arranque, readiness, cierre
  ordenado de uvicorn por `CTRL_BREAK_EVENT` («Application shutdown complete») y sin cierre
  forzado.
- **Ctrl+C con consola real** (consola propia oculta y `GenerateConsoleCtrlEvent`): solo lo
  recibe el supervisor, y los hijos se detienen por su `CTRL_BREAK`, agente → ELSA.
- **E2E de la CLI** con procesos separados: start → status (EN MARCHA) → segundo start
  (código 3) → stop → stop repetido → status (DETENIDO). Un marcador sintético de token no
  apareció en el argv de ningún `python.exe`, en el runtime ni en stdout/stderr. ELSA lo vio
  ausente y el agente presente. 0 procesos huérfanos.
- **Sin red:** ningún test usa Render, Internet, Supabase, Materiales ni Phi.

## 7. Comandos relevantes

Operador (en la raíz del repositorio):

```powershell
.\scripts\Start-ElsaMode.ps1
.\scripts\Get-ElsaModeStatus.ps1
.\scripts\Stop-ElsaMode.ps1
```

Verificación:

```bash
uv run pytest tests/test_pc1_runtime.py tests/test_pc1_preflight.py tests/test_pc1_processes.py \
  tests/test_pc1_supervisor.py tests/test_pc1_cli.py tests/test_agent_runner.py \
  tests/test_agent_config.py tests/test_agent_end_to_end.py
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy --platform linux
uv run pre-commit run --all-files
git merge-base --is-ancestor 6e64b79a9aa54ebbb1b7551c416447aa3e0a248f origin/main
git diff 6e64b79a9aa54ebbb1b7551c416447aa3e0a248f 550aab67eb8d0916ee7aef34226909575408df96
```

## 8. Resultados

**HECHO MEDIDO**, salida real:

```text
# Tests dirigidos (8 archivos)
253 passed, 1 skipped, 2 warnings in 57.70s
SKIPPED tests\test_pc1_processes.py: POSIX has no job object

# Suite completa
2 failed, 2144 passed, 231 skipped, 3 warnings in 253.13s
FAILED tests/test_bench_harness.py::test_a_run_records_what_produced_it
FAILED tests/test_bench_harness.py::test_peak_memory_is_measured_where_the_posix_api_exists

# Calidad
ruff check .                  → All checks passed!
ruff format --check .         → 361 files already formatted
mypy --platform linux         → Success: no issues found in 255 source files
mypy (Windows)                → 3 errors in src/elsa/bench/runner.py (getrusage, RUSAGE_SELF, unused ignore)
git diff --check origin/main...HEAD → limpio
pre-commit run --all-files    → todos Passed, incluido «Detect hardcoded secrets» (gitleaks)
```

- Los 2 fallos son el **baseline histórico de Windows** de `tests/test_bench_harness.py`, y
  D2.5 no toca ese archivo. **No se corrigieron** y siguen abiertos fuera de D2.5.
- Los 3 errores de `mypy` en Windows son el baseline de plataforma de `src/elsa/bench/runner.py`.
- Los 231 skipped son los 230 previos (tests de PostgreSQL sin `ELSA_TEST_DATABASE_URL`) más el
  test POSIX del Job Object.
- Las 3 warnings son preexistentes (Starlette, anyio, PyJWT).
- **Regresiones nuevas: 0.**

Windows específico (**HECHO MEDIDO**):

```text
Job Object: IO_COUNTERS 48 B, BASIC 64 B, EXTENDED 144 B (x64); QueryInformationJobObject
            devuelve 144 B; LimitFlags 0x2000; handle HANDLE_FLAG_INHERIT = False
IsProcessInJob(intérprete real del venv) = True en 10/10 lanzamientos
Test del lock tras la corrección: 30/30
Conjunto sensible final (Job Object, CTRL_BREAK, cierre forzado, supervisor matado,
instancia única, Ctrl+C real, procesos reales, uvicorn real): 10/10 iteraciones,
45 passed + 1 skipped en cada una; sin «Task exception», ResourceWarning ni unraisable;
0 procesos hijos de prueba vivos al terminar
```

## 9. Métricas

**HECHO MEDIDO** con Git y la API de GitHub:

- **Alcance:** 20 archivos (16 creados + 4 modificados), 4902 inserciones y 5 eliminaciones,
  18 commits sobre `main` (`git diff --stat` / `git rev-list --count`).
- **Suite:** 2144 tests pasados, frente a 2120 antes de la revisión pre-PR y 2003 en la
  evidencia de D2.4.
- **Plazos fijados en código** (no medidos en red real):
  - readiness 120 s, con sondeo cada 1 s;
  - gracia del agente 5 s;
  - vigilancia cada 1 s y salud cada 5 s;
  - parada: agente 10 s, ELSA 20 s y espera tras `kill` 5 s;
  - `stop` espera 60 s;
  - latido considerado obsoleto a los 20 s.
- **Dependencias nuevas:** 0. **Base de datos nueva:** NO.

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO / DEL PROCESO.** Claude Code (modelo Claude Opus 5.5):

- verificó el gate de D2.4, auditó el runtime y redactó el microplan con las inconsistencias
  previas al código;
- implementó las 10 unidades de §4;
- descubrió y probó el comportamiento del lanzador del venv;
- lanzó `architecture-reviewer` y `security-reviewer` en solo lectura sobre `1a449e4`;
- aplicó las 8 correcciones de §13;
- ejecutó las verificaciones de §8;
- redactó este documento.

El responsable del proyecto aprobó el microplan (D1–D9 con ajustes), ordenó la revisión integral
pre-PR y **creó y mergeó el PR #52**.

- **Identificador de sesión:** el directorio local de sesión que aparece en las rutas de
  trabajo es `29b70ef1-9764-436a-a361-eee9acaab3f2`. No se contrastó contra otra fuente; se
  registra tal como aparece y **no** se garantiza más que eso.
- **Qué se revisó:** diffs, salidas reales y las dos revisiones de subagentes sobre `1a449e4`.
  Las correcciones posteriores (`78d1b19` … `6e64b79`) se verificaron con tests, repeticiones en
  Windows, lint, tipos, pre-commit y gitleaks, **sin** una nueva ronda de subagentes. Los
  informes de los subagentes se entregaron a la sesión y **no** se versionan.

## 11. Aportes de Codex

Nada que registrar: Codex no participó en D2.5.

## 12. Operaciones manuales y de PowerShell

- Consultas **solo lectura** a la API pública de GitHub, sin autenticación, para el PR #52, el
  merge y las ejecuciones de CI (el entorno de la sesión no tiene `gh`, y no se instaló).
- Ejecución de los wrappers `Get-ElsaModeStatus.ps1` y `Stop-ElsaMode.ps1` (sin nada en
  marcha) y de `Start-ElsaMode.ps1` contra el `.env` de desarrollo, con `LOCALAPPDATA`
  aislado: falló cerrado (código 2, faltan `ELSA_AGENT_RELAY_URL` y `ELSA_AGENT_NODE_ID`) sin
  lanzar procesos. Era el comportamiento esperado.
- Lectura, sin modificarla, de la política de ejecución de PowerShell. No se cambió.
- Experimentos en una carpeta temporal: tamaños de estructura y flags del Job Object,
  `IsProcessInJob`, Ctrl+C en consola real, uvicorn real y E2E de la CLI.
- Durante el primer experimento de Ctrl+C, el supervisor de prueba quedó colgado (§13 #9). Se
  terminó con `Stop-Process` **ese proceso de prueba propio**, identificado por su línea de
  comandos; sus hijos murieron por el Job Object, con 0 restantes. No forma parte del código del
  Modo ELSA, que nunca detiene por PID.
- No se tocó Render, Supabase, Materiales, Phi/llama.cpp, PC1 real, el firewall ni la red.

## 13. Incidentes

| # | Incidente | Qué se hizo | Estado |
|---|---|---|---|
| 1 | Microplan: la instrucción suponía un «Modo E1» ejecutable que no existe | Reportado; no se construyó nada para E1 | Resuelto |
| 2 | Microplan: `/health/ready` siempre `degraded`; el agente no atendía `SIGBREAK`; `Stop-ElsaLlm` fuerza de inmediato; el agente admite cualquier loopback; no existían «perfiles» | Reportados antes de codificar; resueltos por D2, D4 y D8, y con LISTA CON DEGRADACIONES | Resuelto |
| 3 | Ajustes del responsable: 20 archivos y no 21, sin bypass de PowerShell, sin prueba contra un relay local | Aplicados | Resuelto |
| 4 | Los tests de `CTRL_BREAK` fallaron al principio: en Windows `time.sleep` solo lo interrumpe SIGINT | Los procesos de prueba esperan en intervalos cortos; `asyncio` y uvicorn no se ven afectados | Resuelto antes de `22cf247` |
| 5 | `mypy --platform linux` rechazaba `ctypes.WinDLL` en un test | `getattr` documentado | Resuelto antes de `22cf247` |
| 6 | Hallazgo: `.venv\Scripts\python.exe` es un lanzador; el PID de uvicorn no coincidía con el del `Popen` | Tests sobre el PID real del intérprete; ADR 0034 actualizado | Resuelto en `96e4cf1` y `f67609a` |
| 7 | Revisión, MAJOR (ambas): `state.json` no escribible (abierto por `status` o el antivirus) → traza y parada sin orden | Escrituras tolerantes, parada *best effort*, `except Exception` con mensaje fijo | Resuelto en `78d1b19` |
| 8 | Revisión de arquitectura, MAJOR: latido sin renovar en ARRANCANDO y DETENIÉNDOSE | Latido en todas las fases, con test | Resuelto en `78d1b19` |
| 9 | Primer experimento de Ctrl+C colgado: el entorno de la sesión hereda Ctrl+C deshabilitado | El test reactiva Ctrl+C (`SetConsoleCtrlHandler(None, False)`), como una consola normal; se terminó el proceso de prueba propio | Resuelto en `78d1b19` |
| 10 | Revisión de seguridad, MINOR: el token de `getpass` se escribía en `os.environ` | Validación sin `os.environ`, solo en el perfil | Resuelto en `2c37ded` |
| 11 | MINOR: `.env` UTF-16 con traza y puerto 0 aceptado | Mensaje fijo; puerto 1–65535 | Resuelto en `2c37ded` |
| 12 | MINOR: puerto y PID sin rango en `state.json` (`OverflowError` en `status`) | Rangos en `read_state` | Resuelto en `f9e8acb` |
| 13 | MINOR: `status` creaba el lock; rotación antes del preflight; `EOFError` y `OSError` con traza | Corregidos | Resuelto en `892bbc7` |
| 14 | INFO: SIGBREAK con SIGINT `SIG_IGN`/`SIG_DFL` | Comportamiento correcto, con tests | Resuelto en `b2afe54` |
| 15 | INFO: orden del texto del ADR, carreras residuales, entorno del agente | ADR 0034 alineado | Resuelto en `9595a97` |
| 16 | Una de 10 repeticiones falló en `test_the_lock_is_released_when_its_owner_process_dies`: matar al lanzador no libera el lock hasta que muere el intérprete real | Espera acotada en el test; 30/30 y 10/10 después. No era un defecto del producto | Resuelto en `6e64b79` |
| 17 | Al parchear un test, un escape de *heredoc* rompió temporalmente una cadena | Detectado por ruff y corregido antes del commit | Resuelto |
| 18 | Con la salida redirigida, los acentos se ven según la página de códigos | Solo cosmético; en una consola interactiva se ven bien | Registrado |
| 19 | En el E2E, `Start-Process` no devolvió el código de salida del `start` en segundo plano | Su salida terminó en «Modo ELSA detenido.» | Registrado |
| 20 | `mypy` en Windows con 3 errores en `src/elsa/bench/runner.py` | Baseline de plataforma, confirmado con `mypy --platform linux` | Baseline, no se corrige |
| 21 | El SHA del merge se tomó de Git y de la API, no de una captura | `550aab67eb8d0916ee7aef34226909575408df96` | Verificado |

## 14. Git

- **Proceso:** una rama funcional desde `main`, 18 commits, un PR y merge con *merge commit*. No
  se hizo `amend`, `rebase`, `squash` ni `force push`.
- **HECHO MEDIDO — árbol integrado = árbol probado:**
  - `git diff 6e64b79 550aab6` está **vacío** (0 líneas);
  - los padres del merge son `f088442` y `6e64b79`;
  - `git merge-base --is-ancestor 6e64b79… origin/main` retorna éxito.
- **Archivos intactos:**
  - `src/elsa/relay/*` (incluido `protocol.py`);
  - `src/elsa/api/v1/assistant*.py` y `src/elsa/agent/runner.py`;
  - `render.yaml`, `web/`, `supabase/`, `.env.example`;
  - adaptadores y puertos;
  - `pyproject.toml` y `uv.lock`.
- **Creados (16):**
  - `src/elsa/pc1/__init__.py`, `__main__.py`, `preflight.py`, `processes.py`, `runtime.py`,
    `supervisor.py`;
  - `scripts/Start-ElsaMode.ps1`, `Get-ElsaModeStatus.ps1`, `Stop-ElsaMode.ps1`;
  - `tests/test_pc1_cli.py`, `test_pc1_preflight.py`, `test_pc1_processes.py`,
    `test_pc1_runtime.py`, `test_pc1_supervisor.py`;
  - `docs/adr/0034-modo-elsa-operativo-pc1-pilot-0-1.md`;
  - `docs/pc1-modo-elsa-runbook.md`.
- **Modificados (4):**
  - `src/elsa/agent/__main__.py`;
  - `tests/test_agent_runner.py`;
  - `docs/environment-variables.md`;
  - `docs/architecture.md`.
- **Documental de este cierre:** se crea este archivo en la rama
  `docs/closure-d2-5-modo-elsa-operativo`. `docs/architecture.md` **no** se modifica: ya
  registra D2.5 como implementado en código y no operativo en red real (la conectividad con el
  relay no se verifica), y mantiene «Hoy no hay acceso remoto funcionando».

## 15. Ramas

| Rama | Uso | Estado |
|---|---|---|
| `claude/d2-5-modo-elsa-operativo` | Trabajo funcional de D2.5 | Mergeada vía PR #52; **no eliminada** todavía |
| `docs/closure-d2-5-modo-elsa-operativo` | Este documento | Creada desde `main` (`550aab6`); su PR y su merge los registra GitHub |

## 16. Commits

| Commit | Mensaje |
|---|---|
| `73288e4cfae3334220a5f56462b413a784c45946` | `docs(adr): add ADR 0034 for the PC1 ELSA mode` |
| `1b7b1b8f816b799d27f14de45deefdd6be5a8b6c` | `feat(pc1): runtime directory, single-instance lock and state file` |
| `8ce0ff13aae393182f6f37164891d24702f127cd` | `feat(pc1): preflight for the PC1 pilot profile` |
| `22cf2477ad12f9c2a1bb0144be835b2000dab191` | `feat(pc1): owned child processes and Windows job object` |
| `2e9c691e9ec5539896573c3962723474a3285e18` | `feat(agent): orderly stop on SIGBREAK` |
| `0c0d615c2817e4adbbe15a4e6ac408e8f209357c` | `feat(pc1): supervisor start, watch and ordered stop` |
| `7c479b2dc974af6f42cc61f7893546bbffc00fd8` | `feat(pc1): start/status/stop CLI and operator messages` |
| `96e4cf19cd5068b2ac26f8a0f27745bb9f13e1b9` | `test(pc1): check the real interpreter behind the venv launcher and real uvicorn` |
| `a817ba80420d8e5b4d3ba631ceeeccf545d7ea7e` | `feat(scripts): PowerShell wrappers for the ELSA mode` |
| `1a449e46dac0e524f17f6337acf817bc1974f622` | `docs: PC1 ELSA mode runbook, environment profile and architecture` |
| `78d1b192997466bfa5930a7bd3d34659d872972f` | `fix(pc1): best-effort shutdown, tolerant state writes and heartbeat in every phase` |
| `2c37dedfec6b536a54476a0fa464e414cb6ea8c3` | `fix(pc1): keep a prompted node token out of os.environ` |
| `f9e8acb026a9eb3ba79952ccbfc6cf3f186dc20e` | `fix(pc1): reject out-of-range ports and PIDs in state.json` |
| `892bbc776e467624faf40280b410b11cc860abe0` | `fix(pc1): read-only status, rotate logs only on a real start, no traces` |
| `b2afe54aecfeaa4c048c69463a2221cc93c7e288` | `test(agent): SIGBREAK with an ignored or default SIGINT handler` |
| `f67609a54d524528eebb67b9cc154bfaa4c12aaa` | `test(pc1): the real interpreter behind the venv launcher is inside the job` |
| `9595a9733d3514a393b1bb2d2a3870474b52314b` | `docs(adr): align ADR 0034 with the pre-PR review fixes and residual risks` |
| `6e64b79a9aa54ebbb1b7551c416447aa3e0a248f` | `test(pc1): wait for the OS to release the lock after its owner dies` |
| `550aab67eb8d0916ee7aef34226909575408df96` | Merge del PR #52 en `main` |

## 17. Pull requests

| PR | Estado | Detalle |
|---|---|---|
| #52 | **Mergeado** el 2026-10-18 17:55:43 UTC | `feat(pc1): add minimum operational ELSA mode`; 18 commits, 20 archivos, +4902 / −5; base `main`, head `claude/d2-5-modo-elsa-operativo` (`6e64b79`); merge `550aab67eb8d0916ee7aef34226909575408df96` |

CI (**HECHO MEDIDO** con la API pública de GitHub, en solo lectura):

| Ejecución | Evento | HEAD | Lint, types and tests | Secret scan (gitleaks) |
|---|---|---|---|---|
| 39143539695 | push (rama) | `1a449e4` | SUCCESS, job 117722642228 | SUCCESS, job 117722642041 |
| 39147962847 | push (rama) | `9595a97` | SUCCESS, job 117735566511 | SUCCESS, job 117735566215 |
| 39149307810 | push (rama) | `6e64b79` | SUCCESS, job 117739497090 | SUCCESS, job 117739496806 |
| 39151567338 | pull_request (#52) | `6e64b79` | SUCCESS, job 117746103411 | SUCCESS, job 117746103244 |
| 39151811362 | push (`main`, merge #52) | `550aab6` | SUCCESS, job 117746827588 | SUCCESS, job 117746827771 |

Revisiones de subagentes (solo lectura, sobre `1a449e4`): **`architecture-reviewer` BLOCKING
NO**, **`security-reviewer` BLOCKING NO**. Sus hallazgos MAJOR, MINOR e INFO se trataron en §13.

## 18. Migraciones

Ninguna. D2.5 no escribió ni aplicó migraciones y no tocó ningún proyecto Supabase (regla 15).

- Base de datos nueva: NO.
- Migraciones: NO.
- Esquema nuevo: NO.
- Redis: NO.
- Supabase nuevo: NO.
- Persistencia de negocio nueva: NO.

`state.json` es estado operativo local, no una base de datos, y no contiene secretos.

## 19. Estado operacional final

**HECHO DEL REPOSITORIO — qué existe en `main`:** lo descrito en §4. Un operador puede iniciar,
consultar y detener el nodo PC1 local con tres acciones.

**Qué funciona (HECHO MEDIDO, en local y sin red):**

- START, STATUS y STOP, con ELSA local real bajo el supervisor y un agente falso.
- El Job Object, `CTRL_BREAK` y Ctrl+C real.
- Instancia única y rollback.

**Qué no está conectado:** Render, relay real, token real y PAPELSA. Con el agente real, la
conectividad con el relay no se verifica en este bloque: STATUS dice «NO VERIFICADA».

**Riesgos residuales (abiertos, no resueltos en este cierre):**

| # | Riesgo | Situación |
|---|---|---|
| 1 | El Job Object y `CTRL_BREAK` no se ejercitan en el CI de Linux | Validados localmente en Windows (§8) |
| 2 | El `python.exe` del venv es un lanzador que crea el intérprete real como hijo | Los tests verifican que el intérprete real entra en el Job Object y muere |
| 3 | Carrera entre la comprobación del puerto y el bind de uvicorn | Ventana estrecha; un proceso local ajeno podría responder mientras uvicorn importa. La segunda defensa es el fallo del hijo o de la vigilancia |
| 4 | Token en el entorno del agente | Legible por procesos del mismo usuario, igual que al lanzar el agente a mano |
| 5 | Entorno del agente | Hereda el resto de variables de la sesión; no hay lista blanca completa en Pilot 0.1 |
| 6 | Logs locales | ELSA puede registrar trazas internas; el runbook prohíbe compartirlos sin revisarlos |
| 7 | Cierre abrupto del supervisor | Los hijos terminan por el Job Object, pero **no** es un cierre ordenado |
| 8 | Restricciones corporativas de PowerShell | Pueden impedir los wrappers; existe el fallback directo con Python sin cambiar la política |
| 9 | Conectividad con Render | NO verificada |
| 10 | Token real del nodo | NO usado |
| 11 | Deploy | NO realizado |
| 12 | Prueba PAPELSA | NO realizada |
| 13 | Phi | Fuera de D2.5 |
| 14 | Baseline de Windows | Los 2 fallos de `test_bench_harness.py` siguen abiertos, fuera de D2.5 |
| 15 | Carreras estrechas de `status` y `stop` con `start` | Fallan cerrado (código 3, o espera de 60 s); documentadas en ADR 0034 §13 |

## 20. Pendientes

Ninguno de estos se cierra por asociación con D2.5.

| # | Pendiente | Responsable / bloque |
|---|---|---|
| 1 | Despliegue real de Render en modo RELAY | Bloque posterior |
| 2 | Configuración real del relay y URL definitiva | Bloque posterior |
| 3 | Generación y custodia del token real del nodo y de su hash | Responsable del proyecto |
| 4 | Primera conexión real Render ↔ PC1 con el Modo ELSA | Bloque posterior |
| 5 | Medición de latencia y timeouts reales (long poll, proxy de Render, plazos del agente) | Bloque posterior |
| 6 | Prueba externa desde un PC de PAPELSA y conectividad corporativa (proxy) | Bloques posteriores |
| 7 | Qué sirve Render con el resto de la API en modo RELAY. Pendiente heredado de D2.4 que estaba asignado a «D2.5»: D2.5 se dedicó al Modo ELSA y **no** lo resolvió | Bloque posterior, con su ADR |
| 8 | Login definitivo | Bloques posteriores |
| 9 | Phi en `assistant.ask`, si algún día se decide | Decisión futura con ADR |
| 10 | Lista blanca del entorno del agente, si se considera necesaria antes de producción | Decisión futura |
| 11 | Baseline de Windows en `test_bench_harness.py` y `mypy` de `bench/runner.py` | Fuera de D2 |
| 12 | Eliminar las ramas `claude/d2-5-modo-elsa-operativo` y `docs/closure-d2-5-modo-elsa-operativo` tras el merge de este documento y el CI final de `main` | Responsable |

## 21. Siguiente bloque

El siguiente subbloque de D2 (conexión real controlada Render ↔ PC1), **solo después** de que
este documento esté integrado en `main` con CI verde y con autorización explícita del
responsable (regla 20). D2.5 deja el nodo PC1 operable de forma local y segura; **no** deja
nada conectado ni desplegado.

---

## Criterios de cierre

| Criterio | Estado |
|---|---|
| PR #52 mergeado; merge SHA real verificado con Git y la API | Cumplido |
| `6e64b79` contenido en `main`; árbol integrado idéntico al probado (`git diff` vacío) | Cumplido |
| 18 commits y 20 archivos (16 creados + 4 modificados) integrados; ADR 0034 y runbook en `main` | Cumplido |
| CI de `main` del merge (run 39151811362) en verde | Cumplido |
| PC1 siempre LOCAL, relay propio apagado y debug apagado, validados **y fijados** en el entorno del hijo ELSA; bind `127.0.0.1` | Cumplido |
| START: ELSA → readiness → agente; el agente nunca antes de readiness | Cumplido |
| Readiness con LISTA / LISTA CON DEGRADACIONES / NO LISTA; hijo vivo antes y después del 200 | Cumplido |
| STATUS de solo lectura y estados cerrados; NO VERIFICADA siempre; nunca CONNECTED/ONLINE/CONECTADO | Cumplido |
| STOP: agente → ELSA; ordenado primero; forzado solo tras el plazo y sobre el handle propio; `stop` externo sin matar | Cumplido |
| Instancia única; residuos limpiados sin señales; puerto ajeno → fail-closed | Cumplido |
| Propiedad solo por handle; ningún kill por PID de archivo; procesos ajenos intactos | Cumplido |
| Job Object `KILL_ON_JOB_CLOSE` validado en Windows, incluido el intérprete real del venv | Cumplido |
| `SIGBREAK` ordenado validado en Windows; Linux, Ctrl+C y códigos de salida intactos | Cumplido |
| Token solo desde el entorno o `getpass`; nunca en archivo, argv, estado, logs, hijo ELSA ni `os.environ` (prompt) | Cumplido |
| Rollback y sin reinicio automático | Cumplido |
| Sin privilegios de administrador, firewall, puerto público, software nuevo ni red real | Cumplido |
| Suite sin regresiones nuevas (2 fallos baseline Windows, 3 warnings preexistentes); ruff verde; mypy Linux verde; pre-commit y gitleaks verdes | Cumplido |
| `architecture-reviewer` y `security-reviewer` sin hallazgos bloqueantes | Cumplido |
| Dependencias nuevas = 0; base de datos nueva = NO; Phi no requerido | Cumplido |
| `docs/architecture.md` coherente con D2.5 | Cumplido (sin cambios en este documental) |

## Regla de continuidad

Este documento **completa el cierre formal de D2.5 al quedar integrado en `main` con el CI
obligatorio en verde**. Su propio PR y su merge documental los registran Git y GitHub. Este
documento **no se auto-referencia** con un SHA propio: hacerlo obligaría a otro cambio solo
para anotarlo. Mientras no esté integrado, D2.5 se considera abierto.

## Veredicto

**D2.5 — MODO ELSA MÍNIMO OPERATIVO EN PC1 CERRADO FORMALMENTE: SÍ**, como estado efectivo al
quedar este documento integrado en `main` con CI verde.

- PR funcional #52 **mergeado** (`550aab67eb8d0916ee7aef34226909575408df96`); CI de `main`
  (run 39151811362) con Lint/types/tests y Gitleaks en **SUCCESS**.
- Revisiones: `architecture-reviewer` BLOCKING NO; `security-reviewer` BLOCKING NO.
- Evidencia funcional preservada sobre `6e64b79`, que es el árbol mergeado:
  - tests dirigidos: 253 passed, 1 skipped, 2 warnings;
  - suite completa: 2144 passed, 231 skipped, 2 failed (baseline Windows), 3 warnings;
  - Windows: 30/30 en el test del lock, 10/10 en el conjunto sensible (45 passed + 1 skipped
    por iteración) y 0 procesos huérfanos;
  - regresiones nuevas: 0.

Estado que se mantiene:

```text
MODO ELSA OPERATIVO LOCAL EN PC1:   SÍ (START / STATUS / STOP)
MODO LOCAL FORZADO EN PC1:          SÍ
RELAY LOCAL DESHABILITADO:          SÍ
NODE TOKEN PERSISTIDO:              NO
PROCESOS AJENOS MODIFICADOS:        NO
PHI REQUERIDO POR D2.5:             NO
PC1 REAL CONECTADO A RENDER:        NO
RED EXTERNA OPERATIVA:              NO
DEPLOY REAL RENDER:                 NO
DEPENDENCIAS NUEVAS:                0
PRIVILEGIOS ADMIN:                  NO
FIREWALL NUEVO:                     NO
PUERTO PÚBLICO PC1:                 NO
```

**D2 sigue abierto**; no hay acceso remoto funcionando. Los pendientes de §20 siguen abiertos y
no se cierran por asociación.
