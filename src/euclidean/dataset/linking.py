"""Link a fix commit to the text that describes the problem.

Pure functions: the caller fetches PR and issue data, these functions decide.
That keeps the link rules testable without the network.

Why this matters: the query must describe the symptom, not the fix. Issue
text usually describes the symptom. PR text usually names the fixed code,
which leaks the answer into the query.
"""

from __future__ import annotations

import re
from enum import Enum

_BACKPORT = re.compile(r"\bback-?port", re.I)
_RELEASE = re.compile(r"\brelease\b|\bchangelog\b|^(?:bump|prepare)\b.*\bversion\b", re.I)
_CLOSING = re.compile(
    r"\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s*:?\s*"
    r"\[?(?:#|pallets/click#|https://github\.com/pallets/click/issues/)(\d+)",  # '[' = markdown link
    re.I,
)
_MENTION = re.compile(r"(?:(?<![\w/])#|pallets/click#|https://github\.com/pallets/click/(?:issues|pull)/)(\d+)")


class PRKind(str, Enum):
    NORMAL = "normal"
    BACKPORT = "backport"  # copy of another PR onto a branch; follow the original
    RELEASE = "release"    # bundles many changes; no single problem statement


class LinkStrength(str, Enum):
    CLOSES = "closes"      # "fixes #N", "closes #N", ...
    MENTIONS = "mentions"  # any other reference; may be a related issue only


def pr_kind(title: str) -> PRKind:
    if _BACKPORT.search(title):
        return PRKind.BACKPORT
    if _RELEASE.search(title):
        return PRKind.RELEASE
    return PRKind.NORMAL


def backport_source(title: str, body: str) -> int | None:
    """Number of the original PR that a backport copies, if it names one."""
    for text in (title, body):
        m = _MENTION.search(text or "")
        if m:
            return int(m.group(1))
    return None


def issue_refs(text: str, exclude: set[int] = frozenset()) -> list[tuple[int, LinkStrength]]:
    """Referenced numbers, closing references first, no repeats.

    A '#N' can point to an issue or a PR. The caller must check which.
    `exclude` removes numbers we already know are not the issue (e.g. the PR itself).
    """
    out: list[tuple[int, LinkStrength]] = []
    seen = set(exclude)
    for pattern, strength in ((_CLOSING, LinkStrength.CLOSES), (_MENTION, LinkStrength.MENTIONS)):
        for m in pattern.finditer(text or ""):
            n = int(m.group(1))
            if n not in seen:
                seen.add(n)
                out.append((n, strength))
    return out
