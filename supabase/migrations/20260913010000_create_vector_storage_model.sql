-- ============================================================
-- Almacenamiento vectorial de ELSA (Bloque 4.2.b)
--
-- Implementa lo que decidió ADR 0013: el vector vive aparte del chunk, el
-- modelo es un registro inmutable, la corrida deja rastro, y **generar no
-- activa**. Nada de esto se reabre aquí.
--
-- Tres tablas y una vista:
--
--   embedding_models          con qué se generó, de forma reproducible
--   embedding_runs            cuándo, quién, cuántos y cómo terminó
--   document_chunk_embeddings el vector, una fila por (chunk, modelo)
--   chunk_embedding_retrieval provenance lista para citar
--
-- POR QUÉ LA COLUMNA VECTORIAL NO DECLARA DIMENSIÓN
--
-- BGE-M3 usa 1024 dimensiones y EmbeddingGemma 768, y cuál de los dos acaba
-- en produccion depende de una validacion legal que aun no existe
-- (ADR 0015). Una columna `vector(1024)` ataria el esquema a un candidato y
-- convertiria el cambio de modelo en una migracion destructiva.
--
-- `vector` sin modificador acepta cualquier dimension, de modo que los dos
-- modelos conviven en la misma tabla. Que eso no degenere en un cajon de
-- sastre lo garantizan dos reglas del esquema, no el codigo:
--
--   1. La fila lleva `dimension` y una **clave foranea compuesta** contra
--      `embedding_models (id, dimension)`: la dimension declarada es
--      forzosamente la del modelo. Mismo patron que
--      `fk_document_version_run_identity`: la procedencia no puede mentir.
--   2. `check (vector_dims(embedding) = dimension)`: el vector real tiene
--      que medir lo que la fila declara.
--
-- El coste de no fijar la dimension en el tipo seria no poder crear un
-- indice ANN, que **exige** `vector(N)`. No es un coste hoy: el piloto usa
-- busqueda exacta (ADR 0013 §6), y sacrificar la coexistencia de modelos por
-- un indice que todavia no se necesita seria construir por anticipacion
-- (regla 23). Cuando el volumen justifique indexar, el indice se crea sobre
-- una vista materializada o una tabla por dimension, en su propia migracion
-- y con las tres condiciones que ADR 0013 §6 ya fija.
--
-- NO se crea ningun indice HNSW ni IVFFlat. NO se aplica a Supabase remoto.
-- ============================================================

create extension if not exists vector with schema public;

-- ============================================================
-- EMBEDDING_MODELS
-- Un espacio vectorial, descrito de forma que se pueda reproducir.
--
-- Las filas son **inmutables**: cambiar la revision, la dimension, la
-- normalizacion o cualquiera de los prefijos produce otro espacio vectorial,
-- y por tanto otra fila. Un UPDATE aqui convertiria en mentira todos los
-- vectores ya generados, asi que un disparador lo impide.
-- ============================================================
create table if not exists elsa.embedding_models (
  id                  uuid        primary key default gen_random_uuid(),
  family              text        not null,
  model_id            text        not null,
  revision            text        not null,
  dimension           integer     not null,
  normalized          boolean     not null,
  similarity          text        not null default 'cosine',
  document_prefix     text        not null default '',
  query_prefix        text        not null default '',
  composition_template text       not null,
  runtime             text        not null,
  state               text        not null default 'registered',
  registered_by       uuid        not null,
  registered_at       timestamptz not null default now(),
  activated_at        timestamptz,
  retired_at          timestamptz,
  notes               text,

  -- La revision tiene que identificar pesos concretos. `main` es una
  -- referencia movil y ADR 0013 §2 la prohibe para un modelo productivo.
  constraint ck_embedding_model_revision
    check (length(revision) > 0 and revision <> 'main'),
  constraint ck_embedding_model_dimension
    check (dimension between 1 and 16000),
  constraint ck_embedding_model_similarity
    check (similarity in ('cosine', 'inner_product', 'l2')),
  constraint ck_embedding_model_state
    check (state in ('registered', 'active', 'retired')),
  -- Solo los vectores normalizados admiten coseno como se usa aqui.
  constraint ck_embedding_model_cosine_needs_normalised
    check (similarity <> 'cosine' or normalized),
  constraint ck_embedding_model_activated
    check ((state = 'active') = (activated_at is not null and retired_at is null)),
  constraint ck_embedding_model_retired
    check ((state = 'retired') = (retired_at is not null)),

  -- El mismo modelo y la misma revision con distintos prefijos o distinta
  -- plantilla son espacios vectoriales **distintos**, y por eso la identidad
  -- los incluye: dos corridas solo son comparables si coinciden en todo esto.
  unique (model_id, revision, dimension, document_prefix, query_prefix,
          composition_template, normalized)
);

