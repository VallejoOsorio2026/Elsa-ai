# ADR 0026 — Materialización de la gobernanza del contrato Materiales–ELSA y cierre de M7

- Estado: **aceptado**
- Bloque: 5.0, subbloque **5.0.b**, punto **M7**
- **Cierra M7** resolviendo lo único que
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §19.2 dejó pendiente:
  la asignación del ocupante del rol y la materialización de la gobernanza en el
  repositorio donde aquel ADR §16.4 la situó
- **No redefine el rol.** Las responsabilidades, la autoridad exclusiva para
  aprobar rupturas y la ubicación de la definición canónica siguen siendo las de
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §16, **sin cambio**
- **No nombra a ninguna persona**, y ELSA no registra nombre ni contacto del
  ocupante. La asignación vive en Materiales (§4)
- **No toca** §8.3 ni §9 de
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md), y **no gobierna**
  M1, M4, M6 operacional, M8, B9a–B9c ni el subbloque 5.0.c
- **No aprueba, y no contiene, ninguna implementación**: ni fachada, ni
  `MaterialsPort`, ni adaptador, ni endpoint, ni cambio alguno en Materiales
- Aplica las reglas **12, 17, 21, 22, 23, 25 y 26** de [`CLAUDE.md`](../../CLAUDE.md)

---

## Contexto

### 1. Qué quedó abierto en M7, exactamente

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §16 definió la
gobernanza del contrato de inventario completa salvo un punto: **quién ocupa el
rol**. Su §19.2 lo enunció sin ambigüedad —«el **ocupante inicial no está
asignado**» y «la gobernanza **no está materializada** en el repositorio de
Materiales»— y concluyó que **«M7 sigue siendo bloqueante y no se declara
cerrado hasta asignar el ocupante real y materializar la gobernanza
correspondiente»**.

Esas son **dos** condiciones, no una. Una designación verbal no materializa
nada, y un documento sin ocupante no asigna nada. M7 exigía las dos, escritas y
versionadas.

### 2. Por qué la asignación no podía vivir en ELSA

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §16.4 situó la
definición canónica del contrato **en el repositorio de Materiales**, con dos
motivos tomados de la auditoría: es donde el contrato se ejecuta, y el modo de
fallo demostrado del proyecto es la **deriva entre la base viva y el
repositorio**. Su §16.5 extendió el mismo criterio a la asignación operativa del
rol, y añadió la razón: «dos listas de responsables que puedan divergir son
peores que ninguna».

Ese razonamiento no se reabre aquí. Este ADR lo **ejecuta**.

### 3. Por qué M7 no es papeleo

El contrato Materiales–ELSA existe porque una función de consulta dejó de estar
versionada sin que nadie lo aprobara (ADR 0021, Contexto §2). Un contrato cuya
ruptura no tiene un responsable nombrado **reproduce esa misma situación con más
documentos**. M7 es la condición que convierte el §16.3 de ADR 0021 —«solo el
Contract Owner, y solo con constancia escrita»— en una frase con sujeto.

---

## Decisión

### 4. La gobernanza está materializada, y su fuente canónica es única

**La fuente canónica de la asignación del rol `Contract Owner Materiales–ELSA`
es el documento `docs/contrato-elsa.md` del repositorio de Materiales.**

Ese documento —y no este ADR, y no ningún otro artefacto de ELSA— registra:

- quién ocupa el rol y desde cuándo;
- por qué canal se le contacta;
- qué puede hacer el ocupante y qué no cuenta como aprobación;
- cómo se sustituye al ocupante.

**ELSA referencia esa asignación y no la copia.** En particular, **ningún
documento de ELSA registra el nombre, el correo ni el canal de contacto del
ocupante**, ni siquiera de forma auxiliar o «solo informativa». Una copia
auxiliar es exactamente la segunda lista que el §16.5 de ADR 0021 prohíbe: no
falla el día que se escribe, falla el día que el ocupante cambia y alguien lee
la copia.

Esta regla es **permanente** y no depende de quién ocupe el rol.

### 5. Evidencia de la materialización

La verificación se ejecutó sobre el repositorio de Materiales en la revisión
**`436eab92e1d4854e6055daaec808d2213cb37b7f`** de `main`, en lectura directa del
árbol versionado.

