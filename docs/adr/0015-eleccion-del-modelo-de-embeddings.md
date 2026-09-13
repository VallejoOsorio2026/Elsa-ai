# ADR 0015 — EmbeddingGemma gana el banco; BGE-M3 es el candidato productivo

- Estado: **aceptado en lo técnico · condicionado en lo legal**
- Bloque: 4.2.a, etapa B
- Recoge las decisiones **D1**, **D7** y **D11** de
  [`bloque-4-2-plan.md`](../bloque-4-2-plan.md) §4
- Se apoya en [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md)
  (dónde vive el vector) y [ADR 0014](0014-confusabilidad-no-es-autorizacion.md)
  (qué mide el banco y qué no)
- **No autoriza integración productiva.** Eso es la etapa C, no iniciada

## Contexto

La etapa A dejó construido el banco y midió tres líneas base, pero no pudo
ejecutar ningún candidato: la política de egreso del entorno bloqueaba
HuggingFace. La etapa B se ejecutó en otra máquina (PC1), con los tres
candidatos obligatorios y el mismo banco.

Este ADR registra qué se midió, qué se decide y qué queda condicionado.

## Qué se midió, y por qué las tres corridas son comparables

La comparabilidad no se da por supuesta. Cada corrida es un archivo propio, y
los tres se verificaron antes de leer un solo resultado:

| Verificación | Resultado |
|---|---|
| Huella del corpus | `34bebb71…` — **idéntica** en los tres y en la línea base de la etapa A |
| Huella del conjunto dorado | `51171efc…` — **idéntica** en los tres |
| Plantilla de composición | `context-v1` — **idéntica** en los tres |
| Líneas base dentro de cada informe | `lexical-bm25`, `lexical-trigram` y el control determinista dan cifras **bit a bit idénticas** en los tres archivos |

La última es la prueba fuerte. Cada informe incluye las tres líneas base junto
a su candidato; que las tres reproduzcan exactamente los mismos números en los
tres archivos demuestra que el corpus, el conjunto dorado, la composición y el
código de métricas fueron los mismos. La huella `comparison_fingerprint` sí
difiere entre archivos, y debe hacerlo: cada uno contiene un candidato denso
distinto.

**Corpus y consultas:** 42 chunks troceados con el chunker real
`structural-v1`, dos activos técnicos, español e inglés, una versión publicada
y otra sin publicar. 67 consultas en 19 ejes, de las cuales **59 puntúan** —
las 4 de códigos son diagnóstico (ADR 0014) y 4 no tienen respuesta esperada,
para medir abstención.

**Hardware real (PC1):** Windows, Python 3.12.13, CPU AMD64 Family 23 Model 17
(AuthenticAMD), ~7,9 GB de RAM, **sin GPU**. Runtime `sentence-transformers`
sobre `cpu` en los tres.

## Resultados

### Puntuación principal — 59 consultas, códigos excluidos

| Corrida | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | P@5 | conf@5 |
|---|---|---|---|---|---|---|---|---|
| **`google/embeddinggemma-300m`** | **0,831** | **0,797** | **0,905** | **0,958** | **0,878** | **0,847** | 0,285 | 0,200 |
| `BAAI/bge-m3` | 0,678 | 0,771 | 0,893 | 0,915 | 0,783 | 0,783 | **0,288** | 0,213 |
| `Qwen/Qwen3-Embedding-0.6B` | 0,559 | 0,715 | 0,860 | 0,898 | 0,706 | 0,719 | 0,278 | **0,173** |
| `lexical-bm25` *(línea base)* | 0,661 | 0,658 | 0,763 | 0,822 | 0,742 | 0,709 | 0,244 | 0,187 |
| `lexical-trigram` *(línea base)* | 0,373 | 0,508 | 0,669 | 0,848 | 0,556 | 0,591 | 0,220 | 0,187 |
| `control-hashing-ngrams` *(no es un modelo)* | 0,458 | 0,667 | 0,774 | 0,873 | 0,630 | 0,653 | 0,251 | 0,160 |

EmbeddingGemma encabeza **las seis métricas de calidad**. `P@5` queda
prácticamente empatado entre los tres (0,285 / 0,288 / 0,278) y no discrimina.

### Por eje: el ganador gana por la razón correcta

La etapa A dejó establecido cuál sería el eje decisivo antes de medir:
`synonyms`, el único donde las tres líneas base se quedaban en 0,500 o menos y
el único que la composición del contexto no mejoró. Es la comprobación de que
el modelo aporta semántica y no coincidencia de palabras.

