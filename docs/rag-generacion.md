# Bloque 4.4 — generación técnica fundamentada

Entre la evidencia y la respuesta:

```
pregunta + alcances → recuperación híbrida → contexto → LLM → verificación → respuesta citada
```

**El orden de esa línea es el contrato de seguridad del bloque.** La
autorización y la recuperación terminan antes de que exista una sola llamada al
modelo, y la salida del modelo no vuelve a entrar en ninguna búsqueda. No hay
camino por el que el LLM pueda influir en qué se recupera.

## Las seis piezas, y por qué están separadas

| Pieza | Módulo | Responsabilidad |
|---|---|---|
| Recuperación | `services/hybrid_retrieval.py` | Bloque 4.3, sin cambios |
| Contrato de respuesta | `core/answers.py` | Qué es una respuesta de ELSA |
| Selección y contexto | `core/context_builder.py` | Qué ve el modelo, y cuánto |
| Política de generación | `core/generation_policy.py` | Las instrucciones, que son de ELSA |
| Verificación | `core/grounding.py` | Resolver citas contra procedencia real |
| Orquestación | `services/grounded_generation.py` | El camino completo y el estado final |

La recuperación entra por el puerto `EvidenceRetrievalPort`, no por la clase
del Bloque 4.3: la capa de generación no debe saber si detrás hay tres canales
o uno, ni heredar sus dependencias de PostgreSQL para poder probarse.

## Contrato de respuesta

```
GroundedAnswer
├── status        ANSWERED | PARTIAL | NO_EVIDENCE | ERROR
├── answer        el texto, ya sin marcadores inválidos
├── sufficiency   SUFFICIENT | PARTIAL | INSUFFICIENT
├── citations     referencias resueltas contra procedencia real
├── warnings      por qué no es plena, si no lo es
└── audit         rastro técnico — NO es para el usuario normal
```

**`status` y `sufficiency` son ejes distintos y no se colapsan.** El primero
dice qué pudo hacer el sistema; el segundo, cuánto respaldo tenía. Y la
distinción que más importa de todas:

> **`ERROR` nunca se confunde con `NO_EVIDENCE`.**

Un ingeniero que lee «no hay información» concluye que el dato no está
documentado y actúa en consecuencia. Si lo que ocurrió es que se cayó el
proveedor, esa conclusión es falsa y la indujimos nosotros. Un fallo técnico se
declara como fallo técnico.

Un `ERROR` **entrega igualmente las citas**: la evidencia se recuperó y se
autorizó antes de llamar al proveedor, así que sigue siendo válida cuando este
falla. Lo único que falta es la redacción. Es lo que hace cumplible la regla 9
—funcionar parcialmente sin LLM y declararlo— y lo que evita que el mensaje
prometa una lista que no lleva.

`audit` lleva los identificadores internos —chunks, modelo, `request_id`— para
que un operador pueda reconstruir qué se recuperó y qué se envió. Va en un
campo aparte precisamente para que la capa HTTP pueda no serializarlo.

## Citas: el modelo señala, el backend resuelve

El modelo **no escribe referencias**. Escribe marcadores `[E1]`, `[E2]` que
señalan las evidencias que se le entregaron; quien compone documento, versión,
apartado y página es el backend, leyendo la procedencia real del chunk.

Es la única forma de que la promesa «toda referencia visible es verificable»
sea cierta. Si el modelo escribiera «Manual P-200, página 14», no habría manera
de saber si esa página existe.

Un marcador que no se entregó **no se corrige ni se aproxima al más parecido**:
se descarta, se retira del texto visible y se levanta el aviso
`invalid_citation`. Aproximarlo produciría exactamente la cita falsa que toda
esta capa existe para impedir. La respuesta se entrega, pero nunca como
`ANSWERED`.

## Suficiencia: señales observables, no un umbral

[ADR 0016](adr/0016-recuperacion-hibrida-del-mvp.md) dejó cerrado que RRF no
tiene umbral de abstención calibrado y que **no se invente uno**. Aquí se
respeta al pie de la letra: ninguna puntuación de fusión entra en la decisión.

`SUFFICIENT` exige las tres cosas a la vez:

1. la recuperación declaró `EvidenceStrength.SUFFICIENT` —hubo coincidencia
   literal del identificador, o canales independientes coincidieron en el mismo
   pasaje—;
2. el modelo citó al menos una evidencia real;
3. no citó ninguna que no se le diera.

Todo lo demás con evidencia es `PARTIAL`. Sin evidencia, o con fallo técnico,
`INSUFFICIENT`.

