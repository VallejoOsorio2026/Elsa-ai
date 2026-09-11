# Elección del modelo de embeddings — evaluación y protocolo

Documento de **planificación** del Bloque 4.2. No hay código de embeddings en
el repositorio todavía y ninguna cifra de aquí es una medición propia.

Su propósito es doble: dejar por escrito qué candidatos entran, y dejar por
escrito **cómo se decide** antes de medir, para que la elección sea auditable
y no una racionalización posterior.

> **Límite de esta investigación.** La política de egreso de la sesión en que
> se redactó bloqueó `huggingface.co`, `ai.google.dev`, `arxiv.org` y
> `supabase.com`. Las cifras provienen de búsqueda web y de las fuentes
> alcanzables (repositorios en GitHub). **Cada número marcado con ⚠ debe
> reverificarse contra la tarjeta del modelo antes de cerrar la decisión**
> (regla 21 de `CLAUDE.md`: no se afirma lo que no se ha ejecutado ni leído
> en la fuente).

---

## 1. Qué tiene que resolver el modelo en ELSA

No es un problema genérico de *embeddings*. Es este:

| Requisito | De dónde sale | Consecuencia para la elección |
|---|---|---|
| Español técnico de planta | Los ingenieros preguntan en español coloquial de taller | Multilingüe real, no inglés con español añadido |
| Manuales en otro idioma | Tampella es de origen finlandés: la documentación de origen puede estar en inglés | **Recuperación cruzada**: pregunta en español, pasaje en inglés |
| Chunks de 350–700 tokens estimados | `docs/document-chunking.md` | Ventana ≥ 1024 tokens reales, con margen para el prefijo de contexto |
| Textos cortos y largos | Una advertencia de dos líneas y una sección de dos páginas conviven | El modelo no puede degradarse en textos muy cortos |
| Códigos SAP y alfanuméricos | BOM y manuales los mencionan | **Ningún modelo denso resuelve esto** (§5). Se mide, no se supone |
| Ejecución privada | El conocimiento es interno de PAPELSA | Pesos descargables y ejecutables sin llamar a un tercero |
| Entrega a PAPELSA | `CLAUDE.md` §1 | La licencia tiene que permitir uso comercial interno sin ambigüedad |
| CPU | El piloto no tiene GPU (§6) | Huella de RAM y velocidad son criterios, no detalles |

---

## 2. Candidatos

Entran cinco. Uno queda descartado de entrada por licencia.

| Modelo | Licencia | Parámetros | Dim. | Ventana | Idiomas | Canal léxico propio |
|---|---|---|---|---|---|---|
| **BGE-M3** (`BAAI/bge-m3`) | MIT ⚠ | ~568 M ⚠ | 1024 ⚠ | 8192 ⚠ | 100+ ⚠ | **Sí**: denso + disperso + ColBERT ⚠ |
| **EmbeddingGemma-300m** | Gemma Terms of Use ⚠ | 308 M ⚠ | 768, MRL a 512/256/128 ⚠ | 2048 ⚠ | 100+ ⚠ | No |
| **Qwen3-Embedding-0.6B** | Apache-2.0 ⚠ | ~595 M ⚠ | 1024, dimensión definible ⚠ | 32 k ⚠ | 100+ ⚠ | No |
| **multilingual-e5-large** | MIT ⚠ | ~560 M ⚠ | 1024 ⚠ | **512** ⚠ | ~100 ⚠ | No |
| **gte-multilingual-base** | Apache-2.0 ⚠ | 305 M ⚠ | 768 ⚠ | 8192 ⚠ | 70+ ⚠ | No |
| ~~jina-embeddings-v3~~ | **CC BY-NC 4.0** ⚠ | 570 M | 1024 | 8192 | 89 | No |

### Por qué `jina-embeddings-v3` queda fuera antes de medir

Su licencia es CC BY-NC 4.0: **prohíbe el uso comercial** salvo acuerdo
aparte con el proveedor. ELSA se entrega a una empresa para operarlo en su
planta. Medirlo sería gastar tiempo en un candidato que no puede ganar.

