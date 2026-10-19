# SecondChance — Operations

How SecondChance is observed, alerted on and fixed. References: [PRD](../PRD.md) (NFR-006…011, NFR-023, NFR-025, FR-026), [ADR](../ADR.md) (001, 005, 006, 010–014), [GDPR](../compliance/gdpr.md).

**Scope.** The SLOs apply to the managed pilot. They do not apply to the ephemeral demo (NFR-009): the DLQ, 5xx and cost alarms remain. Locally this document is used to try out instrumentation, queries and dashboards before the cloud.

**Status.** In the code: correlation ID, redacted JSON logs on stdout, OTLP export of traces, metrics and logs ([`api/secondchance/observability.py`](../../api/secondchance/observability.py)) and the counters `secondchance.admission.rejections`, `secondchance.offers.reservations`, `secondchance.routing.decisions`, `secondchance.agent.steps`, `secondchance.agent.tokens`, `secondchance.experiment.exposures`, `secondchance.ingestion.versions`, `secondchance.knowledge.answers`. In Terraform: log groups with 30-day retention, the alarms marked "in Terraform" in §3 (the `notify` queue age included), encrypted SNS and AWS Budgets. Operations metrics: `secondchance.matching.runs`, `secondchance.matching.solve_ms`, `secondchance.proposals.decisions`, `secondchance.missions.transitions`, `secondchance.notifications.handoffs`, `secondchance.notifications.email` (outcome `sent`, `refused`, `recipient_unknown`). The rest of this document (SLOs, burn rates, dashboards, the `live` alias) is the plan for the pilot.

## 1. Principles

