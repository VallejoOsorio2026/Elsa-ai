# Cómo se le da contexto a Claude Code en ELSA

Este documento es para el ingeniero que reciba el proyecto. Explica las cuatro
piezas con las que se configura un asistente de código, cuál usamos para cada
cosa en ELSA y, sobre todo, **por qué la mayoría de las reglas no están
cargadas todo el tiempo**.

No hace falta saber nada de esto para trabajar en ELSA. Hace falta para
ampliarlo sin que el asistente empeore.

---

## 1. El problema que resuelve

Claude Code arranca cada sesión con la ventana de contexto vacía y la llena en
este orden: instrucciones del sistema, definiciones de herramientas, ficheros de
memoria del proyecto, y solo entonces la conversación.

Todo lo que se carga «por si acaso» tiene dos costes:

- **Tokens.** Se pagan en cada petición de la sesión, no una sola vez.
- **Adherencia.** Cuanto más largo el bloque de instrucciones, menos
  consistentemente se siguen. Una regla crítica enterrada en la línea 300 se
  cumple peor que la misma regla en la línea 20. La documentación oficial de
  Claude Code recomienda mantener cada `CLAUDE.md` **por debajo de 200 líneas**
  exactamente por eso.

De ahí el principio de ELSA: **el contrato es corto y estable; el detalle se
carga cuando hace falta.**

---

## 2. Las cuatro piezas

### `CLAUDE.md` — el contrato

Un fichero markdown en la raíz. Claude Code lo lee al empezar **cada** sesión,
siempre, sin que nadie lo pida. Sobrevive a la compactación del contexto.

- **Contiene:** reglas que aplican siempre y que Claude no puede deducir
  leyendo el código. En ELSA: las 25 reglas innegociables, el idioma, el stack.
- **No contiene:** procedimientos paso a paso, listas que se deducen del
  repositorio, ni nada que solo importe en una parte del proyecto.
- **Coste:** permanente. Cada línea se paga en cada petición.

Regla práctica para ELSA: si algo es una **regla** («nunca X», «siempre Y»), va
al contrato. Si es un **procedimiento** («para hacer X, primero…»), va a una
Skill.

### Skills — el procedimiento bajo demanda

Un directorio `.claude/skills/<nombre>/SKILL.md` con cabecera YAML (`name`,
`description`) y un cuerpo en markdown.

Claude lee **solo la descripción** de cada Skill al arrancar — unas pocas
líneas. El cuerpo entra en contexto únicamente cuando la tarea encaja con esa
descripción, o cuando alguien la invoca con `/elsa-migrations`.

Por eso la descripción es la parte más importante del fichero: es el
disparador. Una descripción vaga hace que la Skill no se active cuando toca, o
que se active cuando no toca. Las de ELSA dicen explícitamente **cuándo NO
usarla**, que es lo que evita que se disparen dos a la vez.

- **Contiene:** el procedimiento, la lista de comprobación, los criterios de
  aceptación de un tipo de tarea.
- **No contiene:** copias de `docs/`. Una Skill **apunta** a la documentación;
  duplicarla garantiza que las dos versiones se separen.
- **Coste:** ~1 línea permanente por Skill (su descripción) + el cuerpo solo
  cuando se usa.

Skills de ELSA: `elsa-block-planning`, `elsa-migrations`, `elsa-ingestion`,
`elsa-testing`, `elsa-ui-acceptance`, `elsa-release`.

### Subagentes — el trabajo aislado

Un fichero `.claude/agents/<nombre>.md`. Define un asistente **con su propia
ventana de contexto**, que recibe una tarea, la ejecuta y devuelve solo su
conclusión.

Lo que gana no es velocidad: es **aislamiento**. Una revisión de seguridad
completa lee decenas de ficheros; si eso ocurre en la conversación principal,
esos ficheros se quedan ahí ocupando sitio durante el resto de la sesión. En un
subagente, lo que vuelve es el dictamen.

- **Se usa para:** revisiones al cerrar un cambio, búsquedas amplias, cualquier
  cosa cuyo *proceso* sea largo y cuyo *resultado* sea corto.
- **No se usa para:** tareas triviales, ni nada donde haga falta seguir
  iterando sobre lo que el subagente vio. Arranca en frío: no conoce la
  conversación. Un subagente para algo que se resuelve leyendo dos ficheros
  cuesta más de lo que ahorra.
- **Coste:** cero mientras no se invoca.

Subagentes de ELSA: `architecture-reviewer`, `security-reviewer`,
`rag-quality-reviewer`. Los tres son de **solo lectura**: revisan y dictaminan,
no editan.