| Eje (R@5) | n | Gemma | BGE-M3 | Qwen3 | BM25 | Control |
|---|---|---|---|---|---|---|
| **`synonyms`** | 4 | **0,625** | 0,500 | 0,375 | 0,500 | 0,250 |
| **`cross_language`** | 4 | **0,875** | **0,875** | **0,875** | 0,500 | 0,500 |
| `narrative` | 4 | **1,000** | **1,000** | 0,750 | 0,500 | 0,875 |
| `typos` | 4 | **1,000** | **1,000** | **1,000** | 0,375 | 0,750 |
| `section_reference` | 3 | **1,000** | **1,000** | **1,000** | 0,667 | 0,667 |
| `failure_symptoms` | 4 | **1,000** | 0,750 | 0,750 | 1,000 | 1,000 |
| `component_names` | 4 | 0,667 | 0,542 | 0,625 | **0,875** | 0,792 |
| `numbers_units` | 4 | 0,875 | **1,000** | **1,000** | 1,000 | 0,625 |
| `codes` *(diagnóstico)* | 4 | 1,000 | 1,000 | 1,000 | 1,000 | 1,000 |

Tres lecturas que importan:

1. **`synonyms` decide, y solo EmbeddingGemma supera la línea léxica.** 0,625
   frente a 0,500 de BM25; BGE-M3 empata con BM25 y Qwen3 queda **por debajo**.
   En el eje que mide lo que un vector debe aportar, Qwen3 no aporta.
2. **`cross_language`: los tres empatan en 0,875 frente a 0,500 léxico.** Los
   tres cruzan idiomas; ese eje confirma que los tres son multilingües reales,
   pero no separa a uno de otro.
3. **`component_names` es el único eje donde BM25 gana a los tres densos**
   (0,875). Es la señal más clara de que el canal léxico del Bloque 4.3 no
   sobra: hay consultas que se resuelven mejor por coincidencia exacta.

### Confusabilidad

Los tres se comportan casi igual, y ninguno destaca:

| Eje (`confusion@5`, más bajo es mejor) | Gemma | BGE-M3 | Qwen3 |
|---|---|---|---|
| `asset_confusion` | 0,250 | 0,250 | **0,150** |
| `version_confusion` | 0,333 | 0,333 | 0,333 |
| `near_miss_document` | **0,000** | 0,133 | **0,000** |
| Global | 0,200 | 0,213 | **0,173** |

Qwen3 es marginalmente el menos confundible, y es también el más débil en
calidad: confunde menos porque acierta menos. La diferencia global entre los
tres (0,173–0,213) es de unas pocas consultas sobre diez, y **no cambia la
decisión**. Recordatorio de ADR 0014: esto es diagnóstico de calidad, nunca un
mecanismo de autorización; el aislamiento lo impone el filtro de la consulta.

`version_confusion` es 0,333 en los tres, el eje más confundible en todas las
corridas de todo el bloque. Dos versiones del mismo documento comparten casi
todo el texto, y por eso la elegibilidad de versión **no puede** depender del
ranking: la separa `state = 'published'` en el `where`.

### Abstención: solo uno se calla cuando no sabe

De las 4 consultas sin respuesta esperada, fracción correctamente rechazada
(umbral fijo 0,35 sobre la puntuación del primer resultado; **más alto es
mejor**):

| Corrida | Abstención |
|---|---|
| **`google/embeddinggemma-300m`** | **1,000** |
| `BAAI/bge-m3` | 0,000 |
| `Qwen/Qwen3-Embedding-0.6B` | 0,000 |

La comparación es válida entre los tres porque los tres devuelven coseno sobre
vectores normalizados; no lo sería contra BM25, cuya escala no está acotada.

Para un asistente de mantenimiento que no debe inventar, es una diferencia de
peso: con el mismo umbral, EmbeddingGemma reconoce que el corpus no contiene la
respuesta y los otros dos devuelven algo con confianza alta igualmente. No
sustituye a la regla de no afirmar sin evidencia recuperada, pero la apoya.

### Operación: la diferencia más grande del banco

| | Gemma | BGE-M3 | Qwen3 |
|---|---|---|---|
| Dimensión | **768** | 1024 | 1024 |
| Carga del modelo | 94,0 s | 216,2 s | **60,5 s** |
| Embeber 42 chunks | **12,3 s** | 61,6 s | 348,2 s |
| Latencia de consulta p50 | **102,9 ms** | 183,1 ms | 1753,2 ms |
| Latencia de consulta p95 | **115,2 ms** | 231,2 ms | 2410,5 ms |
| MB por 1000 vectores | **2,93** | 3,91 | 3,91 |

