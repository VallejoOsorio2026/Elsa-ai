# ADR 0021 — Contrato de inventario con Materiales (V1)

- Estado: **propuesto**
- El carácter bloqueante de **M8** (§25) se redefine en
  [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md). El **criterio
  de cierre de M8 del §8.3 no se toca**, y este ADR no se reescribe
- **M3 y M5 fueron medidos el 2026-09-19** y quedan **resueltos para V1** por
  [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md),
  sobre [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md). Ese ADR
  **cierra los puntos 1, 2 y 3 de las decisiones diferidas del §22**. Este ADR
  **no se reescribe**; las notas fechadas de §3.2, §20, §21.1, §21.2, §22 y §25
  registran el estado posterior. **El §8.3 sigue intacto**
- Bloque: 5.0, subbloque **5.0.b**
- Deriva de [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md)
  §5, §10, §11, §12 y §13, y **no lo reabre**
- Apoya la identidad ya decidida en
  [ADR 0002](0002-identidad-de-materiales-autorizacion-en-backend.md) y
  [ADR 0005](0005-verificacion-real-del-jwt-de-materiales.md)
- Conserva sin cambios los estados de respuesta de
  [ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md)
- Aplica las reglas **2, 4, 6, 9, 21 y 23** de [`CLAUDE.md`](../../CLAUDE.md)
- **Decide** el contrato del punto **M1** y **define** el rol de gobernanza del
  punto **M7**
- **No cierra operacionalmente ningún punto M1–M8.** Ver §19 y §25
- **No aprueba ninguna fachada construida, ninguna migración, ninguna
  representación de frontera y ningún cambio en Materiales**

---

## Contexto

### 1. Lo que ADR 0020 dejó sin resolver

[ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) decidió que
ELSA compone capacidades, que el LLM no decide relaciones SAP, que la
procedencia se conserva por hecho y por campo, y que **una ausencia no es una
inexistencia**. Declaró la capacidad `get_material_availability` y declaró
explícitamente que su `absence_semantics` era *desconocida*, remitiendo a ocho
puntos abiertos (M1–M8) del contrato con Materiales.

Ese ADR describe **qué debe garantizar** la consulta de inventario. No describe
**contra qué superficie** se hace, ni **qué forma** tiene lo que devuelve. Ese
es el vacío que cierra este ADR.

### 2. Lo que la auditoría del subbloque 5.0.b encontró

Se auditó el repositorio de Materiales en solo lectura, fuera del árbol de
ELSA, sin modificar nada. Hechos relevantes, todos verificados sobre código:

- Materiales es una interfaz web estática sobre Supabase. **No existe backend
  propio.** Toda la lógica vive en funciones de base de datos invocadas desde el
  navegador.
- La superficie que usa hoy el buscador es una función de consulta. **Su
  definición vigente no está versionada en el repositorio**, y su firma ya
  cambió respecto de la última versión que sí lo estuvo. No es un descuido
  aislado: el historial del proyecto registra correcciones previas del mismo
  tipo.
- **No existe ningún contrato formal** entre ambos sistemas: ni tipos
  compartidos, ni esquema publicado, ni pruebas contractuales, ni versión
  declarada.
- El código de material se conserva como texto y solo se recorta. **Materiales
  no puede perder ceros a la izquierda.** El riesgo de representación está
  aguas arriba (la exportación) y aguas abajo (el lector de ELSA), no en su
  almacenamiento.
- La coincidencia exacta por código se resuelve por igualdad literal con una
  normalización **asimétrica**: se normaliza la consulta y no el valor
  almacenado. Un código cuya representación difiera no falla de forma ruidosa:
  **cae en silencio a búsqueda por similitud sobre la descripción**, que es
  exactamente el modo de fallo que anticipó la decisión D17 del subbloque
  anterior.
- Existe versionado real de cargas, con número, estado y marca temporal de
  finalización, y es legible con el JWT del usuario.
- **No existe ninguna fecha de extracción de SAP.** Solo existe la marca del
  momento en que terminó la carga.
- La autenticación funciona con el JWT del propio usuario más una clave
  publicable, sin credencial de servicio, y una función de perfil activo
  protege las operaciones. ELSA ya opera así en producción para la identidad.
- La carga auditada excluía un centro completo por una decisión operativa
  explícita y documentada por Materiales. Mientras eso ocurra, **«no
  encontrado» significa, entre otras cosas, «está en una sede que esta carga no
  cubre»**.
- **No existe consulta por lote.**

La auditoría separó **nueve causas distintas** por las que hoy una consulta
puede no devolver un código. Las nueve llegan al usuario como un único mensaje
de texto.

### 3. El problema

> ELSA necesita afirmar hechos de inventario con procedencia. Hoy la única
> superficie disponible **no puede sostener ninguna de las garantías que
> ADR 0020 exige**: no declara versión, no declara vigencia, no declara
> cobertura, no distingue causas de ausencia, no separa el dato de SAP del
> cálculo de Materiales, y no está versionada.

Consumirla tal cual acoplaría ELSA a una función que puede cambiar sin dejar
rastro en ningún repositorio, y obligaría a ELSA a **inferir** lo que la fuente
no dice. Inferir es exactamente lo que la regla 2 de
[`CLAUDE.md`](../../CLAUDE.md) prohíbe: no se crean hechos sin evidencia
recuperada.

### 4. La alternativa descartada

La alternativa barata es que ELSA consuma el buscador actual y reconstruya por
su cuenta lo que falta: leer la versión activa por separado, deducir la
cobertura de los datos, y tratar cero resultados como ausencia.

Se rechaza por una razón concreta, no ideológica: **cada una de esas
inferencias sería un hecho sin procedencia**, y el conjunto haría que ELSA
afirmara con confianza cosas que su fuente nunca dijo. En un sistema que puede
mandar a un ingeniero a un almacén de madrugada, esa es la peor clase de error,
porque es silenciosa.

---

## Decisión

### 1. ELSA consume una fachada contractual, no el buscador

ELSA **no** se acopla como contrato definitivo a la función de búsqueda que hoy
usa la interfaz de Materiales.

Se define un **contrato Materiales–ELSA V1**: una superficie propia, versionada
y con dueño, que Materiales expone para ELSA.

**La fachada no duplica el motor de Materiales.** Reutiliza la lógica
existente —agrupación multiubicación, orden por cercanía, tratamiento de
materiales marcados para baja, conversión numérica— porque esa lógica ya
existe, funciona y es propiedad de Materiales (regla 4). Lo único que la
fachada aporta es lo que hoy no existe en ninguna superficie:

1. acotar la coincidencia a exacta por código;
2. adjuntar la vigencia del inventario;
3. adjuntar la cobertura del snapshot;
4. tipar la ausencia en lugar de devolver cero filas mudas;
5. declarar su propia versión de contrato.

**La fachada no existe.** Este ADR la especifica; construirla es trabajo
posterior y autorizado aparte (§21.4).

### 2. Lookup exacto y búsqueda textual son operaciones separadas

Cuatro operaciones lógicas, con nombres de contrato independientes del
transporte:

| Operación | Semántica | Piloto 0.1 |
|---|---|---|
| `lookup_material_by_code` | **Identificación autoritativa.** Coincidencia exacta o nada | **Obligatoria** |
| `search_materials_by_text` | **Sugerencia asistida.** Candidatos con metadatos de coincidencia | Forma declarada, **fuera del Piloto 0.1 inicial** |
| `get_inventory_status` | Vigencia y cobertura sin consultar material alguno | Obligatoria |
| `get_contract_descriptor` | Versión del contrato y operaciones disponibles | Obligatoria |

**No se fusionan.** `lookup_material_by_code` responde «¿qué es este código?» y
su respuesta es un hecho atribuible. `search_materials_by_text` responde «¿qué
se parece a este texto?» y su respuesta es un conjunto de hipótesis.

Cuatro reglas derivadas, vinculantes:

- **`lookup_material_by_code` no admite ningún parámetro ni modo que active
  similitud.** No es una opción desactivada por defecto: no existe.
- **El lookup exacto no puede degradarse a búsqueda textual**, ni por
  configuración, ni por ausencia de resultados, ni por decisión del adaptador.
- **Ningún resultado de `search_materials_by_text` puede promoverse a hecho
  factual de identificación.** Puede sugerir; no puede afirmar.
- **La fachada declara su enlace de transporte** (nombre de función, ruta) en
  su descriptor. El contrato no depende de cómo Materiales lo implemente
  internamente.

> Hoy ambas semánticas conviven en la misma llamada, y un código que no coincide
> literalmente degrada a similitud sin avisar. Separarlas es el cortafuegos
> contra ese fallo, no una preferencia de estilo.

### 3. Request mínimo

```jsonc
{
  "contract_version": "1",
  "material_code":   "<string>"
}
```

Dos campos. **Nada más.**

#### 3.1 Minimización de datos

Materiales no participa en el modelo de autorización de ELSA, no necesita saber
qué se preguntó y no debe recibir contexto que no use. **Prohibido en el
request**, y verificable por prueba contractual:

| Prohibido | Motivo |
|---|---|
| La pregunta del usuario | Materiales no la necesita para devolver un código |
| Los alcances de ELSA | Exportaría el modelo de autorización de ELSA a un sistema que no lo tiene |
| El activo, el BOM o el renglón de origen | Materiales no necesita saber por qué se pregunta |
| Historial de conversación, evidencia documental, referencia de respuesta | Nada de ello interviene en un hecho de inventario |
| Identificador de usuario en el cuerpo | Ya viaja en el JWT, y solo ahí |

Materializa la restricción de ADR 0020: *«Materiales no recibe la pregunta
completa, los alcances de ELSA ni contexto que no necesite.»*

#### 3.2 `material_code` no está definido, y es deliberado

`material_code` es la representación que **Materiales** necesita para acertar,
no la que ELSA usa internamente. Cuál es esa representación **es indecidible
hasta M3** (§21.1).

Se conservan cuatro representaciones distintas, que no deben confundirse:

| Representación | Papel | Estado |
|---|---|---|
| Valor original de la fuente | Nunca se pierde | Definido |
| Forma de almacenamiento en ELSA | Cómo se guarda | Definido |
| Forma canónica de comparación | **Solo** para comparar dos códigos **dentro de** ELSA | **Provisional hasta M3** |
| **Representación de frontera (`material_code`)** | Lo único que cruza hacia Materiales | **Indecidible hasta M3** |

