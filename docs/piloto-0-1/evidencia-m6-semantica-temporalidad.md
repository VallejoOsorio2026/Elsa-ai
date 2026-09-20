# Evidencia previa de M6 — semántica, procedencia y temporalidad de los campos de Materiales

Recopilación de la evidencia disponible **en ELSA** sobre qué significan los
campos que devolverá el contrato de inventario, de dónde procede cada
afirmación y qué sigue sin poder verificarse.

> **Qué es este documento, y qué no es.**
>
> Es el **paso 0 de M6**: preservar evidencia verificable antes de decidir
> nada. **No cierra M6**, no decide semántica, no autoriza ADR 0025 y no
> autoriza ninguna implementación.
>
> **No es una auditoría del repositorio de Materiales.** El código de
> Materiales **no se inspeccionó en este trabajo** (§10). Todo lo que aquí
> consta sobre su comportamiento interno procede de documentos normativos de
> ELSA o de antecedentes de conversación, **no de su código**.

> **Regla 12 de [`CLAUDE.md`](../../CLAUDE.md).** Aquí no hay ningún código SAP
> real, ningún fragmento de BOM, ningún JWT, ninguna clave, ningún correo, ninguna
> contraseña y ningún dato de inventario real. Solo nombres de campo, rutas,
> revisiones y conteos.

- Fecha de registro: **2026-09-20**
- Bloque: 5.0, subbloque **5.0.b**, punto **M6**
- Ejecución: sesión de asistente sobre el repositorio ELSA, en solo lectura

---

## 1. Propósito y alcance

**Propósito.** Reunir, con procedencia explícita, lo que hoy se sabe sobre la
semántica y la temporalidad de los campos de inventario, para que la decisión
normativa de M6 se tome sobre evidencia registrada y no sobre memoria de
conversaciones.

**Dentro del alcance:** leer el corpus normativo vigente; verificar qué existe
y qué no existe en el código versionado de ELSA, contra una revisión
identificada; clasificar cada afirmación por su procedencia; enumerar la
evidencia que falta.

**Fuera del alcance, y no se hace aquí:** decidir la semántica de ningún campo;
resolver `dado_de_baja`; redactar ADR 0025; especificar, construir o autorizar
la fachada contractual, el `MaterialsPort` real, el adaptador, los tipos
contractuales o la composición BOM → Materiales; nombrar al Contract Owner;
tocar M8 o la prueba A6c; modificar cualquier ADR, el contrato funcional o
cualquier documento de cierre.

