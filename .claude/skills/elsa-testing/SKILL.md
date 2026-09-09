---
name: elsa-testing
description: Ejecutar y reportar verificaciones de ELSA - pytest enfocado, suite completa, ruff check y format, mypy, gitleaks/pre-commit y los tests que necesitan PostgreSQL. Úsala antes de commitear, antes de afirmar que algo funciona, al diagnosticar un fallo de CI, cuando un test se está omitiendo sin explicación, o cuando haya que decidir qué verificaciones son proporcionales al cambio hecho. NO la uses para escribir la lógica de negocio que se prueba, ni para el runbook de aplicación de migraciones (eso es elsa-migrations).
---

# Verificación en ELSA

Regla 21 del contrato: **nunca afirmes que algo funciona sin haberlo
ejecutado.** Pega la salida real, no un resumen de ella. Un fallo se reporta;
no se oculta ni se reinterpreta.

## Orden de trabajo

1. **Enfocado primero.** Mientras iteras, corre solo lo que toca el cambio:
   `uv run pytest tests/test_<lo_que_toca>.py -x -q`
2. **Cierra la unidad.** Cuando el cambio esté completo y verde en lo
   enfocado, commit + push (regla 18). No esperes al final del bloque.
3. **Suite completa antes de dar por cerrado.** En este orden:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Es exactamente lo que corre CI (`.github/workflows/ci.yml`). Si algo falla
localmente, fallará allí.

4. **Secretos.** `uv run pre-commit run --all-files` incluye gitleaks. En CI
   gitleaks escanea la historia completa, no solo `HEAD`: un secreto
   commiteado y luego borrado sigue rompiendo el pipeline.

## Tests que necesitan PostgreSQL

Los tests de migraciones y del repositorio de permisos se **omiten en
silencio** si no está definida `ELSA_TEST_DATABASE_URL`. Un `pytest` verde sin
esa variable **no prueba el esquema**.

Si el cambio toca `supabase/migrations/`, `src/elsa/adapters/postgres_*` o el
modelo de datos, levanta la base y vuelve a correr — el comando está en
`docs/development.md` §«Tests que necesitan PostgreSQL». Nunca apuntes a un
Supabase real.

Al reportar, di explícitamente cuántos tests se omitieron y por qué.

## No escondas el código de salida

Un pipe se queda con el estado del último comando: `pytest | tail -20`
devuelve el estado de `tail`, que casi siempre es 0. Eso convierte un fallo en
un falso verde.

- Sin pipe siempre que se pueda.
- Si necesitas recortar salida, conserva el estado:
  `uv run pytest; echo "exit=$?"` o `set -o pipefail` antes del pipe.
- Nunca uses `|| true`, `-k` para saltarte un test que falla, ni marques
  `xfail` un test que descubre un defecto real.

## Proporcionalidad

- Cambio solo en `docs/`, `.claude/` o `README.md`: bastan los hooks de
  pre-commit y el escaneo de secretos. Dilo así en el reporte.
- Cambio en `web/`: `uv run pytest tests/test_web_static.py` más la aceptación
  de interfaz (`elsa-ui-acceptance`).
- Cambio en `src/elsa/`: suite completa.
- Cambio en el esquema: suite completa **con** PostgreSQL.

Declarar que una verificación no aplica es válido; darla por hecha no.

## Cómo se reporta

- Comando ejecutado, literal.
- Salida real, incluidos los `skipped` y los avisos.
- Qué **no** se ejecutó y por qué.
- Si algo quedó en rojo: qué falla, dónde, y qué hace falta para arreglarlo.
