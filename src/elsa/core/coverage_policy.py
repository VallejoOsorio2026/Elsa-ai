"""Qué puede afirmar ELSA cuando nadie ha demostrado qué cubre el inventario.

Esto **no es** la integración con Materiales: no hay aquí HTTP, ni SQL, ni
JWT, ni fachada, ni representación de un código SAP. Es la capa que decide,
sobre un resultado ya obtenido, si la respuesta puede emitirse y con qué
marcas.

La pregunta que resuelve el módulo es distinta de la que resuelve
`capability_outcomes`. Allí: «¿qué hizo la fuente con el código pedido?».
Aquí: **«¿sé que el snapshot consultado cubre el ámbito que esta respuesta
necesita?»** (ADR 0021 §12). Son independientes, y confundirlas es
precisamente el error que este módulo existe para impedir.

Mientras nadie declare el alcance de una carga, el estado de cobertura es
`UNKNOWN` (ADR 0021 §7.3). `UNKNOWN` **no impide responder**: obliga a que
la respuesta se atribuya a la fuente y al snapshot que la produjeron, nunca
al mundo. Lo que sí impide es una clase entera de afirmaciones:

- **Clase 1, acotable** — se vuelve verdadera acotándola a su fuente. «Según
  el inventario cargado en Materiales, este código tiene existencias en las
  ubicaciones devueltas». Se permite, degradada y marcada.
- **Clase 2, no acotable** — cuantifica sobre un universo cuyo alcance se
  desconoce. «No hay en ningún almacén», «estos son todos los materiales que
  tenemos». **Ninguna acotación la vuelve verdadera**, así que no se degrada:
  se rechaza (ADR 0023 §9 y §10.2).

`PARTIAL` no basta para la Clase 2. `PARTIAL` significa «respuesta con
respaldo incompleto», y una afirmación universal sobre un universo
desconocido no tiene respaldo incompleto: **no tiene respaldo**. Un aviso
junto a ella la haría parecer una verdad matizada.

Nada de esto lo decide un modelo. `requires_complete_inventory_coverage` es
una propiedad **determinista** de la plantilla, derivada de los campos que la
composición va a afirmar, y llega aquí como dato de entrada (ADR 0021 §12,
ADR 0023 §10.2.5).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from elsa.core.answers import AnswerStatus, AnswerWarning, order_warnings
from elsa.core.capability_outcomes import (
    UNBOUNDED_CLAIM_REFUSAL_MESSAGE,
    CapabilityCallStatus,
    CapabilityOutcome,
    InventoryLookupResult,
    interpret_inventory_lookup,
)

__all__ = [
    "COVERAGE_SENSITIVE_FIELDS",
    "AssertedInventoryField",
    "ClaimScope",
    "CoverageDecision",
    "CoverageRequirement",
    "IncoherentCoverageRequirementError",
    "InventoryCoverageState",
    "coverage_is_relevant",
    "decide_under_coverage",
]


class InventoryCoverageState(StrEnum):
    """Qué se sabe del ámbito que cubrió la carga. Forma de ADR 0021 §7.1."""

    KNOWN_COMPLETE = "known_complete"
    """Ámbito esperado declarado, observado respaldado por metadata, nada falta."""

    KNOWN_INCOMPLETE = "known_incomplete"
    """Se **demuestra** que falta un ámbito esperado."""

    UNKNOWN = "unknown"
    """Cualquier otro caso, incluido que falte el respaldo de metadata.

    **Es el estado disponible hoy** (ADR 0023 §6). No es un error, y no se
    disfraza de completo ni de incompleto.
    """


class AssertedInventoryField(StrEnum):
    """Qué va a afirmar la composición sobre lo que devolvió Materiales.

    No es el esquema de la respuesta de Materiales: es la declaración de la
    **plantilla** sobre qué campos piensa afirmar, que es de donde sale
    `requires_complete_inventory_coverage`.
    """

    DESCRIPTION = "description"
    """Campo estable: no cambia porque falte un ámbito."""

    UNIT_OF_MEASURE = "unit_of_measure"
    """Campo estable."""

    STOCK_QUANTITY = "stock_quantity"
    """Existencias. Un ámbito no cubierto las subestima en silencio."""

    STOCK_LOCATIONS = "stock_locations"
    """Ubicaciones devueltas. Enumerar sin cobertura enumera de menos."""

    AVAILABILITY = "availability"
    """Disponibilidad. Responde «¿lo tenemos?», que es una cuantificación."""


COVERAGE_SENSITIVE_FIELDS: frozenset[AssertedInventoryField] = frozenset(
    {
        AssertedInventoryField.STOCK_QUANTITY,
        AssertedInventoryField.STOCK_LOCATIONS,
        AssertedInventoryField.AVAILABILITY,
    }
)
"""Campos cuya verdad depende de qué ámbito cubrió el snapshot.

