-- ============================================================
-- Reversión del almacenamiento vectorial (Bloque 4.2.b)
--
-- ESTE ARCHIVO NO ES UNA MIGRACIÓN. Vive fuera de
-- `supabase/migrations/` a propósito: la CLI de Supabase no debe
-- aplicarlo nunca por su cuenta. Se ejecuta a mano, con respaldo previo
-- y por decisión explícita.
--
--   psql "<cadena de conexión>" -v ON_ERROR_STOP=1 -f este_archivo.sql
--
-- DESTRUYE DATOS: elimina todos los vectores generados, el registro de
-- modelos y el historial de corridas de embedding. **No toca el modelo
-- documental**: documentos, versiones, secciones y chunks quedan intactos,
-- y con ellos todo lo que hace falta para volver a generar los vectores.
--
-- No retira la extensión `vector`: puede estar en uso por otro esquema, y
-- retirarla es una decisión del administrador de la base, no de este bloque.
-- ============================================================

drop view if exists elsa.chunk_embedding_retrieval;

drop table if exists elsa.document_chunk_embeddings;
drop table if exists elsa.embedding_runs;

drop trigger if exists trg_embedding_models_immutable on elsa.embedding_models;
drop function if exists elsa.reject_embedding_model_mutation();

drop table if exists elsa.embedding_models;

-- La clave candidata que 4.2.b añadió a `document_chunks` para poder atar el
-- embedding a la versión de su chunk. Se retira al final, cuando ya no queda
-- ninguna clave foránea que dependa de ella.
alter table elsa.document_chunks
  drop constraint if exists uq_document_chunk_id_version;
