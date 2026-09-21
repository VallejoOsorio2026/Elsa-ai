"""Conformidad del contrato Materiales–ELSA, verificada contra el fake.

**Estas pruebas no son una segunda definición del contrato.** La definición
canónica vive, versionada, en el repositorio de Materiales (ADR 0021 §16.4)
y todavía no existe; lo que hay aquí son **aserciones sobre la forma**. Si
la fachada cambia y ELSA no, estas pruebas fallan. Ese es todo el objetivo.

Nada de esto toca red, SQL, JWT ni datos reales: la suite completa debe
pasar en un clon limpio, sin proveedor (regla 24 de ``CLAUDE.md``,
ADR 0021 §18).

Lo que **no** se prueba aquí, porque no existe todavía: el adaptador real,
el enlace de transporte, la lectura del descriptor por red, el estado de
salud degradado y la política de vigencia. M1 sigue abierto.
"""

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from elsa.adapters.fake_materials import (
    DEFAULT_CONTRACT_VERSION,
    DEFAULT_MATERIALS,
    FakeMaterialsFacade,
    scenario,
)
from elsa.core.answers import AnswerStatus, AnswerWarning
from elsa.core.capability_outcomes import (
    CapabilityCallStatus,
    CapabilityOutcome,
    interpret_inventory_lookup,
)
from elsa.core.coverage_policy import InventoryCoverageState
from elsa.ports.materials import (
    EXACT_LOOKUP_MATCH_ORIGINS,
    NULL_SENSES,
    AbsenceReason,
    InventoryCoverage,
    InventoryStatusResult,
    InventoryVersion,
    MatchOrigin,
    MaterialAbsence,
    MaterialAttribution,
    MaterialFacts,
    MaterialLookupRequest,
    MaterialsContractViolationError,
    MaterialsLookupResult,
    MaterialsPort,
    NullSense,
    StockLocation,
    _nullable_fields,
)

pytestmark = pytest.mark.anyio

KNOWN_CODE = "10000001"
KNOWN_OLD_CODE = "OLD-0001"
NULL_HEAVY_CODE = "10000002"
UNKNOWN_CODE = "99999999"


@pytest.fixture
def port() -> MaterialsPort:
    return FakeMaterialsFacade()


def ask(code: str) -> MaterialLookupRequest:
    return MaterialLookupRequest(contract_version=DEFAULT_CONTRACT_VERSION, material_code=code)


# ----------------------------------------------------------------------
# El puerto
# ----------------------------------------------------------------------


def test_the_fake_satisfies_the_port(port: MaterialsPort) -> None:
    assert isinstance(port, MaterialsPort)


def test_the_port_does_not_offer_text_search(port: MaterialsPort) -> None:
    """ADR 0021 §2: la búsqueda por texto está fuera del Piloto 0.1 inicial.

    Su ausencia es deliberada y se comprueba: identificación autoritativa y
    sugerencia asistida no se fusionan, y no se construye por anticipación.
    """
    assert not hasattr(port, "search_materials")
    assert not hasattr(port, "search_materials_by_text")


def test_the_port_no_longer_offers_the_legacy_shape(port: MaterialsPort) -> None:
    """La superficie provisional de `get_material` desaparece con su semántica."""
    assert not hasattr(port, "get_material")


# ----------------------------------------------------------------------
# A. Resultado factual normal · B. Código exacto
# ----------------------------------------------------------------------


async def test_a_known_code_returns_a_fact(port: MaterialsPort) -> None:
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.call_status is CapabilityCallStatus.OK
    assert result.outcome is CapabilityOutcome.MATCHED
    assert result.material is not None
    assert result.material.code == KNOWN_CODE
    assert result.absence is None
    assert result.requested_code == KNOWN_CODE


async def test_b_an_exact_code_is_attributed_as_an_exact_code(port: MaterialsPort) -> None:
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.attribution is not None
    assert result.attribution.match_origin is MatchOrigin.EXACT_MATERIAL_CODE


async def test_a_fact_always_carries_its_attribution(port: MaterialsPort) -> None:
    """ADR 0020 §10: un hecho sin atribución válida no se emite."""
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.attribution is not None
    assert result.attribution.capability == "get_material_availability"
    assert result.attribution.source == "materiales"
    assert result.attribution.contract_version == DEFAULT_CONTRACT_VERSION
    assert result.attribution.source_version == result.inventory


