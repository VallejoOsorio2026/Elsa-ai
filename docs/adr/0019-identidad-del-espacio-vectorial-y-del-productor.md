# ADR 0019 — Identidad del espacio vectorial: contrato semántico y productor numérico

- Estado: **aceptado — criterio numérico de equivalencia diferido**
- Bloque: 4.6, decisión **D11**
- Amplía [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md) §2 y
  matiza su §5
- No reabre [ADR 0015](0015-eleccion-del-modelo-de-embeddings.md) ni
  [ADR 0016](0016-recuperacion-hibrida-del-mvp.md)
- Aplica las reglas 2, 6, 21 y 23 de [`CLAUDE.md`](../../CLAUDE.md)
- **No aprueba ningún runtime, ningún modelo y ninguna cuantización**

## Contexto

ELSA guarda un vector por `(chunk, modelo)` en
`elsa.document_chunk_embeddings`, registra cada modelo como una fila inmutable
en `elsa.embedding_models`, deja rastro de cada corrida en
`elsa.embedding_runs`, y separa generar de activar. Todo eso lo decidió
ADR 0013 y aquí no se reabre.

Ese diseño se escribió cuando existía **un solo runtime**:
`sentence-transformers` sobre PyTorch. Bajo ese supuesto, «el modelo» y «quien
calcula los vectores» eran la misma cosa, y confundirlos no tenía
consecuencias.

El Bloque 4.6 rompió el supuesto. Existe un banco experimental que ejecuta
`BAAI/bge-m3` sobre ONNX Runtime FP32 con los mismos pesos nominales, y está
abierta la posibilidad de INT8, de GGUF y de otros modelos. A partir de ahora,
**el mismo modelo puede tener más de una implementación numérica**, y nada
garantiza que dos implementaciones produzcan los mismos números.

Ese es el contexto. Lo que sigue es el problema.

## Problema

### El punto ciego

La identidad de un espacio vectorial se comprueba hoy en cuatro sitios, y los
cuatro comparan **los mismos siete campos**:

| Punto | Ubicación |
|---|---|
| Restricción `unique` | `supabase/migrations/20260913010000_create_vector_storage_model.sql` |
| `find_model` | `src/elsa/adapters/postgres_vectors.py` |
| `_assert_same_vector_space` | `src/elsa/services/embedding_generation.py` |
| `register` (CLI) | `src/elsa/tools/embeddings_admin.py`, vía `find_model` |

Los siete: `model_id`, `revision`, `dimension`, `document_prefix`,
`query_prefix`, `composition_template`, `normalized`.

**`runtime` sí se persiste** —la columna existe, se escribe, se lee y el
disparador de inmutabilidad la protege— y **no se compara nunca**. `family` y
`similarity` tampoco entran en la clave.

### Qué produce eso, paso a paso

1. Se configura el adaptador ONNX con el mismo `model_id`, `revision`,
   `dimension` y prefijos.
2. `register` → `find_model` **encuentra la fila de PyTorch** y devuelve su
   identificador. No hay aviso.
3. Forzar el `insert` tampoco sirve: la `unique` lo rechaza. El sistema
   **impide** registrar el productor nuevo como espacio propio y empuja a
   reutilizar el ajeno.
4. `generate` contra ese identificador pasa el guard, que compara los mismos
   siete campos.
5. `store_embeddings` es idempotente por `embedded_sha256`: los chunks que
   PyTorch ya embebió **se reutilizan, no se regeneran**.
6. Queda una fila con vectores de dos productores numéricos mezclados chunk a
   chunk.

### Y un segundo agujero, en el camino de consulta

`PostgresVectorStore.search` filtra los documentos por el modelo activo y, del
vector de consulta, **solo comprueba la dimensión**. El vector de consulta lo
produce el `EmbeddingsPort` que el proceso haya construido a partir de la
configuración, y ningún punto del camino compara su descriptor con el modelo
activo: `describe()` se invoca exactamente dos veces en el código productivo
—al generar y al registrar—, **nunca al consultar**.

Basta cambiar una variable de entorno para que las consultas se embeban con un
productor distinto al de los documentos, sin tocar una fila y sin ningún error.

### Por qué esto es grave y no ruidoso

Ninguno de los dos casos produce una excepción. Producen un **ranking**. Un
índice que ordena mal es indistinguible de uno que ordena bien salvo midiendo
calidad, y ELSA mide calidad con un banco que no se ejecuta en producción.

Es exactamente el fallo que `EmbeddingDimensionError` ya evita para la
**forma** del vector —«no se trunca ni se rellena: pertenece a otro espacio
vectorial»— y que nadie evita para su **origen**.

### El hueco que ADR 0013 ya había señalado

ADR 0013 §2 dice que el registro del modelo debe llevar «…métrica de
similitud, **tokenizador, ventana máxima**, plantilla del texto embebido…».
La tabla **no tiene columna de tokenizador ni de ventana máxima**, y tampoco
de **pooling**. Son tres factores que cambian el vector y que hoy no se
registran en ninguna parte del camino productivo. No es un descubrimiento
nuevo: es una promesa de ADR 0013 que nunca se implementó, y este ADR la
recoge.

## Fuerzas y criterios

**F1 — Un fallo de identidad no puede ser silencioso.** Es la regla 21
aplicada a los datos: no afirmar que algo funciona sin comprobarlo.

**F2 — La identidad declarada no basta.** El diseño actual confía en lo que el
adaptador dice de sí mismo. Eso es precisamente lo que falló.

**F3 — La equivalencia es una pregunta empírica, no una etiqueta.** Si dos
productores calculan la misma función, se demuestra midiendo. Ninguna cadena
de texto lo establece.

**F4 — Una regla que solo se cumple pagando de más se incumple.** Si demostrar
equivalencia no sirviera de nada, quien tenga delante horas de regeneración
por un runtime que probadamente produce lo mismo tiene un incentivo directo a
editar el descriptor. La política tiene que dar al camino honesto un
mecanismo.

