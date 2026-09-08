# ADR 0012 — El ciclo de vida documental tiene su propio historial

- Estado: aceptado
- Bloque: 4.1

## Contexto

El Bloque 2 ya tiene un ciclo de publicación con revisión
(`elsa.reviews`, ADR 0008 y ADR 0009): validaciones append-only, herencia de
validación entre versiones y publicación atómica. El Bloque 4 necesita el
mismo patrón —ingestar, validar, comparar, activar— para las versiones
documentales.

La opción evidente era reutilizar `elsa.reviews`. No se puede sin romperla:

- `reviews.asset_id` es **obligatorio** y apunta a `technical_assets`. Una
  versión documental puede no tener activo: hay documentación que aplica a un
  dominio entero.
- `reviews.subject_version_id` apunta a `engineering_bom_versions`. Haría
  falta una segunda columna, y una restricción que garantizara que solo una
  de las dos está rellena.
- Hacer nulo `asset_id` debilitaría una restricción que hoy sostiene toda la
  historia de validación del Bloque 2.

## Decisión

### Una tabla propia para el ciclo de vida: `document_version_events`

Registra las transiciones de una versión documental: `created`, `approved`,
`rejected`, `published`, `superseded`, con actor, motivo, `request_id` y
momento. Es estrictamente append-only, protegida por el mismo disparador que
`reviews`: una tabla que puede reescribirse no es trazabilidad.

Rechazar exige motivo, y lo garantiza la base. Una decisión que cierra el
trabajo de alguien tiene que decir por qué.

### Los estados y las garantías son los mismos del Bloque 2

`pending_validation` → `approved` → `published`, con `rejected` como salida y
`superseded` al ser reemplazada. Un índice parcial único hace **imposible**
—no improbable— tener dos versiones publicadas del mismo documento.

**Una versión nueva nunca reemplaza sola a la publicada.** Publicar es una
operación aparte, la toma una persona y solo admite una versión `approved`.
Aprobar no es publicar.

**Una ingesta fallida nunca destruye la última versión válida.** El fallo
cierra la ejecución de ingesta con su tipo y no toca ninguna versión.

### La ejecución de ingesta también es tabla propia

`document_ingestion_runs`, separada de `elsa.imports`, por la misma razón:
una importación del Bloque 2 exige un activo técnico y estas no.

### La validación por chunk queda para más adelante

Este bloque registra el estado de la **versión**, no una validación por
chunk. La comparación entre versiones ya clasifica cada chunk (`new`,
`modified`, `unchanged`, `retired`) y deja lista la herencia, pero quién
valida qué chunk y con qué criterio es una decisión de producto que todavía
no se ha tomado. Construir el mecanismo antes de saberlo sería construir por
anticipación.

## Consecuencias

- Hay dos historiales de validación en el esquema. Se parecen y no son lo
  mismo: uno valida un renglón técnico, el otro el estado de un documento.
- Un Centro de Control futuro tendrá que leer los dos para presentar «qué
  está pendiente de revisión».
- El Bloque 2 no se toca, y su restricción `asset_id not null` sigue en pie.

## Alternativas descartadas

**Ampliar `elsa.reviews`.** Exigiría hacer nulo `asset_id`, añadir una
segunda columna de versión y una restricción de exclusividad entre las dos,
debilitando una tabla que ya sostiene historia real. Descartada.

**Un modelo genérico de «sujeto validable» con tipo y `subject_id` sin clave
foránea.** Perdería la integridad referencial en todos los casos para
ganarla en ninguno. Descartada.

**Estado de publicación denormalizado en cada chunk.** Publicar cambia el
estado de todos los chunks de una versión: habría dos fuentes de verdad para
un valor que se mueve. La procedencia se expone como **vista**
(`document_chunk_provenance`) en su lugar. Descartada.
