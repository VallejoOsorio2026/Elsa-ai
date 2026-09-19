# Cierre del subbloque 5.0.c.1 — Política determinista de ausencia e indisponibilidad

Documento de cierre redactado según
[el estándar de cierre de bloques](project/BLOCK_CLOSURE_STANDARD.md)
(`CLAUDE.md`, regla 26).

> **Qué cierra este documento y qué no.**
>
> Cierra **únicamente** el subbloque **5.0.c.1**: la política pura y
> determinista que traduce el resultado de una capacidad en un estado de
> respuesta, y las pruebas automáticas que la sostienen.
>
> **NO** cierra el subbloque 5.0.c. **NO** cierra el subbloque 5.0.b. **NO**
> cierra el Bloque 5.0. **NO** declara operativo el Piloto 0.1. **NO** cierra
> M8, que sigue abierto y normativamente bloqueante (§20).

Marcas de evidencia usadas, según el estándar: **HECHO MEDIDO**, **HECHO DEL
REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.

---

## 1. Objetivo

Convertir en **garantía automática de integración continua** la regla que
sostiene la seguridad del Piloto 0.1:

> «no encontrado» **no** es «no existe»

y distinguir, de forma probada, tres situaciones que desde el final de una
consulta se parecen mucho:

- **ausencia de evidencia** — la fuente respondió y no devolvió el código;
- **capacidad no disponible** — la fuente no respondió;
- **inventario no activo** — no había versión vigente que consultar.

Solo la primera es una ausencia. Las otras dos no lo son en absoluto: decirle
«no hay información» a un ingeniero que va a intervenir un equipo le hace
concluir que el dato no está, y esa conclusión sería nuestra, no suya.

Al terminar debía existir una **política ejecutable y probada**, no un
documento. Existe.

---

## 2. Alcance

### Entró

- Una pieza pura de dominio con la política de interpretación de resultados de
  capacidades.
- Tres avisos nuevos en el contrato de respuesta.
- Las pruebas automáticas A6, A6b, A18 y A19, más los casos derivados.

### Quedó explícitamente fuera

- La **fachada contractual Materiales–ELSA**.
- El adaptador real de `MaterialsPort`.
- Cualquier consulta a Materiales.
- La representación de frontera del código SAP y `canonical_sap_code`.
- M3 y M5, que siguen bloqueados por pruebas externas.
- Todo endpoint HTTP, incluido el del asistente.
- Frontend, base de datos, migraciones y Supabase.
- El plan de capacidades completo.
- El hilo ONNX/INT8.
- `response_ref`, Incident Snapshot, persistencia, observabilidad HTTP,
  `release_id`, lista blanca de logging y acceso al manual: pertenecen a
  trabajos posteriores de 5.0.c.

> **No se implementó `MaterialsPort`, ni la fachada, ni ningún endpoint.**
> Esta afirmación es verificable: el diff del subbloque son tres archivos
> (§14).

---

## 3. Estado inicial

