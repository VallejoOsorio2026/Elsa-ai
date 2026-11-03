# Cierre de O1.3.R1.0 — Autorización de un uso para el repositorio real

**Esto cierra solo el subbloque O1.3.R1.0.** No cierra O1.3, ni ejecuta `O1.3.R1`, ni abre O1.4.

Las marcas son las de [`BLOCK_CLOSURE_STANDARD.md`](project/BLOCK_CLOSURE_STANDARD.md).

## 1. Objetivo

Que el runner pueda abrir el repositorio real `VallejoOsorio2026/Elsa-ai` al ejecutor Claude real **para un
único run documental previamente aprobado**, sin dejar de rechazarlo por defecto. Es el «gate humano y cambio
deliberado» que exigía el [ADR 0037](adr/0037-limites-del-ejecutor-claude-real.md), §9.

## 2. Alcance

**Dentro:**

- Autorización de un solo uso en `scripts/orchestrator.py`.
- Tests sin Claude real.
- ADR 0037, `docs/orchestration/README.md` y `docs/orchestration/work/O1.3.md`.
- Este documento.

**Fuera:**

- Ejecutar `O1.3.R1` o cualquier run real.
- Push, PR o merge desde el runner.
- Exponer el ejecutor real en la consola.
- O1.4.
- Corregir las 3 pruebas de Windows.
- `src/`, CI, dependencias, Render, Supabase, SAP y migraciones.

## 3. Estado inicial

- **HECHO MEDIDO.** `main` limpio, con `HEAD = origin/main = c8c1a93ade7fa4c8913a08610e591b11990bfa85`: el
  merge del PR #63, O1.3.5.
- **HECHO MEDIDO.** El primer intento de `O1.3.R1` se detuvo en su Fase B, antes de crear nada. Al ejecutar
  solo la barrera con la configuración por defecto se obtuvo:

  ```text
  guard: real_repo_not_authorized ''
  ```

  Claude no se lanzó. No se creó spec, copia, rama ni commit, y hay 0 archivos cambiados.
- **HECHO DEL REPOSITORIO.** `ensure_not_real_repository` rechazaba siempre el repositorio real. Lo hacía al
  principio de `_pipeline` y otra vez en `run_claude_executor`.

## 4. Trabajo realizado

1. **Auditoría y diseño, aprobados por Juan** («Aprobado, implementa»).
2. **`RealRunAuthorization` y su carga estricta** (`load_real_run_authorization`):
   - lista cerrada de campos, cada uno con su tipo exacto;
   - claves repetidas rechazadas;
   - máximo 4 KB;
   - sin enlaces.
3. **Comparación exacta con lo que valida el runner** (`authorize_real_run`): bloque, base, huella de la
   especificación, rama, rutas en su orden, ejecutor real sin prefijo y rutas que no existan en la base.
4. **Remoto exacto en modo autorizado** (`check_real_repository_access`): la configuración y cada URL de
   lectura y de envío deben ser `EXPECTED_ORIGIN`. Sin autorización, se llama a `ensure_not_real_repository`,
   que se conserva.
5. **Un solo uso** (`consume_real_run_authorization`): el archivo se mueve a `state/authorizations-used/`
   después de aprobar y antes de crear la copia.
6. **Comprobación de destino que no confía en quien llama** (`check_authorized_target`). Antes de cualquier
   proceso de Claude exige:
   - que la autorización coincida y que el archivo gastado sea el suyo;
   - que se trabaje en la copia del bloque, nunca en el clon principal;
   - que la copia esté en la rama autorizada;
   - que `HEAD` sea el commit de la especificación, que ese commit solo traiga la especificación y que su
     padre sea la base.
7. **Cambios exactos** (`check_authorized_changes`): las rutas autorizadas, todas nuevas.
8. **Foto de la bandeja y de las autorizaciones** (`runner_folders_snapshot`), comparada en todo run del
   ejecutor real, también tras una parada.
9. **Documentación** y dos revisiones de seguridad, con sus hallazgos corregidos.

## 5. Decisiones

