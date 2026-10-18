# Contributing

Thank you for helping SecondChance. This repository is its starting point: the foundations are in place, and the next steps are shaped by the NGOs that adopt it and the people who build it with them. Code, documentation, translations, accessibility reviews and field knowledge from food banks and volunteers are all contributions.

## Where to start

- Read the [README](README.md), run the local stack and the tests, and skim [docs/ADR.md](docs/ADR.md) for the decisions already taken.
- Good first areas: tailoring the platform to a real organisation (procedures, roles, languages, specialist agents), OCR for scanned PDFs, direct-to-S3 uploads, human approval flows for agent proposals, accessibility, translations and load tests.
- For a larger change, open an issue first and describe the problem; agreeing on the approach saves rework.

## How changes are made

1. Start the stack and the tests as described in the [README](README.md). A change is ready when `uv run pytest`, `uvx ruff@0.16.10 check .` and, if you touched the web app, `npm test && npm run build` pass. Changes to the AWS path also pass `scripts/emulate-aws.sh`.
2. A decision that changes the architecture goes into a new ADR in [docs/ADR.md](docs/ADR.md), with the rejected alternatives.
3. A new table has `tenant_id`, Row-Level Security and a `pii:` comment on every column: the catalogue tests check it.
4. A new endpoint validates its input with Pydantic (`extra="forbid"`), declares the allowed roles and rejects early whatever it cannot serve (ADR-016).
5. A new screen adds its strings to all four files in `web/src/locales` (en, da, pl, it); the build fails otherwise. English is the source text.
6. Commit messages use the `type: description` format (`feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`).
7. Never real personal data, secrets or keys in the repository, the tests or the issues.

## Contributor terms

SecondChance is licensed to everyone under the [PolyForm Noncommercial License 1.0.0](LICENSE), and its author, Pierfrancesco Lijoi, may also license it commercially ([ADR-020](docs/ADR.md#adr-020--licence-polyform-noncommercial-commercial-use-by-agreement)). To keep both possible, every contribution is made on these terms. By opening a pull request you confirm that:

1. the contribution is your own work, or you have the right to submit it under these terms;
2. you grant Pierfrancesco Lijoi a perpetual, worldwide, non-exclusive, royalty-free and irrevocable licence to use, reproduce, modify, distribute and sublicense the contribution under any terms, commercial ones included;
3. you keep the copyright of your contribution, and you are credited for it in the project history.

If you cannot accept these terms, please open an issue to discuss the change instead of a pull request.

## Security

Report vulnerabilities as described in [SECURITY.md](SECURITY.md), never in a public issue.
