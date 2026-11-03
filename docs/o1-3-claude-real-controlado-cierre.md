# Cierre formal — O1.3: Claude Code real controlado

- **Fecha:** 2026-11-03.
- **Estado:** cierre formal de O1.3. **Es efectivo cuando este documento quede integrado en `main`** con el CI
  obligatorio en verde (ver «Regla de continuidad»).
- **Qué cierra:** el subbloque **O1.3** del bloque O1. Recoge O1.3.1 a O1.3.5, O1.3.R1.0 (que tiene su propio
  cierre) y O1.3.R1. Deja
  un ejecutor Claude Code real dentro del runner, sin consola y solo para documentación, que ya hizo un run
  real verificado sobre el repositorio ELSA.
- **Qué NO cierra:** **no cierra O1**, ni abre O1.4. Ver §20 y «Qué no acredita O1.3».
- **Prerrequisitos:** O1.2 ([`o1-2-runner-local-minimo-cierre.md`](o1-2-runner-local-minimo-cierre.md)).
- **Decisión técnica:** [ADR 0037](adr/0037-limites-del-ejecutor-claude-real.md), que este cierre pasa a
  «aceptado» (§5). No reabre el [ADR 0036](adr/0036-orquestacion-semiautomatica-de-bloques.md).
- **Especificación:** [`orchestration/work/O1.3.md`](orchestration/work/O1.3.md).
- **Marcas** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**, **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**,
  **INFERENCIA**, **PENDIENTE**.
- **Procedencia de lo medido:** cada **HECHO MEDIDO** dice de dónde sale. Puede salir de un documento
  versionado, de la sesión operadora de Claude Code o de GitHub. Los logs locales de los runs no se versionan,
  y de ellos solo se registran conteos y valores no sensibles.
- **Sanitización:** este documento no contiene secretos, tokens, cadenas de conexión, rutas de perfil de
  usuario ni datos de planta.

---

## 1. Objetivo

Que el runner de O1 pueda lanzar Claude Code real sin supervisión, con protecciones demostradas, sin consola y
solo para documentación. Y que esa vía quede acreditada con un run real sobre el repositorio ELSA, revisado por
una persona antes del merge.

## 2. Alcance

**Entró:**

- El ejecutor `ClaudeExecutor` en `scripts/orchestrator.py`, con sus tests y el Claude falso.
- Las pruebas reales en repositorios desechables (O1.3.1 a O1.3.4).
- El hardening previo al run real (O1.3.5).
- La autorización de un solo uso para el repositorio real (O1.3.R1.0).
- El primer run real documental (O1.3.R1).
- El ADR 0037 y la documentación de orquestación.

**Quedó fuera, de forma explícita:**

| Qué | Dónde queda |
|---|---|
| Consola para Claude, de cualquier forma | Descartada por diseño (ADR 0037 §4). No es un pendiente |
| Perfil `code` con ejecutor real | Prohibido |
| Push, PR y merge desde el runner | O1.4 y decisión humana |
| Exponer `ClaudeExecutor` en la consola o en `Start-ElsaBlock.ps1` | Sin decisión; no se hizo |
| Las 3 pruebas que fallan en Windows y los errores de `mypy` en Windows | Bloque aparte |
| `src/elsa`, Render, Supabase, SAP, Materiales, BOM y migraciones | No se tocan |

## 3. Estado inicial

