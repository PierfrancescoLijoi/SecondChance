# SecondChance — Data protection (GDPR)

**Version:** 0.2
**Status:** technical draft, **to be validated with the DPO and a lawyer before the pilot**
**Related documents:** [PRD](../PRD.md) (§2.3, §3, NFR-004/005/026, §8) · [ADR](../ADR.md) (ADR-002, 003, 008, 009, 010, 011, 013, 014)

SecondChance provides technical and organisational controls that help a controller comply with the GDPR. The software alone makes no processing compliant: compliance depends on contracts, instance configuration, privacy notices, the legal bases the controller chooses and the DPO's assessments. Parts marked **[legal]** need legal validation; parts marked **[to implement]** do not exist in the code yet.

---

## 1. Roles

| Scenario | Controller | Processor (art. 28) | Sub-processors |
|---|---|---|---|
| Hosted multi-tenant instance | every NGO (tenant), for its own data | whoever runs the instance on the NGOs' behalf | AWS (and the services listed in §9) |
| Self-hosted on the NGO's AWS account | the NGO | AWS, under the NGO's own contract | — |
| Self-hosted on premises (Docker Compose) | the NGO | the hosting provider, if any | — |
| Open-source project | no role: publishing the code processes no data, until one runs an instance | — | — |

- The `platform_admin` of a hosted instance acts for the processor, not for the tenants.
- Sharing offers between organisations (FR-005) may create independent controllers or joint controllers (art. 26). **[legal]**, to be decided before enabling FR-005.
- A person active in two NGOs has one `sub` in the IdP but two controllers: every data-subject request is handled tenant by tenant.

**What the DPA (art. 28(3)) between each NGO and the instance operator must cover:**

1. Subject matter, duration, nature and purpose; categories of data and data subjects (from the record in §2).
2. Processing only on the controller's documented instructions, AI use included: no tenant data used to train models.
3. Confidentiality of staff with access, the `platform_admin` included.
4. The art. 32 measures as an annex (§7), with a commitment to notify substantial changes.
5. Sub-processors: general authorisation, list (§9), advance notice of changes and right to object.
6. Assistance with data-subject rights (§6), with an internal deadline (proposal: 7 working days).
7. Assistance with security, breaches, DPIA and prior consultation (arts. 32-36); notification of a breach to the controller within a fixed time (proposal: 24 hours from discovery).
8. End of service: tenant export and deletion, including backup expiry. **[to implement]** tenant exit procedure.
9. Audits and information to demonstrate compliance.
10. A/B experiments only with the tenant's opt-in (ADR-013).

---

## 2. Record of processing activities (art. 30) — draft

The record belongs to the controller (art. 30(1)): every NGO adapts it. The operator of a hosted instance keeps its own record as processor (art. 30(2)). Legal bases **[legal]**.

