# D2 — Acceso remoto seguro a ELSA: auditoría, arquitectura híbrida y diseño del transporte

**Estado:** auditoría + decisión de arquitectura formalizada + **diseño** del
transporte. El contrato lógico V1 está en [ADR 0030](adr/0030-protocolo-relay-render-pc1-v1.md) (D2.1);
los nombres de mensajes y campos de §7.3 son conceptuales y **prevalece el ADR 0030**. **No es un cierre.** No se implementó nada, no se instaló software, no
se abrió ningún puerto y no se tocó ninguna configuración de Windows, red, router,
Render o Supabase.

- Repositorio: `Elsa-ai`, rama `claude/d2-secure-remote-access`, desde `main` en `cc924f4`.
- Fecha: 2026-10-04.
- Nombre de bloque: el repositorio no define un identificador formal para D2
  (el cierre 5.0 §21 lo llama «Acceso remoto seguro a ELSA»); aquí se usa «D2».
- Decisión vigente: [ADR 0029](adr/0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md).

> **Resumen en cuatro líneas**
> - **HISTÓRICO:** Render = demo sintética HTTPS (`76462ed`, `3d643b2`).
> - **OBJETIVO ACTUAL APROBADO:** PC PAPELSA → Render → PC1.
> - **TRANSPORTE Render ↔ PC1:** pendiente de decisión final; este documento lo diseña y
>   recomienda (§7), sin implementarlo.
> - **D2 no necesita redecidir la arquitectura completa:** necesita diseñar e implementar el
>   enlace seguro Render ↔ PC1.

## 1. Objetivo

PC1 encendido (en casa) con ELSA y la IA local ejecutándose, y un ingeniero en PAPELSA
(otra red, solo navegador) que abre ELSA por HTTPS, se autentica y consulta inventario
real de Materiales. Un puerto abierto que responde **no** es éxito: se exige acceso +
cifrado + autenticación + consulta E2E real desde red externa, sin exponer PC1.

## 2. Evolución de arquitectura

Esta sección existe para no falsear el historial.

| Momento | Qué dice el repositorio | Fuente |
|---|---|---|
| 2026-09-07/08 | Render se crea **para una demo sintética HTTPS**: servicio único, DEV, datos en memoria, sin Supabase ni secretos. Motivo: el micrófono exige HTTPS. | `76462ed`, `3d643b2`, `render.yaml`, `docs/demo-runbook.md` |
| 2026-09-13 | El runtime local (Phi-4-mini + llama.cpp) se conecta tras el puerto LLM. Solo loopback; la excepción remota se **elimina**. «El backend sigue desplegándose en Render, donde no hay ni GPU ni pesos». | ADR 0018, `969ddbe`, `e9931b2`, `0c6a87f` |
| 2026-09/10 | Cierre de ELSA–Materiales V1. D2 queda como siguiente bloque con el mecanismo **abierto** («red privada o VPN preferible a exponer PC1»). Render figura como «despliega solo la interfaz». | cierre 5.0 §21, `HANDOVER_AND_CONTINUITY_MAP.md` |
| 2026-10-04 (auditoría D2 inicial) | Compara VPN, Tailscale, Cloudflare Tunnel, etc. **como si la arquitectura no estuviera decidida**, y recomienda un túnel de terceros. | commit `558407d` |
| 2026-10-04 (auditoría de continuidad) | Se busca en código, Git, ADR y traspaso un diseño PAPELSA → Render → PC1: **no existe evidencia versionada** de relay, WebSocket, polling, túnel, worker o agente. `MECANISMO DE TRANSPORTE = NO DEFINIDO / NO RECUPERADO`. | esta auditoría |
| 2026-10-04 (decisión del responsable) | El proyecto decide la arquitectura híbrida: **Render es el extremo público; PC1 conserva la ejecución local**. | [ADR 0029](adr/0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md) |

**Formulación correcta de la transición:** Render nació como plataforma de demo
sintética. Posteriormente el proyecto decidió evolucionar hacia una arquitectura híbrida
en la que Render es el extremo público y PC1 conserva la ejecución local. **Esa
evolución no había quedado formalizada en el repositorio; D2 la formaliza ahora.**
No debe leerse que el repositorio «siempre» definió Render como relay: no lo hizo.

**Qué estuvo mal en la auditoría inicial (558407d):** reabrió la elección de arquitectura
(túnel de terceros frente a otras) en lugar de partir de la decisión del responsable de
usar Render como extremo público. Además omitió citar que el cierre V1 ya fijaba la
preferencia «red privada o VPN». Sus **hallazgos técnicos** (§4) siguen siendo válidos;
su **recomendación arquitectónica** queda superada y se conserva solo como histórico (§14).

## 3. Arquitectura objetivo y responsabilidades

```text
PC PAPELSA ── navegador (solo), HTTPS 443 ──▶ RENDER  (extremo público)
                                                │  sirve UI same-origin, valida forma,
                                                │  encola/encamina, declara ONLINE/OFFLINE
                                                │
                  conexión SALIENTE iniciada por PC1 (sin puerto entrante)
                                                │
                                                ▼
                                            PC1 (casa)
                                              agente de nodo ─ HTTP loopback ─▶ ELSA (127.0.0.1)
                                                                                  ├─ verifica JWT de Materiales
                                                                                  ├─ permisos propios de ELSA
                                                                                  ├─ llama.cpp / Phi (127.0.0.1)
                                                                                  └─ Materiales (HTTPS saliente)
```

| Componente | Responsabilidad | NO es |
|---|---|---|
| **Render** | Servir la interfaz; recibir HTTPS; saber si el nodo está online; encaminar solicitudes permitidas; devolver respuestas; mostrar «ELSA local no disponible» | Motor de IA; host de Phi/llama.cpp; fuente de conocimiento; copia de SAP/Materiales; decisor de permisos; almacén de secretos de PC1 |
| **PC1** | ELSA, IA local, modelo, conocimiento local, integraciones locales, Materiales | Servidor con puerto público |
| **Agente de nodo (nuevo, en PC1)** | Mantener la conexión saliente a Render; recoger solicitudes; reenviarlas a ELSA por loopback; devolver la respuesta | Parte de ELSA; decisor de permisos |
| **Navegador PAPELSA** | Interfaz same-origin con Render | Conoce IP/URL de PC1, del modelo o credenciales del nodo |

Invariantes (ADR 0029 §5): IA y modelo en PC1; sin puerto 8000 público; sin port
forwarding; sin firewall abierto a Internet; sin `service_role`; sin TI de PAPELSA como
dependencia; el modelo local no se expone a Render.

## 4. Estado actual (hallazgos de la auditoría)

### 4.1 Cómo se sirve ELSA

