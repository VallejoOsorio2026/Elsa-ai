# ADR 0033 — Modo de ejecución de `assistant.ask`: LOCAL o RELAY

- Estado: **aceptado**
- Fecha de la decisión: **2026-10-18**
- Bloque: **D2**, incremento **D2.4** (integración usuario ↔ relay ↔ agente)
- **Decide**: cómo la misma API pública `POST /api/v1/assistant/{domain}/{asset}/ask`
  se ejecuta en la propia ELSA (LOCAL) o se encamina a PC1 por el relay (RELAY);
  qué valida Render y qué valida PC1; qué error ve el usuario; cómo se evita la
  recursión y cómo se propaga la cancelación
- **No reabre** [ADR 0029](0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md),
  [ADR 0030](0030-protocolo-relay-render-pc1-v1.md),
  [ADR 0031](0031-transporte-https-long-polling-relay-render-pc1-pilot-0-1.md) ni
  [ADR 0032](0032-agente-pc1-outbound-pilot-0-1.md): el protocolo V1, el relay y el
  agente se consumen tal cual. La única adición al agente es una cabecera fija (§7)
- Implementación: `src/elsa/config.py`, `src/elsa/api/deps.py`,
  `src/elsa/api/v1/assistant_relay.py`, `src/elsa/main.py`,
  `src/elsa/agent/local_client.py`
- Aplica las reglas **1, 2, 3, 5, 9, 10, 11, 14, 21, 22 y 23** de
  [`CLAUDE.md`](../../CLAUDE.md)

## 1. Contexto

D2.2 dejó `RelayService.submit(AskParams, user_access_token)` y D2.3 un agente que
lo atiende desde PC1. Faltaba que el endpoint público usara ese camino. Hoy el
endpoint ejecuta la lógica de ELSA en el mismo proceso: autentica, consulta el
perfil en Materiales, lee cuenta y permisos de ELSA, resuelve el activo en el
almacén de conocimiento, busca en el BOM y, si hay código exacto, consulta
Materiales.

ADR 0029 §4 dice que Render **no** es ejecutor de las decisiones de ELSA
(permisos, recuperación, generación), ni repositorio de conocimiento, ni
consulta Materiales en sustitución de PC1. ADR 0030 §11: el token del usuario
viaja opaco y **ELSA lo valida, no el relay**.

## 2. Decisión: dos modos explícitos

`ELSA_ASSISTANT_EXECUTION_MODE` = `local` | `relay`. **Default `local`.**

- Valores exactos, sin mayúsculas ni espacios: `RELAY`, `Relay` o ` relay`
  hacen fallar el arranque con `ConfigurationError`.
- `relay` exige `ELSA_RELAY_ENABLED=true`; si no, la aplicación **no arranca**.
- `local` con `ELSA_RELAY_ENABLED=true` es válido (pruebas, administración del
  nodo). No hay cambio automático de modo en ningún caso.

El modo se decide **una vez**, en `create_app`, montando uno de dos routers con
la misma ruta y los mismos modelos (`AskRequest`, `AskResponse`):

```text
mode=local ─▶ elsa.api.v1.assistant          (sin cambios: comportamiento histórico)
mode=relay ─▶ elsa.api.v1.assistant_relay    (RelayService.submit, en proceso)
```

Se descartó un `AssistantExecutor` con implementaciones local y relay: las
dependencias de FastAPI son estáticas y la ruta local **declara** el activo, el
conocimiento y Materiales. Para no ejecutarlas en RELAY habría que mover la
resolución del activo dentro del ejecutor y rehacer el orden «autorizar antes de
recuperar» que hoy garantiza la sub-dependencia de `resolve_asset`. Con dos
routers la ruta RELAY **no tiene** en su firma ni conocimiento, ni Materiales,
ni permisos: ejecutar localmente en Render es imposible por construcción, no por
un `if`. El navegador no cambia: llama a la misma ruta y recibe el mismo modelo.

**Sin fallback.** Si el relay falla, PC1 está fuera de línea o la respuesta no
sirve, el usuario recibe un error explícito. Render nunca ejecuta la búsqueda,
nunca consulta Materiales y nunca responde con otra IA.

## 3. Qué valida Render y qué valida PC1

**Render (RELAY)** autentica: `Authorization: Bearer`, verificación del JWT
contra Supabase Auth de Materiales y control de abuso (`admitted_identity`). Un
token ausente o inválido se rechaza **antes** de `submit`.

**PC1 (LOCAL)** autoriza, con el mismo token: perfil activo en Materiales,
cuenta y permisos de ELSA, alcance, activo, conocimiento y Materiales. **Todo
403 de permisos procede de PC1.**

