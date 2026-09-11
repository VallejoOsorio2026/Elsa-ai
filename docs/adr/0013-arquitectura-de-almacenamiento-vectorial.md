# ADR 0013 — El vector vive aparte del chunk, y generar no activa

- Estado: **aceptado** (no implementado todavía)
- Bloque: 4.2
- Lo respaldan las decisiones **D2**, **D3** y **D5** del proyecto, registradas
  en [`bloque-4-2-plan.md`](../bloque-4-2-plan.md) §4
- Queda un detalle sin aprobación formal, y no bloquea: **D4** —búsqueda exacta
  frente a índice HNSW en el piloto (§6)— se confirma al implementar 4.2.b

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
   vecino más cercano, y cómo se evita que la elección de índice degrade la
   calidad de lo que sí está autorizado.
5. **Cómo se sabe que un vector está obsoleto** sin volver a leer el
   documento entero.

La cuarta tiene dos caras, y conviene no confundirlas.

**La autorización no depende del índice.** La consulta de recuperación filtra
siempre por dominio, activo autorizado, versión publicada y chunks permitidos.
Esos filtros son cláusulas obligatorias del `WHERE`, y un índice —exista o no,
sea exacto o aproximado— no puede devolver una fila que el filtro excluye.
**Ningún índice se salta un permiso.** La regla 3 la sostiene el filtro, y el
puerto ya la hace inevitable: `list_published_chunks` exige los alcances
autorizados como argumento obligatorio.

**Lo que un índice aproximado sí puede degradar es la calidad.** Con HNSW o
IVFFlat, PostgreSQL recorre el índice y el filtro se aplica sobre lo que ese
recorrido trajo. Con filtros selectivos —y los de ELSA lo son, porque acotan a
un activo y a una versión publicada— una consulta con `LIMIT 10` puede acabar
con menos de 10 candidatos útiles: no porque se recupere algo indebido, sino
porque casi todos los vecinos que el índice visitó pertenecían a lo que el
filtro excluye. El fallo es de **recall**, no de autorización: se entrega de
menos, nunca de más. Y es silencioso, que es justo lo que lo hace caro: una
respuesta pobre se parece bastante a una respuesta.

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

### 6. Los filtros son obligatorios siempre; en el piloto, además, la búsqueda es exacta

**Los filtros no son optativos ni dependen del índice.** Toda recuperación
vectorial pasa por la misma cadena, en la misma consulta que calcula la
similitud:

```
dominio → activo autorizado → versión publicada → chunks permitidos
```

Esto no cambia en ningún escenario, con índice o sin él. Es la regla 3 de
`CLAUDE.md`, y el puerto ya la hace inevitable en vez de encomendarla a la
memoria de quien escriba la consulta.

**En el piloto, además, la búsqueda vectorial es exacta**: se ordena por
distancia sobre el conjunto ya filtrado, sin índice ANN. Por qué es la
elección correcta ahora y no una carencia:

- **El tamaño lo permite con holgura.** El piloto es un activo y unos pocos
  manuales: del orden de 10³–10⁴ chunks. Un recorrido exacto sobre eso es
  cuestión de milisegundos, y la documentación de pgvector recomienda
  explícitamente no indexar cuando la tabla es pequeña.
- **Recall 100 % sobre lo autorizado.** Con búsqueda exacta, los `k` mejores
  candidatos del conjunto autorizado son exactamente los `k` que se entregan.
  No hay una variable de recall que ajustar mientras se estrena todo lo demás.
- **Da la verdad de referencia.** Cuando llegue el momento de indexar, la
  búsqueda exacta es contra qué se compara el índice. Sin ella no habría con
  qué medir la pérdida.

**Un índice HNSW se añade cuando el volumen lo justifique**, en su propia
migración y con tres condiciones: medir el recall con los **filtros reales**
puestos (no con filtros de juguete), comparar contra la búsqueda exacta como
verdad de referencia, y usar `hnsw.iterative_scan = strict_order` para que el
recorrido siga buscando cuando el filtro descarta lo que trajo. Lo que se mide
al indexar es **cuántos candidatos útiles sobreviven al filtro**, no si el
filtro se aplica: eso último no está en discusión.

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

