# ADR 0037 — Límites del ejecutor Claude real

- Estado: **propuesto**
- Fecha de la decisión: **2026-11-01**
- Bloque: **O1**, incremento **O1.3.2**
- **Decide**: con qué condiciones el runner puede lanzar Claude Code real, y qué no garantiza
- **No decide**: el primer `run` real sobre el repositorio (`O1.3.R1`), ni dar consola a Claude, ni
  O1.4. Cada uno exige un gate humano propio
- **No reabre** el [ADR 0036](0036-orquestacion-semiautomatica-de-bloques.md), cuyo §9 condicionaba el
  ejecutor a una prueba de bloqueo. Esa prueba ya se hizo:
  [`resultados-o1-3-1-y-o1-3-3.md`](../orchestration/resultados-o1-3-1-y-o1-3-3.md)
- Implementación: `scripts/orchestrator.py`
- Aplica las reglas **11, 12, 17, 20, 21, 22, 23 y 25** de [`CLAUDE.md`](../../CLAUDE.md)

## 1. Contexto

O1.3.1 y O1.3.3 ejecutaron Claude Code 2.1.316 sin supervisión, solo en repositorios desechables y sin
consola: 53 ejecuciones. Ningún señuelo se filtró, nada se escribió fuera de la copia y no quedaron
procesos vivos.

**Pero eso no es aislamiento.** Claude Code corre con el usuario de Windows y con acceso a la red. Lo que
lo limita son sus propias restricciones y las comprobaciones posteriores del runner.

## 2. Decisión: vocabulario

| Palabra | Significado |
|---|---|
| **Prevenido por Claude Code** | La herramienta lo rechaza. Depende de que Claude Code no tenga un fallo |
| **Detectado** | Pudo ocurrir; el runner lo ve después y bloquea el resultado |
| **Prevenido por Windows** | Solo el Job Object: mata todos los procesos del árbol |

En este proyecto, «aislado» no describe este ejecutor.

## 3. Decisión: solo documentación

Con ejecutor real, una especificación solo puede permitir **rutas exactas de `.md` bajo `docs/`, o
`README.md`**, sin comodines y con un máximo de 5. También se rechazan los nombres no seguros y las rutas que
gitleaks excluye por defecto, como `node_modules/` o `vendor/`.

**El perfil `code` queda prohibido**, porque `pytest` ejecutaría código escrito por Claude con el usuario
de Windows, que tiene acceso a `.env` y a las credenciales. Si el diff llegara a tocar código, el bloque se
detiene antes de cualquier control.

## 4. Decisión: sin consola y sin capacidades añadidas

El comando siempre lleva:

```text
--safe-mode --restricted --strict-mcp-config --disable-slash-commands
--tools Read,Edit,Write,Glob,Grep
--permission-mode dontAsk --permission-prompts none
--no-session-persistence
```

- **Ninguna opción basta sola.** `--restricted` sin `--tools` deja disponibles `WebSearch` y `Task`, entre
  otras (medido).
- **Sin `--settings`.** Con `-p`, un archivo inválido se ignora en silencio (medido). Antes de lanzar se
  comprueba una **lista cerrada de opciones**: cada una una sola vez y con su valor exacto.
- **Configuración de usuario.** El primer evento no muestra permisos ni hooks de usuario. El runner exige que
  `~/.claude/settings.json` solo tenga las claves ya medidas, y que no exista `settings.local.json`. Solo lee
  sus nombres de clave.
- **Permisos de escritura con `Edit(ruta)`.** `Write(ruta)` sola no concede nada, y `Edit(ruta)` también
  autoriza `Write` (medido).
- **Denegación de `.env`** en sus 8 variantes de mayúsculas, aunque la copia no lo contenga. Se midieron
  `.env` y `.ENV`.

## 5. Decisión: versión exacta y primer evento

Todo se midió en **2.1.316**. Otra versión detiene el bloque, antes de lanzar y al terminar. El runner no
cambia la configuración de actualizaciones.

El primer evento se compara **de forma exacta**, con lista cerrada de sus 27 campos: un campo nuevo o ausente
o un valor distinto termina el proceso, y sin primer evento en 60 s también. Hay tres salvedades: `uuid` y
`powershell_path` no se comparan, porque cambian por ejecución o por máquina; `tools` y `agents` se comparan sin
importar el orden; y `model` solo exige el prefijo `claude-sonnet`, porque `sonnet` es un alias. El log se vigila
durante toda la ejecución: un `init` posterior también se compara, y una línea ilegible que parezca un `init`
detiene el bloque. **Lo que ocurra antes del primer evento y hasta unos 100 ms después solo se puede detectar,
no impedir.**

