# D2.7 — Primera consulta remota controlada Render ↔ PC1 — Cierre

Fecha de validación física: 2026-10-25

Repositorio:

```text
VallejoOsorio2026/Elsa-ai
```

Rama documental:

```text
claude/d2-7-cierre-documental
```

Base exacta del bloque:

```text
main
HEAD = origin/main
4a3bd66fdbc0fe2760da1e53eb6a2f4998d03ceb
working tree limpio
```

## 1. Objetivo

D2.7 tuvo como objetivo ejecutar y acreditar por primera vez una consulta remota controlada con el recorrido real:

```text
cliente de prueba controlado
→ HTTPS
→ Render
→ relay
→ agente PC1
→ ELSA local en PC1
→ respuesta
→ agente
→ relay
→ Render
→ cliente
```

El bloque debía superar el límite de D2.6, que había validado NODE ONLINE pero no había autorizado ni ejecutado `assistant.ask` remoto.

Criterios de seguridad de la prueba:

- identidad real, no `fake`;
- autenticación real Supabase;
- autorización efectiva en PC1;
- contenido exclusivamente sintético;
- PC1 sin exposición pública;
- sin apertura de puertos;
- sin port forwarding;
- sin túneles/VPN;
- sin persistencia del JWT;
- token del nodo efímero;
- bootstrap temporal;
- sin datos SAP reales;
- sin BOM real;
- sin consulta de inventario real;
- retorno a baseline seguro después de la prueba.

## 2. Fuera de alcance

D2.7 no incluyó:

- acceso desde PAPELSA;
- operación de usuario final;
- login definitivo de producción;
- publicación de BOM real;
- consulta de material SAP real;
- inventario real;
- automatización ZIAA;
- BOM Tampella;
- rendimiento o carga;
- multiusuario;
- producción;
- cambios de modelo;
- exposición pública de PC1;
- apertura de firewall;
- port forwarding;
- instalación de túneles o VPN.

## 3. Estado heredado de D2.6

D2.6 había cerrado formalmente la conectividad real Render ↔ PC1 hasta NODE ONLINE.

Estado seguro heredado de Render:

```text
Servicio: elsa-relay-pilot
ELSA_ENV=DEV
ELSA_WEB_UI_ENABLED=false
ELSA_RELAY_ENABLED=false
ELSA_ASSISTANT_EXECUTION_MODE=local
ELSA_AUTH_PROVIDER=fake
```

Al iniciar D2.7 no existían:

```text
node id activo
node token hash activo
PC1 conectado
assistant.ask remoto autorizado
```

La decisión de seguridad vigente de ADR 0035 establecía:

> RELAY con identidad fake NO está autorizado para enviar `assistant.ask` a PC1.

D2.7 respetó esa restricción.

# 4. D2.7-A — Auditoría de arquitectura y autorización

Antes de realizar cualquier llamada remota se auditó el flujo existente sin modificar código.

## 4.1 Router remoto de assistant

`assistant_relay.py` expone el mismo contrato público de `assistant.ask` cuando:

```text
ELSA_ASSISTANT_EXECUTION_MODE=relay
```

Comportamiento relevante verificado:

- rechaza reentrada mediante `X-Elsa-Relay-Hop`;
- Render autentica JWT;
- Render aplica control de abuso;
- Render no decide autorización funcional de dominio/equipo;
- la autorización completa se conserva en PC1;
- no existe fallback automático al modo local de Render;
- la respuesta recibida del relay se valida contra `AskResponse`;
- logs de relay no deben registrar token, pregunta, adjuntos ni respuesta completa.

## 4.2 Cadena real de autorización en PC1

La cadena auditada es:

```text
Bearer JWT
→ autenticación Supabase
→ perfil Materiales activo
→ cuenta ELSA activa
→ permisos/grants
→ RequireScope(domain, equipment)
→ activo autorizado
→ conocimiento
→ assistant.ask
```

La postura es `default deny`.

Se verificó que una identidad Supabase válida sin cuenta ELSA activa recibe `403`.

## 4.3 Autorización antes de recuperar el activo

`resolve_asset` depende de `RequireScope`.

Orden efectivo:

