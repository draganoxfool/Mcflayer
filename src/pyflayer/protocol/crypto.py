"""AES-128-CFB8 stream cipher for online-mode connections.

Minecraft uses AES/CFB8/NoPadding with the shared secret as both key and IV. Encryption and
decryption need independent stream states (one cipher context per direction).

Examples:
    >>> key = bytes(16)
    >>> enc, dec = CipherPair(key)
    >>> dec.decrypt(enc.encrypt(b"hello"))
    b'hello'
"""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

try:  # cryptography >= 45 moved CFB8 to the decrepit namespace
    from cryptography.hazmat.decrepit.ciphers.modes import CFB8
except ImportError:  # pragma: no cover - older cryptography
    from cryptography.hazmat.primitives.ciphers.modes import CFB8  # type: ignore[assignment]

__all__ = ["CipherPair", "AES_CFB8", "encrypt_rsa"]


def encrypt_rsa(public_key_der: bytes, data: bytes) -> bytes:
    """Encrypt bytes with the server's DER public key (RSA PKCS#1 v1.5).

    Used for the shared secret and verify token in the login encryption exchange.

    Raises:
        ValueError: When the key is not a valid DER public key.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    key = serialization.load_der_public_key(public_key_der)
    if not hasattr(key, "encrypt"):  # pragma: no cover - public keys always encrypt
        raise ValueError("public key cannot encrypt")
    return key.encrypt(data, padding.PKCS1v15())


class CipherPair:
    """Encrypt/decrypt AES-128-CFB8 contexts for one connection."""

    __slots__ = ("_encryptor", "_decryptor")

    def __init__(self, shared_secret: bytes) -> None:
        if len(shared_secret) != 16:
            raise ValueError("AES-128 requires a 16-byte shared secret")
        # Per the protocol, key == IV == shared secret.
        encrypt_cipher = Cipher(algorithms.AES(shared_secret), CFB8(shared_secret))
        decrypt_cipher = Cipher(algorithms.AES(shared_secret), CFB8(shared_secret))
        self._encryptor = encrypt_cipher.encryptor()
        self._decryptor = decrypt_cipher.decryptor()

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt bytes, advancing the outbound stream."""
        return self._encryptor.update(data)

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt bytes, advancing the inbound stream."""
        return self._decryptor.update(data)


#: Public alias used in docs.
AES_CFB8 = CipherPair
