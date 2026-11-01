# Cierre formal — O1.1: contrato y preparación de la orquestación

- **Fecha:** 2026-11-01. El PR #58 se abrió a las 19:08:52 UTC y se fusionó a las 19:14:51 UTC.
- **Estado:** cierre formal de O1.1, **efectivo cuando este documento quede integrado en `main`
  con el CI obligatorio en verde** (ver «Regla de continuidad»).
- **Qué cierra:** el subbloque **O1.1** del bloque O1 (orquestación semiautomática ChatGPT ↔
  GitHub ↔ Claude Code). Deja versionado cómo se especifica y controla un bloque, y activo el
  escaneo local de secretos.
- **Qué NO cierra:** **no cierra O1.** No existe ningún ejecutor, no se ejecutó `claude -p` y nada
  se automatizó todavía. Hoy el contrato se usa a mano. Ver §20.
- **Prerrequisito:** O1-A ([`o1-a-auditoria-y-diseno-cierre.md`](o1-a-auditoria-y-diseno-cierre.md)).
- **Decisión técnica:** [ADR 0036](adr/0036-orquestacion-semiautomatica-de-bloques.md). Operación:
  [`orchestration/README.md`](orchestration/README.md). Especificación:
  [`orchestration/work/O1.1.md`](orchestration/work/O1.1.md).
- **Marcas de afirmación** (`BLOCK_CLOSURE_STANDARD.md`): **HECHO MEDIDO**,
  **HECHO DEL REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.
- **Sanitización:** este documento no contiene secretos, tokens, claves, cadenas de conexión, rutas
  de perfil de usuario ni datos de planta. El token de la prueba era aleatorio y sin valor; nunca se
  mostró y aquí no se reproduce.

---

## 1. Objetivo

Dejar versionado cómo se especifica y controla un bloque, y activar el escaneo local de secretos
antes de construir cualquier automatización.

## 2. Alcance

**Entró:** ADR 0036, manual, plantilla, especificación de O1.1, cierre de O1-A con su auditoría,
enlaces en dos documentos, hooks activos en el clon de PC1, prueba de bloqueo de gitleaks, revisión
de la protección de `main` y este cierre.

**Quedó fuera (explícito):**

| Qué | Dónde queda |
|---|---|
| Ejecutor, lanzador y tests | O1.2 |
| Configuración sin supervisión, `claude -p`, aceptación del riesgo de aislamiento | O1.3 |
| Ajuste de la Skill `elsa-release` | O1.4 |
| `PROJECT_HISTORY_AND_CURRENT_STATE.md` y `HANDOVER_AND_CONTINUITY_MAP.md` | O1.5 |
| `CLAUDE.md`, `ci.yml`, `pyproject.toml`, `.env`, ELSA funcional, Render, Supabase | No se tocan |
| Cambiar la protección de `main` o la visibilidad del repositorio | Decisión de Juan |

## 3. Estado inicial

**HECHO MEDIDO:** `main` limpio y sincronizado en `3068eed14a348cc154357f168a49dfb4d76674a5`; 0 hooks
activos en el clon; `gitleaks` fuera del PATH; entorno de gitleaks ya presente en la caché de
pre-commit, sin haberse ejecutado en esta máquina durante O1-A.

## 4. Trabajo realizado

1. Copia aparte en `%USERPROFILE%\elsa-o1\worktrees\o1-1`, sin `.env`.
2. Instalación de los hooks de pre-commit en el clon.
3. Prueba de bloqueo con un token falso en una rama desechable, sin push; limpieza posterior.
4. Redacción de ADR 0036, manual, plantilla y especificación.
5. Redacción del cierre de O1-A con la auditoría como anexo.
6. Enlaces en `README.md` y `docs/agentic-tooling/README.md`.
7. Revisión del diff: rutas permitidas, rutas personales, enlaces y cabeceras YAML.
8. Dos commits, push solo de la rama y lectura de CI.
9. Juan: revisión de la regla de `main`, sesión de una línea, creación y merge del PR #58.
10. Este cierre y el ADR 0036 en estado «aceptado».

