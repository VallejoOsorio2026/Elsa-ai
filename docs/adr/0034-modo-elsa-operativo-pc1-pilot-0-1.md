# ADR 0034 — Modo ELSA operativo en PC1 (Pilot 0.1)

- Estado: **aceptado**
- Fecha de la decisión: **2026-10-18**
- Bloque: **D2**, incremento **D2.5** (Modo ELSA mínimo operativo en PC1)
- **Decide**: cómo un operador arranca, consulta y detiene el nodo PC1 (ELSA local
  más agente) con una sola operación por acción, sin conocer los procesos que hay
  debajo; qué se valida antes de arrancar; cuándo se considera lista ELSA local; de
  qué procesos es dueño el Modo ELSA y cómo se impide que queden huérfanos
- **No reabre** [ADR 0029](0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md),
  [ADR 0030](0030-protocolo-relay-render-pc1-v1.md),
  [ADR 0031](0031-transporte-https-long-polling-relay-render-pc1-pilot-0-1.md),
  [ADR 0032](0032-agente-pc1-outbound-pilot-0-1.md) ni
  [ADR 0033](0033-modo-de-ejecucion-de-assistant-ask-local-o-relay.md). El protocolo
  V1, el relay y la ruta de `assistant.ask` no cambian. La única modificación de
  código existente es que el agente atiende `SIGBREAK` como Ctrl+C (§7)
- Implementación: `src/elsa/pc1/`, `src/elsa/agent/__main__.py`,
  `scripts/Start-ElsaMode.ps1`, `scripts/Get-ElsaModeStatus.ps1`,
  `scripts/Stop-ElsaMode.ps1`
- Operación: [`docs/pc1-modo-elsa-runbook.md`](../pc1-modo-elsa-runbook.md)
- Aplica las reglas **6, 9, 10, 11, 12, 13, 14, 21, 22 y 23** de
  [`CLAUDE.md`](../../CLAUDE.md)

## 1. Contexto

Tras D2.4 existían todas las piezas de PC1, pero sueltas: ELSA se arrancaba a mano
con `uvicorn` y el agente con `python -m elsa.agent`, sin orden garantizado, sin
comprobación previa, sin forma de saber si el nodo estaba listo y sin parada
coordinada. Los scripts `Start/Stop-ElsaLlm.ps1` gestionan solo `llama-server` y
**no son** el Modo ELSA (ADR 0029, `docs/llm-runtime.md`).

Hechos del código que condicionan la decisión:

- `assistant.ask` en modo LOCAL (`src/elsa/api/v1/assistant.py`) no usa el LLM:
  `Container.require_llm()` no se llama desde la API y `GroundedGenerationService`
  solo lo usa la CLI `elsa.tools.llm_runtime`. **Phi no es requisito del nodo.**
- `/api/v1/health/ready` devuelve `degraded` siempre en la configuración actual:
  la transcripción está simulada y las dependencias planificadas figuran como
  `not_configured` (`src/elsa/core/health.py`). `degraded` no puede significar
  «ELSA no sirve».
- En Windows no hay `SIGTERM` entregable a un proceso concreto. La única señal de
  consola que un proceso puede enviar a otro de forma selectiva es
  `CTRL_BREAK_EVENT`, a un grupo de procesos creado con
  `CREATE_NEW_PROCESS_GROUP`. Uvicorn la atiende con su cierre ordenado; el agente
  de D2.3 no la atendía.

## 2. Decisión: un supervisor Python en primer plano

El Modo ELSA es **un proceso supervisor** (`python -m elsa.pc1 start`) que corre en
primer plano en una ventana de consola —la ventana «Modo ELSA»— durante toda la
vida del nodo. Arranca y vigila exactamente dos procesos hijos:

```text
supervisor (ventana Modo ELSA)
 ├── ELSA local   uvicorn elsa.main:create_app --host 127.0.0.1 --port N
 └── agente PC1   python -m elsa.agent
```

Tres operaciones, cada una con un wrapper PowerShell mínimo en `scripts/` que solo
invoca el Python del `.venv` del repositorio (sin `uv run`, para que operar el nodo
no sincronice dependencias ni toque la red):

| Operación | Wrapper | Comando subyacente |
|---|---|---|
| Iniciar | `Start-ElsaMode.ps1` | `python -m elsa.pc1 start` |
| Estado | `Get-ElsaModeStatus.ps1` | `python -m elsa.pc1 status` |
| Detener | `Stop-ElsaMode.ps1` | `python -m elsa.pc1 stop` |

Si la política de la organización bloquea los `.ps1`, se usan los comandos
subyacentes con `.venv\Scripts\python.exe`. **No se cambia ni se elude la política
de ejecución de PowerShell.**

Alternativas descartadas:

- **Supervisor en PowerShell.** El Job Object exige compilar C# con `Add-Type`, los
  tests requerirían Pester (dependencia nueva) y duplicaría las validaciones que ya
  hacen `load_settings` y `load_agent_config`.
- **Reutilizar `Start/Stop-ElsaLlm.ps1`.** Modelo desacoplado: detiene por un PID
  leído de archivo y, en la práctica, fuerza el cierre de inmediato. No hay orden
  entre componentes.
