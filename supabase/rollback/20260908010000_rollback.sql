-- ============================================================
-- Reversión del Bloque 4 — modelo de conocimiento documental
--
-- ESTE ARCHIVO NO ES UNA MIGRACIÓN. Vive fuera de
-- `supabase/migrations/` a propósito: la CLI de Supabase no debe
-- aplicarlo nunca por su cuenta. Se ejecuta a mano, con respaldo previo
-- y por decisión explícita.
--
--   supabase db dump --linked --schema elsa -f respaldo-elsa.sql
--   psql "<cadena de conexión>" -v ON_ERROR_STOP=1 -f este_archivo.sql
--
-- DESTRUYE DATOS: elimina todos los documentos, versiones, secciones y
-- chunks cargados. Los archivos originales siguen en el almacenamiento
-- privado, pero pierden todo su metadato y su procedencia.
--
-- NO revierte el Bloque 2: el conocimiento estructurado (BOM, SAP, AMEF,
-- criterios S/O/D) es independiente y no se toca.
-- ============================================================

begin;

-- ------------------------------------------------------------
-- 1. La vista, antes que las tablas de las que depende.
-- ------------------------------------------------------------
drop view if exists elsa.document_chunk_provenance;

-- ------------------------------------------------------------
-- 2. Tablas del Bloque 4, de hoja a raíz.
-- `cascade` retira de paso los índices, disparadores y claves foráneas.
-- ------------------------------------------------------------
drop table if exists elsa.document_version_events  cascade;
drop table if exists elsa.document_chunks          cascade;
drop table if exists elsa.document_sections        cascade;
drop table if exists elsa.document_versions        cascade;
drop table if exists elsa.document_ingestion_runs  cascade;
drop table if exists elsa.documents                cascade;

-- ------------------------------------------------------------
-- 3. Los originales de documentos quedan sin dueño.
-- Se borra su metadato porque ya no hay nada que los referencie, y
-- conservar filas huérfanas haría creer que ese contenido sigue ingerido.
-- Los bytes siguen en el almacenamiento privado: borrarlos es una decisión
-- aparte y no la toma una migración.
-- ------------------------------------------------------------
delete from elsa.source_artifacts
 where kind in ('document_text', 'document_markdown', 'document_pdf');

-- ------------------------------------------------------------
-- 4. Restricciones ampliadas por este bloque, devueltas a su estado previo.
-- ------------------------------------------------------------
alter table elsa.technical_assets
  drop constraint if exists uq_technical_asset_id_domain;

alter table elsa.source_artifacts
  drop constraint if exists ck_source_artifact_kind;

alter table elsa.source_artifacts
  add constraint ck_source_artifact_kind check (kind in (
    'engineering_bom_xlsx',
    'sap_bom_htm'
  ));

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
    'demote_admin',
    'reviewer_granted',
    'reviewer_revoked',
    'source_uploaded',
    'import_completed',
    'import_failed',
    'validation_approved',
    'validation_rejected',
    'validation_reverted',
    'bom_published',
    'reconciliation_created'
  ));

commit;
