# Ingestion Platform - Technical Reference

## Overview

The ingestion platform converts enterprise source material - slide decks, PDFs,
and workspace documents - into publication-ready reference documentation. Source
material is normalised into chunked text with slide-accurate figure extraction so
that every generated statement remains traceable to its origin.

## Retrieval

Chunks are ranked by a hybrid scorer that fuses BM25 lexical matching with
embedding similarity. Lexical scoring preserves precision on exact identifiers
such as model names and ticket references; embedding similarity recovers
paraphrased intent. The fused ranking assembles the grounded context window that
constrains generation.

## Generation

Requests are routed to a fast, default, or strong model according to the
requested detail level. When the inference tier is unavailable, a deterministic
structure-preserving composer produces a grounded document from the retrieved
context and the run is recorded as degraded rather than failed.

## Rendering

Output is rendered to PDF and DOCX with section headings, figure captions, and
tables. Presentation artefacts from the source - slide numbers, action items,
and meeting chatter - are removed during post-processing.

## Measured Throughput

| Configuration | Throughput (docs/min) | Median latency (s) |
| --- | --- | --- |
| Baseline | 18 | 4.2 |
| Tuned | 42 | 1.8 |
| Cached | 61 | 1.1 |

## Telemetry

Every run emits a structured record of more than fifty KPIs covering retrieval
quality, generation quality, content integrity, and operational cost. These
records back both the live dashboard and the offline quality analysis.
