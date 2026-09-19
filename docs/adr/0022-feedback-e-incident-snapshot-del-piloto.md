# ADR 0022 — Feedback, observabilidad e Incident Snapshot del Piloto 0.1

- Estado: **propuesto**
- Bloque: 5.0, subbloque **5.0.c**
- Conserva sin cambios los estados de respuesta de
  [ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md)
- Materializa el feedback y la observabilidad que
  [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) declaró
  obligatorios antes del primer tester, y **no lo reabre**
- **No reabre** [ADR 0021](0021-contrato-de-inventario-con-materiales.md), el
  [contrato funcional del Piloto 0.1](../piloto-0-1/contrato-funcional.md) ni
  el carácter bloqueante de M8
- Aplica las reglas **2, 9, 11, 14, 21, 23 y 24** de
  [`CLAUDE.md`](../../CLAUDE.md)
- **No cierra D20**, que sigue siendo puerta previa a liberar
- **No aprueba ninguna migración aplicada, ningún endpoint construido y ningún
  cambio de interfaz**

---

## Contexto

### 1. Qué exige el piloto y qué existe

El [contrato funcional del Piloto 0.1](../piloto-0-1/contrato-funcional.md) §10
fija, entre los bloqueantes previos al primer tester: «Reportar respuesta» con
`response_ref` (B14), Incident Snapshot persistente con migración versionada
(B15), telemetría operativa (B13) y manual del observador accesible desde ELSA
(B17).

Auditoría del repositorio. Lo que **existe**:

- **`request_id`** con middleware, `ContextVar`, cabecera de respuesta y log
  JSON estructurado.
- **Log de acceso** que registra método, ruta, estado y duración, y **nunca
  cabeceras, cadenas de consulta ni cuerpos**.
- **Formato de error** con `request_id` en el cuerpo y sin trazas internas.
- **Auditoría de seguridad**: tabla de auditoría administrativa con su entrada
  tipada, que ya incluye `request_id`.
- **Guardia de abuso** por usuario y sesión.
- **`AnswerStatus`, `Sufficiency`, `AnswerWarning`, `Citation` y
  `AnswerAudit`** en el núcleo.
- **Interfaz estática sin proceso de compilación**, servida bajo su propio
  prefijo, con pruebas que verifican que los archivos del repositorio **no**
  son alcanzables.
- **El manual del observador**, con la advertencia sobre ausencia ya escrita.

Lo que **no existe**: `response_ref`, cualquier identificador en la respuesta
del asistente, persistencia de contenido escrito por una persona, telemetría
por etapas, identificador de versión desplegada, acceso al manual desde la
interfaz, y las pruebas de ausencia segura.

### 2. El hecho incómodo que este ADR no puede esquivar

`AnswerStatus`, `Sufficiency`, `AnswerWarning`, `Citation` y `AnswerAudit`
**existen y están probados, pero ningún endpoint los devuelve**. El endpoint
real del asistente resuelve una búsqueda literal sobre el BOM publicado y nunca
invoca al modelo, de modo que su respuesta no contiene ninguno de esos campos.
[`architecture.md`](../architecture.md) lo dice sin rodeos: *«Todavía no hay
endpoint HTTP que responda preguntas con el modelo.»*

> **Consecuencia:** el Incident Snapshot **no puede capturar hoy lo que
> ADR 0020 describe**. Puede capturar lo que el endpoint produce realmente.
> Este ADR lo asume y diseña para crecer; fingir lo contrario produciría
> snapshots que mienten sobre el sistema que los generó.

### 3. El problema

> Un tester encuentra algo raro. En cuatro días la conversación ya no está.
> **La pregunta, la respuesta que vio y el contexto técnico desaparecen con
> ella**, y el reporte se vuelve irreconstruible justo cuando alguien tiene
> tiempo de investigarlo.

Hacen falta cuatro cosas a la vez, y son difíciles de tener juntas:

1. Anclar el reporte a **esa** respuesta concreta.
2. Conservar lo que desaparece, **sin** capturar preventivamente todas las
   conversaciones.
3. No convertir en hechos del sistema datos que aporta el navegador.
4. No perder nunca lo que la persona se molestó en escribir.

### 4. Las tentaciones descartadas

