"""Recuperadores del banco: denso sobre un adaptador, y líneas base léxicas.

Las líneas base no son relleno. Sin ellas no se sabe si el vector aporta
algo: si un candidato denso pierde contra una búsqueda por palabras en el
eje de códigos, eso no es un fallo del banco, es el dato con el que se
diseña la recuperación híbrida del Bloque 4.3.

Las dos líneas base son de Python puro y no necesitan PostgreSQL. Las
equivalentes reales —`tsvector` con configuración española y `pg_trgm`—
llegan con 4.2.b, cuando exista la migración que las soporte; estas
aproximan el mismo eje y, sobre todo, hacen el banco ejecutable hoy y en CI.
"""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

from elsa.bench.metrics import QueryResult
from elsa.bench.model import BenchCorpus, GoldenSet
from elsa.bench.ports import BenchmarkEmbedder

__all__ = ["DenseRetriever", "LexicalRetriever", "TrigramRetriever", "Retriever"]

_WORD = re.compile(r"[0-9a-záéíóúüñ]+", re.IGNORECASE)
_DEPTH = 10


def _fold(text: str) -> str:
    """Minúsculas sin acentos: así «lubricación» y «lubricacion» coinciden."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _tokens(text: str) -> list[str]:
    return _WORD.findall(_fold(text))


def _trigrams(text: str) -> set[str]:
    folded = f"  {_fold(text)} "
    return {folded[index : index + 3] for index in range(len(folded) - 2)}


class Retriever:
    """Base común: recupera para cada consulta del conjunto dorado."""

    name = "retriever"

    def run(self, corpus: BenchCorpus, golden: GoldenSet) -> dict[str, QueryResult]:
        raise NotImplementedError


class LexicalRetriever(Retriever):
    """BM25 sobre el corpus. Aproxima el canal léxico de PostgreSQL.

    Se eligió BM25 y no un simple conteo porque es lo que hacen tanto
    `ts_rank` como cualquier motor léxico serio: penaliza los términos
    frecuentes y normaliza por longitud del pasaje. Una línea base más débil
    haría parecer mejor de lo que es a cualquier candidato denso.
    """

    name = "lexical-bm25"

    def __init__(self, *, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b

    def run(self, corpus: BenchCorpus, golden: GoldenSet) -> dict[str, QueryResult]:
        documents = [_tokens(chunk.content) for chunk in corpus.chunks]
        lengths = [len(tokens) for tokens in documents]
        average = sum(lengths) / len(lengths) if lengths else 0.0
        frequency: Counter[str] = Counter()
        for tokens in documents:
            frequency.update(set(tokens))
        total = len(documents)

        results: dict[str, QueryResult] = {}
        for query in golden.queries:
            terms = _tokens(query.text)
            scored: list[tuple[float, str]] = []
            for index, chunk in enumerate(corpus.chunks):
                counts = Counter(documents[index])
                score = 0.0
                for term in terms:
                    occurrences = counts.get(term, 0)
                    if not occurrences:
                        continue
                    idf = math.log(1 + (total - frequency[term] + 0.5) / (frequency[term] + 0.5))
                    norm = occurrences + self._k1 * (
                        1 - self._b + self._b * lengths[index] / (average or 1)
                    )
                    score += idf * occurrences * (self._k1 + 1) / norm
                if score:
                    scored.append((score, chunk.chunk_id))
            results[query.id] = _rank(query.id, scored)
        return results


class TrigramRetriever(Retriever):
    """Similitud de trigramas. Es la línea base que tolera erratas.

    Aproxima `pg_trgm`. Existe porque el eje de erratas es real: la mitad de
    las consultas de planta llegan desde un móvil y con faltas.
    """

    name = "lexical-trigram"

    def run(self, corpus: BenchCorpus, golden: GoldenSet) -> dict[str, QueryResult]:
        chunk_grams = [(chunk.chunk_id, _trigrams(chunk.content)) for chunk in corpus.chunks]
        results: dict[str, QueryResult] = {}
        for query in golden.queries:
            grams = _trigrams(query.text)
            scored = [
                (len(grams & other) / len(grams | other), chunk_id)
                for chunk_id, other in chunk_grams
                if grams & other
            ]
            results[query.id] = _rank(query.id, scored)
        return results


class DenseRetriever(Retriever):
    """Vecino más cercano por coseno sobre un adaptador de embeddings.

    Embebe el corpus una vez y cada consulta después, **con la operación que
    corresponde a cada uno**: nunca pasa un pasaje por `embed_queries`.
    """

    def __init__(self, embedder: BenchmarkEmbedder) -> None:
        self._embedder = embedder
        self.name = f"dense:{embedder.describe().model_name}"

    def run(self, corpus: BenchCorpus, golden: GoldenSet) -> dict[str, QueryResult]:
        passages = self._embedder.embed_documents([chunk.content for chunk in corpus.chunks])
        queries = self._embedder.embed_queries([query.text for query in golden.queries])
        return self.precomputed(corpus, golden, passages, queries)

    def precomputed(
        self,
        corpus: BenchCorpus,
        golden: GoldenSet,
        passages: Sequence[Sequence[float]],
        queries: Sequence[Sequence[float]],
    ) -> dict[str, QueryResult]:
        """Puntúa con vectores ya calculados.

        Existe para que el runner pueda cronometrar corpus y consulta por
        separado sin embeber dos veces: medir el coste no debe cambiar lo
        que se mide.
        """
        results: dict[str, QueryResult] = {}
        for position, query in enumerate(golden.queries):
            vector = queries[position]
            scored = [
                (_cosine(vector, passages[index]), chunk.chunk_id)
                for index, chunk in enumerate(corpus.chunks)
            ]
            results[query.id] = _rank(query.id, scored)
        return results


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def _rank(query_id: str, scored: list[tuple[float, str]]) -> QueryResult:
    """Ordena y desempata por identificador.

    El desempate por `chunk_id` no es cosmético: sin él, dos chunks con la
    misma puntuación saldrían en el orden en que los recorrió un bucle, y dos
    corridas del mismo banco podrían dar métricas distintas.
    """
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    top = scored[:_DEPTH]
    return QueryResult(
        query_id=query_id,
        ranked=tuple(chunk_id for _, chunk_id in top),
        scores=tuple(score for score, _ in top),
    )
