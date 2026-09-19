# Contrato funcional del Piloto 0.1

Qué hace y qué no hace la primera versión de ELSA que verá un tester de planta.

Las reglas innegociables viven en [`CLAUDE.md`](../../CLAUDE.md). El diseño de
capacidades y planes está cerrado en
[ADR 0020](../adr/0020-capacidades-componibles-y-planes-de-ejecucion.md); este
documento no lo reescribe, lo aplica.

> **Estado del documento.** Contrato acordado. La implementación **no ha
> empezado**: todo lo que aquí se describe está autorizado a construirse, no
> construido.

## 1. Objetivo

Poner en manos de un tester de planta respuestas **reales y trazables** sobre
Tampella que crucen el BOM aprobado con la disponibilidad de Materiales, y un
camino para reportar cuando algo salga mal que permita investigarlo días
después.

## 2. Dentro del alcance

### 2.1 Capacidades

Las cuatro del catálogo cerrado de ADR 0020 §2: `resolve_asset`,
`get_published_bom`, `search_bom_components`, `get_material_availability`.

### 2.2 Planes

Cinco plantillas, ninguna más:

| Plantilla | Caso | Pasos | `requires_fresh_inventory` |
|---|---|---|---|
| `material_lookup` | Material conocido → Materiales | `get_material_availability` | según la pregunta |
| `asset_components` | Activo → BOM | `resolve_asset` → `get_published_bom` → `search_bom_components` | `false` |
| `asset_components_with_availability` | Activo → BOM → Materiales | la anterior, más extracción de códigos y `get_material_availability` | `true` |
| `asset_membership` | ¿Este código pertenece al activo? | `resolve_asset` → `get_published_bom` → localizar el código | `false` |
| `clarify` | Ambigüedad objetiva | ninguna capacidad; devuelve la pregunta de aclaración | — |

«Fuente incompleta → respuesta parcial» no es una plantilla: es el
comportamiento del ejecutor ante un paso marcado `degrade`.

`requires_fresh_inventory` es una propiedad determinista de la plantilla y de
los campos que la composición va a afirmar (ADR 0020 §11.1). En
`material_lookup` depende de la pregunta: «¿tenemos stock de X?» es `true`;
«¿cuál es la descripción de X?» es `false` mientras la respuesta no afirme
campos temporales.

### 2.3 Entregables verificables

1. Tipos de capacidad y de plan en `src/elsa/core/`, sin entrada ni salida.
2. Selector determinista con léxico de intención versionado y probado.
3. Ejecutor de planes con autorización por paso y traza.
4. Composición con procedencia por hecho.
5. `MaterialsPort` ampliado, adaptador real y fake determinista.
   `MaterialsIdentityPort` **intacto**.
6. Endpoint del asistente ejecutando planes, con `response_ref` en el cuerpo.
7. «Reportar respuesta» con campo libre inmediato.
8. Incident snapshot persistente, con almacenamiento propio y su migración
   versionada.
9. Telemetría en los tres niveles separados de ADR 0020 §15.
10. [Manual del observador](manual-del-observador.md) accesible desde la
    interfaz.

## 3. Fuera del alcance

Lista explícita. Sin ella el bloque se desborda.

- **Estructura técnica de SAP (IH06) para ingenieros.** El acceso actual, tras
  permisos de revisor, **no se toca**. Es una decisión posterior separada.
- **Histórico de intervenciones (IW13).** No existe fuente en el repositorio.
  Una pregunta histórica debe responder que no puede, no aproximar.
- **`search_documents` como capacidad componible.** El camino documental existe
  (`HybridRetrievalService` → `GroundedGenerationService`) pero sin endpoint
  HTTP; exponerlo es otro bloque.
- **LLM en la ruta del asistente.** El piloto responde con plantilla fija y lo
  declara.
- **ONNX, INT8, recuperación semántica y la topología definitiva de modelos.**
  Hilo paralelo, sin dependencia con este piloto.
- **Consulta por lote de códigos en Materiales (M2).** Deseable, no bloqueante;
  se decide con la evidencia que produzca el piloto.
