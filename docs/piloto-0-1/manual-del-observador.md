# Manual del observador — Piloto 0.1 de ELSA

Para quien va a usar ELSA en planta durante el piloto.

Esto no es un manual de usuario de un producto terminado. ELSA está en pruebas,
y tú estás aquí para ver cómo se comporta con preguntas reales. Este documento
explica qué sabe hacer hoy, qué no, y cómo se comporta cuando algo no sale como
esperabas.

> **Versión canónica.** Este archivo es la fuente. Lo que se ve dentro de ELSA
> procede de aquí. Si alguna vez notas una diferencia entre los dos textos,
> repórtala: es un fallo.
>
> **Estado.** El Piloto 0.1 todavía no está construido. Este manual describe el
> comportamiento acordado en el
> [contrato funcional](contrato-funcional.md), y se revisará cuando el piloto
> esté en funcionamiento.

## 1. Qué es ELSA hoy

ELSA responde preguntas sobre el equipo Tampella cruzando dos fuentes:

- **El BOM de Ingeniería aprobado**, que es la lista de componentes y materiales
  del equipo, revisada y publicada. ELSA solo consulta la versión publicada;
  una versión pendiente de revisión no se usa para responderte.
- **El Asistente de Materiales**, que es el dueño del inventario. ELSA no tiene
  una copia del inventario: cuando necesita saber si hay existencias, se lo
  pregunta a Materiales en ese momento.

ELSA no adivina la relación entre las dos. Si te dice que un material está
asociado a Tampella, es porque está escrito en el BOM publicado. Si te dice que
hay existencias, es porque Materiales se lo respondió.

## 2. Qué puede preguntarle

Cuatro clases de pregunta, y una quinta que todavía no sabe responder.

**Sobre un material que ya conoces.** «Busca el material 123456.» «¿Tenemos
stock del 123456?» ELSA va a Materiales.

**Sobre los componentes del equipo.** «¿Qué rodamientos usa Tampella?» ELSA
busca en el BOM publicado.

**Sobre pertenencia.** «¿El 123456 pertenece a Tampella?» ELSA lo busca en el
BOM.

**Las dos cosas a la vez.** «¿Qué rodamientos usa Tampella y tenemos
disponibilidad?» ELSA busca primero en el BOM, saca los códigos, y con esos
códigos —solo con esos— pregunta a Materiales.

**Lo que todavía no sabe responder:** nada sobre el histórico de
intervenciones. Preguntas como «¿cuántas veces hemos cambiado este rodamiento?»
no tienen fuente en el sistema todavía, y ELSA te lo dirá en vez de aproximar.

Tampoco responde, por ahora, preguntas de manual o procedimiento («¿cada cuánto
se lubrica?»). Esa parte existe en el sistema pero no está conectada a este
piloto.

## 3. Cómo te habla ELSA cuando busca por descripción

En esta versión, ELSA no sabe qué *es* una pieza. Sabe qué *dice* su
descripción.

Por eso no te dirá «estos son los rodamientos de Tampella». Te dirá algo como:

> «Encontré 5 elementos del BOM publicado de Tampella cuya descripción coincide
> con "rodamiento".»

La diferencia importa. Si en el BOM hay un rodamiento cuya descripción no
contiene esa palabra, ELSA no lo encontrará. Y si hay una pieza que no es un
rodamiento pero lo menciona en su descripción, aparecerá. **Eso es exactamente
el tipo de cosa que queremos que nos reportes.**

Cada resultado te dice qué palabra produjo la coincidencia y en qué campo, para
que puedas juzgarlo tú.

## 4. El stock tiene una fecha

El inventario de Materiales no se lee en vivo desde SAP: se carga por versiones.
Cuando ELSA te dé una cantidad, te dirá también de qué versión del inventario
salió y de cuándo es.

Si en algún momento ELSA no puede determinar esa fecha, **te lo dirá y marcará
la respuesta como incompleta**. No te dará el número como si fuera de este
momento. Es preferible que sepas que no lo sabemos.

## 5. «No encontrado» no es «no existe»

Esto es lo más importante de este manual.

Cuando ELSA te diga que Materiales no devolvió un código, dirá algo equivalente
a:

> «Materiales no devolvió este código en la fuente consultada.»

**No dirá «ese material no existe», y tú tampoco deberías deducirlo.** Todavía
no sabemos con certeza qué significa que Materiales no devuelva algo. Podría
ser que el material no exista, pero también que no esté en la versión del
inventario que está cargada, que su sede no esté cubierta por la última
exportación, o que la búsqueda simplemente no haya coincidido.

Hasta que eso quede aclarado con el equipo de Materiales, ELSA solo puede
decirte lo que observó, no lo que significa. Si necesitas certeza sobre la
existencia de un material, compruébalo como lo harías normalmente.

