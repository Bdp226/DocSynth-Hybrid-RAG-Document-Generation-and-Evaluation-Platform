# ADR-0001: Hybrid BM25 + embedding retrieval over pure vector search

- **Status:** Accepted
- **Date:** 2026-09-19
- **Deciders:** Retrieval owner, Platform owner

## Context

The corpus is enterprise slide decks, PDFs, and workspace documents. Two
properties of this content break naive vector search:

1. **Rare exact tokens carry most of the signal.** Users search for
   `SHIFT_Sandbox`, `llama3.2-vision:11b`, ticket IDs, and product code names.
   A 384-dimension MiniLM embedding compresses these into near-neighbours of
   semantically similar but factually wrong chunks.
2. **Slide text is short and fragmentary.** Bullet fragments produce weak,
   unstable embeddings — the very chunks where lexical overlap is most reliable.

Pure embedding retrieval was measurably worse on exact-identifier queries, and
those queries are the ones where a wrong answer is most visible to a reviewer.

## Decision

Rank chunks with a hybrid scorer: BM25 lexical scoring fused with embedding
cosine similarity via reciprocal rank fusion, with embeddings degradable through
`RAG_USE_EMBEDDINGS=false`.

## Alternatives considered

| Option | Why it was rejected |
|---|---|
| Pure embedding / Qdrant-only search | Loses exact-token precision on identifiers and version strings, which is the dominant query class. |
| Pure BM25 | No paraphrase recall. Users ask "how do we restore ingestion?" against a deck that says "recovery procedure". |
| Cross-encoder reranking on top of vectors | Best quality, but adds a second model on the request path. Rejected for now on latency and GPU cost; revisit under a rerank budget. |
| LLM-based query expansion | Adds a full generation round trip before retrieval even starts, doubling p95 latency for a marginal recall gain. |

## Consequences

**Positive**

- Exact identifiers and paraphrases both retrieve well.
- BM25 requires no model, so the system degrades gracefully to a working
  retriever when the embedding model is unavailable.
- Both score components are logged per request, so retrieval failures can be
  attributed to the lexical or semantic side rather than guessed at.

**Negative / accepted cost**

- Two scoring passes per query instead of one.
- The fusion weighting is a tuned constant; it is a hyperparameter that must be
  re-validated when the chunk size or embedding model changes.

## Revisit when

`retrieval_recall_at_5` drops below 0.8 on the golden set, or a rerank latency
budget above 200 ms becomes available.
