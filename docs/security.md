# Seguridad básica

Política de seguridad del repositorio y del backend hasta el Bloque 1. La arquitectura debe
facilitar auditoría de ciberseguridad y pentesting (CLAUDE.md, regla 15).

## Secretos

- **Ningún secreto se versiona.** `.env` está en `.gitignore`;
  `.env.example` documenta todas las claves sin valores secretos.
- El escaneo de secretos es automático, no una revisión manual:
  - `pre-commit` ejecuta [gitleaks](https://github.com/gitleaks/gitleaks) y
    `detect-private-key` sobre lo que se va a commitear.
  - CI ejecuta gitleaks sobre **toda la historia** del repositorio en cada
    push y pull request (`.github/workflows/ci.yml`).
- Si un secreto llega a versionarse: se rota de inmediato en el servicio de
  origen y luego se limpia la historia. Rotar es lo urgente; limpiar no
  des-expone nada por sí solo.
- Ninguna clave de servicio (Supabase u otra) sale del backend. El frontend
  nunca recibe secretos.

## Artefactos que nunca se versionan

`.gitignore` bloquea, y `tests/test_gitignore.py` verifica en cada corrida,
que no puedan añadirse al repositorio:

- `.env` y variantes (`.env.local`, `.env.dev`, ...)
- archivos SAP y exportes de oficina (`*.xls`, `*.xlsx`, `*.mdb`)
- PDFs de manuales (`*.pdf`)
- planos (`*.dwg`, `*.dxf`, `*.tif`, `*.tiff`)
- pesos de modelos (`*.gguf`, `*.safetensors`, `*.pt`, `*.pth`, `*.onnx`, `*.ckpt`)
- datasets (`data/`, `datasets/`, `*.parquet`, `*.csv`, `*.jsonl`)
- dumps de base de datos (`*.dump`, `*.bak`, `*.sql.gz`, `*.sqlite`, `*.db`)

`check-added-large-files` (pre-commit) añade una barrera adicional de 500 KB
por archivo. Si un archivo legítimo cae en estos patrones, la excepción se
discute y se documenta; no se elimina el patrón.

## Logs

- Logs estructurados en JSON con `request_id` por request, para trazabilidad
  y auditoría.
- Los logs **no contienen** tokens, secretos ni datos personales. La línea de
  acceso registra método, ruta, estado y duración; nunca cabeceras, query
  strings ni cuerpos (un token en una query string quedaría logueado; por eso
  no se registran).
- El JWT y la cabecera `Authorization` no se registran nunca, ni completos ni
  truncados. Cuando un token se rechaza, al log va el nombre de la excepción
  (`ExpiredSignatureError`, `UnexpectedAlgorithm`, ...), nunca su contenido.
  `tests/test_security_logging.py` lo comprueba sobre la salida JSON real.
- Las trazas de errores no controlados van solo al log del servidor, nunca al
  cliente.

## Errores hacia el cliente

Todo error usa el formato estándar (`docs/architecture.md`). Un error 500
devuelve un mensaje genérico y el `request_id` para correlacionar con los
logs; jamás una traza, un mensaje de excepción interna ni versiones de
librerías.

## CORS

Orígenes declarados explícitamente por ambiente en `ELSA_CORS_ORIGINS`.
Los comodines están prohibidos y la validación de configuración los rechaza
al arranque. Métodos y cabeceras permitidos también son listas explícitas
(`src/elsa/main.py`).

## Modo debug

`ELSA_DEBUG=true` solo es válido en DEV; en cualquier otro ambiente la
aplicación se niega a arrancar. El modo debug únicamente sube la verbosidad
de logs: no activa trazas hacia el cliente ni recarga insegura.

## Autenticación y autorización

**Materiales = identidad. ELSA = autorización.**

- La identidad la emite el Supabase del proyecto Materiales (JWT). ELSA la
  verifica criptográficamente en el backend, a través del puerto `auth`
  (ADR 0002 y ADR 0005): firma, expiración, emisor, audiencia y algoritmo.
  Cualquier algoritmo fuera de la lista configurada se rechaza antes de tocar
  ninguna clave, lo que cierra `none` y la confusión de algoritmo.
- Tras verificar el token se comprueba en la fuente autoritativa que el perfil
  sigue **activo**. Esa consulta usa el JWT del propio usuario y la clave
  publicable de Materiales: ELSA no tiene ni necesita una credencial de
  servicio de aquel proyecto, y ninguna clave de Materiales llega al navegador
  desde ELSA.
- La autorización es propia de ELSA, **por usuario**, y aplica DEFAULT DENY:
  sin cuenta activa y sin permiso explícito, no hay acceso. Solo el
  administrador de ELSA lo evita, y su acceso total queda registrado en cada
  decisión (`via_admin`).
- Los permisos se aplican **antes** de recuperar conocimiento: la
  autorización es una dependencia de FastAPI que se resuelve antes del cuerpo
  del endpoint. Nunca se recupera para después ocultar.
- El LLM nunca decide permisos y no participa en ningún paso de la cadena.
- RLS no es el mecanismo de autorización de ELSA: la autorización vive en
  FastAPI (ADR 0002). Aun así, las tablas de ELSA viven en el esquema `elsa`
  (no expuesto por PostgREST), con RLS habilitado y sin políticas, y con
  `REVOKE` para `anon` y `authenticated`. Es defensa en profundidad: el
  navegador no debe poder alcanzarlas por ninguna vía.

### Credenciales

| Credencial | Dónde vive | Nunca |
|---|---|---|
| JWT del usuario | Cabecera `Authorization` de cada petición | Logs, respuestas, base de datos |
| Clave publicable de Materiales | `ELSA_MATERIALS_API_KEY` | — (es pública por diseño) |
| Secreto simétrico del JWT, si aplica | `ELSA_AUTH_JWT_SECRET` | Repositorio, frontend, logs |
| Conexión a Supabase ELSA | `ELSA_DATABASE_URL` | Repositorio, frontend, logs |
| Token de bootstrap | `ELSA_BOOTSTRAP_ADMIN_TOKEN` | Repositorio, frontend, logs |

Los tres últimos se declaran como `SecretStr`: no se imprimen al representar
la configuración. Hay un test que lo verifica.

### Bootstrap del primer administrador

`POST /api/v1/admin/bootstrap` exige a la vez un JWT válido con perfil activo
(el UUID promovido es el del usuario realmente autenticado) y el token de
`ELSA_BOOTSTRAP_ADMIN_TOKEN` en la cabecera `X-Bootstrap-Token`, comparado en
tiempo constante. Sin esa variable el endpoint está deshabilitado y responde
lo mismo que con un token incorrecto, para no confirmar si el mecanismo está
activo. La operación es idempotente, queda auditada y solo funciona mientras
ELSA no tenga ya un administrador. Después de usarlo, borra la variable.

El bootstrap solo se habilita con un valor **no vacío**. La variable ausente,
vacía (`ELSA_BOOTSTRAP_ADMIN_TOKEN=`, la línea que trae `.env.example`) o con
solo espacios significa siempre *deshabilitado*: nunca un token válido vacío
que una cabecera ausente pudiera igualar. El endpoint rechaza además toda
cabecera `X-Bootstrap-Token` vacía, con independencia de la configuración.

## Auditoría

Se registran los cambios administrativos —otorgar y revocar permisos,
habilitar y deshabilitar usuarios, otorgar y retirar la administración, y el
bootstrap— con actor, usuario afectado, operación, alcance, `request_id` y
momento. **No** se audita que alguien abra una conversación.

La tabla `elsa.admin_audit_log` es *append-only*: un *trigger* rechaza
`UPDATE` y `DELETE` incluso para la credencial de servicio, y cada entrada se
escribe en la misma transacción que el cambio que documenta.

## Control de abuso

Configurable por variables de entorno (ver `docs/environment-variables.md`):
solicitudes por usuario y minuto, solicitudes simultáneas por usuario,
sesiones ELSA simultáneas por usuario y tiempo de inactividad. Al superarse un
límite se responde `429` con `Retry-After`.

No cubre el bloqueo de cuenta por contraseñas fallidas: eso es responsabilidad
del Supabase de Materiales, donde ocurre el inicio de sesión.

**Limitaciones conocidas, documentadas en lugar de disimuladas:**

1. Los contadores viven en la memoria del proceso. Con varios trabajadores o
   varias réplicas, cada uno aplica los suyos y el límite efectivo se
   multiplica por el número de procesos. Es una defensa contra el uso
   desmedido, no una garantía distribuida. Sustituirlo por un almacén
   compartido (p. ej. Redis) es escribir otro adaptador de `AbuseGuardPort`.
2. El límite de sesiones simultáneas depende de que el token traiga un
   identificador de sesión fiable. Si no lo trae, **no se simula**: se avisa
   una vez en el log y el límite queda sin aplicar. Nunca se almacena el JWT
   completo para controlar sesiones; como mucho, el identificador de sesión
   que el propio token declara.
