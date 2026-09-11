# ADR 0013 — El vector vive aparte del chunk, y generar no activa

- Estado: **propuesto** (pendiente de aprobación; no implementado)
- Bloque: 4.2

## Contexto

El modelo documental del Bloque 4.1 deja el chunk listo para ser recuperado y
deliberadamente sin vector: la dimensión depende del modelo de embeddings, y
declararla antes de elegirlo obligaría a migrar la tabla al elegirlo
(`20260908010000_create_documental_knowledge_model.sql`, nota de cabecera).

Al llegar el Bloque 4.2 hay que decidir cinco cosas que no son independientes:

1. **Dónde vive el vector.** Columna en `document_chunks` o tabla aparte.
2. **Cómo se sabe con qué se generó.** Un vector sin modelo, revisión y
   parámetros no es dato: es un número sin significado.
3. **Cómo se re-embebe al cambiar de modelo sin quedarse sin índice** durante
   la transición y sin perder la posibilidad de volver atrás.
4. **Cómo se mantiene la regla 3 de `CLAUDE.md`** —los permisos se aplican
   antes de recuperar— cuando la recuperación pasa a ser una búsqueda por
   vecino más cercano.
5. **Cómo se sabe que un vector está obsoleto** sin volver a leer el
   documento entero.

La cuarta no es teórica. Con un índice aproximado (HNSW, IVFFlat), PostgreSQL
**escanea el índice primero y aplica el `WHERE` después**: una consulta con
`LIMIT 10` y un filtro selectivo puede devolver menos de 10 filas, o ninguna,
sin error. Si el filtro es «el alcance que esta persona puede leer», un índice
mal entendido convierte un control de autorización en una lotería de
recuperación. Sería el peor fallo posible de este bloque: silencioso, y del
lado equivocado.

## Decisión

### 1. El vector vive en tabla aparte, no en `document_chunks`

`elsa.document_chunk_embeddings`, una fila por `(chunk, modelo)`.

Razones, en orden de peso:

- **Un chunk puede tener varios vectores a la vez.** Durante un cambio de
  modelo, el corpus tiene que estar embebido con el modelo viejo y el nuevo
  simultáneamente. Con una columna, eso es imposible sin duplicar filas de
  contenido, y duplicar contenido rompe `uq (version_id, structural_key)`.
- **`document_chunks` es historia, no estado.** Sus filas se escriben una vez
  al ingerir y no se vuelven a tocar. Un vector se regenera; ponerlo en la
  misma fila convierte una tabla inmutable en una tabla que se actualiza, y
  cada corrida de embedding reescribiría filas de procedencia.
- **La dimensión es parte del tipo de la columna.** Una columna
  `vector(N)` en `document_chunks` ataría el modelo al esquema del Bloque 4.1.
- Es el mismo criterio que ya se aplicó a `document_chunk_provenance`: lo que
  cambia por su cuenta no se denormaliza dentro del chunk.

La clave primaria es `(chunk_id, model_id)`. Se lleva también `version_id`
con **clave foránea compuesta** contra `(document_chunks.id, version_id)`,
igual que `fk_chunk_section_same_version`: así la base impide que un embedding
diga pertenecer a una versión distinta que su chunk. La procedencia no puede
mentir aunque el código tuviera un fallo.

### 2. El modelo es un registro, no una cadena de texto suelta

`elsa.embedding_models`: proveedor, nombre, revisión o digest de los pesos,
dimensión, si los vectores salen normalizados, métrica de similitud,
tokenizador, ventana máxima, plantilla del texto embebido, prefijo de consulta
y prefijo de documento.

Las filas son **inmutables**: cambiar cualquiera de esos valores es otro
espacio vectorial, y por tanto otra fila, no una actualización. Un `UPDATE`
sobre esta tabla convertiría en mentira todos los vectores ya generados.

Registrar los prefijos aquí y no en el código es lo que hace comparable una
corrida con otra: dos modelos con la misma plantilla son comparables, con
plantillas distintas no lo son, y eso tiene que poder leerse en la base.

