# Cierre formal — O1-A: auditoría y diseño de la orquestación semiautomática

- **Fecha:** 2026-11-01.
- **Estado:** cierre formal de O1-A, **efectivo cuando este documento quede integrado en
  `main` con el CI obligatorio en verde**.
- **Qué cierra:** el subbloque **O1-A** del bloque O1 (orquestación semiautomática ChatGPT ↔
  GitHub ↔ Claude Code). O1-A fue solo auditoría y diseño, de solo lectura.
- **Qué NO cierra:** **no cierra O1.** No se construyó ningún ejecutor ni se ejecutó Claude
  Code sin supervisión. La capacidad descrita en el Anexo A es diseño hasta que O1.3 la
  demuestre.
- **Por qué se versiona ahora:** O1-A prohibía modificar el repositorio, y por eso su informe
  solo existía en la conversación. Las reglas 17 y 26 exigen versionarlo; se hace aquí, dentro
  de O1.1.
- **Decisión técnica:** [ADR 0036](adr/0036-orquestacion-semiautomatica-de-bloques.md).
- **Marcas de afirmación** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**,
  **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Sanitización:** este documento no contiene secretos, tokens, claves, cadenas de conexión ni
  datos de planta. La única ruta de perfil de usuario del informe original se reemplazó por
  `%USERPROFILE%`.

---

## 1. Objetivo

Determinar qué se puede reutilizar y qué falta para reducir el trabajo mecánico entre ChatGPT,
Claude Code y GitHub sin perder el control humano, y recomendar si conviene implementarlo.

## 2. Alcance

**Entró:** comprobación del estado de Git; lectura de estructura, scripts, workflows, Skills y
reglas; versiones de herramientas; opciones de Claude Code en `--help`; diseño, gates, riesgos y
fases.

**Quedó fuera (explícito):** crear archivos o ramas, commit, push, PR, instalar software, ejecutar
tests, ejecutar `claude -p`, tocar `.env`, GitHub Actions, Render, Supabase, SAP, RAG, Phi o
llama.cpp.

## 3. Estado inicial

- **HECHO MEDIDO:** rama `main`, working tree limpio, y `HEAD`, `origin/main` y `ls-remote` en
  `3068eed14a348cc154357f168a49dfb4d76674a5`.
- **HECHO DEL REPOSITORIO:** D2.7 cerrado formalmente; 56 merges de PR en `main`.

## 4. Trabajo realizado

1. Comprobación del estado de Git y carga de la Skill `elsa-block-planning`.
2. Lectura de `ci.yml`, `contributing.md`, `elsa-release`, `elsa-testing`, `MCP_POLICY.md`,
   `EXTERNAL_TOOLS_EVALUATION.md`, `BLOCK_CLOSURE_STANDARD.md` y `Start-ElsaMode.ps1`.
3. Comprobación de herramientas de PC1 y de `claude --help`.
4. Consultas anónimas a la API pública de GitHub.
5. Redacción del informe y nueva comprobación final de Git, sin cambios.

## 5. Decisiones

| Decisión | Quién | Motivo |
|---|---|---|
| **DECISIÓN TOMADA:** recomendar implementar O1 por fases, con O1.3 como punto de decisión | Claude Code propuso; Juan autorizó definir y luego implementar O1.1 | Es viable con lo instalado, pero el modo sin supervisión no se ejecutó |
| **DECISIÓN TOMADA:** carpeta externa `%USERPROFILE%\elsa-o1\` | Juan, al autorizar O1.1 | Protege al Modo ELSA y queda fuera de OneDrive |
| **DECISIÓN TOMADA:** PR por clic, sin token | Juan, al autorizar O1.1 | Sin credencial nueva, y es un control humano |

Decisión arquitectónica registrada en [ADR 0036](adr/0036-orquestacion-semiautomatica-de-bloques.md).

## 6. Pruebas

No se ejecutaron tests de implementación: O1-A no modificó código y lo prohibía expresamente. Se
ejecutaron solo comprobaciones de lectura. No se ejecutó `claude -p`, `pre-commit` ni gitleaks.

## 7. Comandos relevantes

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse origin/main
git ls-remote origin refs/heads/main
git rev-list --left-right --count HEAD...origin/main
claude --help
curl -s https://api.github.com/repos/VallejoOsorio2026/Elsa-ai
curl -s https://api.github.com/repos/VallejoOsorio2026/Elsa-ai/branches/main
```

