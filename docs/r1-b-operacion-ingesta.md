# R1.B — operación de la ingesta persistente del corpus PR-100

Secuencia de comandos para cargar el corpus sintético de R1 en el ambiente
**TEST** con `elsa.tools.documents_admin`. **Este documento no autoriza
ejecutarla.** Cada fase tiene su punto de autorización, y ninguno está
concedido mientras no lo diga Juan en la conversación del bloque:

| Fase | Autorización | Qué hace |
|---|---|---|
| Precondiciones | **G-0** | Verificar Render (A2) y resolver la inconsistencia DEV/TEST de PC1 |
| Escrituras | **G-W** | Crear activos y documentos, e ingerir las cuatro versiones, incluida la v2 de la prensa |
| Publicación | **G-P** | Aprobar y publicar tres versiones; ninguna ingesta. Su Ctrl+Z es `withdraw` (§5) |

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
publica.

**G-P tiene Ctrl+Z, y tiene que estar disponible antes de publicar.** Es el
comando `withdraw` (§5 y
[ADR 0038](adr/0038-retirada-auditable-de-publicaciones-documentales.md)).
Antes de empezar, comprueba dos cosas:

1. La migración `20261103010000_allow_document_publication_withdrawal` está
   aplicada en TEST. Sin ella, la base rechaza la retirada. La comprueba y la
   aplica quien administra las migraciones, con su propia autorización.
2. Este comando muestra la ayuda de `withdraw`. Si responde
   `invalid choice: 'withdraw'`, la copia de ELSA en PC1 no tiene el Ctrl+Z:
   **no publiques**.

```powershell
uv run python -m $tool withdraw --help
```

### 3.1 Estado antes de publicar

```powershell
$actor = "<UUID del operador autorizado>"
uv run python -m $tool status --domain mantenimiento
```

Tiene que mostrar exactamente esto. **Si no coincide, no publiques.**

| Documento | Versión | UUID | Estado |
|---|---|---|---|
| `bomba-manual` | v1 | `78d38091-604a-434c-b45c-52c21d7dfc42` | `pending_validation` |
| `prensa-manual` | v1 | `9863f1a6-e869-4f0d-88db-bae83cd4edb8` | `pending_validation` |
| `prensa-manual` | v2 | `5b64b985-1895-467b-a658-7f30b342b11e` | `pending_validation` |
| `prensa-nota-en` | v1 | `0fd1d77d-4d68-4fe6-8158-ffe545908a72` | `pending_validation` |

Guarda esa salida: es el **estado anterior** a la operación.

### 3.2 Publicar

Cada versión necesita dos comandos, en este orden: aprobar y después
publicar. La v2 de la prensa (`5b64b985-…`) **no aparece aquí, y no debe
aparecer**.

```powershell
uv run python -m $tool approve --version 9863f1a6-e869-4f0d-88db-bae83cd4edb8 --actor $actor
uv run python -m $tool publish --version 9863f1a6-e869-4f0d-88db-bae83cd4edb8 --actor $actor
uv run python -m $tool approve --version 0fd1d77d-4d68-4fe6-8158-ffe545908a72 --actor $actor
uv run python -m $tool publish --version 0fd1d77d-4d68-4fe6-8158-ffe545908a72 --actor $actor
uv run python -m $tool approve --version 78d38091-604a-434c-b45c-52c21d7dfc42 --actor $actor
uv run python -m $tool publish --version 78d38091-604a-434c-b45c-52c21d7dfc42 --actor $actor
```

Cada `publish` correcto imprime `publicada: v1 published <uuid>`. **Si un
comando falla, detente**: no lo repitas ni sigas con el siguiente, y ve a §6.

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

**La publicación es incorrecta** si no se cumple cualquiera de estas cosas:
la v2 aparece como `approved` o `published`, falta alguna de las tres v1, o
aparece un documento que no está en la tabla. En ese caso, aplica el Ctrl+Z
(§5).

Es la misma secuencia que ejecuta `tests/test_documents_admin.py` contra
PostgreSQL efímero, y la que hace válida la evaluación de
[`bench/r1/evaluacion.json`](../bench/r1/evaluacion.json).

## 5. Ctrl+Z: retirar las publicaciones

