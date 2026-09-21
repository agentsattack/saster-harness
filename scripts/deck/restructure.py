#!/usr/bin/env python3
"""Restructure grrcon-deck-v3-fixed.pptx per the critique: spec before the clip, carl-ops demos grouped,
demos relabelled (opening = Demo 1, chatbot = Demo 4, no-attacker = Demo 5), slides 5+6 merged, the
predictions and uncertainty slides moved to the appendix. All edits count-checked; written atomically."""
import html, os, re, zipfile
from xml.dom import minidom

DECK = "/home/lbsuto/saster-harness/grrcon-deck-v3-fixed.pptx"
TMP = DECK + ".tmp"
def esc(s): return html.escape(s, quote=False).replace("'", "&apos;").replace('"', "&quot;")

with zipfile.ZipFile(DECK) as z:
    names = z.namelist(); parts = {n: z.read(n) for n in names}

def edit(part, pairs):
    s = parts[part].decode()
    for old, new in pairs:
        o = f"<a:t>{esc(old)}</a:t>"; n = f"<a:t>{esc(new)}</a:t>"
        if s.count(o) != 1:
            o2 = f"<a:t>{html.escape(old, quote=False)}</a:t>"
            assert s.count(o2) == 1, (part, s.count(o), s.count(o2), old[:60]); o = o2
        s = s.replace(o, n)
    minidom.parseString(s); parts[part] = s.encode()

def edit_sub(part, pairs):
    """substring replacement inside runs (for long runs where only a phrase changes)"""
    s = parts[part].decode()
    for old, new in pairs:
        o = esc(old); n = esc(new)
        if s.count(o) != 1:
            o2 = html.escape(old, quote=False); assert s.count(o2) == 1, (part, s.count(o), s.count(o2), old[:60]); o = o2; n = html.escape(new, quote=False)
        s = s.replace(o, n)
    minidom.parseString(s); parts[part] = s.encode()

S = "ppt/slides/"; N = "ppt/notesSlides/"

# ---- relabel: Demo 4 -> Demo 5 (no-attacker)
edit(S + "slide64.xml", [("Demo 4 — no attacker, and the agent improvises anyway", "Demo 5 — no attacker, and the agent improvises anyway")])
edit(S + "slide65.xml", [("Demo 4 — what you are about to see", "Demo 5 — what you are about to see")])
edit_sub(S + "slide52.xml", [("except demo 4, which is Ministral-8B", "except demo 5, which is Ministral-8B")])
# ---- relabel: chatbot Demo 1 -> Demo 4
edit(S + "slide25.xml", [("Demo 1 — what you are about to see", "Demo 4 — what you are about to see")])
edit(S + "slide26.xml", [("Demo 1 — the support chatbot", "Demo 4 — the support chatbot")])
edit(S + "slide51.xml", [("RAN — demo 1, n=3 citable, not pre-registered", "RAN — demo 4, n=3 citable, not pre-registered")])
# ---- opening breach -> Demo 1
edit(S + "slide3.xml", [("A compromised agent (Qwen3-8B) — a directive was planted in its instructions before it started. Watch what it does with it.",
                         "Demo 1 · a compromised agent (Qwen3-8B) — a directive was planted in its instructions before it started. Watch what it does with it.")])
edit(S + "slide22.xml", [("The opening breach", "Demo 1 — the opening breach"),
                         ("The three demos are three of these seven setups", "Demos 1, 2 and 3 are three of these seven setups")])
edit_sub(N + "notesSlide22.xml", [("The demos are demos 2, 3, and the opening breach.", "The demos are demos 1, 2 and 3; demo 1 is the opening breach.")])
# ---- slide 24 map: rows reordered 1,2,3,4 and relabelled; rewrite the run list in order
s = parts[S + "slide24.xml"].decode()
runs = re.findall(r"<a:t>(.*?)</a:t>", s)
assert len(runs) == 23, len(runs)
new_runs = [html.unescape(runs[0]), html.unescape(runs[1]), "DEMO", "THE AGENT", "THE ATTACK", "WHAT IT PROVES",
    "Demo 1 — the opening breach", "ops agent", "poisoned prompt: add a firewall rule", "full defenses on — it breaches anyway, console green (BREACH)",
    "Demo 2", "ops agent (same as demo 1)", "same poisoned prompt", "policy engine OFF — the other two layers catch nothing (BREACH)",
    "Demo 3", "ops agent (same as demo 1)", "same poisoned prompt", "policy engine ON — the rule denies the bucket, the agent stops (HELD)",
    "Demo 4", "support chatbot", "a conversation + a prompt telling it to cave", "the filter blocks the asks; it exports on a later turn",
    "Demos 1, 2 and 3 are the ops agent with a poisoned list. Demo 4 is the support chatbot. All four are attacker-influenced. Demo 5, later, has no attacker at all: the same ops agent, the clean ticket, and it breaches anyway."]
