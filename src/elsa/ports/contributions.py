"""Puerto de aportes de conocimiento.

Un **aporte** es lo que una persona de planta envía para que pase a formar
parte del conocimiento del equipo: una nota de voz, lo que dijo en ella y,
opcionalmente, archivos de apoyo.

La regla que gobierna todo el módulo: **un aporte pendiente no es
conocimiento.** Nada de lo que hay aquí aparece en la consulta del Bloque 2
hasta que un Revisor Técnico lo aprueba, y ni siquiera entonces se publica
solo. Esa separación es la misma que ya aplica el BOM de Ingeniería: lo que
no ha validado nadie no se le enseña a quien va a intervenir un equipo.

La **capacidad de aportar** vive en este puerto y no en el de permisos, por
dos razones. Es un concepto nuevo del Bloque 3, y añadirlo al modelo de
autorización obligaría a una migración del esquema para algo que el piloto
todavía guarda en memoria. Consultar es una capacidad; aportar es otra;
revisar es una tercera. Ninguna implica a las demás.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

__all__ = [
    "ChecklistAnswer",
    "ContributionAttachment",
    "ContributionAudio",
    "ContributionNotFoundError",
    "ContributionRecord",
    "ContributionState",
    "ContributionsRepositoryPort",
    "ContributionsUnavailableError",
    "Normalization",
]


class ContributionsUnavailableError(Exception):
    """El almacén de aportes no está disponible."""


class ContributionNotFoundError(Exception):
    """El aporte no existe, o no es visible para quien pregunta."""


class ContributionState(StrEnum):
    """Ciclo de vida de un aporte.

    ``PENDING`` es el estado en el que vive casi todo: enviado, visible para
    revisión, y **sin efecto alguno** sobre el conocimiento publicado.
    """

    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ContributionAudio:
    """La nota de voz. Los bytes viven en el almacén privado de artefactos."""

    storage_key: str
    byte_size: int
    duration_seconds: float
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class ContributionAttachment:
    """Un archivo de apoyo del aporte."""

    id: str
    filename: str
    byte_size: int
    storage_key: str
    content_type: str | None = None


@dataclass(frozen=True, slots=True)
class Normalization:
    """Un dato que las reglas extrajeron del texto y la persona puede corregir.

    ``detected`` es lo que encontró la extracción; ``value`` es lo que la
    persona dejó. Se guardan los dos: poder demostrar qué propuso el sistema
    y qué corrigió el humano es lo que hace auditable la revisión.
    """

    key: str
    label: str
    detected: str | None
    value: str | None
    kind: str = "text"
    matched_in_bom: bool = False
    """Cierto si el valor coincide con algo del BOM publicado del equipo."""

    @property
    def edited(self) -> bool:
        return (self.value or "") != (self.detected or "")


@dataclass(frozen=True, slots=True)
class ChecklistAnswer:
    """Una respuesta de la guía que acompaña al aporte."""

    key: str
    question: str
    answer: str | None = None
    checked: bool = False


@dataclass(frozen=True, slots=True)
class ContributionRecord:
    """Un aporte completo, tal como se guarda."""

    id: str
    domain: str
    asset_code: str
    author_id: str
    author_name: str | None
    title: str
    state: ContributionState
    created_at: datetime

    title_is_generated: bool = False
    """Si el título lo compuso ELSA a partir del propio aporte.

    Existe para no pisar nunca lo que escribió una persona: un título
    generado se recompone cuando llega mejor información, y uno escrito a
    mano se respeta tal cual.
    """

    transcript_text: str = ""
    transcript_is_simulated: bool = True
    transcript_engine: str | None = None
    """Bandera y motor de la transcripción. Viajan con el aporte hasta la
    revisión: quien aprueba tiene que saber si el texto se reconoció o se
    escribió a mano."""

    transcript_edited: bool = False
    """Cierto si la persona cambió el texto que le propuso el motor."""

    audio: ContributionAudio | None = None
    attachments: tuple[ContributionAttachment, ...] = ()
    normalizations: tuple[Normalization, ...] = ()
    checklist: tuple[ChecklistAnswer, ...] = ()

    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None
    decided_by_name: str | None = None
    """Nombre visible de quien decidió.

    Se guarda junto al identificador porque la pantalla de revisión tiene que
    poder decir quién validó algo sin enseñar un UUID, y porque revertir una
    decisión exige saber de quién era.
    """

    decision_reason: str | None = None

    @property
    def is_published_knowledge(self) -> bool:
        """Nunca. Un aporte aprobado espera publicación, no la sustituye.

        Existe como propiedad explícita para que ninguna capa superior tenga
        que deducirlo, y para que el día que eso cambie el cambio sea
        visible en un solo sitio.
        """
        return False


@runtime_checkable
class ContributionsRepositoryPort(Protocol):
    """Almacén de aportes y de la capacidad de aportar."""

    async def create(
        self,
        *,
        domain: str,
        asset_code: str,
        author_id: str,
        author_name: str | None,
        title: str,
        title_is_generated: bool = False,
        transcript_text: str,
        transcript_is_simulated: bool,
        transcript_engine: str | None,
        audio: ContributionAudio | None,
        attachments: Sequence[ContributionAttachment] = (),
        normalizations: Sequence[Normalization] = (),
        checklist: Sequence[ChecklistAnswer] = (),
    ) -> ContributionRecord:
        """Crea un aporte en estado ``DRAFT``."""
        ...

    async def get(self, contribution_id: str) -> ContributionRecord | None: ...

    async def list_by_author(
        self, author_id: str, *, domain: str, asset_code: str
    ) -> tuple[ContributionRecord, ...]:
        """Aportes de una persona, del más reciente al más antiguo."""
        ...

    async def list_by_state(
        self, *, domain: str, asset_code: str, state: ContributionState
    ) -> tuple[ContributionRecord, ...]: ...

    async def update_draft(
        self,
        contribution_id: str,
        *,
        title: str | None = None,
        title_is_generated: bool | None = None,
        transcript_text: str | None = None,
        transcript_edited: bool | None = None,
        normalizations: Sequence[Normalization] | None = None,
        checklist: Sequence[ChecklistAnswer] | None = None,
    ) -> ContributionRecord:
        """Modifica un borrador. Un aporte ya enviado no se puede editar."""
        ...

    async def submit(self, contribution_id: str) -> ContributionRecord:
        """Pasa el borrador a ``PENDING``."""
        ...

    async def decide(
        self,
        contribution_id: str,
        *,
        state: ContributionState,
        actor: str,
        actor_name: str | None = None,
        reason: str | None = None,
    ) -> ContributionRecord:
        """Aprueba o rechaza un aporte pendiente."""
        ...

    async def is_contributor(self, user_id: str, *, domain: str, asset_code: str) -> bool:
        """Si esa persona está habilitada para aportar en ese alcance."""
        ...

    async def set_contributor(
        self, user_id: str, *, domain: str, asset_code: str, enabled: bool
    ) -> None: ...

    async def check_health(self) -> None:
        """Lanza :class:`ContributionsUnavailableError` si no responde."""
        ...
