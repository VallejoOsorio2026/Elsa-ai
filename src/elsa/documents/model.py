"""Estructuras del conocimiento documental.

Son datos puros, sin identificadores de base y sin decisiones tomadas: una
sección, un chunk y la política que los produjo. La persistencia, la
comparación con la versión publicada y la publicación ocurren después, sobre
estas estructuras.

Todo lo que aquí se calcula es **determinístico**. Ningún campo depende del
reloj, de un UUID aleatorio ni del orden de un diccionario, porque de eso
depende que reprocesar el mismo documento con la misma política produzca
exactamente los mismos hashes.
"""

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from math import ceil

from elsa.ingestion.model import IngestionWarning

__all__ = [
    "ChunkKind",
    "ChunkingPolicy",
    "DocumentChunk",
    "DocumentSection",
    "DocumentStructure",
    "content_hash",
    "estimate_tokens",
    "normalize_text",
]

_WHITESPACE = re.compile(r"[ \t]+")


class ChunkKind(StrEnum):
    """Qué clase de contenido predomina en un chunk.

    No es decoración: la fase de recuperación tratará distinto una tabla que
    un párrafo, y una advertencia distinto que un paso. Registrarlo ahora
    evita tener que reprocesar todo el corpus para saberlo después.
    """

    PROSE = "prose"
    LIST = "list"
    STEPS = "steps"
    WARNING = "warning"
    TABLE = "table"
    MIXED = "mixed"


def normalize_text(value: str) -> str:
    """Forma canónica de un texto, para hashearlo y compararlo.

    Colapsa espacios y tabuladores dentro de cada línea y recorta los
    extremos, pero **conserva los saltos de línea**: en una tabla, el salto
    separa filas y borrarlo cambiaría el dato.
    """
    lines = [_WHITESPACE.sub(" ", line).strip() for line in value.split("\n")]
    return "\n".join(lines).strip()


def content_hash(value: str) -> str:
    """SHA-256 del texto normalizado."""
    return hashlib.sha256(normalize_text(value).encode("utf-8")).hexdigest()


def estimate_tokens(value: str, *, chars_per_token: int = 4) -> int:
    """Estimación determinística del tamaño en tokens.

    **No es un tokenizador.** No hay ninguno todavía: el modelo de
    embeddings se decide en el Bloque 4.2, y atarse hoy al vocabulario de un
    modelo concreto obligaría a re-chunkear todo el corpus al cambiarlo.

    La aproximación por caracteres es grosera pero tiene la propiedad que
    aquí hace falta: es estable, no depende de ninguna descarga y produce el
    mismo número en cualquier máquina. ``chars_per_token`` es un parámetro de
    la política, de modo que ajustarlo al tokenizador real cuando exista es
    cambiar un número en la configuración, no reescribir el chunker. El
    perfil de chunking que se persiste con cada versión deja constancia de
    qué valor se usó.
    """
    text = normalize_text(value)
    if not text:
        return 0
    return max(1, ceil(len(text) / chars_per_token))


