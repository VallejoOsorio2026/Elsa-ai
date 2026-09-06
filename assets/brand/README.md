# Assets de marca PAPELSA

Assets del logotipo PAPELSA para la interfaz web de ELSA.

Reglas de uso obligatorias:
[`docs/brand/ELSA_UI_BRAND_RULES.md`](../../docs/brand/ELSA_UI_BRAND_RULES.md).
No se usa ninguno de estos archivos sin leer antes ese documento.

## Archivos

| Archivo | Uso | Proporción | Colores |
|---|---|---|---|
| `papelsa-logotipo-color.svg` | Versión principal. Fondos claros. | 5,120:1 | `#006975`, `#A9C23F` |
| `papelsa-logotipo-blanco.svg` | Versión negativa. Fondos oscuros o petróleo. | 5,120:1 | `#FFFFFF`, `#DCDCDC` |
| `papelsa-logotipo-positivo.svg` | Versión positiva monocroma. Impresión sin color. | 5,120:1 | `#333333`, `#6D6D6D` |
| `papelsa-simbolo-color.svg` | Símbolo aislado. Favicon, icono, avatar. | 1:1 | `#006975`, `#A9C23F` |

Todos con fondo transparente y sin dependencias tipográficas: el nombre
`papelsa` son trazos vectoriales, no texto, así que se renderiza igual en
cualquier equipo.

## Procedencia

**No son redibujos.** Son los vectores originales del Manual de Marca PAPELSA,
extraídos de la página 5 (logotipo y símbolo) con las recoloraciones que el
propio manual define en la página 17 para las versiones positiva y negativa.

El PDF del manual es material corporativo privado y **no está en el
repositorio**; `.gitignore` bloquea `*.pdf` y `*.PDF`.

## Verificación

- Los colores del arte a color son exactamente `#006975` y `#A9C23F`, los dos
  colores principales de la página 14 del manual. No aparece ningún otro.
- La proporción medida del logotipo es 448,594 × 87,609 pt = **5,120:1**, frente
  al **46:9 = 5,111:1** nominal de la planimetría (p. 9). La diferencia del
  0,2 % es el desborde del `®` sobre la retícula modular.
- El símbolo mide 68,724 × 68,757 pt, **1:1**.
- Las versiones positiva y negativa reproducen literalmente los pares de color
  del arte del manual (p. 17), no una recoloración inventada.
- Los cuatro SVG se rasterizaron y se compararon contra las páginas 5 y 17 del
  manual: coinciden.

`#DCDCDC`, presente en la versión negativa, **no es un color corporativo** (el
gris claro del manual es `#BCBCBC`). Se conserva por fidelidad al arte original.
Es una discrepancia del manual, anotada en
[`docs/brand/PAPELSA_BRAND_GUIDE.md`](../../docs/brand/PAPELSA_BRAND_GUIDE.md) §10.

## Modificación

Estos archivos **no se editan**. El manual prohíbe deformar, rotar, recolorear y
aplicar efectos a la marca (pp. 21–22). Si hace falta otra versión, se extrae
del manual y se documenta aquí; no se deriva a mano ni con CSS.