### Notas que cambian la lectura de la tabla

- **`multilingual-e5-large` tiene 512 tokens de ventana.** Nuestros chunks
  llegan a 700 tokens *estimados* (`chars/4`), y el texto que se embebe lleva
  además el rastro de títulos (§4). Truncaría en silencio una parte del
  corpus. No es descalificante —se mide— pero es una desventaja estructural,
  no de calidad.
- **BGE-M3 es el único que trae canal léxico propio.** Emite, en la misma
  pasada, vector denso, pesos léxicos dispersos y multi-vector. Eso importa
  mucho en ELSA porque el eje más débil de la recuperación densa (códigos,
  nombres de componente, erratas) es justo lo que un canal léxico arregla, y
  tenerlo en el mismo modelo evita montar un segundo mecanismo en el Bloque
  4.3. Contra: es el más grande de los tres finalistas y 1024 dimensiones
  cuestan el doble de almacenamiento que 768.
- **EmbeddingGemma exige prefijos.** Consulta:
  `task: search result | query: {texto}`. Documento:
  `title: {titulo|none} | text: {texto}` ⚠. Omitirlos degrada la calidad sin
  avisar. Esto no es un defecto: es parte del contrato del modelo, y obliga a
  que el puerto distinguya consulta de documento (§4 y ADR 0013).
- **Qwen3-Embedding también es *instruction-aware*** y su propio repositorio
  recomienda instrucciones por tarea (mejora reportada del 1–5 %) ⚠.

### Las puntuaciones públicas no son comparables entre sí

- EmbeddingGemma: **61,15** en MTEB Multilingual v2, primer puesto entre los
  modelos de menos de 500 M de parámetros ⚠.
- Qwen3-Embedding-0.6B: **64,33** en MTEB multilingual, según el repositorio
  del propio modelo ⚠.
- BGE-M3 **no tiene un número equiparable**: sus resultados publicados mezclan
  denso, disperso y multi-vector, que es precisamente su propuesta.

Son tableros, revisiones y agregados distintos, medidos sobre tareas que no
son la nuestra. Leerlos como un ranking de ELSA sería un error de método.
Sirven para decidir a quién se mide, no para decidir qué se usa.

---

## 3. Criterio de decisión, fijado antes de medir

### Filtros duros (eliminan, no puntúan)

1. **Licencia** apta para operación comercial interna y entrega a PAPELSA.
   Decisión pendiente de aprobación: si el criterio es «licencia OSI
   permisiva» (MIT/Apache-2.0), EmbeddingGemma queda fuera, porque los
   *Gemma Terms of Use* no son una licencia OSI y traen política de uso
   aceptable y condiciones de redistribución propias ⚠.
2. **Cabe en el escenario de producción acordado** (§6). Un modelo que no
   puede ejecutarse donde se va a ejecutar no es candidato.
3. **Ventana real ≥ 1024 tokens** del tokenizador del propio modelo, medida
   sobre nuestro corpus, no estimada.
4. **Determinismo**: el mismo texto produce el mismo vector entre procesos y
   reinicios. Sin esto, la idempotencia de la ingesta (ADR 0011) deja de ser
   verificable.

### Orden de preferencia entre los que pasen

1. `Recall@5` en el eje **español técnico narrativo** del conjunto dorado.
2. `Recall@5` en el eje **cruce de idioma** (pregunta ES → pasaje EN).
3. Desempate por eficiencia: si un candidato queda a **≤ 2 puntos** del mejor
   con **≤ 50 %** de la RAM pico, gana el más pequeño.
4. Desempate final: el que traiga canal léxico propio, por lo que ahorra en
   el Bloque 4.3.

El eje de **códigos** se reporta pero **no** puntúa la elección: resolverlo no
es trabajo del modelo denso (§5).

---

## 4. Qué texto se embebe

