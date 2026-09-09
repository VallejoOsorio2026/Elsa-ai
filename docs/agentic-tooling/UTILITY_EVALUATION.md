# Prueba de utilidad de la infraestructura

No queremos Skills decorativas. Este documento comprueba dos cosas sobre las
seis Skills y los tres subagentes: que **están bien formados** y que **cada uno
se activa en una tarea real y solo en ella**.

## 1. Validación estructural (ejecutada)

Con el validador oficial de Anthropic, `skill-creator/scripts/quick_validate.py`.
Es determinista, local, sin red y sin credenciales — la única herramienta
externa con veredicto NOW en la evaluación.

```
$ for s in .claude/skills/*/; do python3 .../quick_validate.py "$s"; done
=== .claude/skills/elsa-block-planning/   Skill is valid!
=== .claude/skills/elsa-ingestion/        Skill is valid!
=== .claude/skills/elsa-migrations/       Skill is valid!
=== .claude/skills/elsa-release/          Skill is valid!
=== .claude/skills/elsa-testing/          Skill is valid!
=== .claude/skills/elsa-ui-acceptance/    Skill is valid!
```

Comprobación propia adicional sobre Skills y subagentes: cabecera YAML válida,
`name` en minúsculas con guiones, `name` igual al nombre del directorio (Skills)
o del fichero (subagentes), `description` no vacía y por debajo del límite de
1 536 caracteres, y ausencia de campos inventados. Todas pasan.

Esa comprobación encontró un defecto real: la descripción de
`rag-quality-reviewer` contenía `prompts: esas decisiones`, y los dos puntos
seguidos de espacio rompen el análisis YAML de la cabecera. El subagente no
habría cargado. Corregido.

## 2. Las cinco tareas representativas

Para cada tarea: qué información necesita Claude, qué se activa, qué **no** debe
cargarse, y qué repetición desaparece respecto al `CLAUDE.md` anterior.

### Tarea 1 — Planear el subbloque 4.2

> «Vamos a arrancar el Bloque 4.2. Dime el alcance antes de tocar nada.»

| | |
|---|---|
| **Debe cargar** | Contrato (reglas 19, 20, 23, 25) · `elsa-block-planning` · `docs/adr/` · `docs/architecture.md` §«Qué no existe todavía» |
| **Se activa** | `elsa-block-planning` |
| **NO debe cargar** | `elsa-migrations`, `elsa-testing`, `elsa-ui-acceptance`, `elsa-release`; ningún subagente; nada de `src/` |
| **Repetición que desaparece** | La estructura de seis secciones (objetivo / dentro / fuera / decisiones / aceptación / riesgos) y la orden de reportar inconsistencias antes de codificar. Antes había que re-escribirla en cada prompt de apertura de bloque. |

### Tarea 2 — Revisar una migración antes de aplicarla

> «Revisa la migración pendiente y dime si se puede aplicar a TEST.»

| | |
|---|---|
| **Debe cargar** | Contrato (reglas 5, 7, 15) · `elsa-migrations` · el `.sql` en cuestión · `docs/migration-runbook-bloque-2.md` |
| **Se activa** | `elsa-migrations`; `security-reviewer` al cerrar |
| **NO debe cargar** | `elsa-ingestion`, `elsa-ui-acceptance`, `elsa-block-planning`; `web/`; el modelo documental |
| **Repetición que desaparece** | RLS activo con cero políticas, `security_invoker` en vistas, el par de rollback, y sobre todo la comprobación de **a qué proyecto apunta el enlace** antes de cualquier comando remoto. Era lo más repetido y lo más caro de olvidar. |

Esta es la tarea donde la infraestructura más aporta: la regla 15 está ahora en
el contrato (siempre cargada, coste ~15 tokens) y el procedimiento completo de
~1 035 tokens solo entra cuando se toca SQL.

### Tarea 3 — Diagnosticar un fallo de CI

> «El job de tests está en rojo y en mi máquina pasa.»

| | |
|---|---|
| **Debe cargar** | Contrato (regla 21) · `elsa-testing` · el log del job · `.github/workflows/ci.yml` |
| **Se activa** | `elsa-testing` |
| **NO debe cargar** | `elsa-block-planning`, `elsa-ingestion`, `elsa-ui-acceptance`; ningún subagente |
| **Repetición que desaparece** | El caso «en mi máquina pasa» casi siempre es `ELSA_TEST_DATABASE_URL` sin definir: los tests de esquema se **omiten en silencio**. `elsa-testing` lo dice y obliga a declarar los `skipped`. También la prohibición de ocultar el código de salida con un pipe, que convierte un fallo en falso verde. |

