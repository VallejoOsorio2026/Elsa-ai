# Evidencia previa de M6 — semántica, procedencia y temporalidad de los campos de Materiales

Recopilación de la evidencia disponible sobre qué significan los campos que
devolverá el contrato de inventario, de dónde procede cada afirmación y qué
sigue sin poder verificarse.

> **Qué es este documento, y qué no es.**
>
> Es el **paso 0 de M6**: preservar evidencia verificable antes de decidir
> nada. **No cierra M6**, no decide semántica, no autoriza ADR 0025 y no
> autoriza ninguna implementación.
>
> **Incluye evidencia primaria del repositorio de Materiales**, leído en solo
> lectura en la revisión que el §2 identifica. Esa lectura resolvió parte de lo
> que antes era antecedente de conversación, y **dejó dos huecos explícitos**
> (§5.2 y §8). Lo que el repositorio no versiona sigue registrado como hueco,
> no como conclusión.

> **Regla 12 de [`CLAUDE.md`](../../CLAUDE.md).** Aquí no hay ningún código SAP
> real, ninguna descripción de material real, ningún fragmento de BOM, ningún
> JWT, ninguna clave, ningún correo, ninguna contraseña y ningún dato de
> inventario real. Solo nombres de campo, expresiones SQL, rutas, revisiones y
> conteos.

- Fecha de registro: **2026-09-20**
- Bloque: 5.0, subbloque **5.0.b**, punto **M6**
- Ejecución: sesión de asistente, en solo lectura sobre ambos repositorios

---

## 1. Propósito y alcance

**Propósito.** Reunir, con procedencia explícita, lo que hoy se sabe sobre la
semántica y la temporalidad de los campos de inventario, para que la decisión
normativa de M6 se tome sobre evidencia registrada y no sobre memoria de
conversaciones.

**Dentro del alcance:** leer el corpus normativo vigente de ELSA; leer el código
versionado de Materiales; verificar qué existe y qué no existe en cada uno,
contra revisiones identificadas; clasificar cada afirmación por su procedencia;
enumerar la evidencia que sigue faltando.

**Fuera del alcance, y no se hace aquí:** decidir la semántica de ningún campo;
resolver `dado_de_baja`; redactar ADR 0025; especificar, construir o autorizar
la fachada contractual, el `MaterialsPort` real, el adaptador, los tipos
contractuales o la composición BOM → Materiales; nombrar al Contract Owner;
tocar M8 o la prueba A6c; modificar cualquier ADR, el contrato funcional,
cualquier documento de cierre o cualquier archivo del repositorio de
Materiales.

