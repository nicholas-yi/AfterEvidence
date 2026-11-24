"""Frozen study sources: the hashes every plan records, and the protocol tag's commit and seed.

Sources are recorded by file name (as in every published plan) and found wherever they live under
research/. A tag made before the package layout (research/<name>) is still compared correctly.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable, Iterable
from functools import cache
from pathlib import Path
from typing import Any

from research import REPOSITORY, RESEARCH

PACKAGES = ("analysis", "harness", "studies", "tools")


@cache
def source_path(name: str) -> Path:
    found = [p for p in (RESEARCH / name, *(RESEARCH / d / name for d in PACKAGES)) if p.exists()]
    if len(found) != 1:
        raise FileNotFoundError(f"Expected one research source named {name}, found {len(found)}.")
    return found[0]


def source_hashes(names: Iterable[str]) -> dict[str, str]:
    return {n: hashlib.sha256(source_path(n).read_bytes()).hexdigest() for n in names}


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPOSITORY, capture_output=True, check=True).stdout


def commit_of(name: str) -> str | None:
    try:
        return git("rev-parse", f"{name}^{{commit}}").decode().strip()
    except subprocess.CalledProcessError:
        return None


def at_commit(commit: str, name: str) -> bytes | None:
    """The source as committed: in its package, or at research/<name> before the packages."""
    for path in (source_path(name).relative_to(REPOSITORY).as_posix(), f"research/{name}"):
        try:
            return git("show", f"{commit}:{path}")
        except subprocess.CalledProcessError:
            continue
    return None


def changed_since(commit: str, names: Iterable[str]) -> list[str]:
    return [n for n in names if at_commit(commit, n) != source_path(n).read_bytes()]


def tag_state(
    tag: str, sources: Iterable[str], seed: Callable[[str], int]
) -> dict[str, Any] | None:
    """The protocol tag's commit, the seed derived from it, and the sources changed since it."""
    commit = commit_of(tag)
    if commit is None:
        return None
    return {
        "tag": tag,
        "commit": commit,
        "seed": seed(commit),
        "changed": changed_since(commit, sources),
    }
