# Bloque 4.2 — Embeddings y almacenamiento vectorial (planificación)

Documento de planificación. **No hay implementación de este bloque.** Producido
con la Skill `elsa-block-planning`; no se escribe código hasta autorización
explícita (regla 20 de `CLAUDE.md`).

Base: `origin/main` en `4a1b82e` (Bloque 4.0/4.1 y ELSA Agentic Tooling v1
integrados).

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
planificar, pero condiciona qué modelo puede elegirse, así que se decide antes
de implementar (decisión D2).

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
| **2.º** | **4.2.a — Banco de pruebas y selección de modelo** | Puerto corregido, adaptadores reales, corpus sintético, banco, informe con mediciones y ADR 0014 | Nada. Es independiente de 4.1.b |
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

Lista cerrada. Todo verificable por comando.

1. **`EmbeddingsPort` corregido**: distingue documento de consulta, y declara
   identidad del modelo (nombre, revisión, dimensión, si normaliza, ventana
   máxima, plantillas de prefijo). Sigue siendo `Protocol` en
   `src/elsa/ports/`, sin dependencia de ningún proveedor.
2. **Composición determinista del texto embebido**: plantilla `context-v1`
   (título del documento › rastro de títulos › contenido) y su hash
   `embedded_sha256`. Función pura, sin base de datos, con tests.
3. **`FakeEmbeddingsAdapter` ampliado** a dimensiones reales (768, 1024),
   determinista entre procesos. Es lo que usa el CI.
4. **Un adaptador real por candidato**, en `src/elsa/adapters/`, elegido por
   configuración. Los candidatos que pasan al banco son **tres**: BGE-M3,
   Qwen3-Embedding-0.6B y EmbeddingGemma-300m como opción de bajo consumo
   sujeta a la revisión de licencia (D1). Si D1 no está resuelta cuando
   arranque el banco, se corre con dos y el tercero se añade sin rehacer nada.
   Dependencias en un grupo **opcional** de `pyproject.toml`: un clon limpio
   sigue pasando los tests sin instalarlas (regla 24).
5. **Corpus sintético** en `bench/corpus-sintetico/`: documentos técnicos en
   español inventados, más uno en inglés, troceados con el chunker real.
   Ningún dato de PAPELSA (regla 12).
6. **Conjunto dorado** de ~60 consultas con las `structural_key` esperadas,
   etiquetadas por eje.
7. **Herramienta de banco de pruebas** en `src/elsa/tools/`, al estilo de
   `document_acceptance.py`: `Recall@{1,3,5,10}`, `MRR@10`, `nDCG@10`, `P@5`,
   global y por eje; líneas base léxica y de trigramas; métricas de operación
   (chunks/s, latencia p50/p95, RSS pico, MB por 1000 chunks). Informe
   reproducible byte a byte.
8. **Guardarraíles como tests, no como métricas**: fuga de alcance = 0, fuga de
   versión no publicada = 0, determinismo, truncamiento declarado.
9. **Informe de resultados** con la salida real pegada, y **ADR 0014** con el
   modelo elegido y por qué (se escribe *después* de medir, no antes).
10. **ADR 0013 aprobado o corregido** (hoy propuesto).
11. Documentación: `docs/embeddings-model-evaluation.md` actualizado con las
    cifras verificadas contra las tarjetas de los modelos, y
    `docs/environment-variables.md` con la configuración nueva.

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

## 4. Decisiones que hay que tomar

Las marcadas **A** requieren aprobación antes de escribir una línea de código.

