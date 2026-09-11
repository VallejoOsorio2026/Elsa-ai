# Banco de pruebas del modelo de embeddings (Bloque 4.2.a)

Cómo se mide, qué se midió, **qué no se pudo medir y por qué**, y qué hace
falta para cerrar la selección.

> **La selección NO está cerrada.** De los tres candidatos obligatorios,
> **ninguno se pudo ejecutar** en el entorno donde se construyó este banco.
> No hay ganador provisional, y no se propone uno: elegir con puntuaciones
> públicas sería exactamente lo que el protocolo prohíbe.

Implementación: `src/elsa/bench/`. Herramienta:
`elsa.tools.embedding_benchmark`. Protocolo aprobado:
[`embeddings-model-evaluation.md`](embeddings-model-evaluation.md) §7.

---

## 1. Cómo se ejecuta

Sin red, sin GPU y sin descargar nada — así corre en CI:

```bash
uv run python -m elsa.tools.embedding_benchmark --out bench/resultados
```

Con los candidatos reales, en un entorno con acceso a `huggingface.co`:

```bash
uv pip install "sentence-transformers>=3.0"
uv run python -m elsa.tools.embedding_benchmark \
    --candidates bge-m3,qwen3-0.6b,embeddinggemma-300m \
    --device cpu \
    --out bench/resultados
```

`sentence-transformers` **no** es dependencia del proyecto: pesa cientos de
megas y el runtime de ELSA no la necesita. Un candidato que no se pueda
cargar queda registrado como **sin medir**, con el motivo.

---

## 2. Qué se mide

### Corpus

Cuatro documentos sintéticos en `bench/corpus-sintetico/`, troceados con el
chunker real (`structural-v1`), no con un troceo de juguete: **42 chunks**.

| Documento | Activo | Versión | Publicada | Idioma |
|---|---|---|---|---|
| `prensa-manual` | `prensa-ejemplo` | 1 | Sí | es |
| `prensa-manual` | `prensa-ejemplo` | 2 | **No** | es |
| `prensa-nota-en` | `prensa-ejemplo` | 1 | Sí | en |
| `bomba-manual` | `bomba-ejemplo` | 1 | Sí | es |

El equipo, los códigos (`PRX-…`, `BOX-…`) y las cifras son **inventados**.
La bomba comparte vocabulario con la prensa a propósito: sin dos activos que
hablen parecido no se puede medir confusabilidad.

### Conjunto dorado

**67 consultas** en 19 ejes, 3–4 por eje, en `bench/golden/queries.json`.
Cada una lleva id, texto, eje, chunks esperados con relevancia graduada
(2 responde, 1 parcial), chunks que serían un error, **motivo escrito**, si
se resuelve por semántica/léxico/mixto, y dificultad.

El motivo escrito no es decoración: un conjunto dorado hecho a mano solo se
controla discutiéndolo, y una expectativa sin motivo no se puede discutir.

Se valida contra el corpus al cargarlo. Una expectativa que apunta a un
chunk inexistente **falla ruidosamente** en vez de puntuar cero en silencio
y hacer parecer malo a un modelo que acertó.

### Métricas

`Recall@1/3/5/10`, `MRR@10`, `nDCG@10` (relevancia graduada) y `P@5`,
globales **y desglosadas por eje**. Un promedio global oculta justo lo que
hay que ver.

---

## 3. Tres decisiones que cambian cómo se leen los números

### Los códigos no deciden el ganador denso

El eje `codes` se mide, se reporta y **se excluye de la puntuación
principal**. Los identificadores exactos los resolverá el canal léxico o
estructurado del Bloque 4.3, no el vector. Dejar que decidan sería elegir
por el eje equivocado. En la medición, las tres líneas base los aciertan al
100 %, que es precisamente la razón.

### El aislamiento no es una propiedad del modelo

`embeddings-model-evaluation.md` §7.5 llama «fuga de alcance» y «fuga de
versión» a dos guardarraíles del modelo. **No lo son**, y conviene
corregirlo antes de que alguien lea un número y crea que el modelo protege
algo:

- El aislamiento entre activos y entre versiones lo impone el filtro de la
  consulta (`WHERE` por dominio, activo autorizado y versión publicada).
  Ningún índice puede devolver una fila que el filtro excluye — es lo que
  ya razona [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md).
