# Arquitectura de conocimiento: estructurado y documental

ELSA guarda dos clases de conocimiento que no se tratan igual, y la
diferencia entre las dos es la decisión central del Bloque 4.

**No todo se chunkea.** Trocear un BOM para buscarlo por parecido destruye la
única forma fiable de consultarlo: un código de material o una cantidad se
responden con una consulta exacta, no con un vecino más cercano. Y al revés,
guardar un manual como si fuera una tabla obliga a inventar columnas que el
documento no tiene.

---

## 1. La separación

### Conocimiento estructurado — se consulta directamente, **no se chunkea**

Vive en el modelo del Bloque 2 (`supabase/migrations/20260906010000_*.sql`)
y se consulta con SQL, con filtros exactos y con relaciones.

| Qué | Dónde |
|---|---|
| BOM de Ingeniería | `engineering_bom_items` |
| Snapshot de SAP | `sap_bom_snapshots`, `sap_snapshot_items` |
| AMEF y NPR | `failure_modes` |
| Criterios S/O/D | `sod_criteria` |
| Códigos e identidad de componente | `components`, `component_identifiers` |
| Cantidades y unidades | `engineering_bom_items`, `sap_snapshot_items` |
| Relaciones y jerarquía | `subsystems`, `sap_snapshot_items.parent_path` |
| Equipos y activos | `technical_assets` |
| Estados y versiones | `engineering_bom_versions.state` |
| Reconciliación entre fuentes | `reconciliation_runs`, `reconciliation_items` |
| Planos como evidencia | `drawings`, `drawing_images` |

Por qué no se chunkea:

- **La exactitud no admite aproximación.** «¿Cuántos rodamientos lleva la
  posición 40?» tiene una respuesta exacta en una fila. Recuperada por
  parecido semántico, la respuesta correcta y la de otro subsistema compiten
  entre sí, y la que gana la decide un modelo.
- **Las relaciones se pierden al aplanar.** Un componente que cuelga de un
  subsistema que cuelga de un activo es un grafo; convertido en frases, esa
  estructura desaparece y ya no se puede recorrer.
- **El NPR es `S × O × D` y lo calcula el backend.** Un número que sale de
  una multiplicación verificable no puede depender de que un modelo lo lea
  bien.
- **Ya está versionado y validado.** El Bloque 2 tiene su ciclo de
  publicación y su revisor técnico. Duplicarlo como texto crearía una segunda
  copia que envejece y que nadie valida.

### Conocimiento documental — **sí se chunkea**

Vive en el modelo del Bloque 4
(`supabase/migrations/20260908010000_*.sql`).

| Qué | `source_kind` |
|---|---|
| Manuales de fabricante y de planta | `manual` |
| Procedimientos | `procedure` |
| Instructivos | `instruction` |
| Documentación técnica narrativa | `technical_note` |
| Conocimiento narrativo de planta ya aprobado | `approved_narrative` |

Por qué sí se chunkea: son textos largos, sin estructura tabular, cuya
respuesta útil es un fragmento —un procedimiento, una advertencia, una
sección— y no un registro. La pregunta que responden («¿cómo se ajusta el
juego axial?») no tiene forma de consulta exacta.

### La frontera, cuando no está clara

Tres reglas, en orden:

1. **¿La respuesta correcta es un valor o un pasaje?** Un valor es
   estructurado; un pasaje es documental.
2. **¿Existe ya en el modelo estructurado?** Entonces no entra como
   documento. Dos copias de un mismo hecho terminan discrepando, y la
   documental es la que nadie valida.
3. **¿Perder la estructura cambia el significado?** Una tabla de tolerancias
   dentro de un manual sigue siendo documental —es parte de la prosa que la
   explica— pero se conserva **como unidad**, sin partirla por la mitad. Ver
   [`document-chunking.md`](document-chunking.md).

Una tabla dentro de un manual no se promueve a conocimiento estructurado.
Interpretarla exigiría decidir qué columna es el código y cuál la cantidad,
y esa decisión ya la toma el BOM aprobado por Ingeniería. Aquí la tabla se
conserva tal cual, como evidencia legible.

---

## 2. Cómo conviven

Los dos modelos comparten deliberadamente tres cosas y **no** un cuarto
modelo de permisos:

| Compartido | Por qué |
|---|---|
| `elsa.knowledge_domains` | El dominio es el mismo concepto en los dos |
| `elsa.technical_assets` | Un documento puede aplicar a un activo existente |
| `elsa.source_artifacts` | Un archivo original es un archivo original; la unicidad por hash es la misma garantía |
| El alcance `(dominio, equipo)` | Autorizar un documento es autorizar un alcance del Bloque 1 |

Un documento atado a un activo hereda su dominio, y la base lo impone con
una clave foránea compuesta: no puede existir un documento de
`mantenimiento` colgando de un activo de `materiales`. Un documento sin
activo aplica al dominio completo.

Lo que **no** comparten es el ciclo de validación. `elsa.reviews` valida
renglones del BOM y exige un activo técnico; una versión documental puede no
tener ninguno. Ver [ADR 0012](adr/0012-ciclo-de-vida-documental-propio.md).

---

## 3. Lo que este bloque deliberadamente no trae

| Fase | Qué traerá | Por qué no ahora |
|---|---|---|
| **4.2 Embeddings** | Modelo de embeddings, columna vectorial, pgvector, índice | La dimensión del vector depende del modelo; declararla ahora obligaría a migrar la tabla entera al elegirlo |
| **4.3 Recuperación híbrida** | Búsqueda léxica + vectorial, reranking | Sin embeddings no hay nada que combinar |
| **4.4 Orquestador** | Ensamblado de contexto, presupuesto de tokens, citas | Depende de qué devuelva la recuperación |
| **4.5 LLM** | Generación con evidencia recuperada | Depende del orquestador |
| **4.6 Evaluación** | Conjunto de preguntas, métricas, regresión | Necesita las cinco anteriores para medir algo |

Las tres reglas que este bloque deja preparadas para todas ellas:

1. **La autorización se aplica antes de recuperar.**
   `DocumentRepositoryPort.list_published_chunks` exige los alcances
   autorizados como argumento obligatorio. No existe una lectura masiva de
   chunks sin alcance, así que la fase 4.3 no *puede* escribirse recuperando
   primero y filtrando después.
2. **Solo se recupera lo publicado.** Una versión pendiente de validación o
   ya reemplazada no entra en ninguna recuperación.
3. **Todo chunk lleva su procedencia completa.** Sin ella no puede sostener
   una respuesta, y la regla 5 de `CLAUDE.md` —el LLM nunca crea hechos sin
   evidencia recuperada— no sería comprobable.

---

## Ver también

- [`document-model.md`](document-model.md) — contrato de documento, versión y chunk
- [`document-chunking.md`](document-chunking.md) — estrategia de chunking
- [`document-acceptance.md`](document-acceptance.md) — prueba de aceptación
- [ADR 0010](adr/0010-conocimiento-estructurado-vs-documental.md) — esta separación
- [ADR 0011](adr/0011-chunking-estructural-deterministico.md) — el chunking
- [ADR 0012](adr/0012-ciclo-de-vida-documental-propio.md) — el ciclo de vida
