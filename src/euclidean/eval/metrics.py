"""Ranking metrics for one query, plus a mean that keeps per-query values.

Conventions (state them in every report):
- `ranked` is the system output, best first. Search returns chunks, so the
  same file or symbol can appear many times. We keep only its first position
  (dedupe_ranked) before scoring.
- precision@k divides by k, not by the number of results. A system that
  returns 2 results at k=10 is not rewarded for returning few.
- MRR here is MRR@k: a first hit after rank k scores 0.
- nDCG uses binary gains (relevant = 1). The ideal ranking puts
  min(|relevant|, k) hits at the top.
- An empty relevant set is an error, not a score of 0 or 1. The manifest
  should already prevent it.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


def dedupe_ranked(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _check(relevant: set[str], k: int) -> None:
    if not relevant:
        raise ValueError("relevant set is empty; this query cannot be scored")
    if k < 1:
        raise ValueError("k must be >= 1")


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    _check(relevant, k)
    hits = len(set(dedupe_ranked(ranked)[:k]) & relevant)
    return hits / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    _check(relevant, k)
    hits = len(set(dedupe_ranked(ranked)[:k]) & relevant)
    return hits / k


def reciprocal_rank(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    _check(relevant, k)
    for rank, item in enumerate(dedupe_ranked(ranked)[:k], start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    _check(relevant, k)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(dedupe_ranked(ranked)[:k], start=1)
        if item in relevant
    )
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return dcg / ideal


METRICS = {
    "recall": recall_at_k,
    "precision": precision_at_k,
    "mrr": reciprocal_rank,
    "ndcg": ndcg_at_k,
}


@dataclass(frozen=True)
class MetricReport:
    k: int
    mean: dict[str, float]
    per_query: dict[str, dict[str, float]]  # case id -> metric -> value
    n_queries: int


def evaluate(results: dict[str, Sequence[str]], labels: dict[str, set[str]], k: int) -> MetricReport:
    """Score every labeled query. A query with no result list scores 0, not skipped.

    Skipping missing results would make a system that crashes on hard
    queries look better.
    """
    if not labels:
        raise ValueError("no labeled queries")
    extra = set(results) - set(labels)
    if extra:
        raise ValueError(f"results for unlabeled queries: {sorted(extra)}")
    per_query = {
        qid: {name: fn(results.get(qid, []), rel, k) for name, fn in METRICS.items()}
        for qid, rel in labels.items()
    }
    mean = {name: sum(q[name] for q in per_query.values()) / len(per_query) for name in METRICS}
    return MetricReport(k=k, mean=mean, per_query=per_query, n_queries=len(per_query))
