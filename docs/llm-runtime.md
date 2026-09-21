# Bloque 4.5 — runtime de generación local

El Bloque 4.4 dejó el camino completo de la respuesta y un puerto `LLMPort`
sin proveedor detrás. Esto conecta el proveedor: **Phi-4-mini-instruct
ejecutándose en la máquina, servido por llama.cpp**.

```
pregunta → autorización → recuperación híbrida → evidencia autorizada
        → Context Builder → llama-server (Phi-4-mini) → Grounding Validator
        → respuesta citada
```

Ninguna API comercial participa en ningún punto. No hay clave, no hay cuenta
y no sale un byte de la máquina.

## La decisión que sostiene todo lo demás: un servidor, no un comando

`llama.cpp` se puede invocar de dos maneras. `llama-cli` carga el modelo,
genera y termina. `llama-server` carga el modelo una vez y atiende peticiones
HTTP hasta que se le detiene.

ELSA usa el segundo, y la diferencia no es de comodidad:

| | `llama-cli` por consulta | `llama-server` persistente |
|---|---|---|
| Carga del GGUF | en cada pregunta | una vez |
| Coste de esa carga | segundos + 2,5 GB de lectura de disco | se paga al arrancar |
| VRAM | se reserva y se libera constantemente | reservada y estable |
| Respuesta de 20 tokens | decenas de segundos | segundos |

En PC1 —una RX 570 con 4 GB— la carga repetida además arriesga fragmentar la
memoria de la tarjeta y quedarse corta a mitad de una generación.

La contrapartida es que **hay un proceso más que arrancar y detener**, y de
ahí salen los tres scripts de `scripts/`.

## Arquitectura

```
Phi-4-mini-instruct Q4_K_M (GGUF)
   ↓  cargado por
llama-server  ──  escucha SOLO en 127.0.0.1:8080
   ↓  HTTP /v1/chat/completions
LlamaCppAdapter          src/elsa/adapters/llama_cpp_llm.py
   ↓  implementa
LLMPort                  src/elsa/ports/llm.py
   ↓  consumido por
GroundedGenerationService  src/elsa/services/grounded_generation.py
```

**FastAPI nunca carga el modelo.** Construir el adaptador abre un cliente
HTTP y nada más: no descarga pesos, no reserva VRAM y ni siquiera comprueba
que el servidor exista. Por eso el backend arranca con el modelo apagado, y
por eso puede seguir desplegándose en Render, donde no hay ni GPU ni pesos.

### Por qué `/v1/chat/completions` y no `/completion`

`llama-server` ofrece las dos. La primera recibe roles y aplica la plantilla
de conversación que **el propio GGUF declara en sus metadatos**; la segunda
recibe el prompt ya formateado.

Phi-4-mini delimita sus turnos con marcas propias (`<|system|>`, `<|user|>`,
`<|end|>`). Reproducirlas a mano dentro de ELSA significaría codificar el
formato de un modelo concreto en el adaptador y equivocarse en silencio el
día que se cambie de modelo: el servidor no avisa, simplemente genera peor.
Que la plantilla la aplique quien lee el archivo es la única versión de esto
que sobrevive a un cambio de modelo.

Que el esquema sea compatible con el de OpenAI **no introduce ningún
proveedor comercial**: es el formato que implementa llama.cpp, servido desde
127.0.0.1.

## La seguridad no depende de Phi

Esto es lo más importante del bloque y conviene decirlo sin adornos: **el
modelo no es la barrera**. La cadena es

```
autorización → retrieval autorizado → Context Builder → Generation Policy
            → Phi → Grounding Validator → respuesta
```

y de esos siete pasos, Phi es el único que no se puede auditar. Las pruebas
del bloque mostraron que incluso un modelo adecuado interpreta a veces una
instrucción incrustada en un documento como contenido contradictorio en vez
de como texto inerte.

