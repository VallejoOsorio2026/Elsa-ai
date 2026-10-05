# ADR 0030 — Protocolo Relay Render–PC1 V1

- Estado: **aceptado**
- Fecha de la decisión: **2026-10-04**
- Bloque: **D2**, incremento **D2.1**
- **Decide una sola cosa**: el **contrato lógico** (mensajes, identidad,
  correlación, estados, errores y semántica de entrega) entre el relay de Render
  y el agente de PC1
- **No decide el transporte.** El *long polling* HTTPS es la recomendación de
  diseño actual (documento D2 §7.2), pero **este ADR no la fija**: el protocolo
  está escrito para sobrevivir a un cambio de transporte (por ejemplo, a
  WebSocket) sin romperse
- **No reabre** [ADR 0029](0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md),
  [ADR 0002](0002-identidad-de-materiales-autorizacion-en-backend.md) ni
  [ADR 0018](0018-runtime-llm-local-phi-4-mini-y-llama-cpp.md)
- Implementación: [`src/elsa/relay/protocol.py`](../../src/elsa/relay/protocol.py);
  pruebas: [`tests/test_relay_protocol.py`](../../tests/test_relay_protocol.py)
- Aplica las reglas **2, 3, 6, 9, 11, 14, 20, 21 y 25** de
  [`CLAUDE.md`](../../CLAUDE.md)

---

## Contexto

### 1. Contexto

ADR 0029 fijó que Render es el extremo público y PC1 el nodo de ejecución local,
con un transporte iniciado desde PC1. Antes de escribir el relay (D2.2) y el
agente (D2.3) hace falta **una única definición** de lo que se dicen, para que
cada uno no invente su propio formato.

### 2. Problema

Sin un contrato compartido, el relay y el agente divergen; peor, la forma más
fácil de comunicarlos es un *proxy HTTP genérico* (`method` + `url` + `headers` +
`body`), que convertiría el agente de PC1 en una herramienta para que Render
—o quien lo comprometa— haga peticiones arbitrarias desde la red doméstica.

---

## Decisión

### 3. Principios

El protocolo es **independiente del transporte, versionado, cerrado por
defecto, mínimo, serializable como JSON, determinista y validable**, y no
contiene lógica de red ni de negocio de ELSA.

### 4. Versión

`protocol_version = "1"`, **string**. Una versión desconocida —o un entero— se
rechaza. No hay negociación automática de versiones: falla cerrado.

### 5. Mensajes

| Mensaje | Dirección | Contenido |
|---|---|---|
| `register` | PC1 → Render | `node_id`, `node_session_id`. Sin IP, hostname, MAC, usuario, RAM, modelo ni rutas |
| `heartbeat` | PC1 → Render | `node_id`, `node_session_id`. No es telemetría |
| `request` | Render → PC1 | `request_id`, `node_id`, `node_session_id`, `operation`, `params`, `user_access_token`, `created_at`, `expires_at` |
| `response` | PC1 → Render | `request_id`, `node_id`, `node_session_id`, `result` (objeto JSON opaco) |
| `error` | PC1 → Render | `request_id` (opcional), `node_id`, `node_session_id`, `code`, `detail`, `local_status` |
| `cancel` | Render → PC1 | `request_id`, `node_id`, `node_session_id` |

No hay `ACK`: **no se demostró una invariante contractual que lo necesite** y el
HTTP/long polling futuro no debe contaminar el protocolo lógico. Si D2.2 o D2.3
descubren que hace falta, se reporta y se añade con una decisión explícita.

Todos los modelos **rechazan campos desconocidos** y son inmutables. Una
extensión exige un campo explícito o una versión nueva.

### 6. Identidad del nodo

`node_id`: **opaco, estable, no secreto**, con el formato `^[A-Za-z0-9._-]{1,64}$`.
Es una identidad nueva y propia del relay, **configurada deliberadamente**; no se
deriva del hostname, el usuario de Windows, la MAC, la IP, un correo ni un UUID de
Supabase.

### 7. Sesión / epoch del nodo

