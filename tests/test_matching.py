"""Emparejamiento conservador de renglones con componentes existentes."""

from elsa.core.matching import ComponentIndex, MatchCandidate, MatchConfidence, match_component


def _index() -> ComponentIndex:
    return ComponentIndex.build(
        [
            (
                "c1",
                MatchCandidate(
                    subsystem_name="Accionamiento",
                    component_name="Rodamiento",
                    sap_code="10000001",
                    assembly_drawing="PL-001",
                    drawing_reference="R-01",
                    model_reference="MOD-A",
                ),
            ),
            (
                "c2",
                MatchCandidate(
                    subsystem_name="Bastidor",
                    component_name="Rodamiento",
                    sap_code="10000001",
                    assembly_drawing="PL-002",
                    drawing_reference="R-09",
                    model_reference="MOD-B",
                ),
            ),
            (
                "c3",
                MatchCandidate(
                    subsystem_name="Bastidor",
                    component_name="Tornillo",
                    sap_code="10000002",
                    assembly_drawing="PL-002",
                    drawing_reference="R-03",
                    model_reference="MOD-C",
                ),
            ),
        ]
    )


def test_drawing_and_reference_identify_exactly() -> None:
    result = match_component(
        MatchCandidate(assembly_drawing="PL-001", drawing_reference="R-01"), _index()
    )

    assert result.component_id == "c1"
    assert result.rule == "drawing_reference"
    assert result.confidence is MatchConfidence.EXACT


def test_an_unambiguous_sap_code_identifies() -> None:
    result = match_component(MatchCandidate(sap_code="10000002"), _index())

    assert result.component_id == "c3"
    assert result.confidence is MatchConfidence.STRONG


def test_sap_display_padding_does_not_prevent_a_match() -> None:
    result = match_component(MatchCandidate(sap_code="000000000010000002"), _index())

    assert result.component_id == "c3"


def test_a_repeated_sap_code_is_never_resolved_automatically() -> None:
    """El mismo material en dos sitios: decide una persona."""
    result = match_component(MatchCandidate(sap_code="10000001"), _index())

    assert result.component_id is None
    assert result.ambiguous is True
    assert result.rule == "sap_code_ambiguous"
    assert set(result.candidate_ids) == {"c1", "c2"}


def test_a_name_alone_never_merges() -> None:
    """Dos componentes distintos pueden llamarse igual."""
    result = match_component(MatchCandidate(component_name="Rodamiento"), _index())

    assert result.component_id is None
    assert result.ambiguous is False
    assert result.is_new is True


def test_subsystem_plus_technical_reference_is_weak_evidence() -> None:
    result = match_component(
        MatchCandidate(subsystem_name="Bastidor", model_reference="MOD-C"), _index()
    )

    assert result.component_id == "c3"
    assert result.confidence is MatchConfidence.WEAK


def test_unknown_evidence_means_a_new_component() -> None:
    result = match_component(
        MatchCandidate(component_name="Pieza nueva", sap_code="99999999"), _index()
    )

    assert result.is_new is True
    assert result.rule is None


def test_a_drawing_without_a_reference_is_not_enough() -> None:
    """El plano solo designa el conjunto, no una pieza."""
    result = match_component(MatchCandidate(assembly_drawing="PL-001"), _index())

    assert result.is_new is True


def test_a_component_without_a_sap_code_can_still_match_by_drawing() -> None:
    result = match_component(
        MatchCandidate(sap_code=None, assembly_drawing="PL-002", drawing_reference="R-03"),
        _index(),
    )

    assert result.component_id == "c3"


def test_stronger_evidence_wins_over_weaker() -> None:
    """El plano manda aunque el código SAP apunte a otro componente."""
    result = match_component(
        MatchCandidate(assembly_drawing="PL-002", drawing_reference="R-03", sap_code="10000001"),
        _index(),
    )

    assert result.component_id == "c3"
    assert result.rule == "drawing_reference"
