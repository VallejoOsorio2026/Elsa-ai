# CLAUDE.md — Contrato del proyecto ELSA

Este archivo es la fuente de verdad del proyecto. Claude Code lo lee automáticamente
en cada sesión. Todo lo que aparece aquí aplica siempre, en todos los bloques de
trabajo, sin necesidad de repetirlo en cada prompt.

Si una instrucción de una sesión contradice este archivo, **detente y pregunta**.
No resuelvas la contradicción por tu cuenta.

---

## 1. Qué es ELSA

ELSA es un asistente corporativo para los ingenieros de mantenimiento de la Planta
Molino Barbosa de PAPELSA.

El MVP técnico está limitado al equipo **Tampella**, pero la arquitectura debe
permitir posteriormente múltiples equipos, plantas y dominios de conocimiento.

Componentes previstos (no todos existen todavía):

- frontend web en `elsa-ai.link`
- backend Python + FastAPI
- proyecto Supabase propio de ELSA
- autenticación proveniente del Supabase del Asistente de Materiales
- permisos propios de ELSA
- integración posterior con el motor del Asistente de Materiales
- datos estructurados de IH06 e IW13
- RAG documental para manuales y planos
- LLM local / autohospedado
- modelos de embeddings, OCR y reranking reemplazables
- trazabilidad completa de evidencias
- Centro de Control administrativo

**El proyecto será entregado a PAPELSA.** Otra persona debe poder entenderlo y
continuarlo sin acceso a las conversaciones que lo produjeron.

---

## 2. Reglas arquitectónicas innegociables

1. El navegador nunca se comunica directamente con el LLM.
2. FastAPI es la frontera principal del backend.
3. El LLM nunca decide permisos.
4. Los permisos se aplican **antes** de recuperar conocimiento, no después.
5. El LLM nunca crea hechos sin evidencia recuperada.
6. Materiales sigue siendo propietario de su inventario. ELSA no duplica sus
   ~65.000 registros.
7. ELSA tiene un proyecto Supabase independiente.
8. La identidad proviene inicialmente de Supabase Auth del proyecto Materiales.
9. FastAPI valida esa identidad y aplica los permisos propios de ELSA.
10. No hay secretos en el repositorio ni en el frontend.
11. Toda estructura de base de datos es reproducible mediante migraciones
    versionadas.
12. LLM, embeddings, reranker y OCR dependen de interfaces. Nunca se acoplan
    directamente a la lógica de negocio.
13. Existen ambientes lógicos DEV y TEST.
14. El sistema funciona parcialmente cuando el LLM está fuera de servicio.
15. La arquitectura facilita auditoría de ciberseguridad y pentesting.

---

## 3. Stack decidido

| Área | Decisión | Estado |
|---|---|---|
| Lenguaje | Python 3.12 (fijado en `.python-version`) | Cerrado |
| Framework | FastAPI | Cerrado |
| Dependencias | `uv` con `pyproject.toml` + `uv.lock` | Cerrado |
| Base de datos | PostgreSQL / Supabase + pgvector | Cerrado |
| Migraciones | Supabase CLI (`supabase/migrations/*.sql`) | Cerrado |
| Lint y formato | Ruff (lint + format) | Cerrado |
| Tipos | mypy, modo no estricto | Cerrado |
| Tests | pytest | Cerrado |
| CI | GitHub Actions | Cerrado |
| Commits | Conventional Commits | Cerrado |
| LLM | local / autohospedado, proveedor por determinar | Abierto |
| Servidor de modelos | probablemente Ollama en laboratorio | Abierto, sin dependencia rígida |
| OCR | Docling vs PaddleOCR | Abierto |
| Embeddings | EmbeddingGemma vs BGE-M3 | Abierto |
| Reranker | candidato BGE reranker | Abierto |
| Frontend | se diseñará con Claude Design | Abierto |
| Despliegue | por determinar | Abierto |

