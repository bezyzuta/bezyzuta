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
    model = WhisperModel(model_name, device="auto", compute_type="auto")
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
    slug = job["slug"]
    work = cfg.output_dir / slug
    work.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] download: {job['source_url']}")
    raw = download_gameplay(job["source_url"], work / "source")

    print("[2/5] voiceover")
    vo = synthesize_voiceover(job["script"], cfg, work / "voice.mp3")

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
