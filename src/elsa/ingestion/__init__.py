"""Ingesta segura de fuentes técnicas.

Los parsers de este paquete son **independientes de FastAPI**: reciben bytes
y devuelven estructuras de datos. Ni abren sockets, ni tocan la base, ni
saben qué es una petición HTTP. Eso permite probarlos exhaustivamente con
archivos hostiles sin levantar la aplicación, y es lo que hace creíble la
afirmación de que un archivo malicioso no puede ejecutar nada: no hay nada
que ejecutar en el camino.

Regla común a todo el paquete: **un archivo de entrada es contenido no
confiable**. No se ejecutan sus fórmulas, no se sigue ninguno de sus
enlaces, no se descarga ningún recurso que mencione y no se cree su
extensión.
"""
