# Bloque 4.1.b: persistencia documental PostgreSQL

Estado al 11 de septiembre de 2026: adaptador implementado y verificado
localmente. El cierre del bloque y la preparación de PR quedan pendientes de la
decisión sobre la restricción relacional descrita abajo. **No se ha creado,
modificado ni aplicado una migración nueva.**

Rama: `codex/bloque-4-1b-postgres-documents`. Continuación del checkpoint WIP
`4caa80522da2a405845a088c62042bc8ce29dc30`, conservado como ancestro, sin rebase.

## Contrato implementado

`PostgresDocumentRepository` implementa `DocumentRepositoryPort` mediante
asyncpg contra las migraciones existentes. Se instancia con `connect(dsn)` y
se libera con `close()`. El servicio recibe el puerto por inyección; este
bloque no lo conecta al contenedor HTTP ni cambia la herramienta de aceptación
en memoria. Los originales continúan detrás de `ArtifactStoragePort`.

- `store_version` guarda versión, secciones, chunks, estadísticas, cierre de
  corrida y evento `created` en una sola transacción. La numeración se
  serializa bloqueando el documento; la corrida se bloquea antes del retry.
- Repetir una operación idéntica devuelve la versión en su estado actual,
  incluso publicada o reemplazada, sin cambiar IDs, fechas o eventos. Se
  comparan campos persistidos, contenido estructural, estadísticas, actor y
  `request_id`. Un cambio da `VersionConflictError`, sin escrituras parciales.
- Documento, corrida, archivo y hash se contrastan antes de guardar una
  versión nueva. Las asociaciones inválidas dan `DocumentIntegrityError`.
- Cargar deja `pending_validation`. Aprobar no publica. Rechazar exige motivo
  no vacío ni compuesto solo por espacios, tabuladores o saltos de línea;
  también se rechaza el espacio no separable. La validación está en el
  servicio y en las reglas compartidas por ambos repositorios.
- Una versión `published` o `superseded` no admite aprobación/rechazo directo.
  Publicar otra versión conserva la anterior como `superseded` con su actor,
  fecha y eventos históricos. Una versión rechazada puede volver a revisión
  y aprobarse, como ya permitía el servicio.
- Una corrida `completed` o `failed` conserva su resultado. No se puede
  transformar un fallo en versión ni reemplazar el resultado completado por
  un fallo tardío. El retry exacto de una versión existente sigue permitido.
- La procedencia reconstruye documento, versión, corrida, archivo/hash,
  sección, posición y cita. La lectura histórica explícita conserva versiones
  anteriores; `list_published_chunks` solo devuelve publicadas.
- Los alcances `(domain, equipment)` se filtran en SQL antes de `LIMIT`.
  `equipment=None` es un alcance exacto, no un comodín. No se mezclan dominios,
  activos ni versiones. Un alcance vacío devuelve vacío.
- Orden de lectura: número de versión, creación del documento, ID del
  documento y ordinal del chunk. Corridas: fecha descendente e ID ascendente.
  Límites no positivos devuelven vacío en ambos adaptadores.
- Dedupe por hash documental incluso entre MIME distintos y colisión de
  `storage_key` se resuelven sin generar corridas u originales parciales.
  PostgreSQL usa un cerrojo transaccional por hash para coordinar pools.
- Memoria copia metadatos anidados al escribir y devuelve snapshots de
  corridas/versiones: modificar un dict recibido o devuelto no altera lo
  guardado ni convierte un retry distinto en idéntico.

## Verificación y límites de paridad

`tests/test_document_repository.py` ejecuta los mismos casos con memoria y
PostgreSQL real. `tests/test_documents_postgres.py` añade rollback ante un
CHECK SQL tardío y un UUID inválido al escribir el evento, rollback de
publicación, reconexión, numeración/publicación entre pools, publicación
duplicada, retry conflictivo concurrente y carrera entre guardar/fallar.

La comparación de paridad conserva los campos de negocio, estadísticas,
contenido, historial, citas y cambios; normaliza solo IDs generados y relojes.
Las relaciones entre esos IDs se verifican por separado. PostgreSQL puede
dejar huecos en secuencias tras rollback: se exige orden, no continuidad.

Memoria no contiene el catálogo SQL de dominios/activos y sintetiza el ID del
activo. Los rechazos por activo inexistente o dominio incompatible y las
restricciones SQL se prueban específicamente en PostgreSQL. La paridad
verificada es la del contrato documental con entradas del dominio, no una
emulación de todos los tipos, constraints o errores del servidor SQL.

Todos los documentos son fixtures sintéticas. No se ensaya carga de producción,
un servicio remoto ni una recuperación tras caída abrupta del servidor.

## Decisión SQL pendiente: identidad de la corrida

### Problema y prueba del esquema actual

