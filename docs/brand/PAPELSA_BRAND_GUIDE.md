# Guía de identidad PAPELSA para ELSA

## Alcance y procedencia

Base documental para el diseño del Bloque 3. No implementa interfaz ni
funcionalidades. Fecha de esta síntesis: 2026-09-06.

**Oficial PAPELSA** identifica exclusivamente los datos del Manual de Marca
que el responsable del proyecto suministró como ya revisados. No se consultó,
copió ni incorporó el PDF original al repositorio. No se atribuyen número de
página, edición, equivalencias de impresión ni reglas adicionales al manual.

**Decisión UX ELSA** identifica una elección de producto para aplicar esa
identidad a una interfaz accesible. No amplía el manual ni constituye una
autorización corporativa de nuevas variantes del logo.

## Paleta oficial PAPELSA

| Valor oficial | Nombre descriptivo usado en ELSA |
|---|---|
| `#A9C23F` | Verde lima |
| `#006975` | Verde azulado oscuro |
| `#4F868E` | Verde azulado medio |
| `#333333` | Gris oscuro |
| `#6D6D6D` | Gris medio |
| `#BCBCBC` | Gris claro |
| `#FFFFFF` | Blanco |

Los nombres son etiquetas prácticas de esta documentación. No se infieren
jerarquías oficiales, porcentajes de uso, Pantone, CMYK ni nuevos colores de marca.
La asignación a botones, fondos o estados es una decisión UX descrita en
[DESIGN_TOKENS.md](DESIGN_TOKENS.md).

## Tipografías oficiales PAPELSA

- Comfortaa: Light, Regular y Bold.
- Futura: Medium y Bold.

El extracto no asigna familias a controles, chat o tablas. Esa asignación y los
tamaños de interfaz son decisiones ELSA. Tampoco acredita licencias web ni
incluye archivos de fuentes; no se descarga ni incorpora ninguna tipografía
en esta tarea. No reconstruir el wordmark escribiendo el nombre con una fuente.

## Logo: reglas oficiales suministradas

- Respetar un área de seguridad de **2X**.
- Respetar el tamaño mínimo digital informado de **80 px**.
- Preferir la versión principal a color.
- No deformar, rotar ni recolorear.
- No alterar el orden ni las proporciones de los elementos.
- No aplicar efectos al logo.

El extracto no define la referencia geométrica **X**, el eje de la medida
de 80 px ni un mínimo independiente para el símbolo. Se conservan las reglas
literalmente: no se convierte 2X en píxeles, porcentajes o un padding de interfaz
inventado. Antes de fijar las dimensiones finales del logo se debe confirmar
esa referencia con el responsable de marca, sin versionar el PDF.

## Activos disponibles

| Activo versionado | Aplicación prevista por ELSA |
|---|---|
| [papelsa-wordmark.png](../../frontend/assets/brand/papelsa-wordmark.png) | Identificación principal, con símbolo y nombre, sin slogan |
| [papelsa-symbol.png](../../frontend/assets/brand/papelsa-symbol.png) | Identificación compacta cuando el espacio y las medidas verificadas lo permitan |

**Decisión UX ELSA:** para la presencia permanente de PAPELSA se prefiere el
logo sin slogan, según el encargo. Usar los PNG existentes sin filtros CSS,
recortes, sombras, animación, redibujo ni cambios de color. Los tratamientos
que ya trae el archivo no se reproducen como efectos añadidos.

Reservar un contenedor blanco y conservar la relación de aspecto y el archivo
completo. El tamaño del lienzo PNG y sus márgenes transparentes no demuestran
por sí solos el cumplimiento de 2X o del tamaño de la marca visible. Si una
sidebar compacta no permite cumplir las medidas, trasladar la identificación
principal a la topbar; no reducir el símbolo a un icono de 24 px por analogía.
Estas elecciones de ubicación y fondo son de ELSA, no reglas oficiales nuevas.

## Límites entre marca y producto

- El verde lima sirve como acento de identidad; no significa automáticamente
  éxito, aprobación técnica o conocimiento publicado.
- ELSA puede usar colores semánticos propios para error, advertencia y éxito.
  Deben identificarse como tales y nunca presentarse como paleta oficial PAPELSA.
- Las combinaciones de texto y fondo se eligen por contraste. Que dos colores
  sean corporativos no garantiza que juntos sean legibles.
- Un logo PAPELSA en una respuesta no certifica que su contenido esté validado.
  La fuente y el estado de revisión se comunican de forma independiente.

Los tokens están en [DESIGN_TOKENS.md](DESIGN_TOKENS.md); las reglas de uso
para cada área están en [ELSA_UI_BRAND_RULES.md](ELSA_UI_BRAND_RULES.md).
