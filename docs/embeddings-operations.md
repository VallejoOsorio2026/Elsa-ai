# Operación del motor de embeddings

Cómo registrar un modelo, generar los vectores y activarlo, desde una máquina
con acceso a los pesos. **No desde el servicio web**: en Render Free no caben
los pesos ni la CPU para cargarlos (ADR 0013 §8).

## Instalar el soporte

El motor es un **extra opcional**, no una dependencia de ELSA:

```bash
uv sync --extra embeddings
```

Sin ese extra, ELSA arranca, sirve y pasa toda su suite igual: el servicio web
nunca carga un modelo. Con él se instala `sentence-transformers` y su cadena de
dependencias, que son cientos de megas — por eso no está en la base.

El banco de pruebas de 4.2.a (`uv sync --extra bench`) sigue funcionando y trae
el mismo motor: `bench` lo declara **por referencia** a `embeddings`, de modo
que la versión se fija en un solo sitio y no puede divergir entre lo que mide
el banco y lo que embebe producción.

## Configurar el modelo

En `.env`, o como variables de entorno (en PC1, para R1.C, solo por sesión:
ver más abajo). Todas opcionales para arrancar;
**obligatorias para operar**:

```bash
ELSA_EMBEDDINGS_MODEL_ID=BAAI/bge-m3
ELSA_EMBEDDINGS_REVISION=<commit o digest concreto>
ELSA_EMBEDDINGS_DIMENSION=1024
ELSA_EMBEDDINGS_DEVICE=cpu
ELSA_EMBEDDINGS_BATCH_SIZE=16
```

`ELSA_EMBEDDINGS_REVISION` no admite `main`: una referencia móvil no identifica
unos pesos, y lo que se descargue mañana puede no ser lo que se midió
(ADR 0013 §2). Si el digest no está configurado, la herramienta falla y dice
qué falta.

**BGE-M3 es el primer modelo permitido.** EmbeddingGemma ganó el banco pero no
está aprobado para producción hasta validar su licencia para uso corporativo
(ADR 0015); habilitarlo será cambiar estas variables, sin tocar código ni
esquema. Sus prefijos, cuando llegue el momento:

```bash
ELSA_EMBEDDINGS_DOCUMENT_PREFIX="title: none | text: "
ELSA_EMBEDDINGS_QUERY_PREFIX="task: search result | query: "
```

Si un modelo exige autenticación en HuggingFace, se toma del entorno estándar
(`HF_TOKEN`). **Nunca se pasa por argumento**: acabaría en el historial del
shell.

### Configuración de R1.C en PC1: por sesión, sin tocar el `.env`

Decisión de R1.C.0: BGE-M3 con revisión fija, pesos oficiales ya en la caché
de PC1 y **sin red hacia HuggingFace**. Se define en la ventana de PowerShell
que va a ejecutar los comandos, y desaparece al cerrarla:

```powershell
$env:ELSA_EMBEDDINGS_MODEL_ID = "BAAI/bge-m3"
$env:ELSA_EMBEDDINGS_REVISION = "5617a9f61b028005a4858fdac845db406aefb181"
$env:ELSA_EMBEDDINGS_DIMENSION = "1024"
$env:ELSA_EMBEDDINGS_BATCH_SIZE = "4"
# Sin red: huggingface_hub lee esta variable al importarse, así que tiene que
# estar definida antes de lanzar el comando.
$env:HF_HUB_OFFLINE = "1"
# transformers no intenta convertir los pesos .bin a safetensors en segundo plano.
$env:DISABLE_SAFETENSORS_CONVERSION = "1"
```

Con esa revisión, `transformers` carga el `pytorch_model.bin` oficial con
`torch.load(weights_only=True)`. La conversión del PR 130 de HuggingFace no se
usa. Comprobado leyendo el código instalado (transformers 5.17.0 y
huggingface_hub 1.31.0), **no ejecutando el modelo**: la carga real queda para
G-0 de R1.C, con su propia autorización.

## Los comandos

```bash
# 1. Registrar la configuración actual como espacio vectorial. NO lo activa.
uv run python -m elsa.tools.embeddings_admin register --actor <uuid>

# 2. Embeber los chunks de una versión approved o published. NO activa nada.
uv run python -m elsa.tools.embeddings_admin generate \
    --model <uuid> --version <uuid> --actor <uuid>

# 3. Elegir qué modelo responde en la recuperación. Decisión aparte.
uv run python -m elsa.tools.embeddings_admin activate --model <uuid> --actor <uuid>

# 4. Ctrl+Z de la activación: deja NINGÚN modelo activo. Exige motivo.
uv run python -m elsa.tools.embeddings_admin deactivate \
    --model <uuid del modelo activo> --actor <uuid> --reason "<motivo>"

# 5. Ver qué hay registrado, cuál está activo y el historial.
uv run python -m elsa.tools.embeddings_admin status

# 6. Ver las corridas y cuáles siguen `running`. Solo lectura.
uv run python -m elsa.tools.embeddings_admin runs --status running

# 7. Cerrar a mano una corrida abandonada (ver «Corridas interrumpidas»).
uv run python -m elsa.tools.embeddings_admin reconcile-run \
    --run <uuid> --actor <uuid> --reason "<motivo>" --idle-minutes 30

# 8. Búsqueda de prueba, con alcances explícitos.
uv run python -m elsa.tools.embeddings_admin search "¿cuál es el par de apriete?" \
    --scope mantenimiento:asset-a --limit 5
```