- **SLO-driven alarms.** Alert when the error budget burns too fast (burn rate), not on every error.
- **Symptoms, not causes.** Alert on what users see: errors, latency, late notifications. CPU, ACUs and cold starts belong on dashboards, for diagnosis. The exceptions, because they announce certain damage, are a non-empty DLQ, Aurora connections near the limit, and costs.
- **Every alarm has a runbook.** The link goes in the `AlarmDescription`. No alarm without a runbook; one that always fires for nothing is fixed or deleted.
- **No PII in telemetry.** The log formatter keeps only allowed attributes and runs text through redaction (ADR-012). Names, emails, phone numbers, request text and prompts are never recorded (ADR-008), nor `Authorization` and cookies. The pseudonymous `sub` may appear in a log, never as a metric dimension. `tenant_id` as a dimension is fine while tenants are few.
- **One maintainer, one channel.** Alarms through SNS to email. No 24/7 on-call: response times are in [section 7](#7-incident-management).

## 2. SLIs and SLOs

Window: rolling 30 days. The NFR-009 availability report uses the calendar month. AWS source: Application Signals (SLOs on service and operation) or CloudWatch metrics. Local source: the Prometheus inside `otel-lgtm`.

| SLO | SLI (good events / valid events) | Target | Error budget (30 days) | AWS source | Local source |
|---|---|---|---|---|---|
| API availability | non-5xx responses / all requests, excluding `/health` and 4xx | 99.5% | 0.5% of requests (≈ 3 h 36 min of total downtime) | Application Signals, service `secondchance-api` | `http_server_request_duration_seconds_count` by `http_response_status_code` |
| Read latency | CRUD `GET` with 2xx under 500 ms / CRUD `GET` with 2xx | 95% (= p95 < 500 ms, NFR-007) | 5% of reads over 500 ms | Application Signals, latency SLO per operation | `http_server_request_duration_seconds` histogram |
| RAG latency | assistant answers under 10 s, abstentions included / answers requested | 95% (= p95 < 10 s, NFR-008) | 5% over 10 s | Application Signals, RAG operation | same histogram, RAG route |
| Notifications | notifications accepted by SES within 60 s of the approval commit / notifications generated | 99% (FR-026) | 1% late or failed | metric `secondchance.notification.delay` | same metric |
| Empty DLQs | visible messages in the `jobs`, `notify`, `agents` DLQs | 0 | none: every message is an incident | `AWS/SQS` `ApproximateNumberOfMessagesVisible` | CLI on ElasticMQ ([section 5](#5-local-observability)) |
| Agent run success | runs ending `succeeded` or `waiting_approval` / runs ending also `failed` or `budget_exhausted` (`cancelled` excluded) | 95%, to recalibrate after 4 weeks of data | 5% of runs | metric `secondchance.agent.runs` by `status`; `agent_run` table | same |
| Router agreement in shadow mode | pairs in `routing_decision` where `rizzo_flow` picks the same `route` as `baseline` / pairs with both decisions | none: an indicator, not an SLO (ADR-007) | — | weekly SQL query; `secondchance.router.shadow.agreement` | same |

- In the pilot Aurora's minimum capacity is > 0: a request failing because of a resume from pause counts as bad. In the demo it is accepted behaviour.
- Notifications are measured until SES accepts them, not until delivery to the mailbox. Bounces and complaints are on the service dashboard.
- For shadow agreement, also look at each router's agreement with the class the operator then used, split by language (English, Danish, Polish, Italian). It feeds the P6 benchmark, not alarms.
- `http_server_*` are the OTel semantic conventions (`http.server.request.duration`, seconds) with names translated by Prometheus; the stack sets `OTEL_SEMCONV_STABILITY_OPT_IN=http` so FastAPI emits them. The `secondchance.*` names not listed under "Status" are proposals.

## 3. Alarms

Burn rate = observed error rate / rate allowed by the SLO. Two windows, each confirmed by a short window so the alarm clears quickly once the problem is solved:
- **fast:** burn rate > 14.4 over 1 h and over 5 min (2% of the monthly budget in one hour);
- **slow:** burn rate > 6 over 6 h and over 30 min (5% of the budget in six hours).

With little traffic a single error makes the burn rate shoot up, so every SLO alarm also needs at least 20 events in the long window. On AWS: Application Signals SLO burn rates, or CloudWatch metric math.

Today the Terraform ([`observability.tf`](../../infra/terraform/modules/secondchance/observability.tf)) creates `api-5xx`, an alarm on the errors of each function, `dlq-*`, `queue-age-*`, the budget and the GuardDuty findings rule, all to an SNS topic with an email subscription. The others are the proposal for the pilot.

| Alarm | Condition | Severity | Runbook |
|---|---|---|---|
| `slo-availability-fast` / `-slow` | availability burn rate, fast / slow window | SEV2 / SEV3 | [RB-02](#rb-02-5xx-spike) |
| `slo-read-latency-fast` / `-slow` | read latency burn rate | SEV2 / SEV3 | [RB-03](#rb-03-high-latency) |
| `slo-rag-latency-fast` / `-slow` | RAG latency burn rate | SEV3 / SEV3 | [RB-03](#rb-03-high-latency) |
| `slo-notification-fast` / `-slow` | notification burn rate | SEV2 / SEV3 | [RB-01](#rb-01-dlq-not-empty) |
| `slo-agent-runs-fast` / `-slow` | run success burn rate | SEV3 / SEV3 | [RB-07](#rb-07-agents-out-of-budget) |
| `dlq-notify`, `dlq-jobs`, `dlq-agents` (in Terraform) | `ApproximateNumberOfMessagesVisible` > 0 in one period | SEV2 `notify`, SEV3 the others | [RB-01](#rb-01-dlq-not-empty) |
| `queue-age-*` (in Terraform) | `ApproximateAgeOfOldestMessage` is high on `notify`, `jobs` or `realtime-events` | SEV2 `notify`/real-time, SEV3 jobs | [RB-01](#rb-01-dlq-not-empty) |
| `agent-workflow-*` | a Step Functions agent execution failed or timed out instead of reaching a controlled terminal state | SEV2 | inspect the Standard Workflow history, then the matching `agent-step` log by correlation ID |
| `api-5xx-rate` (in Terraform) | 5xx / requests > 5% over 5 min, at least 20 requests (API Gateway `5xx`, `Count`). Active in the demo too | SEV2 | [RB-02](#rb-02-5xx-spike) |
| `aurora-connections` | `DatabaseConnections` > 80% of `max_connections` for 10 min | SEV3 | [RB-04](#rb-04-aurora-connections-exhausted-or-resuming-from-pause) |
| `bedrock-throttling` | `AWS/Bedrock` `InvocationThrottles` > 0 in 3 consecutive 5-minute periods | SEV3 | [RB-05](#rb-05-bedrock-throttling) |
| `guardrail-spike` | guardrail interventions / calls > 10% over 1 h, at least 20 calls | SEV3 | [RB-06](#rb-06-spike-of-guardrail-interventions-or-rag-abstentions) |
| `rag-abstention-spike` | abstentions / questions > 30% over 1 h, at least 20 questions | SEV3 | [RB-06](#rb-06-spike-of-guardrail-interventions-or-rag-abstentions) |
| `agent-budget-exhausted` | runs in `budget_exhausted` / finished runs > 10% over 6 h, at least 10 runs | SEV3 | [RB-07](#rb-07-agents-out-of-budget) |
| `cost-budget` (in Terraform) | AWS Budgets: actual spend at 50, 80, 100% and forecast at 100% of the monthly budget | SEV3; SEV2 if the forecast exceeds 150% | [RB-08](#rb-08-cost-anomaly) |
| `cost-anomaly` | Cost Anomaly Detection, per-service monitor, impact over the threshold (e.g. $10) | SEV3 | [RB-08](#rb-08-cost-anomaly) |
| `guardduty-findings` (in Terraform) | a GuardDuty finding of severity 7 or more, an infected upload included (EventBridge to the alarm topic) | SEV2; SEV1 if personal data may be involved | [RB-11](#rb-11-guardduty-finding-or-infected-upload) |

Fixed thresholds on guardrails and abstentions move to CloudWatch anomaly detection once there are two weeks of data. Budgets and anomaly detection warn and do not stop spending (PRD §6).

## 4. Dashboards

Three CloudWatch dashboards defined in Terraform, reserved to the platform administrator. Locally the same panels in Grafana. The dashboard for organisations is something else: it lives in the application (FR-052).

| Dashboard | Panels |
|---|---|
| **Service** (`secondchance-service`) | SLO status and remaining error budget · RED per route (requests, 4xx and 5xx, p50/p95/p99 latency) · 409 reservation conflicts (FR-016), kept apart from errors · Lambda per function: invocations, errors, throttles, concurrent executions against reserved concurrency, `Init Duration` · Aurora: ACUs (`ServerlessDatabaseCapacity`), connections against `max_connections`, CPU, read and write latency · `jobs`, `notify`, `agents` queues: depth, age of the oldest message, DLQs · notifications: p99 delay, sends, SES bounces and complaints · admission rejections by stage and reason |
| **Agents and AI** (`secondchance-agents`) | runs by status and success rate against the SLO · steps per run, tokens in/out and estimated cost per agent and per day · p95 latency per agent and per Bedrock call, throttling · tool errors by `error_category` · guardrail interventions by type (prompt attack, grounding, PII) and RAG abstentions, per language · proposals created by agents and the share approved by operators (OBJ-05) · shadow mode: baseline/Rizzo Flow agreement, agreement with the operator's class, Rizzo Flow errors and latency, `model_fingerprint` |
| **Business** (`secondchance-business`) | from domain events, aggregated per tenant, without personal data (FR-053) · offers by status (published, reserved, collected, delivered, expired) · median time from offer to allocation (OBJ-01) · share collected before expiry (OBJ-02) · allocations with reason, operator and timestamp (OBJ-03) · missions completed and failed, centre exceptions · kilograms recovered, only if measured |

## 5. Local observability

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://lgtm:4318 docker compose --profile observability up -d
```

The profile adds `lgtm` (`grafana/otel-lgtm`, version pinned in [`docker-compose.yml`](../../docker-compose.yml)): OTel collector, Tempo, Loki, Prometheus and Grafana in one container, with OTLP on 4318 (HTTP) and 4317 (gRPC). The variable must come from the shell or `.env`: without it export stays off even with the profile on. Services are named `secondchance-api`, `secondchance-agents-worker` and `secondchance-jobs-worker` (`OTEL_SERVICE_NAME`).

- Grafana: http://localhost:3000 → **Explore**: Tempo for traces, Loki for logs, Prometheus for metrics.
- **Logs.** Logs go to stdout as JSON and, with the endpoint set, to Loki over OTLP. Without the profile: `docker compose logs api agents-worker jobs-worker | grep <correlation_id>`.
- **Queues.** ElasticMQ exports no metrics. Depth and DLQs are read with the CLI (fake credentials and region): `aws sqs get-queue-attributes --endpoint-url http://localhost:9324 --queue-url http://localhost:9324/000000000000/notify-dlq --attribute-names ApproximateNumberOfMessages`. Queues and DLQs are in [`local/elasticmq.conf`](../../local/elasticmq.conf).

Sample queries:

```logql
{service_name="secondchance-api"} | json | correlation_id = "<correlation_id>"
```
When logs arrive over OTLP, `correlation_id` is structured metadata and `| json` is not needed.

```traceql
{ resource.service.name = "secondchance-api" && span.http.response.status_code >= 500 }
```
Copy `trace_id` from a log line and search for it directly in Tempo.

```promql
# p95 of reads per route
histogram_quantile(0.95,
  sum by (le, http_route) (
    rate(http_server_request_duration_seconds_bucket{http_request_method="GET"}[5m])))

# share of 5xx
sum(rate(http_server_request_duration_seconds_count{http_response_status_code=~"5.."}[5m]))
/ sum(rate(http_server_request_duration_seconds_count[5m]))
```

On AWS, search by correlation ID in CloudWatch Logs Insights:
```
fields ts, level, logger, message, trace_id
| filter correlation_id = "<correlation_id>"
| sort ts asc
```

## 6. Runbooks

Common first step: from the alarm to a concrete case (`correlation_id` or `trace_id`), then the trace in X-Ray or Transaction Search and the logs in Logs Insights. SQL queries run under RLS: set the tenant (`SELECT set_config('app.tenant_id', '<uuid>', false)`), or, for diagnosis only, use the migrator role, which owns the tables and sees every tenant, inside `BEGIN READ ONLY`.

### RB-01 DLQ not empty
**Symptoms.** `dlq-*`, `queue-age-*` or the notification burn rate. For `notify`: volunteers not receiving their mission.  
**Diagnosis.**
1. How many messages: `aws sqs get-queue-attributes --queue-url <dlq-url> --attribute-names ApproximateNumberOfMessages`.
2. Read them without consuming them: `aws sqs receive-message --queue-url <dlq-url> --max-number-of-messages 10 --visibility-timeout 0 --message-attribute-names All`. They carry only IDs and the `correlation_id` attribute (ADR-011).
3. With the `correlation_id`, find the consumer's error in logs and trace.
4. Classify: transient (Aurora resuming, Bedrock throttling, SES limit) or poison (bug, validation, a state no longer valid). A growing queue with an empty DLQ means a stopped consumer (event source mapping disabled, concurrency at zero).

**Mitigation.**
- Transient cause solved, or bug fixed and released: `aws sqs start-message-move-task --source-arn <dlq-arn>` moves the messages back to the source queue. It is safe because consumers are idempotent (NFR-006, ADR-005, ADR-010).
- Message no longer valid (expired proposal, cancelled run): record ID and reason in the incident, then delete it.
- `notify` with imminent missions: the coordinator warns the volunteers through the usual channels; the in-app notification is already there. Check SES quota and account status (sandbox, suspension for bounces), and that the sender identity is verified (`aws sesv2 get-email-identity`). `refused` outcomes in `secondchance.notifications.email` mean the SES sandbox or an unverified address, not a broken pipeline.
- `jobs` with a matching run: the run stays `running` until its lease expires; the recovery job re-sends it and the next worker claims it (at most five attempts, then `failed` with `attempts_exhausted`). Coordinators can start a new run once it is closed.

**Follow-up.** A regression test built on the case, with synthetic data; review `maxReceiveCount` and the visibility timeout.

### RB-02 5xx spike
**Symptoms.** `api-5xx-rate` or the availability burn rate.  
**Diagnosis.**
1. Application Signals: the operation with the most faults. Transaction Search: spans with `http.response.status_code >= 500`. Logs Insights: `filter level = "ERROR" | stats count(*) as n by error | sort n desc | limit 20`.
2. A recent release? The image tag the functions run and when it changed.
3. Lambda: `Throttles` (reserved concurrency saturated), `Duration` close to the timeout, API Gateway 504s (30 s limit, ADR-001).
4. Dependencies: Aurora ([RB-04](#rb-04-aurora-connections-exhausted-or-resuming-from-pause)), Bedrock ([RB-05](#rb-05-bedrock-throttling)).

**Mitigation.**
- Cause in the release: roll back ([section 9](#9-release-and-rollback)), then investigate.
- AI dependency down: switch off the RAG or agent flag. FL-01 must work without an LLM.
- Throttles: do not raise reserved concurrency blindly, it is sized on database connections (NFR-010).

**Follow-up.** A test that reproduces the error; a postmortem for SEV1 or SEV2.

### RB-03 High latency
**Symptoms.** Read or RAG latency burn rate.  
**Diagnosis.**
- Reads: in the trace, separate cold start (`Init Duration` in the Lambda `REPORT` line), slow queries (SQLAlchemy spans) and connection waits. Aurora: ACUs at the maximum or resuming from pause.
- RAG: compare the retrieval, reranker, Bedrock and guardrail spans; in Bedrock `InvocationLatency` and output tokens.
- Is an experiment on `prompt` or `retrieval` running (ADR-013)?

**Mitigation.**
- Queries: an index or a rewrite through a migration; higher maximum ACUs if the database is saturated.
- Cold starts dominating: provisioned concurrency on the API only, and only after a cost review.
- RAG: stop the experiment, switch off the reranker, reduce top-k and `maxTokens`.

**Follow-up.** Reproduce with k6 (NFR-007) and update the load-test baseline.

### RB-04 Aurora connections exhausted or resuming from pause
**Symptoms.** `too many connections` or `remaining connection slots are reserved` errors, connection timeouts. In the demo: the first request after a quiet period slow or failing.  
**Diagnosis.**
```sql
SHOW max_connections;
SELECT usename, application_name, state, count(*)
FROM pg_stat_activity GROUP BY 1, 2, 3 ORDER BY 4 DESC;
```
- Many `idle in transaction` sessions: a transaction left open by the code.
- `ConcurrentExecutions` per function: an SQS consumer scaling more than expected.
- `ServerlessDatabaseCapacity` at 0: the cluster was paused (demo only, minimum 0 ACU).

**Mitigation.**
- Lower the consumers' concurrency (`MaximumConcurrency` of the event source mapping) before the API's.
- `secondchance_app` closes idle transactions by itself after 30 s (`idle_in_transaction_session_timeout`, `db/bootstrap.sql`). Stuck sessions of other roles: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle in transaction' AND state_change < now() - interval '5 minutes';`
- Demo: a request that reads from the database (e.g. `GET /offers`) a few minutes before the session. Both environments use RDS Proxy; the pilot also keeps a non-zero Aurora floor (ADR-006).

**Follow-up.** Check the constraint: sum of reserved concurrencies × connections per instance (pool of 1) + migrator + administration ≤ 80% of `max_connections`. Check that the `secondchance_app` role timeouts (`statement_timeout`, `lock_timeout`, `idle_in_transaction_session_timeout`) also exist on Aurora.

### RB-05 Bedrock throttling
**Symptoms.** `bedrock-throttling`, `ThrottlingException` in logs, RAG latency rising, abstentions because of provider errors, slow runs.  
**Diagnosis.** Model and `eu.` profile involved (`ModelId` dimension); who consumes, i.e. tokens per caller (API, agents, ingestion), where repeated ingestion or a looping run are the usual cases; current quotas in Service Quotas (requests and tokens per minute per model).  
**Mitigation.**
- Retries with backoff and jitter already exist (NFR-017): do not add more downstream.
- Lower `MaximumConcurrency` on the `agents` and `jobs` queues; pause ingestion.
- RAG abstains and asks the user to try again (FR-035): the planned degradation.
- Never switch to `global.` profiles to get around the limit (ADR-002).

**Follow-up.** Estimate tokens per minute at the pilot's peak and request a quota increase in advance: it takes days.

### RB-06 Spike of guardrail interventions or RAG abstentions
**Symptoms.** `guardrail-spike` or `rag-abstention-spike`; operators reporting missing answers.  
**Diagnosis.** Prompts are not in the logs (ADR-008), so work from metadata.
- Type of intervention: prompt attack, grounding, PII. Concentrated on one tenant, one subject or one language?
- What changed: `prompt_sha256` and `model_id` of the steps, guardrail version, a running experiment.
- Ingestion: documents in the `jobs` DLQ or missing chunks lower the evidence and raise abstentions.
- The chunks' `embedding_model` consistent with the query's (ADR-011).
- Polish questions: lexical search uses word prefixes instead of a stemmer (ADR-019), so abstentions may be higher until a dictionary is added.

**Mitigation.**
- Experiment: kill switch ([section 9](#9-release-and-rollback)). New prompt or model: roll back.
- Ingestion: fix and run again, it is idempotent (FR-040); re-embed if the model changed.
- Do not lower guardrail thresholds to bring answers back without going through the golden set.
- Prompt attacks concentrated on one account: SEV2 security incident, user suspended in the IdP.

**Follow-up.** The cases, rewritten with synthetic data, go into the golden set; run the evaluation harness again (NFR-019).

### RB-07 Agents out of budget
**Symptoms.** `agent-budget-exhausted` or the run-success burn rate; expected proposals not arriving.  
**Diagnosis.** Which limit fires (steps, tokens or duration; defaults 12, 60,000, 10 min, ADR-010):
```sql
SELECT count(*) FILTER (WHERE steps_used >= max_steps)   AS steps,
       count(*) FILTER (WHERE tokens_used >= max_tokens) AS tokens,
       count(*) FILTER (WHERE updated_at >= deadline_at) AS duration
FROM agent_run
WHERE status = 'budget_exhausted' AND updated_at > now() - interval '24 hours';

SELECT seq, agent, status, attempt, error_category, input_tokens + output_tokens AS tok, latency_ms
FROM agent_step WHERE run_id = '<run_id>' ORDER BY seq;
```
Usual cases: the same specialist repeated with the same `error_category` (broken tool or dependency); the supervisor retrying a failing specialist; duration inflated by throttling ([RB-05](#rb-05-bedrock-throttling)) or by a slow solver job.  
**Mitigation.**
- Fix the tool or dependency; if the cause is a prompt or model change, kill switch or roll back.
- If needed, switch off the agent flag: deterministic workflows stay available.
- Raise the limits only with evidence that legitimate tasks need it and with the cost per run accepted.

**Follow-up.** The task goes into the agent's golden set; default limits are reviewed with the month's data.

### RB-08 Cost anomaly
**Symptoms.** An email from AWS Budgets or Cost Anomaly Detection.  
**Diagnosis.** Cost Explorer, daily granularity, last 7 days, by service and usage type. Usual culprits:
- Aurora not pausing in the demo: something keeps a connection open;
- Bedrock tokens: looping runs, repeated ingestion, an experiment with longer prompts;
- interface endpoints or a cluster left behind after a demo;
- logs: `SECONDCHANCE_LOG_LEVEL=DEBUG` left on, traces sampled at 100%;
- a NAT Gateway created by mistake (not planned, ADR-006).

The project's resources, tagged `project=secondchance`: `aws resourcegroupstaggingapi get-resources --tag-filters Key=project,Values=secondchance`.  
**Mitigation.** Demo: `scripts/destroy.sh demo`. Pilot: switch off the agent, RAG and ingestion flags; logs at `INFO`; less trace sampling and indexing; lower maximum ACUs.  
**Follow-up.** Tag the resources that were missing; update [section 10](#10-costs) and the budget thresholds.

### RB-09 Suspected cross-tenant leak
It is a security incident: **SEV1** until ruled out. Times, roles, evidence and notifications follow the breach runbook in [compliance/gdpr.md §8](../compliance/gdpr.md#8-personal-data-breaches-arts-33-34); here only the technical part.  
**Symptoms.** A user sees another organisation's data; RAG cites a document of another tenant; the cross-tenant suite is red on `main`; audit events with a tenant inconsistent with the actor.  
**Diagnosis and containment**, in this order:
1. Open the incident and record when it became known (T0): the GDPR runbook's clock starts there.
2. Contain: roll back to the last healthy version, or switch off the flag of the feature involved. If the scope is unclear, stop the API: `aws apigatewayv2 update-stage --api-id <id> --stage-name '$default' --default-route-settings ThrottlingBurstLimit=0,ThrottlingRateLimit=0`.
3. Preserve evidence as in gdpr.md §8, before any fix. Delete or restore nothing.
4. Check the database defences. In the first query no role may have `BYPASSRLS` (`secondchance_maintenance` works through the policies of migration 0005, with only `SELECT` and `DELETE` on the job tables); the second must list only tables without `tenant_id` (e.g. `alembic_version`, `experiment`).
   ```sql
   SELECT rolname, rolbypassrls FROM pg_roles WHERE rolname LIKE 'secondchance%';
   SELECT relname FROM pg_class
   WHERE relnamespace = 'public'::regnamespace AND relkind = 'r' AND NOT relrowsecurity;
   ```
5. Find the path: access outside `tenant_session`, a worker taking the tenant from the message instead of the run, an S3 key computed from an argument, a tool accepting `tenant_id` (ADR-010, ADR-011).
6. Scope: which tenants, which data, which interval, rebuilt from `audit_event` and logs through `correlation_id`.

**Mitigation.** A fix with a cross-tenant test that reproduces the case, release, verification. The operator informs the controller tenants without undue delay; notifying the authority is up to them (ADR-014).  
**Follow-up.** Mandatory postmortem; the test stays in the cross-tenant suite.

### RB-10 Restore from backup
**When.** Data corrupted by a migration or a bug, accidental deletion, drill ([section 8](#8-backups-and-restore-drills)).  
**Diagnosis.** Fix the instant T, before the damage, from audit and logs. Decide whether the damage is limited (some tables, one tenant) or total.  
**Aurora restore.** Always to a new cluster, never over the one in use. PITR creates the cluster without instances: the instance must be added.
```bash
aws rds restore-db-cluster-to-point-in-time \
  --source-db-cluster-identifier secondchance-pilot \
  --db-cluster-identifier secondchance-restore \
  --restore-to-time <T in ISO 8601 UTC> \
  --db-subnet-group-name <subnet-group> --vpc-security-group-ids <sg> \
  --serverless-v2-scaling-configuration MinCapacity=0.5,MaxCapacity=4
aws rds create-db-instance --db-instance-identifier secondchance-restore-1 \
  --db-cluster-identifier secondchance-restore \
  --db-instance-class db.serverless --engine aurora-postgresql
```
**Verification.** `alembic current` with the migrator role, counts per tenant and table, the queries of [RB-09](#rb-09-suspected-cross-tenant-leak). Never run `pytest` against the restored cluster: the suite downgrades and upgrades the database it gets.  
**Mitigation.**
- Limited damage (preferred): extract only the affected rows from the restored cluster (`pg_dump --data-only --table ...` or `COPY` filtered by tenant) and insert them back with the migrator role, with an audit event explaining the operation.
- Total damage: point the functions to the new endpoint (Terraform variable), accepting the loss of data written after T.
- S3: versioning gives back the previous version (`aws s3api list-object-versions`, then `copy-object` with `VersionId`).
- Locally: `docker compose exec -T db pg_dump -U postgres -Fc secondchance > secondchance.dump`, then `docker compose exec -T db pg_restore -U postgres -d secondchance --clean --if-exists < secondchance.dump`.

**Follow-up.** Apply again the data-subject erasures made after T (gdpr.md §5-6). Delete the restore cluster. Record the actual RPO and RTO in the [drill log](#drill-log).

### RB-11 GuardDuty finding or infected upload
**Symptoms.** An email from the alarm topic with a GuardDuty finding; an ingestion job in `failed` with `malware_scan:threats_found`.  
**Diagnosis.**
1. GuardDuty console, finding details: type, resource, actor, first and last seen. `Object:S3/MaliciousFile` names the bucket and key, and the key gives the tenant (`tenants/{id}/`).
2. For an upload: the `document_version` with that `object_key` gives the document, and the upload's `audit_event` (by `correlation_id`) the user.
3. For anything else (credentials used from an unusual place, a Lambda calling a known bad host): CloudTrail, by access key or role session, over the finding's interval.

**Mitigation.**
- Infected upload: the object is already unreadable (bucket policy) and was never parsed. Delete it with its versions, tell the network's admin, and suspend the uploader unless it was an accident.
- Credentials: revoke the role's sessions (an inline deny on `aws:TokenIssueTime` before now), rotate secrets; if personal data may have been read, follow [RB-09](#rb-09-suspected-cross-tenant-leak) and the breach runbook.

**Follow-up.** Suppression rules only for findings understood and documented here.

## 7. Incident management

| Severity | Examples | Response | Postmortem |
|---|---|---|---|
| SEV1 | suspected cross-tenant leak, data loss, pilot unusable for more than 30 min | as soon as seen, within 1 working hour | mandatory |
| SEV2 | fast SLO burn, `notify` DLQ, notifications blocked, main feature degraded | within the working day | mandatory |
| SEV3 | slow burn, `jobs` or `agents` DLQ, AI spikes, cost anomalies | within 3 working days | a note in the issue |

Times apply in working hours and are declared to the pilot partners in the agreement. Every incident has an issue in the installation's private tracker, not in the public repository; security incidents get a private draft GitHub Security Advisory.

**Timeline.** Times in UTC, written while working: detection, response, mitigation, resolution, and every command that changes state (rollback, flag, redrive, restore).

**Communication.**
- One contact person per tenant, set at onboarding. Write to them, not to the users, in the language agreed with the partner.
- SEV1 and SEV2: a first message within 1 h of the response, with what is not working, what to do meanwhile (e.g. coordinate pickups by phone) and when the next update comes.
- Updates every 2 h for SEV1, at mitigation for SEV2; a closing message with a summary.
- No personal data in the messages.

**Blameless postmortem**, within 5 working days. Look for the conditions that allowed the error, not for someone to blame.

```markdown
# Postmortem — <title> (<SEV>, <date>)
## Summary
What happened, impact and duration in three lines.
## Impact
Tenants and features involved, failed requests, error budget used, data involved (yes/no, which categories).
## Timeline (UTC)
hh:mm detection (alarm or report) · hh:mm response · hh:mm mitigation · hh:mm resolution
## Causes
The technical causal chain. Why tests, alarms and reviews did not stop it.
## What worked, what did not
## Actions
| Action | Type (prevent / detect / mitigate) | Issue | Due |
|---|---|---|---|
```

## 8. Backups and restore drills

NFR-025 applies to environments with real data, i.e. the pilot. The demo uses synthetic data and is rebuilt from the seed: no backups.

| What | How | Proposed retention |
|---|---|---|
| Aurora | continuous automatic backups with PITR, KMS-encrypted | 14 days |
| Aurora before a migration | manual snapshot | 30 days, then deleted by hand |
| S3 (documents, artefacts, attachments) | versioning and lifecycle on non-current versions | 30 days |
| Terraform state | S3 backend with versioning | as S3 |
| SQS queues, logs | no backup: messages carry only IDs and state lives in the database; logs expire at 30 days by design | — |
| Cognito | no native backup | see below |

- The KMS key is not scheduled for deletion while a snapshot using it exists.
- Data erased on request stays in backups until they expire: the 14 days proposed here are the value to carry into the "Aurora backups" row of gdpr.md §5, still to be set.
- If the Cognito pool is lost, users are invited again and get a new `sub`. Domain tables use the `sub` (ADR-014), so an old → new mapping built from the `membership` table is needed. To be tried in the first drill.

**Proposed pilot objectives**, to be confirmed with the partners:
- **RPO 15 min.** Aurora PITR normally reaches a few minutes back; 15 leave a margin.
- **RTO 4 working hours.** One maintainer, no night on-call.

**Drill**: before the pilot starts, then every quarter and after every major schema or infrastructure change.
1. Choose T = one hour ago and record the start time.
2. Restore to a new cluster as in [RB-10](#rb-10-restore-from-backup).
3. Verify: `alembic current`; counts per tenant compared with production (expected difference: only the writes after T); the RLS checks of RB-09; a read with the `secondchance_app` role and an `app.tenant_id` set.
4. Recover an S3 object from a previous version.
5. Record when the cluster is usable: that is the measured RTO.
6. Delete the cluster and record the outcome in the [log](#drill-log). Locally the same path is tried with `pg_dump` and `pg_restore`.

## 9. Release and rollback

**Today.** [`scripts/deploy.sh`](../../scripts/deploy.sh) updates the functions to the commit's image (immutable tag in ECR, NFR-015). Rollback: run the script again from the previous commit; the image already exists, so there is no build. For an old commit, mind the migrations: the expand/contract rule below applies.

**Pilot.** Every deployment publishes a Lambda version; API Gateway and the event source mappings point to the `live` alias, never to `$LATEST`.
- Code canary: `aws lambda update-alias --function-name secondchance-pilot-api --name live --function-version <current> --routing-config 'AdditionalVersionWeights={"<new>"=0.1}'`, 30 minutes with the service dashboard open, then `--function-version <new>` at 100%.
- Rollback: `aws lambda update-alias --function-name secondchance-pilot-api --name live --function-version <previous> --routing-config 'AdditionalVersionWeights={}'`. The effect is immediate.

**Migrations.**
- Forward-only in production: no downgrades on real data.
- CI still tries upgrade → downgrade → upgrade on every push (the suite does it), so an emergency downgrade is at least tested.
- Expand/contract: the schema must support both the new and the previous code version. First add, then the code uses it, and only in a later release remove. So a rollback breaks nothing.
- Order in the pilot: snapshot → migration with the migrator role (the one-shot `migrate` function) → canary.

**Flags and experiments (ADR-013).** State is in the database and read on every request, so the kill switch is one row:
```sql
UPDATE experiment SET status = 'stopped' WHERE key = '<key>';
```
From the next request everyone gets the control. Switching off the RAG, agent or Rizzo Flow shadow flag is the first mitigation for an AI problem.

**Prompts and models.** A new template or model never goes to production all at once:
1. evaluation harness on the golden set in CI, per language, with the thresholds of NFR-019, NFR-020 and the per-agent ones (ADR-010);
2. an experiment on the `prompt` or `retrieval` surface for 10% of the subjects of opted-in tenants. Guardrail metrics fixed beforehand: errors, latency, correct abstentions, guardrail interventions, `budget_exhausted`;
3. promotion to default only if the primary metric and the guardrails hold, otherwise kill switch.

The `prompt_sha256` and `model_id` of every step (ADR-008) attribute a regression to the right version.

## 10. Costs

Check prices in the AWS Pricing Calculator before every deployment.

| Driver | What makes it grow | Levers |
|---|---|---|
| Aurora ACUs | minimum capacity > 0 in the pilot (the main fixed cost), heavy queries, connections that prevent pausing in the demo | minimum 0 ACU in the demo, low maximum ACUs, indexes, no persistent connections |
| Bedrock tokens | agents (several calls per run), long RAG contexts, re-ingestion with embeddings | Haiku, per-run limits (ADR-010), abstention before the model (FL-02), small top-k and `maxTokens`, incremental ingestion |
| Interface endpoints | hourly cost per endpoint and per AZ (`bedrock-runtime`, `sqs`, `secretsmanager`, `lambda`, maybe `xray` and `logs`), always on in the pilot | only the necessary endpoints; demo destroyed after use |
| Logs and traces | GB ingested into CloudWatch, spans indexed by Transaction Search, Application Signals | `INFO`, 30-day retention, trace sampling, a low indexing percentage |
| Detection | GuardDuty (events analysed), Malware Protection for S3 (GB scanned), CloudTrail S3 data events and trail storage (ADR-022) | small at NGO volumes; GuardDuty's usage page shows the cost per source |
| The rest | Lambda, SQS, S3, API Gateway, SES, KMS, WAF | negligible at this volume; still checked in the monthly report |

In the pilot costs are reviewed once a month, together with the cost per workflow (PRD §11).

**Ephemeral demo (NFR-023).**

Before:
- [ ] AWS Budgets and Cost Anomaly Detection active on the account.
- [ ] `terraform plan` read: no NAT Gateway, Aurora at minimum 0 ACU, no provisioned concurrency.
- [ ] `scripts/deploy.sh demo`: apply, migrations and synthetic seed.
- [ ] A database read a few minutes before the session ([RB-04](#rb-04-aurora-connections-exhausted-or-resuming-from-pause)).

After:
- [ ] `scripts/destroy.sh demo` the same day. The ENIs of Lambda functions in a VPC are released slowly: if subnets or security groups stay locked, wait and run it again.
- [ ] `aws resourcegroupstaggingapi get-resources --tag-filters Key=project,Values=secondchance` returns nothing.
- [ ] Checked by hand: log groups created automatically by Lambda (they must be declared in Terraform), final Aurora snapshots, ECR images, versioned buckets to empty, the model invocation logging bucket if enabled.
- [ ] The next day, in Cost Explorer, daily spend is back close to zero.

## Drill log

| Date | Environment | Restore point T | Measured RTO | Outcome and problems |
|---|---|---|---|---|
| — | — | — | — | no drill run yet |
