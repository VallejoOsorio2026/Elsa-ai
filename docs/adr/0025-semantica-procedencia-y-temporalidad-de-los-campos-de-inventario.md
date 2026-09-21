# ADR 0025 — Semántica, procedencia y temporalidad de los campos de inventario (V1)

- Estado: **aceptado**
- Bloque: 5.0, subbloque **5.0.b**, punto **M6**
- **Decide la semántica contractual de los campos** que
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §22 dejó diferida en
  su fila 4, sobre la evidencia primaria registrada en
  [la evidencia M6](../piloto-0-1/evidencia-m6-semantica-temporalidad.md)
- **Reemplaza**, de [ADR 0021](0021-contrato-de-inventario-con-materiales.md):
  la enumeración cerrada de **cuatro** clases de procedencia del §10, y la
  premisa fáctica del §10.3 sobre la priorización. **Nada más de aquel ADR se
  toca**
- **No toca** §7.3, §8.3, **§9** ni §15 de
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md), y **no gobierna**
  M1, M4, M8, B9a–B9c, D20 ni ONNX
- Conserva sin cambios los estados de respuesta de
  [ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md) y las
  decisiones de [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
- **No cierra M6 operacionalmente**, y **no cierra el subbloque 5.0.b** (§15)
- **No aprueba, y no contiene, ninguna implementación**: ni fachada, ni
  `MaterialsPort`, ni adaptador, ni endpoint, ni cambio alguno en Materiales
- Aplica las reglas **2, 4, 6, 12, 21, 22, 23 y 25** de
  [`CLAUDE.md`](../../CLAUDE.md)

---

## Contexto

### 1. Qué quedó diferido, y por qué

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) fijó la forma del
contrato de inventario, pero dejó explícitamente abierta la **semántica
completa** de varios campos (§22, fila 4), porque en aquel momento nadie había
leído la implementación de Materiales. M6 quedó **parcial y bloqueante** (§25).

Esa lectura ya existe.
[La evidencia M6](../piloto-0-1/evidencia-m6-semantica-temporalidad.md) registra
la auditoría de solo lectura del repositorio de Materiales en
`b0cb12b4440d95b5c4ec0a64ca619b31b36e26c3`, y separa lo verificado de lo que
sigue sin versionarse. **Este ADR decide sobre esa evidencia**, no sobre
supuestos.

### 2. El principio que gobierna todo el documento

> La implementación observada **informa** la decisión; **no la sustituye**.

Materiales es propietario de su inventario (regla 4), y el contrato describe
**lo que la fachada deberá cumplir**, no lo que hoy hace su buscador.
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §1 ya decidió que
ELSA no consume esa superficie. De ahí dos consecuencias que se aplican en cada
apartado:

- que algo funcione hoy de una manera **no lo convierte en contrato**;
- que algo no esté versionado hoy **no impide decidir la norma**; impide
  comprobar conformidad, que es otra cosa.

### 3. Dos huecos que no bloquean esta decisión

En la revisión auditada **no están versionadas** las definiciones de la función
de consulta que invoca el cliente de Materiales (**P1**) ni la de la función que
aplica la regla de baja (**P2**). Ambas se invocan y ambas existen en el sistema
desplegado; lo que falta es su definición en el repositorio.

**Ninguno de los dos impide decidir.** P1 impedirá comprobar si la
implementación actual satisface el vocabulario del §9; P2 impedirá que
`rule_verifiable` pueda valer `true` para un campo que este ADR declara **no
accionable**, donde esa verificabilidad deja de ser una puerta (§4).

---

## Decisión

### 4. `dado_de_baja` es una señal no accionable

Permanece en el contrato V1, con su clase `DERIVED_BY_MATERIALES` y su
`rule_verifiable: false`, **y con su uso restringido de forma verificable**:

| Puede | No puede |
|---|---|
| Acompañar un hecho como **advertencia** al ingeniero | Ser el hecho, ni sostener por sí solo el núcleo factual de una respuesta |
| Renderizarse por plantilla junto al material | Excluir, ocultar o filtrar ningún material |
| — | Alterar el orden, la selección, la puntuación o cualquier decisión de ELSA |
| — | Degradar un `AnswerStatus` ni emitir aviso propio |

**Por qué `rule_verifiable: false` deja de ser una puerta.**
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §18 exige que toda
derivación con `rule_verifiable: true` quede demostrada por una prueba
contractual del proveedor. Una señal que **no puede sostener ninguna
afirmación** no necesita esa demostración: lo que hay que probar es que ELSA no
la usa para decidir, y eso **se prueba en ELSA**.

