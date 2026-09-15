# Banco experimental de ONNX (Bloque 4.6)

> **Control experimental, no runtime productivo aprobado.**
>
> Nada de lo que hay aquí habilita ONNX Runtime para ELSA. Este banco existe
> para **medir** si ONNX reproduce el espacio vectorial de BGE-M3, no para
> servirlo. No hay adaptador productivo, no se registra ningún modelo, no se
> genera ningún vector de producción y no se toca la base de datos.

## La pregunta

Mismo `model_id` y misma `revision` **no** implican los mismos vectores. El
runtime, el orden de las operaciones, el pooling y la tokenización pueden
diferir sin que nada falle: el índice parecería correcto y ordenaría mal.

Este experimento demuestra o refuta la equivalencia en vez de suponerla.

## Las tres fases

| Fase | Qué compara | Estado |
|---|---|---|
| **1** | BGE-M3 PyTorch/SentenceTransformers FP32 **vs** BGE-M3 ONNX FP32 oficial | **implementada** (esto) |
| 2 | ONNX INT8 dinámico | **NO IMPLEMENTADA TODAVÍA** |
| 3 | Coexistencia con Phi en PC1 (RAM, latencia con el generador residente) | **NO IMPLEMENTADA TODAVÍA** |

La fase 1 **no aplica ningún umbral de aceptación**, y eso es deliberado:
primero hay que saber de qué tamaño es la diferencia. Fijar un umbral antes de
verla sería elegir el resultado.

## Lo que la fase 1 no hace

- No integra ONNX en FastAPI, ni en `HybridRetrievalService`, ni en
  `SemanticRetrievalService`.
- No crea un adaptador productivo ni un sidecar HTTP.
- No abre ninguna conexión a PostgreSQL ni usa Supabase.
- No lee `.env`, ni `elsa.config`, ni `elsa.container`.
- No modifica el corpus, el conjunto dorado, las métricas ni los resultados
  históricos de `bench/resultados/`.
- No descarga nada: si un archivo falta, dice cuál.

## Modelo y revisión

```
BAAI/bge-m3 @ 5617a9f61b028005a4858fdac845db406aefb181
```

La revisión está fijada en `PINNED_REVISION`
(`src/elsa/bench/onnx_experiment.py`). `CANDIDATES` del banco histórico sigue
declarando `main` y **no se toca**: cambiarla alteraría el banco que produjo
[ADR 0015](adr/0015-eleccion-del-modelo-de-embeddings.md) y volvería
incomparables las corridas registradas.

## Instalación

```bash
uv sync --extra bench-onnx     # onnxruntime + tokenizers, sin PyTorch
uv sync --extra bench          # sentence-transformers, para la referencia
```

Son extras **opcionales**. La suite del proyecto se ejecuta sin ninguno de los
dos: las pruebas del banco experimental usan dobles y no cargan BGE-M3.

`onnxruntime` depende de flatbuffers, numpy, packaging y protobuf;
`tokenizers`, de huggingface-hub. Ninguno arrastra PyTorch — que es
exactamente lo que el bloque quiere demostrar. Hay una prueba que lo comprueba
sobre `sys.modules` en un proceso limpio.

## Los artefactos ONNX

El repositorio de la revisión fijada publica `onnx/model.onnx` y
`onnx/model.onnx_data`. **Este banco no los descarga.** El operador los coloca
en una ruta local y la pasa explícitamente.

`model.onnx_data` es el archivo de pesos externo que acompaña a un `.onnx` de
más de 2 GB. ONNX Runtime lo resuelve **por su nombre y relativo al `.onnx`**:
tiene que estar al lado, y no se le pasa como argumento.

Ni uno ni otro entran en Git, y `.gitignore` los cubre: `*.onnx` no alcanzaba
a `model.onnx_data`, que es el grande de los dos.

### Comprobar qué hay en la caché local

```bash
uv run python -m elsa.bench.onnx_experiment inventory \
  --snapshot "<ruta al snapshot 5617a9f6...>"
```

Imprime, por archivo, si está y cuánto pesa. Devuelve 1 si falta algo
obligatorio. **Es el primer comando a ejecutar en PC1.**

## Cómo se ejecuta

Los dos runtimes **no se cargan a la vez**: PC1 tiene 8 GB y Phi ya es
residente. Cada captura carga uno, escribe sus vectores y termina.

```bash
# 1. Referencia: solo SentenceTransformers/PyTorch
uv run python -m elsa.bench.onnx_experiment capture \
  --runtime pytorch --out D:/elsa-exp/captura-pytorch.json

# 2. Candidato: solo ONNX Runtime
uv run python -m elsa.bench.onnx_experiment capture \
  --runtime onnx --snapshot "<ruta al snapshot>" \
  --out D:/elsa-exp/captura-onnx.json

# 3. Comparacion: no carga ningun modelo
uv run python -m elsa.bench.onnx_experiment compare \
  D:/elsa-exp/captura-pytorch.json D:/elsa-exp/captura-onnx.json \
  --out D:/elsa-exp/comparacion.json
```

La salida va **fuera del repositorio**, y preferiblemente fuera de OneDrive:
son volcados numéricos de decenas de megas y una carpeta sincronizada los
subiría a la nube.