Las FKs independientes de `document_versions.document_id`, `run_id` y
`source_artifact_id` comprueban que cada ID exista. `UNIQUE(run_id)` impide
reutilizar una corrida, pero ninguna de esas reglas exige que los tres IDs
describan la **misma** ingesta.

Un escritor SQL podría insertar una versión del documento B con la corrida
del documento A y el archivo B. También podría cambiar posteriormente el
documento/archivo de una corrida ya usada. La vista de provenance uniría IDs
válidos con atribución incorrecta; si pertenecen a otros alcances, podría
atribuir contenido al alcance equivocado. La validación y los locks del
adaptador protegen sus operaciones, pero no a otros escritores ni cambios
posteriores. Esta garantía permanente requiere una restricción del esquema.

Diagnóstico realizado únicamente en `elsa-documents-41b`, PostgreSQL
`16.15 (Debian 16.15-1.pgdg13+2)`, accesible en `127.0.0.1:55441`:

```text
existing_mismatches: 0
NOTICE: Schema accepted version(document B, run A, source B)
mismatches_inside_transaction: 1
ROLLBACK
mismatches_after_rollback: 0
```

Se insertaron solo metadatos sintéticos dentro de `BEGIN`/`ROLLBACK`. No se
ejecutó DDL adicional ni quedó el dato inconsistente.

### SQL propuesto, no ejecutado

Tablas y columnas afectadas:

| Tabla | Columnas | Restricción |
|---|---|---|
| `elsa.document_ingestion_runs` | `id, document_id, source_artifact_id` | Clave candidata compuesta |
| `elsa.document_versions` | `run_id, document_id, source_artifact_id` | FK a esa clave compuesta |

```sql
BEGIN;

ALTER TABLE elsa.document_ingestion_runs
  ADD CONSTRAINT uq_document_run_identity
  UNIQUE (id, document_id, source_artifact_id);

ALTER TABLE elsa.document_versions
  ADD CONSTRAINT fk_document_version_run_identity
  FOREIGN KEY (run_id, document_id, source_artifact_id)
  REFERENCES elsa.document_ingestion_runs (id, document_id, source_artifact_id)
  ON UPDATE RESTRICT ON DELETE RESTRICT
  NOT VALID;

ALTER TABLE elsa.document_versions
  VALIDATE CONSTRAINT fk_document_version_run_identity;

COMMIT;
```

Conservar las FKs e índices actuales, incluido `UNIQUE(run_id)`. Las columnas
son `NOT NULL`, por lo que no hay escape por nulos. La nueva unicidad no
introduce duplicados posibles, pues `id` ya es PK, pero PostgreSQL necesita
esa clave candidata para referenciar la tupla completa. `NOT VALID` separa
declaración y validación; la propuesta valida antes de confirmar la transacción.
No modifica RLS, políticas, vistas, datos ni privilegios.

### Compatibilidad y preflight

Esta consulta debe devolver cero antes de aplicar una futura migración:

```sql
SELECT count(*) AS mismatches
FROM elsa.document_versions v
JOIN elsa.document_ingestion_runs r ON r.id = v.run_id
WHERE v.document_id IS DISTINCT FROM r.document_id
   OR v.source_artifact_id IS DISTINCT FROM r.source_artifact_id;
```

Los datos locales sintéticos dieron cero. **No se inspeccionaron datos
remotos/existentes de otros ambientes**: su compatibilidad está pendiente.
Si aparecen inconsistencias, detener la aplicación y revisar la procedencia
con el responsable; no corregir ni borrar automáticamente. La validación
fallida revierte toda la transacción propuesta. En tablas grandes, evaluar
los locks y el tiempo de construcción del índice en una ventana aprobada.

Esta FK garantiza la relación entre IDs; no convierte en inmutable todo el
contenido ni impone igualdad de hashes entre tablas. El adaptador verifica
el hash original al crear la versión.

### Rollback propuesto, no ejecutado

```sql
BEGIN;
ALTER TABLE elsa.document_versions
  DROP CONSTRAINT fk_document_version_run_identity;
ALTER TABLE elsa.document_ingestion_runs
  DROP CONSTRAINT uq_document_run_identity;
COMMIT;
```

No borra filas ni cambia las FKs previas. Devuelve la brecha original; primero
se retira la FK dependiente y después la unicidad.

### Pruebas necesarias si se autoriza

1. Migración desde esquema vacío y desde fixtures válidas ya pobladas; comprobar
   que la FK quede validada. Con datos incompatibles, fallo y rollback íntegro.
2. SQL directo: rechazar documento o archivo mezclados en `INSERT` y `UPDATE`
   de versiones, tanto dentro de un dominio/activo como entre alcances.
3. SQL directo: impedir cambiar documento/archivo de una corrida referenciada
   o eliminarla; permitir tuplas válidas y comprobar nulos/FKs existentes.
