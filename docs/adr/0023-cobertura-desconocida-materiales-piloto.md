# ADR 0023 — Cobertura desconocida de Materiales, aceptada bajo controles compensatorios

- Estado: **propuesto**
- Bloque: 5.0, subbloque **5.0.c.2**
- **Decide una sola cosa**: que **M8 deja de ser puerta previa a liberar** el
  Piloto 0.1, y qué lo sustituye
- **No cierra M8.** El criterio de cierre de
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3 sigue vigente,
  intacto y **no cumplido** (§8)
- Ejerce el mecanismo que
  [ADR 0022](0022-feedback-e-incident-snapshot-del-piloto.md) §21 exigió
  —«cualquier cambio futuro del carácter bloqueante de M8 requiere otro ADR»—
  y cuya precondición —A6, A6b, A18 y A19— **ya está cumplida y es
  verificable** (§4)
- Sustituye, **únicamente en lo relativo a M8**, la puerta declarada en
  [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §17. **No
  reabre** ninguna otra decisión de ADR 0020, y la restricción de su §12 sigue
  rigiendo sin cambios
- **No reabre** la taxonomía, la forma del contrato ni el mapeo a
  `AnswerStatus` de [ADR 0021](0021-contrato-de-inventario-con-materiales.md):
  los **aplica**
- Conserva sin cambios los estados de respuesta de
  [ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md). **No crea
  ningún `AnswerStatus` nuevo**
- Aplica las reglas **2, 9, 21, 22 y 23** de [`CLAUDE.md`](../../CLAUDE.md)
- **No aprueba, y no contiene, ninguna implementación**: ni fachada, ni
  `MaterialsPort` real, ni endpoint, ni frontend, ni migración, ni metadata
  nueva, ni plan de capacidades, ni router, ni integración BOM → Materiales

---

## Contexto

### 1. La pregunta que este ADR responde

No es «¿ya sabemos qué significa una ausencia en Materiales?». Esa pregunta
sigue sin respuesta y este ADR **no la responde**.

La pregunta es otra:

> ¿Puede el Piloto 0.1 liberarse con **cobertura de inventario desconocida**,
> sin que ninguna respuesta de ELSA dependa de una cobertura que nadie ha
> demostrado?

Son preguntas distintas y el corpus normativo las había fundido en un único
«M8 bloqueante». Separarlas es todo el contenido de este ADR.

### 2. Qué dice hoy el corpus sobre M8

Dos conjuntos de afirmaciones conviven en documentos ya fusionados.

**Primer conjunto — el corpus ya especificó cómo operar con M8 abierto.**

| Dónde | Qué dice |
|---|---|
| [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §12 | Mientras M8 no esté cerrado, ELSA solo puede afirmar «Materiales no devolvió este código en la fuente consultada», y **no** «el material no existe» |
| [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §13 | La tabla normativa tiene una fila **explícitamente para «M8 abierto»**: consulta directa sin coincidencia → `NO_EVIDENCE` + `code_not_found_in_source` |
| [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.3 | `UNKNOWN` es un **estado contractual legítimo** de cobertura, no un error |
| [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.5 | Bajo `UNKNOWN`, ELSA **nunca afirma cobertura**, y un `NOT_RETURNED` bajo `UNKNOWN` es especialmente débil |
| [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §13 | El mapeo a `AnswerStatus` **ya contempla** `UNKNOWN`: con exigencia de cobertura, `PARTIAL` + `coverage_unknown` |
| [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §21.3 | Nombra la regla que rige **mientras M8 permanece abierto** |

Es decir: **nada en el corpus exige que la cobertura sea `COMPLETE` para que
ELSA responda con seguridad.** Lo que la apertura de M8 prohíbe es **una sola
cosa**: afirmar inexistencia.

**Segundo conjunto — el corpus declaró M8 bloqueante.**

| Dónde | Qué dice |
|---|---|
| [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §17 | M8 es **puerta previa a liberar** |
| [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §25 | M8 **abierto · bloqueante** |
| [Contrato funcional](../piloto-0-1/contrato-funcional.md) §10 | **B9** — M8 entre los bloqueantes previos al primer tester |

### 3. El contrato funcional ya acotó, él mismo, el efecto de esa puerta

Dos hechos del [contrato funcional](../piloto-0-1/contrato-funcional.md), ambos
verificables en `main` y anteriores a este ADR:

1. **§14 declara la consecuencia operativa de M8 en términos estrechos:**
   «M8 — Abierta y bloqueante. **Mientras siga así, ELSA no puede afirmar la
   inexistencia de un material.**» Esa consecuencia —y no otra— es exactamente
   la que hoy está impuesta por código y probada en integración continua.

2. **§13, riesgo R4 —«Cobertura incompleta del inventario»— no lista M8 entre
   sus mitigaciones.** Su mitigación declarada es «el manual lo advierte y el
   mensaje de ausencia nunca se lee como "no existe"». La cobertura incompleta
   estaba ya aceptada como **riesgo mitigado**, no como puerta.

En el riesgo R2 —«ausencia interpretada como inexistencia»— se enumeran cuatro
mitigaciones: «M8 bloqueante; restricción de redacción de ADR 0020 §12; pruebas
A6, A6b y A18; advertencia en el manual». Cuando se escribió, tres de las
cuatro **no existían**. «M8 bloqueante» era el marcador provisional que
sostenía el riesgo mientras las otras tres se construían.

### 4. Las otras tres ya existen, y son ejecutables

**HECHO DEL REPOSITORIO**, verificable en `main`:

| Control | Dónde vive | Estado |
|---|---|---|
| Advertencia al observador sobre ausencia y cobertura | [Manual del observador](../piloto-0-1/manual-del-observador.md) §5 | **Existe.** Enumera la sede no cubierta entre las causas posibles |
| **A6** — capacidad indisponible → `PARTIAL`/`ERROR` + `capability_unavailable`, nunca `NO_EVIDENCE` | `tests/test_absence_safety.py` | **Activa en CI** |
| **A6b** — `NOT_RETURNED` no autoritativo → `NO_EVIDENCE` + `code_not_found_in_source`, con el texto verificado aparte | `tests/test_absence_safety.py` | **Activa en CI** |
| **A18** — ninguna ruta alcanzable afirma inexistencia; guarda comprobada en **las dos direcciones** | `src/elsa/core/capability_outcomes.py`, `tests/test_absence_safety.py` | **Activa en CI** |
| **A19** — `NO_ACTIVE_INVENTORY` → `ERROR` + `inventory_unavailable`, nunca `NO_EVIDENCE` | `tests/test_absence_safety.py` | **Activa en CI** |
| Ausencia `authoritative = true` **rechazada**, no interpretada | `interpret_inventory_lookup` | **Activa en CI** |
| `REJECTED` **no se compone** como evidencia | `interpret_inventory_lookup` | **Activa en CI** |
| Un resultado ilegible **falla** en vez de degradar a `NO_EVIDENCE` | `UncomposableOutcomeError` | **Activa en CI** |

Su cierre está documentado en
[el cierre del subbloque 5.0.c.1](../bloque-5-0-c-1-politica-ausencia-segura-cierre.md).

Y [ADR 0022](0022-feedback-e-incident-snapshot-del-piloto.md) §21 había fijado,
por escrito y de antemano, qué haría falta:

> «Esas pruebas son **controles compensatorios necesarios** si más adelante se
> propusiera que M8 deje de bloquear el piloto. **Cualquier cambio futuro del
> carácter bloqueante de M8 requiere otro ADR** (regla 25).»

**La precondición está cumplida y el mecanismo exigido es este documento.**

### 5. Evidencia real medida, y qué no demuestra

**HECHO MEDIDO** en la comprobación real PC1 (D23), sobre una muestra de 30
códigos reales de Tampella. **No se transcribe aquí ningún código**, conforme a
la regla 12 de [`CLAUDE.md`](../../CLAUDE.md).

| Observación | Valor |
|---|---|
| Códigos de la muestra | 30 |
| Llamadas que respondieron sin error | **30 de 30** |
| Devolvieron coincidencia **exacta** | 27 |
| Devolvieron resultados **sin código exacto** | 3 |
| Naturaleza de esos 3 | exclusivamente HTM-only: `BOM=False`, `AMEF=False`, `HTM=True` |

**Qué demuestra, y nada más:**

1. La integración real **puede** devolver coincidencias exactas.
2. **También existen casos en que una búsqueda devuelve resultados que no son
   el código pedido.**
3. Por tanto el sistema **necesita distinguir** una coincidencia exacta de un
   conjunto de resultados aproximados.

**Qué NO demuestra, y debe decirse con la misma claridad:**

- **No demuestra cobertura completa.** 27 de 30 es una muestra, no un censo, y
  ninguna muestra puede demostrar el ámbito de un snapshot.
- **No demuestra una tasa de acierto esperable.** La muestra no fue diseñada
  como estimador.
- **No convierte los 3 casos en «materiales inexistentes».** Son códigos para
  los que esa consulta no devolvió coincidencia exacta. Nada más.
- **No demuestra equivalencia** entre un resultado aproximado y el código
  pedido (§9, regla C.4).

Los 3 casos son la **confirmación empírica** del modo de fallo que
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §2 anticipó sobre
prosa: una consulta que no coincide literalmente **cae en silencio** a
similitud sobre la descripción. Dejan de ser un riesgo teórico.

> La comprobación M5 (JWKS, algoritmo de firma, login y llamadas autenticadas)
> se ejecutó en el mismo bloque y **no es objeto de este ADR**. No se declara
> aquí ningún avance de M5.
>
> **Estado, 2026-09-19.** Esa comprobación, y la medición M3 completa de la que
> la tabla de arriba es solo el cruce final, están registradas en
> [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md). **Este ADR no
> cambia**: sigue sin declarar ningún avance de M5, y lo que decide —que M8
> deja de ser puerta previa a liberar— **no depende de M3 ni de M5**, como su
> §14 argumenta.

### 6. Hechos que este ADR no altera

Se enumeran porque el resto del documento se apoya en ellos y ninguno puede
deducirse del otro.

1. Materiales **no dispone hoy** de metadata suficiente para demostrar
   cobertura completa.
2. Por tanto la cobertura **no puede llamarse `KNOWN_COMPLETE`**.
3. **Tampoco `KNOWN_INCOMPLETE`**, salvo que una fuente concreta lo demuestre
   para un alcance y un versionado determinados.
4. **El estado general disponible hoy es `UNKNOWN`.**
5. `NOT_RETURNED` **no significa** que el material no exista.
6. Un resultado aproximado **no demuestra** equivalencia con el código pedido.
7. `loaded_at` demuestra **cuándo terminó una carga en Materiales**. No
   demuestra fecha de extracción desde SAP
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §9.2).
8. `extracted_at` **no está disponible**.
9. `observed_scope` y la metadata de cobertura **no están disponibles**.
10. Ninguna exclusión histórica de un centro puede convertirse en **constante
    del código**. Sin metadata ni versionado que la sustente, sería una
    afirmación de cobertura sin procedencia, que es justo lo que
    [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.4 prohíbe.
    **Este ADR no nombra ningún centro.**

### 7. El problema, enunciado con precisión

M8 bloqueaba por una razón sensata: sin saber qué cubre el inventario, ELSA
podría afirmar algo que solo es cierto si la cobertura es completa.

Pero M8 depende de **un tercero**. Exige que Materiales produzca metadata de
cobertura, o que alguno de los tres motivos reservados de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3 adquiera un
mecanismo que lo demuestre. Hoy **ninguna de las dos cosas tiene dueño
asignado** —el ocupante del rol Contract Owner sigue pendiente (M7)— **ni
fecha**.

Sostener la puerta ahí significa condicionar el piloto a un trabajo ajeno,
sin dueño y sin plazo, **para protegerse de un riesgo que ELSA puede
neutralizar por sí sola**: basta con que **ninguna respuesta de ELSA dependa de
una cobertura que nadie demostró**.

---

## Decisión

### 8. Conclusión: M8-A

> **M8 deja de ser puerta previa a liberar el Piloto 0.1**, y **B9a, B9b y B9c
> (§14) ocupan su lugar como puertas.**
>
> La cobertura `UNKNOWN` se acepta para V1 bajo controles compensatorios,
> siempre que **ninguna capacidad trate una ausencia o un no-match como prueba
> de inexistencia**, y que **toda consulta que exigiría cobertura completa se
> resuelva de forma determinista sin producir una respuesta factual completa**.
>
> **Esto no libera nada por sí solo.** B9a, B9b y B9c deben estar
> **implementadas y probadas** antes de liberar las capacidades afectadas.

**Qué NO significa esta decisión.** Se enumera porque cada línea es una
confusión posible:

| No significa | Estado real |
|---|---|
| **M8 está cerrado** | **No.** M8 sigue **ABIERTO**. Su criterio de cierre es [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3 —que alguno de los tres motivos reservados adquiera un mecanismo demostrable— y **no se ha cumplido ninguno** |
| Materiales tiene cobertura completa | **No.** La cobertura es `UNKNOWN` y se declara como tal (§6) |
| La cobertura dejó de importar | **Al contrario.** Pasa a ser una restricción **activa y verificable** sobre lo que ELSA puede afirmar (§10) |
| Ya no queda nada bloqueante aquí | **No.** M8 es sustituido por tres condiciones nuevas, **propias de ELSA** (§14) |
| ADR 0021 §8.3 se reabre o se debilita | **No.** Queda intacto y sin cumplir |
| Se puede activar la prueba A6c | **No.** Sigue **desactivada** mientras M8 siga abierto (§13) |

**La puerta no desaparece: se traslada.** De «Materiales debe demostrar su
cobertura» —externo, sin dueño, sin fecha— a «ELSA no debe emitir ninguna
afirmación que requiera cobertura» —interno, acotado y comprobable con el fake
contractual, sin depender de M3 ni de M5.

### 9. Las afirmaciones dependientes de cobertura son de dos clases

Toda la decisión descansa en esta distinción, que el corpus no había separado.

| Clase | Definición | Ejemplo de forma | Tratamiento |
|---|---|---|---|
| **Clase 1 — acotable** | Se vuelve verdadera **acotándola a la fuente y al snapshot** que la produjeron | «Según el inventario cargado en Materiales en su versión N, este código tiene M unidades en las ubicaciones devueltas» | **Permitida**, degradada según [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §13 (§10.1) |
| **Clase 2 — no acotable** | Cuantifica sobre un universo **cuyo alcance se desconoce**. Ninguna acotación la vuelve verdadera | «No existe», «no hay en ningún almacén», «estos son todos los materiales que tenemos», «no tenemos stock en ninguna parte» | **Prohibida.** No se degrada: se rechaza (§10.2) |

La diferencia no es de grado. Una afirmación de Clase 1 con cobertura
`UNKNOWN` es **incompleta y se marca**. Una afirmación de Clase 2 con cobertura
`UNKNOWN` es **infundada**, y marcarla no la arregla: seguiría afirmando algo
sobre un universo que nadie ha delimitado.

> **Por qué `PARTIAL` no basta para la Clase 2.** `PARTIAL` significa
> «respuesta con respaldo incompleto». Una afirmación universal sobre un
> universo desconocido no tiene respaldo incompleto: **no tiene respaldo**. Un
> aviso junto a ella la haría parecer una verdad matizada.

### 10. Regla A y regla B — consultas según exijan o no cobertura completa

La propiedad que separa un caso del otro es
`requires_complete_inventory_coverage`, ya decidida en
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §12: **determinista,
propiedad de la plantilla del plan, y no la decide un LLM**. Este ADR no la
redefine.

#### 10.1 Regla A — la consulta **no** exige cobertura completa

`requires_complete_inventory_coverage = false`.

1. **`coverage = UNKNOWN` puede utilizarse.** No impide responder.
2. La respuesta **conserva semántica no autoritativa**: se atribuye a la fuente
   y al snapshot, nunca al mundo
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §10.6).
3. **Un no-match exacto nunca implica inexistencia**, cualquiera que sea el
   estado de cobertura.
4. **ELSA nunca afirma cobertura**, ni siquiera implícitamente
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.5).
5. Debe **poder propagarse** el aviso `coverage_unknown` cuando la afirmación
   emitida sea de Clase 1 y la cobertura sea relevante según
   [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §12.1.
6. La cobertura **no degrada por sí sola** cuando la respuesta solo afirma
   campos estables —descripción, unidad—
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §12.1). Degradar
   ahí sería ruido, y el ruido enseña a ignorar los avisos.

#### 10.2 Regla B — la consulta **sí** exige cobertura completa

`requires_complete_inventory_coverage = true` y `coverage != KNOWN_COMPLETE`.

1. **No se produce una respuesta factual completa.** Nunca.
2. **Clase 1** → se responde acotado y **degradado de forma determinista**:
   `PARTIAL` + `coverage_unknown` bajo `UNKNOWN`, `PARTIAL` +
   `coverage_incomplete` bajo `KNOWN_INCOMPLETE`
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §13, sin
   cambios). **`UNKNOWN` no se presenta como `INCOMPLETE`**
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §13.2).
3. **Clase 2** → **se declara incapaz de forma determinista**, con la taxonomía
   ya existente y sin crear ningún `AnswerStatus` nuevo. La respuesta dice qué
   consultó y qué no puede concluir. **No se emite la afirmación, ni degradada,
   ni acompañada de aviso.**
4. **Ninguna plantilla del Piloto 0.1 puede producir una afirmación de Clase
   2** mientras la cobertura no sea `KNOWN_COMPLETE`. Añadir una plantilla que
   la produzca queda **prohibido** sin un ADR que lo autorice.
5. **El LLM no puede ignorar esta restricción, ni puede levantarla.** No
   participa en decidir `requires_complete_inventory_coverage`, no decide el
   estado de la respuesta y no redacta los valores factuales
   ([ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §14, y
   §15 de este ADR).

> **Comprobación hecha sobre el alcance real del piloto.** Las cinco plantillas
> del [contrato funcional](../piloto-0-1/contrato-funcional.md) §2.2 se
> revisaron contra esta regla. **Ninguna produce una afirmación de Clase 2.**
> `asset_components_with_availability` enumera sobre el **BOM publicado**, que
> es fuente propia de ELSA y completa por construcción respecto de sí misma;
> Materiales solo aporta disponibilidad **por código**, nunca la enumeración. Y
> la redacción obligatoria del §6 de ese contrato —«Encontré N elementos del
> BOM publicado…»— ya acota toda enumeración a su fuente.
>
> Es decir: **el piloto, tal como está acotado hoy, no contiene ninguna consulta
> que la regla B tenga que rechazar.** Eso es lo que hace la decisión
> sostenible, y no un acto de fe.

### 11. Regla C — composición BOM → Materiales

1. Los códigos consultados proceden **únicamente de un activo previamente
   autorizado**, por el encadenamiento por campo declarado de
   [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §5. ELSA
   no envía a Materiales ningún código que no haya salido de un BOM publicado
   al que el usuario tenga acceso.
2. **Las coincidencias exactas pueden utilizarse** como hechos, con su
   atribución por hecho
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §10.6).
3. Los códigos sin coincidencia exacta quedan como **«no devuelto por esta
   fuente en esta consulta»**, nunca como «inexistentes».
4. **No se hace fuzzy matching como equivalencia de código.** Un resultado
   aproximado **no es** el código pedido. Bajo la superficie actual, una
   consulta que devuelve filas **sin el código exacto** se trata como
   `NOT_RETURNED`, **jamás** como `MATCHED` y **jamás** como candidato
   promovido a hecho. Es la lectura directa de los 3 casos medidos en §5, y
   ejerce lo que [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §2 y
   §6 ya decidieron.
5. **Si existe evidencia útil parcial, el resultado es `PARTIAL`**, con
   `code_not_found_in_source`
   ([ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §13). Ya
   está implementado y probado: es el caso `other_facts_available = True` de
   `interpret_inventory_lookup`.
6. **La ausencia en Materiales no destruye la evidencia BOM ya válida.** Lo que
   el BOM publicado afirma sigue afirmándose, con su propia procedencia. Un
   fallo o un vacío de la segunda fuente **no invalida la primera**.

### 12. Regla D — búsqueda directa en Materiales

1. No-match exacto con `coverage = UNKNOWN` y sin ninguna otra parte factual
   resuelta → **`NO_EVIDENCE` + `code_not_found_in_source`**
   ([ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §13,
   [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §21.3). **Ya
   implementado y probado** (A6b).
2. **Jamás «el material no existe»**, ni ninguna variante suya. La guarda A18
   lo comprueba sobre **toda salida alcanzable**, en las dos direcciones.
3. El texto dice **lo que la fuente hizo**, no lo que eso significa: «la fuente
   consultada no devolvió el material solicitado».
4. `NO_EVIDENCE` **no es un fallo**: es una respuesta legítima, y así lo explica
   el [manual del observador](../piloto-0-1/manual-del-observador.md) §6.

### 13. La ausencia autoritativa sigue rechazada

**Invariante del que depende toda esta decisión.**

Mientras M8 siga abierto:

- un resultado con `absence_is_authoritative = true` **no es interpretable** y
  se rechaza con excepción explícita;
- la prueba **A6c** del [contrato funcional](../piloto-0-1/contrato-funcional.md)
  §12 permanece **desactivada y documentada como tal**;
- ningún motivo de ausencia de
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3 puede
  activarse.

> **Si alguien reactivara A6c o admitiera una ausencia autoritativa con M8
> abierto, esta decisión quedaría sin fundamento** y el piloto volvería a estar
> bloqueado. El invariante no es una cautela redundante: es la condición de
> validez de este ADR.

### 14. Qué sustituye a M8 como bloqueante

M8 sale de la lista de bloqueantes del
[contrato funcional](../piloto-0-1/contrato-funcional.md) §10 (**B9**). Entran
tres condiciones en su lugar.

| Id | Condición | Tipo |
|---|---|---|
| **B9a** | `requires_complete_inventory_coverage` **implementada** como propiedad determinista de la plantilla ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §12), derivada de los campos que la composición va a afirmar y **no decidida por un LLM** | Código |
| **B9b** | Los avisos `coverage_unknown` y `coverage_incomplete` **disponibles** en `AnswerWarning` y emitidos según [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §13, **sin confundirse entre sí** | Código |
| **B9c** | Pruebas automáticas **A20**, **A20b** y **A21** (§14.1), activas en integración continua | Código |

**Las tres son puertas operativas, no mejoras deseables.** Ninguna capacidad
que pueda emitir una afirmación dependiente de cobertura (§9) se libera a un
tester antes de que **las tres estén implementadas y probadas en integración
continua**. Retirar B9 sin ellas dejaría el riesgo R4 del
[contrato funcional](../piloto-0-1/contrato-funcional.md) sin ningún control
ejecutable, que es exactamente lo que esta decisión evita.

**Por qué esto no es M8 con otro nombre**, que es la objeción obvia:

| | **B9 (M8)** | **B9a–B9c** |
|---|---|---|
| De quién depende | **De Materiales**, un tercero | **De ELSA** |
| Dueño asignado | **No** (M7 pendiente) | Sí: el propio proyecto |
| Fecha | **Ninguna** | Acotada |
| Cómo se verifica | Requiere metadata que no existe | **Con el fake contractual**, sin red y sin datos reales |
| Depende de M3 o M5 | Sí | **No** — mismo argumento de [ADR 0022](0022-feedback-e-incident-snapshot-del-piloto.md) §19 para A6/A6b/A18/A19 |

#### 14.1 Criterios de aceptación nuevos

Se añaden a la tabla del [contrato funcional](../piloto-0-1/contrato-funcional.md)
§12, en el formato «acción → resultado observable» que ya usa.

| Id | Acción | Resultado esperado |
|---|---|---|
| **A20** | Afirmación de **Clase 1** con `requires_complete_inventory_coverage = true` y cobertura `UNKNOWN` | `PARTIAL` + `coverage_unknown`. **Nunca** `coverage_incomplete`, **nunca** `ANSWERED` |
| **A20b** | Lo mismo con `requires_complete_inventory_coverage = false` y solo campos estables afirmados | **No** se degrada por cobertura |
| **A21** | Revisión de todo texto que la plantilla pueda generar | **Ninguna cadena alcanzable** emite una afirmación de **Clase 2** (§9) sobre Materiales. Se verifica **estado y texto por separado**, como exige [ADR 0022](0022-feedback-e-incident-snapshot-del-piloto.md) §19 |

**A21 es a la cobertura lo que A18 es a la inexistencia**, y se construye igual:
comprobada en las dos direcciones, para que no pueda volverse vacua en silencio.

**Este ADR no las implementa.** Fijarlas es su objeto; construirlas es trabajo
posterior a este ADR, autorizado aparte y **previo a liberar** las capacidades
afectadas (§14).

### 15. El LLM no puede levantar ninguna de estas restricciones

Sin cambios respecto de
[ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §14, y se
repite aquí porque es donde importa:

- el LLM **no decide** `requires_complete_inventory_coverage`;
- **no decide** el `AnswerStatus` ni los avisos;
- **no redacta** los valores factuales, que se renderizan por plantilla desde
  el dato;
- **no puede** convertir un resultado aproximado en una identificación.

La degradación y el rechazo ocurren **antes** de que exista texto. No hay
ninguna ruta en la que un modelo pueda decidir ignorar la regla B, porque la
regla B se aplica sobre datos, no sobre prosa.

### 16. Regla E — camino conceptual de la metadata futura

**Diseño conceptual. No se implementa nada aquí, y no se inventa ningún valor
actual.** Los cuatro campos **ya existen reservados** en
[ADR 0021](0021-contrato-de-inventario-con-materiales.md); este ADR **no crea
un vocabulario paralelo**, solo declara qué haría falta para poblarlos y qué
desbloquearía cada uno.

| Concepto | Nombre contractual ya existente | Hoy | Qué exigiría para poblarse | Qué desbloquearía |
|---|---|---|---|---|
| `coverage_status` | `coverage.state` ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.1) | **`UNKNOWN`** | Que Materiales declare `expected_scope` **y** respalde `observed_scope` con metadata de ingestión | `KNOWN_COMPLETE` sobre el **ámbito declarado**, nunca «cobertura corporativa completa» |
| `observed_scope` | `coverage.observed_scope` ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.2) | **No disponible** | Metadata de **ingestión**, no conteo de filas: qué ámbito declaró cubrir la carga | Distinguir `KNOWN_INCOMPLETE` de `UNKNOWN`, y activar `coverage_incomplete` con evidencia |
| `extracted_at` | `inventory.extracted_at` ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §9.3) | **Nulo y reservado** | Un mecanismo que **registre** la extracción desde SAP. **Nunca se infiere de `source_file_label`** | Afirmar edad real del dato; hoy solo puede decirse «cargado en Materiales el …» |
| `inventory_version` | `inventory.version_number` + `loaded_at` ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §9.1) | **Disponible** | — | Ya sostiene la vigencia; **no** sostiene la cobertura. Son ejes independientes ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §12) |

Tres restricciones sobre ese camino, vinculantes desde ya:

1. **Poblar un campo reservado es un cambio compatible**
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §15.1). El camino
   no exige romper el contrato.
2. **Ningún ámbito concreto se codifica en ELSA**, ni ahora ni después
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.4). La
   cobertura se **determina** comparando declaraciones, y cambia con cada carga
   sin tocar código.
3. **Mientras la metadata no exista, el estado es `UNKNOWN`**, aunque se
   observen ámbitos en las filas
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.2). Derivar
   cobertura de datos de negocio produciría una afirmación sin procedencia.

Que la metadata llegue algún día **no cierra M8** por sí sola: cerrarlo exige
además un mecanismo que demuestre alguno de los tres motivos reservados de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3.

---

## Consecuencias

### 17. Qué cambia en los documentos existentes

**Cambios mínimos, solo de estado y referencia.** Ningún cuerpo normativo se
reescribe, y **ningún documento de cierre se toca**: son registros históricos.

| Documento | Cambio |
|---|---|
| [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §17 | Nota: M8 deja de ser puerta previa a liberar por este ADR. **La restricción del §12 sigue rigiendo sin cambios** |
| [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §25 | Nota junto a la tabla: M8 sigue **abierto** y deja de ser bloqueante. **§8.3 no se toca** |
| [ADR 0022](0022-feedback-e-incident-snapshot-del-piloto.md) §21 | Nota: el ADR posterior que ese apartado exigía **es este**, y su precondición está cumplida |
| [Contrato funcional](../piloto-0-1/contrato-funcional.md) §10, §13, §14 | **B9** sustituido por **B9a–B9c**; R2 y R4 actualizados; §14 refleja el estado real de M8 |

**No se modifica** el [manual del observador](../piloto-0-1/manual-del-observador.md):
su §5 ya dice exactamente lo que debe decir, incluida la sede no cubierta entre
las causas posibles. Cambiarlo sería empeorarlo.

### 18. Qué queda abierto después de esta decisión

| # | Pendiente | Estado |
|---|---|---|
| 1 | **M8** | **ABIERTO.** Criterio de cierre: [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3, **no cumplido**. Deja de ser bloqueante, **no se cierra** |
| 2 | **B9a, B9b, B9c** | **Bloqueantes nuevos**, propios de ELSA (§14). **Puertas previas a liberar** las capacidades afectadas: implementadas y probadas antes del primer tester |
| 3 | **Estado de los demás puntos del contrato con Materiales (M1–M7)** | **Fuera del alcance de este ADR.** No se declaran aquí: los gobiernan sus propios subbloques |
| 4 | **D20** — retención del Incident Snapshot | **ABIERTA y puerta previa a liberar**, sin cambio |
| 5 | Fachada contractual, `MaterialsPort` real, adaptador, endpoints, plan de capacidades | **No existen.** Fuera del alcance de este ADR |
| 6 | Documento de cierre del subbloque | **Obligatorio** (regla 26) cuando el subbloque se declare cerrado. Este ADR **no lo es** |

**La cobertura seguirá siendo `UNKNOWN` después de aprobar este ADR.** Esa es
precisamente la situación que se acepta, no una que se resuelva.

### 19. Riesgos

| Riesgo | Mitigación |
|---|---|
| Leer «deja de bloquear» como «M8 cerrado» | §8: tabla explícita de lo que **no** significa, y §18 que lo repite |
| Que alguien active un motivo de ausencia reservado | [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3 intacto; A6c desactivada; ausencia autoritativa rechazada en código (§13) |
| Que aparezca una plantilla que afirme de Clase 2 | §10.2, regla 4: prohibido sin ADR. **A21** lo comprueba sobre texto alcanzable |
| Que `UNKNOWN` se presente como `INCOMPLETE`, o al revés | Avisos distintos y no intercambiables ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §13.2); **A20** lo fija |
| Que un resultado aproximado se promueva a hecho | §11.4; [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §2 y §6; evidencia medida en §5 |
| Que la exclusión histórica de un centro se codifique como constante | §6.10 y [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.4. Este ADR no nombra ningún centro |
| Ruido de avisos que enseñe a ignorarlos | §10.1.6: la cobertura solo degrada cuando es **relevante** ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §12.1) |

**El riesgo que este ADR NO mitiga.** Que un material exista en un ámbito que
el snapshot no cubrió y ELSA no lo devuelva. **Eso seguirá ocurriendo**, y no
hay control compensatorio que lo impida: solo lo resolvería la cobertura real.

Lo que sí se garantiza es que **ese caso nunca se presente como una
inexistencia**, y que el observador esté advertido de que debe comprobarlo por
sus canales habituales si necesita certeza
([manual del observador](../piloto-0-1/manual-del-observador.md) §5). Es una
transferencia de riesgo **declarada**, no una ocultación.

### 20. Alternativas descartadas

| Alternativa | Por qué se descarta |
|---|---|
| **Mantener M8 bloqueante** | Condiciona el piloto a trabajo de un tercero sin dueño ni fecha (§7), para protegerse de un riesgo que ELSA ya neutraliza por sí sola. El piloto existe para producir la evidencia con la que después se decide |
| **Declarar la cobertura `KNOWN_INCOMPLETE`** | Sería afirmar incompletitud **sin evidencia**: el mismo error que el corpus combate, en espejo ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §13.2). Ninguna fuente lo demuestra hoy (§6.3) |
| **Declarar la cobertura `KNOWN_COMPLETE` apoyándose en el 27 de 30 medido** | Una muestra no demuestra un ámbito (§5). Sería una afirmación de cobertura sin procedencia, prohibida por la regla 2 de [`CLAUDE.md`](../../CLAUDE.md) |
| **Codificar la exclusión conocida de un centro como constante** | Sin metadata ni versionado que la sustente, convierte una observación fechada en una verdad permanente (§6.10) |
| **Degradar también la Clase 2 a `PARTIAL` en vez de rechazarla** | Un aviso junto a una afirmación infundada la hace parecer una verdad matizada (§9) |
| **Cerrar M8 aprovechando este ADR** | Su criterio de cierre exige un **mecanismo demostrable**, no una decisión ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3). Cerrarlo por decreto sería exactamente lo que ese apartado prohíbe |

### 21. Trazabilidad de los requisitos de este ADR

| # | Requisito | Sección |
|---|---|---|
| 1 | Pregunta que se responde | §1 |
| 2 | Auditoría normativa del estado de M8 | §2, §3 |
| 3 | Controles compensatorios existentes y verificables | §4 |
| 4 | Evidencia real medida, y qué no demuestra | §5 |
| 5 | Hechos no alterables | §6 |
| 6 | Problema | §7 |
| 7 | **Conclusión M8-A** | §8 |
| 8 | Clases de afirmación dependiente de cobertura | §9 |
| 9 | **Regla A** — no exige cobertura completa | §10.1 |
| 10 | **Regla B** — sí exige cobertura completa | §10.2 |
| 11 | **Regla C** — composición BOM → Materiales | §11 |
| 12 | **Regla D** — búsqueda directa | §12 |
| 13 | Ausencia autoritativa sigue rechazada | §13 |
| 14 | Qué sustituye a M8 como bloqueante | §14 |
| 15 | Criterios de aceptación A20, A20b, A21 | §14.1 |
| 16 | Frontera con el LLM | §15 |
| 17 | **Regla E** — metadata futura, conceptual | §16 |
| 18 | Cambios mínimos en documentos existentes | §17 |
| 19 | Qué queda abierto | §18 |
| 20 | Riesgos, y el que no se mitiga | §19 |
| 21 | Alternativas descartadas | §20 |

## Ver también

- [ADR 0020 — Capacidades componibles y planes de ejecución controlados](0020-capacidades-componibles-y-planes-de-ejecucion.md)
- [ADR 0021 — Contrato de inventario con Materiales (V1)](0021-contrato-de-inventario-con-materiales.md)
- [ADR 0022 — Feedback, observabilidad e Incident Snapshot del Piloto 0.1](0022-feedback-e-incident-snapshot-del-piloto.md)
- [Contrato funcional del Piloto 0.1](../piloto-0-1/contrato-funcional.md)
- [Manual del observador](../piloto-0-1/manual-del-observador.md)
- [Cierre del subbloque 5.0.c.1](../bloque-5-0-c-1-politica-ausencia-segura-cierre.md)
