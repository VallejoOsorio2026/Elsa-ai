# Prueba de aceptación privada (archivos reales)

Cómo ejecutar la ingesta contra los archivos reales de Ingeniería y de SAP
**sin que ninguno de ellos, ni nada derivado de ellos, entre en Git**.

> El repositorio puede ser visible públicamente. Los archivos reales son
> información interna de PAPELSA. Nunca se copian dentro del repositorio,
> nunca se versionan y el reporte que produce esta prueba tampoco.

## Qué hace falta

- Los dos archivos, **en su ubicación actual**. No hay que copiarlos ni
  moverlos.
- Un directorio de artefactos privado, fuera del repositorio.
- Ningún secreto. Esta prueba no necesita credenciales de Supabase: corre
  contra PostgreSQL local o contra los adaptadores en memoria.

## Preparación

```bash
# Directorio privado de artefactos, FUERA del repositorio
export ELSA_ARTIFACT_STORAGE_BACKEND=local
export ELSA_ARTIFACT_STORAGE_ROOT=/var/lib/elsa/artifacts
```

En PowerShell:

```powershell
$env:ELSA_ARTIFACT_STORAGE_BACKEND = "local"
$env:ELSA_ARTIFACT_STORAGE_ROOT    = "C:\ProgramData\elsa\artifacts"
```

## Ejecución

```bash
git status                      # debe estar limpio ANTES

uv run python -m elsa.tools.private_acceptance \
    --engineering "<RUTA LOCAL DEL XLSX>" \
    --sap         "<RUTA LOCAL DEL HTM>" \
    --out         "<RUTA FUERA DEL REPOSITORIO>/reporte.json"

git status                      # debe seguir limpio DESPUÉS
```

Las rutas se pasan como argumentos. **No se copia nada al repositorio** y el
reporte se escribe donde indique `--out`; si se omite, va a `acceptance/`,
que está en `.gitignore`.

## Qué contiene el reporte

Conteos, hashes y metadatos estructurales:

- SHA-256 y tamaño de cada archivo original;
- hojas detectadas;
- número de componentes, con y sin código SAP;
- subsistemas;
- planos extraídos y cuántos quedaron pendientes de asociación;
- registros de AMEF y criterios S/O/D;
- metadatos del HTM (ubicación técnica, denominación, fecha);
- número de materiales y de equipos hijos;
- resumen de la reconciliación por clasificación;
- errores y ambigüedades.

El reporte incluye **conteos, no contenido**: no lleva códigos de material,
descripciones ni números de plano reales. Aun así se escribe en una ruta
ignorada y **no debe adjuntarse a un PR, a un issue ni a CI**.

## Lo que esta prueba no hace

- No aplica migraciones a ningún Supabase remoto.
- No se conecta a SAP.
- No publica nada: la versión queda pendiente de validación, como cualquier
  otra.
- No imprime contenido técnico por consola.

## Después

```bash
git status
```

Debe seguir limpio. Si aparece cualquier archivo nuevo dentro del
repositorio, **no se hace commit**: se revisa por qué apareció y se corrige
la ruta de salida.
