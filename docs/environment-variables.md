# Variables de entorno

Toda la configuración de ELSA entra por variables de entorno con prefijo
`ELSA_`, cargadas y validadas al arranque por `src/elsa/config.py`
(`pydantic-settings`). En desarrollo local se leen de `.env` (las variables
reales del proceso tienen prioridad sobre el archivo).

Si falta una variable obligatoria o un valor es inválido, la aplicación no
arranca: termina con un `ConfigurationError` que nombra cada variable
afectada.

## Referencia

| Variable | Obligatoria | Default | Valores | Descripción |
|---|---|---|---|---|
| `ELSA_ENV` | Sí | — | `DEV`, `TEST` | Ambiente lógico. Selecciona a qué proyecto Supabase y a qué política (docs, CORS) responde la app. |
| `ELSA_CORS_ORIGINS` | Sí | — | Lista separada por comas | Orígenes CORS permitidos, p. ej. `http://localhost:5173,http://localhost:3000`. Cada origen lleva esquema `http(s)://`. Los comodines (`*`) se rechazan. |
| `ELSA_LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | Nivel de log de la aplicación (se normaliza a mayúsculas). |
| `ELSA_DEBUG` | No | `false` | `true`, `false` | Sube el nivel de log a `DEBUG`. Solo válido con `ELSA_ENV=DEV`; en otro ambiente la app no arranca. Nunca expone trazas al cliente. |

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
