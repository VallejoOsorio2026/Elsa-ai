---
name: elsa-migrations
description: Escribir, revisar, probar, aplicar o revertir SQL del esquema de ELSA en supabase/migrations/ y supabase/rollback/. Úsala al crear una migración, al revisar un .sql de este repositorio, ante dudas de RLS, GRANT/REVOKE, vistas, security_invoker, idempotencia o rollback, y siempre antes de tocar un proyecto Supabase remoto (supabase link, db push, db reset). NO la uses para consultas SQL de aplicación en src/elsa/, para el repositorio de permisos en Python, ni para diseñar el modelo documental (eso es elsa-ingestion).
---

# Migraciones de ELSA

La única autoridad del esquema es `supabase/migrations/*.sql` (ADR 0001). No
hay Alembic ni migraciones de ORM. Un cambio hecho a mano en el dashboard de
Supabase **no es válido**: se vuelca a una migración o no existe.

Procedimiento largo y ensayado: `docs/migration-runbook-bloque-2.md`.
Convenciones y flujo local: `docs/development.md` §«Migraciones de base de datos».
No repitas aquí lo que ya está allí: léelo.

## Regla que nunca se relaja

**Ninguna migración se aplica a un proyecto Supabase remoto sin autorización
explícita del responsable en esa misma conversación.** Autorización para una
migración no es autorización para la siguiente.

Antes de cualquier comando que toque un remoto:

1. `supabase projects list` y `supabase status` — confirma **a qué proyecto**
   apunta el enlace. Solo hay un proyecto Supabase remoto de ELSA. El proyecto
   del Asistente de Materiales **nunca** se toca desde este repositorio.
2. Lista lo pendiente y compruébalo contra lo esperado. Si aparece cualquier
   migración que no sea la prevista: responde `N`, detente y reporta.
3. Deja constancia de la salida real del comando. No la resumas.

## Escribir una migración

- Nombre: `supabase/migrations/<YYYYMMDDHHMMSS>_<descripcion_en_ingles>.sql`,
  generado con `supabase migration new <descripcion>`.
- Aplicable sobre base limpia **y** sobre la base existente: `if not exists`
  donde aplique. Hay un test que verifica idempotencia.
- Todo el esquema vive en `elsa`. Comentarios de negocio en español con
  `comment on`, explicando el *porqué* de la restricción.
- Los datos no se borran: revocar es rellenar `revoked_at` / `revoked_by`.
- Las tablas de auditoría son *append-only*, garantizado por disparador.

## RLS, permisos y vistas

El modelo de ELSA es **RLS activo y cero políticas**. En PostgreSQL eso es
negación total para cualquier rol sin `BYPASSRLS`. Es defensa en profundidad,
no el mecanismo de autorización: la autorización vive en FastAPI (ADR 0002).

Por tanto:

- Toda tabla nueva en `elsa`: `alter table ... enable row level security;`
- **No escribas políticas `create policy`** para abrir acceso a `anon` o
  `authenticated`. Si crees que hace falta una, es señal de que estás
  intentando saltarte FastAPI: para y pregunta.
- Revoca sobre los roles de Supabase cuando existan (`anon`, `authenticated`),
  incluyendo `alter default privileges`, siguiendo el patrón del archivo del
  Bloque 1.
- Si creas una **vista** sobre tablas con RLS, decláralas
  `with (security_invoker = true)`. Sin eso la vista se evalúa con los
  privilegios de su dueño y se convierte en una fuga que rodea el RLS.
- Las funciones son `security invoker` por defecto: no las pases a
  `security definer` sin un ADR que lo justifique y un `search_path` fijado.

## Rollback

Cada migración destructiva necesita su par en `supabase/rollback/<mismo_timestamp>_rollback.sql`.

- Vive **fuera** de `supabase/migrations/` a propósito: la CLI no debe
  aplicarlo nunca por su cuenta.
- Se ejecuta a mano, con respaldo previo:
  `supabase db dump --linked --schema elsa -f respaldo-elsa.sql`
- Empieza con `begin;` y documenta en cabecera qué datos destruye.

## Validación antes de decir que funciona

En este orden, y pegando la salida real:

1. Local, desde cero: `supabase db reset` o el PostgreSQL efímero de los tests.
2. `uv run pytest tests/test_migrations.py` y los `test_migrations_*.py` que
   correspondan. Necesitan `ELSA_TEST_DATABASE_URL` (ver `docs/development.md`).
3. Verificación de que RLS quedó activo en **todas** las tablas nuevas.
4. Solo entonces, y solo con autorización, el remoto.

Nunca reportes una migración como aplicada si no has visto la salida del
comando que la aplicó.
