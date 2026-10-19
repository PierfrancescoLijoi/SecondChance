# Deploying to AWS

How to bring SecondChance to AWS repeatably and without secrets in the code ([ADR-018](ADR.md#adr-018--aws-deployment-terraform-no-access-keys-self-configuration)). On Windows the command that performs preflight, bootstrap, deployment and verification is:

```powershell
.\scripts\connect-aws.ps1 -Environment demo -AlarmEmail you@example.org
```

It signs in the `secondchance-admin` profile (`aws sso login` for an IAM Identity Center profile, `aws login` otherwise) and needs Terraform installed locally. Optionally pass `-GitHubRepository owner/repository` and `-BedrockModel <eu.* profile>`. On macOS/Linux, export `SECONDCHANCE_ALARM_EMAIL` and run `scripts/connect-aws.sh demo`.

## In short

| Who | How they authenticate | What they can do |
|---|---|---|
| You, from the CLI | IAM Identity Center (SSO) with MFA, or on a Free plan account an IAM user with MFA and `aws login`; both give credentials that expire | account bootstrap, deployment |
| GitHub Actions | OIDC: GitHub signs a token, AWS exchanges it for 1-hour credentials | deployment, only from this repository's `production` environment |
| The Lambda functions | one IAM role per function | only the queues, buckets, models and database user they use |
| The database | a 15-minute IAM token generated on every connection | no application passwords; RDS keeps the master password in Secrets Manager and only the `migrate` function reads it |

No IAM access key exists in this flow: there is nothing to rotate, lose or commit by mistake.

Before the first deployment with Claude, open the Bedrock model catalog once and complete the Anthropic first-time-use form. Claude is sold through AWS Marketplace, so the account also needs a payment method and Marketplace permissions; Amazon models (Nova, Titan) need neither. `connect-aws` now performs real, minimal Claude and Titan embedding invocations before creating infrastructure, so it fails early if either model is not usable.

## 1. Once per account: human identity

1. In the AWS console open **IAM Identity Center**, enable it in `eu-central-1` and create your user with mandatory MFA.
2. Create a `SecondChanceAdmin` permission set: `AdministratorAccess`, sessions of 1-4 hours. Assign it to your user on the account.
3. On your computer, with AWS CLI v2:

```bash
aws configure sso --profile secondchance-admin
```

Give it the Identity Center start URL, the `eu-central-1` region, the account and the permission set. From then on, to work:

```bash
aws sso login --profile secondchance-admin
```

```bash
export AWS_PROFILE=secondchance-admin
```

Credentials stay in the `~/.aws/sso` cache and expire on their own. The scripts use them directly; if Terraform is not installed it runs in a container with `~/.aws` mounted read-only.

### Free plan account, no payment method

A new account on the Free plan pays nothing for up to six months or until its credits run out. Two rules shape the setup:

- Joining AWS Organizations turns the account into a paid one, so do not enable IAM Identity Center or Control Tower. Create an IAM user with MFA and the `AdministratorAccess` and `SignInLocalDevelopmentAccess` policies, then sign the CLI in with that user's console session (AWS CLI 2.32 or later, no access keys):

  ```bash
  aws login --profile secondchance-admin
  ```

  Install Terraform locally (`winget install Hashicorp.Terraform`): the Terraform container cannot refresh this session.
- Claude needs a payment method (AWS Marketplace). Use an Amazon model instead:

  ```powershell
  .\scripts\connect-aws.ps1 -Environment demo -AlarmEmail you@example.org -BedrockModel eu.amazon.nova-lite-v1:0
  ```

AWS does not publish which services the Free plan withholds; if one is withheld, `terraform apply` stops at that resource with the reason.

## 2. Account bootstrap (automatic)

`connect-aws` detects the state bucket and creates it automatically when absent. It is versioned, encrypted with a dedicated KMS key and uses native S3 locking. When a GitHub repository is supplied it also creates the OIDC deployment role. The equivalent manual commands are:

```bash
terraform -chdir=infra/terraform/bootstrap init
```

```bash
terraform -chdir=infra/terraform/bootstrap apply -var github_repository=<owner>/<repo>
```

The `secondchance-github-deploy` role accepts only OIDC tokens from that repository, issued for the GitHub environment `production`. A permission boundary forbids it to create IAM users or access keys, touch the organisation or remove the boundary itself.

## 3. Once per repository: GitHub

1. Settings → Environments → `production`: add yourself as a **required reviewer**.
2. In the environment, create two *variables* (not secrets): `AWS_DEPLOY_ROLE_ARN` (bootstrap output) and `SECONDCHANCE_ALARM_EMAIL`.
3. Enable secret scanning and push protection for the repository.

The `Deploy` workflow runs only by hand (Actions → Deploy → Run workflow) and waits for approval.

## 4. Deploy

From your machine:

```bash
SECONDCHANCE_ALARM_EMAIL=you@example.org scripts/deploy.sh demo
```

The script, in order:

1. checks who you are (`sts get-caller-identity`) and stops without a valid session;
2. creates the ECR repository, builds the `api`, `worker` and independent `gateway` images and pushes them with an immutable tag equal to the commit;
3. runs `terraform apply`, which creates:
   - a private VPC without NAT, with endpoints;
   - Aurora Serverless v2 with IAM authentication;
   - RDS Proxy with TLS, end-to-end IAM authentication and a bounded connection pool;
   - SQS queues with DLQs and KMS-encrypted S3 buckets;
   - Cognito;
   - API Gateway with JWT authorizer and throttling;
   - Step Functions Standard for durable agent runs and an authenticated API Gateway WebSocket channel for progress events;
   - CloudFront with WAF and security headers;
   - the Lambda functions;
   - EventBridge Scheduler for retention and requeue;
   - Bedrock Guardrail, alarms and budget;
4. invokes `migrate`: creates the database roles (idempotent), applies the migrations and, in `demo` only, the synthetic relational seed;
5. in `demo`, invokes the separate seed function to upload the synthetic PDFs to S3 and index them with Titan through the production RAG path;
6. publishes the web app (the same build everywhere: Terraform writes `config.json`);
7. runs the smoke tests and prints the URL.

`connect-aws.sh` surrounds this deploy with account preflight and `verify-aws.sh`. The preflight resolves every destination of the Bedrock inference profile and rejects a destination outside the EU. Verification checks the public health endpoint, Lambda, SQS and Bedrock resources, then invokes the private `runtime-check` Lambda with the agent execution role. That acceptance probe makes real calls through the deployed VPC endpoints and IAM policies to Aurora, Titan Embeddings, Claude Converse, the Bedrock Guardrail (`ApplyGuardrail`, the same call that wraps every RAG answer) and the hybrid semantic router. Synchronous Lambda invocations in the scripts set `--cli-read-timeout` above the function timeout, so the AWS CLI never retries a migration, seed or probe that is still running. In `demo` verification also invokes the independent MCP Gateway with a real authorised `knowledge_search` and fails unless the request crosses DynamoDB rate limiting, the private executor, Aurora RLS and the indexed RAG corpus and returns evidence. The deployed application exposes the governed specialist contract at authenticated `GET /agents/catalog`.

Then sign up in the web app and become the first platform administrator:

```bash
scripts/grant-platform-admin.sh demo you@example.org
```

From then on NGOs register and you approve them in the app. Network administrators approve donors.

## 5. Tearing the demo down

```bash
scripts/destroy.sh demo
```

It asks you to type the environment name. In `demo` buckets empty themselves (`force_destroy`). At the end the script prints the command to look for leftovers tagged `project=secondchance`.

## Costs to watch

| Item | Ephemeral demo | Always on |
|---|---|---|
| Aurora Serverless v2 and RDS Proxy | RDS Proxy keeps a connection open to each instance, so Aurora never auto-pauses while the proxy exists; the proxy itself bills a minimum of 8 ACU-hours per hour | the second fixed cost after the interface endpoints: destroy the demo after use |
| Interface endpoints | limited for a few hours | hourly per endpoint/AZ: the main fixed cost; check current regional pricing |
| WAF | monthly fee per web ACL and rule | same |
| Bedrock | tokens used (Haiku) | same |
| GuardDuty, Malware Protection, CloudTrail | 30-day GuardDuty trial on a new account; scans per GB uploaded | small at NGO volumes; if the account already has a GuardDuty detector, set `guardduty_detector = false` |

The AWS budget emails at 80% of actual spend and 100% of forecast spend. **It does not stop spending** (PRD §6).

## Emulated AWS, no account

`scripts/emulate-aws.sh` (also a CI job) builds the three Lambda images with the same lines as `deploy.sh`, adds the AWS Lambda Runtime Interface Emulator and runs `api/tests_emulation` against [infra/emulation/compose.yaml](../infra/emulation/compose.yaml):

| What runs as on AWS | What it proves |
|---|---|
| Every function's image, entrypoint and handler, read-only filesystem except `/tmp` | packaging, imports, the runtime's own JSON encoder |
| Postgres requiring TLS, a master that is not a superuser, `rds_iam`, the master secret in a Secrets Manager stand-in | `migrate` bootstraps roles and runs Alembic twice in a row; IAM tokens are signed and sent over TLS |
| MCP gateway → executor and agents → gateway through the Lambda `Invoke` API | the private tool path, with plain JSON between functions |
| SQS event records with partial batch responses | ingestion, OR-Tools matching in the jobs function, real-time event delivery, mission emails through the notifier, and the queue fallback of multi-agent runs |
| `agent_step` invoked in a loop that follows the state machine's `continue` and `retry` outputs | the Step Functions mode of a multi-agent run, end to end through gateway and executor |
| The WebSocket authorizer, `$connect`/`$disconnect` and the publisher, with DynamoDB and the management API in moto | only valid Cognito tokens connect, only a run's owner subscribes, events reach the connection |
| The API behind the Lambda Web Adapter, called with API Gateway HTTP API v2 events and RS256 tokens shaped like Cognito's | offline token checks with the deploy-time JWKS, multipart uploads in base64 |

In CI nothing is pulled anonymously from ECR Public, which answers `429 Data limit exceeded` to shared runner addresses: the emulator is AWS's release binary from GitHub, pinned by checksum; the local stack builds the `api` target, which has no Lambda Web Adapter; and the `lambda-api` target that `deploy.sh` pushes gets the adapter image from the Actions cache (`scripts/ci-lambda-adapter.sh`), saved as soon as one pull succeeds.

IAM policies, VPC endpoints, RDS Proxy, the Step Functions service itself, Bedrock, SES, Cognito's hosted pages, CloudFront and WAF are account services: `connect-aws` checks them before Terraform runs and `verify-aws.sh` after every deployment, through its `runtime-check` probe. `SECONDCHANCE_EMULATION_KEEP=1` leaves the environment running for inspection.

## Mission emails (Amazon SES)

Mission assignments and cancellations reach volunteers by email (FR-026); everything else is in-app.

1. **Sender.** `SECONDCHANCE_NOTIFICATION_SENDER` (Terraform `notification_sender_email`) is the From address; without it the alarm address is used. Terraform creates it as an SES email identity and SES mails it a verification link: open it once. `verify-aws.sh` warns until it is verified.
2. **Sandbox.** A new account sends only to verified recipients. Request production access in the SES console (region `eu-central-1`) before volunteers rely on email; until then the notifier records each refused message as `refused`, without retrying it into the DLQ, and the in-app notification is the delivery channel.
3. **Recipients.** The notifier runs outside the VPC with no data permission: it reads the `notify` queue, looks up the volunteer's verified email in Cognito by `sub` (`cognito-idp:ListUsers`) and sends with `ses:SendEmail`, allowed only from the configured sender. Synthetic demo users have no Cognito account and are recorded as `recipient_unknown`.
4. **Content.** A fixed template per language says that a mission is waiting and links to the web app: no offer details, names or beneficiary data.
5. **Recovery.** The API hands each email to the queue after the commit; the scheduled recovery job re-sends any outbox row still pending after a minute. Transient SES errors are retried by SQS and land in `secondchance-<env>-notify-dlq` after five attempts (alarm).

## Account checks at every deployment

Static validation cannot prove account-specific permissions, service quotas or regional availability. `connect-aws` must complete without bypassing any preflight or smoke check, and `verify-aws.sh` checks the deployed stack: the API health endpoint, the agent state machine, the `agent-step`, `jobs`, `notifier`, `mcp-gateway` and `requeue` functions, the `jobs`, `notify` and `realtime-events` queues with live consumers, the SES sender, the private `runtime-check` probe (Aurora, embeddings, Converse, Guardrail, router, OR-Tools) and, in the demo, an authorised RAG search through the MCP Gateway. Worth knowing for a new account:

- **Bedrock:** access to the `eu.anthropic.claude-haiku-5-5` geographic inference profile and its current EU destination regions. The application uses `bedrock-runtime` Converse through the private VPC endpoint; confirm the account quota and Marketplace access with a synthetic smoke request.
- **Aurora:** that `aurora_engine_version` supports 0 ACU, and that `GRANT rds_iam` and the `vector` and `postgis` extensions work with the master user.
- **RDS Proxy:** end-to-end IAM authentication for all three database roles and connection borrowing under concurrency. With a proxy attached Aurora does not auto-pause (AWS documents this), so the demo pays for at least 0.5 ACU while it is up.
- **Agent orchestration:** one Standard Workflow execution per run, transient Lambda retry behaviour, immediate `budget_exhausted` termination and recovery of a run whose initial dispatch is interrupted.
- **Real-time channel:** Cognito-backed `$connect`, tenant/run ownership checks, stale-connection cleanup and browser recovery through polling after a forced disconnect.
- **Cognito:** the price of the chosen plan (`cognito_tier`). The API never calls Cognito at request time: Terraform reads the pool's JWKS during `apply` and passes it to the API function; sign-out uses the hosted `/logout` page because Cognito publishes no `end_session_endpoint`.
- **Lambda quota:** a fresh account may start at 10 concurrent executions. `connect-aws` warns below 50 and refuses the pilot below 125; ask for 1000 in Service Quotas (`L-B99A9384`).
- **Budget:** account-wide on purpose (Bedrock tokens and data transfer carry no resource tags): deploy into a dedicated account.
- **Requeue schedule:** hourly in the demo, every 2 minutes in the pilot.
- **Uploads:** on AWS the PDF limit is 4 MB (Lambda payload limit). Larger files need a direct S3 upload with a presigned URL (FR-015).
- **SES:** sender verified and production access granted before volunteers rely on email (see above).
- **OR-Tools:** the solver runs in the `jobs` function (2 GB, 300 s, read-only filesystem); `runtime-check` solves a small model to prove the native library loads in the Lambda sandbox.
