"""Puerto de consulta de inventario al Asistente de Materiales.

Materiales sigue siendo propietario de su inventario (~65.000 registros);
ELSA consulta a través de este puerto y **no duplica** esos datos (regla 4
de ``CLAUDE.md``).

Lo que hay aquí es el **contrato esperado**, expresado como tipos: la forma
que ELSA exige de la fachada contractual Materiales–ELSA decidida en
[ADR 0021], con la semántica de campos de [ADR 0025] y la de ``null`` de
[ADR 0027]. Es una **aserción sobre la forma**, no una segunda definición
canónica: la definición canónica vive, versionada, en el repositorio de
Materiales (ADR 0021 §16.4), y todavía no existe.

Tres fronteras que este módulo no cruza:

- **No hay transporte.** Ni HTTP, ni SQL, ni PostgREST, ni JWT. Qué enlace
  usa la fachada es una decisión abierta, y el descriptor la declara
  (ADR 0021 §2); el adaptador la aplicará, este puerto no la conoce.
- **No hay lógica de negocio.** Nada aquí agrega existencias, clasifica
  ubicaciones, calcula vigencia ni decide cobertura. Esas reglas son de
  Materiales (regla 4) o del plan, y el puerto solo transporta su
  resultado.
- **No hay política de respuesta.** Qué ``AnswerStatus`` produce cada
  resultado lo decide :mod:`elsa.core.capability_outcomes`, y este puerto
  le entrega el resultado con :meth:`MaterialsLookupResult.as_capability_result`.

Vocabulario reutilizado, nunca duplicado (ADR 0028): ``CapabilityCallStatus``
y ``CapabilityOutcome`` de :mod:`elsa.core.capability_outcomes`, e
``InventoryCoverageState`` de :mod:`elsa.core.coverage_policy`. Crear aquí
enums equivalentes daría dos vocabularios para lo mismo, que es la forma más
barata de que diverjan.

.. [ADR 0021] ``docs/adr/0021-contrato-de-inventario-con-materiales.md``
.. [ADR 0025] ``docs/adr/0025-semantica-procedencia-y-temporalidad-de-los-campos-de-inventario.md``
.. [ADR 0027] ``docs/adr/0027-semantica-de-null-y-disponibilidad-de-metadata-del-inventario.md``
.. [ADR 0028] ``docs/adr/0028-forma-del-resultado-contractual-del-puerto-de-materiales.md``
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from elsa.core.capability_outcomes import (
    CapabilityCallStatus,
    CapabilityOutcome,
    InventoryLookupResult,
)
from elsa.core.coverage_policy import InventoryCoverageState

__all__ = [
    "CONTRACT_CAPABILITY",
    "CONTRACT_SOURCE",
    "EXACT_LOOKUP_MATCH_ORIGINS",
    "NULL_SENSES",
    "AbsenceReason",
    "ContractDescriptor",
    "ContractOperation",
    "DerivedValue",
    "FieldProvenance",
    "InventoryStatusResult",
    "InventoryVersion",
    "MatchOrigin",
    "MaterialAbsence",
    "MaterialAttribution",
    "MaterialFacts",
    "MaterialLookupRequest",
    "MaterialsContractViolationError",
    "MaterialsLookupResult",
    "MaterialsPort",
    "NullSense",
    "StockLocation",
]


CONTRACT_CAPABILITY = "get_material_availability"
"""Capacidad de ADR 0020 §2 a la que sirve este puerto."""

CONTRACT_SOURCE = "materiales"
"""Origen que firma cada hecho emitido por este contrato (ADR 0021 §10.6)."""


class MaterialsContractViolationError(Exception):
    """La respuesta recibida no es una respuesta válida del contrato.

    **No es un resultado de peor calidad: es una respuesta inválida.** Los
    cuatro desenlaces normales —hecho, código no devuelto, sin inventario
    activo y capacidad no disponible— son *valores*, no excepciones
    (ADR 0021 §14). Esta excepción queda para lo que el contrato declara
    imposible: un lookup exacto que responde con una coincidencia que no
    prueba identidad (ADR 0025 §9), una ausencia que se declara
    autoritativa mientras M8 siga abierto (ADR 0021 §8.1), o un sobre cuyas
    partes se contradicen.

    Que un fallo de red o un tiempo agotado **no** llegue por aquí es
    deliberado: ese caso es ``CapabilityCallStatus.UNAVAILABLE``, y lo
    traduce el adaptador (ADR 0021 §5).
    """


# ----------------------------------------------------------------------
# Vocabularios propios del contrato
#
# Solo aparecen aquí los que **no** tienen ya un equivalente en el núcleo.
# El estado de la llamada, el desenlace por código y el estado de cobertura
# se importan; duplicarlos está prohibido (ADR 0028).
# ----------------------------------------------------------------------


class MatchOrigin(StrEnum):
    """Cómo se encontró el material. Vocabulario cerrado de ADR 0025 §9.

    Es ``MATCH_METADATA``: dice **cómo** se encontró, nunca **qué es**
    (ADR 0021 §10.4). Un dato hallado por descripción aproximada no es el
    mismo hecho que uno hallado por código exacto, y conservar esa
    diferencia es obligatorio (ADR 0020 §10).
    """

    EXACT_MATERIAL_CODE = "exact_material_code"
    """El código pedido coincide literalmente con el código del material."""

    OLD_MATERIAL_CODE = "old_material_code"
    """Coincide con el código antiguo del material."""

    OTHER_MATCH = "other_match"
    """Cualquier otra forma de coincidencia. **Nunca prueba identidad.**"""

    @classmethod
    def from_source(cls, value: str) -> "MatchOrigin":
        """Lee un valor de la fuente, tratando lo desconocido como ``OTHER_MATCH``.

        ADR 0025 §9 declara este tratamiento **por adelantado**, y es lo que
        convierte ampliar el vocabulario en un cambio **compatible**
        (ADR 0021 §15.1): añadir un valor a un enum cerrado sería
        incompatible *salvo que el consumidor declare qué hace con los
        valores desconocidos*. Esto es esa declaración, ejecutable.

        Degradar a ``OTHER_MATCH`` no es perder información: es negarse a
        tratar como prueba de identidad algo que no se sabe leer.
        """
        try:
            return cls(value)
        except ValueError:
            return cls.OTHER_MATCH


EXACT_LOOKUP_MATCH_ORIGINS: frozenset[MatchOrigin] = frozenset(
    {MatchOrigin.EXACT_MATERIAL_CODE, MatchOrigin.OLD_MATERIAL_CODE}
)
"""Los únicos orígenes admisibles en ``lookup_material_by_code``.

