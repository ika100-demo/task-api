#!/usr/bin/env python3
"""Platform-owned (spec 095): helpers for scripts/deps.sh. Standard library only.

Never edits uv.lock.

normalize <pkg>           PEP 503 name
locked <pkg>              the versions uv.lock has for <pkg>, one per line (nothing when absent)
satisfied <pkg> <ver>     exit 0 when every locked copy of <pkg> is <ver> or higher
section <pkg>             uv add flags of the section that declares <pkg>; exit 1 when transitive
constrain <pkg> <ver>     add "<pkg>>=<ver>" to [tool.uv] constraint-dependencies in pyproject.toml
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def version_key(v: str) -> tuple[tuple[int, int, str], ...]:
    parts: list[tuple[int, int, str]] = []
    for p in re.split(r"[.\-+]", v.lstrip("v")):
        parts.append((0, int(p), "") if p.isdigit() else (-1, 0, p))
    return tuple(parts)


def locked(pkg: str) -> list[str]:
    lock = Path("uv.lock")
    if not lock.is_file():
        return []
    data = tomllib.loads(lock.read_text())
    return [
        p.get("version", "")
        for p in data.get("package", [])
        if normalize(p.get("name", "")) == normalize(pkg)
    ]


def req_name(req: str) -> str:
    m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", req)
    return normalize(m.group(1)) if m else ""


def section(pkg: str) -> str | None:
    data = tomllib.loads(Path("pyproject.toml").read_text())
    want = normalize(pkg)
    project = data.get("project", {})
    if any(req_name(r) == want for r in project.get("dependencies", [])):
        return ""
    for extra, reqs in project.get("optional-dependencies", {}).items():
        if any(req_name(r) == want for r in reqs):
            return f"--optional {extra}"
    for group, reqs in data.get("dependency-groups", {}).items():
        if any(isinstance(r, str) and req_name(r) == want for r in reqs):
            return f"--group {group}"
    return None


def _array_end(text: str, start: int) -> int:
    """Index after the `]` closing the array that opens at `start` (strings, comments skipped)."""
    depth, i, quote = 0, start, ""
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "#":
            i = text.index("\n", i) if "\n" in text[i:] else len(text)
            continue
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unterminated array")


def constrain(pkg: str, ver: str) -> None:
    path = Path("pyproject.toml")
    text = path.read_text()
    entry = f"{normalize(pkg)}>={ver}"
    header = re.search(r"^\[tool\.uv\][ \t]*(?:#.*)?$", text, re.M)
    if header is None:
        new = text.rstrip("\n") + f'\n\n[tool.uv]\nconstraint-dependencies = ["{entry}"]\n'
    else:
        body_start = header.end()
        nxt = re.search(r"^\[", text[body_start:], re.M)
        body_end = body_start + nxt.start() if nxt else len(text)
        key = re.search(r"^constraint-dependencies[ \t]*=[ \t]*\[", text[body_start:body_end], re.M)
        if key is None:
            new = text[:body_start] + f'\nconstraint-dependencies = ["{entry}"]' + text[body_start:]
        else:
            open_at = body_start + key.end() - 1
            close = _array_end(text, open_at)
            current = tomllib.loads(text)["tool"]["uv"]["constraint-dependencies"]
            items = [c for c in current if req_name(c) != normalize(pkg)] + [entry]
            if "\n" in text[open_at:close]:
                arr = "[\n" + "".join(f'    "{i}",\n' for i in items) + "]"
            else:
                arr = "[" + ", ".join(f'"{i}"' for i in items) + "]"
            new = text[:open_at] + arr + text[close:]
    if entry not in tomllib.loads(new).get("tool", {}).get("uv", {}).get(
        "constraint-dependencies", []
    ):
        raise ValueError("the edit did not produce the constraint")
    path.write_text(new)


def main(argv: list[str]) -> int:
    cmd, args = (argv[0] if argv else ""), argv[1:]
    if cmd == "normalize" and len(args) == 1:
        print(normalize(args[0]))
    elif cmd == "locked" and len(args) == 1:
        print("\n".join(locked(args[0])))
    elif cmd == "satisfied" and len(args) == 2:
        versions = locked(args[0])
        return (
            0 if versions and all(version_key(v) >= version_key(args[1]) for v in versions) else 1
        )
    elif cmd == "section" and len(args) == 1:
        flags = section(args[0])
        if flags is None:
            return 1
        print(flags)
    elif cmd == "constrain" and len(args) == 2:
        constrain(*args)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
