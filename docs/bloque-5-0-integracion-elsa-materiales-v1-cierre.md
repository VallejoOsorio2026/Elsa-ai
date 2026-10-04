# Cierre formal — Integración ELSA → Materiales V1

- **Fecha:** 2026-10-04
- **Estado:** **CERRADO**
- **Qué cierra:** la integración de ELSA como consumidor real del contrato
  Materiales–ELSA V1, en una sola vertical: **disponibilidad de un código de
  material exacto**.
- **Qué NO cierra:** no cierra **M1 global**, ni M4 operativo, ni M6, ni M8, ni
  H5, ni PENDIENTE-020/021/022, ni el acceso remoto (D2). Ver §20.
- **Identificador del bloque:** el repositorio no define un identificador formal
  para este trabajo posterior a M1-C; **no se inventa uno** (se nombra por su
  contenido). Sigue a los cierres M1-A, M1-B y M1-C.
- **Marcas de afirmación** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**,
  **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Sanitización:** este documento no contiene datos reales de planta. Se omiten a
  propósito el código del material de la prueba, su descripción, existencias,
  ubicaciones, versión y recuento del inventario, identificadores de usuario,
  correos, tokens, claves y referencias de proyecto (regla 12, regla 11 y
  `BLOCK_CLOSURE_STANDARD.md`, «Qué nunca entra en un documento de cierre»).

---

## 1. Objetivo

Que un ingeniero, autenticado en la página de ELSA, pueda preguntar por la
disponibilidad de un material por su código exacto y reciba la respuesta
**factual y trazable que devuelve Materiales en vivo**:

```text
usuario → página ELSA → ELSA → HTTPS/PostgREST → Materiales
        → inventario SAP real → respuesta visible
```

**DECISIÓN TOMADA** (responsable del proyecto): empezar por una vertical mínima y
verificable, antes que por una solución general de búsqueda.

## 2. Alcance

**Entró (HECHO DEL REPOSITORIO, 12 archivos):**

| Archivo | Papel |
|---|---|
| `src/elsa/adapters/supabase_materials.py` | Adaptador HTTPS/PostgREST de `MaterialsPort` |
| `src/elsa/core/material_code.py` | Detección conservadora del código exacto |
| `src/elsa/container.py` | Fábrica del puerto atada al token de cada petición; reporte de salud |
| `src/elsa/api/v1/assistant.py` | Bloque `availability`, aditivo |
| `src/elsa/config.py` | `ELSA_MATERIALS_TIMEOUT_SECONDS` |
| `.env.example` | Declaración de la variable |
| `docs/environment-variables.md` | Documentación de la variable |
| `docs/materials-integration.md` | Autenticación, validación y prueba real |
| `web/js/screens/chat.js` | Presentación del bloque |
| `tests/test_materials_http_adapter.py` | Pruebas unitarias del adaptador |
| `tests/test_material_code.py` | Pruebas del detector |
| `tests/test_api_assistant_availability.py` | Pruebas del endpoint con transporte simulado |

**Quedó fuera, explícitamente:** búsqueda por texto o difusa en Materiales; login
real con formulario; acceso remoto (D2); LLM en el flujo; caché de existencias;
reintentos; consulta por lote; carga de BOM, AMEF o documentos; cambios en
Materiales, en el esquema de Supabase o en migraciones; cualquier dependencia
nueva.

## 3. Estado inicial

- **HECHO DEL REPOSITORIO:** `main` en `082399e` (merge del PR #39, cierre de
  M1-A). `MaterialsPort` existía con su contrato tipado y un fake determinista, y
  **no tenía adaptador real, transporte ni consumidor**. El chat
  (`POST /api/v1/assistant/{domain}/{asset}/ask`) hacía solo búsqueda literal
  sobre el BOM publicado, sin LLM.
- **HECHO DEL REPOSITORIO:** la identidad ya era la de Materiales: ELSA valida el
  JWT contra el JWKS e issuer de ese proyecto (ADR 0002, ADR 0005) y ya reenviaba
  ese mismo token a su PostgREST para leer el perfil propio. Por eso el token
  de ELSA **sí** era utilizable contra Materiales.