**HECHO DEL REPOSITORIO.** Punto de partida: `origin/main` en
`d3056193a684a3e19db4f3eb03acaf27302add91`
(«Merge pull request #22 … ADR 0022»).

Lo que **existía**:

- `AnswerStatus`, `Sufficiency`, `AnswerWarning`, `Citation`, `AnswerAudit` y
  `GroundedAnswer` en `src/elsa/core/answers.py`.
- `GroundedGenerationService`, con el precedente explícito de que «un fallo del
  proveedor es `ERROR`, jamás `NO_EVIDENCE`».
- [ADR 0020](adr/0020-capacidades-componibles-y-planes-de-ejecucion.md) §12 y
  §13, [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §5, §6, §8
  y §13, y [ADR 0022](adr/0022-feedback-e-incident-snapshot-del-piloto.md) §19,
  todos en `main`.
- El [manual del observador](piloto-0-1/manual-del-observador.md) con la
  advertencia sobre ausencia ya escrita.

Lo que **no existía**:

- Ninguna prueba de ausencia segura. **HECHO MEDIDO**: `code_not_found_in_source`
  y `NOT_RETURNED` no aparecían en `src/` ni en `tests/`.
- Ningún aviso para capacidad caída, inventario sin versión activa o código no
  devuelto.
- Ninguna pieza que tradujera un resultado de capacidad en un estado de
  respuesta.

---

## 4. Trabajo realizado

En orden, y en orden **test-first**:

1. **Inspección previa** de `core/answers.py`, `core/generation_policy.py`,
   `services/grounded_generation.py`, los avisos existentes, las pruebas de
   `AnswerStatus` y los ADR 0017, 0020, 0021 y 0022, para decidir si ya existía
   una pieza de dominio donde alojar la política.
2. **Descarte razonado** de las candidatas existentes (§5, D1).
3. **Escritura de las pruebas primero**, antes de cualquier implementación.
4. **Comprobación del rojo inicial** (§6).
5. **Ampliación del contrato de respuesta** con tres avisos.
6. **Implementación de la pieza mínima de dominio.**
7. **Verde, verificaciones completas, revisión del diff, commit, PR #23 y
   merge.**

---

## 5. Decisiones

Todas son **DECISIÓN TOMADA**. Las de garantía (D2 a D7) las fijó el
responsable del proyecto en las instrucciones del subbloque; las de forma (D1,
D8, D9) las propuso Claude Code y se entregaron revisadas.

### D1 — Pieza de dominio nueva, no reutilizada

Se creó `src/elsa/core/capability_outcomes.py` en vez de alojar la política en
una pieza existente. Motivo, tras inspeccionarlas:

- `core/generation_policy.py` es el **prompt del sistema** para el LLM, otra
  cosa pese al nombre.
- `services/grounded_generation.py` es un **servicio** con entrada y salida y
  dependencias de puertos; la política debía ser pura.
- `core/answers.py` es el **contrato de la respuesta**, no la política que
  decide un estado.

Lo que sí se reutilizó fue el **razonamiento** ya asentado en
`grounded_generation`: un fallo del proveedor es `ERROR`, jamás `NO_EVIDENCE`.
Esta política aplica esa misma distinción a las capacidades.

### D2 — A6, capacidad externa indisponible

| Situación | Resultado |
|---|---|
| `UNAVAILABLE` **+ otra evidencia útil** | `PARTIAL` + `capability_unavailable` |
| **Solo** `UNAVAILABLE` | `ERROR` + `capability_unavailable` |

La información útil de otras capacidades **no se descarta** por una que falló.

### D3 — A6b, `NOT_RETURNED` no autoritativo

`OK` + `NOT_RETURNED` + `authoritative = false`, consulta directa y sin otra
evidencia → **`NO_EVIDENCE` + `code_not_found_in_source`**.

**Nunca se convierte en «el material no existe».** Junto a otros hechos
resueltos, el mismo caso produce `PARTIAL` con el mismo aviso.

### D4 — A18, redacción sin afirmaciones negativas autoritativas

La política **no genera lenguaje factual autoritativo negativo** para una
ausencia no autoritativa. La redacción es **única y determinista**; ningún LLM
interviene.

**No se usa una prohibición ingenua de la palabra «existe».** Lo que importa es
la semántica completa de la frase: «este resultado no permite concluir si el
material existe» debe seguir siendo decible, y «el material no existe» no. La
guarda lee **frase a frase**, reconoce marcas de salvedad y solo marca una
frase que afirme sin ellas.

### D5 — A19, inventario sin versión activa

| Situación | Resultado |
|---|---|
| **Solo** `NO_ACTIVE_INVENTORY` | `ERROR` + `inventory_unavailable` |
| En composición **con evidencia útil** | `PARTIAL` + `inventory_unavailable` |

**Nunca** `NO_EVIDENCE`, y **nunca** `code_not_found_in_source`.

### D6 — `REJECTED` no se compone

Un rechazo de autorización **no se compone como evidencia válida**: se resuelve
antes, en la cadena de confianza. La política **falla de forma explícita** en
lugar de inventar un estado.

### D7 — La ausencia autoritativa permanece rechazada

Un resultado con `absence_is_authoritative = true` **no es interpretable** y se
rechaza mientras **M8 siga abierto**. Impide que nadie emita hoy una
inexistencia atribuida por accidente.

### D8 — Fallar antes que adivinar

Un `OK` sin resultado también se rechaza. Un resultado que la política no sabe
leer **no puede convertirse en un `NO_EVIDENCE` por descarte**, que es justo el
error que el módulo existe para impedir.

### D9 — Naturaleza de la capa

La política es **pura, determinista y auditable**: sin HTTP, sin SQL, sin JWT,
sin LLM, sin inventario y sin representación de código SAP.

**No existe en esta capa ningún agente autónomo, ningún SQL generado por un
modelo y ninguna decisión probabilística.** Toda la salida se deriva de los
valores de entrada.

### Sobre ADR

**No se escribió ningún ADR nuevo.** Este subbloque **no toma** decisiones
arquitectónicas propias: **implementa** las ya registradas en ADR 0017 §
`AnswerStatus`, ADR 0020 §12 y §13, y ADR 0021 §5, §6, §8 y §13. El requisito
de estas pruebas estaba ya escrito en ADR 0022 §19.

**ADR 0022 no fue modificado.**

---

## 6. Pruebas

**HECHO MEDIDO.** Todo lo de esta sección se ejecutó y se observó su salida.

### Rojo inicial

Las pruebas se escribieron **antes** que la implementación, y fallaron por lo
que faltaba:

```text
ImportError while importing test module '/home/user/Elsa-ai/tests/test_absence_safety.py'.
E   ModuleNotFoundError: No module named 'elsa.core.capability_outcomes'
```

Faltaban: la política de interpretación y los tres avisos.

### Cobertura de las garantías

| Caso | Entrada | Resultado esperado y obtenido |
|---|---|---|
| **A6.1** | `UNAVAILABLE` + otras evidencias | `PARTIAL` + `capability_unavailable` |
| **A6.2** | `UNAVAILABLE` única capacidad | `ERROR` + `capability_unavailable` |
| **A6b** | `OK` + `NOT_RETURNED` + `authoritative=false`, sin más | `NO_EVIDENCE` + `code_not_found_in_source` |
| **A6b-bis** | ídem, junto a otros hechos resueltos | `PARTIAL` + `code_not_found_in_source` |
| **A6b-msg** | mensaje de esa ausencia | contiene «no devolvió» y no afirma inexistencia |
| **A18-a** | 8 negaciones autoritativas | la guarda **las detecta** |
| **A18-b** | 4 redacciones seguras con el mismo vocabulario | la guarda **no las marca** |
| **A18-c** | afirmación seguida de salvedad | detectada: la salvedad no legitima la frase anterior |
| **A18-d** | las 8 combinaciones alcanzables de la política | ningún mensaje afirma inexistencia |
| **A19.1** | `NO_ACTIVE_INVENTORY` única capacidad | `ERROR` + `inventory_unavailable` |
| **A19.2** | ídem + otras evidencias | `PARTIAL` + `inventory_unavailable` |
| **REJECTED** | con y sin otras evidencias | excepción explícita |
| **Autoritativa** | `NOT_RETURNED` + `authoritative=true` | excepción explícita |
| **Base** | `MATCHED` | `ANSWERED`, sin avisos de ausencia |
| **Malformado** | `OK` sin resultado | excepción explícita |

La guarda A18 se comprueba **en las dos direcciones**, de modo que no puede
volverse vacua en silencio: si alguien la debilitara, los ocho casos de
negación fallarían.

### Qué se ejecutó

- **34 pruebas nuevas**, todas **activas**: sin `skip`, sin `xfail`, sin
  `noqa`, sin `type: ignore`.
- **Suite completa.**
- Ruff, mypy, pre-commit y gitleaks.

**No se omitió ninguna prueba en silencio.** Los 230 casos omitidos de la suite
son preexistentes y requieren una base PostgreSQL (`ELSA_TEST_DATABASE_URL`).

---

## 7. Comandos relevantes

Lo que otra persona necesitaría para reproducir la verificación:

```bash
# Pruebas del subbloque
uv run pytest tests/test_absence_safety.py -q

# Suite completa
uv run pytest -q

# Lint, formato y tipos
uv run ruff check .
uv run ruff format --check .
uv run mypy

# Ganchos locales, incluido gitleaks
uv run pre-commit run --files \
  src/elsa/core/capability_outcomes.py \
  src/elsa/core/answers.py \
  tests/test_absence_safety.py

# Alcance del cambio
git diff --stat d3056193 93a661f
git log --oneline d3056193..93a661f
```

---

## 8. Resultados

**HECHO MEDIDO.** Salida real, sin parafrasear, de la ejecución de los comandos
de §7 sobre un árbol limpio en `93a661f`. La duración que imprime `pytest`
varía entre ejecuciones; el resto de las salidas es estable.

`uv run pytest tests/test_absence_safety.py -q`:

```text
34 passed, 2 warnings in 0.10s
```

`uv run pytest -q`:

```text
1175 passed, 230 skipped, 3 warnings in 37.22s
```

`uv run ruff check .`:

```text
All checks passed!
```

`uv run ruff format --check .`:

```text
289 files already formatted
```

`uv run mypy`:

```text
Success: no issues found in 212 source files
```

`uv run pre-commit run --files …`:

```text
trim trailing whitespace.................................................Passed
fix end of files.........................................................Passed
check yaml...........................................(no files to check)Skipped
check toml...........................................(no files to check)Skipped
check for merge conflicts................................................Passed
check for added large files..............................................Passed
detect private key.......................................................Passed
ruff check...............................................................Passed
ruff format..............................................................Passed
Detect hardcoded secrets.................................................Passed
exit=0
```

`git diff --stat d3056193 93a661f`:

```text
 src/elsa/core/answers.py             |  23 ++++
 src/elsa/core/capability_outcomes.py | 249 +++++++++++++++++++++++++++++++++++
 tests/test_absence_safety.py         | 249 +++++++++++++++++++++++++++++++++++
 3 files changed, 521 insertions(+)
```

---

## 9. Métricas

**HECHO MEDIDO.** Cifras y el método por el que se obtuvieron.

| Métrica | Valor | Método |
|---|---|---|
| Pruebas nuevas | **34** | `uv run pytest tests/test_absence_safety.py -q` |
| Suite completa | **1175 passed, 230 skipped, 3 warnings** | `uv run pytest -q` sobre un árbol limpio en `93a661f` |
| Omitidas atribuibles a este cambio | **0** | Los 230 son preexistentes y requieren PostgreSQL |
| Archivos cambiados | **3** | `git diff --numstat` y la API del PR, por separado |
| Líneas insertadas | **521** | ídem |
| Líneas borradas | **0** | ídem |
| `capability_outcomes.py` | 249 líneas | `git diff --numstat` |
| `test_absence_safety.py` | 249 líneas | ídem |
| Ampliación de `answers.py` | 23 líneas | ídem |
| Avisos añadidos | **3** | `capability_unavailable`, `inventory_unavailable`, `code_not_found_in_source` |
| `AnswerStatus` añadidos | **0** | Siguen siendo cuatro |
| Ruff, mypy, pre-commit, gitleaks | Verde | §8 |
| Checks de CI del PR #23 | **4 de 4 success** | API de check runs sobre `0988894f…` |
| Commits del subbloque | **1 funcional** + 1 de fusión | `git log d3056193..93a661f` |
| Árbol tras el merge | **limpio** | `git status --porcelain` → 0 líneas |
| `HEAD` local = `origin/main` | **sí** | `git rev-parse` sobre ambos |

No hay métricas de latencia ni de calidad de respuesta: **esta capa no ejecuta
ninguna capacidad**, solo interpreta un resultado ya obtenido.

---

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO.**

- Inspección previa del repositorio y descarte razonado de las piezas
  existentes (§5, D1).
- Redacción de las 34 pruebas **antes** de la implementación, y registro del
  rojo inicial.
- Implementación de `capability_outcomes.py` y de los tres avisos.
- Ejecución de todas las verificaciones de §6 y §8.
- Commit, apertura del pull request #23 y merge.
- Redacción de este documento de cierre.

**Identificador de sesión.** Se dispone de uno y es **verificable desde el
repositorio**: el commit funcional `0988894f…` lleva el trailer
`Claude-Session: https://claude.ai/code/session_012TwjwTEJBnMFuL41GrdrtK`,
comprobable con `git log -1 --format=%b 0988894f`.

**Revisión.** El responsable del proyecto fijó por escrito, antes de empezar,
las garantías D2 a D7, el límite de alcance y la exigencia de orden test-first,
y revisó el resultado antes de autorizar el PR y el merge.

**Inconsistencias reportadas por Claude Code** (regla 19), todas entregadas en
la conversación antes de cerrar:

1. **El aviso de A6.2.** El encargo pedía `ERROR` + `capability_unavailable`
   para una capacidad única caída, mientras que ADR 0020 §13 registra esa fila
   como `ERROR` **sin aviso**. Se emitió el aviso: un `ERROR` mudo no
   permitiría distinguir después una caída de capacidad de un fallo del modelo.
   **Precisa el ADR, no lo contradice, y no se modificó ningún ADR.**
2. **La ausencia autoritativa.** ADR 0020 §13 contempla esa fila, pero el
   contrato funcional mantiene A6c desactivada mientras M8 siga abierto. Se
   optó por rechazarla (D7).
3. **`MATCHED` → `ANSWERED` sin degradación por vigencia ni cobertura.** Esa
   degradación depende del plan, no del resultado, y quedaba fuera de alcance.
   Queda documentado en el propio código.

---

## 11. Aportes de Codex

**Nada que registrar.** Codex **no se utilizó** en este subbloque. No se
dispone de ninguna sesión suya porque no la hubo.

---

## 12. Operaciones manuales y de PowerShell

**Nada que registrar.** No se ejecutó ningún script de PowerShell, ningún
comando fuera del repositorio, ninguna comprobación en un panel, ningún
servicio local y ninguna medición sobre archivos externos. Todo el trabajo del
subbloque ocurrió dentro del repositorio y está en §7 y §8.

---

## 13. Incidentes

Dos, ambos menores y resueltos durante el trabajo. **HECHO MEDIDO.**

1. **`ruff format` pidió compactar una línea** de `capability_outcomes.py` que
   se había escrito partida en varias. Se aplicó el formateador; la línea
   resultante mide 97 caracteres, dentro del límite de 100 del proyecto. Se
   reejecutaron `ruff check` y `ruff format --check`, ambos en verde.
2. **El rojo inicial fue un fallo de importación**, no de aserción, porque el
   módulo aún no existía. Es el resultado esperado de escribir las pruebas
   primero, y se registró como tal (§6).

**Ningún incidente quedó pendiente.**

---

## 14. Git

**HECHO DEL REPOSITORIO.**

Base del subbloque: `d3056193a684a3e19db4f3eb03acaf27302add91`.

Archivos tocados, y **solo** estos tres:

| Archivo | Cambio |
|---|---|
| `src/elsa/core/answers.py` | modificado, +23 |
| `src/elsa/core/capability_outcomes.py` | creado, +249 |
| `tests/test_absence_safety.py` | creado, +249 |

**3 files changed, 521 insertions(+), 0 deletions(-).**

No se tocó `docs/`, `supabase/`, `web/` ni `bench/`. No se tocaron ADR 0020,
ADR 0021, ADR 0022, el contrato funcional ni `CLAUDE.md`.

---

## 15. Ramas

| Rama | Uso |
|---|---|
| `feat/5-0-c-1-absence-safety` | Rama de trabajo del subbloque. Creada desde `d3056193…`, fusionada en `main` por el PR #23 |
| `docs/cierre-5-0-c-1` | Rama de este documento de cierre. Creada desde `93a661fe…` |

**Ninguna rama abandonada.** Ninguna rama borrada.

---

## 16. Commits

| Hash | Tipo | Mensaje |
|---|---|---|
| `0988894f52d787901634dfa8003af435f35f64fb` | funcional | `feat(core): make safe absence a tested guarantee` |
| `93a661fe60b93dce0e3830b51255ac089fb70d28` | fusión | `Merge pull request #23 …` |

El commit de fusión tiene dos padres: `d3056193a684a3e19db4f3eb03acaf27302add91`
y `0988894f52d787901634dfa8003af435f35f64fb`.

**Un solo commit funcional.** No hubo amend ni reescritura de historia.

---

## 17. Pull requests

| PR | Estado | CI |
|---|---|---|
| **#23** — `feat(core): enforce safe capability absence semantics` | **merged** | **4 de 4 success** |

**HECHO MEDIDO**, sobre el HEAD `0988894f…`:

| Check | Evento | Conclusión |
|---|---|---|
| Lint, types and tests | `pull_request` | **success** |
| Secret scan (gitleaks) | `pull_request` | **success** |
| Lint, types and tests | `push` | **success** |
| Secret scan (gitleaks) | `push` | **success** |

Merge con **commit de fusión**, sin squash ni rebase, con `expectedHeadSha`.
Sin reviews y sin comentarios.

---

## 18. Migraciones

**Nada que registrar.** Este subbloque **no escribió ninguna migración y no
aplicó ninguna**. No se tocó ningún proyecto Supabase, ni DEV ni TEST, y por
tanto no hizo falta ninguna autorización de las que exige la regla 15.

---

## 19. Estado operacional final

| Pieza | Estado |
|---|---|
| Política de ausencia e indisponibilidad | **Funciona y está probada** |
| Tres avisos del contrato de respuesta | **Disponibles** |
| Pruebas A6, A6b, A18, A19 | **Activas en CI** |
| Conexión con Materiales | **No conectada.** No existe fachada ni adaptador |
| Camino HTTP | **No conectado.** Ningún endpoint devuelve estos estados |
| Plan de capacidades | **No existe** |
| Feedback, Incident Snapshot, manual en la interfaz | **No existen** |

**INFERENCIA.** Que la política esté probada no significa que ELSA emita hoy
estos estados a un usuario: **no hay ningún camino HTTP que la invoque**. Lo
que queda garantizado es que, cuando lo haya, la traducción ya está decidida y
cualquier regresión rompe una prueba. Esta afirmación se deduce de §2 y §19 y
**no se comprobó** ejecutando el sistema extremo a extremo, porque el camino no
existe.

---

## 20. Pendientes

| # | Pendiente | Responsable |
|---|---|---|
| **P1** | **M8 continúa ABIERTO y normativamente BLOQUEANTE.** Este subbloque no lo cierra ni lo modifica; aporta el control compensatorio nº 3 del riesgo R2 | Responsable del proyecto, con ADR posterior |
| **P2** | **El subbloque 5.0.c continúa ABIERTO** | Responsable del proyecto |
| **P3** | Feedback, `response_ref`, Incident Snapshot, persistencia, interfaz y acceso al manual, y observabilidad HTTP: **trabajos posteriores de 5.0.c** | Siguientes subpasos |
| **P4** | **D20 continúa ABIERTO** y es **puerta previa a liberar** | Responsable del proyecto |
| **P5** | **El subbloque 5.0.b continúa ABIERTO.** M3 y M5 siguen bloqueados por pruebas externas | Responsable del proyecto |
| **P6** | La degradación por vigencia y por cobertura no vive en esta política: depende del plan | Subpaso posterior |

**Ningún resultado posterior de M3 o de M5 entra en este documento.** Lo que
esas mediciones produzcan pertenece al cierre del subbloque 5.0.b, no a este.

---

## 21. Siguiente bloque

El siguiente paso permitido es **continuar el subbloque 5.0.c** por el orden ya
acordado, cuyo primer elemento pendiente es el identificador de versión
desplegada (`release_id`) y, en paralelo, `response_ref` en la respuesta del
asistente. Ambos son aditivos y de riesgo bajo.

**No se autoriza aquí** iniciar M8, cerrar 5.0.c, cerrar 5.0.b, cerrar el
Bloque 5.0 ni declarar operativo el Piloto 0.1. Cada uno de esos pasos exige su
propia autorización y su propio documento de cierre.
