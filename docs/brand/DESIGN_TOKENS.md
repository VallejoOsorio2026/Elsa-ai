# Design tokens — ELSA

Valores listos para consumir desde código. Este archivo es la **única fuente de
verdad de los valores**; la interfaz no vuelve a escribir un color a mano.

Dos capas, deliberadamente separadas:

| Capa | Prefijo | Origen | Se puede cambiar |
|---|---|---|---|
| **Marca** | `--papelsa-*` | Manual de Marca PAPELSA | **No.** Sólo PAPELSA, con una revisión del manual. |
| **Aplicación** | `--elsa-*` | Decisión de producto de ELSA | Sí, con criterio de diseño y accesibilidad. |

La razón de la separación: los colores corporativos **identifican a la empresa**;
los colores semánticos **comunican el estado de una operación**. Mezclarlos hace
que un mensaje de error parezca identidad y que la identidad parezca una alerta.
Ningún token `--elsa-*` puede redefinir un token `--papelsa-*`.

Fundamento normativo: [`PAPELSA_BRAND_GUIDE.md`](PAPELSA_BRAND_GUIDE.md).
Reglas de aplicación: [`ELSA_UI_BRAND_RULES.md`](ELSA_UI_BRAND_RULES.md).

---

## 1. Color de marca (inmutable)

```css
:root {
  /* Principales — Manual de Marca, p. 14 */
  --papelsa-verde:        #A9C23F;  /* Pantone 2300 C */
  --papelsa-petroleo:     #006975;  /* Pantone 2238 C */

  /* Slogan — no se usa en ELSA (logo sin slogan, ver guía §7) */
  --papelsa-azul-gris:    #4F868E;  /* Pantone 5483 C */

  /* Complementarios */
  --papelsa-gris-oscuro:  #333333;  /* Pantone 447 C */
  --papelsa-gris-medio:   #6D6D6D;  /* Pantone 4292 C */
  --papelsa-gris-claro:   #BCBCBC;  /* Pantone Gris Frío 4 C */
  --papelsa-blanco:       #FFFFFF;
}
```

Existe además `#DCDCDC`, usado por el arte de la versión negativa del logotipo.
**No es un color corporativo** y no se declara como token: vive dentro del
propio SVG y no debe usarse en la interfaz (ver guía §10).

## 2. Contraste medido de la paleta

Ratios WCAG 2.1 calculados sobre los valores exactos. Umbrales: **4,5** texto
normal (AA), **3,0** texto grande y componentes de interfaz.

| Color | sobre `#FFFFFF` | sobre `#333333` | sobre `#006975` | Uso admisible |
|---|---|---|---|---|
| `#A9C23F` verde | **2,00** ✗ | 6,30 ✓ | 3,20 ▲ | **Nunca texto sobre blanco.** Relleno, acento gráfico. |
| `#006975` petróleo | 6,41 ✓ | 1,97 ✗ | — | Texto, enlaces, fondos de cabecera. |
| `#4F868E` azul gris | **4,09** ▲ | 3,09 ▲ | 1,57 ✗ | Sólo texto grande (≥24 px, o ≥19 px bold) y bordes. |
| `#333333` gris oscuro | 12,63 ✓ | — | 1,97 ✗ | Texto principal. |
| `#6D6D6D` gris medio | 5,17 ✓ | 2,44 ✗ | 1,24 ✗ | Texto secundario sobre blanco. |
| `#BCBCBC` gris claro | 1,90 ✗ | 6,65 ✓ | 3,37 ▲ | Bordes, separadores. Nunca texto sobre blanco. |
| `#FFFFFF` blanco | — | 12,63 ✓ | 6,41 ✓ | Texto sobre petróleo o gris oscuro. |

✓ cumple AA texto normal · ▲ sólo texto grande o elementos no textuales · ✗ no cumple

Dos consecuencias que condicionan todo el diseño de ELSA:

- **El verde corporativo no puede llevar texto sobre blanco** (2,00). Es color de
  superficie y de acento, no de tipografía. Sobre verde, el texto va en
  `#333333` (6,30).
