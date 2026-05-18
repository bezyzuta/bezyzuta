#!/usr/bin/env python3
"""Roblox Shorts autopilot: download gameplay -> ElevenLabs TTS -> 9:16 short."""

import argparse
import json
import os
import random
import re
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import requests


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _loads_lenient(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_TRAILING_COMMA_RE.sub(r"\1", text))


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
    cloudflare_account_id: str
    cloudflare_api_token: str
    cloudflare_image_model: str

    @classmethod
    def load(cls, path: Path) -> "Config":
        data = _loads_lenient(path.read_text(encoding="utf-8"))
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
            cloudflare_account_id=data.get("cloudflare_account_id") or os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
            cloudflare_api_token=data.get("cloudflare_api_token") or os.environ.get("CLOUDFLARE_API_TOKEN", ""),
            cloudflare_image_model=data.get("cloudflare_image_model", "@cf/black-forest-labs/flux-1-schnell"),
        )


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def run_capture_stderr(cmd: list, **kw) -> subprocess.CompletedProcess:
    """Like run(), but on failure raises RuntimeError with the tail of stderr
    so the GUI surfaces the actual ffmpeg/process error message."""
    try:
        return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)
    except subprocess.CalledProcessError as e:
        tail = "\n".join((e.stderr or "").strip().splitlines()[-30:])
        raise RuntimeError(
            f"{cmd[0]} failed (exit {e.returncode}). Last stderr lines:\n{tail}"
        ) from e


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


def pick_unused_channel_video(channel_url: str, used_path: Path, limit: int = 200,
                              title_filter: list | None = None) -> dict:
    used = set()
    if used_path.exists():
        try:
            used = set(json.loads(used_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            used = set()
    videos = list_channel_videos(channel_url, limit)
    if not videos:
        raise RuntimeError(f"channel returned no videos: {channel_url}")
    if title_filter:
        keywords = [k.lower() for k in title_filter]
        filtered = [v for v in videos if any(k in v["title"].lower() for k in keywords)]
        if not filtered:
            sample_titles = "; ".join(v["title"][:40] for v in videos[:5])
            raise RuntimeError(
                f"no channel videos matched title_filter {title_filter}. "
                f"First titles: {sample_titles}"
            )
        videos = filtered
    available = [v for v in videos if v["id"] not in used]
    if not available:
        raise RuntimeError(
            f"all {len(videos)} matching channel videos already used; "
            f"delete {used_path.name} to reset"
        )
    pick = random.choice(available)
    used.add(pick["id"])
    used_path.write_text(json.dumps(sorted(used)), encoding="utf-8")
    return pick


SCRIPT_PROMPT = """Schreibe ein energetisches, jugendliches Skript fuer einen YouTube Short ueber Roblox auf Deutsch.

Thema: {topic}

Anforderungen:
- Laenge: ca. {target_low}-{target_high} Sekunden Sprechzeit (etwa {words_low}-{words_high} deutsche Woerter)
- Starker Hook am Anfang (z.B. "Bro, schau dir das an!", "Achtung!", "99% der Spieler...")
- Action-Beschreibung in der Mitte, spannend und mitreissend
- Call-to-Action am Ende ("Folg fuer mehr...", "Lass ein Like da...")
- Kein Markdown, keine Anfuehrungszeichen, keine Regie-Anweisungen
- Gib NUR den reinen Sprechertext aus, sonst nichts"""


def _gemini_post(url: str, params: dict, body: dict, retries: int = 4,
                 backoff: tuple = (10, 30, 60, 60)) -> dict:
    """POST to Gemini with exponential backoff on 429/503."""
    last_err = None
    for attempt in range(retries + 1):
        r = requests.post(url, params=params, json=body, timeout=60)
        if r.status_code < 400:
            return r.json()
        try:
            err_msg = (r.json().get("error", {}) or {}).get("message", "") or r.text
        except Exception:
            err_msg = r.text
        err_msg = err_msg[:600]
        last_err = f"Gemini {r.status_code}: {err_msg}"
        # Permanent failures (billing/quota exhausted) — no point retrying
        low = err_msg.lower()
        if any(s in low for s in ("prepayment credits", "billing", "quota exceeded", "exceeded your current quota")):
            break
        if r.status_code in (429, 503) and attempt < retries:
            wait = backoff[min(attempt, len(backoff) - 1)]
            print(f"      Gemini {r.status_code}, retrying in {wait}s (attempt {attempt + 2}/{retries + 1})")
            time.sleep(wait)
            continue
        break
    raise RuntimeError(last_err)


_SCRIPT_TEMPLATES = [
    "Bro, schau dir das an! {topic} – das ist absolut der Wahnsinn! Pure Action, "
    "jeder Move sitzt, ich kann das selbst kaum glauben. Wenn du sowas auch drauf "
    "hast, lass ein Like da und folg fuer mehr Roblox-Highlights!",

    "Achtung Leute! {topic} – du wirst nicht glauben was hier gerade passiert. "
    "Ein Move, eine Entscheidung, und alles steht auf dem Spiel. Schau genau hin, "
    "denn solche Momente siehst du nicht jeden Tag. Folg mir fuer noch mehr Action!",

    "99 Prozent der Spieler kriegen das nicht hin. {topic} und ich war live dabei. "
    "Adrenalin pur, das Herz auf Hochtouren. Wenn du das auch erlebt hast, "
    "Kommentar drunter – und folg fuer mehr verrueckte Roblox-Momente!",

    "Alter, das musst du dir ansehen! {topic} – komplett unerwartet, komplett wild. "
    "Ich hab gedacht das wars, aber dann kam alles anders. Like wenn du auch "
    "schon mal so eine Situation hattest und folg mir fuer mehr!",
]


def fallback_template_script(topic: str) -> str:
    return random.choice(_SCRIPT_TEMPLATES).format(topic=topic.strip() or "ein krasser Roblox Moment")


def generate_script(topic: str, cfg: "Config", target_seconds: float = 30.0,
                    on_step=None) -> str:
    """Top-level script generator. Just Gemini for now; falls through to the
    template if Gemini isn't configured or rate-limits the caller."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)
    if cfg.gemini_api_key:
        log(f"      script via Gemini ({cfg.gemini_model})")
        return generate_script_via_gemini(topic, cfg, target_seconds)
    raise RuntimeError("no script backend configured (gemini_api_key missing)")


def generate_script_via_gemini(topic: str, cfg: Config, target_seconds: float = 30.0) -> str:
    if not cfg.gemini_api_key:
        raise RuntimeError("topic given but gemini_api_key missing in config (and GEMINI_API_KEY env not set)")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    target_low = max(10, int(target_seconds - 3))
    target_high = int(target_seconds + 3)
    words_low = int(target_seconds * 2.0)
    words_high = int(target_seconds * 2.6)
    prompt_text = SCRIPT_PROMPT.format(
        topic=topic, target_low=target_low, target_high=target_high,
        words_low=words_low, words_high=words_high,
    )
    body = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.9,
            "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    data = _gemini_post(url, {"key": cfg.gemini_api_key}, body)
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


def make_silent_track(duration: float, out_path: Path) -> Path:
    """Generate a silent mp3 of the given duration. Used when the user runs
    a short without a voiceover so downstream music/SFX mixing still has a
    base track to overlay onto."""
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", f"{max(0.5, duration):.2f}",
        "-c:a", "libmp3lame", "-q:a", "4",
        str(out_path),
    ])
    return out_path


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


def trim_leading_silence(in_path: Path, out_path: Path,
                         threshold_db: float = -45.0,
                         keep_seconds: float = 0.05) -> Path:
    """Strip ElevenLabs' leading dead air so the voiceover starts at t~=0."""
    run([
        "ffmpeg", "-y", "-i", str(in_path),
        "-af", f"silenceremove=start_periods=1:start_silence={keep_seconds}:start_threshold={threshold_db}dB",
        "-c:a", "libmp3lame", "-q:a", "4",
        str(out_path),
    ])
    return out_path


_MUSIC_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}


def pick_music_track(music_dir: str, specific: str = "") -> Path | None:
    """Pick a music file from a folder. Specific filename wins, else random."""
    if not music_dir:
        return None
    d = Path(music_dir).expanduser()
    if not d.is_dir():
        return None
    if specific:
        p = Path(specific).expanduser()
        if not p.is_absolute():
            p = d / specific
        if p.is_file():
            return p
    candidates = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in _MUSIC_EXTS]
    if not candidates:
        return None
    return random.choice(candidates)


