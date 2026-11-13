"""Audit the exact Git index without printing potentially sensitive matches."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT_FILES = {".gitattributes", ".gitignore", "LICENSE", "README.md", "pyproject.toml"}
ROOT_DIRECTORIES = {"afterevidence", "tests", "research", "docs", "scripts", ".github"}
EXTENSIONS = {".py", ".md", ".toml", ".json", ".yml", ".ps1", ".css", ".html", ".js", ".txt"}
PRIVATE_DIRECTORIES = {
    "vendor",
    ".venv",
    "runs",
    "cache",
    "data",
    "results",
    "__pycache__",
    "dist",
    "build",
}
SECRET_PATTERNS = {
    "credential-token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,})"
    ),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "raw-account-quota": re.compile(r'["\']quota_snapshots["\']\s*:\s*\{'),
}


def path_errors(name: str) -> list[str]:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return ["invalid-path"]
    if name in ROOT_FILES:
        return []
    if not path.parts or path.parts[0] not in ROOT_DIRECTORIES:
        return ["not-in-public-allowlist"]
    if any(part in PRIVATE_DIRECTORIES for part in path.parts) or path.name.startswith(".env"):
        return ["private-or-generated-path"]
    if path.suffix not in EXTENSIONS:
        return ["unexpected-file-type"]
    return []


def text_errors(text: str) -> list[str]:
    result = [name for name, pattern in SECRET_PATTERNS.items() if pattern.search(text)]
    normalized = text.replace("\\\\", "/").replace("\\", "/").casefold()
    home = str(Path.home()).replace("\\", "/").casefold()
    if home in normalized:
        result.append("local-home-path")
    return result


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    top = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"], text=True
    ).strip()
    if Path(top).resolve() != root:
        raise RuntimeError("Publication audit must run at the AfterEvidence repository root.")
    entries = (
        subprocess.check_output(["git", "-C", str(root), "ls-files", "--stage", "-z"])
        .decode("utf-8")
        .split("\0")
    )
    entries = [entry for entry in entries if entry]
    if not entries:
        raise RuntimeError("Git index is empty. Stage only the intended release allowlist first.")
    findings: list[tuple[str, str]] = []
    for entry in entries:
        metadata, name = entry.split("\t", 1)
        mode = metadata.split()[0]
        errors = path_errors(name)
        if mode not in {"100644", "100755"}:
            errors.append("symlink-or-submodule")
        if errors:
            findings.extend((name, error) for error in errors)
            continue
        content = subprocess.check_output(["git", "-C", str(root), "show", ":" + name])
        if len(content) > 1_000_000 or b"\0" in content:
            findings.append((name, "large-or-binary-content"))
            continue
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            findings.append((name, "non-utf8-content"))
            continue
        findings.extend((name, error) for error in text_errors(text))
    for name, error in findings:
        print(f"BLOCKED {name}: {error}")
    if findings:
        return 1
    print(f"Publication audit passed for {len(entries)} staged text files.")
    print(
        "No private paths, raw account snapshots, local-home paths, or recognized credential formats were found."
    )
    print(
        "This is an allowlist and pattern check, not a proof that arbitrary content is safe to publish."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