> **Estado, 2026-09-19.** M3 se midió y las dos últimas filas **dejaron de ser
> indecidibles para V1**: la representación de frontera es la regla **M3-A**
> —cadena decimal exacta, sin agregar ni quitar ceros, sin padding— decidida en
> [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
> §8, sobre [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md) §3. **El texto de
> arriba se conserva** porque describe correctamente el estado en el momento de
> esta decisión. **Las cuatro representaciones siguen sin confundirse**, que es
> lo que este apartado decide.

Concuerda con ADR 0020 §5 —*«la representación que exija Materiales se aplica
dentro de su adaptador, nunca en el núcleo»*— sin reabrirlo.

### 4. Respuesta estructurada: tres ejes ortogonales

```jsonc
{
  "contract_version": "1",
  "call_status":      "OK",
  "inventory":        { },
  "coverage":         { },
  "results": [
    {
      "requested_code": "<eco literal de lo enviado>",
      "outcome":        "MATCHED" | "NOT_RETURNED",
      "absence":        { } | null,
      "material":       { } | null,
      "match":          { } | null,
      "attribution":    { }
    }
  ]
}
```

**No se usa un enum plano.** Tres dimensiones independientes:

| Eje | Alcance | Pregunta que responde |
|---|---|---|
| `call_status` | La llamada | ¿Pudo la fuente responder? |
| `outcome` | Cada código | ¿Devolvió este código? |
| `coverage.state` | El snapshot | ¿Sé qué ámbito cubre lo que consulté? |

Un enum plano obligaría a elegir entre verdades simultáneas. **Un material
puede encontrarse y la cobertura seguir siendo incompleta**: existe en el
snapshot y podría existir además, con más existencias, en un ámbito no
cubierto. Con un solo enum ese caso no es expresable; con tres ejes, sí.

`results` es una **lista desde V1**, aunque V1 envíe un solo código (§17).

### 5. `call_status`

| Valor | Cuándo |
|---|---|
| `OK` | La fuente respondió sobre una versión de inventario activa |
| `NO_ACTIVE_INVENTORY` | No hay versión activa. **No es ausencia**: no hubo fuente válida sobre la cual ejecutar la consulta |
| `UNAVAILABLE` | Fallo técnico: red, tiempo agotado, error del servidor, respuesta ilegible |
| `REJECTED` | Autorización: token inválido, o perfil ausente o inactivo en Materiales |

`NO_ACTIVE_INVENTORY` tiene valor propio porque hoy es indistinguible de la
ausencia: una consulta sin versión activa llega al usuario como «no se
encontró ningún material». Es una de las nueve causas que la auditoría separó,
y la más barata de eliminar.

`REJECTED` **nunca se presenta como ausencia ni como fallo de la fuente.** Es
una condición de autorización y se resuelve en la cadena de confianza de ELSA.

### 6. `outcome`

| Valor | Significado |
|---|---|
| `MATCHED` | La fuente devolvió este código |
| `NOT_RETURNED` | La fuente respondió correctamente y **no devolvió** este código |

**El valor se llama `NOT_RETURNED` y no `NOT_FOUND`.** «No encontrado» sugiere
que se buscó exhaustivamente y no está. `NOT_RETURNED` dice exactamente lo
ocurrido. Mientras M8 siga abierto, esa diferencia de una palabra **es** el
contrato.

**Invariante de `lookup_material_by_code`, verificable:** en un lookup exacto,
los metadatos de coincidencia declaran siempre coincidencia por código —exacto
o por código antiguo—. Cualquier otro valor es una **violación del contrato**,
no un resultado de peor calidad. Es el cortafuegos contra la caída silenciosa a
similitud descrita en el Contexto §2.

### 7. Cobertura

#### 7.1 Forma

```jsonc
"coverage": {
  "state":          "KNOWN_COMPLETE" | "KNOWN_INCOMPLETE" | "UNKNOWN",
  "observed_scope": [ ] | null,
  "expected_scope": [ ] | null,
  "missing_scope":  [ ] | null,
  "scope_kind":     "<unidad de cobertura>",
  "declared_at":    "…" | null
}
```

#### 7.2 `observed_scope` es metadata declarada, no una observación de las filas

`observed_scope` significa **«el ámbito que Materiales declara que este
snapshot cubrió»**.

**No significa** «los ámbitos para los que casualmente existen filas».

La distinción decide la corrección del contrato. Contar los ámbitos distintos
presentes en los datos de negocio responde a «¿de qué ámbitos llegó algo?»,
que es una pregunta **distinta** de «¿qué ámbitos intentó cubrir esta carga?».
Una carga puede haber pretendido cubrir un ámbito y no traer ninguna fila de
él —porque el filtro de exportación lo excluyó, porque la consulta de origen
falló, o porque no había existencias—, y los datos de negocio no distinguen
esos casos. Derivar completitud de ellos produciría una afirmación de cobertura
sin evidencia, que es precisamente lo que este ADR existe para impedir.

Por tanto, `observed_scope` debe provenir de **metadata de ingestión o de
cobertura que Materiales pueda sostener contractualmente**: Materiales debe
poder declarar qué ámbito intentó y cubrió la carga, con independencia de que
existan filas para cada uno.

**Si esa metadata todavía no existe, `observed_scope` es nulo o vacío y
`coverage.state` es `UNKNOWN`, aunque puedan observarse ámbitos en las filas.**

`expected_scope` es una **declaración explícita, versionada, recuperable y
asociable al snapshot**. **Dónde la almacene Materiales es decisión interna
suya y el contrato no depende de ello.**

#### 7.3 Cómo se determina el estado

| Estado | Condiciones, **todas** obligatorias |
|---|---|
| `KNOWN_COMPLETE` | `expected_scope` declarado · `observed_scope` respaldado por metadata de ingestión · no falta ningún ámbito esperado |
| `KNOWN_INCOMPLETE` | `expected_scope` declarado · `observed_scope` respaldado por metadata de ingestión · se demuestra que falta algún ámbito esperado |
| `UNKNOWN` | Cualquier otro caso, incluido que falte el respaldo de metadata |

**La completitud no se deriva únicamente de datos de negocio.** Mientras nadie
declare `expected_scope` o falte el respaldo de ingestión, el estado es
`UNKNOWN`, y **`UNKNOWN` no se disfraza de completo.**

#### 7.4 La cobertura es un dato versionado, no una constante

Ningún ámbito concreto se codifica en este ADR, en el contrato ni en ELSA. La
cobertura se **determina** por comparación entre declaraciones y cambia con
cada carga sin tocar código.

El centro ausente que la auditoría encontró **es la evidencia del problema, no
la arquitectura**. Su identidad y el conteo de filas afectadas pertenecen a la
evidencia técnica fechada del snapshot auditado, **no al producto ni al manual
del observador**.

#### 7.5 Qué obliga a ELSA

| Estado | ELSA |
|---|---|
| `KNOWN_COMPLETE` | Puede afirmar cobertura **sobre el ámbito declarado**. Nunca «cobertura corporativa completa» |
| `KNOWN_INCOMPLETE` | Declara cobertura insuficiente cuando es relevante (§12.1). Nombra el **ámbito** faltante, nunca un conteo de filas |
| `UNKNOWN` | **Nunca afirma cobertura.** Un `NOT_RETURNED` bajo `UNKNOWN` es especialmente débil |

### 8. Ausencia no autoritativa

#### 8.1 Lo que el contrato hace imposible

> Cero resultados ⟹ «el material no existe».

En V1 es **estructuralmente imposible**: el único valor de ausencia disponible
lleva `authoritative: false`, y **no existe ningún valor que signifique
inexistencia**.

#### 8.2 La taxonomía V1 tiene un solo valor

```jsonc
"absence": {
  "reason":        "NOT_RETURNED_BY_SOURCE",
  "authoritative": false,
  "basis":         "La fuente respondió correctamente sobre la versión de
                    inventario indicada y no devolvió este código."
}
```

Es la **única causa que Materiales puede demostrar** hoy sobre un código
concreto.

#### 8.3 Reservados, con su condición de activación

Ninguno es utilizable en V1. Cada uno solo se activa con un mecanismo que lo
demuestre.

| Reservado | Exigiría | ¿Existe? |
|---|---|---|
| `NOT_IN_ACTIVE_SNAPSHOT` | Que la fuente distinga «no está en el catálogo» de «no está en esta carga» | No |
| `OUTSIDE_DECLARED_COVERAGE` | Atribuir un código ausente a un ámbito **antes** de tenerlo | No: es circular por naturaleza |
| `NOT_IN_SAP` (autoritativo) | Conexión viva con SAP, o garantía escrita de completitud del export | No |

> **Esta tabla es el criterio de cierre de M8.** M8 no se cierra decidiendo: se
> cierra cuando alguno de estos tres tenga un mecanismo que lo demuestre.

#### 8.4 Por qué no hay una causa por cada hallazgo de la auditoría

La auditoría separó nueve causas posibles. **No aparecen como valores del
enum.** Tres dejan de ser ausencia porque tienen canal propio (`REJECTED`,
`NO_ACTIVE_INVENTORY`, y la violación de invariante de §6). Las demás **no son
distinguibles desde dentro de Materiales**, y nombrarlas sería falsa precisión.

Un enum de un valor parece pobre. Es lo contrario: es la forma honesta de decir
«sé que no lo devolví y no sé por qué», dejando abierto el camino de extensión
sin fingir.

### 9. Vigencia

#### 9.1 Forma, obligatoria en toda respuesta

```jsonc
"inventory": {
  "version_number":    17,
  "loaded_at":         "…",
  "row_count":         54494,
  "source_file_label": "<string>" | null,
  "extracted_at":      null
}
```

#### 9.2 Semántica exacta de `loaded_at`

`loaded_at` es **el momento en que terminó la carga en Materiales**. Nada más.

Por sí solo, `loaded_at` **no permite determinar**:

- cuándo se extrajo la información desde SAP;
- la edad exacta del dato;
- si SAP cambió después de esa carga.

`version_number` + `loaded_at`, en conjunto, significan exactamente:

> **«inventario cargado en Materiales el …»**

**No significan** «SAP actualizado al …» ni «extraído de SAP el …».

| ELSA **puede** decir | ELSA **no puede** decir |
|---|---|
| «Según el inventario **cargado en Materiales** el …» | «Según SAP al …» |
| «Versión N del inventario, cargada el …» | «Inventario actualizado al …» |
| «El dato más reciente de que dispone ELSA proviene de la carga del …» | «Actualmente hay N unidades», sin fecha |

#### 9.3 `extracted_at` es nulo y está reservado

`extracted_at` en nulo significa **«la fecha de extracción desde SAP no está
disponible ni registrada en este contrato»**.

**No significa** que el dato no exista en la realidad: significa que este
contrato no lo transporta. El campo se reserva **ahora** para que, cuando
exista un mecanismo que lo registre, entre como cambio **compatible** (§15.1) y
no como ruptura.

**`extracted_at` no se infiere nunca de `source_file_label`.**
`source_file_label` es una **etiqueta opaca** de trazabilidad humana: aunque
siga una convención de nombre que contenga una fecha, es un nombre de archivo
que nadie valida. **ELSA tiene prohibido extraer una fecha de él.**

### 10. Procedencia: cuatro clases disjuntas

Cada campo pertenece a **exactamente una** clase.

#### 10.1 `FACTUAL_SAP`

Columnas de SAP preservadas, con su transformación declarada.

| Campo | Transformación |
|---|---|
| `material` | recorte de espacios |
| `descripcion` | recorte de espacios |
| `unidad` | recorte de espacios |
| `material_antiguo` | recorte + descarte de valores corrompidos en origen |
| `centro`, `almacen` | recorte de espacios |
| `ubicacion` | recorte; el blanco se preserva como nulo y **nunca se hereda de otra fila** |

#### 10.2 `DERIVED_BY_MATERIALES`

**Materiales sigue siendo propietario de sus reglas de cálculo** (regla 4).
ELSA consume el resultado; no lo recalcula y **no exige sus componentes**.

| Campo | Naturaleza de la regla |
|---|---|
| `disponible` | Suma de dos conceptos de existencias de SAP |
| `comprometido` | Proyección directa de un concepto de existencias de SAP |
| `total_disponible`, `total_comprometido` | Agregación sobre las ubicaciones del material |
| `ambito` | Clasificación de la ubicación |
| `dado_de_baja` | Señal de riesgo inferida de la descripción |

> **`disponible` no es un campo de SAP.** Es el resultado de una regla de
> negocio de Materiales. Presentarlo como dato crudo de SAP sería atribuir a SAP
> una decisión que tomó Materiales. Lo mismo vale para todo campo calculado.

Cada campo de esta clase se emite con:

```jsonc
{ "value": null, "rule_reference": "<regla contractual publicada>", "rule_verifiable": true }
```

- `rule_reference` remite a la regla publicada y versionada por Materiales.
- `rule_verifiable` indica si **una prueba contractual del proveedor** puede
  demostrar que el campo cumple su regla.

**La verificación de las reglas derivadas pertenece a Materiales.** ELSA no
exige los componentes crudos y, por tanto, no puede recalcular ninguna
derivación: la verificación recae íntegramente en las pruebas contractuales del
proveedor, que sí dispone de esos componentes. Es un reparto coherente con la
propiedad del dato y convierte esas pruebas en parte no negociable del contrato
(§18).

#### 10.3 `dado_de_baja` tiene regla propia

- Es **`DERIVED_BY_MATERIALES`**.
- **No es un estado de SAP** y no se presenta como tal.
- Mientras su implementación no esté versionada, **`rule_verifiable` es
  `false`**: hoy su regla está publicada como prosa, pero la función que la
  aplica no está en el repositorio del proveedor.
- **No puede sostener por sí solo el núcleo factual de una respuesta.** Puede
  acompañar un hecho como advertencia; no puede ser el hecho.
- **El material no se oculta ni se despriorioriza** por llevar esta señal. La
  regla de Materiales ya decidió que no se ocultan, y algunos conservan
  existencias reales. ELSA no puede ser más restrictiva que la fuente.

#### 10.4 `MATCH_METADATA` e `INVENTORY_METADATA`

- **`MATCH_METADATA`** — cómo se encontró, no qué es: origen de la
  coincidencia, puntuación, número de resultados, indicador de más resultados.
  **Nunca factual.** Conservar el origen de coincidencia es **obligatorio**:
  ADR 0020 §10 establece que un dato hallado por descripción aproximada no es el
  mismo hecho que uno hallado por código exacto.
- **`INVENTORY_METADATA`** — lo definido en §9 y §7.

#### 10.5 Los componentes crudos de existencias no son requisito de V1

Exponer los conceptos de existencias sin agregar **no bloquea el Piloto 0.1** y
queda registrado como **mejora futura de auditabilidad**. Materiales conserva
la propiedad de sus reglas de cálculo.

Lo que sí es requisito de V1 es que **la distinción entre `FACTUAL_SAP` y
`DERIVED_BY_MATERIALES` se preserve**, y que toda derivación llegue con su
`rule_reference` y su `rule_verifiable`.

#### 10.6 Bloque de atribución, obligatorio por resultado

```jsonc
"attribution": {
  "capability":       "get_material_availability",
  "source":           "materiales",
  "source_version":   { "version_number": 17, "loaded_at": "…" },
  "contract_version": "1",
  "read_at":          "…",
  "match_origin":     "<origen de coincidencia>"
}
```

Materializa ADR 0020 §10: **un hecho sin atribución válida no se emite.** Y
separa dos fechas que no deben confundirse: `read_at` (cuándo preguntó ELSA)
frente a `loaded_at` (cuándo terminó la carga que produjo el dato).

### 11. `requires_fresh_inventory`

Sin cambios respecto de ADR 0020 §11.1. Propiedad **determinista** del plan o
la plantilla; **no la decide un LLM**.

Responde a: **¿sé de qué snapshot proviene este dato?**

| Situación | Efecto |
|---|---|
| `true` + vigencia verificable | No degrada |
| `true` + vigencia no verificable | `PARTIAL` + `inventory_freshness_unknown` |
| `false` | La falta de vigencia no degrada por sí sola |

Como `inventory` es obligatorio en toda respuesta del contrato, la vigencia
**deja de ser verificable "a veces"**: lo es siempre que la llamada tenga
éxito.

### 12. `requires_complete_inventory_coverage`

Propiedad nueva del plan o la plantilla. **Determinista. No la decide un LLM.**

Responde a una pregunta **distinta e independiente** de la anterior: **¿sé que
ese snapshot cubre el ámbito que la respuesta necesita?**

| Pregunta | `requires_fresh_inventory` | `requires_complete_inventory_coverage` |
|---|---|---|
| «¿Cuál es la descripción del material X?» | `false` | `false` |
| «¿Tenemos stock del material X?» | `true` | `true` |
| «¿Qué materiales del BOM de Tampella tenemos disponibles?» | `true` | `true` |

**Las dos propiedades son independientes y no se derivan una de otra.** Un dato
puede tener vigencia perfectamente conocida y provenir de un snapshot de
cobertura desconocida.

#### 12.1 Relevancia de la cobertura

La cobertura solo degrada cuando es **relevante** para la respuesta. La
relevancia se determina así, y **conservadoramente**:

| Caso | Relevancia |
|---|---|
| `MATCHED` y la respuesta afirma existencias o totales | **Relevante.** El total puede estar subestimado: puede haber más en un ámbito no cubierto |
| `MATCHED` y la respuesta solo afirma campos estables (descripción, unidad) | **No relevante** |
| `NOT_RETURNED` | **Relevante conservadoramente.** Un código ausente no dice en qué ámbito estaría: la relevancia es indecidible y se resuelve del lado seguro |

> Que la relevancia sea indecidible para un código ausente no es un defecto del
> diseño: es una de las razones por las que M8 sigue abierto. El contrato no la
> resuelve; la declara y degrada en consecuencia.

### 13. Mapeo a `AnswerStatus`

**No se crea ningún `AnswerStatus` nuevo.** Se conservan `ANSWERED`, `PARTIAL`,
`NO_EVIDENCE` y `ERROR` con la semántica de
[ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md). Estos son
estados internos de una capacidad; la traducción la hace la composición del
plan.

| Contrato | Plan | `AnswerStatus` | Aviso |
|---|---|---|---|
| `OK` + `MATCHED`, sin exigencias temporales ni de cobertura | cualquiera | `ANSWERED` | — |
| `OK` + `MATCHED` + `requires_fresh_inventory=true` + vigencia verificable | cualquiera | `ANSWERED` | — |
| `OK` + `MATCHED` + `requires_fresh_inventory=true` + vigencia no verificable | cualquiera | `PARTIAL` | `inventory_freshness_unknown` |
| `OK` + `MATCHED` + `requires_complete_inventory_coverage=true` + cobertura `KNOWN_INCOMPLETE` **relevante** | cualquiera | `PARTIAL` | `coverage_incomplete` |
| `OK` + `MATCHED` + `requires_complete_inventory_coverage=true` + cobertura `UNKNOWN` | cualquiera | `PARTIAL` | `coverage_unknown` |
| `OK` + `MATCHED` + `requires_complete_inventory_coverage=false` | cualquiera | **No degrada por cobertura** | — |
| `OK` + `NOT_RETURNED`, `authoritative:false` | **directa** | `NO_EVIDENCE` | `code_not_found_in_source` |
| `OK` + `NOT_RETURNED` | **compuesta**, con otros códigos resueltos | `PARTIAL` | `code_not_found_in_source` |
| **`NO_ACTIVE_INVENTORY`** | **Materiales es la única capacidad necesaria** | **`ERROR`** | `inventory_unavailable` |
| **`NO_ACTIVE_INVENTORY`** | **compuesta, con otras capacidades que produjeron hechos útiles** | **`PARTIAL`** | `inventory_unavailable` |
| `UNAVAILABLE` | única capacidad necesaria | `ERROR` | — |
| `UNAVAILABLE` | compuesta, con otros hechos | `PARTIAL` | `capability_unavailable` |
| `REJECTED` | cualquiera | No llega a la composición | Se resuelve en la cadena de confianza |

#### 13.1 Por qué `NO_ACTIVE_INVENTORY` directo es `ERROR` y no `NO_EVIDENCE`

Porque **no hubo una fuente válida sobre la cual ejecutar la consulta**. No es
que se consultara y no hubiera nada: es que no se pudo consultar.

**No es equivalente a `OK` + `NOT_RETURNED` → `NO_EVIDENCE`.** Confundirlos
repetiría, en el plano del estado, el mismo error que este ADR corrige en el
plano del dato: decirle a un ingeniero «no hay información» cuando lo cierto es
que el sistema no pudo mirar. ADR 0017 ya fija esa distinción para el
proveedor de generación; aquí se aplica al proveedor de inventario.

#### 13.2 Avisos declarados conceptualmente

Este ADR **declara conceptualmente** tres avisos que hoy no existen en el
núcleo de ELSA:

| Aviso | Cuándo |
|---|---|
| `inventory_unavailable` | No hubo versión de inventario activa sobre la que consultar |
| `coverage_incomplete` | Se **demuestra** que falta un ámbito esperado y es relevante |
| `coverage_unknown` | La cobertura **no se puede determinar** y la respuesta exigía cobertura completa |

**No se implementan en este ADR.**

`coverage_unknown` y `coverage_incomplete` son **distintos y no
intercambiables**: **`UNKNOWN` no se presenta como `INCOMPLETE`.** Afirmar
incompletitud sin evidencia sería el mismo error que este ADR combate, en
espejo. La convención ya establecida por `inventory_freshness_unknown` es
nombrar el desconocimiento en lugar de asimilarlo al peor caso conocido.

### 14. `MaterialsPort`: resultado tipado

El puerto actual documenta que un valor nulo significa que el material no
existe. **Contradice la decisión D21 del subbloque anterior y ADR 0020 §12**, y
debe corregirse **antes** de implementar el adaptador real.

La semántica futura debe distinguir, **como mínimo, cuatro resultados
normales**:

1. resultado factual;
2. la fuente respondió y no devolvió el código;
3. no hay inventario activo disponible;
4. la capacidad no está disponible.

Más el rechazo por autorización, que se resuelve en la frontera correspondiente
y no llega al puerto como resultado.

Dos reglas:

- **Una ausencia normal no es una excepción.** Modelarla como excepción
  convertiría una respuesta legítima en un fallo.
- Las excepciones quedan para fallos técnicos y de programación cuando
  corresponda.

**Este ADR no modifica el puerto.** La forma concreta del tipo de retorno se
decide al implementarlo.

### 15. Versionado contractual

`contract_version` es una **cadena** (`"1"`, `"1.1"`), no un entero: permite
cambios compatibles sin renumerar.

Viaja en el request (qué entiende ELSA) y en la respuesta (qué emitió la
fachada). La asimetría es informativa.

#### 15.1 Compatibilidad

| Cambio | Clase |
|---|---|
| Añadir un campo **opcional** a la respuesta | Compatible |
| Añadir un parámetro **opcional** al request | Compatible |
| Rellenar un campo reservado que valía nulo | Compatible |
| Añadir un valor a un enum cerrado | **Incompatible por defecto**, salvo que el consumidor declare tratamiento de valores desconocidos |
| Quitar o renombrar un campo | Incompatible |
| **Cambiar el significado de un campo sin cambiar su nombre** | **Incompatible, y el más peligroso**: es invisible en un diff |
| Cambiar la representación esperada de `material_code` | Incompatible |
| Que el lookup exacto deje de garantizar su invariante (§6) | Incompatible |

#### 15.2 Deprecación

Cinco requisitos. **Ninguna duración se fija aquí**: fijarla sin tráfico medido
sería inventar un número.

1. Anuncio escrito en la definición canónica, nombrando la versión sustituta.
2. **Convivencia**: ambas versiones responden simultáneamente.
3. La versión en deprecación se marca como tal en el descriptor.
4. ELSA registra en telemetría cada llamada a una versión deprecada. **Ese
   registro es lo que permitirá fijar el plazo con datos.**
5. La retirada exige aprobación del Contract Owner y telemetría a cero.

#### 15.3 Cómo sabe ELSA qué versión consume

Tres capas: configuración (versión esperada, declarada) → arranque (consulta el
descriptor, compara y refleja el resultado en el estado de salud) → cada
respuesta (`contract_version` en el sobre, registrado en la auditoría si
difiere de lo esperado).

**Nunca se adivina.** Si el descriptor no responde, la versión es desconocida y
el servicio se declara degradado, no se asume la esperada. Cumple la regla 9 de
[`CLAUDE.md`](../../CLAUDE.md): el sistema funciona parcialmente y lo declara.

### 16. Ownership

#### 16.1 El rol

**`Contract Owner Materiales–ELSA`.** Es un **rol**, no una persona. Ninguna
persona se nombra en este ADR ni en la arquitectura.

#### 16.2 Responsabilidades

- Aprobar cambios incompatibles.
- Mantener y versionar el contrato.
- Mantener las **pruebas contractuales del proveedor**.
- Coordinar las deprecaciones.
- Informar a los consumidores.
- Asegurar que la **semántica factual permanezca documentada**.

#### 16.3 Quién puede romper el contrato

**Solo el Contract Owner**, y solo con constancia escrita.

**No** pueden romperlo: una sustitución de función hecha directamente sobre la
base de datos, un cambio de interfaz en Materiales, ni un cambio de adaptador
en ELSA.

> Este punto no es hipotético: es el mecanismo por el que la función de búsqueda
> actual dejó de estar versionada (Contexto §2).

#### 16.4 Dónde vive la definición canónica

**En el repositorio de Materiales**, versionada junto a su esquema.

Dos motivos, ambos de la auditoría: es donde se ejecuta, y el modo de fallo
demostrado es la deriva entre la base viva y el repositorio. Alejar la
definición del punto donde puede divergir empeoraría el problema.

| Repositorio | Contiene |
|---|---|
| **Materiales** | Definición canónica versionada, `contract_version`, descriptor, pruebas contractuales del proveedor, **asignación operativa del ocupante del rol** |
| **ELSA** | El contrato **esperado** como pruebas de conformidad, y este ADR |

La prueba de conformidad **no es una segunda definición**: es una aserción
sobre la forma. Si Materiales cambia y ELSA no, la prueba falla. Ese es todo el
objetivo.

#### 16.5 Ocupante inicial

**Pendiente. Este ADR no nombra a ninguna persona.**

La asignación operativa del ocupante **vive junto a la definición canónica del
contrato, en el repositorio de Materiales**. ELSA puede **referenciar** esa
asignación, pero **no mantiene una segunda fuente de verdad independiente**:
dos listas de responsables que puedan divergir son peores que ninguna.

La asignación real debe resolverse **antes del primer tester** y forma parte de
M7. Debe poder cambiar **sin modificar este ADR**.

### 17. Compatibilidad con lote futuro

**No se implementa lote.** M2 sigue abierto y no bloqueante.

El contrato lo deja preparado con una sola decisión de forma: **`results` es
una lista desde V1**, aunque V1 envíe un solo código. Añadir lote después es
**aditivo en el request** y **cero cambios en la respuesta**.

En el plano de la capacidad, `get_material_availability` mantiene la forma de
lote que ADR 0020 §5 ya declaró; el **transporte** V1 es unitario y el
adaptador hace el reparto. Son dos niveles distintos y se mantienen distintos.

### 18. Pruebas contractuales

El contrato no se sostiene por buena voluntad, sino porque **un cambio
incompatible rompe una prueba**.

- **En ELSA**: la suite completa contra un **fake de la fachada**.
  Determinista, sin red, sin datos reales, en integración continua. Es lo que
  permite que un clon limpio pase la suite (regla 24).
- **En Materiales**: un subconjunto contra la base real, incluyendo la
  verificación de toda derivación cuya `rule_verifiable` sea `true` (§10.2).

Las pruebas son **entregable obligatorio antes del primer tester**, no trabajo
posterior.

---

## Consecuencias

### 19. Qué queda decidido y qué sigue pendiente

**Este ADR no cierra operacionalmente ningún punto M1–M8.** Cierra decisiones;
no cierra implementaciones ni verificaciones.

#### 19.1 M1 — decisión arquitectónica cerrada, implementación contractual pendiente

**Decidido:** la superficie que ELSA consumirá es una fachada contractual
versionada, con la forma, la taxonomía, la vigencia, la cobertura, la
procedencia y las reglas de versionado que fija este ADR.

**Pendiente:**

- la fachada **no existe**;
- la definición canónica **todavía debe materializarse** en el repositorio de
  Materiales;
- **no existen pruebas contractuales**.

**M1 sigue siendo bloqueante.**

#### 19.2 M7 — rol y gobernanza definidos, ocupante inicial pendiente

**Definido:** el rol `Contract Owner Materiales–ELSA`, sus responsabilidades,
su autoridad exclusiva para aprobar rupturas, la ubicación de la definición
canónica y la ubicación de la asignación operativa.

**Pendiente:**

- el **ocupante inicial no está asignado**;
- la gobernanza **no está materializada** en el repositorio de Materiales.

**M7 sigue siendo bloqueante y no se declara cerrado** hasta asignar el
ocupante real y materializar la gobernanza correspondiente.

### 20. Lo que aprobar este ADR **no** significa

| No significa | Estado real |
|---|---|
| La fachada existe | **No existe.** Construirla es trabajo posterior y autorizado aparte |
| M1 está cerrado operacionalmente | **No.** Decisión cerrada, implementación contractual pendiente |
| M7 está cerrado | **No.** Rol definido, ocupante inicial pendiente |
| M3 está cerrado | **Bloqueado por prueba real.** Faltan los archivos del BOM |
| M5 está cerrado | **Bloqueado por prueba real.** Falta la comprobación pública |
| M8 está cerrado | **Abierto.** §8.3 fija el criterio que lo cerraría |
| Materiales ya fue modificado | **No se ha tocado.** La auditoría fue de solo lectura |
| La representación de frontera está decidida | **Indecidible hasta M3** |

> **Estado, 2026-09-19.** Tres filas de esta tabla cambiaron, y **solo tres**:
> **M3** y **M5** dejaron de estar «bloqueados por prueba real» —ambas pruebas
> se ejecutaron y quedan **resueltos para V1**—, y con M3 la **representación
> de frontera quedó decidida** como **M3-A**. Lo decide
> [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md),
> sobre [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md).
> **El resto de la tabla no cambia**: la fachada sigue sin existir, M1 y M7
> siguen sin cerrarse operacionalmente, M8 sigue **abierto** con su §8.3
> intacto, y Materiales sigue sin tocarse.

### 21. Condiciones previas, en orden

#### 21.1 M3 es condición previa al adaptador

**Ningún adaptador de inventario puede escribirse antes de M3.** La
representación de frontera es indecidible sin la medición sobre el BOM real.
ADR 0020 §5 ya lo establece; aquí se confirma sin ampliarlo.

La forma canónica de comparación permanece **provisional hasta M3**, sigue
siendo normalización **interna** de ELSA, y **no se asume que sea la
representación que deba enviarse a Materiales**.

> **Estado, 2026-09-19. La condición previa está cumplida.** M3 se midió sobre
> el BOM real de Tampella según el protocolo D23 y quedó **resuelto para V1**
> como **M3-A**, decidido en
> [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
> §8 sobre [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md) §2 y §3.
> **El adaptador de inventario deja de estar bloqueado por M3** (ADR 0024 §9),
> lo que levanta la condición previa **sin autorizar** su construcción.
>
> Dos advertencias que este levantamiento **no** retira:
>
> - la forma canónica de comparación **sigue siendo normalización interna de
>   ELSA**, y sigue sin ser, por sí misma, lo que se envía a Materiales: lo que
>   cruza la frontera es **M3-A**;
> - **M3-A vale para el dominio observado del Piloto Tampella V1.** El XLSX
>   almacena los códigos numéricamente, de modo que la medición **no demuestra**
>   que nunca haya existido un cero inicial aguas arriba, y **no autoriza**
>   ninguna regla global sobre ceros iniciales en SAP.
>
> **Resuelto:** M3-A ya está registrado como decisión arquitectónica en
> [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
> §8, conforme a la regla 25.

#### 21.2 M5 es condición previa a la autenticación real

El mecanismo está probado en producción para la identidad: JWT del usuario más
clave publicable, sin credencial de servicio. Queda por verificar el
**algoritmo de firma**.

- Si la comprobación pública demuestra **firma asimétrica**, la validación de
  ELSA se confirma y M5 avanza.
- Si demuestra **firma simétrica heredada, M5 se detiene.** **No se comparte
  automáticamente ningún secreto simétrico con ELSA**: ese escenario exige
  **revisión arquitectónica explícita** antes de proceder, porque convertiría a
  ELSA en depositaria de un secreto de Materiales, que es una postura distinta
  de la actual.

> **Estado, 2026-09-19. La bifurcación se resolvió por la primera rama.** La
> comprobación pública demostró **firma asimétrica**: el JWKS real de
> Materiales publica una clave `ES256` / `EC` con `use=sig` y `kid` presente, y
> 30 de 30 llamadas autenticadas al RPC real respondieron sin error con el JWT
> de un usuario real ([evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md)
> §4). **La validación de ELSA queda confirmada y M5 queda resuelto para V1**
> por
> [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
> §11.
>
> Por tanto **el segundo escenario no se activa**: no hay secreto simétrico que
> compartir, y la revisión arquitectónica que ese caso habría exigido **no hace
> falta**. La postura de ELSA frente a Materiales **no cambia**.
>
> **Resuelto:** este cierre ya está registrado en
> [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
> §11, conforme a la regla 25.

#### 21.3 M8 permanece abierto

Mientras lo esté, rige la redacción de ADR 0020 §12: una consulta directa en la
que la fuente responde correctamente y no devuelve el código produce
`NO_EVIDENCE` con `code_not_found_in_source`, y **ELSA no afirma que el
material no existe**.

#### 21.4 Secuencia

1. Aprobar el contrato conceptual.
2. Materializar este ADR.
3. Cerrar las decisiones diferidas (§22).
4. **Después**, solicitar e implementar la fachada en Materiales.

Pedir una función sin contrato escrito reproduciría exactamente el problema que
este ADR resuelve.

### 22. Decisiones explícitamente diferidas

| # | Decisión | Se decide |
|---|---|---|
| 1 | Representación de frontera `ELSA → Materiales` | Tras **M3** |
| 2 | Confirmación o corrección de la forma canónica de comparación | Tras **M3** |
| 3 | Aceptación del algoritmo de firma | Tras **M5**; si es simétrico heredado, en revisión arquitectónica |
| 4 | Semántica completa de `dado_de_baja`, `ubicacion` y `ambito` | **M6**, parcialmente abierto |
| 5 | Activación de cualquier causa de ausencia adicional | **M8**, con mecanismo demostrable |
| 6 | Consulta por lote | **M2**, con telemetría real |
| 7 | Plazo de deprecación | Con telemetría de uso, no antes |
| 8 | Forma concreta del tipo de retorno de `MaterialsPort` | Al implementarlo |
| 9 | Dónde almacena Materiales su metadata de cobertura y su `expected_scope` | Decisión interna de Materiales |
| 10 | Exposición de los componentes crudos de existencias | Mejora futura de auditabilidad; no bloquea el piloto |
| 11 | Ocupante inicial del rol de Contract Owner | Antes del primer tester, en el repositorio de Materiales |
| 12 | Entrega de `search_materials_by_text` | Fuera del Piloto 0.1 inicial |

> **Estado, 2026-09-19. Las filas 1, 2 y 3 quedan CERRADAS** por
> [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
> §14, sobre [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md):
>
> | # | Resultado |
> |---|---|
> | **1** | Representación de frontera: **M3-A** (ADR 0024 §8), **para V1** |
> | **2** | Forma canónica de comparación: **confirmada** como normalización **interna**, distinta de la de frontera (ADR 0024 §8.1) |
> | **3** | Algoritmo de firma: **`ES256` asimétrico aceptado**, sin revisión arquitectónica porque el escenario simétrico no se dio (ADR 0024 §11.1) |
>
> **Las filas 4 a 12 no cambian.**

### 23. Riesgos que este ADR mitiga, y el que no

| Riesgo | Mitigación |
|---|---|
| El contrato cambia sin dejar rastro | Definición canónica versionada + descriptor + pruebas contractuales + autoridad única |
| «No encontrado» leído como «no existe» | `NOT_RETURNED` + `authoritative:false`, sin ningún valor que signifique inexistencia |
| Cobertura incompleta invisible | `coverage` obligatoria en toda respuesta; `UNKNOWN` no se disfraza de completo ni de incompleto |
| Cobertura afirmada sin evidencia | `observed_scope` exige metadata de ingestión; no se deriva de datos de negocio |
| Caída silenciosa a similitud | Operaciones separadas + invariante verificable del lookup |
| Vigencia confundida con actualidad de SAP | Semántica exacta de `loaded_at` + `extracted_at` reservado y no inferible |
| «No se pudo mirar» presentado como «no hay nada» | `NO_ACTIVE_INVENTORY` directo mapea a `ERROR`, no a `NO_EVIDENCE` |
| Cálculo de Materiales presentado como dato de SAP | Cuatro clases disjuntas + `rule_reference` y `rule_verifiable` obligatorios |
| Fuga de contexto hacia Materiales | Minimización de datos verificable por prueba |

**El riesgo que no mitiga:** que la representación del código difiera entre el
BOM y Materiales. El contrato hace que ese fallo sea **ruidoso** en lugar de
silencioso, pero **no lo resuelve**. Lo resuelve M3.

### 24. Relación con otros documentos

- El protocolo de medición de M3 vive en
  [el contrato funcional del Piloto 0.1](../piloto-0-1/contrato-funcional.md)
  §11 y no se reescribe aquí.
- La auditoría que fundamenta el Contexto §2 se documentará en el cierre del
  subbloque 5.0.b, según
  [el estándar de cierre de bloques](../project/BLOCK_CLOSURE_STANDARD.md).
- El subbloque anterior quedó cerrado en
  [su documento de cierre](../bloque-5-0-subbloque-diseno-normativo-cierre.md).

### 25. Estado de M1–M8 después de este ADR

**Ninguno se declara «cerrado operacionalmente» mientras siga dependiendo de
Materiales real.**

| ID | Estado | Bloqueante |
|---|---|---|
| **M1** | **Decisión arquitectónica cerrada · implementación contractual pendiente** | **Sí** |
| **M2** | **Abierto** | **No** |
| **M3** | **Bloqueado por prueba real** | **Sí** |
| **M4** | **Semántica contractual definida · verificación e implementación de metadata pendientes** | **Sí** |
| **M5** | **Bloqueado por prueba real** | **Sí** |
| **M6** | **Parcial** | **Sí** |
| **M7** | **Rol y gobernanza definidos · ocupante inicial pendiente** | **Sí** |
| **M8** | **Abierto** | **Sí** |

> **Actualizado por [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md).**
> La fila de **M8** se lee hoy **«Abierto · no bloqueante»**: la cobertura
> `UNKNOWN` se acepta para V1 bajo controles compensatorios verificables.
> **M8 no se cierra**, y el criterio de cierre del §8.3 de este ADR queda
> **intacto y sin cumplir**. El resto de la tabla **no cambia**.

> **Actualizado el 2026-09-19 por
> [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md).** Dos filas más
> cambian de lectura, y **solo dos**:
>
> | ID | Estado el 2026-09-19 | Bloqueante |
> |---|---|---|
> | **M3** | **Resuelto para V1** como **M3-A**, medido sobre datos reales y decidido en [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md) §8 | **No** |
> | **M5** | **Resuelto para V1** por [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md) §11: JWKS asimétrico `ES256`/`EC`, JWT de usuario real verificado contra el RPC real | **No** |
>
> **M1, M2, M4, M6, M7 y M8 conservan exactamente el estado de la tabla de
> arriba.** Ninguno se cierra por asociación. En particular **M8 sigue
> abierto** bajo [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md), y
> el §8.3 de este ADR sigue **intacto y sin cumplir**.
>
> La frase que encabeza este apartado —«ninguno se declara cerrado
> operacionalmente mientras siga dependiendo de Materiales real»— **se respeta**:
> M3 y M5 se resuelven **precisamente porque se midieron contra Materiales
> real**, no por decisión de escritorio.
>
> Ambos cierres están registrados en
> [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md),
> conforme a la regla 25. **M3-A vale para el dominio observado del Piloto
> Tampella V1**, no universalmente (ADR 0024 §10).

### 26. Trazabilidad de los requisitos de este ADR

| # | Requisito | Sección |
|---|---|---|
| 1 | Contexto | Contexto §1–§2 |
| 2 | Problema | Contexto §3–§4 |
| 3 | Decisión | Decisión §1 |
| 4 | Separación lookup / búsqueda textual | §2 |
| 5 | Request mínimo | §3 |
| 6 | Response estructurado | §4 |
| 7 | `call_status` | §5 |
| 8 | `outcome` | §6 |
| 9 | Cobertura | §7 |
| 10 | Ausencia no autoritativa | §8 |
| 11 | Vigencia | §9 |
| 12 | Procedencia, cuatro clases | §10 |
| 13 | `requires_fresh_inventory` | §11 |
| 14 | `requires_complete_inventory_coverage` | §12 |
| 15 | Mapeo a `AnswerStatus` | §13 |
| 16 | `MaterialsPort` tipado futuro | §14 |
| 17 | Versionado contractual | §15 |
| 18 | Ownership | §16 |
| 19 | Minimización de datos | §3.1 |
| 20 | Compatibilidad batch futura | §17 |
| 21 | M3 como condición previa | §21.1 |
| 22 | M5 como condición de autenticación | §21.2 |
| 23 | M8 todavía abierto | §21.3 |
| 24 | Decisiones diferidas | §22 |
