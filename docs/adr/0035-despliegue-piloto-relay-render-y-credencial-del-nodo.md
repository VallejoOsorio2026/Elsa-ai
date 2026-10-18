# ADR 0035 — Despliegue piloto del relay en Render y credencial del nodo

- Estado: **aceptado**
- Fecha de la decisión: **2026-10-18**
- Bloque: **D2**, incremento **D2.6** (habilitación controlada del entorno real Render ↔ PC1)
- **Decide**: dónde y cómo se despliega por primera vez el relay de D2.2 en Render real,
  cómo se garantiza la instancia única que exige el relay en memoria, cómo se genera y custodia
  la credencial del nodo sin que nadie más que PC1 vea el secreto, qué se considera evidencia
  de que el nodo está en línea y **hasta dónde llega D2.6**
- **No reabre** [ADR 0029](0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md)–
  [ADR 0034](0034-modo-elsa-operativo-pc1-pilot-0-1.md). Protocolo V1, relay, agente, ruta de
  `assistant.ask` y Modo ELSA se consumen tal cual
- Implementación: **ninguna línea de código**. Configuración del servicio en el panel de Render
  y procedimiento en [`render-pc1-conexion-real-runbook.md`](../render-pc1-conexion-real-runbook.md)
- Aplica las reglas **1, 2, 5, 9, 10, 11, 12, 13, 15, 21 y 22** de
  [`CLAUDE.md`](../../CLAUDE.md)

## 1. Contexto

D2.1–D2.5 dejaron la cadena Render ↔ PC1 implementada y probada **en memoria y en local**:
relay (D2.2), agente outbound-only (D2.3), modo RELAY de `assistant.ask` (D2.4) y Modo ELSA
(D2.5). Nada se ha desplegado ni conectado por red real.

Hechos del repositorio que condicionan la decisión:

- `render.yaml` declara un único servicio, `elsa-demo`: la **demostración** del Bloque 3, en
  `ELSA_ENV=DEV`, con identidades **fake**, siembra sintética y el contrato documentado de que
  «no contiene ningún secreto» (`tests/test_render_blueprint.py` lo fija). Se despliega desde
  `main` tras cada push.
- Su start command no fija `--workers`. uvicorn usa `WEB_CONCURRENCY` cuando no recibe el flag
  (`uvicorn/config.py`); con más de un worker cada proceso tendría **su propio** relay en
  memoria y el nodo quedaría registrado en uno solo.
- El relay guarda su estado en memoria (ADR 0031): un reinicio pierde la sesión del nodo, y solo
  se admite una instancia.
- La expiración del nodo es **perezosa**: la sesión deja de estar en línea por política tras
  `ELSA_RELAY_NODE_TTL_SECONDS`, pero el evento `node_offline` solo se materializa en la
  siguiente operación que ejecuta la expiración (register, poll, result o submit). `/health/ready`
  no expone el estado del nodo.
- En DEV con identidad fake, `/api/v1/session/context` publica los tokens deterministas del
  adaptador fake **a propósito** (son de demostración). No existe todavía un login operativo
  real: la interfaz admite pegar un JWT de Materiales para probar.

## 2. Decisión: servicio Render dedicado, manual y de un solo worker

El relay piloto se despliega en un **servicio web de Render nuevo y dedicado**, creado y
configurado **en el panel**, separado de `elsa-demo`:

| Aspecto | Decisión |
|---|---|
| Servicio | Nuevo, solo para el piloto del relay. `elsa-demo`, `render.yaml` y `tests/test_render_blueprint.py` **no se modifican** |
| Origen | Repositorio del proyecto, rama `main` |
| Despliegue | **Manual**. Auto-deploy **deshabilitado**: un merge a `main` no debe reiniciar el relay sin que nadie lo decida |
| Instancias | **Una**. Sin escalado horizontal ni autoescalado configurado |
| Build | El mismo que la demo: `pip install uv && uv sync --frozen --no-dev` |
| Start | El de la demo **más `--workers 1`**: `.venv/bin/uvicorn elsa.main:create_app --factory --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*' --workers 1` |
| Health check | `/api/v1/health/live` (liveness, como la demo) |

