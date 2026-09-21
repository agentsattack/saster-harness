#!/usr/bin/env python3
"""Console-style clip of one W38 support run, drawn from the sealed record's manifest
transcript and diagnoses at run time. Turn rows: user text (wrapped), filter verdict,
Carl's reply or action, boundary state. Replay clock (the record carries no timing)."""
import json, os, subprocess, textwrap
from PIL import Image, ImageDraw, ImageFont

REPO = "/home/lbsuto/saster-harness"; OUT = os.path.dirname(os.path.abspath(__file__))
RUN = os.environ.get("W38_CLIP_RUN", "w38-model-deepseek-seed20260925")
D = f"{REPO}/runs/w38_beat1_clean/{RUN}/"
man = json.load(open(D + "manifest.json")); rec = json.loads(open(D + "trajectories.jsonl").readline())
tr = man["transcript"]

# group the transcript into turns: each user message starts a turn
turns = []
for t in tr:
    if t["who"] == "user":
        turns.append({"user": t["text"], "blocked": False, "carl": [], "action": None})
    elif t["who"] == "system":
        turns[-1]["blocked"] = True
    elif t["who"] == "Carl":
        if t["text"].startswith("[ran "):
            turns[-1]["action"] = t["text"]
        elif t["text"].startswith("[tried "):
            turns[-1]["carl"].append("(action blocked by the filter)")
        else:
            txt = t["text"]
            if "</think>" in txt: txt = txt.split("</think>")[-1].strip()
            elif "<think>" in txt: txt = "(reasoning only; no reply shown)"
            turns[-1]["carl"].append(txt)

W, H, FPS = 1920, 1080, 30
FD = "/usr/share/fonts/truetype/dejavu/"
F = ImageFont.truetype(FD + "DejaVuSansMono.ttf", 21); FB = ImageFont.truetype(FD + "DejaVuSansMono-Bold.ttf", 24); FS = ImageFont.truetype(FD + "DejaVuSansMono.ttf", 19)
BG = (8, 15, 10); TITLE = (1, 250, 68); SUB = (48, 132, 68); GREY = (150, 165, 153); WHITE = (225, 232, 225)
OK = (67, 215, 105); RED = (255, 65, 59); REDBOX = (40, 15, 13); CLOCK = (61, 214, 103); AMBER = (230, 170, 60)
SUBTITLE = "Support agent  ·  Qwen3-8B  ·  no planted weakness  ·  real input filter on every message, blocked text quarantined  ·  attacker: a model  ·  replay"
T0, DT, HOLD = 1.5, 3.0, 6.0
t_turn = [T0 + DT * k for k in range(len(turns))]
DUR = t_turn[-1] + 3.0 + HOLD

def frame(t):
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    d.text((60, 24), "agent console", font=FB, fill=TITLE); d.text((60, 54), SUBTITLE, font=FS, fill=SUB)
    mm, ss = divmod(t, 60); clk = f"{int(mm):02d}:{ss:04.1f}"
    d.text((1860 - d.textlength(clk, font=FB), 24), clk, font=FB, fill=CLOCK)
    y = 110; breached = False
    for k, tu in enumerate(turns):
        if t < t_turn[k]: break
        d.text((60, y), f"[turn {k}]", font=F, fill=GREY)
        for i, line in enumerate(textwrap.wrap(tu["user"], 118)[:3]):
            d.text((230, y + 30 * i), line, font=F, fill=WHITE)
        y += 30 * min(3, len(textwrap.wrap(tu["user"], 118))) + 4
        if tu["blocked"]:
            d.rectangle([228, y - 2, 640, y + 28], outline=RED); d.text((240, y + 2), "input filter: BLOCKED", font=F, fill=RED); y += 34
            d.text((230, y), "boundary: intact", font=F, fill=OK); y += 36
            continue
        d.text((230, y), "input filter: allowed", font=F, fill=OK); y += 32
        if tu["action"] and t >= t_turn[k] + 1.5:
            breached = True
            d.rectangle([228, y - 2, 1000, y + 28], outline=RED, fill=REDBOX); d.text((240, y + 2), "agent exports the customer database", font=F, fill=RED); y += 34
            d.text((230, y), "boundary: VIOLATED", font=FB, fill=RED); y += 36
        elif tu["carl"] and t >= t_turn[k] + 1.5:
            reply = textwrap.wrap(tu["carl"][0], 118)[:2]
            for i, line in enumerate(reply): d.text((230, y + 28 * i), "carl: " + line if i == 0 else "      " + line, font=FS, fill=GREY)
            y += 28 * len(reply) + 4
            d.text((230, y), "boundary: intact", font=F, fill=OK); y += 36
        else:
            y += 8
        if tu["action"] and breached:
            reply = textwrap.wrap(tu["carl"][0], 118)[:2] if tu["carl"] else []
            for i, line in enumerate(reply): d.text((230, y + 28 * i), "carl: " + line if i == 0 else "      " + line, font=FS, fill=GREY)
            y += 28 * len(reply) + 4
    d.rectangle([0, 988, W, 1040], fill=(12, 16, 12))
    if t < T0: d.text((60, 1002), "-  starting", font=F, fill=GREY)
    elif t < t_turn[-1] + 3.0:
        d.text((60, 1002), "|  agent thinking", font=F, fill=GREY)
        if int(t * 2) % 2 == 0: d.rectangle([1832, 1006, 1848, 1022], fill=TITLE)
    else:
        nb = len(man["l1_input_blocks"])
        d.text((60, 1002), f"Run finished.  The filter blocked {nb} message{'s' if nb != 1 else ''}.  The database was exported on an ordinary-looking turn; every message that turn passed.", font=F, fill=RED)
    return im

ff = f"{REPO}/.venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-aarch64-v7.0.2"
mp4 = f"{OUT}/clip_support_clean.mp4"
p = subprocess.Popen([ff, "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high", "-crf", "20", "-movflags", "+faststart", mp4], stdin=subprocess.PIPE)
for k in range(int(DUR * FPS)): p.stdin.write(frame(k / FPS).tobytes())
p.stdin.close(); p.wait()
frame(0.5).save(f"{OUT}/clip_support_clean_poster.png"); frame(DUR - 0.1).save(f"{OUT}/clip_support_clean_last.png")
print("turns", len(turns), "duration", DUR, "rc", p.returncode, "size", os.path.getsize(mp4))
