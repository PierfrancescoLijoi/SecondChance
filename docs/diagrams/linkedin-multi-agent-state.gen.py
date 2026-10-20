"""Generates the "where does the multi-agent loop keep its state?" diagram.

Run from the repository root: python docs/diagrams/linkedin-multi-agent-state.gen.py
Writes linkedin-multi-agent-state.drawio next to this file and an HTML page with the same layout (path as the
first argument, default next to this file). Every edge is a straight line with fixed attachment points, so
draw.io draws what the PNG shows. docs/images/linkedin-multi-agent-state.png is a 2x screenshot of that page
(1600 x 1420 viewport, deviceScaleFactor 2).
The diagram mirrors api/secondchance/agents/runtime.py and migration 0002 (agent_run, agent_step, agent_memory).
"""

import sys
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).parent
DRAWIO = HERE / "linkedin-multi-agent-state.drawio"
W, H = 1600, 1420
FONT = "Helvetica, Arial, sans-serif"
INK, MUTED, EDGE = "#16191F", "#545B64", "#545B64"
RED, RED_BG = "#C7253E", "#FDF1F3"
GREEN, GREEN_BG = "#5A8A0F", "#F5FAEC"
ORANGE, ORANGE_BG = "#D45F00", "#FFF3E6"
PINK, PINK_BG = "#C2125F", "#FDEBF4"
BLUE, BLUE_BG = "#2F3BB0", "#E8F0FE"
TEAL, TEAL_BG = "#00806B", "#E3F8F4"


@dataclass
class Node:
    id: str
    label: str
    x: int
    y: int
    w: int
    h: int
    stroke: str = "none"
    fill: str = "none"
    size: int = 17
    color: str = INK
    bold: bool = False
    align: str = "center"
    valign: str = "middle"
    dashed: bool = False
    rounded: bool = True


@dataclass
class Edge:
    src: Node
    dst: Node
    direction: str  # down, up, right
    at: int  # x for vertical edges, y for horizontal ones
    label: str = ""
    color: str = EDGE
    dashed: bool = False

    def points(self):
        s, d = self.src, self.dst
        if self.direction == "down":
            return (self.at, s.y + s.h), (self.at, d.y)
        if self.direction == "up":
            return (self.at, s.y), (self.at, d.y + d.h)
        return (s.x + s.w, self.at), (d.x, self.at)

    def constraints(self):
        s, d = self.src, self.dst
        if self.direction in ("down", "up"):
            top, bottom = (1, 0) if self.direction == "down" else (0, 1)
            return f"exitX={(self.at - s.x) / s.w:.4f};exitY={top};entryX={(self.at - d.x) / d.w:.4f};entryY={bottom};"
        return f"exitX=1;exitY={(self.at - s.y) / s.h:.4f};entryX=0;entryY={(self.at - d.y) / d.h:.4f};"


nodes: list[Node] = []
edges: list[Edge] = []


def node(*args, **kwargs) -> Node:
    n = Node(*args, **kwargs)
    nodes.append(n)
    return n


def group(id_, label, x, y, w, h, stroke, fill, valign="top", size=19, dashed=True):
    return node(id_, label, x, y, w, h, stroke, fill, size, stroke, True, "left", valign, dashed)


def text(id_, label, x, y, w, h, size=17, color=INK, align="center", bold=False):
    return node(id_, label, x, y, w, h, size=size, color=color, align=align, bold=bold)


def edge(*args, **kwargs):
    edges.append(Edge(*args, **kwargs))


# ---- Title ---------------------------------------------------------------------------------------
text("title", "Multi-agent systems: where does the loop keep its state?", 40, 26, 1520, 46, 34, align="left", bold=True)
text("subtitle", "Same supervisor, same specialists. One design survives a crash, a retry and a runaway model.",
     40, 76, 1520, 30, 19, MUTED, "left")

# ---- Problem -------------------------------------------------------------------------------------
group("p", "✗  PROBLEM · the loop lives inside one process", 40, 130, 620, 830, RED, RED_BG)
sup = group("sup", "Supervisor process · long-running", 80, 200, 540, 200, ORANGE, ORANGE_BG, size=18, dashed=False)
chips = [node(f"ram{i}", label, 105 + 170 * i, 255, 150, 64, ORANGE, "#FFFFFF", 17)
         for i, label in enumerate(("plan", "history", "findings"))]
text("ram_note", "<i>all state lives only in this process's RAM</i>", 100, 340, 500, 40, 17, ORANGE)
specs = [node(f"spec{i}", f"specialist {c}", 105 + 170 * i, 500, 150, 64, ORANGE, ORANGE_BG, 17)
         for i, c in enumerate("ABC")]
tools = node("tools", "<b>tools and direct writes</b><br><i>reserve · notify · update</i>", 105, 660, 490, 76, RED,
             "#FFFFFF", 17)
