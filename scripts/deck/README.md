# Deck tooling (session of 18–20 Sep 2026)

Helpers used to build `grrcon-deck-v4.pptx` and its companions. They edit the .pptx as a zip of XML,
replace text inside `<a:t>` runs with count==1 checks, validate with minidom, and write atomically.
Renderers draw console-style clips from sealed records with PIL and encode with the venv's imageio-ffmpeg.

- `md2pdf.py <md> <pdf> [compact]` — the markdown-to-PDF converter (LibreOffice headless) for the study guide, companion and one-pager.
- `render_induced_clip.py` — demo 6 clip (no-attacker record, w24b Ministral l2/obstructed/induced #0).
- `render_phonehome_clip.py` — demo 5 clip (§T record, w30t Qwen all/obstructed/compromised/firewall #0).
- `render_support_clip.py` — demo 4 clip (W38 record, env `W38_CLIP_RUN`).
- `oracle_diagram.py` — the oracle workflow image on slide 21.
- `insert_slide.py`, `add_phonehome.py`, `demo4_clean.py`, `restructure.py` — the slide-surgery scripts, kept as records of what was done; each was run once.

Render check after any edit: `soffice --headless --convert-to pdf` then `pdftoppm` a page and look at it.
