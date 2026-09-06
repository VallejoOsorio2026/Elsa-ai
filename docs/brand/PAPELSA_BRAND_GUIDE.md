# Identidad visual PAPELSA

Transcripción técnica del **Manual de Marca PAPELSA** para uso dentro de este
repositorio. Recoge únicamente lo que el manual define; nada aquí es invención
ni interpretación libre.

**Fuente:** Manual de Marca PAPELSA, 30 páginas. El PDF es material corporativo
privado y **no se versiona** (`.gitignore` bloquea `*.pdf` y `*.PDF`). Cada
afirmación de este documento cita la página del manual de la que sale.

Este documento describe la marca **PAPELSA**. Cómo la aplica el producto ELSA se
define en [`ELSA_UI_BRAND_RULES.md`](ELSA_UI_BRAND_RULES.md); los valores
listos para código están en [`DESIGN_TOKENS.md`](DESIGN_TOKENS.md).

---

## 1. Estructura de la marca

La marca se compone de tres elementos (pp. 5–6):

| Elemento | Descripción |
|---|---|
| **Símbolo** | La forma abstracta a la izquierda. |
| **Logotipo / Nombre** | La palabra `papelsa` en minúsculas, con `®`. |
| **Slogan** | Elemento **opcional y condicionado** (ver §7). |

El símbolo nace de tres referencias superpuestas (p. 7): la letra «P» inicial del
nombre, un molinillo de viento —el poder de la naturaleza y la energía limpia— y
un rollo o tambor de papel. La abstracción resultante transmite movimiento e
invita al reciclaje y a la economía circular.

El logotipo se escribió en minúsculas y redondeado para transmitir cercanía y
amabilidad, y **se elaboró a partir de la tipografía Comfortaa** (p. 8).

---

## 2. Colores corporativos

Los siete colores del manual (p. 14), con los tres grupos que el propio manual
establece. *«La aplicación de estos colores debe ser constante.»*

### Colores principales

| | Pantone | CMYK | RGB | HEX |
|---|---|---|---|---|
| Verde | 2300 C | 36 0 87 2 | 169 194 63 | `#A9C23F` |
| Petróleo | 2238 C | 98 6 30 41 | 0 105 117 | `#006975` |

### Slogan

| | Pantone | CMYK | RGB | HEX |
|---|---|---|---|---|
| Azul grisáceo | 5483 C | 68 23 28 14 | 79 134 142 | `#4F868E` |

### Colores complementarios

| | Pantone | CMYK | RGB | HEX |
|---|---|---|---|---|
| Gris oscuro | 447 C | 69 60 56 66 | 51 51 51 | `#333333` |
| Gris medio | 4292 C | 54 44 43 29 | 109 109 109 | `#6D6D6D` |
| Gris claro | Gris Frío 4 C | 29 22 23 3 | 188 188 188 | `#BCBCBC` |
| Blanco | — | 0 0 0 0 | 255 255 255 | `#FFFFFF` |

`#4F868E` es, según el manual, el color **del slogan**, no un color principal ni
complementario. Esa distinción importa: ELSA no usa el slogan (§7), así que
`#4F868E` queda fuera de su uso previsto y sólo se emplea bajo la regla que fija
[`ELSA_UI_BRAND_RULES.md`](ELSA_UI_BRAND_RULES.md).

El logotipo a color usa exclusivamente `#006975` y `#A9C23F`; se verificó
extrayendo los vectores del manual (pp. 5, 9, 13, 17): no aparece ningún otro
color en el arte.

---

## 3. Tipografías corporativas

El manual define dos familias (p. 15):

| Familia | Pesos declarados |
|---|---|
| **Comfortaa** | Light, Regular, Bold |
| **Futura** | Medium, Bold |

Ambas se muestran con juego completo de mayúsculas, minúsculas, `Ññ`, cifras y
signos, es decir, están previstas para texto corrido y no sólo para titulares.

El manual **no asigna** una familia a un rol concreto (títulos, cuerpo,
interfaz) ni define escalas tipográficas. Esa jerarquía es una decisión de
producto y se toma —declarada como tal— en
[`ELSA_UI_BRAND_RULES.md`](ELSA_UI_BRAND_RULES.md).

Lo único que el manual sí ata es el origen del logotipo: **Comfortaa** (p. 8).

---

## 4. Proporciones (planimetría)

Las proporciones se definen sobre una retícula modular proporcional al valor
`X`, «de esta manera aseguramos la correcta proporción de la marca sobre
cualquier soporte y medidas» (pp. 9–10). El módulo `X` equivale a la altura del
símbolo `®`.

| Versión | Ancho | Alto |
|---|---|---|
| Logotipo (sin slogan) | `46X` | `9X` |
| Logotipo con slogan | `46X` | `12X` |

La proporción del logotipo sin slogan es por tanto **46:9 ≈ 5,111:1**. Medido
sobre los vectores extraídos del manual, el arte real da 448,594 × 87,609 pt,
esto es **5,120:1** — la diferencia (0,2 %) es el desborde del `®` sobre la
retícula. Los assets de este repositorio conservan la proporción del arte real.

El **símbolo aislado** es cuadrado: 68,724 × 68,757 pt, **1:1** (medido).

---

## 5. Área de seguridad

*«El espacio que debe permanecer libre alrededor de la marca sin que ningún otro
elemento rebase este límite para evitar la contaminación visual del logotipo»*
(pp. 11–12).

