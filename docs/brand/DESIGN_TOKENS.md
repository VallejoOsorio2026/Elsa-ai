# Tokens de diseño para ELSA

## Convención y autoridad

Contrato documental para una futura interfaz clara. No contiene CSS ejecutable
ni instala un framework. Los valores `brand.*` reproducen los datos oficiales
suministrados en [PAPELSA_BRAND_GUIDE.md](PAPELSA_BRAND_GUIDE.md).
Los nombres de tokens, sus alias semánticos y todos los valores `elsa.*` son
**decisiones UX ELSA**, aunque reutilicen un color oficial. No se define un tema
oscuro ni se deduce uno invirtiendo colores.

## Referencias oficiales

| Token | Valor |
|---|---|
| `brand.color.lime` | `#A9C23F` |
| `brand.color.teal-dark` | `#006975` |
| `brand.color.teal-medium` | `#4F868E` |
| `brand.color.gray-dark` | `#333333` |
| `brand.color.gray-medium` | `#6D6D6D` |
| `brand.color.gray-light` | `#BCBCBC` |
| `brand.color.white` | `#FFFFFF` |
| `brand.font.comfortaa` | Comfortaa Light / Regular / Bold |
| `brand.font.futura` | Futura Medium / Bold |
| `brand.logo.clear-space` | `2X`; referencia X pendiente de confirmar |
| `brand.logo.digital-minimum` | `80 px`; eje y aplicación al símbolo pendientes de confirmar |

Los dos tokens de logo son restricciones documentales, no valores listos para
asignar a `width` o `padding`. El espaciado de componentes no sustituye a 2X.

## Colores semánticos de interfaz — decisiones UX ELSA

| Token | Valor o referencia | Uso y restricción |
|---|---|---|
| `elsa.surface.canvas` | `#F5F7F7` | Fondo general; neutral propio de ELSA |
| `elsa.surface.panel` | `brand.color.white` | Chat, topbar, tarjetas y tablas |
| `elsa.surface.selected` | `#E8F2F3` | Selección; fondo propio de ELSA |
| `elsa.text.primary` | `brand.color.gray-dark` | Contenido principal sobre fondos claros |
| `elsa.text.secondary` | `brand.color.gray-medium` | Metadatos y ayudas legibles sobre panel/canvas |
| `elsa.text.on-primary` | `brand.color.white` | Sobre acción primaria verde azulado oscuro |
| `elsa.text.on-accent` | `brand.color.gray-dark` | Sobre acento lima |
| `elsa.action.primary` | `brand.color.teal-dark` | Acción principal; no significa aprobación |
| `elsa.action.link` | `brand.color.teal-dark` | Enlaces subrayados sobre panel/canvas |
| `elsa.accent.brand` | `brand.color.lime` | Detalle de identidad o selección con indicador adicional |
| `elsa.accent.decorative` | `brand.color.teal-medium` | Detalles; no fondo de texto normal blanco ni gris oscuro |
| `elsa.border.subtle` | `brand.color.gray-light` | Separadores decorativos; no único límite de un control |
| `elsa.border.control` | `brand.color.gray-medium` | Contornos necesarios sobre fondos claros |
| `elsa.focus.ring` | `brand.color.teal-dark` | Foco sobre fondos claros |
| `elsa.focus.gap` | `brand.color.white` | Separación visible del foco respecto a controles oscuros |
| `elsa.state.disabled-text` | `brand.color.gray-medium` | Estado inactivo, acompañado de semántica y explicación |

No reducir opacidad para fabricar estados: se debe verificar el contraste de
la combinación resultante. Hover y pressed conservan los pares accesibles y
añaden subrayado, contorno o cambio de grosor; no necesitan nuevos hexadecimales.
Selected incorpora etiqueta/indicador y no se comunica únicamente por color.

## Estados operativos — colores propios de ELSA, no corporativos

| Tokens | Texto, icono y borde | Fondo | Significado |
|---|---|---|---|
| `elsa.status.error.fg` / `.bg` | `#B42318` | `#FEF3F2` | Error o acción destructiva |
| `elsa.status.warning.fg` / `.bg` | `#8A4B00` | `#FFF4E5` | Advertencia, pendiente de atención |
| `elsa.status.success.fg` / `.bg` | `#216E39` | `#EDF7ED` | Operación confirmada por el sistema |
| `elsa.status.info.fg` / `.bg` | `#006975` | `#E8F2F3` | Información contextual |

Cada fila define dos tokens completos, por ejemplo `elsa.status.error.fg`
y `elsa.status.error.bg`. El hexadecimal informativo reutiliza un color PAPELSA,
pero su significado operativo es ELSA. Los restantes colores y fondos no son
ampliaciones de la paleta oficial. Usar icono y texto explícito en cada estado.

