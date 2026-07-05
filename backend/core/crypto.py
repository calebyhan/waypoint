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
