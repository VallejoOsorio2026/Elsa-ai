# Cierre del subbloque 5.0.b — Contrato de inventario con Materiales: decisiones normativas

Documento de cierre redactado según
[el estándar de cierre de bloques](project/BLOCK_CLOSURE_STANDARD.md)
(`CLAUDE.md`, regla 26).

> **Qué cierra este documento y qué no.**
>
> Cierra el subbloque **5.0.b**, que es el trabajo **normativo y documental**
> del contrato de inventario con Materiales: decidir qué superficie consume
> ELSA, medir la frontera del código SAP, aceptar el esquema de autenticación y
> decidir la semántica de los campos.
>
> **NO** cierra **M1**, **M4**, **M7** ni **M8**. **NO** declara cerrado
> operacionalmente **M6**. **NO** cierra el subbloque **5.0.c**, ni el **Bloque
> 5.0**, ni el **Piloto 0.1**. **NO** declara que exista ninguna fachada, ningún
> adaptador ni ninguna integración. **NO** modifica nada en el repositorio de
> Materiales.

Marcas de evidencia usadas, según el estándar: **HECHO MEDIDO**, **HECHO DEL
REPOSITORIO**, **DECISIÓN TOMADA**, **INFERENCIA**, **PENDIENTE**.

---

## 1. Objetivo

La capacidad que debía quedar disponible al terminar 5.0.b es **normativa, no
ejecutable**:

> Que ELSA sepa, por escrito y con procedencia, **qué superficie consumirá de
> Materiales, qué forma tendrá lo que reciba y qué significa cada campo** —de
> modo que la fachada pueda especificarse, pedirse y verificarse sin inventar
> nada.

Lo que **no** era el objetivo: construir esa fachada, escribir el adaptador,
integrar el inventario ni resolver los puntos que dependen de Materiales o de
una decisión de personas.

---

## 2. Alcance

### Entró

**HECHO DEL REPOSITORIO.** Los artefactos que declaran `Bloque: 5.0, subbloque
5.0.b` en su encabezado, todos presentes en `main`:

| Artefacto | Qué aporta |
|---|---|
| [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) | El contrato de inventario V1: fachada contractual, operaciones separadas, tres ejes de respuesta, ausencia no autoritativa, vigencia, cobertura, procedencia, versionado y gobernanza |
| [Evidencia M3/M5 (PC1)](piloto-0-1/evidencia-m3-m5-pc1.md) | Mediciones reales sobre el BOM de Tampella y sobre el entorno real de Materiales |
| [ADR 0024](adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md) | **M3-A** —la regla de frontera del código SAP— y la aceptación del esquema de autenticación (**M5**), ambas para V1 |
| [Evidencia M6](piloto-0-1/evidencia-m6-semantica-temporalidad.md) | Auditoría de solo lectura del repositorio de Materiales, con la procedencia de cada afirmación clasificada |
| [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) | La semántica, la procedencia y la temporalidad de los campos (**M6**) |

### Quedó explícitamente fuera

**DECISIÓN TOMADA**, y cada exclusión tiene su fuente:

- **La fachada contractual y el `MaterialsPort` real.** No existen.
  [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §19.1 lo declara
  y §21.4 fija que construirla es trabajo posterior y autorizado aparte.
- **El adaptador de inventario.**
  [ADR 0024](adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
  §9 levantó su condición previa **sin autorizar su construcción**.
- **La composición BOM → Materiales**, los endpoints y el frontend.
- **Cualquier cambio en el repositorio de Materiales.** Las dos auditorías
  fueron de **solo lectura**.
- **M8**, gobernado por
  [ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) desde el
  subbloque 5.0.c.2.
- **ONNX, INT8 y la topología de modelos.** Hilo paralelo, sin dependencia.

### Qué ADR **no** pertenecen a este subbloque

**HECHO DEL REPOSITORIO**, y se dice para que nadie los cuente aquí por
proximidad de numeración:
[ADR 0020](adr/0020-capacidades-componibles-y-planes-de-ejecucion.md) es del
Bloque 5.0 y quedó cerrado en
[el cierre de 5.0.a](bloque-5-0-subbloque-diseno-normativo-cierre.md);
[ADR 0022](adr/0022-feedback-e-incident-snapshot-del-piloto.md) es de **5.0.c**;
[ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md) es de
**5.0.c.2**.

---

## 3. Estado inicial

**HECHO DEL REPOSITORIO.** 5.0.b se abrió sobre lo que dejó
[el cierre del subbloque 5.0.a](bloque-5-0-subbloque-diseno-normativo-cierre.md),
publicado en el merge `d05aab1ce7728858262be2a099f15dad266bff7f`.

De qué se partía:

- Existía [ADR 0020](adr/0020-capacidades-componibles-y-planes-de-ejecucion.md),
  que declaró la capacidad de consulta de inventario y dejó su
  `absence_semantics` **desconocida**, remitiendo a ocho puntos abiertos
  (M1–M8) del contrato con Materiales.
- Existía el [contrato funcional del Piloto 0.1](piloto-0-1/contrato-funcional.md),
  con M1–M8 entre sus bloqueantes.
- **No existía** ningún contrato con Materiales: ni tipos compartidos, ni
  esquema publicado, ni pruebas contractuales, ni versión declarada.
- **No se había medido** el formato real del código SAP (M3) ni verificado el
  algoritmo de firma (M5).
- **No se había leído** el código de Materiales.

---

## 4. Trabajo realizado

**HECHO DEL REPOSITORIO.** En orden cronológico:

1. **Auditoría de solo lectura del repositorio de Materiales** para fundamentar
   el contrato. Sus hallazgos están en
   [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) Contexto §2.
2. **Redacción de [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md)**:
   el contrato de inventario V1 completo, que **decide el punto M1** y **define
   el rol de gobernanza del punto M7**.
3. **Medición M3 y comprobación M5 en PC1**, ejecutadas por el responsable del
   proyecto fuera de una sesión de asistente, según el protocolo D23 del
   [contrato funcional](piloto-0-1/contrato-funcional.md) §11. Registradas en
   [la evidencia M3/M5](piloto-0-1/evidencia-m3-m5-pc1.md).
4. **Redacción de [ADR 0024](adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)**,
   que formaliza **M3-A** y la aceptación de **M5** como decisiones
   arquitectónicas (regla 25), porque una medición no es una decisión.
5. **Auditoría de estado de M1, M4, M6 y M7**, que identificó que la semántica
   de campos discutida en conversaciones anteriores **no estaba versionada en
   ninguna parte**.
6. **Corrección de coherencia de estado de los ADR 0020–0024**, de `propuesto`
   a `aceptado`, conforme a la convención de `docs/contributing.md`.
7. **Auditoría primaria de solo lectura del repositorio de Materiales** en la
   revisión `b0cb12b4440d95b5c4ec0a64ca619b31b36e26c3`, para responder las
   preguntas abiertas de M6.
8. **Redacción de [la evidencia M6](piloto-0-1/evidencia-m6-semantica-temporalidad.md)**,
   con cada afirmación clasificada por la fuerza de su fuente.
9. **Adopción de las ocho decisiones de M6** por el responsable del proyecto.
10. **Redacción de [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)**,
    que registra esas decisiones.
11. **Este documento de cierre**, que la regla 26 exige.

---

## 5. Decisiones

**DECISIÓN TOMADA.** Todas están registradas como ADR (regla 25) y **este
documento las referencia, no las reescribe**.

### Decididas en ADR 0021

- ELSA consume una **fachada contractual**, no el buscador actual de Materiales.
- **Lookup exacto y búsqueda textual son operaciones separadas**, y el lookup no
  puede degradarse a similitud.
- La respuesta tiene **tres ejes ortogonales**: estado de la llamada, resultado
  por código y estado de la cobertura.
- **La ausencia no es autoritativa**, y la taxonomía V1 tiene un solo valor.
- Vigencia y cobertura son **obligatorias en toda respuesta** y son **ejes
  independientes**.
- La procedencia se conserva **por campo**, con atribución obligatoria por
  resultado.
- Se define el rol **`Contract Owner Materiales–ELSA`**, sus responsabilidades y
  dónde vive su asignación.

### Decididas en ADR 0024

- **M3-A**: el código SAP cruza la frontera como **cadena decimal exacta**, con
  nueve reglas, y **vale para el dominio observado del Piloto Tampella V1**, no
  universalmente.
- **M5**: se acepta la **validación asimétrica por JWKS**, y **no se comparte
  ningún secreto simétrico**.

### Decididas en ADR 0025

- `dado_de_baja` permanece en V1 como **señal no accionable**.
- Se añade una **quinta clase de procedencia** para los valores factuales que
  llegan por agregación, conservando el significado fuerte de la clase factual
  por fila.
- La temporalidad se declara como una **propiedad binaria por campo**.
- **`ambito` no es cobertura** y se prohíbe usarlo para inferirla.
- **`ubicacion` es opaca** y se muestra sin interpretar.
- El contenedor agregado de ubicaciones **se nombra y se tipa**, con garantía de
  coherencia por elemento.
- `match_origin` recibe un **vocabulario mínimo verificable**, con tratamiento
  declarado de valores desconocidos.
- La **emisión de campos es estable**, y la regla queda **acotada a M6**.

### Decisión propia de este cierre

**DECISIÓN TOMADA por el responsable del proyecto.** Declarar cerrado 5.0.b
como subbloque **normativo y documental**, sobre la base del §19. La
justificación de por qué los puntos que siguen abiertos no lo impiden está
en ese mismo apartado, incluida la única objeción versionada que existe y por
qué no aplica hoy.

---

## 6. Pruebas

**HECHO MEDIDO.** Lo que se ejecutó en este subbloque, no lo que se pensaba
ejecutar.

| Prueba | Dónde consta | Resultado |
|---|---|---|
| Medición M3 sobre las fuentes reales de Tampella, sin normalización nueva | [Evidencia M3/M5](piloto-0-1/evidencia-m3-m5-pc1.md) §2 | Longitud observable homogénea; **ningún valor textual con cero inicial**; ningún whitespace externo |
| Cruce real de la muestra D23 contra el RPC de Materiales | [Evidencia M3/M5](piloto-0-1/evidencia-m3-m5-pc1.md) §2.5 | **30 consultadas, 30 respondidas, 0 errores**; 27 coincidencias exactas; **3 resultados devueltos sin el código exacto**; **0 `NOT_RETURNED`** |
| Comprobación del JWKS público | [Evidencia M3/M5](piloto-0-1/evidencia-m3-m5-pc1.md) §4.1 | HTTP 200, una clave, algoritmo **asimétrico**, `use=sig`, `kid` presente |
| Prueba autenticada contra el RPC real | [Evidencia M3/M5](piloto-0-1/evidencia-m3-m5-pc1.md) §4.2 | Login correcto; **30 de 30** llamadas autenticadas respondieron; 0 errores de RPC |
| Auditoría de código de Materiales | [Evidencia M6](piloto-0-1/evidencia-m6-semantica-temporalidad.md) §5–§10 | E1, E3, E4, E6 y E7 **verificadas**; E2 y E5 **parciales** |
| Búsquedas de ausencia en ELSA, fijadas a una revisión | [Evidencia M6](piloto-0-1/evidencia-m6-semantica-temporalidad.md) §14.3 | 22 patrones a cero; tres recuentos crudos corregidos en vez de reportados |
| Enlaces relativos de Markdown | Este subbloque, en cada PR | 0 rotos en cada verificación |
| `pre-commit` dirigido y CI de cada PR | §17 | Verde en todos |

**Ninguna prueba de código se añadió ni se modificó en este subbloque**, porque
no produjo código.

---

## 7. Comandos relevantes

Lo que otra persona necesitaría para reproducir la parte reproducible de este
trabajo. **Las mediciones M3 y M5 no son reproducibles desde el repositorio**:
dependen de archivos reales fuera de Git y del entorno real de Materiales.

```bash
# Situarse en el estado que este documento cierra
git fetch origin
git log --oneline origin/main

# Comprobar qué artefactos declaran pertenecer a 5.0.b
git grep -n "subbloque \*\*5.0.b\*\*" origin/main -- docs/

# Comprobar el estado de los ADR del subbloque
git show origin/main:docs/adr/0021-contrato-de-inventario-con-materiales.md | grep -m1 "^- Estado:"
git show origin/main:docs/adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md | grep -m1 "^- Estado:"
git show origin/main:docs/adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md | grep -m1 "^- Estado:"

# Auditar Materiales como se hizo aquí: solo lectura, fuera del árbol de ELSA
GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 <repositorio de Materiales> <ruta temporal>
git -C <ruta temporal> rev-parse HEAD   # debe dar b0cb12b…

# Verificaciones documentales usadas en cada PR
git diff --check
uv run pre-commit run --files <archivo>
```

---

## 8. Resultados

**HECHO MEDIDO.** Salida real de la verificación final de este subbloque,
ejecutada sobre `origin/main` en `9f5cf359a7bd10fa6840ff274f2f7b982b12388a`:

```text
=== ADR 0020-0025 en origin/main ===
  0021 …contrato-de-inventario-con-materiales.md            - Estado: **aceptado**
  0024 …validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md - Estado: **aceptado**
  0025 …semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md - Estado: **aceptado**

=== evidencia en origin/main ===
docs/piloto-0-1/evidencia-m3-m5-pc1.md
docs/piloto-0-1/evidencia-m6-semantica-temporalidad.md

=== CI de main (9f5cf35) ===
   Secret scan (gitleaks) | completed | success
   Lint, types and tests  | completed | success
FALLOS: 0
```

---

## 9. Métricas

**HECHO MEDIDO.** Cifras con su método. **No se transcribe ningún dato real**
(regla 12).

| Métrica | Valor | Método |
|---|---|---|
| Artefactos normativos producidos | 3 ADR + 2 documentos de evidencia | Conteo sobre los archivos que declaran pertenecer a 5.0.b |
| Puntos M decididos normativamente | **4** — M1 (contrato), M3, M5, M6 | Lectura de los ADR del subbloque |
| Puntos M con gobernanza definida | **1** — M7, rol y responsabilidades | ADR 0021 §16 |
| Muestra de la medición M3 | 30 códigos distintos | Protocolo D23, mínimo exigido |
| Llamadas autenticadas reales | 30 de 30 respondidas, 0 errores | Evidencia M3/M5 §2.5 y §4.2 |
| Evidencias E1–E7 verificadas | **5 de 7** verificadas, 2 parciales | Evidencia M6 §4 |
| Variantes de agregación SQL buscadas en ELSA | 18, con 0 coincidencias | Evidencia M6 §5 |
| Enlaces Markdown comprobados en el último PR del subbloque | 597, **0 rotos** | Herramienta de comprobación de enlaces |
| Pruebas de código añadidas o modificadas | **0** | El subbloque no produjo código |

---

## 10. Aportes de Claude Code

**HECHO DEL REPOSITORIO.** Claude Code redactó, bajo revisión y decisión del
responsable del proyecto, los ADR 0021, 0024 y 0025, el documento de evidencia
M6 y este cierre; ejecutó las auditorías de solo lectura de ambos repositorios;
y realizó las verificaciones documentales y las operaciones de Git de cada PR.

**Ninguna decisión normativa la tomó Claude Code.** Las ocho decisiones de M6
fueron adoptadas expresamente por el responsable del proyecto, y los nombres
propuestos requirieron su confirmación explícita antes de escribirse.

**PENDIENTE.** Los identificadores de sesión de los trabajos anteriores a la
sesión de M6 **no se registraron en su momento y no se dispone de ellos de
forma verificable**; no se reconstruyen de memoria. El respaldo de esos aportes
son sus commits, ramas, PR y archivos versionados, enumerados en §16 y §17.

---

## 11. Aportes de Codex

**Nada que registrar.** Codex no participó en este subbloque.

---

## 12. Operaciones manuales y de PowerShell

**HECHO MEDIDO.** Las mediciones **M3** y **M5** las ejecutó el **responsable
del proyecto en PC1**, fuera de una sesión de asistente, sobre archivos reales
de Tampella y contra el entorno real de Materiales. Los artefactos de esa
ejecución viven **fuera de Git** y están sellados por huella SHA-256 en
[la evidencia M3/M5](piloto-0-1/evidencia-m3-m5-pc1.md) §2.6 y §4.3.

Es la razón por la que el §6 marca esas pruebas como medidas **por él**, no por
una sesión de asistente.

**Ninguna otra operación manual** se ejecutó en este subbloque: no se tocó
ningún panel, no se levantó ningún servicio y no se ejecutó ninguna migración.

---

## 13. Incidentes

### I1 — La semántica de M6 discutida antes no estaba versionada

**HECHO DEL REPOSITORIO.** Al auditar el estado de M6 se comprobó que las
semánticas de campos tratadas en conversaciones anteriores **no existían en el
repositorio**: ni el nombre de la función de agrupación, ni la implicación de
su agregación, ni la naturaleza de `ambito`.

**Qué se hizo:** registrarlas como *antecedente de conversación no
reverificado*, sin ascenderlas a hecho, y auditar Materiales para contrastarlas.
Tras la auditoría, las que la evidencia confirma citan su fuente primaria.

**Por qué importa:** vulneraba la regla 17 y el §1 de `CLAUDE.md` —otra persona
debe poder continuar el proyecto sin acceso a las conversaciones—.

### I2 — Discrepancia entre ADR 0021 §10.3 y la implementación de Materiales

**HECHO DEL REPOSITORIO.** Aquel apartado afirma que el material marcado para
baja «no se oculta **ni se desprioriza**», como descripción de lo que hace
Materiales. La auditoría demostró que **no se oculta, pero sí se desprioriza**.

**Qué se hizo:**
[ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
§4.1 corrige la premisa fáctica **sin cambiar la norma de ELSA**, y §4.2 registra
la priorización como **brecha de implementación**, no como contrato.

### I3 — El PR de la evidencia M6 quedó bloqueado al fusionar el anterior

**HECHO MEDIDO.** Tras fusionar el PR de coherencia de estado, la protección de
rama dejó al PR de la evidencia M6 en estado `behind`, y GitHub rechazó su
fusión con una violación de reglas, no con un fallo de CI.

**Qué se hizo:** detenerse, diagnosticar, reportar y **pedir autorización antes
de resolver**. Con ella, se trajo `main` a la rama mediante merge commit, sin
conflictos, verificando que el diff neto seguía siendo un único archivo.

### I4 — Estado de los ADR incoherente con la convención del repositorio

**HECHO DEL REPOSITORIO.** Los ADR 0020–0024 seguían marcados `propuesto`
estando fusionados y citados como autoridad normativa, mientras los ADR
anteriores estaban `aceptado`.

**Qué se hizo:** auditar la convención real del repositorio —que `aceptado`
significa decisión adoptada, no trabajo terminado— y corregir solo la línea de
estado de los cinco.

### Sobre la ausencia de más incidentes

No hubo ningún otro. Es coherente con la naturaleza del subbloque: **no produjo
código**, y los documentos no tienen modos de fallo en ejecución.

---

## 14. Git

**HECHO DEL REPOSITORIO.** Todo el trabajo llegó a `main` por pull request, con
**merge commit** en todos los casos. No se usó squash, ni rebase, ni
force-push, ni reset destructivo en ninguna rama de este subbloque.

Ninguna rama de este subbloque **se ha borrado**, por trazabilidad.

---

## 15. Ramas

**HECHO DEL REPOSITORIO.**

| Rama | Para qué | Estado |
|---|---|---|
| `docs/adr-0021-materials-inventory-contract` | ADR 0021 | Fusionada; **no borrada** |
| `claude/tender-wright-si54ve` | Evidencia M3/M5 y actualización del corpus | Fusionada; **no borrada** |
| `claude/inspiring-mendel-na5olr` | ADR 0024 | Fusionada; **no borrada** |
| `docs/adr-0020-0024-estado-aceptado` | Coherencia de estado de los ADR | Fusionada; **no borrada** |
| `docs/m6-evidencia-semantica-temporalidad-materiales` | Evidencia M6 | Fusionada; **no borrada** |
| `docs/adr-0025-semantica-temporalidad-materiales` | ADR 0025 | Fusionada; **no borrada** |
| `docs/cierre-5-0-b` | **Este documento** | La rama que lo publica |

---

## 16. Commits

**HECHO DEL REPOSITORIO.** Los commits que produjeron los artefactos del
subbloque:

| Commit | Qué introdujo |
|---|---|
| `8919cf9` | ADR 0021 |
| `bfc76c1` | Evidencia M3/M5 y actualización del corpus vivo |
| `f5673f9` | ADR 0024 |
| `a46e8cf` | Estado `aceptado` de los ADR 0020–0024 |
| `e83bb05` | Evidencia M6, primera versión |
| `0c13a12` | Evidencia M6, con la auditoría primaria de Materiales |
| `1d26b0c` | ADR 0025 |

Merges correspondientes en `main`: `8790944`, `fb3cba3`, `dfcf1bd`, `d4fc948`,
`515ce91`, `28ecf9d` y `9f5cf35`.

---

## 17. Pull requests

**HECHO DEL REPOSITORIO.**

| PR | Qué entregó | Estado | CI |
|---|---|---|---|
| **#21** | ADR 0021 | Fusionado | Verde |
| **#25** | Evidencia M3/M5 | Fusionado | Verde |
| **#26** | ADR 0024 | Fusionado | Verde |
| **#29** | Estado `aceptado` de los ADR 0020–0024 | Fusionado (`d4fc948`) | Verde, 4/4 |
| **#30** | Evidencia M6 | Fusionado (`28ecf9d`) | Verde, 4/4 |
| **#31** | ADR 0025 | Fusionado (`9f5cf35`) | Verde, 4/4 |

El pull request que publique **este mismo documento** es la *publicación del
cierre*, no parte del trabajo que cierra.

---

## 18. Migraciones

**Nada que registrar.** Este subbloque **no escribió ninguna migración**, no
aplicó ninguna y **no tocó ningún proyecto Supabase remoto** (regla 15). No se
ejecutó SQL contra ninguna base real, ni de ELSA ni de Materiales.

---

## 19. Estado operacional final

### Qué existe — HECHO DEL REPOSITORIO

En `origin/main`, en `9f5cf359a7bd10fa6840ff274f2f7b982b12388a`, están
versionados y revisables el contrato de inventario V1, la regla de frontera del
código SAP, la aceptación del esquema de autenticación, la semántica de los
campos y las dos evidencias que los sostienen. Los tres ADR del subbloque están
en estado **`aceptado`**.

### Qué NO está implementado — HECHO DEL REPOSITORIO

Nada de lo siguiente existe en el código:

- la fachada contractual de Materiales;
- el `MaterialsPort` real, que **sigue siendo el puerto legado**;
- el adaptador de inventario;
- la representación de frontera M3-A como función;
- la emisión de vigencia, cobertura, procedencia o atribución;
- la composición BOM → Materiales, endpoints o frontend.

> **Decisión normativa cerrada no es funcionalidad desplegada.** Lo que este
> subbloque entrega es un contrato escrito, medido y revisable. **El inventario
> de Materiales no está integrado**, y ninguna respuesta de ELSA consume todavía
> un dato suyo.

### Por qué 5.0.b puede cerrarse con M1, M4, M7 y M8 abiertos

**INFERENCIA**, y se argumenta en vez de afirmarse:

5.0.b es el subbloque **normativo** del contrato con Materiales. Lo que le
correspondía era **decidir**, y lo decidido está en `main`. Lo que sigue abierto
en M1, M4, M7 y M8 es **implementación, trabajo de un tercero o una decisión de
personas**, y ninguna de las tres cosas es entregable de un subbloque
documental. La propia
[ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §19.1 usa esa
misma separación para M1: *decisión arquitectónica cerrada, implementación
contractual pendiente*.

**Los tres registros versionados de pendientes de 5.0.b nombran un único
requisito para cerrarlo, y es este documento**:
[la evidencia M3/M5](piloto-0-1/evidencia-m3-m5-pc1.md) §5 fila 6,
[ADR 0024](adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
§16 fila 7 —«su documento de cierre es obligatorio (regla 26) **cuando se
declare cerrado**»— y
[el cierre de B9a–B9c](bloque-5-0-b9a-b9c-cobertura-segura-cierre.md) P11.

**La única objeción versionada, declarada aquí en vez de omitida.**
[ADR 0024](adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
§18 descarta «aprovechar ese ADR para cerrar 5.0.b» razonando que «M1, M4, M6,
M7 y B9a–B9c siguen abiertos» y que el cierre exige documento propio. Dos de
esos cinco cambiaron desde entonces: **M6 quedó decidido normativamente** por
ADR 0025 y **B9a–B9c fueron implementados y cerrados**. Los otros tres siguen
abiertos y **este documento no los cierra**. Esa fila explica por qué *aquel*
ADR no cerró el subbloque, no fija criterios de cierre; los criterios los fija
el estándar, y el requisito que los tres registros nombran es el documento.

---

## 20. Pendientes

Estados leídos del corpus vigente, **uno a uno y sin homogeneizar**. Ninguno se
cierra por asociación con este documento.

| Id | Estado exacto, y dónde consta | Quién debe resolverlo |
|---|---|---|
| **P1** | **M1 — decisión arquitectónica cerrada · implementación contractual pendiente · bloqueante** ([ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §19.1). La fachada **no existe** | Responsable del proyecto y Materiales |
| **P2** | **M4 — semántica contractual definida · verificación e implementación de metadata pendientes · bloqueante** ([ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §9 y §25). **Su §9.3 queda intacto**, y con él la reserva de la fecha de extracción | Materiales |
| **P3** | **M6 — decisión normativa cerrada · implementación y verificación pendientes** ([ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §15). **No está cerrado operacionalmente** | Siguientes subbloques y Materiales |
| **P4** | **M7 — rol y gobernanza definidos · ocupante inicial pendiente · bloqueante** ([ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §19.2 y §16.5). **Puerta previa al primer tester** | Responsable del proyecto |
| **P5** | **M8 — ABIERTO**, y **no bloqueante** desde [ADR 0023](adr/0023-cobertura-desconocida-materiales-piloto.md). Su criterio de cierre sigue siendo [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §8.3, **intacto y sin cumplir** | Materiales, con el Contract Owner de M7 |
| **P6** | **M2 — abierto · no bloqueante** | Sin asignar |
| **P7** | **Las cinco brechas de implementación de [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §12** (B1–B5) siguen abiertas | Materiales, salvo B1 que depende también de M1 |
| **P8** | **Los dos huecos de conformidad de [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §13**: dos funciones de Materiales **no versionadas** en la revisión auditada. **Son huecos de conformidad, no bloqueos normativos** | Materiales |
| **P9** | **La doble semántica de `null`** entre [ADR 0025](adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §10 y [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md) §9.3 queda **remitida a M4**, declarada y sin resolver | Siguiente trabajo normativo de M4 |
| **P10** | **D20 — retención del Incident Snapshot: ABIERTA y puerta previa a liberar**, sin cambio | Responsable del proyecto |
| **P11** | **El subbloque 5.0.c continúa ABIERTO** | Siguientes subpasos |
| **P12** | **El Bloque 5.0 y el Piloto 0.1 continúan ABIERTOS.** Cerrar 5.0.b no cierra su bloque padre | Responsable del proyecto |
| **P13** | **Resto de bloqueantes del [contrato funcional](piloto-0-1/contrato-funcional.md) §10** no cubiertos aquí | Responsable del proyecto |

> **No se homogeneizan.** Cada fila lleva el estado que el corpus le da hoy.
> Cerrar 5.0.b **no adelanta ni un paso** a M1, M4, M7, M8 ni D20.

---

## 21. Siguiente bloque

**PENDIENTE de autorización explícita.** Este documento **no autoriza nada** por
sí solo, y el orden lo fija el responsable del proyecto (regla 20).

Lo que este cierre **habilita**: que la fachada pueda **especificarse y pedirse**
a Materiales con un contrato escrito, medido y con semántica decidida — que es
exactamente lo que [ADR 0021](adr/0021-contrato-de-inventario-con-materiales.md)
§21.4 exigía antes de solicitarla. **Eso es todo lo que habilita.**

Candidatos naturales, ninguno autorizado aquí:

1. **Asignar el ocupante del Contract Owner (M7)**, que no tiene dependencia
   técnica y sí latencia humana, y del que depende quién publique y versione las
   reglas que la conformidad necesita.
2. **Solicitar la fachada a Materiales (M1)**, con el contrato ya escrito y las
   cinco brechas de ADR 0025 §12 como lista de requisitos.
3. **Trabajo propio de ELSA que no depende de Materiales**: el retipado del
   `MaterialsPort`, el fake de la fachada y las pruebas de conformidad, que
   convierten el contrato en una especificación ejecutable.
4. **Continuar el subbloque 5.0.c.**

**No se autoriza aquí**, y requiere decisión explícita en cada caso: cerrar M1,
M4, M6 operacional, M7, M8, el subbloque 5.0.c, el Bloque 5.0 ni el Piloto 0.1;
iniciar la fachada, el adaptador o la composición BOM → Materiales; tocar ONNX;
ni decidir D20.
