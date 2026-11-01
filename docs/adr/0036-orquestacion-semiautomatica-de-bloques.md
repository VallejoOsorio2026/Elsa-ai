# ADR 0036 — Orquestación semiautomática de bloques de trabajo

- Estado: **propuesto**
- Fecha de la decisión: **2026-11-01**
- Bloque: **O1**, incremento **O1.1** (contrato y preparación)
- **Decide**: cómo se especifica un bloque en un archivo versionado, qué estados
  recorre, qué pasos pueden automatizarse, cuáles exigen siempre a una persona y qué
  forma tendría un ejecutor local si llega a construirse
- **No decide**: la implementación del ejecutor. O1.1 no construye ninguno. Su
  continuidad depende de la prueba de O1.3 (§9)
- **No reabre** ninguna decisión de producto. O1 es una herramienta para **desarrollar**
  el proyecto, no una capacidad de ELSA: no se despliega, no atiende a usuarios y no
  cambia `docs/architecture.md`. Los «agentes de IA» que ese documento declara
  inexistentes a propósito siguen sin existir en el producto
- Operación: [`docs/orchestration/README.md`](../orchestration/README.md)
- Evidencia: [`docs/o1-a-auditoria-y-diseno-cierre.md`](../o1-a-auditoria-y-diseno-cierre.md)
- Aplica las reglas **11, 12, 15, 16, 17, 18, 20, 21, 22, 23, 25 y 26** de
  [`CLAUDE.md`](../../CLAUDE.md)

## 1. Contexto

