# Bloque 4.3 — recuperación híbrida de evidencia

Tres canales y una fusión explícita, entre la pregunta y la evidencia:

```
consulta → señales exactas → exacto ∥ léxico ∥ semántico → RRF → evidencia
```

**No redacta respuestas.** Entrega pasajes autorizados con su procedencia y con
el rastro de qué canal los trajo. Componer la respuesta es el bloque siguiente.

## Los tres canales, y por qué son tres

| Canal | Qué resuelve | Cómo |
|---|---|---|
| **Exacto** | Códigos, referencias, identificadores | Coincidencia literal con frontera de palabra |
| **Léxico** | Nombres técnicos, componentes, palabras | `to_tsvector('spanish')` + `ts_rank_cd` |
| **Semántico** | Sinónimos, paráfrasis, otro idioma | BGE-M3 → vecino más cercano exacto |

El canal exacto no es un lujo, y la razón es medible. La configuración
`spanish` **parte los identificadores**:

```sql
select to_tsvector('spanish', 'rodamiento SAP-4471');
-- 'rodamient':1 'sap':2 '-4471':3
```

Buscar `SAP-4471` por texto completo devolvería cualquier pasaje que hable de
SAP y cualquiera que mencione 4471, mezclados. Para un identificador eso no es
recuperación, es ruido. Por eso los códigos se detectan con una **regla**
—`core.query_signals`, sin modelo: un código resuelto por un LLM dependería de
la temperatura del muestreo— y se buscan literales.

Para la prosa, en cambio, la lematización española es justo lo que hace falta:
`to_tsvector('spanish','lubricación de rodamientos') @@ plainto_tsquery('spanish','lubricar rodamiento')`
es verdadero.

Esto era predecible con lo que ya midió 4.2.a: **BM25 ganó a los tres modelos
densos en `component_names`** (0,875 frente a 0,667 de EmbeddingGemma), y
ningún denso aportó nada en `codes`, donde todos los recuperadores aciertan al
100 %. El canal léxico no sobra.

## Fusión: RRF, y por qué no una suma de puntuaciones

`ts_rank_cd` y la distancia coseno **no comparten escala, ni rango, ni
significado**. Sumarlos obligaría a inventar pesos y a recalibrarlos cada vez
que cambie el modelo. Reciprocal Rank Fusion usa solo la **posición**, que sí
es comparable:

```
score(chunk) = Σ 1 / (k + posición_en_ese_canal)
```

**`k = 60` es provisional para el MVP**, no un óptimo demostrado. Es el valor
convencional de la propuesta original de RRF, y se deja fijo y declarado **en
vez de ajustarlo contra el conjunto dorado**: 67 consultas sintéticas no bastan
para calibrar un hiperparámetro sin sobreajustarlo, y un 60 documentado es más
defendible que un número elegido porque subía el Recall. No se hizo grid search
ni se ajustaron pesos. Las condiciones bajo las cuales se reevaluará están en
[ADR 0016](adr/0016-recuperacion-hibrida-del-mvp.md) §9.

La fusión conserva el canal de origen, la posición que dio cada canal y su
puntuación propia; **no duplica** un chunk encontrado por dos canales, suma su
aportación. Y una coincidencia exacta inequívoca **encabeza**: si el pasaje
contiene literalmente el código que se preguntó, ninguna señal semántica
mediocre lo desplaza.

## Seguridad: el alcance vive dentro de cada canal

**Los tres canales reciben los alcances autorizados y los aplican en su propia
consulta SQL.** Nunca se recupera de todo el corpus para filtrar al fusionar:
un pasaje prohibido no llega a entrar en la fusión, así que no puede desplazar
a uno permitido ni colarse por un fallo de la última etapa.

La semántica es la de `core.authorization.covers`: un permiso sin equipo cubre
todo su dominio; uno con equipo cubre solo ese equipo. Sin alcances no se
devuelve «todo», se devuelve nada.

## Evidencia suficiente, débil o nula

Deliberadamente **no hay un umbral numérico**. Fijarlo exigiría medirlo sobre
consultas reales de planta, que todavía no existen, y un umbral inventado se
acabaría citando como si estuviera calibrado.

