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

---

## 4. Resultados medidos

Máquina: Intel Xeon @ 2,80 GHz, 4 vCPU, 15,7 GB RAM, **sin GPU**.

### Puntuación principal (59 consultas puntuables de 67)

| Corrida | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | P@5 |
|---|---|---|---|---|---|---|---|
| `lexical-bm25` (línea base) | 0,661 | 0,658 | 0,763 | 0,822 | 0,742 | 0,709 | 0,244 |
| `lexical-trigram` (línea base) | 0,373 | 0,508 | 0,669 | 0,847 | 0,556 | 0,591 | 0,220 |
| `control-hashing-ngrams` (control) | 0,407 | 0,528 | 0,701 | 0,839 | 0,562 | 0,595 | 0,220 |

`control-hashing-ngrams` **no es un modelo**: proyecta n-gramas de
caracteres por hash, sin ninguna semántica. Es el suelo del banco y sirve
para comprobar que el arnés mide lo que dice medir.

### Los ejes donde un modelo denso tiene que ganarse el sitio

| Eje (R@5) | BM25 | Trigramas | Control |
|---|---|---|---|
| **`synonyms`** | 0,500 | 0,250 | **0,125** |
| **`cross_language`** | 0,500 | 0,375 | 0,500 |
| **`typos`** | 0,375 | 0,250 | 0,250 |
| `narrative` | 0,500 | 0,375 | 0,625 |
| `codes` *(diagnóstico)* | 1,000 | 1,000 | 1,000 |
| `safety` | 1,000 | 1,000 | 1,000 |
| `numbers_units` | 1,000 | 1,000 | 0,875 |

Lo que estos números dicen, y es el resultado útil de este bloque aunque no
se haya medido ningún modelo:

- **`synonyms` es el eje discriminante.** Es el más bajo de los tres
  recuperadores y el que mide exactamente lo que aporta un vector:
  «balinera» por «rodamiento», «torsión» por «par». Un candidato denso que
  no supere claramente 0,500 aquí no está aportando semántica.
- **`cross_language` es el segundo.** La línea léxica no puede cruzar
  idiomas por construcción; un multilingüe debería dominarlo.
- **`codes` está resuelto sin vector.** Confirma la decisión de no
  puntuarlo.
- **`narrative`: el control gana a BM25** (0,625 vs 0,500). No es ruido: las
  consultas narrativas usan palabras distintas a las del manual, y ahí un
  emparejamiento por palabras exactas pierde contra cualquier cosa que
  generalice, aunque sea por n-gramas.

### Coste

| Corrida | Corpus (s) | p50 consulta (ms) | p95 (ms) | RSS pico (MB) |
|---|---|---|---|---|
| `lexical-bm25` | 0,013 | — | — | 33,4 |
| `lexical-trigram` | 0,024 | — | — | 33,4 |
| `control-hashing-ngrams` | 0,007 | 0,05 | 0,08 | 33,4 |

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
#    (corpus bf9265a0…, dorado 51171efc…). Si difieren, el corpus o el
#    conjunto cambiaron y los resultados no son comparables con estos.
```

Requisitos de hardware esperados, **no medidos**: los tres candidatos rondan
300–600 M de parámetros, así que en CPU cabe esperar del orden de 1–3 GB de
RSS por modelo y una latencia de consulta de decenas a centenas de
milisegundos. Esa expectativa es la que la corrida real tiene que confirmar o
desmentir; no se usa como dato.

---

## 6. Qué falta para cerrar la selección

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
