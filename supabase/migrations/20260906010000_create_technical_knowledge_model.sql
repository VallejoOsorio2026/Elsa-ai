-- ============================================================
-- Modelo de conocimiento técnico de ELSA (Bloque 2)
--
-- Activo Técnico, componentes con identidad interna permanente, BOM de
-- Ingeniería versionado, snapshots de SAP, planos, AMEF, criterios S/O/D,
-- reconciliación, revisión técnica y auditoría.
--
-- Tres ideas gobiernan el diseño:
--
-- 1. **La identidad del componente es un UUID interno y nada más.** El
--    código SAP, el nombre, el plano y la referencia son atributos que
--    cambian con el tiempo; si fueran la identidad, cambiarlos crearía un
--    componente distinto y se perdería la historia. Un componente puede
--    existir sin código SAP y seguir siendo un componente técnico válido.
--
-- 2. **Ingeniería y SAP son dos fuentes separadas que no se mezclan.** El
--    XLSX aprobado dice cómo *debía* quedar el BOM; el HTM exportado dice
--    cómo *se ve* SAP en una fecha. Una diferencia es evidencia de una
--    desviación, no prueba de cuál valor es correcto. La reconciliación es
--    una capa aparte que conserva ambos valores y nunca corrige el origen.
--
-- 3. **Nada se sobrescribe.** Las versiones, los snapshots y las
--    validaciones se acumulan. Publicar una versión nueva no borra la
--    anterior: la marca como reemplazada.
--
-- Los bytes de los archivos originales NO viven aquí: viven en el puerto de
-- almacenamiento privado. Esta base guarda solo su metadato y su hash.
-- ============================================================

-- ============================================================
-- TECHNICAL_ASSETS
-- Concepto genérico de Activo Técnico. Tampella es el primer caso, no el
-- modelo: nada aquí se llama ni se comporta como un equipo concreto.
--
-- `domain` + `code` reproducen exactamente el alcance del Bloque 1
-- (dominio + equipo), de modo que autorizar un activo es autorizar un
-- alcance ya existente y no hace falta un segundo modelo de permisos.
-- ============================================================
create table if not exists elsa.technical_assets (
  id          uuid primary key default gen_random_uuid(),
  code        text        not null unique,
  name        text        not null,
  domain      text        not null references elsa.knowledge_domains (code),
  description text,
  is_active   boolean     not null default true,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint ck_asset_code_normalized
    check (code = lower(btrim(code)) and code ~ '^[a-z0-9][a-z0-9_-]{0,63}$')
);

comment on table elsa.technical_assets is
  'Activo Técnico genérico. El alcance de autorización es (domain, code), el mismo del Bloque 1.';
comment on column elsa.technical_assets.code is
  'Código del activo, idéntico en forma a `permission_grants.equipment`. Es dato, no constante de código.';

drop trigger if exists trg_technical_assets_touch_updated_at on elsa.technical_assets;
create trigger trg_technical_assets_touch_updated_at
  before update on elsa.technical_assets
  for each row execute function elsa.touch_updated_at();

-- ============================================================
-- SUBSYSTEMS
-- Agrupación técnica dentro de un activo. Se descubre de la fuente de
-- Ingeniería; por eso el nombre original se conserva junto al código
-- normalizado con el que se compara.
-- ============================================================
create table if not exists elsa.subsystems (
  id         uuid primary key default gen_random_uuid(),
  asset_id   uuid        not null references elsa.technical_assets (id) on delete restrict,
  code       text        not null,
  name       text        not null,
  created_at timestamptz not null default now(),
  unique (asset_id, code)
);

comment on table elsa.subsystems is
  'Subsistemas de un activo. `code` es la forma normalizada de `name`, para comparar sin depender de mayúsculas ni acentos.';

