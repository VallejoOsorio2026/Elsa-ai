# Evidencia de las mediciones M3 y M5 (PC1)

Registro agregado de las dos comprobaciones reales ejecutadas en PC1 sobre el
entorno real de Materiales y sobre las fuentes reales de Tampella.

> **Qué es este documento.** Un registro de evidencia, no un documento de
> cierre. **No cierra el subbloque 5.0.b**, que sigue abierto. El cierre de
> 5.0.b se redactará aparte, según
> [el estándar de cierre de bloques](../project/BLOCK_CLOSURE_STANDARD.md).

> **Regla 12 de [`CLAUDE.md`](../../CLAUDE.md).** Aquí no hay ningún código SAP
> real, ningún fragmento de BOM, ningún JWT, ninguna clave, ningún correo y
> ninguna contraseña. Solo conteos, propiedades observadas y huellas SHA-256 de
> archivos que **viven fuera de Git**.

- Fecha de registro: **2026-09-19**
- Ejecución: **PC1**, por el responsable del proyecto, fuera de una sesión de
  asistente
- Bloque: 5.0, subbloque **5.0.b**
- Protocolo aplicado: **D23**, definido en
  [el contrato funcional del Piloto 0.1](contrato-funcional.md) §11

Cada afirmación va marcada según el estándar de cierre: **HECHO MEDIDO**,
**DECISIÓN TOMADA** o **LIMITACIÓN / PENDIENTE**. La distinción es el contenido
principal de este documento: sin ella, una cifra medida y una regla decidida se
leen igual.

---

## 1. Fuentes reales utilizadas

**HECHO MEDIDO.** Las dos fuentes son archivos reales de Tampella, controlados
**fuera del repositorio**. Se registra su huella, no su contenido.

| Archivo | SHA-256 |
|---|---|
| `BOM Tampella.xlsx` | `F37ED62BAB693002FFE99D55229EFEA4CF6999A36FFD06005B07D16E2E4C582F` |
| `TAMPELLA_BOM.HTM` | `9A8C419CDE00D6843694603859A4D05D1A1DDC2CBFBE8B64100CD6A6F4691EE0` |

El XLSX aporta dos secciones con códigos —**BOM** y **AMEF**—; el HTM es el
snapshot exportado.

---

## 2. M3 — formato real del código SAP

### 2.1 Población observada

**HECHO MEDIDO.** Conteos sobre las tres secciones, **sin aplicar ninguna
normalización nueva**, tal como D23 exige.

| Sección | Registros | Códigos distintos | Almacenamiento | Longitud observable |
|---|---|---|---|---|
| BOM (XLSX) | 49 | 48 | entero | 7 en los 49 |
| AMEF (XLSX) | 59 | 47 | entero | 7 en los 59 |
| HTM | 56 | 54 | texto | 7 en los 56 |

### 2.2 Intersección entre fuentes

**HECHO MEDIDO.** Comparación **sin padding, sin `strip` y sin normalización
nueva**.

| Observación | Valor |
|---|---|
| Unión XLSX ∪ HTM | 55 códigos distintos |
| Presentes exactamente en XLSX **y** HTM | 47 |
| Presentes en BOM **y** AMEF **y** HTM | 47 |
| Solo en XLSX | 1 |
| Solo en HTM | 7 |

### 2.3 Propiedades observadas del formato

**HECHO MEDIDO.**

- **No se observó ningún valor textual con cero inicial.**
- **No se observó whitespace externo** en ningún valor.
- Los valores del XLSX están almacenados **numéricamente**; los del HTM, **como
  texto**.
- La longitud observable fue **7 en todos los registros de las tres secciones**.

### 2.4 Muestra D23

**HECHO MEDIDO.** Muestra de **30 códigos reales distintos**, el mínimo que D23
fija.

| Observación | Valor |
|---|---|
| Códigos de la muestra | 30 |
| Presentes en BOM | 24 |
| Presentes en AMEF | 23 |
| Presentes en HTM | 29 |
| Coincidencia exacta XLSX ↔ HTM | 23 |
| Solo en XLSX | 1 |
| Solo en HTM | 6 |

### 2.5 Cruce real contra Materiales

**HECHO MEDIDO.** La misma muestra de 30, consultada contra el RPC real de
Materiales con un JWT de usuario real.

| Observación | Valor |
|---|---|
| Códigos consultados | 30 |
| Llamadas RPC exitosas | 30 |
| Errores de RPC | 0 |
| Coincidencia **exacta** | 27 |
| Resultado devuelto **sin** el código exacto | 3 |
| `NOT_RETURNED` | 0 |