async def test_read_at_and_loaded_at_are_not_the_same_date(port: MaterialsPort) -> None:
    """ADR 0021 §10.6 separa cuándo preguntó ELSA de cuándo terminó la carga."""
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.attribution is not None
    assert result.inventory is not None
    assert result.attribution.read_at != result.inventory.loaded_at


# ----------------------------------------------------------------------
# C. Código antiguo
# ----------------------------------------------------------------------


async def test_c_an_old_code_matches_and_says_so(port: MaterialsPort) -> None:
    """Coincidir por código antiguo es un hecho **distinto** de coincidir por
    el actual, y el contrato conserva la diferencia (ADR 0025 §9)."""
    result = await port.lookup_material_by_code(ask(KNOWN_OLD_CODE))

    assert result.outcome is CapabilityOutcome.MATCHED
    assert result.material is not None
    assert result.material.code == KNOWN_CODE
    assert result.attribution is not None
    assert result.attribution.match_origin is MatchOrigin.OLD_MATERIAL_CODE


# ----------------------------------------------------------------------
# D. Ausencia no autoritativa
# ----------------------------------------------------------------------


async def test_d_an_unknown_code_is_not_returned_not_absent_from_the_world(
    port: MaterialsPort,
) -> None:
    result = await port.lookup_material_by_code(ask(UNKNOWN_CODE))

    assert result.call_status is CapabilityCallStatus.OK
    assert result.outcome is CapabilityOutcome.NOT_RETURNED
    assert result.material is None
    assert result.absence is not None
    assert result.absence.reason is AbsenceReason.NOT_RETURNED_BY_SOURCE
    assert result.absence.authoritative is False


async def test_d_an_absence_is_typed_never_a_bare_empty_value(port: MaterialsPort) -> None:
    """La deuda heredada era exactamente esto: un vacío que se leía como
    «no existe». Ahora un material ausente **nunca viaja solo**."""
    result = await port.lookup_material_by_code(ask(UNKNOWN_CODE))

    assert result.material is None
    assert result.absence is not None
    assert "no devolvió este código" in result.absence.basis


def test_d_the_absence_vocabulary_has_exactly_one_value() -> None:
    """ADR 0021 §8.2. Los tres reservados del §8.3 no se declaran: cada uno
    exige un mecanismo que lo demuestre, y ninguno existe."""
    assert [member.name for member in AbsenceReason] == ["NOT_RETURNED_BY_SOURCE"]


def test_d_no_absence_value_means_nonexistence() -> None:
    """M8 sigue abierto: no hay valor que signifique inexistencia."""
    forbidden = {"NOT_IN_SAP", "NOT_IN_ACTIVE_SNAPSHOT", "OUTSIDE_DECLARED_COVERAGE"}
    assert forbidden.isdisjoint({member.name for member in AbsenceReason})


def test_d_an_authoritative_absence_cannot_be_built() -> None:
    """No es configurable: construirla es un error de contrato (ADR 0021 §8.1)."""
    with pytest.raises(MaterialsContractViolationError, match="M8 remains open"):
        MaterialAbsence(authoritative=True)


async def test_d_absence_composes_as_no_evidence_never_as_a_denial(
    port: MaterialsPort,
) -> None:
    """El puente al núcleo conserva la ausencia no autoritativa."""
    result = await port.lookup_material_by_code(ask(UNKNOWN_CODE))

    interpreted = interpret_inventory_lookup(
        result.as_capability_result(), other_facts_available=False
    )

    assert interpreted.status is AnswerStatus.NO_EVIDENCE
    assert AnswerWarning.CODE_NOT_FOUND_IN_SOURCE in interpreted.warnings


# ----------------------------------------------------------------------
# E. Sin inventario activo · F. Capacidad no disponible
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    [CapabilityCallStatus.NO_ACTIVE_INVENTORY, CapabilityCallStatus.UNAVAILABLE],
)
async def test_ef_the_two_non_answers_are_values_not_exceptions(
    status: CapabilityCallStatus,
) -> None:
    """ADR 0021 §14: los cuatro desenlaces normales son valores.

    Modelar una respuesta legítima como excepción la convertiría en un
    fallo, y quien la recibiera no podría distinguirla de un error de
    programación.
    """
    result = await scenario(status).lookup_material_by_code(ask(KNOWN_CODE))

    assert result.call_status is status
    assert result.outcome is None
    assert result.material is None


