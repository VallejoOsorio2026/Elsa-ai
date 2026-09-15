# Cierre del subbloque 5.0.a — Diseño normativo y arquitectura del Piloto 0.1

Documento de cierre redactado según
[el estándar de cierre de bloques](project/BLOCK_CLOSURE_STANDARD.md)
(`CLAUDE.md`, regla 26). **Es la primera aplicación de ese estándar.**

> **Qué cierra este documento y qué no.**
>
> Cierra **únicamente** el trabajo de definición: ADR 0020, contrato funcional
> del Piloto 0.1, manual del observador y estándar de cierre, culminado en el
> pull request #19.
>
> **NO** cierra el Bloque 5.0 completo. **NO** declara el Piloto 0.1 operativo.
> **NO** declara Materiales integrado. **NO** declara datos reales cargados.
> Nada de eso existe todavía (§19).

Marcas de evidencia usadas, según el estándar: **HECHO MEDIDO**, **HECHO DEL
REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.

---

## 1. Objetivo

Dejar fijada, por escrito y versionada, la arquitectura de **capacidades
componibles y planes de ejecución controlados** con la que ELSA responderá
preguntas que cruzan el BOM de Ingeniería con el inventario de Materiales, y
el contrato funcional del Piloto 0.1 que se construirá sobre ella.

El objetivo era **normativo, no funcional**: al terminar debía existir una
decisión arquitectónica revisable y un contrato de alcance, no una capacidad
ejecutable.

---

## 2. Alcance

### Entró

- ADR 0020 — capacidades componibles y planes de ejecución controlados.
- Contrato funcional del Piloto 0.1.
- Manual del observador (fuente canónica de la guía del piloto).
- Estándar obligatorio de cierre de bloques.
- Regla 26 en `CLAUDE.md`, que obliga a cumplir ese estándar.

### Quedó explícitamente fuera

- Toda implementación de código.
- Toda migración de esquema.
- Cualquier cambio en el repositorio de Materiales.
- Cualquier avance en el hilo de ONNX/INT8.
- El cierre de los puntos M1–M8 del contrato con Materiales.
- La carga de datos reales de Tampella.

---

## 3. Estado inicial

