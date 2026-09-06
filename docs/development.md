# Desarrollo local

## Requisitos

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/). Gestiona
  dependencias y descarga automáticamente Python 3.12 (fijado en
  `.python-version`); no necesitas instalar Python por tu cuenta.
- `git`.

## Primer arranque

```bash
git clone https://github.com/VallejoOsorio2026/Elsa-ai.git
cd Elsa-ai
uv sync                      # crea .venv e instala dependencias exactas (uv.lock)
cp .env.example .env         # configuración local, sin secretos
uv run uvicorn elsa.main:create_app --factory --reload
```

La aplicación valida la configuración al arrancar. Si falta una variable
obligatoria verás un `ConfigurationError` que nombra la variable exacta; es el
comportamiento diseñado (fallo claro, no arranque a medias).

Endpoints disponibles:

- `http://127.0.0.1:8000/api/v1/health/live`
- `http://127.0.0.1:8000/api/v1/health/ready`
- `http://127.0.0.1:8000/docs` (solo en DEV)

Con la configuración por defecto (`ELSA_AUTH_PROVIDER=fake`,
`ELSA_PERMISSIONS_BACKEND=memory`) el servidor arranca sin ningún servicio
externo: las identidades y los permisos viven en memoria.

```bash
# Tokens de prueba del adaptador fake: fake-token-engineer, fake-token-admin
ELSA_DEV_TOKEN=fake-token-engineer

curl -H "Authorization: Bearer $ELSA_DEV_TOKEN" \
     http://127.0.0.1:8000/api/v1/me
# 403: la identidad es válida, pero ELSA todavía no la conoce (default deny)
```

Ambos adaptadores *fake* **solo** funcionan en DEV: con `ELSA_ENV=TEST` la
aplicación se niega a arrancar con ellos.

## Levantar el primer administrador

1. Configura `ELSA_BOOTSTRAP_ADMIN_TOKEN` con un valor aleatorio
   (`openssl rand -hex 32`) en tu `.env`.
2. Inicia sesión en Materiales y usa **tu propio** JWT:

   ```bash
   curl -X POST http://127.0.0.1:8000/api/v1/admin/bootstrap \
        -H "Authorization: Bearer <tu JWT de Materiales>" \
        -H "X-Bootstrap-Token: <el valor de ELSA_BOOTSTRAP_ADMIN_TOKEN>"
   ```

   El UUID que se promueve es el del usuario autenticado: no se escribe a
   mano en ningún sitio.
3. Borra `ELSA_BOOTSTRAP_ADMIN_TOKEN` o déjala sin valor: ambas cosas
   deshabilitan el endpoint. A partir de aquí, la administración se otorga y
   se transfiere con `POST /api/v1/admin/users/{id}/admin`.

## Ciclo de trabajo

```bash
uv run pytest                  # tests
uv run ruff check .            # lint
uv run ruff format .           # formato
uv run mypy                    # tipos (modo no estricto)
uv run pre-commit install      # hooks de commit (una sola vez por clon)
uv run pre-commit run --all-files   # ejecutar todos los hooks a demanda
```

### Tests que necesitan PostgreSQL

Los tests de las migraciones y del repositorio de permisos corren contra una
base real. Se **omiten** si no está definida `ELSA_TEST_DATABASE_URL`, de modo
que `uv run pytest` funciona en un clon limpio sin base de datos:

```bash
docker run --rm -d -p 5432:5432 \
  -e POSTGRES_USER=elsa -e POSTGRES_PASSWORD=elsa -e POSTGRES_DB=elsa_test \
  --name elsa-pg postgres:16

ELSA_TEST_DATABASE_URL=postgresql://elsa:elsa@127.0.0.1:5432/elsa_test uv run pytest
```

Cada test parte de un esquema recreado aplicando las migraciones del
repositorio: es también la prueba de que el esquema es reproducible. **Nunca**
se apunta al Supabase real; en CI es un contenedor efímero.

CI (GitHub Actions, `.github/workflows/ci.yml`) ejecuta lint, formato, mypy,
tests y escaneo de secretos en cada push y pull request. `uv sync --locked`
garantiza que el lockfile esté al día: si cambias dependencias en
`pyproject.toml`, ejecuta `uv sync` y versiona el `uv.lock` resultante.

## Dependencias

- Añadir: `uv add <paquete>` (runtime) o `uv add --group dev <paquete>`.
- Quitar: `uv remove <paquete>`.
- Nunca edites `uv.lock` a mano.

## Migraciones de base de datos

La única autoridad del esquema de ELSA son los archivos SQL bajo
`supabase/migrations/` (ADR 0001). No se usa Alembic ni migraciones de ORM, y
los cambios manuales en el dashboard de Supabase no son válidos: todo cambio
se vuelca a una migración versionada.

### Convención de nombres

```
supabase/migrations/<YYYYMMDDHHMMSS>_<descripcion_en_ingles>.sql
```

Ejemplo: `supabase/migrations/20261015093000_create_permissions_tables.sql`.
Es el formato que genera el CLI de Supabase; el timestamp ordena la aplicación
de las migraciones.

### Flujo

1. Crear la migración con el CLI (genera el archivo con timestamp):

   ```bash
   supabase migration new <descripcion_en_ingles>
   ```

2. Escribir el SQL en el archivo generado. Cada migración debe ser aplicable
   sobre una base limpia y sobre la base existente (idempotencia razonable:
   `if not exists` donde aplique).
3. Probar contra una base local o el proyecto DEV:

   ```bash
   supabase db reset      # aplica todas las migraciones desde cero (local)
   # o
   supabase db push       # aplica pendientes al proyecto enlazado
   ```

4. Versionar el `.sql` en el mismo pull request que el código que lo necesita.

### Estado actual

`supabase/migrations/` contiene el modelo de autorización del Bloque 1
(esquema `elsa`: cuentas, dominios, permisos y auditoría). Está probado
aplicándolo sobre un PostgreSQL limpio (ver arriba), pero **todavía no se ha
aplicado a ningún proyecto Supabase remoto**: ese proyecto aún no está
enlazado. Para enlazarlo hace falta el *project ref* del proyecto Supabase de
ELSA (un dato no sensible) y entonces:

```bash
supabase link --project-ref <ref del proyecto ELSA>
supabase db push
```

Solo hay **un** proyecto Supabase remoto de ELSA. DEV trabaja con
configuración local (fakes o una base local); TEST es el que usa el proyecto
remoto.

## Estructura del repositorio

Ver el árbol comentado en el [`README.md`](../README.md) y la descripción de
capas en [`architecture.md`](architecture.md).