- Lo que sí se puede medir es **confusabilidad**: si el ranking denso
  confunde dos activos que hablan parecido, o dos versiones del mismo
  documento. Eso es una señal sobre el modelo, no sobre los permisos.

Por eso los ejes `asset_confusion`, `version_confusion` y
`near_miss_document` se reportan como `confusion@5`, y el informe repite
dónde acaba la responsabilidad del modelo cada vez que muestra el número.
El banco **no aplica** el filtro de alcance a propósito: si lo aplicara, la
confusión sería inmedible.

### La abstención solo compara escalas iguales

`confusion@5` y la calidad son comparables entre cualquier par de corridas.
La **abstención** no: se mide con un umbral fijo (0,35) sobre la puntuación
del primer resultado, y el coseno sobre vectores normalizados está acotado a
[-1, 1] mientras BM25 no lo está. Entre los tres candidatos densos el número
es comparable; contra la línea léxica no lo es. El informe lo advierte donde
aparece.

### Se embebe el texto compuesto, no el chunk en crudo

El texto que va al modelo lleva delante su contexto, con la plantilla
versionada `context-v1` (`src/elsa/documents/composition.py`):

```
<título del documento> › <rastro de títulos> › <contenido>
```

No es un adorno. «El par de apriete es de 45 N·m» es casi idéntico en el
manual de la prensa y en el de la bomba, y sin contexto los dos vectores
quedarían prácticamente en el mismo sitio. Y sobre todo: **producción va a
embeber el texto compuesto**, así que un banco que midiera el contenido en
crudo elegiría el modelo con una entrada que nunca se va a usar. Es el error
más caro posible aquí, porque no falla — mide otra cosa.

La plantilla se identifica y el texto compuesto se hashea
(`embedded_sha256`), de modo que cambiarla se sabe que invalida los vectores
sin tener que releer el documento. `context-v1` entra en la identidad de cada
corrida: dos corridas con plantillas distintas no son comparables y las
huellas lo dicen.

**Asimetría deliberada con las líneas base.** Los recuperadores léxicos
buscan sobre el contenido en crudo; el denso, sobre el texto compuesto. Es lo
que reproduce la arquitectura prevista —`tsvector` sobre el contenido, vector
sobre la composición— pero conviene saberlo al leer la tabla. Si el canal
léxico del Bloque 4.3 acaba indexando también los títulos, esta comparación
habrá que repetirla.

---

## 4. Resultados medidos

Máquina: Intel Xeon @ 2,80 GHz, 4 vCPU, 15,7 GB RAM, **sin GPU**.

### Puntuación principal (59 consultas puntuables de 67)

| Corrida | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | P@5 |
|---|---|---|---|---|---|---|---|
| `lexical-bm25` (línea base) | 0,661 | 0,658 | 0,763 | 0,822 | 0,742 | 0,709 | 0,244 |
| `lexical-trigram` (línea base) | 0,373 | 0,508 | 0,669 | 0,847 | 0,556 | 0,591 | 0,220 |
| `control-hashing-ngrams` (control) | 0,458 | 0,667 | 0,774 | 0,873 | 0,630 | 0,653 | 0,251 |

`control-hashing-ngrams` **no es un modelo**: proyecta n-gramas de
caracteres por hash, sin ninguna semántica. Es el suelo del banco y sirve
para comprobar que el arnés mide lo que dice medir.

### Los ejes donde un modelo denso tiene que ganarse el sitio

| Eje (R@5) | BM25 | Trigramas | Control |
|---|---|---|---|
| **`synonyms`** | 0,500 | 0,250 | **0,250** |
| **`cross_language`** | 0,500 | 0,375 | 0,500 |
| `section_reference` | 0,667 | 0,667 | 0,667 |
| `preventive` | 0,667 | 0,667 | 1,000 |
| `narrative` | 0,500 | 0,375 | 0,875 |
| `typos` | 0,375 | 0,250 | 0,750 |
| `numbers_units` | 1,000 | 1,000 | 0,625 |
| `safety` | 1,000 | 1,000 | 0,667 |
| `codes` *(diagnóstico)* | 1,000 | 1,000 | 1,000 |

Lo que estos números dicen, y es el resultado útil de este bloque aunque no
se haya medido ningún modelo:

- **`synonyms` es el eje discriminante.** Es el más bajo de los tres
  recuperadores —0,500 el mejor— y mide exactamente lo que aporta un vector:
  «balinera» por «rodamiento», «torsión» por «par». Un candidato denso que no
  supere claramente 0,500 aquí no está aportando semántica, y es el único eje
  que la composición del contexto **no** mejoró.