Lo marcado como **abierto** no debe convertirse en dependencia dura de ningún
módulo. Se accede siempre a través de un puerto (ver sección 5).

---

## 4. Decisiones ya resueltas (no reabrir sin ADR)

**Migraciones.** El esquema de la base de datos de ELSA tiene una sola autoridad:
los archivos SQL versionados bajo `supabase/migrations/`. No se usa Alembic ni
migraciones generadas por ORM. Los cambios hechos a mano en el dashboard de
Supabase no son válidos: deben volcarse a una migración.

**Identidad y autorización.** El token JWT lo emite el proyecto Supabase de
Materiales. El proyecto Supabase de ELSA no puede validar ese token con
`auth.uid()`, por lo que **RLS no es el mecanismo de autorización de ELSA**. La
autorización vive en FastAPI: el backend valida el JWT, resuelve los permisos
propios de ELSA y accede a la base con credencial de servicio. Ninguna clave de
servicio sale del backend.

**Verificación del JWT.** Se prefiere validación asimétrica contra el JWKS público
de Materiales. Si el proyecto solo ofrece firma simétrica, el secreto se lee de
variable de entorno y nunca se versiona. El verificador está detrás de un puerto
para que el cambio afecte a un solo archivo.

**Ambientes.** DEV y TEST son proyectos Supabase distintos, seleccionados por
variable de entorno. Ningún ambiente comparte base de datos con otro.

**Idioma.** Documentación, ADRs y comentarios de negocio en español. Nombres de
código, ramas, mensajes de commit y logs en inglés.

---

## 5. Puertos y adaptadores

Toda dependencia externa reemplazable se define como un `Protocol` en
`src/elsa/ports/` y se implementa en `src/elsa/adapters/`.

Puertos previstos: `auth`, `llm`, `embeddings`, `ocr`, `reranker`, `materials`.

Reglas:

- La lógica de negocio importa el puerto, nunca el adaptador.
- Cada puerto tiene al menos un adaptador *fake* determinista, usado en tests.
- El adaptador real se selecciona por configuración, no por import directo.
- Un puerto sin adaptador real todavía no es deuda técnica: es el diseño previsto.

---

## 6. Seguridad

- Ningún secreto en el repositorio. `.env` está en `.gitignore`; `.env.example`
  contiene claves sin valores.
- El escaneo de secretos es automático (pre-commit + CI), no una revisión manual.
- Nunca se versionan: archivos SAP, PDFs de manuales, planos, pesos de modelos,
  datasets, dumps de base de datos.
- Modo debug prohibido fuera de DEV.
- CORS declarado explícitamente por ambiente, sin comodines en TEST ni producción.
- Todo error devuelto al cliente usa el formato estándar del proyecto y no filtra
  trazas internas.
- Cada request lleva un identificador propagado a los logs, para trazabilidad y
  auditoría.

---

## 7. Criterios de calidad

- Simplicidad sobre sofisticación. No se construye código por anticipación.
- Separación de responsabilidades por encima de brevedad.
- **Criterio de aceptación permanente:** un clon limpio del repositorio, siguiendo
  únicamente el README, debe levantar el servidor y pasar los tests en una máquina
  sin contexto previo.
- Toda decisión arquitectónica relevante se registra como ADR en `docs/adr/`.

---

## 8. Método de trabajo

El proyecto avanza por bloques. Reglas de todos los bloques:

1. Antes de escribir código, reporta las inconsistencias técnicas que detectes en
   las instrucciones recibidas. Si algo impide comenzar, pregunta.
2. No avances al bloque siguiente sin autorización explícita.
3. No amplíes el alcance del bloque actual, aunque el código quede "casi listo"
   para algo más.
4. Al terminar, ejecuta las pruebas y reporta la salida real. No afirmes que algo
   funciona sin haberlo ejecutado.
5. Si una tarea del bloque resulta imposible o desaconsejable, dilo y explica por
   qué en lugar de improvisar una alternativa.