## 5. Decisiones

| Decisión | Quién | Motivo |
|---|---|---|
| **DECISIÓN TOMADA:** carpeta externa `%USERPROFILE%\elsa-o1\` | Juan | Protege al Modo ELSA y queda fuera de OneDrive |
| **DECISIÓN TOMADA:** PR por clic, sin token | Juan | Sin credencial nueva, y es un control humano |
| **DECISIÓN TOMADA:** hooks activos en el clon de PC1 | Juan | Un push es una publicación; el escaneo debe ser anterior |
| **DECISIÓN TOMADA:** `docs/orchestration/` en lugar de `.orchestration/` | Claude Code, sin objeción de Juan | El proyecto documenta en `docs/` |
| **DECISIÓN TOMADA:** cabecera YAML | Claude Code, sin objeción de Juan | Mismo formato que las Skills; sin dependencias nuevas |
| **DECISIÓN TOMADA:** ADR «propuesto» en el primer PR y «aceptado» en este | Claude Code, sin objeción de Juan | Queda aceptado cuando Juan ya hizo el merge |
| **DECISIÓN TOMADA:** dos PR | Claude Code, sin objeción de Juan | Este cierre cita el número y el CI del primero |

## 6. Pruebas

Verificación proporcional para un cambio solo de documentación (`elsa-testing`): hooks y CI. **No se
ejecutó localmente** `pytest`, `ruff` ni `mypy` de forma directa; CI sí los corrió.

| Prueba | Quién | Resultado |
|---|---|---|
| Commit de un token falso | Claude Code | **Bloqueado** por gitleaks |
| Token en la salida guardada | Claude Code | 0 coincidencias |
| Commit normal desde la copia aparte | Claude Code | Hooks en verde |
| Diff contra rutas permitidas y rutas personales | Claude Code | Sin hallazgos |
| Enlaces relativos y cabeceras YAML | Claude Code | Todos válidos |
| Sesión de una línea en modo plan | Juan | Coincide con la especificación |
| CI de la rama, del PR y del merge | GitHub Actions | `success` |

## 7. Comandos relevantes

```bash
git worktree add <carpeta> -b claude/o1-1-contrato-y-preparacion origin/main
.venv/Scripts/pre-commit.exe install
git push -u origin refs/heads/<rama>:refs/heads/<rama>
curl -s https://api.github.com/repos/VallejoOsorio2026/Elsa-ai/rules/branches/main
claude --permission-mode plan
```

## 8. Resultados

**HECHO MEDIDO**, prueba de bloqueo (salida real recortada, sin colores ni pasos ajenos a gitleaks;
gitleaks ya la redacta):

```text
Detect hardcoded secrets.................................................Failed
- hook id: gitleaks
- exit code: 1

Finding:     token = "REDACTED
Secret:      REDACTED
RuleID:      github-pat
File:        o1_secret_test.txt
Line:        1
INF 1 commits scanned.
WRN leaks found: 1

commit exit=1
HEAD unchanged: yes
token present in output: 0
```

**HECHO MEDIDO**, limpieza:

```text
Deleted branch o1-1-secret-test (was 3068eed).
rama local: 0 coincidencias
rama remota: 0 coincidencias
```

**HECHO MEDIDO**, regla de `main`, por la API pública de GitHub (`ruleset_id` 22364974):

| Pregunta | Respuesta | Origen |
|---|---|---|
| ¿Exige pull request? | **Sí**, con 0 aprobaciones y solo método `merge` | API pública |
| ¿Exige checks en verde? | **Sí**: `Lint, types and tests` y `Secret scan (gitleaks)`, con la rama al día | API pública |
| ¿Bloquea force push? | **Sí** (`non_fast_forward`), y también el borrado de la rama | API pública |
| ¿Admite excepciones? | **No: lista vacía** | **Medido por Juan** en GitHub; no es visible por la API anónima |

**HECHO MEDIDO**, CI:

```text
a5d0e79 (push y pull_request): Lint, types and tests  success (x2)
                               Secret scan (gitleaks) success (x2)
