#!/usr/bin/env python3
"""Slide 22: define run / cell / sweep and the sweep's design boundary in the footnote; notes expanded. Count-checked, atomic."""
import html, os, re, zipfile
from xml.dom import minidom
DECK = "/home/lbsuto/saster-harness/grrcon-deck-v4.pptx"; TMP = DECK + ".tmp"
def esc(s): return html.escape(s, quote=False).replace("'", "&apos;").replace('"', "&quot;")
with zipfile.ZipFile(DECK) as z:
    names = z.namelist(); parts = {k: z.read(k) for k in names}
f = "ppt/slides/slide22.xml"; s = parts[f].decode()
old_box = '<a:off x="822960" y="6480000"/><a:ext cx="10789920" cy="365760"/>'
assert s.count(old_box) == 1
s = s.replace(old_box, '<a:off x="822960" y="6110000"/><a:ext cx="10789920" cy="730000"/>')
old_run = "<a:t>&quot;All-on&quot; = policy + trace + auditor."
assert s.count(old_run) == 1
defs = ("Run: one trial, one seed, one record you can replay. Cell: one square of this grid, five runs differing only by seed. "
        "Sweep: one victim model over the whole grid, 48 cells and 240 runs, everything else held fixed (fixture, ticket, tools, four rules, k = 5); "
        "seeds are paired by stratum, so every cell starts the same five trajectories and only the defenses differ. A new model, fixture or post-sweep arm is a new run id.")
rpr = re.search(r'<a:r><a:rPr lang="en-US" sz="1000" dirty="0">.*?</a:rPr>', s[s.find(old_run)-900:s.find(old_run)], re.S).group(0)
new_para = f'<a:p><a:pPr indent="0" marL="0"><a:buNone/></a:pPr>{rpr}<a:t>{esc(defs)}</a:t></a:r><a:endParaRPr lang="en-US" sz="1000" dirty="0"/></a:p>'
i = s.rfind("<a:p>", 0, s.find(old_run)); s = s[:i] + new_para + s[i:]
minidom.parseString(s); parts[f] = s.encode()
n = "ppt/notesSlides/notesSlide22.xml"; t = parts[n].decode()
body = [x for x in re.findall(r"<a:t>(.*?)</a:t>", t) if not re.fullmatch(r"\d+", x)]; assert len(body) == 1
new_notes = html.unescape(body[0]) + (" Vocabulary, if asked: a run is one trial with one seed, the thing a clip replays; a cell is one square here, five runs that differ only by seed, "
    "so demo 3's cell can hold one breach, one clean escalation and three honest closes; a sweep is one victim model over the whole grid, 48 cells, 240 runs, "
    "with the fixture, ticket, tools, rule count and k held fixed. Seeds are paired by stratum, never by defense or route, so every cell in a stratum starts the same five trajectories and the defense is the only difference. "
    "Outside the sweep's boundary: a different model is a different sweep, a different fixture is a different experiment (W38 for the chatbot), and a re-run or post-sweep arm is a new run id (w24c re-ran lost trials; demo 5's §T arm is w30t).")
t = t.replace(f"<a:t>{body[0]}</a:t>", f"<a:t>{esc(new_notes)}</a:t>"); minidom.parseString(t); parts[n] = t.encode()
with zipfile.ZipFile(TMP, "w") as z:
    for k in names: z.writestr(k, parts[k], compress_type=zipfile.ZIP_STORED if k.endswith(".mp4") else zipfile.ZIP_DEFLATED)
os.replace(TMP, DECK); print("slide 22 updated")
import html, os, re, zipfile
from xml.dom import minidom
DECK = "/home/lbsuto/saster-harness/grrcon-deck-v4.pptx"; TMP = DECK + ".tmp"
def esc(s): return html.escape(s, quote=False).replace("'", "&apos;").replace('"', "&quot;")
with zipfile.ZipFile(DECK) as z:
    names = z.namelist(); parts = {k: z.read(k) for k in names}
f = "ppt/slides/slide22.xml"; s = parts[f].decode()
def once(o, n):
    global s; assert s.count(o) == 1, (o[:50], s.count(o)); s = s.replace(o, n)
# caption box: smaller, higher
once('<a:off x="1005840" y="5560000"/><a:ext cx="10424160" cy="740664"/>', '<a:off x="1005840" y="5470000"/><a:ext cx="10424160" cy="600000"/>')
cap = re.search(r'<p:sp>(?:(?!</p:sp>).)*The rule that fires in demos 1 and 3.*?</p:sp>', s, re.S).group(0)
s = s.replace(cap, cap.replace('sz="1600"', 'sz="1400"'))
# footnote box
once('<a:off x="822960" y="6110000"/><a:ext cx="10789920" cy="730000"/>', '<a:off x="822960" y="6200000"/><a:ext cx="10789920" cy="640000"/>')
fn = re.search(r'<p:sp>(?:(?!</p:sp>).)*Run: one trial.*?</p:sp>', s, re.S).group(0)
new_fn = fn.replace('sz="1000"', 'sz="900"')
old_defs = re.search(r"<a:t>Run: one trial.*?</a:t>", new_fn).group(0)
defs = ("Run: one trial, one seed, one replayable record. Cell: one square of this grid, five runs differing only by seed. Sweep: one victim model over the whole grid, 48 cells, 240 runs; "
        "fixture, ticket, tools, rules and k held fixed; seeds paired by stratum, so every cell starts the same five trajectories and only the defenses differ. A new model, fixture or re-run is a new run id.")
new_fn = new_fn.replace(old_defs, f"<a:t>{esc(defs)}</a:t>")
s = s.replace(fn, new_fn); minidom.parseString(s); parts[f] = s.encode()
with zipfile.ZipFile(TMP, "w") as z:
    for k in names: z.writestr(k, parts[k], compress_type=zipfile.ZIP_STORED if k.endswith(".mp4") else zipfile.ZIP_DEFLATED)
os.replace(TMP, DECK); print("ok")
