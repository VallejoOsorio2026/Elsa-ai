"""Conocimiento documental: secciones, chunks y su procedencia.

Este paquete es el equivalente documental de ``elsa.ingestion``, y como él
es **independiente de FastAPI y de la base de datos**: recibe una extracción
y devuelve estructuras de datos. Eso permite probarlo con documentos
hostiles sin levantar nada, y es lo que hace verificable que el mismo
documento produce siempre los mismos chunks.

Lo que **no** vive aquí, y no es un olvido: embeddings, búsqueda semántica y
recuperación. Este bloque construye el material sobre el que esas fases
trabajarán; construirlas antes obligaría a rehacerlas.
"""
