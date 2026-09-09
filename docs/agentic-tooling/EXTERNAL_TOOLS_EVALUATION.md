# Evaluación de Skills y MCPs externos

Fecha de la evaluación: **2026-09-09**. Fuentes primarias consultadas ese día;
los enlaces están al final de cada ficha.

**Resultado: no se instaló ninguna herramienta externa en este trabajo.** Todo
lo construido (`.claude/skills/`, `.claude/agents/`, esta documentación) usa
únicamente formatos nativos de Claude Code. Esta evaluación existe para que la
decisión de instalar algo, cuando llegue, se tome con datos y no por impulso.

## Criterios

| Criterio | Qué se pregunta |
|---|---|
| Mantenedor | ¿Quién publica y actualiza? ¿Es el fabricante del sistema al que accede? |
| Valor para ELSA | ¿Qué problema real nuestro resuelve, hoy? |
| Coste de contexto | ¿Cuántos tokens cuesta tenerlo cargado aunque no se use? |
| Riesgo / permisos | ¿A qué da acceso? ¿Qué pasa si el contenido que devuelve es hostil? |
| Veredicto | NOW (ahora) · LATER (cuando exista la fase) · NO |

## Resumen

| Candidato | Mantenedor | Coste de contexto | Veredicto |
|---|---|---|---|
| `skill-creator` | Anthropic | Nulo si no se invoca | **NOW** |
| Vercel `find-skills` | Vercel Labs | Bajo, permanente | **NO** |
| Supabase MCP | Supabase | Alto (muchas herramientas) | **LATER** |
| GitHub MCP | GitHub | Medio-alto, acotable por *toolsets* | **LATER** |
| Playwright: CLI/Skill frente a MCP | Microsoft | MCP alto (40+ herramientas) | **LATER**, y como CLI |
| Context7 | Upstash | Bajo (2 herramientas) | **NO** |
| Langfuse | Langfuse | Medio | **LATER** |

---

## `skill-creator` — Anthropic

**Finalidad.** Crear, evaluar, mejorar y comparar Skills. Tiene cuatro modos
(Create, Eval, Improve, Benchmark) y scripts para validar la estructura de un
`SKILL.md` y para medir si una Skill se activa cuando debe, con análisis de
varianza.

**Valor para ELSA.** Es la única herramienta de esta lista que sirve
directamente para lo que estamos construyendo: comprobar que nuestras seis
Skills se disparan con los disparadores correctos y no se pisan entre sí. Es
también la vía para revisar las descripciones cuando aparezca la séptima.

**Coste de contexto.** Nulo mientras no se invoca: es una Skill, no un MCP. Su
descripción es la única línea permanente.

**Riesgo.** Bajo. Es de Anthropic, opera sobre ficheros locales y no necesita
red ni credenciales. No toca `src/`, `supabase/` ni el proyecto Supabase.

**Veredicto: NOW.** Ya está disponible en el entorno de trabajo actual. No se
vendorea al repositorio: es una capacidad del entorno, no un artefacto de ELSA.

- <https://github.com/anthropics/claude-plugins-official/tree/main/plugins/skill-creator>
- <https://claude.com/plugins/skill-creator>

---

## `find-skills` — Vercel Labs

**Finalidad.** Buscar e instalar Skills del ecosistema abierto (`skills.sh`)
cuando el usuario pregunta «¿hay una skill para X?». Se instala con
`npx skills add`.

**Valor para ELSA.** Marginal. ELSA no necesita descubrir Skills genéricas: sus
procedimientos son específicos del proyecto y ya están escritos. El ecosistema
que indexa es de terceros sin relación con PAPELSA.

**Coste de contexto.** Bajo pero permanente, y con una tendencia mala: su
propósito es proponer instalar más Skills, que es exactamente lo que este
trabajo intenta evitar.

**Riesgo.** Instala código de terceros a partir de una búsqueda. El criterio de
calidad que documenta es el número de instalaciones, que no es una garantía de
seguridad. Introduce una vía por la que instrucciones escritas por
desconocidos acaban en el contexto de un proyecto que se entrega a un cliente.