- **Persistir todas las preguntas y respuestas** para poder reportarlas
  después. Es el camino fácil, y es el que convierte una herramienta de
  feedback en un registro permanente de todo lo que pregunta cada ingeniero.
  Además decidiría D20 por la puerta de atrás.
- **Confiar en que el navegador reenvíe la respuesta** al reportar. Registraría
  como hecho del sistema lo que diga el cliente.
- **Usar `request_id` como referencia del reporte.** Parece gratis y no lo es
  (§6).

---

## Decisión

### 5. `response_ref`: la respuesta emitida tiene identidad propia

La respuesta del asistente incorpora un campo **`response_ref`**.

**`response_ref` identifica UNA RESPUESTA EMITIDA por el servidor.**

**No se deriva de** el texto, ni de un hash, ni del usuario, ni del activo, ni
de la fecha.

Dos consecuencias que fijan su semántica y que no deben confundirse:

- **Dos respuestas emitidas distintas tienen dos `response_ref` distintos,
  aunque su texto sea exactamente el mismo.** La identidad es la del acto de
  responder, no la del contenido.
- **Una transformación puramente visual de esa respuesta en el cliente no crea
  una referencia nueva.** Plegar una tabla, cambiar de idioma la interfaz o
  volver a pintar el mismo mensaje sigue siendo la misma respuesta emitida.

| Propiedad | Cómo se cumple |
|---|---|
| **Opaco** | Derivado de material aleatorio. No codifica usuario, fecha, activo ni contenido |
| **Generado por el servidor** | En la capa HTTP, junto a la respuesta. Nunca por el cliente |
| **Sin datos sensibles** | No hay nada que extraer de él |
| **Único por respuesta emitida** | Cada emisión produce el suyo |
| **No visible en la interfaz** | Vive en el estado del cliente. **Nunca se pinta** |

Viaja en **el cuerpo de la respuesta**, no en una cabecera. Es un cambio
aditivo que no toca la configuración CORS.

### 6. Por qué `request_id` no puede ser `response_ref`

Dos razones independientes, cualquiera de ellas suficiente:

1. **El cliente puede fijarlo.** El middleware acepta un identificador de
   petición entrante si cumple el patrón declarado. Un identificador bajo
   control del cliente no puede ser la llave de un registro de incidentes.
2. **El navegador no puede leerlo en una respuesta correcta.** La
   configuración CORS declara esa cabecera entre las que el navegador puede
   **enviar**, y no declara ninguna cabecera **expuesta**, así que el frontend
   no puede leerla. Solo la recibe en el cuerpo de los errores. Habilitar la
   exposición de cabeceras sería ampliar la superficie CORS por comodidad.

> **`request_id` se conserva dentro del snapshot** como campo de correlación
> con los logs y con la auditoría. **No es la referencia del reporte.** Son dos
> identificadores con dos dueños y dos propósitos.

### 7. Búfer acotado en memoria

El servidor mantiene un **mapa de las respuestas recientes**, indexado por
`response_ref` y asociado a la cuenta que las recibió.

Sus únicas propiedades fijadas por este ADR:

- **En memoria.** Muere con el proceso, y eso es intencionado.
- **Acotado por cantidad** de entradas.
- **Acotado por antigüedad** de las entradas.
- **Configurable**, para poder ajustarlo sin cambiar código.

**No se fijan aquí la cantidad máxima, el tiempo de vida, el tamaño en memoria
ni ningún otro número.** Los valores por defecto se deciden durante la
implementación, **después de medir**. Fijarlos ahora sería inventar cifras sin
evidencia de uso.

**No se escribe nada en disco mientras nadie reporte.** Esto es lo que permite
cumplir a la vez «no capturar todas las conversaciones» y «no creerse lo que
diga el cliente».

**No se diseñan aquí tokens firmados ni infraestructura adicional.** Si el
búfer resultara insuficiente en la práctica, esa será una decisión posterior
con evidencia de uso, no una anticipación.

### 8. Fallback parcial: el feedback humano nunca se pierde

Tres caminos, y solo tres:

| Situación | Resultado |
|---|---|
| **`response_ref` en el búfer y pertenece a la cuenta autenticada** | Se crea el snapshot **con lo disponible**. `capture_completeness = complete`, `association_verified = true` |
| **`response_ref` ya no está disponible** (búfer expirado o proceso reiniciado) | **El reporte NO se rechaza.** `capture_completeness = partial`, `association_verified = false` |
| **`response_ref` disponible pero pertenece a otra cuenta** | **404 indistinguible.** No se revela que la referencia existe. No se crea ninguna fila |

#### 8.1 Qué se preserva en el caso parcial

Todo lo que el **servidor** puede afirmar por sí mismo:

- el **texto del tester**, literal;
- el `response_ref` **declarado**, marcado como declarado y no verificado;
- la **cuenta autenticada** que reporta, que el servidor conoce;
- el instante del **reporte**;
- el `release_id` disponible en el servidor;
- la `snapshot_schema_version`;
- `capture_completeness = partial`;
- `association_verified = false`.

#### 8.2 Qué NO se acepta del cliente como hecho del sistema

**Nunca**, en ningún caso: la pregunta, la respuesta, el `request_id`, el
activo, el dominio, las evidencias, el plan, las latencias, los errores, el
modelo ni el runtime.

**Si el servidor no puede demostrarlo, el campo vale nulo o `not_available`.**

**No se reconstruye la respuesta. No se reconsulta ninguna fuente.**

> La regla que gobierna el caso parcial: **se conserva el feedback humano, y no
> se convierten en hechos del sistema los datos que aporta el cliente.** El
> texto del tester es lo único que se toma por bueno, porque lo escribió una
> persona y es exactamente lo que se quiere conservar.

### 9. Persistencia: una entidad, y solo al reportar

**`response_ref` no requiere una tabla persistente por cada respuesta.** Mapeo
reciente en memoria, materialización persistente únicamente al reportar,
degradación parcial si el mapeo ya no existe.

Se crea **una sola entidad persistente**, con su migración versionada y su
rollback ([ADR 0001](0001-supabase-cli-unica-autoridad-del-esquema.md)):

```text
elsa.incident_snapshots
```

Campos conceptuales mínimos:

| Campo | Papel |
|---|---|
| identificador interno | Clave propia del reporte |
| **`snapshot_schema_version`** | Qué estructura produjo este snapshot (§14) |
| `response_ref` | Referencia reportada. **Sin restricción de unicidad** (§9.1) |
| `request_id` | Correlación técnica. **Nulo** cuando no pueda demostrarse |
| `reporter_account_id` | Cuenta ELSA que reporta |
| `occurred_at` | Instante de la respuesta. **Nulo** cuando no pueda demostrarse |
| `reported_at` | Instante del reporte. Siempre presente |
| **`capture_completeness`** | `complete` / `partial` — **disponibilidad técnica** de la captura |
| **`association_verified`** | **Si la asociación referencia ↔ ejecución quedó demostrada** |
| `reporter_text` | **Literal. Nunca se resume, reescribe ni clasifica** |
| `release_id` | Versión desplegada (§15) |
| `payload` estructurado | El detalle técnico, con claves estables y nulos explícitos |

**Los nombres físicos finales de columna no se fijan aquí** si las convenciones
reales del repositorio sugieren otra forma al escribir la migración.

#### 9.1 `response_ref` no lleva restricción de unicidad

**`response_ref` identifica una respuesta emitida; un Incident Snapshot
identifica un reporte.** Son cosas distintas, y la relación es
**uno a muchos**: una misma respuesta puede reportarse más de una vez.

Dos motivos, y el segundo es de seguridad:

1. **No se impone en la base una restricción de experiencia de usuario.** Que
   la interfaz ofrezca un solo envío es una decisión de interfaz, reversible;
   una restricción de unicidad en el esquema es irreversible en la práctica.
2. **En el caso parcial la referencia la aporta el cliente y no está
   verificada.** Con una restricción de unicidad, un navegador podría insertar
   una referencia arbitraria y **bloquear el reporte legítimo futuro** de esa
   misma respuesta.

En el Piloto 0.1 la interfaz puede ofrecer inicialmente un solo envío, marcar
«Reportado» tras enviarlo y evitar el doble clic o el reintento accidental.
**Eso no debe convertirse en una restricción irreversible del esquema.**

#### 9.2 Los dos campos de estado no son redundantes

