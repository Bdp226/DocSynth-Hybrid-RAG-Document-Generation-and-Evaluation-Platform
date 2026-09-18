# Security Policy

## Supported scope
This repository contains a document-synthesis platform that may process enterprise material, generated artifacts, and local model endpoints. Security-sensitive changes should be reviewed before deployment in any shared environment.

## Reporting a vulnerability
Do not open a public GitHub issue for security-sensitive findings.

Instead:
1. Email the maintainer directly with reproduction steps, affected files, and impact.
2. Include whether the issue affects local artifact storage, identity headers, prompt injection resistance, model endpoint trust, or generated document leakage.
3. Allow time for triage and remediation before public disclosure.

## Areas that deserve special review
- Artifact download authorization
- Identity and role-header enforcement
- Generated document data leakage
- Local model endpoint exposure
- Dependency vulnerabilities in document parsing libraries

## Hardening expectations
- Keep `.env` files out of version control.
- Do not commit generated customer artifacts.
- Run CI and security workflows before merging.
- Re-run document leak checks after changing extraction or rendering behavior.
