"""Canales exacto y léxico sobre PostgreSQL, sin extensiones ni migración.

Los dos filtran el alcance **dentro de la misma consulta** que ordena. No hay
un camino por el que se recupere de todo el corpus y se filtre después: sería
la regla 3 al revés, y ADR 0014 ya razona por qué el aislamiento vive en el
`WHERE`.

**Por qué son dos canales y no uno.** La configuración `spanish` parte los
identificadores: `to_tsvector('spanish', 'SAP-4471')` da `'sap'` y `'-4471'`.
Para prosa eso es exactamente lo que se quiere —«lubricación» encuentra
«lubricar»—, y para un código es ruido. El canal exacto busca el literal con
frontera de palabra; el léxico busca el sentido de las palabras.

**Sin índice, a propósito.** Un índice GIN sobre `to_tsvector` exigiría una
columna o un índice de expresión, es decir una migración, y el piloto es del
orden de 10³–10⁴ chunks: el mismo razonamiento por el que la búsqueda vectorial
es exacta (ADR 0013 §6). Cuando el volumen lo justifique, será su propia
migración con su propia medición.
"""

import contextlib
import logging
import re
from collections.abc import Iterator, Sequence
from typing import Any

import asyncpg

from elsa.core.authorization import Scope
from elsa.ports.documents import (
    ChunkProvenance,
    DocumentChunkRecord,
    DocumentRecord,
    DocumentSectionRecord,
    DocumentVersionRecord,
)
from elsa.ports.knowledge import KnowledgeUnavailableError

_logger = logging.getLogger(__name__)

__all__ = ["PostgresLexicalSearch"]

_SPANISH = "spanish"


@contextlib.contextmanager
def _database_errors() -> Iterator[None]:
    try:
        yield
    except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError, TimeoutError) as error:
        _logger.warning("lexical search failure", extra={"error": type(error).__name__})
        raise KnowledgeUnavailableError("the ELSA document store is unavailable") from None


# El alcance, tal y como lo define `core.authorization.covers`: un permiso sin
# equipo cubre todo su dominio; uno con equipo cubre solo ese equipo.
_SCOPE_FILTER = """
  and exists (
    select 1 from unnest($1::text[], $2::text[]) as allowed(domain, equipment)
    where p.scope_domain = allowed.domain
      and (allowed.equipment is null or p.scope_equipment = allowed.equipment))
"""

_JOINS = """
from elsa.document_chunk_provenance as p
join elsa.document_chunks   as c on c.id = p.chunk_id
join elsa.document_versions as v on v.id = p.version_id
join elsa.documents         as d on d.id = v.document_id
left join elsa.document_sections as s on s.id = c.section_id
"""

# Canal exacto. `~*` con `\m`/`\M` exige frontera de palabra: `P-200` no
# aparece dentro de `P-2000`. Se ordena por **cuántos** identificadores
# distintos aparecen en el chunk: un pasaje que menciona los dos códigos de la
# pregunta es mejor evidencia que uno que menciona solo uno.
_EXACT = f"""
select p.*, c as chunk, v as version, d as document, s as section,
       (select count(*) from unnest($3::text[]) as needle
         where c.content ~* ('\\m' || needle || '\\M')) as matched
{_JOINS}
where p.version_state = 'published'
  and (select count(*) from unnest($3::text[]) as needle
        where c.content ~* ('\\m' || needle || '\\M')) > 0
  {_SCOPE_FILTER}
order by matched desc, c.ordinal, c.id
limit $4
"""

# Canal léxico. `websearch_to_tsquery` acepta lo que una persona escribe, sin
# sintaxis; `ts_rank_cd` tiene en cuenta la proximidad entre términos, que en
# un manual distingue «apriete del rodamiento» de dos palabras sueltas.
_LEXICAL = f"""
select p.*, c as chunk, v as version, d as document, s as section,
       ts_rank_cd(to_tsvector('{_SPANISH}', c.content), query) as score
{_JOINS}
     , websearch_to_tsquery('{_SPANISH}', $3) as query
where p.version_state = 'published'
  and to_tsvector('{_SPANISH}', c.content) @@ query
  {_SCOPE_FILTER}
order by score desc, c.ordinal, c.id
limit $4
"""

# Un identificador entra en una expresión regular, así que lo que llegue del
# usuario se escapa antes: sin esto, una consulta podría inyectar un patrón.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9._/-]{1,64}$")


class PostgresLexicalSearch:
    """Canales exacto y léxico del Bloque 4.3."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(
        cls, dsn: str, *, min_size: int = 1, max_size: int = 10
    ) -> "PostgresLexicalSearch":
        with _database_errors():
            pool = await asyncpg.create_pool(dsn, min_size=min_size, max_size=max_size)
        if pool is None:
            raise KnowledgeUnavailableError("could not create connection pool")
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def search_exact(
        self, *, identifiers: Sequence[str], scopes: Sequence[Scope], limit: int = 10
    ) -> tuple[tuple[ChunkProvenance, float], ...]:
        """Chunks que contienen literalmente alguno de los identificadores."""
        safe = [i for i in identifiers if _SAFE_IDENTIFIER.match(i)]
        if not safe or not scopes or limit <= 0:
            return ()
        with _database_errors():
            rows = await self._pool.fetch(
                _EXACT,
                [s.domain for s in scopes],
                [s.equipment for s in scopes],
                [re.escape(i) for i in safe],
                limit,
            )
        return tuple((_provenance(row), float(row["matched"])) for row in rows)

    async def search_lexical(
        self, *, query: str, scopes: Sequence[Scope], limit: int = 10
    ) -> tuple[tuple[ChunkProvenance, float], ...]:
        """Chunks cuyo texto responde a la consulta, con lematización española."""
        if not query.strip() or not scopes or limit <= 0:
            return ()
        with _database_errors():
            rows = await self._pool.fetch(
                _LEXICAL,
                [s.domain for s in scopes],
                [s.equipment for s in scopes],
                query,
                limit,
            )
        return tuple((_provenance(row), float(row["score"])) for row in rows)

    async def check_health(self) -> None:
        with _database_errors():
            await self._pool.fetchval("select 1")


def _provenance(row: Any) -> ChunkProvenance:
    from elsa.adapters.postgres_documents import _record

    return ChunkProvenance(
        chunk=_record(DocumentChunkRecord, row["chunk"]),
        version=_record(DocumentVersionRecord, row["version"]),
        document=_record(DocumentRecord, row["document"], asset_code=row["scope_equipment"]),
        section=(
            None if row["section"] is None else _record(DocumentSectionRecord, row["section"])
        ),
        source_sha256=row["source_sha256"],
        source_storage_key=row["source_storage_key"],
    )