- **Procesos en segundo plano sin supervisor.** Una parada ordenada desde otro
  proceso exige compartir consola (`CTRL_BREAK_EVENT`); sin supervisor, la parada
  sería siempre forzada y la propiedad se basaría en PIDs de archivo.

## 3. Perfil PC1: siempre LOCAL, sin relay propio

El preflight falla cerrado si la configuración de ELSA no cumple:

| Variable | Valor exigido | Motivo |
|---|---|---|
| `ELSA_ASSISTANT_EXECUTION_MODE` | `local` | PC1 ejecuta; nunca reenvía (ADR 0033) |
| `ELSA_RELAY_ENABLED` | `false` | ELSA de PC1 no aloja un `RelayService`: menos superficie y refuerzo contra la recursión |
| `ELSA_DEBUG` | `false` | Regla 13 |

Además, el supervisor **fija** esos tres valores en el entorno del hijo ELSA, de
modo que lo validado es lo que se ejecuta aunque cambie el archivo entre la
validación y el arranque.

Bind y puerto:

- ELSA escucha en la constante `127.0.0.1`; no es configurable.
- El puerto sale de `ELSA_AGENT_LOCAL_BASE_URL` (única fuente). Su host debe ser
  **exactamente** `127.0.0.1` —el agente admite cualquier IP de loopback; el Modo
  ELSA no— y el puerto debe ser explícito.
- uvicorn arranca con `--no-access-log` (su línea de acceso incluye la query; ELSA
  tiene la suya sin query), `--no-proxy-headers` y
  `--timeout-graceful-shutdown 10`.

No se crea ninguna variable de entorno nueva.

## 4. Orden de arranque

```text
bloqueo de instancia única
→ limpiar state.json y stop.request residuales (con el bloqueo ya obtenido)
→ validar configuración de ELSA y del agente
→ comprobar que el puerto está libre
→ crear Job Object
→ iniciar ELSA local
→ esperar readiness (§5)
→ iniciar agente
→ periodo de gracia del agente
→ EN MARCHA
```

El agente **nunca** se inicia antes de que ELSA esté lista. Si ELSA no queda lista,
o si el agente muere durante el periodo de gracia, se deshace el arranque: se
detiene lo iniciado por ese intento y el Modo ELSA termina con un mensaje fijo.

Un `stop.request` residual de una ejecución anterior se borra al obtener el
bloqueo; **nunca** se interpreta como orden para la instancia nueva.

## 5. Readiness

Se consulta `GET http://127.0.0.1:N/api/v1/health/ready` con `http.client` (sin
proxies del entorno). El hijo ELSA debe estar vivo antes y después de la respuesta,
y el campo `environment` debe coincidir con `ELSA_ENV`:

| Respuesta | Estado mostrado | ¿Permite arrancar el agente? |
|---|---|---|
| 200, `status=ok` | **ELSA LOCAL: LISTA** | Sí |
| 200, `status=degraded` | **ELSA LOCAL: LISTA CON DEGRADACIONES NO CRÍTICAS** (solo los nombres de las dependencias, nunca su `detail`) | Sí |
| 503, otra respuesta o sin conexión | **ELSA LOCAL: NO LISTA** | No: rollback |

Readiness es un hecho **local**. Ninguna salida del Modo ELSA afirma conexión con
Render: la línea del relay es siempre «**Relay Render: conectividad NO
VERIFICADA**». La conectividad real se verifica en el bloque siguiente.

## 6. Propiedad de procesos, instancia única y huérfanos

- **La propiedad es el handle.** El supervisor solo detiene los `Popen` que él
  creó. En Windows, mientras el handle siga abierto el PID no puede reutilizarse.
- **Nunca se detiene un proceso por un PID leído de archivo.** Los PIDs de
  `state.json` son informativos. No se usa `taskkill`, ni búsqueda por nombre de
  ejecutable.
- **Job Object con `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`** (ctypes, sin
  privilegios). Si el supervisor muere —cierre de la ventana, Administrador de
  tareas—, el sistema operativo termina los hijos. Eso **no** es un cierre
  ordenado: solo garantiza que no queden huérfanos.
- **Instancia única** con un bloqueo del sistema operativo sobre
  `supervisor.lock`, retenido durante toda la vida del supervisor (`msvcrt.locking`
  sobre el primer byte en Windows; `fcntl.flock` en POSIX, solo para los tests). El
  sistema lo libera si el proceso muere, de modo que un bloqueo no puede quedar
  «stale».
- **Puerto ocupado** por un proceso no propio: el arranque falla cerrado. El
  proceso ajeno no se identifica ni se toca.

## 7. Parada

`stop` (desde otra ventana) **no mata nada**: crea `stop.request` y espera a que el
supervisor libere el bloqueo. Ctrl+C en la ventana tiene el mismo efecto.

```text
agente  → CTRL_BREAK_EVENT, espera hasta 10 s → si no sale, kill sobre su handle
ELSA    → CTRL_BREAK_EVENT, espera hasta 20 s → si no sale, kill sobre su handle
→ borrar state.json y stop.request → cerrar Job Object → liberar bloqueo
```

