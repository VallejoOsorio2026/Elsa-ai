# Cierre del subbloque de implementación B9a + B9b + B9c — Cobertura de inventario como garantía ejecutable

Documento de cierre redactado según
[el estándar de cierre de bloques](project/BLOCK_CLOSURE_STANDARD.md)
(`CLAUDE.md`, regla 26).

> **Qué cierra este documento y qué no.**
>
> Cierra **únicamente** el subbloque de implementación de las tres puertas
> operativas **B9a**, **B9b** y **B9c** que
> [ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) §14 puso en
> lugar de M8: el requisito tipado de cobertura, los dos avisos de la
> taxonomía y las pruebas A20, A20b y A21 activas en integración continua.
>
> **NO** cierra **M8**, que sigue **ABIERTO**. **NO** cierra el subbloque
> **5.0.b**. **NO** cierra el subbloque **5.0.c**. **NO** cierra el **Bloque
> 5.0**. **NO** declara operativo el **Piloto 0.1**. **NO** declara cobertura
> `KNOWN_COMPLETE` ni aporta ningún mecanismo para demostrarla.

> **Numeración.** El corpus asigna el identificador **5.0.c.2** a
> [ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md), que es la
> **decisión normativa**. El corpus **no asigna** un número de subbloque a
> este trabajo de **implementación**, y este documento **no inventa uno**: se
> identifica por lo que cierra, B9a–B9c.

Marcas de evidencia usadas, según el estándar: **HECHO MEDIDO**, **HECHO DEL
REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.

---

## 1. Objetivo

[ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) retiró **M8**
de la lista de bloqueantes del
[contrato funcional](piloto-0-1/contrato-funcional.md) §10 y puso **tres
condiciones propias de ELSA** en su lugar. Ese ADR **no implementó ninguna**, y
lo dijo: «fijarlas es su objeto; construirlas es trabajo posterior».

La capacidad que debía quedar disponible al terminar este subbloque es una
sola, y es la que sostiene toda la decisión de ADR 0023:

> **Ninguna respuesta de ELSA puede depender de una cobertura de inventario
> que nadie ha demostrado.**

Traducida a código, eso son tres garantías que una máquina comprueba en cada
integración continua, y no una revisión humana que alguien recuerde hacer:

