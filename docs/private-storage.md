# Almacenamiento privado de artefactos

Los bytes de los archivos originales (XLSX de Ingeniería, HTM de SAP) y de
sus derivados (imágenes de plano) **no viven en PostgreSQL ni en Git**.
Viven detrás del puerto `artifact_storage`; la base guarda solo el metadato
y el SHA-256.

La separación existe por tres razones concretas: los archivos son
información interna de planta que el repositorio (potencialmente público)
nunca debe contener, pesan más de lo que conviene mover en una fila, y el
destino final —sistema de archivos privado hoy, bucket privado de Supabase
Storage mañana— es una decisión que todavía no está tomada. Cambiarla debe
afectar a un adaptador, no a la ingesta.

## Garantías del puerto

- **La clave la genera el sistema**, derivada del SHA-256 del contenido:
  `{prefijo}/{2 primeros del hash}/{hash}`. El nombre que traía el archivo
  **nunca** es su identificador: puede venir con rutas, con caracteres
  hostiles o repetido. Como consecuencia, el mismo contenido cae siempre en
  la misma clave y reintentar una subida es idempotente.
- **Escribir no sobrescribe.** Guardar sobre una clave existente es un error
  explícito, no un reemplazo silencioso de evidencia.
- **Un fallo no se disfraza de éxito.** Si el backend no responde, la
  operación falla con 503 y el metadato nunca queda registrado como si el
  archivo estuviera guardado.
- **La clave no puede salir de su raíz.** Se valida antes de tocar el disco:
  una clave absoluta, con `..` o con separadores del sistema se rechaza
  aunque el llamador se haya equivocado.

## Adaptadores

| Adaptador | Uso | Notas |
|---|---|---|
| `LocalArtifactStorage` | DEV y prueba de aceptación privada | Escritura atómica (temporal + `os.replace`), creación con `O_EXCL`, permisos `0600`/`0700` |
| `InMemoryArtifactStorage` | Tests y arranque en DEV sin disco | No persiste; solo permitido en DEV |

Se selecciona con `ELSA_ARTIFACT_STORAGE_BACKEND` (`local` | `memory`). El
backend `memory` **solo es válido en DEV**: la configuración se niega a
arrancar con él en TEST.

## Configuración del backend local

```bash
ELSA_ARTIFACT_STORAGE_BACKEND=local
ELSA_ARTIFACT_STORAGE_ROOT=/var/lib/elsa/artifacts   # Windows: C:\ProgramData\elsa\artifacts
```

La raíz **debe estar fuera del repositorio** y **no debe tener exposición
web directa**. No hay CDN pública y no se sirve ningún artefacto por una URL
sin autenticar.

Aun así, `.gitignore` cubre `.artifacts/`, `artifacts/` y `private/` por si
alguien apunta la raíz dentro del repositorio por error. Es una red de
seguridad, no el mecanismo.

## Supabase Storage

El puerto está diseñado para admitirlo después. Cuando llegue:

- bucket **privado**, nunca público;
- acceso **solo desde el backend**;
- ningún secreto en el código, en el frontend ni en los tests;
- la clave de servicio no se pide por chat ni se versiona.

No se implementa en este bloque, y la suite de PostgreSQL **no depende** del
esquema `storage` específico de Supabase: corre contra un PostgreSQL limpio.

## Salud

`artifact_storage` es una dependencia **crítica** en
`GET /api/v1/health/ready`. Con el adaptador local comprueba que la raíz
existe y acepta escrituras; con el de memoria reporta `degraded`, porque
responde pero pierde todo al reiniciar.

`GET /api/v1/health/live` no depende del almacenamiento y sigue respondiendo
aunque esté caído.