**`generate` no activa y `activate` no genera**, y están separados porque son
decisiones distintas (ADR 0013 §5). Generar deja los vectores nuevos
conviviendo con los del modelo activo; activar cambia cuál responde, en una
sola transacción, sin borrar nada.

`search` exige al menos un `--scope`: sin alcances no se recupera «todo», se
recupera nada.

**Negativas antes de conectar:** `--actor`, `--model`, `--version` y `--run`
tienen que ser UUID. Desde `ELSA_ENV=DEV` no se escribe en una base remota,
que es la de TEST. Ante una configuración inválida, el comando sale con
código 2 y sin traza.

## Ctrl+Z

Detalle completo: [ADR 0039](adr/0039-historial-activaciones-embeddings.md).

| Si hay que deshacer… | Se hace con | Queda |
|---|---|---|
| Una activación, incluida la **primera** | `deactivate` | Ningún modelo activo. El modelo vuelve a `registered`, se conservan sus vectores y puede reactivarse |
| Un cambio de modelo A → B | `activate` de A | A activo; B registrado con sus vectores |
| Un registro equivocado | Nada que deshacer: sin activar es inerte. Se registra el correcto | El registro, inactivo |
| Vectores equivocados | No activar ese modelo | Los vectores, inertes |

**Retirar (`retire`) no es un Ctrl+Z**: es irreversible y la CLI no lo
expone. Cada `activate`, `deactivate`, retirada y conciliación queda en
`elsa.embedding_model_events`, con actor, motivo y `request_id`. Ese historial
no se modifica ni se borra, y `status` muestra las últimas entradas.

## Corridas interrumpidas

- **Una excepción** cierra la corrida como `failed`, con su motivo.
- **Ctrl+C o la cancelación de la tarea** la cierran como `cancelled`.
- Los lotes ya confirmados se conservan, y repetir `generate` los reutiliza.
- **Si el proceso muere** (corte de luz, cierre forzado o la base caída al cerrar), la corrida queda `running`.
  Para cerrarla:
  1. `runs --status running` para identificarla.
  2. Confirmar que **ningún proceso de ELSA** sigue en marcha en PC1.
  3. `reconcile-run` con un motivo.

  La herramienta **se niega** si cualquier sesión de PostgreSQL mantiene todavía la prueba de vida de esa
  corrida, o si escribió algo en los últimos `--idle-minutes` (mínimo 10). La antigüedad sola no basta.
- Después, repetir `generate`, que reutiliza lo confirmado.

## Aplicar la migración del historial en TEST (no autorizado todavía)

`20261108010000_create_embedding_model_events.sql` es obligatoria antes de
cualquier `activate` en TEST: sin ella, la tabla de eventos no existe y la
operación falla entera, sin cambiar el modelo activo. Su aplicación necesita
autorización expresa (regla 15). El procedimiento previsto es el de G-M.1 de
R1.B:

1. **Precondiciones** (solo lectura):
   - `20261108010000` es la única migración pendiente;
   - `elsa.embedding_models` no tiene ningún modelo activo;
   - no hay transacciones abiertas en otras sesiones.
2. **Respaldo:** una instantánea del historial de migraciones y de las restricciones, en una carpeta local fuera
   de OneDrive y con permisos restringidos.
3. **Dry-run:** `supabase db push --dry-run --db-url <…>` tiene que listar **solo** esa migración.
4. **Aplicación:** una única ejecución de `supabase db push`, sin reintentos.
5. **Verificación:**
   - la tabla existe, con RLS, 0 políticas y el disparador append-only;
   - el historial de migraciones tiene una entrada más;
   - nada más cambió.
6. **Rollback:** `supabase/rollback/20261108010000_rollback.sql` y después
   `supabase migration repair --status reverted 20261108010000`. Se niega si ya existe algún evento.
7. **Parada:** ante cualquier diferencia con lo esperado.

## Qué esperar

- **Repetir `generate` no recalcula nada** si el texto compuesto no cambió: la
  idempotencia es por el hash del texto embebido, no por el nombre del chunk.
- Una versión `pending_validation`, `rejected` o `superseded` se niega sin
  abrir corrida.
- La primera llamada carga el modelo y tarda; las siguientes no.

## Qué está probado y qué no

- **Cubierto por las pruebas de CI** (PostgreSQL efímero, datos y modelo sintéticos;
  el resultado de cada ejecución está en el PR que lo introduce):
  - activar, desactivar, reactivar y cambiar de modelo;
  - concurrencia de activación y de desactivación;
  - auditoría atómica e historial append-only;
  - elegibilidad por estado documental;
  - cancelación, conservación e idempotencia de lotes;
  - prueba de vida y conciliación;
  - migración y rollback.
- **No probado:**
  - BGE-M3 real en PC1, incluidos la RAM pico, los tiempos y la carga offline;
  - la migración y cualquier operación en Supabase TEST;
  - la prueba de vida a través del pooler de Supabase.

## Ver también

- [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) — dónde vive el vector; generar no activa
- [ADR 0015](adr/0015-eleccion-del-modelo-de-embeddings.md) — qué modelo y con qué condición
- [ADR 0039](adr/0039-historial-activaciones-embeddings.md) — Ctrl+Z de la activación, historial y corridas abandonadas
- [`environment-variables.md`](environment-variables.md) — el resto de la configuración
