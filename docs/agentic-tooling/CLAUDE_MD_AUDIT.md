# Auditoría de `CLAUDE.md`: antes y después

Trabajo realizado el 2026-09-09 en la rama `chore/elsa-agentic-tooling-v1`.
Este documento existe para demostrar dos cosas: **qué se midió** y **que no se
perdió ninguna regla crítica**.

## 1. Medición

| | Antes | Después | Δ |
|---|---:|---:|---:|
| Líneas de `CLAUDE.md` | 172 | 120 | **−52 (−30,2 %)** |
| Caracteres | 7 187 | 5 982 | **−1 205 (−16,8 %)** |
| Tokens estimados (≈3,6 c/token) | ~1 996 | ~1 662 | **−334 (−16,7 %)** |
| Reglas numeradas explícitas | 15 + prosa | 25 | **+10** |

La reducción de caracteres es menor que la de líneas porque el contrato
**ganó contenido**: cuatro reglas que antes solo se sostenían por costumbre
ahora están escritas (15, 16, 17, 18). El contrato es más corto *y* dice más.

### Contabilidad honesta del contexto

Lo que se paga en **cada** petición de **cada** sesión:

| Concepto | Antes | Después |
|---|---:|---:|
| `CLAUDE.md` | ~1 996 t | ~1 662 t |
| Descripciones de las 6 Skills | 0 | ~891 t |
| Descripciones de los 3 subagentes | 0 | ~393 t |
| **Total permanente** | **~1 996 t** | **~2 946 t** |

**El coste fijo sube unos 950 tokens.** Decirlo al revés sería falso. Lo que se
compra con esos 950 tokens:

| Concepto | Tokens | Cuándo entran al contexto |
|---|---:|---|
| Cuerpos de las 6 Skills | ~4 787 t | Solo la que aplica a la tarea (~700–1 035 t) |
| Cuerpos de los 3 subagentes | ~1 904 t | **Nunca** en la conversación principal |

El ahorro real no está en el arranque; está en tres sitios:

1. **Procedimiento que ya no se re-escribe.** Cada prompt que hoy explica cómo
   probar, cómo aplicar una migración o cómo aceptar la interfaz cuesta esos
   tokens *y* el riesgo de escribirlo distinto cada vez. Ahora se invoca.
2. **Documentación que ya no se re-lee entera.** Una Skill de ~800 tokens
   apunta al documento exacto en vez de obligar a leer `docs/` de 300 líneas
   por si acaso.
3. **Revisiones aisladas.** Una revisión de seguridad lee decenas de ficheros.
   En la conversación principal esos ficheros se quedan ocupando sitio el resto
   de la sesión; en un subagente vuelve solo un dictamen de ~400 tokens.

Y el efecto que no se mide en tokens: un contrato de 120 líneas con reglas
numeradas se cumple mejor que uno de 172 con reglas en prosa. La documentación
oficial de Claude Code recomienda mantenerlo por debajo de 200 líneas
justamente por esto.

## 2. Trazabilidad: dónde acabó cada regla

Ninguna regla se eliminó. Todas están en el contrato o en una Skill invocable.

