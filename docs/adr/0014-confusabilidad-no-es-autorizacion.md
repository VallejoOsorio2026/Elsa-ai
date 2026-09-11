# ADR 0014 — El aislamiento lo aplica el retrieval; el banco mide confusabilidad

- Estado: **aceptado**
- Bloque: 4.2.a
- Reescribe los **criterios 6 y 7** de la lista de aceptación de 4.2.a
  ([`bloque-4-2-plan.md`](../bloque-4-2-plan.md) §5) y el guardarraíl «fuga de
  alcance / fuga de versión» de
  [`embeddings-model-evaluation.md`](../embeddings-model-evaluation.md) §7.5
- Deriva de [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md) §6 y de
  la regla 3 de `CLAUDE.md`
- La elección del modelo de embeddings se registrará en el **ADR 0015**, que
  sigue pendiente de mediciones. Este ADR ocupa el número que el plan había
  reservado para aquella; no la sustituye ni la anticipa

## Contexto

La lista de aceptación aprobada para el Bloque 4.2.a pedía dos guardarraíles
del modelo de embeddings, redactados así:

> 6. Banco con corpus de dos activos y usuario autorizado a uno → **0** chunks
>    del activo no autorizado en los resultados, para todo `k`.
> 7. Banco con una versión publicada y otra `pending_validation` → **0** chunks
>    de la no publicada.

`embeddings-model-evaluation.md` §7.5 los llamaba «fuga de alcance» y «fuga de
versión», y los declaraba criterios de «pasa o no pasa»: un candidato que
fallara cualquiera de los dos quedaba fuera por bueno que fuera su `Recall`.

Al construir el banco quedó claro que esa redacción atribuye al modelo una
responsabilidad que no es suya, y que medirla como propiedad del modelo
produce dos daños concretos:

1. **Mide lo que no depende del modelo.** Un guardarraíl que cualquier
   candidato aprueba —o reprueba— por razones ajenas a él no discrimina nada,
   y ocupa el lugar de una medición que sí lo haría.
2. **Invita a leer el número como una garantía de seguridad.** Un informe que
   publica «fuga de alcance: 0» junto a las métricas de calidad sugiere que el
   modelo protege algo. No lo protege. Que ese número saliera bien podría, con
   el tiempo, usarse para justificar que el filtro de la consulta es menos
   crítico, y eso es exactamente la inversión de la regla 3.

Hay además una consecuencia práctica que obliga a decidir: el banco **no puede
a la vez** aplicar el filtro de alcance y medir si el modelo confunde activos
parecidos. Si el filtro está puesto, los chunks del activo ajeno nunca entran
al ranking y la confusión es inmedible por construcción. Las dos cosas no son
compatibles en la misma corrida, así que hay que elegir cuál de ellas es el
banco de embeddings y cuál es el retrieval.

## Decisión

### 1. «Fuga de alcance = 0» y «fuga de versión = 0» no son métricas de seguridad del modelo de embeddings

Se retiran como guardarraíles del modelo. Ningún candidato se acepta ni se
descarta por ellos, y el informe del banco no publica un número con ese
nombre.

Un modelo de embeddings produce vectores y un orden de similitud. No conoce el
dominio, ni el activo, ni el estado de publicación de nada, y no tiene ninguna
vía por la que imponerlos: **no es un mecanismo de autorización, ni puede
serlo**. Pedirle que garantice aislamiento es pedirle una propiedad que su
interfaz no tiene.

Los otros dos guardarraíles de §7.5 —determinismo y truncamiento— sí son
propiedades del modelo y del pipeline, y se mantienen intactos.

### 2. La autorización por dominio y activo, y la elegibilidad de la versión publicada, pertenecen al retrieval mediante filtros obligatorios

Son cláusulas obligatorias del `WHERE` de la consulta de recuperación, en la
misma consulta que calcula la similitud, y en este orden:

```
dominio → activo autorizado → versión publicada → chunks permitidos
```

