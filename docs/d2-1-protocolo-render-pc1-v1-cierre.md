# Cierre formal — D2.1: Protocolo Render ↔ PC1 V1

- **Fecha:** 2026-10-05 (UTC; el PR #43 se mergeó el 2026-10-05 02:48 UTC, 2026-10-04 en hora local)
- **Estado:** **CERRADO**
- **Qué cierra:** el subbloque **D2.1** del bloque D2 (acceso remoto seguro a ELSA):
  la auditoría de D2, la formalización de la arquitectura híbrida Render–PC1 (ADR 0029)
  y el **contrato lógico** del protocolo Render ↔ PC1 V1 (ADR 0030), con sus modelos
  puros y sus pruebas.
- **Qué NO cierra:** **no cierra D2.** No hay red, relay, agente de PC1, heartbeat
  operativo, cola, despliegue, login real ni Modo ELSA. **No hay acceso remoto
  funcionando.** Ver §20.
- **Identificador del bloque:** `D2` / `D2.1` es la nomenclatura de trabajo usada en
  el proyecto; el repositorio no define un identificador formal más allá de ella. El
  nombre de este archivo lleva `d2-1` para que **no pueda leerse como el cierre de D2**.
- **Marcas de afirmación** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**,
  **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Sanitización:** este documento no contiene secretos, tokens, correos, claves,
  cadenas de conexión, IP públicas, identificadores de usuario ni datos de planta
  (reglas 11 y 12). Los valores de prueba del protocolo son sintéticos y no se
  reproducen aquí.

---

## 1. Objetivo

Dejar **formalizada y verificable** la arquitectura de acceso remoto y un **contrato
único** que compartan los futuros componentes (relay en Render, agente en PC1), de modo
que no inventen formatos independientes ni conviertan el agente en un proxy genérico:

```text
PC PAPELSA
    │  HTTPS / navegador
    ▼
RENDER                      (extremo público / intermediario)
    │  transporte seguro futuro, iniciado desde PC1
    ▼
PC1
    ├── ELSA
    ├── IA local · Phi / llama.cpp
    ├── conocimiento local
    └── Materiales
```

## 2. Alcance

**Entró (HECHO DEL REPOSITORIO, 6 archivos, +2076 / −0):**

| Archivo | Papel |
|---|---|
| `docs/d2-acceso-remoto-seguro-auditoria.md` | Auditoría de D2, evolución de la arquitectura, diseño del transporte (sin implementar) |
| `docs/adr/0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md` | Decisión de arquitectura híbrida |
| `docs/adr/0030-protocolo-relay-render-pc1-v1.md` | Decisión del contrato lógico V1 |
| `src/elsa/relay/__init__.py` | Marcador de paquete, sin efectos |
| `src/elsa/relay/protocol.py` | Modelos, enums y validadores puros del protocolo V1 |
| `tests/test_relay_protocol.py` | Pruebas del protocolo (85) |

**Quedó fuera, explícitamente:** red; relay HTTP; *long polling* u otro transporte;
agente de PC1; heartbeat real; cola real; Render ↔ PC1 operativo; despliegue;
cualquier cambio de `render.yaml`, `config.py`, `main.py` o `assistant.py`;
autenticación real del nodo; login real; Modo ELSA; Materiales; Supabase; LLM;
migraciones; dependencias nuevas.

## 3. Estado inicial

- **HECHO DEL REPOSITORIO:** `main` en `cc924f42178390b2a5da3c3b3209d81545bc02a5`
  (merge del PR #42, cierre formal de ELSA–Materiales V1). El cierre V1 dejaba D2
  como siguiente bloque con el mecanismo **abierto** («red privada o VPN preferible
  a exponer PC1»).
- **HECHO DEL REPOSITORIO:** Render existía solo como **demo sintética HTTPS**
  (`76462ed`, `3d643b2`, `render.yaml`): un servicio, DEV, datos en memoria, sin
  Supabase ni secretos. El runtime LLM solo escucha en loopback y rechaza uno remoto
  (ADR 0018). **No existía ningún relay, WebSocket, polling, túnel, worker ni agente**
  entre Render y PC1.
- **Baseline de pruebas previo a D2:** 1556 passed, 230 skipped, 2 failed (los 2 son
  de Windows, ver §9).

## 4. Trabajo realizado

En orden (HECHO DEL REPOSITORIO, §16):

1. **Auditoría inicial de D2** (`558407d`). Describió PC1, firewall, login y seguridad
   web, pero **reabrió la elección de arquitectura** (túnel de terceros frente a otras)
   como si no estuviera decidida. Se corrigió después.
2. **Auditoría de continuidad.** Se buscó en código, historial Git, ADR y documentos
   de traspaso un diseño PAPELSA → Render → PC1. **No se encontró evidencia versionada**
   de relay ni de mecanismo de transporte. El responsable reafirmó la arquitectura
   como decisión actual.
3. **Formalización** (`cd256c2`): ADR 0029 y reescritura del documento D2 (evolución de
   la arquitectura, responsabilidades, diseño del transporte, incrementos).
4. **Implementación del contrato** (`201d458`): `protocol.py`, pruebas y ADR 0030.
5. **Revisión y endurecimiento** (`2e49d67`): ver §12.
6. **PR #43** y merge (`edf658a…`).

## 5. Decisiones

| Decisión | Motivo | Marca |
|---|---|---|
| **Render es el extremo público; PC1 es el nodo de ejecución local; IA y modelo en PC1; PC PAPELSA solo navegador; ningún puerto público en PC1** (ADR 0029) | Objetivo del responsable, sin depender de TI de PAPELSA y sin exponer PC1 | **DECISIÓN TOMADA** (responsable del proyecto) |
| El historial **no se reinterpreta**: Render nació como demo sintética; la evolución a híbrida **no estaba formalizada** y se formaliza ahora | No falsear la historia | **DECISIÓN TOMADA** |
| El protocolo es **independiente del transporte** (ADR 0030); el *long polling* es **recomendación de diseño**, no decisión | Poder sustituir el transporte sin redefinir V1 | **DECISIÓN TOMADA** |
| `protocol_version = "1"` (string); versión desconocida rechazada; sin negociación | Falla cerrado | **DECISIÓN TOMADA** |
| Seis mensajes (`register`, `heartbeat`, `request`, `response`, `error`, `cancel`); **sin `ACK`** | V1 mínimo; no se demostró una invariante que lo requiera | **DECISIÓN TOMADA** |
| `assistant.ask` como **única operación**, lista cerrada | El agente no debe ser un proxy genérico | **DECISIÓN TOMADA** |
| `request_id` y `node_session_id` UUID; `node_id` con `^[A-Za-z0-9._-]{1,64}$` | Correlación inequívoca; identidad configurada, no derivada del equipo | **DECISIÓN TOMADA** |
| Timestamps en **UTC con offset cero**; sin reloj en la validación | Determinismo | **DECISIÓN TOMADA** |
| **At-most-once** por `request_id` dentro del `node_session_id` activo; **sin replay** tras desconexión; cancelación *best effort* | Una reconexión nunca duplica una acción | **DECISIÓN TOMADA** |
| `ErrorCode` cerrado, con `DUPLICATE_REQUEST` | Semántica at-most-once precisa | **DECISIÓN TOMADA** |
| `domain`/`asset`: solo no vacío; **sin charset nuevo** | `resolve_asset` no impone ninguno y el contrato no debe rechazar activos válidos | **DECISIÓN TOMADA** |

## 6. Pruebas

**HECHO MEDIDO** (ejecutadas en PC1 antes del PR y por CI después):

- `tests/test_relay_protocol.py`: **85 passed**.
- Suite completa local: ver §8.
- CI de la rama, del PR y del merge en `main`: ver §17.

Cobertura del protocolo: versión (válida, desconocida, entera); campos extra
rechazados en todos los mensajes y en parámetros anidados; inmutabilidad; `node_id`
válido e inválido; UUID; los seis mensajes y su etiqueta; operaciones (solo
`assistant.ask`); token del usuario (oculto en `repr`, `str`, `model_dump`,
`model_dump_json`; revelado solo por la vía de transporte explícita; ida y vuelta);
tiempos (UTC aceptado; naïve, otro offset y `expires_at ≤ created_at` rechazados;
sin dependencia del reloj); códigos de error cerrados; `result` JSON contractual
(rechaza `set`, `bytes`, objetos arbitrarios, `NaN` e infinitos); alineación de
límites con `AskRequest`/`AttachmentDeclaration`; ausencia de campos de proxy, de
secreto del nodo, de `service_role` y de `authorization`; módulo sin imports de red
ni de I/O; `parse_message` (enrutado por etiqueta, etiqueta obligatoria); estados,
transiciones y efecto de la cancelación.

## 7. Comandos relevantes

```bash
uv run pytest -q tests/test_relay_protocol.py
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q                       # suite completa
git diff --check origin/main...HEAD
```

## 8. Resultados

**HECHO MEDIDO** (ejecución local en PC1 del estado final de la rama, `2e49d67`):

```text
tests/test_relay_protocol.py : 85 passed
suite completa               : 1641 passed, 230 skipped, 2 failed, 3 warnings in 194.72s
ruff check .                 : All checks passed!
ruff format --check .        : 320 files already formatted
mypy                         : 3 errores, todos en src/elsa/bench/runner.py (históricos, Windows)
git diff --check             : limpio (solo avisos LF -> CRLF de Git en Windows)
```

Los 2 fallos son los conocidos de `tests/test_bench_harness.py`
(`test_a_run_records_what_produced_it` y
`test_peak_memory_is_measured_where_the_posix_api_exists`), por `resource` y
`peak_rss_mb` en Windows. Los 3 errores de mypy son `getrusage`, `RUSAGE_SELF` y un
`type: ignore` sin uso, todos en `bench/runner.py`. **No son de D2.1 y no se
corrigieron.**

## 9. Métricas

| Métrica | Valor | Método |
|---|---|---|
| Pruebas nuevas | **85** | `pytest tests/test_relay_protocol.py` |
| Passed antes → después | 1556 → 1641 (+85) | Dos ejecuciones completas en PC1 |
| Fallos nuevos | **0** | Los 2 fallos son los mismos de la baseline |
| Dependencias nuevas | **0** | `pyproject.toml` y `uv.lock` sin cambios en el diff |
| Archivos / líneas del PR #43 | 6 / +2076 −0, 4 commits | API pública de GitHub |

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO / DEL PROCESO.** Claude Code (modelo Sonnet 5.5) hizo la
auditoría, redactó ADR 0029 y ADR 0030 y el documento D2, implementó `protocol.py` y
sus pruebas, ejecutó las verificaciones de §8, encontró los hallazgos de §12 y redactó
este documento. El responsable aprobó cada plan antes de que se implementara y
reafirmó la decisión de arquitectura.

- **Identificador de sesión:** el directorio local de sesión que aparece en las rutas de
  trabajo es `c803f2da-f121-4eaa-81d8-7231347c4a84`. No se contrastó contra otra
  fuente; se registra tal como aparece y **no** se garantiza más que eso.
- **Qué se revisó:** diffs y salidas reales de comandos. No se invocaron los
  subagentes `architecture-reviewer` ni `security-reviewer` (**PENDIENTE** recomendable
  antes de cerrar D2, §20).

## 11. Aportes de Codex

Nada que registrar. Codex no intervino en este subbloque.

## 12. Operaciones manuales y de PowerShell

- El responsable **creó el PR #43 y lo mergeó** manualmente en GitHub (no hay `gh`
  instalado ni otro mecanismo autenticado en la sesión). **HECHO DEL REPOSITORIO**:
  el merge existe en `main`.
- La auditoría de PC1 (red, firewall, herramientas instaladas, arranque) fue **solo
  de lectura**; sus resultados están en el documento D2 §4. No se cambió ninguna
  configuración de Windows, red, firewall, router ni servicio.

**Hardening aplicado antes del PR** (`2e49d67`), derivado de la revisión:

- **`ErrorMessage.local_status` ELIMINADO.** Acoplaba el protocolo lógico al HTTP de
  loopback, era ambiguo para errores que no vienen de HTTP, admitía valores sin
  sentido en un error y era redundante con `ErrorCode`.
- **`NaN` e infinitos rechazados** en `Response.result`: el serializador los convertía
  en `null` en silencio y rompía el ida y vuelta.
- **`parse_message`** (unión discriminada): exige `message_type`. `register` y
  `heartbeat` tienen los mismos campos, así que un mensaje sin etiqueta era ambiguo.
- **`ALLOWED_TRANSITIONS` de solo lectura.**
- **`running` no es observable en el cable en V1** (no hay `ACK`): documentado.

## 13. Incidentes

1. **La auditoría inicial reabrió la arquitectura.** Comparó VPN, Tailscale y
   Cloudflare Tunnel como si no estuviera decidida y recomendó un túnel de terceros
   (`558407d`). Se detectó al contrastar con el responsable; se corrigió con la
   auditoría de continuidad, el ADR 0029 y la reescritura del documento D2. La
   recomendación inicial se conserva solo como histórico (documento D2 §14).
2. **No había evidencia versionada de Render ↔ PC1.** Se reportó como conflicto con la
   premisa del responsable en lugar de falsear el historial; el responsable aceptó la
   conclusión y la reafirmó como decisión actual.
3. **Hallazgos de la revisión previa al PR** (§12): corregidos antes del merge.

No hubo fallos de CI ni de Gitleaks, ni se filtraron secretos.

## 14. Git

- Trabajo de D2.1 en una rama única, `claude/d2-secure-remote-access`, creada desde
  `main` en `cc924f4`; **nunca** se commiteó directamente en `main`.
- Sin *force push*, sin *amend* y sin reescritura de historia compartida.
- Este cierre se versiona desde una rama documental aparte.

## 15. Ramas

| Rama | Papel | Fin |
|---|---|---|
| `claude/d2-secure-remote-access` | Trabajo funcional de D2.1 (4 commits) | Mergeada con el PR #43 |
| `docs/closure-d2-1-render-pc1-protocol` | Este documento de cierre | Mergeada con el PR documental (§17) |

## 16. Commits

| Commit | Mensaje | Destino |
|---|---|---|
| `558407dc792fd2b120902f163b2c70334589161a` | `docs(d2): remote access audit and architecture decision` | en `main` |
| `cd256c274e70ac6b84a6fc1ae70f1cb7e324a31d` | `docs(d2): formalize hybrid Render-PC1 architecture` | en `main` |
| `201d4588b94c8c67f8515c5be16b27672d55e983` | `feat(relay): define Render-PC1 protocol V1` | en `main` |
| `2e49d67df28f7e071ca0adc1ceb8f5c7990735fd` | `fix(relay): harden Render-PC1 protocol V1` | en `main` |
| `edf658a8c5aab7c358cf98d5370549baf0604561` | merge del PR #43 (padres `cc924f4` y `2e49d67`) | `main` |

**HECHO DEL REPOSITORIO:** los cuatro commits de D2.1 son ancestros de `main`
(`git merge-base --is-ancestor`), y el merge trae exactamente los 6 archivos de §2.

## 17. Pull requests

| PR | Estado | Detalle |
|---|---|---|
| #43 | **Mergeado** el 2026-10-05 02:48 UTC | `feat(relay): define D2 Render-PC1 architecture and protocol V1`; 4 commits, 6 archivos, +2076 / −0; base `main`; merge `edf658a8c5aab7c358cf98d5370549baf0604561` |

CI (**HECHO MEDIDO** por la API pública de GitHub, en solo lectura):

| Ejecución | Evento | HEAD | Gitleaks | Lint, types and tests |
|---|---|---|---|---|
| 37251523655 | push (rama) | `2e49d67` | SUCCESS, job 111579965025 | SUCCESS, job 111579965140 |
| 37256609169 | pull_request (#43) | `2e49d67` | SUCCESS, job 111594937785 | SUCCESS, job 111594937598 |
| 37256860353 | push (`main`, merge) | `edf658a` | SUCCESS, job 111595698931 | SUCCESS, job 111595698744 |

La ejecución 37256860353 en `main` terminó con `status = completed` y `conclusion = success`. El resultado
del CI del commit que versiona este documento y el PR documental se registran fuera
de este archivo, en el informe de la sesión, para no escribir aquí un hecho que aún
no existía al redactarlo.

## 18. Migraciones

**Nada que registrar.** No se escribió ni se aplicó ninguna migración (regla 15). No
se tocó Supabase ni Materiales.

## 19. Estado operacional final

- **Funciona (HECHO DEL REPOSITORIO):** el contrato V1 existe, es importable y está
  probado; la arquitectura híbrida está formalizada en dos ADR.
- **No existe:** transporte, relay en Render, agente en PC1, heartbeat operativo, cola,
  autenticación real del nodo, reconexión, manejo de PC1 fuera de línea, login real,
  Modo ELSA, despliegue. **No hay acceso remoto funcionando.**
- **El demo de Render sigue siendo lo que era:** una demo sintética. D2.1 no tocó
  `render.yaml` ni el servicio.
- **Resumen:** `ARQUITECTURA HÍBRIDA FORMALIZADA = SÍ` · `PROTOCOLO V1 =
  IMPLEMENTADO` · `RED = NO IMPLEMENTADA` · `RELAY = NO IMPLEMENTADO` ·
  `AGENTE PC1 = NO IMPLEMENTADO`.

## 20. Pendientes

Ninguno se cierra por asociación.

| Pendiente | Dónde / responsable |
|---|---|
| **D2.2** — relay/gateway en Render | siguiente incremento; responsable del proyecto |
| Tamaño máximo de `result` y de la solicitud completa | D2.2 |
| Tope de longitud del token, si se decide | D2.2 |
| Semántica pública adicional a `ErrorCode`, si la interfaz la necesita (campo lógico, no un código HTTP) | D2.2 |
| Lista cerrada de rutas del relay | D2.2 |
| **Transporte definitivo** (el *long polling* es solo recomendación) y su ADR | D2.2/D2.3 |
| **D2.3** — agente de PC1 | responsable del proyecto |
| **Mitigación de `.` y `..` en `domain`/`asset`**: `httpx` colapsa esos segmentos antes de enviar. El agente debe construir la ruta con código fijo, codificar cada segmento, rechazar `.`, `..` y `/`, y probarlo | D2.3 (**no es una falla abierta de D2.1**) |
| Autenticación real del nodo (hash, comparación segura, rotación, revocación) | D2.2/D2.3 |
| Heartbeat operativo, reconexión, manejo de PC1 fuera de línea | D2.2/D2.3 |
| **D2.4** — integración y endurecimiento (incluye el endurecimiento de `domain`/`asset` en el contrato y el máximo de adjuntos) | responsable del proyecto |
| Login real (hoy se pega un JWT de ~1 h) | responsable del proyecto |
| Medición real de los límites de Render (duración de petición, comportamiento del plan Free) | D2.7 |
| Ambiente de ejecución de ELSA en PC1 (`TEST` o variante) y su ADR | responsable del proyecto |
| Modo ELSA | bloque propio |
| Prueba real desde PAPELSA | D2.8 |
| Revisión con `architecture-reviewer` y `security-reviewer` | antes del cierre de D2 |
| Actualizar `PROJECT_HISTORY_AND_CURRENT_STATE.md` y `HANDOVER_AND_CONTINUITY_MAP.md` con D2.1 | responsable del proyecto |

## 21. Siguiente bloque

**D2.2 — relay/gateway en Render.** Motivo: el contrato V1 ya existe; falta el extremo
público que lo hable. **No se inicia en este cierre.** Antes de abrirlo hay que
resolver los pendientes de tamaños y de rutas, y fijar el transporte en su ADR.

---

## Criterios de cierre

| Criterio | Estado |
|---|---|
| PR #43 mergeado | Sí (`edf658a8c5aab7c358cf98d5370549baf0604561`) |
| Los 4 commits de D2.1 son ancestros de `main` | Sí |
| Los 6 archivos integrados | Sí |
| `main` local = `origin/main` | Sí en el momento de verificar |
| CI del merge en `main` | Sí: ejecución 37256860353, `completed`/`success` (§17) |
| Sin datos reales ni secretos en el diff | Sí (revisión manual; Gitleaks de CI en SUCCESS) |
| Documento de cierre versionado en `main` y CI posterior en verde | Se confirma en el commit y la ejecución que registran este cierre |

## Veredicto

**D2.1 — PROTOCOLO RENDER ↔ PC1 V1 = CERRADO**, sujeto a que el CI del commit que
versiona este documento termine en verde; ese resultado y los SHA del commit de cierre
y de su merge se registran fuera de este archivo, en el informe de la sesión.

Este cierre **no** significa acceso remoto funcionando: `RED IMPLEMENTADA = NO`,
`RELAY IMPLEMENTADO = NO`, `AGENTE PC1 IMPLEMENTADO = NO`.

**Regla de continuidad:** quien continúe D2 debe leer, en este orden,
`docs/adr/0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md`,
`docs/adr/0030-protocolo-relay-render-pc1-v1.md` y
`docs/d2-acceso-remoto-seguro-auditoria.md` (en particular §2 «Evolución de
arquitectura»), y **no** debe reabrir la arquitectura sin un ADR nuevo.