**F5 — Una actualización irrelevante no puede costar una regeneración.** Meter
la versión del runtime en la clave convertiría cada actualización de parche en
una migración de datos.

**F6 — Nada de esto puede depender del resultado del experimento.** El diseño
tiene que funcionar si ONNX FP32 resulta equivalente, si no lo resulta, si
INT8 se descarta y si mañana aparece GGUF.

**F7 — Simplicidad sobre sofisticación (regla 23).** No se construye por
anticipación: la asimetría, los modos degradados y las políticas finas quedan
fuera.

**F8 — Las capas ajenas siguen ajenas (regla 6).** Chunking, permisos,
documentos, generación y LLM no pueden enterarse de que existe un concepto de
productor.

## Decisión

> **La identidad de un espacio vectorial se parte en dos conceptos, y la
> pertenencia de un productor alternativo a un espacio se demuestra en lugar
> de declararse.**

Siete puntos:

**1.** La identidad se separa en **espacio vectorial** (contrato semántico:
qué función queremos representar) y **productor** (receta numérica: qué
implementación la calcula). `runtime` sale del espacio.

**2.** Cada espacio tiene exactamente un **productor de referencia designado
explícitamente**. La designación es un acto declarado al crear el espacio, no
la consecuencia de haber ejecutado algo primero.

**3.** La política es **estricta por defecto**. Un productor distinto de la
referencia **no** pertenece al espacio aunque declare el mismo `model_id`, la
misma `revision`, la misma dimensión, los mismos prefijos y la misma
normalización. Es un espacio distinto hasta que se demuestre lo contrario.

**4.** La única excepción es una **atestación de equivalencia** explícita,
registrada, evidencial y auditable. **Medir ≠ atestar ≠ usar**, igual que
ADR 0013 §5 ya separó generar de activar y la regla 16 separó cargar de
aprobar y de publicar.

**5.** Cada espacio lleva un **conjunto de sondas canónicas** con referencia
**numérica**, no solo un digest. Es el instrumento con el que un productor
**alternativo** demuestra equivalencia; el productor de referencia no lo
necesita contra sí mismo.

**6.** La procedencia vive en la **corrida**, no en cada vector. `run_id` ya
la deriva.

**7.** El vector de consulta llega con la identidad de quien lo produjo, y el
almacén **rechaza explícitamente** si ese productor no es miembro válido del
espacio activo. No se degrada en silencio.

### Vocabulario

Siete términos, y el ADR los usa con este significado exacto:

| Término | Significado |
|---|---|
| **Vector space** | Contrato semántico: la función texto → vector que se quiere representar |
| **Producer** | Implementación numérica concreta que calcula esa función |
| **Reference producer** | Productor **designado explícitamente** que define el espacio |
| **Alternative producer** | Cualquier otro productor; solo puede usar el espacio con una atestación válida |
| **Embedding run** | Procedencia concreta de un lote de vectores |
| **Canonical probe** | Instrumento reproducible para medir equivalencia |
| **Equivalence attestation** | Evidencia explícita que concede membresía a un productor alternativo |
| **Retrieval configuration** | Configuración que afecta la comparación de vectores, no su generación |

## Definición de espacio vectorial

### Definición operacional

> Dos productores comparten espacio vectorial si, y solo si, **implementan la
> misma función texto → vector**: para cualquier texto admisible, sus vectores
> son intercambiables a efectos de ordenar por cercanía.

Es una afirmación **sobre la función**, no sobre su implementación. La
implementación es evidencia de la función, nunca su definición.

### Los nueve casos, resueltos

| | Caso | ¿Mismo espacio? | Por qué |
|---|---|---|---|
| **A** | Mismo modelo, runtime, revisión y configuración | **SÍ** | Caso trivial |
| **B** | PyTorch vs ONNX FP32, **equivalencia demostrada** | **SÍ, condicionado** | Misma función. Exige atestación registrada, no suposición |
| **C** | PyTorch vs ONNX FP32 con **pequeñas diferencias** | **Depende del criterio** | «Pequeña» no significa nada hasta que el criterio exista |
| **D** | FP32 vs INT8 | **NO, por defecto** | Cambian los pesos, no solo la aritmética. Podría atestarse; la carga de la prueba es suya |
| **E** | Distinto **pooling** | **NO, nunca** | CLS y mean son funciones distintas sobre los mismos estados |
| **F** | Distinta **normalización** | **NO, nunca** | Cambia el vector |
| **G** | Distintos **prefijos** | **NO, nunca** | Ya resuelto así: están en la clave y hay un test que lo fija |
| **H** | Distinta **tokenización o truncamiento** | **NO, nunca** | Cambia la entrada real del encoder |
| **I** | Otro modelo | **NO, nunca** | Trivial |

### La partición que decide el diseño

Los casos se agrupan en dos naturalezas distintas, y confundirlas es el error
que este ADR corrige:

- **E, F, G, H, I son diferencias de contrato semántico.** No admiten
  demostración: son funciones distintas por definición. La estructura debe
  hacerlas imposibles de confundir, poniéndolas en la clave.
- **B, C, D son diferencias de implementación numérica.** Aquí sí cabe
  preguntar «¿producen lo mismo?», y esa pregunta se responde midiendo.

**Un solo campo `runtime` en la `unique` mezclaría las dos naturalezas**,
tratando una pregunta empírica como si fuera una etiqueta.

## Definición de productor

### El criterio de inclusión

Para cada atributo candidato: **¿cambiar su valor puede cambiar los números?**
Si no puede, es procedencia, no identidad.

### Identidad del productor

| Campo | Por qué entra |
|---|---|
| `runtime_family` | `sentence-transformers`, `onnxruntime`, `llama.cpp`… |
| `precision` | `fp32`, `fp16`, `bf16` |
| `quantization` | `none`, `int8-dynamic-qdq`, `q8_0`, `q4_k_m`… |
| `weights_digest` | **El discriminador más fuerte.** Distingue dos exportaciones del mismo `revision` nominal, que es el caso que ninguna otra etiqueta atrapa |
| `execution_provider` | CPU, DirectML, Vulkan, CUDA: cambian los núcleos y con ellos los últimos bits |
| `output_affecting_params` | Lista **corta y cerrada**, no un volcado de configuración |

