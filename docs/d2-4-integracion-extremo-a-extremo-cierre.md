# Cierre formal — D2.4: Integración extremo a extremo

- **Fecha:** 2026-10-18 (UTC). El PR funcional #50 se abrió a las 14:26:31 UTC y se mergeó a
  las 14:29:50 UTC.
- **Estado:** cierre formal de D2.4, **efectivo cuando este documento quede integrado en
  `main` con el CI obligatorio en verde** (ver «Regla de continuidad»).
- **Qué cierra:** el subbloque **D2.4** del bloque D2 (acceso remoto seguro a ELSA). D2.4 une
  por primera vez las piezas de D2.1–D2.3: la ruta pública `POST
  /api/v1/assistant/{domain}/{asset}/ask` puede ejecutarse en modo **RELAY**, que encamina la
  pregunta por el `RelayService` de D2.2 y el agente de D2.3 hasta la ELSA local de PC1, y
  devuelve una `AskResponse` validada. El modo **LOCAL**, histórico, sigue siendo el default.
  Está probado de extremo a extremo **en memoria, sin red real**.
- **Qué NO cierra:** **no cierra D2.** No hay conexión real Render ↔ PC1, despliegue, token
  real del nodo, medición de latencia de Internet ni del timeout del proxy de Render, prueba
  desde PAPELSA, login definitivo ni Modo ELSA. **No hay acceso remoto funcionando.** Ver §20.
- **Prerrequisitos:** D2.1 ([`d2-1-protocolo-render-pc1-v1-cierre.md`](d2-1-protocolo-render-pc1-v1-cierre.md)),
  D2.2 ([`d2-2-relay-gateway-render-cierre.md`](d2-2-relay-gateway-render-cierre.md)) y D2.3
  ([`d2-3-agente-pc1-cierre.md`](d2-3-agente-pc1-cierre.md)), los tres cerrados formalmente.
- **Identificador del bloque:** `D2` / `D2.4` es la nomenclatura de trabajo del proyecto. El
  nombre de este archivo lleva `d2-4` para que **no pueda leerse como el cierre de D2**.
- **Marcas de afirmación** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**,
  **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Sanitización:** este documento no contiene secretos, tokens, hashes reales, correos,
  claves, cadenas de conexión, IP públicas, identificadores de usuario, cuerpos de
  solicitudes o respuestas reales ni datos de planta (reglas 11 y 12). Los valores de prueba
  del repositorio son sintéticos y aquí no se reproducen.

---

## 1. Objetivo

Que una petición real al endpoint público `assistant.ask` recorra la arquitectura híbrida
completa y regrese una `AskResponse` válida, **sin que Render ejecute la consulta**:

```text
Usuario / navegador
    │  POST /api/v1/assistant/{domain}/{asset}/ask   (sin cambios en web/)
    ▼
ELSA pública (Render), modo RELAY  ── autentica JWT + control de abuso
    │  llamada Python directa
    ▼
RelayService (D2.2, en memoria)
    ↑↓  HTTPS long polling, iniciado por PC1
NodeAgent (D2.3, outbound-only)
    │  HTTP loopback + X-Elsa-Relay-Hop: 1
    ▼
ELSA local (PC1), modo LOCAL  ── autoriza y ejecuta
    ▼
conocimiento / Materiales / futura IA local
```

La misma API debía operar en dos modos explícitos, LOCAL y RELAY, sin romper el
comportamiento histórico y sin fallback de RELAY a LOCAL. Las decisiones de ADR 0029–0032
se **consumieron**, no se reabrieron.

## 2. Alcance

**Entró (HECHO DEL REPOSITORIO):**

- [ADR 0033](adr/0033-modo-de-ejecucion-de-assistant-ask-local-o-relay.md): modo de ejecución
  de `assistant.ask`.
- `ELSA_ASSISTANT_EXECUTION_MODE` (`local` | `relay`) en `src/elsa/config.py`, fail-closed.
- `admitted_identity` en `src/elsa/api/deps.py` (JWT + control de abuso), extraída de
  `verified_identity` sin cambiarle la semántica.
- Ruta RELAY `src/elsa/api/v1/assistant_relay.py`: rechazo de reentrada, prevalidación
  estructural, `RelayService.submit` directo, watcher de desconexión, validación de
  `AskResponse`, tabla de errores cerrada y log de correlación.
- Selección de un único router por modo en `src/elsa/main.py`.
- Cabecera `X-Elsa-Relay-Hop: 1` en `src/elsa/agent/local_client.py`.
- Tests: ruta RELAY con el relay real y un nodo guionizado; E2E con app pública, relay real,
  agente real y app local; configuración; cabecera del agente.
- `.env.example`, `docs/environment-variables.md` y `docs/architecture.md`.

**Quedó fuera (explícito):**

- Render real, PC1 real conectado, token real del nodo, deploy, `render.yaml`.
- Puertos, firewall, port forwarding, VPN, túneles, proxy genérico.
- Cambios a `src/elsa/api/v1/assistant.py`, `src/elsa/container.py`, `protocol.py`,
  `src/elsa/relay/*` y al diseño del agente D2.3 (salvo la cabecera de salto).
- Frontend (`web/`), Materiales, Supabase, LLM (Phi/llama.cpp), login real, Modo ELSA.
- Base de datos, migraciones, Redis, persistencia del relay; dependencias nuevas.
- Qué debe servir Render en RELAY con el resto de la API (ver §20).
- D2.5.

## 3. Estado inicial

