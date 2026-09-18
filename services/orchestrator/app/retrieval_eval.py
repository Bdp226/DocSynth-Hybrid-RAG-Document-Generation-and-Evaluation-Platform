"""Information-retrieval quality metrics and a known-item benchmark builder.

Retrieval quality was previously unmeasured, so a change to the ranking function
could silently degrade every generated document. These metrics make ranking a
gated, regression-tested property of the system.

Labelling strategy
------------------
The corpus has no human relevance judgements, so the harness constructs a
*known-item* benchmark: for each sampled chunk it builds a query out of that
chunk's most distinctive (highest-IDF) terms, and the chunk itself is the single
relevant result. This is the standard evaluation for unlabelled corpora. It
measures whether the ranker can find a specific known passage; it does not
measure topical relevance, and the numbers should be read with that caveat.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .retrieval import BM25Index, tokenize


@dataclass(frozen=True)
class EvalQuery:
    query: str
    relevant_doc_id: int


@dataclass(frozen=True)
class RetrievalMetrics:
    queries: int
    recall_at_1: float
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_10: float

    def as_dict(self) -> dict[str, float]:
        return {
            "queries": self.queries,
            "recall_at_1": round(self.recall_at_1, 4),
            "recall_at_5": round(self.recall_at_5, 4),
            "recall_at_10": round(self.recall_at_10, 4),
            "mrr": round(self.mrr, 4),
            "ndcg_at_10": round(self.ndcg_at_10, 4),
        }


def recall_at_k(ranked_ids: list[int], relevant_id: int, k: int) -> float:
    return 1.0 if relevant_id in ranked_ids[:k] else 0.0


def reciprocal_rank(ranked_ids: list[int], relevant_id: int) -> float:
    for position, doc_id in enumerate(ranked_ids, start=1):
        if doc_id == relevant_id:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked_ids: list[int], relevant_id: int, k: int) -> float:
    """nDCG for a single relevant document.

    With one relevant item the ideal DCG is always 1.0 (that item at rank 1), so
    nDCG reduces to the discounted gain of wherever the ranker actually put it.
    """
    for position, doc_id in enumerate(ranked_ids[:k], start=1):
        if doc_id == relevant_id:
            return 1.0 / math.log2(position + 1)
    return 0.0


def evaluate(rankings: list[list[int]], queries: list[EvalQuery]) -> RetrievalMetrics:
    """Aggregate metrics over a benchmark.

    ``rankings[i]`` is the ordered list of document ids returned for
    ``queries[i]``.
    """
    if not queries:
        return RetrievalMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0)

    totals = {"r1": 0.0, "r5": 0.0, "r10": 0.0, "mrr": 0.0, "ndcg": 0.0}
    for ranked_ids, query in zip(rankings, queries):
        totals["r1"] += recall_at_k(ranked_ids, query.relevant_doc_id, 1)
        totals["r5"] += recall_at_k(ranked_ids, query.relevant_doc_id, 5)
        totals["r10"] += recall_at_k(ranked_ids, query.relevant_doc_id, 10)
        totals["mrr"] += reciprocal_rank(ranked_ids, query.relevant_doc_id)
        totals["ndcg"] += ndcg_at_k(ranked_ids, query.relevant_doc_id, 10)

    n = float(len(queries))
    return RetrievalMetrics(
        queries=len(queries),
        recall_at_1=totals["r1"] / n,
        recall_at_5=totals["r5"] / n,
        recall_at_10=totals["r10"] / n,
        mrr=totals["mrr"] / n,
        ndcg_at_10=totals["ndcg"] / n,
    )


def build_known_item_queries(
    documents: list[str],
    *,
    terms_per_query: int = 4,
    stride: int = 1,
    max_df_ratio: float = 0.25,
) -> list[EvalQuery]:
    """Derive queries from each document's distinctive-but-shared vocabulary.

    Two filters keep the benchmark honest:

    * Terms occurring in exactly one document are dropped. A hapax term
      identifies its chunk uniquely, so including it makes every ranker score a
      perfect 1.0 and the benchmark discriminates nothing.
    * Terms occurring in more than ``max_df_ratio`` of the corpus are dropped as
      boilerplate.

    What remains is vocabulary shared by a handful of chunks - the realistic case
    where ranking quality actually decides the outcome.

    Sampling is strided rather than random so the benchmark is byte-for-byte
    reproducible across runs and CI machines.
    """
    index = BM25Index.build(documents)
    max_df = max(2, int(len(documents) * max_df_ratio))
    queries: list[EvalQuery] = []

    for doc_id in range(0, len(documents), stride):
        candidates = []
        for term in set(tokenize(documents[doc_id])):
            df = len(index.postings.get(term, ()))
            if df < 2 or df > max_df:
                continue
            candidates.append(term)

        if len(candidates) < terms_per_query:
            continue
        # Highest IDF first; ties broken alphabetically for determinism.
        candidates.sort(key=lambda t: (-index.idf(t), t))
        queries.append(
            EvalQuery(query=" ".join(candidates[:terms_per_query]), relevant_doc_id=doc_id)
        )

    return queries