```text
autorización
→ después recuperación del activo
```

Un equipo inexistente, de otro dominio o inactivo no se utiliza para eludir autorización ni para filtrar existencia antes del control de permisos.

## 4.4 RequireScope

`RequireScope`:

- normaliza dominio/equipo;
- depende de `current_principal`;
- construye el scope requerido;
- llama a `authorize`;
- ante denegación devuelve `403`;
- mantiene postura default deny.

## 4.5 Identidad fake

Se confirmó que técnicamente la configuración no bloqueaba de forma absoluta:

```text
DEV + fake + relay
```

pero esto no constituía autorización para D2.7.

Los tokens `fake` son valores sintéticos fijos del código y no se consideraron una credencial aceptable para un endpoint público en Render.

Conclusión:

```text
fake NO usado para assistant.ask remoto D2.7
```

## 4.6 Agente PC1

El agente auditado:

- usa conexión saliente hacia Render;
- usa cliente independiente para ELSA local;
- utiliza `trust_env=False`;
- solo acepta ELSA local sobre loopback literal;
- transmite al ELSA local el mismo Bearer JWT recibido;
- añade `X-Elsa-Relay-Hop: 1`;
- no permite a Render elegir host, puerto, URL arbitraria o método arbitrario;
- no reejecuta una solicitud por fallos en la entrega del resultado;
- serializa el resultado una sola vez;
- conserva control de expiración/capacidad/duplicados.

## 4.7 Consulta sin material SAP

La pregunta sintética seleccionada no contiene código de material SAP.

De acuerdo con el flujo auditado de `assistant.py`, sin un código de material exacto aplicable no se ejecuta la consulta de disponibilidad de inventario.

Esto permitió comprobar el recorrido remoto sin consultar inventario real.

## 4.8 Activo sin BOM publicado

Se verificó que un activo válido sin versión publicada no produce error.

Respuesta esperada:

```text
HTTP 200
published = false
mensaje informativo presente
```

Esto permitió usar un activo completamente sintético sin BOM ni conocimiento real.

## 4.9 Repositorios en memoria

Se confirmó que en DEV es posible combinar:

```text
auth_provider = supabase
permissions_backend = memory
knowledge = memory
demo_seed = false
```

manteniendo autenticación real y datos ELSA sintéticos/efímeros.

El dominio `mantenimiento` existe en el repositorio de permisos en memoria.

## 4.10 Bootstrap administrativo

Se auditó `/api/v1/admin/bootstrap`.

Características relevantes:

- requiere identidad real verificada;
- requiere token de bootstrap;
- solo funciona si todavía no existe administrador;
- el sujeto administrativo proviene del JWT autenticado;
- el secreto de bootstrap no sustituye identidad;
- puede utilizarse con permisos en memoria;
- el administrador tiene autorización global dentro de ese repositorio temporal.

## 4.11 Login controlado

Para D2.7 se utilizó el patrón técnico ya empleado anteriormente:

```text
email + contraseña introducidos con getpass
→ Supabase Auth
→ access token solo en memoria del script
→ JWT no impreso
→ JWT no almacenado
```

No se utilizó `service_role`.

# 5. D2.7-B — Diseño mínimo seleccionado

No se encontró necesidad de cambiar código.

## PC1

```text
ELSA_ENV=DEV
ELSA_AUTH_PROVIDER=supabase
ELSA_PERMISSIONS_BACKEND=memory
ELSA_DEMO_SEED=false
ELSA_WEB_UI_ENABLED=false
ELSA_RELAY_ENABLED=false
ELSA_ASSISTANT_EXECUTION_MODE=local
```

Estos valores se aplicaron únicamente al proceso temporal D2.7.

El `.env` normal de PC1 permaneció:

```text
auth = supabase
permissions = postgres
assistant mode = local
relay = false
```

## Activo sintético

```text
domain = mantenimiento
code = d27-test
name = D2.7 Synthetic Test Asset
description = Activo temporal sintético para validación D2.7.
```

No se publicó BOM.

## Pregunta sintética

```text
¿Existe conocimiento publicado para esta prueba sintética?
```

No contiene código SAP.

## Render