- **Rama base:** `main` en `aa890b014fd15402e9d9ad488843576bf0ba530d` (merge del PR #49, cierre
  documental de D2.3), con CI de `main` en verde (run 39130283731).
- **Existía:** protocolo V1 (D2.1), relay en memoria con `RelayService.submit(AskParams,
  user_access_token)` (D2.2) y agente outbound-only (D2.3). El endpoint `/ask` ejecutaba
  siempre la lógica local: autenticación, perfil en Materiales, cuenta y permisos de ELSA,
  `resolve_asset`, búsqueda literal en el BOM/AMEF publicados y, con código exacto,
  disponibilidad en Materiales.
- **No existía:** ningún camino desde el endpoint público hasta el relay; ningún modo de
  ejecución; ninguna prueba con las cuatro piezas juntas.

## 4. Trabajo realizado

En orden:

1. **Gate D2.3.** La primera sesión encontró el documento de cierre de D2.3 fuera de `main` y
   se detuvo (D2.4 BLOQUEADO). Tras el merge del PR #49 se volvió a comprobar: documento en
   `main`, veredicto SÍ, CI verde. Se creó la rama `claude/d2-4-end-to-end-integration`.
2. **Auditoría dirigida y microplan** de 11 archivos (13 con D4), con la inconsistencia D1
   reportada antes de escribir código (§5). El responsable aprobó D1–D5 con 4 precisiones
   obligatorias y un máximo de 13 archivos.
3. **Implementación por unidades** (§16): ADR 0033 → configuración → `admitted_identity` →
   ruta RELAY → cabecera del agente → E2E → documentación de variables → corrección de un
   test intermitente.
4. **Revisión integral pre-PR:** `architecture-reviewer` y `security-reviewer` en solo
   lectura, revisión propia y repetición de los tests de cancelación. Ningún hallazgo
   bloqueante; 2 MINOR y varios NIT corregidos en `f2e03fc` y `ad28056` (§13).
5. **PR #50**, CI y merge (§17).
6. Este documento.

### 4.1 Modos LOCAL y RELAY (HECHO DEL REPOSITORIO)

| `ELSA_ASSISTANT_EXECUTION_MODE` | `ELSA_RELAY_ENABLED` | Resultado |
|---|---|---|
| `local` (default) | `false` | Comportamiento histórico |
| `local` | `true` | Válido: rutas de nodo montadas, la pregunta se responde aquí. Sin cambio automático de modo |
| `relay` | `true` | Render autentica; PC1 autoriza y responde |
| `relay` | `false` | **No arranca** (`ConfigurationError`) |

Solo valores exactos y en minúscula: `RELAY`, `Relay`, ` relay`, `relay `, vacío o
cualquier otro valor impiden arrancar. `create_app` monta **un único** router para la ruta:
el histórico (`assistant.py`, sin cambios) o el de RELAY. La ruta RELAY no declara en su firma
conocimiento, Materiales ni permisos: ejecutar localmente en Render es imposible por
construcción, no por un `if`. **No hay fallback.**

### 4.2 Frontera Render / PC1

| Render (RELAY) | PC1 / ELSA local (LOCAL) |
|---|---|
| Rechazo de `X-Elsa-Relay-Hop` | Validación del mismo token del usuario |
| Autenticación JWT pública (`admitted_identity`) | Perfil activo en Materiales |
| Control de abuso | Cuenta ELSA y permisos |
| Validación estructural de `domain`/`asset` y del cuerpo (`AskRequest`) | Alcance y activo |
| Transporte por `RelayService` | Conocimiento publicado |
| Validación final de `AskResponse` | Materiales cuando corresponda |
| Mapeo a errores públicos | Ejecución funcional y límites de adjuntos |

**Doble validación del JWT, intencional:** Render no confía en nada que no verificó y PC1 no
confía en Render. Sin `service_role`, sin credencial del nodo como usuario, sin identidad
inventada. **Todo 403 de permisos de una pregunta procede de PC1.**

### 4.3 Relay submission

`RelayService.submit(params, SecretStr(token), request_id=uuid4())` como **llamada Python
directa** al relay del mismo proceso (`container.relay`). Sin HTTP hacia sí mismo, sin
protocolo nuevo: se usan `AskParams` y `AttachmentMeta` de V1 tal cual.

### 4.4 Validación de la respuesta del nodo

`AskResponse.model_validate(result, strict=True)` y, además, `domain` y `asset` del resultado
deben coincidir con los pedidos (normalizados). Si no: `503 local_node_invalid_response`, sin
eco. Se devuelve el modelo, nunca el dict. **Campos extra: se descartan** según el contrato
actual de `AskResponse`, que no se modificó.

### 4.5 Errores públicos

`RelayFailure.detail` **nunca** llega al cliente ni a los logs: solo elige una fila de una
lista blanca; los mensajes son fijos. Tabla completa en ADR 0033 §5.

| ErrorCode | Público |
|---|---|
| UNAUTHORIZED | 401 `unauthorized` + `WWW-Authenticate: Bearer` |
| FORBIDDEN | 403 `account_disabled` / `insufficient_permissions` / `forbidden` |
| INVALID_REQUEST | 404 `asset_not_found`; 422 `too_many_attachments` / `attachments_too_large` / `validation_error` |
| LOCAL_UNAVAILABLE | 429 `too_many_requests`; 503 `identity_provider_unavailable` / `knowledge_store_unavailable` / `local_node_unavailable` |
| TIMEOUT | 503 `local_node_timeout` |
| LOCAL_ERROR, PROTOCOL_ERROR, DUPLICATE_REQUEST | 503 `local_node_error` |
| CANCELLED | 503 `request_cancelled` |
| `AskResponse` inválida | 503 `local_node_invalid_response` |