### Identidad, procedencia y condición de revalidación

Tres conceptos distintos que conviene no confundir:

| Concepto | Qué es | Qué le pasa al cambiar | Ejemplos |
|---|---|---|---|
| **Identidad** | Lo que determina si dos productores son la misma receta | **Otro productor** | precisión, cuantización, digest de pesos, proveedor de ejecución |
| **Procedencia** | Se registra para auditar. **Nunca se compara** | Nada | versión del runtime, host, CPU, hilos, tamaño de lote, fecha, actor |
| **Condición de revalidación** | Subconjunto de la procedencia cuyo cambio invalida **la prueba**, no la identidad | Las atestaciones que dependían de ella quedan **pendientes de reverificación** | `runtime_version` |

El caso que esto resuelve, y que es la fuerza F5: **actualizar el runtime de
una versión de parche a la siguiente no crea un productor nuevo y no obliga a
regenerar nada.** Lo que hace es dejar obsoletas las atestaciones probadas
bajo la versión anterior, hasta que la sonda vuelva a pasar.

El razonamiento de fondo: el número de hilos y el tamaño de lote **no deben**
cambiar el resultado. Si lo cambian, eso es un defecto del runtime, no un
espacio vectorial nuevo — y la forma correcta de detectarlo no es versionar la
clave, es **volver a medir**.

## Space digest

### Qué entra

El `space_digest` se deriva **únicamente** de los atributos que definen el
contrato semántico:

| Campo | Estado hoy |
|---|---|
| `model_id` | existe |
| `revision` (commit o digest inmutable) | existe |
| `dimension` | existe |
| `normalized` | existe |
| `document_prefix`, `query_prefix` | existen |
| `composition_template` | existe |
| **`pooling`** | **no existe** |
| **`tokenizer_digest`** | **no existe** — ADR 0013 §2 lo prometía |
| **`max_sequence_length` y política de truncamiento** | **no existe** — ADR 0013 §2 lo prometía |

### Qué NO entra, y por qué

- **`runtime` y `runtime_version`**: pertenecen al productor y a la
  procedencia. Esto es el corazón de la decisión.
- **Parámetros operativos** —hilos, tamaño de lote, sistema operativo, fecha,
  CPU—: no cambian el resultado, y si lo cambian son un defecto.
- **`family`**: **decisión cerrada, no entra.** Es descriptivo y derivable
  —hoy se calcula como el prefijo de `model_id`— y no modifica la función
  texto → vector. Se conserva como metadato legible, nunca como identidad.
- **`similarity`**: ver el apartado siguiente.

### Por qué el tokenizador va en el espacio y no en el productor

Tres razones: ADR 0013 §2 ya lo colocaba ahí; cambia el **significado de la
entrada**, no la aritmética de la salida; y dos productores del mismo espacio
tienen que usarlo idéntico por definición. Ponerlo en el espacio hace que un
desajuste de tokenizador falle **al registrar**, no después de medir.

### `similarity` no pertenece al espacio

**La pregunta correcta:** ¿coseno, producto interno o L2 modifican el **vector
producido**? **No.** Son funciones de comparación aplicadas a vectores ya
calculados. No participan en la función texto → vector.

**Clasificación:** `similarity` pertenece a una capa distinta, de
**configuración de recuperación**, y **no entra en el `space_digest`**.
`normalized` sí pertenece al espacio, porque modifica el vector.

**Consecuencia:** dos configuraciones idénticas en todo lo semántico pero que
declaren distinta métrica son **el mismo espacio**, consultado de otra forma.
Los vectores almacenados sirven para ambas.

**Lo que sí está acoplado, y no lo contradice.** El esquema tiene hoy
`ck_embedding_model_cosine_needs_normalised`: `similarity <> 'cosine' or
normalized`. Eso no prueba que la métrica sea parte del espacio; expresa una
**restricción de compatibilidad entre dos capas** —el espacio vectorial y la
configuración de recuperación—, porque la interpretación que ELSA hace de la
puntuación (`similarity = 1.0 - distance`) supone vectores normalizados.

**El esquema actual ya está de acuerdo, sin saberlo.** `similarity` **no
figura en la `unique`**: hoy ya se comporta como un atributo no identificador.
Lo único que falta es la etiqueta conceptual. La columna se conserva donde
está —este ADR **no cambia la base**— y se reclasifica.

No se fuerza la clasificación por el hecho de que el esquema histórico ya lo
almacene. Se clasifica por lo que hace, y resulta que el esquema no estorba.

## Productor de referencia y productor alternativo

### La designación es explícita

> Cada espacio vectorial tiene exactamente **un productor de referencia,
> designado explícitamente**.

Esa designación:

- queda asociada al espacio **al crearlo**, como parte del acto de registro;
- **no** la decide `generate`: ejecutar una generación no convierte a nadie en
  referencia;
- **no** la altera registrar otros productores;
- solo podría cambiar mediante una operación futura explícita y auditable, si
  alguna vez se decide soportarla. **Este ADR no la diseña.**

**Por qué explícita y no «el primero que generó».** Hacer depender una
identidad arquitectónica de un hecho operativo la vuelve frágil: dos corridas
concurrentes, una prueba lanzada por error o un `generate` de reconocimiento
decidirían en silencio quién define el espacio. La referencia es una
afirmación sobre qué queremos representar, y las afirmaciones se declaran.

### Los dos papeles

| | **Productor de referencia** | **Productor alternativo** |
|---|---|---|
| Quién es | El designado explícitamente para ese espacio | Cualquier otro |
| Define el espacio | Sí | No |
| Necesita atestación | **No**, contra sí mismo no tiene sentido | **Sí**, y válida |
| Puede generar documentos | Sí, cumpliendo las validaciones del espacio | Solo con atestación válida |
| Puede generar consultas | Sí, cumpliendo las validaciones del espacio | Solo con atestación válida |

