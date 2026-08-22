"""Encryption utilities for sensitive stored values.

Deprecated location — the implementation moved to app.utils.encryption so
non-MCP modules (e.g. sandboxes) can use it without importing mcp.servers.
"""

from app.utils.encryption import decrypt_value, encrypt_value, get_encryption_key


__all__ = ["decrypt_value", "encrypt_value", "get_encryption_key"]

# Deprecated aliases — use encrypt_value / decrypt_value instead
encrypt_api_key = encrypt_value
decrypt_api_key = decrypt_value