assert html.unescape(runs[6]) == "Opening breach" and html.unescape(runs[10]) == "Demo 1" and "Demo 4, later" in html.unescape(runs[22])
it = iter(new_runs)
s = re.sub(r"<a:t>.*?</a:t>", lambda m: f"<a:t>{esc(next(it))}</a:t>", s)
minidom.parseString(s); parts[S + "slide24.xml"] = s.encode()
edit_sub(N + "notesSlide24.xml", [("The first three demos are the SAME ops agent with a poisoned to-do list, shown three ways. Demo 1 is a DIFFERENT agent",
                                   "Demos 1, 2 and 3 are the SAME ops agent with a poisoned to-do list, shown three ways, played first. Demo 4 is a DIFFERENT agent"),
                                  ("is demo 4, later: a number, and one replayed run.", "is demo 5, later: a number, and one replayed run.")])
# ---- spec slide moves before the clip
edit(S + "slide14.xml", [("carl-ops objective spec · the full prompt is verbatim two slides back · this is the part that carries the weight",
                          "carl-ops objective spec · read this before the clip · the full prompt is verbatim a few slides on · the two clauses that carry the weight")])
edit_sub(N + "notesSlide1.xml", [("Let the opening clip play before you speak.", "Two setup slides (how to read the console, what the boundary says), then let the opening clip play.")])
edit_sub(N + "notesSlide14.xml", [("Read the second clause aloud, slowly, because the whole talk hangs on it:", "This now comes BEFORE the opening clip, so the room knows the rule the agent is about to break. Read the second clause aloud, slowly, because the whole talk hangs on it:")])
# ---- merge slides 5 and 6 into slide66 (layout of 6)
s = parts[S + "slide6.xml"].decode().replace('<p:cSld name="Slide 6">', '<p:cSld name="Slide 66">')
assert '<p:cSld name="Slide 66">' in s
parts[S + "slide66.xml"] = s.encode()
edit(S + "slide66.xml", [
    ('"Why didn\'t you just —"', "Why no per-action fix reaches this"),
    ("every per-action, declared-in-advance fix, and why none of them reaches this", "a legitimate capability · an underspecified order · a specific invented at runtime, and scope-shaped · the four fixes you are about to suggest"),
    ("Every declared-in-advance control fails on a specific the agent makes up mid-run. The only thing left is to check the world after each action — is it still in scope. That is the oracle.",
     "Every declared-in-advance control fails on a specific the agent makes up mid-run. Real orders to real agents are goals, not fully-specified actions, so the agent supplies the missing specifics itself — a bucket name here, an endpoint, a principal, a path — and those are in nobody's threat model. The only thing left is to check the world after each action: is it still in scope. That is the oracle."),
])
parts[S + "_rels/slide66.xml.rels"] = parts[S + "_rels/slide6.xml.rels"].decode().replace("notesSlide6.xml", "notesSlide66.xml").encode()
n = parts[N + "notesSlide6.xml"].decode()
old_note = "This is the Q&amp;A slide. When someone proposes a fix it&apos;s almost always one of these four. Each fails for the same reason: the agent supplied a novel, scope-shaped specific during the run, and declared-in-advance controls can only reason about what exists and is declared before it."
if n.count(old_note) != 1: old_note = old_note.replace("&apos;", "'")
assert n.count(old_note) == 1
n = n.replace(old_note, esc("One slide, four points, then the forward-looking line. The capability is legitimate (managing network policy is this agent's job), the order was underspecified (reach 'the bucket', no name), the specific was invented at runtime and fit the allowed pattern. So each fix the room will propose fails the same way: remove the tool and you break the agent; pre-approve a target that did not exist yet; pattern-match a value that matches the pattern; filter the prompt, which the adaptive-attack study bypassed 12 of 12 times. As we hand agents vaguer goals and more tools, they supply the missing specifics themselves, and nobody wrote those down. Only checking the world after the action catches it. That is the oracle."))
minidom.parseString(n); parts[N + "notesSlide66.xml"] = n.encode()
parts[N + "_rels/notesSlide66.xml.rels"] = parts[N + "_rels/notesSlide6.xml.rels"].decode().replace("slide6.xml", "slide66.xml").encode()
# drop slides 5 and 6 (parts, rels, notes, content types, presentation rels)
for k in [S + "slide5.xml", S + "slide6.xml", S + "_rels/slide5.xml.rels", S + "_rels/slide6.xml.rels",
          N + "notesSlide5.xml", N + "notesSlide6.xml", N + "_rels/notesSlide5.xml.rels", N + "_rels/notesSlide6.xml.rels"]:
    del parts[k]
