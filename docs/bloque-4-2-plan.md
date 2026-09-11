# Bloque 4.2 — Embeddings y almacenamiento vectorial (planificación)

> **Planificación CERRADA.** Las decisiones del bloque están tomadas y
> registradas en §4: **D1, D2, D3, D5, D8 y D10 aprobadas** (D2 con su ubicación
> diferida a propósito); **D4, D6, D7, D9 y D11 abiertas y no bloqueantes**, cada
> una con recomendación vigente y con el subbloque donde se cierra. El trabajo
> autorizado a continuación es **4.1.b**, y en paralelo los dos hilos que no son
> ingeniería: la validación de licencia de EmbeddingGemma y la reverificación de
> las cifras marcadas ⚠.

Documento de planificación. **No hay implementación de este bloque.** Producido
con la Skill `elsa-block-planning`; no se escribe código hasta autorización
explícita (regla 20 de `CLAUDE.md`).

Base: `origin/main` en `4a1b82e` (Bloque 4.0/4.1 y ELSA Agentic Tooling v1
integrados). Esquema documental aplicado y validado en el Supabase de ELSA
(§0.1).

---

## 0. Estado real de partida e inconsistencias detectadas

Regla 19. Se reportan primero, sin resolverlas por cuenta propia.

### 0.1 Estado real del Supabase de ELSA: la migración documental **sí** está aplicada

`20260908010000_create_documental_knowledge_model.sql` está **aplicada y
validada manualmente** en el proyecto Supabase de ELSA `shiaxoyhallucehoygqt`.

> **Procedencia de este dato.** Lo confirmó el responsable del proyecto con las
> comprobaciones que se listan abajo. **No se verificó desde esta sesión**: el
> repositorio no tiene —ni debe tener— credenciales del proyecto remoto, y
> ninguna sesión de planificación toca un Supabase (regla 15). Se registra como
> lo que es: estado confirmado por el responsable, no una medición propia.

| Comprobación | Resultado confirmado |
|---|---|
| Migraciones local/remoto alineadas | `20260905020000`, `20260906010000`, `20260908010000` |
| Tablas documentales con RLS activo | **6/6** con `RLS = true` |
| Políticas RLS | **0** — el modelo previsto: RLS activo y cero políticas (ADR 0002) |
| `document_chunk_provenance` | `security_invoker = true` |
| Rol `anon` | `SELECT = false` |
| Rol `authenticated` | `SELECT = false` |
| `fk_chunk_section_same_version` | presente |
| `fk_document_asset` | presente |
| `uq_published_document_version` | presente |
| Columnas vector/embedding | **0** |
| Filas documentales insertadas | **0** |

Las once comprobaciones son exactamente las garantías que el esquema prometía:
el remoto no solo tiene las tablas, tiene las restricciones que hacen
*imposible* —no improbable— publicar dos versiones del mismo documento o
mezclar un chunk con la sección de otra versión.

**Qué cambia esto en la planificación**, y es bastante:

1. **El prerrequisito de 4.1.b está satisfecho.** El adaptador PostgreSQL
   documental se puede construir y verificar contra un esquema remoto que ya
   existe, en vez de contra una promesa.
2. **`0` columnas vector/embedding confirma que no hay deuda de esquema.** La
   decisión de dónde vive el vector sigue abierta de verdad, sin nada que
   deshacer (ADR 0013).
3. **`0` filas documentales significa que no hay *backfill*.** La primera
   corrida de embedding de 4.2.b operará sobre un corpus que se cargará
   después, no sobre uno existente que haya que migrar. Es el momento más
   barato posible para fijar el espacio vectorial.

### 0.1.1 Un documento del repositorio quedó desactualizado

`docs/migration-runbook-bloque-4.md:7` sigue diciendo:

> **Esta migración NO se ha aplicado a ningún proyecto Supabase.**

Era cierto cuando se escribió y **ya no lo es**. Ese aviso no debe usarse como
fuente del estado actual.

Corregirlo es un cambio de documentación ajeno a esta planificación, así que
**no se mezcla aquí**: queda propuesto como unidad de trabajo aparte, que debe
actualizar el aviso del runbook y registrar la aplicación confirmada con sus
comprobaciones. Mientras eso no ocurra, el estado de referencia es §0.1 de este
documento.

### 0.2 No existe adaptador PostgreSQL del repositorio documental

Comprobado en el código, que es la única fuente válida para esto:
`DocumentRepositoryPort` solo tiene `memory_documents.py` (566 líneas) y no
existe `postgres_documents.py`.

