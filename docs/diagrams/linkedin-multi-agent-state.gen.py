"""Generates linkedin-multi-agent-state.drawio: where a multi-agent loop keeps its state.

Run from the repository root: python docs/diagrams/linkedin-multi-agent-state.gen.py
The diagram mirrors api/secondchance/agents/runtime.py and migration 0002 (agent_run, agent_step, agent_memory).
"""

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).with_suffix("").with_suffix(".drawio")
FONT = "fontFamily=Helvetica;html=1;whiteSpace=wrap;"
INK, EDGE = "#16191F", "#545B64"
RED, GREEN, ORANGE, PINK, BLUE, TEAL, GREY = "#DD344C", "#7AA116", "#ED7100", "#E7157B", "#3B48CC", "#01A88D", "#4B5563"

cells: list[str] = []


def box(id_, label, x, y, w, h, stroke, fill="#FFFFFF", size=15, extra=""):
    style = f"rounded=1;arcSize=8;{FONT}fontSize={size};fontColor={INK};strokeColor={stroke};fillColor={fill};strokeWidth=2;{extra}"
    cells.append(
        f'<mxCell id="{id_}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
    )


def group(id_, label, x, y, w, h, stroke, fill="none", dashed=True, valign="top", align="left", size=17):
    dash = "dashed=1;dashPattern=6 4;" if dashed else ""
    extra = f"verticalAlign={valign};align={align};fontStyle=1;spacingLeft=14;spacingRight=14;spacingTop=6;spacingBottom=6;fontColor={stroke};{dash}"
    box(id_, label, x, y, w, h, stroke, fill, size, "arcSize=3;" + extra)


def text(id_, label, x, y, w, h, size=15, extra=""):
    style = f"text;{FONT}fontSize={size};fontColor={INK};strokeColor=none;fillColor=none;{extra}"
    cells.append(
        f'<mxCell id="{id_}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>'
    )


def badge(id_, n, x, y, color):
    style = f"ellipse;{FONT}fontSize=16;fontStyle=1;fontColor=#FFFFFF;strokeColor={color};fillColor={color};"
    cells.append(
        f'<mxCell id="{id_}" value="{n}" style="{style}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="30" height="30" as="geometry"/></mxCell>'
    )


def edge(id_, src, dst, label="", color=EDGE, dashed=False, points=(), extra=""):
    dash = "dashed=1;dashPattern=8 6;" if dashed else ""
    style = (
        f"edgeStyle=orthogonalEdgeStyle;rounded=1;{FONT}strokeColor={color};strokeWidth=2;fontSize=13;"
        f"fontColor={INK};labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;{dash}{extra}"
    )
    pts = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points)
    geometry = f'<mxGeometry relative="1" as="geometry"><Array as="points">{pts}</Array></mxGeometry>' if pts else (
        '<mxGeometry relative="1" as="geometry"/>'
    )
    cells.append(
        f'<mxCell id="{id_}" value="{escape(label, {chr(34): "&quot;"})}" style="{style}" edge="1" parent="1" '
        f'source="{src}" target="{dst}">{geometry}</mxCell>'
    )


# Title
text("title", "<b>Multi-agent systems: where does the loop keep its state?</b>", 40, 24, 1720, 44, 30, "align=left;")
text("subtitle", "Same supervisor and specialists, two answers. One survives a crash, a retry and a runaway model; one does not.",
     40, 70, 1720, 30, 17, "align=left;fontColor=#545B64;")

