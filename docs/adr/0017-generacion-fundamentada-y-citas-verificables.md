# ADR 0017 — Generación fundamentada: el backend resuelve las citas y decide el estado

- Estado: **aceptado**
- Bloque: 4.4
- Deriva de [ADR 0016](0016-recuperacion-hibrida-del-mvp.md) (recuperación
  híbrida, sin umbral calibrado), [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md) §6
  (filtros obligatorios) y [ADR 0003](0003-puertos-y-adaptadores-para-modelos-reemplazables.md)
  (el proveedor de LLM sigue abierto)
- Aplica las reglas 2 y 5 de `CLAUDE.md`: el LLM nunca decide permisos y nunca
  crea hechos sin evidencia recuperada
- Implementación y detalle en [`rag-generacion.md`](../rag-generacion.md)

## Contexto

El Bloque 4.3 dejó la evidencia autorizada, ordenada y con procedencia. Falta
convertirla en una respuesta, y ahí aparecen cuatro preguntas que no tienen
respuesta obvia y que, mal resueltas, producen un asistente peligroso en vez de
uno útil:

1. **¿Quién escribe la referencia?** Si la escribe el modelo, no hay forma de
   saber si el documento y la página que nombra existen.
2. **¿Cuándo se considera que hay respaldo suficiente?** ADR 0016 prohibió
   expresamente inventar un umbral sobre la puntuación de RRF, que es la
   tentación inmediata.
3. **¿Qué se le dice al ingeniero cuando falla el proveedor?** La respuesta
   fácil —«no encontré información»— es una mentira con consecuencias físicas.
4. **¿Qué pasa cuando un documento contiene instrucciones?** Los manuales de
   planta se copian, se traducen y se pegan de muchos sitios; asumir que su
   texto es inocuo es asumir de más.

## Decisión

### 1. El modelo señala con marcadores; el backend resuelve la referencia

El modelo cita `[E1]`, `[E2]`: identificadores de las evidencias que se le
entregaron en ese mismo contexto. Documento, versión, apartado y página los
compone el backend leyendo la procedencia real del chunk.

Es lo único que hace cierta la promesa de que **toda referencia visible es
verificable**. El modelo nunca escribe el nombre de un documento y espera que
se le crea.

### 2. Una cita que no corresponde a la evidencia entregada se descarta

Un marcador no entregado no se corrige ni se aproxima al más parecido: se
descarta, se retira del texto visible y se levanta `invalid_citation`.
Aproximarlo produciría exactamente la cita falsa que esta capa existe para
impedir. La respuesta se entrega —tirarla perdería lo que sí estaba bien— pero
**nunca como `ANSWERED`**.

### 3. El estado lo decide el servicio, con hechos, no el modelo

Cuatro estados: `ANSWERED`, `PARTIAL`, `NO_EVIDENCE`, `ERROR`.

`ANSWERED` exige las tres cosas a la vez: que el modelo no haya declarado
insuficiencia, que haya citado al menos una evidencia real y que no haya citado
ninguna inexistente. Basta que falle una para que la respuesta salga marcada.

Para declarar insuficiencia el modelo escribe un **centinela literal**
(`SIN_EVIDENCIA_SUFICIENTE`) y no una frase libre: deducirlo de la redacción
sería adivinar, y «no puedo responder» y «no citó nada» exigen tratamientos
distintos.

### 4. `ERROR` no es `NO_EVIDENCE`, y la distinción es de seguridad

Un fallo del proveedor —caída, expiración o respuesta vacía— se declara como
fallo técnico y jamás como ausencia de información.

No es una sutileza de contrato: un ingeniero que lee «no hay información sobre
esto» concluye que el dato no está documentado y decide con esa creencia. Si lo
que pasó es que se cayó el modelo, esa creencia es falsa y la indujimos
nosotros.

**Y un `ERROR` entrega igualmente las citas que ya tenía.** La evidencia se
recuperó y se autorizó antes de llamar al proveedor, así que sigue siendo
válida cuando este falla: lo único que falta es la redacción. Devolver el aviso
sin el material dejaría al ingeniero peor de lo que estaba, y es lo que hace
cumplible la regla 9 —el sistema funciona parcialmente sin LLM y lo declara—.

El centinela de insuficiencia **no se le muestra al usuario**: es cómo el
modelo nos avisa, no cómo se le habla a una persona. Se retira del texto
visible y la señal viaja en `status` y en el aviso correspondiente.

### 5. La suficiencia sale de señales observables, nunca de una puntuación

`SUFFICIENT` requiere que la recuperación declarara `EvidenceStrength.SUFFICIENT`
—coincidencia literal del identificador, o acuerdo entre canales
independientes—, que el modelo citara evidencia real y que no citara ninguna
inventada. **Ninguna puntuación de RRF entra en la decisión**, como exige
ADR 0016.