## Atestación de equivalencia

### La regla

Un productor alternativo entra en un espacio **solo** mediante una atestación
registrada contra el productor de referencia de ese espacio.

### Qué registra una atestación

- espacio, **productor de referencia**, **productor candidato**;
- versión del conjunto de sondas empleado;
- estadísticas numéricas: similitud coseno (mínimo, media, mediana, máximo),
  error absoluto medio y máximo, distancia L2, y el **ejemplo responsable del
  peor caso**;
- comparación de **recuperación y ranking** sobre el banco de ELSA;
- `runtime_version` y proveedor de ejecución **de ambos lados**;
- fecha y actor;
- **artefacto de evidencia y su digest**;
- veredicto;
- estado: **válida · obsoleta · revocada**.

Reportar el **mínimo** y el **peor caso** —no solo la media— no es un adorno:
una media excelente con un caso pésimo es exactamente el perfil que degrada un
ranking sin que se note.

### No hay equivalencia asimétrica en la primera versión

Una atestación cubre **ambos caminos**: `embed_documents` y `embed_queries`.
Los prefijos difieren, así que un productor puede comportarse distinto en cada
lado y medir uno solo dejaría el otro sin evidencia.

Una revisión futura podría permitir membresía asimétrica —apto para consultas
y no para documentos—. Queda **fuera** de este diseño: duplicaría el espacio
de estados por una ganancia que hoy nadie necesita (regla 23).

### El umbral no se fija aquí

El criterio numérico depende de datos que todavía no existen. La fase 1 del
experimento ONNX está diseñada exactamente para producir esa caracterización,
y su propio informe declara que «no aplica ningún umbral de aceptación…
fijar uno antes de verlo sería elegir el resultado». **Lo mismo vale aquí**:
este ADR crea el mecanismo, no el número.

### Por qué esta política y no la estricta pura

La estricta pura —todo productor distinto es un espacio distinto— no requiere
umbral y es imposible de equivocar. Se descarta por dos razones:

1. **Si ONNX FP32 reprodujera los vectores hasta el último bit, habría que
   regenerar el corpus igualmente**, y jamás podría cambiarse el runtime de
   consulta.
2. **Crea presión para mentir** (fuerza F4). Una regla que solo se cumple
   pagando de más acaba incumpliéndose sin dejar rastro.

Lo que se conserva de ella es lo esencial: **el comportamiento estricto es lo
que se obtiene sin hacer nada**. El caso peligroso exige un acto deliberado y
registrado. Hoy exige lo contrario: no darse cuenta.

## Sonda canónica

### Por qué un digest no basta

Un **digest del vector demuestra identidad bit a bit y nada más.** El caso
principal de ELSA —PyTorch FP32 frente a ONNX FP32— puede presentar
diferencias numéricas pequeñas y ser aun así equivalente bajo un criterio
futuro. Un diseño basado solo en hashes **excluiría por construcción el caso
que motivó todo esto**.

Por tanto: la sonda debe permitir **comparar numéricamente**, no solo
verificar igualdad.

### Qué contiene el conjunto de sondas

Asociado al espacio, versionado:

| Elemento | Para qué |
|---|---|
| Identificador de la sonda | Citar un caso concreto |
| `kind`: `document` o `query` | Los prefijos difieren; hacen falta ambos |
| Texto exacto, o su digest verificable | Demostrar que los dos productores vieron lo mismo |
| Tokenización observada bajo la referencia: identificadores, longitud, truncamiento | Separar «el encoder calcula distinto» de «la entrada era otra» |
| **Referencia numérica**: los vectores de referencia, o una referencia a un artefacto numérico versionado | Permitir comparación aproximada, no solo igualdad |
| **Digest del artefacto** | Integridad: detectar una referencia alterada |

### Dos mecanismos, y no se unifican

**Decisión cerrada: coexisten los dos, y son distintos a propósito.**

**A. Sonda canónica sintética.** Textos del corpus sintético del banco
(`bench/corpus-sintetico/`), que ya está versionado y **no contiene nada de la
planta**. La regla 12 lo exige: los datos reales nunca entran en Git, y un
artefacto de vectores derivado de manuales de Tampella **es dato real**. Con
textos sintéticos, el artefacto de referencia también es seguro de versionar.
Sirve para comparar productores de forma **reproducible** por cualquiera que
clone el repositorio.

**B. Caracterización contra la base, para espacios heredados.** Usa los
vectores históricos ya almacenados como referencia. **No se versiona en Git**
y **no implica que esos vectores sean verdad matemática**. Sirve para
caracterizar un espacio que nació antes de que existiera este ADR.

No se unifican porque responden preguntas distintas: A pregunta «¿estos dos
productores calculan lo mismo?» de forma reproducible y pública; B pregunta
«¿este productor reproduce lo que ELSA ya tiene guardado?».

### Cuándo se exige

**Al incorporar un productor alternativo**, y para revalidar una atestación
cuando cambie una condición de revalidación. **No** es un requisito del
productor de referencia contra sí mismo. El detalle está en los invariantes.

Es la pieza que convierte la identidad **declarada** en identidad
**verificada**, y responde a la fuerza F2.

## Procedencia

### Dónde vive

```
document_chunk_embeddings.run_id  →  embedding_runs  →  producer
```

**No se duplica el productor en cada vector.** La tabla de embeddings crece a
millones de filas; la de corridas, a decenas. `run_id` ya es `not null` con
clave foránea, así que la procedencia por vector se deriva sin coste de
almacenamiento.

### Qué debe poder responder cada corrida

- qué **espacio** estaba generando;
- qué **productor** lo generó;
- cuándo y quién la lanzó;
- con qué **runtime y versión**;
- con qué **parámetros relevantes**.

