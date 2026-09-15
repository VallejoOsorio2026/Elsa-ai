"""Adaptador **experimental** de ONNX Runtime para el banco. Fase 1: FP32.

**No es un adaptador productivo y no debe convertirse en uno sin un ADR.**
Existe para responder una sola pregunta, que el Bloque 4.6 dejó abierta:

    ¿ONNX Runtime reproduce el espacio vectorial de BGE-M3 que hoy produce
    PyTorch/SentenceTransformers, o produce otro?

Mismo `model_id` y misma `revision` **no** implican los mismos vectores. El
runtime, el orden de las operaciones, el pooling y la tokenización pueden
diferir sin que nada falle: el índice parecería correcto y ordenaría mal. Este
módulo está escrito para que cada una de esas diferencias sea visible en vez de
silenciosa, y por eso rechaza ruidosamente lo que otro código daría por
supuesto.

Cuatro decisiones que este archivo encarna:

**No importa torch ni sentence-transformers, ni directamente ni en diferido.**
El objetivo del bloque es un runtime sin PyTorch residente; un import perdido
lo anularía sin que se note. Hay una prueba que lo comprueba sobre
`sys.modules`.

**No toca la red.** El modelo, el tokenizador y las configuraciones se abren
por ruta local explícita. No se usa `huggingface_hub`, no se resuelve ningún
repositorio remoto y no hay descarga automática: si un archivo falta, se dice
cuál falta.

**La sesión de ONNX Runtime está detrás de una frontera estrecha.**
`OnnxRuntimeSession` es lo único que conoce `onnxruntime` y `numpy`; convierte
los tensores y devuelve listas planas con su forma declarada. Todo lo demás
—selección de la salida, pooling CLS, normalización y validación— es Python
puro y se puede probar sin instalar ni ONNX Runtime ni numpy.

**Nada se infiere en silencio.** Ni que `outputs[0]` sea la salida buena, ni
que el grafo acepte `token_type_ids`, ni cuál es el truncamiento. Lo que no se
puede determinar a partir de los archivos locales detiene la ejecución.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from elsa.bench.ports import ModelUnavailableError

__all__ = [
    "LocalTokenizer",
    "OnnxEmbedder",
    "OnnxGraphError",
    "OnnxInputSpec",
    "OnnxModelPaths",
    "OnnxOutput",
    "OnnxRuntimeSession",
    "OnnxVectorError",
    "SnapshotInventory",
    "TokenizedText",
    "VectorDiagnostics",
]

# La única salida que este adaptador acepta como estados por token. Se prefiere
# por nombre, pero solo después de verificar su forma: un nombre no es una
# garantía.
_PREFERRED_OUTPUT = "last_hidden_state"

# Lo único que este adaptador sabe construir. Un grafo que pida otra cosa se
# rechaza en vez de recibir ceros con buena fe.
_SUPPLIABLE_INPUTS = ("input_ids", "attention_mask", "token_type_ids")

_ONNX_INT_TYPES = {"tensor(int64)": "int64", "tensor(int32)": "int32"}


class OnnxGraphError(Exception):
    """El grafo no encaja con el pipeline esperado de BGE-M3.

    Es un error de incompatibilidad, no de configuración: significa que el
    modelo exportado no expone lo que este adaptador necesita, y la respuesta
    correcta es detenerse y reportarlo, no adaptarse a lo que haya.
    """


class OnnxVectorError(Exception):
    """El vector producido no es utilizable: dimensión, NaN/Inf o norma cero."""


@dataclass(frozen=True, slots=True)
class OnnxInputSpec:
    """Una entrada que el grafo declara, con el tipo que pide."""

    name: str
    onnx_type: str

    @property
    def integer_kind(self) -> str:
        kind = _ONNX_INT_TYPES.get(self.onnx_type)
        if kind is None:
            raise OnnxGraphError(
                f"input {self.name!r} has type {self.onnx_type!r}; this adapter only feeds "
                f"integer tensors ({', '.join(sorted(_ONNX_INT_TYPES))})"
            )
        return kind


@dataclass(frozen=True, slots=True)
class OnnxOutput:
    """Una salida del grafo, aplanada y con su forma real declarada.

    La forma viene de la ejecución, no del grafo: los grafos exportados
    declaran ejes simbólicos (`batch`, `sequence`) que no se pueden comparar
    con nada.
    """

    name: str
    shape: tuple[int, ...]
    values: Sequence[float]


@dataclass(frozen=True, slots=True)
class TokenizedText:
    """Lo que el tokenizador produjo para un texto, con su huella.

    `input_ids` y `attention_mask` se guardan completos **y** resumidos: los
    completos permiten comparar dos runtimes token a token; las huellas
    permiten comparar rápido y citar la diferencia en un informe.
    """

    text_sha256: str
    input_ids: tuple[int, ...]
    attention_mask: tuple[int, ...]
    truncated: bool

    @property
    def length(self) -> int:
        return len(self.input_ids)

    @property
    def input_ids_sha256(self) -> str:
        return _digest_of_ints(self.input_ids)

    @property
    def attention_mask_sha256(self) -> str:
        return _digest_of_ints(self.attention_mask)

    @property
    def special_tokens(self) -> tuple[int, int]:
        """Primer y último identificador. En XLM-R son `<s>` y `</s>`."""
        if not self.input_ids:
            raise OnnxGraphError("the tokenizer produced an empty sequence")
        return self.input_ids[0], self.input_ids[-1]


@dataclass(frozen=True, slots=True)
class VectorDiagnostics:
    """Un vector y todo lo que hizo falta para producirlo.

    Las dos normas son el dato que separa «el runtime calcula distinto» de
    «el runtime normaliza distinto»: si `norm_before` coincide entre dos
    runtimes, la diferencia no está en el encoder.
    """

    tokenized: TokenizedText
    vector: tuple[float, ...]
    norm_before: float
    norm_after: float


class TokenizerLike(Protocol):
    """Lo mínimo que el adaptador necesita de un tokenizador."""

    def encode_one(self, text: str) -> TokenizedText: ...

    def describe(self) -> Mapping[str, object]: ...

    @property
    def pad_id(self) -> int | None: ...


class SessionLike(Protocol):
    """Lo mínimo que el adaptador necesita de una sesión de inferencia."""

    def input_specs(self) -> tuple[OnnxInputSpec, ...]: ...

    def output_names(self) -> tuple[str, ...]: ...

    def run(
        self,
        feeds: Mapping[str, Sequence[Sequence[int]]],
        *,
        only: str | None = None,
    ) -> tuple[OnnxOutput, ...]: ...

    def describe(self) -> Mapping[str, object]: ...


# ---------------------------------------------------------------------
# Inventario del snapshot local
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OnnxModelPaths:
    """Rutas locales explícitas. Ninguna se resuelve contra la red.

    `external_data` es el archivo de pesos que acompaña a un `.onnx` mayor de
    2 GB (`model.onnx_data`). ONNX Runtime lo resuelve **por su nombre y
    relativo al `.onnx`**, así que no se le pasa: se comprueba que esté al
    lado y se registra su huella.
    """

    model: Path
    tokenizer: Path
    sentence_bert_config: Path
    tokenizer_config: Path | None = None
    external_data: Path | None = None

    @classmethod
    def from_snapshot(cls, snapshot: Path, *, onnx_subdir: str = "onnx") -> "OnnxModelPaths":
        """Compone las rutas de un snapshot de HuggingFace ya descargado.

        No comprueba que existan: eso es :meth:`inventory`, que existe para
        poder informar de lo que falta sin lanzar.
        """
        root = Path(snapshot)
        onnx_dir = root / onnx_subdir
        model = onnx_dir / "model.onnx"
        external = onnx_dir / "model.onnx_data"
        return cls(
            model=model,
            tokenizer=root / "tokenizer.json",
            sentence_bert_config=root / "sentence_bert_config.json",
            tokenizer_config=root / "tokenizer_config.json",
            external_data=external,
        )

    def inventory(self) -> "SnapshotInventory":
        """Qué hay y qué no, sin lanzar. Es lo que el operador ejecuta primero."""
        return SnapshotInventory(
            entries=tuple(
                (label, path, path.is_file(), path.stat().st_size if path.is_file() else None)
                for label, path in (
                    ("model", self.model),
                    ("external_data", self.external_data),
                    ("tokenizer", self.tokenizer),
                    ("sentence_bert_config", self.sentence_bert_config),
                    ("tokenizer_config", self.tokenizer_config),
                )
                if path is not None
            )
        )

    def require(self) -> None:
        """Falla nombrando **todos** los archivos que faltan, no solo el primero."""
        missing = [
            f"{label}: {path}"
            for label, path in (
                ("model", self.model),
                ("tokenizer", self.tokenizer),
                ("sentence_bert_config", self.sentence_bert_config),
            )
            if not path.is_file()
        ]
        if missing:
            raise ModelUnavailableError(
                "the ONNX snapshot is incomplete; nothing is downloaded automatically. "
                "Missing: " + "; ".join(missing)
            )


@dataclass(frozen=True, slots=True)
class SnapshotInventory:
    """Presencia y tamaño de cada archivo esperado del snapshot."""

    entries: tuple[tuple[str, Path, bool, int | None], ...]

    @property
    def complete(self) -> bool:
        required = {"model", "tokenizer", "sentence_bert_config"}
        return all(present for label, _, present, _ in self.entries if label in required)

    def as_dict(self) -> dict[str, dict[str, object]]:
        return {
            label: {
                "path": str(path),
                "present": present,
                "size_bytes": size,
            }
            for label, path, present, size in self.entries
        }

    def render(self) -> str:
        lines = ["archivo              presente  tamaño        ruta"]
        for label, path, present, size in self.entries:
            megabytes = "-" if size is None else f"{size / 1024 / 1024:,.1f} MB"
            lines.append(f"{label:<20} {'sí' if present else 'NO':<9} {megabytes:<13} {path}")
        lines.append("")
        lines.append("completo: " + ("sí" if self.complete else "NO"))
        return "\n".join(lines)


# ---------------------------------------------------------------------
# Tokenizador local
# ---------------------------------------------------------------------


class LocalTokenizer:
    """`tokenizers` sobre un `tokenizer.json` local. Sin red y sin transformers.

    El truncamiento **no se adivina**: sale de `sentence_bert_config.json`, que
    es el archivo que SentenceTransformers lee para fijar `max_seq_length`. Si
    no está, esto falla. Inferir un límite sería introducir exactamente la
    divergencia silenciosa que el experimento busca detectar.
    """

    def __init__(
        self,
        tokenizer: Any,
        *,
        max_length: int,
        max_length_source: str,
        pad_id: int | None,
    ) -> None:
        if max_length < 1:
            raise OnnxGraphError("max_seq_length must be a positive integer")
        self._tokenizer = tokenizer
        self._max_length = max_length
        self._max_length_source = max_length_source
        self._pad_id = pad_id

    @classmethod
    def from_paths(cls, paths: OnnxModelPaths) -> "LocalTokenizer":
        paths.require()
        # El truncamiento se valida **antes** de tocar la dependencia opcional:
        # un `sentence_bert_config.json` sin `max_seq_length` es un problema del
        # snapshot, y decir «falta tokenizers» lo habría escondido.
        config = json.loads(paths.sentence_bert_config.read_text(encoding="utf-8"))
        max_length = config.get("max_seq_length")
        if not isinstance(max_length, int):
            raise OnnxGraphError(
                f"{paths.sentence_bert_config} does not declare an integer 'max_seq_length'; "
                "the truncation length is not guessed"
            )

        try:
            from tokenizers import Tokenizer
        except ImportError as error:  # pragma: no cover - depende del extra
            raise ModelUnavailableError(
                "the 'tokenizers' package is not installed; it belongs to the experimental "
                "extra. See docs/bench-onnx-experimental.md"
            ) from error

        tokenizer = Tokenizer.from_file(str(paths.tokenizer))
        # El truncamiento se declara aquí y no se hereda de lo que traiga el
        # `tokenizer.json`: dos fuentes para el mismo límite acaban divergiendo.
        tokenizer.no_truncation()
        tokenizer.no_padding()
        tokenizer.enable_truncation(max_length=max_length)

        pad_id = _read_pad_id(paths)
        return cls(
            tokenizer,
            max_length=max_length,
            max_length_source=paths.sentence_bert_config.name,
            pad_id=pad_id,
        )

    @property
    def pad_id(self) -> int | None:
        return self._pad_id

    @property
    def max_length(self) -> int:
        return self._max_length

    def encode_one(self, text: str) -> TokenizedText:
        encoding = self._tokenizer.encode(text)
        ids = tuple(int(value) for value in encoding.ids)
        mask = tuple(int(value) for value in encoding.attention_mask)
        return TokenizedText(
            text_sha256=_digest_of_text(text),
            input_ids=ids,
            attention_mask=mask,
            truncated=len(ids) >= self._max_length,
        )

    def describe(self) -> Mapping[str, object]:
        return {
            "max_length": self._max_length,
            "max_length_source": self._max_length_source,
            "pad_id": self._pad_id,
            "truncation": "right",
        }


def _read_pad_id(paths: OnnxModelPaths) -> int | None:
    """Identificador de relleno, si los archivos locales lo declaran.

    Solo hace falta cuando se agrupan varios textos en un lote. Con lote de 1
    —el modo del experimento— no se rellena nada, así que no encontrarlo no es
    un error aquí: lo es más tarde, y solo si alguien sube el lote.
    """
    raw = json.loads(paths.tokenizer.read_text(encoding="utf-8"))
    padding = raw.get("padding")
    if isinstance(padding, dict) and isinstance(padding.get("pad_id"), int):
        return int(padding["pad_id"])
    if paths.tokenizer_config is not None and paths.tokenizer_config.is_file():
        config = json.loads(paths.tokenizer_config.read_text(encoding="utf-8"))
        pad = config.get("pad_token")
        if isinstance(pad, dict):
            pad = pad.get("content")
        if isinstance(pad, str):
            vocab = raw.get("model", {}).get("vocab")
            if isinstance(vocab, dict) and pad in vocab:
                return int(vocab[pad])
            added = raw.get("added_tokens")
            if isinstance(added, list):
                for token in added:
                    if isinstance(token, dict) and token.get("content") == pad:
                        return int(token["id"])
    return None


# ---------------------------------------------------------------------
# Sesión de ONNX Runtime
# ---------------------------------------------------------------------


class OnnxRuntimeSession:
    """Frontera estrecha con `onnxruntime`. Es lo único que importa numpy.

    Devuelve las salidas **aplanadas** con su forma real. Convertir aquí y no
    en el adaptador es lo que permite probar la selección de salida, el pooling
    y la validación sin instalar ni ONNX Runtime ni numpy.
    """

    def __init__(self, session: Any, *, provider: str, version: str) -> None:
        self._session = session
        self._provider = provider
        self._version = version

    @classmethod
    def open(cls, model_path: Path, *, threads: int | None = None) -> "OnnxRuntimeSession":
        """Abre el `.onnx` local **solo** con `CPUExecutionProvider`.

        El proveedor se pasa explícito y único. Dejar que ONNX Runtime elija
        haría que el resultado dependiera de qué paquete esté instalado, y una
        corrida que no sabe en qué dispositivo corrió no es una medición.
        """
        try:
            import onnxruntime
        except ImportError as error:  # pragma: no cover - depende del extra
            raise ModelUnavailableError(
                "onnxruntime is not installed; it belongs to the experimental extra. "
                "See docs/bench-onnx-experimental.md"
            ) from error

        if not model_path.is_file():
            raise ModelUnavailableError(f"the ONNX model is not at {model_path}")

        options = onnxruntime.SessionOptions()
        if threads is not None:
            options.intra_op_num_threads = threads
        session = onnxruntime.InferenceSession(
            str(model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        actual = tuple(session.get_providers())
        if actual != ("CPUExecutionProvider",):
            raise OnnxGraphError(
                f"the session resolved providers {actual}, but this experiment runs on "
                "CPUExecutionProvider only"
            )
        return cls(session, provider="CPUExecutionProvider", version=onnxruntime.__version__)

    def input_specs(self) -> tuple[OnnxInputSpec, ...]:
        return tuple(
            OnnxInputSpec(name=meta.name, onnx_type=meta.type)
            for meta in self._session.get_inputs()
        )

    def output_names(self) -> tuple[str, ...]:
        return tuple(meta.name for meta in self._session.get_outputs())

    def run(
        self,
        feeds: Mapping[str, Sequence[Sequence[int]]],
        *,
        only: str | None = None,
    ) -> tuple[OnnxOutput, ...]:
        import numpy as np

        kinds = {spec.name: spec.integer_kind for spec in self.input_specs()}
        prepared = {
            name: np.asarray(rows, dtype=np.int64 if kinds[name] == "int64" else np.int32)
            for name, rows in feeds.items()
        }
        names = [only] if only is not None else list(self.output_names())
        outputs = self._session.run(names, prepared)
        return tuple(
            OnnxOutput(name=name, shape=tuple(int(x) for x in array.shape), values=_flat(array))
            for name, array in zip(names, outputs, strict=True)
        )

    def describe(self) -> Mapping[str, object]:
        return {
            "runtime": "onnxruntime",
            "runtime_version": self._version,
            "execution_provider": self._provider,
        }


def _flat(array: Any) -> list[float]:
    return [float(value) for value in array.reshape(-1).tolist()]


# ---------------------------------------------------------------------
# El adaptador
# ---------------------------------------------------------------------


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


class OnnxEmbedder:
    """Candidato del banco servido por ONNX Runtime. **Experimental, FP32.**

    Implementa `BenchmarkEmbedder`. Cada llamada recorre siempre los mismos
    cinco pasos, y ninguno se salta en silencio:

    1. tokenizar con el tokenizador de la **misma** revisión;
    2. alimentar **solo** las entradas que el grafo declara;
    3. elegir la salida de estados por token verificando su forma;
    4. tomar la posición 0 (pooling CLS) y normalizar en L2;
    5. rechazar el vector si no mide lo declarado, si no es finito o si su
       norma es cero.
    """

    def __init__(
        self,
        session: SessionLike,
        tokenizer: TokenizerLike,
        *,
        model_name: str,
        revision: str,
        dimension: int,
        document_prefix: str = "",
        query_prefix: str = "",
        batch_size: int = 1,
    ) -> None:
        if dimension < 1:
            raise OnnxGraphError("dimension must be a positive integer")
        if batch_size < 1:
            raise OnnxGraphError("batch size must be a positive integer")
        self._session = session
        self._tokenizer = tokenizer
        self._dimension = dimension
        self._batch_size = batch_size
        self._model_name = model_name
        self._revision = revision
        self._document_prefix = document_prefix
        self._query_prefix = query_prefix
        self._selected_output: str | None = None
        self._selection_reason: str = "not selected yet"

    @classmethod
    def from_local_files(
        cls,
        paths: OnnxModelPaths,
        *,
        model_name: str,
        revision: str,
        dimension: int,
        document_prefix: str = "",
        query_prefix: str = "",
        batch_size: int = 1,
        threads: int | None = None,
    ) -> "OnnxEmbedder":
        """Construye desde rutas locales. No descarga nada y no usa la red."""
        paths.require()
        return cls(
            OnnxRuntimeSession.open(paths.model, threads=threads),
            LocalTokenizer.from_paths(paths),
            model_name=model_name,
            revision=revision,
            dimension=dimension,
            document_prefix=document_prefix,
            query_prefix=query_prefix,
            batch_size=batch_size,
        )

    # -- contrato del banco ------------------------------------------------

    def describe(self) -> _Description:
        return _Description(
            model_name=self._model_name,
            revision=self._revision,
            dimension=self._dimension,
            normalized=True,
            document_prefix=self._document_prefix,
            query_prefix=self._query_prefix,
            runtime="onnxruntime",
            device="cpu",
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [list(record.vector) for record in self.encode_documents(texts)]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return [list(record.vector) for record in self.encode_queries(texts)]

    # -- diagnóstico -------------------------------------------------------

    def encode_documents(self, texts: Sequence[str]) -> list[VectorDiagnostics]:
        return self._encode(texts, self._document_prefix)

    def encode_queries(self, texts: Sequence[str]) -> list[VectorDiagnostics]:
        return self._encode(texts, self._query_prefix)

    def runtime_details(self) -> dict[str, object]:
        """Qué se usó de verdad. Entra en el manifiesto del experimento."""
        return {
            **dict(self._session.describe()),
            "precision": "fp32",
            "pooling": "cls",
            "normalization": "l2",
            "batch_size": self._batch_size,
            "declared_inputs": [spec.name for spec in self._session.input_specs()],
            "graph_outputs": list(self._session.output_names()),
            "selected_output": self._selected_output,
            "selected_output_reason": self._selection_reason,
            "tokenizer": dict(self._tokenizer.describe()),
        }

    # -- interior ----------------------------------------------------------

    def _encode(self, texts: Sequence[str], prefix: str) -> list[VectorDiagnostics]:
        if not texts:
            return []
        records: list[VectorDiagnostics] = []
        # El orden de salida es el de entrada, lote a lote. No se reordena por
        # longitud: el banco cruza los vectores con los chunks por posición.
        for start in range(0, len(texts), self._batch_size):
            batch = [prefix + text for text in texts[start : start + self._batch_size]]
            records.extend(self._encode_batch(batch))
        return records

    def _encode_batch(self, texts: Sequence[str]) -> list[VectorDiagnostics]:
        tokenized = [self._tokenizer.encode_one(text) for text in texts]
        width = max(item.length for item in tokenized)
        ids, mask = self._pad(tokenized, width)

        feeds: dict[str, Sequence[Sequence[int]]] = {}
        for spec in self._session.input_specs():
            if spec.name == "input_ids":
                feeds[spec.name] = ids
            elif spec.name == "attention_mask":
                feeds[spec.name] = mask
            elif spec.name == "token_type_ids":
                # XLM-R no usa segmentos. Si el grafo exportado lo pide igual,
                # ceros es lo que HuggingFace alimenta; queda registrado en
                # `runtime_details()` para que no pase inadvertido.
                feeds[spec.name] = [[0] * width for _ in tokenized]
            else:
                raise OnnxGraphError(
                    f"the graph requires input {spec.name!r}, which this adapter does not know "
                    f"how to build; it only supplies {_SUPPLIABLE_INPUTS}"
                )
        missing = {"input_ids"} - set(feeds)
        if missing:
            raise OnnxGraphError(
                "the graph does not declare 'input_ids'; it does not look like a text encoder "
                f"(declared: {[spec.name for spec in self._session.input_specs()]})"
            )

        outputs = self._session.run(feeds, only=self._selected_output)
        states = self._token_states(outputs, batch=len(tokenized), width=width)
        return [
            self._pool(states, index=index, width=width, tokenized=item)
            for index, item in enumerate(tokenized)
        ]

    def _pad(
        self, tokenized: Sequence[TokenizedText], width: int
    ) -> tuple[list[list[int]], list[list[int]]]:
        if all(item.length == width for item in tokenized):
            return (
                [list(item.input_ids) for item in tokenized],
                [list(item.attention_mask) for item in tokenized],
            )
        pad_id = self._tokenizer.pad_id
        if pad_id is None:
            raise OnnxGraphError(
                "this batch mixes sequence lengths and the local files do not declare a pad "
                "token id; run with batch size 1 or supply a tokenizer that declares one"
            )
        ids = [list(item.input_ids) + [pad_id] * (width - item.length) for item in tokenized]
        mask = [list(item.attention_mask) + [0] * (width - item.length) for item in tokenized]
        return ids, mask

    def _token_states(self, outputs: Sequence[OnnxOutput], *, batch: int, width: int) -> OnnxOutput:
        """Elige la salida de estados por token, verificando la forma.

        Nunca se toma `outputs[0]`. Una salida de rango 2 —`pooler_output`,
        `sentence_embedding`— queda excluida por construcción: el pooling CLS
        de BGE-M3 se aplica sobre los estados por token, y usar una cabeza ya
        agrupada produciría un vector plausible de **otro** espacio.
        """
        expected = (batch, width, self._dimension)
        candidates = [output for output in outputs if tuple(output.shape) == expected]
        if not candidates:
            detail = ", ".join(f"{o.name}{tuple(o.shape)}" for o in outputs) or "none"
            raise OnnxGraphError(
                f"no graph output has the shape of per-token states {expected}; "
                f"outputs were: {detail}. This adapter does not fall back to outputs[0]"
            )
        named = [output for output in candidates if output.name == _PREFERRED_OUTPUT]
        if named:
            chosen, reason = named[0], f"name {_PREFERRED_OUTPUT!r} with verified shape {expected}"
        elif len(candidates) == 1:
            chosen = candidates[0]
            reason = f"only output with per-token shape {expected}"
        else:
            names = ", ".join(output.name for output in candidates)
            raise OnnxGraphError(
                f"several outputs have the shape of per-token states ({names}); the adapter "
                "will not guess which one carries the encoder states"
            )
        if self._selected_output is None:
            self._selected_output = chosen.name
            self._selection_reason = reason
        return chosen

    def _pool(
        self, states: OnnxOutput, *, index: int, width: int, tokenized: TokenizedText
    ) -> VectorDiagnostics:
        # Pooling CLS: la posición 0 de la secuencia. El relleno va a la
        # derecha, así que nunca alcanza esta posición.
        start = (index * width) * self._dimension
        raw = states.values[start : start + self._dimension]
        return _finish(raw, dimension=self._dimension, tokenized=tokenized)


def _finish(raw: Sequence[float], *, dimension: int, tokenized: TokenizedText) -> VectorDiagnostics:
    """Valida y normaliza. Cada rechazo aquí es un fallo que no llega al índice."""
    if len(raw) != dimension:
        raise OnnxVectorError(
            f"the pooled vector has {len(raw)} components but {dimension} were declared; "
            "it is not truncated or padded: it belongs to a different vector space"
        )
    for position, value in enumerate(raw):
        if not math.isfinite(value):
            raise OnnxVectorError(
                f"the pooled vector has a non-finite value ({value!r}) at position {position}"
            )
    norm = math.sqrt(math.fsum(value * value for value in raw))
    if norm == 0.0:
        raise OnnxVectorError(
            "the pooled vector has zero norm; cosine similarity is undefined and the vector "
            "would rank against everything equally"
        )
    # Cada componente vuelve a float32 después de dividir: el vector que se
    # compara tiene que ser el que se almacenaría, no un float64 intermedio.
    vector = tuple(_to_float32(value / norm) for value in raw)
    after = math.sqrt(math.fsum(value * value for value in vector))
    return VectorDiagnostics(tokenized=tokenized, vector=vector, norm_before=norm, norm_after=after)


def _to_float32(value: float) -> float:
    import struct

    return float(struct.unpack("<f", struct.pack("<f", value))[0])


def _digest_of_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_of_ints(values: Sequence[int]) -> str:
    payload = ",".join(str(int(value)) for value in values)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()