for i, spec in enumerate(specs):
    x = 180 + 170 * i
    edge(sup, spec, "down", x, "in-process call" if i == 1 else "")
    edge(spec, tools, "down", x, "no guard" if i == 1 else "", RED, True)
text("p_note", "<b>Works on a laptop.</b><br>In production it breaks in four ways ↓", 80, 800, 540, 90, 22, RED)

# ---- Solution ------------------------------------------------------------------------------------
group("s", "✓  SOLUTION · stateless steps, durable state", 700, 130, 860, 830, GREEN, GREEN_BG)
sfn = node("sfn", "<b>AWS Step Functions</b> · owns the loop<br>"
           "<i>runs one step, continues only if the committed outcome says so</i>",
           740, 195, 780, 84, PINK, PINK_BG, 17)
lam = group("lam", "agent-step Lambda · stateless, any instance", 740, 350, 780, 180, ORANGE, "#FFFFFF",
            valign="bottom", size=17, dashed=False)
phase_labels = ("<b>① claim</b><br>lease · attempt + 1<br>budget check",
                "<b>② execute</b><br>one supervisor or<br>specialist turn",
                "<b>③ complete</b><br>fenced by attempt<br>commit · next seq")
phases = [node(f"ph{i}", label, 765 + 260 * i, 370, 220, 100, ORANGE, ORANGE_BG, 17) for i, label in enumerate(phase_labels)]
edge(sfn, phases[0], "down", 875, "invoke (run_id, seq)")
edge(phases[2], sfn, "up", 1395, "committed outcome")
edge(phases[0], phases[1], "right", 420)
edge(phases[1], phases[2], "right", 420)

db = group("db", "Aurora PostgreSQL · Row-Level Security · source of truth", 740, 590, 780, 230, BLUE, "#FFFFFF",
           valign="bottom", size=17, dashed=False)
table_labels = ("<b>agent_run</b><hr>status · version<br>max 12 steps<br>max 60k tokens<br>deadline 10 min",
                "<b>agent_step</b><hr>UNIQUE (run_id, seq)<br>attempt (fencing)<br>lease_until<br>model · tokens",
                "<b>agent_memory</b><hr>scope = run<br>(the blackboard)<br>source agent<br>expires_at")
for i, label in enumerate(table_labels):
    node(f"t{i}", label, 765 + 260 * i, 608, 220, 170, BLUE, BLUE_BG, 16, align="left", valign="top")
edge(lam, db, "down", 1135, "short transaction · SET LOCAL tenant")

gov_labels = ("<b>closed catalog</b><br>supervisor picks specialists",
              "<b>MCP gateway</b><br>read-only tools · audit",
              "<b>pending proposal</b><br>a person approves")
text("gov_title", "every turn is governed", 765, 826, 740, 30, 17, TEAL, "left", True)
gov = [node(f"g{i}", label, 765 + 260 * i, 860, 220, 72, TEAL, TEAL_BG, 16) for i, label in enumerate(gov_labels)]
edge(gov[0], gov[1], "right", 896)
edge(gov[1], gov[2], "right", 896)

# ---- Failure → fix -------------------------------------------------------------------------------
text("h_left", "What breaks when state lives in one process", 40, 995, 740, 40, 21, RED, "left", True)
text("h_right", "How the durable model prevents it", 840, 995, 720, 40, 21, GREEN, "left", True)
rows = (
    ("<b>1 · Crash or timeout</b> (Lambda 15 min, pod eviction): the run and everything it learned are lost.",
     "<b>1 · Commit after every step</b>: any instance resumes the run from the last committed seq."),
    ("<b>2 · Retry</b> after a timeout: the same tool call runs twice, e.g. a double reservation.",
     "<b>2 · UNIQUE (run_id, seq) + attempt fencing</b>: a duplicate is a no-op, a late result is dropped."),
    ("<b>3 · No budget</b>: a looping model keeps calling itself; tokens and cost are unbounded.",
     "<b>3 · Circuit breaker in the commit</b>: 12 steps · 60k tokens · 10 min, before the next step exists."),
    ("<b>4 · Memory in RAM</b>: no tenant boundary, no audit trail, sticky sessions.",
     "<b>4 · Blackboard in PostgreSQL under RLS</b>: per tenant and run, with provenance, expiry and audit."),
)
for i, (bad, good) in enumerate(rows):
    y = 1045 + 88 * i
    left = node(f"bad{i}", bad, 40, y, 740, 74, RED, RED_BG, 17, align="left")
    right = node(f"good{i}", good, 840, y, 720, 74, GREEN, GREEN_BG, 17, align="left")
    edge(left, right, "right", y + 37)


# ---- draw.io -------------------------------------------------------------------------------------
def attr(value: str) -> str:
    return escape(value, {'"': "&quot;"})


