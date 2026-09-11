# Contrato de documento, versión y chunk

Qué representa cada tabla del modelo documental, qué garantiza y qué no.

La cadena es siempre la misma y no se puede saltar ningún eslabón:

```
documento ──► versión ──► sección ──► chunk
     │            │
     │            └── ejecución de ingesta ──► archivo original (hash + bytes privados)
     │
     └── alcance (dominio, equipo)  ──►  el mismo del Bloque 1
```

---

## 1. Documento — la identidad estable

`elsa.documents`

Un documento es «el manual de lubricación del equipo X»; sus versiones son
las ediciones de ese manual. **La identidad no es el archivo.** Si lo fuera,
cada edición nueva rompería toda referencia anterior y la historia se
perdería.

| Campo | Qué es |
|---|---|
| `domain` | Dominio de conocimiento. Primera mitad del alcance |
| `asset_id` | Activo al que aplica. **Nulo** si aplica al dominio completo |
| `code` | Clave de negocio, normalizada y única dentro del dominio |
| `title` | Nombre legible. Es el que aparece en una cita |
| `source_kind` | `manual`, `procedure`, `instruction`, `technical_note`, `approved_narrative` |

El alcance de autorización es `(domain, asset.code)` — exactamente el par que
ya usan `permission_grants` y `technical_assets`. **No hay un segundo modelo
de permisos.** Un documento de dominio (`asset_id` nulo) exige permiso sobre
el dominio completo: un permiso de un solo equipo no lo alcanza.

Una clave foránea compuesta `(asset_id, domain)` impide que un documento
diga pertenecer a un dominio y cuelgue de un activo de otro. Sin ella el
alcance podría mentir sin que nada fallara.

---

## 2. Ejecución de ingesta — qué pasó al procesar un archivo

`elsa.document_ingestion_runs`

Una ejecución por archivo procesado, termine bien o mal.

- `status`: `received` → `processing` → `completed` | `failed`.
- `failure_kind`: `file`, `parse`, `validation`, `storage`, `database`. Una
  ejecución fallida **tiene** que decir por qué, y lo garantiza la base.
- `stats`: **solo conteos y códigos**. `{"chunks": 42, "warnings":
  {"table_split": 3}}`. Nunca una línea del documento: un reporte de
  diagnóstico no puede filtrar un manual interno.

Existe separada de `elsa.imports` porque una importación del Bloque 2 exige
un activo técnico y estas no: hay documentación de dominio que no cuelga de
ningún equipo.

---

## 3. Versión — el contenido en un momento dado

`elsa.document_versions`

Estados, y el orden en que se recorren:

```
pending_validation ──► approved ──► published
        │                              │
        └──► rejected                  └──► superseded  (al publicarse otra)
```

`received` y `processing` pertenecen a la ingesta, no a la versión: **una
versión solo existe si el chunking terminó**.

### Dos hashes, no uno

| Hash | De qué |
|---|---|
| `content_sha256` | Los bytes del archivo original |
| `structure_sha256` | Las secciones y chunks producidos |

Dos versiones con el mismo contenido y distinta estructura significan que
cambió el extractor o la política de chunking, **no el documento**. Sin los
dos hashes esa diferencia sería invisible y alguien la leería como un cambio
del manual.

Por eso la versión guarda también `extractor`, `extractor_version`,
`chunking_profile` y `chunking_parameters`: los límites exactos con los que
se chunkeó. Dos versiones chunkeadas con límites distintos no son
comparables, y sin ese registro nadie podría saber si una diferencia viene
del documento o de un cambio de configuración.

### Garantías del esquema

- `uq_published_document_version` — índice parcial sobre `state =
  'published'`. Dos versiones vigentes del mismo documento son **imposibles**,
  no improbables.
- `unique (document_id, version_number)` — los números no se reutilizan.
- `run_id` es `unique` — una ejecución produce como mucho una versión.
- Una versión publicada tiene que decir cuándo y por quién.

---

## 4. Sección — el árbol de títulos

`elsa.document_sections`

| Campo | Qué es |
|---|---|
| `path` | Dirección estructural: `1`, `1.2`, `1.2.3` |
| `number_label` | La numeración **impresa** en el documento: `3.2` |
| `depth` | Profundidad en el árbol, desde 1. `0` es el preámbulo |
| `ordinal` | Orden de lectura dentro de la versión, sin huecos |

`path` se calcula por **posición en el árbol**, no por la numeración
impresa. Los manuales reales tienen títulos sin numerar, numeraciones que se
repiten entre capítulos y saltos de numeración; la posición, en cambio,
siempre existe y siempre es única.