- **Proveedor** (repositorio de Materiales, solo lectura, en `339f5d0`): las tres
  RPC del contrato V1 desplegadas y el ACL cerrado (`EXECUTE` solo para
  `authenticated`). No se tocó nada allí.
- **Baseline de pruebas:** 1453 passed, 230 skipped, 2 failed (**HECHO MEDIDO**,
  §6).

## 4. Trabajo realizado

En orden:

1. Precheck de Git, baseline de pruebas y auditoría dirigida del código, los ADR y
   el contrato del proveedor.
2. Plan de archivos presentado y aprobado antes de editar (regla de más de dos
   archivos): primero 14, luego corregido a 9 y, tras detectar que
   `ELSA_AUTH_TIMEOUT_SECONDS` era solo de identidad, **12**.
3. Implementación del adaptador, el detector, el cableado en el contenedor, el
   bloque `availability` y su presentación.
4. Pruebas específicas, regresión relevante y suite completa.
5. Prueba **live directa** ELSA → Materiales.
6. Arranque local de ELSA y prueba **E2E desde la página**, con la preparación
   previa descrita en §12 y §13.
7. Saneamiento: sustitución de datos reales por fixtures sintéticos y rehacer la
   rama sin historia previa (§13).
8. PR definitivo #41 y merge (§17).

## 5. Decisiones

**DECISIÓN TOMADA** salvo indicación. Cada una con su motivo:

| # | Decisión | Motivo |
|---|---|---|
| 1 | Reutilizar el JWT del propio usuario, **por petición**; el adaptador compartido no conserva ningún token | Sin `service_role` y sin superficie nueva de credenciales; límite verificable por prueba |
| 2 | **No** modificar `MaterialsPort`: el puerto se ata al token en una fábrica del contenedor | El puerto es una decisión cerrada por ADR (0021, 0028); cambiarlo habría costado 3 archivos más y reabierto el ADR |
| 3 | Lookup **exacto**, sin `trim`, relleno, conversión numérica ni cambio de ceros | M3-A (ADR 0024 §8) |
| 4 | Detección conservadora: 6 a 18 dígitos ASCII aislados y palabra de inventario (o mensaje que es solo el código); más de un código distinto es **ambiguo** y no se consulta | Un hecho vivo no debe derivar de una conjetura; V1 es unitario |
| 5 | El texto libre **nunca** se envía como código | ADR 0021 §2; la búsqueda por texto no está habilitada en el descriptor |
| 6 | Descriptor V1 validado de forma perezosa con la primera llamada autenticada, caché de 10 min con información solo contractual, **falla cerrado** | El ACL no permite sondearlo sin sesión; ADR 0021 §15.3: la versión nunca se adivina |
| 7 | `contract_version` es la cadena `"1"` | ADR 0021 §15 |
| 8 | `NOT_RETURNED` no es autoritativo y nunca se redacta como inexistencia; `coverage = UNKNOWN` se conserva; las ubicaciones no se colapsan; `extracted_at` no se transporta | ADR 0021, 0025, 0027 |
| 9 | Fallos técnicos (tiempo, red, 401, 403, 429, 5xx) son `UNAVAILABLE`, nunca una ausencia; sin reintentos | ADR 0021 §5 |
| 10 | Variable propia `ELSA_MATERIALS_TIMEOUT_SECONDS` (8 s, mayor que 0), independiente de `ELSA_AUTH_TIMEOUT_SECONDS` | La segunda es semánticamente de identidad; acoplarlas habría alterado una al ajustar la otra |
| 11 | El bloque `availability` es **aditivo**: el BOM responde igual con o sin él | Regla 9: funcionar parcialmente y declararlo |
| 12 | `/health/ready` reporta `materials` como `degraded` («se verifica con la primera consulta autenticada») | Sin sesión no hay forma honesta de sondear; no se inventa un `ok` |
| 13 | **D1 = A:** para la prueba de página se pega el token en el login actual; el login real queda para otro bloque | Regla 20: no ampliar el alcance |
| 14 | **D2 fuera:** acceso desde otra red no se aborda aquí | Regla 20; es un bloque de infraestructura |
| 15 | Crear el activo `tampella` con el endpoint administrativo existente, tras auditar el historial | §12 |
| 16 | Rehacer la rama sin historia previa para retirar datos reales de la historia pública | §13 |

