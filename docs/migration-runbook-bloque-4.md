# Runbook de migración — Bloque 4

Cómo aplicar `supabase/migrations/20260908010000_create_documental_knowledge_model.sql`
al proyecto Supabase de ELSA, qué comprobar antes y después, y cómo
revertirlo.

> **Esta migración NO se ha aplicado a ningún proyecto Supabase.** Se ha
> verificado únicamente contra un PostgreSQL 16 local y efímero. Aplicarla
> requiere autorización explícita del responsable del proyecto.

---

## 1. Qué se aplica

Un solo archivo, `20260908010000_create_documental_knowledge_model.sql`, que
crea el modelo de conocimiento documental sobre el esquema `elsa` ya
existente.

Requiere que estén aplicadas las migraciones de los Bloques 1 y 2
(`20260905020000` y `20260906010000`): esta se apoya en
`knowledge_domains`, `technical_assets`, `source_artifacts`,
`admin_audit_log` y las funciones `touch_updated_at` y
`forbid_review_mutation`.

---

## 2. Objetos que crea

### Tablas

| Tabla | Qué guarda |
|---|---|
| `elsa.documents` | Identidad estable de cada documento |
| `elsa.document_ingestion_runs` | Una ejecución de ingesta y cómo terminó |
| `elsa.document_versions` | Una versión completa: su contenido en un momento dado |
| `elsa.document_sections` | El árbol de títulos de una versión |
| `elsa.document_chunks` | La unidad recuperable, con su procedencia |
| `elsa.document_version_events` | Historial append-only del ciclo de vida |

### Vista

`elsa.document_chunk_provenance` — reconstruye la cadena chunk → sección →
versión → documento → activo → ejecución → archivo original, y expone el
alcance (`scope_domain`, `scope_equipment`) que hay que autorizar antes de
recuperar.

### Índices que imponen garantías

| Índice | Impide |
|---|---|
| `uq_published_document_version` | Dos versiones publicadas del mismo documento |
| `documents (domain, code)` | Dos documentos con el mismo código en un dominio |
| `document_versions (document_id, version_number)` | Reutilizar un número de versión |
| `document_chunks (version_id, structural_key)` | Dos chunks con la misma dirección en una versión |
| `document_chunks (version_id, ordinal)` | Dos chunks en la misma posición |

### Restricciones que se **sustituyen** (no se borran datos)

| Restricción | Qué cambia |
|---|---|
| `source_artifacts.ck_source_artifact_kind` | Acepta además `document_text`, `document_markdown`, `document_pdf` |
| `admin_audit_log.ck_audit_operation` | Acepta además las seis operaciones documentales |

### Restricción que se **añade**

`technical_assets.uq_technical_asset_id_domain` — unicidad sobre
`(id, domain)`. Es necesaria para que un documento pueda declarar una clave
foránea compuesta y la base pueda impedir que un documento de un dominio
cuelgue de un activo de otro. **No cambia ningún dato**: `id` ya era clave
primaria, así que el par nunca podía repetirse.

---

## 3. Cambios destructivos

**Ninguno.** Esta migración solo crea objetos nuevos y amplía dos listas de
valores permitidos. No borra tablas, no borra columnas, no borra filas y no
estrecha ninguna restricción existente.

Es la diferencia con el Bloque 2, y por eso este runbook es más corto.

---

## 4. RLS y superficie de exposición

Las seis tablas nuevas quedan con RLS habilitado y **sin políticas**:
cualquier rol sin `BYPASSRLS` obtiene cero filas aunque llegue a conectarse.
La autorización real la aplica FastAPI con credencial de servicio
([ADR 0002](adr/0002-identidad-de-materiales-autorizacion-en-backend.md)).

La vista `document_chunk_provenance` se declara con
`security_invoker = true`, de modo que se evalúa con los privilegios y la RLS
de quien la consulta. **Sin esa opción una vista ignora la RLS de sus tablas
base**: fue un hallazgo real de la auditoría previa a aplicar esta migración,
y está cubierto por pruebas de regresión.

La migración vuelve a revocar `anon` y `authenticated` sobre el esquema, sus
tablas y sus funciones, igual que hicieron los Bloques 1 y 2. Un `REVOKE` es
una operación puntual, no una regla permanente: cada migración que añade
objetos tiene que volver a cerrarlos, o el cierre solo cubre lo que existía
cuando se ejecutó.

