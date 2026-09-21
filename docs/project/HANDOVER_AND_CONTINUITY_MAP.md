# Mapa de entrega y continuidad de ELSA

Qué hace falta para que otra persona pueda recibir, operar y continuar este
proyecto sin acceso a las conversaciones que lo produjeron.

- Fecha de corte: **2026-09-21**
- Revisión de referencia: `origin/main` = `2425c8ae`
- Documento hermano: [Historia técnica y estado actual](PROJECT_HISTORY_AND_CURRENT_STATE.md)
- Aplica las reglas **11, 12, 15, 17, 21, 22 y 24** de [`CLAUDE.md`](../../CLAUDE.md)

---

## 1. Objetivo

**El proyecto será entregado a PAPELSA.** Esa frase ya está en el contrato del
proyecto, pero hasta hoy no tenía detrás ningún inventario de qué habría que
entregar, ni a quién, ni en qué orden.

Este documento es ese inventario. Registra:

- qué sistemas componen el proyecto y quién puede hoy acceder a cada uno;
- qué credenciales existen, **por nombre y tipo, nunca por valor**;
- qué depende de una máquina concreta (PC1) y qué no;
- qué depende del administrador actual como **persona**, y no como **rol**;
- el procedimiento por el que una transferencia futura podría ejecutarse.

### 1.1 Qué este documento NO hace

- **No transfiere nada.** No rota credenciales, no crea cuentas, no revoca
  accesos, no nombra sucesores.
- **No contiene secretos.** Ningún valor, ni siquiera parcial (§8).
- **No publica identidades.** No registra correos corporativos ni nombres.
- **No corrige las deudas que documenta.** Registrar un riesgo aquí no lo
  mitiga.

### 1.2 Estado de este documento

Es un **esqueleto inicial**, no un acta de entrega. Muchas casillas dicen
`NO DETERMINADO` porque hoy no hay evidencia que las llene. Eso es correcto:
un `NO DETERMINADO` honesto es continuidad; un nombre inventado es un fallo de
auditoría.

---

## 2. Principios de continuidad

> ```text
> Ningún componente debe depender permanentemente de una persona.
> Los roles permanecen; los ocupantes, credenciales, cuentas y rutas
> se sustituyen.
> ```

De este principio central se derivan seis reglas operativas.

### 2.1 Mínimo privilegio

Cada rol recibe el acceso que su función exige y **nada más**. Un sucesor no
hereda automáticamente todos los accesos del predecesor: hereda los de su rol.
Los accesos que el predecesor tenía por acumulación histórica se revisan, no se
copian.

### 2.2 Secretos fuera de Git

Ningún secreto vive en el repositorio ni en el frontend (regla 11). `.env` está
en `.gitignore`; `.env.example` lleva las claves **sin valores**. El escaneo de
secretos es automático (pre-commit + CI con `gitleaks`), no una revisión
manual. Una entrega **no** se hace enviando un `.env` por correo o por chat.

### 2.3 Roles separados de personas

Este documento nombra **roles** («administrador del proyecto», «Contract
Owner», «operador de PC1»), no personas. La asignación de ocupantes vive donde
corresponda —para el Contract Owner, en el repositorio de Materiales, según
[ADR 0026](../adr/0026-gobernanza-y-cierre-de-m7.md)— y se actualiza allí, no
aquí.

### 2.4 Una fuente de verdad

GitHub es la fuente de verdad del código y de la documentación (regla 17). Lo
que no está commiteado y empujado **no existe**. Una entrega que dependa de
archivos en el escritorio de alguien no es una entrega.

### 2.5 Transferencia antes de revocación

El acceso del sucesor se crea y se **prueba** antes de retirar el del
predecesor. El orden inverso produce sistemas a los que nadie puede entrar.

### 2.6 Prueba antes de retirar el acceso anterior

Corolario del anterior, y lo bastante importante para enunciarlo aparte: la
revocación es el **último** paso de cada componente, nunca el primero, y solo
ocurre después de que la lista de aceptación de §12 pase para ese componente.

---

## 3. ELSA

