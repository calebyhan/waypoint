from cryptography.fernet import Fernet, InvalidToken

from core.config import settings

_fernet = Fernet(settings.token_encryption_key)


def encrypt(value: str) -> str:
    """Encrypt a plaintext string for storage."""
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    """Decrypt a stored value, or return None if it isn't decryptable.

    Tokens stored before encryption was introduced are plaintext and will
    fail to decrypt; treat that the same as a missing token so callers fall
    back to prompting the user to reconnect their GitHub account.
    """
    try:
        return _fernet.decrypt(value.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def decrypt_or_plaintext(value: str | None) -> str | None:
    """Decrypt a stored secret, falling back to the raw value if undecryptable.

    Used for columns (e.g. profiles.gemini_api_key) that historically stored
    plaintext: rows written before encryption shipped fail Fernet decryption
    and are treated as legacy plaintext instead of breaking existing users.
    New writes always encrypt, so plaintext values age out naturally the next
    time the user saves the field.
    """
    if not value:
        return None
    decrypted = decrypt(value)
    return decrypted if decrypted is not None else value