# ---- Problem: the loop lives inside one process -------------------------------------------------
group("p", "PROBLEM · the supervisor loop lives in one process", 40, 120, 760, 800, RED, "#FFF7F8")
box("l_user", "<b>API request</b><br><i>tenant · user · task</i>", 290, 175, 180, 56, GREY, "#F3F4F6")
group("l_sup", "Supervisor process · long-running loop", 120, 270, 520, 200, ORANGE, "#FFF3E6", dashed=False, size=15)
box("l_ram1", "plan", 145, 320, 150, 60, ORANGE)
box("l_ram2", "conversation<br>history", 305, 320, 150, 60, ORANGE)
box("l_ram3", "specialist<br>findings", 465, 320, 150, 60, ORANGE)
text("l_ram_note", "<i>all state is held in the RAM of this one process</i>", 145, 400, 470, 40, 14, "fontColor=#ED7100;")
box("l_sa", "specialist A", 145, 540, 150, 56, ORANGE, "#FFF3E6")
box("l_sb", "specialist B", 305, 540, 150, 56, ORANGE, "#FFF3E6")
box("l_sc", "specialist C", 465, 540, 150, 56, ORANGE, "#FFF3E6")
box("l_tools", "<b>tools and writes</b><br><i>reserve · notify · update</i>", 290, 660, 180, 60, RED, "#FDECEF")
edge("le1", "l_user", "l_sup")
edge("le2", "l_sup", "l_sa", extra="exitX=0.1923;exitY=1;entryX=0.5;entryY=0;")
edge("le3", "l_sup", "l_sb", "in-process call", extra="exitX=0.5;exitY=1;entryX=0.5;entryY=0;")
edge("le4", "l_sup", "l_sc", extra="exitX=0.8077;exitY=1;entryX=0.5;entryY=0;")
edge("le5", "l_sa", "l_tools", color=RED, dashed=True, extra="exitX=0.5;exitY=1;entryX=0.2;entryY=0;")
edge("le6", "l_sb", "l_tools", "direct side effects", color=RED, dashed=True, extra="exitX=0.5;exitY=1;entryX=0.5;entryY=0;")
edge("le7", "l_sc", "l_tools", color=RED, dashed=True, extra="exitX=0.5;exitY=1;entryX=0.8;entryY=0;")
badge("lb1", 1, 625, 255, RED)
badge("lb3", 3, 105, 255, RED)
badge("lb4", 4, 625, 395, RED)
badge("lb2", 2, 455, 645, RED)
notes_l = [
    "<b>1 · Crash or timeout</b> (Lambda 15 min, pod eviction): the run and everything it learned are gone.",
    "<b>2 · Retry</b> after a timeout: the same tool call runs twice, e.g. a double reservation.",
    "<b>3 · No budget</b>: a looping model keeps calling itself; tokens and cost are unbounded.",
    "<b>4 · Memory in RAM</b>: no tenant boundary, no audit trail, sticky sessions, no scale-out.",
]
for i, note in enumerate(notes_l):
    box(f"ln{i}", note, 60 + (i % 2) * 365, 760 + (i // 2) * 78, 345, 68, RED, "#FFFFFF", 14, "align=left;spacingLeft=10;")

# ---- Solution: stateless steps, durable state, external loop ---------------------------------------
group("s", "SOLUTION · stateless steps, durable state, the loop outside the agent", 840, 120, 920, 800, GREEN, "#F7FBEF")
box("r_api", "<b>API</b><br><i>start run</i>", 870, 200, 170, 56, GREY, "#F3F4F6")
group("r_sfn", "AWS Step Functions Standard · owns the loop", 1080, 150, 650, 140, PINK, "#FFFFFF", valign="bottom",
      align="right", size=14)
box("r_inv", "<b>invoke agent-step</b><br><i>(run_id, seq)</i>", 1110, 195, 190, 60, PINK, "#FDEBF4")
box("r_choice", "committed<br>outcome =<br>continue?", 1370, 180, 150, 90, PINK, "#FDEBF4", 13, "rhombus;")
box("r_end", "<b>end</b><br><i>result in DB</i>", 1580, 195, 120, 60, PINK, "#FDEBF4")
edge("re1", "r_api", "r_inv", "start")
edge("re2", "r_inv", "r_choice")
edge("re3", "r_choice", "r_end", "no")
edge("re4", "r_choice", "r_inv", "yes · seq + 1", points=((1445, 165), (1205, 165)),
     extra="exitX=0.5;exitY=0;entryX=0.5;entryY=0;")

group("r_step", "agent-step Lambda · stateless, any warm or cold instance", 870, 320, 860, 130, ORANGE, "#FFFFFF",
      dashed=False, align="right", size=15)
box("r_claim", "<b>① claim</b><br>lease 5 min · attempt + 1<br>budget check", 890, 360, 260, 76, ORANGE, "#FFF3E6", 14)
box("r_exec", "<b>② execute</b><br>one supervisor or specialist turn<br><i>no transaction held</i>", 1170, 360, 260, 76,
    ORANGE, "#FFF3E6", 14)
box("r_done", "<b>③ complete</b> (fenced by attempt)<br>record step · write memory<br>update run · insert seq + 1",
    1450, 360, 260, 76, ORANGE, "#FFF3E6", 14)
edge("re5", "r_inv", "r_step", "1 step = 1 invocation", extra="exitX=0.5;exitY=1;entryX=0.3895;entryY=0;")
edge("re6", "r_claim", "r_exec")
edge("re7", "r_exec", "r_done")

box("r_cat", "<b>specialist catalog</b><br><i>specialists.v1.json · closed list<br>plan validated by the server</i>",
    870, 490, 240, 80, TEAL, "#E3F8F4", 14)
box("r_mcp", "<b>MCP Gateway</b><br><i>schema · allow-list · quota · audit</i>", 870, 590, 240, 70, TEAL, "#E3F8F4", 14)
box("r_prop", "<b>pending proposal</b> + SHA-256<br>→ <b>human approval</b>", 870, 680, 240, 70, GREY, "#F3F4F6", 14)
edge("re8", "r_exec", "r_cat", "supervisor plans from", extra="exitX=0.25;exitY=1;entryX=0.5;entryY=0;")
edge("re9", "r_cat", "r_mcp", "tool calls · read-only")
edge("re10", "r_mcp", "r_prop", "the only write")

group("r_db", "Aurora PostgreSQL · Row-Level Security · source of truth", 1140, 490, 590, 260, BLUE, "#FFFFFF",
      valign="bottom", size=14)
table = "align=left;verticalAlign=top;spacingLeft=10;spacingTop=6;"
box("t_run", "<b>agent_run</b><hr>status · version<br>steps_used / max <b>12</b><br>tokens_used / max <b>60k</b><br>"
    "deadline_at <b>+10 min</b>", 1160, 510, 170, 200, BLUE, "#E8F0FE", 14, table)
box("t_step", "<b>agent_step</b><hr>run_id, seq <b>UNIQUE</b><br>agent · status<br>attempt <i>(fencing)</i><br>"
    "lease_until<br>model · prompt hash<br>tokens · latency", 1350, 510, 170, 200, BLUE, "#E8F0FE", 14, table)
box("t_mem", "<b>agent_memory</b><hr>scope = run<br><i>(the blackboard)</i><br>source agent<br>embedding<br>"
    "expires_at", 1540, 510, 170, 200, BLUE, "#E8F0FE", 14, table)
edge("re11", "r_done", "t_step", "short tx · SET LOCAL tenant", extra="exitX=0.25;exitY=1;entryX=0.5;entryY=0;")
badge("rb1", 1, 1715, 136, GREEN)
badge("rb2", 2, 1485, 515, GREEN)
badge("rb3", 3, 1295, 515, GREEN)
badge("rb4", 4, 1675, 515, GREEN)
notes_r = [
    "<b>1 · Committed after every step</b>: any instance resumes the run from the last seq; nothing is lost.",
    "<b>2 · UNIQUE(run_id, seq) + attempt fencing</b>: a duplicate message finds the step done; a late result is dropped.",
    "<b>3 · Circuit breaker in the commit</b>: 12 steps · 60k tokens · 10 min, checked before the next step exists.",
    "<b>4 · Blackboard in Postgres under RLS</b>: per tenant, per run, with provenance, expiry and audit.",
]
for i, note in enumerate(notes_r):
    box(f"rn{i}", note, 860 + (i % 2) * 450, 770 + (i // 2) * 72, 430, 64, GREEN, "#FFFFFF", 14,
        "align=left;spacingLeft=10;")

# ---- How to model it: two state machines ---------------------------------------------------------
group("m", "HOW TO MODEL IT · two state machines, one source of truth", 40, 945, 1720, 205, BLUE, "#FFFFFF", size=16)
text("m_run", "<b>agent_run</b>", 70, 1000, 150, 40, 16, "align=left;")
box("s_run", "running", 250, 995, 130, 44, BLUE, "#E8F0FE")
group("s_term", "", 440, 985, 860, 64, BLUE, "#F7F9FE", size=12)
for i, (name, w) in enumerate((("succeeded", 140), ("failed", 110), ("budget_exhausted", 180), ("waiting_approval", 180),
                               ("cancelled", 130))):
    x = 455 + sum((140, 110, 180, 180, 130)[:i]) + 25 * i
    box(f"s_t{i}", name, x, 997, w, 40, BLUE, "#FFFFFF", 14)
edge("me1", "s_run", "s_term", "commit decides")
text("m_note1", "Terminal state is set by the transaction that commits the step, from the outcome and the budgets, "
     "never from the model's free text.", 1320, 985, 420, 64, 14, "align=left;fontColor=#545B64;")

text("m_step", "<b>agent_step</b>", 70, 1080, 150, 40, 16, "align=left;")
box("s_pend", "pending", 250, 1078, 130, 44, BLUE, "#E8F0FE")
box("s_runn", "running<br><i>lease · attempt + 1</i>", 470, 1072, 210, 56, BLUE, "#E8F0FE", 14)
box("s_ok", "succeeded", 780, 1078, 140, 44, BLUE, "#FFFFFF")
box("s_ko", "failed", 1000, 1078, 110, 44, BLUE, "#FFFFFF")
edge("me2", "s_pend", "s_runn", "claim")
edge("me3", "s_runn", "s_ok", "complete")
edge("me4", "s_runn", "s_ko", "error", points=((575, 1140), (1055, 1140)), extra="exitX=0.5;exitY=1;entryX=0.5;entryY=1;")
edge("me5", "s_runn", "s_runn", "lease expired → re-claim", dashed=True, points=((680, 1060), (470, 1060)),
     extra="exitX=1;exitY=0.25;entryX=0;entryY=0.25;")
text("m_note2", "ON CONFLICT (run_id, seq) DO NOTHING: at-least-once delivery can never run a step twice.",
     1320, 1068, 420, 64, 14, "align=left;fontColor=#545B64;")

xml = (
    '<mxfile host="generator"><diagram id="multi-agent-state" name="Multi-agent state">'
    '<mxGraphModel dx="1800" dy="1180" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" '
    'page="1" pageScale="1" pageWidth="1800" pageHeight="1180" background="#FFFFFF" math="0" shadow="0" '
    'defaultFontFamily="Helvetica"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    + "".join(cells)
    + "</root></mxGraphModel></diagram></mxfile>\n"
)
OUT.write_text(xml, encoding="utf-8")
print(f"wrote {OUT} ({len(cells)} cells)")
