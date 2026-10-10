# ADR 0031 — Transporte HTTPS long polling para el relay Render–PC1 (Pilot 0.1)

- Estado: **aceptado**
- Fecha de la decisión: **2026-10-10**
- Bloque: **D2**, incremento **D2.2**
- **Decide**: el transporte del relay para **Pilot 0.1**, los timeouts y límites
  de tamaño pendientes de D2.1, y las limitaciones que el piloto acepta por
  usar estado en memoria
- **No es una garantía de arquitectura definitiva.** El transporte es una
  decisión **de piloto**, con condición de reevaluación explícita (§5)
- **No reabre** [ADR 0029](0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md)
  ni [ADR 0030](0030-protocolo-relay-render-pc1-v1.md): el protocolo V1 se
  consume tal cual, sin modificarlo
- Implementación: `src/elsa/relay/{store,service,auth}.py` y
  `src/elsa/api/v1/relay.py`
- Aplica las reglas **1, 2, 6, 9, 11, 13, 14 y 21** de
  [`CLAUDE.md`](../../CLAUDE.md)

## 1. Contexto

El ADR 0029 fijó que PC1 es el nodo de ejecución y que **inicia** toda
conexión; el ADR 0030 fijó el contrato lógico y dejó el transporte abierto.
D2.2 construye la mitad pública (Render) y necesita elegir cómo viajan los
mensajes de ese contrato.

## 2. Decisión

Para Pilot 0.1 el transporte es **HTTPS long polling iniciado por PC1**:

| Operación | Ruta (`/api/v1/relay/node`) | Mensaje del protocolo |
|---|---|---|
| Anunciar sesión | `POST /register` | `Register` |
| Esperar trabajo (y señal de vida) | `POST /poll` | `Heartbeat` → `Request` \| `Cancel` \| vacío |
| Entregar resultado | `POST /result` | `Response` \| `ErrorMessage` |

Cumple los criterios de D2.1: PC1 inicia todas las conexiones, solo HTTPS
saliente, sin dependencia Python nueva (`httpx` ya está disponible para el
agente), sin puerto entrante, sin IP pública fija y sin tocar NAT ni router.
No se implementa WebSocket ni SSE.

**Autenticación del nodo**, distinta del JWT del usuario: cabecera
`X-Elsa-Node-Token` con un secreto aleatorio de alta entropía. Render guarda
solo su SHA-256 (actual y, opcionalmente, anterior para rotar sin corte) y
compara con `hmac.compare_digest`. El secreto nunca viaja en query, body ni
cookie, y nunca se registra. No se usa `service_role`.

**No hay proxy genérico.** Ninguna ruta acepta url, host, método, cabeceras,
ruta, comando, archivo ni SQL: solo mensajes V1 con la operación
`assistant.ask`.

## 3. Semántica operativa

- **Fail-closed.** `ELSA_RELAY_ENABLED=false` por defecto; las rutas ni
  siquiera se montan. Habilitado con configuración incompleta, la aplicación
  no arranca.
- **Solicitudes `queued` independientes de la sesión.** El `Request`
  protocolario se materializa **al despacharlo** con la sesión activa; un
  `REGISTER` nuevo conserva las `queued` vigentes y jamás reutiliza el
  `node_session_id` antiguo.
- **At-most-once.** Una solicitud entregada por poll nunca vuelve a la cola.
  Un `REGISTER` nuevo, o la caída del nodo por TTL, hace fallar las
  solicitudes en vuelo con `LOCAL_UNAVAILABLE`; no hay replay.
- **Caída por TTL sin otra operación.** Cada `submit` espera con *deadlines*
  asíncronos propios (vencimiento de la solicitud y vigencia del nodo): no hay
  scheduler permanente ni dependencia de que llegue otra llamada.
- **El TTL vencido retira la sesión.** Pasado `NODE_TTL` sin señal, la
  sesión queda **retirada** (stale) y lo despachado a ella falla. Ni `poll`, ni
  `result`, ni `register` con ese mismo `node_session_id` la reviven (409
  `stale_session`): el vencimiento se evalúa **antes** de refrescar
  `last_seen`. La reconexión exige un `REGISTER` con un `node_session_id`
  **nuevo**.
- **Un `node_session_id` es de un solo uso** dentro de la vida del proceso:
  una vez vencido o reemplazado no puede volver a registrarse. Solo se admite
  el reintento del `REGISTER` de la sesión **vigente** y viva. Este historial
  vive en memoria y se pierde con el reinicio de Render, igual que el resto
  del estado (§6); crece un UUID por sesión registrada.
- **`queued` puede sobrevivir y esperar un `REGISTER` nuevo** hasta su propio
  TTL (120 s por defecto): no hay espera infinita. Se materializa entonces con
  la sesión nueva, nunca con la caída.
