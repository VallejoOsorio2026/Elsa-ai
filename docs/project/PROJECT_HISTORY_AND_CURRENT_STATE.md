# Historia técnica y estado actual de ELSA

Reconstrucción verificable de lo que ELSA **ya es**, redactada para que una
persona o una sesión futura no tenga que reconstruirla otra vez.

- Fecha de corte: **2026-09-21**
- Revisión de referencia: `origin/main` = `2425c8ae`
- Alcance: repositorio `VallejoOsorio2026/Elsa-ai`
- Aplica las reglas **17, 21, 22 y 25** de [`CLAUDE.md`](../../CLAUDE.md)

---

## 1. Propósito y alcance

### 1.1 Qué hace este documento

Reconstruye el **estado real** del proyecto a partir de la evidencia que vive
en Git, en la documentación versionada y en las decisiones humanas ya
registradas. Existe porque hasta hoy buena parte de esa memoria vivía en
conversaciones, y una conversación no es una fuente de verdad: no se puede
auditar, no se hereda y no sobrevive a la entrega del proyecto (regla 17).

Su función es responder, sin volver a auditar nada:

```text
¿Qué ya está construido?
¿Qué ya fue probado, y dónde?
¿Qué está realmente pendiente?
¿Qué depende de PC1?
```

### 1.2 Qué NO hace

- **No reemplaza a los ADR.** Los ADR de [`docs/adr/`](../adr/) siguen siendo
  la **única autoridad normativa**. Este documento los resume, los referencia
  y los ordena en el tiempo; no los reinterpreta y no los deroga. Ante
  cualquier discrepancia entre este documento y un ADR, **manda el ADR**.
- **No es un documento de cierre de bloque.** Los cierres se rigen por
  [`BLOCK_CLOSURE_STANDARD.md`](BLOCK_CLOSURE_STANDARD.md) (regla 26) y viven
  en `docs/bloque-*-cierre.md`.
- **No decide nada.** No abre ni cierra hitos, no aprueba fusiones, no
  remedia deudas. Registrar una deuda aquí **no** la corrige.
- **No es un registro de continuidad.** Eso es el
  [Mapa de entrega y continuidad](HANDOVER_AND_CONTINUITY_MAP.md).

### 1.3 Cómo mantenerlo

Se actualiza cuando un bloque cierra o cuando un hecho aquí registrado deja de
ser cierto. No se actualiza commit a commit: para eso está el historial de Git.

---

## 2. Fuentes y clasificación de evidencia

Todo hecho de este documento lleva, explícita o implícitamente, una de estas
cinco clasificaciones. La distinción no es decorativa: es lo que impide que una
afirmación cómoda se convierta con el tiempo en un hecho técnico demostrado.

| Clasificación | Significado | Fuente |
|---|---|---|
| `VERIFICADO_ACTUAL` | Comprobado sobre `origin/main` = `2425c8ae` en esta misma sesión | Árbol de trabajo, `git`, archivos del repositorio |
| `VERIFICADO_HISTORICO` | Consta en el historial de Git, en un ADR aceptado o en un documento de evidencia versionado, pero **no** se volvió a ejecutar ahora | `git log`, `docs/adr/`, `docs/piloto-0-1/`, `bench/resultados/` |
| `DECLARADO_POR_USUARIO` | Afirmado por el administrador del proyecto; **no** hay artefacto versionado que lo respalde | Instrucciones de sesión |
| `INFERIDO` | Deducido de la evidencia disponible, con razonamiento explícito; **no** medido | Este documento |
| `NO_RECUPERADO` | Se sabe que existió o que debería existir, y **no** se encontró | Ausencia comprobada |

**Regla de uso.** `DECLARADO_POR_USUARIO` e `INFERIDO` **nunca** se promueven a
hecho técnico demostrado. Si una decisión futura depende de uno de ellos,
primero hay que medirlo y versionar la medida.

### 2.1 Fuentes primarias consultadas

- Historial de Git de `origin/main` y de las ramas remotas.
- Los **26 ADR** de [`docs/adr/`](../adr/).
- Los documentos de evidencia de [`docs/piloto-0-1/`](../piloto-0-1/).
- Los artefactos del banco de embeddings en `bench/resultados/`.
- El código de `src/elsa/`, las pruebas de `tests/` y las migraciones de
  `supabase/migrations/`.

---

## 3. Línea de tiempo

`VERIFICADO_ACTUAL` salvo donde se indique. Período reconstruido:
**2026-09-04 → 2026-09-21**, 18 días naturales.

### 3.1 Cifras del repositorio

| Métrica | Valor | Nota |
|---|---|---|
| Commits alcanzables desde todas las referencias remotas | **169** | `git rev-list --count --remotes` |
| Commits en `origin/main` | **162** | Los 7 restantes viven solo en ramas no fusionadas |
| Pull requests fusionados | **33** | `#1`–`#33`, sin huecos |
| ADR | **28** | `0001`–`0028` |
| Migraciones | **5** | [`supabase/migrations/`](../../supabase/migrations/) |
| Ramas remotas | **41** | Excluyendo `origin/HEAD` |
| Ramas no fusionadas en `main` | **5** | §11 y §3.3 |
| Historia de Git | **Continua** | Sin reescrituras ni huecos detectados |