| Processing | Purpose | Legal basis (art. 6) | Data subjects | Data categories | Recipients | Transfers | Retention | Measures |
|---|---|---|---|---|---|---|---|---|
| Accounts and access | authenticate, assign role and tenant, manage members | (b) if there is a volunteering or employment agreement; otherwise (f) | operators, volunteers, donor contacts, organisation admins | name, email, phone (IdP), `sub`, role, tenant, sign-in events | organisation admins; instance operator; Cognito | none outside the EEA | duration of the relationship, then deletion (period to be set) | OIDC, RLS, least privilege, MFA for admin roles **[to configure]** |
| Offers and logistics (FL-01) | record surplus, match it with centres, plan missions | (f) coordination of redistribution; (c) if a food traceability rule applies to the organisation | donor contacts, coordinators, volunteers | `sub` of whoever creates, approves and executes (in the audit); offer data (not personal) | authorised tenant staff; organisations with an agreement (FR-005) | none | to be set with the controller | RLS, atomic reservation, audit in the same transaction |
| Volunteer notifications | communicate assigned and cancelled missions; in-app notices for operators and centre staff | (b) or (f) | volunteers, coordinators, centre staff | in-app: recipient `sub`, kind, object id; email: the verified address read from Cognito at send time (never stored by SecondChance), a fixed template with no offer, name or beneficiary data (FR-026) | Amazon SES; the volunteer's mail provider | delivery goes through the provider the volunteer chose | in-app 90 days, outbox 30 days, queue messages a few days with identifiers only | RLS per recipient, outbox, notifier without data access, DLQ, plain-text templates |
| Missions and receipts | carry out pickups and deliveries, confirm receipt | (f) coordination of redistribution | volunteers, centre staff, coordinators | volunteer `sub` and the display name they chose, `sub` of who approved and acted (in `mission_event` and the audit), quantities, times | the network's coordinators; the volunteer; the destination centre's staff | none | finished missions and their history 730 days | RLS per role, database guards, idempotency, audit |
| Audit and accountability | prove who did what (FR-004, art. 5(2)) | (c) where a rule requires it; otherwise (f) | all users | `sub`, role, action, object, outcome, correlation ID, timestamp | organisation admins; authorities on request | none | 5 years **[legal]** | append-only, RLS, no contact data |
| AI assistant and agent memory | help coordinators: procedures, proposals, explanations (ADR-010) | (f), with a legitimate-interest assessment | operators; third parties possibly named in free text | request text after redaction, `requested_by`, `conversation` memory per `sub`, step metadata | Bedrock; locally Ollama and Rizzo Flow | inference only in EU regions (`eu.` profile) | memory 7/30/365 days; steps 365 days | PII redaction, Guardrails PII mask, no prompts in logs, `pending` proposals only |
| Knowledge base | make authorised procedures and guidelines searchable (ADR-015) | (f); (c) if a rule requires the procedure to be shared | people possibly named in the documents; uploaders | document text and embeddings, `created_by` (`sub`) | roles allowed by the space; every network for public spaces | none; embeddings and models in the EU | while the document is active; deletion removes it from search at once | RLS per space and role, authorised documents only (PRD §8.1) |
| A/B experiments | improve operator-facing features (ADR-013) | (f), with a legitimate-interest assessment | operators and volunteers of opted-in tenants | sha256 pseudonym, variant, correlation ID | instance operator (aggregate analysis), organisation admins | none | 180 days | tenant opt-in, kill switch, surfaces constrained by `CHECK`, individual opt-out **[to implement]** |
| Observability and logs | operation, diagnosis, SLOs (ADR-012) | (f) | all users | trace and correlation IDs, route, outcome, latency, allowed attributes; IP if access logs are on | instance operator; CloudWatch, X-Ray | none | 30 days; sampled traces | attribute allowlist, PII redaction, never `Authorization` |
| Security | prevent and handle incidents and unauthorised access (art. 32) | (c) art. 32, with (f) | users, administrators | `denied` outcomes in the audit, authentication events, AWS administrative activity | instance operator; authorities in case of a breach | none | logs 30 days; audit 5 years; CloudTrail trail 365 days (ADR-022) | alarms, breach runbook (§8) |

---

## 3. Data inventory

Every database column carries a `COMMENT 'pii:none|personal|sensitive; <purpose>'`. `python -m secondchance.privacy` prints the inventory from the PostgreSQL catalogue, and a CI test fails if a migration adds an unclassified column. **The catalogue is the source**: the table below is a summary for the record and must be realigned with the command's output after every migration.

