# ADR 0020 — Capacidades componibles y planes de ejecución controlados

- Estado: **propuesto**
- El carácter bloqueante de **M8** (§17) se redefine en
  [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md). El resto de
  este ADR, incluida la restricción del §12, **no se reabre**
- Bloque: 5.0 (Piloto 0.1)

## Contexto

Hasta el Bloque 4.5, ELSA respondía desde **una sola fuente por pregunta**: o el
conocimiento estructurado publicado (`elsa.core.retrieval` sobre `BomItemRecord`
y `FailureModeRecord`), o el documental (`HybridRetrievalService` →
`GroundedGenerationService`). Las dos rutas están implementadas y probadas, y
ninguna sabe de la otra.

Las preguntas reales de planta no respetan esa frontera. La pregunta de
referencia del piloto —«¿Qué rodamientos usa Tampella y tenemos
disponibilidad?»— exige encadenar dos fuentes de verdad de propietarios
distintos:

- la relación **activo → material SAP** solo la puede afirmar el BOM de
  Ingeniería aprobado, que vive en ELSA;
- la relación **material SAP → existencias, centro, almacén** solo la puede
  afirmar el Asistente de Materiales, que es su propietario (regla 4) y cuyo
  inventario no se duplica aquí.

[ADR 0010](0010-conocimiento-estructurado-vs-documental.md) cerró que el
conocimiento estructurado no se chunkea ni se resuelve por parecido semántico.
Lo que no resolvió es **cómo se componen dos fuentes estructuradas en una sola
respuesta sin que un modelo invente el puente entre ellas**. Ese es el vacío que
cierra este ADR.

La tentación conocida es un agente con herramientas: dar al modelo acceso al BOM
y a Materiales y dejar que decida la secuencia. Se rechaza aquí por una razón
operativa antes que ideológica: el espacio de planes de un agente libre no es
enumerable, y por tanto no es testeable. En un sistema que va a mandar a un
ingeniero a un almacén, una respuesta que no se puede reproducir no es una
respuesta.

## Decisión

### 1. Una Capacidad es una operación declarada, no una herramienta ofrecida a un modelo

Una **Capacidad** convierte una entrada estructurada en una salida estructurada
con procedencia declarada. Declara, como mínimo:

| Atributo | Contenido |
|---|---|
| `name` | Identificador estable, en inglés (sección 3 de `CLAUDE.md`) |
| `purpose` | Una frase: qué pregunta responde |
| `inputs` | Tipos exigidos, **ya normalizados**. Nunca texto libre del usuario |
| `outputs` | Registro tipado (`frozen dataclass`). Nunca texto redactado |
| `source_of_truth` | Fuente que **afirma** la salida, con su versión |
| `authorization` | Requisito propio de autorización (§7) |
| `errors` | Conjunto cerrado: `unauthorized`, `not_found`, `unavailable`, `timeout` |
| `determinism` | `deterministic` (regla o consulta exacta) o `ranked` (motor con puntaje ajeno) |
| `absence_semantics` | Qué significa que esta capacidad no devuelva algo (§12) |
| `resolves_alone` | Si puede cerrar una respuesta por sí sola |
| `feeds` | Qué capacidades consumen su salida, **y por qué campo** |

Una capacidad **no puede** declarar como `source_of_truth` una fuente que no
consultó ella misma. «Lo dijo el modelo» no es una fuente.

Una capacidad vive en `src/elsa/core/`; su dependencia externa, si la tiene,
entra por un `Protocol` de `src/elsa/ports/` con su fake determinista (regla 6,
[ADR 0003](0003-puertos-y-adaptadores-para-modelos-reemplazables.md)). Ninguna
capacidad importa un adaptador.

### 2. El catálogo de capacidades es cerrado

No hay registro dinámico, ni descubrimiento, ni carga por configuración. Añadir
una capacidad es un cambio de código revisado, con su prueba.

| Capacidad | Fuente de verdad | Determinismo | Puerto |
|---|---|---|---|
| `resolve_asset` | Activos técnicos, **restringidos al universo autorizado** (§7.2) | `deterministic` | `KnowledgeRepositoryPort` |
| `get_published_bom` | Versión publicada del BOM y sus renglones | `deterministic` | `KnowledgeRepositoryPort` |
| `search_bom_components` | Los renglones ya recuperados, vía `elsa.core.retrieval.search` | `deterministic` | ninguno |
| `get_material_availability` | Asistente de Materiales | `ranked` — **el ranking es suyo, no nuestro** | `MaterialsPort` **ampliado** |

