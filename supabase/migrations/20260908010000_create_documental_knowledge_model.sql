-- ============================================================
-- Modelo de conocimiento documental de ELSA (Bloque 4.0 / 4.1)
--
-- Documento → versión → ejecución de ingesta → secciones → chunks.
--
-- Tres ideas gobiernan el diseño, y las tres son deliberadamente las mismas
-- del Bloque 2, porque los problemas son los mismos:
--
-- 1. **La identidad del documento no es su archivo.** Un documento es «el
--    manual de lubricación del equipo X»; sus versiones son las ediciones de
--    ese manual. Si la identidad fuera el archivo, cada edición nueva
--    rompería toda referencia anterior y la historia se perdería.
--
-- 2. **No todo se chunkea.** El BOM, los datos de SAP, el AMEF, los códigos,
--    las cantidades, las relaciones y los criterios S/O/D viven
--    estructurados en el modelo del Bloque 2 y se consultan directamente.
--    Aquí solo entra conocimiento narrativo: manuales, procedimientos,
--    instructivos y documentación técnica. Convertir una tabla de cantidades
--    en texto para trocearla destruiría la única forma fiable de
--    consultarla. Ver `docs/knowledge-architecture.md`.
--
-- 3. **Nada se sobrescribe.** Las versiones y las ejecuciones de ingesta se
--    acumulan. Publicar una versión nueva no borra la anterior: la marca
--    como reemplazada.
--
-- Lo que este bloque **no** trae, y no es un olvido: no hay columna de
-- embeddings, ni índice vectorial, ni pgvector. El modelo de embeddings se
-- decide en el Bloque 4.2 y su dimensión determina el tipo de la columna;
-- declararla ahora obligaría a migrar la tabla entera al elegirlo.
--
-- Los bytes de los archivos originales NO viven aquí: viven en el puerto de
-- almacenamiento privado. Esta base guarda solo su metadato y su hash.
-- ============================================================

-- ============================================================
-- El catálogo de originales del Bloque 2 acepta ahora documentos.
-- Se sustituye la restricción en vez de crear un segundo catálogo: un
-- archivo original es un archivo original, y duplicar la tabla duplicaría
-- también la garantía de unicidad por hash que la hace útil.
-- ============================================================
alter table elsa.source_artifacts
  drop constraint if exists ck_source_artifact_kind;

alter table elsa.source_artifacts
  add constraint ck_source_artifact_kind check (kind in (
    -- Bloque 2
    'engineering_bom_xlsx',
    'sap_bom_htm',
    -- Bloque 4
    'document_text',
    'document_markdown',
    'document_pdf'
  ));

-- Un activo se referencia junto con su dominio, de modo que la base misma
-- impide que un documento diga pertenecer a `mantenimiento` y cuelgue de un
-- activo de otro dominio. Sin esta unicidad no se puede declarar esa clave
-- foránea compuesta.
--
-- Se anade solo si falta, en vez de borrarla y volver a crearla: en cuanto
-- exista un documento, su clave foranea depende de este indice y el borrado
-- fallaria. Una migracion que solo se puede aplicar sobre una base vacia no
-- es reproducible.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'elsa.technical_assets'::regclass
      and conname = 'uq_technical_asset_id_domain'
  ) then
    alter table elsa.technical_assets
      add constraint uq_technical_asset_id_domain unique (id, domain);
  end if;
end;
$$;

-- ============================================================
-- DOCUMENTS
-- Identidad estable de un documento, por encima de sus versiones.
--
-- `asset_id` puede ser nulo: hay documentación que aplica a un dominio
-- entero y no a un activo concreto (un procedimiento general de bloqueo y
-- etiquetado, por ejemplo). Su alcance de autorización es entonces el
-- dominio completo.
--
-- El alcance es `(domain, asset.code)`, exactamente el mismo par que ya
-- usan `permission_grants` y `technical_assets`. Autorizar un documento es
-- autorizar un alcance que ya existe: no hace falta un segundo modelo de
-- permisos, y no lo hay.
-- ============================================================
create table if not exists elsa.documents (
  id          uuid primary key default gen_random_uuid(),
  domain      text        not null references elsa.knowledge_domains (code),
  asset_id    uuid,
  code        text        not null,
  title       text        not null,
  source_kind text        not null,
  language    text,
  description text,
  is_active   boolean     not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint ck_document_code_normalized
    check (code = lower(btrim(code)) and code ~ '^[a-z0-9][a-z0-9_-]{0,63}$'),
  constraint ck_document_title_present check (btrim(title) <> ''),
  constraint ck_document_source_kind check (source_kind in (
    'manual',
    'procedure',
    'instruction',
    'technical_note',
    'approved_narrative'
  )),
  -- Un documento atado a un activo hereda forzosamente su dominio.
  constraint fk_document_asset
    foreign key (asset_id, domain) references elsa.technical_assets (id, domain)
    on delete restrict,
  unique (domain, code)
);

