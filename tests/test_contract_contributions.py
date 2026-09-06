"""El adaptador en memoria cumple el contrato del puerto de aportes."""

import pytest

from elsa.adapters.memory_contributions import InMemoryContributionsRepository
from elsa.core.contributions import (
    ALLOWED_TRANSITIONS,
    ContributionRuleError,
    InvalidTransitionError,
    check_submittable,
    validate_transition,
)
from elsa.ports.contributions import (
    ChecklistAnswer,
    ContributionAudio,
    ContributionNotFoundError,
    ContributionRecord,
    ContributionsRepositoryPort,
    ContributionState,
)

pytestmark = pytest.mark.anyio

AUTHOR = "00000000-0000-4000-8000-00000000aaaa"
OTHER = "00000000-0000-4000-8000-00000000bbbb"


@pytest.fixture
def repo() -> InMemoryContributionsRepository:
    return InMemoryContributionsRepository()


async def _draft(repo: InMemoryContributionsRepository, **overrides: object) -> ContributionRecord:
    defaults: dict[str, object] = {
        "domain": "mantenimiento",
        "asset_code": "tampella",
        "author_id": AUTHOR,
        "author_name": "Autor",
        "title": "Ruido en la prensa",
        "transcript_text": "hay un ruido",
        "transcript_is_simulated": True,
        "transcript_engine": "simulated",
        "audio": None,
    }
    defaults.update(overrides)
    return await repo.create(**defaults)  # type: ignore[arg-type]


async def test_the_adapter_satisfies_the_port(repo: InMemoryContributionsRepository) -> None:
    assert isinstance(repo, ContributionsRepositoryPort)


async def test_a_new_contribution_is_a_draft(repo: InMemoryContributionsRepository) -> None:
    record = await _draft(repo)
    assert record.state is ContributionState.DRAFT
    assert record.submitted_at is None


async def test_an_approved_contribution_is_never_published_knowledge(
    repo: InMemoryContributionsRepository,
) -> None:
    """Aprobar marca el aporte como válido; publicar es otra puerta."""
    record = await _draft(repo)
    await repo.submit(record.id)
    decided = await repo.decide(
        record.id, state=ContributionState.APPROVED, actor=OTHER, reason=None
    )
    assert decided.state is ContributionState.APPROVED
    assert decided.is_published_knowledge is False


async def test_scope_is_normalised(repo: InMemoryContributionsRepository) -> None:
    record = await _draft(repo, domain="Mantenimiento", asset_code="TAMPELLA")
    assert (record.domain, record.asset_code) == ("mantenimiento", "tampella")
    listed = await repo.list_by_author(AUTHOR, domain="mantenimiento", asset_code="tampella")
    assert [item.id for item in listed] == [record.id]


async def test_listing_is_scoped(repo: InMemoryContributionsRepository) -> None:
    await _draft(repo)
    other_scope = await repo.list_by_author(
        AUTHOR, domain="mantenimiento", asset_code="otro-equipo"
    )
    assert other_scope == ()


async def test_a_submitted_contribution_cannot_be_edited(
    repo: InMemoryContributionsRepository,
) -> None:
    """Reescribir lo enviado dejaría al revisor sin saber qué aprueba."""
    record = await _draft(repo)
    await repo.submit(record.id)
    with pytest.raises(ContributionRuleError):
        await repo.update_draft(record.id, title="otro título")


async def test_submitting_twice_is_refused(repo: InMemoryContributionsRepository) -> None:
    record = await _draft(repo)
    await repo.submit(record.id)
    with pytest.raises(InvalidTransitionError):
        await repo.submit(record.id)


async def test_a_rejection_can_be_reconsidered(repo: InMemoryContributionsRepository) -> None:
    record = await _draft(repo)
    await repo.submit(record.id)
    await repo.decide(
        record.id, state=ContributionState.REJECTED, actor=OTHER, reason="falta contexto"
    )
    reconsidered = await repo.decide(
        record.id, state=ContributionState.APPROVED, actor=OTHER, reason=None
    )
    assert reconsidered.state is ContributionState.APPROVED


