"""Merge freshly mined cases into an existing manifest without undoing review.

Ownership rule:
- 'candidate' cases belong to the miner. A re-run replaces them, so they pick
  up miner fixes. A candidate is dropped only if this run examined its commit
  and no longer produces it. A run that stops early (--max-cases, a crash, a
  rate limit) sees only part of the history; not seeing a case is not
  evidence that it is invalid, so unexamined candidates are kept.
- 'reviewed' and 'rejected' cases belong to a person. A re-run never changes
  them. If the miner no longer produces one, it is kept and reported.

Running the miner twice must give the same manifest (idempotent), and running
it after a review must not erase the review.

Works on plain dicts (the YAML data), so human-owned cases are copied exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HUMAN_OWNED = {"reviewed", "rejected"}


@dataclass
class MergeResult:
    cases: list[dict]
    added: list[str] = field(default_factory=list)       # new candidates
    refreshed: list[str] = field(default_factory=list)   # candidates replaced by the new mining
    kept: list[str] = field(default_factory=list)        # human-owned, left as they were
    dropped: list[str] = field(default_factory=list)     # examined this run, no longer produced
    unscanned: list[str] = field(default_factory=list)   # candidates this run did not examine (kept)
    orphaned: list[str] = field(default_factory=list)    # human-owned, no longer mined (kept)


def merge_cases(existing: list[dict], mined: list[dict], scanned: set[str]) -> MergeResult:
    """`scanned` holds the ids of every commit this run examined, mined or skipped."""
    old = {c["id"]: c for c in existing}
    if len(old) != len(existing):
        raise ValueError("existing manifest has duplicate case ids")
    result = MergeResult(cases=[])
    mined_ids: set[str] = set()

    for case in mined:  # keep the miner's order
        cid = case["id"]
        if cid in mined_ids:
            raise ValueError(f"miner produced case {cid!r} twice")
        mined_ids.add(cid)
        prev = old.get(cid)
        if prev is None:
            result.cases.append(case)
            result.added.append(cid)
        elif prev["status"] in HUMAN_OWNED:
            result.cases.append(prev)
            result.kept.append(cid)
        else:
            result.cases.append(case)
            result.refreshed.append(cid)

    for cid, prev in old.items():
        if cid in mined_ids:
            continue
        if prev["status"] in HUMAN_OWNED:
            result.cases.append(prev)
            result.orphaned.append(cid)
        elif cid in scanned:
            result.dropped.append(cid)
        else:
            result.cases.append(prev)
            result.unscanned.append(cid)
    return result