> **Sobre las cifras.** Una auditoría previa registró «169 commits» y «42 ramas
> remotas». La diferencia con `main` (162) no es una pérdida: **169 es el total
> alcanzable desde todas las referencias remotas**, y 162 el subconjunto que
> llegó a `main`. Para las ramas, 41 es el conteo excluyendo el alias
> `origin/HEAD`. Ambas cifras son consistentes con la auditoría previa.

### 3.2 Hitos

| Fecha | Hito | PR | Qué dejó |
|---|---|---|---|
| 2026-09-04 | **Bloque 0** — fundación técnica | `#1` | Esqueleto FastAPI, `uv`, puertos, CI |
| 2026-09-05 | **Bloque 1** — identidad y permisos | `#2` | Autorización propia de ELSA, primera migración |
| 2026-09-06 | **Bloque 2** — activo técnico y BOM | `#3` | Modelo de conocimiento estructurado |
| 2026-09-08 | **Bloque 3** — marca e interfaz | `#4`, `#5` | `docs/brand/`, `web/`, despliegue Render |
| 2026-09-09 | Tooling agéntico | `#6` | `CLAUDE.md`, Skills, subagentes |
| 2026-09-10 | **Bloque 4.0/4.1** — arquitectura de ingesta | `#7`, `#8` | Modelo documental, chunking determinista |
| 2026-09-11 | **Bloque 4.2.a A** — banco de embeddings | `#9` | Infraestructura del banco, corpus, conjunto dorado |
| 2026-09-12 | **Bloque 4.1.b** — documentos en PostgreSQL | `#10` | `postgres_documents.py`, migración documental |
| 2026-09-12 | Banco portable en Windows | `#11` | Habilita la corrida en **PC1** |
| 2026-09-12 | **Bloque 4.2.a B** — selección de modelo | `#12` | [ADR 0015](../adr/0015-eleccion-del-modelo-de-embeddings.md) |
| 2026-09-12 | **Bloque 4.2.b** — persistencia vectorial | `#13` | pgvector, migración de almacenamiento vectorial |
| 2026-09-12 | **Bloque 4.2.a C** — integración de embeddings | `#14` | `embeddings_admin`, generación y activación |
| 2026-09-13 | **Bloque 4.3** — recuperación híbrida | `#15` | [ADR 0016](../adr/0016-recuperacion-hibrida-del-mvp.md), RRF |
| 2026-09-13 | **Bloque 4.4** — generación fundamentada | `#16` | [ADR 0017](../adr/0017-generacion-fundamentada-y-citas-verificables.md) |
| 2026-09-13 | **Bloque 4.5** — runtime LLM local | `#17` | [ADR 0018](../adr/0018-runtime-llm-local-phi-4-mini-y-llama-cpp.md), `LlamaCppAdapter` (`0c6a87f`) |
| 2026-09-13 | **Experimento ONNX** (fuera de `main`) | — | Rama `claude/keen-curie-2xeh0r`, commit `61b3b42` (§11) |
| 2026-09-15 | **Bloque 4.6 / D11** — identidad del espacio vectorial | `#18` | [ADR 0019](../adr/0019-identidad-del-espacio-vectorial-y-del-productor.md) |
| 2026-09-15 | Capacidades componibles | `#19` | [ADR 0020](../adr/0020-capacidades-componibles-y-planes-de-ejecucion.md), `capability_outcomes.py` |
| 2026-09-16 | **Piloto 0.1** — diseño normativo | `#20` | Contrato funcional, manual del observador |
| 2026-09-16 | Contrato de inventario con Materiales | `#21` | [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md), hitos **M1–M8** |
| 2026-09-19 | Feedback e incident snapshot | `#22` | [ADR 0022](../adr/0022-feedback-e-incident-snapshot-del-piloto.md) |
| 2026-09-19 | **Subbloque 5.0.c.1** — ausencia segura | `#23`, `#24` | Política de ausencia segura, su cierre |
| 2026-09-19 | Validación real de frontera (**M3/M5**) | `#25`, `#26` | [ADR 0024](../adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md), evidencia en PC1 |
| 2026-09-19 | **B9a/B9b/B9c** — cobertura segura | `#27`, `#28` | [ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md), `coverage_policy.py` |
| 2026-09-20 | ADR 0020–0024 a estado `aceptado` | `#29` | Normalización de estados |
| 2026-09-20 | **M6** — semántica y temporalidad | `#30`, `#31` | Evidencia M6, [ADR 0025](../adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) |
| 2026-09-20 | **Subbloque 5.0.b** — cierre | `#32` | Cierre normativo y documental de 5.0.b |
| 2026-09-21 | **M7** — cierre | `#33` | [ADR 0026](../adr/0026-gobernanza-y-cierre-de-m7.md). **M7 cerrado** |
| 2026-09-21 | **M4-NORMATIVO** — cierre | `#36`, `#37` | [ADR 0027](../adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md). **M4 operativo sigue abierto** |
| 2026-09-21 | **M1-A** — contrato consumidor ejecutable | pendiente | [ADR 0028](../adr/0028-forma-del-resultado-contractual-del-puerto-de-materiales.md), [cierre M1-A](../bloque-5-0-m1-a-contrato-consumidor-cierre.md). **M1 sigue abierto** |

