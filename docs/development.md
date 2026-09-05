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

## Ciclo de trabajo

```bash
uv run pytest                  # tests
uv run ruff check .            # lint
uv run ruff format .           # formato
uv run mypy                    # tipos (modo no estricto)
uv run pre-commit install      # hooks de commit (una sola vez por clon)
uv run pre-commit run --all-files   # ejecutar todos los hooks a demanda
```

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

En el Bloque 0 el directorio está vacío a propósito: no existe todavía ninguna
tabla de ELSA. `supabase init` / `supabase link` (que generan la configuración
local del CLI) se ejecutarán cuando llegue la primera migración real, contra
los proyectos DEV y TEST descritos en CLAUDE.md.

## Estructura del repositorio

Ver el árbol comentado en el [`README.md`](../README.md) y la descripción de
capas en [`architecture.md`](architecture.md).