Un `detail` desconocido cae en la fila genérica de su `ErrorCode`. Una excepción inesperada es
el `500 internal_error` genérico del proyecto.

### 4.6 Prevención de recursión

1. PC1 usa el default `local`; `relay` exige relay habilitado.
2. La ruta RELAY solo habla con el relay de su propio proceso.
3. El agente exige `https` hacia el relay y `http` sobre IP de loopback hacia ELSA.
4. El agente añade `X-Elsa-Relay-Hop: 1` a cada llamada local. La ruta RELAY rechaza su
   **presencia**, con cualquier valor, antes de autenticar y de `submit`, venga de un
   navegador o de cualquier otro cliente. **CORS no es el mecanismo de seguridad.** LOCAL
   ignora la cabecera.

Un PC1 configurado por error en RELAY no ejecuta nada ni forma un ciclo: rechaza la llamada
del agente y el usuario recibe `503 local_node_unavailable` (probado de extremo a extremo).

### 4.7 Watcher de desconexión, cancelación y plazos

- **Hallazgo:** con Starlette 1.6 y `BaseHTTPMiddleware`, una desconexión del navegador no
  cancela el endpoint por sí sola.
- `_submit_until_disconnect` lanza **como máximo 1 tarea de `RelayService.submit` y 1
  watcher** de `http.disconnect` por petición:
  - `submit` termina primero → el watcher se cancela y se recoge;
  - la desconexión llega primero → `submit` se cancela, el `CancelledError` llega a
    `RelayService.submit`, el relay libera la solicitud y encola el `CANCEL` *best effort*;
  - `finally` + `gather` recogen siempre ambas tareas;
  - si el watcher falla, la espera termina igual (fail-safe) y se registra
    `disconnect_watcher_failed` con el tipo de error, nunca su texto.
- **Plazos:** no se añadió ninguno. La espera pública la acota el TTL del relay (120 s); el
  agente corta antes (110 s, con margen de entrega); la caída del nodo se detecta por su TTL
  (45 s). PC1 fuera de línea al enviar = fallo inmediato, sin cola.

### 4.8 Logs y correlación

El `request_id` HTTP de Render acompaña los logs de la petición. La ruta asigna el
`relay_request_id` antes de `submit` y emite un único evento `assistant_relayed`: ambos ids,
resultado, código público, estado HTTP y duración. El agente envía `X-Request-ID =
relay_request_id` y ELSA local registra ese mismo id. Nunca se registran pregunta, metadatos
de adjuntos, token del usuario o del nodo, resultado, cuerpo del cable ni `detail`.

## 5. Decisiones

| # | Decisión | Motivo | Marca |
|---|---|---|---|
| D1 | Render en RELAY **autentica** (JWT + control de abuso); la autorización funcional (perfil, cuenta, permisos, alcance, activo, conocimiento, Materiales) es de PC1 | La cadena existente de `/ask` lee conocimiento, permisos y Materiales; ADR 0029 §4 dice que Render no ejecuta decisiones de ELSA. Se reportó como inconsistencia antes de codificar | DECISIÓN TOMADA (responsable, opción A) |
| D2 | Fallos del nodo y timeout = **503** con códigos públicos diferenciados | En el repositorio todo fallo de dependencia es 503; no se usa 502 ni 504 | DECISIÓN TOMADA (responsable) |
| D3 | `local` + `relay_enabled=true` permitido; **sin cambio automático de modo** | Pruebas y administración del nodo | DECISIÓN TOMADA (responsable) |
| D4 | `X-Elsa-Relay-Hop: 1` contra la reentrada | Única forma de que la recursión sea imposible por petición, no solo por configuración | DECISIÓN TOMADA (responsable) |
| D5 | Watcher explícito de `http.disconnect` que cancela el `submit` | Starlette 1.6 no cancela el endpoint al desconectarse el cliente | DECISIÓN TOMADA (responsable) |
| P1 | `domain`/`asset` mal formados → **422 `validation_error`**, no 403 | La validación estructural no es autorización; los 403 reales vienen de PC1 | DECISIÓN TOMADA (precisión obligatoria) |
| P2 | Adjuntos: `AskRequest` conserva su contrato; validación funcional autoritativa = ELSA local; `Request` ≤ 16 KiB = protección de transporte. Ningún límite nuevo | No duplicar reglas | DECISIÓN TOMADA (precisión obligatoria) |
| P3 | La cabecera de salto es defensa estructural; la seguridad no depende de CORS | Un cliente no navegador puede enviarla | DECISIÓN TOMADA (precisión obligatoria) |
| P4 | Watcher: máximo 1 `submit` + 1 watcher; limpieza con `finally`/`gather`; 0 tareas huérfanas | Sin trabajo huérfano | DECISIÓN TOMADA (precisión obligatoria) |
| I1 | Dos routers seleccionados en `create_app` en lugar de un `AssistantExecutor` | Las dependencias de FastAPI son estáticas; un ejecutor obligaría a rehacer el orden «autorizar antes de recuperar» de la ruta local | DECISIÓN TOMADA (microplan aprobado; ADR 0033 §2) |
| I2 | Validación `strict` y campos extra descartados | Sin coerciones; tolera desfase de versión PC1 ↔ Render sin dejar pasar nada no declarado | DECISIÓN TOMADA (ADR 0033 §4) |
| I3 | Un único evento de correlación `assistant_relayed` | Mínimo necesario para diagnosticar sin datos sensibles | DECISIÓN TOMADA (microplan aprobado) |

