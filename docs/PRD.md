# SecondChance — Product Requirements Document (PRD)

**Version:** 0.5.0  
**Status:** draft for validation with humanitarian organisations  
**Licence:** PolyForm Noncommercial 1.0.0: free for non-profit, charitable and other noncommercial use; commercial use by written licence from the author (ADR-020)  
**Type:** source-available platform for aid coordination  
**First use case:** recovery and redistribution of surplus food  
**Languages:** English (source and default), Danish, Polish, Italian  
**Deployment target:** local development with Docker Compose; ephemeral serverless AWS demo in `eu-central-1`; pilot on AWS with the same architecture in a Multi-AZ configuration  
**Related documents:** [architecture](architecture.md) · [ADR](ADR.md) · [deployment](deployment.md) · [diagrams](diagrams/)

## What's new

### v0.5

| Area | v0.4 | v0.5 | Why |
|---|---|---|---|
| Centres | Name only | Capacity, accepted categories, storage, coordinates, time zone and weekly acceptance slots, managed by org admins and the centre's own staff (FR-003, FR-014) | The optimiser can only propose what a centre can really receive |
| Matching | Planned for P2 | Deterministic rules then OR-Tools CP-SAT in the asynchronous jobs worker, with a time limit, explanations, alternatives, infeasibility reasons and an input checksum (FR-020, FR-021); food rules per country as versioned data (FR-017) | Allocation becomes reproducible and explainable |
| Approval | Not available | A proposal is executed only when a coordinator confirms its content hash; deterministic code reserves the offer, creates the mission and notifies in one transaction (FR-016, FR-022) | AI and solver propose, people decide |
| Missions | Planned for P1 | Life cycle assigned → accepted → picked_up → delivered, failure with reason, reassignment without duplicates, centre receipt or exception, idempotency keys, guards in the database (FR-023, FR-025, FR-027) | FL-01 completes end to end |
| Notifications | Planned for P1 | In-app notifications per recipient; mission emails through an outbox, a notifier with no data access, Cognito and Amazon SES, DLQ on failure (FR-026) | Volunteers learn about missions within a minute, without beneficiary data in any message |
| Dashboard | Not available | Aggregated operational dashboard: offers, missions, kg received, rates, time to allocation, proposals, centre capacity, categories (FR-052, FR-053) | Measure OBJ-01..OBJ-04 without identifying anyone |
| Membership | Donors and NGOs self-register | Volunteers, centre staff and coordinators also request to join a network; its admin approves, centre staff for one centre (ADR-017) | The operational roles can exist on a real deployment |

### v0.4

| Area | v0.3 | v0.4 | Why |
|---|---|---|---|
| Name | AidOS | **SecondChance**: a second chance for food that would otherwise be thrown away | A name that says what the product does |
| Languages | Italian interface and documents; retrieval in Italian, English, Danish | English as source and default; interface in English, Danish, Polish and Italian with a visible language picker; retrieval and intent router in the same four languages (FR-046, FR-064) | An international product for networks in Denmark, Poland and Italy (ADR-019) |

### v0.3

| Area | v0.2 | v0.3 | Why |
|---|---|---|---|
| Access | Users created by administrators | Registration from the web app as a donor or as an NGO, approved by whoever runs the network; screens per role (FR-006, FR-007) | The platform is public: newcomers must be able to introduce themselves, but not grant themselves access (ADR-017) |
| Robustness | Validation inside the endpoints | Staged admission control: every unsuitable or malformed request is rejected at the first stage that can recognise it (FR-036, NFR-027) | Useless load must not reach database, queues and models (ADR-016) |
| Knowledge | Minimal RAG as a Should | Knowledge service with spaces and role ACLs, autonomous PDF ingestion, multilingual hybrid search, `/assist` with an intent router (FR-037, FR-047, FR-048) | The "Intelligent Knowledge & Multi-Agent Orchestration" v0.2.0 specification, adapted to the existing architecture (ADR-015) |
| Agents | Out of the MVP | Stateless supervisor and specialists on a queue, shared memory with scope and TTL, per-run budgets (FR-038) | Needed for compound requests, without giving up control of the workflows (ADR-010, ADR-011) |
| Experimentation | Not planned | A/B experiments in the database, deterministic assignment, kill switch (FR-039) | Compare prompts, models and routers on real data (ADR-013) |
| Deployment | Terraform planned for P4 | Complete Terraform, `scripts/deploy.sh` configuring the account from scratch, temporary credentials only (NFR-014) | Go to production with one command and no keys to guard (ADR-018) |

### v0.2