comment on table elsa.embedding_models is
  'Un espacio vectorial reproducible. Las filas son inmutables: cambiar cualquier campo es otro modelo.';
comment on column elsa.embedding_models.revision is
  'Commit o digest de los pesos. `main` esta prohibido: es una referencia movil (ADR 0013 §2).';

-- Clave candidata para la clave foranea compuesta de los embeddings. `id` ya
-- es la primaria; esto existe porque PostgreSQL exige unicidad sobre las
-- columnas exactas a las que apunta una FK compuesta.
create unique index if not exists uq_embedding_model_id_dimension
  on elsa.embedding_models (id, dimension);

-- A lo sumo un modelo activo. Indice unico parcial, el mismo mecanismo que
-- `uq_published_document_version` usa para la version publicada: la regla la
-- garantiza la base, no la aplicacion.
create unique index if not exists uq_active_embedding_model
  on elsa.embedding_models ((true)) where state = 'active';

-- ============================================================
-- EMBEDDING_RUNS
-- Mismo criterio que `document_ingestion_runs` (ADR 0012): una ejecucion que
-- no deja rastro no se puede auditar ni reanudar.
-- ============================================================
create table if not exists elsa.embedding_runs (
  id              uuid        primary key default gen_random_uuid(),
  model_id        uuid        not null references elsa.embedding_models (id) on delete restrict,
  status          text        not null default 'running',
  trigger_source  text        not null default 'manual',
  started_by      uuid        not null,
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  total_chunks    integer     not null default 0,
  generated       integer     not null default 0,
  reused          integer     not null default 0,
  failed          integer     not null default 0,
  failure_kind    text,
  failure_message text,
  request_id      text,
  parameters      jsonb       not null default '{}'::jsonb,

  constraint ck_embedding_run_status
    check (status in ('running', 'completed', 'failed', 'cancelled')),
  constraint ck_embedding_run_trigger
    check (trigger_source in ('manual', 'ingestion', 'model_change', 'backfill')),
  constraint ck_embedding_run_failure_kind
    check (failure_kind is null
           or failure_kind in ('model', 'database', 'timeout', 'cancelled', 'unknown')),
  -- Una corrida fallida explica por que; una completada no inventa un motivo.
  constraint ck_embedding_run_failure_consistent
    check ((status = 'failed') = (failure_kind is not null)),
  constraint ck_embedding_run_finished
    check ((status = 'running') = (finished_at is null)),
  constraint ck_embedding_run_counters
    check (total_chunks >= 0 and generated >= 0 and reused >= 0 and failed >= 0)
);

comment on table elsa.embedding_runs is
  'Una corrida de generacion de embeddings: que modelo, quien, cuantos y como termino.';

create index if not exists ix_embedding_run_model
  on elsa.embedding_runs (model_id, started_at desc);

-- `document_chunks` necesita la clave candidata para la FK compuesta de
-- `document_chunk_embeddings`. Se anade solo si falta, porque en cuanto existan embeddings su
-- clave foranea depende de este indice y el borrado fallaria.
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'elsa.document_chunks'::regclass
      and conname = 'uq_document_chunk_id_version'
  ) then
    alter table elsa.document_chunks
      add constraint uq_document_chunk_id_version unique (id, version_id);
  end if;
end;
$$;

-- ============================================================
-- DOCUMENT_CHUNK_EMBEDDINGS
-- Una fila por (chunk, modelo). El mismo chunk puede tener a la vez su
-- vector de BGE-M3 y el de EmbeddingGemma: es lo que permite cambiar de
-- modelo sin quedarse sin indice durante la transicion (ADR 0013 §1).
-- ============================================================
create table if not exists elsa.document_chunk_embeddings (
  chunk_id        uuid        not null,
  model_id        uuid        not null,
  version_id      uuid        not null,
  run_id          uuid        not null references elsa.embedding_runs (id) on delete restrict,
  dimension       integer     not null,
  embedding       vector      not null,
  embedded_sha256 text        not null,
  content_sha256  text        not null,
  created_at      timestamptz not null default now(),
  state           text        not null default 'current',

  primary key (chunk_id, model_id),

  constraint ck_chunk_embedding_state
    check (state in ('current', 'superseded')),
  constraint ck_chunk_embedding_sha256
    check (embedded_sha256 ~ '^[0-9a-f]{64}$' and content_sha256 ~ '^[0-9a-f]{64}$'),

  -- El vector mide lo que la fila declara...
  constraint ck_chunk_embedding_dimension
    check (vector_dims(embedding) = dimension),
  -- ...y lo que declara es forzosamente la dimension de su modelo.
  constraint fk_chunk_embedding_model_dimension
    foreign key (model_id, dimension)
    references elsa.embedding_models (id, dimension)
    on update restrict on delete restrict,

  -- El embedding no puede decir pertenecer a una version distinta que su
  -- chunk. Mismo patron que `fk_chunk_section_same_version`.
  constraint fk_chunk_embedding_same_version
    foreign key (chunk_id, version_id)
    references elsa.document_chunks (id, version_id)
    on update restrict on delete cascade
);

