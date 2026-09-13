# ADR 0016 — Recuperación híbrida del MVP: tres canales, RRF y `k = 60` provisional

- Estado: **aceptado**
- Bloque: 4.3 — cierre
- Fija la arquitectura de recuperación con la que el MVP entra al bloque de RAG
- Deriva de [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md) §6
  (filtros obligatorios, búsqueda exacta), de
  [ADR 0014](0014-confusabilidad-no-es-autorizacion.md) (el aislamiento lo
  aplica el retrieval, el banco mide confusabilidad) y de
  [ADR 0015](0015-eleccion-del-modelo-de-embeddings.md) (BGE-M3 como candidato
  productivo)
- Detalle de implementación en
  [`hybrid-retrieval.md`](../hybrid-retrieval.md)

## Contexto

El Bloque 4.3 entregó tres canales de recuperación y una fusión explícita. Al
cerrarlo hay una medición real sobre el conjunto dorado sintético, ejecutada en
PC1 con BGE-M3, que **no es unánime**:

| Corrida | R@1 | R@5 | R@10 | MRR@10 | nDCG@10 |
|---|---|---|---|---|---|
| `lexical-bm25` | 0,661 | 0,763 | — | 0,742 | 0,709 |
| `dense:BAAI/bge-m3` | 0,678 | 0,893 | — | 0,783 | 0,783 |
| `fusion-rrf(bm25+bge-m3,k=60)` | **0,729** | 0,801 | **0,975** | **0,800** | **0,800** |

La fusión gana en R@1, MRR@10 y nDCG@10, y **pierde en R@5 frente al canal
denso solo** (0,801 contra 0,893). El análisis consulta por consulta —posible
porque los rankings ya se persisten— confirmó el mecanismo: con `k = 60` sobre
listas de profundidad 10, el rango de aportación de un solo canal es apenas
`1/61 … 1/70`, es decir un factor 1,148, mientras que un chunk hallado por
**ambos** canales en la peor posición aporta `2/70`. Cualquier pasaje que los
dos canales encuentren, aunque sea en último lugar, supera a uno que un solo
canal puso primero. **RRF con este `k` premia el consenso por encima de la
convicción.**

La tentación evidente es corregir `k`. Y es precisamente la que hay que
resistir, por una razón que no es de prudencia sino de validez: **el banco no
mide lo que producción hace**.

El corpus sintético contiene a propósito `@v1` y `@v2` del mismo manual
simultáneamente —13 de 42 chunks son `@v2`— porque su función es medir
**confusabilidad** entre versiones y activos parecidos (ADR 0014). Por la misma
razón **no aplica alcance ni estado de publicación**: si los aplicara, los
pasajes confundibles nunca entrarían al ranking y la confusión sería inmedible
por construcción. El banco es **adversarial por diseño**.

Producción hace justo lo contrario: filtra alcance autorizado y versión
publicada **dentro de cada canal, antes del ranking**. Un usuario del piloto
nunca verá `@v1` y `@v2` compitiendo en la misma lista.

Así que el banco y producción no ven el mismo corpus efectivo, y calibrar un
hiperparámetro de producción contra el banco global significaría ajustarlo
contra duplicados que producción ya elimina.

### Análisis de sensibilidad: qué pasa si se retiran los duplicados

Sobre los **rankings ya persistidos**, sin reejecutar ningún modelo, se puede
retirar toda entrada `@v2` y recalcular. Eso no es el benchmark oficial —es una
simulación aproximada de un filtro que producción aplica antes, no después— pero
sí dice de dónde viene la degradación.

Ejecutado en este repositorio con las líneas base y el control determinista
(sin BGE-M3, que este entorno no puede descargar), sobre las mismas 59 consultas
puntuables:

| Corrida | R@1 | R@5 | MRR@10 | nDCG@10 |
|---|---|---|---|---|
| `lexical-bm25` | 0,661 → 0,661 | 0,763 → **0,809** | 0,742 → 0,763 | 0,709 → 0,739 |
| `control-hashing-ngrams` | 0,458 → 0,610 | 0,774 → **0,847** | 0,630 → 0,739 | 0,653 → 0,734 |
| `fusion-rrf(bm25+control,k=60)` | 0,559 → **0,661** | 0,750 → **0,898** | 0,710 → 0,782 | 0,713 → 0,770 |

