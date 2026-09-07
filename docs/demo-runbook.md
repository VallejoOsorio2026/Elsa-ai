# Runbook de la demostración del piloto (Bloque 3)

Cómo levantar ELSA para enseñarla, qué se puede enseñar y qué no, y qué falta
exactamente para tenerla en una URL HTTPS pública.

> **Todo lo que se ve en la demostración es sintético.** Los cuatro usuarios,
> el BOM, el AMEF y los códigos de material están inventados. Nada procede de
> la Planta Molino Barbosa.

---

## 1. La ruta más corta: en el propio equipo

Es la que hay que usar si mañana solo hace falta enseñarla desde el portátil
que la ejecuta.

```bash
git clone https://github.com/VallejoOsorio2026/Elsa-ai.git
cd Elsa-ai
uv sync

ELSA_ENV=DEV \
ELSA_CORS_ORIGINS=http://127.0.0.1:8000 \
ELSA_DEMO_SEED=true \
uv run uvicorn elsa.main:create_app --factory --host 127.0.0.1 --port 8000
```

Abrir **http://127.0.0.1:8000/** en el navegador. Eso es todo: no hay proceso
de compilación, ni `npm`, ni un segundo servidor. Quien ve la demostración
solo necesita un navegador.

**El micrófono funciona aquí sin HTTPS.** El navegador considera `localhost` y
`127.0.0.1` contextos seguros, así que `getUserMedia` está disponible. Es la
razón por la que esta ruta no necesita certificado.

Navegadores probados con esta interfaz: Chromium. Firefox y Edge deberían
comportarse igual (usan las mismas API estándar), pero no se han verificado.

### Qué se puede enseñar

Entrando como cada una de las cuatro personas de la pantalla de acceso:

| Persona | Consultar | Aportar | Revisar |
|---|---|---|---|
| Ingeniero de mantenimiento | sí | sí | no |
| Revisora técnica | sí | sí | sí |
| Segundo revisor | sí | sí | sí |
| Administradora | sí | sí | sí (por ser administradora) |

Recorrido completo: consultar el equipo → grabar una nota de voz → revisar
«Esto es lo que entendí» → responder la guía → enviar → cambiar de usuario a
la revisora → aprobar o rechazar. Que el ingeniero **no** vea el Centro de
Revisión es parte de lo que se enseña, no una carencia.

---

## 2. Desde otro dispositivo de la red: hace falta HTTPS

Si la demostración se ve desde un móvil o un portátil distinto del que ejecuta
el servidor, **la grabación de voz deja de funcionar sin HTTPS**. No es un
límite de ELSA: los navegadores no dan acceso al micrófono sobre `http://` en
una dirección que no sea local, y no hay forma de saltárselo.

El resto de la aplicación —consultar, revisar, ver aportes— sí funciona sobre
HTTP en la red local. Solo se pierde el micrófono.

Si hace falta HTTPS, lo más corto es publicarla en Render (§4) y abrirla
desde el navegador de cada equipo, en vez de servirla desde la red local.

Mientras tanto, sirviendo en la red local sin cifrar:

```bash
ELSA_ENV=DEV \
ELSA_CORS_ORIGINS=http://<ip-del-equipo>:8000 \
ELSA_DEMO_SEED=true \
uv run uvicorn elsa.main:create_app --factory --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` expone el servidor a la red. Hacerlo solo en una red de
confianza y solo mientras dure la demostración: el ambiente DEV acepta
identidades fake y cualquiera que llegue al puerto entra como quien quiera.

---

## 3. Configuración

Todo lo que sigue está documentado en [`environment-variables.md`](environment-variables.md)
y declarado en `.env.example`.

| Variable | Demo | Por qué |
|---|---|---|
| `ELSA_ENV` | `DEV` | La demostración usa identidades y almacenes en memoria, y eso solo se permite en DEV. |
| `ELSA_DEMO_SEED` | `true` | Siembra las cuatro personas y el BOM sintético. |
| `ELSA_CORS_ORIGINS` | el origen desde el que se abre | Obligatorio, sin comodines. |
| `ELSA_WEB_UI_ENABLED` | `true` (por defecto) | Sirve la interfaz. |
| `ELSA_DEBUG` | sin poner | Prohibido fuera de DEV y prescindible dentro. |