| Aspecto | Hallazgo | Fuente |
|---|---|---|
| Entrypoint | `elsa.main:create_app` (patrón factory), ASGI con Uvicorn | `src/elsa/main.py` |
| Comando documentado | `uv run uvicorn elsa.main:create_app --factory --host 127.0.0.1 --port 8000` | cierre 5.0 §, `docs/demo-runbook.md` |
| Host/puerto | No hay configuración propia: los fija quien lanza Uvicorn por CLI. Default de Uvicorn y de los runbooks: `127.0.0.1:8000` | — |
| Modo producción / `reload` | No existe script de producción. `--reload` solo aparece en el arranque de desarrollo | `README.md`, `docs/development.md` |
| UI | `StaticFiles` en `/app` (y `/brand`); `/` redirige a `/app/`. Sin build | `src/elsa/web.py` |
| Health | `/api/v1/health/live` (sin dependencias) y `/health/ready` (200 `ok`/`degraded`, 503 si una dependencia crítica cae). Ambos **públicos** | `src/elsa/api/v1/health.py` |
| Docs/OpenAPI | Solo en `ELSA_ENV=DEV` (`/docs`, `/openapi.json`); desactivados en TEST | `main.py:74-82` |
| Errores | Formato estándar, sin trazas, con `request_id` | `docs/security.md` |
| Logs | JSON; la línea de acceso lleva método, ruta, estado y duración; nunca cabeceras, query ni cuerpos | `src/elsa/logging.py` |

### 4.2 Seguridad web

| Control | Estado |
|---|---|
| `CORSMiddleware` | Presente. Orígenes explícitos por `ELSA_CORS_ORIGINS`, comodín rechazado al arrancar; métodos y cabeceras en lista cerrada |
| `TrustedHostMiddleware` | **Ausente.** Cualquier cabecera `Host` es aceptada |
| `HTTPSRedirectMiddleware` | Ausente (correcto si TLS termina en un proxy/túnel) |
| Cabeceras `X-Forwarded-*` | ELSA no las lee. Uvicorn sí, por defecto solo desde `127.0.0.1` (`--forwarded-allow-ips`). `render.yaml` usa `'*'`, válido **solo** porque allí únicamente llega el proxy de Render; **no debe copiarse a PC1** |
| Decisiones por IP | Ninguna: el control de abuso cuenta por usuario autenticado. Falsificar `X-Forwarded-For` no da ventaja |
| Cookies | No se usan. Sin riesgo CSRF clásico: la auth es por cabecera `Authorization` |
| Cabeceras de seguridad (HSTS, CSP, `X-Frame-Options`, `nosniff`) | **Ausentes.** Con TLS externo, HSTS y una CSP serían deseables |
| `/health/*` | Públicos por diseño (sin datos sensibles; `ready` revela estado de dependencias) |

**Qué pasa si ELSA deja de escucharse solo en `127.0.0.1`:** Uvicorn
sirve HTTP en claro a cualquier host que alcance el puerto; no hay `TrustedHost`; la UI
estática y `/health` son anónimos; la API exige JWT válido (la auth se verifica contra el
JWKS de Materiales, no se puede evitar). El riesgo real no es un bypass de la API sino:
(a) JWT en claro sobre HTTP, (b) superficie anónima expuesta (UI, health, y el endpoint de
bootstrap, protegido por JWT + token), (c) el micrófono exige contexto seguro (HTTPS)
fuera de `localhost`. Por eso `0.0.0.0` está descartado.

### 4.3 Autenticación y login

Verificado en el código actual (`web/js/screens/login.js`, `web/js/api.js`):

- El login en identidad real **es pegar un JWT** en un campo `password`. No hay formulario
  de correo/contraseña, ni refresh, ni enlace de sesión con Materiales.
- El token se guarda en `sessionStorage` (clave `elsa.token`): sobrevive a recargas de la
  pestaña, se pierde al cerrarla. No va en URL ni en cookies; viaja solo en
  `Authorization: Bearer`.
- Vida del token: ~1 h (cierre 5.0 §20). Al expirar el backend responde 401 y el
  usuario tiene que volver a pegar uno nuevo. No existe renovación.
- Hoy ese JWT solo se obtiene por una vía técnica (script en PC1 con correo y contraseña).
- Los logs no registran el token (política y `tests/test_security_logging.py`).

**Veredicto de login: REQUIERE SUBBLOQUE DE LOGIN.** Pegar en PAPELSA un JWT generado
en PC1 contradice el requisito de D2 (§19 del encargo). El transporte puede ser viable
sin esto, pero la **operación real** no.

### 4.4 PC1 (solo lectura)

| Elemento | Resultado |
|---|---|
| Red activa | Sí. Una interfaz Ethernet, IPv4 privada presente, gateway presente |
| Perfil de red | **Public** (el más restrictivo de Windows) |
| Firewall | Los tres perfiles **activos**; acciones inbound/outbound por defecto: `NotConfigured` (= valores de Windows: inbound bloqueado, outbound permitido) |
| Puerto 8000 / 8080 | Libres ahora (ELSA y llama-server no están en ejecución) |
| Escuchando en red | Solo servicios estándar de Windows (135, 139, 445, 5040, 7680, RPC dinámicos), más `8032` y un proceso `dispatcher` en `30950` **no identificados** (ver §13) |
| RDP | Denegado (`fDenyTSConnections=1`), `TermService` detenido |
| OpenSSH | Solo el **cliente** (`ssh.exe`); `sshd` ausente; `ssh-agent` deshabilitado |
| Docker | Docker Desktop **instalado** (v28.5.2); servicio detenido; arranca con la sesión |
| Tailscale, cloudflared, ngrok, ZeroTier, WireGuard, OpenVPN, nginx, Caddy, IIS | **Ausentes** (no detectados en PATH, programas instalados ni servicios; IIS/WSL «no determinado» sin admin) |
| VPN corporativa | No detectada (`RemoteAccess` deshabilitado) |
| `uv` | Presente. `gh`: ausente |
| Arranque de ELSA | **Manual**, en una terminal abierta. No hay servicio, tarea programada ni entrada de inicio de ELSA. Las tareas/entradas de inicio existentes son ajenas (OneDrive, Steam, Docker Desktop, etc.) |
| Energía | Plan «Economizador»; suspensión en **corriente alterna = nunca** (0 s), en batería 600 s. PC de escritorio: no se suspende enchufado |
| Reinicio | ELSA **no vuelve solo**; tras reiniciar hay que arrancar a mano (y, si se usa, `llama-server`) |
| Materiales/Supabase tras arranque | Son servicios externos HTTPS; no dependen de PC1. El proyecto Supabase de ELSA **se pausó** una vez (cierre 5.0 §13, incidente 3): también es un punto de fallo operativo |

Conclusión: **ninguna herramienta de acceso remoto existente y aprobada** en PC1 sirve
para D2. Todo mecanismo viable requiere instalar algo o crear cuenta externa.

## 5. Restricciones aplicables

