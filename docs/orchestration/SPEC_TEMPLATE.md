---
# Copiar a docs/orchestration/work/<id>.md y reemplazar los valores de ejemplo.
# Este archivo es público: nunca lleva secretos, datos de planta ni rutas personales.
id: O0.0
title: Título corto del bloque
base: main
branch: claude/o0-0-descripcion-corta
# Únicas rutas que el bloque puede cambiar. Todo lo demás está prohibido.
allowed_paths:
  - docs/ejemplo.md
# Prohibiciones adicionales. Nunca reducen las rutas bloqueadas siempre del manual.
forbidden_paths: []
# Límite de una ejecución, en minutos. Máximo 120.
timeout_minutes: 60
# Cuándo debe detenerse y reportar, además de las paradas generales del manual.
stop_conditions:
  - una verificación falla
  - hace falta cambiar una ruta fuera de allowed_paths
# Pasos que solo hace una persona.
human_gates:
  - crear el pull request
  - hacer el merge
---

# <id> — <título>

**Autorizó:** quién, y dónde consta. **Fecha:** AAAA-MM-DD.

## Objetivo

Una frase: qué capacidad queda disponible al terminar.

## Dentro del alcance

Lista cerrada de entregables verificables.

## Fuera del alcance

Lista explícita de lo que queda «casi listo» pero pertenece a otro bloque.

## Decisiones

Las ya tomadas, con su motivo. Las pendientes se preguntan antes de empezar.

## Criterios de aceptación

Formato: `acción → resultado observable`. Son texto para una persona: **nunca se ejecutan
como comandos** copiados de este archivo.

| Acción | Resultado esperado |
|---|---|
| | |

## Riesgos

Cada uno con su mitigación concreta.

## Cierre

Nombre del documento de cierre, según `docs/project/BLOCK_CLOSURE_STANDARD.md`.
