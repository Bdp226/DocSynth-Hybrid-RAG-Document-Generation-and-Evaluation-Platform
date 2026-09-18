## Summary
- Describe the user-visible or platform-facing change.
- Link the issue, deck sample, or evaluation artifact when relevant.

## Validation
- [ ] `pytest tests -q`
- [ ] `python scripts/check_partwise.py`
- [ ] `python scripts/check_compose_full_deck.py`
- [ ] I verified no generated PDFs or DOCX files are being committed.

## Risk Review
- [ ] No new slide-number leakage in rendered PDF text
- [ ] No roster or meeting-chatter leakage
- [ ] No regression in image or table counts
- [ ] No environment-secret changes

## Notes
- Mention any Ollama availability assumptions, benchmark deltas, or known limits.
