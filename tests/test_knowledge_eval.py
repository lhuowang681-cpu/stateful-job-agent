import pytest

from job_agent.knowledge.eval import (
    RetrievalEvalCase,
    evaluate_rankings,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k() -> None:
    retrieved = ["A", "B", "D", "E"]
    relevant = {"A", "C"}

    assert recall_at_k(
        retrieved,
        relevant,
        k=4,
    ) == pytest.approx(0.5)


def test_precision_at_k() -> None:
    retrieved = ["A", "B", "D", "E"]
    relevant = {"A", "C"}

    assert precision_at_k(
        retrieved,
        relevant,
        k=4,
    ) == pytest.approx(0.25)


def test_reciprocal_rank() -> None:
    retrieved = [
        "wrong-a",
        "wrong-b",
        "correct",
        "another-correct",
    ]

    relevant = {
        "correct",
        "another-correct",
    }

    assert reciprocal_rank(
        retrieved,
        relevant,
    ) == pytest.approx(1 / 3)


def test_reciprocal_rank_is_zero_when_no_relevant_result() -> None:
    assert reciprocal_rank(
        ["A", "B", "C"],
        {"D"},
    ) == 0.0
    
def test_evaluate_rankings() -> None:
    cases = [
        RetrievalEvalCase(
            query="query-1",
            relevant_ids={"A"},
        ),
        RetrievalEvalCase(
            query="query-2",
            relevant_ids={"C"},
        ),
    ]

    rankings = [
        ["A", "B", "C"],   # 正确答案 rank 1
        ["A", "C", "B"],   # 正确答案 rank 2
    ]

    metrics = evaluate_rankings(
        rankings,
        cases,
        k=2,
    )

    assert metrics.recall_at_k == pytest.approx(1.0)

    # 每个 query 的 Precision@2 都是 1/2
    assert metrics.precision_at_k == pytest.approx(0.5)

    # RR: 1 和 1/2
    # MRR = (1 + 0.5) / 2 = 0.75
    assert metrics.mrr == pytest.approx(0.75)