### 3. La corrida de embedding es una tabla, como la de ingesta

`elsa.embedding_runs`: modelo, quién la lanzó, cuándo empezó y acabó, cuántos
chunks, cómo terminó y por qué falló si falló. Mismo criterio que
`document_ingestion_runs` (ADR 0012): una ejecución que no deja rastro no se
puede auditar ni reanudar.

### 4. Un embedding se sabe obsoleto por el hash del texto embebido

Cada fila guarda `embedded_sha256`: el hash del texto **exacto** que se envió
al modelo, ya compuesto con el rastro de títulos y con el prefijo que el
modelo exija.

No es `content_sha256`, y la diferencia es el mecanismo entero:

> Un embedding está obsoleto si y solo si su `model_id` no es el activo, **o**
> su `embedded_sha256` no coincide con el hash del texto que hoy se compondría
> para su chunk.

Una sola comparación cubre los tres casos que importan: cambió el chunk,
cambió la plantilla de composición, cambió el modelo. No hay un cuarto caso
que se escape, y no hace falta releer el documento para saberlo.

`content_sha256` se conserva en la fila además del anterior, para poder
reconocer entre versiones un chunk cuyo contenido no cambió.

### 5. Generar no activa

El paralelo exacto de la regla 16 de `CLAUDE.md` —cargar no publica, aprobar
no publica— aplicado a los embeddings:

1. Se registra el modelo nuevo. Queda inactivo.
2. Se corre el embedding del corpus. Los vectores nuevos **conviven** con los
   del modelo activo; nada se borra.
3. Se mide con el banco de pruebas, leyendo explícitamente por el modelo
   nuevo.
4. **Activar es una operación aparte y atómica**: una sola transacción cambia
   qué modelo es el activo. Un índice parcial único garantiza que hay a lo
   sumo uno, igual que `uq_published_document_version` garantiza una sola
   versión publicada.
5. Retirar el modelo viejo es una decisión posterior y explícita, no un efecto
   de activar el nuevo.

En ningún momento de la secuencia el sistema se queda sin vectores, y volver
atrás es cambiar el activo otra vez, no regenerar nada.

### 6. En el piloto no hay índice aproximado, y es una decisión

La recuperación filtra **primero** por alcance autorizado y por versión
publicada, y ordena por distancia **después**, sobre el conjunto ya filtrado:
búsqueda exacta, recall 100 %, sin índice ANN.

Por qué es la elección correcta ahora y no una carencia:

- **Correcta por construcción.** El filtro de autorización es un `WHERE` que
  se evalúa antes del orden, no un post-filtro sobre lo que un índice quiso
  devolver. La regla 3 de `CLAUDE.md` deja de depender de la calidad de un
  índice.
- **El tamaño lo permite con holgura.** El piloto es un activo y unos pocos
  manuales: del orden de 10³–10⁴ chunks. Un recorrido exacto sobre eso es
  cuestión de milisegundos, y la documentación de pgvector recomienda
  explícitamente no indexar cuando la tabla es pequeña.
- **Un índice se añade cuando el volumen lo exija**, en su propia migración,
  midiendo el recall **con el filtro puesto** y con `hnsw.iterative_scan` en
  `strict_order`. Lo que nunca se hará es que la corrección de la
  autorización dependa del índice.

Los vectores se guardan **normalizados** y la similitud se mide con distancia
coseno. Con vectores normalizados el orden es el mismo que con producto
interno, y coseno se lee sin tener que recordar que están normalizados.

### 7. Qué se embebe y qué no

**Se embebe** el chunk de una versión documental, con su contexto compuesto.

**No se embebe**, y ninguno es un olvido:

| Qué | Por qué |
|---|---|
| BOM, SAP, AMEF, códigos, cantidades, relaciones | ADR 0010: se consultan exactos. Trocearlos destruiría la única forma fiable de consultarlos |
| Los bytes del archivo original | Viven en el almacenamiento privado; la base guarda su hash |
| Un aporte pendiente | Regla 16: un aporte no es conocimiento |
| Una transcripción simulada | No se ha oído nada; embeberla sería fabricar evidencia |