-- ============================================================
-- COMPONENTS
-- Identidad interna y permanente del componente.
--
-- La tabla es deliberadamente pobre: solo el UUID, el activo y el
-- subsistema. Todo lo demás (código SAP, nombre, plano, referencia,
-- cantidad) pertenece a una versión concreta del BOM o a la tabla de
-- identificadores, porque todo lo demás puede cambiar sin que el
-- componente deje de ser el mismo componente.
--
-- Un componente retirado conserva `retired_at`: nunca se borra, porque la
-- evidencia histórica que lo menciona seguiría siendo válida.
-- ============================================================
create table if not exists elsa.components (
  id           uuid primary key default gen_random_uuid(),
  asset_id     uuid        not null references elsa.technical_assets (id) on delete restrict,
  subsystem_id uuid        references elsa.subsystems (id) on delete restrict,
  created_at   timestamptz not null default now(),
  retired_at   timestamptz
);

comment on table elsa.components is
  'Identidad interna permanente del componente. Un componente sin código SAP es un componente válido.';
comment on column elsa.components.retired_at is
  'Retirado de la última versión publicada. No se borra: la evidencia histórica sigue apuntando aquí.';

create index if not exists ix_components_by_asset
  on elsa.components (asset_id)
  where retired_at is null;

-- ============================================================
-- COMPONENT_IDENTIFIERS
-- Identificadores externos observados para un componente: código SAP,
-- referencia de plano, part number, nombre.
--
-- Son *alias*, no identidad. Se acumulan: si un componente cambia de
-- código SAP, el alias antiguo sigue aquí y permite reconocerlo en
-- evidencia vieja. Por eso hay `first_seen_at` / `last_seen_at` en vez de
-- un UPDATE destructivo del valor.
-- ============================================================
create table if not exists elsa.component_identifiers (
  id             uuid primary key default gen_random_uuid(),
  component_id   uuid        not null references elsa.components (id) on delete cascade,
  asset_id       uuid        not null references elsa.technical_assets (id) on delete restrict,
  kind           text        not null,
  value          text        not null,
  value_original text        not null,
  first_seen_at  timestamptz not null default now(),
  last_seen_at   timestamptz not null default now(),
  constraint ck_identifier_kind check (kind in (
    'sap_code',
    'drawing_reference',
    'part_number',
    'name'
  )),
  unique (component_id, kind, value)
);

comment on table elsa.component_identifiers is
  'Alias externos de un componente. Nunca son su identidad: el nombre por sí solo jamás basta para fusionar.';

-- Índice de emparejamiento: dado un activo y un valor observado, ¿qué
-- componentes lo han llevado alguna vez? Si devuelve más de uno, el
-- emparejamiento es ambiguo y no se resuelve automáticamente.
create index if not exists ix_identifiers_lookup
  on elsa.component_identifiers (asset_id, kind, value);

-- ============================================================
-- SOURCE_ARTIFACTS
-- Metadato del archivo original. Los bytes viven en el almacenamiento
-- privado (puerto `artifact_storage`), nunca en PostgreSQL ni en Git.
--
-- `unique (kind, sha256)` es el mecanismo de idempotencia: reimportar
-- exactamente el mismo archivo se detecta de forma determinística en la
-- base, no por una comprobación previa que dos peticiones simultáneas
-- podrían pasar a la vez.
-- ============================================================
create table if not exists elsa.source_artifacts (
  id                uuid primary key default gen_random_uuid(),
  kind              text        not null,
  sha256            text        not null,
  byte_size         bigint      not null,
  original_filename text,
  content_type      text,
  storage_key       text        not null unique,
  uploaded_by       uuid        not null,
  uploaded_at       timestamptz not null default now(),
  constraint ck_source_artifact_kind check (kind in (
    'engineering_bom_xlsx',
    'sap_bom_htm'
  )),
  constraint ck_source_artifact_sha256 check (sha256 ~ '^[0-9a-f]{64}$'),
  constraint ck_source_artifact_size check (byte_size > 0),
  unique (kind, sha256)
);

comment on table elsa.source_artifacts is
  'Archivo original inmutable. Solo metadato y SHA-256: los bytes están en el almacenamiento privado.';
comment on column elsa.source_artifacts.storage_key is
  'Clave generada por el sistema. El nombre que traía el archivo nunca se usa como identificador.';