Ninguna consulta sale del promedio al filtrar (`n = 59` antes y después), así que
la comparación es directa. Con **el mismo `k = 60`**, la fusión pasa de perder
contra BM25 en R@1 a igualarla, y de 0,750 a 0,898 en R@5 — por encima de ambos
canales. El operador reporta el mismo comportamiento en PC1 al repetir el
ejercicio sobre los rankings de BGE-M3; **ese resultado no está versionado en
este repositorio y no se recoge aquí como cifra**.

La lectura es que **una parte sustancial de la degradación atribuida a RRF es
en realidad la duplicación `v1`/`v2` que el banco introduce a propósito y que
producción no tiene**. Cambiar `k` para compensar un artefacto del banco sería
corregir el algoritmo por un defecto del instrumento.

## Decisión

### 1. El MVP mantiene la arquitectura entregada, sin ajustes

| Componente | Estado |
|---|---|
| Canal **exacto** con prioridad determinista | Se mantiene |
| Canal **léxico** PostgreSQL (`spanish`, `ts_rank_cd`) | Se mantiene |
| Canal **semántico** BGE-M3 | Se mantiene |
| Fusión **RRF** | Se mantiene |
| **`k = 60`** | Se mantiene, **provisional** |
| Alcance, autorización y versión publicada filtrados **antes** del ranking de cada canal | Se mantiene, **innegociable** |

### 2. `k = 60` es provisional, no óptimo

`60` es el valor convencional de la propuesta original de RRF. Se adopta
**declarado como provisional para el MVP**: no se afirma que sea el mejor valor
para este dominio, ni se ha demostrado que lo sea. Es un punto de partida
defendible y trazable, no una constante validada.

### 3. `k` no fue calibrado contra las 67 consultas, y no debe serlo

67 consultas sintéticas no bastan para fijar un hiperparámetro sin
sobreajustarlo. Elegir `k` por cuál da mejor número sobre este conjunto
produciría una constante que describe el conjunto dorado, no el problema.

**No se hizo grid search, no se ajustaron pesos, y no se eligió ningún valor
mirando la métrica resultante.**

### 4. El banco global es adversarial y no es el juez de producción

Mide también confusabilidad, contiene versiones simultáneas y **no aplica
alcance ni publicación**. Sus números son válidos para lo que mide —comparar
recuperadores en condiciones duras e idénticas— y **no** son válidos para
ajustar parámetros de producción ignorando los filtros que producción sí
aplica.

Queda prohibido, sin un ADR nuevo, usar el banco global como justificación para
cambiar `k`, introducir pesos o alterar el orden de los canales.

### 5. Qué **no** se implementa en este bloque

Ninguna de estas opciones se descarta para siempre; se descartan **ahora**, por
falta de una medición que las justifique sobre datos representativos:

- cambio de `k`;
- pesos por canal;
- *champion guarantee* (garantizar la entrada del primero de cada canal);
- reranker neuronal;
- índices ANN (HNSW, IVFFlat);
- heurísticas de ranking nuevas.

### 6. La coincidencia exacta conserva prioridad determinista sobre RRF

Si un pasaje contiene literalmente el identificador preguntado, encabeza el
resultado. Esa prioridad **no** es una aportación a la suma de recíprocos que
otra señal pueda superar: es una regla previa. Un código de repuesto resuelto
por semejanza semántica es un error caro en planta, y la regla lo impide por
construcción, no por puntuación.

### 7. RRF no tiene umbral de abstención calibrado

Una fusión RRF reporta `abstention_rate = null` y `N/A — no calibrada`. El
umbral del banco está pensado para una **similitud**; RRF suma recíprocos, cuyo
máximo con dos canales y `k = 60` es `2/61 ≈ 0,033`. Aplicárselo marcaría el
100 % de las consultas como abstenidas: un artefacto, no una medición.

