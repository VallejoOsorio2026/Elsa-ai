---
name: elsa-block-planning
description: Delimita un bloque o subbloque de trabajo de ELSA antes de escribir código - alcance, exclusiones explícitas, decisiones abiertas, criterios de aceptación y qué ADR hace falta. Úsala cuando el usuario abra un bloque nuevo ("Bloque 4.2", "vamos a hacer X"), pida planear o acotar trabajo, pida el plan antes de implementar, o cuando una instrucción recibida sea ambigua o contradiga CLAUDE.md. NO la uses para ejecutar trabajo ya acotado, para revisar código escrito, ni para cerrar un bloque (eso es elsa-release).
---

# Planeación de un bloque de ELSA

El proyecto avanza por bloques. Un bloque mal delimitado es la causa más cara de
retrabajo: se amplía el alcance, se toca código de otro bloque y se pierde la
trazabilidad de por qué se hizo algo.

## Antes de proponer nada

1. Lee `CLAUDE.md`. Contradicciones con el contrato **se preguntan, no se resuelven**.
2. Revisa `docs/adr/` para no reabrir una decisión cerrada.
3. Revisa `docs/architecture.md` sección «Qué no existe todavía (a propósito)»:
   lo que está ahí es diseño, no deuda.
4. Comprueba en qué rama estás y qué ramas de bloques anteriores siguen abiertas
   (`git branch -a`). No mezcles trabajo de dos bloques en una rama.

## Reporta primero las inconsistencias

Regla 19 del contrato. Antes de la primera línea de código, enumera:

- instrucciones que se contradicen entre sí o contra `CLAUDE.md`;
- supuestos que no puedes verificar en el repositorio;
- lo que la instrucción da por existente y no existe.

Si algo impide comenzar, **pregunta y detente**. No improvises una alternativa.

## Estructura de la propuesta

Entrega siempre estas seis secciones, en español y en este orden:

1. **Objetivo del bloque** — una frase. Qué capacidad queda disponible al final.
2. **Dentro del alcance** — lista cerrada de entregables verificables.
3. **Fuera del alcance** — lista explícita. Aquí va todo lo que quede «casi
   listo» pero pertenezca a otro bloque. Sin esta lista el bloque se desborda.
4. **Decisiones que hay que tomar** — cada una con opciones y una recomendación.
   Marca cuáles exigen ADR nuevo en `docs/adr/NNNN-titulo-corto.md`.
5. **Criterios de aceptación** — verificables y ejecutables, no opiniones.
   Formato: «comando o acción → resultado observable esperado».
6. **Riesgos** — con la mitigación concreta, no genérica.

## Reglas de corte

- Un bloque cabe en una rama y en una unidad de revisión. Si el alcance no cabe,
  propón subbloques numerados (4.1, 4.2) en vez de agrandar el actual.
- Si un entregable necesita datos reales (SAP, planos, manuales), el bloque los
  consume desde fuera del repositorio; nunca los versiona.
- Si un entregable depende de una pieza abierta del stack (LLM, OCR, embeddings,
  reranker), el bloque entrega el **puerto** y un adaptador fake, no el proveedor.
- No propongas trabajo por anticipación: si nadie lo necesita en este bloque,
  va a «Fuera del alcance».

## Al terminar la planeación

No empieces a implementar. Espera autorización explícita (regla 20).