def _media_duration(path: Path) -> float:
    """Return duration in seconds via ffprobe, or 0 on failure."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def find_loudest_music_offset(music_path: Path, voice_duration: float,
                              window: float = 3.0, step: float = 8.0) -> float:
    """Sample loudness in `window`-sec chunks across the track and return the
    start offset that has the highest mean volume and still leaves at least
    `voice_duration` seconds before the end (so no mid-mix loop). Falls back to 0."""
    duration = _media_duration(music_path)
    if duration <= 0 or duration <= voice_duration + 5:
        return 0.0
    max_start = max(0.0, duration - voice_duration - 1.0)
    if max_start <= 0:
        return 0.0
    starts = []
    t = 0.0
    while t <= max_start + 0.01:
        starts.append(round(t, 2))
        t += step
    if not starts:
        return 0.0
    vol_re = re.compile(r"mean_volume:\s*([-\d.]+)\s*dB")
    scored: list[tuple[float, float]] = []  # (volume_dB, offset)
    for s in starts:
        try:
            proc = subprocess.run(
                ["ffmpeg", "-ss", f"{s}", "-t", f"{window}",
                 "-i", str(music_path),
                 "-af", "volumedetect", "-vn", "-f", "null", "-"],
                capture_output=True, text=True,
            )
            m = vol_re.search(proc.stderr)
            if m:
                scored.append((float(m.group(1)), s))
        except Exception:
            continue
    if not scored:
        return 0.0
    scored.sort(key=lambda x: x[0], reverse=True)
    # Pick randomly from the top 3 loudest windows for variety between runs.
    top = scored[:3]
    return random.choice(top)[1]


def mix_voice_with_music(voice_path: Path, music_path: Path, volume_pct: float,
                         out_path: Path, start_offset: float = 0.0) -> Path:
    """Loop music under voice at given volume (%). Output ends with the voice.
    `start_offset` skips into the music track before mixing."""
    pct = max(0.0, min(volume_pct, 100.0)) / 100.0
    # Quadratic taper: matches perceived loudness so low slider values are actually quiet.
    # e.g. 3% -> 0.0009 (~-60dB), 10% -> 0.01 (~-40dB), 30% -> 0.09 (~-21dB).
    vol = pct * pct
    music_args = ["-stream_loop", "-1"]
    if start_offset > 0.05:
        music_args = ["-ss", f"{start_offset:.2f}", "-stream_loop", "-1"]
    run([
        "ffmpeg", "-y",
        "-i", str(voice_path),
        *music_args, "-i", str(music_path),
        "-filter_complex",
        f"[1:a]volume={vol:.3f}[bgm];"
        f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]",
        "-map", "[mix]",
        "-c:a", "libmp3lame", "-q:a", "4",
        str(out_path),
    ])
    return out_path


def list_sfx_files(sfx_dir: str) -> list[Path]:
    if not sfx_dir:
        return []
    d = Path(sfx_dir).expanduser()
    if not d.is_dir():
        return []
    return sorted(f for f in d.iterdir() if f.is_file() and f.suffix.lower() in _MUSIC_EXTS)


def pick_sfx_track(sfx_dir: str, specific: str = "") -> Path | None:
    """Pick a specific SFX or a random one from the folder."""
    if not sfx_dir:
        return None
    d = Path(sfx_dir).expanduser()
    if not d.is_dir():
        return None
    if specific:
        p = Path(specific).expanduser()
        if not p.is_absolute():
            p = d / specific
        if p.is_file():
            return p
    tracks = list_sfx_files(sfx_dir)
    return random.choice(tracks) if tracks else None


def mix_voice_with_sfx(voice_path: Path, sfx_events: list, out_path: Path) -> Path:
    """sfx_events: list of (time_seconds: float, sfx_path: Path, volume_pct: float)."""
    if not sfx_events:
        return voice_path
    cmd = ["ffmpeg", "-y", "-i", str(voice_path)]
    for _, sfx_path, _ in sfx_events:
        cmd += ["-i", str(sfx_path)]

    parts = []
    sfx_labels = []
    for i, (t, _, vol_pct) in enumerate(sfx_events):
        vol = max(0.0, min(vol_pct / 100.0, 1.5))
        delay_ms = max(0, int(t * 1000))
        parts.append(
            f"[{i + 1}:a]volume={vol:.3f},adelay={delay_ms}|{delay_ms}[s{i}]"
        )
        sfx_labels.append(f"[s{i}]")

    n_total = 1 + len(sfx_events)
    all_inputs = "[0:a]" + "".join(sfx_labels)
    parts.append(
        f"{all_inputs}amix=inputs={n_total}:duration=first:normalize=0:dropout_transition=0[mix]"
    )

    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "[mix]",
        "-c:a", "libmp3lame", "-q:a", "4",
        str(out_path),
    ]
    run(cmd)
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


def pick_multi_clips(source: Path, total_seconds: float, n_segments: int,
                     out_path: Path) -> Path:
    """Pick n non-overlapping random segments distributed across the source and stitch them."""
    if n_segments <= 1:
        return pick_clip(source, total_seconds, out_path)

    total = probe_duration(source)
    margin = 5.0
    usable = max(0.0, total - 2 * margin)
    seg_dur = total_seconds / n_segments

    # need enough room: each bucket must be at least seg_dur wide
    if usable < n_segments * seg_dur * 1.2:
        return pick_clip(source, total_seconds, out_path)

    bucket = usable / n_segments
    segments = []
    for i in range(n_segments):
        b_start = margin + i * bucket
        b_end = b_start + bucket
        latest = max(b_start, b_end - seg_dur)
        s = random.uniform(b_start, latest) if latest > b_start else b_start
        segments.append((s, seg_dur))

    return _extract_and_concat(source, segments, out_path)


def _extract_and_concat(source: Path, segments: list[tuple[float, float]],
                        out_path: Path) -> Path:
    """Cut each (start, dur) segment from source, re-encode with matching params, concat."""
    work_dir = out_path.parent
    seg_paths = []
    for i, (s, d) in enumerate(segments):
        seg_path = work_dir / f"seg_{i:02d}.mp4"
        run([
            "ffmpeg", "-y",
            "-ss", f"{s:.2f}", "-i", str(source),
            "-t", f"{d:.2f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
            "-r", "60",
            str(seg_path),
        ])
        seg_paths.append(seg_path)

    concat_list = work_dir / "concat.txt"
    concat_list.write_text("\n".join(f"file '{p.name}'" for p in seg_paths), encoding="utf-8")
    run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        str(out_path),
    ], cwd=str(work_dir))
    return out_path


def _parse_time(s: str) -> float:
    """Parse a single timestamp into float seconds. Accepts:
      'MM:SS', 'MM:SS.fff', 'HH:MM:SS', 'HH:MM:SS.fff', or raw seconds ('78')."""
    s = s.strip().replace(",", ".")
    if not s:
        raise ValueError("empty timestamp")
    parts = s.split(":")
    try:
        if len(parts) == 1:
            return float(parts[0])
        if len(parts) == 2:
            return float(parts[0]) * 60.0 + float(parts[1])
        if len(parts) == 3:
            return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
    except ValueError as e:
        raise ValueError(f"unrecognized time {s!r}: {e}") from e
    raise ValueError(f"too many ':' in time {s!r}")


def parse_time_ranges(text: str) -> list:
    """Parse multi-line text of time ranges. One range per line, format:
      'START-END' where START/END are 'MM:SS', 'HH:MM:SS', or raw seconds.
    Returns [(start_sec, duration_sec), ...]. Empty lines and # comments
    are skipped. Multiple separator chars accepted (-, –, —, ' to ', ' bis ')."""
    out = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        sep_used = None
        for sep in [" - ", " – ", " — ", " bis ", " to ", "–", "—", "-"]:
            if sep in line:
                sep_used = sep
                break
        if sep_used is None:
            raise ValueError(f"no range separator in line: {raw_line!r}")
        start_s, _, end_s = line.partition(sep_used)
        start = _parse_time(start_s)
        end = _parse_time(end_s)
        if end <= start:
            raise ValueError(f"end <= start in range {raw_line!r}")
        out.append((start, end - start))
    if not out:
        raise ValueError("no valid time ranges parsed")
    return out


def pick_manual_clips(source: Path, ranges: list,
                      out_path: Path) -> Path:
    """Extract user-specified (start, duration) ranges and stitch them in order."""
    return _extract_and_concat(source, ranges, out_path)


def analyze_loudness(source: Path, work_dir: Path,
                     window_seconds: float = 1.0) -> list[tuple[float, float]]:
    """Return [(time, rms_db), ...] for each window of audio in the source."""
    out_file = work_dir / "loudness.txt"
    sample_rate = 48000
    chunk_samples = int(sample_rate * window_seconds)
    try:
        run([
            "ffmpeg", "-y", "-i", str(source),
            "-vn",
            "-af",
            f"aresample={sample_rate},"
            f"asetnsamples=n={chunk_samples}:p=0,"
            f"astats=metadata=1:reset=1,"
            f"ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:"
            f"file={out_file.as_posix()}",
            "-f", "null", "-",
        ])
    except subprocess.CalledProcessError:
        return []
    if not out_file.exists():
        return []
    samples = []
    current_time = None
    for line in out_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("frame:"):
            for tok in line.split():
                if tok.startswith("pts_time:"):
                    try:
                        current_time = float(tok.split(":", 1)[1])
                    except ValueError:
                        current_time = None
        elif "RMS_level" in line and "=" in line:
            val = line.split("=", 1)[1].strip()
            if val in ("-inf", "nan", "inf", ""):
                current_time = None
                continue
            try:
                rms = float(val)
                if current_time is not None:
                    samples.append((current_time, rms))
            except ValueError:
                pass
            current_time = None
    return samples


def pick_loud_clip(source: Path, target_seconds: float, out_path: Path,
                   work_dir: Path | None = None) -> Path:
    """Pick a single window centered on the loudest sub-window."""
    wd = work_dir or out_path.parent
    samples = analyze_loudness(source, wd)
    total = probe_duration(source)
    margin = 5.0
    if not samples or total <= target_seconds + 2 * margin:
        return pick_clip(source, target_seconds, out_path)
    eligible = [
        (t, r) for t, r in samples
        if margin + target_seconds / 2 <= t <= total - margin - target_seconds / 2
    ]
    if not eligible:
        return pick_clip(source, target_seconds, out_path)
    peak_t, _ = max(eligible, key=lambda x: x[1])
    start = max(margin, peak_t - target_seconds * 0.4)  # peak ~40% in
    start = min(start, total - target_seconds - margin)
    run([
        "ffmpeg", "-y",
        "-ss", f"{start:.2f}", "-i", str(source),
        "-t", f"{target_seconds:.2f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k",
        str(out_path),
    ])
    return out_path


def pick_loud_multi_clips(source: Path, total_seconds: float, n_segments: int,
                          out_path: Path) -> Path:
    """Pick top-N loud peaks with min separation, sort by time, extract + concat."""
    if n_segments <= 1:
        return pick_loud_clip(source, total_seconds, out_path)

    work_dir = out_path.parent
    samples = analyze_loudness(source, work_dir)
    total = probe_duration(source)
    margin = 5.0
    seg_dur = total_seconds / n_segments

    if not samples or total <= n_segments * seg_dur * 1.3:
        return pick_multi_clips(source, total_seconds, n_segments, out_path)

    # pre-roll: start each cut a bit before the peak so the build-up is visible
    pre_roll = min(seg_dur * 0.4, 2.0)
    min_gap = seg_dur + 2.0  # gap between cut starts so no overlap

    eligible = [
        (t, r) for t, r in samples
        if margin + pre_roll <= t and t + (seg_dur - pre_roll) <= total - margin
    ]
    if not eligible:
        return pick_multi_clips(source, total_seconds, n_segments, out_path)

    eligible.sort(key=lambda x: x[1], reverse=True)
    picked: list[float] = []
    for t, _ in eligible:
        start = t - pre_roll
        if all(abs(start - p) >= min_gap for p in picked):
            picked.append(start)
            if len(picked) >= n_segments:
                break

    if len(picked) < n_segments:
        return pick_multi_clips(source, total_seconds, n_segments, out_path)

    picked.sort()
    segments = [(s, seg_dur) for s in picked]
    return _extract_and_concat(source, segments, out_path)


def _extract_thumbnail(source: Path, at_seconds: float, out_path: Path,
                       width: int = 480) -> bool:
    """Single ffmpeg seek+frame grab. Returns True on success."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{at_seconds:.2f}", "-i", str(source),
             "-vframes", "1", "-q:v", "5", "-vf", f"scale={width}:-1",
             str(out_path)],
            check=True, capture_output=True,
        )
        return out_path.is_file() and out_path.stat().st_size > 0
    except Exception:
        return False


def detect_subject_x_position(source: Path, cfg, n_samples: int = 10,
                              on_step=None) -> float:
    """Ask Cloudflare Llama Vision where the main subject is horizontally.
    Samples n_samples frames evenly across the source video and averages.
    Returns 0.0-1.0 where 0 = far left, 0.5 = centered, 1.0 = far right.
    Returns 0.5 (centered) on any failure."""
    def log(msg: str) -> None:
        if on_step:
            try:
                on_step(msg)
            except Exception:
                pass
        else:
            print(msg)

    if not cfg.cloudflare_account_id or not cfg.cloudflare_api_token:
        log("      auto-reframe: cloudflare creds missing, using centered crop")
        return 0.5
    src_dur = _media_duration(source)
    if src_dur <= 1.0:
        return 0.5

    work = source.parent
    work.mkdir(parents=True, exist_ok=True)
    sample_times = [src_dur * (i + 0.5) / n_samples for i in range(n_samples)]
    prompt = (
        "This is a frame from a wide landscape video. It will be cropped to a "
        "narrow vertical 9:16 portrait. Pick the horizontal position that "
        "shows the MOST PEOPLE / LARGEST FACE.\n\n"
        "Reply with EXACTLY ONE of these five integers (no other values):\n"
        "  10 = a person is on the FAR LEFT side of the frame\n"
        "  30 = a person is on the LEFT side\n"
        "  50 = ONE person is centered AND no other people visible\n"
        "  70 = a person is on the RIGHT side\n"
        "  90 = a person is on the FAR RIGHT side\n\n"
        "IMPORTANT: If there are TWO OR MORE people spread across the frame "
        "(podcast, interview, two speakers), DO NOT answer 50 — that crops "
        "the empty middle. Pick 30 or 70 (or 10/90) for the side with the "
        "most prominent face. 50 is ONLY for a single subject dead-centered "
        "or no people at all.\n\n"
        "Reply with just one of: 10, 30, 50, 70, 90. Nothing else."
    )
    num_re = re.compile(r"\d+")
    positions: list[float] = []  # 0-100 from vision LLM
    direct_offsets: list[float] = []  # 0-1 from face detection
    face_label = ""
    no_face_count = 0
    first_err = ""
    have_face_detector = _face_detector_available()
    for i, t in enumerate(sample_times):
        thumb = work / f"reframe_sample_{i}.jpg"
        if not _extract_thumbnail(source, t, thumb, width=640):
            continue
        # Face detection first
        face_res = detect_face_crop_offset(thumb)
        if face_res is not None:
            direct_offsets.append(face_res[0])
            face_label = face_res[1]
            continue
        if have_face_detector:
            # Face detector ran and found nothing — trust it, don't ask the LLM.
            no_face_count += 1
            continue
        # No local face detector at all — LLM fallback
        text, err = _vision_score_cf_first(thumb, prompt, cfg)
        if err:
            if not first_err:
                first_err = err
            continue
        m = num_re.search(text)
        if not m:
            if not first_err:
                first_err = f"unparseable: {text!r}"
            continue
        val = float(m.group(0))
        if 0 <= val <= 100:
            positions.append(val)

    # If the face detector found at least one face, use those (exact pixels).
    if direct_offsets:
        direct_offsets.sort()
        median_off = direct_offsets[len(direct_offsets) // 2]
        log(f"      auto-reframe: {face_label} detected face at crop@{median_off*100:.0f}% (median of {len(direct_offsets)}/{n_samples} samples)")
        return median_off

    # Face detector ran on all samples and found NO face anywhere —
    # this is the "video has no people" case. Stay centered, don't ask
    # the LLM to guess (it will, and it will be wrong).
    if have_face_detector and no_face_count > 0:
        log(f"      auto-reframe: no faces detected in {no_face_count}/{n_samples} samples, staying centered")
        return 0.5

    if not positions:
        if first_err:
            log(f"      auto-reframe: cloudflare error: {first_err[:200]}")
        log("      auto-reframe: no usable responses, using centered crop")
        return 0.5

    # Bucket each sample into 0/25/50/75/100, pick the bucket with most votes.
    # Then: if 50 has the most votes BUT any non-50 bucket got votes too, the
    # frame likely shows multiple subjects spread out (the model defaulted to
    # "centered" out of indecision). Force a side pick in that case.
    buckets = {10: 0, 30: 0, 50: 0, 70: 0, 90: 0}
    bucket_keys = list(buckets.keys())
    for p in positions:
        nearest = min(bucket_keys, key=lambda b: abs(b - p))
        buckets[nearest] += 1
    best = max(bucket_keys, key=lambda b: buckets[b])
    if best == 50:
        non_50 = {k: v for k, v in buckets.items() if k != 50 and v > 0}
        if non_50:
            best = max(non_50, key=non_50.get)
    log(f"      auto-reframe: subject at ~{best}% from left (samples: {positions}, buckets: {buckets})")
    return _subject_pct_to_crop_offset(best)


_CF_VISION_AGREED: set = set()


def _cloudflare_accept_vision_agreement(cfg) -> str:
    """Meta requires a one-time license acceptance for the Llama 3.2 Vision
    model on Cloudflare Workers AI. Send the magic 'agree' prompt to record
    consent for this account. Idempotent. Returns '' on success or an error
    string."""
    key = cfg.cloudflare_account_id
    if key in _CF_VISION_AGREED:
        return ""
    model = "@cf/meta/llama-3.2-11b-vision-instruct"
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{cfg.cloudflare_account_id}/ai/run/{model}"
    )
    headers = {
        "Authorization": f"Bearer {cfg.cloudflare_api_token}",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(url, headers=headers, json={"prompt": "agree"}, timeout=30)
    except Exception as e:
        return f"agreement request error: {e}"
    # Cloudflare returns 403 with "Thank you for agreeing" on successful
    # acceptance (quirky API). Treat that as success.
    if "Thank you for agreeing" in r.text:
        _CF_VISION_AGREED.add(key)
        return ""
    if r.status_code >= 400:
        return f"agreement HTTP {r.status_code}: {r.text[:200]}"
    _CF_VISION_AGREED.add(key)
    return ""


_MP_FACE_DETECTOR = None  # lazy-initialized singleton
_IF_FACE_APP = None  # InsightFace FaceAnalysis singleton, False = unavailable
_YOLO_FACE_MODEL = None  # Ultralytics YOLOv8-face singleton, False = unavailable
_FACE_LOG_PRINTED = False  # log which detector we ended up with, once


_YOLO_FACE_WEIGHTS_URL = (
    "https://github.com/akanametov/yolo-face/releases/download/v0.0.0/yolov11n-face.pt"
)


def _get_yolo_face_detector():
    """Lazy-init Ultralytics YOLO face detector. Downloads yolov11n-face.pt
    (~6MB) to ~/.cache/yolo-face on first call. Returns None if ultralytics
    isn't installed or the download fails."""
    global _YOLO_FACE_MODEL, _FACE_LOG_PRINTED
    if _YOLO_FACE_MODEL is False:
        return None
    if _YOLO_FACE_MODEL is not None:
        return _YOLO_FACE_MODEL
    try:
        from ultralytics import YOLO
    except Exception:
        _YOLO_FACE_MODEL = False
        return None
    try:
        cache_dir = Path.home() / ".cache" / "yolo-face"
        cache_dir.mkdir(parents=True, exist_ok=True)
        weights = cache_dir / "yolov11n-face.pt"
        if not weights.exists() or weights.stat().st_size < 100_000:
            r = requests.get(_YOLO_FACE_WEIGHTS_URL, timeout=120)
            r.raise_for_status()
            weights.write_bytes(r.content)
        _YOLO_FACE_MODEL = YOLO(str(weights))
    except Exception:
        _YOLO_FACE_MODEL = False
        return None
    if not _FACE_LOG_PRINTED:
        print("      face detection: using YOLOv11-face (ultralytics)")
        _FACE_LOG_PRINTED = True
    return _YOLO_FACE_MODEL


def _get_insightface():
    """Lazy-init InsightFace's FaceAnalysis (detection only, RetinaFace).
    Returns None if insightface / onnxruntime / model download fail."""
    global _IF_FACE_APP, _FACE_LOG_PRINTED
    if _IF_FACE_APP is False:
        return None
    if _IF_FACE_APP is not None:
        return _IF_FACE_APP
    try:
        from insightface.app import FaceAnalysis
    except Exception:
        _IF_FACE_APP = False
        return None
    # CUDAExecutionProvider works on Windows with the nvidia-cudnn wheel we
    # already pulled for faster-whisper; CPU is the safe fallback.
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    try:
        app = FaceAnalysis(
            name="buffalo_l",
            allowed_modules=["detection"],  # skip recognition/landmark models
            providers=providers,
        )
        # ctx_id=0 picks the first GPU, falls back to CPU if CUDA provider fails.
        app.prepare(ctx_id=0, det_size=(640, 640))
    except Exception:
        try:
            app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection"],
                               providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=-1, det_size=(640, 640))
        except Exception:
            _IF_FACE_APP = False
            return None
    _IF_FACE_APP = app
    if not _FACE_LOG_PRINTED:
        print("      face detection: using InsightFace (buffalo_l)")
        _FACE_LOG_PRINTED = True
    return _IF_FACE_APP