Sin instalar aplicaciones externas (cloudflared, Tailscale, ngrok, ZeroTier, WireGuard,
OpenVPN); sin tocar firewall, router, NAT, DNS, servicios de Windows, tareas
programadas ni certificados; sin exponer Uvicorn; Materiales y su adaptador intactos;
sin migraciones ni Supabase. Posiblemente el PC de PAPELSA tiene restricciones de TI: no
se asume que permita VPN, software nuevo, puertos no estándar ni WebSockets, y por eso
se prefiere HTTPS estándar al puerto 443. **Las librerías Python son potencialmente
autorizables, pero deben quedar justificadas** (§8.3).


## 6. Modelo de amenazas

> **Nota de lectura.** Esta tabla es de la auditoría inicial y se redactó pensando en un
> túnel de terceros con capa de acceso. Se conserva porque el análisis de superficie
> (JWT, HTTP en claro, `Host`, `X-Forwarded-*`, `/docs`, DEV) **sigue siendo válido** para
> Render y para ELSA en PC1. Las filas que mencionan «capa de acceso», «agente de túnel»
> o «cuenta externa» deben leerse ahora como: **Render** (extremo público), **agente de
> nodo** (PC1) y **cuenta de Render/GitHub**. Las amenazas propias del relay están en §7.12.

Prob. = probabilidad aproximada; Imp. = impacto. «Bloq.» = debe resolverse antes de abrir acceso.


| # | Amenaza | Prob. | Imp. | Mitigación necesaria | Bloq. |
|---|---|---|---|---|---|
| 1 | Acceso anónimo a la UI | Alta si hay URL pública | Bajo (estática, sin datos) | Poner la UI detrás de una capa de acceso previa (Access/VPN) | Sí |
| 2 | Acceso anónimo a la API | Alta (escaneo) | Medio: JWT obligatorio, 401 sin él | Mantener auth; capa previa que filtre; rate limit existente | Sí |
| 3 | Interceptación del JWT | Media en HTTP | Alto (1 h de acceso) | Solo TLS; nunca HTTP; HSTS | Sí |
| 4 | HTTP sin cifrar | Alta si se usa `0.0.0.0` | Alto | Bind a loopback; TLS en el canal | Sí |
| 5 | Puerto 8000 expuesto | Alta con port-forward | Alto | No abrir; salida solo (outbound) | Sí |
| 6 | Fuerza bruta | Media | Medio: la contraseña vive en Supabase Auth (de Materiales), no en ELSA | Límites de Supabase + capa previa | No |
| 7 | Reutilización de token robado | Baja-media | Alto | TLS, vida corta (1 h), logout que limpia, sin token en URL/logs | Sí |
| 8 | Logs con `Authorization` | Baja | Alto | Ya mitigado en ELSA. **Verificar los logs del agente de túnel/proxy** | Sí (verificar) |
| 9 | URL pública indexable | Media | Bajo-medio | Capa de acceso previa; `X-Robots-Tag: noindex`; URL no listada | No |
| 10 | CORS incorrecto | Baja | Medio | Origen exacto de la URL publicada en `ELSA_CORS_ORIGINS`; UI y API son mismo origen | Sí |
| 11 | Ataques por cabecera `Host` | Baja | Bajo-medio | Añadir `TrustedHostMiddleware` con hosts declarados | No (recomendado) |
| 12 | `X-Forwarded-*` falsificadas | Baja | Bajo (ELSA no decide por IP) | Mantener `--forwarded-allow-ips` al default `127.0.0.1`; nunca `*` en PC1 | Sí |
| 13 | Exposición de `/docs` | Baja | Bajo | Ya cerrado fuera de DEV. **Atención:** PC1 corre en DEV hoy → ver §13 | Sí |
| 14 | PC1 perdido/apagado | Media | Disponibilidad | Fallo cerrado (no hay ruta alternativa); runbook | No |
| 15 | Reinicio inesperado | Alta | Disponibilidad | Documentar; arranque automático solo con autorización posterior | No |
| 16 | Cambio de IP | Media | Disponibilidad | Irrelevante con salida-primero (outbound) o overlay | No |
| 17 | CGNAT/NAT | Desconocida | Bloquea port-forward | Salida-primero (túnel saliente) o overlay evitan el problema | No |
| 18 | Bloqueo de red corporativa | Media-alta | Bloquea el uso | Probar antes de invertir; preferir HTTPS 443 estándar | Sí |
| 19 | Dependencia de proveedor | Cierta | Disponibilidad y confianza | Aceptarla explícitamente; plan B | No |
| 20 | Compromiso de la cuenta externa | Baja | **Alto**: un tercero podría redirigir o abrir el túnel | 2FA en esa cuenta; mínimos privilegios; revocación documentada | Sí |

Riesgo adicional (**nuevo, alto**): ELSA hoy corre en `ELSA_ENV=DEV`
con posibles adaptadores fake (`docs/demo-runbook.md`: «identidades fake y cualquiera que llegue
al puerto entra como quien quiera»). Exponer **jamás** puede hacerse con `auth_provider=fake`,
ni `DEV` con `/docs` abierto. Para D2 hay que correr con `ELSA_ENV=TEST` (la config lo obliga a
`supabase`, `postgres` y storage `local`) o añadir un ambiente adecuado (ver §13).

## 7. Diseño del transporte Render ↔ PC1 (nada implementado)

Se comparan **mecanismos** dentro de la arquitectura ya aprobada, no arquitecturas. Todo
mecanismo debe cumplir: **PC1 inicia las conexiones**; sin conexión entrante a la IP
doméstica, port forwarding, IP fija, firewall inbound, DMZ ni UPnP; sin servicio externo
adicional salvo que sea indispensable.

### 7.1 Alternativas de transporte

| | A. Conexión persistente saliente (WebSocket) | B. Polling corto autenticado | C. **Long polling** autenticado | D. SSE saliente + POST de respuesta | E. Render → PC1 por HTTP directo |
|---|---|---|---|---|---|
| Quién inicia | PC1 | PC1 | PC1 | PC1 | **Render** |
| Entrante a casa | No | No | No | No | **Sí** → **RECHAZADA** |
| Latencia de entrega | Mínima (push) | Hasta el intervalo (p. ej. 1–3 s) | Mínima (la espera se libera al encolar) | Mínima | — |
| Carga/tráfico ocioso | 1 conexión | Alto (peticiones vacías constantes) | Bajo (1 petición por ventana de espera) | 1 conexión | — |
| Dependencia Python nueva | **Sí** (`websockets` o similar; **no está** en `pyproject.toml` ni en `uv.lock`) | No (`httpx` ya es dependencia) | **No** | No (`httpx` soporta streaming) | — |
| Encaje con proxy de Render / red corporativa | Requiere que el proxy admita *upgrade*; ruta de menor certeza | HTTPS normal | HTTPS normal; depende de la duración máxima de la petición (**NO VERIFICADO**) | HTTPS normal; riesgo de *buffering* intermedio | — |
| Reconexión/estado | Hay que gestionar *ping/pong*, caídas silenciosas | Trivial, sin conexión viva | Simple: cada petición es un latido | Moderada | — |
| Pruebas | Más complejas (servidor WS de test) | Muy simples | Simples (`TestClient`/`httpx.ASGITransport`) | Moderadas | — |
| Streaming futuro de respuestas | Natural | No | Limitado (por bloques) | Natural | — |
| Veredicto | Viable; **descartable en el primer incremento** por la dependencia nueva y el menor determinismo | Viable pero ineficiente | **RECOMENDADO** | Viable; no aporta frente a C hoy | **RECHAZADA** |

