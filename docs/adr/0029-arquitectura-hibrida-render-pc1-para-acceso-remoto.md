# ADR 0029 — Arquitectura híbrida Render–PC1 para acceso remoto a ELSA

- Estado: **aceptado**
- Fecha de la decisión: **2026-10-04**
- Bloque: **D2** (acceso remoto seguro a ELSA)
- Decide el responsable del proyecto; este ADR **formaliza** una decisión que
  hasta hoy no estaba en el repositorio
- **Decide una sola cosa**: la forma de la arquitectura de acceso remoto y el
  reparto de responsabilidades entre Render y PC1
- **No decide** el protocolo Render ↔ PC1, la implementación del relay, el
  login definitivo ni el arranque definitivo del «Modo ELSA» (§ «No decidido»)
- **No reabre** ADR 0002 (identidad de Materiales, autorización en backend),
  ADR 0003 (puertos y adaptadores) ni ADR 0018 (el runtime LLM escucha solo
  en loopback)
- Aplica las reglas **1, 2, 3, 6, 9, 11, 13, 14, 15, 19, 20, 22 y 25** de
  [`CLAUDE.md`](../../CLAUDE.md)

---

## Contexto

### 1. Contexto histórico

Render **se introdujo como plataforma de una demo sintética HTTPS**. Lo
demuestran los commits `76462ed` (2026-09-07, «add a Render blueprint for the
synthetic demo over HTTPS») y `3d643b2` (2026-09-08), y el propio
[`render.yaml`](../../render.yaml): un único servicio web gratuito en
`ELSA_ENV=DEV`, con identidades y conocimiento **en memoria**, datos sintéticos,
sin Supabase y sin secretos. Su motivo era que el micrófono exige HTTPS
desde un equipo corporativo.

Esa demo **no se reinterpreta**. La auditoría de continuidad de D2 (2026-10-04)
buscó en código, historial Git, ADR y documentos de traspaso y **no encontró**
ningún relay, WebSocket, polling, túnel, worker ni agente entre Render y PC1, ni
documentado ni implementado. El cierre de ELSA–Materiales V1
([§21](../bloque-5-0-integracion-elsa-materiales-v1-cierre.md)) dejaba D2 como
siguiente bloque con el mecanismo **abierto** («red privada o VPN preferible a
exponer PC1»).

Lo que el repositorio sí fija y esta decisión **respeta**:

- ADR 0018: el LLM corre en PC1, `llama-server` escucha solo en `127.0.0.1`
  y `ELSA_LLM_ALLOW_REMOTE=true` se rechaza incluso en DEV. Render no tiene GPU
  ni pesos (ADR 0013 §8, ADR 0018 §4).
- Regla 5 / ADR 0002: la identidad es la de Supabase Auth de Materiales y ELSA
  decide permisos en el backend.

### 2. Problema nuevo

El responsable quiere dejar PC1 encendido (en casa) y usar ELSA desde un equipo
de PAPELSA con **solo navegador**, sin depender de TI de PAPELSA, **sin
exponer PC1 a Internet** y manteniendo en PC1 la IA y los recursos locales.

---

## Decisión

### 3. Arquitectura objetivo

```text
PC PAPELSA ── navegador, HTTPS ──▶ RENDER (extremo público)
                                      │
                                      │  transporte seguro iniciado por PC1
                                      │  (PENDIENTE DE DISEÑO DETALLADO, §6)
                                      ▼
                                   PC1 (nodo de ejecución local)
                                      ├─ ELSA (FastAPI, solo loopback)
                                      ├─ runtime local: llama.cpp / Phi
                                      ├─ conocimiento y recursos locales
                                      └─ integración existente con Materiales
```

### 4. Responsabilidades

**Render es el extremo público de ELSA para el piloto.** Según el diseño
posterior puede: servir la interfaz; recibir solicitudes HTTPS; conocer si el
nodo PC1 está disponible; encaminar solicitudes; recibir respuestas y devolverlas
al navegador.

