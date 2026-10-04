# Integración ELSA → Materiales V1

Cómo ELSA consulta la **disponibilidad de un código exacto** en el inventario de
Materiales, con qué identidad lo hace, cómo se valida y cómo se prueba contra
la fuente real.

Alcance: una sola vertical. Si la pregunta trae un código exacto, la respuesta
suma el bloque `availability` con lo que Materiales devuelve **en vivo**. No hay
búsqueda por texto en Materiales (no está habilitada en el contrato V1), ni
acceso remoto, ni login propio de ELSA: esos son bloques aparte.

## 1. Qué hace

```
Página ELSA ──Bearer──▶ POST /api/v1/assistant/{domain}/{asset}/ask   (FastAPI)
                          │  autenticación → permisos → resolve_asset   (sin cambios)
                          ├─ búsqueda literal en el BOM publicado        (sin cambios)
                          └─ ¿código exacto sin ambigüedad?
                               sí ─▶ SupabaseMaterialsGateway.for_token(JWT del usuario)
                                      └─ HTTPS/PostgREST ─▶ Materiales
                                         elsa_v1_get_contract_descriptor  (1.ª vez / cada 10 min)
                                         elsa_v1_lookup_material_by_code
                               no ─▶ no se llama a Materiales
```

- El bloque `availability` es **aditivo**: el BOM responde exactamente igual con
  o sin él, y si Materiales falla el bloque lo declara y el resto sigue.
- Todos los hechos del bloque salen del contrato de Materiales. Ningún modelo los
  redacta ni los completa (el chat no usa LLM).
- Código: `adapters/supabase_materials.py` (transporte e interpretación),
  `core/material_code.py` (cuándo hay un código exacto), `api/v1/assistant.py`
  (composición del bloque), `web/js/screens/chat.js` (presentación).

## 2. Cuándo se consulta un código

`core/material_code.py`, sin normalizar jamás el código:

- Un código es una corrida de **6 a 18 dígitos ASCII** que no forma parte de otra
  palabra ni de un número con separadores (`SYN-100003`, `A1234567`, `1.500000`
  no lo son).
- Solo cuenta si la pregunta lo pide: trae una palabra de inventario (material,
  código, disponibilidad, stock, existencias, inventario) o el mensaje es solo
  el código.
- **Más de un código distinto** es ambiguo: no se consulta ninguno.
- El texto libre (`rodamiento SKF`) **nunca** se envía como código.
- Limitación conocida: los códigos alfanuméricos no se detectan (el dominio
  observado del Piloto Tampella es numérico, ADR 0024 §10).

El código viaja **tal cual se escribió**: `000123` llega como `"000123"`. Sin
`strip`, sin ceros añadidos ni quitados, sin conversión numérica (M3-A, ADR 0024
§8).

## 3. Autenticación

No hay credencial nueva ni login nuevo.

- El JWT que la página ya envía a ELSA **es** el de Supabase Auth de Materiales:
  ELSA lo valida contra su JWKS e issuer (ADR 0005) y ya lo reenvía a Materiales
  para comprobar el perfil (ADR 0002).
- La consulta de inventario reutiliza ese mismo token, con la clave publicable
  (`ELSA_MATERIALS_API_KEY`) en `apikey`. El ACL de Materiales solo da `EXECUTE`
  a `authenticated`: **sin `service_role`**, sin contraseña guardada, sin
  PostgreSQL directo.
- **El token vive solo en la petición.** `SupabaseMaterialsGateway` (compartido)
  guarda el cliente HTTP, la configuración y la caché del descriptor, y **nunca
  un token**. Por petición se crea un `BoundMaterials` con el JWT de esa petición
  y se descarta con ella.
- La caché del descriptor contiene solo información contractual común (versión y
  operaciones): ni identidad, ni token, ni respuestas de inventario.
- No se registran `Authorization`, el token, la clave publicable ni el cuerpo de
  la respuesta. El log lleva operación, estado HTTP, `elapsed_ms`, categoría de
  fallo, `call_status`, `outcome`, `match_origin`, `contract_version` y versión de
  inventario.
