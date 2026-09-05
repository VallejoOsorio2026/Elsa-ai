# ADR 0002 — Identidad desde Materiales; autorización en el backend, no RLS

## Estado

Aceptado (2026-09-04).

## Contexto

Los usuarios de ELSA ya existen en el Supabase del Asistente de Materiales,
que emite sus JWT. ELSA tiene un proyecto Supabase propio e independiente.
El mecanismo idiomático de autorización dentro de un proyecto Supabase es RLS
(Row Level Security) basado en `auth.uid()`, pero ese mecanismo solo funciona
con tokens emitidos por el **mismo** proyecto: el Supabase de ELSA no puede
resolver `auth.uid()` a partir de un token del proyecto Materiales.

## Decisión

- La identidad proviene del Supabase Auth del proyecto Materiales (JWT).
- FastAPI valida ese token y aplica los **permisos propios de ELSA**; RLS no
  es el mecanismo de autorización de ELSA.
- El backend accede a la base de ELSA con credencial de servicio, que nunca
  sale del backend.
- La verificación del JWT se prefiere asimétrica, contra el JWKS público de
  Materiales; si el proyecto solo ofrece firma simétrica, el secreto se lee
  de variable de entorno y nunca se versiona.
- El verificador vive detrás del puerto `auth` (`src/elsa/ports/auth.py`),
  de modo que cambiar de mecanismo afecte a un solo adaptador.

## Consecuencias

- Los permisos de ELSA se implementan y prueban en código Python, no en
  políticas SQL; el LLM nunca participa en decisiones de permisos y estos se
  aplican antes de recuperar conocimiento.
- La credencial de servicio convierte al backend en frontera de seguridad
  única: los controles de acceso deben cubrirse con tests y auditoría en esa
  capa (no existe una segunda barrera RLS detrás).
- Migrar en el futuro a identidad propia de ELSA (o a otra fuente) se reduce
  a escribir otro adaptador del puerto `auth`.
