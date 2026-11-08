# ADR 0039 — Historial de activaciones de embeddings y Ctrl+Z de la primera activación

- Estado: **propuesto** (2026-11-08). Queda aceptado con el merge del PR de R1.C.1
- Bloque: **R1.C.1**, previo a cualquier escritura de R1.C en TEST
- **Decide**:
  - cómo se deshace una activación hasta volver a «ningún modelo activo»;
  - cómo queda en la base el historial de activaciones;
  - qué versiones documentales pueden embeberse;
  - cómo se cierra una corrida interrumpida o abandonada.
- **No decide**: aplicar la migración en Supabase TEST, ni registrar, generar o activar BGE-M3. Cada operación
  tiene su autorización (regla 15)
- **Amplía** el [ADR 0013](0013-arquitectura-de-almacenamiento-vectorial.md) §5 sin reabrirlo. «Volver atrás es
  activar otra vez» sigue siendo válido cuando hay un modelo anterior; este ADR cubre el caso en que no lo hay
- Implementación:
  - `supabase/migrations/20261108010000_create_embedding_model_events.sql`, con su rollback;
  - en `PostgresVectorStore`: `deactivate_model`, `run_guard` y `reconcile_run`;
  - en `elsa.tools.embeddings_admin`: los comandos `deactivate`, `runs` y `reconcile-run`.

## Contexto

R1.C.0 encontró cuatro huecos antes de la primera activación de BGE-M3 en TEST:

1. **No había forma de volver a «ningún modelo activo».**
   - `activate` solo cambia de un modelo a otro, y en la primera activación no existe un anterior.
   - `retire_model` es irreversible: un modelo retirado no se reactiva, y el `unique` sobre el espacio vectorial
     impide registrarlo otra vez.
2. **La activación no dejaba rastro en la base.** Solo iba al log de la aplicación, y `activated_at` se vacía
   al desactivar.
3. **`generate` embebía cualquier versión** que recibiera, incluida una pendiente.
4. **Un Ctrl+C o la muerte del proceso dejaban la corrida `running` para siempre**, sin forma soportada de
   cerrarla.

La regla permanente del proyecto exige un Ctrl+Z comprobado antes de cualquier modificación que afecte al
funcionamiento.

## Decisión

### 1. `deactivate`: el Ctrl+Z de `activate`

`deactivate_model(model_id, actor, reason)` devuelve el modelo activo a `registered` y vacía `activated_at`.

- **Mecanismo:** el mismo advisory lock de activación y una sola transacción.
- **Resultado:** deja **ningún modelo activo**. No reactiva el anterior: volver a él es un `activate` explícito.
- **Conservación:** no borra el modelo, ni sus vectores, ni el historial. El mismo modelo puede volver a
  activarse.
- **Negativas:** se niega sin escribir nada si el modelo indicado no es el activo, si no hay ningún activo, si
  no existe o si el motivo está vacío. Exige el id del modelo **que el operador cree activo**, para que dos
  operadores no deshagan cosas distintas.
- **Esquema:** las restricciones de 20260913010000 ya admitían `active → registered`; esta operación no
  necesitó cambiarlas.

### 2. Historial append-only: `elsa.embedding_model_events`

Una tabla nueva, en la **misma transacción** que cada cambio de estado. Si la fila de auditoría no puede
escribirse, el cambio no ocurre.

| Evento | Cuándo | Columnas obligatorias |
|---|---|---|
| `activated` | Un modelo pasa a activo | `model_id`; `previous_model_id` si había otro activo |
| `deactivated` | Ctrl+Z de una activación | `model_id` y `reason` |
| `retired` | Se retira un modelo (irreversible) | `model_id` |
| `run_reconciled` | Se cierra a mano una corrida abandonada | `model_id`, `run_id` y `reason` |

Todas llevan `actor`, `request_id` y `occurred_at`. La forma de cada evento la impone la base
(`ck_embedding_event_shape`, `ck_embedding_event_reason`). Las filas no se modifican ni se borran: lo impide
el mismo disparador de `reviews` y `document_version_events`.

**Una sola tabla, no dos:** activar, desactivar, retirar y cerrar corridas son la historia de un mismo espacio
vectorial. No sustituye a `admin_audit_log`, que es la auditoría de cuentas y permisos.

Activar el modelo que ya está activo, o retirar uno ya retirado, no escribe nada: no hay transición.

