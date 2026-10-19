# SecondChance on AWS

Serverless, multi-tenant, EU-only. AI agents propose, people decide.

```mermaid
%%{init: {"theme": "base", "themeVariables": {"fontFamily": "Inter, Segoe UI, Arial, sans-serif", "fontSize": "15px", "background": "#FFFFFF", "clusterBkg": "#FAFAFB", "clusterBorder": "#9CA3AF", "lineColor": "#545B64", "edgeLabelBackground": "#FFFFFF", "primaryTextColor": "#16191F"}}}%%
flowchart TB
    U(["👥 <b>Users</b><br/>donors · volunteers · NGO staff"])

    subgraph EDGE["🌍 EDGE · global"]
        WAF["🛡️ <b>AWS WAF</b><br/><i>Web ACL · protects CloudFront</i>"]
        CF["🌐 <b>Amazon CloudFront</b><br/><i>CDN · security headers</i>"]
        WEB[("🪣 <b>Amazon S3</b><br/><i>React SPA · via OAC</i>")]
    end

    subgraph ENTRY["🚪 ENTRY AND IDENTITY · eu-central-1"]
        COG["🔐 <b>Amazon Cognito</b><br/><i>User Pool · OIDC + PKCE</i>"]
        HTTP["<b>API Gateway</b><br/><i>HTTP API · JWT authorizer</i>"]
        WS["<b>API Gateway</b><br/><i>WebSocket API</i>"]
    end

    subgraph VPC["🔒 PRIVATE VPC · 2 AZ · no internet gateway · no NAT"]
        subgraph APP["⚙️ Application · AWS Lambda"]
                API["λ <b>api</b><br/><i>FastAPI</i>"]
            JOBS["λ <b>jobs</b><br/><i>PDF ingest · OR-Tools</i>"]
            RT["λ <b>realtime</b><br/><i>WebSocket</i>"]
            MAINT["λ <b>retention</b><br/><i>requeue</i>"]
        end
        subgraph AGENT["🤖 Governed agents · AI proposes, people decide"]
                STEP["λ <b>agent-step</b><br/><i>one bounded turn</i>"]
            MCP["λ <b>mcp-gateway</b><br/><i>allow-list · quota · audit</i>"]
            TOOL["λ <b>tool-executor</b><br/><i>read-only tools</i>"]
            STEP --> MCP --> TOOL
        end
        PROXY["<b>RDS Proxy</b><br/><i>IAM auth · TLS</i>"]
        DB[("🐘 <b>Aurora PostgreSQL</b><br/><i>Serverless v2 · Row-Level Security<br/>pgvector · PostGIS</i>")]
        APP --> PROXY
        TOOL --> PROXY
        PROXY --> DB
    end

    subgraph ASYNC["🔁 ORCHESTRATION AND MESSAGING"]
        SCH["⏰ <b>EventBridge</b><br/><i>Scheduler</i>"]
        SFN["<b>Step Functions</b><br/><i>Standard</i>"]
        SQS["📨 <b>Amazon SQS</b><br/><i>queues + DLQ</i>"]
        NOTIF["λ <b>notifier</b><br/><i>no data access</i>"]
        SES["✉️ <b>Amazon SES</b>"]
        SQS --> NOTIF --> SES
    end

    subgraph MANAGED["☁️ MANAGED SERVICES · via VPC endpoints"]
        BR["🧠 <b>Amazon Bedrock</b><br/><i>Claude Haiku · Titan Embeddings<br/>Guardrails · EU inference</i>"]
        S3O[("🪣 <b>Amazon S3</b><br/><i>tenant documents · KMS</i>")]
        DDB[("<b>Amazon DynamoDB</b><br/><i>quotas · connections</i>")]
    end

    subgraph OPS["🛡️ SECURITY AND OPERATIONS"]
        KMS["🔑 <b>AWS KMS</b>"]
        SM["<b>Secrets Manager</b>"]
        CW["📊 <b>CloudWatch</b><br/><i>+ X-Ray</i>"]
        SNS["🔔 <b>Amazon SNS</b><br/><i>alarms</i>"]
        CT["📜 <b>AWS CloudTrail</b><br/><i>validated audit trail</i>"]
        GD["🕵️ <b>Amazon GuardDuty</b><br/><i>threats · malware scan</i>"]
    end

    U -->|HTTPS| EDGE
    U -->|sign-in| COG
    U -->|wss| WS
    EDGE -->|/api/*| HTTP
    HTTP --> API
    WS --> RT
    API -->|async jobs| SQS
    API -->|start run| SFN
    SFN -->|each step| STEP
    SCH --> MAINT
    SQS -->|jobs queue| JOBS
    API & JOBS --> BR & S3O
    STEP & TOOL --> BR
    MCP -->|quota| DDB
    S3O -.->|every upload| GD
    GD -.->|findings| SNS
    RT --> DDB
    VPC ~~~ ASYNC
    MANAGED ~~~ OPS

    classDef users fill:#F3F4F6,stroke:#4B5563,stroke-width:2px,color:#16191F
    classDef compute fill:#FFF3E6,stroke:#ED7100,stroke-width:2px,color:#16191F
    classDef net fill:#F3ECFF,stroke:#8C4FFF,stroke-width:2px,color:#16191F
    classDef storage fill:#F1F7E6,stroke:#7AA116,stroke-width:2px,color:#16191F
    classDef db fill:#E8F0FE,stroke:#3B48CC,stroke-width:2px,color:#16191F
    classDef integ fill:#FDEBF4,stroke:#E7157B,stroke-width:2px,color:#16191F
    classDef sec fill:#FDECEF,stroke:#DD344C,stroke-width:2px,color:#16191F
    classDef ai fill:#E3F8F4,stroke:#01A88D,stroke-width:2px,color:#16191F

    class U users
    class API,JOBS,RT,MAINT,STEP,MCP,TOOL,NOTIF compute
    class CF,HTTP,WS,PROXY net
    class WEB,S3O storage
    class DB,DDB db
    class SCH,SFN,SQS,SES,SNS,CW,CT integ
    class WAF,COG,KMS,SM,GD sec
    class BR ai

    style EDGE fill:#FFFFFF,stroke:#9CA3AF,stroke-dasharray:6 4
    style ENTRY fill:#FFFFFF,stroke:#9CA3AF,stroke-dasharray:6 4
    style VPC fill:#F7FBEF,stroke:#7AA116,stroke-width:2px,stroke-dasharray:6 4
    style APP fill:#FFFFFF,stroke:#ED7100
    style AGENT fill:#FFF8F0,stroke:#ED7100,stroke-width:2px,stroke-dasharray:6 4
    style ASYNC fill:#FFFFFF,stroke:#E7157B,stroke-dasharray:6 4
    style MANAGED fill:#FFFFFF,stroke:#9CA3AF,stroke-dasharray:6 4
    style OPS fill:#FFFFFF,stroke:#DD344C,stroke-dasharray:6 4
```

