import math

import pytest

from euclidean.eval.metrics import (
    evaluate,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

# Hand-worked example. ranked has a duplicate 'a' (two chunks of one file).
# After dedupe: [a, x, b, y]. Top 3: [a, x, b]. Hits: a (rank 1), b (rank 3).
RANKED = ["a", "x", "b", "a", "y"]
RELEVANT = {"a", "b", "c"}


def test_recall_precision_hand_values():
    assert recall_at_k(RANKED, RELEVANT, 3) == pytest.approx(2 / 3)
    assert precision_at_k(RANKED, RELEVANT, 3) == pytest.approx(2 / 3)


def test_ndcg_hand_value():
    # DCG  = 1/log2(2) + 1/log2(4) = 1 + 0.5 = 1.5
    # IDCG = 1/log2(2) + 1/log2(3) + 1/log2(4) = 2.130930
    expected = 1.5 / (1 + 1 / math.log2(3) + 0.5)
    assert ndcg_at_k(RANKED, RELEVANT, 3) == pytest.approx(expected)
    assert expected == pytest.approx(0.703918, abs=1e-6)


def test_reciprocal_rank_respects_cutoff():
    assert reciprocal_rank(["x", "y", "b"], {"b"}, 2) == 0.0
    assert reciprocal_rank(["x", "y", "b"], {"b"}, 3) == pytest.approx(1 / 3)


def test_duplicates_do_not_push_hits_down():
    # Three chunks of file x, then file a. Without dedupe, a is rank 4.
    assert reciprocal_rank(["x", "x", "x", "a"], {"a"}, 2) == pytest.approx(0.5)


def test_precision_divides_by_k_not_result_count():
    assert precision_at_k(["a"], {"a"}, 5) == pytest.approx(0.2)


def test_empty_relevant_is_error():
    with pytest.raises(ValueError):
        recall_at_k(["a"], set(), 5)


def test_evaluate_missing_result_scores_zero_and_keeps_per_query():
    report = evaluate({"q1": ["a"]}, {"q1": {"a"}, "q2": {"b"}}, k=1)
    assert report.per_query["q2"]["recall"] == 0.0
    assert report.mean["recall"] == pytest.approx(0.5)
    assert report.n_queries == 2


def test_evaluate_rejects_results_for_unlabeled_queries():
    with pytest.raises(ValueError):
        evaluate({"q9": ["a"]}, {"q1": {"a"}}, k=1)