La detección de contradicciones entre evidencias queda **pendiente de
calibración** con corpus real: exige entender el contenido, y un detector
heurístico marcaría como contradictorias dos redacciones distintas del mismo
procedimiento.

### 6. La evidencia es dato, y lo que lo garantiza es la estructura

Las instrucciones van en el mensaje de sistema; la evidencia va **siempre** en
el de usuario, dentro de una valla delimitada cuyas imitaciones se neutralizan
antes de componer. El aviso del prompt de sistema acompaña, pero lo que protege
es que el texto de un documento no ocupe nunca el lugar de una instrucción.

**La neutralización cubre los dos lados, no solo el documento.** La pregunta
comparte mensaje con la evidencia, así que quien pregunta puede redactar un
bloque entero con el marcador `[E1]`; al citarlo, el verificador lo resolvería
contra procedencia real y devolvería un dato inventado por el usuario con una
cita verificable y estado `ANSWERED`. La pregunta se neutraliza igual y sus
marcadores se retiran. Lo mismo la cabecera del bloque, cuyo título sale de un
archivo que subió alguien.

El texto sospechoso **no se censura**: se neutraliza el formato y se deja
legible. Un pasaje recortado por precaución sería un pasaje que el ingeniero no
puede comprobar contra su documento.

### 7. El prompt de sistema vive en el código

Versionado y probado, no en la base ni en una variable de entorno. Si
cualquiera pudiera cambiarlo sin pasar por revisión, todas las reglas que
declara serían decorativas. Una prueba fija que es **idéntico** para toda
pregunta y toda evidencia.

### 8. No se elige proveedor de LLM en este bloque

No existe decisión previa registrada y este bloque **no la inventa**. Todo se
construyó contra `LLMPort` con un adaptador determinista. La decisión —dónde se
ejecuta, con qué coste, con qué implicación de privacidad— es del responsable
del proyecto y se registrará en su propio ADR.

Consecuencia aceptada: no hay comando operativo que responda preguntas de
verdad hasta que ese adaptador exista. Añadir uno contra el fake daría una
demostración falsa.

### 9. El presupuesto de contexto se cuenta en caracteres

Contar tokens exige el tokenizador del proveedor, que no está decidido. Los
caracteres son conservadores, independientes del modelo y exactos. Se traduce
cuando haya proveedor.

## Consecuencias

- Una cita visible siempre corresponde a un pasaje real que el usuario tenía
  autorizado. No hay camino por el que el modelo fabrique una fuente.
- El sistema puede abstenerse **sin gastar una llamada** al proveedor: sin
  evidencia no se genera. Además evita el caso peor, que es pedirle a un modelo
  que responda sin material —tiende a rellenar—.
- Una respuesta marcada `PARTIAL` con avisos es más frecuente que un
  `ANSWERED`. Es deliberado: el listón de «respondido» es alto.
- El bloque siguiente puede conectar el chat web contra un contrato cerrado, y
  serializar `audit` o no según quién pregunte.

## Alternativas descartadas

**Que el modelo escriba la referencia en texto libre.** Es lo que hace la
mayoría de asistentes y es justo el fallo que no podemos permitirnos: una
página inventada sobre un equipo real manda a alguien a buscar algo que no
existe, o peor, a confiar en un procedimiento que nadie escribió.

**Usar `rrf_score > X` como umbral de suficiencia.** Prohibido por ADR 0016 y,
además, incalculable: con dos canales y `k = 60` el máximo posible es `≈ 0,033`,
así que cualquier umbral con aspecto razonable marcaría todo como insuficiente.

**Rechazar entera una respuesta con una cita inválida.** Se descartó porque
tira también lo que estaba bien citado. Descartar la cita falsa, avisar y bajar
el estado conserva la información sin conservar la mentira.

**Filtrar el texto que parezca una instrucción.** Produciría falsos positivos
sobre prosa técnica legítima y dejaría al ingeniero con un pasaje mutilado que
no coincide con su documento. Se neutraliza el formato, no el contenido.

**Elegir un proveedor «provisional» para poder demostrar el flujo.** Añadiría
una dependencia externa, un coste y una implicación de privacidad que nadie ha
aprobado, y la provisionalidad de estas cosas dura hasta que alguien la cita
como decisión tomada.

## Ver también

- [ADR 0016](0016-recuperacion-hibrida-del-mvp.md) — recuperación híbrida; RRF sin umbral calibrado
- [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md) §6 — los filtros son obligatorios
- [ADR 0012](0012-ciclo-de-vida-documental-propio.md) — qué significa que una versión esté publicada
- [ADR 0003](0003-puertos-y-adaptadores-para-modelos-reemplazables.md) — el proveedor de LLM sigue abierto
- [`rag-generacion.md`](../rag-generacion.md) — implementación y contrato
