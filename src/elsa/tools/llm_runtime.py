"""Herramienta de operación del runtime de generación local.

Cinco comandos, para ejecutarse en la máquina que tiene ``llama-server``
delante —PC1, hoy— y no desde el servicio web, que nunca carga un modelo::

    check     comprueba la configuración sin hablar con nadie
    health    pregunta al runtime si tiene el modelo cargado
    generate  una generación mínima, con latencia y tokens/s
    demo      el camino RAG completo sobre evidencia SINTÉTICA, sin base
    ask       el camino RAG completo sobre el corpus real recuperado

`demo` y `ask` se separan a propósito. `ask` es la demostración del bloque
—autorización, recuperación híbrida, contexto, modelo, verificación— pero
exige PostgreSQL con conocimiento ya ingerido y embeddings generados. `demo`
recorre el mismo tramo desde el Context Builder con evidencia fabricada aquí
mismo, y por tanto sirve para comprobar el runtime **el primer día**, cuando
todavía no hay corpus. Ninguno de los dos toca datos de planta.

Esta herramienta imprime números de operación (latencia, tokens/s, tamaño del
contexto) porque son los que deciden si el hardware aguanta. No los inventa:
los que vienen del servidor se marcan como suyos.
"""

import argparse
import asyncio
import hashlib
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from elsa.adapters.llama_cpp_llm import GenerationMetrics, LlamaCppAdapter
from elsa.adapters.postgres_lexical import PostgresLexicalSearch
from elsa.adapters.postgres_vectors import PostgresVectorStore
from elsa.config import LLMBackend, Settings, load_settings
from elsa.container import build_llm_adapter
from elsa.core.answers import AnswerStatus, GroundedAnswer
from elsa.core.authorization import Scope
from elsa.ports.documents import (
    ChunkKind,
    ChunkProvenance,
    DocumentChunkRecord,
    DocumentRecord,
    DocumentSectionRecord,
    DocumentSourceKind,
    DocumentVersionRecord,
    DocumentVersionState,
)
from elsa.ports.evidence import (
    Channel,
    ChannelHit,
    Evidence,
    EvidenceRetrievalPort,
    EvidenceSet,
    EvidenceStrength,
)
from elsa.ports.llm import ChatMessage, LLMConfigurationError, LLMUnavailableError
from elsa.services.grounded_generation import GroundedGenerationService
from elsa.services.hybrid_retrieval import HybridRetrievalService
from elsa.tools.embeddings_admin import build_embeddings

__all__ = ["build_llm", "build_parser", "main", "synthetic_evidence_set"]


def build_llm(settings: Settings) -> LlamaCppAdapter:
    """Construye el adaptador desde la configuración, o explica qué falta.

    El mapeo configuración → adaptador es uno solo, el del contenedor. Aquí
    solo cambia qué significa «no hay motor»: para la aplicación es un estado
    válido —recupera y cita sin redactar—, y para esta herramienta es el
    final del camino, porque no hace otra cosa.
    """
    adapter = build_llm_adapter(settings)
    if adapter is None:
        raise LLMConfigurationError(
            "no generation runtime is configured; set ELSA_LLM_BACKEND=llama_cpp"
        )
    return adapter


def _database_url(settings: Settings) -> str:
    if settings.database_url is None:
        raise LLMConfigurationError("ELSA_DATABASE_URL is not configured")
    return settings.database_url.get_secret_value()


def _scopes(raw: Sequence[str]) -> list[Scope]:
    """`dominio` o `dominio:equipo`. Sin alcances no se recupera nada."""
    scopes: list[Scope] = []
    for item in raw:
        domain, _, equipment = item.partition(":")
        scopes.append(Scope(domain.strip(), equipment.strip() or None))
    return scopes


# ---------------------------------------------------------------------
# check / health / generate
# ---------------------------------------------------------------------