### MCP — el acceso al exterior

Model Context Protocol: un servidor que expone herramientas a Claude para
hablar con un sistema externo (una base de datos, GitHub, un navegador).

Un MCP conectado carga la definición de **todas** sus herramientas en cada
petición, esté usándolas o no. Un servidor con 40 herramientas es un coste
permanente considerable. Además, todo lo que devuelve entra al contexto y puede
contener texto escrito por terceros.

- **Se usa para:** acceso real a un sistema externo que no se puede resolver
  con la CLI que ya está instalada.
- **No se usa para:** nada que `git`, `uv`, `pytest` o `supabase` ya hagan
  desde la terminal.
- **Coste:** permanente y proporcional al número de herramientas.

Política completa y obligatoria: [`MCP_POLICY.md`](MCP_POLICY.md).
Evaluación de los candidatos externos: [`EXTERNAL_TOOLS_EVALUATION.md`](EXTERNAL_TOOLS_EVALUATION.md).

---

## 3. Cómo elegir

| Lo que quieres | Pieza | Por qué |
|---|---|---|
| «Nunca hagas X» en todo el proyecto | `CLAUDE.md` | Debe estar siempre presente |
| «Para hacer X, sigue estos pasos» | Skill | Solo importa cuando se hace X |
| «Revisa esto contra N criterios» | Subagente | Proceso largo, resultado corto |
| «Consulta el sistema Z» | MCP | Solo si la CLI no llega |
| «Esto solo aplica a ficheros de tipo T» | `.claude/rules/` con `paths:` | Se carga solo al tocar esos ficheros |

La última fila es un mecanismo oficial que **ELSA todavía no usa, y no debe
usar todavía**. Se deja apuntado porque es la salida natural si el contrato
vuelve a crecer: una regla que solo importa dentro de `supabase/migrations/`
podría vivir en `.claude/rules/migrations.md` con `paths: ["supabase/**"]` y no
ocupar contexto el resto del tiempo.

**Condición para implementarlo.** No se hace por elegancia. Se hace solo si se
observa un problema real y concreto, de uno de estos dos tipos:

- *Activación:* una Skill no se dispara cuando debía, o se dispara cuando no
  debía, de forma repetida — y la causa es que la regla debería estar cargada
  al tocar cierto tipo de fichero, no al invocar una Skill.
- *Contexto:* el contrato vuelve a acercarse a las 200 líneas porque hay reglas
  que solo importan en una parte del repositorio.

Sin una de las dos observaciones, añadir un tercer mecanismo es complejidad sin
beneficio y contradice la regla 23 del contrato.

---

## 4. Cómo se añade una capacidad nueva sin inflar el contexto

1. **Pregunta primero si hace falta.** La mayoría de las veces la respuesta es
   una frase en la Skill que ya existe, no una Skill nueva. Diez Skills
   solapadas son peores que cinco precisas: compiten entre sí por activarse.
2. **Escribe la descripción antes que el cuerpo.** Si no puedes decir en dos
   frases cuándo se activa y cuándo no, la Skill no está bien delimitada.
3. **Apunta, no copies.** Si la información ya está en `docs/`, enlázala.
4. **Mide.** Antes y después: líneas del contrato, número de Skills, número de
   herramientas MCP cargadas. Lo que no se mide, crece.
5. **Pruébala.** Una Skill que nunca se dispara sola es decorativa. El método
   de comprobación está en [`UTILITY_EVALUATION.md`](UTILITY_EVALUATION.md).
6. **Regístralo.** Si cambia cómo se trabaja, es una decisión: ADR en
   `docs/adr/`.

---

## 5. Qué NO hacemos, y por qué

- **Un `CLAUDE.md` gigantesco.** Pierde adherencia y se paga siempre.
- **Decenas de Skills.** Cada descripción es coste permanente y aumentan las
  colisiones de activación.
- **Subagentes automáticos en cada tarea.** Arrancan en frío y vuelven a
  deducir contexto que la conversación principal ya tenía.
- **MCPs cargados «por si acaso».** Coste permanente y superficie de ataque.
- **Copiar repositorios externos completos** dentro de este. Se evalúa, se
  documenta y se enlaza; no se vendorea.

---

## 6. Referencias

Documentación oficial de Claude Code, verificada al construir esta estructura:

- Skills: <https://code.claude.com/docs/en/skills>
- Subagentes: <https://code.claude.com/docs/en/sub-agents>
- Memoria y `CLAUDE.md`: <https://code.claude.com/docs/en/memory>
- MCP: <https://code.claude.com/docs/en/mcp>