@pytest.mark.parametrize(
    "status",
    [CapabilityCallStatus.NO_ACTIVE_INVENTORY, CapabilityCallStatus.UNAVAILABLE],
)
async def test_ef_a_failed_call_never_carries_an_absence(
    status: CapabilityCallStatus,
) -> None:
    """«No se pudo mirar» no es «se miró y no estaba» (ADR 0021 §13.1)."""
    result = await scenario(status).lookup_material_by_code(ask(KNOWN_CODE))

    assert result.absence is None
    assert result.inventory is None
    assert result.coverage is None


async def test_e_no_active_inventory_alone_composes_as_error_not_no_evidence() -> None:
    """No hubo fuente válida sobre la cual consultar. Decir «no hay
    información» sería decirle a un ingeniero que el dato no está."""
    result = await scenario(CapabilityCallStatus.NO_ACTIVE_INVENTORY).lookup_material_by_code(
        ask(KNOWN_CODE)
    )

    interpreted = interpret_inventory_lookup(
        result.as_capability_result(), other_facts_available=False
    )

    assert interpreted.status is AnswerStatus.ERROR
    assert AnswerWarning.INVENTORY_UNAVAILABLE in interpreted.warnings


async def test_f_unavailable_beside_other_facts_degrades_instead_of_failing() -> None:
    result = await scenario(CapabilityCallStatus.UNAVAILABLE).lookup_material_by_code(
        ask(KNOWN_CODE)
    )

    interpreted = interpret_inventory_lookup(
        result.as_capability_result(), other_facts_available=True
    )

    assert interpreted.status is AnswerStatus.PARTIAL
    assert AnswerWarning.CAPABILITY_UNAVAILABLE in interpreted.warnings


def test_the_four_normal_outcomes_are_all_representable() -> None:
    """Los cuatro de ADR 0021 §14, sin que ninguno sea una excepción."""
    assert {status.name for status in CapabilityCallStatus} >= {
        "OK",
        "NO_ACTIVE_INVENTORY",
        "UNAVAILABLE",
    }
    assert {outcome.name for outcome in CapabilityOutcome} == {"MATCHED", "NOT_RETURNED"}


# ----------------------------------------------------------------------
# G. Cobertura
# ----------------------------------------------------------------------


async def test_g_coverage_is_mandatory_in_every_successful_response(
    port: MaterialsPort,
) -> None:
    for code in (KNOWN_CODE, UNKNOWN_CODE):
        result = await port.lookup_material_by_code(ask(code))
        assert result.coverage is not None


async def test_g_unknown_coverage_is_neither_complete_nor_incomplete(
    port: MaterialsPort,
) -> None:
    """ADR 0021 §7.3: `UNKNOWN` no se disfraza de completo, y ADR 0021 §13.2:
    tampoco de incompleto. Afirmar incompletitud sin evidencia sería el mismo
    error en espejo."""
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.coverage is not None
    assert result.coverage.state is InventoryCoverageState.UNKNOWN
    assert result.coverage.state is not InventoryCoverageState.KNOWN_COMPLETE
    assert result.coverage.state is not InventoryCoverageState.KNOWN_INCOMPLETE


async def test_g_unknown_coverage_declares_no_scope_at_all(port: MaterialsPort) -> None:
    """Sin metadata de ingestión que lo respalde, el ámbito no se declara,
    aunque puedan observarse ámbitos en las filas (ADR 0021 §7.2)."""
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.coverage is not None
    assert result.coverage.observed_scope is None
    assert result.coverage.expected_scope is None
    assert result.coverage.missing_scope is None


async def test_g_ambito_in_the_rows_never_becomes_coverage(port: MaterialsPort) -> None:
    """ADR 0025 §7: contar los ámbitos presentes responde a otra pregunta.

    El material devuelto tiene filas en dos ámbitos distintos, y la cobertura
    sigue siendo `UNKNOWN`. Derivarla de esas filas sería una afirmación de
    cobertura sin evidencia.
    """
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.material is not None
    observed = {location.ambito for location in result.material.stock_locations}
    assert len(observed) > 1
    assert result.coverage is not None
    assert result.coverage.state is InventoryCoverageState.UNKNOWN