- **HECHO DEL REPOSITORIO.** O1.2 estaba cerrado formalmente (PR #60 y #61). El runner solo ofrecía un
  ejecutor que no hace cambios.
- **HECHO DEL REPOSITORIO.** El ADR 0036 §9 condicionaba un ejecutor real a demostrar el bloqueo.

## 4. Trabajo realizado

| Paso | Qué | Estado |
|---|---|---|
| O1.3.1 | Contrato de Claude Code 2.1.316 sin supervisión, en desechable | **Completado** |
| O1.3.2 | `ClaudeExecutor` en el runner y pruebas reales de procesos | **Integrado** (PR #62) |
| O1.3.3 | Pruebas negativas, en desechable | **Completado** |
| O1.3.4 | Consola acotada con hijo y nieto, en desechable | **Completado, con STOP de diseño** |
| O1.3.5 | Hardening previo a O1.3.R1 | **Integrado** (PR #63) |
| O1.3.R1, primer intento | Detenido antes de lanzar Claude | Barrera correcta |
| O1.3.R1.0 | Autorización de un solo uso para el repositorio real | **Cerrado formalmente** (PR #64) |
| O1.3.R1, segundo intento | Primer run real documental | **`verified_local`, integrado** (PR #65) |
| Este cierre | Documento de cierre y ADR 0037 aceptado | Al integrarse |

**Cronología, sin fusionar eventos distintos:**

1. **O1.3.1 y O1.3.3 (2026-11-01).** HECHO MEDIDO, en
   [`resultados-o1-3-1-y-o1-3-3.md`](orchestration/resultados-o1-3-1-y-o1-3-3.md): 53 ejecuciones en
   desechable, sin consola. Se midieron el contrato, el primer evento y las pruebas negativas; 6 variantes
   quedaron INCONCLUSO.
2. **O1.3.2, PR #62** (fusionado el 2026-11-02 a las 16:47 UTC, `5731826`). HECHO MEDIDO, en el mismo
   documento:
   - un cambio documental real, `verified_local` en 10,5 s;
   - timeout, Claude esperando, Ctrl+C y muerte del runner, todos con 0 procesos vivos;
   - repositorio real idéntico antes y después.
3. **O1.3.4 (2026-11-02).** HECHO MEDIDO, en [`resultados-o1-3-4.md`](orchestration/resultados-o1-3-4.md):
   la consola no se puede acotar. STOP antes de las pruebas de terminación con consola.
4. **O1.3.5, PR #63** (fusionado el 2026-11-02 a las 21:20 UTC, `c8c1a93`).
5. **Primer intento de O1.3.R1 (2026-11-02).** Detenido en su Fase B con `real_repo_not_authorized`.
6. **O1.3.R1.0, PR #64** (fusionado el 2026-11-03 a las 13:57 UTC, `64bf0d8`).
7. **Segundo intento de O1.3.R1 (2026-11-03).** `verified_local`, sobre la base `64bf0d8`.
8. **PR #65** (fusionado el 2026-11-03 a las 15:29 UTC). `main` quedó en
   `5f8e7577e490383e3f404323299b734048753603`.

Los PR, sus SHA y sus horas de merge salen de la API pública de GitHub.

## 5. Decisiones

| Decisión | Quién | Motivo |
|---|---|---|
| **DECISIÓN TOMADA:** Claude real en O1 no recibe consola: ni `Bash`, ni `PowerShell`, ni ninguna herramienta que ejecute comandos. Sin excepciones para comandos «seguros» | Juan, tras O1.3.4 | `Bash(<comando exacto>)` dejó ejecutar otros comandos y encadenarlos |
| **DECISIÓN TOMADA:** la prueba de hijo y nieto mediante consola queda **NO APLICABLE POR DISEÑO** | Juan | Sin consola no hay forma de lanzarlos. Los procesos internos de Claude Code ya se midieron en O1.3.2 |
| **DECISIÓN TOMADA:** el repositorio real sigue cerrado por defecto, y solo se abre con una autorización externa de un solo uso | Juan aprobó el diseño de O1.3.R1.0 | Es el «gate humano y cambio deliberado» del ADR 0037 §9 |
| **DECISIÓN TOMADA:** el runner deja 3 commits (especificación, contenido y evidencia) y no publica | Diseño del runner, sin cambios | El push y el merge siguen siendo humanos |
| **DECISIÓN TOMADA:** el ADR 0037 pasa de «propuesto» a «aceptado» en este cierre | Claude Code, para la revisión de Juan | Precedente del ADR 0036, aceptado en el cierre de O1.1. Justificación: §19 |

## 6. Pruebas

| Tipo | Dónde | Resultado |
|---|---|---|
| Pruebas reales de contrato y negativas | Desechable, Windows | **HECHO MEDIDO:** 53 ejecuciones; ver el documento de resultados |
| Pruebas reales de procesos | Desechable, Windows | **HECHO MEDIDO:** 0 procesos vivos en todas |
| Consola acotada | Desechable, Windows | **HECHO MEDIDO:** STOP; ver `resultados-o1-3-4.md` |
| Tests del runner con Claude falso (O1.3.5) | Windows y CI | **HECHO MEDIDO:** 699 aprobados en el árbol final del PR #63; CI en verde |
| Tests del runner con Claude falso (O1.3.R1.0) | Windows y CI | **HECHO MEDIDO:** 860 aprobados y 11 omitidos; suite completa 3.002 aprobados; ver su cierre |
| Run real sobre el repositorio ELSA | Windows | **HECHO MEDIDO:** `verified_local` (§8) |
| CI de la rama de O1.3.R1 | Linux | **HECHO MEDIDO:** run `41650917272` (push) y `41660475725` (PR #65), `success` |
| CI de `main` tras el merge del PR #65 | Linux | **HECHO MEDIDO:** run `41664433382` (push), `success` |

**No se ejecutó en este cierre:** ningún run del runner, ningún Claude real, ni una suite nueva. Este bloque es
solo documental.

## 7. Comandos relevantes

Validación, sin lanzar Claude:

```bash
python scripts/orchestrator.py validate O1.3.R1
```

El run real se lanzó con un driver temporal fuera del repositorio. Ese driver solo llamó a
`run_block(default_config(), "O1.3.R1", executor=ClaudeExecutor(), confirm=…)`, cuya aprobación aceptaba
únicamente la especificación con su huella exacta. El ejecutor real no está en la consola del runner.

## 8. Resultados

### O1.3.4 y la prohibición de consola

**HECHO MEDIDO** (`resultados-o1-3-4.md`).

- Con `--tools PowerShell`, el primer evento no tenía herramientas.
- Con `--tools Bash` y una regla de comando exacto, Claude ejecutó sin permiso `echo`, `pwd`, `ls`, `whoami`,
  `cat`, `git status` y `hostname`, y también encadenó el comando permitido con otro.

La consola no se puede acotar. Por eso Claude real en O1 **no tiene `Bash`, ni `PowerShell`, ni consola**.

### O1.3.5: hardening

**HECHO DEL REPOSITORIO**, en el ADR 0037 §4 y §8.

| Control | Qué hace |
|---|---|
| Sin consola | Lista literal de herramientas de archivos, independiente de `CLAUDE_TOOLS`, comprobada al importar el runner, al construir `--tools`, `--allowedTools` y `--disallowedTools`, y en el primer evento antes de la comparación exacta. El prefijo de los tests no admite opciones con guion |
| Revisión de daños en toda salida | Timeout, error, `blocked`, capacidad inesperada, `init` ilegible, salida excesiva, `structured_output` inválido, error al leer el log y Ctrl+C. Conserva el motivo de la parada y el resultado de la revisión |
| Prioridad de motivos | Daño en el repositorio, luego comando Git prohibido, luego configuración, luego motivo de la parada |
| `GIT_TRACE` | Lista cerrada de comandos Git de lectura. Una traza que no se llegó a leer no se da por limpia |
| Configuración de Claude Code | Por defecto denegada: usuario, proyecto y local, MCP y administrada (archivo, registro y caché remota) |
| Procesos | Job Object. Tras una excepción, el runner espera a que quede vacío o se detiene con `orphan_suspected` |

**Esto no es aislamiento de Windows.**

### Primer intento de O1.3.R1

**HECHO MEDIDO** (cierre de O1.3.R1.0, §3). **No ejecutó Claude.** Al ejecutar solo la barrera con la
configuración por defecto se obtuvo `real_repo_not_authorized`. **La barrera funcionó como estaba diseñada.**
No es un fallo funcional de Claude: el repositorio real estaba cerrado por diseño, y eso dio lugar a O1.3.R1.0.

### O1.3.R1.0

**HECHO DEL REPOSITORIO**, en
[`o1-3-r1-0-autorizacion-repositorio-real-cierre.md`](o1-3-r1-0-autorizacion-repositorio-real-cierre.md) y en
el ADR 0037 §9.

- **Qué es la autorización:** externa y de un solo uso, ligada a:
  - el repositorio exacto;
  - la base exacta;
  - la huella exacta de la especificación;
  - la rama y las rutas exactas;
  - `change: add`, `profile: docs`, `executor: claude` y `console: false`.
- **Sin autorización:** `ensure_not_real_repository` sigue rechazando el repositorio real antes que nada.
- **Base posterior al merge:** `64bf0d825ba871ebc66d14b9e69d6cc66d5c8df0`.

### O1.3.R1: el run real

**HECHO MEDIDO por la sesión operadora**, con los logs locales del run y el repositorio. La evidencia versionada
es [`orchestration/runs/O1.3.R1.md`](orchestration/runs/O1.3.R1.md).

| Dato | Valor |
|---|---|
| Resultado del runner | `verified_local` (también en la evidencia versionada) |
| Claude Code | `2.1.316` (también en la evidencia versionada) |
| Modelo observado | `claude-sonnet-5-5` |
| Duración del ejecutor | 11,3 s (también en la evidencia versionada) |
| Código de salida | `0` |
| `structured_output` | `done`, con el único archivo cambiado, coherente con Git |
| Coste informado por Claude Code | US$0,045 |

**Autorización de un solo uso.** HECHO MEDIDO.

- Especificación: `spec_sha256 = c09c8f879f419c1219083c85090961e97e09f5181b1a442b6df97ddcc8ce4bed`.
- La creó el operador por orden escrita de Juan. Lleva los 11 campos exactos del contrato, y el runner la
  validó antes del run.
- El runner la consumió antes de crear la copia: la carpeta de autorizaciones quedó vacía, y el archivo gastado
  conserva la huella del original.
- **Un segundo intento de carga dio `real_run_authorization_used`.**
- La autorización no se versiona.

**Primer evento.** HECHO MEDIDO.

| Campo | Valor |
|---|---|
| Eventos `init` | 1, con los 27 campos exactos |
| `permissionMode` | `dontAsk` |
| `mcp_servers` | ninguno |
| `additional_directories` | ninguno |
| `skills` y `slash_commands` | ninguno |
| `apiKeySource` | `none` |

**Herramientas.** HECHO MEDIDO.

- **Disponibles:** exactamente `Edit`, `Glob`, `Grep`, `Read`, `StructuredOutput` y `Write`. No había `Bash`,
  `PowerShell`, `WebFetch`, `WebSearch`, `Task` ni ningún MCP.
- **Usadas:** `Read` sobre la especificación, `Glob`, `Write` sobre el archivo autorizado y `StructuredOutput`.
- **Denegaciones:** ninguna.

**Commits de la rama `claude/o1-3-r1-first-real-doc-run`.** HECHO DEL REPOSITORIO:

| Commit | Padre | Único archivo |
|---|---|---|
| Especificación `061444cc05af756acdd140abeb85eee6b154ddb9` | `64bf0d825ba871ebc66d14b9e69d6cc66d5c8df0` | `A docs/orchestration/work/O1.3.R1.md` |
| Contenido `8623d100dd91aba7c4ea9508a438b69510ce5b79` | `061444c` | `A docs/orchestration/o1-3-r1-controlled-document.md` |
| Evidencia `6ea237d57efe1e243f0c53ccfb7c563984ba9819` | `8623d10` | `A docs/orchestration/runs/O1.3.R1.md` |

**Controles.** HECHO MEDIDO.

- **Pasaron**, porque `verified_local` los exige a todos:
  - alcance, y que los cambios sean exactamente las rutas autorizadas y nuevas;
  - foto del repositorio principal, `HEAD`, refs y `.git`;
  - archivos ignorados;
  - `GIT_TRACE`, con 5 comandos de lectura de la lista;
  - configuración de Claude Code;
  - primer evento y `structured_output`;
  - las tres pasadas de gitleaks;
  - limpieza de procesos;
  - carpetas de la bandeja y de autorizaciones;
  - copia y rama del bloque.
- **La revisión de daños no aplicó:** el run no se detuvo, y por eso su campo va vacío. No se registra como
  PASS.

**Procesos.** HECHO MEDIDO.

- **0 procesos atribuibles supervivientes.**
- El runner no marcó `orphan_suspected` ni `left_processes`.
- Había 12 `claude.exe` antes del run y 12 después, todos de otras sesiones del usuario.
- Al terminar no quedaba ningún proceso que referenciara el run.

**`main` y el remoto.** HECHO MEDIDO.

- `main` siguió limpio en `64bf0d8` durante todo el run.
- El operador hizo a mano el push solo de la rama, y `origin/main` no cambió.

### GitHub, revisión y merge

**HECHO MEDIDO.**

- La revisión de solo lectura previa al merge, sobre `6ea237d`, dio **PASS, con 0 bloqueantes y 0 importantes**.
- PR #65, con head `6ea237d`, fusionado por Juan.
- `main` quedó en `5f8e7577e490383e3f404323299b734048753603`, con el CI de `main` en verde.

## 9. Métricas

| Métrica | Valor | Método |
|---|---|---|
| Ejecuciones reales en desechable (O1.3.1 a O1.3.3) | 53 | Documento de resultados |
| Ejecuciones reales en desechable (O1.3.4) | 3 | `resultados-o1-3-4.md` |
| Runs reales sobre el repositorio ELSA | 1 | Esta sesión y la evidencia versionada |
| Archivos de contenido del run real | 1 | `git diff-tree` del commit de contenido |
| Procesos atribuibles supervivientes en el run real | 0 | Runner y listado de procesos antes y después |
| Coste informado por Claude Code | US$0,54 (O1.3.1 a O1.3.3), US$0,05 (O1.3.4) y US$0,045 (O1.3.R1) | Eventos `result` de Claude Code. No se sabe cómo se refleja en la suscripción |

## 10. Aportes de Claude Code

Sesión de Claude Code en la app de escritorio, con identificador `6db3917e-6734-4a42-a00c-505c8becaa1a`. El
identificador figura en las rutas de la propia sesión. La sesión hizo:

- las sondas y pruebas reales de O1.3.4;
- la implementación y documentación de O1.3.5 y O1.3.R1.0;
- la operación del run real;
- las revisiones previas al merge;
- este cierre.

`security-reviewer` revisó O1.3.5 dos veces y O1.3.R1.0 otras dos, siempre con PASS. Sus hallazgos se
corrigieron dentro de cada PR.

El Claude anidado del run real tuvo la sesión `cce55af2-7e82-4089-9850-a898a37e5123`, sin transcripción
guardada.

Para O1.3.1 a O1.3.3 y O1.3.2 no se dispone aquí de un identificador de sesión verificable. Sus resultados están
en el documento versionado.

## 11. Aportes de Codex

Nada que registrar.

## 12. Operaciones manuales y de PowerShell

- **Juan:** las órdenes de cada fase en la conversación, la creación de los PR #62 a #65 y sus merges.
- **El operador, por orden escrita de Juan:**
  - escribió la especificación y la autorización de O1.3.R1 fuera del repositorio;
  - lanzó el driver temporal;
  - hizo el push de la rama de O1.3.R1.

## 13. Incidentes

| Incidente | Qué se hizo |
|---|---|
| La consola no se puede acotar (O1.3.4) | STOP. Decisión de diseño: sin consola |
| El primer intento de O1.3.R1 se detuvo por `real_repo_not_authorized` | La barrera funcionó. Se diseñó e integró O1.3.R1.0 |
| En O1.3.5, un ajuste rompió 3 tests de versión antes del merge | Corregido en el mismo PR |
| En O1.3.R1.0, el documento de cierre contaba mal los tests nuevos | Corregido en el mismo PR. Son 53 tests nuevos |
| En el run real, un análisis de procesos del operador falló por un error de comillas | Repetido con un script. Sin efecto en el run |

## 14. Git

Todos los cambios de O1.3 entraron por PR revisado y fusionado por Juan. Nunca hubo push a `main`, force, tags
ni merge hecho por Claude.

## 15. Ramas

| Rama | PR |
|---|---|
| `claude/o1-3-2-ejecutor-claude` | #62 |
| `claude/o1-3-5-hardening-pre-r1` | #63 |
| `claude/o1-3-r1-0-real-repo-authorization` | #64 |
| `claude/o1-3-r1-first-real-doc-run` | #65 |
| `claude/o1-3-cierre` | Este cierre |

## 16. Commits

| Merge en `main` | PR |
|---|---|
| `5731826` | #62, O1.3.2 |
| `c8c1a93` | #63, O1.3.5 |
| `64bf0d8` | #64, O1.3.R1.0 |
| `5f8e757` | #65, O1.3.R1 |

Los 3 commits del run real están en §8.

## 17. Pull requests

Los PR #62, #63, #64 y #65 están fusionados, con el CI en verde. El de este cierre queda por crear y fusionar
por Juan.

## 18. Migraciones

Nada que registrar.

## 19. Estado operacional final

- **HECHO DEL REPOSITORIO.**
  - El runner lanza Claude Code real 2.1.316 en repositorios desechables.
  - En el repositorio real, solo con una autorización exacta de un solo uso para un run documental.
  - Sin consola y con perfil `code` prohibido.
  - El ejecutor real no está en la consola del runner.

**ADR 0037: de «propuesto» a «aceptado».** DECISIÓN TOMADA por Claude Code; queda aceptado cuando Juan haga el
merge.

- **Sus decisiones están implementadas y probadas:**
  - vocabulario;
  - solo documentación;
  - sin consola ni capacidades añadidas;
  - versión exacta y primer evento;
  - entorno cerrado;
  - comandos Git internos;
  - Claude no decide nada;
  - repositorio real cerrado por defecto, con autorización.

  Están en `scripts/orchestrator.py`, con tests en CI, y se ejercieron en el run real. Hay un detalle en la
  autorización: la carga y el remoto exacto se comprueban al empezar el run, y la comparación con la
  especificación y la base, después de las validaciones de solo lectura (ADR 0037 §9).
- **Sus dos acciones de «antes de O1.3.R1» tienen evidencia:**
  - **Hooks.** HECHO MEDIDO: la huella de `hooks/` del clon principal es igual a la foto del 2026-11-02, previa
    a O1.3.R1.0 y a O1.3.R1. Solo contiene el hook que genera pre-commit.
  - **Configuración administrada remota.** HECHO MEDIDO: no hay caché remota ni claves de política. La cuenta es
    personal, según declaró Juan. Sigue siendo detección, no prevención.
- **Sus riesgos residuales siguen declarados**, y eso no contradice la aceptación: el ADR los acepta de forma
  explícita.

## 20. Pendientes

| Pendiente | Responsable |
|---|---|
| **PENDIENTE, O1.4:** publicar la rama, leer CI y dar el enlace del PR desde el runner | Requiere autorización de Juan |
| **PENDIENTE, bloque aparte:** las 3 pruebas que fallan en Windows y los errores de `mypy` en Windows | Juan decide cuándo |
| **PENDIENTE, sin explicar:** 6 variantes de `Glob` y `Grep` que quedaron INCONCLUSO en O1.3.3 | Abierto, sin datos expuestos (ADR 0037 §11) |
| **PENDIENTE, del cierre de O1.2:** configuración global de Git, `.pyc` y cachés en carpetas toleradas, ediciones que conservan tamaño y fecha, limpieza parcial de logs, bloques que solo borran | Siguen como límites del runner. **INFERENCIA:** el perfil `docs` no ejecuta Python, así que los `.pyc` no le afectan |
| **PENDIENTE, opcional:** retirar las copias locales `o1-1`, `o1-3-2-impl`, `o1-3-5-hardening`, `o1-3-r1-0-auth` y `o1-3-r1`, los logs locales y el driver temporal | Juan, cuando quiera. No afectan a `main` |

## 21. Siguiente bloque

**O1.4: publicar la rama, leer CI y dar el enlace del PR desde el runner**, solo si Juan lo autoriza.

---

## Riesgos residuales

Todos estaban ya aceptados en el ADR 0037 §11. Ninguno es nuevo:

| Riesgo | Situación |
|---|---|
| Claude Code corre con el usuario de Windows | No resuelto; aceptado para documentación |
| Tiene acceso de red, el que requiere su servicio | No resuelto |
| Nada de esto constituye aislamiento de Windows | Declarado |
| La autorización local no está firmada | Aceptado: es un segundo control, no aislamiento |
| La copia comparte el `.git` común con el clon principal | Un daño se detecta, pero no se impide físicamente |
| Configuración administrada remota | Detección, no prevención |
| El push lo hace una persona a mano | Por diseño, hasta O1.4 |
| El merge es humano | Por diseño |

## Qué acredita O1.3

- Claude Code real puede operar mediante O1 sobre el repositorio ELSA real:
  - con autorización explícita de un solo uso;
  - en una copia de trabajo separada;
  - sin consola;
  - con alcance restringido;
  - con controles independientes;
  - con evidencia;
  - con revisión humana antes del merge.
- La cadena **especificación → autorización → runner → Claude real → controles → `verified_local` → rama →
  CI → revisión → merge** funcionó una vez en el repositorio real.

## Qué no acredita O1.3

- **Seguridad y ejecución:**
  - aislamiento de Windows;
  - que Claude ejecute código funcional;
  - el perfil `code`.
- **Automatización:**
  - push, PR, merge o despliegue automáticos;
  - O1.4.
- **Producto:**
  - RAG, Phi y `llama.cpp` en producción;
  - Render y Supabase;
  - SAP, Materiales y BOM;
  - la UX final de PAPELSA.

## Criterios de cierre

| Criterio | Resultado |
|---|---|
| Ejecutor real con protecciones demostradas | **Cumplido** (§8) |
| Timeout, Ctrl+C y muerte del runner sin procesos vivos | **Cumplido** en O1.3.2 |
| Consola: decisión tomada | **Cumplido:** sin consola, por diseño |
| Hardening previo al run real | **Cumplido** (PR #63) |
| Repositorio real cerrado por defecto y abierto solo con autorización de un uso | **Cumplido** (PR #64) |
| Primer run real `verified_local` con un solo archivo nuevo | **Cumplido** (PR #65) |
| Autorización consumida y segundo uso bloqueado | **Cumplido** |
| 0 procesos atribuibles supervivientes | **Cumplido** |
| `main` intacto durante el run, y cambios solo por PR | **Cumplido** |
| CI en verde en cada PR | **Cumplido** |
| ADR 0037 revisado | **Cumplido:** pasa a aceptado (§19) |
| Documento de cierre | **Este documento** |
| PR de cierre con CI verde y merge de Juan | **Se cumple al fusionar este cierre** |

## Regla de continuidad

O1.3 queda cerrado solo cuando este documento esté en `main` con los checks obligatorios en verde. Aun después,
O1.4 requiere autorización explícita de Juan.

## Veredicto

**O1.3 = CERRADO FORMALMENTE** cuando se integre este documento. El ejecutor Claude real existe, sin consola y
solo para documentación, e hizo un run real verificado sobre el repositorio ELSA con autorización de un solo
uso. **No es aislamiento de Windows**, y no automatiza ni el push, ni el PR, ni el merge.