async def _check(settings: Settings, args: argparse.Namespace) -> int:
    """Lo que ELSA cree del runtime, sin mandar una sola petición."""
    print(f"backend        : {settings.llm_backend.value}")
    if settings.llm_backend is not LLMBackend.LLAMA_CPP:
        print("no hay runtime de generación configurado; ELSA recupera y cita, no redacta")
        return 0
    llm = build_llm(settings)
    try:
        print(f"url            : {llm.base_url}")
        print(f"modelo lógico  : {llm.model}")
        print(f"contexto       : {settings.llm_context_tokens} tokens")
        print(f"salida máxima  : {settings.llm_max_output_tokens} tokens")
        print(f"temperatura    : {settings.llm_temperature}")
        print(f"concurrencia   : {llm.concurrency}")
        print(f"plazo          : {llm.timeout_seconds} s")
        print(f"fuera de loopback: {'sí (declarado)' if settings.llm_allow_remote else 'no'}")
        ruta = settings.llm_model_path
        print(f"GGUF (solo scripts): {ruta if ruta is not None else 'no declarado'}")
    finally:
        await llm.aclose()
    return 0


async def _health(settings: Settings, args: argparse.Namespace) -> int:
    llm = build_llm(settings)
    started = time.monotonic()
    try:
        await llm.check_health()
    except LLMUnavailableError as error:
        print(f"no disponible: {error}", file=sys.stderr)
        return 1
    finally:
        await llm.aclose()
    print(f"listo: {llm.model} en {llm.base_url} ({(time.monotonic() - started) * 1000:.0f} ms)")
    return 0


async def _generate(settings: Settings, args: argparse.Namespace) -> int:
    """Generación mínima, sin evidencia. Mide el runtime, no el RAG."""
    llm = build_llm(settings)
    messages = (ChatMessage(role="user", content=args.prompt),)
    started = time.monotonic()
    try:
        result, metrics = await llm.complete_with_metrics(
            messages, max_tokens=settings.llm_max_output_tokens
        )
    finally:
        await llm.aclose()
    elapsed = time.monotonic() - started

    print(result.content.strip() or "(salida vacía)")
    print()
    _print_metrics(metrics, elapsed)
    return 0


def _print_metrics(metrics: GenerationMetrics | None, elapsed: float) -> None:
    print(f"latencia total : {elapsed:.2f} s")
    if metrics is None:
        return
    print(f"tokens entrada : {metrics.prompt_tokens}")
    print(f"tokens salida  : {metrics.completion_tokens}")
    if metrics.tokens_per_second is not None:
        source = (
            "medidos por llama-server"
            if metrics.tokens_per_second_source == "server"
            else "calculados con latencia HTTP, incluyen procesamiento del prompt"
        )
        print(f"tokens/s       : {metrics.tokens_per_second:.1f} ({source})")


# ---------------------------------------------------------------------
# demo: el camino RAG con evidencia sintética
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _SyntheticPassage:
    """Un pasaje inventado, con la procedencia que exige una cita."""

    code: str
    title: str
    section_number: str
    section_title: str
    page: int
    content: str


_DEMO_DOMAIN = "mantenimiento"
_DEMO_ASSET = "demo-prensa"
_DEMO_SCOPE = Scope(_DEMO_DOMAIN, _DEMO_ASSET)

# Equipo, códigos y cifras **inventados**. No proceden de la planta y no
# pretenden parecerse a nada real: el objetivo es comprobar que el runtime
# cita lo que se le da, no enseñarle nada a nadie.
_SYNTHETIC: tuple[_SyntheticPassage, ...] = (
    _SyntheticPassage(
        code="MAN-DEMO-01",
        title="Manual de la prensa de demostración",
        section_number="3",
        section_title="Lubricación",
        page=12,
        content=(
            "El rodamiento principal SAP-DEMO-4471 se lubrica cada 500 horas de "
            "operación con grasa de litio NLGI 2."
        ),
    ),
    _SyntheticPassage(
        code="MAN-DEMO-01",
        title="Manual de la prensa de demostración",
        section_number="4",
        section_title="Aprietes",
        page=18,
        content=(
            "El par de apriete de los tornillos de la tapa del rodamiento "
            "SAP-DEMO-4471 es de 45 N·m."
        ),
    ),
    _SyntheticPassage(
        code="AMEF-DEMO-02",
        title="AMEF de la prensa de demostración",
        section_number="2",
        section_title="Modos de falla",
        page=4,
        content=(
            "La falta de lubricación del rodamiento SAP-DEMO-4471 produce "
            "sobrecalentamiento y desgaste prematuro de la pista interior."
        ),
    ),
)