| Fuerza | Cuándo |
|---|---|
| `sufficient` | Coincidencia literal del identificador, **o** varios canales coinciden en el mismo pasaje |
| `weak` | Un solo canal, sin refuerzo. Se entrega, marcado |
| `none` | Ningún canal devolvió nada dentro del alcance autorizado |

Los dos criterios de `sufficient` son **hechos observables**, no puntuaciones.
La política de responder o callar es del bloque de RAG, con estas señales
delante.

## Sin migración

Nada de esto necesitó tocar el esquema. `spanish` viene en el núcleo de
PostgreSQL: sin extensión, sin columna `tsvector`, sin índice GIN. El
`to_tsvector` se calcula al vuelo, por el mismo razonamiento que mantiene
exacta la búsqueda vectorial: el piloto es del orden de 10³–10⁴ chunks
(ADR 0013 §6). Cuando el volumen lo justifique, el índice será su propia
migración con su propia medición.

## Uso

```bash
uv run python -m elsa.tools.embeddings_admin hybrid-search \
    "¿cada cuánto se lubrica el SAP-4471?" \
    --scope mantenimiento:asset-a --limit 5
```

Muestra el ranking final, qué canales encontraron cada pasaje con su posición y
puntuación, el `rrf`, y la cita completa.

## Lo que se midió, y hasta dónde vale

La comparación **BM25 vs BGE-M3 vs híbrido** sobre el conjunto dorado se
ejecutó en PC1, donde el modelo está en caché:

```bash
uv run python -m elsa.tools.embedding_benchmark --candidates bge-m3 --fusion \
    --out bench/resultados/hibrido
```

| Corrida | R@1 | R@5 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| `lexical-bm25` | 0,661 | 0,763 | — | 0,742 | 0,709 |
| `dense:BAAI/bge-m3` | 0,678 | **0,893** | — | 0,783 | 0,783 |
| `fusion-rrf(bm25+bge-m3,k=60)` | **0,729** | 0,801 | **0,975** | **0,800** | **0,800** |

La fusión gana en R@1, MRR@10 y nDCG@10, y **pierde en R@5** frente al canal
denso solo. El mecanismo está identificado: con `k = 60` sobre listas de
profundidad 10, un solo canal aporta entre `1/61` y `1/70` —un factor 1,148 de
extremo a extremo— mientras que un chunk hallado por **ambos** canales, aunque
sea en la última posición, aporta `2/70`. **Cualquier pasaje en el que los dos
canales coincidan supera a uno que un solo canal puso primero.** RRF con este
`k` premia el consenso por encima de la convicción.

**El banco no es el juez de producción.** Contiene `@v1` y `@v2` del mismo
manual a la vez —13 de 42 chunks son `@v2`— y **no** aplica alcance ni estado
de publicación, porque su función es medir confusabilidad y un filtro puesto la
haría inmedible (ADR 0014). Producción hace lo contrario: filtra alcance
autorizado y versión publicada **dentro de cada canal, antes del ranking**.

Retirando las entradas `@v2` de los rankings ya persistidos y recalculando —sin
reejecutar ningún modelo, sobre las mismas 59 consultas puntuables— con **el
mismo `k = 60`**:

| Corrida | R@1 | R@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|
| `lexical-bm25` | 0,661 → 0,661 | 0,763 → 0,809 | 0,742 → 0,763 | 0,709 → 0,739 |
| `control-hashing-ngrams` | 0,458 → 0,610 | 0,774 → 0,847 | 0,630 → 0,739 | 0,653 → 0,734 |
| `fusion-rrf(bm25+control,k=60)` | 0,559 → **0,661** | 0,750 → **0,898** | 0,710 → 0,782 | 0,713 → 0,770 |

Es un **análisis de sensibilidad, no el benchmark oficial**: aproxima con un
filtro posterior algo que producción aplica antes. Pero muestra que buena parte
de la degradación atribuida a RRF es la duplicación `v1`/`v2` que el banco
introduce a propósito. Por eso `k` **no se toca**: ver
[ADR 0016](adr/0016-recuperacion-hibrida-del-mvp.md).

**La fusión no reejecuta nada.** Toma las posiciones que cada corrida ya produjo
y les aplica el mismo RRF con la misma constante, así que medir el híbrido no
cuesta una segunda pasada de inferencia ni puede dar un resultado distinto al
del canal que fusiona.

