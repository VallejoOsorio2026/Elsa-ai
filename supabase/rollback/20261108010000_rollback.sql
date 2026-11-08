-- ============================================================
-- Reversión del historial del modelo de embeddings activo (ADR 0039)
--
-- ESTE ARCHIVO NO ES UNA MIGRACIÓN. Vive fuera de
-- `supabase/migrations/` a propósito: la CLI de Supabase no debe
-- aplicarlo nunca por su cuenta. Se ejecuta a mano, con respaldo previo
-- y por decisión explícita.
--
--   psql "<cadena de conexión>" -v ON_ERROR_STOP=1 -f este_archivo.sql
--
-- NO DESTRUYE DATOS: solo retira la tabla, y **se niega** si tiene alguna
-- fila. Una fila es la auditoría de una activación, una desactivación o un
-- cierre de corrida que ya ocurrió; borrarla para poder revertir sería
-- reescribir la historia. Una vez usada, la vuelta atrás funcional es una
-- operación compensatoria (`deactivate`, `activate`), nunca un borrado.
--
-- Orden: revertir esta migración **antes** que 20260913010000, porque sus
-- claves foráneas apuntan a `embedding_models` y `embedding_runs`.
-- ============================================================

begin;

do $$
begin
  if to_regclass('elsa.embedding_model_events') is not null
     and exists (select 1 from elsa.embedding_model_events) then
    raise exception
      'rollback refused: embedding model events exist and the history cannot be rewritten';
  end if;
end;
$$;

-- El disparador append-only se va con la tabla.
drop table if exists elsa.embedding_model_events;

commit;