| Decisión | Quién y por qué |
|---|---|
| **DECISIÓN TOMADA:** autorización en archivo externo, de un solo uso, no un interruptor | Juan aprobó el diseño. Una especificación sola no basta, y `allow_real_repo = true` quedó descartado de forma expresa |
| **DECISIÓN TOMADA:** sin firma criptográfica | Lo más simple que cumple. Quien tenga el usuario de Windows ya podría inyectar el ejecutor por código. Registrado como riesgo en el ADR 0037, §11 |
| **DECISIÓN TOMADA:** se gasta antes de crear la copia | Una parada posterior no deja la autorización reutilizable. Reintentar exige un identificador nuevo |
| **DECISIÓN TOMADA:** en modo autorizado, el remoto debe ser literalmente `EXPECTED_ORIGIN` | Normalizar sirve para rechazar, no para permitir. Hallazgo de la primera revisión de seguridad |
| **DECISIÓN TOMADA:** se actualiza el ADR 0037 en vez de crear otro | Su propio §9 preveía este cambio, y el ADR sigue en estado `propuesto` |
| **DECISIÓN TOMADA:** los tests hacen del sandbox el repositorio real cambiando solo `EXPECTED_ORIGIN` en el test | Así nunca se lanza el Claude real. Un control de importación liga `REAL_REPOSITORY` a `EXPECTED_ORIGIN` |

## 6. Pruebas

Todo **HECHO MEDIDO**, en Windows, en la copia del bloque:

- Una selección por palabras clave de 76 tests, sobre el árbol de `4f06a9e`: 44 de los 53 tests nuevos de
  R1.0 y 32 que ya existían. Los 53 nuevos corrieron todos en la pasada de los tests del runner.
- Todos los tests del runner, sobre `4f06a9e`: `test_orchestrator.py`, `test_orchestrator_claude.py`,
  `test_orchestrator_integration.py`, `test_orchestrator_rehearsal.py` y `test_orchestrator_claude_live.py`,
  que se omite sin `ELSA_O1_CLAUDE_LIVE=1`.
- La suite completa con las 3 omisiones aprobadas, sobre `cef1f6f`. El último commit de código, `4f06a9e`,
  solo cambia el runner y sus tests, y esos sí corrieron sobre él.
- `ruff check`, `ruff format --check`, `mypy --platform linux`, pre-commit con gitleaks y `git diff --check`.
- `security-reviewer`, dos pasadas: la primera sobre el diff sin commitear, la segunda sobre `9222af1..cef1f6f`.

## 7. Comandos relevantes

```bash
python -m pytest -q tests/test_orchestrator.py tests/test_orchestrator_claude.py tests/test_orchestrator_integration.py tests/test_orchestrator_rehearsal.py tests/test_orchestrator_claude_live.py
```

```bash
python -m mypy --platform linux
```

La suite completa se lanzó con `--deselect` de cada prueba de `WINDOWS_KNOWN_TEST_FAILURES`.

## 8. Resultados

```text
selección ejecutada (4f06a9e): 76 passed, 367 deselected, 2 warnings in 127.81s
tests del runner (4f06a9e):   860 passed, 11 skipped, 2 warnings in 1464.59s (0:24:24)
suite completa   (cef1f6f):   3002 passed, 242 skipped, 3 deselected, 3 warnings in 1684.49s (0:28:04)
mypy --platform linux:        Success: no issues found in 263 source files
ruff check:                   All checks passed!
git diff --check origin/main..HEAD: sin salida
```

**Revisiones de seguridad:**

| Pasada | Veredicto | Hallazgos | Qué se hizo |
|---|---|---|---|
| Primera | PASS | 1 importante y 6 menores | Corregidos en `cef1f6f` y `4f06a9e` |
| Segunda | PASS | 4 menores | Corregidos en `4f06a9e` |

## 9. Métricas

- **HECHO MEDIDO.** El diff de código de los tres commits es `scripts/orchestrator.py` y dos archivos de
  tests.