**Área de seguridad = `2X` por los cuatro lados**, tanto en la versión sin
slogan como en la versión con slogan. Es proporcional al tamaño de
reproducción: no es una medida absoluta, escala con la marca.

Como el logotipo mide `9X` de alto, `2X` equivale a **2/9 ≈ 22,2 % de la altura
del logotipo** aplicado a cada lado. Esa es la forma operativa de calcularlo en
pantalla, donde no se razona en módulos sino en píxeles.

---

## 6. Tamaños mínimos

*«Para asegurar la legibilidad de la marca»* (p. 13):

| Soporte | Mínimo |
|---|---|
| Impresos | **3,5 cm** |
| Digital | **80 px** |

Ambas medidas se toman sobre el **ancho del logotipo completo** (símbolo +
nombre): en el manual la cota está dibujada horizontalmente bajo la marca.
A 80 px de ancho, la proporción 46:9 da ≈ 15,7 px de alto.

El manual **no fija un tamaño mínimo para el símbolo aislado**. Es un vacío
real; ver §9.

---

## 7. Slogan: cuándo se usa

Regla explícita del manual (p. 6):

> «Solo se recomienda la inclusión del slogan, dentro de las aplicaciones del
> logotipo, cuando se trate de comunicaciones de **corto plazo (máximo un
> año)**. Para piezas con exposición mayor a ese tiempo, se recomienda la
> aplicación del **logo sin el slogan**.»

ELSA es una herramienta corporativa permanente, no una campaña. Por tanto usa
**siempre el logotipo sin slogan**, y esa elección es la que el manual indica,
no una preferencia de diseño.

---

## 8. Versiones y usos

### 8.1 Versiones correctas (pp. 17–18)

> «Siempre que sea posible se utilizará el logotipo en su **versión principal a
> color**. En el caso que no sea posible por razones técnicas se utilizará la
> versión en blanco y negro o en reserva.»

| Versión | Composición (extraída del arte del manual) |
|---|---|
| **Principal a color** | Nombre y parte oscura del símbolo `#006975`; parte clara del símbolo `#A9C23F`. |
| **Principal positivo** | Nombre y parte oscura del símbolo `#333333`; parte clara del símbolo `#6D6D6D`. |
| **Principal negativo** | Nombre y parte oscura del símbolo `#FFFFFF`; parte clara del símbolo `#DCDCDC`. |

En el manual el negativo se muestra sobre fondo `#006975`.

### 8.2 Aplicaciones correctas sobre fondos ajenos (pp. 19–20)

> «La máxima visibilidad, legibilidad y contraste tienen que asegurarse en todas
> las aplicaciones. Si el logotipo se tiene que aplicar sobre fondos no
> corporativos o fotografías debe aplicarse la mejor opción o aplicar en blanco
> o negro, en función de la luminosidad del fondo.»

Es decir: sobre imagen clara → positivo; sobre imagen oscura → negativo.

### 8.3 Aplicaciones incorrectas (pp. 21–22)

> «En ningún caso se podrán emplear otros colores que no sean los especificados
> dentro del manual de marca. **No se permite la aplicación de efectos gráficos
> ni deformaciones.**»

Prohibiciones ilustradas explícitamente:

- **No distorsionar** — no alterar la proporción 46:9; nunca escalar en un solo eje.
- **No rotar** — la marca es horizontal; ningún ángulo es admisible.
- **No modificar los colores** — ni sustituirlos, ni saturarlos, ni recolorear.
- **Utilizar adecuadamente el símbolo** — no alterar la relación entre sus dos
  colores ni su construcción.
- **No alterar su orden** (versión con slogan) — la secuencia de los elementos es fija.

De la regla general se sigue, además: sin sombras, sin degradados, sin
contornos, sin brillos, sin filtros — «efectos gráficos» está prohibido en
bloque, no por lista cerrada.

---

## 9. Lo que el manual no define

Estos puntos **no** aparecen en el manual. No se inventan aquí: se declaran como
vacíos, y donde ELSA necesita una respuesta para funcionar, la decisión se toma
en [`ELSA_UI_BRAND_RULES.md`](ELSA_UI_BRAND_RULES.md) **marcada como decisión de
producto**, no como norma de marca.

1. **Tamaño mínimo del símbolo aislado.** Sólo se acota el logotipo completo.
2. **Jerarquía tipográfica** para producto digital: qué familia y qué peso
   corresponde a título, cuerpo, etiqueta o dato.
3. **Escala tipográfica** y alturas de línea.
4. **Colores semánticos de aplicación** (éxito, advertencia, error, información).
   El manual es un manual de marca, no un sistema de diseño de interfaz.
5. **Reglas responsive**: comportamiento de la marca en anchos reducidos.
6. **Modo oscuro** de interfaz.
7. **Iconografía** propia.
8. **Uso del símbolo aislado como identificador** (favicon, avatar): el manual lo
   nombra como componente de la marca, pero no autoriza ni prohíbe expresamente
   su uso independiente.

## 10. Hallazgos sobre el propio manual

Detectados al extraer el arte, y anotados por honestidad documental:

- **El gris del negativo no es corporativo.** La versión negativa usa `#DCDCDC`
  para la parte clara del símbolo (p. 17). `#DCDCDC` **no está** entre los siete
  colores de la p. 14; el gris claro corporativo es `#BCBCBC`. Los assets de
  este repositorio reproducen `#DCDCDC` por fidelidad al arte original, pero la
  discrepancia debería resolverla PAPELSA.
- **`#4F868E` queda sin uso en ELSA.** Está definido como color del slogan, y
  ELSA no usa slogan.
