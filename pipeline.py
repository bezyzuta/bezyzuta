#!/usr/bin/env python3
"""Roblox Shorts autopilot: download gameplay -> ElevenLabs TTS -> 9:16 short."""

import argparse
import json
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass
class Config:
    output_dir: Path
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model: str
    whisper_model: str
    target_w: int
    target_h: int
    ducking_db: float
    gemini_api_key: str
    gemini_model: str

    @classmethod
    def load(cls, path: Path) -> "Config":
        data = json.loads(path.read_text(encoding="utf-8"))
        api_key = data.get("elevenlabs_api_key") or os.environ.get("ELEVENLABS_API_KEY", "")
        if not api_key:
            raise SystemExit("elevenlabs_api_key missing in config and ELEVENLABS_API_KEY not set")
        w, h = data.get("target_resolution", [1080, 1920])
        return cls(
            output_dir=Path(data["output_dir"]).expanduser(),
            elevenlabs_api_key=api_key,
            elevenlabs_voice_id=data["elevenlabs_voice_id"],
            elevenlabs_model=data.get("elevenlabs_model", "eleven_multilingual_v2"),
            whisper_model=data.get("whisper_model", "small"),
            target_w=int(w),
            target_h=int(h),
            ducking_db=float(data.get("ducking_db", -18)),
            gemini_api_key=data.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", ""),
            gemini_model=data.get("gemini_model", "gemini-2.5-flash"),
        )


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def download_gameplay(url: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / "%(id)s.%(ext)s")
    run([
        sys.executable, "-m", "yt_dlp",
        "-f", "bv*[height<=1080]+ba/b[height<=1080]",
        "--merge-output-format", "mp4",
        "-o", template,
        url,
    ])
    files = sorted(out_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("yt-dlp produced no mp4")
    return files[0]


def list_channel_videos(channel_url: str, limit: int = 50) -> list:
    """Return [{id, url, title}, ...] for the most recent videos on a channel."""
    result = subprocess.run(
        [sys.executable, "-m", "yt_dlp",
         "--flat-playlist", "-J",
         "--playlist-end", str(limit),
         channel_url],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    entries = data.get("entries") or []
    out = []
    for e in entries:
        vid = e.get("id")
        if not vid:
            continue
        out.append({
            "id": vid,
            "url": e.get("url") or f"https://www.youtube.com/watch?v={vid}",
            "title": e.get("title") or "",
        })
    return out


def pick_unused_channel_video(channel_url: str, used_path: Path, limit: int = 50) -> dict:
    used = set()
    if used_path.exists():
        try:
            used = set(json.loads(used_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            used = set()
    videos = list_channel_videos(channel_url, limit)
    if not videos:
        raise RuntimeError(f"channel returned no videos: {channel_url}")
    available = [v for v in videos if v["id"] not in used]
    if not available:
        raise RuntimeError(
            f"all {len(videos)} channel videos already used; delete {used_path.name} to reset"
        )
    pick = random.choice(available)
    used.add(pick["id"])
    used_path.write_text(json.dumps(sorted(used)), encoding="utf-8")
    return pick


SCRIPT_PROMPT = """Schreibe ein energetisches, jugendliches Skript fuer einen YouTube Short ueber Roblox auf Deutsch.

Thema: {topic}

Anforderungen:
- Laenge: 25-35 Sekunden Sprechzeit (ca. 60-80 deutsche Woerter)
- Starker Hook am Anfang (z.B. "Bro, schau dir das an!", "Achtung!", "99% der Spieler...")
- Action-Beschreibung in der Mitte, spannend und mitreissend
- Call-to-Action am Ende ("Folg fuer mehr...", "Lass ein Like da...")
- Kein Markdown, keine Anfuehrungszeichen, keine Regie-Anweisungen
- Gib NUR den reinen Sprechertext aus, sonst nichts"""


def generate_script_via_gemini(topic: str, cfg: Config) -> str:
    if not cfg.gemini_api_key:
        raise RuntimeError("topic given but gemini_api_key missing in config (and GEMINI_API_KEY env not set)")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": SCRIPT_PROMPT.format(topic=topic)}]}],
        "generationConfig": {
            "temperature": 0.9,
            "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    r = requests.post(url, params={"key": cfg.gemini_api_key}, json=body, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:300]}")
    data = r.json()
    try:
        candidate = data["candidates"][0]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini response had no candidates: {data}") from e
    parts = candidate.get("content", {}).get("parts", []) or []
    text_parts = [p.get("text", "") for p in parts if not p.get("thought")]
    text = "\n".join(text_parts).strip()
    finish = candidate.get("finishReason", "")
    if not text:
        raise RuntimeError(f"Gemini returned no text (finishReason={finish}); full response: {data}")
    if len(text) < 120 or finish not in ("STOP", ""):
        print(f"      WARN: Gemini output looks short ({len(text)} chars, finishReason={finish})")
        print(f"      full response: {json.dumps(data, ensure_ascii=False)[:1200]}")
    return text


def synthesize_voiceover(text: str, cfg: Config, out_path: Path) -> Path:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{cfg.elevenlabs_voice_id}"
    headers = {
        "xi-api-key": cfg.elevenlabs_api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    body = {
        "text": text,
        "model_id": cfg.elevenlabs_model,
        "voice_settings": {"stability": 0.4, "similarity_boost": 0.85, "style": 0.55, "use_speaker_boost": True},
    }
    r = requests.post(url, headers=headers, json=body, timeout=180)
    if r.status_code >= 400:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:300]}")
    out_path.write_bytes(r.content)
    return out_path


def probe_duration(media: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(media)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def pick_clip(source: Path, target_seconds: float, out_path: Path) -> Path:
    total = probe_duration(source)
    margin = 5.0
    if total <= target_seconds + 2 * margin:
        start = max(0.0, (total - target_seconds) / 2)
    else:
        start = random.uniform(margin, total - target_seconds - margin)
    # re-encode (not -c copy) so we land on exact frames and audio stays in sync
    run([
        "ffmpeg", "-y",
        "-ss", f"{start:.2f}", "-i", str(source),
        "-t", f"{target_seconds:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k",
        str(out_path),
    ])
    return out_path


def transcribe_words(audio_path: Path, model_name: str):
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(audio_path), word_timestamps=True)
    words = []
    for seg in segments:
        for w in seg.words or []:
            words.append((float(w.start), float(w.end), w.word.strip()))
    return words


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def write_ass(words, video_w: int, video_h: int, out_path: Path) -> Path:
    """Bold, center-bottom karaoke captions, 2-3 words per chunk."""
    fontsize = max(56, int(video_h * 0.048))
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_w}\n"
        f"PlayResY: {video_h}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Pop, Impact, {fontsize}, &H00FFFFFF, &H000000FF, &H00000000, &H64000000, "
        "1, 0, 0, 0, 100, 100, 0, 0, 1, 6, 2, 2, 80, 80, 360, 1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    chunks, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= 3:
            chunks.append(buf)
            buf = []
    if buf:
        chunks.append(buf)

    lines = []
    for ch in chunks:
        start, end = ch[0][0], ch[-1][1]
        text = " ".join(w[2] for w in ch).upper().replace("{", "(").replace("}", ")")
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Pop,,0,0,0,,{{\\fad(80,80)}}{text}")

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def compose_short(gameplay_clip: Path, voice_audio: Path, ass_path: Path,
                  cfg: Config, out_path: Path) -> Path:
    # crop center vertical strip from gameplay, scale to target, then burn captions
    vf = (
        f"crop=ih*9/16:ih,scale={cfg.target_w}:{cfg.target_h}:flags=lanczos,"
        f"subtitles={ass_path.name}"
    )
    # duck original gameplay audio, mix with voice
    af = (
        f"[0:a]volume={cfg.ducking_db}dB[bg];"
        f"[bg][1:a]amix=inputs=2:duration=shortest:dropout_transition=0[a]"
    )
    # cwd = ass dir so the subtitles filter doesn't trip over Windows drive colons
    cwd = ass_path.parent
    run([
        "ffmpeg", "-y",
        "-i", str(gameplay_clip),
        "-i", str(voice_audio),
        "-filter_complex", f"[0:v]{vf}[v];{af}",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ], cwd=str(cwd))
    return out_path


def run_one(job: dict, cfg: Config) -> Path:
    base_slug = job["slug"]
    source_url = (job.get("source_url") or "").strip()

    if not source_url:
        channel_url = (job.get("channel_url") or "").strip()
        if not channel_url:
            raise RuntimeError(f"job {base_slug!r} needs either 'source_url' or 'channel_url'")
        used_path = cfg.output_dir / "used_videos.json"
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        pick = pick_unused_channel_video(channel_url, used_path)
        source_url = pick["url"]
        slug = f"{base_slug}-{pick['id']}"
        print(f"      channel pick: {pick['title'][:60]} ({pick['id']})")
    else:
        slug = base_slug

    work = cfg.output_dir / slug
    work.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] download: {source_url}")
    raw = download_gameplay(source_url, work / "source")

    script = (job.get("script") or "").strip()
    if not script:
        topic = (job.get("topic") or "").strip()
        if not topic:
            raise RuntimeError(f"job {slug!r} has neither 'script' nor 'topic'")
        print(f"      generating script via Gemini for topic: {topic!r}")
        script = generate_script_via_gemini(topic, cfg)
        (work / "script.txt").write_text(script, encoding="utf-8")
        preview = script[:80].replace("\n", " ")
        print(f"      script: {preview}...")

    print("[2/5] voiceover")
    vo = synthesize_voiceover(script, cfg, work / "voice.mp3")

    vo_dur = probe_duration(vo)
    target = min(max(vo_dur + 0.6, 22.0), 45.0)
    print(f"      voice {vo_dur:.1f}s -> clip {target:.1f}s")

    print("[3/5] pick gameplay segment")
    clip = pick_clip(raw, target, work / "clip.mp4")

    print("[4/5] transcribe + captions")
    words = transcribe_words(vo, cfg.whisper_model)
    ass = write_ass(words, cfg.target_w, cfg.target_h, work / "captions.ass")

    print("[5/5] compose final short")
    out = cfg.output_dir / f"{slug}.mp4"
    compose_short(clip, vo, ass, cfg, out)
    print(f"      -> {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Roblox Shorts pipeline")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--jobs", required=True, help="JSON file: list of {slug, source_url, script}")
    args = ap.parse_args()

    cfg = Config.load(Path(args.config))
    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    logfile = cfg.output_dir / "logdatei.txt"

    for job in jobs:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            out = run_one(job, cfg)
            with logfile.open("a", encoding="utf-8") as f:
                f.write(f"{ts} OK   {job['slug']} -> {out}\n")
        except subprocess.CalledProcessError as e:
            with logfile.open("a", encoding="utf-8") as f:
                f.write(f"{ts} FAIL {job['slug']}: {e.cmd}\n")
            print(f"FAIL {job['slug']}: {e}", file=sys.stderr)
        except Exception as e:
            with logfile.open("a", encoding="utf-8") as f:
                f.write(f"{ts} FAIL {job['slug']}: {e}\n")
            print(f"FAIL {job['slug']}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
