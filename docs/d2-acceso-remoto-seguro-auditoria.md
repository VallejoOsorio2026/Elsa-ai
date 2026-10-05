# D2 — Acceso remoto seguro a ELSA: auditoría y decisión

**Estado:** auditoría y propuesta. **No es un cierre.** No se implementó nada, no se
instaló software, no se abrió ningún puerto y no se tocó ninguna configuración de
Windows, red o router.

- Repositorio: `Elsa-ai`, rama `claude/d2-secure-remote-access`, desde `main` en `cc924f4`.
- Fecha de la auditoría: 2026-10-04.
- Nombre de bloque: el repositorio no define un identificador formal para D2
  (el cierre 5.0 §21 lo llama «Acceso remoto seguro a ELSA»); aquí se usa «D2».

## 1. Objetivo

PC1 encendido con ELSA ejecutándose, y un ingeniero en PAPELSA (otra red) que abre
ELSA desde el navegador, se autentica y consulta inventario real de Materiales.
Un puerto abierto que responde **no** es éxito: se exige acceso + cifrado +
autenticación + consulta E2E real desde red externa.

## 2. Estado actual (hallazgos)

### 2.1 Cómo se sirve ELSA

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

### 2.2 Seguridad web

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

### 2.3 Autenticación y login

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

### 2.4 PC1 (solo lectura)

| Elemento | Resultado |
|---|---|
| Red activa | Sí. Una interfaz Ethernet, IPv4 privada presente, gateway presente |
| Perfil de red | **Public** (el más restrictivo de Windows) |
| Firewall | Los tres perfiles **activos**; acciones inbound/outbound por defecto: `NotConfigured` (= valores de Windows: inbound bloqueado, outbound permitido) |
| Puerto 8000 / 8080 | Libres ahora (ELSA y llama-server no están en ejecución) |
| Escuchando en red | Solo servicios estándar de Windows (135, 139, 445, 5040, 7680, RPC dinámicos), más `8032` y un proceso `dispatcher` en `30950` **no identificados** (ver §8) |
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

## 3. Restricciones aplicables

Sin instalar software; sin cuentas nuevas; sin tocar firewall, router, DNS, servicios,
tareas programadas, admin; sin exponer Uvicorn; Materiales y su adaptador intactos;
sin migraciones. Posiblemente PC de PAPELSA con restricciones de TI (no se asume que
permita VPN, software nuevo, túneles, puertos no estándar o WebSockets).

## 4. Modelo de amenazas

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
| 13 | Exposición de `/docs` | Baja | Bajo | Ya cerrado fuera de DEV. **Atención:** PC1 corre en DEV hoy → ver §8 | Sí |
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
`supabase`, `postgres` y storage `local`) o añadir un ambiente adecuado (decisión de §10).

## 5. Alternativas

| Opción | Seguridad | Instala en PC1 | Instala en PAPELSA | Admin | Firewall | Router | CGNAT | Cifrado | URL estable | Dependencia externa | Costo | Tras reiniciar | Red corporativa | Complejidad | Cumple restricciones hoy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A. VPN corporativa/privada ya existente | Alta | No | Quizá | Quizá | No | No | Sí | Sí | Sí | TI PAPELSA | — | Depende | Alta | Media | **No existe/no detectada** |
| B. Overlay privado (Tailscale/ZeroTier/WireGuard) | Alta (extremo a extremo) | Sí | **Sí** (cliente) | Sí (instalación) | No | No | Sí | Sí | Sí (nombre del overlay) | Coordinador del overlay | Gratis a esta escala (verificar vigente) | Servicio, arranca solo | **Baja**: exige software en el PC corporativo | Media | No: instala y crea cuenta |
| C. Túnel saliente + capa de acceso (p. ej. Cloudflare Tunnel + Access) | Alta si se usa Access (SSO/OTP) + auth de ELSA | Sí (`cloudflared`) | **No** (solo navegador) | Sí en PC1 (si se instala como servicio) | No | No | Sí | Sí (TLS hasta el borde; el proveedor ve el tráfico) | Sí, **requiere dominio propio**; los túneles rápidos son efímeros y sin Access | Cuenta + proveedor | Gratis a esta escala (verificar vigente); dominio ~costo anual | Servicio o tarea | Media-alta (443 saliente/entrante estándar, WebSockets no necesarios) | Media | No: instala, crea cuenta, DNS |
| D. Port-forward en el router | Baja | No | No | No | Sí | **Sí** | **No** | Solo si se añade TLS | No (IP dinámica) | No | — | Sí | Media | Media-alta | **Rechazada** |
| E. SSH expuesto a Internet | Media-baja | Sí (`sshd`) | Cliente | Sí | Sí | Sí | No | Sí | No | No | — | Servicio | Baja (SSH suele bloquearse) | Alta | **Rechazada** |
| F. Uvicorn/FastAPI directo a Internet | Muy baja | No | No | No | Sí | Sí | No | No | No | No | — | — | — | — | **Rechazada** |
| G. Mover ELSA a cloud | Depende | No | No | No | No | No | Sí | Sí | Sí | Proveedor cloud | Pago | Sí | Alta | Alta | Cambia el requisito (PC1 como servidor); fuera de alcance |