### Tarea 4 — Aceptación de la interfaz

> «¿La pantalla de revisión está lista para enseñarla?»

| | |
|---|---|
| **Debe cargar** | Contrato (regla 16) · `elsa-ui-acceptance` · `web/js/screens/review.js` · `docs/brand/ELSA_UI_BRAND_RULES.md` si hay duda de marca |
| **Se activa** | `elsa-ui-acceptance` |
| **NO debe cargar** | `elsa-migrations`, `elsa-ingestion`; `src/elsa/adapters/`; los 371 renglones de reglas de marca por defecto |
| **Repetición que desaparece** | Los seis anchos, el recorrido con Tab y Shift+Tab, la conservación del foco, el comportamiento del grabador y la comprobación de que la pantalla dice que **aprobar no es publicar**. Era la lista más larga de re-escribir a mano. |

### Tarea 5 — Preparar el cierre y el PR

> «Cierra esto: commit, push y déjame el PR listo.»

| | |
|---|---|
| **Debe cargar** | Contrato (reglas 17, 18, 25) · `elsa-release` · `elsa-testing` para la verificación previa · `git diff` completo |
| **Se activa** | `elsa-release`, más `elsa-testing`; `security-reviewer` y `architecture-reviewer` antes del PR |
| **NO debe cargar** | `elsa-block-planning`, `elsa-ingestion`, `elsa-ui-acceptance` |
| **Repetición que desaparece** | Conventional Commits, revisar el diff **entero** antes de commitear, `uv sync` si cambian dependencias, no abrir PR sin que lo pidan, no mezclar con checks en rojo. |

## 3. Colisiones de activación

Cada Skill declara explícitamente cuándo **no** usarla. Comprobación cruzada:

| Skill | Disparador propio | Frontera declarada |
|---|---|---|
| `elsa-block-planning` | Abrir o acotar un bloque | No ejecuta, no cierra |
| `elsa-migrations` | `supabase/**`, SQL, remoto | No SQL de aplicación, no modelo documental |
| `elsa-ingestion` | `ingestion/`, `documents/`, chunking | No el esquema que lo guarda, no la suite |
| `elsa-testing` | pytest, ruff, mypy, gitleaks, CI | No la lógica probada, no el runbook remoto |
| `elsa-ui-acceptance` | `web/`, demo | No diseño, no backend |
| `elsa-release` | commit, PR, CI, merge, Render | No decide qué sigue, no primera ejecución |

Los dos pares con riesgo real de solaparse están resueltos por exclusión mutua
explícita: `elsa-migrations` ↔ `elsa-ingestion` (esquema frente a contenido) y
`elsa-testing` ↔ `elsa-release` (verificar frente a publicar). En la tarea 5 se
activan dos a propósito, y es correcto: son fases distintas de la misma tarea.

## 4. Subagentes: cuándo sí y cuándo no

| Subagente | Se invoca | No se invoca |
|---|---|---|
| `architecture-reviewer` | Cambio en `ports/`, `adapters/`, `core/`, o cierre de bloque | Solo documentación, solo `web/`, solo tests |
| `security-reviewer` | Antes de un PR; auth, permisos, migraciones, configuración, ingesta de ficheros | Solo documentación; como sustituto de gitleaks, que ya es automático |
| `rag-quality-reviewer` | `core/retrieval.py`, `ingestion/`, `documents/`, camino de respuesta | Esquema, interfaz, tooling; y **nunca** para juzgar embeddings o reranking, que aún no están decididos |

Ninguno se dispara solo. Los tres son de solo lectura y devuelven un dictamen
corto: ese es el ahorro, porque el proceso de revisión (decenas de ficheros) no
contamina la conversación principal.

## 5. Lo que esta prueba **no** demuestra

- No se ejecutaron *evals* con `skill-creator` en modo Eval/Benchmark. Ese modo
  lanza subagentes ejecutores y calificadores contra prompts de prueba: cuesta
  varias sesiones completas y mide activación estadísticamente. Está justificado
  cuando haya dudas reales de disparo, no para estrenar seis Skills.
- No se ha medido el ahorro en sesiones reales. Los números de
  [`CLAUDE_MD_AUDIT.md`](CLAUDE_MD_AUDIT.md) son estimaciones a ≈3,6 caracteres
  por token, no telemetría.
- La utilidad real se verá en el primer bloque que se trabaje con esto puesto.
  Si una Skill no se activa sola cuando debía, se corrige su descripción — no se
  añade una Skill nueva.
