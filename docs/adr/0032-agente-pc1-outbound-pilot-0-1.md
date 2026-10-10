# ADR 0032 — Agente PC1 outbound-only para el relay Render–PC1 (Pilot 0.1)

- Estado: **aceptado**
- Fecha de la decisión: **2026-10-10**
- Bloque: **D2**, incremento **D2.3**
- **Decide**: cómo se comporta la mitad local del relay —el agente de PC1—:
  conexión, credenciales, sesiones, reconexión, concurrencia, entrega de
  resultados, cancelación, expiración y límites del piloto
- **No reabre** [ADR 0029](0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md),
  [ADR 0030](0030-protocolo-relay-render-pc1-v1.md) ni
  [ADR 0031](0031-transporte-https-long-polling-relay-render-pc1-pilot-0-1.md):
  el protocolo V1 y el transporte se consumen tal cual, sin modificarlos
- Implementación: `src/elsa/agent/{config,relay_client,local_client,runner,__main__}.py`
- Aplica las reglas **1, 2, 3, 6, 9, 10, 11, 14, 21, 22 y 23** de
  [`CLAUDE.md`](../../CLAUDE.md)

## 1. Contexto

D2.2 construyó el relay de Render: guarda solicitudes en memoria y las entrega
por *long polling* a un nodo autenticado. Falta el nodo: un proceso en PC1 que
inicie todas las conexiones, ejecute `assistant.ask` contra la ELSA local y
devuelva el resultado, sin abrir ningún puerto ni aceptar tráfico entrante.

ADR 0031 §6 dejó un requisito explícito: el agente debe seguir haciendo poll
**mientras ejecuta**, porque el poll es la señal de vida y una ejecución larga
sin poll haría caer al nodo por TTL. Pero cada poll puede entregar otro
`Request`, y el protocolo no tiene `ACK` ni forma de «devolver» una solicitud
despachada.

## 2. Decisión

### 2.1 Outbound-only

El agente es un proceso aparte (`uv run python -m elsa.agent`) que **solo
abre conexiones salientes**: HTTPS hacia el relay y HTTP hacia la ELSA local
en loopback. No escucha en ningún socket, no necesita puerto público, regla de
firewall, VPN ni túnel. Un test de frontera impide que el paquete importe
servidores, `subprocess`, FastAPI, la API o los adaptadores de ELSA.

### 2.2 ELSA solo en loopback

La URL local se configura (`ELSA_AGENT_LOCAL_BASE_URL`, por defecto
`http://127.0.0.1:8000`) y se valida al arrancar: esquema `http`, anfitrión
**IP literal de loopback** (127.0.0.0/8 o `::1`), sin credenciales, ruta,
query ni fragmento. Se rechaza `localhost` (depende de la resolución de
nombres) y cualquier IP de red o nombre. Render **nunca** aporta host, puerto,
URL, método, cabeceras ni ruta.

La única llamada local es `POST /api/v1/assistant/{domain}/{asset}/ask`,
construida por código fijo. Mitigación obligatoria de ADR 0030, consecuencia 6:

- se rechaza (`INVALID_REQUEST`, sin llamada local) un `domain` o `asset` que,
  en crudo, recortado o tras decodificar porcentajes, sea `.` o `..`, contenga
  `/` o `\`, o contenga caracteres de control;
- cada valor se codifica como **un único segmento** (`quote(valor, safe="")`);
- se comprueba que la ruta que `httpx` va a enviar es exactamente la
  construida: si algo la normalizara, no se llama.

No hay expresión regular de charset: un activo con espacios, acentos, `?`, `#`
o `%` viaja codificado y ELSA decide si existe.

### 2.3 Separación de credenciales

| Credencial | Origen | Uso único | Nunca |
|---|---|---|---|
| Token del nodo | **Solo** la variable de entorno del proceso `ELSA_AGENT_NODE_TOKEN` (`SecretStr`) | Cabecera `X-Elsa-Node-Token` hacia Render | En `.env` u otro archivo (el agente **no arranca** si lo encuentra en el archivo de configuración), URL, body, logs, ni hacia ELSA local |
| Token del usuario | Cada `Request` V1 (`SecretStr`) | `Authorization: Bearer` hacia ELSA local, que es quien lo valida (ADR 0002) | Hacia Render, en disco, en logs |

