# SecondChance

<p align="center">
  <strong>AI-assisted food rescue. Human-approved decisions. Secure by design.</strong>
</p>

<p align="center">
  <a href="#engineering-confidence"><img alt="Quality checks" src="https://img.shields.io/badge/Checks-passing-2ea44f?style=flat-square&logo=githubactions&logoColor=white"></a>
  <a href="#engineering-confidence"><img alt="API test suite" src="https://img.shields.io/badge/API%20tests-290%20passing-2ea44f?style=flat-square&logo=pytest&logoColor=white"></a>
  <a href="#engineering-confidence"><img alt="Frontend test suite" src="https://img.shields.io/badge/Frontend%20tests-22%20passing-2ea44f?style=flat-square&logo=vitest&logoColor=white"></a>
  <a href="#engineering-confidence"><img alt="MCP test suite" src="https://img.shields.io/badge/MCP%20tests-6%20passing-2ea44f?style=flat-square&logo=python&logoColor=white"></a>
  <a href="#engineering-confidence"><img alt="IaC security scan" src="https://img.shields.io/badge/IaC%20scan-no%20HIGH%20or%20CRITICAL-2ea44f?style=flat-square&logo=terraform&logoColor=white"></a>
  <a href="#licence"><img alt="PolyForm Noncommercial license" src="https://img.shields.io/badge/License-PolyForm%20Noncommercial%201.0.0-007ec6?style=flat-square"></a>
</p>

<p align="center">
  <a href="#stack-at-a-glance"><img alt="Python backend" src="https://img.shields.io/badge/Python-backend-3776AB?style=flat-square&logo=python&logoColor=white"></a>
  <a href="#stack-at-a-glance"><img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-API-009688?style=flat-square&logo=fastapi&logoColor=white"></a>
  <a href="#stack-at-a-glance"><img alt="React" src="https://img.shields.io/badge/React-web-149ECA?style=flat-square&logo=react&logoColor=white"></a>
  <a href="#stack-at-a-glance"><img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-web-3178C6?style=flat-square&logo=typescript&logoColor=white"></a>
  <a href="#stack-at-a-glance"><img alt="Vite" src="https://img.shields.io/badge/Vite-build-646CFF?style=flat-square&logo=vite&logoColor=white"></a>
  <a href="#stack-at-a-glance"><img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-Aurora-4169E1?style=flat-square&logo=postgresql&logoColor=white"></a>
  <a href="#stack-at-a-glance"><img alt="pgvector" src="https://img.shields.io/badge/pgvector-vector%20search-336791?style=flat-square&logo=postgresql&logoColor=white"></a>
</p>

<p align="center">
  <a href="#stack-at-a-glance"><img alt="Amazon Bedrock" src="https://img.shields.io/badge/Amazon%20Bedrock-GenAI-6B42C1?style=flat-square&logo=amazonwebservices&logoColor=white"></a>
  <a href="#stack-at-a-glance"><img alt="Grounded RAG" src="https://img.shields.io/badge/RAG-hybrid%20retrieval-635BFF?style=flat-square"></a>
  <a href="#why-there-are-two-gateways"><img alt="Model Context Protocol" src="https://img.shields.io/badge/MCP-governed%20tools-24292F?style=flat-square"></a>
  <a href="#what-the-product-offers"><img alt="Google OR-Tools" src="https://img.shields.io/badge/OR-Tools-CP-SAT%20matching-4285F4?style=flat-square&logo=google&logoColor=white"></a>
  <a href="#what-the-product-offers"><img alt="Human approval" src="https://img.shields.io/badge/AI%20decisions-human%20approved-5D6875?style=flat-square"></a>
</p>