def drawio() -> str:
    cells = []
    for n in nodes:
        box = (f"rounded={int(n.rounded)};arcSize=6;strokeColor={n.stroke};fillColor={n.fill};strokeWidth=2;"
               if n.stroke != "none" else "text;strokeColor=none;fillColor=none;")
        style = (f"{box}html=1;whiteSpace=wrap;fontFamily=Helvetica;fontSize={n.size};fontColor={n.color};"
                 f"fontStyle={int(n.bold)};align={n.align};verticalAlign={n.valign};spacing=10;"
                 f"{'dashed=1;dashPattern=8 5;' if n.dashed else ''}")
        cells.append(f'<mxCell id="{n.id}" value="{attr(n.label)}" style="{style}" vertex="1" parent="1">'
                     f'<mxGeometry x="{n.x}" y="{n.y}" width="{n.w}" height="{n.h}" as="geometry"/></mxCell>')
    for i, e in enumerate(edges):
        style = (f"edgeStyle=none;html=1;strokeColor={e.color};strokeWidth=2.5;endArrow=block;endFill=1;"
                 f"fontFamily=Helvetica;fontSize=15;fontColor={INK};labelBackgroundColor=#FFFFFF;"
                 f"{'dashed=1;dashPattern=8 5;' if e.dashed else ''}{e.constraints()}")
        cells.append(f'<mxCell id="e{i}" value="{attr(e.label)}" style="{style}" edge="1" parent="1" '
                     f'source="{e.src.id}" target="{e.dst.id}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    return ('<mxfile host="generator"><diagram id="multi-agent-state" name="Multi-agent state">'
            f'<mxGraphModel dx="{W}" dy="{H}" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
            f'fold="1" page="1" pageScale="1" pageWidth="{W}" pageHeight="{H}" background="#FFFFFF" math="0" '
            'shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
            + "".join(cells) + "</root></mxGraphModel></diagram></mxfile>\n")


# ---- HTML (same layout, for the PNG export) ------------------------------------------------------
def html() -> str:
    flex = {"top": "flex-start", "middle": "center", "bottom": "flex-end"}
    divs = []
    for n in nodes:
        border = f"border:2px {'dashed' if n.dashed else 'solid'} {n.stroke};" if n.stroke != "none" else ""
        bg = n.fill if n.fill != "none" else "transparent"
        divs.append(
            f'<div style="position:absolute;left:{n.x}px;top:{n.y}px;width:{n.w}px;height:{n.h}px;box-sizing:border-box;'
            f'{border}background:{bg};border-radius:{8 if n.rounded else 0}px;padding:8px 12px;display:flex;'
            f'align-items:{flex[n.valign]};justify-content:{"flex-start" if n.align == "left" else "center"};'
            f'text-align:{n.align};font-size:{n.size}px;line-height:1.3;color:{n.color};'
            f'font-weight:{700 if n.bold else 400}"><div>{n.label}</div></div>')
    lines, labels = [], []
    colors = sorted({e.color for e in edges})
    markers = "".join(f'<marker id="m{i}" markerWidth="12" markerHeight="12" refX="10" refY="6" orient="auto" '
                      f'markerUnits="userSpaceOnUse"><path d="M0,0 L12,6 L0,12 z" fill="{c}"/></marker>'
                      for i, c in enumerate(colors))
    for e in edges:
        (x1, y1), (x2, y2) = e.points()
        dash = ' stroke-dasharray="8 5"' if e.dashed else ""
        lines.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{e.color}" stroke-width="2.5"{dash} '
                     f'marker-end="url(#m{colors.index(e.color)})"/>')
        if e.label:
            labels.append(f'<div style="position:absolute;left:{(x1 + x2) / 2}px;top:{(y1 + y2) / 2}px;'
                          f'transform:translate(-50%,-50%);background:#FFFFFF;padding:1px 6px;font-size:15px;'
                          f'color:{INK};white-space:nowrap">{e.label}</div>')
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>body{{margin:0;background:#fff;font-family:{FONT}}}'
            f'hr{{border:0;border-top:1px solid currentColor;opacity:.35;margin:4px 0}}</style></head><body>'
            f'<div style="position:relative;width:{W}px;height:{H}px;background:#fff">{"".join(divs)}'
            f'<svg width="{W}" height="{H}" style="position:absolute;left:0;top:0"><defs>{markers}</defs>'
            f'{"".join(lines)}</svg>{"".join(labels)}</div></body></html>')


DRAWIO.write_text(drawio(), encoding="utf-8")
html_path = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "linkedin-multi-agent-state.html"
html_path.write_text(html(), encoding="utf-8")
print(f"wrote {DRAWIO} and {html_path} ({len(nodes)} nodes, {len(edges)} edges)")