Invariante de ADR 0021 §6, hecho comprobable por ADR 0025 §9. Es el
cortafuegos contra la caída silenciosa a búsqueda por similitud: hoy, en
Materiales, un código que no coincide literalmente degrada a parecido sobre
la descripción **sin avisar**. Bajo este contrato esa degradación deja de
ser un resultado peor y pasa a ser una violación ruidosa.
"""


class AbsenceReason(StrEnum):
    """Por qué la fuente no devolvió un código. Taxonomía de ADR 0021 §8.2.

    **Un solo valor, y es deliberado.** Es la única causa que Materiales
    puede demostrar hoy sobre un código concreto. Los tres reservados de
    ADR 0021 §8.3 —«no está en esta carga», «está fuera de la cobertura
    declarada» y «no está en SAP»— **no se declaran aquí**: cada uno exige
    un mecanismo que lo demuestre, ninguno existe, y esa tabla es el
    criterio de cierre de M8, que sigue abierto.

    Un enum de un valor parece pobre. Es lo contrario: es la forma honesta
    de decir «sé que no lo devolví y no sé por qué».
    """

    NOT_RETURNED_BY_SOURCE = "not_returned_by_source"
    """La fuente respondió sobre la versión indicada y no devolvió el código."""


class FieldProvenance(StrEnum):
    """De dónde sale un valor. Cinco clases disjuntas.

    Cuatro de ADR 0021 §10, más ``FACTUAL_SAP_AGGREGATED``, que
    ADR 0025 §5 añadió al verificar que ciertos campos se obtienen por
    agregaciones **independientes por campo** sobre el grupo. Cada campo
    pertenece a **exactamente una**.
    """

    FACTUAL_SAP = "factual_sap"
    """Columna de SAP **de una fila concreta**, con su transformación declarada."""

    FACTUAL_SAP_AGGREGATED = "factual_sap_aggregated"
    """Valor factual presente en **alguna** fila del grupo, por una agregación
    declarada. **No es el valor de una fila concreta, y está prohibido
    presentarlo como tal.** Dos campos de esta clase no pueden afirmarse
    juntos como si describieran la misma fila (ADR 0025 §5)."""

    DERIVED_BY_MATERIALES = "derived_by_materiales"
    """Resultado de una regla de negocio de Materiales. **No es dato de SAP.**"""

    MATCH_METADATA = "match_metadata"
    """Cómo se encontró, no qué es. **Nunca factual.**"""

    INVENTORY_METADATA = "inventory_metadata"
    """Describe el snapshot; no se afirma sobre él (ADR 0021 §9 y §7)."""


class NullSense(StrEnum):
    """Qué significa que un campo llegue vacío. Vocabulario cerrado de ADR 0027 §6.

    **``null`` no tiene significado universal en este contrato.** Su
    semántica se define campo por campo, y todo campo nulable pertenece a
    exactamente uno de estos tres sentidos. Dos ``null`` del mismo payload
    pueden significar cosas distintas, y significarlas es correcto
    (ADR 0027 §6.2.3).

    **Esto no es un campo del payload**, y no debe llegar a serlo: mientras
    no exista un caso real que lo exija, el vocabulario es documental y
    normativo (ADR 0027 §12). Vive aquí, junto a :data:`NULL_SENSES`, para
    que la regla de clasificación obligatoria pueda comprobarse por prueba
    en lugar de quedarse en prosa.
    """

    VALOR_FACTUAL_AUSENTE = "valor_factual_ausente"
    """La fuente tiene autoridad sobre el campo, la ejerció, y no hay valor.

    Es el único de los tres que permite afirmar algo negativo, y **solo
    dentro de la frontera de la fuente y de la versión de inventario
    nombrada**. No autoriza ninguna afirmación sobre SAP ni sobre la planta.
    """

    DATO_NO_PROPORCIONADO = "dato_no_proporcionado"
    """El contrato, en esta versión, no transporta el dato.

    Habla del **transporte**, no del hecho. La fuente puede tenerlo o no, y
    el contrato no lo sabe ni lo dice. **No permite afirmar nada sobre el
    hecho.**
    """

    DATO_DESCONOCIDO = "dato_desconocido"
    """El contrato transporta el campo, pero el valor no se pudo determinar,
    o la causa del vacío es **indistinguible**.

    Es el sentido más débil, y el destino por defecto de cualquier
    ambigüedad (ADR 0027 §6.3). Obliga a **nombrar el desconocimiento**:
    prohibido asimilarlo al peor caso conocido, y prohibido asimilarlo a
    ``VALOR_FACTUAL_AUSENTE``.
    """


# ----------------------------------------------------------------------
# Bloques del sobre contractual
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DerivedValue[T]:
    """Un valor calculado por Materiales, con la regla que lo produjo.

    Envoltorio de ADR 0021 §10.2. ELSA **no recalcula** ninguna derivación
    y **no exige sus componentes crudos**: la verificación recae en las
    pruebas contractuales del proveedor, que sí dispone de ellos. Es el
    reparto coherente con la propiedad del dato (regla 4).
    """

    value: T
    rule_reference: str
    """Regla publicada y versionada por Materiales que produjo el valor."""

    rule_verifiable: bool
    """Si una prueba contractual **del proveedor** puede demostrar la regla.

    Es ``False`` mientras la función que aplica la regla no esté versionada
    en el repositorio de Materiales. No es un defecto de este contrato:
    es el estado real de la fuente, declarado en voz alta.
    """


@dataclass(frozen=True, slots=True)
class InventoryVersion:
    """Vigencia del inventario consultado. Bloque ``inventory`` de ADR 0021 §9.1.

    Obligatorio en toda respuesta con ``call_status`` ``OK``, y por eso la
    vigencia deja de ser verificable «a veces»: lo es siempre que la llamada
    tenga éxito (ADR 0021 §11).

    Los cinco campos son ``INVENTORY_METADATA``: **describen** el snapshot,
    no se afirman sobre él. Preguntar si ``loaded_at`` es sensible al
    snapshot es un error de categoría, y por eso ninguno declara
    ``snapshot_sensitive`` (ADR 0027 §9.2).
    """

    version_number: int
    """Número de la versión **activa** sobre la que se respondió. No nulable:
    sin versión activa la llamada no emite ``inventory`` con nulos, responde
    ``NO_ACTIVE_INVENTORY`` (ADR 0027 §13, L1)."""

    loaded_at: datetime
    """**El momento en que terminó la carga en Materiales. Nada más.**

    No es «SAP actualizado al …» ni «extraído de SAP el …» (ADR 0021 §9.2).
    Junto con ``version_number`` significa exactamente «inventario cargado en
    Materiales el …».
    """

    row_count: int
    """Filas de la versión activa. Es un **recuento de carga**, no una medida
    de cobertura: la cobertura vive en :class:`InventoryCoverage` y **nunca se
    deriva de este número**. Un ``row_count`` de 0 con versión activa es un
    hecho, y no autoriza a afirmar que el ámbito esté vacío (ADR 0027 L6)."""

    source_file_label: str | None = None
    """Etiqueta **opaca** de trazabilidad humana. ``null`` es
    ``DATO_DESCONOCIDO``: la carga no registró etiqueta, o la fuente no la
    expone, y el contrato no distingue ambos casos.

    **Nulo o no nulo, no habilita ninguna afirmación.** Extraer de él una
    fecha está prohibido, aunque el nombre siga una convención que la
    contenga (ADR 0021 §9.3, ADR 0027 L2).
    """

    extracted_at: None = None
    """**Siempre nulo en V1**, y es ``DATO_NO_PROPORCIONADO``.

    Significa «este contrato no transporta la fecha de extracción desde
    SAP». **No** significa que SAP carezca de ella: la evidencia solo
    demuestra que el esquema auditado no la registra, que es una afirmación
    sobre Materiales, no sobre SAP.

    Está tipado ``None`` a propósito. Rellenarlo cuando exista un mecanismo
    que lo registre es un cambio **compatible** (ADR 0027 L4), y exige
    cambiar este tipo junto con la versión del contrato — que es
    exactamente la constancia que el campo debe dejar.
    """


@dataclass(frozen=True, slots=True)
class InventoryCoverage:
    """Qué ámbito cubrió la carga. Bloque ``coverage`` de ADR 0021 §7.1.

    ``observed_scope`` significa «el ámbito que Materiales **declara** que
    este snapshot cubrió», y debe provenir de metadata de ingestión que
    Materiales pueda sostener contractualmente. **No** significa «los
    ámbitos para los que casualmente hay filas»: contar los ámbitos
    presentes en los datos responde a otra pregunta, y derivar completitud
    de ella produciría una afirmación de cobertura sin evidencia
    (ADR 0021 §7.2, ADR 0025 §7).

    Mientras esa metadata no exista, el estado es ``UNKNOWN`` y los cuatro
    campos nulables son ``DATO_NO_PROPORCIONADO``: hablan de lo que el
    contrato no transporta, no de lo que el mundo no tiene (ADR 0027 §8).
    **``UNKNOWN`` no se disfraza de completo ni de incompleto.**
    """

    state: InventoryCoverageState
    observed_scope: tuple[str, ...] | None = None
    expected_scope: tuple[str, ...] | None = None
    missing_scope: tuple[str, ...] | None = None
    scope_kind: str | None = None
    """Unidad en la que se mide la cobertura. **Ningún ámbito concreto se
    codifica en ELSA**, ni ahora ni después (ADR 0021 §7.4)."""

    declared_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class StockLocation:
    """Una fila del material en el snapshot. Elemento de ``stock_locations``.

    **Garantía de coherencia, contractual y verificable** (ADR 0025 §8.2):
    todos los atributos de un elemento proceden de la **misma** fila. Es lo
    que lo distingue de los escalares agregados de
    :class:`MaterialFacts`: **estos pueden afirmarse juntos; aquellos, no.**

    ``ubicacion`` es **opaca**: se muestra sin interpretar. ELSA no la
    analiza, no la descompone y **no deriva de ella ningún hecho** — ni
    ámbito, ni cobertura, ni proximidad (ADR 0025 §8.1).
    """

    centro: str
    almacen: str
    ambito: str
    """Clasificación de la ubicación, con vocabulario cerrado publicado por
    Materiales. Es ``DERIVED_BY_MATERIALES``.

    **No es cobertura y está prohibido usarlo como tal** (ADR 0025 §7):
    ``ambito`` no sustituye a ``observed_scope``, no se derivan estados de
    cobertura de los valores presentes en un resultado, y no se concluye la
    ausencia de un ámbito porque no aparezca en las filas devueltas.
    """

    disponible: Decimal
    comprometido: Decimal
    ubicacion: str | None = None
    """``null`` es ``DATO_DESCONOCIDO``: la fila llegó sin ubicación en el
    origen. **No significa** que el material carezca de ubicación física, y
    el blanco **nunca se hereda de otra fila** (ADR 0021 §10.1,
    ADR 0025 §10, ADR 0027 §8)."""


@dataclass(frozen=True, slots=True)
class MaterialFacts:
    """Lo que la fuente devolvió sobre un material.

    Los escalares de descripción llegan por agregaciones **independientes
    por campo**, de modo que el contrato **no garantiza** que procedan de
    una misma fila de origen: son ``FACTUAL_SAP_AGGREGATED`` y **está
    prohibido combinarlos afirmando que describen la misma fila**
    (ADR 0025 §5). Lo que sí puede afirmarse junto es cada elemento de
    :attr:`stock_locations`.
    """

    code: str
    """``FACTUAL_SAP``. El código del material, tal como lo devolvió la fuente."""

    stock_locations: tuple[StockLocation, ...]
    """Una entrada por fila del material en el snapshot consultado."""

    total_disponible: DerivedValue[Decimal]
    total_comprometido: DerivedValue[Decimal]
    """``DERIVED_BY_MATERIALES``: agregaciones sobre las ubicaciones del
    material. **No son campos de SAP**, y presentarlos como dato crudo
    atribuiría a SAP una decisión que tomó Materiales (ADR 0021 §10.2)."""

    dado_de_baja: DerivedValue[bool]
    """Señal de riesgo inferida de la descripción. **No es un estado de SAP.**

    Es **no accionable** (ADR 0025 §4): puede acompañar un hecho como
    advertencia y renderizarse junto al material, pero **no puede ser el
    hecho**, no excluye ni oculta ningún material, no altera orden,
    selección ni puntuación, y no degrada un ``AnswerStatus`` ni emite aviso
    propio. ELSA no puede ser más restrictiva que la fuente.
    """

    descripcion: str | None = None
    unidad: str | None = None
    """``FACTUAL_SAP_AGGREGATED``. ``null`` es ``VALOR_FACTUAL_AUSENTE``: la
    columna llegó vacía en todas las filas del grupo (ADR 0025 §10)."""

    material_antiguo: str | None = None
    """``FACTUAL_SAP_AGGREGATED``. ``null`` es ``DATO_DESCONOCIDO``: no hay
    código antiguo, **o** el valor de origen estaba corrompido y se
    descartó. **Ambos casos son indistinguibles por diseño**, y ELSA tiene
    prohibido resolver la ambigüedad por su cuenta (ADR 0025 §10,
    ADR 0027 §6.3 y §8)."""


@dataclass(frozen=True, slots=True)
class MaterialAbsence:
    """La fuente respondió y no devolvió el código. Forma de ADR 0021 §8.2.

    **Nunca es una inexistencia.** En V1 eso es estructuralmente imposible:
    el único valor disponible lleva ``authoritative`` en falso y **no existe
    ningún valor que signifique inexistencia**.
    """

    reason: AbsenceReason = AbsenceReason.NOT_RETURNED_BY_SOURCE
    basis: str = (
        "La fuente respondió correctamente sobre la versión de inventario "
        "indicada y no devolvió este código."
    )
    authoritative: bool = False
    """Si la fuente **garantiza** que lo que no devuelve no existe.

    **Falso siempre mientras M8 siga abierto.** Activarlo exige un mecanismo
    que lo demuestre, y ninguno de los tres reservados de ADR 0021 §8.3 lo
    tiene. Construir una ausencia autoritativa es un error de contrato, no
    una opción de configuración.
    """

    def __post_init__(self) -> None:
        if self.authoritative:
            raise MaterialsContractViolationError(
                "an authoritative absence cannot exist while M8 remains open (ADR 0021 §8.1, §8.3)"
            )


@dataclass(frozen=True, slots=True)
class MaterialAttribution:
    """Procedencia del hecho. Bloque obligatorio por resultado (ADR 0021 §10.6).

    Materializa ADR 0020 §10: **un hecho sin atribución válida no se emite.**
    Separa además dos fechas que no deben confundirse: :attr:`read_at`
    —cuándo preguntó ELSA— frente a ``loaded_at`` —cuándo terminó la carga
    que produjo el dato—.
    """

    source_version: InventoryVersion
    contract_version: str
    read_at: datetime
    match_origin: MatchOrigin
    capability: str = CONTRACT_CAPABILITY
    source: str = CONTRACT_SOURCE


@dataclass(frozen=True, slots=True)
class MaterialLookupRequest:
    """Lo único que cruza la frontera hacia Materiales. ADR 0021 §3.

    **Dos campos. Nada más**, y la minimización es verificable por prueba
    (ADR 0021 §3.1). Quedan prohibidos en el request: la pregunta del
    usuario, los alcances de ELSA, el activo, el BOM o el renglón de origen,
    el historial de conversación, la evidencia documental, la referencia de
    respuesta y el identificador de usuario en el cuerpo —que ya viaja en el
    JWT, y solo ahí—.

    Materiales no participa en el modelo de autorización de ELSA y no debe
    recibir contexto que no use: enviárselo exportaría ese modelo a un
    sistema que no lo tiene.
    """

    contract_version: str
    material_code: str
    """La **representación de frontera**, que es la regla M3-A: cadena
    decimal exacta, sin agregar ni quitar ceros y sin relleno
    (ADR 0024 §8). No es la forma canónica de comparación interna de ELSA,
    que es otra cosa y no cruza (ADR 0021 §3.2, ADR 0024 §8.1). Aplicarla es
    trabajo del adaptador, nunca del núcleo (ADR 0020 §5)."""


@dataclass(frozen=True, slots=True)
class ContractOperation:
    """Una operación que la fachada declara ofrecer, y por dónde se llega a ella."""

    name: str
    transport_binding: str
    """Nombre de función o ruta. **El contrato no depende de esto**
    (ADR 0021 §2): la fachada declara aquí su enlace, y cambiarlo no cambia
    el contrato. Qué enlace concreto usará sigue sin decidirse."""

    deprecated: bool = False


@dataclass(frozen=True, slots=True)
class ContractDescriptor:
    """Qué versión del contrato habla la fachada, y qué ofrece. ADR 0021 §15.3.

    Se modela aquí **solo su forma**. En M1-A nada lo consulta por red, nada
    lo lee de configuración y nada lo refleja en el estado de salud: ese
    cableado llega con el adaptador real. Lo que la forma permite hoy es
    escribir la regla que importa como prueba en lugar de como prosa:
    **la versión nunca se adivina**. Si el descriptor no responde, la
    versión es desconocida y el servicio se declara degradado, no se asume
    la esperada (regla 9 de ``CLAUDE.md``).
    """

    contract_version: str
    operations: tuple[ContractOperation, ...]
    unsupported_fields: tuple[str, ...] = ()
    """Lo que el contrato **no transporta todavía**, declarado aquí y no
    omitiendo claves del payload (ADR 0025 §10.3).

    Es el segundo de los dos canales que ADR 0027 §11.3 separa: el descriptor
    declara la **capacidad**; un ``null`` clasificado declara el **caso**.
    Ya no compiten.
    """


# ----------------------------------------------------------------------
# Resultados del puerto
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MaterialsLookupResult:
    """Lo que devuelve un lookup. El sobre de tres ejes de ADR 0021 §4.

    **No se usa un enum plano**, porque obligaría a elegir entre verdades
    simultáneas: un material puede encontrarse y la cobertura seguir siendo
    incompleta. Los tres ejes son independientes:

    ===================  ===========  =========================================
    Eje                  Alcance      Pregunta que responde
    ===================  ===========  =========================================
    :attr:`call_status`  la llamada   ¿Pudo la fuente responder?
    :attr:`outcome`      el código    ¿Devolvió este código?
    ``coverage.state``   el snapshot  ¿Sé qué ámbito cubre lo que consulté?
    ===================  ===========  =========================================

    **Los cuatro desenlaces normales son valores, no excepciones**
    (ADR 0021 §14): hecho factual, código no devuelto, sin inventario activo
    y capacidad no disponible. Modelar una ausencia legítima como excepción
    convertiría una respuesta correcta en un fallo.

    **No existe aquí ninguna lectura en la que un vacío signifique «el
    material no existe».** Un :attr:`material` ausente nunca viaja solo:
    va siempre acompañado de un :attr:`outcome` ``NOT_RETURNED`` y de una
    :class:`MaterialAbsence` que dice, con todas sus letras, que la fuente
    respondió y no lo devolvió — que es un hecho sobre la fuente, no sobre
    el mundo.
    """

    call_status: CapabilityCallStatus
    contract_version: str | None = None
    """``null`` es ``DATO_NO_PROPORCIONADO``: la llamada no llegó a producir
    un sobre del contrato. **Nunca se sustituye por la versión esperada**
    (ADR 0021 §15.3)."""

    inventory: InventoryVersion | None = None
    """``null`` es ``DATO_NO_PROPORCIONADO``: no hubo versión activa sobre la
    que responder, o la llamada no llegó a ejecutarse. **No es un
    ``inventory`` con campos nulos**, que sería un defecto de contrato
    (ADR 0027 L1)."""

    coverage: InventoryCoverage | None = None
    """``null`` es ``DATO_NO_PROPORCIONADO``, por el mismo motivo."""

    requested_code: str | None = None
    """Eco literal de lo enviado (ADR 0021 §4)."""

    outcome: CapabilityOutcome | None = None
    """``null`` es ``DATO_NO_PROPORCIONADO``: sin llamada correcta no hay
    desenlace por código que declarar."""

    material: MaterialFacts | None = None
    """``null`` es ``VALOR_FACTUAL_AUSENTE`` **acotado a la fuente y a la
    versión**, nunca a la realidad: se acompaña siempre de :attr:`absence`."""

    absence: MaterialAbsence | None = None
    """``null`` es ``DATO_NO_PROPORCIONADO``: no hubo ausencia que tipar."""

    attribution: MaterialAttribution | None = None
    """``null`` es ``DATO_NO_PROPORCIONADO``. **Un hecho sin atribución
    válida no se emite** (ADR 0020 §10), de modo que un :attr:`material`
    presente obliga a que este no lo esté."""

    def __post_init__(self) -> None:
        if self.call_status is not CapabilityCallStatus.OK:
            self._reject_payload_without_a_successful_call()
            return

        if self.outcome is None:
            raise MaterialsContractViolationError("a successful call must carry an outcome")
        if self.inventory is None:
            raise MaterialsContractViolationError(
                "a successful call answers over an active inventory version (ADR 0021 §9)"
            )
        if self.coverage is None:
            raise MaterialsContractViolationError(
                "coverage is mandatory in every successful response (ADR 0021 §7)"
            )

        if self.outcome is CapabilityOutcome.MATCHED:
            self._check_matched()
        else:
            self._check_not_returned()

    def _reject_payload_without_a_successful_call(self) -> None:
        """Sin llamada correcta no hay nada que afirmar, y eso incluye la ausencia.

        ``NO_ACTIVE_INVENTORY`` **no es una ausencia**: no hubo fuente válida
        sobre la cual ejecutar la consulta. Dejarle adjuntar un
        :class:`MaterialAbsence` volvería a confundir «no se pudo mirar» con
        «se miró y no estaba», que es el error que este contrato existe para
        impedir (ADR 0021 §5, §13.1).
        """
        forbidden = {
            "outcome": self.outcome,
            "material": self.material,
            "absence": self.absence,
            "attribution": self.attribution,
            "inventory": self.inventory,
            "coverage": self.coverage,
        }
        carried = sorted(name for name, value in forbidden.items() if value is not None)
        if carried:
            raise MaterialsContractViolationError(
                f"a {self.call_status.value} call carries no payload, but got: {', '.join(carried)}"
            )

    def _check_matched(self) -> None:
        if self.material is None:
            raise MaterialsContractViolationError("a matched outcome must carry the material")
        if self.absence is not None:
            raise MaterialsContractViolationError("a matched outcome cannot carry an absence")
        if self.attribution is None:
            raise MaterialsContractViolationError(
                "a fact without valid attribution is not emitted (ADR 0020 §10)"
            )
        if self.attribution.match_origin not in EXACT_LOOKUP_MATCH_ORIGINS:
            raise MaterialsContractViolationError(
                f"{self.attribution.match_origin.value!r} is not admissible in an exact lookup: "
                "the invariant of ADR 0021 §6 allows only a match by code, exact or old. "
                "This is a contract violation, not a lower-quality result"
            )

    def _check_not_returned(self) -> None:
        if self.material is not None:
            raise MaterialsContractViolationError("a not-returned outcome cannot carry a material")
        if self.absence is None:
            raise MaterialsContractViolationError(
                "an absence is typed, never zero mute rows (ADR 0021 §8.2)"
            )

    def as_capability_result(self) -> InventoryLookupResult:
        """Entrega este resultado a la política de respuesta del núcleo.

        El puerto transporta el contrato; **no decide qué se responde**. Esa
        decisión es de :func:`elsa.core.capability_outcomes.interpret_inventory_lookup`,
        que no sabe —ni debe saber— de dónde vino el resultado.

        Es también la razón por la que aquí no se duplica ningún vocabulario:
        los valores viajan tal cual, sin traducción, porque son los mismos.
        """
        return InventoryLookupResult(
            call_status=self.call_status,
            outcome=self.outcome,
            absence_is_authoritative=(
                self.absence.authoritative if self.absence is not None else False
            ),
        )


@dataclass(frozen=True, slots=True)
class InventoryStatusResult:
    """Vigencia y cobertura, sin consultar material alguno. ADR 0021 §2.

    Responde «¿sobre qué estoy consultando?» antes de preguntar por nada
    concreto. Es obligatoria en V1 porque es lo que permite declarar el
    servicio degradado sin fabricar una consulta de material para
    averiguarlo.
    """

    call_status: CapabilityCallStatus
    contract_version: str | None = None
    inventory: InventoryVersion | None = None
    coverage: InventoryCoverage | None = None

    def __post_init__(self) -> None:
        if self.call_status is CapabilityCallStatus.OK:
            if self.inventory is None:
                raise MaterialsContractViolationError(
                    "a successful status answers over an active inventory version"
                )
            if self.coverage is None:
                raise MaterialsContractViolationError(
                    "coverage is mandatory in every successful response (ADR 0021 §7)"
                )
        elif self.inventory is not None or self.coverage is not None:
            raise MaterialsContractViolationError(
                f"a {self.call_status.value} status carries no inventory metadata"
            )


# ----------------------------------------------------------------------
# Clasificación obligatoria de los campos nulables
# ----------------------------------------------------------------------

NULL_SENSES: Mapping[str, NullSense] = {
    "InventoryVersion.source_file_label": NullSense.DATO_DESCONOCIDO,
    "InventoryVersion.extracted_at": NullSense.DATO_NO_PROPORCIONADO,
    "InventoryCoverage.observed_scope": NullSense.DATO_NO_PROPORCIONADO,
    "InventoryCoverage.expected_scope": NullSense.DATO_NO_PROPORCIONADO,
    "InventoryCoverage.missing_scope": NullSense.DATO_NO_PROPORCIONADO,
    "InventoryCoverage.scope_kind": NullSense.DATO_NO_PROPORCIONADO,
    "InventoryCoverage.declared_at": NullSense.DATO_NO_PROPORCIONADO,
    "StockLocation.ubicacion": NullSense.DATO_DESCONOCIDO,
    "MaterialFacts.descripcion": NullSense.VALOR_FACTUAL_AUSENTE,
    "MaterialFacts.unidad": NullSense.VALOR_FACTUAL_AUSENTE,
    "MaterialFacts.material_antiguo": NullSense.DATO_DESCONOCIDO,
    "MaterialsLookupResult.contract_version": NullSense.DATO_NO_PROPORCIONADO,
    "MaterialsLookupResult.inventory": NullSense.DATO_NO_PROPORCIONADO,
    "MaterialsLookupResult.coverage": NullSense.DATO_NO_PROPORCIONADO,
    "MaterialsLookupResult.requested_code": NullSense.DATO_NO_PROPORCIONADO,
    "MaterialsLookupResult.outcome": NullSense.DATO_NO_PROPORCIONADO,
    "MaterialsLookupResult.material": NullSense.VALOR_FACTUAL_AUSENTE,
    "MaterialsLookupResult.absence": NullSense.DATO_NO_PROPORCIONADO,
    "MaterialsLookupResult.attribution": NullSense.DATO_NO_PROPORCIONADO,
    "InventoryStatusResult.contract_version": NullSense.DATO_NO_PROPORCIONADO,
    "InventoryStatusResult.inventory": NullSense.DATO_NO_PROPORCIONADO,
    "InventoryStatusResult.coverage": NullSense.DATO_NO_PROPORCIONADO,
}
"""Sentido de cada campo nulable del contrato. Regla de ADR 0027 §6.2.

