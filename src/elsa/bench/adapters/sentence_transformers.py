"""Adaptador de los candidatos reales, vía `sentence-transformers`.

**No se ejecutó en este bloque.** El entorno donde se escribió tiene
`huggingface.co` bloqueado por política de egreso (403 a CONNECT), así que
los pesos no se pudieron descargar y ninguno de los tres candidatos se midió.
El código queda listo y el procedimiento reproducible está en
`docs/embedding-benchmark.md`.

Dos cosas que este archivo resuelve y que son la razón de que exista:

- **Los prefijos no son opcionales.** EmbeddingGemma exige
  `title: none | text: ` en el pasaje y `task: search result | query: ` en la
  consulta; Qwen3-Embedding es *instruction-aware* y espera una instrucción
  en la consulta y el pasaje en crudo; BGE-M3 no usa ninguno. Medir los tres
  con el mismo trato favorecería sistemáticamente al que no los necesita.
- **La dependencia es opcional.** `sentence-transformers` y `torch` no están
  en `pyproject.toml`: pesan cientos de megas y el runtime de ELSA no los
  necesita. Si faltan, esto lanza `ModelUnavailableError` y el informe
  registra el candidato como **sin medir**, que es la verdad.

Los prefijos de abajo provienen de la investigación de
`docs/embeddings-model-evaluation.md` y están marcados allí como **no
verificados contra fuente primaria**, por el mismo bloqueo de red.
Reverificarlos contra la tarjeta del modelo es el primer paso de cualquier
corrida real; la constante vive aquí para que sea un solo sitio que corregir.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from elsa.bench.ports import ModelUnavailableError

__all__ = ["CANDIDATES", "CandidateSpec", "SentenceTransformerEmbedder"]


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    """Cómo se mide un candidato. Todo lo que cambia entre modelos vive aquí."""

    key: str
    model_name: str
    revision: str
    """Revisión de los pesos.

    Hoy es ``main`` en los tres, que es una referencia **móvil**: lo que se
    descargue mañana puede no ser lo que se midió. Antes de la primera
    corrida real hay que fijar aquí el commit o el digest de cada modelo, al
    reverificar su tarjeta. ADR 0013 §2 lo exige precisamente porque la
    identidad del espacio vectorial tiene que ser inmutable, y las huellas
    del informe cubren corpus y conjunto dorado, nunca los pesos.
    """

    expected_dimension: int
    document_prefix: str
    query_prefix: str
    normalize: bool
    license_name: str
    production_eligible: bool
    """Si puede elegirse para producción. Medir no habilita (decisión D1)."""

    notes: str = ""


# Los tres candidatos obligatorios del Bloque 4.2.a.
CANDIDATES: tuple[CandidateSpec, ...] = (
    CandidateSpec(
        key="bge-m3",
        model_name="BAAI/bge-m3",
        revision="main",
        expected_dimension=1024,
        document_prefix="",
        query_prefix="",
        normalize=True,
        license_name="MIT",
        production_eligible=True,
        notes="Sin prefijos. Unico con canal lexico propio (denso+disperso+ColBERT).",
    ),
    CandidateSpec(
        key="qwen3-0.6b",
        model_name="Qwen/Qwen3-Embedding-0.6B",
        revision="main",
        expected_dimension=1024,
        document_prefix="",
        query_prefix=(
            "Instruct: Given a maintenance question in Spanish, retrieve the "
            "technical passage that answers it\nQuery: "
        ),
        normalize=True,
        license_name="Apache-2.0",
        production_eligible=True,
        notes="Instruction-aware: instruccion solo en la consulta, pasaje en crudo.",
    ),
    CandidateSpec(
        key="embeddinggemma-300m",
        model_name="google/embeddinggemma-300m",
        revision="main",
        expected_dimension=768,
        document_prefix="title: none | text: ",
        query_prefix="task: search result | query: ",
        normalize=True,
        license_name="Gemma Terms of Use",
        production_eligible=False,
        notes=(
            "Aprobado para el banco, NO elegible para produccion hasta validar "
            "formalmente la licencia para uso corporativo (decision D1)."
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class _Description:
    model_name: str
    revision: str
    dimension: int
    normalized: bool
    document_prefix: str
    query_prefix: str
    runtime: str
    device: str


class SentenceTransformerEmbedder:
    """Envuelve un modelo de `sentence-transformers` para el banco."""

    def __init__(self, spec: CandidateSpec, *, device: str = "cpu", batch_size: int = 16) -> None:
        self._spec = spec
        self._device = device
        self._batch_size = batch_size
        self._model = _load(spec, device)
        dimension = int(self._model.get_sentence_embedding_dimension())
        self._notes: tuple[str, ...] = ()
        if dimension != spec.expected_dimension:
            # No se aborta: se registra. La dimensión esperada venía de una
            # fuente sin verificar, y la del modelo cargado es la verdad.
            self._notes = (
                f"dimension {dimension} differs from the unverified expected "
                f"{spec.expected_dimension}",
            )
        else:
            self._notes = ()
        self._dimension = dimension

    @property
    def spec(self) -> CandidateSpec:
        return self._spec

    @property
    def notes(self) -> tuple[str, ...]:
        return self._notes

    def describe(self) -> _Description:
        return _Description(
            model_name=self._spec.model_name,
            revision=self._spec.revision,
            dimension=self._dimension,
            normalized=self._spec.normalize,
            document_prefix=self._spec.document_prefix,
            query_prefix=self._spec.query_prefix,
            runtime="sentence-transformers",
            device=self._device,
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([self._spec.document_prefix + text for text in texts])

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([self._spec.query_prefix + text for text in texts])

    def _encode(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._model.encode(
            list(texts),
            batch_size=self._batch_size,
            normalize_embeddings=self._spec.normalize,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [[float(value) for value in row] for row in vectors]


def _load(spec: CandidateSpec, device: str) -> Any:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise ModelUnavailableError(
            "sentence-transformers is not installed; it is an optional dependency of the "
            "benchmark only. See docs/embedding-benchmark.md"
        ) from error
    try:
        return SentenceTransformer(
            spec.model_name,
            revision=spec.revision,
            device=device,
            # Explícito y no por defecto: este es el único punto del
            # proyecto que descarga artefactos de terceros, y que no se
            # ejecute código del repositorio remoto tiene que ser una
            # propiedad auditable, no el valor por defecto de una versión.
            trust_remote_code=False,
        )
    except Exception as error:  # noqa: BLE001 - cualquier fallo deja el candidato sin medir
        raise ModelUnavailableError(
            f"could not load {spec.model_name!r}: {type(error).__name__}"
        ) from error