- **`#4F868E` se queda a 4,09**, por debajo de 4,5. No es apto para texto de
  cuerpo sobre blanco.

## 3. Color semántico de aplicación (decisión de ELSA)

> **No proviene del Manual de Marca.** El manual no define colores de estado.
> Estos valores son una propuesta de producto y requieren visto bueno de
> PAPELSA antes de considerarse cerrados.

```css
:root {
  --elsa-error:            #B3261E;
  --elsa-error-surface:    #FDECEA;
  --elsa-advertencia:      #8A5A00;
  --elsa-advertencia-surface: #FFF6E5;
  --elsa-exito:            #1B6B3A;
  --elsa-exito-surface:    #E9F4EE;
  --elsa-info:             var(--papelsa-petroleo);
  --elsa-info-surface:     #E6F0F1;
}
```

| Token | sobre `#FFFFFF` | sobre su propia superficie |
|---|---|---|
| `--elsa-error` | 6,54 ✓ | 5,72 ✓ |
| `--elsa-advertencia` | 5,93 ✓ | 5,52 ✓ |
| `--elsa-exito` | 6,54 ✓ | 5,81 ✓ |
| `--elsa-info` | 6,41 ✓ | 5,52 ✓ |

**El verde corporativo `#A9C23F` no significa «éxito».** Es el color de la
identidad: si señalara estado, cada superficie de marca se leería como una
confirmación. Por eso `--elsa-exito` es un verde distinto y más oscuro, elegido
además para cumplir contraste de texto, cosa que `#A9C23F` no hace.

Ninguno de estos cuatro colores puede aparecer en el logotipo, ni el logotipo
puede recolorearse con ellos.

## 4. Color funcional de interfaz

Roles de interfaz resueltos con la paleta corporativa. Cambiar el rol no cambia
la marca; cambia a qué token apunta.

```css
:root {
  --elsa-texto:            var(--papelsa-gris-oscuro);   /* 12,63 sobre blanco */
  --elsa-texto-secundario: var(--papelsa-gris-medio);    /*  5,17 sobre blanco */
  --elsa-texto-inverso:    var(--papelsa-blanco);
  --elsa-fondo:            var(--papelsa-blanco);
  --elsa-superficie:       #F5F6F3;   /* gris cálido neutro, decisión de producto */
  --elsa-borde:            var(--papelsa-gris-claro);
  --elsa-acento:           var(--papelsa-petroleo);
  --elsa-acento-grafico:   var(--papelsa-verde);         /* relleno, nunca texto */
  --elsa-foco:             var(--papelsa-petroleo);
  --elsa-foco-inverso:     var(--papelsa-blanco);        /* anillo sobre fondo oscuro */
}
```

`--elsa-foco` da 6,41 sobre blanco, muy por encima del mínimo de 3,0 exigido a un
indicador de foco. Sobre superficies petróleo o gris oscuro se usa
`--elsa-foco-inverso`, porque el anillo petróleo sobre petróleo es invisible (1,00).

## 5. Tipografía

Familias del manual (p. 15). El reparto de roles **no está en el manual**: es
decisión de producto, tomada aquí y justificada en
[`ELSA_UI_BRAND_RULES.md`](ELSA_UI_BRAND_RULES.md) §3.

```css
:root {
  --papelsa-fuente-marca:   "Comfortaa", system-ui, sans-serif;
  --papelsa-fuente-soporte: "Futura", "Futura PT", system-ui, sans-serif;

  --elsa-fuente-titulo: var(--papelsa-fuente-marca);
  --elsa-fuente-cuerpo: var(--papelsa-fuente-soporte);
  --elsa-fuente-dato:   ui-monospace, "SFMono-Regular", "Consolas", monospace;
}
```

Pesos declarados por el manual, y **sólo esos**:

| Familia | Pesos | `font-weight` |
|---|---|---|
| Comfortaa | Light, Regular, Bold | 300, 400, 700 |
| Futura | Medium, Bold | 500, 700 |