comment on table elsa.documents is
  'Documento narrativo (manual, procedimiento, instructivo). Su identidad no es su archivo: las ediciones son versiones.';
comment on column elsa.documents.asset_id is
  'Activo al que aplica. Nulo si aplica al dominio completo; el alcance de autorizacion es entonces el dominio.';
comment on column elsa.documents.source_kind is
  'Clase de documento. Decide como se revisa, no como se chunkea: eso lo decide la estructura del archivo.';

create index if not exists ix_documents_by_asset
  on elsa.documents (asset_id)
  where asset_id is not null;

drop trigger if exists trg_documents_touch_updated_at on elsa.documents;
create trigger trg_documents_touch_updated_at
  before update on elsa.documents
  for each row execute function elsa.touch_updated_at();

-- ============================================================
-- DOCUMENT_INGESTION_RUNS
-- Una ejecución de ingesta documental. Existe separada de `imports` porque
-- una importación del Bloque 2 exige un activo técnico y estas no: hay
-- documentación de dominio que no cuelga de ningún equipo.
--
-- `stats` guarda solo conteos y códigos: nunca una línea del documento.
-- ============================================================
create table if not exists elsa.document_ingestion_runs (
  id                 uuid primary key default gen_random_uuid(),
  document_id        uuid        not null references elsa.documents (id) on delete restrict,
  source_artifact_id uuid        not null references elsa.source_artifacts (id) on delete restrict,
  status             text        not null default 'received',
  failure_kind       text,
  failure_message    text,
  request_id         text,
  started_by         uuid        not null,
  started_at         timestamptz not null default now(),
  finished_at        timestamptz,
  stats              jsonb       not null default '{}'::jsonb,
  constraint ck_document_run_status
    check (status in ('received', 'processing', 'completed', 'failed')),
  constraint ck_document_run_failure_kind check (failure_kind is null or failure_kind in (
    'file',
    'parse',
    'validation',
    'storage',
    'database'
  )),
  -- Una ingesta fallida explica por que; una completada no inventa un motivo.
  constraint ck_document_run_failure_consistent
    check ((status = 'failed') = (failure_kind is not null))
);

comment on table elsa.document_ingestion_runs is
  'Ejecucion de ingesta documental. `stats` solo contiene conteos y codigos; el contenido del documento nunca entra en logs ni en auditoria.';

create index if not exists ix_document_runs_by_document
  on elsa.document_ingestion_runs (document_id, started_at desc);