def test_g_the_coverage_vocabulary_is_not_duplicated() -> None:
    """Se reutiliza el enum del núcleo; no hay una segunda escala paralela."""
    from elsa.core import coverage_policy
    from elsa.ports import materials

    assert materials.InventoryCoverage.__annotations__["state"] is (
        coverage_policy.InventoryCoverageState
    )


# ----------------------------------------------------------------------
# H. Semántica de `null`
# ----------------------------------------------------------------------


async def test_h_extracted_at_is_always_null_and_speaks_about_the_contract(
    port: MaterialsPort,
) -> None:
    """ADR 0027 §7: `DATO_NO_PROPORCIONADO`.

    Significa «este contrato no transporta la fecha de extracción desde
    SAP». **No** significa que SAP carezca de ella.
    """
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.inventory is not None
    assert result.inventory.extracted_at is None
    assert NULL_SENSES["InventoryVersion.extracted_at"] is NullSense.DATO_NO_PROPORCIONADO


async def test_h_extracted_at_null_does_not_make_the_version_unverifiable(
    port: MaterialsPort,
) -> None:
    """ADR 0027 §10.2: la vigencia se verifica con `version_number` +
    `loaded_at`, que son obligatorios y no nulables.

    Leer `extracted_at: null` como señal de vigencia desconocida sería
    exactamente el error que ADR 0027 §7 prohíbe.
    """
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.inventory is not None
    assert result.inventory.extracted_at is None
    assert result.inventory.version_number is not None
    assert result.inventory.loaded_at is not None


async def test_h_extracted_at_null_raises_no_freshness_warning(port: MaterialsPort) -> None:
    """ADR 0027 §10.3: no produce `inventory_freshness_unknown` por sí solo.

    Y no puede producirlo por accidente: M4 operativo sigue abierto y la
    política de vigencia no existe todavía.
    """
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))
    interpreted = interpret_inventory_lookup(
        result.as_capability_result(), other_facts_available=False
    )

    assert interpreted.status is AnswerStatus.ANSWERED
    assert interpreted.warnings == ()


async def test_h_loaded_at_never_stands_in_for_extracted_at(port: MaterialsPort) -> None:
    """ADR 0027 §7: son campos de naturaleza distinta y no se sustituyen."""
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.inventory is not None
    assert result.inventory.extracted_at is None
    assert result.inventory.extracted_at != result.inventory.loaded_at


def test_h_source_file_label_keeps_its_sense_and_is_opaque() -> None:
    """ADR 0027 §7 y L3: `DATO_DESCONOCIDO`. Nulo o no, no habilita ninguna
    afirmación, y de él nunca se extrae una fecha."""
    assert NULL_SENSES["InventoryVersion.source_file_label"] is NullSense.DATO_DESCONOCIDO

    labelled = InventoryVersion(
        version_number=1,
        loaded_at=datetime(2026, 1, 1, tzinfo=UTC),
        row_count=10,
        source_file_label="export-2026-09-08.xlsx",
    )
    unlabelled = InventoryVersion(
        version_number=1,
        loaded_at=datetime(2026, 1, 1, tzinfo=UTC),
        row_count=10,
    )
    # Ninguno de los dos cambia la vigencia, que es lo único que la decide.
    assert labelled.loaded_at == unlabelled.loaded_at


async def test_h_the_three_senses_coexist_in_one_response(port: MaterialsPort) -> None:
    """ADR 0027 L7: es correcto y esperado. Homogeneizarlos sería el error."""
    result = await port.lookup_material_by_code(ask(NULL_HEAVY_CODE))

    assert result.material is not None
    assert result.inventory is not None
    assert result.coverage is not None

    assert result.inventory.extracted_at is None  # DATO_NO_PROPORCIONADO
    assert result.coverage.observed_scope is None  # DATO_NO_PROPORCIONADO
    assert result.material.descripcion is None  # VALOR_FACTUAL_AUSENTE
    assert result.material.material_antiguo is None  # DATO_DESCONOCIDO

    senses = {
        NULL_SENSES["InventoryVersion.extracted_at"],
        NULL_SENSES["InventoryCoverage.observed_scope"],
        NULL_SENSES["MaterialFacts.descripcion"],
        NULL_SENSES["MaterialFacts.material_antiguo"],
    }
    assert len(senses) == 3