`--workers 1` explícito tiene prioridad sobre `WEB_CONCURRENCY`: la instancia única no depende
de lo que la plataforma decida poner en el entorno. Ni el plan contratado ni la configuración
del panel se dan por garantía: **la garantía es la configuración observada más los logs del
proceso** (§5).

Alternativa descartada: reutilizar `elsa-demo`. Rompería su contrato «sin secretos», cada push a
`main` reiniciaría el relay y mezclaría la demostración pública con el piloto.

## 3. Configuración de D2.6: relay encendido, asistente en LOCAL

Durante D2.6 el servicio piloto corre con:

```text
ELSA_ENV=DEV
ELSA_RELAY_ENABLED=true
ELSA_ASSISTANT_EXECUTION_MODE=local
ELSA_AUTH_PROVIDER=fake          (default; no se declara)
ELSA_WEB_UI_ENABLED=false
ELSA_DEMO_SEED                   (sin declarar: false)
```

`local` con el relay habilitado es una combinación válida (ADR 0033 §2): las rutas de nodo
existen y el nodo puede conectarse, pero **ninguna pregunta se reenvía a PC1**. Es lo único que
hace aceptable la identidad fake en este servicio.

**Regla: RELAY con identidad fake NO está autorizado para enviar `assistant.ask` a PC1.** Con
`ELSA_AUTH_PROVIDER=fake`, cualquiera puede obtener un token fake válido desde
`/session/context`; en modo `relay` ese token llegaría a PC1. Antes de poner
`ELSA_ASSISTANT_EXECUTION_MODE=relay` en cualquier servicio, Render debe validar identidad real
(`ELSA_AUTH_PROVIDER=supabase` con la configuración de Materiales) y PC1 debe validarla también.
Eso pertenece a un bloque posterior, con su propio ADR.

## 4. Credencial del nodo: token efímero por sesión

- **Generación:** solo en PC1, en una única ventana de PowerShell: 32 bytes de un generador
  criptográfico del sistema (`System.Security.Cryptography.RandomNumberGenerator`) codificados
  en base64url sin relleno (43 caracteres ASCII, 256 bits). Cumple el mínimo de 32 caracteres
  del agente.
- **Hash:** SHA-256 en hexadecimal minúscula de los bytes UTF-8 del token, la misma función que
  usa el relay (`elsa.relay.auth.hash_node_token`). Es lo único que sale de PC1.
- **Render:** el hash se introduce como variable secreta `ELSA_RELAY_NODE_TOKEN_SHA256` en el
  panel del servicio piloto. Nunca en `render.yaml`.
- **PC1:** el token crudo vive en una variable de esa ventana y pasa al agente por el entorno del
  proceso (`ELSA_AGENT_NODE_TOKEN`), que es lo que el Modo ELSA ya acepta (ADR 0034 §10). **No se
  imprime**, no pasa por el portapapeles, no va en argv, `.env`, `state.json`, logs, chat,
  documentos ni capturas.
- **Fin de la sesión:** se borra la variable y se cierra la ventana; el token deja de existir.
- **Rotación:** cada sesión de prueba genera un token nuevo y sustituye el hash actual.
  `ELSA_RELAY_NODE_TOKEN_SHA256_PREVIOUS` no se usa en D2.6: el token anterior ya no existe.
- **Revocación:** cambiar o borrar el hash, o poner `ELSA_RELAY_ENABLED=false`, y redesplegar.
  El agente recibe 401 o 404, termina con `EXIT_FATAL` y el Modo ELSA se detiene entero.

Ningún asistente, documento ni persona distinta del operador de PC1 conoce el token.

## 5. Gates y evidencia

**Antes de conectar PC1** (sin token y sin JWT):

- deploy correcto desde el SHA de `main` registrado;
- `GET /api/v1/health/live` → 200;
- `GET /api/v1/health/ready` → 200 con `environment: DEV`; `degraded` es aceptable si solo
  degradan dependencias no críticas (contrato de `/health/ready`);
- `POST /api/v1/relay/node/register` **sin** cabecera de nodo → **401**: la ruta existe y la
  autenticación falla cerrada (un 404 significa relay apagado);
- logs de arranque: exactamente un `Started server process [N]`, ningún
  `Started parent process` ni `Waiting for child process` (supervisor multiproceso de uvicorn), y
  la línea `application configured` con `relay_enabled: true` y
  `assistant_execution_mode: local`;