`capture_completeness` dice **cuánto se pudo capturar**; `association_verified`
dice **si se pudo demostrar** que la referencia corresponde a una ejecución
real. Hoy van correlacionados, porque el único mecanismo de verificación es el
búfer. Se mantienen separados porque un mecanismo futuro podría demostrar la
asociación sin capturar el detalle, y entonces fundirlos habría sido un error
irreversible.

#### 9.3 No se reutiliza el almacén de aportes

Los ciclos de vida son incompatibles: un aporte se revisa, se aprueba y puede
publicarse; un incidente ni se revisa ni se publica. Mezclarlos obligaría a que
uno de los dos mienta sobre el otro.

### 10. Inmutabilidad

El Incident Snapshot es **append-only**.

- **Sin `UPDATE`.** Ninguna política lo permite, tampoco al administrador. Es
  la misma garantía estructural que aplica el inventario de Materiales:
  corregir exige un registro nuevo, no editar el viejo.
- **Sin `DELETE` ordinario.**
- **Sin columna de estado.** `recibido`, `analizado` y `resuelto` **no
  existen**: pertenecen a Incident Management, que queda **fuera del
  Piloto 0.1**.

> La futura política de retención (§20) podrá definir **eliminación
> controlada**. Eliminar conforme a una política escrita no convierte el
> registro en editable; editarlo durante una investigación, sí.

### 11. Permisos

Denegación por defecto.

| Acción | Usuario normal | Administrador |
|---|---|---|
| **Crear** un reporte sobre su propia interacción | **Sí** | Sí |
| **Enumerar** reportes | **No** | Sí, según autorización administrativa |
| **Leer** un snapshot | **No**, ni siquiera los propios | Sí, según autorización administrativa |
| **Modificar** | **No** | **No** |
| **Borrar** | **No** | **No** (solo la futura política de retención) |

Un usuario normal no necesita listar sus reportes durante el piloto, y no
ofrecerlo elimina superficie.

**El snapshot nunca amplía lo que el usuario podía ver.** Se construye a partir
de la respuesta **ya entregada**, que pasó por la autorización en su momento.
**Al reportar no se consulta ninguna fuente nueva.**

Un `response_ref` ajeno produce **404**, no 403: un 403 confirmaría que la
referencia existe.

### 12. Tres sistemas distintos, formalizados

| | **Auditoría de seguridad** | **Telemetría operativa** | **Incident Snapshot** |
|---|---|---|---|
| **Responde a** | Quién hizo qué | Cómo se comportó el sistema | Qué ocurrió en una interacción **que el tester decidió reportar** |
| **Se escribe** | Siempre | Siempre | **Solo al reportar** |
| **Contenido de usuario** | **Nunca** | **Nunca** | **Sí, y es su razón de ser** |
| **Retención** | Larga | Corta | **D20, abierta** |
| **Mutabilidad** | Append-only | Rotación | **Inmutable** |
| **Quién lee** | Administración | Operación | Administración |

Tres reglas que hacen operativa la separación:

1. **La telemetría nunca lleva la pregunta ni la respuesta.** Solo dimensiones
   y medidas.
2. **La auditoría nunca lleva contenido de conocimiento.** Solo actor, sujeto,
   operación y alcance.
3. **El snapshot no duplica lo que la auditoría ya registró.** Lo correlaciona
   por `request_id`.

**No se mezclan sus retenciones, sus permisos ni sus contenidos.**

### 13. Minimización y datos sensibles

**Nunca se almacenan deliberadamente:** JWT, tokens de refresco, contraseñas,
credenciales de servicio, claves privadas, cabeceras de autorización, cadenas
de conexión, secretos, ni información fuera del alcance autorizado del usuario.

Qué se preserva y por qué, distinguiendo lo que desaparece de lo que permanece:

| Se preserva **íntegro** | Motivo |
|---|---|
| La pregunta | Desaparece con la conversación |
| La respuesta que vio el tester | Desaparece con la conversación |
| El texto original del tester | **Es el reporte.** Literal, sin resumir ni reescribir |

| Se preserva **por referencia** | Motivo |
|---|---|
| Fragmentos documentales | `Citation` ya está diseñada así: documento, versión, apartado, página. **Nunca el texto completo del fragmento** |
| Renglones del BOM | Identificador de renglón y versión |
| Datos de inventario de Materiales | Regla 4: ELSA no duplica su inventario, **tampoco dentro de un incidente** |
| Versiones de fuente | Etiqueta de versión, no su contenido |