| Regla original | Dónde está ahora |
|---|---|
| §1 Qué es ELSA, MVP Tampella, entrega a PAPELSA | §1 (íntegra) |
| §1 Lista de componentes previstos | `docs/architecture.md` §Visión general (diagrama) — era deducible del repositorio |
| §2.1 Navegador nunca habla con el LLM | Regla 1 |
| §2.2 FastAPI es la frontera | Regla 1 |
| §2.3 El LLM nunca decide permisos | Regla 2 |
| §2.4 Permisos antes de recuperar | Regla 3 |
| §2.5 Nunca hechos sin evidencia | Regla 2 |
| §2.6 Materiales dueño de su inventario | Regla 4 |
| §2.7 Supabase independiente | Regla 5 |
| §2.8 Identidad desde Supabase de Materiales | Regla 5 |
| §2.9 FastAPI valida y aplica permisos | Regla 5 |
| §2.10 Sin secretos en repositorio ni frontend | Regla 11 |
| §2.11 Migraciones versionadas | Regla 7 |
| §2.12 Puertos para LLM/embeddings/reranker/OCR | Regla 6 |
| §2.13 Ambientes DEV y TEST | Regla 8 |
| §2.14 Funciona con el LLM caído | Regla 9 |
| §2.15 Auditable / pentesting | Regla 10 |
| §3 Stack cerrado (tabla) | §4, en prosa compacta |
| §3 Stack abierto = nunca dependencia dura | §4 + regla 6 |
| §4 Migraciones: única autoridad, no Alembic, no dashboard | Regla 7 + `elsa-migrations` |
| §4 RLS no es el mecanismo de autorización | Regla 5 |
| §4 Verificación del JWT (JWKS / simétrico / puerto) | ADR 0005, citado desde regla 5 |
| §4 DEV y TEST son proyectos distintos | Regla 8 |
| §4 Idioma | §3 (íntegra) |
| §5 Puertos en `ports/`, adaptadores en `adapters/` | Regla 6 |
| §5 La lógica importa el puerto, no el adaptador | Regla 6 |
| §5 Cada puerto tiene un fake determinista | Regla 6 |
| §5 Adaptador real por configuración | Regla 6 |
| §5 Puerto sin adaptador real no es deuda técnica | Regla 6 |
| §6 `.env` ignorado, `.env.example` sin valores | Regla 11 |
| §6 Escaneo de secretos automático | Regla 11 + `elsa-testing` |
| §6 Nunca versionar SAP/PDF/planos/pesos/datasets/dumps | Regla 12 |
| §6 Debug prohibido fuera de DEV | Regla 13 |
| §6 CORS explícito, sin comodines | Regla 13 |
| §6 Formato de error estándar, sin trazas | Regla 14 |
| §6 Identificador de request en logs | Regla 14 |
| §7 Simplicidad, no construir por anticipación | Regla 23 |
| §7 Separación de responsabilidades sobre brevedad | Regla 23 |
| §7 Criterio de aceptación del clon limpio | Regla 24 |
| §7 ADR para toda decisión relevante | Regla 25 |
| §8.1 Reportar inconsistencias antes de codificar | Regla 19 + `elsa-block-planning` |
| §8.2 No avanzar de bloque sin autorización | Regla 20 |
| §8.3 No ampliar el alcance | Regla 20 + `elsa-block-planning` |
| §8.4 Ejecutar y reportar salida real | Regla 21 + `elsa-testing` |
| §8.5 Decir si algo es imposible, no improvisar | Regla 22 |
| Preámbulo: contradicción → detente y pregunta | Preámbulo (íntegro) |
| Decisiones cerradas no se reabren sin ADR | Regla 25 |

### Reglas **añadidas** (no existían en el contrato)

| Nueva regla | Origen |
|---|---|
| 15 — Ninguna migración a un remoto sin autorización explícita; Materiales nunca se toca | `docs/migration-runbook-bloque-2.md` §5, ahora elevado a contrato |
| 16 — Cargar no publica y aprobar no publica | `docs/demo-runbook.md`, `src/elsa/api/v1/contributions.py`, interfaz de revisión |
| 17 — GitHub es la fuente de verdad | Práctica del proyecto, no escrita |
| 18 — Commit + push por unidad coherente | Práctica del proyecto, no escrita |
| §5 — Tabla de Skills y subagentes | Nuevo mecanismo |

## 3. Referencias cruzadas corregidas

Al renumerar el contrato, tres punteros quedaban colgando. Se corrigieron:

| Fichero | Antes | Ahora |
|---|---|---|
| `docs/migration-runbook-bloque-2.md:100` | «regla 4 del contrato» | «regla 3 del contrato» |
| `src/elsa/ports/transcription.py:3` | «CLAUDE.md §5» | «CLAUDE.md, regla 6» |
| `web/js/screens/login.js:11` | «CLAUDE.md §4» | «CLAUDE.md, regla 5» |

Los dos últimos son **líneas de comentario**: cero cambios de comportamiento.
`ruff check`, `ruff format --check` y la suite completa lo confirman.

## 4. Lo que deliberadamente no se hizo

- **No se creó `.claude/rules/`.** Es un mecanismo oficial y encajaría con
  ELSA (reglas de migraciones que solo se cargan al tocar `supabase/**`), pero
  no estaba en el alcance de este trabajo y hoy no resuelve ningún problema
  observado. Queda propuesto en [`README.md`](README.md) §3, **condicionado a
  observar un problema real** de activación de Skills o de crecimiento del
  contrato. Añadirlo antes sería construir por anticipación (regla 23).
- **No se instaló ninguna herramienta externa.** Ver
  [`EXTERNAL_TOOLS_EVALUATION.md`](EXTERNAL_TOOLS_EVALUATION.md).
- **No se creó `.mcp.json`.** Ver [`MCP_POLICY.md`](MCP_POLICY.md).
