from __future__ import annotations

import math

from app.retrieval import (
    BM25Index,
    rank_positions,
    reciprocal_rank_fusion,
    tokenize,
)
from app.retrieval_eval import (
    EvalQuery,
    build_known_item_queries,
    evaluate,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

CORPUS = [
    "azure cost analysis dashboard for the sandbox subscription",
    "kubernetes cluster autoscaling and node pool configuration",
    "azure cost export scheduled to a storage account daily",
    "onboarding guide for new sandbox tenant administrators",
]


def test_tokenize_preserves_repetition_for_term_frequency() -> None:
    # BM25 weights by term frequency, so the tokenizer must not deduplicate.
    assert tokenize("cost cost cost") == ["cost", "cost", "cost"]


def test_tokenize_drops_short_tokens() -> None:
    assert tokenize("a an the cost") == ["the", "cost"]


def test_bm25_ranks_the_matching_document_first() -> None:
    index = BM25Index.build(CORPUS)
    scores = index.scores("kubernetes node pool")
    assert scores.index(max(scores)) == 1


def test_bm25_idf_is_never_negative_for_common_terms() -> None:
    # A term in every document has df == doc_count; the unsmoothed Robertson
    # formula goes negative there, which would subtract relevance.
    index = BM25Index.build(["cost report", "cost summary", "cost detail"])
    assert index.idf("cost") >= 0.0


def test_bm25_idf_is_zero_for_unknown_terms() -> None:
    index = BM25Index.build(CORPUS)
    assert index.idf("nonexistentterm") == 0.0


def test_bm25_prefers_the_shorter_of_two_equally_matching_documents() -> None:
    # Length normalisation: a hit in a short document is stronger evidence.
    index = BM25Index.build(["alpha beta", "alpha beta " + "filler " * 60])
    scores = index.scores("alpha beta")
    assert scores[0] > scores[1]


def test_bm25_handles_empty_corpus() -> None:
    index = BM25Index.build([])
    assert index.scores("anything") == []


def test_rank_positions_leaves_zero_scoring_documents_unranked() -> None:
    # A channel that never matched a document must not vote for it.
    assert rank_positions([0.0, 5.0, 0.0, 2.0]) == [0, 1, 0, 2]


def test_rrf_normalises_a_unanimous_top_result_to_one() -> None:
    fused = reciprocal_rank_fusion([[9.0, 1.0], [7.0, 1.0]])
    assert math.isclose(fused[0], 1.0)


def test_rrf_rewards_agreement_between_channels() -> None:
    # Document 0 is ranked first by both channels; document 1 is first by one
    # channel only. Agreement must win.
    agree = reciprocal_rank_fusion([[9.0, 8.0, 0.0], [9.0, 1.0, 0.0]])
    assert agree[0] > agree[1]


def test_rrf_is_invariant_to_channel_score_scale() -> None:
    # The whole point of rank fusion: multiplying one channel by 1000 must not
    # let it dominate, which is exactly what a weighted sum would do.
    small = reciprocal_rank_fusion([[0.9, 0.8, 0.1], [0.2, 0.3, 0.9]])
    large = reciprocal_rank_fusion([[900.0, 800.0, 100.0], [0.2, 0.3, 0.9]])
    assert small == large


def test_rrf_handles_no_channels() -> None:
    assert reciprocal_rank_fusion([]) == []


def test_recall_at_k_respects_the_cutoff() -> None:
    assert recall_at_k([5, 1, 2], 2, k=3) == 1.0
    assert recall_at_k([5, 1, 2], 2, k=2) == 0.0


def test_reciprocal_rank_uses_one_based_positions() -> None:
    assert reciprocal_rank([7, 3, 9], 3) == 0.5
    assert reciprocal_rank([7, 3, 9], 42) == 0.0


def test_ndcg_is_one_when_the_relevant_document_is_first() -> None:
    assert ndcg_at_k([4, 1, 2], 4, k=10) == 1.0


def test_ndcg_discounts_lower_positions() -> None:
    assert ndcg_at_k([1, 4], 4, k=10) == 1.0 / math.log2(3)


def test_evaluate_aggregates_a_perfect_run() -> None:
    queries = [EvalQuery("a", 0), EvalQuery("b", 1)]
    metrics = evaluate([[0, 1], [1, 0]], queries)
    assert metrics.recall_at_1 == 1.0
    assert metrics.mrr == 1.0


def test_evaluate_handles_an_empty_benchmark() -> None:
    assert evaluate([], []).queries == 0


def test_known_item_queries_exclude_unique_terms() -> None:
    # "kubernetes" appears in exactly one chunk, so it must not be used as a
    # query term - it would make the benchmark trivially passable.
    queries = build_known_item_queries(CORPUS, terms_per_query=2)
    for query in queries:
        assert "kubernetes" not in query.query.split()


def test_known_item_queries_are_deterministic() -> None:
    assert build_known_item_queries(CORPUS) == build_known_item_queries(CORPUS)


def test_bm25_beats_chance_on_the_known_item_benchmark() -> None:
    # Each term appears in exactly two documents (so it survives the hapax
    # filter) and any two documents share at most one term. The only way to rank
    # the right document first is to actually combine the query terms.
    documents = [
        "alpha bravo charlie",
        "delta echo foxtrot",
        "golf hotel india",
        "alpha delta golf",
        "bravo echo hotel",
        "charlie foxtrot india",
    ]
    queries = build_known_item_queries(documents, terms_per_query=3)
    assert len(queries) == len(documents)

    index = BM25Index.build(documents)
    rankings = []
    for query in queries:
        scores = index.scores(query.query)
        rankings.append(sorted(range(len(documents)), key=lambda i: scores[i], reverse=True))

    assert evaluate(rankings, queries).recall_at_1 == 1.0
