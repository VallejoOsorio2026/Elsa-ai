# Reglas de marca en la interfaz de ELSA

Cómo aplica ELSA la identidad de PAPELSA. Este documento **no reinterpreta el
manual**: lo aplica, y donde el manual calla, decide de forma explícita y
marcada como decisión de producto.

- Norma de marca: [`PAPELSA_BRAND_GUIDE.md`](PAPELSA_BRAND_GUIDE.md)
- Valores en código: [`DESIGN_TOKENS.md`](DESIGN_TOKENS.md)
- Assets: [`../../assets/brand/`](../../assets/brand/)

Regla de precedencia: **ante cualquier conflicto, manda el Manual de Marca.** Si
una necesidad de interfaz sólo puede resolverse contradiciendo el manual, no se
resuelve por cuenta propia: se pregunta a PAPELSA.

---

## 1. Qué es ELSA frente a la marca PAPELSA

ELSA es una herramienta interna de PAPELSA, no una marca comercial
independiente. Consecuencias directas:

1. **La marca visible es PAPELSA.** ELSA es el nombre del producto, escrito como
   texto, no como logotipo.
2. **ELSA no tiene logotipo propio** y no se crea uno en este bloque. El manual
   no contempla submarcas y no corresponde inventarlas.
3. **No se construye un lockup** que combine el logotipo PAPELSA con la palabra
   ELSA en una sola pieza gráfica. Eso sería modificar la marca, que el manual
   prohíbe (pp. 21–22). Los dos elementos conviven **separados**, respetando el
   área de seguridad del logotipo.
4. Escrito, el nombre es **ELSA** en versales. No se estiliza, no se le aplican
   los colores del logotipo ni se le añaden efectos.

> **Duda abierta para PAPELSA.** Si en el futuro se quiere una identidad
> conjunta PAPELSA + ELSA (una pieza única de cabecera, un icono de aplicación
> con la «E»), eso es una extensión del manual y debe autorizarla PAPELSA. No se
> improvisa desde el código.

## 2. Uso del logotipo en pantalla

### 2.1 Qué asset se usa y cuándo

| Situación | Asset | Fundamento |
|---|---|---|
| Cabecera sobre fondo claro | `papelsa-logotipo-color.svg` | «Siempre que sea posible… versión principal a color» (p. 17) |
| Cabecera sobre fondo `#006975` o `#333333` | `papelsa-logotipo-blanco.svg` | Versión negativa (p. 17) |
| Impresión monocroma, fax, sello | `papelsa-logotipo-positivo.svg` | Versión positiva (p. 17) |
| Favicon, icono de aplicación, avatar | `papelsa-simbolo-color.svg` | Ver §2.4 |

La versión a color es la predeterminada. Las monocromas se usan por
**imposibilidad técnica o falta de contraste**, nunca por preferencia estética.

### 2.2 Área de seguridad

`2X` por los cuatro lados, es decir **22,22 % de la altura del logotipo**
(`--papelsa-logo-area-seguridad`). Dentro de ese margen no entra **nada**: ni
texto, ni el nombre ELSA, ni menús, ni bordes de contenedor, ni el borde de la
ventana.

En la práctica, el logotipo se envuelve en su propio contenedor con `padding`
proporcional, y ese contenedor no se comparte con ningún otro elemento.

### 2.3 Tamaño mínimo

**80 px de ancho** para el logotipo completo (p. 13). Es un mínimo absoluto: si
el espacio disponible no permite 80 px, **no se encoge el logotipo** — se cambia
de elemento (§4.2).

Se recomienda no bajar de 120 px en cabeceras de escritorio: 80 px es el límite
de legibilidad, no un objetivo.

### 2.4 Símbolo aislado

El manual describe el símbolo como componente de la marca (p. 5) pero **no
autoriza ni prohíbe explícitamente su uso independiente**, ni le fija tamaño
mínimo. Decisión de producto, conservadora:

- El símbolo aislado se usa **sólo** donde un formato cuadrado es obligatorio y
  el logotipo completo es imposible: favicon, icono de aplicación instalada,
  avatar, y la cabecera en anchos muy reducidos (§4.2).
- **Mínimo adoptado: 24 px.** Es una decisión de ELSA, no una norma del manual.
  Se fija en 24 px porque por debajo el contraentrelazado de los dos colores deja
  de distinguirse; el favicon a 16 px es la excepción impuesta por el navegador.
- El símbolo aislado **no sustituye** al logotipo en la cabecera de escritorio.
- Conserva siempre sus dos colores y su proporción 1:1.

