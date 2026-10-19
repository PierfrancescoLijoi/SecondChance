"""Draw the deployed AWS architecture as SVG (docs/images/aws-architecture.svg).

The layout is hand-placed; the content mirrors infra/terraform/modules/secondchance, which stays the
source of truth. Change the Terraform first, then the boxes and arrows here, then regenerate:

  python3 scripts/architecture-diagram.py docs/images/aws-architecture.svg
  chromium --headless --hide-scrollbars --window-size=1920,1300 --force-device-scale-factor=2 \
    --screenshot=docs/images/aws-architecture.png docs/images/aws-architecture.svg

Standard library only; the PNG needs any headless Chromium (the README embeds it).
"""
import sys
from xml.sax.saxutils import escape

W, H = 1920, 1300
FONT = "Inter, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'DejaVu Sans Mono', Menlo, Consolas, monospace"

C = {
    "ink": "#16191F", "muted": "#4B5563", "soft": "#6B7280", "rule": "#D1D5DB",
    "compute": "#ED7100", "net": "#8C4FFF", "storage": "#7AA116", "db": "#C925D1",
    "integ": "#E7157B", "sec": "#DD344C", "ai": "#01A88D", "slate": "#232F3E",
    "rt": "#8C4FFF", "agent": "#ED7100",
}
FILL = {
    "compute": "#FFF7EF", "net": "#F6F1FF", "storage": "#F5F9EC", "db": "#FCF1FD",
    "integ": "#FEF1F7", "sec": "#FDF1F3", "ai": "#ECFAF7", "users": "#F3F4F6",
}

out = []


def add(s):
    out.append(s)


def text(x, y, s, size=12, weight=400, color=None, family=FONT, anchor="start", extra=""):
    color = color or C["muted"]
    add(f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
        f'fill="{color}" text-anchor="{anchor}" {extra}>{escape(s)}</text>')


def box(x, y, w, h, cat, tag, title, lines=(), title_size=15, line_size=12):
    color, fill = C[cat], FILL[cat]
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{color}" stroke-width="1.4"/>')
    add(f'<rect x="{x}" y="{y}" width="5" height="{h}" rx="2" fill="{color}"/>')
    ty = y + 17
    if tag:
        text(x + 14, ty, tag, size=9.5, weight=600, color=color, family=MONO, extra='letter-spacing="0.6"')
        ty += 18
    else:
        ty += 2
    text(x + 14, ty, title, size=title_size, weight=700, color=C["ink"])
    ty += 17
    for line in lines:
        text(x + 14, ty, line, size=line_size)
        ty += line_size + 4


def zone(x, y, w, h, label, color="#9CA3AF", fill="none", dash="6 5", label_color=None):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{color}" '
        f'stroke-width="1.3" stroke-dasharray="{dash}"/>')
    text(x + 14, y + 20, label, size=11, weight=700, color=label_color or C["muted"], family=MONO,
         extra='letter-spacing="1"')


# One arrowhead per line colour.
MARKERS = {C["slate"]: "a-slate", C["agent"]: "a-agent", C["db"]: "a-db", C["rt"]: "a-rt", C["soft"]: "a-soft"}


def arrow(points, color=None, dash=None, width=1.6, marker="end", label=None, lx=None, ly=None,
          lanchor="start"):
    color = color or C["slate"]
    d = "M " + " L ".join(f"{px} {py}" for px, py in points)
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    m = f' marker-end="url(#{MARKERS[color]})"' if marker == "end" else ""
    add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash_attr}{m} '
        f'stroke-linejoin="round"/>')
    if label:
        text(lx, ly, label, size=10.5, weight=600, color=color, anchor=lanchor)


def line(points, color, width=1.6, dash=None):
    arrow(points, color=color, width=width, dash=dash, marker=None)


# ---------------------------------------------------------------- canvas
add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
    f'role="img" aria-labelledby="t d">')
add('<title id="t">SecondChance on AWS</title>')
add('<desc id="d">Deployed AWS architecture of SecondChance as defined in infra/terraform/modules/secondchance: '
    'CloudFront with WAF, API Gateway HTTP and WebSocket APIs, Cognito, Lambda functions inside a private VPC '
    'without NAT, RDS Proxy and Aurora PostgreSQL, SQS, Step Functions, EventBridge Scheduler, DynamoDB, S3, '
    'Bedrock, SES and the cross-cutting security, observability and delivery services.</desc>')