**HECHO MEDIDO.** Los 3 casos sin coincidencia exacta fueron **exclusivamente**
códigos con el patrón `BOM=False`, `AMEF=False`, `HTM=True`.

Esta misma medición ya está citada en
[ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md) §5, que
enumera qué demuestra y qué **no** demuestra. Aquel apartado sigue vigente sin
cambios.

### 2.6 Artefactos sellados

**HECHO MEDIDO.** Archivos locales, **fuera de Git**.

| Artefacto | SHA-256 |
|---|---|
| `m3_d23_v2_1.py` | `24206FA1EACC8D0EEDB920D9DB5347BE4A2832A1710F6B896E5D10418D1B0DE4` |
| `m3_d23_detalle_v2_1.csv` | `69C271274FF39471436AEC6B4F0AB4F7C044871A19EB0FCCE5CD2F3568DA070A` |
| `m3_d23_resumen_v2_1.txt` | `885C4B294043B6516952941350A8CF3125BBB8A942DCF7619EC7CBEFEB931EED` |
| `m3_cruce_materiales.py` | `C55F4DBF8216A244D360D40F9AB6F1C226E7A9D78ADA03DA395E89F7E6A11CCC` |
| `m3_cruce_materiales.txt` | `1E661F70AACE4EC6BB129E13FD0A48C5FFC749E4DE19B8B1CFABCE0795A8B703` |

---

## 3. M3-A — la regla de frontera decidida

