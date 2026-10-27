"""Generates docs/diagrams/linkedin-architecture-azure.drawio: the Azure counterpart of the AWS LinkedIn diagram.

Same page, same grid, same typography, line styles and legend as linkedin-architecture.drawio; the AWS service
icons are replaced by the official Azure icons that draw.io ships (img/lib/azure2). Edit the layout here, not in
the .drawio, then export with:

  # copy the .drawio outside OneDrive first (the container hangs on synced folders), then:
  docker run --rm -v "$PWD:/data" rlespinasse/drawio-export -f png --width 4706 -o png --remove-page-suffix linkedin-architecture-azure.drawio
  docker run --rm -v "$PWD:/data" rlespinasse/drawio-export -f svg --embed-svg-images -o svg --remove-page-suffix linkedin-architecture-azure.drawio
  (--scale hangs in the headless exporter; --width gives the same 2x. Copy both files to docs/images/.)

Every service drawn is one the Terraform module infra/terraform/azure/modules/secondchance creates.
"""

from pathlib import Path
from xml.sax.saxutils import escape

FONT = "fontFamily=Helvetica;"
GRAY = "<font style='font-size:13px' color='#4B5563'>{}</font>"
cells: list[str] = []  # groups and text
edges: list[str] = []  # drawn above the groups, below the icons
icons: list[str] = []


def q(text: str) -> str:
    return escape(text, {'"': "&quot;"})


def label(title: str, sub: str = "") -> str:
    return f"<b>{title}</b>" + (f"<br>{GRAY.format(sub)}" if sub else "")


