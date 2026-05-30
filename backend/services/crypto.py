import base64
import binascii
import os

from cryptography.fernet import Fernet

_GENERATE_CMD = (
    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)


def _validate_fernet_key() -> None:
    key = os.environ.get("STRYD_FERNET_KEY")
    if not key:
        return
    try:
        # urlsafe_b64decode silently drops invalid chars; use b64decode(validate=True) instead
        standard = key.replace("-", "+").replace("_", "/")
        padded = standard + "=" * (-len(standard) % 4)
        raw = base64.b64decode(padded, validate=True)
    except (ValueError, binascii.Error):
        raise RuntimeError(
            f"STRYD_FERNET_KEY is not valid URL-safe base64. "
            f"Generate a valid key with: {_GENERATE_CMD}"
        )
    if len(raw) != 32:
        raise RuntimeError(
            f"STRYD_FERNET_KEY decoded to {len(raw)} bytes; Fernet requires exactly 32. "
            f"Generate a valid key with: {_GENERATE_CMD}"
        )


_validate_fernet_key()


def _get_fernet() -> Fernet:
    key = os.environ.get("STRYD_FERNET_KEY")
    if not key:
        raise RuntimeError(
            "STRYD_FERNET_KEY environment variable is not set. "
            f"Generate one with: {_GENERATE_CMD}"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