Durante la ventana D2.7 se utilizó:

```text
ELSA_ENV=DEV
ELSA_WEB_UI_ENABLED=false
ELSA_AUTH_PROVIDER=supabase
ELSA_ASSISTANT_EXECUTION_MODE=relay
ELSA_RELAY_ENABLED=true
ELSA_RELAY_NODE_ID=pc1-pilot
```

Además:

```text
ELSA_MATERIALS_SUPABASE_URL
ELSA_MATERIALS_API_KEY
```

La API key utilizada fue la clave pública/publishable configurada para Materiales.

No se configuró en Render:

```text
contraseña
JWT
service_role
ELSA_BOOTSTRAP_ADMIN_TOKEN
ELSA_DEMO_SEED
base de datos ELSA
credencial SAP
```

# 6. D2.7-C — Validación local

## 6.1 Gate de configuración normal PC1

Estado observado:

```text
ELSA_ENV = DEV
ELSA_AUTH_PROVIDER = supabase
ELSA_PERMISSIONS_BACKEND = postgres
ELSA_DEMO_SEED = False
ELSA_ASSISTANT_EXECUTION_MODE = local
ELSA_RELAY_ENABLED = False
ELSA_WEB_UI_ENABLED = True
MATERIALS_SUPABASE_URL_CONFIGURED = True
MATERIALS_API_KEY_CONFIGURED = True
BOOTSTRAP_ADMIN_TOKEN_CONFIGURED = False
```

Esto confirmó que no debía utilizarse el backend PostgreSQL normal para crear datos sintéticos.

## 6.2 Gate de composición aislada

Con overrides únicamente de proceso:

```text
AUTH_ADAPTER = SupabaseJwtAuthAdapter
MATERIALS_IDENTITY = SupabaseMaterialsIdentityAdapter
PERMISSIONS = InMemoryPermissionsRepository
KNOWLEDGE = InMemoryKnowledgeRepository
```

Resultado:

```text
PASS
```

No se modificó `.env`.

## 6.3 Identidad real + default deny

Login Supabase:

```text
SUPABASE_LOGIN = 200
```

JWKS:

```text
jwks refreshed
key_count = 1
```

Antes del bootstrap:

```text
GET /api/v1/me
HTTP 403
access denied: no active ELSA account
```

Resultado:

```text
DEFAULT DENY = ACREDITADO
```

El identificador concreto del usuario autenticado se omite deliberadamente del cierre.

## 6.4 Incidente de login 400

En una ejecución posterior se obtuvo inicialmente:

```text
SUPABASE_LOGIN = 400
```

Se detuvo correctamente el gate.

Se ejecutó diagnóstico sin mostrar credenciales:

```text
STATUS = 200
```

La autenticación volvió a funcionar normalmente.

No se encontró evidencia de fallo arquitectónico o de configuración persistente. Se trató como incidencia puntual de entrada/autenticación y el gate fue repetido antes de continuar.

## 6.5 Bootstrap + activo + assistant local

Resultado final del gate:

```text
SUPABASE_LOGIN = 200
BOOTSTRAP_STATUS = 200
BOOTSTRAP_CREATED = True
ME_AFTER_BOOTSTRAP = 200
CREATE_ASSET_STATUS = 201
ASK_STATUS = 200
ASK_ASSET = d27-test
ASK_PUBLISHED = False
ASK_HAS_MESSAGE = True
D27_C_LOCAL_GATE_COMPLETE = True
```

Resultado:

```text
D2.7-C = PASS
```

## 6.6 Limpieza después del gate local

Se verificó:

```text
working tree limpio
AUTH = supabase
PERMISSIONS = postgres
DEMO_SEED = False
ASSISTANT_MODE = local
RELAY = False
BOOTSTRAP_CONFIGURED = False
```

No persistieron los datos en memoria del gate.

# 7. Preparación segura de D2.7-D

## 7.1 Separación de entornos

La auditoría del supervisor confirmó:

```text
ELSA local → elsa_environment(...)
Agente     → agent_environment(...)
```

`elsa_environment` elimina explícitamente:

```text
ELSA_AGENT_NODE_TOKEN
```

