# Cierre formal — D2.6: Conexión real Render ↔ PC1 (NODE ONLINE)

- **Fecha:** 2026-10-18 (UTC). Primera conexión real a las 20:19 UTC; restart de Render a las
  21:41 UTC.
- **Estado:** la **ejecución técnica de D2.6 está completada y aceptada**. Este documento es
  su **cierre documental**; el **cierre formal** queda efectivo cuando el PR que lo contiene
  esté mergeado en `main` y el CI de `main` resulte verde (ver «Regla de continuidad»).
- **Qué cierra:** el subbloque **D2.6** del bloque D2 (acceso remoto seguro a ELSA). D2.6 lleva
  por primera vez la arquitectura a red real: un servicio Render **dedicado** con el relay de
  D2.2, un **único worker**, y el agente de PC1 (D2.3) arrancado por el Modo ELSA (D2.5)
  conectándose **solo con conexiones salientes**. Termina en **NODE ONLINE**, que es su límite
  (ADR 0035 §6).
- **Qué NO cierra:** **no cierra D2.** No se ejecutó `assistant.ask` real a través del relay, no
  hubo login real ni JWT de usuario, no se consultaron datos de planta ni SAP, no se probó desde
  PAPELSA ni desde la red corporativa y no participó Phi. **No hay consulta remota funcional
  validada.** Ver §20.
- **Prerrequisitos:** D2.1–D2.5 cerrados formalmente
  ([`d2-5-modo-elsa-operativo-pc1-cierre.md`](d2-5-modo-elsa-operativo-pc1-cierre.md)) y
  preparación de D2.6 integrada en `main` (PR #54, merge
  `2054d260cda4e559d20f17452f27280f580d10d7`): ADR 0035 y runbook de conexión real.
- **Decisión técnica:** [ADR 0035](adr/0035-despliegue-piloto-relay-render-y-credencial-del-nodo.md).
  Procedimiento: [`render-pc1-conexion-real-runbook.md`](render-pc1-conexion-real-runbook.md).
- **Identificador del bloque:** el nombre de este archivo lleva `d2-6` para que **no pueda
  leerse como el cierre de D2**.
- **Procedencia de la evidencia:** la ejecución física (panel de Render, ventanas de PowerShell
  de PC1, logs de Render y de PC1) la realizó y verificó **el operador / responsable del
  proyecto**. Los datos de este documento son los que él aportó, registrados como **HECHO
  MEDIDO por el operador**. Esta sesión no ejecutó ninguna operación contra Render.
- **Marcas de afirmación** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**,
  **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Sanitización:** este documento no contiene tokens, hashes, JWT, credenciales, capturas del
  panel de variables, direcciones IP observadas en los logs, la URL del servicio piloto ni datos
  de planta (reglas 11 y 12). `node_id` y `node_session_id` son identificadores operativos no
  secretos (ADR 0035 §7).

---

## 1. Objetivo

Pasar de «arquitectura probada en memoria y en local» a «Render real + Modo ELSA real en PC1 +
primera conexión outbound real PC1 → Render», y demostrar con evidencia:

```text
REGISTER autenticado → polls sostenidos → NODE ONLINE (≥ 20 min)
→ STOP → expiración por TTL (OFFLINE perezoso) → reconexión con sesión nueva
→ restart real de Render → recuperación automática del agente
→ estado seguro final (relay OFF, sin credenciales)
```

sin abrir puertos en PC1, sin firewall, sin VPN ni túnel, y sin persistir el token del nodo.

## 2. Alcance

**Ejecutado:**

- Servicio Render piloto dedicado, distinto de `elsa-demo` (ADR 0035 §2), con el relay en
  memoria y el asistente en `local`.
- Gate de Render previo a PC1.
- Conectividad HTTPS directa PC1 → Render con la pila del agente (`httpx`, `trust_env=False`).
- Primera sesión: REGISTER autenticado, polls sostenidos, NODE ONLINE, ventana de estabilidad,
  STOP, OFFLINE por TTL y reconexión con sesión nueva.
- Segunda sesión, con **otra credencial**: restart real del servicio Render con el agente
  conectado y recuperación automática.
