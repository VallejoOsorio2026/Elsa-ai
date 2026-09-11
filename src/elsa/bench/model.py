"""Estructuras del banco: corpus, consultas del conjunto dorado y corridas.

Datos puros y deterministas. Ningún campo depende del reloj salvo los que
describen explícitamente una corrida, y esos se excluyen de toda huella que
se compare entre ejecuciones.
"""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "Axis",
    "BenchChunk",
    "BenchCorpus",
    "Difficulty",
    "GoldenQuery",
    "GoldenSet",
    "MatchKind",
    "RunMetadata",
]


class Axis(StrEnum):
    """Eje de evaluación. Los resultados se desglosan por eje, no solo en
    promedio: una media global oculta justo lo que hay que ver, un modelo
    excelente en narrativo y nulo en códigos."""

    NARRATIVE = "narrative"
    SYNONYMS = "synonyms"
    COMPONENT_NAMES = "component_names"
    CODES = "codes"
    TYPOS = "typos"
    KEYWORD = "keyword"
    CROSS_LANGUAGE = "cross_language"
    NUMBERS_UNITS = "numbers_units"
    ABBREVIATIONS = "abbreviations"
    FAILURE_SYMPTOMS = "failure_symptoms"
    PREVENTIVE = "preventive"
    SAFETY = "safety"
    PROCEDURE = "procedure"
    SECTION_REFERENCE = "section_reference"
    NO_ANSWER = "no_answer"
    AMBIGUITY = "ambiguity"
    ASSET_CONFUSION = "asset_confusion"
    VERSION_CONFUSION = "version_confusion"
    NEAR_MISS_DOCUMENT = "near_miss_document"


# Ejes que NO entran en la puntuación principal del modelo denso.
#
# Los códigos y los identificadores exactos los resolverá el canal léxico o
# estructurado de la fase 4.3, no el vector. Medirlos aquí sirve de
# diagnóstico —dice cuánto tendría que aportar ese canal— pero dejar que
# decidan el ganador del modelo denso sería elegir por el eje equivocado.
DIAGNOSTIC_AXES: frozenset[Axis] = frozenset({Axis.CODES})

# Ejes que miden **confusabilidad**, no autorización.
#
# El aislamiento entre activos y entre versiones lo garantiza el filtro de la
# consulta (`WHERE`), nunca el modelo. Lo que estos ejes miden es si el
# ranking denso confunde dos activos que hablan parecido o dos versiones del
# mismo documento. Un resultado malo aquí no es una fuga de permisos: es una
# señal de que el canal denso solo no distingue, y de que el filtro es
# imprescindible. Ver `docs/embedding-benchmark.md`.
CONFUSABILITY_AXES: frozenset[Axis] = frozenset(
    {Axis.ASSET_CONFUSION, Axis.VERSION_CONFUSION, Axis.NEAR_MISS_DOCUMENT}
)


class MatchKind(StrEnum):
    """Por dónde se espera que se resuelva la consulta."""

    SEMANTIC = "semantic"
    LEXICAL = "lexical"
    MIXED = "mixed"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass(frozen=True, slots=True)
class BenchChunk:
    """Un chunk del corpus, con el metadato del escenario que representa.

    ``chunk_id`` es legible y estable: ``<documento>@v<version>#<clave>``. Se
    usa en el conjunto dorado para no tener que anotar UUID, que cambiarían en
    cada corrida y harían el conjunto irreproducible.
    """

    chunk_id: str
    document_code: str
    document_title: str
    domain: str
    asset: str
    version: int
    published: bool
    language: str
    structural_key: str
    section_path: str | None
    section_title: str | None
    page_start: int | None
    kind: str
    content: str

    embedded_text: str = ""
    """Texto compuesto con `context-v1`: es **esto** lo que se embebe.

    El banco indexa y rankea todo el corpus a propósito, incluida la versión
    no publicada: si aplicara el corte por estado no podría medir si el
    ranking confunde dos versiones. El corte lo hace el `WHERE` de la
    consulta de recuperación, que no vive aquí.
    """

    embedded_sha256: str = ""