**Qwen3 es 17 veces más lento que EmbeddingGemma en consulta** (1753 ms frente
a 103 ms de mediana) y 28 veces más lento embebiendo. En una máquina sin GPU,
que es el escenario del piloto, casi dos segundos por consulta antes de
recuperar nada es inasumible para un asistente interactivo.

EmbeddingGemma es además el más barato de almacenar: 768 dimensiones son un
**25 % menos** de espacio vectorial que las 1024 de los otros dos.

## Decisión

### 1. Ganador técnico: `google/embeddinggemma-300m`

Gana las seis métricas de calidad, gana el eje discriminante `synonyms` —el
único de los tres que supera a la línea léxica ahí—, es el más rápido en
consulta, el más barato en almacenamiento y el único que abstiene correctamente.
No hay ninguna dimensión medida en la que pierda de forma relevante.

### 2. Pero no queda aprobado para producción

**EmbeddingGemma solo podrá convertirse en el modelo productivo de ELSA si se
valida formalmente que sus términos de licencia y condiciones de uso son
aceptables para el uso corporativo de PAPELSA.** Es la condición de la decisión
D1, y sigue sin cumplirse.

Dos hechos de la propia ejecución la refuerzan: es el único de los tres
distribuido bajo **Gemma Terms of Use** en vez de una licencia abierta
estándar, y el único cuya descarga **exigió autenticación y aceptar
explícitamente el acceso a un repositorio gated**. Una condición de acceso que
una persona acepta a título individual no es lo mismo que una autorización para
que una empresa lo use en un sistema interno, y el proyecto se entrega a
PAPELSA (regla 1 de `CLAUDE.md`).

Hasta que esa validación exista:

- **ganador técnico:** EmbeddingGemma-300m;
- **candidato productivo sin dependencia legal pendiente:** BGE-M3.

### 3. Segunda opción y fallback de producción: `BAAI/bge-m3`

MIT, sin repositorio gated, sin condiciones que validar. Segundo en todas las
métricas de calidad y con latencia perfectamente usable (183 ms p50). Empata a
EmbeddingGemma en `cross_language`, `narrative`, `typos` y
`section_reference`, y le gana en `numbers_units`.

Pierde en `synonyms` (0,500 frente a 0,625) —empata con BM25, es decir, en ese
eje no aporta sobre el canal léxico— y no abstiene. Es una segunda opción real,
no un premio de consolación: si la validación legal no prospera, ELSA se
construye sobre BGE-M3 sin rehacer nada.

### 4. Tercero: `Qwen/Qwen3-Embedding-0.6B`, y por qué no gana

No es una derrota ajustada. Tres razones independientes, cualquiera de ellas
suficiente:

1. **Es el más débil en calidad**: último en las seis métricas principales,
   con R@1 0,559 frente a 0,831.
2. **Falla el eje que decide.** En `synonyms` obtiene 0,375, **por debajo** de
   BM25 (0,500) y de los otros dos candidatos. Un modelo denso que no supera a
   la coincidencia de palabras en el eje de sinónimos no está aportando lo que
   se le pide.
3. **Su latencia lo descarta para el piloto**: 1753 ms de mediana por consulta
   en CPU, 17× el ganador.

Su única ventaja medida —la confusabilidad global más baja, 0,173 frente a
0,200— es marginal y es consecuencia de acertar menos.

## Consecuencias

- La dimensión del espacio vectorial del piloto queda condicionada a cuál de
  los dos se apruebe: **768** con EmbeddingGemma, **1024** con BGE-M3. La
  migración de 4.2.b no puede escribirse hasta resolver la validación legal, o
  debe escribirse para el candidato productivo (BGE-M3) y migrarse después.
- `EmbeddingsPort` tiene que distinguir consulta de documento y declarar
  identidad del modelo: los dos candidatos usan prefijos distintos
  —EmbeddingGemma exige `title: none | text: ` y `task: search result | query: `;
  BGE-M3 no usa ninguno— y medirlos igual habría falseado la comparación.
- El canal léxico del Bloque 4.3 **no es opcional**: `component_names` y
  `codes` se resuelven mejor por coincidencia exacta que por vector.
- Las cifras de los modelos siguen **sin verificarse contra fuente primaria**
  en este repositorio; lo que este ADR registra es lo que el banco midió.

### Cambiar de modelo no obliga a re-trocear el corpus

Es un requisito, y el diseño ya lo cumple:

- El troceado es **estructural y determinista** (ADR 0011) y su estimación de
  tamaño es `caracteres / 4`, deliberadamente **no un tokenizador**. Ningún
  límite del chunker depende del modelo, así que cambiar de modelo no cambia
  dónde se corta el texto.
