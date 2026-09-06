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

Para tener HTTPS hacen falta tres decisiones que **no** están tomadas y que no
corresponde tomar desde el código; ver §4.

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

## 4. Qué falta para una URL HTTPS pública

Tres decisiones, ninguna de ellas técnica del lado del código:

1. **Dónde se ejecuta.** Un servidor accesible desde internet: VPS, un equipo
   de PAPELSA con puerto publicado, o un túnel (Cloudflare Tunnel, ngrok).
   Cada opción implica una cuenta y unas credenciales que este repositorio no
   tiene ni debe tener.
2. **Qué dominio.** CLAUDE.md menciona `elsa-ai.link` como destino previsto.
   Hace falta confirmar quién controla el DNS y apuntar un registro al
   servidor elegido.
3. **Quién termina TLS.** Lo natural es un proxy inverso delante de uvicorn
   (Caddy obtiene el certificado solo; nginx o Traefik con Let's Encrypt
   funcionan igual). Uvicorn puede servir TLS directamente con
   `--ssl-keyfile` y `--ssl-certfile`, pero para algo permanente el proxy es
   mejor: renueva el certificado y no obliga a reiniciar la aplicación.

Con esas tres respuestas, lo que queda por hacer del lado de ELSA es corto y
está acotado:

- declarar `ELSA_CORS_ORIGINS=https://<dominio>`;
- decidir si la demostración pública sigue en DEV con datos sintéticos (lo
  recomendable) o pasa a TEST, que exige Supabase real, PostgreSQL y
  desactivar la siembra;
- ejecutar detrás del proxy con `--proxy-headers --forwarded-allow-ips`, para
  que los logs registren la IP del cliente y no la del proxy;
- comprobar en el navegador que el candado aparece y que el micrófono queda
  habilitado.

**No se ha elegido servicio, ni preparado credenciales, ni configurado
dominio.** Es el punto exacto en el que se detuvo este bloque.

---

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

En el navegador, antes de empezar:

- [ ] La pantalla de acceso muestra las cuatro personas y el aviso de ambiente
      de demostración.
- [ ] El logotipo PAPELSA se ve (si falta, el servidor lo dice en el log al
      arrancar).
- [ ] Al pulsar «Grabar» el navegador pide permiso de micrófono y se concede.
- [ ] La barra de contexto técnico muestra «BOM publicado · 8 componentes».

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