La interfaz y la API se sirven **desde el mismo origen**, así que CORS no
interviene en el recorrido de la demostración. La variable sigue siendo
obligatoria porque el backend se niega a arrancar sin orígenes declarados.

### Lo que la demostración pierde al reiniciar

Los permisos, el conocimiento y los aportes viven en memoria. **Reiniciar el
servidor borra todos los aportes creados durante la demostración** y vuelve a
sembrar el estado inicial. Es deliberado —lo de una demostración no debe
sobrevivirla— pero conviene no reiniciar a mitad.

---

## 4. Publicarla en HTTPS con Render

Es la ruta elegida para la demostración: da HTTPS con certificado válido sin
tocar DNS ni gestionar certificados, y con ello el micrófono funciona desde
cualquier PC corporativo. El repositorio ya trae
[`render.yaml`](../render.yaml), así que la configuración manual se reduce a
conectar el repositorio y pulsar «Apply».

**Lo que se despliega es la demostración con datos sintéticos.** No hay
Supabase, ni base de datos, ni secretos. Los tests de
`tests/test_render_blueprint.py` fijan esas propiedades para que un cambio
descuidado no las rompa en silencio.

### 4.1 Pasos en Render

1. Empujar la rama `claude/bloque-3-papelsa-brand-mf5nfm` (ya está en
   `origin`).
2. En <https://dashboard.render.com>, crear cuenta o entrar, y autorizar el
   acceso a GitHub para el repositorio `VallejoOsorio2026/Elsa-ai`. Basta con
   dar acceso a ese repositorio; no hace falta a toda la organización.
3. **New → Blueprint**.
4. Elegir el repositorio `Elsa-ai`. Render encuentra `render.yaml` solo.
5. Poner nombre al blueprint (por ejemplo `elsa-demo`) y pulsar **Apply**.
6. Esperar al primer despliegue: instala dependencias y arranca. En el plan
   gratuito suele tardar entre dos y cinco minutos.
7. La URL aparece arriba en la página del servicio, con la forma
   `https://elsa-demo.onrender.com`. Abrirla lleva directamente a `/app/`.

Si el nombre `elsa-demo` ya estuviera tomado, Render asigna otro y la URL
cambia. En ese caso, corregir `ELSA_CORS_ORIGINS` en **Environment** con la
URL real y guardar (redespliega solo). La demostración funciona igual —la
interfaz y la API comparten origen— pero el valor quedaría mal declarado.

### 4.2 Si prefieres crear el servicio a mano

Sin blueprint, en **New → Web Service**, con estos valores exactos:

| Campo | Valor |
|---|---|
| Repository | `VallejoOsorio2026/Elsa-ai` |
| Branch | `claude/bloque-3-papelsa-brand-mf5nfm` |
| Language / Runtime | Python 3 |
| Build Command | `pip install uv && uv sync --frozen --no-dev` |
| Start Command | `.venv/bin/uvicorn elsa.main:create_app --factory --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'` |
| Health Check Path | `/api/v1/health/live` |

Y estas variables de entorno, **ninguna secreta**:

| Variable | Valor |
|---|---|
| `ELSA_ENV` | `DEV` |
| `ELSA_DEMO_SEED` | `true` |
| `ELSA_CORS_ORIGINS` | la URL HTTPS del servicio, p. ej. `https://elsa-demo.onrender.com` |

### 4.3 Por qué cada pieza es como es

- **`ELSA_ENV=DEV`.** La demostración se sostiene sobre adaptadores en
  memoria, que la configuración solo permite en DEV. Poner `TEST` no la haría
  más seria: la aplicación se negaría a arrancar por falta de Supabase y
  PostgreSQL reales.