-- ============================================================
-- DOCUMENT_VERSIONS
-- Una versión completa de un documento: su contenido en un momento dado.
--
-- Estados: `pending_validation` → `approved` → `published`, con `rejected`
-- como salida y `superseded` cuando otra versión la reemplaza. `received` y
-- `processing` pertenecen a la ingesta, no a la versión: una versión solo
-- existe si el chunking terminó.
--
-- Se guardan **dos hashes**. `content_sha256` es el de los bytes originales;
-- `structure_sha256` el de las secciones y chunks producidos. Dos versiones
-- con el mismo contenido y distinta estructura significan que cambió el
-- extractor o la política de chunking, no el documento. Sin los dos, esa
-- diferencia sería invisible y alguien la leería como un cambio del manual.
--
-- El índice parcial `uq_published_document_version` es lo que hace
-- imposible —no improbable— tener dos versiones vigentes del mismo
-- documento.
-- ============================================================
create table if not exists elsa.document_versions (
  id                  uuid primary key default gen_random_uuid(),
  document_id         uuid        not null references elsa.documents (id) on delete restrict,
  run_id              uuid        not null unique
                        references elsa.document_ingestion_runs (id) on delete restrict,
  source_artifact_id  uuid        not null references elsa.source_artifacts (id) on delete restrict,
  version_number      integer     not null,
  state               text        not null default 'pending_validation',
  content_sha256      text        not null,
  structure_sha256    text        not null,
  chunking_profile    text        not null,
  chunking_parameters jsonb       not null default '{}'::jsonb,
  extractor           text        not null,
  extractor_version   text        not null,
  section_count       integer     not null default 0,
  chunk_count         integer     not null default 0,
  created_at          timestamptz not null default now(),
  published_at        timestamptz,
  published_by        uuid,
  superseded_at       timestamptz,
  constraint ck_document_version_state check (state in (
    'pending_validation',
    'approved',
    'published',
    'rejected',
    'superseded'
  )),
  constraint ck_document_version_number_positive check (version_number > 0),
  constraint ck_document_version_content_sha256 check (content_sha256 ~ '^[0-9a-f]{64}$'),
  constraint ck_document_version_structure_sha256 check (structure_sha256 ~ '^[0-9a-f]{64}$'),
  constraint ck_document_version_counts check (section_count >= 0 and chunk_count >= 0),
  constraint ck_document_version_publication_consistent
    check ((published_at is null) = (published_by is null)),
  -- Una version publicada tiene que decir cuando y por quien.
  constraint ck_document_version_published_has_actor
    check (state <> 'published' or published_by is not null),
  unique (document_id, version_number)
);

comment on table elsa.document_versions is
  'Version historica completa de un documento. Nunca se sobrescribe: se reemplaza y la anterior queda `superseded`.';
comment on column elsa.document_versions.structure_sha256 is
  'Huella de las secciones y chunks producidos. Distingue un cambio del documento de un cambio del extractor o de la politica.';
comment on column elsa.document_versions.chunking_parameters is
  'Limites exactos con los que se chunkeo. Dos versiones con limites distintos no son comparables.';

create unique index if not exists uq_published_document_version
  on elsa.document_versions (document_id)
  where state = 'published';

create index if not exists ix_document_versions_by_document
  on elsa.document_versions (document_id, version_number desc);

-- ============================================================
-- DOCUMENT_SECTIONS
-- El árbol de títulos del documento, reconstruido.
--
-- `path` es la dirección estructural (`1`, `1.2`, `1.2.3`) y se calcula por
-- **posición en el árbol**, no por la numeración impresa: los manuales
-- reales tienen títulos sin numerar, numeraciones repetidas entre capítulos
-- y saltos. `number_label` conserva la numeración impresa, que es como la
-- gente se refiere a la sección al hablar.
-- ============================================================
create table if not exists elsa.document_sections (
  id           uuid primary key default gen_random_uuid(),
  version_id   uuid        not null references elsa.document_versions (id) on delete cascade,
  parent_id    uuid        references elsa.document_sections (id) on delete cascade,
  ordinal      integer     not null,
  path         text        not null,
  parent_path  text,
  depth        integer     not null,
  title        text        not null,
  number_label text,
  page_start   integer,
  page_end     integer,
  char_start   integer,
  char_end     integer,
  is_preamble  boolean     not null default false,
  created_at   timestamptz not null default now(),
  constraint ck_section_ordinal check (ordinal >= 0),
  constraint ck_section_depth check (depth >= 0),
  constraint ck_section_pages
    check (page_start is null or page_end is null or page_end >= page_start),
  constraint ck_section_offsets
    check (char_start is null or char_end is null or char_end >= char_start),
  unique (version_id, ordinal),
  unique (version_id, path)
);

comment on table elsa.document_sections is
  'Arbol de secciones de una version. `path` es posicional; `number_label` es la numeracion impresa.';

create index if not exists ix_document_sections_by_version
  on elsa.document_sections (version_id, ordinal);