def _get_mediapipe_detector():
    """Lazy-load MediaPipe's face detector as fallback."""
    global _MP_FACE_DETECTOR, _FACE_LOG_PRINTED
    if _MP_FACE_DETECTOR is False:
        return None
    if _MP_FACE_DETECTOR is not None:
        return _MP_FACE_DETECTOR
    try:
        import mediapipe as mp
    except Exception:
        _MP_FACE_DETECTOR = False
        return None
    _MP_FACE_DETECTOR = mp.solutions.face_detection.FaceDetection(
        model_selection=1, min_detection_confidence=0.4
    )
    if not _FACE_LOG_PRINTED:
        print("      face detection: using MediaPipe (InsightFace unavailable)")
        _FACE_LOG_PRINTED = True
    return _MP_FACE_DETECTOR


def _detect_face_center_x(thumb_path: Path):
    """Return (face_center_x_normalized, source_label) of the largest face
    in `thumb_path`, or None if no face. Detector priority: YOLOv8-face ->
    InsightFace -> MediaPipe."""
    try:
        import cv2
    except Exception:
        return None
    img = cv2.imread(str(thumb_path))
    if img is None:
        return None
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return None

    # YOLOv8-face path (best accuracy/speed on GPU, requires ultralytics)
    yolo = _get_yolo_face_detector()
    if yolo:
        try:
            results = yolo(img, verbose=False, conf=0.35)
        except Exception:
            results = []
        # ultralytics returns a list of Results; each has .boxes (xyxy tensor)
        boxes_all = []
        for r in results or []:
            try:
                for b in r.boxes:
                    x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].cpu().tolist()]
                    boxes_all.append((x1, y1, x2, y2))
            except Exception:
                continue
        if boxes_all:
            best = max(boxes_all, key=lambda bb: (bb[2] - bb[0]) * (bb[3] - bb[1]))
            center_x_px = (best[0] + best[2]) / 2.0
            return (center_x_px / w, "yolo")

    # InsightFace path
    app = _get_insightface()
    if app:
        try:
            faces = app.get(img)
        except Exception:
            faces = []
        if faces:
            best = max(faces, key=lambda f: (
                max(0.0, float(f.bbox[2] - f.bbox[0])) *
                max(0.0, float(f.bbox[3] - f.bbox[1]))
            ))
            x1, _, x2, _ = best.bbox
            center_x_px = (float(x1) + float(x2)) / 2.0
            return (center_x_px / w, "insightface")

    # MediaPipe fallback
    fd = _get_mediapipe_detector()
    if fd:
        try:
            results = fd.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        except Exception:
            results = None
        detections = getattr(results, "detections", None) or []
        if detections:
            best = max(detections, key=lambda d: (
                max(0.0, d.location_data.relative_bounding_box.width) *
                max(0.0, d.location_data.relative_bounding_box.height)
            ))
            bb = best.location_data.relative_bounding_box
            return (bb.xmin + bb.width / 2.0, "mediapipe")

    return None


def detect_face_crop_offset(thumb_path: Path, source_aspect: float = 16.0 / 9.0):
    """Compute the 0..1 crop offset that centers the largest detected face
    in a 9:16 portrait crop. Returns (offset, detector_label) or None when
    no face is detected / source is already (near-)portrait."""
    result = _detect_face_center_x(thumb_path)
    if result is None:
        return None
    face_center_x, label = result
    r = 9.0 / (16.0 * source_aspect)
    if r >= 0.99:
        return (0.5, label)
    offset = (face_center_x - r / 2.0) / (1.0 - r)
    return (max(0.0, min(1.0, offset)), label)


def _subject_pct_to_crop_offset(subject_pct: float) -> float:
    """Map the model's 5-bucket answer (10/30/50/70/90) to an aggressive crop
    offset that biases side picks toward the edges. The model tends to call
    "30" for any speaker sitting in the left half (could be x=200 or x=550),
    and 0.25 offset only centers x≈630 — too far right for a host at x=350.
    Use a curve that pushes 30 -> 0.15 and 70 -> 0.85 so the speaker actually
    lands near the middle of the 9:16 window in podcast layouts:

      10 -> 0.00  (left edge)
      30 -> 0.15  (biased left)
      50 -> 0.50  (centered)
      70 -> 0.85  (biased right)
      90 -> 1.00  (right edge)

    Piecewise linear between bucket points."""
    pct = max(0.0, min(100.0, float(subject_pct)))
    pts = [(0.0, 0.0), (10.0, 0.0), (30.0, 0.15), (50.0, 0.50),
           (70.0, 0.85), (90.0, 1.0), (100.0, 1.0)]
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        if x1 <= pct <= x2:
            if x2 == x1:
                return y1
            t = (pct - x1) / (x2 - x1)
            return y1 + t * (y2 - y1)
    return 0.5
    """Send one image to Gemini and return (text, err)."""
    import base64
    if not cfg.gemini_api_key:
        return ("", "Gemini API key not set")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    b64 = base64.b64encode(thumb_path.read_bytes()).decode("ascii")
    body = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 16,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        data = _gemini_post(url, {"key": cfg.gemini_api_key}, body)
    except RuntimeError as e:
        return ("", str(e))
    try:
        candidate = data["candidates"][0]
        parts_resp = candidate.get("content", {}).get("parts", []) or []
        text = "\n".join(p.get("text", "") for p in parts_resp if not p.get("thought")).strip()
        return (text, "")
    except Exception as e:
        return ("", f"parse error: {e}")


def _vision_score(thumb_path: Path, prompt: str, cfg) -> tuple:
    """Try Gemini first (cheap, multi-image capable, high free-tier limit),
    fall back to Cloudflare Llama Vision (free tier neurons). Returns (text, err)."""
    gemini_err = ""
    if cfg.gemini_api_key:
        text, err = _gemini_vision_score(thumb_path, prompt, cfg)
        if not err and text:
            return (text, "")
        gemini_err = err or "empty response"
    if cfg.cloudflare_account_id and cfg.cloudflare_api_token:
        text, err = _cloudflare_vision_score(thumb_path, prompt, cfg)
        if not err and text:
            return (text, "")
        return ("", f"gemini={gemini_err[:80]}; cloudflare={err[:80]}")
    return ("", gemini_err or "no vision backend configured")


def _vision_score_cf_first(thumb_path: Path, prompt: str, cfg) -> tuple:
    """Cloudflare Llama Vision first, Gemini fallback. Used for tasks where
    Cloudflare's spatial reasoning has been more reliable in practice
    (auto-reframe / subject position detection)."""
    cf_err = ""
    if cfg.cloudflare_account_id and cfg.cloudflare_api_token:
        text, err = _cloudflare_vision_score(thumb_path, prompt, cfg)
        if not err and text:
            return (text, "")
        cf_err = err or "empty response"
    if cfg.gemini_api_key:
        text, err = _gemini_vision_score(thumb_path, prompt, cfg)
        if not err and text:
            return (text, "")
        return ("", f"cloudflare={cf_err[:80]}; gemini={err[:80]}")
    return ("", cf_err or "no vision backend configured")


def _cloudflare_vision_score(thumb_path: Path, prompt: str, cfg) -> tuple:
    """Send one image to Cloudflare Llama 3.2 Vision and return (text, err).
    Uses the OpenAI-style messages format with base64 data URL (most reliable
    across Cloudflare Workers AI versions). On the Meta licensing 403, auto-
    submit the 'agree' acceptance and retry once."""
    import base64
    model = "@cf/meta/llama-3.2-11b-vision-instruct"
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{cfg.cloudflare_account_id}/ai/run/{model}"
    )
    headers = {
        "Authorization": f"Bearer {cfg.cloudflare_api_token}",
        "Content-Type": "application/json",
    }
    b64 = base64.b64encode(thumb_path.read_bytes()).decode("ascii")
    body = {
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ]},
        ],
        "max_tokens": 16,
        "temperature": 0.1,
    }
    for attempt in range(2):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=60)
        except Exception as e:
            return ("", f"request error: {e}")
        if r.status_code == 403 and "Model Agreement" in r.text and attempt == 0:
            agree_err = _cloudflare_accept_vision_agreement(cfg)
            if agree_err:
                return ("", f"could not accept Meta license: {agree_err}")
            continue  # retry
        if r.status_code >= 400:
            return ("", f"HTTP {r.status_code}: {r.text[:240]}")
        try:
            data = r.json()
        except Exception:
            return ("", f"non-json response: {r.text[:240]}")
        if not data.get("success", True):
            return ("", f"api error: {str(data.get('errors'))[:240]}")
        result = data.get("result") or {}
        if isinstance(result, dict):
            text = (
                result.get("response")
                or result.get("description")
                or ""
            )
            choices = result.get("choices")
            if not text and isinstance(choices, list) and choices:
                msg = (choices[0] or {}).get("message") or {}
                text = msg.get("content") or ""
        else:
            text = ""
        return (str(text).strip(), "")
    return ("", "retry loop exhausted")


def _face_detector_available() -> bool:
    """True if any local face detector (YOLO / InsightFace / MediaPipe) is
    loaded. When one is available, "no face" is an authoritative answer —
    we should stay centered instead of falling back to the vision LLM which
    has no way to say 'no people here' and just guesses a side."""
    return bool(
        _get_yolo_face_detector()
        or _get_insightface()
        or _get_mediapipe_detector()
    )


def _detect_subject_at_time(source: Path, at_time: float, cfg,
                            sample_path: Path) -> tuple:
    """Sample ONE frame at the given time, return (offset 0-1, source_label).

    Order of trust:
      1. Face detector (InsightFace / MediaPipe). If a face is found, use it.
      2. If a face detector is loaded but found NO face -> stay centered.
         The detector is the authority; the LLM would just hallucinate a
         side for empty frames.
      3. Only if no face detector is installed at all do we ask the vision
         LLM as a last-resort guess.
    """
    if not _extract_thumbnail(source, at_time, sample_path, width=640):
        return (0.5, "centered")

    face_res = detect_face_crop_offset(sample_path)
    if face_res is not None:
        offset, label = face_res
        return (offset, label)

    if _face_detector_available():
        # Face detector ran and found nothing → trust it.
        return (0.5, "no-face")

    # No face detector installed → fall back to vision LLM.
    have_any = bool(cfg.gemini_api_key) or bool(cfg.cloudflare_account_id and cfg.cloudflare_api_token)
    if not have_any:
        return (0.5, "centered")
    prompt = (
        "This is a frame from a wide landscape video. It will be cropped to a "
        "narrow vertical 9:16 portrait. Pick the horizontal position that "
        "shows the MOST PEOPLE / LARGEST FACE.\n\n"
        "Reply with EXACTLY ONE of these five integers (no other values):\n"
        "  10 = a person is on the FAR LEFT side of the frame\n"
        "  30 = a person is on the LEFT side\n"
        "  50 = ONE person is centered AND no other people visible\n"
        "  70 = a person is on the RIGHT side\n"
        "  90 = a person is on the FAR RIGHT side\n\n"
        "IMPORTANT: If TWO OR MORE people are spread across the frame "
        "(podcast, interview), DO NOT answer 50 — pick 30 or 70 for the side "
        "with the most prominent face. 50 is ONLY for a single dead-centered "
        "subject or no people visible.\n\n"
        "Reply with just one of: 10, 30, 50, 70, 90. Nothing else."
    )
    text, err = _vision_score_cf_first(sample_path, prompt, cfg)
    if err:
        return (0.5, "centered")
    m = re.search(r"\d+", text)
    if not m:
        return (0.5, "centered")
    val = float(m.group(0))
    if 0 <= val <= 100:
        return (_subject_pct_to_crop_offset(val), "llm")
    return (0.5, "centered")


def detect_subjects_per_segment(clip: Path, n_segments: int, seg_dur: float,
                                cfg, on_step=None) -> list:
    """Per-segment subject detection. Returns [(segment_start_time, offset), ...].
    For each segment, samples one frame in the middle and asks the detector
    (MediaPipe face detection first, vision LLM fallback). Falls back to 0.5
    (centered) per segment if nothing usable comes back."""
    def log(msg: str) -> None:
        if on_step:
            try:
                on_step(msg)
            except Exception:
                pass
        else:
            print(msg)

    work = clip.parent
    work.mkdir(parents=True, exist_ok=True)
    offsets: list = []
    labels: list = []
    for i in range(n_segments):
        seg_start = i * seg_dur
        seg_mid = seg_start + seg_dur / 2
        sample = work / f"reframe_seg_{i:02d}.jpg"
        off, label = _detect_subject_at_time(clip, seg_mid, cfg, sample)
        offsets.append((float(seg_start), float(off)))
        labels.append(label)
    summary = ", ".join(
        f"{t:.1f}s=crop@{int(o*100)}%({lab})"
        for (t, o), lab in zip(offsets, labels)
    )
    # Aggregated counter so it's easy to see which detector handled how many.
    counts: dict = {}
    for lab in labels:
        counts[lab] = counts.get(lab, 0) + 1
    counts_str = ", ".join(f"{k}={v}" for k, v in counts.items())
    log(f"      auto-reframe per-scene ({counts_str}): {summary}")
    return offsets


