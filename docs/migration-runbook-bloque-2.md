# Runbook de migración — Bloque 2

Procedimiento para aplicar el modelo de conocimiento técnico al proyecto
Supabase de ELSA. Este documento se escribió **antes** de aplicar nada y
describe lo que se va a hacer, no lo que ya se hizo.

Proyecto destino: `papelsa-elsa` (ref `shiaxoyhallucehoygqt`).

---

## 1. Qué se aplica

`supabase/migrations/` contiene dos archivos, en este orden:

| Archivo | Bloque | Contenido |
|---|---|---|
| `20260905020000_create_elsa_authorization_model.sql` | 1 | Esquema `elsa`, cuentas, dominios, permisos, auditoría |
| `20260906010000_create_technical_knowledge_model.sql` | 2 | Modelo de conocimiento técnico |

**Estado remoto confirmado** con `supabase migration list` sobre el proyecto
enlazado:

| Local | Remoto |
|---|---|
| `20260905020000` | `20260905020000` |
| `20260906010000` | — |

El Bloque 1 ya está aplicado. Solo queda pendiente el Bloque 2, y `db push`
aplicará únicamente ese archivo. Las dependencias listadas abajo ya existen en
el remoto, de modo que la migración tiene sobre qué apoyarse.

Dependencias del Bloque 2 sobre el Bloque 1:

- esquema `elsa`
- función `elsa.touch_updated_at()`
- tabla `elsa.accounts` (clave foránea desde `reviewer_grants`)
- tabla `elsa.knowledge_domains` (clave foránea desde `technical_assets` y `reviewer_grants`)
- tabla `elsa.admin_audit_log` (se le **sustituye** una restricción, ver §3)

## 2. Objetos que crea el Bloque 2

20 tablas: `technical_assets`, `subsystems`, `components`,
`component_identifiers`, `source_artifacts`, `derived_artifacts`, `imports`,
`engineering_bom_versions`, `engineering_bom_items`, `drawings`,
`drawing_images`, `failure_modes`, `sod_criteria`, `option_tables`,
`sap_bom_snapshots`, `sap_snapshot_items`, `reconciliation_runs`,
`reconciliation_items`, `reviewer_grants`, `reviews`.

Además: 21 índices, 2 disparadores (`trg_technical_assets_touch_updated_at`,
`trg_reviews_append_only`), 1 función (`elsa.forbid_review_mutation`).

No crea extensiones, tipos ni esquemas nuevos. No usa `pgvector` — eso
corresponde a un bloque posterior. No usa `create index concurrently`, de modo
que la migración corre entera dentro de una transacción.

Estado final esperado del esquema `elsa` tras aplicar ambos archivos, medido
en un PostgreSQL 16 limpio:

| Métrica | Valor |
|---|---|
| Tablas | 24 (4 del Bloque 1 + 20 del Bloque 2) |
| Índices | 66 |
| Claves foráneas | 42 |
| Disparadores no internos | 4 |
| Funciones | 3 |
| Tablas con RLS activo | 24 de 24 |
| Políticas RLS | 0 |

## 3. El único cambio destructivo

El Bloque 2 **no** elimina ninguna tabla, columna ni dato. Su única operación
sobre un objeto preexistente es esta:

```sql
alter table elsa.admin_audit_log drop constraint if exists ck_audit_operation;
alter table elsa.admin_audit_log add constraint ck_audit_operation check (...);
```

La restricción nueva **contiene** las ocho operaciones del Bloque 1 y añade
nueve del Bloque 2. Es una ampliación, no una sustitución restrictiva: ninguna
fila existente puede violarla. `add constraint` valida las filas presentes; si
la tabla estuviera vacía o solo tuviera operaciones del Bloque 1, la validación
pasa por construcción.

Riesgo residual: si alguien hubiera insertado operaciones fuera del catálogo
por vías ajenas a la migración, el `add constraint` fallaría y abortaría toda
la transacción sin dejar nada aplicado. Se comprueba antes (§5, paso 3).

## 4. RLS y superficie de exposición

Las 20 tablas nuevas quedan con RLS activo y **cero políticas**. En PostgreSQL
eso significa negación total: cualquier rol sin `BYPASSRLS` obtiene cero filas
aunque logre conectarse. Adicionalmente la migración revoca todos los permisos
sobre tablas y funciones del esquema `elsa` a los roles `anon` y
`authenticated` cuando existen — que es el caso en Supabase.

Consecuencia práctica: **estas tablas no son accesibles desde PostgREST ni
desde el cliente JavaScript de Supabase.** El único camino de lectura es
FastAPI con credencial de servicio, que aplica la autorización propia de ELSA
antes de recuperar conocimiento (ADR 0002, regla 4 del contrato).