-- ============================================================
-- DERIVED_ARTIFACTS
-- Todo derivado (una imagen de plano extraída del XLSX) conserva la
-- relación con el original del que salió y su propio hash.
-- ============================================================
create table if not exists elsa.derived_artifacts (
  id                 uuid primary key default gen_random_uuid(),
  source_artifact_id uuid        not null references elsa.source_artifacts (id) on delete restrict,
  kind               text        not null,
  sha256             text        not null,
  byte_size          bigint      not null,
  content_type       text,
  storage_key        text        not null unique,
  created_at         timestamptz not null default now(),
  constraint ck_derived_artifact_kind check (kind in ('drawing_image')),
  constraint ck_derived_artifact_sha256 check (sha256 ~ '^[0-9a-f]{64}$'),
  constraint ck_derived_artifact_size check (byte_size > 0)
);

comment on table elsa.derived_artifacts is
  'Artefactos derivados del original (p. ej. planos embebidos). Conservan hash y procedencia.';

create index if not exists ix_derived_by_source
  on elsa.derived_artifacts (source_artifact_id);

-- ============================================================
-- IMPORTS
-- Una ejecución de ingesta. Distingue el tipo de fallo, porque «el archivo
-- no es un XLSX» y «la base no responde» exigen respuestas distintas del
-- administrador y códigos HTTP distintos.
--
-- `stats` guarda solo conteos: nunca contenido técnico.
-- ============================================================
create table if not exists elsa.imports (
  id                 uuid primary key default gen_random_uuid(),
  source_artifact_id uuid        not null references elsa.source_artifacts (id) on delete restrict,
  asset_id           uuid        not null references elsa.technical_assets (id) on delete restrict,
  kind               text        not null,
  status             text        not null default 'received',
  failure_kind       text,
  failure_message    text,
  request_id         text,
  started_by         uuid        not null,
  started_at         timestamptz not null default now(),
  finished_at        timestamptz,
  stats              jsonb       not null default '{}'::jsonb,
  constraint ck_import_kind check (kind in ('engineering_bom', 'sap_snapshot')),
  constraint ck_import_status check (status in ('received', 'processing', 'completed', 'failed')),
  constraint ck_import_failure_kind check (failure_kind is null or failure_kind in (
    'file',
    'parse',
    'ambiguity',
    'storage',
    'database'
  )),
  -- Una importación fallida explica por qué; una completada no inventa un motivo.
  constraint ck_import_failure_consistent
    check ((status = 'failed') = (failure_kind is not null))
);

comment on table elsa.imports is
  'Ejecución de ingesta. `stats` solo contiene conteos; el contenido técnico nunca entra en logs ni en auditoría.';

create index if not exists ix_imports_by_asset
  on elsa.imports (asset_id, started_at desc);

-- ============================================================
-- ENGINEERING_BOM_VERSIONS
-- Versión completa del BOM aprobado por Ingeniería.
--
-- Estados: `pending_validation` → `approved` → `published`, con
-- `rejected` como salida y `superseded` cuando otra versión la reemplaza.
-- `received` y `processing` pertenecen a la importación, no a la versión:
-- una versión solo existe si el parser terminó.
--
-- El índice parcial `uq_published_version_per_asset` es lo que hace
-- imposible —no improbable— tener dos versiones vigentes del mismo activo.
-- ============================================================
create table if not exists elsa.engineering_bom_versions (
  id                 uuid primary key default gen_random_uuid(),
  asset_id           uuid        not null references elsa.technical_assets (id) on delete restrict,
  import_id          uuid        not null unique references elsa.imports (id) on delete restrict,
  source_artifact_id uuid        not null references elsa.source_artifacts (id) on delete restrict,
  version_number     integer     not null,
  state              text        not null default 'pending_validation',
  created_at         timestamptz not null default now(),
  published_at       timestamptz,
  published_by       uuid,
  superseded_at      timestamptz,
  constraint ck_version_state check (state in (
    'pending_validation',
    'approved',
    'published',
    'rejected',
    'superseded'
  )),
  constraint ck_version_number_positive check (version_number > 0),
  constraint ck_version_publication_consistent
    check ((published_at is null) = (published_by is null)),
  unique (asset_id, version_number)
);

comment on table elsa.engineering_bom_versions is
  'Versión histórica completa del BOM de Ingeniería. Nunca se sobrescribe: se reemplaza y la anterior queda `superseded`.';