`node_session_id` (UUID), **nuevo en cada arranque o reconexión lógica** del
agente y **nunca persistido**. Sirve para distinguir una conexión antigua de una
nueva, rechazar respuestas tardías y evitar que lo de una sesión previa
contamine otra.

### 8. Correlación

`request_id` (UUID) lo asigna Render, es **inmutable y no se reutiliza**, y
correlaciona `request → response | error | cancel`. No es una secuencia
numérica.

### 9. Operaciones permitidas

Lista **cerrada** (`Operation`). En V1 solo existe `assistant.ask`: sus
parámetros son `domain`, `asset`, `question` y `attachments` (solo **metadatos**:
`filename`, `byte_size`, `content_type`; **nunca bytes**). Reconstruye
localmente `POST /api/v1/assistant/{domain}/{asset}/ask`.

El contrato **no tiene** `url`, `method`, `headers`, `query` ni `path`: **no es un
proxy genérico**, y Render no puede ordenar al nodo «haz GET/POST a cualquier
URL». Una operación nueva es un cambio de contrato explícito.

Límites alineados con el endpoint actual (un test compara ambos y falla si
divergen): `question` de 1 a 2000 caracteres; `filename` y `content_type` ≤ 255;
`byte_size` ≥ 0 y entero. `domain` y `asset` solo exigen **no vacío**:
`resolve_asset` los trata como strings de ruta (`strip().lower()`), sin charset
contractual, y este ADR **no inventa uno** (ver §21).

### 10. Autenticación del nodo

**Separada del usuario y fuera del mensaje.** La credencial permanente del nodo
no aparece en ningún modelo; pertenece al **transporte** (D2.2/D2.3: cabecera,
hash, comparación segura, rotación y revocación). Los tests verifican que ningún
modelo tiene un campo de secreto del nodo, de `service_role` ni de
`authorization`.

### 11. Autenticación del usuario

El `request` transporta, **de forma opaca**, la credencial **temporal** del
usuario (`user_access_token`) para que ELSA conserve su modelo actual de
autorización: ELSA la valida, no el relay (ADR 0002). Es un `SecretStr`:
`repr`, `str`, `model_dump()` y `model_dump_json()` la **enmascaran**.

Solo `Request.to_wire_dict()` la revela, porque es el payload de transporte.
**D2.2 y D2.3 deben usar esa representación deliberadamente y está prohibida en
logs**, trazas, métricas y mensajes de error. Nunca va en URL ni query string.

### 12. Estados (conceptuales)

Los lleva el relay; no viajan en el cable.

```text
queued ──▶ dispatched ──▶ running ──▶ completed
   │            │             ├──────▶ failed
   └────────────┴─────────────┴──────▶ expired | cancelled
```

`ALLOWED_TRANSITIONS` y `can_transition()` lo codifican. Los estados terminales
no tienen salida y **nada vuelve a `queued`**.

### 13. Errores

Códigos **cerrados**: `INVALID_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`,
`LOCAL_UNAVAILABLE`, `TIMEOUT`, `LOCAL_ERROR`, `CANCELLED`, `PROTOCOL_ERROR` y
`DUPLICATE_REQUEST`. Este último existe porque sostiene la semántica
at-most-once y es más preciso que `INVALID_REQUEST`.

`detail` es opcional, **acotado (≤ 200)** y lo sanea el productor: nada de
trazas, rutas físicas, secretos ni `repr` de excepciones. `local_status`
(100–599, opcional) conserva el estado HTTP de ELSA local para no perderlo al
mapear a un código.

### 14. Expiración

`created_at` y `expires_at`, **con zona horaria y en UTC** (offset cero, `Z` o
`+00:00`): un instante naïve **o con otro offset se rechaza**, no se normaliza en
silencio. `expires_at` debe ser posterior a `created_at`.

El protocolo **no consulta el reloj**: valida coherencia estructural. Decidir si
un mensaje ya expiró es del relay o del agente, que reciben el instante. Así las
pruebas son deterministas.

### 15. Cancelación