#### 4.1 Corrección de una premisa de ADR 0021 §10.3

**HECHO VERIFICADO.** Aquel apartado afirma que el material marcado «no se
oculta **ni se desprioriza**», y lo presenta como descripción de lo que hace
Materiales. La segunda mitad **no es exacta**:

> **Materiales sí desprioriza hoy.** La superficie agrupada auditada ordena por
> el indicador de baja en sentido ascendente, de modo que los marcados quedan
> **al final** de la lista. La regla de negocio publicada por Materiales declara
> ese tratamiento de forma expresa.

**No se ocultan** —esa mitad sí es exacta, y es lo que importa— pero sí se
desprioriza.

**Esta corrección no cambia la norma de ELSA.** La regla contractual sigue
siendo la del §4: la señal es **no accionable**, y ELSA no altera por ella
ningún orden, ninguna selección y ninguna decisión. Lo que se corrige es la
**descripción de la fuente**, no la obligación del consumidor.

#### 4.2 La priorización es brecha de implementación, no contrato

El orden en que Materiales devuelve candidatos **no entra en el contrato V1**, y
por una razón de alcance, no de conveniencia: la operación obligatoria de V1 es
`lookup_material_by_code`, que responde por un código;
`search_materials_by_text`, donde el orden importaría, está **fuera del Piloto
0.1 inicial** ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §2).

Queda registrada como **brecha de implementación** (§12, **B5**) para cuando esa
operación entre en alcance.

### 5. Una quinta clase de procedencia, para lo factual agregado

**Reemplaza la enumeración cerrada de cuatro clases de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §10.** Cada campo
sigue perteneciendo a **exactamente una** clase; las clases pasan a ser
**cinco**.

La razón es un hecho verificado: en la superficie agrupada auditada,
`descripcion`, `unidad` y `material_antiguo` se obtienen mediante agregaciones
**independientes por campo** sobre el grupo, de modo que el código **no
garantiza** que procedan de una misma fila de origen.

La clase nueva es **`FACTUAL_SAP_AGGREGATED`**:

| Aspecto | Regla |
|---|---|
| Qué es | Un valor **factual de SAP** presente en **alguna** fila del grupo, seleccionado por una agregación declarada |
| Qué **no** es | El valor de una fila concreta. **Prohibido presentarlo como tal** |
| Qué acompaña obligatoriamente | La **agregación que lo produjo**, declarada por Materiales |
| Qué prohíbe | Combinar dos campos de esta clase afirmando que describen la misma fila |

**`FACTUAL_SAP` se conserva con su significado fuerte**: valor de una columna de
SAP **de una fila concreta**, con su transformación declarada. **No se
debilita**, que es justamente la alternativa que se descarta en §17.

**Reparto en V1:**

| Clase | Campos |
|---|---|
| `FACTUAL_SAP` | `material`, `centro`, `almacen`, `ubicacion` |
| `FACTUAL_SAP_AGGREGATED` | `descripcion`, `unidad`, `material_antiguo` |

La clase **depende de cómo se produjo el valor, no del nombre del campo**: si
una operación futura devolviera una fila sin agregar, esos tres campos serían
`FACTUAL_SAP` en ella.

> **`max()` sobre texto es máximo lexicográfico.** No representa una selección
> por recencia ni por ninguna otra propiedad temporal, y **queda prohibido
> presentarla como tal**.

### 6. Sensibilidad al snapshot: una propiedad binaria

Cada campo del contrato declara **`snapshot_sensitive: boolean`**. Nada más.

**Qué significa:** el campo exige un inventario vigente para que la afirmación
que lo use sea sólida. Un campo no sensible sigue siendo informativo aunque el
snapshot sea antiguo; uno sensible, no.

| `snapshot_sensitive` | Campos V1 |
|---|---|
| **`true`** | `disponible`, `comprometido`, `total_disponible`, `total_comprometido`, y el contenedor `stock_locations` del §8.2 con todos sus elementos |
| **`false`** | `descripcion`, `unidad`, `material_antiguo`, `centro`, `almacen`, `ubicacion`, `ambito` |