Ningún índice —exista o no, exacto o aproximado— puede devolver una fila que
el filtro excluye. Lo razona ya ADR 0013 §6, y el puerto documental del Bloque
4.1 lo hace inevitable en vez de encomendarlo a la memoria de quien escriba la
consulta: `list_published_chunks` exige los alcances autorizados como
argumento obligatorio, de modo que no existe la forma de escribirla que
recupere primero y filtre después (regla 3).

**Los tests que los criterios 6 y 7 pedían ya existen, donde corresponde** —en
el repositorio documental, no en el banco:

| Qué prueba | Dónde |
|---|---|
| Un chunk solo se lee dentro de un alcance autorizado | `tests/test_document_lifecycle.py::test_chunks_are_only_readable_within_an_authorised_scope` |
| Solo las versiones publicadas se recuperan | `tests/test_document_lifecycle.py::test_only_published_versions_are_retrievable` |
| Una versión reemplazada deja de recuperarse | `tests/test_document_lifecycle.py::test_a_superseded_version_stops_being_retrievable` |

Esos tests corren contra el repositorio documental —hoy el adaptador en
memoria, que es la implementación de referencia del puerto—, no contra un
modelo. Es el sitio correcto: el aislamiento se prueba donde se aplica. Cuando
entre la persistencia PostgreSQL del Bloque 4.1.b, esas mismas pruebas
tendrán que pasar contra los dos adaptadores: es la condición para darla por
buena, no un añadido.

### 3. El banco de embeddings mide confusabilidad entre activos, documentos y versiones similares

Lo que sí es una señal sobre el modelo, y es la que se mide en su lugar: si el
ranking denso **confunde** dos activos que hablan parecido, dos documentos
cercanos, o dos versiones del mismo documento.

Tres ejes del conjunto dorado, agrupados en `CONFUSABILITY_AXES`
(`src/elsa/bench/model.py`) y reportados como una sola métrica, `confusion@5`:

| Eje | Qué confunde |
|---|---|
| `asset_confusion` | Dos activos técnicos distintos con vocabulario casi idéntico |
| `near_miss_document` | Dos documentos cercanos del mismo activo |
| `version_confusion` | Dos versiones del mismo documento |

`confusion@5` es la proporción de los cinco primeros resultados que pertenecen
al vecino equivocado, promediada sobre las consultas del eje. Es comparable
entre cualquier par de corridas, a diferencia de la abstención.

**Para poder medirla, el banco no aplica el filtro de alcance, y lo hace a
propósito.** Es la consecuencia directa de §1 y §2: el banco mide al modelo, y
el filtro es precisamente la pieza que no es del modelo. Un banco con el filtro
puesto mediría el filtro.

### 4. La confusabilidad es diagnóstico de calidad, nunca un mecanismo de autorización

La distinción es la razón de ser de este ADR, así que queda escrita como regla
y no como comentario:

- `confusion@5` **informa** la elección del modelo. Un candidato que confunda
  dos versiones del mismo documento entrega peores respuestas.
- `confusion@5` **no autoriza nada**. Un valor bajo no relaja ningún filtro, no
  justifica omitir una cláusula del `WHERE`, y no es evidencia de aislamiento.
  Un valor alto tampoco constituye una fuga: es un problema de calidad de
  ranking en un corpus sin filtrar.
- El informe **repite dónde acaba la responsabilidad del modelo cada vez que
  muestra el número**. La nota está en `src/elsa/bench/metrics.py` y viaja con
  el informe, no con la documentación, porque el informe es lo que alguien va a
  leer dentro de un año.
- Ninguna decisión de autorización puede tomar `confusion@5` como entrada. Si
  alguna vez un cambio propone leer una métrica del banco desde `core/` o desde
  el camino de una consulta, el diseño está mal y se corrige antes de seguir.

## Consecuencias

- Los criterios 6 y 7 de `bloque-4-2-plan.md` §5 quedan **reinterpretados por
  este ADR**, no incumplidos ni pendientes. La lista de aceptación los recoge
  con esa marca.
