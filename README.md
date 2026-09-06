# ELSA

Asistente corporativo para los ingenieros de mantenimiento de la Planta Molino
Barbosa de PAPELSA. Este repositorio contiene el backend (Python + FastAPI).

El contrato del proyecto —reglas arquitectónicas, stack y decisiones cerradas—
vive en [`CLAUDE.md`](CLAUDE.md). La documentación técnica está en [`docs/`](docs/).

> Estado actual: identidad y permisos (Bloque 1). Sobre la fundación técnica
> del Bloque 0 existen ya la verificación real del JWT de Materiales, el modelo
> de autorización propio de ELSA con migraciones versionadas, la API
> administrativa mínima y el control de abuso. Todavía no hay RAG, LLM,
> documentos, Centro de Control ni interfaz.

**Materiales = identidad. ELSA = autorización.** El Asistente de Materiales
sigue siendo la única fuente de identidad (los usuarios inician sesión una sola
vez, allí); ELSA verifica ese JWT y decide, con su propio modelo, qué puede
consultar cada persona. Ver [ADR 0005](docs/adr/0005-verificacion-real-del-jwt-de-materiales.md)
y [ADR 0006](docs/adr/0006-modelo-minimo-de-autorizacion.md).

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
# estado por dependencia
```

Con la configuración por defecto (`ELSA_AUTH_PROVIDER=fake`,
`ELSA_PERMISSIONS_BACKEND=memory`) el servidor arranca sin ningún servicio
externo, con identidades y permisos en memoria. Ambos adaptadores *fake* solo
se permiten en DEV: en TEST la aplicación se niega a arrancar con ellos.

```bash
# Tokens de prueba del adaptador fake: fake-token-engineer, fake-token-admin
ELSA_DEV_TOKEN=fake-token-engineer

curl -H "Authorization: Bearer $ELSA_DEV_TOKEN" \
     http://127.0.0.1:8000/api/v1/me
# 403: la identidad es válida, pero ELSA todavía no la conoce (default deny)
```

En DEV la documentación interactiva queda en `http://127.0.0.1:8000/docs`.

## Endpoints

| Endpoint | Requiere |
|---|---|
| `GET /api/v1/health/live` · `/ready` | — |
| `GET /api/v1/me` | Identidad válida y cuenta activa en ELSA |
| `GET /api/v1/access/{dominio}` | Permiso sobre el dominio |
| `GET /api/v1/access/{dominio}/{equipo}` | Permiso sobre ese equipo |
| `POST /api/v1/admin/bootstrap` | JWT válido + `X-Bootstrap-Token` |
| `/api/v1/admin/users/...` · `/api/v1/admin/audit` · `/api/v1/admin/assets` | Ser administrador de ELSA |
| `GET /api/v1/knowledge/{dominio}/{activo}` · `/components` · `/failure-modes` | Permiso de lectura sobre el activo |
| `/api/v1/technical/{dominio}/{activo}/...` | Permiso de lectura **y** capacidad de Revisor Técnico |

Las rutas `/access/...` son sondas de autorización: no recuperan conocimiento,
existen para poder verificar la cadena de confianza y desaparecerán cuando
lleguen los endpoints reales. La API administrativa es el mínimo para probar
el modelo; **no** es el Centro de Control.

`/knowledge/...` sirve **solo conocimiento publicado**, sin identificadores
internos, y reporta las diferencias con SAP como una advertencia contada, no
como un informe. `/technical/...` es la API de gobierno: cargar fuentes,
revisar, publicar y reconciliar. Revisar exige poder leer, pero poder leer no
habilita a revisar.

**ELSA no escribe en SAP.** Importa archivos exportados, compara e informa.

Si falta una variable obligatoria, el arranque falla con un mensaje que nombra
la variable afectada: es el comportamiento esperado, no un bug.

## Tests y calidad

```bash
uv run pytest              # suite completa
uv run ruff check .        # lint
uv run ruff format --check .
uv run mypy                # tipos
```

Los tests de migraciones y del repositorio de permisos necesitan una base
PostgreSQL y se omiten si no la hay; ver
[`docs/development.md`](docs/development.md).

Hooks de pre-commit (formato, lint y escaneo de secretos con gitleaks):

```bash
uv run pre-commit install
```

## Documentación

| Documento | Contenido |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Arquitectura, capas y fronteras del sistema |
| [`docs/development.md`](docs/development.md) | Desarrollo local, tests y flujo de migraciones |
| [`docs/security.md`](docs/security.md) | Política de secretos, logs, CORS y fuentes de entrada |
| [`docs/ingestion-contract.md`](docs/ingestion-contract.md) | Qué acepta la ingesta y qué no hace nunca |
| [`docs/private-storage.md`](docs/private-storage.md) | Almacenamiento privado de archivos originales y planos |
| [`docs/private-acceptance-test.md`](docs/private-acceptance-test.md) | Prueba local con archivos reales, sin tocar Git |
| [`docs/environment-variables.md`](docs/environment-variables.md) | Referencia de variables de entorno |
| [`docs/contributing.md`](docs/contributing.md) | Convención de commits y flujo de trabajo |
| [`docs/brand/`](docs/brand/) | Identidad visual PAPELSA: guía de marca, design tokens y reglas de interfaz |
| [`docs/adr/`](docs/adr/) | Decisiones arquitectónicas registradas (ADR) |

## Estructura del repositorio

```
src/elsa/
  main.py          # factory de la aplicación FastAPI
  config.py        # configuración tipada por variables de entorno
  logging.py       # logging JSON + request-id
  api/             # capa HTTP: cadena de confianza, rutas v1 y errores
  core/            # lógica de dominio pura: autorización, salud, emparejamiento,
                   #   versionado, reconciliación y reglas de revisión
  ingestion/       # parsers de XLSX y HTM, independientes de FastAPI
  services/        # orquestación de casos de uso (ingesta, reconciliación)
  tools/           # utilidades de línea de comandos (aceptación privada)
  container.py     # composición: qué adaptador implementa cada puerto
  ports/           # interfaces (Protocol) de dependencias externas
  adapters/        # implementaciones reales y fakes deterministas
supabase/migrations/  # migraciones SQL (autoridad única del esquema)
tests/                # pytest
docs/                 # documentación, ADRs y guía de marca
assets/brand/         # logotipo PAPELSA para la interfaz web (SVG)
```
