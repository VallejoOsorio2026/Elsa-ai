# Estándar de cierre de bloques

**Ningún bloque o subbloque se considera cerrado sin su documento Markdown de
cierre.** Este archivo es la fuente canónica de qué debe contener ese documento.
[`CLAUDE.md`](../../CLAUDE.md) obliga a cumplirlo; los detalles viven aquí.

## Por qué existe

El proyecto será entregado a PAPELSA, y otra persona debe poder entenderlo y
continuarlo **sin acceso a las conversaciones que lo produjeron**. Una
conversación con un asistente no es documentación: se pierde, no se versiona, y
nadie puede auditarla después.

Hay además una razón más dura. Buena parte del trabajo de este proyecto se
produce fuera del repositorio: comandos ejecutados en PowerShell, comprobaciones
hechas a mano contra un panel de Supabase, mediciones sobre archivos que nunca
entran a Git, decisiones tomadas en una conversación. Si eso no se escribe, el
repositorio guarda el resultado pero pierde la evidencia, y dentro de seis meses
nadie sabrá si una cifra se midió o se supuso.

## Cuándo se aplica

Al cerrar cualquier bloque o subbloque. Un bloque sin documento de cierre no
está cerrado, aunque su código esté en `main` y su CI esté en verde.

## Dónde vive

Un archivo Markdown por bloque, en `docs/`, con el número del bloque en el
nombre. Ejemplo: `docs/bloque-5-0-cierre.md`.

## Qué debe contener

Todas estas secciones. Una sección sin contenido se escribe con «nada que
registrar»; no se omite, porque omitirla no distingue entre «no pasó» y «se
olvidó».

1. **Objetivo** — qué capacidad debía quedar disponible al terminar.
2. **Alcance** — lo que entró, y lo que se dejó explícitamente fuera.
3. **Estado inicial** — de qué se partía: rama base, commit, qué existía y qué
   no.
4. **Trabajo realizado** — qué se construyó, en orden.
5. **Decisiones** — cada decisión tomada durante el bloque, con su motivo. Las
   arquitectónicas relevantes, además, como ADR (regla 25).
6. **Pruebas** — qué se ejecutó, no qué se pensaba ejecutar.
7. **Comandos relevantes** — los que otra persona necesitaría para reproducir el
   trabajo.
8. **Resultados** — la salida real. Pegada, no parafraseada.
9. **Métricas** — cifras medidas, con el método por el que se obtuvieron.
10. **Aportes de Claude Code** — qué produjo, en qué sesiones, y qué se revisó.
11. **Aportes de Codex** — lo mismo.
12. **Operaciones manuales y de PowerShell** — lo que se ejecutó fuera del
    repositorio: scripts, comandos, comprobaciones en un panel, arranque de
    servicios locales.
13. **Incidentes** — lo que falló, qué se hizo y qué quedó pendiente. Un bloque
    sin incidentes es sospechoso; si de verdad no los hubo, se dice.
14. **Git** — qué se tocó y cómo.
15. **Ramas** — las creadas, usadas y abandonadas.
16. **Commits** — los del bloque, con su hash.
17. **Pull requests** — número, estado y resultado de CI.
18. **Migraciones** — cuáles se escribieron, cuáles se aplicaron, a qué ambiente
    y con qué autorización (regla 15).
19. **Estado operacional final** — qué funciona, qué está degradado y qué no
    está conectado.
20. **Pendientes** — lo que queda abierto, con quién debe resolverlo.
21. **Siguiente bloque** — qué viene después y por qué.

## Cómo se marca cada afirmación

El documento debe distinguir, en cada afirmación relevante, de qué tipo es. Sin
esta distinción un lector no puede saber si algo se comprobó o se supuso.

| Marca | Significado |
|---|---|
| **HECHO MEDIDO** | Se ejecutó y se observó el resultado. Va acompañado de la salida real |
| **HECHO DEL REPOSITORIO** | Se puede verificar leyendo el código o el historial |
| **DECISIÓN TOMADA** | Alguien decidió esto, y el documento dice quién y por qué |
| **INFERENCIA** | Se deduce de lo anterior, pero **no** se comprobó |
| **PENDIENTE** | Abierto. Con responsable, si lo tiene |

Nunca se marca como **HECHO MEDIDO** algo que no se ejecutó (regla 21). Si una
comprobación la hizo el responsable del proyecto fuera de la sesión, se registra
como medida **por él**, nombrando la procedencia del dato.

## De dónde puede venir la evidencia

El estándar aplica a todo lo que produjo el bloque, viniera de donde viniera:

- **Claude Code** — sesiones, cambios propuestos y revisión.
- **Codex** — lo mismo.
- **PowerShell** — scripts del repositorio y comandos ejecutados a mano en la
  máquina de trabajo.
- **Pruebas manuales** — recorridos por la interfaz, comprobaciones de
  accesibilidad, ensayos con datos reales.
- **Supabase** — migraciones aplicadas, comprobaciones en el panel, estado de
  RLS, permisos de rol.
- **GitHub** — ramas, commits, pull requests, CI.
- **Render** — despliegues, variables de entorno declaradas, estado del
  servicio.
- **Mediciones realizadas por el usuario** — todo lo comprobado fuera de una
  sesión de asistente, registrado como tal.
- **Decisiones arquitectónicas tomadas durante la conversación** — que además
  necesitan su ADR.

## Qué nunca entra en un documento de cierre

- Secretos, tokens, claves, contraseñas o cadenas de conexión (regla 11).
- Datos reales de planta: contenido de archivos SAP, manuales, planos o volcados
  de base de datos (regla 12).
- Identificadores de usuario que no hagan falta para entender lo ocurrido.
- Resultados inventados, redondeados sin decirlo, o copiados de una ejecución
  que no es la que se describe.

Cuando una evidencia útil contiene algo de lo anterior, se registra su forma
—conteos, estructura, mensaje de error saneado— y **no** su contenido.