**Ningún volcado completo.**

#### 13.1 Lista blanca en el logging, y su orden obligatorio

La infraestructura de logging debe aceptar **únicamente un conjunto declarado
de campos estructurados**. Hoy el formateador copia todos los campos extra de
cada registro: ninguna llamada actual pasa datos sensibles, pero nada lo impide
estructuralmente.

La lista blanca debe hacer imposible que por accidente lleguen al log una
cabecera de autorización, un JWT, la pregunta, la respuesta, el texto del
tester, un cuerpo completo o un secreto.

**Orden obligatorio, sin excepciones:**

1. lista blanca del logging;
2. pruebas que demuestren que un campo extra no autorizado **se descarta**;
3. **solo después**, añadir métricas.

**El catálogo completo de métricas no se fija en este ADR.**

### 14. `snapshot_schema_version`

Cada snapshot declara **la versión del contrato con el que fue escrito**.

**No es lo mismo que `release_id`, y confundirlos haría inútiles a ambos:**

| | Responde a |
|---|---|
| `snapshot_schema_version` | ¿Con qué **estructura** se escribió este registro? |
| `release_id` | ¿Qué **versión desplegada de ELSA** produjo la respuesta reportada? |

Dos snapshots de la misma versión desplegada pueden tener estructuras distintas
si el esquema cambia entre ellos; y la misma estructura convive con muchas
versiones desplegadas. Son ejes independientes.

Permite leer snapshots antiguos sin reescribirlos y sin adivinar qué
significaba cada clave cuando se escribieron.

### 15. `release_id`

**`ELSA_RELEASE` es el contrato interno**: una variable de configuración leída
**una sola vez al arrancar** y guardada en la configuración.

- Si no está definida, el valor es **`unknown`**, y `unknown` se registra como
  tal. **No se inventa.**
- Se expone también en el estado de salud, donde ya existe un modelo de
  respuesta al que añadirlo.
- **Nunca se ejecuta `git` por petición.** Ni por petición ni en caliente.

> **Cuál es la variable real de la plataforma de despliegue que alimentará
> `ELSA_RELEASE` queda PENDIENTE DE VERIFICACIÓN.** Este ADR **no afirma** el
> nombre de ninguna variable concreta por parecer probable. Se comprueba en el
> panel antes de implementarla.

### 16. Campos que hoy no existen

El snapshot **describe la ELSA que realmente produjo esa respuesta**.

Hoy el endpoint del asistente **no produce**: `AnswerStatus`, `Sufficiency`,
avisos, plan de capacidades, capacidades ejecutadas, procedencia por hecho,
modelo, runtime ni espacio vectorial.

Esos campos se emiten como **nulos o `not_available` explícitos**, con sus
claves presentes. **No se infieren, no se estiman y no se omiten.** Un campo
omitido se lee como «no aplicaba»; un nulo explícito se lee como «esto no
existía cuando se escribió», que es la verdad.

De forma análoga, las latencias por etapa distinguen **`not_executed` de
`0 ms`**: un cero significa «se ejecutó y tardó menos de un milisegundo», un
`not_executed` significa «no se ejecutó». Confundirlos haría creer que existe
un motor instantáneo donde no hay motor.

### 17. Crecimiento futuro con el plan de capacidades

Cuando existan el plan de ejecución y las capacidades de
[ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md), sus datos
**rellenan claves ya reservadas** en el detalle estructurado del snapshot.

- **Sin migración de esquema.**
- **Sin reescribir snapshots históricos.** Los antiguos siguen diciendo la
  verdad sobre el sistema que los produjo.
- `snapshot_schema_version` distingue una generación de otra.

### 18. Manual del observador accesible

El contenido ya existe y **no requiere cambios**.
[El manual](../piloto-0-1/manual-del-observador.md) contiene la advertencia
sobre ausencia —«no encontrado» no es «no existe»— y la descripción de
«Reportar respuesta», el campo libre, la ausencia de categorías, que el texto
se guarda literal, y la advertencia de no escribir contraseñas ni tokens.

**Lo único que falta es hacerlo permanentemente accesible desde la interfaz.**