Las versiones no publicadas **sí** pueden tener embeddings: la garantía de que
no se recuperan la da el filtro por `state = 'published'` en la consulta, no
la ausencia de vectores. Al contrario: exigir que solo lo publicado esté
embebido obligaría a que publicar esperase a una corrida de CPU, y publicar
tiene que ser atómico e inmediato (ADR 0012).

## Consecuencias

- La dimensión del espacio vectorial queda fijada por la migración de este
  bloque. Cambiar de modelo a otra dimensión es una migración nueva, con su
  tabla o columna nueva, y eso es correcto: en ELSA todo cambio de esquema es
  una migración versionada (ADR 0001).
- Hay que actualizar el `comment on table elsa.document_chunks`, que hoy dice
  «los embeddings llegan en el Bloque 4.2» y podría leerse como que llegan
  *ahí dentro*.
- `EmbeddingsPort` tiene que distinguir consulta de documento y declarar
  identidad del modelo. El puerto actual solo tiene `embed` y `dimension`, y
  con un modelo asimétrico eso produce peor calidad sin error visible.
- La extensión `vector` tiene que existir donde corran las migraciones. El CI
  usa hoy `postgres:16`, que no la trae: la migración de este bloque exige
  cambiar la imagen. Un test que se omita porque falta la extensión sería
  peor que un test que falle.
- El vector de la consulta se calcula en cada pregunta. En el piloto no hay
  dónde hacerlo (`render.yaml` usa el plan `free`, 512 MB): el puerto permite
  que el adaptador sea un servicio privado, pero **dónde vive ese servicio es
  una decisión abierta** que condiciona la elección del modelo.

## Alternativas descartadas

**Una columna `embedding vector(N)` en `document_chunks`.** Es lo más simple
mientras hay un solo modelo y se rompe el día que hay dos. Convertiría además
una tabla de procedencia inmutable en una tabla que se reescribe en cada
corrida.

**Almacén vectorial aparte (Qdrant, Milvus, pgvector en otra base).** Añade un
servicio, un backup y una frontera de consistencia nuevos, y sobre todo pone
los vectores fuera del alcance del `WHERE` que aplica los permisos: el filtro
de autorización pasaría a hacerse en el cliente, después de recuperar. Es
exactamente lo que la regla 3 prohíbe. PostgreSQL con pgvector mantiene el
alcance y la similitud en la misma consulta.

**Una tabla de vectores direccionada por contenido** (clave
`(modelo, hash del texto)`), con una tabla puente hacia el chunk. Deduplica
gratis los chunks que no cambian entre versiones, y a cambio aleja el vector
del alcance: el índice quedaría en una tabla sin dominio ni activo, que es
justo lo que no conviene. La deduplicación se consigue igual, sin segunda
tabla, resolviendo por `(model_id, embedded_sha256)` antes de llamar al
modelo.

**Denormalizar dominio, activo y estado de publicación en la tabla de
embeddings** para poder indexar con filtro. Crearía dos fuentes de verdad
para un dato que cambia —publicar cambia el estado de todos los chunks de una
versión— y tarde o temprano una mentiría. Es el mismo argumento con el que el
Bloque 4.1 dejó `document_chunk_provenance` como vista.

## Ver también

- [`embeddings-model-evaluation.md`](../embeddings-model-evaluation.md) — candidatos y protocolo de medición
- [`bloque-4-2-plan.md`](../bloque-4-2-plan.md) — alcance y criterios de aceptación
- [ADR 0001](0001-supabase-cli-unica-autoridad-del-esquema.md) — el esquema solo cambia por migración
- [ADR 0002](0002-identidad-de-materiales-autorizacion-en-backend.md) — la autorización la aplica FastAPI
- [ADR 0010](0010-conocimiento-estructurado-vs-documental.md) — qué no se embebe
- [ADR 0011](0011-chunking-estructural-deterministico.md) — el chunk que se embebe
- [ADR 0012](0012-ciclo-de-vida-documental-propio.md) — las corridas y el historial como tablas propias
