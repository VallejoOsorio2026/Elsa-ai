# Arquitectura de ELSA

Este documento describe la arquitectura implementada hasta el Bloque 0 y las
fronteras previstas del sistema. Las reglas innegociables viven en
[`CLAUDE.md`](../CLAUDE.md); las decisiones cerradas, en [`docs/adr/`](adr/).

## Visión general

ELSA es un asistente corporativo para ingenieros de mantenimiento. El backend
(este repositorio) es la frontera principal del sistema: el navegador nunca se
comunica directamente con el LLM ni con la base de datos.

```
Frontend (elsa-ai.link)
        │  HTTPS + JWT (emitido por Supabase de Materiales)
        ▼
FastAPI (este repositorio)
  ├─ valida identidad (puerto auth) y aplica permisos propios de ELSA
  ├─ orquesta recuperación de conocimiento y generación (bloques futuros)
  └─ accede a la base de ELSA con credencial de servicio
        │
        ├──► Supabase ELSA (PostgreSQL + pgvector)     [no configurado aún]
        ├──► LLM local / autohospedado (puerto llm)    [no configurado aún]
        ├──► Embeddings / OCR / Reranker (puertos)     [no configurados aún]
        └──► Asistente de Materiales (puerto materials)[no configurado aún]
```

## Capas

| Capa | Ubicación | Responsabilidad |
|---|---|---|
| API | `src/elsa/api/` | HTTP: rutas versionadas (`/api/v1`), formato de error estándar, esquemas de respuesta |
| Dominio | `src/elsa/core/` | Lógica de negocio; importa puertos, nunca adaptadores |
| Puertos | `src/elsa/ports/` | Interfaces (`Protocol`) de toda dependencia externa reemplazable |
| Adaptadores | `src/elsa/adapters/` | Implementaciones concretas de los puertos; hoy solo *fakes* deterministas |
| Transversal | `config.py`, `logging.py`, `main.py` | Configuración validada, logging JSON con request-id, ensamblaje de la app |

Reglas de dependencia entre capas:

- `api` y `core` importan `ports`, nunca `adapters`.
- Los adaptadores reales se seleccionarán por configuración en `main.py`
  (composición), no por import directo desde el negocio.
- `core` no conoce FastAPI ni HTTP.

## Puertos definidos

| Puerto | Interfaz | Dependencia que abstrae |
|---|---|---|
| `auth` | `AuthPort.verify_token` | Verificación del JWT emitido por el Supabase de Materiales |
| `llm` | `LLMPort.complete` | Modelo de lenguaje local / autohospedado |
| `embeddings` | `EmbeddingsPort.embed` + `dimension` | Modelo de embeddings |
| `ocr` | `OCRPort.extract_text` | Extracción de texto de documentos |
| `reranker` | `RerankerPort.rerank` | Reordenamiento de candidatos por relevancia |
| `materials` | `MaterialsPort.get_material` / `search_materials` | Motor del Asistente de Materiales (sin duplicar su inventario) |

Cada puerto tiene un adaptador *fake* determinista usado por los tests de
contrato (`tests/test_contract_*.py`). Un puerto sin adaptador real no es deuda
técnica: es el diseño previsto (CLAUDE.md, sección 5).

## Health check en dos niveles

- `GET /api/v1/health/live`: el proceso responde. Sin dependencias. Siempre
  `200 {"status": "ok"}` mientras el proceso viva.
- `GET /api/v1/health/ready`: estado por dependencia y estado agregado.

Semántica del estado agregado (`src/elsa/core/health.py`):

| Situación | Estado | HTTP |
|---|---|---|
| Todas las dependencias `ok` | `ok` | 200 |
| Alguna dependencia no crítica caída o sin configurar | `degraded` | 200 |
| Alguna dependencia **crítica** caída | `down` | 503 |

Esta distinción hace cumplible la regla 14 de CLAUDE.md: con el LLM fuera de
servicio el sistema se reporta *degradado* y sigue sirviendo lo que no depende
de él, en lugar de declararse caído. Hoy (Bloque 0) ninguna dependencia tiene
adaptador real, así que todas reportan `not_configured` y el sistema queda
`degraded` de forma esperada. Una dependencia crítica *sin configurar* degrada
pero no tumba: `down` queda reservado a fallos reales de operación.

## Formato de error estándar

Toda respuesta de error de la API (`src/elsa/api/errors.py`) tiene la forma:

```json
{
  "error": {
    "code": "not_found",
    "message": "Not Found",
    "request_id": "6f9d3a4e-...",
    "details": [{"field": "query.number", "message": "..."}]
  }
}
```

- `code` es estable y apto para lógica del cliente; `message` es legible.
- `details` solo aparece en errores de validación y describe la request del
  cliente, nunca el interior del servidor.
- Los errores no controlados devuelven `internal_error` con mensaje genérico;
  la traza completa queda en el log del servidor, asociada al `request_id`.

## Trazabilidad de requests

Un middleware (`src/elsa/logging.py`) asigna a cada request un identificador:
respeta un `X-Request-ID` entrante bien formado o genera un UUID4. El
identificador viaja en un `ContextVar`, aparece en todos los logs emitidos
durante la request y se devuelve en la cabecera `X-Request-ID` de la
respuesta. Los logs son JSON estructurado (una línea por evento).

## Ambientes

`ELSA_ENV` selecciona el ambiente lógico (`DEV` | `TEST`). DEV y TEST serán
proyectos Supabase distintos (ADR 0002 y CLAUDE.md sección 4); ningún ambiente
comparte base con otro. La documentación interactiva (`/docs`) solo se expone
en DEV. CORS se declara explícitamente por ambiente, sin comodines.

## Qué no existe todavía (a propósito)

RAG, LLM real, OCR, embeddings, reranking, agentes, UI, tablas de negocio,
integración con Materiales y despliegue. El Bloque 0 deja las fronteras
preparadas (puertos, health por dependencia, migraciones versionadas) para que
esos componentes lleguen sin romper la arquitectura.
