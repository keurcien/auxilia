"""Encryption utilities for sensitive stored values."""
import base64
import hashlib

from cryptography.fernet import Fernet

from app.mcp.servers.settings import mcp_server_settings


def get_encryption_key() -> bytes:
    """Derive a valid Fernet key from the configured salt.

    Reads SALT first; falls back to the deprecated MCP_API_KEY_ENCRYPTION_SALT.
    Hashes the salt with SHA-256 to produce 32 bytes, then base64url-encodes
    it into a valid Fernet key.
    """
    salt = mcp_server_settings.get_salt()
    derived = hashlib.sha256(salt.encode()).digest()
    return base64.urlsafe_b64encode(derived)


def encrypt_value(value: str) -> str:
    """Encrypt a string value for storage."""
    fernet = Fernet(get_encryption_key())
    return fernet.encrypt(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    """Decrypt a string value from storage."""
    fernet = Fernet(get_encryption_key())
    return fernet.decrypt(encrypted.encode()).decode()


# Deprecated aliases — use encrypt_value / decrypt_value instead
encrypt_api_key = encrypt_value
decrypt_api_key = decrypt_value
