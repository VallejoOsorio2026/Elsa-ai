# ADR 0037 — Límites del ejecutor Claude real

- Estado: **aceptado** (2026-11-03, en el cierre de O1.3, tras el run real `O1.3.R1` del PR #65). Queda
  aceptado cuando Juan haga el merge de ese cierre:
  [`o1-3-claude-real-controlado-cierre.md`](../o1-3-claude-real-controlado-cierre.md)
- Fecha de la decisión: **2026-11-01**; actualizado el **2026-11-02** en O1.3.5 y en O1.3.R1.0
- Bloque: **O1**, incrementos **O1.3.2**, **O1.3.5** y **O1.3.R1.0**
- **Decide**: con qué condiciones el runner puede lanzar Claude Code real, y qué no garantiza. Desde
  O1.3.5, también que **Claude real en O1 no recibe consola**, y qué configuración de Claude Code se niega.
  Desde O1.3.R1.0, **cómo se autoriza un run concreto sobre el repositorio real** (§9)
- **No decide**: ejecutar el primer `run` real sobre el repositorio (`O1.3.R1`) ni O1.4. Cada uno exige un
  gate humano propio
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

O1.3.4 probó, también fuera del repositorio, si una consola limitada a un comando fijo bastaba para lanzar
un hijo y un nieto bajo control. No bastó: la prueba se detuvo antes de las terminaciones, y O1.3.5 cierra
la consola por diseño (§4).

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

**Claude real en O1 no recibe consola.** Ni `Bash`, ni `PowerShell`, ni ninguna herramienta que ejecute
comandos o código, ni `WebFetch`, `WebSearch`, `Task`, MCP o `NotebookEdit`. **No hay excepción para comandos
«seguros».** En O1.3.4, una regla `Bash(<comando exacto>)` con `dontAsk` dejó ejecutar otros comandos de solo
lectura, como `cat`, `whoami` o `git status`, y también encadenar el comando permitido con otro
([`resultados-o1-3-4.md`](../orchestration/resultados-o1-3-4.md)). Una consola acotada no existe en 2.1.316.

El runner lo hace cumplir por su cuenta, con una lista literal de herramientas de archivos escrita aparte de
`CLAUDE_TOOLS`. Si alguien añade una consola a esa constante, o a las herramientas esperadas, se detiene igual:

- **al importar** el runner, si `CLAUDE_TOOLS` incluye otra cosa;
- **al construir el comando**, si `--tools`, `--allowedTools` o `--disallowedTools` nombran otra herramienta,
  separada por comas o por espacios;
- **en el primer evento**, si aparece otra herramienta, antes de la comparación exacta.

`ClaudeExecutor` no tiene ningún parámetro para ampliar herramientas. Su prefijo, que solo usan los tests, no
puede llevar opciones con guion; la barrera de fondo es que el prefijo no se puede fijar desde la consola. Con el
Claude real, tampoco se aceptan las rutas de usuario y administrada que los tests sustituyen. Los agentes que
lista el primer evento no son herramientas ejecutables: sin herramienta de subagentes, nadie puede invocarlos.

Esto no afecta a los comandos propios del runner: Git, gitleaks y los controles de calidad siguen codificados
en `scripts/orchestrator.py`. Eso no es dar consola a Claude.

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
- **Configuración de Claude Code, por defecto denegada.** El primer evento no muestra permisos ni hooks, y la
  configuración administrada se aplica aunque `--safe-mode` y `--restricted` desactiven lo demás. El runner lo
  comprueba antes de lanzar, al terminar y en la revisión de daños. Ver la tabla siguiente.
- **Permisos de escritura con `Edit(ruta)`.** `Write(ruta)` sola no concede nada, y `Edit(ruta)` también
  autoriza `Write` (medido).
- **Denegación de `.env`** en sus 8 variantes de mayúsculas, aunque la copia no lo contenga. Se midieron
  `.env` y `.ENV`.

Las fuentes de configuración se leyeron del binario de 2.1.316 instalado, no se supusieron. **De ninguna se lee
el contenido**, salvo los nombres de clave de `~/.claude/settings.json`:

| Fuente | Qué detiene el bloque |
|---|---|
| Usuario | `settings.json` con claves distintas de las medidas, `settings.local.json` o `cowork_settings.json` |
| Proyecto | En la copia, versionado o no: cualquier `.mcp.json`, y en `.claude/` cualquier cosa fuera de `agents/` y `skills/`, cuyo efecto ya controla el primer evento. En las carpetas que la contienen: `.mcp.json`, `.claude/settings.json` o `.claude/settings.local.json` |
| Administrada en archivo | Que exista `C:\Program Files\ClaudeCode`, donde 2.1.316 busca `managed-settings.json`, `managed-settings.d\` y `managed-mcp.json` |
| Administrada en el registro | Que exista `SOFTWARE\Policies\ClaudeCode` en `HKLM` o `HKCU`, en sus vistas de 32 y 64 bits, o que no se pueda abrir |
| Administrada remota | Su caché en `~/.claude`: `remote-settings.json`, `policy-limits.json` y los archivos de consentimiento |
| Otra ruta administrada | `CLAUDE_CODE_MANAGED_SETTINGS_PATH` nunca llega al proceso, por el entorno cerrado, y `--managed-settings` está prohibida |

**Límites.** La administrada remota solo se detecta por su caché, y por eso también se comprueba al terminar:
es detección, no prevención. No se midió si 2.1.316 lee configuración de las carpetas que contienen la copia:
se niega igual.

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
junctions, y gitleaks. **También cuando Claude se detiene, por cualquier camino:** timeout, error, `blocked`,
capacidad inesperada, `init` ilegible, salida excesiva, `structured_output` inválido, un error al leer el log y
Ctrl+C. Tras cualquier excepción, el runner espera primero a que el job quede vacío; si no se vacía, el motivo
es `orphan_suspected`.

La revisión de daños mira, en este orden, el repositorio principal y su `.git`, `HEAD` y la rama, la
especificación, el índice, los archivos ignorados, el alcance, enlaces y junctions, la traza de Git y la
configuración de Claude Code. Un daño en el repositorio pesa más que un comando Git prohibido, este más que la
configuración, y todo más que el motivo de la parada. **El motivo de la parada no se pierde:** el informe guarda
los dos. Una traza que no se llegó a leer no se da por limpia. Si la revisión falla, el motivo es
`damage_check_failed`: sin revisar, no se puede decir que no hubo daño. Si un segundo Ctrl+C la corta, el
bloque termina como `interrupted` y el informe dice que la revisión quedó a medias.

## 9. Decisión: el repositorio real, cerrado por defecto

`ClaudeExecutor` no está en la consola, solo se inyecta por código y se niega a trabajar si `origin` es el
repositorio autorizado. Lo comprueba en la configuración y preguntándole a Git, por las URL de lectura y de
envío. Compara solo dueño y repositorio, en cualquier anfitrión, para reconocer HTTPS, SSH, usuario, puerto y
alias de host. Un repositorio sin `origin` legible también se rechaza. **Protege de un error, no de un cambio
deliberado:** quien cambie el remoto o el código la salta, y formas raras como `%2D` en la URL no se reconocen.

**Desde O1.3.R1.0, un run concreto se puede autorizar.** Es el «cambio deliberado» que pedía esta cláusula, y
no es un interruptor: es una orden humana para un único run, y todo lo demás de este ADR sigue igual.

- **Qué es.** Un archivo JSON, en UTF-8 sin BOM, en `%USERPROFILE%\elsa-o1\authorizations\<id>.json`, fuera
  del repositorio. Lo escribe Juan, o el **operador** con los valores exactos que Juan da por escrito. El
  operador es la sesión de Claude Code que dirige el bloque y llama al runner. **Nunca lo escribe el Claude que
  el runner lanza**: cuando ese Claude arranca, el archivo ya se retiró. Como el operador también responde a la
  aprobación del runner, el gate humano es el mensaje de Juan que ordena el run.
- **Qué contiene.** Lista cerrada de campos, cada uno con su tipo exacto:

  | Campo | Debe ser |
  |---|---|
  | `schema` | `elsa-o1-real-run-authorization/1` |
  | `block_id` | El del bloque, igual al de la especificación |
  | `repository` | `VallejoOsorio2026/Elsa-ai`. Además, la configuración y cada URL de lectura y de envío de `origin` deben ser exactamente `https://github.com/VallejoOsorio2026/Elsa-ai.git`: normalizar sirve para rechazar, no para permitir |
  | `base_sha` | El SHA de `main` que valida el runner, igual a `origin/main` y al remoto. No existe «el último `main`» |
  | `spec_sha256` | La huella exacta de la especificación |
  | `branch` | La rama de la especificación, `claude/<id>-…`; nunca `main` |
  | `allowed_paths` | Las rutas de la especificación, en el mismo orden |
  | `change` | Solo `add`: cada ruta debe no existir en la base, ni con otras mayúsculas |
  | `profile` | Solo `docs` |
  | `executor` | Solo `claude` |
  | `console` | Solo `false` |

- **Cuándo se valida.** En dos momentos, y siempre antes de crear nada:
  - **Lo primero del run:** se carga el archivo y se exige el remoto exacto. Sin archivo, el repositorio real se
    rechaza como siempre, antes que nada.
  - **Después de las validaciones de solo lectura del runner** (especificación, repositorio, base y rama libre):
    se compara con la especificación y con la base validada.
- **Un solo uso.** Antes de crear la copia, el archivo se mueve a `state\authorizations-used\`. Si la
  ejecución se detiene después, la autorización sigue gastada, y ese bloque no admite otra: reintentar exige
  un identificador nuevo. Si el archivo cambió entre la validación y ese momento, el bloque se detiene.
- **Qué exige además.** El Claude real, sin prefijo: un Claude falso nunca trabaja sobre el repositorio real.
  Antes de lanzarlo, sin fiarse de quien llama: que la autorización coincida con la especificación y que el
  archivo gastado sea precisamente el suyo, que la copia sea la del bloque y no el clon principal, y que esté
  en la rama autorizada, con `HEAD` en el commit de la especificación, que solo trae la especificación, y su
  padre en la base. Al terminar, que los cambios sean exactamente
  las rutas autorizadas, todas nuevas, y que la bandeja y las carpetas de autorizaciones no hayan cambiado:
  eso se comprueba en todo run del ejecutor real, también tras una parada.
- **Qué no concede.** Ni consola, ni perfil `code`, ni push, ni merge, ni despliegue, ni cambios en `main`. El
  runner no publica nada; el push de la rama y el merge siguen siendo decisiones humanas aparte.

**Límites.** El archivo no está firmado: quien tenga el usuario de Windows puede escribirlo, igual que puede
inyectar `ClaudeExecutor` por código. La autorización es un segundo control, no aislamiento.

## 10. Consecuencias

- El runner lanza Claude Code real en repositorios desechables y, solo con una autorización de un uso (§9), en
  el repositorio real.
- Una nueva versión de Claude Code exige repetir las pruebas reales antes de aceptarla. Lo mismo un cambio en
  `.claude/` o `CLAUDE.md` que altere el primer evento: las pruebas reales copian esa estructura.
- Las pruebas reales consumen uso y corren solo a mano, con `ELSA_O1_CLAUDE_LIVE=1`. CI nunca las ejecuta.
- Dar consola a Claude real exigiría un ADR nuevo que reemplace el §4. O1.3.4 muestra por qué una regla de
  comando exacto no basta.
- Cuando llegue, `O1.3.R1` trabajará en una copia de trabajo que crea el runner, nunca sobre `main`.

## 11. Riesgos residuales

| Riesgo | Situación |
|---|---|
| Un fallo de Claude Code tendría acceso a todo el usuario de Windows | **No resuelto.** Aceptado para repositorios desechables y, con autorización de un uso, para un archivo documental nuevo en el repositorio real. Sin datos reales |
| Autorización de run real sin firma | **Aceptado.** Quien tenga el usuario de Windows puede escribirla; es un segundo control junto a la inyección por código, no aislamiento (§9) |
| La copia comparte el `.git` común con el clon principal | **Detectado.** Un cambio en hooks, refs o configuración se ve en la foto del repositorio y detiene el bloque, pero no se impide |
| Red disponible para el proceso | **No resuelto.** Sin herramienta para que el modelo dirija tráfico |
| Credential Manager accesible al usuario | **Mitigado.** Sin consola, y con `credential.helper` anulado para Git interno |
| `.credentials.json` accesible al proceso | **Mitigado.** Claude Code lo necesita; el modelo tiene confinamiento |
| Hijo y nieto de larga duración lanzados por Claude mediante una consola | **NO APLICABLE POR DISEÑO.** Claude real no recibe consola (§4; O1.3.4) |
| Procesos internos propios de Claude Code, como `git`, `reg.exe`, `where.exe` o `conhost.exe` | **Mitigado.** Los terminan el Job Object, el timeout, Ctrl+C y la muerte del runner, con 0 vivos (medido en O1.3.2). **No es aislamiento de Windows** |
| Configuración administrada remota | **Detectado**, no prevenido: solo por su caché local, antes y después de lanzar. Puede traer hooks, que se ejecutan aunque Claude no tenga consola. **Antes de `O1.3.R1`**, confirmar que la cuenta no pertenece a una organización con configuración remota. Hecho para `O1.3.R1`: sin caché remota ni claves de política, y cuenta personal según Juan |
| Comandos de solo lectura que Claude Code autoriza por su cuenta | **NO APLICABLE POR DISEÑO.** Solo ocurren con consola (medido en O1.3.4) |
| Procesos creados a través de otros servicios de Windows | **No resuelto** |
| Configuración global de Git | **No resuelto** |
| Exclusiones por ruta de gitleaks | **Mitigado.** Solo `.md` en rutas exactas, sin las exclusiones por defecto; `.md` en `docs/` se escanea (medido en una ruta) |
| Un hook alterado queda como línea base del siguiente `run` | **Mitigado.** El bloque que lo causó se detiene; el siguiente no lo sabe. Revisado en el cierre de O1.3: `hooks/` del clon principal igual a su foto previa a `O1.3.R1.0` y `O1.3.R1` |
| Seis variantes de `Glob` y `Grep` quedaron INCONCLUSO en O1.3.3 | **Sin explicar.** Sin datos expuestos, pero sin rechazo ni mecanismo conocido |
| `--safe-mode` frente a configuración de usuario distinta | **Sin medir.** Por eso se exige que sea la ya medida, y se niega la de proyecto y la administrada (§4) |
| Valores del primer evento que dependan de la cuenta, como `fast_mode_state` | **Inferencia.** Un cambio ajeno al proyecto detendría el bloque, sin daño; habría que volver a medir |
| `claude.exe` plantado en el `PATH` | **No resuelto.** La versión la declara el propio binario |
| Limpieza de logs y carpeta temporal de Claude | **Parcial.** Sin borrar, fuera del repositorio |

## 12. Fuera de esta decisión

Ejecutar `O1.3.R1`, O1.4, el push y el merge, el perfil `code` y las 3 pruebas que fallan en Windows. La
consola para Claude ya no está fuera de esta decisión: el §4 la descarta.
