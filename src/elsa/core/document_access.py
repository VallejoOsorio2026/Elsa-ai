"""Autorización sobre el conocimiento documental.

Este módulo existe para que la regla 4 de ``CLAUDE.md`` —los permisos se
aplican **antes** de recuperar conocimiento, no después— sea aplicable el día
que exista recuperación, y no una intención escrita en un documento.

No introduce un segundo modelo de permisos. Un documento tiene el mismo
alcance que ya define el Bloque 1: ``(dominio, equipo)``. Un documento atado
a un activo técnico toma el código del activo como equipo; uno que aplica al
dominio entero no declara equipo. La decisión la sigue tomando
:func:`elsa.core.authorization.authorize`, que no conoce ni documentos ni
chunks.

El orden correcto es siempre el mismo:

1. Resolver qué alcances puede leer la persona (:func:`readable_scopes`).
2. Pedir al repositorio **solo** esos alcances.
3. Recuperar.

Nunca al revés. Recuperar y después ocultar deja el contenido dentro del
proceso, dentro de los logs y a un descuido de distancia del LLM.
"""

from collections.abc import Iterable, Sequence
from typing import Protocol

from elsa.core.authorization import AccessDecision, Principal, Scope, authorize

__all__ = [
    "document_scope",
    "may_read",
    "readable",
    "readable_scopes",
]


def document_scope(*, domain: str, asset_code: str | None) -> Scope:
    """Alcance que hay que autorizar para leer un documento."""
    return Scope(domain=domain, equipment=asset_code)


class _HasScope(Protocol):
    """Cualquier cosa que declare su alcance: un documento o una procedencia.

    Es estructural a propósito. Este módulo no debe importar el puerto de
    documentos —el negocio no depende de la forma de la persistencia—, y
    lo único que necesita de su argumento es que sepa decir a qué alcance
    pertenece.
    """

    @property
    def scope(self) -> Scope: ...


def may_read(principal: Principal, subject: _HasScope) -> AccessDecision:
    """Decide si ``principal`` puede leer ese documento o ese chunk."""
    return authorize(principal, subject.scope)


def readable[T: _HasScope](principal: Principal, subjects: Iterable[T]) -> tuple[T, ...]:
    """Filtra lo que la persona puede leer, conservando el orden.

    Se usa sobre **documentos**, para saber qué hay disponible. Sobre chunks
    llega tarde por definición: para entonces el contenido ya se recuperó.
    """
    return tuple(subject for subject in subjects if may_read(principal, subject).allowed)


def readable_scopes[T: _HasScope](principal: Principal, subjects: Sequence[T]) -> tuple[Scope, ...]:
    """Alcances que la persona puede leer, de entre los que existen.

    Es lo que se pasa a
    :meth:`~elsa.ports.documents.DocumentRepositoryPort.list_published_chunks`.
    Se calcula a partir de los documentos que existen y no de los permisos en
    bruto, porque un administrador tiene acceso total y no lleva un permiso
    por cada alcance: enumerar sus permisos daría una lista vacía y no
    recuperaría nada.

    El resultado no tiene duplicados y viene ordenado, para que dos llamadas
    equivalentes produzcan la misma consulta.
    """
    allowed = {subject.scope for subject in subjects if may_read(principal, subject).allowed}
    return tuple(sorted(allowed, key=lambda scope: (scope.domain, scope.equipment or "")))