El chunker guarda `heading_trail` como metadato y **no** lo antepone al
contenido, deliberadamente, para no alterar `content_sha256`. Para embeber, en
cambio, el contexto sí hace falta: un chunk que dice «Apriete a 45 Nm» sin
decir de qué conjunto es, es irrecuperable.

Propuesta: el texto que se embebe se **compone** de forma determinista y su
hash se guarda aparte del hash del contenido.

```
plantilla "context-v1":
  {título del documento} › {heading_trail unido por " › "}
  {content}
```

Sobre esa composición se aplica, si el modelo lo exige, su propio prefijo de
consulta o de documento. Consecuencias:

- El hash del texto embebido (`embedded_sha256`) cubre contenido **y**
  plantilla **y** prefijo. Cambiar la plantilla invalida exactamente los
  embeddings afectados y ninguno más.
- `content_sha256` no se toca. La comparación entre versiones del Bloque 4.1
  sigue significando lo mismo.
- El puerto tiene que distinguir consulta de documento. El puerto actual
  (`EmbeddingsPort.embed`) **no** lo hace, y con un modelo asimétrico eso
  produce peor calidad sin error visible. Es un cambio de puerto del Bloque
  4.2.

Detalle completo del esquema y del versionado: [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md).

---

## 5. Los códigos no los resuelve el vector, y eso ya estaba decidido

La evidencia pública es consistente y coincide con el diseño de ELSA: la
recuperación densa **falla sistemáticamente en identificadores exactos**.
`RTE-4471-B` y `RTE-4471-D` son casi el mismo punto del espacio vectorial, y
el modelo no tiene forma principiada de distinguirlos; devuelve el vecino más
cercano con toda la confianza del mundo.

En ELSA esto está mayormente resuelto por [ADR 0010](adr/0010-conocimiento-estructurado-vs-documental.md):
**los códigos, cantidades y relaciones viven estructurados y se consultan con
SQL exacto**, no por parecido. El Bloque 2 ya es el camino correcto para «qué
lleva la posición 40».

Queda un residuo real: un código **mencionado dentro de un manual**
(«sustituir por el retén RTE-4471-B»). Para eso hace falta un canal léxico
sobre los chunks, y ese es trabajo del Bloque 4.3 (búsqueda híbrida). El
Bloque 4.2 no lo construye; solo **no lo impide** y **lo mide**, para que
nadie cierre 4.2 creyendo que los códigos ya funcionan.

---

## 6. Escenarios de hardware

Separados a propósito entre lo que el piloto necesita y lo que la
arquitectura futura prevé.

### Requisito del piloto

| Escenario | Máquina | Qué hace | Viabilidad |
|---|---|---|---|
| **E0** | Render, plan `free`: 512 MB RAM, CPU compartida, se suspende por inactividad (`render.yaml`) | Servicio FastAPI actual | **No puede alojar ningún candidato.** 512 MB no dan para el proceso más un modelo de 300–600 M de parámetros, y el arranque en frío descargaría pesos en cada despertar |
| **E1** | Estación del ingeniero: 4–8 núcleos, 16 GB RAM, sin GPU | Ejecuta las **corridas de embedding** del corpus, por CLI, fuera del camino HTTP | Viable para los tres finalistas. Es donde se mide el rendimiento real |
| **E2** | Contenedor/VPS privado: 2 vCPU, 4 GB RAM | Servicio privado de embeddings que atiende la **consulta** (1 texto corto por pregunta) | Viable. BGE-M3 cuantizado a int8 ronda 570 MB en disco ⚠; con runtime, del orden de 1 GB de RSS |

**El punto que hay que decidir antes de implementar:** con E0 tal como está,
*no hay donde embeber la pregunta del usuario en producción*. O el piloto
suma E2 (un servicio privado detrás del puerto), o sube de plan, o la
recuperación del Bloque 4.3 arranca sin canal denso. No es un problema del
Bloque 4.2, pero **condiciona qué modelo puede elegirse**, así que se decide
aquí.

