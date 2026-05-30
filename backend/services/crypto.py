import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = os.environ.get("STRYD_FERNET_KEY")
    if not key:
        raise RuntimeError(
            "STRYD_FERNET_KEY environment variable is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
