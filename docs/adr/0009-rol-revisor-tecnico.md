# ADR 0009 — Revisor Técnico como capacidad separada de la administración

- Estado: aceptado
- Bloque: 2

## Contexto

El conocimiento técnico que ELSA publica tiene que estar validado por
alguien que responda por su exactitud. La pregunta es quién.

La opción cómoda era reutilizar el administrador del Bloque 1: ya existe,
ya tiene acceso total y no hace falta tabla nueva. Es también la opción
equivocada. Quien valida que un rodamiento es el que va en ese plano
responde por una afirmación técnica; quien administra responde por la
seguridad y por quién entra al sistema. Son responsabilidades distintas y
las ejercen personas distintas: el ingeniero que conoce la máquina no tiene
por qué gestionar usuarios, y quien gestiona usuarios no tiene por qué
saber de rodamientos.

## Decisión

Existe `elsa.reviewer_grants`, con la misma forma que `permission_grants`
—usuario, dominio, equipo opcional, quién otorgó, quién revocó— porque
responde a la misma pregunta: sobre qué puede actuar esta persona. Pero es
una capacidad **distinta**.

**Un Revisor Técnico puede**: cargar fuentes dentro de su alcance, consultar
importaciones y versiones, ver las discrepancias, aprobar, rechazar,
revertir y publicar cuando se cumplen los criterios.

**Un Revisor Técnico no puede**: administrar usuarios, concederse permisos,
cambiar la seguridad, cambiar la configuración global ni revisar fuera de su
alcance.

Reglas asociadas:

- **Revisar exige poder leer, pero poder leer no habilita a revisar.** En la
  API se aplican los dos filtros en ese orden.
- El alcance funciona como el del Bloque 1: una capacidad sobre un equipo no
  habilita otro equipo ni el dominio completo; una capacidad de dominio
  cubre todos sus activos.
- **El administrador conserva capacidad global de intervención**, porque
  alguien tiene que poder desbloquear una situación en la que el revisor
  asignado ya no está disponible.
- Otorgar y revocar es potestad exclusiva del administrador y queda
  auditado (`reviewer_granted`, `reviewer_revoked`).
- Las capacidades se resuelven **en cada petición**, no se cachean:
  deshabilitar a un revisor surte efecto de inmediato.
- **Deshabilitar conserva el historial.** La fila se marca revocada, no se
  borra, y ninguna validación firmada se toca. Borrarlas dejaría
  aprobaciones sin responsable, que es justo lo que una auditoría necesita
  saber.

### Las decisiones y sus motivos

- **Aprobar** admite comentario opcional.
- **Rechazar** exige motivo.
- **Revertir** exige motivo y señala qué validación deshace.

Cerrar o deshacer el trabajo de otra persona sin decir por qué lo vuelve
inapelable. La regla vive a la vez en el dominio y como restricción de la
base (`ck_review_reason_required`): la capa HTTP puede equivocarse, la base
no.

Una validación puede revertirla el mismo revisor (si sigue habilitado y
conserva alcance), otro revisor con alcance equivalente, o un administrador.

### Las validaciones solo se añaden

`elsa.reviews` es estrictamente *append-only*: un trigger prohíbe `UPDATE` y
`DELETE`, incluso para la credencial de servicio. Por eso no hay columna
«vigente»: la validación vigente de un sujeto es la de mayor `seq`. Una
tabla que puede reescribirse no es un historial, es una opinión actual.

Una misma persona puede cargar y validar información si tiene ambas
capacidades: la separación que exige este bloque es entre **revisar y
administrar**, no entre cargar y revisar.

## Alternativas descartadas

- **Reutilizar el administrador.** Habría concentrado en un rol dos
  responsabilidades que auditoría necesita separadas, y habría obligado a
  dar acceso a la gestión de usuarios a ingenieros que solo necesitan
  validar un BOM.
- **Un rol «contribuidor» separado del revisor** (quien carga no valida).
  Descartado para este bloque por decisión de alcance: se puede añadir
  después sin romper nada, porque cargar y validar ya son endpoints
  distintos.
- **Marcar la validación vigente con una columna y actualizarla.** Más
  simple de consultar y destruye la propiedad que hace útil el historial.
