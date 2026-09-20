"""Garantías automáticas de cobertura de inventario (A20, A20b, A21).

Son el control compensatorio del riesgo R4 del contrato funcional del
Piloto 0.1 —«cobertura incompleta del inventario»— y ejercen lo que
ADR 0023 §10 decidió sobre la base del mapeo de ADR 0021 §12 y §13.

Los identificadores A20, A20b y A21 se usan con la semántica **normativa**
del contrato funcional §12 y de ADR 0023 §14.1:

- **A20** — `requires_complete_inventory_coverage = true` con cobertura
  `UNKNOWN`: `PARTIAL` + `coverage_unknown`, nunca `coverage_incomplete`,
  nunca `ANSWERED`.
- **A20b** — `requires_complete_inventory_coverage = false` afirmando solo
  campos estables: **no** degrada por cobertura.
- **A21** — garantía negativa: ninguna cadena alcanzable afirma algo que
  solo sería cierto con cobertura completa. Estado y texto, por separado.

Nada aquí consulta a Materiales, ni implementa su fachada, ni conoce la
representación de un código SAP: se ejercita únicamente la política pura.
"""

import ast
import itertools
from pathlib import Path

import pytest

from elsa.core.answers import AnswerStatus, AnswerWarning
from elsa.core.capability_outcomes import (
    UNBOUNDED_CLAIM_REFUSAL_MESSAGE,
    CapabilityCallStatus,
    CapabilityOutcome,
    InventoryLookupResult,
    asserts_complete_coverage,
    asserts_nonexistence,
)
from elsa.core.coverage_policy import (
    AssertedInventoryField,
    ClaimScope,
    CoverageRequirement,
    IncoherentCoverageRequirementError,
    InventoryCoverageState,
    coverage_is_relevant,
    decide_under_coverage,
)

# ----------------------------------------------------------------------
# Constructores, para que cada prueba diga solo lo suyo
# ----------------------------------------------------------------------

_STABLE_FIELDS = (
    AssertedInventoryField.DESCRIPTION,
    AssertedInventoryField.UNIT_OF_MEASURE,
)
_QUANTITATIVE_FIELDS = (
    AssertedInventoryField.STOCK_QUANTITY,
    AssertedInventoryField.STOCK_LOCATIONS,
    AssertedInventoryField.AVAILABILITY,
)

_DEMANDING = CoverageRequirement(requires_complete_inventory_coverage=True)
_NOT_DEMANDING = CoverageRequirement(requires_complete_inventory_coverage=False)
_UNIVERSAL = CoverageRequirement(
    requires_complete_inventory_coverage=True, claim_scope=ClaimScope.UNIVERSAL
)

_NOT_COMPLETE = (InventoryCoverageState.UNKNOWN, InventoryCoverageState.KNOWN_INCOMPLETE)


def _matched() -> InventoryLookupResult:
    return InventoryLookupResult(
        call_status=CapabilityCallStatus.OK, outcome=CapabilityOutcome.MATCHED
    )


def _not_returned() -> InventoryLookupResult:
    return InventoryLookupResult(
        call_status=CapabilityCallStatus.OK,
        outcome=CapabilityOutcome.NOT_RETURNED,
        absence_is_authoritative=False,
    )


def _unavailable() -> InventoryLookupResult:
    return InventoryLookupResult(call_status=CapabilityCallStatus.UNAVAILABLE)


def _no_active_inventory() -> InventoryLookupResult:
    return InventoryLookupResult(call_status=CapabilityCallStatus.NO_ACTIVE_INVENTORY)


# ======================================================================
# B9a — `requires_complete_inventory_coverage` tipado y determinista
# ======================================================================


def test_b9a_the_flag_is_an_explicit_typed_property() -> None:
    """La decisión existe como dato, no como conjetura en tiempo de respuesta."""
    requirement = CoverageRequirement(requires_complete_inventory_coverage=True)

    assert requirement.requires_complete_inventory_coverage is True
    assert requirement.claim_scope is ClaimScope.ATTRIBUTED_TO_SOURCE


def test_b9a_stable_fields_alone_do_not_demand_complete_coverage() -> None:
    """ADR 0021 §12: «¿cuál es la descripción del material X?» → `false`."""
    requirement = CoverageRequirement.for_asserted_fields(_STABLE_FIELDS)

    assert requirement.requires_complete_inventory_coverage is False


