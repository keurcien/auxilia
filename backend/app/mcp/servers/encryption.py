"""Encryption utilities for MCP server API keys."""
import os
from cryptography.fernet import Fernet

from app.mcp.servers.settings import mcp_server_settings

def get_encryption_key() -> bytes:
    """Get or generate the encryption key for API keys.

    In production, this should be stored in environment variables or a secrets manager.
    For now, we'll use an environment variable or generate one.
    """
    key = mcp_server_settings.mcp_api_key_encryption_key.get_secret_value()
    if not key:
        # In development, generate a key. In production, this should be set in env vars
        # For now, we'll use a placeholder - you should set this in your .env file
        raise ValueError(
            "MCP_API_KEY_ENCRYPTION_KEY not found in environment variables. "
            "Generate one using: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return key.encode()


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