**Esta es la única carencia dura que queda**, y es la importante: el esquema
documental está aplicado en el remoto (§0.1), pero ELSA todavía no sabe
escribir en él. Y no se pueden guardar vectores de chunks que no están en
PostgreSQL. Construir el adaptador es un trabajo comparable al de un bloque
entero: `postgres_knowledge.py`, su equivalente del Bloque 2, tiene 1362
líneas.

Esto obliga a cortar el bloque (§1) y es la razón principal del corte.

### 0.3 El piloto no tiene dónde ejecutar el modelo

`render.yaml` declara `plan: free`: 512 MB de RAM, CPU compartida y suspensión
por inactividad. Ninguno de los candidatos (300–600 M de parámetros) cabe ahí
junto al proceso de FastAPI. La instrucción pide evaluar «ejecución local» y
«RAM/VRAM/CPU»; el resultado de esa evaluación es que **el escenario de
despliegue actual no admite ningún modelo local**. No es un impedimento para
planificar. **Resuelto en parte por la decisión D2** (§4): está aprobado que el
motor no se ejecute ahí y que FastAPI quede desacoplado por puerto; la ubicación
definitiva queda **diferida**, y la cierran las mediciones de RAM y latencia del
banco.

### 0.4 El CI no tiene pgvector

`.github/workflows/ci.yml` usa `postgres:16`, que no trae la extensión
`vector`. La migración de este bloque fallará en CI hasta que cambie la imagen
(decisión D9). Un test que se omita por falta de extensión sería peor que uno
que falle: dejaría el esquema sin verificar sin que nadie lo note.

### 0.5 El puerto de embeddings actual no sirve para un modelo asimétrico

`EmbeddingsPort` tiene `embed(texts)` y `dimension`. Los tres candidatos
finalistas necesitan **prefijos distintos para consulta y para documento**;
usar el mismo texto para ambos degrada la calidad sin producir ningún error.
El puerto tiene que cambiar en este bloque.

Además, `FakeEmbeddingsAdapter` limita la dimensión a 32, así que hoy no puede
emular 768 ni 1024.

### 0.6 Un comentario del esquema quedará desactualizado

`comment on table elsa.document_chunks` dice «Sin vector: los embeddings llegan
en el Bloque 4.2», lo que puede leerse como que llegarán *en esa tabla*. Con la
arquitectura propuesta (ADR 0013) llegan en tabla aparte, y el comentario hay
que corregirlo en la migración de este bloque.

### 0.7 Sin contradicción, para que quede constancia

- «Trabaja desde el `main` más reciente»: verificado. `HEAD` de
  `claude/wonderful-archimedes-hmyn5i` es idéntico a `origin/main` (`4a1b82e`);
  la referencia local `main` estaba atrasada y se actualizó con `git fetch`.
- «NO actives pgvector» y «define arquitectura con pgvector» no se contradicen:
  se diseña ahora, se activa cuando se autorice.

---

## 1. Objetivo del bloque

Que ELSA pueda convertir su conocimiento documental en vectores con un modelo
**elegido con mediciones propias**, guardarlos de forma versionada y
reproducible, y volver a generarlos al cambiar de modelo sin quedarse sin
índice ni perder el anterior.

### El bloque no cabe en una rama: se parte en tres

Regla de corte de la Skill. Con lo hallado en §0.2, el Bloque 4.2 completo
serían tres unidades de revisión, no una.

| Orden | Subbloque | Qué entrega | Depende de |
|---|---|---|---|
| **1.º** | **4.1.b — Adaptador PostgreSQL documental** | `postgres_documents.py` contra el esquema ya aplicado en el remoto | Nada nuevo: el esquema ya está aplicado y validado (§0.1) |
| **2.º** | **4.2.a — Banco de evaluación y selección de modelo** | Se entrega en tres etapas (§2): **A** infraestructura y banco, **B** ejecución real de los modelos, **C** integración productiva | Nada. Es independiente de 4.1.b |
| **3.º** | **4.2.b — Persistencia vectorial** | Migración vectorial, registro de modelos, corridas de embedding | **4.2.a** (la dimensión) y **4.1.b** (dónde viven los chunks) |

### Por qué este orden es el correcto

**Las dependencias duras son solo dos, y las dos apuntan a 4.2.b:**

- 4.2.b necesita **4.2.a** porque la dimensión del vector es parte del tipo de
  la columna: escribir la migración antes de elegir el modelo sería fijar a
  ciegas lo que la medición tiene que decidir.
- 4.2.b necesita **4.1.b** porque un embedding es una fila que referencia un
  chunk por clave foránea. Sin chunks en PostgreSQL no hay a qué apuntar.

**4.1.b y 4.2.a no dependen entre sí.** El banco de pruebas trabaja sobre el
corpus sintético troceado con el chunker real, en memoria, sin base de datos.
Podrían ir en cualquier orden, o en paralelo si hubiera dos manos.