**Mecanismos ya presentes en la plataforma:** no hay evidencia en el repositorio de ningún
canal Render ↔ PC1 existente (la auditoría de continuidad no lo encontró), por lo que
no hay un «mecanismo soportado ya» que reutilizar. Lo único reutilizable es el
cliente/servidor HTTP del proyecto (`httpx`, FastAPI) y el patrón de CLI de
`src/elsa/tools/`.

### 7.2 Recomendación: long polling saliente PC1 → Render (opción C)

Un agente en PC1 hace `POST` a Render y la petición **se mantiene abierta** hasta que hay
trabajo para el nodo o vence la ventana de espera; entonces responde y el agente vuelve a
preguntar. Las respuestas se devuelven con un `POST` aparte.

Por qué C:
1. **Sin dependencia nueva** (`httpx` ya es dependencia de runtime).
2. **Solo HTTPS saliente al 443 normal**: el modelo menos frágil ante redes y proxies; no
   asume WebSockets (el PC de PAPELSA ni siquiera participa en este tramo).
3. **Cada petición es un latido**: el estado ONLINE/OFFLINE sale gratis del propio
   protocolo, sin un canal de control aparte.
4. **El agente reenvía a ELSA por loopback sin tocar ELSA.** ELSA sigue sin saber que existe
   un relay; no se añade lógica de negocio al agente (regla 3, ADR 0002).
5. Es **testeable** sin red real.
6. El protocolo se define independiente del transporte (§7.3): si D2.7 muestra que C no
   cabe en Render, se puede sustituir por A **sin tocar el contrato**.

**Lo que NO está verificado y se mide en D2.7 antes de fijar números:** el máximo de duración
de una petición y el tiempo de inactividad que tolera el proxy de Render; si en el plan
Free una petición abierta mantiene despierto el servicio; y si las ~744 h/mes de una
instancia siempre activa caben en el plan. Hasta medirlo, **no se declara viable el plan
Free**; la salida alternativa es un plan de pago (decisión del responsable).

> Esta recomendación es un **diseño**. Fijar el protocolo exige un ADR propio (ADR 0030 en
> D2.1) y la regla 20 exige autorización explícita para empezar a implementar.

### 7.3 Protocolo lógico (nombres conceptuales)

| Mensaje | Dirección | Mapeo sobre long polling | Contenido |
|---|---|---|---|
| **REGISTER** | PC1 → Render | `POST` de registro | `node_id` y `node_session_id` (el «epoch» de este documento) nuevo generado por el nodo; **sin versión del agente ni otros datos** (ADR 0030). Los parámetros de la respuesta de Render son transporte |
| **HEARTBEAT** | PC1 → Render | implícito en cada espera; opcional `POST` explícito si el nodo está ocupado | `node_id`, `epoch`, indicadores mínimos (p. ej. «ELSA local responde», «LLM degradado: sí/no») |
| **REQUEST** | Render → PC1 | cuerpo de la respuesta a la espera | sobre de solicitud (abajo) |
| **RESPONSE** | PC1 → Render | `POST` por `request_id` | `request_id`, `epoch`, estado HTTP, cabeceras permitidas, cuerpo |
| **ERROR** | PC1 → Render | `RESPONSE` con tipo de fallo | `request_id`, `code` (`ErrorCode` cerrado de ADR 0030: p. ej. `LOCAL_ERROR`, `FORBIDDEN`, `TIMEOUT`, `DUPLICATE_REQUEST`), `detail` acotado y sin trazas |
| **CANCEL** | Render → PC1 | lista en la respuesta a la espera | `request_id` cancelados (el navegador se fue o venció el plazo) |

**Sobre de solicitud (REQUEST):** `request_id` (UUID generado por Render) · `created_at` ·
`deadline` (instante absoluto) · `op` = método + ruta (de una **lista cerrada**) ·
cabeceras permitidas (`Authorization`, `Content-Type`) · cuerpo acotado · `state`.

**Estados:**

```text
queued ──▶ dispatched ──▶ running ──▶ completed
   │            │             │  └──▶ failed
   └────────────┴─────────────┴─────▶ expired      (+ cancelled, terminal)
```

`queued` y `expired` los fija Render; `dispatched` cuando se entrega al nodo; `running` **no es
observable en el cable en V1** (no hay ACK; ver ADR 0030 §12); `completed`/`failed` según su RESPONSE. **Todo en memoria**; no hay persistencia en el
piloto (§8.5).

### 7.4 Identidad del nodo y autenticación Render ↔ PC1

Es un problema **distinto** del JWT del usuario.

- **Identidad:** `node_id` fijo y declarado por configuración (no deducido). Una sola
  sesión activa por `node_id`; un `REGISTER` nuevo sustituye al anterior (por `epoch`).
- **Credencial del nodo:** un secreto aleatorio de ≥256 bits, generado por el operador
  **fuera de Git** y guardado solo en el `.env` de PC1. Render guarda **solo su hash SHA-256**
  como variable de entorno del panel (no en el repositorio).
- **Verificación:** hash del secreto presentado + `hmac.compare_digest`; **default deny**
  (sin hash configurado, los endpoints de nodo no existen/responden 404).
- **Transporte:** cabecera `Authorization: Bearer` **solo** en las rutas de nodo; nunca en URL ni en
  cuerpo; solo TLS.
- **Rotación:** Render admite dos hashes a la vez (actual y siguiente); se rota
  añadiendo el siguiente, cambiando el secreto en PC1 y retirando el anterior.
- **Revocación:** quitar el hash en Render. El agente recibe 401/403 y deja de insistir
  (espera larga con registro del error, **sin imprimir el secreto**).
- **Límites de abuso:** intentos fallidos limitados por origen; respuestas uniformes.
- **No se usa** `service_role`, ni el JWT del usuario como identidad del nodo.
- **Riesgo residual aceptado:** quien controle la cuenta de Render (o la de GitHub vinculada)
  puede sustituir el hash y suplantar al nodo, y de todos modos ve el tráfico (ADR 0029,
  consecuencia 6). Mitigación: 2FA en ambas cuentas y JWT de vida corta.