@pytest.mark.parametrize("field", _QUANTITATIVE_FIELDS)
def test_b9a_any_quantitative_field_demands_complete_coverage(
    field: AssertedInventoryField,
) -> None:
    """ADR 0021 §12: «¿tenemos stock del material X?» → `true`."""
    requirement = CoverageRequirement.for_asserted_fields([*_STABLE_FIELDS, field])

    assert requirement.requires_complete_inventory_coverage is True


def test_b9a_derivation_is_deterministic_and_order_independent() -> None:
    fields = [*_STABLE_FIELDS, AssertedInventoryField.STOCK_QUANTITY]

    first = CoverageRequirement.for_asserted_fields(fields)
    reversed_order = CoverageRequirement.for_asserted_fields(reversed(fields))

    assert first == reversed_order
    assert first == CoverageRequirement.for_asserted_fields(fields)


def test_b9a_a_universal_claim_always_demands_complete_coverage() -> None:
    """Una afirmación de Clase 2 cuantifica sobre el universo entero.

    Ninguna combinación de campos la vuelve inocua: el universo **es** la
    afirmación (ADR 0023 §9).
    """
    requirement = CoverageRequirement.for_asserted_fields(
        _STABLE_FIELDS, claim_scope=ClaimScope.UNIVERSAL
    )

    assert requirement.requires_complete_inventory_coverage is True


def test_b9a_a_universal_claim_that_waives_the_requirement_is_refused() -> None:
    """No se puede construir la combinación incoherente: se rechaza al crearla."""
    with pytest.raises(IncoherentCoverageRequirementError):
        CoverageRequirement(
            requires_complete_inventory_coverage=False, claim_scope=ClaimScope.UNIVERSAL
        )


def test_b9a_the_policy_module_cannot_reach_a_model() -> None:
    """ADR 0023 §10.2.5: el LLM no participa y no puede levantar la restricción.

    Se comprueba estructuralmente —qué importa el módulo— y no por
    convención: un import de un puerto de generación o de un adaptador
    rompería esta prueba antes de llegar a producir una respuesta.
    """
    source = Path("src/elsa/core/coverage_policy.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert imported <= {
        "collections.abc",
        "dataclasses",
        "enum",
        "elsa.core.answers",
        "elsa.core.capability_outcomes",
    }


def test_b9a_the_decision_takes_the_requirement_as_an_input() -> None:
    """Dos requisitos distintos, mismo resultado de fuente: decisiones distintas.

    Es la prueba de que el flag manda sobre la política, y no al revés.
    """
    demanding = decide_under_coverage(
        _matched(),
        requirement=_DEMANDING,
        coverage=InventoryCoverageState.UNKNOWN,
        other_facts_available=False,
    )
    not_demanding = decide_under_coverage(
        _matched(),
        requirement=_NOT_DEMANDING,
        coverage=InventoryCoverageState.UNKNOWN,
        other_facts_available=False,
    )

    assert demanding.status is AnswerStatus.PARTIAL
    assert not_demanding.status is AnswerStatus.ANSWERED


# ======================================================================
# B9b — taxonomía de avisos, sin confundirse entre sí
# ======================================================================


def test_b9b_both_warnings_exist_in_the_shared_taxonomy() -> None:
    assert AnswerWarning.COVERAGE_UNKNOWN.value == "coverage_unknown"
    assert AnswerWarning.COVERAGE_INCOMPLETE.value == "coverage_incomplete"
    assert AnswerWarning.COVERAGE_UNKNOWN is not AnswerWarning.COVERAGE_INCOMPLETE


def test_b9b_the_pre_existing_taxonomy_is_intact() -> None:
    """Extender no puede romper lo que ya emitían A6, A6b y A19."""
    for name in (
        "NO_CITATIONS",
        "INVALID_CITATION",
        "WEAK_EVIDENCE",
        "MODEL_DECLARED_INSUFFICIENT",
        "CONTEXT_TRUNCATED",
        "EVIDENCE_DROPPED",
        "CAPABILITY_UNAVAILABLE",
        "INVENTORY_UNAVAILABLE",
        "CODE_NOT_FOUND_IN_SOURCE",
    ):
        assert hasattr(AnswerWarning, name)