def synthetic_evidence_set() -> EvidenceSet:
    """Evidencia sintética con procedencia completa.

    Se construyen registros de verdad —documento, versión publicada, sección
    y chunk— en vez de un bloque de texto ya formateado. Cuesta unas líneas
    más y compra lo que hace útil este comando: el contexto lo compone el
    Context Builder real y las citas las resuelve el verificador real, así
    que lo que se ejercita es el camino del bloque y no una imitación suya.
    """
    created = datetime(2026, 1, 1, tzinfo=UTC)
    evidence: list[Evidence] = []
    for position, passage in enumerate(_SYNTHETIC, start=1):
        document = DocumentRecord(
            id=f"demo-doc-{passage.code}",
            domain=_DEMO_DOMAIN,
            code=passage.code,
            title=passage.title,
            source_kind=DocumentSourceKind.MANUAL,
            asset_code=_DEMO_ASSET,
            language="es",
        )
        version = DocumentVersionRecord(
            id=f"demo-ver-{passage.code}",
            document_id=document.id,
            run_id="demo-run",
            source_artifact_id="demo-artifact",
            version_number=1,
            state=DocumentVersionState.PUBLISHED,
            content_sha256="0" * 64,
            structure_sha256="1" * 64,
            chunking_profile="structural-v1",
            chunking_parameters={},
            extractor="structured-text",
            extractor_version="1",
            created_at=created,
        )
        section = DocumentSectionRecord(
            id=f"demo-sec-{position}",
            version_id=version.id,
            ordinal=position,
            path=str(position),
            depth=1,
            title=passage.section_title,
            number_label=passage.section_number,
        )
        chunk = DocumentChunkRecord(
            id=f"demo-chunk-{position}",
            version_id=version.id,
            ordinal=position,
            structural_key=f"{position}#0001",
            content=passage.content,
            content_sha256=hashlib.sha256(passage.content.encode("utf-8")).hexdigest(),
            kind=ChunkKind.PROSE,
            section_id=section.id,
            section_title=passage.section_title,
            page_start=passage.page,
            page_end=passage.page,
            char_length=len(passage.content),
        )
        evidence.append(
            Evidence(
                provenance=ChunkProvenance(
                    chunk=chunk,
                    document=document,
                    version=version,
                    section=section,
                    source_sha256="2" * 64,
                    source_storage_key=f"private/demo/{passage.code}",
                ),
                hits=(ChannelHit(channel=Channel.LEXICAL, rank=position, score=1.0),),
                fused_score=1.0 / (60 + position),
                rank=position,
            )
        )
    return EvidenceSet(
        evidence=tuple(evidence),
        strength=EvidenceStrength.WEAK,
        channels_queried=(Channel.LEXICAL,),
        identifiers_detected=(),
    )


class _FixedEvidence:
    """Devuelve siempre la misma evidencia sintética. No autoriza nada.

    Implementa `EvidenceRetrievalPort` para poder enchufarlo al servicio real
    del Bloque 4.4 en vez de rehacer el camino a mano. Y **no comprueba los
    alcances**, a propósito: aquí no hay corpus, ni permisos, ni base de
    datos. Comprobar el aislamiento es de `ask`, que recupera de verdad, y de
    `tests/test_rag_llama_cpp_end_to_end.py`. Fingir autorización en un
    comando de demostración sería peor que no tenerla, porque saldría bien.
    """

    def __init__(self, evidence: EvidenceSet) -> None:
        self._evidence = evidence

    async def search(self, *, query: str, scopes: Sequence[Scope], limit: int = 10) -> EvidenceSet:
        return self._evidence