Entre ChatGPT, Claude Code y GitHub, el responsable del proyecto copia prompts y
resultados a mano en cada etapa. La fricción está medida: 5 de los últimos 8 merges
anteriores a este bloque fueron solo de cierre documental, y D2.7 necesitó dos PR de
cierre (#56 y #57).

La auditoría O1-A (2026-11-01) encontró además cuatro condiciones que determinan el
diseño:

1. **El repositorio es público y tiene issues habilitados.** Un push es una publicación,
   y cualquier persona puede escribir un issue o un comentario.
2. **El nodo PC1 corre desde el clon de trabajo.** `Start-ElsaMode.ps1` usa el `.venv` y
   el `.env` de esa carpeta. Cambiar de rama allí altera el código de un nodo en servicio.
3. **`gh` no está instalado**, ni se exige. Git usa el Credential Manager ya presente.
4. **Las reglas eran solo texto.** No había hooks activos en el clon ni permisos en
   `.claude/`. «No hacer merge» dependía de que el asistente lo cumpliera.

## 2. Decisión: la especificación versionada es el contrato de un bloque

Un bloque se describe en `docs/orchestration/work/<id>.md`, según
[`SPEC_TEMPLATE.md`](../orchestration/SPEC_TEMPLATE.md): cabecera YAML con rama, rutas
permitidas y prohibidas, límite de tiempo, paradas y gates humanos, seguida del objetivo y
los criterios de aceptación en texto.

- Se usa **YAML** porque es el formato que ya usan las Skills. PyYAML ya es dependencia de
  desarrollo, así que no se agrega ninguna.
- **Los criterios de aceptación nunca se ejecutan como comandos.** Una especificación es
  texto: lo que se ejecute saldrá de una lista fija en código, no de ella.
- La especificación se versiona en la rama del bloque y llega a `main` con el merge.

## 3. Decisión: Git es la memoria compartida

| Mecanismo | Papel |
|---|---|
| Archivo versionado | Fuente principal: especificación e informe de evidencia |
| Pull request | Revisión humana y CI en un solo lugar |
| Issues y comentarios | **Rechazados como fuente de órdenes.** Son datos de terceros (regla 8 de [`MCP_POLICY.md`](../agentic-tooling/MCP_POLICY.md)) |

No se agrega base de datos ni servicio residente. ChatGPT aprovecha el acceso a GitHub si
lo tiene; si no, se le pega un solo archivo. Ningún paso depende de esa integración.

## 4. Decisión: cinco estados

| Estado | Significado | Quién lo cambia |
|---|---|---|
| `READY` | Especificación revisada | **Una persona** la aprueba |
| `RUNNING` | Trabajo y verificación en curso | El ejecutor |
| `BLOCKED` | Error, timeout, fuera de alcance o bloqueo declarado | El ejecutor; **una persona** decide |
| `PR_READY` | Rama publicada, CI leído, enlace de PR listo | El ejecutor |
| `CLOSED` | PR fusionado y cierre en `main` | **Una persona** hace el merge |

El estado se deduce de Git, del informe y del PR. No se mantiene un archivo de estado
aparte, porque se desactualizaría.

## 5. Decisión: lo que nunca se automatiza

Merge, deploy, force push, `reset --hard` y borrados destructivos; migraciones, Render y
Supabase; SAP real, secretos, red y firewall, instalación de programas; pruebas físicas;
ampliar el alcance, avanzar al bloque siguiente, aprobar una especificación o cambiar la
arquitectura.

Ante cualquiera de ellos el trabajo se detiene y queda en manos de una persona.

## 6. Decisión: el trabajo ocurre en una copia aparte

Los bloques ejecutados por este mecanismo trabajan en un `git worktree` dentro de
`%USERPROFILE%\elsa-o1\worktrees\`, fuera del clon y fuera de OneDrive. Es un cambio
aprobado respecto a «solo dentro del repositorio»: es el mismo repositorio, con otra
carpeta de trabajo.

Motivos:

- no toca el código desde el que corre el nodo PC1;
- no contiene `.env` ni datos reales, porque Git no los versiona;
- no sufre bloqueos de sincronización de OneDrive.

## 7. Decisión: el PR se crea con un clic

No se guarda ningún token en PC1 para crear pull requests. El flujo termina con un enlace
`compare/main...<rama>?expand=1` ya rellenado, y la persona responsable lo crea. Es un paso
manual aceptado a cambio de no tener una credencial más, y sirve de control humano.

## 8. Decisión: el escaneo local de secretos es condición previa

Como un push es una publicación, gitleaks debe bloquear **antes** del push, no solo en CI.
Los hooks de pre-commit quedan activos en el clon de PC1. Ningún ejecutor puede publicar
sin ese escaneo.

## 9. Forma prevista del ejecutor, no construida

Si O1 continúa, el ejecutor sería un script local de un solo uso: una orden, un bloque, y
termina. Se justifica porque una instrucción a un modelo no garantiza timeouts ni que se
revise a sí mismo. Comprobaría el estado de Git, crearía la copia aparte, invocaría a Claude
Code con permisos prohibitivos por defecto, verificaría el diff contra las rutas
permitidas, correría pruebas fijas, escanearía secretos, publicaría solo su rama y se
detendría. No tendría ningún camino de merge.

**Esto es diseño, no capacidad.** El modo sin supervisión de Claude Code solo se verificó en
su `--help`; no se ejecutó. Su ayuda advierte además que, en ese modo, un archivo de
configuración inválido se ignora en silencio. **O1.3 es el punto de decisión:** si no se
demuestra que merge, push, lectura de `.env` y edición externa quedan bloqueados, O1 se
detiene y se conserva solo lo construido hasta entonces.

## 10. Consecuencias

- Un bloque se puede entregar con una línea que apunte a su especificación.
- `docs/orchestration/` pasa a formar parte de lo que hay que entender al recibir el
  proyecto.
- Los commits hechos en el clon de PC1 pasan por los hooks. Un autoformato puede abortar un
  commit: se vuelve a hacer `git add` y se repite. Se revierte con `pre-commit uninstall`.
- Continúa el patrón de dos PR por bloque: uno de contenido y otro de cierre, porque el
  cierre debe citar el número y el CI del primero.

## 11. Riesgos residuales

| Riesgo | Situación |
|---|---|
| Sin aislamiento real: los tests corren con el usuario de Windows y podrían alcanzar otros archivos o credenciales | **Pendiente de aceptación explícita en O1.3.** No aplica a O1.1, que no ejecuta nada sin supervisión |
| La protección de `main` podría admitir excepciones | Debe revisarla la persona responsable en GitHub. Si las admite, bloquea O1.3 |
| La lectura anónima de CI depende de que el repositorio sea público | Si pasa a privado, el resultado de CI se consulta en el PR. La visibilidad se decide aparte |

## 12. Fuera de esta decisión

El ejecutor y sus tests, la configuración sin supervisión, el ajuste de la Skill
`elsa-release`, la visibilidad del repositorio y cualquier cambio en `CLAUDE.md`, `ci.yml`,
Render o Supabase.
