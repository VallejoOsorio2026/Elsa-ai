# Cierre formal — D2.2: Relay/Gateway Render

- **Fecha:** 2026-10-10 (UTC; el PR funcional #45 se mergeó a las 14:26 UTC y el PR
  documental #46 a las 14:45 UTC)
- **Estado:** **CERRADO** — PR #45 y PR documental #46 mergeados en `main`, y CI de `main`
  posterior al merge de #46 en verde (§17 y veredicto).
- **Qué cierra:** el subbloque **D2.2** del bloque D2 (acceso remoto seguro a ELSA): la mitad
  pública (Render) de la comunicación remota Render ↔ PC1: el relay/gateway en memoria, con
  transporte HTTPS long polling para Pilot 0.1 (ADR 0031), probado íntegramente con un **nodo
  PC1 simulado**.
- **Qué NO cierra:** **no cierra D2.** No hay agente de PC1 (D2.3), no hay conexión real
  Render ↔ PC1, no hay despliegue del relay en Render, no hay integración con el navegador ni
  con el usuario (D2.4), no hay login real ni Modo ELSA. **No hay acceso remoto funcionando.**
  Ver §20.
- **Prerrequisito:** D2.1 (protocolo V1, ADR 0029 y ADR 0030), cerrado formalmente en
  [`d2-1-protocolo-render-pc1-v1-cierre.md`](d2-1-protocolo-render-pc1-v1-cierre.md).
- **Identificador del bloque:** `D2` / `D2.2` es la nomenclatura de trabajo usada en el
  proyecto. El nombre de este archivo lleva `d2-2` para que **no pueda leerse como el cierre
  de D2**.
- **Marcas de afirmación** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**,
  **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Sanitización:** este documento no contiene secretos, tokens, hashes reales, correos,
  claves, cadenas de conexión, IP públicas, identificadores de usuario ni datos de planta
  (reglas 11 y 12). Los valores de prueba son sintéticos (`synthetic-*`) y no se reproducen.

---

## 1. Objetivo

Construir la **mitad pública** del acceso remoto híbrido, en la aplicación FastAPI que puede
ejecutarse en Render, de forma que el futuro agente de PC1 (D2.3) y la integración con el
usuario (D2.4) tengan un relay seguro, acotado y probado sobre el cual apoyarse:

```text
PC PAPELSA
    │  navegador / HTTPS
    ▼
RENDER                           ← D2.2 (este bloque): relay/gateway
    │  transporte iniciado desde PC1 (HTTPS long polling, Pilot 0.1)
    ▼
PC1
    ├── agente              (D2.3, futuro)
    ├── ELSA local
    ├── Phi / llama.cpp
    ├── conocimiento local
    └── Materiales (detrás de ELSA)
```

Render es el extremo público e **intermediario**; PC1 es el nodo de ejecución. Las decisiones
de ADR 0029 y ADR 0030 se **consumieron**, no se reabrieron.

## 2. Alcance

**Entró (HECHO DEL REPOSITORIO):**

- Autenticación independiente del nodo PC1 (cabecera, hash SHA-256, rotación con hash anterior).
- `REGISTER`, `poll` (con `HEARTBEAT` como señal de vida) y `result` (`RESPONSE` / `ERROR`).
- Estado ONLINE/OFFLINE interno, cola temporal en memoria con capacidad máxima.
- Despacho at-most-once, correlación por `request_id`, expiración, timeouts, `CANCEL` best
  effort y limpieza de referencias.
- Retiro de sesiones vencidas por TTL; `node_session_id` de un solo uso.
- Límites de payload y lectura HTTP acotada por streaming.
- Logs sanitizados.
- API interna Python `RelayService.submit(params, user_access_token)`, sin ruta pública de
  usuario.
- Configuración fail-closed (`ELSA_RELAY_*`), router montado solo con el relay habilitado.
- ADR 0031.
- Pruebas con nodo PC1 simulado.

**Quedó fuera (explícito):** agente real de PC1 (D2.3); llamadas reales desde PC1; ELSA local
desde Render; frontend (`web/`); login nuevo; Modo ELSA; deploy real a Render; secretos reales
en Render; consulta SAP, Materiales o LLM reales; base de datos, Redis, SQLite o disco;
WebSocket y SSE; endpoint público de estado; cualquier cambio a `protocol.py`, `render.yaml`,
Materiales, Supabase o LLM.

## 3. Estado inicial

- **HECHO DEL REPOSITORIO:** `main = origin/main = 01a53c0d61adaf961a9c0fc6e6b48caa65e02d68`
  (merge del PR documental #44 de D2.1), árbol limpio.
- Existían `src/elsa/relay/protocol.py` (contrato V1), ADR 0029, ADR 0030 y el cierre D2.1.
- El último ADR era el 0030; el siguiente disponible, **0031**.
- No existía ningún relay, ni configuración `ELSA_RELAY_*`, ni rutas de nodo.

## 4. Trabajo realizado

En orden:

1. Verificación de `main` y creación de la rama `claude/d2-2-render-relay-gateway` desde el
   `origin/main` vigente.
2. Exploración acotada (`main.py`, `config.py`, `container.py`, `errors.py`, `assistant.py`,
   `protocol.py`, ADR 0029/0030, plantilla de entorno) y **microplan** de 12 archivos, aprobado
   con 3 ajustes obligatorios: (1) `queued` independiente de `node_session_id`; (2) caída por
   TTL resuelta con *deadlines* asíncronos, sin scheduler; (3) body HTTP acotado por lectura en
   streaming.
3. Implementación en 4 commits: ADR 0031; store/service/auth/config/container; router y wiring;
   variables de entorno.
4. **Revisión integral pre-PR** con `architecture-reviewer` y `security-reviewer`, suite
   completa y verificaciones de CI. Detectó el defecto H1 (ver §13).
5. **Corrección** (commit `cf7ad6d`) de H1 y H2; ADR 0031 ampliado.
6. Validación final sobre el HEAD exacto, PR #45, CI y merge.

## 5. Decisiones

| # | Decisión | Motivo | Marca |
|---|---|---|---|
| 1 | Transporte **HTTPS long polling** para Pilot 0.1; **no** es arquitectura definitiva y exige un ADR nuevo si las mediciones reales de Render lo hacen inviable (ADR 0031 §5) | PC1 inicia toda conexión, solo HTTPS saliente, sin dependencia nueva, sin inbound, sin IP pública | DECISIÓN TOMADA (ADR 0031) |
| 2 | Estado **solo en memoria**; reinicio de Render pierde sesión y solicitudes en vuelo | Sin DB, Redis, SQLite ni disco en Pilot 0.1 | DECISIÓN TOMADA |
| 3 | **Una única instancia lógica / un worker**; `WEB_CONCURRENCY > 1` no soportado | Un store en memoria no se comparte entre workers | DECISIÓN TOMADA |
| 4 | Auth del nodo independiente del JWT del usuario: cabecera `X-Elsa-Node-Token`, Render guarda solo SHA-256 (actual y anterior), `hmac.compare_digest` | Credencial propia, rotación sin corte, el secreto crudo nunca en Render | DECISIÓN TOMADA |
| 5 | Relay **deshabilitado por defecto** y fail-closed; con él apagado las rutas no se montan (404) | No exponer superficie sin configuración completa | DECISIÓN TOMADA |
| 6 | `queued` no almacena `node_session_id`; el `Request` se materializa al despachar con la sesión activa | Evita entregar a B un request construido para A | DECISIÓN TOMADA (ajuste 1) |
| 7 | Caída por TTL resuelta con *deadlines* async propios de cada `submit` | Sin scheduler permanente | DECISIÓN TOMADA (ajuste 2) |
| 8 | Body acotado por `Content-Length` y lectura por chunks, nunca `request.body()` | No cargar un body arbitrario para medirlo | DECISIÓN TOMADA (ajuste 3) |
| 9 | **TTL vencido retira la sesión**; `poll`/`result`/`register` con ese id → 409 `stale_session`; un `node_session_id` es de **un solo uso** | Reconexión explícita, at-most-once, sin resurrección silenciosa | DECISIÓN TOMADA (corrección `cf7ad6d`) |
| 10 | Interfaz interna `submit(AskParams, user_access_token)`; D2.4 no conoce `node_session_id` | `Request` exige la sesión, que el llamador no tiene | DECISIÓN TOMADA (aprobada) |
| 11 | Fallo interno de Render como `RelayFailure(ErrorCode, detail)`, no `ErrorMessage` | `ErrorMessage` exige `node_session_id` | DECISIÓN TOMADA |
| 12 | Sin refactor `RelayPolicy.from_settings` → `container.py` (H3) | Opcional; no se construye por anticipación | DECISIÓN TOMADA (no hacerlo) |

Valores de partida del piloto (**sin SLA; pendientes de medición real en Render**):

| Parámetro | Valor | Variable |
|---|---|---|
| Long poll | 25 s | `ELSA_RELAY_LONG_POLL_SECONDS` |
| TTL del nodo | 45 s (debe ser mayor que el long poll) | `ELSA_RELAY_NODE_TTL_SECONDS` |
| TTL de solicitud | 120 s | `ELSA_RELAY_REQUEST_TTL_SECONDS` |
| `max_pending` (cola + en vuelo) | **16** | `ELSA_RELAY_MAX_PENDING` |

Límites de tamaño (constantes de código; cierran los pendientes de D2.1):

| Límite | Valor |
|---|---|
| `user_access_token` | ≤ 4096 caracteres |
| `REQUEST` en el cable (bytes UTF-8 del JSON compacto) | ≤ 16 KiB |
| `RESPONSE` en el cable | ≤ 256 KiB |
| `ERROR` en el cable | ≤ 2 KiB |
| Body HTTP de `register` / `poll` | ≤ 1 KiB |
| Body HTTP de `result` | ≤ 257 KiB (256 KiB + 1 KiB de envoltura) |

## 6. Pruebas

**HECHO MEDIDO.** Se ejecutaron: tests dirigidos (`test_relay_service.py`,
`test_api_relay.py`, `test_relay_protocol.py`, más config, render blueprint, cors, health,
logging, errors, gitignore y autenticación), suite completa, `ruff check .`,
`ruff format --check .`, `mypy`, `git diff --check` y revisión manual de secretos sobre todo
el diff.

Cobertura de comportamiento de los tests D2.2 (nodo simulado, reloj inyectable, sin red):
E2E register → submit → poll → response; nodo offline; error del nodo; TTL; sesión antigua;
`queued` que sobrevive a REGISTER; duplicados y `request_id` desconocido; at-most-once y
polls concurrentes; token descartado al despachar y ausente del frame de `submit`; expiración
con y sin otra operación; capacidad; límites de tamaño; cancelación; logs sin secretos;
verificación actual/anterior/incorrecto; configuración fail-closed; 401 indistinguible;
413 por límite exacto, `Content-Length` mentiroso y body chunked; rutas inexistentes
(`execute`, `proxy`, `fetch`, `status`); relay deshabilitado = 404 con ELSA operativa.

## 7. Comandos relevantes

```bash
git fetch --all --prune
git diff origin/main...HEAD --stat

uv run pytest -q tests/test_relay_protocol.py tests/test_relay_service.py tests/test_api_relay.py
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check origin/main...HEAD
```

Configuración mínima para habilitar el relay (valores de ejemplo, nunca reales):

```text
ELSA_RELAY_ENABLED=true
ELSA_RELAY_NODE_ID=<id configurado>
ELSA_RELAY_NODE_TOKEN_SHA256=<sha256 hex en minúscula de 64 caracteres>
```

## 8. Resultados

**HECHO MEDIDO** — suite completa sobre el HEAD exacto `cf7ad6d`:

```text
2 failed, 1708 passed, 230 skipped, 3 warnings in 173.80s (0:02:53)
FAILED tests/test_bench_harness.py::test_a_run_records_what_produced_it
FAILED tests/test_bench_harness.py::test_peak_memory_is_measured_where_the_posix_api_exists
```

- Los 2 fallos son el **baseline histórico de Windows** (`resource` / `peak_rss_mb`) y no
  tienen relación con D2.2. Baseline previo a D2.2: 1641 passed, 230 skipped, 2 failed,
  3 warnings. **Regresiones atribuibles a D2.2: 0.**
- `ruff check .`: `All checks passed!`; `ruff format --check .`: `328 files already formatted`.
- `mypy`: 3 errores, todos históricos en `src/elsa/bench/runner.py` (`getrusage`,
  `RUSAGE_SELF`, `unused-ignore`). **Errores nuevos: 0.**
- `git diff --check`: limpio (solo avisos LF→CRLF de Windows, no fallos).
- Revisión de secretos: búsqueda sobre todo el diff de JWT, hashes de 64 hex, `service_role`,
  correos, IP, cadenas de conexión y `sk-`: sin hallazgos reales.

## 9. Métricas

| Métrica | Valor | Método |
|---|---|---|
| Tests D2.2 nuevos | 67 (46 en `test_relay_service.py`, 21 en `test_api_relay.py`) | `pytest --collect-only` sobre `main` |
| Diferencia en la suite | 1641 → 1708 passed (+67) | comparación con el baseline medido |
| Archivos del PR | 12 (7 creados, 5 modificados) | `git diff --name-status 01a53c0 aee7db6` |
| Líneas del PR | +2568 / −2 | API de GitHub, PR #45 |
| Commits del PR | 5 | API de GitHub, PR #45 |
| Dependencias nuevas | 0 | `pyproject.toml` y `uv.lock` sin cambios |

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO / DEL PROCESO.** Claude Code (modelo Sonnet 5.5) exploró, redactó el
microplan, implementó ADR 0031, store, service, auth, router, configuración y tests, ejecutó
las verificaciones de §8, lanzó las revisiones de §13, corrigió H1 y H2 y redactó este
documento. El responsable aprobó el microplan (con 3 ajustes), el plan de corrección (con
ajustes) y autorizó el PR.

- **Identificador de sesión:** el directorio local de sesión que aparece en las rutas de
  trabajo es `5f981b76-7520-4304-8c57-6b04d5554ea6`. No se contrastó contra otra fuente; se
  registra tal como aparece y **no** se garantiza más que eso.
- **Qué se revisó:** diffs, salidas reales de comandos y dos revisiones de subagentes en
  modo solo lectura: `architecture-reviewer` (BLOCKING: NO) y `security-reviewer`
  (BLOCKING: SÍ por H1, luego corregido). Sus informes los entregó cada subagente a la
  sesión; **no** se versionan.

## 11. Aportes de Codex

Nada que registrar: Codex no participó en D2.2.

## 12. Operaciones manuales y de PowerShell

- Consulta **solo lectura** a la API pública de GitHub (sin autenticación) para obtener el
  estado del PR #45 y de las ejecuciones de CI de `cf7ad6d` y del merge `aee7db6`.
- Scripts de apoyo en el directorio temporal de la sesión (no versionados): reproducción del
  defecto H1, comprobación de los límites exactos del body y generación del cuerpo del PR.
- Los PR #45 y #46 los **creó y mergeó el responsable del proyecto** desde su navegador: el
  entorno de la sesión no tiene `gh` y el navegador integrado no tenía sesión de GitHub.
- Consultas **solo lectura** a la API pública de GitHub para verificar el PR #46, el merge
  `60b3c8c` y las ejecuciones de CI de `main` y de la rama documental.
- No se tocó Render, Supabase, Materiales, PC1 ni la red.

## 13. Incidentes

| # | Incidente | Qué se hizo | Estado |
|---|---|---|---|
| 1 | Primera ejecución de `test_relay_service.py` se colgó: un test con reloj falso esperaba plazos en tiempo real | Los tests de deadlines asíncronos pasaron a reloj real con milisegundos; los de reloj falso solo invocan `enforce_deadlines()` | Resuelto en `484d5ec` |
| 2 | **H1 (ALTO, bloqueante)** — la revisión de seguridad y una reproducción mostraron que una sesión vencida por TTL **revivía** con el mismo `node_session_id` por `poll`, `result` y `register`; un test lo afirmaba. Causa: `touch` solo comparaba el id y se refrescaba `last_seen` antes de evaluar el vencimiento | Se retira la sesión vencida antes de refrescar; `node_session_id` de un solo uso; 409 `stale_session`; tests invertidos y ampliados | Resuelto en `cf7ad6d` |
| 3 | **H2 (MEDIO)** — el token del usuario seguía referenciado en el frame de `submit` (`secret`, `trial`, el parámetro) durante la espera | Validación en un helper; `del user_access_token` tras crear la entrada; test sobre el frame | Resuelto en `cf7ad6d` |
| 4 | El informe de implementación contó 8 creados / 4 modificados | Cuenta correcta: 7 creados / 5 modificados / 12 | Corregido solo en el informe, sin commit |
| 5 | Una captura del PR se leyó como SHA corto `ace7db6` | El SHA real es `aee7db6685297f167f04137150267fd56ecaca5e`, obtenido con Git | Resuelto |
| 6 | `gh` no está instalado; el navegador integrado no tenía sesión | Los PR se crearon manualmente (§12) | Aceptado |
| 7 | Se informó el PR documental como mergeado cuando seguía **abierto** (#46 `open`, `main` aún en `aee7db6`) | Se verificó contra Git y la API pública, no se tomó la confirmación como evidencia, y se esperó al merge real (`60b3c8c`) | Resuelto |
| 8 | El documento de cierre original dejaba como PENDIENTE su propio merge y el CI posterior, por lo que, ya mergeado, afirmaba un estado desactualizado | Esta versión final lo regulariza con la evidencia real (rama `docs/finalize-d2-2-closure`) | Resuelto con esta corrección |

## 14. Git

- Se creó una rama funcional desde `main`, 5 commits, un PR, merge con *merge commit*.
- No se hizo `amend`, `rebase` ni `force push`.
- Archivos prohibidos intactos: `src/elsa/relay/protocol.py`, `render.yaml`, `web/`,
  `pyproject.toml`, `uv.lock`, workflows, Materiales, Supabase y LLM.
- **Creados (7):** `docs/adr/0031-transporte-https-long-polling-relay-render-pc1-pilot-0-1.md`,
  `src/elsa/relay/{store,service,auth}.py`, `src/elsa/api/v1/relay.py`,
  `tests/test_relay_service.py`, `tests/test_api_relay.py`.
- **Modificados (5):** `src/elsa/config.py`, `src/elsa/container.py`, `src/elsa/main.py`,
  `.env.example`, `docs/environment-variables.md`.

## 15. Ramas

| Rama | Uso | Estado |
|---|---|---|
| `claude/d2-2-render-relay-gateway` | Trabajo funcional de D2.2 | Mergeada vía PR #45; **no eliminada** todavía |
| `docs/closure-d2-2-render-relay-gateway` | Documento de cierre original | Mergeada vía PR #46; **no eliminada** todavía |
| `docs/finalize-d2-2-closure` | Corrección final de la evidencia de este documento | Creada desde `main` (`60b3c8c`); pendiente de su propio merge y de la limpieza posterior |

## 16. Commits

| Commit | Mensaje |
|---|---|
| `f772328eab25b70913b13be369a43ae89b5507bc` | `docs(adr): transporte HTTPS long polling para relay Render-PC1 Pilot 0.1` |
| `484d5ec4882d69554ec02be18d48a57ab38659a6` | `feat(relay): in-memory relay store, service and node auth` |
| `697efd1a845a9c12f5692a7b9dbcbf4063c6e6d9` | `feat(api): relay node endpoints` |
| `aa3151675c89fac2442156d600c8eac5618ce5e6` | `docs(env): variables del relay Render-PC1` |
| `cf7ad6d6f65ccfe3d30c5746cad1973181cc9c0d` | `fix(relay): retire expired node sessions` |
| `aee7db6685297f167f04137150267fd56ecaca5e` | Merge del PR #45 en `main` |
| `0f3bd37a624b98c35bb9c4d3117b7206eec236d9` | `docs(project): cierre formal D2.2 relay gateway Render` |
| `60b3c8c7f52259d60b2a2843113c6bad396575b8` | Merge del PR #46 en `main` |

**HECHO DEL REPOSITORIO:** los 5 commits funcionales y `0f3bd37` son ancestros de
`origin/main` (comprobado con `git merge-base --is-ancestor`). El commit de la corrección final
de este documento lo registra el historial de la rama `docs/finalize-d2-2-closure`.

## 17. Pull requests

| PR | Estado | Detalle |
|---|---|---|
| #45 | **Mergeado** el 2026-10-10 14:26 UTC | `feat(relay): implement Render-PC1 relay gateway Pilot 0.1`; 5 commits, 12 archivos, +2568 / −2; base `main`; merge `aee7db6685297f167f04137150267fd56ecaca5e` |
| #46 | **Mergeado** el 2026-10-10 14:45 UTC | `docs(project): cierre formal D2.2 relay gateway Render`; 1 commit (`0f3bd37`), 1 archivo (+400 / −0); base `main`; merge `60b3c8c7f52259d60b2a2843113c6bad396575b8` |

CI (**HECHO MEDIDO** por la API pública de GitHub, en solo lectura):

| Ejecución | Evento | HEAD | Secret scan (gitleaks) | Lint, types and tests |
|---|---|---|---|---|
| 38057189251 | push (rama) | `cf7ad6d` | SUCCESS, job 114227962891 | SUCCESS, job 114227963244 |
| 38058590881 | pull_request (#45) | `cf7ad6d` | SUCCESS, job 114232027988 | SUCCESS, job 114232027740 |
| 38059603166 | push (`main`, merge #45) | `aee7db6` | SUCCESS, job 114234985152 | SUCCESS, job 114234985029 |
| 38060000492 | push (rama documental) | `0f3bd37` | SUCCESS, job 114236145010 | SUCCESS, job 114236144676 |
| 38060902546 | push (`main`, merge #46) | `60b3c8c` | SUCCESS, job 114238779460 | SUCCESS, job 114238779325 |

Las ejecuciones 38059603166 (merge #45) y 38060902546 (merge #46) en `main` terminaron con
`status = completed` y `conclusion = success`. La ejecución 38060902546 es el **CI final de
`main` posterior al merge documental**. Esta corrección de evidencia es solo Markdown; su
propio merge y su CI se verifican aparte y no se anticipan aquí.

## 18. Migraciones

Ninguna. D2.2 no escribió ni aplicó migraciones; no tocó ningún proyecto Supabase (regla 15).

## 19. Estado operacional final

**HECHO DEL REPOSITORIO:**

- El relay existe en `main` y está **deshabilitado por defecto**: con
  `ELSA_RELAY_ENABLED=false` no hay rutas de nodo (404) y el comportamiento histórico de ELSA
  no cambia. Con él habilitado y configuración incompleta o inválida, la aplicación **no
  arranca**.
- Rutas de nodo (solo con el relay habilitado), todas `POST` bajo `/api/v1/relay/node`:
  `/register`, `/poll`, `/result`. No hay `/execute`, `/proxy`, `/fetch` ni `/status`.
- Semántica vigente:
  - ONLINE = sesión válida y `last_seen` dentro del TTL; OFFLINE → `submit` falla de
    inmediato con `LOCAL_UNAVAILABLE`.
  - **At-most-once, sin replay automático:** lo despachado nunca vuelve a la cola.
  - **Sesión vencida por TTL queda retirada**; `poll`, `result` y `register` con ese id →
    409 `stale_session`; el `REGISTER` posterior **exige un `node_session_id` nuevo**.
  - **`dispatched` de una sesión vencida o reemplazada nunca se reproduce**: falla con
    `LOCAL_UNAVAILABLE` y no llega a la sesión siguiente.
  - **`queued` puede sobrevivir** a un nuevo `REGISTER` y esperar hasta su propio TTL (120 s
    por defecto); se materializa con la sesión nueva.
  - **`CANCEL` es best effort**, sin ACK: `queued` se retira; `dispatched` se entrega al nodo
    en el siguiente poll.
  - Body HTTP acotado por streaming; `max_pending = 16`.
- Logs sanitizados: solo identificadores, estado, código y duración. Nunca token del nodo,
  token del usuario, hash, pregunta, resultado ni `Error.detail`.
- **Limitaciones aceptadas del piloto:** estado solo en memoria; el **reinicio de Render
  pierde sesión y solicitudes en vuelo**; **una sola instancia / un worker lógico**;
  **`WEB_CONCURRENCY > 1` no está soportado**; el historial de `node_session_id` usados
  también se pierde con el reinicio.

**Qué NO está conectado (HECHO DEL REPOSITORIO):**

| Elemento | Estado |
|---|---|
| PC1 real | **NO conectado** |
| Agente PC1 (D2.3) | **No existe** |
| Red externa utilizada | **NO** |
| Despliegue real en Render | **NO** |
| Secreto/hash real del nodo | **No generado** |
| Integración con el navegador / usuario | **No existe** |
| Login real y Modo ELSA | **Pendientes** |
| Dependencias nuevas | **0** |

## 20. Pendientes

Ninguno de estos se cierra por asociación con D2.2.

| # | Pendiente | Responsable / bloque |
|---|---|---|
| 1 | Agente PC1 (D2.3): REGISTER con `node_session_id` nuevo en cada arranque o reconexión, poll **continuo mientras ejecuta** (de lo contrario el nodo cae por TTL), entrega de result/error, tratamiento de `CANCEL` | D2.3 |
| 2 | Conexión real Render ↔ PC1 | D2.3 / despliegue controlado |
| 3 | Generación y custodia del secreto real del nodo y de su hash en Render; ningún secreto real existe hoy | Responsable del proyecto |
| 4 | **Medición real** de long polling y de los timeouts (25 s / 45 s / 120 s) en Render; reevaluación del transporte si no es viable (ADR 0031 §5) | Despliegue controlado |
| 5 | Despliegue controlado del relay en Render (no existe); decidir el entorno expuesto (la auditoría D2 señaló que DEV admite identidades fake); mencionar el relay y la restricción de un worker en `render.yaml` / runbook; no fijar `WEB_CONCURRENCY` | Responsable / despliegue |
| 6 | Mitigaciones correspondientes en el agente (límites, saneamiento de `detail`, manejo de `CANCEL`) | D2.3 |
| 7 | Login real (operación normal) y Modo ELSA | Bloques posteriores |
| 8 | Prueba en entorno PAPELSA | Bloques posteriores |
| 9 | **Rate limiting de node auth: riesgo aceptado del piloto.** No hay límite de intentos fallidos; se confía en un secreto de alta entropía y en 401 uniforme | Aceptado; reevaluar antes de producción |
| 10 | Integración usuario ↔ relay: ruta pública, qué ve el usuario del estado, saneado de `RelayFailure.detail` antes de mostrarlo, liberar el `SecretStr` del usuario | D2.4 |
| 11 | Observaciones menores de la revisión: acoplamiento `service.py` → `config.Settings` (H3, no aplicado); `RESPONSE` con mucho texto no ASCII escapado podría superar el tope del body HTTP (413 con la solicitud en vuelo hasta su TTL); `queued` con el nodo caído espera hasta su TTL; `auth_failed` sin límite en logs; el historial de ids usados crece un UUID por sesión | Revisar en D2.3 / D2.4 |
| 12 | Eliminar las ramas de D2.2 (`claude/d2-2-render-relay-gateway`, `docs/closure-d2-2-render-relay-gateway` y `docs/finalize-d2-2-closure`) tras el merge de la corrección final y el CI final de `main` | Responsable |
| 13 | Instalar o disponer de `gh` en el entorno de trabajo si se quiere automatizar la creación de PR | Responsable (opcional) |

## 21. Siguiente bloque

**D2.3 — agente PC1**, solo después de que este documento esté mergeado en `main` y el CI de
`main` esté verde. Es el consumidor natural del relay: debe iniciar todas las conexiones desde
PC1, registrarse con un `node_session_id` nuevo, mantener el poll mientras ejecuta y entregar
resultados. D2.2 deja el relay listo y probado contra un nodo simulado; **no** deja nada
conectado.

---

## Criterios de cierre

| Criterio | Estado |
|---|---|
| Arquitectura D2.1 y protocolo V1 intactos (`protocol.py` sin cambios) | Cumplido |
| ADR 0031 mergeado y releído desde `main` | Cumplido |
| Relay deshabilitado por defecto y fail-closed | Cumplido |
| Auth del nodo independiente; hash en Render, secreto crudo no retenido | Cumplido |
| REGISTER / poll / result, ONLINE/OFFLINE, at-most-once, sin replay | Cumplido |
| Sesión vencida retirada; `node_session_id` nuevo obligatorio | Cumplido |
| Límites de payload, `max_pending`, body por streaming | Cumplido |
| Logs sin secretos ni payloads | Cumplido |
| Suite completa sin regresiones D2.2 (2 fallos baseline Windows) | Cumplido |
| Ruff verde; 0 errores nuevos de mypy; secret review limpio | Cumplido |
| CI del PR #45 y del merge en `main` en verde | Cumplido |
| Dependencias nuevas = 0; PC1 real no conectado; red externa no utilizada | Cumplido |
| PR documental #46 mergeado y CI de `main` posterior (run 38060902546) en verde | Cumplido |
| Este documento versionado en `main` y coherente con el estado final | Cumplido (con esta corrección) |

## Veredicto

**D2.2 — RELAY/GATEWAY RENDER CERRADO FORMALMENTE: SÍ.**

- PR funcional #45 **mergeado** (`aee7db6685297f167f04137150267fd56ecaca5e`), CI verde.
- PR documental #46 **mergeado** (`60b3c8c7f52259d60b2a2843113c6bad396575b8`); CI de `main`
  posterior (run 38060902546) con Lint/types/tests y Gitleaks en **SUCCESS**.
- Evidencia funcional preservada sobre `cf7ad6d`: 1708 passed, 230 skipped, 2 failed
  (baseline Windows), 3 warnings; regresiones D2.2 = 0.

Estado que se mantiene:

```text
PC1 REAL CONECTADO:     NO
RED EXTERNA OPERATIVA:  NO
DEPLOY REAL RENDER:     NO
DEPENDENCIAS NUEVAS:    0
```

**D2 sigue abierto**; no hay acceso remoto funcionando. Los pendientes de §20 continúan
abiertos y no se cierran por asociación: D2.3 (agente PC1), conexión real Render ↔ PC1,
secreto y autenticación reales del nodo, despliegue real en Render, medición real de long
polling y timeouts, rate limiting de node auth, integración usuario ↔ relay, login real,
Modo ELSA y prueba PAPELSA. **Siguiente bloque: D2.3 — agente PC1** (no iniciado).