**Con 4.1.b primero se gana lo siguiente**, y por eso el orden propuesto es el
recomendado:

1. **Es el camino crítico.** 4.1.b es la pieza más grande de las tres y la
   única que bloquea a 4.2.b por sí sola. Empezarla primero significa que
   cuando 4.2.a entregue la dimensión, 4.2.b puede arrancar sin esperar nada.
2. **Vale por sí misma, aunque 4.2 no existiera.** Hoy la ingesta documental
   no puede persistir nada: se ejerce en memoria y se pierde al reiniciar. Eso
   es una carencia funcional mayor que no tener embeddings.
3. **Su prerrequisito acaba de quedar satisfecho.** Con el esquema aplicado y
   verificado en el remoto (§0.1), el adaptador se escribe contra algo que
   existe. Era el momento para el que estaba esperando.
4. **No hay riesgo de trabajo perdido en ninguno de los dos órdenes.** 4.1.b
   hace falta pase lo que pase con la elección del modelo, así que adelantarla
   no apuesta nada.

**Una salvedad, y no es menor.** Hay dos tareas de 4.2.a que **no deben
esperar a 4.1.b**, porque no son trabajo de ingeniería y su latencia no la
controlamos:

- La **revisión de licencia** de EmbeddingGemma (decisión D1). Depende de un
  criterio corporativo, no de código.
- La **reverificación de las cifras** de los modelos contra sus tarjetas
  (riesgo R12), bloqueadas por el egreso de la sesión en que se planificó.

Las dos pueden y deben empezar en paralelo con 4.1.b. Si la licencia se
resuelve tarde, el banco se corre con dos candidatos y el tercero se añade
después: el protocolo no cambia por eso.

Lo que sigue detalla **4.2.a**, y delimita 4.1.b y 4.2.b sin planificarlas al
detalle. Cada una tendrá su propia planificación cuando le toque.

---

## 2. Dentro del alcance de 4.2.a

4.2.a se entrega en **tres etapas**, y la separación no es cosmética: la
primera no depende de nada, la segunda depende de un entorno con acceso a
HuggingFace, y la tercera de una decisión de producto que todavía no está
tomada. Mezclarlas haría que un bloqueo de red pareciera trabajo sin hacer.