La doble verificación del JWT es intencional en el piloto: Render no confía en
nada que no haya verificado y PC1 no confía en Render. No se sustituye por
`service_role`, por la credencial del nodo ni por una identidad inventada.

Render valida además la **forma** de `domain` y `asset` (la misma regla que
`normalize_scope_value`). Eso **no es autorización**: un valor
estructuralmente inválido se rechaza como `422 validation_error`, no como 403.
Cierra el pendiente de ADR 0030 §20 en el borde público, **sin tocar V1**.

**Adjuntos** (pendiente de ADR 0030 §20). Render aplica solo lo que ya declara
`AskRequest` (forma de cada declaración y longitud de la pregunta). La
validación funcional —número máximo y tope de bytes— es de ELSA local, que es
la autoritativa; su error vuelve 1:1 (§5). El tope de 16 KiB del `Request` del
relay (ADR 0031) es protección de transporte, no una regla de negocio.

## 4. Validación de la respuesta del nodo

`Response.result` es JSON opaco para el protocolo. Antes de devolverlo:
`AskResponse.model_validate(result, strict=True)` —sin coerciones: `"true"` no
es `True` ni `"9"` es `9`— y, además, `domain` y `asset` del resultado deben
coincidir con los pedidos. Si no: `503 local_node_invalid_response`, sin eco del
contenido. Se devuelve el modelo validado, nunca el dict.

**Campos extra:** se descartan, no se rechazan. Es el contrato actual de
`AskResponse` (no prohíbe extras) y no se cambia aquí: tolera un desfase de
versión entre PC1 y Render, y nada no declarado cruza, porque el modelo los
descarta al validar y `response_model` solo serializa lo declarado. Contrapartida
aceptada: una deriva de contrato pasa en silencio. `strict` funciona porque
todos los campos de `AskResponse` son tipos JSON nativos; un `datetime`, `UUID` o
`Enum` futuro obligaría a revisarlo.

## 5. Errores públicos

`RelayFailure.detail` **nunca** llega al cliente ni a los logs: solo elige una
fila de una lista blanca. Los mensajes son fijos en Render. Lo que tiene
equivalente en el modo LOCAL conserva su estado (401, 403, 404, 422, 429); los
fallos **del propio nodo** (fuera de línea, plazo, error, respuesta inválida,
cancelación) son `503` con un código distinto, como el resto de dependencias
del proyecto (en el repositorio no se usa 502 ni 504). Un `detail` desconocido
cae en la fila genérica de su `ErrorCode`. Una excepción inesperada es el `500`
genérico del proyecto y el evento `assistant_relayed` la registra como
`internal_error`, no como cancelación.

| ErrorCode | `detail` admitido | HTTP | `code` |
|---|---|---|---|
| UNAUTHORIZED | cualquiera | 401 | `unauthorized` |
| FORBIDDEN | `local:account_disabled` | 403 | `account_disabled` |
| FORBIDDEN | `local:insufficient_permissions` | 403 | `insufficient_permissions` |
| FORBIDDEN | otro | 403 | `forbidden` |
| INVALID_REQUEST | `local:asset_not_found`, `local:not_found` | 404 | `asset_not_found` |
| INVALID_REQUEST | `local:too_many_attachments` | 422 | `too_many_attachments` |
| INVALID_REQUEST | `local:attachments_too_large` | 422 | `attachments_too_large` |
| INVALID_REQUEST | otro | 422 | `validation_error` |
| LOCAL_UNAVAILABLE | `local:too_many_requests` | 429 | `too_many_requests` |
| LOCAL_UNAVAILABLE | `local:identity_provider_unavailable` | 503 | `identity_provider_unavailable` |
| LOCAL_UNAVAILABLE | `local:knowledge_store_unavailable` | 503 | `knowledge_store_unavailable` |
| LOCAL_UNAVAILABLE | otro (fuera de línea, capacidad, sesión perdida) | 503 | `local_node_unavailable` |
| TIMEOUT | cualquiera | 503 | `local_node_timeout` |
| LOCAL_ERROR, PROTOCOL_ERROR, DUPLICATE_REQUEST | cualquiera | 503 | `local_node_error` |
| CANCELLED | cualquiera | 503 | `request_cancelled` |
| respuesta incompatible con `AskResponse` | — | 503 | `local_node_invalid_response` |

## 6. Plazos y cancelación

No hay plazo nuevo. La espera pública la acota el `request_ttl_seconds` del
relay (120 s); el agente corta la llamada local antes (110 s); la caída del
nodo se detecta por su TTL (45 s). Nodo fuera de línea al enviar: fallo
inmediato, sin cola.

