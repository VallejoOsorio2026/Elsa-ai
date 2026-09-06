# Variables de entorno

Toda la configuración de ELSA entra por variables de entorno con prefijo
`ELSA_`, cargadas y validadas al arranque por `src/elsa/config.py`
(`pydantic-settings`). En desarrollo local se leen de `.env` (las variables
reales del proceso tienen prioridad sobre el archivo).

Si falta una variable obligatoria o un valor es inválido, la aplicación no
arranca: termina con un `ConfigurationError` que nombra cada variable
afectada.

**Variable opcional declarada sin valor = variable ausente.** Copiar
`.env.example` a `.env` deja líneas como `ELSA_AUTH_JWKS_URL=`. Un valor
vacío o compuesto solo por espacios se interpreta como «no configurada», de
modo que el valor por defecto o derivado toma el relevo. Esto vale también
para los secretos: `ELSA_BOOTSTRAP_ADMIN_TOKEN=` es *no hay token*, nunca
*el token es la cadena vacía*.

La tolerancia se limita al valor vacío. Un valor no vacío y malformado se
sigue rechazando: `ELSA_AUTH_JWKS_URL=esto-no-es-una-url` impide el arranque.

Las variables marcadas como **secreto** no se versionan nunca: viven en
`.env` (ignorado por git) o en el gestor de secretos del entorno de
despliegue. Se cargan como `SecretStr`, de modo que no aparecen al imprimir
la configuración.

## General

