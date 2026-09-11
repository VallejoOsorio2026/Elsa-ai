"""Banco de pruebas para elegir el modelo de embeddings (Bloque 4.2.a).

**Este paquete no forma parte del camino productivo de ELSA.** Existe para
medir candidatos y decidir con datos propios, no para servir consultas. Nada
de `api/`, `core/` o `services/` lo importa, y hay una prueba que lo
comprueba —`test_the_productive_code_does_not_import_the_benchmark`, en
`tests/test_bench_harness.py`—: si algún día el runtime dependiera de esto,
se enteraría alguien antes de desplegarlo.

La interfaz de evaluación (`ports.py`) es deliberadamente **distinta** del
puerto `elsa.ports.embeddings`, que es el que usará el flujo real. Aquí hacen
falta cosas que al runtime no le importan —qué prefijo se usó, cuánto tardó
la carga, cuánta memoria ocupó— y no hacen falta otras que al runtime sí.
Fundirlas habría atado el runtime a las necesidades de un banco de pruebas.

Lo que este bloque **no** hace: no persiste vectores, no toca pgvector, no
añade migraciones y no recupera nada en producción. Ver
`docs/bloque-4-2-plan.md`.
"""