### 7.5 JWT del usuario

Se **preserva** la autenticación de ELSA: el navegador envía `Authorization: Bearer` a Render; el
agente lo reenvía a ELSA por loopback; **ELSA lo valida como hoy** (JWKS de Materiales, ADR 0005).
Render **no** decide permisos.

- Solo viaja en la cabecera; nunca en query string.
- En Render vive **en memoria**, dentro de la solicitud en cola, y se descarta al despacharla o al
  llegar a un estado terminal.
- En PC1 vive en memoria durante la llamada local; **no se escribe a disco** ni en logs.
- **Logging de Render y del agente:** `request_id`, plantilla de ruta, estado, duración, estado del
  nodo. **Nunca** cabeceras, query ni cuerpos (igual que `src/elsa/logging.py`).
- Render solo exige, como filtro barato, que una ruta de API traiga `Authorization: Bearer`
  sintácticamente presente; **no** valida el token.

Alternativas descritas, **no adoptadas**: (i) que Render valide el JWT y envíe una aserción firmada
(mueve una decisión de seguridad a Render y contradice ADR 0002/regla 5); (ii) un *ticket* de un solo
uso emitido por PC1 y ligado a la solicitud (endurecimiento futuro, exige rediseñar el login);
(iii) cifrado extremo a extremo navegador ↔ PC1 con Render ciego (exige gestión de claves en
navegador; fuera del piloto).

### 7.6 Qué datos viajan

Principio: **Render transporta el mínimo necesario.**

| Dirección | Permitido | Prohibido | Retención | Log permitido |
|---|---|---|---|---|
| **PAPELSA → Render** | Archivos estáticos de la UI; solicitudes de API de la **lista cerrada**, con `Authorization` y JSON acotado | Subida de audio/archivos y rutas de administración o ingesta en las primeras fases; `X-Bootstrap-Token`; cuerpos sobre el tope | Solo mientras vive la solicitud, en memoria | Método, plantilla de ruta, estado, duración, `request_id`, estado ONLINE/OFFLINE |
| **Render → PC1** | Sobre de §7.3 | Cualquier dato que no proceda de la solicitud del usuario; órdenes iniciadas por Render | Ninguna (el agente lo descarta al terminar) | `request_id`, ruta, estado, duración |
| **PC1 → Render** | Estado HTTP, tipo de contenido y cuerpo JSON de ELSA (ya autorizado); indicadores mínimos de salud | Archivos SAP/BOM crudos, rutas de modelo, trazas, secretos, datos del host | Ninguna | `request_id`, estado, duración |
| **Render → PAPELSA** | Respuesta de ELSA o error en el formato estándar con `request_id` | Detalles del nodo, IP, versiones internas, trazas | Ninguna | Igual que la fila de entrada |

**Lista cerrada inicial de rutas** (a fijar en D2.1 contra el OpenAPI real): sesión/contexto, `me`,
asistente (`ask`, `understanding`), lectura de activos, salud. **Excluidas al inicio:**
administración y `bootstrap`, ingesta (`engineering-bom`, `sap-snapshots`, `reconciliations`),
revisión y publicación, y los aportes con audio.

### 7.7 PC1 fuera de línea (caso de primera clase)

| Situación | Comportamiento de Render |
|---|---|
| Nodo OFFLINE (sin latido dentro del TTL) | Responde **de inmediato** 503 con código `ELSA_LOCAL_UNAVAILABLE` y mensaje «ELSA local no disponible». **No encola** |
| Nodo ONLINE pero no recoge la solicitud a tiempo | Vence la espera de cola → error `ELSA_LOCAL_BUSY`; la solicitud pasa a `expired` |
| Nodo recogió pero no responde a tiempo | `expired` → `ELSA_LOCAL_TIMEOUT` |
| Error de ELSA local | Se devuelve tal cual (formato estándar), o `ELSA_LOCAL_ERROR` si ELSA no respondió |
| ELSA local arriba, **LLM** apagado | Lo declara ELSA como hoy (`degraded`, regla 9); no es asunto de Render |

**Nunca:** esperar indefinidamente, inventar respuesta, usar IA en la nube, ni consultar
Materiales «en sustitución» de PC1. La UI muestra un estado visible y puede consultar un
`status` mínimo (online/offline).

### 7.8 Reconexión

- El agente repite ciclo `REGISTER → espera → responder`.
- Ante error de red o 5xx: **backoff exponencial con *jitter***, tope de decenas de segundos
  (criterio: inicio ~1 s, factor 2, tope ~30–60 s) y re-`REGISTER` con un `epoch` nuevo.
- Ante 401/403: no martillear; espera larga y error visible en el log del agente.
- Un `REGISTER` nuevo marca como `failed (NODE_RESET)` lo que seguía `dispatched/running` del
  `epoch` anterior: **semántica *at-most-once***, sin reenvío automático.
- Una respuesta tardía de un `epoch` caducado se rechaza (409) y se descarta.
- Si Render se reinicia (despliegue o suspensión del plan Free) pierde su memoria: el agente
  recibe «sesión desconocida», se re-registra, y las solicitudes en vuelo fallan con error
  claro; el usuario reintenta. **Aceptable** porque las solicitudes viven segundos.

### 7.9 Idempotencia

- `request_id` único generado por Render.
- Render **despacha cada solicitud como máximo una vez**; tras `dispatched` nunca la reenvía.
- El agente guarda en memoria un conjunto acotado de `request_id` vistos (TTL ≥ plazo máximo +
  margen) y rechaza duplicados (`duplicate`).
- `RESPONSE` es idempotente por `request_id` (la primera gana).
- Un reintento del usuario crea un `request_id` nuevo (nivel usuario). Una *Idempotency-Key* de
  cliente queda fuera del piloto.

### 7.10 Timeouts (distintos; sin valores finales inventados)

Regla: **cada plazo interno es estrictamente menor que el que lo contiene.**

| Plazo | Dónde | Criterio / rango propuesto | Evidencia |
|---|---|---|---|
| Navegador → Render | UI | Algo mayor que el plazo del relay, para que el error lo dé el relay y no el navegador | A decidir en D2.4 |
| Espera en cola (recogida) | Render | Corta (**~3–10 s**): si el nodo está ONLINE debería recoger casi al instante | Criterio |
| Ventana del *long poll* | Render/agente | Menor que el límite de inactividad del proxy (**~20–30 s**) | **NO VERIFICADO** (medir en D2.7) |
| TTL ONLINE | Render | ventana + margen (**~35–45 s**) | Criterio |
| Plazo total de solicitud (`deadline`) | Render | ≥ peor caso de ELSA, sujeto al máximo de petición de Render | `llm_timeout_seconds=120.0` en `config.py:264`; límite de Render **NO VERIFICADO** |
| Agente → ELSA (loopback) | PC1 | `deadline` − margen de tránsito | Criterio |
| ELSA ↔ LLM | PC1 | Ya existe: 120 s | `config.py:264` |
| ELSA ↔ Materiales | PC1 | Ya existe: 8 s (auth 5 s) | `config.py:155,161` |