> **Duda abierta para PAPELSA:** confirmar que el uso del símbolo aislado como
> favicon e icono de aplicación es aceptable, y si existe un tamaño mínimo
> oficial para él.

### 2.5 Integridad del asset

Los SVG se usan **tal cual**. En concreto, está prohibido en el código:

- aplicar `transform: rotate()`, `skew()` o escalados no uniformes;
- sobrescribir los `fill` del SVG con CSS o con `currentColor`;
- aplicar `filter`, `box-shadow`, `drop-shadow`, `opacity` parcial, `mix-blend-mode`;
- recortar el `viewBox` o alterar `preserveAspectRatio`;
- reconstruir el logotipo con tipografía en vez de usar el asset.

Para cambiar de color se cambia de archivo, no de estilo. Por eso existen tres
versiones del logotipo como archivos separados.

## 3. Tipografía en el producto

### 3.1 Reparto de roles

El manual da dos familias pero **no asigna roles** (guía §3). Decisión de ELSA:

| Rol | Familia | Peso | Token |
|---|---|---|---|
| Títulos de pantalla y de sección | Comfortaa | Bold (700) | `--elsa-fuente-titulo` |
| Subtítulos | Comfortaa | Regular (400) | `--elsa-fuente-titulo` |
| Cuerpo, formularios, tablas | Futura | Medium (500) | `--elsa-fuente-cuerpo` |
| Énfasis en cuerpo | Futura | Bold (700) | `--elsa-fuente-cuerpo` |
| Códigos SAP, IDs, números de material | Monoespaciada | Regular | `--elsa-fuente-dato` |

Razón del reparto: **Comfortaa es la tipografía del logotipo** (p. 8), así que
titular con ella liga la interfaz a la marca sin tocar el logotipo. Futura, más
neutra y de mejor rendimiento en texto pequeño, sostiene la lectura densa que
ELSA exige. Comfortaa Light (300) queda reservado a piezas grandes; en tamaños
de interfaz su trazo fino pierde legibilidad.

### 3.2 Lo que no se hace

- No se introducen familias fuera del manual, salvo la monoespaciada de datos,
  que es funcional y no corporativa.
- No se sintetizan pesos ausentes (*faux bold*, *faux italic*).
- No se usa Comfortaa para texto de cuerpo: su altura de x y su redondeo la
  hacen menos legible en párrafos largos.

### 3.3 Licencia — bloqueante para el frontend

- **Comfortaa**: SIL Open Font License. Autohospedable sin coste.
- **Futura**: tipografía **comercial**. Servirla como fuente web exige una
  licencia web específica, distinta de la de escritorio.

Hasta que PAPELSA confirme la licencia web de Futura, el frontend **no la
autohospeda**: `--elsa-fuente-cuerpo` resuelve a la pila del sistema. Publicar
un `.woff2` de Futura sin licencia es una infracción, y además dejaría un
binario tipográfico en el repositorio.

> **Duda abierta para PAPELSA:** ¿existe licencia web de Futura, y qué variante
> concreta (Futura PT, Futura Std, Paratype…) es la que usa la empresa? El
> manual dice «Futura» sin fundidor.

## 4. Reglas responsive

No están en el manual: la marca se escala proporcionalmente, y todo lo demás es
decisión de producto. Lo que **sí** viene del manual y no es negociable en
ningún ancho: proporción, área de seguridad, mínimo de 80 px y prohibición de
deformar.

### 4.1 Escalado

El logotipo escala **proporcionalmente**, nunca por eje. Su altura se deriva del
ancho (`ancho / 5.12`), nunca al revés, y el margen de seguridad escala con él.

| Ancho de viewport | Ancho del logotipo |
|---|---|
| ≥ 1024 px | 160 px |
| 640–1023 px | 120 px |
| 360–639 px | 96 px |
| < 360 px | símbolo aislado, 32 px (§4.2) |

Todos los valores ≥ 96 px respetan con holgura el mínimo de 80 px.

### 4.2 Cuando no cabe

Orden de degradación, en este orden y no otro:

1. Reducir el logotipo hasta **80 px**, nunca menos.
2. Si aún no cabe: **cambiar al símbolo aislado**, no encoger el logotipo.
3. Si tampoco cabe el símbolo a 24 px: **quitar la marca de esa zona**.

Nunca se recorta el logotipo, ni se apila en dos líneas, ni se elimina el `®`,
ni se reduce el área de seguridad para ganar espacio. El área de seguridad no es
un margen ajustable: es parte de la marca.

### 4.3 Densidad de pantalla

Los assets son SVG, así que no hay versiones `@2x` ni pérdida en pantallas de
alta densidad. Sólo el favicon requiere rasterización, y se genera desde
`papelsa-simbolo-color.svg` en el proceso de build, no a mano.

