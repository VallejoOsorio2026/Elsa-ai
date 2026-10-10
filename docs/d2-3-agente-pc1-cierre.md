# Cierre formal — D2.3: Agente PC1

- **Fecha:** 2026-10-10 (UTC). El PR funcional #48 se abrió a las 18:32 UTC y se mergeó a las
  18:48:58 UTC.
- **Estado:** cierre formal de D2.3, **efectivo cuando este documento quede integrado en
  `main` con el CI obligatorio en verde** (ver «Regla de continuidad»).
- **Qué cierra:** el subbloque **D2.3** del bloque D2 (acceso remoto seguro a ELSA). D2.3 es la
  **mitad local** de la comunicación Render ↔ PC1: un agente outbound-only que corre en PC1,
  habla HTTPS long polling con el relay de D2.2 y ejecuta `assistant.ask` exclusivamente
  contra la ELSA local en loopback. Está probado íntegramente con un relay simulado, con el
  relay real de D2.2 en memoria y con la app ELSA en memoria, **sin red real**.
- **Qué NO cierra:** **no cierra D2.** No hay conexión real PC1 ↔ Render, no hay despliegue
  del relay, no existe secreto real del nodo, no hay integración con el navegador ni con el
  usuario (D2.4), no hay login definitivo ni Modo ELSA, y no se ha hecho la prueba en
  PAPELSA. **No hay acceso remoto funcionando.** Ver §20.
- **Prerrequisitos:** D2.1 ([`d2-1-protocolo-render-pc1-v1-cierre.md`](d2-1-protocolo-render-pc1-v1-cierre.md))
  y D2.2 ([`d2-2-relay-gateway-render-cierre.md`](d2-2-relay-gateway-render-cierre.md)),
  ambos cerrados formalmente.
- **Identificador del bloque:** `D2` / `D2.3` es la nomenclatura de trabajo del proyecto. El
  nombre de este archivo lleva `d2-3` para que **no pueda leerse como el cierre de D2**.
- **Marcas de afirmación** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**,
  **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Sanitización:** este documento no contiene secretos, tokens, hashes reales, correos,
  claves, cadenas de conexión, IP públicas, identificadores de usuario, cuerpos de
  solicitudes o respuestas reales ni datos de planta (reglas 11 y 12). Los valores de prueba
  del repositorio son sintéticos (`synthetic-*`) y aquí no se reproducen.

---

## 1. Objetivo

Construir la **mitad local** de la arquitectura remota híbrida de ADR 0029, sobre el relay
de D2.2 y el protocolo V1 de D2.1:

```text
PC PAPELSA
    │  navegador / HTTPS
    ▼
RENDER: relay/gateway (D2.2)
    ↑↓  HTTPS long polling, iniciado siempre por PC1
PC1: agente outbound-only        ← D2.3 (este bloque)
    │  HTTP loopback (IP literal)
    ▼
PC1: ELSA local ─► conocimiento / Materiales / futura IA local
```

El agente debía autenticarse ante el relay, registrar una sesión, mantener el long polling
saliente, recibir `REQUEST`/`CANCEL`, ejecutar `assistant.ask` solo contra ELSA local, devolver
`RESPONSE`/`ERROR`, seguir haciendo poll mientras ELSA trabaja y recuperarse de desconexiones.
Todo ello preservando at-most-once sin replay, protegiendo los secretos y sin puertos ni
tráfico entrante en PC1. Las decisiones de ADR 0029, 0030 y 0031 se **consumieron**, no se
reabrieron.

## 2. Alcance

**Entró (HECHO DEL REPOSITORIO):**

- Paquete `src/elsa/agent/`:
  - `config.py`: configuración validada y fail-closed;
  - `relay_client.py`: cliente HTTPS del relay;
  - `local_client.py`: cliente loopback de ELSA;
  - `runner.py`: sesión, poll, ejecución acotada, CANCEL, entrega y shutdown;
  - `__main__.py`: arranque `python -m elsa.agent`.
- REGISTER, poll, result, renovación de sesión con backoff + jitter, CANCEL best effort,
  shutdown y cleanup.
- Ruta local fija y segura; separación estricta de credenciales; logs sanitizados.
- ADR 0032; variables `ELSA_AGENT_*` en `.env.example` y `docs/environment-variables.md`.
- Pruebas deterministas: relay y ELSA simulados con `httpx.MockTransport`, más E2E con el
  `RelayService` real de D2.2 y la app ELSA real (autenticación fake, datos sintéticos) sobre
  `httpx.ASGITransport`.

**Quedó fuera (explícito):**

- Conexión real a Render; secreto real del nodo; deploy.
- Puertos, firewall, Tailscale, Cloudflare Tunnel, ngrok.
- Base de datos, Redis o disco; dependencias nuevas.
- Cambios a `protocol.py`, al relay D2.2, a `render.yaml`, al frontend, al login, a
  Materiales, a Supabase o a Phi/llama.cpp.