async def _demo(settings: Settings, args: argparse.Namespace) -> int:
    """Evidencia sintética → el servicio real del 4.4 → runtime real.

    Pasa por `GroundedGenerationService`, no por una copia suya. Eso importa:
    lo que se quiere comprobar en PC1 no es que el modelo responda, sino que
    **el sistema completo hace con esa respuesta lo que promete** —descartar
    los marcadores inventados, decidir el estado, tratar una salida vacía
    como fallo técnico y no como ausencia de información—. Una segunda
    implementación de esa política aquí acabaría divergiendo de la de
    producción, y esta herramienta diría que todo está bien mientras el
    sistema real hace otra cosa.

    Lo único que se sustituye es la recuperación. Sin base de datos y sin
    embeddings: es el comando del primer día.
    """
    llm = build_llm(settings)
    retrieval: EvidenceRetrievalPort = _FixedEvidence(synthetic_evidence_set())
    assistant = GroundedGenerationService(
        retrieval=retrieval,
        llm=llm,
        timeout_seconds=settings.llm_timeout_seconds + 5.0,
        max_tokens=settings.llm_max_output_tokens,
    )

    started = time.monotonic()
    try:
        answer = await assistant.answer(
            question=args.question,
            scopes=[_DEMO_SCOPE],
            request_id=args.request_id,
        )
    finally:
        await llm.aclose()
    elapsed = time.monotonic() - started

    print("evidencia      : SINTÉTICA, no procede de la planta")
    print("recuperación   : omitida (este comando no autoriza nada; para eso está `ask`)")
    print()
    _print_answer(answer, elapsed)
    return 0 if answer.status is not AnswerStatus.ERROR else 1


# ---------------------------------------------------------------------
# ask: el camino completo del bloque
# ---------------------------------------------------------------------


async def _ask(settings: Settings, args: argparse.Namespace) -> int:
    """pregunta → alcances → híbrido → contexto → runtime → verificación.

    Es el criterio de cierre del bloque ejecutándose de verdad. Los alcances
    se pasan explícitamente y no tienen valor por defecto: sin alcances no se
    abre nada, igual que en la recuperación.
    """
    embeddings = build_embeddings(settings)
    url = _database_url(settings)
    llm = build_llm(settings)
    store = await PostgresVectorStore.connect(url)
    lexical = await PostgresLexicalSearch.connect(url)
    started = time.monotonic()
    try:
        hybrid = HybridRetrievalService(lexical=lexical, vectors=store, embeddings=embeddings)
        retrieval: EvidenceRetrievalPort = hybrid
        assistant = GroundedGenerationService(
            retrieval=retrieval,
            llm=llm,
            timeout_seconds=settings.llm_timeout_seconds + 5.0,
            max_tokens=settings.llm_max_output_tokens,
        )
        answer = await assistant.answer(
            question=args.question,
            scopes=_scopes(args.scope),
            request_id=args.request_id,
        )
    finally:
        await lexical.close()
        await store.close()
        await llm.aclose()
    elapsed = time.monotonic() - started

    if args.json:
        print(json.dumps(_as_dict(answer, elapsed), ensure_ascii=False, indent=2))
        return 0 if answer.status is not AnswerStatus.ERROR else 1

    _print_answer(answer, elapsed)
    return 0 if answer.status is not AnswerStatus.ERROR else 1