**Colour = AWS service category:** 🟧 compute · 🟪 networking · 🟩 storage · 🟦 database · 🟥 security and identity · 🩷 application integration · 🟢 machine learning.

## How to read it

1. **Edge:** the browser loads the React app from S3 through CloudFront, behind WAF. `/api/*` goes to API Gateway.
2. **Identity:** Cognito signs users in; API Gateway checks the JWT. The token says *who*, the database decides *what* (Row-Level Security per tenant).
3. **Private compute:** every Lambda that touches data runs in a VPC with no internet path. AWS services are reached through VPC endpoints.
4. **Agents under governance:** Step Functions runs the agent one bounded turn at a time. Every tool call passes an MCP gateway (allow-list, quota, audit) and runs read-only. Agents propose, a person confirms.
5. **Async and real-time:** heavy work (PDF ingestion, matching) goes through SQS. Results reach the browser over WebSocket; emails go out through SES, from Lambdas that have no database access.
6. **Detection:** CloudTrail records every AWS action and who touched which tenant document; GuardDuty watches the account and scans every upload, and the jobs worker parses a PDF only after a clean verdict.
7. **AI in the EU:** Bedrock with an EU inference profile, Guardrails on prompt attacks and personal data.

## Export as an image

Paste the `mermaid` block into https://mermaid.live, then **Actions → PNG** (or SVG). For a LinkedIn feed image, a 1200 px wide export reads well on mobile.