**PENDIENTE (regla 25):** las decisiones 1, 2 y 6 son arquitectónicas y no tienen
ADR propio; este bloque no creó ninguno. Responsable: responsable del proyecto.

## 6. Pruebas

**HECHO MEDIDO.** Qué se ejecutó:

- Pruebas específicas del bloque, sobre el árbol final: **103 passed, 0 failed**
  (adaptador 49, detector 25, endpoint 29).
- Regresión relevante (configuración, salud, asistente, autenticación,
  identidad, ausencia segura, registro seguro, demo): **321 passed**.
- Suite completa sobre el árbol funcional: **1556 passed, 230 skipped,
  2 failed**. Los 230 *skips* son pruebas que requieren PostgreSQL
  (`ELSA_TEST_DATABASE_URL` sin definir en esta máquina).
- `ruff check`: limpio. `ruff format --check`: limpio. `git diff --check`: limpio.
  `mypy` solo reporta 3 errores preexistentes en `src/elsa/bench/runner.py`
  (módulo `resource`, inexistente en Windows).

**Los 2 fallos de la suite completa son los mismos del baseline**, por causa de
plataforma (HECHO MEDIDO, causa leída en el código): en Windows no existe el
módulo `resource`, así que `peak_rss_mb` vale `None`:

```text
tests/test_bench_harness.py::test_a_run_records_what_produced_it
tests/test_bench_harness.py::test_peak_memory_is_measured_where_the_posix_api_exists
```

Conclusión válida: **103 pruebas nuevas, 0 fallos nuevos** (1556 − 1453 = 103
pruebas más, mismos 230 *skips* y mismos 2 fallos).

Nota de procedencia (honestidad sobre el momento): la suite completa se midió
sobre el árbol funcional **antes** del saneamiento de fixtures. Los commits
posteriores solo cambiaron datos de prueba y comentarios; sobre el árbol final se
repitieron las 103 pruebas específicas y las comprobaciones de calidad, no la suite
completa local. El CI de Linux (§17) sí ejecuta la suite completa sobre el árbol
final y terminó en verde; su recuento no se pudo leer porque los *logs* de Actions
exigen sesión de GitHub (**INFERENCIA**: no hay fallos nuevos).

Qué demuestra cada nivel y qué no: las pruebas con transporte simulado demuestran
enrutamiento, mapeo, errores y seguridad; **no** demuestran autenticación real,
conectividad, el ACL de Materiales ni inventario real. Eso es de §8 y §9.

## 7. Comandos relevantes

```bash
uv run pytest tests/test_material_code.py tests/test_materials_http_adapter.py \
  tests/test_api_assistant_availability.py
uv run ruff check src tests && uv run ruff format --check src tests
uv run pytest                                   # suite completa
uv run uvicorn elsa.main:create_app --factory --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/api/v1/health/ready
```

Página local: `http://127.0.0.1:8000/app/`. Procedimiento de prueba real:
`docs/materials-integration.md` §7.

## 8. Resultados

### 8.1 Prueba live directa — APROBADA

Ejecutada por el responsable del proyecto en su terminal con un script temporal
(§12) y pegada en la sesión (**medida por él**, no reejecutada por Claude Code).
Valores sanitizados:

```text
role                  = authenticated
SupabaseJwtAuthAdapter = OK  (ELSA verifica el mismo token)
descriptor             = contract_version "1", 3 operaciones correctas
inventory_status       = OK, coverage UNKNOWN
lookup exacto real     = call_status ok, outcome matched,
                         match_origin exact_material_code
ubicaciones            = 2, preservadas
last_failure           = None
latencia total         ≈ 1610 ms
```

Sin `service_role` y sin secretos impresos.

### 8.2 Prueba E2E desde la página — APROBADA