| Componente | Qué es | Depende de | Estado de continuidad |
|---|---|---|---|
| **GitHub** | Repositorio `VallejoOsorio2026/Elsa-ai`. Fuente de verdad | Cuenta/organización GitHub | **Transferible.** Requiere que exista más de un propietario u organización |
| **Ejecución** | Servidor FastAPI. `uv run` según [`README.md`](../../README.md) | Python 3.12 (`.python-version`), `uv`, `uv.lock` | **Reproducible.** Criterio de aceptación permanente (regla 24) |
| **`.env`** | Configuración local. **Nunca** en Git | `.env.example` como plantilla | **Documentado.** Los nombres están versionados; los valores no (§8) |
| **Supabase** | Proyecto **independiente** del de Materiales. Ambientes lógicos DEV y TEST en proyectos distintos (regla 8) | Cuenta Supabase, credencial de servicio | **Parcial.** Ver riesgo R2 |
| **Migraciones** | 5 migraciones versionadas en `supabase/migrations/`. Ni Alembic, ni ORM, ni cambios a mano en el dashboard (ADR 0001) | Supabase CLI | **Reproducible.** Toda la estructura se recrea desde Git |
| **CI** | GitHub Actions, `.github/workflows/ci.yml`. Dos jobs: *Lint, types and tests* y *Secret scan (gitleaks)* | GitHub | **Transferible con el repositorio** |
| **Render** | Blueprint `render.yaml`. Despliega **solo** la interfaz; en plan Free **no** puede cargar un modelo (ADR 0013 §8) | Cuenta Render vinculada a GitHub | **Parcial.** Ver riesgo R3 |
| **Modelo** | Phi-4-mini-instruct GGUF Q4_K_M. **Fuera de Git** (regla 12) | PC1, `ELSA_LLM_MODEL_PATH` | **Frágil.** Sin hash ni tamaño versionados. Riesgo R1 |
| **`llama.cpp`** | `llama-server` build `b10938` (`f1e44dcc1`), backend Vulkan, dispositivo `Vulkan0` | PC1, GPU con 4 GB VRAM | **Frágil.** Binario fuera de Git; versión exacta en PC1 no verificada |
| **RAG** | Implementado completo en `src/elsa/`. Ver [Historia §7](PROJECT_HISTORY_AND_CURRENT_STATE.md#7-rag) | Código versionado | **Transferible.** Todo está en Git |
| **CLI** | Cinco herramientas en `src/elsa/tools/`. Ver [Historia §8](PROJECT_HISTORY_AND_CURRENT_STATE.md#8-cli) | Código versionado; PC1 para las que cargan pesos | **Transferible** |
| **Logs** | Cada request lleva un identificador propagado a los logs (regla 14). Runtime local escribe en `%LOCALAPPDATA%\ELSA\llm` | PC1 para los del runtime | **Parcial.** No hay agregación centralizada. Riesgo R6 |
| **Rama ONNX** | `claude/keen-curie-2xeh0r`, commit `61b3b42`, ~3064 líneas, sin PR, sin merge | GitHub | **Preservada.** Su destino exige un ADR (Historia §11) |

### 3.1 Lo que un sucesor puede hacer solo con GitHub

Clonar, instalar dependencias, levantar el servidor, pasar los tests y leer
toda la documentación y los ADR. Esto es el criterio de aceptación permanente
del proyecto (regla 24) y **no** depende de ningún acceso heredado.

### 3.2 Lo que un sucesor NO puede hacer solo con GitHub

Ejecutar el modelo, medir rendimiento real, aplicar migraciones a un proyecto
Supabase remoto, desplegar en Render, o consultar inventario real de
Materiales. Todo eso exige credenciales o una máquina, y por eso existe el
resto de este documento.

---

## 4. Materiales

**No se modifica desde este repositorio** (regla 15 y §12.2 de la Historia).
Este apartado mapea la dependencia, no la gestiona.

| Componente | Qué es | Estado de continuidad |
|---|---|---|
| **GitHub** | Repositorio `VallejoOsorio2026/papelsa-asistente-materiales`. Revisión conocida: `436eab92` (`DECLARADO_POR_USUARIO`) | **NO DETERMINADO** desde ELSA |
| **Supabase** | Proyecto **propio** de Materiales, distinto del de ELSA (regla 5) | **NO DETERMINADO** desde ELSA |
| **Rol técnico `admin`** | Rol de base de datos de Materiales usado por los flujos administrativos | **Dependencia demostrada** del administrador actual. Riesgo R4 |
| **Contract Owner** | Rol de gobernanza del contrato de inventario. Autoridad exclusiva para aprobar rupturas. Materializado en el repositorio de Materiales | **Rol definido, ocupante asignado** ([ADR 0026](../adr/0026-gobernanza-y-cierre-de-m7.md)). ELSA **no** registra nombre ni contacto |
| **Contrato Materiales–ELSA** | `docs/contrato-elsa.md`, en Materiales. Definición canónica, `contract_version` y descriptor | **M1 abierto.** La definición canónica versionada sigue siendo trabajo pendiente en Materiales |
| **Inventario** | ~65.000 registros. Materiales sigue siendo su propietario; ELSA **no** los duplica (regla 4) | **Por contrato.** No hay copia que transferir |
| **Dominio** | La semántica de los campos de inventario | **M6 decidido normativamente** ([ADR 0025](../adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md)); implementación y verificación pendientes |

### 4.1 Nota sobre identidad

La identidad de usuario proviene de **Supabase Auth del proyecto Materiales**;
FastAPI valida ese JWT y aplica los permisos propios de ELSA con credencial de
servicio. **RLS no es el mecanismo de autorización de ELSA**
([ADR 0002](../adr/0002-identidad-de-materiales-autorizacion-en-backend.md)).

Consecuencia de continuidad: **ELSA no puede autenticar a nadie si el proyecto
Supabase de Materiales deja de estar accesible.** Esa es la dependencia cruzada
más fuerte entre ambos streams.

---

## 5. SAP/ZIAA

`DECLARADO_POR_USUARIO` en su totalidad. **Nada de este apartado vive en este
repositorio**, y nada de él está automatizado extremo a extremo.

| Componente | Qué es | Estado de continuidad |
|---|---|---|
| **Cuenta SAP** | Acceso nominal al sistema SAP de PAPELSA | **NO DETERMINADO.** Dependencia de persona, no de rol. Riesgo R5 |
| **Permisos** | Autorización para ejecutar la transacción **ZIAA** | **NO DETERMINADO** |
| **Macro** | Macro de extracción que automatiza la corrida de ZIAA | **NO DETERMINADO.** Ubicación, versión y custodia sin registrar |
| **Selección de centros** | Los centros incluidos en cada extracción | **Parcialmente documentado.** Ver PENDIENTE-019 |
| **Extracción** | Corrida de ZIAA que produce el *snapshot* | **Manual** |
| **Transformación** | Conversión del *snapshot* a un formato consumible | **Manual** |
| **Carga** | Entrada del *snapshot* `.htm` a la ingesta de ELSA | **Implementada** en ELSA (`private_acceptance`, `structured_text_extractor`) |

### 5.1 Pendiente registrado

```text
PENDIENTE-019:
P210/Bogotá ausente desde la carga documentada del 2026-09-10.
```

**Clasificación:** `DECLARADO_POR_USUARIO`. No existe en este repositorio
ningún artefacto que registre ni la presencia ni la ausencia de P210/Bogotá;
la búsqueda de «P210» y «Bogotá» en `docs/` no devuelve ninguna coincidencia.

**Este documento lo registra y no lo resuelve.** Resolverlo exige acceso a SAP
y a la carga original, ambos fuera del alcance de este bloque.

### 5.2 Lo que un sucesor necesitaría

Para reproducir la extracción, un sucesor necesita: cuenta SAP con permiso para
ZIAA, la macro, el criterio de selección de centros y la definición de qué
transformación se aplica. **Hoy, tres de esos cuatro elementos son
`NO DETERMINADO`.** Es el punto más débil del proyecto en materia de
continuidad.

---

## 6. Infraestructura local

**PC1** es la máquina Windows del administrador actual. Es hoy el único entorno
donde se han ejecutado el modelo de generación, los modelos de embeddings y las
pruebas contra Materiales real.

| Componente | Detalle | Estado |
|---|---|---|
| **PC1** | Windows. CPU AMD64 Family 23 Model 17. GPU Radeon RX 570 con **4 GB VRAM** | **Dependencia de máquina.** Riesgo R1 |
| **Python** | 3.12.13, fijado por `.python-version` | **Reproducible** |
| **`uv`** | Gestor de dependencias. `pyproject.toml` + `uv.lock` | **Reproducible** |
| **Herramientas** | Ruff, mypy, pytest, pre-commit, gitleaks | **Reproducibles** desde `uv.lock` y `.pre-commit-config.yaml` |
| **PostgreSQL** | Requerido por las pruebas que tocan base y por la CLI `ask` | **Reproducible** |
| **Supabase CLI** | Única vía admitida para migraciones (ADR 0001) | **Reproducible** |
| **GGUF** | Phi-4-mini-instruct Q4_K_M. **Fuera de Git** (regla 12) | **Frágil.** Sin hash ni tamaño versionados |
| **`llama-server`** | Build `b10938` (`f1e44dcc1`), Vulkan, `Vulkan0`. Binario **fuera de Git** | **Frágil.** Versión presente hoy en PC1 no verificada |
| **Rutas** | Ver §9 | **Documentadas** |
| **`%LOCALAPPDATA%\ELSA\llm`** | Directorio de runtime: PID y log del servidor, usado por los scripts PowerShell | **Reproducible.** Se crea solo |
| **Almacenamiento de artefactos** | `ELSA_ARTIFACT_STORAGE_ROOT`, backend elegido por `ELSA_ARTIFACT_STORAGE_BACKEND` | **Configurable.** Contenido **fuera de Git** |

### 6.1 Qué se pierde si PC1 desaparece

- El binario `llama-server` en la versión exacta validada.
- El archivo GGUF en la copia exacta usada (sin hash, es irrepetible con
  certeza).
- Los pesos de los modelos de embeddings descargados.
- Cualquier medición no versionada
  ([Historia §15](PROJECT_HISTORY_AND_CURRENT_STATE.md#15-evidencia-faltante)).

### 6.2 Qué NO se pierde

Todo el código, toda la documentación, los 26 ADR, las 5 migraciones y los
artefactos del banco de embeddings en `bench/resultados/`. Un sucesor puede
reconstruir el entorno; lo que no puede es reconstruir las mediciones perdidas
sin volver a medir.

---

## 7. Cuentas y accesos

**Sin secretos.** Esta tabla registra **qué rol hace falta**, no quién lo tiene
ni con qué clave.

`NO DETERMINADO` significa que no existe evidencia en este repositorio. No
significa que no exista el acceso.

| Sistema | Rol/cuenta requerida | Propietario actual | Sucesor | Método de transferencia | Estado |
|---|---|---|---|---|---|
| GitHub — `Elsa-ai` | Propietario del repositorio / de la organización | Administrador actual | NO DETERMINADO | Añadir propietario u organización; transferir repositorio | **Pendiente** |
| GitHub — `papelsa-asistente-materiales` | Propietario del repositorio | Administrador actual | NO DETERMINADO | Igual que arriba, **desde Materiales** | **Pendiente** |
| GitHub Actions | Se hereda con el repositorio | — | — | Automática | **Cubierto** |
| Supabase ELSA — DEV | Propietario del proyecto | Administrador actual | NO DETERMINADO | Invitar como miembro; transferir propiedad | **Pendiente** |
| Supabase ELSA — TEST | Propietario del proyecto | Administrador actual | NO DETERMINADO | Igual que DEV | **Pendiente** |
| Supabase Materiales | Propietario del proyecto | NO DETERMINADO | NO DETERMINADO | **Fuera del alcance de ELSA** | **Pendiente** |
| Materiales — rol técnico `admin` | Rol de base de datos | Administrador actual | NO DETERMINADO | Crear rol equivalente; probar; revocar anterior | **Pendiente** |
| Materiales — Contract Owner | Rol de gobernanza | Asignado en Materiales ([ADR 0026](../adr/0026-gobernanza-y-cierre-de-m7.md)) | NO DETERMINADO | Actualizar la asignación **en Materiales** | **Asignado; sucesión pendiente** |
| Render | Propietario del servicio, vinculado a GitHub | Administrador actual | NO DETERMINADO | Invitar a equipo; transferir servicio | **Pendiente** |
| SAP | Usuario nominal con permiso para **ZIAA** | Administrador actual | NO DETERMINADO | Solicitud formal a TI de PAPELSA | **Pendiente** |
| PC1 | Operador de la máquina | Administrador actual | NO DETERMINADO | Recrear el entorno en otra máquina (§11 FASE 3) | **Pendiente** |
| HuggingFace | Cuenta con aceptación de los *gated repos* (EmbeddingGemma) | Administrador actual | NO DETERMINADO | Cuenta propia del sucesor; `HF_TOKEN` en entorno | **Pendiente** |

> **Los correos corporativos no se registran aquí** ni en ningún otro documento
> versionado de ELSA. La identificación de personas vive en los sistemas de
> PAPELSA, no en este repositorio.

---

## 8. Credenciales

**Solo nombres y tipos. Ningún valor, ni completo ni parcial.**

| Nombre | Tipo | Servicio | Dónde se configura |
|---|---|---|---|
| `ELSA_DATABASE_URL` | Cadena de conexión | Supabase / PostgreSQL de ELSA | `.env` local; variable de entorno en el servicio desplegado |
| `ELSA_AUTH_JWT_SECRET` | Secreto simétrico | Validación de JWT | `.env` local; variable de entorno |
| `ELSA_AUTH_JWKS_URL` | URL pública | Supabase Auth de Materiales | `.env`; **no es secreto**, pero identifica el proyecto |
| `ELSA_BOOTSTRAP_ADMIN_TOKEN` | Token de arranque | Alta del primer administrador de ELSA | `.env` local; **se retira tras el arranque** |
| `ELSA_MATERIALS_API_KEY` | Clave de API | Materiales | `.env` local; variable de entorno |
| `ELSA_MATERIALS_SUPABASE_URL` | URL | Supabase de Materiales | `.env`; **no es secreto** |
| Credencial de servicio de Supabase (ELSA) | Clave de servicio | Supabase | Panel de Supabase → variables de entorno. **Nunca** en el frontend |
| Token de GitHub | PAT o credencial de App | GitHub | Configuración de la cuenta/organización |
| Credencial de Render | Sesión / vinculación con GitHub | Render | Panel de Render |
| Credencial SAP | Usuario y contraseña nominales | SAP de PAPELSA | Gestionada por TI de PAPELSA. **Fuera de ELSA** |
| `HF_TOKEN` | Token de HuggingFace | HuggingFace | Variable de entorno estándar. **Nunca** por argumento de línea de comandos |

La lista completa de variables de configuración —secretas y no secretas— está
en [`.env.example`](../../.env.example) y documentada en
[`docs/environment-variables.md`](../environment-variables.md).

### 8.1 Procedimiento de sustitución

**Para cada credencial, sin excepción:**

```text
crear acceso sucesor
    → probar
        → rotar/revocar acceso anterior
```

Los tres pasos, en ese orden. Nunca revocar primero (§2.5, §2.6). Y «probar»
significa ejecutar la prueba de aceptación correspondiente de §12, no
simplemente iniciar sesión.

### 8.2 Qué hacer si una credencial se filtra

Fuera del procedimiento ordenado de arriba: rotar **inmediatamente**, sin
esperar al sucesor, y revisar el historial de Git con `gitleaks` sobre el
historial completo (es lo que hace el job de CI). Una fuga es la única
situación en que revocar primero es correcto.

---

## 9. Rutas locales

| Ruta / variable | Qué es | Clasificación |
|---|---|---|
| `ELSA_LLM_MODEL_PATH` | Ruta absoluta al archivo GGUF en la máquina que sirve el modelo | **Activa.** Específica de cada máquina |
| `ELSA_LLAMA_SERVER_PATH` | Ruta absoluta al binario `llama-server` | **Activa.** Específica de cada máquina |
| `%LOCALAPPDATA%\ELSA\llm` | Directorio de runtime: PID y log de `llama-server`. Usado por `Start-ElsaLlm.ps1`, `Stop-ElsaLlm.ps1` y `Test-ElsaLlm.ps1` | **Activa.** Se crea sola; no requiere configuración |
| `ELSA_ARTIFACT_STORAGE_ROOT` | Raíz del almacenamiento de artefactos originales y planos | **Activa.** Contenido **fuera de Git** (regla 12) |

### 9.1 Ruta histórica

En [`docs/postgres-documents-4-1b.md`](../postgres-documents-4-1b.md), línea
296, aparece:

```text
C:/Users/juanp/.cache/pre-commit/repo3x7oavce/golangenv-default/bin/gitleaks.exe
```

Clasificación:

```text
HISTORICA
BAJO RIESGO
NO FUNCIONAL
PENDIENTE DE LIMPIEZA DOCUMENTAL
```

Razón de cada etiqueta:

- **HISTORICA** — es la transcripción de una salida de consola de aquel
  bloque, no una instrucción a ejecutar.
- **BAJO RIESGO** — revela un nombre de usuario local de Windows y la ruta de
  una caché de `pre-commit`. No es un secreto, no da acceso a nada y no
  identifica una cuenta corporativa.
- **NO FUNCIONAL** — el hash del directorio de caché (`repo3x7oavce`) es
  específico de aquella instalación; la ruta no existe en ninguna otra máquina
  ni, muy probablemente, en la misma tras reinstalar `pre-commit`.
- **PENDIENTE DE LIMPIEZA DOCUMENTAL** — debería sustituirse por `gitleaks` a
  secas o por una ruta genérica, en un bloque posterior.

**Es la única ruta personal admitida en la documentación de ELSA**, y se admite
únicamente acompañada de esta clasificación. Cualquier otra ruta personal que
aparezca en el futuro debe eliminarse, no clasificarse.

**Este documento no la corrige.** Corregirla modificaría un tercer archivo, lo
que está fuera del alcance de este bloque.

---

## 10. Riesgos de continuidad

| ID | Riesgo | Prioridad | Por qué |
|---|---|---|---|
| **R1** | **PC1 es un punto único de fallo.** Es la única máquina donde se han ejecutado el modelo, los embeddings y las pruebas contra Materiales real. El GGUF no tiene hash ni tamaño versionados | **ALTO** | Si PC1 desaparece, el proyecto no puede demostrar que reproduce sus propias mediciones |
| **R2** | **Los proyectos Supabase de ELSA (DEV y TEST) dependen de una cuenta personal.** No hay copropietario registrado | **ALTO** | Pérdida de acceso a la base de datos de ambos ambientes |
| **R3** | **El despliegue en Render depende de una cuenta personal vinculada a GitHub** | **MEDIO** | El blueprint `render.yaml` está versionado, así que el servicio se puede recrear; se pierde continuidad, no capacidad |
| **R4** | **El rol técnico `admin` de Materiales depende hoy del administrador actual** | **ALTO** | Dependencia cruzada entre streams; afecta a la identidad de usuarios de ELSA (§4.1) |
| **R5** | **El acceso a SAP y la macro de ZIAA son nominales y no están documentados** | **ALTO** | Tres de los cuatro elementos necesarios para reproducir la extracción son `NO DETERMINADO` (§5.2) |
| **R6** | **No hay agregación centralizada de logs.** Los del runtime local viven en `%LOCALAPPDATA%\ELSA\llm` | **BAJO** | Dificulta el diagnóstico posterior, no la operación |
| **R7** | **Mediciones históricas no recuperadas.** Prompts, corpus comparativo y línea base de nueve métricas se perdieron ([Historia §15](PROJECT_HISTORY_AND_CURRENT_STATE.md#15-evidencia-faltante)) | **MEDIO** | Obliga a volver a medir antes de cualquier comparación futura |
| **R8** | **La rama ONNX (~3064 líneas) no está integrada y su base tiene 16 PR de antigüedad** | **MEDIO** | Cuanto más se retrase la decisión, más caro será aplicarla o descartarla |
| **R9** | **M1 sigue abierto y bloqueante.** La definición canónica del contrato vive en Materiales y aún no está versionada allí. **M1-A no lo cierra**: dejó lista la especificación ejecutable del consumidor, no el proveedor | **ALTO** | Bloquea la fachada, y con ella el cierre operacional de M4 y M6 |
| **R10** | **El sucesor no está determinado** para ningún sistema (§7) | **ALTO** | Sin sucesor designado, ninguna fase de §11 puede iniciarse |

---

## 11. Procedimiento futuro de entrega

**Esqueleto. No se ejecuta nada en este bloque.** Cada fase termina con la
parte correspondiente de la lista de aceptación de §12 en verde; ninguna fase
empieza antes de que la anterior haya cerrado.

### FASE 1 — Preparar al sucesor

Designar a la persona. Darle acceso de **lectura** a ambos repositorios. Que
lea, en este orden: [`README.md`](../../README.md),
[`CLAUDE.md`](../../CLAUDE.md), [`docs/architecture.md`](../architecture.md),
la [Historia técnica](PROJECT_HISTORY_AND_CURRENT_STATE.md) y este documento.
Ningún acceso de escritura todavía.

### FASE 2 — Transferir accesos

Para cada fila de §7, **crear** el acceso del sucesor. Sin revocar nada. El
predecesor conserva todos sus accesos durante todas las fases restantes.

### FASE 3 — Recrear entorno

El sucesor recrea el entorno desde cero en su propia máquina: clon limpio,
Python 3.12, `uv sync`, PostgreSQL, Supabase CLI, `pre-commit install`.
Descarga del GGUF y del binario `llama-server` en la versión de referencia
(`b10938`, `f1e44dcc1`).

> **Oportunidad:** es el momento de cerrar el hueco de
> [Historia §5.1](PROJECT_HISTORY_AND_CURRENT_STATE.md#51-huecos-de-evidencia-del-modelo).
> Medir y versionar el hash y el tamaño del GGUF durante esta fase elimina R1
> para siempre.

### FASE 4 — Validar ELSA

Servidor arriba, CI verde, `llama-server` arriba, prueba local del modelo, RAG
usable por CLI. §12, filas 1–9.

### FASE 5 — Validar Materiales

Acceso al repositorio y al proyecto Supabase de Materiales. Nuevo rol técnico
`admin` funcional. Asignación del Contract Owner actualizada **en Materiales**.
§12, filas 10–12.

### FASE 6 — Validar SAP/ZIAA

Acceso a SAP con permiso para ZIAA. Extracción reproducida por el sucesor.
§12, filas 13–14.

### FASE 7 — Rotar/revocar credenciales anteriores

**Solo ahora.** Componente por componente, y únicamente donde la fila
correspondiente de §12 esté en verde. Un componente sin validar conserva el
acceso del predecesor.

### FASE 8 — Acta de entrega

Documento versionado que registre: qué se transfirió, qué se validó, qué se
revocó y con qué fecha; qué quedó `NO DETERMINADO`; y qué deudas se heredan.
Redactado según [`BLOCK_CLOSURE_STANDARD.md`](BLOCK_CLOSURE_STANDARD.md) en lo
que aplique (regla 26).

---

## 12. Pruebas de aceptación de futura entrega

Cada fila se ejecuta **por el sucesor**, en su máquina, sin ayuda del
predecesor. Que funcione «cuando lo hacemos juntos» no cuenta.

| # | Prueba | Fase | Criterio |
|---|---|---|---|
| 1 | El sucesor clona ambos repositorios | 1 | Clon completo con su propia credencial |
| 2 | CI en verde | 4 | Los dos jobs de `ci.yml` pasan sobre una rama del sucesor |
| 3 | Entorno Python reproducible | 3 | `uv sync` desde `uv.lock` sin errores, con Python 3.12 |
| 4 | El servidor ELSA arranca | 4 | Siguiendo **únicamente** el `README.md` (regla 24) |
| 5 | Los tests pasan localmente | 4 | `pytest`, `ruff check`, `ruff format --check`, `mypy` |
| 6 | `llama-server` arranca | 4 | `Start-ElsaLlm.ps1`; `Vulkan0` visible en el log |
| 7 | El GGUF es el correcto | 4 | Hash y tamaño coinciden con lo versionado en FASE 3 |
| 8 | Prueba local del modelo | 4 | `elsa.tools.llm_runtime health` y `generate` responden |
| 9 | RAG usable | 4 | `elsa.tools.llm_runtime demo` y, con corpus, `ask` |
| 10 | Materiales accesible | 5 | Clon y acceso al proyecto Supabase de Materiales |
| 11 | Nuevo `admin` funcional | 5 | El rol técnico del sucesor ejecuta lo que ejecutaba el anterior |
| 12 | Contract Owner actualizado | 5 | La asignación **en Materiales** nombra al sucesor |
| 13 | SAP accesible | 6 | Inicio de sesión y acceso a la transacción ZIAA |
| 14 | Extracción ZIAA reproducible | 6 | El sucesor produce un *snapshot* equivalente, solo |
| 15 | **Credenciales anteriores revocadas** | 7 | **Únicamente** después de que las filas 1–14 aplicables estén en verde |

> La fila 15 es la última por diseño. Si alguna fila anterior falla, la
> revocación de ese componente **no** se ejecuta (§2.5, §2.6).

---

## 13. Pendientes conocidos

Lo que este documento **no** pudo determinar, y que una entrega real tendría
que resolver antes de empezar.

### 13.1 Continuidad

| # | Pendiente |
|---|---|
| C1 | **No hay sucesor designado** para ningún sistema (§7) |
| C2 | **No hay copropietario** de los proyectos Supabase de ELSA (DEV y TEST) |
| C3 | **No hay copropietario** del servicio de Render |
| C4 | El método formal de transferencia de cada acceso está enunciado, **no acordado con TI de PAPELSA** |
| C5 | **No existe acta de entrega**, ni plantilla para ella |
| C6 | La propiedad de los repositorios GitHub no está en una organización con más de un propietario |

### 13.2 PC1

| # | Pendiente |
|---|---|
| P1 | Hash y tamaño del GGUF: `NO_RECUPERADO` |
| P2 | Versión exacta del `llama-server` presente hoy en la máquina: sin verificar |
| P3 | No existe copia ni respaldo de los pesos fuera de PC1 |
| P4 | Ninguna otra máquina ha reproducido jamás las mediciones |

### 13.3 SAP/ZIAA

| # | Pendiente |
|---|---|
| S1 | Ubicación, versión y custodia de la macro de extracción |
| S2 | Criterio documentado de selección de centros |
| S3 | Definición de la transformación aplicada al *snapshot* |
| S4 | **PENDIENTE-019** — P210/Bogotá ausente desde la carga del 2026-09-10 (§5.1) |
| S5 | Procedimiento formal para que TI de PAPELSA conceda el permiso de ZIAA a un sucesor |

### 13.4 Materiales

| # | Pendiente |
|---|---|
| T1 | **M1 abierto:** definición canónica versionada del contrato, `contract_version` y descriptor, **en el repositorio de Materiales**. El lado consumidor ya está hecho: **M1-A cerrado** ([ADR 0028](../adr/0028-forma-del-resultado-contractual-del-puerto-de-materiales.md), [cierre M1-A](../bloque-5-0-m1-a-contrato-consumidor-cierre.md)) dejó el contrato esperado ejecutable y probado en ELSA, y eliminó la deuda `Material | None` |
| T2 | **M4 operativo abierto:** transporte y consumo de la metadata de versión y fecha del inventario activo. **M4-NORMATIVO está cerrado** por [ADR 0027](../adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md) y su [documento de cierre](../bloque-5-0-m4-normativo-cierre.md); la semántica de `null` ya no es una decisión pendiente |
| T3 | **M6:** implementación y verificación de la semántica decidida en ADR 0025 |
| T4 | **M8 abierto, no bloqueante:** el criterio de cierre de ADR 0021 §8.3 sigue intacto y sin cumplir |
| T5 | La **fachada Materiales–ELSA no existe** y no está solicitada. Quedan pendientes las dos decisiones humanas que la gobiernan: **H3** (enlace de transporte) y **H5** (autorización para modificar el repositorio de Materiales) |

### 13.5 Trabajo técnico futuro

| # | Pendiente |
|---|---|
| F1 | Decidir el destino de la rama ONNX `claude/keen-curie-2xeh0r` mediante un ADR (regla 25) |
| F2 | Exponer el RAG por HTTP: hoy ningún endpoint invoca `GroundedGenerationService` ([Historia §9](PROJECT_HISTORY_AND_CURRENT_STATE.md#9-http)) |
| F3 | Medir el canal híbrido completo (RRF) extremo a extremo ([Historia §10.4](PROJECT_HISTORY_AND_CURRENT_STATE.md#104-el-hueco-de-la-corrida-híbrida)) |
| F4 | Validación legal de EmbeddingGemma, o adopción definitiva de BGE-M3 |
| F5 | Recuperar la línea base de métricas del runtime de generación |
| F6 | Limpieza documental de la ruta histórica de §9.1 |

---

## 14. Referencias

- [`CLAUDE.md`](../../CLAUDE.md) — contrato del proyecto
- [Historia técnica y estado actual](PROJECT_HISTORY_AND_CURRENT_STATE.md) — documento hermano
- [`docs/architecture.md`](../architecture.md) — arquitectura y fronteras
- [`docs/security.md`](../security.md) — política de secretos, logs y CORS
- [`docs/environment-variables.md`](../environment-variables.md) — referencia de variables
- [`docs/development.md`](../development.md) — desarrollo local y migraciones
- [`docs/llm-runtime.md`](../llm-runtime.md) — operación de `llama-server`
- [ADR 0021](../adr/0021-contrato-de-inventario-con-materiales.md) — contrato de inventario e hitos M1–M8
- [ADR 0026](../adr/0026-gobernanza-y-cierre-de-m7.md) — gobernanza del contrato y cierre de M7
- [`BLOCK_CLOSURE_STANDARD.md`](BLOCK_CLOSURE_STANDARD.md) — estándar de cierre de bloques