### Arquitectura futura (no requisito del piloto)

| Escenario | Máquina | Qué hace |
|---|---|---|
| **E3** | GPU de 8–16 GB | Corridas de re-embedding masivo del corpus completo en minutos; cualquier candidato, lotes de 64+ |
| **E4** | Servidor on-premise de PAPELSA: 8+ núcleos, 32 GB RAM, GPU opcional | Aloja LLM + embeddings + reranker. De los tres, **embeddings es el más barato**: es el único que puede ir en CPU sin arruinar la experiencia |

Coste de almacenamiento vectorial, para dimensionar: 1024 dimensiones en
`float4` son ~4 KB por chunk más la fila. **10 000 chunks ≈ 40 MB.** No es
una restricción en ningún escenario.

---

## 7. Protocolo del banco de pruebas

Un modelo se elige con nuestro corpus o no se elige.

### 7.1 Corpus, en dos capas

| Capa | Dónde vive | Para qué |
|---|---|---|
| **Sintética** | `bench/corpus-sintetico/` en el repositorio | Corre en CI. Documentos técnicos en español **inventados** (equipo, códigos y textos ficticios), más uno en inglés para el eje de cruce de idioma. Determinista y publicable |
| **Privada** | Fuera del repositorio, ruta por variable de ambiente | Los manuales reales de Tampella y las preguntas reales de los ingenieros. **Nunca se versiona** (regla 12). Solo su informe se cita en el cierre del bloque |

Los dos corpus se trocean con el chunker real (`structural-v1`), no con un
troceo de juguete: se mide sobre los chunks que ELSA va a tener.

### 7.2 Conjunto dorado

~60 consultas, entre 5 y 10 por eje, cada una con una o más
`structural_key` esperadas. Ejes:

| Eje | Qué comprueba | Ejemplo de consulta |
|---|---|---|
| Narrativo | Pregunta de taller completa | «¿cómo se ajusta el juego axial del conjunto de prensa?» |
| Sinónimos | Vocabulario distinto al del manual | «rodamiento» vs «balinera» vs «cojinete» |
| Nombres de componente | Nombre parcial o local | «el retén del lado motriz» |
| Códigos | Identificador exacto | «RTE-4471-B» |
| Erratas y tildes | Escritura real de un móvil | «lubricacion rodamento prensa» |
| Palabra clave | Consulta de 1–2 palabras | «torque tapa» |
| Cruce de idioma | Pregunta ES, pasaje EN | «par de apriete de la tapa» → *tightening torque* |
| Aislamiento | Que no devuelva lo de otro activo o versión | pregunta válida para el activo A, corpus con A y B |

### 7.3 Métricas

- `Recall@1`, `Recall@3`, `Recall@5`, `Recall@10`
- `MRR@10`
- `nDCG@10`
- `P@5`

Global **y desglosado por eje**. Un promedio global oculta exactamente lo que
hay que ver: un modelo excelente en narrativo y nulo en códigos.

### 7.4 Líneas base obligatorias

Sin ellas no se sabe si el vector aporta algo:

1. **Léxica**: `tsvector` de PostgreSQL con configuración española.
2. **Trigramas** (`pg_trgm`), que es la que tolera erratas.
3. Cada candidato denso.
4. **Denso + léxica fusionadas** (RRF), solo para dimensionar cuánto tiene que
   ganar el Bloque 4.3. No se implementa ahí: se estima.

Si un candidato denso pierde contra la línea léxica en un eje, eso es un
resultado, no un fallo del banco: es el dato con el que se diseña 4.3.

### 7.5 Guardarraíles: pasa o no pasa

No son puntuaciones. Un candidato que falle cualquiera de estos queda fuera,
por bueno que sea su `Recall`:

| Guardarraíl | Criterio |
|---|---|
| Fuga de alcance | **0** chunks de un alcance no autorizado en los resultados, sobre un corpus con dos activos y un usuario autorizado a uno |
| Fuga de versión | **0** chunks de versiones no publicadas |
| Determinismo | Dos corridas del mismo corpus producen vectores idénticos |
| Truncamiento | **0** chunks truncados con los límites elegidos, o el número declarado explícitamente |

### 7.6 Métricas de operación, en la misma corrida

- Chunks embebidos por segundo, en E1, declarando la máquina.
- Latencia de la consulta, `p50` y `p95`, en E1 y E2.
- RSS pico del proceso.
- Tamaño del modelo en disco.
- MB de vectores por 1000 chunks.

### 7.7 Salida

Un informe reproducible, generado por una herramienta del repositorio, con la
salida real pegada en el cierre del bloque. Dos corridas iguales producen
informes idénticos, byte a byte.

---

## 8. Fuentes

Consultadas para este documento. Las marcadas ⚠ en el texto dependen de
fuentes secundarias porque el egreso a los sitios de origen estaba bloqueado.

- [pgvector](https://github.com/pgvector/pgvector) — tipos, límites de dimensión por índice, filtrado, escaneo iterativo, parámetros HNSW
- [FlagEmbedding (BAAI)](https://github.com/FlagOpen/FlagEmbedding) — familia BGE, BGE-M3, licencia MIT, rerankers
- [Qwen3-Embedding](https://github.com/QwenLM/Qwen3-Embedding) — tamaños, dimensiones, ventana, puntuaciones MTEB declaradas
- [BAAI/bge-m3 (tarjeta del modelo)](https://huggingface.co/BAAI/bge-m3) — bloqueada en esta sesión; pendiente de verificación directa
- [google/embeddinggemma-300m (tarjeta del modelo)](https://huggingface.co/google/embeddinggemma-300m) y [modelo EmbeddingGemma](https://ai.google.dev/gemma/docs/embeddinggemma/model_card) — bloqueadas; pendientes de verificación directa
- [EmbeddingGemma: Powerful and Lightweight Text Representations](https://arxiv.org/abs/2509.20354) — bloqueada; pendiente
- [jina-embeddings-v3](https://jina.ai/models/jina-embeddings-v3/) — licencia CC BY-NC 4.0
- [Alibaba-NLP/gte-multilingual-base](https://huggingface.co/Alibaba-NLP/gte-multilingual-base) — bloqueada; pendiente
- [HNSW indexes (Supabase)](https://supabase.com/docs/guides/ai/vector-indexes/hnsw-indexes) y [Vector indexes](https://supabase.com/docs/guides/ai/vector-indexes) — bloqueadas; pendientes
- [Hybrid Search Patterns with Postgres and pgvector (Crunchy Data)](https://www.crunchydata.com/blog/hybrid-vector-search) — patrón híbrido en PostgreSQL
- [Hybrid Search in Production: Why BM25 Still Wins on the Queries That Matter](https://tianpan.co/blog/2026-04-12-hybrid-search-production-bm25-dense-embeddings) — fallo de la recuperación densa en identificadores exactos
- [pgvector Limitations (ParadeDB)](https://www.paradedb.com/learn/postgresql/pgvector-limitations) y [Tuning pgvector](https://www.paradedb.com/learn/postgresql/tuning-pgvector) — filtrado posterior al escaneo del índice
- [HNSW index bypassed when LIMIT or filter selectivity exceeds threshold](https://github.com/pgvector/pgvector/issues/721) — el problema de filtrar y buscar a la vez

---

## Ver también

- [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) — arquitectura vectorial propuesta
- [`bloque-4-2-plan.md`](bloque-4-2-plan.md) — alcance, exclusiones y criterios de aceptación del bloque
- [ADR 0010](adr/0010-conocimiento-estructurado-vs-documental.md) — por qué los códigos no se embeben
- [ADR 0011](adr/0011-chunking-estructural-deterministico.md) — qué se embebe, y por qué es determinista
- [`document-chunking.md`](document-chunking.md) — límites de tamaño del chunk