| # | Decisión | Opciones | Recomendación | ADR |
|---|---|---|---|---|
| **D1 A** | Política de licencia para el modelo entregado a PAPELSA | (a) solo OSI permisiva (MIT/Apache-2.0); (b) se acepta *Gemma Terms of Use* con revisión de uso corporativo | Los tres candidatos se **miden** igualmente; lo que D1 decide es si EmbeddingGemma puede ser **elegido**. Arrancar esta revisión en paralelo con 4.1.b, porque su latencia no la controlamos | 0014 |
| **D2 A** | Dónde se calcula el vector de la consulta en el piloto | (a) servicio privado aparte (2 vCPU / 4 GB) detrás del puerto; (b) subir el plan de Render; (c) 4.3 arranca sin canal denso | **(a)**: es lo único compatible con el puerto y con no tocar el plan actual | 0013 |
| **D3 A** | Dónde vive el vector | (a) tabla `document_chunk_embeddings`; (b) columna en `document_chunks` | **(a)**, ADR 0013 §1 | 0013 |
| **D4** | Tipo, métrica e índice | (a) `vector(N)` normalizado, coseno, búsqueda **exacta** en el piloto; (b) HNSW desde el principio | **(a)**, ADR 0013 §6. Los filtros de autorización y publicación son obligatorios en los dos casos; lo que evita (a) es la pérdida de recall que un índice aproximado introduce bajo filtros selectivos, antes de tener con qué medirla | 0013 |
| **D5** | Qué versiones se embeben | (a) `approved` y `published`; (b) solo `published` | **(a)**: publicar tiene que seguir siendo atómico; la seguridad la da el filtro de la consulta | 0013 |
| **D6** | El texto embebido lleva contexto (título + rastro de títulos) | (a) sí, plantilla versionada; (b) solo el contenido | **(a)**: sin contexto, «apriete a 45 Nm» es irrecuperable | 0013 |
| **D7** | Se embeben los chunks de tipo `table` | (a) sí; (b) no | **(a)**: una tabla de pares de apriete es justo lo que se pregunta. Se confirma con el eje de códigos del banco | 0014 |
| **D8 A** | Corte del bloque y orden | (a) **4.1.b → 4.2.a → 4.2.b**; (b) 4.2.a → 4.1.b → 4.2.b; (c) un solo bloque grande | **(a)**, justificado en §1: 4.1.b es el camino crítico, vale por sí misma y su prerrequisito ya está satisfecho. (b) también funciona —4.1.b y 4.2.a son independientes— pero deja a 4.2.b esperando la pieza grande | — |
| **D9** | Imagen de PostgreSQL del CI | (a) `pgvector/pgvector:pg16`; (b) instalar la extensión en el paso de CI | **(a)** al llegar 4.2.b, no antes | — |
| **D10 A** | Confirmar que 4.2 **no** toca ningún Supabase remoto | — | Confirmado por la instrucción; se deja escrito | — |
| **D11** | Runtime del adaptador real | (a) ONNX Runtime; (b) PyTorch + sentence-transformers | **(a)**: PyTorch son ~2 GB de dependencia para un clon limpio. En ambos casos, grupo opcional y pesos **fuera de Git** | 0014 |

**ADR nuevos que exige el bloque:**
`docs/adr/0013-arquitectura-de-almacenamiento-vectorial.md` (escrito, estado
propuesto) y `docs/adr/0014-eleccion-del-modelo-de-embeddings.md`, que **no se
escribe hasta tener mediciones** (regla 21).

---

## 5. Criterios de aceptación de 4.2.a

Comando o acción → resultado observable.

| # | Comando / acción | Resultado esperado |
|---|---|---|
| 1 | `uv run pytest` en un clon limpio **sin** el grupo opcional | Verde. Sin omisiones nuevas salvo las de PostgreSQL ya existentes |
| 2 | `uv run ruff check . && uv run ruff format --check . && uv run mypy` | Sin hallazgos |
| 3 | `uv run python -m elsa.tools.embedding_benchmark --corpus bench/corpus-sintetico --model fake` | Sale 0 e imprime las métricas por eje y las de operación |
| 4 | El comando 3, dos veces, con `diff` de las salidas | Idénticas byte a byte |
| 5 | `uv run pytest tests/test_embedding_benchmark.py` | Verde, incluidos los guardarraíles: fuga de alcance 0, fuga de versión 0 |
| 6 | Banco con corpus de dos activos y usuario autorizado a uno | **0** chunks del activo no autorizado en los resultados, para todo `k` |
| 7 | Banco con una versión publicada y otra `pending_validation` | **0** chunks de la no publicada |
| 8 | El comando 3 con **cada** adaptador real, en la máquina de referencia declarada | Informe completo por candidato, con la salida real pegada en el cierre |
| 9 | Texto embebido de un chunk, calculado dos veces | Mismo `embedded_sha256`; y distinto al cambiar la plantilla |
| 10 | `git status` tras una corrida completa | Limpio: ni pesos, ni vectores, ni corpus privado |
| 11 | `git grep -nE "\.onnx|\.gguf|\.safetensors"` y `gitleaks` | Sin pesos versionados, sin secretos |
| 12 | `uv run pytest tests/test_contract_embeddings.py` | El fake y cada adaptador real cumplen el mismo contrato de puerto |
| 13 | Revisión del informe por el responsable | El modelo elegido cumple los filtros duros y el orden de preferencia fijado **antes** de medir |

---

## 6. Riesgos

Con mitigación concreta.

| # | Riesgo | Mitigación |
|---|---|---|
| R1 | Se elige por tableros públicos y el modelo rinde mal en español técnico de planta | Criterio de decisión escrito **antes** de medir (`embeddings-model-evaluation.md` §3) y conjunto dorado propio. El puerto permite cambiar de modelo sin tocar el negocio |
| R2 | El modelo elegido no cabe donde va a correr | D2 se decide antes de implementar; «cabe en el escenario acordado» es un **filtro duro**, no un criterio ponderado |
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
- [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) — arquitectura vectorial propuesta
- [`knowledge-architecture.md`](knowledge-architecture.md) — las dos clases de conocimiento y la hoja de ruta 4.x
- [`document-chunking.md`](document-chunking.md) — el chunk que se va a embeber
- [`migration-runbook-bloque-4.md`](migration-runbook-bloque-4.md) — procedimiento de la migración documental. **Su aviso de «no aplicada» está desactualizado**: el estado real está en §0.1