| Area | v0.1 | v0.2 | Why |
|---|---|---|---|
| Cloud | AWS optional, Kubernetes as the production reference | Serverless AWS as the only cloud target; Kubernetes out of the MVP | Near-zero fixed cost at rest, one maintainer (ADR-001) |
| MVP scope | 7 phases, advanced AI before the pilot | MVP = operational core + optimisation + minimal RAG. Forecasting, MCP and router benchmark after the pilot | Show end-to-end value before complexity |
| Workflow | LangGraph with state and checkpoints | Workflow state in the database (state machine + idempotency keys), asynchronous work on SQS with DLQs | FL-01 is deterministic; the database is already the source of truth (ADR-005) |
| Multi-tenancy | Open decision | Multi-tenant from day one with PostgreSQL Row-Level Security | Adding it later means rewriting queries and tests (ADR-003) |
| RAG | Custom stack with a generic vector store | PostgreSQL FTS + pgvector in the same Aurora, ACL enforced by the database | One store, isolation guaranteed by RLS, identical locally (ADR-004) |
| Rizzo Flow | Router mentioned without a definition | Open-source typed-decision engine (Rizzo AI Academy) as a second `DecisionRouter` implementation, in shadow mode next to the baseline, off by default | Measure it on real requests without putting it on the critical path (ADR-007) |
| New requirements | — | Atomic reservation, notifications, PWA for volunteers, food rules per country, expiry date type, AI Act classification | Gaps found when re-reading the flows |

**v0.2.1:** corrected the description of Rizzo Flow, which v0.2.0 presented as a project by the author. It is an open-source project by Rizzo AI Academy, integrated in shadow mode (ADR-007, FR-030, FR-031).

## 1. Executive summary

**SecondChance** is a source-available platform that helps NGOs, food banks and volunteer organisations find, plan and distribute essential resources to communities in need.

The product combines traceable operations management with **AI/ML** capabilities: document search with verifiable sources (RAG), interpretation of requests, donation-to-centre matching suggestions and logistics optimisation. Demand forecasting comes after the pilot, once there is real data to measure it on. **Decisions that affect access to aid remain a human responsibility.**

The first implementation focuses on **surplus food**: a donor makes food available, an organisation assesses whether it is suitable, and the system proposes an allocation and, if needed, a pickup and delivery route. Later the platform can extend to clothing, hygiene kits and other essential goods.

## 2. Mission and goals

### 2.1 Mission

Reduce waste and improve access to essential aid by giving non-profit organisations transparent, affordable, interoperable and verifiable tools to coordinate limited resources.

### 2.2 Product goals

| ID | Goal | Success indicator in the pilot |
|---|---|---|
| OBJ-01 | Reduce the time needed to match a donation with a centre | Median allocation time compared with the manual reference process |
| OBJ-02 | Make better use of the surplus offered | Share of donations collected or delivered before they expire |
| OBJ-03 | Increase operational transparency | Share of allocations with a verifiable reason, operator and timestamp |
| OBJ-04 | Simplify the volunteers' work | Time spent planning a mission and number of manual interventions |
| OBJ-05 | Provide reliable AI recommendations | Accuracy of cited information and share of suggestions approved by operators |
| OBJ-06 | Make adoption easy for NGOs | Documented, working installation without mandatory proprietary services |

**Note:** no social results are claimed before a verified pilot. Metrics must be measured on authorised data and compared with a baseline.

### 2.3 Non-goals (MVP)

- It does not decide automatically who receives aid and who does not.
- It does not build individual vulnerability profiles or score people in need.
- It does not replace operators, social services, emergency services or official food-safety guidance.
- It does not handle payments, monetary donations, health procedures or clinical data.
- It does not assume active integrations with real NGOs before agreements and validation.
- It does not guarantee real-time availability of external resources without an up-to-date, authorised source.
- It uses no expensive always-on infrastructure: no Kubernetes clusters, self-hosted GPUs or permanent NAT Gateways.
- It does not forecast demand on synthetic data: a forecast without real history proves nothing.

## 3. Users and stakeholders

| Role | Main need | Indicative permissions |
|---|---|---|
| Donor (shop, canteen, restaurant) | Register surplus food and pickup availability | Manages only its own offers |
| NGO operator / coordinator | Review offers and aggregated needs, propose allocations | Manages its own organisation and approves allocations |
| Volunteer | See and update assigned missions, often from a phone | Minimal access to assigned missions |
| Receiving centre | State capacity, accepted goods and time slots | Manages only its own centre |
| Organisation administrator | Manage members, roles, configuration and audit | Administration limited to the organisation |
| Platform administrator | Maintenance and security | Controlled and audited privileged access |
| Final beneficiary | Receive aid through the responsible organisations | No personal account in the MVP |