El agente debe **seguir esperando trabajo mientras ejecuta** una solicitud larga (tareas
concurrentes), con un tope de solicitudes simultáneas bajo (1–2): PC1 tiene 4 GB de VRAM.

### 7.11 Cancelación

Si el navegador se desconecta o vence el plazo, Render marca `cancelled`/`expired` y lo
anuncia en la siguiente espera; el agente cancela su llamada local. Es **mejor esfuerzo**:
ELSA puede haber terminado ya.

### 7.12 Amenazas propias del relay

| Amenaza | Mitigación |
|---|---|
| Inundar la cola con solicitudes anónimas | Cola y cuerpos acotados; exigir `Authorization` presente; límite por origen (mejor esfuerzo: la IP la ve el proxy de Render) y respuestas 429/503 |
| Suplantar al nodo | Credencial de nodo (§7.4); sesión única; `epoch`; TLS |
| Reproducir una solicitud | `request_id` + at-most-once + plazo |
| Fuga del secreto del nodo | Fuera de Git/URL/logs; solo hash en Render; rotación y revocación |
| El agente usado como proxy (SSRF/abuso de rutas) | Solo base **loopback configurada** + lista cerrada de método/ruta; sin URLs absolutas, sin `..`, **sin seguir redirecciones**, `trust_env=False` (mismo criterio que `LlamaCppAdapter`) |
| Inyección por cabeceras | Lista cerrada de cabeceras reenviadas |
| Crecimiento de memoria | Topes de cola, cuerpo y número de solicitudes vivas; limpieza al estado terminal |
| Cuenta de Render o GitHub comprometida | 2FA; mínimos privilegios; revocación documentada (riesgo aceptado en ADR 0029) |
| `X-Forwarded-*` en Render | `--forwarded-allow-ips '*'` solo es válido en Render; **nunca** en PC1 |

## 8. Impacto de la implementación

### 8.1 Render

| Pregunta | Respuesta |
|---|---|
| ¿Modificar la app existente (`elsa.main`)? | **No.** La demo se conserva intacta |
| ¿Endpoints nuevos? | Sí, en una app **nueva**: rutas de nodo (registro, espera, respuesta), `status`, y *passthrough* de la API de lista cerrada |
| ¿Segundo servicio Render? | **Sí, recomendado:** `elsa-relay` junto a `elsa-demo`. La demo tiene otra naturaleza (DEV, datos sintéticos) y `tests/test_render_blueprint.py` fija «un único servicio», por lo que ese test cambiaría |
| ¿Cambiar `render.yaml`? | Sí: añadir el servicio, con **una sola instancia** (el estado del relay vive en memoria; escalar a varias lo rompería) |
| ¿Almacenamiento/DB? | **No** |
| ¿Variables nuevas? | `ELSA_RELAY_NODE_ID`, hash(es) de la credencial del nodo (en el panel, no en Git), topes y plazos. Una `RelaySettings` propia, independiente de `elsa.config.Settings` (que fuerza adaptadores DEV/TEST) |
| ¿La UI? | La sirve el relay (mismo montaje estático que hoy) para ser **same-origin** |

### 8.2 PC1

- **Componente:** un **agente Python perteneciente a ELSA** (`src/elsa/node/` + CLI en
  `src/elsa/tools/`, como las herramientas actuales), **proceso separado** de FastAPI: ELSA sigue
  funcionando sin él (regla 9) y no depende de él.
- Reenvía solo a la URL de ELSA en **loopback** configurada; no abre ningún puerto.
- Arranque **manual** al inicio; automatizarlo (tarea programada/servicio) **no está autorizado**
  y se decide en D2.5.
- ELSA en PC1 debe correr con `ELSA_ENV` adecuado y sin adaptadores *fake*; ver §13 (decisión
  pendiente).

### 8.3 Dependencias Python (`pyproject.toml`, `uv.lock`, imports)

| Alternativa | Clasificación |
|---|---|
| **C. Long polling (recomendada)** | **SIN DEPENDENCIA NUEVA** (`httpx>=0.27` ya es dependencia de runtime; el servidor usa FastAPI/Starlette y `asyncio`) |
| A. WebSocket | **REQUIERE LIBRERÍA PYTHON:** `websockets` (cliente en PC1 y servidor bajo Uvicorn). No aparece en `pyproject.toml` ni en `uv.lock`. Justificación: *push* sin latencia de espera y base para *streaming*; solo se justifica si C no cabe en Render |

### 8.4 Frontend

Hoy `web/js/api.js` usa `BASE = '/api/v1'` (relativo): **ya es same-origin**; no conoce IP,
localhost, modelo ni credenciales de nodo. Cambios previstos mínimos: mensajes en español para
los códigos nuevos (`ELSA_LOCAL_UNAVAILABLE`, `ELSA_LOCAL_BUSY`, `ELSA_LOCAL_TIMEOUT`) y,
opcionalmente, un aviso ONLINE/OFFLINE. El **login real** es un subbloque aparte (§12). La CSP
actual (sin recursos remotos) es compatible.

### 8.5 Base de datos

**Sin base de datos nueva y sin tocar Supabase.** Persistencia solo haría falta para auditar
solicitudes del relay, escalar a varias instancias o encolar con el nodo apagado: nada de eso es
Pilot 0.1. Coste asumido: un reinicio de Render pierde solicitudes en vuelo (de segundos).

## 9. Relación con el «Modo ELSA»

D2 **alimenta** el Modo ELSA futuro; **no lo cierra**. `Start/Stop-ElsaLlm.ps1` **no son** el Modo ELSA
(`docs/llm-runtime.md`: «Eso es otro bloque»).

| Pieza | Estado | Nota |
|---|---|---|
| Preflight de PC1 (memoria, GPU libre) | **NO DOCUMENTADO** | Solo hay línea base de rendimiento en `docs/llm-runtime.md` |
| Arranque de Phi/llama.cpp | **YA EXISTE** | `Start-ElsaLlm.ps1` (no es el Modo ELSA) |
| Parada de Phi/llama.cpp | **YA EXISTE** | `Stop-ElsaLlm.ps1` |
| Arranque de ELSA (FastAPI) | **NUEVO** | Hoy es manual en una terminal |
| Agente/conector de Render | **NUEVO** | D2.3 |
| Health | **PARCIAL** | `/health/live`, `/health/ready`, `Test-ElsaLlm.ps1`; falta una vista conjunta |
| Estado ONLINE hacia Render | **NUEVO** | Sale del latido del agente |
| Reconexión | **NUEVO** | §7.8 |
| Apagado ordenado (dejar de aceptar, esperar en vuelo, parar) | **PARCIAL** | Solo la parada del LLM |
| Limpieza | **NUEVO** | Archivos PID/log del agente |
| Recuperación tras reinicio de PC1 | **NUEVO** | Hoy ELSA no vuelve solo (§4.4) |
| Cerrar aplicaciones / liberar memoria | **NO DOCUMENTADO** | Explícitamente fuera de lo hecho |