**HECHO MEDIDO** (observado por el responsable en la interfaz; el recorrido
HTTP lo observó Claude Code en el *log* sanitizado del servidor):

- Usuario real administrador, token pegado en el login actual (D1 = A), equipo
  Tampella, dominio `mantenimiento`, **BOM publicado: no**.
- Pregunta: «¿Qué disponibilidad tiene el material <código>?».
- La interfaz mostró: material encontrado con descripción, disponible y
  comprometido, **dos ubicaciones**, fuente `materiales`, versión de inventario,
  `match_origin exact_material_code`, `contract_version 1` y cobertura
  `UNKNOWN` preservada.
- Recorrido en el *log* del servidor (campos sanitizados):

```text
POST /api/v1/assistant/mantenimiento/tampella/ask        200  (~2,1 s)
elsa_v1_get_contract_descriptor     http_status 200  elapsed_ms 235
elsa_v1_lookup_material_by_code     http_status 200  elapsed_ms 328
materials lookup interpreted: call_status ok, outcome matched,
  contract_version "1", match_origin exact_material_code, source_version presente
```

- Búsqueda de `Bearer`, `eyJ`, `apikey`, `sb_publishable`, `access_token`,
  `password`, cadenas de conexión y `@` en todo el *log* del servidor:
  **0 coincidencias**.
- **Hallazgo:** que el BOM de Tampella no esté publicado **no** bloquea la consulta
  directa de disponibilidad a Materiales; solo exige que el activo exista y que la
  persona tenga alcance.

### 8.3 Estado de salud observado

`GET /api/v1/health/ready` → **HTTP 200**, estado global `degraded`. `auth` y
`database` en `ok`. `materials` en `degraded` por diseño (no crítico). `degraded`
por dependencias no críticas ya existentes (transcripción simulada, almacenamiento
en memoria en DEV) y `not_configured` para LLM, embeddings, OCR y reranker.

## 9. Métricas

| Métrica | Valor | Método |
|---|---|---|
| Pruebas nuevas | 103 | `pytest`, árbol final |
| Suite completa | 1556 passed, 230 skipped, 2 failed | `pytest` completo en PC1 |
| Latencia del lookup en el servidor | 328 ms | campo `elapsed_ms` del *log* |
| Latencia del descriptor | 235 ms | ídem (una vez por 10 min) |
| Latencia de la petición `/ask` | ~2,1 s | `duration_ms` del *log* |
| Latencia de la prueba live directa | ≈ 1610 ms | medida por el responsable |
| Tamaño del cambio | 12 archivos, +2228 / −3 | `git diff --stat`, PR #41 |

Las cifras de latencia son de una ejecución local en PC1; no son un rendimiento
garantizado.

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO / DEL PROCESO.** Claude Code (modelo Sonnet 5.5) propuso el
plan, implementó los 12 archivos, escribió las pruebas, ejecutó las verificaciones
de §6 y §8.2 (log) y redactó este documento. El responsable del proyecto aprobó cada
plan antes de editar y ejecutó él mismo todo lo que implicaba credenciales.

- **Identificador de sesión:** el directorio local de sesión de Claude Code que
  aparece en las rutas de trabajo es `45b49d68-581e-499f-a25d-802c126cf8f8`. No
  se contrastó contra otra fuente; se registra tal como aparece y **no** se
  garantiza más que eso.
- **Qué se revisó:** diffs y salidas reales; sin delegar en subagentes de revisión
  (`architecture-reviewer`, `security-reviewer`) en este bloque (**PENDIENTE**
  recomendable, §20).

## 11. Aportes de Codex

Nada que registrar. Codex no intervino en este bloque.

## 12. Operaciones manuales y de PowerShell

Todas fuera del repositorio. Los scripts auxiliares eran **temporales y no se
versionaron** (se describe lo que hacían, no su código):

- **Prueba live:** script en la terminal del responsable que hacía el inicio de
  sesión contra Supabase Auth de Materiales con correo y contraseña tecleados por
  él (la contraseña no se mostraba), verificaba el token con el verificador real de
  ELSA y llamaba al adaptador real. El token vivía solo en memoria.