- **Incident Management** (recibido → analizado → resuelto).
- **Detección y redacción de secretos en el texto de quien reporta.**
- **Concurrencia, reintentos, caché y límites por capacidad.** No se inventan
  sin medición.
- **Campo estructurado de clase o tipo en el BOM.** Mejora futura.
- **Interfaz del reporte más allá del campo libre**: categorías, adjuntos,
  triaje.
- **Métricas numéricas de éxito.** No hay evidencia todavía para fijarlas.

## 4. Autorización

Según ADR 0020 §7. Dos puntos que el piloto debe respetar literalmente:

- **Materiales directo no exige alcance sobre activos** (§7.1). Una cuenta ELSA
  activa con cero permisos puede ejecutar `material_lookup`. Eso no abre el BOM
  ni ningún activo.
- **`resolve_asset` no divulga activos** (§7.2). La resolución opera solo dentro
  del universo autorizado. Un usuario sin permiso sobre un equipo no debe poder
  inferir su existencia por mensajes, sugerencias, aclaraciones, listas de
  candidatos ni tiempos de respuesta.

## 5. Estados y comportamiento parcial

**La tabla normativa es la de ADR 0020 §13.** Este documento no la duplica ni la
reinterpreta; solo ilustra cómo se lee.

Redacción esperada de una respuesta compuesta con una ausencia y con vigencia
conocida:

> «Identifiqué 5 elementos del BOM publicado de Tampella cuya descripción
> coincide con "rodamiento". Obtuve disponibilidad para 4, según el inventario
> de Materiales en su versión del {fecha}. Del quinto, Materiales no devolvió
> ese código en la fuente consultada; eso no significa que el material no
> exista.»

Las tres afirmaciones tienen fuente distinta y la respuesta lo refleja. Ninguna
diferencia se oculta, y ninguna ausencia se convierte en inexistencia.

## 6. Semántica de la respuesta

Prohibido: «Estos son los rodamientos de Tampella.»

Obligatorio: «Encontré N elementos del BOM publicado de Tampella cuya
descripción coincide con "rodamiento"», con el campo que produjo la coincidencia
—`component_name` o `technical_description`— trazable en cada renglón.

La clasificación del Piloto 0.1 es **léxica sobre el texto del BOM**, no
estructural. La respuesta dice lo que hizo: buscó una palabra en una
descripción. No afirma que la pieza *sea* un rodamiento.

El patrón ya existe en la composición de mensaje de `elsa.api.v1.assistant` y
solo hay que generalizarlo.

## 7. Aclaraciones

**Ejecutar** cuando se cumplan las tres: un solo activo autorizado es
identificable (o el usuario solo tiene uno), hay al menos un término buscable o
un identificador, y **una sola** plantilla encaja.

**Aclarar** solo ante una señal objetiva:

| Señal | Pregunta |
|---|---|
| Dos o más activos **autorizados** y ninguno nombrado | «¿Sobre qué equipo?», con **solo los autorizados** |
| Identificador solo, sin verbo de intención ni activo | «¿El material en inventario, o el componente instalado en {activo autorizado}?» |
| Dos plantillas mutuamente excluyentes encajan | Ofrecer las dos rutas |
| Ningún término buscable | Pedir un término concreto |

**Nunca aclarar** cuando hay un solo candidato, cuando la respuesta parcial ya
es útil, o cuando ejecutar es barato y resuelve la duda por sí mismo.

**Prohibido**: umbrales de confianza de un modelo, y nombrar en una aclaración
cualquier activo fuera del universo autorizado.

## 8. Reportar respuesta

- Asociado a una respuesta concreta mediante el `response_ref` del cuerpo
  (ADR 0020 §16). **El usuario nunca lo ve.**
- Al activarlo se abre **inmediatamente un campo libre**: «Cuéntanos con tus
  palabras qué ocurrió o qué esperabas que ocurriera.»
- **Ninguna categoría obligatoria antes del texto.** Clasificar puede venir
  después, o no venir.
- El texto se conserva **literal**, sin normalizar ni resumir.

## 9. Incident snapshot

Fotografía técnica, append-only, con almacenamiento propio (ADR 0020 §15.1).

