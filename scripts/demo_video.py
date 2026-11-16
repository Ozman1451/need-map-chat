"""Edit the recorded demo into docs/media/demo.mp4 + demo.gif (ffmpeg only).

Input: docs/media/raw/<clip>/{frames/*.jpg, timeline.json, cap_*.png} from
`node frontend/scripts/record-demo.ts <clip>` (+ `--captions` for the pills).
Dead time (page load, RPM gaps, waiting for Gemini) is cut via the timeline's cut marks.

    python scripts/demo_video.py                      # whole "main" clip
    python scripts/demo_video.py main:1-2 'hover*1.6' 'main@c9~159.85' 'main@c10~s9#crop=735:0:1185:667'
      clip:3-5 = steps 3..5 · clip:c4-7 = from caption 4 · clip@a~b = seconds/cN/sK · *1.6 = speed
      (below 1 = slow-motion / freeze) · #crop=x:y:w:h = zoom into that region
"""
from __future__ import annotations

import argparse
import bisect
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs" / "media"
RAW = MEDIA / "raw"
FPS = 30
CAP_FADE = 0.3


def load(clip: str) -> dict:
    tl = json.loads((RAW / clip / "timeline.json").read_text())
    tl["clip"] = clip
    caps = [m for m in tl["marks"] if m["kind"] == "caption"]
    for i, m in enumerate(caps):
        m["png"] = str(RAW / clip / f"cap_{i:02d}.png")
    return tl


def point(tl: dict, p: str) -> float:
    """Timeline position: `cN` = N-th caption, `sK` = step K mark, else seconds."""
    if p[0] == "c":
        return [m for m in tl["marks"] if m["kind"] == "caption"][int(p[1:])]["t"]
    if p[0] == "s":
        return next(m["t"] for m in tl["marks"] if m["kind"] == "step" and m["text"] == p[1:])
    return float(p)


def span(tl: dict, rng: str) -> tuple[float, float]:
    """`@a~b` = positions (see point); `first-last` = steps inclusive, `cN-last` starts at a caption."""
    if rng.startswith("@"):
        a, b = rng[1:].split("~")
        return point(tl, a), point(tl, b)
    steps = [m for m in tl["marks"] if m["kind"] == "step"]
    names = [m["text"] for m in steps]
    first, _, last = rng.partition("-")
    last = last or first
    a = point(tl, first) if first[0] == "c" else steps[names.index(first)]["t"]
    return a, steps[names.index(last) + 1]["t"]


def crop_frames(clip: str, idx: list[int], crop: str) -> str:
    """Crop + upscale frames idx[0]..idx[-1] of a clip (Loom-style zoom); returns the frame dir."""
    out = RAW / clip / f"crop_{crop.replace(':', '_')}"
    out.mkdir(exist_ok=True)
    lo, hi = min(idx), max(idx)
    x, y, w, h = crop.split(":")
    run(["ffmpeg", "-y", "-loglevel", "error", "-start_number", str(lo), "-i", str(RAW / clip / "frames" / "%06d.jpg"),
         "-frames:v", str(hi - lo + 1), "-vf", f"crop={w}:{h}:{x}:{y},scale=1920:1080:flags=lanczos", "-q:v", "2",
         "-start_number", str(lo), str(out / "%06d.jpg")])
    return str(out)


def keeps(tl: dict, a: float, b: float) -> list[tuple[float, float]]:
    """[a, b] minus every cut_start..cut_end pair."""
    out, cur, start = [], a, None
    for m in tl["marks"]:
        if m["kind"] == "cut_start":
            start = m["t"]
        elif m["kind"] == "cut_end" and start is not None:
            s, e = max(start, a), min(m["t"], b)
            if e > s:
                if s > cur:
                    out.append((cur, s))
                cur = max(cur, e)
            start = None
    if b > cur:
        out.append((cur, b))
    return out


