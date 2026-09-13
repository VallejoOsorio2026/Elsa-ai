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

En `.env`, o como variables de entorno. Todas opcionales para arrancar;
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

## Los cinco comandos

```bash
# 1. Registrar la configuración actual como espacio vectorial. NO lo activa.
uv run python -m elsa.tools.embeddings_admin register --actor <uuid>

# 2. Embeber los chunks de una versión documental. NO activa nada.
uv run python -m elsa.tools.embeddings_admin generate \
    --model <uuid> --version <uuid> --actor <uuid>

# 3. Elegir qué modelo responde en la recuperación. Decisión aparte.
uv run python -m elsa.tools.embeddings_admin activate --model <uuid> --actor <uuid>

# 4. Ver qué hay registrado y cuál está activo.
uv run python -m elsa.tools.embeddings_admin status

# 5. Búsqueda de prueba, con alcances explícitos.
uv run python -m elsa.tools.embeddings_admin search "¿cuál es el par de apriete?" \
    --scope mantenimiento:asset-a --limit 5
```

**`generate` no activa y `activate` no genera**, y están separados porque son
decisiones distintas (ADR 0013 §5). Generar deja los vectores nuevos
conviviendo con los del modelo activo; activar cambia cuál responde, en una
sola transacción, sin borrar nada. Volver atrás es activar el anterior otra
vez.

`search` exige al menos un `--scope`: sin alcances no se recupera «todo», se
recupera nada.

## Qué esperar

- **Repetir `generate` no recalcula nada** si el texto compuesto no cambió: la
  idempotencia es por el hash del texto embebido, no por el nombre del chunk.
- Una corrida interrumpida queda `failed` con su motivo, nunca a medias ni
  cerrada como completada, y lo ya escrito sigue sirviendo en el siguiente
  intento.
- La primera llamada carga el modelo y tarda; las siguientes no.

## Ver también

- [ADR 0013](adr/0013-arquitectura-de-almacenamiento-vectorial.md) — dónde vive el vector; generar no activa
- [ADR 0015](adr/0015-eleccion-del-modelo-de-embeddings.md) — qué modelo y con qué condición
- [`environment-variables.md`](environment-variables.md) — el resto de la configuración