**Veredicto: NO.** Contradice el principio de este trabajo. Si algún día hace
falta una capacidad concreta, se busca y se evalúa a mano, una vez.

- <https://github.com/vercel-labs/skills>
- <https://vercel.com/docs/agent-resources/skills>

---

## Supabase MCP — Supabase

**Finalidad.** Servidor MCP oficial que expone gestión de proyectos, consulta
de tablas, ejecución de SQL y configuración. Soporta modo `read-only` (excluye
las herramientas que mutan) y `project_scoped` (fija el proyecto y elimina
`project_id` de los esquemas de entrada).

**Valor para ELSA.** Real pero futuro: inspeccionar el estado del esquema
remoto sin abrir el dashboard, y verificar tras aplicar una migración. Hoy no
resuelve nada que la CLI de Supabase no haga ya desde la terminal, que es como
está escrito el runbook del Bloque 2 y como se ensayó.

**Coste de contexto.** Alto. Expone gestión de proyectos completa; son muchas
herramientas cargadas en cada petición de la sesión.

**Riesgo — el más alto de la lista.** Un MCP con acceso a la base es acceso a
los datos de PAPELSA. Dos peligros propios de ELSA:

1. **Proyecto equivocado.** El Asistente de Materiales es otro proyecto
   Supabase. Un servidor sin `project_scoped` puede alcanzarlo. La regla 15 del
   contrato lo prohíbe.
2. **Inyección indirecta.** El contenido de las filas entra al contexto. Si un
   aporte de conocimiento contiene instrucciones, un servidor con escritura las
   podría acabar ejecutando. El propio Supabase remite a sus «security best
   practices» antes de conectar un LLM a un proyecto.

**Veredicto: LATER.** No antes de que exista el proyecto Supabase remoto
enlazado y haya una tarea concreta que lo necesite. Condiciones mínimas al
activarlo: `read-only`, `project_scoped` al proyecto de ELSA, alcance
*project* en `.mcp.json`, credencial fuera del repositorio y desactivado al
terminar la tarea.

- <https://github.com/supabase-community/supabase-mcp>
- <https://supabase.com/docs/guides/getting-started/mcp>

---

## GitHub MCP — GitHub

**Finalidad.** Servidor MCP oficial de GitHub, en versión remota alojada
(`https://api.githubcopilot.com/mcp/`, con OAuth) y en contenedor local. Agrupa
sus herramientas en *toolsets* (`repos`, `issues`, `pull_requests`, `actions`,
`code_security`…), activables con `--toolsets` o `GITHUB_TOOLSETS`.

**Valor para ELSA.** Moderado. Leer el log del job de CI que falló sin salir de
la sesión es cómodo. Pero `git` ya cubre ramas, diffs, commits y push, que es
el 90 % del trabajo real, y `.github/workflows/ci.yml` dice qué corre.

**Coste de contexto.** Medio-alto por defecto; acotable de verdad si se limita
a `actions` o a `pull_requests`. Sin acotar, no compensa.

**Riesgo.** Da acceso al repositorio con los permisos del token. Los cuerpos de
issues y de comentarios de revisión son texto escrito por terceros que entra al
contexto: superficie de inyección indirecta.

**Veredicto: LATER.** Cuando el ciclo de PR y CI sea frecuente y se note la
fricción. Al activarlo: versión remota con OAuth (el token no queda en disco),
solo el *toolset* estrictamente necesario, y nunca con permisos de
administración de la organización.

- <https://github.com/github/github-mcp-server>

---

## Playwright — CLI/Skill frente a MCP · Microsoft

**Finalidad.** Automatización de navegador. El MCP expone **más de 40
herramientas** y opera sobre el árbol de accesibilidad; la CLI (`npx playwright
test`) ejecuta especificaciones escritas como código.

**Valor para ELSA.** Directo y ya identificado: la aceptación de interfaz de
`elsa-ui-acceptance` es una lista de comprobación manual en seis anchos. Es
justo lo que se automatiza bien.

**La comparación que importa:**