antes de iniciar ELSA.

El agente recibe el token únicamente en su propio entorno.

## 7.2 Bootstrap y token del nodo

Para evitar que el agente heredara el bootstrap, D2.7-D inició:

```text
ELSA local
y
agente PC1
```

como procesos separados.

Separación obtenida:

```text
ELSA:
- bootstrap temporal
- NO token del nodo

Agente:
- token del nodo
- NO bootstrap
```

## 7.3 Configuración no sensible del agente

El `.env` ya contenía desde D2.6:

```text
ELSA_AGENT_RELAY_URL=https://elsa-relay-pilot.onrender.com
ELSA_AGENT_NODE_ID=pc1-pilot
ELSA_AGENT_LOCAL_BASE_URL=http://127.0.0.1:8000
```

No fue necesario modificarlo.

## 7.4 ELSA temporal

ELSA D2.7 se inició únicamente en:

```text
127.0.0.1:8000
```

Resultado:

```text
D27_ELSA_READY_STATUS = 200
D27_ELSA_LOCAL_ONLY = True
BOOTSTRAP_ENV_IN_PARENT = False
```

La referencia temporal del bootstrap también fue retirada posteriormente de la variable PowerShell del operador.

## 7.5 Activo dentro del mismo proceso usado por el relay

En la ELSA temporal que posteriormente recibió las consultas del agente:

```text
SUPABASE_LOGIN = 200
BOOTSTRAP_STATUS = 200
ME_STATUS = 200
CREATE_ASSET_STATUS = 201
LOCAL_ASK_STATUS = 200
LOCAL_ASK_ASSET = d27-test
LOCAL_ASK_PUBLISHED = False
LOCAL_ASK_HAS_MESSAGE = True
BOOTSTRAP_ENV_AFTER_CALL = False
ELSA_PROCESS_ALIVE = True
```

Esto garantizó que el activo sintético existiera en el mismo repositorio en memoria utilizado por la prueba remota.

# 8. D2.7-D — Primera consulta remota real

## 8.1 Credencial nueva del nodo

Se generó una nueva credencial exclusiva para D2.7-D.

Características observadas:

```text
NODE_TOKEN_PRESENT = True
NODE_TOKEN_LENGTH = 43
NODE_HASH_LENGTH = 64
```

Reglas aplicadas:

- token crudo no se mostró;
- token crudo no se pegó en Render;
- token crudo no se escribió en `.env`;
- solo el SHA-256 se configuró en Render;
- hash copiado temporalmente al portapapeles;
- portapapeles limpiado posteriormente;
- token crudo retirado del entorno y de la variable PowerShell después de arrancar el proceso agente.

No se afirma borrado físico seguro de memoria del runtime.

## 8.2 Gate Render antes de conectar PC1

Con Render temporalmente configurado para D2.7:

```text
RENDER_READY_STATUS = 200
REGISTER_WITHOUT_CREDENTIAL = 401
REMOTE_ASK_WITHOUT_JWT = 401
```

Esto acreditó:

- Render operativo;
- relay montado;
- registro del nodo protegido;
- `assistant.ask` remoto montado;
- `assistant.ask` remoto protegido por JWT real.

## 8.3 NODE ONLINE

El agente temporal arrancó correctamente:

```text
AGENT_PROCESS_ALIVE = True
NODE_TOKEN_ENV_IN_PARENT = False
NODE_TOKEN_PS_VARIABLE_PRESENT = False
ELSA_PROCESS_ALIVE = True
```

Eventos:

```text
agent_started
2026-10-25T18:11:53.317483+00:00

node_registered
2026-10-25T18:11:53.736697+00:00
```

Node:

```text
pc1-pilot
```

Sesión:

```text
ad8284a2-d550-436a-badc-b886d9f6d44e
```

Resultado:

```text
NODE ONLINE = ACREDITADO
```

## 8.4 Primera assistant.ask remota real

Login previo:

```text
SUPABASE_LOGIN = 200
```

Request HTTP del cliente:

```text
22cc95e9-a65c-4fb3-ae7d-cf2d11579e4f
```

Resultado recibido por el cliente:

```text
REMOTE_ASK_STATUS = 200
REMOTE_ASK_ASSET = d27-test
REMOTE_ASK_PUBLISHED = False
REMOTE_ASK_HAS_MESSAGE = True
```

Resultado:

```text
PRIMERA CONSULTA REMOTA CONTROLADA = PASS
```

# 9. Trazabilidad extremo a extremo

Se identificaron correctamente dos IDs distintos:

```text
HTTP request_id
22cc95e9-a65c-4fb3-ae7d-cf2d11579e4f

relay_request_id
e963c0a2-369a-464c-ab28-25ee9c35d9a9
```

Esto no constituye pérdida de trazabilidad.

## 9.1 Render — queue

```text
event = request_queued
request_id = 22cc95e9-a65c-4fb3-ae7d-cf2d11579e4f
relay_request_id = e963c0a2-369a-464c-ab28-25ee9c35d9a9
node_session_id = ad8284a2-d550-436a-badc-b886d9f6d44e
```

## 9.2 Render — dispatch

```text
event = request_dispatched
relay_request_id = e963c0a2-369a-464c-ab28-25ee9c35d9a9
node_session_id = ad8284a2-d550-436a-badc-b886d9f6d44e
state = dispatched
```

El `request_id` del log HTTP interno de esta operación puede ser diferente y no sustituye al `relay_request_id`.

## 9.3 Agente PC1

```text
request_accepted
request_id = e963c0a2-369a-464c-ab28-25ee9c35d9a9

local_call_finished
request_id = e963c0a2-369a-464c-ab28-25ee9c35d9a9
duration_ms = 1110

result_delivered
request_id = e963c0a2-369a-464c-ab28-25ee9c35d9a9
attempt = 1
```

## 9.4 ELSA local

```text
POST /api/v1/assistant/mantenimiento/d27-test/ask
status_code = 200
request_id = e963c0a2-369a-464c-ab28-25ee9c35d9a9
duration_ms = 1080.68
```

## 9.5 Render — completion

```text
event = request_completed
relay_request_id = e963c0a2-369a-464c-ab28-25ee9c35d9a9
state = completed
duration_ms = 1777
```

## 9.6 Render — respuesta al cliente

```text
event = assistant_relayed
request_id = 22cc95e9-a65c-4fb3-ae7d-cf2d11579e4f
relay_request_id = e963c0a2-369a-464c-ab28-25ee9c35d9a9
outcome = ok
status_code = 200
duration_ms = 1778.85
```

Access log final:

```text
POST /api/v1/assistant/mantenimiento/d27-test/ask
request_id = 22cc95e9-a65c-4fb3-ae7d-cf2d11579e4f
status_code = 200
duration_ms = 1797.36
```

Conclusión:

```text
CORRELACIÓN EXTREMO A EXTREMO = PASS
```

Render relaciona explícitamente:

```text
request_id del cliente
↔ relay_request_id interno
```

y el `relay_request_id` se conserva en agente y ELSA.

# 10. Seguridad observada durante la prueba

En la evidencia revisada no aparecieron:

- contraseña;
- JWT;
- token crudo del nodo;
- secreto de bootstrap;
- pregunta completa en logs de relay/agente;
- datos SAP reales.

El token del nodo:

- nunca se escribió en `.env`;
- solo estuvo en memoria de la sesión/proceso;
- fue retirado de la consola padre después del arranque.

El bootstrap:

- estuvo solo en el proceso temporal de ELSA;
- fue retirado del entorno padre antes de arrancar el agente;
- su variable PowerShell fue retirada después del bootstrap.

PC1:

```text
sin puerto público
sin port forwarding
sin firewall entrante nuevo
sin túnel
sin VPN
ELSA únicamente en loopback
```

# 11. Limpieza posterior

## 11.1 PC1

Después de la prueba:

```text
AGENT_ALIVE = False
ELSA_ALIVE = False
NODE_TOKEN_ENV = False
BOOTSTRAP_ENV = False
```

Configuración normal recuperada:

```text
NORMAL_AUTH = supabase
NORMAL_PERMISSIONS = postgres
NORMAL_ASSISTANT_MODE = local
NORMAL_RELAY = False
```

