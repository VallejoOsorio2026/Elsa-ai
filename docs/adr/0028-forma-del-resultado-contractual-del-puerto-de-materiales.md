# ADR 0028 — Forma del resultado contractual de `MaterialsPort`

- Estado: **aceptado**
- Fecha de la decisión: **2026-09-21**
- Bloque: 5.0, subbloque **M1-A**, punto **M1**
- **Decide una sola cosa**: qué forma tiene lo que devuelve el puerto de
  Materiales. Es la fila 8 de las decisiones diferidas de
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §22 —«forma
  concreta del tipo de retorno de `MaterialsPort`, se decide al
  implementarlo»— y la deuda **D2** de
  [ADR 0027](0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
  §20
- **No redefine** [ADR 0021](0021-contrato-de-inventario-con-materiales.md).
  Aquel ADR decide **el contrato**; este decide **cómo lo expresa el
  consumidor en sus propios tipos**. Son dos planos distintos y se mantienen
  distintos
- **No cierra M1.** Cierra **M1-A**. La fachada no existe, el descriptor real
  no existe, las pruebas del proveedor no existen y el adaptador no existe
  (§20)
- **No gobierna** M4 operativo, M6 operativo, M7, M8, B9a–B9c, D20 ni ONNX
- **No toca** §7.3, §8.3, §9 ni §15 de
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md); los **aplica**
- **No reabre** ninguna decisión de
  [ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
  ni de [ADR 0027](0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
- **No elige transporte** y **no modifica el repositorio de Materiales**
- Aplica las reglas **2, 4, 6, 19, 21, 22, 23, 25 y 26** de
  [`CLAUDE.md`](../../CLAUDE.md)

---

## Contexto

### 1. Contexto

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) fijó el contrato de
inventario: el sobre de tres ejes, la taxonomía de ausencia, la vigencia, la
cobertura, la procedencia y las reglas de versionado.
[ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
fijó la semántica de los campos, y
[ADR 0027](0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
la de `null`. Las tres decisiones son normativas y están cerradas.

**Ninguna tiene emisor.** La fachada contractual no existe, y no existirá
mientras no se autorice pedirla. Entretanto, lo que ELSA espera de ella vive
solo en prosa: tres ADR que nadie cumple ni incumple, porque no hay código
que los aplique.

Este ADR decide la forma con la que ELSA **expresa esa espera en sus propios
tipos**, de modo que el contrato pase de documento a especificación
ejecutable.

### 2. El problema heredado

`src/elsa/ports/materials.py` venía del Bloque 0 (commit `a4a93b9`,
2026-09-04), **anterior a [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md)
y a [ADR 0021](0021-contrato-de-inventario-con-materiales.md)**. Su forma era:

```python
@dataclass(frozen=True, slots=True)
class Material:
    code: str
    description: str


async def get_material(self, code: str) -> Material | None:
    """Devuelve el material con ese código, o ``None`` si no existe."""
```

El propio docstring del módulo admitía ser provisional: *«el contrato real
con Materiales se definirá en el bloque de integración»*. No fue una
regresión; fue un provisional que la norma alcanzó después.

### 3. Por qué `Material | None` ya no es válida

Cuatro motivos, y el cuarto es el que obliga.

**3.1. Afirma lo que el contrato declara imposible.** «`None` si no existe»
convierte cero resultados en una inexistencia. En V1 eso es
**estructuralmente imposible**: el único valor de ausencia disponible lleva
`authoritative: false` y **no existe ningún valor que signifique
inexistencia** ([ADR 0021](0021-contrato-de-inventario-con-materiales.md)
§8.1).

**3.2. Colapsa cuatro desenlaces en uno.** Un vacío no distingue «la fuente
respondió y no lo devolvió» de «no había versión activa que consultar» ni de
«la fuente no respondió». Los tres se parecen mucho al mirarlos desde el
final, y solo el primero es una ausencia. Separarlos es la razón de ser del
sobre de tres ejes ([ADR 0021](0021-contrato-de-inventario-con-materiales.md)
§4, §5).

**3.3. Es un tercer sentido de `null`.**
[ADR 0027](0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
§6 cerró el vocabulario en tres sentidos disjuntos:
`VALOR_FACTUAL_AUSENTE`, `DATO_NO_PROPORCIONADO` y `DATO_DESCONOCIDO`.
«No existe en la realidad» **no es ninguno de los tres**, y no podría serlo:
ninguno autoriza una afirmación sobre el mundo. Aquel ADR lo registró como
deuda **D2** y deliberadamente no la corrigió, por pertenecer a M1.

**3.4. Es inerte hoy y deja de serlo con el adaptador.**
**HECHO DEL REPOSITORIO.** `git grep` sobre `MaterialsPort`, `get_material`
y `search_materials` no encontraba, fuera del propio puerto, su fake y su
prueba, ni un solo consumidor: ni en `core/`, ni en `services/`, ni en
`api/`, ni en `container.py`. El error no podía dispararse porque nada
llamaba al puerto.

Eso es precisamente lo que lo hacía urgente. El día que el adaptador se
conecte, la semántica heredada produce la afirmación prohibida **sin que
nada falle**: no hay excepción, no hay aviso, y la respuesta le dice a un
ingeniero que el material no existe. Corregirlo con cero consumidores cuesta
un subbloque; corregirlo después cuesta una respuesta equivocada de
madrugada.

---

## Decisión

### 4. Decisión humana H4

**DECISIÓN TOMADA por el responsable del proyecto el 2026-09-21**, antes de
escribir código:

> - **reutilizar** las semánticas y vocabularios existentes
>   `CapabilityCallStatus` y `CapabilityOutcome`;
> - **no crear enums paralelos** que representen lo mismo;
> - **encapsular** esas semánticas en un tipo de resultado propio del
>   puerto/fachada;
> - el tipo propio **no debe convertir el código de ELSA en una segunda
>   definición canónica** independiente de Materiales;
> - la forma concreta debe quedar **documentada mediante ADR nuevo**.

Este ADR es ese documento. La forma concreta que sigue es la implementación
de esa decisión, no una decisión distinta.

### 5. Reutilización, no duplicación

`src/elsa/core/capability_outcomes.py` ya contenía, desde el subbloque de
política de ausencia segura, la lectura del consumidor de los dos primeros
ejes del contrato:

| Tipo reutilizado | Origen normativo | Valores |
|---|---|---|
| `CapabilityCallStatus` | [0021](0021-contrato-de-inventario-con-materiales.md) §5 | `OK`, `NO_ACTIVE_INVENTORY`, `UNAVAILABLE`, `REJECTED` |
| `CapabilityOutcome` | [0021](0021-contrato-de-inventario-con-materiales.md) §6 | `MATCHED`, `NOT_RETURNED` |
| `InventoryCoverageState` | [0021](0021-contrato-de-inventario-con-materiales.md) §7.1 | `KNOWN_COMPLETE`, `KNOWN_INCOMPLETE`, `UNKNOWN` |

El puerto **los importa y los usa tal cual**. No los envuelve, no los
traduce y no los renombra.

#### 5.1 La dirección de dependencia es legítima

**HECHO DEL REPOSITORIO, comprobado antes de implementar.** `ports/` ya
importa de `core/` en cuatro módulos: `ports/documents.py`,
`ports/evidence.py`, `ports/vectors.py` y `ports/knowledge.py`. No es una
excepción que se abre aquí, es el patrón vigente.

Y no hay ciclo posible: el cierre transitivo de importaciones de
`core.capability_outcomes` y `core.coverage_policy` es exactamente
`{core.answers, core.capability_outcomes, core.coverage_policy}`, y
**ninguno de los tres alcanza `elsa.ports`**.

### 6. Prohibición de vocabularios paralelos

**Queda prohibido declarar en `ports/materials.py`, o en cualquier
adaptador, un enum que represente el estado de la llamada, el desenlace por
código o el estado de cobertura.**

No es una preferencia de estilo. Dos vocabularios para lo mismo divergen: el
día que alguien añada un valor a uno y no al otro, la traducción entre ambos
se vuelve silenciosamente incompleta, y el modo de fallo es el mismo que
este contrato existe para impedir —una afirmación que nadie autorizó, sin
que ninguna prueba se entere—.

Los tres vocabularios que **sí** se declaran aquí son los que **no tenían
equivalente**: `MatchOrigin`, `AbsenceReason` y `FieldProvenance`. Cada uno
reproduce literalmente el que fijó su ADR de origen.

### 7. El tipo de resultado propio del puerto

`MaterialsLookupResult`: un *dataclass* congelado con `slots`, coherente con
el resto de los puertos del repositorio, que transporta el sobre de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §4.

```
MaterialsLookupResult
├── call_status        CapabilityCallStatus   ← reutilizado
├── contract_version   str | None
├── inventory          InventoryVersion | None
├── coverage           InventoryCoverage | None
├── requested_code     str | None
├── outcome            CapabilityOutcome | None  ← reutilizado
├── material           MaterialFacts | None
├── absence            MaterialAbsence | None
└── attribution        MaterialAttribution | None
```

Lo acompañan `InventoryStatusResult` para `get_inventory_status`, y
`ContractDescriptor` para `get_contract_descriptor`.

#### 7.1 Por qué no es una segunda definición canónica

La condición que H4 impone. Tres propiedades la sostienen:

1. **No hay formato de cable.** Los valores de los enums son los internos
   de ELSA (`"ok"`, `"matched"`), no las etiquetas del contrato. La
   traducción a lo que emita la fachada es trabajo del adaptador, y el
   puerto no la conoce.
2. **No hay reglas de negocio.** Nada aquí agrega existencias, clasifica
   ubicaciones, calcula vigencia ni decide cobertura. El tipo transporta el
   resultado de reglas ajenas, con su `rule_reference`.
3. **Es una aserción sobre la forma.** Si Materiales cambia y ELSA no, las
   pruebas fallan. Eso es exactamente lo que
   [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §16.4 pide de
   este repositorio, y nada más: *«la prueba de conformidad no es una
   segunda definición: es una aserción sobre la forma»*.

La definición canónica **sigue sin existir**, y sigue debiendo vivir
versionada en el repositorio de Materiales.

### 8. Tres planos, y no se mezclan

| Plano | Quién lo responde | Dónde vive |
|---|---|---|
| **Estado de la llamada** — ¿pudo la fuente responder? | `call_status` | El sobre |
| **Resultado de la capacidad** — ¿devolvió este código? | `outcome` | El sobre, por código |
| **Payload factual** — qué es este material | `material`, `inventory`, `coverage` | Dentro del sobre |

Un enum plano obligaría a elegir entre verdades simultáneas: **un material
puede encontrarse y la cobertura seguir siendo incompleta**. Con tres planos
ese caso es expresable; con uno, no.

El puerto **hace imposibles las combinaciones que el contrato prohíbe**, y
lo hace en la construcción del objeto, no en quien lo consume:

- una llamada que no es `OK` **no transporta payload alguno**, y eso incluye
  la ausencia: `NO_ACTIVE_INVENTORY` **no es una ausencia**, porque no hubo
  fuente válida sobre la que consultar
  ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §5, §13.1);
- una llamada `OK` lleva siempre `inventory` y `coverage`, que son
  obligatorios en toda respuesta (§9, §7);
- `MATCHED` obliga a material y a atribución, y prohíbe ausencia;
- `NOT_RETURNED` obliga a una ausencia tipada y prohíbe material.

### 9. Una ausencia normal no es una excepción

Los **cuatro desenlaces normales** de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §14 son **valores**:

| # | Desenlace | Cómo llega |
|---|---|---|
| 1 | Resultado factual | `call_status=OK`, `outcome=MATCHED`, con material |
| 2 | La fuente respondió y no devolvió el código | `call_status=OK`, `outcome=NOT_RETURNED`, con ausencia tipada |
| 3 | No hay inventario activo | `call_status=NO_ACTIVE_INVENTORY`, sin payload |
| 4 | La capacidad no está disponible | `call_status=UNAVAILABLE`, sin payload |

Modelar cualquiera de los cuatro como excepción convertiría una respuesta
legítima en un fallo, y quien la recibiera no podría distinguirla de un
error de programación.

**Consecuencia concreta: `MaterialsUnavailableError` desaparece.** Su
significado —«el servicio de Materiales no está disponible»— es exactamente
el desenlace 4, que
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §5 clasifica como
un `call_status` y no como un fallo. Conservarla habría dejado dos caminos
para el mismo hecho, uno de ellos prohibido. **HECHO DEL REPOSITORIO:** no
tenía ningún consumidor.

### 10. `NOT_RETURNED` no es inexistencia

El valor se llama `NOT_RETURNED` y no `NOT_FOUND` a propósito: «no
encontrado» sugiere que se buscó exhaustivamente y no está.

En el tipo, **un material ausente nunca viaja solo**. Va siempre acompañado
de una `MaterialAbsence` con su `reason`, su `basis` en prosa y su
`authoritative` en falso. El vacío deja de ser la señal, y pasa a ser la
consecuencia de un hecho declarado sobre **la fuente**, no sobre el mundo.

`AbsenceReason` tiene **un solo valor**, `NOT_RETURNED_BY_SOURCE`. Los tres
reservados de [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3
**no se declaran**: cada uno exige un mecanismo que lo demuestre, ninguno
existe, y esa tabla es el criterio de cierre de M8.

**`MaterialAbsence(authoritative=True)` lanza excepción.** No es una opción
de configuración: mientras M8 siga abierto, construir una ausencia
autoritativa es un error de contrato.

### 11. `NO_ACTIVE_INVENTORY`

Tiene valor propio porque hoy es indistinguible de la ausencia, y es la más
barata de las nueve causas de eliminar. En el tipo, una llamada con este
estado **no puede transportar ni `inventory` ni `absence`**: no hubo versión
activa que describir, y no hubo consulta que ausentarse.

Un `inventory` con `version_number` nulo sería un defecto de contrato
([ADR 0027](0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
L1), y el tipo lo hace inconstruible.

### 12. `UNAVAILABLE`

Fallo técnico: red, tiempo agotado, error del servidor, respuesta ilegible.
**Es un valor, no una excepción** (§9). Traducir el fallo de transporte a
este estado es trabajo del adaptador, que todavía no existe.

### 13. `REJECTED` se resuelve antes de componer, y esa frontera no se mueve

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §5: *«`REJECTED`
nunca se presenta como ausencia ni como fallo de la fuente. Es una condición
de autorización y se resuelve en la cadena de confianza de ELSA.»*

Esa frontera **ya existe en el código**, y está donde debe: la política de
`interpret_inventory_lookup` lanza `UncomposableOutcomeError` si un
`REJECTED` llega hasta ella. **Este ADR no la mueve.** El puerto puede
transportar el estado, porque el vocabulario lo incluye y amputarlo crearía
un cuarto vocabulario; lo que no puede es componerse.

Forzar el rechazo **dentro** del puerto habría duplicado una decisión que ya
estaba tomada en la capa correcta.

### 14. Excepciones, y qué queda reservado para ellas

Una sola, `MaterialsContractViolationError`, y cubre lo que el contrato
declara imposible:

- un lookup exacto que responde con una coincidencia que no prueba identidad
  (§15);
- una ausencia que se declara autoritativa con M8 abierto;
- un sobre cuyas partes se contradicen: `MATCHED` sin material, `MATCHED`
  sin atribución, `NOT_RETURNED` con material, ausencia sin tipar, llamada
  fallida con payload, llamada correcta sin cobertura.

**No es un resultado de peor calidad: es una respuesta inválida.** Y no
cubre el fallo técnico, que es el desenlace 4.

### 15. El invariante del lookup exacto, ejecutable

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §6 declaró el
invariante; [ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
§9 lo hizo comprobable. Aquí se hace **inconstruible su violación**: un
resultado `MATCHED` cuyo `match_origin` no esté en
`EXACT_LOOKUP_MATCH_ORIGINS` —es decir, que no sea `EXACT_MATERIAL_CODE` ni
`OLD_MATERIAL_CODE`— lanza `MaterialsContractViolationError` al construirse.

Es el cortafuegos contra la caída silenciosa a similitud que la auditoría
del subbloque 5.0.b encontró y que **sigue viva hoy en Materiales**: un
código que no coincide literalmente degrada a parecido sobre la descripción
sin avisar.

`MatchOrigin.from_source()` implementa además el tratamiento declarado de
valores desconocidos —se leen como `OTHER_MATCH`
([ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
§9)—, que es lo que convierte ampliar el vocabulario en un cambio
**compatible** (§15.1) en lugar de una ruptura.

### 16. Relación con la cobertura

`coverage` es **obligatoria en toda respuesta correcta**, y el tipo lo
impone. Se reutiliza `InventoryCoverageState`; no hay una segunda escala.

Los cuatro campos de ámbito son nulables y su sentido es
`DATO_NO_PROPORCIONADO`: mientras no exista metadata de ingestión que los
respalde, el estado es `UNKNOWN`, y **`UNKNOWN` no se disfraza de completo
ni de incompleto**.

**No se deriva cobertura de `ambito`.** El tipo no ofrece ningún camino para
hacerlo, y una prueba comprueba que un material con filas en dos ámbitos
distintos sigue teniendo cobertura `UNKNOWN`
([ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
§7).

### 17. Relación con M8

**M8 sigue ABIERTO**, y este ADR no lo toca. El criterio de cierre de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3 queda
**intacto y sin cumplir**.

Tipar el puerto **no mejora la autoridad de la ausencia**, y el tipo está
construido para que no pueda parecerlo: no existe valor de inexistencia, no
se declara ninguno de los tres reservados, y la única bandera que podría
afirmarla es inconstruible.

### 18. Relación con ADR 0027 y `null`

`null` no tiene significado universal, y cada campo nulable debe declarar su
sentido. Eso deja de ser prosa:

- **`NullSense`** reproduce los tres sentidos cerrados del §6.
- **`NULL_SENSES`** asigna uno a cada campo nulable del contrato.
- Una prueba comprueba que **todo campo nulable tiene sentido declarado y
  que no hay sentidos huérfanos**. Añadir un campo nulable sin clasificarlo
  rompe la suite, que es lo que
  [ADR 0027](0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
  §6.2.2 quiere decir con «un campo nulable sin clasificación es un defecto
  de contrato».

**Esto no es un campo del payload, y no debe llegar a serlo.** §12 de aquel
ADR reserva esa ruta —la Alternativa C— para cuando un caso real la exija, y
fija que hasta entonces el vocabulario es documental y normativo. Una tabla
de clasificación paralela al payload respeta ese límite.

`extracted_at` queda tipado `None`: **siempre nulo en V1**, y es
`DATO_NO_PROPORCIONADO`. Rellenarlo en el futuro es un cambio compatible
([ADR 0027](0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
L4) que exigirá cambiar este tipo junto con la versión del contrato —que es
exactamente la constancia que el campo debe dejar—.

### 19. Compatibilidad futura con la fachada

Cuando la fachada exista, el adaptador traducirá su respuesta a estos tipos.
Cuatro propiedades lo hacen posible sin renegociar nada:

1. **El transporte no está en los tipos.** Elegir enlace no cambia ninguno.
2. **El descriptor lleva el enlace**, como campo inerte por ahora.
3. **Los valores desconocidos de `match_origin` degradan**, de modo que
   ampliar el vocabulario del proveedor no rompe al consumidor.
4. **`results` como lista** sigue siendo la forma del contrato; el puerto
   expone hoy la operación unitaria, y añadir lote (M2) es aditivo
   ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §17).

---

## Consecuencias

### 20. Qué NO decide este ADR

| No decide | Dónde pertenece |
|---|---|
| El enlace de transporte de la fachada | **H3**, pendiente. Contract Owner + Materiales |
| Modificar el repositorio de Materiales | **H5**, no autorizada |
| La definición canónica, `contract_version` real y descriptor real | **M1**, en Materiales |
| Las pruebas contractuales del proveedor | **M1**, en Materiales |
| El adaptador real | **M1**, después de H3 |
| `requires_fresh_inventory`, `inventory_freshness_unknown`, política de vigencia | **M4 operativo** |
| La implementación de la semántica de campos y su verificación | **M6 operativo** |
| El criterio de cierre de M8 | **Intacto** en [0021](0021-contrato-de-inventario-con-materiales.md) §8.3 |
| La búsqueda por texto libre | Fuera del Piloto 0.1 inicial ([0021](0021-contrato-de-inventario-con-materiales.md) §2, §22 fila 12) |
| Cableado en `container.py`, configuración y estado de salud | Con el adaptador real |
| D20, ONNX, Modo ELSA, embeddings, ZIAA, BOM | Fuera de alcance |

### 21. Consecuencias

**Para ELSA:**

1. La deuda **D2** queda **eliminada**. No queda ninguna lectura contractual
   en la que un vacío signifique «el material no existe».
2. El contrato pasa de documento a **especificación ejecutable**: lo que
   antes solo podía leerse ahora rompe la suite si se incumple.
3. **Ningún consumidor cambia**, porque no había ninguno. El cambio es local
   y verificable.
4. **Ninguna prueba existente se modificó** para acomodarlo. Las de ausencia
   y cobertura siguen tal cual, y el puente `as_capability_result()` las
   conecta con el puerto sin tocarlas.
5. `MaterialsUnavailableError` deja de existir (§9), y `Material` con ella.

**Para Materiales:** **ninguna.** No se modificó nada, no se pidió nada, y
el trabajo que le corresponde sigue siendo exactamente el mismo.

### 22. Casos de ejemplo

**22.1. Hecho factual, con cobertura desconocida — y las dos cosas son
ciertas a la vez:**

```
call_status = OK · outcome = MATCHED · coverage.state = UNKNOWN
material.descripcion = "…" · attribution.match_origin = EXACT_MATERIAL_CODE
```

ELSA puede afirmar la descripción. **No puede** afirmar que esas sean todas
las existencias: podría haber más en un ámbito no cubierto.

**22.2. La fuente respondió y no devolvió el código:**

```
call_status = OK · outcome = NOT_RETURNED · material = None
absence.reason = NOT_RETURNED_BY_SOURCE · absence.authoritative = False
```

Compone como `NO_EVIDENCE` con `code_not_found_in_source`. **Nunca** como
«ese material no existe».

**22.3. No hubo dónde mirar:**

```
call_status = NO_ACTIVE_INVENTORY · sin outcome, sin inventory, sin absence
```

Compone como `ERROR` en un plan directo. **No** es `NO_EVIDENCE`: no es que
se consultara y no hubiera nada, es que no se pudo consultar.

**22.4. Tres `null` con tres sentidos en la misma respuesta:**

```
inventory.extracted_at   = None   → DATO_NO_PROPORCIONADO
coverage.observed_scope  = None   → DATO_NO_PROPORCIONADO
material.descripcion     = None   → VALOR_FACTUAL_AUSENTE
material.material_antiguo = None  → DATO_DESCONOCIDO
```

Las cuatro lecturas son distintas y las cuatro son correctas
([ADR 0027](0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
L7). Homogeneizarlas sería el error.

**22.5. Violación de contrato, no resultado peor:**

```
outcome = MATCHED · attribution.match_origin = OTHER_MATCH
→ MaterialsContractViolationError
```

Es la caída silenciosa a similitud, hecha ruidosa.

### 23. Alternativas descartadas

| Alternativa | Por qué se descartó |
|---|---|
| **Conservar `Material \| None` y documentar mejor** | La documentación no falla cuando se incumple. El error solo aparecería en la respuesta a un ingeniero |
| **Enums propios del puerto, traducidos desde los del núcleo** | H4 lo prohíbe, y con razón: dos vocabularios para lo mismo divergen, y la traducción se vuelve incompleta en silencio |
| **Excepciones para ausencia y para «sin inventario activo»** | Convierte respuestas legítimas en fallos ([0021](0021-contrato-de-inventario-con-materiales.md) §14) |
| **Mover los tipos del contrato a `core/`** | El puerto es su dueño natural, y `ports/` ya aloja los DTO de sus contratos. Habría creado una capa sin necesidad |
| **Un `dict` o un modelo laxo, «hasta que exista la fachada»** | Un tipo laxo no puede comprobar un invariante, que es justo lo que M1-A debía producir |
| **Esperar a que la fachada exista para tipar el puerto** | Invierte el orden útil: la especificación ejecutable es lo que permite medir lo que entregue el proveedor ([0021](0021-contrato-de-inventario-con-materiales.md) §16.4) |
| **Implementar también el descriptor por red y el estado de salud** | Exige H3. Se modela solo la forma |

### 24. Pendientes derivados

| Id | Pendiente | Quién |
|---|---|---|
| **P1** | **H3** — enlace de transporte de la fachada | Contract Owner + Materiales |
| **P2** | **H5** — autorización para modificar el repositorio de Materiales | Responsable del proyecto |
| **P3** | Definición canónica versionada, `contract_version` y descriptor reales | Materiales (M1) |
| **P4** | Pruebas contractuales del proveedor | Materiales (M1) |
| **P5** | Adaptador real, cableado, configuración y salud degradada | ELSA, tras H3 |
| **P6** | M4 operativo y M6 operativo | Sus propios subbloques, tras M1 |
| **P7** | **M8 sigue abierto**, con su criterio intacto y sin cumplir | Su propio subbloque |

### 25. Trazabilidad de los requisitos de este ADR

| # | Requisito | Sección |
|---|---|---|
| 1 | Contexto | §1 |
| 2 | Problema heredado | §2 |
| 3 | Semántica antigua y por qué no vale | §3 |
| 4 | Decisión humana H4 | §4 |
| 5 | Reutilización de los vocabularios | §5 |
| 6 | Prohibición de enums paralelos | §6 |
| 7 | Tipo de resultado propio | §7 |
| 8 | Tres planos separados | §8 |
| 9 | Ausencia normal ≠ excepción | §9 |
| 10 | `NOT_RETURNED` ≠ inexistencia | §10 |
| 11 | `NO_ACTIVE_INVENTORY` | §11 |
| 12 | `UNAVAILABLE` | §12 |
| 13 | `REJECTED` y su frontera | §13 |
| 14 | Excepciones reservadas | §14 |
| 15 | Invariante del lookup exacto | §15 |
| 16 | Relación con cobertura | §16 |
| 17 | Relación con M8 | §17 |
| 18 | Relación con ADR 0027 y `null` | §18 |
| 19 | Compatibilidad futura con la fachada | §19 |
| 20 | Qué NO decide | §20 |
| 21 | Consecuencias | §21 |
| 22 | Casos de ejemplo | §22 |

---

## Ver también

- [ADR 0020 — Capacidades componibles y planes de ejecución](0020-capacidades-componibles-y-planes-de-ejecucion.md)
- [ADR 0021 — Contrato de inventario con Materiales](0021-contrato-de-inventario-con-materiales.md)
- [ADR 0023 — Cobertura desconocida de Materiales](0023-cobertura-desconocida-materiales-piloto.md)
- [ADR 0024 — Validación real de la frontera del código SAP y de la autenticación](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
- [ADR 0025 — Semántica, procedencia y temporalidad de los campos de inventario](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
- [ADR 0026 — Gobernanza y cierre de M7](0026-gobernanza-y-cierre-de-m7.md)
- [ADR 0027 — Semántica de `null` y disponibilidad de metadata del inventario](0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md)
- [Cierre de M1-A](../bloque-5-0-m1-a-contrato-consumidor-cierre.md)
