# Guía de contribución

## Idioma

Según el contrato del proyecto (CLAUDE.md, sección 4):

- **Español:** documentación, ADRs y comentarios de negocio.
- **Inglés:** nombres de código, ramas, mensajes de commit y logs.

## Convención de commits: Conventional Commits

Formato del mensaje (en inglés):

```
<tipo>(<ámbito opcional>): <resumen en imperativo, minúsculas, sin punto final>

<cuerpo opcional: el porqué del cambio>
```

Tipos permitidos:

| Tipo | Uso |
|---|---|
| `feat` | Nueva funcionalidad visible para el sistema |
| `fix` | Corrección de un defecto |
| `docs` | Solo documentación |
| `test` | Solo tests |
| `refactor` | Cambio de código sin cambio de comportamiento |
| `chore` | Mantenimiento: dependencias, configuración, tooling |
| `ci` | Cambios en la integración continua |

Ejemplos:

```
feat(health): add per-dependency readiness reporting
fix(config): reject wildcard CORS origins
docs: document migration naming convention
chore: update ruff to 0.16
```

Un cambio incompatible se marca con `!` (`feat!: ...`) y se explica en el
cuerpo. Los mensajes describen el **porqué**; el diff ya muestra el qué.

## Flujo de trabajo

1. Rama por cambio, desde `main` (nombres en inglés, p. ej.
   `feat/permissions-model`).
2. `uv run pre-commit install` una vez por clon: los hooks aplican formato,
   lint y escaneo de secretos en cada commit.
3. Antes de abrir un pull request: `uv run pytest`, `uv run ruff check .`,
   `uv run mypy`. CI ejecuta lo mismo y no se mezcla con checks en rojo.
4. Toda decisión arquitectónica relevante se registra como ADR (ver abajo)
   en el mismo pull request que la implementa.
5. Las decisiones cerradas de CLAUDE.md no se reabren sin un ADR que lo
   justifique.

## ADRs (Architecture Decision Records)

- Ubicación: `docs/adr/NNNN-titulo-corto.md`, numeración incremental de
  cuatro dígitos.
- Estructura: **Estado** (propuesto / aceptado / reemplazado por NNNN),
  **Contexto**, **Decisión**, **Consecuencias**.
- En español, como el resto de la documentación.
- Un ADR no se edita para cambiar la decisión: se escribe uno nuevo que lo
  reemplaza y se enlazan entre sí.
