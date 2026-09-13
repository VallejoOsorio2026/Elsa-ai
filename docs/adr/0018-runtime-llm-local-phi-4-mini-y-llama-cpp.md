# ADR 0018 — Runtime de generación local: Phi-4-mini sobre llama-server persistente

- Estado: **aceptado**
- Bloque: 4.5
- Cierra el proveedor que [ADR 0003](0003-puertos-y-adaptadores-para-modelos-reemplazables.md)
  dejó deliberadamente abierto, sin reabrir el puerto
- Deriva de [ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md)
  (el backend resuelve las citas y decide el estado) y de
  [ADR 0016](0016-recuperacion-hibrida-del-mvp.md) (la evidencia llega ya
  autorizada)
- Aplica las reglas 1, 2, 9 y 13 de `CLAUDE.md`
- Implementación y operación en [`llm-runtime.md`](../llm-runtime.md)

## Contexto

El Bloque 4.4 dejó el camino completo de la respuesta —contexto, política,
verificación, estados— contra un `LLMPort` sin nadie detrás. Eso era el diseño
previsto, no deuda: ADR 0003 mantuvo abierto el proveedor precisamente para no
atarse antes de tiempo.

Al conectarlo hay cuatro preguntas que, mal resueltas, producen un sistema
peor que el que no responde nada:

1. **¿Qué modelo?** Y sobre todo, ¿con qué criterio se elige, si el modelo no
   es lo que sostiene las garantías del bloque anterior?
2. **¿Dónde se ejecuta?** Una API comercial resolvería el problema técnico y
   crearía otro: enviar documentación interna de planta a un tercero que nadie
   ha aprobado.
3. **¿Cómo se invoca?** `llama.cpp` permite cargar el modelo por consulta o
   mantenerlo cargado, y la diferencia en PC1 es de un orden de magnitud.
4. **¿Qué pasa cuando el modelo no está?** El Bloque 4.4 ya decidió que es
   `ERROR` y no `NO_EVIDENCE`; queda decidir si el backend puede siquiera
   arrancar sin él.

El hardware disponible —PC1: Ryzen 3 2200G, 8 GB de RAM, Radeon RX 570 con
**4 GB** de VRAM— acota el espacio de respuestas más que ninguna preferencia.

## Decisión

### 1. La generación del MVP es local. Ninguna API comercial participa

Ni OpenAI, ni Anthropic, ni Gemini, ni Azure OpenAI, ni ninguna otra.

El motivo no es el precio. ELSA consulta manuales, planos y AMEF de la Planta
Molino Barbosa: cada pregunta que llega al modelo lleva dentro pasajes de
documentación interna. Mandarlos a un tercero es una decisión sobre datos de
PAPELSA que no corresponde tomar aquí, y menos «provisionalmente» —la
provisionalidad de estas cosas dura hasta que alguien la cita como decisión
tomada—.

Local además hace cierta la regla 9 de otra manera: el sistema no depende de
que un proveedor externo esté disponible, ni de una cuota, ni de una clave que
caduca.

### 2. El modelo es Phi-4-mini-instruct, GGUF Q4_K_M

**Microsoft Phi-4-mini-instruct**, formato GGUF, cuantización Q4_K_M, del
repositorio `bartowski/microsoft_Phi-4-mini-instruct-GGUF`.

El criterio de elección fue **el comportamiento en seguridad y
fundamentación**, no la calidad general de la redacción: en las pruebas de
ELSA, Phi se comportó mejor que Qwen3-4B-Instruct-2507 ante evidencia con
instrucciones incrustadas y ante peticiones de saltarse el alcance.

Q4_K_M no es una preferencia estética: es lo que cabe en 4 GB de VRAM junto
con un contexto de 2048 dejando margen. Con más VRAM la decisión se revisa.

**Qwen3-4B-Instruct-2507 queda como alternativa de referencia**, evaluada y no
descartada, pero no conectada. Sustituir el modelo exige un ADR nuevo, no
cambiar una variable de entorno.

### 3. El runtime es `llama-server`, persistente, no `llama-cli` por consulta

