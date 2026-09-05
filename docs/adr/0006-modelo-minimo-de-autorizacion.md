# ADR 0006 — Modelo mínimo de autorización de ELSA

## Estado

Aceptado (2026-09-05).

## Contexto

Materiales dice **quién** es cada persona (ADR 0002 y ADR 0005). ELSA tiene
que decidir **qué** puede consultar cada una, con tres restricciones que no
son negociables:

- los permisos se aplican **antes** de recuperar conocimiento, nunca después:
  una fuente no autorizada no puede llegar a entrar en el conjunto de
  recuperación;
- el LLM no participa en la decisión;
- los permisos de ELSA no dependen de los roles de Materiales (`admin` /
  `ingeniero`): son propios y, sobre todo, **por usuario**.

La jerarquía completa prevista es
`dominio → planta → área/ubicación → equipo → tipo de información`, pero
construirla entera ahora sería código por anticipación. El MVP solo necesita
dominio y equipo, y `Tampella` tiene que ser un **dato**, no una constante del
código.

Además hay que poder declarar de forma segura al primer administrador sin
editar tablas a mano, permitir varios administradores después, transferir la
administración y auditar los cambios.

## Decisión

### Esquema

Todo vive en el esquema `elsa` de Supabase ELSA, definido por migraciones
versionadas (ADR 0001). Tres tablas y un catálogo:

| Tabla | Papel |
|---|---|
| `elsa.accounts` | Asocia un usuario externo de Materiales (`external_user_id` = `sub` del JWT) con ELSA; `is_active` e `is_admin` |
| `elsa.knowledge_domains` | Catálogo de dominios (`mantenimiento`, `materiales`) |
| `elsa.permission_grants` | Permisos por usuario sobre `(domain, equipment)`, con quién otorgó/revocó y cuándo |
| `elsa.admin_audit_log` | Auditoría *append-only* de los cambios administrativos |

Decisiones concretas y su porqué:

- **Autorización por usuario, no por rol.** Un `grant` apunta a una persona.
  Los roles podrán existir más adelante como plantillas administrativas que
  *generan* grants, sin dejar de ser esta tabla la autoridad final.
- **`equipment IS NULL` significa el dominio completo.** Un permiso de dominio
  cubre cualquier equipo; un permiso de equipo cubre **solo** ese equipo, ni
  el dominio entero ni otro equipo.
- **Revocar no borra.** Se rellenan `revoked_at` y `revoked_by`, de modo que
  el historial de quién otorgó y quién revocó sobrevive. Dos índices únicos
  parciales garantizan un solo permiso *activo* por alcance (hacen falta dos
  porque en SQL `NULL` no es igual a `NULL`).
- **Los alcances son dato normalizado.** `Tampella`, `tampella` y ` TAMPELLA `
  son el mismo equipo: se normalizan a minúsculas y las restricciones `CHECK`
  de la migración impiden que entre otra cosa. `tampella` no aparece como
  constante en ningún módulo de ELSA.
- **Evolución sin destruir.** Los niveles que faltan (`plant`, `area`,
  `information_type`) se añadirán como columnas *nullable* adicionales de
  `permission_grants`. Una fila existente, con esas columnas en `NULL`,
  conservará exactamente el significado que tiene hoy: «todo ese nivel».
- **Auditoría inmodificable.** Un *trigger* rechaza `UPDATE` y `DELETE` sobre
  `admin_audit_log`, también para la credencial de servicio. Un registro que
  puede reescribirse no es auditoría. Cada entrada guarda actor, usuario
  afectado, operación, alcance, `request_id` y momento; se escribe en la
  **misma transacción** que el cambio que documenta.
- **RLS activo y sin políticas** en las cuatro tablas, y `REVOKE` para los
  roles `anon` y `authenticated`. No es el mecanismo de autorización —ese está
  en FastAPI—, sino defensa en profundidad. El esquema `elsa` además no se
  expone por PostgREST, así que estas tablas no son alcanzables desde el
  navegador.

### Decisión de acceso

Vive en `src/elsa/core/authorization.py`, sin HTTP ni SQL:

```
if not is_active:        -> denegado (account_inactive)
if is_admin:             -> permitido (acceso total)
if algún grant cubre el alcance: -> permitido
en cualquier otro caso:  -> denegado (no_matching_grant)
```

**DEFAULT DENY**: sin cuenta activa en ELSA y sin permiso explícito, no hay
acceso. Es la rama final, no una excepción.

### Bootstrap del primer administrador

`POST /api/v1/admin/bootstrap` exige simultáneamente:

1. un JWT válido de Materiales con perfil activo — el UUID que se promueve es
   el del usuario **realmente autenticado**, nunca uno escrito a mano ni
   incrustado en el repositorio;
2. el token de `ELSA_BOOTSTRAP_ADMIN_TOKEN` en la cabecera
   `X-Bootstrap-Token`, comparado en tiempo constante. Sin esa variable, el
   endpoint está deshabilitado;
3. que ELSA no tenga todavía otro administrador (serializado con un cerrojo
   consultivo de PostgreSQL, para que dos peticiones simultáneas no creen dos
   «primeros» administradores).

Es idempotente y queda auditado. A partir de ahí, la administración se otorga
y se transfiere por la API administrativa, puede haber varios administradores,
y el sistema impide que el último se retire y deje ELSA sin gobierno.

## Consecuencias

- Perder un permiso impide de inmediato nuevas recuperaciones de ese
  conocimiento: la decisión se toma en cada petición sobre los grants
  vigentes, sin caché.
- El adaptador en memoria y el de PostgreSQL pasan la **misma** batería de
  contrato (`tests/test_contract_permissions.py`), de modo que el de DEV no
  puede convertirse en una ficción cómoda que oculte errores del real.
- Como no hay RLS que respalde la decisión, la corrección del backend es la
  única barrera: por eso la autorización está aislada en un módulo puro, con
  tests propios, y toda ruta protegida pasa por la misma dependencia.
- El precio del catálogo de dominios es que otorgar un permiso sobre un
  dominio inexistente falla en lugar de crear un permiso que nunca casaría.
  Se considera una ventaja.
