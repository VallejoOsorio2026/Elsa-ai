"""Servicios de aplicación.

Orquestan puertos para llevar a cabo un caso de uso completo. No contienen
reglas de negocio —esas viven en ``elsa.core``— ni saben de HTTP —eso vive
en ``elsa.api``—: deciden en qué orden ocurren las cosas y qué pasa cuando
un paso falla.
"""
