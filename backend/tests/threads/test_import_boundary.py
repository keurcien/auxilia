"""`app/threads` owns thread rows, not the conversation.

The conversation is encoded in exactly one place — `app/agents/protocol/messages.py`
(`serialize_message` / `serialize_message_preview`) — and served by
`app/agents/protocol/`. Until #313 the threads module carried a second, unread
encoding (`threads/serialization.py` + the AI-SDK adapter); this test keeps it
from growing back. It parses the sources rather than importing them so a
transitive import elsewhere cannot mask a direct one here.
"""

import ast
from pathlib import Path

import app.threads


FORBIDDEN_PREFIXES = ("app.agents.protocol", "app.agents.checkpoints")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_threads_module_does_not_encode_the_conversation():
    package_dir = Path(app.threads.__file__).parent
    offenders = {
        f"{path.name}: {name}"
        for path in package_dir.glob("*.py")
        for name in _imports(path)
        if name.startswith(FORBIDDEN_PREFIXES)
    }
    assert not offenders, (
        "app/threads must not read or encode the transcript; that lives in "
        f"app/agents/protocol/. Offending imports: {sorted(offenders)}"
    )