**Render no es**: motor de IA; host de Phi o de llama.cpp; repositorio de
conocimiento local; copia del inventario SAP o de Materiales; ejecutor de las
decisiones de ELSA (permisos, recuperación, generación); lugar de secretos
innecesarios de PC1.

**PC1 es el nodo de ejecución local**: ELSA, la IA local, el modelo, el
conocimiento local, las integraciones locales y la consulta a Materiales.

**El modelo local no se expone a Render por una URL pública.** `llama-server`
sigue en loopback (ADR 0018); Render nunca lo alcanza.

### 5. Invariantes

`IA LOCAL = PC1` · `MODELO LOCAL = PC1` · `RENDER = EXTREMO PÚBLICO /
INTERMEDIARIO` · el equipo PAPELSA necesita solo navegador, si es posible ·
**no** hay puerto público en PC1 · **no** hay port forwarding · **no** se abre
el firewall a Internet · **no** se usa `service_role` · TI de PAPELSA **no** es
dependencia del piloto.

### 6. No decidido por este ADR

- El **protocolo** Render ↔ PC1 (se compara en el diseño de D2; sigue abierto
  hasta su ADR propio).
- La implementación concreta del relay y del agente de PC1.
- El login definitivo (hoy se pega un JWT; ver el documento D2 §12).
- El arranque definitivo del «Modo ELSA»: los scripts `Start/Stop-ElsaLlm.ps1`
  **no son** el Modo ELSA (`docs/llm-runtime.md`).

Sí queda fijado, como restricción que cualquier transporte debe cumplir: **lo
inicia PC1 hacia afuera**, y no requiere conexión entrante a la red doméstica.

---

## Consecuencias

1. **Render deja de ser únicamente una demo en la arquitectura objetivo.** El
   servicio `elsa-demo` existente y su razón histórica no cambian.
2. **PC1 sigue siendo necesario.** Es un punto único de fallo ya reconocido
   (riesgo R1 del mapa de traspaso).
3. **Si PC1 está fuera de línea, la IA local no puede responder.** Render lo
   declara de forma explícita («ELSA local no disponible») y **no** responde con
   IA en la nube, **no** inventa y **no** consulta Materiales en sustitución de
   PC1 (reglas 2 y 9).
4. **La comunicación Render ↔ PC1 requiere autenticación propia**, distinta de
   la identidad del usuario, y estado explícito ONLINE/OFFLINE.
5. **No se abre ningún puerto público en PC1.**
6. **Render ve el tráfico en claro** (termina TLS y transporta solicitudes y
   respuestas, incluido el JWT del usuario y respuestas de inventario). Es una
   decisión de confianza aceptada por el responsable; obliga a que Render
   transporte el mínimo, no persista nada y no registre cabeceras ni cuerpos.
7. Las alternativas evaluadas en la auditoría D2 (VPN corporativa, Tailscale,
   Cloudflare Tunnel, ngrok, SSH público, port forwarding) **no son la
   arquitectura del piloto**; quedan como descartadas o de contingencia.
8. El despliegue de Render y la interfaz siguen siendo «abiertos» en el sentido
   de `CLAUDE.md` §4: nada de esto convierte a Render en dependencia dura de un
   módulo de negocio.
9. Antes de implementar hay que registrar un ADR de **protocolo** (sucesor de
   este) y respetar la regla 20: cada incremento de D2 necesita autorización.

## Ver también

- [`docs/d2-acceso-remoto-seguro-auditoria.md`](../d2-acceso-remoto-seguro-auditoria.md) — auditoría, evolución y diseño del transporte
- [ADR 0002](0002-identidad-de-materiales-autorizacion-en-backend.md), [ADR 0003](0003-puertos-y-adaptadores-para-modelos-reemplazables.md), [ADR 0018](0018-runtime-llm-local-phi-4-mini-y-llama-cpp.md)