## 5. Color en la interfaz

### 5.1 Reglas heredadas del manual

- **Sólo los siete colores corporativos** en elementos de marca. «En ningún caso
  se podrán emplear otros colores que no sean los especificados» (p. 21).
- El logotipo no se recolorea nunca.
- `#4F868E` es el color del slogan y ELSA no usa slogan, así que **no se emplea**
  salvo como color de apoyo en elementos no textuales, y sólo si ninguna
  alternativa corporativa sirve.

### 5.2 Reglas propias de ELSA

- **El verde `#A9C23F` nunca lleva texto encima sobre fondo blanco** (contraste
  2,00). Es color de relleno y acento.
- Sobre verde, el texto va en `#333333` (6,30).
- **El verde corporativo no significa «éxito»** ni ningún otro estado. Los
  estados usan los tokens `--elsa-*` (`DESIGN_TOKENS.md` §3).
- Un color semántico nunca aparece dentro del logotipo ni en su área de
  seguridad.
- El color **nunca es el único portador de significado**: todo estado lleva
  además texto o icono. Es requisito de accesibilidad y, en una planta, de
  seguridad operativa.

### 5.3 Cabecera

La cabecera de ELSA usa fondo `#FFFFFF` con el logotipo a color, o fondo
`#006975` con el logotipo blanco. Ambas combinaciones están en el manual (p. 17)
y ambas dan contraste suficiente para el texto que las acompañe (blanco sobre
petróleo: 6,41).

## 6. Accesibilidad

ELSA se usa en planta, en condiciones de luz variables y a veces desde
dispositivos pequeños. Objetivo: **WCAG 2.1 nivel AA**.

| Requisito | Umbral |
|---|---|
| Texto normal | ≥ 4,5:1 |
| Texto grande (≥ 24 px, o ≥ 19 px bold) | ≥ 3,0:1 |
| Componentes de interfaz y bordes con significado | ≥ 3,0:1 |
| Indicador de foco | ≥ 3,0:1 contra el fondo adyacente |

Reglas de obligado cumplimiento:

1. Toda combinación texto/fondo se verifica contra la tabla de
   [`DESIGN_TOKENS.md`](DESIGN_TOKENS.md) §2. Las que están marcadas ✗ no se usan.
2. `#4F868E` (4,09) **no se usa para texto de cuerpo** sobre blanco.
3. `#BCBCBC` (1,90) es borde o separador, nunca texto.
4. El foco es siempre visible; no se elimina el `outline` sin sustituirlo por un
   indicador que cumpla 3,0:1. En superficies oscuras se usa `--elsa-foco-inverso`.
5. Los SVG llevan `role="img"` y un `<title>` con el texto «PAPELSA» —ya
   incluido en los assets—, de modo que el lector de pantalla anuncie la marca.
   Si el logotipo es decorativo y el nombre ya está en el texto, se marca
   `aria-hidden="true"` para no duplicar el anuncio.
6. El texto de la interfaz escala hasta el 200 % sin pérdida de contenido: por
   eso la escala tipográfica está en `rem` y no en `px`.
7. Ningún estado se comunica sólo con color (§5.2).

El contraste **no** se aplica al interior del logotipo: la relación entre sus dos
colores es parte de la marca y no se altera para mejorar un ratio.

## 7. Navegación por teclado

Estas reglas son parte del Design System de ELSA: toda pantalla nueva las
cumple. Hay gente que trabaja con guantes, con el ratón inutilizable, o
sencillamente más rápido con el teclado.

### 7.1 El orden lo da el DOM, no `tabindex`

El orden de tabulación es el orden del documento, y el documento se escribe en
el orden del flujo. En «Agregar conocimiento» eso significa:

```
A Capturar → B Esencial → C Entender → D Contexto → E Revisar
```

Dentro de cada bloque, lo obligatorio antes que lo opcional, y las acciones
después de los campos que las habilitan. Un `tabindex` positivo desplaza un
control fuera de ese orden y crea una secuencia que nadie puede predecir: **no
se usa nunca**. Solo se admite `tabindex="-1"` para sacar del recorrido algo
que no debe recibir foco.

Reordenar visualmente con CSS —`order`, `grid-area`, `flex-direction`— no
cambia el orden de tabulación. Cuando el orden visual y el del DOM difieran,
manda el del DOM: si eso resulta confuso, lo que hay que cambiar es el HTML.

### 7.2 Tab y Shift+Tab, y nada más

