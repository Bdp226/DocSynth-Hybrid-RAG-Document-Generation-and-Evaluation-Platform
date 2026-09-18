# Compliance and Governance Checklist

Use this checklist before production rollout.

## A) Data governance

- [ ] Data classification tags defined for all document sources
- [ ] Sensitive data handling policy mapped to processing actions
- [ ] Data retention and deletion policy implemented
- [ ] Data residency constraints validated

## B) Security

- [ ] Private network-only deployment validated
- [ ] TLS for all service-to-service traffic
- [ ] Secrets stored in approved vault/K8s secrets
- [ ] RBAC integrated with enterprise IAM/SSO
- [ ] Vulnerability scans enabled for images and dependencies

## C) AI governance

- [ ] Model endpoint is enterprise-approved
- [ ] Prompt and output filtering policy enabled
- [ ] Hallucination and regression evaluation pipeline defined
- [ ] Human-in-the-loop checkpoints configured for high-risk docs
- [ ] Model/version change management documented

## D) Operations

- [ ] Audit logs immutable and queryable
- [ ] Alerting and SLOs defined
- [ ] Backup and disaster recovery runbooks available
- [ ] Capacity planning completed for expected load

## E) Legal/compliance

- [ ] Final legal review completed
- [ ] Vendor/open-source license review completed
- [ ] DPIA/PIA completed if applicable
- [ ] Export control constraints reviewed if applicable
