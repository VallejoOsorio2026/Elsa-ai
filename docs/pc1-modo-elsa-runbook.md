# Runbook — Modo ELSA en PC1

Guía para el ingeniero que opera PC1. No hace falta saber Python.

**Qué es.** El Modo ELSA prepara PC1 como nodo del piloto con una sola acción:
comprueba la configuración, arranca **ELSA local** (solo en este equipo,
dirección `127.0.0.1`), espera a que esté lista y después arranca el **agente de
PC1**, que es quien más adelante hablará con Render. También consulta el estado y
detiene todo en orden.

**Qué no es.** No conecta todavía con Render: en este piloto la conexión real
**no se verifica** (verá siempre «conectividad NO VERIFICADA»). No arranca el
modelo Phi (`Start-ElsaLlm.ps1` es aparte y no hace falta para el Modo ELSA). No
instala nada, no necesita administrador, no abre puertos ni toca el cortafuegos.

Decisión técnica: [ADR 0034](adr/0034-modo-elsa-operativo-pc1-pilot-0-1.md).

## 1. Antes de empezar (una sola vez)

1. El repositorio de ELSA está en PC1 y su entorno `.venv` está preparado según
   el [README](../README.md). Los scripts usan ese entorno; no instalan nada.
2. El archivo `.env` de la carpeta del repositorio tiene el **perfil PC1**
   ([variables de entorno](environment-variables.md#modo-elsa-en-pc1-d25)):

   ```text
   ELSA_ASSISTANT_EXECUTION_MODE=local
   ELSA_RELAY_ENABLED=false
   ELSA_AGENT_RELAY_URL=<URL https del relay, la entrega el responsable>
   ELSA_AGENT_NODE_ID=<identificador del nodo, lo entrega el responsable>
   ELSA_AGENT_LOCAL_BASE_URL=http://127.0.0.1:8000
   ```

   además de la configuración normal de ELSA (`ELSA_ENV`, identidad, etc.).
3. **El token del nodo no va en el `.env`.** Es una contraseña: el Modo ELSA lo
   pide al iniciar, sin mostrarlo en pantalla. Si alguien lo escribió en el
   `.env`, el Modo ELSA se niega a arrancar.

## 2. Iniciar

1. Abra **PowerShell** y vaya a la carpeta del repositorio.
2. Ejecute:

   ```powershell
   .\scripts\Start-ElsaMode.ps1
   ```

3. Cuando pida `Token del nodo (no se muestra al escribir):`, péguelo y pulse
   Enter. No verá caracteres: es normal.
4. Espere. ELSA local puede tardar hasta un par de minutos en quedar lista.
5. Cuando aparezca el resumen **«Modo ELSA: EN MARCHA»**, el nodo quedó listo.
   **Deje esa ventana abierta**: es la ventana «Modo ELSA».

Resumen de ejemplo:

```text
Modo ELSA: EN MARCHA
  ELSA local  : proceso activo (PID 1234) · 127.0.0.1:8000 · LISTA CON DEGRADACIONES NO CRÍTICAS (transcription)
  Agente PC1  : proceso activo (PID 5678)
  Relay Render: conectividad NO VERIFICADA

Deje esta ventana abierta. Para detener: Ctrl+C aquí o Stop-ElsaMode.ps1.
```

Si ya hay un Modo ELSA en marcha, el segundo inicio se niega: no puede haber dos.

## 3. Qué significa cada estado de ELSA local

| Mensaje | Qué significa | ¿El nodo sirve? |
|---|---|---|
| **LISTA** | ELSA local responde y todas sus dependencias están bien. | Sí |
| **LISTA CON DEGRADACIONES NO CRÍTICAS (…)** | ELSA local responde. Las piezas entre paréntesis están simuladas o sin configurar todavía (por ejemplo, `transcription`). **Es lo normal en este piloto.** | Sí |
| **NO LISTA** | ELSA local no responde, o le falta algo imprescindible. Si aparece «dependencias críticas caídas: auth», ELSA no puede comprobar quién es cada usuario. | No. Durante el inicio, el agente **no** se arranca y todo se detiene |
| **Relay Render: conectividad NO VERIFICADA** | El Modo ELSA no comprueba la conexión con Render en este piloto. **No es un error.** | — |

## 4. Consultar el estado

Desde **otra** ventana de PowerShell, en la carpeta del repositorio:

```powershell
.\scripts\Get-ElsaModeStatus.ps1
```

Solo lee; no cambia nada.

| Estado | Qué significa |
|---|---|
| **EN MARCHA** | ELSA local lista y agente en ejecución. |
| **ARRANCANDO** | El inicio está en curso. |
| **DEGRADADO** | Algo que funcionaba dejó de hacerlo: ELSA local dejó de responder o pasó a NO LISTA, uno de los procesos terminó y empieza la parada, o la ventana «Modo ELSA» no responde. |
| **DETENIÉNDOSE** | La parada está en curso. |
| **DETENIDO** | No hay Modo ELSA en marcha. |

## 5. Detener

Cualquiera de las dos formas hace una parada ordenada (primero el agente,
después ELSA local):

- **Ctrl+C** en la ventana «Modo ELSA», o
- desde otra ventana:

  ```powershell
  .\scripts\Stop-ElsaMode.ps1
  ```

Termina con **«Modo ELSA detenido.»**

**Cerrar la ventana** «Modo ELSA» también detiene sus procesos, pero de golpe, sin
parada ordenada. Úselo solo si el método normal no responde.

## 6. Si los scripts `.ps1` están bloqueados

Si la política de la organización no permite ejecutar los scripts, **no cambie
la política**. Use los comandos equivalentes, desde la carpeta del repositorio:

```powershell
.venv\Scripts\python.exe -m elsa.pc1 start
.venv\Scripts\python.exe -m elsa.pc1 status
.venv\Scripts\python.exe -m elsa.pc1 stop
```

## 7. Qué hacer ante cada mensaje

| Mensaje (resumido) | Qué hacer |
|---|---|
| «No se encontró el entorno de ELSA (.venv)» | Prepare el entorno según el README y repita. |
| «No se encontró la carpeta de datos locales del usuario (%LOCALAPPDATA%)» | Use una sesión normal de Windows con su usuario. Si persiste, avise al responsable. |
| «Modo ELSA ya está en marcha en este equipo» | Consulte el estado o deténgalo antes de volver a iniciar. |
| «La configuración de ELSA está incompleta o no es válida. Variables: …» | Revise en el `.env` las variables nombradas ([variables de entorno](environment-variables.md)). |
| «La configuración no corresponde al perfil PC1…» | En el `.env`: `ELSA_ASSISTANT_EXECUTION_MODE=local`, `ELSA_RELAY_ENABLED=false` y `ELSA_DEBUG` en `false` o ausente. |
| «La configuración del agente está incompleta o no es válida. Variables: …» | Complete en el `.env` las variables nombradas; la URL del relay debe empezar por `https://`. |
| «La URL local del agente debe ser http://127.0.0.1:<puerto>…» | Escriba exactamente `ELSA_AGENT_LOCAL_BASE_URL=http://127.0.0.1:8000` (no `localhost`). |
| «El token del nodo está escrito en el archivo de configuración» | Borre esa línea del `.env` y **avise al responsable**: un token que estuvo guardado en disco debe considerarse expuesto y reemplazarse. |
| «Falta el token del nodo y no hay consola para pedirlo» | Inicie desde una ventana de PowerShell normal, no desde una tarea automática. |
| «El token del nodo introducido no tiene un formato válido» | Repita el inicio y pegue el token completo, sin espacios. |
| «El archivo de configuración no se puede leer como texto UTF-8» | Guarde el `.env` como UTF-8 desde el editor. |
| «El puerto 127.0.0.1:N está ocupado por otro programa» | Otro programa usa ese puerto; el Modo ELSA **no** lo toca. Si es una ELSA que usted arrancó a mano, ciérrela. Si no sabe qué es, no lo cierre: avise al responsable. |
| «ELSA LOCAL: NO LISTA… No quedó lista en 120 s; el agente no se inicia» | Revise lo que diga entre paréntesis (p. ej. `auth`: conexión con el Supabase de Materiales) y el log `elsa-local.log`. Repita cuando esté resuelto. |
| «ELSA local terminó durante el arranque (código X)» | Revise `elsa-local.log`. Suele ser configuración. |
| «El agente de PC1 terminó durante el arranque (código 2)» | Configuración rechazada, o el relay rechazó la credencial o el protocolo. Revise `agent.log` y avise al responsable. |
| «… terminó inesperadamente (código X). Modo ELSA se detiene.» | Todo el nodo se detuvo (no se reinicia solo). Inicie de nuevo; si se repite, revise el log indicado y avise. |
| «Modo ELSA: DEGRADADO. ELSA LOCAL: NO LISTA …» | Puede recuperarse solo. Si no, detenga e inicie de nuevo. |
| «… no respondió a la parada ordenada; se forzó su cierre.» | Informativo: se cerró a la fuerza **solo** ese proceso del Modo ELSA. |
| «El supervisor no respondió en 60 s. Cierre la ventana «Modo ELSA»» | Cierre esa ventana; Windows terminará sus procesos. |
| «No se pudo preparar el control de procesos de Windows (Job Object)» | No se arrancó nada. Avise al responsable. |
| «El último cierre de Modo ELSA no fue limpio. Se limpió su estado» | Informativo. No se detuvo ningún proceso. |

Códigos de salida de los scripts: `0` correcto · `1` el arranque o la parada
fallaron (o el nodo se detuvo por un fallo) · `2` configuración o entorno
inválidos · `3` ya hay un Modo ELSA en marcha.

## 8. Logs

En `%LOCALAPPDATA%\ELSA\mode\logs\`:

| Archivo | Contenido |
|---|---|
| `supervisor.log` | Arranques, paradas, estados y códigos de salida. |
| `elsa-local.log` | Salida de ELSA local. |
| `agent.log` | Salida del agente. |
| `*.prev.log` | El mismo log del arranque anterior. Solo se guardan el actual y el anterior. |

Los logs no deben contener tokens ni preguntas, pero ante un fallo pueden
incluir detalles técnicos. **No los comparta sin revisarlos.** En la misma
carpeta, `state.json` es el estado del supervisor (sin secretos); no lo edite.

## 9. Qué NO hacer

- No escriba el token del nodo en el `.env` ni en ningún otro archivo, ni lo
  pegue en chats, correos o capturas.
- No use `setx` ni variables de entorno permanentes para el token.
- No cambie la política de ejecución de PowerShell.
- No ejecute el Modo ELSA como administrador: no lo necesita.
- No abra puertos, no cree reglas de cortafuegos ni configure VPN o túneles.
- No termine procesos de ELSA desde el Administrador de tareas; use Ctrl+C o
  `Stop-ElsaMode.ps1`.
- No arranque ELSA o el agente a mano mientras el Modo ELSA está en marcha.
- No interprete «EN MARCHA» como «conectado a Render»: la conexión no se
  verifica en este piloto.