Por eso, y esto no cambia con ningún modelo:

| Garantía | Quién la sostiene |
|---|---|
| El modelo no ve evidencia fuera del alcance autorizado | La recuperación, que filtra en cada canal SQL |
| El modelo no ve versiones sin publicar | El mismo filtro, antes de fusionar |
| El modelo no decide permisos | No recibe ninguno que decidir |
| Las citas visibles existen | El backend las resuelve contra la procedencia real |
| Un documento con órdenes dentro no manda | La evidencia viaja como mensaje de usuario, nunca de sistema |
| El estado de la respuesta | El servicio, con hechos observables |

`tests/test_rag_llama_cpp_end_to_end.py` comprueba las tres primeras **sobre
el cuerpo de la petición HTTP**: con el modelo en otro proceso, el prompt es
tráfico de red, así que «ese pasaje nunca llegó al modelo» se verifica
mirando los bytes que salieron de ELSA.

## Instalación en PC1

### 1. llama.cpp

Versión de referencia validada: **b10938** (commit `f1e44dcc1`), backend
**Vulkan**. Se descarga el binario precompilado para Windows con Vulkan, o se
compila. No entra en el repositorio: `.gitignore` cubre `llama.cpp/`,
`llama-server`, `*.exe` y `*.dll`.

Comprobación rápida de que la tarjeta se ve:

```powershell
C:\llama.cpp\llama-server.exe --list-devices
```

Debe aparecer `Vulkan0` con la Radeon RX 570.

### 2. El modelo

**Microsoft Phi-4-mini-instruct**, formato GGUF, cuantización **Q4_K_M**,
desde el repositorio `bartowski/microsoft_Phi-4-mini-instruct-GGUF`. Ocupa
algo más de 2 GB y **nunca entra en Git** (`*.gguf` está en `.gitignore`).

Se guarda donde se quiera, fuera del repositorio, y esa ruta se declara en el
`.env` local.

### 3. Configuración

En `.env` (nunca versionado):

```ini
ELSA_LLM_BACKEND=llama_cpp
ELSA_LLM_BASE_URL=http://127.0.0.1:8080
ELSA_LLM_MODEL=phi-4-mini-instruct
ELSA_LLM_CONTEXT_TOKENS=2048
ELSA_LLM_MAX_OUTPUT_TOKENS=512
ELSA_LLM_TEMPERATURE=0
ELSA_LLM_CONCURRENCY=1
ELSA_LLM_TIMEOUT_SECONDS=120
ELSA_LLM_HEALTH_TIMEOUT_SECONDS=5

# Rutas de esta máquina. Solo las leen los scripts de arranque.
ELSA_LLM_MODEL_PATH=C:\modelos\microsoft_Phi-4-mini-instruct-Q4_K_M.gguf
ELSA_LLAMA_SERVER_PATH=C:\llama.cpp\llama-server.exe
```

Comprobar sin hablar con nadie:

```powershell
uv run python -m elsa.tools.llm_runtime check
```

## Operación

Tres scripts, en `scripts/`. Ninguno cambia nada permanente de Windows: no
instalan servicios, no tocan el registro, no abren puertos en el cortafuegos
y no modifican variables de entorno del sistema. Dejan un archivo de PID y un
log en `%LOCALAPPDATA%\ELSA\llm`.

**No son el «Modo ELSA».** No cierran aplicaciones, no liberan memoria a la
fuerza y no reorganizan nada. Eso es otro bloque.

### Arrancar

```powershell
.\scripts\Start-ElsaLlm.ps1
```

Lee el `.env`, valida que existan el binario y el modelo, arranca
`llama-server` con Vulkan0 y cuatro hilos, **espera a que `/health` devuelva
200** y entonces informa del PID y del tiempo que tardó en quedar listo.

