"""A directory on disk. Symlinks are rejected, not followed."""

from __future__ import annotations

from pathlib import Path

from skillkit.digest import bundle_digest
from skillkit.errors import LimitExceeded, ValidationError
from skillkit.model import Limits, ResolvedSource
from skillkit.sources.base import resolve_tree


class LocalSource:
    def __init__(
        self,
        path: str | Path,
        *,
        subpath: str | None = None,
        full_depth: bool = False,
        limits: Limits = Limits(),
    ) -> None:
        self.path = Path(path)
        self.subpath = subpath
        self.full_depth = full_depth
        self.limits = limits

    def resolve(self) -> ResolvedSource:
        tree = read_tree(self.path, self.limits)
        return resolve_tree(
            tree,
            kind="local",
            url=str(self.path),
            ref=None,
            revision="local:" + bundle_digest(tree),
            subpath=self.subpath,
            full_depth=self.full_depth,
            limits=self.limits,
        )


def read_tree(root: Path, limits: Limits) -> dict[str, bytes]:
    if not root.is_dir():
        raise ValidationError(f"{root} is not a directory", "E001")
    tree: dict[str, bytes] = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValidationError(f"symlink in tree: {path.relative_to(root)}", "E006")
        if not path.is_file():
            continue
        if any(part == ".git" for part in path.relative_to(root).parts):
            continue
        data = path.read_bytes()
        total += len(data)
        if len(tree) >= limits.max_files:
            raise LimitExceeded(f"more than {limits.max_files} files under {root}")
        if total > limits.max_extracted_bytes:
            raise LimitExceeded(
                f"more than {limits.max_extracted_bytes} bytes under {root}"
            )
        tree[path.relative_to(root).as_posix()] = data
    return tree