Los hijos se crean en su propio grupo de procesos: el Ctrl+C del operador llega
solo al supervisor, que es quien decide el orden.

El agente de D2.3 solo convertía Ctrl+C en salida ordenada. Ahora, si
`signal.SIGBREAK` existe (solo Windows), `SIGBREAK` sigue el mismo camino que
Ctrl+C: cancela la tarea principal, ejecuta los `finally` actuales y termina con
código 0. En Linux no cambia nada. No se modifican ni el runner ni el protocolo.

## 8. Fallos en ejecución: parada completa, sin reinicio automático

El Modo ELSA o está completo o no está. Si cualquiera de los dos hijos termina
mientras el nodo está en marcha, el supervisor pasa a `DEGRADADO`, detiene el otro
en orden y termina con un mensaje fijo y la ruta del log. **No hay reinicio
automático**: el agente ya reintenta por sí mismo los fallos transitorios del
relay, y un fallo fatal (credencial o protocolo rechazados) se repetiría en bucle.

Si ELSA sigue viva pero `/health/ready` pasa a 503 o deja de responder, el estado
pasa a `DEGRADADO` sin parar nada (puede recuperarse) y vuelve a `EN MARCHA` en
cuanto readiness se recupera.

## 9. Estado operativo

| Estado | Significado |
|---|---|
| `ARRANCANDO` | Supervisor vivo; arranque en curso |
| `EN MARCHA` | ELSA lista (con o sin degradaciones no críticas) y agente vivo |
| `DEGRADADO` | Se perdió una condición que permitía operar: ELSA no responde o devuelve 503, un hijo terminó y empieza la parada, o el latido del supervisor tiene más de 20 s |
| `DETENIÉNDOSE` | Parada ordenada en curso |
| `DETENIDO` | No hay supervisor (bloqueo libre) |

`status` es de solo lectura. Lee `state.json`, comprueba el bloqueo y sondea
readiness por su cuenta.

## 10. Secretos

- `ELSA_AGENT_NODE_TOKEN` solo llega desde el entorno del proceso o, si falta y hay
  consola, desde `getpass` (sin eco). Antes de pedirlo se comprueba —con la misma
  función del agente— que el token **no** está en el archivo de configuración: el
  fail-closed de D2.3 se conserva.
- El token vive en la memoria del supervisor y en el entorno del hijo agente. El
  hijo ELSA recibe una copia del entorno con la variable **eliminada
  explícitamente**.
- Nunca en argv, `.env`, `state.json` (esquema cerrado por lista blanca), logs ni
  mensajes. Los errores de configuración se muestran por nombre de variable, nunca
  por valor ni con `str(exc)`.

## 11. Runtime y logs

`%LOCALAPPDATA%\ELSA\mode\` (convención de `%LOCALAPPDATA%\ELSA\llm` de los
scripts del LLM; fuera del repositorio y fuera de OneDrive):

```text
supervisor.lock   bloqueo de instancia única
state.json        fase, PIDs informativos, puerto, readiness, latido
stop.request      petición de parada (transitoria)
logs\supervisor.log, elsa-local.log, agent.log   (+ .prev.log del arranque anterior)
```

La salida de los hijos va a sus logs y nunca a la consola. Ante un fallo, el
operador ve un mensaje fijo y la ruta del log; nunca contenido del log ni trazas.

## 12. Consecuencias

- Un ingeniero opera el nodo con tres acciones y un vocabulario de estados cerrado.
- No hay base de datos, migraciones, dependencias nuevas, privilegios de
  administrador, servicios de Windows, Task Scheduler, firewall ni puertos públicos.
- Phi/llama.cpp sigue fuera y se gestiona con sus propios scripts.
- Las piezas exclusivas de Windows (Job Object, `CTRL_BREAK_EVENT`, `msvcrt`) no se
  ejercitan en el CI de Linux; sus tests se ejecutan en Windows y se reportan.

## 13. Riesgos residuales

- `CTRL_BREAK_EVENT` exige que el supervisor tenga consola. Sin ella, la parada pasa
  al cierre forzado sobre el handle propio tras el plazo, y se informa como forzada.
- Entre `Popen` y la asignación al Job Object hay una ventana mínima. uvicorn (sin
  `--reload` ni `--workers`) y el agente no crean procesos nietos.
- Entre la comprobación del puerto y el bind de uvicorn hay una carrera. Si uvicorn
  no puede enlazar, termina, y readiness exige el hijo vivo antes y después del 200.
- El token en el entorno del agente es legible por procesos del mismo usuario,
  igual que al lanzar el agente a mano.
- El log de ELSA puede contener trazas de excepciones. Está en el perfil local del
  usuario y el runbook prohíbe compartirlo sin revisarlo.

## 14. Fuera de esta decisión

Deploy real de Render, configuración real del relay, token real del nodo, primera
conexión Render ↔ PC1, medición de latencia y timeouts, prueba desde PAPELSA, Phi
en `assistant.ask`, servicio de Windows o arranque automático.
