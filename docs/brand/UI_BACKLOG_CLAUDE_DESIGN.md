# Pendientes de interfaz para el ELSA Design System

Lista de trabajo visual **reservado para una fase posterior**, a abordar con
Claude Design. Nada de esto se implementa en el Bloque 3.

## Cómo leer este documento

El Bloque 3 construyó una interfaz **funcional y verificada**, no una interfaz
terminada. Se priorizó que el piloto se pudiera usar y probar con ingenieros
reales; el refinamiento visual se aplazó de forma consciente.

Por eso conviene distinguir dos cosas que suelen confundirse:

- **Defecto**: la pantalla no hace lo que dice hacer. Eso se corrige en el
  bloque donde aparece, no aquí. (Ejemplo real: el método de captura activo
  dejó de distinguirse del inactivo porque una regla de CSS apuntaba a un
  atributo viejo. Se corrigió en el Bloque 3, con prueba de regresión.)
- **Pendiente de diseño**: la pantalla funciona, pero su tratamiento visual no
  está sistematizado. Eso es lo que se registra en este documento.

Cada punto indica **qué existe hoy** y **qué falta**, para que quien lo tome
no tenga que reconstruir el contexto leyendo el código.

Referencias obligatorias para cualquier trabajo derivado de esta lista:

- [`PAPELSA_BRAND_GUIDE.md`](PAPELSA_BRAND_GUIDE.md) — norma de marca. Manda
  siempre.
- [`DESIGN_TOKENS.md`](DESIGN_TOKENS.md) — valores en código y contraste medido.
- [`ELSA_UI_BRAND_RULES.md`](ELSA_UI_BRAND_RULES.md) — cómo aplica ELSA la marca,
  incluida la §7 de navegación por teclado.

---

## 1. Estado visual del método de captura activo

**Hoy.** «Escribir» y «Grabar audio» son dos botones equivalentes con
`aria-pressed`, y el activo se distingue por borde, fondo y anillo interior en
color de acento.

**Falta.** Un tratamiento sistematizado del grupo de selección: qué distingue
un método activo de uno inactivo, de uno deshabilitado y de uno enfocado, sin
depender solo del color (el criterio de accesibilidad exige un segundo canal:
peso, icono, marca). Hoy la única diferencia perceptible es cromática.

## 2. Inventario completo de botones e iconos

**Hoy.** Solo existen dos clases de botón nombradas (`.icon-btn`,
`.identity-btn`); el resto son `<button>` estilizados por contexto. La
iconografía es un conjunto suelto de glifos Unicode: `✕ → ✅ ⚠ ☰ ▾ ⏻ ✍ 🎙`.
No hay un set de iconos ni un archivo que los reúna.

**Falta.** Inventariar cada botón real de la aplicación y reducirlo a un número
pequeño de variantes con nombre (primaria, secundaria, destructiva, terciaria,
icono). Sustituir los glifos por un set de iconos coherente, con tamaño,
grosor de trazo y área táctil definidos, y decidir qué significa cada uno.

## 3. Estados de los controles

**Hoy.** La cobertura es desigual y está medida: `:hover` aparece 4 veces en
todo el CSS, `:focus`/`:focus-visible` 4, `:disabled` 2, y **`:active` ninguna
vez**. No existe estado de carga en ningún botón salvo el de audio.

**Falta.** Definir, para cada variante del punto 2, los siete estados:
normal, hover, focus, pressed, disabled, loading y error. El estado *pressed*
y el *loading* son los más ausentes hoy, y son justamente los que dan
sensación de respuesta en un equipo lento o con guantes.

## 4. Microinteracciones de audio

**Hoy.** La grabación recorre seis estados con nombre (Listo → Iniciando →
Grabando → Finalizando → Procesando → Lista) y avisa a 60/30/10 s antes del
corte. Los cambios son de texto: no hay transiciones ni indicador de nivel.

**Falta.** Movimiento y realimentación no textual: pulso durante la grabación,
indicador de nivel de entrada, transición entre estados, tratamiento del
contador cuando entra en la zona de aviso, y forma de onda o progreso en la
reproducción. Restricción heredada: **nada de esto puede reconstruir los nodos
del panel en cada tick**; eso destruye los clics (ver §7).

## 5. Jerarquía visual recibido → validado → publicado

**Hoy.** Los tres estados se dibujan como un recorrido, con el tercero en línea
discontinua porque nunca se alcanza automáticamente. El texto de la regla es
explícito: aprobar valida el aporte, publicar es una decisión posterior e
independiente.

**Falta.** Que la jerarquía se lea **antes que el texto**. Hoy la distinción
depende de leer las etiquetas. Falta decidir tipografía, color y peso de cada
estado, y cómo se representa un estado inalcanzable sin que parezca un error
ni un paso pendiente de hacer.

## 6. Revisión y revisión cruzada

**Hoy.** El Centro de Revisión separa pendientes y decididos, muestra quién
decidió y permite revisar una decisión anterior con un tratamiento distinto.

**Falta.** Distinguir visualmente cuatro situaciones que hoy comparten forma:
revisar algo nuevo, revisar lo propio, revisar la decisión de otra persona, y
consultar una decisión ya cerrada. También falta el tratamiento de la
trazabilidad: quién, cuándo y sobre qué evidencia.

