"""Modo ELSA de PC1 (ADR 0034).

Un supervisor en primer plano que arranca, vigila y detiene en orden ELSA local
y el agente de PC1. Se opera con tres acciones::

    python -m elsa.pc1 start
    python -m elsa.pc1 status
    python -m elsa.pc1 stop

El supervisor solo detiene los procesos que él creó, y en Windows los ata a un
Job Object para que no queden huérfanos si él muere.
"""