def test_b9b_unknown_is_never_presented_as_incomplete() -> None:
    """ADR 0021 §13.2: afirmar incompletitud sin evidencia es el error en espejo."""
    decision = decide_under_coverage(
        _matched(),
        requirement=_DEMANDING,
        coverage=InventoryCoverageState.UNKNOWN,
        other_facts_available=False,
    )

    assert AnswerWarning.COVERAGE_UNKNOWN in decision.warnings
    assert AnswerWarning.COVERAGE_INCOMPLETE not in decision.warnings


def test_b9b_incomplete_is_never_presented_as_unknown() -> None:
    decision = decide_under_coverage(
        _matched(),
        requirement=_DEMANDING,
        coverage=InventoryCoverageState.KNOWN_INCOMPLETE,
        other_facts_available=False,
    )

    assert AnswerWarning.COVERAGE_INCOMPLETE in decision.warnings
    assert AnswerWarning.COVERAGE_UNKNOWN not in decision.warnings


def test_b9b_complete_coverage_raises_no_coverage_warning() -> None:
    decision = decide_under_coverage(
        _matched(),
        requirement=_DEMANDING,
        coverage=InventoryCoverageState.KNOWN_COMPLETE,
        other_facts_available=False,
    )

    assert AnswerWarning.COVERAGE_UNKNOWN not in decision.warnings
    assert AnswerWarning.COVERAGE_INCOMPLETE not in decision.warnings


def test_b9b_warnings_are_ordered_and_deduplicated() -> None:
    """Dos corridas idénticas producen la misma tupla (`order_warnings`)."""
    decision = decide_under_coverage(
        _not_returned(),
        requirement=_DEMANDING,
        coverage=InventoryCoverageState.UNKNOWN,
        other_facts_available=True,
    )

    assert decision.warnings == (
        AnswerWarning.CODE_NOT_FOUND_IN_SOURCE,
        AnswerWarning.COVERAGE_UNKNOWN,
    )
    assert len(set(decision.warnings)) == len(decision.warnings)


def test_b9b_relevance_follows_the_adr_0021_table() -> None:
    """§12.1: `NOT_RETURNED` es relevante de forma conservadora."""
    assert coverage_is_relevant(CapabilityOutcome.NOT_RETURNED, _NOT_DEMANDING) is True
    assert coverage_is_relevant(CapabilityOutcome.MATCHED, _NOT_DEMANDING) is False
    assert coverage_is_relevant(CapabilityOutcome.MATCHED, _DEMANDING) is True


# ======================================================================
# A20 — Clase 1, exige cobertura completa, cobertura no demostrada
# ======================================================================


def test_a20_bounded_claim_demanding_coverage_under_unknown_is_partial() -> None:
    """Contrato funcional §12, A20, literal."""
    decision = decide_under_coverage(
        _matched(),
        requirement=_DEMANDING,
        coverage=InventoryCoverageState.UNKNOWN,
        other_facts_available=False,
    )

    assert decision.status is AnswerStatus.PARTIAL
    assert decision.status is not AnswerStatus.ANSWERED
    assert AnswerWarning.COVERAGE_UNKNOWN in decision.warnings
    assert AnswerWarning.COVERAGE_INCOMPLETE not in decision.warnings
    # Clase 1: la afirmación se emite, acotada y degradada (ADR 0023 §10.2.2).
    assert decision.claim_emitted is True


def test_a20_bounded_claim_demanding_coverage_under_incomplete_is_partial() -> None:
    decision = decide_under_coverage(
        _matched(),
        requirement=_DEMANDING,
        coverage=InventoryCoverageState.KNOWN_INCOMPLETE,
        other_facts_available=False,
    )

    assert decision.status is AnswerStatus.PARTIAL
    assert AnswerWarning.COVERAGE_INCOMPLETE in decision.warnings
    assert decision.claim_emitted is True


@pytest.mark.parametrize("coverage", _NOT_COMPLETE)
@pytest.mark.parametrize("other_facts", [True, False])
def test_a20_no_complete_factual_answer_without_demonstrated_coverage(
    coverage: InventoryCoverageState, other_facts: bool
) -> None:
    """Regla B.1: nunca una respuesta factual completa. Nunca es nunca."""
    decision = decide_under_coverage(
        _matched(),
        requirement=_DEMANDING,
        coverage=coverage,
        other_facts_available=other_facts,
    )

    assert decision.status is not AnswerStatus.ANSWERED