def group(cid, title, x, y, w, h, stroke, fill="none", font=None, dashed=True, align="left", width=2, icon=None, bottom=False):
    style = (
        f"fontSize=17;fontStyle=1;{FONT}html=1;whiteSpace=wrap;verticalAlign={'bottom' if bottom else 'top'};spacingBottom={10 if bottom else 6};align={align};"
        "container=0;pointerEvents=0;collapsible=0;rounded=1;arcSize=4;"
        f"strokeColor={stroke};fillColor={fill};strokeWidth={width};spacingLeft={34 if icon else 14};spacingRight=14;spacingTop=6;"
        f"fontColor={font or stroke};" + ("dashed=1;dashPattern=6 4;" if dashed else "dashed=0;")
    )
    cells.append(f'<mxCell id="{cid}" value="{q(title)}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
    if icon:
        icon_cell(f"{cid}_i", icon, x + 8, y + (h - 33 if bottom else 7), 26)


def icon_cell(cid, path, x, y, size, value="", right=False, font=15, extra=""):
    pos = ("labelPosition=right;verticalLabelPosition=middle;align=left;verticalAlign=middle;spacingLeft=4;" if right
           else "verticalLabelPosition=bottom;verticalAlign=top;align=center;")
    style = (f"image;aspect=fixed;html=1;points=[];sketch=0;outlineConnect=0;fontColor=#16191F;{pos}"
             f"fontSize={font};{FONT}image=img/lib/azure2/{path};{extra}")
    icons.append(f'<mxCell id="{cid}" value="{q(value)}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{size}" height="{size}" as="geometry"/></mxCell>')


def svc(cid, path, x, y, title, sub="", size=64, right=False, font=15):
    icon_cell(cid, path, x, y, size, label(title, sub), right=right, font=font)


def badge(cid, path, x, y):
    """The small 'managed identity' sticker that the AWS diagram uses for KMS."""
    icon_cell(cid, path, x, y, 26)


def text(cid, value, x, y, w, h, size, color, bold):
    style = f"text;html=1;whiteSpace=wrap;fontSize={size};{FONT}fontColor={color};align=left;verticalAlign=middle;fontStyle={1 if bold else 0};"
    cells.append(f'<mxCell id="{cid}" value="{q(value)}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')


def edge(cid, source, target, value="", dashed=False, extra="", points=(), out=None, into=None):
    """out / into are (x, y) fractions of the source / target icon where the line leaves / arrives."""
    if out:
        extra += f"exitX={out[0]};exitY={out[1]};exitDx=0;exitDy=0;"
    if into:
        extra += f"entryX={into[0]};entryY={into[1]};entryDx=0;entryDy=0;"
    style = (f"edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;strokeColor=#545B64;strokeWidth=2;fontSize=14;{FONT}"
             "fontColor=#16191F;labelBackgroundColor=#FFFFFF;endArrow=block;endFill=1;"
             + ("dashed=1;dashPattern=8 6;" if dashed else "") + extra)
    pts = "".join(f'<mxPoint x="{x}" y="{y}"/>' for x, y in points)
    geometry = f'<Array as="points">{pts}</Array>' if points else ""
    edges.append(f'<mxCell id="{cid}" value="{q(value)}" style="{style}" edge="1" parent="1" source="{source}" target="{target}">'
                 f'<mxGeometry relative="1" as="geometry">{geometry}</mxGeometry></mxCell>')


# ------------------------------------------------------------------------------------------------ title, legend
text("title", "SecondChance on Azure", 40, 24, 1200, 50, 40, "#16191F", True)
text("subtitle", "Containers that scale to zero · multi-tenant · EU-only · AI proposes, people decide", 40, 74, 1400, 36, 22, "#4B5563", False)

cells.append('<mxCell id="lg0a" value="" style="text;" vertex="1" parent="1"><mxGeometry x="1460" y="52" width="1" height="1" as="geometry"/></mxCell>')
cells.append('<mxCell id="lg0b" value="" style="text;" vertex="1" parent="1"><mxGeometry x="1520" y="52" width="1" height="1" as="geometry"/></mxCell>')
cells.append('<mxCell id="lg1a" value="" style="text;" vertex="1" parent="1"><mxGeometry x="1760" y="52" width="1" height="1" as="geometry"/></mxCell>')
cells.append('<mxCell id="lg1b" value="" style="text;" vertex="1" parent="1"><mxGeometry x="1820" y="52" width="1" height="1" as="geometry"/></mxCell>')
edge("e_lg0", "lg0a", "lg0b")
edge("e_lg1", "lg1a", "lg1b", dashed=True)
text("lg0t", "synchronous call", 1535, 38, 220, 28, 14, "#16191F", False)
text("lg1t", "asynchronous", 1835, 38, 220, 28, 14, "#16191F", False)
cells.append('<mxCell id="lg2" value="" style="rounded=1;arcSize=12;fillColor=#FFF8F0;strokeColor=#D83B01;strokeWidth=2;dashed=1;dashPattern=6 4;" vertex="1" parent="1">'
             '<mxGeometry x="1460" y="88" width="60" height="30" as="geometry"/></mxCell>')
text("lg2t", "governed or isolated", 1535, 88, 260, 30, 14, "#16191F", False)
icon_cell("lg3", "identity/Managed_Identities.svg", 1762, 88, 30)
text("lg3t", "managed identity · no secret", 1835, 88, 320, 30, 14, "#16191F", False)

# ------------------------------------------------------------------------------------------------ groups
group("g_edge", "Edge · global", 190, 150, 260, 880, "#9CA3AF", font="#9CA3AF")
group("g_region", "Azure region Germany West Central (Frankfurt)", 490, 150, 1900, 920, "#0078D4", font="#0078D4", align="right")
group("g_out", "Notifier · no data access", 520, 650, 430, 390, "#D83B01", fill="#FFF8F0")
group("g_vnet", "Virtual network 10.50.0.0/16 · private endpoints · no public data plane", 990, 170, 900, 880,
      "#5E9624", width=2, dashed=False, align="right", font="#3B7A0A", icon="networking/Virtual_Networks.svg", bottom=True)
group("g_env", "Container Apps environment · KEDA scale to zero", 1010, 270, 860, 520, "#50A0E0", fill="#EAF4FB", dashed=False,
      font="#0F6CBD", icon="other/Container_App_Environments.svg", bottom=True)
group("g_agent", "Governed agent path · AI proposes, people decide", 1030, 410, 830, 190, "#D83B01", fill="#FFF8F0")
group("g_pg", "PostgreSQL flexible server · Entra auth only · Row-Level Security · pgvector · PostGIS", 1030, 810, 740, 200,
      "#8764B8", fill="#FFFFFF", font="#5C2D91", bottom=True)
group("g_sec", "Security", 40, 1110, 1440, 210, "#D13438", fill="#FFFFFF", dashed=False)
group("g_obs", "Observability", 1510, 1110, 880, 210, "#8764B8", fill="#FFFFFF", dashed=False)

# ------------------------------------------------------------------------------------------------ edge and identity
icon_cell("browser", "general/Browser.svg", 60, 520, 64, label("Browser", "React SPA"))
svc("waf", "networking/Web_Application_Firewall_Policies_WAF.svg", 288, 230, "Front Door WAF", "rate limit · managed rules")
svc("fd", "networking/Front_Doors.svg", 288, 520, "Azure Front Door", "one origin for app and API")
svc("web", "other/Worker_Container_App.svg", 288, 820, "web container", "nginx · static SPA")
svc("entra", "identity/Azure_Active_Directory.svg", 600, 190, "Microsoft Entra ID", "OIDC + PKCE · app roles")
svc("ps", "integration/Azure_PubSub.svg", 780, 190, "Web PubSub", "run groups · URL minted by API")

# ------------------------------------------------------------------------------------------------ container apps
svc("jobs", "other/Worker_Container_App.svg", 1040, 300, "jobs", "PDF ingest · matching", right=True)
svc("api", "other/Worker_Container_App.svg", 1500, 300, "api", "FastAPI · JWT in the API", right=True)
svc("agents", "other/Worker_Container_App.svg", 1090, 460, "agents", "one bounded turn")
svc("mcp", "other/Worker_Container_App.svg", 1360, 460, "mcp-gateway", "allow-list · quota · audit")
svc("tool", "other/Worker_Container_App.svg", 1640, 460, "tool-executor", "read-only · user's RLS")
svc("maint", "other/Worker_Container_App.svg", 1030, 650, "retention · requeue", "cron jobs", right=True)
icon_cell("mi", "identity/Managed_Identities.svg", 1440, 650, 64, label("Managed identity", "Entra token · no password"), right=False,
          extra="labelPosition=left;verticalLabelPosition=middle;align=right;verticalAlign=middle;spacingRight=4;")
svc("mig", "other/Worker_Container_App.svg", 1700, 650, "migrate · bootstrap", "deploy only")
svc("primary", "databases/Azure_Database_PostgreSQL_Server.svg", 1440, 850, "primary", "")
svc("standby", "databases/Azure_Database_PostgreSQL_Server.svg", 1680, 850, "standby (pilot)", "zone-redundant")
svc("pe", "networking/Private_Endpoint.svg", 1800, 815, "Private endpoints", "private DNS", size=48)

# ------------------------------------------------------------------------------------------------ notifier box
svc("notif", "other/Worker_Container_App.svg", 600, 720, "notifier", "no data access")
svc("acs", "other/Azure_Communication_Services.svg", 840, 720, "Communication Services", "mission e-mail")
svc("graph", "identity/Azure_Active_Directory.svg", 720, 880, "Microsoft Graph", "address by object id", size=56)

# ------------------------------------------------------------------------------------------------ managed services (right column)
svc("sb", "general/Service_Bus.svg", 2110, 190, "Service Bus", "jobs · notify · agents · dead letters")
svc("oai", "ai_machine_learning/Azure_OpenAI.svg", 2110, 345, "Azure OpenAI", "chat · embeddings · EU data zone")
svc("cs", "ai_machine_learning/Content_Safety.svg", 2110, 490, "AI Content Safety", "Prompt Shields · harm")
svc("blob", "storage/Storage_Accounts.svg", 2110, 635, "Blob Storage", "tenant documents · malware-scanned")
svc("table", "general/Table.svg", 2110, 800, "Table Storage", "MCP rate limits")
for badge_id, (x, y) in {"b_sb": (2160, 240), "b_oai": (2160, 395), "b_cs": (2160, 540), "b_blob": (2160, 685), "b_table": (2160, 850)}.items():
    badge(badge_id, "identity/Managed_Identities.svg", x, y)
badge("b_def", "security/Azure_Defender.svg", 2084, 635)

# ------------------------------------------------------------------------------------------------ security and observability
security = [
    ("Managed identities", "no keys · no secrets", "identity/Managed_Identities.svg"),
    ("Entra ID", "app roles · PKCE", "identity/Azure_Active_Directory.svg"),
    ("Row-Level Security", "per tenant", "databases/Azure_Database_PostgreSQL_Server.svg"),
    ("AI Content Safety", "prompt attack · harm", "ai_machine_learning/Content_Safety.svg"),
    ("Front Door WAF", "edge filtering", "networking/Web_Application_Firewall_Policies_WAF.svg"),
    ("Defender for Storage", "malware scan", "security/Azure_Defender.svg"),
    ("Private Link", "no public data plane", "networking/Private_Link.svg"),
    ("Container Registry", "pull-only identity", "containers/Container_Registries.svg"),
    ("GitHub OIDC", "no stored secrets", "other/Entra_Identity.svg"),
    ("Resource locks", "one group per env", "general/Resource_Groups.svg"),
]
for i, (title, sub, path) in enumerate(security):
    svc(f"s{i}", path, 90 + 128 * i, 1160, title, sub, size=56, font=13)
icons.append('<mxCell id="eu" value="' + q("<b><font color='#FFCC00' style='font-size:18px'>★</font><br>EU</b>") +
             '" style="rounded=1;arcSize=12;fillColor=#003399;strokeColor=none;fontColor=#FFFFFF;fontSize=16;html=1;fontFamily=Helvetica;" vertex="1" parent="1">'
             '<mxGeometry x="1370" y="1160" width="56" height="56" as="geometry"/></mxCell>')
text("eu_t", "<b>EU-only</b><br>" + GRAY.format("data and inference"), 1338, 1218, 120, 44, 13, "#16191F", False)

observability = [
    ("o_logs", "Log Analytics", "30 days · no PII", "management_governance/Log_Analytics_Workspaces.svg"),
    ("o_alarm", "Azure Monitor alerts", "errors · DLQ · restarts", "management_governance/Alerts.svg"),
    ("o_ag", "Action group", "e-mail to operators", "management_governance/Monitor.svg"),
    ("o_budget", "Cost budget", "monthly alert", "general/Cost_Management_and_Billing.svg"),
    ("o_ai", "Application Insights", "traces · Entra-only", "devops/Application_Insights.svg"),
]
for i, (cid, title, sub, path) in enumerate(observability):
    svc(cid, path, 1560 + 170 * i, 1160, title, sub, size=56, font=13)

# ------------------------------------------------------------------------------------------------ flows
# Browser: two lines leave from the top, sharing the corridor at y=132 above the region
edge("e0", "browser", "fd", "HTTPS")
edge("e1", "browser", "entra", "sign-in", out=(0.5, 0), into=(0.5, 0), points=[(92, 132), (632, 132)])
edge("e2", "browser", "ps", "wss", out=(0.8, 0), into=(0.5, 0), points=[(111, 132), (812, 132)])
edge("e3", "fd", "waf", "", out=(0.5, 0), into=(0.5, 1))
edge("e4", "fd", "web", "/", out=(0.5, 1), into=(0.5, 0))
# /api/* travels the corridor at y=388, below the first row of containers
edge("e5", "fd", "api", "/api/*", out=(1, 0.75), into=(0, 0.5), points=[(470, 552), (470, 388), (1470, 388), (1470, 332)])
# api: one line up to the corridor at y=222, then left to Web PubSub and right to Service Bus
edge("e6", "api", "ps", "push", dashed=True, out=(0.5, 0), into=(1, 0.5), points=[(1532, 222)])
edge("e7", "api", "sb", "enqueue", dashed=True, out=(0.5, 0), into=(0, 0.5), points=[(1532, 222)])
edge("e8", "sb", "jobs", "jobs", dashed=True, out=(0, 0.25), into=(0.5, 0), points=[(1072, 206)])
edge("e9", "sb", "agents", "agents queue · KEDA", dashed=True, out=(0, 0.75), into=(0, 0.5), points=[(1020, 238), (1020, 492)])
edge("e10", "agents", "mcp")
edge("e11", "mcp", "tool")
# identities reach the database through one Entra token, never a password
edge("e12", "api", "mi", "", out=(0.5, 1), into=(0.5, 0), points=[(1532, 625), (1472, 625)])
edge("e13", "tool", "mi", "", out=(1, 0.5), into=(0.5, 0), points=[(1845, 492), (1845, 625), (1472, 625)])
edge("e14", "mig", "mi", "", out=(0, 0.5), into=(1, 0.5))
edge("e15", "mi", "primary", "", out=(0.5, 1), into=(0.5, 0))
edge("e16", "primary", "standby", "replica", dashed=True, out=(1, 0.5), into=(0, 0.5))
# notifications: Service Bus, round the bottom of the region, to the notifier
edge("e17", "sb", "notif", "notify", dashed=True, out=(1, 0.5), into=(0, 0.5), points=[(2330, 222), (2330, 1060), (560, 1060), (560, 752)])
edge("e18", "notif", "acs", "SendEmail")
edge("e19", "notif", "graph", "", out=(0.5, 1), into=(0.5, 0))
# private endpoints to the services that hold data
for i, (cid, target, y) in enumerate([("e20", "oai", 377), ("e21", "cs", 522), ("e22", "blob", 667), ("e23", "table", 832)]):
    edge(cid, "pe", target, "", out=(1, 0.5), into=(0, 0.5), points=[(2040, 839), (2040, y)])
edge("e24", "o_alarm", "o_ag")
edge("e25", "o_budget", "o_ag")

page = (
    '<mxfile host="generator"><diagram id="secondchance-azure" name="SecondChance on Azure">'
    '<mxGraphModel dx="2400" dy="1350" grid="0" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" '
    'pageScale="1" pageWidth="2460" pageHeight="1360" background="#FFFFFF" math="0" shadow="0" defaultFontFamily="Helvetica">'
    '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' + "".join(cells + edges + icons) + "</root></mxGraphModel></diagram></mxfile>"
)
target = Path(__file__).parent / "linkedin-architecture-azure.drawio"
target.write_text(page, encoding="utf-8")
print(f"{target} ({len(cells) + len(edges) + len(icons)} cells)")
