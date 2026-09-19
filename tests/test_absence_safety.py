"""Garantías automáticas de ausencia segura (A6, A6b, A18, A19).

Estas pruebas son el control compensatorio del riesgo R2 del contrato
funcional del Piloto 0.1 —«ausencia interpretada como inexistencia»— y
fijan lo que ADR 0020 §12 y §13 y ADR 0021 §6, §8 y §13 exigen del
consumidor.

Nada aquí consulta a Materiales, ni implementa su fachada, ni conoce la
representación de un código SAP: se ejercita únicamente la política pura
que traduce el resultado de una capacidad en un estado de respuesta.
"""

import pytest

from elsa.core.answers import AnswerStatus, AnswerWarning
from elsa.core.capability_outcomes import (
    CapabilityCallStatus,
    CapabilityOutcome,
    InventoryLookupResult,
    UncomposableOutcomeError,
    asserts_nonexistence,
    interpret_inventory_lookup,
)

# ----------------------------------------------------------------------
# Constructores de resultados, para que cada prueba diga solo lo suyo
# ----------------------------------------------------------------------


def _unavailable() -> InventoryLookupResult:
    return InventoryLookupResult(call_status=CapabilityCallStatus.UNAVAILABLE)


def _no_active_inventory() -> InventoryLookupResult:
    return InventoryLookupResult(call_status=CapabilityCallStatus.NO_ACTIVE_INVENTORY)


def _not_returned() -> InventoryLookupResult:
    return InventoryLookupResult(
        call_status=CapabilityCallStatus.OK,
        outcome=CapabilityOutcome.NOT_RETURNED,
        absence_is_authoritative=False,
    )


def _matched() -> InventoryLookupResult:
    return InventoryLookupResult(
        call_status=CapabilityCallStatus.OK,
        outcome=CapabilityOutcome.MATCHED,
    )


# ======================================================================
# A6 — capacidad externa indisponible
# ======================================================================


def test_a6_1_unavailable_in_a_composed_query_is_partial_not_no_evidence() -> None:
    """Otras capacidades aportaron algo útil: no se tira por una que falló."""
    result = interpret_inventory_lookup(_unavailable(), other_facts_available=True)

    assert result.status is AnswerStatus.PARTIAL
    assert AnswerWarning.CAPABILITY_UNAVAILABLE in result.warnings
    # La distinción que protege esta prueba: un fallo técnico jamás se
    # presenta como ausencia de información.
    assert result.status is not AnswerStatus.NO_EVIDENCE
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE not in result.warnings


def test_a6_2_unavailable_as_the_only_capability_is_an_error() -> None:
    result = interpret_inventory_lookup(_unavailable(), other_facts_available=False)

    assert result.status is AnswerStatus.ERROR
    assert AnswerWarning.CAPABILITY_UNAVAILABLE in result.warnings
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE not in result.warnings


# ======================================================================
# A6b — NOT_RETURNED no autoritativo
# ======================================================================


def test_a6b_non_authoritative_absence_alone_is_no_evidence() -> None:
    result = interpret_inventory_lookup(_not_returned(), other_facts_available=False)

    assert result.status is AnswerStatus.NO_EVIDENCE
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE in result.warnings


def test_a6b_non_authoritative_absence_beside_other_facts_is_partial() -> None:
    """ADR 0020 §13: con otros códigos resueltos, la respuesta es parcial."""
    result = interpret_inventory_lookup(_not_returned(), other_facts_available=True)

    assert result.status is AnswerStatus.PARTIAL
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE in result.warnings


def test_a6b_message_says_the_source_did_not_return_it() -> None:
    result = interpret_inventory_lookup(_not_returned(), other_facts_available=False)

    assert "no devolvió" in result.message
    assert not asserts_nonexistence(result.message)


def test_an_authoritative_absence_is_refused_while_m8_stays_open() -> None:
    """Nadie puede emitir hoy una inexistencia atribuida: M8 sigue abierto.

    Rechazarlo es más seguro que interpretarlo: si algún día una fuente
    garantiza su ausencia, esa decisión llegará con su propio ADR.
    """
    authoritative = InventoryLookupResult(
        call_status=CapabilityCallStatus.OK,
        outcome=CapabilityOutcome.NOT_RETURNED,
        absence_is_authoritative=True,
    )

    with pytest.raises(UncomposableOutcomeError):
        interpret_inventory_lookup(authoritative, other_facts_available=False)


# ======================================================================
# A18 — guarda transversal de redacción
# ======================================================================