4eac05f (merge en main):       Lint, types and tests  success
                               Secret scan (gitleaks) success
```

**HECHO MEDIDO**, sesión de una línea: se abrió en modo `plan` desde la copia aparte con la línea
«Lee docs/orchestration/work/O1.1.md y dime objetivo, exclusiones y paradas.». Su respuesta reprodujo
el objetivo, las exclusiones, las rutas prohibidas, las cuatro condiciones de parada y los cuatro gates
humanos de la especificación. `git status --short` quedó vacío.

## 9. Métricas

| Métrica | Valor | Método |
|---|---|---|
| Archivos del primer PR | 7, con 836 líneas añadidas | `git diff --stat` |
| Hooks activos en el clon | de 0 a 1 | `ls .git/hooks`, sin `.sample` |
| Espera de CI de la rama | 3 consultas, con una por minuto | Bucle de lectura anónima |
| PR #58, de apertura a merge | 5 min 59 s | Marcas de tiempo de la API |
| Longitud de la orden para entregar el bloque | 1 línea | Sesión de una línea |

El ahorro de pasos manuales por bloque **no se midió**. Corresponde a O1.5.

## 10. Aportes de Claude Code

| Sesión | Qué hizo | Quién revisó |
|---|---|---|
| `bb23d2bc-80dc-4076-9953-97eebc08161d` | O1-A, definición de O1.1, todos los documentos, hooks, prueba de bloqueo, commits, push y este cierre | Juan revisó el diff del PR #58 y autorizó cada etapa |
| `a60d8585-5453-4a23-8a6e-c00fa7bff303` | Sesión de prueba en modo plan, abierta por Juan; no modificó archivos | Claude Code comparó su respuesta con la especificación |

Ambos identificadores se verificaron por la existencia de sus transcripciones locales.

## 11. Aportes de Codex

Nada que registrar.

## 12. Operaciones manuales y de PowerShell

Registradas como **medidas por Juan**: revisión de la lista de excepciones de la regla de `main`;
apertura de la sesión de una línea; creación del PR #58 con el enlace rellenado; merge del PR #58.

Ejecutadas por Claude Code fuera del repositorio versionado: creación de `%USERPROFILE%\elsa-o1\` e
instalación de `.git/hooks/pre-commit` en el clon. El hook no se versiona: se revierte con
`pre-commit uninstall`.

## 13. Incidentes

Ningún fallo de seguridad. El secreto falso no se commiteó. Registrado:

1. **Seguimiento de rama.** `git worktree add` dejó la rama siguiendo a `origin/main`. No tuvo efecto:
   el push usó una referencia explícita, y `main` no cambió. La rama de este cierre se dejó sin
   seguimiento antes de publicarla.
2. **Salida de error esperada.** La limpieza terminó con `exit 2` porque su último comando comprobaba
   que el archivo de prueba ya no existía. Es el resultado buscado.
3. **Avisos de fin de línea.** Git avisó de LF a CRLF en la copia de trabajo. Sin efecto en el contenido
   versionado.
4. **Línea repetida.** La transcripción de la sesión de prueba muestra la línea enviada más de una vez.
   No cambió el resultado.
5. **Evidencia no entregada en el mensaje.** Juan confirmó sus acciones sin adjuntar los resultados.
   Claude Code los obtuvo de la API pública y de la transcripción local de esa sesión, y preguntó a Juan
   solo por las excepciones, que no eran legibles.

## 14. Git

Se creó un worktree, dos ramas de contenido y una desechable, sin tocar `main` directamente. Sin force
push ni `reset --hard`. Sí se usó `git branch -d` sobre la rama desechable, que no tenía commits propios.

## 15. Ramas

| Rama | Estado |
|---|---|
| `claude/o1-1-contrato-y-preparacion` | Fusionada por el PR #58 |
| `o1-1-secret-test` | Desechable; borrada; nunca publicada |
| `claude/o1-1-cierre` | Este cierre |

## 16. Commits

| Commit | Contenido |
|---|---|
| `6a9a150` | ADR 0036, manual, plantilla, especificación y enlaces |
| `a5d0e79` | Cierre de O1-A con su auditoría |
| `4eac05f` | Merge del PR #58 en `main` |

El commit de este cierre consta en su propio PR.

## 17. Pull requests

| PR | Estado | CI |
|---|---|---|
| [#58](https://github.com/VallejoOsorio2026/Elsa-ai/pull/58) | Fusionado por Juan | Los dos checks obligatorios en `success` |
| PR de este cierre | Lo crea y fusiona Juan | Debe quedar en verde (ver «Regla de continuidad») |

## 18. Migraciones

No aplica: ninguna escrita ni aplicada.

## 19. Estado operacional final

| Pieza | Estado |
|---|---|
| Contrato de orquestación | **En `main`.** Se usa a mano |
| Escaneo local de secretos | **Activo** en el clon de PC1 |
| Protección de `main` | **Activa y sin excepciones** |
| Ejecutor automático | **No existe** |
| Claude Code sin supervisión | **No ejecutado.** Sigue sin demostrarse |
| ELSA funcional | Sin cambios de código |

**INFERENCIA:** Render despliega desde `main`, así que los merges de este bloque pueden haber disparado
un despliegue sin cambios funcionales. No se verificó en Render.

## 20. Pendientes

| Pendiente | Responsable |
|---|---|
| **PENDIENTE:** aceptar o no el riesgo de aislamiento | Juan, en O1.3 |
| **PENDIENTE:** decidir si el repositorio sigue público | Juan, aparte |
| **PENDIENTE:** revisar si `.env` se sincroniza con la nube | Juan, aparte |
| **PENDIENTE:** sincronizar el `main` local y retirar la copia `o1-1`, tras el merge de este cierre | Claude Code |
| **PENDIENTE:** el resto de O1, de O1.2 a O1.5 | Requiere autorización de Juan (regla 20) |

## 21. Siguiente bloque

**O1.2 — Runner sin Claude y sin push**, si Juan lo autoriza: comprobaciones previas, copia aparte,
control de alcance, pruebas fijas, timeouts e informe, con tests que usen un Claude falso. La regla de
`main` sin excepciones ya elimina el bloqueo previsto para O1.3 por ese lado.

---

## Criterios de cierre

| Criterio de la especificación | Resultado |
|---|---|
| Hook instalado | **Cumplido** |
| Token falso bloqueado, sin entrar al historial ni a la salida guardada | **Cumplido** |
| Rama desechable borrada y nunca publicada | **Cumplido** |
| Commit normal desde la copia aparte | **Cumplido** |
| Regla de `main` registrada en sus cuatro puntos | **Cumplido** |
| Sesión de una línea coincide y `git status` vacío | **Cumplido** |
| Sin rutas personales nuevas y gitleaks en verde | **Cumplido** |
| Checks de CI en verde | **Cumplido** en el PR #58 |
| `main` contiene el contrato y ambos cierres | **Se cumple al fusionar este cierre** |
| `main` limpio y sincronizado | **Se verifica al fusionar este cierre** |

## Regla de continuidad

O1.1 queda cerrado solo cuando este documento esté en `main` con los checks obligatorios en verde. Hasta
entonces no empieza O1.2, y aun después O1.2 requiere autorización explícita de Juan.

## Veredicto

**O1.1 cumple su alcance.** El contrato está versionado, el escaneo local bloquea secretos de forma
demostrada y `main` no admite excepciones. **La automatización sigue sin existir ni demostrarse.**
