# Estrategia de chunking

Cómo un documento se convierte en secciones y chunks, por qué se corta donde
se corta, y qué garantiza que dos ejecuciones den exactamente el mismo
resultado.

Implementación: `src/elsa/documents/chunking.py`.

---

## 1. Por qué no se corta cada N caracteres

Es trivial de implementar y destruye lo que hace útil a un manual de
mantenimiento:

- Parte el paso 4 de un procedimiento en dos, y produce dos instrucciones
  falsas donde había una verdadera.
- Separa una advertencia del trabajo al que se refiere.
- Deja media tabla sin encabezado, y una tabla sin sus rótulos no es
  información sino ruido.

La recuperación devuelve entonces trozos que **parecen** respuestas. Es peor
que no devolver nada, porque nadie lo nota.

Aquí el corte lo decide la estructura del documento, y el tamaño solo
interviene cuando la estructura no basta.

---

## 2. Las reglas, en el orden en que mandan

1. **Una sección no se mezcla con otra.** El cambio de título es siempre un
   corte.
2. **Una tabla es una unidad.** Ocupa su propio chunk y no se mezcla con
   prosa. Si no cabe, se parte **por filas** —nunca a mitad de fila— y el
   encabezado se repite en cada trozo.
3. **Una advertencia no se parte ni se queda huérfana.** Abre siempre un
   chunk, de modo que viaja con el texto al que precede y nunca cierra uno
   como último renglón suelto.
4. **Un paso numerado no se parte.** El orden y el número son parte del
   significado. Si un solo paso supera el techo, se emite entero y se marca
   como sobredimensionado: partirlo sería inventar instrucciones.
5. **Un pie acompaña a su figura o a su tabla.** Se queda con el bloque
   anterior mientras quepa.
6. Dentro de esos límites se agrupa hasta `target_tokens`.
7. Solo si una unidad **sola** supera `max_tokens` se parte por frases; y si
   una frase sola lo supera, por palabras enteras, nunca a mitad de palabra
   (un código de material partido en dos deja de ser buscable).
8. Un chunk por debajo de `min_tokens` se fusiona con el anterior de su
   misma sección, salvo que la separación sea estructural (tabla,
   advertencia, sobredimensionado).

## 3. Qué reconoce el extractor

| Marca | Se lee como |
|---|---|
| `#` … `######` | Título, con su profundidad y su numeración impresa |
| `\f` (avance de página) | **Frontera de página, no de párrafo** |
| `- `, `* `, `• ` | Elemento de lista |
| `1. `, `2) `, `3.- ` | Paso numerado |
| `> …`, o una línea que empieza por `ADVERTENCIA`, `PELIGRO`, `PRECAUCIÓN`… | Advertencia |
| `\| a \| b \|` | Fila de tabla; `\|---\|` marca el encabezado |
| `Figura 3`, `Tabla 2`… | Pie |
| Línea realmente vacía | Fin de bloque |

El avance de página merece explicación. En el texto que produce cualquier
extractor de PDF, `\f` marca dónde termina una página. Tratarlo como una
línea en blanco parte en dos todo párrafo que cruce de página, y entonces la
mitad de una frase queda en un chunk y la otra mitad en otro. Aquí un `\f`
**avanza la página y no cierra nada**: el párrafo sigue entero y registra las
dos páginas como su procedencia.

Una tabla sin fila separadora **no supone encabezado**. Suponerlo haría que,
al partir una tabla larga, se repitiera una fila de datos haciéndola pasar
por rótulos en cada trozo. Se avisa (`table_without_header_marker`) en su
lugar.

---

## 4. El solape

`overlap_tokens` se aplica **solo cuando el corte lo provocó el tamaño**, y
solo entre prosa.

- Un corte **estructural** —cambia de sección, empieza una tabla, aparece una
  advertencia— ya marca una discontinuidad real que el documento declara.
  Solapar ahí duplicaría texto en el índice sin añadir continuidad.
- Un corte **por tamaño** parte una idea a la mitad. Ahí el solape sí evita
  perder el hilo.
- Una lista o un procedimiento se cortan por elemento, y un elemento ya es
  una unidad completa: repetirlo solo lo duplicaría.

El solape son **frases completas** de la cola del chunk anterior, hasta el
presupuesto; si ninguna cabe, palabras enteras. La regla vive también en el
esquema: `ck_chunk_overlap_only_on_size` impide que un chunk con
`boundary_reason = 'structure'` declare solape.

---

## 5. Los límites, y por qué son configuración

| Parámetro | Por defecto | Qué hace |
|---|---|---|
| `target_tokens` | 350 | Tamaño al que se apunta; un chunk se cierra al superarlo |
| `max_tokens` | 700 | Techo duro; por encima la prosa se parte por frases |
| `min_tokens` | 60 | Por debajo, se fusiona con el anterior de su sección |
| `overlap_tokens` | 50 | Solape, solo en cortes por tamaño; `0` lo desactiva |
| `chars_per_token` | 4 | Divisor de la estimación |