## 6. Pruebas

**HECHO MEDIDO.** Se ejecutaron:

- los tests de D2.4 (`tests/test_api_assistant_relay.py`, `tests/test_assistant_relay_end_to_end.py`);
- los tests de D2.2/D2.3 afectados (protocolo, servicio y API del relay, agente completo);
- autenticación, autorización, control de abuso, asistente, configuración y errores;
- la suite completa **sin** suprimir avisos;
- `ruff check .`, `ruff format --check .`, `mypy`, `mypy --platform linux`,
  `git diff --check` y `pre-commit run --all-files` (incluye gitleaks);
- repeticiones de los tests de cancelación: 30 antes de las correcciones de la revisión y 10
  después.

Comportamiento cubierto (**HECHO DEL REPOSITORIO**):

| Área | Qué cubren los tests |
|---|---|
| Composición | Un solo router por modo (verificado por el `operationId` de OpenAPI); LOCAL sin relay, agente ni token del nodo; `local` con relay habilitado sigue local |
| No ejecución en Render | Conocimiento, permisos, identidad de Materiales e inventario son **trampas** en la app pública; la lógica local de `assistant` se parchea para fallar; 0 usos |
| E2E | App pública RELAY → `RelayService` real → `NodeAgent` real → app local LOCAL: 200, cuerpo idéntico al de ELSA local directa, **una** ejecución local, mismo token en PC1, token del nodo solo hacia el relay, cabecera de salto presente, sin solicitudes pendientes |
| Autenticación | Sin token, esquema no Bearer y token inválido → 401 sin `submit`; proveedor caído → 503 sin `submit`; válido en Render pero rechazado en PC1 → 401 / 403 `account_disabled` sin fuga del token; alcance fuera de permisos → 403 de PC1 |
| Estructura | `domain`/`asset` mal formados → 422 sin `submit`; pregunta demasiado larga → 422 sin `submit` |
| Recursión | Cabecera de salto con valores `1`, `0`, vacío y `yes`, con y sin token, desde cliente no navegador → 503 sin `submit`; PC1 mal configurado en RELAY → 503, su relay con 0 pendientes |
| Respuesta del nodo | Forma ajena, otro activo, otro dominio, booleano y entero coaccionados, lista inválida, falta de `message` → 503 sin eco; campos extra descartados |
| Errores | 22 combinaciones `ErrorCode`/`detail` con sus estados y códigos públicos; `detail` ausente de cuerpo y logs; todo `ErrorCode` traducible; `WWW-Authenticate` en 401; excepción inesperada → 500 genérico registrado como `internal_error` |
| Offline | Sin nodo → 503 inmediato (< 1 s), sin fallback |
| Cancelación | Desconexión ASGI con la solicitud despachada → `CANCEL` al nodo, 0 pendientes; cancelación de la petición pública → `CANCEL`, llamada local cancelada en PC1; watcher fallido registrado |
| Tareas | En vuelo, exactamente `RelayService.submit` + `_wait_for_disconnect`; al terminar, ninguna |
| Sesión perdida | Sesión reemplazada con la solicitud en vuelo → 503, **sin replay** (1 llamada local), agente con sesión nueva, siguiente petición 200 |
| Timeout | ELSA local lenta → 503 `local_node_timeout`, sin replay, 0 pendientes |
| Logs | Correlación `request_id` HTTP ↔ `relay_request_id` ↔ logs del agente y de ELSA local; ausencia de tokens, `Bearer`, `Authorization`, pregunta, nombre de adjunto, resultado y `detail` |
| Configuración | Default `local`; `relay` sin relay → no arranca; `local` + relay válido; 7 valores ambiguos rechazados |

## 7. Comandos relevantes

```bash
git fetch --all --prune
git diff --stat aa890b0 75490a7

uv run pytest -q tests/test_api_assistant_relay.py tests/test_assistant_relay_end_to_end.py
uv run pytest -q tests/test_relay_protocol.py tests/test_relay_service.py tests/test_api_relay.py \
  tests/test_agent_config.py tests/test_agent_local_client.py tests/test_agent_relay_client.py \
  tests/test_agent_runner.py tests/test_agent_end_to_end.py
uv run pytest -q tests/test_api_authentication.py tests/test_api_authorization.py \
  tests/test_auth_supabase.py tests/test_contract_auth.py tests/test_authorization_rules.py \
  tests/test_abuse_control.py tests/test_api_assistant.py tests/test_api_assistant_availability.py \
  tests/test_config.py tests/test_errors.py
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run mypy --platform linux
git diff --check origin/main...HEAD
uv run pre-commit run --all-files
```

Configuración de los dos lados (valores de ejemplo; **no ejecutado contra Render ni PC1
real**):

```text
Render:  ELSA_ASSISTANT_EXECUTION_MODE=relay   ELSA_RELAY_ENABLED=true   (+ variables del relay)
PC1:     ELSA_ASSISTANT_EXECUTION_MODE=local   (default; no hace falta declararla)
```

## 8. Resultados

**HECHO MEDIDO** sobre el HEAD funcional `ad28056`. El merge `75490a7` tiene como padres
`aa890b0` y `ad28056`, y `aa890b0` es el merge-base: el árbol mergeado es el mismo que se
probó.

```text
uv run pytest -q   →   2 failed, 2003 passed, 230 skipped, 3 warnings in 163.89s (0:02:43)
FAILED tests/test_bench_harness.py::test_a_run_records_what_produced_it
FAILED tests/test_bench_harness.py::test_peak_memory_is_measured_where_the_posix_api_exists
```