Con `BaseHTTPMiddleware` (Starlette 1.6) una desconexión del navegador **no**
cancela el endpoint. La ruta RELAY corre `submit` en una tarea y, a la vez,
espera `http.disconnect` en el `receive` de la petición (el cuerpo ya está
leído). Si el cliente se va primero, cancela la tarea de `submit`: eso dispara
el camino propio de D2.2 (`CANCEL` *best effort* al agente). Como máximo una
tarea de `submit` y una de vigilancia por petición; ambas se recogen en
`finally`. No es un mecanismo paralelo: es el disparador que faltaba.

## 7. Recursión imposible

1. PC1 usa el default `local`; `relay` exige relay habilitado y su credencial.
2. La ruta RELAY solo habla con el `RelayService` **del mismo proceso**: no hay
   URL de relay remoto que configurar en el servidor.
3. El agente exige `https` hacia el relay y `http` sobre IP de loopback hacia
   ELSA (ADR 0032 §2.2).
4. **Defensa estructural por petición**: el agente marca toda llamada a ELSA
   local con `X-Elsa-Relay-Hop: 1`. La ruta RELAY rechaza cualquier petición que
   la traiga (`503 local_node_unavailable`) antes de autenticar y de `submit`,
   venga de un navegador o de cualquier otro cliente. **No depende de CORS.** La
   ruta LOCAL la ignora.

Una ELSA de PC1 arrancada por error en `relay` no ejecuta nada: rechaza la
petición del agente por la cabecera, y el usuario recibe «ELSA local no
disponible».

El rechazo ocurre antes de autenticar y emite un `WARNING` (`relay_hop_rejected`)
sin datos de la petición: es la señal de una mala configuración. Un cliente
anónimo puede generar esas líneas a voluntad, igual que ya genera la línea de
acceso de cada petición; se acepta ese volumen.

## 8. Correlación y logs

El `request_id` HTTP de Render ya acompaña todo log de la petición; la ruta
RELAY asigna el `relay_request_id` antes de `submit` y emite un único evento
`assistant_relayed` con ambos, el resultado (`ok` o el `ErrorCode`), el código
público, el estado HTTP y la duración. El agente envía `X-Request-ID =
relay_request_id` a ELSA local, de modo que los logs de PC1 usan ese mismo id.
Nunca se registran pregunta, token, resultado, `detail` ni adjuntos. Si el
vigilante de desconexión falla, la espera termina igual (fail-safe) y se emite
`disconnect_watcher_failed` con el tipo de error, nunca su texto.

**Vida del token del usuario.** Render lo verifica una vez y lo entrega como
`SecretStr` a `submit`; el relay lo suelta al despachar (`scrub_token`). Mientras
dura la petición, la cadena sigue en la memoria del proceso (caché de
dependencias de FastAPI y `scope` ASGI), igual que en el modo LOCAL: Python no
permite borrarla. No se guarda ni se registra.

## Consecuencias

1. El comportamiento histórico no cambia: `local` es el default y su ruta es la
   misma de siempre.
2. Render en RELAY no necesita conocimiento, permisos ni Materiales para
   responder; sí necesita verificar el JWT.
3. Un usuario sin cuenta o sin alcance en PC1 recibe el 403 de PC1, no de Render.
4. **Capacidad compartida (riesgo residual).** El relay admite como mucho
   `ELSA_RELAY_MAX_PENDING` solicitudes vivas en total (16) y el control de abuso
   limita a cada usuario a `ELSA_RATE_LIMIT_MAX_CONCURRENT_REQUESTS` simultáneas
   (5), plaza que se conserva durante toda la espera. Render admite a toda
   identidad autenticada, tenga o no cuenta en ELSA (eso lo decide PC1): con PC1
   lento, cuatro cuentas pueden ocupar el relay y el resto recibe `503
   local_node_unavailable` hasta que venzan los plazos. Memoria y solicitudes
   siguen acotadas. Un cupo por usuario dentro del relay queda como decisión
   futura explícita; en el piloto hay un solo usuario.
5. **Solo `assistant.ask`.** Este ADR decide el modo de esa ruta. En `relay` el
   resto de la API (`/me`, `/access`, `/admin`, `/knowledge`, `/technical`,
   `/assets`, `/contributions`) y la siembra de datos demo siguen en el proceso,
   como antes. Qué debe servir Render en `relay` frente a ADR 0029 §4 es materia
   de D2.5 y de su propio ADR.
6. Reiniciar Render pierde las solicitudes en vuelo; no hay persistencia ni
   *replay* (ADR 0031). Una solicitud en cola cuando el nodo cae espera una
   sesión nueva hasta su plazo (limitación aceptada en D2.2).
7. Fuera de este ADR: despliegue real en Render, conexión real de PC1, login
   definitivo y Modo ELSA (D2.5 en adelante).