def _cloudflare_pick_thumbnails(thumb_paths: list, n_pick: int, cfg,
                                on_step=None) -> list:
    """Score each thumbnail via Cloudflare Llama 3.2 Vision (free tier) and
    return the top n_pick indices sorted by score. Sequential, ~1-2s/image."""
    if not cfg.cloudflare_account_id or not cfg.cloudflare_api_token:
        raise RuntimeError("cloudflare credentials missing")
    prompt = (
        "Rate this gaming video frame's action level on a scale of 1 to 10. "
        "10 = exciting moment (combat, fall, explosion, chase, big motion, "
        "dramatic colors). 1 = boring still (empty room, menu, loading "
        "screen, idle). Respond ONLY with one integer between 1 and 10, "
        "nothing else."
    )
    num_re = re.compile(r"\d+(?:\.\d+)?")
    scores: list = []
    failures = 0
    first_err = ""
    for i, p in enumerate(thumb_paths):
        text, err = _cloudflare_vision_score(p, prompt, cfg)
        if err:
            failures += 1
            if not first_err:
                first_err = err
            scores.append((i, -1.0))
            continue
        m = num_re.search(text)
        if not m:
            failures += 1
            if not first_err:
                first_err = f"unparseable response: {text!r}"
            scores.append((i, -1.0))
            continue
        score = max(0.0, min(10.0, float(m.group(0))))
        scores.append((i, score))
    if failures >= len(thumb_paths):
        raise RuntimeError(
            f"all {failures} Cloudflare vision calls failed. First error: {first_err}"
        )
    if failures and on_step:
        try:
            on_step(f"      AI pick: {failures}/{len(thumb_paths)} cloudflare calls failed: {first_err[:160]}")
        except Exception:
            pass
    scores.sort(key=lambda s: (-s[1], s[0]))
    return [i for i, sc in scores[:n_pick] if sc >= 0]


def _gemini_pick_thumbnails(thumb_paths: list, n_pick: int, cfg) -> list:
    """Send thumbnails to Gemini and ask which N look most exciting.
    Returns indices into thumb_paths sorted by interest. Raises on failure."""
    import base64
    if not cfg.gemini_api_key:
        raise RuntimeError("Gemini API key not set")
    prompt = (
        f"Du bekommst {len(thumb_paths)} Standbilder aus einem Gaming-Video, "
        f"durchnummeriert 0 bis {len(thumb_paths) - 1} in der Reihenfolge wie sie erscheinen.\n\n"
        f"Waehle die {n_pick} Bilder, die am spannendsten / aktion-geladensten / visuell "
        f"interessantesten aussehen (Kaempfe, Stuerze, Explosionen, dramatische Momente, "
        f"grosse Bewegungen, intensive Farben). Vermeide langweilige Standbilder, leere "
        f"Raeume, Menues, Ladebildschirme.\n\n"
        f"Antworte NUR mit einem JSON-Array von genau {n_pick} Zahlen, sortiert vom "
        f"spannendsten zum am wenigsten spannenden. KEINE Erklaerung, KEIN Markdown."
    )
    parts = [{"text": prompt}]
    for p in thumb_paths:
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 256,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    data = _gemini_post(url, {"key": cfg.gemini_api_key}, body)
    candidate = data["candidates"][0]
    parts_resp = candidate.get("content", {}).get("parts", []) or []
    text = "\n".join(p.get("text", "") for p in parts_resp if not p.get("thought")).strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:].strip()
    s_idx, e_idx = text.find("["), text.rfind("]")
    if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
        text = text[s_idx:e_idx + 1]
    picks = json.loads(text)
    if not isinstance(picks, list):
        raise ValueError("expected JSON array")
    out = []
    for p in picks:
        try:
            ip = int(p)
        except Exception:
            continue
        if 0 <= ip < len(thumb_paths) and ip not in out:
            out.append(ip)
    if not out:
        raise ValueError("no valid indices returned")
    return out


def pick_ai_scenes(source: Path, total_seconds: float, n_segments: int,
                   out_path: Path, cfg,
                   work_dir=None, on_step=None) -> Path:
    """Sample candidate windows, extract a thumbnail per window, ask Gemini
    Vision to rank them, stitch the top N. Falls back to even/random pick if
    Gemini fails or refuses."""
    def log(msg: str) -> None:
        if on_step:
            try:
                on_step(msg)
            except Exception:
                pass
        else:
            print(msg)

    n_segments = max(1, n_segments)
    src_dur = _media_duration(source)
    if src_dur <= 0:
        log("      AI pick: cannot probe source duration, falling back to even pick")
        if n_segments <= 1:
            return pick_clip(source, total_seconds, out_path)
        return pick_multi_clips(source, total_seconds, n_segments, out_path)

    seg_dur = total_seconds / n_segments if n_segments > 1 else total_seconds
    n_candidates = min(20, max(n_segments * 3, n_segments + 5))
    buffer = 3.0
    usable = max(seg_dur, src_dur - 2 * buffer)
    if usable < n_segments * seg_dur * 1.2:
        log("      AI pick: source too short for AI pick, falling back to even pick")
        if n_segments <= 1:
            return pick_clip(source, total_seconds, out_path)
        return pick_multi_clips(source, total_seconds, n_segments, out_path)

    if n_candidates == 1:
        starts = [(src_dur - seg_dur) / 2]
    else:
        step_size = (usable - seg_dur) / (n_candidates - 1)
        starts = [buffer + i * step_size for i in range(n_candidates)]

    work = work_dir or out_path.parent
    work.mkdir(parents=True, exist_ok=True)
    thumbs: list = []
    for i, s in enumerate(starts):
        thumb_t = s + seg_dur / 2
        thumb_path = work / f"ai_thumb_{i:02d}.jpg"
        if _extract_thumbnail(source, thumb_t, thumb_path):
            thumbs.append((s, thumb_path))

    if len(thumbs) < n_segments:
        log(f"      AI pick: only {len(thumbs)} thumbnails extracted, falling back")
        if n_segments <= 1:
            return pick_clip(source, total_seconds, out_path)
        return pick_multi_clips(source, total_seconds, n_segments, out_path)

    thumb_files = [t[1] for t in thumbs]
    gemini_ready = bool(cfg.gemini_api_key)
    cf_ready = bool(cfg.cloudflare_account_id and cfg.cloudflare_api_token)
    picks: list = []
    if gemini_ready:
        log(f"      AI pick: scoring {len(thumbs)} scenes via Gemini Vision (one batched call)")
        try:
            picks = _gemini_pick_thumbnails(thumb_files, n_segments, cfg)
        except Exception as e:
            log(f"      AI pick: Gemini failed: {str(e)[:240]}")
            picks = []
    if not picks and cf_ready:
        log(f"      AI pick: trying Cloudflare Llama Vision for {len(thumbs)} scenes")
        try:
            picks = _cloudflare_pick_thumbnails(thumb_files, n_segments, cfg, on_step=log)
        except Exception as e:
            log(f"      AI pick: Cloudflare failed ({str(e)[:160]}); falling back to even pick")
            if n_segments <= 1:
                return pick_clip(source, total_seconds, out_path)
            return pick_multi_clips(source, total_seconds, n_segments, out_path)
    if not picks:
        log("      AI pick: no vision backend usable, falling back to even pick")
        if n_segments <= 1:
            return pick_clip(source, total_seconds, out_path)
        return pick_multi_clips(source, total_seconds, n_segments, out_path)

    if len(picks) < n_segments:
        existing = set(picks)
        for i in range(len(thumbs)):
            if i not in existing:
                picks.append(i)
                if len(picks) >= n_segments:
                    break

    chosen_starts = sorted([thumbs[i][0] for i in picks[:n_segments]])
    log("      AI pick: chose " + ", ".join(f"{t:.1f}s" for t in chosen_starts))

    if n_segments <= 1:
        return _extract_and_concat(source, [(chosen_starts[0], total_seconds)], out_path)
    segments = [(s, seg_dur) for s in chosen_starts]
    return _extract_and_concat(source, segments, out_path)


def _register_cuda_dlls_windows() -> list[str]:
    """faster-whisper on Windows can't find cuBLAS/cuDNN DLLs from the
    pip-installed nvidia-* wheels unless we explicitly add them to the DLL
    search path. Returns the list of directories actually registered (empty
    on non-Windows or if nothing was found)."""
    if sys.platform != "win32":
        return []
    try:
        import importlib.util
    except Exception:
        return []
    registered: list[str] = []
    for pkg in ("nvidia.cublas", "nvidia.cudnn", "nvidia.cuda_runtime", "nvidia.cuda_nvrtc"):
        try:
            spec = importlib.util.find_spec(pkg)
        except Exception:
            spec = None
        if not spec or not spec.submodule_search_locations:
            continue
        for loc in spec.submodule_search_locations:
            bin_dir = os.path.join(loc, "bin")
            if os.path.isdir(bin_dir):
                try:
                    os.add_dll_directory(bin_dir)
                    # also prepend to PATH so dependent DLLs (like cudnn's
                    # internal deps) can still be discovered by the loader
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                    registered.append(bin_dir)
                except Exception:
                    pass
    return registered


def transcribe_words_subprocess(audio_path: Path, model_name: str,
                                device: str = "auto", on_step=None):
    """Subprocess-isolated version of transcribe_words for word-level captions.
    Same crash-safe approach as transcribe_full_video: child writes results to
    a JSON sidecar before the model destructor runs, so a CUDA cleanup fault
    on long sessions can't kill the parent GUI process."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    out_json = audio_path.with_suffix(".words.json")
    if out_json.exists():
        try: out_json.unlink()
        except Exception: pass

    devices = (
        ["cuda", "cpu"] if device == "auto"
        else ["cuda"] if device == "cuda"
        else ["cpu"]
    )
    child_code = (
        "import json, os, sys, importlib.util\n"
        "if sys.platform == 'win32':\n"
        "    for pkg in ('nvidia.cublas','nvidia.cudnn','nvidia.cuda_runtime','nvidia.cuda_nvrtc'):\n"
        "        try:\n"
        "            spec = importlib.util.find_spec(pkg)\n"
        "        except Exception:\n"
        "            spec = None\n"
        "        if spec and spec.submodule_search_locations:\n"
        "            for loc in spec.submodule_search_locations:\n"
        "                b = os.path.join(loc, 'bin')\n"
        "                if os.path.isdir(b):\n"
        "                    try: os.add_dll_directory(b)\n"
        "                    except Exception: pass\n"
        "                    os.environ['PATH'] = b + os.pathsep + os.environ.get('PATH','')\n"
        "from faster_whisper import WhisperModel\n"
        "audio, model_name, device, out_json = sys.argv[1:5]\n"
        "ct = 'float16' if device == 'cuda' else 'int8'\n"
        "model = WhisperModel(model_name, device=device, compute_type=ct)\n"
        "segments, _info = model.transcribe(audio, word_timestamps=True)\n"
        "out = []\n"
        "for s in segments:\n"
        "    for w in (s.words or []):\n"
        "        out.append([float(w.start), float(w.end), str(w.word).strip()])\n"
        "with open(out_json, 'w', encoding='utf-8') as f:\n"
        "    json.dump(out, f)\n"
        "print(f'OK {len(out)} words', flush=True)\n"
    )
    last_err = None
    for dev in devices:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", child_code, str(audio_path), model_name, dev, str(out_json)],
                capture_output=True, text=True, timeout=600,
            )
        except subprocess.TimeoutExpired:
            last_err = f"timeout on {dev}"
            continue
        if out_json.exists() and out_json.stat().st_size > 2:
            try:
                arr = json.loads(out_json.read_text(encoding="utf-8"))
                words = [(float(a), float(b), str(c)) for (a, b, c) in arr]
                return words, dev
            except Exception:
                pass
        err_tail = (proc.stderr or "").strip().splitlines()[-8:]
        last_err = f"subprocess exit {proc.returncode} on {dev}: " + " | ".join(err_tail)
        log(f"      whisper-words {dev} failed: {last_err[:200]}")
    raise RuntimeError(f"transcribe_words_subprocess failed: {last_err}")


def transcribe_words(audio_path: Path, model_name: str, device: str = "auto"):
    """Transcribe to word-level timestamps. device in {"auto","cuda","cpu"}.
    "auto" tries CUDA first and silently falls back to CPU if CUDA isn't available."""
    registered = _register_cuda_dlls_windows()
    from faster_whisper import WhisperModel
    tried = []
    candidates = []
    if device == "cuda":
        candidates = [("cuda", "float16")]
    elif device == "cpu":
        candidates = [("cpu", "int8")]
    else:  # auto
        candidates = [("cuda", "float16"), ("cpu", "int8")]
    last_err = None
    for dev, ct in candidates:
        try:
            model = WhisperModel(model_name, device=dev, compute_type=ct)
            segments, _ = model.transcribe(str(audio_path), word_timestamps=True)
            words = []
            for seg in segments:
                for w in seg.words or []:
                    words.append((float(w.start), float(w.end), w.word.strip()))
            return words, dev
        except Exception as e:
            tried.append(dev)
            last_err = e
            continue
    # CUDA failed with no fallback available -> add hint to error
    hint = ""
    if sys.platform == "win32" and "cuda" in tried:
        if not registered:
            hint = (
                "\n  Hinweis: NVIDIA CUDA Runtime Pakete fehlen. Im venv ausfuehren:\n"
                "    .venv\\Scripts\\python.exe -m pip install nvidia-cublas-cu12 nvidia-cuda-runtime-cu12 \"nvidia-cudnn-cu12<10\""
            )
        else:
            hint = (
                f"\n  CUDA DLL Pfade registriert: {registered}\n"
                "  Trotzdem nicht gefunden - eventuell falsche cuDNN-Version. "
                "Versuch 'pip install --upgrade nvidia-cudnn-cu12<10' oder waehle 'CPU forcieren'."
            )
    raise RuntimeError(f"faster-whisper failed on {tried}: {last_err}{hint}")


def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _hex_to_ass_color(hex_color: str) -> str:
    """Convert '#RRGGBB' (or '#RGB') to ASS '&H00BBGGRR' (BGR, alpha 00)."""
    h = (hex_color or "").lstrip("#").strip()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return "&H00FFFFFF"
    rr, gg, bb = h[0:2], h[2:4], h[4:6]
    return f"&H00{bb}{gg}{rr}".upper()


