"""Hybrid lexical + dense retrieval.

The original implementation summed an ad-hoc IDF score with a cosine similarity.
That had two defects:

1.  Correctness.  The two channels live on incompatible scales (cosine is
    bounded in [-1, 1]; the IDF sum is unbounded and depends on corpus size), so
    a weighted sum silently let one channel dominate and produced fused scores
    that could not be interpreted or thresholded.
2.  Cost.  Document frequency was recomputed inside the per-chunk loop, which
    re-tokenised the entire corpus once per query term per chunk - quadratic in
    the number of chunks.

This module replaces both with textbook Okapi BM25 over a precomputed inverted
index, fused with the dense channel using Reciprocal Rank Fusion.  RRF consumes
only the *rank* each channel assigns, so it is invariant to score scale and
needs no per-corpus tuning.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

# Okapi BM25 parameters. These are the values from the original TREC experiments
# and remain the accepted defaults for general prose.
BM25_K1 = 1.5
BM25_B = 0.75

# Reciprocal Rank Fusion damping constant from Cormack et al. (2009). Large
# enough that the gap between rank 1 and rank 2 does not swamp agreement between
# the two channels.
RRF_K = 60

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
_MIN_TOKEN_LENGTH = 3


def tokenize(text: str) -> list[str]:
    """Tokenise preserving order and repetition.

    BM25 is a bag-of-words model that weights by term *frequency*, so unlike the
    set-based tokeniser used for the noise heuristics this must keep duplicates.
    """
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= _MIN_TOKEN_LENGTH]


@dataclass
class BM25Index:
    """Inverted index supporting Okapi BM25 scoring.

    Built once per corpus in O(total tokens); each query then costs
    O(query terms x postings) instead of re-scanning every chunk.
    """

    doc_count: int = 0
    avg_doc_length: float = 0.0
    doc_lengths: list[int] = field(default_factory=list)
    # term -> {doc index: term frequency}
    postings: dict[str, dict[int, int]] = field(default_factory=dict)

    @classmethod
    def build(cls, documents: list[str]) -> "BM25Index":
        index = cls(doc_count=len(documents))
        total_length = 0
        for doc_id, document in enumerate(documents):
            tokens = tokenize(document)
            index.doc_lengths.append(len(tokens))
            total_length += len(tokens)
            for term, freq in Counter(tokens).items():
                index.postings.setdefault(term, {})[doc_id] = freq
        index.avg_doc_length = (total_length / len(documents)) if documents else 0.0
        return index

    def idf(self, term: str) -> float:
        """Robertson/Sparck-Jones IDF with the standard +0.5 smoothing.

        The outer ``log(1 + x)`` form keeps the value non-negative even for terms
        appearing in more than half the corpus, which the raw formulation does
        not guarantee.
        """
        df = len(self.postings.get(term, ()))
        if df == 0:
            return 0.0
        return math.log(1.0 + (self.doc_count - df + 0.5) / (df + 0.5))

    def scores(self, query: str) -> list[float]:
        """Return a BM25 score for every document in the corpus."""
        results = [0.0] * self.doc_count
        if self.doc_count == 0 or self.avg_doc_length <= 0:
            return results

        for term in set(tokenize(query)):
            postings = self.postings.get(term)
            if not postings:
                continue
            idf = self.idf(term)
            if idf <= 0.0:
                continue
            for doc_id, freq in postings.items():
                length_norm = 1.0 - BM25_B + BM25_B * (self.doc_lengths[doc_id] / self.avg_doc_length)
                denominator = freq + BM25_K1 * length_norm
                if denominator <= 0:
                    continue
                results[doc_id] += idf * (freq * (BM25_K1 + 1.0)) / denominator
        return results


def rank_positions(scores: list[float]) -> list[int]:
    """Map each document to its 1-based rank, best score first.

    Documents scoring exactly zero are unranked: a channel that never matched a
    document should not vote for it at all, otherwise RRF would reward documents
    purely for existing in the corpus.
    """
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    ranks = [0] * len(scores)
    position = 0
    for doc_id in order:
        if scores[doc_id] <= 0.0:
            continue
        position += 1
        ranks[doc_id] = position
    return ranks


def reciprocal_rank_fusion(channels: list[list[float]], k: int = RRF_K) -> list[float]:
    """Fuse ranked channels into a single 0-1 relevance score.

    Raw RRF values are tiny (~1/61) and depend on the channel count, which makes
    them useless for reporting or thresholding. Dividing by the score a document
    would receive if every channel ranked it first normalises the result to
    [0, 1] without changing the ordering.
    """
    if not channels:
        return []

    doc_count = len(channels[0])
    fused = [0.0] * doc_count
    for scores in channels:
        for doc_id, rank in enumerate(rank_positions(scores)):
            if rank > 0:
                fused[doc_id] += 1.0 / (k + rank)

    best_possible = len(channels) / (k + 1)
    if best_possible <= 0:
        return fused
    return [value / best_possible for value in fused]
