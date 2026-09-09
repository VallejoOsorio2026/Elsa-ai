---
name: elsa-release
description: Cerrar una unidad de trabajo o un bloque de ELSA - mensaje de commit, push, revisión del diff completo, apertura de pull request, verificación de CI en verde, merge controlado, despliegue en Render y registro del ADR correspondiente. Úsala cuando el trabajo esté terminado y verificado, al preparar un PR, al diagnosticar CI en rojo sobre un PR propio, o al cerrar un bloque. NO la uses para decidir qué hacer a continuación (eso es elsa-block-planning), ni para ejecutar las pruebas por primera vez (eso es elsa-testing).
---

# Cierre y publicación en ELSA

GitHub es la fuente de verdad: **lo que no está commiteado y empujado no
existe.** Commit + push al cerrar cada unidad coherente, no al final del bloque.

## Antes de commitear

1. Verificaciones proporcionales al cambio, en verde y con salida real
   (`elsa-testing`).
2. `git status` limpio de basura: sin archivos reales de PAPELSA, sin `.env`,
   sin dumps, sin pesos de modelos, sin datasets.
3. `git diff` **completo**, leído. No commitees un diff que no has mirado
   entero: ahí es donde aparecen los secretos, los `print` olvidados y el
   código de otro bloque que se coló.
4. `uv run pre-commit run --all-files` — formato, lint y gitleaks.
5. Si cambiaron dependencias: `uv sync` y versiona el `uv.lock` resultante.
   CI usa `uv sync --locked` y falla si está desfasado.

## Mensaje de commit

Conventional Commits, en inglés, imperativo, sin punto final. Tipos y ejemplos:
`docs/contributing.md`. El cuerpo explica el **porqué**; el diff ya muestra el qué.

Una unidad coherente = un commit. No mezcles un `feat` con un `chore` de
tooling.

## Push

```bash
git push -u origin <rama>
```

Solo a la rama designada para el trabajo en curso. Nunca a `main` directamente,
y nunca a la rama de otro bloque.

## Pull request

- **No abras un PR si no te lo han pedido explícitamente.**
- Cuerpo en español: qué cambia, por qué, qué se verificó (con la salida) y qué
  queda fuera del alcance a propósito.
- Enlaza el ADR si la decisión es arquitectónica. Un cambio arquitectónico sin
  ADR en el mismo PR está incompleto.

## CI

`.github/workflows/ci.yml` corre lint, formato, mypy, tests contra PostgreSQL
efímero y gitleaks sobre la historia completa.

En rojo: lee el log del job que falla y arregla la causa. Nunca desactives un
test, nunca reintentes esperando que cambie, nunca empujes un commit vacío para
volver a disparar CI. Un test rojo es un defecto hasta que se demuestre lo
contrario.

## Merge

- No se mezcla con checks en rojo.
- **No hagas merge sin autorización explícita.**
- Después del merge, la rama del bloque no se reutiliza para trabajo nuevo:
  se parte de `main` otra vez.

## Render

El despliegue de la demostración se define en `render.yaml` y sale de `main`.
Procedimiento, límites del plan gratuito y lo que la demo **no** demuestra:
`docs/demo-runbook.md`. No cambies configuración de Render como efecto
colateral de otro trabajo.

## Cierre de bloque

Reporta: rama y HEAD, commits, qué se verificó con qué salida, ADRs añadidos,
qué quedó explícitamente fuera y qué hace falta autorizar para el bloque
siguiente. No declares cerrado un bloque cuyo criterio de aceptación no
ejecutaste.