def write_ass(words, video_w: int, video_h: int, out_path: Path,
              font_name: str = "Impact",
              font_size: int | None = None,
              primary_color: str = "#FFFFFF",
              outline_color: str = "#000000",
              outline_width: int = 5,
              hook_text: str = "",
              hook_duration: float = 3.0,
              pop_captions: bool = False,
              subscribe_overlay: bool = False,
              subscribe_text: str = "ABONNIEREN",
              total_duration: float = 0.0,
              enable_captions: bool = True) -> Path:
    """Bold center-bottom karaoke captions; styling exposed for the GUI.
    Optional hook_text shown big at the top for the first hook_duration seconds.
    pop_captions: every chunk pops in with a scale animation (TikTok-style).
    subscribe_overlay: red SUBSCRIBE button in the last ~2.5s (needs total_duration)."""
    if font_size is None or font_size <= 0:
        font_size = max(56, int(video_h * 0.048))
    primary = _hex_to_ass_color(primary_color)
    outline = _hex_to_ass_color(outline_color)
    hook_size = int(font_size * 1.4)
    sub_size = int(font_size * 1.2)
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
        f"Style: Pop, {font_name}, {int(font_size)}, {primary}, &H000000FF, {outline}, &H64000000, "
        f"1, 0, 0, 0, 100, 100, 0, 0, 1, {int(outline_width)}, 2, 2, 80, 80, 360, 1\n"
        f"Style: Hook, {font_name}, {hook_size}, &H00FFFFFF, &H000000FF, &H00000000, &H64000000, "
        f"1, 0, 0, 0, 100, 100, 0, 0, 1, {int(outline_width) + 2}, 3, 8, 60, 60, 280, 1\n"
        # Red opaque box behind text (BorderStyle=3), white text. Sits above the captions.
        f"Style: Sub, {font_name}, {sub_size}, &H00FFFFFF, &H000000FF, &H000000FF, &H000000FF, "
        f"1, 0, 0, 0, 100, 100, 0, 0, 3, 12, 0, 2, 0, 0, 250, 1\n\n"
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
    if hook_text.strip():
        ht = (hook_text.strip()
              .replace("{", "(").replace("}", ")")
              .replace("\r\n", "\n").replace("\n", "\\N"))
        dur = max(0.5, min(float(hook_duration), 10.0))
        lines.append(
            f"Dialogue: 1,{_ass_time(0.0)},{_ass_time(dur)},Hook,,0,0,0,,"
            f"{{\\fad(120,200)}}{ht}"
        )

    # TikTok-style pop animation: start scaled up, shrink to 100% over 150ms.
    pop_tag = "\\fscx125\\fscy125\\t(0,150,\\fscx100\\fscy100)" if pop_captions else ""
    if enable_captions:
        for ch in chunks:
            start, end = ch[0][0], ch[-1][1]
            text = " ".join(w[2] for w in ch).upper().replace("{", "(").replace("}", ")")
            lines.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Pop,,0,0,0,,"
                f"{{{pop_tag}\\fad(80,80)}}{text}"
            )

    if subscribe_overlay and total_duration > 1.0:
        sub_start = max(0.0, total_duration - 2.5)
        sub_end = total_duration
        sub_txt = subscribe_text.strip().upper().replace("{", "(").replace("}", ")") or "ABONNIEREN"
        lines.append(
            f"Dialogue: 2,{_ass_time(sub_start)},{_ass_time(sub_end)},Sub,,0,0,0,,"
            f"{{\\fad(180,0)\\fscx115\\fscy115\\t(0,250,\\fscx100\\fscy100)}}{sub_txt}"
        )

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def derive_image_prompt(seed_text: str) -> str:
    return (
        "vertical cartoon illustration, Roblox blocky aesthetic, vibrant saturated colors, "
        "dramatic action scene, dynamic composition, bold lighting, no text, no logos, "
        f"no real people, theme: {seed_text[:200]}"
    )


SCENE_PROMPT = """Du bekommst ein deutsches Voiceover-Skript fuer einen Roblox YouTube Short.

Teile das Skript gedanklich in {n} dramatische visuelle Schluesselmomente und schreibe pro Moment einen englischen Bild-Prompt fuer ein Text-zu-Bild-Modell.

Pflicht-Stil pro Prompt:
"vertical cartoon illustration, Roblox blocky aesthetic, vibrant saturated colors, [DEINE SZENE IN ENGLISCH], dramatic lighting, no text, no logos, no real people"

Skript:
\"\"\"
{script}
\"\"\"

Antworte NUR mit einem gueltigen JSON-Array von genau {n} Strings.
KEINE Markdown-Codeblocks, KEINE Kommentare, NUR das JSON-Array."""


