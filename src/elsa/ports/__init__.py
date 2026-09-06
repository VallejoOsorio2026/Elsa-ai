"""Puertos de ELSA: interfaces (``Protocol``) de toda dependencia externa.

La lógica de negocio importa estos puertos, nunca un adaptador concreto.
El adaptador real se selecciona por configuración (ver CLAUDE.md, sección 5).
"""

from elsa.ports.abuse import AbuseGuardPort, AbusePolicy, LimitKind, LimitVerdict
from elsa.ports.auth import (
    AuthenticatedUser,
    AuthPort,
    IdentityProviderUnavailableError,
    InvalidTokenError,
)
from elsa.ports.embeddings import EmbeddingsPort
from elsa.ports.llm import ChatMessage, ChatResult, LLMPort, LLMUnavailableError
from elsa.ports.materials import Material, MaterialsPort, MaterialsUnavailableError
from elsa.ports.materials_identity import MaterialsIdentityPort, MaterialsProfile
from elsa.ports.ocr import OCRPage, OCRPort, OCRResult, UnsupportedDocumentError
from elsa.ports.permissions import (
    AccountNotFoundError,
    AdminOperation,
    AuditEntry,
    BootstrapAlreadyCompletedError,
    ElsaAccount,
    PermissionGrant,
    PermissionsRepositoryPort,
    PermissionsUnavailableError,
    UnknownDomainError,
)
from elsa.ports.reranker import RankedDocument, RerankerPort

__all__ = [
    "AbuseGuardPort",
    "AbusePolicy",
    "AccountNotFoundError",
    "AdminOperation",
    "AuditEntry",
    "AuthPort",
    "AuthenticatedUser",
    "BootstrapAlreadyCompletedError",
    "ChatMessage",
    "ChatResult",
    "ElsaAccount",
    "EmbeddingsPort",
    "IdentityProviderUnavailableError",
    "InvalidTokenError",
    "LLMPort",
    "LLMUnavailableError",
    "LimitKind",
    "LimitVerdict",
    "Material",
    "MaterialsIdentityPort",
    "MaterialsPort",
    "MaterialsProfile",
    "MaterialsUnavailableError",
    "OCRPage",
    "OCRPort",
    "OCRResult",
    "PermissionGrant",
    "PermissionsRepositoryPort",
    "PermissionsUnavailableError",
    "RankedDocument",
    "RerankerPort",
    "UnknownDomainError",
    "UnsupportedDocumentError",
]