- **Auditoría de solo lectura** de la base real de ELSA (transacción de solo
  lectura): reveló 2 cuentas activas, 0 *grants* activos y `technical_assets`
  **vacía**; todas las tablas del Bloque 2 en adelante, vacías.
- **Alta del activo `tampella`:** tras auditar el historial (migraciones, *seeds*,
  documentación y Git), se creó con el endpoint administrativo existente
  `POST /api/v1/admin/assets` (**HTTP 201** en el *log*), con exactamente
  `code=tampella`, `name=Tampella`, `domain=mantenimiento`, desde un script de una
  sola ejecución con el token solo en memoria. **No se creó ningún *grant***: el
  usuario de la prueba es administrador y el administrador no los necesita. No se
  tocó su cuenta ni se cargó BOM, AMEF, documentos ni conocimiento técnico.
- **Arranque local** de ELSA en `127.0.0.1:8000` con el `.env` real y su parada
  limpia al terminar.
- **Reactivación** del proyecto Supabase de ELSA por el responsable (ver §13).

**Conclusión de la auditoría sobre Tampella (HECHO DEL REPOSITORIO / MEDIDO):**

```text
TAMPELLA YA HABÍA SIDO INTEGRADO COMO TECHNICAL_ASSET = NO
EXISTE SEED/MIGRACIÓN PENDIENTE                       = NO
CREAR EL ACTIVO ERA LA ACCIÓN CORRECTA                = SÍ
```

Razones: ninguna migración inserta activos (solo dominios); el único *seed*
(`elsa.demo.seed`) se niega a escribir salvo en memoria y en DEV; el runbook del
Bloque 2 declara las tablas «nacen vacías» y la ingesta real «un paso posterior y
manual»; `docs/development.md` pone el alta del activo como paso 1.

## 13. Incidentes

| # | Incidente | Qué se hizo | Estado |
|---|---|---|---|
| 1 | **Datos reales en la historia pública.** El repositorio es público; los primeros commits publicados en la rama llevaban en sus pruebas datos reales de inventario (un código de material y cifras de carga). El cuerpo del PR se sanitizó **antes** de publicarse, así que nunca los mostró | Sustitución por fixtures sintéticos; rama nueva desde `main` sin historia previa; borrado de la rama remota antigua | Resuelto en el repositorio. **PENDIENTE (INFERENCIA):** GitHub puede conservar commits huérfanos accesibles por SHA hasta su recolección; si preocupa, solo el soporte de GitHub puede forzarla |
| 2 | **Gitleaks (`generic-api-key`).** Falló el escaneo de secretos | Ver el análisis abajo | Resuelto |
| 3 | **Proyecto Supabase de ELSA pausado.** `ELSA_DATABASE_URL` fallaba con «tenant/user not found» y ELSA no arrancaba | Diagnóstico de solo lectura, sin cambiar configuración; el responsable reactivó el proyecto | Resuelto (el pooler tardó unos minutos en reconocerlo) |
| 4 | **Token en el portapapeles.** El script de alta leyó del portapapeles un texto que no era un JWT y abortó antes de escribir | Se sustituyó por un único script con el token solo en memoria | Resuelto; no hubo escrituras erróneas |
| 5 | **Cuenta sin equipo.** La interfaz mostró «cuenta activa pero sin equipo asignado» | La auditoría de solo lectura mostró que faltaba el activo, no un permiso | Resuelto con §12 |

**Incidente 2, análisis.** Gitleaks 8.21.2 escanea toda la historia descargada
(`fetch-depth: 0`, `gitleaks git`). El hallazgo, leído por el responsable en la
interfaz de GitHub porque los *logs* exigen sesión:

```text
RuleID: generic-api-key
File:   tests/test_materials_http_adapter.py
Line:   33
Commit: d04a7b0 (rama remota intermedia)
```

No era un secreto real: era un valor sintético de prueba con forma de clave
publicable de Supabase. Cadena de razonamiento y sus errores:

1. Se sospechó de dos fixtures por su entropía; se cambiaron por valores ya
   aceptados en `main`. Gitleaks siguió fallando.
