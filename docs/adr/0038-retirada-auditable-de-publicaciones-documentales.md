# ADR 0038 — Retirada auditable de publicaciones documentales

- Estado: **propuesto** (2026-11-03). Queda aceptado cuando Juan haga el merge del PR que lo introduce
- Bloque: **R1.B**, previo a G-P
- **Decide**: cómo se deshace una publicación documental —el «Ctrl+Z» de `publish`— sin borrar nada ni
  cambiar el significado de los estados que fija el [ADR 0012](0012-ciclo-de-vida-documental-propio.md)
- **No decide**: aplicar la migración en Supabase TEST ni ejecutar G-P. Cada una exige su propia
  autorización (regla 15)
- **Amplía** el ADR 0012: añade una transición y un evento, y no reabre nada de lo que aquel decidió
- Implementación: `supabase/migrations/20261103010000_allow_document_publication_withdrawal.sql`,
  `withdraw_version` en `DocumentRepositoryPort` y el comando `withdraw` de `elsa.tools.documents_admin`

## Contexto

El responsable de PAPELSA fijó una condición permanente: toda modificación que pueda afectar el
funcionamiento necesita antes un mecanismo de reversión **probado**. Una copia de seguridad no basta.

Con el ciclo del ADR 0012, publicar era irreversible:

- `validate_transition` impide cualquier cambio de estado desde `published` o `superseded`.
- `publish_version` solo avanza: publica la versión nueva y pasa a `superseded` la anterior.
- El historial solo admite `created`, `approved`, `rejected`, `published` y `superseded`, y es
  append-only.

Ninguno de esos eventos describe «esta versión deja de estar vigente sin que otra la reemplace».

## Decisión

### Una operación propia: `withdraw`

`withdraw` lleva la versión de `published` a `approved`, vacía `published_at` y `published_by`, y añade
al historial un evento **`withdrawn`** con actor, motivo y `request_id`, todo en una sola transacción con
el documento y la versión bloqueados. Es la misma disciplina de `publish_version`.

- **Solo** se retira una versión `published`. Una pendiente, aprobada, rechazada o reemplazada se niega
  con `NotPublishableError`, sin escribir nada. Por eso una retirada repetida también se niega.
- El **motivo es obligatorio**, y lo garantiza la base (`ck_document_event_reason`), no solo el código.
- **No hay estado nuevo.** Una versión retirada es una versión aprobada que hoy no está vigente. Así
  `published`, `rejected` y `superseded` conservan su significado, y el índice
  `uq_published_document_version` sigue garantizando una sola versión vigente por documento.
- **Volver a publicar** es el `publish` de siempre: la versión está `approved`. Los chunks y los
  vectores no cambian, así que no se recalcula nada.

### La recuperación no cambia

Los tres canales —exacto, léxico y semántico— y `list_published_chunks` ya filtran por
`version_state = 'published'`. La retirada saca la versión de la recuperación por ese mismo filtro, sin
tocar ninguna consulta ni ocultar nada por otra vía.

### El historial cuenta las dos cosas

La fila `published` original no se toca: el historial es append-only. Tras una retirada, la versión
lleva `created → approved → published → withdrawn`; si vuelve a publicarse, se añade otro `published`.
Quién publicó, cuándo y quién lo retiró y por qué quedan en el historial. `published_at` y
`published_by` describen solo la publicación **vigente**.

### La migración y su reversión

La migración amplía dos restricciones de `elsa.document_version_events`: el evento `withdrawn` y su
motivo obligatorio. No toca datos, estados, índices, vistas, RLS ni privilegios.

El rollback (`supabase/rollback/20261103010000_rollback.sql`) devuelve las restricciones a las de
20260908010000, **y se niega si ya existe algún evento `withdrawn`**. Esas filas serían inválidas con el
esquema anterior, y borrarlas para poder revertir sería reescribir la auditoría. Una vez usada la
retirada, la vuelta atrás se hace con operaciones compensatorias (`publish` de la versión retirada), no
eliminando historial.

## Consecuencias

- **Retirar no restaura la versión que esta reemplazó.** `superseded` sigue siendo terminal, como fija el
  ADR 0012. Si se retira la v2 de un documento cuya v1 quedó `superseded`, el documento se queda sin
  versión vigente. Para G-P no importa: las tres son primeras publicaciones.
- **Retirar no deshace la aprobación.** La versión queda `approved`, no `pending_validation`: la decisión
  de quien la aprobó sigue registrada. El Ctrl+Z devuelve la **visibilidad** al estado anterior, no
  cada campo de la fila.
- El ciclo documental sigue sin exponerse por HTTP: `withdraw` existe solo en la CLI de operación.
- Hasta que la migración se aplica, la base rechaza el evento `withdrawn` y la transacción se revierte
  entera. El código nuevo sobre el esquema viejo falla sin dejar nada a medias.

## Alternativas descartadas

**Reutilizar `superseded`.** Diría que otra versión la reemplazó, y no la reemplazó ninguna. Además es
terminal: la versión no podría volver a publicarse, y reingerir el mismo archivo se deduplica por su
hash. Descartada.

**Reutilizar `rejected` desde `published`.** No necesitaba migración, pero «rechazada» significa que no
pasó la validación, y también es terminal. G-P no podría repetirse. Descartada.

**Un estado nuevo `withdrawn`.** Habría que tocar la restricción de estados, la vista de procedencia y
permitir `withdrawn → published`. Más superficie para el mismo efecto observable. Descartada.

**Retirar permisos sobre el ámbito.** Cambia las reglas de autorización, no actúa por documento y no
queda en el historial del documento. Descartada.

**Restaurar un respaldo de Supabase.** Afectaría a registros ajenos al corpus. Descartada.