def test_h_material_antiguo_keeps_its_irreducible_ambiguity() -> None:
    """ADR 0025 §10 y ADR 0027 §6.3: dos causas indistinguibles por diseño.

    Se clasifica como `DATO_DESCONOCIDO`, y ELSA tiene prohibido resolver la
    ambigüedad por su cuenta. Clasificarlo como `VALOR_FACTUAL_AUSENTE`
    afirmaría que no hay código antiguo, que es una de las dos causas.
    """
    assert NULL_SENSES["MaterialFacts.material_antiguo"] is NullSense.DATO_DESCONOCIDO
    assert NULL_SENSES["MaterialFacts.material_antiguo"] is not NullSense.VALOR_FACTUAL_AUSENTE


def test_h_every_nullable_field_declares_its_sense() -> None:
    """ADR 0027 §6.2.2: un campo nulable sin clasificación es un **defecto de
    contrato**, no un campo permisivo.

    Esta prueba es lo que impide que esa regla se quede en prosa: añadir un
    campo nulable sin declarar qué significa su vacío rompe la suite.
    """
    declared = frozenset(NULL_SENSES)
    actual = _nullable_fields(
        InventoryVersion,
        InventoryCoverage,
        StockLocation,
        MaterialFacts,
        MaterialsLookupResult,
        InventoryStatusResult,
    )

    assert actual - declared == frozenset(), "campos nulables sin sentido declarado"
    assert declared - actual == frozenset(), "sentidos declarados para campos inexistentes"


def test_h_the_three_senses_are_a_closed_vocabulary() -> None:
    assert {sense.name for sense in NullSense} == {
        "VALOR_FACTUAL_AUSENTE",
        "DATO_NO_PROPORCIONADO",
        "DATO_DESCONOCIDO",
    }


def test_h_an_absent_key_is_never_a_signal() -> None:
    """ADR 0027 §11.1: todo campo definido se emite siempre, con `null`
    cuando no lleva valor. La ausencia de una clave no significa nada."""
    emitted = {field.name for field in fields(InventoryVersion)}

    assert emitted == {
        "version_number",
        "loaded_at",
        "row_count",
        "source_file_label",
        "extracted_at",
    }


# ----------------------------------------------------------------------
# I. `dado_de_baja`
# ----------------------------------------------------------------------


async def test_i_marked_for_disposal_is_transported_without_being_actionable(
    port: MaterialsPort,
) -> None:
    """ADR 0025 §4: el contrato lo lleva; no filtra, no oculta, no ordena."""
    result = await port.lookup_material_by_code(ask(NULL_HEAVY_CODE))

    assert result.material is not None
    assert result.material.dado_de_baja.value is True
    # Se devolvió igual que cualquier otro: la señal no excluye.
    assert result.outcome is CapabilityOutcome.MATCHED


async def test_i_marked_for_disposal_degrades_no_state_and_raises_no_warning(
    port: MaterialsPort,
) -> None:
    """No puede sostener el núcleo factual de una respuesta ni emitir aviso
    propio. ELSA no puede ser más restrictiva que la fuente."""
    marked = await port.lookup_material_by_code(ask(NULL_HEAVY_CODE))
    plain = await port.lookup_material_by_code(ask(KNOWN_CODE))

    marked_outcome = interpret_inventory_lookup(
        marked.as_capability_result(), other_facts_available=False
    )
    plain_outcome = interpret_inventory_lookup(
        plain.as_capability_result(), other_facts_available=False
    )

    assert marked_outcome.status is plain_outcome.status
    assert marked_outcome.warnings == plain_outcome.warnings == ()


async def test_i_marked_for_disposal_carries_its_rule_and_is_not_sap(
    port: MaterialsPort,
) -> None:
    """Es `DERIVED_BY_MATERIALES`, y su regla no está versionada todavía."""
    result = await port.lookup_material_by_code(ask(NULL_HEAVY_CODE))

    assert result.material is not None
    assert result.material.dado_de_baja.rule_reference
    assert result.material.dado_de_baja.rule_verifiable is False


