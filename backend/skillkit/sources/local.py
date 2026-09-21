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
    # `is_dir()` follows a symlink, so a link pointing at another tree read as
    # a perfectly good root while every path inside it escaped the check below.
    if root.is_symlink():
        raise ValidationError(f"symlink as root: {root}", "E006")
    if not root.is_dir():
        raise ValidationError(f"{root} is not a directory", "E001")
    tree: dict[str, bytes] = {}
    total = 0
    # `.git` is skipped while walking, not after: sorting the whole of a real
    # checkout first meant holding every object path in memory before any
    # limit applied.
    paths = sorted(
        p
        for p in root.rglob("*")
        if not any(part == ".git" for part in p.relative_to(root).parts)
    )
    for path in paths:
        if path.is_symlink():
            raise ValidationError(f"symlink in tree: {path.relative_to(root)}", "E006")
        if not path.is_file():
            continue
        if len(tree) >= limits.max_files:
            raise LimitExceeded(f"more than {limits.max_files} files under {root}")
        # Size first: `read_bytes()` on a huge file would already have spent
        # the memory the limit exists to bound.
        size = path.stat().st_size
        if total + size > limits.max_extracted_bytes:
            raise LimitExceeded(
                f"more than {limits.max_extracted_bytes} bytes under {root}"
            )
        total += size
        tree[path.relative_to(root).as_posix()] = path.read_bytes()
    return tree