def test_a20_complete_coverage_satisfies_the_requirement() -> None:
    """Regla 4: `COMPLETE` puede satisfacerlo, sin que ELSA demuestre cómo.

    Es la dirección que impide que A20 se vuelva vacua: si ningún estado
    de cobertura pudiera satisfacer el requisito, la prueba no distinguiría
    nada.
    """
    decision = decide_under_coverage(
        _matched(),
        requirement=_DEMANDING,
        coverage=InventoryCoverageState.KNOWN_COMPLETE,
        other_facts_available=False,
    )

    assert decision.status is AnswerStatus.ANSWERED
    assert decision.warnings == ()
    assert decision.claim_emitted is True


def test_a20_absence_under_unknown_stays_non_authoritative() -> None:
    """La cobertura marca la respuesta; no convierte la ausencia en hecho."""
    decision = decide_under_coverage(
        _not_returned(),
        requirement=_DEMANDING,
        coverage=InventoryCoverageState.UNKNOWN,
        other_facts_available=False,
    )

    assert decision.status is AnswerStatus.NO_EVIDENCE
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE in decision.warnings
    assert AnswerWarning.COVERAGE_UNKNOWN in decision.warnings
    assert not asserts_nonexistence(decision.message)
    assert decision.claim_emitted is False


# ======================================================================
# A20b — no exige cobertura completa: no degrada por cobertura
# ======================================================================


@pytest.mark.parametrize("coverage", _NOT_COMPLETE)
def test_a20b_stable_fields_do_not_degrade_by_coverage(
    coverage: InventoryCoverageState,
) -> None:
    """Contrato funcional §12, A20b, literal. ADR 0023 §10.1.6: degradar aquí
    sería ruido, y el ruido enseña a ignorar los avisos."""
    requirement = CoverageRequirement.for_asserted_fields(_STABLE_FIELDS)

    decision = decide_under_coverage(
        _matched(),
        requirement=requirement,
        coverage=coverage,
        other_facts_available=False,
    )

    assert decision.status is AnswerStatus.ANSWERED
    assert AnswerWarning.COVERAGE_UNKNOWN not in decision.warnings
    assert AnswerWarning.COVERAGE_INCOMPLETE not in decision.warnings


def test_a20b_usable_evidence_under_unknown_stays_attributed_to_the_source() -> None:
    """Regla A: `UNKNOWN` no impide responder, y la respuesta no es del mundo.

    El texto dice qué hizo la fuente consultada; nunca afirma cobertura
    (ADR 0021 §7.5).
    """
    decision = decide_under_coverage(
        _matched(),
        requirement=CoverageRequirement.for_asserted_fields(_STABLE_FIELDS),
        coverage=InventoryCoverageState.UNKNOWN,
        other_facts_available=True,
    )

    assert decision.status is AnswerStatus.ANSWERED
    assert "fuente consultada" in decision.message
    assert not asserts_complete_coverage(decision.message)
    assert not asserts_nonexistence(decision.message)


@pytest.mark.parametrize("coverage", _NOT_COMPLETE)
def test_a20b_absence_still_propagates_the_coverage_warning(
    coverage: InventoryCoverageState,
) -> None:
    """ADR 0023 §10.1.5 con §12.1: un código ausente es relevante en
    conservador, aunque la consulta no exigiera cobertura completa.

    El aviso se propaga; el estado **no** se degrada por cobertura.
    """
    decision = decide_under_coverage(
        _not_returned(),
        requirement=_NOT_DEMANDING,
        coverage=coverage,
        other_facts_available=False,
    )

    expected = (
        AnswerWarning.COVERAGE_UNKNOWN
        if coverage is InventoryCoverageState.UNKNOWN
        else AnswerWarning.COVERAGE_INCOMPLETE
    )
    assert decision.status is AnswerStatus.NO_EVIDENCE
    assert expected in decision.warnings
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE in decision.warnings


# ======================================================================
# A21 — garantía negativa: guarda de redacción, en las dos direcciones
# ======================================================================


# Redacciones que **solo** serían ciertas con cobertura completa demostrada.
_UNBOUNDED_CLAIMS = [
    "No hay en ningún almacén.",
    "No hay stock de ese material en ningún almacén.",
    "No tenemos stock en ninguna parte.",
    "El material no está en ninguna bodega.",
    "Estos son todos los materiales que tenemos.",
    "Son todos los repuestos de la empresa.",
    "No existe en el inventario de la empresa.",
    "Revisé el inventario completo de la planta.",
    "Ese código no está disponible en todos los almacenes consultados por SAP.",
    "La cobertura es completa.",
]