# ----------------------------------------------------------------------
# J. `stock_locations`
# ----------------------------------------------------------------------


async def test_j_every_location_is_internally_coherent(port: MaterialsPort) -> None:
    """ADR 0025 §8.2: todos los atributos de un elemento proceden de la
    **misma** fila. Es lo que permite afirmarlos juntos."""
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.material is not None
    assert result.material.stock_locations
    for location in result.material.stock_locations:
        assert isinstance(location, StockLocation)
        assert location.centro
        assert location.almacen
        assert location.ambito
        assert isinstance(location.disponible, Decimal)
        assert isinstance(location.comprometido, Decimal)


async def test_j_a_location_without_ubicacion_is_not_inherited_from_another(
    port: MaterialsPort,
) -> None:
    """ADR 0021 §10.1: el blanco se preserva como nulo y nunca se hereda.

    Rellenarlo hacia abajo mandaría a un ingeniero a un estante equivocado.
    """
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.material is not None
    blanks = [loc for loc in result.material.stock_locations if loc.ubicacion is None]
    assert blanks, "el catálogo del fake debe cubrir este caso"
    assert NULL_SENSES["StockLocation.ubicacion"] is NullSense.DATO_DESCONOCIDO


async def test_j_aggregates_are_derived_and_never_presented_as_sap(
    port: MaterialsPort,
) -> None:
    """ADR 0021 §10.2: `disponible` no es un campo de SAP. Presentarlo como
    dato crudo atribuiría a SAP una decisión que tomó Materiales."""
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.material is not None
    assert result.material.total_disponible.rule_reference
    assert result.material.total_comprometido.rule_reference


async def test_j_elsa_does_not_recompute_the_aggregates(port: MaterialsPort) -> None:
    """ELSA consume el resultado y **no exige sus componentes** (regla 4).

    Esta prueba comprueba que el total llega tal cual, no que cuadre: si
    ELSA validara la suma estaría recalculando una regla ajena, y la
    verificación de las derivaciones pertenece al proveedor (ADR 0021 §10.2).
    """
    result = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert result.material is not None
    assert isinstance(result.material.total_disponible.value, Decimal)


# ----------------------------------------------------------------------
# K. `match_origin`
# ----------------------------------------------------------------------


def test_k_the_match_vocabulary_is_closed() -> None:
    assert {origin.name for origin in MatchOrigin} == {
        "EXACT_MATERIAL_CODE",
        "OLD_MATERIAL_CODE",
        "OTHER_MATCH",
    }


def test_k_only_a_match_by_code_is_admissible_in_an_exact_lookup() -> None:
    assert EXACT_LOOKUP_MATCH_ORIGINS == {
        MatchOrigin.EXACT_MATERIAL_CODE,
        MatchOrigin.OLD_MATERIAL_CODE,
    }
    assert MatchOrigin.OTHER_MATCH not in EXACT_LOOKUP_MATCH_ORIGINS


def test_k_other_match_in_an_exact_lookup_is_a_contract_violation() -> None:
    """ADR 0021 §6 y ADR 0025 §9: **no es un resultado de peor calidad**.

    Es el cortafuegos contra la caída silenciosa a similitud. Hoy, en
    Materiales, un código que no coincide literalmente degrada a parecido
    sobre la descripción sin avisar; bajo este contrato eso no pasa
    inadvertido.
    """
    inventory = InventoryVersion(
        version_number=1, loaded_at=datetime(2026, 1, 1, tzinfo=UTC), row_count=1
    )

    with pytest.raises(MaterialsContractViolationError, match="not admissible in an exact lookup"):
        MaterialsLookupResult(
            call_status=CapabilityCallStatus.OK,
            contract_version="1",
            inventory=inventory,
            coverage=InventoryCoverage(state=InventoryCoverageState.UNKNOWN),
            requested_code="X",
            outcome=CapabilityOutcome.MATCHED,
            material=DEFAULT_MATERIALS[0].facts,
            attribution=MaterialAttribution(
                source_version=inventory,
                contract_version="1",
                read_at=datetime(2026, 1, 2, tzinfo=UTC),
                match_origin=MatchOrigin.OTHER_MATCH,
            ),
        )


