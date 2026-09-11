# ADR 0010 — Conocimiento estructurado y conocimiento documental son dos cosas distintas

- Estado: aceptado
- Bloque: 4.0

## Contexto

ELSA tiene que responder dos clases de pregunta que se parecen y no son lo
mismo:

- «¿Cuántos rodamientos lleva la posición 40 del conjunto X?» — tiene una
  respuesta **exacta**, que está en una fila del BOM aprobado por
  Ingeniería.
- «¿Cómo se ajusta el juego axial de ese conjunto?» — tiene una respuesta
  que es un **pasaje** de un manual.

La tentación al construir un RAG es convertirlo todo en texto y buscarlo por
parecido semántico, porque es un solo mecanismo y parece más simple. Sería el
error más caro de este bloque.

Si el BOM se troceara como texto:

- La exactitud pasaría a ser aproximación. La fila correcta y la de otro
  subsistema competirían por parecido, y quién gana lo decidiría un modelo.
- Las relaciones desaparecerían. Un componente que cuelga de un subsistema
  que cuelga de un activo es un grafo; convertido en frases, deja de poder
  recorrerse.
- El NPR (`S × O × D`), que el backend calcula de forma verificable, pasaría
  a depender de que un modelo lea bien tres números.
- Habría **dos copias** del mismo hecho. El Bloque 2 valida la suya con un
  Revisor Técnico; la copia textual no la validaría nadie, y envejecería.

## Decisión

**No todo se chunkea.** El conocimiento se separa en dos modelos con dos
tratamientos.

### Permanece estructurado y se consulta directamente

BOM, snapshots de SAP, AMEF y NPR, criterios S/O/D, códigos, cantidades,
unidades, relaciones y jerarquía, equipos y activos, estados, versiones,
reconciliación y planos como evidencia. Todo eso vive en el modelo del
Bloque 2 y se consulta con SQL, con filtros exactos.

### Se chunkea

Manuales, procedimientos, instructivos, documentación técnica narrativa y —en
fases posteriores— conocimiento narrativo de planta ya aprobado. Vive en el
modelo del Bloque 4.

### La frontera, cuando no está clara

En este orden:

1. ¿La respuesta correcta es un **valor** o un **pasaje**? Valor →
   estructurado. Pasaje → documental.
2. ¿Existe ya en el modelo estructurado? Entonces **no** entra como
   documento.
3. ¿Perder la estructura cambia el significado? Entonces se conserva como
   unidad dentro del documento, sin partirla.

Una tabla dentro de un manual **no se promueve** a conocimiento
estructurado. Interpretarla exigiría decidir qué columna es el código y cuál
la cantidad, y esa decisión ya la toma el BOM aprobado por Ingeniería. Se
conserva tal cual, como evidencia legible, y el chunking la trata como
unidad coherente.

### Los dos modelos comparten lo que ya existe

`knowledge_domains`, `technical_assets`, `source_artifacts` y —sobre todo— el
alcance `(dominio, equipo)` del Bloque 1. **No hay un segundo modelo de
permisos.** Un documento atado a un activo hereda su dominio, y la base lo
impone con una clave foránea compuesta.

## Consecuencias

- Responder una pregunta sobre cantidades no pasa nunca por el corpus
  documental, ni al revés.
- El Bloque 4.3 tendrá que combinar dos caminos de recuperación distintos,
  no uno. Es más trabajo, y es el trabajo correcto.
- Un hecho estructurado tiene una sola copia y un solo ciclo de validación.
- Añadir una clase de documento nueva es una fila en `ck_document_source_kind`;
  añadir una clase de dato estructurado sigue exigiendo una migración con su
  modelo, que es lo que debe costar.

## Alternativas descartadas

**Chunkear todo, incluido el BOM.** Un solo mecanismo, y respuestas
aproximadas a preguntas que tienen respuesta exacta. Descartada.

**Convertir los manuales en datos estructurados.** Exigiría inventar columnas
que el documento no tiene y perder la prosa, que es justamente la respuesta.
Descartada.

**Un único modelo genérico de «conocimiento» con un campo de tipo.** Suena
elegante y termina siendo dos modelos con la mitad de las columnas nulas en
cada fila, sin poder imponer restricciones a ninguno de los dos. Descartada.