async def test_a_draft_cannot_be_approved_directly(
    repo: InMemoryContributionsRepository,
) -> None:
    """Sin pasar por revisión no hay aprobación posible."""
    record = await _draft(repo)
    with pytest.raises(InvalidTransitionError):
        await repo.decide(record.id, state=ContributionState.APPROVED, actor=OTHER)


async def test_an_unknown_contribution_is_reported(
    repo: InMemoryContributionsRepository,
) -> None:
    with pytest.raises(ContributionNotFoundError):
        await repo.submit("00000000-0000-4000-8000-00000000cccc")


async def test_the_contributor_capability_is_per_scope(
    repo: InMemoryContributionsRepository,
) -> None:
    await repo.set_contributor(AUTHOR, domain="mantenimiento", asset_code="tampella", enabled=True)
    assert await repo.is_contributor(AUTHOR, domain="mantenimiento", asset_code="tampella")
    assert not await repo.is_contributor(AUTHOR, domain="mantenimiento", asset_code="otro")
    assert not await repo.is_contributor(OTHER, domain="mantenimiento", asset_code="tampella")


async def test_the_contributor_capability_can_be_withdrawn(
    repo: InMemoryContributionsRepository,
) -> None:
    await repo.set_contributor(AUTHOR, domain="mantenimiento", asset_code="tampella", enabled=True)
    await repo.set_contributor(AUTHOR, domain="mantenimiento", asset_code="tampella", enabled=False)
    assert not await repo.is_contributor(AUTHOR, domain="mantenimiento", asset_code="tampella")


def test_no_state_means_published() -> None:
    """El ciclo de vida de un aporte no contempla publicar.

    Publicar es una operación del BOM versionado, con su propia autoridad.
    Que aquí no exista el estado es lo que impide que un aporte aprobado se
    confunda con conocimiento vigente.
    """
    assert "published" not in {state.value for state in ContributionState}
    assert set(ALLOWED_TRANSITIONS) <= set(ContributionState)
    for targets in ALLOWED_TRANSITIONS.values():
        assert targets <= set(ContributionState)


def test_a_decision_cannot_be_sent_back_to_pending() -> None:
    """Un aporte decidido no vuelve a la cola por sí solo."""
    with pytest.raises(InvalidTransitionError):
        validate_transition(ContributionState.APPROVED, ContributionState.PENDING)
    with pytest.raises(InvalidTransitionError):
        validate_transition(ContributionState.REJECTED, ContributionState.PENDING)


def test_a_draft_cannot_jump_to_a_decision() -> None:
    with pytest.raises(InvalidTransitionError):
        validate_transition(ContributionState.DRAFT, ContributionState.APPROVED)


async def test_content_is_required_to_submit(repo: InMemoryContributionsRepository) -> None:
    record = await _draft(repo, transcript_text="", audio=None)
    check = check_submittable(record)
    assert "content" in check.missing


async def test_audio_alone_counts_as_content(repo: InMemoryContributionsRepository) -> None:
    record = await _draft(
        repo,
        transcript_text="",
        audio=ContributionAudio(storage_key="k", byte_size=10, duration_seconds=5.0),
    )
    assert "content" not in check_submittable(record).missing


async def test_the_required_checklist_questions_block_submission(
    repo: InMemoryContributionsRepository,
) -> None:
    record = await _draft(repo)
    check = check_submittable(record, checklist=[])
    assert "que_paso" in check.missing
    assert "donde" in check.missing
    assert check.ok is False


async def test_answering_the_required_questions_unblocks_submission(
    repo: InMemoryContributionsRepository,
) -> None:
    record = await _draft(repo)
    check = check_submittable(
        record,
        checklist=[
            ChecklistAnswer(key="que_paso", question="?", answer="Ruido metálico"),
            ChecklistAnswer(key="donde", question="?", answer="Prensa inferior"),
        ],
    )
    assert check.ok is True
    assert check.missing == ()


async def test_a_blank_answer_does_not_count(repo: InMemoryContributionsRepository) -> None:
    record = await _draft(repo)
    check = check_submittable(
        record,
        checklist=[
            ChecklistAnswer(key="que_paso", question="?", answer="   "),
            ChecklistAnswer(key="donde", question="?", answer="Prensa"),
        ],
    )
    assert "que_paso" in check.missing