@dataclass(frozen=True, slots=True)
class BenchCorpus:
    chunks: tuple[BenchChunk, ...]

    def by_id(self, chunk_id: str) -> BenchChunk | None:
        return next((chunk for chunk in self.chunks if chunk.chunk_id == chunk_id), None)

    @property
    def fingerprint(self) -> str:
        """Huella del corpus. Dos corpus iguales dan la misma; uno distinto, otra."""
        payload = "\x1f".join(
            f"{c.chunk_id}\x1e{c.embedded_text or c.content}" for c in self.chunks
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GoldenQuery:
    """Una consulta del conjunto dorado, con su expectativa y su motivo.

    ``rationale`` no es documentación decorativa: una expectativa sin motivo
    escrito no se puede discutir, y en un conjunto dorado hecho a mano la
    discusión es el único control de calidad que hay.
    """

    id: str
    text: str
    axis: Axis
    match_kind: MatchKind
    difficulty: Difficulty
    rationale: str
    relevant: Mapping[str, int] = field(default_factory=dict)
    """``chunk_id`` → relevancia graduada (2 = responde, 1 = parcial)."""

    must_not_retrieve: tuple[str, ...] = ()
    """Chunks que serían un error devolver arriba. Diagnóstico, no permiso."""

    @property
    def expects_an_answer(self) -> bool:
        return bool(self.relevant)

    @property
    def is_diagnostic(self) -> bool:
        return self.axis in DIAGNOSTIC_AXES

    @property
    def is_confusability(self) -> bool:
        return self.axis in CONFUSABILITY_AXES


@dataclass(frozen=True, slots=True)
class GoldenSet:
    queries: tuple[GoldenQuery, ...]

    @property
    def fingerprint(self) -> str:
        payload = "\x1f".join(
            f"{q.id}\x1e{q.text}\x1e{q.axis}\x1e{json.dumps(dict(sorted(q.relevant.items())))}"
            for q in self.queries
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def by_axis(self) -> dict[Axis, tuple[GoldenQuery, ...]]:
        grouped: dict[Axis, list[GoldenQuery]] = {}
        for query in self.queries:
            grouped.setdefault(query.axis, []).append(query)
        return {axis: tuple(items) for axis, items in sorted(grouped.items())}

    @property
    def scored(self) -> tuple[GoldenQuery, ...]:
        """Las que puntúan al modelo denso: con respuesta y no diagnósticas."""
        return tuple(
            query for query in self.queries if query.expects_an_answer and not query.is_diagnostic
        )


@dataclass(frozen=True, slots=True)
class RunMetadata:
    """Con qué se produjo una corrida. Sin esto un número no significa nada.

    Los campos de tiempo y memoria describen **esta** máquina y no entran en
    ninguna comparación de calidad; se registran para separar la viabilidad
    del piloto de la del servidor futuro.
    """

    retriever: str
    model_name: str
    revision: str
    dimension: int
    normalized: bool
    document_prefix: str
    query_prefix: str
    runtime: str
    device: str
    corpus_fingerprint: str
    golden_fingerprint: str
    composition_template: str = ""
    """Plantilla con la que se compuso el texto embebido.

    Entra en :meth:`identity` porque una corrida con otra plantilla mide
    otra entrada: sin esto, dos corridas incomparables dirían que lo son.
    """

    started_at: str = ""
    load_seconds: float | None = None
    corpus_embed_seconds: float | None = None
    query_latency_p50_ms: float | None = None
    query_latency_p95_ms: float | None = None
    peak_rss_mb: float | None = None
    model_disk_mb: float | None = None
    """Tamaño del modelo en disco. Solo la corrida real puede medirlo."""

    vectors_mb_per_1000_chunks: float | None = None
    """MB de vectores por cada 1000 chunks, en coma flotante de 32 bits.

    Se calcula, no se mide: depende solo de la dimensión. Está aquí porque
    es el número que decide cuánto va a pesar el índice, y entre 768 y 1024
    dimensiones hay un 33 % de diferencia que conviene ver al comparar.
    """
    cpu: str = ""
    ram_gb: float | None = None
    gpu: str = "none"
    notes: tuple[str, ...] = ()

    def identity(self) -> Mapping[str, object]:
        """Lo que define la corrida sin depender de la máquina ni del reloj."""
        return {
            "retriever": self.retriever,
            "model_name": self.model_name,
            "revision": self.revision,
            "dimension": self.dimension,
            "normalized": self.normalized,
            "document_prefix": self.document_prefix,
            "query_prefix": self.query_prefix,
            "corpus_fingerprint": self.corpus_fingerprint,
            "golden_fingerprint": self.golden_fingerprint,
            "composition_template": self.composition_template,
        }