M6 sigue con el estado que le da el corpus: **parcial y bloqueante**
([ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §25).
**Este documento no lo cambia.**

---

## 2. Base auditada

**HECHO DEL REPOSITORIO.**

| Elemento | Valor |
|---|---|
| Repositorio | `VallejoOsorio2026/Elsa-ai` |
| Revisión auditada | `26f6f94349cb6abb96c125c684966054820e9ebd` |
| Referencia | `origin/main` en la fecha de registro |
| Fecha de la auditoría | 2026-09-20 |
| Árbol de trabajo | limpio antes de crear este documento |

**Todas las búsquedas de ausencia del §9 se ejecutaron contra esa revisión
mediante `git grep <patrón> 26f6f94 -- <rutas>`**, no contra el árbol de
trabajo. Este documento no existe en esa revisión y, por tanto, **no altera sus
propios recuentos**.

> **PENDIENTE, y relevante para leer este documento.** En la fecha de registro,
> el PR #29 (`docs/adr-0020-0024-estado-aceptado`, commit `a46e8cf`) estaba
> **abierto y sin fusionar**, verificado por los metadatos del PR
> (`state: open`, `merged: false`). Ese PR solo cambia la línea `- Estado:` de
> los ADR 0020–0024 y **no toca ningún contenido citado aquí**. Este documento
> es independiente de él.

---

## 3. Fuentes inspeccionadas y antecedentes no reverificados

### 3.1 Fuentes normativas leídas, en la revisión auditada

| Documento | Secciones leídas para este trabajo |
|---|---|
| [ADR 0020](../adr/0020-capacidades-componibles-y-planes-de-ejecucion.md) | §11 y §11.1 (vigencia), §12 (ausencia), §13 (estados), §17 (contrato externo pendiente y tabla M1–M8) |
| [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) | §9, §9.1, §9.2, §9.3 · §10, §10.1–§10.6 · §12, §12.1 · §14 · §16, §16.1–§16.5 · §19, §19.1, §19.2 · §22 · §25 |
| [ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md) | §6 (hechos que no altera), §9 (clases de afirmación), §16 (metadata futura), §18 (qué queda abierto) |
| [ADR 0024](../adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md) | §3 (alcance excluido), §11.2 (firma observada del RPC), §14 (diferidas cerradas), §16 (qué queda abierto) |
| [Contrato funcional](contrato-funcional.md) | §10 (bloqueantes), §12 (criterios), §14 (decisiones abiertas) |
| [Evidencia M3/M5](evidencia-m3-m5-pc1.md) | §2.5 (cruce real), §4.2 (firma del RPC), §5 (pendientes) |
| [Cierre de 5.0.c.1](../bloque-5-0-c-1-politica-ausencia-segura-cierre.md) y [cierre B9a–B9c](../bloque-5-0-b9a-b9c-cobertura-segura-cierre.md) | Solo para precisar qué garantizan y qué no |

Las numeraciones de sección se comprobaron contra los archivos en la revisión
auditada. **Ninguna de estas fuentes se modificó.**

### 3.2 Antecedentes de conversación, no reverificables aquí

**PENDIENTE.** Existe un conjunto de afirmaciones sobre la semántica V1 de los
campos que llegó a este trabajo **como texto de encargo**, no como fuente
técnica. Enumera semánticas para `ubicacion`, `dado_de_baja`, `ambito`,
`disponible`/`comprometido`, los totales, `match_origin`,
`descripcion`/`unidad`/`material_antiguo`, y plantea la implicación de una
agregación `max()` en una función `buscar_agrupado`.

Para **ninguna** de esas afirmaciones constan los cinco elementos que las harían
verificables:

| Elemento exigible | ¿Consta? |
|---|---|
| Repositorio identificado | No |
| Commit o revisión | No |
| Ruta del archivo | No |
| Función, consulta o sección | Solo el nombre `buscar_agrupado`, sin ruta ni revisión |
| Fragmento técnico suficiente | No |
| Fecha de observación | No |

**Por tanto se clasifican como `ANTECEDENTE DE CONVERSACIÓN NO REVERIFICADO`**
y así aparecen en la matriz del §4. **Este documento no los llama «auditoría de
Materiales recuperada»**, porque no contienen las fuentes inspeccionadas.

Que no sean reverificables **no los convierte en falsos**. Los conserva
registrados, con su naturaleza declarada, para que el trabajo normativo pueda
confirmarlos o descartarlos contra la fuente.

### 3.3 Clasificación usada

Se combinan las marcas del
[estándar de cierre de bloques](../project/BLOCK_CLOSURE_STANDARD.md) con la
clasificación de procedencia que este trabajo necesita:

| Marca | Significado |
|---|---|
| **EVIDENCIA PRIMARIA VERIFICADA** | Se leyó la fuente técnica y se cita ruta y revisión |
| **DECLARACIÓN NORMATIVA EXISTENTE** | Un ADR o documento vigente de ELSA lo establece. Es norma, no observación del sistema real |
| **ANTECEDENTE DE CONVERSACIÓN NO REVERIFICADO** | Llegó por conversación o encargo, sin fuente citable |
| **AUSENCIA VERIFICADA EN EL ALCANCE INSPECCIONADO** | Se buscó en rutas y revisión concretas de **ELSA** y no está. **No dice nada sobre Materiales** |
| **EVIDENCIA PENDIENTE** | Hace falta y no se tiene |

---

## 4. Matriz de campos

Una fila por campo nombrado en
[ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §10 o en los
antecedentes. **Las celdas sin evidencia dicen «sin determinar», no se
rellenan por intuición.**

Abreviaturas de procedencia:
`F-SAP` = `FACTUAL_SAP` · `DER-MAT` = `DERIVED_BY_MATERIALES` ·
`MATCH` = `MATCH_METADATA` · `INV` = `INVENTORY_METADATA`.

En la columna **Implementación/prueba**, «ausente en ELSA `26f6f94`» significa
`AUSENCIA VERIFICADA EN EL ALCANCE INSPECCIONADO` según el §9, y **no** afirma
nada sobre Materiales.

| Campo | Fuente/revisión | Significado documentado | Procedencia | Nulabilidad | Temporalidad | Agregación/regla | Implementación/prueba | Pendiente |
|---|---|---|---|---|---|---|---|---|
| `material` | ADR 0021 §10.1 · `26f6f94` | Código de material de SAP, preservado | `F-SAP`, normado | Sin determinar | Sin determinar | Transformación declarada: recorte de espacios | Ausente en ELSA `26f6f94` | Temporalidad y nulabilidad sin normar |
| `descripcion` | ADR 0021 §10.1 · `26f6f94` | Columna de SAP preservada | `F-SAP`, normado | Sin determinar | **Sin determinar.** ADR 0020 §11 advierte que **no se asume** que solo `disponible` cambie con el snapshot | Recorte de espacios. **Efecto de una agregación por material: sin determinar** (§5) | Ausente en ELSA `26f6f94`. Existe `AssertedInventoryField.DESCRIPTION`, que es declaración de la **plantilla** de ELSA, no del campo de Materiales | Si una agregación elige el valor entre filas, ¿sigue siendo factual **por fila**? |
| `unidad` | ADR 0021 §10.1 · `26f6f94` | Columna de SAP preservada | `F-SAP`, normado | Sin determinar | Sin determinar | Recorte de espacios. Mismo interrogante de agregación | Ausente en ELSA `26f6f94`. Existe `AssertedInventoryField.UNIT_OF_MEASURE`, con el mismo matiz | Igual que `descripcion` |
| `material_antiguo` | ADR 0021 §10.1 · `26f6f94` | Columna de SAP preservada | `F-SAP`, normado | Implícita: hay «valores corrompidos en origen» que se descartan. **Regla de descarte no publicada** | Sin determinar | Recorte **+ descarte de valores corrompidos en origen** | Ausente en ELSA `26f6f94` | Qué cuenta como «corrompido», y si el descarte produce nulo o ausencia de campo |
| `centro`, `almacen` | ADR 0021 §10.1 · `26f6f94` | Columnas de SAP preservadas | `F-SAP`, normado | Sin determinar | Sin determinar | Recorte de espacios | Ausente en ELSA `26f6f94` | Relación con `ambito` y con la cobertura: sin normar (§6) |
| `ubicacion` | ADR 0021 §10.1 · `26f6f94` | Columna de SAP preservada | `F-SAP`, normado | **Normada**: el blanco se preserva como **nulo** y **nunca se hereda de otra fila** | **Sin normar.** La sensibilidad al snapshot aparece como antecedente, no como norma | Recorte de espacios | Ausente en ELSA `26f6f94` | Opacidad, prohibición de interpretar y sensibilidad al snapshot: **sin normar** (§6) |
| `ubicaciones` (plural) | Antecedente · ADR 0020 §17 lo nombra en la definición de M6 | Sin determinar si designa el mismo concepto que `ubicacion` o el conjunto agregado por material | Sin determinar | Sin determinar | Sin determinar | Sin determinar | Ausente en ELSA `26f6f94` | **No se unifica con `ubicacion` sin evidencia**: son nombres distintos en fuentes distintas |
| `disponible` | ADR 0021 §10.2 · `26f6f94` | **Suma de dos conceptos de existencias de SAP.** El ADR subraya que **no es un campo de SAP** | `DER-MAT`, normado | Sin determinar | Sensible al snapshot por naturaleza; **magnitud y frecuencia sin determinar** | Regla de negocio de Materiales. `rule_reference` y `rule_verifiable` **obligatorios**; ELSA no recalcula y no exige los componentes (§10.5) | Ausente en ELSA `26f6f94`. `AssertedInventoryField.AVAILABILITY` es la declaración de la plantilla | Cuáles son los dos conceptos; dónde se publica la regla; `rule_verifiable` real |
| `comprometido` | ADR 0021 §10.2 · `26f6f94` | **Proyección directa de un concepto de existencias de SAP** | `DER-MAT`, normado | Sin determinar | Igual que `disponible` | Regla de Materiales, con `rule_reference` y `rule_verifiable` | Ausente en ELSA `26f6f94` | Qué concepto proyecta; regla publicada |
| `total_disponible`, `total_comprometido` | ADR 0021 §10.2 · `26f6f94` | **Agregación sobre las ubicaciones del material** | `DER-MAT`, normado | Sin determinar | Igual que sus sumandos | Agregación declarada en prosa; **función concreta sin determinar** (§5) | Ausente en ELSA `26f6f94`. `AssertedInventoryField.STOCK_QUANTITY` es la declaración de la plantilla | Sobre qué conjunto agrega y si el conjunto depende de la cobertura |
| `ambito` | ADR 0021 §10.2 · `26f6f94` | **«Clasificación de la ubicación».** Una línea; sin más definición normativa | `DER-MAT`, normado | Sin determinar | **Sin normar.** «Temporal» consta solo como antecedente | Clasificación; **regla sin publicar** | Ausente en ELSA `26f6f94` | Valores posibles; regla; y **su separación explícita de `coverage.observed_scope`** (§6) |
| `dado_de_baja` | ADR 0021 §10.2 y §10.3 · `26f6f94` | **Señal de riesgo inferida de la descripción.** No es un estado de SAP | `DER-MAT`, normado | Sin determinar | Sin determinar | **`rule_verifiable` es `false`**: la regla está publicada como prosa, pero la función que la aplica no está en el repositorio del proveedor | Ausente en ELSA `26f6f94` | **Su inclusión o exclusión de V1 es DECISIÓN NORMATIVA PENDIENTE** (§8) |
| `match_origin` | ADR 0021 §10.4 y §10.6 · `26f6f94` | Origen de la coincidencia. **Nunca factual**; conservarlo es **obligatorio** | `MATCH`, normado | Sin determinar | No temporal | Invariante de ADR 0021 §6: en lookup exacto solo cabe coincidencia por código —exacto o antiguo— y **cualquier otro valor es violación de contrato** | Ausente en ELSA `26f6f94`. Aparece **una sola vez** en todo el repositorio, en el ejemplo JSON de §10.6 | Vocabulario cerrado de valores; **validación ejecutable** (§7) |
| `version_number`, `loaded_at`, `row_count`, `source_file_label`, `extracted_at` | ADR 0021 §9.1–§9.3 · `26f6f94` | Bloque `inventory`. `loaded_at` = **fin de la carga en Materiales**, nada más | `INV`, normado | `extracted_at` **es nulo y reservado** por decisión; `source_file_label` admite nulo | **Normado, y es lo mejor definido de M6-adyacente**: la vigencia no equivale a la actualidad de SAP | Prohibido **inferir una fecha de `source_file_label`** | Ausente en ELSA `26f6f94` (§9). Pertenece a **M4**, no a M6 | Ver §9 de este documento y el estado de M4 |

> **Los campos de inventario no aparecen en el código de ELSA porque la fachada
> no existe.** Eso es coherente con
> [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §19.1 y **no
> es un defecto que este documento proponga corregir.**

---

## 5. Hallazgos sobre agregaciones

**EVIDENCIA PENDIENTE.** Este apartado **no describe comportamiento
observado**, porque el código que lo produciría no se inspeccionó.

**AUSENCIA VERIFICADA EN EL ALCANCE INSPECCIONADO.** En la revisión `26f6f94`,
el SQL versionado de ELSA vive en `supabase/migrations/` y `supabase/rollback/`
(nueve archivos `.sql` más un `.gitkeep`). Se buscaron **dieciocho variantes
sintácticas** de agregación y ventana —`max(`, `min(`, `sum(`, `count(`,
`array_agg`, `string_agg`, `jsonb_agg`, `json_agg`, `bool_or`, `bool_and`,
`group by`, `distinct on`, `over(`, `row_number`, `rank(`, `first_value`,
`last_value`, `coalesce`—, con espaciado flexible y sin distinguir
mayúsculas: **cero coincidencias en cero archivos**. Tampoco existe ninguna
función `buscar_agrupado` ni ningún SQL de inventario de Materiales.

Las únicas menciones a Materiales en el SQL de ELSA son de **identidad** —el
modelo de autorización— y un comentario que delimita la frontera:

> «Los valores de inventario (`inventory_strategy`, `stock_max`, `stock_min`,
> `source_stock`) son los de ESA fuente en ESA fecha. No son el stock actual:
> el stock actual seguirá siendo de Materiales/ZIAA.»
>
> `supabase/migrations/20260906010000_create_technical_knowledge_model.sql`, en `26f6f94`

**Conclusión, y su límite exacto:** toda la lógica de agrupación vive en el
repositorio de Materiales, **que no se inspeccionó**. Lo que sigue son las
preguntas que el trabajo normativo deberá responder contra ese código, no
hallazgos:

| # | Pregunta pendiente sobre la agregación |
|---|---|
| A1 | ¿De qué tabla o vista salen los registros, y de qué versión o snapshot de inventario? |
| A2 | ¿Qué filtros se aplican antes de agrupar, y excluyen alguna fila del universo? |
| A3 | ¿Cuál es exactamente la clave de agrupación? |
| A4 | ¿Qué función se aplica a **cada** campo devuelto, campo por campo? |
| A5 | Cuando hay varias filas por grupo, ¿cómo se elige el valor representativo de un campo factual? |
| A6 | ¿Pueden dos campos del mismo resultado agregado proceder de **filas distintas**? Si es así, la relación entre campos de una misma fila se pierde |
| A7 | ¿La agregación depende de la versión activa del inventario, o la ignora? |

> **Dos supuestos que este documento se prohíbe.** No se asume que `max()`
> signifique «el más reciente» —sobre un texto es orden lexicográfico, no
> temporal—, ni que todos los valores de un resultado agregado procedan de una
> misma fila. Ambas cosas **solo pueden comprobarse leyendo el código**.

La pregunta **A6** es la que más consecuencias tiene para M6: si se confirma,
`descripcion`, `unidad` y `material_antiguo` dejarían de ser factuales **por
fila** y pasarían a ser factuales **por agrupación**, que es una procedencia
distinta de la que hoy les asigna
[ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §10.1.
**Este documento no lo decide.**

---

## 6. Ubicación, ámbito y cobertura son tres cosas distintas

**Separarlas es un requisito, no una aclaración de estilo.**

### 6.1 Dos «ubicaciones» que no son la misma

**EVIDENCIA PRIMARIA VERIFICADA.** En `26f6f94`, el término `ubicacion` aparece
en `src/` en dos dominios que no deben confundirse:

| Ruta y línea | Dominio | Qué es |
|---|---|---|
| `src/elsa/ingestion/sap_htm.py:465`, `:524`, `:759` | Activos y BOM | **Ubicación técnica** (`floc`, `funcloc`): dónde está instalado un equipo. **Propiedad de ELSA** |
| `src/elsa/core/coverage_policy.py:21`, `:99` | Inventario | Prosa y un miembro de enum sobre las **ubicaciones de existencias devueltas**. Declaración de la plantilla de ELSA, **no** el campo de Materiales |

**No existe en ELSA ningún tipo, campo ni validación de la `ubicacion` de
inventario de Materiales.**

### 6.2 Qué está normado y qué no

| Aspecto de `ubicacion` de inventario | Estado |
|---|---|
| El blanco se preserva como **nulo** | **Normado**, ADR 0021 §10.1 |
| **Nunca se hereda de otra fila** | **Normado**, ADR 0021 §10.1 |
| Es opaca y se muestra **sin interpretar** | **Sin normar.** Consta solo como antecedente de conversación |
| Es sensible al snapshot | **Sin normar.** Consta solo como antecedente |
| Distinción entre campo ausente, valor nulo y valor desconocido | **Sin normar** |

### 6.3 `ambito` no es cobertura

**DECLARACIÓN NORMATIVA EXISTENTE.** Son dimensiones distintas y el corpus ya
lo exige, aunque no nombre el riesgo:

- `ambito` es **`DERIVED_BY_MATERIALES`**: una clasificación de la ubicación,
  calculada sobre **datos de negocio**
  ([ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §10.2).
- `coverage.observed_scope` es **`INVENTORY_METADATA`**: el ámbito que
  Materiales **declara** que cubrió la carga, y debe provenir de **metadata de
  ingestión**, no de las filas
  ([ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §7.2).

Derivar cobertura de los valores de `ambito` presentes en los datos sería
exactamente la inferencia que §7.2 prohíbe, y produciría una afirmación de
cobertura sin procedencia. Mientras no exista esa metadata, el estado es
`UNKNOWN` ([ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md)
§6).

**PENDIENTE.** Que ambas cosas sean distintas se deduce de dos apartados
separados; **ninguna fuente lo dice de forma explícita**. Escribirlo es trabajo
del ADR de M6.

---

## 7. Procedencia y coincidencia: norma sin tipo ni validación

**EVIDENCIA PRIMARIA VERIFICADA**, contra `26f6f94` en `src/` y `tests/`.

| Elemento | Norma | Ejemplo documental | Tipo | Serialización | Validación | Prueba |
|---|---|---|---|---|---|---|
| `FACTUAL_SAP` | ADR 0021 §10.1 | Tabla de campos | **No existe** | No existe | No existe | No existe |
| `DERIVED_BY_MATERIALES` | ADR 0021 §10.2 | Tabla + fragmento `jsonc` | **No existe** | No existe | No existe | No existe |
| `MATCH_METADATA` | ADR 0021 §10.4 | Enumeración en prosa | **No existe** | No existe | No existe | No existe |
| `INVENTORY_METADATA` | ADR 0021 §10.4, §9.1 | Fragmento `jsonc` | **No existe** | No existe | No existe | No existe |
| `rule_reference` | ADR 0021 §10.2 | Clave del fragmento `jsonc` | **No existe** | No existe | No existe | No existe |
| `rule_verifiable` | ADR 0021 §10.2, §10.3 | Clave del fragmento `jsonc` | **No existe** | No existe | No existe | No existe |
| `attribution` | ADR 0021 §10.6 | Fragmento `jsonc` de seis claves | **No existe** | No existe | No existe | No existe |
| `match_origin` | ADR 0021 §10.4, §10.6; invariante §6 | Una clave del fragmento de §10.6 | **No existe** | No existe | No existe | No existe |

> **Un ejemplo `jsonc` en un ADR no es una validación ejecutable.** Los ocho
> elementos están **decididos** y **ninguno está representado en código** en la
> revisión auditada. Esa distancia es el contenido de esta fila, y no se cierra
> leyendo el ADR otra vez.

**Por qué `match_origin` importa más de lo que su tamaño sugiere.** La
[evidencia M3/M5](evidencia-m3-m5-pc1.md) §2.5 registra que, en el cruce real
de 30 códigos, hubo **27 coincidencias exactas, 3 resultados devueltos sin el
código exacto y 0 `NOT_RETURNED`**. Es decir: la fuente real **no devolvió
vacío**, devolvió **otra cosa**. `match_origin` y el invariante de ADR 0021 §6
son el mecanismo que convertiría esos 3 casos en una violación de contrato
ruidosa en lugar de un resultado silencioso. Hoy ese mecanismo **solo existe
como norma**.

---

## 8. `dado_de_baja`: discrepancia registrada, sin resolver

**DECISIÓN NORMATIVA PENDIENTE. Este documento no la resuelve, y no puede.**

| Posición | Procedencia | Clasificación |
|---|---|---|
| **Incluido** en el contrato V1 como `DERIVED_BY_MATERIALES`, con `rule_verifiable: false`, sin sostener por sí solo el núcleo factual, y sin ocultar ni despriorizar el material | [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §10.2 y §10.3, en `26f6f94`. **Está versionado** | **DECLARACIÓN NORMATIVA EXISTENTE** |
| **Excluido** del contrato V1 | Texto de encargo recibido en conversación. **No está versionado en ninguna parte del repositorio** | **ANTECEDENTE DE CONVERSACIÓN NO REVERIFICADO** |

**Lo que está versionado hoy es la inclusión.** La exclusión existe únicamente
como antecedente externo y **no se trata aquí como una decisión aprobada**:
convertir una instrucción de conversación en una exclusión normativa sería
justamente el error que este documento existe para evitar.

Las dos posiciones quedan registradas con su naturaleza. **Resolverlas exige un
ADR** (regla 25 de [`CLAUDE.md`](../../CLAUDE.md)), y ese ADR **no está
autorizado por este trabajo**.

---

## 9. Implementación y pruebas en el alcance inspeccionado

### 9.1 Qué sí existe, y qué garantiza

**EVIDENCIA PRIMARIA VERIFICADA** en `26f6f94`.

| Ruta | Líneas | Qué es |
|---|---|---|
| `src/elsa/core/capability_outcomes.py` | 319 | Política del **consumidor** sobre resultado y ausencia |
| `src/elsa/core/coverage_policy.py` | 299 | Política del **consumidor** sobre cobertura |
| `src/elsa/core/answers.py` | 210 | `AnswerStatus`, `Sufficiency` y `AnswerWarning` |
| `tests/test_absence_safety.py` | 249 | Garantías A6, A6b, A18, A19 |
| `tests/test_coverage_policy.py` | 679 | Garantías A20, A20b, A21 |
| `tests/test_contract_materials.py` | 43 | Contrato del puerto **legado**, contra el fake |

**Estos módulos deciden sobre un resultado ya obtenido y no conocen ningún
campo de Materiales.** Su cierre está documentado y **este trabajo no lo
reabre**. Tampoco traslada esas políticas a Materiales: pertenecen al
consumidor ELSA.

**Limitación de integración, registrada sin proponer solución:** el cierre de
B9a–B9c dejó constancia de que esas políticas **todavía no tienen llamador** en
un camino de respuesta real. Sigue siendo cierto en la revisión auditada.
Dónde conectarlas **no se decide aquí**.

El único vocabulario de campos de inventario presente en el código de ELSA es
`AssertedInventoryField` en `coverage_policy.py`, con cinco miembros:
`DESCRIPTION`, `UNIT_OF_MEASURE`, `STOCK_QUANTITY`, `STOCK_LOCATIONS`,
`AVAILABILITY`. El propio módulo declara que **no es el esquema de la respuesta
de Materiales**, sino la declaración de qué piensa afirmar la plantilla. La
partición que hace —descripción y unidad estables; existencias, ubicaciones y
disponibilidad sensibles a cobertura— **es coherente** con lo que M6 debe
fijar, pero **no lo sustituye**, y queda condicionada a la pregunta **A6**
del §5.

### 9.2 Ausencias verificadas, con su alcance declarado

**AUSENCIA VERIFICADA EN EL ALCANCE INSPECCIONADO.** Búsqueda
case-insensitive con `git grep -i <patrón> 26f6f94 -- src tests`.

**Cero archivos con coincidencia** para: `buscar_agrupado`, `FACTUAL_SAP`,
`DERIVED_BY_MATERIALES`, `MATCH_METADATA`, `INVENTORY_METADATA`,
`rule_reference`, `rule_verifiable`, `match_origin`, `attribution`,
`dado_de_baja`, `ambito`, `comprometido`, `total_disponible`,
`total_comprometido`, `material_antiguo`, `contract_version`, `observed_scope`,
`expected_scope`, `extracted_at`, `row_count`, `source_file_label` y
`requires_fresh_inventory`.

Tres resultados exigen precisión, porque un recuento crudo engañaría:

| Patrón | Resultado crudo | Qué es realmente |
|---|---|---|
| `loaded_at` | 1 archivo | **Falso positivo.** Es `uploaded_at` en `src/elsa/ports/knowledge.py:173`, un campo del ciclo documental. **El `loaded_at` de inventario no existe en ELSA** |
| `ubicacion` | 5 líneas | Dos dominios distintos, desglosados en §6.1. Ninguna es el campo de inventario |
| `disponible` | varias | Prosa española con el sentido «no disponible» en puertos y servicios sin relación con inventario, más `coverage_policy.py` |

Además, `inventory_freshness_unknown` aparece **solo como prosa** en
`src/elsa/core/coverage_policy.py:290`; **no existe** como miembro de
`AnswerWarning`, cuyos once miembros se leyeron en `src/elsa/core/answers.py`.

> **Qué significan estas ausencias, exactamente.** Significan que **ELSA no ha
> implementado el contrato**, que es lo que
> [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §19.1 ya
> declara. **No significan nada sobre si esos campos existen en Materiales.**

### 9.3 El puerto legado

**EVIDENCIA PRIMARIA VERIFICADA.** En `26f6f94`,
`src/elsa/ports/materials.py:32` declara `get_material(code) -> Material | None`
con la documentación «o `None` si no existe», y `Material` tiene dos campos:
`code` y `description`.

[ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §14 establece
que esa semántica debe corregirse **antes** de implementar el adaptador real y
que el tipo de retorno concreto **se decide al implementarlo**. Se registra el
hecho. **Este documento no modifica el puerto, su adaptador ni sus pruebas**, y
la expectativa obsoleta de `tests/test_contract_materials.py` **no se toca**:
corregirla es trabajo de M1, y no autoriza eliminar esa suite.

---

## 10. Evidencia pendiente de Materiales

**EVIDENCIA PENDIENTE.** El repositorio relacionado es
`VallejoOsorio2026/papelsa-asistente-materiales`. **No se inspeccionó en este
trabajo**, y el acceso de esta sesión estaba limitado al repositorio ELSA. No se
clonó, no se añadió ningún conector y no se consultó ningún servicio real.

Lo que haría falta, por orden de impacto sobre M6:

| # | Evidencia solicitada | Desbloquea |
|---|---|---|
| E1 | Definición de `buscar_agrupado` o de la función de agrupación vigente: origen, filtros, clave de agrupación y función por campo | §5 completo: A1–A7, y con ellas la procedencia real de `descripcion`, `unidad` y `material_antiguo` |
| E2 | Definición de `consultar_materiales`, la firma que la [evidencia M3/M5](evidencia-m3-m5-pc1.md) §4.2 observó **como observación, no como contrato** | Qué campos devuelve hoy y con qué nombres |
| E3 | Regla publicada de `disponible` y `comprometido`: qué conceptos de existencias suman o proyectan | `rule_reference` real y `rule_verifiable` real |
| E4 | Regla y función de `ambito`, con su vocabulario de valores | Cerrar `ambito` y separarlo de la cobertura |
| E5 | Regla de `dado_de_baja` y si su implementación está versionada | Comprobar el `rule_verifiable: false` de ADR 0021 §10.3 |
| E6 | Definición de `ubicacion` en el esquema: tipo, nulabilidad y si se interpreta | Cerrar §6.2 |
| E7 | Regla de descarte de `material_antiguo` corrompido | Nulabilidad de ese campo |
| E8 | Esquema de la tabla de cargas: qué columnas de versión y fecha existen | **M4**, no M6 |

Para cualquiera de estas, basta con la **ruta, la revisión y el fragmento
sanitizado**. **No hacen falta credenciales, ni datos de inventario, ni acceso a
ningún entorno.**

---

## 11. Preguntas para el siguiente trabajo normativo

Se enumeran para que el ADR de M6 tenga un orden del día, **no para
responderlas aquí**.

| # | Pregunta | Depende de |
|---|---|---|
| Q1 | ¿Se incluye o se excluye `dado_de_baja` del contrato V1? | Decisión humana (§8) |
| Q2 | ¿Un campo factual elegido por una agregación sigue siendo `FACTUAL_SAP`, o necesita una clase propia? | E1 (§5, A6) |
| Q3 | ¿Qué temporalidad se declara para cada campo, y cuáles son sensibles al snapshot además de las existencias? | E1, E3, E6. ADR 0020 §11 advierte que **no se asume** que solo `disponible` cambie |
| Q4 | ¿Se escribe explícitamente que `ambito` no es `coverage.observed_scope`? | Decisión normativa (§6.3) |
| Q5 | ¿Se norma que `ubicacion` es opaca, se muestra sin interpretar y es sensible al snapshot? | E6 + decisión |
| Q6 | ¿Cuál es el vocabulario cerrado de `match_origin` y cómo se hace verificable el invariante de ADR 0021 §6? | Decisión + E2 |
| Q7 | ¿`ubicaciones` designa el mismo concepto que `ubicacion`? | E1, E6 |
| Q8 | ¿Cómo se distinguen campo ausente, valor nulo y valor desconocido, campo por campo? | Decisión |

**Dependencias con M1, M4 y M7, sin sobregeneralizarlas:**

- **M1** necesita las respuestas a Q2–Q8 para especificar qué transporta la
  fachada, pero **no hace falta que la fachada exista** para decidirlas. Son
  decisiones previas, no posteriores.
- **M4** es un eje distinto y **no lo resuelve M6**. `extracted_at: null` es
  una **decisión** registrada en ADR 0021 §9.3, no un defecto:
  la fecha de carga y la de extracción no se confunden, y rellenar el campo
  reservado sería un cambio compatible. **Este documento no propone
  corregirlo.**
- **M7** aporta el dueño que publicaría y versionaría las reglas que E3–E5
  piden. Que el ocupante siga sin asignarse
  ([ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §16.5) es
  un pendiente real y una **puerta previa al primer tester**, pero **ninguna
  fuente lo convierte en impedimento para recopilar evidencia ni para redactar
  un ADR**. Conviene no confundir tres cosas distintas: la decisión humana de
  nombrar a alguien, el registro canónico de esa asignación —que vive en el
  repositorio de Materiales, §16.4— y el carácter bloqueante previo a liberar.

---

## 12. Límites de esta auditoría

Se enumeran porque cada uno acota lo que este documento puede sostener.

1. **El código de Materiales no se inspeccionó.** Ninguna afirmación de aquí
   describe su implementación.
2. **Las ausencias del §9 son ausencias en ELSA**, en las rutas `src/` y
   `tests/` de la revisión `26f6f94`. No son ausencias en Materiales.
3. **Los antecedentes del §3.2 no se reverificaron** y se marcan como tales. No
   se descartan ni se ascienden a hecho.
4. **No se ejecutó la suite de pruebas** en este trabajo, y no se reutiliza
   ningún recuento de pruebas de auditorías anteriores como si fuera propio.
5. **No se consultó ningún servicio real**: ni SAP, ni Supabase, ni inventarios
   activos. No se ejecutó SQL.
6. **Árbol limpio no equivale a entorno intacto.** Este trabajo no sincronizó
   dependencias ni regeneró artefactos, pero la ausencia de cambios versionados
   no demuestra por sí sola que nada cambiara fuera de Git.
7. **Este documento no cierra M6, no cierra 5.0.b, no cierra 5.0.c y no
   autoriza ADR 0025.**
8. La numeración de secciones citada se comprobó contra `26f6f94`; si un
   documento se reordena después, las referencias deben revisarse.

---

## Ver también

- [ADR 0020 — Capacidades componibles y planes de ejecución controlados](../adr/0020-capacidades-componibles-y-planes-de-ejecucion.md)
- [ADR 0021 — Contrato de inventario con Materiales (V1)](../adr/0021-contrato-de-inventario-con-materiales.md)
- [ADR 0023 — Cobertura desconocida de Materiales](../adr/0023-cobertura-desconocida-materiales-piloto.md)
- [ADR 0024 — Validación real de la frontera del código SAP y de la autenticación](../adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
- [Contrato funcional del Piloto 0.1](contrato-funcional.md)
- [Evidencia de las mediciones M3 y M5 (PC1)](evidencia-m3-m5-pc1.md)
- [Estándar de cierre de bloques](../project/BLOCK_CLOSURE_STANDARD.md)