Las capturas corren con `HF_HUB_OFFLINE=1` y `TRANSFORMERS_OFFLINE=1` en el
entorno del proceso, salvo que se pase `--allow-network`. No es una promesa
del README: es una variable que el propio comando fija.

### Por qué lote de 1 por defecto

`--batch-size 1`. Con un solo texto por lote no hay relleno, así que el
relleno no puede ser la explicación de una diferencia. Es más lento y es la
configuración correcta para **caracterizar**; medir rendimiento es otra cosa y
viene después.

## Qué se guarda de cada texto

| Campo | Para qué |
|---|---|
| `text_sha256`, `prefixed_text_sha256` | demostrar que los dos runtimes vieron el **mismo** texto |
| `input_ids`, `attention_mask` (completos y con su sha256) | comparar la tokenización token a token |
| `token_count`, `truncated` | detectar truncamientos distintos |
| `norm_before` | separar «el encoder calcula distinto» de «se normaliza distinto» |
| `norm_after` | comprobar que la normalización se aplicó |
| `vector_f32_b64` | el vector, en `float32` crudo |

El vector viaja en base64 y no como lista de decimales: un `repr` de coma
flotante y su lectura de vuelta introducirían una diferencia propia del
formato, del mismo tamaño que lo que se está midiendo.

## Qué compara el informe

**Tokenización.** Identificadores, máscara, longitud, tokens especiales,
truncamiento y la primera posición donde divergen. Es la explicación más
barata de descartar: si los identificadores difieren, lo que falla no es el
encoder sino la entrada.

**Vectores.** Por pareja: coseno, error absoluto medio, error absoluto máximo
y distancia L2. Resumidos en mínimo, media, mediana y máximo, con el ejemplo
responsable del peor caso por cada criterio. Los agregados se calculan en
`float64`; los vectores de origen siguen siendo `float32`.

**Recuperación.** Ranking con vectores del **mismo** runtime, siempre: nunca
documentos de uno con consultas del otro. La firma de `_rank_with` recibe
**una** captura, así que la mezcla no es posible por construcción, y hay una
prueba que fija esa firma.

Por consulta se guardan el top-10 de cada runtime con las puntuaciones **sin
redondear**, si cambió el primer resultado, si cambió el orden, qué entró y
qué salió del top-10, y en qué posición quedó cada chunk relevante.

Las métricas son las del banco histórico, sin tocar sus fórmulas: R@1, R@3,
R@5, R@10, MRR@10, nDCG@10, P@5, ejes y confusabilidad, calculadas por el
mismo `score_run` y el mismo `DenseRetriever`.

## Manifiesto: por qué no reutiliza la identidad histórica

`RunMetadata.identity()` del banco **no incluye el runtime**. Dos corridas del
mismo modelo con motores distintos declararían la misma identidad —es el mismo
punto ciego que tiene `elsa.embedding_models` en producción—, así que este
experimento escribe la suya:

```
model_id · revision · runtime · runtime_version · precision ·
execution_provider · pooling · normalization · dimension ·
document_prefix · query_prefix · composition_template ·
corpus_fingerprint · golden_fingerprint
```

Más las huellas y tamaños de `model.onnx`, `model.onnx_data`, el tokenizador y
las configuraciones, el sello de tiempo, la plataforma, la versión de Python y
la de NumPy.

**Este manifiesto no corrige la identidad productiva.** Ese es un trabajo
aparte, con su migración y su ADR, y este bloque no lo hace.

## Qué se rechaza, y por qué ruidosamente

El adaptador se detiene en vez de adaptarse:

- ninguna salida del grafo tiene la forma de estados por token → **para**; no
  se toma `outputs[0]`, y una salida ya agrupada (`pooler_output`,
  `sentence_embedding`) queda excluida por rango;
- dos salidas encajan → **para**, no adivina cuál;
- el grafo pide una entrada que no sabe construir → **para**;
- `sentence_bert_config.json` no declara `max_seq_length` → **para**, no
  inventa el truncamiento;
- un lote mezcla longitudes y no hay `pad_id` declarado → **para**;
- el vector no mide lo declarado, tiene NaN/Inf o norma cero → **para**, sin
  truncar ni rellenar.

Cada uno de esos casos, resuelto «con buena fe», produciría un vector
plausible de otro espacio vectorial. Un fallo ruidoso cuesta una ejecución;
uno silencioso cuesta un índice entero.

## Si el ONNX oficial no encaja

Si el grafo publicado no expone estados por token, o exige entradas que este
adaptador no construye, **eso es el hallazgo**, no un obstáculo que sortear.
Repórtalo y detente: adaptar el código a lo que haya es exactamente cómo se
fabrica un espacio vectorial equivocado que nadie detecta.

## Ver también

- [ADR 0015](adr/0015-eleccion-del-modelo-de-embeddings.md) — qué modelo, con qué condición y con qué banco
- [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) — identidad del espacio vectorial; generar no activa
- [`embedding-benchmark.md`](embedding-benchmark.md) — el banco histórico, su corpus y su conjunto dorado
- [`embeddings-operations.md`](embeddings-operations.md) — el runtime productivo, que este bloque **no** toca