`embedding_runs` ya tiene `model_id`, `started_by`, `started_at`,
`trigger_source`, `request_id` y una columna **`parameters jsonb` que existe
en el esquema y el puerto Python no expone**. Lo que falta es que la corrida
sepa **qué productor** la ejecutó — y eso merece ser una relación de primera
clase y no una clave dentro del JSON, porque se va a consultar: «qué vectores
produjo el productor X».

### Qué habilita

Un espacio puede contener legítimamente lotes de productores distintos —un
lote de la referencia y otro de un alternativo atestado— y **cada vector sigue
siendo atribuible**. Espacio y procedencia responden preguntas distintas: uno
dice si los vectores son comparables, el otro dice quién los hizo.

## Invariantes

### I1 — REGISTER

Registrar un espacio y registrar un productor son **operaciones
conceptualmente distintas**. Buscar un espacio por su contrato y buscar un
productor por su receta son búsquedas distintas.

Un productor nuevo sobre un espacio existente **se registra sin conflicto y
sin membresía**. El camino que hoy lleva a la mezcla —una única búsqueda que
devuelve la fila ajena— desaparece porque las dos búsquedas se separan.

**Registrar un productor no lo declara equivalente.** Registrar es decir que
existe; atestar es decir que produce lo mismo.

### I2 — DESIGNACIÓN DE LA REFERENCIA

Al crear un espacio queda **designado explícitamente** su productor de
referencia. Ni `generate` ni el registro de otros productores modifican esa
designación. Cambiarla exigiría una operación futura explícita y auditable,
que este ADR no diseña.

### I3 — GENERATE

Distingue los dos papeles, porque un espacio nuevo todavía no tiene vectores
contra los cuales demostrar nada:

**El productor de referencia** puede generar los vectores del espacio que
define. Antes debe superar las validaciones del espacio:

- validación de configuración;
- identidad declarada;
- integridad de los artefactos;
- dimensión;
- prefijos;
- pooling;
- tokenizador y su configuración;
- normalización;
- el resto de invariantes del espacio.

**No necesita una atestación de equivalencia contra sí mismo.** Exigirla sería
pedirle que demuestre que es igual a sí mismo antes de existir, y dejaría
imposible arrancar cualquier espacio nuevo.

**Un productor alternativo** no puede generar documentos ni consultas para ese
espacio hasta contar con: sonda canónica, medición, criterio de equivalencia
aprobado y **atestación válida** (no obsoleta, no revocada).

En ambos casos, cada corrida registra el productor **real**, no el esperado.

### I4 — ACTIVATE

Activar significa **activar un espacio vectorial**, no «un modelo».

Solo puede activarse un espacio que tenga vectores válidos, y el productor
destinado a las consultas debe ser miembro válido de ese espacio: su
referencia designada, o un alternativo con atestación válida.

**Pero la activación no puede ser el único punto de control.** El productor de
consulta lo elige la configuración del proceso, no la base de datos, y puede
cambiar sin tocar una sola fila. Un control que solo mira al activar es
precisamente el que el segundo agujero de la sección «Problema» esquiva.

### I5 — QUERY

Antes de cualquier búsqueda vectorial, ELSA verifica que **el productor de la
consulta es miembro válido del espacio activo**.

El vector de consulta llega **acompañado de la identidad de quien lo
produjo**, igual que hoy llega acompañado implícitamente de una afirmación
sobre su dimensión.

> Nunca se combinan silenciosamente documentos del espacio A con consultas del
> espacio B.

### I6 — QUÉ OCURRE CUANDO LA VERIFICACIÓN FALLA

Un productor no miembro es un **error de configuración e integridad del
espacio vectorial**. En la primera versión, ELSA **falla explícitamente** antes
de usar vectores incompatibles.

Cómo se expresa con los contratos actuales, sin fijar todavía nombres
definitivos:

| Contrato existente | ¿Sirve? |
|---|---|
| `VectorIntegrityError` — «el vector no encaja con el modelo, el chunk o su versión» | **La familia correcta.** Ya cubre el desajuste de dimensión en `search` |
| `EmbeddingConfigurationError` — «la configuración no describe un espacio vectorial reproducible» | **También adecuada** para el caso que nace de una configuración incoherente |
| `ActiveModelError` | **NO.** `HybridRetrievalService._semantic` lo captura y degrada el canal semántico en silencio. Usarlo reintroduciría la silencio que esta decisión prohíbe |
| `AnswerStatus.ERROR` | **Sí**, en la capa de respuesta. `GroundedGenerationService` ya traduce fallos técnicos a `ERROR`, y ADR 0017 fijó que un `ERROR` no es un «no hay nada» |
| `AnswerStatus.NO_EVIDENCE` | **NO.** Decirle a un ingeniero que no hay información cuando lo que pasa es que el sistema está mal configurado es la confusión más peligrosa que ese contrato ya evita |

Lo que este ADR fija: **el fallo no puede ser capturable por la ruta de
degradación existente**, y debe distinguirse de `NO_EVIDENCE` y de la
indisponibilidad normal. Si la implementación acaba usando una excepción nueva
o una existente es decisión de implementación, **diferida**.

Un modo degradado deliberado —continuar solo con los canales exacto y léxico—
es concebible y **no forma parte de este ADR**: sería otra decisión explícita.

## Legacy

### Principios

**Aditiva.** No se reescribe ningún vector, no se borra ninguna columna, no se
toca el disparador de inmutabilidad.

**Conservadora.** Lo que no se registró **no se inventa**.

**Segura por omisión.** Un espacio cuya referencia no está caracterizada **no
admite un productor alternativo**, porque no hay contra qué atestar.

### Qué hace la migración futura

- Cada fila actual de `embedding_models` sigue siendo el **espacio**, con su
  identificador, su estado y su activación intactos.
- La migración **designa explícitamente** como productor de referencia de cada
  espacio al productor histórico reconstruido a partir de la información
  disponible: `runtime` y `family`. La designación es un acto de la migración,
  no una consecuencia de qué corrida ocurrió antes.
- Las corridas existentes se atribuyen a ese productor.
- Los vectores no se tocan.

