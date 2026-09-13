# Resultados del banco de embeddings

Un archivo por corrida. Ninguno se sobrescribe: cada medición nueva se añade.

| Archivo | Qué contiene | Máquina |
|---|---|---|
| `informe.json` · `informe.md` | **Etapa A.** Solo líneas base: BM25, trigramas y el control determinista. Es el informe que produce el banco sin red ni GPU, y el que corre en CI | Contenedor Linux, sin GPU |
| `bge-m3-informe.json` | **Etapa B.** `BAAI/bge-m3` más las tres líneas base | PC1 · Windows · Python 3.12.13 · CPU AMD64 · sin GPU |
| `qwen3-0.6b-informe.json` | **Etapa B.** `Qwen/Qwen3-Embedding-0.6B` más las tres líneas base | idem |
| `embeddinggemma-300m-informe.json` | **Etapa B.** `google/embeddinggemma-300m` más las tres líneas base | idem |

## Por qué las tres corridas de la etapa B son comparables

Cada informe de la etapa B incluye **las mismas tres líneas base** junto a su
candidato, y las tres reproducen cifras idénticas en los tres archivos. Eso, más
la coincidencia de `corpus_fingerprint` (`34bebb71…`), `golden_fingerprint`
(`51171efc…`) y `composition_template` (`context-v1`), es lo que demuestra que
se midió lo mismo de la misma forma.

`comparison_fingerprint` **sí difiere** entre los tres archivos, y debe hacerlo:
cada uno contiene un candidato denso distinto.

La lectura de estos resultados y la decisión que se tomó con ellos están en
[ADR 0015](../../docs/adr/0015-eleccion-del-modelo-de-embeddings.md).

## Qué no hay aquí, y no es un olvido

Ni pesos de modelos, ni cachés de HuggingFace, ni credenciales, ni datos reales
de PAPELSA. Estos archivos son solo métricas y metadatos de ejecución.