## 6. Los cuatro finales posibles de una respuesta

ELSA siempre te dice en qué situación quedó:

**Respondida.** Encontró lo que hacía falta, y cada dato tiene su fuente.

**Parcial.** Respondió, pero con algo incompleto, y te dice qué. Por ejemplo:
encontró 5 rodamientos en el BOM y consiguió existencias de 4. Eso sigue siendo
útil, y por eso te lo entrega en vez de descartarlo todo.

**Sin evidencia.** No encontró nada que responda tu pregunta dentro de lo que
puede consultar.

**Sin evidencia es una respuesta legítima, no un fallo.** Significa que no está
escrito en el conocimiento publicado, o que la fuente consultada no devolvió
nada. No significa que el dato no exista en el equipo. Si tú sabes la respuesta
y no está ahí, eso es información valiosa: puedes aportarla desde «Agregar
conocimiento», y pasará por revisión.

**Error.** Algo técnico falló: un servicio no respondió o tardó demasiado.
Es distinto de «sin evidencia», y ELSA no los confunde a propósito: decirte «no
hay información» cuando en realidad se cayó un servicio te haría concluir algo
falso por culpa nuestra. Ante un error, vuelve a intentarlo.

## 7. Cuando ELSA te pregunta algo

A veces ELSA te devolverá una pregunta en vez de una respuesta. Por ejemplo, si
escribes solo un código, puede preguntarte si te refieres al material en
inventario o al componente instalado en el equipo.

Lo hace únicamente cuando hay una razón concreta: falta el equipo, hay varias
rutas posibles, o no hay nada buscable en lo que escribiste. No debería
preguntarte por costumbre. **Si te parece que pregunta de más, o que pregunta
cuando la respuesta era obvia, repórtalo.**

## 8. Lo que ELSA no ve

Solo verás equipos sobre los que tengas permiso. Si no tienes permiso sobre un
equipo, ELSA se comporta igual que si ese equipo no existiera: no te lo nombra,
no te lo sugiere y no te dice que existe pero no puedes verlo. Es deliberado.

## 9. Reportar respuesta

Debajo de cada respuesta hay un botón para reportarla.

Al pulsarlo se abre directamente un campo de texto:

> «Cuéntanos con tus palabras qué ocurrió o qué esperabas que ocurriera.»

No hay que elegir una categoría, ni rellenar un formulario, ni clasificar nada.
Escribe lo que viste y lo que esperabas, como se lo contarías a un compañero.

**No hace falta que tengas razón para reportar.** Si algo te pareció raro,
confuso, lento, incompleto, o simplemente distinto de lo que esperabas, eso es
suficiente motivo. También sirve reportar una respuesta que estaba bien pero se
entendía mal.

Cuando reportas, el sistema guarda por su cuenta el detalle técnico de esa
respuesta concreta: qué se consultó, en qué orden, qué devolvió cada fuente,
cuánto tardó y qué versión de los datos se usó. Eso nos permite investigar tu
reporte días después sin depender de que la conversación siga ahí.

Tu texto se guarda **tal cual lo escribiste**. No se resume, no se reescribe y
no se clasifica automáticamente.

**No escribas contraseñas, tokens ni claves en ese campo.** No hacen falta para
investigar nada, y el sistema está diseñado para no almacenarlas.

## 10. Qué nos sirve de ti

No necesitamos que juzgues si ELSA es buena o mala, ni que puntúes nada. Lo que
nos sirve es lo concreto:

- la pregunta que escribiste y lo que esperabas recibir;
- cuándo te dio algo que no venía a cuento;
- cuándo no encontró algo que tú sabes que está;
- cuándo la respuesta era correcta pero no se entendía;
- cuándo te preguntó algo que no hacía falta preguntar;
- cuándo tardó tanto que dejaste de esperar.

Usa ELSA como usarías cualquier herramienta de trabajo, con tus preguntas
reales. El piloto sirve precisamente para eso.

## 11. A quién acudir

Para dudas sobre el piloto, ELSA o este manual: el responsable del proyecto.

Para dudas sobre un material concreto o sobre el inventario: los canales
habituales de Materiales. ELSA no sustituye a Materiales; le pregunta.

---

## Sobre este documento

Fuente canónica del contenido que ELSA muestra como guía del piloto. El
mecanismo por el que la interfaz lo presenta —contenido versionado servido
desde aquí, o una vinculación verificable con este archivo— se decide al
implementarlo, tras revisar la arquitectura del frontend. Lo que **no** se
admite son dos textos evolucionando por separado.

Contrato que describe: [contrato funcional del Piloto 0.1](contrato-funcional.md).
