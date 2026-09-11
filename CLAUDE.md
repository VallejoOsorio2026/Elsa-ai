# CLAUDE.md — Contrato del proyecto ELSA

Fuente de verdad del proyecto. Aplica siempre, en todos los bloques, sin
repetirlo en cada prompt. Si una instrucción de sesión contradice este archivo,
**detente y pregunta**: no resuelvas la contradicción por tu cuenta.

Este archivo contiene **reglas**. Los procedimientos viven en las Skills de
`.claude/skills/` y en `docs/`. Ver `docs/agentic-tooling/README.md`.

## 1. Qué es ELSA

Asistente corporativo para los ingenieros de mantenimiento de la Planta Molino
Barbosa de PAPELSA. El MVP técnico se limita al equipo **Tampella**, pero la
arquitectura debe admitir después más equipos, plantas y dominios de
conocimiento.

**El proyecto será entregado a PAPELSA.** Otra persona debe poder entenderlo y
continuarlo sin acceso a las conversaciones que lo produjeron.

Visión completa y estado actual: `docs/architecture.md`.

## 2. Reglas innegociables

### Arquitectura

1. El navegador nunca se comunica directamente con el LLM. FastAPI es la
   frontera principal del backend.
2. El LLM nunca decide permisos, y nunca crea hechos sin evidencia recuperada.
3. Los permisos se aplican **antes** de recuperar conocimiento, nunca después.
4. Materiales sigue siendo propietario de su inventario. ELSA no duplica sus
   ~65.000 registros.
5. ELSA tiene un proyecto Supabase independiente. La identidad proviene de
   Supabase Auth del proyecto Materiales; FastAPI valida ese JWT y aplica los
   permisos propios de ELSA con credencial de servicio. **RLS no es el
   mecanismo de autorización de ELSA** (ADR 0002).
6. LLM, embeddings, reranker, OCR y materiales se consumen como `Protocol` en
   `src/elsa/ports/`. La lógica de negocio importa el puerto, nunca el
   adaptador; el adaptador real se elige por configuración. Cada puerto tiene
   un fake determinista para los tests. Un puerto sin adaptador real no es
   deuda técnica: es el diseño previsto (ADR 0003).
7. Toda estructura de base de datos es reproducible mediante migraciones
   versionadas en `supabase/migrations/`. Ni Alembic, ni migraciones de ORM,
   ni cambios a mano en el dashboard (ADR 0001).
8. Existen ambientes lógicos DEV y TEST, en proyectos Supabase distintos.
   Ningún ambiente comparte base de datos con otro.
9. El sistema funciona parcialmente cuando el LLM está fuera de servicio, y lo
   declara.
10. La arquitectura facilita auditoría de ciberseguridad y pentesting.

### Seguridad y datos

11. Ningún secreto en el repositorio ni en el frontend. `.env` está en
    `.gitignore`; `.env.example` lleva las claves sin valores. El escaneo de
    secretos es automático (pre-commit + CI), no una revisión manual.
12. **Los datos reales nunca entran a Git**: archivos SAP, PDFs de manuales,
    planos, pesos de modelos, datasets y dumps de base de datos.
13. Modo debug prohibido fuera de DEV. CORS declarado explícitamente por
    ambiente, sin comodines en TEST ni producción.
14. Los errores devueltos al cliente usan el formato estándar del proyecto y no
    filtran trazas internas. Cada request lleva un identificador propagado a
    los logs.
15. **Ninguna migración se aplica a un proyecto Supabase remoto sin
    autorización explícita** en esa misma conversación, y solo la migración
    prevista. El proyecto de Materiales nunca se toca desde este repositorio.
16. **Cargar no publica y aprobar no publica.** Un aporte queda pendiente;
    aprobar lo valida; publicar es una decisión posterior y explícita.

### Método de trabajo

17. GitHub es la fuente de verdad: lo que no está commiteado y empujado no
    existe.
18. Commit + push al cerrar cada unidad coherente de trabajo, no al final del
    bloque. Conventional Commits (`docs/contributing.md`).
19. Antes de escribir código, reporta las inconsistencias técnicas que detectes
    en las instrucciones recibidas. Si algo impide comenzar, pregunta.
20. No avances al bloque siguiente ni amplíes el alcance del actual sin
    autorización explícita, aunque el código quede «casi listo» para algo más.
21. **Nunca afirmes que algo funciona sin haberlo ejecutado.** Pega la salida
    real. No inventes resultados ni ocultes un fallo.
22. Si una tarea resulta imposible o desaconsejable, dilo y explica por qué en
    lugar de improvisar una alternativa.
23. Simplicidad sobre sofisticación; no se construye por anticipación.
    Separación de responsabilidades por encima de brevedad.
24. Criterio de aceptación permanente: un clon limpio, siguiendo únicamente el
    README, levanta el servidor y pasa los tests en una máquina sin contexto.
25. Toda decisión arquitectónica relevante se registra como ADR en
    `docs/adr/`. Las decisiones cerradas no se reabren sin un ADR nuevo.

## 3. Idioma

- **Español:** documentación, ADRs y comentarios de negocio.
- **Inglés:** nombres de código, ramas, mensajes de commit y logs.

## 4. Stack

**Cerrado.** Python 3.12 (`.python-version`) · FastAPI · `uv` con
`pyproject.toml` + `uv.lock` · PostgreSQL / Supabase + pgvector · Supabase CLI
para migraciones · Ruff (lint y formato) · mypy no estricto · pytest ·
GitHub Actions.

**Abierto**, y por tanto nunca dependencia dura de un módulo: proveedor de LLM,
servidor de modelos, OCR, embeddings, reranker, frontend y despliegue. Se
acceden siempre por un puerto (regla 6).

## 5. Skills del proyecto

Invoca la Skill en vez de reconstruir su procedimiento:

| Skill | Cuándo |
|---|---|
| `elsa-block-planning` | Delimitar un bloque: alcance, exclusiones, criterios de aceptación |
| `elsa-migrations` | Escribir, revisar o aplicar SQL de `supabase/` |
| `elsa-ingestion` | Chunking, provenance, versionado y aceptación de ingesta |
| `elsa-testing` | Ejecutar y reportar pruebas, ruff, mypy, gitleaks |
| `elsa-ui-acceptance` | Aceptación de la interfaz de `web/` |
| `elsa-release` | Commit, PR, CI, merge, Render y cierre de bloque |

Subagentes de revisión disponibles: `architecture-reviewer`,
`security-reviewer`, `rag-quality-reviewer`. Se invocan al cerrar un cambio,
no en cada tarea.