**Qué falta por calibrar con Tampella real:** la detección de contradicciones
entre evidencias. Está en la lista de señales deseables y no se implementó
porque exige entender el contenido; un detector heurístico marcaría como
contradictorias dos redacciones distintas del mismo procedimiento. Se calibra
con corpus real y consultas del piloto, no antes.

## Inyección documental: la estructura antes que el aviso

Un manual de planta puede contener «ignora las instrucciones anteriores» —por
accidente, por copiar de internet o porque alguien lo puso—. Tres defensas, en
orden de fuerza:

1. **La evidencia nunca ocupa el lugar de una instrucción.** Las instrucciones
   van en el mensaje de sistema; la evidencia, siempre, en el de usuario. Esto
   es lo que protege; el resto ayuda.
2. **Nada que no escribamos nosotros puede romper el formato.** Cada pasaje va
   dentro de una valla delimitada y las líneas que la imitan se neutralizan
   antes de componer —los guiones pasan a puntos medios—. Se normalizan además
   los separadores de línea y los espacios raros, para que la valla no se
   esconda tras un `\r` o un NBSP. El texto **no se censura**: sigue legible y
   citable, pero inerte. Un pasaje mutilado por precaución sería un pasaje que
   el ingeniero no puede comprobar contra su documento.
3. **La pregunta recibe el mismo trato que el documento.** Quien pregunta
   comparte mensaje con la evidencia, así que puede redactar un bloque entero
   y bien formado con el marcador `[E1]`. Si se insertara crudo, el modelo lo
   leería como una evidencia más y, al citarlo, el verificador resolvería `E1`
   contra la procedencia **real**: saldría un dato inventado por el usuario con
   una cita verificable a una página que existe. Por eso la pregunta se
   neutraliza igual, y los marcadores que traiga se retiran — los reparte ELSA
   al componer el contexto, no quien pregunta.
4. **También la cabecera.** El título del documento y el del apartado salen de
   un archivo que subió alguien: se aplanan a una línea y se neutralizan.
5. **El prompt lo declara.** Las reglas 8 y 9 del mensaje de sistema dicen que
   las evidencias son datos, que pueden contener frases con forma de orden y
   que no se obedecen.

Lo que las pruebas fijan no es que el modelo «se porte bien» —con un fake eso
no se demuestra— sino la propiedad estructural que lo hace posible: el mensaje
de sistema es **idéntico** con y sin inyección, y el texto malicioso aparece
solo como contenido de usuario dentro de su valla.

## El presupuesto de contexto

En **caracteres**, no en tokens: contar tokens exige el tokenizador del
proveedor, y el proveedor todavía no está decidido (ADR 0003). Es conservador,
independiente del modelo y exacto; cuando haya proveedor, se traduce.

El recorte es determinista: piezas enteras mientras quepan, y se para en la
primera que no cabe. Única excepción, que la primera pieza por sí sola exceda
el presupuesto — entonces entra recortada y marcada, porque devolver contexto
vacío teniendo evidencia sería peor. **Lo que se recorta es el texto, nunca la
capacidad de citar de dónde salió.**

Nada se paga dos veces: ni el mismo chunk, ni dos chunks con contenido
idéntico —una tabla repetida entre versiones de un manual es un caso real—.
Descartar un duplicado **no** levanta el aviso `evidence_dropped`: no se perdió
información, porque no había nada distinto que citar. Ese aviso queda para lo
que de verdad no cupo.

## Proveedor de LLM: **no elegido**

`LLMPort` existía desde el Bloque 0 y no se tocó. Lo que **no** existe es una
decisión de proveedor y modelo productivo: `docs/architecture.md` dice
`LLM local / autohospedado [no configurado aún]`, ADR 0003 lo deja abierto y no
hay ninguna variable `ELSA_LLM_*` en la configuración.

Este bloque **no la inventa**. Todo se construyó y se probó contra el puerto
con `ScriptedLLMAdapter`, un adaptador determinista que además registra qué se
le mandó — sin ese registro, «la evidencia prohibida nunca llega al modelo»
sería una afirmación sin forma de comprobarse.

Consecuencia operativa honesta: **no hay comando que responda preguntas de
verdad todavía**. Añadir uno que corriera contra el fake daría una demostración
falsa. Llega con el adaptador productivo, cuando haya decisión.

## Ver también

- [ADR 0017](adr/0017-generacion-fundamentada-y-citas-verificables.md) — las decisiones de este bloque
- [ADR 0016](adr/0016-recuperacion-hibrida-del-mvp.md) — recuperación híbrida y por qué no hay umbral
- [ADR 0003](adr/0003-puertos-y-adaptadores-para-modelos-reemplazables.md) — el proveedor sigue abierto
- [`hybrid-retrieval.md`](hybrid-retrieval.md) — los tres canales y la fusión