**No se inventa un umbral para RRF.**

### 8. La suficiencia de evidencia la decide el bloque de RAG, sin inventar un umbral

El bloque siguiente recibe señales **observables** —coincidencia literal del
identificador, acuerdo entre canales, ausencia total de resultados en el
alcance autorizado— y decide con ellas si responde o calla.

No debe fabricar un umbral numérico sobre la puntuación RRF para esa decisión.
Si en algún momento hace falta un umbral, se calibra sobre consultas reales de
planta y se registra en su propio ADR.

### 9. Cuándo se reevalúa el ranking

La siguiente revisión de `k`, de los pesos y del orden de los canales se hará
**solo** con estas cinco condiciones a la vez:

1. corpus real de Tampella, no sintético;
2. únicamente versiones **publicadas**, como en producción;
3. alcances de autorización **reales**, aplicados dentro de cada canal;
4. consultas del **piloto**, formuladas por los ingenieros de mantenimiento;
5. **rankings persistidos**, para poder auditar consulta por consulta sin
   reejecutar los modelos.

Con menos que eso, la reevaluación repetiría el error que este ADR evita.

## Consecuencias

- El MVP entra al bloque de RAG con una recuperación **congelada y documentada**,
  no con una en ajuste.
- Se acepta conscientemente que `fusion-rrf` quede por debajo del canal denso en
  R@5 sobre el banco global. El análisis de sensibilidad indica que esa
  diferencia se debe en buena parte a duplicados que producción no tiene, y
  R@10 = 0,975 muestra que es un problema de **orden**, no de candidatos: lo que
  hace falta está casi siempre dentro de los diez primeros.
- Cualquier cambio futuro en el ranking nace con una medición representativa
  detrás, o no nace.
- El artefacto de la corrida híbrida real de PC1 **no está versionado**. Hasta
  que lo esté, las cifras de la tabla de Contexto se sostienen en el reporte del
  operador, no en un archivo de este repositorio.

## Alternativas descartadas

**Ajustar `k` a la profundidad de las listas.** Es la corrección técnicamente
correcta al mecanismo descrito en Contexto, y sigue sobre la mesa. Se descarta
**ahora** porque la única evidencia disponible para elegir el nuevo valor es el
banco adversarial, y el análisis de sensibilidad sugiere que buena parte del
problema que corregiría desaparece sola al aplicar los filtros de producción.
Cambiar el algoritmo por un defecto del instrumento es la peor de las dos
opciones.

**Garantizar la entrada del primero de cada canal.** Resolvería el caso concreto
sin tocar `k`, pero añade una regla de ranking cuyo efecto no está medido en
ninguna condición realista, y el MVP no necesita más piezas sin medir.

**Sustituir RRF por una suma ponderada.** Exigiría inventar pesos entre
`ts_rank_cd` y distancia coseno, que no comparten escala ni significado, y
recalibrarlos con cada cambio de modelo. RRF usa solo la posición, que sí es
comparable entre canales.

**Declarar `k = 60` como valor definitivo.** Sería afirmar una optimalidad que
nadie midió. La diferencia entre «convencional y provisional» y «óptimo» es
justo la que impide que dentro de un año alguien lo cite como validado.

## Ver también

- [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md) §6 — por qué la búsqueda es exacta y los filtros obligatorios
- [ADR 0014](0014-confusabilidad-no-es-autorizacion.md) — el banco mide confusabilidad; el aislamiento lo aplica el retrieval
- [ADR 0015](0015-eleccion-del-modelo-de-embeddings.md) — BGE-M3 como candidato productivo; `component_names` y el canal léxico
- [ADR 0012](0012-ciclo-de-vida-documental-propio.md) — qué significa que una versión esté publicada
- [`hybrid-retrieval.md`](../hybrid-retrieval.md) — implementación de los tres canales y la fusión
- [`embedding-benchmark.md`](../embedding-benchmark.md) — el banco, sus ejes y sus límites