Mecanismo decidido:

- **Fuente única**: el archivo del manual sigue siendo el documento canónico.
- **Un endpoint de ruta fija y literal** que sirve **exclusivamente** ese
  archivo. Sin parámetro de ruta, sin concatenación, sin patrón: imposible de
  convertir en un lector de archivos arbitrario.
- **No se sirve el árbol de documentación completo.**
- **No se copia el manual dentro de la interfaz.**
- **No se añade ninguna dependencia de render Markdown.** El proyecto no tiene
  ninguna en tiempo de ejecución, y añadirla para esto sería desproporcionado.
- **Render seguro por construcción**: la interfaz construye nodos del DOM
  asignando **texto**, mediante el ayudante que ya usa toda la aplicación,
  sobre un subconjunto controlado de construcciones del documento. **Queda
  prohibido el uso de `innerHTML` en este camino**, incluida la propiedad
  equivalente que el ayudante admite y que hoy no usa ningún archivo de la
  interfaz. Así no existe vector de inyección.
- Acceso visible y permanente del tipo «Guía del piloto», disponible desde
  cualquier pantalla.

### 19. Pruebas de ausencia segura

Requisito de este subbloque. **Hoy no existe ninguna.**

| Id | Debe demostrar |
|---|---|
| **A6** | Capacidad externa indisponible en consulta compuesta → **`PARTIAL` + `capability_unavailable`**, nunca `NO_EVIDENCE` |
| **A6b** | `OK` + `NOT_RETURNED` con `authoritative = false` → **`NO_EVIDENCE` + `code_not_found_in_source`**, y **el texto emitido no afirma inexistencia** |
| **A6c** | El mismo caso con garantía de ausencia autoritativa → `ANSWERED` como hecho negativo. **Desactivada y documentada como tal mientras M8 siga abierto** |
| **A18** | **Ninguna ruta** puede transformar una ausencia no autoritativa en «no existe», «no está creado», «no figura en SAP» ni equivalentes |
| **A19** | Prueba **adicional derivada de [ADR 0021](0021-contrato-de-inventario-con-materiales.md)**: `NO_ACTIVE_INVENTORY` con Materiales como única capacidad necesaria → **`ERROR` + `inventory_unavailable`**, **nunca** `NO_EVIDENCE` |

**El estado y el texto se verifican por separado.** Comprobar solo el
`AnswerStatus` no basta: un `NO_EVIDENCE` acompañado de un texto que diga «ese
material no existe» cumpliría el estado y rompería la garantía.

**Estas pruebas usan el fake contractual de la fachada. No requieren M3 ni M5**,
y por tanto no dependen del subbloque 5.0.b.

### 20. D20 sigue abierta

**Este ADR no fija ninguna cantidad de días.** La retención del Incident
Snapshot continúa siendo **decisión abierta y puerta previa a liberar** (D20).

La política futura deberá resolver al menos:

1. Retención del **texto del tester**.
2. Retención de la **pregunta y la respuesta** preservadas.
3. Relación con la **caducidad de las conversaciones a los cuatro días**, que
   es la razón por la que el snapshot existe.
4. Retención de las **referencias a evidencias**.
5. **Qué ocurre si una versión de fuente se purga antes que el snapshot** y sus
   referencias quedan colgando.
6. **Borrado controlado** conforme a la política que se apruebe, sin convertir
   el snapshot en un registro editable (§10).

### 21. M8 permanece bloqueante

**Este ADR no cambia el estado normativo de M8.** Los documentos ya fusionados
—[ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md),
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) y el
[contrato funcional del Piloto 0.1](../piloto-0-1/contrato-funcional.md)—
siguen declarándolo **bloqueante**, y **este ADR no los modifica ni los
reabre**.

Se registran únicamente tres hechos:

1. **La advertencia necesaria en el manual del observador YA EXISTE**,
   redactada y verificada.
2. **A6, A6b y A18 están PENDIENTES.**
3. **A19** es una prueba adicional derivada de ADR 0021.

Esas pruebas son **controles compensatorios necesarios** si más adelante se
propusiera que M8 deje de bloquear el piloto.

**Cualquier cambio futuro del carácter bloqueante de M8 requiere otro ADR**
(regla 25).

---

## Consecuencias