El activo `d27-test`, el administrador temporal y los permisos sintéticos estaban en memoria y desaparecieron al terminar el proceso.

Los logs D2.7 se conservaron temporalmente como evidencia operativa bajo `%LOCALAPPDATA%\ELSA\d27`.

## 11.2 Render

Render fue restaurado a:

```text
ELSA_ENV=DEV
ELSA_CORS_ORIGINS=https://elsa-relay-pilot.onrender.com
ELSA_WEB_UI_ENABLED=false
ELSA_RELAY_ENABLED=false
ELSA_ASSISTANT_EXECUTION_MODE=local
ELSA_AUTH_PROVIDER=fake
```

Se eliminaron:

```text
ELSA_RELAY_NODE_ID
ELSA_RELAY_NODE_TOKEN_SHA256
ELSA_RELAY_NODE_TOKEN_SHA256_PREVIOUS, si existía
ELSA_MATERIALS_SUPABASE_URL
ELSA_MATERIALS_API_KEY
```

Se verificó que no estuvieran configurados:

```text
ELSA_BOOTSTRAP_ADMIN_TOKEN
ELSA_DEMO_SEED
```

Estado observado:

```text
RENDER_LIVE = True
RELAY = OFF
AUTH = fake
ASSISTANT_MODE = local
NODE_ID_REMOVED = True
NODE_HASH_REMOVED = True
MATERIALS_VARS_REMOVED = True
```

Comprobación externa final:

```text
RENDER_READY_STATUS = 200
REGISTER_AFTER_CLEANUP = 404
```

Resultado:

```text
RETORNO A BASELINE SEGURO = PASS
```

# 12. Tests dirigidos D2.7-E

Se ejecutaron:

```text
tests/test_auth_supabase.py
tests/test_api_authentication.py
tests/test_api_authorization.py
tests/test_api_assistant_relay.py
tests/test_assistant_relay_end_to_end.py
tests/test_api_relay.py
tests/test_relay_protocol.py
tests/test_relay_service.py
tests/test_agent_config.py
tests/test_agent_end_to_end.py
```

Resultado:

```text
325 passed
3 warnings
34.43 s
```

Warnings observados:

1. deprecación de integración `httpx`/Starlette TestClient;
2. deprecación de alias AnyIO;
3. warning esperado de clave HMAC corta dentro de una prueba diseñada para comprobar rechazo de algoritmo/clave no segura.

No hubo fallo de test.

Resultado:

```text
TESTS DIRIGIDOS D2.7 = PASS
```

# 13. Cambios de código

D2.7 no requirió cambios funcionales.

Antes de crear la rama documental:

```text
git status --short = sin salida
branch = main
HEAD = 4a3bd66fdbc0fe2760da1e53eb6a2f4998d03ceb
origin/main = 4a3bd66fdbc0fe2760da1e53eb6a2f4998d03ceb
```

Conclusión:

```text
cambios de código = 0
migraciones = 0
cambios de esquema = 0
cambios persistentes de configuración PC1 = 0
```

El único cambio previsto para cerrar el bloque es esta documentación.

# 14. Hallazgos principales

