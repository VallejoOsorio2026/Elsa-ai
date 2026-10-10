"""Agente de PC1: la mitad local del relay Render–PC1 (D2.3, ADR 0032).

Es un proceso aparte (``uv run python -m elsa.agent``) que **solo abre
conexiones salientes**: HTTPS hacia el relay de Render y HTTP hacia la ELSA
local en loopback. No escucha en ningún socket.

Fronteras que el paquete respeta (y que un test comprueba):

- Del relay solo importa el contrato (:mod:`elsa.relay.protocol`), el nombre
  de la cabecera del nodo y los límites de tamaño del cable. No importa
  FastAPI, la API, el contenedor ni los adaptadores de ELSA: habla con ELSA
  por HTTP, como cualquier cliente.
- La única operación que ejecuta es ``assistant.ask``; la ruta local la
  construye por código fijo. No es un proxy genérico.
- El token del nodo va únicamente a Render; el del usuario, únicamente a ELSA
  local. Ninguno se persiste ni se registra.
"""