create unique index if not exists uq_published_version_per_asset
  on elsa.engineering_bom_versions (asset_id)
  where state = 'published';

create index if not exists ix_versions_by_asset
  on elsa.engineering_bom_versions (asset_id, version_number desc);

-- ============================================================
-- ENGINEERING_BOM_ITEMS
-- Una fila del BOM de Ingeniería, tal y como venía y ya normalizada.
--
-- Se guardan las dos formas de cada valor sensible (`quantity` y
-- `quantity_original`, `sap_code` y `sap_code_original`): la normalizada
-- para comparar, la original para poder demostrarle a un ingeniero qué
-- decía exactamente su archivo. `extra` conserva las columnas que la
-- plantilla traiga y este bloque no reconozca, para no perder información
-- por no haberla previsto.
--
-- Los valores de inventario (`inventory_strategy`, `stock_max`,
-- `stock_min`, `source_stock`) son los de ESA fuente en ESA fecha. No son
-- el stock actual: el stock actual seguirá siendo de Materiales/ZIAA.
-- ============================================================
create table if not exists elsa.engineering_bom_items (
  id                    uuid primary key default gen_random_uuid(),
  version_id            uuid    not null references elsa.engineering_bom_versions (id) on delete cascade,
  component_id          uuid    references elsa.components (id) on delete restrict,
  subsystem_id          uuid    references elsa.subsystems (id) on delete restrict,
  source_row            integer not null,
  position              text,
  subsystem_name        text,
  component_name        text,
  sap_code              text,
  sap_code_original     text,
  technical_description text,
  quantity              numeric,
  quantity_original     text,
  unit                  text,
  model_reference       text,
  assembly_drawing      text,
  drawing_reference     text,
  bom_update_flag       text,
  inventory_strategy    text,
  stock_max             numeric,
  stock_min             numeric,
  source_stock          numeric,
  remarks               text,
  match_rule            text,
  match_confidence      text    not null default 'unresolved',
  change_kind           text,
  extra                 jsonb   not null default '{}'::jsonb,
  constraint ck_bom_item_confidence check (match_confidence in (
    'exact',
    'strong',
    'weak',
    'unresolved'
  )),
  constraint ck_bom_item_change_kind check (change_kind is null or change_kind in (
    'new',
    'modified',
    'unchanged',
    'retired'
  )),
  constraint ck_bom_item_row_positive check (source_row > 0),
  unique (version_id, source_row)
);

comment on table elsa.engineering_bom_items is
  'Fila del BOM de Ingeniería. Conserva valor original y normalizado, y la razón por la que se emparejó con un componente.';
comment on column elsa.engineering_bom_items.source_stock is
  'Stock que traía el archivo de Ingeniería en su fecha. NO es el stock actual de SAP.';
comment on column elsa.engineering_bom_items.match_rule is
  'Regla que produjo el emparejamiento automático (p. ej. drawing_reference). Auditable y explicable.';

create index if not exists ix_bom_items_by_version
  on elsa.engineering_bom_items (version_id, source_row);

create index if not exists ix_bom_items_by_component
  on elsa.engineering_bom_items (component_id);

create index if not exists ix_bom_items_by_sap_code
  on elsa.engineering_bom_items (version_id, sap_code)
  where sap_code is not null;

-- ============================================================
-- DRAWINGS y DRAWING_IMAGES
-- El plano es una entidad del activo; la imagen extraída es evidencia
-- concreta de una versión.
--
-- Si no se puede asociar una imagen a un número de plano con certeza, se
-- queda en `pending_review` con `drawing_id` nulo. Adivinar la asociación
-- sería inventar un hecho técnico. En este bloque no hay OCR ni visión:
-- la imagen se conserva, no se interpreta.
-- ============================================================
create table if not exists elsa.drawings (
  id         uuid primary key default gen_random_uuid(),
  asset_id   uuid        not null references elsa.technical_assets (id) on delete restrict,
  number     text        not null,
  title      text,
  created_at timestamptz not null default now(),
  unique (asset_id, number)
);

comment on table elsa.drawings is
  'Plano del activo, identificado por su número. La interpretación gráfica queda fuera de este bloque.';