`MaterialsPort` (`src/elsa/ports/materials.py`) se **amplía** con la consulta
factual de inventario; hoy expone `get_material` / `search_materials` sobre un
`Material(code, description)` que su propio docstring declara provisional.

`MaterialsIdentityPort` (`src/elsa/ports/materials_identity.py`) es un puerto
**distinto**, cubre la identidad y **no se mezcla con esto**: son dos
superficies del mismo sistema externo, no dos abstracciones de la misma cosa.

Fuera del catálogo: `get_failure_modes`, `search_documents`, la estructura
técnica de SAP para ingenieros y el histórico de intervenciones.

### 3. Un `CapabilityPlan` es dato, no código

```text
QuestionSignals  →  PlanSelection  →  CapabilityPlan  →  PlanExecution  →  ComposedAnswer
(señales léxicas    (regla sobre      (secuencia         (resultado y      (hechos con
 y de intención)     señales)          cerrada)           traza por paso)   procedencia)
```

Un `CapabilityStep` lleva: la capacidad, sus entradas (literales o una
referencia explícita `paso[i].campo`), su requisito de autorización y su
comportamiento ante fallo (`abort` o `degrade`).

El plan se construye **antes** de ejecutar nada, se registra entero y no se
modifica durante la ejecución. Un plan que no puede construirse no se improvisa:
produce aclaración o `NO_EVIDENCE`.

### 4. La selección de plan es determinista y distingue intención de pertenencia

El plan se elige con reglas sobre señales objetivas, nunca con un modelo. Las
señales son las que ya produce el código existente —`detect_signals` de
`elsa.core.query_signals` y `parse_query` de `elsa.core.retrieval`— más un
**léxico de intención versionado en el repositorio**.

**La pertenencia de un código al BOM no es una señal de intención.**

| Pregunta | Señal decisiva | Plan |
|---|---|---|
| «Busca el material 123456» | verbo de búsqueda de material + identificador | `material_lookup` |
| «¿Tenemos stock de 123456?» | término de disponibilidad + identificador | `material_lookup` |
| «¿123456 pertenece a Tampella?» | término de pertenencia + activo + identificador | `asset_membership` |
| «¿Qué rodamientos usa Tampella y tenemos stock?» | activo + término descriptivo + término de disponibilidad | `asset_components_with_availability` |
| «123456» | identificador sin verbo ni activo | `clarify` |

«Busca el material 123456» va a Materiales **aunque 123456 esté en el BOM de
Tampella**. El BOM responde a qué pertenece algo; Materiales responde qué es y
dónde está. Confundir las dos preguntas porque el dato aparece en ambas fuentes
es el error que este apartado prohíbe.

El léxico de intención es **dato del repositorio**: una lista declarada,
versionada y cubierta por pruebas, no expresiones dispersas por el código.
Cuando el léxico no reconoce la intención, la salida segura es `clarify`, nunca
adivinar.

### 5. El encadenamiento es por campo declarado

El paso N no lee la salida del paso N−1 como texto ni la vuelve a interpretar.
Declara de qué paso y de qué campo toma su entrada:

```text
get_material_availability.codes  ←  search_bom_components[*].sap_code
```

La normalización ocurre **una sola vez, en la frontera**:
`elsa.core.normalization.canonical_sap_code` al extraer; la representación que
exija Materiales se aplica **dentro de su adaptador**, nunca en el núcleo. La
clave de unión entre fuentes es el código canónico, y la unión es un cruce
explícito, nunca una fusión por parecido.

Si el BOM repite un código en dos posiciones, son **dos renglones de BOM y una
sola consulta de disponibilidad**, y la respuesta lo dice así.

> La forma canónica definitiva depende de la medición M3 (§17). Hasta que esa
> medición exista, ningún adaptador de inventario fija su representación de
> frontera.