`llama-cli` carga el modelo, genera y termina. Invocarlo por consulta
significa releer más de 2 GB de disco, reservar y liberar VRAM y volver a
calentar todo en cada pregunta: en PC1 convierte una respuesta de segundos en
una de decenas, y en una tarjeta de 4 GB arriesga quedarse corta a mitad de
una generación.

`llama-server` carga el modelo una vez y atiende peticiones HTTP. ELSA le
habla por `/v1/chat/completions`, que aplica la plantilla de conversación que
el propio GGUF declara. Formatear los turnos de Phi a mano dentro de ELSA
—`<|system|>`, `<|user|>`, `<|end|>`— codificaría el formato de un modelo
concreto en el adaptador y fallaría en silencio el día que se cambie de
modelo: el servidor no avisa, simplemente genera peor.

Que ese esquema sea compatible con el de OpenAI **no introduce un proveedor
comercial**: es el formato que implementa llama.cpp, servido desde 127.0.0.1.

Versión de referencia validada: **b10938** (commit `f1e44dcc1`), backend
**Vulkan**, dispositivo `Vulkan0`.

### 4. El modelo nunca se carga dentro del proceso de FastAPI

`LlamaCppAdapter` abre un cliente HTTP y nada más. No descarga pesos, no
reserva VRAM y ni siquiera comprueba en el arranque que el servidor exista.

De ahí salen tres propiedades que importan:

- El backend **arranca con el modelo apagado**, y lo declara en
  `/health/ready` como `degraded`, nunca como `down`: el motor de generación
  no es una dependencia crítica (regla 9).
- El backend **sigue desplegándose en Render**, donde no hay ni GPU ni pesos.
- El ciclo de vida de la aplicación no queda atado al del modelo. Comprobar la
  salud del runtime al arrancar parecería inofensivo y bloquearía el
  despliegue durante la carga de los pesos.

Las rutas físicas —el `.gguf` y el ejecutable— se declaran en configuración
pero **solo las leen los scripts de arranque**. Una prueba lo comprueba por
AST: el día que alguien las use en el arranque «solo para verificar que el
archivo existe», el servicio web pasaría a depender de que los pesos estén en
disco.

### 5. El runtime escucha solo en loopback, y salir de ahí se declara

`llama-server` no lleva autenticación y este bloque **no se la añade**,
porque mientras solo escuche en 127.0.0.1 no la necesita: la superficie
pública de ELSA sigue siendo FastAPI.

Una URL que no sea loopback detiene el arranque con un error explícito.
`0.0.0.0` no cuenta como loopback: no es una dirección de destino, es «todas
las interfaces», que es exactamente lo que no puede ocurrir por descuido.
Exponerlo exige `ELSA_LLM_ALLOW_REMOTE=true`, y entonces la decisión —y la
obligación de protegerlo— es de quien la declara.

### 6. Phi no es la barrera de seguridad, y el diseño lo asume

La cadena es

```
autorización → retrieval autorizado → Context Builder → Generation Policy
            → Phi → Grounding Validator → respuesta
```

De esos siete pasos, Phi es el único que no se puede auditar. Las pruebas
mostraron que incluso un modelo adecuado interpreta a veces una instrucción
incrustada en un documento como contenido contradictorio en vez de como texto
inerte.

Por tanto **ninguna garantía del sistema descansa en que el modelo obedezca**.
Las evidencias siguen siendo datos no confiables, el backend sigue resolviendo
las citas contra la procedencia real, el estado lo sigue decidiendo el
servicio, el modelo no recibe evidencia fuera de alcance ni versiones sin
publicar, y no decide ningún permiso porque no recibe ninguno que decidir.

Cambiar de modelo no cambia nada de esto. Ese es el punto.

### 7. Los límites operativos son configuración, no código

Contexto, tokens de salida, plazo y concurrencia entran por configuración y se
aplican en el adaptador. Hoy no hay coste por token —Phi es local— así que no
hay facturación que implementar; lo que queda preparado es lo que permitirá
imponer un presupuesto operativo cuando los costes relevantes (energía,
hardware, hosting) haya que acotarlos.