## Contraste comprobado

Cálculo sRGB de luminancia relativa, sin transparencia, para estos valores
exactos. Ratios mostrados con dos decimales; los umbrales se verifican sin
redondear. Esto valida pares de colores, no una interfaz completa.

| Primer plano / fondo | Ratio | Uso |
|---|---:|---|
| `#333333` / `#FFFFFF` | 12.63:1 | Texto normal |
| `#6D6D6D` / `#FFFFFF` | 5.17:1 | Texto normal |
| `#6D6D6D` / `#F5F7F7` | 4.81:1 | Texto secundario en canvas |
| `#FFFFFF` / `#006975` | 6.41:1 | Acción primaria |
| `#333333` / `#A9C23F` | 6.30:1 | Texto sobre acento lima |
| `#006975` / `#E8F2F3` | 5.62:1 | Texto seleccionado/informativo |
| `#B42318` / `#FEF3F2` | 6.05:1 | Error |
| `#8A4B00` / `#FFF4E5` | 6.26:1 | Advertencia |
| `#216E39` / `#EDF7ED` | 5.70:1 | Éxito |
| `#FFFFFF` / `#A9C23F` | 2.01:1 | No usar para texto |
| `#FFFFFF` / `#4F868E` | 4.09:1 | No usar para texto normal |
| `#333333` / `#4F868E` | 3.09:1 | No usar para texto normal |
| `#BCBCBC` / `#FFFFFF` | 1.90:1 | No usar para texto ni límite único de control |

**Objetivo de accesibilidad ELSA:** WCAG 2.2 AA. Texto normal ≥4.5:1;
texto grande ≥3:1 (18 pt, o 14 pt en negrita). Contornos e indicadores visuales
necesarios para identificar controles/estados deben alcanzar ≥3:1 frente al
color adyacente. Aplicar las reglas al resultado final, incluidos foco, errores
y selección. Fuentes: [W3C, contraste de texto](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
y [W3C, contraste no textual](https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html).

## Tipografía, dimensiones y movimiento — decisiones UX ELSA

| Token | Valor documental | Aplicación |
|---|---|---|
| `elsa.font.heading` | `Comfortaa, system-ui, sans-serif` | Títulos breves; Regular o Bold |
| `elsa.font.body` | `Futura, system-ui, sans-serif` | Texto, chat y controles; Medium o Bold |
| `elsa.font.code` | `ui-monospace, monospace` | Identificadores técnicos y fragmentos de código |
| `elsa.font-size.body` | `1rem` | Base de lectura |
| `elsa.font-size.meta` | `0.875rem` | Metadatos secundarios, nunca texto esencial comprimido |
| `elsa.font-size.heading` | `1.5rem` | Encabezado de sección |
| `elsa.line-height.body` | `1.5` | Texto prolongado y chat |
| `elsa.line-height.heading` | `1.3` | Encabezados |
| `elsa.space.1` / `.2` / `.3` / `.4` / `.6` / `.8` | `0.25rem` / `0.5rem` / `0.75rem` / `1rem` / `1.5rem` / `2rem` | Escala de espaciado |
| `elsa.radius.control` / `.panel` | `0.5rem` / `0.75rem` | Controles y paneles; no se aplica al logo |
| `elsa.border.width` | `1px` | Contorno estándar |
| `elsa.focus.width` / `.offset` | `2px` / `2px` | Anillo visible con separación; probar sobre cada superficie |
| `elsa.target.minimum` | `2.75rem` | Objetivo de área operable: 44 px a raíz de 16 px |
| `elsa.reading.max-width` | `72ch` | Mensajes y texto prolongado; tablas requieren otra distribución |
| `elsa.motion.duration` / `.reduced` | `120ms` / `0ms` | Transiciones discretas y preferencia de movimiento reducido |

Los grupos abreviados definen tokens con el mismo prefijo completo. `rem`
respeta la configuración del usuario; no fijar la raíz para impedir el zoom.
44 px es una decisión UX ELSA más amplia que el mínimo WCAG de 24 CSS px,
que contempla excepciones: [W3C, tamaño de objetivo](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html).

Las familias corporativas solo se activarán con archivos web autorizados y
pesos reales correctamente mapeados. No sintetizar Light/Medium/Bold ni asumir
licencias por el nombre. Mientras tanto se usan las fuentes de sistema de los
fallbacks. Comfortaa Light se reserva a títulos grandes opcionales después de
comprobar legibilidad; no se usa en chat, tablas o advertencias. Esta asignación
es una decisión de lectura de ELSA, no una jerarquía tipográfica del manual.