El contenido anterior al primer título no se descarta ni se cuelga de una
sección que no lo contiene: recibe una **sección de preámbulo** (`path` `0`,
`is_preamble`) que declara lo que es. Un manual empieza a menudo con el
alcance y las condiciones de seguridad, y esa es justo la parte que no puede
perderse.

---

## 5. Chunk — la unidad recuperable

`elsa.document_chunks`

Cada chunk conserva, sin excepción:

| Trazabilidad | Cómo |
|---|---|
| Documento | `version → document` |
| Versión | `version_id`, **en la propia fila del chunk** |
| Tipo de fuente | `document.source_kind` |
| Dominio | `document.domain` |
| Activo técnico | `document.asset_id` |
| Sección y título | `section_id`, `section_path`, `section_title` |
| Ruta de títulos | `heading_trail`, de la raíz hacia abajo |
| Página o rango | `page_start`, `page_end` |
| Posición / orden | `ordinal`, `index_in_section`, `structural_key` |
| Hash | `content_sha256` |
| Ejecución de ingesta | `version → run` |
| Estado de publicación | `version.state` |
| Ámbito / permisos | `document.domain` + `asset.code` |
| Referencia al texto fuente | `char_start`, `char_end`, `block_start`, `block_end` + `source_artifacts.storage_key` |

### Un chunk nunca mezcla dos versiones

`version_id` está en la fila del chunk, no solo en su sección. Y una clave
foránea compuesta `(section_id, version_id)` impide que un chunk de la
versión 2 apunte a una sección de la versión 1. Sin ella, la procedencia
mentiría sin que nada fallara.

### `structural_key` — la dirección con la que se comparan versiones

`<sección>#<índice>`, por ejemplo `1.3.2#0001`.

Es **posicional a propósito**. Si alguien inserta un párrafo, los chunks
siguientes de esa sección cambian de dirección y vuelven a revisión. Es
conservador —marca como modificado algo que quizá no cambió— y esa es la
dirección correcta del error: dar por validado un dato que sí cambió sería
mucho peor.

La comparación entre versiones reutiliza
`elsa.core.versioning.classify_versions`, la misma del Bloque 2: la
identidad es `structural_key` y la huella es `content_sha256`.

| Clasificación | Significa |
|---|---|
| `new` | No estaba en la versión publicada |
| `modified` | Estaba y su contenido cambió → vuelve a revisión |
| `unchanged` | Estaba y no cambió → su validación puede heredarse |
| `retired` | Estaba y ya no está |

### `heading_trail` es metadato, no contenido

La ruta de títulos se guarda aparte y **no se antepone al texto del chunk**.
Mezclarla con el contenido cambiaría el hash del texto y haría imposible
saber qué decía el documento exactamente. Anteponerla al indexar, si el
modelo de embeddings lo necesita, es decisión del Bloque 4.2.

### No hay columna vectorial

Ninguna, y no es un olvido. La dimensión del vector depende del modelo de
embeddings, que se decide en el Bloque 4.2; declararla ahora obligaría a
migrar la tabla entera al elegirlo.

---

## 6. Ciclo de vida

`ingestar → validar → comparar → activar/publicar`

El orden lo impone `elsa.services.document_ingestion` y no es arbitrario:

1. **SHA-256 antes de mirar el archivo.** Es la huella del original y la base
   de la idempotencia.
2. **¿Ya se ingirió este contenido exacto?** Entonces se devuelve la
   ejecución original y no se crea una versión.
3. **Los bytes al almacenamiento privado.** Si no responde, no se registra
   nada: fingir que el archivo está guardado sería perder evidencia sin que
   nadie se entere.
4. **Se abre la ejecución de ingesta.** La unicidad la impone la base, no la
   comprobación del paso 2: dos peticiones simultáneas con el mismo archivo
   pasan las dos por el paso 2 y solo una sobrevive al 4.
5. **Extracción.** Un formato ilegible cierra la ejecución como `file`; un
   fallo del extractor, como `parse`.
6. **Chunking** determinístico.
7. **Validación.** Lo bloqueante cierra la ejecución; los avisos se
   registran como conteos y siguen.
8. **Comparación** con la versión publicada.
9. **Escritura de la versión entera**, en una transacción, como
   `pending_validation`.

### Dos promesas que sostienen todo lo demás