#### Generar un embedding y poder recuperarlo son dos cosas distintas

La política aprobada (decisión D5) separa las dos, porque confundirlas lleva a
un diseño peor en las dos direcciones posibles:

| Estado de la versión | ¿Se generan embeddings? | ¿Elegible en recuperación productiva? |
|---|---|---|
| `pending_validation` | **No**, normalmente no | No |
| `rejected` | **No** | No |
| `approved` | **Sí, permitido** antes de publicar, para poder validar el índice nuevo | **No** |
| `published` | Sí | **Sí**, y solo esta |
| `superseded` | No se generan nuevos | No, pero **se conservan** mientras sirvan para rollback o comparación |

Por qué se permite embeber una versión `approved` antes de publicarla: publicar
tiene que ser **atómico e inmediato** (ADR 0012), y si publicar tuviera que
esperar a una corrida de CPU dejaría de serlo. Embeber antes es lo que permite
además **validar el índice nuevo** antes de que nadie dependa de él.

Por qué eso no abre una fuga: **la elegibilidad no la da la existencia del
vector, la da la versión**. La consulta exige `state = 'published'` en el mismo
`where` que el alcance, así que un vector de una versión `approved` existe y no
se recupera.

Y por eso **publicar cambia atómicamente qué embeddings son elegibles**, sin
tocar una sola fila de embeddings: la elegibilidad se deriva por `join` de la
versión, y publicar está protegido por `uq_published_document_version`. Si el
estado de publicación se copiara dentro de la fila del embedding, publicar
tendría que reescribir una fila por chunk y **dejaría de ser atómico**. Es el
mismo argumento de §1, visto desde el otro lado.

### 8. El motor de embeddings es un servicio reemplazable, y su ubicación queda diferida

Decisión D2. Dos partes, y conviene no confundirlas: una está aprobada y la
otra deliberadamente no.

**Aprobado, y es una prohibición:** no se ejecutan modelos de embeddings dentro
del servicio web de ELSA en el plan actual de Render (512 MB, CPU compartida,
suspensión por inactividad). No caben, y competir por la CPU con las requests
degradaría lo único que hoy funciona.

**Aprobado:** FastAPI queda desacoplado del motor por puerto y adaptador. Es el
ADR 0003 aplicado a esta dependencia. El adaptador puede ser un proceso local,
un servicio privado por HTTP o un servidor dedicado: el negocio no lo sabe.

**Diferida:** dónde vive ese servicio en el piloto. No se decide por anticipado
porque depende de cuatro datos que todavía no existen: el modelo ganador, su
consumo real de RAM/CPU/GPU, su latencia medida y las restricciones de
infraestructura de PAPELSA. Decidirlo antes sería construir por anticipación
(regla 23) sobre supuestos que la medición puede desmentir.

**El requisito que esto impone al diseño, y que es verificable:** cambiar entre
servicio local u on-premise, servidor dedicado u otro proveedor autorizado no
puede exigir modificar **ni la lógica de recuperación ni el esquema
documental**. Si un cambio de ubicación obligara a tocar `core/` o una
migración, el diseño está mal y se corrige antes de seguir. No es una
aspiración: es una prueba que se puede hacer.

Consecuencia para 4.2.a: los candidatos se miden en un **entorno de banco
independiente**, fuera del servicio web y fuera del camino de la request. Eso
está permitido y es lo previsto.

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
- El vector de la consulta se calcula en cada pregunta, y **no dentro del
  servicio web** (§8). El puerto permite que el adaptador sea un servicio
  privado; **dónde vive queda diferido** hasta tener modelo, consumo, latencia
  y restricciones de infraestructura. Mientras esté diferido, ninguna pieza
  puede darlo por supuesto: es la razón de que el requisito de §8 sea
  verificable y no una intención.

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
