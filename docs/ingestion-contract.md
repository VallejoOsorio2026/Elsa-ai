# Contrato de ingesta de fuentes técnicas

Qué acepta ELSA, qué hace con ello y qué no hace nunca.

Los parsers viven en `src/elsa/ingestion/` y son **independientes de
FastAPI**: reciben bytes y devuelven estructuras de datos. No abren sockets,
no tocan la base y no saben qué es una petición HTTP. Eso permite probarlos
con archivos hostiles sin levantar la aplicación, y es lo que hace creíble
la afirmación de que un archivo malicioso no puede ejecutar nada: no hay
nada que ejecutar en el camino.

**Regla común: un archivo de entrada es contenido no confiable.** No se
ejecutan sus fórmulas, no se sigue ninguno de sus enlaces, no se descarga
ningún recurso que mencione y no se cree su extensión.

---

## 1. BOM de Ingeniería (`.xlsx`)

`POST /api/v1/technical/{domain}/{asset}/engineering-bom`

### Qué se rechaza, y antes de leer una sola celda

`inspect_xlsx` revisa la estructura del paquete antes de que ningún parser
lea contenido:

| Control | Motivo |
|---|---|
| Tamaño máximo | `ELSA_INGESTION_MAX_UPLOAD_BYTES` |
| Firma ZIP real | La extensión no es prueba de nada |
| Rutas internas | Absolutas, con `..` o con separadores del sistema |
| Entradas ejecutables | `.exe`, `.dll`, `.vbs`, `.js`, `.sh`… |
| Expansión total y por entrada | Bomba de descompresión |
| Número de entradas | `ELSA_INGESTION_MAX_ARCHIVE_ENTRIES` |
| `xl/vbaProject.bin` | Libro con macros: un `.xlsm` renombrado se rechaza por su contenido |
| `[Content_Types].xml` + `xl/workbook.xml` | Sin ellos no es un libro de Excel |

Los **enlaces externos** y las **conexiones de datos** no se rechazan pero
tampoco se siguen: se avisa de su presencia y el libro se abre con
`keep_links=False`, que los descarta al cargar.

### Cómo se interpreta

Hojas y columnas se reconocen por **sinónimos normalizados**, no por
posición ni por nombre exacto, y la fila de encabezados se busca (las
plantillas traen título y filas en blanco antes de la tabla). Un encabezado
con aclaraciones (`Cantidad (UN)`) empareja de forma laxa **solo si apunta a
un único campo**; si apunta a varios, es ambiguo y el valor se conserva sin
interpretar.

Hojas previstas: `BOM` (obligatoria), `Plano Despiece`,
`Tablas de Opciones (BOM)`, `AMEF`, `Valoración SOD`. Sin hoja de BOM la
importación falla; las demás producen un aviso.

**Una columna que no se reconoce no se pierde**: va a `extra` con un aviso.
Perder información por no haberla previsto es peor que guardarla sin
interpretarla.

De cada valor sensible se conservan **dos formas**: la normalizada, con la
que se compara, y la original, con la que se le demuestra a un ingeniero qué
decía exactamente su archivo.

### Fórmulas

El libro se abre con `data_only=False`, de modo que una celda con fórmula
llega como texto (`"=A1*2"`) y **no se evalúa**: el valor numérico queda
vacío, el original se conserva y se emite el aviso
`formula_not_evaluated`. Leer el resultado que Excel dejó cacheado sería
aceptar como verdad técnica un número que nadie en ELSA puede verificar.

### AMEF y NPR

El **NPR se calcula siempre en el backend** como `S × O × D`. Si el archivo
trae un NPR distinto, manda el calculado y se emite `rpn_recomputed`. Si
falta cualquiera de los tres factores no hay NPR: uno parcial sería un
número inventado. La coherencia se impone además como restricción de la base
(`ck_amef_rpn`).

### Criterios S/O/D

