# FAANG 10/10 Project Playbook

This playbook turns the current project into a top-tier interview and portfolio asset.

## 1) 10/10 target definition

A 10/10 project demonstrates:

- Product clarity: clear user problem, scope, and success metrics
- System depth: thoughtful architecture, tradeoffs, and failure handling
- Engineering quality: tests, observability, and reproducibility
- Production readiness: security, governance, scaling, rollout plans
- Ownership: constraints handled with strong execution and documentation

## 2) North-star outcomes for this project

- End-to-end document pipeline from prompt + image + text to PDF and DOCX
- Enterprise controls: role-aware access, auditability, policy checks
- Scale design: multi-user operation model and deployment pathways
- Interview-ready evidence: demos, metrics, and structured design docs

## 3) Upgrade backlog (priority order)

## P0: Must-have (high impact)

1. Add automated tests
- Unit tests for policy checks, artifact generation, request validation
- API integration tests for optimize, compose, and artifact download

2. Add evaluation harness
- Quality scoring for output structure and instruction following
- Failure cases for invalid images, disallowed terms, and unauthorized access

3. Add observability baseline
- Request ID, latency, error class, and model route logs
- Basic dashboard-ready JSON logging schema

4. Add security hardening notes
- Header trust assumptions
- OIDC migration path and zero-trust boundary notes

## P1: Strong differentiators

1. Hybrid retrieval implementation
- Dense + keyword + reranker design and measurable gains

2. Quantitative retrieval instrumentation
- Retrieval latency, cache-hit rate, context size, and source coverage reported per request and in eval runs

3. Rate limiting and quota controls
- Protect service in multi-user environments

4. Model fallback strategy
- Vision model fallback path when unavailable

5. Canary release plan
- Versioned configs, rollback policy, acceptance checks

## P2: Showcase polish

1. Workflow templates library in UI
- SOP, executive brief, regulatory summary templates

2. Better artifact quality
- Structured headings, table support, metadata page

3. Demo dataset and scripted demo mode
- Repeatable demo for interviews

## 4) 12-week execution plan

## Weeks 1-2
- Testing baseline and CI checks
- Metrics instrumentation and error taxonomy

## Weeks 3-4
- Evaluation harness with benchmark cases
- Result table in docs (before vs after)

## Weeks 5-6
- Hybrid RAG path and relevance metrics
- Rate limits and graceful degradation

## Weeks 7-8
- Security hardening docs and OIDC path
- Canary and rollback procedure docs

## Weeks 9-10
- UI workflow templates and export improvements
- Demo recording and reproducible scenario scripts

## Weeks 11-12
- Mock interview drills and project narrative refinement
- Final repo cleanup and portfolio packaging

## 5) Interview framing sentence

I built an enterprise-grade document automation platform that transforms mixed text and image inputs into policy-governed, optimized Word and PDF outputs, and I engineered it to remain production-ready despite strict infrastructure constraints.