ct = parts["[Content_Types].xml"].decode()
for pn in ["/ppt/slides/slide5.xml", "/ppt/slides/slide6.xml", "/ppt/notesSlides/notesSlide5.xml", "/ppt/notesSlides/notesSlide6.xml"]:
    ov = re.search(rf'<Override PartName="{re.escape(pn)}"[^>]*/>', ct); assert ov, pn; ct = ct.replace(ov.group(0), "")
ct = ct.replace("</Types>", '<Override PartName="/ppt/slides/slide66.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/><Override PartName="/ppt/notesSlides/notesSlide66.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"/></Types>')
minidom.parseString(ct); parts["[Content_Types].xml"] = ct.encode()

pr = parts["ppt/_rels/presentation.xml.rels"].decode()
rid2t = dict(re.findall(r'Id="(rId\d+)"[^>]*Target="slides/(slide\d+)\.xml"', pr))
t2rid = {v: k for k, v in rid2t.items()}
for sl in ("slide5", "slide6"):
    rel = re.search(rf'<Relationship Id="{t2rid[sl]}"[^>]*/>', pr); assert rel; pr = pr.replace(rel.group(0), "")
rid = max(int(x) for x in re.findall(r'Id="rId(\d+)"', pr)) + 1
pr = pr.replace("</Relationships>", f'<Relationship Id="rId{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide66.xml"/></Relationships>')
minidom.parseString(pr); parts["ppt/_rels/presentation.xml.rels"] = pr.encode()
t2rid["slide66"] = f"rId{rid}"

# ---- new order
order = ["slide1", "slide2", "slide14", "slide3", "slide4", "slide66", "slide7", "slide8", "slide9", "slide10", "slide11", "slide12", "slide13", "slide15"] \
    + [f"slide{i}" for i in range(16, 24)] + ["slide24", "slide28", "slide29", "slide30", "slide31", "slide25", "slide26"] \
    + ["slide32", "slide33", "slide34", "slide35", "slide27", "slide36", "slide37", "slide38", "slide39", "slide65", "slide64", "slide40", "slide41", "slide43"] \
    + [f"slide{i}" for i in range(45, 56)] + ["slide44", "slide42"] + [f"slide{i}" for i in range(56, 64)]
assert len(order) == 64 and len(set(order)) == 64
p = parts["ppt/presentation.xml"].decode()
ids = re.findall(r'<p:sldId id="(\d+)" r:id="(rId\d+)"/>', p)
present = {rid2t[r] for _, r in ids}
assert present - {"slide5", "slide6"} == set(order) - {"slide66"}, (present ^ set(order))
lst = re.search(r"<p:sldIdLst>.*?</p:sldIdLst>", p, flags=re.S).group(0)
base = max(int(i) for i, _ in ids) + 1
new_lst = "<p:sldIdLst>" + "".join(f'<p:sldId id="{base + k}" r:id="{t2rid[sl]}"/>' for k, sl in enumerate(order)) + "</p:sldIdLst>"
p = p.replace(lst, new_lst); minidom.parseString(p); parts["ppt/presentation.xml"] = p.encode()
parts["docProps/app.xml"] = parts["docProps/app.xml"].decode().replace("<Slides>65</Slides>", "<Slides>64</Slides>").encode()

keep = [k for k in names if k in parts] + [k for k in parts if k not in names]
with zipfile.ZipFile(TMP, "w") as z:
    for k in keep:
        z.writestr(k, parts[k], compress_type=zipfile.ZIP_STORED if k.endswith(".mp4") else zipfile.ZIP_DEFLATED)
os.replace(TMP, DECK)
print("restructured: 64 slides; order:", " ".join(order))
