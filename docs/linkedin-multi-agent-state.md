# LinkedIn draft · Multi-agent systems: where does the loop keep its state?

Second SecondChance post, after [SecondChance on AWS](linkedin-architecture.md). One design decision, as a problem and its fix.

![Where a multi-agent loop keeps its state](images/linkedin-multi-agent-state.png)

Image to post: [`images/linkedin-multi-agent-state.png`](images/linkedin-multi-agent-state.png) (3200 × 2840). Editable source: [`diagrams/linkedin-multi-agent-state.drawio`](diagrams/linkedin-multi-agent-state.drawio), generated with the PNG layout by [`diagrams/linkedin-multi-agent-state.gen.py`](diagrams/linkedin-multi-agent-state.gen.py).

---

## Post

A multi-agent run will die halfway sooner or later. The design question is what survives.

Many multi-agent prototypes keep the supervisor loop inside one process: the plan, the history and every specialist's findings live in RAM. In production that fails in four ways:

1️⃣ A timeout or restart (Lambda stops at 15 minutes, pods get evicted) loses the run and everything it learned.
2️⃣ A retry repeats a tool call that already ran.
3️⃣ Nothing stops a model that keeps looping.
4️⃣ Memory in RAM has no tenant boundary and no audit trail, and ties each run to one machine.

So the first choice is not the framework. It is where the state lives.

In SecondChance, the source-available food-rescue platform I am building, the answer is: in no process.

How it is modelled:

→ A run is a state machine in PostgreSQL. agent_run holds the status and the budgets (by default 12 steps, 60k tokens, 10 minutes). agent_step holds one row per turn, UNIQUE (run_id, seq), with an attempt counter and a lease.

→ Each step is stateless: claim (take the lease, attempt + 1, check the budget), execute one turn of one agent, then complete in a short transaction that only the claiming attempt can commit. A worker that lost its lease has its result dropped.

→ The loop lives outside the agents. AWS Step Functions invokes one step at a time and continues only when the committed outcome says so. Code and budgets end the run, not the model's text.

→ The shared blackboard is a table under Row-Level Security: per tenant and run, the source agent on every row, a 7-day expiry.

→ The supervisor plans only from a closed catalog of specialists; the server validates the plan and falls back to a fixed one when it is invalid. Tools go through an MCP gateway (allow-list, quota) and are read-only. Agents write no operational data: they return a recommendation, and a person decides.

One honest caveat: this gives exactly-once commits, not exactly-once execution. After a crash a turn can run again, but only one result is ever committed. That is why the tools are read-only.

What it buys: any instance can resume any run, a duplicate message is a no-op, a run over budget ends as budget_exhausted instead of "success", and every turn records model, prompt hash, tokens and latency. The recovery and budget paths are covered by tests against a real PostgreSQL.

The cost: more database round trips, and no hidden framework state (I skipped LangGraph checkpointers because they would duplicate state the database already owns). For a single-turn assistant this is overkill. For agents that run for minutes, touch real data or serve several tenants, it is the first decision I would make.

Rule of thumb: the agent is a function, the run is a state machine, the database is the memory.

Code and ADRs: https://github.com/PierfrancescoLijoi/SecondChance

#AgenticAI #MultiAgent #LLMOps #SoftwareArchitecture #AWS #PostgreSQL

---

## Evidence for every claim

Each statement in the post and the image, and where it is true in this repository. Tests marked ✓ were run against PostgreSQL 16 with pgvector and PostGIS, as the `secondchance_app` role (no BYPASSRLS): 43 agent, memory and tool tests, 18 tenant-isolation tests, 6 MCP Gateway tests, all passing.