- Modo ELSA definitivo y D2.4.
- `Accept-Encoding: identity` en el cliente local, que queda como riesgo aceptado (§20).

## 3. Estado inicial

- **HECHO DEL REPOSITORIO:** `main = origin/main = ede1cf79e16d90124b169d337f49291b8ef9464d`
  (merge del PR #47, cierre final de D2.2), árbol limpio.
- Existían el protocolo V1 (`protocol.py`), el relay D2.2 (`src/elsa/relay/{store,service,auth}.py`,
  `src/elsa/api/v1/relay.py`) y los ADR 0029, 0030 y 0031. No existía ningún agente.
- El último ADR era el 0031; el siguiente disponible se verificó: **0032**.
- **HECHO MEDIDO** (registrado en el cierre de D2.2): baseline de la suite de 1708 passed,
  230 skipped, 2 failed (baseline Windows) y 3 warnings.

## 4. Trabajo realizado

En orden:

1. Verificación de `main`, creación de la rama `claude/d2-3-pc1-agent` y auditoría dirigida
   de ADR 0029–0031, el relay D2.2, el endpoint `/ask`, la autenticación local, la
   configuración y los tests.
2. **Microplan** de 15 archivos, con las decisiones D1–D9 (§5). Se aprobó con 4 ajustes
   obligatorios:
   1. token del nodo solo desde el entorno del proceso;
   2. toda tarea de ejecución o entrega acotada;
   3. protección contra *busy loop* del poll vacío;
   4. `/result` con 1 envío y como mucho 3 reintentos.
3. Implementación en 7 commits: ADR 0032, configuración, cliente local, cliente del relay,
   runner y arranque, E2E y variables de entorno.
4. **Revisión integral pre-PR**: `architecture-reviewer` y `security-reviewer`,
   reproducciones propias, suite completa. Ningún hallazgo bloqueante, pero sí dos MEDIO
   (AR1, SR1) y varios BAJO/OBSERVACIÓN (§13).
5. **Corrección aprobada** (9 archivos): commits `f74b6bd` y `ab606df`. Siguieron las
   re-revisiones de ambos revisores (BLOCKING: NO).
6. Observaciones de las re-revisiones (compresión y configuración no UTF-8): commit `60b5904`,
   con revisión de seguridad focalizada (BLOCKING: NO).
7. **Última corrección autorizada** (diagnóstico de `compressed_body` y archivo de
   configuración con bytes NUL): commit `bb0fae2`.
8. PR #48, CI y merge (§17).

## 5. Decisiones

| # | Decisión | Motivo | Marca |
|---|---|---|---|
| D1 | 401/403/404 y cualquier otro 4xx del relay en register/poll son **fatales**: el proceso termina con código 2, sin bucle | Un fallo de configuración no se arregla reintentando | DECISIÓN TOMADA (aprobada) |
| D2 | Concurrencia local **1** y cola local **4** por defecto (rangos 1–4 y 0–16) | Alineado con `llm_concurrency = 1` y con `max_pending = 16` del relay | DECISIÓN TOMADA (aprobada) |
| D3 | ELSA local solo en **IP literal de loopback** (127.0.0.0/8 o `::1`); se rechaza `localhost` | No depender de la resolución de nombres | DECISIÓN TOMADA (aprobada) |
| D4 | Relay solo `https`, sin excepción para `http` local | Fail-closed; los tests inyectan transporte | DECISIÓN TOMADA (aprobada) |
| D5 | `trust_env=False` en ambos clientes: se ignoran el proxy del sistema y `.netrc` | Ninguna configuración de entorno puede desviar ni observar el tráfico. Riesgo: un proxy corporativo obligatorio | DECISIÓN TOMADA (aprobada, Pilot 0.1) |
| D6 | `detail` = texto fijo del agente o `local:<code>` de una lista blanca; nunca cuerpo, traza ni `str(exc)` | Distinguir causas sin cambiar el protocolo ni filtrar datos | DECISIÓN TOMADA (aprobada) |
| D7 | Un `request_id` duplicado se **ignora sin responder** | Enviar `DUPLICATE_REQUEST` haría fallar en el relay el original. Concreta ADR 0030 §16: reconocer = detectar e ignorar | DECISIÓN TOMADA (aprobada) |
| D8 | `docs/architecture.md` se actualiza en el cierre, no durante la implementación | Mantener la unidad funcional acotada | DECISIÓN TOMADA (aprobada) |
| D9 | Sin comprobación de salud de ELSA antes de registrar; si ELSA cae, las solicitudes fallan con `LOCAL_UNAVAILABLE` y el sistema lo declara (regla 9) | Simplicidad | DECISIÓN TOMADA (aprobada) |
| A1 | `ELSA_AGENT_NODE_TOKEN` solo desde el entorno del proceso. Si aparece en `.env` o `--env-file`, el agente **no arranca**, aunque también esté en el entorno | Un secreto permanente no se escribe en disco | DECISIÓN TOMADA (ajuste obligatorio; confirmada por el responsable en la corrección) |
| A2 | Rechazos inmediatos (ocupado, expirado al llegar, ruta insegura) por una cola acotada de 16 con **un único** trabajador; nunca `create_task` por rechazo | Tareas acotadas | DECISIÓN TOMADA (ajuste obligatorio) |
| A3 | Poll vacío o descartado: espera mínima inyectable (1 s) | Sin *busy loop* aunque el relay responda de inmediato | DECISIÓN TOMADA (ajuste obligatorio) |
| A4 | `/result`: 1 envío + como mucho 3 reintentos (0,5 / 1 / 2 s), máximo 4 transmisiones del mismo cuerpo, ninguna después de `expires_at` | Cubrir el ACK perdido sin reejecutar | DECISIÓN TOMADA (ajuste obligatorio) |
| C1 | Tras `stale_session`, espera con backoff + jitter antes del REGISTER nuevo; el contador solo vuelve a cero tras un poll exitoso | Frenar el reemplazo mutuo de dos agentes con el mismo nodo (AR1) | DECISIÓN TOMADA (plan de corrección aprobado) |
| C2 | Hacia Render se pide `Accept-Encoding: identity` y un cuerpo comprimido se rechaza sin leerlo, registrado como `compressed_body` | El tope de lectura mide bytes reales (sin bombas gzip) y el rechazo se puede diagnosticar | DECISIÓN TOMADA (corrección autorizada) |
| C3 | Un archivo de configuración no UTF-8 o con bytes NUL se rechaza con un mensaje genérico | Un UTF-16LE sin BOM ocultaría el token a la comprobación «no en archivo» | DECISIÓN TOMADA (corrección autorizada) |

## 6. Pruebas

**HECHO MEDIDO.** Se ejecutaron:

- los tests dirigidos de D2.3 (`tests/test_agent_{config,local_client,relay_client,runner,end_to_end}.py`);
- los tests cercanos (protocolo, servicio y API del relay, configuración, autenticación,
  logging, errores, health y asistente);
- la suite completa;
- `ruff check .`, `ruff format --check .`, `mypy` y `git diff --check`;
- `pre-commit run --all-files`, que incluye gitleaks.

Los tests sin red se pueden repetir; el CI de GitHub sí se consultó en línea (§17).

Comportamiento cubierto (**HECHO DEL REPOSITORIO**):

| Área | Qué cubren los tests |
|---|---|
| Flujo feliz | register → poll → `Request` → ELSA → `Response` → `/result`. También E2E contra el relay real |
| Credenciales | El token del nodo nunca llega a ELSA y el del usuario nunca llega a Render (sobre los bytes enviados). Token solo del entorno. Con el token en `.env`/`--env-file` el agente no arranca, también en UTF-16 y con NUL |
| Rutas | `.`, `..`, `/`, `\`, `%2F`, `%5C`, `%2e%2e`, control, NUL y CR/LF se rechazan sin llamada. Acentos, espacios, `?`, `#` y `%` viajan como un único segmento |
| Errores locales | Conversión de 200, 3xx, 400, 401, 403, 404, 413, 422, 429, 500, 503, timeout, conexión rechazada, JSON inválido, NaN, cuerpo demasiado grande y surrogate no serializable |
| Sesiones | `stale_session` → UUID nuevo sin replay. Dos `stale` simultáneos → una sola transición A→B. REGISTER sin ACK → mismo id. Backoff tras `stale` sin reinicio del contador por REGISTER 200 |
| Reinicio de Render (relay real) | Poll con la sesión vieja → 409 → sesión nueva. Un `REGISTER(A)` reintentado se acepta en el proceso nuevo |
| Concurrencia | Poll continuo mientras ELSA ejecuta. Admisión acotada. Cola de respuestas acotada sin tareas nuevas. Tareas vivas contadas |
| Ritmo | Poll vacío y mensajes descartados con espera mínima. Backoff de red/5xx con techo de 30 s |
| ACK perdido | 1 ejecución y 2 POST (unitario y E2E). Máximo 4 transmisiones. Ninguna después de `expires_at` |
| CANCEL | Antes, durante y después de la ejecución, y desconocido. Liberación del `Request` sin esperar al GC |
| Fallos fatales | 401/403/404/413/422 terminan con código 2 sin reintentos. Un error inesperado termina con código 1 y solo el tipo en el log |
| Robustez del relay | gzip roto, JSON profundo, `long_poll` absurdo, cuerpo comprimido (`compressed_body` frente a `invalid_body`), 409 comprimido siempre rechazado |
| Cleanup | Sin tareas huérfanas ni `Request` retenidos tras éxito, error, cancel, timeout, stale y shutdown |
| Logs y superficie | Logs sin tokens, `Bearer`, pregunta, adjuntos, resultado ni `detail`. Frontera de imports: sin servidores, `subprocess`, FastAPI ni adaptadores |

## 7. Comandos relevantes

```bash
git fetch --all --prune
git diff --stat ede1cf7 7216c01

uv run pytest -q tests/test_agent_config.py tests/test_agent_local_client.py \
  tests/test_agent_relay_client.py tests/test_agent_runner.py tests/test_agent_end_to_end.py
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check origin/main...HEAD
uv run pre-commit run --all-files
```

Arranque del agente en PC1 (valores de ejemplo, nunca reales; **no ejecutado contra Render**):

```powershell
$env:ELSA_AGENT_NODE_TOKEN = "<secreto, solo en esta sesión>"
$env:ELSA_AGENT_RELAY_URL = "https://<relay>"
$env:ELSA_AGENT_NODE_ID = "<id configurado>"
uv run python -m elsa.agent
```

## 8. Resultados

**HECHO MEDIDO**: suite completa sobre el HEAD funcional exacto `bb0fae2`, el mismo árbol
que se mergeó:

```text
2 failed, 1919 passed, 230 skipped, 3 warnings in 125.38s (0:02:05)
FAILED tests/test_bench_harness.py::test_a_run_records_what_produced_it
FAILED tests/test_bench_harness.py::test_peak_memory_is_measured_where_the_posix_api_exists
```

| Comprobación | Resultado |
|---|---|
| Fallos | Los 2 son el **baseline histórico de Windows** (`resource` / `peak_rss_mb` en `tests/test_bench_harness.py`) y no tienen relación con D2.3 |
| Regresiones nuevas | **0**: 1708 → 1919 passed, +211, exactamente los tests de D2.3 |
| Tests dirigidos D2.3 | **211 passed**: config 48, local_client 53, relay_client 46, runner 56, end_to_end 8 |
| Tests cercanos | **230 passed** |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `342 files already formatted` |
| `mypy`, proyecto | 3 errores, todos históricos en `src/elsa/bench/runner.py` (`getrusage`, `RUSAGE_SELF`, `unused-ignore`) |
| `mypy`, paquete y tests de D2.3 | **0 errores** |
| `git diff --check` | limpio; solo avisos LF→CRLF de Windows, no fallos |
| `pre-commit run --all-files` | todos **Passed**, incluido «Detect hardcoded secrets» (gitleaks) |

## 9. Métricas

| Métrica | Valor | Método |
|---|---|---|
| Tests D2.3 | 211 | `pytest --collect-only` sobre `main` (`7216c01`) |
| Diferencia en la suite | 1708 → 1919 passed (+211) | comparación con el baseline del cierre D2.2 |
| Archivos del PR | 15 (13 creados, 2 modificados) | `git diff --name-status ede1cf7 7216c01` |
| Líneas del PR | +4523 / −0 | API de GitHub, PR #48 |
| Commits del PR | 11 | `git log ede1cf7..bb0fae2` y API de GitHub |
| Dependencias nuevas | 0 | `pyproject.toml` y `uv.lock` sin cambios |
| Reproducción AR1 | antes: 21 REGISTER sin espera; después: esperas 1, 2, 4, 8, 16, 30 s | script de la sesión, no versionado |
| Bomba gzip desde el relay | pico de memoria ~670 KiB con el rechazo previo; 146 MiB sin él | medición del revisor de seguridad (tracemalloc), no versionada |

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO / DEL PROCESO.** Claude Code (modelo Claude Opus 5.5) hizo lo
siguiente:

- auditó el repositorio y redactó el microplan;
- implementó el agente, ADR 0032, los tests y la documentación de variables;
- ejecutó las verificaciones de §8 y lanzó las revisiones de subagentes;
- reprodujo y corrigió los hallazgos;
- redactó este documento y la actualización de `docs/architecture.md`.

El responsable del proyecto:

- aprobó el microplan con 4 ajustes;
- confirmó la política fail-closed del token;
- aprobó el plan de corrección de 9 archivos y la última corrección;
- creó y mergeó el PR #48.

- **Identificador de sesión:** el directorio local de sesión que aparece en las rutas de
  trabajo es `87c79258-0f5f-4243-ad81-5b4f950fb108`. No se contrastó contra otra fuente; se
  registra tal como aparece y **no** se garantiza más que eso.
- **Qué se revisó:** diffs, salidas reales de comandos y cinco revisiones de subagentes en
  modo solo lectura (§13): `architecture-reviewer` ×2 y `security-reviewer` ×3. El último
  commit, `bb0fae2`, se verificó con tests y lint, **sin** una nueva ronda de subagentes. Los
  informes de los subagentes se entregaron a la sesión y **no** se versionan.

## 11. Aportes de Codex

Nada que registrar: Codex no participó en D2.3.

## 12. Operaciones manuales y de PowerShell

- Consultas **solo lectura** a la API pública de GitHub, sin autenticación, para obtener el
  estado del PR #48, el merge y las ejecuciones de CI de la rama, del PR y de `main`.
- Scripts de apoyo en el directorio temporal de la sesión, no versionados:
  - reproducción de AR1 y SR1;
  - comprobación empírica de rutas contra httpx y un router FastAPI real;
  - comprobación de redirecciones 301/302/303/307/308 y de la paridad del tamaño en bytes
    con `_wire_size` de D2.2;
  - comprobación del comportamiento real del relay D2.2 ante un reinicio.
- El PR #48 lo **creó y mergeó el responsable del proyecto** desde su navegador: el entorno de
  la sesión no tiene `gh`.
- No se tocó Render, Supabase, Materiales, Phi/llama.cpp, PC1 real, el firewall ni la red.

## 13. Incidentes

| # | Incidente | Qué se hizo | Estado |
|---|---|---|---|
| 1 | Auditoría: `/ask` hoy **no usa Phi** (búsqueda literal más Materiales); el diagrama «ELSA → Phi» describe el futuro | Reportado antes de escribir código; el poll durante la ejecución se diseñó para el peor caso | Registrado |
| 2 | Implementación: `_poll_loop` retenía el último `Request`, con el token del usuario, en sus variables locales. Lo detectó un test de retención con `gc` | El despacho se movió a una función propia y la referencia se suelta enseguida | Resuelto antes del commit `594d915` |
| 3 | E2E: se esperaba 404 para un activo inexistente, pero ELSA devuelve 403 porque autoriza el alcance antes de resolver el activo (regla 3) | Se corrigió la expectativa; el 404 queda cubierto en los tests unitarios | Resuelto en `4bcdf01` |
| 4 | Un comando de shell quedó esperando stdin (`cat >` sin entrada) | Se detuvo la tarea y se rehízo | Sin efecto en el repositorio |
| 5 | El informe de implementación citó el SHA del ADR como `0b0c1e0` | El real es `8212fca`, verificado con Git en la revisión | Corregido en el informe |
| 6 | **AR1 (MEDIO)**: tras `stale_session` el agente se re-registraba sin espera y un REGISTER 200 reiniciaba el contador. Dos agentes con el mismo nodo se reemplazaban en bucle. Reproducido: 21 REGISTER sin espera | Backoff antes de renovar; el contador solo vuelve a cero con un poll OK; test de stale concurrente | Resuelto en `f74b6bd` |
| 7 | **SR1 (MEDIO)**: un surrogate no serializable mataba la tarea del trabajo, no se enviaba resultado y aparecía «Task exception was never retrieved» con el `repr` del resultado en stderr. Reproducido | Degradación a `LOCAL_ERROR local:invalid_response`, captura con solo el tipo, `EXIT_CRASH`, `job.task = None` | Resuelto en `f74b6bd` |
| 8 | BAJO: respuestas ilegibles del relay tumbaban el proceso; el error de URL podía repetir la contraseña; el primer envío no comprobaba `expires_at`; el ADR estaba incompleto sobre el reinicio de Render; el test de frontera era permisivo | Corregidos con tests que fallan sobre el código anterior | Resuelto en `f74b6bd` / `ab606df` |
| 9 | La corrección del plan pedía 1–2 commits y se hicieron 3 (`f74b6bd`, `ab606df`, `60b5904`) | Se informó; no se reescribió historia ya empujada | Aceptado |
| 10 | Un intento de leer con `aiter_raw` rompía todos los tests con respuestas simuladas precargadas | Se volvió a `aiter_bytes` con rechazo previo de `Content-Encoding`, igual de seguro | Resuelto antes de `60b5904` |
| 11 | Un test quedó con un byte NUL literal en el código fuente | Se sustituyó por el escape `\x00` antes del commit | Resuelto antes de `60b5904` |
| 12 | Observaciones finales: un cuerpo comprimido no se distinguía de un JSON ilegible en los logs, y un UTF-16LE sin BOM con el token no se detectaba | `compressed_body` con estado HTTP en el log; rechazo de archivos con NUL | Resuelto en `bb0fae2` |
| 13 | El SHA del merge se tomó de Git y de la API, no de una captura | `7216c017840e55db10f71c18ee00b69d700b7950` | Verificado |

## 14. Git

- Una rama funcional desde `main`, 11 commits, un PR, merge con *merge commit*.
- No se hizo `amend`, `rebase` ni `force push`.
- Archivos prohibidos intactos: `src/elsa/relay/*` (incluido `protocol.py`),
  `src/elsa/api/*`, `render.yaml`, `web/`, `supabase/`, `pyproject.toml` y `uv.lock`.
- **Creados (13):**
  - `docs/adr/0032-agente-pc1-outbound-pilot-0-1.md`;
  - `src/elsa/agent/{__init__,__main__,config,local_client,relay_client,runner}.py`;
  - `tests/agent_fakes.py`;
  - `tests/test_agent_{config,local_client,relay_client,runner,end_to_end}.py`.
- **Modificados (2):** `.env.example` y `docs/environment-variables.md`.
- **Documentales de este cierre:** se modifica `docs/architecture.md` y se crea este archivo,
  en la rama `docs/closure-d2-3-pc1-agent`.

## 15. Ramas

| Rama | Uso | Estado |
|---|---|---|
| `claude/d2-3-pc1-agent` | Trabajo funcional de D2.3 | Mergeada vía PR #48; **no eliminada** todavía |
| `docs/closure-d2-3-pc1-agent` | Este documento y la actualización de `docs/architecture.md` | Creada desde `main` (`7216c01`); su PR y su merge los registra GitHub |

## 16. Commits

| Commit | Mensaje |
|---|---|
| `8212fca272cf160ccd29861ad641cbd33eb4cbab` | `docs(adr): agente PC1 outbound-only para Pilot 0.1 (ADR 0032)` |
| `98dac473c2459616f0882c64a0795fea52d0be9f` | `feat(agent): validated PC1 agent configuration` |
| `9858fd1fbe21b472cd47fe0c9c0332e06cc3f6d0` | `feat(agent): loopback ELSA client for assistant.ask` |
| `e717f2602eaf99a634ceefbe89a23e8b01cd31bd` | `feat(agent): relay HTTPS client for register, poll and result` |
| `594d9156a60c9e61266e5053e344ec4a5db18724` | `feat(agent): session lifecycle, bounded execution and cancel` |
| `4bcdf0105ea07bb66f13d0ad97da7d914f6ff110` | `test(agent): end-to-end against in-memory relay and ELSA` |
| `ff36b09d34aa805e3367964ba93d3fbaccbe13be` | `docs(env): variables del agente PC1` |
| `f74b6bd6a94fe52250e57ceea6c0e249fa3e45c1` | `fix(agent): address pre-PR review findings for the PC1 agent` |
| `ab606df1243307952679f5fed2494aa088d55c2c` | `docs(adr): precisar reinicio de Render, dedupe y limites del agente PC1` |
| `60b590406b9b1862f92f769073b02a3121323c0b` | `fix(agent): reject compressed relay bodies and non-UTF-8 config files` |
| `bb0fae22d806cc98e79a67f69a04553542c36d7f` | `fix(agent): harden relay diagnostics and config loading` |
| `7216c017840e55db10f71c18ee00b69d700b7950` | Merge del PR #48 en `main` |

**HECHO DEL REPOSITORIO:** `bb0fae2` es ancestro de `origin/main`, comprobado con
`git merge-base --is-ancestor`, y `git diff bb0fae2 7216c01` sobre el agente y ADR 0032 es
vacío.

## 17. Pull requests

| PR | Estado | Detalle |
|---|---|---|
| #48 | **Mergeado** el 2026-10-10 18:48:58 UTC | `feat(agent): implement outbound PC1 agent Pilot 0.1`; 11 commits, 15 archivos, +4523 / −0; base `main`, head `claude/d2-3-pc1-agent`; merge `7216c017840e55db10f71c18ee00b69d700b7950` |

CI (**HECHO MEDIDO** con la API pública de GitHub, en solo lectura):

| Ejecución | Evento | HEAD | Lint, types and tests | Secret scan (gitleaks) |
|---|---|---|---|---|
| 38073846523 | push (rama) | `bb0fae2` | SUCCESS, job 114276597430 | SUCCESS, job 114276597624 |
| 38076183667 | pull_request (#48) | `bb0fae2` | SUCCESS, job 114283486284 | SUCCESS, job 114283486446 |
| 38077303312 | push (`main`, merge #48) | `7216c01` | SUCCESS, job 114286856757 | SUCCESS, job 114286856595 |

Los push anteriores de la rama también terminaron en `success`:

| Ejecución | HEAD |
|---|---|
| 38064926991 | `8212fca` |
| 38065179804 | `98dac47` |
| 38065332938 | `9858fd1` |
| 38065442378 | `e717f26` |
| 38066087393 | `594d915` |
| 38066300828 | `4bcdf01` |
| 38066362568 | `ff36b09` |
| 38072263572 | `ab606df` |
| 38073043050 | `60b5904` |

## 18. Migraciones

Ninguna. D2.3 no escribió ni aplicó migraciones y no tocó ningún proyecto Supabase
(regla 15). Base de datos nueva: NO. Redis: NO. Persistencia de solicitudes: NO. Supabase
nuevo: NO.

## 19. Estado operacional final

**HECHO DEL REPOSITORIO: qué existe en `main`.**

**Proceso y conexiones**
- Agente `uv run python -m elsa.agent`, proceso aparte, **solo conexiones salientes**: HTTPS
  al relay y HTTP a ELSA en loopback. No escucha en ningún socket.
- Sin puerto público, reenvío de puertos, regla de firewall entrante ni proxy genérico.

**Credenciales**
- Token del nodo: **solo** del entorno del proceso; viaja únicamente en `X-Elsa-Node-Token`
  hacia Render.
- Token del usuario: **solo** como `Authorization: Bearer` hacia ELSA local.
- Clientes separados, `follow_redirects=False` y `trust_env=False`.

**ELSA local y rutas**
- ELSA local solo en IP literal de loopback.
- Única operación: `assistant.ask`, con ruta fija y segmentos codificados y validados, sin
  regex de charset.

**Sesiones**
- `stale_session` → retirar la sesión → esperar con backoff + jitter → UUID nuevo →
  REGISTER nuevo.
- Dos `stale` concurrentes producen una sola transición A→B. Sin replay.

**Concurrencia**
- Por defecto, 1 ejecución y 4 en espera.
- Poll continuo mientras ELSA ejecuta.
- Rechazos inmediatos por una cola de 16 con un trabajador.
- Tareas auxiliares acotadas.

**Entrega del resultado**
- `assistant.ask` se ejecuta **exactamente una vez**.
- Resultado serializado una vez, como mucho 4 transmisiones (1 + 3 reintentos a 0,5 / 1 /
  2 s), ninguna después de `expires_at`.
- ACK perdido → `409 request_not_pending` → fin, sin reejecutar.

**CANCEL**
- *Best effort* y sin ACK.

**Relay**
- Solo HTTPS, `Accept-Encoding: identity`.
- Respuesta comprimida rechazada sin leerla (`compressed_body`); lectura acotada.

**Configuración**
- Fail-closed; token presente en `.env`/`--env-file` → no arranca.
- Archivo no UTF-8 o con NUL → rechazado.

**Logs**
- Solo evento, identificadores, código, estado HTTP, intento y duración.

**Qué NO está conectado (HECHO DEL REPOSITORIO):**

| Elemento | Estado |
|---|---|
| Agente PC1 implementado | **SÍ** |
| PC1 real conectado a Render | **NO** |
| Red externa utilizada | **NO** |
| Despliegue real del relay en Render | **NO** |
| Secreto/hash real del nodo | **No generado** |
| Integración con el navegador / usuario (D2.4) | **No existe** |
| Login real y Modo ELSA | **Pendientes** |
| Dependencias nuevas | **0** |

**Limitaciones aceptadas del Pilot 0.1** (ADR 0031 §6 y ADR 0032 §3), todas abiertas:

| Limitación | Consecuencia |
|---|---|
| **Poll perdido sin ACK** | Si se pierde la respuesta HTTP de un poll que traía un `Request`, este puede expirar sin ejecutarse. Corregirlo exige una versión posterior del protocolo |
| **CANCEL** | No garantiza detener el trabajo ya iniciado dentro de ELSA, Materiales o un LLM |
| **Reinicio completo de Render** | Pierde memoria e historial de ids. Poll y result con la sesión vieja reciben `stale_session`, pero un `REGISTER(A)` reintentado puede ser aceptado por el relay nuevo (inocuo: A no tiene trabajo en ningún lado) |
| **Deduplicación del agente** | Es una defensa secundaria (LRU de 1024 por sesión); la garantía primaria at-most-once reside en el relay |
| **`reply_dropped`** | Bajo un fallo prolongado de `/result`, la solicitud vence por TTL en vez de recibir `LOCAL_UNAVAILABLE` rápido |
| **`trust_env=False`** | Posible incompatibilidad futura con un proxy corporativo obligatorio |
| **Puerto loopback** | Otro proceso local podría ocuparlo antes que ELSA y recibir los Bearer; ELSA debe arrancar antes y PC1 no debe ser multiusuario |
| **`ElsaLocalClient` sin `Accept-Encoding: identity`** | Su tope se mide tras descomprimir; riesgo aceptado y documentado |
| **Dos agentes con el mismo `node_id`** | El backoff reduce el *thrashing* a un reemplazo cada ~15–30 s, pero no lo detiene; no hay elección distribuida de líder |
| **Desfase de reloj PC1 ↔ Render** | `expires_at` es del reloj de Render y no se compensa |

## 20. Pendientes

Ninguno de estos se cierra por asociación con D2.3.

| # | Pendiente | Responsable / bloque |
|---|---|---|
| 1 | Integración extremo a extremo usuario ↔ relay (ruta pública, qué ve el usuario, saneado de `RelayFailure.detail`, liberación del `SecretStr` del usuario) | D2.4 |
| 2 | Conexión real Render ↔ PC1 | Despliegue controlado |
| 3 | Despliegue real del relay en Render (un worker; no fijar `WEB_CONCURRENCY`) | Responsable / despliegue |
| 4 | Generación y custodia del token real del nodo y de su hash en Render; en PC1 solo como variable de entorno del proceso | Responsable del proyecto |
| 5 | **Mediciones reales** de long polling, timeouts (25 / 45 / 120 s), latencia de entrega de `Request`/`Cancel` y comportamiento del proxy de Render; reevaluación del transporte si no es viable (ADR 0031 §5) | Despliegue controlado |
| 6 | Login real (operación normal) y Modo ELSA | Bloques posteriores |
| 7 | Prueba en entorno PAPELSA | Bloques posteriores |
| 8 | `Accept-Encoding: identity` en `ElsaLocalClient` | Fase posterior (riesgo aceptado) |
| 9 | Mover los límites `MAX_*_WIRE_BYTES` a un módulo neutro, cuando se autorice tocar D2.2 | Deuda anotada (ADR 0032 §2.1) |
| 10 | Arranque operativo del agente en PC1 (servicio de Windows o lanzador, orden ELSA → agente, sincronización de hora) | Despliegue controlado |
| 11 | Riesgos de Pilot 0.1 de §19 | Reevaluar antes de producción |
| 12 | Eliminar las ramas `claude/d2-3-pc1-agent` y `docs/closure-d2-3-pc1-agent` tras el merge de este documento y el CI final de `main` | Responsable |

## 21. Siguiente bloque

**D2.4: integración usuario ↔ relay**, solo después de que este documento esté integrado en
`main` con CI verde. D2.3 deja las dos mitades del transporte implementadas y probadas entre
sí sin red; **no** deja nada conectado ni desplegado.

---

## Criterios de cierre

| Criterio | Estado |
|---|---|
| PR #48 mergeado; merge SHA real verificado con Git y la API | Cumplido |
| `bb0fae2` contenido en `main`; 15 archivos integrados; ADR 0032 en `main` | Cumplido |
| CI de `main` del merge (run 38077303312) en verde | Cumplido |
| Agente outbound-only; ningún puerto de escucha; Render real no utilizado | Cumplido |
| ELSA local solo IP literal de loopback; `assistant.ask` única operación; sin proxy genérico | Cumplido |
| Token del nodo solo del entorno, separado del token del usuario; secretos ausentes de los logs | Cumplido |
| `stale_session` → sesión nueva sin replay; una sola transición ante `stale` concurrentes | Cumplido |
| ACK perdido sin reejecución; máximo 4 transmisiones; expiración respetada | Cumplido |
| Poll durante la ejecución; concurrencia, colas y tareas acotadas; CANCEL best effort | Cumplido |
| Shutdown sin tareas huérfanas ni `Request` retenidos | Cumplido |
| Suite completa sin regresiones nuevas (2 fallos baseline Windows); ruff verde; 0 errores mypy nuevos; gitleaks verde | Cumplido |
| `architecture-reviewer` y `security-reviewer` sin hallazgos bloqueantes | Cumplido |
| Dependencias nuevas = 0; base de datos nueva = NO; PC1 real no conectado | Cumplido |
| `docs/architecture.md` actualizado (implementado frente a operativo en red real) | Cumplido en este cambio documental |

## Regla de continuidad

Este documento **completa el cierre formal de D2.3 al quedar integrado en `main` con el CI
obligatorio en verde**. Su propio PR y su merge documental los registran Git y GitHub. Este
documento **no se auto-referencia** con un SHA propio: hacerlo obligaría a otro cambio solo
para anotarlo. Mientras no esté integrado, D2.3 se considera abierto.

## Veredicto

**D2.3 — AGENTE PC1 CERRADO FORMALMENTE: SÍ**, como estado efectivo al quedar este documento
integrado en `main` con CI verde.

- PR funcional #48 **mergeado** (`7216c017840e55db10f71c18ee00b69d700b7950`); CI de `main`
  (run 38077303312) con Lint/types/tests y Gitleaks en **SUCCESS**.
- Evidencia funcional preservada sobre `bb0fae2`:
  - 211 tests dirigidos y 230 cercanos;
  - suite completa: 1919 passed, 230 skipped, 2 failed (baseline Windows), 3 warnings;
  - regresiones nuevas: 0.

Estado que se mantiene:

```text
AGENTE PC1 IMPLEMENTADO:      SÍ
PC1 REAL CONECTADO A RENDER:  NO
RED EXTERNA OPERATIVA:        NO
DEPLOY REAL RENDER:           NO
DEPENDENCIAS NUEVAS:          0
```

**D2 sigue abierto**; no hay acceso remoto funcionando. Los pendientes de §20 siguen abiertos
y no se cierran por asociación. **Siguiente bloque: D2.4** (no iniciado).