## 6. Recomendación

**Opción recomendada: C — túnel saliente con capa de acceso por delante de ELSA**
(implementación de referencia: Cloudflare Tunnel + Cloudflare Access).

```text
PC PAPELSA (solo navegador, HTTPS 443)
  → https://<subdominio-propio>   (TLS)
  → capa de acceso del proveedor (SSO / código por correo, lista de correos autorizados)
  → túnel SALIENTE iniciado por PC1  (sin puerto entrante, sin router, sin firewall)
  → PC1: agente del túnel → http://127.0.0.1:8000
  → ELSA (FastAPI/Uvicorn, escucha SOLO en 127.0.0.1)
       → verifica JWT de Materiales (segunda barrera, la existente)
       → ELSA → Materiales (HTTPS/PostgREST)
```

**Por qué:**
1. Es la única que cumple a la vez «PC corporativo solo con navegador» y «sin puerto
   entrante». PAPELSA no necesita instalar nada ni aceptar VPN.
2. Dos barreras independientes: la capa de acceso decide *quién puede ver siquiera* la UI/API; ELSA
   sigue decidiendo *quién puede consultar qué* con el JWT y sus permisos. Ninguna reemplaza a la otra.
3. ELSA permanece en `127.0.0.1`: no se cambia el modelo de exposición; si el túnel cae, la única
   ruta desaparece (falla cerrado, criterio 12).
4. Funciona con CGNAT/IP dinámica.

**Costos y riesgos que hay que aceptar explícitamente:** (a) el proveedor termina TLS y *ve el
tráfico en claro*, incluido el JWT y las respuestas de inventario; es una decisión de
confianza, no solo técnica — debe pasar por la validación del responsable y, si aplica, de
TI/seguridad de PAPELSA; (b) hace falta un dominio propio y una cuenta con 2FA (riesgo 20);
(c) dependencia de un tercero (riesgo 19); (d) si TI de PAPELSA bloquea el dominio o
inspecciona TLS, no funcionará — se descubre solo con la prueba real.

**Opción de respaldo: B — overlay privado (p. ej. Tailscale)**, si la política de confianza
no admite que un tercero vea el tráfico: cifrado extremo a extremo, sin dominio, pero **exige
instalar un cliente en el PC de PAPELSA**, lo que probablemente TI no permitirá. Se mantiene como
plan B y como vía de acceso para el propio responsable desde otras redes.

**Si PAPELSA ya ofrece VPN corporativa (A):** es preferible a ambas y no requiere instalar nada
en PC1; confirmar con TI antes de gastar esfuerzo. Eso es una consulta humana, no algo
descubrible desde PC1.

**Rechazadas:** D (port-forward), E (SSH expuesto), F (Uvicorn directo). G solo queda como
alternativa conceptual futura.

## 7. Cambios necesarios (diseño, nada implementado)

### 7.1 En ELSA

