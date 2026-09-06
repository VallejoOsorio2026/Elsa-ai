# ADR 0008 — Fuentes, versionado, publicación atómica y reconciliación

- Estado: aceptado
- Bloque: 2

## Contexto

ELSA recibe dos cosas que se parecen y no son lo mismo:

- El **XLSX aprobado por Ingeniería**: cómo *debía* quedar alimentado el BOM
  y cuál es la información técnica de referencia.
- El **HTM exportado de SAP**: cómo *se ve* el BOM en SAP en una fecha.

Confundirlas sería el error más caro posible. Si ELSA tratara el snapshot de
SAP como conocimiento aprobado, una desviación mal alimentada en SAP se
convertiría en la verdad del asistente y se propagaría a las decisiones de
mantenimiento.

## Decisión

### Ingeniería y SAP se guardan separados y nunca se mezclan

Son dos tablas distintas (`engineering_bom_versions` y `sap_bom_snapshots`),
alimentadas por dos parsers distintos, y **un snapshot de SAP nunca se
convierte en BOM de Ingeniería publicado**. ELSA no escribe en SAP: no
inicia sesión, no ejecuta transacciones y no envía cambios. Solo observa
archivos exportados.

### Nada se sobrescribe

Cada versión y cada snapshot se conservan completos. Publicar una versión
nueva marca la anterior como `superseded`, con su fecha; no la borra ni la
modifica. Sus renglones, su AMEF y sus planos siguen consultables.

### Una sola versión publicada, y publicar es atómico

La restricción vive en el esquema, no en el código de aplicación:

```sql
create unique index uq_published_version_per_asset
  on elsa.engineering_bom_versions (asset_id)
  where state = 'published';
```

Un índice parcial hace **imposible**, no improbable, que un activo tenga dos
versiones vigentes. Publicar ocurre dentro de una transacción que además
toma un cerrojo consultivo sobre el activo
(`pg_advisory_xact_lock`), de modo que dos publicaciones simultáneas se
serializan aunque vengan de dos instancias del backend. Un cerrojo en
memoria del proceso no protegería nada en cuanto haya más de un proceso.

Escribir una versión es igualmente una sola transacción: entra entera o no
entra. Una importación defectuosa **nunca** afecta a la última versión
publicada; queda registrada como `failed` con su tipo de fallo.

### Idempotencia por contenido

`unique (kind, sha256)` sobre `source_artifacts` hace que reimportar
exactamente el mismo archivo se detecte de forma determinística **en la
base**, no en una comprobación previa que dos peticiones simultáneas
pasarían a la vez. La segunda subida devuelve la importación original y no
crea una versión nueva.

### La validación pertenece a la versión que se evaluó

Al llegar una versión nueva se compara renglón a renglón contra la
publicada, usando una huella de los datos técnicos:

- **sin cambio** → puede heredarse la validación anterior, dejando
  constancia de la herencia (`reviews.inherited_from_id`);
- **modificado** → la aprobación previa queda histórica y el dato vuelve a
  revisión;
- **nuevo** → requiere validación;
- **retirado** → se conserva la historia; ni el componente ni su evidencia
  se borran.

La huella incluye los datos técnicos (qué es la pieza, cuántas, de qué
plano) y **excluye** los de inventario (`Max`, `Min`, `Stock Actual`). El
stock que traía la hoja es una foto del inventario en la fecha de esa
fuente, no un hecho técnico sobre el componente; si entrara en la huella,
cada actualización de existencias reabriría la validación de renglones que
no cambiaron, y un revisor que aprueba ruido termina aprobando sin mirar.
Los valores se conservan igualmente en la versión.

### La reconciliación es una capa aparte que no corrige nada

Comparar la versión publicada con un snapshot produce un resultado histórico
propio (`reconciliation_runs`) que **conserva ambos valores** y no modifica
ninguna de las dos fuentes. Clasificaciones:

`match`, `quantity_difference`, `engineering_only`, `sap_only`,
`duplicate_or_structural_difference`, `unresolved`.

Una diferencia entre 2 y 3 significa que hay una desviación; **no dice cuál
de los dos números es correcto**. Puede que SAP esté mal alimentado, que el
Excel esté desactualizado o que alguien cambiara la máquina. Elegir
automáticamente convertiría una pregunta abierta en un hecho falso que
sobreviviría a la persona capaz de detectarlo. Por eso ninguna discrepancia
se corrige sola.

Detalles que se siguen de ahí:

- Los **equipos hijos** del snapshot se excluyen de la comparación: describen
  la estructura del activo, no su lista de materiales.
- Un componente **sin código SAP** produce `unresolved`, no una
  discrepancia: no hay con qué emparejarlo automáticamente, y eso no lo hace
  incorrecto.
- Un material repetido produce `duplicate_or_structural_difference` en vez de
  emparejar «el primero con el primero», que sería inventar una
  correspondencia.
- Un snapshot posterior genera una corrida nueva. Así es como se demuestra
  que una discrepancia cambió o desapareció.

### Un usuario normal solo ve conocimiento publicado

La API de consulta sirve únicamente la versión publicada, omite los
identificadores internos y reporta las diferencias con SAP como una
**advertencia contada, no un informe**. El detalle —qué dice cada fuente, en
qué renglón— es material de revisión técnica.

## Consecuencias

- Un activo sin versión publicada no muestra nada al usuario normal, con una
  advertencia explícita. Es deliberado: nadie debe operar un equipo con una
  lista que no validó nadie.
- Reconciliar exige una versión publicada. Comparar contra un borrador daría
  un resultado que cambiaría al publicarse.