### Qué queda como `legacy` / `unknown`

`precision`, `quantization`, `weights_digest`, `execution_provider`,
`pooling`, `tokenizer_digest`, `max_sequence_length`.

**Ninguno se registró nunca.** Se marcan explícitamente como desconocidos, no
como un valor plausible: un `precision = 'fp32'` inventado sería una
afirmación sin respaldo justo en la tabla que existe para no tener que suponer
nada.

### El BGE-M3 actual no se invalida

Un espacio heredado **sigue siendo válido, activo y consultable por su
productor de referencia designado**. Lo único que no puede hacer es admitir un
productor alternativo mientras no se sepa contra qué compararlo.

### Caracterización de un espacio heredado

Los vectores almacenados sirven de referencia, **y conviene formularlo con
precisión**:

> Los vectores históricos **no son verdad matemática**. Son la **referencia
> operacional histórica**: lo que ELSA ha estado recuperando efectivamente
> hasta hoy.

Eso basta, y basta por una razón concreta: el espacio *es* aquello contra lo
que ELSA recupera. La pregunta «¿estaba PyTorch calculando bien?» no se
plantea aquí, no se puede responder aquí, y no hace falta responderla. Lo que
hay que decidir es si un productor candidato puede **acompañar o sustituir** al
que produjo lo que ya está guardado, y eso se responde comparando contra lo
guardado.

**Procedimiento conceptual:**

1. Se elige un conjunto canónico de chunks que **ya tienen vector**, y un
   conjunto de consultas.
2. El productor candidato los re-embebe.
3. Se compara contra lo almacenado.
4. El resultado sostiene la caracterización del espacio y, con ella, la
   primera atestación.

**No se regeneran los vectores históricos durante la caracterización.** Y el
mismo procedimiento sirve para confirmar que el productor de referencia sigue
produciendo lo que producía.

## Consecuencias positivas

- **El fallo silencioso desaparece.** Mezclar productores pasa de ser lo que
  ocurre por defecto a requerir un acto deliberado y registrado.
- **El agujero de la consulta se cierra.** Cambiar el runtime por variable de
  entorno deja de poder alterar el ranking sin aviso.
- **El camino honesto tiene mecanismo.** Si ONNX FP32 demuestra equivalencia,
  existe una ruta registrada para aprovecharla sin regenerar.
- **Una actualización de parche no cuesta una regeneración.** Solo obliga a
  reverificar.
- **Un espacio nuevo puede arrancar.** La referencia designada genera sin
  tener que demostrar equivalencia contra sí misma.
- **La procedencia se responde sin coste.** Quién produjo cada vector es
  derivable, sin una columna en millones de filas.
- **Se salda una deuda de ADR 0013.** Tokenizador, ventana máxima y pooling
  dejan de ser promesas.
- **La decisión es independiente de la que la motivó.** Funciona con cualquier
  resultado del experimento.
- **El banco ya produce la evidencia.** El artefacto de comparación del
  experimento ONNX contiene exactamente las estadísticas que una atestación
  necesita.
- **La identidad pasa de declarada a verificada** (fuerza F2).

## Consecuencias negativas y costos

Se dicen enteras, porque son reales:

- **Aparecen conceptos nuevos.** Espacio, productor, referencia, alternativo,
  atestación, sonda. Quien continúe el proyecto tiene más cosas que entender.
- **Incorporar un productor alternativo deja de ser gratis.** Requiere
  registrar, medir, atestar y verificar. Ese es el punto, y es el coste.
- **La atestación se queda obsoleta sola.** Cada actualización del runtime la
  invalida hasta reverificar. Es fricción operativa recurrente, deliberada.
- **La primera versión crea un mecanismo que todavía no puede usarse.** Sin
  criterio numérico no se puede atestar nada. Mientras tanto todo corre en
  estricto — que es seguro, y que significa que **la primera consecuencia
  práctica de este ADR es que ONNX exigirá regenerar, hasta que exista el
  umbral**.
- **La sonda añade un paso al incorporar productores**, y hay que mantenerla.
- **La migración tiene que escribirse con cuidado**: es aditiva, pero toca la
  tabla más sensible del esquema.
- **Hay un riesgo de ceremonia.** Si atestar resultara tan costoso que nadie
  lo hiciera, volvería la presión de F4 por otra vía. Conviene vigilarlo: si
  ocurre, el problema es el procedimiento, no la política.
- **Se acepta una asimetría temporal**: un espacio heredado no puede recibir
  productores alternativos hasta caracterizarse. Es el precio de no inventar
  metadatos.

## Alternativas descartadas

**Añadir `runtime` a la `unique` y terminar.** Es lo obvio y es insuficiente:
`runtime = "onnxruntime"` no distingue FP32 de INT8, ni dos exportaciones
distintas de los mismos pesos, ni CPU de DirectML. Daría sensación de
protección y la primera cuantización la rompería en silencio. Y trata como
etiqueta una pregunta que es empírica.

**Definir la referencia como «el primero que generó».** Haría depender una
identidad arquitectónica de un hecho operativo y potencialmente de una
carrera: dos corridas concurrentes, o un `generate` lanzado por error,
decidirían en silencio quién define el espacio. La referencia se designa.

**Exigir la sonda de equivalencia también al productor de referencia.** Sería
pedirle que demuestre ser igual a sí mismo, y dejaría imposible crear ningún
espacio nuevo: no hay vectores previos contra los que medir. La referencia
supera las validaciones del espacio; no una atestación.

**Política estricta pura.** Segura y sin umbrales. Se descarta porque
impediría aprovechar una equivalencia demostrada, haría imposible cambiar el
runtime de consulta, y crearía presión para editar el descriptor (F4). Lo
valioso de ella —que estricto sea el comportamiento por defecto— **se
conserva**.

**Confiar en la identidad declarada sin sonda.** Es el diseño actual, y es el
que falló. Un adaptador que dice quién es y nadie comprueba es exactamente el
punto ciego que motivó este ADR.