| Comprobación | Resultado |
|---|---|
| Tests D2.4 | `72 passed, 2 warnings in 11.80s` |
| Tests D2.2/D2.3 afectados | `364 passed, 2 warnings in 15.74s` |
| Auth / assistant / config / errors | `176 passed, 3 warnings in 9.14s` |
| Fallos de la suite | Los 2 son el **baseline histórico de Windows** (`runner.resource is None` en `tests/test_bench_harness.py`) |
| Warnings de la suite | 3, preexistentes: deprecación del testclient de Starlette, alias `anyio.abc.BlockingPortal`, clave HMAC corta en `test_auth_supabase`. **Ninguno originado por D2.4** |
| Skips | 230; todos requieren `ELSA_TEST_DATABASE_URL` |
| Regresiones nuevas | **0**: 1919 → 2003 passed, +84, exactamente los tests nuevos |
| `ruff check .` | `All checks passed!` |
| `ruff format --check .` | `347 files already formatted` |
| `mypy` (Windows) | 3 errores, todos históricos en `src/elsa/bench/runner.py` (`getrusage`, `RUSAGE_SELF`, `unused-ignore`); archivo no tocado por D2.4 |
| `mypy --platform linux` (plataforma del CI) | `Success: no issues found in 244 source files` |
| `git diff --check origin/main...HEAD` | limpio |
| `pre-commit run --all-files` | todos **Passed**, incluido «Detect hardcoded secrets» (gitleaks) |
| Tests de cancelación repetidos | 30 + 10 ejecuciones, **0 fallos**, 0 «Task exception was never retrieved» |

## 9. Métricas

| Métrica | Valor | Método |
|---|---|---|
| Tests nuevos | 84 (72 de D2.4 + 11 de configuración + 1 del agente) | `pytest --collect-only` sobre `main` (`75490a7`) |
| Tests D2.4 por archivo | ruta RELAY 60, E2E 12 | `pytest --collect-only` |
| Diferencia en la suite | 1919 → 2003 passed (+84) | comparación con el baseline del cierre D2.3 |
| Archivos del PR | 13 (4 creados, 9 modificados) | `git diff --name-status aa890b0 75490a7` y API de GitHub (`changed_files`) |
| Líneas del PR | +2110 / −17 | `git diff --numstat aa890b0 75490a7` |
| Commits del PR | 10 | `git rev-list --count aa890b0..ad28056` y API de GitHub |
| Dependencias nuevas | 0 | `pyproject.toml` y `uv.lock` sin cambios |

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO / DEL PROCESO.** Claude Code (modelo Claude Opus 5.5) hizo lo
siguiente:

- comprobó el gate de D2.3, auditó el repositorio y redactó el microplan, reportando la
  inconsistencia D1 antes de codificar;
- implementó ADR 0033, la configuración, `admitted_identity`, la ruta RELAY, la cabecera del
  agente, los tests y la documentación de variables;
- ejecutó las verificaciones de §8 y lanzó las revisiones de subagentes;
- corrigió los hallazgos de la revisión;
- redactó este documento.

El responsable del proyecto:

- aprobó el microplan con las decisiones D1–D5 y 4 precisiones obligatorias;
- autorizó un máximo de 13 archivos;
- ordenó la revisión integral pre-PR;
- creó y mergeó el PR #50.

- **Identificador de sesión:** el directorio local de sesión que aparece en las rutas de
  trabajo es `02f464ac-a5da-4980-9c27-8fb1e426db90`. No se contrastó contra otra fuente; se
  registra tal como aparece y **no** se garantiza más que eso.
- **Qué se revisó:** diffs, salidas reales de comandos y dos revisiones de subagentes en modo
  solo lectura sobre `79a65a4` (§13). Las correcciones `f2e03fc` y `ad28056` se verificaron con
  tests, lint, tipos y gitleaks, **sin** una nueva ronda de subagentes. Los informes de los
  subagentes se entregaron a la sesión y **no** se versionan.

## 11. Aportes de Codex

Nada que registrar: Codex no participó en D2.4.

## 12. Operaciones manuales y de PowerShell

- Consultas **solo lectura** a la API pública de GitHub, sin autenticación, para el estado
  de los PR #49 y #50, el merge y las ejecuciones de CI.
- Lectura, sin modificarlo, del código instalado de Starlette 1.6
  (`starlette/middleware/base.py`) para confirmar cómo trata la desconexión.
- Los PR #49 y #50 los **creó y mergeó el responsable del proyecto** desde su navegador: el
  entorno de la sesión no tiene `gh`.
- No se tocó Render, Supabase, Materiales, Phi/llama.cpp, PC1 real, el firewall ni la red.

## 13. Incidentes