| # | Hecho verificado | Cómo |
|---|---|---|
| 1 | `docs/contrato-elsa.md` existe en `main` y está versionado | Lectura del archivo en esa revisión |
| 2 | Nombra el rol `Contract Owner Materiales–ELSA` **literalmente igual** que ADR 0021 §16.1 | Comparación de cadenas entre ambos documentos |
| 3 | Registra un **ocupante identificable** y la fecha desde la que lo es | Sección «Ocupante actual» |
| 4 | **No publica ninguna dirección de correo**: el documento no contiene el carácter `@` | Búsqueda sobre el contenido completo del archivo |
| 5 | Separa explícitamente el rol de gobernanza del rol técnico `admin` | Sección «No es el rol `admin`», con tabla comparativa |
| 6 | Reproduce la autoridad exclusiva de ruptura de ADR 0021 §16.3, incluidas las tres vías que **no** cuentan como aprobación | Sección «Quién puede romper el contrato» |
| 7 | Declara que ELSA **no copia** la asignación ni registra nombre ni contacto | Sección «Qué vive aquí y qué vive en ELSA» |
| 8 | Declara **PENDIENTE** lo que todavía no existe: definición canónica, descriptor y pruebas contractuales del proveedor | Sección «Estado» |
| 9 | El documento está enlazado desde el índice del README de Materiales | Lectura del README en esa misma revisión |

**Esa revisión es evidencia histórica de verificación, no un puntero
permanente.** Sirve para reconstruir qué se comprobó y cuándo. **No** debe
citarse como la ubicación del dato vigente: el dato vigente es
`docs/contrato-elsa.md` en la rama principal de Materiales, cualquiera que sea
su revisión actual. Un ADR que fijara una revisión como fuente envejecería mal y
volvería a crear la segunda fuente de verdad que el §4 prohíbe.

### 6. El rol permanece; el ocupante es un dato

La separación que ADR 0021 §16.1 estableció —«es un **rol**, no una persona»— se
mantiene íntegra y adquiere aquí su consecuencia operativa:

- **Sustituir al ocupante es editar una sección de un documento de Materiales.**
- Esa sustitución **no** requiere, y **no debe provocar**: modificar este ADR ni
  ningún otro, modificar código, esquema, RLS o configuración, modificar el
  adaptador de ELSA ni ninguna prueba, ni cambio alguno de arquitectura.
- Si alguna vez una sustitución de ocupante obligara a tocar un ADR, un puerto o
  una prueba, **eso sería un defecto de este diseño**, no un procedimiento.

Esta propiedad es la que permite que el proyecto cambie de manos sin tocar lo
que sostiene el contrato, y es un requisito de entrega a PAPELSA, no una
comodidad.

### 7. `Contract Owner` no es `admin`, y esa distinción es normativa

El repositorio de Materiales define `admin` como **rol técnico de autorización**
aplicado en base de datos. `Contract Owner Materiales–ELSA` es un **rol de
gobernanza contractual**. Son independientes en ambos sentidos.

| | `admin` | `Contract Owner Materiales–ELSA` |
|---|---|---|
| Naturaleza | Autorización técnica | Gobernanza del contrato |
| Dónde se aplica | Base de datos de Materiales | Decisiones sobre el contrato con ELSA |
| Qué permite | Operar la aplicación de Materiales | Aprobar cambios del contrato con ELSA |

**Tener `admin` no convierte a nadie en Contract Owner, y ser Contract Owner no
otorga `admin`.** Que hoy ambos recaigan en la misma persona es una
circunstancia, no una equivalencia, y no debe registrarse como tal en ninguna
parte.

La razón es la misma del §3: si bastara con tener `admin` para romper el
contrato, el modo de fallo que originó todo esto podría repetirse sin constancia
escrita.

### 8. Regla de secuencia

**M7 debe estar formalmente materializado y cerrado antes de solicitar la
fachada contractual Materiales–ELSA (M1).**

No es una preferencia de orden de trabajo. Solicitar una fachada es pedir a
Materiales que se comprometa a una interfaz estable; sin un responsable nombrado
que pueda comprometerse y que responda por las rupturas, la petición no tiene
destinatario y el compromiso no tiene custodio. Sería volver al punto de
partida: una función de la que nadie responde.

Esta regla **no** implica lo contrario de sí misma: cerrar M7 **no** autoriza
solicitar la fachada. Levanta un requisito previo; la solicitud es una decisión
posterior y explícita, y sigue sujeta a su propia autorización.

### 9. Criterio exacto de cierre de M7

M7 se cierra cuando, y solo cuando, se cumplen **las cuatro** condiciones:

| # | Condición | Estado |
|---|---|---|
| C1 | Existe en el repositorio de Materiales un documento **versionado** que asigna el rol `Contract Owner Materiales–ELSA` | **Cumplida** (§5, hechos 1–3) |
| C2 | Ese documento nombra un **ocupante identificable** y establece **cómo se le sustituye** sin tocar arquitectura | **Cumplida** (§5, hecho 3; §6) |
| C3 | La asignación es **fuente única**: ELSA la referencia y no registra nombre ni contacto | **Cumplida** (§4; §5, hecho 7) |
| C4 | ELSA registra la decisión de cierre en un **ADR versionado**, conforme a la regla 25 | **La cumple este ADR** |