## 7. Refinamiento del progressive disclosure en «Agregar conocimiento»

**Hoy.** Una sola pantalla con cinco bloques progresivos (Capturar → Esencial →
Entender → Contexto → Revisar). No es un asistente de «Siguiente». El bloque
«Esto es lo que ELSA entendió» aparece solo cuando hay material, y el contexto
adicional viene contraído.

**Falta.** Que la progresión se entienda de un vistazo: qué bloque está activo,
cuál ya está resuelto y cuál aún no aplica. Falta también el tratamiento de la
aparición del bloque «Entender», que hoy simplemente se muestra.

> **Restricción no negociable para esta fase.** Refrescar la vista previa no
> puede reconstruir el bloque que contiene el cursor. Rehacer DOM por
> temporizador o por dato derivado destruye el foco y destruye los clics; ya
> ocurrió tres veces en el Bloque 3. Cualquier rediseño mantiene contenedores
> estables por bloque.

## 8. Densidad, espaciado y jerarquía de tarjetas

**Hoy.** El espaciado usa la escala `--elsa-espacio-*`, aplicada caso por caso.
Las tarjetas de hallazgo, de aporte y de evidencia no comparten una estructura
común.

**Falta.** Una escala de densidad decidida (no heredada del caso concreto) y un
patrón único de tarjeta: dónde va el título, el metadato, el estado y la
acción, y cómo se comprime en pantalla estrecha.

## 9. Navegación por teclado y preservación del foco

**Hoy.** Es lo más terminado de la lista, y sus reglas ya están escritas en
[`ELSA_UI_BRAND_RULES.md`](ELSA_UI_BRAND_RULES.md) §7: el orden sale del DOM,
sin `tabindex` positivo; solo Tab y Shift+Tab; lo que no se ve no se tabula; el
foco se conserva mientras se escribe.

**Falta.** La parte visual: un anillo de foco propio del sistema, visible sobre
fondo blanco y sobre el teal corporativo, con contraste medido. Hoy se usa el
anillo por defecto del navegador, que sobre `#006975` se ve mal.

## 10. Tablas y responsive

**Hoy.** Las tablas tienen banda de encabezado y un contenedor con degradado que
avisa de que hay más contenido a la derecha. Funciona de 320 a 1920 px.

**Falta.** Decidir qué hace una tabla técnica por debajo de 768 px: hoy se
desplaza horizontalmente. Falta evaluar el paso a formato de lista o tarjeta, y
definir qué columnas son imprescindibles y cuáles se pueden ocultar.

## 11. Selector y contexto de Activo Técnico

**Hoy.** El activo se obtiene del backend cruzando catálogo y permisos. Con un
solo activo autorizado se selecciona automáticamente; con varios hay que
elegir. El contexto vive en la barra superior.

**Falta.** Su forma visual con volumen real. Hoy el caso probado es «un activo»;
con decenas hará falta búsqueda, agrupación por planta o dominio, y un
indicador de contexto activo que no se confunda con un filtro. Falta además el
estado «sin ningún activo autorizado», que hoy se resuelve con texto.

## 12. Estados vacíos, advertencias, errores y ausencia de evidencia

**Hoy.** Los estados vacíos son frases sueltas escritas caso por caso
(«Todavía no has enviado ningún aporte sobre este equipo», «No hay aportes
esperando revisión», «Todavía no he leído nada que reconocer»). No hay un
patrón común ni ilustración ni acción sugerida.

**Falta.** Un patrón único para cuatro cosas que hoy se ven parecidas y **no
son lo mismo**:

1. *vacío* — todavía no hay nada, y está bien;
2. *advertencia* — hay algo que mirar, pero el proceso siguió;
3. *error* — el proceso no pudo completarse;
4. *sin evidencia* — ELSA no responde porque no tiene con qué respaldarlo.

La cuarta es la más importante del proyecto y hoy es la menos visible: es la
diferencia entre un asistente que se calla con motivo y uno que parece roto.

## 13. Consistencia de iconografía

**Hoy.** Glifos Unicode mezclados, con estilos de origen distinto (algunos
monocromos, `✅` en color, `🎙` como emoji a todo color). Su aspecto cambia
según el sistema operativo del PC corporativo.

**Falta.** Un set único, monocromo, que herede el color del texto y no dependa
de la fuente del sistema. Es también un riesgo de marca: un emoji a todo color
introduce colores ajenos a la paleta PAPELSA.

## 14. Documentación reproducible de componentes

**Hoy.** No existe. Los componentes viven en el CSS y en las funciones que los
construyen; para saber qué variantes hay, hay que leer el código.

**Falta.** Un catálogo de componentes reproducible: cada componente con sus
variantes y sus estados, visible en una página, alineado con los tokens y
enlazado desde este documento. Es el entregable que convierte todo lo anterior
en un Design System y no en una lista de arreglos.

---

## Qué no entra en esta lista

- Cambiar la marca PAPELSA. El manual manda; lo que no resuelve, se pregunta.
- Reabrir decisiones de arquitectura o de seguridad. Ningún punto de esta lista
  justifica tocar permisos, evidencias ni la separación entre aprobar y
  publicar.
- Convertir «Agregar conocimiento» en un asistente por pasos.