**Un campo nulable sin clasificación es un defecto de contrato**, no un
campo permisivo: ELSA lo trataría como ``DATO_DESCONOCIDO``, registraría la
anomalía y no inferiría nada de él (ADR 0027 §6.2.2). Esta tabla existe para
que esa regla se compruebe por prueba y no se quede en prosa, y para que
añadir un campo nulable sin declarar su sentido rompa la suite.

**Cambiar la clasificación de un campo sin cambiar su nombre es
incompatible** (ADR 0027 §6.2.4): es un cambio de significado invisible en
un diff, que ADR 0021 §15.1 marca como el más peligroso de todos.

La tabla **no se deriva** de los tipos: que un campo sea ``X | None`` dice
que puede llegar vacío, no qué significa que llegue vacío. Esa es
justamente la distinción que ADR 0027 existe para sostener.
"""


def _nullable_fields(*types: type) -> frozenset[str]:
    """Campos declarados como opcionales en los tipos del contrato."""
    names: set[str] = set()
    for tipo in types:
        for field in fields(tipo):
            annotation = field.type if isinstance(field.type, str) else str(field.type)
            if "None" in annotation:
                names.add(f"{tipo.__name__}.{field.name}")
    return frozenset(names)


# ----------------------------------------------------------------------
# El puerto
# ----------------------------------------------------------------------


@runtime_checkable
class MaterialsPort(Protocol):
    """Consulta del inventario de Materiales, sin duplicarlo en ELSA.

    Tres operaciones. **Falta una a propósito:** la búsqueda por texto libre
    está declarada en el contrato pero **fuera del Piloto 0.1 inicial**
    (ADR 0021 §2, §22 fila 12), y no se construye por anticipación
    (regla 23).

    Que la ausencia de esa operación sea visible es parte del diseño.
    Identificación autoritativa y sugerencia asistida **no se fusionan**:
    ``lookup_material_by_code`` responde «¿qué es este código?» y su
    respuesta es un hecho atribuible; una búsqueda por texto respondería
    «¿qué se parece a este texto?», y su respuesta sería un conjunto de
    hipótesis que **nunca puede promoverse a hecho de identificación**.

    La identidad del usuario vive en otro puerto,
    :class:`elsa.ports.materials_identity.MaterialsIdentityPort`, y no se
    mezcla con esto: son dos superficies del mismo sistema externo, no dos
    abstracciones de la misma cosa.
    """

    async def lookup_material_by_code(
        self, request: MaterialLookupRequest
    ) -> MaterialsLookupResult:
        """Identificación autoritativa: coincidencia exacta por código, o nada.

        **No admite ningún parámetro ni modo que active similitud.** No es
        una opción desactivada por defecto: no existe. Y el lookup exacto
        **no puede degradarse a búsqueda textual**, ni por configuración, ni
        por ausencia de resultados, ni por decisión del adaptador
        (ADR 0021 §2).

        Los cuatro desenlaces normales llegan como
        :class:`MaterialsLookupResult`, nunca como excepción. Se lanza
        :class:`MaterialsContractViolationError` solo si la respuesta viola
        el contrato.
        """
        ...

    async def get_inventory_status(self) -> InventoryStatusResult:
        """Vigencia y cobertura del inventario, sin consultar material alguno."""
        ...

    async def get_contract_descriptor(self) -> ContractDescriptor:
        """Versión del contrato y operaciones que la fachada declara ofrecer.

        **La versión nunca se adivina** (ADR 0021 §15.3): si el descriptor no
        responde, la versión es desconocida y el servicio se declara
        degradado, no se asume la esperada.
        """
        ...