- El descriptor **no se puede sondear sin sesión** (mismo ACL), así que
  `/health/ready` reporta `materials` como `degraded` («se verifica con la
  primera consulta autenticada») y no inventa un `ok`.

## 4. Configuración

Se reutilizan `ELSA_MATERIALS_SUPABASE_URL` y `ELSA_MATERIALS_API_KEY`. Se añade:

| Variable | Defecto | Uso |
|---|---|---|
| `ELSA_MATERIALS_TIMEOUT_SECONDS` | `8` | Plazo de cada llamada al contrato de inventario. Independiente de `ELSA_AUTH_TIMEOUT_SECONDS`, que es solo del proveedor de identidad. |

Con `ELSA_AUTH_PROVIDER=fake` (DEV) el contenedor usa `FakeMaterialsFacade`; con
`supabase` usa el adaptador real. No hay reintentos: una llamada, un plazo.

## 5. Errores y semántica

| Situación | `availability.status` | Qué dice |
|---|---|---|
| `MATCHED` | `matched` | Material, **todas** las ubicaciones, totales con su regla, procedencia y alcance |
| `NOT_RETURNED` | `not_returned` | La fuente no devolvió ese código; **no** permite concluir que no exista |
| `NO_ACTIVE_INVENTORY` | `no_active_inventory` | No había dónde mirar; no es una ausencia |
| `REJECTED` | `rejected` | Sesión rechazada o perfil inactivo; sin datos de inventario |
| timeout, red, 401, 403, 429, 5xx | `unavailable` | Fallo técnico, no una ausencia (401 y 403 con mensaje propio) |
| JSON ilegible, campos que faltan, versión distinta de `"1"`, eco de código distinto, descriptor incompatible | `contract_error` | La respuesta no se muestra |
| varios códigos | `ambiguous_code` | No se consultó nada |

La cobertura de Materiales es hoy `UNKNOWN` y se muestra así (`scope_note`): no se
disfraza de completa ni de incompleta. `extracted_at` es siempre nulo en V1 y no
se muestra: `loaded_at` es cuándo terminó la carga en Materiales, **no** la fecha
de extracción de SAP.

## 6. Cómo validar sin tocar Materiales

Nivel **UNIT / INTEGRATION MOCK**: demuestran routing, mapeo, errores y
seguridad. No demuestran autenticación real, conectividad, el ACL ni inventario
real.

```bash
uv run pytest tests/test_material_code.py tests/test_materials_http_adapter.py \
  tests/test_api_assistant_availability.py
uv run ruff check src tests && uv run ruff format --check src tests
```

## 7. Prueba real (nivel PHYSICAL LIVE / E2E de página)

Necesita un usuario real de PAPELSA, activo en Materiales y con cuenta en ELSA, y
el `.env` de la máquina con `ELSA_AUTH_PROVIDER=supabase`, la URL y la clave
publicable de Materiales. **Ningún valor secreto se escribe en Git ni en el
chat.**

1. **Adaptador contra la fuente real.** Con un token de ese usuario en memoria,
   llamar a `SupabaseMaterialsGateway.for_token(token).lookup_material_by_code`
   con un código existente. Se espera `call_status=OK`, `contract_version="1"`,
   `outcome=MATCHED` y `match_origin=exact_material_code`; las cifras de inventario
   (versión, filas, fecha de carga) son las del día, no valores fijos.
2. **Desde la página.** Arrancar ELSA
   (`uv run uvicorn elsa.main:create_app --factory --host 127.0.0.1 --port 8000`),
   abrir `/app/`, entrar con el token del usuario (mecanismo actual: pegarlo en
   el login; el login real es un bloque aparte) y preguntar
   `¿Qué disponibilidad tiene el material <código>?`. Debe aparecer el bloque
   «Disponibilidad en Materiales» con procedencia.

Los tokens caducan (del orden de una hora) y no se guardan en ningún sitio.

## 8. Fuera de alcance

Búsqueda por texto en Materiales, login con formulario en la página, acceso
desde otra red, LLM en el chat, caché de existencias, reintentos y consulta por
lote. Cada uno es una decisión posterior con su propio bloque.