**Usar solo un digest de vectores como sonda.** Demuestra identidad bit a bit
y excluye por construcción el caso principal: dos runtimes FP32 con
diferencias mínimas y equivalentes bajo criterio. Sería una sonda que
garantiza no responder la pregunta que hay que responder.

**Unificar la sonda sintética con la caracterización contra la base.**
Responden preguntas distintas y tienen restricciones distintas: la sintética
es versionable y reproducible por cualquiera; la caracterización usa datos que
no pueden entrar en Git (regla 12). Fundirlas obligaría a sacrificar una de
las dos propiedades.

**`producer_id` en cada fila de `document_chunk_embeddings`.** Millones de
filas para un dato que `run_id` ya deriva. Se descarta por coste sin
beneficio.

**Equivalencia asimétrica en la primera versión.** Duplicaría el espacio de
estados —apto para consultas pero no para documentos— para un caso que nadie
ha pedido. Queda **diferida**, no descartada.

**Degradar el canal semántico ante un productor incompatible.** Sería
consistente con ADR 0016, que ya degrada cuando no hay modelo activo. Se
descarta porque reintroduciría el silencio: un ranking que empeora sin aviso
es peor que una consulta que falla. La indisponibilidad y la incompatibilidad
son cosas distintas y merecen respuestas distintas.

**Incluir `runtime_version` en la identidad.** Convertiría cada actualización
de parche en una migración de datos. Se resuelve mejor con la condición de
revalidación.

**Incluir `similarity` o `family` en el `space_digest`.** Se evaluaron y se
descartan: ninguno modifica el vector. `similarity` solo cambia cómo se
comparan; `family` es derivable de `model_id`.

## Compatibilidad con los ADR anteriores

Resumen, y debajo el detalle de los dos que sí cambian de alcance:

| ADR | Efecto de esta decisión |
|---|---|
| **0013** — almacenamiento vectorial | **Amplía §2 · matiza §5.** Ver abajo |
| **0015** — elección del modelo | **Intacto.** Su corrida pasa a ser el primer caso heredado. Ver abajo |
| **0016** — recuperación híbrida | Intacto. Gana un motivo más de indisponibilidad del canal semántico |
| **0017** — generación fundamentada | Intacto. `ERROR` frente a `NO_EVIDENCE` se reutiliza tal cual |
| **0014** — confusabilidad no es autorización | Intacto. Se cita como precedente y como límite |
| **0011** — chunking determinista | Intacto. Cambiar de productor es re-embeber, nunca re-trocear |
| **0003** — puertos y adaptadores | Intacto. El descriptor del puerto gana campos |
| **0001** — Supabase CLI única autoridad | Intacto. La migración será versionada, con su rollback |

### ADR 0013 — qué se conserva y qué se amplía

**Se conserva íntegro:** §1 el vector vive en tabla aparte · §3 la corrida de
embedding es una tabla · §4 un embedding se sabe obsoleto por
`embedded_sha256` · §6 los filtros son obligatorios y el piloto usa búsqueda
exacta · §7 qué se embebe y qué no · §8 el motor es reemplazable. Y sobre
todo **§5: generar no activa**, que esta decisión refuerza en lugar de tocar.

**Se amplía §2.** La lista de identidad del modelo se parte en contrato
semántico y productor numérico, y se completa con lo que ese mismo §2 ya
prometía y nunca llegó al esquema —**tokenizador y ventana máxima**— más
**pooling**.

**Se matiza §5, solo en su alcance.** «Activar un modelo» pasa a significar
«activar un espacio vectorial, con su productor de consulta verificado». La
regla de que generar no activa **no cambia**: se le añade que activar tampoco
basta, porque el productor de consulta vive en la configuración del proceso.

### ADR 0015 — intacto, y primer caso heredado

La decisión de modelo y su condición legal quedan **intactas**: este ADR no
toca qué modelo gana ni reabre nada.

Lo que sí cambia es cómo se lee su corrida a la luz de esta decisión. Se midió
con `revision = "main"` y `runtime = sentence-transformers` sin más detalle,
así que es **el primer caso heredado** que la migración tendrá que designar
explícitamente. Y su exigencia de que las tres corridas reprodujeran las
mismas huellas antes de compararlas es el **precedente directo** de la
atestación: la comparabilidad se demuestra, no se supone.

### ADR 0016 — incompatibilidad no es indisponibilidad

El canal semántico ya sabe declararse indisponible y decir qué canales
respondieron. Esta decisión añade una distinción: **un productor incompatible
no es un modelo ausente**. La indisponibilidad sigue degradando como hoy; la
incompatibilidad falla explícitamente.

**Ningún ADR existente se modifica.** Este los referencia; ADR 0013 queda
**ampliado en §2 y matizado en §5**, nunca reescrito en silencio.

### Capas que permanecen completamente ajenas

No necesitan conocer el concepto de productor, y este ADR se compromete a que
no lo conozcan:

**chunking · documentos · autorización · permisos y scopes · recuperación
exacta · recuperación léxica · `GroundedGenerationService` · `ContextBuilder`
· `grounding` · LLM.**

Solo cuatro piezas lo conocen: el **adaptador de embeddings** (lo declara), el
**almacén vectorial** (impone la membresía), la **administración y generación
de embeddings** (registra, designa y atesta) y la **recuperación semántica**.

El orden de seguridad no cambia:

```
autorización → retrieval filtrado → contexto autorizado → LLM
```

Se conservan sin cambio: múltiples modelos, múltiples revisiones, `generate`,
`activate`, rollback, el banco de pruebas, la autorización previa a la
recuperación y la búsqueda vectorial filtrada por scopes.

## Plan conceptual de migración

Sin SQL. Aditiva y reversible.

**Se conserva** `embedding_models` como tabla del espacio, con su clave
primaria, su estado, su activación y su disparador de inmutabilidad.

**Se añaden** al espacio los campos semánticos que faltan —`pooling`,
`tokenizer_digest`, `max_sequence_length`— **admitiendo valor desconocido**,
para que las filas actuales sigan siendo válidas.