### 3.3 Ramas no fusionadas

`VERIFICADO_ACTUAL`. Cinco ramas remotas no están contenidas en `origin/main`:

| Rama | Contenido | Lectura |
|---|---|---|
| `claude/keen-curie-2xeh0r` | Experimento ONNX FP32 (§11) | **Trabajo histórico no integrado**, único y relevante |
| `bloque-3-ui-audio-piloto` | Trabajo de interfaz previo al Bloque 3 | Superado por `#4` |
| `prep/bloque-3-brand` | Preparación de marca | Superado por `#4` |
| `feat/bloque-4-1b-postgres-documents` | Documentos en PostgreSQL | Superado por `#10` |
| `chore/bench-etapa-b-artefactos` | Artefactos del banco | Superado por `#12` |

Solo la primera contiene trabajo técnico único que no llegó a `main`.

---

## 4. Estado de `llama.cpp`

> ```text
> llama.cpp NO está pendiente de integración.
> ```
>
> Está **integrado, documentado, cubierto por pruebas y ejercitado en CI**.
> Quien lea este documento y concluya que hay que «instalar llama.cpp» estará
> repitiendo trabajo ya hecho. Ver §14.

`VERIFICADO_ACTUAL` para todo lo que es código y documentación en el
repositorio. `VERIFICADO_HISTORICO` para la ejecución en PC1.

### 4.1 Qué existe

| Pieza | Ubicación | Clasificación |
|---|---|---|
| Decisión arquitectónica | [ADR 0018](../adr/0018-runtime-llm-local-phi-4-mini-y-llama-cpp.md) | `VERIFICADO_ACTUAL` |
| Guía de operación | [`docs/llm-runtime.md`](../llm-runtime.md) | `VERIFICADO_ACTUAL` |
| Puerto | `src/elsa/ports/llm.py` — `LLMPort` | `VERIFICADO_ACTUAL` |
| Adaptador real | `src/elsa/adapters/llama_cpp_llm.py` — `LlamaCppAdapter` | `VERIFICADO_ACTUAL` |
| Adaptadores falsos | `fake_llm.py`, `scripted_llm.py` | `VERIFICADO_ACTUAL` |
| Composición | `src/elsa/container.py` elige el adaptador por configuración | `VERIFICADO_ACTUAL` |
| Herramienta CLI | `src/elsa/tools/llm_runtime.py` | `VERIFICADO_ACTUAL` |
| Scripts de operación | `scripts/Start-ElsaLlm.ps1`, `Stop-ElsaLlm.ps1`, `Test-ElsaLlm.ps1` | `VERIFICADO_ACTUAL` |
| Servidor falso para pruebas | `tests/fake_llama_server.py` | `VERIFICADO_ACTUAL` |
| Pruebas | `test_llama_cpp_adapter.py`, `test_rag_llama_cpp_end_to_end.py`, `test_llm_runtime_tool.py`, `test_llm_runtime_configuration.py` | `VERIFICADO_ACTUAL` |

### 4.2 Modo de operación

**`llama-server`, no `llama-cli`.** La decisión está tomada y razonada en
[ADR 0018](../adr/0018-runtime-llm-local-phi-4-mini-y-llama-cpp.md): un
servidor HTTP persistente en loopback mantiene el modelo residente, evitando
recargarlo en cada petición. `LlamaCppAdapter` habla HTTP con él.

### 4.3 Versión de referencia

`VERIFICADO_ACTUAL` como texto versionado en
[ADR 0018 §90-91](../adr/0018-runtime-llm-local-phi-4-mini-y-llama-cpp.md) y
[`docs/llm-runtime.md`](../llm-runtime.md):

```text
Build:      b10938
Commit:     f1e44dcc1
Backend:    Vulkan
Dispositivo: Vulkan0  (Radeon RX 570, 4 GB VRAM)
```

### 4.4 CI

`VERIFICADO_ACTUAL`. El adaptador y el camino RAG completo se ejercitan en CI
contra `tests/fake_llama_server.py`, un servidor HTTP real en loopback que
**no** carga ningún modelo. Esto es deliberado: CI valida el **contrato** del
adaptador —petición, respuesta, plazos, errores, concurrencia, métricas— sin
depender de pesos ni de GPU.

**Consecuencia que no debe olvidarse:** CI en verde demuestra que la
integración es correcta, **no** que el modelo responda bien. La calidad del
modelo solo se mide en PC1.

### 4.5 PC1