**DECISIÓN TOMADA.** Sobre la evidencia del §2, **M3 queda resuelto para V1
como `M3-A`**. La decisión se formaliza en
[ADR 0024](../adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
§8, que es su autoridad; lo que sigue es la misma regla, registrada aquí junto
a la evidencia que la sostiene.

La regla, completa:

1. Un código SAP **se transporta como cadena decimal exacta**.
2. Un valor del XLSX almacenado numéricamente **se serializa a su
   representación decimal observada**.
3. **No se agregan ceros.**
4. **No se quitan ceros.**
5. **No hay padding** a ninguna longitud fija.
6. **`fuzzy` no es una equivalencia de código.** Un resultado aproximado nunca
   prueba que el código pedido y el devuelto sean el mismo.
7. **Los valores textuales se preservan** tal como llegan.
8. **`NOT_RETURNED` no prueba inexistencia**, conforme a
   [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §6.

Las reglas 6 y 8 no son nuevas: M3-A las hereda y las deja explícitas en el
punto donde se decide la representación de frontera.

### 3.1 Limitación que esta decisión no puede superar

**LIMITACIÓN.** El XLSX almacena los códigos observados **numéricamente**. Por
construcción, un almacenamiento numérico no conserva un cero inicial si alguna
vez lo hubo.

Por tanto esta medición **no demuestra** que históricamente nunca haya existido
un cero inicial antes de llegar al XLSX. Demuestra únicamente que **en el
dominio observado del Piloto Tampella V1 no se observó ninguno**.

**M3-A aplica a ese dominio observado.** **No autoriza** una regla global del
tipo «SAP jamás usa ceros iniciales», y nadie debe derivarla de aquí.

### 3.2 Lo que esta medición no afirma

**LIMITACIÓN.** Ninguna de las cifras del §2 debe leerse como:

- cobertura completa del inventario de Materiales;
- freshness de SAP;
- un `extracted_at` conocido;
- que los 3 casos sin coincidencia exacta **no existan** en Materiales;
- que 30 códigos representen todo el SAP corporativo.

---

## 4. M5 — el JWT del usuario en la llamada real

### 4.1 JWKS público

**HECHO MEDIDO.** Comprobación contra el JWKS público real de Materiales.

| Observación | Valor |
|---|---|
| Respuesta HTTP | 200 |
| Claves publicadas | 1 |
| `alg` | `ES256` |
| `kty` | `EC` |
| `use` | `sig` |
| `kid` | presente |

### 4.2 Prueba autenticada

**HECHO MEDIDO.**

| Observación | Valor |
|---|---|
| Login | HTTP 200 |
| JWT obtenido | sí |
| JWT mostrado o almacenado en la evidencia | **no** |
| Llamadas autenticadas a `consultar_materiales` que respondieron | 30 de 30 |
| `rpc_errors` | 0 |

**HECHO MEDIDO.** Firma pública observada del RPC:

```text
consultar_materiales(p_consulta, p_desde, p_limite)
```

### 4.3 Artefactos sellados

**HECHO MEDIDO.** Archivos locales, **fuera de Git**.

| Artefacto | SHA-256 |
|---|---|
| `m5_m3_materiales.py` | `07D58AC8E41859B81204B1B2E6FEF0F961C44C1F954B35A6B8364920A11DA472` |
| `m5_m3_materiales_detalle.json` | `7B1FB8291408AADF2FBD98A3F6BEBAD3E0027654828C4911CB05DC8F5D2CC65F` |
| `m5_m3_materiales_resumen.txt` | `0A4FE74EC4B8C7C70532BEE727884E41DF50006CADA7617204671683CF2D2AF9` |

### 4.4 La decisión

**DECISIÓN TOMADA.** **M5 queda resuelto para V1**, formalizado en
[ADR 0024](../adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md)
§11.

Queda demostrado, en el entorno real observado, que:

- Materiales publica un JWKS **asimétrico `ES256` / `EC`**;
- existe `kid`;
- un usuario real puede autenticarse;
- el JWT resultante **funciona contra el RPC real**;
- **no es necesario ni aceptable compartir un secreto simétrico HS256.**

Esto resuelve por la vía positiva la bifurcación que
[ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §21.2 dejó
planteada: la comprobación pública demostró firma **asimétrica**, de modo que
la validación de ELSA se confirma y **no se activa** la revisión arquitectónica
que el escenario simétrico habría exigido.

---

## 5. Qué sigue abierto

**PENDIENTE.** Esta evidencia no cierra nada más que M3 y M5 para V1.

| # | Pendiente | Estado | Responsable |
|---|---|---|---|
| 1 | **M8** — semántica de ausencia y cobertura | **ABIERTO**, y **no bloqueante** desde [ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md). Su criterio de cierre sigue siendo [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §8.3, **sin cumplir**. **Este documento no lo toca** | Responsable del proyecto |
| 2 | **M1, M4, M6, M7** | **Conservan su estado real.** Ninguno se cierra por asociación con M3 o M5 | Sus propios subbloques |
| 3 | **M2** — consulta por lote | **Abierto y no bloqueante**, sin cambio | Responsable del proyecto |
| 4 | ~~ADR que registre `M3-A` y el cierre de M5 para V1~~ | **RESUELTO.** Es [ADR 0024](../adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md), que decide M3-A (§8) y el cierre de M5 (§11) y **cierra los puntos 1, 2 y 3** de las decisiones diferidas de [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §22, conforme a la regla 25 | — |
| 5 | **B9a, B9b, B9c** | **Bloqueantes nuevos** de [ADR 0023](../adr/0023-cobertura-desconocida-materiales-piloto.md) §14. **No implementados** | Responsable del proyecto |
| 6 | **Cierre del subbloque 5.0.b** | **PENDIENTE.** Obligatorio (regla 26). Este documento **no lo es** | Responsable del proyecto |

---

## 6. Documentos actualizados por esta evidencia

Los cuerpos normativos **no se reescriben**. Donde un documento describía
correctamente que M3 o M5 estaban pendientes en el momento de una decisión
anterior, **esa historia se conserva** y se le añade una nota de estado
posterior fechada.

| Documento | Qué se añadió |
|---|---|
| [ADR 0024](../adr/0024-validacion-real-frontera-codigo-sap-y-autenticacion-materiales.md) | **Creado.** Formaliza M3-A (§8) y el cierre de M5 (§11) como decisión arquitectónica, y cierra los puntos 1, 2 y 3 de las diferidas de [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §22 |
| [Contrato funcional](contrato-funcional.md) §10, §11, §13, §14 | B3 y B6 marcados como resueltos para V1; resultado de la medición en el §11; R1 actualizado; §14 retira «Muestra concreta de la medición M3» de las decisiones abiertas |
| [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) §3.2, §20, §21.1, §21.2, §22, §25 | Notas de estado posterior. **Los cuerpos normativos y el §8.3 no se tocan** |
| [ADR 0020](../adr/0020-capacidades-componibles-y-planes-de-ejecucion.md) §5, §17 | Notas de estado posterior sobre M3 y M5 |

**No se modifica ningún documento de cierre.** Son registros históricos, y
[el cierre del subbloque 5.0.c.1](../bloque-5-0-c-1-politica-ausencia-segura-cierre.md)
declara explícitamente que los resultados posteriores de M3 y M5 no entran en
él, sino en el cierre de 5.0.b.
