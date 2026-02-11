"""Tests for utility modules: encryption, logging, file_storage."""
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet


def test_encryption_round_trip():
    """Encrypting then decrypting should return original text."""
    from app.utils.encryption import FieldEncryptor

    key = Fernet.generate_key().decode()
    enc = FieldEncryptor(key)

    original = "my-super-secret-api-key-12345"
    encrypted = enc.encrypt(original)
    decrypted = enc.decrypt(encrypted)

    assert encrypted != original
    assert decrypted == original


def test_encryption_different_ciphertexts():
    """Same plaintext should produce different ciphertexts (Fernet uses random IV)."""
    from app.utils.encryption import FieldEncryptor

    key = Fernet.generate_key().decode()
    enc = FieldEncryptor(key)

    ct1 = enc.encrypt("hello")
    ct2 = enc.encrypt("hello")
    assert ct1 != ct2


def test_encryption_invalid_ciphertext_returns_empty():
    """Decrypting garbage should return empty string, not raise."""
    from app.utils.encryption import FieldEncryptor

    key = Fernet.generate_key().decode()
    enc = FieldEncryptor(key)

    result = enc.decrypt("not-a-valid-ciphertext")
    assert result == ""


def test_logging_setup(capsys):
    """setup_logging should configure the root logger."""
    from app.utils.logging_config import setup_logging, get_logger

    setup_logging()
    logger = get_logger("test_module")

    assert logger.name == "generador.test_module"
    assert isinstance(logger, logging.Logger)


def test_file_storage_video_path():
    """get_video_path should return a path under storage/videos/{slug}/."""
    from app.utils.file_storage import get_video_path

    path = get_video_path("fitness-bot", 42)
    assert isinstance(path, Path)
    assert "storage/videos/fitness-bot" in str(path)
    assert "content_42.mp4" in str(path)


def test_file_storage_video_url():
    """get_video_url should return a public URL string."""
    from app.utils.file_storage import get_video_url

    url = get_video_url("tech-bot", 7)
    assert "storage/videos/tech-bot" in url
    assert "content_7.mp4" in url
    assert url.startswith("http")