- `embeddings-model-evaluation.md` §7.5 pierde dos de sus cuatro guardarraíles
  y gana una referencia a este ADR en su lugar. Determinismo y truncamiento
  siguen siendo guardarraíles.
- El conjunto dorado debe mantener consultas de los tres ejes de confusabilidad
  en cantidad suficiente para que el número signifique algo. Hoy son diez
  consultas de 67, y el informe declara el número de consultas de cada eje
  junto a su métrica, precisamente para que se vea cuándo la muestra es
  pequeña.
- El banco corre sin filtro de alcance, y por tanto **no es** —ni puede
  presentarse como— evidencia de que el aislamiento funciona. Esa evidencia
  está en `tests/test_document_lifecycle.py` y en el contrato del puerto.
- La elección del modelo se registra en ADR 0015, tras medir. Este ADR no la
  anticipa.

### Lo que ya está medido

Con las tres líneas base de la etapa A, `confusion@5` discrimina poco todavía
—era esperable: ninguna es un modelo denso entrenado—, pero el eje de versiones
es el más confundible de los tres en las tres corridas:

| Corrida | `asset_confusion` | `near_miss_document` | `version_confusion` |
|---|---|---|---|
| `lexical-bm25` | 0,100 | 0,133 | **0,333** |
| `lexical-trigram` | 0,200 | 0,133 | **0,267** |
| `control-hashing-ngrams` | 0,200 | 0,133 | **0,200** |

Que sea el eje más confundible es coherente con lo que es: dos versiones del
mismo documento comparten casi todo el texto. Y es justamente la razón por la
que la elegibilidad de versión **no puede** depender del ranking: si el texto
es casi idéntico, ningún orden de similitud va a separarlas de forma fiable. La
separa el estado `published` en el `where`.

## Alternativas descartadas

**Dejar los criterios 6 y 7 como estaban y medirlos en el banco.** Habría que
aplicar el filtro de alcance en el banco, y entonces los tres ejes de
confusabilidad quedan inmedibles: el vecino equivocado nunca entra al ranking.
Se cambiaría una medición que discrimina por otra que siempre da 0 por
construcción y que no dice nada del modelo.

**Medirlos en el banco como comprobación redundante del filtro**, con filtro
puesto y reportando 0. No es redundancia útil: probaría el filtro del banco, no
el de producción, y el de producción ya tiene sus propios tests contra cada
adaptador. Un test verde que prueba otra cosa es peor que no tenerlo, porque se
cuenta como cobertura.

**Renombrarlos a «confusabilidad» y mantenerlos como «pasa o no pasa» con
umbral.** Fijar un umbral de descarte antes de haber medido un solo modelo
sería inventar el corte: no hay ningún dato que diga si 0,10 es bueno o malo
para un modelo denso real. La confusabilidad entra en la decisión como
diagnóstico comparado entre candidatos, y si más adelante hay base para un
umbral, se fija en el ADR 0015 con las mediciones delante.

**No registrar nada y dejar la reinterpretación solo en el plan.** La lista de
aceptación la aprobó el responsable del proyecto; cambiar dos de sus criterios
desde la documentación de un sub-bloque dejaría la decisión sin rastro
auditable y sin autor. La regla 25 pide ADR para las decisiones
arquitectónicas, y esta lo es: reparte una responsabilidad entre dos capas.

## Ver también

- [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md) §6 — los filtros son obligatorios; el índice no decide permisos
- [ADR 0002](0002-identidad-de-materiales-autorizacion-en-backend.md) — la autorización la aplica FastAPI, no la base ni el modelo
- [ADR 0006](0006-modelo-minimo-de-autorizacion.md) — alcance `(dominio, activo)`
- [ADR 0012](0012-ciclo-de-vida-documental-propio.md) — qué significa que una versión esté publicada
- [`embedding-benchmark.md`](../embedding-benchmark.md) §3 — cómo lo aplica el banco
- [`bloque-4-2-plan.md`](../bloque-4-2-plan.md) §5 — la lista de aceptación reinterpretada