def test_k_an_unknown_match_value_degrades_to_other_match() -> None:
    """ADR 0025 §9: el tratamiento declarado de valores desconocidos es lo
    que hace **compatible** ampliar el vocabulario (ADR 0021 §15.1).

    Degradar no es perder información: es negarse a tratar como prueba de
    identidad algo que no se sabe leer.
    """
    assert MatchOrigin.from_source("descripcion aproximada") is MatchOrigin.OTHER_MATCH
    assert MatchOrigin.from_source("exact_material_code") is MatchOrigin.EXACT_MATERIAL_CODE


# ----------------------------------------------------------------------
# L. Excepciones, reservadas
# ----------------------------------------------------------------------


def test_l_a_successful_call_must_carry_an_outcome() -> None:
    with pytest.raises(MaterialsContractViolationError, match="must carry an outcome"):
        MaterialsLookupResult(call_status=CapabilityCallStatus.OK)


def test_l_a_matched_outcome_without_a_material_is_a_violation() -> None:
    inventory = InventoryVersion(
        version_number=1, loaded_at=datetime(2026, 1, 1, tzinfo=UTC), row_count=1
    )
    with pytest.raises(MaterialsContractViolationError, match="must carry the material"):
        MaterialsLookupResult(
            call_status=CapabilityCallStatus.OK,
            inventory=inventory,
            coverage=InventoryCoverage(state=InventoryCoverageState.UNKNOWN),
            outcome=CapabilityOutcome.MATCHED,
        )


def test_l_a_not_returned_outcome_must_carry_a_typed_absence() -> None:
    """ADR 0021 §8.2: una ausencia se tipa, nunca son cero filas mudas."""
    inventory = InventoryVersion(
        version_number=1, loaded_at=datetime(2026, 1, 1, tzinfo=UTC), row_count=1
    )
    with pytest.raises(MaterialsContractViolationError, match="never zero mute rows"):
        MaterialsLookupResult(
            call_status=CapabilityCallStatus.OK,
            inventory=inventory,
            coverage=InventoryCoverage(state=InventoryCoverageState.UNKNOWN),
            outcome=CapabilityOutcome.NOT_RETURNED,
        )


def test_l_a_failed_call_carrying_payload_is_a_violation() -> None:
    with pytest.raises(MaterialsContractViolationError, match="carries no payload"):
        MaterialsLookupResult(
            call_status=CapabilityCallStatus.UNAVAILABLE,
            outcome=CapabilityOutcome.NOT_RETURNED,
        )


def test_l_a_successful_call_without_coverage_is_a_violation() -> None:
    inventory = InventoryVersion(
        version_number=1, loaded_at=datetime(2026, 1, 1, tzinfo=UTC), row_count=1
    )
    with pytest.raises(MaterialsContractViolationError, match="coverage is mandatory"):
        MaterialsLookupResult(
            call_status=CapabilityCallStatus.OK,
            inventory=inventory,
            outcome=CapabilityOutcome.MATCHED,
            material=DEFAULT_MATERIALS[0].facts,
        )


def test_l_the_four_normal_outcomes_raise_nothing() -> None:
    """La comprobación complementaria: las excepciones están reservadas, y
    ningún desenlace normal pasa por ellas."""
    inventory = InventoryVersion(
        version_number=1, loaded_at=datetime(2026, 1, 1, tzinfo=UTC), row_count=1
    )
    coverage = InventoryCoverage(state=InventoryCoverageState.UNKNOWN)

    MaterialsLookupResult(call_status=CapabilityCallStatus.NO_ACTIVE_INVENTORY)
    MaterialsLookupResult(call_status=CapabilityCallStatus.UNAVAILABLE)
    MaterialsLookupResult(
        call_status=CapabilityCallStatus.OK,
        inventory=inventory,
        coverage=coverage,
        outcome=CapabilityOutcome.NOT_RETURNED,
        absence=MaterialAbsence(),
    )
    MaterialsLookupResult(
        call_status=CapabilityCallStatus.OK,
        inventory=inventory,
        coverage=coverage,
        outcome=CapabilityOutcome.MATCHED,
        material=DEFAULT_MATERIALS[0].facts,
        attribution=MaterialAttribution(
            source_version=inventory,
            contract_version="1",
            read_at=datetime(2026, 1, 2, tzinfo=UTC),
            match_origin=MatchOrigin.EXACT_MATERIAL_CODE,
        ),
    )


