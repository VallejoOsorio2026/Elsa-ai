-- ============================================================
-- Reversión del Bloque 2 — modelo de conocimiento técnico
--
-- ESTE ARCHIVO NO ES UNA MIGRACIÓN. Vive fuera de
-- `supabase/migrations/` a propósito: la CLI de Supabase no debe
-- aplicarlo nunca por su cuenta. Se ejecuta a mano, con respaldo previo
-- y por decisión explícita.
--
--   supabase db dump --linked --schema elsa -f respaldo-elsa.sql
--   psql "<cadena de conexión>" -v ON_ERROR_STOP=1 -f este_archivo.sql
--
-- DESTRUYE DATOS: elimina todo el conocimiento técnico cargado.
-- Procedimiento completo en docs/migration-runbook-bloque-2.md §7.
-- ============================================================

begin;

-- ------------------------------------------------------------
-- 1. Tablas del Bloque 2.
-- `cascade` retira de paso los índices, disparadores y claves foráneas
-- que dependen de ellas. El orden no importa por eso mismo, pero se
-- listan de hoja a raíz para que el volcado sea legible.
-- ------------------------------------------------------------
drop table if exists elsa.reviews                   cascade;
drop table if exists elsa.reviewer_grants           cascade;
drop table if exists elsa.reconciliation_items      cascade;
drop table if exists elsa.reconciliation_runs       cascade;
drop table if exists elsa.sap_snapshot_items        cascade;
drop table if exists elsa.sap_bom_snapshots         cascade;
drop table if exists elsa.option_tables             cascade;
drop table if exists elsa.sod_criteria              cascade;
drop table if exists elsa.failure_modes             cascade;
drop table if exists elsa.drawing_images            cascade;
drop table if exists elsa.drawings                  cascade;
drop table if exists elsa.engineering_bom_items     cascade;
drop table if exists elsa.engineering_bom_versions  cascade;
drop table if exists elsa.imports                   cascade;
drop table if exists elsa.derived_artifacts         cascade;
drop table if exists elsa.source_artifacts          cascade;
drop table if exists elsa.component_identifiers     cascade;
drop table if exists elsa.components                cascade;
drop table if exists elsa.subsystems                cascade;
drop table if exists elsa.technical_assets          cascade;

-- ------------------------------------------------------------
-- 2. Función propia del Bloque 2.
-- `elsa.touch_updated_at()` NO se elimina: pertenece al Bloque 1 y
-- sigue en uso por `elsa.accounts`.
-- ------------------------------------------------------------
drop function if exists elsa.forbid_review_mutation();

-- ------------------------------------------------------------
-- 3. Catálogo de auditoría.
--
-- ATENCIÓN: si `elsa.admin_audit_log` ya contiene operaciones del
-- Bloque 2, este paso FALLA y aborta la transacción entera. Es lo
-- correcto: la auditoría es append-only y no se edita para acomodar
-- una reversión.
--
-- Si eso ocurre, la decisión consciente es una de estas dos:
--   (a) dejar el catálogo ampliado y comentar este bloque — es inocuo,
--       una restricción más permisiva no rompe nada del Bloque 1;
--   (b) abortar la reversión.
-- Nunca borrar filas de auditoría.
-- ------------------------------------------------------------
alter table elsa.admin_audit_log
  drop constraint if exists ck_audit_operation;

alter table elsa.admin_audit_log
  add constraint ck_audit_operation check (operation in (
    'bootstrap_admin',
    'create_account',
    'grant_permission',
    'revoke_permission',
    'enable_user',
    'disable_user',
    'promote_admin',
    'demote_admin'
  ));

commit;
