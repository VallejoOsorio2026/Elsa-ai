"""La herramienta de operación documental, en memoria y con PostgreSQL real.

Lo que importa aquí es que **cada transición exige su comando**: ingerir deja
una versión pendiente, aprobar no publica, y publicar solo acepta una versión
aprobada. Y que las negativas —almacén en memoria, DEV contra una base
remota, archivo no admitido, actor que no es un UUID— ocurren antes de abrir
ninguna conexión, de modo que nada se escribe.

El último bloque carga el corpus de R1 con la propia CLI y comprueba que la
evaluación de ``bench/r1/evaluacion.json`` se sostiene sobre los chunks que
produce de verdad: cada cita esperada existe, está publicada y cae en el
alcance, y sus anclas de evidencia aparecen en el texto.
"""

import hashlib
import json
import unicodedata
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from elsa.adapters.local_artifact_storage import LocalArtifactStorage
from elsa.adapters.memory_documents import InMemoryDocumentRepository
from elsa.adapters.memory_knowledge import InMemoryKnowledgeRepository
from elsa.adapters.postgres_documents import PostgresDocumentRepository
from elsa.adapters.postgres_knowledge import PostgresKnowledgeRepository
from elsa.core.authorization import Scope
from elsa.documents.model import ChunkingPolicy
from elsa.ports.documents import DocumentRecord, DocumentVersionState
from elsa.tools.documents_admin import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, Stores, ToolConfig, run
from tests import db

pytestmark = pytest.mark.anyio

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "bench" / "corpus-sintetico"
EVALUATION = ROOT / "bench" / "r1" / "evaluacion.json"
GOLDEN = ROOT / "bench" / "golden" / "queries.json"

ACTOR = "aaaaaaaa-0000-4000-8000-000000000001"
DOMAIN = "mantenimiento"
PRESS = "prensa-ejemplo"
PUMP = "bomba-ejemplo"
REMOTE_URL = "postgresql://elsa@db.example.test:5432/elsa"
LOOPBACK_URL = "postgresql://elsa@127.0.0.1:5432/elsa"


@dataclass
class Harness:
    """Almacenes compartidos entre comandos y un contador de conexiones."""

    stores: Stores
    root: Path
    opened: int = 0
    calls: list[bool] = field(default_factory=list)

    async def open(self, config: ToolConfig, with_storage: bool) -> Stores:
        self.opened += 1
        self.calls.append(with_storage)
        return self.stores

    def config(
        self,
        *,
        is_dev: bool = False,
        database_url: str | None = REMOTE_URL,
        storage_local: bool = True,
    ) -> ToolConfig:
        return ToolConfig(
            is_dev=is_dev,
            database_url=database_url,
            artifact_storage_local=storage_local,
            artifact_storage_root=self.root if storage_local else None,
            policy=ChunkingPolicy(),
        )

    async def cli(self, argv: Sequence[str], config: ToolConfig | None = None) -> int:
        return await run(list(argv), config or self.config(), self.open)

    async def document(self, code: str) -> DocumentRecord:
        found = await self.stores.documents.get_document(domain=DOMAIN, code=code)
        assert found is not None
        return found


async def _no_close() -> None:
    return None


