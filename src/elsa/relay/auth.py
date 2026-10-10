"""Autenticación del nodo PC1 ante el relay (ADR 0031).

Es **independiente** del JWT del usuario. El nodo presenta un secreto de alta
entropía en la cabecera ``X-Elsa-Node-Token``; Render conserva únicamente su
SHA-256 (el actual y, durante una rotación, el anterior). El secreto crudo no
se retiene, no se registra y no aparece en ninguna respuesta.

Los hashes de 256 bits sobre un secreto aleatorio de alta entropía no necesitan
un KDF lento: no hay diccionario que recorrer. La comparación es de tiempo
constante y no distingue cuál de los dos hashes coincidió.
"""

from __future__ import annotations

import hashlib
import hmac

NODE_TOKEN_HEADER = "X-Elsa-Node-Token"
"""Cabecera HTTPS que transporta la credencial del nodo. Nunca query, body ni cookie."""


def hash_node_token(token: str) -> str:
    """SHA-256 hexadecimal en minúscula del secreto del nodo.

    Lo usan el verificador y los tests; el operador lo usará para derivar el
    valor que se configura en Render sin que el secreto salga de PC1.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class NodeCredentialVerifier:
    """Verifica la credencial y la identidad configurada del único nodo."""

    def __init__(
        self,
        node_id: str,
        current_sha256: str,
        previous_sha256: str | None = None,
    ) -> None:
        self._node_id = node_id
        self._accepted: tuple[bytes, ...] = tuple(
            value.encode("ascii") for value in (current_sha256, previous_sha256) if value
        )

    @property
    def node_id(self) -> str:
        return self._node_id

    def verify_token(self, token: str | None) -> bool:
        """``True`` si el token corresponde al hash actual o al anterior."""
        if not token:
            return False
        digest = hash_node_token(token).encode("ascii")
        # Sin cortocircuito: se recorren todos los hashes aceptados.
        matched = False
        for accepted in self._accepted:
            matched |= hmac.compare_digest(digest, accepted)
        return matched

    def node_id_matches(self, node_id: str) -> bool:
        """El ``node_id`` del mensaje debe ser exactamente el configurado."""
        return hmac.compare_digest(node_id.encode("utf-8"), self._node_id.encode("utf-8"))
