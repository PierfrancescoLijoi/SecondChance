# Security

## Reporting a vulnerability

Do not open a public issue. Use the repository's **Security → Report a vulnerability** (GitHub private vulnerability reporting). Include the version or commit, steps to reproduce and the expected impact. We answer within 5 working days.

Of particular interest: access to another tenant's data, bypassing human approval, role escalation during registration, personal data exposed in logs, traces or model answers.

## What the code already does

- Tenant isolation in PostgreSQL (Row-Level Security), with tests that fail if a table is left without it: see the [threat model](docs/security/threat-model.md).
- No AWS access keys: people use IAM Identity Center or console sessions (`aws login`), CI uses OIDC, the runtime uses IAM roles: see [deployment](docs/deployment.md).
- Dependencies, images and actions pinned to versions or digests; updates wait 14 days after a release ([dependabot](.github/dependabot.yml)).
- Only synthetic data outside the pilot ([GDPR](docs/compliance/gdpr.md)).
