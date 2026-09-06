-- ============================================================
-- Modelo mínimo de autorización de ELSA (Bloque 1)
--
-- Materiales = identidad. ELSA = autorización.
--
-- La identidad de un usuario la emite el Supabase del Asistente de
-- Materiales; aquí solo se guarda su UUID (`auth.users.id` de aquel
-- proyecto) como referencia externa. No hay clave foránea posible entre
-- dos proyectos Supabase distintos, y no se duplican credenciales.
--
-- Todo vive en el esquema `elsa`, no en `public`: PostgREST solo expone
-- los esquemas declarados en la configuración de la API (por defecto
-- `public`), de modo que estas tablas no quedan alcanzables desde el
-- navegador. La autorización real la aplica FastAPI (ADR 0002); RLS y los
-- REVOKE de más abajo son defensa en profundidad, no el mecanismo.
-- ============================================================

create schema if not exists elsa;

comment on schema elsa is
  'Modelo propio de ELSA. No se expone por PostgREST: solo lo usa el backend.';

-- ============================================================
-- ACCOUNTS
-- Asocia un usuario externo de Materiales con ELSA y define si está
-- activo dentro de ELSA y si es administrador. Los usuarios no se
-- borran: se desactivan, para que la auditoría nunca quede huérfana.
-- ============================================================
create table if not exists elsa.accounts (
  external_user_id uuid primary key,
  display_name     text,
  is_active        boolean     not null default true,
  is_admin         boolean     not null default false,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

comment on table elsa.accounts is
  'Usuarios de Materiales habilitados en ELSA. DEFAULT DENY: sin fila aquí no hay acceso.';
comment on column elsa.accounts.external_user_id is
  'UUID del usuario en el Supabase Auth de Materiales (claim `sub` del JWT).';
comment on column elsa.accounts.is_admin is
  'Administrador de ELSA: acceso total. Puede haber varios y es transferible.';

-- ============================================================
-- KNOWLEDGE_DOMAINS
-- Catálogo de dominios de conocimiento. Los alcances son dato, no
-- constantes de código: añadir un dominio es un INSERT, no un despliegue.
-- ============================================================
create table if not exists elsa.knowledge_domains (
  code       text primary key,
  label      text        not null,
  is_active  boolean     not null default true,
  created_at timestamptz not null default now(),
  constraint ck_domain_code_normalized
    check (code = lower(btrim(code)) and code ~ '^[a-z0-9][a-z0-9_-]{0,63}$')
);

comment on table elsa.knowledge_domains is
  'Dominios de conocimiento de ELSA. Evita otorgar permisos sobre alcances inexistentes.';

insert into elsa.knowledge_domains (code, label) values
  ('mantenimiento', 'Mantenimiento'),
  ('materiales',    'Materiales')
on conflict (code) do nothing;

-- ============================================================
-- PERMISSION_GRANTS
-- Autorización efectiva, otorgada directamente por usuario. Los roles
-- podrán existir después como plantillas administrativas, pero la
-- autoridad final es esta tabla.
--
-- Jerarquía prevista: dominio → planta → área/ubicación → equipo →
-- tipo de información. En este bloque solo existen DOMINIO y EQUIPO.
-- Los niveles restantes se añadirán como columnas nullable adicionales
-- sin destruir lo implementado: una fila con columnas nuevas en NULL
-- conserva exactamente el significado que tiene hoy («todo el nivel»).
--
-- `equipment IS NULL` significa acceso a todo el dominio.
--
-- Las filas no se borran: revocar es rellenar `revoked_at`/`revoked_by`,
-- de modo que el historial de quién otorgó y quién revocó se conserva.
-- ============================================================
create table if not exists elsa.permission_grants (
  id               uuid primary key default gen_random_uuid(),
  external_user_id uuid        not null references elsa.accounts (external_user_id) on delete cascade,
  domain           text        not null references elsa.knowledge_domains (code),
  equipment        text,
  granted_by       uuid        not null,
  granted_at       timestamptz not null default now(),
  revoked_by       uuid,
  revoked_at       timestamptz,
  constraint ck_equipment_normalized
    check (equipment is null
           or (equipment = lower(btrim(equipment)) and equipment ~ '^[a-z0-9][a-z0-9_-]{0,63}$')),
  constraint ck_revocation_consistent
    check ((revoked_at is null) = (revoked_by is null))
);

comment on table elsa.permission_grants is
  'Permisos por usuario. Perder un permiso (revoked_at) impide toda recuperación posterior de ese conocimiento.';
comment on column elsa.permission_grants.equipment is
  'Equipo concreto (p. ej. tampella) o NULL para todo el dominio. Es dato, nunca constante de código.';
comment on column elsa.permission_grants.granted_by is
  'UUID externo del administrador que otorgó el permiso.';

-- Un solo permiso activo por (usuario, dominio, equipo). Hacen falta dos
-- índices porque en SQL NULL no es igual a NULL: el segundo cubre el
-- permiso de dominio completo.
create unique index if not exists uq_active_grant_on_equipment
  on elsa.permission_grants (external_user_id, domain, equipment)
  where revoked_at is null and equipment is not null;

create unique index if not exists uq_active_grant_on_domain
  on elsa.permission_grants (external_user_id, domain)
  where revoked_at is null and equipment is null;

create index if not exists ix_active_grants_by_user
  on elsa.permission_grants (external_user_id)
  where revoked_at is null;

-- ============================================================
-- ADMIN_AUDIT_LOG
-- Auditoría de cambios administrativos: quién (actor), sobre quién
-- (subject), qué operación, sobre qué alcance y cuándo.
--
-- Append-only por trigger: ni siquiera la credencial de servicio puede
-- modificar o borrar una entrada. Un registro que puede reescribirse no
-- es auditoría.
-- ============================================================
create table if not exists elsa.admin_audit_log (
  id                       bigint generated always as identity primary key,
  actor_external_user_id   uuid,
  subject_external_user_id uuid        not null,
  operation                text        not null,
  scope_domain             text,
  scope_equipment          text,
  request_id               text,
  details                  jsonb       not null default '{}'::jsonb,
  occurred_at              timestamptz not null default now(),
  constraint ck_audit_operation check (operation in (
    'bootstrap_admin',
    'create_account',
    'grant_permission',
    'revoke_permission',
    'enable_user',
    'disable_user',
    'promote_admin',
    'demote_admin'
  ))
);

comment on table elsa.admin_audit_log is
  'Auditoría append-only de cambios administrativos. No registra el uso normal del asistente.';
comment on column elsa.admin_audit_log.actor_external_user_id is
  'Administrador que ejecutó la operación. En el bootstrap es el propio interesado. NULL queda reservado a operaciones del sistema.';
comment on column elsa.admin_audit_log.request_id is
  'X-Request-ID de la petición que originó el cambio, para correlacionar con los logs.';

create index if not exists ix_audit_by_subject
  on elsa.admin_audit_log (subject_external_user_id, occurred_at desc);

create or replace function elsa.forbid_audit_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'elsa.admin_audit_log is append-only';
end;
$$;

drop trigger if exists trg_admin_audit_log_append_only on elsa.admin_audit_log;
create trigger trg_admin_audit_log_append_only
  before update or delete on elsa.admin_audit_log
  for each row execute function elsa.forbid_audit_mutation();

-- ============================================================
-- updated_at automático en accounts
-- ============================================================
create or replace function elsa.touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

drop trigger if exists trg_accounts_touch_updated_at on elsa.accounts;
create trigger trg_accounts_touch_updated_at
  before update on elsa.accounts
  for each row execute function elsa.touch_updated_at();

-- ============================================================
-- DEFENSA EN PROFUNDIDAD
--
-- RLS activo y sin ninguna política: cualquier rol que no tenga
-- BYPASSRLS obtiene cero filas aunque llegue a conectarse. La
-- credencial de servicio del backend sí las ve; el navegador no debe
-- llegar hasta aquí en ningún caso.
--
-- Los REVOKE se aplican solo si los roles de Supabase existen, para que
-- estas migraciones también corran sobre un PostgreSQL limpio (tests).
-- ============================================================
alter table elsa.accounts           enable row level security;
alter table elsa.knowledge_domains  enable row level security;
alter table elsa.permission_grants  enable row level security;
alter table elsa.admin_audit_log    enable row level security;

do $$
declare
  role_name text;
begin
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
