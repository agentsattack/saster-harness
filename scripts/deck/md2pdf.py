import re, html, subprocess, sys, os, shutil
src, out_pdf = sys.argv[1], sys.argv[2]
COMPACT = len(sys.argv) > 3 and sys.argv[3] == "compact"
lines = open(src).read().splitlines()
def inline(t):
    t = html.escape(t, quote=False)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"(?<![\w*])\*([^*]+?)\*(?![\w*])", r"<i>\1</i>", t)
    return t
body = []; i = 0; in_list = False; in_table = False
def close():
    global in_list, in_table
    if in_list: body.append("</ul>"); in_list = False
    if in_table: body.append("</table>"); in_table = False
while i < len(lines):
    l = lines[i]
    if l.startswith("# "): close(); body.append(f"<h1>{inline(l[2:])}</h1>")
    elif l.startswith("## "): close(); body.append(f"<h2>{inline(l[3:])}</h2>")
    elif l.startswith("### "): close(); body.append(f"<h3>{inline(l[4:])}</h3>")
    elif l.strip() == "---": close(); body.append("<hr/>")
    elif l.startswith("- "):
        if in_table: body.append("</table>"); in_table = False
        if not in_list: body.append("<ul>"); in_list = True
        body.append(f"<li>{inline(l[2:])}</li>")
    elif l.startswith("|"):
        if in_list: body.append("</ul>"); in_list = False
        cells = [c.strip() for c in l.strip().strip("|").split("|")]
        if all(re.fullmatch(r"-+", c) for c in cells): i += 1; continue
        if not in_table: body.append("<table>"); in_table = True; tag = "th"
        else: tag = "td"
        body.append("<tr>" + "".join(f"<{tag}>{inline(c)}</{tag}>" for c in cells) + "</tr>")
    elif l.strip() == "": close()
    else:
        close()
        if l.startswith("*") and l.endswith("*") and not l.startswith("**"): body.append(f"<p class='stage'>{inline(l[1:-1])}</p>")
        else: body.append(f"<p>{inline(l)}</p>")
    i += 1
close()
css = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 10.5pt; line-height: 1.38; color: #111; }
h1 { font-size: 20pt; margin: 0 0 6pt 0; }
h2 { font-size: 13pt; margin: 16pt 0 4pt 0; padding-top: 6pt; border-top: 1px solid #bbb; color: #0a3d1a; page-break-after: avoid; }
h3 { font-size: 11.5pt; margin: 10pt 0 3pt 0; }
p { margin: 3pt 0 5pt 0; }
p.stage { color: #444; font-style: italic; margin-bottom: 4pt; }
ul { margin: 2pt 0 6pt 0; padding-left: 16pt; }
li { margin: 0 0 3pt 0; }
table { border-collapse: collapse; margin: 6pt 0 8pt 0; width: 100%; font-size: 9.5pt; }
th, td { border: 1px solid #999; padding: 3pt 5pt; vertical-align: top; text-align: left; }
th { background: #e8efe9; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 9pt; }
hr { border: 0; border-top: 1px solid #999; margin: 10pt 0; }
"""
if COMPACT:
    css = """
@page { size: A4; margin: 6mm 8mm; }
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 6.5pt; line-height: 1.13; color: #111; }
h1 { font-size: 11.5pt; margin: 0 0 3pt 0; }
h2 { font-size: 9pt; margin: 4pt 0 2pt 0; }
p { margin: 1.5pt 0 3pt 0; }
ul { margin: 1pt 0 3pt 0; padding-left: 12pt; } li { margin: 0 0 1pt 0; }
table { border-collapse: collapse; margin: 2pt 0 4pt 0; width: 100%; font-size: 6.6pt; }
th, td { border: 1px solid #999; padding: 1.2pt 3pt; vertical-align: top; text-align: left; }
th { background: #e8efe9; }
code { font-family: 'DejaVu Sans Mono', monospace; font-size: 6.8pt; }
"""
html_doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>GrrCON talk narrative</title><style>{css}</style></head><body>{''.join(body)}</body></html>"
tmpdir = os.path.dirname(os.path.abspath(__file__))
h = os.path.join(tmpdir, os.path.basename(out_pdf).replace(".pdf", ".html")); open(h, "w").write(html_doc)
r = subprocess.run(["soffice", "--headless", "--convert-to", "pdf:writer_web_pdf_Export", "--outdir", tmpdir, h], capture_output=True, text=True, timeout=300)
pdf = os.path.join(tmpdir, os.path.basename(out_pdf))
if not os.path.exists(pdf): print(r.stdout, r.stderr); sys.exit(1)
shutil.copyfile(pdf, out_pdf); print("wrote", out_pdf)