La distinción es la de ADR 0021 §12: la descripción de un material no cambia
porque falte una sede; sus existencias, sí.
"""


class ClaimScope(StrEnum):
    """Sobre qué universo habla la afirmación. Clases de ADR 0023 §9."""

    ATTRIBUTED_TO_SOURCE = "attributed_to_source"
    """Clase 1. Se acota a la fuente y al snapshot que la produjeron."""

    UNIVERSAL = "universal"
    """Clase 2. Cuantifica sobre un universo cuyo alcance nadie declaró.

    Ninguna plantilla del Piloto 0.1 produce una de estas. El valor existe
    para que la prohibición sea **comprobable** en vez de confiada: una
    plantilla futura que lo declarase quedaría bloqueada por la política, no
    por una revisión humana.
    """


class IncoherentCoverageRequirementError(ValueError):
    """Una afirmación universal que dice no necesitar cobertura completa.

    No es un caso a resolver, es una contradicción: el universo **es** la
    afirmación. Se rechaza al construirla, no al emitirla, para que nunca
    llegue a existir un requisito capaz de autorizarse a sí mismo.
    """


@dataclass(frozen=True, slots=True)
class CoverageRequirement:
    """Lo que la plantilla exige de la cobertura. **No lo decide un LLM.**

    Es una propiedad del plan, fijada antes de ejecutar nada y derivable de
    los campos declarados. El modelo no la recibe, no la propone y no puede
    levantarla: esta política la lee como dato de entrada.
    """

    requires_complete_inventory_coverage: bool
    claim_scope: ClaimScope = ClaimScope.ATTRIBUTED_TO_SOURCE

    def __post_init__(self) -> None:
        if self.claim_scope is ClaimScope.UNIVERSAL and not (
            self.requires_complete_inventory_coverage
        ):
            raise IncoherentCoverageRequirementError(
                "a universal claim always requires complete inventory coverage"
            )

    @classmethod
    def for_asserted_fields(
        cls,
        fields: Iterable[AssertedInventoryField],
        *,
        claim_scope: ClaimScope = ClaimScope.ATTRIBUTED_TO_SOURCE,
    ) -> "CoverageRequirement":
        """Deriva la exigencia de los campos que la composición va a afirmar.

        Determinista y sin orden: los mismos campos dan el mismo requisito,
        lleguen como lleguen. Una afirmación universal exige cobertura
        completa aunque solo toque campos estables, porque lo que afirma no
        es el campo sino el universo.
        """
        demands = bool(COVERAGE_SENSITIVE_FIELDS.intersection(fields))
        return cls(
            requires_complete_inventory_coverage=(demands or claim_scope is ClaimScope.UNIVERSAL),
            claim_scope=claim_scope,
        )


@dataclass(frozen=True, slots=True)
class CoverageDecision:
    """Lo que la política autoriza a emitir, ya aplicada la cobertura."""

    status: AnswerStatus
    warnings: tuple[AnswerWarning, ...]
    message: str
    claim_emitted: bool
    """Si la afirmación dependiente de cobertura llega a emitirse.

    Se expone aparte del estado porque son cosas distintas y la garantía A21
    las comprueba por separado: una Clase 2 rechazada y una Clase 1 degradada
    pueden compartir estado y no comparten esto.
    """


def coverage_is_relevant(
    outcome: CapabilityOutcome | None, requirement: CoverageRequirement
) -> bool:
    """Si la cobertura afecta a lo que la respuesta va a afirmar.

    Tabla de ADR 0021 §12.1, y **conservadora** por decisión de ese ADR:

    | Caso | Relevancia |
    |---|---|
    | `MATCHED` afirmando existencias o totales | relevante |
    | `MATCHED` afirmando solo campos estables | no relevante |
    | `NOT_RETURNED` | relevante, conservadoramente |

    Un código ausente no dice en qué ámbito estaría, así que la relevancia
    es indecidible y se resuelve del lado seguro. Con campos estables, en
    cambio, degradar sería ruido, y el ruido enseña a ignorar los avisos
    (ADR 0023 §10.1.6).
    """
    if outcome is CapabilityOutcome.NOT_RETURNED:
        return True
    return requirement.requires_complete_inventory_coverage


def decide_under_coverage(
    result: InventoryLookupResult,
    *,
    requirement: CoverageRequirement,
    coverage: InventoryCoverageState,
    other_facts_available: bool,
) -> CoverageDecision:
    """Aplica la cobertura sobre un resultado ya interpretado.

    Compone, sin sustituirla, la política de ausencia segura: lo que A6, A6b,
    A18 y A19 garantizan sigue decidiéndose en `interpret_inventory_lookup`,
    y esta función solo puede **restringir** lo que aquella autorizó. Un
    `REJECTED` o una ausencia autoritativa siguen siendo inconcebibles y
    siguen levantando la misma excepción.

    **No se crea ningún `AnswerStatus` nuevo** (ADR 0017, ADR 0023 §10.2.3).
    """
    interpreted = interpret_inventory_lookup(result, other_facts_available=other_facts_available)

    if result.call_status is not CapabilityCallStatus.OK:
        # No se llegó a consultar nada: la cobertura de lo que no se miró no
        # añade ni quita. Decir aquí «cobertura desconocida» convertiría un
        # fallo técnico en un problema de alcance, que es otra cosa.
        return CoverageDecision(
            status=interpreted.status,
            warnings=interpreted.warnings,
            message=interpreted.message,
            claim_emitted=False,
        )

    coverage_satisfied = coverage is InventoryCoverageState.KNOWN_COMPLETE
    warning = _coverage_warning(coverage)

    warnings = list(interpreted.warnings)
    if warning is not None and coverage_is_relevant(result.outcome, requirement):
        warnings.append(warning)

    status = interpreted.status
    if requirement.requires_complete_inventory_coverage and not coverage_satisfied:
        # Regla B.1: no se produce una respuesta factual completa. Nunca.
        if status is AnswerStatus.ANSWERED:
            status = AnswerStatus.PARTIAL

    claim_emitted = result.outcome is CapabilityOutcome.MATCHED
    message = interpreted.message

    if requirement.claim_scope is ClaimScope.UNIVERSAL and not coverage_satisfied:
        # Regla B.3: la afirmación no se emite, ni degradada ni acompañada
        # de aviso. Lo que se emite es la incapacidad: qué se consultó y qué
        # no puede concluirse. El aviso que sí queda marca **la respuesta**,
        # no acompaña a una afirmación que no existe.
        claim_emitted = False
        message = UNBOUNDED_CLAIM_REFUSAL_MESSAGE
        status = AnswerStatus.PARTIAL if other_facts_available else AnswerStatus.NO_EVIDENCE

    return CoverageDecision(
        status=status,
        warnings=order_warnings(warnings),
        message=message,
        claim_emitted=claim_emitted,
    )


def _coverage_warning(coverage: InventoryCoverageState) -> AnswerWarning | None:
    """Un estado, un aviso. `UNKNOWN` **no** se presenta como `INCOMPLETE`.

    La convención es la de `inventory_freshness_unknown`: nombrar el
    desconocimiento en lugar de asimilarlo al peor caso conocido, porque
    afirmar incompletitud sin evidencia es el mismo error en espejo
    (ADR 0021 §13.2).
    """
    if coverage is InventoryCoverageState.UNKNOWN:
        return AnswerWarning.COVERAGE_UNKNOWN
    if coverage is InventoryCoverageState.KNOWN_INCOMPLETE:
        return AnswerWarning.COVERAGE_INCOMPLETE
    return None
