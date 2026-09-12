-- ============================================================
-- Reversión de la integridad relacional de la procedencia documental
--
-- ESTE ARCHIVO NO ES UNA MIGRACIÓN. Vive fuera de
-- `supabase/migrations/` a propósito: la CLI de Supabase no debe
-- aplicarlo nunca por su cuenta. Se ejecuta a mano, con respaldo previo
-- y por decisión explícita.
--
--   psql "<cadena de conexión>" -v ON_ERROR_STOP=1 -f este_archivo.sql
--
-- NO DESTRUYE DATOS: no borra ni modifica ninguna fila. Solo retira las dos
-- restricciones que añadió 20260912010000, devolviendo el esquema al estado
-- en que una versión podía citar la corrida de otro documento.
--
-- El orden importa: primero la clave foránea que depende de la unicidad,
-- después la unicidad.
-- ============================================================

alter table elsa.document_versions
  drop constraint if exists fk_document_version_run_identity;

alter table elsa.document_ingestion_runs
  drop constraint if exists uq_document_run_identity;