**HECHO DEL REPOSITORIO.** Punto de partida: `origin/main` en
`bd1c09bef81c1792fcf0df027a897cfcfed636e2`
(«Merge pull request #18 … docs/adr-0019-vector-space-identity»).

Lo que **existía** al empezar:

- `QuerySignals` / `detect_signals` (`src/elsa/core/query_signals.py`).
- Recuperación literal sobre conocimiento estructurado
  (`src/elsa/core/retrieval.py`).
- `HybridRetrievalService` (`src/elsa/services/hybrid_retrieval.py`) con los
  tres canales y fusión RRF.
- `GroundedGenerationService` (`src/elsa/services/grounded_generation.py`) con
  los cuatro estados de respuesta de `src/elsa/core/answers.py`.
- Modelo estructurado de BOM, AMEF y snapshots de SAP en
  `src/elsa/ports/knowledge.py`.
- Autorización default-deny en `src/elsa/core/authorization.py` y la cadena de
  confianza de `src/elsa/api/deps.py`.
- `MaterialsPort` y `MaterialsIdentityPort` como puertos **separados**, el
  primero solo con adaptador fake.
- ADR 0001 a 0019.

Lo que **no** existía:

- Ningún concepto de capacidad, plan de ejecución, orquestador ni router.
- Ningún adaptador real de `MaterialsPort`.
- Ninguna composición entre dos fuentes de verdad distintas.
- Ninguna procedencia por hecho o por campo.
- Ningún mecanismo de reporte de respuestas ni de incidentes.
- Ninguna regla de cierre de bloques en el repositorio.

---

## 4. Trabajo realizado

En orden:

1. **Auditoría del estado real.** Inspección del repositorio para clasificar
   cada pieza como implementada, parcial, planificada o inexistente, sin
   asumir la existencia de un router de capacidades.
2. **Inspección de Materiales en solo lectura.** Clon de
   `VallejoOsorio2026/papelsa-asistente-materiales` **fuera del árbol de
   ELSA**, sin modificarlo, para conocer su contrato real en vez de
   inventarlo.
3. **Primer borrador** de definición de capacidad, tipos de consulta, plan de
   ejecución, procedencia, autorización y observabilidad, entregado en
   conversación para revisión.
4. **Segunda ronda**, incorporando las decisiones D11–D19 y las correcciones
   sobre intención frente a pertenencia al BOM, autorización por capacidad,
   feedback como bloqueante, incident snapshot y tres niveles de
   observabilidad.
5. **Tercera ronda**, incorporando D21–D24 y M8, con la regla de vigencia
   reescrita sobre `requires_fresh_inventory`.
6. **Materialización documental** de los cuatro archivos y de la regla 26.
7. **Validación, commit, pull request #19 y merge.**

---

## 5. Decisiones

### 5.1 Decisiones de sesión D11–D24

Todas son **DECISIÓN TOMADA** por el responsable del proyecto durante la
conversación de este subbloque.

| Id | Decisión | Motivo |
|---|---|---|
| **D11** | Una consulta directa a Materiales **no requiere alcance sobre activos de ELSA**. Basta cuenta ELSA activa, JWT válido y perfil activo en Materiales. **No habilita acceso al BOM.** | Materiales no tiene alcances y ese usuario ya puede entrar allí directamente. Negarlo sería teatro de seguridad, pero dejarlo sin escribir sería un malentendido peligroso |
| **D12** | La vigencia **no crea un `AnswerStatus` nuevo**. Si la respuesta requiere inventario fresco y la vigencia no se puede verificar: `PARTIAL` + `inventory_freshness_unknown` | Multiplicar estados no añade información; un campo de procedencia y un aviso lo expresan mejor |
| **D13** | La interfaz usa un `response_ref` interno para anclar «Reportar respuesta». **No se muestran UUID técnicos al usuario normal** | Respeta la regla ya vigente de no exponer identificadores internos en la experiencia normal |
| **D14** | El Incident Snapshot exige **persistencia versionada** antes del primer tester | Un snapshot en memoria se pierde al reiniciar, que es justo lo contrario de su motivo de existir |
| **D15** | Incident Snapshot y aportes permanecen **separados**. El snapshot es estable y append-only. **Incident Management queda fuera** del Piloto 0.1 inicial | Un aporte pasa por revisión y puede publicarse; un incidente ni se revisa ni se publica. Dos ciclos de vida distintos |
| **D16** | **Ampliar `MaterialsPort`** para la consulta factual de inventario. `MaterialsIdentityPort` permanece **separado** | Es la misma fuente externa, pero son dos superficies distintas; mezclarlas confundiría identidad con inventario |
| **D17** | La **medición real de códigos SAP** precede a la normalización definitiva, a la unión BOM ↔ Materiales y al adaptador de inventario | Si las dos representaciones difieren, el caso central falla en silencio y cae a búsqueda por parecido sobre un número |
| **D18** | Contrato funcional canónico en `docs/piloto-0-1/contrato-funcional.md` | El directorio alojará después el resto de documentos del piloto |
| **D19** | Regla de cierre obligatoria para cada bloque y subbloque | El proyecto se entrega a PAPELSA; una conversación no es documentación |
| **D19-bis** | Fuente canónica en `docs/project/BLOCK_CLOSURE_STANDARD.md`; `CLAUDE.md` obliga a cumplirla | Separa la regla (breve, en el contrato) del procedimiento (extenso, en `docs/`) |
| **D20** | La **retención del Incident Snapshot permanece ABIERTA**. Es **puerta previa a liberar** antes del primer tester | No hay evidencia para fijar un número de días, pero liberar sin política sería acumular datos sin criterio |
| **D21** | Mientras M8 esté abierto: consulta directa + Materiales responde correctamente + código no devuelto → **`NO_EVIDENCE` + `code_not_found_in_source`**. **No afirmar «el material no existe»** | `PARTIAL` no corresponde cuando no hay ninguna otra parte factual resuelta |
| **D22** | `requires_fresh_inventory` es una **propiedad determinista del plan o plantilla**. La vigencia depende del **hecho utilizado**, no de haber ejecutado Materiales | Derivarla de «se ejecutó la capacidad» degradaría respuestas que no afirman nada temporal |
| **D23** | Protocolo M3: BOM real de Tampella, mínimo 30 códigos distintos, todas las hojas o secciones aplicables, todos si hay menos de 30, incluir todos los patrones observados, **primera comparación sin normalización nueva** | Aplicar normalización antes de medir ocultaría el problema que se está midiendo |
| **D24** | Fuente canónica del manual en `docs/piloto-0-1/manual-del-observador.md`, **siempre accesible desde ELSA** durante el piloto | Evita que un manual documental y otro de interfaz evolucionen por separado |

### 5.2 Decisiones arquitectónicas centrales

**DECISIÓN TOMADA**, registrada además como ADR 0020 (regla 25):

- ELSA **no** será únicamente un RAG documental.
- ELSA podrá **orquestar capacidades componibles**.
- **No** se construirá un agente autónomo de herramientas ilimitadas.
- Los planes del Piloto 0.1 serán **cerrados, enumerables y auditables**.
- El **LLM no decide relaciones SAP**.
- **BOM/IH06** demuestra la relación activo → componente/material.
- **Materiales** demuestra la información factual de inventario.
- **Manuales y documentos** demuestran los hechos técnicos.
- La **procedencia se conserva por hecho y por campo**.
- **Un hecho sin procedencia válida no se emite.**
- La **autorización ocurre antes** de recuperar información protegida.
- `resolve_asset` **no puede divulgar** activos fuera del universo autorizado.
- Materiales **no recibe** la pregunta completa, los alcances de ELSA ni
  contexto que no necesite.
- Los **resultados parciales no se ocultan**.
- Se conservan `ANSWERED`, `PARTIAL`, `NO_EVIDENCE` y `ERROR`.
- **«No encontrado» no equivale automáticamente a «no existe».**
- El Piloto 0.1 **puede iniciar sin ONNX, INT8 ni Phi** para las relaciones
  estructuradas.
- **Phi no determina** códigos, stock ni pertenencia a activos.

### 5.3 Feedback y observabilidad

**DECISIÓN TOMADA.** Antes del primer tester deben existir:

- «Reportar respuesta»;
- campo de texto libre inmediato, sin categorías obligatorias previas;
- observabilidad mínima;
- Incident Snapshot;
- manual del observador.

El tester describe el síntoma **con sus propias palabras**. El sistema conserva
automáticamente evidencia suficiente para reconstruir:

```text
pregunta → autorización → plan → capacidades → resultados → procedencia
        → composición → respuesta → latencias → error si ocurrió
        → comentario del tester
```

Tres niveles **separados**, que no se mezclan:

1. auditoría de seguridad;
2. telemetría operativa;
3. Incident Snapshot.

**No se guardan deliberadamente**: JWT, tokens, contraseñas, claves, cabeceras
sensibles ni datos fuera de los permisos del usuario.

---

## 6. Pruebas

**HECHO MEDIDO.** Todo lo de esta sección se ejecutó y se observó su salida.

### Enlaces relativos

Script propio sobre los cinco archivos del cambio:

- **22 enlaces comprobados**
- **0 rotos**

### pre-commit

Sobre los archivos del cambio. **Código de salida 0.**

| Hook | Resultado |
|---|---|
| trim trailing whitespace | Passed |
| fix end of files | Passed |
| check for merge conflicts | Passed |
| check for added large files | Passed |
| detect private key | Passed |
| ruff format | Passed |
| Detect hardcoded secrets (gitleaks) | Passed |
| check yaml, check toml, ruff check | Skipped — no aplicaban a un cambio documental |

### pytest enfocado

- **61 passed**, 2 warnings, **1.32 s**
- Archivos: `tests/test_web_static.py`, `tests/test_gitignore.py`
- Criterio de selección: `test_web_static.py` usa `CLAUDE.md` como objetivo de
  *path traversal* y era el único test con dependencia real del archivo
  modificado.

### Qué NO se ejecutó, y por qué

**No se ejecutó la suite completa. No se ejecutó `mypy`. No se ejecutaron las
pruebas que requieren PostgreSQL.**

No eran necesarias: el cambio fue **exclusivamente documental**, sin un solo
archivo `.py` ni de `supabase/`. La estrategia de pruebas del proyecto fija esa
proporcionalidad para cambios en `docs/`. Ningún test se omitió en silencio.

### CI del pull request #19

**HECHO MEDIDO**, sobre `688a69b0…`:

| Check | Conclusión |
|---|---|
| Lint, types and tests | **success** |
| Secret scan (gitleaks) | **success** |

El run del push anterior a la apertura del PR terminó también con **ambos jobs
en success**.

---

## 7. Comandos relevantes

Lo que otra persona necesitaría para reproducir la verificación:

```bash
# Verificaciones locales
uv run pre-commit run --files CLAUDE.md \
  docs/adr/0020-capacidades-componibles-y-planes-de-ejecucion.md \
  docs/piloto-0-1/contrato-funcional.md \
  docs/piloto-0-1/manual-del-observador.md \
  docs/project/BLOCK_CLOSURE_STANDARD.md

uv run pytest tests/test_web_static.py tests/test_gitignore.py -q

# Comprobación del alcance del diff, antes de abrir el PR
git diff --name-only origin/main...HEAD
git diff --stat origin/main...HEAD

# Comprobación del merge, después
git diff --stat bd1c09b d05aab1
git log -1 --format="%H%n%P" origin/main
```

---

## 8. Resultados

Salida real, sin parafrasear.

`git diff --stat bd1c09b d05aab1`:

```text
 CLAUDE.md                                          |   3 +
 ...apacidades-componibles-y-planes-de-ejecucion.md | 541 +++++++++++++++++++++
 docs/piloto-0-1/contrato-funcional.md              | 307 ++++++++++++
 docs/piloto-0-1/manual-del-observador.md           | 206 ++++++++
 docs/project/BLOCK_CLOSURE_STANDARD.md             | 114 +++++
 5 files changed, 1171 insertions(+)
```

`uv run pytest tests/test_web_static.py tests/test_gitignore.py -q`:

```text
61 passed, 2 warnings in 1.32s
```

`uv run pre-commit run --files …`:

```text
trim trailing whitespace.................................................Passed
fix end of files.........................................................Passed
check yaml...........................................(no files to check)Skipped
check toml...........................................(no files to check)Skipped
check for merge conflicts................................................Passed
check for added large files..............................................Passed
detect private key.......................................................Passed
ruff check...........................................(no files to check)Skipped
ruff format..............................................................Passed
Detect hardcoded secrets.................................................Passed
exit=0
```

`git log -1 --format="%H%n%P" origin/main`:

```text
d05aab1ce7728858262be2a099f15dad266bff7f
bd1c09bef81c1792fcf0df027a897cfcfed636e2 688a69b061786eac4441958512ac84dbc0398f62
```

---

## 9. Métricas

**HECHO MEDIDO.** Cifras y el método por el que se obtuvieron.

| Métrica | Valor | Método |
|---|---|---|
| Archivos cambiados | 5 | `git diff --stat bd1c09b d05aab1` y la API del PR, por separado |
| Líneas insertadas | 1171 | ídem |
| Líneas borradas | 0 | ídem |
| ADR 0020 | 541 líneas | `git show origin/main:… \| wc -l` |
| Contrato funcional | 307 líneas | ídem |
| Manual del observador | 206 líneas | ídem |
| Estándar de cierre | 114 líneas | ídem |
| Regla añadida a `CLAUDE.md` | 3 líneas | `git diff --stat` |
| Enlaces relativos comprobados | 22, 0 rotos | script propio |
| Tests ejecutados | 61 passed en 1.32 s | `uv run pytest` |
| Checks de CI en verde | 2 de 2 | API de check runs sobre `688a69b0…` |
| Commits del subbloque | 1 | `git log origin/main..HEAD` antes del merge |

No hay métricas de rendimiento, latencia ni calidad de respuesta: **no se
ejecutó ninguna capacidad**, porque ninguna existe todavía.

---

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO.**

- Auditoría del estado real del repositorio contra las capacidades pedidas.
- Inspección en **solo lectura** del repositorio de Materiales, clonado fuera
  del árbol de ELSA y no modificado.
- Redacción de los cuatro documentos y de la regla 26.
- Ejecución de las verificaciones de §6.
- Commit, apertura del pull request #19 y merge.

**Revisión.** Cada borrador se entregó en conversación **antes** de escribir un
archivo, y el responsable del proyecto lo revisó y corrigió en tres rondas. Las
correcciones que cambiaron el resultado fueron: intención frente a pertenencia
al BOM, autorización por capacidad, feedback y manual como bloqueantes, el
Incident Snapshot como registro propio, los tres niveles de observabilidad, la
semántica de ausencia (M8) y la regla de vigencia sobre
`requires_fresh_inventory`.

**Inconsistencias reportadas por Claude Code antes de escribir código**
(regla 19), todas confirmadas y resueltas:

1. El Incident Snapshot no tenía dónde vivir: el único precedente de
   persistencia de contenido de usuario es en memoria. Resuelto por D14.
2. «Reportar respuesta» no tenía a qué anclarse: la respuesta del asistente no
   lleva identificador, y el de petición no está expuesto vía CORS. Resuelto
   por D13.
3. Tensión aparente entre la vigencia y «no crear estados nuevos». Resuelta por
   D12 y luego precisada por D22.
4. La telemetría operativa es el instrumento que hace decidible el punto M2.
5. Una consulta directa a Materiales no tiene alcance de ELSA que autorizar.
   Resuelto por D11.

---

## 11. Aportes de Codex

**Nada que registrar.** Codex no participó en este subbloque.

---

## 12. Operaciones manuales y de PowerShell

**Nada que registrar.** No se ejecutó ningún script de PowerShell, ningún
comando fuera del repositorio, ninguna comprobación en un panel y ningún
servicio local. El subbloque fue exclusivamente documental.

---

## 13. Incidentes

Sin incidentes que afectaran al resultado. Se registran dos observaciones
menores, por transparencia:

1. **`get_status` de la API de GitHub devolvió `pending` con `total_count: 0`**
   cuando los check runs ya estaban en `success`. **HECHO MEDIDO.** Es la API
   antigua de *commit statuses*, que este repositorio no usa: trabaja con
   *check runs*. Lo confirmó `mergeable_state: clean`. No bloqueó nada y no
   requirió acción.
2. **No existe plantilla de pull request** en el repositorio. **HECHO DEL
   REPOSITORIO.** Se comprobaron las cuatro rutas habituales y
   `.github/PULL_REQUEST_TEMPLATE/`. La descripción del PR se redactó
   libremente.

---

## 14. Git

**HECHO DEL REPOSITORIO.**

| Concepto | Valor |
|---|---|
| Base previa de `main` | `bd1c09bef81c1792fcf0df027a897cfcfed636e2` |
| Commit documental | `688a69b061786eac4441958512ac84dbc0398f62` |
| Método de integración | **merge commit** — no squash, no rebase |
| Merge commit | `d05aab1ce7728858262be2a099f15dad266bff7f` |
| Padre 1 | `bd1c09bef81c1792fcf0df027a897cfcfed636e2` |
| Padre 2 | `688a69b061786eac4441958512ac84dbc0398f62` |
| Nuevo `HEAD` de `origin/main` | `d05aab1ce7728858262be2a099f15dad266bff7f` |
| Diff efectivo | 5 archivos, 1171 inserciones, 0 borrados |

Archivos incorporados a `main`:

- `CLAUDE.md`
- `docs/adr/0020-capacidades-componibles-y-planes-de-ejecucion.md`
- `docs/piloto-0-1/contrato-funcional.md`
- `docs/piloto-0-1/manual-del-observador.md`
- `docs/project/BLOCK_CLOSURE_STANDARD.md`

Ningún archivo adicional entró. El alcance se verificó **dos veces por vías
independientes**: con `git diff --name-only` antes de abrir el PR, y con la
lista de archivos de la API del PR después.

---

## 15. Ramas

| Rama | Papel | Estado |
|---|---|---|
| `claude/adr-0020-capacidades-componibles` | Rama de trabajo del subbloque | Fusionada en `main`; **no borrada** |
| `claude/keen-curie-2xeh0r` | Hilo ONNX, ajeno a este subbloque | **Intacta**, en `61b3b428b214de805d23ad12571e26fa87f2825a` |

**HECHO MEDIDO.** La rama ONNX se verificó con `git ls-remote` al empezar, al
terminar el commit, al abrir el PR, tras el merge y al redactar este cierre:
el mismo hash en las cinco comprobaciones. **El trabajo de ONNX permanece
independiente y este subbloque no lo tocó.**

---

## 16. Commits

| Hash | Fecha (UTC) | Asunto |
|---|---|---|
| `688a69b061786eac4441958512ac84dbc0398f62` | 2026-09-15T18:13:15Z | `docs: add ADR 0020, pilot 0.1 contract and block closure standard` |
| `d05aab1ce7728858262be2a099f15dad266bff7f` | 2026-09-15T18:29:36Z | `Merge pull request #19 from VallejoOsorio2026/claude/adr-0020-capacidades-componibles` |

---

## 17. Pull requests

| | |
|---|---|
| Número | **#19** |
| URL | <https://github.com/VallejoOsorio2026/Elsa-ai/pull/19> |
| Título | `docs: define arquitectura y contrato del Piloto 0.1` |
| Estado | `closed`, **merged** |
| Fusionado | 2026-09-15T18:29:37Z |
| CI | Lint, types and tests: **success** · Secret scan (gitleaks): **success** |
| Reviews | Ninguna |
| Comentarios | Ninguno |

---

## 18. Migraciones

**Ninguna migración se escribió y ninguna se aplicó.** Ningún proyecto Supabase
remoto se tocó en este subbloque, y por tanto no hubo ninguna autorización que
pedir ni que registrar (regla 15).

**PENDIENTE.** El contrato funcional deja registrado que el Piloto 0.1
necesitará **al menos una migración versionada** para el Incident Snapshot
(D14). No se ha escrito.

---

## 19. Estado operacional final

### Lo que existe — HECHO DEL REPOSITORIO

En `origin/main`, en `d05aab1c…`, están versionados y revisables:

- la arquitectura de capacidades componibles y planes controlados (ADR 0020);
- el contrato funcional del Piloto 0.1;
- el manual del observador;
- el estándar de cierre de bloques;
- la regla 26 de `CLAUDE.md`.

**ADR 0020 está en estado `propuesto`**, no aceptado.

### Lo que NO está implementado — HECHO DEL REPOSITORIO

Nada de lo siguiente existe en el código:

- `CapabilityPlan` operativo;
- router o selector de planes del Piloto 0.1;
- integración factual con Materiales (`MaterialsPort` sigue solo con fake);
- Incident Snapshot;
- botón «Reportar respuesta»;
- datos reales de Tampella publicados para el piloto;
- los puntos M1–M8;
- despliegue del Piloto 0.1.

> **Diseño aceptado no es funcionalidad desplegada.** Lo que este subbloque
> entrega es una decisión escrita y revisable. El piloto **no** está operativo,
> Materiales **no** está integrado y **no** hay datos reales cargados.

---

## 20. Pendientes

### Contrato con Materiales

**PENDIENTE.** Ninguno se resuelve desde este repositorio: todos requieren al
responsable de Materiales y datos reales.

| Id | Qué falta | Estado |
|---|---|---|
| **M1** | Contrato estable de consulta que usará ELSA | **ABIERTO · BLOQUEANTE** |
| **M2** | Consulta por lote de códigos | **ABIERTO · NO BLOQUEANTE** |
| **M3** | Formato real del código SAP | **ABIERTO · BLOQUEANTE** |
| **M4** | Versión y fecha del inventario activo | **ABIERTO · BLOQUEANTE** |
| **M5** | JWT real del usuario en la llamada ELSA → Materiales | **ABIERTO · BLOQUEANTE** |
| **M6** | Semántica y temporalidad real de los campos devueltos | **ABIERTO · BLOQUEANTE** |
| **M7** | Responsable y versionado del contrato | **ABIERTO · BLOQUEANTE** |
| **M8** | Semántica de ausencia y cobertura | **ABIERTO · BLOQUEANTE** |

Ninguno de estos puntos se resolvió en este subbloque.

### Otros pendientes

| Qué | Estado | Quién |
|---|---|---|
| **Retención del Incident Snapshot (D20)** | **ABIERTA · puerta previa a liberar.** Ningún tester entra antes de que exista una política escrita | Responsable del proyecto |
| Muestra concreta de la medición M3: qué hojas y quién la ejecuta | Abierto, dentro del protocolo de D23 | Responsable del proyecto |
| Mecanismo por el que la interfaz presenta el manual (D24) | Abierto, pendiente de inspeccionar el frontend | Al implementar |
| Migración del Incident Snapshot | Abierto | Al implementar |

---

## 21. Siguiente bloque

**PENDIENTE de autorización.** Lo que el contrato funcional señala como
siguiente, y por qué en ese orden:

1. **Medición M3 sobre el BOM real de Tampella**, según el protocolo de D23.
   Va primero porque puede invalidar el diseño del adaptador de inventario, y
   es una comprobación manual, no código.
2. **Cierre del contrato con Materiales** (M1, M4, M5, M6, M7, M8). No es
   trabajo de ingeniería y es lo que más tarda; conviene lanzarlo en paralelo.
3. **Extracción de las capacidades que ya existen** embebidas en
   `elsa.api.v1.assistant` y `elsa.api.v1.technical`, sin cambiar su
   comportamiento.

Nada de esto está autorizado todavía (regla 20).

---

## Nota sobre este documento

Este cierre registra el trabajo culminado en el pull request #19 y su merge
`d05aab1ce7728858262be2a099f15dad266bff7f`.

El commit y el pull request que publiquen **este mismo archivo** son la
*publicación del cierre*, no parte del trabajo que el documento cierra. No
procede redactar un documento de cierre sobre un documento de cierre.
