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
cambia la escala, cambia el archivo, no el backend.

**Cada dimensión se lee por separado.** Primero se delimita su bloque —qué
filas y qué columnas le pertenecen— y después se recorre solo ese bloque, con
su propia columna de escala. Leer la hoja como un único recorrido lineal era
el origen de las pérdidas: el rótulo de una tabla cambiaba el estado con el
que se leían las demás.

Se admiten las dos disposiciones que la plantilla puede tener:

- **Apiladas**: cada tabla precedida de su rótulo; su bloque llega hasta que
  se anuncie la siguiente dimensión.
- **Una al lado de otra**: una misma fila anuncia varias dimensiones en
  columnas distintas y cada una gobierna su franja de columnas.

Las tres **no necesitan la misma geometría**: una puede tener una columna
auxiliar y otra no.

Las dimensiones se reconocen por un vocabulario amplio —«Severidad»,
«Gravedad», «Ocurrencia», «Frecuencia», «Probabilidad», «Detección», sus
equivalentes en inglés— y también por su inicial entre paréntesis, como
`Calificación (S)`.

El valor de la escala se lee de **la columna que la tabla declare** («Valor»,
«Nivel», «Calificación», «Índice»…). Solo si no declara ninguna se recurre al
primer entero entre 1 y 10 de la fila. La diferencia importa: las tablas de
ocurrencia suelen anteponer una tasa o un porcentaje, y ese primer número no
es la escala.

Esa columna se busca **solo entre las filas que no traen ningún valor de
escala**, es decir entre las de rótulos. Buscarla en cualquier fila hacía que
una descripción como «Rango muy bajo» o «Nivel medio» se tomara por un rótulo
de columna y se llevara por delante la fila de datos entera.

El parser importa **todas las filas válidas que encuentre**. El número de
niveles no es una regla suya: un archivo con tres tablas de diez niveles da
treinta criterios porque los tiene, no porque el parser espere treinta.

Avisos propios de la hoja:

| Código | Significado |
|---|---|
| `sod_dimension_unknown` | Filas anteriores a cualquier rótulo de dimensión |
| `sod_dimension_without_criteria` | La dimensión se anuncia pero no se pudo leer ningún valor |
| `sod_dimension_missing` | La hoja no produjo criterios para las tres dimensiones |
| `sod_rows_not_imported` | Filas del bloque con números que no dieron criterio |

Una dimensión anunciada que no produce criterios **avisa**. Quedarse callado
ahí era el defecto: la dimensión desaparecía sin que nadie lo notara.

### Planos

Las imágenes embebidas se extraen leyendo el paquete OpenXML directamente,
sin pasar por ninguna librería de imágenes. Se conservan bytes, MIME,
SHA-256, hoja, anclaje y dimensiones cuando el formato las declara en su
cabecera.

**No hay OCR ni visión artificial en este bloque.** El plano es evidencia
que se conserva, no información que se interpreta.

La asociación a un número de plano sigue una regla única y conservadora: si
la hoja donde está anclada la imagen menciona **exactamente un** número de
plano de los declarados en el BOM, esa es la asociación, y se registra la
regla que la produjo. Con cero o con varios, **no se elige**: la imagen se
conserva y queda pendiente de revisión.

Toda imagen sin asociación cierta genera `drawing_association_pending`, con
el número de imágenes afectadas. El aviso llega hasta el reporte de
aceptación, porque un plano que se extrae y del que nadie avisa es un plano
que nadie asocia.

---

## 2. Snapshot de SAP (`.htm`)

`POST /api/v1/technical/{domain}/{asset}/sap-snapshots`

### El export puede no tener tablas HTML

SAP produce estas listas de dos formas y ELSA admite las dos:

- **Como tabla HTML**, donde cada renglón es un `<tr>`.
- **Como lista monoespaciada**, sin un solo `<table>`: una sucesión de
  `<nobr>…</nobr><br>` en fuente de ancho fijo, donde las columnas se dibujan
  alineando espacios y el tipo de cada renglón lo indica un icono.

Se intenta primero la lectura como tabla; si no produce ningún renglón, el
documento se interpreta como líneas. Un parser que exigiera `<table>` no vería
absolutamente nada en la segunda forma, que es la que producen las
exportaciones de lista.

Un renglón **no es un fragmento HTML**. SAP reparte un solo registro en
varios `<nobr>` con iconos intercalados:

```html
<nobr>&nbsp;&nbsp;</nobr><img title="Material"><nobr>MAT-0001</nobr>
<nobr>&nbsp;&nbsp;Descripción</nobr><nobr>&nbsp;&nbsp;2</nobr><nobr>&nbsp;&nbsp;UN</nobr><br>
```

El parser modela primero **fragmentos** (texto o icono) y después los reúne
en un renglón lógico hasta la frontera. Tratar `</nobr>` como fin de renglón
parte cada registro en tantos trozos como columnas tenga, y ninguno se
reconoce.

- La frontera de renglón es **`<br>`**. Un export que no use `<br>` en
  absoluto se agrupa por `</nobr>`, que en ese caso sí delimita el renglón.
  La decisión se toma al final, con el documento ya leído.
- `&nbsp;` se convierte en espacio normal, porque cumple exactamente su
  función en estos exports.
- La **indentación se mide sobre el texto crudo**, antes de colapsar nada: es
  la única evidencia de nivel jerárquico cuando no hay columna de nivel.
- Los campos salen de los fragmentos: cada fragmento aporta uno, o varios si
  trae separación de columnas. Así se leen igual un renglón monolítico y uno
  repartido.

En la ruta de líneas:

- La fila de rótulos se distingue de una línea de metadatos por **cuántos de
  sus campos son nombres de columna**. Una cabecera es casi toda rótulos; una
  línea de metadatos alterna rótulo y valor. Sin esa distinción,
  `Ubic.técn. | MB-01 | Denominación | Molino` pasa por cabecera —porque
  «Denominación» es rótulo de campo y de columna a la vez— y desplaza la
  cabecera real a la zona de datos.
- Los renglones se cortan por campos separados por **dos o más espacios**, no
  por la posición de carácter de cada rótulo. El corte por posición parece
  más fiel a una lista de ancho fijo y se rompe entero, en silencio, en
  cuanto la cabecera y los datos no arrancan en la misma columna.
- El **identificador se extrae antes que la cantidad**. Un código de material
  es un número: buscar primero «el último campo numérico» se lo lleva por
  delante en cuanto la cantidad no es legible, y el renglón se pierde por no
  tener identificador. Un identificador debe contener al menos un dígito,
  para que una línea de totales no pase por renglón.
- El **tipo** se toma del `title` o el `alt` que declare el icono, y solo
  después del nombre del archivo de imagen: atarse a `s_b_matl.gif` dejaría de
  distinguir tipos en cuanto SAP renombrara sus iconos. Sin icono, decide la
  evidencia estructural: en una lista de BOM solo los materiales llevan
  cantidad y unidad.
- La **jerarquía** sale de una columna de nivel si existe, y si no del
  sangrado. Cada renglón guarda de qué objeto cuelga. Si el padre no puede
  identificarse, el renglón **se conserva igual** y se avisa: no se descarta
  un material válido por no poder probar su relación, ni se le inventa una.
- Lo que no se reconoce **se cuenta y se avisa** (`unrecognised_lines`,
  `incomplete_material_lines`, `contradictory_type_icons`,
  `unresolved_hierarchy`); no se rellena por conjetura.

### Diagnóstico estructural

El parser devuelve conteos por etapa, y la excepción los lleva también cuando
falla:

| Contador | Etapa |
|---|---|
| `nobr_fragments_seen` | Fragmentos leídos |
| `br_boundaries_seen` | Fronteras de renglón |
| `logical_lines_built` | Renglones reunidos |
| `html_tables_seen` | Tablas HTML, si las hubiera |
| `metadata_labels_detected` | Rótulos de cabecera reconocidos |
| `icon_material_signals` / `icon_equipment_signals` | Tipos declarados por iconos |
| `candidate_records` | Renglones con algo interpretable |
| `parsed_material_records` / `parsed_equipment_records` | Registros importados |
| `unresolved_records` | Renglones que no se pudieron interpretar |

Son **solo números**. Existen para poder diagnosticar en qué etapa se detuvo
el parseo de un archivo que no puede compartirse, sin ver una sola línea de
su contenido.

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

## 5. Avisos persistidos

Los avisos del parser se guardan en `imports.stats` como **códigos estables y
conteos** (`{"formula_not_evaluated": 3}`). Un revisor puede así ver, sin
volver a procesar el archivo, que hubo fórmulas sin evaluar o planos sin
asociar. Un código y un número no dicen nada de ninguna pieza, de modo que la
regla de no almacenar contenido técnico se mantiene intacta.