4. Dos conexiones: carrera entre guardar la versión y cambiar la identidad
   de su corrida; al confirmar, nunca debe existir una tupla inconsistente.
5. Rollback y reaplicación; integridad de datos, RLS, políticas y vista
   `security_invoker` intactos.
6. Repetir contrato compartido, rollback/concurrencia y suite completa sobre
   PostgreSQL 16, además de los controles de calidad.

Hasta resolver esta decisión no se considera cerrado 4.1.b ni listo para PR.

## Registro de ejecución

Entorno: Windows, Python 3.12 y PostgreSQL 16 local/efímero. Docker se reinició
y se volvió a levantar el contenedor existente, sin tocar Supabase remoto.
Las pruebas reconstruyen el esquema de esa base local con las migraciones
versionadas; nunca usar este procedimiento sobre una base con datos reales.

Primer pase del checkpoint:

```text
uv run pytest tests/test_document_repository.py tests/test_documents_postgres.py -q --tb=short
30 passed, 38 skipped, 2 warnings in 0.99s
```

Las 38 omisiones eran PostgreSQL sin `ELSA_TEST_DATABASE_URL`. Al habilitar el
contenedor, el primer pase dio `1 failed, 67 passed, 2 warnings in 91.27s`:
faltaba importar `IngestedVersion` en el test de paridad. Se corrigió y el
hito `4220594` pasó con `84 passed, 2 warnings in 110.34s`, sin omisiones.

La regresión de metadatos mutables reprodujo después un fallo en memoria:
modificar las estadísticas de entrada alteraba la corrida almacenada. Tras
separar los snapshots, el caso pasó en ambos adaptadores:
`2 passed, 74 deselected, 2 warnings in 1.50s`.

Los dos avisos de dependencia presentes en esos pases son:

```text
StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
```

Verificación del código en `d5a742a`:

```text
uv run ruff check .
All checks passed!

uv run ruff format --check .
212 files already formatted

uv run mypy
Success: no issues found in 161 source files
```

Configuración exclusiva del contenedor efímero local para los dos comandos
pytest de cierre (las credenciales son las sintéticas del contenedor de tests):

```powershell
$env:ELSA_TEST_DATABASE_URL = 'postgresql://elsa:elsa@127.0.0.1:55441/elsa_test'
```

Suite documental (38 casos por backend, 10 específicos de PostgreSQL y el
resto de extracción, chunking, lifecycle, aceptación y migraciones existentes):

```text
uv run pytest tests/test_document_repository.py tests/test_documents_postgres.py tests/test_document_lifecycle.py tests/test_document_extraction.py tests/test_document_chunking.py tests/test_document_acceptance.py tests/test_migrations_documents.py -q --tb=short
199 passed, 2 warnings in 260.97s (0:04:20)
```

Cero omisiones; ambos avisos se transcriben arriba.

Suite general con la misma configuración PostgreSQL 16:

```text
uv run pytest
================ 1078 passed, 3 warnings in 412.40s (0:06:52) =================
```

Cero omisiones y cero pruebas excluidas. Los dos avisos anteriores más uno de
una prueba negativa existente con clave HMAC sintética corta:

```text
tests/test_auth_supabase.py::test_unexpected_algorithm_is_rejected
InsecureKeyLengthWarning: The HMAC key is 8 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
```

Controles de pre-commit ejecutados antes de los hitos de código:

```text
uv run pre-commit run --all-files
trim trailing whitespace.................................................Passed
fix end of files.........................................................Passed
check yaml...............................................................Passed
check toml...............................................................Passed
check for merge conflicts................................................Passed
check for added large files..............................................Passed
detect private key.......................................................Passed
ruff check...............................................................Passed
ruff format..............................................................Passed
Detect hardcoded secrets.................................................Passed
```

Escaneo completo de historia en `d5a742a`, con el ejecutable instalado por el
hook de gitleaks (se omiten únicamente hora y códigos ANSI de color):

```powershell
& 'C:/Users/juanp/.cache/pre-commit/repo3x7oavce/golangenv-default/bin/gitleaks.exe' git --redact --no-banner --verbose .
```

```text
INF 80 commits scanned.
INF scan completed in 916ms
INF no leaks found
```

Hitos de código publicados, ambos posteriores al WIP conservado:

- `4220594`: lifecycle, orden/límites, colisiones y regresiones compartidas.
- `d5a742a`: snapshots de metadatos y regresión de idempotencia mutable.

La suite general valida el código de `d5a742a`; el hito posterior solo registra
documentación y su cierre requiere pre-commit y escaneo de secretos. No se
abrió PR ni se hizo merge. No se ensayó la restricción propuesta: requiere
autorización y las pruebas SQL enumeradas arriba antes de cerrar 4.1.b.
