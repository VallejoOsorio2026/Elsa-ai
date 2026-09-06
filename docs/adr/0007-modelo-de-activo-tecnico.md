# ADR 0007 — Modelo genérico de Activo Técnico e identidad del componente

- Estado: aceptado
- Bloque: 2
- Reemplaza a: —

## Contexto

El MVP técnico de ELSA está limitado al equipo Tampella, pero la
arquitectura debe permitir después múltiples equipos, plantas y dominios.
Escribir el modelo alrededor de Tampella habría sido más corto hoy y habría
obligado a reescribirlo entero al segundo equipo.

Al mismo tiempo hay que decidir **qué hace que un componente sea el mismo
componente** entre una versión del BOM y la siguiente. Es la decisión con
más consecuencias del bloque: si se equivoca, la historia técnica de una
pieza se parte en dos o se fusiona con la de otra, y en ambos casos en
silencio.

## Decisión

### El dominio se llama Activo Técnico

Existe `elsa.technical_assets` con `code`, `name` y `domain`. Tampella es una
fila, no una clase. El alcance de autorización de un activo es exactamente
`(domain, code)`, es decir el mismo par `(dominio, equipo)` que el Bloque 1
ya usa en `permission_grants`. Autorizar un activo no necesita un segundo
modelo de permisos.

### La identidad del componente es un UUID interno y nada más

`elsa.components` contiene el UUID, el activo y el subsistema. Nada más.

El código SAP, el nombre, el plano, la referencia, la cantidad y el modelo
**no son la identidad**: son atributos de una versión del BOM o alias
acumulados en `elsa.component_identifiers`. Todos ellos cambian con el
tiempo. Si cualquiera fuese la identidad, cambiarlo crearía un componente
distinto y se perdería la historia del que existía.

Consecuencias directas:

- Un componente **puede existir sin código SAP** y sigue siendo un
  componente técnico válido. Muchos lo están: piezas fabricadas, elementos
  sin codificar todavía.
- Cambiar el código SAP de una pieza no crea una pieza nueva.
- El UUID no se muestra al usuario normal (ver ADR 0008 y la API de
  consulta): a quien va a cambiar un rodamiento le sirven el plano, la
  referencia y el código, no un identificador interno.

### El emparejamiento es conservador y explica por qué emparejó

Para decidir si un renglón nuevo corresponde a un componente existente se
aplican, en este orden:

1. **Activo + plano + referencia de plano.** Dentro de un activo, la
   referencia dentro de un plano señala una pieza concreta.
2. **Código SAP, si es inequívoco.** El mismo código puede aparecer en
   varios componentes (dos rodamientos iguales en sitios distintos), así que
   solo vale cuando apunta a uno.
3. **Subsistema + referencia técnica** (modelo o *part number*). Evidencia
   débil, marcada como tal.

Y tres prohibiciones sin excepción:

- **El nombre por sí solo nunca basta.** Dos componentes distintos pueden
  llamarse igual.
- **Varios candidatos nunca se resuelven automáticamente.** El renglón queda
  `unresolved`, sin componente, y decide una persona. En particular **no se
  crea un componente nuevo**: eso bifurcaría en silencio una identidad que
  ya existe.
- **Nunca hay fusión destructiva.** Emparejar es enlazar, no reescribir.

Cada coincidencia automática guarda la regla que la produjo
(`engineering_bom_items.match_rule`) y su fuerza (`match_confidence`), de
modo que siempre se puede explicar por qué dos renglones se consideraron la
misma pieza.

## Alternativas descartadas

- **Usar el código SAP como clave primaria del componente.** Es lo más
  natural para quien viene de SAP y es exactamente el error que este ADR
  evita: dejaría fuera del modelo a todo componente sin código, y un cambio
  de código partiría la historia.
- **Emparejar por descripción con similitud textual.** Habría cubierto más
  casos automáticamente y habría fusionado piezas distintas con nombres
  parecidos, sin dejar rastro de la decisión.
- **Modelar solo Tampella y generalizar después.** Generalizar un esquema
  con datos ya cargados es una migración de datos, no un refactor.

## Consecuencias

- Habrá renglones `unresolved` que exigen intervención humana. Es el precio
  de no inventar identidades, y es visible: aparecen en el detalle de la
  versión con su regla y su confianza.
- El índice de emparejamiento se construye a partir de los renglones ya
  almacenados del activo, así que crece con la historia y no depende de un
  catálogo mantenido a mano.
