# Cierre de M1-A — Contrato esperado ejecutable en ELSA

> **M1-A = CERRADO Y DOCUMENTADO.**
>
> **Esto cierra M1-A, no M1.** M1 sigue **ABIERTO** y bloqueante: la fachada
> contractual no existe, no está solicitada, y el adaptador real tampoco
> existe. Este subbloque convierte la norma ya aprobada en una
> especificación ejecutable **del lado consumidor**, y nada más.

- Bloque: 5.0, subbloque **M1-A**, punto **M1**
- Fecha: **2026-09-21**
- Documento exigido por la regla 26 de [`CLAUDE.md`](../CLAUDE.md), conforme
  a [`BLOCK_CLOSURE_STANDARD.md`](project/BLOCK_CLOSURE_STANDARD.md)

---

## 1. Objetivo

Que ELSA disponga de una **especificación ejecutable y probada** de lo que
espera del contrato Materiales–ELSA, **sin disponer todavía de un
proveedor real**.

Dicho de otro modo: que las decisiones de
[ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md),
[ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
y [ADR 0027](adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
dejen de ser prosa que nadie cumple ni incumple, y pasen a ser invariantes
que **rompen la suite** cuando se violan.

Y, de paso pero no accesoriamente, que desaparezca la deuda **D2**: la
semántica heredada `None = «el material no existe»`.

## 2. Alcance

### 2.1 Lo que entró

1. **ADR 0028**, que resuelve la decisión humana **H4** y la fila 8 de las
   decisiones diferidas de
   [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §22.
2. **`MaterialsPort` retipado** conforme a
   [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §14.
3. **Eliminación de la deuda D2** en las tres ubicaciones donde vivía.
4. **Tipos del resultado contractual**, propios del puerto.
5. **Fake determinista de la fachada esperada.**
6. **62 pruebas de conformidad del consumidor**, incluidas las negativas.
7. **Actualización mínima de `docs/architecture.md`.**
8. **Este documento** y el registro mínimo de estado.

### 2.2 Lo que quedó explícitamente fuera

| Fuera de alcance | Por qué |
|---|---|
| **El repositorio de Materiales** | **H5 no autorizada.** No se creó allí SQL, funciones, descriptor, `contract_version`, tests, CI ni documentación contractual |
| **El enlace de transporte** | **H3 pendiente.** No se eligió entre RPC/PostgREST, endpoint HTTP propio ni otro mecanismo |
| **El adaptador real** | Depende de H3 y de que la fachada exista |
| **M4 operativo** | No se calcula vigencia, no se implementa `requires_fresh_inventory`, no se emite `inventory_freshness_unknown`, no se tocó `AnswerWarning` |
| **M6 operativo** | El fake **transporta** los campos; no implementa agregación, clasificación, frescura ni búsqueda |
| **M8** | Sigue abierto, con su criterio de cierre intacto y sin cumplir |
| **Búsqueda por texto libre** | Fuera del Piloto 0.1 inicial ([ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §2, §22 fila 12) |
| **`config.py`, `container.py`, `core/health.py`, `scripts/`, `web/`, SQL, Supabase** | Prohibidos en M1-A. No se tocó ninguno |
| **D20, ONNX, Modo ELSA, embeddings, ZIAA, BOM** | Ningún frente se avanzó |

## 3. Estado inicial

**HECHO DEL REPOSITORIO.**

| | |
|---|---|
| Base | `origin/main` = `dd0634b20dfc1b6bc1178d63835d61ad2eea7480` |
| Último commit de la base | `Merge pull request #37 from VallejoOsorio2026/docs/m4-normativo-cierre-final` |
| Working tree al empezar | Limpio |
| Rama creada | `claude/upbeat-turing-4bppro` (impuesta por la sesión; ver §15) |
| Numeración ADR libre | **0028**, verificada: el último existente era 0027 |

`origin/main` **no había avanzado** desde el SHA declarado, comprobado con
`git log dd0634b..origin/main`, que devolvió vacío.

### 3.1 Qué existía

- La **política del consumidor**, completa y probada:
  `CapabilityCallStatus`, `CapabilityOutcome`, `InventoryLookupResult`,
  `interpret_inventory_lookup` (`core/capability_outcomes.py`) e
  `InventoryCoverageState`, `CoverageRequirement`, `decide_under_coverage`
  (`core/coverage_policy.py`).
- Las pruebas **A6, A6b, A18, A19, A20, A20b, A21, B9a, B9b** activas.
- Las tres decisiones normativas (ADR 0021, 0025, 0027), cerradas.

### 3.2 Qué no existía

- Ningún tipo del **transporte** del contrato: `contract_version`,
  descriptor, `match_origin`, `stock_locations`, `attribution`,
  `snapshot_sensitive`, bloque `inventory`, clases de procedencia. **Cero
  apariciones** en `src/` y en `tests/`.
- Ningún **consumidor** de `MaterialsPort`. **HECHO DEL REPOSITORIO:**
  `git grep` no encontraba ninguno fuera del puerto, su fake y su prueba.
- La fachada, el adaptador, el descriptor real y las pruebas del proveedor.

## 4. Trabajo realizado

En orden.

1. **Precheck.** `git fetch origin`, verificación de `origin/main`, árbol
   limpio, numeración ADR.
2. **Comprobación arquitectónica previa, que podía detener el trabajo.**
   Antes de escribir una línea se verificó que importar
   `CapabilityCallStatus` y `CapabilityOutcome` desde `core` dentro de
   `ports` no rompiera ninguna regla vigente ni creara un ciclo (§5.1).
3. **Retipado de `src/elsa/ports/materials.py`**: vocabularios propios,
   bloques del sobre, tipos de resultado, invariantes y el `Protocol`.
4. **Reescritura de `src/elsa/adapters/fake_materials.py`** como fake de la
   fachada esperada.
5. **Actualización de `src/elsa/ports/__init__.py`.**
6. **Reescritura completa de `tests/test_contract_materials.py`.**
7. **Validación focal**, luego **completa**: pytest, ruff, format, mypy,
   `git diff --check`.
8. **ADR 0028** y este documento.
9. **Control de alcance** (§7 de la secuencia; resultados en §19.2).

## 5. Decisiones

### 5.1 La comprobación que habilitó H4

**HECHO MEDIDO.** La instrucción del subbloque exigía detenerse si reutilizar
los tipos del núcleo dentro de `ports` rompía una regla arquitectónica o
creaba un ciclo. Se comprobaron las dos cosas:

```
=== ¿ports importa de core hoy? ===
  src/elsa/ports/documents.py:32:from elsa.core.authorization import Scope
  src/elsa/ports/documents.py:33:from elsa.core.versioning import ChangeKind
  src/elsa/ports/evidence.py:14:from elsa.core.authorization import Scope
  src/elsa/ports/vectors.py:22:from elsa.core.authorization import Scope
  src/elsa/ports/knowledge.py:31:from elsa.core.matching import MatchCandidate
  src/elsa/ports/knowledge.py:32:from elsa.core.reconciliation import ReconciliationEntry
  src/elsa/ports/knowledge.py:33:from elsa.core.review import ReviewDecision, ReviewSubject

=== cierre transitivo desde core.capability_outcomes y core.coverage_policy ===
   elsa.core.answers
   elsa.core.capability_outcomes
   elsa.core.coverage_policy

  MODULOS DE ports/ ALCANZADOS: NINGUNO -> sin ciclo posible
```

**Conclusión: no hay incompatibilidad.** `ports/` ya importa de `core/` en
cuatro módulos, y los tres módulos implicados no alcanzan `elsa.ports`. H4
se implementó sin desviación y sin volver a preguntar.

### 5.2 Decisiones tomadas en el subbloque

| # | Decisión | Motivo | Dónde queda |
|---|---|---|---|
| **D1** | Reutilizar `CapabilityCallStatus`, `CapabilityOutcome` e `InventoryCoverageState` sin envolverlos ni traducirlos | **H4.** Dos vocabularios para lo mismo divergen en silencio | ADR 0028 §5 |
| **D2** | Declarar solo los vocabularios **sin equivalente**: `MatchOrigin`, `AbsenceReason`, `FieldProvenance` | Reproducen literalmente los de sus ADR de origen | ADR 0028 §6 |
| **D3** | Un sobre `MaterialsLookupResult` con los tres ejes separados | Un enum plano obligaría a elegir entre verdades simultáneas | ADR 0028 §8 |
| **D4** | Hacer **inconstruibles** las combinaciones que el contrato prohíbe, validando al construir | Un invariante que no se comprueba no es un invariante | ADR 0028 §8 |
| **D5** | **Eliminar `MaterialsUnavailableError`** | Su significado es el desenlace normal 4, que [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §14 prohíbe modelar como excepción. Conservarla dejaría dos caminos para el mismo hecho, uno prohibido. No tenía consumidores | ADR 0028 §9 |
| **D6** | **Eliminar `search_materials`** del puerto | La búsqueda por texto está fuera del Piloto 0.1 inicial, y no se construye por anticipación (regla 23) | ADR 0028 §20 |
| **D7** | **Añadir `get_inventory_status`** | [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §2 la declara **obligatoria en V1** | ADR 0028 §7 |
| **D8** | **Modelar la forma del descriptor**, sin conectarlo a red ni a configuración | §2 lo declara obligatorio en V1 y §15.3 lo hace el mecanismo por el que la versión «nunca se adivina». Sin él, esa regla no se puede escribir como prueba. Cuesta dos *dataclasses* y no toca nada | §5.3 |
| **D9** | `NullSense` + `NULL_SENSES` como **tabla paralela**, nunca como campo del payload | Hace ejecutable [ADR 0027](adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md) §6.2 sin cruzar el límite de su §12, que reserva el campo de disponibilidad para un ADR futuro | ADR 0028 §18 |
| **D10** | Mantener todos los tipos en `ports/materials.py` | `ports/knowledge.py` (637 líneas) ya usa ese patrón. Crear una capa nueva no aportaba nada | ADR 0028 §23 |
| **D11** | No mover la frontera de `REJECTED` | Ya está resuelta en la capa correcta: la composición lanza `UncomposableOutcomeError`. Forzarla dentro del puerto habría duplicado una decisión tomada | ADR 0028 §13 |

### 5.3 Justificación exigida sobre el descriptor

La instrucción pedía justificar si modelar la forma de `contract_version` y
del descriptor ampliaba el alcance innecesariamente. **No lo amplía, y
omitirlo habría dejado un hueco:**

- [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §2 declara
  `get_contract_descriptor` **obligatoria en V1**, no opcional.
- Su §15.3 lo convierte en el mecanismo por el que ELSA sabe qué versión
  consume, con la regla dura **«nunca se adivina»**. Sin la forma, esa regla
  no puede escribirse como prueba, y M1-A existe precisamente para eso.
- **Lo que se prohibía era conectarlo**, y no se conectó: no hay red, no hay
  lectura de configuración, no hay estado de salud, y el enlace de
  transporte es un rótulo inerte porque **H3 sigue pendiente**.

### 5.4 Decisiones arquitectónicas registradas como ADR

**ADR 0028** (regla 25). Ninguna otra decisión de este subbloque alcanza el
umbral de ADR.

## 6. Pruebas

**HECHO MEDIDO.** Todo lo de este apartado se ejecutó en esta sesión y la
salida está pegada en §8.

| Suite | Antes | Después |
|---|---|---|
| `tests/test_contract_materials.py` | 5 funciones | **62 funciones, 64 casos** |
| `tests/test_absence_safety.py` | intacta | **intacta, sin una sola modificación** |
| `tests/test_coverage_policy.py` | intacta | **intacta, sin una sola modificación** |

**Ninguna prueba existente se tocó para «hacerla pasar».** No hizo falta: no
apareció ninguna incompatibilidad normativa.

### 6.1 Cobertura de los casos exigidos

| Caso | Cubierto por |
|---|---|
| **A.** Resultado factual normal | `test_a_known_code_returns_a_fact`, `test_a_fact_always_carries_its_attribution` |
| **B.** Código exacto | `test_b_an_exact_code_is_attributed_as_an_exact_code` |
| **C.** Código antiguo | `test_c_an_old_code_matches_and_says_so` |
| **D.** Ausencia no autoritativa | 6 pruebas, incluidas `test_d_no_absence_value_means_nonexistence` y `test_d_an_authoritative_absence_cannot_be_built` |
| **E.** Sin inventario activo | `test_e_no_active_inventory_alone_composes_as_error_not_no_evidence` y las parametrizadas |
| **F.** Capacidad no disponible | `test_f_unavailable_beside_other_facts_degrades_instead_of_failing` |
| **G.** Cobertura `UNKNOWN` | 5 pruebas, incluida `test_g_ambito_in_the_rows_never_becomes_coverage` |
| **H.** Semántica de `null` | 9 pruebas, incluida `test_h_every_nullable_field_declares_its_sense` |
| **I.** `dado_de_baja` no accionable | 3 pruebas |
| **J.** `stock_locations` coherentes | 4 pruebas |
| **K.** `match_origin` | 4 pruebas, incluida la violación de contrato |
| **L.** Excepciones reservadas | 7 pruebas, incluida la complementaria de que ningún desenlace normal lanza |
| **M.** Minimización del request | 3 pruebas |
| **N.** Determinismo | 3 pruebas |

## 7. Comandos relevantes

Lo que otra persona necesita para reproducir el trabajo:

```bash
git fetch origin
git log --oneline dd0634b20dfc1b6bc1178d63835d61ad2eea7480..origin/main

uv sync --all-extras

uv run pytest tests/test_contract_materials.py -q
uv run pytest tests/test_contract_materials.py tests/test_absence_safety.py \
              tests/test_coverage_policy.py -q
uv run pytest -q

uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

## 8. Resultados

**HECHO MEDIDO.** Salida real, pegada sin parafrasear.

### 8.1 Pruebas focales del contrato

```
................................................................         [100%]
64 passed, 2 warnings in 0.23s
```

### 8.2 Las tres suites que no debían romperse

```
314 passed, 2 warnings in 0.47s
```

### 8.3 Suite completa

```
1455 passed, 230 skipped, 3 warnings in 72.27s (0:01:12)
```

Los 230 omitidos son los que exigen PostgreSQL y los que dependen de
artefactos que no entran a Git; se omiten por diseño en un clon limpio y
corren en CI. Ejemplo literal del motivo:

```
SKIPPED [1] tests/test_vectors_postgres.py:167: requires a PostgreSQL database;
set ELSA_TEST_DATABASE_URL (e.g. postgresql://user@127.0.0.1:5432/elsa_test)
```

### 8.4 Ruff, formato, mypy y `git diff --check`

```
=== RUFF CHECK ===
All checks passed!

=== RUFF FORMAT --check ===
305 files already formatted

=== MYPY ===
Success: no issues found in 215 source files

=== GIT DIFF --CHECK ===
(limpio, sin salida)
```

### 8.5 Verificación de que la deuda D2 desapareció

```
=== ¿queda 'Material | None' o 'si no existe'? ===
  NINGUNA APARICIÓN
```

## 9. Métricas

**HECHO MEDIDO**, obtenidas con los comandos de §7.

| Métrica | Valor | Método |
|---|---|---|
| Archivos modificados | 5 | `git diff --stat` |
| Archivos creados | 2 | `git status` |
| Líneas insertadas / eliminadas | 2020 / 62 | `git diff --stat` |
| Pruebas del contrato, antes | 5 | `git show origin/main:tests/test_contract_materials.py \| grep -c` |
| Pruebas del contrato, después | 62 funciones · 64 casos | `grep -c` + `pytest --collect-only` |
| Suite completa | 1455 pasan · 230 omitidas | `uv run pytest -q` |
| Ficheros que mypy revisa | 215 | `uv run mypy` |
| Consumidores rotos por el cambio | **0** | `git grep` previo + suite completa en verde |
| Pruebas existentes modificadas | **0** | `git diff --stat` |

## 10. Aportes de Claude Code

Todo el trabajo técnico de este subbloque —la comprobación arquitectónica
previa, el retipado, el fake, las 62 pruebas, ADR 0028 y este documento— se
produjo en una sesión de Claude Code, revisada por el responsable del
proyecto antes del merge.

**Identificador de sesión verificable:**
`https://claude.ai/code/session_01TohWh9zyb62Rp5dGhDQgEi`

La misma sesión había producido antes la auditoría de preparación de M1 que
identificó la deuda D2 en sus tres ubicaciones y verificó que no tenía
consumidores. Ese hallazgo es el que permitió acotar M1-A como un cambio
local y seguro.

## 11. Aportes de Codex

**Nada que registrar.** Codex no participó en este subbloque.

## 12. Operaciones manuales y de PowerShell

**Nada que registrar.** Todo el trabajo ocurrió dentro del repositorio, en
un entorno Linux efímero. No se ejecutó nada en PC1, no se tocó ningún panel
de Supabase, no se arrancó ningún servicio local y no se manipuló ningún
archivo fuera de Git.

Las **decisiones humanas H1 y H4** las tomó el responsable del proyecto
fuera de la sesión y llegaron por escrito en la instrucción del subbloque.

## 13. Incidentes

Tres, todos menores y resueltos dentro de la sesión. Se registran porque un
bloque sin incidentes es sospechoso.

| # | Incidente | Qué se hizo |
|---|---|---|
| **I1** | La primera comprobación de sintaxis falló con `SyntaxError` en `class DerivedValue[T]` | **Falso positivo del entorno, no del código.** Se había usado el `python3` del sistema, que es 3.11; el proyecto fija 3.12 (`.python-version`), donde los genéricos PEP 695 son válidos. **HECHO DEL REPOSITORIO:** `core/retrieval.py:92` y `:108` ya los usan. Se repitió con `python3.12` y pasó |
| **I2** | `ruff check` señaló 3 errores de orden de importaciones y `ruff format` quiso reformatear 2 archivos | Corregidos con `ruff check --fix` y `ruff format`. Las pruebas focales se re-ejecutaron **después** del formateo, y siguieron en verde (314) |
| **I3** | `git diff --check` señaló una línea en blanco al final de `fake_materials.py` | Eliminada. La comprobación quedó limpia |

**Ningún incidente obligó a modificar una prueba existente ni a desviarse de
H4.**

## 14. Git

| | |
|---|---|
| Base | `origin/main` = `dd0634b20dfc1b6bc1178d63835d61ad2eea7480` |
| Archivos modificados | `src/elsa/ports/materials.py`, `src/elsa/ports/__init__.py`, `src/elsa/adapters/fake_materials.py`, `tests/test_contract_materials.py`, `docs/architecture.md` |
| Archivos creados | `docs/adr/0028-forma-del-resultado-contractual-del-puerto-de-materiales.md`, `docs/bloque-5-0-m1-a-contrato-consumidor-cierre.md` |
| Archivos **no** tocados | `config.py`, `container.py`, `core/health.py`, `scripts/`, `web/`, `supabase/`, y **todo** el repositorio de Materiales |
| Commit del trabajo | `36b692fbdf37f8861fd014f9840f7d32f8bb3022` |
| Merge de PR #38 | `d6b3270aa9ad37f6833ff77f4e5278f2c5efb171`, **merge commit real de dos padres** |
| Padres del merge | `dd0634b2…` (main previo) · `36b692fb…` (la rama) |
| `main` tras el merge | `d6b3270aa9ad37f6833ff77f4e5278f2c5efb171` |
| Sin squash ni rebase | Correcto. Merge commit real, verificado con `git rev-list --parents -n1` |
| Rama remota | **Conservada**, no borrada al mergear |

## 15. Ramas

| Rama | Papel |
|---|---|
| `claude/upbeat-turing-4bppro` | **La usada.** La sesión impone esta rama de desarrollo, de modo que **no se creó** `feat/m1-a-materials-contract-consumer`, que era el nombre sugerido. Se registra aquí porque el estándar lo exige y porque la desviación es del entorno, no de una preferencia |
| `docs/m1-a-cierre-final` | **Cierre documental.** Creada desde `main` = `d6b3270a…`, ya con el trabajo dentro, para registrar en este documento los SHA reales que no existían antes del merge. Solo toca `docs/` |
| `main` | Destino de ambos pull requests. **PR #38 mergeado** con merge commit real |
| Ninguna abandonada | Nada que registrar |

## 16. Commits

**HECHO DEL REPOSITORIO.**

| Hash | Asunto | Papel |
|---|---|---|
| `36b692fbdf37f8861fd014f9840f7d32f8bb3022` | `feat(materials): make M1 consumer contract executable` | El trabajo de M1-A. Único commit del PR #38 |
| `d6b3270aa9ad37f6833ff77f4e5278f2c5efb171` | `Merge pull request #38 from VallejoOsorio2026/claude/upbeat-turing-4bppro` | Merge commit real, dos padres: `dd0634b2…` y `36b692fb…` |
| *(cierre documental)* | `docs(project): close M1-A with real SHAs` | Este documento con los valores reales. Ver §17 |

## 17. Pull requests

**HECHO MEDIDO.**

### 17.1 PR #38 — el trabajo

| | |
|---|---|
| Número | [#38](https://github.com/VallejoOsorio2026/Elsa-ai/pull/38) |
| Rama | `claude/upbeat-turing-4bppro` → `main` |
| Estado | **MERGED** |
| Head | `36b692fbdf37f8861fd014f9840f7d32f8bb3022` |
| Merge commit | `d6b3270aa9ad37f6833ff77f4e5278f2c5efb171` |
| Método | **Merge commit**, sin squash ni rebase |
| Fecha efectiva del merge | **2026-09-21 16:34:42 -05:00** (21:34:42 UTC) |
| Commits | 1 |
| Archivos | 9 |
| `mergeable_state` antes del merge | `clean` |
| Hilos de revisión pendientes | 0 |
| CI del PR | **4/4 success** |

### 17.2 CI post-merge de `main`

| | |
|---|---|
| Run ID | **35657978542** ([enlace](https://github.com/VallejoOsorio2026/Elsa-ai/actions/runs/35657978542)) |
| Número de run | 207 |
| Commit probado | `d6b3270aa9ad37f6833ff77f4e5278f2c5efb171` |
| Evento | `push` sobre `main` |
| Jobs | `Lint, types and tests` → **success** · `Secret scan (gitleaks)` → **success** |
| Pasos del job principal | Containers, checkout, uv, dependencias, **Ruff lint**, **Ruff format check**, **mypy**, **Tests** — todos `success` |
| Duración | 21:34:44 → 21:37:31 UTC |

> En CI la suite corre **con PostgreSQL** (paso «Initialize containers»), de
> modo que los 230 casos que localmente se omiten sí se ejecutan allí. El
> paso **Tests** cerró en `success` a las 21:37:28 UTC.

### 17.3 PR del cierre documental

Registrado en §19.4.

## 18. Migraciones

**Nada que registrar.** Este subbloque no escribió ni aplicó ninguna
migración, no tocó `supabase/`, y no se conectó a ningún proyecto Supabase
remoto. La regla 15 no se activó en ningún momento.

## 19. Estado operacional final

### 19.1 Qué funciona, qué está degradado y qué no está conectado

| | Estado |
|---|---|
| **El contrato esperado** | **Ejecutable y probado.** 64 casos en verde |
| **`MaterialsPort`** | **Retipado y conforme.** Sin semántica heredada |
| **Fake de la fachada** | **Funciona**, determinista, sin red ni datos reales |
| **La política de respuesta** | **Intacta y conectada** al puerto por `as_capability_result()` |
| **El adaptador real** | **No existe.** No está conectado a nada |
| **La fachada de Materiales** | **No existe, y no está solicitada** |
| **El puerto en producción** | **No cableado.** `container.py` sigue listando `materials` como dependencia planeada, sin tocar |

### 19.2 Control de alcance

**HECHO MEDIDO.** Verificado sobre el diff completo antes del commit:

- El repositorio de Materiales **no fue modificado**: su árbol quedó limpio
  en `436eab92e1d4854e6055daaec808d2213cb37b7f`, el mismo SHA con el que se
  clonó en solo lectura.
- `config.py`, `container.py` y `core/health.py` **no aparecen en el diff**.
- **No existe ningún adaptador real**: el único adaptador tocado es el fake.
- **No se eligió transporte**: el campo `transport_binding` del descriptor
  vale `"fake"` y no lo lee nada.

### 19.3 Estado de los puntos

| Punto | Estado |
|---|---|
| **M1-A** | **CERRADO Y DOCUMENTADO** |
| **M1** | **ABIERTO** |
| **M4 OPERATIVO** | **ABIERTO** |
| **M6 OPERATIVO** | **ABIERTO** |
| **M8** | **ABIERTO**, con el criterio de [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §8.3 intacto y sin cumplir |
| **M3, M5, M7, M4-NORMATIVO, M6-NORMATIVO** | Cerrados antes de este subbloque; **no se tocaron** |

### 19.4 Cierre documental

**HECHO MEDIDO.** La regla 26 exige que un bloque no esté cerrado sin su `.md`
integrado en `main`. Este apartado registra esa integración.

| | |
|---|---|
| Rama | `docs/m1-a-cierre-final`, desde `main` = `d6b3270aa9ad37f6833ff77f4e5278f2c5efb171` |
| Alcance | **Solo `docs/`.** Ningún archivo de `src/`, `tests/`, `scripts/`, configuración, runtime ni Materiales |
| Qué cambia | Los SHA reales del merge, el CI post-merge, y el estado de M1-A |
| Qué **no** cambia | **ADR 0028 no se toca.** No se duplica ni se reescribe |

Los datos de PR, merge y CI del cierre documental quedan en el pull request
correspondiente, enlazado desde el historial del proyecto. Este documento se
considera definitivo cuando ese PR está mergeado y su CI post-merge en verde.

## 20. Pendientes

| Id | Pendiente | Quién |
|---|---|---|
| **H3** | **PENDIENTE.** Enlace de transporte concreto de la fachada | Contract Owner + Materiales |
| **H5** | **PENDIENTE.** Autorización para modificar el repositorio de Materiales | Responsable del proyecto |
| **T1** | Definición canónica versionada, `contract_version` y descriptor reales | Materiales (M1) |
| **T2** | Pruebas contractuales del proveedor | Materiales (M1) |
| **T3** | Versionar las definiciones que hoy no lo están en Materiales (P1/P2 de [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §3) | Contract Owner |
| **T4** | Adaptador real, cableado, configuración y salud degradada | ELSA, tras H3 |
| **T5** | **M4 operativo** y **M6 operativo**, que comparten emisor y esperan a M1 | Sus propios subbloques |
| **T6** | **M8**, abierto y no bloqueante | Su propio subbloque |

### 20.1 Limitaciones honestas de este subbloque

1. **El contrato sigue sin emisor.** Todo lo que aquí se prueba se prueba
   contra un fake que ELSA misma escribió. Que la suite esté verde dice que
   ELSA es coherente consigo misma, **no** que Materiales vaya a cumplirlo.
   La conformidad real llega con las pruebas del proveedor.
2. **El fake no es una implementación de referencia.** No agrega, no calcula
   y no busca. Si alguien lo tomara por una especificación de *cómo*
   implementar la fachada, se equivocaría: especifica **qué** debe
   devolver.
3. **La forma del descriptor está modelada, no verificada.** Nada comprueba
   todavía qué ocurre cuando el descriptor no responde, porque no hay
   descriptor al que preguntar.
4. **M3-A no se ejercita.** El campo `material_code` documenta la regla de
   frontera, pero ninguna prueba la aplica: aplicarla es trabajo del
   adaptador.

## 21. Siguiente bloque

**PENDIENTE de autorización explícita.** Este documento **no autoriza nada**
por sí solo, y el orden lo fija el responsable del proyecto (regla 20).

### 21.1 Qué debe saber quien siga

1. **M1-A no es M1.** Lo que se cerró es el lado consumidor. La fachada no
   existe y no está pedida.
2. **La deuda D2 está eliminada.** No volver a introducir ninguna lectura en
   la que un vacío signifique inexistencia, en ninguna capa.
3. **No crear enums paralelos.** ADR 0028 §6 lo prohíbe, y la razón es que
   divergen en silencio.
4. **Antes de leer un campo vacío del contrato, consultar `NULL_SENSES` y la
   tabla de [ADR 0027](adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
   §7 y §8.** `null` no significa nada por sí solo.
5. **`extracted_at` no sirve para vigencia**, y `loaded_at` no lo sustituye.
6. **M8 sigue abierto.** Tipar el puerto no mejoró la autoridad de la
   ausencia, y no debe parecer que sí.
7. **El siguiente paso técnico de ELSA depende de H3.** Sin enlace elegido
   no se puede escribir el adaptador, y escribirlo «provisionalmente»
   volvería a acoplar ELSA a una superficie que nadie gobierna, que es el
   problema que todo esto existe para evitar.

### 21.2 Qué habilita este cierre

Que la especificación que se pida a Materiales para la fachada de M1 pueda
acompañarse de **una suite que ya dice, sin ambigüedad, qué se espera de
cada campo, de cada vacío y de cada desenlace** — y que falle si lo que
llega no lo cumple.

**Eso es todo lo que habilita.** No se autoriza aquí, y requiere decisión
explícita en cada caso: resolver H3, solicitar H5, pedir la fachada,
escribir el adaptador, iniciar M4 operativo o M6 operativo, cerrar M8,
cerrar el subbloque 5.0.c, cerrar el Bloque 5.0 o el Piloto 0.1, tocar ONNX
ni decidir D20.

---

## Nota sobre este documento

Su función es que alguien que no participó en la sesión pueda reconstruir
**qué se decidió, por qué, sobre qué evidencia, y qué sigue abierto**, sin
acceso a la conversación que lo produjo.

---

## Estado final

**HECHO DEL REPOSITORIO**, con los SHA reales de §14, §16 y §17.

> # M1-A = CERRADO Y DOCUMENTADO

El trabajo está en `main` (`d6b3270aa9ad37f6833ff77f4e5278f2c5efb171`), su CI
post-merge cerró en verde (run **35657978542**), y este documento lo registra
conforme a la regla 26 y a
[`BLOCK_CLOSURE_STANDARD.md`](project/BLOCK_CLOSURE_STANDARD.md).

**Cerrar M1-A no cierra nada más. Lo que sigue abierto, sigue abierto:**

| Punto | Estado |
|---|---|
| **M1** | **ABIERTO** |
| **M4 OPERATIVO** | **ABIERTO** |
| **M6 OPERATIVO** | **ABIERTO** |
| **M8** | **ABIERTO**, con el criterio de [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §8.3 intacto y sin cumplir |
| **H3** — enlace de transporte de la fachada | **PENDIENTE** |
| **H5** — autorización para modificar el repositorio de Materiales | **PENDIENTE** |

Y dos hechos que este cierre **no** cambia:

- **El repositorio de Materiales no fue modificado.**
- **No existe adaptador real**, y no puede existir antes de H3.

**Ninguno de estos puntos se cierra por asociación con M1-A.**