2. **Error de planteamiento (de Claude Code):** corregir el valor en un commit
   posterior no podía limpiar el escaneo, porque el commit anterior conservaba el
   valor en la historia. Se rehízo la rama con un solo commit; siguió fallando.
3. **Causa real:** el *runner* descarga la historia de **todas** las ramas
   remotas, y el commit problemático seguía alcanzable desde la rama remota
   intermedia (no era ancestro de la rama final).
4. Se cerró el PR #40 sin merge, se borró esa rama remota y se relanzó el CI **sin
   cambiar código**: Gitleaks pasó con el mismo HEAD. La causa quedó confirmada
   empíricamente.

No se desactivó Gitleaks, no se tocó su configuración, no se añadió *allowlist* y no
se modificó ningún *workflow*.

## 14. Git

- Todo el trabajo salió de ramas nuevas desde `origin/main`; nunca se commiteó
  directamente en `main` hasta este cierre documental.
- Sin *force push* y sin reescritura de historia compartida. La "limpieza" se hizo
  creando ramas nuevas y borrando las antiguas con push normal.
- Ningún archivo temporal, token ni evidencia local se versionó.

## 15. Ramas

| Rama | Papel | Fin |
|---|---|---|
| `claude/elsa-materiales-v1-integration` | Primera implementación (4 commits más saneamiento) | Borrada del remoto: conservaba datos reales en su historia |
| `claude/elsa-materiales-v1-integration-clean` | Segunda (sin historia, 2 commits) | Borrada del remoto: su commit `d04a7b0` mantenía el hallazgo de Gitleaks |
| `claude/elsa-materiales-v1-integration-final` | **Definitiva (1 commit)** | Mergeada con el PR #41 |

## 16. Commits

| Commit | Rama | Destino |
|---|---|---|
| `16d1850`, `a5560bc`, `7c9187b`, `6e6c47c`, `860d6cc` | primera rama | **descartados** |
| `d04a7b0`, `70a642d` | segunda rama | **descartados** |
| `e5e0c4501bcf11c49b8ff1eadcdaaf57aed51646` | rama final | **funcional definitivo**, `feat(materials): integrate live Materiales V1 availability` |
| `f586bbd60434ba4e498ec23a9429c2223722f88d` | `main` | merge del PR #41 (padres `082399e` y `e5e0c45`) |

**HECHO DEL REPOSITORIO:** `e5e0c45` es ancestro de `main`; el merge trae
exactamente los 12 archivos aprobados; `d04a7b0`, `70a642d`, `860d6cc` y `6e6c47c`
no son ancestros de `main`.

## 17. Pull requests

| PR | Estado | Detalle |
|---|---|---|
| #40 | **Cerrado sin merge** | Pertenecía a la historia intermedia descartada; se cerró al borrar su rama |
| #41 | **Mergeado** el 2026-10-04 | `feat(materials): ELSA to Materiales V1 live availability for exact codes`; 1 commit, 12 archivos, +2228 / −3; base `main`, merge commit `f586bbd` |

CI (HECHO MEDIDO por la API pública de GitHub, en solo lectura):