**Best effort.** Se correlaciona por `request_id`. Efecto por estado
(`cancel_effect`): `queued` → se puede; `dispatched` → puede intentarse;
`running` → mejor esfuerzo, sin prometer abortar lo ya iniciado; `completed` y
`failed` → demasiado tarde; `expired` y `cancelled` → no aplica.

### 16. Idempotencia y duplicados

El contrato permite **detectarlos** (`request_id`, `DUPLICATE_REQUEST`) pero **no
construye** caché ni almacén. Regla para D2.3: el agente rechazará o reconocerá
un `request_id` que **ya procesó dentro de su sesión activa**. No hay persistencia
entre reinicios.

### 17. Semántica de entrega: at-most-once

**At-most-once por `request_id` dentro de la sesión activa del nodo.** No se
promete *exactly once*: no hay infraestructura que pueda garantizarlo.

Si se pierde la conexión con una solicitud en vuelo, **no se reejecuta
automáticamente**: termina después como fallo explícito. El usuario puede
repetirla; recibirá otro `request_id`. Así una reconexión nunca duplica una
acción.

### 18. Datos sensibles

Solo el `user_access_token` es secreto y está enmascarado. No hay datos del
host, secretos del nodo, rutas ni inventario en el contrato. `result` es JSON
**contractual** (`JsonValue`): un objeto con valores JSON válidos, no cualquier
objeto Python, y el protocolo **no interpreta** su contenido (BOM, Materiales,
LLM).

### 19. Compatibilidad

V1 es **cerrado**: los campos desconocidos y las versiones desconocidas se
rechazan, así que agregar un campo opcional ya **no** es compatible hacia
atrás con un receptor V1. Toda ampliación es campo explícito versionado o V2.

### 20. Qué NO decide este ADR

- El **transporte** (long polling, WebSocket u otro) y sus plazos.
- La **autenticación del nodo** (hash, comparación, rotación, cabeceras).
- La implementación del relay y del agente.
- El **tamaño máximo** de `result` y de la solicitud completa: **PENDIENTE D2.2**.
- El **número máximo de adjuntos** y el tope de bytes totales: hoy los fija la
  configuración del endpoint, no el contrato: **PENDIENTE D2.2/D2.4**.
- El endurecimiento de `domain`/`asset`: **PENDIENTE D2.4**.
- El login definitivo y el Modo ELSA.

---

## Consecuencias

1. Hay **una sola definición** que importan el relay y el agente.
2. El agente de PC1 **no puede** actuar como proxy genérico: solo ejecuta
   `assistant.ask`.
3. Quien reciba un `request` **no puede** filtrar el token por `repr` o logs
   normales; solo lo revela la vía explícita de transporte.
4. Un cambio de transporte no obliga a cambiar el contrato.
5. `can_transition` y `cancel_effect` son puros y pequeños; **no** son una
   máquina de estados. El relay la construirá en D2.2.
6. **Obligación para D2.3:** como `domain` y `asset` no tienen charset
   contractual, el agente debe codificarlos como **un único segmento de ruta**
   (sin `/`, `..` ni reinterpretar), de modo que un valor extraño no cambie el
   endpoint al que se llama.

## Riesgos

- Hay un riesgo si los límites del endpoint cambian: el test de alineación
  falla y obliga a actualizar el contrato y este ADR.
- El tope de tamaño de solicitud y respuesta no está fijado todavía; hasta D2.2
  el contrato por sí solo no impide cuerpos grandes.
- `to_wire_dict()` es una vía deliberada de revelación del secreto; la
  disciplina de no registrarla depende de D2.2/D2.3 y de sus tests.

## Criterios para evolucionar a V2

Una V2 se justifica solo si ocurre alguno de estos casos: una segunda
operación que exija un contrato distinto; un cambio incompatible en
`AskRequest`/`AskResponse`; un transporte que requiera un mensaje nuevo
(p. ej. `ACK` demostrablemente necesario); o un cambio de la regla de
expiración. Se publica con un ADR sucesor y **sin negociación automática**.

## Ver también

- [ADR 0029](0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md)
- [`docs/d2-acceso-remoto-seguro-auditoria.md`](../d2-acceso-remoto-seguro-auditoria.md) §7