**Una versión nueva nunca reemplaza sola a la publicada.** Publicar es una
operación aparte que toma una persona, y solo se puede publicar una versión
`approved`. Aprobar no es publicar.

**Una ingesta fallida nunca destruye la última versión válida.** Un fallo en
cualquier paso deja intacta la versión publicada, con todos sus chunks. Eso
es lo que hace seguro reintentar sobre un documento que ya está en uso.

### El historial

`elsa.document_version_events` es estrictamente append-only, protegido por
un disparador: aprobar, rechazar, publicar y reemplazar son cuatro filas
nuevas, nunca una modificación de la anterior. Una tabla que puede
reescribirse no es trazabilidad. Rechazar exige un motivo, y lo garantiza la
base.

---

## 7. Procedencia

`elsa.document_chunk_provenance` es una **vista** que reconstruye la cadena
completa en una sola lectura: chunk → sección → versión → documento →
activo → ejecución → archivo original.

Es una vista y no columnas copiadas en `document_chunks` porque publicar una
versión cambia el estado de todos sus chunks: denormalizarlo crearía dos
fuentes de verdad para un valor que se mueve, y tarde o temprano una de las
dos mentiría.

Expone `scope_domain` y `scope_equipment` —el alcance que hay que autorizar—
para que la consulta de recuperación pueda filtrar por permiso en el mismo
`where`, y no recuperar primero para ocultar después.

Se declara **`with (security_invoker = true)`**, y no es opcional. Una vista
de PostgreSQL se ejecuta por defecto con los privilegios de su propietario,
de modo que **ignora la RLS de las tablas que consulta**. Sin esa opción,
conceder lectura sobre esta vista a cualquier rol le entregaría el corpus
documental entero sin filtrar una sola fila, mientras la misma consulta
contra `document_chunks` devolvía cero filas. Con la opción activada, la
vista se evalúa con los privilegios y la RLS de quien la consulta; el
backend, que usa credencial de servicio con `BYPASSRLS`, la sigue viendo
entera.

La regresión está cubierta por dos pruebas en
`tests/test_migrations_documents.py`: una comprueba la opción y otra que un
rol con `SELECT` sobre **todas** las tablas base sigue obteniendo cero filas
por la vista.

---

## 8. Autorización, antes de recuperar

El orden es siempre el mismo (`elsa.core.document_access`):

1. Resolver qué alcances puede leer la persona (`readable_scopes`).
2. Pedir al repositorio **solo** esos alcances.
3. Recuperar.

Nunca al revés. `DocumentRepositoryPort.list_published_chunks` exige los
alcances como argumento obligatorio y no admite comodín: con una lista vacía
devuelve vacío, que es la respuesta correcta para quien no tiene ningún
permiso.

`readable_scopes` se calcula a partir de los documentos que existen y no de
los permisos en bruto, porque un administrador tiene acceso total y no lleva
un permiso por cada alcance: enumerar sus permisos daría una lista vacía y
no recuperaría nada.

---

## 9. Limitaciones conocidas

Se registran aquí porque quien continúe el proyecto tiene que conocerlas.

| Limitación | Consecuencia | Cuándo se aborda |
|---|---|---|
| Solo texto plano y Markdown | Un PDF se rechaza con un aviso claro; no se adivina | Adaptador de PDF, sin OCR, cuando haya documentos reales que probar |
| Sin OCR | Un documento escaneado no se ingiere | Cuando se decida entre Docling y PaddleOCR |
| Estimación de tokens por caracteres | Los límites son aproximados | Con el tokenizador real del modelo de embeddings (4.2) |
| `structural_key` posicional | Insertar un párrafo marca como modificados los chunks siguientes de esa sección | Es deliberado; la alternativa validaría de más |
| Cierre PostgreSQL pendiente | Adaptador implementado; falta resolver la garantía relacional permanente | Ver [estado de 4.1.b](postgres-documents-4-1b.md) |
| Sin endpoints HTTP | La ingesta documental se ejerce por la herramienta de aceptación | Cuando el Centro de Control los necesite |
| Una tabla dentro de un manual no se interpreta | Se conserva como texto, no como datos | No previsto: interpretarla duplicaría el BOM |

---

## Ver también

- [`knowledge-architecture.md`](knowledge-architecture.md) — qué se chunkea y qué no
- [`document-chunking.md`](document-chunking.md) — estrategia de chunking
- [`document-acceptance.md`](document-acceptance.md) — prueba de aceptación
- [`migration-runbook-bloque-4.md`](migration-runbook-bloque-4.md) — aplicar la migración