**Se amplía** la clave única del espacio con esos campos.

**Se conserva `runtime` donde está**, como columna heredada. Quitarla obligaría
a tocar el disparador de inmutabilidad y haría el rollback destructivo.

**Se introducen** las estructuras nuevas: productores, designación de
referencia, atestaciones y conjunto de sondas.

**Se enlaza** la corrida con su productor.

**Se rellena hacia atrás**: la migración **designa explícitamente** el
productor de referencia de cada espacio existente, reconstruido a partir de
`runtime` y `family`, con el resto de atributos marcado desconocido; cada
corrida existente se atribuye a él.

**No se toca ningún vector.**

**Rollback**: al ser aditiva, retirar las estructuras y columnas nuevas
devuelve el sistema al comportamiento actual, con todos los modelos, vectores,
corridas y activaciones intactos. El único efecto de revertir es **volver a
quedar sin protección** — no perder datos.

## Casos de prueba futuros

Dieciocho. No se escriben aquí; se fijan para que quien los escriba sepa qué
protegen.

| # | Caso | Debe garantizar |
|---|---|---|
| 1 | Mismo espacio, mismo productor | Camino feliz completo. `generate` sigue siendo idempotente por `embedded_sha256` |
| 2 | Mismo espacio, productor alternativo **atestado** | Genera y consulta sin regenerar. **Sin la atestación, el mismo caso falla** |
| 3 | Mismo `model_id`, **cuantización distinta** | Productor distinto; no colisiona ni reutiliza vectores; `generate` se detiene sin atestación |
| 4 | Mismo `model_id`, **prefijo distinto** | Sigue siendo otro espacio; el test existente debe seguir pasando |
| 5 | Mismo `model_id`, **tokenizador distinto** | Otro espacio, detectado **al registrar**, no al medir |
| 6 | Embeddings **heredados** | Se consultan con su referencia designada y **rechazan** un alternativo sin caracterizar |
| 7 | **Consultas de un espacio contra documentos de otro** | Se rechaza. Es el agujero abierto hoy |
| 8 | **Rollback** al productor o modelo anterior | Activar el anterior funciona sin regenerar; ADR 0013 §5 sigue siendo cierto |
| 9 | **Regeneración parcial interrumpida** | La corrida queda `failed` con su motivo, lo escrito sigue sirviendo, y **no queda ningún vector del alternativo dentro del espacio del anterior** |
| 10 | Dos productores **declarándose equivalentes sin evidencia** | Se rechaza. Una declaración desnuda no basta |
| 11 | **`runtime_version` cambia y la sonda sigue pasando** | La atestación se revalida; **no** se crea un productor nuevo; **no** se regenera nada |
| 12 | **`runtime_version` cambia y la sonda falla** | La atestación queda obsoleta; generar y consultar se detienen hasta resolverlo |
| 13 | **Cambia la métrica de similitud sin cambiar los vectores** | Sigue siendo el **mismo espacio**; los vectores almacenados siguen sirviendo; no se regenera |
| 14 | Productor aparentemente correcto pero **`weights_digest` distinto** | Productor distinto. Es el caso que ninguna otra etiqueta atrapa |
| 15 | **Artefacto de sonda o de referencia alterado** | La comprobación de integridad falla; no se acepta la medición |
| 16 | **Espacio nuevo con su referencia designada** | La referencia genera **sin** atestación, tras superar las validaciones del espacio |
| 17 | **Capas ajenas** | Chunking, permisos, documentos, generación y LLM pasan sus tests sin conocer el concepto de productor |
| 18 | **Incompatibilidad ≠ indisponibilidad** | Un productor no miembro **no** se confunde con «no hay modelo activo» ni con `NO_EVIDENCE`, y la ruta de degradación del canal semántico **no** lo captura |

**Nota de método:** el caso 7 debería escribirse **antes** que la solución,
como prueba que falla contra el código actual. Es la única forma de demostrar
que el agujero existía y que se cerró.

## Decisiones explícitamente diferidas

La arquitectura queda decidida ahora. Quedan diferidos **únicamente**:

- **umbrales y criterios numéricos** de equivalencia;
- **resultado de PyTorch FP32 frente a ONNX FP32**;
- **resultado de INT8**;
- **composición definitiva de la sonda**: cuántos textos y cuáles;
- **equivalencia asimétrica** (apto para consultas y no para documentos);
- **modo degradado** deliberado ante un productor incompatible;
- **nombres definitivos de las excepciones**, y si se reutiliza una existente
  o se añade una nueva;
- **implementación física del esquema** y su migración.

Fuera del alcance de este ADR, y no se prejuzgan: si ONNX se aprueba · el
modelo definitivo · GGUF · la topología · nube u on-premise · sidecar HTTP ·
PC1 como servidor · la integración con FastAPI · el Modo ELSA.

**La identidad del espacio vectorial funciona correctamente con cualquier
resultado de todas ellas.** Esa es la condición que este ADR tenía que
cumplir, y es la razón de que se decida ahora y no después.

## Ver también

- [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md) — dónde vive el vector; generar no activa; la identidad que aquí se amplía
- [ADR 0015](0015-eleccion-del-modelo-de-embeddings.md) — qué modelo, con qué condición, y la comparabilidad como precedente
- [ADR 0016](0016-recuperacion-hibrida-del-mvp.md) — el canal semántico y su degradación
- [ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md) — por qué un `ERROR` no es un «no hay nada»
- [ADR 0014](0014-confusabilidad-no-es-autorizacion.md) — esto es calidad, no seguridad
- [ADR 0011](0011-chunking-estructural-deterministico.md) — cambiar de productor no obliga a re-trocear
- [ADR 0003](0003-puertos-y-adaptadores-para-modelos-reemplazables.md) — por qué el runtime era reemplazable desde el principio
- [`bench-onnx-experimental.md`](../bench-onnx-experimental.md) — el experimento que producirá la evidencia de la primera atestación
