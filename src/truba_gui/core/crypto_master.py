from __future__ import annotations

import base64
import os
from dataclasses import dataclass

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


@dataclass(frozen=True)
class EncryptedSecret:
    """Encrypted payload and salt (both urlsafe-base64 strings)."""

    token: str
    salt: str


def _derive_fernet_key(master_password: str, salt_b64: str, *, iterations: int = 200_000) -> bytes:
    """Derive a Fernet key from a user-provided master password and salt."""
    if not master_password:
        raise ValueError("master password is required")
    salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    key = kdf.derive(master_password.encode("utf-8"))
    return base64.urlsafe_b64encode(key)


def encrypt_with_master(master_password: str, plaintext: str) -> EncryptedSecret:
    """Encrypt plaintext using a master password. Returns token + per-secret salt."""
    if plaintext is None:
        plaintext = ""
    salt = os.urandom(16)
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii")
    f = Fernet(_derive_fernet_key(master_password, salt_b64))
    token = f.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return EncryptedSecret(token=token, salt=salt_b64)


def decrypt_with_master(master_password: str, token: str, salt_b64: str) -> str:
    """Decrypt a token using the provided master password and salt."""
    f = Fernet(_derive_fernet_key(master_password, salt_b64))
    return f.decrypt(token.encode("ascii")).decode("utf-8")