Conserva, con minimización: identificador de petición, identificador de plan,
`response_ref`, momento, pregunta que originó **esa** respuesta, respuesta que
el tester vio, `AnswerStatus`, `Sufficiency`, avisos, activo y dominio,
capacidades ejecutadas, resultado de cada paso, códigos utilizados, procedencia,
referencias de evidencia, versiones y snapshots relevantes (BOM e inventario),
tiempos por etapa, versión o commit de ELSA, runtime y modelo si participaron,
error técnico si lo hubo, y el **texto libre original del tester**.

No conserva nunca: JWT, tokens, contraseñas, claves, cabeceras sensibles, filas
fuera de los permisos del usuario, ni volcados indiscriminados de documentos.
**La seguridad prevalece sobre la completitud de la investigación.**

**Retención: decisión abierta y puerta previa a liberar** (§10, B16).

## 10. Bloqueantes antes del primer tester

| Id | Bloqueante | Tipo |
|---|---|---|
| B1 | Datos reales de Tampella validados | Dato |
| B2 | BOM real publicado | Dato |
| B3 | **M3** — formato real del código SAP, medido según el protocolo del §11 | Medición |
| B4 | **M1** — contrato estable de consulta de Materiales | Contrato |
| B5 | **M4** — versión y fecha del inventario activo | Contrato |
| B6 | **M5** — JWT del usuario confirmado en la llamada real | Contrato |
| B7 | **M6** — semántica **y temporalidad** de los campos devueltos | Contrato |
| B8 | **M7** — responsable y versionado del contrato | Contrato |
| ~~B9~~ | ~~**M8** — semántica de ausencia y cobertura~~ — **retirado** por [ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md). M8 sigue **abierto**, pero **deja de ser bloqueante**. Lo sustituyen B9a–B9c | — |
| B9a | `requires_complete_inventory_coverage` implementada como propiedad determinista de la plantilla, **no decidida por un LLM** | Código |
| B9b | Avisos `coverage_unknown` y `coverage_incomplete` disponibles y emitidos según [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §13, sin confundirse entre sí | Código |
| B9c | Pruebas **A20**, **A20b** y **A21** activas en integración continua | Código |
| B10 | Las cuatro capacidades, cinco plantillas, selector y ejecutor | Código |
| B11 | Autorización por capacidad, minimización y no divulgación en planes | Código |
| B12 | Composición con procedencia por hecho | Código |
| B13 | Telemetría operativa (nivel 2) | Código |
| B14 | «Reportar respuesta» y `response_ref` en el cuerpo, no visible | Código |
| B15 | Incident snapshot persistente, almacenamiento propio y migración versionada | Código y esquema |
| B16 | **Política de retención del snapshot, escrita** | **Puerta previa a liberar** |
| B17 | Manual del observador accesible desde ELSA | Documento |

**No son bloqueantes, y no deben convertirse en tales:** consulta por lote (M2),
concurrencia, caché, reintentos, LLM, recuperación semántica, ONNX e INT8, IH06
para ingenieros, IW13, campo estructurado de clase, Incident Management,
redacción de secretos y métricas numéricas de éxito.

## 11. Protocolo de la medición M3

La medición se hace **sobre el BOM real de Tampella**, antes de implementar la
normalización definitiva, la unión BOM ↔ Materiales y el adaptador de
inventario.

Muestra:

- mínimo **30 códigos SAP distintos**;
- distribuidos entre **todas** las hojas o secciones reales que contengan
  códigos;
- si existen menos de 30 códigos distintos, se usan todos;
- debe incluir **cada patrón de formato que aparezca realmente**.

**No se predefinen categorías** del tipo «con ceros», «sin ceros» o
«alfanumérico». Primero se observan los datos; las categorías salen de la
observación.

Para cada código se compara:

1. representación exacta en el BOM;
2. valor recibido o almacenado;
3. representación esperada o devuelta por Materiales;
4. resultado de la búsqueda exacta;
5. cualquier transformación que haya hecho falta.

La primera medición se hace **sin aplicar normalización nueva**, para no ocultar
el problema que se está midiendo.

El resultado debe permitir decidir después la forma canónica de
`canonical_sap_code` y la representación de frontera del adaptador de
Materiales.

## 12. Criterios de aceptación

Formato «acción → resultado observable». **Sin métricas numéricas de éxito.**

| Id | Acción | Resultado esperado |
|---|---|---|
| A1 | Clon limpio, siguiendo solo el README → suite de pruebas | Verde, sin datos reales ni credenciales (regla 24) |
| A2 | Cada consulta del catálogo → selector de plan | La plantilla esperada, en una tabla de prueba |
| A3 | «Busca el material X» con X presente en el BOM | Elige `material_lookup`, **no** el BOM |
| A4 | Plan compuesto contra el fake de Materiales | Cada campo de la respuesta idéntico al devuelto por la capacidad |
| A5 | Fake de Materiales caído, BOM con resultados | `PARTIAL` + `capability_unavailable`; nunca `ERROR` ni `NO_EVIDENCE` |
| A6 | Compuesta: BOM da 5, el fake devuelve 4, uno ausente | `PARTIAL` + `code_not_found_in_source`. El texto dice «no devolvió ese código en la fuente consultada» y **no** dice «no existe» |
| A6b | Directa: el fake responde y no devuelve el código, con M8 abierto | `NO_EVIDENCE` + `code_not_found_in_source`. Prueba explícita de que el texto **no** afirma inexistencia |
| A6c | Directa: mismo caso simulando garantía de ausencia autoritativa | `ANSWERED` como hecho negativo atribuido. **Mientras M8 siga abierto esta prueba queda desactivada y documentada como tal** |
| A7 | Solo Materiales era necesario y está caído | `ERROR` |
| A8 | `requires_fresh_inventory = true` y vigencia verificable | `ANSWERED`, sin aviso de vigencia |
| A8b | `requires_fresh_inventory = true` y vigencia no verificable | `PARTIAL` + `inventory_freshness_unknown` |
| A8c | `requires_fresh_inventory = false` y vigencia no verificable | **No** se degrada por ese motivo |
| A8d | Inspección del selector | `requires_fresh_inventory` se deriva de la plantilla y de los campos afirmados, **no** de que se haya ejecutado la capacidad de inventario |
| A9 | Usuario sin permiso sobre el activo | Denegación indistinguible de activo inexistente: mismo código, mismo mensaje |
| A9b | Usuario sin permiso menciona el nombre del activo en texto libre | La aclaración o el error **no** lo nombran, **no** lo sugieren y **no** lo ofrecen como candidato |
| A9c | Selector con usuario de cero permisos | La resolución de activos nunca invoca el catálogo global; se verifica sobre el doble del repositorio |
| A10 | Inspección de la llamada a Materiales | Lleva códigos y JWT; **no** lleva activo, pregunta, términos, alcances ni identificador de petición |
| A11 | Cuenta ELSA activa con **cero** permisos | `material_lookup` se ejecuta; cualquier plantilla que toque el BOM se deniega |
| A12 | Toda respuesta del asistente | Trae `response_ref` en el cuerpo |
| A12b | Inspección de la respuesta renderizada | El `response_ref` no aparece en la experiencia del usuario; ningún UUID interno se muestra |
| A13 | «Reportar respuesta» → escribir texto → enviar | Snapshot creado y recuperable **tras reiniciar el proceso** |
| A14 | Inspección del snapshot | Ningún JWT, token, clave ni cabecera sensible; ninguna fila fuera de permisos |
| A14b | Intentar recuperar un snapshot con el `response_ref` de otra persona | Denegado |
| A15 | Dado un identificador de plan | Se reconstruye pregunta, plan, pasos, entradas, resultados, errores, procedencia y tiempos |
| A16 | Manual del observador | Alcanzable desde cualquier pantalla, sin salir de ELSA, y contiene la advertencia sobre ausencia |
| A17 | Medición real con el BOM de Tampella | Número de llamadas y latencias registradas, como evidencia para decidir M2 |
| A18 | Revisión de todo texto que la plantilla pueda generar | Ninguna cadena afirma la inexistencia de un material a partir de una ausencia en Materiales |
| A20 | Afirmación **acotable** con `requires_complete_inventory_coverage = true` y cobertura `UNKNOWN` | `PARTIAL` + `coverage_unknown`. **Nunca** `coverage_incomplete`, **nunca** `ANSWERED` |
| A20b | Lo mismo con `requires_complete_inventory_coverage = false` y solo campos estables afirmados | **No** se degrada por cobertura |
| A21 | Revisión de todo texto que la plantilla pueda generar | **Ninguna cadena alcanzable** afirma algo que solo sería cierto con cobertura completa: «no hay en ningún almacén», «estos son todos los materiales que tenemos» o equivalentes. Estado y texto se verifican **por separado** |

## 13. Riesgos

| Id | Riesgo | Mitigación concreta |
|---|---|---|
| R1 | **Formato del código SAP.** Si el BOM y Materiales difieren en su representación, el caso central falla en silencio y cae a búsqueda por parecido | Medición M3 previa (§11), sin asumir categorías. Bloquea normalización, unión y adaptador; **no** bloquea tipos, contratos, documentación ni observabilidad independiente del formato |
| R2 | **Ausencia interpretada como inexistencia** | Restricción de redacción de ADR 0020 §12; pruebas A6, A6b, A18 y A19, **activas en CI**; ausencia autoritativa rechazada en código; advertencia en el manual §5. M8 **ya no** figura entre las mitigaciones: [ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md) lo retiró como puerta al existir las otras |
| R3 | **Contrato de Materiales no versionado del lado de Materiales** | M1 y M7 por escrito; prueba de contrato propia que falle si la forma cambia |
| R4 | **Cobertura incompleta del inventario.** La exportación puede no cubrir todas las sedes | No es nuestro fallo, sí nuestro problema: el manual lo advierte y el mensaje de ausencia nunca se lee como «no existe». Formalizado en [ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md): la cobertura `UNKNOWN` se acepta, y **ninguna respuesta puede depender de una cobertura que nadie demostró** (A20, A21) |
| R5 | **Muchas llamadas en consultas compuestas** | Aceptado: la primera versión hace consultas individuales. Se mide (B13) y se decide con evidencia. Sin concurrencia inventada |
| R6 | **Léxico de intención que no cubre cómo habla la planta** | La salida segura es `clarify`, no adivinar. Los reportes de los testers son el instrumento para ampliarlo |
| R7 | **Divulgación de activos por aclaración o por mensaje** | Resolución restringida al universo autorizado por construcción; pruebas A9, A9b y A9c, extendiendo la prueba de no divulgación existente |
| R8 | **Secretos en el texto libre del tester** | Se conserva literal para investigar, pero no se almacenan credenciales deliberadamente. Si más adelante se implementa redacción, debe dejar marca sin guardar el secreto |
| R9 | **Snapshot que acumula datos de planta** | Minimización enumerada en §9, pruebas A14 y A14b, y retención decidida **antes** de liberar |
| R10 | **Desbordamiento hacia IH06 o hacia el camino documental** | La lista del §3 es cerrada. Ambos tienen código tentadoramente cerca y quedan fuera por decisión, no por olvido |

## 14. Decisiones que siguen abiertas

| Qué | Estado |
|---|---|
| **Retención del Incident Snapshot** | **Abierta. Puerta previa a liberar**: ningún tester entra antes de que exista una política escrita. No se fija aquí un número de días |
| **M8** — semántica de ausencia y cobertura | **Abierta y NO bloqueante** desde [ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md). Mientras siga abierta, ELSA **no puede afirmar la inexistencia de un material** y la cobertura se declara `UNKNOWN`. **M8 no está cerrado**: su criterio de cierre sigue siendo [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §8.3, sin cumplir |
| **M1–M7** | Sus estados se mantienen en sus artefactos y decisiones correspondientes. **Este apartado no los redefine** |
| M2 — consulta por lote | Abierta y **no** bloqueante |
| Muestra concreta de la medición M3 | Pendiente: qué hojas y quién la ejecuta, dentro del protocolo del §11 |
| Mecanismo por el que la interfaz presenta el manual | Pendiente de inspeccionar el frontend (ver el manual, §«Sobre este documento») |

## 15. Cierre del bloque

Este bloque no se considera cerrado sin su documento de cierre, según
[el estándar de cierre de bloques](../project/BLOCK_CLOSURE_STANDARD.md).
