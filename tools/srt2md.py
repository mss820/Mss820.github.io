#!/usr/bin/env python3
"""Convert a YouTube auto-caption SRT into a cleaned, timestamped transcript.md.

Handles two quirks of YouTube ASR output:
  * rollup cues that repeat the tail of the previous cue (collapsed)
  * '>>' speaker-change markers (used as turn boundaries)

Usage: srt2md.py IN.srt [--info v.info.json] [--title T] [--url U] [-o OUT.md]
"""
import argparse, json, os, re, sys

SPLIT_AFTER = 75          # seconds; break very long turns into sub-paragraphs
ANNOT = re.compile(r"^\[[^\]]+\]$")


def parse_srt(path):
    blocks, cur = [], []
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.rstrip("\n")
        if not line.strip():
            if cur: blocks.append(cur); cur = []
        else:
            cur.append(line)
    if cur: blocks.append(cur)

    ts = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{1,3})?\s*-->")
    cues = []
    for b in blocks:
        m = None; ti = 0
        for i, l in enumerate(b):
            m = ts.search(l)
            if m: ti = i; break
        if not m: continue
        h, mi, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        ms = int(m.group(4) or 0)
        start = h*3600 + mi*60 + s + ms/1000
        text = " ".join(b[ti+1:])
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if text: cues.append((start, text))
    cues.sort(key=lambda c: c[0])
    return cues


def to_turns(cues):
    """Split into speaker turns on '>>'; collapse rollup repetition."""
    turns, cur, prev = [], None, []

    def flush():
        nonlocal cur
        if cur and cur["words"]:
            turns.append(cur)
        cur = None

    for start, text in cues:
        new_turn = text.lstrip().startswith(">>")
        body = text.lstrip()[2:].strip() if new_turn else text
        # a bare annotation ('>> [laughter]') is not a real turn boundary
        if new_turn and ANNOT.match(body):
            new_turn = False
        if new_turn or cur is None:
            flush()
            cur = {"start": start, "words": []}
        words = body.split()
        overlap = 0
        for n in range(min(len(prev), len(words)), 0, -1):
            if prev[-n:] == words[:n]: overlap = n; break
        new = words[overlap:]
        if new:
            cur["words"].extend((start, w) for w in new)
            prev = (prev + new)[-40:]
    flush()
    return turns


def hms(t):
    t = int(t)
    return f"{t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}"


def tidy(s):
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.;:?!])", r"\1", s)
    s = re.sub(r"\b(\w+) \1\b", r"\1", s)      # immediate stutter dupes
    return (s[0].upper() + s[1:]) if s else s


def render(turns):
    """Turn -> one or more (timestamp, text) paragraphs."""
    out = []
    for t in turns:
        anchor = t["start"]; buf = []
        for ts_, w in t["words"]:
            if buf and ts_ - anchor >= SPLIT_AFTER:
                out.append((anchor, " ".join(buf), False))
                anchor = ts_; buf = []
            buf.append(w)
        if buf:
            out.append((anchor, " ".join(buf), True))
    # mark first paragraph of each turn
    res, prev_end = [], True
    for ts_, txt, _ in out:
        res.append((ts_, txt, prev_end)); prev_end = False
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srt"); ap.add_argument("--info"); ap.add_argument("--title")
    ap.add_argument("--url"); ap.add_argument("-o", default="transcript.md")
    a = ap.parse_args()

    meta = {"title": a.title, "url": a.url}
    if a.info and os.path.exists(a.info):
        d = json.load(open(a.info, encoding="utf-8"))
        meta = {"title": a.title or d.get("title"), "url": a.url or d.get("webpage_url"),
                "channel": d.get("uploader") or d.get("channel"),
                "duration": d.get("duration"), "date": d.get("upload_date")}

    cues = parse_srt(a.srt)
    turns = to_turns(cues)
    paras = render(turns)

    L = [f"# {meta.get('title') or 'Transcript'}\n"]
    if meta.get("channel"): L.append(f"**Channel:** {meta['channel']}  ")
    if meta.get("date"):
        d = meta["date"]; L.append(f"**Published:** {d[:4]}-{d[4:6]}-{d[6:]}  ")
    dur = meta.get("duration") or (cues[-1][0] if cues else 0)
    L.append(f"**Duration:** ~{hms(dur)}  ")
    if meta.get("url"): L.append(f"**Source:** {meta['url']}  ")
    L.append(f"\n*Generated from YouTube auto-generated English captions (ASR). "
             f"Expect word-level errors, especially on names and technical terms. "
             f"`>>` in the source marks a speaker change; paragraph breaks below follow "
             f"those turns, but the captions carry no speaker names, so none are asserted here.*\n")
    L.append("---\n")
    for start, text, _ in paras:
        L.append(f"**[{hms(start)}]** {tidy(text)}\n")

    open(a.o, "w", encoding="utf-8").write("\n".join(L))
    words = sum(len(t.split()) for _, t, _ in paras)
    print(f"wrote {a.o}: {len(turns)} turns, {len(paras)} paragraphs, ~{words} words, "
          f"through {hms(dur)}")


if __name__ == "__main__":
    main()