- El vector vive en **tabla aparte**, una fila por `(chunk, modelo)`
  (ADR 0013 §1), de modo que dos modelos conviven sobre los mismos chunks.
- `embedded_sha256` detecta qué hay que re-embeber sin releer el documento
  (ADR 0013 §4), y **generar no activa** (ADR 0013 §5).

Cambiar de EmbeddingGemma a BGE-M3, o al revés, es **volver a embeber**, no
volver a trocear: los chunks, sus secciones y su procedencia no se tocan. Lo
único que cambia con la dimensión es el tipo de la columna vectorial, que es
una migración nueva (ADR 0001).

## Limitaciones de este banco

Se registran para que nadie lea las cifras con más confianza de la que
merecen:

1. **El corpus es sintético y pequeño**: 42 chunks, 2 activos. Distingue bien
   entre candidatos, pero no predice el rendimiento sobre los manuales reales
   de Tampella.
2. **Los ejes tienen 3 o 4 consultas cada uno.** Una consulta de diferencia
   mueve un eje entre 0,25 y 0,33. Las diferencias por eje son indicios, no
   mediciones finas; la puntuación principal, sobre 59 consultas, es lo sólido.
3. **`revision = "main"` en los tres**: una referencia **móvil**. Lo que se
   descargue mañana puede no ser lo que se midió. ADR 0013 §2 exige fijar el
   commit o digest antes de la primera corrida productiva.
4. **No se midió la memoria.** `peak_rss_mb` es `None` en las tres corridas: la
   lectura por `psapi` que se añadió para Windows devolvió `None`. El banco
   degradó como estaba previsto y no se rompió, pero el dato de RAM por modelo
   **no existe** y no se ha estimado aquí.
5. **Una sola corrida por modelo y una sola máquina.** Las latencias no llevan
   varianza.
6. **La abstención usa un umbral fijo de 0,35** que nadie ha calibrado. Es
   comparable entre los tres candidatos, no es un valor recomendado para
   producción.

## Cómo repetir la prueba

En una máquina con acceso a HuggingFace, desde un clon del repositorio:

```bash
uv sync --extra bench
uv run python -m elsa.tools.embedding_benchmark \
  --candidates bge-m3 --out bench/resultados/repeticion-bge-m3
uv run python -m elsa.tools.embedding_benchmark \
  --candidates qwen3-0.6b --out bench/resultados/repeticion-qwen3
uv run python -m elsa.tools.embedding_benchmark \
  --candidates embeddinggemma-300m --out bench/resultados/repeticion-gemma
```

EmbeddingGemma exige autenticación en HuggingFace y aceptar el acceso a su
repositorio gated; los otros dos no.

Para que los resultados sean comparables con los de este ADR, los informes
nuevos deben mostrar `corpus_fingerprint = 34bebb71…`,
`golden_fingerprint = 51171efc…` y `composition_template = context-v1`, y sus
líneas base deben reproducir las cifras de la tabla. Si alguna difiere, las
corridas no son comparables y la diferencia hay que explicarla antes de
comparar nada.

Los artefactos de esta medición están versionados en `bench/resultados/`, un
archivo por candidato.

## Alternativas descartadas

**Declarar EmbeddingGemma aprobado para producción.** Gana el banco, pero la
condición D1 es de licencia, no de calidad, y ninguna medición la resuelve.
Aprobarlo «provisionalmente» y construir encima sería exactamente el camino que
obliga a rehacer el trabajo si la validación no prospera.

**Elegir BGE-M3 directamente, por ser el que no tiene condición pendiente.**
Renunciaría a 15 puntos de R@1 y a la abstención correcta sin haber intentado
siquiera la validación legal. La decisión correcta es intentarla, con el
fallback listo.

**Descartar Qwen3 por licencia o tamaño.** No es necesario: lo descartan sus
propias cifras, y conviene que quede registrado por qué, para que nadie lo
reabra suponiendo que se descartó por un prejuicio.

## Ver también

- [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md) — dónde vive el vector; generar no activa
- [ADR 0014](0014-confusabilidad-no-es-autorizacion.md) — qué mide el banco y qué no
- [ADR 0011](0011-chunking-estructural-deterministico.md) — por qué cambiar de modelo no obliga a re-trocear
- [`embedding-benchmark.md`](../embedding-benchmark.md) — el banco y sus resultados
- [`embeddings-model-evaluation.md`](../embeddings-model-evaluation.md) — protocolo de medición aprobado
- [`bloque-4-2-plan.md`](../bloque-4-2-plan.md) — alcance y etapas de 4.2