# Redacciones seguras con vocabulario parecido. Una guarda ingenua a base de
# palabras prohibidas rompería estas, y con ellas la única forma honesta de
# hablar de una cobertura que nadie demostró.
_BOUNDED_PHRASINGS = [
    "La fuente consultada no devolvió el material solicitado.",
    "Según el inventario cargado en Materiales, este código tiene existencias "
    "en las ubicaciones devueltas.",
    "No puedo afirmar que no haya en ningún almacén: se desconoce qué "
    "almacenes cubre este inventario.",
    "Encontré 7 elementos del BOM publicado con disponibilidad en la fuente consultada.",
    "Estos son todos los elementos del BOM publicado que devolvió la consulta.",
    "Se desconoce el alcance que cubre este inventario.",
    UNBOUNDED_CLAIM_REFUSAL_MESSAGE,
]


@pytest.mark.parametrize("text", _UNBOUNDED_CLAIMS)
def test_a21_guard_detects_unbounded_coverage_claims(text: str) -> None:
    """La guarda no es decorativa: estas frases deben dispararla."""
    assert asserts_complete_coverage(text)


@pytest.mark.parametrize("text", _BOUNDED_PHRASINGS)
def test_a21_guard_allows_bounded_phrasings(text: str) -> None:
    """Vocabulario aislado no es una afirmación universal."""
    assert not asserts_complete_coverage(text)


def test_a21_guard_reads_sentence_by_sentence() -> None:
    """Una salvedad al final no legitima una afirmación anterior."""
    mixed = "No hay en ningún almacén. Se desconoce el alcance del inventario."

    assert asserts_complete_coverage(mixed)


def test_a21_guard_is_independent_of_the_nonexistence_guard() -> None:
    """A21 no es A18 con otro nombre: cada una ve lo que la otra no ve."""
    assert asserts_complete_coverage("Estos son todos los materiales que tenemos.")
    assert not asserts_nonexistence("Estos son todos los materiales que tenemos.")
    assert asserts_nonexistence("El material no existe.")
    assert not asserts_complete_coverage("El material no existe.")


# --- Recorrido exhaustivo de la política -------------------------------

_ALL_RESULTS = [_matched(), _not_returned(), _unavailable(), _no_active_inventory()]
_ALL_REQUIREMENTS = [_NOT_DEMANDING, _DEMANDING, _UNIVERSAL]
_ALL_COVERAGES = list(InventoryCoverageState)
_ALL_COMBINATIONS = list(
    itertools.product(_ALL_RESULTS, _ALL_REQUIREMENTS, _ALL_COVERAGES, [True, False])
)


@pytest.mark.parametrize(("result", "requirement", "coverage", "other_facts"), _ALL_COMBINATIONS)
def test_a21_no_reachable_message_presupposes_complete_coverage(
    result: InventoryLookupResult,
    requirement: CoverageRequirement,
    coverage: InventoryCoverageState,
    other_facts: bool,
) -> None:
    """Texto: ninguna salida alcanzable afirma lo que nadie demostró."""
    decision = decide_under_coverage(
        result,
        requirement=requirement,
        coverage=coverage,
        other_facts_available=other_facts,
    )

    assert not asserts_complete_coverage(decision.message)
    # A18 sigue rigiendo sobre el texto compuesto, no solo sobre el de origen.
    assert not asserts_nonexistence(decision.message)


@pytest.mark.parametrize(("result", "requirement", "coverage", "other_facts"), _ALL_COMBINATIONS)
def test_a21_state_never_claims_an_undemonstrated_coverage(
    result: InventoryLookupResult,
    requirement: CoverageRequirement,
    coverage: InventoryCoverageState,
    other_facts: bool,
) -> None:
    """Estado: se verifica aparte del texto, como exige ADR 0022 §19."""
    decision = decide_under_coverage(
        result,
        requirement=requirement,
        coverage=coverage,
        other_facts_available=other_facts,
    )

    if coverage is InventoryCoverageState.KNOWN_COMPLETE:
        return

    if requirement.requires_complete_inventory_coverage:
        assert decision.status is not AnswerStatus.ANSWERED
    if requirement.claim_scope is ClaimScope.UNIVERSAL:
        assert decision.claim_emitted is False


