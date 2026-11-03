# Evaluación de R1 — corpus PR-100

`evaluacion.json` contiene las 15 preguntas con las que R1.D medirá el camino
RAG real (recuperación híbrida, BGE-M3 y Phi) sobre el corpus sintético de
`bench/corpus-sintetico/`. **Todo es inventado**: ningún dato de PAPELSA.

## Escenario

| | |
|---|---|
| Alcance de las preguntas | `mantenimiento:prensa-ejemplo` |
| Publicados en el alcance | `prensa-manual` v1 y `prensa-nota-en` v1 |
| Pendiente (no debe verse) | `prensa-manual` v2 |
| Publicado fuera del alcance (no debe verse) | `bomba-manual` v1, en el activo `bomba-ejemplo` |

La secuencia que deja la base así está en
[`docs/r1-b-operacion-ingesta.md`](../../docs/r1-b-operacion-ingesta.md).

## Campos de cada pregunta

| Campo | Significado |
|---|---|
| `category` | `direct`, `combination`, `no_answer`, `ambiguity`, `isolation` o `version` |
| `origin` | Id de `bench/golden/queries.json` del que deriva, o `null` si es nueva |
| `expected_status` | `answered` o `no_evidence` (`AnswerStatus` de `core/answers.py`) |
| `reference_answer` | Lo que una respuesta correcta debe decir |
| `evidence_anchors` | Texto **literal** de la fuente que sostiene la respuesta |
| `expected_citations` | Chunks que la respuesta debería citar |
| `must_not_cite` | Chunks que nunca deben aparecer: otra versión u otro activo |
| `forbidden_values` | Cifras o términos que delatan una confusión si aparecen en la respuesta |
| `known_limitation` | Solo en `ambiguity`: ELSA no tiene aún un estado de aclaración |

Las claves de cita tienen la forma
`<código del documento>@v<número de versión>#<clave estructural del chunk>`, la
misma que usa el banco de embeddings.

## Qué está comprobado y qué no

`tests/test_documents_admin.py` carga el corpus con la CLI real
(`elsa.tools.documents_admin`) y comprueba:

- que cada cita esperada existe, está publicada y es de la prensa;
- que cada cita prohibida existe y queda fuera de lo publicado en el alcance;
- que cada ancla de evidencia aparece en el texto de las citas esperadas, sin
  distinguir mayúsculas ni tildes.

Eso valida las respuestas de referencia contra los documentos. **No** mide
todavía ninguna respuesta de ELSA: eso es R1.D.