comment on table elsa.document_chunk_embeddings is
  'Vector de un chunk bajo un modelo. La columna no fija dimension a proposito: 768 y 1024 conviven.';
comment on column elsa.document_chunk_embeddings.embedded_sha256 is
  'Hash del texto exacto que se envio al modelo, ya compuesto. Un embedding esta obsoleto si este hash no coincide con el que hoy se compondria (ADR 0013 §4).';

create index if not exists ix_chunk_embedding_model_state
  on elsa.document_chunk_embeddings (model_id, state);
create index if not exists ix_chunk_embedding_run
  on elsa.document_chunk_embeddings (run_id);
create index if not exists ix_chunk_embedding_version
  on elsa.document_chunk_embeddings (version_id);

-- ============================================================
-- INMUTABILIDAD DEL MODELO
-- Lo unico que puede cambiar de un modelo es su estado y sus fechas: activar
-- y retirar. Todo lo demas define el espacio vectorial, y cambiarlo
-- convertiria en mentira los vectores ya generados.
-- ============================================================
create or replace function elsa.reject_embedding_model_mutation()
returns trigger
language plpgsql
as $$
begin
  if (new.family, new.model_id, new.revision, new.dimension, new.normalized,
      new.similarity, new.document_prefix, new.query_prefix,
      new.composition_template, new.runtime, new.registered_by, new.registered_at)
     is distinct from
     (old.family, old.model_id, old.revision, old.dimension, old.normalized,
      old.similarity, old.document_prefix, old.query_prefix,
      old.composition_template, old.runtime, old.registered_by, old.registered_at)
  then
    raise exception
      'an embedding model is immutable: change the state, or register another model'
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_embedding_models_immutable on elsa.embedding_models;
create trigger trg_embedding_models_immutable
  before update on elsa.embedding_models
  for each row execute function elsa.reject_embedding_model_mutation();

-- ============================================================
-- VISTA DE RECUPERACION
-- Deja lista la procedencia para citar, junto al vector: la consulta de
-- recuperacion ordena por distancia sobre el, asi que tiene que estar aqui.
--
-- La vista no decide nada sobre permisos. El alcance lo aplica el WHERE de
-- quien consulta, y por eso la vista expone `scope_domain` y
-- `scope_equipment`: para que ese filtro sea escribible sin volver a unir
-- documentos y activos.
--
-- `security_invoker = true` es obligatorio: sin el, la vista se ejecutaria
-- con los privilegios de su propietario y saltaria el RLS de sus tablas base.
-- ============================================================
create or replace view elsa.chunk_embedding_retrieval
  with (security_invoker = true)
as
select
  emb.chunk_id,
  emb.model_id,
  emb.embedding,
  emb.dimension,
  emb.embedded_sha256,
  chunk.ordinal          as chunk_ordinal,
  chunk.structural_key,
  chunk.content,
  chunk.heading_trail,
  chunk.page_start,
  chunk.page_end,
  chunk.section_id,
  version.id             as version_id,
  version.version_number,
  version.state          as version_state,
  document.id            as document_id,
  document.code          as document_code,
  document.title         as document_title,
  document.domain        as scope_domain,
  asset.code             as scope_equipment,
  artifact.sha256        as source_sha256,
  artifact.storage_key   as source_storage_key
from elsa.document_chunk_embeddings as emb
join elsa.document_chunks     as chunk    on chunk.id = emb.chunk_id
join elsa.document_versions   as version  on version.id = emb.version_id
join elsa.documents           as document on document.id = version.document_id
join elsa.source_artifacts    as artifact on artifact.id = version.source_artifact_id
left join elsa.technical_assets as asset  on asset.id = document.asset_id;

comment on view elsa.chunk_embedding_retrieval is
  'Vector mas procedencia citable. La autorizacion la aplica el WHERE de quien consulta, nunca esta vista.';

-- ============================================================
-- DEFENSA EN PROFUNDIDAD
-- Igual que en los bloques anteriores: RLS activo y sin politicas, de modo
-- que cualquier rol sin BYPASSRLS obtiene cero filas aunque llegue a
-- conectarse. La autorizacion real la aplica FastAPI (ADR 0002).
-- ============================================================
do $$
declare
  table_name text;
  role_name text;
begin
  foreach table_name in array array[
    'embedding_models',
    'embedding_runs',
    'document_chunk_embeddings'
  ] loop
    execute format('alter table elsa.%I enable row level security', table_name);
  end loop;

  -- Cada migracion que anade objetos tiene que volver a cerrarlos: un REVOKE
  -- es puntual, no una regla permanente. `all tables` cubre tambien la vista.
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
