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

`k = 60`, el valor convencional de la propuesta original. **Se deja fijo y
declarado en vez de ajustarlo contra el conjunto dorado**: 67 consultas no
bastan para calibrar un hiperparámetro sin sobreajustar, y un 60 documentado es
más defendible que un número elegido porque subía el Recall.

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

## Qué falta medir, y por qué

La comparación **BM25 vs BGE-M3 vs híbrido** sobre el conjunto dorado **no se
pudo completar** con los artefactos existentes. Los informes de 4.2.a guardan
solo métricas agregadas, no los **rankings por consulta**, y RRF necesita las
listas ordenadas de cada canal. Fusionar fuera de línea es por tanto imposible
sin volver a ejecutar BGE-M3.

`FusionRetriever` deja la comparación a un comando en una máquina con el modelo
en caché. Lo que sí se comprobó aquí, con el control determinista en lugar del
modelo denso, es que **la fusión es reproducible** y que RRF **diluye cuando un
canal es débil**: fusionar BM25 con el control baja `recall@1` de 0,661 a
0,559. Es un aviso concreto y no una medición del híbrido real: dice que el
canal semántico tiene que aportar de verdad para que la fusión gane, no que
BM25+BGE-M3 vaya a comportarse así.

## Ver también

- [ADR 0014](adr/0014-confusabilidad-no-es-autorizacion.md) — el aislamiento lo aplica el retrieval
- [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) §6 — por qué la búsqueda es exacta
- [ADR 0015](adr/0015-eleccion-del-modelo-de-embeddings.md) — `component_names` y el canal léxico
- [`embedding-benchmark.md`](embedding-benchmark.md) — el banco y sus ejes