create table if not exists elsa.drawing_images (
  id                  uuid primary key default gen_random_uuid(),
  version_id          uuid        not null references elsa.engineering_bom_versions (id) on delete cascade,
  derived_artifact_id uuid        not null references elsa.derived_artifacts (id) on delete restrict,
  drawing_id          uuid        references elsa.drawings (id) on delete restrict,
  sheet_name          text,
  anchor              text,
  width_px            integer,
  height_px           integer,
  association_status  text        not null default 'pending_review',
  association_rule    text,
  created_at          timestamptz not null default now(),
  constraint ck_drawing_image_status check (association_status in ('resolved', 'pending_review')),
  -- Resuelto exige plano; pendiente exige que no se haya inventado uno.
  constraint ck_drawing_image_association
    check ((association_status = 'resolved') = (drawing_id is not null))
);

comment on table elsa.drawing_images is
  'Imagen embebida extraída del XLSX como evidencia. Sin asociación cierta a un plano, queda pendiente de revisión.';

create index if not exists ix_drawing_images_by_version
  on elsa.drawing_images (version_id);

-- ============================================================
-- FAILURE_MODES (AMEF)
-- El NPR lo calcula el backend, no el Excel: las fórmulas del archivo son
-- contenido no confiable y no se evalúan. La restricción de más abajo
-- impide que una fila con NPR incoherente entre siquiera en la base.
-- ============================================================
create table if not exists elsa.failure_modes (
  id                 uuid primary key default gen_random_uuid(),
  version_id         uuid    not null references elsa.engineering_bom_versions (id) on delete cascade,
  component_id       uuid    references elsa.components (id) on delete restrict,
  source_row         integer not null,
  subsystem_name     text,
  component_name     text,
  sap_code           text,
  failure_mode       text,
  effect             text,
  cause              text,
  severity           integer,
  occurrence         integer,
  detection          integer,
  rpn                integer,
  action             text,
  preventive_plan    text,
  corrective_action  text,
  remarks            text,
  match_rule         text,
  match_confidence   text    not null default 'unresolved',
  change_kind        text,
  extra              jsonb   not null default '{}'::jsonb,
  constraint ck_amef_severity   check (severity   is null or severity   between 1 and 10),
  constraint ck_amef_occurrence check (occurrence is null or occurrence between 1 and 10),
  constraint ck_amef_detection  check (detection  is null or detection  between 1 and 10),
  -- NPR = S x O x D, o nulo si falta algún factor. Determinístico y verificable.
  constraint ck_amef_rpn check (
    case
      when severity is null or occurrence is null or detection is null then rpn is null
      else rpn = severity * occurrence * detection
    end
  ),
  constraint ck_amef_confidence check (match_confidence in (
    'exact',
    'strong',
    'weak',
    'unresolved'
  )),
  constraint ck_amef_change_kind check (change_kind is null or change_kind in (
    'new',
    'modified',
    'unchanged',
    'retired'
  )),
  unique (version_id, source_row)
);

comment on table elsa.failure_modes is
  'AMEF de una versión. El NPR se calcula en el backend (S x O x D) y la restricción impide almacenar uno incoherente.';

create index if not exists ix_failure_modes_by_version
  on elsa.failure_modes (version_id, source_row);

create index if not exists ix_failure_modes_by_component
  on elsa.failure_modes (component_id);

-- ============================================================
-- SOD_CRITERIA
-- Los criterios de Severidad, Ocurrencia y Detección son DATO versionado,
-- no constantes de código: si Ingeniería cambia la escala, cambia el
-- archivo, no el backend.
-- ============================================================
create table if not exists elsa.sod_criteria (
  id          uuid primary key default gen_random_uuid(),
  version_id  uuid    not null references elsa.engineering_bom_versions (id) on delete cascade,
  dimension   text    not null,
  scale_value integer,
  label       text,
  description text,
  range_low   numeric,
  range_high  numeric,
  source_row  integer not null,
  constraint ck_sod_dimension check (dimension in ('severity', 'occurrence', 'detection')),
  constraint ck_sod_scale check (scale_value is null or scale_value between 1 and 10),
  unique (version_id, dimension, source_row)
);

