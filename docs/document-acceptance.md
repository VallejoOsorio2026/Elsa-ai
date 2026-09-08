# Prueba de aceptación de la ingesta documental

Herramienta: `src/elsa/tools/document_acceptance.py`.

Ejecuta la ingesta completa —extracción, seccionado, chunking, validación,
comparación entre versiones y publicación— sobre un documento y escribe un
reporte con todo lo que hace falta para decidir si el bloque pasa.

```bash
uv run python -m elsa.tools.document_acceptance \
    --input  "ruta/manual-v1.md" \
    --second "ruta/manual-v2.md" \
    --out    "acceptance/documento.json" \
    --title  "Manual de lubricacion" \
    --asset-code equipo-ejemplo
```

Todo ocurre en adaptadores **en memoria**: no se toca ningún Supabase, ni
ningún almacenamiento persistente, y no se publica nada en ningún sitio real.

---

## Contrato de salida

| Código | Significa |
|---|---|
| **0** | Aceptado. El documento se procesó, la validación no encontró nada bloqueante y `errors` está vacío |
| **1** | Aceptación fallida. El reporte se escribe igualmente: es el material con el que se diagnostica |
| **2** | No se pudo ni intentar: falta el archivo de entrada, o el reporte no se puede escribir |

**No existe el éxito parcial.** Un reporte con `errors` nunca termina en 0,
para que no pueda confundirse con una aceptación aprobada.

Puede haber `warnings` y terminar en 0: un chunk sobredimensionado o una
tabla partida son cosas que una persona debe mirar, no fallos del proceso.

---

## Qué reporta

| Clave | Contenido |
|---|---|
| `input` | Nombre, tipo y tamaño del archivo |
| `policy` | Los límites exactos con los que se chunkeó |
| `extraction` | Motor, versión, páginas, bloques y bloques por clase |
| `sections` | Árbol completo: `path`, padre, profundidad, número impreso, título, páginas, cuántos chunks |
| `chunks` | Orden, clave estructural, sección, ruta de títulos, clase, páginas, desplazamientos, tokens, solape, motivo del corte, hash y avisos |
| `totals` | Secciones, chunks, tokens, sobredimensionados, con solape |
| `validation` | Si es válido, qué bloquea, conteo de hallazgos |
| `changes` | Clasificación frente a la versión publicada |
| `determinism` | Huellas de dos ejecuciones y si coinciden |
| `provenance` | Cuántos chunks reconstruyen su procedencia y llegan al texto fuente, con citas de muestra |
| `authorization` | Alcance requerido, y qué se ve con y sin permiso |
| `lifecycle` | Número de versión, estado y eventos registrados |
| `second_version` | Qué cambió en la v2 y qué versión sigue publicada |
| `warnings` | Códigos y conteos |
| `errors` | Lo que hace fallar la aceptación |

### Dos comprobaciones que no se ven mirando el resultado una vez

**Idempotencia** (`determinism`). Chunkea el documento dos veces y compara
las huellas. Dos resultados distintos significarían que el chunking depende
de algo que no está en el documento.

**Reconstrucción** (`provenance`). Verifica que los desplazamientos de cada
chunk apuntan a texto real del documento original y que su procedencia está
completa. Un chunk que no puede volver a su fuente no sirve como evidencia.

---

## El reporte no lleva el documento

**El texto de los chunks no se incluye por defecto.** Los títulos y la
metadata sí, porque sin ellos el reporte no sirve para aceptar nada; el
contenido no, porque un reporte de un manual interno filtrado por accidente
revelaría el manual entero.

`--include-text` lo añade de forma explícita, y el propio reporte lo declara
en `includes_document_text`.

---

## Documentos reales

Igual que la prueba de aceptación estructurada
([`private-acceptance-test.md`](private-acceptance-test.md)):

- **Los documentos no se copian al repositorio.** Se leen desde su ruta.
- La salida va a `acceptance/`, que está en `.gitignore`.
- Con documentos reales, **no** se usa `--include-text`.

En este bloque el extractor lee texto plano y Markdown. Un PDF se rechaza con
un aviso claro (`file`) en vez de adivinarse: no hay OCR ni motor de PDF
todavía.

---

## Opciones

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--input` | *(obligatoria)* | Documento a procesar |
| `--second` | — | Segunda versión, para comparar v1 contra v2 |
| `--out` | `acceptance/documento.json` | Ruta del reporte |
| `--title` | `Documento de aceptacion` | Título del documento en ELSA |
| `--domain` | `mantenimiento` | Dominio del alcance |
| `--asset-code` | — | Activo al que aplica. Sin él, aplica al dominio |
| `--source-kind` | `manual` | Clase de documento |
| `--target-tokens` … `--overlap-tokens` | Los de `ChunkingPolicy` | Límites del chunking |
| `--include-text` | apagado | Incluye el texto de cada chunk |

---

## Cobertura automática

`tests/test_document_acceptance.py` ejercita la herramienta contra los
documentos sintéticos de `tests/fixtures_documents.py`: documento correcto,
documento vacío, entrada inexistente, encabezados, listas, tablas, tabla
larga partida, contenido que cruza páginas, unidad indivisible demasiado
grande, v1 contra v2, segunda versión idéntica, idempotencia, reconstrucción
de procedencia, alcance de autorización y ausencia de texto en el reporte.

```bash
uv run pytest tests/test_document_acceptance.py -q
```

---

## Ver también

- [`document-chunking.md`](document-chunking.md) — qué decide cada corte
- [`document-model.md`](document-model.md) — qué garantiza el modelo
- [`private-acceptance-test.md`](private-acceptance-test.md) — la equivalente para fuentes estructuradas
