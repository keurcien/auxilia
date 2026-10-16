"""OAuth completion rendezvous, keyed by an unguessable authorization state."""

import hashlib


def oauth_completion_key(state: str) -> str:
    return "mcp:oauth-complete:" + hashlib.sha256(state.encode()).hexdigest()
