# Informe del banco de embeddings

Generado por `elsa.tools.embedding_benchmark`. Corpus y conjunto dorado
**sintéticos**: ningún dato de PAPELSA.

- Huella comparable: `c4306605c08d51ef67bf0763ccc323b7`
- Huella del corpus: `34bebb7167bcde2c16396118d616ebb3`
- Huella del conjunto dorado: `51171efcf7f93cca8776b63b38278bcc`

> Los ejes diagnósticos (códigos) **no** entran en la puntuación principal:
> los resuelve el canal léxico o estructurado del Bloque 4.3, no el vector.
> `confusion@5` mide **confusabilidad** del ranking, nunca autorización: el
> aislamiento lo impone el filtro de la consulta, que este banco no aplica
> a propósito para poder medir la confusión.

## 1. Puntuación principal

| Corrida | Consultas | R@1 | R@3 | R@5 | R@10 | MRR@10 | nDCG@10 | P@5 |
|---|---|---|---|---|---|---|---|---|
| lexical-bm25 | 59 | 0.661 | 0.658 | 0.763 | 0.822 | 0.742 | 0.709 | 0.244 |
| lexical-trigram | 59 | 0.373 | 0.508 | 0.669 | 0.847 | 0.556 | 0.591 | 0.220 |
| control-hashing-ngrams | 59 | 0.458 | 0.667 | 0.774 | 0.873 | 0.630 | 0.653 | 0.251 |

## 2. Por eje

| Eje | lexical-bm25 | lexical-trigram | control-hashing-ngrams |
|---|---|---|---|
| abbreviations (R@5) | 0.833 | 0.833 | 0.667 |
| ambiguity (R@5) | 0.833 | 0.833 | 1.000 |
| asset_confusion (R@5) | 0.875 | 1.000 | 1.000 |
| component_names (R@5) | 0.875 | 0.750 | 0.792 |
| cross_language (R@5) | 0.500 | 0.375 | 0.500 |
| failure_symptoms (R@5) | 1.000 | 0.750 | 1.000 |
| keyword (R@5) | 0.833 | 0.833 | 0.833 |
| narrative (R@5) | 0.500 | 0.375 | 0.875 |
| near_miss_document (R@5) | 1.000 | 1.000 | 0.833 |
| numbers_units (R@5) | 1.000 | 1.000 | 0.625 |
| preventive (R@5) | 0.667 | 0.667 | 1.000 |
| procedure (R@5) | 0.667 | 0.167 | 0.833 |
| safety (R@5) | 1.000 | 1.000 | 0.667 |
| section_reference (R@5) | 0.667 | 0.667 | 0.667 |
| synonyms (R@5) | 0.500 | 0.250 | 0.250 |
| typos (R@5) | 0.375 | 0.250 | 0.750 |
| version_confusion (R@5) | 1.000 | 0.833 | 1.000 |

## 3. Diagnóstico: códigos (no puntúa)

| Corrida | R@1 | R@5 | MRR@10 |
|---|---|---|---|
| lexical-bm25 | 1.000 | 1.000 | 1.000 |
| lexical-trigram | 1.000 | 1.000 | 1.000 |
| control-hashing-ngrams | 1.000 | 1.000 | 1.000 |

## 4. Confusabilidad y abstención

| Corrida | confusion@5 | Abstención |
|---|---|---|
| lexical-bm25 | 0.210 | 0.000 |
| lexical-trigram | 0.186 | 1.000 |
| control-hashing-ngrams | 0.148 | 0.000 |

## 5. Coste y hardware

Depende de la máquina; no se compara como calidad.

| Corrida | Runtime | Disp. | Dim. | Corpus (s) | p50 (ms) | p95 (ms) | RSS pico (MB) | Carga (s) | MB/1000 chunks |
|---|---|---|---|---|---|---|---|---|---|
| lexical-bm25 | pure-python | cpu | 0 | 0.013 | — | — | 34.6 | — | — |
| lexical-trigram | pure-python | cpu | 0 | 0.026 | — | — | 34.6 | — | — |
| control-hashing-ngrams | pure-python | cpu | 256 | 0.011 | 0.05 | 0.08 | 34.6 | — | 0.98 |

Máquina: Intel(R) Xeon(R) Processor @ 2.80GHz · 15.7 GB RAM · GPU: none

## 6. Candidatos SIN MEDIR

Un candidato sin medir **no se descarta ni se elige**. No se sustituye
por puntuaciones públicas: no son comparables con esta medición.

| Candidato | Motivo |
|---|---|
| `BAAI/bge-m3` | sentence-transformers is not installed; it is an optional dependency of the benchmark only. See docs/embedding-benchmark.md |
| `Qwen/Qwen3-Embedding-0.6B` | sentence-transformers is not installed; it is an optional dependency of the benchmark only. See docs/embedding-benchmark.md |
| `google/embeddinggemma-300m` | sentence-transformers is not installed; it is an optional dependency of the benchmark only. See docs/embedding-benchmark.md |

## Notas de la medición

- abstention is only comparable between retrievers on the same score scale: cosine over normalised vectors is bounded to [-1, 1] while BM25 is not, so a fixed threshold means different things for each
- abstention measured over 4 queries with no expected answer, threshold 0.35
- confusion@5 measures ranking confusability, never authorisation: isolation is enforced by the query filter, which this benchmark deliberately does not apply
- diagnostic axes are excluded from the primary score: exact codes are for the lexical or structured channel of block 4.3, not for the dense vector
