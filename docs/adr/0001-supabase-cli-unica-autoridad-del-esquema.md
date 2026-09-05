# ADR 0001 — Supabase CLI como única autoridad del esquema

## Estado

Aceptado (2026-09-04).

## Contexto

ELSA usa PostgreSQL gestionado por Supabase, con ambientes DEV y TEST en
proyectos separados. El proyecto será entregado a PAPELSA: cualquier persona
debe poder reconstruir la base de datos desde el repositorio, sin acceso a
las conversaciones ni a los dashboards que la produjeron. Existen varias vías
posibles para definir el esquema (dashboard de Supabase, un ORM con
migraciones generadas como Alembic/SQLModel, SQL versionado), y mezclarlas
produce esquemas irreproducibles y divergencia silenciosa entre ambientes.

## Decisión

La única autoridad del esquema de la base de datos de ELSA son los archivos
SQL versionados bajo `supabase/migrations/`, gestionados con el CLI de
Supabase y su convención de nombres (`<YYYYMMDDHHMMSS>_<descripcion>.sql`).

- No se usa Alembic ni migraciones generadas por ORM.
- Los cambios hechos a mano en el dashboard de Supabase no son válidos: si
  ocurren, deben volcarse a una migración versionada para existir.
- Toda estructura de base de datos es reproducible aplicando las migraciones
  en orden sobre una base limpia.

## Consecuencias

- Un clon del repositorio contiene todo lo necesario para reconstruir el
  esquema de cualquier ambiente (`supabase db reset` / `db push`).
- DEV y TEST convergen por construcción: ambos reciben exactamente los mismos
  archivos de migración.
- El precio es escribir SQL a mano y cuidar el orden y la compatibilidad de
  cada migración; el flujo está documentado en `docs/development.md`.
- Las revisiones de cambios de esquema ocurren en el pull request, sobre SQL
  explícito, lo que facilita la auditoría de seguridad.
