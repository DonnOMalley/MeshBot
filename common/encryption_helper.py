from __future__ import annotations
import base64
import os
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_PBKDF2_ITERATIONS: int = 480_000
_KEY_LENGTH: int = 32
_SALT_LENGTH: int = 16


class EncryptionHelper:
    """Provides static utility methods for symmetric encryption and decryption.

    Uses Fernet (AES-128-CBC + HMAC-SHA256) with a key derived from a user-supplied
    passphrase via PBKDF2-HMAC-SHA256. A random salt must be generated once and
    stored alongside the encrypted data so the same key can be re-derived on each run.
    """

    # region Public Functions
    @staticmethod
    def generate_salt() -> bytes:
        """Generates a cryptographically random salt for key derivation.

        Returns:
            A byte string of length 16 suitable for use with :meth:`derive_key`.
        """
        return os.urandom(_SALT_LENGTH)

    @staticmethod
    def derive_key(passphrase: str, salt: bytes) -> bytes:
        """Derives a Fernet-compatible encryption key from a passphrase and salt.

        Uses PBKDF2-HMAC-SHA256 with 480 000 iterations, producing a 32-byte key
        that is base64url-encoded for direct use with :class:`~cryptography.fernet.Fernet`.

        Args:
            passphrase: The user-supplied passphrase string.
            salt: The random salt bytes previously produced by :meth:`generate_salt`.

        Returns:
            A base64url-encoded 32-byte key as ``bytes``, ready for ``Fernet(key)``.
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=_KEY_LENGTH,
            salt=salt,
            iterations=_PBKDF2_ITERATIONS,
        )
        return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))

    @staticmethod
    def encrypt(plaintext: str, key: bytes) -> str:
        """Encrypts a plain-text string and returns a base64-encoded ciphertext string.

        Each call produces a unique ciphertext because Fernet embeds a random IV.

        Args:
            plaintext: The text to encrypt.
            key: A Fernet-compatible key as produced by :meth:`derive_key`.

        Returns:
            A URL-safe base64-encoded ciphertext string that can be safely stored
            in a text file.
        """
        return Fernet(key).encrypt(plaintext.encode("utf-8")).decode("utf-8")

    @staticmethod
    def decrypt(ciphertext: str, key: bytes) -> str | None:
        """Decrypts a base64-encoded ciphertext string back to plain text.

        Args:
            ciphertext: The base64-encoded ciphertext produced by :meth:`encrypt`.
            key: The same Fernet-compatible key used during encryption.

        Returns:
            The decrypted plain-text string, or ``None`` if the key is wrong or
            the ciphertext has been tampered with.
        """
        result: str | None = None
        try:
            result = Fernet(key).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            pass
        return result

    @staticmethod
    def resolve_key(passphrase: str | None, salt_path: str) -> bytes | None:
        """Derives and returns a Fernet key from *passphrase* using a persistent salt.

        Loads the salt from *salt_path* if the file exists, otherwise generates a
        fresh random salt and writes it there. Returns ``None`` when no passphrase
        is supplied so callers can treat ``None`` as "encryption disabled".

        Args:
            passphrase: The user-supplied passphrase, or ``None`` to disable encryption.
            salt_path: Path to the salt file. The parent directory must already exist.

        Returns:
            A Fernet-compatible key as ``bytes``, or ``None``.
        """
        key: bytes | None = None
        if passphrase:
            if os.path.isfile(salt_path):
                with open(salt_path, "rb") as f:
                    salt: bytes = f.read()
            else:
                salt = EncryptionHelper.generate_salt()
                with open(salt_path, "wb") as f:
                    f.write(salt)
            key = EncryptionHelper.derive_key(passphrase, salt)
        return key
    # endregion Public Functions