No se sintetizan pesos ni cursivas que el manual no declare: nada de *faux bold*
ni *faux italic*. Si un peso falta, se usa el declarado más próximo.

`--elsa-fuente-dato` es monoespaciada y **no es tipografía corporativa**: existe
porque los códigos de equipo SAP, los identificadores de orden y los números de
material se leen mal en proporcional. Se limita a ese uso.

> **Pendiente de licencia.** Comfortaa se distribuye bajo SIL Open Font License y
> puede autohospedarse sin coste. **Futura es una tipografía comercial**: su uso
> como fuente web requiere una licencia que PAPELSA debe confirmar. Hasta que se
> confirme, `--elsa-fuente-cuerpo` cae en la pila del sistema. Ver
> [`ELSA_UI_BRAND_RULES.md`](ELSA_UI_BRAND_RULES.md) §3.3.

## 6. Escala tipográfica

Decisión de producto. Base 16 px; ELSA es una herramienta de consulta técnica
densa, así que la escala es contenida y no editorial.

```css
:root {
  --elsa-texto-xs:  0.75rem;   /* 12 px — metadatos, sellos de evidencia */
  --elsa-texto-sm:  0.875rem;  /* 14 px — texto secundario, tablas */
  --elsa-texto-md:  1rem;      /* 16 px — cuerpo (por defecto) */
  --elsa-texto-lg:  1.25rem;   /* 20 px — subtítulo */
  --elsa-texto-xl:  1.5rem;    /* 24 px — título de sección */
  --elsa-texto-2xl: 2rem;      /* 32 px — título de pantalla */

  --elsa-interlineado-ajustado: 1.25;  /* títulos */
  --elsa-interlineado-normal:   1.5;   /* cuerpo */
}
```

12 px es el mínimo absoluto y sólo para metadatos; nunca para texto que el
usuario deba leer para decidir algo.

## 7. Geometría del logotipo

Derivada del manual (pp. 9–13). No son valores de estilo: son restricciones.

```css
:root {
  --papelsa-logo-proporcion:      5.12;   /* ancho / alto, arte real (46:9 nominal) */
  --papelsa-simbolo-proporcion:   1;      /* cuadrado */
  --papelsa-logo-ancho-minimo:    80px;   /* manual, p. 13 */
  --papelsa-logo-area-seguridad:  0.2222; /* 2X sobre 9X de alto = 22,22 % */
}
```

Cálculo del área de seguridad en píxeles: `margen = alto_del_logo × 0.2222`, por
los cuatro lados. Para un logotipo de 160 px de ancho (31,3 px de alto), el
margen libre es ≈ 7 px.

## 8. Espaciado

Decisión de producto. Escala de 4 px, la habitual en interfaz densa.

```css
:root {
  --elsa-espacio-1: 0.25rem;  /*  4 px */
  --elsa-espacio-2: 0.5rem;   /*  8 px */
  --elsa-espacio-3: 0.75rem;  /* 12 px */
  --elsa-espacio-4: 1rem;     /* 16 px */
  --elsa-espacio-6: 1.5rem;   /* 24 px */
  --elsa-espacio-8: 2rem;     /* 32 px */
  --elsa-espacio-12: 3rem;    /* 48 px */
}
```

El espaciado alrededor del logotipo **no** sale de esta escala: sale de
`--papelsa-logo-area-seguridad`, que es proporcional y no fijo.

## 9. Radio y elevación

Decisión de producto. El logotipo es redondeado y amable (manual, p. 8); la
interfaz acompaña ese carácter sin imitar la forma de la marca.

```css
:root {
  --elsa-radio-sm: 4px;
  --elsa-radio-md: 8px;
  --elsa-radio-lg: 16px;
  --elsa-radio-completo: 9999px;
}
```

**No se definen sombras para el logotipo.** El manual prohíbe efectos gráficos
sobre la marca (pp. 21–22). Las sombras de interfaz, si se usan, se aplican a
tarjetas y menús, nunca al logotipo ni al símbolo.