Además de los permitidos en el prompt, se usaron `git remote -v`, `git ls-remote`, `git rev-list`,
`claude --help`, `tasklist`, `where.exe` y `curl` anónimo, todos de lectura. No se abrieron `.env`
ni las credenciales de Claude Code; de la configuración de usuario solo se leyeron nombres de
claves y conteos.

## 8. Resultados

**HECHO MEDIDO**, salidas reales de la auditoría:

```text
--HEAD--          3068eed14a348cc154357f168a49dfb4d76674a5
--origin/main--   3068eed14a348cc154357f168a49dfb4d76674a5
--upstream delta-- 0 0

git version 2.53.0.windows.2
Python 3.14.4                 (global)
Python 3.12.13                (.venv)
uv 0.11.14
2.1.261 (Claude Code)
gh: command not found
gitleaks: command not found

{'private': False, 'visibility': 'public', 'default_branch': 'main', 'has_issues': True}
{'name': 'main', 'protected': True}
Secret scan (gitleaks) completed success
Lint, types and tests completed success
anon core limit 60
```

El informe completo está en el [Anexo A](#anexo-a--informe-o1-a-entregado).

## 9. Métricas

| Métrica | Valor | Método |
|---|---|---|
| Merges de PR en `main` | 56 | `git log --merges --grep='Merge pull request'` |
| Merges solo de cierre, entre los últimos 8 | 5 | `git log -8 --merges` |
| Hooks activos en el clon al auditar | 0 | `ls .git/hooks`, sin `.sample` |
| Límite de la API anónima de GitHub | 60/hora | `GET /rate_limit` |

## 10. Aportes de Claude Code

Claude Code (modelo Opus 5.5) produjo la auditoría y el informe. Juan revisó el informe y autorizó
definir O1.1. Sesión: `bb23d2bc-80dc-4076-9953-97eebc08161d`, verificada porque existe su
transcripción local con ese identificador.

## 11. Aportes de Codex

Nada que registrar.

## 12. Operaciones manuales y de PowerShell

Juan pegó el prompt de O1-A en Claude Code. Ninguna otra operación manual.

## 13. Incidentes

Sin fallos de ejecución. Correcciones hechas después de entregar el informe:

1. El informe decía «solo librería estándar» para el ejecutor. Se corrigió porque la especificación
   usa YAML y PyYAML ya es dependencia de desarrollo.
2. El informe pedía aceptar el riesgo R1 antes de O1.1. Se movió a O1.3, que es donde se materializa.
3. La comprobación de `OneDrive.exe` se hizo con una salida recortada a su última línea, en la que
   `tasklist` indicaba que no había coincidencias. Se trata como observación de ese momento.

## 14. Git

O1-A no tocó Git. Estado final medido: `main`, limpio, `3068eed`.

## 15. Ramas

Ninguna creada en O1-A.

## 16. Commits

Ninguno en O1-A. Este documento entra con O1.1.

## 17. Pull requests

Ninguno propio. Se integra en el primer PR de O1.1; su número y CI constan en
`docs/o1-1-contrato-y-preparacion-cierre.md`.

## 18. Migraciones

No aplica: ninguna escrita ni aplicada.

## 19. Estado operacional final

ELSA funcional no cambió. Al terminar O1-A no existía ningún mecanismo de orquestación ni hooks
activos en el clon.

## 20. Pendientes

| Pendiente | Responsable |
|---|---|
| **PENDIENTE:** revisar la protección de `main` | Juan, en O1.1 |
| **PENDIENTE:** aceptar o no el riesgo R1 | Juan, en O1.3 |
| **PENDIENTE:** decidir si el repositorio sigue público | Juan, aparte |
| **PENDIENTE:** revisar si `.env` se sincroniza con la nube | Juan, aparte |

## 21. Siguiente bloque

O1.1 — Contrato y preparación, ya autorizado por Juan: versiona el contrato y activa el escaneo local
de secretos, condición previa de cualquier automatización.

---

## Anexo A — Informe O1-A entregado

Transcrito de la conversación. Solo se reemplazó la ruta de perfil por `%USERPROFILE%` y se ajustó
el nivel de los títulos.

### A.1 Estado del repositorio

| Verificación | Resultado medido |
|---|---|
| Repositorio | `https://github.com/VallejoOsorio2026/Elsa-ai.git` |
| Rama | `main` |
| Working tree | limpio |
| `HEAD`, `origin/main` y GitHub remoto (`ls-remote`) | los tres en `3068eed14a348cc154357f168a49dfb4d76674a5` |
| CI de ese commit | gitleaks y tests/lint en `success` |
| Visibilidad | **público**, con issues habilitados |
| `main` protegida | `protected: true`; los detalles de la regla no se ven sin iniciar sesión |

Inconsistencias reportadas (regla 19):

1. **Gitleaks no protegía los commits en PC1.** No estaba en el PATH y había 0 hooks activos, aunque
   `pre-commit` estaba en `.venv` y su caché existía. Solo protegía CI, que actúa después del push.
   Como el repositorio es público, un push ya es una publicación.
2. **No había barreras técnicas en Claude Code.** No existían `.claude/settings.json` ni `.mcp.json`,
   y la configuración de usuario no tenía reglas de permisos.
3. **`elsa-release` choca con el objetivo.** Dice «No abras un PR si no te lo han pedido». Hay que
   ajustarla para que una especificación aprobada cuente como ese pedido.
4. **«Fuera del repositorio» choca con el diseño,** que recomienda una carpeta de trabajo externa.
5. **Reglas 17 y 26.** El informe solo existía en la conversación.

### A.2 Herramientas disponibles

| Herramienta | Estado en PC1 |
|---|---|
| Git | 2.53.0, con Git Credential Manager |
| Python | global 3.14.4; `.venv` 3.12.13, que es la del proyecto |
| uv | 0.11.14 |
| Claude Code | 2.1.261 |
| pytest, ruff, mypy, pre-commit | dentro de `.venv` |
| GitHub CLI (`gh`) | no existe; no se instala ni se exige |
| Gitleaks | no está en el PATH |
| Docker | el binario existe; no se comprobó si está en marcha |

Reutilizable: `CLAUDE.md`, las 6 Skills, los 3 subagentes revisores, `ci.yml` (corre en cualquier
rama al hacer push), el estándar de cierre y el patrón de `scripts/*.ps1`.

No reutilizable: `src/elsa/agent/`. Es el agente del relay de producción y no debe mezclarse con O1.

### A.3 Flujo manual actual

| Actor | Qué hace hoy | ¿Manual? |
|---|---|---|
| ChatGPT | Planea, escribe prompts, revisa evidencia | Depende de que Juan le copie todo |
| Juan | Copia prompts y resultados, ejecuta Git, abre PR, hace merge | Sí, es el cuello de botella |
| Claude Code | Audita, edita, prueba y reporta | Se activa a mano, con prompts largos |
| Git | Ramas, commits y push | Comandos a mano |
| GitHub | Protege `main`, aloja los PR | Clics |
| CI | Lint, tipos, tests y gitleaks | Ya automático |

### A.4 Qué se puede automatizar

Comprobar repositorio, rama, working tree y sincronía; crear rama y copia de trabajo; entregar la
especificación desde un archivo; ejecutar pruebas, escaneo de secretos y control de alcance; commit
y push de la rama del bloque; leer el resultado de CI sin token mientras el repositorio sea público;
generar un informe de evidencia y un enlace de PR rellenado; redactar el borrador del cierre.

### A.5 Qué no se debe automatizar

Merge, deploy, force push, `reset --hard` y borrados destructivos; migraciones, Render y Supabase; SAP
real, secretos, red y firewall, instalación de programas; pruebas físicas; ampliar el alcance o avanzar
al bloque siguiente; aprobar una especificación o decidir un cambio de arquitectura.

### A.6 Arquitectura O1 V1 recomendada

```text
ChatGPT redacta especificación
   ↓ Juan la guarda en la bandeja y lanza un comando
Runner local: revisa todo y Juan escribe APROBAR <id>
   ↓
Copia de trabajo aparte (sin .env, sin datos reales)
   ↓
Claude Code sin supervisión (todo prohibido salvo lista corta)
   ↓
Runner verifica: alcance → pruebas → secretos
   ↓
Push solo de la rama → lee CI → imprime enlace de PR → TERMINA
   ↓
Juan crea el PR, revisa y hace merge
```

Hace falta un orquestador local, pero pequeño: un script de un solo uso, no un servicio residente. Se
justifica porque una instrucción a un modelo de IA no garantiza timeouts ni que se revise a sí mismo.

| Hipótesis `.orchestration/` | Decisión | Motivo |
|---|---|---|
| `PROJECT_RULES.md` | No crear | Duplica `CLAUDE.md` |
| `CURRENT_STATE.md` | No crear | Se desactualizaría; Git y `PROJECT_HISTORY_AND_CURRENT_STATE.md` ya cumplen esa función |
| `CLAUDE_EXECUTION_RULES.md` | Convertir | Pasa a `docs/orchestration/README.md` y a una plantilla |
| `work/<bloque>.md` | Conservar | En `docs/orchestration/work/` |

La copia de trabajo aparte fue el hallazgo más importante. El Modo ELSA corre desde el clon, usando
su `.env` y su `.venv`; cambiar de rama allí alteraría el código del nodo en vivo.

| Pregunta | Respuesta |
|---|---|
| Cómo recibe la tarea | `Start-ElsaBlock.ps1 -Block <id>` lee `%USERPROFILE%\elsa-o1\inbox\<id>.md` |
| Qué valida | URL del remoto, `main`, working tree limpio, `HEAD` = `origin/main`, formato de la especificación, sin secretos, un solo bloque a la vez |
| Cómo identifica el repositorio | URL exacta de `origin` |
| Cómo crea la rama | `claude/o1-<id>` desde `origin/main`; si ya existe, se detiene |
| Cómo invoca a Claude | `claude -p` con instrucción corta por entrada estándar y permisos prohibitivos por defecto |
| Cómo valida el retorno | Respuesta JSON estructurada, y además revisa Git por su cuenta |
| Cómo ejecuta los tests | Comandos fijos en su código, nunca tomados de la especificación |
| Cómo deja evidencia | `docs/orchestration/runs/<id>.md` en la rama |
| Cómo impide el merge | No tiene comando de merge, Claude no puede hacer push y `main` está protegida |
| Dónde se detiene | En el primer error, y siempre tras imprimir el enlace del PR |

**A. Claude Code:** sí puede recibir una especificación desde archivo, según su ayuda; **no se
ejecutó**. `--help` documenta `-p`, `--permission-mode dontAsk`, `--permission-prompts none`,
`--allowedTools`, `--settings`, `--strict-mcp-config`, `--restricted`, `--output-format json`,
`--json-schema` y `--session-id`. Advertencias: en modo `-p`, un archivo de configuración inválido se
ignora en silencio, y `--max-turns` no aparece en esta versión.

**B. Memoria compartida:** archivo versionado como fuente principal y PR para revisar. Issues y
comentarios quedan rechazados como fuente de órdenes, porque en un repositorio público cualquiera
puede escribirlos.

**C. ChatGPT:** funciona con o sin integración. No se verificó qué integración tiene la cuenta.

**D. PC1:** comprobación de `origin`; rama y working tree validados antes de empezar; timeouts por
fase con cierre del árbol de procesos; sin bucles ni reintentos automáticos; logs crudos fuera del
repositorio; parada ante error; sin merge en el código.

**Protección de secretos:**

| Lugar | Protección |
|---|---|
| Archivos | La copia aparte no tiene `.env`, y Claude no puede leer `.env*` |
| Argumentos | Solo identificadores y rutas; la instrucción va por entrada estándar |
| Entorno | El runner filtra variables con token, clave, contraseña o similares |
| Git | Escaneo local antes del push; CI queda como segunda barrera |
| Autenticación | Ningún token nuevo; el push usa el Credential Manager ya instalado |

**E. Control de Claude Code:** rutas permitidas comparadas con el diff real; rutas bloqueadas siempre
(`supabase/**`, `render.yaml`, `.github/**`, `.env*`, `.claude/**`, `CLAUDE.md`); dependencias solo si
la especificación lo declara; una ejecución equivale a un bloque.

Base de datos: no hace falta. El estado se deduce de Git, del informe y del PR.

### A.7 Archivos propuestos

Crear: ADR 0036, `docs/orchestration/README.md`, `SPEC_TEMPLATE.md`, `work/<id>.md`, `runs/<id>.md`,
`scripts/orchestrator.py`, `scripts/Start-ElsaBlock.ps1`, `.claude/o1-headless-settings.json`,
`tests/test_orchestrator.py` y `docs/o1-orquestacion-semiautomatica-cierre.md`, más un cierre por
subbloque.

Modificar: `pyproject.toml`, `.claude/skills/elsa-release/SKILL.md`, `docs/agentic-tooling/README.md`,
`README.md`, `docs/project/PROJECT_HISTORY_AND_CURRENT_STATE.md` y
`docs/project/HANDOVER_AND_CONTINUITY_MAP.md`. Dependencias nuevas: ninguna.

### A.8 Gates humanos obligatorios

Los cinco estados y las paradas están en el [ADR 0036](adr/0036-orquestacion-semiautomatica-de-bloques.md)
y en el [manual](orchestration/README.md).

### A.9 Riesgos

| # | Riesgo | Nivel | Mitigación |
|---|---|---|---|
| R1 | Sin aislamiento real: los tests corren con el usuario de Windows | Alto, residual | Copia aparte, entorno filtrado y aprobación previa; reduce el riesgo, no lo elimina |
| R2 | Push = publicación en un repositorio público | Alto | Escaneo local obligatorio antes del push |
| R3 | Permisos ignorados en silencio por configuración inválida | Alto | Validación y prueba de bloqueo en cada arranque |
| R4 | Protección de `main` con excepciones para administradores | Medio | Juan la revisa en GitHub durante O1.1 |
| R5 | Inyección desde texto de terceros | Medio | Solo se aceptan órdenes de la especificación aprobada |
| R6 | Falso verde: pytest omite tests de PostgreSQL sin `ELSA_TEST_DATABASE_URL` | Medio | El informe declara las omisiones, y CI sí los corre |
| R7 | La lectura anónima de CI falla si el repositorio pasa a privado o se agota el límite | Bajo | CI queda como «desconocido» y se revisa en el PR |
| R8 | Coste de uso de Claude; `--max-budget-usd` podría no aplicar a una suscripción | Bajo | Medirlo en O1.3 |
| R9 | Ya hay 3 worktrees registrados (`A`, `B`, `Elsa-ai-4-1b`) | Bajo | Nombres propios y no tocarlos |

### A.10 Fases propuestas

| Fase | Entrega | Se acepta si |
|---|---|---|
| O1.1 Contrato y preparación | ADR, manual, plantilla, informe versionado; revisar `main`; activar pre-commit | Gitleaks local detecta un secreto falso; un bloque se puede dar con una línea |
| O1.2 Runner sin Claude y sin push | Comprobaciones, copia aparte, control de alcance, pruebas, timeouts, informe | Tests con Claude falso cubren cada causa de parada |
| O1.3 Claude real y prueba de bloqueo | Conexión real con permisos prohibitivos | Merge, push, lectura de `.env` y edición externa quedan bloqueados de forma demostrada |
| O1.4 Push, CI y enlace de PR | Publicar la rama y leer CI | Una rama de prueba llega a `PR_READY`; no existe camino al merge |
| O1.5 Validación real y cierre | Un bloque real de bajo riesgo de principio a fin | Pasos manuales medidos antes y después; cierre en `main` |

### A.11 Estimación de esfuerzo

**INFERENCIA**, no medida: unos 3 días de trabajo de Claude y 2,5–3 horas de Juan en total, con
complejidad media-baja en código. Lo delicado son los permisos.

### A.12 Recomendación final

```text
IMPLEMENTAR O1
```

Por fases, con O1.3 como punto de decisión. Es posible usando solo lo que ya está instalado; Claude
Code documenta las opciones necesarias; CI corre en cualquier rama y se lee sin credenciales; `main`
figura como protegida; y la fricción está medida. Lo que no estaba demostrado es el modo sin
supervisión, y O1.3 existe para comprobarlo.

### A.13 Estado Git final de O1-A

```text
git status --short          → (vacío)
git branch --show-current   → main
git rev-parse HEAD          → 3068eed14a348cc154357f168a49dfb4d76674a5
git rev-parse origin/main   → 3068eed14a348cc154357f168a49dfb4d76674a5
```