- desde PC1, una petición HTTPS **sin proxy** con la misma pila del agente (httpx con
  `trust_env=False`). Si solo funciona a través de un proxy corporativo, **D2.6 se bloquea**:
  `trust_env` no se cambia en este bloque.

Si cualquiera falla, PC1 no se conecta.

**NODE ONLINE** se declara solo con:

- `node_registered` en los logs de Render y en `agent.log`, con el mismo `node_id`;
- polls `POST /api/v1/relay/node/poll` con estado 200 **sostenidos** y la sesión siempre dentro
  del TTL;
- **20 minutos** de ventana de estabilidad sin `register_failed`, `session_stale`, 401, 409 ni
  5xx. Es una ventana de estabilidad, no una comprobación de las reglas comerciales de Render.

El estado del Modo ELSA sigue diciendo «Relay Render: conectividad NO VERIFICADA» (D2.5 no
cambia): la evidencia de ONLINE es la correlación de los logs de Render y del agente.

**OFFLINE y reconexión:** tras un STOP, la sesión queda expirada por política después del TTL;
el evento se observa en la siguiente operación (el REGISTER del siguiente START), como
`node_offline` de la sesión anterior seguido de `node_registered` de una nueva. Un START antes del
TTL produce `node_session_replaced`. En ambos casos hay un `node_session_id` nuevo y no hay
replay.

**Restart de Render:** se prueba en una sesión posterior de D2.6, **nunca** durante la primera
conexión. Fallos transitorios, backoff y `stale_session` durante el reinicio son el
comportamiento diseñado; el veredicto se da sobre la recuperación completa.

## 6. Límite de D2.6

D2.6 termina en **NODE ONLINE**. Queda fuera:

- `assistant.ask` real a través del relay, login real, JWT de usuario y datos reales de planta;
- la prueba desde PAPELSA y la red corporativa;
- Phi;
- exponer el estado del nodo en Render, un control de arranque que rechace varios workers, una
  lista blanca del entorno del agente y la rotación con hash anterior (endurecimiento).

## 7. Observabilidad

Permitido: SHA del deploy, estado del servicio, respuestas de health, eventos del relay
(`node_registered`, `node_offline`, `node_session_replaced`, `stale_session`), ruta, estado y
duración de las peticiones del relay, líneas de arranque de uvicorn, la salida de
`Get-ElsaModeStatus` y los eventos de `supervisor.log` y `agent.log`.

Prohibido: cabeceras completas, cuerpos, volcados de entorno, la pantalla de variables del
servicio, tokens, hashes, JWT, preguntas, inventario y cualquier dato de planta. La evidencia que
sale de una sesión son extractos filtrados por nombre de evento y conteos.

## 8. Rollback

En cualquier fallo: STOP del Modo ELSA en PC1, borrar el token de la ventana y poner
`ELSA_RELAY_ENABLED=false` (o suspender el servicio piloto) y redesplegar. El sistema vuelve a
«PC1 detenido, Render sin nodo». Nunca se cambia el firewall, se mata un proceso ajeno ni se
borran datos.

## 9. Consecuencias

- Código nuevo: 0. Dependencias: 0. Base de datos, migraciones y Redis: no.
- La configuración del servicio piloto vive en el panel, no en el repositorio. Este ADR y el
  runbook son su definición reproducible; cualquier cambio de configuración se registra en el
  documento de cierre de la sesión que lo haga.
- `elsa-demo` sigue siendo la demostración, intacta.

## 10. Limitaciones y riesgos residuales

- **Expiración perezosa:** el instante exacto de OFFLINE no es observable en Render sin tráfico.
- **Plan y plataforma:** suspensión por inactividad, reinicios y límites de uso del plan
  contratado se verifican el día de la prueba; no se dan por contractuales. Un reinicio pierde la
  sesión del nodo (comportamiento conocido del relay en memoria).
- **Token en el entorno de la ventana y del agente:** legible por procesos del mismo usuario en
  PC1, como en D2.5.
- **DEV en el servicio piloto:** `/docs` y `/openapi.json` quedan públicos (solo describen la API,
  que es pública en el repositorio). La identidad fake es inocua mientras el asistente esté en
  `local`.
- **Proxy:** el agente ignora el proxy del sistema; una red que lo exija bloquea D2.6.