> **Estado, 2026-09-19. La medición existe.** M3 se midió sobre datos reales y
> la representación de frontera quedó fijada para V1 como **M3-A** en
> [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
> §8, sobre [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md) §3. **La regla de
> este apartado no cambia**: la normalización sigue ocurriendo una sola vez, en
> la frontera, y la representación que exige Materiales se sigue aplicando
> **dentro de su adaptador**, nunca en el núcleo. Lo único que cambia es que ya
> se sabe cuál es.

### 6. No hay agente autónomo

Prohibido por diseño, no por ahora:

- que un modelo elija qué capacidad ejecutar;
- que un modelo construya o modifique un plan;
- que un modelo genere SQL, códigos SAP o parámetros de una capacidad;
- bucles de herramienta, replanificación en caliente, herramientas registradas
  dinámicamente.

El LLM, cuando exista en esta ruta, entra **después** de que el plan haya
terminado y los hechos estén cerrados (§14). Reabrir esto exige un ADR nuevo
(regla 25).

### 7. La autorización es por capacidad, y no todas piden lo mismo

`authorize()` de `elsa.core.authorization` sigue siendo la única autoridad y
sigue ejecutándose **antes** de recuperar (regla 3). Lo nuevo es que cada
capacidad declara su requisito, y ese requisito se comprueba **antes de cada
paso**, no una sola vez al principio del plan.

| Capacidad | Requisito |
|---|---|
| `resolve_asset` | Cuenta ELSA activa + alcance autorizado sobre el activo |
| `get_published_bom` | El alcance del activo ya resuelto |
| `search_bom_components` | Ninguno adicional: opera sobre renglones ya autorizados |
| `get_material_availability` | Cuenta ELSA activa + JWT válido + perfil activo en Materiales. **Ningún alcance sobre activos de ELSA** |

#### 7.1 Materiales directo no exige alcance sobre activos

Una consulta directa a Materiales puede ejecutarse aunque el usuario tenga
**cero permisos sobre activos de ELSA**, siempre que la cuenta ELSA esté activa,
el JWT sea válido y el perfil esté activo en Materiales.

Esto **no concede** acceso al BOM ni a ningún activo: la autorización de
Materiales sigue perteneciendo a Materiales, y la de ELSA sigue siendo
default-deny sobre lo suyo.

La asimetría es deliberada y conviene entenderla bien: **Materiales no tiene
alcances**. Cualquier perfil activo allí ve su catálogo completo, y ese usuario
ya puede entrar directamente. La autorización de ELSA no restringe *qué se puede
ver* de Materiales; restringe **qué códigos llegan a preguntarse** cuando esos
códigos salieron del BOM de un activo. Dar por supuesto lo contrario sería un
fallo de seguridad por malentendido, y por eso queda escrito.

#### 7.2 `resolve_asset` no divulga la existencia de activos

Queda **prohibido** el patrón «buscar el activo en el catálogo global →
confirmar que existe → autorizar después».

`resolve_asset` opera únicamente sobre el **universo autorizado** del usuario:
el mismo conjunto que `authorize()` admite y que `GET /api/v1/assets` ya
devuelve filtrado. Nunca consulta el catálogo completo para luego descartar.

De ello se derivan cuatro obligaciones para cualquier plan:

1. Un activo fuera del universo autorizado es **indistinguible** de uno
   inexistente: mismo código de error, mismo mensaje, misma forma.
2. Una pregunta de aclaración **solo puede nombrar activos del universo
   autorizado**. Nunca los ofrece como candidatos, ni los insinúa, ni los
   sugiere por parecido.
3. La ruta no puede ramificar según la existencia antes de autorizar: es la
   ausencia de esa rama lo que elimina la diferencia observable, incluida la de
   tiempos.
4. El comportamiento actual —la autorización como sub-dependencia de
   `resolve_asset`, resuelta **antes** del cuerpo del endpoint— se conserva tal
   cual y se extiende a las capacidades.

### 8. Materiales se consulta con el JWT del usuario

ELSA **no** usa credencial privilegiada contra Materiales. La llamada lleva el
JWT del propio usuario, de modo que la comprobación de perfil activo —y con ella
toda la frontera de autorización de Materiales— se evalúa allí, sobre esa
persona.

El mecanismo ya existe: la identidad verificada transporta el token, y el
adaptador de identidad de Materiales es el precedente exacto de cómo se usa sin
registrarlo ni guardarlo
([ADR 0005](0005-verificacion-real-del-jwt-de-materiales.md)). El adaptador de
inventario replica ese patrón, **por el puerto ampliado del §2, no por el puerto
de identidad**.

Una credencial de servicio contra Materiales convertiría a ELSA en un canal de
fuga del inventario de otro sistema. Queda prohibida.

### 9. Minimización entre capacidades

A una capacidad se le entrega **solo lo que su contrato exige**. A
`get_material_availability` se le pasan códigos SAP y nada más.

No se envían a Materiales: el nombre del activo, la pregunta del usuario, los
términos de búsqueda, los alcances de ELSA, el identificador de petición
interno, el contexto documental ni identidad de ELSA más allá del JWT que la
propia llamada requiere.

La razón no es formal: Materiales es un sistema externo con su propia
telemetría. Todo lo que le enviemos de más queda registrado allí, fuera de
nuestro control y fuera de nuestra política de retención.

### 10. Procedencia por hecho, no por respuesta

Un hecho es un triple `(sujeto, campo, valor)` acompañado de una atribución que
nombra la capacidad que lo produjo, la fuente con su versión, el identificador
dentro de esa fuente y cuándo se leyó.

| Hecho | Capacidad | Fuente y versión |
|---|---|---|
| «Este renglón está asociado a Tampella» | `search_bom_components` | BOM publicado, renglón y fila de origen |
| «Su código es SAP-XXXX» | `get_published_bom` | BOM publicado, campo `sap_code` del renglón |
| «Hay N unidades» | `get_material_availability` | Materiales, versión de inventario y su fecha |
| «Están en Centro Y / Almacén Z» | `get_material_availability` | Materiales, misma versión |
| «Se lubrica cada N horas» | `search_documents` (diferida) | Procedencia documental del chunk |

**Un hecho sin atribución válida no se emite.** Es la misma disciplina que
`check_grounding` de `elsa.core.grounding` aplica hoy a los marcadores de cita,
extendida al dato estructurado.

Dos reglas derivadas:

- **La cita legible no cambia.** `Citation` sigue siendo lo que una persona usa
  para ir a la fuente, sin identificadores internos. Los UUID siguen en
  `AnswerAudit`.
- **El `origen` que devuelve Materiales se conserva y se muestra.** Su motor ya
  declara si acertó por código exacto, código antiguo, referencia, medida o
  descripción. **Un stock hallado por descripción aproximada no es el mismo
  hecho que uno hallado por código exacto**, y ELSA no puede presentarlos igual.
  El dato ya viene en la respuesta: descartarlo sería perder procedencia que la
  fuente nos regala.

### 11. La afirmación de disponibilidad exige vigencia

El stock de Materiales **es un snapshot**, no una lectura en vivo: una
exportación alimenta una versión de datos, y esa versión tiene fecha.

La vigencia **no crea un `AnswerStatus` nuevo**. Existe como:

- **atributo de procedencia** del dato de inventario, obligatorio;
- **`AnswerWarning`** (`inventory_freshness_unknown`) cuando no puede
  verificarse.

#### 11.1 `requires_fresh_inventory` es una propiedad del plan

La degradación por vigencia **no depende de que se haya ejecutado una
capacidad**. Depende de si la respuesta utiliza hechos cuyo significado depende
de la actualidad del snapshot.

Cada plantilla de plan declara una propiedad determinista
`requires_fresh_inventory: bool`. **No la decide un LLM**: se deriva de la
plantilla y de qué campos va a afirmar la composición.

| Pregunta | `requires_fresh_inventory` |
|---|---|
| «¿Tenemos stock de X?» | `true` |
| «¿Qué rodamientos de Tampella tenemos disponibles?» | `true` |
| «¿Cuál es la descripción del material X?» | `false`, siempre que la respuesta no afirme campos temporales |

Consecuencia sobre el estado, desarrollada en la tabla del §13:

- `requires_fresh_inventory = true` y vigencia verificable → `ANSWERED` si todo
  lo demás está completo.
- `requires_fresh_inventory = true` y vigencia no verificable → `PARTIAL` +
  `inventory_freshness_unknown`.
- `requires_fresh_inventory = false` → la falta de vigencia **no degrada por sí
  sola** el `AnswerStatus`.

**Qué campos concretos de Materiales son sensibles al tiempo no se fija en este
ADR.** Se cierra con M6 (§17), que debe determinar la semántica y la
temporalidad real de `disponible`, `comprometido`, `dado_de_baja`,
`ubicaciones`, `ambito` y de cualquier otro campo devuelto. **No se asume que
solo `disponible` cambia con el snapshot.**

Si la vigencia no se puede verificar, ELSA **no presenta el dato como actualidad
confirmada**: no lo oculta, no lo inventa, y lo entrega degradado y marcado.

### 12. La ausencia no es inexistencia

Que una fuente no devuelva un código **no significa que el material no exista**.

Cada capacidad declara su `absence_semantics`. Para
`get_material_availability`, esa semántica **es hoy desconocida** y forma parte
del contrato pendiente con Materiales (M8, §17). Una ausencia puede significar,
entre otras cosas: material inexistente, material ausente del snapshot vigente,
sede no cubierta por la exportación, dato no cargado, o simplemente búsqueda sin
coincidencia.

**Mientras M8 no esté cerrado**, ELSA solo puede afirmar lo equivalente a:

> «Materiales no devolvió este código en la fuente consultada.»

y **no** puede afirmar «el material no existe».

ELSA solo podrá emitir la inexistencia como **hecho negativo atribuido** cuando
el contrato de Materiales garantice que su ausencia es autoritativa. Esa
garantía es un dato del contrato, no una suposición del código.

### 13. Composición parcial: los cuatro estados existentes bastan

No se crean estados nuevos. `AnswerStatus` mantiene la semántica de
[ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md).

**Esta tabla es la fuente única. El contrato funcional del piloto remite a ella
y no la reescribe.**

| Situación | Estado | Aviso |
|---|---|---|
| Todos los pasos respondieron y todo hecho tiene atribución; `requires_fresh_inventory = false` o vigencia verificable | `ANSWERED` | — |
| `requires_fresh_inventory = true` + stock obtenido + **vigencia verificable** | `ANSWERED` | — |
| `requires_fresh_inventory = true` + stock obtenido + **vigencia no verificable** | `PARTIAL` | `inventory_freshness_unknown` |
| `requires_fresh_inventory = false` + vigencia no verificable | No degrada por ese motivo | — |
| BOM da N códigos, Materiales devuelve N−1, uno no aparece | `PARTIAL` | `code_not_found_in_source` + redacción del §12 |
| BOM da N códigos y Materiales está caído | `PARTIAL` | `capability_unavailable` |
| Materiales era la única capacidad necesaria y está caído | `ERROR` | — |
| Consulta directa; Materiales responde correctamente y no devuelve el código; **M8 abierto** | `NO_EVIDENCE` | `code_not_found_in_source` |
| Consulta directa; mismo caso con **M8 cerrado garantizando ausencia autoritativa** | `ANSWERED` como hecho negativo atribuido | — |
| Activo sin BOM publicado, o ningún renglón coincide | `NO_EVIDENCE` | — |
| Activo fuera del universo autorizado | Denegación indistinguible (§7.2) | — |

Sobre la fila de consulta directa con M8 abierto: **`PARTIAL` no corresponde**
cuando no existe ninguna otra parte factual de la respuesta que sí se haya
podido resolver. `PARTIAL` significa que hay respuesta con respaldo incompleto;
si no hay ninguna parte respondida, lo que hay es ausencia de evidencia. La
respuesta debe indicar únicamente algo equivalente a «Materiales no devolvió
este código en la fuente consultada», y **nunca** «el material no existe».

Avisos nuevos en `AnswerWarning`: `capability_unavailable`,
`capability_partial_result`, `inventory_freshness_unknown`,
`code_not_found_in_source`.

### 14. Frontera con el LLM

El LLM **no participa** en: seleccionar capacidades, construir planes, decidir
relaciones estructurales, producir o normalizar códigos SAP, ni afirmar
disponibilidad.

Cuando exista en esta ruta recibirá hechos **ya cerrados y ya atribuidos**, y
redactará alrededor de ellos. Los valores factuales se renderizan desde el dato
por plantilla, como ya hace la composición del mensaje en
`elsa.api.v1.assistant`: el modelo escribe la prosa, no los números. Es el mismo
contrato que `GroundedGenerationService` sostiene hoy.

Por tanto el Piloto 0.1 puede liberarse **sin LLM**, con plantilla fija,
declarándolo en `engine` e `is_generated` como ya se hace.

### 15. Observabilidad en tres niveles que no se mezclan

| Nivel | Cuándo | Contenido |
|---|---|---|
| **1. Auditoría de seguridad** | Siempre | Quién, qué alcance, qué acción, resultado. Retención según la política existente |
| **2. Telemetría operativa** | Siempre | Tiempos, estados, conteos, capacidades ejecutadas, errores. **Sin copiar datos de planta** (regla 12) |
| **3. Incident snapshot** | Solo ante «Reportar respuesta» o captura diagnóstica explícita | Contexto autorizado mínimo para reproducir el caso |

#### 15.1 El Incident Snapshot es una fotografía, no un expediente

Se separan dos cosas que suelen confundirse:

- **Incident Snapshot** — fotografía técnica del momento. **Append-only**, con
  almacenamiento **propio**. No se reescribe al investigarlo.
- **Incident Management** — el ciclo recibido → analizado → resuelto. **Fuera
  del Piloto 0.1**, salvo decisión posterior.

No se reutiliza el modelo de aportes: un aporte pasa por revisión y puede
publicarse; un incidente ni se revisa ni se publica. Mezclarlos mezclaría dos
ciclos de vida distintos.

El snapshot **debe sobrevivir a un reinicio**: exige adaptador de PostgreSQL y
migración versionada
([ADR 0001](0001-supabase-cli-unica-autoridad-del-esquema.md)). Su **política de
retención es una decisión explícita pendiente y una condición previa a liberar**
(§17).

Nunca se almacenan, en ningún nivel: JWT, tokens, contraseñas, claves, cabeceras
sensibles, filas fuera de los permisos del usuario, ni volcados indiscriminados
de documentos. **La seguridad prevalece sobre la completitud de la
investigación.**

El texto original de quien reporta se conserva **literal** para poder
investigar. Si en algún momento se implementa detección y redacción de secretos
sobre ese texto, debe preservar una marca de que hubo redacción, **sin
almacenar el secreto**. Ese mecanismo no se diseña en este ADR.

### 16. El identificador de respuesta no se enseña

Toda respuesta del asistente lleva en su **cuerpo** un `response_ref`: la
referencia con la que la interfaz ancla «Reportar respuesta» a esa respuesta
concreta.

- Va en el cuerpo, no en una cabecera: una cabecera obliga al cliente a
  correlacionar y se pierde si la respuesta se guarda o se reenvía. Hoy, además,
  el identificador de petición no está declarado en `expose_headers` del CORS,
  así que un navegador en otro origen no puede leerlo.
- **No se muestra al usuario.** Es un dato técnico que consume la interfaz, no
  parte de la experiencia. Respeta la regla ya vigente de no exponer UUID ni
  versiones internas en la respuesta normal: los identificadores internos viven
  en `AnswerAudit`.
- Es opaco y no adivinable, y solo resuelve para la persona a la que se emitió:
  reportar no puede convertirse en una vía para recuperar la respuesta de otro.

### 17. Puertas previas a liberar y contrato externo pendiente

Dos condiciones no son técnicas y aun así bloquean:

- **Política de retención del Incident Snapshot** — **abierta**. Ningún tester
  entra antes de que exista y esté escrita. No se inventa aquí un número de
  días.
- **M8, semántica de ausencia** — **abierto**. Mientras siga así, rige la
  restricción del §12.

> **Actualizado por [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md).**
> M8 **sigue abierto** y la restricción del §12 **sigue rigiendo sin cambios**,
> pero **deja de ser puerta previa a liberar** el Piloto 0.1: la cobertura
> `UNKNOWN` se acepta bajo controles compensatorios verificables. La política de
> retención del Incident Snapshot (D20) **no cambia** y sigue siendo puerta
> previa a liberar.

El contrato con Materiales que este ADR da por necesario, y que **todavía no
está cerrado**:

| Id | Qué falta | Bloqueante |
|---|---|---|
| M1 | Qué contrato estable de consulta usará ELSA | Sí |
| M2 | Consulta por lote de códigos | **No** |
| M3 | Formato real del código SAP, medido sobre datos reales | Sí |
| M4 | Versión y fecha del inventario activo | Sí |
| M5 | Confirmación de que el JWT del usuario funciona en la llamada de ELSA | Sí |
| M6 | Semántica **y temporalidad** de `disponible`, `comprometido`, `dado_de_baja`, `ubicaciones`, `ambito` y cualquier otro campo devuelto | Sí |
| M7 | Responsable y versionado del contrato | Sí |
| M8 | Semántica de ausencia y cobertura | Sí |

> **Actualizado el 2026-09-19 por
> [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md),
> sobre [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md).** **M3** y
> **M5** se midieron contra Materiales real y quedan **resueltos para V1**;
> dejan de ser bloqueantes. **M1, M2, M4, M6, M7 y M8 conservan su estado**, y M8 sigue
> además gobernado por la nota de ADR 0023 de más arriba. La medición de M3
> **no** demuestra cobertura, freshness de SAP ni un `extracted_at` conocido, y
> **M3-A vale para el dominio observado del Piloto Tampella V1**.

## Consecuencias

- Un plan es enumerable, y por tanto **cada plantilla es un caso de prueba**. Es
  la propiedad que un agente libre no puede ofrecer.
- Añadir una capacidad nueva es añadir una entrada al catálogo y una plantilla;
  **no toca el ejecutor**.
- El endpoint del asistente deja de contener lógica de recuperación: construye
  señales, selecciona plan y lo ejecuta. Las capacidades hoy embebidas en
  `elsa.api.v1.assistant` y `elsa.api.v1.technical` se extraen sin cambiar su
  comportamiento.
- ELSA pasa a depender operativamente de un contrato de Materiales que hoy **no
  está versionado del lado de Materiales**. Se mitiga fijándolo antes del
  adaptador y con pruebas de contrato propias.
- La procedencia por hecho aumenta el tamaño de la respuesta y del registro. Se
  acepta: es el precio de poder responder «¿de dónde salió este número?».
- **ELSA no podrá decir «ese material no existe» durante el Piloto 0.1.** Es una
  limitación deliberada y visible, no un defecto de redacción.

## Alternativas descartadas

- **Agente con herramientas.** Espacio de planes no enumerable, no reproducible,
  no auditable. Incompatible con las reglas 2 y 23.
- **LLM que genera SQL.** Superficie de inyección contra la base de ELSA y
  contra la de Materiales; incompatible con la regla 10.
- **Copiar el inventario de Materiales dentro de ELSA.** Prohibido por la regla
  4; además envejecería sin que nadie lo valide, que es el argumento de ADR 0010
  contra la doble copia del BOM.
- **Reimplementar el buscador de Materiales.** Su motor está ajustado contra
  datos reales durante meses. Una segunda copia divergiría en semanas y nadie
  sabría cuál miente.
- **Convertir el BOM y SAP a texto y buscarlo por embeddings.** Cerrado por
  ADR 0010.
- **Usar recuperación documental para la relación activo → material.** Esa
  relación es una fila, no un parecido.
- **Un `AnswerStatus` nuevo para vigencia desconocida o para ausencia.**
  Multiplica estados sin añadir información; un campo de atribución, un aviso y
  la tabla del §13 lo expresan mejor.
- **Derivar la degradación por vigencia de «se ejecutó la capacidad de
  inventario».** Degradaría respuestas que no afirman nada temporal. Por eso la
  propiedad es `requires_fresh_inventory`, declarada por la plantilla.
- **Reutilizar el modelo de aportes para el Incident Snapshot.** Dos ciclos de
  vida distintos bajo un mismo tipo.
- **Tratar la ausencia en Materiales como inexistencia.** Es exactamente la
  suposición que M8 existe para impedir.

## Ver también

- [ADR 0001](0001-supabase-cli-unica-autoridad-del-esquema.md) — toda estructura
  de base es una migración versionada.
- [ADR 0002](0002-identidad-de-materiales-autorizacion-en-backend.md) y
  [ADR 0006](0006-modelo-minimo-de-autorizacion.md) — identidad en Materiales,
  autorización propia de ELSA.
- [ADR 0003](0003-puertos-y-adaptadores-para-modelos-reemplazables.md) — puertos
  y adaptadores; un puerto sin adaptador real es diseño, no deuda.
- [ADR 0005](0005-verificacion-real-del-jwt-de-materiales.md) — el JWT del
  usuario como credencial contra Materiales.
- [ADR 0010](0010-conocimiento-estructurado-vs-documental.md) — conocimiento
  estructurado y documental son dos cosas distintas. **Este ADR es su ejecución
  en la capa de composición.**
- [ADR 0014](0014-confusabilidad-no-es-autorizacion.md) — el aislamiento vive en
  cada capacidad, no después de componer.
- [ADR 0016](0016-recuperacion-hibrida-del-mvp.md) — recuperación híbrida, sin
  umbral numérico inventado.
- [ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md) — el backend
  decide el estado, no el modelo. `ERROR` no es `NO_EVIDENCE`.
- [Contrato funcional del Piloto 0.1](../piloto-0-1/contrato-funcional.md).