| Variable | Obligatoria | Default | Valores | Descripción |
|---|---|---|---|---|
| `ELSA_ENV` | Sí | — | `DEV`, `TEST` | Ambiente lógico. DEV admite fakes y recursos locales; TEST usa el proyecto Supabase remoto. |
| `ELSA_CORS_ORIGINS` | Sí | — | Lista separada por comas | Orígenes CORS permitidos, p. ej. `http://localhost:5173,http://localhost:3000`. Cada origen lleva esquema `http(s)://`. Los comodines (`*`) se rechazan. |
| `ELSA_LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Nivel de log de la aplicación (se normaliza a mayúsculas). |
| `ELSA_DEBUG` | No | `false` | `true`, `false` | Sube el nivel de log a `DEBUG`. Solo válido con `ELSA_ENV=DEV`; en otro ambiente la app no arranca. Nunca expone trazas al cliente. |

## Identidad (Asistente de Materiales)

| Variable | Obligatoria | Default | Descripción |
|---|---|---|---|
| `ELSA_AUTH_PROVIDER` | No | `fake` | `supabase` (verificación real) o `fake` (identidades deterministas en memoria). `fake` **solo** es válido en DEV. |
| `ELSA_MATERIALS_SUPABASE_URL` | Con `supabase` | — | URL del proyecto Supabase de Materiales, sin barra final. Fuera de DEV debe ser `https`. No es un secreto. |
| `ELSA_MATERIALS_API_KEY` | Con `supabase` | — | Clave publicable (`sb_publishable_...` o `anon`) de Materiales. Pública por diseño: se envía como cabecera `apikey` a PostgREST. |
| `ELSA_AUTH_JWT_ALGORITHMS` | No | `ES256,RS256` | Algoritmos aceptados, separados por coma. Cualquier otro se rechaza; `none` no es configurable. Con un `HS*` se exige `ELSA_AUTH_JWT_SECRET`. |
| `ELSA_AUTH_JWT_AUDIENCE` | No | `authenticated` | Audiencia esperada (`aud`). Vacío desactiva la comprobación. |
| `ELSA_AUTH_JWT_ISSUER` | No | derivada | Emisor esperado. Por defecto `<ELSA_MATERIALS_SUPABASE_URL>/auth/v1`. Vacía o ausente, se deriva. |
| `ELSA_AUTH_JWKS_URL` | No | derivada | Por defecto `<ELSA_MATERIALS_SUPABASE_URL>/auth/v1/.well-known/jwks.json`. Vacía o ausente, se deriva; no vacía y malformada, se rechaza. |
| `ELSA_AUTH_JWT_SECRET` | Con `HS*` | — | **Secreto.** Solo si Materiales firma de forma simétrica (ver ADR 0005). Con `ES256`/`RS256` no hace falta. Declarada sin valor cuenta como ausente: con un `HS*` la app no arranca. |
| `ELSA_AUTH_JWT_LEEWAY_SECONDS` | No | `10` | Tolerancia de reloj al comprobar `exp` / `iat`. |
| `ELSA_AUTH_TIMEOUT_SECONDS` | No | `5.0` | Timeout de las llamadas al proveedor de identidad. |
| `ELSA_AUTH_JWKS_CACHE_SECONDS` | No | `600` | Vigencia del JWKS en caché. |
| `ELSA_AUTH_JWKS_MIN_REFRESH_SECONDS` | No | `60` | Espera mínima entre refrescos del JWKS ante un `kid` desconocido. Evita que un token forjado provoque una descarga por petición; a cambio, una rotación tarda como mucho ese tiempo en reconocerse. |

## Autorización (Supabase ELSA)

| Variable | Obligatoria | Default | Descripción |
|---|---|---|---|
| `ELSA_PERMISSIONS_BACKEND` | No | `memory` | `postgres` (Supabase ELSA) o `memory` (no persistente). `memory` **solo** es válido en DEV. |
| `ELSA_DATABASE_URL` | Con `postgres` | — | **Secreto.** Cadena de conexión a Supabase ELSA. Credencial exclusiva del servidor: nunca en el frontend, el repositorio ni los logs. |
| `ELSA_DATABASE_POOL_MIN_SIZE` | No | `1` | Tamaño mínimo del pool de conexiones. |
| `ELSA_DATABASE_POOL_MAX_SIZE` | No | `10` | Tamaño máximo del pool de conexiones. |
| `ELSA_BOOTSTRAP_ADMIN_TOKEN` | No | — | **Secreto.** Habilita `POST /api/v1/admin/bootstrap`, que se presenta en la cabecera `X-Bootstrap-Token`. Ausente, vacía o con solo espacios, el endpoint queda **deshabilitado**: nunca vale como token vacío. Genera uno aleatorio (`openssl rand -hex 32`), úsalo una vez y bórralo. |

## Control de abuso

Todos los límites son por usuario autenticado; `0` significa sin límite. Ver
las limitaciones conocidas en [`security.md`](security.md).

| Variable | Obligatoria | Default | Descripción |
|---|---|---|---|
| `ELSA_RATE_LIMIT_ENABLED` | No | `true` | Desactivarlo pone a cero los dos límites siguientes. |
| `ELSA_RATE_LIMIT_REQUESTS_PER_MINUTE` | No | `60` | Máximo de solicitudes por usuario y minuto. Al superarlo, `429` con `Retry-After`. |
| `ELSA_RATE_LIMIT_MAX_CONCURRENT_REQUESTS` | No | `5` | Máximo de solicitudes simultáneas por usuario. |
| `ELSA_MAX_SESSIONS_PER_USER` | No | `0` | Máximo de sesiones ELSA simultáneas. Solo aplicable si el JWT trae un identificador de sesión fiable; si no lo trae, no se aplica y se avisa en el log. |
| `ELSA_SESSION_IDLE_TIMEOUT_SECONDS` | No | `1800` | Inactividad tras la cual una sesión deja de contar como activa. |

## Solo para tests

| Variable | Descripción |
|---|---|
| `ELSA_TEST_DATABASE_URL` | Base PostgreSQL contra la que corren los tests de migraciones y del repositorio de permisos. Sin ella, esos tests se omiten. **Nunca** apunta al Supabase real: en CI es un contenedor efímero. |

## Reglas

- `.env` nunca se versiona (está en `.gitignore`); `.env.example` contiene
  todas las claves **sin** valores secretos y se mantiene al día en el mismo
  cambio que introduce una variable nueva.
- Este documento se actualiza en el mismo pull request que añade, renombra o
  elimina una variable.
- Las credenciales que lleguen en bloques posteriores (Supabase, JWKS de
  Materiales, etc.) seguirán el mismo mecanismo: clave documentada aquí y en
  `.env.example`, valor solo en `.env` o en el gestor de secretos del entorno
  de despliegue.