`VERIFICADO_HISTORICO`. PC1 es la máquina Windows del administrador actual, y
es hoy el **único** entorno donde `llama-server` y el modelo se han ejecutado
de verdad. Ni CI ni Render cargan modelos. Ver el
[Mapa de entrega y continuidad §6](HANDOVER_AND_CONTINUITY_MAP.md#6-infraestructura-local).

---

## 5. Modelo local

`VERIFICADO_ACTUAL` como configuración versionada.

| Campo | Valor |
|---|---|
| Modelo | **Microsoft Phi-4-mini-instruct** |
| Formato | **GGUF** |
| Cuantización | **Q4_K_M** |
| Origen | `bartowski/microsoft_Phi-4-mini-instruct-GGUF` |
| Variable de ruta | `ELSA_LLM_MODEL_PATH` |
| Identificador lógico | `ELSA_LLM_MODEL=phi-4-mini-instruct` |
| Contexto conocido | **2048** tokens (`ELSA_LLM_CONTEXT_TOKENS`) |
| Salida máxima | **512** tokens (`ELSA_LLM_MAX_OUTPUT_TOKENS`) |
| Temperatura | **0** (`ELSA_LLM_TEMPERATURE`) |
| Concurrencia | **1** (`ELSA_LLM_CONCURRENCY`) |

La cuantización no es una preferencia estética: **Q4_K_M es lo que cabe en los
4 GB de VRAM** de la GPU de PC1 junto con un contexto de 2048
([ADR 0018](../adr/0018-runtime-llm-local-phi-4-mini-y-llama-cpp.md)).

La temperatura no se fija al arrancar el servidor: ELSA la envía en cada
petición, de modo que el determinismo es responsabilidad del cliente.

### 5.1 Huecos de evidencia del modelo

```text
Hash del GGUF:   NO_RECUPERADO
Tamaño medido:   NO_RECUPERADO
```

La documentación describe el peso del archivo de forma aproximada. **`~2 GB`
es un orden de magnitud, no una medición**, y no debe citarse como tal. Hasta
que alguien mida el archivo en PC1 y versione el resultado, ELSA **no sabe**
qué GGUF exacto se usó: no hay hash, no hay tamaño en bytes, no hay fecha de
descarga.

Esto importa para la continuidad: un sucesor que descargue «el mismo modelo»
no tiene hoy forma de comprobar que obtuvo el mismo archivo.

---

## 6. Pruebas históricas del modelo

Esta sección separa deliberadamente lo demostrado de lo que se perdió. La
separación es el punto: el proyecto **sí** probó el modelo, y **no** conservó
los números.

### 6.1 Demostrado

| Hecho | Clasificación | Evidencia |
|---|---|---|
| El runtime se ejecutó en PC1 | `VERIFICADO_HISTORICO` | [ADR 0018](../adr/0018-runtime-llm-local-phi-4-mini-y-llama-cpp.md), [`docs/llm-runtime.md`](../llm-runtime.md) |
| Phi-4-mini quedó residente en `llama-server` | `VERIFICADO_HISTORICO` | ADR 0018 |
| Se comparó Phi-4-mini con Qwen3-4B-Instruct-2507 | `VERIFICADO_HISTORICO` | [`docs/llm-runtime.md`](../llm-runtime.md) §387 |
| Se eligió `llama-server` sobre `llama-cli` | `VERIFICADO_HISTORICO` | ADR 0018 |
| El adaptador y el flujo RAG pasan en CI | `VERIFICADO_ACTUAL` | `tests/test_llama_cpp_adapter.py`, `tests/test_rag_llama_cpp_end_to_end.py` |
| Los embeddings se midieron en PC1 | `VERIFICADO_HISTORICO` | `bench/resultados/`, [ADR 0015](../adr/0015-eleccion-del-modelo-de-embeddings.md) |

La comparación Phi/Qwen quedó registrada **normativamente** —como conclusión
que fundamenta una decisión— pero no como dato reproducible.

### 6.2 No recuperado

| Falta | Clasificación |
|---|---|
| Prompts exactos usados con Phi-4-mini y con Qwen | `NO_RECUPERADO` |
| Corpus comparativo de la evaluación Phi/Qwen | `NO_RECUPERADO` |
| Resultados completos de esa comparación | `NO_RECUPERADO` |
| Línea base de nueve métricas del runtime de generación | `NO_RECUPERADO` |
| Origen y condiciones de la cifra `~20 tok/s` | `NO_RECUPERADO` |

Sobre `~20 tok/s`: [`docs/llm-runtime.md`](../llm-runtime.md) la registra
explícitamente como «referencia del banco previo» y deja la medición real como
**pendiente**. Ese banco previo no está versionado. La cifra es, por tanto,
una referencia heredada sin procedencia: **no** es una medición del proyecto.

---

## 7. RAG

`VERIFICADO_ACTUAL`. El camino de recuperación y generación fundamentada está
**implementado completo** en el repositorio.

### 7.1 Piezas

| Pieza | Ubicación | ADR |
|---|---|---|
| Modelo documental | `src/elsa/documents/`, [`docs/document-model.md`](../document-model.md) | 0010, 0012 |
| Ingestión | `src/elsa/ingestion/`, `services/document_ingestion.py` | 0008, 0011 |
| Chunking determinista | [`docs/document-chunking.md`](../document-chunking.md) | 0011 |
| Embeddings | `services/embedding_generation.py`, `adapters/sentence_transformer_embeddings.py` | [0015](../adr/0015-eleccion-del-modelo-de-embeddings.md) |
| Persistencia vectorial (pgvector) | `adapters/postgres_vectors.py` | [0013](../adr/0013-arquitectura-de-almacenamiento-vectorial.md) |
| Canal léxico | `adapters/postgres_lexical.py` | 0016 |
| Recuperación híbrida (RRF) | `services/hybrid_retrieval.py`, `core/retrieval.py` | [0016](../adr/0016-recuperacion-hibrida-del-mvp.md) |
| Context Builder | `core/context_builder.py` | 0017 |
| Política de generación | `core/generation_policy.py` | 0017 |
| Generación fundamentada | `services/grounded_generation.py` | [0017](../adr/0017-generacion-fundamentada-y-citas-verificables.md) |
| Validador de fundamentación | `core/grounding.py` | 0017 |
| Ausencia segura | `core/answers.py`, `core/capability_outcomes.py` | 0020, 5.0.c.1 |
| Cobertura | `core/coverage_policy.py` | [0023](../adr/0023-cobertura-desconocida-materiales-piloto.md) |
| Identidad del espacio vectorial | `core/versioning.py` | [0019](../adr/0019-identidad-del-espacio-vectorial-y-del-productor.md) |

### 7.2 La distinción que más se malinterpreta

```text
RAG implementado          ≠          RAG expuesto por HTTP
```

| | Estado |
|---|---|
| **RAG implementado** | **Sí.** Completo, con pruebas, ejercitable hoy |
| **RAG accesible por CLI** | **Sí.** `python -m elsa.tools.llm_runtime ask` |
| **RAG expuesto por HTTP** | **No.** Ningún endpoint invoca `GroundedGenerationService` |

`VERIFICADO_ACTUAL`: `GroundedGenerationService` aparece únicamente en
`src/elsa/services/grounded_generation.py` (su definición),
`src/elsa/tools/llm_runtime.py` (la CLI) y cuatro archivos de `tests/`.
**Ninguna referencia en `src/elsa/api/`.**

Confundir estas dos cosas es el error más probable de una sesión futura, y por
eso §9 lo desarrolla y §14 lo prohíbe explícitamente.

---

## 8. CLI

`VERIFICADO_ACTUAL`. Cinco herramientas en `src/elsa/tools/`. Todas están
pensadas para ejecutarse en una máquina con acceso a pesos y a datos reales
—PC1, hoy— y **nunca** desde el servicio web.

| Herramienta | Propósito |
|---|---|
| `llm_runtime` | Operar el runtime de generación local. Cinco subcomandos: `check` (configuración sin red), `health` (¿el modelo está cargado?), `generate` (generación mínima con latencia y tokens/s), `demo` (camino RAG sobre evidencia sintética, sin base), `ask` (camino RAG sobre el corpus real) |
| `embeddings_admin` | Operar el motor de embeddings. Cinco subcomandos: `register`, `generate`, `activate`, `status`, `search`. **`generate` no activa** y **`activate` no genera** (ADR 0013 §5) |
| `embedding_benchmark` | Banco de evaluación de modelos de embeddings (Bloque 4.2.a) |
| `document_acceptance` | Prueba de aceptación determinística de la ingesta documental |
| `private_acceptance` | Prueba de aceptación contra archivos reales que viven **fuera** del repositorio (regla 12) |

`demo` y `ask` de `llm_runtime` se separan a propósito: `demo` permite validar
el runtime **el primer día**, sin corpus ni PostgreSQL; `ask` es la
demostración completa del bloque y exige base con conocimiento ingerido y
embeddings generados. Ninguno toca datos de planta.

La CLI llama al **mismo** `GroundedGenerationService` que usaría un endpoint,
no a una copia: lo que la CLI demuestra es el camino real.

---

## 9. HTTP

`VERIFICADO_ACTUAL`.

### 9.1 Qué existe

Existe el endpoint:

```text
POST /api/v1/assistant/{domain}/{asset}/ask
```

Definido en `src/elsa/api/v1/assistant.py`.

### 9.2 Qué hace realmente

**No usa el LLM. No usa el RAG.** Su implementación:

1. Resuelve el activo y valida adjuntos.
2. Obtiene la **versión publicada** del BOM mediante `KnowledgeRepositoryPort`.
   Si no hay versión publicada, responde que no hay nada validado que
   consultar.
3. Extrae términos y códigos de la pregunta con un analizador léxico simple.
4. Ejecuta una **búsqueda literal** sobre los ítems y modos de falla de esa
   versión.
5. Redacta la respuesta con **plantillas de texto** fijas.

Sus dependencias declaradas son `resolve_asset`, `KnowledgeRepositoryPort` y
`Settings`. No hay `LLMPort`, no hay recuperación híbrida, no hay generación
fundamentada.

### 9.3 La afirmación que debe quedar registrada

```text
No existe todavía ningún endpoint HTTP productivo
que invoque GroundedGenerationService.
```

Esto **no** es una deuda oculta: es el estado deliberado del piloto, que
prioriza no afirmar nada sin evidencia recuperada. Pero sí es la brecha más
importante entre lo que ELSA **puede** hacer (por CLI) y lo que **expone** (por
HTTP).

---

## 10. Embeddings

`VERIFICADO_HISTORICO` para las mediciones; `VERIFICADO_ACTUAL` para los
artefactos.

### 10.1 Resultado de la selección

| Modelo | Veredicto |
|---|---|
| `google/embeddinggemma-300m` | **Ganador técnico, condicionado.** Encabeza las seis métricas de calidad, es el único que supera la línea léxica en el eje discriminante `synonyms`, el más rápido en consulta y el único que se abstiene cuando el corpus no contiene la respuesta. **No aprobado para producción**: su licencia (Gemma Terms of Use) y su repositorio *gated* exigen una validación legal corporativa de PAPELSA que sigue pendiente |
| `BAAI/bge-m3` | **Candidato productivo.** Segundo en todas las métricas, sin dependencia legal bloqueante |
| `Qwen/Qwen3-Embedding-0.6B` | **Descartado.** Por debajo de la línea léxica en `synonyms` y ~17× más lento en consulta que EmbeddingGemma |

Decisión en [ADR 0015](../adr/0015-eleccion-del-modelo-de-embeddings.md).

### 10.2 Banco real de PC1

Las tres corridas se ejecutaron **en PC1**, no en el entorno de agente: la
política de egreso de este entorno bloquea `huggingface.co`. Hardware
registrado: Windows, Python 3.12.13, CPU AMD64 Family 23 Model 17, sin GPU.

### 10.3 Artefactos versionados

`VERIFICADO_ACTUAL`. En `bench/resultados/`:

```text
informe.json                      informe.md
bge-m3-informe.json               embeddinggemma-300m-informe.json
qwen3-0.6b-informe.json           README.md
```

Estos sí sobrevivieron. Son el contraejemplo útil frente a §6.2: cuando una
medición se versiona, se hereda.

### 10.4 El hueco de la corrida híbrida

`VERIFICADO_ACTUAL` por ausencia comprobada.

El banco midió los **candidatos densos** y las **líneas base léxicas** por
separado. **No existe en `bench/resultados/` ninguna corrida del canal híbrido
completo** —exacto + léxico + semántico fusionados por RRF— sobre datos reales:
`informe.json` no contiene ninguna referencia a `rrf` ni a fusión híbrida.

Es decir: la recuperación híbrida está **implementada y razonada**
([ADR 0016](../adr/0016-recuperacion-hibrida-del-mvp.md)) pero **no medida
extremo a extremo**. Clasificación del rendimiento del canal híbrido:
`NO_RECUPERADO`.

---

## 11. ONNX

```text
Estado en main:
  sin runtime ONNX activo.

Estado histórico:
  rama    claude/keen-curie-2xeh0r
  commit  61b3b42
  aprox.  3064 líneas únicas
  sin PR
  sin merge
```

`VERIFICADO_ACTUAL`. Comprobado en esta sesión:

- La rama `origin/claude/keen-curie-2xeh0r` **existe**.
- El commit `61b3b42` —«feat(bench): experimental ONNX FP32 harness for BGE-M3
  equivalence (block 4.6, phase 1)»— **no es ancestro de `origin/main`**.
- Su diff introduce **3064 líneas** en 8 archivos:

  | Archivo | Líneas |
  |---|---|
  | `src/elsa/bench/onnx_experiment.py` | 1150 |
  | `tests/test_bench_onnx.py` | 802 |
  | `src/elsa/bench/adapters/onnx.py` | 791 |
  | `docs/bench-onnx-experimental.md` | 219 |
  | `pyproject.toml`, `.gitignore`, `uv.lock`, `tests/test_gitignore.py` | 102 |

- Parte de `dfdd2ef` (PR `#17`, 2026-09-13), por lo que su base es el `main` de
  aquel momento, no el actual.

### 11.1 Clasificación

```text
TRABAJO HISTORICO NO INTEGRADO
```

**Este documento no decide si debe fusionarse.** Esa decisión exige un ADR
propio (regla 25) y una evaluación de si el trabajo sigue siendo aplicable
sobre el `main` actual, 16 PR más adelante.

Lo único que este documento fija es que **el trabajo existe, es sustancial y no
se perdió**. Una sesión futura que escriba «ONNX nunca se desarrolló» estará
equivocada (§14).

---

## 12. Streams separados

Tres flujos de trabajo distintos conviven en el contexto del administrador.
**No comparten entregables, ni fases, ni criterios de cierre.** Mezclarlos es
una fuente recurrente de confusión.

### 12.1 ELSA

- **Repositorio:** `VallejoOsorio2026/Elsa-ai`.
- **Qué es:** el asistente corporativo para los ingenieros de mantenimiento de
  la Planta Molino Barbosa. MVP limitado al equipo **Tampella**.
- **Estado:** este documento.

### 12.2 Materiales

- **Repositorio:** `VallejoOsorio2026/papelsa-asistente-materiales`.
- **Revisión conocida:** `436eab92` (`DECLARADO_POR_USUARIO`; no verificable
  desde este repositorio, cuyo alcance de acceso no lo incluye).
- **Qué es:** sistema propietario de su inventario (~65.000 registros). ELSA
  **no** los duplica (regla 4).
- **Relación con ELSA:** ELSA consume identidad y datos de inventario a través
  de un contrato versionado
  ([ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md)).
  `docs/contrato-elsa.md` vive en Materiales, y el **Contract Owner** está
  materializado allí ([ADR 0026](../adr/0026-gobernanza-y-cierre-de-m7.md)).
- **Regla operativa:** **Materiales no se modifica desde este repositorio.**

### 12.3 SAP / ZIAA

- **Qué es:** la extracción de datos de inventario desde SAP mediante la
  transacción **ZIAA**, con selección de centros, macro de extracción y
  transformación posterior.
- **Estado:** `DECLARADO_POR_USUARIO`. **No** está automatizado extremo a
  extremo, y **no** vive en este repositorio.
- **Relación con ELSA:** ELSA consume *snapshots* de SAP en formato `.htm`
  durante la ingesta, pero **no** ejecuta SAP ni la macro.
- Ver el [Mapa de entrega y continuidad §5](HANDOVER_AND_CONTINUITY_MAP.md#5-sapziaa).

### 12.4 BOM / estructuras de activos

- **Qué es:** las estructuras de activos técnicos que Ingeniería mantiene en
  archivos `.xlsx`, con sus modos de falla (AMEF).
- **Relación con ELSA:** son la fuente del conocimiento estructurado que ELSA
  ingiere, revisa y publica. El endpoint HTTP de §9 consulta exactamente esto.
- **Estado:** modelo cerrado ([ADR 0007](../adr/0007-modelo-de-activo-tecnico.md)),
  ingesta implementada, flujo de publicación implementado.

---

## 13. Estado normativo actual

`VERIFICADO_ACTUAL` contra
[ADR 0021 §25](../adr/0021-contrato-de-inventario-con-materiales.md) y sus
notas de actualización, [ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md),
[ADR 0024](../adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md),
[ADR 0025 §15](../adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
[ADR 0026](../adr/0026-gobernanza-y-cierre-de-m7.md) y
[ADR 0027](../adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md).

| ID | Estado al 2026-09-21 | Bloqueante | Fijado por |
|---|---|---|---|
| **M1** | **Abierto.** Decisión arquitectónica cerrada. **M1-A cerrado**: el contrato esperado es ejecutable en ELSA y la deuda `Material | None` está eliminada. **Pendiente**: la fachada no existe ni está solicitada, y no hay adaptador real | **Sí** | ADR 0021 §19.1, §25, ADR 0028, [cierre M1-A](../bloque-5-0-m1-a-contrato-consumidor-cierre.md) |
| **M2** | **Abierto** | No | ADR 0021 §25 |
| **M3** | **Resuelto para V1** como **M3-A**, medido sobre datos reales | No | ADR 0024 §8 |
| **M4** | **Abierto.** **M4-NORMATIVO cerrado**: la semántica de `null` y la de los cinco campos del bloque `inventory` quedan decididas. **M4 operativo abierto**: verificación e implementación de metadata pendientes | **Sí** | ADR 0021 §25, ADR 0027 §22, [cierre M4-NORMATIVO](../bloque-5-0-m4-normativo-cierre.md) |
| **M5** | **Resuelto para V1.** JWKS asimétrico `ES256`/`EC`, JWT de usuario real verificado contra el RPC real | No | ADR 0024 §11 |
| **M6** | **Decisión normativa cerrada · implementación y verificación pendientes** | **Sí** | ADR 0025 §15 |
| **M7** | **CERRADO.** Rol, ocupante y gobernanza materializados; la asignación vive en Materiales y ELSA la referencia sin copiarla | No | ADR 0026 §4, §9 |
| **M8** | **Abierto · no bloqueante.** La cobertura `UNKNOWN` se acepta para V1 bajo controles compensatorios verificables. El criterio de cierre de **ADR 0021 §8.3 sigue intacto y sin cumplir** | No | ADR 0023 |

### 13.1 Lecturas que este documento fija

- **M1 sigue abierto y bloqueante.** No se cierra por asociación con M7.
- **M4-NORMATIVO está cerrado; M4 operativo no.** La semántica de `null` y la
  de `extracted_at` quedan decididas por
  [ADR 0027](../adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md),
  pero **nadie emite ni consume el bloque `inventory`**: depende de la fachada
  de M1, que no existe. **M4 como punto sigue abierto y bloqueante.**
- **M6 está decidido normativamente, no cerrado operacionalmente.** Su cierre
  depende de que exista la fachada que emita los campos y de que las pruebas
  contractuales demuestren conformidad.
- **La fachada Materiales–ELSA no existe.** No está solicitada, no está
  implementada, no está aprobada.
- **El subbloque 5.0.b está cerrado** normativa y documentalmente.
- **El subbloque 5.0.c no está iniciado** más allá de 5.0.c.1, que sí cerró.

---

## 14. Qué NO debe repetirse

Lista explícita de errores que una sesión futura, leyendo solo parte del
contexto, cometería con alta probabilidad.

| No hacer | Porque |
|---|---|
| **No reinstalar `llama.cpp` dando por hecho que falta** | Está integrado, documentado, con adaptador real, CLI, scripts y pruebas en CI (§4) |
| **No rediseñar el RAG existente** | Ingesta, chunking, embeddings, pgvector, canal léxico, RRF, context builder, política de generación, generación fundamentada, validador de citas y ausencia segura están implementados (§7) |
| **No volver a seleccionar el modelo local desde cero** | Phi-4-mini-instruct Q4_K_M está decidido en ADR 0018, comparado contra Qwen y restringido por los 4 GB de VRAM de PC1 (§5, §6) |
| **No interpretar ONNX como trabajo inexistente** | Hay ~3064 líneas reales en `claude/keen-curie-2xeh0r`, commit `61b3b42` (§11) |
| **No confundir la búsqueda HTTP actual con el RAG/LLM existente por CLI** | `/ask` hace búsqueda literal sobre el BOM publicado con plantillas de texto; el RAG completo solo es alcanzable por `elsa.tools.llm_runtime` (§7.2, §9) |
| **No volver a seleccionar el modelo de embeddings desde cero** | ADR 0015 decidió: EmbeddingGemma ganador técnico condicionado, BGE-M3 candidato productivo, Qwen3 descartado (§10) |
| **No dar `~2 GB` ni `~20 tok/s` como mediciones** | Son referencias sin procedencia versionada (§5.1, §6.2) |
| **No leer «CI en verde» como «el modelo funciona bien»** | CI usa un servidor falso que no carga pesos (§4.4) |
| **No cerrar M1, M4, M6 u M8 por asociación** | Solo M7 cerró, y solo M3/M5 están resueltos para V1 (§13) |
| **No leer «M4-NORMATIVO cerrado» como «M4 cerrado»** | M4 operativo sigue abierto y bloqueante: nadie emite ni consume el bloque `inventory` ([ADR 0027](../adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md) §22) |
| **No inferir nada de un `null` del contrato sin consultar su tabla** | `null` no tiene significado universal; `extracted_at: null` habla del contrato, no de SAP ([ADR 0027](../adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md) §5–§7) |

---

## 15. Evidencia faltante

Inventario consolidado de `NO_RECUPERADO`. Esta lista es el trabajo de
recuperación pendiente, no una lista de defectos a corregir ahora.

| # | Falta | Dónde se recuperaría |
|---|---|---|
| 1 | Hash del archivo GGUF de Phi-4-mini | PC1 |
| 2 | Tamaño exacto en bytes del GGUF | PC1 |
| 3 | Fecha y procedencia exacta de la descarga del GGUF | PC1 |
| 4 | Prompts exactos usados en la comparación Phi/Qwen | Irrecuperable salvo reejecución |
| 5 | Corpus comparativo de la evaluación Phi/Qwen | Irrecuperable salvo reconstrucción |
| 6 | Resultados completos de la comparación Phi/Qwen | Irrecuperable salvo reejecución |
| 7 | Línea base de nueve métricas del runtime de generación | Reejecución en PC1 |
| 8 | Origen y condiciones de la cifra `~20 tok/s` | Irrecuperable; medir de nuevo |
| 9 | Corrida medida del canal híbrido completo (RRF) | Reejecución con corpus real |
| 10 | Versión exacta del binario `llama-server` presente hoy en PC1 | PC1 |
| 11 | Estado de aplicabilidad del experimento ONNX sobre el `main` actual | Evaluación técnica |
| 12 | Evidencia versionada de PENDIENTE-019 (P210/Bogotá) | Fuera de este repositorio (SAP) |

> **Ninguno de estos huecos se corrige en este bloque.** Este documento los
> declara para que existan como trabajo reconocido en lugar de como silencio.

---

## 16. Referencias

- [`CLAUDE.md`](../../CLAUDE.md) — contrato del proyecto
- [`docs/architecture.md`](../architecture.md) — arquitectura, capas y fronteras
- [`docs/adr/`](../adr/) — las 26 decisiones arquitectónicas, autoridad normativa
- [`docs/llm-runtime.md`](../llm-runtime.md) — operación de `llama-server`
- [`docs/embedding-benchmark.md`](../embedding-benchmark.md) — banco de embeddings
- [`docs/hybrid-retrieval.md`](../hybrid-retrieval.md) — recuperación híbrida
- [`docs/rag-generacion.md`](../rag-generacion.md) — generación fundamentada
- [`docs/piloto-0-1/`](../piloto-0-1/) — contrato funcional y evidencia del piloto
- [`BLOCK_CLOSURE_STANDARD.md`](BLOCK_CLOSURE_STANDARD.md) — estándar de cierre
- [Mapa de entrega y continuidad](HANDOVER_AND_CONTINUITY_MAP.md) — documento hermano