**El contexto, las ranuras, el puerto y el alias salen del mismo `.env` que
lee la aplicación**, no de valores propios del script. Tenerlos duplicados
haría que arrancar con `-ContextSize 4096` dejara a ELSA creyendo 2048: la
validación `ELSA_LLM_MAX_OUTPUT_TOKENS < ELSA_LLM_CONTEXT_TOKENS` pasaría a no
significar nada, porque la ventana real la fija el servidor, y este truncaría
en silencio. Un parámetro explícito sigue ganando, para poder probar.

El servidor arranca con `--no-webui` y con **`--no-slots`**. Lo segundo no es
opcional: el endpoint de ranuras viene **activado por defecto** en llama.cpp y
publica el estado de cada ranura, prompt en curso incluido —es decir, el
bloque de evidencias que ELSA acaba de enviar—, legible con un `GET` y sin
credencial. Loopback protege de la LAN, no de otro proceso ni de otra sesión
de la misma máquina, y PC1 es un equipo de planta. `Test-ElsaLlm.ps1`
comprueba que la versión instalada efectivamente lo respeta.

Esperar al 200 importa: `/health` devuelve 503 mientras carga los pesos, y
devolver el control antes dejaría a quien lance la primera consulta creyendo
que el modelo está caído.

La temperatura no se fija al arrancar. La manda ELSA en cada petición desde
`ELSA_LLM_TEMPERATURE`: un valor de arranque distinto del de la aplicación
haría que la misma configuración diera resultados distintos según quién
hubiera arrancado el servidor.

### Comprobar

```powershell
.\scripts\Test-ElsaLlm.ps1
```

Salud, `/props`, que `/slots` esté cerrado, y una generación mínima con
latencia y tokens/s. Es una comprobación **del runtime**: no hay recuperación
ni citas.

### Detener

```powershell
.\scripts\Stop-ElsaLlm.ps1
```

Detiene **solo** el proceso que arrancó ELSA. Comprueba PID *y* hora de
arranque antes de tocar nada, porque Windows reutiliza los identificadores de
proceso: matar un PID a ciegas puede detener un proceso ajeno. Tampoco hace
`Get-Process llama-server | Stop-Process`, porque en esa máquina puede haber
otro llama.cpp que no es nuestro.

**Y borra el log del servidor.** `llama-server` vuelca por su salida el prompt
que procesa, y el prompt de ELSA es el bloque de evidencias: documentación
interna de planta. Dejarlo en el perfil de quien arrancó el servidor sería un
archivo de texto plano con contenido de planta fuera de toda política de
retención. Para una sesión de medición, `-KeepLog` lo conserva, y entonces
borrarlo es responsabilidad de quien lo pidió.

**Por qué el cierre es directo.** `llama-server` se arranca oculto, así que en
Windows el proceso puede no tener `MainWindowHandle`: `CloseMainWindow()`
devuelve `False` sin llegar a enviar ninguna solicitud de cierre. Esperar el
timeout en ese caso es tiempo perdido, de modo que el script solo espera
cuando la solicitud sí se envió, y si no, fuerza el cierre de inmediato.
Medido en PC1: 20,59 s antes de la corrección, 1,12 s después, sin procesos,
archivos de PID ni logs residuales. El registro y el log se borran solo
después de comprobar explícitamente que el proceso desapareció; si sigue
vivo, el script falla y los conserva.

## Probar el camino de ELSA

Los scripts prueban el runtime. Para el camino del bloque hay una herramienta
de Python:

```powershell
# Configuración, sin mandar una sola petición
uv run python -m elsa.tools.llm_runtime check

# ¿Está listo, con el modelo cargado?
uv run python -m elsa.tools.llm_runtime health

# Generación mínima, con latencia y tokens/s
uv run python -m elsa.tools.llm_runtime generate "Responde solo LISTO."

# Camino RAG sobre evidencia SINTÉTICA: contexto real, citas verificadas
# de verdad, y ni base de datos ni embeddings. Es el comando del primer día.
uv run python -m elsa.tools.llm_runtime demo "¿cada cuánto se lubrica el rodamiento?"

# Camino COMPLETO sobre el corpus recuperado: alcances explícitos,
# recuperación híbrida, contexto, modelo y verificación.
uv run python -m elsa.tools.llm_runtime ask "¿cada cuánto se lubrica el SAP-4471?" `
    --scope mantenimiento:tampella --request-id pc1-001