Son dos clientes HTTP distintos: el del relay lleva la cabecera del nodo; el
local no tiene cabeceras por defecto. Ambos con `follow_redirects=False` (una
redirección se llevaría la cabecera del nodo) y `trust_env=False` (un proxy de
entorno no intercepta el tráfico).

### 2.4 Sesiones y reconexión

- Cada arranque genera un `node_session_id` (UUID) nuevo, nunca persistido.
- Un `REGISTER` sin respuesta se reintenta **con el mismo id**: el relay lo
  admite como refresco mientras la sesión esté vigente.
- `409 stale_session` (TTL vencido, reemplazo o reinicio de Render) → se
  cancela todo el trabajo de la sesión vieja **sin enviar su resultado** (el
  relay ya lo falló), se olvidan los ids vistos y se registra una sesión con un
  id **nuevo**. **No hay replay**: ningún `Request` anterior se reejecuta ni se
  reenvía, y un id retirado no se reutiliza.
- Fallo de red, timeout, 5xx o 429 → espera exponencial (1 s, ×2, techo 30 s,
  con jitter) y mismo id. Nunca hay reintento sin espera.
- 401/403 (credencial del nodo), 404 (relay deshabilitado o URL errónea) y
  413/422 en register/poll (desajuste de protocolo o configuración) son
  **fatales**: el proceso termina con código 2. No hay bucle de reintentos
  contra un fallo de configuración.

### 2.5 Poll durante la ejecución y concurrencia acotada

- **Un único poll en vuelo**, en una tarea propia que nunca espera a que
  termine una ejecución: la señal de vida se mantiene y los `Cancel` llegan
  aunque la ejecución esté ocupada.
- Ejecución local con `asyncio.Semaphore(ELSA_AGENT_MAX_CONCURRENCY)`, por
  defecto **1** (alineado con `llm_concurrency = 1`).
- Admisión: como mucho `concurrency + ELSA_AGENT_MAX_QUEUED` trabajos vivos
  (por defecto 1 + 4). Cada trabajo admitido es **una** tarea que ejecuta y
  después entrega su resultado; el número de tareas está acotado por la
  admisión.
- Un `Request` que llega con la capacidad llena se responde
  `LOCAL_UNAVAILABLE` (`agent:busy`), igual que los rechazos inmediatos
  (expirado al llegar, ruta insegura). Esas respuestas **no crean tareas**: van
  a una cola acotada que atiende **un único** trabajador de respuestas; si la
  cola está llena, la respuesta se descarta (y se registra) y el relay vence
  la solicitud por su TTL.
- Un poll que vuelve vacío (o con un mensaje descartado) antes de un mínimo
  de tiempo espera hasta ese mínimo: no hay *busy loop* aunque el relay
  conteste de inmediato.
- Un `request_id` ya visto en la sesión **se ignora sin responder**: enviar
  `DUPLICATE_REQUEST` haría fallar en el relay el original, que puede seguir
  ejecutándose (ADR 0030 §16: «rechazará o reconocerá»). El registro de ids
  vistos está acotado.

### 2.6 Entrega del resultado sin reejecución

El resultado (`Response` o `ErrorMessage`) **se calcula una sola vez** y se
conserva serializado solo hasta terminar su entrega. `assistant.ask` **jamás
se reejecuta**.

- Envío inicial + **como mucho 3 reintentos** (0,5 s, 1 s, 2 s): un máximo de
  **4 transmisiones del mismo cuerpo**, y ninguna después de `expires_at`.
- Se reintenta solo ante fallo de transporte, timeout, 5xx o 429. Ahí cae el
  **ACK perdido**: Render aceptó pero la respuesta HTTP no llegó; el
  reintento recibe `409 request_not_pending` y la entrega termina. Ese 409 es
  ambiguo a propósito (aceptado antes, o ya expirado/cancelado) y en ambos
  casos es seguro detenerse.
- `409 stale_session` → se descarta y se renueva la sesión; 401/403 → fatal;
  413/422 → se descarta y se registra.
- El agente serializa el JSON él mismo (UTF-8 sin escapar, separadores
  compactos) y comprueba los límites de ADR 0031 §4 **antes** de enviar: un
  resultado que no cabe se sustituye por `LOCAL_ERROR`
  (`local:response_too_large`) en lugar de provocar un 413 que dejaría la
  solicitud en vuelo hasta su TTL.