-- ============================================================
-- DOCUMENT_CHUNKS
-- La unidad recuperable, con toda su procedencia.
--
-- La procedencia no es metadato opcional: es lo que hace cumplible la regla
-- 5 de CLAUDE.md. Un chunk que no puede señalar qué documento, qué versión,
-- qué sección y qué páginas lo produjeron no sirve como evidencia, y sin
-- evidencia no puede sustentar ninguna respuesta.
--
-- `version_id` en cada chunk, y no solo en la sección, es lo que hace
-- **imposible** por construcción que un chunk mezcle información de dos
-- versiones: un chunk pertenece a una versión y a una sola.
--
-- `structural_key` es la dirección del chunk dentro de la versión
-- (`<seccion>#<indice>`). Es la identidad con la que se comparan dos
-- versiones. Es posicional a propósito: si alguien inserta un párrafo, los
-- chunks siguientes de esa sección cambian de dirección y vuelven a
-- revisión. Es conservador, y esa es la dirección correcta del error: dar
-- por validado un dato que sí cambió sería mucho peor.
--
-- Aquí no hay vector. Ver la nota de la cabecera.
-- ============================================================
create table if not exists elsa.document_chunks (
  id               uuid primary key default gen_random_uuid(),
  version_id       uuid        not null references elsa.document_versions (id) on delete cascade,
  section_id       uuid        references elsa.document_sections (id) on delete cascade,
  ordinal          integer     not null,
  structural_key   text        not null,
  index_in_section integer     not null default 0,
  content          text        not null,
  content_sha256   text        not null,
  kind             text        not null,
  section_path     text,
  section_title    text,
  heading_trail    text[]      not null default '{}',
  page_start       integer,
  page_end         integer,
  block_start      integer,
  block_end        integer,
  char_start       integer,
  char_end         integer,
  token_estimate   integer     not null default 0,
  char_length      integer     not null default 0,
  overlap_chars    integer     not null default 0,
  boundary_reason  text        not null default 'structure',
  oversized        boolean     not null default false,
  change_kind      text,
  warnings         text[]      not null default '{}',
  created_at       timestamptz not null default now(),
  constraint ck_chunk_ordinal check (ordinal >= 0),
  constraint ck_chunk_content_present check (btrim(content) <> ''),
  constraint ck_chunk_content_sha256 check (content_sha256 ~ '^[0-9a-f]{64}$'),
  constraint ck_chunk_kind check (kind in ('prose', 'list', 'steps', 'warning', 'table', 'mixed')),
  constraint ck_chunk_boundary_reason check (boundary_reason in ('structure', 'size')),
  constraint ck_chunk_change_kind
    check (change_kind is null or change_kind in ('new', 'modified', 'unchanged', 'retired')),
  constraint ck_chunk_pages
    check (page_start is null or page_end is null or page_end >= page_start),
  constraint ck_chunk_offsets
    check (char_start is null or char_end is null or char_end >= char_start),
  constraint ck_chunk_measures
    check (token_estimate >= 0 and char_length >= 0 and overlap_chars >= 0),
  -- Un corte estructural no solapa: el documento ya marca ahi la
  -- discontinuidad, y repetir texto solo lo duplicaria en el indice.
  constraint ck_chunk_overlap_only_on_size
    check (boundary_reason = 'size' or overlap_chars = 0),
  unique (version_id, ordinal),
  unique (version_id, structural_key)
);

comment on table elsa.document_chunks is
  'Unidad recuperable con su procedencia completa. Sin vector: los embeddings llegan en el Bloque 4.2.';
comment on column elsa.document_chunks.structural_key is
  'Direccion del chunk dentro de la version. Es la identidad con la que se comparan dos versiones.';
comment on column elsa.document_chunks.heading_trail is
  'Titulos de los ancestros. Es metadato: no se antepone al contenido, para no cambiar el hash del texto.';
comment on column elsa.document_chunks.change_kind is
  'Como cambio respecto de la version publicada. Nulo cuando no habia version previa.';

create index if not exists ix_document_chunks_by_version
  on elsa.document_chunks (version_id, ordinal);

create index if not exists ix_document_chunks_by_section
  on elsa.document_chunks (section_id);

-- Reconocer el mismo contenido entre versiones sin comparar texto.
create index if not exists ix_document_chunks_by_content
  on elsa.document_chunks (content_sha256);