**Qué habilita.** `requires_fresh_inventory`
([ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §11.1,
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §11) se deriva de
forma determinista: es `true` si y solo si la plantilla declara afirmar **algún**
campo con `snapshot_sensitive: true`. **No la decide un LLM.**

**Qué se descarta, y por qué.** Se descarta una taxonomía por momento de
determinación —valor de carga, derivado en consulta, agregado en consulta—.
Describe mejor cómo se produce cada valor y **no habilita ninguna decisión
adicional**: la respuesta a «¿degrado por vigencia?» es idéntica con ella y sin
ella. Además envejecería mal, porque Materiales puede mover un cálculo de la
carga a la consulta sin cambiar nada de lo que ELSA afirma.

**Esto no reabre [ADR 0021](0021-contrato-de-inventario-con-materiales.md)
§12.** Vigencia y cobertura siguen siendo ejes independientes, y un campo puede
ser sensible al snapshot sin serlo a la cobertura.

### 7. `ambito` no es cobertura, y se prohíbe usarlo como tal

`ambito` es una **clasificación de la ubicación de una fila**, con vocabulario
cerrado publicado por Materiales, determinada durante la carga y persistida. Es
`DERIVED_BY_MATERIALES`.

**Prohibiciones, verificables por prueba:**

1. `ambito` **no es** `coverage.observed_scope`, y **no puede sustituirlo**.
2. **Prohibido derivar cobertura** de los valores de `ambito` presentes en un
   resultado: contar ámbitos distintos responde «¿de qué ámbitos llegó algo?»,
   que es una pregunta **distinta** de «¿qué ámbito cubrió esta carga?».
3. **Prohibido concluir la ausencia de un ámbito** porque no aparezca en las
   filas devueltas.
4. Mientras no exista metadata de ingestión que lo respalde, `coverage.state`
   sigue siendo `UNKNOWN`, aunque se observen ámbitos en los datos.

**Por qué se nombra explícitamente.**
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.2 ya prohíbe
derivar cobertura de datos de negocio, en abstracto. Los valores de `ambito`
**se leen como etiquetas de alcance**, y es el punto donde esa prohibición
genérica tiene más probabilidad de olvidarse. Nombrarlo cuesta una frase y una
prueba.

**Ningún ámbito concreto se codifica en ELSA**, ni ahora ni después
([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §7.4).

### 8. `ubicacion` es opaca; el contenedor agregado se nombra y se tipa

#### 8.1 Opacidad

`ubicacion` se **muestra sin interpretar**. ELSA no la analiza, no la
descompone, no la clasifica y **no deriva de ella ningún hecho**: ni ámbito, ni
cobertura, ni proximidad, ni disponibilidad.

**Lo que ya estaba normado no se repite**: su nulabilidad y su no herencia entre
filas siguen rigiendo por
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §10.1, su sensibilidad
temporal va por el §6 de este ADR, y la prohibición de inferir cobertura por
el §7.

#### 8.2 Contenedor y elemento

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) **nunca nombró** el
contenedor agregado de ubicaciones, de modo que esto **no reemplaza nada**: lo
define por primera vez.

El contenedor se llama **`stock_locations`**, que es el término que ELSA ya usa
en `AssertedInventoryField`. Evita además la ambigüedad entre un singular y un
plural indistinguibles de un vistazo y de nivel distinto.

| Concepto | Nivel | Regla |
|---|---|---|
| `ubicacion` | **Atributo de una fila** | `FACTUAL_SAP`, opaco, nulable, nunca heredado |
| `stock_locations` | **Colección tipada** | Una entrada por fila del material en el snapshot consultado |
| Elemento de `stock_locations` | **Una fila** | **Garantía de coherencia**: todos sus atributos proceden de la **misma** fila |

**La garantía de coherencia del elemento es contractual y verificable**, y es lo
que lo distingue de los escalares del §5: dentro de un elemento, los atributos
de centro, almacén, ubicación, ámbito y existencias describen la misma fila.
**ELSA puede afirmarlos juntos; los del §5, no.**

### 9. `match_origin`: vocabulario mínimo y verificable

| Valor | Significado |
|---|---|
| `EXACT_MATERIAL_CODE` | El código pedido coincide literalmente con el código del material |
| `OLD_MATERIAL_CODE` | Coincide con el código antiguo del material |
| `OTHER_MATCH` | Cualquier otra forma de coincidencia. **Nunca prueba identidad** |

**Invariante**, que [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §6
ya fijó y que aquí se hace comprobable: en `lookup_material_by_code` los únicos
valores admisibles son los dos primeros. **`OTHER_MATCH` en un lookup exacto es
una violación de contrato**, no un resultado de peor calidad.

**Tratamiento de valores desconocidos, declarado:** un consumidor que reciba un
valor que no conoce **lo trata como `OTHER_MATCH`**. Eso convierte la ampliación
futura del vocabulario en un cambio **compatible**
([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §15.1), sin renumerar
el contrato.

**Por qué el mínimo.** V1 solo necesita distinguir «es el código pedido» de «no
lo es». Fijar un vocabulario mayor acoplaría el contrato al ranking actual de
Materiales, que puede cambiar, a cambio de una información que ELSA no usa para
decidir nada en V1.

### 10. Emisión estable de campos y semántica de `null`

> **Alcance acotado, y es deliberado.** Esta regla gobierna **los campos de
> semántica M6**. **No toca
> [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §9** ni el
> precedente de `extracted_at`, que pertenecen a **M4**.

1. **Todo campo M6 definido por el contrato se emite siempre.** La ausencia de
   una clave **nunca** es una señal.
2. **`null` significa «no hay valor en la fuente para este campo»**, y su
   semántica concreta se documenta **campo por campo**.
3. **Lo que el contrato aún no transporta se declara en el descriptor**
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §15.3), **no**
   omitiendo claves.

Semántica de `null` por campo, en V1:

| Campo | Qué significa `null` |
|---|---|
| `ubicacion` | La fila llegó sin ubicación en el origen. **No significa** que el material carezca de ubicación física |
| `material_antiguo` | No hay código antiguo, **o** el valor de origen estaba corrompido y se descartó. **Ambos casos son indistinguibles por diseño** |
| `descripcion`, `unidad` | La columna llegó vacía en todas las filas del grupo |
| `disponible`, `comprometido`, `total_disponible`, `total_comprometido` | **No aplica**: estos campos nunca son nulos |

> **PENDIENTE, y es de M4.**
> [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §9.3 usa `null` con
> otro sentido —«este contrato no transporta el dato»— para `extracted_at`.
> **Este ADR no toca el §9.3 y no resuelve esa doble semántica.** La coherencia
> entre ambas convenciones se decidirá al abordar **M4**, y hasta entonces
> conviven dos sentidos de `null` en secciones distintas del contrato. Se
> declara en voz alta para que nadie la descubra por sorpresa.

---

## Consecuencias

### 11. Qué queda decidido

La semántica, la procedencia y la temporalidad de los campos de inventario
de V1. Con ello, **la fila 4 de las decisiones diferidas de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §22 queda cerrada**.

### 12. Brechas de implementación que esta decisión abre

Ninguna es un defecto de este ADR: son la distancia entre la norma y lo que
existe hoy.

| # | Brecha | De quién |
|---|---|---|
| **B1** | La fachada contractual **no existe**. Ninguna de estas reglas tiene hoy emisor | **M1**, Materiales |
| **B2** | `match_origin` con el vocabulario del §9 no se emite hoy | Materiales |
| **B3** | El contenedor `stock_locations` tipado del §8.2, con su garantía de coherencia por elemento, no existe | Materiales |
| **B4** | Ningún campo declara hoy `snapshot_sensitive` ni su clase de procedencia | Materiales |
| **B5** | La priorización de los marcados para baja (§4.2) queda fuera del contrato V1, pendiente para cuando entre la búsqueda textual | Materiales |

### 13. Conformidad, que es cosa distinta

**P1** y **P2** (§3) **no bloquean nada de lo decidido aquí**. Bloquean
**comprobar** si la implementación actual satisfaría el §9 y el §4. Esa
comprobación llega con las pruebas contractuales del proveedor
([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §18) y con el
Contract Owner de **M7**, que sigue sin asignarse
([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §16.5).

### 14. Qué NO significa aprobar este ADR

| No significa | Estado real |
|---|---|
| La fachada existe | **No.** M1 sigue bloqueante |
| M6 está cerrado operacionalmente | **No.** Ver §15 |
| M4 avanzó | **No.** El §9 de ADR 0021 queda intacto, y `extracted_at` sin tocar |
| M8 se tocó | **No.** Sigue abierto, con su criterio de cierre del §8.3 intacto |
| Materiales fue modificado | **No.** La auditoría que sostiene este ADR fue de solo lectura |
| `dado_de_baja` quedó excluido | **No.** Permanece, como señal no accionable |
| Se autorizó implementación | **No** |

### 15. Estado de M6 después de este ADR

**M6 queda decidido normativamente.** Su **cierre operacional** sigue dependiendo
de que exista la fachada que emita estos campos y de que las pruebas
contractuales demuestren conformidad. Se lee, por tanto, igual que M1 en
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §19.1:

> **M6 — decisión normativa cerrada · implementación y verificación
> pendientes.**

**Este ADR no cierra el subbloque 5.0.b**, que sigue abierto y exige su
documento de cierre (regla 26).

### 16. Riesgos

| Riesgo | Mitigación |
|---|---|
| Leer la implementación observada como contrato | §2, y cada apartado separa norma de implementación |
| Presentar un valor de `FACTUAL_SAP_AGGREGATED` como si fuera de una fila | §5 lo prohíbe y la prueba de conformidad lo comprueba |
| Leer `max()` como «el más reciente» | §5 lo declara máximo lexicográfico y lo prohíbe por escrito |
| Derivar cobertura de `ambito` | §7, con cuatro prohibiciones verificables |
| Tratar `dado_de_baja` como dato accionable | §4, tabla de lo que puede y no puede |
| Confundir `ubicacion` con `stock_locations` | §8.2 los separa por nivel y por nombre |
| Que la doble semántica de `null` se descubra tarde | §10 la declara y la remite a M4 |
| Tomar P1/P2 por bloqueadores de la decisión | §3 y §13 separan decidir de comprobar |

### 17. Alternativas descartadas

| Alternativa | Por qué se descarta |
|---|---|
| Redefinir `FACTUAL_SAP` como «presente en alguna fila del grupo» | Conserva un nombre fuerte y le quita el significado. Es lo contrario de lo que ADR 0021 existe para lograr |
| Exigir a Materiales una fila representativa coherente | Es la opción más correcta en el fondo, pero traslada a Materiales un trabajo y una decisión de producto que V1 no necesita. Queda disponible si la evidencia futura la justifica |
| Taxonomía de temporalidad por momento de determinación | Describe más y **no habilita ninguna decisión adicional** (§6) |
| Fijar el vocabulario completo de coincidencia observado | Acopla el contrato al ranking actual de Materiales sin beneficio para V1 (§9) |
| Conservar ambos nombres, singular y plural | La trampa sobrevive a cualquier definición; renombrar es gratis antes de publicar V1 e incompatible después (§8.2) |
| Extender la regla de emisión del §10 al §9.3 | Cruzaría el límite de M4, que este ADR no gobierna |
| Aprovechar este ADR para cerrar M6 operacionalmente | Exige una fachada que no existe (§15) |

### 18. Trazabilidad de los requisitos de este ADR

| # | Requisito | Sección |
|---|---|---|
| 1 | Contexto y evidencia que lo sostiene | §1 |
| 2 | Norma frente a implementación | §2 |
| 3 | Huecos que no bloquean | §3 |
| 4 | `dado_de_baja` no accionable | §4 |
| 5 | Corrección de la premisa de §10.3 | §4.1 |
| 6 | Priorización como brecha | §4.2 |
| 7 | Quinta clase de procedencia | §5 |
| 8 | `snapshot_sensitive` binario | §6 |
| 9 | `ambito` no es cobertura | §7 |
| 10 | Opacidad de `ubicacion` | §8.1 |
| 11 | `stock_locations` tipado | §8.2 |
| 12 | Vocabulario de `match_origin` | §9 |
| 13 | Emisión estable y `null` | §10 |
| 14 | Brechas de implementación | §12 |
| 15 | Conformidad frente a decisión | §13 |
| 16 | Lo que no significa aprobarlo | §14 |
| 17 | Estado de M6 | §15 |

## Ver también

- [ADR 0020 — Capacidades componibles y planes de ejecución controlados](0020-capacidades-componibles-y-planes-de-ejecucion.md)
- [ADR 0021 — Contrato de inventario con Materiales (V1)](0021-contrato-de-inventario-con-materiales.md)
- [ADR 0023 — Cobertura desconocida de Materiales](0023-cobertura-desconocida-materiales-piloto.md)
- [ADR 0024 — Validación real de la frontera del código SAP y de la autenticación](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
- [Evidencia previa de M6](../piloto-0-1/evidencia-m6-semantica-temporalidad.md)
- [Contrato funcional del Piloto 0.1](../piloto-0-1/contrato-funcional.md)