| Etapa | Qué es | Estado |
|---|---|---|
| **A — Infraestructura y banco de evaluación** | Con qué se mide | **Cerrada** (PR #9) |
| **B — Ejecución real de los modelos** | Medir los tres candidatos y elegir | **Pendiente**, por causa externa |
| **C — Integración productiva** | Que ELSA use embeddings de verdad | **Diferida** |

Los once ítems de la lista original se conservan con su numeración; lo único
que cambia es a qué etapa pertenece cada uno.

### 2.A — Infraestructura y banco de evaluación (cerrada)

Lo que se puede construir y verificar sin descargar un solo modelo.

5. **Corpus sintético** en `bench/corpus-sintetico/`: documentos técnicos en
   español inventados, más uno en inglés, troceados con el chunker real.
   Ningún dato de PAPELSA (regla 12). → **42 chunks, 2 activos, v1 publicada
   y v2 no.**
6. **Conjunto dorado** de ~60 consultas con las `structural_key` esperadas,
   etiquetadas por eje. → **67 consultas en 19 ejes.**
7. **Herramienta de banco de pruebas** en `src/elsa/tools/`:
   `Recall@{1,3,5,10}`, `MRR@10`, `nDCG@10`, `P@5`, global y por eje; líneas
   base léxica y de trigramas; métricas de operación. Informe reproducible.
   → **`elsa.tools.embedding_benchmark`; la parte comparable del informe es
   idéntica entre corridas.**
2. **Composición determinista del texto embebido**: plantilla `context-v1`
   (título del documento › rastro de títulos › contenido) y su hash
   `embedded_sha256`. Función pura, sin base de datos, con tests. →
   **`src/elsa/documents/composition.py`.** Estaba en la lista sin etapa
   asignada; pertenece aquí porque **sin ella el banco mediría una entrada
   que producción no va a usar**.

Añadido que la lista original no preveía y que la etapa necesitaba:

- **Interfaz de adaptadores medibles** (`src/elsa/bench/ports.py`) y un
  **control determinista** (`adapters/hashing.py`) que fija el suelo y hace
  el banco ejecutable sin red, también en CI.
- **Grupo opcional** `bench` en `pyproject.toml` con el `uv.lock` al día, de
  modo que la corrida de la etapa B sea reproducible desde el manifiesto y un
  clon limpio siga pasando sin instalar nada (regla 24).

### 2.B — Ejecución real de los modelos (pendiente, causa externa)

4. *(parte de medición)* Medir los **tres** candidatos con el mismo conjunto
   dorado y las mismas reglas: BGE-M3, Qwen3-Embedding-0.6B y
   EmbeddingGemma-300m, este último sujeto a la revisión de licencia (D1).
9. **Informe de resultados** con la salida real pegada, y **ADR 0014** con el
   modelo elegido y por qué (se escribe *después* de medir).
10. **Confirmación de D4, D6, D7 y D11** con lo que muestre el banco,
    registrada en ADR 0014.
11. Documentación: `docs/embeddings-model-evaluation.md` actualizado con las
    cifras **verificadas contra las tarjetas de los modelos**.

Bloqueo: la política de egreso del entorno de trabajo responde `403` al
`CONNECT` para `huggingface.co`, `hf.co` y `cdn-lfs.huggingface.co`. No se
pueden descargar los pesos ni leer las tarjetas. El procedimiento para
completarlo en un entorno habilitado está en
[`embedding-benchmark.md`](embedding-benchmark.md) §7.

**Sin esta etapa no hay ganador, ni provisional.** Un candidato sin medir no
se descarta ni se elige, y una puntuación pública no sustituye la medición.

### 2.C — Integración productiva (diferida)

Todo lo que hace que ELSA *use* embeddings, frente a *medirlos*. Se difiere
en conjunto porque los tres ítems solo tienen sentido juntos: un puerto
asimétrico sin adaptador no sirve a nadie, y un fake a 1024 dimensiones sin
puerto asimétrico prueba un contrato que no existe.

1. **`EmbeddingsPort` corregido**: distingue documento de consulta, y declara
   identidad del modelo (nombre, revisión, dimensión, si normaliza, ventana
   máxima, plantillas de prefijo). Sigue siendo `Protocol` en
   `src/elsa/ports/`, sin dependencia de ningún proveedor.
3. **`FakeEmbeddingsAdapter` ampliado** a dimensiones reales (768, 1024),
   determinista entre procesos. **No afecta a la validez del banco**: el
   banco tiene su propio control y nunca importa este fake, que hoy solo lo
   usa `tests/test_contract_embeddings.py` contra el puerto productivo.
4. *(parte de integración)* **Un adaptador real por candidato**, en
   `src/elsa/adapters/`, elegido por configuración.

La etapa A deja el camino hecho: los prefijos por candidato, la composición
del texto y la distinción documento/consulta ya están resueltos y probados en
`src/elsa/bench/`, listos para trasladarse cuando se autorice.

---

## 3. Fuera del alcance

Explícito. Aquí va todo lo que quedará «casi listo».

| Fuera | Dónde va | Por qué no aquí |
|---|---|---|
| Migración vectorial, pgvector, índices | 4.2.b | La dimensión la decide la medición de 4.2.a |
| Activar pgvector en Supabase, cualquier migración remota | 4.2.b, con autorización explícita en su momento | Regla 15 |
| `postgres_documents.py` | **4.1.b** | Es un bloque propio (§0.2) |
| Búsqueda vectorial, híbrida, RRF, reranking | 4.3 | Sin vectores almacenados no hay nada que combinar |
| Reranker real (`RerankerPort` sigue con su fake) | 4.3 | Se elige con el resultado de la recuperación, no antes |
| LLM, generación, citas, orquestador | 4.4 y 4.5 | Reglas 2 y 20 |
| Endpoint HTTP que embeba algo | 4.3 | Embeber en el camino de la request con CPU compartida bloquearía el servicio |
| Decidir dónde se aloja el modelo en producción | Decisión D2, antes de 4.2.b | Es una decisión de despliegue, no de código |
| Canal léxico para códigos SAP en documentos | 4.3 | 4.2 solo lo mide, para que nadie lo dé por resuelto |
| Embeddings de aportes del Bloque 3 | No previsto | Regla 16: un aporte no es conocimiento |
| Subir plan de Render, servidor on-premise | Fuera del proyecto | Es compra, no código |
| Corregir el aviso desactualizado de `migration-runbook-bloque-4.md` (§0.1.1) | Unidad de trabajo aparte | Es documentación ajena a esta planificación; mezclarla aquí ensuciaría el diff del bloque |

---

## 4. Registro de decisiones

Las decisiones de este bloque están **tomadas y registradas** salvo donde se
indica. Una decisión aprobada no se reabre sin un ADR nuevo (regla 25).

| # | Decisión | Estado | ADR |
|---|---|---|---|
| **D1** | EmbeddingGemma como candidato | **Aprobada con condición** | 0014 |
| **D2** | Dónde se ejecuta el motor de embeddings | **Aprobada en lo arquitectónico · ubicación DIFERIDA** | 0013 §8 |
| **D3** | Dónde vive el vector | **Aprobada** | 0013 §1 |
| **D4** | Tipo, métrica e índice | Abierta, no bloqueante | 0013 §6 |
| **D5** | Qué versiones se embeben | **Aprobada con política** | 0013 §5 y §7 |
| **D6** | Contexto en el texto embebido | Abierta, no bloqueante | 0013 §4 |
| **D7** | Embeber chunks de tipo `table` | Abierta, no bloqueante | 0014 |
| **D8** | Corte del bloque y orden | **Aprobada** | — |
| **D9** | Imagen de PostgreSQL del CI | Abierta, se decide al llegar 4.2.b | — |
| **D10** | Supabase remoto | **Aprobada con aclaración** | — |
| **D11** | Runtime del adaptador real | Abierta, no bloqueante | 0014 |

---

### D1 — EmbeddingGemma: aprobada **para el banco**, no para producción

**Aprobado** entrar al banco de pruebas como tercer candidato.

**No puede ser elegido para producción** mientras no se valide formalmente que
sus términos de licencia y de uso son aceptables para un despliegue corporativo
de PAPELSA.

Consecuencias operativas:

- **No bloquea 4.1.b ni el banco de 4.2.a.** Se mide con los otros dos y en las
  mismas condiciones.
- La validación de licencia es un hilo **paralelo**, no una tarea del camino
  crítico. Su latencia no la controlamos porque no es trabajo de ingeniería.
- Si el banco lo señalara como mejor candidato y la validación no estuviera
  resuelta, **el resultado se reporta y no se elige**: se elige el mejor de los
  habilitados, y el dato de EmbeddingGemma queda registrado por si la
  validación llega después. Medir no habilita, igual que aprobar no publica.

### D2 — El motor de embeddings no vive dentro del servicio web

**Aprobado, y es una prohibición explícita:** no se ejecutan modelos de
embeddings dentro del servicio Render Free actual de ELSA.

**Aprobado** que la arquitectura desacople FastAPI del motor de embeddings
mediante puerto y adaptador. Es la aplicación directa del ADR 0003 a esta
dependencia: el negocio importa el puerto, nunca el motor.

**Permitido para 4.2.a:** ejecutar los candidatos en un **entorno de banco
independiente**, fuera del servicio web y fuera del camino de la request.

**DIFERIDA** la ubicación definitiva del servicio de inferencia del piloto.
Se decidirá cuando se conozcan las cuatro cosas de las que depende, y no antes:

1. el modelo ganador;
2. su consumo real de RAM, CPU y GPU;
3. su latencia medida;
4. las restricciones de infraestructura de PAPELSA.

**Requisito que la arquitectura objetivo tiene que cumplir.** Debe poder
cambiarse entre servicio local u on-premise, servidor dedicado u otro proveedor
autorizado **sin modificar la lógica de recuperación ni el esquema documental**.
Ese requisito es verificable, no una aspiración: si cambiar de ubicación
obligara a tocar `core/` o una migración, el diseño está mal y hay que
corregirlo antes de seguir.

### D3 — Tabla separada, con convivencia de modelos

**Aprobado:** el vector vive en `elsa.document_chunk_embeddings`, **no** en una
columna de `document_chunks`.

**Requisito aprobado junto con la decisión:** debe permitir la convivencia de
más de un modelo o versión de embedding **durante migraciones y rollback**. Es
exactamente lo que una columna única no puede hacer, y la razón principal de la
tabla aparte (ADR 0013 §1 y §5).

### D5 — Política de qué se embebe y qué es elegible para recuperar

**Aprobada** con esta política, que distingue dos cosas que no son la misma:
**generar** un embedding y que ese embedding sea **elegible para recuperación
productiva**.

| Estado de la versión | ¿Se generan embeddings? | ¿Elegible en recuperación productiva? |
|---|---|---|
| `pending_validation` (borrador, sin validar) | **No**, normalmente no | No |
| `rejected` | **No** | No |
| `approved` | **Sí, permitido** antes de publicar, para poder validar el índice nuevo | **No** |
| `published` | Sí | **Sí**, y solo esta |
| `superseded` | No se generan nuevos | No, pero **se conservan** mientras sirvan para rollback o comparación |

> Nota de vocabulario: el esquema no tiene un estado `draft`. Su equivalente es
> `pending_validation`, que es donde nace una versión tras la ingesta
> (ADR 0012). La política se aplica sobre los estados que existen.

**Cambiar la versión publicada cambia atómicamente qué embeddings son elegibles.**
Y esto se cumple **por construcción, no por convención**: la elegibilidad se
deriva de la versión mediante el `join`, así que publicar —que es atómico y está
protegido por `uq_published_document_version`— cambia de golpe qué embeddings
entran. Es la razón exacta por la que el estado de publicación **no** se copia
en la fila del embedding: si se copiara, publicar tendría que reescribir una
fila por chunk y dejaría de ser atómico.

**Los embeddings anteriores se conservan** mientras sean necesarios para
rollback o comparación. Retirarlos es una decisión posterior y explícita, nunca
un efecto colateral de activar un modelo nuevo (ADR 0013 §5).

**La autorización productiva exige siempre la cadena completa:**

```
dominio autorizado → activo autorizado → versión publicada → chunk permitido
```

### D8 — Corte y orden, aprobados formalmente

1. **4.1.b** — Adaptador PostgreSQL del repositorio documental.
2. **4.2.a** — Banco de pruebas ELSA y selección del modelo.
3. **4.2.b** — Persistencia vectorial, registro de modelos y corridas de embedding.

Justificación de las dependencias en §1.

### D10 — Supabase remoto: compuerta explícita

**Aprobado con esta aclaración, que es más estricta que la regla 15:**

- **4.1.b y 4.2.a no modifican el Supabase remoto.** Ninguna de las dos tiene
  motivo para tocarlo: el esquema documental ya está aplicado (§0.1) y el banco
  trabaja fuera de la base.
- En **4.2.b** la migración vectorial se diseña y se prueba **localmente**,
  contra PostgreSQL efímero.
- **Ninguna migración del Bloque 4.2 se aplica al Supabase real sin una
  compuerta explícita de aceptación y autorización del responsable**, en la
  conversación en que se aplique y solo para la migración prevista.
- **Que el destino final sea Supabase no autoriza modificaciones remotas
  durante el desarrollo.** Es la trampa que esta aclaración cierra: «al final va
  a acabar ahí» no es una autorización.

### Decisiones que siguen abiertas

Ninguna bloquea el arranque de 4.1.b ni de 4.2.a. Cada una lleva su
recomendación vigente y se cierra donde corresponda.

| # | Decisión | Recomendación vigente | Se cierra en |
|---|---|---|---|
| **D4** | Tipo, métrica e índice | `vector(N)` normalizado, coseno y búsqueda **exacta** en el piloto. Los filtros son obligatorios en los dos casos; lo que evita la búsqueda exacta es la pérdida de recall que un índice aproximado introduce bajo filtros selectivos, antes de tener con qué medirla (ADR 0013 §6) | 4.2.b |
| **D6** | Contexto en el texto embebido | Sí, con plantilla versionada: sin contexto, «apriete a 45 Nm» es irrecuperable | 4.2.a |
| **D7** | Embeber chunks de tipo `table` | Sí: una tabla de pares de apriete es justo lo que se pregunta. Lo confirma el eje de códigos del banco | 4.2.a |
| **D9** | Imagen de PostgreSQL del CI | `pgvector/pgvector:pg16`, al llegar 4.2.b y no antes | 4.2.b |
| **D11** | Runtime del adaptador real | ONNX Runtime: PyTorch son ~2 GB de dependencia para un clon limpio. En ambos casos, grupo opcional y pesos **fuera de Git** | 4.2.a |

---

### ADR que exige el bloque

| ADR | Estado | Qué registra |
|---|---|---|
| [0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) | **Aceptado** | Arquitectura vectorial: tabla aparte, registro de modelos, «generar no activa», filtros obligatorios, motor reemplazable. Lo respaldan D2, D3 y D5 |
| `0014-eleccion-del-modelo-de-embeddings.md` | Pendiente | El modelo elegido y por qué. **No se escribe hasta tener mediciones** (regla 21). Recogerá D1, D7 y D11 |

---

## 5. Criterios de aceptación de 4.2.a

Comando o acción → resultado observable, separados por etapa (§2). Algunos
comandos de la redacción original nombraban banderas y archivos que no
existen (`--corpus`, `--model fake`, `tests/test_embedding_benchmark.py`);
aquí se corrigen por los reales, porque un criterio que no se puede ejecutar
no es un criterio.

### Etapa A — verificables hoy

| # | Comando / acción | Resultado esperado | Estado |
|---|---|---|---|
| 1 | `uv run pytest` en un clon limpio **sin** el extra `bench` | Verde. Sin omisiones nuevas salvo las de PostgreSQL ya existentes | ✅ 941 pasadas, 106 omitidas |
| 2 | `uv run ruff check . && uv run ruff format --check . && uv run mypy` | Sin hallazgos | ✅ |
| 3 | `uv run python -m elsa.tools.embedding_benchmark --out bench/resultados` | Sale 0 e imprime las métricas por eje y las de operación | ✅ |
| 4 | El comando 3, dos veces, comparando la **huella comparable** del informe | Idéntica. La sección de coste depende de la máquina y se excluye de la huella a propósito | ✅ |
| 5 | `uv run pytest tests/test_bench_corpus.py tests/test_bench_metrics.py tests/test_bench_harness.py` | Verde | ✅ 49 pasadas |
| 9 | Texto embebido de un chunk, calculado dos veces | Mismo `embedded_sha256`; y distinto al cambiar la plantilla | ✅ `tests/test_document_composition.py` |
| 10 | `git status` tras una corrida completa | Limpio: ni pesos, ni vectores, ni corpus privado | ✅ |
| 11 | `git grep -nE "\.onnx\|\.gguf\|\.safetensors"` y `gitleaks` | Sin pesos versionados, sin secretos | ✅ |

### Etapa B — exigen medir los modelos

| # | Comando / acción | Resultado esperado |
|---|---|---|
| 8 | El comando 3 con `--candidates bge-m3,qwen3-0.6b,embeddinggemma-300m`, en la máquina de referencia declarada | Informe completo por candidato, con la salida real pegada en el cierre |
| 13 | Revisión del informe por el responsable | El modelo elegido cumple los filtros duros y el orden de preferencia fijado **antes** de medir |

### Etapa C — exigen integración productiva

| # | Comando / acción | Resultado esperado |
|---|---|---|
| 12 | `uv run pytest tests/test_contract_embeddings.py` | El fake y cada adaptador real cumplen el mismo contrato de puerto |

### Criterios 6 y 7: reinterpretados

La redacción original los pedía como guardarraíles **del modelo**:

> 6. Banco con corpus de dos activos y usuario autorizado a uno → **0**
>    chunks del activo no autorizado en los resultados, para todo `k`.
> 7. Banco con una versión publicada y otra `pending_validation` → **0**
>    chunks de la no publicada.

No son propiedades del modelo, y exigirlas como tales sería medir lo que no
depende de él. El aislamiento lo impone el `WHERE` de la consulta de
recuperación, y ningún índice puede devolver una fila que el filtro excluye
—es lo que ya razona [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md).
Los tests de que una versión no publicada no se recupera **ya existen**,
donde corresponde: en el repositorio documental del Bloque 4.1
(`list_published_chunks`).

Lo que el banco sí mide, y aporta, es **confusabilidad**: si el ranking denso
confunde dos activos que hablan parecido o dos versiones del mismo documento
(`confusion@5`, ejes `asset_confusion`, `version_confusion` y
`near_miss_document`). Para poder medirla, el banco **no aplica** el filtro
de alcance: si lo aplicara, la confusión sería inmedible.

**Esta reinterpretación reescribe dos criterios de una lista aprobada y
necesita quedar registrada** —ADR 0014 o enmienda firmada de este plan—
antes de dar 4.2.a por cerrado en su totalidad. Detalle en
[`embedding-benchmark.md`](embedding-benchmark.md) §3.

---

## 6. Riesgos

Con mitigación concreta.

| # | Riesgo | Mitigación |
|---|---|---|
| R1 | Se elige por tableros públicos y el modelo rinde mal en español técnico de planta | Criterio de decisión escrito **antes** de medir (`embeddings-model-evaluation.md` §3) y conjunto dorado propio. El puerto permite cambiar de modelo sin tocar el negocio |
| R2 | El modelo elegido no cabe donde acabe corriendo, y la ubicación está diferida (D2) | Lo que el diferimiento **no** aplaza es la medición: el banco reporta RAM pico y latencia por candidato, que son dos de los cuatro datos con los que se cierra D2. El filtro duro es «ejecutable, con huella declarada, en al menos uno de los escenarios viables (E1 o E2)», y el desacople por puerto (ADR 0013 §8) permite mover el motor sin tocar recuperación ni esquema |
| R3 | **Calidad, no autorización.** Un índice ANN combinado con filtros selectivos (activo, versión publicada) deja menos candidatos útiles tras el filtrado: se entrega de menos, en silencio. Los permisos se siguen aplicando —el filtro es obligatorio y el índice no puede devolver lo que excluye— pero una respuesta pobre parece una respuesta | Búsqueda exacta en el piloto, que además es la verdad de referencia (ADR 0013 §6). Cuando el volumen justifique indexar: medir el recall con los **filtros reales** puestos, comparar contra la búsqueda exacta, y `hnsw.iterative_scan = strict_order` |
| R4 | Alguien cierra el bloque creyendo que los códigos SAP ya se recuperan | El eje de códigos se mide y se reporta, y **no** puntúa la elección. ADR 0010 ya dice dónde se resuelven |
| R5 | PyTorch u ONNX entran como dependencia dura y rompen el criterio del clon limpio | Grupo opcional en `pyproject.toml`; el CI corre con el fake; criterio de aceptación 1 |
| R6 | Pesos del modelo o manuales reales acaban en Git | Patrones explícitos en `.gitignore` (`*.onnx`, `*.gguf`, `*.safetensors`, `models/`, `bench/corpus-privado/`); criterios 10 y 11; gitleaks ya corre sobre toda la historia |
| R7 | La corrida de embedding compite con FastAPI por la CPU y degrada el servicio | Las corridas son una herramienta CLI, nunca un endpoint. Fuera del alcance, explícito en §3 |
| R8 | Truncamiento silencioso de chunks que superan la ventana | Bandera `truncated` en cada fila y criterio de aceptación que exige declarar el número |
| R9 | Un re-embedding deja el corpus a medias | «Generar no activa» (ADR 0013 §5): los vectores son aditivos y la activación es una transacción. Volver atrás es cambiar el activo |
| R10 | La migración de 4.2.b rompe el CI por falta de pgvector | D9, en el mismo PR que la migración. La suite **falla**, no se omite |
| R11 | El esquema de la extensión difiere entre Supabase y PostgreSQL local | Se resuelve en 4.2.b: la migración crea el esquema si falta y cualifica el tipo; se prueba en local **y** se verifica contra Supabase antes de aplicar (regla 15) |
| R12 | Las cifras de esta planificación son de fuentes secundarias (egreso bloqueado) | Cada cifra marcada ⚠ se reverifica contra la tarjeta del modelo como primera tarea de 4.2.a, antes de escribir adaptadores |

---

## 7. Estimación cualitativa de coste y tiempo

Sin fechas: el proyecto avanza por bloques, no por calendario.

| Trabajo | Tamaño | Qué lo domina |
|---|---|---|
| **4.1.b** (primero, y camino crítico) | **Grande** | Reproducir en SQL las 566 líneas de semántica del adaptador en memoria, con sus tests de esquema contra PostgreSQL |
| Reverificar cifras contra las tarjetas de los modelos (en paralelo) | Pequeño | Acceso a red sin bloqueos |
| Revisión de licencia de EmbeddingGemma (en paralelo) | Pequeño en esfuerzo, **incierto en latencia** | No lo controlamos: es criterio corporativo |
| Puerto, composición del texto, fake ampliado | Pequeño | Diseño, no volumen |
| Corpus sintético y conjunto dorado | **Medio, y es el cuello de botella** | Es trabajo humano de criterio: 60 consultas realistas con su respuesta esperada. Es lo único que no se puede acelerar |
| Herramienta de banco de pruebas y sus tests | Medio | Métricas por eje e informe reproducible |
| Tres adaptadores reales | Medio | Descarga de pesos y runtime ONNX; la primera vez cuesta, la segunda y la tercera no |
| Corridas de medición | Pequeño en tiempo de persona | Minutos de CPU por modelo sobre 200–400 chunks, tres veces. No horas |
| Informe y ADR 0014 | Pequeño | Ya está el protocolo |
| **4.2.b** (último) | Medio | Migración, registro de modelos, corridas, herramienta. **Sin *backfill***: el corpus documental remoto está vacío (§0.1) |

**Coste monetario del piloto: cero en licencias.** Los tres finalistas son
descargables y ejecutables en local. Lo que sí cuesta:

- Disco: 2–4 GB de pesos, **fuera del repositorio**.
- Almacenamiento vectorial: ~40 MB por cada 10 000 chunks a 1024 dimensiones.
  Irrelevante.
- Un contenedor pequeño (2 vCPU / 4 GB) si se aprueba D2(a). Es el único gasto
  recurrente nuevo, y es modesto.

---

## Ver también

- [`embeddings-model-evaluation.md`](embeddings-model-evaluation.md) — candidatos, criterio de decisión, protocolo del banco y escenarios de hardware
- [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) — arquitectura vectorial **aceptada**
- [`knowledge-architecture.md`](knowledge-architecture.md) — las dos clases de conocimiento y la hoja de ruta 4.x
- [`document-chunking.md`](document-chunking.md) — el chunk que se va a embeber
- [`migration-runbook-bloque-4.md`](migration-runbook-bloque-4.md) — procedimiento de la migración documental. **Su aviso de «no aplicada» está desactualizado**: el estado real está en §0.1
