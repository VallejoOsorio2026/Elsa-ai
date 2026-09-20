# ADR 0024 — Validación real de la frontera del código SAP y de la autenticación con Materiales (V1)

- Estado: **propuesto**
- Bloque: 5.0, subbloque **5.0.b**
- **Decide dos cosas, y solo dos**: la representación del código SAP en la
  frontera hacia Materiales (**M3-A**, §8) y la aceptación del esquema de
  autenticación real de Materiales (**M5**, §11), **ambas para V1**
- Ejerce el mecanismo que la **regla 25** de [`CLAUDE.md`](../../CLAUDE.md)
  exige: formaliza como decisión arquitectónica lo que hasta ahora vivía solo
  en un registro de evidencia
- **Cierra** los puntos **1**, **2** y **3** de las decisiones diferidas de
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §22, y **solo
  esos** (§14)
- Se apoya en [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md), que
  es la fuente estable de los conteos y de las huellas SHA-256. **Este ADR no
  la duplica**: la cita
- **No cierra M8**, no lo toca y **no reabre**
  [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md) (§13)
- **No gobierna** M1, M2, M4, M6, M7, M8, B9a–B9c, la fachada contractual,
  `MaterialsPort`, endpoints, frontend, ONNX ni D20 (§3)
- Confirma la identidad ya decidida en
  [ADR 0002](0002-identidad-de-materiales-autorizacion-en-backend.md) y
  [ADR 0005](0005-verificacion-real-del-jwt-de-materiales.md), **sin
  reabrirlas**
- Conserva sin cambios los estados de respuesta de
  [ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md) y la
  taxonomía de [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §6
- Aplica las reglas **2, 6, 9, 12, 21, 22, 23 y 25** de
  [`CLAUDE.md`](../../CLAUDE.md)
- **No cierra el subbloque 5.0.b**, que sigue abierto (§16)
- **No aprueba, y no contiene, ninguna implementación**

---

## Contexto

### 1. Por qué este ADR existe

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) dejó dos puntos
explícitamente bloqueados **por prueba real**, no por falta de decisión:

- **M3** — la representación de frontera del código SAP era
  «**indecidible hasta M3**» (§3.2), y §21.1 prohibía escribir cualquier
  adaptador de inventario antes de medirla.
- **M5** — el algoritmo de firma de Materiales estaba sin verificar, y §21.2
  fijó de antemano una bifurcación: firma asimétrica → M5 avanza; firma
  simétrica heredada → **M5 se detiene** y exige revisión arquitectónica.

Ambas pruebas **se ejecutaron** en PC1. Sus resultados, conteos y huellas
SHA-256 están registrados en
[la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md), y el corpus vivo ya
se actualizó para dejar de presentarlos como pendientes.

