"""Encryption utilities for MCP server API keys."""
import base64
import hashlib
from cryptography.fernet import Fernet

from app.mcp.servers.settings import mcp_server_settings


def get_encryption_key() -> bytes:
    """Derive a valid Fernet key from the user-provided salt.

    Hashes the salt with SHA-256 to produce 32 bytes, then base64url-encodes
    it into a valid Fernet key.
    """
    salt = mcp_server_settings.mcp_api_key_encryption_salt.get_secret_value()
    if not salt:
        raise ValueError(
            "MCP_API_KEY_ENCRYPTION_SALT not found in environment variables. "
            "Set it to any secret string in your .env file."
        )
    derived = hashlib.sha256(salt.encode()).digest()
    return base64.urlsafe_b64encode(derived)


def encrypt_api_key(api_key: str) -> str:
    """Encrypt an API key for storage.

    Args:
        api_key: The plain text API key to encrypt

    Returns:
        The encrypted API key as a base64-encoded string
    """
    fernet = Fernet(get_encryption_key())
    encrypted = fernet.encrypt(api_key.encode())
    return encrypted.decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """Decrypt an API key from storage.

    Args:
        encrypted_key: The encrypted API key as a base64-encoded string

    Returns:
        The decrypted plain text API key
    """
    fernet = Fernet(get_encryption_key())
    decrypted = fernet.decrypt(encrypted_key.encode())
    return decrypted.decode()