- **`cross_language` es el segundo.** La línea léxica no puede cruzar
  idiomas por construcción; un multilingüe debería dominarlo.
- **`codes` está resuelto sin vector**, al 100 % por las tres. Confirma la
  decisión de no puntuarlo.
- **Componer el contexto cambia mucho más de lo esperado.** Con el chunk en
  crudo el control sacaba 0,701 de R@5 global; con `context-v1`, 0,774. Por
  eje el salto es grande donde el título de la sección coincide con la
  consulta —`narrative` de 0,625 a 0,875, `typos` de 0,250 a 0,750— y hay
  **retrocesos** donde el contexto añade palabras que compiten con el dato:
  `numbers_units` bajó de 0,875 a 0,625 y `safety` de 1,000 a 0,667.
  Es una advertencia concreta para 4.2.b: la plantilla de composición no es
  neutra y merece medirse como una variable más, no fijarse por intuición.
- **`narrative`: el control gana a BM25** (0,875 vs 0,500). Las consultas
  narrativas usan palabras distintas a las del manual, y ahí un
  emparejamiento por palabras exactas pierde contra cualquier cosa que
  generalice, aunque sea por n-gramas.

### Coste### Coste

| Corrida | Corpus (s) | p50 consulta (ms) | p95 (ms) | RSS pico (MB) | MB/1000 chunks |
|---|---|---|---|---|---|
| `lexical-bm25` | 0,013 | — | — | 34,6 | — |
| `lexical-trigram` | 0,026 | — | — | 34,6 | — |
| `control-hashing-ngrams` | 0,011 | 0,05 | 0,08 | 34,6 | 0,98 |

`MB/1000 chunks` se calcula de la dimensión (`float32`), no se mide: entre
768 y 1024 dimensiones hay un 33 % de diferencia en lo que va a pesar el
índice, y conviene verlo al comparar. 1024 dim → 3,91 MB por 1000 chunks.

Son las líneas base: irrelevantes como referencia de coste de un modelo
real. Están para que la columna exista y se llene en la corrida de verdad.

---

## 5. Lo que NO se pudo medir, y por qué

**Los tres candidatos obligatorios quedaron sin medir.**

| Candidato | Licencia | Estado |
|---|---|---|
| `BAAI/bge-m3` | MIT | **Sin medir** |
| `Qwen/Qwen3-Embedding-0.6B` | Apache-2.0 | **Sin medir** |
| `google/embeddinggemma-300m` | Gemma Terms of Use | **Sin medir** |

Causa, comprobada y no supuesta: la política de egreso de este entorno
**bloquea `huggingface.co`**. El gateway responde `403` al `CONNECT` para
`huggingface.co`, `hf.co` y `cdn-lfs.huggingface.co`, de modo que no se
pueden descargar los pesos ni leer las tarjetas de modelo. `pypi.org` sí es
accesible.

Consecuencias que hay que aceptar tal cual:

1. **No hay ganador provisional ni segunda opción.** Un candidato sin medir
   no se descarta ni se elige.
2. **Los datos de los modelos siguen sin verificar.** Dimensión, ventana de
   contexto, revisión recomendada y —sobre todo— **los prefijos** vienen de
   la investigación de `embeddings-model-evaluation.md`, marcada allí como
   no verificada contra fuente primaria por el mismo bloqueo. Están
   centralizados en `CANDIDATES`
   (`src/elsa/bench/adapters/sentence_transformers.py`) para que sea **un
   solo sitio** que corregir. Reverificarlos contra la tarjeta del modelo es
   el primer paso de cualquier corrida real.
3. **Las puntuaciones públicas no sustituyen la medición.** Un número de
   MTEB y un `Recall@5` sobre este corpus no son comparables.

### Procedimiento para completarlo en un entorno habilitado

```bash
# 1. Reverificar contra la tarjeta de cada modelo y corregir CANDIDATES
#    si algo no coincide: nombre exacto, revisión, dimensión, ventana,
#    prefijo de documento y prefijo de consulta.
#    -> src/elsa/bench/adapters/sentence_transformers.py

# 2. Instalar la dependencia opcional del banco.
uv pip install "sentence-transformers>=3.0"

# 3. Correr los tres con el mismo conjunto dorado y las mismas reglas.
uv run python -m elsa.tools.embedding_benchmark \
    --candidates bge-m3,qwen3-0.6b,embeddinggemma-300m \
    --device cpu --out bench/resultados

# 4. Comprobar en el informe que las tres huellas coinciden con esta corrida
#    (corpus 34bebb71…, dorado 51171efc…, plantilla context-v1). Si difieren, el corpus o el
#    conjunto cambiaron y los resultados no son comparables con estos.
```