**Multi-tenancy (decided in v0.2, ADR-003):** *pooled* model. One database; every domain table has `tenant_id` and a Row-Level Security policy. Every transaction sets `app.tenant_id` from the user's active membership, so a query without a filter still sees no rows of other organisations. Sharing between organisations goes through explicit permissions recorded in an agreements table, also protected by RLS.

## 4. End-to-end flows

### FL-01 — Food donation

1. An authenticated donor creates an offer with category, quantity, pickup window, date type and expiry (`use_by` / `best_before`), and storage conditions.
2. The backend validates fields, format, offer ownership and the country's food rules (FR-017).
3. The coordinator sees the offers compatible with the centres' capacity and needs.
4. The coordinator starts a matching run; an asynchronous worker (OR-Tools) proposes matches with explanations, satisfied constraints and alternatives.
5. An operator **approves** or changes the proposal. Approval reserves the offer atomically: if another coordinator has already reserved it, they get a conflict (FR-016).
6. The authorised volunteer receives a notification (email and in-app) and a mission with minimal details, and updates its status, also from a phone.
7. The centre confirms receipt or records an exception.
8. The system keeps events, reasons and aggregated indicators for audit and measurement.

### FL-02 — Assisted search for coordinators

1. The operator asks: "What is the procedure for receiving chilled food?" — in English, Danish, Polish or Italian.
2. The platform sets the user's tenant and role on the transaction **before** retrieval; RLS limits the visible chunks.
3. It runs hybrid search (PostgreSQL FTS + pgvector), RRF fusion and, if enabled, reranking.
4. If the retrieved evidence is below the threshold, the system abstains without calling the model.
5. The LLM (Amazon Bedrock) answers citing document and version; a guardrail with *contextual grounding* blocks answers not grounded in the sources, and in that case the system also abstains and suggests checking with a contact person.

### FL-03 — Forecasting and planning (after the pilot)

1. The coordinator opens a dashboard for a region and a time window.
2. The ML module processes aggregated time series and authorised context data.
3. The system shows a forecast with uncertainty intervals and model quality.
4. Operational recommendations are proposed for review, never executed automatically.

This flow starts only when the pilot has produced enough real history for a backtest.

## 5. Functional requirements

Priority: **Must** = essential for the MVP; **Should** = next iteration; **Could** = later evolution.

### 5.1 Identity, tenants and governance

| ID | Priority | Requirement | Acceptance criterion |
|---|---|---|---|
| FR-001 | Must | OIDC authentication for operators, donors and volunteers (Amazon Cognito; passwordless email sign-in for volunteers) | Protected endpoints reject missing, invalid or expired tokens |
| FR-002 | Must | RBAC per role and tenant with least privilege; tenant isolation enforced by RLS | Cross-tenant and privilege-escalation tests get access denied, even with unfiltered queries |
| FR-003 | Must | Management of organisations, centres and members | An organisation administrator manages users and centres of their own tenant only |
| FR-004 | Must | Audit of sensitive operations and approvals in an append-only table | Every relevant action has actor, timestamp, tenant, object, outcome and correlation ID; UPDATE and DELETE on the audit table are denied to the application role |
| FR-005 | Should | Authorised sharing of offers between organisations | Sharing needs explicit consent or configuration and leaves a trace |
| FR-006 | Must | Registration from the web app as a donor (joining an existing network) or as an NGO (new network). The request stays `pending` until a network or platform administrator approves it | Nobody can approve themselves or pick a role other than the one requested; escalation tests |
| FR-007 | Must | Screens per role, derived from the capabilities returned by `/me` | Every role sees only its allowed features; the backend still rejects out-of-role calls |

### 5.2 Donations and resources

| ID | Priority | Requirement | Acceptance criterion |
|---|---|---|---|
| FR-010 | Must | CRUD of donation offers | The owner creates, edits and withdraws their own offers with server-side validation |
| FR-011 | Must | Catalogue of categories, units, quantities and time windows | Incomplete data or inconsistent units fail validation |
| FR-012 | Must | Record date type (`use_by`, `best_before`), expiry, conditions and cold chain | Expired `use_by` products or products out of temperature are excluded from suggestions; `best_before` products past the date are allowed only if the country rule permits it |
| FR-013 | Must | Offer status: draft, available, reserved, collected, delivered, expired, cancelled | Every transition is validated and traced |
| FR-014 | Must | Capacity and acceptance slots of receiving centres | The optimiser respects the configured constraints |
| FR-015 | Should | Attachments and proofs of delivery with retention (S3, short-lived presigned URLs) | Validated uploads, accessible only to authorised roles |
| FR-016 | Must | Atomic offer reservation (optimistic version control) | Two concurrent reservations of the same offer: one succeeds, the other gets 409 Conflict; no quantity reserved twice |
| FR-017 | Must | Food-safety rules as versioned configuration per country | Every rule has a source, version and date; changing it needs no deployment; tests for at least two countries (e.g. DK and PL) |

