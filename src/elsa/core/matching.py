"""Emparejamiento de un renglón con un componente ya existente.

Cuando llega una versión nueva del BOM hay que decidir, renglón a renglón,
si describe un componente que ELSA ya conoce o uno nuevo. Acertar conserva
la historia del componente; equivocarse la destruye, y de forma silenciosa.

Por eso el emparejamiento es **conservador por diseño**: ante la duda no
elige. Las reglas se aplican en orden de fuerza decreciente y la primera que
identifica exactamente un candidato gana:

1. **Activo + plano + referencia de plano.** Dentro de un activo, la
   referencia dentro de un plano señala una pieza concreta. Es la evidencia
   más fuerte disponible.
2. **Código SAP, si es inequívoco.** Un material identifica bien, pero un
   mismo código puede aparecer en varios componentes (dos rodamientos
   iguales en sitios distintos), así que solo vale cuando apunta a uno.
3. **Subsistema + referencia técnica** (modelo o *part number*). Es
   evidencia débil y se marca como tal.

Y tres prohibiciones que no admiten excepción:

- **El nombre por sí solo nunca basta.** Dos componentes distintos pueden
  llamarse igual; fusionarlos por el nombre mezclaría dos historias.
- **Varios candidatos nunca se resuelven automáticamente.** Se marca
  ``unresolved`` y decide una persona.
- **Nunca hay fusión destructiva.** Este módulo no borra ni reescribe nada:
  devuelve una decisión, y quien la aplica conserva ambos lados.

Toda coincidencia automática registra la regla que la produjo, para que
después pueda explicarse por qué dos renglones se consideraron el mismo
componente.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from elsa.core.normalization import canonical_sap_code, normalize_key, normalize_text

__all__ = [
    "ComponentIndex",
    "MatchCandidate",
    "MatchConfidence",
    "MatchResult",
    "drawing_key",
    "match_component",
    "subsystem_attribute_key",
]


class MatchConfidence(StrEnum):
    """Fuerza de la evidencia que sostiene un emparejamiento.

    Coincide con ``ck_bom_item_confidence`` de la migración.
    """

    EXACT = "exact"
    STRONG = "strong"
    WEAK = "weak"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """Los datos de un renglón que pueden identificar un componente."""

    subsystem_name: str | None = None
    component_name: str | None = None
    sap_code: str | None = None
    assembly_drawing: str | None = None
    drawing_reference: str | None = None
    model_reference: str | None = None


@dataclass(frozen=True, slots=True)
class MatchResult:
    """Decisión sobre un renglón.

    - ``component_id`` con ``confidence`` distinta de ``UNRESOLVED``: se
      reconoció un componente existente.
    - ``component_id`` nulo y ``ambiguous`` falso: no hay candidato, es un
      componente nuevo.
    - ``ambiguous`` verdadero: había más de un candidato. **No se elige
      ninguno**; el renglón queda pendiente de revisión humana.
    """

    component_id: str | None = None
    rule: str | None = None
    confidence: MatchConfidence = MatchConfidence.UNRESOLVED
    ambiguous: bool = False
    candidate_ids: tuple[str, ...] = ()

    @property
    def is_new(self) -> bool:
        return self.component_id is None and not self.ambiguous


def drawing_key(assembly_drawing: str | None, drawing_reference: str | None) -> str | None:
    """Clave de «pieza señalada dentro de un plano», o ``None`` si falta algo.

    Hacen falta las dos partes: un plano sin referencia designa el conjunto,
    no una pieza.
    """
    drawing = normalize_key(assembly_drawing)
    reference = normalize_key(drawing_reference)
    if drawing is None or reference is None:
        return None
    return f"{drawing}|{reference}"


def subsystem_attribute_key(subsystem_name: str | None, model_reference: str | None) -> str | None:
    """Clave de «subsistema + referencia técnica», o ``None``.

    Exige la referencia técnica a propósito. Sin ella la clave sería el
    subsistema y el nombre, y emparejar por nombre está prohibido.
    """
    subsystem = normalize_key(subsystem_name)
    model = normalize_key(model_reference)
    if subsystem is None or model is None:
        return None
    return f"{subsystem}|{model}"


@dataclass(frozen=True, slots=True)
class ComponentIndex:
    """Componentes conocidos de un activo, indexados por cada evidencia.

    Cada valor es el conjunto de componentes que han llevado esa evidencia
    alguna vez. Un conjunto de más de uno significa ambigüedad, y la
    ambigüedad no se resuelve sola.
    """

    by_drawing_reference: Mapping[str, frozenset[str]] = field(default_factory=dict)
    by_sap_code: Mapping[str, frozenset[str]] = field(default_factory=dict)
    by_subsystem_attributes: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, entries: "list[tuple[str, MatchCandidate]]") -> "ComponentIndex":
        """Construye el índice a partir de (componente, evidencia observada)."""
        drawings: dict[str, set[str]] = {}
        codes: dict[str, set[str]] = {}
        attributes: dict[str, set[str]] = {}

        for component_id, candidate in entries:
            key = drawing_key(candidate.assembly_drawing, candidate.drawing_reference)
            if key is not None:
                drawings.setdefault(key, set()).add(component_id)
            code = canonical_sap_code(candidate.sap_code)
            if code is not None:
                codes.setdefault(code, set()).add(component_id)
            attribute_key = subsystem_attribute_key(
                candidate.subsystem_name, candidate.model_reference
            )
            if attribute_key is not None:
                attributes.setdefault(attribute_key, set()).add(component_id)

        return cls(
            by_drawing_reference={key: frozenset(value) for key, value in drawings.items()},
            by_sap_code={key: frozenset(value) for key, value in codes.items()},
            by_subsystem_attributes={key: frozenset(value) for key, value in attributes.items()},
        )


# Reglas en orden de fuerza decreciente. La primera que identifica
# exactamente un componente decide; la primera que encuentra varios detiene
# la búsqueda, porque seguir bajando de fuerza para «desempatar» sería
# resolver una ambigüedad con evidencia más débil que la que la creó.
_RULES: tuple[tuple[str, MatchConfidence], ...] = (
    ("drawing_reference", MatchConfidence.EXACT),
    ("sap_code", MatchConfidence.STRONG),
    ("subsystem_attributes", MatchConfidence.WEAK),
)


def match_component(candidate: MatchCandidate, index: ComponentIndex) -> MatchResult:
    """Decide con qué componente se corresponde un renglón, si con alguno."""
    lookups: dict[str, tuple[Mapping[str, frozenset[str]], str | None]] = {
        "drawing_reference": (
            index.by_drawing_reference,
            drawing_key(candidate.assembly_drawing, candidate.drawing_reference),
        ),
        "sap_code": (index.by_sap_code, canonical_sap_code(candidate.sap_code)),
        "subsystem_attributes": (
            index.by_subsystem_attributes,
            subsystem_attribute_key(candidate.subsystem_name, candidate.model_reference),
        ),
    }

    for rule, confidence in _RULES:
        mapping, key = lookups[rule]
        if key is None:
            continue
        matches = mapping.get(key)
        if not matches:
            continue
        if len(matches) == 1:
            return MatchResult(
                component_id=next(iter(matches)),
                rule=rule,
                confidence=confidence,
                candidate_ids=tuple(sorted(matches)),
            )
        return MatchResult(
            component_id=None,
            rule=f"{rule}_ambiguous",
            confidence=MatchConfidence.UNRESOLVED,
            ambiguous=True,
            candidate_ids=tuple(sorted(matches)),
        )

    # Ninguna evidencia coincidió. El nombre existe pero no se usa: no es
    # prueba de identidad.
    _ = normalize_text(candidate.component_name)
    return MatchResult(component_id=None, rule=None, confidence=MatchConfidence.UNRESOLVED)