- **`dispatched` nunca se reproduce.** Lo entregado a una sesión que vence o
  se reemplaza falla con `LOCAL_UNAVAILABLE`; no llega a la sesión siguiente.
- **Respuestas rechazadas** (HTTP 409, sin efecto): sesión desconocida,
  vencida o antigua, `request_id` desconocido, duplicado o expirado.
- **Cancelación best effort.** `queued` se retira; `dispatched` genera un
  `Cancel` entregado en el siguiente poll, sin ACK.
- **Nodo OFFLINE.** `submit` falla de inmediato con `LOCAL_UNAVAILABLE`. No
  hay cola de horas, ni IA cloud, ni consulta a Materiales desde Render.
- **Cuerpo HTTP acotado por lectura en streaming**: nunca se carga un body
  arbitrario para medirlo después.

## 4. Valores del piloto

Son **valores de partida, configurables, no un SLA**. Las mediciones reales de
Render se harán después.

| Parámetro | Valor | Razón |
|---|---|---|
| Long poll | 25 s | Por debajo de los timeouts de inactividad habituales de proxy (30–60 s) |
| TTL del nodo | 45 s | Poll + 20 s: tolera un poll lento o un reintento; siempre `long poll < TTL` |
| TTL de la solicitud | 120 s | Techo de una inferencia local |
| Máximo pendiente (cola + en vuelo) | 16 | `llm_concurrency = 1`: la cola útil es corta |

**Límites de tamaño** (cierran los pendientes de D2.1 sobre `Response.result`
y la solicitud completa; son constantes de código, no variables de entorno):

| Límite | Valor | Razón |
|---|---|---|
| `user_access_token` | ≤ 4096 caracteres | Un JWT mide ~1–2 KB |
| `REQUEST` en el cable | ≤ 16 KiB | `question` ≤ 2000 chars + token + adjuntos; acota también su número, que el protocolo no limita |
| `RESPONSE` en el cable | ≤ 256 KiB | `result` es opaco; holgado para listas de componentes y modos de falla |
| `ERROR` en el cable | ≤ 2 KiB | `detail` ≤ 200 caracteres |

Estimados por estructura del contrato, no con datos SAP reales.

## 5. Condición de reevaluación

Este ADR **debe reabrirse con uno nuevo** si las mediciones reales de Render
muestran que el long polling no es viable, por ejemplo: la plataforma corta
conexiones inactivas por debajo de los 25 s del poll, el coste de peticiones
repetidas es inaceptable, o la latencia de entrega de `Cancel`/`Request` no
sirve al flujo del ingeniero. El protocolo V1 está escrito para sobrevivir a
ese cambio de transporte sin romperse.

## 6. Limitaciones aceptadas del piloto

- **Estado solo en memoria del proceso.** Un reinicio de Render pierde la
  sesión del nodo y toda solicitud en vuelo; PC1 debe volver a registrarse y el
  usuario debe reintentar manualmente. No hay base de datos, Redis, SQLite ni
  disco.
- **Una única instancia lógica.** Pilot 0.1 requiere **un solo worker**: el
  escalado horizontal y los múltiples workers con memoria independiente **no
  están soportados**, y `WEB_CONCURRENCY > 1` tampoco (uvicorn lo toma como
  número de workers por defecto y cada uno tendría su propio store; `render.yaml`
  no lo fija y no debe fijarse). No se añade sincronización distribuida.
- **Retención del token del usuario.** `submit` conserva una sola referencia
  (la de la solicitud pendiente) y la suelta al despachar; el llamador conserva
  la suya hasta que la libere. Python no garantiza borrado seguro de memoria: el
  objetivo es minimizar referencias y tiempo de retención.
- **Un único nodo configurado.**
- **Sin límite de intentos de autenticación fallidos.** El secreto de alta
  entropía hace inviable la fuerza bruta; queda anotado, no resuelto.
- **Requisito para D2.3:** el agente debe seguir haciendo poll **mientras
  ejecuta** una solicitud, porque `poll` y `result` son la señal de vida y una
  inferencia larga sin poll haría caer al nodo por TTL.
- Una respuesta tardía de una solicitud ya fallada, expirada o cancelada se
  rechaza; el trabajo del nodo se descarta.

## 7. Consecuencias

- D2.4 consume `RelayService.submit(params, user_access_token)` y **no conoce**
  `node_session_id`.
- No se expone endpoint público de estado; ONLINE/OFFLINE es interno hasta que
  D2.4 decida qué ve el usuario.
- El despliegue real, los secretos reales en Render y el login de operación
  normal quedan fuera de D2.2.