def _print_answer(answer: GroundedAnswer, elapsed: float) -> None:
    print(f"estado         : {answer.status.value}")
    print(f"suficiencia    : {answer.sufficiency.value}")
    print()
    print(answer.answer)
    print()
    if answer.citations:
        print("citas:")
        for citation in answer.citations:
            print(f"  [{citation.marker}] {citation.reference}")
    if answer.warnings:
        print(f"avisos: {', '.join(w.value for w in answer.warnings)}")
    print()
    audit = answer.audit
    print(f"request_id     : {audit.request_id or '(sin identificador)'}")
    # `audit.model` solo se rellena cuando el modelo llegó a responder, así
    # que por sí solo no distingue «no se le llamó» de «se le llamó y falló».
    # Quien lo distingue es `llm_called`, y confundirlos aquí haría creer que
    # un runtime caído es una abstención.
    if not audit.llm_called:
        print("modelo         : no se llamó (no había evidencia autorizada)")
    else:
        print(f"modelo         : {audit.model or 'sin respuesta del runtime'}")
    print(
        f"evidencia      : {audit.evidence_retrieved} recuperadas, "
        f"{audit.evidence_in_context} en contexto"
    )
    print(f"contexto       : {audit.context_characters} caracteres")
    if audit.error_code:
        print(f"error          : {audit.error_code}")
    if audit.invalid_markers:
        # Lo que el modelo se inventó y el backend descartó. Es el número que
        # hay que mirar en PC1 para saber si Phi está citando de más.
        print(f"citas inventadas y descartadas: {', '.join(audit.invalid_markers)}")
    print(f"latencia RAG   : {elapsed:.2f} s (recuperación + generación + verificación)")


def _as_dict(answer: GroundedAnswer, elapsed: float) -> dict[str, object]:
    return {
        "status": answer.status.value,
        "sufficiency": answer.sufficiency.value,
        "answer": answer.answer,
        "citations": [{"marker": c.marker, "reference": c.reference} for c in answer.citations],
        "warnings": [w.value for w in answer.warnings],
        "audit": {
            "request_id": answer.audit.request_id,
            "model": answer.audit.model,
            "llm_called": answer.audit.llm_called,
            "evidence_retrieved": answer.audit.evidence_retrieved,
            "evidence_in_context": answer.audit.evidence_in_context,
            "context_characters": answer.audit.context_characters,
            "invalid_markers": list(answer.audit.invalid_markers),
            "error_code": answer.audit.error_code,
        },
        "elapsed_seconds": round(elapsed, 3),
    }


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m elsa.tools.llm_runtime",
        description=(
            "Operación del runtime de generación local (llama-server). "
            "El modelo NO se carga en este proceso."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="Configuración del runtime, sin hablar con nadie")
    check.set_defaults(run=_check)

    health = sub.add_parser("health", help="¿Está llama-server listo con el modelo cargado?")
    health.set_defaults(run=_health)

    generate = sub.add_parser("generate", help="Generación mínima, con latencia y tokens/s")
    generate.add_argument("prompt")
    generate.set_defaults(run=_generate)

    demo = sub.add_parser(
        "demo",
        help="Camino RAG sobre evidencia SINTÉTICA: no necesita base ni embeddings",
    )
    demo.add_argument("question")
    demo.add_argument("--request-id", default=None, help="Identificador para cruzar con los logs")
    demo.set_defaults(run=_demo)

    ask = sub.add_parser(
        "ask",
        help="Camino completo: alcances → recuperación híbrida → runtime → citas",
    )
    ask.add_argument("question")
    ask.add_argument(
        "--scope",
        action="append",
        required=True,
        metavar="DOMINIO[:EQUIPO]",
        help="Alcance autorizado. Repetible. Sin alcances no se recupera nada",
    )
    ask.add_argument("--request-id", default=None, help="Identificador para cruzar con los logs")
    ask.add_argument("--json", action="store_true", help="Salida estructurada")
    ask.set_defaults(run=_ask)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    try:
        return int(asyncio.run(args.run(settings, args)))
    except LLMConfigurationError as error:
        print(f"configuración inválida: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # noqa: BLE001 - la CLI reporta, no propaga trazas
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
