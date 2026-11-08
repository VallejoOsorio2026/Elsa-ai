# Cierre del subbloque R1.B — ingesta y publicación persistentes del corpus PR-100 en TEST

- **Fecha:** 2026-11-08.
- **Estado:** documento de cierre de **R1.B**. **Es efectivo solo cuando quede integrado en `main` con el CI
  obligatorio en verde.** Operativamente, R1.B terminó con G-P el 2026-11-08 (§8.7).
- **Qué cierra:** el subbloque **R1.B** del bloque R1 («RAG local real en PC1 por CLI»):
  - la herramienta de operación documental (`elsa.tools.documents_admin`);
  - el corpus sintético PR-100 y su evaluación;
  - las precondiciones G-0;
  - la carga G-W;
  - el Ctrl+Z de las publicaciones (PR #69, ADR 0038) y su migración en TEST (G-M.1);
  - la publicación G-P.
- **Qué NO cierra:** **no cierra R1**, ni inicia R1.C ni R1.D.
- **Qué NO acredita:** el RAG semántico, BGE-M3, la generación de embeddings ni Phi.
- **Prerrequisitos:** el cierre de R1.A ([`r1-a-entorno-supabase-test-cierre.md`](r1-a-entorno-supabase-test-cierre.md)).
- **Decisión técnica:** el [ADR 0038](adr/0038-retirada-auditable-de-publicaciones-documentales.md), retirada
  auditable de publicaciones, que amplía el [ADR 0012](adr/0012-ciclo-de-vida-documental-propio.md).
- **Marcas** (`docs/project/BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**, **HECHO DEL REPOSITORIO**,
  **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Procedencia de lo medido:**
  - Los **HECHO MEDIDO** de PC1 salen de comandos que ejecutaron sesiones de Claude Code en la máquina que se
    presume PC1 (§10, §12).
  - Lo de GitHub se consultó en su API pública.
  - Lo que comprobó Juan fuera de las sesiones se marca como medido por él.
- **Sanitización:**
  - Sin secretos, cadenas de conexión ni contraseñas.
  - Sin rutas de perfil de usuario: las rutas locales se escriben con `%LOCALAPPDATA%`.
  - Sin contenido de filas fuera del corpus sintético.
  - Del UUID del operador solo se registra el prefijo.
  - Los UUID de las versiones son identificadores del corpus sintético y ya figuran en el runbook.

---

## 1. Objetivo

Dejar en el ambiente **TEST** (`papelsa-elsa`) un conocimiento documental **persistente, publicado y
reversible**: el corpus sintético PR-100 ingerido con su procedencia, sus tres primeras versiones publicadas y
la cuarta pendiente. Todo con una herramienta de operación reproducible y con un Ctrl+Z comprobado antes de
publicar. Es la base sobre la que R1.C generará los embeddings.

## 2. Alcance

**Dentro:**

- **R1.B.1:** la CLI `elsa.tools.documents_admin`, con `status`, `create-asset`, `create-document`, `ingest`,
  `approve`, `reject` y `publish`. Cada transición es un comando aparte (regla 16).
- **R1.B.2:**
  - el corpus PR-100 (`bench/corpus-sintetico/`);
  - la evaluación de 15 preguntas (`bench/r1/evaluacion.json`);
  - el runbook [`r1-b-operacion-ingesta.md`](r1-b-operacion-ingesta.md).
- **G-0:** precondiciones de las escrituras.
  - G-0.1: verificación de Render.
  - G-0.2: corrección de la inconsistencia DEV/TEST del `.env` de PC1.
  - G-0.3: validación de ELSA local bajo TEST.
- **G-W:** 2 activos, 3 documentos y 4 ingestas en TEST.
- **Ctrl+Z:** la operación `withdraw`, el ADR 0038 y la migración `20261103010000` (PR #69).
- **G-M.0 / G-M.1:** preparación y aplicación de esa migración en TEST.
- **G-P:** aprobación y publicación de las tres v1.
- Este documento, y el paso del ADR 0038 de `propuesto` a `aceptado`.

**Fuera, de forma explícita:**

- Embeddings, el registro de BGE-M3, la recuperación semántica real y Phi: corresponden a R1.C y R1.D.
- Exponer el ciclo documental o `withdraw` por HTTP.
- Datos reales de PAPELSA, y cualquier documento distinto del corpus PR-100.
- El rol de servicio con privilegios mínimos (§20).
- Cambios en Render, en Materiales o en los permisos.
- El activo preexistente `tampella`, que no se tocó.

## 3. Estado inicial

- **HECHO DEL REPOSITORIO:** `main` en `70ceb8e`, el merge del cierre de R1.A (PR #67). No existía ninguna
  herramienta de operación documental persistente.
- **HECHO MEDIDO (R1.A, §8.4 y §19 de su cierre):**
  - `papelsa-elsa` tenía las cinco migraciones `20260905020000` … `20260913010000` y pgvector 0.8.2.
  - El corpus documental estaba vacío y no había ningún modelo de embeddings.
- **HECHO MEDIDO (R1.A):** el `.env` de PC1 decía `ELSA_ENV=DEV` y apuntaba a `papelsa-elsa`, que es TEST.
  R1.A dejó esa inconsistencia como pendiente.
- **HECHO MEDIDO (G-P, Fase A):** en `elsa.technical_assets` había un activo preexistente, `tampella`, sin
  documentos. Su origen no se investigó: R1.A había dejado la indicación de no tocar los registros existentes.

## 4. Trabajo realizado

En orden:

1. **Planificación de R1.B.** Juan la aprobó con ajustes (§5).
2. **R1.B.1 y R1.B.2** (`523d0e4`): la CLI, sus pruebas en memoria y en PostgreSQL efímero, el corpus, la
   evaluación y el runbook.
3. **Corrección del runbook** (`e0855d2`). En la revisión, Juan detectó que la v2 de la prensa se ingería
   después de G-P. Se movió a G-W, de modo que G-P no contiene ninguna ingesta. Merge del PR #68 en `c2f2044`.
4. **G-0:**
   - G-0.1: guía para revisar Render y verificación de Juan en el panel (§8.1).
   - G-0.2: respaldo del `.env` con permisos restringidos y cambio de exactamente tres variables (§8.2).
   - G-0.3: arranque de ELSA local bajo TEST, `status` y parada ordenada (§8.2).
5. **G-W:** la ejecutó otra sesión de Claude Code (§10), el 2026-11-03 entre las 21:44 y las 21:48 UTC (§8.3).
6. **G-P, primera evaluación.** Al preparar G-P se comprobó que **no existía un Ctrl+Z para una publicación**.
   Juan fijó entonces una regla permanente: toda modificación que pueda afectar el funcionamiento necesita
   antes una reversión comprobada. G-P quedó bloqueado (§5).
7. **Ctrl+Z** (`ea11490`, `b6f3c22`, PR #69, merge en `4ede3b2`):
   - la operación `withdraw` (`published → approved` con un evento `withdrawn`);
   - el ADR 0038;
   - la migración `20261103010000` y su rollback;
   - las pruebas y el runbook de G-P.
8. **G-M.0:** preparación en solo lectura de la migración en TEST, con instantánea y wrappers (§8.5).
9. **G-M.1:** dry-run y aplicación única de `20261103010000` en TEST, con verificación posterior (§8.6).
10. **G-P:** seis operaciones, una a una, con `status` después de cada una y verificación final (§8.7).
11. **Este cierre:** la verificación final en solo lectura (§8.8) y la actualización del estado del ADR 0038.

## 5. Decisiones

| Decisión | Quién | Motivo |
|---|---|---|
| **DECISIÓN TOMADA:** R1 se demuestra en `papelsa-elsa` como TEST, solo con datos sintéticos | Juan (R1.A) | No existe un proyecto DEV remoto aparte |
| **DECISIÓN TOMADA:** si `status` encuentra un código ya presente, la operación se detiene: no se renombra ni se reutiliza | Juan (plan de R1.B) | Evitar mezclar el corpus con registros previos |
| **DECISIÓN TOMADA:** rechazar y reemplazar no son eliminación de datos, y no deben presentarse como tal | Juan (plan de R1.B) | El modelo documental no borra |
| **DECISIÓN TOMADA:** la v2 de la prensa se ingiere en G-W y G-P no contiene ingestas | Juan (revisión del PR #68) | G-P debe ser solo aprobar y publicar |
| **DECISIÓN TOMADA:** en G-0.2, el respaldo del `.env` solo es accesible para la cuenta operadora, SYSTEM y Administradores; si no se pudiera garantizar, no se modifica el `.env` | Juan | Que el respaldo no herede permisos de `CodexSandboxUsers` |
| **DECISIÓN TOMADA:** `%LOCALAPPDATA%\ELSA\artifacts` queda aceptado **solo para el corpus sintético** | Juan | Fuera de OneDrive y del repositorio. No para documentación real |
| **DECISIÓN TOMADA:** el exit 3 de uvicorn al detenerse en G-0.3 es una observación no bloqueante | Juan | La parada fue ordenada y el puerto quedó libre (§8.2) |
| **DECISIÓN TOMADA:** G-0.1 lo verifica el administrador de Render directamente en el panel, sin navegador integrado ni credenciales compartidas | Juan | §8.1 |
| **DECISIÓN TOMADA:** el actor de G-W y G-P es el UUID del operador autorizado (`9ae501b3-…`), comunicado por Juan | Juan | `--actor` identifica al operador en la auditoría. **No es una autenticación**: la CLI no comprueba identidades |
| **DECISIÓN TOMADA:** regla permanente: antes de modificar algo que pueda afectar el funcionamiento, debe existir un Ctrl+Z comprobado | El responsable de PAPELSA, comunicado por Juan | Una copia de seguridad no basta |
| **DECISIÓN TOMADA:** el Ctrl+Z es `published → approved` con el evento `withdrawn` y motivo obligatorio, sin estado nuevo | Juan; [ADR 0038](adr/0038-retirada-auditable-de-publicaciones-documentales.md) | `rejected` y `superseded` no cambian de significado y la versión puede volver a publicarse |
| **DECISIÓN TOMADA:** la migración se aplica con `supabase db push --db-url`, no `--linked` | La sesión de Claude Code, autorizada por Juan en G-M.1 | En R1.A, `--linked` intentó crear un rol temporal en el remoto (§13) |
| **DECISIÓN TOMADA:** `tampella` no es un conflicto para G-P y debe permanecer intacto | Juan (G-P) | G-P solo trabaja con los dos activos del corpus |

## 6. Pruebas

**PR #68 (R1.B.1 y R1.B.2):**

- **HECHO MEDIDO (GitHub):** CI `success` en `e0855d2`, en los runs `41701441200` y `41701451642`, y en el
  merge `c2f2044` (run `41706762150`). Los dos jobs son «Lint, types and tests» y «Secret scan (gitleaks)».
- **HECHO DEL REPOSITORIO:** `tests/test_documents_admin.py` ejecuta, en memoria y en PostgreSQL, la misma
  secuencia del runbook. Comprueba que la evaluación se sostiene sobre los fragmentos reales.
- **HECHO MEDIDO (PC1):** la suite completa local no terminó. Se cortó por el límite de 900 s, hacia el 74 %, y
  no hay resumen. La evidencia completa es la de CI.

**PR #69 (Ctrl+Z):**

- **HECHO MEDIDO (PC1):**
  - Suites del cambio: `88 passed, 127 skipped`. Lo omitido son los casos de PostgreSQL, porque en PC1 no había
    PostgreSQL.
  - Suite completa: `2 failed, 3027 passed, 271 skipped in 2568.69s`. Los 2 fallos están en
    `tests/test_bench_harness.py` y vienen de `main` (§13).
  - pre-commit (ruff, formato, gitleaks): todo `Passed`.
  - mypy `--platform linux`: `Success: no issues found in 265 source files`.
- **HECHO MEDIDO (GitHub):** CI `success` en `b6f3c22` (runs `41753501704` y `42486138055`) y en el merge
  `4ede3b2` (run `42486765615`). En los dos casos terminaron en `success` los pasos Initialize containers
  (`pgvector/pgvector:pg16`), Ruff lint, Ruff format, mypy y Tests.
- **INFERENCIA:** las pruebas de PostgreSQL se ejecutaron en CI y no se omitieron.
  - El log solo se lee con sesión de GitHub y la sesión no inició ninguna.
  - Solo se omiten si falta `ELSA_TEST_DATABASE_URL` (`tests/db.py`), y CI la define (`.github/workflows/ci.yml`).
  - Si la base fallara, el resultado sería un error y no una omisión.

**Operativas en TEST:** **HECHO MEDIDO**, siempre en transacciones de solo lectura salvo las escrituras
autorizadas.

- G-0.3, `status` antes de G-W (§8.2).
- G-M.1: antes, dry-run, aplicación y después (§8.6).
- G-P: `status` después de cada una de las seis operaciones (§8.7).
- Verificación final de este cierre (§8.8).

**Las pruebas de CI no sustituyen a las de TEST.** CI demuestra el comportamiento del código sobre PostgreSQL
16 efímero. TEST es PostgreSQL 17.6, y su estado solo lo acreditan las lecturas de §8.

## 7. Comandos relevantes

Desde la raíz del repositorio, con el `.env` de TEST (§8.2). La secuencia completa, con el Ctrl+Z, está en
[`r1-b-operacion-ingesta.md`](r1-b-operacion-ingesta.md) §1 a §6.

```powershell
$tool = "elsa.tools.documents_admin"
$actor = "<UUID del operador autorizado>"
uv run --offline python -m $tool status --domain mantenimiento
uv run --offline python -m $tool approve --version <uuid> --actor $actor
uv run --offline python -m $tool publish --version <uuid> --actor $actor
uv run --offline python -m $tool withdraw --version <uuid> --actor $actor --reason "<motivo>"   # Ctrl+Z
```

**Migración (G-M.1).** La sesión usó tres scripts temporales que **no están versionados**:

- `gm_inspect.py`: lecturas `READ ONLY` y una instantánea;
- `gm_cli.py`: envoltura de la CLI que enmascara la URL;
- `gm_rollback.py`: el rollback.

El equivalente reproducible es:

```powershell
supabase db push --dry-run --db-url <cadena de TEST, sin imprimirla>
supabase db push --db-url <cadena de TEST, sin imprimirla>
# Ctrl+Z, solo mientras no existan eventos `withdrawn`:
#   1. ejecutar supabase/rollback/20261103010000_rollback.sql en una transacción
#   2. supabase migration repair --status reverted 20261103010000 --db-url <…>
```

## 8. Resultados

### 8.1 G-0.1 — Render

**HECHO MEDIDO por Juan** (procedencia: capturas del panel de Render aportadas por él). En `elsa-demo` y
`elsa-relay-pilot`:

- **no** aparece `ELSA_DATABASE_URL` entre las variables de entorno visibles;
- **no** hay grupos de entorno vinculados.

G-0.1 está **cerrado**.

- **Alcance:** los dos servicios, en el momento de la revisión, en lo que muestra el panel.
- **Limitaciones:**
  - La sesión no vio el panel.
  - No consta que se revisaran los Secret Files.
  - Un cambio posterior en Render no queda cubierto.

**INFERENCIA:** Render no está conectado a `papelsa-elsa`. Las escrituras de G-W y G-P no afectan a la demo de
Render, que es otro entorno.

### 8.2 G-0.2 y G-0.3 — `.env` de PC1 y validación bajo TEST

**HECHO MEDIDO**, salida de G-0.2 (solo nombres de variables, ningún valor):

```text
bom=True newline=CRLF
other lines unchanged: True
ELSA_ENV line now: ELSA_ENV=TEST
added keys: ['ELSA_ARTIFACT_STORAGE_BACKEND', 'ELSA_ARTIFACT_STORAGE_ROOT']
root under OneDrive: False
```

- **Respaldo previo:** `%LOCALAPPDATA%\ELSA\backup-g0\env-pre-g0.bak`, de 2182 bytes. Su hash coincide con el
  original y su ACL está protegida: cuenta operadora, SYSTEM y Administradores.

**HECHO MEDIDO**, salida de G-0.3 (ELSA local, sin agente ni relay):

```text
[config] env=TEST port=8000
[readiness] ready_degraded
[ready] http=200 status=degraded env=TEST
[ready]   artifact_storage: ok critical=True
[ready]   auth: ok critical=True
[ready]   database: ok critical=True
[ready]   embeddings: not_configured critical=False
[ready]   llm: not_configured critical=False
[ready]   materials: degraded critical=False
[ready]   ocr: not_configured critical=False
[ready]   reranker: not_configured critical=False
[ready]   transcription: degraded critical=False
[documents_admin status] exit=0
[documents_admin]   activo prensa-ejemplo: ausente
[documents_admin]   activo bomba-ejemplo: ausente
[documents_admin]   documento mantenimiento/prensa-manual: ausente
[documents_admin]   documento mantenimiento/prensa-nota-en: ausente
[documents_admin]   documento mantenimiento/bomba-manual: ausente
[stop] graceful, exit=3
[stop] port free afterwards: True
```

### 8.3 G-W — carga del corpus

**HECHO MEDIDO por la sesión `4e08b932-…`** (§10). Su transcripción registra las salidas de la CLI:
`activo creado` para `prensa-ejemplo` y `bomba-ejemplo`, y estas cuatro:

```text
versión creada: v1 pending_validation 9863f1a6-e869-4f0d-88db-bae83cd4edb8
versión creada: v1 pending_validation 0fd1d77d-4d68-4fe6-8158-ffe545908a72
versión creada: v1 pending_validation 78d38091-604a-434c-b45c-52c21d7dfc42
versión creada: v2 pending_validation 5b64b985-1895-467b-a658-7f30b342b11e
```

**HECHO MEDIDO por esta sesión**, verificación independiente con `status`, antes de G-P:

```text
documento mantenimiento/bomba-manual: presente (activo bomba-ejemplo)
  v1 pending_validation 78d38091-604a-434c-b45c-52c21d7dfc42 chunks=10
documento mantenimiento/prensa-manual: presente (activo prensa-ejemplo)
  v1 pending_validation 9863f1a6-e869-4f0d-88db-bae83cd4edb8 chunks=13
  v2 pending_validation 5b64b985-1895-467b-a658-7f30b342b11e chunks=13
documento mantenimiento/prensa-nota-en: presente (activo prensa-ejemplo)
  v1 pending_validation 0fd1d77d-4d68-4fe6-8158-ffe545908a72 chunks=6
exit=0
```

### 8.4 Ctrl+Z — PR #69

**HECHO DEL REPOSITORIO:**

- `withdraw_version` está en `DocumentRepositoryPort` y en los adaptadores de memoria y de PostgreSQL. El de
  PostgreSQL trabaja en una transacción, con el documento y la versión bloqueados.
- El comando `withdraw --version --actor --reason` está en la CLI.
- Las pruebas cubren:
  - retirada, conservación de fragmentos e historial, y nueva publicación;
  - negativas sin escritura: pendiente, aprobada, sin motivo, repetida, reemplazada e inexistente;
  - aislamiento por documento;
  - exclusión de los canales exacto, léxico y semántico;
  - reversión de la transacción ante un fallo;
  - concurrencia entre pools;
  - migración idempotente, rollback limpio y rollback rechazado.

### 8.5 G-M.0 — estado de TEST antes de la migración

**HECHO MEDIDO** (`transaction_read_only=on`):

```text
migrations_remote=['20260905020000', '20260906010000', '20260908010000', '20260912010000', '20260913010000']
migrations_pending=['20261103010000']
remote_not_in_repo=[]
ck_document_event: CHECK ((event = ANY (ARRAY['created'::text, 'approved'::text, 'rejected'::text, 'published'::text, 'superseded'::text])))
ck_document_event_reason: CHECK (((event <> 'rejected'::text) OR ((reason IS NOT NULL) AND (btrim(reason) <> ''::text))))
withdrawn_events_total=0
rows_violating_new_constraints=0
documents_total=3 documents_outside_corpus=0
chunks_corpus=42
events_corpus=created=4
versions_published_total=0
```

### 8.6 G-M.1 — aplicación de la migración

**HECHO MEDIDO**, dry-run:

```text
{"upToDate":false,"dryRun":true,"migrations":["20261103010000_allow_document_publication_withdrawal.sql"],"seeds":[],"roles":[],"message":"Finished supabase db push."}
Would push these migrations:
 • 20261103010000_allow_document_publication_withdrawal.sql
[supabase db push --dry-run] exit=0
```

**HECHO MEDIDO**, aplicación (una sola vez, sin reintentos):

```text
{"upToDate":false,"dryRun":false,"migrations":["20261103010000_allow_document_publication_withdrawal.sql"],"seeds":[],"roles":[],"message":"Finished supabase db push."}
Applying migration 20261103010000_allow_document_publication_withdrawal.sql...
[supabase db push --yes] exit=0
```

**HECHO MEDIDO**, diferencias entre las instantáneas de antes y de después. Son **exactamente estas cuatro**;
las columnas del historial, el resto de restricciones, RLS y el disparador no cambiaron:

```text
=> migrations_remote=[… '20260913010000', '20261103010000']
=> migrations_pending=[]
=> ck_document_event: CHECK ((event = ANY (ARRAY[… 'superseded'::text, 'withdrawn'::text])))
=> ck_document_event_reason: CHECK (((event <> ALL (ARRAY['rejected'::text, 'withdrawn'::text])) OR ((reason IS NOT NULL) AND (btrim(reason) <> ''::text))))
```

**HECHO MEDIDO:** después, `documents_admin withdraw --help` devolvió exit 0. Una búsqueda en `supabase/.temp`,
`~/.supabase`, el historial de PSReadLine y las carpetas de la sesión encontró **0** archivos con la cadena de
conexión.

### 8.7 G-P — publicación

**HECHO MEDIDO.** Todas las operaciones usaron el actor `9ae501b3-…` y se ejecutaron una a una. Después de cada
una se corrió `status`.

| # | Operación | Versión | Salida | Exit |
|---|---|---|---|---|
| 1 | `approve` | prensa-manual v1 | `aprobada: v1 approved 9863f1a6-…` | 0 |
| 2 | `publish` | prensa-manual v1 | `publicada: v1 published 9863f1a6-…` | 0 |
| 3 | `approve` | prensa-nota-en v1 | `aprobada: v1 approved 0fd1d77d-…` | 0 |
| 4 | `publish` | prensa-nota-en v1 | `publicada: v1 published 0fd1d77d-…` | 0 |
| 5 | `approve` | bomba-manual v1 | `aprobada: v1 approved 78d38091-…` | 0 |
| 6 | `publish` | bomba-manual v1 | `publicada: v1 published 78d38091-…` | 0 |

`status` final:

```text
documento mantenimiento/bomba-manual: presente (activo bomba-ejemplo)
  v1 published 78d38091-604a-434c-b45c-52c21d7dfc42 chunks=10
documento mantenimiento/prensa-manual: presente (activo prensa-ejemplo)
  v1 published 9863f1a6-e869-4f0d-88db-bae83cd4edb8 chunks=13
  v2 pending_validation 5b64b985-1895-467b-a658-7f30b342b11e chunks=13
documento mantenimiento/prensa-nota-en: presente (activo prensa-ejemplo)
  v1 published 0fd1d77d-4d68-4fe6-8158-ffe545908a72 chunks=6
status_exit=0
```

Diferencias entre la instantánea anterior a G-P y la posterior: solo los tres cambios de estado, los seis
eventos nuevos (`approved` y `published` del mismo actor) y `versions_published_total`, que pasa de 0 a 3. Las
huellas md5 de las filas de los tres activos son idénticas antes y después, `tampella` incluido.

### 8.8 Verificación final de este cierre (2026-11-08, solo lectura)

**HECHO MEDIDO:**

```text
env=TEST targets_papelsa_elsa=True
read_only=on
state=pending_validation versions=1 chunk_count_declared=13 chunks_stored=13
state=published versions=3 chunk_count_declared=29 chunks_stored=29
published_chunks_view=29
event=created n=4 actors=1 first=2026-11-03 21:47:00+0000 last=2026-11-03 21:47:58+0000
event=approved n=3 actors=1 first=2026-11-08 14:18:10+0000 last=2026-11-08 14:20:36+0000
event=published n=3 actors=1 first=2026-11-08 14:18:41+0000 last=2026-11-08 14:21:15+0000
source_artifacts=4
document_ingestion_runs=4
document_sections=32
embedding_models=0
embedding_runs=0
document_chunk_embeddings=0
runs_by_status=completed:4
artifact_files_present_locally=4/4
migrations_remote=['20260905020000', '20260906010000', '20260908010000', '20260912010000', '20260913010000', '20261103010000']
migrations_pending=[]
withdrawn_events_total=0
documents_total=3 documents_outside_corpus=0
asset_row_md5 bomba-ejemplo=f9387ff1a9669e11f9c327a59a329997
asset_row_md5 prensa-ejemplo=80c486a904b013d4aa9cf6fcd560fc9e
asset_row_md5 tampella=22d65a7113bc11093050e08dbec212a2
chunks_corpus=42
events_corpus=approved=3, created=4, published=3
versions_published_total=3
```

## 9. Métricas

Todas son **HECHO MEDIDO** con las lecturas de §8.8.

| Medida | Valor |
|---|---|
| Activos del corpus / activos totales | 2 / 3 (`tampella` es preexistente) |
| Documentos | 3, ninguno fuera del corpus |
| Versiones | 4: 3 `published` y 1 `pending_validation` |
| Fragmentos **almacenados** | 42 (10 + 13 + 13 + 6) |
| Fragmentos **publicados** (recuperables por alcance) | 29, contados en la vista de procedencia |
| Fragmentos de la v2 pendiente | 13, no recuperables |
| Secciones | 32 |
| Archivos fuente | 4 registrados; los 4 presentes en `%LOCALAPPDATA%\ELSA\artifacts` |
| Ejecuciones de ingesta | 4 `completed` |
| Eventos del corpus | 4 `created` (2026-11-03), 3 `approved` y 3 `published` (2026-11-08), con un solo actor |
| Eventos `withdrawn` | 0 |
| Embeddings y modelos | 0 |
| Migraciones en TEST | 6 |
| Duración de G-P | 14:18:10 a 14:21:15 UTC: 3 min 5 s para las seis operaciones y sus `status` |

No hay métricas de rendimiento: R1.B no mide latencias ni calidad de recuperación.

## 10. Aportes de Claude Code

- **Sesión `3d38ede2-50f8-47ef-9185-1b8a2b657ce1`** (app de escritorio; el identificador figura en las rutas de
  la sesión). La misma sesión que R1.A. Hizo:
  - la planificación de R1.B;
  - los commits `523d0e4`, `e0855d2`, `ea11490` y `b6f3c22`;
  - G-0;
  - la evaluación que bloqueó G-P;
  - G-M.0, G-M.1 y G-P;
  - este documento.
- **Sesión `4e08b932-ec20-4d88-b2f5-4593ec19e6ff`.** Ejecutó G-W el 2026-11-03 entre las 21:44 y las 21:48 UTC.
  El identificador es el de su transcripción local en PC1, que contiene las salidas de §8.3. Esta sesión
  verificó su resultado de forma independiente (§8.3).
- No consta que se invocaran los subagentes de revisión.

## 11. Aportes de Codex

Nada que registrar.

## 12. Operaciones manuales y de PowerShell

**Juan:**

- las decisiones y autorizaciones de §5;
- la verificación de Render (§8.1);
- la apertura y el merge de los PR #68 y #69 en GitHub, porque la sesión no tenía `gh`;
- la comunicación del UUID del operador.

**Las sesiones de Claude Code, en PC1:**

- la CLI `documents_admin`;
- la edición controlada del `.env` (G-0.2);
- el arranque y la parada de ELSA local (G-0.3);
- `supabase db push --dry-run` y `db push`, mediante la envoltura;
- las lecturas de solo lectura con asyncpg;
- las instantáneas, guardadas en `%LOCALAPPDATA%\ELSA\backup-gm\`:
  - `pre-20261103010000.txt`
  - `pre-gm1-20261108-090252.txt`
  - `post-gm1-20261108-090419.txt`
  - `pre-gp-20261108-091119.txt`
  - `pre-gp-assets-20261108-091738.txt`
  - `post-gp-20261108-092140.txt`

  La hora del nombre es la local de PC1. La carpeta está fuera de OneDrive, con la herencia de permisos cortada,
  y solo pueden abrirla la cuenta operadora, SYSTEM y Administradores.

**PENDIENTE:** la identidad física de PC1 sigue siendo **probable, no acreditada** (R1.A).

## 13. Incidentes

| Incidente | Qué se hizo |
|---|---|
| El runbook ingería la v2 después de G-P | Juan lo detectó en la revisión; corregido en `e0855d2` |
| La suite completa local de R1.B.1 superó el límite de 900 s | Declarado; la evidencia completa es la de CI |
| G-W no podía empezar: faltaba el UUID real del operador | STOP antes de escribir. Juan lo aportó |
| Al preparar G-P no existía ningún Ctrl+Z para una publicación | G-P bloqueado. Se implementó `withdraw` (PR #69) antes de publicar |
| Docker Desktop no estaba en marcha en PC1, así que las pruebas de PostgreSQL se omitieron en local | No se arrancó ni se instaló. La evidencia de PostgreSQL es la de CI |
| La suite completa local de PR #69 dio 2 fallos (`tests/test_bench_harness.py`) | Vienen de `main`: el test y `src/elsa/bench/` son idénticos. En Windows no existe el módulo POSIX `resource` |
| mypy da 3 errores en `src/elsa/bench/runner.py` en Windows | El archivo es idéntico al de `main`; con `--platform linux` no hay errores |
| El log de CI solo se lee con sesión de GitHub | No se inició sesión. La ejecución de PostgreSQL en CI queda como inferencia (§6) |
| No había `gh` en PC1 | Los PR los abrió Juan con el enlace de comparación |
| Un reemplazo hecho con PowerShell 5.1 estropeó las tildes de los comentarios de `gm_cli.py` | Detectado antes de ejecutarlo; el archivo se reescribió en UTF-8. Sin efecto en TEST |
| `withdraw --help` devolvió exit `-1` | Lo causó un `Select-Object -First` que cortó la salida; repetido sin cortar, exit 0 |
| El documento de instrucciones de G-P llegó cortado | STOP después de las fases de lectura; Juan reenvió el resto |
| El ref local `main` estaba en `c2f2044` durante G-M y G-P | No se modificó. El árbol de trabajo era idéntico al de `origin/main`, comprobado con hashes |
| Al detenerse en G-0.3, uvicorn salió con exit 3 | Parada ordenada y puerto libre. Juan lo aceptó como observación |

## 14. Git

- **PR #68:** código, pruebas, corpus, evaluación y runbook.
- **PR #69:** código, migración, rollback, ADR y runbook.
- **Este PR:** solo documental, con este cierre y el estado del ADR 0038.
- No hubo push a `main`, force ni tags. Los merges los hizo Juan.

## 15. Ramas

| Rama | Uso | Estado |
|---|---|---|
| `claude/r1-b-ingesta-persistente` | R1.B.1 y R1.B.2 | Fusionada (PR #68) |
| `claude/r1-b-withdraw-publication` | Ctrl+Z | Fusionada (PR #69) |
| `claude/r1-b-cierre` | Este cierre | En revisión |

## 16. Commits

| Commit | Mensaje |
|---|---|
| `523d0e4` | feat(documents): add a persistent document operations CLI for R1.B |
| `e0855d2` | docs(r1): move the press v2 ingestion into the G-W phase |
| `c2f2044` | Merge del PR #68 |
| `ea11490` | feat(documents): add an auditable withdrawal of document publications |
| `b6f3c22` | docs(r1): document the G-P publication and its withdraw Ctrl+Z |
| `4ede3b2` | Merge del PR #69 |

El commit de este cierre está en el PR de §17.

## 17. Pull requests

| PR | Título | Estado | CI |
|---|---|---|---|
| [#68](https://github.com/VallejoOsorio2026/Elsa-ai/pull/68) | feat(documents): add a persistent document operations CLI for R1.B | Fusionado el 2026-11-03 | `success` |
| [#69](https://github.com/VallejoOsorio2026/Elsa-ai/pull/69) | R1.B — Retirada auditable de publicaciones documentales (Ctrl+Z) | Fusionado el 2026-11-08 | `success`, también después del merge |
| Este cierre | docs(r1): close R1.B | Pendiente de CI, revisión y merge | — |

## 18. Migraciones

- **Escrita:** `20261103010000_allow_document_publication_withdrawal.sql`, con su rollback
  `supabase/rollback/20261103010000_rollback.sql` (PR #69). Solo amplía dos restricciones de
  `elsa.document_version_events` y no toca datos.
- **Aplicada:** en `papelsa-elsa` (TEST), en G-M.1, el 2026-11-08 entre las instantáneas de las 09:02:52 y las
  09:04:19, hora local de PC1. Contaba con la **autorización expresa de Juan en la misma conversación**, solo
  para esa migración (regla 15).
- **Estado del historial:** **HECHO MEDIDO**, seis migraciones; las cinco iniciales y `20261103010000`.
- **Ctrl+Z de la migración:** el rollback abre su propia transacción y **se niega** en cuanto existe un evento
  `withdrawn`. Hoy hay 0, así que sigue disponible.
- **Limitación:** después del primer `withdrawn`, la vuelta atrás es por compensación (`publish`) y no por
  eliminación de historial.
- **G-P se ejecutó después de** verificar que la migración estaba aplicada y que `withdraw` estaba disponible.

## 19. Estado operacional final

| Pieza | Estado |
|---|---|
| Corpus **almacenado** en TEST | 3 documentos, 4 versiones, 42 fragmentos, 32 secciones y 4 archivos fuente |
| Corpus **publicado** | 3 versiones v1, con 29 fragmentos, recuperables dentro de su alcance (`mantenimiento/prensa-ejemplo` o `mantenimiento/bomba-ejemplo`) |
| `prensa-manual` v2 | `pending_validation`, no recuperable. Es la trampa de versión de la evaluación |
| Recuperación **documental** | **HECHO MEDIDO:** la vista `document_chunk_provenance`, sobre la que filtran los canales exacto y léxico, expone exactamente los 29 fragmentos publicados. **INFERENCIA:** esos canales los devuelven en TEST. Está probado en CI, pero no se ejecutó una búsqueda contra TEST |
| Recuperación **semántica** | **No disponible:** no hay modelos ni embeddings. Corresponde a R1.C |
| LLM (Phi) | Sin ejecutar. Corresponde a R1.D |
| Ctrl+Z de las publicaciones | Disponible: `withdraw` para cada v1 (runbook §5). **Retira una publicación; no revierte el estado completo**: la versión queda `approved` y el historial conserva ambos eventos |
| Ctrl+Z de la migración | Disponible mientras haya 0 eventos `withdrawn` |
| `tampella` | Intacto: misma huella md5 de la fila antes y después de G-P |
| `.env` de PC1 | `ELSA_ENV=TEST` y almacén de artefactos `local` fuera de OneDrive |
| Render (`elsa-demo`, `elsa-relay-pilot`) | Otro entorno. Según la verificación de Juan, no apunta a `papelsa-elsa` (§8.1) |

## 20. Pendientes

**Riesgos aceptados**, conocidos y que no bloquean R1:

| Pendiente | Responsable |
|---|---|
| **PENDIENTE (P1):** ELSA se conecta a TEST como `postgres`, el superusuario. Hace falta un rol de servicio con privilegios mínimos, mediante migración versionada | Juan |
| **PENDIENTE (prioritario):** el `.env` de PC1 vive dentro del repositorio, en una carpeta sincronizada por OneDrive | Juan; tarea aparte |
| **PENDIENTE:** los archivos fuente del corpus solo existen en `%LOCALAPPDATA%\ELSA\artifacts` de PC1. Si se pierden, las versiones conservan hash y procedencia, pero no los bytes. Para el corpus sintético basta con reingerir en otro entorno desde `bench/` | Juan |

**Problemas operativos abiertos:**

| Pendiente | Responsable |
|---|---|
| **PENDIENTE:** confirmar la identidad física de PC1 | Operador |
| **PENDIENTE:** el ref local `main` de PC1 está desactualizado. Basta con `git switch main` y `git pull --ff-only` cuando se decida | Operador |
| **PENDIENTE:** `tests/test_bench_harness.py` (2 tests) no pasa en Windows | Bloque aparte |
| **PENDIENTE:** mypy da 3 errores en `src/elsa/bench/runner.py` solo en Windows | Bloque aparte |
| **PENDIENTE (P2):** salida limpia de `embeddings_admin` cuando falla la configuración (R1.A) | Bloque aparte |

**Capacidades futuras** (no son deuda):

| Pendiente | Bloque |
|---|---|
| Fijar la revisión de BGE-M3, registrar el modelo y generar los embeddings de las 3 versiones publicadas | R1.C |
| Evaluación de las 15 preguntas con Phi sobre la recuperación real | R1.D |

## 21. Siguiente bloque

**R1.C — embeddings reales con BGE-M3 en PC1:**

1. fijar una revisión concreta del modelo;
2. registrarlo con `embeddings_admin`;
3. generar los embeddings de los 29 fragmentos publicados;
4. comprobar la recuperación semántica en TEST.

**Requiere autorización expresa de Juan** y, por la regla permanente, un Ctrl+Z comprobado para sus escrituras
antes de empezar.

---

## Qué acredita R1.B

- Una herramienta de operación documental persistente, con una transición por comando y negativas antes de
  escribir.
- El corpus PR-100 está en TEST con su procedencia completa: 42 fragmentos almacenados y 29 publicados.
- Las publicaciones son **reversibles** con `withdraw`, probado en CI y disponible en TEST.
- Toda transición quedó en el historial append-only, con un único actor registrado.
- La migración del Ctrl+Z se aplicó una sola vez, con dry-run y verificación, y conserva su rollback.
- `tampella` y el resto de la base no se tocaron.

## Qué no acredita R1.B

- La recuperación semántica, BGE-M3, los embeddings ni la generación con Phi.
- Una búsqueda ejecutada contra TEST (la recuperación documental en TEST es inferencia, §19).
- Que `--actor` autentique a nadie: solo registra a quién se atribuye la operación.
- Que ningún cambio posterior en Render conecte la demo a TEST.
- La identidad física de PC1.
- Que la credencial de servicio tenga privilegios mínimos (no los tiene).

## Criterios de cierre

| Criterio | Estado |
|---|---|
| CLI documental con transiciones separadas | Cumplido (PR #68) |
| Corpus y evaluación verificados sobre los fragmentos reales | Cumplido (PR #68, CI) |
| G-0 resuelto (G-0.1, G-0.2 y G-0.3) | Cumplido (§8.1, §8.2) |
| G-W: 2 activos, 3 documentos y 4 versiones pendientes | Cumplido (§8.3) |
| Ctrl+Z comprobado antes de publicar | Cumplido (PR #69, G-M.1) |
| G-P: 3 publicadas, la v2 pendiente, 42 fragmentos, `tampella` intacto | Cumplido (§8.7, §8.8) |
| Documento de cierre en `main` con CI en verde | Pendiente de este PR |

## Regla de continuidad

R1.B queda cerrado formalmente cuando este documento esté en `main` con el CI obligatorio en verde. R1.C no
empieza sin autorización expresa.

## Veredicto

R1.B terminó operativamente. TEST contiene el corpus PR-100 persistente, con tres versiones publicadas y
reversibles y la cuarta pendiente. Es la base que R1.C necesita para generar los embeddings.
