# ADR 0011 — El chunking lo decide la estructura, y es determinístico

- Estado: aceptado
- Bloque: 4.1

## Contexto

Un manual de mantenimiento hay que trocearlo para poder recuperar pasajes.
La forma habitual —cortar cada N caracteres, con solape fijo— es trivial de
implementar y destruye exactamente lo que hace útil al documento:

- Parte el paso 4 de un procedimiento en dos, y produce **dos instrucciones
  falsas** donde había una verdadera.
- Separa una advertencia del trabajo al que se refiere.
- Deja media tabla sin encabezado, que no es información sino ruido.

La recuperación devuelve entonces trozos que *parecen* respuestas. Es peor
que no devolver nada, porque nadie lo nota.

Hay además un requisito que no es estético: **reprocesar el mismo documento
tiene que dar el mismo resultado**. De eso dependen la idempotencia de la
ingesta, la comparación entre versiones y la posibilidad de comprobar que
nada cambió sin volver a validarlo todo.

## Decisión

### El corte lo decide la estructura; el tamaño solo cuando no basta

En este orden:

1. Una sección no se mezcla con otra.
2. Una tabla es una unidad: chunk propio, y si no cabe se parte **por filas**
   repitiendo el encabezado. Nunca a mitad de fila.
3. Una advertencia abre siempre un chunk, para no quedar huérfana al final
   de otro, y no se parte.
4. Un paso numerado no se parte. Si uno solo supera el techo se emite entero
   y se marca como sobredimensionado.
5. Un pie acompaña a su figura o a su tabla.
6. Dentro de esos límites se agrupa hasta `target_tokens`.
7. Solo una unidad que sola supere `max_tokens` se parte, por frases; y una
   frase que lo supere, por palabras enteras.

### Un avance de página no cierra un párrafo

`\f` marca frontera de **página**, no de párrafo. Tratarlo como una línea en
blanco parte en dos todo párrafo que cruce de página. El párrafo sigue entero
y registra las dos páginas como su procedencia.

### El solape solo donde el tamaño forzó el corte, y solo entre prosa

Un corte estructural ya marca una discontinuidad que el documento declara:
solapar ahí duplica texto en el índice sin añadir continuidad. Una lista o un
procedimiento se cortan por elemento, y un elemento ya es una unidad
completa. La regla vive también en el esquema
(`ck_chunk_overlap_only_on_size`).

### La dirección de un chunk es posicional

`structural_key` es `<sección>#<índice>`. Si alguien inserta un párrafo, los
chunks siguientes de esa sección cambian de dirección y vuelven a revisión.
Es conservador —marca como modificado algo que quizá no cambió— y esa es la
dirección correcta del error: dar por validado un dato que sí cambió sería
mucho peor.

### La estimación de tokens no es un tokenizador, y es configuración

`ceil(len(texto) / chars_per_token)`. No hay tokenizador: el modelo de
embeddings se decide en el Bloque 4.2, y atarse hoy a su vocabulario
obligaría a re-chunkear todo el corpus al cambiarlo. La aproximación es
grosera pero estable, no depende de ninguna descarga y da el mismo número en
cualquier máquina.

Los límites (`350 / 700 / 60 / 50`) son puntos de partida razonables, **no
calibrados contra documentos reales**, y por eso son configuración
(`ELSA_DOCUMENT_CHUNK_*`).

### Cada versión persiste la política con la que se chunkeó

Perfil, valores exactos, extractor y versión del extractor. Dos versiones
chunkeadas con límites distintos no son comparables, y sin ese registro nadie
podría saber si una diferencia viene del documento o de un cambio de
configuración.

### Determinismo, por construcción

Sin relojes, sin identificadores generados dentro del chunking, sin recorrer
diccionarios cuyo orden importe. `structure_sha256` resume política,
secciones y pares `(clave, hash)` en una sola huella comparable.

### La ruta de títulos es metadato, no contenido

No se antepone al texto del chunk: mezclarla cambiaría el hash del contenido
y haría imposible saber qué decía el documento exactamente. Anteponerla al
indexar, si el modelo lo necesita, es decisión del Bloque 4.2.

## Consecuencias

- Los chunks tienen tamaños desiguales. Es la consecuencia de respetar la
  estructura, y es aceptable.
- Un documento sin ninguna estructura (un volcado de texto corrido) cae
  entero en el camino de tamaño, con solape. Funciona, y el reporte lo hace
  visible.
- Cambiar los límites produce chunks distintos, y la huella lo declara. No
  hay forma de cambiarlos en silencio.
- Cambiar de extractor invalida la equivalencia entre versiones, y también
  queda registrado.

## Alternativas descartadas

**Cortar cada N caracteres con solape fijo.** El motivo de este ADR.

**Chunking semántico con un modelo.** Hoy no hay LLM configurado; y aunque lo
hubiera, un chunking que depende de un modelo deja de ser reproducible: el
mismo documento daría cortes distintos según la versión del modelo, y la
comparación entre versiones dejaría de significar nada.

**Un tokenizador real ahora (`tiktoken` o similar).** Ataría los límites al
vocabulario de un modelo que todavía no se ha elegido, y añadiría una
dependencia con descarga de datos a un módulo que debe ser puro.

**Clave de chunk por hash del contenido.** Sería estable frente a inserciones,
pero entonces cambiar el contenido cambiaría la identidad, y no habría forma
de decir «este chunk se modificó»: solo «desapareció uno y apareció otro».