La concurrencia se limita **en el adaptador y en el servidor con el mismo
número**. `llama-server` sirve tantas peticiones a la vez como ranuras se le
pidieran con `--parallel`, y cada ranura reparte el mismo contexto: mandarle
más no acelera nada y en 4 GB de VRAM reparte la memoria entre trabajos que
compiten.

## Consecuencias

**A favor**

- La documentación interna de planta no sale de la máquina.
- No hay coste por token, ni clave, ni cuota, ni proveedor que pueda cambiar
  sus condiciones.
- El sistema funciona parcialmente con el modelo apagado, y lo dice.
- El puerto sigue siendo un puerto: cambiar de runtime es escribir otro
  adaptador, no tocar la lógica de negocio.

**En contra, y hay que decirlo**

- **Aparece un proceso más que operar.** Arrancarlo, comprobarlo y detenerlo
  es responsabilidad de alguien. De ahí los tres scripts de `scripts/`.
- **El rendimiento lo fija el hardware.** ~20 tokens/s en PC1 es lo que hay;
  una respuesta larga se nota.
- **4 GB de VRAM es el techo real.** Sube el contexto y hay que bajar capas a
  CPU, que es mucho más lento.
- **La prueba con el modelo real no puede estar en CI.** Exigiría GPU y más de
  2 GB de pesos. Se separa en una prueba operativa de PC1, y CI ejercita todo
  el camino del software contra un servidor HTTP que reproduce el contrato de
  llama.cpp.
- **Un modelo de 4B redacta peor que uno grande.** Se acepta: lo que no puede
  fallar son las citas y el alcance, y eso no depende del modelo.

## Alternativas descartadas

**Una API comercial, aunque fuera «solo para demostrar el flujo».** Añade una
dependencia externa, un coste y una implicación de privacidad sobre datos de
PAPELSA que nadie ha aprobado. Ya se descartó en ADR 0017 y aquí se confirma.

**`llama-cli` por consulta.** Más simple de operar —no hay proceso que
mantener— y un orden de magnitud más lento, con riesgo de agotar la VRAM en
cada carga. La simplicidad que compra no vale lo que cuesta.

**Cargar el modelo dentro del proceso de Python** (`llama-cpp-python`,
`transformers`). Ataría el arranque de FastAPI a la disponibilidad de los
pesos, impediría desplegar en Render y convertiría cada reinicio del backend
en una recarga del modelo. El puerto existe justamente para no tener que hacer
esto.

**Formatear a mano los turnos de Phi contra `/completion`.** Daría control
total sobre el prompt y metería el formato de un modelo concreto dentro de
ELSA. El fallo sería silencioso: el servidor no rechaza un prompt mal
plantillado, solo genera peor.

**Añadir autenticación al `llama-server`.** Protegería algo que no está
expuesto. Mientras escuche solo en loopback, la única superficie que hay que
proteger es FastAPI, y añadir un mecanismo de credenciales aquí sugeriría que
sí es seguro exponerlo.

**Dejar que el modelo escriba las referencias.** Cerrado en ADR 0017 y no se
reabre: ningún modelo, por bueno que sea, puede garantizar que el documento y
la página que nombra existan.

**Esperar a tener más VRAM para elegir.** El bloque necesita demostrar el
camino completo en el hardware que hay. Con más memoria se revisan la
cuantización y el contexto, que es exactamente lo que esta decisión deja
parametrizado.

## Ver también

- [ADR 0017](0017-generacion-fundamentada-y-citas-verificables.md) — el backend resuelve las citas y decide el estado
- [ADR 0016](0016-recuperacion-hibrida-del-mvp.md) — la evidencia llega ya autorizada y ordenada
- [ADR 0003](0003-puertos-y-adaptadores-para-modelos-reemplazables.md) — por qué el proveedor estaba abierto
- [`llm-runtime.md`](../llm-runtime.md) — instalación, operación y línea base de PC1
- [`rag-generacion.md`](../rag-generacion.md) — el camino de la respuesta