- **HECHO MEDIDO.** R1.0 añade 27 funciones de test, que dan 53 tests nuevos al recolectarlos. La selección
  ejecutada tiene 76 tests: 44 de esos 53 y 32 que ya existían. Los 53 corrieron en los tests del runner,
  sobre `4f06a9e`.
- **HECHO MEDIDO.** 0 ejecuciones del Claude real en este bloque y 0 llamadas al modelo desde el runner.

## 10. Aportes de Claude Code

Una sesión de Claude Code en la app de escritorio, con identificador `6db3917e-6734-4a42-a00c-505c8becaa1a`.
Ese identificador aparece en las rutas de la propia sesión, así que es verificable. La sesión hizo:

- la auditoría y el diseño;
- la implementación y los tests;
- la documentación;
- la ejecución de los controles.

Dos subagentes `security-reviewer` revisaron el cambio. Los hallazgos los corrigió la sesión, y Juan aprobó el
diseño.

## 11. Aportes de Codex

Nada que registrar.

## 12. Operaciones manuales y de PowerShell

- **HECHO MEDIDO.** Las únicas operaciones fuera del repositorio fueron la lectura de la barrera del primer
  intento de `O1.3.R1` y la ejecución local de pruebas.
- No se creó ninguna autorización real, ni se escribió en `%USERPROFILE%\elsa-o1\authorizations\`.

## 13. Incidentes

- **El primer intento de `O1.3.R1` quedó bloqueado por diseño.** Es la razón de este bloque.
- **Una prueba con fallos de mi helper.** La primera versión de un helper de tests no conocía la nueva
  exigencia de huella del archivo gastado. Se corrigió antes del commit.
- **Una suite parada a tiempo.** Una suite lanzada sobre un árbol ya superado se detuvo y se relanzó.
- Ningún fallo de seguridad.

## 14. Git

Cambios solo en la rama del bloque. `main` sin tocar.

## 15. Ramas

`claude/o1-3-r1-0-real-repo-authorization`, desde `c8c1a93`, en `%USERPROFILE%\elsa-o1\worktrees\o1-3-r1-0-auth`.

## 16. Commits

| Hash | Mensaje |
|---|---|
| `9222af1` | feat(orchestration): authorize one real-repository run explicitly |
| `cef1f6f` | docs(adr): open the real repository by single-use authorization in ADR 0037 |
| `4f06a9e` | fix(orchestration): bind the spent authorization and the spec commit |
| Este | El documento de cierre |

## 17. Pull requests

**PENDIENTE.** Lo abre Juan. El resultado de CI de la rama se verá en el PR.

## 18. Migraciones

Nada que registrar.

## 19. Estado operacional final

- **HECHO DEL REPOSITORIO.** El repositorio real sigue cerrado por defecto.
- **HECHO DEL REPOSITORIO.** Con una autorización exacta, el runner puede llegar a `verified_local` con un
  único archivo documental nuevo. Medido en el sandbox, que hace de repositorio real, con Claude falso.
- **HECHO DEL REPOSITORIO.** No hay ninguna autorización creada para el repositorio real.

## 20. Pendientes

Antes de repetir `O1.3.R1`, **PENDIENTE**, todo con decisión de Juan:

- **Integrar este PR.** La base de `O1.3.R1` será el SHA de `main` posterior a ese merge, no `c8c1a93`.
- **Revisar los criterios de `O1.3.R1`:**
  - el runner deja 3 commits: especificación, contenido y evidencia;
  - solo el de contenido lleva el archivo autorizado;
  - el runner no hace push, así que el push de la rama lo hace el operador después de `verified_local`.
- **Escribir la especificación y la autorización exacta para esa base.** El id `O1.3.R1` sigue sin gastar:
  el primer intento no creó ninguna autorización.
- **Confirmar** que la cuenta no pertenece a una organización con configuración administrada remota, y que
  Claude Code sigue en 2.1.316.

## 21. Siguiente bloque

`O1.3.R1`, el primer run real documental, sobre la nueva base y con autorización de un uso. Después, el cierre
de O1.3.