def test_l_rejected_stays_outside_the_port_boundary() -> None:
    """ADR 0021 §5: la autorización se resuelve en la cadena de confianza.

    El puerto puede transportar el estado, pero la composición lo rechaza.
    Esa frontera ya existía y M1-A no la mueve.
    """
    from elsa.core.capability_outcomes import UncomposableOutcomeError

    result = MaterialsLookupResult(call_status=CapabilityCallStatus.REJECTED)

    with pytest.raises(UncomposableOutcomeError):
        interpret_inventory_lookup(result.as_capability_result(), other_facts_available=False)


# ----------------------------------------------------------------------
# M. Minimización del request
# ----------------------------------------------------------------------


def test_m_the_request_carries_exactly_two_fields() -> None:
    """ADR 0021 §3: dos campos, nada más, y es verificable por prueba."""
    assert {field.name for field in fields(MaterialLookupRequest)} == {
        "contract_version",
        "material_code",
    }


def test_m_the_request_cannot_carry_elsa_context() -> None:
    """ADR 0021 §3.1: enviar los alcances de ELSA exportaría su modelo de
    autorización a un sistema que no lo tiene."""
    forbidden = {
        "question",
        "user_question",
        "scopes",
        "asset",
        "asset_id",
        "bom",
        "bom_item",
        "user_id",
        "response_ref",
        "evidence",
        "history",
    }
    assert forbidden.isdisjoint({field.name for field in fields(MaterialLookupRequest)})


def test_m_the_request_is_immutable() -> None:
    request = ask(KNOWN_CODE)
    with pytest.raises(FrozenInstanceError):
        request.material_code = "otro"  # type: ignore[misc]


# ----------------------------------------------------------------------
# N. Determinismo
# ----------------------------------------------------------------------


async def test_n_the_fake_is_deterministic(port: MaterialsPort) -> None:
    first = await port.lookup_material_by_code(ask(KNOWN_CODE))
    second = await port.lookup_material_by_code(ask(KNOWN_CODE))

    assert first == second


async def test_n_two_facades_built_alike_answer_alike() -> None:
    first = await FakeMaterialsFacade().lookup_material_by_code(ask(KNOWN_CODE))
    second = await FakeMaterialsFacade().lookup_material_by_code(ask(KNOWN_CODE))

    assert first == second


async def test_n_absence_is_deterministic_too(port: MaterialsPort) -> None:
    first = await port.lookup_material_by_code(ask(UNKNOWN_CODE))
    second = await port.lookup_material_by_code(ask(UNKNOWN_CODE))

    assert first == second


# ----------------------------------------------------------------------
# Estado del inventario y descriptor
# ----------------------------------------------------------------------


async def test_inventory_status_answers_without_consulting_any_material(
    port: MaterialsPort,
) -> None:
    status = await port.get_inventory_status()

    assert status.call_status is CapabilityCallStatus.OK
    assert status.inventory is not None
    assert status.coverage is not None


async def test_inventory_status_without_an_active_version_carries_no_metadata() -> None:
    status = await scenario(CapabilityCallStatus.NO_ACTIVE_INVENTORY).get_inventory_status()

    assert status.inventory is None
    assert status.coverage is None


async def test_the_descriptor_declares_the_version_and_what_is_not_transported(
    port: MaterialsPort,
) -> None:
    """ADR 0021 §15.3 y ADR 0027 §11.3: el descriptor declara la
    **capacidad**; un `null` clasificado declara el **caso**."""
    descriptor = await port.get_contract_descriptor()

    assert descriptor.contract_version == DEFAULT_CONTRACT_VERSION
    assert isinstance(descriptor.contract_version, str)
    assert "inventory.extracted_at" in descriptor.unsupported_fields


async def test_the_descriptor_declares_the_operations_it_offers(port: MaterialsPort) -> None:
    descriptor = await port.get_contract_descriptor()

    names = {operation.name for operation in descriptor.operations}
    assert names == {
        "lookup_material_by_code",
        "get_inventory_status",
        "get_contract_descriptor",
    }
    assert "search_materials_by_text" not in names