## 6. Decisión: entorno cerrado

Lista cerrada de variables, sin `ANTHROPIC_*`, `CLAUDE*` ni tokens heredados. El runner solo añade valores
fijos, entre ellos `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`. La autenticación usa la credencial ya presente en
el perfil. Si hiciera falta un token, el bloque se detiene.

## 7. Decisión: comandos Git internos

Claude Code lanza `git` por su cuenta, incluso sin consola para el modelo. Se registran con `GIT_TRACE` y se
aceptan solo los comandos de lectura observados. **Cualquier otro, o una línea desconocida, detiene el
bloque.** Es detección posterior: el comando ya se ejecutó. **Sus límites:** Git no registra opciones globales
como `-C`, y el proceso vigilado controla esa variable y ese archivo.

## 8. Decisión: Claude no decide nada

`structured_output` se valida en forma y se compara con Git. Una discrepancia bloquea. **Todos los controles
independientes del runner siguen activos:** alcance, archivos ignorados, `HEAD`, índice, `.git`, enlaces y
junctions, y gitleaks. **También cuando Claude se detiene:** en un timeout, un error o un `blocked`, se revisan
la traza, el repositorio y el alcance, y un daño pesa más que el motivo declarado.

## 9. Decisión: el repositorio real sigue cerrado

`ClaudeExecutor` no está en la consola, solo se inyecta por código y se niega a trabajar si `origin` es el
repositorio autorizado. Lo comprueba en la configuración y preguntándole a Git, por las URL de lectura y de
envío. Compara solo dueño y repositorio, en cualquier anfitrión, para reconocer HTTPS, SSH, usuario, puerto y
alias de host. Un repositorio sin `origin` legible también se rechaza. **Protege de un error, no de un cambio
deliberado:** quien cambie el remoto o el código la salta, y formas raras como `%2D` en la URL no se reconocen.
Abrirlo exige un gate humano y un cambio deliberado de esa función.

## 10. Consecuencias

- El runner lanza Claude Code real, pero solo en repositorios desechables hasta el gate de `O1.3.R1`.
- Una nueva versión de Claude Code exige repetir las pruebas reales antes de aceptarla. Lo mismo un cambio en
  `.claude/` o `CLAUDE.md` que altere el primer evento: las pruebas reales copian esa estructura.
- Las pruebas reales consumen uso y corren solo a mano, con `ELSA_O1_CLAUDE_LIVE=1`. CI nunca las ejecuta.

## 11. Riesgos residuales

| Riesgo | Situación |
|---|---|
| Un fallo de Claude Code tendría acceso a todo el usuario de Windows | **No resuelto.** Aceptado solo para repositorios desechables, sin datos reales y cambios documentales |
| Red disponible para el proceso | **No resuelto.** Sin herramienta para que el modelo dirija tráfico |
| Credential Manager accesible al usuario | **Mitigado.** Sin consola, y con `credential.helper` anulado para Git interno |
| `.credentials.json` accesible al proceso | **Mitigado.** Claude Code lo necesita; el modelo tiene confinamiento |
| Hijo y nieto de larga duración de Claude | **Sin demostrar.** Exige consola, y sigue sin autorizarse |
| Procesos creados a través de otros servicios de Windows | **No resuelto** |
| Configuración global de Git | **No resuelto** |
| Exclusiones por ruta de gitleaks | **Mitigado.** Solo `.md` en rutas exactas, sin las exclusiones por defecto; `.md` en `docs/` se escanea (medido en una ruta) |
| Un hook alterado queda como línea base del siguiente `run` | **Mitigado.** El bloque que lo causó se detiene; el siguiente no lo sabe. Revisar antes de `O1.3.R1` |
| Seis variantes de `Glob` y `Grep` quedaron INCONCLUSO en O1.3.3 | **Sin explicar.** Sin datos expuestos, pero sin rechazo ni mecanismo conocido |
| `--safe-mode` frente a configuración de usuario distinta | **Sin medir.** Por eso se exige que sea la ya medida |
| Valores del primer evento que dependan de la cuenta, como `fast_mode_state` | **Inferencia.** Un cambio ajeno al proyecto detendría el bloque, sin daño; habría que volver a medir |
| `claude.exe` plantado en el `PATH` | **No resuelto.** La versión la declara el propio binario |
| Limpieza de logs y carpeta temporal de Claude | **Parcial.** Sin borrar, fuera del repositorio |

## 12. Fuera de esta decisión

`O1.3.R1`, la consola para Claude, O1.4, el perfil `code` y las 3 pruebas que fallan en Windows.