| Archivo | Propósito | Riesgo |
|---|---|---|
| `src/elsa/config.py`, `.env.example`, `docs/environment-variables.md` | `ELSA_ALLOWED_HOSTS` (lista explícita; obligatoria en TEST) | Bajo |
| `src/elsa/main.py` | `TrustedHostMiddleware` con esos hosts; cabeceras de seguridad (HSTS solo si hay HTTPS, `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `X-Robots-Tag: noindex`, CSP acorde a `docs/security.md` §«sin recursos remotos») | Medio: una CSP errónea rompe la UI; probar con la UI real |
| `scripts/Start-Elsa.ps1`, `Stop-Elsa.ps1`, `Test-Elsa.ps1` (mismo estilo que los de LLM) | Arranque/parada/verificación reproducibles, **bind fijo a 127.0.0.1**, sin `--reload`, sin `--forwarded-allow-ips '*'` | Bajo |
| `docs/d2-runbook-acceso-remoto.md` | Runbook: iniciar, verificar, detener, URL, reinicio de PC1, revocar acceso, fallos de Materiales/canal | Bajo |
| `docs/adr/0029-…` | ADR de la arquitectura de exposición y del ambiente de ejecución (regla 25) | Bajo |

No se tocan: Materiales, `MaterialsPort`, adaptador, contratos, migraciones, grants, BOM, Tampella.
**Default seguro intacto:** `127.0.0.1`, sin `0.0.0.0`, sin CORS `*`.

### 7.2 Externos

| Dónde | Cambio |
|---|---|
| PC1 | Instalar el agente del túnel; crear la configuración (credencial del túnel fuera de Git y del repo); decidir si arranca como servicio (hoy no se autoriza). Sin cambios de firewall |
| Red doméstica/oficina de PC1 | Ninguno (salida a 443; sin port-forward) |
| PC de PAPELSA | Ninguno: navegador. Posible desbloqueo del dominio por TI |
| Servicio externo | Cuenta del proveedor con 2FA; dominio; túnel; política de acceso (lista de correos autorizados, duración de sesión corta) |

## 8. Pendientes de verificación (no bloquean la decisión)

- Puerto `8032` (System/PID 4) y proceso `dispatcher` en `30950` (PID 4416): escuchan en todas las
  interfaces y no se identificaron. Con perfil de red *Public* y firewall activo no son accesibles
  desde fuera, pero conviene saber qué son. Se puede investigar en solo lectura bajo petición.
- Ambiente de ejecución: PC1 corre ELSA hoy en `DEV` por costumbre (`docs/development.md`). Para exponerlo
  hay que decidir `TEST` (config estricta) o una variante; también hay un único proyecto
  Supabase de ELSA (`docs/development.md` §Supabase), lo que choca con la regla 8 si DEV y TEST
  llegasen a diferenciarse. **Decisión humana + ADR.**
- No se ejecutó ELSA ni la suite: no se cambió código.

## 9. Login (subbloque propuesto, no iniciado)

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

## 10. Pruebas

**Local, antes de cualquier red externa:** servidor arranca con los scripts; `health/live` 200;
`health/ready` entendido (`materials` aparece `degraded` por diseño, ver cierre 5.0 decisión 12);
`/app/` 200; `Host` inválido → 400; sin `Authorization` → 401; consulta E2E a Materiales; parada
limpia; escaneo de logs sin `Bearer`/`eyJ`. Más `pytest` focalizado, `ruff check`,
`ruff format --check`, `git diff --check`, CI verde.

**Remota (desde PAPELSA o una red distinta):** abrir la URL; candado TLS; pasa la capa de acceso con una
identidad autorizada y **falla con una no autorizada**; login; ver Tampella; consulta de inventario con
respuesta de Materiales; el token no aparece en URL ni en consola; logs de ELSA y del agente sin secretos;
**apagar el agente y comprobar que la URL deja de responder**; revocar un acceso y comprobar el bloqueo.
La evidencia se guarda sin datos SAP.

## 11. Autorizaciones necesarias (hard stop)

La recomendación exige **instalar un programa, crear una cuenta externa, un dominio/DNS y un
túnel externo**. Por el encargo (§17), no se implementa nada. Se solicita una decisión por vez:

| # | Acción | Por qué | Riesgo | Alternativa |
|---|---|---|---|---|
| 1 | Decidir el mecanismo: **C** (túnel + capa de acceso), **B** (overlay) o consultar a TI si hay **A** (VPN) | Es la decisión raíz; todo lo demás depende de ella | C: el proveedor ve el tráfico; B: software en el PC corporativo | Consultar a TI primero |
| 2 | (tras 1) autorizar instalar el agente en PC1 y crear la cuenta con 2FA | PC1 no tiene nada utilizable | Cuenta externa como nuevo activo a proteger | — |
| 3 | (tras 1) decidir el ambiente de ejecución expuesto (`TEST`) | No se puede exponer `DEV`/fake | Reabre la regla 8 | ADR |
| 4 | Aprobar el diseño del subbloque de login | Sin él la operación no es real | Ver §9 | — |

## 12. Veredicto

- **D2 — arquitectura de acceso remoto segura definida:** SÍ (opción C, respaldo B), condicionada a las
  autorizaciones anteriores.
- **Implementación D2 puede comenzar sin aprobaciones adicionales:** **NO.**
- **Siguiente única decisión del responsable:** ¿consultas primero con TI de PAPELSA si dispone de una
  VPN que pueda usarse (A) y, si no, autorizas la opción C (túnel + capa de acceso con una cuenta nueva
  y 2FA) o prefieres B?

Este documento no cierra D2. Un cierre exige §10 completo y el documento definido por
`docs/project/BLOCK_CLOSURE_STANDARD.md`.