```

`demo` y `ask` se separan a propósito. `ask` es la demostración del bloque,
pero exige PostgreSQL con conocimiento ingerido y embeddings generados.
`demo` recorre el mismo tramo desde el Context Builder con evidencia
fabricada en el propio comando, así que sirve para comprobar el runtime
cuando todavía no hay corpus. Ninguno de los dos toca datos de planta: los
códigos del corpus sintético llevan `DEMO` dentro para que nadie confunda su
salida con un dato real al leerla meses después.

`demo` pasa por **`GroundedGenerationService`, el servicio real**, no por una
copia suya: solo sustituye la recuperación. Eso importa, porque lo que hay que
comprobar en PC1 no es que el modelo conteste, sino que el sistema completo
hace con esa respuesta lo que promete —descartar los marcadores inventados,
decidir el estado, tratar una salida vacía como fallo técnico y no como
ausencia de información—. Una segunda implementación de esa política aquí
acabaría divergiendo de la de producción, y la herramienta diría que todo está
bien mientras el sistema real hace otra cosa.

Lo que `demo` **no** hace es autorizar: no hay corpus, ni permisos, ni base de
datos, así que los alcances no se comprueban. Eso es de `ask`, que recupera de
verdad, y de `tests/test_rag_llama_cpp_end_to_end.py`. Fingir autorización en
un comando de demostración sería peor que no tenerla, porque saldría bien.

## Qué pasa cuando el runtime falla

Un fallo del modelo es `ERROR`, **jamás** `NO_EVIDENCE`. La distinción no es
cosmética: un ingeniero que lee «no encontré información» concluye que el
dato no está documentado y actúa en consecuencia. Si lo que pasó es que el
modelo estaba apagado, esa conclusión es falsa y la causó el sistema.

| Situación | Estado | `audit.error_code` |
|---|---|---|
| `llama-server` apagado | `ERROR` | `llm_unavailable` |
| Plazo vencido | `ERROR` | `llm_timeout` |
| HTTP 4xx/5xx del runtime | `ERROR` | `llm_unavailable` |
| Cuerpo que no es JSON, o sin `choices` | `ERROR` | `llm_unavailable` |
| Generación vacía | `ERROR` | `llm_empty_response` |
| Sin evidencia autorizada | `NO_EVIDENCE` | — (no se llama al modelo) |

En todos los casos de `ERROR` la respuesta **entrega igualmente los pasajes
recuperados**, citados, para que se puedan consultar directamente. Es lo que
hace que el sistema funcione parcialmente en vez de no funcionar, y lo que el
mensaje promete: prometerlo sin cumplirlo sería peor que no prometerlo.

Sin evidencia autorizada no se llama al modelo. Con el modelo en otro
proceso, abstenerse deja de ser solo una decisión de política y pasa a ser
una petición HTTP que no ocurre: en PC1, decenas de segundos de CPU y GPU que
no se gastan.

Y el motor de generación **no es una dependencia crítica**: con el modelo
caído, `/health/ready` reporta el sistema como `degraded`, no como `down`.

## Red

| | |
|---|---|
| `llama-server` escucha en | `127.0.0.1` únicamente |
| Autenticación del runtime | ninguna, y no hace falta mientras no salga de loopback |
| Superficie pública de ELSA | FastAPI, como siempre |
| `0.0.0.0` | **no** cuenta como loopback: es «todas las interfaces» |

Apuntar ELSA a un runtime remoto detiene el arranque. No existe excepción
para DEV: `ELSA_LLM_ALLOW_REMOTE=true` se rechaza. El cliente ignora proxies
del entorno y no sigue redirecciones. El script solo acepta `127.0.0.1` y
restringe CORS al origen del propio runtime; el navegador no consume el LLM.

Dos cosas más que el arranque cierra por defecto:

| Endpoint de llama.cpp | Por defecto | Con `Start-ElsaLlm.ps1` |
|---|---|---|
| `GET /slots` — estado de cada ranura, **prompt en curso incluido** | activado | `--no-slots` |
| Interfaz web de chat sobre el mismo modelo | activada | `--no-webui` |

Loopback protege de la LAN, no de otro proceso ni de otra sesión de la misma
máquina, y PC1 es un equipo de planta compartido.

## Límites operativos

Hoy no hay facturación porque no hay coste por token: Phi es local. Los
costes reales del MVP son energía, el propio PC, y el hosting que ELSA
conserve (Supabase, Render, dominio).

Lo que sí queda preparado son los límites con los que se podrá imponer un
presupuesto operativo cuando haga falta:

| Límite | Variable | Dónde se aplica |
|---|---|---|
| Contexto | `ELSA_LLM_CONTEXT_TOKENS` | `llama-server`, al arrancar |
| Tokens de salida | `ELSA_LLM_MAX_OUTPUT_TOKENS` | El adaptador, en cada petición |
| Plazo de generación | `ELSA_LLM_TIMEOUT_SECONDS` | El adaptador y el servicio |
| Plazo del sondeo de salud | `ELSA_LLM_HEALTH_TIMEOUT_SECONDS` | El adaptador, en `/health/ready` |
| Generaciones simultáneas | `ELSA_LLM_CONCURRENCY` | Un semáforo en el adaptador |
| Evidencia por respuesta | `DEFAULT_MAX_ITEMS` (Bloque 4.4) | El Context Builder |
| Caracteres de contexto | `DEFAULT_BUDGET_CHARS` (Bloque 4.4) | El Context Builder |

El techo de salida del runtime gana siempre sobre lo que pida el servicio: en
PC1 una salida larga no es una factura, son minutos de espera.

La concurrencia se limita en el adaptador **y** en el servidor, con el mismo
número. `llama-server` sirve tantas peticiones a la vez como ranuras se le
pidieran con `--parallel`, y cada ranura reparte el mismo contexto: mandarle
más no acelera nada —las encola él— y en una tarjeta de 4 GB reparte la VRAM
entre trabajos que compiten.

El adaptador registra en cada generación la duración, los tokens de entrada y
salida, los tokens/s y cuánto se esperó por el semáforo. Cuando
`llama-server` informa de su propio ritmo (`timings.predicted_per_second`) se
prefiere ese, que mide solo la fase de generación; el calculado aquí incluye
además leer el prompt y la red, así que da un número menor y no se mezclan.

## Límites del hardware de PC1

| | |
|---|---|
| CPU | AMD Ryzen 3 2200G, 4 núcleos / 4 hilos |
| RAM | 8 GB |
| GPU | Radeon RX 570, **4 GB** de VRAM |
| Disco | SSD |

Las consecuencias prácticas:

- **4 GB de VRAM es la restricción real.** Phi-4-mini en Q4_K_M cabe con el
  contexto en 2048. Subir el contexto cuesta VRAM y puede obligar a dejar
  capas en CPU, que es mucho más lento.
- **8 GB de RAM con el modelo cargado deja poco margen.** Conviene no tener
  el navegador con veinte pestañas mientras se hacen mediciones.
- **4 hilos.** `--threads 4` es el máximo útil; pedir más solo añade
  contención.
- **Concurrencia 1.** Con esta tarjeta, dos generaciones a la vez no son el
  doble de trabajo: son dos trabajos más lentos y más riesgo de quedarse sin
  memoria.

## Modelo elegido, y el que no

**Phi-4-mini-instruct** frente a **Qwen3-4B-Instruct-2507**: en las pruebas
de ELSA, Phi se comportó mejor en el conjunto de seguridad y fundamentación,
que es lo que decide aquí. Qwen queda como alternativa de referencia, no
descartada pero no conectada.

El detalle de la decisión está en
[ADR 0018](adr/0018-runtime-llm-local-phi-4-mini-y-llama-cpp.md). Cambiarla
exige un ADR nuevo, no una variable de entorno: el modelo es una decisión
cerrada, aunque el runtime sea reemplazable.

## Línea base de rendimiento (PC1)

Estos números **hay que medirlos en PC1**, con el modelo real. Sirven de
línea base para el futuro «Modo ELSA», para estimar el coste energético y
para decidir si merece la pena ampliar la RAM.

`Start-ElsaLlm.ps1` informa del tiempo hasta listo; `Test-ElsaLlm.ps1` y
`llm_runtime demo` informan de latencia y tokens/s. La RAM y la VRAM se leen
con el Administrador de tareas y con `Test-ElsaLlm.ps1`.

Y una advertencia antes de medir: si conservas el log con `-KeepLog` para
diagnosticar algo, **bórralo al terminar**. Contiene el prompt, es decir las
evidencias.

| Medida | Valor |
|---|---|
| Tamaño del GGUF | _pendiente_ |
| Arranque de `llama-server` | _pendiente_ |
| Tiempo hasta `/health` = 200 | _pendiente_ |
| Tokens/s de generación | _pendiente_ (referencia del banco previo: ~20 tok/s) |
| Latencia de una consulta RAG completa | _pendiente_ |
| RAM antes / durante | _pendiente_ |
| VRAM antes / durante | _pendiente_ |
| CPU aproximada durante la generación | _pendiente_ |
| Errores observados | _pendiente_ |

No hacen falta medidas de laboratorio. Una corrida de cada cosa, anotada
aquí, ya permite comparar contra la siguiente.

## Qué prueba CI y qué no

CI **no descarga un modelo de 2 GB ni necesita una GPU**, y no debe. Lo que
sí ejercita es todo el camino del software:

| Prueba | Qué cubre |
|---|---|
| `tests/test_llama_cpp_adapter.py` | El adaptador contra un servidor HTTP real en loopback: petición, respuesta, plazos, errores, concurrencia, métricas |
| `tests/test_rag_llama_cpp_end_to_end.py` | El camino completo con PostgreSQL real: citas resueltas, citas inventadas rechazadas, aislamiento comprobado sobre el cuerpo HTTP |
| `tests/test_llm_runtime_configuration.py` | Configuración inválida, arranque de FastAPI sin modelo, salud |
| `tests/test_llm_runtime_tool.py` | La herramienta de operación que se usa en PC1 |

`tests/fake_llama_server.py` es un servidor HTTP de verdad, no un transporte
simulado. Se hace así porque con un transporte simulado nunca se serializa
nada: una petición mal formada, un cuerpo que no es JSON o un plazo que no se
respeta pasarían desapercibidos. Y porque guarda el cuerpo crudo de cada
petición, que es lo que convierte «la evidencia prohibida nunca llega al
modelo» en algo comprobable.

**La generación real con Phi es una prueba operativa de PC1**, no de CI. Se
ejecuta con `llm_runtime demo` y `llm_runtime ask`, y sus resultados se
anotan en la tabla de arriba.

## Fuera de alcance de este bloque

Interfaz final, audio, voz a texto, «Modo ELSA» de Windows, servicios de
Windows, índices aproximados, reranker, agentes, acceso a internet para
responder, herramientas autónomas, memoria conversacional, datos reales de
PAPELSA, Supabase remoto y migraciones. Tampoco se cambia BGE-M3 ni se
sustituye Phi.