@dataclass(frozen=True, slots=True)
class ChunkingPolicy:
    """Parámetros del chunking. Se persisten con cada versión.

    Guardarlos no es burocracia: dos versiones chunkeadas con límites
    distintos no son comparables, y sin el registro de qué límites se usaron
    nadie podría saber si una diferencia entre versiones viene del documento
    o de un cambio de configuración.
    """

    name: str = "structural-v1"

    target_tokens: int = 350
    """Tamaño al que se apunta. Un chunk se cierra al superarlo."""

    max_tokens: int = 700
    """Techo duro. Por encima, una unidad se parte aunque sea prosa corrida."""

    min_tokens: int = 60
    """Por debajo, un chunk se fusiona con el anterior de su misma sección.

    Un chunk de una línea suelta no aporta contexto suficiente para
    responder nada, y sí ensucia cualquier recuperación posterior.
    """

    overlap_tokens: int = 50
    """Solape entre chunks, **solo** en cortes provocados por el tamaño.

    Un corte estructural (cambia de sección, empieza una tabla, aparece una
    advertencia) ya marca una discontinuidad real: solapar ahí duplicaría
    texto sin añadir continuidad. Un corte por tamaño parte una idea a la
    mitad, y ahí el solape sí evita perder el hilo.
    """

    chars_per_token: int = 4
    """Divisor de :func:`estimate_tokens`. Ver la nota de esa función."""

    keep_tables_whole: bool = True
    """Una tabla ocupa su propio chunk y no se mezcla con prosa."""

    def __post_init__(self) -> None:
        if self.target_tokens <= 0 or self.max_tokens <= 0 or self.chars_per_token <= 0:
            raise ValueError("token limits must be greater than zero")
        if self.max_tokens < self.target_tokens:
            raise ValueError("max_tokens cannot be smaller than target_tokens")
        if self.min_tokens < 0 or self.min_tokens > self.target_tokens:
            raise ValueError("min_tokens must be between zero and target_tokens")
        if self.overlap_tokens < 0 or self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be between zero and target_tokens")

    def parameters(self) -> dict[str, int | str | bool]:
        """Los valores exactos, en forma serializable y ordenada."""
        return {
            "name": self.name,
            "target_tokens": self.target_tokens,
            "max_tokens": self.max_tokens,
            "min_tokens": self.min_tokens,
            "overlap_tokens": self.overlap_tokens,
            "chars_per_token": self.chars_per_token,
            "keep_tables_whole": self.keep_tables_whole,
        }

    def fingerprint(self) -> str:
        """Huella de la política. Entra en la identidad de la versión."""
        payload = "\x1f".join(
            f"{key}\x1e{value}" for key, value in sorted(self.parameters().items())
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DocumentSection:
    """Una sección del documento, con su lugar exacto en el original."""

    ordinal: int
    """Orden dentro de la versión, desde 0 y en orden de lectura."""

    path: str
    """Dirección estructural (``1``, ``1.2``, ``1.2.3``).

    Se calcula por **posición en el árbol**, no por la numeración impresa.
    Un manual con títulos sin numerar, con numeración repetida o con saltos
    seguiría necesitando una dirección única, y la posición siempre la tiene.
    La numeración impresa se conserva aparte, en :attr:`number_label`.
    """

    parent_path: str | None
    depth: int
    """Profundidad en el árbol, desde 1. ``0`` es el preámbulo."""

    title: str
    number_label: str | None = None
    """Numeración tal y como está impresa (``3.2``), si el documento la trae."""

    page_start: int | None = None
    page_end: int | None = None
    block_start: int | None = None
    block_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    is_preamble: bool = False
    """Contenido anterior al primer título. No es una sección del autor."""


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """Una unidad recuperable, con toda su procedencia.

    La procedencia no es metadato opcional: es la única forma de cumplir la
    regla 5 de ``CLAUDE.md``. Si un chunk no puede señalar qué documento, qué
    versión, qué sección y qué páginas lo produjeron, no sirve como
    evidencia, y sin evidencia no puede sustentar ninguna respuesta.
    """

    ordinal: int
    """Orden dentro de la versión, desde 0 y sin huecos."""

    structural_key: str
    """Dirección del chunk dentro de la versión: ``<sección>#<índice>``.

    Es la identidad que se usa para comparar dos versiones. Es **posicional**
    a propósito: si alguien inserta un párrafo, los chunks siguientes de esa
    sección cambian de dirección y vuelven a revisión. Es conservador —marca
    como modificado algo que quizá no cambió— y esa es la dirección correcta
    del error: dar por validado un dato que sí cambió sería mucho peor.
    """

    content: str
    content_sha256: str
    kind: ChunkKind

    section_path: str | None = None
    section_ordinal: int | None = None
    section_title: str | None = None
    index_in_section: int = 0
    heading_trail: tuple[str, ...] = ()
    """Títulos de los ancestros más el de la sección, en orden.

    Se guarda como metadato y **no** se antepone al texto del chunk: mezclar
    el encabezado con el contenido cambiaría el hash del texto y haría
    imposible saber qué decía el documento exactamente. Anteponerlo al
    indexar, si el modelo lo necesita, es decisión del Bloque 4.2.
    """

    page_start: int | None = None
    page_end: int | None = None
    block_start: int | None = None
    block_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    """Desplazamientos en el texto extraído. Cierran la cadena hasta la fuente."""

    token_estimate: int = 0
    char_length: int = 0
    overlap_chars: int = 0
    """Caracteres heredados del chunk anterior. ``0`` en un corte estructural."""

    boundary_reason: str = "structure"
    """Por qué se cerró el chunk anterior: ``structure`` o ``size``."""

    oversized: bool = False
    """Supera :attr:`ChunkingPolicy.max_tokens` y no se pudo partir más."""

    warnings: tuple[str, ...] = ()
    """Códigos de aviso propios del chunk (``table_split``, ``chunk_oversized``…)."""


@dataclass(frozen=True, slots=True)
class DocumentStructure:
    """Resultado completo de seccionar y chunkear un documento."""

    sections: tuple[DocumentSection, ...] = ()
    chunks: tuple[DocumentChunk, ...] = ()
    policy: ChunkingPolicy = field(default_factory=ChunkingPolicy)
    warnings: tuple[IngestionWarning, ...] = ()

    @property
    def structure_sha256(self) -> str:
        """Huella determinística de toda la estructura producida.

        Dos ejecuciones que dan la misma huella produjeron exactamente las
        mismas secciones y los mismos chunks. Es lo que hace comprobable la
        idempotencia sin comparar objeto por objeto, y lo que permite
        detectar que un documento distinto produjo la misma estructura.
        """
        parts: list[str] = [self.policy.fingerprint()]
        for section in self.sections:
            parts.append(
                f"S\x1e{section.path}\x1e{section.depth}\x1e{normalize_text(section.title)}"
            )
        for chunk in self.chunks:
            parts.append(f"C\x1e{chunk.structural_key}\x1e{chunk.content_sha256}")
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    def warning_counts(self) -> Mapping[str, int]:
        """Avisos agrupados por código, aptos para ``stats``.

        Códigos y conteos, nunca contenido: ``chunk_oversized: 2`` le dice a
        un revisor que hay dos chunks demasiado grandes sin revelar una sola
        línea del manual.
        """
        counts: dict[str, int] = {}
        for warning in self.warnings:
            counts[warning.code] = counts.get(warning.code, 0) + 1
        for chunk in self.chunks:
            for code in chunk.warnings:
                counts[code] = counts.get(code, 0) + 1
        return counts
