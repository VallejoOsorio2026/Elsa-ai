---
name: elsa-ingestion
description: Trabajo sobre el conocimiento que entra a ELSA - qué se chunkea y qué no, secciones, solape, determinismo, provenance, versionado, idempotencia y criterios de aceptación de una ingesta. Úsala al tocar src/elsa/ingestion/, src/elsa/documents/ o services/*ingestion*, al interpretar BOM de Ingeniería .xlsx o snapshots de SAP .htm, al decidir cómo trocear un manual o un plano, y al revisar si una ingesta es reproducible y trazable. NO la uses para el esquema SQL que la almacena (eso es elsa-migrations), para recuperación o reranking, ni para ejecutar la suite de pruebas (eso es elsa-testing).
---

# Ingesta de conocimiento en ELSA

## Documentación que manda

No dupliques estas fuentes: léelas.

| Tema | Documento |
|---|---|
| Fuentes estructuradas (BOM `.xlsx`, SAP `.htm`) | `docs/ingestion-contract.md` |
| Frontera estructurado / documental | `docs/knowledge-architecture.md` |
| Modelo documental | `docs/document-model.md` |
| Estrategia de chunking | `docs/document-chunking.md` |
| Aceptación de la ingesta | `docs/document-acceptance.md` |
| Versionado y reconciliación | ADR 0008, `docs/architecture.md` |

Los cuatro documentos del modelo documental llegan con el Bloque 4. Si no
existen en la rama en la que estás, **léelos con `git show <rama>:<ruta>`; no
copies su código ni sus commits a otra rama.**

## La separación que no se negocia

- **Conocimiento estructurado** (BOM, SAP, materiales) **no se chunkea**. Se
  consulta directamente por sus campos. Trocearlo destruye la relación entre
  componente, cantidad y unidad, que es justo el dato.
- **Conocimiento documental** (manuales, procedimientos, planos) **sí se
  chunkea**, por secciones, nunca cada N caracteres.

Cuando la frontera no esté clara, decide por cómo se va a *consultar*, no por
el formato del archivo.

## Reglas transversales

**Determinismo.** La misma entrada produce exactamente la misma salida:
mismos cortes, mismos identificadores, mismo orden. Sin timestamps, sin UUID
aleatorios, sin recorrer diccionarios sin orden. Es lo que permite comparar
dos versiones de un documento y lo que hace reproducible la prueba de
aceptación.

**Provenance.** Ningún fragmento entra sin poder decir de dónde salió:
archivo de origen, versión, sección y posición. Sin esto el LLM no puede citar
evidencia, y la regla 2 del contrato («nunca crea hechos sin evidencia
recuperada») deja de ser verificable.

**Versionado.** Cargar no publica. Una ingesta crea una versión pendiente de
validación; publicarla es una decisión posterior y explícita.

**Idempotencia.** Reprocesar la misma fuente no duplica conocimiento. Si el
contenido no cambió, no hay versión nueva.

**Rechazo temprano.** Un archivo se rechaza *antes* de leer su contenido
cuando ya se sabe que es inseguro o inservible (ver «Qué se rechaza, y antes
de leer una sola celda» en `docs/ingestion-contract.md`). Los avisos se
persisten: un dato dudoso se marca, no se inventa ni se descarta en silencio.

**Datos reales.** Los `.xlsx`, `.htm`, PDFs y planos de PAPELSA **nunca** se
versionan. Los tests usan las fixtures sintéticas de `tests/fixtures_*.py`.

## Criterios de aceptación de una ingesta

1. Los tests de ingesta pasan y la salida real está pegada en el reporte.
2. Ejecutar dos veces la misma entrada produce salidas idénticas byte a byte.
3. Cada fragmento resultante puede rastrearse hasta su origen.
4. Los avisos emitidos son explicables uno por uno.
5. Ningún archivo real quedó en el árbol de trabajo (`git status` limpio).
