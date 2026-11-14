from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(<?([^)\s>]+)>?\)|!\[[^\]]*\]\(<?([^)\s>]+)>?\)")
FENCE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)


def slugs(markdown: str) -> set[str]:
    """GitHub-style heading anchors, including -1, -2 suffixes for repeats."""
    seen: dict[str, int] = {}
    result = set()
    for line in FENCE.sub("", markdown).splitlines():
        match = re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not match:
            continue
        slug = re.sub(r"[^\w\- ]", "", match.group(1).strip().lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        result.add(slug if count == 0 else f"{slug}-{count}")
        seen[slug] = count + 1
    return result


def broken_links() -> list[str]:
    tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "*.md"], text=True)
    problems = []
    for name in tracked.split():
        source = ROOT / name
        if not source.exists():
            continue
        text = FENCE.sub("", source.read_text(encoding="utf-8"))
        for match in LINK.finditer(text):
            target = match.group(1) or match.group(2)
            if re.match(r"[a-z][a-z0-9+.-]*:", target):
                continue
            path, _, anchor = target.partition("#")
            resolved = (source.parent / path).resolve() if path else source
            if not resolved.exists():
                problems.append(f"{name}: missing {target}")
            elif anchor and resolved.suffix == ".md":
                if anchor not in slugs(resolved.read_text(encoding="utf-8")):
                    problems.append(f"{name}: no anchor {target}")
    return problems


class DocumentationLinkTests(unittest.TestCase):
    def test_slugs_follow_github_rules(self) -> None:
        self.assertEqual(
            slugs("## Memory study v1\n## Task 2: `x` (a, b)\n## Usage\n### Usage"),
            {"memory-study-v1", "task-2-x-a-b", "usage", "usage-1"},
        )

    def test_relative_links_and_anchors_resolve(self) -> None:
        self.assertEqual(broken_links(), [])


if __name__ == "__main__":
    unittest.main()
