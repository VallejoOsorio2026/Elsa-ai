# R1.B — operación de la ingesta persistente del corpus PR-100

Secuencia de comandos para cargar el corpus sintético de R1 en el ambiente
**TEST** con `elsa.tools.documents_admin`. **Este documento no autoriza
ejecutarla.** Cada fase tiene su punto de autorización, y ninguno está
concedido mientras no lo diga Juan en la conversación del bloque:

| Fase | Autorización | Qué hace |
|---|---|---|
| Precondiciones | **G-0** | Verificar Render (A2) y resolver la inconsistencia DEV/TEST de PC1 |
| Escrituras | **G-W** | Crear activos y documentos, e ingerir las cuatro versiones, incluida la v2 de la prensa |
| Publicación | **G-P** | Aprobar y publicar tres versiones; ninguna ingesta |

Ver el cierre de R1.A ([`r1-a-entorno-supabase-test-cierre.md`](r1-a-entorno-supabase-test-cierre.md),
§20) para los pendientes que condicionan G-W.

## Configuración, solo para la sesión

Nada de esto se escribe en el `.env`. Se define en la ventana de PowerShell que
va a ejecutar los comandos, abierta en la raíz del repositorio, y desaparece al
cerrarla:

```powershell
$env:ELSA_ENV = "TEST"
$env:ELSA_ARTIFACT_STORAGE_BACKEND = "local"
$env:ELSA_ARTIFACT_STORAGE_ROOT = "$env:LOCALAPPDATA\ELSA\artifacts"
```

- La raíz de artefactos queda **fuera de OneDrive y del repositorio**. Su
  ubicación, permisos y persistencia se confirman en G-0.
- `ELSA_DATABASE_URL` sale de la configuración que G-0 deje establecida. La
  herramienta nunca la imprime.
- La herramienta **se niega** a escribir con `ELSA_ENV=DEV` contra una base
  remota, y a ingerir con el almacén de artefactos en memoria.

`<ACTOR>` es el UUID de quien ejecuta, que queda en el historial de cada
versión. Cuál se usa se decide en G-W.

## 1. Comprobación de conflictos (solo lectura, antes de G-W)

```powershell
uv run python -m elsa.tools.documents_admin status --domain mantenimiento `
  --asset prensa-ejemplo --asset bomba-ejemplo `
  --document prensa-manual --document prensa-nota-en --document bomba-manual
```

Lo esperado es que todo aparezca `ausente`. **Si algo aparece `presente`, se
detiene la operación**: no se renombra ni se reutiliza (decisión D2).

## 2. Escrituras (G-W)

```powershell
$tool = "elsa.tools.documents_admin"
uv run python -m $tool create-asset --domain mantenimiento --code prensa-ejemplo --name "Prensa de ejemplo PR-100"
uv run python -m $tool create-asset --domain mantenimiento --code bomba-ejemplo --name "Bomba de ejemplo BO-200"

uv run python -m $tool create-document --domain mantenimiento --code prensa-manual `
  --title "Manual de mantenimiento de la prensa de ejemplo PR-100" --source-kind manual `
  --asset prensa-ejemplo --language es
uv run python -m $tool create-document --domain mantenimiento --code prensa-nota-en `
  --title "Press PR-100 technical note" --source-kind technical_note `
  --asset prensa-ejemplo --language en
uv run python -m $tool create-document --domain mantenimiento --code bomba-manual `
  --title "Manual de mantenimiento de la bomba de ejemplo BO-200" --source-kind manual `
  --asset bomba-ejemplo --language es

uv run python -m $tool ingest --domain mantenimiento --document prensa-manual `
  --file bench/corpus-sintetico/prensa-ejemplo-v1.md --actor <ACTOR>
uv run python -m $tool ingest --domain mantenimiento --document prensa-nota-en `
  --file bench/corpus-sintetico/prensa-ejemplo-en-v1.md --actor <ACTOR>
uv run python -m $tool ingest --domain mantenimiento --document bomba-manual `
  --file bench/corpus-sintetico/bomba-ejemplo-v1.md --actor <ACTOR>

# La revisión 2 de la prensa: se ingiere aquí y se dejará pendiente.
# Es la trampa de versión de la evaluación.
uv run python -m $tool ingest --domain mantenimiento --document prensa-manual `
  --file bench/corpus-sintetico/prensa-ejemplo-v2.md --actor <ACTOR>
```

Cada `ingest` imprime la versión creada (`v1 pending_validation <uuid>`) y su
número de chunks. **Ingerir no aprueba ni publica.** La v2 de la prensa debe
ingerirse **después** de la v1, para que reciba el número de versión 2.

Al terminar G-W, `status` debe mostrar las cuatro versiones en
`pending_validation` y ninguna publicada.

## 3. Publicación (G-P)

**G-P no incluye ninguna ingesta ni ninguna otra escritura**: solo aprueba y
publica la v1 de cada documento. La v2 de la prensa no se aprueba ni se
publica. Con los UUID que imprimió cada `ingest`, o los que muestra `status`:

```powershell
uv run python -m $tool approve --version <uuid prensa-manual v1> --actor <ACTOR>
uv run python -m $tool publish --version <uuid prensa-manual v1> --actor <ACTOR>
uv run python -m $tool approve --version <uuid prensa-nota-en v1> --actor <ACTOR>
uv run python -m $tool publish --version <uuid prensa-nota-en v1> --actor <ACTOR>
uv run python -m $tool approve --version <uuid bomba-manual v1> --actor <ACTOR>
uv run python -m $tool publish --version <uuid bomba-manual v1> --actor <ACTOR>
```

## 4. Verificación

```powershell
uv run python -m $tool status --domain mantenimiento
```

Estado esperado:

| Documento | Versiones |
|---|---|
| `prensa-manual` | v1 `published`, v2 `pending_validation` |
| `prensa-nota-en` | v1 `published` |
| `bomba-manual` | v1 `published` |

Es la misma secuencia que ejecuta `tests/test_documents_admin.py` contra
PostgreSQL efímero, y la que hace válida la evaluación de
[`bench/r1/evaluacion.json`](../bench/r1/evaluacion.json).

## Permanencia y retirada

El modelo documental **no borra**. Lo que esta secuencia escribe en TEST queda
ahí: activos, documentos, versiones, chunks, ejecuciones e historial.

- `reject` rechaza una versión **no publicada**. No retira la versión
  publicada ni borra nada.
- Publicar una versión nueva **reemplaza** la vigente, que pasa a
  `superseded` y sigue guardada.

Ninguna de las dos operaciones es una eliminación de datos, y no deben
presentarse como tal.