- **`--host 0.0.0.0`.** El proxy de Render no llega por la loopback.
- **`--port $PORT`.** El puerto lo asigna Render en cada arranque.
- **`--forwarded-allow-ips '*'`.** Uvicorn solo confía en las cabeceras
  `X-Forwarded-*` que vengan de 127.0.0.1. Sin esta opción se cree en texto
  plano detrás del TLS de Render y las redirecciones absolutas de
  `StaticFiles` salen como `http://`, lo que rompe el contexto seguro del
  navegador y, con él, el micrófono. El comodín es seguro aquí: solo el proxy
  de Render alcanza ese puerto, y ELSA no toma ninguna decisión de seguridad
  a partir de la IP —el control de abuso cuenta por usuario autenticado.
- **`uv sync --frozen`.** Instala exactamente lo que fija `uv.lock`, sin
  resolver de nuevo: dos despliegues del mismo commit instalan lo mismo.
- **`/api/v1/health/live` como sonda.** No depende de nada.
  `/health/ready` informa `degraded` a propósito en esta demostración (los
  adaptadores son fake y el motor de voz es simulado); usarla como sonda haría
  que Render reiniciara en bucle un servicio que funciona como se espera.

### 4.4 Lo que hay que saber del plan gratuito

- **El servicio se apaga tras unos 15 minutos sin tráfico.** La siguiente
  visita lo despierta y tarda cerca de un minuto en responder. Conviene abrir
  la URL unos minutos antes de enseñarla.
- **Cada arranque borra el estado.** Permisos, conocimiento y aportes viven en
  memoria (§3): al despertar, el servicio vuelve a sembrar los datos
  sintéticos y los aportes creados en una sesión anterior ya no están.
- El primer despliegue tras cada `git push` a esa rama es automático.

### 4.5 Lo que sigue sin estar decidido

Render da una URL propia, suficiente para la demostración. Un dominio de
PAPELSA —CLAUDE.md menciona `elsa-ai.link`— sigue siendo una decisión
pendiente: requiere confirmar quién controla el DNS y añadir el dominio
personalizado en Render. No hace falta para enseñarla mañana.

## 5. Comprobaciones antes de enseñarla

```bash
# El servidor vive
curl http://127.0.0.1:8000/api/v1/health/live

# Estado por dependencia: `transcription` aparece como `degraded`, y es
# correcto — el motor de voz a texto es simulado y lo declara.
curl http://127.0.0.1:8000/api/v1/health/ready

# La interfaz responde
curl -I http://127.0.0.1:8000/app/
```

Sobre el despliegue de Render, cambiando la dirección:

```bash
curl -sI https://elsa-demo.onrender.com/            # 307 -> /app/
curl -s  https://elsa-demo.onrender.com/api/v1/health/live
```

En el navegador, antes de empezar:

- [ ] La pantalla de acceso muestra las cuatro personas y el aviso de ambiente
      de demostración.
- [ ] El logotipo PAPELSA se ve (si falta, el servidor lo dice en el log al
      arrancar).
- [ ] Al pulsar «Grabar» el navegador pide permiso de micrófono y se concede.
- [ ] La barra de contexto técnico muestra «BOM publicado · 8 componentes».
- [ ] En el despliegue de Render, el candado del navegador aparece y la
      dirección es `https://`. Sin eso no habrá micrófono.

---

## 6. Lo que esta demostración **no** demuestra

Decirlo antes de enseñarla evita que alguien se lleve una idea equivocada:

- **No hay inteligencia artificial.** El chat busca literalmente los términos
  de la pregunta en el BOM publicado y responde con una plantilla fija. Cada
  respuesta lo lleva escrito.
- **No hay transcripción.** El audio se graba y se guarda de verdad; el texto
  es un marcador de posición hasta que la persona escribe lo que dijo. La
  interfaz lo marca como simulado en cada pantalla donde aparece.
- **No hay RAG, ni documentos, ni planos, ni búsqueda semántica.**
- **Aprobar un aporte no lo publica.** Queda marcado como válido; el
  conocimiento vigente del equipo solo cambia al publicar una versión.
- **Los aportes no persisten** entre reinicios (§3).
