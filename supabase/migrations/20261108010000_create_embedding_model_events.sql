-- ============================================================
-- Historial auditable del modelo de embeddings activo (R1.C.1, ADR 0039)
--
-- Hasta aquí, cambiar el modelo activo solo dejaba rastro en el log de la
-- aplicación: `activated_at` se vacía al desactivar, así que la base no podía
-- decir quién activó qué ni cuándo. Y no existía forma de volver a «ningún
-- modelo activo»: la única vuelta atrás era activar **otro** modelo, que en la
-- primera activación no existe, y retirar es irreversible.
--
-- Esta tabla registra cada transición del modelo activo —activar, desactivar,
-- retirar— y el cierre manual de una corrida abandonada, en la **misma
-- transacción** que cambia el estado. Si la fila de auditoría no puede
-- escribirse, el cambio de estado tampoco ocurre.
--
-- Es estrictamente append-only, con el mismo disparador que `reviews` y
-- `document_version_events`. No sustituye a `admin_audit_log`, que registra
-- la administración de cuentas y permisos; esta es la historia del espacio
-- vectorial que sirve la recuperación.
--
-- Solo añade objetos nuevos. No toca datos, ni las tablas de 20260913010000,
-- ni sus restricciones. Es idempotente.
-- ============================================================

create table if not exists elsa.embedding_model_events (
  id                uuid        primary key default gen_random_uuid(),
  seq               bigint      generated always as identity unique,
  event             text        not null,
  -- El modelo afectado: el que se activa, se desactiva o se retira, o el de
  -- la corrida que se cierra.
  model_id          uuid        not null references elsa.embedding_models (id) on delete restrict,
  -- En una activación, el que estaba activo antes, si había alguno.
  previous_model_id uuid        references elsa.embedding_models (id) on delete restrict,
  run_id            uuid        references elsa.embedding_runs (id) on delete restrict,
  actor             uuid        not null,
  reason            text,
  request_id        text,
  occurred_at       timestamptz not null default now(),
  constraint ck_embedding_event check (event in (
    'activated',
    'deactivated',
    'retired',
    'run_reconciled'
  )),
  constraint ck_embedding_event_shape check (
    (event = 'activated' and run_id is null
       and (previous_model_id is null or previous_model_id <> model_id))
    or (event in ('deactivated', 'retired') and previous_model_id is null and run_id is null)
    or (event = 'run_reconciled' and previous_model_id is null and run_id is not null)
  ),
  -- Desactivar deshace una decisión de otra persona, y cerrar a mano una
  -- corrida afirma que el proceso ya no corre: las dos tienen que decir por
  -- qué, y lo garantiza la base.
  constraint ck_embedding_event_reason check (
    event not in ('deactivated', 'run_reconciled')
    or (reason is not null and btrim(reason) <> '')
  )
);

comment on table elsa.embedding_model_events is
  'Historial append-only del modelo de embeddings activo y del cierre manual de corridas. Ninguna fila se modifica ni se borra.';

create index if not exists ix_embedding_model_events_by_model
  on elsa.embedding_model_events (model_id, seq);

drop trigger if exists trg_embedding_model_events_append_only on elsa.embedding_model_events;
create trigger trg_embedding_model_events_append_only
  before update or delete on elsa.embedding_model_events
  for each row execute function elsa.forbid_review_mutation();

-- ============================================================
-- DEFENSA EN PROFUNDIDAD
-- RLS activo y sin políticas, como el resto del esquema (ADR 0002). Cada
-- migración que añade objetos vuelve a cerrarlos para los roles de Supabase.
-- ============================================================
do $$
declare
  role_name text;
begin
  alter table elsa.embedding_model_events enable row level security;

  foreach role_name in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = role_name) then
      execute format('revoke all on schema elsa from %I', role_name);
      execute format('revoke all on all tables in schema elsa from %I', role_name);
      execute format('revoke all on all functions in schema elsa from %I', role_name);
      execute format(
        'alter default privileges in schema elsa revoke all on tables from %I', role_name);
    end if;
  end loop;
end;
$$;