@pytest.mark.parametrize("coverage", _NOT_COMPLETE)
@pytest.mark.parametrize("other_facts", [True, False])
def test_a21_an_unbounded_claim_is_refused_not_degraded(
    coverage: InventoryCoverageState, other_facts: bool
) -> None:
    """ADR 0023 §10.2.3: no se emite, ni degradada, ni acompañada de aviso.

    `PARTIAL` no basta para la Clase 2: un aviso junto a una afirmación sin
    respaldo la haría parecer una verdad matizada.
    """
    decision = decide_under_coverage(
        _matched(),
        requirement=_UNIVERSAL,
        coverage=coverage,
        other_facts_available=other_facts,
    )

    assert decision.claim_emitted is False
    assert decision.message == UNBOUNDED_CLAIM_REFUSAL_MESSAGE
    assert decision.status is (AnswerStatus.PARTIAL if other_facts else AnswerStatus.NO_EVIDENCE)


def test_a21_is_not_vacuous_complete_coverage_admits_the_universal_claim() -> None:
    """La guarda se comprueba en las dos direcciones, como A18.

    Si ninguna combinación pudiera emitir la afirmación, la garantía sería
    cierta por vacuidad y dejaría de proteger nada.
    """
    decision = decide_under_coverage(
        _matched(),
        requirement=_UNIVERSAL,
        coverage=InventoryCoverageState.KNOWN_COMPLETE,
        other_facts_available=False,
    )

    assert decision.claim_emitted is True
    assert decision.status is AnswerStatus.ANSWERED


# ======================================================================
# Las garantías existentes siguen en pie
# ======================================================================


@pytest.mark.parametrize("coverage", list(InventoryCoverageState))
@pytest.mark.parametrize("requirement", _ALL_REQUIREMENTS)
def test_a6_capability_unavailable_never_becomes_no_evidence_under_coverage(
    coverage: InventoryCoverageState, requirement: CoverageRequirement
) -> None:
    """A6 sobrevive al paso de cobertura: un fallo técnico no es una ausencia."""
    decision = decide_under_coverage(
        _unavailable(),
        requirement=requirement,
        coverage=coverage,
        other_facts_available=True,
    )

    assert decision.status is AnswerStatus.PARTIAL
    assert AnswerWarning.CAPABILITY_UNAVAILABLE in decision.warnings
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE not in decision.warnings


@pytest.mark.parametrize("coverage", list(InventoryCoverageState))
def test_a19_no_active_inventory_keeps_its_semantics_under_coverage(
    coverage: InventoryCoverageState,
) -> None:
    """A19: no hubo dónde mirar. La cobertura no cambia eso ni lo disfraza."""
    decision = decide_under_coverage(
        _no_active_inventory(),
        requirement=_DEMANDING,
        coverage=coverage,
        other_facts_available=False,
    )

    assert decision.status is AnswerStatus.ERROR
    assert AnswerWarning.INVENTORY_UNAVAILABLE in decision.warnings
    assert AnswerWarning.COVERAGE_UNKNOWN not in decision.warnings
    assert AnswerWarning.COVERAGE_INCOMPLETE not in decision.warnings


@pytest.mark.parametrize("coverage", list(InventoryCoverageState))
def test_rejected_is_still_never_composed_under_coverage(
    coverage: InventoryCoverageState,
) -> None:
    """`REJECTED` no se compone: la autorización se resolvió antes."""
    from elsa.core.capability_outcomes import UncomposableOutcomeError

    rejected = InventoryLookupResult(call_status=CapabilityCallStatus.REJECTED)

    with pytest.raises(UncomposableOutcomeError):
        decide_under_coverage(
            rejected,
            requirement=_DEMANDING,
            coverage=coverage,
            other_facts_available=False,
        )


@pytest.mark.parametrize("coverage", list(InventoryCoverageState))
def test_an_authoritative_absence_is_still_refused_while_m8_stays_open(
    coverage: InventoryCoverageState,
) -> None:
    """Invariante del que depende ADR 0023 entero (§13).

    Ningún estado de cobertura, `KNOWN_COMPLETE` incluido, habilita una
    ausencia autoritativa: M8 sigue abierto.
    """
    from elsa.core.capability_outcomes import UncomposableOutcomeError

    authoritative = InventoryLookupResult(
        call_status=CapabilityCallStatus.OK,
        outcome=CapabilityOutcome.NOT_RETURNED,
        absence_is_authoritative=True,
    )

    with pytest.raises(UncomposableOutcomeError):
        decide_under_coverage(
            authoritative,
            requirement=_NOT_DEMANDING,
            coverage=coverage,
            other_facts_available=False,
        )
