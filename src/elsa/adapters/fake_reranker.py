"""Adaptador fake del puerto de reranking (determinista, para tests)."""

from collections.abc import Sequence

from elsa.ports.reranker import RankedDocument


class FakeRerankerAdapter:
    """Puntúa por solapamiento de palabras entre consulta y documento.

    El orden es estable: a igual puntaje gana el documento con menor índice
    de entrada, de modo que el resultado es siempre reproducible.
    """

    async def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_k: int | None = None,
    ) -> list[RankedDocument]:
        query_terms = set(query.lower().split())
        ranked = [
            RankedDocument(index=index, score=self._score(query_terms, document))
            for index, document in enumerate(documents)
        ]
        ranked.sort(key=lambda item: (-item.score, item.index))
        return ranked if top_k is None else ranked[:top_k]

    @staticmethod
    def _score(query_terms: set[str], document: str) -> float:
        document_terms = set(document.lower().split())
        if not query_terms or not document_terms:
            return 0.0
        return len(query_terms & document_terms) / len(query_terms)