<p align="center">
  <a href="#aws-architecture"><img alt="Amazon Web Services" src="https://img.shields.io/badge/AWS-serverless-FF9900?style=flat-square&logo=amazonwebservices&logoColor=white"></a>
  <a href="#aws-architecture"><img alt="AWS Lambda" src="https://img.shields.io/badge/AWS%20Lambda-compute-FF9900?style=flat-square&logo=awslambda&logoColor=white"></a>
  <a href="#aws-architecture"><img alt="AWS Step Functions" src="https://img.shields.io/badge/Step%20Functions-orchestration-E7157B?style=flat-square"></a>
  <a href="#deploy-to-aws"><img alt="Terraform" src="https://img.shields.io/badge/Terraform-IaC-844FBA?style=flat-square&logo=terraform&logoColor=white"></a>
  <a href="#run-locally"><img alt="Docker Compose" src="https://img.shields.io/badge/Docker%20Compose-local%20dev-2496ED?style=flat-square&logo=docker&logoColor=white"></a>
  <a href="#engineering-confidence"><img alt="GitHub Actions" src="https://img.shields.io/badge/GitHub%20Actions-CI%2FCD-2088FF?style=flat-square&logo=githubactions&logoColor=white"></a>
  <a href="#stack-at-a-glance"><img alt="OpenTelemetry" src="https://img.shields.io/badge/OpenTelemetry-observability-425CC7?style=flat-square&logo=opentelemetry&logoColor=white"></a>
</p>

<p align="center">
  <a href="#what-the-product-offers">Features</a> ·
  <a href="#aws-architecture">Architecture</a> ·
  <a href="#stack-at-a-glance">Tech stack</a> ·
  <a href="#security-model">Security</a> ·
  <a href="#run-locally">Quick start</a> ·
  <a href="#deploy-to-aws">AWS deployment</a> ·
  <a href="#join-the-project">Contribute</a>
</p>
SecondChance is a source-available coordination platform, free for non-profit and charitable organisations, that helps surplus food reach people instead of becoming waste. Donors publish available food, NGO networks organise the work, coordinators reserve offers, and authorised people remain in control of every operational decision.

The platform combines a multilingual web application, strict tenant isolation, asynchronous workers, grounded knowledge search and governed AI agents. AI can retrieve procedures, explain evidence and prepare a plan; it cannot silently allocate food or bypass a human approval.

## See it in action

| Public landing and local demo access | Coordinator assistant |
|---|---|
| <img src="docs/images/interface-landing.png" alt="SecondChance landing page with language selection and demo users" width="390"> | <img src="docs/images/interface-assistant.png" alt="SecondChance coordinator assistant with suggested requests" width="390"> |

The interface is responsive and available in English, Danish, Polish and Italian. Navigation is adapted to the active membership, while the API independently enforces every permission.

## What the product offers

