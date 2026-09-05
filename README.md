# ELSA

Asistente corporativo para los ingenieros de mantenimiento de la Planta Molino
Barbosa de PAPELSA. Este repositorio contiene el backend (Python + FastAPI).

El contrato del proyecto —reglas arquitectónicas, stack y decisiones cerradas—
vive en [`CLAUDE.md`](CLAUDE.md). La documentación técnica está en [`docs/`](docs/).

> Estado actual: fundación técnica (Bloque 0). Existen la API de health check,
> la configuración validada, los puertos con adaptadores *fake* y la cadena de
> calidad/CI. Todavía no hay RAG, LLM, base de datos ni interfaz.

## Requisitos

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) (gestiona las
  dependencias **y** descarga automáticamente Python 3.12; no necesitas tenerlo
  instalado).
- `git`.

## Puesta en marcha

```bash
git clone https://github.com/VallejoOsorio2026/Elsa-ai.git
cd Elsa-ai

# 1. Instala dependencias (crea .venv con Python 3.12)
uv sync

# 2. Crea tu configuración local (sin secretos; ver docs/environment-variables.md)
cp .env.example .env

# 3. Levanta el servidor de desarrollo
uv run uvicorn elsa.main:create_app --factory --reload
```

Comprueba que responde:

```bash
curl http://127.0.0.1:8000/api/v1/health/live
# {"status":"ok"}

curl http://127.0.0.1:8000/api/v1/health/ready
# estado por dependencia; hoy todas reportan "not_configured"
```

En DEV la documentación interactiva queda en `http://127.0.0.1:8000/docs`.

Si falta una variable obligatoria, el arranque falla con un mensaje que nombra
la variable afectada: es el comportamiento esperado, no un bug.

## Tests y calidad

```bash
uv run pytest              # suite completa
uv run ruff check .        # lint
uv run ruff format --check .
uv run mypy                # tipos
```

Hooks de pre-commit (formato, lint y escaneo de secretos con gitleaks):

```bash
uv run pre-commit install
```

## Documentación

| Documento | Contenido |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Arquitectura, capas y fronteras del sistema |
| [`docs/development.md`](docs/development.md) | Desarrollo local, tests y flujo de migraciones |
| [`docs/security.md`](docs/security.md) | Política de secretos, logs y CORS |
| [`docs/environment-variables.md`](docs/environment-variables.md) | Referencia de variables de entorno |
| [`docs/contributing.md`](docs/contributing.md) | Convención de commits y flujo de trabajo |
| [`docs/adr/`](docs/adr/) | Decisiones arquitectónicas registradas (ADR) |

## Estructura del repositorio

```
src/elsa/
  main.py          # factory de la aplicación FastAPI
  config.py        # configuración tipada por variables de entorno
  logging.py       # logging JSON + request-id
  api/             # capa HTTP: rutas v1 y formato de error estándar
  core/            # lógica de dominio (hoy: modelo de salud)
  ports/           # interfaces (Protocol) de dependencias externas
  adapters/        # implementaciones; hoy solo fakes deterministas
supabase/migrations/  # migraciones SQL (autoridad única del esquema)
tests/                # pytest
docs/                 # documentación y ADRs
```
