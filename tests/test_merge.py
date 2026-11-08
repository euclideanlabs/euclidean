import pytest

from euclidean.dataset.merge import merge_cases


def case(cid, status="candidate", query="mined query"):
    return {"id": cid, "status": status, "query": query}


def ids(cases):
    return {c["id"] for c in cases}


def test_review_survives_a_re_run():
    existing = [case("a", "reviewed", query="hand-written symptom"), case("b", "rejected")]
    mined = [case("a"), case("b")]
    r = merge_cases(existing, mined, scanned={"a", "b"})
    assert r.cases == existing  # exactly as the person left them
    assert r.kept == ["a", "b"]


def test_candidates_are_refreshed_and_new_ones_added():
    existing = [case("a", query="old link")]
    mined = [case("a", query="fixed link"), case("new")]
    r = merge_cases(existing, mined, scanned={"a", "new"})
    assert [c["query"] for c in r.cases] == ["fixed link", "mined query"]
    assert (r.refreshed, r.added) == (["a"], ["new"])


def test_examined_but_not_produced_candidate_is_dropped():
    # e.g. the miner now recognizes the commit's PR as a release PR and skips it
    r = merge_cases([case("gone")], mined=[], scanned={"gone"})
    assert r.cases == [] and r.dropped == ["gone"]


def test_partial_run_keeps_unexamined_candidates():
    # Regression (2026-11-08): a --max-cases 15 re-run dropped 27 candidates
    # it never looked at.
    existing = [case("a"), case("later1"), case("later2")]
    r = merge_cases(existing, mined=[case("a")], scanned={"a"})
    assert ids(r.cases) == {"a", "later1", "later2"}
    assert (r.dropped, r.unscanned) == ([], ["later1", "later2"])


def test_vanished_review_is_kept_even_if_examined():
    r = merge_cases([case("decided", "reviewed")], mined=[], scanned={"decided"})
    assert ids(r.cases) == {"decided"} and r.orphaned == ["decided"]


def test_merge_is_idempotent():
    existing = [case("a", "reviewed"), case("b"), case("c")]
    mined = [case("a"), case("b")]
    once = merge_cases(existing, mined, scanned={"a", "b"}).cases
    assert merge_cases(once, mined, scanned={"a", "b"}).cases == once


def test_duplicate_ids_are_errors():
    with pytest.raises(ValueError, match="twice"):
        merge_cases([], [case("a"), case("a")], scanned={"a"})
    with pytest.raises(ValueError, match="duplicate"):
        merge_cases([case("a"), case("a")], [], scanned=set())