`withdraw` saca de la recuperación una versión publicada. ELSA deja de
encontrar sus fragmentos en cuanto termina el comando. **No borra nada**: el
documento, la versión, los fragmentos, los vectores y el historial siguen
ahí. Exige un motivo, que queda escrito en el historial.

Para deshacer G-P completo, retira las tres v1:

```powershell
$motivo = "Ctrl+Z de G-P: <explica aquí por qué>"
uv run python -m $tool withdraw --version 9863f1a6-e869-4f0d-88db-bae83cd4edb8 --actor $actor --reason $motivo
uv run python -m $tool withdraw --version 0fd1d77d-4d68-4fe6-8158-ffe545908a72 --actor $actor --reason $motivo
uv run python -m $tool withdraw --version 78d38091-604a-434c-b45c-52c21d7dfc42 --actor $actor --reason $motivo
```

Cada retirada correcta imprime `publicación retirada: v1 approved <uuid>`.
Para retirar una sola publicación, ejecuta solo su línea.

### 5.1 Comprobar que funcionó

```powershell
uv run python -m $tool status --domain mantenimiento
```

**No debe quedar ninguna versión `published`**: las tres v1 aparecen en
`approved` y la v2 de la prensa sigue en `pending_validation`.

**El Ctrl+Z devuelve la visibilidad, no cada estado.** Antes de G-P las v1
estaban en `pending_validation`. Después del Ctrl+Z quedan en `approved`,
porque la aprobación ya ocurrió y sigue registrada. Para ELSA el resultado es
el mismo: no recupera ninguna de las tres.

### 5.2 Volver a publicar

Una versión retirada se vuelve a publicar con el mismo `publish` de §3.2, sin
`approve`, porque ya está aprobada:

```powershell
uv run python -m $tool publish --version 9863f1a6-e869-4f0d-88db-bae83cd4edb8 --actor $actor
```

### 5.3 Lo que no hace

- No retira una versión que no está publicada: responde con error y no
  cambia nada. Por eso repetir una retirada es seguro.
- No restaura una versión anterior reemplazada (`superseded`). En G-P no hay
  ninguna, porque las tres son primeras publicaciones.
- No deshace la aprobación ni borra historial (§5.1).

## 6. Si un comando falla

| Lo que ves | Qué significa | Qué hacer |
|---|---|---|
| `NotPublishableError: only an approved version can be published` | Intentaste publicar sin aprobar, o la versión ya no está aprobada | No cambió nada. Revisa `status` antes de seguir |
| `NotPublishableError: only a published version can be withdrawn` | La versión no estaba publicada: ya se retiró, o nunca se publicó | No cambió nada. Revisa `status` |
| `NotPublishableError: withdrawing a publication requires a nonblank reason` | `--reason` estaba vacío | No cambió nada. Repite con un motivo |
| `the following arguments are required: --reason` | Faltó `--reason` | No llegó a conectarse a la base. Repite con un motivo |
| `invalid choice: 'withdraw'` | La copia de ELSA en PC1 no tiene el Ctrl+Z | No publiques. Actualiza PC1 desde `main` |
| `la base de datos no está disponible` | No hubo conexión, o la base rechazó la operación (por ejemplo, porque falta la migración) | La operación se revierte entera. Revisa `status` y avisa antes de repetir |

En cualquier caso, **no repitas un comando a ciegas**. Ejecuta `status`,
compáralo con la tabla del paso en el que estabas y decide a partir de lo que
muestra.

## Permanencia y retirada

El modelo documental **no borra**. Lo que esta secuencia escribe en TEST queda
ahí: activos, documentos, versiones, chunks, ejecuciones e historial.

- `reject` rechaza una versión **no publicada**. No retira la versión
  publicada ni borra nada.
- Publicar una versión nueva **reemplaza** la vigente, que pasa a
  `superseded` y sigue guardada.
- `withdraw` retira la publicación vigente sin reemplazarla: la versión
  vuelve a `approved` y puede publicarse otra vez (§5).

Ninguna de las tres operaciones es una eliminación de datos, y no deben
presentarse como tal. El historial de cada versión conserva quién ingirió,
aprobó, publicó y retiró, cuándo y con qué motivo.
