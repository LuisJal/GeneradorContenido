from cryptography.fernet import Fernet, InvalidToken


class FieldEncryptor:
    """Encrypts/decrypts sensitive fields (API keys, tokens) using Fernet."""

    def __init__(self, key: str):
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, Exception):
            return ""