comment on table elsa.sod_criteria is
  'Criterios y rangos S/O/D tal como los define la fuente de Ingeniería. Datos versionados, nunca lógica compilada.';

-- ============================================================
-- OPTION_TABLES
-- Tablas de opciones de la plantilla (p. ej. estrategias de inventario).
-- Mismo principio que S/O/D: dato versionado.
-- ============================================================
create table if not exists elsa.option_tables (
  id           uuid primary key default gen_random_uuid(),
  version_id   uuid    not null references elsa.engineering_bom_versions (id) on delete cascade,
  table_name   text    not null,
  option_value text    not null,
  description  text,
  source_row   integer not null,
  unique (version_id, table_name, source_row)
);

comment on table elsa.option_tables is
  'Tablas de opciones de la plantilla de Ingeniería, conservadas como dato de la versión.';

-- ============================================================
-- SAP_BOM_SNAPSHOTS
-- Cómo se veía SAP en una fecha. Inmutable y acumulativo: un snapshot
-- nunca se convierte en BOM publicado de Ingeniería, ni lo reemplaza.
-- ============================================================
create table if not exists elsa.sap_bom_snapshots (
  id                   uuid primary key default gen_random_uuid(),
  asset_id             uuid        not null references elsa.technical_assets (id) on delete restrict,
  import_id            uuid        not null unique references elsa.imports (id) on delete restrict,
  source_artifact_id   uuid        not null references elsa.source_artifacts (id) on delete restrict,
  functional_location  text,
  description          text,
  valid_from           date,
  captured_at          timestamptz not null default now(),
  created_at           timestamptz not null default now()
);

comment on table elsa.sap_bom_snapshots is
  'Estado observado en SAP en una fecha. Evidencia, no autoridad: nunca reemplaza al BOM de Ingeniería publicado.';

create index if not exists ix_snapshots_by_asset
  on elsa.sap_bom_snapshots (asset_id, captured_at desc);

-- ============================================================
-- SAP_SNAPSHOT_ITEMS
-- `entry_kind` separa material de equipo/objeto técnico. Mezclar un equipo
-- hijo con un material del BOM produciría discrepancias falsas en la
-- reconciliación, así que la distinción es estructural, no una convención.
-- ============================================================
create table if not exists elsa.sap_snapshot_items (
  id                uuid primary key default gen_random_uuid(),
  snapshot_id       uuid    not null references elsa.sap_bom_snapshots (id) on delete cascade,
  source_row        integer not null,
  entry_kind        text    not null,
  position          text,
  sap_code          text,
  description       text,
  quantity          numeric,
  quantity_original text,
  unit              text,
  parent_path       text,
  depth             integer not null default 0,
  extra             jsonb   not null default '{}'::jsonb,
  constraint ck_snapshot_entry_kind check (entry_kind in ('material', 'equipment')),
  constraint ck_snapshot_depth check (depth >= 0),
  unique (snapshot_id, source_row)
);

comment on table elsa.sap_snapshot_items is
  'Renglón de un snapshot SAP. `entry_kind` impide comparar equipos hijos contra materiales del BOM.';

create index if not exists ix_snapshot_items_by_snapshot
  on elsa.sap_snapshot_items (snapshot_id, source_row);

create index if not exists ix_snapshot_items_by_sap_code
  on elsa.sap_snapshot_items (snapshot_id, sap_code)
  where sap_code is not null;

-- ============================================================
-- RECONCILIATION_RUNS / RECONCILIATION_ITEMS
-- Capa separada. No toca ni el BOM de Ingeniería ni el snapshot: guarda
-- ambos valores uno al lado del otro y deja la conclusión a una persona.
--
-- `unique (version_id, snapshot_id)` mantiene el resultado determinístico
-- para un par dado; un snapshot posterior produce una corrida nueva, que
-- es precisamente cómo se demuestra que una discrepancia desapareció.
-- ============================================================
create table if not exists elsa.reconciliation_runs (
  id          uuid primary key default gen_random_uuid(),
  asset_id    uuid        not null references elsa.technical_assets (id) on delete restrict,
  version_id  uuid        not null references elsa.engineering_bom_versions (id) on delete restrict,
  snapshot_id uuid        not null references elsa.sap_bom_snapshots (id) on delete restrict,
  created_by  uuid        not null,
  created_at  timestamptz not null default now(),
  stats       jsonb       not null default '{}'::jsonb,
  unique (version_id, snapshot_id)
);

