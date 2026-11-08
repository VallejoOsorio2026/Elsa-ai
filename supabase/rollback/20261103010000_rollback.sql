-- ============================================================
-- Reversión de la retirada auditable de publicaciones (ADR 0038)
--
-- ESTE ARCHIVO NO ES UNA MIGRACIÓN. Vive fuera de
-- `supabase/migrations/` a propósito: la CLI de Supabase no debe
-- aplicarlo nunca por su cuenta. Se ejecuta a mano, con respaldo previo
-- y por decisión explícita.
--
--   psql "<cadena de conexión>" -v ON_ERROR_STOP=1 -f este_archivo.sql
--
-- NO DESTRUYE DATOS: devuelve las dos restricciones de
-- `elsa.document_version_events` a su definición de 20260908010000.
--
-- SE NIEGA si ya existe algún evento `withdrawn`. Con el esquema anterior
-- esas filas serían inválidas, y el historial es append-only: borrarlas para
-- poder revertir sería reescribir la auditoría. Una vez usada la retirada, la
-- vuelta atrás funcional es una operación compensatoria (`publish` de la
-- versión retirada), nunca la eliminación de historial.
-- ============================================================

begin;

do $$
begin
  if exists (select 1 from elsa.document_version_events where event = 'withdrawn') then
    raise exception
      'rollback refused: withdrawn events exist and the history cannot be rewritten';
  end if;
end;
$$;

alter table elsa.document_version_events
  drop constraint if exists ck_document_event,
  add constraint ck_document_event check (event in (
    'created',
    'approved',
    'rejected',
    'published',
    'superseded'
  ));

alter table elsa.document_version_events
  drop constraint if exists ck_document_event_reason,
  add constraint ck_document_event_reason
    check (event <> 'rejected' or (reason is not null and btrim(reason) <> ''));

comment on constraint ck_document_event_reason on elsa.document_version_events is null;

commit;