- Gestión efímera del token, controles de no persistencia, retirada de credenciales y vuelta a
  relay OFF tras cada sesión.

**Fuera de alcance (explícito):**

- `assistant.ask` real a través del relay; modo `relay` en Render.
- Login real, JWT de usuario, identidad Supabase en Render.
- Datos de planta, SAP, Materiales reales en una consulta remota.
- PAPELSA, red corporativa, proxy.
- Phi/llama.cpp.
- Cambios de código, de `render.yaml`, de protocolo, relay, agente o Modo ELSA.
- Base de datos, migraciones, Redis, persistencia del relay.

## 3. Estado inicial

- **HECHO DEL REPOSITORIO:** `main` en `2054d260cda4e559d20f17452f27280f580d10d7` (merge del PR
  #54, preparación de D2.6), con CI de `main` en verde (run 39156509918: «Lint, types and
  tests» y gitleaks SUCCESS). D2.1–D2.5 cerrados formalmente.
- `elsa-demo` es la demostración del Bloque 3 (`render.yaml`) y **no** forma parte de D2.6.
- Ningún servicio Render ejecutaba el relay; PC1 nunca se había conectado a Render.

## 4. Trabajo realizado

En orden (**HECHO MEDIDO por el operador**, salvo indicación):

### 4.1 Gate de Render previo a PC1

Servicio piloto dedicado creado y desplegado según el runbook §2–§3, y gate superado **antes**
de conectar PC1. Evidencia saneada conservada por el operador:

| Comprobación | Resultado observado |
|---|---|
| Servicio piloto | `elsa-relay-pilot`, distinto de `elsa-demo` |
| Commit desplegado | `2054d26` (merge del PR #54) |
| Deploy | `Live` / `SUCCESS` |
| Un solo worker (logs de arranque) | `Started server process`: **1** · `Started parent process`: **0** · `Waiting for child process`: **0** |
| Ejemplo de la línea observada | `INFO: Started server process [58]` |
| Relay OFF: `POST /api/v1/relay/node/register` | `HTTP 404 Not Found` (las rutas de nodo no existen) |
| Relay ON: `register` **sin credencial** | `HTTP 401 Unauthorized` (ruta montada, autenticación fail-closed) |
| Auditoría en Render | Evento `auth_failed`, con el **mismo `request_id`** que la respuesta 401 |
| Tras el gate: relay de nuevo OFF, `register` | `HTTP 404 Not Found` |

El gate se superó con el relay apagado (línea base) y con el relay encendido. La coincidencia
del `request_id` correlaciona la petición de prueba con su evento de auditoría.

### 4.2 Conectividad HTTPS directa PC1 → Render (antes del agente)

Prueba con `httpx` y `trust_env=False` (la misma pila y la misma política del agente):

```text
/api/v1/health/live  -> HTTP 200
/api/v1/health/ready -> HTTP 200
ready.status      = degraded
ready.environment = DEV
```

`degraded` es aceptable para este piloto DEV (runbook §3, contrato de `/health/ready`). La red
de PC1 llegó a Render **sin proxy**.

### 4.3 Primera conexión real (sesión 1)

Arranque real del Modo ELSA en PC1:

```text
ELSA LOCAL: LISTA CON DEGRADACIONES NO CRÍTICAS
Agente PC1: proceso activo
Relay Render: conectividad NO VERIFICADA
```

La última línea es el comportamiento esperado del Modo ELSA de D2.5, que no verifica la
conexión: **no invalida D2.6**. La evidencia de conexión es la correlación de logs.

PC1 (`agent.log`):

```text
2026-10-18T20:19:06.917657+00:00  agent_started    node_id=pc1-pilot
2026-10-18T20:19:07.602555+00:00  node_registered  node_id=pc1-pilot  node_session_id=f43fe1c9-228d-414a-b45c-100069117ca0
```

Render:

```text
2026-10-18T20:19:07.284372+00:00  node_registered  node_id=pc1-pilot  node_session_id=f43fe1c9-228d-414a-b45c-100069117ca0
```

El **mismo `node_session_id`** en Render y en PC1 es la evidencia de **registro cruzado**
PC1 ↔ Render: el REGISTER autenticado llegó al relay real y el agente recibió su confirmación.

### 4.4 NODE ONLINE y ventana de estabilidad

Render registró polls continuos:

```text
POST /api/v1/relay/node/poll   HTTP 200   duración de cada long poll ≈ 25 s
primeros polls: 20:19 UTC
polls sostenidos hasta al menos: 20:41:24 UTC
```

- Desde `agent_started` (20:19:06 UTC) hasta el último poll documentado (20:41:24 UTC) hay
  **22 min 17 s** (cálculo sobre las marcas anteriores), por encima de la ventana objetivo de
  **20 minutos** (ADR 0035 §5).
- La duración de ≈ 25 s por poll coincide con `ELSA_RELAY_LONG_POLL_SECONDS` por defecto (25 s):
  polls vacíos que se mantienen abiertos el tiempo de long poll y se renuevan.
- **No** se afirma disponibilidad productiva ni SLA: es una ventana de estabilidad.
- Se observaron polls HTTP 200 continuos durante más de 20 minutos, superando la ventana
  objetivo. No se observaron anomalías relevantes en la evidencia revisada durante esa ventana.
  No se realizó una búsqueda negativa exhaustiva sobre la totalidad de los logs, por lo que
  **no** se afirma la ausencia absoluta de cualquier evento no mostrado en los extractos
  conservados.

### 4.5 STOP, expiración por TTL y reconexión (sesión 1)

STOP controlado con Ctrl+C:

```text
Parada solicitada con Ctrl+C.
Deteniendo Modo ELSA...
Modo ELSA detenido.
```

Espera de **95 segundos**, por encima del mínimo de 90 s del runbook §8.1 (TTL 45 s + long poll
25 s + margen). Después, START.

Render:

```text
2026-10-18T20:48:02.089614+00:00  event=node_offline     node_id=pc1-pilot  node_session_id=f43fe1c9-228d-414a-b45c-100069117ca0
2026-10-18T20:48:02.089927+00:00  event=node_registered  node_id=pc1-pilot  node_session_id=ff68fc7c-3f1c-4d7b-9497-b7c2d1438f3d
```

seguidos de múltiples `POST /api/v1/relay/node/poll` con HTTP 200.

**Cómo leerlo.** La expiración del relay es **perezosa** (ADR 0035 §1 y §5): la sesión anterior
quedó expirada por política al superar el TTL, pero el evento `node_offline` solo se materializa
en la siguiente operación que obliga al relay a evaluar la expiración, aquí el REGISTER del
nuevo START. Por eso `node_offline` (sesión anterior) y `node_registered` (sesión nueva) aparecen
con 0,3 ms de diferencia. **No** se afirma que Render marcara OFFLINE en el instante exacto del
TTL.

La sesión nueva tiene un `node_session_id` distinto: no se reutilizó ninguna sesión y no hubo
replay.

### 4.6 Limpieza de la sesión 1

Antes de retirar el token, en la ventana del token (runbook §9):

```text
Select-String  %LOCALAPPDATA%\ELSA\mode\*.*  y  %LOCALAPPDATA%\ELSA\mode\logs\*.log   -> False
Select-String  .env                                                                -> False
```

El token no apareció en los archivos inspeccionados ni en `.env`. Después:

```text
Remove-Item Env:\ELSA_AGENT_NODE_TOKEN
Test-Path   Env:\ELSA_AGENT_NODE_TOKEN   -> False
```

Render se devolvió a relay OFF. Comprobación final:

```text
POST /api/v1/relay/node/register   -> HTTP 404
```

El `404` indica que las rutas de nodo ya no existen (relay apagado). Repositorio al final:
`## main...origin/main`, sin cambios.

### 4.7 Restart real de Render (sesión 2, credencial nueva)

Sesión separada con una **credencial nueva**, distinta de la de la sesión 1. Su valor no se
registra en ningún sitio. Formas observadas:

```text
node_id = pc1-pilot
token   = 43 caracteres
hash    = 64 caracteres
```

El token se cargó **solo** en `ELSA_AGENT_NODE_TOKEN` (entorno de la ventana); el hash, **solo** en
la configuración del servicio Render durante la sesión.

Antes del restart, PC1:

```text
2026-10-18T21:07:58.511145+00:00  agent_started
2026-10-18T21:07:58.911354+00:00  node_registered  node_session_id=85ffa121-f2aa-4413-a09e-216e17b4aef8
```

Desde el panel de Render: **Manual Deploy → Restart service**. No se desplegó un commit nuevo
ni se limpió la caché de build.

PC1 (`agent.log`) durante el restart:

```text
2026-10-18T21:41:38.981108+00:00  poll_failed      http_status=502  node_session_id=85ffa121-f2aa-4413-a09e-216e17b4aef8
2026-10-18T21:41:40.921261+00:00  session_stale
2026-10-18T21:41:40.924982+00:00  session_retired  cancelled=0
2026-10-18T21:41:42.835145+00:00  node_registered  node_session_id=3068927f-192e-40e7-97bd-07484ca599fa
```

Render:

```text
21:41:36.544035  POST /api/v1/relay/node/poll       200   duration_ms=25002.82
21:41:40.467220  POST /api/v1/relay/node/poll       409   duration_ms=644.08
21:41:42.391293  POST /api/v1/relay/node/register   200   duration_ms=1.56
21:42:07.580083  POST /api/v1/relay/node/poll       200   duration_ms=25002.52
```

**Interpretación (comportamiento diseñado, runbook §11 y ADR 0035 §5):**

- El **`502`** fue **transitorio**, mientras el proceso de Render se reiniciaba.
- El **`409 stale_session`** era **esperado**: el relay reiniciado perdió en memoria la sesión
  anterior y rechazó el poll de una sesión que ya no conocía.
- El agente **retiró** la sesión obsoleta (`session_retired`, sin trabajo que cancelar) y
  **registró automáticamente** una sesión nueva.
- Volvió a polls **200** sin ninguna intervención manual en PC1.

El `409` **no** es un fallo funcional: es la señal con la que el relay obliga al nodo a
registrarse de nuevo. El veredicto del restart se da sobre la **recuperación completa**.

Entre el `node_registered` previo (21:07:58 UTC) y el primer error del restart (21:41:38 UTC)
el nodo estuvo conectado **33 min 40 s** (cálculo sobre las marcas de PC1).

### 4.8 Limpieza de la sesión 2

```text
Parada solicitada con Ctrl+C.
Deteniendo Modo ELSA...
Modo ELSA detenido.
```

```text
Select-String (estado y logs del Modo ELSA)  -> False
Select-String (.env)                         -> False
Test-Path Env:\ELSA_AGENT_NODE_TOKEN         -> False   (tras Remove-Item)
```

En Render: `ELSA_RELAY_ENABLED=false`, y se retiraron `ELSA_RELAY_NODE_ID` y
`ELSA_RELAY_NODE_TOKEN_SHA256`.

**Una comprobación intermedia devolvió `HTTP 401`** en `register` sin credencial: el relay
**todavía estaba activo** en ese instante. Se revisó y corrigió el estado de Render y se repitió
la prueba. Resultado final:

```text
POST /api/v1/relay/node/register   -> HTTP 404
```

El estado seguro final quedó **verificado** con el `404`, no supuesto (§13, incidente 2).

## 5. Decisiones

**DECISIÓN TOMADA** (responsable, al aprobar el microplan y ADR 0035):

| # | Decisión |
|---|---|
| D1 | Servicio Render **dedicado** al piloto; `elsa-demo` y `render.yaml` intactos |
| D2 | Token **efímero por sesión**, generado en PC1; solo el hash llega a Render |
| D3 | D2.6 termina en **NODE ONLINE**; `assistant.ask` real diferido |
| D4 | Ventana de estabilidad de **20 minutos**; restart solo en una sesión posterior a la primera conexión |
| D5 | ADR 0035 con la regla **RELAY con identidad fake NO está autorizado para enviar `assistant.ask` a PC1** |

Durante la ejecución no se tomó ninguna decisión arquitectónica nueva.

## 6. Pruebas

**HECHO MEDIDO por el operador** (red real, PC1 real, Render real):

| Prueba | Resultado |
|---|---|
| Gate Render previo | PASS (§4.1: un solo worker; relay OFF → 404; relay ON sin credencial → 401 con `auth_failed` correlacionado; vuelta a OFF → 404) |
| Conectividad HTTPS directa PC1 → Render (`trust_env=False`) | PASS (`live` 200, `ready` 200 `degraded` DEV) |
| REGISTER autenticado | PASS (`node_registered` en Render y PC1, mismo `node_session_id`) |
| Polling continuo 200 | PASS |
| Ventana ≥ 20 min | PASS (≥ 22 min 17 s) |
| STOP controlado | PASS |
| OFFLINE por TTL (perezoso) | PASS (`node_offline` de la sesión anterior en el siguiente REGISTER) |
| Reconexión con sesión nueva | PASS |
| Restart de Render | PASS (502 y 409 transitorios; recuperación completa) |
| Recuperación automática del agente | PASS (sin intervención en PC1) |
| Polling restaurado tras el restart | PASS |
| No persistencia del token (archivos inspeccionados y `.env`) | PASS (`False` en las dos sesiones) |
| Retirada del token del entorno | PASS (`Test-Path` → `False` en las dos sesiones) |
| Render final relay OFF; `register` → 404 | PASS |

**No se ejecutó:** `assistant.ask`, ningún JWT, ninguna consulta a Materiales ni a SAP, ninguna
prueba desde PAPELSA. Esta sesión documental no ejecutó pruebas contra Render.

## 7. Comandos relevantes

Los del runbook ([`render-pc1-conexion-real-runbook.md`](render-pc1-conexion-real-runbook.md)):
probes con `httpx` y `trust_env=False` (§3–§4.1), generación del token y del hash en una sola
ventana (§4.2), `.\scripts\Start-ElsaMode.ps1` (§5), Ctrl+C / `Stop-ElsaMode.ps1` (§8), y las
comprobaciones `Select-String -Quiet` + `Remove-Item Env:\ELSA_AGENT_NODE_TOKEN` (§9). Ninguno
contiene un valor secreto literal.

## 8. Resultados

Las salidas reales aportadas están en §4.2–§4.8, tal como las registró el operador (extractos de
`agent.log`, de los logs de Render y de la consola del Modo ELSA). Se reproducen sin modificar
salvo el formato en columnas.

## 9. Métricas

**HECHO MEDIDO por el operador** (marcas de tiempo de los logs) y cálculo directo sobre ellas.
Son **intervalos observados**, no SLA ni tiempos absolutos de indisponibilidad.

| Métrica | Valor | Base |
|---|---|---|
| Ventana de estabilidad, sesión 1 | ≥ 22 min 17 s | `agent_started` 20:19:06 → último poll documentado 20:41:24 (PC1 y Render) |
| Duración de un long poll vacío | ≈ 25 000 ms | `duration_ms` de los polls 200 en Render |
| Espera tras STOP antes de reconectar | 95 s | Operador |
| Separación `node_offline` → `node_registered` | ≈ 0,3 ms | Render, misma operación de REGISTER |
| Conexión estable antes del restart, sesión 2 | 33 min 40 s | PC1: `node_registered` 21:07:58 → `poll_failed` 21:41:38 |
| Último poll 200 completado → REGISTER nuevo completado | ≈ 5,85 s | Render: 21:41:36.544 → 21:41:42.391 (mismo reloj) |
| Primer `poll_failed` → nuevo `node_registered` | ≈ 3,85 s | PC1: 21:41:38.981 → 21:41:42.835 (mismo reloj) |
| `register` tras el restart | 1,56 ms | `duration_ms` en Render |
| `poll` rechazado con 409 | 644,08 ms | `duration_ms` en Render |

Cada intervalo se calcula dentro de **un mismo reloj** (Render o PC1); no se comparan marcas de
relojes distintos.

**Lectura correcta del poll de 21:42:07.580 con `duration_ms≈25002`:** es un long poll normal que
**empezó** hacia 21:41:42, justo después del nuevo registro, y terminó al vencer su espera. **No**
significa 25 s adicionales de caída.

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO / DEL PROCESO.** Claude Code (modelo Claude Opus 5.5):

- redactó el microplan de D2.6 y, tras su aprobación, ADR 0035, el runbook de conexión real, el
  perfil «Render Relay Pilot» de `docs/environment-variables.md` y la fila D2.6 de
  `docs/architecture.md` (PR #54);
- comprobó, sin ejecutarlos, la sintaxis de los fragmentos del runbook y la equivalencia del
  procedimiento de hash con el relay usando valores sintéticos fijos;
- redactó este documento a partir de la evidencia aportada por el operador.

La **ejecución física** de D2.6 (panel de Render, PC1, logs) la realizó el operador. No se
dispone en esta sesión de un identificador verificable de las sesiones en que se ejecutó; no se
inventa ninguno.

- **Identificador de sesión (preparación y este cierre):** el directorio local de sesión que
  aparece en las rutas de trabajo es `29b70ef1-9764-436a-a361-eee9acaab3f2`. No se contrastó con
  otra fuente; se registra tal como aparece.

## 11. Aportes de Codex

Nada que registrar: Codex no participó en D2.6.

## 12. Operaciones manuales y de PowerShell

Todas las hizo el operador:

- Panel de Render: creación y configuración del servicio piloto dedicado, deploys manuales,
  activación y desactivación del relay, configuración y retirada del hash y del `node_id`, y
  **Manual Deploy → Restart service** en la sesión 2.
- PC1, PowerShell: generación del token y del hash en una sola ventana por sesión (dos sesiones,
  dos credenciales distintas), Modo ELSA START/STOP, comprobaciones `Select-String -Quiet`,
  `Remove-Item Env:\ELSA_AGENT_NODE_TOKEN` y `Test-Path`.
- Lectura de logs de Render y de `agent.log`; extractos filtrados por evento.
- No se abrió ningún puerto, no se tocó el firewall, no hubo VPN ni túnel, no se usó un proxy y
  no se ejecutó nada como administrador.

## 13. Incidentes

| # | Incidente | Qué se hizo | Estado |
|---|---|---|---|
| 1 | Durante el restart: `502` en un poll y `409 stale_session` en el siguiente | Ninguna acción: es la ruta diseñada; el agente se recuperó solo | Esperado, no bloqueante |
| 2 | Al volver al estado seguro en la sesión 2, una comprobación intermedia de `register` devolvió **`401`**: el relay seguía activo | Se revisó y corrigió el estado de Render y se repitió la prueba: **`404`** | Resuelto; estado seguro verificado |
| 3 | `Set-Clipboard -Value ""` falló con `ArgumentNullException` («El valor no puede ser nulo») en esa versión de PowerShell | El portapapeles se sobrescribió con un valor inocuo (`LIMPIO`). No afectó al agente ni a ELSA | Observación operativa no bloqueante |
| 4 | La primera versión de este documento no incluía la evidencia del gate previo | Incorporada en §4.1 con los datos saneados conservados por el operador | Resuelto |
| 5 | `docs/architecture.md` decía que D2.6 estaba «preparado, no ejecutado» | Fila D2.6 actualizada en este mismo PR, con autorización expresa del responsable | Resuelto |

## 14. Git

- Este cierre **crea** `docs/d2-6-conexion-real-render-pc1-cierre.md` y, con autorización
  expresa del responsable, **modifica** en `docs/architecture.md` solo la fila D2.6 y la frase
  sobre el estado del acceso remoto, en la rama `claude/d2-6-cierre-documental`, creada desde
  `main` (`2054d26`).
- Ningún archivo de código, test, `render.yaml` ni otro documento cambia.
- La ejecución de D2.6 no cambió el repositorio: al final de la sesión 1, `## main...origin/main`
  sin cambios (**HECHO MEDIDO por el operador**).

## 15. Ramas

| Rama | Uso | Estado |
|---|---|---|
| `claude/d2-6-render-pc1-live-readiness` | Preparación de D2.6 (ADR 0035, runbook, variables, arquitectura) | Mergeada vía PR #54; **no eliminada** todavía |
| `claude/d2-6-cierre-documental` | Este documento | Creada desde `main` (`2054d26`); su PR y su merge los registra GitHub |

## 16. Commits

| Commit | Mensaje |
|---|---|
| `c72a2e8` | `docs(adr): add ADR 0035 for the pilot relay deployment and node credential` |
| `514687e` | `docs(runbook): add the Render to PC1 real connection runbook` |
| `2c31ff0` | `docs(env): add the Render relay pilot profile` |
| `c7a9668e8a56a00986e61a2e0ae740db32b16662` | `docs(architecture): record D2.6 as prepared, not executed` |
| `2054d260cda4e559d20f17452f27280f580d10d7` | Merge del PR #54 en `main` |

La ejecución real no produjo commits (no hubo cambios de código ni de configuración versionada).

## 17. Pull requests

| PR | Estado | Detalle |
|---|---|---|
| #54 | **Mergeado** el 2026-10-18 18:57:06 UTC | `docs(project): prepare D2.6 Render-PC1 live connection`; 4 archivos; head `c7a9668`; merge `2054d26`; CI de `main` run 39156509918 en verde |
| Este cierre | Por abrir / revisar | Rama `claude/d2-6-cierre-documental` → `main` |

## 18. Migraciones

Ninguna. Base de datos nueva: NO. Migraciones: NO. Esquema: NO. Redis: NO. Supabase: no se tocó.
Persistencia del relay: NO (sigue en memoria; el restart lo demostró).

## 19. Estado operacional final

**Estado seguro al terminar (HECHO MEDIDO por el operador):**

```text
Render (servicio piloto): Live, relay OFF,
                          ELSA_RELAY_NODE_ID y ELSA_RELAY_NODE_TOKEN_SHA256 retirados
POST /api/v1/relay/node/register (sin credenciales) -> HTTP 404
PC1: Modo ELSA detenido; ELSA_AGENT_NODE_TOKEN ausente del entorno
Token de cada sesión: no encontrado en .env, estado ni logs inspeccionados;
                      retirado del entorno; no se reutilizará
```

**Qué queda demostrado:** el transporte real Render ↔ PC1 de Pilot 0.1 funciona: registro
autenticado, long polling sostenido, expiración por TTL, reconexión con sesión nueva y
recuperación automática tras un restart de Render, con PC1 **solo saliente**.

**Qué no está demostrado:** ninguna consulta remota funcional (`assistant.ask`), ningún usuario
real, ningún dato de planta por el relay, nada desde PAPELSA.

**Invariantes que se mantienen:**

- Render es intermediario público: no aloja el modelo, ni inventario SAP real, ni el
  conocimiento local.
- PC1 conserva la ejecución local e inicia todas las conexiones; sin puerto público, sin port
  forwarding, sin regla entrante nueva, sin túnel ni VPN.
- **RELAY con identidad fake NO está autorizado para enviar `assistant.ask` a PC1.**

**Limitaciones:**

| # | Limitación |
|---|---|
| 1 | La expiración es perezosa: el instante exacto de OFFLINE no es observable en Render sin tráfico |
| 2 | El relay vive en memoria: un restart pierde la sesión (demostrado y recuperado) |
| 3 | El Modo ELSA sigue mostrando «conectividad NO VERIFICADA»: la evidencia de conexión es la correlación de logs |
| 4 | Token en el entorno de la ventana y del agente durante la sesión: legible por procesos del mismo usuario |
| 5 | Comportamiento del plan de Render (suspensión, reinicios, límites) no evaluado como contrato |
| 6 | Servicio piloto en DEV con identidad fake: inocuo solo mientras el asistente esté en `local` |
| 7 | Sin borrado seguro de memoria garantizado: se retiraron las referencias controladas del token y se eliminó del entorno del proceso; no se afirma más |
| 8 | Configuración del servicio piloto en el panel, no en el repositorio (ADR 0035 §9) |

## 20. Pendientes

Ninguno se cierra por asociación con D2.6.

| # | Pendiente | Responsable / bloque |
|---|---|---|
| 1 | Primera consulta remota funcional (`assistant.ask` por el relay) con login real, identidad Supabase en Render y en PC1, y su propio ADR | Bloque posterior |
| 2 | Qué sirve Render con el resto de la API en modo RELAY (pendiente heredado de D2.4) | Bloque posterior, con ADR |
| 3 | Prueba externa desde PAPELSA y red corporativa (proxy, `trust_env`) | Bloque posterior |
| 4 | Endurecimiento: exponer el estado del nodo en Render, rechazar varios workers al arrancar, lista blanca del entorno del agente, rotación con hash anterior | Bloque posterior |
| 5 | Eliminar las ramas `claude/d2-6-render-pc1-live-readiness` y `claude/d2-6-cierre-documental` tras el merge de este documento y el CI final de `main` | Responsable |
| 6 | Phi en `assistant.ask`, si algún día se decide | Decisión futura con ADR |

## 21. Siguiente bloque

La **primera consulta remota funcional** (pendiente 1), solo después de que este documento esté
integrado en `main` con CI verde y con autorización explícita del responsable (regla 20). D2.6
deja el transporte real demostrado y el servicio piloto en estado seguro; **no** deja ninguna
consulta remota habilitada.

---

## Criterios de cierre

| Criterio | Estado |
|---|---|
| Gate Render previo | PASS (§4.1) |
| Conectividad HTTPS directa PC1 → Render sin proxy | PASS |
| REGISTER autenticado con registro cruzado (mismo `node_session_id`) | PASS |
| NODE ONLINE | PASS |
| Estabilidad ≥ 20 min | PASS (≥ 22 min 17 s) |
| STOP controlado | PASS |
| OFFLINE por TTL (perezoso, materializado en el siguiente REGISTER) | PASS |
| Reconexión con sesión nueva, sin replay | PASS |
| Restart de Render | PASS |
| Recuperación automática del agente | PASS |
| Polling restaurado | PASS |
| No persistencia del token | PASS |
| Retirada de credenciales (entorno de PC1 y configuración de Render) | PASS |
| Render final relay OFF; `register` sin credenciales → 404 | PASS |
| `assistant.ask` | NO ejecutado |
| PC1 expuesto públicamente | NO |
| Código, tests o `render.yaml` modificados | NO |
| `docs/architecture.md` coherente con D2.6 | Cumplido (fila D2.6 actualizada en este PR) |

## Regla de continuidad

Este documento es el **cierre documental** de D2.6. El **cierre formal** queda efectivo
**cuando el PR que lo contiene esté mergeado en `main` y el CI de `main` resulte verde**. Su
propio PR y su merge los registran Git y GitHub. Este documento **no se auto-referencia** con
un SHA propio: hacerlo obligaría a otro cambio solo para anotarlo. Mientras no esté integrado
en `main`, D2.6 **no** está cerrado formalmente en el repositorio principal.

## Veredicto

- **Ejecución técnica de D2.6: COMPLETADA Y ACEPTADA**, con la evidencia de §4 y los
  criterios de cierre en PASS.
- **Este documento es el cierre documental de D2.6.**
- **D2.6 — CONEXIÓN REAL RENDER ↔ PC1 (NODE ONLINE): cierre formal efectivo cuando este PR
  esté mergeado en `main` y el CI de `main` resulte verde.** Hasta entonces, D2.6 no está
  cerrado formalmente en el repositorio principal.

```text
PRIMERA CONEXIÓN REAL PC1 → RENDER:  SÍ
NODE ONLINE:                         SÍ (≥ 20 min)
OFFLINE POR TTL Y RECONEXIÓN:        SÍ
RESTART RENDER CON RECUPERACIÓN:     SÍ
TOKEN PERSISTIDO:                    NO
RENDER FINAL:                        relay OFF, register -> 404
ASSISTANT.ASK REAL:                  NO (bloque posterior)
PAPELSA:                             NO (bloque posterior)
PUERTO PÚBLICO PC1:                  NO
FIREWALL NUEVO:                      NO
DEPENDENCIAS NUEVAS:                 0
```

**D2 sigue abierto**: el transporte real está demostrado, pero **no hay consulta remota
funcional**. Los pendientes de §20 siguen abiertos y no se cierran por asociación.