def generate_scene_prompts_cloudflare(script: str, n: int, cfg: Config) -> list[str]:
    """Generate scene prompts via Cloudflare Workers AI (Llama). Raises on failure."""
    if not cfg.cloudflare_account_id or not cfg.cloudflare_api_token:
        raise RuntimeError("cloudflare credentials missing")
    model = "@cf/meta/llama-3.1-8b-instruct"
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{cfg.cloudflare_account_id}/ai/run/{model}"
    )
    headers = {
        "Authorization": f"Bearer {cfg.cloudflare_api_token}",
        "Content-Type": "application/json",
    }
    body = {
        "messages": [
            {"role": "system", "content": "You output only a JSON array of strings. No prose, no markdown, no code fences."},
            {"role": "user", "content": SCENE_PROMPT.format(n=n, script=script)},
        ],
        "max_tokens": 1024,
        "temperature": 0.85,
    }
    r = requests.post(url, headers=headers, json=body, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Cloudflare LLM {r.status_code}: {r.text[:200]}")
    data = r.json()
    if not data.get("success"):
        raise RuntimeError(f"Cloudflare LLM error: {str(data.get('errors'))[:200]}")
    text = (data.get("result") or {}).get("response", "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    prompts = json.loads(text)
    if not isinstance(prompts, list):
        raise ValueError("expected JSON array")
    prompts = [str(p).strip() for p in prompts if str(p).strip()]
    if not prompts:
        raise ValueError("empty prompt list")
    return prompts[:n]


def generate_scene_prompts(script: str, n: int, cfg: Config) -> list[str]:
    base = derive_image_prompt(script[:200])
    if cfg.gemini_api_key:
        try:
            return _scene_prompts_gemini(script, n, cfg, base)
        except _SceneGenError as e:
            print(f"      WARN: Gemini scene gen failed ({e})")
    if cfg.cloudflare_account_id and cfg.cloudflare_api_token:
        try:
            print(f"      trying Cloudflare Llama for {n} scene prompts")
            prompts = generate_scene_prompts_cloudflare(script, n, cfg)
            while len(prompts) < n:
                prompts.append(base)
            return prompts[:n]
        except Exception as e:
            print(f"      WARN: Cloudflare scene gen failed ({e}); falling back to single prompt")
    return [base] * n


class _SceneGenError(RuntimeError):
    pass


def _scene_prompts_gemini(script: str, n: int, cfg: Config, base: str) -> list[str]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": SCENE_PROMPT.format(n=n, script=script)}]}],
        "generationConfig": {
            "temperature": 0.85,
            "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        data = _gemini_post(url, {"key": cfg.gemini_api_key}, body)
    except RuntimeError as e:
        raise _SceneGenError(str(e))
    try:
        candidate = data["candidates"][0]
    except (KeyError, IndexError):
        raise _SceneGenError("no candidates in Gemini response")
    parts = candidate.get("content", {}).get("parts", []) or []
    text = "\n".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        prompts = json.loads(text)
        if not isinstance(prompts, list):
            raise ValueError("expected JSON array")
        prompts = [str(p).strip() for p in prompts if str(p).strip()]
    except Exception as e:
        raise _SceneGenError(f"parse error: {e}")
    if not prompts:
        raise _SceneGenError("empty prompt list")
    while len(prompts) < n:
        prompts.append(base)
    return prompts[:n]


def fetch_image_from_cloudflare(prompt: str, out_path: Path, cfg: Config,
                                width: int = 1024, height: int = 1024,
                                seed: int | None = None) -> Path:
    """Cloudflare Workers AI image generation. Requires account_id + api_token in cfg."""
    if not cfg.cloudflare_account_id or not cfg.cloudflare_api_token:
        raise RuntimeError("cloudflare_account_id or cloudflare_api_token missing in config")
    model = cfg.cloudflare_image_model or "@cf/black-forest-labs/flux-1-schnell"
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{cfg.cloudflare_account_id}/ai/run/{model}"
    )
    headers = {
        "Authorization": f"Bearer {cfg.cloudflare_api_token}",
        "Content-Type": "application/json",
    }
    body: dict = {"prompt": prompt, "width": width, "height": height, "num_steps": 4}
    if seed is not None:
        body["seed"] = int(seed)
    r = requests.post(url, headers=headers, json=body, timeout=120)
    if r.status_code >= 400:
        try:
            err = r.json().get("errors", [])
            msg = str(err)[:300] if err else r.text[:300]
        except Exception:
            msg = r.text[:300]
        raise RuntimeError(f"Cloudflare {r.status_code}: {msg}")
    ctype = (r.headers.get("content-type") or "").lower()
    if "image" in ctype:
        out_path.write_bytes(r.content)
        return out_path
    if "json" in ctype:
        import base64
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"Cloudflare API error: {str(data.get('errors'))[:200]}")
        result = data.get("result") or {}
        if isinstance(result, dict):
            b64 = result.get("image") or result.get("response") or ""
            if isinstance(b64, str) and b64:
                out_path.write_bytes(base64.b64decode(b64))
                return out_path
        raise RuntimeError(f"Cloudflare result shape unexpected: {str(data)[:200]}")
    # treat as raw bytes
    out_path.write_bytes(r.content)
    return out_path


def fetch_image_from_pollinations(prompt: str, out_path: Path,
                                  width: int = 1024, height: int = 1024,
                                  seed: int | None = None,
                                  retries: int = 1,
                                  backoff: tuple = (5,)) -> Path:
    encoded = urllib.parse.quote(prompt)
    # Try the newer documented endpoint first, fall back to the legacy one
    endpoints = [
        f"https://pollinations.ai/p/{encoded}",
        f"https://image.pollinations.ai/prompt/{encoded}",
    ]
    params = {
        "width": width, "height": height,
        "nologo": "true", "private": "true",
        "model": "flux",
    }
    if seed is not None:
        params["seed"] = seed

    last_err = None
    for attempt in range(retries + 1):
        for url in endpoints:
            try:
                r = requests.get(url, params=params, timeout=90)
            except requests.RequestException as e:
                last_err = f"Pollinations request error: {e}"
                continue
            ctype = (r.headers.get("content-type") or "").lower()
            if r.status_code < 400 and r.content and "image" in ctype:
                out_path.write_bytes(r.content)
                return out_path
            try:
                err_json = r.json().get("error") or {}
                msg = err_json.get("message") if isinstance(err_json, dict) else r.text
            except Exception:
                msg = r.text
            last_err = f"Pollinations {r.status_code}: {str(msg)[:160]}"
        if attempt < retries:
            wait = backoff[min(attempt, len(backoff) - 1)]
            print(f"      Pollinations all endpoints failed, retrying in {wait}s")
            time.sleep(wait)
    raise RuntimeError(last_err or "Pollinations failed (unknown)")


def _image_schedule(n: int, duration: float, image_dur: float,
                    buffer: float = 1.0) -> list[tuple[float, float]]:
    """Return [(start, end), ...] for n images evenly distributed."""
    if n <= 0:
        return []
    usable = max(image_dur, duration - 2 * buffer)
    if n == 1:
        start = (duration - image_dur) / 2
        return [(start, start + image_dur)]
    gap = (usable - image_dur) / (n - 1) if n > 1 else 0
    out = []
    for i in range(n):
        start = buffer + i * gap
        out.append((start, start + image_dur))
    return out


_TILT_ANGLES_DEG = [-3.0, 2.5, -2.0, 3.0, -2.5]


def _image_chain(idx_input: int, image_idx: int, image_dur: float, start: float,
                 overlay_w: int, angle_deg: float) -> str:
    """Filter chain for one image overlay: white border, tilt, pop-in scale, fades."""
    fade_in, fade_out, pop_dur = 0.2, 0.3, 0.25
    angle_rad = angle_deg * 3.14159265 / 180.0
    pop_start_w = int(overlay_w * 1.18)
    pop_delta = pop_start_w - overlay_w
    fade_out_start = max(0.0, image_dur - fade_out)
    return (
        f"[{idx_input}:v]"
        f"trim=duration={image_dur:.2f},setpts=PTS-STARTPTS,"
        f"format=rgba,"
        f"pad=iw+18:ih+18:9:9:color=white@0.95,"
        f"rotate={angle_rad:.4f}:c=black@0:ow=hypot(iw\\,ih):oh=ow,"
        f"scale=w='if(lt(t\\,{pop_dur:.2f})\\,{pop_start_w}-{pop_delta}*(t/{pop_dur:.2f})\\,{overlay_w})'"
        f":h=-1:eval=frame:flags=bicubic,"
        f"fade=t=in:st=0:d={fade_in}:alpha=1,"
        f"fade=t=out:st={fade_out_start:.2f}:d={fade_out}:alpha=1,"
        f"tpad=start_duration={start:.2f}:color=black@0"
        f"[img{image_idx}]"
    )


def compose_short(gameplay_clip: Path, voice_audio: Path, ass_path: Path,
                  cfg: Config, out_path: Path,
                  image_paths: list | None = None,
                  duration: float = 0.0,
                  image_duration: float = 1.5,
                  mute_source_audio: bool = False,
                  progress_bar: bool = False,
                  progress_color: str = "red",
                  progress_duration: float = 0.0,
                  crop_offset: float = 0.5) -> Path:
    image_paths = list(image_paths or [])
    if mute_source_audio:
        # ignore gameplay audio; output is just the voice/music track
        af = "[1:a]anull[a]"
    else:
        af = (
            f"[0:a]volume={cfg.ducking_db}dB[bg];"
            f"[bg][1:a]amix=inputs=2:duration=shortest:dropout_transition=0[a]"
        )
    cwd = ass_path.parent

    # 9:16 crop window with optional horizontal offset(s).
    # crop_offset can be a single float 0..1 or a list of (segment_start_seconds, offset)
    # tuples for per-scene reframe. offset 0 = left edge, 0.5 = centered, 1 = right edge.
    if isinstance(crop_offset, (list, tuple)) and crop_offset and isinstance(crop_offset[0], (list, tuple)):
        offsets = [(float(t), max(0.0, min(1.0, float(o)))) for t, o in crop_offset]
        offsets.sort(key=lambda x: x[0])
    else:
        try:
            single = max(0.0, min(1.0, float(crop_offset)))
        except (TypeError, ValueError):
            single = 0.5
        offsets = [(0.0, single)]

    if len(offsets) <= 1:
        crop_x = f"(iw-ih*9/16)*{offsets[0][1]:.3f}"
    else:
        # Build nested if(lt(t, T_next), this_offset, ...) inside out.
        crop_x = f"(iw-ih*9/16)*{offsets[-1][1]:.3f}"
        for i in range(len(offsets) - 2, -1, -1):
            next_t = offsets[i + 1][0]
            this_off = offsets[i][1]
            crop_x = (
                f"if(lt(t\\,{next_t:.2f})\\,"
                f"(iw-ih*9/16)*{this_off:.3f}\\,{crop_x})"
            )
    crop_expr = f"crop=ih*9/16:ih:x='{crop_x}':y=0"

    use_bar = bool(progress_bar and progress_duration > 0.5)
    bar_h = max(8, int(cfg.target_h * 0.008)) if use_bar else 0
    # Label the main video chain output: if we add a bar, the main chain emits
    # [vmain] and an extra overlay produces the real [v].
    main_label = "vmain" if use_bar else "v"

    cmd = ["ffmpeg", "-y", "-i", str(gameplay_clip), "-i", str(voice_audio)]

    if image_paths:
        for img in image_paths:
            cmd += ["-loop", "1", "-i", str(img)]

        overlay_w = int(cfg.target_w * 0.85)
        schedule = _image_schedule(len(image_paths), duration or 25.0, image_duration)

        parts = [
            f"[0:v]{crop_expr},scale={cfg.target_w}:{cfg.target_h}:flags=lanczos[bg0]"
        ]
        cur = "bg0"
        for i, (img_path, (start, end)) in enumerate(zip(image_paths, schedule)):
            angle = _TILT_ANGLES_DEG[i % len(_TILT_ANGLES_DEG)]
            parts.append(_image_chain(
                idx_input=2 + i, image_idx=i,
                image_dur=end - start, start=start,
                overlay_w=overlay_w, angle_deg=angle,
            ))
            nxt = f"bg{i+1}"
            parts.append(
                f"[{cur}][img{i}]overlay=(W-w)/2:(H-h)/2-120:format=auto:eof_action=pass[{nxt}]"
            )
            cur = nxt
        parts.append(f"[{cur}]subtitles={ass_path.name}[{main_label}]")
    else:
        vf = (
            f"{crop_expr},scale={cfg.target_w}:{cfg.target_h}:flags=lanczos,"
            f"subtitles={ass_path.name}"
        )
        parts = [f"[0:v]{vf}[{main_label}]"]

    if use_bar:
        # Generate a colored strip and shrink/grow its width per frame.
        # scale (not crop) supports eval=frame in ffmpeg 8.x; drawbox's width
        # expression is config-time only in most builds, hence this workaround.
        parts.append(
            f"color=c={progress_color}@0.9:s={cfg.target_w}x{bar_h}:d={progress_duration:.2f}:r=30[barfull]"
        )
        parts.append(
            f"[barfull]scale=w='max(2\\,iw*t/{progress_duration:.2f})':h={bar_h}:eval=frame[bar]"
        )
        parts.append(
            f"[vmain][bar]overlay=x=0:y=H-{bar_h}:eof_action=pass[v]"
        )

    parts.append(af)
    filter_complex = ";".join(parts)

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    run_capture_stderr(cmd, cwd=str(cwd))
    return out_path


def _slugify_local(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower())[:40].strip("-")
    return s or "clip"


def transcribe_full_video(video_path: Path, model_name: str,
                          device: str = "auto", on_step=None) -> list:
    """Full-video transcription returning [(start, end, text), ...] segments.

    Runs whisper in a SUBPROCESS so that ctranslate2 / cuDNN cleanup faults
    on long files (which silently kill python.exe on Windows + cudnn 9) can't
    take the GUI down with them. The subprocess writes the parsed segment
    list to a JSON file BEFORE the model goes out of scope, so even if the
    child crashes during teardown the parent already has the results."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    # Pre-extract audio so whisper doesn't have to demux a long video stream.
    audio_path = video_path.with_suffix(".whisper.wav")
    if not audio_path.exists() or audio_path.stat().st_size < 1024:
        log(f"      extracting audio -> {audio_path.name} (16kHz mono)")
        try:
            run_capture_stderr([
                "ffmpeg", "-y", "-i", str(video_path),
                "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", str(audio_path),
            ])
        except Exception as e:
            raise RuntimeError(f"audio extraction failed: {e}") from e

    out_json = audio_path.with_suffix(".segments.json")
    if out_json.exists():
        try: out_json.unlink()
        except Exception: pass

    # Order of device attempts
    devices = (
        ["cuda", "cpu"] if device == "auto"
        else ["cuda"] if device == "cuda"
        else ["cpu"]
    )

    # Child script. Writes JSON ASAP after iteration, before model goes out
    # of scope. We register the same Windows CUDA-DLL workaround here too.
    child_code = (
        "import json, os, sys, importlib.util\n"
        "if sys.platform == 'win32':\n"
        "    for pkg in ('nvidia.cublas','nvidia.cudnn','nvidia.cuda_runtime','nvidia.cuda_nvrtc'):\n"
        "        try:\n"
        "            spec = importlib.util.find_spec(pkg)\n"
        "        except Exception:\n"
        "            spec = None\n"
        "        if spec and spec.submodule_search_locations:\n"
        "            for loc in spec.submodule_search_locations:\n"
        "                b = os.path.join(loc, 'bin')\n"
        "                if os.path.isdir(b):\n"
        "                    try: os.add_dll_directory(b)\n"
        "                    except Exception: pass\n"
        "                    os.environ['PATH'] = b + os.pathsep + os.environ.get('PATH','')\n"
        "from faster_whisper import WhisperModel\n"
        "audio = sys.argv[1]\n"
        "model_name = sys.argv[2]\n"
        "device = sys.argv[3]\n"
        "out_json = sys.argv[4]\n"
        "ct = 'float16' if device == 'cuda' else 'int8'\n"
        "model = WhisperModel(model_name, device=device, compute_type=ct)\n"
        "segments_iter, info = model.transcribe(\n"
        "    audio, word_timestamps=False, vad_filter=True,\n"
        "    vad_parameters={'min_silence_duration_ms': 500},\n"
        ")\n"
        "out = []\n"
        "for s in segments_iter:\n"
        "    t = str(s.text).strip()\n"
        "    if t:\n"
        "        out.append([float(s.start), float(s.end), t])\n"
        "with open(out_json, 'w', encoding='utf-8') as f:\n"
        "    json.dump({'duration': float(info.duration), 'segments': out}, f)\n"
        "print(f'OK {len(out)} segments {info.duration:.1f}s', flush=True)\n"
    )

    last_err = None
    for dev in devices:
        log(f"      transcribe via subprocess (device={dev}, model={model_name})")
        try:
            proc = subprocess.run(
                [sys.executable, "-c", child_code, str(audio_path), model_name, dev, str(out_json)],
                capture_output=True, text=True, timeout=1800,
            )
        except subprocess.TimeoutExpired as e:
            last_err = f"timeout after 30min on {dev}"
            log(f"      {last_err}")
            continue

        # Even if the child crashed during teardown, the JSON may already
        # have been written. Trust the JSON if it exists.
        if out_json.exists() and out_json.stat().st_size > 2:
            try:
                payload = json.loads(out_json.read_text(encoding="utf-8"))
            except Exception as e:
                payload = None
            if payload:
                segs = payload.get("segments") or []
                dur = float(payload.get("duration") or 0.0)
                out = [(float(a), float(b), str(c)) for (a, b, c) in segs]
                log(f"      whisper {dev}: {len(out)} segments, duration {dur:.1f}s "
                    f"(subprocess exit={proc.returncode})")
                return out

        # No JSON written -> capture stderr for the user
        err_tail = (proc.stderr or "").strip().splitlines()[-10:]
        last_err = f"subprocess exit {proc.returncode} on {dev}: " + " | ".join(err_tail)
        log(f"      whisper {dev} failed: {last_err[:240]}")

    raise RuntimeError(f"full transcription failed on all backends: {last_err}")


def _snap_to_segment_boundary(time_target: float, segments: list,
                              kind: str, tolerance: float,
                              debug: list = None) -> float:
    """Snap a time to the nearest Whisper segment boundary within `tolerance`.
    Scoring per candidate combines:
      - punctuation (.!?…) at end / before start
      - gap to next/previous segment (real speech pause)
      - distance from target (closer is better, weak tiebreaker)
    A real sentence end almost always has both punctuation AND a >0.4s gap.
    Whisper hallucinates periods inside abbreviations ('vs.', 'z.B.'), so
    we won't trust punctuation alone; the gap is the stronger signal."""
    if not segments or tolerance <= 0:
        if debug is not None:
            debug.append(f"no segments / tol={tolerance}")
        return time_target
    sentence_enders = (".", "!", "?", "…")
    # Build (sorted-by-time) start/end arrays once for gap computation
    seg_starts = sorted(s[0] for s in segments)
    seg_ends = sorted(s[1] for s in segments)

    def gap_after(t: float) -> float:
        """Silence between t and the next segment start."""
        for s in seg_starts:
            if s > t + 0.01:
                return s - t
        return 99.0  # end of video

    def gap_before(t: float) -> float:
        """Silence between previous segment end and t."""
        prev = -1.0
        for e in seg_ends:
            if e < t - 0.01:
                prev = e
            else:
                break
        return (t - prev) if prev >= 0 else 99.0

    if kind == "start":
        cand = [s for s in segments if abs(s[0] - time_target) <= tolerance]
    else:
        cand = [s for s in segments if abs(s[1] - time_target) <= tolerance]
    if not cand:
        if debug is not None:
            debug.append(f"no candidates within ±{tolerance}s of {time_target:.1f}")
        return time_target

    scored = []
    for s in cand:
        text = str(s[2]).rstrip()
        if kind == "end":
            t = s[1]
            has_punct = text.endswith(sentence_enders)
            gap = gap_after(t)
        else:
            t = s[0]
            # For "start", punctuation belongs to the PREVIOUS segment.
            prev_e = max((x[1] for x in segments if x[1] <= t + 0.01), default=-1.0)
            prev_text = ""
            for x in segments:
                if abs(x[1] - prev_e) < 0.01:
                    prev_text = str(x[2]).rstrip()
                    break
            has_punct = prev_text.endswith(sentence_enders)
            gap = gap_before(t)
        # Heuristic score: gap is the strongest signal (real pause), punctuation
        # is a bonus on top. Distance from target is a soft tiebreaker.
        gap_score = min(gap, 2.0) * 1.5  # 0..3
        punct_score = 0.8 if has_punct else 0.0
        dist_penalty = abs(t - time_target) * 0.15  # 0..1.8 across ±12s window
        score = gap_score + punct_score - dist_penalty
        scored.append((score, t, has_punct, gap))
    scored.sort(key=lambda x: -x[0])
    best = scored[0]
    if debug is not None:
        n_punct = sum(1 for x in scored if x[2])
        debug.append(
            f"{len(cand)} cands ±{tolerance}s, {n_punct} punctuated, "
            f"picked {best[1]:.1f} (gap={best[3]:.2f}s, punct={'Y' if best[2] else 'N'})"
        )
    return best[1]


def find_best_moments(segments: list, n_clips: int, target_duration: float,
                      cfg: "Config", on_step=None) -> list:
    """Send the transcript to Gemini and ask for the N best viral moments.
    For long sources (>10 min), splits the transcript into n_clips equal
    time-regions and asks Gemini for ONE moment per region. Guarantees
    distribution across the whole video. Returns list of moment dicts."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)
    if not segments:
        raise RuntimeError("no transcript segments to analyse")
    if not cfg.gemini_api_key:
        raise RuntimeError("multi-clip best-moments needs gemini_api_key")

    src_dur_all = max(s[1] for s in segments)
    if src_dur_all > 600 and n_clips >= 3:
        log(f"      chunking transcript into {n_clips} regions for forced distribution")
        chunk_dur = src_dur_all / n_clips
        all_moments: list = []
        for i in range(n_clips):
            c_start = i * chunk_dur
            c_end = (i + 1) * chunk_dur
            chunk = [s for s in segments if s[0] >= c_start and s[1] <= c_end]
            if len(chunk) < 5:
                log(f"        region {i+1}/{n_clips} ({c_start:.0f}-{c_end:.0f}s): too few segments, skip")
                continue
            log(f"        region {i+1}/{n_clips} ({c_start:.0f}-{c_end:.0f}s): {len(chunk)} segments")
            try:
                ms = _find_moments_single_call(chunk, 1, target_duration, cfg)
                all_moments.extend(ms)
            except Exception as e:
                log(f"        region {i+1} failed: {str(e)[:160]}")
        if not all_moments:
            raise RuntimeError("all transcript regions failed to yield moments")
        return _snap_and_dedupe_moments(all_moments, segments, n_clips, target_duration, on_step=log)

    # Short video / few clips: single call as before
    ms = _find_moments_single_call(segments, n_clips, target_duration, cfg)
    return _snap_and_dedupe_moments(ms, segments, n_clips, target_duration, on_step=log)


def _find_moments_single_call(segments: list, n_clips: int, target_duration: float,
                              cfg: "Config") -> list:
    """One Gemini API call: parse N viral moments from the given transcript."""
    lines = []
    for s, e, t in segments:
        ts = f"{int(s // 60):02d}:{s % 60:05.2f}"
        te = f"{int(e // 60):02d}:{e % 60:05.2f}"
        lines.append(f"{ts}-{te}  {t}")
    transcript = "\n".join(lines)
    # Opus-style free length: hint at a preferred duration but let Gemini
    # pick the actual length based on content. Hard floor 20s — anything
    # shorter is rarely viral on its own without setup/punchline context.
    hint = max(30, int(target_duration))
    src_dur = max(s[1] for s in segments) if segments else 0.0
    dur_min = int(src_dur // 60)
    dur_sec_rem = int(src_dur % 60)
    third = src_dur / 3.0
    prompt = (
        f"Du analysierst ein deutsches Voll-Transkript eines Podcasts/Talks/Streams "
        f"und findest die {n_clips} viralsten Momente für YouTube Shorts.\n\n"
        f"GESAMTDAUER des Videos: {dur_min}:{dur_sec_rem:02d} Minuten ({int(src_dur)}s).\n\n"
        f"Transkript-Format pro Zeile: 'MM:SS.ss-MM:SS.ss  Text'\n\n"
        f"=== TRANSKRIPT ===\n{transcript}\n=== ENDE ===\n\n"
        f"Finde EXAKT {n_clips} Momente. Beachte BEIDE Regeln strikt:\n\n"
        f"REGEL 1 — VERTEILUNG (kritisch!):\n"
        f"- Die {n_clips} Momente müssen ÜBER DAS GANZE VIDEO verteilt sein (0 bis {int(src_dur)}s).\n"
        f"- Picke NICHT alle nur aus dem Anfang. Auch der mittlere und späte Teil hat "
        f"  virale Momente — such sie aktiv.\n"
        f"- Faustregel: ~{n_clips//3} Momente aus 0–{int(third):.0f}s, "
        f"~{n_clips//3} aus {int(third):.0f}–{int(2*third):.0f}s, "
        f"~{n_clips - 2*(n_clips//3)} aus {int(2*third):.0f}–{int(src_dur):.0f}s.\n\n"
        f"REGEL 2 — LÄNGE (kritisch!):\n"
        f"- Jeder Moment muss MINDESTENS 25 Sekunden lang sein (lieber 30–60s).\n"
        f"- Schneide NIE mitten im Satz — IMMER am Ende eines vollständigen Gedankens.\n"
        f"- Wenn die eigentliche Pointe 5s dauert: nimm den Kontext davor (Setup, Frage) "
        f"  UND danach (Reaktion, Folgesatz) mit dazu bis es 25–60s wird.\n"
        f"- Typische Längen je Content-Typ (Pflicht-Bereich):\n"
        f"  * Pointe mit Setup: 25–40s\n"
        f"  * Story mit Aufbau: 40–70s\n"
        f"  * Debatte / Argumentation: 70–120s\n"
        f"  * Komplexe Geschichte: bis zu 5 Minuten (300s) wenn es WIRKLICH viral ist\n"
        f"- Richtwert: ~{hint}s. Harte Grenzen: 25s minimum, 10 Minuten maximum.\n\n"
        f"Such nach: schockierenden Aussagen, Cliffhangern, lustigen Pointen, "
        f"Streit, Storys mit Hook, kontroversen Meinungen, 'wait what' Momenten, "
        f"emotionalen Spitzen. AKTIV im ganzen Video — auch hinten!\n\n"
        f"Für JEDEN Moment liefere:\n"
        f"- start_seconds: float, Beginn in Sekunden vom Source-Anfang\n"
        f"- end_seconds: float, Ende in Sekunden\n"
        f"- hook: maximal 60 Zeichen, fett-knackiger Aufmacher für oben im Bild "
        f"(z.B. 'POV: Niemand hat damit gerechnet')\n"
        f"- title: YouTube Short Titel, maximal 70 Zeichen, mit Emoji am Ende\n"
        f"- hashtags: Array von 3-5 deutschen Hashtags OHNE # davor (z.B. ['podcast','viral','wahnsinn'])\n"
        f"- score: Virality 1-100 (deine ehrliche Einschätzung)\n"
        f"- reason: 1 Satz warum dieser Moment funktioniert\n\n"
        f"Antworte NUR mit einem gültigen JSON-Array von genau {n_clips} Objekten. "
        f"KEINE Markdown-Codeblocks, KEINE Kommentare, NUR das JSON-Array."
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
            # Dynamic thinking: model decides budget based on task complexity.
            # Moment-picking is the one call where reasoning pays off (judging
            # virality across a long transcript), so we don't disable it like
            # we do for the cheaper script/scene/vision calls.
            "thinkingConfig": {"thinkingBudget": -1},
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent"
    data = _gemini_post(url, {"key": cfg.gemini_api_key}, body)
    try:
        candidate = data["candidates"][0]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini returned no candidates: {data}") from e
    parts = candidate.get("content", {}).get("parts", []) or []
    text = "\n".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:].strip()
    s_idx, e_idx = text.find("["), text.rfind("]")
    if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
        text = text[s_idx:e_idx + 1]
    try:
        moments = json.loads(text)
    except Exception as e:
        raise RuntimeError(f"could not parse Gemini moments JSON: {e}; raw={text[:400]}") from e
    if not isinstance(moments, list):
        raise RuntimeError(f"expected JSON array, got {type(moments).__name__}")
    cleaned = []
    for m in moments:
        if not isinstance(m, dict):
            continue
        try:
            start = float(m.get("start_seconds") or m.get("start") or 0)
            end = float(m.get("end_seconds") or m.get("end") or 0)
        except (TypeError, ValueError):
            continue
        if end <= start or end - start < 5:
            continue
        cleaned.append({
            "start": start,
            "end": end,
            "hook": str(m.get("hook", "")).strip()[:80],
            "title": str(m.get("title", "")).strip()[:120],
            "hashtags": [str(h).lstrip("#").strip() for h in (m.get("hashtags") or []) if h],
            "score": int(m.get("score", 0) or 0),
            "reason": str(m.get("reason", "")).strip()[:240],
        })
    if not cleaned:
        raise RuntimeError("Gemini returned no usable moments")
    return cleaned


def _snap_and_dedupe_moments(cleaned: list, segments: list, n_clips: int,
                             target_duration: float, on_step=None) -> list:
    """Apply sentence-boundary snap + dedup + chronological sort to a raw
    list of Gemini moment dicts. Returns up to n_clips final moments."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)
    if not cleaned:
        raise RuntimeError("no moments to snap")

    # Snap each Gemini moment to natural sentence boundaries (Whisper segment
    # ends, preferring real .!? endings). This is how Opus.pro avoids cutting
    # mid-sentence — the clip finishes at a real speech pause, even if that
    # means 26s or 38s instead of the requested 30s.
    src_end = max(s[1] for s in segments) if segments else 0.0
    # Opus-style free length: Gemini's chosen end IS the target. We just snap
    # it to a nearby sentence boundary. Hard rails kept very loose (10s / 10min)
    # so a strong narrative can run as long as it needs to.
    HARD_MIN, HARD_MAX = 20.0, 600.0
    if on_step:
        try:
            n_punct = sum(1 for s in segments if str(s[2]).rstrip().endswith((".","!","?","…")))
            on_step(f"      snap context: {len(segments)} segments, {n_punct} end with .!? — free-length mode")
        except Exception:
            pass
    snapped = []
    for m in cleaned:
        orig_start, orig_end = m["start"], m["end"]
        dbg_start: list = []
        dbg_end: list = []
        # Start: snap to nearest segment start that follows a sentence end.
        snapped_start = _snap_to_segment_boundary(orig_start, segments, "start", 5.0, debug=dbg_start)
        # End: TRUST Gemini's chosen end as the ideal. Snap to nearest clean
        # sentence boundary within ±8s of that — no forced target_duration.
        snapped_end = _snap_to_segment_boundary(orig_end, segments, "end", 8.0, debug=dbg_end)
        # Apply hard safety rails only.
        if snapped_end - snapped_start < HARD_MIN:
            snapped_end = _snap_to_segment_boundary(
                snapped_start + HARD_MIN, segments, "end", 6.0,
            )
        if snapped_end - snapped_start > HARD_MAX:
            snapped_end = _snap_to_segment_boundary(
                snapped_start + HARD_MAX, segments, "end", 6.0,
            )
        # Clamp to source end.
        if src_end > 0 and snapped_end > src_end:
            snapped_end = src_end
        m["start"] = snapped_start
        m["end"] = snapped_end
        if on_step:
            try:
                on_step(
                    f"      snapped {orig_start:6.1f}-{orig_end:6.1f}s -> "
                    f"{snapped_start:6.1f}-{snapped_end:6.1f}s "
                    f"({snapped_end - snapped_start:5.1f}s) "
                    f"[start: {' / '.join(dbg_start) or '-'}] "
                    f"[end: {' / '.join(dbg_end) or '-'}] | {m['title'][:40]}"
                )
            except Exception:
                pass
        snapped.append(m)

    # Drop near-duplicates that ended up snapping to the same range (Gemini
    # sometimes returns two slightly different picks that collapse to one
    # clip after snapping). Keep the first occurrence by score order.
    snapped.sort(key=lambda x: -int(x.get("score", 0) or 0))
    deduped = []
    for m in snapped:
        is_dup = False
        for prev in deduped:
            overlap = max(0.0, min(m["end"], prev["end"]) - max(m["start"], prev["start"]))
            m_dur = max(0.1, m["end"] - m["start"])
            p_dur = max(0.1, prev["end"] - prev["start"])
            if overlap / min(m_dur, p_dur) > 0.7:
                is_dup = True
                if on_step:
                    try:
                        on_step(
                            f"      dropping duplicate {m['start']:.1f}-{m['end']:.1f}s "
                            f"(overlaps {prev['start']:.1f}-{prev['end']:.1f}s)"
                        )
                    except Exception:
                        pass
                break
        if not is_dup:
            deduped.append(m)

    # Restore chronological order so multi-clip plays in source order.
    deduped.sort(key=lambda x: x["start"])
    if not deduped:
        raise RuntimeError("all moments collapsed after dedupe")
    return deduped[:n_clips]


def run_multiclip(job: dict, cfg: "Config", on_step=None) -> list:
    """Download source once, transcribe whole video, ask Gemini for the N best
    moments, then render each as its own short via run_one. Returns list of
    output paths. Writes a sibling .txt with title/hashtags/score per clip."""
    def step(msg: str):
        # NOTE: only delegate to on_step (which prints + sends to GUI). Don't
        # print here — run_one's step() will print the message itself when we
        # call it as on_step for sub-clips, otherwise we'd duplicate every
        # line in the console.
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    base_slug = job.get("slug") or "multiclip"
    source_url = (job.get("source_url") or "").strip()
    if not source_url:
        raise RuntimeError("multi-clip mode needs source_url (channel scrape not yet supported)")

    n_clips = max(2, min(int(job.get("multiclip_count", 5)), 15))
    target_dur = float(job.get("target_duration", 30.0))

    work_root = cfg.output_dir / f"{base_slug}__multiclip_work"
    work_root.mkdir(parents=True, exist_ok=True)
    step(f"[MULTI 1/4] download source: {source_url}")
    raw = download_gameplay(source_url, work_root)

    step("[MULTI 2/4] full-video transcription (Whisper)")
    whisper_device = str(job.get("whisper_device", "auto"))
    segments = transcribe_full_video(raw, cfg.whisper_model, device=whisper_device, on_step=step)
    src_dur = segments[-1][1] if segments else 0.0
    step(f"      transcript: {len(segments)} segments, source ≈ {src_dur:.0f}s")

    step(f"[MULTI 3/4] ask Gemini for the top {n_clips} viral moments")
    moments = find_best_moments(segments, n_clips, target_dur, cfg, on_step=step)
    step(f"      Gemini returned {len(moments)} moments:")
    for i, m in enumerate(moments, 1):
        step(f"        {i:2d}. {m['start']:6.1f}s-{m['end']:6.1f}s  score={m['score']:3d}  {m['title'][:60]}")

    if not bool(job.get("auto_reframe", False)):
        step("")
        step("  ⚠️⚠️⚠️  AUTO-REFRAME IST AUS  ⚠️⚠️⚠️")
        step("  Die Clips werden ZENTRAL gecroppt — Sprecher links/rechts werden ABGESCHNITTEN.")
        step("  In der GUI '🎯 Auto-Reframe (KI findet wo Menschen/Gesichter sind)' anhaken!")
        step("")
    else:
        step("      auto-reframe: ON (YOLOv11/MediaPipe wird pro Clip rufen)")
    step(f"[MULTI 4/4] render {len(moments)} shorts")
    outputs: list = []
    for i, m in enumerate(moments, 1):
        clip_slug = f"{base_slug}_{i:02d}_{_slugify_local(m['hook'] or m['title'])[:30]}"
        step(f"  ── Clip {i}/{len(moments)}: {clip_slug}")
        sub_job = dict(job)
        sub_job["slug"] = clip_slug
        sub_job["source_url"] = source_url
        sub_job["source_file"] = str(raw)
        sub_job["scene_pick_mode"] = "manual"
        sub_job["manual_ranges"] = f"{m['start']:.2f}-{m['end']:.2f}"
        # Override the GUI slider so downstream stages (silent audio track,
        # progress bar, etc.) use the snap-adjusted actual range length
        # instead of the slider's nominal target. Otherwise ffmpeg -shortest
        # caps the final video at the GUI's 30s while the clip is 31s/29s/39s.
        sub_job["target_duration"] = float(m["end"] - m["start"])
        if m.get("hook"):
            sub_job["hook_text"] = m["hook"]
        sub_job["multiclip_enabled"] = False  # prevent recursion
        try:
            out_mp4 = run_one(sub_job, cfg, on_step=step)
        except Exception as e:
            step(f"  ── Clip {i} FAILED: {e}")
            continue
        # Sidecar metadata
        meta = (
            f"TITLE: {m['title']}\n"
            f"HOOK: {m['hook']}\n"
            f"HASHTAGS: {' '.join('#' + h for h in m['hashtags'])}\n"
            f"VIRALITY SCORE: {m['score']}/100\n"
            f"REASON: {m['reason']}\n"
            f"SOURCE RANGE: {m['start']:.1f}s - {m['end']:.1f}s\n"
            f"SOURCE URL: {source_url}\n"
        )
        try:
            out_mp4.with_suffix(".txt").write_text(meta, encoding="utf-8")
        except Exception:
            pass
        outputs.append(out_mp4)

    step(f"[MULTI DONE] {len(outputs)}/{len(moments)} clips rendered")
    return outputs


def run_one(job: dict, cfg: Config, on_step=None) -> Path:
    def step(msg: str) -> None:
        if on_step:
            try:
                on_step(msg)
            except Exception:
                pass
        print(msg)

    base_slug = job["slug"]
    source_url = (job.get("source_url") or "").strip()

    if not source_url:
        channel_url = (job.get("channel_url") or "").strip()
        if not channel_url:
            raise RuntimeError(f"job {base_slug!r} needs either 'source_url' or 'channel_url'")
        used_path = cfg.output_dir / "used_videos.json"
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        title_filter = job.get("title_filter") or None
        scan_limit = int(job.get("channel_scan_limit", 200))
        pick = pick_unused_channel_video(channel_url, used_path, limit=scan_limit, title_filter=title_filter)
        source_url = pick["url"]
        slug = f"{base_slug}-{pick['id']}"
        step(f"      channel pick: {pick['title'][:60]} ({pick['id']})")
    else:
        slug = base_slug

    work = cfg.output_dir / slug
    work.mkdir(parents=True, exist_ok=True)

    pre_downloaded = job.get("source_file")
    if pre_downloaded and Path(pre_downloaded).is_file():
        raw = Path(pre_downloaded)
        step(f"[1/5] reusing pre-downloaded source: {raw.name}")
    else:
        step(f"[1/5] download: {source_url}")
        raw = download_gameplay(source_url, work / "source")

    target_duration = float(job.get("target_duration", 30.0))

    enable_voice = bool(job.get("enable_voice", True))

    if enable_voice:
        script = (job.get("script") or "").strip()
        if script:
            step(f"      using user-provided script ({len(script)} chars)")
        else:
            topic = (job.get("topic") or "").strip()
            if not topic:
                raise RuntimeError(f"job {slug!r} has neither 'script' nor 'topic'")
            step(f"      generating script for topic: {topic!r} (target {target_duration:.0f}s)")
            try:
                script = generate_script(topic, cfg, target_seconds=target_duration, on_step=step)
            except RuntimeError as e:
                step(f"      WARN: script gen failed: {e}")
                step(f"      using template fallback script (pipeline continues)")
                script = fallback_template_script(topic)
        (work / "script.txt").write_text(script, encoding="utf-8")
        preview = script[:80].replace("\n", " ")
        step(f"      script: {preview}...")

        step("[2/5] voiceover")
        vo_raw = synthesize_voiceover(script, cfg, work / "voice_raw.mp3")
        vo = trim_leading_silence(vo_raw, work / "voice.mp3")
        vo_dur = probe_duration(vo)
    else:
        step("[2/5] voice disabled — generating silent base track")
        vo_dur = float(target_duration)
        vo = make_silent_track(vo_dur, work / "voice.mp3")
        # Still need a non-empty seed for image prompt generation; fall back to
        # the topic field if there's no script.
        script = (job.get("topic") or "").strip() or "cinematic scene"

    # bias clip duration toward target_duration but never cut the voiceover
    target = min(max(vo_dur + 0.6, target_duration - 5.0, 15.0), target_duration + 12.0, 150.0)
    step(f"      voice {vo_dur:.1f}s -> clip {target:.1f}s (target {target_duration:.0f}s)")

    clip_segments = max(1, min(int(job.get("clip_segments", 1)), 24))
    mode = str(job.get("scene_pick_mode", "even")).lower()
    # Back-compat with the old smart_picking checkbox
    if mode == "even" and bool(job.get("smart_picking", False)):
        mode = "loud"
    if mode == "manual":
        manual_text = str(job.get("manual_ranges", "")).strip()
        if not manual_text:
            raise RuntimeError(
                "Szenen-Auswahl 'Manuell' gewählt aber keine Zeit-Bereiche angegeben."
            )
        try:
            ranges = parse_time_ranges(manual_text)
        except ValueError as e:
            raise RuntimeError(f"Fehler beim Parsen der manuellen Zeit-Bereiche: {e}") from e
        # Manual mode overrides the slider-derived target/segments: we honor
        # exactly what the user asked for.
        clip_segments = len(ranges)
        target = sum(d for _, d in ranges)
        pretty = ", ".join(f"{s:.1f}s-{s+d:.1f}s" for s, d in ranges)
        step(f"[3/5] manual pick {clip_segments} scenes ({target:.1f}s total): {pretty}")
        clip = pick_manual_clips(raw, ranges, work / "clip.mp4")
    elif clip_segments > 1:
        if mode == "ai":
            step(f"[3/5] AI pick {clip_segments} scenes via Vision LLM (~{target / clip_segments:.1f}s each)")
            clip = pick_ai_scenes(raw, target, clip_segments, work / "clip.mp4",
                                  cfg, work_dir=work, on_step=step)
        elif mode == "loud":
            step(f"[3/5] loud pick {clip_segments} loudest scenes (~{target / clip_segments:.1f}s each)")
            clip = pick_loud_multi_clips(raw, target, clip_segments, work / "clip.mp4")
        else:
            step(f"[3/5] even pick {clip_segments} gameplay scenes (~{target / clip_segments:.1f}s each, stitched)")
            clip = pick_multi_clips(raw, target, clip_segments, work / "clip.mp4")
    else:
        if mode == "ai":
            step("[3/5] AI pick: most exciting window via Vision LLM")
            clip = pick_ai_scenes(raw, target, 1, work / "clip.mp4",
                                  cfg, work_dir=work, on_step=step)
        elif mode == "loud":
            step("[3/5] loud pick: loudest window of gameplay")
            clip = pick_loud_clip(raw, target, work / "clip.mp4", work_dir=work)
        else:
            step("[3/5] pick gameplay segment")
            clip = pick_clip(raw, target, work / "clip.mp4")

    if enable_voice:
        whisper_device = str(job.get("whisper_device", "auto"))
        step(f"[4/5] transcribe + captions (device={whisper_device})")
        words, used_dev = transcribe_words(vo, cfg.whisper_model, device=whisper_device)
        step(f"      whisper ran on {used_dev}")
    elif bool(job.get("enable_captions", True)):
        # No TTS voice, but the user wants captions — pull the original
        # speaker audio out of the cut clip and transcribe THAT. Whisper
        # auto-detects the language (German / English / etc.).
        whisper_device = str(job.get("whisper_device", "auto"))
        step(f"[4/5] transcribe source audio for captions (device={whisper_device})")
        clip_audio = work / "clip_audio.wav"
        try:
            run_capture_stderr([
                "ffmpeg", "-y", "-i", str(clip),
                "-vn", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", str(clip_audio),
            ])
            # Use subprocess isolation: per-clip whisper calls accumulate
            # CUDA cleanup state and can hard-crash python.exe after ~10 clips.
            words, used_dev = transcribe_words_subprocess(
                clip_audio, cfg.whisper_model, device=whisper_device, on_step=step,
            )
            step(f"      whisper ran on {used_dev} — {len(words)} words from source audio")
        except Exception as e:
            step(f"      WARN: source transcription failed ({str(e)[:160]}); no captions")
            words = []
    else:
        step("[4/5] no voice + captions disabled — skipping transcription")
        words = []
    ass = write_ass(
        words, cfg.target_w, cfg.target_h, work / "captions.ass",
        font_name=str(job.get("caption_font", "Impact")),
        font_size=int(job.get("caption_font_size", 0)) or None,
        primary_color=str(job.get("caption_color", "#FFFFFF")),
        outline_color=str(job.get("caption_stroke_color", "#000000")),
        outline_width=int(job.get("caption_stroke_width", 5)),
        hook_text=str(job.get("hook_text", "")),
        hook_duration=float(job.get("hook_duration", 3.0)),
        pop_captions=bool(job.get("pop_captions", False)),
        subscribe_overlay=bool(job.get("subscribe_overlay", False)),
        subscribe_text=str(job.get("subscribe_text", "ABONNIEREN")),
        total_duration=vo_dur,
        enable_captions=bool(job.get("enable_captions", True)),
    )

    image_paths: list = []
    image_duration = float(job.get("image_duration", 1.5))
    if not job.get("no_image"):
        explicit_paths = job.get("image_paths") or []
        if explicit_paths:
            image_paths = [Path(p).expanduser() for p in explicit_paths]
            for p in image_paths:
                if not p.exists():
                    raise RuntimeError(f"image path does not exist: {p}")
        elif job.get("image_path"):
            single = Path(job["image_path"]).expanduser()
            if not single.exists():
                raise RuntimeError(f"image_path does not exist: {single}")
            image_paths = [single]
        else:
            n_images = max(1, min(int(job.get("image_count", 3)), 5))
            user_prompts = [p.strip() for p in (job.get("image_prompts") or []) if p and p.strip()]
            if user_prompts:
                step(f"      using {len(user_prompts)} user-provided image prompt(s)")
                prompts = user_prompts[:n_images]
                if len(prompts) < n_images:
                    step(f"      filling remaining {n_images - len(prompts)} prompt(s) via Gemini")
                    auto = generate_scene_prompts(script, n_images - len(prompts), cfg)
                    prompts.extend(auto)
            else:
                step(f"      generating {n_images} scene prompts via Gemini")
                prompts = generate_scene_prompts(script, n_images, cfg)
            consecutive_failures = 0
            cloudflare_ready = bool(cfg.cloudflare_account_id and cfg.cloudflare_api_token)
            for i, prompt in enumerate(prompts, 1):
                step(f"      [{i}/{n_images}] image: {prompt[:80]}")
                target_path = work / f"image_{i}.png"
                ok = False
                primary_err: str | None = None

                if cloudflare_ready:
                    try:
                        fetch_image_from_cloudflare(
                            prompt, target_path, cfg,
                            seed=random.randint(1, 1_000_000),
                        )
                        image_paths.append(target_path)
                        ok = True
                    except Exception as e:
                        primary_err = f"Cloudflare: {e}"
                        step(f"      Cloudflare failed, falling back to Pollinations")

                if not ok:
                    try:
                        fetch_image_from_pollinations(
                            prompt, target_path, seed=random.randint(1, 1_000_000)
                        )
                        image_paths.append(target_path)
                        ok = True
                    except Exception as e:
                        poll_err = f"Pollinations: {e}"
                        primary_err = f"{primary_err}; {poll_err}" if primary_err else poll_err

                if ok:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    err_summary = primary_err or "unknown"
                    step(f"      WARN: image {i} failed: {err_summary[:200]}")
                    if consecutive_failures >= 2 and i < n_images:
                        step(
                            f"      image generators seem down, skipping remaining "
                            f"{n_images - i} image(s); pipeline continues without them"
                        )
                        break

    # Background music: mix AFTER transcription (so captions stay clean)
    audio_for_compose = vo
    using_bgm = False

    # SFX layer first — hit on each image pop-in AND on each scene cut.
    # We collect events first, optionally add a subscribe-sting, then mix once.
    sfx_dir = (job.get("sfx_dir") or "").strip()
    sfx_pct = float(job.get("sfx_volume_pct", 0.0))
    sfx_track = (job.get("sfx_track") or "").strip()
    enable_sfx = bool(job.get("enable_sfx", True))
    events: list = []

    if enable_sfx and sfx_dir and sfx_pct > 0:
        if image_paths:
            schedule = _image_schedule(len(image_paths), target, image_duration)
            for start, _end in schedule:
                picked = pick_sfx_track(sfx_dir, sfx_track)
                if picked is not None:
                    events.append((float(start), picked, sfx_pct))

        if clip_segments > 1:
            seg_dur = target / clip_segments
            for i in range(1, clip_segments):  # skip t=0 start
                picked = pick_sfx_track(sfx_dir, sfx_track)
                if picked is not None:
                    events.append((i * seg_dur, picked, sfx_pct))

        # dedupe near-collisions (image pop-in landing on a scene cut)
        events.sort(key=lambda e: e[0])
        deduped = []
        for ev in events:
            if not deduped or abs(ev[0] - deduped[-1][0]) > 0.3:
                deduped.append(ev)
        events = deduped

        if events:
            n_image = len(image_paths) if image_paths else 0
            n_cuts = max(0, clip_segments - 1)
            step(
                f"      adding {len(events)} SFX hits @ {sfx_pct:.0f}% "
                f"({n_image} image pop-ins + {n_cuts} scene cuts, deduped to {len(events)})"
            )
        elif not image_paths and clip_segments <= 1:
            step("      no SFX trigger events (no images, no scene cuts) — skipping")
        else:
            step(f"      WARN: no SFX files found in {sfx_dir!r}, skipping")

    # Optional sting that fires the moment the Subscribe banner pops in.
    # Independent of the regular SFX toggle so the user can keep SFX off but
    # still want the sub sting (or vice versa).
    if bool(job.get("subscribe_overlay", False)):
        sting_path_str = str(job.get("subscribe_sting_file") or "").strip()
        sting_vol = float(job.get("subscribe_sting_volume", 60.0))
        if sting_path_str and sting_vol > 0:
            sting_path = Path(sting_path_str).expanduser()
            if sting_path.is_file():
                sting_at = max(0.0, vo_dur - 2.5)
                events.append((sting_at, sting_path, sting_vol))
                step(f"      adding subscribe sting @ {sting_vol:.0f}% at {sting_at:.1f}s")
            else:
                step(f"      WARN: subscribe sting file not found: {sting_path_str}")

    if events:
        events.sort(key=lambda e: e[0])
        audio_for_compose = mix_voice_with_sfx(
            audio_for_compose, events, work / "voice_with_sfx.mp3"
        )

    music_dir = (job.get("music_dir") or "").strip()
    music_pct = float(job.get("music_volume_pct", 0.0))
    music_track = (job.get("music_track") or "").strip()
    smart_music_start = bool(job.get("smart_music_start", True))
    enable_music = bool(job.get("enable_music", True))
    if enable_music and music_dir and music_pct > 0:
        track = pick_music_track(music_dir, music_track)
        if track is None:
            step(f"      WARN: no music tracks found in {music_dir!r}, skipping BGM")
        else:
            offset = 0.0
            if smart_music_start:
                voice_dur = _media_duration(audio_for_compose)
                step(f"      analyzing {track.name} for best start offset")
                offset = find_loudest_music_offset(track, voice_dur)
            if offset > 0:
                step(f"      mixing background music: {track.name} @ {music_pct:.0f}% from {offset:.1f}s (gameplay-audio muted)")
            else:
                step(f"      mixing background music: {track.name} @ {music_pct:.0f}% (gameplay-audio muted)")
            audio_for_compose = mix_voice_with_music(
                audio_for_compose, track, music_pct, work / "audio_final.mp3",
                start_offset=offset,
            )
            using_bgm = True

    crop_offset = 0.5
    if bool(job.get("auto_reframe", False)):
        if clip_segments > 1:
            seg_dur = target / clip_segments
            step(f"      auto-reframe: per-scene detection ({clip_segments} segments)")
            crop_offset = detect_subjects_per_segment(
                clip, clip_segments, seg_dur, cfg, on_step=step
            )
        else:
            step("      auto-reframe: asking Cloudflare Vision where the subject is")
            crop_offset = detect_subject_x_position(clip, cfg, on_step=step)

    step("[5/5] compose final short")
    out = cfg.output_dir / f"{slug}.mp4"
    compose_short(
        clip, audio_for_compose, ass, cfg, out,
        image_paths=image_paths,
        duration=target,
        image_duration=image_duration,
        mute_source_audio=using_bgm,
        progress_bar=bool(job.get("progress_bar", False)),
        progress_color=str(job.get("progress_color", "red")),
        progress_duration=vo_dur,
        crop_offset=crop_offset,
    )
    step(f"      -> {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Roblox Shorts pipeline")
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--jobs", required=True, help="JSON file: list of {slug, source_url, script}")
    args = ap.parse_args()

    cfg = Config.load(Path(args.config))
    jobs = _loads_lenient(Path(args.jobs).read_text(encoding="utf-8"))
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