Se extraen como **dato versionado**, no como lógica compilada: si Ingeniería
cambia la escala, cambia el archivo, no el backend. Las filas que aparecen
antes de que se anuncie una dimensión no se importan y se avisa; la
dimensión no se adivina.

### Planos

Las imágenes embebidas se extraen leyendo el paquete OpenXML directamente,
sin pasar por ninguna librería de imágenes. Se conservan bytes, MIME,
SHA-256, hoja, anclaje y dimensiones cuando el formato las declara en su
cabecera.

**No hay OCR ni visión artificial en este bloque.** El plano es evidencia
que se conserva, no información que se interpreta.

La asociación a un número de plano sigue una regla única y conservadora: si
la hoja donde está anclada la imagen menciona **exactamente un** número de
plano de los declarados en el BOM, esa es la asociación. Con cero o con
varios, **no se elige**: la imagen se conserva y queda pendiente de revisión
(`drawing_association_pending`).

---

## 2. Snapshot de SAP (`.htm`)

`POST /api/v1/technical/{domain}/{asset}/sap-snapshots`

El archivo se trata como **dato, nunca como página**. No se renderiza en un
navegador, no se ejecuta JavaScript, no se interpreta CSS y no se descarga
ni un solo recurso de los que mencione. Se usa `html.parser` de la
biblioteca estándar, que es un analizador léxico puro: no tiene motor de
scripts ni cliente HTTP, así que no hay nada que deshabilitar.

- El contenido de `<script>` y `<style>` se descarta al leerlo y su
  presencia se reporta (`script_content_ignored`).
- Las direcciones externas que declare el archivo se cuentan y se reportan
  (`remote_references_ignored`). Ninguna se abre.
- La estructura se reconoce **semánticamente**, por los rótulos de columnas
  y campos, nunca por identificadores de fila del tipo `l0006002`: esos
  cambian entre exportaciones.
- Se extraen ubicación técnica, denominación, fecha «Válido de», materiales
  con cantidad y unidad, equipos hijos y el nivel jerárquico disponible.
- **Materiales y equipos se separan estructuralmente**
  (`sap_snapshot_items.entry_kind`). Mezclarlos inventaría una discrepancia
  en cada reconciliación.
- Se acepta UTF-8, UTF-16 y Windows-1252, con o sin `charset` declarado, y
  HTML sin etiquetas de cierre (los exportes de SAP los omiten a menudo).

Si no se reconoce ninguna tabla con confianza suficiente, la importación
**falla de forma segura**: no se publica nada, el original se conserva y el
administrador recibe una explicación. Publicar una interpretación dudosa
sería peor que no publicar nada.

---

## 3. Idempotencia

Antes de mirar el archivo se calcula su SHA-256. Si ese contenido exacto ya
se importó, se devuelve la importación original y **no se crea una versión
nueva**. La unicidad la impone la base (`unique (kind, sha256)`), no una
comprobación previa: dos peticiones simultáneas con el mismo archivo pasan
las dos por la comprobación y solo una sobrevive al registro.

Un snapshot de SAP distinto sí crea evidencia nueva, aunque sea del mismo
activo: es exactamente cómo se demuestra que una discrepancia cambió.

---

## 4. Errores

Una importación distingue el tipo de fallo, porque «el archivo que subiste
no es un XLSX» y «el disco no responde» exigen respuestas distintas:

| `failure_kind` | HTTP | Código |
|---|---|---|
| `file` | 422 | `invalid_source_file` |
| `parse` | 422 | `unreadable_source_file` |
| `ambiguity` | 409 | `ambiguous_source_data` |
| almacenamiento | 503 | `artifact_storage_unavailable` |
| base de datos | 503 | `knowledge_store_unavailable` |
| tamaño | 413 | `file_too_large` |
| duplicado | 200 | respuesta con `duplicate: true` |

Ningún error devuelve trazas internas ni contenido del archivo. Todos llevan
`request_id` para correlacionar con los logs.

Los logs registran **conteos y motivos**, nunca códigos SAP, nombres de
componente ni números de plano.