| | MCP | CLI / Skill |
|---|---|---|
| Coste de contexto | 40+ herramientas, permanente | Cero: es un comando |
| Reproducible en CI | No | Sí |
| Queda como artefacto del proyecto | No | Sí: es código versionado |
| Útil para explorar algo una vez | Sí | Menos |

**Riesgo.** La documentación de Microsoft es explícita: *«Playwright MCP is not
a security boundary»*. Con la CLI el navegador solo visita lo que dice el test.

**Veredicto: LATER, y como CLI.** La aceptación de interfaz debe acabar siendo
tests de Playwright versionados que corran en CI, no un MCP que un humano
conduce. El MCP se queda como herramienta de exploración puntual, nunca
cargada de forma permanente. Decidirlo exige su propio bloque: añade una
dependencia de Node a un proyecto que hoy es solo Python.

- <https://github.com/microsoft/playwright-mcp>

---

## Context7 — Upstash

**Finalidad.** Inyectar documentación actualizada y específica de versión de
librerías en el prompt. Expone `resolve-library-id` y `query-docs`.

**Valor para ELSA.** Bajo. Las dependencias de ELSA son pocas, estables y muy
documentadas (FastAPI, pydantic, asyncpg, pytest), y `uv.lock` fija las
versiones. El problema que resuelve Context7 —conocimiento desactualizado sobre
una librería que se mueve rápido— no es un problema que tengamos.

**Coste de contexto.** Bajo: dos herramientas.

**Riesgo.** El backend, el motor de *parsing* y el rastreador son privados y no
están en el repositorio público. Las consultas salen hacia un tercero. En un
proyecto que se entrega a un cliente industrial, enviar contexto de trabajo a
un servicio externo sin necesidad es un coste de cumplimiento sin beneficio.

**Veredicto: NO.** Reevaluable si el stack incorpora una librería que se mueva
deprisa y sobre la que el asistente se equivoque de forma medible.

- <https://github.com/upstash/context7>

---

## Langfuse — Langfuse

**Finalidad.** Observabilidad de aplicaciones LLM: trazas, evaluaciones y
gestión de prompts. Ofrece servidor MCP autenticado sobre su plataforma de
datos y un MCP público de su documentación.

**Valor para ELSA.** Nulo **hoy**: no hay LLM conectado. El puerto `llm` existe
con adaptador fake. Cuando haya un modelo real, la pregunta «¿por qué respondió
esto y con qué evidencia?» pasa a ser central, y ahí la trazabilidad de la
regla 2 del contrato exige tener alguna respuesta.

**Coste de contexto.** Medio; tanto lectura como escritura por defecto. Su
propia documentación indica restringir a solo lectura con una lista de permitidos
en el cliente MCP.

**Riesgo.** Las trazas contienen preguntas de ingenieros y fragmentos de
manuales de PAPELSA. Enviarlas a un servicio alojado por un tercero es una
decisión de tratamiento de datos que corresponde a PAPELSA, no a este
repositorio. Langfuse es de código abierto y autohospedable, que es la única
variante compatible con el criterio de LLM local del proyecto.

**Nota de verificación.** `langfuse.com` está bloqueado por el proxy de salida
de este entorno; su documentación no pudo leerse como fuente primaria directa.
Lo anterior procede de resultados de búsqueda que citan su documentación
oficial. **Confirmar contra la fuente antes de decidir.**

**Veredicto: LATER.** Se reevalúa cuando exista un LLM real conectado, y solo
en variante autohospedada.

- <https://langfuse.com/docs/api-and-data-platform/features/mcp-server> (no verificable desde este entorno)

---

## Conclusión

Lo único con veredicto **NOW** es `skill-creator`, que es de Anthropic, no
necesita red ni credenciales y sirve para mantener lo que acabamos de
construir. Todo lo demás toca datos de PAPELSA o cuesta contexto permanente sin
resolver un problema que tengamos hoy.

Reevaluar cuando: se enlace el proyecto Supabase remoto (Supabase MCP), el
ciclo de PR se vuelva frecuente (GitHub MCP), se automatice la aceptación de
interfaz (Playwright CLI) o se conecte un LLM real (Langfuse autohospedado).
