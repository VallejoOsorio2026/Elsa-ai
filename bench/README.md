# `bench/` — banco de pruebas del modelo de embeddings

Corpus y conjunto dorado **sintéticos**, y los informes que produce el banco.
Nada de aquí procede de PAPELSA.

| Ruta | Qué es |
|---|---|
| `corpus-sintetico/` | Documentos técnicos inventados y su manifiesto |
| `golden/queries.json` | 67 consultas con su expectativa y su motivo |
| `resultados/` | Último informe generado, en JSON y Markdown |

```bash
uv run python -m elsa.tools.embedding_benchmark --out bench/resultados
```

Cómo se mide, qué se midió y qué quedó sin medir:
[`docs/embedding-benchmark.md`](../docs/embedding-benchmark.md).

**El corpus privado no vive aquí.** Los manuales reales y las preguntas
reales de los ingenieros nunca se versionan (regla 12 del contrato); se leen
desde una ruta fuera del repositorio y solo su informe se cita.