| Table | Personal data | Class | Purpose | Retention |
|---|---|---|---|---|
| `tenant` | none (`name` is the organisation's name) | none | organisation registry, country for food rules | duration of the contract |
| `organization` | none; `name` can be a person's name if the donor is a sole trader | none | organisations and donors | duration of the relationship |
| `center`, `center_slot` | none (organisation sites, opening times) | none | receiving centres, capacity, storage, acceptance slots | duration of the relationship |
| `food_rule` | none | none | versioned food rules per country (FR-017) | while in force, then kept as history |
| `matching_run` | `requested_by` (`sub`) | personal | solver runs, input checksum, statistics and reasons per unassigned offer | 365 days (`secondchance.retention`) |
| `allocation_proposal` | `decided_by` (`sub`) | personal | solver proposals bound to a content hash, human decision (FR-022) | 365 days, while no mission references them |
| `mission` | `volunteer_subject`, `created_by` (`sub`) | personal | mission life cycle and receipts (FR-023) | 730 days after the mission is finished |
| `mission_event` | `actor` (`sub`) | personal | mission history and idempotency keys | with its mission |
| `notification` | `recipient` (`sub`) | personal | in-app notifications, readable only by the recipient (RLS) | 90 days |
| `notification_delivery` | none directly; linked to the recipient through `notification` | none | email outbox (status, attempts, language) | 30 days |
| `donation_offer` | none: the donor is an organisation, whoever acts is in the audit | none | FL-01 | to be set with the controller |
| `audit_event` | `actor` (`sub`), `actor_role`; `details` must contain only IDs and enums | personal | accountability (FR-004) | 5 years **[legal]** |
| `agent_run` | `requested_by` (`sub`) | personal | agent execution | 365 days, like the steps (assumption) |
| `agent_step` | no direct column; linkable to a person through `agent_run` | none | AI traceability: agent, model, template hash, tokens, latency, outcome (ADR-008) | 365 days |
| `agent_memory` | `subject` (`sub`, `conversation` scope), `content` after redaction, `embedding` of the content | personal | agent memory (ADR-011) | mandatory `expires_at`: 7 / 30 / 365 days |
| `experiment` | none | none | platform-level experiment definitions | duration of the experiment |
| `experiment_exposure` | `unit` = sha256 of tenant and `sub` | personal (pseudonym) | A/B analysis | 180 days |
| `routing_decision` | none; no request text | none | router comparison (ADR-007) | 365 days (`secondchance.retention`) |
| `membership` | the member's `subject` (`sub`), `display_name` chosen by volunteers, centre staff and coordinators, `decided_by` (`sub`) of whoever decided | personal | registration, role, status and centre of the membership (ADR-017) | duration of the membership **[to set]** |
| `knowledge_space` | none | none | knowledge spaces and allowed roles | while the space exists |
| `document`, `document_version` | `created_by` (`sub`) of the uploader | personal | provenance and versions of documents | while the document is active |
| `knowledge_chunk` | `content` and `embedding`: the text may name people | personal | search and citations | like the document version |
| IdP (outside the database) | email, name, phone, `sub`, authentication factors | personal | authentication | duration of the account |

Notes:
- No column should be `sensitive`. If one appears, the DPO reviews it before the merge.
- An embedding of personal text is personal data: it is deleted with the row that holds it.
- S3 objects (attachments, proofs of delivery, FR-015) must not contain photos or documents of people, beneficiaries above all.
- SQS messages carry IDs only (ADR-011); `notify` messages also carry the recipient's `sub`, a notification kind and a language, never an address or content.
- The interface language choice is stored only in the user's browser (`localStorage`), never on the server.

---

## 4. Minimisation and pseudonymisation

- **Only the `sub`.** Domain tables keep the IdP `sub`, never names or contacts. Those live in the IdP (Cognito on AWS, the mock locally).
- **No beneficiaries.** They have no accounts and no columns. Notifications contain no beneficiary data (FR-026), experiments never use them as units (ADR-013), agents do not assess people (ADR-009).
- **PII redaction before logs, memory and prompts** (ADR-014):
  - in code, baseline redaction of emails, phone numbers and IBANs;
  - on AWS, Bedrock Guardrails with the *sensitive information* filter in *mask* mode in front of the model;
  - in logs, the formatter keeps only allowed attributes and redacts text (ADR-012).
  - Limit: regular expressions do not recognise names, addresses or health information written in free text, and the Guardrails filter is probabilistic. Redaction reduces the risk, it does not remove it.
- **No plain-text prompts.** Bedrock model invocation logging stays off; `agent_step` records metadata and the template hash only (ADR-008).
- **Exposure pseudonym.** `sha256(tenant + sub)` is pseudonymisation, not anonymisation: whoever knows the `sub` can recompute the hash. It remains personal data. An HMAC with a secret key per tenant is worth evaluating.
- **Only synthetic data outside the pilot.** Seed, tests, CI and the AWS demo use synthetic data (PRD §8.1). Locally there are no Guardrails: no real data enters a development environment, and no copy of the pilot database goes to development.

---

## 5. Retention

| Data | Duration | From | How it is applied | Status |
|---|---|---|---|---|
| `agent_memory`, `run` scope | 7 days | write | mandatory `expires_at`, retention job | active |
| `agent_memory`, `conversation` scope | 30 days | write | as above | active |
| `agent_memory`, `tenant` scope | 365 days | operator confirmation | as above | active |
| `experiment_exposure` | 180 days | exposure | retention job | active |
| `agent_step` (and `agent_run`) | 365 days | creation | retention job; a run is deleted only once it has no steps or memories | active; `agent_run` by assumption |
| `routing_decision` | 365 days | creation | retention job (`secondchance.retention`) | active |
| Application logs | 30 days | write | CloudWatch log group retention (Terraform); Loki retention locally | in Terraform |
| `audit_event` | 5 years | event | retention job with a dedicated role | **[legal]** |
| `membership`, IdP account | duration of the relationship | leaving the organisation | deletion on leaving | **[to set]** |
| Aurora backups | to set (1-35 days automatic) | snapshot | automatic backup retention | **[to set]** before the pilot |
| SQS queues and DLQs | 4 days (queues), 14 days (DLQs) | send | `MessageRetentionPeriod` | in Terraform |

**Retention job** ([`api/secondchance/retention.py`](../../api/secondchance/retention.py)): every night at 03:15 UTC (EventBridge Scheduler on AWS; locally `python -m secondchance.retention`).
1. It runs as `secondchance_maintenance`, which has no `BYPASSRLS`: it sees every tenant's rows only through the dedicated policies of migration 0005, and has only `SELECT` and `DELETE` on the tables it cleans.
2. It deletes rows with `expires_at <= now()` in `agent_memory` and rows past their duration in the other tables, respecting foreign keys.
3. It logs only the counts per table. A `retention.purge` audit event is **[to implement]**.
4. Tests: `test_retention.py::test_purge_deletes_expired_rows_and_keeps_fresh_ones` and `test_maintenance_role_can_only_read_and_delete_what_retention_needs`.

Deleted data remains in backups until they expire. After a restore, the deletions made in the meantime are applied again (§6).

---

## 6. Data-subject rights (arts. 15-22)

**Common rules.**
- Answer within **one month** of the request, extendable by two months for complex requests, informing the data subject within the first month (art. 12(3)).
- The request goes to the controller (the NGO). In a hosted instance the operator assists within the DPA deadline.
- Identity verified before acting (art. 12(6)): request from an authenticated session, or confirmed by the organisation admin.
- Every operation runs in the controller tenant's context (`SET LOCAL app.tenant_id`), never with a role that bypasses RLS.
- Every request leaves an audit event (`dsr.access`, `dsr.erasure`, …) with the request ID and no contact data of the requester in `details`.
- Dedicated endpoints are planned for P1 (ADR-014). **[to implement]** Until then the runbook runs with reviewed scripts.

**Access and portability (arts. 15, 20)**
1. Get the `sub` from the IdP (on Cognito: `AdminGetUser`, profile attributes).
2. Collect in the tenant: `membership` rows; `audit_event` with `actor = sub`; `agent_run` with `requested_by = sub` and its `agent_step` rows; `agent_memory` with `subject = sub`; `experiment_exposure` with `unit` = the recomputed hash.
3. Logs: included if the formatter allowlist records the `sub` (CloudWatch Logs Insights search over the last 30 days).
4. Deliver a JSON file with purpose, recipients and retention for each category (art. 15(1)), over a secure channel.
5. Portability covers only data provided by the data subject and processed on basis (b) or consent. The JSON of step 4 covers it anyway.

**Rectification (art. 16)**
- Name, email and phone: corrected in the IdP; SecondChance does not store them.
- Domain data: the organisation corrects it with the normal operations.
- The audit is never rewritten: an event documenting the correction is added.

**Erasure (art. 17)**. Order matters: the `sub` is needed until the last step.
1. Check the art. 17(3) exceptions (legal obligation, legal claims) and record them.
2. Delete `agent_memory` with `conversation` scope and `subject = sub`.
3. Delete `experiment_exposure` with `unit` = hash of tenant and `sub`, computed exactly as when writing.
4. Delete the `membership` rows.
5. Remove the address from the SES suppression list, if present.
6. Delete the user from the IdP (on Cognito: `AdminDeleteUser`). If the person belongs to other tenants, each controller decides.
7. Record the `dsr.erasure` event and answer the data subject.

What remains, and why:
- **`audit_event.actor` and `agent_run.requested_by`** keep the `sub`. Without the IdP and `membership`, the system can no longer link it to a person. Basis: legal obligation or legitimate interest in accountability (ADR-014). **[legal]**
  - The link remains possible while backups or logs with the `membership` rows exist, and through the NGO's external records (e.g. volunteer lists). Whether the residual data is anonymous under recital 26 must be assessed.
  - For `agent_run` the DPO may prefer replacing the `sub` with a fixed value.
- **Logs**: CloudWatch does not delete single records, so they expire within 30 days. The data subject is told.
- **Backups**: they expire according to their retention. The hashes of deleted `sub`s are kept in a list, to be applied again after every restore. **[to implement]**

**Restriction (art. 18)**: disable the user in the IdP (on Cognito: `AdminDisableUser`) and set their `membership` rows to `suspended`. From then on: no new memory, no exposures, no notifications, because every request without an `active` membership gets 403.

**Objection (art. 21)**. It concerns processing based on legitimate interest.
- Experiments: the data subject leaves the experiments, always gets the control and generates no exposures. ADR-013 today has only the tenant opt-in. **[to implement]** a per-subject opt-out read by the assignment function (e.g. a column on `membership`).
- `conversation` memory: stop writing it for that subject.
- Audit: objection is assessed case by case, against the controller's compelling legitimate grounds.

**Automated decisions (art. 22)**: SecondChance makes none. Every allocation needs a human approval (FR-022) and no agent assesses people (ADR-009, ADR-010).

---

## 7. Security of processing (art. 32)

| Control | Reference | Evidence | Status |
|---|---|---|---|
| Tenant isolation with RLS, even on unfiltered queries | ADR-003 | `api/tests/test_tenant_isolation.py`: `test_every_table_with_tenant_id_has_rls`, `test_query_without_where_returns_only_own_tenant`, `test_insert_for_other_tenant_is_rejected`, `test_reference_to_other_tenant_organization_is_rejected`; `test_api.py::test_other_tenant_cannot_reserve` | in CI |
| Tenant context that does not survive on the pool | ADR-003 | `test_tenant_setting_does_not_survive_on_pooled_connection` | in CI |
| Application role without ownership or `BYPASSRLS`; migrations with a separate role; no temporary tables | ADR-003, `db/bootstrap.sql` | `test_app_role_is_not_owner_and_cannot_bypass_rls` | in CI (`test_no_role_bypasses_row_level_security`) |
| Suite extended to memory, exposures, `routing_decision` and S3 prefixes | ADR-011 | cross-tenant tests on the new tables | active (`test_memory.py`, `test_agents.py`, `test_queues_storage.py`, `test_tenant_isolation.py`) |
| OIDC authentication with issuer, audience and expiry checked | FR-001, NFR-002 | `test_api.py`: missing token, invalid token, unknown role | mock in CI; Cognito in Terraform (`identity.tf`, Trivy in CI) |
| Append-only audit | FR-004 | `api/tests/test_audit.py::test_audit_cannot_be_rewritten` | in CI |
| Reservation integrity | FR-016 | `api/tests/test_reservation.py` | in CI |
| Encryption in transit (TLS 1.2+) and at rest (KMS: Aurora, S3; SQS-managed encryption for queues) | NFR-001 | configuration audit of the Terraform | in Terraform (Trivy in CI); Aurora `sslmode=require`, `verify-full` before the pilot |
| Least-privilege IAM per function; endpoint policies limited to the project's models and queues | NFR-002, ADR-006 | IaC scanning | in Terraform (`compute.tf`, Trivy in CI); the notifier may send only from the configured SES sender |
| Agents: identity from the context, read-only tools, writes only as `pending` proposals | ADR-010 | FR-034 tests | identity from the context active (`test_agents.py::test_message_with_another_tenant_cannot_reach_the_run`); no writing tool exists for agents |
| Operational writes only after human approval of a hashed proposal | FR-022, ADR-021 | `test_operations.py` | in CI: content hash, one-way decisions, solver-only proposals, mission guards |
| Notifications readable only by their recipient; emails without personal or beneficiary content | FR-026, ADR-021 | `test_operations.py::test_notifications_are_marked_read_by_their_recipient_only`, `test_notify.py` | in CI |
| No prompts or `Authorization` in logs; PII redaction | ADR-008, ADR-012 | formatter tests | active (`test_observability.py`, `test_memory.py::test_content_is_redacted_before_it_is_stored`) |
| Encrypted backups and a tested restore | NFR-025 | restore drill, RPO/RTO | before the pilot |
| Monitoring and alarms (errors, DLQ, burn rate) | ADR-012 | dashboards and SNS alarms | alarms on 5xx, function errors, DLQs (`notify` included), queue age and budget in Terraform (`observability.tf`) |
| Supply chain: secret scanning, SBOM, image and IaC scanning | NFR-014, NFR-024 | CI pipeline | lint, tests, Trivy on Terraform, shellcheck and Dependabot in CI; secret scanning to enable on the repository; SBOM and image scanning still to do |

---

## 8. Personal data breaches (arts. 33-34)

**Roles.** The *technical incident lead* is the instance operator; in self-hosting, the NGO. The *controller* is the NGO, with its DPO or privacy contact. The processor informs the controller without undue delay (art. 33(2)), within the DPA deadline. Notifying the authority and informing data subjects remain the controller's decisions.

| When (T0 = awareness of the breach) | Who | What |
|---|---|---|
| T0 | whoever detects it | opens the incident, records time and source; deletes or restores nothing |
| T0 + 1 h | technical lead | contains: revokes credentials and tokens, disables users or functions, experiment kill switch, isolates resources |
| T0 + 4 h | technical lead | preserves evidence (see below) and estimates scope, tenants and data subjects involved |
| within the DPA deadline | processor | informs every controller involved with the information gathered so far |
| T0 + 48 h | controller with the DPO | assesses the risk to data subjects and decides whether to notify |
| T0 + 72 h | controller | notifies the competent supervisory authority if the breach presents a risk; missing information follows in phases (art. 33(4)) |
| without undue delay | controller | informs data subjects if the risk is high (art. 34) |
| within 30 days | both | post-incident review, corrective actions, runbook and DPIA updates |

Every breach, notified or not, goes into the controller's breach register (art. 33(5)).

**Preserving evidence**
- Export the affected log groups at once: the 30-day retention would delete them.
- Take a manual Aurora snapshot; manual snapshots do not expire on their own.
- Export the relevant files from the CloudTrail bucket (365 days) and verify them with `aws cloudtrail validate-logs`; collect the GuardDuty findings of the period.
- Extract `audit_event` rows by tenant, interval and correlation ID; S3 object versions; DLQ messages.
- Suspend the retention job on the affected tables and record the suspension.
- Compute the sha256 of every exported file and keep a chain-of-custody log: who, when, where.

**Information to collect** (art. 33(3))
- Date and time of start, discovery and containment; how it was discovered.
- Nature of the breach: confidentiality, integrity or availability.
- Tenants involved; categories and approximate number of data subjects and records.
- Data categories: IdP identifiers, contacts, `sub`, memory content, logs.
- Likely consequences for data subjects.
- Measures taken or proposed, including to mitigate the effects.
- Contact of the controller's DPO or privacy contact.
- Notifications made: authority, data subjects, other controllers; date and reference.

---

## 9. Sub-processors and transfers

Home region `eu-central-1` (Frankfurt). Bedrock inference goes through the `eu.` profile, which routes requests only between EU regions (ADR-002). Rizzo Flow and Ollama run locally. **No transfer outside the EEA is planned.**

| AWS service | Use | Personal data |
|---|---|---|
| Cognito | identity and sign-in | name, email, phone, `sub`, authentication events |
| API Gateway, Lambda | API, workers, agents, notifications | in transit; IP in access logs, if on |
| Aurora PostgreSQL | domain data, audit, memory | see §3 |
| S3 | documents, artefacts, attachments | only if present in attachments |
| SQS | `jobs`, `notify`, `realtime-events` queues; local-only agent transport | identifiers and run status only, no prompt or document content |
| SES | mission emails to volunteers | recipient email address (from Cognito at send time); content is a fixed template without personal data |
| Bedrock (models, Guardrails, Titan Embeddings) | assistant, embeddings | text after redaction, in transit |
| CloudWatch, X-Ray | logs, metrics, traces | allowed attributes (§4) |
| SNS | alarms to technical staff | email of the on-call staff |
| CloudFront | static assets | visitors' IPs, global service |
| KMS, EventBridge Scheduler, ECR | keys, scheduling, images | none |

**To check before the pilot**
- The current version of the AWS GDPR DPA (in the Service Terms); the list of AWS sub-processors.
- Standard contractual clauses and the EU-US Data Privacy Framework for access by the US parent company, with a transfer risk assessment. **[legal]**
- Bedrock: that inputs and outputs are not used to train models nor shared with model providers, **to be checked in the current AWS documentation**. Also check the destination regions of the `eu.` profile and where Guardrails runs.
- Cognito: threat-protection features collect device data and IPs; if switched on, update the record.
- CloudFront: choose the price class and leave access logs off unless needed.
- An organisation policy that denies regions outside the EU, leaving the `eu.` profile's regions open.
- Never personal data in AWS support tickets.

---

## 10. DPIA (art. 35)

Screening against the nine criteria of the WP248 rev.01 guidelines, endorsed by the EDPB:

| Criterion | Result | Why |
|---|---|---|
| Evaluation or scoring | no | no profiles or scores of people (PRD §2.3, ADR-009) |
| Automated decisions with legal effects | no | mandatory human approval (FR-022) |
| Systematic monitoring | partly | audit and logs record the activity of operators and volunteers |
| Sensitive or highly personal data | residual risk | not planned, but free text can contain it (e.g. beneficiaries' health) |
| Large scale | probably not in the pilot | to reassess with the number of organisations and users |
| Combining datasets | no | — |
| Vulnerable data subjects | partly | volunteers in a power imbalance towards the organisation; vulnerable beneficiaries, even if only indirect |
| Innovative use of technology | yes | LLMs, agents, RAG, experiments |
| Preventing the exercise of a right or access to a service | no by design | the area (access to aid) is delicate, but no person is assessed |

Two or more criteria met make a high risk likely. The national lists of the pilot's authority must also be checked (Datatilsynet in Denmark, UODO in Poland, Garante in Italy).

**Conclusion: a DPIA is required before a pilot with real data.** The controller writes it, after consulting the DPO, with the processor's support.

**DPIA outline** (art. 35(7)):
1. Description: flows FL-01 and FL-02, agents, experiments, architecture (§9), inventory (§3).
2. Necessity and proportionality: legal bases, minimisation (§4), retention (§5), rights (§6), privacy notices.
3. Risks to data subjects: leakage between tenants; PII in free text towards model, memory and logs; beneficiary data entered by mistake; re-identification of pseudonyms; monitoring of volunteers; AI errors affecting the distribution of aid.
4. Measures: §4, §7, ADR-003, ADR-008, ADR-010, ADR-013; residual risk for each risk.
5. The DPO's opinion, the views of data subjects where appropriate (art. 35(9); e.g. volunteer representatives), prior consultation (art. 36) if the residual risk stays high.
6. Review at every scope change and after the pilot.

---

## 11. AI Act

- **Classification** (ADR-009): SecondChance neither assesses nor ranks people and allocates resources to centres with human approval. The goal is to stay outside high risk (Annex III). To be reassessed if a feature moves towards beneficiary eligibility or priority. **[legal]**, before the pilot.
- **Agents** (ADR-010): they only produce `pending` proposals; the `compliance` component is deterministic, without an LLM; Rizzo Flow only routes requests (ADR-007).
- **Transparency (art. 50)**:
  - users know they are interacting with an AI;
  - every output carries `generated_by` (agent, model, prompt version) and the interface shows it as generated content, in the user's language.
  - To check: provider or deployer role for each scenario in §1, and the dates of application in force.
- **No profiling of people**: routing classifies requests, not the people who write them; experiments do not segment by personal characteristics; `tenant` memory accepts only content confirmed by an operator.
- **AI literacy (art. 4)**: NGOs using the assistant train their operators on the system's limits.

---

## 12. Checklist before the pilot

- [ ] Scenario of §1 chosen; DPA signed between each NGO and the operator, with the §7 measures annexed.
- [ ] Decision on FR-005 (joint or independent controllers) **[legal]**.
- [ ] Record of processing filled in by every controller from §2; the processor's record.
- [ ] Legal bases validated, in particular the 5-year audit and the relationship with volunteers **[legal]**.
- [ ] Legitimate-interest assessment for the AI assistant, experiments and audit.
- [ ] Privacy notices (arts. 13-14) for operators, volunteers and donor contacts, covering the AI assistant and experiments, in the languages of the pilot.
- [ ] DPIA completed and signed; prior consultation if the residual risk stays high.
- [ ] DPO designated or privacy contact appointed for each controller (art. 37: check whether it is mandatory).
- [ ] Classification test green; output of `python -m secondchance.privacy` attached to the record.
- [ ] Missing durations set: `membership`, IdP account, backups, offers (`routing_decision`: 365 days, done).
- [ ] Retention job in production, with tests on expired rows and a dedicated role for the audit.
- [ ] Endpoints or scripts for access and erasure, tried on synthetic data within the deadline.
- [ ] Individual opt-out from experiments; `experiments_enabled` false until the legitimate-interest assessment is approved.
- [ ] Restriction through `membership.status = suspended`; list of erasures to apply again after a restore.
- [ ] Guardrails with PII mask configured and tried on synthetic cases; Bedrock invocation logging off.
- [x] Log formatter tests: PII redaction, no `Authorization`.
- [ ] Review of the code that writes `audit_event.details`: IDs and enums only.
- [ ] Operating rule: no photos or documents of people in attachments (FR-015).
- [x] Cross-tenant suite extended to memory, exposures, `routing_decision` and S3 prefixes.
- [ ] KMS encryption and TLS verified on the applied Terraform; CloudTrail logging, GuardDuty and the malware protection plan active.
- [ ] Restore drill done, RPO and RTO defined (NFR-025).
- [ ] Breach runbook rehearsed in an exercise; DPO and authority contacts at hand.
- [ ] AWS checks of §9 completed and archived.
- [ ] Policy denying regions outside the EU.
- [ ] AI Act classification (ADR-009) reviewed with the lawyer.
- [ ] Operator training on the AI assistant (AI Act art. 4).
- [ ] Tenant exit procedure: export and deletion.
- [ ] No real data in development, CI or demos.