comment on table elsa.reconciliation_runs is
  'Comparación determinística entre una versión de Ingeniería y un snapshot de SAP. Histórica: no se recalcula sobre sí misma.';

create table if not exists elsa.reconciliation_items (
  id                      uuid primary key default gen_random_uuid(),
  run_id                  uuid not null references elsa.reconciliation_runs (id) on delete cascade,
  classification          text not null,
  bom_item_id             uuid references elsa.engineering_bom_items (id) on delete restrict,
  snapshot_item_id        uuid references elsa.sap_snapshot_items (id) on delete restrict,
  component_id            uuid references elsa.components (id) on delete restrict,
  sap_code                text,
  engineering_quantity    numeric,
  sap_quantity            numeric,
  engineering_unit        text,
  sap_unit                text,
  engineering_description text,
  sap_description         text,
  detail                  jsonb not null default '{}'::jsonb,
  constraint ck_reconciliation_classification check (classification in (
    'match',
    'engineering_only',
    'sap_only',
    'quantity_difference',
    'duplicate_or_structural_difference',
    'unresolved'
  )),
  -- Una clasificación siempre se apoya en al menos un lado real.
  constraint ck_reconciliation_has_side
    check (bom_item_id is not null or snapshot_item_id is not null)
);

comment on table elsa.reconciliation_items is
  'Resultado por renglón. Conserva el valor de Ingeniería y el de SAP: ninguna fuente se corrige para «hacerlas coincidir».';

create index if not exists ix_reconciliation_items_by_run
  on elsa.reconciliation_items (run_id, classification);

-- ============================================================
-- REVIEWER_GRANTS
-- Capacidad de Revisor Técnico, separada de la de administrador y con el
-- mismo alcance (dominio + equipo opcional) que los permisos de lectura.
--
-- Deshabilitar un revisor es rellenar `revoked_at`: pierde la capacidad de
-- revisar de inmediato, pero su historial de validaciones permanece intacto,
-- porque borrarlo dejaría aprobaciones huérfanas y sin responsable.
-- ============================================================
create table if not exists elsa.reviewer_grants (
  id               uuid primary key default gen_random_uuid(),
  external_user_id uuid        not null references elsa.accounts (external_user_id) on delete cascade,
  domain           text        not null references elsa.knowledge_domains (code),
  equipment        text,
  granted_by       uuid        not null,
  granted_at       timestamptz not null default now(),
  revoked_by       uuid,
  revoked_at       timestamptz,
  constraint ck_reviewer_equipment_normalized
    check (equipment is null
           or (equipment = lower(btrim(equipment)) and equipment ~ '^[a-z0-9][a-z0-9_-]{0,63}$')),
  constraint ck_reviewer_revocation_consistent
    check ((revoked_at is null) = (revoked_by is null))
);

comment on table elsa.reviewer_grants is
  'Capacidad de Revisor Técnico. No implica administración: un revisor no gestiona usuarios ni seguridad.';

-- Mismos dos índices parciales que `permission_grants`, y por la misma
-- razón: en SQL NULL no es igual a NULL.
create unique index if not exists uq_active_reviewer_on_equipment
  on elsa.reviewer_grants (external_user_id, domain, equipment)
  where revoked_at is null and equipment is not null;

create unique index if not exists uq_active_reviewer_on_domain
  on elsa.reviewer_grants (external_user_id, domain)
  where revoked_at is null and equipment is null;

create index if not exists ix_active_reviewer_grants_by_user
  on elsa.reviewer_grants (external_user_id)
  where revoked_at is null;

