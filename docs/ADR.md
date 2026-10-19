# SecondChance — Architecture Decision Records

Short format: context, decision, rejected alternatives, consequences. Status: ADR-001…009 **accepted in v0.2**, ADR-010…019 **accepted in v0.3**, ADR-020 **accepted at the starting point**, ADR-021 **accepted in v0.5**, all to be reviewed after the pilot.

| ADR | Topic | ADR | Topic |
|---|---|---|---|
| [001](#adr-001--aws-serverless-instead-of-kubernetes) | AWS serverless | [011](#adr-011--shared-memory-and-storage-across-services-and-agents) | Shared memory and storage |
| [002](#adr-002--region-eu-central-1-with-the-eu-inference-profile) | EU region and inference | [012](#adr-012--observability-with-opentelemetry-same-code-locally-and-on-aws) | Observability |
| [003](#adr-003--pooled-multi-tenancy-with-row-level-security) | Multi-tenancy with RLS | [013](#adr-013--feature-flags-and-ab-experiments-in-the-database) | Feature flags and A/B |
| [004](#adr-004--rag-on-aurora-pgvector--fts-instead-of-bedrock-knowledge-bases) | RAG on Aurora | [014](#adr-014--privacy-by-design-gdpr) | Privacy (GDPR) |
| [005](#adr-005--workflow-state-in-the-database-asynchronous-work-on-sqs) | Workflows in the DB + SQS | [015](#adr-015--knowledge-service-and-intent-router) | Knowledge and intent router |
| [006](#adr-006--network-lambda-in-a-vpc-with-endpoints-no-nat-no-rds-proxy-in-the-demo) | Network without NAT | [016](#adr-016--fail-fast-early-rejection-and-admission-control) | Fail fast |
| [007](#adr-007--rizzo-flow-as-an-experimental-decisionrouter-in-shadow-mode) | Rizzo Flow in shadow mode | [017](#adr-017--identity-registration-and-authorisation-authn-in-the-idp-authz-in-secondchance) | Identity and registration |
| [008](#adr-008--ai-logs-metadata-yes-plain-text-prompts-no) | AI logs | [018](#adr-018--aws-deployment-terraform-no-access-keys-self-configuration) | AWS deployment and credentials |
| [009](#adr-009--ai-act-classification) | AI Act | [019](#adr-019--internationalisation-english-first-then-danish-polish-and-italian) | Languages |
| [010](#adr-010--agent-layer-stateless-supervisor-and-specialists-inside-deterministic-workflows) | Agent layer | [020](#adr-020--licence-polyform-noncommercial-commercial-use-by-agreement) | Licence |
| | | [021](#adr-021--operations-or-tools-proposals-bound-to-a-hash-missions-and-a-notification-outbox) | Matching, approval, missions, notifications |

The choices were checked against the AWS Well-Architected Framework with the Generative AI Lens. Prices and model availability per region change often: check them in the AWS Pricing Calculator and the Bedrock documentation before every deployment.

---

## ADR-001 — AWS serverless instead of Kubernetes

**Context.** One maintainer, a budget close to zero, low and spiky traffic (pickup hours). v0.1 named Kubernetes as the production reference.

**Decision.** Lambda (API and workers) behind API Gateway HTTP API, Aurora PostgreSQL Serverless v2, SQS, S3, CloudFront, Cognito. The same container image runs in Lambda (through the Lambda Web Adapter) and in Docker Compose.

**Rejected alternatives.**
- *EKS*: the control plane alone costs about $0.10/h (~$73/month) before any node; cluster operations are out of proportion for a team of one.
- *ECS Fargate + ALB*: sound, but an always-on ALB and tasks cost money even at zero traffic. It becomes the right option if the pilot brings steady load or requests longer than the API Gateway timeout (30 s).

**Consequences.** Near-zero cost at rest, simple deployment. Limits to manage: cold starts, the 30 s API Gateway timeout (long computations go to workers), database connections to keep under control (ADR-006).

---

## ADR-002 — Region `eu-central-1` with the `eu.` inference profile

**Context.** GDPR: data and inference must stay in the EU. The pilot is likely to be in Denmark.

**Decision.** Home region Frankfurt (`eu-central-1`). Bedrock calls use the `eu.` cross-region inference profiles, which route traffic only between EU regions.

**Rejected alternatives.**
- *`eu-north-1` (Stockholm)*: closer to Copenhagen, but the latency difference is irrelevant for this load and the local Bedrock catalogue is smaller.
- *`global.` profiles*: they leave the EU.

**Consequences.** For every chosen model (Claude Haiku, Titan Embeddings V2, any reranker), check that it is available in `eu-central-1` or through the `eu.` profile. Logs and buckets stay in the region.

---

## ADR-003 — Pooled multi-tenancy with Row-Level Security

**Context.** Many NGOs on the same platform; the most serious risk is leakage between organisations (NFR-003), retrieval included. v0.1 left single- versus multi-tenant open.

**Decision.** One database, `tenant_id` on every domain table, RLS policies comparing `tenant_id` with `current_setting('app.tenant_id')`. Every request opens a transaction and sets `app.tenant_id` and `app.role` with `SET LOCAL`. The application role does not own the tables and has no `BYPASSRLS`. Migrations run with a separate role.

**Rejected alternatives.**
- *`WHERE tenant_id = ?` in code only*: one forgotten query is a leak.
- *A database or schema per tenant*: stronger isolation, but multiplied costs and migrations; out of proportion before there are more than a handful of organisations.

**Consequences.** Isolation also applies to vector retrieval (ADR-004). A suite of negative cross-tenant tests runs in CI from day one. With a connection pooler in transaction mode, `SET LOCAL` stays correct because it lives inside the transaction.

---

## ADR-004 — RAG on Aurora (pgvector + FTS) instead of Bedrock Knowledge Bases

**Context.** FR-043 requires the ACL before retrieval, NFR-013 requires the core to run locally, and the corpus is small (procedures and regulations, thousands of chunks).

**Decision.** Chunks, embeddings (`vector`) and the full-text index (`tsvector` with the `english`, `danish` and `italian` configurations, `simple` for Polish) in the same Aurora instance, protected by the RLS of ADR-003. Hybrid retrieval with RRF fusion in SQL. Titan Text Embeddings V2 as the baseline, to be compared with another multilingual model on the golden set. A reranker only if it improves hit@k.

**Rejected alternatives.**
- *Bedrock Knowledge Bases*: manages ingestion and chunking, but tenant isolation becomes a metadata filter the application must remember to pass, and it does not exist locally.
- *OpenSearch Serverless*: excellent hybrid search, but with a continuous minimum cost that makes no sense at this volume.

**Consequences.** One store to run and back up. Chunking and ingestion are our code (workers on SQS). To be reconsidered if the corpus grows past a few million chunks.

---

## ADR-005 — Workflow state in the database, queues for work, Step Functions for agent orchestration

**Context.** FL-01 must survive interruptions without repeating actions (FR-032) and wait for a human approval of unpredictable length (FR-022).

**Decision.** Offers, proposals and missions are state machines in the database. Every transition is an `UPDATE ... WHERE status = :expected AND version = :v`, in the same transaction as its audit event; client requests carry an idempotency key. Waiting for approval is simply a proposal in `pending`. Ingestion, notifications and real-time delivery go through SQS queues with DLQs. AWS Step Functions Standard owns the long-running agent loop while Aurora remains the source of truth for each run and step. Locally, the same bounded runtime is driven through ElasticMQ.

**Rejected alternatives.**
- *Step Functions task tokens for human approval*: rejected because approvals already have a durable database state. Standard Workflows are used only as the agent execution coordinator; they do not duplicate domain state.
- *LangGraph with checkpoints*: designed for agents whose path the model decides; FL-01 has a fixed path.

**Consequences.** A single source of truth, transactional with the audit. Expiry of unapproved proposals runs as a scheduled job (EventBridge Scheduler).

Operational workflows (FL-01, missions) stay deterministic. The agent layer of ADR-010 sits on top of them: it can only create proposals, which enter these same workflows and wait for human approval. Step Functions coordinates agent compute; it does not decide domain transitions.

---

## ADR-006 — Private compute, VPC endpoints, no NAT, pooled database access

**Context.** Aurora must sit in private subnets, so the Lambda functions that use it must be in the VPC, yet they must also reach Bedrock, SQS and S3. A NAT Gateway has a fixed hourly cost plus traffic.

**Decision.**
- API and worker Lambda functions in the VPC, private subnets across 2 AZs.
- Gateway endpoints for S3 and DynamoDB (free); interface endpoints only for the services actually called (`sqs`, `bedrock-runtime`, `secretsmanager` for the bootstrap, `lambda` for agent → MCP gateway → executor). The plan fails if one of them is not offered in the chosen AZs.
- No `cognito-idp` endpoint: a user pool with a domain (needed by the hosted sign-in) is not reachable through PrivateLink. Terraform reads the pool's JWKS at deploy time and the API verifies tokens offline.
- No NAT Gateway.
- IAM database authentication: the token is signed locally.
- RDS Proxy sits in front of Aurora in every environment, uses TLS and end-to-end IAM authentication, and bounds the database connection pool. The migration bootstrap alone reaches the cluster endpoint directly with its separate role.
- WebSocket delivery leaves the private plane through an SQS relay and a dedicated publisher Lambda outside the VPC; private functions do not need a NAT gateway to call the public `@connections` endpoint.

**Rejected alternatives.**
- *NAT Gateway*: fixed cost and outbound internet traffic that nothing needs.
- *RDS Data API (Lambda outside the VPC)*: removes networking and endpoints, but forces a second database access path, different from the local one, and complicates `SET LOCAL` for RLS.

**Consequences.** Interface endpoints are billed per hour and per AZ: negligible in an ephemeral demo, to be budgeted in an always-on environment. A new AWS service without an endpoint fails with a timeout, not a permission error.

---

## ADR-007 — Rizzo Flow as an experimental `DecisionRouter`, in shadow mode

*Revised in v0.2.1: v0.2 described Rizzo Flow as a project by the author of SecondChance, which was wrong. Shadow mode added.*

**Context.** FR-030 asks to classify incoming requests (free text from donors, centres, volunteers and coordinators), send them to the right workflow and escalate to an operator when the case is unclear.

[Rizzo Flow](https://github.com/Rizzo-AI-Academy/rizzo-flow) is an open-source project (Apache-2.0) by Simone Rizzo, Rizzo AI Academy, with no link to SecondChance. It reproduces locally the "System One" pattern of Jev (TypeSafe):
- it receives unstructured state and typed questions: `boolean`, `choice` with up to 26 options, `score`, `numeric`;
- it returns probabilities read from the logits of the answer letters, without generating tokens;
- it can abstain (`__insufficient__`);
- it runs on llama.cpp with Spark-X2.5 4B. In Q8_0 it takes 4.4 GB on disk and about 5.6 GiB of GPU memory, and answers a short decision in about 50 ms on an RTX 5060 Ti;
- it exposes `POST /v1/decisions` and a Jev-compatible endpoint.

The project itself states these figures and limits:
- accuracy 0.65 on the public typed-decisions benchmark, 0.71 on customer-service triage;
- probabilities not calibrated by default;
- confident answers even when evidence is missing (6 cases out of 36 in their test);
- English stronger than Italian;
- a single resident model, serving one request at a time;
- no rate limiting, not meant for public exposure;
- measured by the maintainers only on Windows with NVIDIA GPUs.

**Decision.**
- **Interface.** Routing goes through `DecisionRouter`. Input: the request text and minimal context (channel, role, language). Output: the chosen workflow, a probability and an outcome, `ok` or `escalate`. Beneficiary data never enters the state (FR-053, NFR-004).
- **Who decides.** The rules + classifier baseline (FR-030) is active by default and is the only one that decides.
- **`RizzoFlowRouter`** is the second implementation: an HTTP client for `POST /v1/decisions`. It asks one `choice` question, with the FR-030 classes described in one line each, and abstention enabled. It escalates if it abstains, if the `status` is not `ok`, or if the top probability is below the threshold. The Jev-compatible endpoint is not used because it has no abstention.
- **Shadow mode.** Behind a flag, off by default. The baseline decides and answers. Outside the request path, a job asks Rizzo Flow for the same decision with a short timeout. The result goes into a comparison table protected by RLS (ADR-003).
- **What is recorded.** Metadata only (ADR-008): class and probability from each router, outcome, latency, model fingerprint, and the class the operator actually used. The request text is not recorded. An error or timeout from Rizzo Flow changes nothing for the user.
- **Where it runs.**
  - Docker Compose: an optional service (dedicated profile) on the machine's GPU, reachable only from the internal network, port not published.
  - AWS demo: absent.
  - Pilot: only if the cost review approves a GPU host in `eu-central-1`, inside the private VPC.
  - Not on Bedrock, which does not expose answer-letter logits. Not on Lambda, which has no GPU, until someone measures CPU performance.
- **Allowed use.** Routing and triage of requests only. Rizzo Flow stays out of:
  - food-safety rules (FR-012, FR-017), which remain deterministic;
  - any assessment of people or of access to aid (ADR-009);
  - the RAG abstention gate (FR-045), precisely because it is confidently wrong when evidence is missing.
- **Promotion to default router.** Needs a new ADR, and only if the FR-030 golden set (per language) and the shadow comparison show all of these:
  - macro-F1 at least equal to the baseline and ≥ 0.90 (NFR-020);
  - escalation recall not lower than the baseline;
  - probabilities calibrated on our data (the project's temperature scaling, tied to the fingerprint);
  - p95 within the routing budget;
  - GPU host cost accepted.

**Rejected alternatives.**
- *Rizzo Flow as the main router from the MVP*: an unvalidated dependency on the critical path, with a dedicated GPU and uncalibrated probabilities.
- *Synchronous call to Rizzo Flow during the request*: ties API latency and availability to an experimental service, for a decision that is not used in shadow mode.
- *Offline evaluation on the golden set only*: still the main benchmark tool, but it does not show how Rizzo Flow behaves on real requests.

**Consequences.**
- Rizzo Flow version and weights pinned by commit and sha256, as the project does. Every comparison records the fingerprint, and a calibration is valid only for that fingerprint.
- The FR-030 golden set is needed in every supported language (FR-046): Italian is a declared weak spot, Danish and Polish are unmeasured.
- No data leaves the machine hosting the model. Compatible licences: Rizzo Flow, Spark-X2.5 and llama.cpp are Apache-2.0 or MIT.
- Shadow mode can be switched on as soon as the FR-030 baseline exists. The formal benchmark against an ML classifier and LLM routers stays in P6 (FR-031).

---

## ADR-008 — AI logs: metadata yes, plain-text prompts no

**Context.** NFR-012 forbids recording sensitive prompts in plain text. Bedrock model invocation logging records full prompts and responses.

**Decision.** For every call the application records: model and version, tokens in and out, latency, guardrail outcome, IDs of the cited chunks, correlation ID. Bedrock model invocation logging stays off; it can be switched on in the demo (synthetic data), to an encrypted bucket with short retention.

**Consequences.** Quality debugging uses the golden set and the chunk IDs, not production prompts.

*Extended in v0.3.*
- Prompt templates are versioned files in the repository. Every agent step records the template hash and the model ID, so a prompt change stays traceable without the text.
- Agent memory (ADR-011) is not a log. It is domain data, with its own scope, RLS and expiry, and follows the minimisation rules of ADR-014.

---

## ADR-009 — AI Act classification

**Context.** The EU AI Act classifies as high risk, among others, systems that assess access to essential services and benefits.

**Decision.** SecondChance neither assesses nor ranks people; it allocates resources to centres, with mandatory human approval. Goal: stay out of the high-risk category. Transparency obligations apply (users know they are interacting with an AI and that answers are generated). The classification must be reviewed if the scope moves towards beneficiary eligibility criteria.

**Consequences.** The non-goals in PRD §2.3 are compliance constraints, not just product choices. Legal assessment before the pilot.

---

## ADR-010 — Agent layer: stateless supervisor and specialists inside deterministic workflows

**Context.** Some coordinator tasks have no fixed path: the next step depends on what comes up along the way. Examples:
- "what do we do with today's surplus?";
- understanding a badly written request;
- explaining why the solver discarded a centre;
- looking up a procedure before proposing an allocation.

They need different contexts and permissions: documents (RAG), operational data, the solver. The PRD stays *human-in-control* and ADR-005 keeps FL-01 deterministic.

**Decision.**
- **Star topology (agents as tools).** A *supervisor* receives the task, decides which specialists to call and produces one final answer. Specialists do not call each other, so traces and permissions stay readable.

  | Agent | Does | Tools (read-only unless stated) | Model |
  |---|---|---|---|
  | `supervisor` | plans, delegates, synthesises, writes the proposal | the specialists; `create_proposal` (write, always `pending`) | LLM (Claude Haiku via `eu.` / Ollama) |
  | `intake` | classifies requests (FR-030) and extracts offer fields from free text | `DecisionRouter` (ADR-007), category catalogue | rules + classifier; LLM only for extraction |
  | `knowledge` | answers on procedures and rules with citations, or abstains (FL-02) | hybrid retrieval with RLS (ADR-004) | LLM + Guardrails |
  | `matching` | prepares the solver input, queues the OR-Tools job, explains the result | offers, centres, capacity; `enqueue_solver_job` | LLM for the explanation; the solver decides |
  | `compliance` | applies country food rules (FR-017) | — | **no LLM**: deterministic code, callable by everyone, cannot be bypassed |

- **Durable, stateless execution.**
  - Every execution is an `agent_run` with its `agent_step` rows in Postgres, under RLS.
  - A step is a bounded invocation: one supervisor turn or one specialist call.
  - On AWS, a Standard Step Functions execution invokes the stateless agent-step Lambda once per turn and loops only while the committed result says `continue`. Locally, ElasticMQ drives the same runtime.
  - Uniqueness of `(run_id, seq)` and a fencing attempt number make retries harmless: a stored step is never repeated.
- **Framework.** Strands Agents SDK (Apache-2.0) *inside* the step. In the cloud models go through Bedrock, locally through Ollama, behind the same adapter (FR-035). State is not left to the framework: it lives in the tables above.
- **Explicit circuit breaker per run**: number of steps (default 12), tokens (default 60,000) and duration (default 10 min). The transaction that commits each step calculates projected usage and immediately sets `budget_exhausted` before another step can be created. The loop stops on the model's `stop_reason`, never on its text.
- **Side effects only through proposals.** Tools are read-only. The only write is `create_proposal`, which creates a `pending` proposal with a content hash. The operator approves that hash: after approval the model cannot change the parameters (FR-022, FR-034).
- **Identity from the context, never from the model.** Tenant, role and subject come from the run (set from the token of whoever started it) and every step opens its own transaction with `SET LOCAL`. No tool accepts `tenant_id` as an argument.
- **Untrusted content.** Documents, requests and memory enter the prompt delimited as data, not instructions. On AWS, Guardrails filter prompt attacks; tools have least privilege.
- **Errors as errors.** A failing tool returns a category and `retryable`, never an empty result. A failing specialist returns its attempts and partial outcome to the supervisor.
- **Transparency (AI Act, art. 50).** Every agent output is marked `generated_by` with agent, model and prompt version, and the interface shows it as generated content.

**Rejected alternatives.**
- *Bedrock AgentCore Runtime*: microVM isolation per session, but a second deployment target that does not exist in Docker Compose (NFR-013), and we run no untrusted code. To be reconsidered if long sessions, Code Interpreter or Browser become necessary. Agents written with Strands move there without a rewrite.
- *AgentCore Memory*: managed, but tenant isolation would be a namespace the application must remember to pass, not RLS, and it does not exist locally (same reasoning as ADR-004).
- *Bedrock Agents configured in the console*: no local parity, little control over the loop.
- *LangGraph*: its checkpointer would duplicate state already in the database. Strands is lighter and aligned with AWS.
- *Swarms or peer-to-peer agents*: harder to trace and to authorise, with no benefit for these tasks.
- *Agents executing approved actions on their own*: would violate FR-022.

**Consequences.**
- FL-01 does not change: agents produce proposals that enter the workflows of ADR-005.
- Every agent has a golden set and a quality threshold before release. LLM-as-judge scores are calibrated on human labels; prompt or model changes go through the A/B or shadow mechanism of ADR-013, with rollback.
- The AI Act classification (ADR-009) holds as long as agents do not assess people.
- Costs grow per run: budgets, per-agent metrics and alarms are in ADR-012.

---

## ADR-011 — Shared memory and storage across services and agents

**Context.** API, workers and agents are stateless (Lambda or replicable containers), but they need shared context:
- workflow state;
- a run's "blackboard", read and written by several agents;
- the history of a conversation;
- tenant knowledge that lasts;
- files such as solver input and output, documents and proofs of delivery.

All of it must respect RLS (ADR-003), GDPR retention (ADR-014) and local parity (NFR-013).

**Decision.** No state stays in a process's memory. There are four shared layers, each with a single access path:

| Layer | Where | What | Isolation | Expiry |
|---|---|---|---|---|
| State | PostgreSQL/Aurora | workflows, `agent_run`, `agent_step`, proposals, audit | RLS | per table (ADR-014) |
| Agent memory | PostgreSQL + pgvector, table `agent_memory` | scope `run` (the run's blackboard), `conversation` (short term per subject), `tenant` (long term) | RLS + scope | mandatory: 7 / 30 / 365 days |
| Objects | S3; locally SeaweedFS (S3 API) | solver artefacts, documents, attachments | prefix `tenants/{tenant_id}/` from the context; on AWS ABAC with a `tenant_id` session tag | lifecycle per area |
| Hand-off of work | Step Functions for agent steps; SQS/ElasticMQ for asynchronous work | `jobs`, `notify`, `realtime-events` with DLQs; local agent queue for parity | messages carry IDs and status metadata only | short queue retention |

- **Memory rules.**
  - Writes go only through the memory module, which enforces scope, provenance and expiry.
  - `tenant` memory accepts only content confirmed by an operator: no model-extracted facts without review.
  - Never beneficiary data or special categories (GDPR art. 9). Text goes through the PII redaction of ADR-014 before it is stored.
  - Recall is by scope and recency, or by cosine similarity on the embedding. Every row declares its `embedding_model`, and only vectors of the same model are compared: Titan V2 with 1024 dimensions on AWS, a local 1024-dimension provider in Compose.
- **Object keys.** The key is computed from the transaction context, never from an argument: `tenants/{tenant_id}/{area}/{id}`. On AWS the bucket uses SSE-KMS, versioning and Block Public Access. Downloads use short-lived presigned URLs (FR-015).
- **No distributed cache in the MVP.** Postgres is enough. A semantic cache (MemoryDB) is considered only if the Bedrock bill justifies it.

**Rejected alternatives.**
- *AgentCore Memory*: see ADR-010.
- *DynamoDB for chat history*: native TTL, but a second database with a second access path and no RLS.
- *ElastiCache/Redis*: always-on fixed cost.
- *MinIO locally*: the repository is archived and its images are no longer published. SeaweedFS (Apache-2.0) replaces it.

**Consequences.**
- The cross-tenant suite also covers memory and objects.
- A daily retention job (EventBridge Scheduler on AWS) deletes expired rows.
- Erasure on a data subject's request includes that subject's `conversation` memory (ADR-014).
- The agent-step runtime needs no sticky sessions: Step Functions may invoke any warm or cold instance for any step.

---

## ADR-012 — Observability with OpenTelemetry, same code locally and on AWS

**Context.** Traces, metrics and logs must cross API, queues, workers and agents with one correlation ID (FR-004, NFR-011). The PRD asks for a near-zero fixed cost and no prompts in logs (ADR-008).

**Decision.**
- **One instrumentation with OpenTelemetry.** OTel SDK for traces and metrics, auto-instrumentation of FastAPI and SQLAlchemy, structured JSON logs with `trace_id`, `span_id` and `correlation_id`.
- **Correlation ID.** Taken from `X-Correlation-ID`, or generated when missing or invalid. Returned in the response and carried in SQS message attributes, agent steps and audit events.
- **Export over OTLP.**
  - Locally to `grafana/otel-lgtm`: collector, Tempo, Prometheus, Loki and Grafana in one container, in the `observability` Compose profile.
  - On AWS: ADOT → X-Ray for traces, CloudWatch for metrics and logs, Transaction Search and Application Signals for SLOs.
  - Without a configured endpoint export is off and the code does not change.
- **Signals.**

  | Area | Metrics |
  |---|---|
  | API | requests, errors and latency per route (RED); database pool |
  | Queues | depth, age of the oldest message, messages in DLQ |
  | Agents | steps per run, tokens in/out, estimated cost, latency per agent, tool errors by category, guardrail interventions, abstentions, `budget_exhausted` |
  | Routing | agreement between baseline and Rizzo Flow in shadow mode (ADR-007) |
  | Domain | offers published and reserved, 409 conflicts, missions completed and failed |
  | Admission | rejections by stage and reason (ADR-016) |

- **Pilot SLOs.**
  - API availability 99.5% per month (NFR-009).
  - p95 < 500 ms on reads (NFR-007) and p95 < 10 s for RAG (NFR-008).
  - 99% of notifications within 1 minute (FR-026).
  - Empty DLQs.
  - Alarms fire on the error-budget *burn rate* (1 h and 6 h windows), through SNS to email; runbooks live in `docs/operations/`.
- **Privacy in signals.**
  - The log formatter keeps only allowed attributes and runs text through PII redaction.
  - `Authorization` and cookies are never recorded.
  - Logs are kept 30 days; traces are sampled.

**Rejected alternatives.**
- *Prometheus and Grafana in the cloud*: always-on components.
- *Observability SaaS*: cost, and data outside the EU perimeter to assess.
- *Langfuse*: useful for deep LLM traces, but one more service. The OTel GenAI semantic conventions cover the MVP.

**Consequences.**
- One more dependency (OTel SDK and instrumentation), the same everywhere.
- On AWS, exporting from a function inside the VPC needs the `xray` and `logs` interface endpoints (ADR-006); Lambda's active tracing covers the default configuration, and `otel_exporter_otlp_endpoint` enables OTLP export when a collector is reachable.

---

## ADR-013 — Feature flags and A/B experiments in the database

**Context.** Prompts, retrieval settings, routers and interface copy must be compared on real data, with an instant way back. This is a humanitarian context, though: an experiment must never change who receives aid.

**Decision.**
- **A platform-level `experiment` table.** It holds key, `surface`, weighted variants, status (`draft`, `running`, `stopped`), hypothesis, primary metric, guardrail metrics, owner and time window.
- **Allowed surfaces, enforced by a `CHECK` constraint**: `ui`, `prompt`, `retrieval`, `routing`, `notification_copy`. Allocation, solver and food rules are not surfaces, so no experiment can touch them.
- **Deterministic, stateless assignment.**
  - Compute `sha256(key:unit)`, reduce it to a bucket 0…9999 and pick the variant from the cumulative weights.
  - The unit is the pseudonymous subject or the tenant.
  - There is no assignment table: every instance computes the same variant.
- **Tenant opt-in.** `tenant.experiments_enabled` is false by default; while false, every subject of the tenant gets the control.
- **Kill switch.** The status is read on every request, in the same transaction. Setting it to `stopped` puts everyone back on the control immediately.
- **Exposures.** `experiment_exposure` is append-only with RLS and 180-day retention. It records the pseudonymous unit, the variant and the correlation ID. Outcomes come from existing metrics and audit.
- **Analysis.**
  - Primary metric, minimum sample and stopping rules are fixed before starting.
  - Guardrail metrics (errors, latency, correct abstentions) stop the experiment if they get worse.
  - Shadow mode (ADR-007) is a special case: no variant visible to the user.

**Rejected alternatives.**
- *AWS AppConfig feature flags*: validators, gradual rollout and rollback, but it does not run in Compose. It can be added later for configuration unrelated to experiments.
- *Self-hosted GrowthBook or Unleash*: one more service to run, for a need that today takes one table and one function.

**Consequences.**
- Every experiment is declared in the record of processing activities (ADR-014), with legitimate interest in improving operator-facing features as the legal basis.
- Beneficiaries are never experimental units.

---

## ADR-014 — Privacy by design (GDPR)

**Context.**
- **Roles.** Every NGO (tenant) is the controller of its own data. Whoever runs an installation for several NGOs is a processor (art. 28), with AWS as sub-processor. In a self-hosted installation the NGO is controller and operator at once.
- **Data subjects.** Operators, volunteers and donor contacts. Beneficiaries have no accounts and must not appear (PRD §2.3).
- **Risks.** Free text containing personal data, logs and agent memory, experiments.

**Decision.**
- **Inventory generated from the schema.**
  - Every column carries a `pii:none|personal|sensitive` comment with its purpose.
  - A test blocks migrations that add unclassified columns.
  - The inventory for the record of processing activities (art. 30) is generated from the catalogue with `python -m secondchance.privacy`.
- **Pseudonyms, not identities.**
  - Domain tables keep only the IdP `sub` (Cognito, Keycloak or the mock).
  - Names, emails and phone numbers live in the IdP.
  - Erasing a data subject means deleting the IdP user, their `membership` rows, their `conversation` memory and their exposures. The append-only audit keeps the pseudonym, which can no longer be linked to a person: legal basis legal obligation and legitimate interest in accountability.
- **PII redaction in free text.**
  - Applied before logs, memory and prompts.
  - The code redacts emails, phone numbers and IBANs.
  - On AWS, Guardrails with PII *mask* sit in front of the model.
  - Locally only synthetic data is used.
- **Retention as code.** A table of durations per area, applied by the retention job:

  | Data | Duration |
  |---|---|
  | `run` memory | 7 days |
  | `conversation` memory | 30 days |
  | `tenant` memory | 365 days |
  | Experiment exposures | 180 days |
  | Agent steps (metadata only) | 365 days |
  | Logs | 30 days |
  | Audit | 5 years, to be validated with the pilot's legal counsel |

- **Residency.** Everything stays in `eu-central-1`. Inference uses the `eu.` profile; Rizzo Flow runs locally. No sub-processors outside the EU.
- **Data subject rights.** Access, portability and erasure follow a runbook, with dedicated endpoints in P1, and close within one month (art. 12).
- **Security of processing (art. 32).** Encryption in transit and at rest, RLS, least privilege, audit, and encrypted backups with tested restores.
- **Breaches (art. 33-34).** A runbook with notification to the authority within 72 hours.
- **DPIA.** Screening points to a DPIA before a pilot with real data: innovative use of AI, a context with vulnerable people even if indirect.

**Rejected alternatives.**
- *Anonymise everything*: impossible, because notifications to volunteers need a contact.
- *A database per tenant*: see ADR-003.

**Consequences.** Operational details (record of processing, legal bases, procedures) in [`compliance/gdpr.md`](compliance/gdpr.md). Real compliance depends on contracts, AWS configuration and legal assessments: this ADR fixes the technical controls and does not replace the DPO's opinion.

---

## ADR-015 — Knowledge service and intent router

**Context.** The external specification "Intelligent Knowledge & Multi-Agent Orchestration" v0.2.0 asks for four capabilities:
- an *Intent Router* that sends every request down the cheapest path;
- a multilingual RAG *Knowledge Service* shared by portals and agents, with Knowledge Spaces;
- autonomous PDF ingestion with atomic publication;
- tool access through MCP with an allowlisted catalogue.

It also names a stack (LangGraph, Celery, MinIO, Kubernetes, LiteLLM, TEI) that partly contradicts ADR-001, ADR-005 and ADR-011.

**Decision.** The capabilities and contracts of the specification enter the product. The technologies follow the existing ADRs.

| Specification | SecondChance | Why |
|---|---|---|
| Intent Router with 6 intents | Two-level `IntentRouter`: intent (`KNOWLEDGE_QUERY`, `DIRECT_OPERATION`, `SINGLE_CAPABILITY`, `MULTI_AGENT_TASK`, `CLARIFICATION`, `UNSUPPORTED`) and suggested workflow. Rules baseline in English, Danish, Polish and Italian; Rizzo Flow in shadow mode (ADR-007) | fast path before any agent; Rizzo Flow answers both questions with one prefill |
| LangGraph Agentic Brain | the durable runtime of ADR-010 (Strands inside the step). The plan is a DAG of allowlisted capabilities, validated by code before any step runs | state is already in the database; local parity; portable to AgentCore |
| Celery + Redis/RabbitMQ | Step Functions for agent orchestration; SQS for asynchronous delivery; locally ElasticMQ | no always-on broker (ADR-005) |
| MinIO | S3, locally SeaweedFS | MinIO is archived (ADR-011) |
| Kubernetes, Helm | Lambda with a container image (ADR-001). The image also runs on ECS or Kubernetes unchanged | cost at rest, one maintainer |
| LiteLLM gateway | a thin adapter: Bedrock (cloud) / Ollama (local). LiteLLM can sit behind the same adapter | fewer components in the MVP |
| Docling | `pypdf` in the baseline parser for standard digital PDFs. Docling as an adapter in a separate ingestion image (spike) | Docling brings torch and models: it does not belong in the API image |
| Granite embedding + TEI | `EmbeddingProvider` interface: Titan Text Embeddings V2 with 1024 dimensions on Bedrock; locally a deterministic provider (feature hashing) for tests and offline demos, or Ollama/TEI | no always-on GPU. Granite (768 dimensions) stays a benchmark candidate: adopting it means migrating the dimension and recomputing embeddings |
| GTE reranker | optional reranker behind an interface: Bedrock Rerank on AWS (availability in `eu-central-1` to be checked), TEI locally | active only if it improves hit@k (ADR-004) |
| Prometheus, Grafana, Langfuse | OpenTelemetry → LGTM locally, CloudWatch/X-Ray on AWS (ADR-012) | the same code everywhere |
| MLflow | out of the MVP | forecasting comes after the pilot |
| MCP Gateway | a catalogue of allowlisted tools as the single contract for agents and services. Exposure over MCP (AgentCore Gateway) comes later | the contract matters before the transport |

- **Knowledge Spaces and ACL in the database.**
  - Every space has a tenant, a `visibility` (`public` | `tenant`) and `allowed_roles`.
  - Chunks copy these fields (denormalised), so the RLS policy checks them without a join: `(tenant_id = current tenant OR visibility = 'public') AND app.role = ANY(allowed_roles)`.
  - A revocation updates space and chunks in the same transaction, so it takes effect on the next query.
  - Territory is a relevance filter, never an authorisation.
  - Public spaces belong to the platform tenant and only `platform_admin` curates them.
- **Ingestion.** Upload validation (ADR-016) → original on S3 with SHA-256 → job on `jobs` → parsing → versioned canonical schema → section-aware chunking (350-650 tokens) → batched embeddings → quality gate → staging → atomic publication.
  - Atomic publication is an `UPDATE` of the active version in the same transaction.
  - Idempotency holds on `(document_id, content_hash, pipeline_version)`.
  - The previous version stays searchable until the new one is published.
- **Separate APIs:**
  - `POST /knowledge/search`, without an LLM;
  - `POST /knowledge/answer`, with citations and abstention;
  - `POST /documents`;
  - `GET /ingestion/jobs/{id}`;
  - `GET /knowledge/spaces`.

**Rejected alternatives.** Adopting the specification's stack as is: two brokers, a cluster and an extra LLM gateway, all always on, against NFR-023 and with no requirement justifying them today.

**Consequences.**
- The specification stays the functional reference; its KPI and DoD sections enter the PRD.
- Every technology deviation is listed above and can be reopened with a new ADR if a benchmark justifies it.

---

## ADR-016 — Fail fast: early rejection and admission control

**Context.** A malformed or inadmissible request must not consume expensive resources (Lambda, database, LLM, solver) only to be thrown away at the end. The system must stay stable under abuse and spikes.

**Decision.** Checks run from the cheapest to the most expensive. Every stage accepts only what the previous one has guaranteed.

| # | Stage | Rejects | Cost of the rejection |
|---|---|---|---|
| 1 | CloudFront + AWS WAF | IPs over the rate limit, known patterns (managed rule groups), bodies over the threshold | no Lambda invoked |
| 2 | API Gateway HTTP API | missing or invalid token (Cognito JWT authorizer), over the route throttling | no Lambda invoked |
| 3 | API middleware | `Content-Length` over the route limit, wrong content type | no query |
| 4 | Strict Pydantic schemas | unknown fields (`extra="forbid"`), types, lengths, enums | no query |
| 5 | Identity and role | no membership, suspended or pending; role not allowed | one indexed query |
| 6 | Admission control | per-tenant quotas: concurrent active runs, daily runs, daily uploads, registrations per user → `429` with `Retry-After`; tokens have a per-run budget (ADR-010). A queue-backlog check is planned; today a CloudWatch alarm reports it | one aggregate query |
| 7 | Intent router | `UNSUPPORTED` and `CLARIFICATION` answer at once, without agents | in-memory rules |
| 8 | Upload | `%PDF-` magic bytes, size, page count, encrypted PDFs, active content: all checked before writing to S3 and queueing. On AWS, GuardDuty Malware Protection for S3 scans the stored file and the jobs worker parses it only after a clean verdict (ADR-022) | no job queued; an infected file is never parsed |
| 9 | Worker | message schema validated before any work; poisoned messages go to the DLQ after 5 attempts | no LLM called |
| 10 | Agent plans | a DAG of allowlisted capabilities, acyclic, within budget, validated before the first step | no tool run |

- Limits are per-environment configuration with prudent defaults. Every rejection increments `secondchance.admission.rejections` with stage and reason, so a spike of rejections shows on the dashboard.

**Rejected alternatives.**
- *Validating only in the domain*: the rejection comes after paying for network, Lambda and database.
- *API Gateway REST with JSON Schema validators*: moves one check further upstream, but costs about 3.5 times HTTP API and duplicates the Pydantic schemas. To be reconsidered if needed.

**Consequences.**
- Every new endpoint declares a body limit, a strict schema, its roles and, if it starts asynchronous work, a quota.
- Tests cover every application stage (3-10).

---

## ADR-017 — Identity, registration and authorisation: AuthN in the IdP, AuthZ in SecondChance

**Context.** The platform is a web application. Donors and NGOs register by themselves and see different screens per role. Roles and memberships change over time (approvals, suspensions) and a revocation must take effect at once.

**Decision.**
- **Authentication.** OIDC. On AWS: a Cognito user pool with self sign-up, email verification, MFA mandatory for administrators, Hosted UI with PKCE. Locally: a mock OIDC with a development sign-in page. The token carries only `sub` and the verified email.
- **Authorisation in the database.**
  - The `membership` table (`subject`, `tenant_id`, `organization_id`, `role`, `status`) is the source of truth.
  - On every request the API resolves the active membership of the `sub` (with `X-Tenant-ID` if there is more than one) and sets `app.tenant_id`, `app.role` and `app.subject` with `SET LOCAL`.
  - A suspension applies from the next request, without waiting for the token to expire.
- **Two-step registration, the same locally and on AWS.** First the sign-up in the IdP, then `POST /registrations` in the app:

  | Type | Creates | Initial status | Who approves |
  |---|---|---|---|
  | NGO | tenant, `ngo` organisation, `org_admin` membership | `pending` | `platform_admin` (checks the organisation) |
  | Donor | `donor` organisation in the network chosen from the public directory, `donor` membership | `pending` | the network's `org_admin` |
  | Coordinators, volunteers, centre staff | `membership` in the network chosen from the directory, with a display name, no organisation | `pending` | the network's `org_admin`; centre staff are approved for one centre (`membership.center_id`, set only by an admin) |

- **Screens per role.**
  - `GET /me` returns memberships, status and the list of enabled *capabilities*.
  - The frontend builds its navigation from that list; the backend still enforces roles on every endpoint (ADR-016, stage 5).
  - A `pending` user sees only the waiting screen.
- **Network directory.** A `network_directory` view with only public columns (id, name, country) of active tenants. It is the only intended cross-tenant read, and it is documented and tested.
- **Database guards.** Triggers refuse self-approval, role changes through an update and activating a tenant without being a platform administrator.

**Rejected alternatives.**
- *Roles and tenant in token claims (Cognito groups, pre-token trigger)*: every change needs a new token, revocation waits for expiry, and customising the access token depends on the Cognito feature plan.
- *Self-registration for every role*: opens the door to fake coordinators.

**Consequences.**
- One more indexed query per request.
- The seed creates memberships for the synthetic users.
- Registration is a public endpoint (valid token only, no membership), so WAF and quotas protect it (ADR-016).

---

## ADR-018 — AWS deployment: Terraform, no access keys, self-configuration

**Context.** The production deployment must configure everything from the command line, with no secrets in the repository or in CI variables, and it must be repeatable and destroyable (NFR-014, NFR-023, NFR-024).

**Decision.**
- **Human credentials.** IAM Identity Center (SSO) with MFA and a dedicated permission set. Locally `aws configure sso`, then `aws sso login --profile secondchance-admin`: credentials are temporary and no access key exists.
- **CI credentials.** GitHub Actions with OIDC towards an IAM role whose trust policy accepts only this repository and the GitHub environment `production`, which requires reviewers. No AWS secret in GitHub.
- **Runtime credentials.**
  - IAM roles per function, with IAM database authentication for Aurora: no application passwords.
  - The Aurora master password is managed by RDS in Secrets Manager and only the role-bootstrap function uses it.
  - Any future secret goes into Secrets Manager, referenced by ARN.
- **Terraform** in `infra/terraform`:
  - `bootstrap/`: once per account. State bucket with versioning, encryption and native locking; GitHub OIDC provider and deploy role with a permission boundary.
  - `envs/<environment>`: instantiates the `secondchance` module (network, data, compute, edge, identity, observability) with per-environment parameters (ephemeral `demo`, `pilot`).
- **Self-configuration.** One command, `scripts/deploy.sh <environment>`:
  1. checks the identity (`sts get-caller-identity`);
  2. builds the images and pushes them to ECR with an immutable tag;
  3. runs `terraform apply`;
  4. invokes the `migrate` function (role bootstrap, `alembic upgrade`, seed in the demo only);
  5. publishes the web app, runs the smoke test and prints the URL.

  `scripts/destroy.sh` tears an environment down.
- **Same image, different commands.** API (Lambda Web Adapter + uvicorn), agent and job workers (SQS event source, partial batch response), migrate, retention and requeue (EventBridge Scheduler).

**Rejected alternatives.**
- *IAM access keys in a file or in GitHub secrets*: long-lived secrets, to rotate, easy to leak.
- *AWS CDK*: sound, but the PRD chose Terraform and the open-source community knows it better.
- *Manual configuration in the console*: not repeatable, not destroyable with one command.

**Consequences.**
- The first deployment needs a single high-privilege action (`bootstrap`). After that, everything goes through the deploy role.
- The detailed steps are in [`deployment.md`](deployment.md).
- WAF, interface endpoint and Aurora costs go into the cost review before any always-on environment.

---

## ADR-019 — Internationalisation: English first, then Danish, Polish and Italian

**Context.** SecondChance is meant for networks in several countries; the first candidates are in Denmark, Poland and Italy. Volunteers and small donors should use the platform in their own language, while code, documentation and the default interface must be readable by any contributor.

**Decision.**
- **English is the source language** of code, documentation, API messages and the interface.
- **Web interface** in English, Danish, Polish and Italian, with a language picker on every page. The choice is remembered per browser; the default is English.
- **No i18n library.** One typed dictionary per language (`web/src/locales`): the English file defines the keys and the type checker fails if another language misses one. Country and language names, dates and numbers come from the browser's `Intl` API.
- **Values from the API are codes**, never prose (statuses, categories, roles, assistant outcome kinds): the interface translates them. Free-form error details from the API stay in English.
- **Documents and retrieval** in the same four languages. PostgreSQL has stemmers for English, Danish and Italian, but none for Polish: Polish text uses the `simple` configuration (lower-cased, unstemmed words); on Polish chunks the query also matches word prefixes (a word minus its last three letters), a crude stand-in for a stemmer, and dense retrieval covers the rest. Queries without a declared language are matched against all four.
- **Intent router** keywords and question words in the four languages, until the FR-030 classifier replaces them.

**Rejected alternatives.**
- *i18next or FormatJS*: plurals and lazy loading are not needed yet; a typed object is smaller and fails at build time.
- *Detecting the language from the browser*: fewer clicks, but the explicit request is an English default with a visible choice.
- *A Polish ispell dictionary in PostgreSQL now*: better lexical recall, but it is an extra file in every database image and on Aurora it needs a custom text-search configuration. To be added if the golden set shows a recall gap.

**Consequences.**
- A new screen needs its strings in four files; the build fails otherwise.
- The golden sets for routing (FR-030) and RAG (NFR-019) need Danish and Polish cases, not only English and Italian.

---

## ADR-020 — Licence: PolyForm Noncommercial, commercial use by agreement

**Context.** SecondChance is built for food banks, NGOs and charities. Its author wants it free for them, and wants no one to sell it or run it for profit without the author's consent. Contributors should know from the first commit what happens to their work.

**Decision.**
- The code is **source-available** under the [PolyForm Noncommercial License 1.0.0](../LICENSE), with the required notice `Copyright (c) 2026 Pierfrancesco Lijoi`.
- Any noncommercial purpose is permitted, and the licence names charitable organisations, educational institutions, public research, health and safety organisations and government bodies as permitted users whatever their funding.
- Commercial use (selling, paid hosting, use inside a for-profit business) needs a separate written licence from the author.
- Every contribution grants the author the right to relicense it, commercially included (contributor terms in CONTRIBUTING.md), so free use and commercial licences remain possible together.

**Rejected alternatives.**
- *Apache-2.0 or MIT*: permissive and widely adopted, but they allow anyone to sell the software or offer it as a paid service.
- *AGPL-3.0*: keeps modifications open, yet commercial resale and paid hosting stay allowed as long as the source is shared.
- *Creative Commons BY-NC*: the same intent, but written for creative works, not software (no patent or distribution terms for code).

**Consequences.**
- SecondChance is not "open source" in the OSI sense, which excludes restrictions on commercial use; it is described as source-available everywhere.
- Dependencies keep their own licences; the licence-governance item in the PRD checks that none conflicts with noncommercial redistribution.
- A company that wants to use it asks the author first.

---

## ADR-021 — Operations: OR-Tools, proposals bound to a hash, missions and a notification outbox

**Context.** FL-01 needs the steps between a published offer and food at a centre: who receives what (FR-020, FR-021), a human decision (FR-022), a mission a volunteer carries out (FR-023, FR-025), notifications (FR-026), receipt by the centre and measurable results (FR-052, FR-053). AI may help, but must not be able to move food on its own (ADR-009, ADR-010), and every piece must run the same way locally and on AWS.

**Decision.**
- **Rules, then CP-SAT, in the jobs worker.** A matching run is a job on the existing `jobs` queue (no new queue, no new function family). Deterministic rules build the allowed (offer, centre, day) options and record a reason for every rejected pairing; OR-Tools CP-SAT picks at most one option per offer within each centre's remaining daily capacity. One search worker, a fixed seed and a deterministic time budget make the answer reproducible; the run stores the checksum of its input. One run per network at a time (ADR-016 quota); a newer run supersedes open proposals.
- **Proposals bound to their content.** A proposal row is immutable (trigger) and carries the SHA-256 of its canonical content. Approval requires that hash from the client and re-hashes the stored row, so the approver confirms exactly what they reviewed. The approver may choose one of the listed alternatives and assigns a volunteer.
- **Execution is application code, in one transaction.** Re-check centre, storage, category and capacity; reserve the offer with the version the solver read (FR-016); create the mission; record the decision; write notifications and the audit event. The solver and agents only produce rows that wait for this step.
- **Missions as a guarded state machine.** `assigned → accepted → picked_up → delivered`, `failed` with a reason code, `cancelled` by an operator, reassignment before pickup on the same row. The API checks the transition; the `guard_mission` trigger re-checks role, ownership and a version bump; `mission_event` keeps the history and the `Idempotency-Key`; a partial unique index allows one live mission per offer. Offer transitions are guarded the same way.
- **Visibility by RLS.** Operators see the network's missions, volunteers their own, centre staff their centre's; a notification is visible only to its recipient.
- **Notifications through an outbox and a data-free relay.** In-app rows always; email for mission assignment and cancellation through `notification_delivery`, handed to the `notify` queue after the commit and re-sent by the recovery job. The notifier runs outside the VPC with no data permission (as the real-time relay), resolves the verified address in Cognito by `sub` and sends a fixed template with SES, allowed only from the configured sender. Permanent refusals are counted, not retried; transient failures go to the DLQ.
- **Centre staff and volunteers join through approval.** They request membership of an existing network; its admin approves, and assigns the centre for centre staff.

**Rejected alternatives.**
- *Greedy matching in SQL*: simple, but it cannot trade one offer against another under shared capacity, and explains less.
- *A separate solver service or container*: one more image and network path; the jobs Lambda (2 GB, 300 s) fits the MVP volumes.
- *Letting an agent create missions with a "confirm" flag*: the approval would depend on model output; a content hash and deterministic code keep the human decision explicit.
- *Sending email from the API Lambda*: SES and Cognito are not reachable from the VPC without NAT, and the API would need contact data; the outbox keeps the request fast and the API free of addresses.
- *Storing volunteers' emails in the database*: duplicates personal data that the identity provider already holds (ADR-014).

**Consequences.**
- OR-Tools (with numpy and pandas) makes the worker image larger; cold starts of the jobs function grow, the API image too.
- New accounts start in the SES sandbox: until production access, only verified recipients receive emails; in-app notifications carry the information anyway.
- Distances are great-circle estimates with a road factor; FR-024 brings a travel-time matrix and multi-stop routes.
- Retention covers the new tables: notifications 90 days, outbox 30 days, proposals and runs 365 days, finished missions and their history 730 days.

---

## ADR-022 — Detective controls: CloudTrail, GuardDuty and a malware verdict before parsing

**Context.** The preventive controls are strong (RLS, per-function IAM, no NAT, KMS everywhere), but nothing recorded who did what on the AWS account or noticed an attack in progress, and uploaded PDFs reached the parser unscanned (threat model, residual risk 8). The platform holds data about vulnerable people: GDPR art. 32 asks for the ability to detect and investigate incidents, not only to prevent them.

**Decision.**
- **An account trail in its own bucket.** Multi-region, management events plus object-level events on the documents bucket (who read or wrote which tenant file), log file validation, encrypted with the project key. The bucket keeps files for `trail_retention_days` (365), is versioned and accepts writes only from this trail. The deploy role's boundary forbids `cloudtrail:StopLogging`: a stolen CI credential cannot silence the record of what it does.
- **GuardDuty on the account** with S3 data events, Aurora login events and Lambda network activity. A variable skips the detector where one already exists (one per region) or an organisation manages it.
- **Malware Protection for S3 on `tenants/`.** Every upload is scanned and tagged `GuardDutyMalwareScanStatus`. The jobs worker reads the tag before parsing: `NO_THREATS_FOUND` continues; `THREATS_FOUND`, `FAILED`, `UNSUPPORTED` or `ACCESS_DENIED` fail the version closed (`malware_scan:<status>`); no verdict within 40 seconds puts the version back to `uploaded`, and the recovery job sends it again. The bucket policy denies reading an object tagged `THREATS_FOUND` to every principal, whatever its IAM role.
- **Findings of severity 7 or more** (an infected upload included) reach the alarm topic through EventBridge (runbook RB-11).
- **Locally and in emulation nothing changes**: without `SECONDCHANCE_MALWARE_SCAN=guardduty` every file counts as clean, as before.

**Rejected alternatives.**
- *ClamAV in the jobs image or in a Lambda layer*: signatures to update and an image to keep patched by one maintainer; a managed scan costs per GB at this volume and needs no code to keep current.
- *Waiting for the verdict through the event (EventBridge → SQS → jobs)*: one more queue and rule for a path the tag already covers; polling for 40 seconds plus the existing recovery job is enough at MVP volumes.
- *Only the bucket policy, without the worker check*: the worker would see `AccessDenied` and retry until the DLQ, mixing infected files with real failures.
- *Security Hub and AWS Config now*: useful for a team, heavier to run and pay for one account; they come with the pilot's compliance review.

**Consequences.**
- Costs grow a little: GuardDuty by events analysed, Malware Protection by GB scanned, CloudTrail data events per 100,000 events, S3 storage for the trail. See [section 10 of the operations guide](operations/README.md#10-costs).
- Ingestion of a PDF waits for the scan: usually seconds, at most until the next recovery run (2 minutes in the pilot, 1 hour in the demo).
- Signatures do not catch a parser zero-day: structural validation and parsing in an isolated worker remain the other layers.