**Domain note:** under the EU guidelines on food donation, products with a "use by" date must not be distributed after that date, while "best before" products may be if intact and correctly stored. National rules must be validated with the competent authority before the pilot.

### 5.3 Logistics coordination

| ID | Priority | Requirement | Acceptance criterion |
|---|---|---|---|
| FR-020 | Must | Suggest donation-to-centre matches with deterministic rules | Every suggestion lists the conditions and constraints it satisfies |
| FR-021 | Must | Allocation optimisation with OR-Tools in an asynchronous worker, with a solver time limit | With fixed inputs and constraints, reproducible results or an infeasibility explanation |
| FR-022 | Must | Human approval before confirming allocations | No AI proposal can create an active mission without authorised approval |
| FR-023 | Must | Mission life cycle: assigned, accepted, picked_up, delivered, failed | Authorised, idempotent and auditable transitions |
| FR-024 | Should | Multi-stop optimisation for volunteers | Routes respect capacity, time windows and availability |
| FR-025 | Should | Exception handling and reassignment | A failure can be handled without duplicating missions |
| FR-026 | Must | Mission notifications to volunteers (email via Amazon SES + in-app) | Notification within 1 minute of approval; no beneficiary data in the message; failures end up in a DLQ |
| FR-027 | Should | PWA for volunteers with offline access to assigned missions and an update queue | Updates made offline are applied exactly once thanks to idempotency keys |

**Distances:** in the MVP distances come from PostGIS (straight line with a correction factor). A road travel-time matrix (Amazon Location Service) comes in as an adapter when FR-024 needs it.

### 5.4 AI orchestration and integrations