- `Tab` avanza al siguiente control; `Shift+Tab` retrocede al anterior.
- El recorrido hacia atrás es **exactamente** el inverso del de ida.
- `Enter` y `Espacio` activan botones; `Enter` envía un formulario.
- `Escape` cierra lo que se haya abierto encima (menú de identidad, cajón).

**No se inventan atajos.** Nada de teclas propietarias, ni de `Shift` a solas
con significado, ni de secuencias que haya que aprender. Un patrón ARIA que
exija teclas de flecha —`role="tablist"`, por ejemplo— solo se adopta si se
implementa entero; mientras tanto se usan controles corrientes. Por eso los
selectores de «Escribir / Grabar audio» son botones con `aria-pressed` y no
pestañas: se alcanzan con `Tab` y se activan con `Enter`, sin nada que saber.

### 7.3 Lo que no se ve no se tabula

Un control alcanzable con `Tab` pero invisible manda a quien navega con
teclado a un sitio que no puede ver. Se evita así:

- Lo que está oculto va con `hidden` o `visibility: hidden`, **no** con
  `transform` ni con `opacity: 0`, que dejan el elemento en el recorrido.
- El cajón lateral por debajo de 1024 px está oculto de verdad mientras está
  cerrado.
- Un `<details>` cerrado no expone su contenido.
- El enlace «Saltar al contenido» es la excepción deliberada: está fuera de la
  vista hasta que recibe el foco, y entonces **aparece**.

### 7.4 El foco se conserva y se lleva

- **Escribir nunca se interrumpe.** Actualizar un bloque derivado no puede
  quitar el foco ni mover el cursor. La regla operativa es no redibujar el
  bloque donde está el cursor; cuando un redibujado es inevitable, se
  restituyen foco y posición del cursor.
- **Mover el foco acompaña a la acción.** Al abrir el cajón, el foco va a su
  primer enlace; al cerrarlo, vuelve al botón que lo abrió. Nunca se queda
  huérfano en el `body`.
- **El foco siempre se ve**: `:focus-visible` con un contorno de 3 px y
  contraste ≥ 3:1. No se elimina un `outline` sin sustituirlo.

### 7.5 Qué se comprueba

En cada pantalla, y en los seis anchos de referencia:

- [ ] `Tab` desde el principio recorre el flujo en orden, sin saltos.
- [ ] `Shift+Tab` recorre exactamente lo mismo a la inversa.
- [ ] Ningún control del recorrido es invisible.
- [ ] El foco es visible en todos ellos.
- [ ] Escribir con pausas no pierde el foco ni mueve el cursor.
- [ ] No hay ningún `tabindex` positivo.

## 8. Assets del repositorio

En [`assets/brand/`](../../assets/brand/):

| Archivo | Contenido | Colores |
|---|---|---|
| `papelsa-logotipo-color.svg` | Logotipo completo, fondo transparente | `#006975`, `#A9C23F` |
| `papelsa-logotipo-blanco.svg` | Versión negativa, para fondos oscuros | `#FFFFFF`, `#DCDCDC` |
| `papelsa-logotipo-positivo.svg` | Versión positiva monocroma | `#333333`, `#6D6D6D` |
| `papelsa-simbolo-color.svg` | Símbolo aislado, cuadrado | `#006975`, `#A9C23F` |

Todos son **vectores extraídos del propio manual**, no reproducciones ni
redibujos. Fondo transparente, sin texto convertido a fuente (el nombre son
trazos, así que no depende de tener Comfortaa instalada).

Ver [`assets/brand/README.md`](../../assets/brand/README.md) para el detalle de
procedencia y verificación.

## 9. Lista de verificación

Antes de dar por buena una pantalla:

- [ ] El logotipo usa un asset de `assets/brand/`, sin filtros ni transformaciones.
- [ ] La versión elegida es la que corresponde al fondo (color / blanco / positivo).
- [ ] El logotipo mide ≥ 80 px de ancho, o se ha degradado al símbolo (≥ 24 px).
- [ ] Se respeta el área de seguridad de 22,22 % de la altura, por los cuatro lados.
- [ ] La proporción es la original; no hay escalado por un solo eje.
- [ ] Ningún color fuera de los tokens `--papelsa-*` y `--elsa-*`.
- [ ] Ningún color semántico dentro del logotipo o su área de seguridad.
- [ ] Todo texto cumple su umbral de contraste; nada marcado ✗ se usa como texto.
- [ ] Ningún estado se comunica sólo con color.
- [ ] El foco es visible en todos los elementos interactivos.
- [ ] `Tab` recorre el flujo en orden y `Shift+Tab` lo mismo a la inversa (§7).
- [ ] Ningún control alcanzable con `Tab` es invisible.
- [ ] Sin slogan.
