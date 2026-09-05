# ADR 0005 — Verificación real del JWT emitido por Materiales

## Estado

Aceptado (2026-09-05). Complementa el [ADR 0002](0002-identidad-de-materiales-autorizacion-en-backend.md),
que decidió *dónde* vive la autorización; este decide *cómo* se verifica la
identidad.

## Contexto

El Bloque 1 exige el primer adaptador real del puerto `auth`. Antes de
escribirlo se inspeccionó, **en modo lectura y sin modificar nada**, el
repositorio del Asistente de Materiales
(`VallejoOsorio2026/papelsa-asistente-materiales`).

### Lo que sí se pudo comprobar

| Hecho | Evidencia en el repositorio de Materiales |
|---|---|
| La identidad la emite Supabase Auth con correo + contraseña | `js/auth.js` (`db.auth.signInWithPassword`) |
| El registro público está desactivado; los usuarios los crea el administrador | `js/auth.js`, `docs/seguridad.md` |
| Existe la tabla `public.perfiles`, uno a uno con `auth.users` | `sql/002_schema.sql` |
| El campo `activo` gobierna el acceso; los usuarios no se borran, se desactivan | `sql/002_schema.sql`, `sql/005_rls.sql` |
| La política `perfil_propio_lectura` permite a cada usuario leer **su propia** fila (`id = auth.uid()`) | `sql/005_rls.sql` |
| El proyecto expone una clave publicable con el formato nuevo `sb_publishable_...`, pública por diseño | `js/config.js`, `docs/seguridad.md` |
| El piloto **no** genera clave secreta (`sb_secret_...`) | `docs/seguridad.md` |

De aquí sale una consecuencia importante: **ELSA no necesita ninguna
credencial privilegiada de Materiales**. Puede comprobar que un usuario sigue
activo consultando su propio perfil con el JWT de ese mismo usuario, que es
exactamente lo que la política RLS de Materiales autoriza.

### Lo que NO se pudo comprobar

**El algoritmo con el que Supabase firma hoy los JWT de Materiales.** Esa
configuración vive en el servidor de Supabase, no en el repositorio, y el
entorno donde se desarrolló este bloque tiene el egreso de red restringido:
las conexiones a `*.supabase.co` se rechazan en el proxy, de modo que no fue
posible consultar el JWKS público del proyecto ni el endpoint
`/auth/v1/settings`.

La presencia de una clave `sb_publishable_...` indica que el proyecto usa el
sistema **nuevo** de claves de API de Supabase, que suele acompañar a la firma
asimétrica con JWKS. **Es un indicio, no una comprobación**: las claves de API
y las claves de firma del JWT se migran por separado, así que un proyecto con
clave publicable puede seguir firmando con el secreto simétrico heredado
(HS256). No se da por supuesto ninguno de los dos casos.

Lo que hace falta confirmar está en la sección **Pendiente de confirmación**.

## Decisión

1. El adaptador real `SupabaseJwtAuthAdapter` verifica el token
   **criptográficamente y en local**, sin llamar a Materiales por cada
   petición.
2. Soporta los dos mecanismos posibles, elegidos por configuración
   (`ELSA_AUTH_JWT_ALGORITHMS`), no por código:
   - **asimétrico (preferido)**: descarga el JWKS público del proyecto de
     Materiales, cachea las claves y las refresca ante un `kid` desconocido
     (rotación), con una espera mínima entre refrescos para que un token
     forjado no provoque una descarga por petición;
   - **simétrico (solo si el proyecto lo exige)**: el secreto se lee de
     `ELSA_AUTH_JWT_SECRET`, existe únicamente como variable de entorno del
     backend y nunca se versiona.
3. Se comprueban firma, expiración (`exp`), emisor (`iss`) y audiencia
   (`aud`, cuando está configurada), y se exige la presencia de `sub`.
4. **El algoritmo del token debe estar en la lista configurada.** Cualquier
   otro se rechaza antes de tocar ninguna clave, lo que cierra tanto `none`
   como la confusión de algoritmo (un HS256 firmado con la clave pública).
5. El `sub` debe ser un UUID: es la referencia con la que ELSA identifica al
   usuario.
6. Tras verificar el token, ELSA comprueba en la **fuente autoritativa** que
   el perfil sigue activo: `GET /rest/v1/perfiles?id=eq.<sub>` con la clave
   publicable como `apikey` y el **JWT del propio usuario** como
   `Authorization`. Sin credencial de servicio de Materiales.
7. Se distinguen siempre dos familias de error:
   `InvalidTokenError` (credenciales → 401) e
   `IdentityProviderUnavailableError` (fallo técnico → 503).
8. Ni el token ni la cabecera `Authorization` se registran nunca en los logs,
   ni completos ni truncados, y no se devuelven en ninguna respuesta.

## Pendiente de confirmación

Para cerrar el mecanismo hace falta una comprobación en el proyecto Supabase
de Materiales que solo puede hacer quien tenga acceso al panel. **Nada de lo
que se pide es secreto**; no se debe pegar en ningún sitio un JWT, el JWT
secret, una clave privada ni una `service_role`.

1. En el panel de Supabase del proyecto de Materiales,
   *Project Settings → API Keys / JWT Keys*: ¿el proyecto sigue con el
   **JWT secret heredado (HS256)** o ya tiene **claves de firma asimétricas**
   (ECC P-256 / RSA)?
2. La respuesta del endpoint público del JWKS:

   ```bash
   curl -s https://<ref>.supabase.co/auth/v1/.well-known/jwks.json
   ```

   Basta con los campos `kty`, `alg` y `kid` de cada clave. Ese endpoint es
   público y solo contiene claves **públicas**.
3. Si el resultado fuese que el proyecto firma en simétrico, la decisión a
   tomar es si se migra Materiales a claves asimétricas (recomendable, y no
   es trabajo de este bloque) o si ELSA se configura con `HS256` y el secreto
   en su variable de entorno.

Mientras tanto, el valor por defecto de `ELSA_AUTH_JWT_ALGORITHMS` es
`ES256,RS256`: si el proyecto resultara ser simétrico, la aplicación
rechazará los tokens en lugar de aceptarlos por descuido, y bastará cambiar
una variable de entorno.

## Consecuencias

- Cambiar de mecanismo de firma es cambiar variables de entorno, no código.
- La verificación no depende de la disponibilidad de Materiales en cada
  petición: solo del JWKS cacheado. Si el JWKS deja de responder, los tokens
  firmados con claves ya conocidas se siguen aceptando; si no hay ninguna
  clave utilizable, se responde 503 y no 401.
- La espera mínima entre refrescos del JWKS introduce una latencia máxima
  conocida ante una rotación de claves (por defecto 60 s), durante la cual
  los tokens firmados con la clave nueva se rechazan con 401. Es el precio de
  no permitir que un `kid` inventado dispare descargas ilimitadas.
- La comprobación del perfil añade una llamada HTTP a Materiales por petición
  autenticada. Es aceptable en este bloque —es la garantía de que un usuario
  desactivado deja de entrar de inmediato— y su coste se podrá reducir después
  con una caché de vida corta, que será una decisión con su propio ADR.
- No se modificó nada del proyecto Materiales, ni hizo falta.
