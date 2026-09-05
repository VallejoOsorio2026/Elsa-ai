# ADR 0003 — Puertos y adaptadores para modelos reemplazables

## Estado

Aceptado (2026-09-04).

## Contexto

Varias decisiones de modelos siguen abiertas a propósito: proveedor de LLM
local/autohospedado, OCR (Docling vs PaddleOCR), embeddings (EmbeddingGemma
vs BGE-M3), reranker (candidato BGE). Acoplar la lógica de negocio a
cualquiera de ellos convertiría cada evaluación de alternativas en una
reescritura. Además, los tests no pueden depender de servicios externos ni de
modelos pesados.

## Decisión

Toda dependencia externa reemplazable se define como un `Protocol` en
`src/elsa/ports/` y se implementa en `src/elsa/adapters/`:

- Puertos: `auth`, `llm`, `embeddings`, `ocr`, `reranker`, `materials`.
- La lógica de negocio importa el puerto, nunca el adaptador.
- El adaptador real se selecciona por configuración, no por import directo.
- Cada puerto tiene al menos un adaptador *fake* determinista, usado por los
  tests de contrato (`tests/test_contract_*.py`).
- Un puerto sin adaptador real todavía no es deuda técnica: es el diseño
  previsto.

## Consecuencias

- Cambiar de modelo (u ofrecer varios) se reduce a escribir un adaptador y
  seleccionarlo por configuración; el negocio no se toca.
- La suite corre completa, rápida y determinista sin ningún servicio externo,
  también en CI.
- Los tests de contrato fijan la semántica de cada puerto (tipos, errores,
  determinismo); un adaptador real deberá pasar los mismos contratos.
- El precio es mantener una capa de indirección y tipos propios por puerto;
  se acepta a cambio de la reemplazabilidad exigida por CLAUDE.md (regla 12).