Faltaba el paso que la **regla 25** obliga: una medición no es una decisión. La
regla de frontera y la aceptación del esquema de autenticación son decisiones
arquitectónicas, y **hasta este ADR no estaban registradas como tales**. Ese
hueco quedó marcado como PENDIENTE en
[la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md) §5, en
[el contrato funcional](../piloto-0-1/contrato-funcional.md) §14 y en las notas
de [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §21.1, §21.2
y §22. **Este ADR lo cierra.**

### 2. De dónde sale la evidencia

**HECHO DEL REPOSITORIO.** La fuente estable es
[la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md): fuentes reales
selladas por SHA-256, conteos de la población observada, muestra D23 de 30
códigos distintos, cruce real contra Materiales y comprobación del JWKS.

**Este ADR no repite esas mediciones y no vuelve a consultar Materiales.** Cita
el documento de evidencia y decide sobre él. Los conteos que aparecen aquí son
los mínimos necesarios para que la decisión se entienda sin abrir otro archivo;
el detalle agregado vive allí y no se duplica.

Conforme a la **regla 12**, aquí no hay ningún código SAP real, ningún
fragmento de BOM, ningún JWT, ningún refresh token, ninguna contraseña, ningún
correo y ninguna apikey.

### 3. Qué queda explícitamente fuera

Lista cerrada. Sin ella este ADR se desborda hacia decisiones que no le
corresponden.

| Fuera del alcance | Dónde se gobierna |
|---|---|
| **M1** — contrato estable de consulta | [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §19.1. Sigue bloqueante |
| **M2** — consulta por lote | [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §22.6. Abierto, no bloqueante |
| **M4** — versión y fecha del inventario activo | [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §9. Sin cambio |
| **M6** — semántica y temporalidad de los campos | [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §22.4. Parcial |
| **M7** — responsable y versionado del contrato | [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §19.2. Sigue bloqueante |
| **M8** — semántica de ausencia y cobertura | [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md). **ABIERTO** (§13) |
| **B9a, B9b, B9c** | [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md) §14. No implementados |
| Fachada contractual y `MaterialsPort` real | No existen. Trabajo posterior |
| Endpoints, frontend | Fuera |
| ONNX e INT8 | Hilo paralelo, sin dependencia |
| **D20** — retención del Incident Snapshot | [ADR 0022](0022-feedback-e-incident-snapshot-del-piloto.md). Puerta previa a liberar, sin cambio |

---

## Decisión

### 4. Lo que se decide, en una frase

**Para el dominio observado del Piloto Tampella V1**, el código SAP cruza la
frontera hacia Materiales como **cadena decimal exacta** (**M3-A**, §8), y la
autenticación de ELSA contra Materiales se diseña alrededor de **validación
asimétrica por JWKS** (**M5**, §11).

Ambas decisiones son **para V1**. Ninguna es universal, y el §10 dice
exactamente por qué M3-A no puede serlo.

### 5. Hecho medido que sostiene M3-A

**HECHO MEDIDO**, registrado en
[la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md) §2, sobre las
fuentes reales de Tampella y **sin aplicar ninguna normalización nueva**, como
el protocolo D23 exige.

| Observación | Valor |
|---|---|
| Secciones observadas | BOM y AMEF del XLSX, más el snapshot HTM |
| Almacenamiento en el XLSX | **numérico** |
| Almacenamiento en el HTM | **texto** |
| Longitud observable | **7** en todos los registros de las tres secciones |
| Valores textuales con cero inicial | **ninguno observado** |
| Whitespace externo | **ninguno observado** |
| Muestra D23 | 30 códigos distintos |
| Cruce real contra Materiales | 30 llamadas, 30 respuestas, 0 errores |
| Coincidencia exacta | 27 |
| Resultado devuelto sin el código exacto | 3, **exclusivamente** del patrón HTM-only |

### 6. El modo de fallo que la medición confirmó

**HECHO MEDIDO.** Los 3 casos sin coincidencia exacta **no son ruido**. Son la
confirmación empírica del modo de fallo que
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §2 anticipó sobre
prosa y que [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md) §5 ya
registró: una consulta que no coincide literalmente **cae en silencio** a
similitud sobre la descripción, y devuelve algo que no es lo que se pidió.

Ese hallazgo es la razón por la que M3-A no se limita a decir cómo se serializa
un código: tiene que decir, además, **qué no cuenta como igualdad** (§8, reglas
6 a 8).

### 7. El problema, enunciado con precisión

No es «qué formato tiene el código SAP». Es:

1. **Qué cadena exacta** se envía a Materiales cuando el valor de origen vino
   almacenado como número.
2. **Qué transformaciones están prohibidas** en esa frontera, para que un
   desajuste de representación no se disfrace de coincidencia.
3. **Qué no cuenta como equivalencia**, dado que la fuente real **sí** devuelve
   resultados aproximados cuando no hay coincidencia literal.

### 8. Decisión M3-A

**DECISIÓN TOMADA.** Para el dominio observado del Piloto Tampella V1, la
representación de frontera del código SAP —lo único que cruza hacia
Materiales— queda fijada así:

| # | Regla | Naturaleza |
|---|---|---|
| 1 | El código SAP **se transporta como cadena decimal exacta** | Serialización |
| 2 | Un valor del XLSX almacenado numéricamente **se serializa a su representación decimal observada** | Serialización |
| 3 | **No se agregan ceros** | Prohibición |
| 4 | **No se quitan ceros** | Prohibición |
| 5 | **No hay padding** a ninguna longitud fija | Prohibición |
| 6 | **Ni `strip` ni ninguna normalización adicional** valen como **regla de equivalencia** entre dos códigos | Prohibición |
| 7 | **`fuzzy` no es igualdad de código.** Un resultado aproximado **no prueba equivalencia** con el código pedido | Prohibición |
| 8 | **`NOT_RETURNED` no prueba inexistencia** | Prohibición |
| 9 | **Los valores textuales se preservan** tal como llegan | Preservación |

**Las reglas 7 y 8 no son nuevas.** La 7 materializa el invariante de
`lookup_material_by_code` de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §6; la 8 es la
semántica de `NOT_RETURNED` del mismo apartado. M3-A las hereda y las deja
explícitas **en el punto donde se decide la representación de frontera**, que
es donde alguien estaría tentado de romperlas para «hacer que cuadre».

#### 8.1 Qué separa esta decisión de la normalización interna

M3-A decide **la representación de frontera**, y nada más. Las otras tres
representaciones de
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §3.2 **siguen sin
confundirse**:

| Representación | Papel | Estado tras este ADR |
|---|---|---|
| Valor original de la fuente | Nunca se pierde | **Sin cambio** |
| Forma de almacenamiento en ELSA | Cómo se guarda | **Sin cambio** |
| Forma canónica de comparación | **Solo** para comparar dos códigos **dentro de** ELSA | **Confirmada como normalización interna.** Deja de ser «provisional», y **no** es lo que se envía |
| **Representación de frontera (`material_code`)** | Lo único que cruza hacia Materiales | **Decidida: M3-A** |

Concuerda con [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md)
§5 —la representación que exija Materiales se aplica **dentro de su
adaptador**, nunca en el núcleo— **sin reabrirlo**.

### 9. Consecuencia operativa de M3-A

**El adaptador de inventario deja de estar bloqueado por M3.** La prohibición
de [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §21.1 —«ningún
adaptador de inventario puede escribirse antes de M3»— **queda levantada**.

Esto **no autoriza a escribirlo**: autorizar trabajo es otra decisión, y la
fachada contractual (M1) sigue sin existir. Levanta la condición previa, no
concede el permiso.

### 10. Limitación de M3-A, que es parte de la decisión

**LIMITACIÓN.** El XLSX observado almacena los códigos **numéricamente**. Un
almacenamiento numérico **no puede conservar un cero inicial** si alguna vez lo
hubo.

Por tanto, y esto es vinculante:

- Esta medición **NO demuestra** que antes de llegar al XLSX nunca hubiera
  existido un cero inicial.
- Lo único demostrado es que **en el dominio observado no se observó ninguno**.
- **M3-A vale para el dominio observado del Piloto Tampella V1.**
- **Queda prohibido generalizar** la regla a todo SAP corporativo, y prohibido
  derivar de aquí un enunciado del tipo «SAP jamás usa ceros iniciales».

**M3 queda RESUELTO / CERRADO PARA V1, no universalmente.** Un dominio nuevo
—otro equipo, otra planta, otra exportación— **no hereda M3-A**: exige su
propia medición, y si contradice lo observado aquí, exige un ADR nuevo
(regla 25).

### 11. Decisión M5

**HECHO MEDIDO**, registrado en
[la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md) §4, sobre el entorno
real de Materiales.

| Observación | Valor |
|---|---|
| JWKS público | **HTTP 200** |
| Claves publicadas | **1** |
| `alg` | **`ES256`** |
| `kty` | **`EC`** |
| `use` | **`sig`** |
| `kid` | **presente** |
| Login real | **HTTP 200** |
| JWT de usuario real | **funcional** |
| Llamadas autenticadas al RPC real que respondieron | **30 de 30** |
| `rpc_errors` | **0** |

**DECISIÓN TOMADA. M5 queda RESUELTO / CERRADO PARA V1.**

De ello se sigue, y se decide:

1. **ELSA puede diseñarse alrededor de validación asimétrica por JWKS.** La
   validación que [ADR 0005](0005-verificacion-real-del-jwt-de-materiales.md)
   ya había decidido **queda confirmada contra el entorno real**, no supuesta.
2. La presencia de `kid` permite seleccionar la clave sin adivinar, y admite
   rotación sin cambiar el mecanismo.
3. **No es necesario ni aceptable compartir un secreto simétrico HS256.**

#### 11.1 La bifurcación de ADR 0021 §21.2 se resolvió por la primera rama

[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §21.2 fijó de
antemano las dos salidas. La comprobación pública demostró **firma
asimétrica**, de modo que:

- la validación de ELSA **se confirma** y M5 avanza — **esta rama es la que se
  dio**;
- el escenario de **firma simétrica heredada no se produjo**, y por tanto la
  **revisión arquitectónica explícita** que ese caso habría exigido **no hace
  falta**.

**La postura de ELSA frente a Materiales no cambia**: ELSA **no** se convierte
en depositaria de ningún secreto de Materiales, que era exactamente el riesgo
que §21.2 quería evitar.

#### 11.2 Firma pública observada del RPC

**HECHO MEDIDO.** La firma observada del procedimiento consultado fue:

```text
consultar_materiales(p_consulta, p_desde, p_limite)
```

Se registra **como observación**, no como contrato. **M1 sigue abierto**: esa
firma no está versionada del lado de Materiales, no tiene pruebas
contractuales, y este ADR **no la convierte** en la superficie estable que
[ADR 0021](0021-contrato-de-inventario-con-materiales.md) §19.1 exige.

### 12. Qué NO se decide aquí, aunque lo parezca

**Tabla explícita**, porque cada fila es una lectura que alguien hará.

| No significa | Estado real |
|---|---|
| «La cobertura de Materiales está demostrada» | **No.** Sigue `UNKNOWN` ([ADR 0023](0023-cobertura-desconocida-materiales-piloto.md)) |
| «Se conoce la freshness de SAP» | **No.** No se midió y no se infiere |
| «Hay un `extracted_at` conocido» | **No.** Sigue reservado y no inferible ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §9) |
| «Los 3 casos sin coincidencia exacta no existen en Materiales» | **No.** Son códigos para los que esa consulta no devolvió coincidencia exacta. Nada más |
| «27 de 30 es una tasa de acierto esperable» | **No.** La muestra no fue diseñada como estimador |
| «30 códigos representan todo el SAP corporativo» | **No.** Es una muestra de un dominio, no un censo |
| «La fachada contractual existe» | **No.** M1 sigue bloqueante |
| «El adaptador de inventario está autorizado» | **No.** Solo deja de estar bloqueado por M3 (§9) |
| «M3-A vale para cualquier dominio SAP» | **No.** Vale para el Piloto Tampella V1 (§10) |

### 13. M8 no se toca

**M8 continúa ABIERTO.**

- Su criterio de cierre sigue siendo
  [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3 —que alguno de
  los tres motivos reservados adquiera un mecanismo demostrable— y **no se ha
  cumplido ninguno**. **Este ADR no toca el §8.3.**
- **[ADR 0023](0023-cobertura-desconocida-materiales-piloto.md) no se reabre ni
  se modifica.** M8 sigue siendo **abierto y no bloqueante**, con los controles
  compensatorios que aquel ADR fijó.
- La prueba **A6c sigue desactivada**, y la ausencia autoritativa sigue
  **rechazada en código**.
- **B9a, B9b y B9c siguen siendo bloqueantes** y siguen sin implementarse.

Ni M3 ni M5 aportan nada a M8: **medir el formato de un código y verificar una
firma no dice nada sobre qué ámbito cubre un snapshot**. Son ejes
independientes, y confundirlos sería exactamente el error que
[ADR 0023](0023-cobertura-desconocida-materiales-piloto.md) §8 previene.

---

## Consecuencias

### 14. Decisiones diferidas de ADR 0021 §22 que este ADR cierra

**Tres, y solo tres.**

| # en §22 | Decisión diferida | Se decidía «tras» | Resultado |
|---|---|---|---|
| **1** | Representación de frontera `ELSA → Materiales` | M3 | **CERRADA: M3-A** (§8), para V1 |
| **2** | Confirmación o corrección de la forma canónica de comparación | M3 | **CERRADA: confirmada** como normalización **interna**, distinta de la de frontera (§8.1) |
| **3** | Aceptación del algoritmo de firma | M5 | **CERRADA: `ES256` asimétrico aceptado.** Sin revisión arquitectónica, porque el escenario simétrico no se dio (§11.1) |

**Las filas 4 a 12 de §22 no se tocan.** En particular siguen diferidas la
semántica completa de `dado_de_baja`, `ubicacion` y `ambito` (M6), la consulta
por lote (M2), el ocupante inicial del Contract Owner (M7) y la forma concreta
del tipo de retorno de `MaterialsPort`.

### 15. Qué cambia en los documentos existentes

**Cambios mínimos, solo de autoridad y referencia.** Ningún cuerpo normativo se
reescribe, **ningún documento de cierre se toca** —son registros históricos— y
**la historia se conserva**: donde un documento describía correctamente que M3
o M5 estaban pendientes en el momento de una decisión anterior, ese texto
permanece y la nota fechada dice qué cambió después.

| Documento | Cambio |
|---|---|
| [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §21.1, §21.2, §22, §25 | Las notas fechadas pasan a citar **este ADR** como autoridad de la decisión, en lugar de dejarla como PENDIENTE |
| [ADR 0020](0020-capacidades-componibles-y-planes-de-ejecucion.md) §5, §17 | La nota fechada cita este ADR |
| [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md) §5 | La nota fechada cita este ADR, **sin alterar** lo que aquel ADR decide |
| [Contrato funcional](../piloto-0-1/contrato-funcional.md) §10 (B3, B6), §14 | B3 y B6 y las filas de M3 y M5 citan este ADR; el PENDIENTE del ADR desaparece |
| [Evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md) §5 | La fila del ADR pendiente pasa a **resuelta por este ADR** |

**El detalle agregado de la evidencia no se duplica en ninguno de ellos.** Vive
en [la evidencia M3/M5](../piloto-0-1/evidencia-m3-m5-pc1.md) y se cita.

### 16. Qué queda abierto después de esta decisión

| # | Pendiente | Estado |
|---|---|---|
| 1 | **M8** | **ABIERTO.** Criterio de cierre [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3, **sin cumplir**. No bloqueante desde [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md) |
| 2 | **M1** — fachada contractual | **Bloqueante.** La fachada **no existe** |
| 3 | **M4**, **M6**, **M7** | **Conservan su estado real.** Ninguno se cierra por asociación con M3 o M5 |
| 4 | **M2** — consulta por lote | Abierto, **no** bloqueante |
| 5 | **B9a, B9b, B9c** | **Bloqueantes**, no implementados |
| 6 | **D20** — retención del Incident Snapshot | **Puerta previa a liberar**, sin cambio |
| 7 | **Subbloque 5.0.b** | **ABIERTO.** Este ADR **no lo cierra**. Su documento de cierre es obligatorio (regla 26) cuando se declare cerrado |

### 17. Riesgos

| Riesgo | Mitigación |
|---|---|
| Leer M3-A como una regla global de SAP | §10 lo prohíbe por escrito, y el §12 lo repite en la tabla de lecturas erróneas |
| Que alguien reintroduzca padding o `strip` «para que cuadre» un caso | Reglas 3 a 6 del §8, enunciadas como prohibiciones y no como preferencias |
| Que un resultado aproximado se acepte como coincidencia | Regla 7 del §8 más el invariante verificable de [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §6: la violación es un fallo de contrato, no un resultado peor |
| Leer «M3 y M5 resueltos» como «el contrato con Materiales está cerrado» | §3 y §16: M1, M4, M6 y M7 siguen con su estado, y la fachada no existe |
| Leer este ADR como un avance sobre cobertura | §13: ejes independientes, y [ADR 0023](0023-cobertura-desconocida-materiales-piloto.md) intacto |
| Que la firma observada del RPC se tome por contrato | §11.2 la registra como observación y recuerda que M1 sigue abierto |
| Que un dominio nuevo herede M3-A sin medir | §10: exige medición propia y, si contradice, ADR nuevo |

### 18. Alternativas descartadas

| Alternativa | Por qué se descarta |
|---|---|
| **Declarar una regla global «SAP no usa ceros iniciales»** | El XLSX almacena numéricamente: la evidencia **no puede** sostener esa afirmación (§10). Sería inventar alcance sobre una medición real |
| **Normalizar con padding a longitud 7** | La longitud 7 fue **observada**, no garantizada. Padding a una longitud observada convierte una coincidencia en una suposición, y ocultaría justo el fallo que la medición encontró |
| **Aceptar el resultado aproximado como coincidencia cuando no hay exacta** | Es el modo de fallo silencioso que [ADR 0021](0021-contrato-de-inventario-con-materiales.md) §2 describe y que los 3 casos confirmaron (§6). Lo haría invisible |
| **Dejar M3-A solo en el documento de evidencia** | Un registro de evidencia no es una decisión arquitectónica. La **regla 25** exige ADR, y sin él la regla de frontera no tiene autoridad citable |
| **Aprovechar este ADR para cerrar M8** | Su criterio de cierre exige un **mecanismo demostrable**, no una decisión ([ADR 0021](0021-contrato-de-inventario-con-materiales.md) §8.3). Cerrarlo aquí sería exactamente lo que ese apartado prohíbe |
| **Aprovechar este ADR para cerrar 5.0.b** | M1, M4, M6, M7 y B9a–B9c siguen abiertos. El cierre exige su documento propio (regla 26) |

### 19. Trazabilidad de los requisitos de este ADR

| # | Requisito | Sección |
|---|---|---|
| 1 | Por qué existe: la regla 25 sin cumplir | Contexto §1 |
| 2 | Fuente de evidencia estable, sin duplicar | Contexto §2 |
| 3 | Alcance cerrado y exclusiones | Contexto §3 |
| 4 | Hecho medido que sostiene M3-A | §5 |
| 5 | Modo de fallo confirmado | §6 |
| 6 | **Decisión M3-A**, nueve reglas | §8 |
| 7 | Separación frente a la normalización interna | §8.1 |
| 8 | Consecuencia sobre el adaptador | §9 |
| 9 | **Limitación obligatoria** de M3-A | §10 |
| 10 | **Decisión M5** | §11 |
| 11 | Bifurcación de ADR 0021 §21.2 resuelta | §11.1 |
| 12 | Firma del RPC como observación, no contrato | §11.2 |
| 13 | Lo que no se decide | §12 |
| 14 | **M8 intacto** | §13 |
| 15 | Diferidas §22 que se cierran: 1, 2 y 3 | §14 |
| 16 | Cambios en documentos existentes | §15 |
| 17 | Qué queda abierto; 5.0.b no se cierra | §16 |
| 18 | Riesgos | §17 |
| 19 | Alternativas descartadas | §18 |

## Ver también

- [ADR 0002 — Identidad de Materiales, autorización en el backend](0002-identidad-de-materiales-autorizacion-en-backend.md)
- [ADR 0005 — Verificación real del JWT de Materiales](0005-verificacion-real-del-jwt-de-materiales.md)
- [ADR 0020 — Capacidades componibles y planes de ejecución controlados](0020-capacidades-componibles-y-planes-de-ejecucion.md)
- [ADR 0021 — Contrato de inventario con Materiales (V1)](0021-contrato-de-inventario-con-materiales.md)
- [ADR 0023 — Cobertura desconocida de Materiales, aceptada bajo controles compensatorios](0023-cobertura-desconocida-materiales-piloto.md)
- [Evidencia de las mediciones M3 y M5 (PC1)](../piloto-0-1/evidencia-m3-m5-pc1.md)
- [Contrato funcional del Piloto 0.1](../piloto-0-1/contrato-funcional.md)