| Claim | Evidence |
|---|---|
| Budgets default to 12 steps, 60k tokens, 10 minutes | `api/migrations/versions/0002_agents_memory_experiments.py` (`max_steps DEFAULT 12`, `max_tokens DEFAULT 60000`, `deadline_at DEFAULT now() + interval '10 minutes'`); `start_run(max_steps=12)` in `api/secondchance/agents/runtime.py` |
| `agent_step` has `UNIQUE (run_id, seq)`, `attempt`, `lease_until`, model, prompt hash, tokens, latency | same migration, `CREATE TABLE agent_step` |
| Claim takes a lease, increments the attempt, checks the budget | `_claim` in `runtime.py` |
| Execute holds no transaction | module docstring and `execute` in `runtime.py`; `intake` comment "never hold an Aurora transaction while waiting" in `agents/builtin.py` |
| Only the claiming attempt can commit; a late result is dropped | `_complete`: `UPDATE ... WHERE attempt = :attempt AND status = 'running'`, rollback on 0 rows · ✓ `test_worker_that_lost_its_lease_cannot_complete` |
| A duplicate message is a no-op | `_claim` returns `not_claimable` for a finished step; next step inserted `ON CONFLICT (run_id, seq) DO NOTHING` · ✓ `test_redelivered_message_does_not_run_the_step_again` |
| Over budget ends as `budget_exhausted`, decided in the commit before the next step exists | `_complete` sets the status in the same `UPDATE agent_run` and inserts the next step only if still `running` · ✓ `test_step_budget_ends_the_run_as_budget_exhausted` |
| Step Functions invokes one step and continues only on the committed outcome | `infra/terraform/modules/secondchance/orchestration.tf` (`STANDARD`, Choice on `$.continue`); `agent_step` handler in `api/secondchance/aws_lambda.py` returns `continue` from the outcome after commit |
| Any instance resumes; a lost Lambda response is recovered from the database | `workflow_resume` in `runtime.py`, Step Functions `Retry` and `Wait for lease` · ✓ `test_agent_step_recovers_when_the_previous_lambda_response_was_lost`, ✓ `test_workflow_retry_waits_while_the_original_step_still_holds_its_lease` |
| Code and budgets end the run, not the model's text | `supervisor` in `agents/builtin.py` returns `succeeded` when every planned specialist has a result; a specialist's refusal becomes `failed`; a refused or invalid plan or synthesis falls back to a deterministic one (`plan_operations`, `synthesize_results`) |
| Short transaction with `SET LOCAL` tenant | `tenant_transaction` in `api/secondchance/db.py` (`set_config(..., true)`) |
| Blackboard under RLS, source agent on every row, 7-day expiry | `agent_memory` (`source NOT NULL`, `expires_at NOT NULL`), RLS policy `tenant_isolation` in migration 0002; `run: timedelta(days=7)` in `api/secondchance/memory.py`; app role `NOBYPASSRLS` and owns nothing (`db/bootstrap.sql`) · ✓ `test_other_tenant_sees_no_memory` |
| Closed catalog, validated plan, fixed fallback | `_parse_plan` (1 to 4 steps, no repeats, registered agents only) and `FALLBACK_PLANS` in `agents/planning.py` · ✓ `test_invalid_model_plan_falls_back_to_safe_route_plan`, ✓ `test_supervisor_accepts_only_a_valid_allowlisted_plan` |
| Tools go through the MCP gateway with allow-list and quota, read-only | `Specialist.build` calls `ToolGatewayClient`; `mcp-gateway/mcp_gateway/policy.py` and DynamoDB rate limiter; `ALLOWED_TOOLS = {"knowledge_search"}`; `read_only` enforced in `api/secondchance/tools/gateway.py` · ✓ MCP Gateway tests, ✓ `test_gateway_rejects_unknown_tool_invalid_input_role_and_agent` |
| Agents write no operational data; the output is a recommendation | specialists only return findings to run memory; the supervisor ends with `Synthesis(..., recommended_next_action)`; no agent code touches offers, proposals or missions (`docs/agents.md`, "Agents never write") |
| No LangGraph checkpointers, because they would duplicate state | `docs/ADR.md`, ADR-005 and ADR-010, rejected alternatives |
| Lambda's 15-minute limit | AWS Lambda maximum function timeout (900 s) |

Not claimed, on purpose: exactly-once execution (a turn can re-run after a lost lease, which is why tools are read-only), and that agents create proposals. ADR-010 describes a `create_proposal` tool, but the code does not implement one: operational proposals come only from the OR-Tools solver and are approved by a coordinator.

## Image alt text

Two panels and a table. Left, in red: a long-running supervisor process holds plan, history and findings in RAM and calls three specialists, which write directly to tools with no guard. Right, in green: AWS Step Functions invokes a stateless agent-step Lambda once per turn (claim, execute, complete) and continues only on the committed outcome; the state lives in Aurora PostgreSQL tables agent_run, agent_step and agent_memory under Row-Level Security; every turn is governed by a closed specialist catalog, an MCP gateway with an allow-list, a quota and read-only tools, and agents make no operational writes. Below, four failures of the in-process design, each mapped to its fix: commit after every step, UNIQUE (run_id, seq) with attempt fencing, a circuit breaker in the commit, and a blackboard in PostgreSQL under RLS.

## Changing the image

1. Edit `docs/diagrams/linkedin-multi-agent-state.gen.py` and run it from the repository root: it rewrites the `.drawio` and an HTML page with the same layout.
2. Export the PNG with a 2x screenshot of that HTML page (Chromium, viewport 1600 × 1420, `deviceScaleFactor: 2`), or open the `.drawio` in [app.diagrams.net](https://app.diagrams.net) and use **File → Export as → PNG**, zoom 200 %.
