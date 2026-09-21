# Cierre del subbloque 5.0 — M4-NORMATIVO: semántica de `null` y vigencia del inventario

Documento de cierre redactado según
[el estándar de cierre de bloques](project/BLOCK_CLOSURE_STANDARD.md)
(`CLAUDE.md`, regla 26).

- **Fecha:** 2026-09-21
- **Estado:** **M4-NORMATIVO = CERRADO Y DOCUMENTADO.**
  **M4 OPERATIVO = ABIERTO.**
- **Repositorio:** `VallejoOsorio2026/Elsa-ai`
- **Main / base:** `880ccf24656198fb7cd134b69f069af7c974c0ed`
- **Rama de trabajo:** `claude/beautiful-cori-0yk4de`
- **Pull request:** [#36](https://github.com/VallejoOsorio2026/Elsa-ai/pull/36)
  — **MERGED** el 2026-09-21T20:06:34Z
- **Merge commit:** `42482ef4f26d8e8e97cc790308e5ca66dd188ec5`
- **Main final:** `42482ef4f26d8e8e97cc790308e5ca66dd188ec5`
- **CI post-merge:** ✅ **SUCCESS** — run
  [`35649004508`](https://github.com/VallejoOsorio2026/Elsa-ai/actions/runs/35649004508)

> **Qué cierra este documento y qué no.**
>
> Cierra **únicamente** la mitad **normativa** de **M4**: la contradicción
> **C1** sobre la semántica de `null`, resuelta por decisión humana explícita y
> registrada en
> [ADR 0027](adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md).
>
> **NO** cierra **M4 operativo**. **NO** cierra **M1**. **NO** cierra **M6
> operacional**. **NO** cierra **M8**, que sigue **ABIERTO**. **NO** cierra el
> subbloque 5.0.c, el Bloque 5.0 ni el Piloto 0.1. **NO** autoriza ninguna
> implementación.

Marcas de evidencia usadas, según el estándar: **HECHO MEDIDO**, **HECHO DEL
REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.

> **Sobre la estructura de este documento.** La sesión que lo originó proponía
> un esquema de 18 apartados. Se usa en su lugar el de **21 apartados** de
> [`BLOCK_CLOSURE_STANDARD.md`](project/BLOCK_CLOSURE_STANDARD.md), que es la
> fuente canónica por la regla 26 de [`CLAUDE.md`](../CLAUDE.md) y la
> convención ya aplicada en los cierres de 5.0.a, 5.0.b, B9a–B9c y 5.0.c.1.
> Todas las declaraciones que aquella sesión exigía están presentes: **§19.1 y
> §19.2** declaran el estado de M4 en los términos textuales pedidos, **§17**
> registra el merge con su evidencia real, **§19.4** contiene el checklist de
> cierre y **§21** la regla de continuidad.

---

## 1. Objetivo

Dejar **inequívoca y versionada** la semántica de `null` en el contrato de
inventario Materiales–ELSA, de modo que ningún consumidor pueda derivar de un
campo vacío una afirmación que el contrato no sostiene.

El objetivo era **normativo, no funcional**: al terminar debía existir una
decisión arquitectónica revisable, no una capacidad ejecutable. **Ninguna línea
de código entraba en el alcance.**

La contradicción a resolver ya estaba declarada por el propio corpus:
[ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
§10 la nombró como PENDIENTE «y es de M4», y el
[cierre de 5.0.b](bloque-5-0-b-contrato-materiales-cierre.md) §20 la registró
como **P9**.

---

## 2. Alcance

### Entró

- **Auditoría documental de C1** sobre el corpus vigente (§5.1).
- **Decision Brief** con cuatro familias de alternativas y sus consecuencias
  para Materiales, para ELSA y para la compatibilidad futura.
- **Decisión humana explícita** del responsable del proyecto (§5.2).
- **[ADR 0027](adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)**,
  que decide la semántica de `null`, la de los cinco campos del bloque
  `inventory` y su relación con `snapshot_sensitive` y
  `requires_fresh_inventory`.
- **Notas fechadas mínimas** en los encabezados de
  [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) y
  [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md),
  que remiten al ADR nuevo **sin tocar sus cuerpos**.
- Este documento de cierre y la actualización mínima de los dos documentos de
  estado.

### Quedó explícitamente fuera

**M4 operativo, íntegro:**

- `requires_fresh_inventory` implementado;
- `inventory_freshness_unknown`;
- `freshness_policy.py` o cualquier política de vigencia;
- cambios en `AnswerWarning`;
- lógica de metadata en tiempo de ejecución;
- cambios de API;
- cambios en `MaterialsPort`, en `fake_materials` o en adaptadores de
  Materiales;
- pruebas de implementación de M4 y pruebas de integración con Materiales.

**Y además:**

- **M1.** `src/elsa/ports/materials.py`, `src/elsa/adapters/fake_materials.py`
  y `tests/test_contract_materials.py` **no se tocaron**. La deuda histórica
  «`None` = no existe» queda **registrada como dependencia** (§19.3), no
  corregida.
- **M6.** Ninguna decisión de
  [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
  se rediseña: `dado_de_baja`, `FACTUAL_SAP_AGGREGATED`, `snapshot_sensitive`,
  `ambito` frente a `coverage.observed_scope`, la opacidad de `ubicacion`,
  `stock_locations` y el vocabulario de `match_origin` quedan intactos.
- **M8.** Sigue **ABIERTO**. No se intentó ningún «cierre por espera».
- **D20, ONNX, Modo ELSA, embeddings, ZIAA y BOM.** No se tocaron.

---

## 3. Estado inicial

**HECHO MEDIDO**, al comenzar la sesión:

```
$ git fetch origin
   dfdd2ef..880ccf2  main -> origin/main

$ git status
On branch claude/beautiful-cori-0yk4de
nothing to commit, working tree clean

$ git rev-parse HEAD
880ccf24656198fb7cd134b69f069af7c974c0ed

$ git rev-parse origin/main
880ccf24656198fb7cd134b69f069af7c974c0ed
```

`origin/main` **no había avanzado** más allá de `880ccf2` (PR #35, que incluye
la corrección de `Stop-ElsaLlm`). El árbol de trabajo estaba limpio y HEAD
coincidía exactamente con `origin/main`, de modo que **no hizo falta rebasar ni
partir de otra base**. La comprobación se repitió antes de editar el primer
archivo, con idéntico resultado.

Qué existía — **HECHO DEL REPOSITORIO**:

- ADR 0001–0026, sin huecos de numeración.
- [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §9 con la forma
  del bloque `inventory` y la semántica de `loaded_at` y `extracted_at`.
- [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
  §10 con la regla de emisión estable y su PENDIENTE declarada.
- La evidencia primaria de Materiales sobre metadata de carga
  ([evidencia M6](piloto-0-1/evidencia-m6-semantica-temporalidad.md) §10, E8).

Qué **no** existía — **HECHO DEL REPOSITORIO**:

- Ninguna decisión sobre la doble semántica de `null`.
- Ninguna definición de `source_file_label` en nulo.
- Ningún símbolo de M4 en el código: `grep` de `requires_fresh_inventory`,
  `inventory_freshness_unknown`, `snapshot_sensitive` y `extracted_at` sobre
  `src/` y `tests/` devolvió **una sola coincidencia**, y es un comentario en
  `src/elsa/core/coverage_policy.py:290` que cita la convención de nombrado.

---

## 4. Trabajo realizado

En orden:

1. **Verificación del estado de partida** (§3), antes de leer nada más.
2. **Lectura de las fuentes obligatorias**: ADR 0020 §17, ADR 0021 §7–§16 y
   §25, ADR 0023, ADR 0025 completo, ADR 0026, contrato funcional, evidencia
   M6, los tres documentos de `docs/project/` y los cuatro cierres previos del
   Bloque 5.0.
3. **Reconstrucción de C1** y búsqueda de sus manifestaciones fuera del §9
   (`grep` sobre `docs/`, lectura del bloque `coverage` de ADR 0021 §7.2).
4. **Comprobación del estado del código** respecto de M4 y de la deuda de M1,
   en **solo lectura**.
5. **Decision Brief** entregado al usuario, con los apartados A–J y cuatro
   familias de alternativas. **Sin tocar ningún archivo.**
6. **Parada y consulta.** No se editó nada hasta recibir la decisión.
7. **Decisión humana recibida** (§5.2).
8. **Re-verificación de `origin/main`**, que seguía en `880ccf2`.
9. **Redacción de
   [ADR 0027](adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)**.
10. **Notas fechadas mínimas** en los encabezados de ADR 0021 y ADR 0025.
11. **Validaciones** (§6).
12. **Este documento de cierre** y la actualización mínima de los documentos de
    estado.

---

## 5. Decisiones

### 5.1 La contradicción C1, reconstruida

**HECHO DEL REPOSITORIO.** La contradicción no se descubrió aquí: el propio
corpus la había declarado. Lo que faltaba era resolverla.

**Los dos textos en conflicto:**

| Origen | Qué dice sobre `null` |
|---|---|
| [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §10.2 | «**`null` significa "no hay valor en la fuente para este campo"**, y su semántica concreta se documenta **campo por campo**» |
| [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §9.3 | «`extracted_at` en nulo significa **"la fecha de extracción desde SAP no está disponible ni registrada en este contrato"**. **No significa** que el dato no exista en la realidad: significa que **este contrato no lo transporta**» |

Y [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
§10 declaró expresamente que **no tocaba** el §9 de ADR 0021 y **no resolvía**
la doble semántica, remitiéndola a M4.

**Por qué era una contradicción real**, y no solo aparente — tres choques,
todos verificables leyendo los documentos:

| # | Choque | En qué consiste |
|---|---|---|
| **C1.a** | **De cabecera** | Un significado universal frente a uno incompatible para un campo del mismo contrato. Un consumidor que leyera solo §10.2 concluiría de `extracted_at: null` que **SAP no tiene fecha de extracción** — la inferencia que §9.3 prohíbe |
| **C1.b** | **De mecanismo** | §10.3 ordena declarar **en el descriptor** lo que el contrato no transporta; `extracted_at: null` lo declara **en el payload**. Dos canales para el mismo hecho |
| **C1.c** | **Interno del §10.2** | Su cabecera universal está **falsada por su propia tabla**: `material_antiguo: null` cubre «el valor de origen estaba corrompido y se descartó», que es un valor **que sí existía en la fuente**; y `ubicacion: null` se define advirtiendo que **no** significa que el material carezca de ubicación física |

**Hallazgo añadido durante la auditoría, no previsto al abrir el subbloque** —
**HECHO DEL REPOSITORIO**: el sentido «el contrato no lo transporta» **ya vivía
fuera del §9**.
[ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §7.2 dice que «si
esa metadata todavía no existe, `observed_scope` es **nulo** o vacío y
`coverage.state` es `UNKNOWN`». Por tanto `extracted_at` **no era una excepción
aislada**, y cualquier regla que prohibiera ese sentido habría roto también el
bloque de cobertura. Este hallazgo fue **decisivo** para descartar la
Alternativa A.

**Campos afectados:** `extracted_at`, `source_file_label` (cuyo nulo **nunca
había sido definido**), los cuatro campos de `coverage`, `ubicacion`,
`material_antiguo`, `descripcion` y `unidad`. Detalle completo en
[ADR 0027](adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
§3.4.

### 5.2 Decisión humana adoptada

**DECISIÓN TOMADA por el responsable del proyecto el 2026-09-21**, tras recibir
el Decision Brief y **antes de que se editara ningún archivo**.

Se presentaron cuatro familias de alternativas:

| | Alternativa | Resultado |
|---|---|---|
| **A** | `null` significa universalmente «la fuente factual no tiene valor» | **Descartada.** Falsada por la propia tabla de ADR 0025 §10; rompería §7.2; convertiría `extracted_at: null` en una afirmación falsa sobre SAP; exigiría un cambio de significado sin cambio de nombre, que ADR 0021 §15.1 marca como el más peligroso |
| **B** | Semántica campo por campo, sin vocabulario cerrado | **Descartada por insuficiente.** Correcta y compatible, pero permite prosa libre y podría repetir la ambigüedad no nombrada de `material_antiguo` |
| **C** | Separar valor y disponibilidad en el payload, ahora | **Descartada por anticipación.** Hoy nadie puede emitirla (la fachada de M1 no existe, B1–B4 de ADR 0025 §12 siguen abiertas) y fijaría un enum cerrado sin casos medidos. Contradice la regla 23 |
| **D** | **B disciplinada: semántica campo por campo con vocabulario cerrado obligatorio, y ruta compatible hacia C** | **APROBADA** |

**La alternativa D fue además la recomendación técnica de la sesión, pero la
selección la hizo el responsable del proyecto.** La Alternativa C **no queda
descartada para siempre**: queda declarada como ampliación **compatible** para
cuando exista un caso real que la exija.

### 5.3 Regla final de `null`

> **`null` no tiene significado universal en el contrato de inventario.**
> Significa exactamente «este campo no lleva un valor utilizable en esta
> respuesta», y **nada más puede inferirse sin consultar la tabla normativa del
> campo**.

Todo campo nulable se clasifica en **exactamente uno** de tres sentidos
cerrados y disjuntos: **`VALOR_FACTUAL_AUSENTE`**, **`DATO_NO_PROPORCIONADO`**
y **`DATO_DESCONOCIDO`**. Un campo nulable sin clasificación es un **defecto de
contrato**, no un campo permisivo.

### 5.4 Semántica final de `extracted_at`

> **`DATO_NO_PROPORCIONADO`.** Su `null` significa «este contrato no transporta
> la fecha de extracción desde SAP». **No significa** que SAP carezca de ella.

Y, en consecuencia:

- **`loaded_at` no se presenta nunca como fecha de extracción**, ni como
  aproximación, ni acompañado de advertencia.
- **`extracted_at` no participa en la vigencia**, ni nulo ni relleno en el
  futuro: `requires_fresh_inventory` se sigue derivando **solo** de
  `snapshot_sensitive`.
- **`extracted_at: null` nunca produce `inventory_freshness_unknown` por sí
  solo.**
- Rellenarlo cuando exista un mecanismo sigue siendo un cambio **compatible**.

### 5.5 ADR generado (regla 25)

**[ADR 0027 — Semántica de `null` y disponibilidad de metadata del
inventario](adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)**

- **Número:** 0027. **HECHO DEL REPOSITORIO**: es el siguiente libre real;
  existen 0001–0026 sin huecos.
- **Estado:** aceptado.
- Contiene: contexto, problema, reconstrucción de C1, decisión aprobada,
  semántica exacta de `null`, los tres sentidos cerrados, la semántica de los
  cinco campos del bloque `inventory`, la relación con `snapshot_sensitive`, la
  relación futura con `requires_fresh_inventory`, las reglas de emisión y
  serialización, la ruta compatible hacia la Alternativa C, ocho casos límite,
  ejemplos concretos, compatibilidad con ADR 0021 y ADR 0025, consecuencias
  para Materiales y para ELSA, qué NO decide, pendientes operativos,
  alternativas descartadas y trazabilidad.

### 5.6 Historia normativa conservada

**Los cuerpos de ADR 0021 §9.3 y ADR 0025 §10 no se tocaron.** Se añadió a cada
uno **una nota fechada mínima en el encabezado**, que remite al ADR nuevo y
declara que aquel documento no se reescribe. Es la convención que el propio
ADR 0021 ya usaba para ADR 0023 y ADR 0024.

**ADR 0027 es la decisión posterior autoritativa.** Ningún documento histórico
se convirtió en documentación «actualizada» borrando la evolución del diseño.

### 5.7 Decisiones de forma, reportadas antes de escribir (regla 19)

| Decisión | Motivo |
|---|---|
| **Usar los 21 apartados del estándar** en vez de los 18 propuestos por la sesión | Regla 26 de `CLAUDE.md`; autorizado explícitamente por el responsable del proyecto |
| **Usar la rama `claude/beautiful-cori-0yk4de`** en vez de `docs/m4-normativo-null-inventory` | Es la rama que la restricción de la sesión impone, y ya estaba a la altura de `origin/main` |
| **Definir `source_file_label` en nulo**, aunque no estuviera en el encargo | Es un hueco del bloque `inventory`, y por tanto de M4; dejarlo abierto habría reproducido C1 en otro campo |
| **No corregir la deuda de `Material \| None`** | Pertenece a M1 (§19.3, N2) |

---

## 6. Pruebas

**Todo lo de este apartado es HECHO MEDIDO**, ejecutado en el contenedor de la
sesión sobre el árbol con los cambios aplicados. Las salidas reales están en
§8.

| Verificación | Ejecutada | Resultado |
|---|---|---|
| `git diff --check` | Sí | Sin hallazgos, código de salida `0` |
| Enlaces relativos de los archivos tocados | Sí | Sin enlaces rotos |
| `ruff check` | Sí | `All checks passed!` |
| `ruff format --check` | Sí | `305 files already formatted`. **Ruff 0.16 también formatea Markdown**, de modo que esta verificación **sí cubre los documentos de este cambio** |
| `mypy` | Sí | `Success: no issues found in 215 source files` |
| `pytest -q` | Sí | `1396 passed, 230 skipped` |
| **`gitleaks`** | **No, localmente** | ✅ **Verde en CI** (§17.1) |
| Pruebas que exigen PostgreSQL | **No, localmente** | ✅ **Verdes en CI** (§17.1) |

### Qué NO se ejecutó, y por qué

- **Las 230 pruebas omitidas** son las que exigen PostgreSQL y no tienen
  `ELSA_TEST_DATABASE_URL` en este contenedor. **En CI sí se ejecutan**, contra
  el servicio `pgvector/pgvector:pg16` del flujo de trabajo, **y pasaron**
  (§17.1).
- **`gitleaks` no se ejecutó localmente**: no está instalado en el contenedor y
  el encargo prohíbe instalar herramientas nuevas. **Lo ejecutó CI** sobre la
  historia completa (trabajo `secret-scan`), **y pasó** (§17.1).
- **Ninguna migración** se escribió, se aplicó ni se revirtió.
- **No se ejecutó nada contra Materiales**, ni real ni de prueba.

---

## 7. Comandos relevantes

```bash
# Estado de partida, repetido antes de editar
git fetch origin && git rev-parse origin/main && git status --short

# Instalación reproducible
uv sync --locked

# Verificaciones
git diff --check
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q

# Control de alcance, antes del commit
git status --short
git diff --cached --name-only | grep -E '^(src|tests|scripts|supabase|web)/' && echo "ALCANCE VIOLADO"
```

---

## 8. Resultados

### 8.1 Archivos modificados

**HECHO MEDIDO.** Salida de `git status --short` antes del commit:

```
 M docs/adr/0021-contrato-de-inventario-con-materiales.md
 M docs/adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md
 M docs/project/HANDOVER_AND_CONTINUITY_MAP.md
 M docs/project/PROJECT_HISTORY_AND_CURRENT_STATE.md
?? docs/adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md
?? docs/bloque-5-0-m4-normativo-cierre.md
```

| Archivo | Naturaleza del cambio |
|---|---|
| `docs/adr/0027-…md` | **Nuevo.** El ADR |
| `docs/bloque-5-0-m4-normativo-cierre.md` | **Nuevo.** Este documento |
| `docs/adr/0021-…md` | **Solo encabezado.** Una nota fechada. **§9 intacto** |
| `docs/adr/0025-…md` | **Solo encabezado.** Una nota fechada. **§10 intacto** |
| `docs/project/PROJECT_HISTORY_AND_CURRENT_STATE.md` | Fila M4 y §13.1 |
| `docs/project/HANDOVER_AND_CONTINUITY_MAP.md` | Fila T2 de §13.4 |

**Seis archivos, todos bajo `docs/`. Ningún archivo de `src/`, `tests/`,
`scripts/`, `supabase/`, `web/` ni configuración de runtime.**

### 8.2 Salidas reales

```
$ git diff --check
$ echo $?
0
```

```
$ uv run ruff check .
All checks passed!
```

```
$ uv run ruff format --check .
305 files already formatted
```

```
$ uv run mypy
Success: no issues found in 215 source files
```

```
$ uv run pytest -q
[…]
1396 passed, 230 skipped, 3 warnings in 41.00s
```

```
$ python3 (comprobador de enlaces relativos de los archivos tocados)
enlaces relativos comprobados: 276 · rotos: 0
```

---

## 9. Métricas

**HECHO MEDIDO**, obtenidas con los comandos de §7 y con `wc -l` sobre los
archivos nuevos.

| Métrica | Valor | Método |
|---|---|---|
| Archivos tocados | **6**, todos en `docs/` | `git status --short` |
| Archivos de código tocados | **0** | `git diff --cached --name-only`, filtrado por `src/`, `tests/`, `scripts/`, `supabase/`, `web/` |
| Líneas del ADR 0027 | **596** | `wc -l` |
| Líneas de este documento | **719** | `wc -l` |
| Líneas añadidas a ADR 0021 | **7**, todas en el encabezado | `git diff --stat` |
| Líneas añadidas a ADR 0025 | **6**, todas en el encabezado | `git diff --stat` |
| Enlaces relativos comprobados | **276**, **0 rotos** | Comprobador de §6 |
| Pruebas ejecutadas | **1396 pasadas**, 230 omitidas | `pytest -q` |
| Archivos verificados por mypy | **215** | `mypy` |
| Archivos verificados por ruff format | **305** (215 `.py` + 90 `.md`) | `ruff format --check`, con ruff 0.16.6 |
| ADR existentes antes / después | **26 / 27**, sin huecos | `ls docs/adr/` |

---

## 10. Aportes de Claude Code

Toda la auditoría documental, el Decision Brief, la redacción de ADR 0027, de
este documento y de las notas fechadas se produjeron en **una sesión de Claude
Code**, con el modelo configurado como Opus 5, el 2026-09-21.

**Identificador de sesión:** se dispone del identificador
`session_01HW5V9LcMMkHDfxkdZqAXpT`, asociado a esta sesión.

**Qué revisó el responsable del proyecto:** el Decision Brief completo, con sus
cuatro alternativas y sus consecuencias, **antes** de que se editara ningún
archivo. La selección de la alternativa fue suya (§5.2), igual que la
autorización de las dos desviaciones de forma de §5.7.

**Qué NO hizo la sesión, y consta:** no seleccionó la alternativa, no editó
ningún archivo antes de la decisión, no tocó código, no ejecutó nada contra
Materiales y no hizo merge.

---

## 11. Aportes de Codex

**Nada que registrar.** Codex no participó en este subbloque.

---

## 12. Operaciones manuales y de PowerShell

**Nada que registrar.** No se ejecutó ningún script de PowerShell, ninguna
comprobación en el panel de Supabase, ningún servicio local y ninguna operación
fuera del repositorio. El subbloque es íntegramente documental.

**El runtime local de PC1, Phi/llama.cpp y el entorno de PC1 no se tocaron.**

---

## 13. Incidentes

| # | Incidente | Qué se hizo |
|---|---|---|
| **1** | **La sesión proponía un esquema de 18 apartados** para el documento de cierre, incompatible con los 21 de `BLOCK_CLOSURE_STANDARD.md`, que la regla 26 de `CLAUDE.md` hace obligatorio | Se reportó **antes** de escribir y se resolvió con autorización explícita: se usa el estándar del repositorio, incrustando las declaraciones exigidas |
| **2** | **La sesión proponía una rama** (`docs/m4-normativo-null-inventory`) distinta de la que su propia restricción impone | Se reportó y se usó la rama impuesta, declarándolo en §15 |
| **3** | **`source_file_label` no tenía definido el significado de su nulo** en ningún documento. No estaba previsto en el encargo | Se resolvió dentro del alcance normativo de M4: queda clasificado como `DATO_DESCONOCIDO` en ADR 0027 §7 |
| **4** | **Se encontró un tercer sentido de `null`, en código** (`src/elsa/ports/materials.py`), contrario a ADR 0021 §8 | **No se corrigió**, por pertenecer a M1. Registrado como dependencia N2 |
| **5** | **`gitleaks` no está disponible** en el contenedor de la sesión, y el encargo prohíbe instalar herramientas nuevas | No se ejecutó localmente, y no se fingió que pasara. **Resuelto en CI**, sobre la historia completa (§17.1) |
| **6** | **El primer borrador de este documento mezcló** el esquema de 18 apartados con el del estándar, produciendo 24 | Se detectó antes del commit y se rehízo conforme al estándar. **No llegó a la historia de Git** |

---

## 14. Git

Cambio **íntegramente documental**, sobre `origin/main` en `880ccf2`, sin
rebase, sin squash y sin reescritura de historia.

**Control de alcance ejecutado antes del commit** (§7): la lista de archivos se
limita a `docs/`. Ningún archivo bajo `src/`, `tests/`, `scripts/`, `supabase/`
ni `web/`. **El pull request integrado tocó 6 archivos, los 6 bajo `docs/`**,
con 1361 líneas añadidas y 3 eliminadas.

**La integración fue un merge commit real** (`42482ef`, dos padres), conforme a
la instrucción de no usar squash ni rebase.

---

## 15. Ramas

| Rama | Uso |
|---|---|
| `claude/beautiful-cori-0yk4de` | **La usada.** Creada por la sesión anterior, a la altura exacta de `origin/main` al comenzar |
| `docs/m4-normativo-cierre-final` | **La del cierre documental final.** Creada desde `origin/main` ya en `42482ef`, para registrar la evidencia real del merge |
| `docs/m4-normativo-null-inventory` | **No se creó.** Era la propuesta de la sesión, descartada por la restricción que impone la rama anterior |

**Ninguna rama se borra.** `claude/beautiful-cori-0yk4de` se conserva tras el
merge, en `0d45171`.

> Se declara la desviación para que nadie busque una rama que no existe.

---

## 16. Commits

| Commit | Contenido |
|---|---|
| `9dd78ee17b5ea7908c6d069111554d6e85d96659` | `docs(adr): decide M4 null and inventory metadata semantics` — ADR 0027, documento de cierre, notas fechadas y actualización de los documentos de estado |
| `c34f76a385260cee291c25edba81ab1565400497` | `docs(pilot): record commit, pull request and CI state in the M4 closure` |
| `0d451711e9669a54d759b7f95b49b4f5a6539878` | `docs(pilot): record the green CI result in the M4 closure` |
| `42482ef4f26d8e8e97cc790308e5ca66dd188ec5` | **Merge commit de [#36](https://github.com/VallejoOsorio2026/Elsa-ai/pull/36).** Padres: `880ccf2` (main) y `0d45171` (head). Merge commit real: **sin squash y sin rebase** |
| Cierre documental final | El commit que trae esta versión del documento, en la rama `docs/m4-normativo-cierre-final`. **Su propio SHA no se incrusta aquí**: un documento no puede contener su propio hash. Es trazable por su pull request (§17.2) |

---

## 17. Pull requests

| Campo | Valor |
|---|---|
| **Pull request** | [#36](https://github.com/VallejoOsorio2026/Elsa-ai/pull/36) |
| **Título** | `docs(adr): decide M4 null and inventory metadata semantics` |
| **Base** | `main` |
| **Estado** | ✅ **MERGED** |
| **CI del PR** | ✅ **verde** — ver §17.1 |
| **Merge** | ✅ `42482ef4f26d8e8e97cc790308e5ca66dd188ec5` |
| **Fecha de integración** | **2026-09-21T20:06:34Z** |
| **Método** | **Merge commit real.** Sin squash, sin rebase |
| **Padres del merge** | `880ccf24656198fb7cd134b69f069af7c974c0ed` · `0d451711e9669a54d759b7f95b49b4f5a6539878` |
| **Main final** | ✅ `42482ef4f26d8e8e97cc790308e5ca66dd188ec5` |
| **CI post-merge** | ✅ **SUCCESS** — ver §17.1 |
| **Rama** | **conservada** en `0d45171`, no borrada |

### 17.1 CI

**HECHO MEDIDO** sobre el head `c34f76a`, consultado el 2026-09-21. El flujo de
trabajo se dispara en `push` y en `pull_request`, de modo que cada trabajo
aparece dos veces:

| Trabajo | Estado |
|---|---|
| **Lint, types and tests** | ✅ **success** (ambas corridas) |
| **Secret scan (gitleaks)** | ✅ **success** (ambas corridas) |

**CI REQUERIDO EN VERDE.** También lo estuvo sobre el commit anterior
`9dd78ee`, que es el que contiene el ADR y el grueso de este documento.

Dos cosas que localmente **no** pudieron verificarse (§6) quedan verificadas
aquí:

- **`gitleaks`**, que no está instalado en el contenedor de la sesión, se
  ejecutó sobre la **historia completa** y pasó.
- **Las 230 pruebas que exigen PostgreSQL**, omitidas localmente por falta de
  `ELSA_TEST_DATABASE_URL`, se ejecutaron contra el servicio
  `pgvector/pgvector:pg16` del flujo de trabajo y pasaron.

**CI post-merge sobre `main` — HECHO MEDIDO.**

| Campo | Valor |
|---|---|
| **Run ID** | [`35649004508`](https://github.com/VallejoOsorio2026/Elsa-ai/actions/runs/35649004508) |
| **Evento** | `push` sobre `main` |
| **Commit probado** | `42482ef4f26d8e8e97cc790308e5ca66dd188ec5` |
| **Conclusión del run** | ✅ **success** |
| **Lint, types and tests** | ✅ **success** |
| **Secret scan (gitleaks)** | ✅ **success** |

> **`main` quedó verde después de integrar este trabajo.** Es la condición que
> convierte «listo para cierre tras merge» en **cerrado**.

### 17.2 Pull request del cierre documental final

Esta versión del documento —la que incorpora la evidencia real del merge— entra
por un pull request propio desde `docs/m4-normativo-cierre-final`, titulado
`docs(project): finalize M4 normative closure`. Contiene **únicamente** este
archivo.

> **Por qué su CI post-merge no se transcribe aquí.** Registrarlo exigiría un
> commit posterior, cuyo CI exigiría otro, sin final. Ese CI **sí se verifica**
> antes de declarar el cierre (§19.4), y queda consultable en el historial de
> `main`. Lo que este documento transcribe es la evidencia del trabajo que
> cierra: el merge de [#36](https://github.com/VallejoOsorio2026/Elsa-ai/pull/36)
> y su CI post-merge.

---

## 18. Migraciones

**Nada que registrar.** No se escribió ninguna migración, no se aplicó ninguna
a ningún ambiente, y **no se tocó ningún proyecto Supabase, ni de ELSA ni de
Materiales** (regla 15).

---

## 19. Estado operacional final

**Sin cambio respecto del estado de partida.** Este subbloque **no altera el
comportamiento del sistema en ninguna forma observable**: no añade capacidad,
no cambia una respuesta, no toca un endpoint y no modifica una línea de código.

Lo que cambia es **qué está permitido afirmar** y **qué queda prohibido
inferir**, de forma versionada y auditable.

### 19.1 Qué parte de M4 queda cerrada

> ## **M4-NORMATIVO = CERRADO Y DOCUMENTADO**

**DECISIÓN TOMADA**, documentada en
[ADR 0027](adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
y en este documento. Concretamente, quedan **inequívocas**:

1. **La regla general de `null`** (§5.3): sin significado universal, con
   clasificación obligatoria en tres sentidos cerrados.
2. **`extracted_at`** (§5.4): `DATO_NO_PROPORCIONADO`. Habla del contrato, no
   del mundo.
3. **Su relación con `loaded_at`**: campos de naturaleza distinta que **no se
   sustituyen**; `loaded_at` sigue siendo solo «fin de carga en Materiales».
4. **`source_file_label`**: `DATO_DESCONOCIDO`, y la prohibición de inferir de
   él cualquier fecha se mantiene sin excepción.
5. **`version_number`, `loaded_at` y `row_count`**: no nulables; la ausencia de
   inventario activo viaja por `NO_ACTIVE_INVENTORY`, no por nulos.
6. **La relación con `snapshot_sensitive`**: ejes ortogonales, ninguno derivado
   del otro; los campos de `inventory` no declaran `snapshot_sensitive` porque
   describen el snapshot en lugar de afirmarse sobre él.
7. **La relación futura con `requires_fresh_inventory`**: `extracted_at` no
   participa.
8. **La PENDIENTE de
   [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
   §10 y el pendiente P9 del
   [cierre de 5.0.b](bloque-5-0-b-contrato-materiales-cierre.md) §20**, que
   quedan resueltos.

**El cierre es efectivo**, y las tres condiciones que lo hacían depender del
merge están cumplidas y medidas:

1. [#36](https://github.com/VallejoOsorio2026/Elsa-ai/pull/36) **mergeado** con
   merge commit real `42482ef` (§17).
2. **CI post-merge de `main` en verde**, run `35649004508` (§17.1).
3. **`main` contiene el ADR 0027 y este documento** (§16).

La regla del proyecto —**bloque cerrado = bloque documentado en un `.md`**— se
cumple: el documento existe, está en `main`, y lleva la evidencia real del
merge en lugar de un marcador pendiente.

### 19.2 Qué parte de M4 sigue abierta

> ## **M4 OPERATIVO = ABIERTO**

**HECHO DEL REPOSITORIO.** Nada de la metadata de vigencia se transporta, se
consume ni existe en ELSA:

- el bloque `inventory` **no lo emite nadie**: la fachada contractual de **M1**
  no existe;
- `requires_fresh_inventory` **no está implementado**;
- `inventory_freshness_unknown` **no existe** como aviso: solo se cita en un
  comentario de `src/elsa/core/coverage_policy.py:290`;
- **no hay política de vigencia**, ni módulo que la contenga;
- `AnswerWarning` **no cambió**;
- `MaterialsPort`, `fake_materials` y sus pruebas de contrato **no cambiaron**.

**Por tanto, M4 como punto sigue ABIERTO y bloqueante.** Lo que este subbloque
elimina no es el bloqueo: es la **ambigüedad** que habría hecho que la
implementación futura fuera incorrecta sin que nadie lo notara.

### 19.3 Dependencias

| Id | Dependencia | Estado |
|---|---|---|
| **M1** | **ABIERTO y bloqueante.** La fachada contractual no existe; sin ella nadie emite el bloque `inventory`. **M4 operativo no puede empezar antes** | ADR 0021 §19.1 |
| **N2 — deuda concreta de M1** | `MaterialsPort.get_material` documenta su `None` como «o `None` si **no existe**» (`src/elsa/ports/materials.py`). Es un **tercer sentido de `null`**, incompatible con ADR 0021 §8 y con ADR 0027. **Registrada, deliberadamente no corregida** | **PENDIENTE**, M1 |
| **M6 operativo** | **ABIERTO.** Decisión normativa cerrada por ADR 0025; implementación y verificación pendientes. Comparte emisor con M4: ambos esperan la misma fachada | ADR 0025 §15 |
| **M7** | **CERRADO.** El Contract Owner debe publicar y versionar la tabla del §7 de ADR 0027 en la definición canónica cuando exista | ADR 0026 |
| **M8** | **ABIERTO.** No bloqueante desde ADR 0023, con el criterio de cierre de ADR 0021 §8.3 **intacto y sin cumplir**. **No se tocó y no se intentó cerrar** | ADR 0021 §8.3, ADR 0023 |
| **Pruebas contractuales del proveedor** | Deben cubrir: campo nulable sin clasificación, centinela en lugar de `null`, y clave omitida | **PENDIENTE**, Materiales |

### 19.4 Criterio de cierre

| # | Criterio | Estado |
|---|---|---|
| 1 | C1 resuelta por **decisión humana explícita** | ✅ §5.2 |
| 2 | Existe **ADR nuevo**, con el siguiente número libre real | ✅ ADR 0027 |
| 3 | La semántica de `null` queda **inequívoca** | ✅ §5.3; ADR 0027 §5–§6 |
| 4 | **`extracted_at`** queda inequívoco | ✅ §5.4; ADR 0027 §7 |
| 5 | La relación con **`loaded_at`** queda inequívoca | ✅ §5.4; ADR 0027 §7 |
| 6 | La relación con **`snapshot_sensitive`** queda documentada | ✅ ADR 0027 §9 |
| 7 | **No se modificó código** | ✅ §8.1 |
| 8 | **No se modificó M1** | ✅ §2 |
| 9 | **No se modificó M6** | ✅ §2 |
| 10 | **No se intentó cerrar M8** | ✅ §2, §19.3 |
| 11 | Existe **`.md` específico de cierre** | ✅ este documento |
| 12 | **`git diff --check`** pasa | ✅ §8.2 |
| 13 | **Historia normativa conservada** en ADR 0021 y ADR 0025 | ✅ §5.6 |
| 14 | **CI requerido en verde** | ✅ §17.1 |
| 15 | **PR creado** | ✅ [#36](https://github.com/VallejoOsorio2026/Elsa-ai/pull/36) |
| 16 | **PR #36 mergeado**, con merge commit real | ✅ `42482ef` |
| 17 | **CI post-merge de `main` en verde** | ✅ run `35649004508` |
| 18 | **`main` contiene el documento definitivo** | ✅ §16 |
| 19 | **M4 operativo sigue marcado ABIERTO** | ✅ §19.2 |
| 20 | **No se trabajó ningún otro pendiente** | ✅ §2 |

**Estado resultante:**

- **M4-NORMATIVO: CERRADO Y DOCUMENTADO.**
- **M4 OPERATIVO: ABIERTO.**
- **M8: ABIERTO**, con el criterio de cierre de ADR 0021 §8.3 intacto y sin
  cumplir.

---

## 20. Pendientes

### 20.1 Pendientes derivados

| Id | Pendiente | Quién |
|---|---|---|
| **N1** | **M4 operativo**, íntegro: transporte, consumo y política de vigencia | M1 + subbloque futuro |
| **N2** | **Corregir la deuda de `Material \| None`** en `src/elsa/ports/materials.py` | **M1** |
| **N3** | Reemitir la tabla del §7 de ADR 0027 en la **definición canónica versionada** del contrato | Contract Owner (M7) + Materiales |
| **N4** | Pruebas contractuales del proveedor sobre nulos, centinelas y claves omitidas | Materiales |
| **N5** | ADR adicional si `material_antiguo` necesitara distinguir sus dos causas | Trabajo normativo futuro |
| **N6** | **M6 operacional, M8 y D20** siguen abiertos, sin cambio | Sus propios subbloques |
| **N7** | ~~Verificar el CI del pull request~~ **CERRADO**: CI verde, §17.1 completado | — |

### 20.2 Riesgos y limitaciones

| # | Riesgo | Mitigación, o su ausencia |
|---|---|---|
| **1** | **La norma no tiene emisor.** ADR 0027 describe lo que la fachada deberá cumplir; hoy nadie lo cumple ni lo incumple | Es el mismo estado que M6 tras ADR 0025. Se declara, no se disimula |
| **2** | **La norma es documental, no ejecutable.** Ninguna prueba automática verifica hoy la clasificación de un `null` | **Deliberado.** Escribir esas pruebas exigiría el retipado del `MaterialsPort`, que es M1 |
| **3** | **El tercer sentido de `null` sigue vivo en el código** | Registrado como N2. Quien implemente M1 debe corregirlo |
| **4** | **`material_antiguo` conserva una ambigüedad irreductible** | ADR 0025 la declaró por diseño; ADR 0027 la nombra como `DATO_DESCONOCIDO` y prohíbe a ELSA resolverla |
| **5** | **La Alternativa C podría hacer falta antes de lo previsto** | ADR 0027 §12 deja la ruta declarada como cambio **compatible**, de modo que adoptarla no sería una ruptura |
| **6** | **`gitleaks` no se verificó localmente** | **Resuelto:** verde en CI (§17.1) |
| **7** | **Las pruebas que exigen PostgreSQL se omitieron localmente** | **Resuelto:** verdes en CI (§17.1) |

---

## 21. Siguiente bloque

**PENDIENTE de autorización explícita.** Este documento **no autoriza nada** por
sí solo, y el orden lo fija el responsable del proyecto (regla 20).

### 21.1 Regla de continuidad — qué debe saber el siguiente bloque

1. **M4-NORMATIVO está cerrado. M4 operativo NO.** No confundir uno con otro, y
   no cerrar M4 por asociación.
2. **`null` no significa nada por sí solo.** Antes de escribir código que lea un
   campo vacío del contrato, **consultar la tabla del campo** en ADR 0027 §7 y
   §8.
3. **`extracted_at` no es una fecha, ni siquiera una fecha desconocida.** Es un
   hueco declarado del contrato. **No sirve para vigencia**, y **`loaded_at` no
   lo sustituye**.
4. **`requires_fresh_inventory` se deriva solo de `snapshot_sensitive`.** Eso no
   cambió.
5. **Quien implemente M1 debe corregir la deuda N2** del `MaterialsPort`.
6. **M8 sigue ABIERTO**, con su criterio de cierre intacto y sin cumplir. No se
   cierra por espera.
7. **M1 es la puerta.** Sin fachada no hay emisor, y sin emisor M4 operativo y
   M6 operativo no pueden empezar.

### 21.2 Qué habilita este cierre

Que la especificación que se pida a Materiales para la fachada de **M1** pueda
incluir, por escrito y sin ambigüedad, **qué significa cada campo vacío** y qué
prueba contractual debe demostrarlo. **Eso es todo lo que habilita.**

**No se autoriza aquí**, y requiere decisión explícita en cada caso: iniciar M4
operativo, iniciar M1, cerrar M6 operacional, cerrar M8, cerrar el subbloque
5.0.c, cerrar el Bloque 5.0 o el Piloto 0.1, tocar ONNX, ni decidir D20.

---

## Nota sobre este documento

Su función es que alguien que no participó en la sesión pueda reconstruir **qué
se decidió, por qué, sobre qué evidencia, y qué sigue abierto**, sin acceso a la
conversación que lo produjo.
