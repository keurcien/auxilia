"""`app/threads` owns thread rows, not the conversation.

The conversation is encoded in exactly one place — `app/agents/protocol/messages.py`
(`serialize_message` / `serialize_message_preview`) — and served by
`app/agents/protocol/`. Until #313 the threads module carried a second, unread
encoding (`threads/serialization.py` + the AI-SDK adapter); this test keeps it
from growing back. It parses the sources rather than importing them so a
transitive import elsewhere cannot mask a direct one here, and it resolves
relative imports (`from ..agents.protocol import …`) to their absolute name.
"""

import ast
from pathlib import Path

import app.threads


FORBIDDEN_PREFIXES = ("app.agents.protocol", "app.agents.checkpoints")


def _resolve_relative(package: str, level: int, module: str | None) -> str:
    """`from ..x import y` inside `package` → the absolute dotted module."""
    parts = package.split(".")
    base = ".".join(parts[: len(parts) - (level - 1)]) if level > 1 else package
    return f"{base}.{module}" if module else base


def imports_of(source: str, package: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names.add(_resolve_relative(package, node.level, node.module))
            elif node.module:
                names.add(node.module)
    return names


def test_relative_imports_resolve_to_absolute_names():
    src = (
        "from ..agents.protocol.messages import serialize_message\n"
        "from . import models\n"
        "from .schemas import ThreadRead\n"
        "import app.pagination\n"
    )
    assert imports_of(src, "app.threads") == {
        "app.agents.protocol.messages",
        "app.threads",
        "app.threads.schemas",
        "app.pagination",
    }


def test_threads_module_does_not_encode_the_conversation():
    package_dir = Path(app.threads.__file__).parent
    offenders = {
        f"{path.name}: {name}"
        for path in package_dir.glob("*.py")
        for name in imports_of(path.read_text(), app.threads.__name__)
        if name.startswith(FORBIDDEN_PREFIXES)
    }
    assert not offenders, (
        "app/threads must not read or encode the transcript; that lives in "
        f"app/agents/protocol/. Offending imports: {sorted(offenders)}"
    )