Se ajustan con `ELSA_DOCUMENT_CHUNK_*` (ver
[`environment-variables.md`](environment-variables.md)).

**Por qué esos valores.** 350 tokens es del orden de una sección corta o dos
párrafos técnicos: suficiente para que el pasaje se entienda solo y bastante
por debajo de la ventana de cualquier modelo de embeddings candidato. 700
deja margen para una tabla o un procedimiento largo sin partirlos. 60 es el
umbral por debajo del cual un fragmento no aporta contexto para responder
nada y sí ensucia la recuperación. 50 de solape es alrededor del 15 % del
objetivo: recupera el hilo sin duplicar medio corpus.

**Ninguno está calibrado contra documentos reales todavía**, porque los
documentos reales no están en el repositorio y el modelo de embeddings no
está decidido. Son puntos de partida razonables, y por eso son
configuración.

### La estimación de tokens no es un tokenizador

No hay ninguno: el modelo de embeddings se decide en el Bloque 4.2, y atarse
hoy al vocabulario de un modelo concreto obligaría a re-chunkear todo el
corpus al cambiarlo.

La aproximación por caracteres (`ceil(len(texto) / chars_per_token)`) es
grosera pero tiene la propiedad que aquí hace falta: es estable, no depende
de ninguna descarga y produce el mismo número en cualquier máquina. Ajustarla
al tokenizador real cuando exista es cambiar un número en la configuración,
no reescribir el chunker.

Cada versión persiste el perfil y los valores exactos con los que se
chunkeó, de modo que siempre se puede saber qué produjo qué.

---

## 6. Determinismo

La misma entrada y la misma política producen los mismos chunks, con los
mismos hashes, en cualquier máquina:

- No se consultan relojes.
- No se generan identificadores dentro del chunking.
- No se recorre ningún diccionario cuyo orden importe.
- El texto se normaliza antes de hashearlo (`normalize_text`): se colapsan
  espacios dentro de cada línea, **conservando los saltos**, porque en una
  tabla el salto separa filas.

`DocumentStructure.structure_sha256` resume toda la estructura —política,
secciones y pares `(clave, hash)`— en una sola huella. Dos ejecuciones que
den la misma huella produjeron exactamente lo mismo. Es lo que hace
comprobable la idempotencia sin comparar objeto por objeto, y lo que permite
que reingerir un archivo idéntico no cree una versión.

---

## 7. Ejemplo completo

Documento sintético de `tests/fixtures_documents.py`, con límites pequeños
(`target 60`, `max 120`, `min 10`, `overlap 10`) para que los cortes se vean
en un documento legible.

### Entrada

```markdown
# Manual de ejemplo del equipo de laboratorio

Este documento es sintético y existe para probar la ingesta. No describe
ningun equipo real.

## 1. Alcance
...
## 2. Seguridad

ADVERTENCIA: bloquear y etiquetar la fuente de energia antes de abrir
cualquier tapa. La omision de este paso puede causar lesiones graves.

- Usar guantes de proteccion.
- Verificar ausencia de tension.
- Despresurizar el circuito auxiliar.

## 3. Procedimiento de revision
### 3.1 Desmontaje

1. Retirar los cuatro tornillos de la tapa superior.
2. Extraer el conjunto de ejemplo sin forzar los apoyos.
3. Marcar la orientacion antes de separar las mitades.

### 3.2 Inspeccion
...
| Componente | Medida nominal | Tolerancia |
|---|---|---|
| Eje de ejemplo | 40 mm | 0,05 mm |
...
Tabla 1. Medidas de referencia del conjunto de ejemplo.

## 4. Registro
...
```

### Secciones detectadas

| `path` | Profundidad | Nº impreso | Título | Chunks |
|---|---|---|---|---|
| `1` | 1 | — | Manual de ejemplo del equipo de laboratorio | 1 |
| `1.1` | 2 | 1 | Alcance | 1 |
| `1.2` | 2 | 2 | Seguridad | 2 |
| `1.3` | 2 | 3 | Procedimiento de revision | 0 |
| `1.3.1` | 3 | 3.1 | Desmontaje | 1 |
| `1.3.2` | 3 | 3.2 | Inspeccion | 2 |
| `1.4` | 2 | 4 | Registro | 1 |

`1.3` no tiene chunks propios: solo contiene subsecciones, y su contenido
pertenece a ellas. Si el contenido de los hijos colgara también del padre, el
mismo texto se chunkearía dos veces y la recuperación devolvería duplicados.

`path` es posicional: el título sin numerar es `1` y `3.2 Inspeccion` es
`1.3.2`. La numeración impresa se conserva aparte.

### Chunks producidos