**Las cuatro se cumplen. M7 queda cerrado.**

El criterio es deliberadamente corto. No exige que exista la definición canónica
del contrato, ni el descriptor, ni las pruebas contractuales del proveedor:
**eso es M1**, y el propio documento de Materiales lo declara PENDIENTE (§5,
hecho 8). Confundir ambas cosas convertiría M7 en un punto imposible de cerrar
antes de M1, cuando el §8 establece justamente la dependencia inversa.

---

## Consecuencias

### 10. Qué significa cerrar M7

- Existe un **responsable nombrado** del contrato Materiales–ELSA, registrado en
  un repositorio, con fecha.
- El §16.3 de ADR 0021 —«solo el Contract Owner, y solo con constancia
  escrita»— **tiene sujeto**: ya se puede señalar quién debe aprobar una ruptura
  y quién no puede aprobarla.
- **B8 deja de ser bloqueante** del Piloto 0.1.
- El requisito previo del §8 queda levantado: M1 puede solicitarse **cuando se
  autorice**.
- La sustitución futura del ocupante tiene un procedimiento escrito, de un solo
  paso y sin consecuencias arquitectónicas (§6).

### 11. Qué **no** significa cerrar M7

- **No** significa que exista la fachada contractual. **M1 sigue abierto y
  bloqueante.**
- **No** significa que exista la definición canónica versionada del contrato, ni
  el descriptor, ni las pruebas contractuales del proveedor. Los tres siguen sin
  existir, y el documento de Materiales lo declara.
- **No** significa que exista `contract_version`, ni que ELSA pueda consumir
  nada.
- **No** cierra M4, M6 operacional ni M8, ni levanta B9a–B9c. Ninguno se cierra
  por asociación.
- **No** cierra el subbloque 5.0.c ni ningún bloque. El cierre de un bloque
  exige su propio documento (regla 26) y este ADR no lo es.
- **No** autoriza tocar el repositorio de Materiales desde ELSA, ni ampliar los
  permisos de acceso sobre él.
- **No** convierte a ELSA en custodio de datos personales del ocupante: §4 lo
  prohíbe expresamente y de forma permanente.

### 12. Qué queda abierto después de esta decisión

| Qué | Dónde se resuelve |
|---|---|
| Definición canónica versionada del contrato, `contract_version` y descriptor | **M1**, en el repositorio de Materiales |
| Pruebas contractuales del **proveedor** | **M1**, custodiadas por el Contract Owner |
| Pruebas de **conformidad** de ELSA | ELSA, cuando exista la fachada |
| Metadata de versión y fecha del inventario activo | **M4** |
| Implementación y verificación de la semántica decidida | **M6 operacional** y [ADR 0025](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md) §12 |
| Semántica de ausencia y cobertura | **M8**, criterio de cierre en ADR 0021 §8.3, intacto y sin cumplir |

### 13. Riesgos

| Riesgo | Mitigación en este ADR | Riesgo residual |
|---|---|---|
| **Que alguien copie el nombre o el contacto del ocupante en ELSA «para comodidad»** y las dos fuentes diverjan | §4 lo prohíbe de forma permanente y explica por qué | Depende de que quien edite ELSA lea esta regla. No hay control automático |
| **Que se confunda `admin` con Contract Owner**, sobre todo mientras coincidan en la misma persona | §7 lo declara normativo en ambas direcciones, y el documento de Materiales lo repite con tabla | Alto si la coincidencia se prolonga y nadie relee la distinción |
| **Que el cierre de M7 se lea como permiso para solicitar la fachada** | §8 lo niega expresamente; §11 lo repite | Bajo |
| **Que el documento de Materiales se edite y ELSA no se entere**, quedando este ADR describiendo algo que ya no es | §5 fija que la fuente vigente es el archivo, no la revisión citada | Real y **no mitigado**: ELSA no observa el repositorio de Materiales. Se detecta al releer, no automáticamente |
| **Que el ocupante deje la organización sin sustituto registrado** | §6 hace la sustitución barata; el documento de Materiales la reduce a editar una sección | Real: nada obliga a que se ejecute a tiempo |
| **Que se lea este cierre como avance de M1** | §9 y §11 separan los criterios | Bajo |

### 14. Alternativas descartadas