## 10. Estrategia incremental

Un único PR para todo está **descartado**. Cada incremento exige autorización (regla 20) y su
documento de cierre (regla 26).

| Incremento | Contenido | Archivos | Nº |
|---|---|---|---|
| **D2.1 — Contrato** | ADR del protocolo; modelos tipados del sobre/estados/errores y lista cerrada; pruebas del contrato. **Sin red** | `docs/adr/0030-protocolo-relay-render-pc1.md` (CREATE), `src/elsa/relay/__init__.py` (CREATE), `src/elsa/relay/protocol.py` (CREATE), `tests/test_relay_protocol.py` (CREATE) | 4 |
| **D2.2 — Relay en Render** | Concentrador en memoria, autenticación de nodo, rutas de nodo, *passthrough*, `RelaySettings`, segundo servicio | `src/elsa/relay/settings.py`, `hub.py`, `auth.py`, `app.py` (CREATE); `tests/test_relay_hub.py`, `tests/test_relay_app.py` (CREATE); `render.yaml`, `tests/test_render_blueprint.py`, `.env.example`, `docs/environment-variables.md` (MODIFY) | 10 |
| **D2.3 — Agente de PC1** | Cliente *long poll*, reenvío a loopback con lista cerrada, backoff, duplicados, cancelación | `src/elsa/node/__init__.py`, `settings.py`, `agent.py`, `src/elsa/tools/relay_node.py`, `tests/test_node_agent.py` (CREATE); `.env.example`, `docs/environment-variables.md` (MODIFY) | 7 |
| **D2.4 — Integración y endurecimiento** | Prueba de extremo a extremo en proceso (relay + agente + ELSA), `TrustedHost` y cabeceras de seguridad en el relay, mensajes de la UI | `tests/test_relay_e2e_local.py` (CREATE); `src/elsa/relay/app.py`, `web/js/api.js` (MODIFY) y sus pruebas | ~5 |
| **D2.5 — Modo ELSA operacional mínimo** | Scripts de arranque/parada/verificación de ELSA + agente; runbook. **Sin servicios ni tareas** salvo autorización | `scripts/Start-Elsa.ps1`, `Stop-Elsa.ps1`, `Test-Elsa.ps1`, `docs/d2-runbook-acceso-remoto.md` (CREATE) | 4 |
| **D2.6 — Login real** | Subbloque propio (§12) | Planificado aparte | — |
| **D2.7 — Mediciones y prueba en Render** | Medir límites de Render (§7.2, §7.10); prueba desde otra red | Evidencia sin datos SAP | — |
| **D2.8 — Prueba PAPELSA y cierre** | Prueba real desde PAPELSA; documento de cierre según `BLOCK_CLOSURE_STANDARD.md` | Documento de cierre | — |

Ningún incremento supera ~12 archivos. **Primer incremento recomendado: D2.1.**

## 11. Pruebas diseñadas

| Prueba | Incremento |
|---|---|
| PC1 online: solicitud válida → respuesta normal | D2.2/D2.4 |
| PC1 offline → `ELSA_LOCAL_UNAVAILABLE` inmediato, sin encolar | D2.2 |
| Latido caducado (TTL) → pasa a OFFLINE | D2.2 |
| Solicitud sin `Authorization` → rechazada por Render | D2.2 |
| Ruta fuera de la lista cerrada → `route_not_allowed` | D2.2/D2.3 |
| Nodo no autenticado / credencial incorrecta / sin hash configurado | D2.2 |
| Timeouts: cola, nodo sin responder, plazo total | D2.2/D2.4 |
| Error local de ELSA devuelto sin trazas | D2.3/D2.4 |
| Reconexión: backoff, nuevo `epoch`, `NODE_RESET` de lo en vuelo | D2.3 |
| Solicitud duplicada → una sola ejecución | D2.2/D2.3 |
| Cancelación y expiración | D2.2/D2.3 |
| **El JWT del usuario no aparece en logs, ni en URL, ni en disco** | D2.2/D2.3/D2.4 |
| **La credencial del nodo no aparece en logs ni en URL** | D2.2/D2.3 |
| Cabeceras no permitidas no se reenvían | D2.3 |
| E2E local (relay + agente + ELSA, loopback) | D2.4 |
| E2E en Render, medición de límites | D2.7 |
| Prueba real desde PAPELSA; **apagar el agente y comprobar que la URL pasa a «no disponible»**; revocar la credencial y comprobar el bloqueo | D2.8 |

La evidencia se guarda sin datos SAP. Además, antes de cualquier prueba remota: `pytest`
focalizado, `ruff check`, `ruff format --check`, `git diff --check` y CI en verde.

## 12. Login: piloto controlado frente a operación normal

Este subbloque **no es una condición arquitectónica previa** del relay.

- **Prueba piloto controlada:** **posible con el mecanismo actual.** Pegar un JWT
  de ~1 h es incómodo pero no impide técnicamente PAPELSA → Render → PC1 con un operador que
  lo genera y lo pega.
- **Operación normal:** **requiere login real**; pegar en PAPELSA un JWT generado en PC1 no es
  aceptable como uso diario.

Se conserva el diseño de la auditoría:

Objetivo: que PAPELSA entre con correo y contraseña de Materiales sin copiar JWT.

- Flujo: formulario en `web/js/screens/login.js` → Supabase Auth del proyecto Materiales
  (`/auth/v1/token?grant_type=password`, con la clave **publicable**, sin `service_role`) →
  `access_token` + `refresh_token`. Es el mismo sistema de identidad (ADR 0002); no se crea otro.
- Archivos probables: `web/js/screens/login.js`, `web/js/api.js` (refresh y reintento ante 401, logout),
  `web/js/state.js`, `web/js/main.js`, config del origen de Supabase vía `/session/context`, CSP
  (`connect-src` al proyecto Materiales), tests y docs.
- Riesgos: el refresh token en el navegador es un secreto de larga vida (guardarlo solo en
  `sessionStorage` o en memoria; nunca en URL/log); la CSP actual prohíbe recursos remotos
  (`docs/security.md`), hay que abrir `connect-src` solo al host de Materiales; no registrar
  credenciales; MFA, si Materiales lo exige, cambia el flujo; la contraseña viaja a Supabase
  (no pasa por ELSA).
- Logout: borrar tokens y llamar a `/auth/v1/logout`. Expiración: refresh silencioso;
  si falla, volver al login. Recuperación de contraseña: la de Materiales.