Esto es defensa en profundidad, no el mecanismo de autorización.

## 5. Procedimiento de ejecución

Se ejecuta desde la máquina del usuario, que es donde viven las credenciales.
El contenedor de la sesión de Claude no tiene ni la CLI de Supabase ni acceso
de red al proyecto, y no debe tenerlos.

1. **Confirmar rama y árbol limpio.**

   ```bash
   git rev-parse --abbrev-ref HEAD    # claude/bloque-2-activo-tecnico-bom-x8aeic
   git status --porcelain             # sin salida
   ```

2. **Enlazar el proyecto.** El *project ref* no es un secreto; la contraseña de
   base de datos sí, y la pide la CLI de forma interactiva. No se escribe en la
   línea de comandos ni se versiona.

   ```bash
   supabase link --project-ref shiaxoyhallucehoygqt
   ```

3. **Consultar el estado remoto antes de tocarlo.** Este paso es obligatorio:
   determina si el remoto está realmente vacío o si alguien aplicó algo a mano.

   ```bash
   supabase migration list
   ```

   Interpretación:

   - Ambas migraciones sin marca en la columna remota → escenario esperado,
     seguir al paso 4.
   - El Bloque 1 aparece como aplicado → también correcto, `db push` aplicará
     solo el Bloque 2.
   - Aparece cualquier migración remota que no exista en local, o el esquema
     `elsa` ya tiene tablas sin migración que las respalde → **detenerse**. El
     esquema fue modificado a mano y hay que volcar ese estado a una migración
     antes de continuar (ADR 0001).

   Si el esquema ya existe, comprobar además que la auditoría no tenga
   operaciones fuera de catálogo (§3):

   ```sql
   select distinct operation from elsa.admin_audit_log
   where operation not in (
     'bootstrap_admin','create_account','grant_permission','revoke_permission',
     'enable_user','disable_user','promote_admin','demote_admin');
   ```

   Debe devolver cero filas.

4. **Ver el diferencial antes de aplicar.**

   ```bash
   supabase db diff --linked --schema elsa
   ```

5. **Aplicar.**

   ```bash
   supabase db push
   ```

6. **Verificar.** Las consultas de §6 deben coincidir con la tabla de §2.

### Procedimiento en PowerShell (Windows)

Estado de partida ya verificado: Bloque 1 aplicado, Bloque 2 pendiente.
Ejecutar desde la raíz del repositorio.

```powershell
# --- 0. Contexto ---
cd C:\ruta\a\Elsa-ai
git rev-parse --abbrev-ref HEAD     # claude/bloque-2-activo-tecnico-bom-x8aeic
git status --porcelain              # sin salida
supabase --version

# --- 1. Última comprobación segura ---
supabase migration list             # confirmar que 20260906010000 sigue sin remoto
supabase db diff --linked --schema elsa   # ver el diferencial real
supabase db push --dry-run          # listar qué se aplicaría, sin aplicar
```

Antes de continuar, en el **SQL Editor** del panel de Supabase (así ninguna
credencial pasa por la terminal) comprobar que la auditoría no tiene
operaciones fuera del catálogo del Bloque 1, que harían fallar el
`add constraint` de §3:

```sql
select distinct operation from elsa.admin_audit_log
where operation not in (
  'bootstrap_admin','create_account','grant_permission','revoke_permission',
  'enable_user','disable_user','promote_admin','demote_admin');
```

Debe devolver **cero filas**. Si devuelve alguna, detenerse y reportar.

```powershell
# --- 2. Aplicar únicamente la migración pendiente ---
# La CLI lista lo pendiente y pide confirmación. Debe mostrar SOLO
# 20260906010000. Si aparece cualquier otra cosa: responder N y detenerse.
supabase db push
```

```powershell
# --- 3. Validación inmediata ---
supabase migration list             # 20260906010000 debe aparecer ya en Remoto
```

Y en el SQL Editor:

```sql
-- 24
select count(*) as tablas from pg_tables where schemaname = 'elsa';

-- una sola fila: true | 24
select c.relrowsecurity as rls, count(*)
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'elsa' and c.relkind = 'r'
group by 1;

-- 0
select count(*) as politicas from pg_policies where schemaname = 'elsa';

-- debe incluir 'bom_published', 'reviewer_granted', etc.
select pg_get_constraintdef(oid) from pg_constraint
where conname = 'ck_audit_operation';

-- índice parcial de versión publicada única
select indexdef from pg_indexes
where schemaname = 'elsa' and indexname = 'uq_published_version_per_asset';

-- 20 tablas nuevas, todas vacías
select relname, n_live_tup from pg_stat_user_tables
where schemaname = 'elsa' order by relname;
```

