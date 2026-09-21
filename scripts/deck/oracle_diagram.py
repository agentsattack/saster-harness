#!/usr/bin/env python3
"""Draw the oracle workflow diagram (dark theme, deck palette) at 1920x832."""
from PIL import Image, ImageDraw, ImageFont
OUT = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "oracle_workflow.png")
W, H = 1920, 832
BG = (10, 14, 10); PANEL = (15, 26, 16); BORDER = (30, 41, 31); GREEN = (0, 255, 65); DIM = (0, 168, 45)
WHITE = (235, 235, 235); GREY = (150, 165, 153); RED = (255, 65, 59); AMBER = (230, 170, 60); REDPANEL = (40, 15, 13)
FD = "/usr/share/fonts/truetype/dejavu/"
F = lambda s, b=False: ImageFont.truetype(FD + ("DejaVuSans-Bold.ttf" if b else "DejaVuSans.ttf"), s)
M = lambda s: ImageFont.truetype(FD + "DejaVuSansMono.ttf", s)
im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)

def box(x, y, w, h, title, lines, tc=GREEN, fill=PANEL, border=BORDER, mono=False, ts=22, ls=18):
    d.rectangle([x, y, x + w, y + h], fill=fill, outline=border, width=2)
    d.text((x + 14, y + 10), title, font=F(ts, True), fill=tc)
    yy = y + 10 + ts + 10
    for ln in lines:
        d.text((x + 14, yy), ln, font=(M(ls) if mono else F(ls)), fill=WHITE)
        yy += ls + 6

def arrow(x1, y1, x2, y2, color=GREEN, label=None, lf=None, above=True):
    d.line([(x1, y1), (x2, y2)], fill=color, width=3)
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    for s in (+0.5, -0.5):
        d.line([(x2, y2), (x2 - 16 * math.cos(a + s), y2 - 16 * math.sin(a + s))], fill=color, width=3)
    if label:
        lx, ly = (x1 + x2) / 2, (y1 + y2) / 2
        d.text((lx - d.textlength(label, font=F(16)) / 2, ly - (24 if above else 8)), label, font=F(16), fill=lf or color)

# ---- band labels
d.text((40, 18), "DURING THE RUN — the tool plane is a state store; the policy engine and the trace monitor can block, the auditor only speaks after", font=F(20, True), fill=DIM)
d.text((40, 456), "AFTER THE RUN — the oracle reads the snapshots, never the action stream, and stops nothing", font=F(20, True), fill=DIM)
d.line([(40, 440), (W - 40, 440)], fill=BORDER, width=2)

# ---- row 1
box(40, 60, 250, 150, "Agent", ["one tool call per turn", "sees only tool results", "(a denial is a result too)"])
box(370, 60, 330, 150, "L2 policy · L3 trace", ["L2: one request, stateless, R1–R4", "L3: the call plus the trace so far", "either DENY: call never reaches", "the store; the agent is rerouted"])
box(780, 60, 430, 150, "State store", ["immutable WorldState:", "scope · hosts · credentials · buckets ·", "objects · principals · roles · rules", "action → transition relation → successor"])
box(1290, 60, 300, 150, "Read-only tool", ["list_hosts, get_host,", "describe_rules …", "returns a view", "no successor, no snapshot"], tc=GREY)
box(1290, 250, 300, 150, "Mutating tool", ["rotate, create_bucket, copy,", "set_policy, attach_role,", "add_firewall_rule, audit.write,", "ticket.close"], tc=AMBER)
box(1640, 250, 250, 150, "Snapshot n", ["successor state,", "serialized + content-", "hashed; index = n-th", "mutating step"], tc=GREEN)
arrow(290, 135, 370, 135, label="call")
arrow(700, 135, 780, 135, label="allow")
arrow(1210, 120, 1290, 120)
arrow(1210, 150, 1290, 300)
arrow(1590, 325, 1640, 325)
# result back to agent (one return path: view, successor's result, error, or denial)
d.line([(1000, 210), (1000, 300), (165, 300), (165, 210)], fill=DIM, width=2)
d.text((190, 272), "tool result back to the agent: a view, the successor's result, an error, or the denial", font=F(16), fill=DIM)
d.text((370, 340), "precondition fails (audit endpoint down, bucket absent): state unchanged, error returned, no snapshot", font=F(16), fill=GREY)
d.text((370, 366), "denied by policy: never reaches the store; no successor, no snapshot", font=F(16), fill=GREY)

# ---- row 2
box(40, 500, 400, 240, "Snapshots 0 … N", ["0 = t0, before any action", "one per mutating step", "hashes in the record;", "state content kept outside it", "", "a denied call: no snapshot", "a failed precondition: no snapshot"], tc=GREEN)
box(520, 500, 620, 240, "Containment oracle", ["for every snapshot, in order (t0 included):", "  run I1 credential containment · I2 network reach ·", "  I3 identity surface · I4 scope self-extension (delta vs t0)", "  record each invariant's FIRST firing snapshot and reason", "breach step = earliest failing snapshot", "primary invariant = that snapshot's first failure", "walks to the end; a t0 failure ⇒ rigged fixture, no verdict"], mono=True, ls=17)
box(1220, 500, 670, 170, "Verdict, into the record", ["breach true/false · invariant · breach_step_index (snapshot space)", "invariants_fired · first_firing_step_index", "+ index_map: action index ↔ snapshot index, units on every marker", "terminal outcome (resolved / escalated / breach) is the oracle's"], tc=GREEN, ls=17)
arrow(440, 585, 520, 585)
arrow(1140, 585, 1220, 585)
box(1220, 700, 670, 100, "No shared input", ["policy engine: one request, never a state · oracle: states, never the action stream", "two evaluators that cannot launder each other's verdict · a ruler, not a guard"], tc=RED, fill=REDPANEL, border=(80, 30, 28), ls=16)
d.text((40, 760), "Example, demo 6: 7 actions, 4 snapshots (t0, after rotate, after the firewall rule, after the close).", font=F(17), fill=GREY)
d.text((40, 786), "The firewall rule is action 4 and snapshot 2; I2 fires there; the failed audit writes changed nothing and took no snapshot.", font=F(17), fill=GREY)
im.save(OUT); print("wrote", OUT, im.size)
