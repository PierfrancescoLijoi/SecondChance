# LinkedIn draft · Multi-agent systems: where does the loop keep its state?

Second SecondChance post, after [SecondChance on AWS](linkedin-architecture.md). Structure: hook, problem, solution, how it works, then the image. Written in a plain first-person voice.

![Where a multi-agent loop keeps its state](images/linkedin-multi-agent-state.png)

Image to post: [`images/linkedin-multi-agent-state.png`](images/linkedin-multi-agent-state.png) (3200 × 2840). Editable source: [`diagrams/linkedin-multi-agent-state.drawio`](diagrams/linkedin-multi-agent-state.drawio), generated with the PNG layout by [`diagrams/linkedin-multi-agent-state.gen.py`](diagrams/linkedin-multi-agent-state.gen.py).

---

## Post

Minute 14 of a multi-agent run. 🕑
The supervisor has its plan, three specialists have reported back.
Then the process dies. 💥

What's left?

If the loop lived inside that process, nothing.

A lot of multi-agent prototypes work like this: the supervisor runs in one process and keeps the plan, the history and every finding in memory. It's fine on a laptop. In production it breaks in four ways:

⏱️ A timeout or a restart (Lambda stops at 15 minutes, pods get evicted) throws away the run and everything it learned.
🔁 A retry runs a tool call that already ran.
♾️ Nobody stops a model that keeps looping.
🧠 Memory in RAM has no tenant boundary and no audit trail, and it ties each run to one machine.

For SecondChance, the source-available food-rescue platform I'm building, I went the other way: no process keeps any state. 💡
The agent is a function. The run is a state machine. The database is the memory.

Here's what that looks like in practice 👇

🗂️ Every run is a state machine in PostgreSQL. agent_run holds the status and the budgets (by default 12 steps, 60k tokens, 10 minutes). agent_step has one row per turn, UNIQUE (run_id, seq), with an attempt counter and a lease.

⚙️ Each step is stateless. It claims the step (lease, attempt + 1, budget check), runs one turn of one agent, then commits in a short transaction that only the claiming attempt can write. If a worker lost its lease, its result is thrown away.

🔄 The loop sits outside the agents. AWS Step Functions calls one step at a time and only continues when the committed outcome says so. Code and budgets end a run, not whatever the model writes.

🔒 The blackboard the agents share is a table under Row-Level Security: scoped to tenant and run, with the source agent on every row and a 7-day expiry.

🛡️ The supervisor can only plan with specialists from a closed catalog, and the server checks the plan. Tools go through an MCP gateway (allow-list, quota) and they're read-only. Agents don't write operational data. They return a recommendation, and a person decides.

One thing I want to be upfront about ⚠️: this gives you exactly-once commits, not exactly-once execution. After a crash a turn can run again, but only one result ever gets committed. That's the reason the tools are read-only.

It isn't free either 💸. You pay with more database round trips, and you give up any state hidden inside a framework. For a single-turn assistant I wouldn't bother. For agents that run for minutes, touch real data or serve more than one tenant, it's the first thing I'd decide.

The image below puts both designs side by side, with each failure mapped to its fix. 👇

Code, ADRs and tests: https://github.com/PierfrancescoLijoi/SecondChance

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
