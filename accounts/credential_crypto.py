"""
Symmetric encryption helpers for player login credentials.

Uses cryptography.fernet keyed off Django SECRET_KEY. The derived key
is stable across processes as long as SECRET_KEY is unchanged. If
SECRET_KEY rotates, previously encrypted passwords cannot be decrypted.
"""
import base64
import hashlib

from django.conf import settings
from cryptography.fernet import Fernet, InvalidToken


def _get_fernet():
    """Derive a Fernet key from Django SECRET_KEY."""
    secret = settings.SECRET_KEY.encode("utf-8")
    # SHA-256 gives a stable 32-byte value, base64-url-encoded for Fernet
    digest = hashlib.sha256(secret).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns an empty string if input is empty."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Returns an empty string if input is empty."""
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken:
        raise ValueError(
            "Unable to decrypt the stored credential. The encryption key may "
            "have changed since this value was saved."
        )