-- ============================================================
-- REVIEWS
-- Validaciones técnicas. Estrictamente append-only: aprobar, rechazar y
-- revertir son tres filas nuevas, nunca una modificación de la anterior.
-- Por eso no hay columna «vigente»: la validación vigente de un sujeto es
-- simplemente la de mayor `seq`. Una tabla sin UPDATE no puede mentir
-- sobre su propio pasado.
--
-- `subject_version_id` ata la validación a la versión de información que
-- se evaluó: si una versión posterior cambia ese dato, la aprobación
-- anterior queda histórica y el dato vuelve a revisión.
-- ============================================================
create table if not exists elsa.reviews (
  id                 uuid primary key default gen_random_uuid(),
  seq                bigint generated always as identity unique,
  asset_id           uuid        not null references elsa.technical_assets (id) on delete restrict,
  subject_kind       text        not null,
  subject_id         uuid        not null,
  subject_version_id uuid        references elsa.engineering_bom_versions (id) on delete restrict,
  decision           text        not null,
  comment            text,
  reviewer           uuid        not null,
  decided_at         timestamptz not null default now(),
  reverts_review_id  uuid        references elsa.reviews (id) on delete restrict,
  inherited_from_id  uuid        references elsa.reviews (id) on delete restrict,
  request_id         text,
  constraint ck_review_subject_kind check (subject_kind in (
    'engineering_bom_version',
    'bom_item',
    'failure_mode',
    'drawing_image',
    'reconciliation_item'
  )),
  constraint ck_review_decision check (decision in ('approved', 'rejected', 'reverted')),
  -- Aprobar admite comentario opcional. Rechazar y revertir exigen motivo:
  -- una decisión que cierra o deshace trabajo ajeno tiene que dejar dicho
  -- por qué, y esto lo garantiza la base, no la capa HTTP.
  constraint ck_review_reason_required check (
    decision = 'approved' or (comment is not null and btrim(comment) <> '')
  ),
  -- Revertir siempre apunta a la validación que deshace.
  constraint ck_review_revert_target
    check ((decision = 'reverted') = (reverts_review_id is not null))
);

comment on table elsa.reviews is
  'Historial append-only de validaciones. Ninguna se borra ni se modifica: revertir es una fila nueva que apunta a la anterior.';
comment on column elsa.reviews.inherited_from_id is
  'Validación original reutilizada cuando una versión nueva no cambió el dato. Deja trazabilidad de la herencia.';

create index if not exists ix_reviews_by_subject
  on elsa.reviews (subject_kind, subject_id, seq desc);

create index if not exists ix_reviews_by_version
  on elsa.reviews (subject_version_id, seq desc);

create or replace function elsa.forbid_review_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'elsa.reviews is append-only';
end;
$$;

drop trigger if exists trg_reviews_append_only on elsa.reviews;
create trigger trg_reviews_append_only
  before update or delete on elsa.reviews
  for each row execute function elsa.forbid_review_mutation();

-- ============================================================
-- AUDITORÍA
-- Se amplía el catálogo de operaciones del Bloque 1 con las de este
-- bloque. La migración anterior no se toca: se sustituye la restricción.
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
    'reconciliation_created'
  ));

-- ============================================================
-- DEFENSA EN PROFUNDIDAD
-- Igual que en el Bloque 1: RLS activo y sin políticas, de modo que
-- cualquier rol sin BYPASSRLS obtiene cero filas aunque llegue a
-- conectarse. La autorización real la aplica FastAPI (ADR 0002).
-- ============================================================
do $$
declare
  table_name text;
  role_name text;
begin
  foreach table_name in array array[
    'technical_assets', 'subsystems', 'components', 'component_identifiers',
    'source_artifacts', 'derived_artifacts', 'imports',
    'engineering_bom_versions', 'engineering_bom_items',
    'drawings', 'drawing_images', 'failure_modes', 'sod_criteria', 'option_tables',
    'sap_bom_snapshots', 'sap_snapshot_items',
    'reconciliation_runs', 'reconciliation_items',
    'reviewer_grants', 'reviews'
  ] loop
    execute format('alter table elsa.%I enable row level security', table_name);
  end loop;

  foreach role_name in array array['anon', 'authenticated'] loop
    if exists (select 1 from pg_roles where rolname = role_name) then
      execute format('revoke all on all tables in schema elsa from %I', role_name);
      execute format('revoke all on all functions in schema elsa from %I', role_name);
    end if;
  end loop;
end;
$$;
