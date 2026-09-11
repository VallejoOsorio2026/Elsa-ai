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

El informe por defecto se escribe en `resultados/`, que **sí** se versiona:
es la evidencia del bloque. Su sección de coste depende de la máquina, así
que un diff ahí entre dos máquinas es esperable y no una regresión; la parte
comparable tiene su propia huella.

**El corpus privado todavía no se puede correr.** Los manuales reales y las
preguntas reales de los ingenieros nunca se versionan (regla 12 del
contrato), y la herramienta aún **no** acepta una ruta de corpus alternativa:
solo lee `corpus-sintetico/`. Cuando se añada, el informe de una corrida
privada tendrá que escribirse con `--out` fuera del repositorio.