| Clave | Clase | Tokens | Página | Ruta de títulos | Hash |
|---|---|---|---|---|---|
| `1#0000` | prose | 23 | 1 | Manual… | `f2601443f2f2…` |
| `1.1#0000` | prose | 32 | 1 | Manual… › Alcance | `ebefc1ca7555…` |
| `1.2#0000` | mixed | 51 | 1 | Manual… › Seguridad | `7019c24434ba…` |
| `1.2#0001` | list | 10 | 1 | Manual… › Seguridad | `bcc236c76380…` |
| `1.3.1#0000` | steps | 41 | 1 | Manual… › Procedimiento… › Desmontaje | `a4c61b5bbde3…` |
| `1.3.2#0000` | prose | 27 | 1 | Manual… › Procedimiento… › Inspeccion | `a5bdaa140f42…` |
| `1.3.2#0001` | mixed | 50 | 1 | Manual… › Procedimiento… › Inspeccion | `3d3ae127ea02…` |
| `1.4#0000` | prose | 18 | 1 | Manual… › Registro | `6e377817966d…` |

### Los cortes, uno a uno

**`1.2#0000`** — la advertencia abre el chunk, y arrastra consigo los dos
primeros elementos de la lista de seguridad hasta llegar al objetivo:

```
ADVERTENCIA: bloquear y etiquetar la fuente de energia antes de abrir
cualquier tapa. La omision de este paso puede causar lesiones graves.
- Usar guantes de proteccion.
- Verificar ausencia de tension.
```

**`1.2#0001`** — el tercer elemento no cabía. Corte por tamaño, pero **sin
solape**: es una lista, y un elemento ya es una unidad completa.

```
- Despresurizar el circuito auxiliar.
```

**`1.3.1#0000`** — los tres pasos, enteros y con su número. Ningún paso se
parte, y la numeración sobrevive al chunking:

```
1. Retirar los cuatro tornillos de la tapa superior.
2. Extraer el conjunto de ejemplo sin forzar los apoyos.
3. Marcar la orientacion antes de separar las mitades.
```

**`1.3.2#0001`** — la tabla, entera y con su pie. El párrafo que la precede
quedó en `1.3.2#0000`: una tabla no se mezcla con prosa, pero su pie sí es
parte de ella.

```
Componente | Medida nominal | Tolerancia
Eje de ejemplo | 40 mm | 0,05 mm
Buje de ejemplo | 42 mm | 0,10 mm
Tapa de ejemplo | 12 mm | 0,20 mm
Tabla 1. Medidas de referencia del conjunto de ejemplo.
```

### Versión 1 contra versión 2

La versión 2 del mismo manual cambia una tolerancia en `3.2` y añade un paso
en `3.1`. La comparación da:

```
unchanged: 6    modified: 2    new: 0    retired: 0
```

Las seis secciones que nadie tocó conservan su clasificación y su validación
puede heredarse. Las dos que cambiaron vuelven a revisión. Y la versión
publicada **sigue siendo la 1**: la 2 entra como `pending_validation`.

---

## 8. Avisos

Códigos estables, que se persisten como conteos en `stats` y llegan al
reporte de aceptación. Un código y un número no dicen nada del documento.

| Código | Significa | ¿Bloquea? |
|---|---|---|
| `empty_document` | El documento no produjo ningún bloque legible | Sí |
| `no_chunks` | No salió ningún chunk | Sí |
| `chunk_oversized` | Un chunk supera el techo y no se pudo partir más | No |
| `indivisible_unit_too_large` | Un paso o una advertencia no cabe en un chunk | No |
| `table_split` | Una tabla se partió por filas | No |
| `table_without_header_marker` | La tabla no declara encabezado | No |
| `heading_level_skipped` | La profundidad de títulos salta un nivel | No |
| `section_without_content` | Un título abre una sección sin contenido propio | No |
| `content_before_first_heading` | El documento abre con texto antes de cualquier título | No |

Un aviso no bloquea. Un manual con una tabla partida o con un salto de nivel
sigue siendo un manual útil, y rechazarlo obligaría a «arreglar» el PDF que
Ingeniería aprobó.

---

## 9. Lo que no hace este bloque

- **No hay OCR.** Un documento escaneado no se interpreta: se rechaza con un
  aviso claro. Inventar texto que nadie leyó sería la peor forma posible de
  romper la regla 5 de `CLAUDE.md`.
- **No hay PDF.** El puerto `document_extraction` está listo para que el
  adaptador entre sin tocar el chunking; el de este bloque lee texto plano y
  Markdown, que es con lo que se demuestra la aceptación.
- **No hay embeddings ni recuperación.** Ver
  [`knowledge-architecture.md`](knowledge-architecture.md) §3.

---

## Ver también

- [`document-model.md`](document-model.md) — contrato de documento, versión y chunk
- [`document-acceptance.md`](document-acceptance.md) — cómo comprobarlo
- [ADR 0011](adr/0011-chunking-estructural-deterministico.md)
