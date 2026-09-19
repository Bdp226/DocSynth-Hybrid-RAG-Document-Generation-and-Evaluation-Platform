"""Benchmark the retrieval ranker against the previous weighted-sum scorer.

Run from services/orchestrator:
    ..\\..\\.venv\\Scripts\\python.exe scripts\\eval_retrieval.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.retrieval import BM25Index, reciprocal_rank_fusion
from app.retrieval_eval import build_known_item_queries, evaluate
from app.workspace_context import _chunk_text, _read_document_text_cached, _tokenize


def _legacy_idf(chunks: list[str], token: str) -> float:
    df = sum(1 for chunk in chunks if token in _tokenize(chunk))
    return math.log((1 + len(chunks)) / (1 + df)) + 1.0


def _legacy_scores(query: str, chunks: list[str]) -> list[float]:
    """The scorer this change replaced: per-chunk IDF sum, recomputed each call."""
    query_tokens = _tokenize(query)
    scores = []
    for chunk in chunks:
        chunk_tokens = _tokenize(chunk)
        if not chunk_tokens or not query_tokens:
            scores.append(0.0)
            continue
        total = sum(_legacy_idf(chunks, t) for t in query_tokens if t in chunk_tokens)
        scores.append(total / max(len(chunk_tokens), 1))
    return scores


def _rank(scores: list[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)


def _load_corpus(root: Path, limit_chunks: int) -> list[str]:
    chunks: list[str] = []
    for path in sorted(root.iterdir()):
        if path.suffix.lower() not in {".pptx", ".pdf", ".docx", ".md", ".txt"}:
            continue
        text, _ = _read_document_text_cached(path, max_chars=120_000)
        if not text.strip():
            continue
        chunks.extend(_chunk_text(text.strip(), chunk_size=900, overlap=180))
        if len(chunks) >= limit_chunks:
            break
    return chunks[:limit_chunks]


def main() -> int:
    root = Path(__file__).resolve().parents[3]
    corpus = _load_corpus(root, limit_chunks=400)
    if not corpus:
        print("No corpus documents found at", root)
        return 1

    queries = build_known_item_queries(corpus, stride=4)
    print(f"CORPUS_CHUNKS {len(corpus)}")
    print(f"BENCHMARK_QUERIES {len(queries)}")
    print()

    index = BM25Index.build(corpus)

    started = time.perf_counter()
    new_rankings = [_rank(reciprocal_rank_fusion([index.scores(q.query)])) for q in queries]
    new_ms = (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    legacy_rankings = [_rank(_legacy_scores(q.query, corpus)) for q in queries]
    legacy_ms = (time.perf_counter() - started) * 1000

    legacy = evaluate(legacy_rankings, queries).as_dict()
    new = evaluate(new_rankings, queries).as_dict()

    print(f"{'metric':<14}{'legacy':>10}{'bm25+rrf':>12}{'delta':>12}")
    print("-" * 48)
    for key in ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"):
        delta = new[key] - legacy[key]
        print(f"{key:<14}{legacy[key]:>10.4f}{new[key]:>12.4f}{delta:>+12.4f}")

    print("-" * 48)
    print(f"{'latency_ms':<14}{legacy_ms:>10.1f}{new_ms:>12.1f}{new_ms - legacy_ms:>+12.1f}")
    print(f"SPEEDUP {legacy_ms / new_ms:.1f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