-- ============================================================
-- Un chunk pertenece a la misma versión que su sección.
--
-- Sin esto, la base aceptaría un chunk de la versión 2 apuntando a una
-- sección de la versión 1, y la procedencia mentiría sin que nada fallara.
-- La clave foránea compuesta lo hace imposible en vez de improbable.
-- ============================================================
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'elsa.document_sections'::regclass
      and conname = 'uq_document_section_id_version'
  ) then
    alter table elsa.document_sections
      add constraint uq_document_section_id_version unique (id, version_id);
  end if;

  if not exists (
    select 1 from pg_constraint
    where conrelid = 'elsa.document_chunks'::regclass
      and conname = 'fk_chunk_section_same_version'
  ) then
    alter table elsa.document_chunks
      add constraint fk_chunk_section_same_version
      foreign key (section_id, version_id)
      references elsa.document_sections (id, version_id)
      on delete cascade;
  end if;
end;
$$;

-- ============================================================
-- DOCUMENT_VERSION_EVENTS
-- Historial del ciclo de vida: quién activó qué y cuándo.
--
-- Estrictamente append-only, igual que `reviews`. Aprobar, rechazar,
-- publicar y reemplazar son cuatro filas nuevas, nunca una modificación de
-- la anterior. Una tabla que puede reescribirse no es trazabilidad.
--
-- No sustituye a `reviews`: aquella registra la validación técnica de un
-- dato del BOM y esta el estado de una versión documental. Ampliar
-- `reviews` habría exigido hacer nulo su `asset_id`, que hoy es obligatorio
-- y sostiene toda la historia del Bloque 2.
-- ============================================================
create table if not exists elsa.document_version_events (
  id          uuid primary key default gen_random_uuid(),
  seq         bigint generated always as identity unique,
  version_id  uuid        not null references elsa.document_versions (id) on delete restrict,
  event       text        not null,
  actor       uuid        not null,
  reason      text,
  request_id  text,
  occurred_at timestamptz not null default now(),
  constraint ck_document_event check (event in (
    'created',
    'approved',
    'rejected',
    'published',
    'superseded'
  )),
  -- Rechazar cierra el trabajo de alguien: tiene que decir por que, y lo
  -- garantiza la base, no la capa HTTP.
  constraint ck_document_event_reason
    check (event <> 'rejected' or (reason is not null and btrim(reason) <> ''))
);

comment on table elsa.document_version_events is
  'Historial append-only del ciclo de vida de una version documental. Ninguna fila se modifica ni se borra.';

create index if not exists ix_document_events_by_version
  on elsa.document_version_events (version_id, seq);

drop trigger if exists trg_document_events_append_only on elsa.document_version_events;
create trigger trg_document_events_append_only
  before update or delete on elsa.document_version_events
  for each row execute function elsa.forbid_review_mutation();

-- ============================================================
-- DOCUMENT_CHUNK_PROVENANCE
-- La reconstrucción completa de un chunk, en una sola lectura.
--
-- Es una **vista**, no columnas copiadas en `document_chunks`. Denormalizar
-- el estado de publicación o el alcance dentro del chunk crearía dos fuentes
-- de verdad para un dato que cambia —publicar una versión cambia el estado
-- de todos sus chunks— y tarde o temprano una de las dos mentiría.
--
-- `scope_domain` y `scope_equipment` son el alcance que hay que autorizar
-- **antes** de recuperar el chunk. Estan aqui para que la consulta de
-- recuperacion pueda filtrar por permiso en el mismo `where`, y no
-- recuperar primero y ocultar despues.
-- ============================================================
--
-- `security_invoker = true` NO es opcional aquí. Una vista de PostgreSQL se
-- ejecuta por defecto con los privilegios de su propietario, de modo que
-- **ignora la RLS de las tablas que consulta**. Sin esta opción, conceder
-- lectura sobre esta vista a cualquier rol le entregaría el corpus
-- documental entero sin filtrar una sola fila, y la RLS de las seis tablas
-- —que cualquiera daría por hecho que lo protege— no se aplicaría.
--
-- Con la opción activada, la vista se evalúa con los privilegios y la RLS
-- de quien la consulta. El backend, que usa credencial de servicio con
-- BYPASSRLS, la sigue viendo entera (ADR 0002).
create or replace view elsa.document_chunk_provenance
  with (security_invoker = true)
