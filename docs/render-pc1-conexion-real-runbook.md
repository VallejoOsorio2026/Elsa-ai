# Runbook — Primera conexión real Render ↔ PC1 (D2.6)

Guía para el ingeniero responsable de PC1 y del servicio de Render. Decisión técnica:
[ADR 0035](adr/0035-despliegue-piloto-relay-render-y-credencial-del-nodo.md).

**Qué se consigue.** El relay de ELSA queda desplegado en un servicio de Render dedicado y el
agente de PC1 se conecta a él **solo con conexiones salientes**, hasta que el nodo está **en
línea** de forma estable. Es el límite de D2.6: **NODE ONLINE**.

**Qué NO se hace.** No se envía ninguna pregunta (`assistant.ask`) a PC1, no se usa login real ni
JWT de usuario, no se tocan datos de planta, no se prueba desde PAPELSA y no se usa Phi. No se
modifica el servicio de demostración `elsa-demo` ni `render.yaml`. No se abren puertos, no se
toca el cortafuegos, no hay VPN ni túneles y no hace falta ser administrador.

**Reglas que no se rompen en ningún paso:**

- El **token del nodo** solo existe en la memoria de una ventana de PowerShell de PC1. No se
  imprime, no se copia, no se pega en ningún chat, documento, archivo ni captura.
- El **hash** del token solo se escribe en el campo secreto del servicio de Render.
- **Nunca** se pone `ELSA_ASSISTANT_EXECUTION_MODE=relay` en el servicio piloto: con la identidad
  fake de D2.6, eso enviaría a PC1 preguntas de cualquiera (ADR 0035 §3).
- Si un paso no da el resultado esperado, **se para** y se va a §10 (rollback). No se improvisa.

Marcadores que usa esta guía (se sustituyen por los valores reales, ninguno es secreto):

| Marcador | Qué es |
|---|---|
| `<servicio-piloto>` | Nombre del servicio piloto en Render; su URL es `https://<servicio-piloto>.onrender.com` |
| `<id-del-nodo>` | Identificador del nodo, igual en Render y en PC1 (`[A-Za-z0-9._-]`, p. ej. un nombre neutro como `pc1-piloto`) |

---

## 1. Antes del deploy

1. `main` del repositorio en verde (CI) y con el Modo ELSA de D2.5 integrado. Anotar el SHA de
   `main` que se va a desplegar.
2. En PC1, el Modo ELSA ya funciona en local ([runbook del Modo ELSA](pc1-modo-elsa-runbook.md)).
3. Reservar una ventana de trabajo sin prisa: la primera conexión más la ventana de estabilidad
   llevan unos 40 minutos.
4. Tener a mano esta guía; **no** tener abierto ningún chat ni grabación de pantalla durante los
   pasos de §4.2.

## 2. Deploy del servicio piloto (lo hace el responsable en el panel de Render)

### 2.1 Crear el servicio

Un **servicio web nuevo**, conectado al repositorio del proyecto, sin blueprint:

| Campo | Valor |
|---|---|
| Rama | `main` |
| Runtime | Python, como `elsa-demo` |
| Build command | `pip install uv && uv sync --frozen --no-dev` |
| Start command | `.venv/bin/uvicorn elsa.main:create_app --factory --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*' --workers 1` |
| Health check path | `/api/v1/health/live` |

El start command es el de la demo **más `--workers 1`**. No se añaden otras opciones.

### 2.2 Variables de entorno

