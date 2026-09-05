"""Claves de firma generadas al vuelo para los tests.

No hay ninguna clave, secreto ni token real en el repositorio: cada corrida
genera su propio par y publica solo la parte pública en un JWKS de prueba.
"""

from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm


class KeyPair:
    """Par de claves de prueba, con su JWK público."""

    def __init__(self, key_id: str, algorithm: str = "RS256") -> None:
        self.key_id = key_id
        self.algorithm = algorithm
        if algorithm.startswith("ES"):
            self.private: Any = ec.generate_private_key(ec.SECP256R1())
            jwk = ECAlgorithm.to_jwk(self.private.public_key(), as_dict=True)
        else:
            self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            jwk = RSAAlgorithm.to_jwk(self.private.public_key(), as_dict=True)
        self.jwk = {**jwk, "kid": key_id, "alg": algorithm, "use": "sig"}

    def sign(self, claims: dict[str, Any]) -> str:
        return jwt.encode(
            claims,
            self.private,
            algorithm=self.algorithm,
            headers={"kid": self.key_id},
        )