| Alternativa | Por qué se descarta |
|---|---|
| **Registrar el ocupante también en ELSA** | Crea la segunda fuente de verdad que ADR 0021 §16.5 prohíbe, y publica datos de contacto en un segundo repositorio sin necesidad |
| **Nombrar a la persona en este ADR** | ADR 0021 §16.1 lo prohíbe —«ninguna persona se nombra en este ADR ni en la arquitectura»— y obligaría a escribir un ADR nuevo cada vez que cambie el ocupante, contra §16.5 |
| **Fijar la revisión `436eab9…` como fuente de la asignación** | Congela un dato que está diseñado para cambiar, y rompe §6 |
| **Dejar M7 abierto hasta que exista la fachada** | Invierte la dependencia del §8 y hace M7 incerrable por construcción |
| **Reescribir ADR 0021 §16.5 y §19.2** | Contra la regla 25 y contra el precedente de [ADR 0024](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md) §15: los cuerpos normativos no se reescriben; la historia se conserva y la nota fechada dice qué cambió después |
| **Aprovechar este ADR para cerrar 5.0.c o iniciar M1** | M1, M4, M6 operacional y M8 siguen abiertos. El cierre de un bloque exige su documento propio (regla 26) |

### 15. Qué cambia en los documentos existentes

**Cambios mínimos, solo de autoridad y referencia.** Ningún cuerpo normativo se
reescribe, **ningún documento de cierre se toca** —son registros históricos— y
**la historia se conserva**: donde un documento describía correctamente que M7
estaba pendiente en el momento de una decisión anterior, ese texto permanece y
la nota fechada dice qué cambió después.

| Documento | Cambio |
|---|---|
| [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §16.5 | Nota fechada: el ocupante **ya está asignado**, en el lugar que ese mismo apartado designó. El texto normativo del apartado **no cambia** |
| [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §19.2 | Nota fechada: las dos condiciones pendientes que enuncia **se cumplieron**; M7 **deja de ser bloqueante** por este ADR |
| [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §25 | Nota fechada: **solo la fila de M7** cambia de lectura. El resto de la tabla **no cambia** |
| [Contrato funcional](../piloto-0-1/contrato-funcional.md) §10 (B8), §14 | B8 pasa a **resuelto**, con tachado, citando este ADR; en §14, M7 sale de la fila de decisiones abiertas y obtiene fila propia |

**Y nada más.** No se tocan ADR 0020, 0022, 0023, 0024 ni 0025; no se toca
ADR 0021 §8.3 ni §9.3; no se toca ningún documento de cierre; no se toca código,
prueba ni configuración; y **no se toca el repositorio de Materiales**.

El contenido del documento de gobernanza **no se duplica aquí**. Vive en
Materiales y se cita.

### 16. Estado de M7 después de este ADR

**M7 — cerrado.**

| Dimensión | Estado |
|---|---|
| Rol definido | Cerrado desde [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §16 |
| Ocupante asignado | **Cerrado**, en el repositorio de Materiales |
| Gobernanza materializada | **Cerrada**, en el repositorio de Materiales |
| Bloqueante | **No** |
| Sustitución del ocupante | Procedimiento escrito, sin impacto arquitectónico (§6) |

El cierre de M7 **no depende de Materiales real en ejecución**: es una decisión
de gobernanza materializada en un repositorio, verificable por lectura. Por eso
no contradice la frase que encabeza ADR 0021 §25, que habla de cierres que
dependen del sistema en funcionamiento.

### 17. Trazabilidad de los requisitos de este ADR

| # | Requisito | Sección |
|---|---|---|
| 1 | Contexto de M7 y qué dejó abierto ADR 0021 | §1 |
| 2 | Por qué la asignación no vive en ELSA | §2 |
| 3 | Por qué M7 no es papeleo | §3 |
| 4 | Fuente canónica y una sola fuente de verdad | §4 |
| 5 | Evidencia de materialización | §5 |
| 6 | Continuidad y sustitución futura | §6 |
| 7 | Separación respecto de `admin` | §7 |
| 8 | Regla de secuencia frente a la fachada | §8 |
| 9 | Criterio exacto de cierre | §9 |
| 10 | Qué significa cerrar M7 | §10 |
| 11 | Qué **no** significa cerrar M7 | §11 |
| 12 | Qué queda abierto | §12 |
| 13 | Riesgos, incluido el residual no mitigado | §13 |
| 14 | Alternativas descartadas | §14 |
| 15 | Qué cambia en los documentos existentes | §15 |
| 16 | Estado de M7 | §16 |

## Ver también

- [ADR 0021 — Contrato de inventario con Materiales (V1)](0021-contrato-de-inventario-con-materiales.md)
- [ADR 0024 — Validación real de la frontera del código SAP y de la autenticación](0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
- [ADR 0025 — Semántica, procedencia y temporalidad de los campos de inventario](0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)
- [Contrato funcional del Piloto 0.1](../piloto-0-1/contrato-funcional.md)
- [Cierre del subbloque 5.0.b](../bloque-5-0-b-contrato-materiales-cierre.md)
- `docs/contrato-elsa.md`, en el repositorio de Materiales — **fuente canónica de
  la asignación del rol**
