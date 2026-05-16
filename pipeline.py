#!/usr/bin/env python3
"""Roblox Shorts autopilot: download gameplay -> ElevenLabs TTS -> 9:16 short."""

import argparse
import json
import os
import random
import subprocess
import sys
import time
import urllib.parse
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


def mix_voice_with_music(voice_path: Path, music_path: Path, volume_pct: float,
                         out_path: Path) -> Path:
    """Loop music under voice at given volume (%). Output ends with the voice."""
    vol = max(0.0, min(volume_pct / 100.0, 1.0))
    run([
        "ffmpeg", "-y",
        "-i", str(voice_path),
        "-stream_loop", "-1", "-i", str(music_path),
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
              outline_width: int = 5) -> Path:
    """Bold center-bottom karaoke captions; styling exposed for the GUI."""
    if font_size is None or font_size <= 0:
        font_size = max(56, int(video_h * 0.048))
    primary = _hex_to_ass_color(primary_color)
    outline = _hex_to_ass_color(outline_color)
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
        f"1, 0, 0, 0, 100, 100, 0, 0, 1, {int(outline_width)}, 2, 2, 80, 80, 360, 1\n\n"
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


def generate_scene_prompts(script: str, n: int, cfg: Config) -> list[str]:
    base = derive_image_prompt(script[:200])
    if not cfg.gemini_api_key:
        return [base] * n
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
        print(f"      WARN: Gemini scene gen failed ({e}); falling back to single prompt")
        return [base] * n
    try:
        candidate = data["candidates"][0]
    except (KeyError, IndexError):
        return [base] * n
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
    except Exception:
        prompts = []
    while len(prompts) < n:
        prompts.append(base)
    return prompts[:n]


def fetch_image_from_pollinations(prompt: str, out_path: Path,
                                  width: int = 1024, height: int = 1024,
                                  seed: int | None = None,
                                  retries: int = 2,
                                  backoff: tuple = (5, 12)) -> Path:
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
                  mute_source_audio: bool = False) -> Path:
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

    cmd = ["ffmpeg", "-y", "-i", str(gameplay_clip), "-i", str(voice_audio)]

    if image_paths:
        for img in image_paths:
            cmd += ["-loop", "1", "-i", str(img)]

        overlay_w = int(cfg.target_w * 0.85)
        schedule = _image_schedule(len(image_paths), duration or 25.0, image_duration)

        parts = [
            f"[0:v]crop=ih*9/16:ih,scale={cfg.target_w}:{cfg.target_h}:flags=lanczos[bg0]"
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
        parts.append(f"[{cur}]subtitles={ass_path.name}[v]")
        parts.append(af)
        filter_complex = ";".join(parts)
    else:
        vf = (
            f"crop=ih*9/16:ih,scale={cfg.target_w}:{cfg.target_h}:flags=lanczos,"
            f"subtitles={ass_path.name}"
        )
        filter_complex = f"[0:v]{vf}[v];{af}"

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    run(cmd, cwd=str(cwd))
    return out_path


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

    step(f"[1/5] download: {source_url}")
    raw = download_gameplay(source_url, work / "source")

    target_duration = float(job.get("target_duration", 30.0))

    script = (job.get("script") or "").strip()
    if script:
        step(f"      using user-provided script ({len(script)} chars)")
    else:
        topic = (job.get("topic") or "").strip()
        if not topic:
            raise RuntimeError(f"job {slug!r} has neither 'script' nor 'topic'")
        step(f"      generating script via Gemini for topic: {topic!r} (target {target_duration:.0f}s)")
        try:
            script = generate_script_via_gemini(topic, cfg, target_seconds=target_duration)
        except RuntimeError as e:
            step(f"      WARN: Gemini failed: {e}")
            step(f"      using template fallback script (pipeline continues)")
            script = fallback_template_script(topic)
    (work / "script.txt").write_text(script, encoding="utf-8")
    preview = script[:80].replace("\n", " ")
    step(f"      script: {preview}...")

    step("[2/5] voiceover")
    vo_raw = synthesize_voiceover(script, cfg, work / "voice_raw.mp3")
    vo = trim_leading_silence(vo_raw, work / "voice.mp3")

    vo_dur = probe_duration(vo)
    # bias clip duration toward target_duration but never cut the voiceover
    target = min(max(vo_dur + 0.6, target_duration - 5.0, 15.0), target_duration + 12.0, 150.0)
    step(f"      voice {vo_dur:.1f}s -> clip {target:.1f}s (target {target_duration:.0f}s)")

    clip_segments = max(1, min(int(job.get("clip_segments", 1)), 8))
    smart_picking = bool(job.get("smart_picking", False))
    if clip_segments > 1:
        if smart_picking:
            step(f"[3/5] smart pick {clip_segments} loudest scenes (~{target / clip_segments:.1f}s each)")
            clip = pick_loud_multi_clips(raw, target, clip_segments, work / "clip.mp4")
        else:
            step(f"[3/5] pick {clip_segments} gameplay scenes (~{target / clip_segments:.1f}s each, stitched)")
            clip = pick_multi_clips(raw, target, clip_segments, work / "clip.mp4")
    else:
        if smart_picking:
            step("[3/5] smart pick: loudest window of gameplay")
            clip = pick_loud_clip(raw, target, work / "clip.mp4", work_dir=work)
        else:
            step("[3/5] pick gameplay segment")
            clip = pick_clip(raw, target, work / "clip.mp4")

    step("[4/5] transcribe + captions (CPU, kann ~30s dauern)")
    words = transcribe_words(vo, cfg.whisper_model)
    ass = write_ass(
        words, cfg.target_w, cfg.target_h, work / "captions.ass",
        font_name=str(job.get("caption_font", "Impact")),
        font_size=int(job.get("caption_font_size", 0)) or None,
        primary_color=str(job.get("caption_color", "#FFFFFF")),
        outline_color=str(job.get("caption_stroke_color", "#000000")),
        outline_width=int(job.get("caption_stroke_width", 5)),
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
            for i, prompt in enumerate(prompts, 1):
                step(f"      [{i}/{n_images}] image: {prompt[:80]}")
                try:
                    p = fetch_image_from_pollinations(
                        prompt, work / f"image_{i}.png", seed=random.randint(1, 1_000_000)
                    )
                    image_paths.append(p)
                    consecutive_failures = 0
                except Exception as e:
                    consecutive_failures += 1
                    step(f"      WARN: image {i} failed: {e}")
                    if consecutive_failures >= 2 and i < n_images:
                        step(
                            f"      Pollinations seems down, skipping remaining "
                            f"{n_images - i} image(s); pipeline continues without them"
                        )
                        break

    # Background music: mix AFTER transcription (so captions stay clean)
    audio_for_compose = vo
    using_bgm = False

    # SFX layer first — hit on each image pop-in AND on each scene cut
    sfx_dir = (job.get("sfx_dir") or "").strip()
    sfx_pct = float(job.get("sfx_volume_pct", 0.0))
    sfx_track = (job.get("sfx_track") or "").strip()
    if sfx_dir and sfx_pct > 0:
        events = []

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
            cuts_part = ""
            n_image = len(image_paths) if image_paths else 0
            n_cuts = max(0, clip_segments - 1)
            step(
                f"      adding {len(events)} SFX hits @ {sfx_pct:.0f}% "
                f"({n_image} image pop-ins + {n_cuts} scene cuts, deduped to {len(events)})"
            )
            audio_for_compose = mix_voice_with_sfx(
                audio_for_compose, events, work / "voice_with_sfx.mp3"
            )
        elif not image_paths and clip_segments <= 1:
            step("      no SFX trigger events (no images, no scene cuts) — skipping")
        else:
            step(f"      WARN: no SFX files found in {sfx_dir!r}, skipping")

    music_dir = (job.get("music_dir") or "").strip()
    music_pct = float(job.get("music_volume_pct", 0.0))
    music_track = (job.get("music_track") or "").strip()
    if music_dir and music_pct > 0:
        track = pick_music_track(music_dir, music_track)
        if track is None:
            step(f"      WARN: no music tracks found in {music_dir!r}, skipping BGM")
        else:
            step(f"      mixing background music: {track.name} @ {music_pct:.0f}% (gameplay-audio muted)")
            audio_for_compose = mix_voice_with_music(
                audio_for_compose, track, music_pct, work / "audio_final.mp3"
            )
            using_bgm = True

    step("[5/5] compose final short")
    out = cfg.output_dir / f"{slug}.mp4"
    compose_short(
        clip, audio_for_compose, ass, cfg, out,
        image_paths=image_paths,
        duration=target,
        image_duration=image_duration,
        mute_source_audio=using_bgm,
    )
    step(f"      -> {out}")
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
