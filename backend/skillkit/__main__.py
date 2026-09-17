"""Thin CLI: ``python -m skillkit list|validate|lock|diff|check <source>``.

Meant for the company skills repository's CI (``validate --strict`` and
``check`` exit non-zero) and for humans; the Python API is the product.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from skillkit.errors import SkillkitError
from skillkit.lock import Lockfile
from skillkit.model import ResolvedSource
from skillkit.requirements import EnvironmentManifest
from skillkit.sources import GitHubSource, GitLabSource, LocalSource, StaticCredentials


def _source(spec: str, ref: str, subpath: str | None, host: str | None):
    if spec.startswith(("http://", "https://")):
        kind = host or ("gitlab" if "gitlab" in spec else "github")
        credentials = StaticCredentials(os.environ.get("SKILLKIT_TOKEN"))
        cls = GitLabSource if kind == "gitlab" else GitHubSource
        return cls(spec, ref=ref, subpath=subpath, credentials=credentials)
    return LocalSource(spec, subpath=subpath)


def _print_resolved(resolved: ResolvedSource) -> None:
    print(f"{resolved.kind} {resolved.url} @ {resolved.revision}")
    for skill in resolved.all_skills:
        flags = " internal" if skill.internal else ""
        status = "ok" if skill.report.ok else f"{len(skill.report.errors)} error(s)"
        print(
            f"  {skill.name:<32} {skill.container or '/':<22} {skill.bundle.digest[:19]}  {status}{flags}"
        )
    for issue in resolved.issues:
        print(f"  {issue.code} {issue.message}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skillkit")
    parser.add_argument(
        "command", choices=["list", "validate", "lock", "diff", "check"]
    )
    parser.add_argument("source", help="a directory, or a GitHub/GitLab repository URL")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--path", dest="subpath", default=None)
    parser.add_argument("--host", choices=["github", "gitlab"], default=None)
    parser.add_argument("--lock", default="skills.lock")
    parser.add_argument(
        "--env", default=None, help="environment manifest (yaml/json) for `check`"
    )
    parser.add_argument(
        "--strict", action="store_true", help="warnings fail `validate` too"
    )
    args = parser.parse_args(argv)

    try:
        resolved = _source(args.source, args.ref, args.subpath, args.host).resolve()
        if args.command == "list":
            _print_resolved(resolved)
            return 0
        if args.command == "validate":
            failed = False
            for skill in resolved.all_skills:
                for issue in skill.report.issues:
                    where = f" ({issue.path})" if issue.path else ""
                    print(
                        f"{issue.severity[0].upper()} {issue.code} {skill.path or skill.name}{where}: {issue.message}"
                    )
                    if issue.suggestion:
                        print(f"    → did you mean '{issue.suggestion}'?")
                    failed = failed or issue.severity == "error" or args.strict
            for issue in resolved.issues:
                print(f"W {issue.code} {issue.message}")
                failed = failed or args.strict
            print(
                f"{len(resolved.all_skills)} skill(s); {'FAILED' if failed else 'ok'}"
            )
            return 1 if failed else 0
        if args.command == "lock":
            Lockfile.from_resolved(resolved).write(args.lock)
            print(f"wrote {args.lock} at {resolved.revision}")
            return 0
        if args.command == "diff":
            diff = Lockfile.read(args.lock).diff(resolved)
            print(f"revision {'changed' if diff.revision_changed else 'unchanged'}")
            for status in diff.skills:
                if status.status != "unchanged":
                    print(f"  {status.status:<9} {status.name}")
            return 0
        if args.command == "check":
            if not args.env:
                parser.error("--env is required for check")
            env = EnvironmentManifest.from_file(Path(args.env))
            failed = False
            for skill in resolved.skills:
                verdict = skill.check(env)
                print(
                    f"  {skill.name:<32} {'runnable' if verdict.runnable else 'NOT runnable'}"
                )
                for reason in verdict.reasons:
                    print(f"      {reason}")
                failed = failed or not verdict.runnable
            return 1 if failed else 0
    except SkillkitError as exc:
        print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
