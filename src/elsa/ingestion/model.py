"""Estructuras que devuelven los parsers.

Son datos puros: sin identificadores de base, sin componentes resueltos y
sin decisiones tomadas. El emparejamiento con componentes existentes, el
versionado y la persistencia ocurren después, sobre estas estructuras.

Cada valor sensible viaja en dos formas: la normalizada, con la que se
compara, y la original, con la que se le demuestra a un ingeniero qué decía
exactamente su archivo.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

__all__ = [
    "IngestionWarning",
    "ParsedBomRow",
    "ParsedDrawingImage",
    "ParsedEngineeringBom",
    "ParsedFailureMode",
    "ParsedOptionRow",
    "ParsedSapItem",
    "ParsedSapSnapshot",
    "ParsedSodCriterion",
]


@dataclass(frozen=True, slots=True)
class IngestionWarning:
    """Aviso que no impide la importación pero sí la revisión ciega.

    ``code`` es estable y comparable en tests y en la API; ``message`` es
    para una persona. Ninguno lleva contenido técnico del archivo.
    """

    code: str
    message: str
    location: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedBomRow:
    """Un renglón del BOM de Ingeniería."""

    source_row: int
    position: str | None = None
    subsystem_name: str | None = None
    component_name: str | None = None
    sap_code: str | None = None
    sap_code_original: str | None = None
    technical_description: str | None = None
    quantity: Decimal | None = None
    quantity_original: str | None = None
    unit: str | None = None
    model_reference: str | None = None
    assembly_drawing: str | None = None
    drawing_reference: str | None = None
    bom_update_flag: str | None = None
    inventory_strategy: str | None = None
    stock_max: Decimal | None = None
    stock_min: Decimal | None = None
    source_stock: Decimal | None = None
    remarks: str | None = None
    extra: dict[str, str] = field(default_factory=dict)
    """Columnas presentes en la plantilla que este bloque no reconoce.

    Se conservan en vez de descartarse: perder información por no haberla
    previsto es peor que guardarla sin interpretarla.
    """


@dataclass(frozen=True, slots=True)
class ParsedFailureMode:
    """Un renglón del AMEF. El NPR lo calcula el backend, no el Excel."""

    source_row: int
    subsystem_name: str | None = None
    component_name: str | None = None
    sap_code: str | None = None
    failure_mode: str | None = None
    effect: str | None = None
    cause: str | None = None
    severity: int | None = None
    occurrence: int | None = None
    detection: int | None = None
    action: str | None = None
    preventive_plan: str | None = None
    corrective_action: str | None = None
    remarks: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def rpn(self) -> int | None:
        """Número de Prioridad de Riesgo: ``S x O x D``.

        Se calcula aquí, de forma determinística, en vez de leer el valor que
        el Excel hubiera dejado cacheado. Si falta cualquiera de los tres
        factores no hay NPR: un NPR parcial sería un número inventado.
        """
        if self.severity is None or self.occurrence is None or self.detection is None:
            return None
        return self.severity * self.occurrence * self.detection


@dataclass(frozen=True, slots=True)
class ParsedSodCriterion:
    """Una fila de las tablas de criterios S/O/D."""

    source_row: int
    dimension: str
    scale_value: int | None = None
    label: str | None = None
    description: str | None = None
    range_low: Decimal | None = None
    range_high: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ParsedOptionRow:
    """Una opción de las tablas de opciones de la plantilla."""

    source_row: int
    table_name: str
    option_value: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedDrawingImage:
    """Imagen embebida extraída del libro, como evidencia.

    No se interpreta: en este bloque no hay OCR ni visión artificial. Se
    conservan los bytes, su hash y de dónde salieron.
    """

    content: bytes
    content_type: str
    sha256: str
    sheet_name: str | None = None
    anchor: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    drawing_number: str | None = None
    association_rule: str | None = None

    @property
    def is_associated(self) -> bool:
        return self.drawing_number is not None


@dataclass(frozen=True, slots=True)
class ParsedEngineeringBom:
    """Resultado completo de interpretar el XLSX aprobado por Ingeniería."""

    sheets_detected: tuple[str, ...] = ()
    bom_rows: tuple[ParsedBomRow, ...] = ()
    failure_modes: tuple[ParsedFailureMode, ...] = ()
    sod_criteria: tuple[ParsedSodCriterion, ...] = ()
    option_rows: tuple[ParsedOptionRow, ...] = ()
    drawing_images: tuple[ParsedDrawingImage, ...] = ()
    warnings: tuple[IngestionWarning, ...] = ()


@dataclass(frozen=True, slots=True)
class ParsedSapItem:
    """Un renglón del snapshot de SAP.

    ``entry_kind`` distingue un material de un equipo/objeto técnico. La
    distinción es estructural: comparar un equipo hijo contra un material del
    BOM produciría discrepancias inventadas.
    """

    source_row: int
    entry_kind: str
    position: str | None = None
    sap_code: str | None = None
    description: str | None = None
    quantity: Decimal | None = None
    quantity_original: str | None = None
    unit: str | None = None
    parent_path: str | None = None
    depth: int = 0
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ParsedSapSnapshot:
    """Resultado de interpretar un HTM exportado de SAP."""

    functional_location: str | None = None
    description: str | None = None
    valid_from: date | None = None
    items: tuple[ParsedSapItem, ...] = ()
    warnings: tuple[IngestionWarning, ...] = ()

    @property
    def materials(self) -> tuple[ParsedSapItem, ...]:
        return tuple(item for item in self.items if item.entry_kind == "material")

    @property
    def equipments(self) -> tuple[ParsedSapItem, ...]:
        return tuple(item for item in self.items if item.entry_kind == "equipment")
