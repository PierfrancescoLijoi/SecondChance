# infra

Terraform for AWS ([ADR-018](../docs/ADR.md#adr-018--aws-deployment-terraform-no-access-keys-self-configuration)). It is not run by hand: [`scripts/deploy.sh`](../scripts/deploy.sh) and [`scripts/destroy.sh`](../scripts/destroy.sh) use it. Credentials and first run: [docs/deployment.md](../docs/deployment.md).

```
terraform/
  bootstrap/              once per account: state bucket (KMS, S3 locking), GitHub OIDC provider, deploy role with a permission boundary
  modules/secondchance/   the whole environment, one file per area (network, data, storage, queues, identity, ai, compute, edge, observability)
  envs/demo/              ephemeral demo with synthetic data: Aurora at 0 ACU, buckets that can be emptied, no deletion protection
  envs/pilot/             pilot: two Aurora instances, deletion protection, longer backup retention
```

Pinned versions: Terraform 1.16.5, AWS provider `~> 6.66`, lock files for Linux, Windows and macOS. CI runs `fmt -check`, `validate` and Trivy (HIGH and CRITICAL fail the build).

## From logical component to service

| Component | On AWS | Locally (Compose) |
|---|---|---|
| Web app | private S3 + CloudFront (OAC), WAF in `us-east-1`, security headers, `config.json` written by Terraform | nginx (`web`) |
| Identity | Cognito user pool, Hosted UI with PKCE; roles live in `membership`, not in the token | HS256 mock OIDC (`/dev/token`), refused outside `SECONDCHANCE_ENV=local` |
| API | API Gateway HTTP API (JWT authorizer, throttling) → Lambda with FastAPI through the Lambda Web Adapter | uvicorn, same image |
| Agent orchestration | Step Functions Standard → bounded agent-step Lambda; run state remains in Aurora | `agents-worker` drives the same bounded runtime through ElasticMQ |
| Workers | Lambda on the `jobs` and real-time event queues, retention and recovery from EventBridge Scheduler | `jobs-worker`, `agents-worker` |
| Data | RDS Proxy → Aurora PostgreSQL Serverless v2, PostGIS, pgvector, RLS; end-to-end IAM authentication, master password managed by RDS | PostgreSQL 16 in a container |
| Queues | SQS with DLQs | ElasticMQ |
| Objects | KMS-encrypted S3, Block Public Access, keys `tenants/{tenant}/` | SeaweedFS |
| LLM and embeddings | Bedrock Runtime Converse: EU Claude Haiku inference profile, Titan Text Embeddings V2, Guardrails | deterministic hash embeddings, optional Ollama |
| Observability | CloudWatch (logs, alarms), encrypted SNS, AWS Budgets; OTLP to a collector when needed | `grafana/otel-lgtm` (`observability` profile) |
| Network | private VPC without NAT; interface endpoints include Lambda, SQS, Bedrock, Secrets Manager and Cognito; S3 and DynamoDB use gateway endpoints | Compose network, ports on 127.0.0.1 |
| MCP tools | dedicated Gateway Lambda/IAM/logs/concurrency plus DynamoDB quotas; private tool-executor Lambda | separate `mcp-gateway` and non-published `tool-executor` containers |
| Real-time updates | authenticated API Gateway WebSocket, DynamoDB connection registry, SQS relay and public publisher Lambda | five-second polling fallback |

The module defaults to `router_mode = "hybrid"`: hard safety rules and confident direct paths avoid an LLM call, while ambiguous or multi-step requests use the configured Bedrock model with a strict output contract. Optional Rizzo Flow primary/shadow URLs are Terraform inputs, but must resolve through private VPC connectivity because the deployment intentionally has no NAT gateway.

The module creates no NAT gateway: every service the Lambda functions reach from the VPC needs an endpoint (`interface_endpoints`). A new service without an endpoint fails with a timeout, not a permission error.
