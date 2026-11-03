# Cierre del subbloque R1.A — verificación del entorno Supabase TEST para el RAG real

- **Fecha:** 2026-11-03.
- **Estado:** documento de cierre de **R1.A**. **Es efectivo solo cuando este documento quede integrado en
  `main`** con el CI obligatorio en verde **y** Juan acepte expresamente la desviación de A2 (ver «Criterios de
  cierre»). Hasta entonces R1.A sigue abierto.
- **Qué cierra:** el subbloque **R1.A** del bloque R1 («RAG local real en PC1 por CLI»): identidad del proyecto
  Supabase de ELSA, consumidores, migraciones aplicadas, esquema y conexión de ELSA bajo `ELSA_ENV=TEST`.
- **Qué NO cierra:** **no cierra R1**, ni inicia R1.B, R1.C ni R1.D. No acredita el RAG, ni BGE-M3, ni Phi.
- **Prerrequisitos:** la auditoría de camino crítico (§3), hecha en la misma sesión sobre `main` en `51f785a`.
- **Decisión técnica:** ninguna nueva. R1.A se apoya en el
  [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) (el vector vive en la misma base que el
  chunk) y no abre ningún ADR.
- **Marcas** (`docs/project/BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**, **HECHO DEL REPOSITORIO**,
  **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Procedencia de lo medido:** todo **HECHO MEDIDO** sale de comandos ejecutados por la sesión de Claude Code
  en la máquina que se presume PC1 (§12). Lo que comprobó Juan fuera de la sesión se marca como tal.
- **Sanitización:** sin secretos, tokens, contraseñas, cadenas de conexión, rutas de perfil de usuario ni
  contenido de filas. De la base solo se registran metadatos y conteos. El ref del proyecto de Materiales no
  se registra.

---

## 1. Objetivo

Acreditar con evidencia que el proyecto Supabase de ELSA (`papelsa-elsa`) sirve como ambiente lógico **TEST**
para la demo sintética de R1: que tiene el esquema documental y vectorial completo y que ELSA puede consultarlo
desde PC1 bajo `ELSA_ENV=TEST`, sin modificar nada.

## 2. Alcance

**Dentro:**

- **G1 (solo lectura):** A1 identidad del proyecto, A2 consumidores, A3 migraciones aplicadas, A4 inventario del
  esquema (pgvector, tablas, RLS, políticas, privilegios, conteos).
- **G2 (condicional):** aplicar migraciones pendientes. **No fue necesario** (§18).
- **G3:** conexión de ELSA bajo `ELSA_ENV=TEST` con `embeddings_admin status`.
- Este documento de cierre.

**Fuera, de forma explícita:**

- Código de R1.B (CLI de ingesta persistente), corpus y preguntas de evaluación.
- Descargar BGE-M3, fijar su revisión, registrar, generar o activar modelos.
- Arrancar Phi o `llama-server`.
- Insertar, modificar o borrar filas; crear roles; aplicar migraciones.
- Modificar el `.env` de PC1, el código, Render o Materiales.
- `assistant.ask`, O1.4 y O1.5.
- Corregir la inconsistencia DEV/TEST de PC1 (§20).

## 3. Estado inicial

- **HECHO MEDIDO:** rama `main`, `HEAD = origin/main = 51f785a40274d469752f287f49ab17b18eac0d77`, árbol limpio.
- **HECHO DEL REPOSITORIO**, de la auditoría de camino crítico previa:
  - La cadena RAG completa existe: recuperación híbrida (`services/hybrid_retrieval.py`), Context Builder,
    política de generación, `GroundedGenerationService` y validación de citas. Solo se puede invocar por CLI
    (`python -m elsa.tools.llm_runtime ask`). Ningún endpoint la usa: `assistant.ask` es una búsqueda literal
    sobre el BOM (`api/v1/assistant.py:1-11`).
  - No existe una herramienta que ingiera y publique un documento en PostgreSQL: `document_acceptance` usa un
    repositorio en memoria (`tools/document_acceptance.py:160`).
  - Todos los tests de RAG usan embeddings fake y un LLM con guion o un servidor HTTP falso. Ninguno carga
    BGE-M3 ni Phi.
  - La línea base de Phi en PC1 sigue pendiente (`docs/llm-runtime.md:407-431`).
- **HECHO DEL REPOSITORIO:** solo la migración `20260908010000` constaba como aplicada, confirmada por Juan
  (`docs/bloque-4-2-plan.md:24-40`). El estado de `20260912010000` y `20260913010000` era desconocido.
- **HECHO DEL REPOSITORIO:** `docs/development.md:166-168` documenta un único proyecto Supabase remoto de
  ELSA, usado por **TEST**; DEV trabaja en local.

## 4. Trabajo realizado

1. Planificación de R1.A con tres puntos de autorización: G1, G2 y G3.
2. A1: `supabase projects list`. El proyecto apareció **pausado** (`INACTIVE`).
3. A3, primer intento con la CLI de Supabase: falló porque el proyecto estaba pausado (§13).
4. Juan reactivó el proyecto manualmente desde el panel de Supabase.
5. A2: clasificación del `.env` de PC1 con un script que no imprime valores, revisión de procesos de ELSA y
   lectura de la configuración de Render declarada en el repositorio.
6. A3 y A4: un script de solo lectura con `asyncpg`, dentro de una transacción `READ ONLY` con
   `statement_timeout` de 15 s.
7. G3, primer intento con solo lectura forzada en la conexión: el pooler descartó el parámetro y la sesión se
   detuvo antes de ejecutar nada (§13).
8. G3, segundo intento: rechazado en la validación de configuración por el almacén de artefactos (§13).
9. G3, tercer intento, con `ELSA_ARTIFACT_STORAGE_BACKEND=local` solo en el proceso: correcto.
10. Este documento.

## 5. Decisiones

| Decisión | Quién | Motivo |
|---|---|---|
| **DECISIÓN TOMADA:** el siguiente bloque funcional es R1 (RAG local real por CLI), por etapas R1.A–D | Juan | Es el camino más corto a una demo real sin tocar la API |
| **DECISIÓN TOMADA:** O1.4 y O1.5 se difieren | Juan | Automatizan el método de trabajo; no habilitan ni bloquean el código del producto |
| **DECISIÓN TOMADA:** usar el proyecto Supabase existente de ELSA con datos exclusivamente sintéticos | Juan | Evita instalar PostgreSQL en PC1 (8 GB de RAM) y respeta el ADR 0013 |
| **DECISIÓN TOMADA:** queda pendiente la autorización para guardar manuales reales de PAPELSA | Juan | Fuera de R1 |
| **DECISIÓN TOMADA (D1):** R1 corre como ambiente lógico **TEST** (`ELSA_ENV=TEST`) | Juan | El repositorio documenta ese proyecto como TEST; apuntar DEV a él violaría la regla 8 |
| **DECISIÓN TOMADA:** G2 se omite | Juan | A3 mostró las 5 migraciones aplicadas |
| **DECISIÓN TOMADA:** no inspeccionar ni reutilizar las filas preexistentes; R1 usará dominio, activo y documentos sintéticos propios, y antes de crearlos se verificará que no hay identificadores en conflicto | Juan | Evitar mezclar datos de procedencia desconocida |
| **DECISIÓN TOMADA:** la inconsistencia DEV/TEST de PC1 se corrige de forma controlada antes de cualquier escritura de R1.B, sin romper D2.5. Hasta entonces no se arranca ELSA con el `.env` normal | Juan | Regla 8 |
| **DECISIÓN TOMADA:** G3 se ejecuta sin forzar la solo lectura en el pool, apoyándose en la revisión de código | Juan | `status` solo hace `SELECT`. asyncpg ejecuta `RESET ALL` al devolver cada conexión al pool, así que un `SET` hecho una sola vez no garantiza la solo lectura |
| **DECISIÓN TOMADA:** A2 se registra como **verificación incompleta** y como condición previa a las escrituras de R1.B | Juan | Falta comprobar el panel de Render |

Ninguna decisión es arquitectónica nueva: no hay ADR (regla 25).

## 6. Pruebas

No se ejecutó la suite de tests: el subbloque no cambia código. Se ejecutaron verificaciones operativas, todas
de lectura:

| Verificación | Resultado |
|---|---|
| `supabase projects list` | Ejecutada (§8.1) |
| `supabase migration list --linked` | Falló, proyecto pausado (§8.2) |
| Clasificación del `.env` de PC1 sin imprimir valores | Ejecutada (§8.3) |
| Procesos de ELSA y puertos 8000/8080 | Ejecutada (§8.3) |
| A3/A4, transacción `READ ONLY` | Ejecutada (§8.4) |
| G3, tres intentos | El tercero correcto (§8.5) |

**HECHO DEL REPOSITORIO:** antes de G3 se revisó que `embeddings_admin status` solo lee. `_status`
(`tools/embeddings_admin.py:155-176`) llama a `list_models()` y `get_active_model()`, que son un único
`SELECT` sobre `elsa.embedding_models` cada uno (`adapters/postgres_vectors.py:227-239`). El pool se crea sin
hook de inicialización (`:150-159`).

## 7. Comandos relevantes

```bash
supabase projects list
```

```bash
ELSA_ENV=TEST ELSA_ARTIFACT_STORAGE_BACKEND=local ELSA_ARTIFACT_STORAGE_ROOT=<carpeta temporal vacía fuera de OneDrive y del repositorio> uv run python -m elsa.tools.embeddings_admin status
```

Los scripts de A2 y de A3/A4 eran temporales, fuera del repositorio. Su lógica:

- **A2:** analiza el `.env` y, para cada clave `*DATABASE_URL*`, imprime solo si existe, a qué proyecto conocido
  apunta, el tipo de host y el puerto.
- **A3/A4:** abre una sola conexión, `BEGIN READ ONLY`, `SET LOCAL statement_timeout = 15000`, y consulta
  `supabase_migrations.schema_migrations`, `pg_available_extensions`, `pg_extension`, `pg_class` (RLS),
  `count(*)` por tabla de `elsa`, `pg_constraint`, `pg_policies`, `has_schema_privilege` e
  `information_schema.role_table_grants`.

Para repetir A3/A4 basta con reproducir esas consultas en una transacción `READ ONLY`.

## 8. Resultados

### 8.1 A1 — identidad

**HECHO MEDIDO**, salida JSON de `supabase projects list` reducida a sus campos no sensibles:

| name | ref | status | Postgres | linked |
|---|---|---|---|---|
| `papelsa-asistente-materiales` | *(no se registra)* | `ACTIVE_HEALTHY` | 17.6.1.155 | `false` |
| `papelsa-elsa` | `shiaxoyhallucehoygqt` | `INACTIVE` | 17.6.1.166 | `true` |

El enlace de la CLI apunta al proyecto de ELSA, no al de Materiales.

### 8.2 A3 — primer intento con la CLI

**HECHO MEDIDO:**

```text
Initialising login role...
{"_tag":"Error","error":{"code":"LegacyDbConfigLoginRoleStatusError","message":"unexpected login role status 544: {\"message\":\"Failed to create login role: Connection terminated due to connection timeout\"}"}}
```

### 8.3 A2 — consumidores

**HECHO MEDIDO**, clasificación del `.env` normal de PC1:

```text
ELSA_ENV = DEV
ELSA_PERMISSIONS_BACKEND = postgres
ELSA_AUTH_PROVIDER = supabase
ELSA_ASSISTANT_EXECUTION_MODE = <absent>
ELSA_RELAY_ENABLED = <absent>
ELSA_LLM_BACKEND = <absent>
ELSA_DEMO_SEED = <absent>
ELSA_DATABASE_URL: configured=yes target=papelsa-elsa host_kind=supabase-pooler port=5432
process env ELSA_DATABASE_URL: configured=no
process env ELSA_TEST_DATABASE_URL: configured=no
```

**HECHO MEDIDO**, procesos en el momento de la comprobación:

```text
python.exe pid=14500 kind=unrelated
python.exe pid=11432 kind=unrelated
no listeners on 8000/8080
```

**HECHO DEL REPOSITORIO:** `render.yaml` (`elsa-demo`) declara solo `ELSA_ENV`, `ELSA_DEMO_SEED` y
`ELSA_CORS_ORIGINS`. Ni `docs/render-pc1-conexion-real-runbook.md`, ni el ADR 0035, ni el cierre de D2.6
mencionan `DATABASE_URL`.

**PENDIENTE:** el panel real de Render (`elsa-demo`, el servicio relay y los grupos de variables compartidas)
**no se verificó**. Desde PC1 no hay ningún acceso a Render: ni CLI, ni configuración `~/.render`, ni claves
`RENDER*`.

### 8.4 A3/A4 — migraciones y esquema

**HECHO MEDIDO**, salida real del script de solo lectura:

```text
[session] transaction_read_only=on
[session] server_version=17.6
[session] current_user=postgres

== A3 · migraciones registradas ==
remote 20260905020000  create_elsa_authorization_model
remote 20260906010000  create_technical_knowledge_model
remote 20260908010000  create_documental_knowledge_model
remote 20260912010000  enforce_document_run_artifact_identity
remote 20260913010000  create_vector_storage_model
local  20260905020000  APPLIED  (20260905020000_create_elsa_authorization_model.sql)
local  20260906010000  APPLIED  (20260906010000_create_technical_knowledge_model.sql)
local  20260908010000  APPLIED  (20260908010000_create_documental_knowledge_model.sql)
local  20260912010000  APPLIED  (20260912010000_enforce_document_run_artifact_identity.sql)
local  20260913010000  APPLIED  (20260913010000_create_vector_storage_model.sql)

== A4 · pgvector ==
{'name': 'vector', 'default_version': '0.8.2', 'installed_version': '0.8.2'}
pg_extension vector: [{'extname': 'vector', 'extversion': '0.8.2', 'nspname': 'public'}]

== A4 · tablas de elsa, RLS y filas ==
accounts                         rls=True  force=False rows=2
admin_audit_log                  rls=True  force=False rows=4
component_identifiers            rls=True  force=False rows=0
components                       rls=True  force=False rows=0
derived_artifacts                rls=True  force=False rows=0
document_chunk_embeddings        rls=True  force=False rows=0
document_chunks                  rls=True  force=False rows=0
document_ingestion_runs          rls=True  force=False rows=0
document_sections                rls=True  force=False rows=0
document_version_events          rls=True  force=False rows=0
document_versions                rls=True  force=False rows=0
documents                        rls=True  force=False rows=0
drawing_images                   rls=True  force=False rows=0
drawings                         rls=True  force=False rows=0
embedding_models                 rls=True  force=False rows=0
embedding_runs                   rls=True  force=False rows=0
engineering_bom_items            rls=True  force=False rows=0
engineering_bom_versions         rls=True  force=False rows=0
failure_modes                    rls=True  force=False rows=0
imports                          rls=True  force=False rows=0
knowledge_domains                rls=True  force=False rows=2
option_tables                    rls=True  force=False rows=0
permission_grants                rls=True  force=False rows=1
reconciliation_items             rls=True  force=False rows=0
reconciliation_runs              rls=True  force=False rows=0
reviewer_grants                  rls=True  force=False rows=0
reviews                          rls=True  force=False rows=0
sap_bom_snapshots                rls=True  force=False rows=0
sap_snapshot_items               rls=True  force=False rows=0
sod_criteria                     rls=True  force=False rows=0
source_artifacts                 rls=True  force=False rows=0
subsystems                       rls=True  force=False rows=0
technical_assets                 rls=True  force=False rows=1

== A4 · diferencias frente a las migraciones locales ==
20260905020000_create_elsa_authorization_model.sql: expected=4 missing=none
20260906010000_create_technical_knowledge_model.sql: expected=20 missing=none
20260908010000_create_documental_knowledge_model.sql: expected=6 missing=none
20260912010000_enforce_document_run_artifact_identity.sql: expected=0 missing=none
20260913010000_create_vector_storage_model.sql: expected=3 missing=none
tables in elsa not created by any local migration: none
20260912010000 constraints present: ['fk_document_version_run_identity', 'uq_document_run_identity']

== A4 · políticas y privilegios ==
policies in elsa: 0
role anon: schema_usage=False table_grants=0
role authenticated: schema_usage=False table_grants=0
```

La consola mostró como caracteres de reemplazo el «·» de los encabezados y la «í» de «políticas». Aquí se
transcriben con el texto literal del script; el resto es la salida tal cual.

Lectura de esta salida:

- **HECHO MEDIDO:** las 5 migraciones locales están registradas en remoto; no hay ninguna remota sin archivo
  local.
- **HECHO MEDIDO:** las 33 tablas esperadas existen, todas con RLS activo, 0 políticas, y `anon` y
  `authenticated` sin privilegios sobre `elsa`. Coincide con el ADR 0002: la credencial de servicio salta el
  RLS y la autorización la aplica FastAPI.
- **HECHO MEDIDO:** las tablas documentales y vectoriales están vacías. Hay **filas preexistentes en cinco
  tablas**: `accounts` (2), `admin_audit_log` (4), `knowledge_domains` (2), `permission_grants` (1) y
  `technical_assets` (1). Su contenido **no se consultó**.
- **INFERENCIA:** esas filas proceden probablemente del uso normal de PC1 en DEV, que apunta a esta base (§8.3).
  No está comprobado.

### 8.5 G3 — conexión bajo TEST

**HECHO MEDIDO**, primer intento, con `default_transaction_read_only=on` añadido como parámetro de la conexión:

```text
[g3] default_transaction_read_only=off
STOP: read-only mode not in effect
exit=1
```

**HECHO MEDIDO**, segundo intento, solo con `ELSA_ENV=TEST` en el proceso. Es un error de validación; no hubo
conexión a la base:

```text
elsa.config.ConfigurationError: Invalid application configuration:
  - ELSA_SETTINGS: Value error, the in-memory artifact storage is only allowed in the DEV environment; set ELSA_ARTIFACT_STORAGE_BACKEND=local
See .env.example and docs/environment-variables.md.
exit=1
```

**HECHO MEDIDO**, tercer intento, con `ELSA_ENV=TEST`, `ELSA_ARTIFACT_STORAGE_BACKEND=local` y
`ELSA_ARTIFACT_STORAGE_ROOT` apuntando a una carpeta temporal vacía, todo solo en el proceso:

```text
no hay ningún modelo registrado
exit=0
```

La consola mostró la «ú» como un carácter de reemplazo; es la codificación de la consola, no un error.

**HECHO MEDIDO**, después de G3:
- `git status --porcelain` vacío;
- la carpeta temporal de artefactos sigue con 0 archivos;
- el `.env` no se editó.

## 9. Métricas

Nada que registrar: R1.A no mide rendimiento. Los conteos del esquema están en §8.4.

## 10. Aportes de Claude Code

Sesión de Claude Code en la app de escritorio, con identificador `3d38ede2-50f8-47ef-9185-1b8a2b657ce1`. El
identificador figura en las rutas de la propia sesión. La sesión hizo:

- la auditoría de camino crítico;
- la planificación de R1.A;
- todas las verificaciones de §8;
- este documento.

No se invocaron subagentes de revisión: el cambio es solo documental.

## 11. Aportes de Codex

Nada que registrar.

## 12. Operaciones manuales y de PowerShell

- **Juan:** las decisiones y autorizaciones de §5, en la conversación; la **reactivación manual** del proyecto
  `papelsa-elsa` desde el panel de Supabase. Esto lo informó Juan; la sesión no lo observó directamente, pero
  la conexión correcta de A3/A4 es coherente con ello.
- **La sesión de Claude Code**, en la máquina local:
  - `supabase projects list` y el intento de `supabase migration list`;
  - la lectura de RAM, CPU y GPU de la máquina;
  - la revisión de procesos;
  - los scripts temporales de A2, de A3/A4 y de G3.
- **HECHO MEDIDO:** la máquina tiene 7,95 GB de RAM, un AMD Ryzen 3 2200G y una Radeon RX 570. Coincide con
  el hardware registrado de PC1.
- **PENDIENTE:** la identidad física de PC1 es **probable, no acreditada**. Debe confirmarla el operador.

## 13. Incidentes

| Incidente | Qué se hizo |
|---|---|
| `papelsa-elsa` estaba pausado (`INACTIVE`) | STOP. Juan lo reactivó manualmente |
| `supabase migration list` intentó crear un rol de acceso temporal mediante la API de gestión: la CLI no es solo lectura sin contraseña | Falló por el tiempo de espera, sin crear nada. No se reintentó y A3/A4 se hicieron sin la CLI |
| El pooler de Supabase en modo sesión descarta el parámetro de arranque `default_transaction_read_only` | STOP antes de ejecutar nada. Juan eligió la opción sin forzar la solo lectura (§5) |
| En TEST, la validación exige un almacén de artefactos que no sea en memoria; no estaba en el plan | STOP. Repetido con `local` solo en el proceso, con autorización |
| Si `load_settings()` falla, `embeddings_admin` imprime la traza completa, porque la llamada está fuera del `try` (`tools/embeddings_admin.py:298`) | Registrado como P2. No expone credenciales |

## 14. Git

Solo este documento, en su propia rama y PR. No hubo cambios de código, push a `main`, force ni tags. El merge
lo hace Juan.

## 15. Ramas

| Rama | Uso |
|---|---|
| `claude/r1-a-cierre` | Este cierre |

## 16. Commits

El commit de este documento está en el PR de §17. R1.A no tiene otros commits.

## 17. Pull requests

El de este cierre, pendiente de CI, de revisión y del merge de Juan.

## 18. Migraciones

- **Escritas:** ninguna.
- **Aplicadas en R1.A:** ninguna.
- **HECHO MEDIDO:** las cinco migraciones del repositorio, de `20260905020000` a `20260913010000`, ya estaban
  aplicadas en `papelsa-elsa` (§8.4). G2 no fue necesario y no se pidió ninguna autorización de la regla 15.
  Este documento no registra cuándo ni quién aplicó `20260912010000` y `20260913010000`: el repositorio no
  contiene esa evidencia.

## 19. Estado operacional final

| Pieza | Estado |
|---|---|
| Proyecto `papelsa-elsa` | Activo tras la reactivación manual; se conecta desde PC1 |
| Esquema documental y vectorial | Completo, con pgvector 0.8.2 |
| ELSA bajo `ELSA_ENV=TEST` | Pasa la validación y lee `elsa.embedding_models` con `embeddings_admin status` |
| Modelos de embeddings | Ninguno registrado ni activo. Es lo esperado: registrarlos corresponde a R1.C |
| Corpus documental | Vacío |
| `.env` normal de PC1 | Sin cambios. Sigue apuntando a `papelsa-elsa` con `ELSA_ENV=DEV`. **No debe usarse para arrancar ELSA** hasta corregir la inconsistencia |
| RAG, BGE-M3 y Phi | Sin ejecutar |

## 20. Pendientes

| Pendiente | Responsable | Bloquea |
|---|---|---|
| **PENDIENTE:** verificar en el panel de Render si `elsa-demo`, el servicio relay o un grupo de variables compartidas tienen `ELSA_DATABASE_URL`, y, si la tienen, a qué proyecto apunta, sin divulgar credenciales | Quien administre la cuenta de Render | Las escrituras de R1.B |
| **PENDIENTE:** corregir de forma controlada la inconsistencia DEV/TEST de PC1 (el `.env` DEV apunta al proyecto TEST), preservando D2.5 | Juan decide; se prepara como tarea propia | Las escrituras de R1.B |
| **PENDIENTE:** la credencial de PC1 se conecta como `postgres`, el superusuario del proyecto. Riesgos: cualquier fallo o abuso de ELSA local tendría privilegios totales sobre la base, y complica la auditoría y el pentesting (regla 10). Propuesta: un rol de servicio con privilegios mínimos, mediante migración versionada | Juan | No bloquea R1; es P1 |
| **PENDIENTE:** confirmar la identidad física de PC1 | Operador | La atribución de las mediciones de R1.C y R1.D a PC1 |
| **PENDIENTE:** comprobar que no hay identificadores en conflicto con las filas preexistentes antes de crear el dominio, el activo y los documentos sintéticos de R1, y autorizar su creación | Juan | R1.B |
| **PENDIENTE (P2):** salida limpia de `embeddings_admin` cuando falla la configuración | Bloque aparte | Nada |

## 21. Siguiente bloque

**R1.B — ingesta y publicación persistentes:** una CLI sobre `DocumentIngestionService` y
`PostgresDocumentRepository` para documentos `.md`, con ingestar, aprobar y publicar como pasos separados
(regla 16), y el corpus sintético PR-100. **Requiere autorización expresa de Juan**, y sus escrituras exigen
antes resolver A2 y la inconsistencia DEV/TEST.

---

## Qué acredita R1.A

- El proyecto enlazado es `papelsa-elsa` y no el de Materiales.
- Las cinco migraciones están aplicadas, con pgvector 0.8.2 y el esquema completo, sin deriva.
- RLS está activo en las 33 tablas, sin políticas ni privilegios para `anon` y `authenticated`.
- ELSA, con su propio adaptador, lee la base bajo `ELSA_ENV=TEST` desde la máquina local.
- No hizo falta ninguna migración.

## Qué no acredita R1.A

- Que ningún servicio de Render use esta base (A2 incompleto).
- Que la máquina sea físicamente PC1.
- La procedencia ni el contenido de las filas preexistentes.
- Escrituras bajo TEST, ingesta, embeddings, recuperación ni generación.
- Que la credencial de servicio tenga privilegios mínimos (no los tiene).

## Criterios de cierre

| Criterio del plan | Estado |
|---|---|
| A1: ref y nombre coinciden; no es Materiales | Cumplido (§8.1) |
| A2: ningún consumidor vivo de Render usa esta base | **No cumplido: verificación incompleta.** Desviación que Juan debe aceptar expresamente para cerrar R1.A |
| A3: 5 migraciones locales registradas en remoto, sin migraciones solo remotas | Cumplido (§8.4) |
| A4: `vector` disponible e instalado, RLS en todas las tablas, 0 políticas | Cumplido (§8.4) |
| G2: aplicar lo pendiente con autorización | No aplica: nada pendiente |
| G3: `embeddings_admin status` lee la base y no muestra credenciales | Cumplido (§8.5). El criterio original esperaba «no hay ningún modelo registrado»; Juan lo relajó para no presuponer el resultado, y ese fue el resultado observado |
| Documento de cierre en `main` con CI en verde | Pendiente de este PR |

## Regla de continuidad

R1.A queda cerrado solo cuando este documento esté en `main` con el CI obligatorio en verde **y** Juan haya
aceptado por escrito la desviación de A2. R1.B no empieza sin autorización expresa.

## Veredicto

El entorno de base de datos está listo para el RAG de R1 bajo TEST, sin haber modificado nada. A2 queda como
condición previa abierta para las escrituras de R1.B.
