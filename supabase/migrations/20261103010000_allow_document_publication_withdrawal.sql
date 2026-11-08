-- ============================================================
-- Retirada auditable de una publicación documental (R1.B, ADR 0038)
--
-- Hasta aquí, publicar una versión era irreversible: el historial solo
-- admitía `created`, `approved`, `rejected`, `published` y `superseded`, y
-- ninguno de ellos describe «esta versión deja de estar vigente sin que otra
-- la reemplace». Reutilizar `rejected` o `superseded` habría cambiado su
-- significado y, además, ambos son terminales: la versión no podría volver a
-- publicarse.
--
-- Retirar devuelve la versión de `published` a `approved` (no hay estado
-- nuevo) y deja en el historial una fila `withdrawn` con actor y motivo. La
-- publicación original sigue registrada: su fila `published` no se toca,
-- porque el historial es append-only. Volver a publicar es el `publish` de
-- siempre.
--
-- Esta migración solo amplía dos restricciones de
-- `elsa.document_version_events`. No toca datos, estados, índices, vistas,
-- RLS ni privilegios. Es idempotente: cada restricción se retira y se vuelve
-- a crear con su definición final.
-- ============================================================

alter table elsa.document_version_events
  drop constraint if exists ck_document_event,
  add constraint ck_document_event check (event in (
    'created',
    'approved',
    'rejected',
    'published',
    'superseded',
    'withdrawn'
  ));

-- Retirar una publicación, igual que rechazar, cierra algo que otra persona
-- dio por bueno: tiene que decir por qué, y lo garantiza la base.
alter table elsa.document_version_events
  drop constraint if exists ck_document_event_reason,
  add constraint ck_document_event_reason check (
    event not in ('rejected', 'withdrawn')
    or (reason is not null and btrim(reason) <> '')
  );

comment on constraint ck_document_event_reason on elsa.document_version_events is
  'Rechazar o retirar una publicacion exige un motivo no vacio.';