| Id | Qué debía quedar disponible |
|---|---|
| **B9a** | `requires_complete_inventory_coverage` como propiedad **determinista y tipada**, derivada de los campos que la composición va a afirmar, y **no decidida por un LLM** |
| **B9b** | Los avisos `coverage_unknown` y `coverage_incomplete` disponibles en `AnswerWarning` y emitidos según [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §13, **sin confundirse entre sí** |
| **B9c** | Las pruebas automáticas **A20**, **A20b** y **A21** activas en integración continua |

**DECISIÓN TOMADA.** El objetivo **no** era demostrar la cobertura. La puerta
se trasladó de «Materiales debe demostrar su alcance» —externo, sin dueño y
sin fecha— a «ELSA no debe emitir ninguna afirmación que requiera cobertura»
—interno, acotado y comprobable con la política pura, sin red y sin datos
reales—.

---

## 2. Alcance

### Entró

1. Una representación explícita y tipada de la exigencia de cobertura, con su
   derivación determinista a partir de campos declarados.
2. Los dos avisos de cobertura, dentro de la taxonomía `AnswerWarning` que ya
   existía.
3. Una guarda de redacción para afirmaciones que presuponen cobertura
   completa, construida con el mismo método que la guarda de inexistencia de
   [5.0.c.1](bloque-5-0-c-1-politica-ausencia-segura-cierre.md).
4. La composición determinista que aplica la cobertura **sobre** la política
   de ausencia segura ya existente, sin sustituirla.
5. Las pruebas A20, A20b y A21, más las pruebas de regresión que comprueban
   que las garantías previas siguen en pie bajo la nueva capa.

### Quedó explícitamente fuera

**HECHO DEL REPOSITORIO**, verificable en el diff de
[PR #27](https://github.com/VallejoOsorio2026/Elsa-ai/pull/27): ninguno de
estos elementos se implementó, se inició ni se modificó.

| Fuera de alcance | Estado tras este subbloque |
|---|---|
| Fachada real de Materiales | No iniciada |
| `MaterialsPort` real | No modificado |
| Consultas HTTP a Materiales | No existen |
| Composición real BOM → Materiales | No iniciada |
| Endpoints | No tocados |
| Frontend (`web/`) | No tocado |
| Base de datos y migraciones (`supabase/`) | No tocadas |
| Router completo | No iniciado |
| `CapabilityPlan` completo | No iniciado |
| LLM | No tocado |
| ONNX | No tocado |
| Incident snapshot | No tocado |
| **D20** — retención del Incident Snapshot | **Abierta**, puerta previa a liberar, sin cambio |
| Documentos normativos (`docs/`) | **Sin cambios** durante PR #27 |

**DECISIÓN TOMADA.** Tampoco entró demostrar cómo una fuente acredita
`KNOWN_COMPLETE`. La política **consume** ese estado; no lo produce ni lo
verifica. Esa demostración pertenece a M8, que sigue abierto.

---

## 3. Estado inicial

**HECHO DEL REPOSITORIO.**

| Qué | Valor |
|---|---|
| Rama base | `main` |
| Commit base | `dfcf1bda884063042190ef5eee1c087cbb91efaa` |
| Árbol | Limpio |
| Rama de trabajo | `claude/b9-coverage-adr-0023-aa22f7` |

Qué existía ya en `main`:

- `src/elsa/core/capability_outcomes.py` — la política pura de ausencia segura
  cerrada en [5.0.c.1](bloque-5-0-c-1-politica-ausencia-segura-cierre.md), con
  `interpret_inventory_lookup`, `asserts_nonexistence` y
  `UncomposableOutcomeError`.
- `src/elsa/core/answers.py` — la taxonomía `AnswerWarning` con nueve avisos.
- `tests/test_absence_safety.py` — A6, A6b, A18 y A19 activas en integración
  continua.
- [ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md), que fija
  B9a, B9b y B9c, y
  [ADR 0024](adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md),
  que resolvió M3 y M5 para V1.
- El [contrato funcional](piloto-0-1/contrato-funcional.md) §10 con B9a, B9b y
  B9c ya enumerados como bloqueantes, y §12 con A20, A20b y A21 ya enumeradas
  como criterios de aceptación.

Qué **no** existía:

- Ningún tipo, constante o función relacionada con cobertura de inventario. La
  búsqueda de `coverage` en `src/` y `tests/` solo devolvía coincidencias de
  un concepto distinto —alcance de permisos en
  `tests/test_document_repository.py`—.
- Los avisos `coverage_unknown` y `coverage_incomplete`, declarados
  **conceptualmente** por [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md)
  §13.2 y explícitamente **no implementados** allí.
- `requires_fresh_inventory` tampoco existe en código. **PENDIENTE**: no
  entraba en este subbloque y sigue sin implementar.

---

## 4. Trabajo realizado

En este orden.

1. **Verificación de la base.** `HEAD` y árbol comprobados contra los valores
   esperados antes de leer nada.
2. **Auditoría del diseño existente.** Lectura completa de
   [ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md),
   [ADR 0024](adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md),
   del [contrato funcional](piloto-0-1/contrato-funcional.md), de
   `answers.py`, de `capability_outcomes.py`, de `tests/test_absence_safety.py`
   y de las secciones §7, §12, §12.1 y §13 de
   [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md), que son el
   mapeo normativo que este trabajo aplica.
3. **Pruebas primero.** `tests/test_coverage_policy.py` escrito antes que la
   implementación, y ejecutado para comprobar que fallaba por la razón correcta
   (§6, «Rojo inicial»).
4. **Implementación mínima**, en tres piezas:
   - los dos avisos en `answers.py`;
   - la guarda de redacción `asserts_complete_coverage` y el mensaje de
     incapacidad en `capability_outcomes.py`, junto a la guarda de
     inexistencia que ya vivía allí;
   - el módulo nuevo `src/elsa/core/coverage_policy.py` con los tipos y la
     decisión.
5. **Verificación por mutación** de que las garantías no son vacuas (§9).
6. **Pruebas específicas, suite completa, Ruff, mypy, pre-commit y gitleaks**
   (§6, §7, §8).
7. **Commit único, push y pull request.** Sin merge en ese momento.
8. **Auditoría final conductual** antes del merge (§«Auditoría conductual»).
9. **Merge commit** a `main`, autorizado explícitamente y con las once
   condiciones verificadas de antemano.

---

## 5. Decisiones

### D1 — Módulo propio para la cobertura, no una ampliación de la política de ausencia

**DECISIÓN TOMADA.** `capability_outcomes.py` responde a «¿qué hizo la fuente
con el código pedido?». La cobertura responde a otra pregunta, independiente:
«¿sé que el snapshot consultado cubre el ámbito que esta respuesta necesita?»
([ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §12).

Mezclarlas habría hecho que una pregunta contaminara la otra, que es
exactamente el error que ambos módulos existen para impedir. `coverage_policy.py`
**compone sobre** `interpret_inventory_lookup` y solo puede **restringir** lo
que aquella autorizó.

Lo que sí se añadió a `capability_outcomes.py` es la guarda de redacción
`asserts_complete_coverage`, porque ese módulo es el que concentra las guardas
sobre todo texto alcanzable, y tenerlas en un solo sitio es en sí mismo una
ventaja de auditoría.

### D2 — B9a: el requisito es un dato de entrada, nunca una inferencia

**DECISIÓN TOMADA.** `CoverageRequirement` es un `dataclass` congelado con el
campo `requires_complete_inventory_coverage: bool`. Se deriva de
`AssertedInventoryField` —los campos que la plantilla **declara** que va a
afirmar— por la tabla de
[ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §12:

| Campos afirmados | `requires_complete_inventory_coverage` |
|---|---|
| Solo estables: descripción, unidad de medida | `false` |
| Cualquiera de existencias, ubicaciones o disponibilidad | `true` |

**El LLM no participa**, y eso se sostiene por tres vías independientes:

1. El requisito es **entrada** de la decisión, no una lectura de texto libre.
2. Se deriva de campos declarados, no de lenguaje natural.
3. `coverage_policy.py` importa únicamente `collections.abc`, `dataclasses`,
   `enum`, `elsa.core.answers` y `elsa.core.capability_outcomes`. Ningún
   puerto, ningún adaptador, ningún modelo. Hay una prueba que lee los imports
   del módulo con `ast` y falla si eso cambia.

### D3 — Una afirmación universal no puede renunciar a la cobertura

**DECISIÓN TOMADA.** `ClaimScope` distingue las dos clases de
[ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) §9:
`ATTRIBUTED_TO_SOURCE` (Clase 1, acotable) y `UNIVERSAL` (Clase 2, no
acotable).

Una afirmación de Clase 2 cuantifica sobre el universo entero, así que exige
cobertura completa **cualesquiera que sean los campos que toque**: el universo
**es** la afirmación. La combinación incoherente —universal declarando
`requires_complete_inventory_coverage = false`— se rechaza **al construir el
requisito**, con `IncoherentCoverageRequirementError`, y no al emitir la
respuesta.

Rechazar en la construcción y no en la emisión es deliberado: impide que
llegue a existir un requisito capaz de autorizarse a sí mismo.

### D4 — Relevancia conservadora, para que el aviso signifique algo

**DECISIÓN TOMADA.** La cobertura solo degrada o avisa cuando es **relevante**,
por la tabla de [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md)
§12.1:

| Caso | Relevancia |
|---|---|
| `MATCHED` afirmando existencias o totales | Relevante |
| `MATCHED` afirmando solo campos estables | **No relevante** |
| `NOT_RETURNED` | **Relevante, conservadoramente** |

Un código ausente no dice en qué ámbito estaría, así que su relevancia es
indecidible y se resuelve del lado seguro. Con campos estables, en cambio,
degradar sería ruido, **y el ruido enseña a ignorar los avisos**
([ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) §10.1.6).

### D5 — Clase 1 se degrada; Clase 2 se rechaza

**DECISIÓN TOMADA.** No es una diferencia de grado.

| Clase | Con cobertura no demostrada |
|---|---|
| **Clase 1** | Se responde **acotada y degradada**: nunca `ANSWERED`, con el aviso que corresponda al estado |
| **Clase 2** | **No se emite.** Ni degradada, ni acompañada de aviso. La respuesta declara qué consultó y qué no puede concluir |

`PARTIAL` no basta para la Clase 2: significa «respuesta con respaldo
incompleto», y una afirmación universal sobre un universo desconocido no tiene
respaldo incompleto, **no tiene respaldo**. Un aviso junto a ella la haría
parecer una verdad matizada.

El aviso de cobertura que sí acompaña a esa respuesta marca **la respuesta**
—explica por qué ELSA se declara incapaz—, no acompaña a una afirmación que no
se emitió.

### D6 — `claim_emitted` como eje separado del estado

**DECISIÓN TOMADA.** `CoverageDecision` expone `claim_emitted: bool` aparte de
`status`, porque son cosas distintas y A21 las comprueba por separado. Una
Clase 2 rechazada y una Clase 1 degradada pueden compartir estado y no
comparten esto.

### D7 — La cobertura no habla cuando la fuente no pudo ser consultada

**DECISIÓN TOMADA.** Si `call_status` no es `OK`, la capa de cobertura
devuelve lo que la política de ausencia segura decidió, sin añadir nada.

No se llegó a consultar: la cobertura de lo que no se miró no añade ni quita, y
decir «cobertura desconocida» ahí convertiría un fallo técnico en un problema
de alcance, que es otra cosa. Las taxonomías `capability_unavailable` e
`inventory_unavailable` ya describen mejor ese fallo.

### D8 — B9b: extender la taxonomía existente, no crear una paralela

**DECISIÓN TOMADA.** `coverage_unknown` y `coverage_incomplete` entran en
`elsa.core.answers.AnswerWarning`, detrás de `code_not_found_in_source`. Ningún
aviso previo cambia de nombre, de valor ni de posición, así que
`order_warnings` sigue produciendo el mismo orden para las combinaciones que ya
existían.

**`UNKNOWN` no se presenta como `INCOMPLETE`.** Afirmar incompletitud sin
evidencia sería el mismo error que ADR 0021 combate, en espejo. La convención
es la que ya fijó `inventory_freshness_unknown`: nombrar el desconocimiento en
vez de asimilarlo al peor caso conocido.

### D9 — A21 se construye como A18, no como una lista de palabras

**DECISIÓN TOMADA.** `asserts_complete_coverage` mira **frase a frase**, admite
salvedades epistémicas y **no prohíbe vocabulario**. Una prohibición de «todos»
o de «ningún» habría roto la única forma honesta de acotar una respuesta a su
fuente.

Dos consecuencias que el diseño fija a propósito:

- **Una atribución no es una salvedad.** «Según el inventario cargado en
  Materiales, no hay en ningún almacén» **sigue siendo** Clase 2, porque
  ninguna acotación vuelve verdadera una afirmación universal sobre un universo
  desconocido ([ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md)
  §9).
- **Un universo conocido sí puede enumerarse.** «Estos son todos los elementos
  del BOM publicado» es una afirmación acotada a una fuente propia de ELSA,
  completa por construcción respecto de sí misma, y **no** se rechaza.

### Sobre ADR

**DECISIÓN TOMADA.** Este subbloque **no genera ningún ADR nuevo**, y no
modifica ninguno. No reabre una decisión cerrada ni toma una nueva: **ejecuta**
lo que [ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) §14 ya
decidió, con el mapeo que
[ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §13 ya fijó. Las
decisiones D1–D9 son de implementación, no de arquitectura: ninguna elige entre
opciones que un ADR hubiera dejado abiertas.

---

## 6. Pruebas

### Rojo inicial

**HECHO MEDIDO.** `tests/test_coverage_policy.py` se escribió y se ejecutó
antes de existir la implementación:

```
E   ImportError: cannot import name 'UNBOUNDED_CLAIM_REFUSAL_MESSAGE' from
    'elsa.core.capability_outcomes'
...
ERROR tests/test_coverage_policy.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
2 warnings, 1 error in 0.23s
```

### Mapeo normativo de las pruebas

Las etiquetas son las de
[ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) §14.1 y del
[contrato funcional](piloto-0-1/contrato-funcional.md) §12, que coinciden entre
sí. Ver el incidente **I1** en §13.

| Id | Qué prueba | Resultado esperado y obtenido |
|---|---|---|
| **A20** | `requires_complete_inventory_coverage = true` + cobertura `UNKNOWN` o `KNOWN_INCOMPLETE` | **Nunca** `ANSWERED`. Bajo `UNKNOWN`: `PARTIAL` + `coverage_unknown`, **nunca** `coverage_incomplete`. Bajo `KNOWN_INCOMPLETE`: `PARTIAL` + `coverage_incomplete` |
| **A20b** | `requires_complete_inventory_coverage = false` afirmando solo campos estables | La cobertura **no degrada por sí sola**: `ANSWERED` sin aviso de cobertura, con `UNKNOWN` y con `KNOWN_INCOMPLETE` |
| **A21** | Afirmaciones universales, texto y estado **por separado** | Con `UNKNOWN` o `KNOWN_INCOMPLETE`, una afirmación que presupone cobertura completa **no se emite**: `claim_emitted = False` y mensaje de incapacidad |

Tres matices que el mapeo fija, y que el documento deja por escrito para que
nadie los deduzca al revés:

1. **`UNKNOWN` no produce siempre un aviso.** Si la consulta solo afirma campos
   estables y no exige cobertura completa, la cobertura global **no es
   material** para lo afirmado, y no se avisa (D4).
2. **A20b sí puede llevar aviso de cobertura** cuando `UNKNOWN` sí es material:
   el caso `NOT_RETURNED`, relevante en conservador, propaga
   `coverage_unknown` o `coverage_incomplete` **sin** degradar el estado.
3. **`claim_emitted` y `AnswerStatus` son ejes separados**, y A21 los comprueba
   aparte (D6).

### Cobertura de las garantías

**HECHO MEDIDO.** 35 funciones de prueba, 216 casos.

| Grupo | Casos | Qué cubre |
|---|---|---|
| **B9a** | 10 | Tipo del flag, derivación por campos, determinismo e independencia del orden, universal que siempre exige cobertura, combinación incoherente rechazada, imports del módulo, el flag como entrada de la decisión |
| **B9b** | 7 | Nombres exactos, taxonomía previa intacta, `UNKNOWN` ≠ `INCOMPLETE` en las dos direcciones, `KNOWN_COMPLETE` sin aviso, orden y deduplicación, tabla de relevancia |
| **A20** | 8 | Los casos literales del contrato funcional §12, la variante `KNOWN_INCOMPLETE`, el barrido «nunca `ANSWERED`», el caso `KNOWN_COMPLETE` que evita la vacuidad y la ausencia que sigue sin ser inexistencia |
| **A20b** | 5 | No degradación con campos estables, evidencia utilizable con semántica no autoritativa, y la ausencia que sí propaga el aviso |
| **A21** | 168 | Guarda en las dos direcciones, lectura frase a frase, independencia respecto de la guarda A18, y **dos barridos de 72 combinaciones** —texto y estado, por separado— más el rechazo de Clase 2 y la comprobación de no vacuidad |
| **Regresión** | 19 | A6, A19, `REJECTED` y ausencia autoritativa, todos bajo los tres estados de cobertura |

Las 72 combinaciones del barrido son el producto de 4 resultados de capacidad ×
3 requisitos × 3 estados de cobertura × 2 composiciones.

### Guarda A21, en las dos direcciones

**HECHO MEDIDO.** Frases que **deben** disparar la guarda, y frases con el
mismo vocabulario que **no** deben hacerlo:

| Disparada | Frase |
|---|---|
| Sí | «Según el inventario cargado en Materiales, no hay en ningún almacén.» |
| Sí | «De acuerdo con la fuente consultada, estos son todos los materiales que tenemos.» |
| Sí | «Consultando Materiales, el material no está en ninguna bodega.» |
| Sí | «No existe en el inventario de la empresa.» |
| No | «Estos son todos los elementos del BOM publicado que devolvió la consulta.» |
| No | «Encontré 7 elementos del BOM publicado con disponibilidad en la fuente consultada.» |
| No | «Según el inventario cargado en Materiales, este código tiene existencias en las ubicaciones devueltas.» |
| No | «La fuente consultada no devolvió el material solicitado.» |
| No | «No puedo afirmar que no haya en ningún almacén: se desconoce qué almacenes cubre este inventario.» |

El mismo vocabulario —«todos los», «en ningún almacén»— pasa o no según la
semántica de la frase, no según las palabras que contiene.

### Qué se ejecutó

**HECHO MEDIDO.**

| Ejecución | Resultado |
|---|---|
| `tests/test_coverage_policy.py` | `216 passed` |
| `tests/test_coverage_policy.py` + `tests/test_absence_safety.py` | `250 passed` |
| `tests/test_absence_safety.py` sola | `34 passed` |
| Suite completa | `1391 passed, 230 skipped` |

Los 230 omitidos requieren PostgreSQL o modelos locales, se omiten igual en
`main` y este cambio **no toca base de datos**. La integración continua sí
dispone de PostgreSQL —el job `Lint, types and tests` levanta un servicio
`postgres` y define `ELSA_TEST_DATABASE_URL`—, así que esas pruebas **sí se
ejecutaron allí** y quedaron en verde.

---

## 7. Comandos relevantes

Los que otra persona necesitaría para reproducir el trabajo.

```bash
# Pruebas del subbloque
uv run pytest tests/test_coverage_policy.py -q

# Junto a las garantías de ausencia segura, que no deben romperse
uv run pytest tests/test_coverage_policy.py tests/test_absence_safety.py -q

# Suite completa
uv run pytest -q

# Lint, formato y tipos
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests

# Ganchos locales, incluido gitleaks
uv run pre-commit run --all-files

# Alcance del cambio
git diff --stat dfcf1bda884063042190ef5eee1c087cbb91efaa...3f12ef59158d36b3a098e05c77224c27ba35f772
```

---

## 8. Resultados

Salida real, pegada.

```
$ uv run pytest tests/test_coverage_policy.py -q
........................................................................ [ 33%]
........................................................................ [ 66%]
........................................................................ [100%]
216 passed, 2 warnings in 0.20s
```

```
$ uv run pytest tests/test_coverage_policy.py tests/test_absence_safety.py -q
250 passed, 2 warnings in 0.26s
```

```
$ uv run pytest -q
1391 passed, 230 skipped, 3 warnings in 39.90s
```

```
$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
295 files already formatted

$ uv run mypy src tests
Success: no issues found in 214 source files
```

```
$ uv run pre-commit run --all-files
trim trailing whitespace.................................................Passed
fix end of files.........................................................Passed
check yaml...............................................................Passed
check toml...............................................................Passed
check for merge conflicts................................................Passed
check for added large files..............................................Passed
detect private key.......................................................Passed
ruff check...............................................................Passed
ruff format..............................................................Passed
Detect hardcoded secrets.................................................Passed
```

**HECHO DEL REPOSITORIO.** `gitleaks` se ejecuta en este proyecto como gancho
de `pre-commit` —la línea `Detect hardcoded secrets`— y como job propio de
integración continua sobre el historial completo. No hay binario suelto
instalado en el entorno de la sesión, así que no se ejecutó un `gitleaks
detect` independiente.

---

## 9. Métricas

**HECHO MEDIDO.** Cifras medidas, con el método por el que se obtuvieron.

| Métrica | Valor | Método |
|---|---|---|
| Funciones de prueba nuevas | 35 | `grep -c '^def test_' tests/test_coverage_policy.py` |
| Casos de prueba nuevos | 216 | `pytest --collect-only -q`, contando líneas con `::` |
| Archivos cambiados | 4 | `git diff --stat` sobre el rango del PR |
| Líneas insertadas | 1064 | ídem |
| Líneas borradas | **0** | ídem |
| Archivos fuente analizados por mypy | 214 | Salida de `mypy src tests` |
| Archivos formateados por Ruff | 295 | Salida de `ruff format --check .` |

### Duración de la suite

**HECHO MEDIDO**, y **no una constante**. Es el tiempo observado en tres
ejecuciones concretas de la suite completa, en el contenedor de la sesión:

| Momento | Duración observada |
|---|---|
| Tras la implementación | `39.90 s` |
| Durante la auditoría previa al merge | `37.97 s` |
| En la verificación de condiciones del merge | `37.82 s` |

El conteo de pruebas fue idéntico en las tres: `1391 passed, 230 skipped`. La
duración depende de la máquina y de la carga, y **no debe citarse como umbral
ni como criterio de aceptación**.

### Verificación por mutación

**HECHO MEDIDO**, y **temporal**. Durante el desarrollo se introdujeron tres
mutaciones deliberadas en la implementación, se observó cuántas pruebas
fallaban y **se restauró la implementación original** desde una copia de
seguridad.

| Mutación introducida | Pruebas que fallaron |
|---|---|
| Desactivar la regla B.1, para que `ANSWERED` no degradara | 11 |
| Permitir que la afirmación de Clase 2 se emitiera | 16 |
| Convertir `UNKNOWN` en `COVERAGE_INCOMPLETE` | 5 |
| **Implementación restaurada** | **0 — `216 passed`** |

> **Esto no es comportamiento productivo.** Ninguna de las tres mutaciones
> existe en el código integrado, y ninguna se commiteó en ningún momento. Son
> una comprobación de que las garantías **muerden**: una prueba que pasa tanto
> con la implementación correcta como con la rota no protege nada. El árbol se
> verificó limpio después de restaurar, antes de cualquier commit.

---

## Auditoría conductual

**HECHO MEDIDO.** Antes del merge se ejecutó la política sobre todas las
combinaciones alcanzables, comprobando el comportamiento en vez de leer el
código.

### B9a — las reglas, ejecutadas

| `requires_complete_inventory_coverage` | Cobertura | `status` | `claim_emitted` | Avisos |
|---|---|---|---|---|
| `false` | `unknown` | `answered` | `True` | — |
| `false` | `known_incomplete` | `answered` | `True` | — |
| `false` | `known_complete` | `answered` | `True` | — |
| `true` | `unknown` | `partial` | `True` | `coverage_unknown` |
| `true` | `known_incomplete` | `partial` | `True` | `coverage_incomplete` |
| `true` | `known_complete` | `answered` | `True` | — |

Los casos con `requires = false` usan una plantilla que solo afirma campos
estables, y su mensaje es «La fuente consultada devolvió el material
solicitado»: atribuido a la fuente, **no al mundo**. Ni
`asserts_complete_coverage` ni `asserts_nonexistence` lo marcan.

### A21 — los dos ejes, separados

| Escenario | `status` | `claim_emitted` |
|---|---|---|
| Clase 1, `requires = true`, `UNKNOWN` | `partial` | `True` |
| Clase 2, `UNKNOWN` | `no_evidence` | `False` |
| Clase 2, `KNOWN_INCOMPLETE` | `no_evidence` | `False` |
| Clase 2, `KNOWN_COMPLETE` | `answered` | `True` |

La última fila es la comprobación de **no vacuidad**: si ningún estado de
cobertura pudiera admitir la afirmación universal, la garantía sería cierta
por vacuidad y dejaría de proteger nada.

### Monotonía de la capa

**HECHO MEDIDO.** Sobre las **72 combinaciones** alcanzables, comparando el
resultado de `interpret_inventory_lookup` con el de `decide_under_coverage`:

| Comprobación | Resultado |
|---|---|
| Estados **mejorados** indebidamente por la capa de cobertura | **0** |
| Avisos previos **perdidos** al aplicar la cobertura | **0** |

**INFERENCIA**, derivada de lo anterior: la capa de cobertura solo restringe.
No puede convertir un `ERROR` en un `PARTIAL`, ni un `PARTIAL` en un
`ANSWERED`, ni hacer desaparecer un aviso que la política de ausencia segura ya
había levantado.

### Garantías previas, bajo la capa nueva

**HECHO MEDIDO.**

| Garantía | Comprobación | Resultado |
|---|---|---|
| **A6** | Capacidad indisponible, bajo los tres estados de cobertura y los tres requisitos | `PARTIAL` + `capability_unavailable`, nunca `NO_EVIDENCE`, nunca avisos de cobertura |
| **A6b** | `NOT_RETURNED` no autoritativo | `NO_EVIDENCE` + `code_not_found_in_source`; el texto sigue sin afirmar inexistencia |
| **A18** | Todos los mensajes alcanzables de la política compuesta | Ninguno afirma inexistencia |
| **A19** | `NO_ACTIVE_INVENTORY`, con y sin otros hechos, bajo los tres estados | Resultado **idéntico** con y sin la capa de cobertura: mismo estado, mismos avisos, mismo mensaje |
| **`REJECTED`** | Bajo los tres estados de cobertura | Excepción `UncomposableOutcomeError` en los tres |
| **Ausencia autoritativa** | `NOT_RETURNED` + `absence_is_authoritative = True`, bajo los tres estados, **`KNOWN_COMPLETE` incluido** | Excepción `UncomposableOutcomeError` en los tres |

La última fila es el invariante del que depende
[ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) §13 entero:
ningún estado de cobertura habilita una ausencia autoritativa mientras M8 siga
abierto.

`tests/test_absence_safety.py` siguió en verde sin que se modificara ni una
línea de ese archivo: **HECHO DEL REPOSITORIO**, el diff del PR no lo toca.

---

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO.** Toda la implementación, las pruebas y este documento
se produjeron en sesiones de Claude Code sobre el repositorio.

| Sesión | Identificador | Qué produjo |
|---|---|---|
| Implementación B9a–B9c | `https://claude.ai/code/session_01VeUFivjy4iVfKWjpMYjN3Y` | `coverage_policy.py`, `test_coverage_policy.py`, los dos avisos, la guarda `asserts_complete_coverage`, la auditoría previa al merge y este documento de cierre |

**HECHO DEL REPOSITORIO.** El identificador es **verificable en Git**: aparece
como trailer `Claude-Session:` del commit funcional
`3f12ef59158d36b3a098e05c77224c27ba35f772`, recuperable con
`git log -1 --format=%B 3f12ef5`. No se reconstruye de memoria.

Qué se revisó, y cómo: el responsable del proyecto solicitó una auditoría
previa al merge con once condiciones explícitas, que se verificaron una a una
—`HEAD`, base, árbol, CI, conteos, calidad, alcance, mapeo normativo y
garantías previas— antes de autorizar la fusión. El resultado de esa auditoría
está en §«Auditoría conductual».

---

## 11. Aportes de Codex

**Nada que registrar.** Codex **no se utilizó** en este subbloque. Ni la
implementación, ni las pruebas, ni este documento pasaron por esa herramienta.

---

## 12. Operaciones manuales y de PowerShell

**Nada que registrar.** No hubo comandos de PowerShell, ni comprobaciones en el
panel de Supabase, ni arranque de servicios locales, ni mediciones sobre
archivos fuera de Git.

**HECHO DEL REPOSITORIO**, y es consecuencia del diseño, no una casualidad:
este subbloque implementa **política pura**. Todo lo ejecutado ocurrió dentro
del contenedor de la sesión mediante `uv run`, sin red, sin datos reales y sin
tocar ningún proyecto Supabase. Es exactamente lo que
[ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) §14 anticipó al
decir que B9a–B9c se verifican «con el fake contractual, sin red y sin datos
reales».

---

## 13. Incidentes

### I1 — Discrepancia de especificación: A20 y A20b intercambiadas en el encargo

**HECHO DEL REPOSITORIO.** Las instrucciones de la sesión que encargó la
implementación describían A20 y A20b **al revés** respecto de las dos fuentes
normativas, que coinciden entre sí y estaban ya en `main` antes del encargo:

| Fuente | A20 | A20b |
|---|---|---|
| [ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) §14.1 | `requires_complete_inventory_coverage = true` + `UNKNOWN` | `requires_complete_inventory_coverage = false` + campos estables |
| [Contrato funcional](piloto-0-1/contrato-funcional.md) §12 | Igual | Igual |
| Encargo de la sesión | `= false` | `= true` |

**Qué se hizo.** No se resolvió por cuenta propia ni en silencio. Se aplicó la
regla 19 de [`CLAUDE.md`](../CLAUDE.md) —reportar las inconsistencias técnicas
detectadas en las instrucciones antes de escribir código— y la regla 25 —las
decisiones cerradas no se reabren sin un ADR nuevo—:

1. Se conservaron las **etiquetas normativas**, que son la autoridad.
2. Se cubrió la **unión de ambas lecturas**, de modo que ninguno de los dos
   escenarios quedara sin prueba: el trabajo pedido se entregó completo bajo
   cualquiera de las dos interpretaciones.
3. El docstring de `tests/test_coverage_policy.py` declara el mapeo empleado,
   para que nadie tenga que deducirlo.
4. La discrepancia se reportó al responsable del proyecto y se registró en el
   cuerpo de [PR #27](https://github.com/VallejoOsorio2026/Elsa-ai/pull/27).

**Cómo se cerró.** El responsable del proyecto confirmó por escrito que la
decisión de conservar las etiquetas normativas fue la correcta, que su encargo
anterior las había intercambiado y que el código y los documentos **no** debían
cambiarse para seguir ese error. **DECISIÓN TOMADA**, y sin efecto sobre el
código: no hizo falta modificar nada.

**Qué queda pendiente de este incidente.** Nada.

### I2 — Formato aplicado por Ruff tras escribir las pruebas

**HECHO MEDIDO.** `ruff format --check .` señaló tres archivos por reformatear
tras escribir la implementación y las pruebas. Se ejecutó `ruff format .`, se
reformatearon los tres —los dos nuevos y `capability_outcomes.py`— y se
volvieron a pasar `ruff check`, `ruff format --check`, `mypy` y las pruebas, en
verde. Ningún otro archivo del repositorio resultó modificado.

Sin efecto sobre el comportamiento: es formato. Se registra porque ocurrió
antes del commit y explica por qué el commit sale ya formateado.

### Sobre la ausencia de más incidentes

El estándar advierte que un bloque sin incidentes es sospechoso. Aquí hubo dos,
y ninguno fue un fallo de la implementación: uno de especificación y uno de
formato. **No hubo** integración continua en rojo, ni conflicto de fusión, ni
prueba que hubiera que rehacer, ni comportamiento inesperado en la auditoría
previa al merge. La razón previsible es el tamaño del alcance y que las pruebas
se escribieron antes que el código, no una virtud del proceso.

---

## 14. Git

**HECHO DEL REPOSITORIO.**

| Qué | Valor |
|---|---|
| Base | `dfcf1bda884063042190ef5eee1c087cbb91efaa` |
| Commit funcional | `3f12ef59158d36b3a098e05c77224c27ba35f772` |
| Merge commit | `a0ec4813c1ed0ac82fc9ab29cb567ce25121ce4d` |
| Método de fusión | **Merge commit**. No squash, no rebase |
| Commits integrados desde la base | **2** — el funcional y la fusión |

Diff funcional:

```
 src/elsa/core/answers.py             |  16 +
 src/elsa/core/capability_outcomes.py |  70 ++++
 src/elsa/core/coverage_policy.py     | 299 +++++++++++++++
 tests/test_coverage_policy.py        | 679 +++++++++++++++++++++++++++++++++++
 4 files changed, 1064 insertions(+)
```

**Cero borrados.** Ningún archivo existente pierde una línea, y ningún
documento de `docs/` cambió durante PR #27.

---

## 15. Ramas

| Rama | Uso | Estado |
|---|---|---|
| `claude/b9-coverage-adr-0023-aa22f7` | Implementación B9a–B9c | Fusionada en `main` por PR #27. **No borrada**, por instrucción explícita |
| `claude/b9a-b9c-closure-doc` | Este documento de cierre | Abierta, con su propio pull request |
| `main` | Rama base | Actualizada con `--ff-only` a `a0ec4813c1ed0ac82fc9ab29cb567ce25121ce4d` |

Ninguna rama abandonada.

---

## 16. Commits

| Hash | Mensaje |
|---|---|
| `3f12ef59158d36b3a098e05c77224c27ba35f772` | `feat(core): enforce inventory coverage as an executable guarantee` |
| `a0ec4813c1ed0ac82fc9ab29cb567ce25121ce4d` | `Merge pull request #27 from VallejoOsorio2026/claude/b9-coverage-adr-0023-aa22f7` |

Un solo commit funcional, por decisión del encargo. El commit del documento de
cierre vive en su propia rama y su propio pull request.

---

## 17. Pull requests

**HECHO DEL REPOSITORIO.**

| PR | Título | Estado | CI |
|---|---|---|---|
| [#27](https://github.com/VallejoOsorio2026/Elsa-ai/pull/27) | `feat(core): B9a + B9b + B9c — cobertura de inventario como garantía ejecutable` | **Merged** el 2026-09-20 | **Verde** |

Checks sobre `3f12ef59158d36b3a098e05c77224c27ba35f772`: **4 de 4**, dos jobs ×
dos eventos.

| Evento | Job | Conclusión |
|---|---|---|
| `push` | `Lint, types and tests` | `success` |
| `push` | `Secret scan (gitleaks)` | `success` |
| `pull_request` | `Lint, types and tests` | `success` |
| `pull_request` | `Secret scan (gitleaks)` | `success` |

Runs: [#164 `push`](https://github.com/VallejoOsorio2026/Elsa-ai/actions/runs/35486609429)
y [#165 `pull_request`](https://github.com/VallejoOsorio2026/Elsa-ai/actions/runs/35486633404).

El job `Lint, types and tests` levanta un servicio PostgreSQL, así que las
pruebas que localmente se omiten por falta de base de datos **sí se ejecutaron
en integración continua**.

El PR no recibió revisiones formales: `0` reviews en el momento del merge. La
revisión fue la auditoría solicitada por el responsable del proyecto y
respondida en la conversación, con las once condiciones verificadas antes de
autorizar la fusión.

---

## 18. Migraciones

**Nada que registrar.** Este subbloque **no escribió ninguna migración**, no
modificó `supabase/`, no aplicó nada a ningún proyecto Supabase y no requirió
autorización de la regla 15. La política es pura y no tiene esquema.

---

## 19. Estado operacional final

### Qué funciona

**HECHO MEDIDO**, verificado en integración continua sobre `main`.

| Id | Estado |
|---|---|
| **B9a** — `requires_complete_inventory_coverage` | **IMPLEMENTADO Y PROBADO** |
| **B9b** — `coverage_unknown` y `coverage_incomplete` | **IMPLEMENTADO Y PROBADO** |
| **B9c** — pruebas A20, A20b y A21 | **IMPLEMENTADO Y PROBADO**, activas en integración continua |

Junto a ellas siguen activas y verdes las garantías de
[5.0.c.1](bloque-5-0-c-1-politica-ausencia-segura-cierre.md): **A6**, **A6b**,
**A18** y **A19**.

### Qué está degradado, por diseño

La política **declara** la incertidumbre de cobertura en vez de ocultarla. Con
`coverage = UNKNOWN`, que es el estado disponible hoy:

- una consulta que exige cobertura completa **nunca** alcanza `ANSWERED`;
- una afirmación universal **no se emite**;
- una consulta que no exige cobertura completa responde con normalidad, y su
  texto se atribuye a la fuente y al snapshot, nunca al mundo.

Eso **no es un fallo**: es la garantía funcionando.

### Qué no está conectado

Nada de esto existe todavía, y este subbloque no lo acerca:

- la fachada real de Materiales y su `MaterialsPort` real;
- cualquier consulta HTTP a Materiales;
- la composición real BOM → Materiales;
- el router, el `CapabilityPlan` completo, los endpoints y el frontend;
- `requires_fresh_inventory`, que sigue sin implementar.

**INFERENCIA.** La política de cobertura está lista para que una fachada futura
le entregue un estado de cobertura, pero **nadie la invoca aún** desde un
camino de respuesta real. Es código correcto y probado que todavía no tiene
llamador en producción, exactamente como lo estuvo la política de ausencia
segura al cerrar 5.0.c.1.

### Qué **no** demuestra este subbloque

Se enumera porque cada línea es una confusión posible:

| No significa | Estado real |
|---|---|
| La cobertura de Materiales es completa | **No.** Es `UNKNOWN`, y se declara como tal |
| M8 está cerrado | **No.** Sigue **ABIERTO** |
| ELSA sabe demostrar `KNOWN_COMPLETE` | **No.** La política **consume** ese estado; no lo produce ni lo verifica |
| El Piloto 0.1 está listo para testers | **No.** B9a–B9c eran tres de los bloqueantes del [contrato funcional](piloto-0-1/contrato-funcional.md) §10. Los demás siguen en su estado |
| La prueba A6c puede reactivarse | **No.** Sigue desactivada mientras M8 siga abierto |

**DECISIÓN TOMADA**, y es la de
[ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md): lo que este
subbloque consigue es **permitir operar de forma controlada con M8 abierto**,
no cerrar M8. **ADR 0023 sigue siendo la autoridad normativa** sobre esta
materia, y este documento no la reabre ni la modifica.

---

## 20. Pendientes

Estados leídos del corpus vigente, **uno a uno y sin homogeneizar**.

| Id | Estado exacto, y dónde consta | Quién debe resolverlo |
|---|---|---|
| **P1** | **M8 — ABIERTO.** «Abierta y NO bloqueante» desde ADR 0023 ([contrato funcional](piloto-0-1/contrato-funcional.md) §14). Su criterio de cierre sigue siendo [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §8.3, **intacto y sin cumplir**. Mientras siga abierto, ELSA no puede afirmar la inexistencia de un material y la cobertura se declara `UNKNOWN` | Materiales, con el Contract Owner de M7 |
| **P2** | **M1 — decisión arquitectónica cerrada · implementación contractual pendiente · bloqueante** ([ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §25, fila sin cambios) | Responsable del proyecto y Materiales |
| **P3** | **M4 — semántica contractual definida · verificación e implementación de metadata pendientes · bloqueante** (ídem) | Materiales |
| **P4** | **M6 — parcial · bloqueante** (ídem) | Materiales |
| **P5** | **M7 — rol y gobernanza definidos · ocupante inicial pendiente · bloqueante** (ídem). Es la razón por la que M8 no tiene dueño asignado | Responsable del proyecto |
| **P6** | **M2 — abierto · no bloqueante** (ídem) | Sin asignar |
| **P7** | **D20 — retención del Incident Snapshot: ABIERTA y puerta previa a liberar**, sin cambio ([ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) §18, [ADR 0022](adr/0022-feedback-e-incident-snapshot-del-piloto.md) §20). Ningún tester entra antes de que exista una política escrita | Responsable del proyecto |
| **P8** | **Fachada y `MaterialsPort` reales de Materiales** — no iniciados | Siguientes subbloques |
| **P9** | **Composición real BOM → Materiales** — no iniciada | Siguientes subbloques |
| **P10** | **`requires_fresh_inventory`** — decidido en [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §11, **sin implementar** | Siguientes subbloques |
| **P11** | **El subbloque 5.0.b continúa ABIERTO.** M3 y M5 quedaron resueltos para V1 por [ADR 0024](adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md), pero eso **no cierra el subbloque** | Responsable del proyecto |
| **P12** | **El subbloque 5.0.c continúa ABIERTO.** Feedback, `response_ref`, Incident Snapshot, persistencia, interfaz, acceso al manual y observabilidad HTTP son trabajos posteriores suyos | Siguientes subpasos |
| **P13** | **Resto de bloqueantes del [contrato funcional](piloto-0-1/contrato-funcional.md) §10**: B1, B2, B4, B5, B7, B8, B10–B17. Retirar B9 **no los toca** | Responsable del proyecto |
| **P14** | **La prueba A6c sigue desactivada** y documentada como tal, mientras M8 siga abierto ([contrato funcional](piloto-0-1/contrato-funcional.md) §12) | Bloqueado por P1 |
| **P15** | **Mecanismo por el que la interfaz presenta el manual** — pendiente de inspeccionar el frontend (ídem §14) | Siguientes subbloques |

> **No se homogeneizan.** Cada fila lleva el estado que el corpus le da hoy, y
> ninguno se cierra por asociación con otro. En particular, **retirar B9 de los
> bloqueantes no adelanta ni un paso** a M1, M4, M6, M7 ni D20.

---

## 21. Siguiente bloque

**PENDIENTE de autorización explícita.** Este documento **no autoriza** nada
por sí solo, y el orden lo fija el responsable del proyecto.

Lo que este cierre **habilita**, en términos de ADR 0023 §14: las capacidades
que puedan emitir una afirmación dependiente de cobertura ya cuentan con los
tres controles ejecutables que se exigían antes de liberarlas. **Eso es todo lo
que habilita.** Liberar a un tester sigue dependiendo del resto de bloqueantes
del [contrato funcional](piloto-0-1/contrato-funcional.md) §10, y **D20 sigue
siendo puerta previa a liberar**.

El paso natural, y el que menos alcance nuevo abre, es **continuar el subbloque
5.0.c** por el orden ya trazado en
[el cierre de 5.0.c.1](bloque-5-0-c-1-politica-ausencia-segura-cierre.md) §21.

**No se autoriza aquí**, y requiere una decisión explícita en cada caso:

- cerrar M8, ni reactivar la prueba A6c;
- cerrar el subbloque 5.0.b, el 5.0.c, el Bloque 5.0 ni el Piloto 0.1;
- iniciar la fachada real de Materiales o su `MaterialsPort` real;
- iniciar la composición real BOM → Materiales;
- tocar ONNX;
- decidir D20.