| # | Incidente | Qué se hizo | Estado |
|---|---|---|---|
| 1 | Primer intento: el cierre de D2.3 estaba solo en su rama documental | D2.4 se declaró BLOQUEADO y no se escribió nada | Resuelto con el merge del PR #49 |
| 2 | En el segundo gate, el CI de `main` (`aa890b0`) seguía en curso | Se auditó en solo lectura y la rama se creó tras verlo en SUCCESS | Resuelto |
| 3 | Inconsistencia en la instrucción: «mantener la autenticación/autorización existente» frente a «0 llamadas a conocimiento y Materiales en Render» | Reportada en el microplan; el responsable eligió D1 = A | Resuelto por decisión |
| 4 | Starlette 1.6 no cancela el endpoint cuando el cliente se desconecta | Se diseñó el watcher (D5), aprobado | Resuelto |
| 5 | `b2bcaaf` dejó tests de configuración con errores de tipos (`dict[str, object]`) | Corregido dentro de `206e9ea` y declarado en su mensaje | Resuelto |
| 6 | FastAPI 0.141 anida los routers incluidos en un objeto privado y el test de rutas no los veía | Comprobación por `operationId` de OpenAPI, API pública | Resuelto antes de `206e9ea` |
| 7 | Test de timeout con TTL de 0,4 s: el agente reserva 2 s de margen de entrega y lo daba por expirado al llegar | El test usa el plazo local del agente (0,3 s) con el TTL normal, como en producción (110 s < 120 s) | Resuelto antes de `9a76a15` |
| 8 | E2E de cancelación intermitente: la comprobación global de tareas detectaba el long poll propio del agente | La comprobación se limitó a las tareas de la ruta RELAY; el test unitario exige exactamente 1 `submit` + 1 watcher en vuelo | Resuelto en `79a65a4` |
| 9 | Revisión de seguridad, MINOR: una excepción inesperada se registraba como `cancelled` | `internal_error` por defecto; `cancelled` solo ante `CancelledError` | Resuelto en `f2e03fc` |
| 10 | Revisión de seguridad, MINOR: capacidad compartida del relay | Documentada como riesgo residual en ADR 0033 | Registrado (§19) |
| 11 | Revisión de arquitectura, MINOR: `architecture.md` parecía aplicar a todo Render la frase que solo vale para `assistant.ask` | Frase acotada; el resto de la API queda para D2.5 | Resuelto en `ad28056` |
| 12 | NIT de ambas revisiones: watcher fallido sin rastro, comentarios sobre el escudo y `strict`, vida del token, volumen del log de salto, texto de ADR §4/§5 | Corregidos o documentados | Resueltos en `f2e03fc` / `ad28056` |
| 13 | NIT: constante `RELAY_HOP_HEADER` duplicada en API y agente | Se mantiene: el agente no importa la API y `protocol.py` no se toca; un test compara ambas | Aceptado |
| 14 | `mypy` en Windows con 3 errores en `src/elsa/bench/runner.py` | Confirmado como baseline de plataforma con `mypy --platform linux` | Baseline, no se corrige |
| 15 | El SHA del merge se tomó de Git y de la API, no de una captura | `75490a71164660db7bcb43ae5f169d659b12d9b6` | Verificado |

## 14. Git

- Una rama funcional desde `main`, 10 commits, un PR, merge con *merge commit*.
- No se hizo `amend`, `rebase`, `squash` ni `force push`.
- Archivos intactos: `src/elsa/api/v1/assistant.py`, `src/elsa/container.py`,
  `src/elsa/relay/*` (incluido `protocol.py`), `render.yaml`, `web/`, `supabase/`,
  adaptadores y puertos (Materiales, LLM), `pyproject.toml` y `uv.lock`.
- **Creados (4):**
  - `docs/adr/0033-modo-de-ejecucion-de-assistant-ask-local-o-relay.md`;
  - `src/elsa/api/v1/assistant_relay.py`;
  - `tests/test_api_assistant_relay.py`;
  - `tests/test_assistant_relay_end_to_end.py`.
- **Modificados (9):** `.env.example`, `docs/architecture.md`,
  `docs/environment-variables.md`, `src/elsa/agent/local_client.py`, `src/elsa/api/deps.py`,
  `src/elsa/config.py`, `src/elsa/main.py`, `tests/test_agent_local_client.py`,
  `tests/test_config.py`.
- **Documental de este cierre:** se crea este archivo en la rama
  `docs/closure-d2-4-end-to-end`. `docs/architecture.md` **no** se modifica: ya refleja D2.1–D2.4
  como implementados en código, no operativos en red real, y acota a `assistant.ask` la
  afirmación sobre conocimiento, permisos y Materiales.

## 15. Ramas

| Rama | Uso | Estado |
|---|---|---|
| `claude/d2-4-end-to-end-integration` | Trabajo funcional de D2.4 | Mergeada vía PR #50; **no eliminada** todavía |
| `docs/closure-d2-4-end-to-end` | Este documento | Creada desde `main` (`75490a7`); su PR y su merge los registra GitHub |

## 16. Commits

| Commit | Mensaje |
|---|---|
| `babd05f5c8c7fc3ff32a9b7f59e8749033412ddd` | `docs(adr): add ADR 0033 for the assistant.ask execution mode` |
| `b2bcaaf46ed73d3c6053e463bc79bbcc16110bb6` | `feat(config): add ELSA_ASSISTANT_EXECUTION_MODE with fail-closed validation` |
| `fc073d33c0a22b564a2a25595a94169a858f4c34` | `refactor(api): extract admitted_identity without behavior change` |
| `206e9ea80581ba66d2bb010bc056ff1bd09b7c6f` | `feat(api): relay-backed assistant.ask route with response validation and error mapping` |
| `050da2f15d920e26b66ecbe447bfe72d68ae929a` | `feat(agent): mark local calls with a relay hop header` |
| `9a76a15f8d10ef2dc7643def91a28c8b81a2e6fd` | `test(e2e): public app to relay to agent to local ELSA in memory` |
| `e923317a0396461c68d92bb2cb58a1a8c1546543` | `docs(env): document the assistant execution mode` |
| `79a65a46df6894d9cdb2832ecc1332f1ba1509ff` | `test(e2e): scope the orphan-task check to relay route tasks` |
| `f2e03fcb51e2c03b54675099e3b1184f9b4ebc06` | `fix(api): label unexpected relay failures and log watcher errors` |
| `ad28056cf9842dfceb262f18bace289982d475a1` | `docs(adr): align ADR 0033 with the code and record residual risks` |
| `75490a71164660db7bcb43ae5f169d659b12d9b6` | Merge del PR #50 en `main` |