---

## 5. Ensayo previo realizado

Contra PostgreSQL 16 local, en este orden:

1. Esquema vacío → se aplican las tres migraciones en orden. Correcto.
2. Se aplican **tres veces seguidas** sobre la misma base. Correcto: la
   migración es idempotente y no duplica datos.
3. Se ejecuta `supabase/rollback/20260908010000_rollback.sql`. Correcto: las
   seis tablas y la vista desaparecen; el Bloque 2 queda intacto.
4. Se vuelve a aplicar la migración sobre la base revertida. Correcto.
5. Sobre una base que **imita a Supabase** —con los roles `anon`,
   `authenticated` y `service_role` creados, y con privilegios concedidos
   antes de migrar— se comprueba que tras aplicar la migración ninguno de
   los dos primeros conserva `USAGE` sobre `elsa` ni privilegio alguno sobre
   sus tablas.
6. `uv run pytest tests/test_migrations.py tests/test_migrations_documents.py`
   con `ELSA_TEST_DATABASE_URL` apuntando a esa base: **43 pruebas en
   verde**.

---

## 6. Procedimiento de ejecución

```bash
# --- 0. Contexto ---
supabase projects list
supabase link --project-ref <ref del proyecto de ELSA>

# --- 1. Respaldo, antes de nada ---
supabase db dump --linked --schema elsa -f respaldo-elsa-antes-bloque-4.sql

# --- 2. Ver qué está pendiente ---
supabase migration list --linked
# Debe mostrar SOLO 20260908010000 como pendiente.
# Si aparece cualquier otra cosa: detenerse y preguntar.

# --- 3. Aplicar ---
supabase db push --linked

# --- 4. Validación inmediata ---
psql "<cadena de conexión>" -c "
  select tablename from pg_tables
   where schemaname='elsa' and tablename like 'document%' order by 1;"
# Esperado: document_chunks, document_ingestion_runs, document_sections,
#           document_version_events, document_versions, documents

psql "<cadena de conexión>" -c "
  select tablename, rowsecurity from pg_tables
   where schemaname='elsa' and tablename like 'document%';"
# Esperado: rowsecurity = t en las seis.

psql "<cadena de conexión>" -c "
  select count(*) from elsa.document_chunk_provenance;"
# Esperado: 0. La vista existe y no hay datos todavía.

# --- 5. Detenerse ---
# No cargar documentos hasta que el responsable lo autorice.
```

---

## 7. Verificación posterior

Que el Bloque 2 sigue intacto:

```sql
select count(*) from elsa.engineering_bom_versions;
select count(*) from elsa.reviews;
select count(*) from elsa.source_artifacts;
```

Los tres conteos deben ser exactamente los de antes de aplicar.

Que la ampliación de `source_artifacts` no rompió nada existente:

```sql
select kind, count(*) from elsa.source_artifacts group by kind;
```

---

## 8. Reversión

`supabase/rollback/20260908010000_rollback.sql`, ejecutado **a mano** y con
respaldo previo:

```bash
supabase db dump --linked --schema elsa -f respaldo-antes-de-revertir.sql
psql "<cadena de conexión>" -v ON_ERROR_STOP=1 \
  -f supabase/rollback/20260908010000_rollback.sql
```

Destruye todos los documentos, versiones, secciones y chunks cargados, y
borra el metadato de los originales documentales. **Los bytes siguen en el
almacenamiento privado**: borrarlos es una decisión aparte y no la toma una
migración.

No revierte el Bloque 2.

---

## 9. Qué no cubre este runbook

- **Cargar documentos.** No hay endpoints HTTP de ingesta documental en este
  bloque; la ingesta se ejerce con
  [`document-acceptance.md`](document-acceptance.md), que trabaja en memoria.
- **El adaptador PostgreSQL del repositorio documental.** El puerto solo
  tiene implementación en memoria; el esquema está listo para cuando haga
  falta persistir.
- **Embeddings y pgvector.** No forman parte de esta migración
  ([ADR 0010](adr/0010-conocimiento-estructurado-vs-documental.md)).
