# ADR 0027 — Semántica de `null` y disponibilidad de metadata del inventario

- Estado: **aceptado**
- Fecha de la decisión: **2026-09-21**
- Bloque: 5.0, subbloque **M4-NORMATIVO**, punto **M4**
- **Decide una sola cosa**: qué significa `null` en el contrato de inventario,
  y cómo se distingue «no hay valor» de «el contrato no transporta el dato».
  Es la contradicción que
  [ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
  §10 declaró en voz alta y remitió explícitamente a **M4**
- **No reescribe** [ADR 0021](0021-contrato-de-inventario-con-materiales.md)
  §9.3 ni [ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
  §10. Ambos conservan su texto histórico íntegro; este ADR es la **decisión
  posterior autoritativa** que los clarifica
- **No cierra M4.** Cierra **M4-NORMATIVO**. El cierre operacional de M4 sigue
  abierto y depende de la fachada de **M1**, que no existe (§22)
- **No gobierna** M1, M6 operacional, M7, M8, B9a–B9c, D20 ni ONNX
- **No toca** §7.3, §8.3, §9.1, §9.2, §13 ni §15 de
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md); los **aplica**
- **No reabre** ninguna decisión de
  [ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md):
  ni `dado_de_baja`, ni `FACTUAL_SAP_AGGREGATED`, ni `snapshot_sensitive`, ni
  `ambito`, ni `ubicacion`, ni `stock_locations`, ni el vocabulario de
  `match_origin`
- Conserva sin cambios los estados de respuesta de
  [ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md). **No crea
  ningún `AnswerStatus` ni ningún aviso nuevo**
- **No aprueba, y no contiene, ninguna implementación**: ni fachada, ni
  `MaterialsPort`, ni adaptador, ni endpoint, ni migración, ni cambio alguno en
  Materiales
- Aplica las reglas **2, 4, 6, 12, 19, 21, 22, 23, 25 y 26** de
  [`CLAUDE.md`](../../CLAUDE.md)

---

## Contexto

### 1. Contexto

**M4** es, en su definición canónica, «versión y fecha del inventario activo»
([ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §17, tabla
del contrato externo pendiente; [contrato funcional](../piloto-0-1/contrato-funcional.md)
§10, fila B5).

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §9 fijó la forma del
bloque `inventory`, obligatorio en toda respuesta del contrato:

```jsonc
"inventory": {
  "version_number":    17,
  "loaded_at":         "…",
  "row_count":         54494,
  "source_file_label": "<string>" | null,
  "extracted_at":      null
}
```

y fijó dos semánticas que este ADR **no toca y da por vigentes**:

- §9.2 — `loaded_at` es **el momento en que terminó la carga en Materiales**.
  Nada más. No es «SAP actualizado al …» ni «extraído de SAP el …».
- §9.3 — `extracted_at` está **reservado y nulo**, y **no se infiere nunca de
  `source_file_label`**.

La evidencia primaria de Materiales
([evidencia M6](../piloto-0-1/evidencia-m6-semantica-temporalidad.md) §10, E8)
confirmó el hecho que sostiene todo lo anterior: la tabla de cargas registra
`iniciado_en`, `finalizado_en` y `archivo_nombre`, y **no existe ninguna
columna de fecha de extracción desde SAP**.

### 2. El problema

Después de
[ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md),
el contrato usa `null` con **dos sentidos distintos en secciones distintas**, y
no dice cuál rige. Un consumidor correcto puede llegar a dos conclusiones
opuestas sobre el mismo valor.

Esto no es un defecto cosmético. `null` es el único marcador de vacío del
contrato, y un consumidor que lo interprete mal producirá una **afirmación
falsa sobre SAP** sin que ningún mecanismo lo detecte.

### 3. La contradicción C1

#### 3.1 Los dos textos

**[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §9.3** —
texto histórico, conservado:

> `extracted_at` en nulo significa **«la fecha de extracción desde SAP no está
> disponible ni registrada en este contrato»**.
>
> **No significa** que el dato no exista en la realidad: significa que este
> contrato no lo transporta.

**[ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
§10.2** — texto histórico, conservado:

> **`null` significa «no hay valor en la fuente para este campo»**, y su
> semántica concreta se documenta **campo por campo**.

Y la propia nota de cierre de aquel §10:

> **PENDIENTE, y es de M4.** […] **Este ADR no toca el §9.3 y no resuelve esa
> doble semántica.** La coherencia entre ambas convenciones se decidirá al
> abordar **M4**, y hasta entonces conviven dos sentidos de `null` en secciones
> distintas del contrato. Se declara en voz alta para que nadie la descubra por
> sorpresa.

Registrada además como pendiente **P9** en el
[cierre del subbloque 5.0.b](../bloque-5-0-b-contrato-materiales-cierre.md)
§20.

#### 3.2 Por qué la contradicción es real, y no solo aparente

Son **tres** choques, no uno.

| # | Choque | En qué consiste |
|---|---|---|
| **C1.a** | **De cabecera** | §10.2 enuncia un significado universal —«no hay valor en la fuente»— y §9.3 enuncia, para un campo del mismo contrato, uno incompatible —«la fuente puede tenerlo; el contrato no lo transporta»— |
| **C1.b** | **De mecanismo** | §10.3 ordena declarar **en el descriptor** lo que el contrato aún no transporta, «no omitiendo claves». Pero `extracted_at: null` expresa exactamente «el contrato no lo transporta» **en el payload**. Dos canales para el mismo hecho |
| **C1.c** | **Interno del propio §10.2** | Su cabecera universal ya está **falsada por su propia tabla** |

**C1.c, en detalle, porque decide el resto del ADR.** La tabla del §10.2 define
`material_antiguo: null` como «no hay código antiguo, **o** el valor de origen
estaba corrompido y se descartó. **Ambos casos son indistinguibles por
diseño**». El segundo caso es un valor que **sí existía en la fuente** y que el
transporte perdió. La misma tabla define `ubicacion: null` advirtiendo que **no
significa** que el material carezca de ubicación física.

> **Conclusión de evidencia, no de preferencia:** el sentido «ausencia factual
> en la fuente» **nunca fue cierto de forma universal** en este contrato, ni
> siquiera dentro de M6. La cabecera del §10.2 es una generalización que la
> tabla del §10.2 desmiente.

#### 3.3 El sentido «no transportado» ya vivía fuera del §9

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.2 dice, sobre
cobertura:

> **Si esa metadata todavía no existe, `observed_scope` es nulo o vacío y
> `coverage.state` es `UNKNOWN`, aunque puedan observarse ámbitos en las
> filas.**

Es el sentido del §9.3 —«el contrato no lo transporta»— aplicado a un bloque
distinto. **`extracted_at` no es una excepción aislada:** cualquier regla que
prohibiera ese sentido rompería también el bloque de cobertura.

#### 3.4 Campos que la contradicción afecta

| Campo | Dónde | Sentido vigente antes de este ADR |
|---|---|---|
| `extracted_at` | [0021](0021-contrato-de-inventario-con-materiales.md) §9.3 | «el contrato no lo transporta» |
| `source_file_label` | [0021](0021-contrato-de-inventario-con-materiales.md) §9.1 | **nunca definido** — hueco |
| `coverage.observed_scope`, `expected_scope`, `missing_scope`, `declared_at` | [0021](0021-contrato-de-inventario-con-materiales.md) §7.1–§7.2 | «la metadata no existe» |
| `ubicacion` | [0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §10 | fila sin ubicación en origen; **no** inexistencia física |
| `material_antiguo` | [0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §10 | dos causas **indistinguibles por diseño** |
| `descripcion`, `unidad` | [0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §10 | columna vacía en todas las filas del grupo |

Y, **fuera del contrato**, una tercera lectura que este ADR **no corrige**:
`MaterialsPort.get_material` documenta su `None` como «o `None` si **no
existe**» (`src/elsa/ports/materials.py`). Es deuda de **M1** (§20, §21).

---

## Decisión

### 4. Decisión adoptada

**DECISIÓN TOMADA por el responsable del proyecto el 2026-09-21**, sobre el
informe de alternativas presentado en esta sesión. Se evaluaron cuatro
familias —`null` universalmente factual (A), semántica campo por campo (B),
separación de valor y disponibilidad (C), y la combinación disciplinada que
aquí se adopta (D)—. Las descartadas y su motivo están en §21.

> **`null` no tiene significado universal en el contrato de inventario. Su
> semántica se define campo por campo, y cada definición debe clasificarse en
> exactamente uno de tres sentidos cerrados y disjuntos.**

La separación explícita de valor y disponibilidad (Alternativa C) **no se
construye ahora**, y queda declarada como ampliación **compatible** para cuando
exista un caso real que la exija (§12, regla 23 de
[`CLAUDE.md`](../../CLAUDE.md)).

### 5. Semántica exacta de `null`

`null` en el contrato de inventario significa **exactamente**:

> **«Este campo no lleva un valor utilizable en esta respuesta.»**

**Nada más puede inferirse de un `null` sin consultar la tabla normativa del
campo.** En particular, `null` **no significa por sí solo**:

- que el hecho no exista en SAP;
- que el hecho no exista en Materiales;
- que el hecho no exista en la realidad;
- que el dato sea desconocido;
- que el dato sea irrelevante.

**La ausencia de una clave nunca es una señal.** Todo campo definido del
contrato se emite siempre, con `null` cuando no lleva valor. Esta regla, que
[ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
§10.1 fijó para los campos M6, se extiende aquí al bloque `inventory` del §9 y
al bloque `coverage` del §7.

### 6. Los tres sentidos cerrados de `null`

Vocabulario **cerrado**. Todo campo nulable del contrato pertenece a
**exactamente uno**.

| Sentido | Qué afirma | Qué puede afirmar ELSA a partir de él |
|---|---|---|
| **`VALOR_FACTUAL_AUSENTE`** | La fuente fue consultada sobre este campo, respondió, y **no hay valor** para esa versión de inventario | Puede afirmar la ausencia **acotada a la fuente y a la versión**. Nunca acotada a la realidad ni a SAP |
| **`DATO_NO_PROPORCIONADO`** | El hecho puede existir o no en la fuente: **este contrato, en esta versión, no lo transporta**. El `null` habla del **transporte**, no del hecho | **Nada sobre el hecho.** Solo puede decir que el contrato no transporta ese dato |
| **`DATO_DESCONOCIDO`** | El contrato transporta el campo, pero el valor **no se pudo determinar**, o la causa del vacío es **indistinguible** | Debe **nombrar el desconocimiento**. Prohibido asimilarlo al peor caso conocido, y prohibido asimilarlo a `VALOR_FACTUAL_AUSENTE` |

#### 6.1 Las tres definiciones, sin abreviar

- **«Valor factual ausente»** — la fuente tiene autoridad sobre este campo, la
  ejerció, y el resultado es que no hay valor. Es la única de las tres que
  permite a ELSA afirmar algo negativo, y **solo dentro de la frontera de la
  fuente y de la versión de inventario nombrada**. No autoriza ninguna
  afirmación sobre SAP ni sobre la planta.
- **«Dato no proporcionado»** — el contrato no transporta el dato. No es una
  afirmación sobre el mundo: es una afirmación sobre el contrato. La fuente
  puede tenerlo, puede no tenerlo, y el contrato **no lo sabe ni lo dice**.
- **«Dato desconocido»** — el contrato sí transporta el campo, pero en este caso
  no hay forma de determinar el valor, o el vacío tiene varias causas posibles
  que la fuente no distingue. Es el sentido **más débil**, y por eso es el
  destino por defecto de cualquier ambigüedad (§6.3).

#### 6.2 Regla de clasificación obligatoria

1. **Todo campo nulable definido por el contrato debe declarar su sentido**, en
   la tabla normativa del campo.
2. **Un campo nulable sin clasificación es un defecto de contrato**, no un
   campo permisivo. ELSA lo trata como `DATO_DESCONOCIDO`, registra la
   anomalía y **no infiere nada de él**.
3. **ELSA no generaliza el sentido de un `null` de un campo a otro.** Dos
   `null` del mismo payload pueden significar cosas distintas, y significarlas
   es correcto.
4. **Cambiar la clasificación de un campo sin cambiar su nombre es
   incompatible**, por
   [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §15.1: es un
   cambio de significado invisible en un diff.

#### 6.3 Regla de ambigüedad declarada

Cuando el `null` de un campo sea **irreductiblemente ambiguo** —dos causas que
la fuente no distingue—, la tabla del campo **debe declararlo**, el campo se
clasifica como **`DATO_DESCONOCIDO`**, y **ELSA tiene prohibido resolver la
ambigüedad por su cuenta**.

Esto no inventa una figura nueva: aplica al plano del dato la convención que
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §13.2 ya fijó para
el plano del estado —*«nombrar el desconocimiento en lugar de asimilarlo al
peor caso conocido»*—.

### 7. Semántica de los cinco campos del bloque `inventory`

Tabla normativa del §9.1 de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md), que **no se
modifica**: se le añade la clasificación que faltaba.

| Campo | Nulable en V1 | Sentido | Qué significa exactamente |
|---|---|---|---|
| **`version_number`** | **No** | — | Número de la versión de inventario **activa** sobre la que se respondió. No es nulable: si no hay versión activa, la llamada **no** emite un `inventory` con nulos, sino `call_status` = `NO_ACTIVE_INVENTORY` ([0021](0021-contrato-de-inventario-con-materiales.md) §13) |
| **`loaded_at`** | **No** | — | **El momento en que terminó la carga en Materiales. Nada más** ([0021](0021-contrato-de-inventario-con-materiales.md) §9.2, íntegro y sin cambio). No es «SAP actualizado al …» ni «extraído de SAP el …» |
| **`row_count`** | **No** | — | Filas de la versión activa. Es un **recuento de carga**, no una medida de cobertura: la cobertura vive en `coverage` ([0021](0021-contrato-de-inventario-con-materiales.md) §7) y **nunca se deriva de este número** |
| **`source_file_label`** | **Sí** | **`DATO_DESCONOCIDO`** | Etiqueta **opaca** de trazabilidad humana. `null` significa que esta carga no registró etiqueta, o que la fuente no la expone; **el contrato no distingue ambos casos**. Nulo o no nulo, **no habilita ninguna afirmación**: sigue vigente sin excepción la prohibición de [0021](0021-contrato-de-inventario-con-materiales.md) §9.3 de **extraer de él una fecha**, aunque el nombre siga una convención que la contenga |
| **`extracted_at`** | **Sí, y siempre nulo en V1** | **`DATO_NO_PROPORCIONADO`** | **«Este contrato no transporta la fecha de extracción desde SAP.»** No significa que SAP carezca de ella, ni que el dato no exista en la realidad. Campo **reservado**: rellenarlo cuando exista un mecanismo que lo registre es cambio **compatible** ([0021](0021-contrato-de-inventario-con-materiales.md) §15.1) |

> **`extracted_at` queda inequívoco.** Su `null` habla del **contrato**, no del
> mundo. La lectura «SAP no tiene fecha de extracción» queda **prohibida y es
> falsa**: la evidencia primaria de Materiales
> ([evidencia M6](../piloto-0-1/evidencia-m6-semantica-temporalidad.md) §10)
> demuestra únicamente que **el esquema auditado no la registra**, que es una
> afirmación sobre Materiales, no sobre SAP.

> **La relación con `loaded_at` queda inequívoca.** Son campos de naturaleza
> distinta y **no se sustituyen**: `loaded_at` es un hecho transportado sobre un
> evento de Materiales; `extracted_at` es un hueco declarado sobre un evento de
> SAP. **`loaded_at` no se presenta nunca como fecha de extracción**, ni
> siquiera como aproximación, ni siquiera acompañado de una advertencia.

### 8. Los campos ya decididos por otros ADR: lectura, no reescritura

La clasificación del §6 **nombra** lo que aquellos ADR ya decían. **No cambia
el significado de ningún campo.** Si alguna vez se leyera una divergencia entre
esta tabla y el texto de origen, **prevalece el texto de origen** y esta tabla
es la que está mal.

| Campo | Texto de origen, intacto | Sentido que le corresponde |
|---|---|---|
| `descripcion`, `unidad` | «La columna llegó vacía en todas las filas del grupo» ([0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §10) | `VALOR_FACTUAL_AUSENTE` |
| `ubicacion` | «La fila llegó sin ubicación en el origen. **No significa** que el material carezca de ubicación física» ([0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §10) | `DATO_DESCONOCIDO` |
| `material_antiguo` | «No hay código antiguo, **o** el valor de origen estaba corrompido y se descartó. **Ambos casos son indistinguibles por diseño**» ([0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §10) | `DATO_DESCONOCIDO`, por §6.3 |
| `disponible`, `comprometido`, `total_disponible`, `total_comprometido` | «**No aplica**: estos campos nunca son nulos» ([0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §10) | No aplica |
| `coverage.observed_scope`, `expected_scope`, `missing_scope`, `declared_at` | «Si esa metadata todavía no existe, `observed_scope` es nulo o vacío y `coverage.state` es `UNKNOWN`» ([0021](0021-contrato-de-inventario-con-materiales.md) §7.2) | `DATO_NO_PROPORCIONADO` |

> **Esto no reabre M6.** `dado_de_baja`, `FACTUAL_SAP_AGGREGATED`,
> `snapshot_sensitive`, la prohibición sobre `ambito`, la opacidad de
> `ubicacion`, `stock_locations` y el vocabulario de `match_origin` quedan
> **exactamente como
> [ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
> los dejó.**

### 9. Relación con `snapshot_sensitive`

**Son ejes ortogonales, y ninguno se deriva del otro.**

| Pregunta | La responde |
|---|---|
| ¿Este campo exige un inventario vigente para sostener una afirmación? | **`snapshot_sensitive`** ([0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §6) |
| ¿Qué significa que este campo llegue vacío? | **La clasificación de `null`** (§6 de este ADR) |

Las cuatro combinaciones existen y ninguna es contradictoria:

| | `snapshot_sensitive: true` | `snapshot_sensitive: false` |
|---|---|---|
| **Nulable** | Posible en el futuro; ninguno en V1 | `ubicacion`, `material_antiguo` |
| **No nulable** | `disponible`, `comprometido`, `total_*` | `centro`, `almacen`, `ambito` |

Consecuencias normativas:

1. **Ninguna clasificación de `null` modifica el `snapshot_sensitive` de ningún
   campo**, y ninguna se deriva de la otra.
2. **Los cinco campos del bloque `inventory` no declaran `snapshot_sensitive`.**
   Son `INVENTORY_METADATA`
   ([0021](0021-contrato-de-inventario-con-materiales.md) §10.4): **describen
   el snapshot**, no se afirman sobre él. Preguntar si `loaded_at` es sensible
   al snapshot es un error de categoría.
3. La tabla de `snapshot_sensitive` de
   [ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
   §6 **queda intacta**.

### 10. Relación futura con `requires_fresh_inventory`

`requires_fresh_inventory` sigue siendo **propiedad determinista del plan o la
plantilla, que no decide un LLM**
([ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §11.1,
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §11), y se deriva
**exclusivamente** de `snapshot_sensitive`
([ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
§6). **Este ADR no cambia esa derivación.**

Lo que sí fija, porque es consecuencia directa de §7:

1. **`extracted_at` no participa en la vigencia**, ni nulo ni relleno en el
   futuro. No es un insumo de `requires_fresh_inventory` ni de su evaluación.
2. **La «vigencia verificable» de
   [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §11 se satisface
   con `version_number` + `loaded_at`**, que son obligatorios y no nulables.
   Por eso aquel §11 pudo decir que la vigencia «deja de ser verificable a
   veces».
3. **Por tanto, `extracted_at: null` no produce nunca
   `inventory_freshness_unknown` por sí solo.** Leerlo como señal de vigencia
   desconocida sería exactamente el error que §7 prohíbe.

> **Qué queda para M4 operativo, y este ADR no decide:** cuándo y cómo se emite
> `inventory_freshness_unknown`, dónde vive la política de vigencia, qué forma
> toma en `AnswerWarning`, y cómo se transporta el bloque `inventory` por el
> `MaterialsPort`. Nada de eso se decide aquí (§19).

### 11. Reglas de emisión y serialización

1. **Todo campo definido se emite siempre.** La ausencia de una clave **nunca**
   es una señal, en ningún bloque del contrato.
2. **`null` es el único marcador de vacío.** Quedan **prohibidos** como
   sustitutos: la cadena vacía, el cero, `"N/A"`, `"-"`, `"desconocido"`,
   cualquier centinela y cualquier fecha imposible. Un campo que use un
   centinela es un defecto de contrato.
3. **Dos planos, dos canales, y ya no compiten.** Lo que el contrato no
   transporta **a nivel de contrato** se declara en el **descriptor**
   ([0021](0021-contrato-de-inventario-con-materiales.md) §15.3 y
   [0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
   §10.3). Lo que no lleva valor **en una respuesta concreta** se emite como
   **`null` clasificado**. El descriptor declara la **capacidad**; el `null`
   declara el **caso**. `extracted_at` es hoy el caso límite en que ambos
   coinciden, y esa coincidencia **no es una contradicción**: es un campo
   reservado cuya capacidad está declarada como ausente y cuyo caso es
   siempre nulo.
4. **ELSA no reescribe ni normaliza los `null` que recibe.** No los convierte a
   cadena vacía al serializar hacia el cliente, y no los omite.
5. **Toda redacción hacia el usuario que dependa de un `null` debe nombrar su
   sentido**, no el vacío. «No consta en el inventario cargado el …» y «el
   inventario no informa ese dato» **no son la misma frase** y no se sustituyen.

### 12. Ruta compatible hacia la separación de valor y disponibilidad

**No se construye ahora** (regla 23 de [`CLAUDE.md`](../../CLAUDE.md): no se
construye por anticipación). Se declara la ruta para que, si llega el caso, no
sea una ruptura.

Si algún día un campo debe distinguir **dos causas de vacío en la misma
respuesta** —y `material_antiguo` es el candidato natural—, la forma prevista
es **añadir un descriptor opcional de disponibilidad junto al valor**, análogo
al envoltorio que
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §10.2 ya usa para los
campos derivados (`{ value, rule_reference, rule_verifiable }`).

- Añadir ese campo opcional es **compatible**
  ([0021](0021-contrato-de-inventario-con-materiales.md) §15.1).
- Exige **otro ADR**, porque fija un enum cerrado (regla 25).
- **Hasta entonces, el vocabulario del §6 es documental y normativo, no un
  campo del payload.**

### 13. Casos límite

| # | Caso | Resolución |
|---|---|---|
| **L1** | **No hay versión de inventario activa** | **No** se emite un `inventory` con nulos. La llamada responde `call_status` = `NO_ACTIVE_INVENTORY`, que mapea a `ERROR` o `PARTIAL` según el plan ([0021](0021-contrato-de-inventario-con-materiales.md) §13, §13.1). Un `inventory` con `version_number: null` sería un **defecto de contrato** |
| **L2** | **`source_file_label` contiene una fecha en el nombre** | Sigue siendo **opaco**. Extraer esa fecha está **prohibido**, esté el campo nulo o no ([0021](0021-contrato-de-inventario-con-materiales.md) §9.3) |
| **L3** | **`source_file_label` llega nulo** | `DATO_DESCONOCIDO`. No se infiere que la carga careciera de archivo de origen |
| **L4** | **`extracted_at` se rellena en el futuro** | Deja de ser un hueco y pasa a ser un hecho transportado, con su clase de procedencia declarada. **El cambio de nulo a valor en un campo reservado es compatible**; el cambio de **clasificación** de cualquier otro campo **no lo es** (§6.2.4). Requiere actualizar la tabla del §7, y el ADR que lo haga debe decir de dónde sale la fecha |
| **L5** | **Un campo nulable nuevo llega sin clasificación** | Defecto de contrato. ELSA lo trata como `DATO_DESCONOCIDO`, lo registra y no infiere nada (§6.2.2) |
| **L6** | **`row_count` es 0 con versión activa** | Es un **hecho**, no un `null`, y **no es cobertura**: no autoriza a afirmar que el ámbito esté vacío. La cobertura la decide `coverage` ([0021](0021-contrato-de-inventario-con-materiales.md) §7.5) |
| **L7** | **Coexisten en una respuesta tres `null` con tres sentidos** | Es **correcto y esperado**. Cada uno se lee con su tabla (§6.2.3) |
| **L8** | **La fuente emite cadena vacía donde el contrato espera `null`** | Defecto de conformidad del proveedor, detectable por prueba contractual ([0021](0021-contrato-de-inventario-con-materiales.md) §18). ELSA **no lo normaliza en silencio** |

### 14. Ejemplos concretos

#### 14.1 Respuesta V1 típica

```jsonc
"inventory": {
  "version_number":    17,
  "loaded_at":         "2026-09-10T…",
  "row_count":         54494,
  "source_file_label": "…",          // opaco; nunca se lee una fecha de aquí
  "extracted_at":      null          // DATO_NO_PROPORCIONADO
}
```

#### 14.2 Lecturas correctas e incorrectas del mismo payload

| `extracted_at: null` | |
|---|---|
| ✅ «El contrato de inventario no transporta la fecha de extracción desde SAP» | Correcto: describe el contrato |
| ✅ «Según el inventario **cargado en Materiales** el 2026-09-10 …» | Correcto: usa `loaded_at` con su semántica de [0021](0021-contrato-de-inventario-con-materiales.md) §9.2 |
| ❌ «SAP no tiene fecha de extracción» | **Prohibido y falso**: `null` habla del transporte, no del mundo |
| ❌ «El inventario se extrajo el 2026-09-10» | **Prohibido**: sustituye `extracted_at` por `loaded_at` |
| ❌ «El inventario se extrajo el 2026-09-08, según el nombre del archivo» | **Prohibido**: infiere del `source_file_label` opaco |
| ❌ «La vigencia del inventario es desconocida, porque falta `extracted_at`» | **Prohibido**: la vigencia se verifica con `version_number` + `loaded_at` (§10.2) |

#### 14.3 Tres `null` con tres sentidos en la misma respuesta

```jsonc
{
  "inventory": { "extracted_at": null },        // DATO_NO_PROPORCIONADO
  "coverage":  { "observed_scope": null,        // DATO_NO_PROPORCIONADO
                 "state": "UNKNOWN" },
  "material":  { "descripcion": null,           // VALOR_FACTUAL_AUSENTE
                 "ubicacion":   null }          // DATO_DESCONOCIDO
}
```

Las cuatro lecturas son distintas y **las cuatro son correctas**. Homogeneizarlas
sería el error que este ADR existe para impedir.

---

## Consecuencias

### 15. Compatibilidad con ADR 0021

- **§9.1, §9.2 y §9.3 quedan íntegros y vigentes.** Este ADR **no los
  reescribe**: añade la clasificación que faltaba y la extiende a los demás
  campos nulables.
- **§9.3 queda confirmado, no corregido.** Su lectura —«este contrato no lo
  transporta»— pasa a ser un sentido **nombrado** (`DATO_NO_PROPORCIONADO`) en
  lugar de una excepción sin nombre.
- **§7.2 queda confirmado** por el mismo mecanismo (§8).
- **§15.1 se aplica sin excepción**, y se refuerza: cambiar la clasificación de
  un campo es un cambio de significado sin cambio de nombre, que aquella tabla
  marca como el más peligroso.
- **§8.3, §11, §12, §13 y §16 no se tocan.**

### 16. Compatibilidad con ADR 0025

- **§10 queda íntegro.** Su texto, su tabla y su nota de PENDIENTE se conservan
  como registro histórico de cómo se llegó aquí.
- **§10.1 se extiende**, no se sustituye: la emisión estable de campos pasa a
  regir también el bloque `inventory` y el bloque `coverage`.
- **§10.2 se acota**: su enunciado sigue describiendo correctamente la mayoría
  de los campos M6, y deja de ser una regla universal del contrato. El propio
  §10 ya declaraba su alcance acotado a los campos M6 y ya remitía la coherencia
  a M4; este ADR es esa decisión.
- **La PENDIENTE del §10 queda cerrada.** Es lo único de
  [ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
  que cambia de estado.
- **§4, §5, §6, §7, §8 y §9 no se tocan.** M6 no se rediseña.

### 17. Consecuencias para Materiales

| | Efecto |
|---|---|
| **Cambio de esquema** | **Ninguno** |
| **Cambio de forma del contrato** | **Ninguno** |
| **Trabajo de implementación añadido** | **Ninguno.** Las brechas B1–B5 de [0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §12 siguen siendo las mismas |
| **Obligación nueva** | Al definir la fachada, **todo campo nulable debe llegar con su sentido declarado**, y las pruebas contractuales del proveedor ([0021](0021-contrato-de-inventario-con-materiales.md) §18) deben poder comprobar que ningún campo usa un centinela en lugar de `null` |
| **Propiedad del dato** | **Sin cambio.** Materiales sigue siendo propietario de su inventario y de sus reglas (regla 4) |

**Este ADR no autoriza ningún cambio en Materiales, y la auditoría que lo
sostiene fue de solo lectura.**

### 18. Consecuencias para ELSA

1. **ELSA no puede afirmar nada sobre SAP a partir de un `null`.** Ni sobre
   fechas, ni sobre existencia, ni sobre cobertura.
2. **ELSA debe consultar la tabla del campo** antes de redactar cualquier frase
   que dependa de un vacío, y **no puede generalizar** entre campos.
3. **La derivación de `requires_fresh_inventory` no cambia** (§10).
4. **No se crea ningún `AnswerStatus` ni ningún aviso nuevo.** Los tres avisos
   declarados conceptualmente en
   [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §13.2 siguen sin
   implementarse, y este ADR no los implementa.
5. **Ningún archivo de `src/` cambia por este ADR.** La primera
   implementación que lo aplique pertenece a M4 operativo y a M1.

### 19. Qué NO decide este ADR

| No decide | Dónde pertenece |
|---|---|
| `requires_fresh_inventory` implementado, `inventory_freshness_unknown`, política de vigencia, cambios en `AnswerWarning` | **M4 operativo** |
| Cómo se transporta el bloque `inventory` por el `MaterialsPort`, su retipado, el fake de la fachada y las pruebas de conformidad | **M1**, y el trabajo propio de ELSA que depende de él |
| La deuda de `Material \| None` = «no existe» en `src/elsa/ports/materials.py` | **M1** (§20, D2) |
| Cualquier decisión de M6 ya tomada | **Cerrada por [ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)** |
| El criterio de cierre de M8 | **Intacto en [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3** |
| Un campo de disponibilidad en el payload (Alternativa C) | **ADR futuro**, si un caso real lo exige (§12) |
| Quién ocupa qué rol, qué se despliega, qué se migra | Fuera de alcance |
| D20, ONNX, Modo ELSA, embeddings, ZIAA, BOM | Fuera de alcance |

### 20. Pendientes operativos

| Id | Pendiente | Quién |
|---|---|---|
| **D1** | **M4 operativo sigue ABIERTO.** La metadata de vigencia no se transporta, no se consume y no existe en ELSA | M1 + M4 operativo |
| **D2** | **Deuda de M1:** `MaterialsPort.get_material` documenta su `None` como «no existe», tercer sentido incompatible con [0021](0021-contrato-de-inventario-con-materiales.md) §8 y con este ADR. **Registrada, no corregida** | M1 |
| **D3** | La tabla del §7 debe **reemitirse en la definición canónica del contrato** cuando exista, versionada por el Contract Owner | Contract Owner (M7) + Materiales |
| **D4** | Las **pruebas contractuales del proveedor** deben cubrir: campo nulable sin clasificación, centinela en lugar de `null`, y clave omitida | Materiales |
| **D5** | Si `material_antiguo` llegara a necesitar distinguir sus dos causas, hace falta el ADR del §12 | Trabajo normativo futuro |
| **D6** | **M6 operacional, M8 y D20 siguen abiertos** y no se tocan aquí | Sus propios subbloques |

### 21. Alternativas descartadas

| Alternativa | Por qué se descartó |
|---|---|
| **A — `null` significa universalmente «la fuente factual no tiene valor»** | Obligaría a **reescribir** [0021](0021-contrato-de-inventario-con-materiales.md) §9.3 y a cambiar el significado de `extracted_at` sin cambiar su nombre, que §15.1 marca como **incompatible y el más peligroso**. Convertiría `extracted_at: null` en la afirmación **falsa** «SAP no tiene fecha de extracción», repitiendo en el eje temporal el error que §8 impide en el eje de ausencia. Rompería además §7.2 (cobertura). Y está **falsada por la propia tabla** de [0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §10, donde `material_antiguo` cubre un valor que sí existía en la fuente |
| **B — semántica campo por campo, sin vocabulario cerrado** | Correcta y compatible, pero **insuficiente**: permite prosa libre por campo y no impide repetir la ambigüedad no nombrada de `material_antiguo` en campos futuros. La decisión adoptada es B **más** la clasificación obligatoria del §6 |
| **C — separar valor y disponibilidad en el payload, ahora** | Máxima desambiguación formal, pero **hoy nadie puede emitirla**: la fachada de M1 no existe y B1–B4 de [0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §12 siguen abiertas. Fijaría un enum cerrado sin casos medidos, y §15.1 marca añadir valores a un enum cerrado como incompatible por defecto. Construir por anticipación contradice la regla 23. **Queda declarada como ruta compatible** (§12), no descartada para siempre |

### 22. Estado de M4 después de este ADR

| | Estado |
|---|---|
| **M4-NORMATIVO** | **DECIDIDO.** La semántica de `null`, la de `extracted_at` y la de los cinco campos del bloque `inventory` quedan fijadas. Su **cierre documental** lo formaliza el documento de cierre del subbloque (regla 26) |
| **M4 OPERATIVO** | **ABIERTO.** Nada de la metadata de vigencia se transporta, se consume ni existe en ELSA. Depende de la fachada de **M1**, que **no existe** |

**M4, como punto, sigue ABIERTO.** Este ADR cierra su mitad normativa y **no
adelanta ni un paso** M1, M6 operacional, M7, M8, B9a–B9c ni D20. **M8 sigue
ABIERTO**, con el criterio de cierre de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3 **intacto y sin
cumplir**.

### 23. Trazabilidad de los requisitos de este ADR

| Requisito | Dónde se resuelve |
|---|---|
| Reconstruir C1 con precisión | §3 |
| Decisión humana explícita | §4 |
| Semántica exacta de `null` | §5, §6 |
| «Dato desconocido», «dato no proporcionado», «valor factual ausente» | §6, §6.1 |
| Semántica de los cinco campos de `inventory` | §7 |
| Relación con `snapshot_sensitive` | §9 |
| Relación futura con `requires_fresh_inventory` | §10 |
| Compatibilidad con [0021](0021-contrato-de-inventario-con-materiales.md) y [0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) | §15, §16 |
| Consecuencias para Materiales y para ELSA | §17, §18 |
| Reglas de serialización | §11 |
| Casos límite y ejemplos | §13, §14 |
| Qué NO decide | §19 |
| Pendientes operativos | §20 |
| Historia normativa conservada | §3.1, §8, §16 |

---

## Ver también

- [ADR 0020 — Capacidades componibles y planes de ejecución](0020-capacidades-componibles-y-planes-de-ejecucion.md)
- [ADR 0021 — Contrato de inventario con Materiales](0021-contrato-de-inventario-con-materiales.md)
- [ADR 0023 — Cobertura desconocida de Materiales](0023-cobertura-desconocida-materiales-piloto.md)
- [ADR 0025 — Semántica, procedencia y temporalidad de los campos de inventario](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
- [ADR 0026 — Gobernanza y cierre de M7](0026-gobernanza-y-cierre-de-m7.md)
- [Evidencia M6 — semántica y temporalidad](../piloto-0-1/evidencia-m6-semantica-temporalidad.md)
- [Cierre del subbloque 5.0.b](../bloque-5-0-b-contrato-materiales-cierre.md)
- [Cierre de M4-NORMATIVO](../bloque-5-0-m4-normativo-cierre.md)