**HECHO DEL REPOSITORIO:** `ad28056` es ancestro de `origin/main`, comprobado con
`git merge-base --is-ancestor`.

## 17. Pull requests

| PR | Estado | Detalle |
|---|---|---|
| #50 | **Mergeado** el 2026-10-18 14:29:50 UTC | `feat(assistant): integrate relay execution mode end to end`; 10 commits, 13 archivos; base `main`, head `claude/d2-4-end-to-end-integration`; merge `75490a71164660db7bcb43ae5f169d659b12d9b6` |

CI (**HECHO MEDIDO** con la API pública de GitHub, en solo lectura):

| Ejecución | Evento | HEAD | Lint, types and tests | Secret scan (gitleaks) |
|---|---|---|---|---|
| 39133542813 | push (rama) | `79a65a4` | SUCCESS, job 117693383889 | SUCCESS, job 117693383636 |
| 39135105892 | push (rama) | `ad28056` | SUCCESS, job 117697917984 | SUCCESS, job 117697918144 |
| 39136002490 | pull_request (#50) | `ad28056` | SUCCESS, job 117700526994 | SUCCESS, job 117700526749 |
| 39136247090 | push (`main`, merge #50) | `75490a7` | SUCCESS, job 117701240039 | SUCCESS, job 117701239868 |

## 18. Migraciones

Ninguna. D2.4 no escribió ni aplicó migraciones y no tocó ningún proyecto Supabase
(regla 15). Base de datos nueva: NO. Migraciones: NO. Redis: NO. Supabase nuevo: NO.
Persistencia nueva del relay: NO. Esquema nuevo: NO.

## 19. Estado operacional final

**HECHO DEL REPOSITORIO: qué existe en `main`.** Lo descrito en §4.1–§4.8: dos modos
explícitos de `assistant.ask`, LOCAL por defecto y RELAY fail-closed, con la frontera Render /
PC1, la validación de la respuesta, la tabla de errores cerrada, la cabecera de salto, el
watcher de desconexión y la correlación de logs.

**Qué NO está conectado (HECHO DEL REPOSITORIO):**

| Elemento | Estado |
|---|---|
| Integración usuario ↔ relay ↔ agente ↔ ELSA local en código | **SÍ**, probada en memoria |
| Conexión real Render ↔ PC1 | **NO** |
| Despliegue real en Render | **NO** |
| Token real del nodo operativo | **NO** (no generado) |
| Latencia real de Internet | **No medida** |
| Timeout real del proxy de Render | **No medido** |
| Watcher con una conexión externa real a uvicorn/Render | **No validado** |
| Prueba desde PAPELSA | **NO** |
| Login real y Modo ELSA | **Pendientes** |
| Dependencias nuevas | **0** |

**Riesgos residuales y limitaciones** (ADR 0031 §6, ADR 0032 §3, ADR 0033), todos abiertos y
**no** resueltos por asociación con D2.4:

| # | Riesgo / limitación | Consecuencia |
|---|---|---|
| 1 | **Poll perdido sin ACK** | Un `Request` cuya respuesta de poll se pierde puede expirar sin ejecutarse; resolverlo del todo exige una versión posterior del protocolo |
| 2 | **CANCEL best effort** | No garantiza detener el trabajo ya iniciado dentro de ELSA local, Materiales o un futuro LLM |
| 3 | **Relay en memoria** | Un reinicio completo de Render pierde sesiones, solicitudes pendientes e historial de ids; sin replay |
| 4 | **Solicitud en cola** | Si el nodo cae después del `submit`, la solicitud en cola espera una sesión nueva hasta su TTL |
| 5 | **Capacidad compartida** | `relay_max_pending=16` en total frente a 5 simultáneas por usuario: con PC1 lento, varias cuentas autenticadas pueden llenar el relay y el resto recibe `503 local_node_unavailable` hasta que venzan los plazos |
| 6 | **Timeout real del proxy de Render** | Todavía no medido |
| 7 | **Watcher** | Probado con Starlette/`ASGITransport` y revisado contra el código de Starlette 1.6; no validado con una conexión externa real a uvicorn/Render |
| 8 | **Token del usuario en memoria** | Permanece en la memoria de Python mientras vive la petición (caché de dependencias, `scope` ASGI), igual que en LOCAL; no se reclama borrado seguro |
| 9 | **`relay_hop_rejected`** | Un cliente anónimo puede provocar ese `WARNING`; el evento está saneado y no contiene secretos |
| 10 | **Campos extra de `AskResponse`** | Se descartan según el contrato actual; una deriva de contrato pasa en silencio |
| 11 | **Limitaciones heredadas de Pilot 0.1** | `ElsaLocalClient` sin `Accept-Encoding: identity`, `trust_env=False`, puerto loopback, dos agentes con el mismo `node_id`, desfase de reloj PC1 ↔ Render y las demás del cierre D2.3 §19 siguen vigentes |
| 12 | **Resto de la API en RELAY** | `/me`, `/access`, `/admin`, `/knowledge`, `/technical`, `/assets`, `/contributions` y la siembra demo siguen sirviéndose en el proceso público; ADR 0033 solo decide `assistant.ask` |

## 20. Pendientes

Ninguno de estos se cierra por asociación con D2.4.

| # | Pendiente | Responsable / bloque |
|---|---|---|
| 1 | Qué debe servir Render en modo RELAY con el resto de la API frente a ADR 0029 §4 (y la siembra demo) | D2.5, con su propio ADR |
| 2 | Conexión real Render ↔ PC1 | Despliegue controlado |
| 3 | Despliegue real en Render en modo RELAY (un worker; configuración de `TEST` exige hoy `PERMISSIONS_BACKEND=postgres` aunque `assistant.ask` no lo use) | Responsable / despliegue |
| 4 | Generación y custodia del token real del nodo y de su hash | Responsable del proyecto |
| 5 | **Mediciones reales**: long polling, plazos (25 / 45 / 110 / 120 s), timeout del proxy de Render, latencia de Internet y comportamiento del watcher con uvicorn real | Despliegue controlado |
| 6 | Cupo por usuario dentro del relay, si la capacidad compartida (§19 #5) resulta un problema | Decisión futura explícita |
| 7 | Prueba en entorno PAPELSA | Bloques posteriores |
| 8 | Login real (operación normal) y Modo ELSA | Bloques posteriores |
| 9 | Riesgos y limitaciones de §19 | Reevaluar antes de producción |
| 10 | Eliminar las ramas `claude/d2-4-end-to-end-integration` y `docs/closure-d2-4-end-to-end` tras el merge de este documento y el CI final de `main` | Responsable |

## 21. Siguiente bloque

**D2.5**, solo después de que este documento esté integrado en `main` con CI verde y con
autorización explícita del responsable (regla 20). D2.4 deja la cadena completa implementada
y probada en memoria; **no** deja nada conectado ni desplegado.

---

## Criterios de cierre

| Criterio | Estado |
|---|---|
| PR #50 mergeado; merge SHA real verificado con Git y la API | Cumplido |
| `ad28056` contenido en `main`; 10 commits y 13 archivos integrados; ADR 0033 en `main` | Cumplido |
| CI de `main` del merge (run 39136247090) en verde | Cumplido |
| LOCAL default y preservado; `assistant.py` sin cambios | Cumplido |
| RELAY fail-closed; `relay` sin relay habilitado no arranca; un solo router por modo | Cumplido |
| Render en RELAY solo autentica; 0 ejecución de conocimiento, permisos, Materiales o lógica local | Cumplido |
| Mismo token del usuario revalidado en PC1; token del nodo separado | Cumplido |
| `RelayService.submit` directo; sin protocolo nuevo; sin fallback; sin replay | Cumplido |
| `AskResponse` validada (estricta, mismo `domain`/`asset`); `detail` nunca expuesto; tabla de errores cerrada | Cumplido |
| Estructura mal formada = 422; 403 solo de PC1 | Cumplido |
| Recursión imposible por petición (cabecera de salto, sin depender de CORS) | Cumplido |
| Watcher: 1 `submit` + 1 watcher, limpieza garantizada, 0 tareas huérfanas, 40 repeticiones sin fallos | Cumplido |
| E2E en memoria con relay real, agente real y app local | Cumplido |
| Suite sin regresiones nuevas (2 fallos baseline Windows, 3 warnings preexistentes); ruff verde; mypy Linux verde; gitleaks verde | Cumplido |
| `architecture-reviewer` y `security-reviewer` sin hallazgos bloqueantes | Cumplido |
| Dependencias nuevas = 0; base de datos nueva = NO; Render real y PC1 real no utilizados | Cumplido |
| `docs/architecture.md` coherente con D2.4 | Cumplido (sin cambios en este documental) |

## Regla de continuidad

Este documento **completa el cierre formal de D2.4 al quedar integrado en `main` con el CI
obligatorio en verde**. Su propio PR y su merge documental los registran Git y GitHub. Este
documento **no se auto-referencia** con un SHA propio: hacerlo obligaría a otro cambio solo
para anotarlo. Mientras no esté integrado, D2.4 se considera abierto.

## Veredicto

**D2.4 — INTEGRACIÓN EXTREMO A EXTREMO CERRADO FORMALMENTE: SÍ**, como estado efectivo al
quedar este documento integrado en `main` con CI verde.

- PR funcional #50 **mergeado** (`75490a71164660db7bcb43ae5f169d659b12d9b6`); CI de `main`
  (run 39136247090) con Lint/types/tests y Gitleaks en **SUCCESS**.
- Revisiones: `architecture-reviewer` BLOCKING NO; `security-reviewer` BLOCKING NO.
- Evidencia funcional preservada sobre `ad28056`:
  - 72 tests D2.4, 364 de D2.2/D2.3 y 176 de auth/assistant/config/errors;
  - suite completa: 2003 passed, 230 skipped, 2 failed (baseline Windows), 3 warnings
    preexistentes;
  - regresiones nuevas: 0.

Estado que se mantiene:

```text
INTEGRACIÓN EXTREMO A EXTREMO EN CÓDIGO: SÍ (en memoria)
MODO LOCAL PRESERVADO:                   SÍ
FALLBACK LOCAL EN RELAY:                 NO
REPLAY DE REQUEST:                       NO
PC1 REAL CONECTADO A RENDER:             NO
RED EXTERNA OPERATIVA:                   NO
DEPLOY REAL RENDER:                      NO
DEPENDENCIAS NUEVAS:                     0
```

**D2 sigue abierto**; no hay acceso remoto funcionando. Los pendientes de §20 siguen abiertos
y no se cierran por asociación.
