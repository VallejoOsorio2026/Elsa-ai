# Arquitectura de ELSA

Este documento describe la arquitectura implementada hasta el Bloque 1 y las
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
  ├─ verifica el JWT contra el JWKS de Materiales (puerto auth)
  ├─ comprueba el perfil vigente en Materiales (puerto materials_identity)
  ├─ aplica los permisos propios de ELSA antes de recuperar nada
  ├─ orquesta recuperación de conocimiento y generación (bloques futuros)
  └─ accede a la base de ELSA con credencial de servicio
        │
        ├──► Supabase Materiales: JWKS + perfil propio  [adaptador real]
        ├──► Supabase ELSA (permisos y auditoría)       [adaptador real]
        ├──► LLM local / autohospedado (puerto llm)     [no configurado aún]
        ├──► Embeddings / OCR / Reranker (puertos)      [no configurados aún]
        └──► Motor de Materiales (puerto materials)     [no configurado aún]
```

**Materiales = identidad. ELSA = autorización.** Materiales dice quién es cada
persona y si sigue habilitada; ELSA decide, por su cuenta y con su propio
modelo, qué puede consultar. Ver [ADR 0005](adr/0005-verificacion-real-del-jwt-de-materiales.md)
y [ADR 0006](adr/0006-modelo-minimo-de-autorizacion.md).

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
| `materials_identity` | `MaterialsIdentityPort.get_own_profile` | Perfil vigente del usuario en Materiales (tabla `perfiles`) |
| `permissions` | `PermissionsRepositoryPort` | Modelo de autorización de ELSA (Supabase ELSA) |
| `abuse` | `AbuseGuardPort.acquire` / `release` | Control de abuso por usuario |
| `llm` | `LLMPort.complete` | Modelo de lenguaje local / autohospedado |
| `embeddings` | `EmbeddingsPort.embed` + `dimension` | Modelo de embeddings |
| `ocr` | `OCRPort.extract_text` | Extracción de texto de documentos |
| `reranker` | `RerankerPort.rerank` | Reordenamiento de candidatos por relevancia |
| `materials` | `MaterialsPort.get_material` / `search_materials` | Motor del Asistente de Materiales (sin duplicar su inventario) |

Cada puerto tiene un adaptador *fake* determinista usado por los tests de
contrato (`tests/test_contract_*.py`). Un puerto sin adaptador real no es deuda
técnica: es el diseño previsto (CLAUDE.md, sección 5).

Adaptadores reales existentes (Bloque 1):

| Adaptador | Puerto | Qué hace |
|---|---|---|
| `SupabaseJwtAuthAdapter` | `auth` | Verifica el JWT con el JWKS de Materiales (o con secreto simétrico si el proyecto lo exige) |
| `SupabaseMaterialsIdentityAdapter` | `materials_identity` | Lee el perfil propio en PostgREST con el JWT del usuario |
| `PostgresPermissionsRepository` | `permissions` | Modelo de autorización y auditoría en Supabase ELSA |
| `InMemoryAbuseGuard` | `abuse` | Límites por usuario dentro del proceso |

Los adaptadores `fake` de `auth`, `materials_identity` y `permissions` **solo
se permiten en DEV**: la configuración se niega a arrancar con ellos en TEST.

## Cadena de confianza

`src/elsa/api/deps.py` impone un orden que no admite excepciones. Ningún
endpoint protegido puede saltárselo, porque la autorización es una dependencia
de FastAPI que se resuelve **antes** del cuerpo del handler:

```
1. Autenticar   Authorization: Bearer → verificar firma, exp, iss, aud, alg
2. Admitir      control de abuso sobre el usuario ya identificado
3. Vigencia     el perfil sigue activo en Materiales (fuente autoritativa)
4. Autorizar    cuenta activa en ELSA + permiso que cubra el alcance pedido
5. Endpoint     recién aquí se hace el trabajo
```

Nunca se recupera algo para después ocultarlo: una fuente no autorizada no
llega a entrar en el conjunto de recuperación. El LLM no participa en ninguno
de los cinco pasos.

## Modelo de autorización

`src/elsa/core/authorization.py` decide, sin conocer HTTP ni SQL:

- **DEFAULT DENY**: sin cuenta activa en ELSA y sin permiso explícito, se
  niega.
- El administrador de ELSA tiene acceso total.
- Un permiso de dominio (`equipment` vacío) cubre el dominio y cualquiera de
  sus equipos.
- Un permiso de equipo cubre **solo** ese equipo.
- Los alcances se normalizan (`Tampella` → `tampella`); son dato, no
  constantes de código.

El detalle del esquema está en [ADR 0006](adr/0006-modelo-minimo-de-autorizacion.md)
y en `supabase/migrations/`.

## Endpoints

| Endpoint | Requiere | Devuelve |
|---|---|---|
| `GET /api/v1/health/live` | — | El proceso responde |
| `GET /api/v1/health/ready` | — | Estado por dependencia |
| `GET /api/v1/me` | Identidad válida + cuenta activa en ELSA | Identificador externo, nombre, estado, si es administrador y alcances autorizados |
| `GET /api/v1/access/{domain}` | Permiso sobre el dominio | Sonda de autorización |
| `GET /api/v1/access/{domain}/{equipment}` | Permiso sobre ese equipo | Sonda de autorización |
| `POST /api/v1/admin/bootstrap` | JWT válido + `X-Bootstrap-Token` | Declara al primer administrador |
| `GET /api/v1/admin/users/{id}` | Administrador | Cuenta y permisos vigentes |
| `POST /api/v1/admin/users/{id}/grants` | Administrador | Otorga un permiso |
| `POST /api/v1/admin/users/{id}/grants/revoke` | Administrador | Revoca un permiso |
| `POST /api/v1/admin/users/{id}/status` | Administrador | Habilita o deshabilita en ELSA |
| `POST /api/v1/admin/users/{id}/admin` | Administrador | Otorga o retira la administración |
| `GET /api/v1/admin/audit` | Administrador | Auditoría de cambios administrativos |

Las sondas `/access/...` no recuperan conocimiento: existen para poder
verificar la cadena de confianza de forma observable y desaparecerán cuando
lleguen los endpoints reales. La API administrativa es el mínimo para probar
el modelo; **no** es el Centro de Control.

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

Dependencias críticas: `auth` (el proveedor de identidad) y `database` (el
almacén de permisos). Con el adaptador real configurado y el JWKS de
Materiales inaccesible, readiness responde 503: sin proveedor de identidad
ELSA no puede autorizar a nadie. `/health/live` no depende de nada y sigue
respondiendo 200. Con los adaptadores *fake* de DEV, ambas se reportan como
`degraded`: sirven para desarrollar, no para operar.

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
- Códigos de identidad y autorización: `unauthorized` (401),
  `account_disabled` (403, el perfil no está habilitado en Materiales),
  `elsa_access_denied` (403, sin cuenta activa en ELSA),
  `insufficient_permissions` (403, el alcance no está autorizado),
  `too_many_requests` (429, con `Retry-After`),
  `identity_provider_unavailable` y `permissions_store_unavailable` (503).
  Un fallo técnico **nunca** se convierte en 401.
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

`ELSA_ENV` selecciona el ambiente lógico (`DEV` | `TEST`). Hay **un único**
proyecto Supabase remoto de ELSA: DEV trabaja con configuración local, fakes
y/o una base local, y TEST es el que usa el proyecto remoto. La configuración
impone esa separación: los adaptadores `fake` y el almacén de permisos en
memoria solo son válidos en DEV. La documentación interactiva (`/docs`) solo se expone
en DEV. CORS se declara explícitamente por ambiente, sin comodines.

## Qué no existe todavía (a propósito)

RAG, LLM real, OCR, embeddings, reranking, agentes, UI, tablas de documentos,
integración con el motor de búsqueda de Materiales, IH06/IW13, Centro de
Control y despliegue. Los bloques 0 y 1 dejan las fronteras preparadas
(puertos, health por dependencia, migraciones versionadas, cadena de confianza
y modelo de permisos) para que esos componentes lleguen sin romper la
arquitectura.