- Pruebas: unit de `api.js`, tests de CSP y de logs sin credenciales, E2E manual.
- Este diseño requiere aprobación antes de implementarse (toca autenticación sensible).

## 13. Pendientes de verificación

- Puerto `8032` (System/PID 4) y proceso `dispatcher` en `30950` (PID 4416): escuchan en todas las
  interfaces y no se identificaron. Con perfil de red *Public* y firewall activo no son accesibles
  desde fuera, pero conviene saber qué son. Se puede investigar en solo lectura bajo petición.
- Ambiente de ejecución: PC1 corre ELSA hoy en `DEV` por costumbre (`docs/development.md`). Para exponerlo
  hay que decidir `TEST` (config estricta) o una variante; también hay un único proyecto
  Supabase de ELSA (`docs/development.md` §Supabase), lo que choca con la regla 8 si DEV y TEST
  llegasen a diferenciarse. **Decisión humana + ADR.**
- No se ejecutó ELSA ni la suite: no se cambió código.

## 14. Alternativas evaluadas durante D2 pero no base del piloto

**Estado: histórico.** Esta comparación se hizo en la auditoría inicial como si la arquitectura
no estuviera decidida. Tras [ADR 0029](adr/0029-arquitectura-hibrida-render-pc1-para-acceso-remoto.md)
**ninguna de estas opciones es la arquitectura del piloto.** Se conservan como
descartadas (D, E, F, G) o de contingencia (A, B, C), y para dejar constancia de por qué
no se usan.

- **A. VPN corporativa/privada ya existente:** contingencia, solo si TI de PAPELSA la ofreciera;
  el piloto **no** depende de TI.
- **B. Overlay privado (Tailscale/ZeroTier/WireGuard):** contingencia para el acceso del propio
  responsable desde otras redes; exige software en el PC de PAPELSA, contra el requisito de «solo
  navegador».
- **C. Túnel saliente de terceros + capa de acceso (p. ej. Cloudflare Tunnel + Access):** fue la
  **recomendación inicial** de la auditoría y queda **superada**. Exige instalar un agente
  externo, una cuenta y un dominio propio; el relay sobre Render cumple el mismo requisito
  «saliente, sin puerto entrante» sin software externo.
- **D, E, F:** rechazadas (port forwarding, SSH público, Uvicorn directo a Internet).
- **G. Mover ELSA a la nube:** descartada: contradice «IA local = PC1».

| Opción | Seguridad | Instala en PC1 | Instala en PAPELSA | Admin | Firewall | Router | CGNAT | Cifrado | URL estable | Dependencia externa | Costo | Tras reiniciar | Red corporativa | Complejidad | Cumple restricciones hoy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A. VPN corporativa/privada ya existente | Alta | No | Quizá | Quizá | No | No | Sí | Sí | Sí | TI PAPELSA | — | Depende | Alta | Media | **No existe/no detectada** |
| B. Overlay privado (Tailscale/ZeroTier/WireGuard) | Alta (extremo a extremo) | Sí | **Sí** (cliente) | Sí (instalación) | No | No | Sí | Sí | Sí (nombre del overlay) | Coordinador del overlay | Gratis a esta escala (verificar vigente) | Servicio, arranca solo | **Baja**: exige software en el PC corporativo | Media | No: instala y crea cuenta |
| C. Túnel saliente + capa de acceso (p. ej. Cloudflare Tunnel + Access) | Alta si se usa Access (SSO/OTP) + auth de ELSA | Sí (`cloudflared`) | **No** (solo navegador) | Sí en PC1 (si se instala como servicio) | No | No | Sí | Sí (TLS hasta el borde; el proveedor ve el tráfico) | Sí, **requiere dominio propio**; los túneles rápidos son efímeros y sin Access | Cuenta + proveedor | Gratis a esta escala (verificar vigente); dominio ~costo anual | Servicio o tarea | Media-alta (443 saliente/entrante estándar, WebSockets no necesarios) | Media | No: instala, crea cuenta, DNS |
| D. Port-forward en el router | Baja | No | No | No | Sí | **Sí** | **No** | Solo si se añade TLS | No (IP dinámica) | No | — | Sí | Media | Media-alta | **Rechazada** |
| E. SSH expuesto a Internet | Media-baja | Sí (`sshd`) | Cliente | Sí | Sí | Sí | No | Sí | No | No | — | Servicio | Baja (SSH suele bloquearse) | Alta | **Rechazada** |
| F. Uvicorn/FastAPI directo a Internet | Muy baja | No | No | No | Sí | Sí | No | No | No | No | — | — | — | — | **Rechazada** |
| G. Mover ELSA a cloud | Depende | No | No | No | No | No | Sí | Sí | Sí | Proveedor cloud | Pago | Sí | Alta | Alta | Cambia el requisito (PC1 como servidor); fuera de alcance |

## 15. Autorizaciones necesarias (hard stop)

Aprobada la arquitectura, **lo que sigue pendiente de autorización explícita**, una por vez
(regla 20):

| # | Acción | Por qué | Riesgo |
|---|---|---|---|
| 1 | Aprobar el transporte recomendado (long polling, §7.2) y abrir D2.1 (contrato + ADR 0030) | Es el primer incremento; sin red ni dependencias | Bajo |
| 2 | (D2.2) Crear el segundo servicio en Render y fijar sus variables en el panel | Cambia el despliegue y exige tocar la cuenta de Render | Medio: cuenta con 2FA |
| 3 | (D2.7) Medir los límites de Render y decidir el plan (Free o de pago) | Hay supuestos **NO VERIFICADOS** | Coste |
| 4 | Decidir el ambiente de ejecución de ELSA en PC1 (`TEST` o variante) y su ADR | No se puede exponer `DEV`/fake; choca con la regla 8 si DEV y TEST llegan a diferenciarse | Reabre la regla 8 |
| 5 | Aprobar el diseño del subbloque de login (§12) antes de la operación normal | Toca autenticación sensible | Ver §12 |
| 6 | (D2.5) Decidir si el agente arranca automáticamente (tarea programada/servicio) | Hoy no se autoriza | Medio |

## 16. Veredicto

- **Arquitectura híbrida Render–PC1 formalizada:** SÍ (ADR 0029).
- **Transporte Render ↔ PC1 definido:** **NO.** Hay una **recomendación de diseño** (long polling saliente,
  §7.2) con puntos **NO VERIFICADOS** sobre los límites de Render; falta su ADR de protocolo (D2.1) y la
  autorización para implementar.
- **Listo para el primer incremento de implementación (D2.1):** SÍ, previa autorización del responsable.
- **D2 no necesita redecidir la arquitectura completa:** necesita diseñar e implementar el enlace seguro
  Render ↔ PC1.

Este documento no cierra D2. Un cierre exige §11 completo y el documento definido por
`docs/project/BLOCK_CLOSURE_STANDARD.md`.