```powershell
# --- 4. Detenerse ---
git status --porcelain              # sin salida: db push no toca el repositorio
```

Aplicar la migración **no** genera cambios en el árbol de trabajo. No abrir PR
ni hacer merge en este punto: reportar los resultados de la validación primero.

Si algo falla durante `db push`, la migración corre en una transacción y no
deja estado intermedio (§7). Reportar el error tal cual, sin reintentar a
ciegas.

### Ensayo previo realizado

Antes de escribir este runbook se aplicaron ambas migraciones, en orden, sobre
un PostgreSQL 16 limpio dentro del entorno de la sesión. Resultados reales:

- Bloque 1 y Bloque 2 aplican sin error (solo avisos `NOTICE` de
  `drop trigger if exists` sobre disparadores inexistentes, que es lo esperado
  en una base nueva).
- Reejecutar el Bloque 2 sobre la base ya migrada termina con código 0 y sin
  una sola línea que no sea `NOTICE`: la migración es idempotente.
- El esquema resultante coincide con la tabla de §2, incluidas las 24 tablas
  con RLS activo y cero políticas.
- El guion de reversión de §7 deja el esquema exactamente con las cuatro
  tablas del Bloque 1 y restaura `ck_audit_operation` a su forma original.

La base de ensayo se eliminó al terminar. Esto verifica el SQL, no el proyecto
remoto: no sustituye al paso 3.

## 6. Verificación posterior

```sql
-- 24 tablas
select count(*) from pg_tables where schemaname = 'elsa';

-- 24 con RLS, 0 sin RLS
select c.relrowsecurity, count(*)
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'elsa' and c.relkind = 'r'
group by 1;

-- 0 políticas
select count(*) from pg_policies where schemaname = 'elsa';

-- el catálogo de auditoría incluye las operaciones del Bloque 2
select pg_get_constraintdef(oid) from pg_constraint
where conname = 'ck_audit_operation';

-- índice parcial de versión publicada única
select indexdef from pg_indexes
where schemaname = 'elsa' and indexname = 'uq_published_version_per_asset';
```

Comprobación funcional mínima, sin insertar datos reales: crear un activo
técnico de prueba en el ambiente TEST, publicarle dos versiones y confirmar
que la segunda publicación falla mientras la primera siga `published`.

## 7. Reversión

La migración corre dentro de una transacción y no usa `concurrently`. Por
tanto **un fallo durante `db push` no deja estado intermedio**: PostgreSQL
revierte todo. El escenario de reversión no es "la migración falló" sino
"la migración se aplicó y se decide dar marcha atrás".

Para ese caso está `supabase/rollback/20260906010000_rollback.sql`, que:

1. elimina las 20 tablas del Bloque 2 con `drop ... cascade`,
2. elimina la función `elsa.forbid_review_mutation()`,
3. restaura la restricción `ck_audit_operation` a su forma del Bloque 1.

Ese archivo **no** vive en `supabase/migrations/`: no es una migración y la CLI
no debe aplicarlo por su cuenta. Se ejecuta a mano y solo por decisión
explícita.

Advertencia sobre el paso 3: si en la auditoría ya hay operaciones del Bloque 2
registradas, restaurar la restricción antigua fallará porque esas filas la
violan. Es el comportamiento correcto — la auditoría es append-only y no se
edita para acomodar una reversión. En ese caso hay que decidir conscientemente
si se deja el catálogo ampliado (opción recomendada: es inocuo) o se aborta la
reversión.

El guion corre dentro de una transacción, así que ese fallo no deja el
esquema a medias: se comprobó ejecutándolo contra una base con una fila de
auditoría del Bloque 2 y las 20 tablas seguían intactas después del error.

La reversión **destruye datos** de conocimiento técnico. Antes de ejecutarla,
respaldar:

```bash
supabase db dump --linked --schema elsa -f respaldo-elsa-$(date +%F).sql
```

El volcado contiene datos técnicos internos: es privado, no se versiona y está
cubierto por `.gitignore`.

## 8. Qué no cubre este runbook

- No hay migración de datos: las 20 tablas nacen vacías.
- No hay ventana de indisponibilidad que gestionar: no existe todavía tráfico
  productivo contra este esquema.
- La ingesta de los archivos reales de Tampella es un paso posterior y manual,
  ejecutado por el usuario en su máquina. Ni los archivos ni sus derivados
  entran al repositorio.
