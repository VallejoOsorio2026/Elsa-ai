"""Contexto de sesión para la interfaz web.

Un único endpoint **sin autenticar** que responde lo que el navegador
necesita saber *antes* de tener identidad: en qué ambiente está, cómo se
inicia sesión aquí y qué límites aplica el servidor.

Los límites se publican para que la interfaz pueda avisar antes de que el
usuario pierda trabajo, no para que los aplique: quien los hace cumplir es
el backend, en cada petición. Un cliente modificado que ignore lo que dice
este endpoint choca igual contra la validación del servidor.

**Identidades de demostración.** En DEV con el proveedor de identidad
``fake``, este endpoint devuelve los tokens deterministas del adaptador
fake para que la pantalla de acceso pueda ofrecerlos. No es una fuga: esos
tokens están escritos en el código, solo valen contra el adaptador fake y la
configuración prohíbe ese adaptador fuera de DEV. En cualquier otro
ambiente la lista viene vacía y la identidad la emite Materiales.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from elsa.adapters.fake_auth import ADMIN_ID, ENGINEER_ID, OTHER_REVIEWER_ID, REVIEWER_ID
from elsa.api.deps import get_settings
from elsa.config import AuthProvider, Environment, Settings

router = APIRouter(prefix="/session", tags=["session"])


class DemoIdentity(BaseModel):
    """Una identidad de demostración ofrecida por la pantalla de acceso."""

    token: str
    label: str
    role: str
    description: str


class SessionLimits(BaseModel):
    """Límites que el servidor aplica. La interfaz los muestra, no los decide."""

    max_attachments: int
    max_attachment_bytes: int
    max_audio_seconds: int


class SessionContext(BaseModel):
    """Lo que el navegador puede saber sin haberse identificado."""

    environment: str
    auth_provider: str
    demo_mode: bool = Field(
        description="Cierto si el ambiente usa identidades y datos sintéticos.",
    )
    demo_identities: list[DemoIdentity] = Field(default_factory=list)
    limits: SessionLimits


_DEMO_IDENTITIES: tuple[DemoIdentity, ...] = (
    DemoIdentity(
        token="fake-token-engineer",
        label="Ingeniero de mantenimiento",
        role="engineer",
        description="Consulta el equipo y aporta conocimiento. No valida lo que otros aportan.",
    ),
    DemoIdentity(
        token="fake-token-reviewer",
        label="Revisora técnica",
        role="reviewer",
        description="Consulta, aporta y además valida los aportes pendientes.",
    ),
    DemoIdentity(
        token="fake-token-other-reviewer",
        label="Segundo revisor",
        role="reviewer",
        description="Mismo alcance que la revisora: sirve para ver decisiones cruzadas.",
    ),
    DemoIdentity(
        token="fake-token-admin",
        label="Administradora",
        role="admin",
        description="Alcance completo del dominio y capacidad de administración.",
    ),
)

# Identificadores expuestos solo para que los tests puedan comprobar que la
# lista de demostración coincide con las cuentas que siembra `elsa.demo`.
DEMO_USER_IDS = (ENGINEER_ID, REVIEWER_ID, OTHER_REVIEWER_ID, ADMIN_ID)


@router.get("/context", response_model=SessionContext)
async def session_context(settings: Settings = Depends(get_settings)) -> SessionContext:
    """Ambiente, forma de acceso y límites vigentes."""
    is_demo = settings.env is Environment.DEV and settings.auth_provider is AuthProvider.FAKE
    return SessionContext(
        environment=settings.env.value,
        auth_provider=settings.auth_provider.value,
        demo_mode=is_demo,
        demo_identities=list(_DEMO_IDENTITIES) if is_demo else [],
        limits=SessionLimits(
            max_attachments=settings.contribution_max_attachments,
            max_attachment_bytes=settings.contribution_max_attachment_bytes,
            max_audio_seconds=settings.contribution_max_audio_seconds,
        ),
    )