| ID | Priority | Requirement | Acceptance criterion |
|---|---|---|---|
| FR-030 | Must | Request classification and routing to the right workflow behind the `DecisionRouter` interface (rules baseline + classifier), escalating to an operator when the decision is uncertain | Evaluation on a golden set with a report per language and class. Every decision records router, class, probability and outcome, as metadata only (ADR-008) |
| FR-031 | Could | [Rizzo Flow](https://github.com/Rizzo-AI-Academy/rizzo-flow) (open source, Rizzo AI Academy) as a second `DecisionRouter` implementation in shadow mode, then a benchmark against an ML classifier and LLM routers | Shadow mode runs outside the request path, has no effect on users and its flag is off by default. Reproducible benchmark with macro-F1, escalation recall, calibration, p95 latency and costs. It becomes the default router only through a new ADR (criteria in ADR-007) |
| FR-032 | Must | Durable operational workflows: state in the database, asynchronous work on a queue with a DLQ | An interrupted workflow resumes without repeating actions (idempotency keys, conditional transitions) |
| FR-033 | Could | Authorised MCP tools (catalogue, availability, missions), e.g. through Bedrock AgentCore Gateway | Contract tests for schema, authN/authZ, timeouts and rate limits |
| FR-034 | Must | Tool calls read-only by default; writes need explicit confirmation | A test shows that no unapproved change happens |
| FR-035 | Should | LLM adapter with fallback: Bedrock in the cloud, Ollama locally | Fallback and controlled degradation (abstention) when the provider does not answer |
| FR-036 | Must | Staged admission control: body size, strict schema, role, per-tenant quotas, unsupported intents, invalid PDFs, malformed queue messages | Every rejection happens before the next stage is touched, with an explicit HTTP status and reason, and is counted in `secondchance.admission.rejections` |
| FR-037 | Must | `POST /assist`: the intent router picks the cheapest path (knowledge search, direct operation, single agent, several agents, clarification, refusal) | Vague requests get a clarification question and unsupported ones stop without calling any model |
| FR-038 | Should | Stateless agents (supervisor and specialists) on a queue, with shared memory per run, conversation and tenant, and step and token budgets | An interrupted worker resumes without repeating steps; when the budget runs out the run stops with an explicit status |
| FR-039 | Should | A/B experiments with deterministic assignment, opt-in and kill switch | Same user, same variant; exposures recorded without personal data |

### 5.5 Document intelligence and RAG

| ID | Priority | Requirement | Acceptance criterion |
|---|---|---|---|
| FR-040 | Should | Ingestion of authorised procedures and documents from S3, with metadata and versions | Idempotent re-ingestion; updates and removals reconciled |
| FR-041 | Should | Parsing, section-aware chunking and deduplication | Every chunk can be traced back to document, tenant and version |
| FR-042 | Should | Hybrid retrieval FTS + pgvector, RRF fusion, optional reranking | Repeatable retrieval benchmark on golden queries; the reranker stays only if it improves hit@k |
| FR-043 | Must if RAG is on | ACL filter before retrieval, enforced by RLS | Zero leakage in negative ACL tests |
| FR-044 | Must if RAG is on | Grounded answers with verifiable citations (Bedrock Guardrails, contextual grounding) | Every relevant factual statement points to a source that was actually retrieved |
| FR-045 | Must if RAG is on | Abstention when evidence is insufficient | Tests on unanswerable requests produce no invented information |
| FR-046 | Should | Multilingual documents and questions: English, Danish, Polish and Italian | Separate test sets per language; Polish lexical search works without a stemmer (ADR-019) |
| FR-047 | Must if RAG is on | Knowledge spaces per tenant or public, with allowed roles enforced by RLS | An excluded role does not find the space's documents, not even in search |
| FR-048 | Should | Autonomous PDF ingestion: validated upload, parsing, chunking, embeddings and atomic publication in the background | An invalid PDF is rejected at upload; a new version replaces the previous one only when it is complete |
| FR-049 | Could | MCP gateway to the authorised tools, with the same rules as FR-034 | Contract tests and audit of every call |

### 5.6 ML, analytics and impact monitoring

| ID | Priority | Requirement | Acceptance criterion |
|---|---|---|---|
| FR-050 | Could (after the pilot) | Aggregated demand forecast per category and area | Temporal backtest on real data, comparison with a seasonal baseline and uncertainty intervals |
| FR-051 | Could (after the pilot) | Model and dataset versions (artefacts on S3 + metadata table; MLflow only if needed) | Every forecast stores model and dataset versions |
| FR-052 | Must | Dashboard of offers, missions and aggregated results | Figures consistent with domain events and tenant-aware filters |
| FR-053 | Must | Social metrics without identifying individual beneficiaries | Aggregated reports expose no unnecessary personal data |
| FR-054 | Could | Drift monitoring and governed retraining | Threshold-based alerts and review before release |

### 5.7 Accessibility, languages and community

| ID | Priority | Requirement | Acceptance criterion |
|---|---|---|---|
| FR-060 | Must | Responsive, accessible interface | Keyboard navigation and automated and manual accessibility tests |
| FR-061 | Must | Self-hosted local deployment | Start from the repository with synthetic demo data and verifiable instructions |
| FR-062 | Must | Documented API (OpenAPI) and versioned schema | Generated OpenAPI and contract tests in CI |
| FR-063 | Should | Contributor documentation and architecture decision records | CONTRIBUTING, SECURITY, governance, ADRs and roadmap available |
| FR-064 | Must | Interface in English, Danish, Polish and Italian, English by default, language picker on every page | A missing translation fails the build; the choice is remembered; dates, numbers and country names follow the chosen language |

## 6. Non-functional requirements

The thresholds below are **MVP acceptance targets**, to be confirmed by benchmarks; they are not measured performance.

| ID | Category | Requirement / target | Verification |
|---|---|---|---|
| NFR-001 | Security | TLS 1.2+ in transit; encryption at rest (KMS) for Aurora, S3 and queues | Configuration audit and TLS tests |
| NFR-002 | Identity | OIDC/JWT with expiry, issuer and audience verified by the API Gateway JWT authorizer; least-privilege IAM role per function | Integration and negative security tests |
| NFR-003 | Tenant isolation | No data of tenant A reachable by tenant B, retrieval, caches and logs included | Cross-tenant test suite against RLS |
| NFR-004 | Privacy | Data minimisation, defined purposes, configurable retention, export and delete procedures | Privacy review and erasure tests |
| NFR-005 | Compliance | GDPR by design, data and inference in EU regions (`eu.` inference profile); DPIA when needed before real processing | Checklist and governance approval |
| NFR-006 | Reliability | Idempotent writes; retries with backoff and dead-letter queues for asynchronous events | Fault-injection tests |
| NFR-007 | API performance | p95 < 500 ms for simple CRUD reads with 50 concurrent users in the defined test environment, with the database awake | k6/Locust, excluding external round trips and resume from pause |
| NFR-008 | AI performance | p95 < 10 s per RAG answer in a documented benchmark environment | Fixed dataset, declared region and model |
| NFR-009 | Availability | 99.5% monthly target for a managed pilot; **not applicable to the demo** | SLI/SLO and incident review |
| NFR-010 | Scalability | Stateless API functions; queues for heavy tasks; Lambda reserved concurrency sized on database connections | Load test |
| NFR-011 | Observability | Structured logs, traces, metrics, correlation ID (OpenTelemetry everywhere; X-Ray and CloudWatch on AWS) | Dashboards and alerts |
| NFR-012 | Auditability | Evidence of changes, approvals and AI output without storing sensitive prompts in plain text: the app records metadata (model, tokens, latency, guardrail outcome, cited sources), not the text | Audit trail verification |
| NFR-013 | Portability | The domain core runs in Docker Compose without AWS; AWS services are adapters (Bedrock ↔ Ollama, SQS ↔ ElasticMQ, S3 ↔ SeaweedFS, Cognito ↔ mock OIDC) | Documented local installation and CI tests on both |
| NFR-014 | Deployability | CI with lint, unit, integration and security tests, SBOM, image scanning and IaC scanning; deployment with GitHub OIDC → AWS, no access keys | Mandatory green pipeline |
| NFR-015 | Versioning | SemVer for the API, versioned database migrations, immutable image tags and rollback | Upgrade and downgrade tests |
| NFR-016 | Maintainability | Separate modules for domain, AI, ML, integrations and infrastructure | Code review and architectural tests |
| NFR-017 | LLM resilience | Timeouts, retries with backoff, fallback or abstention on external failures | Unavailability simulation |
| NFR-018 | AI security | Guardrails against prompt injection and ungrounded output, confirmed write tools, authorisation outside the model | Red team and regression suite |
| NFR-019 | RAG quality | Faithfulness target >= 95%; citation correctness >= 90% on the golden set, per language | Versioned evaluation harness |
| NFR-020 | Routing quality | Macro-F1 target >= 0.90 on a balanced dataset and high recall for escalation classes | Holdout + confusion matrix |
| NFR-021 | ML quality | (after the pilot) Forecasting model better than the seasonal baseline on the temporal backtest | MAE/WAPE and calibrated intervals |
| NFR-022 | Accessibility | WCAG 2.2 AA target for the main interfaces | axe + manual audit |
| NFR-023 | Cost | AWS demo created and destroyed with one command; fixed cost at rest close to zero (Aurora paused, no NAT, no cluster) | Cost review, `terraform destroy` and check for leftover services |
| NFR-024 | Supply chain | Secrets never in Git; secret scanning, dependency pinning, verified licences | CI gates and dependency review |
| NFR-025 | Backup and recovery | Encrypted backups and tested restores for environments holding real data | Restore drill and RPO/RTO defined before the pilot |
| NFR-026 | AI Act | Documented system classification: SecondChance does not decide access to benefits, so the goal is to stay out of high risk; transparency obligations of art. 50 (users know they are talking to an AI) | Classification ADR reviewed at every scope change |
| NFR-027 | Overload protection | Rejection at the first possible stage (WAF, API Gateway throttling, middleware, schema, quotas, router); workers with bounded concurrency and DLQs | Admission tests for every stage; no malformed message retried forever |

**Cost constraint:** AWS Budgets on a paid account **does not guarantee** a hard stop of billing. For a "never spend more than a fixed amount" requirement, use only local resources or a plan that really has no automatic charges (e.g. the AWS Free Plan if eligible and without upgrading); do not treat budget alerts as absolute protection. The demo follows the *ephemeral* model: `terraform apply` before the session, `terraform destroy` after.

## 7. Reference architecture on AWS

Region: `eu-central-1` (Frankfurt), with the `eu.` inference profile for Bedrock (ADR-002). The current view, with agents, knowledge service and admission control, is in [architecture.md](architecture.md); the map of AWS services and their local equivalents is in [`infra/README.md`](../infra/README.md). Detailed diagrams in [`diagrams/`](diagrams/).

### 7.1 Architectural principles

1. **Human-in-control:** AI proposes; authorised users confirm operational actions.
2. **Security before retrieval:** authentication, authorisation and tenant filtering happen before data access, in the database itself (RLS).
3. **Fail fast:** whatever cannot be served is rejected at the cheapest stage that can recognise it.
4. **Deterministic core first:** availability, storage and logistics constraints are software rules, not conclusions left to the LLM alone.
5. **AI modularity:** routers, models and retrieval behind interfaces that can be swapped without rewriting the domain.
6. **Open standards:** OpenAPI, OIDC, OpenTelemetry, Docker/OCI; MCP when tools arrive.
7. **Cost-aware architecture:** serverless with scale to zero, an ephemeral demo, no expensive always-on component in the MVP.
8. **Verifiable outcomes:** reproducible metrics and benchmarks, with explicit limits.

### 7.2 Application stack

- **Frontend:** React, TypeScript, typed dictionaries for four languages and the browser `Intl` API; MapLibre optional.
- **Backend:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy, Alembic.
- **Data:** PostgreSQL, PostGIS, pgvector, FTS; S3 (SeaweedFS locally).
- **AI:** Anthropic SDK towards Bedrock behind an adapter (Ollama locally), Titan Text Embeddings V2, Guardrails; custom retrieval FTS + dense + RRF with citations; Rizzo Flow as an experimental `DecisionRouter` implementation in shadow mode.
- **Optimisation:** OR-Tools with explicit constraints and readable explanations.
- **Quality:** pytest, Vitest, k6, axe, versioned RAG and routing evaluation harness.
- **Out of the MVP:** Kubernetes, Helm, vLLM/llama.cpp, LangGraph, MLflow, Langfuse. Grafana only locally (`otel-lgtm`); MCP gateway as FR-049. They come back only with a requirement that justifies them.

## 8. Datasets and experimentation strategy

### 8.1 MVP

- Seed with **synthetic organisations, centres, volunteers and donations**, including edge cases and failures (concurrent offers, broken cold chain, full centres), and sample documents in the four supported languages.
- Public geographic data with licence and attribution checks where applicable.
- No real beneficiary data collected during development.
- Regulatory or procedural documents only if public or authorised, with URL, version and acquisition date.

### 8.2 Real pilot

- Partnership and organisational consent before ingesting internal data.
- Definition of controller and processor roles, purposes, retention and access.
- GDPR assessment and DPIA where needed.
- Measurement against a manual baseline and operator feedback.

## 9. Delivery plan

Status: **P0, P1 and P2 done**: registration for every role, offers, centres with capacity and slots, atomic reservation, OR-Tools matching with human approval, missions, notifications, dashboard and audit. **P3** (knowledge, ingestion, `/assist`) is implemented. **P4**: complete Terraform, one-command deployment (`connect-aws`) with account preflight and post-deployment verification, observability and offline infrastructure tests. The agent layer (ADR-010) has its durable runtime, memory, governed specialists and LLM supervisor. Next: multi-stop routes (FR-024), the volunteer PWA (FR-027), the pilot (P5).

| Phase | Scope | Deliverable | Exit criteria |
|---|---|---|---|
| P0 — Foundation | Monorepo, Docker Compose, data schema with RLS, local OIDC, CI, Terraform skeleton | API and demo seed | Reproducible setup from scratch; green cross-tenant tests |
| P1 — Core operations | Offers, centres, missions, approvals, atomic reservation, audit, notifications | MVP without AI | FL-01 complete and tested locally |
| P2 — Optimisation | Deterministic matching and OR-Tools in the asynchronous worker | Suggested allocations with explanations | No mission without approval |
| P3 — RAG | Ingestion, ACL-aware hybrid retrieval, Bedrock + Guardrails, abstention | Assistant with citations | Golden set and negative ACL tests green |
| P4 — Cloud demo | Complete AWS Terraform, observability, load and security tests | Ephemeral demo on AWS | `apply`/`destroy` verified, cost review |
| P5 — Pilot | Interviews and collaboration with NGOs | Preliminary impact report | Field evidence, no unsupported claims |
| P6 — Advanced AI | Rizzo Flow benchmark (golden set + shadow-mode data), forecasting on pilot data, MCP tools | Technical report with baselines | Published metrics and failure modes |

## 10. Definition of Done (MVP)

- [x] A donor can create a valid, traced offer.
- [x] A centre can communicate availability and constraints.
- [x] A coordinator sees the suggestions and can approve or reject them.
- [x] Two concurrent approvals of the same offer do not produce double reservations.
- [x] The volunteer receives the notification and can update only assigned missions.
- [x] Every critical change produces an audit event.
- [x] Tenant isolation and RBAC tests are green.
- [x] The complete flow works with synthetic data and without any LLM.
- [x] The AI module, if enabled, cannot bypass approvals.
- [x] OpenAPI, README, SECURITY, CONTRIBUTING, ADRs and setup documentation are published.
- [x] CI/CD and automated tests are reproducible.
- [x] Self-hosted demo that starts without AWS and with zero cloud costs.
- [x] AWS demo created and destroyed with one command, with no paid leftovers.
- [x] Every screen available in English, Danish, Polish and Italian.

## 11. KPIs for portfolio and hiring managers

**Product KPIs:** offers published, offers completed, kilograms of food recovered (only if measured), median allocation time, mission failure rate, undelivered resources.

**Engineering KPIs:** p95 latency, throughput, error rate, availability per environment, load test results, cost per workflow, test coverage, number and severity of security issues fixed.

**AI/ML KPIs:** retrieval hit@k, citation correctness, faithfulness, correct abstention rate, classification macro-F1, escalation recall, cost per 1,000 requests, optimisation quality — each per language.

**Public artefacts:** architecture diagrams, ADRs, threat model, API contracts, IaC, runbooks, test reports, routing benchmark, synthetic evaluation dataset and a technical case study with real (not invented) results.

## 12. Risks, dependencies and mitigations

| Risk | Mitigation |
|---|---|
| No partners or real data | Start with a synthetic MVP; run validation interviews before the pilot |
| Wrong AI suggestions | Deterministic rules, human approval, evidence and logging |
| Access breaches between NGOs | RLS in the database, RBAC and automated negative tests |
| Wrong food information | Versioned country rules with sources, conservative constraints and validation by competent operators |
| Biased or incomplete datasets | Data quality analysis, baselines and explicit uncertainty |
| Excessive complexity | Operational core before RAG/ML and agents; feature flags; reduced stack (section 7.2) |
| Unexpected AWS costs | Ephemeral demo, no NAT Gateway, Aurora paused, budget alerts as a warning (not a block) |
| Aurora resuming from pause (seconds) | Accepted in the demo; minimum capacity > 0 in the pilot |
| Lambda exhausting database connections | RDS Proxy in every AWS environment, bounded pool and reserved concurrency where quotas allow it |
| Dependence on paid services | Self-hosted core, optional cloud adapters, ephemeral deployment |
| Experimental APIs and technologies (Rizzo Flow included) | Spikes, shadow mode, benchmarks, feature flags, fallbacks and provider abstraction |
| Weaker quality in some languages | Per-language golden sets; Polish without a stemmer relies on dense retrieval until an ispell dictionary is justified |

## 13. Decisions

### 13.1 Taken in v0.2

1. **Cloud:** serverless AWS in `eu-central-1` (ADR-001, ADR-002).
2. **Organisation model:** pooled multi-tenancy with RLS from the first release (ADR-003).
3. **Retrieval:** Aurora pgvector + FTS, no separate vector store (ADR-004).
4. **Workflow:** domain state in the database; Step Functions Standard coordinates bounded agent steps on AWS, while SQS carries ingestion and delivery events (ADR-005).
5. **Rizzo Flow:** second `DecisionRouter` implementation, in shadow mode and behind a flag; routing only, never food rules or decisions about people (ADR-007).

### 13.2 Taken in v0.3

1. **Agents:** stateless supervisor and specialists inside the deterministic workflows, never instead of them (ADR-010); shared memory in the database with scope and TTL (ADR-011).
2. **Observability:** OpenTelemetry everywhere, the same code locally and on AWS (ADR-012). **Experiments:** in the database, no external services (ADR-013). **Privacy:** every column classified and automatic retention (ADR-014).
3. **Knowledge and intent router:** the v0.2.0 specification enters adapted, with the substitutions justified in ADR-015.
4. **Fail fast:** ten-stage admission control (ADR-016). **Identity:** the token proves who you are, SecondChance decides what you may do (ADR-017).
5. **Deployment:** Terraform, IAM Identity Center for people, OIDC for CI, no access keys (ADR-018).

### 13.3 Taken in v0.4

1. **Name:** SecondChance.
2. **Languages:** English first; interface, retrieval and intent router also in Danish, Polish and Italian (ADR-019).

### 13.4 Still open

1. **Pilot geography:** Denmark, Poland or Italy, or an international scenario on synthetic datasets.
2. **First partner:** food bank, redistribution NGO or volunteer association.
3. **Public deployment mode:** synthetic demo only, or a restricted pilot with authorised users.
4. **Licence governance:** check that every model, dataset and dependency allows redistribution under PolyForm Noncommercial and the author's commercial licences (ADR-020).
5. **AWS account:** Free Plan (credits, no charges without upgrading) or paid; check that Bedrock and Aurora are usable on the chosen plan.

---

## 14. One-line pitch

> **SecondChance is a source-available, human-governed humanitarian operations platform combining resource coordination, constrained optimisation and evidence-grounded AI to help non-profits give surplus food a second chance.**

**Positioning:** a portfolio piece and a concrete social product, with an enterprise-grade architecture demonstrated through code, tests, benchmarks, security and verifiable metrics.