- **Donor, NGO and team onboarding.** People register as a donor, an organisation, a volunteer, centre staff or a coordinator. Network and platform administrators review every request before access becomes active; centre staff are approved for one centre.
- **Surplus offer management.** Donors publish quantities, categories, storage conditions and collection windows. Coordinators see only offers available to their network and can reserve them safely under concurrency.
- **Receiving centres.** Each centre declares its daily capacity, accepted food categories, storage (ambient, chilled, frozen), location and weekly opening slots in its own time zone. Administrators manage every centre; centre staff manage their own.
- **Matching with OR-Tools.** A coordinator starts a matching run; an asynchronous worker applies deterministic rules (category, storage, opening slot, use-by and the country's best-before rule, capacity) and then solves the allocation with the CP-SAT solver under a time limit. Every proposal explains the constraints it satisfies and lists alternatives; every offer left out says why. Fixed inputs give the same result, recorded with an input checksum.
- **Human-controlled execution.** A proposal reserves nothing. An authorised coordinator approves it by confirming its content hash, may pick an alternative centre and assigns a volunteer; deterministic application code then reserves the offer atomically, creates the mission, notifies and audits, in one transaction.
- **Missions.** Volunteers accept, pick up and deliver their own missions, or report a problem; centre staff confirm receipt or record an exception; coordinators reassign or cancel. Transitions are idempotent, audited and enforced by the database, and a failure is handled by reassigning the same mission, never by a duplicate.
- **Notifications.** Every event that needs a person creates an in-app notification only its recipient can read. Mission assignments and cancellations also leave by email through an outbox: the address is looked up in the identity provider and the message holds no offer or beneficiary data.
- **Operations dashboard.** Offers, missions, kilograms received, on-time and failure rates, median time to allocation, proposals waiting, centre capacity and food by category, as aggregates only.
- **Shared operational knowledge.** Administrators upload PDFs into role-aware knowledge spaces. Documents are parsed and indexed in the background, then searched with PostgreSQL full-text search and `pgvector`.
- **Grounded answers.** Answers cite the retrieved document sections. If the evidence is weak or a Bedrock guardrail rejects the answer, the system abstains instead of guessing.
- **Hybrid intent routing.** `/assist` chooses the least expensive safe path: direct operation, search, one specialist, a multi-agent plan or a clarification request.
- **Governed specialist agents.** A supervisor may compose a plan only from the versioned specialist catalog. Agent output cannot invent permissions or grant itself tools.
- **MCP tool governance.** Every agent tool call crosses a dedicated MCP Gateway that validates schemas, checks the agent and role allow-lists, applies distributed quotas, writes an audit event and invokes only the private tool executor.
- **Privacy and operations by design.** The project includes tenant Row-Level Security, append-only audit records, data minimisation, retention jobs, OpenTelemetry, CloudWatch alarms and an account-wide AWS budget.

## AWS architecture

![SecondChance AWS architecture as deployed by Terraform: CloudFront with WAF, the HTTP and WebSocket APIs, Cognito, Lambda functions in a private VPC without NAT, RDS Proxy and Aurora, SQS, Step Functions, EventBridge Scheduler, DynamoDB, S3, Bedrock, SES, and the three Lambda functions that run outside the VPC with no data permission](docs/images/aws-architecture.png)

[Open the full-resolution image](docs/images/aws-architecture.png) · [SVG](docs/images/aws-architecture.svg), generated by [`scripts/architecture-diagram.py`](scripts/architecture-diagram.py); it mirrors `infra/terraform/modules/secondchance`, which remains the source of truth.

The order is intentional:

1. **AWS WAF and CloudFront are the web front door.** WAF filters edge traffic; CloudFront serves the React application from a private S3 bucket through Origin Access Control.
2. **Cognito establishes identity; API Gateway protects the backend.** The browser signs in with Cognito Hosted UI and PKCE, then sends the JWT to API Gateway. The gateway validates the token and applies throttling before the request can reach FastAPI.
3. **The API Lambda performs application authorisation.** Memberships and capabilities come from PostgreSQL, not from user-controlled claims. Requests are rejected before expensive work when they are malformed, oversized, unsupported or over quota.
4. **Durable orchestration separates the request from the AI run.** The API starts one AWS Step Functions Standard Workflow per agent run. The workflow can outlive any individual compute invocation and calls a short, idempotent agent step at a time. SQS remains the durable buffer for document ingestion and real-time delivery events.
5. **Private compute performs bounded work.** The jobs worker parses and indexes documents. The agent-step runtime executes one supervisor or specialist turn, commits its state and shared memory, then returns control to Step Functions. No long-running supervisor process has to remain reachable.
6. **The MCP Gateway stands in front of every agent tool.** Agents cannot invoke the domain executor directly. The gateway is a separate Lambda, image, IAM role, log group and concurrency bulkhead.
7. **The tool executor stays private.** Only the MCP Gateway role can invoke it. It runs approved read-only knowledge tools against tenant-scoped data.
8. **Data and model access remains private.** Application compute runs in private subnets across two Availability Zones. Aurora is reached through RDS Proxy, while S3, SQS, DynamoDB, Secrets Manager, Lambda, Step Functions and Bedrock use VPC endpoints; the VPC has no NAT gateway.
9. **The browser receives real-time progress safely.** Agent steps publish small status events to SQS. A public relay with no database permission delivers them through API Gateway WebSockets. The UI keeps polling as a recovery path. Only committed, policy-checked results are exposed; raw model tokens are not streamed before guardrails.
10. **Allocation and missions stay deterministic.** Matching runs are jobs on the `jobs` queue: the same worker Lambda that ingests documents runs the OR-Tools CP-SAT solver inside the VPC and writes pending proposals. Approval, reservation and mission creation are API transactions, never agent or solver actions.
11. **Mission emails leave through a data-free relay.** The API writes the notification and an outbox row in the approval transaction and hands identifiers to the `notify` queue after the commit. A notifier Lambda outside the VPC, like the real-time relay and with no data permission, resolves the volunteer's verified address in Cognito and sends a fixed template through Amazon SES; the recovery job re-sends anything whose hand-off failed.

### Production controls highlighted in the diagram

The diagram highlights four explicit production controls implemented by the stack:

| Control | Placement | Why it exists |
|---|---|---|
| **Step Functions Standard Workflow** | between the application API and the agent-step runtime | owns the durable supervisor loop, retries transient compute failures and removes the 15-minute Lambda limit from the overall run |
| **RDS Proxy** | between all application database clients and Aurora | pools connections, absorbs Lambda concurrency spikes and preserves IAM database authentication |
| **API Gateway WebSocket API** | parallel to the HTTP API, in front of the browser event channel | sends progress and final-state events without holding a 29-second HTTP request open |
| **Run circuit breaker** | enforced transactionally in Aurora after every step | stops immediately when the run reaches 12 steps, 60,000 tokens or its deadline; the UI exposes the consumed and maximum budgets |

### Why there are two gateways

| Boundary | What it protects | What it allows through |
|---|---|---|
| **API Gateway** | the public application backend | authenticated, throttled HTTP requests from the web app |
| **MCP Gateway** | private tools, data and model-backed operations | schema-valid calls from approved agents and roles, within quota |

The API Gateway is the public ingress. The MCP Gateway is an internal policy enforcement point. Putting the MCP Gateway after the agent-step runtime and before the tool executor prevents model output from becoming direct infrastructure access.

## Runtime flows

### A normal application request

```text
Browser
  → WAF / CloudFront → private S3 web application
  → Cognito Hosted UI → JWT
  → API Gateway JWT authorizer + throttling
  → FastAPI Lambda → tenant transaction → Aurora / S3 / SQS / Bedrock
```

### A governed agent tool call

```text
Browser → API Gateway HTTP API → API Lambda → Step Functions Standard Workflow
  → Agent Step Runtime [one bounded supervisor or specialist turn]
  → MCP Gateway [schema + allow-list + role + quota + audit]
  → private Tool Executor Lambda
  → RDS Proxy → tenant-scoped Aurora / S3 / Bedrock operation
  → SQS real-time events → WebSocket relay → API Gateway WebSocket → Browser
```

### A grounded knowledge answer

```text
Question → tenant and role context → hybrid retrieval (FTS + pgvector)
  → evidence threshold → Bedrock Converse + Guardrail
  → cited answer, or an explicit abstention
```

The detailed visual flows are available as standalone documents:

- [AWS architecture](docs/diagrams/01-aws-architecture.html)
- [Human approval sequence](docs/diagrams/02-fl01-approval-sequence.html)
- [Grounded RAG flow](docs/diagrams/03-fl02-rag-flow.html)

## Stack at a glance

| Layer | Technology | Responsibility |
|---|---|---|
| Web | React, TypeScript, Vite, nginx | multilingual, capability-aware user experience |
| Identity | Amazon Cognito, Hosted UI, OAuth 2.0 PKCE | sign-in and short-lived JWTs |
| Public API | API Gateway HTTP API, JWT authorizer | public ingress, token validation and throttling |
| Application | FastAPI on AWS Lambda | domain API, admission control, permissions and orchestration |
| Orchestration | Step Functions Standard, bounded Lambda steps | durable multi-agent loop, retries and state transitions without a 15-minute workflow ceiling |
| Workers | Lambda, SQS, dead-letter queues | document ingestion, OR-Tools matching and asynchronous event delivery |
| Optimisation | Google OR-Tools CP-SAT in the jobs worker | reproducible offer-to-centre allocation under capacity, slot, storage and expiry constraints |
| Notifications | in-app rows under RLS, SQS outbox, notifier Lambda, Cognito lookup, Amazon SES | mission emails without offer or beneficiary data, retried and dead-lettered |
| Tool boundary | MCP Gateway Lambda, DynamoDB quotas | tool policy, validation, audit and rate limiting |
| Private tools | Tool Executor Lambda | approved domain operations with no public route |
| Relational and vector data | RDS Proxy, Aurora PostgreSQL Serverless v2, PostGIS, pgvector | pooled IAM-authenticated connections, tenant data, workflow state, full-text and vector search |
| Object data | Amazon S3, KMS | tenant-prefixed source documents and objects |
| Generative AI | Amazon Bedrock Converse, Titan Text Embeddings, Bedrock Guardrails | routing, generation, embeddings and safety checks |
| Real-time channel | API Gateway WebSocket, DynamoDB connection registry, SQS relay | authenticated run subscriptions and immediate committed-state updates |
| Network | private VPC, two Availability Zones, VPC endpoints, no NAT | private service connectivity and reduced egress exposure |
| Operations | CloudWatch, X-Ray, SNS, AWS Budgets, OpenTelemetry | logs, traces, metrics, alarms and cost awareness |
| Delivery | Terraform, ECR, GitHub Actions OIDC | reproducible infrastructure and keyless deployment |

## Security model

- PostgreSQL Row-Level Security is the final tenant boundary. Every tenant transaction sets `app.tenant_id`, `app.role` and `app.subject` before the first query.
- Roles live in the `membership` table and are checked on the server. Hiding a screen in React is never treated as authorisation.
- Each compute family has a separate least-privilege IAM role. Database connections use short-lived IAM authentication tokens through RDS Proxy rather than application passwords.
- S3, Aurora, logs, DynamoDB and secrets are encrypted with KMS. S3 Block Public Access is enabled.
- Guardrails are applied around model-backed answers. Prompts are not written to normal application logs.
- GitHub Actions assumes an AWS role through OIDC. The deployment path does not create or store long-lived AWS access keys.
- The MCP Gateway validates model-proposed tool use before any domain executor is invoked.

For the full analysis, see the [threat model](docs/security/threat-model.md), [GDPR notes](docs/compliance/gdpr.md) and [architecture decisions](docs/ADR.md).

## Engineering confidence

*The quality and security badges above reflect the last checks documented below; they are not live GitHub Actions status indicators.*

**Confidence level: high.**

| Evidence | Result |
|---|---|
| API test suite (real PostgreSQL with RLS, ElasticMQ, SeaweedFS) | 290 passing tests |
| MCP Gateway test suite | 6 passing tests |
| Frontend test suite | 22 passing tests |
| Frontend type-check and production build | passed |
| Python lint for API and MCP Gateway | passed |
| Terraform formatting and validation | passed for bootstrap, demo and pilot stacks |
| Terraform offline tests | 2 passing infrastructure tests, including the notifier, SES sender and queue wiring |
| IaC security scan | no HIGH or CRITICAL findings |
| Shell deployment scripts | ShellCheck passed |
| AWS Lambda Runtime Interface Emulation (CI job `aws-emulation`) | 13 end-to-end tests on the deployable images, including OR-Tools matching through the jobs function and mission emails through the notifier function |

Account-specific aspects (Bedrock model access and quotas, regional service availability, the SES sender verification and sandbox status, Lambda concurrency quotas, live VPC endpoint policies) are checked by `connect-aws` before Terraform runs and by `verify-aws.sh` after every deployment, which also invokes the private `runtime-check` probe: Aurora through RDS Proxy, Titan embeddings, Claude Converse, the Guardrail, the hybrid router and the OR-Tools solver.

## Run locally

You need Docker with Compose v2 and [uv](https://docs.astral.sh/uv/). Node is needed only when running the frontend outside Docker.

```bash
docker compose up -d
```

Open [http://localhost:8088](http://localhost:8088). The local environment uses simulated OIDC and synthetic users; no AWS account is required.

| Service | Local address | AWS equivalent |
|---|---|---|
| `web` | http://localhost:8088 | CloudFront + private S3 |
| `api` | http://localhost:8000 | API Gateway + API Lambda |
| `db` | 127.0.0.1:5432 | Aurora PostgreSQL |
| `queue` | 127.0.0.1:9324 | Amazon SQS |
| `storage` | 127.0.0.1:8333 | Amazon S3 |
| `mcp-gateway` | 127.0.0.1:8010 | MCP Gateway Lambda |
| `tool-executor` | private Compose network | private Tool Executor Lambda |
| `agents-worker`, `jobs-worker` | private Compose network | queue-triggered Lambdas (the jobs worker also runs the OR-Tools solver) |
| `notify-worker` | private Compose network | notifier Lambda (Cognito lookup + SES) |
| `mail` | http://localhost:8025 | Amazon SES: every mission email lands here and never leaves the machine |
| `lgtm` profile | http://localhost:3000 | CloudWatch, X-Ray and an OTLP collector |

Every published local port is bound to `127.0.0.1`.

### Demo users

| User | Role | Main capabilities |
|---|---|---|
| `demo-platform-admin` | platform administrator | review networks and manage documents |
| `demo-it-admin`, `demo-dk-admin` | network administrator | review members, manage documents and coordinate work |
| `demo-it-coordinator`, `demo-dk-coordinator` | coordinator | dashboard, matching and approval, missions, reservations, assistant |
| `demo-it-donor`, `demo-dk-donor` | donor | publish and review their own offers, set the pickup location |
| `demo-it-volunteer`, `demo-dk-volunteer` | volunteer | accept, pick up and deliver missions; search shared knowledge |
| `demo-it-center`, `demo-dk-center` | centre staff | configure their centre and its opening slots, confirm receipts |

To see FL-01 end to end: publish an offer as a donor, run matching and approve a proposal as a coordinator, move the mission forward as the volunteer, confirm the receipt as centre staff, then open the dashboard. The volunteer's email is in the local mail catcher.

### Useful local commands

```bash
# API tests
cd api && uv run pytest

# MCP Gateway tests
cd mcp-gateway && uv run pytest

# Frontend tests and production build
cd web && npm ci && npm test && npm run build

# Optional local observability
OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318 docker compose --profile observability up -d
```

Reset the local data with `docker compose down -v`.

## Deploy to AWS

The Windows entry point performs identity login, account preflight, state bootstrap, image build, Terraform apply, database migration, demo seeding, web publication and live verification:

```powershell
.\scripts\connect-aws.ps1 -Environment demo -AlarmEmail you@example.org
```

For macOS or Linux:

```bash
export SECONDCHANCE_ALARM_EMAIL=you@example.org
# optional: the SES sender of mission emails (default: the alarm address)
export SECONDCHANCE_NOTIFICATION_SENDER=missions@example.org
scripts/connect-aws.sh demo
```

SES sends a verification link to the sender address on the first apply; mission emails start once it is confirmed. In-app notifications work from the start.

The deployment uses IAM Identity Center where available and can create a repository-scoped GitHub OIDC role. See [Deploying to AWS](docs/deployment.md) for prerequisites, account bootstrap, costs, teardown and the acceptance checks.

## Deploy to Azure

The same code and the same images run on Azure: choose the cloud when you deploy ([ADR-023](docs/ADR.md#adr-023--multi-cloud-the-same-code-on-azure-with-adapters-container-apps-and-entra)).

```bash
az login
export SECONDCHANCE_ALARM_EMAIL=you@example.org
scripts/connect.sh azure demo        # preflight, bootstrap, deployment, verification
```

Container Apps scaled by KEDA, Front Door with a WAF, PostgreSQL flexible server with Entra authentication, Service Bus, Blob Storage, Azure OpenAI in the EU data zone with Azure AI Content Safety, Web PubSub, Communication Services and Defender for Storage; every service is reached with a managed identity and no secret exists. The Terraform module is evaluated offline by `terraform test` with the provider's own validators, and a preflight checks what only your subscription knows. See [Deploying to Azure](docs/deployment-azure.md) for the architecture, the mapping from AWS, prerequisites, costs, the verification checklist and what is not the same.

## Repository map

```text
api/          FastAPI, domain services, agents, workers, migrations and tests
web/          React application, role-aware screens and four language packs
db/           PostgreSQL image and local role bootstrap
mcp-gateway/  independent MCP policy enforcement service
infra/        Terraform for AWS (infra/terraform) and Azure (infra/terraform/azure), and the AWS runtime emulation
scripts/      build, connect, deploy, verify, bootstrap-admin and destroy flows
local/        local service configuration
docs/         product, architecture, decisions, compliance, operations and diagrams
```

## Documentation

| Document | Purpose |
|---|---|
| [Product requirements](docs/PRD.md) | goals, users, features, metrics and scope |
| [Architecture](docs/architecture.md) | components, data model and runtime flows |
| [Architecture decisions](docs/ADR.md) | important decisions and rejected alternatives |
| [Agent guide](docs/agents.md) | governed specialists, planning and tool rules |
| [AWS deployment](docs/deployment.md) | credentials, bootstrap, deployment and verification |
| [Azure deployment](docs/deployment-azure.md) | the same on Azure: architecture, mapping, preflight, verification, differences, costs |
| [Operations](docs/operations/README.md) | SLOs, alerts and runbooks |
| [Threat model](docs/security/threat-model.md) | threats, controls and residual risks |
| [GDPR notes](docs/compliance/gdpr.md) | data roles, minimisation and retention |

## Join the project

This repository is the starting point of SecondChance. The architecture, the operational core (centres, matching, approval, missions, notifications, dashboard), the local stack, the one-command AWS deployment and the test suites are in place; what comes next is shaped by the organisations that adopt it and the people who build it with them. Contributions are welcome, from code to field knowledge:

- tailoring the platform to a real NGO: its procedures, roles, languages and specialist agents;
- deployment reports from new AWS accounts and regions, against the checks in [docs/deployment.md](docs/deployment.md);
- OCR for scanned PDFs and direct-to-S3 uploads for large documents;
- multi-stop route optimisation for volunteers (FR-024) and an offline-first PWA for missions (FR-027);
- accessibility reviews, translations and load tests.

Start with [CONTRIBUTING.md](CONTRIBUTING.md), which also explains the contributor terms. Security issues follow [SECURITY.md](SECURITY.md).

## Licence

SecondChance is source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE). Copyright (c) 2026 Pierfrancesco Lijoi.

- **Free for noncommercial use**, including use by charitable and non-profit organisations, educational institutions, public research and health organisations and public bodies, whatever their funding.
- **Commercial use needs a written licence from the author**: selling the software, offering it as a paid service, or using it in a for-profit business. Open an issue titled "Commercial licence" or contact [@PierfrancescoLijoi](https://github.com/PierfrancescoLijoi).
- Contributions are accepted under the terms in [CONTRIBUTING.md](CONTRIBUTING.md), so the project stays free for non-profits while its author can still license it commercially.