| Ejecución | Evento | HEAD | Gitleaks | Lint, types and tests |
|---|---|---|---|---|
| 37241680735, intento 2 | push (rama final) | `e5e0c45` | SUCCESS, job 111554950968 | SUCCESS, job 111554951129 |
| 37243505061 | pull_request (#41) | `e5e0c45` | SUCCESS, job 111556742355 | SUCCESS, job 111556742471 |
| 37243813387 | push (`main`, merge) | `f586bbd` | SUCCESS, job 111557625083 | SUCCESS, job 111557624988 |

Ejecuciones fallidas previas, todas por Gitleaks: 37231617466, 37239924848,
37240149338, 37240596878, 37241313933, 37241317687 (ramas ya descartadas) y el
intento 1 de la ejecución 37241680735 (rama final, mismo HEAD), que pasó en el
intento 2 tras eliminar la rama remota que mantenía alcanzable el commit
problemático.

## 18. Migraciones

**Nada que registrar.** No se escribió ni se aplicó ninguna migración, ni a ELSA ni
a Materiales (regla 15). El único cambio de datos en la base de ELSA fue la fila de
`technical_assets` del §12, hecha con el endpoint administrativo existente.

## 19. Estado operacional final

- **Funciona (probado):** consulta de disponibilidad por código exacto desde la
  página local, con identidad real, hasta el inventario de Materiales.
- **Degradado por diseño:** `materials` en `/health/ready` hasta la primera consulta
  autenticada (el ACL de Materiales no permite sondearlo sin sesión); el estado
  global es 200.
- **No conectado:** LLM, embeddings, OCR, reranker; la transcripción de voz es
  simulada.
- **Sin cambios:** el BOM de Tampella sigue **sin publicarse**; la base de ELSA
  conserva su activo `tampella` y no tiene BOM, AMEF ni documentos.
- **Servidor local:** detenido al terminar; ELSA no queda expuesto (no se abrió
  ningún puerto, túnel ni regla de firewall).

## 20. Pendientes

Ninguno de estos queda cerrado por este bloque:

| Pendiente | Responsable |
|---|---|
| **Acceso remoto seguro (D2)** | responsable del proyecto |
| Login real con formulario (hoy se pega el token; los tokens duran ~1 h) | responsable del proyecto |
| Publicar el BOM de Tampella, AMEF y conocimiento técnico | responsable del proyecto |
| Búsqueda por texto o difusa sobre Materiales | Contract Owner y Materiales |
| Cobertura global autoritativa (`coverage` sigue `UNKNOWN`) | Materiales |
| **ADR** de las decisiones 1, 2 y 6 de §5 (regla 25) | responsable del proyecto |
| Revisión con `security-reviewer` y `architecture-reviewer` (no se invocaron) | responsable del proyecto |
| Actualizar `PROJECT_HISTORY_AND_CURRENT_STATE.md` y `HANDOVER_AND_CONTINUITY_MAP.md`: su fila T5 aún dice que la fachada «no existe y no está solicitada» | responsable del proyecto |
| Posible retención de commits huérfanos por GitHub (§13, incidente 1) | responsable del proyecto |
| M1 global, M4, M6 operativo, M8, H5, PENDIENTE-020/021/022 | los de siempre; **no** se cierran por asociación |

**Límites conocidos de la funcionalidad:** solo código exacto; los códigos
alfanuméricos no se detectan (el dominio del Piloto Tampella es numérico, ADR 0024
§10); una corrida de 6 a 18 dígitos puede no ser un material (mitigado con la
palabra de inventario y el código único); `NOT_RETURNED` no prueba inexistencia; el
activo debe existir en ELSA y la persona debe tener alcance (o ser administradora).

## 21. Siguiente bloque

**Acceso remoto seguro a ELSA desde otro equipo o red (D2).** Motivo: la meta del
responsable es dejar PC1 encendido y consultar desde la empresa; hoy ELSA solo se
sirve en loopback o por HTTP en la red local, y la voz exige HTTPS fuera de
`localhost`. **No se inicia en este cierre.** Antes de abrir cualquier puerto o
túnel hace falta decidir el mecanismo (red privada o VPN preferible a exponer PC1) y
planificarlo como bloque propio.

---

## Criterios de cierre

| Criterio | Estado |
|---|---|
| PR #41 mergeado y verificado | Sí (`f586bbd`) |
| Commit funcional contenido en `main` | Sí (`e5e0c45`) |
| `main` local = `origin/main` | Sí en el momento de verificar |
| CI funcional en verde (rama, PR y merge) | Sí |
| Prueba live directa | Aprobada |
| Prueba E2E desde la página | Aprobada |
| Sin datos reales ni secretos en los 12 archivos | Sí |
| Documento de cierre versionado en `main` y CI posterior en verde | Se confirma en el commit y la ejecución que registran este cierre |

## Veredicto

**ELSA → MATERIALES V1 = CERRADO**, sujeto a que el CI del commit que versiona este
documento termine en verde; ese resultado y los SHA del commit de cierre se
registran fuera de este archivo, en el informe de la sesión, para no escribir aquí
un hecho que aún no existía al redactarlo.