# Redacciones que **sí** afirman inexistencia como hecho. Si el día de
# mañana alguien escribe una de estas en un mensaje de ausencia, la guarda
# tiene que verlo.
_AUTHORITATIVE_DENIALS = [
    "El material no existe.",
    "Ese material no existe en el catálogo.",
    "Este material no existe.",
    "No existe el material solicitado.",
    "El material no está creado.",
    "El material no está registrado en SAP.",
    "El material no figura en SAP.",
    "Ese código no existe en SAP.",
]

# Redacciones seguras que contienen el mismo vocabulario. Una prueba que
# prohibiera la palabra «existe» las rompería, y con ellas la única forma
# honesta de explicar una ausencia no autoritativa.
_SAFE_PHRASINGS = [
    "Este resultado no permite concluir si el material existe.",
    "La fuente consultada no devolvió el material solicitado.",
    "Que no lo devuelva no significa que el material no exista.",
    "No se puede concluir que el material no exista a partir de este resultado.",
]


@pytest.mark.parametrize("text", _AUTHORITATIVE_DENIALS)
def test_a18_guard_detects_authoritative_denials(text: str) -> None:
    """La guarda no es decorativa: estas frases deben dispararla."""
    assert asserts_nonexistence(text)


@pytest.mark.parametrize("text", _SAFE_PHRASINGS)
def test_a18_guard_allows_safe_explanations(text: str) -> None:
    """Vocabulario aislado no es una afirmación: estas no deben dispararla."""
    assert not asserts_nonexistence(text)


def test_a18_guard_reads_sentence_by_sentence() -> None:
    """Una salvedad al final no legitima una afirmación anterior."""
    mixed = "El material no existe. Este resultado no permite concluir nada más."

    assert asserts_nonexistence(mixed)


@pytest.mark.parametrize(
    ("result", "other_facts"),
    [
        (_unavailable(), True),
        (_unavailable(), False),
        (_no_active_inventory(), True),
        (_no_active_inventory(), False),
        (_not_returned(), True),
        (_not_returned(), False),
        (_matched(), True),
        (_matched(), False),
    ],
)
def test_a18_no_reachable_message_asserts_nonexistence(
    result: InventoryLookupResult, other_facts: bool
) -> None:
    """Ninguna salida alcanzable de la política afirma que algo no existe."""
    interpreted = interpret_inventory_lookup(result, other_facts_available=other_facts)

    assert not asserts_nonexistence(interpreted.message)


# ======================================================================
# A19 — inventario sin versión activa
# ======================================================================


def test_a19_1_no_active_inventory_as_the_only_capability_is_an_error() -> None:
    """No hubo fuente válida sobre la que consultar: no es una ausencia."""
    result = interpret_inventory_lookup(_no_active_inventory(), other_facts_available=False)

    assert result.status is AnswerStatus.ERROR
    assert AnswerWarning.INVENTORY_UNAVAILABLE in result.warnings
    assert result.status is not AnswerStatus.NO_EVIDENCE
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE not in result.warnings


def test_a19_2_no_active_inventory_beside_other_facts_is_partial() -> None:
    result = interpret_inventory_lookup(_no_active_inventory(), other_facts_available=True)

    assert result.status is AnswerStatus.PARTIAL
    assert AnswerWarning.INVENTORY_UNAVAILABLE in result.warnings
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE not in result.warnings


# ======================================================================
# REJECTED — no se compone como respuesta técnica
# ======================================================================


@pytest.mark.parametrize("other_facts", [True, False])
def test_rejected_is_never_composed_into_an_answer(other_facts: bool) -> None:
    """La autorización se resuelve antes, en la cadena de confianza."""
    rejected = InventoryLookupResult(call_status=CapabilityCallStatus.REJECTED)

    with pytest.raises(UncomposableOutcomeError):
        interpret_inventory_lookup(rejected, other_facts_available=other_facts)


# ======================================================================
# Caso base
# ======================================================================


@pytest.mark.parametrize("other_facts", [True, False])
def test_a_matched_lookup_is_answered_without_absence_warnings(other_facts: bool) -> None:
    result = interpret_inventory_lookup(_matched(), other_facts_available=other_facts)

    assert result.status is AnswerStatus.ANSWERED
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE not in result.warnings
    assert AnswerWarning.CAPABILITY_UNAVAILABLE not in result.warnings
    assert AnswerWarning.INVENTORY_UNAVAILABLE not in result.warnings


def test_an_ok_call_without_an_outcome_is_refused() -> None:
    """`OK` sin resultado no es interpretable: no se adivina."""
    malformed = InventoryLookupResult(call_status=CapabilityCallStatus.OK)

    with pytest.raises(UncomposableOutcomeError):
        interpret_inventory_lookup(malformed, other_facts_available=False)
