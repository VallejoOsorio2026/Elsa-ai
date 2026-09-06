"""Reglas de la revisión técnica, sin HTTP ni base de datos."""

import pytest

from elsa.core.authorization import Principal, Scope
from elsa.core.review import (
    MissingReasonError,
    ReviewDecision,
    ReviewerCapability,
    build_capability,
    can_review,
    validate_decision,
)

DOMAIN = Scope(domain="mantenimiento")
TAMPELLA = Scope(domain="mantenimiento", equipment="tampella")
OTHER_ASSET = Scope(domain="mantenimiento", equipment="otro-equipo")


def _capability(*scopes: Scope, is_admin: bool = False) -> ReviewerCapability:
    return ReviewerCapability(external_user_id="u1", is_admin=is_admin, scopes=scopes)


def test_a_user_without_any_reviewer_grant_cannot_review() -> None:
    assert can_review(_capability(), TAMPELLA) is False


def test_a_reviewer_of_the_asset_can_review_it() -> None:
    assert can_review(_capability(TAMPELLA), TAMPELLA) is True


def test_a_reviewer_of_one_asset_cannot_review_another() -> None:
    assert can_review(_capability(TAMPELLA), OTHER_ASSET) is False


def test_a_domain_wide_reviewer_covers_every_asset_of_that_domain() -> None:
    assert can_review(_capability(DOMAIN), TAMPELLA) is True
    assert can_review(_capability(DOMAIN), OTHER_ASSET) is True


def test_an_asset_reviewer_does_not_cover_the_whole_domain() -> None:
    assert can_review(_capability(TAMPELLA), DOMAIN) is False


def test_an_administrator_keeps_global_intervention() -> None:
    assert can_review(_capability(is_admin=True), TAMPELLA) is True


def test_read_permission_alone_does_not_grant_review() -> None:
    """Leer y validar son capacidades distintas."""
    principal = Principal(
        external_user_id="u1",
        display_name=None,
        is_active=True,
        is_admin=False,
        scopes=(TAMPELLA,),
    )

    capability = build_capability(principal, [])

    assert can_review(capability, TAMPELLA) is False


def test_approving_may_carry_no_comment() -> None:
    assert validate_decision(ReviewDecision.APPROVED, None) is None


def test_approving_keeps_the_comment_when_given() -> None:
    assert validate_decision(ReviewDecision.APPROVED, "  se verificó en campo ") == (
        "se verificó en campo"
    )


@pytest.mark.parametrize("decision", [ReviewDecision.REJECTED, ReviewDecision.REVERTED])
@pytest.mark.parametrize("comment", [None, "", "   "])
def test_rejecting_and_reverting_require_a_reason(
    decision: ReviewDecision, comment: str | None
) -> None:
    with pytest.raises(MissingReasonError):
        validate_decision(decision, comment)


@pytest.mark.parametrize("decision", [ReviewDecision.REJECTED, ReviewDecision.REVERTED])
def test_rejecting_and_reverting_work_with_a_reason(decision: ReviewDecision) -> None:
    assert validate_decision(decision, "el plano no corresponde") == "el plano no corresponde"