as
select
  chunk.id                as chunk_id,
  chunk.ordinal           as chunk_ordinal,
  chunk.structural_key,
  chunk.content,
  chunk.content_sha256,
  chunk.kind,
  chunk.heading_trail,
  chunk.page_start,
  chunk.page_end,
  chunk.char_start,
  chunk.char_end,
  chunk.token_estimate,
  chunk.change_kind,
  chunk.warnings,
  section.id              as section_id,
  section.path            as section_path,
  section.number_label    as section_number_label,
  section.title           as section_title,
  version.id              as version_id,
  version.version_number,
  version.state           as version_state,
  version.published_at,
  version.chunking_profile,
  version.extractor,
  version.extractor_version,
  version.structure_sha256,
  document.id             as document_id,
  document.code           as document_code,
  document.title          as document_title,
  document.source_kind,
  document.domain         as scope_domain,
  asset.code              as scope_equipment,
  run.id                  as run_id,
  artifact.sha256         as source_sha256,
  artifact.storage_key    as source_storage_key
from elsa.document_chunks         as chunk
join elsa.document_versions       as version  on version.id = chunk.version_id
join elsa.documents               as document on document.id = version.document_id
join elsa.document_ingestion_runs as run      on run.id = version.run_id
join elsa.source_artifacts        as artifact on artifact.id = version.source_artifact_id
left join elsa.document_sections  as section  on section.id = chunk.section_id
left join elsa.technical_assets   as asset    on asset.id = document.asset_id;

comment on view elsa.document_chunk_provenance is
  'Reconstruccion completa de la procedencia de un chunk, con el alcance que hay que autorizar antes de recuperarlo.';

-- ============================================================
-- AUDITORÍA
-- Se amplía el catálogo de operaciones con las de este bloque. Las
-- migraciones anteriores no se tocan: se sustituye la restricción.
-- ============================================================
alter table elsa.admin_audit_log
  drop constraint if exists ck_audit_operation;

alter table elsa.admin_audit_log
  add constraint ck_audit_operation check (operation in (
    -- Bloque 1
    'bootstrap_admin',
    'create_account',
    'grant_permission',
    'revoke_permission',
    'enable_user',
    'disable_user',
    'promote_admin',
    'demote_admin',
    -- Bloque 2
    'reviewer_granted',
    'reviewer_revoked',
    'source_uploaded',
    'import_completed',
    'import_failed',
    'validation_approved',
    'validation_rejected',
    'validation_reverted',
    'bom_published',
    'reconciliation_created',
    -- Bloque 4
    'document_created',
    'document_ingested',
    'document_ingestion_failed',
    'document_version_approved',
    'document_version_rejected',
    'document_published'
  ));

-- ============================================================
-- DEFENSA EN PROFUNDIDAD
-- Igual que en los bloques anteriores: RLS activo y sin políticas, de modo
-- que cualquier rol sin BYPASSRLS obtiene cero filas aunque llegue a
-- conectarse. La autorización real la aplica FastAPI (ADR 0002).
-- ============================================================
do $$
declare
  table_name text;
  role_name text;
begin
  foreach table_name in array array[
    'documents',
    'document_ingestion_runs',
    'document_versions',
    'document_sections',
    'document_chunks',
    'document_version_events'
  ] loop
    execute format('alter table elsa.%I enable row level security', table_name);
  end loop;

  -- Se vuelve a revocar, igual que hizo el Bloque 2 sobre lo del Bloque 1.
  -- Un REVOKE es una operación puntual, no una regla permanente: cada
  -- migración que añade objetos al esquema tiene que volver a cerrarlos, o
  -- el cierre solo cubre lo que existía cuando se ejecutó.
  --
  -- `all tables` incluye las vistas, así que `document_chunk_provenance`
  -- queda cubierta por la misma sentencia.
  --
  -- Se aplican solo si los roles de Supabase existen, para que estas
  -- migraciones también corran sobre un PostgreSQL limpio (tests).
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
