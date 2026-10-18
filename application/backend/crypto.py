import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key(secret: str) -> bytes:
    raw = secret.encode("utf-8")
    if len(raw) < 16:
        raise ValueError("TOKEN_ENCRYPTION_KEY trop court")
    return raw.ljust(32, b"0")[:32]


def encrypt_text(plaintext: str, secret: str) -> str:
    aes = AESGCM(_key(secret))
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ct).decode("ascii")


def decrypt_text(ciphertext: str, secret: str) -> str:
    aes = AESGCM(_key(secret))
    raw = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    nonce, ct = raw[:12], raw[12:]
    return aes.decrypt(nonce, ct, None).decode("utf-8")
