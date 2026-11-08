"""Small read-only git helpers. Every call names an exact commit."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


class GitRepo:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(self.path), *args],
            check=True, capture_output=True, text=True, encoding="utf-8",
        )
        return result.stdout

    def resolve(self, ref: str) -> str:
        return self._git("rev-parse", ref).strip()

    def list_files(self, sha: str) -> set[str]:
        return set(self._git("ls-tree", "-r", "--name-only", sha).splitlines())

    def show(self, sha: str, path: str) -> str:
        return self._git("show", f"{sha}:{path}")

    def changed_lines(self, sha: str, path: str) -> list[int]:
        """Line numbers in the post-fix file that the commit added or changed.

        A pure deletion has no new lines, so we use the line where it happened.
        """
        diff = self._git("diff", "-U0", f"{sha}^", sha, "--", path)
        lines: list[int] = []
        for m in HUNK_RE.finditer(diff):
            start, count = int(m.group(1)), int(m.group(2) or 1)
            lines.extend(range(start, start + count) if count else [max(start, 1)])
        return lines