M6 sigue con el estado que le da el corpus: **parcial y bloqueante**
([ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §25).
**Este documento no lo cambia.** Que la implementación sea ahora observable
**no sustituye** la decisión normativa: la informa.

---

## 2. Base auditada

**HECHO DEL REPOSITORIO.** Dos repositorios, dos revisiones, ambas en solo
lectura.

| Repositorio | Revisión | Fecha del commit | Alcance leído |
|---|---|---|---|
| `VallejoOsorio2026/Elsa-ai` | `26f6f94349cb6abb96c125c684966054820e9ebd` | — | `docs/`, `src/`, `tests/`, `supabase/` |
| `VallejoOsorio2026/papelsa-asistente-materiales` | `b0cb12b4440d95b5c4ec0a64ca619b31b36e26c3` | 2026-09-10 11:32:47 -0500 (`v1.3.0`) | `sql/`, `js/`, `docs/`, esquema |

Sobre la revisión de Materiales, dos comprobaciones necesarias para que la cita
sea inequívoca: es el `HEAD` de `main`, su rama por defecto; y la única otra
rama del repositorio, `docs/reglas-negocio.md`, **es ancestro de `main`** y
**no difiere en ningún archivo `.sql`**, de modo que no hay ambigüedad sobre
cuál es la versión vigente.

**Todas las búsquedas de ausencia sobre ELSA del §9.2 se ejecutaron contra
`26f6f94`** mediante `git grep <patrón> 26f6f94 -- <rutas>`, no contra el árbol
de trabajo. Este documento no existe en esa revisión y, por tanto, **no altera
sus propios recuentos**.

**No se consultó ningún entorno desplegado**: ni SAP, ni Supabase, ni
inventario activo, ni ninguna RPC. No se ejecutó SQL. No se usaron
credenciales.

> **PENDIENTE, y relevante para leer este documento.** En la fecha de registro,
> el PR #29 (`docs/adr-0020-0024-estado-aceptado`) estaba **abierto y sin
> fusionar**, verificado por los metadatos del PR. Ese PR solo cambia la línea
> `- Estado:` de los ADR 0020–0024 y **no toca ningún contenido citado aquí**.

---

## 3. Fuentes inspeccionadas y antecedentes

### 3.1 Fuentes normativas de ELSA, en `26f6f94`

| Documento | Secciones leídas |
|---|---|
| [ADR 0020](../adr/0020-capacidades-componibles-y-planes-de-ejecucion.md) | §11 y §11.1 (vigencia), §12 (ausencia), §13 (estados), §17 (contrato externo pendiente y tabla M1–M8) |
| [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) | §9, §9.1–§9.3 · §10, §10.1–§10.6 · §12, §12.1 · §14 · §16, §16.1–§16.5 · §19, §19.1, §19.2 · §22 · §25 |
| [ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md) | §6, §9, §16, §18 |
| [ADR 0024](../adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md) | §3, §11.2, §14, §16 |
| [Contrato funcional](contrato-funcional.md) | §10, §12, §14 |
| [Evidencia M3/M5](evidencia-m3-m5-pc1.md) | §2.5, §4.2, §5 |
| [Cierre de 5.0.c.1](../bloque-5-0-c-1-politica-ausencia-segura-cierre.md) y [cierre B9a–B9c](../bloque-5-0-b9a-b9c-cobertura-segura-cierre.md) | Solo para precisar qué garantizan y qué no |

Las numeraciones de sección se comprobaron contra los archivos en `26f6f94`.
**Ninguna de estas fuentes se modificó.**

### 3.2 Fuentes primarias de Materiales, en `b0cb12b`

| Ruta | Qué aporta |
|---|---|
| `sql/013_agrupacion.sql` | `buscar_agrupado`: agrupación y agregaciones (§5.1) |
| `sql/012_rendimiento.sql` | `buscar_materiales`: origen de `disponible`, `comprometido`, `ambito`, `ubicacion` y del vocabulario de coincidencia |
| `sql/008_importacion.sql` | Carga del inventario y `limpiar_material_antiguo` |
| `sql/011_clave_ubicacion.sql` | `clasificar_ubicacion`, que produce `ambito` |
| `sql/002_schema.sql` | `inventario_materiales` y `versiones_datos`: tipos y nulabilidad |
| `sql/029_recorte_columnas.sql` | Estado efectivo del esquema y comentario versionado de `ubicacion` |
| `docs/reglas-negocio.md` | RN-030 (disponibilidad), RN-033 (multiubicación), RN-034 (baja), RN-018/RN-019 (ámbito) |
| `js/search.js` | Invocación y consumo de `consultar_materiales` |
| `sql/028_banco_pruebas.sql` | Único artefacto de prueba del repositorio |

**Ningún archivo de Materiales se modificó.**

### 3.3 Antecedentes de conversación: qué pasó con ellos

**Registro histórico, conservado a propósito.** Un conjunto de afirmaciones
sobre la semántica V1 llegó originalmente **como texto de encargo**, sin
repositorio, commit, ruta, fragmento ni fecha. La lectura de `b0cb12b` permite
ahora contrastarlas una a una:

| Antecedente original | Estado tras leer `b0cb12b` |
|---|---|
| `ubicacion`: factual, opaca, nulable, sensible al snapshot | **Confirmado** por evidencia primaria (§7) |
| `ambito`: derivado, regla verificable, no representa cobertura | **Confirmado** por evidencia primaria (§6.3) |
| `disponible` / `comprometido`: derivados por reglas conocidas | **Confirmado**, con la fórmula exacta (§5.3) |
| Totales: reglas conocidas | **Confirmado** (§5.3) |
| `match_origin`: regla conocida | **Parcialmente confirmado**: el vocabulario está versionado en `buscar_materiales`, pero la función que el cliente llama no lo está (§5.2) |
| `descripcion`, `unidad`, `material_antiguo`: factuales de SAP, con la duda de la agregación `max()` | **La duda queda resuelta**: la agregación existe y es independiente por campo (§5.1) |
| `dado_de_baja`: regla no versificable, y **excluido del contrato V1** | **La no verificabilidad queda confirmada** (§8). **La exclusión sigue siendo antecedente no versionado** y es **DECISIÓN NORMATIVA PENDIENTE** |

**Ningún antecedente se borra.** Los que la evidencia confirma pasan a citar su
fuente primaria; el único que sigue sin respaldo —la exclusión de
`dado_de_baja`— conserva su clasificación original y su naturaleza declarada.

### 3.4 Clasificación usada

| Marca | Significado |
|---|---|
| **EVIDENCIA PRIMARIA VERIFICADA** | Leída en el código versionado, con repositorio, revisión, ruta y línea |
| **EVIDENCIA PRIMARIA PARCIAL** | Parte está versionada y parte no; el hueco se nombra |
| **DECLARACIÓN NORMATIVA EXISTENTE** | Un ADR o documento vigente lo establece. Es norma, no observación del sistema real |
| **ANTECEDENTE DE CONVERSACIÓN NO REVERIFICADO** | Llegó por conversación, sin fuente citable, y el código no lo respalda |
| **AUSENCIA VERIFICADA EN EL REPOSITORIO INSPECCIONADO** | Se buscó en rutas y revisión concretas y no está. **No afirma que no exista en el sistema desplegado** |
| **DECISIÓN NORMATIVA PENDIENTE** | Requiere una decisión humana registrada en un ADR |

> **Una precisión que gobierna todo el documento.** Que un símbolo no esté en el
> repositorio de Materiales significa que **su definición no está versionada en
> la revisión inspeccionada**, no que la función no exista en el sistema
> desplegado. Los dos huecos del §5.2 y del §8 se enuncian siempre así.

---

## 4. Estado de la evidencia solicitada

| # | Evidencia | Estado | Dónde |
|---|---|---|---|
| **E1** | Función de agrupación y sus reglas | **PRIMARIA VERIFICADA** | §5.1 |
| **E2** | Función de consulta que usa el cliente | **PRIMARIA PARCIAL** | §5.2 |
| **E3** | Reglas de `disponible` y `comprometido` | **PRIMARIA VERIFICADA** | §5.3 |
| **E4** | Regla y naturaleza de `ambito` | **PRIMARIA VERIFICADA** | §6.3 |
| **E5** | Regla de `dado_de_baja` | **PRIMARIA PARCIAL** | §8 |
| **E6** | Definición y tratamiento de `ubicacion` | **PRIMARIA VERIFICADA** | §7 |
| **E7** | Regla de limpieza de `material_antiguo` | **PRIMARIA VERIFICADA** | §5.4 |
| **E8** | Esquema de cargas y versiones | **PRIMARIA VERIFICADA**, y **pertenece a M4**, no a M6 | §10 |

---

## 5. La implementación observada en Materiales

### 5.1 E1 — la agrupación por material

**EVIDENCIA PRIMARIA VERIFICADA.** `sql/013_agrupacion.sql:26`, función
`public.buscar_agrupado(p_consulta text, p_limite integer DEFAULT 5)`,
`LANGUAGE sql STABLE SECURITY DEFINER`. **Definición única, nunca redefinida**
en la revisión inspeccionada.

- **Origen de las filas:** `public.buscar_materiales(p_consulta, p_limite * 8)`
  (línea 47). El margen está justificado en comentario: un material puede
  ocupar varias filas.
- **Clave de agrupación:** `group by e.material` (línea 81). **Una sola
  columna.**

Agregación **campo por campo**, tal como está escrita (líneas 52–79):

| Campo devuelto | Expresión exacta |
|---|---|
| `descripcion` | `max(e.descripcion)` |
| `puntaje` | `max(e.puntaje)` |
| `origen` | `(array_agg(e.origen order by e.puntaje desc))[1]` |
| `unidad` | `max(e.unidad)` |
| `material_antiguo` | `max(e.material_antiguo)` |
| `total_disponible` | `sum(e.disponible)` |
| `total_comprometido` | `sum(e.comprometido)` |
| `dado_de_baja` | `bool_or(es_material_baja(normalizar_texto(e.descripcion)))` |
| `ubicaciones` | `jsonb_agg(jsonb_build_object(…) order by <prioridad de ámbito>, e.disponible desc)` |

**Tres hechos que se siguen de esa tabla, y que conviene no confundir entre
sí.**

**Primero: los escalares se eligen por expresiones independientes.**
`descripcion`, `unidad`, `material_antiguo` y `puntaje` son cuatro `max()`
evaluados por separado sobre el grupo; `origen` es una quinta selección, tomada
de la fila de mayor puntaje. **El código no garantiza que todos procedan de una
misma fila original.** Que el grupo pueda tener más de una fila está demostrado
por la clave de carga: `on conflict (version_id, material, centro, almacen)`
(`sql/008_importacion.sql:396`).

Si en los datos reales esos campos fueran idénticos en todas las filas de un
material, el `max()` sería inocuo. **Eso sería una propiedad del dato, no una
garantía del código**, y el esquema no la impone.

**Segundo: `max()` sobre texto es máximo lexicográfico.** No hay `ORDER BY`
temporal ni columna de fecha implicada en esas expresiones. **No representa una
selección por recencia**, y leerla así sería atribuirle una semántica que no
tiene.

**Tercero: dentro de `ubicaciones` la coherencia por fila sí se conserva.**
Cada elemento del array se construye con `jsonb_build_object` sobre una misma
fila `e` (líneas 61–69), de modo que `centro`, `almacen`, `ubicacion`,
`ambito`, `disponible` y `comprometido` **de un mismo elemento siempre
proceden de la misma fila**. La selección independiente afecta a los escalares
del nivel superior, no a los elementos de esta colección.

**Orden final:** `order by a.dado_de_baja asc, a.puntaje desc,
a.total_disponible desc` (línea 96). Ver §8.

**Pruebas:** ninguna cubre `buscar_agrupado` (§9.1).

### 5.2 E2 — la función que el cliente llama

**EVIDENCIA PRIMARIA PARCIAL.**

**Lo que está versionado.** `js/search.js:24` invoca
`db.rpc('consultar_materiales', { p_consulta, p_limite, p_desde })`. El cliente
consume un **objeto envoltorio** —`nivel`, `total`, `hay_mas`, `mensaje`,
`resultados[]`— y cada elemento de `resultados` se renderiza con los mismos
campos que produce la salida agrupada, incluidas las `ubicaciones` con sus seis
atributos.

**El hueco.** **La definición SQL de `consultar_materiales` no está versionada
en `b0cb12b`**: aparece una sola vez en todo el repositorio, y es esa
invocación. Lo mismo ocurre con `consultar_sin_existencias`. De los veinte RPC
que el cliente invoca, **cuatro no tienen definición en el repositorio**.

**Lo que sí puede afirmarse, porque su fuente aguas arriba está versionada.**
`buscar_materiales` (`sql/012_rendimiento.sql:143`) construye su conjunto de
candidatos admitiendo en la **misma** consulta código exacto, código antiguo,
coincidencia por referencia, por medida y por similitud de descripción, y
ordena por puntaje total. De ahí se sigue un hallazgo técnico:

> La implementación versionada aguas arriba permite que una consulta que
> contiene un código exacto coexista con candidatos no exactos en el mismo
> resultado.

El vocabulario de coincidencia que esa función emite está versionado
(`sql/012_rendimiento.sql:249-254`) y tiene **seis valores**: `'codigo'`,
`'codigo antiguo'`, `'referencia'`, `'medida'`,
`'descripcion aproximada'`, `'descripcion'`.

**Lo que NO se atribuye a `consultar_materiales`:** sus filtros, su
paginación real, el contenido exacto de su envoltorio, sus prioridades y
cualquier garantía de lookup. Nada de eso está versionado, y no se infiere.

### 5.3 E3 — `disponible` y `comprometido`

**EVIDENCIA PRIMARIA VERIFICADA.** `sql/012_rendimiento.sql:219-221`:

```sql
coalesce(i.stock_libre_utilizacion,0)
  + coalesce(i.stock_consignacion,0)   as disponible,
coalesce(i.stock_proyectos,0)          as comprometido,
```

Tres niveles que no deben mezclarse:

| Nivel | Campos | Dónde se determina |
|---|---|---|
| **Fuente SAP persistida** | `stock_libre_utilizacion`, `stock_consignacion`, `stock_proyectos` | Columnas `numeric` **nulables** de `inventario_materiales` (`sql/002_schema.sql`), cargadas vía `convertir_numero` |
| **Derivado en consulta** | `disponible`, `comprometido` | Calculados por `buscar_materiales`; **nunca nulos**, porque `coalesce(...,0)` absorbe el nulo |
| **Agregado por material** | `total_disponible`, `total_comprometido` | `sum()` en `buscar_agrupado` (§5.1) |

**La regla está publicada y versionada.** `docs/reglas-negocio.md:117-128`,
**RN-030**: *«Disponible: `Stock Libre_Utilizacion` + `Stock consignación`.
Comprometido: `Stock Proyectos`. No se oculta ni se suma al disponible.»* La
prosa y el SQL **coinciden**.

De ahí se sigue un hecho, y solo un hecho: **la regla es técnicamente
verificable desde el repositorio**, porque tanto su enunciado como su
implementación están versionados. **Qué valor deba llevar `rule_verifiable` en
el contrato de ELSA es una decisión normativa que este documento no toma.**

### 5.4 E7 — `material_antiguo`

**EVIDENCIA PRIMARIA VERIFICADA.** Transformación aplicada **en la carga**,
`sql/008_importacion.sql:301-305`:

```sql
case
  when coalesce(p_texto,'') = '' then null
  when p_texto like '%00:00:00%' then null   -- corrupcion de origen
  else trim(p_texto)
end
```

Hechos, sin interpretación añadida:

- procede de SAP y es **nulable**;
- vacío → **`NULL`**;
- valor que contiene el patrón de corrupción → **`NULL`**;
- **la fila se conserva**: no se descarta ni se sustituye por nada;
- cualquier otro valor se conserva con `trim`;
- la función es `IMMUTABLE` y se invoca en el `INSERT` (línea 388), junto con
  su forma normalizada para búsqueda (línea 391).

El comentario versionado justifica el descarte: un código falso llevaría al
ingeniero a buscar en SAP un dato inventado.

**En la representación agrupada** el campo llega al consumidor a través de
`max(e.material_antiguo)` (§5.1), con la salvedad de mezcla de filas que allí
se describe.

---

## 6. Ubicación, ámbito y cobertura son tres cosas distintas

### 6.1 Dos «ubicaciones» dentro de ELSA que no son la misma

**EVIDENCIA PRIMARIA VERIFICADA**, en ELSA `26f6f94`:

| Ruta y línea | Dominio | Qué es |
|---|---|---|
| `src/elsa/ingestion/sap_htm.py:465`, `:524`, `:759` | Activos y BOM | **Ubicación técnica** (`floc`, `funcloc`): dónde está instalado un equipo. **Propiedad de ELSA** |
| `src/elsa/core/coverage_policy.py:21`, `:99` | Inventario | Prosa y un miembro de enum sobre las ubicaciones de existencias **declaradas por la plantilla** de ELSA, no el campo de Materiales |

### 6.2 Qué está normado en ELSA y qué lo respalda ahora

| Aspecto de `ubicacion` de inventario | Norma en ELSA | Respaldo primario en Materiales |
|---|---|---|
| El blanco se preserva como **nulo** | ADR 0021 §10.1 | **Confirmado** (§7) |
| **Nunca se hereda de otra fila** | ADR 0021 §10.1 | **Confirmado**, con su justificación versionada (§7) |
| Es opaca y se muestra **sin interpretar** | **Sin normar** | **Confirmado en la implementación** (§7) |
| Es sensible al snapshot | **Sin normar** | **Confirmado** (§11) |
| Campo ausente vs. nulo vs. desconocido | **Sin normar** | Nulabilidad observable (§9) |

### 6.3 E4 — `ambito` no es cobertura

**EVIDENCIA PRIMARIA VERIFICADA.**

- **Nombre persistido:** columna `ambito_ubicacion` de `inventario_materiales`
  (`sql/002_schema.sql`), expuesta como `ambito` por `buscar_materiales`.
- **Se determina durante la carga** y **queda persistida**: el `INSERT` de
  `cargar_lote_inventario` la calcula en `sql/008_importacion.sql:392`.
- **Regla:** `public.clasificar_ubicacion(p_centro, p_almacen)`,
  `sql/011_clave_ubicacion.sql:21-36`, función `IMMUTABLE`. Un `CASE` sobre
  códigos de centro que produce un **vocabulario cerrado de cinco valores**:
  `'molino'`, `'planta'`, `'virtual'`, `'remoto'`, `'otra'`. Los códigos de
  centro concretos **no se reproducen aquí**: el propio repositorio de
  Materiales pide que no se propaguen fuera de esa función.
- **Defecto conocido y versionado:** la función **recibe `p_almacen` y no lo
  usa**; clasifica solo por centro. Registrado por Materiales en
  `docs/pendientes.md` con severidad «Menor».
- **Consecuencia temporal:** al estar persistida, **una modificación futura de
  la función no reclasifica las cargas anteriores**.
- **Nulabilidad:** la columna es nulable; el valor efectivo nunca lo es, porque
  la función tiene rama `else`. Un centro desconocido cae en `'otra'` y **no
  oculta el material**.

**La afirmación que importa, enunciada con prudencia:**

> La implementación inspeccionada define `ambito` como una clasificación
> asociada a **una fila** del inventario. **No existe evidencia versionada de
> que represente el alcance cubierto por una carga**, ni de que sea equivalente
> a `coverage.observed_scope`.

Esto es coherente con lo que
[ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §7.2 ya exige
—que `observed_scope` provenga de metadata de ingestión y no de datos de
negocio— y lo respalda ahora con evidencia primaria en lugar de con una
deducción. **`ambito` no alimenta la cobertura y no se convierte en metadata de
cobertura.**

---

## 7. E6 — `ubicacion` y `ubicaciones` no son el mismo dato

**EVIDENCIA PRIMARIA VERIFICADA.** Son dos conceptos de **nivel distinto**, y
el plural no es el plural del singular.

**`ubicacion` — singular, por fila:**

- columna `text` de `inventario_materiales` (`sql/002_schema.sql`), **nulable**;
- procede de SAP y solo se recorta: en la carga,
  `nullif(trim(coalesce(f->>'ubicacion','')), ''))`
  (`sql/008_importacion.sql:386`) convierte el blanco en **`NULL`**;
- **no se hereda de la fila anterior, y no se inventa.** El comentario
  versionado de la columna (`sql/029_recorte_columnas.sql:60-63`) lo registra
  junto a su motivo: un porcentaje apreciable de filas llega vacía, está
  pendiente confirmar si son vacíos legítimos o supresión de repetidos en el
  reporte de origen, y *«incompleto nunca es peor que incorrecto»*;
- **no se concatena, no se agrega y no se selecciona con `max`/`min`**;
- **no se interpreta**: no participa en el ranking, no decide disponibilidad y
  no se usa para cobertura. El cliente solo la muestra si existe;
- **puede cambiar entre cargas**: la consulta filtra por la versión activa y
  nada la fija entre snapshots.

**`ubicaciones` — plural, agregado por material:**

- campo `jsonb` **construido** por `buscar_agrupado`
  (`sql/013_agrupacion.sql:61-79`);
- cada objeto contiene **centro, almacén, ubicación, ámbito, disponible y
  comprometido**, y esos seis atributos **proceden de una misma fila** (§5.1).

> `ubicacion` y `ubicaciones` no representan el mismo nivel de dato: la primera
> pertenece a una fila; la segunda es una colección agregada de filas y
> contiene `ubicacion` como **uno de sus atributos**.

---

## 8. E5 — `dado_de_baja`: dos huecos y una discrepancia

**EVIDENCIA PRIMARIA PARCIAL.**

**Lo que está verificado:**

- **no es una columna persistida**: no existe en el esquema;
- **se calcula durante la consulta**, dentro de la agregación, con la
  expresión `bool_or(public.es_material_baja(public.normalizar_texto(e.descripcion)))`
  (`sql/013_agrupacion.sql:59-60`);
- `bool_or` implica que **basta una fila del material** para marcar la tarjeta
  entera;
- la **regla de negocio está publicada y versionada**:
  `docs/reglas-negocio.md:92-101`, **RN-034**, que nombra tres marcadores de
  baja presentes en la descripción y ordena que **no se oculten**, porque
  algunos conservan existencias reales.

**El hueco:** **`es_material_baja` no tiene definición versionada en
`b0cb12b`.** Se invoca en `sql/013_agrupacion.sql:59` y no se define en ningún
archivo del repositorio. El archivo cuyo nombre lo prometería,
`sql/016_materiales_baja.sql`, lleva por dentro una cabecera distinta y trata
de cierre de solicitudes por inactividad.

En consecuencia, **no puede determinarse desde el repositorio** si la
coincidencia es por subcadena o por palabra, cómo trata acentos y mayúsculas
más allá de lo que haga `normalizar_texto`, ni qué devuelve ante un valor nulo.
Esto **confirma con evidencia primaria** el `rule_verifiable: false` que
[ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §10.3 ya
anticipaba, y lo hace por la razón que aquel apartado daba.

**Tampoco existen pruebas automáticas** que demuestren esa implementación
(§9.1).

### 8.1 Discrepancia entre norma e implementación

**INCONSISTENCIA ENTRE NORMA E IMPLEMENTACIÓN — DECISIÓN PENDIENTE.**

| Fuente | Qué dice |
|---|---|
| [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §10.3 | *«El material no se oculta ni se desprioriza por llevar esta señal.»* |
| Materiales, `sql/013_agrupacion.sql:96` | **No lo oculta**, pero `order by a.dado_de_baja asc, …` **sitúa después** los materiales marcados. RN-034 declara ese tratamiento de forma expresa: se muestran al final, con advertencia |

Las dos afirmaciones coinciden en lo esencial —el material **nunca se oculta**—
y difieren en la priorización. **Ninguno de los dos lados se corrige aquí.**

### 8.2 La inclusión en V1 sigue sin decidirse

**DECISIÓN NORMATIVA PENDIENTE.**

| Posición | Procedencia | Clasificación |
|---|---|---|
| **Incluido** en el contrato V1 como `DERIVED_BY_MATERIALES`, con `rule_verifiable: false` | ADR 0021 §10.2 y §10.3, en `26f6f94`. **Está versionado** | **DECLARACIÓN NORMATIVA EXISTENTE** |
| **Excluido** del contrato V1 | Texto de encargo recibido en conversación. **No está versionado en ninguna parte** | **ANTECEDENTE DE CONVERSACIÓN NO REVERIFICADO** |

La evidencia primaria de este apartado **informa** la decisión —confirma la no
verificabilidad y añade la discrepancia de §8.1— pero **no la toma**.
Resolverla exige un ADR (regla 25 de [`CLAUDE.md`](../../CLAUDE.md)), **que
este trabajo no autoriza**.

---

## 9. Matriz de campos

Una fila por campo. Las celdas sin evidencia dicen «sin determinar»; **no se
rellenan por intuición**.

«Momento de determinación» distingue tres instantes: **carga** (al insertar la
fila), **consulta** (al ejecutar `buscar_materiales`) y **agregación** (al
ejecutar `buscar_agrupado`).

| Campo | Origen | Transformación | Persistido | Agregado / derivado | Nulabilidad | Momento de determinación | Verificación |
|---|---|---|---|---|---|---|---|
| `material` | SAP | `trim` en carga | **Sí** | No | **`not null`** en el esquema | Carga | **PRIMARIA VERIFICADA** |
| `descripcion` (`texto_breve_material`) | SAP | `trim` en carga | **Sí** | **Sí — `max()` por material** | Columna nulable | Carga; **valor expuesto elegido en agregación** | **PRIMARIA VERIFICADA** |
| `unidad` (`unidad_medida_base`) | SAP | `trim` en carga | **Sí** | **Sí — `max()` por material** | Columna nulable | Carga; **valor expuesto elegido en agregación** | **PRIMARIA VERIFICADA** |
| `material_antiguo` | SAP | `limpiar_material_antiguo`: vacío y corrupción → `NULL`; resto `trim` | **Sí** | **Sí — `max()` por material** | **Nulable, y la regla produce nulos** | Carga; **valor expuesto elegido en agregación** | **PRIMARIA VERIFICADA** |
| `centro`, `almacen` | SAP | `trim` en carga | **Sí** | No (viajan por fila dentro de `ubicaciones`) | Columnas nulables | Carga | **PRIMARIA VERIFICADA** |
| `ubicacion` | SAP | `nullif(trim(coalesce(…,'')), '')` | **Sí** | **No se agrega ni se hereda** | **Nulable**; el blanco se guarda como `NULL` | Carga | **PRIMARIA VERIFICADA** |
| `stock_libre_utilizacion`, `stock_consignacion`, `stock_proyectos` | SAP | `convertir_numero(valor, unidad)` | **Sí** | No | **`numeric` nulables** | Carga | **PRIMARIA VERIFICADA** |
| `disponible` | — | — | **No** | **Derivado en consulta**: suma de dos conceptos, cada uno `coalesce(…,0)` | **Nunca nulo** | Consulta | **PRIMARIA VERIFICADA** |
| `comprometido` | — | — | **No** | **Derivado en consulta**: proyección de un concepto, `coalesce(…,0)` | **Nunca nulo** | Consulta | **PRIMARIA VERIFICADA** |
| `total_disponible`, `total_comprometido` | — | — | **No** | **Agregados — `sum()` por material** | No nulos en la práctica | Agregación | **PRIMARIA VERIFICADA** |
| `ambito` (`ambito_ubicacion`) | — | — | **Sí** | **Derivado en carga** por `clasificar_ubicacion`; vocabulario cerrado de cinco valores | Columna nulable; valor efectivo nunca nulo | **Carga**, y queda congelado | **PRIMARIA VERIFICADA** |
| `ubicaciones` | — | — | **No** | **Agregado — `jsonb_agg`**; cada objeto conserva la coherencia de **una** fila | — | Agregación | **PRIMARIA VERIFICADA** |
| `dado_de_baja` | — | — | **No** | **Derivado en agregación** — `bool_or(es_material_baja(...))` sobre la descripción normalizada | Sin determinar | Agregación | **PRIMARIA PARCIAL**: la función de la regla no está versionada |
| `origen` | — | — | **No** | **Metadata de coincidencia**; seleccionado con `array_agg(… order by puntaje desc)[1]` | — | Consulta (valor) y agregación (selección) | **PRIMARIA PARCIAL**: versionado en `buscar_materiales`; la función que llama el cliente, no |
| `puntaje` | — | — | **No** | **Metadata de coincidencia** — `max()` por material | — | Consulta y agregación | **PRIMARIA VERIFICADA** |
| **M4 — metadata de versión y carga** | — | — | **Sí** | — | Ver §10 | Carga | **PRIMARIA VERIFICADA**, y **fuera de M6** |

> **Precaución deliberada sobre `descripcion`, `unidad` y `material_antiguo`.**
> Su procedencia original es SAP y su transformación de carga está declarada,
> pero **el valor que llega al consumidor se elige por una agregación
> independiente**. Por eso la matriz separa los tres planos y **no los declara
> «factuales por fila»**. Qué clase de procedencia les corresponda en el
> contrato de ELSA es **decisión normativa pendiente** (§12, Q2).

---

## 10. E8 — metadata de carga: evidencia secundaria, y pertenece a M4

**EVIDENCIA PRIMARIA VERIFICADA**, registrada aquí porque apareció al leer el
esquema. **Corresponde a M4, no a M6**, y no se amplió la auditoría para
perseguirla.

Tabla `public.versiones_datos`, `sql/002_schema.sql:38`:

| Columna | Tipo y restricción | Qué representa |
|---|---|---|
| `id` | `uuid`, clave primaria | Identificador de la carga |
| `numero` | `integer generated always as identity` | Número de versión |
| `estado` | `text not null default 'preparando'`, con `check` sobre cuatro valores | Ciclo de vida de la carga |
| `iniciado_en` | `timestamptz not null default now()` | **Inicio de la carga** |
| `finalizado_en` | `timestamptz` — **nulable** | **Fin de la carga** |
| `archivo_nombre` | `text` — **nulable** | Etiqueta del archivo de origen |
| `filas_esperadas` | `integer` — nulable | Recuento declarado |
| `filas_cargadas` | `integer not null default 0` | Recuento efectivo |
| `cargado_por`, `resultado`, `observaciones` | nulables | Metadata adicional |

Además, cada fila de inventario lleva `cargado_en timestamptz not null default
now()`: la marca de **inserción de esa fila**.

Conclusiones permitidas, y sus límites:

- Materiales **versiona sus cargas**, con estado, número, recuentos y etiqueta
  de archivo de origen.
- Existen marca de inicio y marca de finalización de la carga.
- **No existe ninguna columna de fecha de extracción desde SAP** en el esquema
  inspeccionado.

> `iniciado_en`, `finalizado_en` y las marcas de inserción representan **eventos
> de carga en Materiales**. **No se interpretan como `extracted_at`.**

> `archivo_nombre` es una **etiqueta opaca**; **no se utiliza para inferir una
> fecha de extracción**, conforme a
> [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §9.3.

**Esto no declara M4 cerrado.** Que la metadata de vigencia exista en la fuente
no implica que el contrato la transporte ni que ELSA la consuma.

---

## 11. Temporalidad observada

Lo que el código permite demostrar. **No se afirma estabilidad donde el
repositorio no la garantiza.**

| Campo | Momento de determinación | Sensibilidad demostrable al snapshot | Evidencia |
|---|---|---|---|
| `material`, `descripcion`, `unidad`, `centro`, `almacen`, `ubicacion` | **Carga** | **Sí.** Nada garantiza estabilidad entre versiones | `INSERT` de `cargar_lote_inventario`; filtro por versión activa en `buscar_materiales` |
| `material_antiguo` | **Carga**, con limpieza | **Sí** | `sql/008_importacion.sql:301-305, 388` |
| `stock_libre_utilizacion`, `stock_consignacion`, `stock_proyectos` | **Carga** | **Sí** | `sql/002_schema.sql`; `convertir_numero` |
| `ambito` | **Carga**, persistido | **Sí**, y además **congelado**: un cambio de la función clasificadora no reclasifica lo ya cargado | `sql/011_clave_ubicacion.sql`; `sql/008_importacion.sql:392` |
| `disponible`, `comprometido` | **Consulta**, sobre datos de la carga | **Sí** | `sql/012_rendimiento.sql:219-221` |
| `origen`, `puntaje` | **Consulta** | **Sí**: dependen de la consulta y del corpus de la versión activa | `sql/012_rendimiento.sql:234-257` |
| `total_disponible`, `total_comprometido` | **Agregación** | **Sí** | `sql/013_agrupacion.sql:57-58` |
| `descripcion`, `unidad`, `material_antiguo` **tal como se exponen** | **Agregación** (`max()` por campo) | **Sí**, y con la salvedad de §5.1 | `sql/013_agrupacion.sql:52-56` |
| `ubicaciones` | **Agregación** (`jsonb_agg`) | **Sí** | `sql/013_agrupacion.sql:61-79` |
| `dado_de_baja` | **Agregación** | **Sí**, indirectamente: depende de la descripción cargada **y** de una función no versionada, que puede cambiar sin dejar rastro en el repositorio | `sql/013_agrupacion.sql:59-60` |

**Ninguna columna de negocio lleva marca temporal propia.** La única fecha por
fila es la de inserción, que registra cuándo se cargó, no cuándo se extrajo de
SAP.

---

## 12. Preguntas para el siguiente trabajo normativo

**Ninguna se responde aquí.** Lo que cambia es qué evidencia está disponible
para responderlas.

### Con evidencia suficiente para pasar a decisión normativa

| # | Pregunta | Evidencia que la sostiene |
|---|---|---|
| **Q2** | ¿Un campo factual elegido por una agregación sigue siendo `FACTUAL_SAP`, o necesita una clase propia? | **E1 verificada** (§5.1): los escalares se eligen por expresiones independientes |
| **Q4** | ¿Se escribe explícitamente que `ambito` no es `coverage.observed_scope`? | **E4 verificada** (§6.3): es una clasificación por fila, sin evidencia de representar alcance |
| **Q5** | ¿Se norma que `ubicacion` es opaca, nulable, no heredada y sensible al snapshot? | **E6 verificada** (§7): las cuatro dimensiones, con su justificación versionada |
| **Q7** | ¿`ubicaciones` designa el mismo concepto que `ubicacion`? | **E6 verificada** (§7): **no**, y son de nivel distinto |
| **Q8**, parcialmente | ¿Cómo se distinguen campo ausente, valor nulo y valor desconocido? | **E3, E6 y E7 verificadas**: nulabilidad establecida para los campos persistidos y derivados |
| — | ¿Qué `rule_reference` y `rule_verifiable` corresponden a `disponible` y `comprometido`? | **E3 verificada** (§5.3): regla publicada e implementación versionada |

### Todavía con evidencia parcial

| # | Pregunta | Qué falta |
|---|---|---|
| **Q1** | ¿`dado_de_baja` entra o sale del contrato V1? | **E5 parcial** (§8): la función de la regla no está versionada, y hay una discrepancia sin resolver con ADR 0021 §10.3 |
| **Q3** | ¿Qué temporalidad se declara campo a campo? | Decidible para casi todos (§11); **no** para `dado_de_baja`, que depende de una función no versionada |
| **Q6** | ¿Cuál es el vocabulario cerrado de `match_origin` y cómo se hace verificable el invariante de ADR 0021 §6? | **E2 parcial** (§5.2): el vocabulario está versionado aguas arriba, pero la función que el cliente llama no lo está y podría no conservarlo |
| **Q8**, el resto | Distinción ausente / nulo / desconocido para campos producidos por funciones no versionadas | Los dos huecos de §5.2 y §8 |

### Decisiones que permanecen expresamente abiertas

- La inclusión o exclusión de `dado_de_baja` en V1 (§8.2).
- La discrepancia de priorización entre ADR 0021 §10.3 y la implementación
  (§8.1).
- La clase de procedencia de `descripcion`, `unidad` y `material_antiguo` a la
  luz de la agregación (§9).
- Qué valor de `rule_verifiable` corresponde a cada campo derivado.

**Dependencias con M1, M4 y M7, sin sobregeneralizarlas:**

- **M1** necesita las respuestas a Q2–Q8 para especificar qué transporta la
  fachada, pero **no hace falta que la fachada exista** para decidirlas.
- **M4** es un eje distinto y **no lo resuelve M6**. `extracted_at: null` es una
  **decisión** registrada en ADR 0021 §9.3, no un defecto, y el §10 de este
  documento la respalda con evidencia: en la fuente tampoco existe esa fecha.
- **M7** aporta el dueño que publicaría y versionaría las reglas hoy ausentes.
  Que el ocupante siga sin asignarse es un pendiente real y una puerta previa al
  primer tester, pero **ninguna fuente lo convierte en impedimento para
  recopilar evidencia ni para redactar un ADR**.

---

## 13. Evidencia que sigue pendiente

**E1, E3, E4, E6 y E7 dejan de ser pendientes.** Lo que queda:

| # | Evidencia solicitada | Por qué falta | A quién corresponde |
|---|---|---|---|
| **P1** | Definición de `consultar_materiales` | **No está versionada** en `b0cb12b`. Sin ella no se conocen su envoltorio real, sus filtros, su paginación ni sus garantías de lookup (§5.2) | **Materiales** |
| **P2** | Definición de `es_material_baja` | **No está versionada** en `b0cb12b`. Sin ella, RN-034 no es verificable (§8) | **Materiales** |
| **P3** | Restricción única efectiva de `inventario_materiales` | El esquema declara una clave de dos columnas y la carga usa `on conflict` sobre cuatro. **El cambio no está versionado.** Se registra porque **es lo que hace posible la agrupación multifila** del §5.1 | **Materiales** |
| **P4** | Pruebas que protejan las reglas de M6 | No existen (§14) | **Materiales**, bajo el Contract Owner de M7 |

Las tres primeras se obtendrían versionándolas o leyéndolas del catálogo de la
base. **No se piden aquí**: exigirían acceso a un entorno desplegado, que está
fuera del alcance de este trabajo.

> **Ausencia en el repositorio no equivale a ausencia desplegada.** P1 y P2
> afirman que esas definiciones **no están versionadas en la revisión
> inspeccionada**. El sistema desplegado las tiene, porque el cliente las invoca
> y la agrupación las usa.

---

## 14. Implementación y pruebas

### 14.1 En Materiales, `b0cb12b`

**AUSENCIA VERIFICADA EN EL REPOSITORIO INSPECCIONADO.** El único artefacto de
prueba es `sql/028_banco_pruebas.sql`, un **banco de medición de posiciones de
ranking** que invoca `buscar_materiales` y exige sesión activa e inventario
real. **No se ejecutó**, y hacerlo habría requerido un entorno desplegado.

**Ninguna prueba cubre** `buscar_agrupado`, las fórmulas de stock,
`es_material_baja`, `limpiar_material_antiguo` ni `clasificar_ubicacion`. No
hay framework de pruebas ni integración continua en el repositorio.

### 14.2 En ELSA, `26f6f94`

**EVIDENCIA PRIMARIA VERIFICADA.**

| Ruta | Líneas | Qué es |
|---|---|---|
| `src/elsa/core/capability_outcomes.py` | 319 | Política del **consumidor** sobre resultado y ausencia |
| `src/elsa/core/coverage_policy.py` | 299 | Política del **consumidor** sobre cobertura |
| `src/elsa/core/answers.py` | 210 | `AnswerStatus`, `Sufficiency` y `AnswerWarning` |
| `tests/test_absence_safety.py` | 249 | Garantías A6, A6b, A18, A19 |
| `tests/test_coverage_policy.py` | 679 | Garantías A20, A20b, A21 |
| `tests/test_contract_materials.py` | 43 | Contrato del puerto **legado**, contra el fake |

Estos módulos deciden sobre un resultado ya obtenido y **no conocen ningún
campo de Materiales**. Su cierre está documentado y **este trabajo no lo
reabre**; tampoco traslada esas políticas a Materiales. La limitación de
integración registrada al cerrar B9a–B9c —que **todavía no tienen llamador** en
un camino de respuesta real— sigue siendo cierta, y **dónde conectarlas no se
decide aquí**.

El único vocabulario de campos de inventario presente en código de ELSA es
`AssertedInventoryField` en `coverage_policy.py`, con cinco miembros. El módulo
declara que **no es el esquema de la respuesta de Materiales**, sino la
declaración de qué piensa afirmar la plantilla.

### 14.3 Ausencias verificadas en ELSA

**AUSENCIA VERIFICADA EN EL REPOSITORIO INSPECCIONADO.** Búsqueda
case-insensitive con `git grep -i <patrón> 26f6f94 -- src tests`. **Cero
archivos con coincidencia** para: `buscar_agrupado`, `FACTUAL_SAP`,
`DERIVED_BY_MATERIALES`, `MATCH_METADATA`, `INVENTORY_METADATA`,
`rule_reference`, `rule_verifiable`, `match_origin`, `attribution`,
`dado_de_baja`, `ambito`, `comprometido`, `total_disponible`,
`total_comprometido`, `material_antiguo`, `contract_version`, `observed_scope`,
`expected_scope`, `extracted_at`, `row_count`, `source_file_label` y
`requires_fresh_inventory`.

Tres resultados exigen precisión, porque un recuento crudo engañaría:

| Patrón | Resultado crudo | Qué es realmente |
|---|---|---|
| `loaded_at` | 1 archivo | **Falso positivo.** Es `uploaded_at` en `src/elsa/ports/knowledge.py:173`, del ciclo documental. **El `loaded_at` de inventario no existe en ELSA** |
| `ubicacion` | 5 líneas | Dos dominios distintos (§6.1). Ninguna es el campo de inventario |
| `disponible` | varias | Prosa española con el sentido «no disponible», en puertos sin relación con inventario |

Además, `inventory_freshness_unknown` aparece **solo como prosa** en
`src/elsa/core/coverage_policy.py:290`; **no existe** como miembro de
`AnswerWarning`.

> Estas ausencias significan que **ELSA no ha implementado el contrato**, que es
> lo que ADR 0021 §19.1 ya declara.

### 14.4 El puerto legado

`src/elsa/ports/materials.py:32` declara
`get_material(code) -> Material | None` con la documentación «o `None` si no
existe», y `Material` tiene dos campos.
[ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §14 ordena
corregir esa semántica **antes** de implementar el adaptador real. Se registra
el hecho. **Este documento no modifica el puerto, su adaptador ni sus
pruebas**, y la expectativa obsoleta de `tests/test_contract_materials.py`
tampoco se toca: corregirla es trabajo de M1, y no autoriza eliminar esa suite.

---

## 15. Límites de esta auditoría

1. **Materiales fue inspeccionado** en
   `b0cb12b4440d95b5c4ec0a64ca619b31b36e26c3`, solo lectura, sobre `main`.
2. **E1, E3, E4, E6 y E7 quedaron verificadas** con evidencia primaria.
   **E2 y E5 quedaron parciales**, y el §13 nombra exactamente qué falta.
3. **No se conoce desde Git la implementación efectiva de
   `consultar_materiales`** ni la de **`es_material_baja`**.
4. **Ausencia en el repositorio no equivale a ausencia desplegada.** Las
   afirmaciones de ausencia son siempre sobre una revisión y unas rutas.
5. **No se consultó ningún entorno desplegado**: ni SAP, ni Supabase, ni
   inventario activo. **No se ejecutaron RPC ni SQL contra ninguna base real**,
   ni migraciones, ni seeds.
6. **No se ejecutó ninguna suite de pruebas**, ni en ELSA ni en Materiales, y
   no se reutiliza ningún recuento de pruebas de auditorías anteriores como si
   fuera propio.
7. **No se usó ningún dato real** de inventario, BOM o usuarios, ni ninguna
   credencial.
8. **Árbol limpio no equivale a entorno intacto.** Este trabajo no sincronizó
   dependencias ni regeneró artefactos, pero la ausencia de cambios versionados
   no demuestra por sí sola que nada cambiara fuera de Git.
9. Las numeraciones de sección citadas se comprobaron contra sus revisiones; si
   un documento se reordena después, las referencias deben revisarse.
10. **Este documento no cierra M6, no cierra 5.0.b, no cierra 5.0.c, no cierra
    M4 y no autoriza ADR 0025.** La evidencia técnica de Materiales **informa**
    la decisión normativa; **no la sustituye**.

---

## Ver también

- [ADR 0020 — Capacidades componibles y planes de ejecución controlados](../adr/0020-capacidades-componibles-y-planes-de-ejecucion.md)
- [ADR 0021 — Contrato de inventario con Materiales (V1)](../adr/0021-contrato-de-inventario-con-materiales.md)
- [ADR 0023 — Cobertura desconocida de Materiales](../adr/0023-cobertura-desconocida-materiales-piloto.md)
- [ADR 0024 — Validación real de la frontera del código SAP y de la autenticación](../adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
- [Contrato funcional del Piloto 0.1](contrato-funcional.md)
- [Evidencia de las mediciones M3 y M5 (PC1)](evidencia-m3-m5-pc1.md)
- [Estándar de cierre de bloques](../project/BLOCK_CLOSURE_STANDARD.md)