@pytest.fixture(params=["memory", "postgres"])
async def harness(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[Harness]:
    storage = LocalArtifactStorage(tmp_path / "artifacts")
    if request.param == "memory":
        stores = Stores(
            documents=InMemoryDocumentRepository(),
            assets=InMemoryKnowledgeRepository(),
            storage=storage,
        )
        yield Harness(stores=stores, root=tmp_path / "artifacts")
        return
    url = db.database_url()
    if url is None:
        pytest.skip(db.SKIP_REASON)
    await db.reset_database(url)
    documents = await PostgresDocumentRepository.connect(url, max_size=2)
    assets = await PostgresKnowledgeRepository.connect(url, max_size=2)
    try:
        yield Harness(
            stores=Stores(documents=documents, assets=assets, storage=storage),
            root=tmp_path / "artifacts",
        )
    finally:
        await assets.close()
        await documents.close()


async def _state(h: Harness, version_id: str) -> DocumentVersionState:
    version = await h.stores.documents.get_version(version_id)
    assert version is not None
    return version.state


async def _press_document(h: Harness) -> DocumentRecord:
    assert (
        await h.cli(
            ["create-asset", "--domain", DOMAIN, "--code", PRESS, "--name", "Prensa de ejemplo"]
        )
        == EXIT_OK
    )
    assert (
        await h.cli(
            [
                "create-document",
                "--domain",
                DOMAIN,
                "--code",
                "prensa-manual",
                "--title",
                "Manual de mantenimiento de la prensa de ejemplo PR-100",
                "--source-kind",
                "manual",
                "--asset",
                PRESS,
                "--language",
                "es",
            ]
        )
        == EXIT_OK
    )
    return await h.document("prensa-manual")


def _ingest(code: str, file: str) -> list[str]:
    return [
        "ingest",
        "--domain",
        DOMAIN,
        "--document",
        code,
        "--file",
        str(CORPUS / file),
        "--actor",
        ACTOR,
    ]


# ---------------------------------------------------------------------
# Cada transición, su comando
# ---------------------------------------------------------------------


async def test_each_transition_needs_its_own_command(harness: Harness) -> None:
    document = await _press_document(harness)
    repo = harness.stores.documents

    assert await harness.cli(_ingest("prensa-manual", "prensa-ejemplo-v1.md")) == EXIT_OK
    (version,) = await repo.list_versions(document.id)
    assert version.state is DocumentVersionState.PENDING_VALIDATION
    assert await repo.get_published_version(document.id) is None

    # Publicar sin aprobar no se acepta y no cambia nada.
    publish = ["publish", "--version", version.id, "--actor", ACTOR]
    assert await harness.cli(publish) == EXIT_FAILED
    assert await _state(harness, version.id) is DocumentVersionState.PENDING_VALIDATION

    # Aprobar no publica.
    assert await harness.cli(["approve", "--version", version.id, "--actor", ACTOR]) == EXIT_OK
    assert await _state(harness, version.id) is DocumentVersionState.APPROVED
    assert await repo.get_published_version(document.id) is None

    assert await harness.cli(publish) == EXIT_OK
    published = await repo.get_published_version(document.id)
    assert published is not None and published.id == version.id
    events = [e.event.value for e in await repo.list_version_events(version.id)]
    assert events == ["created", "approved", "published"]
    assert {e.actor for e in await repo.list_version_events(version.id)} == {ACTOR}


async def test_reingesting_the_same_file_creates_no_version(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    document = await _press_document(harness)
    assert await harness.cli(_ingest("prensa-manual", "prensa-ejemplo-v1.md")) == EXIT_OK
    capsys.readouterr()

    assert await harness.cli(_ingest("prensa-manual", "prensa-ejemplo-v1.md")) == EXIT_OK
    assert "no se creó ninguna versión" in capsys.readouterr().out
    assert len(await harness.stores.documents.list_versions(document.id)) == 1


@pytest.mark.parametrize("reason", [" ", "\t\n"])
async def test_reject_needs_a_reason_and_keeps_the_version(harness: Harness, reason: str) -> None:
    document = await _press_document(harness)
    assert await harness.cli(_ingest("prensa-manual", "prensa-ejemplo-v1.md")) == EXIT_OK
    (version,) = await harness.stores.documents.list_versions(document.id)

    reject = ["reject", "--version", version.id, "--actor", ACTOR, "--reason", reason]
    assert await harness.cli(reject) == EXIT_FAILED
    current = await harness.stores.documents.get_version(version.id)
    assert current is not None and current.state is DocumentVersionState.PENDING_VALIDATION

    with pytest.raises(SystemExit):
        await harness.cli(["reject", "--version", version.id, "--actor", ACTOR])


async def test_rejecting_a_new_version_does_not_withdraw_the_published_one(
    harness: Harness,
) -> None:
    document = await _press_document(harness)
    repo = harness.stores.documents
    assert await harness.cli(_ingest("prensa-manual", "prensa-ejemplo-v1.md")) == EXIT_OK
    (first,) = await repo.list_versions(document.id)
    await harness.cli(["approve", "--version", first.id, "--actor", ACTOR])
    await harness.cli(["publish", "--version", first.id, "--actor", ACTOR])

    assert await harness.cli(_ingest("prensa-manual", "prensa-ejemplo-v2.md")) == EXIT_OK
    second = next(v for v in await repo.list_versions(document.id) if v.id != first.id)
    reject = ["reject", "--version", second.id, "--actor", ACTOR, "--reason", "prueba"]
    assert await harness.cli(reject) == EXIT_OK

    published = await repo.get_published_version(document.id)
    assert published is not None and published.id == first.id


# ---------------------------------------------------------------------
# Negativas: nada se conecta, nada se escribe
# ---------------------------------------------------------------------


async def test_in_memory_artifact_storage_is_refused_before_connecting(harness: Harness) -> None:
    config = harness.config(storage_local=False)
    assert await harness.cli(_ingest("prensa-manual", "prensa-ejemplo-v1.md"), config) == (
        EXIT_REFUSED
    )
    assert harness.opened == 0


async def test_dev_never_writes_to_a_remote_database(harness: Harness) -> None:
    dev_remote = harness.config(is_dev=True, database_url=REMOTE_URL)
    create = ["create-asset", "--domain", DOMAIN, "--code", PRESS, "--name", "Prensa"]
    assert await harness.cli(create, dev_remote) == EXIT_REFUSED
    assert harness.opened == 0
    assert await harness.stores.assets.get_asset(PRESS) is None

    # Leer sí se permite, y DEV contra loopback sí escribe.
    assert await harness.cli(["status", "--domain", DOMAIN], dev_remote) == EXIT_OK
    dev_local = harness.config(is_dev=True, database_url=LOOPBACK_URL)
    assert await harness.cli(create, dev_local) == EXIT_OK


async def test_missing_database_url_is_refused(harness: Harness) -> None:
    config = harness.config(database_url=None)
    create = ["create-asset", "--domain", DOMAIN, "--code", PRESS, "--name", "Prensa"]
    assert await harness.cli(create, config) == EXIT_REFUSED
    assert harness.opened == 0


async def test_unsupported_or_missing_files_are_refused_before_connecting(
    harness: Harness, tmp_path: Path
) -> None:
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.7 synthetic")
    base = ["ingest", "--domain", DOMAIN, "--document", "prensa-manual", "--actor", ACTOR]
    assert await harness.cli([*base, "--file", str(pdf)]) == EXIT_REFUSED
    assert await harness.cli([*base, "--file", str(tmp_path / "nope.md")]) == EXIT_REFUSED
    assert harness.opened == 0


@pytest.mark.parametrize("actor", ["juan", "", "aaaaaaaa-0000"])
async def test_actor_must_be_a_uuid(harness: Harness, actor: str) -> None:
    with pytest.raises(SystemExit):
        await harness.cli(
            ["ingest", "--domain", DOMAIN, "--document", "x", "--file", "a.md", "--actor", actor]
        )
    assert harness.opened == 0


async def test_conflicts_stop_without_renaming(harness: Harness) -> None:
    await _press_document(harness)
    again = ["create-asset", "--domain", DOMAIN, "--code", PRESS, "--name", "Otra prensa"]
    assert await harness.cli(again) == EXIT_FAILED
    asset = await harness.stores.assets.get_asset(PRESS)
    assert asset is not None and asset.name == "Prensa de ejemplo"

    duplicate = [
        "create-document",
        "--domain",
        DOMAIN,
        "--code",
        "prensa-manual",
        "--title",
        "Otro título",
        "--source-kind",
        "manual",
    ]
    assert await harness.cli(duplicate) == EXIT_FAILED
    assert (await harness.document("prensa-manual")).title.startswith("Manual de mantenimiento")


async def test_a_document_needs_an_existing_asset_of_its_domain(harness: Harness) -> None:
    orphan = [
        "create-document",
        "--domain",
        DOMAIN,
        "--code",
        "huerfano",
        "--title",
        "Sin activo",
        "--source-kind",
        "manual",
        "--asset",
        "no-existe",
    ]
    assert await harness.cli(orphan) == EXIT_FAILED
    assert await harness.stores.documents.get_document(domain=DOMAIN, code="huerfano") is None


async def test_status_reports_absent_and_present_codes(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    status = ["status", "--domain", DOMAIN, "--asset", PRESS, "--document", "prensa-manual"]
    assert await harness.cli(status) == EXIT_OK
    out = capsys.readouterr().out
    assert f"activo {PRESS}: ausente" in out
    assert "documento mantenimiento/prensa-manual: ausente" in out
    assert harness.calls == [False]

    await _press_document(harness)
    await harness.cli(_ingest("prensa-manual", "prensa-ejemplo-v1.md"))
    capsys.readouterr()
    assert await harness.cli(status) == EXIT_OK
    out = capsys.readouterr().out
    assert f"activo {PRESS}: presente" in out
    assert "v1 pending_validation" in out
    assert "postgresql://" not in out


# ---------------------------------------------------------------------
# El corpus de R1 y su evaluación
# ---------------------------------------------------------------------


async def _load_r1_corpus(h: Harness) -> None:
    """La secuencia de `docs/r1-b-operacion-ingesta.md`, contra estos almacenes."""
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    for code, name in ((PRESS, "Prensa de ejemplo PR-100"), (PUMP, "Bomba de ejemplo BO-200")):
        create = ["create-asset", "--domain", DOMAIN, "--code", code, "--name", name]
        assert await h.cli(create) == EXIT_OK
    kinds = {"prensa-nota-en": "technical_note"}
    created: set[str] = set()
    for entry in manifest["documents"]:
        if entry["code"] in created:
            continue
        created.add(entry["code"])
        argv = [
            "create-document",
            "--domain",
            entry["domain"],
            "--code",
            entry["code"],
            "--title",
            entry["title"],
            "--source-kind",
            kinds.get(entry["code"], "manual"),
            "--asset",
            entry["asset"],
            "--language",
            entry["language"],
        ]
        assert await h.cli(argv) == EXIT_OK
    for entry in manifest["documents"]:
        if not entry["published"]:
            continue
        assert await h.cli(_ingest(entry["code"], entry["file"])) == EXIT_OK
        document = await h.document(entry["code"])
        (version,) = await h.stores.documents.list_versions(document.id)
        assert await h.cli(["approve", "--version", version.id, "--actor", ACTOR]) == EXIT_OK
        assert await h.cli(["publish", "--version", version.id, "--actor", ACTOR]) == EXIT_OK
    # La revisión 2 se ingiere y se deja pendiente: es la trampa de versión.
    assert await h.cli(_ingest("prensa-manual", "prensa-ejemplo-v2.md")) == EXIT_OK


@dataclass(frozen=True)
class _Chunk:
    content: str
    state: DocumentVersionState
    asset: str | None
    source_sha256: str


async def _all_chunks(h: Harness) -> dict[str, _Chunk]:
    repo = h.stores.documents
    chunks: dict[str, _Chunk] = {}
    for document in await repo.list_documents(domain=DOMAIN):
        for version in await repo.list_versions(document.id):
            for chunk in await repo.list_chunks(version.id):
                key = f"{document.code}@v{version.version_number}#{chunk.structural_key}"
                provenance = await repo.get_chunk_provenance(chunk.id)
                assert provenance is not None
                chunks[key] = _Chunk(
                    content=chunk.content,
                    state=version.state,
                    asset=document.asset_code,
                    source_sha256=provenance.source_sha256,
                )
    return chunks


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _evaluation() -> dict[str, object]:
    data: dict[str, object] = json.loads(EVALUATION.read_text(encoding="utf-8"))
    return data


async def test_r1_corpus_is_published_isolated_and_traceable(harness: Harness) -> None:
    await _load_r1_corpus(harness)
    chunks = await _all_chunks(harness)
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    hashes = {
        f"{e['code']}@v{e['version']}": hashlib.sha256(
            (CORPUS / e["file"]).read_bytes()
        ).hexdigest()
        for e in manifest["documents"]
    }
    for key, chunk in chunks.items():
        assert chunk.source_sha256 == hashes[key.split("#", 1)[0]], key

    visible = await harness.stores.documents.list_published_chunks(
        scopes=[Scope(DOMAIN, PRESS)], limit=1000
    )
    assert visible
    for provenance in visible:
        assert provenance.document.asset_code == PRESS
        assert provenance.version.state is DocumentVersionState.PUBLISHED
        assert provenance.version.version_number == 1
    seen = {p.document.code for p in visible}
    assert seen == {"prensa-manual", "prensa-nota-en"}


async def test_evaluation_holds_on_the_real_chunks(harness: Harness) -> None:
    await _load_r1_corpus(harness)
    chunks = await _all_chunks(harness)
    evaluation = _evaluation()
    questions = evaluation["questions"]
    assert isinstance(questions, list)
    for question in questions:
        for key in question["expected_citations"]:
            assert key in chunks, f"{question['id']}: {key} no existe"
            chunk = chunks[key]
            assert chunk.state is DocumentVersionState.PUBLISHED, key
            assert chunk.asset == PRESS, key
        for key in question["must_not_cite"]:
            assert key in chunks, f"{question['id']}: {key} no existe"
            chunk = chunks[key]
            assert chunk.state is not DocumentVersionState.PUBLISHED or chunk.asset != PRESS, key
        cited = _fold(" ".join(chunks[k].content for k in question["expected_citations"]))
        for anchor in question["evidence_anchors"]:
            assert _fold(anchor) in cited, f"{question['id']}: ancla {anchor!r} no está"


def test_evaluation_file_shape() -> None:
    evaluation = _evaluation()
    assert evaluation["scope"] == f"{DOMAIN}:{PRESS}"
    questions = evaluation["questions"]
    assert isinstance(questions, list)
    assert len(questions) == 15
    assert len({q["id"] for q in questions}) == 15
    counts: dict[str, int] = {}
    for question in questions:
        counts[question["category"]] = counts.get(question["category"], 0) + 1
        assert question["question"].strip() and question["reference_answer"].strip()
        if question["expected_status"] == "no_evidence":
            assert question["expected_citations"] == [] and question["evidence_anchors"] == []
        else:
            assert question["expected_status"] == "answered"
            assert question["expected_citations"] and question["evidence_anchors"]
        if question["category"] == "combination":
            assert len(question["expected_citations"]) >= 2
        if question["category"] == "ambiguity":
            assert question["known_limitation"].strip()
    assert counts == {
        "direct": 5,
        "combination": 3,
        "no_answer": 3,
        "ambiguity": 2,
        "isolation": 1,
        "version": 1,
    }
    golden = {q["id"] for q in json.loads(GOLDEN.read_text(encoding="utf-8"))["queries"]}
    for question in questions:
        assert question["origin"] is None or question["origin"] in golden
