"""Find skills in a file tree the way the ecosystem CLI does.

Rules (see ``data/containers.json`` for the list, and the spec §6):

- The repository root is a container if it holds ``SKILL.md`` — then the
  whole tree is that one skill.
- Each container is walked up to ``max_depth`` levels below it, covering
  flat (``skills/<name>/SKILL.md``) and catalog
  (``skills/<category>/<name>/SKILL.md``) layouts.
- A ``SKILL.md`` at a shallower level shadows anything nested beneath it:
  the nested files belong to the outer skill.
- Directories starting with ``.`` are skipped unless they are themselves a
  registered container (``skills/.curated``).
- ``full_depth=True`` also returns any ``SKILL.md`` outside the containers,
  with container ``"*"``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import resources

from skillkit.model import SKILL_MD


DEFAULT_MAX_DEPTH = 3
FULL_DEPTH_CONTAINER = "*"
ROOT_CONTAINER = ""


def default_containers() -> tuple[str, ...]:
    data = json.loads(
        resources.files("skillkit.data").joinpath("containers.json").read_text("utf-8")
    )
    return tuple(data["containers"])


@dataclass(frozen=True)
class Found:
    """A skill directory and the files under it, relative to that directory."""

    path: str  # skill directory, POSIX, "" for the root skill
    container: str
    files: dict[str, bytes]


def discover(
    tree: Mapping[str, bytes],
    *,
    containers: Iterable[str] | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    full_depth: bool = False,
    subpath: str | None = None,
) -> list[Found]:
    """Skill directories in ``tree`` (POSIX paths → bytes).

    ``subpath`` restricts the walk to one directory of the tree, which then
    plays the role of the repository root.
    """
    files = {_clean(p): c for p, c in tree.items() if _clean(p)}
    if subpath:
        prefix = _clean(subpath) + "/"
        files = {p[len(prefix) :]: c for p, c in files.items() if p.startswith(prefix)}

    skill_dirs = sorted(
        (
            p[: -len(SKILL_MD)].rstrip("/")
            for p in files
            if p == SKILL_MD or p.endswith("/" + SKILL_MD)
        ),
        key=lambda d: (d.count("/"), d),
    )
    if not skill_dirs:
        return []
    if "" in skill_dirs:
        return [Found("", ROOT_CONTAINER, dict(files))]

    registered = tuple(containers if containers is not None else default_containers())
    claimed: dict[str, str] = {}  # skill dir -> container
    for container in registered:
        base = _clean(container)
        for skill_dir in skill_dirs:
            if skill_dir in claimed or not _under(skill_dir, base):
                continue
            rel = skill_dir[len(base) :].strip("/") if base else skill_dir
            segments = rel.split("/")
            if len(segments) > max_depth or any(s.startswith(".") for s in segments):
                continue
            if _shadowed(skill_dir, claimed):
                continue
            claimed[skill_dir] = base
    if full_depth:
        for skill_dir in skill_dirs:
            if skill_dir not in claimed and not _shadowed(skill_dir, claimed):
                claimed[skill_dir] = FULL_DEPTH_CONTAINER

    found: list[Found] = []
    for skill_dir, container in sorted(claimed.items()):
        prefix = skill_dir + "/"
        found.append(
            Found(
                path=skill_dir,
                container=container,
                files={
                    p[len(prefix) :]: c
                    for p, c in files.items()
                    if p.startswith(prefix)
                },
            )
        )
    return found


def _clean(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def _under(path: str, base: str) -> bool:
    return base == "" or path == base or path.startswith(base + "/")


def _shadowed(skill_dir: str, claimed: Mapping[str, str]) -> bool:
    return any(skill_dir.startswith(outer + "/") for outer in claimed)