Requisitos de hardware esperados, **no medidos**: los tres candidatos rondan
300–600 M de parámetros, así que en CPU cabe esperar del orden de 1–3 GB de
RSS por modelo y una latencia de consulta de decenas a centenas de
milisegundos. Esa expectativa es la que la corrida real tiene que confirmar o
desmentir; no se usa como dato.

---

## 6. Ítems del alcance de 4.2.a que NO se entregaron

`docs/bloque-4-2-plan.md` §2 es una **lista cerrada de 11 ítems**. Este
bloque entregó 5, 6, 7 y parte del 9. Lo que falta, y por qué:

| Ítem | Qué pedía | Estado |
|---|---|---|
| §2.1 | `EmbeddingsPort` corregido: documento/consulta + identidad del modelo | **No entregado.** Es el puerto **productivo**, y la instrucción de esta sesión fue explícita: «NO integrar todavía embeddings al flujo productivo de ELSA». Requiere decisión |
| §2.2 | Composición `context-v1` + `embedded_sha256` | **Entregado** (`src/elsa/documents/composition.py`), función pura y con tests |
| §2.3 | `FakeEmbeddingsAdapter` a 768/1024 | **No entregado.** Toca un adaptador del runtime |
| §2.4 | Adaptador real por candidato en `src/elsa/adapters/`, elegido por configuración | **No entregado.** Misma razón que §2.1. El adaptador medible vive en `src/elsa/bench/adapters/`, fuera del camino productivo. El **grupo opcional** de dependencias sí se declaró |
| §2.8 | Guardarraíles como tests | **Reinterpretado.** Ver §3: el aislamiento lo impone el filtro de la consulta, no el modelo. Los tests de que una versión no publicada no se recupera ya existen en 4.1 (`list_published_chunks`); aquí se mide confusabilidad |
| §2.9 | ADR 0014 con el modelo elegido | **Imposible todavía:** no hay medición |
| §2.10 | Confirmación de D4, D6, D7 y D11 | **Pendiente.** D6 queda parcialmente respondida —`context-v1` existe— pero sin medir no se confirma nada |
| §2.11 | `embeddings-model-evaluation.md` con cifras verificadas y `environment-variables.md` | **No entregado:** las tarjetas de modelo no son accesibles, y no hay configuración nueva porque no hay integración productiva |

Entregar parcialmente es legítimo; no declararlo no lo sería (reglas 19-21).
**El corte de §2.1, §2.3 y §2.4 necesita autorización explícita**: chocan con
la instrucción de no integrar embeddings al flujo productivo, y la regla 20
no permite estrechar un alcance cerrado por cuenta propia.

---

## 7. Qué falta para cerrar la selección

1. **Medir los tres** en un entorno con acceso a HuggingFace.
2. **Reverificar** las tarjetas de modelo antes de medir.
3. **Resolver la decisión D1**: los *Gemma Terms of Use* no son una licencia
   OSI. EmbeddingGemma está aprobado para el banco y **no es elegible para
   producción** hasta que se valide formalmente su uso corporativo. Medir no
   habilita: si resultara el mejor, se reporta y se elige el mejor de los
   elegibles.
4. **Aprobación explícita** de la elección. Este banco produce evidencia; la
   decisión no la toma la herramienta.

Lo que este bloque deliberadamente **no** hace: no persiste vectores, no
toca pgvector, no añade migraciones, no recupera nada en producción y no
integra los embeddings al flujo real de ELSA. `src/elsa/bench/` no lo
importa ningún módulo del runtime, y una prueba lo comprueba.

---

## Ver también

- [`embeddings-model-evaluation.md`](embeddings-model-evaluation.md) — candidatos y criterio de decisión, fijado antes de medir
- [`bloque-4-2-plan.md`](bloque-4-2-plan.md) — plan del Bloque 4.2
- [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) — dónde vive el vector y por qué el índice no decide permisos
- [`document-chunking.md`](document-chunking.md) — el chunker con el que se trocea el corpus