### 22. Riesgos

| # | Riesgo | Mitigación |
|---|---|---|
| **R1** | **El búfer pierde el detalle técnico al reiniciar el proceso.** En un plan que duerme el servicio por inactividad, no es hipotético | Degradación a `partial` (§8). **El texto del tester nunca se pierde.** Se acepta conscientemente: perder detalle técnico es tolerable; perder lo que la persona escribió, no |
| **R2** | **El snapshot nace sin los campos de ADR 0020** porque el camino HTTP no los produce | Claves reservadas con nulos explícitos (§16) y `snapshot_schema_version` (§14). Crece sin migración |
| **R3** | **El logging podría capturar por accidente datos sensibles** al añadir telemetría | Lista blanca y sus pruebas **antes** de la primera métrica (§13.1) |
| **R4** | **Servir el manual publica un archivo del repositorio** | Ruta fija y literal, sin parámetro. Las pruebas de recorrido de rutas existentes se mantienen intactas |
| **R5** | **Un reporte en modo parcial contiene una referencia no verificada del cliente** | `association_verified = false` lo declara, y §8.2 impide que cualquier dato técnico del cliente entre como hecho |
| **R6** | **El alcance se desborda hacia gestión de incidentes** | El esquema **no tiene columna de estado**. La estructura lo impide, no solo la intención |
| **R7** | **El snapshot podría ampliar lo visible** si se reconsultaran fuentes al reportar | Se construye solo desde la respuesta ya entregada. **Prohibido reconsultar** (§11) |

### 23. Alternativas rechazadas

| Alternativa | Por qué se rechaza |
|---|---|
| **Persistir toda pregunta y respuesta** para permitir el feedback | Convierte la herramienta en un registro permanente de todo lo que pregunta cada ingeniero, y pre-decide D20 sin discutirla |
| **Que el cliente reenvíe la respuesta al reportar** | Registraría como hecho del sistema lo que afirme el navegador |
| **`request_id` como referencia del reporte** | El cliente puede fijarlo, y el navegador no puede leerlo en un éxito (§6) |
| **Exponer el identificador de petición como cabecera legible** | Ampliar la superficie CORS por comodidad, para obtener un identificador que además no sirve |
| **Restricción de unicidad sobre `response_ref`** | Impone en la base una decisión de interfaz y abre una vía de denegación en el caso parcial (§9.1) |
| **Servir el árbol de documentación como estático** | Publicaría toda la documentación y contradice una prueba existente |
| **Copiar el manual dentro de la interfaz** | Crearía un segundo manual que divergiría del canónico |
| **Generar el manual en tiempo de compilación** | El proyecto **no tiene proceso de compilación**, y añadirlo rompe el criterio de aceptación permanente (regla 24) |
| **Añadir una dependencia de render Markdown** | Desproporcionado frente a construir nodos asignando texto |
| **Reutilizar el almacén de aportes para los reportes** | Ciclos de vida incompatibles (§9.3) |
| **Estados `recibido` / `analizado` / `resuelto`** | Es Incident Management, fuera del Piloto 0.1 |
| **Tokens firmados para la referencia** | Infraestructura adicional sin evidencia de que el búfer sea insuficiente |

### 24. Decisiones diferidas

| # | Decisión | Se decide |
|---|---|---|
| 1 | **Política de retención** del Incident Snapshot | **D20**, puerta previa a liberar |
| 2 | **Variable real de la plataforma** que alimenta `ELSA_RELEASE` | Verificación en el panel, **antes** de implementar (§15) |
| 3 | **Valores por defecto del búfer**: cantidad, antigüedad y tamaño | Durante la implementación, **después de medir** (§7) |
| 4 | **Catálogo de métricas de telemetría** | Tras la lista blanca y sus pruebas (§13.1) |
| 5 | Mecanismo reforzado de asociación (tokens firmados) | Solo con evidencia de que el búfer es insuficiente |
| 6 | Que un usuario normal pueda listar sus propios reportes | Después del piloto, si hace falta |
| 7 | Incident Management y sus estados | Fuera del Piloto 0.1 |
| 8 | Nombres físicos finales de columna | Al escribir la migración, según las convenciones del repositorio |
| 9 | **Carácter bloqueante de M8** | **ADR posterior** (§21) |