Detalle completo en [variables de entorno → Render Relay Pilot](environment-variables.md#render-relay-pilot-d26).

| Variable | Valor | ¿Secreto? |
|---|---|---|
| `ELSA_ENV` | `DEV` | No |
| `ELSA_CORS_ORIGINS` | `https://<servicio-piloto>.onrender.com` | No |
| `ELSA_RELAY_ENABLED` | `true` | No |
| `ELSA_RELAY_NODE_ID` | `<id-del-nodo>` | No |
| `ELSA_RELAY_NODE_TOKEN_SHA256` | El hash de §4.2 (se añade **en ese paso**, no antes) | **Sí** |
| `ELSA_ASSISTANT_EXECUTION_MODE` | `local` | No |
| `ELSA_WEB_UI_ENABLED` | `false` | No |

**No** se declaran `ELSA_AUTH_PROVIDER` (queda `fake`, inocuo en `local`), `ELSA_DEMO_SEED`,
`ELSA_RELAY_NODE_TOKEN_SHA256_PREVIOUS` ni las de Supabase. Los plazos del relay se dejan en su
default.

Con `ELSA_RELAY_ENABLED=true` la aplicación **no arranca** sin un hash válido: es lo esperado.
El orden práctico es crear el servicio con el relay en `false`, comprobar que arranca, y activar
el relay junto con el hash en §4.2.

### 2.3 Comprobar en el panel (no darlo por supuesto)

Anotar lo observado; si algo no coincide, **no se conecta PC1**:

- [ ] el servicio es **nuevo** y distinto de `elsa-demo`;
- [ ] rama `main`;
- [ ] **auto-deploy deshabilitado**: solo despliegues manuales;
- [ ] **una instancia**, sin escalado horizontal ni autoescalado configurado;
- [ ] el start command termina en `--workers 1`.

El plan contratado no se da por garantía de nada de lo anterior: lo que vale es lo observado en
el panel y en los logs (§3).

### 2.4 Desplegar

Despliegue **manual** del SHA anotado en §1. Esperar a que termine con éxito.

## 3. Gate Render (antes de conectar PC1)

Todas estas pruebas se hacen **sin token y sin JWT**. Se ejecutan desde la raíz del repositorio,
con el Python del proyecto, sin proxy (`trust_env=False`, igual que el agente).

El gate se pasa **dos veces**:

- tras §2.4, con el relay todavía apagado: pruebas 1, 2 y 4 (con `"relay_enabled": false`);
- tras §4.2, con el relay encendido: **todas**, y con `"relay_enabled": true`.

1. **Liveness:**

   ```powershell
   .venv\Scripts\python.exe -c "import httpx; r = httpx.get('https://<servicio-piloto>.onrender.com/api/v1/health/live', trust_env=False, timeout=30); print(r.status_code, r.text)"
   ```

   Esperado: `200 {"status":"ok"}`. Si el servicio estaba dormido, la primera respuesta puede
   tardar; repetir una vez.

2. **Readiness:** la misma orden con `/api/v1/health/ready`. Esperado: `200`, con
   `"environment": "DEV"` y `"status"` en `ok` o `degraded`. `degraded` es normal si solo
   degradan dependencias no críticas (por ejemplo la transcripción simulada). Un `503` bloquea.

3. **Relay montado y cerrado** (solo después de §4.2, con el relay ya en `true`):

   ```powershell
   .venv\Scripts\python.exe -c "import httpx; r = httpx.post('https://<servicio-piloto>.onrender.com/api/v1/relay/node/register', json={}, trust_env=False, timeout=30); print(r.status_code, r.json()['error']['code'])"
   ```

   Esperado: `401 unauthorized`: la ruta existe y rechaza una petición sin credencial. Un `404`
   significa que el relay está apagado. En los logs de Render aparecerá un evento `auth_failed`
   por esta prueba: es esperado.

4. **Un solo worker**, en los logs del arranque en Render:
   - [ ] exactamente **una** línea `Started server process [N]`;
   - [ ] **ninguna** línea `Started parent process` ni `Waiting for child process` (son del
     supervisor multiproceso de uvicorn);
   - [ ] la línea `application configured` muestra `"relay_enabled": true` y
     `"assistant_execution_mode": "local"`.

   Si aparece más de un proceso o más de una instancia: **no se conecta PC1**.

5. **Logs sin secretos (opcional):** la aplicación nunca registra el hash (es un valor secreto
   de la configuración). Si se quiere comprobar, el responsable busca en los logs del panel los
   primeros caracteres del hash, tomados del propio campo secreto; no debe aparecer nada. El
   valor no se escribe en ningún otro sitio.

## 4. Preparar PC1

### 4.1 Comprobación de red directa (sin proxy)

Desde la raíz del repositorio en PC1:

```powershell
.venv\Scripts\python.exe -c "import httpx; r = httpx.get('https://<servicio-piloto>.onrender.com/api/v1/health/live', trust_env=False, timeout=30); print(r.status_code, r.text)"
```

Usa la misma biblioteca y la misma política que el agente: **ignora cualquier proxy** del
entorno. Esperado: `200 {"status":"ok"}`.

Si falla (error de conexión, de TLS o tiempo agotado) pero el navegador sí abre la URL, la red de
PC1 exige un proxy: **D2.6 se bloquea**. No se cambia la configuración del agente ni se configura
ningún proxy en este bloque.

### 4.2 Credencial del nodo (una ventana, un token)

Abrir **una sola ventana nueva de PowerShell** en la raíz del repositorio y no cerrarla hasta §9.
Ejecutar, línea a línea:

```powershell
$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create(); $rng.GetBytes($bytes); $rng.Dispose()
$nodeToken = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
Remove-Variable bytes
$sha = [System.Security.Cryptography.SHA256]::Create()
$nodeHash = -join ($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($nodeToken)) | ForEach-Object { $_.ToString('x2') })
$sha.Dispose()
$nodeToken.Length
$nodeHash
```

- `$nodeToken.Length` debe mostrar `43`. **El token no se muestra nunca**: ninguna línea lo
  imprime.
- `$nodeHash` muestra 64 caracteres hexadecimales: es lo que se copia **solo** al campo secreto
  `ELSA_RELAY_NODE_TOKEN_SHA256` del servicio piloto. No se pega en ningún otro sitio ni se
  captura la pantalla.
- El historial de PowerShell guarda estas órdenes, no los valores.

En el panel de Render: poner `ELSA_RELAY_NODE_TOKEN_SHA256` con el hash y
`ELSA_RELAY_ENABLED=true`, desplegar (manual) y repetir el gate completo de §3, incluida la
prueba 3 (401).

De vuelta en **la misma ventana**:

```powershell
Remove-Variable nodeHash
$env:ELSA_AGENT_NODE_TOKEN = $nodeToken
Remove-Variable nodeToken
```

El token queda solo en el entorno de esta ventana, que es de donde lo toma el agente.

### 4.3 Configuración no secreta del agente

En el `.env` de la raíz del repositorio en PC1 (además de la configuración habitual de ELSA):

```text
ELSA_AGENT_RELAY_URL=https://<servicio-piloto>.onrender.com
ELSA_AGENT_NODE_ID=<id-del-nodo>
ELSA_AGENT_LOCAL_BASE_URL=http://127.0.0.1:8000
```

**`ELSA_AGENT_NODE_TOKEN` nunca va en el `.env`**: el Modo ELSA se niega a arrancar si lo
encuentra ahí. El Modo ELSA fija por su cuenta `ELSA_ASSISTANT_EXECUTION_MODE=local`,
`ELSA_RELAY_ENABLED=false` y `ELSA_DEBUG=false` para ELSA local.

## 5. Primera conexión

En **la misma ventana** de §4.2:

```powershell
.\scripts\Start-ElsaMode.ps1
```

1. El preflight pasa y aparece `ELSA LOCAL: LISTA` (o `LISTA CON DEGRADACIONES NO CRÍTICAS`).
2. Arranca el agente y aparece `Modo ELSA: EN MARCHA`.
3. La línea `Relay Render: conectividad NO VERIFICADA` **sigue apareciendo**: el Modo ELSA no
   comprueba la conexión. La evidencia está en los logs (§7).
4. Anotar la hora.

En **otra** ventana de PowerShell (sin el token), comprobar que PC1 no expone nada:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000 | Select-Object LocalAddress, LocalPort
```

Esperado: solo `127.0.0.1`. Ningún `0.0.0.0` ni IP de red.

## 6. Estabilidad (20 minutos)

Dejar el nodo conectado **20 minutos** sin tocar nada. Es una ventana de estabilidad; no sirve
para comprobar las reglas comerciales del plan de Render, que se verifican el día de la prueba.

Criterio de **NODE ONLINE**, con todo lo siguiente:

- [ ] `node_registered` en los logs de Render, con `node_id` = `<id-del-nodo>` y un
  `node_session_id`;
- [ ] `node_registered` en `agent.log` de PC1 a la misma hora (±1 min);
- [ ] peticiones `POST /api/v1/relay/node/poll` con estado **200** de forma continua durante los
  20 minutos (con el relay sin trabajo, cada poll dura cerca de 25 s);
- [ ] ningún `register_failed`, `session_stale`, `node_offline`, `401`, `409` ni `5xx` en la
  ventana;
- [ ] `Get-ElsaModeStatus.ps1` (en la otra ventana) sigue en `EN MARCHA`.

## 7. Evidencia

**Se recoge** (sin secretos, para el documento de cierre):

| Origen | Qué |
|---|---|
| Render | SHA y hora del deploy; respuestas de §3; líneas de arranque de uvicorn; eventos `node_registered`, `node_offline`, `node_session_replaced`, `stale_session`, `auth_failed` con su hora, `node_id` y `node_session_id`; conteo y duración de los polls (`path`, `status_code`, `duration_ms`) |
| PC1 | Salida de `Get-ElsaModeStatus.ps1`; eventos de `supervisor.log` (`elsa_ready` con sus segundos, `child_started`, `child_stopped`) y de `agent.log` (`agent_started`, `node_registered`, `agent_stopped`); la salida de `Get-NetTCPConnection` |
| Tiempos | Deploy, primera respuesta del servicio, START → `ELSA LOCAL: LISTA`, START → `node_registered`, duración de la conexión, STOP → START |

**No se recoge nunca:** el token, el hash, la pantalla de variables de Render, cabeceras,
cuerpos de petición o respuesta, volcados de entorno, JWT, preguntas, datos de planta. Los
extractos de logs se filtran por nombre de evento antes de copiarlos.

## 8. STOP, OFFLINE y reconexión

**Cómo se ve OFFLINE.** El relay no avisa cuando el nodo desaparece: la sesión queda expirada por
política tras `ELSA_RELAY_NODE_TTL_SECONDS` (45 s por defecto), pero el evento `node_offline` se
registra en la **siguiente operación** que ejecuta la expiración, normalmente el REGISTER del
siguiente START. No se espera ver nada en Render en el momento exacto del TTL.

### 8.1 Reconexión tras el TTL

1. En la ventana del Modo ELSA: **Ctrl+C** (o `Stop-ElsaMode.ps1` desde la otra). Termina con
   `Modo ELSA detenido.`
2. Esperar **al menos 90 segundos** (TTL + long poll + margen).
3. En la misma ventana (el token sigue en su entorno): `.\scripts\Start-ElsaMode.ps1`.
4. Esperado en Render: `node_offline` con el `node_session_id` **anterior** y, a continuación,
   `node_registered` con uno **nuevo**. Polls 200 de nuevo.

### 8.2 Reconexión inmediata

1. STOP y START sin esperar.
2. Esperado en Render: `node_session_replaced` y `node_registered` con un `node_session_id`
   **nuevo**.

En ambos casos el agente nunca reutiliza una sesión y no hay replay de nada.

## 9. Fin de la sesión y limpieza de secretos

Siempre, también si algo falló:

1. STOP del Modo ELSA y esperar a `Modo ELSA detenido.`
2. En la ventana del token, **antes** de borrarlo, comprobar que no quedó escrito en ningún
   archivo de la prueba. Cada orden responde solo `True` o `False` y nunca muestra el valor:

   ```powershell
   Select-String -Path "$env:LOCALAPPDATA\ELSA\mode\*.*", "$env:LOCALAPPDATA\ELSA\mode\logs\*.log" -Pattern $env:ELSA_AGENT_NODE_TOKEN -SimpleMatch -Quiet
   Select-String -Path .env -Pattern $env:ELSA_AGENT_NODE_TOKEN -SimpleMatch -Quiet
   ```

   Esperado: `False` en las dos. Un `True` es un incidente: anotar **en qué archivo** (sin el
   contenido), borrar ese archivo y tratar el token como expuesto (no reutilizar el hash).

   Después:

   ```powershell
   Remove-Item Env:\ELSA_AGENT_NODE_TOKEN
   exit
   ```

   Que el token no va en argumentos de proceso lo prueban ya los tests automáticos de D2.5.

3. En Render: poner `ELSA_RELAY_ENABLED=false` (o suspender el servicio piloto) y desplegar. El
   hash de esa sesión ya no sirve para nada: el token no existe.
4. Comprobar que `git status` en PC1 no muestra ningún archivo nuevo con datos de la prueba.

Una sesión posterior empieza de nuevo en §4.2 con **otro** token.

## 10. Rollback

| Situación | Qué hacer |
|---|---|
| El deploy falla o el health no responde | No conectar PC1. Revisar el log de build/arranque en Render; con el relay en `true` y sin hash válido, la aplicación no arranca por diseño |
| `register` sin token no da `401` | Relay apagado (`404`) o configuración errónea: corregir en el panel y repetir §3 |
| Aparece más de un worker o instancia | No conectar PC1. Corregir el start command o la configuración de instancias |
| El agente no registra (`401`/`404`) | El agente termina solo y el Modo ELSA se detiene. Revisar `<id-del-nodo>` y el hash; si hay duda, nuevo token (§4.2) |
| El agente reintenta sin parar (red, `5xx`) | STOP del Modo ELSA. Revisar §4.1 |
| PC1 queda `DEGRADADO` | STOP. Revisar `elsa-local.log` (ruta en el mensaje) |
| Cualquier duda | §9 completo |

El estado final de un rollback es siempre: **PC1 detenido, sin token; Render sin recibir nodo**.
Nunca se cambia el cortafuegos, se mata un proceso que no sea del Modo ELSA ni se borran datos.

## 11. Restart de Render (sesión posterior, nunca en la primera conexión)

Solo cuando §6 y §8 ya se superaron en una sesión anterior.

1. Nodo en línea (§5–§6).
2. En el panel: reiniciar o redesplegar manualmente el servicio piloto.
3. Durante el reinicio, en `agent.log` pueden aparecer fallos transitorios y reintentos con
   espera creciente (hasta 30 s). El relay nuevo no conoce la sesión: puede responder `409`
   `stale_session`, y el agente registra una sesión nueva.
4. Esperado al final: `node_registered` con un `node_session_id` nuevo y polls 200 sostenidos.
5. Medir: duración del corte, número de reintentos, tiempo hasta el nuevo `node_registered`.

Los `409` y fallos temporales **durante** el reinicio son el comportamiento diseñado: el
veredicto se da sobre la recuperación completa, no sobre cada error intermedio.

## 12. Qué NO hacer

- No poner `ELSA_ASSISTANT_EXECUTION_MODE=relay` en el servicio piloto.
- No escribir el token en el `.env`, en un archivo, en un argumento ni en el portapapeles; no
  mostrarlo en pantalla.
- No pegar el token ni el hash en ningún chat ni documento; no hacer capturas de esos pasos.
- No reutilizar el servicio `elsa-demo` ni cambiar `render.yaml`.
- No activar auto-deploy en el servicio piloto.
- No configurar un proxy, VPN, túnel ni regla de cortafuegos para «hacer que funcione».
- No ejecutar como administrador.
- No dar por terminado el piloto: D2.6 llega a NODE ONLINE, no a una consulta remota.