### 2.7 Cancelación best effort

| Estado local | Efecto |
|---|---|
| Esperando turno | se retira **sin ejecutar** |
| Ejecutando | se cancela la tarea; `httpx` cierra la conexión loopback |
| Entregando | se cancela la entrega |
| Desconocido o terminado | se ignora |

No se envía `CANCELLED`: el relay ya cerró la solicitud. **Cerrar la conexión
no garantiza** que ELSA, Materiales o un futuro Phi/llama.cpp detengan el
trabajo ya iniciado: el servidor puede terminar lo que empezó aunque el
cliente se haya ido.

### 2.8 Expiración y timeouts

- Antes de ejecutar: si `expires_at − ahora − 2 s` (margen de entrega) no es
  positivo, se responde `TIMEOUT` sin llamar a ELSA.
- La llamada local, lectura incluida, tiene un plazo de
  `min(ELSA_AGENT_LOCAL_TIMEOUT_SECONDS, tiempo restante)` medido con el reloj
  **monótono**: nunca se extiende más allá de `expires_at`.
- El poll usa un timeout de lectura (`ELSA_AGENT_POLL_TIMEOUT_SECONDS`, 35 s)
  mayor que el long poll del relay (25 s).

### 2.9 Conversión de resultados locales

| Resultado local | Mensaje |
|---|---|
| 200 con objeto JSON finito y dentro del límite | `Response(result=…)` |
| 200 ilegible, no objeto, con NaN/Inf, o demasiado grande | `LOCAL_ERROR` |
| 400, 413, 422 y 404 (activo inexistente) | `INVALID_REQUEST` |
| 401 | `UNAUTHORIZED` |
| 403 | `FORBIDDEN` |
| 429, 503, conexión rechazada | `LOCAL_UNAVAILABLE` |
| timeout | `TIMEOUT` |
| 500, otros 5xx, 3xx, otros 4xx, fallo de transporte o error interno | `LOCAL_ERROR` |

El `detail` es siempre un texto fijo del agente (`local:…` / `agent:…`); de
la respuesta de ELSA solo se copia el `error.code` si está en una lista
blanca. Nunca el cuerpo, una traza ni el texto de una excepción.
`PROTOCOL_ERROR` y `DUPLICATE_REQUEST` no se emiten en V1.

### 2.10 Logs

Logger `elsa.agent`, salida JSON. Solo: evento, `node_session_id`,
`request_id`, código de error, estado HTTP, intento y duración. Nunca tokens,
cabeceras, pregunta, adjuntos, resultado, `detail` ni cuerpos del cable.
`httpx` y `httpcore` se fijan en WARNING.

## 3. Limitaciones aceptadas del piloto

- **Request perdido en la respuesta del poll.** Sin `ACK`, si la respuesta
  HTTP de un poll que traía un `Request` se pierde, el relay lo da por
  despachado y el agente nunca lo ve: el usuario espera hasta `expires_at`.
  Corregirlo exige una versión nueva del protocolo.
- **Desfase de reloj** entre PC1 y Render: `expires_at` es del reloj de
  Render. No hay tolerancia de desfase (falla cerrado); el agente registra
  `request_expired_on_arrival`. PC1 debe sincronizar la hora.
- **CANCEL no detiene trabajo ya iniciado** en el servidor local (§2.7).
- **Estado solo en memoria del proceso**: un reinicio del agente pierde lo
  que estuviera en curso; el relay lo falla por TTL.
- **Python no garantiza borrado seguro de memoria**: se minimizan las
  referencias al token del usuario y el tiempo que se retienen.
- **No se probó contra Render real**: los cortes de proxy de la plataforma se
  miden después (condición de reevaluación de ADR 0031 §5).
- Sin despedida al terminar: la sesión cae en Render por TTL.

## 4. Consecuencias

- El agente es **la única pieza** que habla con Render desde PC1 y **solo**
  sabe ejecutar `assistant.ask`: no es un proxy genérico.
- La autoridad sobre el usuario sigue siendo ELSA local; el agente no
  interpreta el JWT.
- La conexión real Render ↔ PC1, el despliegue y la integración con el
  navegador quedan fuera de D2.3.