add('<defs>')
for col, mid in MARKERS.items():
    add(f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{col}"/></marker>')
add('</defs>')
add(f'<rect width="{W}" height="{H}" fill="#FFFFFF"/>')

# ---------------------------------------------------------------- header + legend
text(30, 46, "SecondChance on AWS", size=28, weight=800, color=C["ink"])
text(30, 74, "Deployed view of infra/terraform/modules/secondchance · eu-central-1 · every arrow is a call "
     "the module's IAM policies allow", size=13.5)

lx, ly = 1215, 26
add(f'<rect x="{lx}" y="{ly}" width="675" height="64" rx="8" fill="#F9FAFB" stroke="{C["rule"]}"/>')
legend = [
    ((lx + 16, ly + 22), C["slate"], None, "synchronous call / invocation"),
    ((lx + 16, ly + 46), C["slate"], "6 4", "asynchronous: queue, schedule"),
    ((lx + 240, ly + 22), C["agent"], None, "governed agent path"),
    ((lx + 240, ly + 46), C["db"], None, "database connection (IAM token)"),
    ((lx + 470, ly + 22), C["rt"], None, "real-time return path"),
    ((lx + 470, ly + 46), C["soft"], "2 3", "configuration / attachment"),
]
for (sx, sy), col, dash, label in legend:
    arrow([(sx, sy), (sx + 34, sy)], color=col, dash=dash, width=1.8)
    text(sx + 42, sy + 4, label, size=11.5, color=C["ink"])

# ---------------------------------------------------------------- users
add(f'<rect x="30" y="250" width="170" height="400" rx="10" fill="{FILL["users"]}" stroke="#9CA3AF" stroke-width="1.4"/>')
text(46, 274, "USERS", size=9.5, weight=600, color=C["soft"], family=MONO, extra='letter-spacing="0.6"')
text(46, 296, "Browser", size=16, weight=700, color=C["ink"])
text(46, 315, "React SPA, one origin", size=12)
roles = ["donor", "volunteer", "coordinator", "org_admin", "center_staff", "platform_admin"]
text(46, 350, "roles (from membership):", size=11.5, color=C["soft"])
for i, r in enumerate(roles):
    text(56, 372 + i * 19, r, size=11.5, color=C["ink"], family=MONO)
text(46, 510, "The token proves who;", size=11.5, color=C["soft"])
text(46, 526, "Aurora decides what.", size=11.5, color=C["soft"])

# ---------------------------------------------------------------- edge (global)
zone(235, 110, 235, 275, "EDGE · GLOBAL")
box(250, 140, 205, 82, "sec", "SECURITY · US-EAST-1", "AWS WAF",
    ["web ACL on the distribution", "managed rules · 1000 req/5 min/IP"], line_size=11)
box(250, 245, 205, 128, "net", "CONTENT DELIVERY", "Amazon CloudFront",
    ["/* → S3 web (OAC)", "/api/* → HTTP API, no cache", "functions: spa · strip-api", "CSP · HSTS · frame DENY"],
    line_size=11)
arrow([(352, 222), (352, 245)], color=C["soft"], dash="2 3", width=1.4, marker=None)
text(360, 238, "attached", size=10, color=C["soft"])

# ---------------------------------------------------------------- region frame
zone(490, 100, 1415, 945, "AWS REGION · eu-central-1 (Frankfurt)", color="#232F3E", dash="8 5",
     label_color=C["ink"])

# public regional column
box(520, 150, 220, 72, "storage", "STORAGE", "S3 · web bucket", ["SPA build + config.json", "read only via CloudFront OAC"],
    line_size=11)
box(520, 240, 220, 92, "net", "NETWORKING", "API Gateway · HTTP API",
    ["JWT authorizer: Cognito issuer", "throttle 50 rps · burst 100", "GET /health without token"], line_size=11)
box(520, 350, 220, 92, "net", "NETWORKING", "API Gateway · WebSocket",
    ["$connect: Lambda authorizer", "routes → λ realtime", "@connections ← publisher"], line_size=11)
box(520, 462, 220, 62, "compute", "LAMBDA · OUTSIDE VPC · NO DATA", "λ realtime-authorizer",
    [], title_size=13.5)
text(534, 516, "JWT check with JWKS in env", size=11)
box(520, 545, 220, 100, "sec", "IDENTITY", "Amazon Cognito",
    ["user pool · Hosted UI", "code + PKCE · MFA optional", "JWKS copied to env at apply"], line_size=11)
box(520, 665, 220, 80, "compute", "LAMBDA · OUTSIDE VPC · NO DATA", "λ notifier",
    ["← SQS notify (ids only)", "address by sub · fixed template"], title_size=13.5, line_size=11)
box(520, 765, 220, 62, "sec", "EMAIL", "Amazon SES", ["one verified sender identity"], title_size=13.5, line_size=11)
box(520, 850, 220, 80, "compute", "LAMBDA · OUTSIDE VPC · NO DATA", "λ realtime-publisher",
    ["← SQS realtime-events", "DynamoDB → PostToConnection"], title_size=13.5, line_size=11)
text(520, 955, "Outside the VPC, no data access:", size=11, color=C["soft"])
text(520, 970, "reach Cognito, SES, @connections", size=11, color=C["soft"])

# ---------------------------------------------------------------- VPC
zone(790, 140, 690, 845, "VPC 10.40.0.0/16 · PRIVATE SUBNETS IN 2 AZ · NO IGW · NO NAT", color="#7AA116",
     fill="#FBFDF7", label_color="#4D6B0E")

# column A
box(825, 185, 180, 115, "compute", "LAMBDA · IN VPC", "λ api",
    ["FastAPI · Web Adapter", "JWT + membership + quotas", "→ S3 · SQS · SFN · Bedrock"], line_size=11)
box(825, 345, 180, 100, "compute", "LAMBDA · IN VPC", "λ realtime",
    ["$connect · $disconnect", "active member + run owner", "→ DynamoDB connections"], line_size=11)

# column C
box(1260, 185, 175, 55, "compute", None, "λ retention · requeue", ["recovery · outbox · expiry"],
    title_size=13, line_size=11)
box(1260, 248, 175, 52, "compute", None, "λ migrate", ["deploy only · bootstrap roles"], title_size=13,
    line_size=11)
box(1260, 340, 175, 115, "compute", "LAMBDA · IN VPC", "λ jobs",
    ["PDF parse · chunk · embed", "OR-Tools CP-SAT matching", "writes SHA-256 proposals"], line_size=11)

# governed path
add(f'<rect x="812" y="490" width="640" height="172" rx="10" fill="none" stroke="{C["agent"]}" '
    f'stroke-width="1.4" stroke-dasharray="6 4"/>')
text(826, 508, "GOVERNED AGENT TOOL PATH · AI PROPOSES, PEOPLE DECIDE", size=10.5, weight=700,
     color=C["agent"], family=MONO, extra='letter-spacing="0.6"')
box(825, 520, 180, 128, "compute", "LAMBDA · IN VPC", "λ tool-executor",
    ["caller = active run step", "requester identity + RLS", "read-only tools", "→ Bedrock embeddings"],
    line_size=11)
box(1040, 520, 180, 128, "compute", "LAMBDA · IN VPC", "λ mcp-gateway",
    ["agent + role allow-list", "schema · quota · audit", "own role, logs, bulkhead", "no database access"],
    line_size=11)
box(1260, 520, 175, 128, "compute", "LAMBDA · IN VPC", "λ agent-step",
    ["one bounded turn", "supervisor · specialists", "→ Bedrock · SQS events", "12 steps · 60k tokens"],
    line_size=11)

# data
box(825, 700, 395, 70, "db", "DATABASE", "Amazon RDS Proxy",
    ["IAM auth end to end · TLS required · pool max 80 %"], line_size=11)
box(825, 815, 610, 150, "db", "DATABASE", "Aurora PostgreSQL Serverless v2",
    ["RLS on every tenant table · DB users app, maintenance, migrator (IAM tokens, no BYPASSRLS)",
     "pgvector · full-text en/da/pl/it · PostGIS",
     "runs, steps, agent memory · immutable SHA-256 proposals · email outbox · audit",
     "KMS at rest · master secret in Secrets Manager · pilot: reader in the second AZ"], line_size=11.5)

# endpoint strip
add(f'<rect x="1446" y="185" width="26" height="780" rx="6" fill="#F6F1FF" stroke="{C["net"]}" stroke-width="1.2"/>')
text(1463, 575, "VPC ENDPOINTS · interface: sqs · bedrock-runtime · secretsmanager · lambda · states  ·  "
     "gateway: s3 · dynamodb", size=10.5, weight=600, color=C["net"], family=MONO, anchor="middle",
     extra='transform="rotate(-90 1463 575)" letter-spacing="0.3"')

# ---------------------------------------------------------------- managed services
box(1520, 180, 335, 60, "integ", "APP INTEGRATION", "EventBridge Scheduler",
    [], title_size=13.5)
text(1534, 233, "retention 03:15 UTC daily · requeue every 2 min", size=11)
box(1520, 250, 335, 55, "sec", None, "Secrets Manager", ["Aurora master secret · read by λ migrate only"],
    title_size=13.5, line_size=11)

box(1520, 330, 335, 140, "integ", "APP INTEGRATION", "Amazon SQS · DLQ after 5 receives", [], title_size=13.5)
queues = [
    (380, "jobs", "← api, requeue → λ jobs"),
    (408, "notify", "← api, requeue → λ notifier"),
    (436, "realtime-events", "← agent-step → λ publisher"),
]
for qy, name, flow in queues:
    add(f'<rect x="1534" y="{qy - 6}" width="308" height="24" rx="5" fill="#FFFFFF" stroke="{C["integ"]}" stroke-width="1"/>')
    text(1542, qy + 10, name, size=11, weight=700, color=C["ink"], family=MONO)
    text(1662, qy + 10, flow, size=10, color=C["muted"], family=MONO)

box(1520, 495, 335, 120, "integ", "APP INTEGRATION", "Step Functions · Standard",
    ["loop: invoke agent-step → wait 30 s on lease", "→ continue or succeed · 6 retries per step",
     "started by api · requeue (start / redrive)", "logs without execution data"], title_size=13.5, line_size=11)
box(1520, 640, 335, 90, "db", "DATABASE", "Amazon DynamoDB · on demand · KMS",
    ["mcp-rate-limit ← mcp-gateway (1-min window)", "realtime-connections ← realtime, publisher"],
    title_size=13.5, line_size=11)
box(1520, 746, 335, 92, "storage", "STORAGE", "S3 · objects bucket",
    ["tenants/{tenant}/ · SSE-KMS · versioned · ← api, jobs",
     "GuardDuty malware scan: infected files unreadable"], title_size=13.5, line_size=11)
box(1520, 850, 335, 125, "ai", "MACHINE LEARNING", "Amazon Bedrock",
    ["Claude Haiku · eu. inference profile (Converse)", "Titan Text Embeddings V2",
     "Guardrails: prompt attack · PII · grounding", "← api, jobs, agent-step, tool-executor"],
    title_size=13.5, line_size=11)

# ---------------------------------------------------------------- arrows: browser and edge
arrow([(200, 300), (250, 300)], label="HTTPS", lx=207, ly=292)
arrow([(455, 272), (478, 272), (478, 186), (520, 186)])
text(462, 266, "OAC", size=10, weight=600, color=C["slate"])
arrow([(455, 310), (520, 310)], label="/api/*", lx=470, ly=304)
arrow([(200, 405), (520, 405)], label="wss · token in subprotocol", lx=262, ly=399)
arrow([(200, 590), (520, 590)], label="OIDC code + PKCE (Hosted UI)", lx=262, ly=584)

# public column internal
arrow([(630, 442), (630, 462)])
text(638, 456, "$connect", size=10, weight=600, color=C["slate"])
arrow([(600, 665), (600, 645)])
text(608, 659, "ListUsers by sub", size=10, weight=600, color=C["slate"])
arrow([(600, 745), (600, 765)])
text(608, 759, "SendEmail (sender only)", size=10, weight=600, color=C["slate"])
arrow([(520, 895), (504, 895), (504, 428), (520, 428)], color=C["rt"])
text(498, 700, "PostToConnection", size=10, weight=600, color=C["rt"], anchor="middle",
     extra='transform="rotate(-90 498 700)"')

# into the VPC
arrow([(740, 285), (825, 285)], label="proxy", lx=750, ly=279)
arrow([(740, 405), (825, 405)], label="routes", lx=750, ly=399)

# ---------------------------------------------------------------- arrows: api to managed services
arrow([(1005, 255), (1022, 255), (1022, 316), (1600, 316), (1600, 330)])
text(1032, 310, "SendMessage → jobs, notify", size=10.5, weight=600, color=C["slate"])
arrow([(1022, 316), (1022, 482), (1700, 482), (1700, 495)])
text(1032, 476, "StartExecution", size=10.5, weight=600, color=C["slate"])

# schedule, secrets, queue consumer
arrow([(1520, 212), (1435, 212)], dash="6 4")
arrow([(1435, 274), (1520, 274)])
arrow([(1534, 392), (1435, 392)], dash="6 4")

# governed agent path
arrow([(1520, 575), (1435, 575)], color=C["agent"], width=2.2)
arrow([(1260, 584), (1220, 584)], color=C["agent"], width=2.2)
arrow([(1040, 584), (1005, 584)], color=C["agent"], width=2.2)
arrow([(1130, 648), (1130, 680), (1520, 680)], color=C["agent"], dash="6 4", width=1.8,
      label="quota: conditional UpdateItem", lx=1252, ly=674)

# real-time events out of agent-step
arrow([(1435, 535), (1500, 535), (1500, 448), (1534, 448)], color=C["rt"])
text(1494, 505, "events", size=10, weight=600, color=C["rt"], anchor="middle",
     extra='transform="rotate(-90 1494 505)"')

# database buses
db = C["db"]
for y in (200, 365, 630):
    line([(825, y), (812, y)], db)
line([(812, 200), (812, 735)], db)
arrow([(812, 735), (825, 735)], color=db)
for y in (226, 290, 445, 640):
    line([(1260, y), (1240, y)], db)
line([(1240, 226), (1240, 735)], db)
arrow([(1240, 735), (1220, 735)], color=db)
arrow([(1022, 770), (1022, 815)], color=db, width=2.2)
text(1032, 797, "IAM auth · TLS", size=10.5, weight=600, color=db)

# queue consumers outside the VPC
arrow([(1842, 420), (1872, 420), (1872, 1005), (770, 1005), (770, 705), (740, 705)], dash="6 4")
text(1300, 999, "notify → λ notifier", size=10.5, weight=600, color=C["slate"])
arrow([(1842, 448), (1888, 448), (1888, 1025), (755, 1025), (755, 890), (740, 890)], color=C["rt"], dash="6 4")
text(1300, 1019, "realtime-events → λ realtime-publisher", size=10.5, weight=600, color=C["rt"])

# ---------------------------------------------------------------- cross-cutting band
panels = [
    ("SECURITY", C["sec"], [
        "KMS: one CMK with rotation for Aurora, the master secret,",
        "S3 objects, logs, DynamoDB, SNS, ECR and the audit trail",
        "IAM: one role per Lambda family; rds-db:connect to its own",
        "database user only; scheduler invokes retention + requeue only",
        "CloudTrail: multi-region, validated files, S3 object events",
        "GuardDuty + malware scan; jobs parse only clean uploads",
    ]),
    ("OBSERVABILITY AND COST", C["integ"], [
        "CloudWatch Logs: 30 days, KMS, no PII in access logs",
        "Alarms: API 5xx and p95, Lambda errors and throttles, DLQ,",
        "queue age, Step Functions failures, MCP denials, GuardDuty → SNS",
        "X-Ray active tracing on Lambda and Step Functions; OTLP optional",
        "AWS Budgets: account-wide monthly alert (30 / 150 USD)",
    ]),
    ("DELIVERY", C["slate"], [
        "GitHub Actions 'production' → OIDC → STS → deploy role",
        "with permission boundary (no users, keys or account changes)",
        "Terraform state: S3 + KMS, native S3 locking",
        "ECR: immutable tags, scan on push (api, worker, gateway)",
        "deploy.sh: apply → λ migrate → S3 sync → CloudFront invalidation",
    ]),
    ("DEMO vs PILOT", C["compute"], [
        "Aurora: 0–2 ACU, 1 instance  |  0.5–8 ACU, writer + reader",
        "Reserved concurrency: none  |  api 20 · mcp-gateway 5",
        "requeue: hourly  |  every 2 minutes",
        "Backups 7 days  |  14 days, deletion protection, PITR",
        "Both: same module, same images, eu-central-1",
    ]),
]
px = 30
widths = [455, 455, 455, 430]
for (title, col, lines), pw in zip(panels, widths):
    add(f'<rect x="{px}" y="1065" width="{pw}" height="200" rx="10" fill="#F9FAFB" stroke="{C["rule"]}"/>')
    add(f'<rect x="{px}" y="1065" width="{pw}" height="5" rx="2" fill="{col}"/>')
    text(px + 16, 1094, title, size=11, weight=700, color=col, family=MONO, extra='letter-spacing="1"')
    for i, s in enumerate(lines):
        text(px + 16, 1120 + i * 27, s, size=12, color=C["ink"])
    px += pw + 15

text(30, 1288, "Source: infra/terraform/modules/secondchance (network, edge, identity, compute, data, storage, "
     "queues, orchestration, realtime, ai, notifications, observability, detection). Local equivalents: infra/README.md.",
     size=11, color=C["soft"])

add('</svg>')

with open(sys.argv[1], "w", encoding="utf-8") as f:
    f.write("\n".join(out) + "\n")