1. No fue necesario modificar código para ejecutar una consulta remota controlada con identidad real.
2. La prohibición `fake + relay + assistant.ask` de ADR 0035 era una regla operativa/arquitectónica, no un bloqueo técnico automático de Settings.
3. D2.7 respetó esa prohibición y utilizó Supabase real.
4. Render autentica y controla abuso, pero la autorización funcional permanece en PC1.
5. PC1 aplica nuevamente JWT, perfil Materiales, cuenta ELSA y autorización de scope.
6. El sistema mantiene default deny.
7. `RequireScope` se ejecuta antes de recuperar el activo.
8. Un activo sin BOM publicado puede responder correctamente `200/published=false`.
9. Una consulta sin código de material permite evitar inventario real.
10. Supabase real puede combinarse con permisos/conocimiento ELSA en memoria.
11. El bootstrap administrativo temporal funciona con identidad real.
12. Los datos sintéticos y permisos temporales desaparecen al terminar el proceso.
13. El token del nodo está separado del proceso ELSA.
14. Para evitar que el agente heredara el bootstrap se utilizaron procesos separados en D2.7-D.
15. Render rechazó registro sin credencial con `401`.
16. Render rechazó `assistant.ask` sin JWT con `401`.
17. El agente consiguió NODE ONLINE real.
18. La primera `assistant.ask` remota real terminó con HTTP `200`.
19. La respuesta fue la esperada para un activo sintético sin BOM publicado.
20. Existe separación deliberada entre `request_id` HTTP y `relay_request_id`.
21. Render conserva el vínculo entre ambos identificadores.
22. Agente y ELSA conservan el `relay_request_id`.
23. La entrega del resultado ocurrió en el primer intento.
24. Los logs observados no expusieron credenciales sensibles.
25. PC1 nunca quedó públicamente expuesto.
26. Render y PC1 fueron restaurados al baseline seguro.
27. `register → 404` confirmó relay realmente desmontado al final.
28. Los tests dirigidos cerraron con `325 passed`.
29. No hubo modificación funcional del repositorio.

# 15. Limitaciones que siguen abiertas

D2.7 no acredita todavía:

- acceso real desde un PC PAPELSA;
- experiencia completa de usuario final;
- mecanismo definitivo de login;
- refresh token/sesión de largo plazo;
- operación multiusuario;
- despliegue productivo;
- alta disponibilidad del relay;
- múltiples workers/instancias;
- tolerancia de carga;
- SLA de latencia;
- BOM real;
- inventario SAP real;
- Materiales SAP mediante consulta remota;
- modelo local/Phi dentro de esta prueba;
- continuidad funcional ante reinicio de PC1 durante una consulta;
- seguridad productiva completa de Render;
- cierre del frente PAPELSA.

Estos puntos deben tratarse en bloques posteriores y no se consideran implícitamente validados por D2.7.

# 16. Criterios de aceptación D2.7

| Criterio | Resultado |
|---|---|
| Identidad real Supabase | PASS |
| Fake excluido de la consulta real | PASS |
| Default deny comprobado | PASS |
| Autorización mantenida en PC1 | PASS |
| Activo sintético aislado | PASS |
| Sin BOM real | PASS |
| Sin consulta SAP/inventario real | PASS |
| ELSA solo loopback | PASS |
| Token del nodo efímero | PASS |
| Bootstrap efímero | PASS |
| NODE ONLINE | PASS |
| `assistant.ask` remota real | PASS |
| Respuesta HTTP 200 | PASS |
| `published=false` esperado | PASS |
| Correlación HTTP ↔ relay ↔ PC1 | PASS |
| Sin exposición pública de PC1 | PASS |
| Limpieza PC1 | PASS |
| Limpieza Render | PASS |
| Relay final OFF / register 404 | PASS |
| Tests dirigidos | 325 PASS |
| Cambios funcionales requeridos | NO |

# 17. Estado final técnico

D2.7 demostró físicamente por primera vez:

```text
cliente autenticado
→ Render público
→ autenticación JWT real
→ relay
→ agente PC1 outbound-only
→ ELSA local
→ autorización real en PC1
→ activo sintético
→ respuesta 200
→ retorno por relay
→ cliente
```

Sin:

```text
fake identity para assistant.ask
datos SAP reales
BOM real
inventario real
puerto público PC1
port forwarding
firewall entrante nuevo
túnel
VPN
persistencia del token del nodo
persistencia del JWT
cambio de código funcional
```

# 18. Cierre formal

La validación técnica y física de D2.7 está completa.

Las condiciones de cierre formal verificadas fueron:

1. versionar este documento;
2. ejecutar revisión/CI de la rama;
3. crear PR documental;
4. aprobar y mergear el PR;
5. comprobar CI de `main`;
6. comprobar repositorio final limpio y alineado con `origin/main`.

Evidencia final: PR #56 fusionado; CI del cierre = PASS (4 checks); merge commit = 4c5ed3198d05f97024f360f56927af3f52844f11; main local sincronizado con origin/main y working tree limpio. Estado final:

```text
D2.7 — CERRADO FORMALMENTE
PR #56 — MERGED — CI PASS
```