### Qué guarda el informe, y por qué

`informe.json` conserva los **rankings por consulta** de cada corrida, no solo
los promedios. Un promedio dice que algo empeoró; no dice **cuál** consulta ni
por qué, y sin eso auditar una fusión obliga a volver a ejecutar el modelo.

El conjunto dorado —texto, eje, `must_retrieve` y `must_not_retrieve`— se
escribe **una sola vez** bajo `golden`, y los rankings solo cruzan por
`query_id`: repetirlo por corrida multiplicaría el archivo por el número de
recuperadores sin añadir un dato.

```json
{
  "golden": {"fingerprint": "...", "queries": [{"id": "...", "text": "...",
             "axis": "synonyms", "must_retrieve": {"chunk": 2}, "must_not_retrieve": []}]},
  "runs": [{"metadata": {...}, "scoreboard": {...},
            "rankings": [{"query_id": "...",
                          "ranked": [{"rank": 1, "chunk_id": "...", "score": 2.85}]}]}]
}
```

Junto a él se escribe `diagnostico.md`, que muestra para cada consulta qué puso
primero cada corrida y en qué posición quedó lo esperado. **Presenta los datos;
no saca conclusiones.**

### Abstención de una fusión: `N/A`, no un número

El banco mide abstención con un umbral fijo sobre la puntuación del primer
resultado. Ese umbral **no significa nada sobre una suma de recíprocos**: el
valor máximo posible de RRF con dos canales y `k=60` es `2/61 ≈ 0,033`, así que
toda consulta sin respuesta quedaría por debajo de cualquier umbral pensado
para coseno y el resultado sería `1,000` — un artefacto, no una medición.

Una corrida de fusión reporta `abstention_rate = null` y `N/A — no calibrada`.
No se inventa un umbral: RRF no puntúa similitud. Para los recuperadores donde
el umbral sí tiene el significado que tenía, nada cambia.

### Identidad auditable

Cada fusión se nombra con lo que fusiona y con la constante —
`fusion-rrf(lexical-bm25+BAAI/bge-m3,k=60)` — en el JSON, en el Markdown, en
las tablas por eje y en las de coste. Antes las dos fusiones aparecían ambas
como `fusion-rrf(k=60)` y distinguirlas exigía conocer el orden de ejecución.

Sin red, con el control determinista en lugar del modelo denso, se comprueba
además que **la fusión es reproducible** y que RRF **diluye cuando un canal es
débil**: fusionar BM25 con el control baja `recall@1` de 0,661 a 0,559.

## Estado al cerrar el Bloque 4.3

La recuperación queda **congelada** y el bloque de RAG la recibe así:

| Pieza | Estado |
|---|---|
| Canal exacto con prioridad determinista sobre RRF | Cerrado |
| Canal léxico PostgreSQL (`spanish`, `ts_rank_cd`) | Cerrado |
| Canal semántico BGE-M3 | Cerrado |
| Fusión RRF | Cerrada |
| `k = 60` | **Provisional**, no óptimo declarado |
| Alcance, autorización y versión publicada **antes** del ranking de cada canal | Cerrado, innegociable |
| Pesos por canal, *champion guarantee*, reranker, ANN, heurísticas nuevas | **No implementados**, y no por descuido |
| Umbral de abstención de RRF | **No existe**, y no se inventa |

Lo que el bloque de RAG hereda son **señales observables** —coincidencia
literal del identificador, acuerdo entre canales, ausencia total de resultados
dentro del alcance autorizado— con las que decidir si responde o calla. **No
debe fabricar un umbral numérico sobre la puntuación RRF** para esa decisión:
si alguna vez hace falta uno, se calibra sobre consultas reales de planta y se
registra en su propio ADR.

## Ver también

- [ADR 0016](adr/0016-recuperacion-hibrida-del-mvp.md) — cierre de 4.3: por qué `k = 60` se mantiene y qué no se implementa

- [ADR 0014](adr/0014-confusabilidad-no-es-autorizacion.md) — el aislamiento lo aplica el retrieval
- [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) §6 — por qué la búsqueda es exacta
- [ADR 0015](adr/0015-eleccion-del-modelo-de-embeddings.md) — `component_names` y el canal léxico
- [`embedding-benchmark.md`](embedding-benchmark.md) — el banco y sus ejes
