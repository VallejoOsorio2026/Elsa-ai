# ADR 0004 — `uv` como gestor de dependencias

## Estado

Aceptado (2026-09-04).

## Contexto

El proyecto necesita entornos reproducibles en tres lugares: la máquina de
cada desarrollador, CI y el despliegue futuro. El criterio de aceptación
permanente exige que un clon limpio, siguiendo solo el README, levante el
servidor y pase los tests en una máquina sin contexto previo — idealmente sin
pasos manuales de instalación de Python. Las alternativas clásicas (pip +
requirements.txt, Poetry, pipenv) requieren gestionar el intérprete aparte o
resuelven dependencias sin lockfile multiplataforma consistente.

## Decisión

[`uv`](https://docs.astral.sh/uv/) es el gestor de dependencias y de entorno
del proyecto:

- `pyproject.toml` declara dependencias (grupo `dev` para tooling);
  `uv.lock` fija versiones exactas y se versiona.
- `.python-version` fija Python 3.12; `uv sync` descarga ese intérprete si la
  máquina no lo tiene y crea `.venv` con las versiones del lockfile.
- CI instala con `uv sync --locked`, que falla si el lockfile no corresponde
  a `pyproject.toml`.
- Las dependencias se cambian con `uv add` / `uv remove`; `uv.lock` nunca se
  edita a mano.

## Consecuencias

- La puesta en marcha de un clon limpio son dos comandos (`uv sync`,
  `cp .env.example .env`), idénticos en desarrollo y CI.
- Los entornos son deterministas: mismas versiones en todas las máquinas;
  la deriva entre `pyproject.toml` y el lockfile se detecta en CI.
- El equipo depende de una herramienta relativamente joven (Astral); se
  mitiga con formatos estándar (`pyproject.toml` cumple PEP 621), que
  permiten migrar a otro gestor si hiciera falta.