### 3. Solo se embeben versiones `approved` o `published`

`generate_for_version` comprueba el estado **antes de abrir la corrida**. Una versión `pending_validation`,
`rejected`, `superseded` o inexistente se niega con `IneligibleVersionError`, sin escribir nada. Esto es lo
que ya decía el ADR 0013 §7; la recuperación productiva sigue exigiendo `published`.

### 4. Interrupciones

- **Una excepción** cierra la corrida como `failed`, igual que antes.
- **Un Ctrl+C o la cancelación de la tarea** la cierran como `cancelled`, y se vuelve a lanzar la misma
  interrupción.
  - Con `asyncio.run`, en Python ≥ 3.11, Ctrl+C llega a la tarea principal como `CancelledError`.
  - `KeyboardInterrupt` también se captura por si llega directamente.
- **Si cerrar la corrida también falla**, normalmente porque la base cayó, la corrida queda `running`. El
  llamador ve el error original, no el del cierre.
- **Los lotes ya confirmados se conservan** y un reintento los reutiliza (idempotencia por `embedded_sha256`).

### 5. Corridas abandonadas: prueba de vida y conciliación

La muerte del proceso no deja ejecutar ninguna limpieza. **La antigüedad de una corrida no prueba que su
proceso haya terminado.** Por eso:

- **Mientras genera**, el proceso mantiene un *advisory lock de sesión* de PostgreSQL sobre la corrida
  (`run_guard`), en una conexión propia que dura toda la corrida.
- **Si el proceso muere o pierde la conexión**, PostgreSQL suelta el lock solo.
- **`reconcile_run` exige las dos condiciones:**
  1. poder tomar ese lock, es decir, que ninguna sesión viva lo mantiene;
  2. que la corrida lleve al menos `idle_minutes` sin escribir ningún vector. La CLI exige un mínimo de 10.
- **Si se cumplen**, cierra la corrida como `cancelled` y deja un evento `run_reconciled` con actor y motivo.
- **Si un proceso zombi intentara seguir después**, `store_embeddings` lo rechaza, porque la corrida ya no
  está `running`.

## Ctrl+Z de cada operación de R1.C

| Operación | Escribe | Recuperación funcional | Lo que se conserva |
|---|---|---|---|
| `register` | 1 fila en `embedding_models` | Un modelo registrado y no activo es **inerte**: no cambia la recuperación. Uno mal registrado se deja así y se registra el correcto, que es otra fila. No se retira, porque es irreversible | La fila |
| `generate` | 1 corrida y sus vectores | Mientras el modelo no se active, los vectores son **inertes**: la búsqueda semántica exige un modelo activo | La corrida y los vectores. No existe ninguna operación para borrar vectores; el rollback de 20260913010000 los destruiría todos y no es un Ctrl+Z |
| Interrupción | Lotes confirmados | `cancelled`, `failed` o `reconcile_run`; repetir reutiliza lo confirmado | Los vectores confirmados |
| `activate` | Estado del modelo y un evento | **`deactivate`**: vuelve a ningún modelo activo | El modelo, los vectores y el historial |
| La migración | Tabla nueva | El rollback, que **se niega si hay eventos** | El historial |

**Limitación aceptada:** un modelo registrado o unos vectores generados por error no pueden eliminarse. Se
neutralizan dejándolos sin activar.

## Consecuencias

- El rollback de esta migración tiene que aplicarse **antes** que el de 20260913010000, porque hay claves
  foráneas. Su cabecera y sus tests lo fijan.
- `run_guard` ocupa una conexión del pool durante cada corrida.
- La prueba de vida depende de que el pooler de Supabase, en modo sesión, cierre el backend cuando el cliente
  desaparece. **INFERENCIA:** es su comportamiento en modo sesión, pero no se ha medido en TEST.

## Alternativas descartadas

- **Retirar como Ctrl+Z.** Es irreversible y bloquearía BGE-M3 en esa revisión para siempre.
- **Registrar la activación en `admin_audit_log`.** Exigiría ampliar su catálogo de operaciones y mezclaría la
  administración de cuentas con la historia del espacio vectorial.
- **Conciliar solo por antigüedad.** No distingue un proceso lento de uno muerto.
- **Guardar host y PID en la corrida.** Solo sirve en la misma máquina, y un PID se reutiliza.
