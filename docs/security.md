# Seguridad básica

Política de seguridad del repositorio en el Bloque 0. La arquitectura debe
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

## Autenticación y autorización (previsto)

- La identidad la emite el Supabase del proyecto Materiales (JWT). ELSA la
  valida en el backend a través del puerto `auth` (ADR 0002).
- El LLM nunca decide permisos; los permisos se aplican **antes** de
  recuperar conocimiento.
- RLS no es el mecanismo de autorización de ELSA: la autorización vive en
  FastAPI (ver ADR 0002).
