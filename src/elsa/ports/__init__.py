"""Puertos de ELSA: interfaces (``Protocol``) de toda dependencia externa.

La lógica de negocio importa estos puertos, nunca un adaptador concreto.
El adaptador real se selecciona por configuración (ver CLAUDE.md, sección 5).
"""

from elsa.ports.auth import AuthenticatedUser, AuthPort, InvalidTokenError
from elsa.ports.embeddings import EmbeddingsPort
from elsa.ports.llm import ChatMessage, ChatResult, LLMPort, LLMUnavailableError
from elsa.ports.materials import Material, MaterialsPort, MaterialsUnavailableError
from elsa.ports.ocr import OCRPage, OCRPort, OCRResult, UnsupportedDocumentError
from elsa.ports.reranker import RankedDocument, RerankerPort

__all__ = [
    "AuthPort",
    "AuthenticatedUser",
    "ChatMessage",
    "ChatResult",
    "EmbeddingsPort",
    "InvalidTokenError",
    "LLMPort",
    "LLMUnavailableError",
    "Material",
    "MaterialsPort",
    "MaterialsUnavailableError",
    "OCRPage",
    "OCRPort",
    "OCRResult",
    "RankedDocument",
    "RerankerPort",
    "UnsupportedDocumentError",
]
