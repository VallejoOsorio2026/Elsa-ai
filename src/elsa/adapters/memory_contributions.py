"""Almacén de aportes en memoria.

Es el único adaptador del puerto en el Bloque 3, y basta para el piloto: los
aportes de una demostración no deben sobrevivir a la demostración. Cuando el
flujo se dé por bueno, el adaptador de PostgreSQL llegará con su migración
versionada, igual que el resto del esquema (ADR 0001).

Se serializa con un lock, como el resto de adaptadores en memoria del
proyecto: dos revisores decidiendo a la vez sobre el mismo aporte no pueden
dejarlo en un estado intermedio.
"""

import asyncio
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime

from elsa.core.authorization import normalize_scope_value
from elsa.core.contributions import ContributionRuleError, validate_transition
from elsa.ports.contributions import (
    ChecklistAnswer,
    ContributionAttachment,
    ContributionAudio,
    ContributionNotFoundError,
    ContributionRecord,
    ContributionState,
    Normalization,
)


def _scope(domain: str, asset_code: str) -> tuple[str, str]:
    return normalize_scope_value(domain), normalize_scope_value(asset_code)


class InMemoryContributionsRepository:
    """Aportes y capacidad de aportar, en memoria y no persistentes."""

    def __init__(self) -> None:
        self._records: dict[str, ContributionRecord] = {}
        self._contributors: set[tuple[str, str, str]] = set()
        self._lock = asyncio.Lock()

    # -- Lectura -------------------------------------------------------

    async def get(self, contribution_id: str) -> ContributionRecord | None:
        return self._records.get(contribution_id)

    async def list_by_author(
        self, author_id: str, *, domain: str, asset_code: str
    ) -> tuple[ContributionRecord, ...]:
        scope = _scope(domain, asset_code)
        return self._sorted(
            record
            for record in self._records.values()
            if record.author_id == author_id and (record.domain, record.asset_code) == scope
        )

    async def list_by_state(
        self, *, domain: str, asset_code: str, state: ContributionState
    ) -> tuple[ContributionRecord, ...]:
        scope = _scope(domain, asset_code)
        return self._sorted(
            record
            for record in self._records.values()
            if record.state is state and (record.domain, record.asset_code) == scope
        )

    @staticmethod
    def _sorted(records: object) -> tuple[ContributionRecord, ...]:
        return tuple(sorted(records, key=lambda item: item.created_at, reverse=True))  # type: ignore[call-overload]

    # -- Escritura -----------------------------------------------------

    async def create(
        self,
        *,
        domain: str,
        asset_code: str,
        author_id: str,
        author_name: str | None,
        title: str,
        transcript_text: str,
        transcript_is_simulated: bool,
        transcript_engine: str | None,
        audio: ContributionAudio | None,
        attachments: Sequence[ContributionAttachment] = (),
        normalizations: Sequence[Normalization] = (),
        checklist: Sequence[ChecklistAnswer] = (),
    ) -> ContributionRecord:
        scope_domain, scope_asset = _scope(domain, asset_code)
        record = ContributionRecord(
            id=str(uuid.uuid4()),
            domain=scope_domain,
            asset_code=scope_asset,
            author_id=author_id,
            author_name=author_name,
            title=title,
            state=ContributionState.DRAFT,
            created_at=datetime.now(tz=UTC),
            transcript_text=transcript_text,
            transcript_is_simulated=transcript_is_simulated,
            transcript_engine=transcript_engine,
            audio=audio,
            attachments=tuple(attachments),
            normalizations=tuple(normalizations),
            checklist=tuple(checklist),
        )
        async with self._lock:
            self._records[record.id] = record
        return record

    async def update_draft(
        self,
        contribution_id: str,
        *,
        title: str | None = None,
        transcript_text: str | None = None,
        transcript_edited: bool | None = None,
        normalizations: Sequence[Normalization] | None = None,
        checklist: Sequence[ChecklistAnswer] | None = None,
    ) -> ContributionRecord:
        async with self._lock:
            current = self._require(contribution_id)
            if current.state is not ContributionState.DRAFT:
                # Un aporte enviado es un hecho registrado: si se pudiera
                # reescribir, el revisor no sabría qué está aprobando.
                raise ContributionRuleError("only a draft contribution can be edited")
            updated = _replace(
                current,
                title=current.title if title is None else title,
                transcript_text=(
                    current.transcript_text if transcript_text is None else transcript_text
                ),
                transcript_edited=(
                    current.transcript_edited if transcript_edited is None else transcript_edited
                ),
                normalizations=(
                    current.normalizations if normalizations is None else tuple(normalizations)
                ),
                checklist=current.checklist if checklist is None else tuple(checklist),
            )
            self._records[contribution_id] = updated
            return updated

    async def submit(self, contribution_id: str) -> ContributionRecord:
        async with self._lock:
            current = self._require(contribution_id)
            validate_transition(current.state, ContributionState.PENDING)
            updated = _replace(
                current,
                state=ContributionState.PENDING,
                submitted_at=datetime.now(tz=UTC),
            )
            self._records[contribution_id] = updated
            return updated

    async def decide(
        self,
        contribution_id: str,
        *,
        state: ContributionState,
        actor: str,
        reason: str | None = None,
    ) -> ContributionRecord:
        async with self._lock:
            current = self._require(contribution_id)
            validate_transition(current.state, state)
            updated = _replace(
                current,
                state=state,
                decided_at=datetime.now(tz=UTC),
                decided_by=actor,
                decision_reason=reason,
            )
            self._records[contribution_id] = updated
            return updated

    # -- Capacidad de aportar ------------------------------------------

    async def is_contributor(self, user_id: str, *, domain: str, asset_code: str) -> bool:
        scope_domain, scope_asset = _scope(domain, asset_code)
        return (user_id, scope_domain, scope_asset) in self._contributors

    async def set_contributor(
        self, user_id: str, *, domain: str, asset_code: str, enabled: bool
    ) -> None:
        scope_domain, scope_asset = _scope(domain, asset_code)
        entry = (user_id, scope_domain, scope_asset)
        async with self._lock:
            if enabled:
                self._contributors.add(entry)
            else:
                self._contributors.discard(entry)

    async def check_health(self) -> None:
        return None

    # -- Interno -------------------------------------------------------

    def _require(self, contribution_id: str) -> ContributionRecord:
        record = self._records.get(contribution_id)
        if record is None:
            raise ContributionNotFoundError(contribution_id)
        return record


def _replace(record: ContributionRecord, **changes: object) -> ContributionRecord:
    """Copia del registro con los campos indicados cambiados."""
    return replace(record, **changes)  # type: ignore[arg-type]