def build(plan: list[str]) -> tuple[list[tuple[str, float]], list[dict], list[float], float]:
    """Frame list with durations, captions and chart-appearance times on the output timeline."""
    entries: list[tuple[str, float]] = []
    captions: list[dict] = []
    reveals: list[float] = []
    clock = 0.0
    for item in plan:
        item, _, crop = item.partition("#crop=")
        item, _, speed_s = item.partition("*")
        speed = float(speed_s or 1)
        clip, rng = (item.split("@", 1)[0], "@" + item.split("@", 1)[1]) if "@" in item else (item.partition(":")[0], item.partition(":")[2])
        tl = load(clip)
        steps = [m["text"] for m in tl["marks"] if m["kind"] == "step" and m["text"] != "end"]
        a, b = span(tl, rng or f"{steps[0]}-{steps[-1]}")
        segs = keeps(tl, a, b)
        times = [f["t"] for f in tl["frames"]]
        files = [str(RAW / clip / f["f"]) for f in tl["frames"]]
        if crop:
            used = [max(0, bisect.bisect_right(times, t) - 1) for s, e in segs for t in (s, e)]
            cdir = crop_frames(clip, used, crop)
            files = [f"{cdir}/{Path(f).name}" for f in files]

        def out_time(t: float) -> float:
            acc = clock
            for s, e in segs:
                if t < s:
                    return acc
                if t <= e:
                    return acc + (t - s) / speed
                acc += (e - s) / speed
            return acc

        for m in tl["marks"]:
            if m["kind"] == "caption" and a <= m["t"] < b:
                captions.append({"text": m["text"], "png": m["png"], "start": out_time(m["t"])})
            if m["kind"] == "cut_end" and a < m["t"] < b:
                reveals.append(out_time(m["t"]))
        for s, e in segs:
            n = round((e - s) / speed * FPS)
            for k in range(n):
                i = max(0, bisect.bisect_right(times, s + k * speed / FPS) - 1)
                if entries and entries[-1][0] == files[i]:
                    entries[-1] = (files[i], entries[-1][1] + 1 / FPS)
                else:
                    entries.append((files[i], 1 / FPS))
            clock += n / FPS
    for c, nxt in zip(captions, captions[1:] + [None]):
        c["end"] = (nxt["start"] if nxt else clock) - 0.1
        c["start"] += 0.15
    return entries, captions, reveals, clock


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def encode(entries, captions, total: float, out: Path) -> None:
    lst = RAW / "concat.txt"
    lines = [f"file '{f}'\nduration {d:.5f}" for f, d in entries] + [f"file '{entries[-1][0]}'"]
    lst.write_text("\n".join(lines) + "\n")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
    graph = [f"[0:v]fps={FPS},scale=1920:1080,setsar=1[v0]"]
    for k, c in enumerate(captions, start=1):
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", c["png"]]
        a, b = c["start"], c["end"]
        graph.append(f"[{k}:v]format=rgba,fade=t=in:st={a:.2f}:d={CAP_FADE}:alpha=1,"
                     f"fade=t=out:st={b - CAP_FADE:.2f}:d={CAP_FADE}:alpha=1[c{k}]")
        y = f"H-h-36+max(0\\,{a + CAP_FADE:.2f}-t)*60"
        graph.append(f"[v{k - 1}][c{k}]overlay=x=(W-w)/2:y='{y}':enable='between(t,{a:.2f},{b:.2f})'[v{k}]")
    graph.append(f"[v{len(captions)}]format=yuv420p[out]")
    cmd += ["-filter_complex", ";".join(graph), "-map", "[out]", "-t", f"{total:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-r", str(FPS),
            "-movflags", "+faststart", "-an", str(out)]
    run(cmd)


def gif(src: Path, windows: list[tuple[float, float]], out: Path) -> None:
    parts = "".join(f"[0:v]trim={a:.2f}:{b:.2f},setpts=PTS-STARTPTS[g{i}];" for i, (a, b) in enumerate(windows))
    cat = "".join(f"[g{i}]" for i in range(len(windows)))
    graph = (f"{parts}{cat}concat=n={len(windows)}:v=1:a=0,fps=12,scale=960:-1:flags=lanczos,split[x][y];"
             "[x]palettegen=max_colors=128:stats_mode=diff[p];[y][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-filter_complex", graph, "-loop", "0", str(out)])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", nargs="*", default=["main"])
    ap.add_argument("--gif", default="", help="comma list of start:end output seconds (default: map + drill-down)")
    args = ap.parse_args()
    entries, captions, reveals, total = build(args.plan)
    (RAW / "edit.json").write_text(json.dumps({"total": total, "captions": captions, "reveals": reveals}, indent=1))
    out = MEDIA / "demo.mp4"
    encode(entries, captions, total, out)
    print(f"demo.mp4: {total:.1f}s, {out.stat().st_size / 1e6:.1f} MB")
    if args.gif:
        windows = [tuple(map(float, w.split(":"))) for w in args.gif.split(",")]
    else:
        windows = [(reveals[1] - 0.6, reveals[1] + 5.0), (reveals[-1] - 0.6, reveals[-1] + 5.5)]
    gif(out, windows, MEDIA / "demo.gif")
    print(f"demo.gif: {sum(b - a for a, b in windows):.1f}s, {(MEDIA / 'demo.gif').stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
