# Advanced RAG Design

## 1) Retrieval strategy

Use hybrid retrieval to improve robustness:

- Dense retrieval: semantic embedding similarity
- Sparse retrieval: BM25 keyword relevance
- Reranking: cross-encoder for final top-k ordering

Final retrieval score can be a weighted blend:

score = alpha * dense + beta * sparse + gamma * rerank

Tune alpha/beta/gamma on a held-out evaluation set.

## 2) Indexing pipeline

1. Document normalization
2. Section-aware chunking (target 300-800 tokens)
3. Metadata enrichment (source, owner, validity dates, classification)
4. Embedding generation on private GPU/CPU workers
5. Index upsert with version tags

## 3) Context assembly rules

- Include only policy-allowed chunks
- Prefer same domain/business unit chunks first
- Include citation metadata with each chunk
- Apply max-token budgets by priority tiers

## 4) Guardrail architecture for RAG

Pre-retrieval:
- Query risk classification
- User entitlement check

Post-retrieval:
- Sensitive chunk filtering and redaction
- Data minimization enforcement

Pre-generation:
- Prompt policy template injection

Post-generation:
- Output classifier for leakage/harm/compliance risk

## 5) Evaluation framework

Track at least:

- Retrieval: Recall@k, MRR, nDCG@k
- Generation: answer relevance, groundedness, completeness
- Safety: policy violation rate, sensitive leak rate
- Ops: P50/P95 latency, timeout rate, error rate

## 6) Production hardening

- Cache layer for embeddings and frequent queries
- Circuit breaker on LLM endpoint
- Timeouts and retries with jitter
- Index freshness jobs with dead-letter queue
