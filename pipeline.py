#!/usr/bin/env python3
"""Roblox Shorts autopilot: download gameplay -> Chatterbox TTS -> 9:16 short."""

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


# Module-level cache for the Chatterbox model. Loaded once, kept in VRAM for
# the lifetime of the GUI process. ~3-4 GB VRAM. None=not tried, False=tried
# and failed (no torch / no chatterbox-tts / OOM), otherwise the model.
_CHATTERBOX_MODEL = None

# Same cache for the MULTILINGUAL Chatterbox model (German/other-language voice
# cloning). Loaded only when German cloning is requested. None/False/model.
_CHATTERBOX_ML_MODEL = None

# Module-level cache for the Piper voice (German TTS). Piper is CPU-friendly
# (~100 MB RAM, ~real-time on a modern CPU), so no VRAM impact. We cache per
# voice name so switching voices at runtime re-loads cleanly.
_PIPER_VOICE = None         # None=not tried, False=failed, else the voice
_PIPER_VOICE_NAME = ""

# Where Piper .onnx + .onnx.json files get cached on disk. Picked the same
# spot Piper's own CLI uses by convention so future native installs share
# the cache.
_PIPER_CACHE_DIR = Path.home() / ".cache" / "piper-voices"

# Curated set of German voices that work well for shorts. Keys are the
# logical name we expose in config; values are the rhasspy/piper-voices
# huggingface paths to the .onnx file (the .onnx.json sits next to it).
_PIPER_MODEL_URLS = {
    # Thorsten Müller — male, the de-facto German open-source TTS voice.
    # "medium" is the sweet spot: ~63 MB, very natural prosody, near-real-time.
    "de_DE-thorsten-medium": "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium/de_DE-thorsten-medium.onnx",
    # Higher quality, larger, slower (~115 MB).
    "de_DE-thorsten-high":   "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx",
    # Female alternative.
    "de_DE-eva_k-x_low":     "https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/eva_k/x_low/de_DE-eva_k-x_low.onnx",
}

# German stopwords used by the auto-detect fallback. Only need a handful —
# any text with >10% of these is overwhelmingly German.
_GERMAN_STOPWORDS = frozenset({
    "der", "die", "das", "und", "ist", "nicht", "ein", "eine", "mit",
    "auf", "für", "fuer", "von", "im", "wir", "du", "ich", "sie", "er",
    "es", "den", "dem", "des", "zu", "zum", "zur", "auch", "wie", "so",
    "noch", "nur", "schon", "aber", "oder", "mal", "doch", "ja",
})

# Opt-in upgrades (resume, YT optimizer, reframe v2). The modules are
# tolerant of missing optional deps and produce no behavior change unless
# the matching job flag is set.
from state_manager import Logger, StateStore, Step, set_subclip_done, set_subclip_failed, get_subclip_status
import youtube_optimizer as _yt_opt
import reframe_v2 as _reframe2


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _loads_lenient(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return json.loads(_TRAILING_COMMA_RE.sub(r"\1", text))


@dataclass
class Config:
    output_dir: Path
    # Chatterbox TTS (Resemble AI, Apache 2.0). Runs locally on GPU, supports
    # zero-shot voice cloning via a reference audio file. No API key needed.
    # Primary training language is English; German output is achievable but
    # quality varies.
    tts_reference_audio: str   # optional path to a voice sample for cloning (Chatterbox/EN only)
    # German voice cloning (opt-in): when tts_de_clone is on, German uses the
    # multilingual Chatterbox model with cloning instead of the fixed Piper
    # voice. tts_reference_audio_de is an optional German-specific sample;
    # empty → reuse tts_reference_audio.
    tts_de_clone: bool
    tts_reference_audio_de: str
    tts_exaggeration: float    # 0..1, default 0.5 (Chatterbox emotion; 0=flat, 1=dramatic)
    tts_cfg_weight: float      # 0..1, default 0.5 (Chatterbox guidance; lower=more natural)
    # Auto-clean the clone reference (mono/trim/normalize) before Chatterbox
    # uses it. True for any raw recording; set False if you hand it a sample
    # that's already perfectly prepared.
    tts_clone_autoprep: bool
    # Language dispatcher: "de" → Piper (offline native German), "en" →
    # Chatterbox (offline English w/ voice cloning), "auto" → heuristic
    # on the voiceover text.
    tts_language: str
    # Piper voice model name; see _PIPER_MODEL_URLS in pipeline.py for the
    # curated set. Empty = use the default (de_DE-thorsten-medium).
    tts_piper_model: str
    whisper_model: str
    # Opt-in WhisperX for word-level captions. WhisperX runs the same
    # faster-whisper transcription, then force-aligns every word with a
    # wav2vec2 model -> noticeably tighter karaoke timing (no drift). Free,
    # local, GPU. Falls back to plain faster-whisper if whisperx isn't
    # installed or alignment fails, so it never breaks a render.
    use_whisperx: bool
    # Path to a SEPARATE python.exe (its own venv) that has whisperx + a
    # compatible torch installed. WhisperX 3.8.x needs torch ~2.8 / numpy 2 /
    # transformers 4.x, which conflict head-on with Chatterbox in the main venv
    # (torch cu124 / numpy<2 / transformers 5.2.0). So we run WhisperX
    # out-of-process in its own env. Empty = use the main interpreter (only
    # works if whisperx is somehow installed here too — usually it can't be).
    whisperx_python: str
    # Max height for the downloaded gameplay source. 1080 default; drop to 720
    # for much faster downloads (a vertical short is cropped+scaled anyway).
    download_max_height: int
    target_w: int
    target_h: int
    ducking_db: float
    # Video encoder: "auto" (use NVENC on an NVIDIA GPU, else x264), "nvenc"
    # (force GPU), or "cpu" (force x264). NVENC is 5-10x faster on an RTX card.
    video_encoder: str
    gemini_api_key: str
    gemini_model: str
    # Optional override for the multi-clip moment-picker. Defaults to
    # gemini_model when empty. Set to "gemini-2.5-pro" in config.json to get
    # noticeably better viral-moment picks at the cost of more free-tier
    # quota per run.
    gemini_moments_model: str
    cloudflare_account_id: str
    cloudflare_api_token: str
    cloudflare_image_model: str
    # Local Claude Code CLI as an LLM provider for the text tasks (moment-
    # picking, script, metadata). Uses the logged-in `claude` CLI and its
    # subscription auth — no API key, no per-call cost. Opt-in because it's
    # slower than Gemini and only makes sense for personal/local use.
    # `claude_cli_model` is passed to `claude --model` (e.g. "sonnet",
    # "opus"); empty = the CLI's default.
    use_claude_cli: bool
    claude_cli_model: str
    claude_cli_path: str
    # Local Grok Build CLI as an IMAGE provider (the AI-render path). Uses the
    # logged-in `grok` CLI + SuperGrok subscription auth — no API key, no per-
    # image cost. Opt-in (slower than an API call, counts against subscription
    # limits). When on, it's tried FIRST in the AI-render cascade, with
    # Cloudflare Flux / Pollinations behind it. grok_cli_extra_args lets you
    # tweak the headless invocation (e.g. an auto-approve flag) without a code
    # change.
    use_grok_cli: bool
    grok_cli_path: str
    grok_cli_extra_args: str
    # Higgsfield CLI as an AI-VIDEO provider for the video beats (subscription,
    # browser-login, no API key). When on (and a model is set), it's tried
    # FIRST for video beats, with Pexels stock B-roll as fallback. Opt-in:
    # video generation is slow (~1-3 min/clip) and costs subscription credits.
    use_higgsfield: bool
    higgsfield_cli_path: str
    higgsfield_video_model: str
    higgsfield_extra_args: str
    # Higgsfield as an AI-IMAGE provider (e.g. nano_banana_2). When
    # use_higgsfield_images is on, it's tried FIRST for AI image beats (before
    # Grok/Cloudflare/Pollinations) — good for the faceless stickman/doodle
    # videos. Separate from the video integration above.
    use_higgsfield_images: bool
    higgsfield_image_model: str
    higgsfield_image_extra_args: str
    # AI-image style. "auto" (default) = the scene planner picks the medium per
    # beat (Roblox-render for game characters, photoreal for real/abstract
    # subjects). "roblox"/"realistic"/"cinematic" force one look for the whole
    # video; any other non-empty string is used verbatim as the style suffix.
    image_style: str
    # In "auto", the max number of AI beats that may be Roblox 3D renders; any
    # beyond this are rewritten into photoreal real-world scenes. 0 = never
    # Roblox even in auto. Ignored when image_style forces a look.
    image_roblox_max: int
    # Seconds to pause between AI image generations. 0 = off (default). Raise it
    # (e.g. 2-5) if a long image run trips a thermal / power shutdown on a
    # marginal PSU/cooling setup — gives the GPU time to cool between renders.
    image_cooldown_secs: float
    # Optional override for the color-emoji font used to render caption
    # emojis. Empty = auto-detect (Segoe UI Emoji on Windows, Noto on Linux).
    emoji_font_path: str
    # Optional free Pixabay API key for reliable real-photo beats. Empty =
    # fall back to the no-key sources (Openverse / Wikimedia).
    pixabay_api_key: str
    # yt-dlp auth to get past YouTube's "Sign in to confirm you're not a bot"
    # / 429. youtube_cookies_from_browser: "chrome"/"firefox"/"edge"/"brave"/
    # "" — reads the logged-in cookies from that browser. youtube_cookies_file:
    # path to a cookies.txt export. File wins if both are set.
    youtube_cookies_from_browser: str
    youtube_cookies_file: str
    # Optional free Pexels API key for stock B-roll VIDEOS in the middle
    # slot. https://www.pexels.com/api/ — 30s signup, no card. Empty = the
    # pipeline keeps using AI renders / photos only (today's behavior).
    pexels_api_key: str
    # Telegram remote control (bot.py). Empty token = bot disabled. Only the
    # allowed chat id may trigger renders. Optional music/sfx dirs let bot jobs
    # use background audio.
    telegram_bot_token: str
    telegram_allowed_chat_id: int
    telegram_music_dir: str
    telegram_sfx_dir: str
    # Your exact preferred short settings for bot renders (any job key from the
    # GUI: caption_color, caption_font_size, subscribe_sting_file, voice_tempo,
    # image_size, …). Overlaid on the bot's built-in short defaults; a per-
    # message value still wins. Empty {} = just use the built-in defaults.
    telegram_defaults: dict

    @classmethod
    def load(cls, path: Path) -> "Config":
        data = _loads_lenient(path.read_text(encoding="utf-8"))
        w, h = data.get("target_resolution", [1080, 1920])
        default_gemini = data.get("gemini_model", "gemini-2.5-flash")
        return cls(
            output_dir=Path(data["output_dir"]).expanduser(),
            tts_reference_audio=data.get("tts_reference_audio", ""),
            tts_de_clone=bool(data.get("tts_de_clone", False)),
            tts_reference_audio_de=data.get("tts_reference_audio_de", ""),
            tts_exaggeration=float(data.get("tts_exaggeration", 0.5)),
            tts_cfg_weight=float(data.get("tts_cfg_weight", 0.5)),
            tts_clone_autoprep=bool(data.get("tts_clone_autoprep", True)),
            tts_language=str(data.get("tts_language", "auto")).lower(),
            tts_piper_model=str(data.get("tts_piper_model", "de_DE-thorsten-medium")),
            whisper_model=data.get("whisper_model", "small"),
            use_whisperx=bool(data.get("use_whisperx", False)),
            whisperx_python=str(data.get("whisperx_python", "")).strip(),
            download_max_height=int(data.get("download_max_height", 1080)),
            target_w=int(w),
            target_h=int(h),
            ducking_db=float(data.get("ducking_db", -18)),
            video_encoder=str(data.get("video_encoder", "auto")).strip().lower() or "auto",
            gemini_api_key=data.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", ""),
            gemini_model=default_gemini,
            gemini_moments_model=data.get("gemini_moments_model", default_gemini),
            cloudflare_account_id=data.get("cloudflare_account_id") or os.environ.get("CLOUDFLARE_ACCOUNT_ID", ""),
            cloudflare_api_token=data.get("cloudflare_api_token") or os.environ.get("CLOUDFLARE_API_TOKEN", ""),
            cloudflare_image_model=data.get("cloudflare_image_model", "@cf/black-forest-labs/flux-1-schnell"),
            use_claude_cli=bool(data.get("use_claude_cli", False)),
            claude_cli_model=str(data.get("claude_cli_model", "")),
            claude_cli_path=str(data.get("claude_cli_path", "claude")),
            use_grok_cli=bool(data.get("use_grok_cli", False)),
            grok_cli_path=str(data.get("grok_cli_path", "grok")),
            grok_cli_extra_args=str(data.get("grok_cli_extra_args", "")),
            use_higgsfield=bool(data.get("use_higgsfield", False)),
            higgsfield_cli_path=str(data.get("higgsfield_cli_path", "higgsfield")),
            higgsfield_video_model=str(data.get("higgsfield_video_model", "")),
            higgsfield_extra_args=str(data.get("higgsfield_extra_args", "")),
            use_higgsfield_images=bool(data.get("use_higgsfield_images", False)),
            higgsfield_image_model=str(data.get("higgsfield_image_model", "nano_banana_2")),
            higgsfield_image_extra_args=str(data.get("higgsfield_image_extra_args", "")),
            image_style=str(data.get("image_style", "auto")).strip() or "auto",
            image_roblox_max=int(data.get("image_roblox_max", 2)),
            image_cooldown_secs=float(data.get("image_cooldown_secs", 0.0)),
            emoji_font_path=str(data.get("emoji_font_path", "")),
            pixabay_api_key=data.get("pixabay_api_key") or os.environ.get("PIXABAY_API_KEY", ""),
            youtube_cookies_from_browser=str(data.get("youtube_cookies_from_browser", "")).strip(),
            youtube_cookies_file=str(data.get("youtube_cookies_file", "")).strip(),
            pexels_api_key=data.get("pexels_api_key") or os.environ.get("PEXELS_API_KEY", ""),
            telegram_bot_token=str(data.get("telegram_bot_token", "")).strip(),
            telegram_allowed_chat_id=int(data.get("telegram_allowed_chat_id", 0) or 0),
            telegram_music_dir=str(data.get("telegram_music_dir", "")),
            telegram_sfx_dir=str(data.get("telegram_sfx_dir", "")),
            telegram_defaults=dict(data.get("telegram_defaults", {}) or {}),
        )

    def validate(self) -> tuple[list[str], list[str]]:
        """Run sanity checks on the loaded config. Returns (errors, warnings).
        Errors block startup; warnings are surfaced to the user but the GUI
        boots anyway. Called at GUI launch so the user gets clear feedback
        before they wait through a download just to hit an "API key missing"
        crash three minutes in."""
        errors: list[str] = []
        warnings: list[str] = []

        # output_dir must be creatable (we don't require it to exist yet —
        # mkdir at first job is fine, but the parent has to be writable).
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            errors.append(f"output_dir {self.output_dir} can't be created/written: {e}")

        # Gemini is normally the required text backend — script generation
        # needs it. But if the local Claude CLI is enabled it can serve as
        # the text backend instead, so Gemini becomes optional then.
        if not self.gemini_api_key:
            if self.use_claude_cli:
                warnings.append(
                    "gemini_api_key not set, but use_claude_cli is on — "
                    "text tasks will go through the local Claude CLI. Note "
                    "there's no Gemini fallback if the CLI is unavailable."
                )
            else:
                errors.append(
                    "gemini_api_key missing. Either set it in config.json or "
                    "export GEMINI_API_KEY in the environment. Free key at "
                    "https://aistudio.google.com/apikey"
                )

        if not self.cloudflare_account_id or not self.cloudflare_api_token:
            warnings.append(
                "cloudflare_account_id / cloudflare_api_token not set — "
                "image overlays and Cloudflare LLM fallbacks will be unavailable. "
                "Pipeline still runs without them."
            )

        # Resolution sanity. Catches typos like target_resolution: [108, 192]
        # (which would technically work but produce a 108×192 thumbnail).
        if self.target_w < 240 or self.target_h < 240:
            errors.append(
                f"target_resolution {self.target_w}×{self.target_h} is too "
                "small. Use [1080, 1920] for shorts or [1920, 1080] for "
                "landscape (the GUI's Output-Format toggle overrides this)."
            )

        # Whisper model. faster-whisper accepts a fixed enum; an unknown
        # value would error 10 minutes into a job during transcription.
        known_whisper = {"tiny", "tiny.en", "base", "base.en", "small",
                         "small.en", "medium", "medium.en", "large",
                         "large-v1", "large-v2", "large-v3", "distil-small.en",
                         "distil-medium.en", "distil-large-v2", "distil-large-v3"}
        if self.whisper_model not in known_whisper:
            warnings.append(
                f"whisper_model {self.whisper_model!r} not in the known list "
                f"({sorted(known_whisper)}). Transcription may fail to load."
            )

        # TTS language must be one of the dispatcher's known values.
        if self.tts_language not in ("auto", "de", "en"):
            warnings.append(
                f"tts_language {self.tts_language!r} unknown — falling back "
                "to 'auto'. Valid: 'de', 'en', 'auto'."
            )

        # Chatterbox knobs bounded 0..1.
        for name, val in [("tts_exaggeration", self.tts_exaggeration),
                          ("tts_cfg_weight", self.tts_cfg_weight)]:
            if not 0.0 <= val <= 1.0:
                warnings.append(f"{name}={val} outside [0..1] range; Chatterbox may behave oddly")

        # Voice-cloning reference audio path — only check existence if set.
        if self.tts_reference_audio:
            ref = Path(self.tts_reference_audio).expanduser()
            if not ref.is_file():
                warnings.append(
                    f"tts_reference_audio {ref} not found — Chatterbox will fall "
                    "back to its default voice instead of cloning."
                )

        return errors, warnings


def _release_gpu_memory() -> None:
    """Best-effort release of CUDA VRAM held by the current process. Called
    between heavy stages (Whisper / YOLO / FaceMesh) to keep VRAM from
    creeping up across long multi-clip runs. No-op when torch isn't
    installed or CUDA isn't available."""
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:
        pass


def _unload_tts_model() -> None:
    """Drop the resident Chatterbox TTS model (~3-4 GB VRAM) and free it.
    The voiceover is already rendered to disk by the time we reach the image
    stage, so keeping the model loaded just pins VRAM and adds thermal/power
    load during the long image-generation loop for no benefit. Re-loaded lazily
    if needed again (e.g. the long-form voice-extend path runs before images)."""
    global _CHATTERBOX_MODEL
    if _CHATTERBOX_MODEL in (None, False):
        return
    try:
        model = _CHATTERBOX_MODEL
        _CHATTERBOX_MODEL = None
        try:
            import torch  # type: ignore
            # Move any tensors off the GPU before dropping the reference.
            if hasattr(model, "to"):
                try: model.to("cpu")
                except Exception: pass
        except Exception:
            pass
        del model
    except Exception:
        _CHATTERBOX_MODEL = None
    _release_gpu_memory()


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


def ytdlp_cookie_args(cfg) -> list:
    """Build yt-dlp cookie CLI args from config. Cookies get past YouTube's
    "Sign in to confirm you're not a bot" wall and 429 rate-limits, because
    the requests then look like a logged-in browser. A cookies.txt file wins
    over a browser name if both are set. Returns [] when neither is set."""
    if cfg is None:
        return []
    f = (getattr(cfg, "youtube_cookies_file", "") or "").strip()
    if f and Path(f).expanduser().is_file():
        return ["--cookies", str(Path(f).expanduser())]
    b = (getattr(cfg, "youtube_cookies_from_browser", "") or "").strip()
    if b:
        return ["--cookies-from-browser", b]
    return []


def _ytdlp_error_hint(output: str, had_cookies: bool) -> str:
    """Turn a raw yt-dlp failure into an actionable hint for the GUI."""
    low = (output or "").lower()
    # Missing JS runtime: yt-dlp needs one (Deno recommended) to solve
    # YouTube's player challenges. Without it formats go missing and the
    # bot-check fires far more often — fixing this often fixes the
    # "not a bot" error too.
    js_hint = ""
    if "js runtime" in low or "jsruntime" in low or " ejs " in low or "/ejs" in low:
        js_hint = ("\n\n→ yt-dlp braucht eine JavaScript-Runtime für YouTube. "
                   "Einmalig installieren:  winget install DenoLand.Deno  "
                   "— danach Terminal/GUI neu starten. Das behebt oft auch "
                   "den 'not a bot'-Fehler gleich mit.")
    # Cookie DB locked (browser is running) or encrypted (Chrome v127+ App-Bound
    # Encryption, yt-dlp #7271). Almost always: the browser we read cookies from
    # is open. Closing it fixes the common case; a cookies.txt export sidesteps
    # both the lock and the newer encryption entirely.
    if "could not copy" in low and "cookie" in low:
        return js_hint + ("\n\n→ yt-dlp kommt nicht an die Browser-Cookies: der Browser "
                "läuft (DB gesperrt) oder Chrome verschlüsselt sie (v127+). "
                "Browser GANZ schließen und neu starten — oder am stabilsten "
                "eine cookies.txt exportieren und in config.json "
                '"youtube_cookies_file" setzen (oder auf "edge"/"firefox" '
                "umstellen).")
    if any(s in low for s in ("sign in to confirm", "not a bot", "429",
                              "too many requests", "confirm you")):
        if had_cookies:
            return js_hint + ("\n\n→ YouTube blockt trotz Cookies. Browser GANZ schließen "
                    "(damit yt-dlp die Cookies lesen kann), ein paar Minuten "
                    "warten (429), oder eine frische cookies.txt exportieren.")
        return js_hint + ("\n\n→ YouTube verlangt Login. Am stabilsten: cookies.txt "
                "exportieren (Browser-Extension 'Get cookies.txt LOCALLY') und in "
                'config.json "youtube_cookies_file" setzen. Alternativ '
                '"youtube_cookies_from_browser": "firefox" — bei Chrome/Edge '
                "scheitert das oft an der Cookie-Verschlüsselung (v127+).")
    if "requested format is not available" in low or "format" in low and "not available" in low:
        return js_hint + "\n\n→ Format nicht verfügbar — evtl. ist das Video privat/gelöscht/region-locked."
    if "video unavailable" in low or "private video" in low:
        return js_hint + "\n\n→ Video ist privat/gelöscht/nicht verfügbar."
    return js_hint


def download_gameplay(url: str, out_dir: Path, cookies: list | None = None,
                      max_height: int = 1080) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / "%(id)s.%(ext)s")
    h = max(360, int(max_height or 1080))
    cmd = [
        sys.executable, "-m", "yt_dlp",
        *(cookies or []),
        "--no-playlist",                       # never accidentally pull a whole playlist
        "--concurrent-fragments", "5",         # download DASH fragments in parallel — big speedup
        "--retries", "3", "--fragment-retries", "3",
        "-f", f"bv*[height<={h}]+ba/b[height<={h}]",
        "--merge-output-format", "mp4",
        "-o", template,
        url,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        combined = f"{proc.stdout or ''}\n{proc.stderr or ''}".strip()
        tail = combined[-700:]
        hint = _ytdlp_error_hint(combined, bool(cookies))
        raise RuntimeError(f"yt-dlp download failed (exit {proc.returncode}):\n{tail}{hint}")
    files = sorted(out_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise RuntimeError("yt-dlp produced no mp4")
    return files[0]


def list_channel_videos(channel_url: str, limit: int = 50, cookies: list | None = None) -> list:
    """Return [{id, url, title}, ...] for the most recent videos on a channel."""
    result = subprocess.run(
        [sys.executable, "-m", "yt_dlp",
         *(cookies or []),
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
                              title_filter: list | None = None,
                              cookies: list | None = None) -> dict:
    used = set()
    if used_path.exists():
        try:
            used = set(json.loads(used_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            used = set()
    videos = list_channel_videos(channel_url, limit, cookies=cookies)
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


SCRIPT_PROMPT_SHORT = """Schreibe ein energetisches, jugendliches Skript fuer einen YouTube Short ueber Roblox auf Deutsch.

Thema: {topic}

Anforderungen:
- Laenge: ca. {target_low}-{target_high} Sekunden Sprechzeit (etwa {words_low}-{words_high} deutsche Woerter)
- STRUKTUR (Curiosity Gap — entscheidend fuer Watchtime):
  1. OEFFNE mit einer Frage oder einem ungeloesten Raetsel/Versprechen, das sofort fesselt — und verrate die Antwort NOCH NICHT (z.B. "Niemand wusste, was hinter dieser Tuer war...", "Das haette nie passieren duerfen...").
  2. Baue in der Mitte Spannung auf und eskaliere — gib Andeutungen, aber halte die Aufloesung bewusst zurueck.
  3. Liefere die AUFLOESUNG / den Payoff erst in den LETZTEN ~5 Sekunden, direkt vor dem Call-to-Action. Der Zuschauer muss bis zum Ende dranbleiben, um die versprochene Antwort zu bekommen.
  4. Ganz am Schluss ein kurzer Call-to-Action ("Folg fuer Teil 2...", "Lass ein Like da...").
- Kein Markdown, keine Anfuehrungszeichen, keine Regie-Anweisungen
- Gib NUR den reinen Sprechertext aus, sonst nichts"""


SCRIPT_PROMPT_LONG = """Schreibe ein vollstaendiges, energetisches Skript fuer ein YouTube-Video ueber Roblox auf Deutsch. Das ist KEIN Short — es soll ein langes, ausfuehrliches Video werden.

Thema: {topic}

Anforderungen:
- ZWINGEND ca. {target_low}-{target_high} Sekunden Sprechzeit. Das sind etwa {words_low}-{words_high} deutsche Woerter — bitte WIRKLICH so viel schreiben. Nicht kuerzen!
- Starker Hook in den ersten 10 Sekunden
- Mehrere Action-Beats und Wendungen ueber den Verlauf
- Detaillierte Story / Erzaehlung, keine Stichpunkte
- Mehrere "Pattern Interrupts" mit "Aber Moment...", "Du wirst nicht glauben was als naechstes...", "Krass, oder?"
- Call-to-Action am Ende ("Abonniere fuer mehr...", "Like wenn das wild war...")
- Kein Markdown, keine Anfuehrungszeichen, keine Regie-Anweisungen, keine Kapitel-Ueberschriften
- Gib NUR den reinen Sprechertext aus, sonst nichts
- WICHTIG: Wenn dein erster Entwurf zu kurz ist, schreibe weiter bis die Wortanzahl stimmt"""


SCRIPT_PROMPT_SHORT_EN = """Write an energetic, youthful script for a YouTube Short about Roblox in English.

Topic: {topic}

Requirements:
- Length: about {target_low}-{target_high} seconds of speech (around {words_low}-{words_high} English words)
- STRUCTURE (curiosity gap — critical for watch time):
  1. OPEN with a question or an unresolved mystery/promise that grabs attention instantly — and DO NOT reveal the answer yet (e.g. "Nobody knew what was behind that door...", "This was never supposed to happen...").
  2. Build tension through the middle and escalate — drop hints but deliberately withhold the resolution.
  3. Deliver the PAYOFF / answer only in the FINAL ~5 seconds, right before the call to action. The viewer must watch to the end to get the answer they were promised.
  4. End with a short call to action ("Follow for part 2...", "Like if that was wild...").
- No markdown, no quotes, no stage directions
- Output ONLY the speaker text, nothing else"""


SCRIPT_PROMPT_LONG_EN = """Write a complete, energetic script for a long-form YouTube video about Roblox in English. This is NOT a Short — it should be a long, detailed video.

Topic: {topic}

Requirements:
- MUST be approximately {target_low}-{target_high} seconds of speech. That's {words_low}-{words_high} English words — please WRITE that much, do not cut short!
- Strong hook in the first 10 seconds
- Multiple action beats and twists throughout
- Detailed story / narrative, no bullet points
- Multiple pattern interrupts: "But wait...", "You won't believe what happens next...", "Crazy, right?"
- Call to action at the end ("Subscribe for more...", "Like if that was wild...")
- No markdown, no quotes, no stage directions, no chapter headings
- Output ONLY the speaker text, nothing else
- IMPORTANT: if your first draft is too short, keep writing until you hit the word count"""


SCRIPT_PROMPT = SCRIPT_PROMPT_SHORT  # back-compat alias for any external callers


# Continuation prompts for the top-up loop. Gemini-2.5-flash routinely
# delivers ~75-80% of the requested length even when the prompt screams
# "MUST". Top-up keeps asking for the rest until we're within 15% of
# target or hit max_attempts.
CONTINUATION_PROMPT_DE = """Schreibe NUR die Fortsetzung dieses YouTube-Skripts. Etwa {add_words} Woerter mehr. Selbe Energie und Stil, kein Recap, KEINE "Zum Schluss", "Zusammenfassend" oder "Abonniere fuer mehr" Phrasen — das Video geht einfach mittendrin weiter. Schreibe so, als waere es Satz fuer Satz die direkte Fortsetzung. Gib NUR den zusaetzlichen Sprechertext aus, sonst nichts.

Bisheriges Skript (NICHT wiederholen, NICHT zitieren):
---
{previous}
---"""


CONTINUATION_PROMPT_EN = """Write ONLY the continuation of this YouTube script. About {add_words} more words. Same energy and style, no recap, NO "in summary", "to wrap up", or "subscribe for more" phrases — the video just keeps going mid-stream. Write as if it's the direct next sentence. Output ONLY the additional speaker text, nothing else.

Existing script so far (do NOT repeat, do NOT quote back):
---
{previous}
---"""


# Words-per-second estimates for word-count → speech-duration math.
# Empirically Chatterbox EN runs ~2.5 wps natural; Piper DE-Thorsten
# ~2.4 wps. Used to decide if a script is short enough to top up.
_WPS_EN = 2.5
_WPS_DE = 2.4


def _estimate_script_seconds(text: str, language: str) -> float:
    """Estimate TTS speech duration in seconds from word count."""
    wps = _WPS_EN if (language or "de").lower() == "en" else _WPS_DE
    return len(text.split()) / max(wps, 0.1)


def _clean_user_script(text: str) -> str:
    """Strip the first line if it's an obvious LLM-assistant preamble. Users
    sometimes copy-paste a whole chat response that starts with "Here is the
    script you asked for:" — which Chatterbox then dutifully reads aloud.

    Only strips when the first line is clearly meta (matches a well-known
    intro pattern AND ends with a colon AND is short enough to be a header
    not real content). Conservative on purpose: false-strip of legit
    content would be worse than reading one extra sentence."""
    text = (text or "").strip()
    if not text:
        return text
    lines = text.split("\n", 1)
    if len(lines) != 2:
        return text
    first = lines[0].strip()
    rest = lines[1].strip()
    if not rest:
        return text
    # Length guard. Lower bound at 20 chars (shortest plausible preamble:
    # "Here's the script:"); upper at 400 (longer than that is real content).
    if not (20 < len(first) < 400):
        return text
    if not first.endswith(":"):
        return text
    preamble_starters = re.compile(
        r"^(Here\s+is|Here'?s|Below\s+is|This\s+is|Sure|Of\s+course|Certainly|"
        r"Absolutely|Okay|Alright|I'?ve\s+written|I\s+have\s+written|"
        r"As\s+requested|Hier\s+ist|Hier\s+hast\s+du|Klar|Natuerlich|Naturlich)\b",
        re.IGNORECASE,
    )
    if preamble_starters.match(first):
        return rest
    return text


def _sanitize_script_for_tts(text: str) -> str:
    """Strip non-spoken artifacts so the TTS only ever reads clean prose.
    Removes timestamps (0:07 / 00:07 / 1:02:03), Danny-Why "00_07 - " prefixes,
    markdown headers/emphasis, and bracketed stage directions. Conservative:
    must never delete a normal hyphen, a colon in real speech, or apostrophes."""
    if not text:
        return text

    def _strip_line(s: str) -> str:
        # "00_07 - " / "00:07 - " / "0:07 — " timestamp+dash prefix at line start,
        # applied repeatedly so a single-line "0:07 - A 0:14 - B" loses each one.
        prev = None
        while prev != s:
            prev = s
            s = re.sub(r"^\s*\d{1,2}[:_]\d{2}(?:[:_]\d{2})?\s*[-–—]\s*", "", s)
            # Bare leading timestamp at line start: "0:07", "00:07", "1:02:03".
            s = re.sub(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\b[.\)]?\s*", "", s)
        # Markdown header markers at line start ("# ", "## "...).
        s = re.sub(r"^\s*#{1,6}\s+", "", s)
        # Bullet "- " / "* " at line start ONLY when it precedes a timestamp.
        s = re.sub(r"^\s*[-*]\s+(?=\d{1,2}[:_]\d{2})", "", s)
        return s

    text = "\n".join(_strip_line(line) for line in text.split("\n"))
    # Stage directions — keyword-gated in BOTH bracket styles so legit speech
    # like "[absolutely insane]" or "(my brother)" survives; only [SFX...],
    # [music], (PAUSE), (cut to ...) etc. are removed.
    _direction = r"(?:SFX|SOUND|MUSIC|BEAT|PAUSE|CUT|VFX|B-?ROLL|INTRO|OUTRO|TRANSITION)"
    text = re.sub(rf"\[\s*{_direction}[^\]\n]*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\[\s*(?:pause|music|beat)\s*\]", "", text, flags=re.IGNORECASE)
    text = re.sub(rf"\(\s*{_direction}[^)\n]*\)", "", text, flags=re.IGNORECASE)
    # Inline timestamps — ONLY in clear timestamp contexts, so real speech like
    # "John 3:16", "a 2:1 ratio" or "meet me at 5:30" is preserved:
    #   • parenthesized "(0:42)" / "[1:23]"
    #   • dash-bracketed segment markers "- 0:42 -"
    text = re.sub(r"[\(\[]\s*\d{1,2}:\d{2}(?::\d{2})?\s*[\)\]]", "", text)
    text = re.sub(r"(?<=[-–—])\s*\d{1,2}:\d{2}(?::\d{2})?\s*(?=[-–—])", " ", text)
    # Markdown emphasis: asterisks wholesale; underscores only as _word_ wrappers
    # (never a bare hyphen or snake_case mid-word underscore).
    text = re.sub(r"\*{1,3}", "", text)
    text = re.sub(r"(?<!\w)_(?=\w)|(?<=\w)_(?!\w)", "", text)
    # Tidy orphaned punctuation/separators left behind by removals.
    text = re.sub(r"\(\s*\)", "", text)             # empty parens "()"
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)    # " ," → ","
    text = re.sub(r"[-–—]\s+[-–—]", "", text)       # collapse "- -" left by removals
    text = re.sub(r"(?m)^\s*[-–—]\s+", "", text)    # leftover leading dash on a line
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _gemini_continuation(previous: str, cfg: "Config", add_words: int,
                         language: str = "de", on_step=None) -> str:
    """Ask Gemini for a chunk that extends `previous` by ~add_words words.
    Returns just the new text; caller concatenates."""
    template = CONTINUATION_PROMPT_EN if (language or "de").lower() == "en" else CONTINUATION_PROMPT_DE
    prompt_text = template.format(previous=previous.strip(), add_words=add_words)
    body = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.9,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    text = _complete_text(prompt_text, cfg, prefer_claude=True, gemini_body=body, on_step=on_step)
    if not text:
        raise RuntimeError("continuation returned empty text")
    return text


# Max words to request in a SINGLE continuation call. LLMs reliably produce a
# few hundred words per turn but ignore "write 900 more words" and stop early —
# which is exactly why one big top-up request only recovered ~half the deficit
# (600s asked → ~340s out). We request the deficit in bounded chunks and loop.
_CONTINUATION_CHUNK_WORDS = 280


def _script_tail(text: str, words: int = 380) -> str:
    """Last `words` words of the script — enough context for a coherent
    continuation without handing the model the whole (complete-looking) script,
    which makes it write a conclusion instead of continuing."""
    parts = (text or "").split()
    return " ".join(parts[-words:]) if len(parts) > words else (text or "")


def _continuation_block(context: str, cfg: "Config", want_words: int,
                        language: str, on_step=None, max_rounds: int = 14) -> str:
    """Produce ~want_words of NEW continuation text for `context`, looping
    bounded chunks because the LLM under-delivers on any single call. Returns
    just the new text (caller concatenates). Stops on a stall (two near-empty
    rounds) or a per-call error."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass

    added_parts: list[str] = []
    added = 0
    stalls = 0
    ctx = context
    for _ in range(max_rounds):
        if added >= want_words:
            break
        ask = min(want_words - added, _CONTINUATION_CHUNK_WORDS)
        if ask < 40:
            break
        try:
            chunk = _gemini_continuation(_script_tail(ctx), cfg, ask,
                                         language=language, on_step=on_step)
        except Exception as e:
            log(f"      continuation call failed: {str(e)[:120]} — stopping")
            break
        w = len(chunk.split())
        if w < 25:
            stalls += 1
            if stalls >= 2:
                break
            continue
        stalls = 0
        added_parts.append(chunk.strip())
        ctx = ctx.rstrip() + " " + chunk
        added += w
    return " ".join(added_parts)


def _extend_script_to_target(script: str, cfg: "Config", target_seconds: float,
                             language: str, on_step=None,
                             accept_frac: float = 0.92) -> str:
    """Grow `script` until its ESTIMATED speech duration is within accept_frac
    of target_seconds. Note: the estimate uses a fixed wps and is only a first
    approximation — the authoritative length correction happens after TTS in
    _grow_voiceover_to_target, which measures the real spoken duration."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass

    wps = _WPS_EN if (language or "de").lower() == "en" else _WPS_DE
    target_words = int(target_seconds * accept_frac * wps)
    current_words = len(script.split())
    deficit = target_words - current_words
    if deficit < 40:
        return script
    log(f"      extending script: {current_words}w → ~{target_words}w "
        f"(target ~{target_seconds:.0f}s)")
    block = _continuation_block(script, cfg, deficit, language, on_step=on_step)
    if block:
        script = script.rstrip() + " " + block.lstrip()
    final_words = len(script.split())
    log(f"      final script: {final_words}w (~{final_words / wps:.0f}s est, "
        f"target ~{target_seconds:.0f}s)")
    return script


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


# Cache the resolved claude CLI path. None=untested, ""=not found, else the
# absolute path (incl. .cmd/.exe on Windows — subprocess needs the FULL path
# to run a .cmd, the bare name fails).
_CLAUDE_CLI_PATH: str | None = None

# Same cache for the Grok Build CLI (image provider). None=untested.
_GROK_CLI_PATH: str | None = None

# Same cache for the Higgsfield CLI (AI video/image provider). None=untested.
_HIGGSFIELD_CLI_PATH: str | None = None


def _resolve_claude_cli(claude_path: str = "claude") -> str:
    """Return the absolute path to the claude executable, or "" if not found.
    Cached. On Windows shutil.which resolves "claude" → "...\\claude.cmd";
    we must pass that full path to subprocess (running a bare "claude" .cmd
    without the resolved path raises FileNotFoundError)."""
    global _CLAUDE_CLI_PATH
    if _CLAUDE_CLI_PATH is not None:
        return _CLAUDE_CLI_PATH
    import shutil
    # If the user gave an explicit path that exists, use it as-is.
    if claude_path and Path(claude_path).expanduser().is_file():
        _CLAUDE_CLI_PATH = str(Path(claude_path).expanduser())
        return _CLAUDE_CLI_PATH
    # On PATH? (resolves claude.cmd/.exe on Windows)
    found = shutil.which(claude_path) or shutil.which("claude")
    if found:
        _CLAUDE_CLI_PATH = found
        return _CLAUDE_CLI_PATH
    # Common npm-global / install locations when PATH wasn't refreshed —
    # very common on Windows right after `npm install -g`.
    home = Path.home()
    appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
    candidates = [
        Path(appdata) / "npm" / "claude.cmd",
        Path(appdata) / "npm" / "claude.exe",
        Path(appdata) / "npm" / "claude",
        home / "AppData" / "Roaming" / "npm" / "claude.cmd",
        home / ".npm-global" / "bin" / "claude",
        home / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/opt/homebrew/bin/claude"),
    ]
    for c in candidates:
        try:
            if c.is_file():
                _CLAUDE_CLI_PATH = str(c)
                return _CLAUDE_CLI_PATH
        except Exception:
            continue
    _CLAUDE_CLI_PATH = ""
    return _CLAUDE_CLI_PATH


def claude_cli_complete(prompt: str, cfg: "Config", *, timeout: int = 180,
                        on_step=None) -> str | None:
    """Run a single prompt through the local `claude` CLI in headless print
    mode and return the text response. Returns None on ANY failure (CLI not
    installed, timeout, non-zero exit, unparseable output) so callers can
    fall back to Gemini.

    This taps the user's logged-in Claude subscription — no API key, no
    per-call billing. It's slower than a Gemini HTTP call (full agent spin-
    up) and counts against the subscription's usage limits, so it's opt-in
    via cfg.use_claude_cli. Intended for local/personal use; a real product
    backend would use the Anthropic API instead.
    """
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    claude_path = getattr(cfg, "claude_cli_path", "") or "claude"
    resolved = _resolve_claude_cli(claude_path)
    if not resolved:
        log(f"      claude CLI '{claude_path}' nicht auf PATH gefunden — Gemini-Fallback. "
            "(claude installiert? 'claude login' gemacht? ggf. vollen Pfad in "
            "config.json claude_cli_path setzen.)")
        return None

    # Pass the prompt on stdin, not as an argv element: moment-picking
    # prompts embed a full transcript and can easily exceed Windows'
    # ~32KB command-line limit. `claude -p` reads the prompt from stdin
    # when no positional prompt is given. Use the RESOLVED path so a
    # Windows .cmd actually executes.
    cmd = [resolved, "-p", "--output-format", "json"]
    model = (getattr(cfg, "claude_cli_model", "") or "").strip()
    if model:
        cmd += ["--model", model]

    try:
        proc = subprocess.run(
            cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        log(f"      claude CLI timed out after {timeout}s — falling back")
        return None
    except Exception as e:
        log(f"      claude CLI failed to start: {str(e)[:160]} — falling back")
        return None

    if proc.returncode != 0:
        log(f"      claude CLI exited {proc.returncode}: "
            f"{(proc.stderr or '').strip()[:200]} — falling back")
        return None

    out = (proc.stdout or "").strip()
    if not out:
        return None
    # --output-format json wraps the answer in an envelope with a "result"
    # field. Older/other formats may print raw text — tolerate both.
    try:
        env = json.loads(out)
        if isinstance(env, dict):
            text = env.get("result") or env.get("text") or ""
            if isinstance(text, str) and text.strip():
                return text.strip()
            # Some versions nest under content blocks.
            if isinstance(env.get("content"), list):
                joined = "".join(
                    b.get("text", "") for b in env["content"]
                    if isinstance(b, dict)
                ).strip()
                if joined:
                    return joined
    except json.JSONDecodeError:
        # stdout was raw text, not JSON — use it directly.
        return out
    return out or None


def _resolve_grok_cli(grok_path: str = "grok") -> str:
    """Return the absolute path to the `grok` (Grok Build) executable, or ""
    if not found. Cached. Mirrors _resolve_claude_cli — on Windows shutil.which
    resolves to a .cmd/.exe which subprocess needs in full."""
    global _GROK_CLI_PATH
    if _GROK_CLI_PATH is not None:
        return _GROK_CLI_PATH
    import shutil
    if grok_path and Path(grok_path).expanduser().is_file():
        _GROK_CLI_PATH = str(Path(grok_path).expanduser())
        return _GROK_CLI_PATH
    found = shutil.which(grok_path) or shutil.which("grok")
    if found:
        _GROK_CLI_PATH = found
        return _GROK_CLI_PATH
    home = Path.home()
    appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
    candidates = [
        Path(appdata) / "npm" / "grok.cmd",
        Path(appdata) / "npm" / "grok.exe",
        Path(appdata) / "npm" / "grok",
        home / ".grok" / "bin" / "grok.exe",
        home / ".grok" / "bin" / "grok",
        home / ".local" / "bin" / "grok",
        Path("/usr/local/bin/grok"),
        Path("/opt/homebrew/bin/grok"),
    ]
    for c in candidates:
        try:
            if c.is_file():
                _GROK_CLI_PATH = str(c)
                return _GROK_CLI_PATH
        except Exception:
            continue
    _GROK_CLI_PATH = ""
    return _GROK_CLI_PATH


# Image extensions Grok Build writes into its session images/ dir.
_GROK_IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def _grok_image_snapshot() -> dict[str, float]:
    """Map of {image_path: mtime} for every image currently under ~/.grok.
    Used to detect which file a `grok` run just produced — Grok Build saves
    generated images into its own session dir (…/.grok/sessions/<cwd>/<uuid>/
    images/N.jpg) and only announces the path in free-text, so we diff the
    tree instead of parsing its (localized) prose."""
    base = Path.home() / ".grok"
    out: dict[str, float] = {}
    if not base.is_dir():
        return out
    try:
        for p in base.rglob("*"):
            if p.suffix.lower() in _GROK_IMG_EXTS and p.is_file():
                try:
                    out[str(p)] = p.stat().st_mtime
                except OSError:
                    continue
    except OSError:
        pass
    return out


def fetch_image_from_grok_cli(prompt: str, out_path: Path, cfg: "Config", *,
                              aspect: str = "1:1", timeout: int = 240,
                              on_step=None) -> Path:
    """Generate one image via the local Grok Build CLI (`grok -p`), tapping the
    user's SuperGrok subscription — no API key, no per-image billing. Writes the
    result to `out_path` and returns it. `aspect` ("1:1"/"9:16"/"16:9") is asked
    for in the prompt and enforced by cropping the bytes to that ratio (Grok may
    ignore the request, so we never trust it blindly). Raises on ANY failure so
    the caller falls back to Cloudflare / Pollinations.

    Grok Build saves generated images into its own session dir and names the
    path only in prose, so we snapshot ~/.grok before/after and pick up the new
    file rather than dictating a path. Slower than an API call (full agent
    spin-up, ~15s observed) and counts against the subscription's limits, so
    it's opt-in via cfg.use_grok_cli. Local/personal use only — a product
    backend would use the xAI image API instead."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass

    resolved = _resolve_grok_cli(getattr(cfg, "grok_cli_path", "") or "grok")
    if not resolved:
        raise RuntimeError(
            "grok CLI not found on PATH (Grok Build installed? `grok login` "
            "done? set grok_cli_path in config.json)")

    before = _grok_image_snapshot()
    # One image in the requested aspect. The explicit instructions keep the
    # agent from asking a follow-up question or generating several variations.
    # Single line — it's passed as an argv value, and image prompts are short
    # (no Windows command-length concern).
    _aspect_word = {"1:1": "1:1 square", "9:16": "9:16 vertical portrait",
                    "16:9": "16:9 widescreen"}.get(aspect, "1:1 square")
    ask = (
        "imagine " + " ".join(prompt.split())
        + f" — generate exactly ONE image in {_aspect_word} format, produce it "
        "directly, do not ask questions, do not generate variations."
    )
    # Grok Build's `-p` (alias --single) takes the prompt as its VALUE, not on
    # stdin (unlike `claude -p`). Any extra flags go before it so the prompt
    # stays adjacent to -p.
    extra = (getattr(cfg, "grok_cli_extra_args", "") or "").strip()
    extra_args = []
    if extra:
        import shlex
        extra_args = shlex.split(extra)
    cmd = [resolved] + extra_args + ["-p", ask]

    try:
        proc = subprocess.run(
            cmd, input="", capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"grok CLI timed out after {timeout}s") from e
    except Exception as e:
        raise RuntimeError(f"grok CLI failed to start: {str(e)[:160]}") from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"grok CLI exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}")

    after = _grok_image_snapshot()
    # New files, or ones whose mtime advanced since the snapshot.
    fresh = [Path(p) for p, m in after.items()
             if p not in before or m > before.get(p, 0.0)]
    if not fresh:
        raise RuntimeError("grok CLI produced no new image under ~/.grok")
    newest = max(fresh, key=lambda p: p.stat().st_mtime)
    log(f"      grok image → {newest.name}")

    # Normalize to the requested aspect at out_path. Reuses the shared
    # center-crop helpers, which also validate the bytes are a real image — a
    # half-written file raises and we fall back.
    try:
        data = newest.read_bytes()
    except OSError as e:
        raise RuntimeError(f"grok image unreadable: {str(e)[:120]}") from e
    _ar = {"1:1": 1.0, "9:16": 9 / 16, "16:9": 16 / 9}.get(aspect, 1.0)
    if aspect == "1:1":
        if not _save_square_image(data, out_path):
            raise RuntimeError("grok image could not be decoded")
    else:
        if not _save_aspect_image(data, out_path, ar=_ar):
            raise RuntimeError("grok image could not be decoded")
    return out_path


def _complete_text(prompt: str, cfg: "Config", *, prefer_claude: bool,
                   gemini_body: dict, gemini_model: str | None = None,
                   on_step=None) -> str:
    """Unified text completion: try the local Claude CLI first when
    prefer_claude (and cfg.use_claude_cli) is set, otherwise POST to Gemini.
    Always returns text or raises — callers parse the text themselves.

    gemini_body is the full Gemini request body (with the prompt already
    embedded) used for the fallback path; gemini_model overrides the model
    in the URL when given."""
    def _log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)
    if prefer_claude and getattr(cfg, "use_claude_cli", False):
        text = claude_cli_complete(prompt, cfg, on_step=on_step)
        if text:
            mdl = (getattr(cfg, "claude_cli_model", "") or "default").strip() or "default"
            _log(f"      ✓ via Claude CLI ({mdl})")
            return text
        # fall through to Gemini on any CLI failure (reason already logged)
    if not cfg.gemini_api_key:
        raise RuntimeError("no text backend available (claude CLI failed and no gemini_api_key)")
    model = gemini_model or cfg.gemini_model
    _log(f"      ✓ via Gemini ({model})")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = _gemini_post(url, {"key": cfg.gemini_api_key}, gemini_body)
    try:
        candidate = data["candidates"][0]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini returned no candidates: {data}") from e
    parts = candidate.get("content", {}).get("parts", []) or []
    return "\n".join(p.get("text", "") for p in parts if not p.get("thought")).strip()


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


_HOOK_PROMPT_DE = """Schreibe {n} VERSCHIEDENE kurze YouTube-Short Hooks (Aufmacher-Text fuer die ersten 2-3 Sekunden) zum Thema "{topic}".

Jeder Hook MUSS:
- Maximal 8 Woerter / 50 Zeichen sein
- Sofort Neugier oder Schock ausloesen
- KEIN Punkt am Ende, optional ! oder ?
- Komplett anderer Stil zueinander (POV, Frage, Behauptung, Warnung, "99%"-Stat)

Antworte NUR mit einem JSON-Array von {n} Strings, sonst nichts. Beispiel: ["Hook 1","Hook 2","Hook 3"]"""

_HOOK_PROMPT_EN = """Write {n} DIFFERENT short YouTube-Short hooks (the big text for the first 2-3 seconds) about "{topic}".

Each hook MUST:
- Be max 8 words / 50 characters
- Trigger instant curiosity or shock
- NO trailing period, optional ! or ?
- Completely different style from each other (POV, question, claim, warning, "99%"-stat)

Reply with ONLY a JSON array of {n} strings, nothing else. Example: ["Hook 1","Hook 2","Hook 3"]"""


def generate_hook_variants(topic: str, cfg: "Config", n: int = 4,
                           language: str = "de", on_step=None) -> list[str]:
    """Ask the LLM for n short hook variants — the user picks the best one in
    the GUI. Returns a list of strings (may be shorter than n if the LLM
    delivers fewer). Routes through _complete_text so the Claude-CLI toggle
    is honored. On any failure returns a few hand-rolled fallbacks so the
    GUI button never silently does nothing."""
    n = max(1, min(int(n), 8))
    topic = (topic or "").strip() or "ein krasser Roblox Moment"
    template = _HOOK_PROMPT_EN if (language or "de").lower() == "en" else _HOOK_PROMPT_DE
    prompt = template.format(n=n, topic=topic)
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.95, "maxOutputTokens": 512,
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    try:
        text = _complete_text(prompt, cfg, prefer_claude=True, gemini_body=body, on_step=on_step)
    except Exception:
        text = ""
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    s, e = raw.find("["), raw.rfind("]")
    if s != -1 and e != -1:
        raw = raw[s:e + 1]
    hooks: list[str] = []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            for h in parsed:
                h = str(h).strip().rstrip(".").strip('"').strip("'")
                if 2 <= len(h) <= 80:
                    hooks.append(h)
    except Exception:
        pass
    if not hooks:
        # safe last-resort fallbacks so the button never dies on the user
        is_en = (language or "de").lower() == "en"
        fallbacks_de = [f"99% schaffen das nicht", f"POV: {topic}", f"Achtung! Das ist Wahnsinn",
                       f"Du wirst es nicht glauben"]
        fallbacks_en = [f"99% can't do this", f"POV: {topic}", f"Wait... watch this",
                       f"You won't believe it"]
        hooks = (fallbacks_en if is_en else fallbacks_de)[:n]
    return hooks[:n]


def fallback_template_script(topic: str) -> str:
    return random.choice(_SCRIPT_TEMPLATES).format(topic=topic.strip() or "ein krasser Roblox Moment")


def generate_script(topic: str, cfg: "Config", target_seconds: float = 30.0,
                    on_step=None, language: str = "de") -> str:
    """Top-level script generator. Gemini-driven, with an auto top-up
    loop for long-form: if Gemini's first draft is more than 15% short
    of the requested duration, we ask it to keep writing (up to 3 extra
    calls) until the script is long enough. Without this, asking for
    500s typically yields ~380s and the user thinks the pipeline ignored
    them — actually Gemini just stopped early."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)
    if not cfg.gemini_api_key and not getattr(cfg, "use_claude_cli", False):
        raise RuntimeError("no script backend configured (gemini_api_key missing)")
    if getattr(cfg, "use_claude_cli", False):
        mdl = (getattr(cfg, "claude_cli_model", "") or "default").strip() or "default"
        log(f"      script: Claude CLI ({mdl}) bevorzugt, Gemini als Fallback (lang={language})")
    else:
        log(f"      script via Gemini ({cfg.gemini_model}, lang={language})")
    script = generate_script_via_gemini(topic, cfg, target_seconds, language=language, on_step=on_step)

    # Short jobs don't need top-up — Gemini reliably nails ≤60s targets.
    if target_seconds < 90:
        return script

    # Long-form: the first draft almost always comes back short (the model
    # stops after a few hundred words no matter the requested length), so loop
    # bounded continuations until we're within ~8% of the target.
    return _extend_script_to_target(script, cfg, target_seconds, language, on_step=on_step)


def generate_script_via_gemini(topic: str, cfg: Config, target_seconds: float = 30.0,
                               language: str = "de", on_step=None) -> str:
    # Name kept for back-compat; actually dispatches Claude-CLI-or-Gemini.
    if not cfg.gemini_api_key and not getattr(cfg, "use_claude_cli", False):
        raise RuntimeError("topic given but gemini_api_key missing in config (and GEMINI_API_KEY env not set)")
    target_low = max(10, int(target_seconds - 3))
    target_high = int(target_seconds + 3)
    # Word ranges aligned with actual TTS speech rate (DE ~2.4 wps,
    # EN ~2.5 wps). The old 2.0-2.6 hardcode let Gemini hit the low
    # bound (e.g. 1000 words for 500s) and stop, producing only 400s
    # of speech. Bias the low bound to 95% of expected and the high
    # bound to 115% so even Gemini's lazy "low-bound" output lands
    # close to target.
    wps = _WPS_EN if (language or "de").lower() == "en" else _WPS_DE
    words_low = int(target_seconds * wps * 0.95)
    words_high = int(target_seconds * wps * 1.15)
    # Pick template along two axes: language (de/en) and length (short
    # vs long-form). Long-form switches because "YouTube Short" in the
    # prompt makes Gemini silently cap output at ~60s. Language switches
    # to honor the user's TTS-Sprache choice — the previous hardcoded
    # German prompt meant English TTS jobs got German scripts that
    # Chatterbox then tried to speak in an American accent.
    is_long_form = target_seconds >= 90
    lang = (language or "de").lower()
    if lang == "en":
        prompt_template = SCRIPT_PROMPT_LONG_EN if is_long_form else SCRIPT_PROMPT_SHORT_EN
    else:
        prompt_template = SCRIPT_PROMPT_LONG if is_long_form else SCRIPT_PROMPT_SHORT
    prompt_text = prompt_template.format(
        topic=topic, target_low=target_low, target_high=target_high,
        words_low=words_low, words_high=words_high,
    )
    # Long scripts blow past the default 2048 token budget — at ~2.5 tokens
    # per German word we need ~3.5k tokens for 1300 words. Give it 8192 so
    # there's actual headroom for 15-minute videos.
    max_tokens = 8192 if is_long_form else 2048
    body = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.9,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    text = _complete_text(prompt_text, cfg, prefer_claude=True, gemini_body=body, on_step=on_step)
    if not text:
        raise RuntimeError("script generation returned no text")
    if len(text) < 120:
        print(f"      WARN: script output looks short ({len(text)} chars)")
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


def make_color_background(duration: float, out_path: Path,
                          width: int, height: int,
                          color: str = "white") -> Path:
    """Generate a solid-color silent mp4 of `duration` at width×height. Used as
    the base track for faceless/explainer videos where there's no gameplay —
    the generated images (stickman/doodle) sit on this plain background, like
    the Danny-Why style. `color` is any ffmpeg color (e.g. 'white', '#0d0d0d')."""
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"color=c={color}:s={width}x{height}:r=30:d={max(0.5, duration):.2f}",
        *_vcodec("fast"),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ])
    if not out_path.is_file() or out_path.stat().st_size < 1024:
        raise RuntimeError("color background generation produced empty mp4")
    return out_path


# Chatterbox tokenizer has an undocumented context limit. Empirically ~300
# characters works reliably; longer scripts hit a CUDA embedding-lookup
# OOB ("srcIndex < srcSelectDimSize") that corrupts the CUDA context for
# the rest of the process. So we always chunk Chatterbox input.
_CHATTERBOX_MAX_CHARS = 280


def _split_sentences_for_tts(text: str, max_chars: int = _CHATTERBOX_MAX_CHARS) -> list[str]:
    """Greedy-pack sentences into chunks <= `max_chars`. Splits primarily on
    sentence boundaries (.!?); a sentence longer than max_chars itself is
    sub-split on commas, and as a last resort on whitespace."""
    text = (text or "").strip()
    if not text:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    cur = ""
    def _flush():
        nonlocal cur
        if cur.strip():
            chunks.append(cur.strip())
        cur = ""
    for sent in sentences:
        if len(sent) <= max_chars:
            if len(cur) + 1 + len(sent) <= max_chars:
                cur = f"{cur} {sent}".strip() if cur else sent
            else:
                _flush()
                cur = sent
            continue
        # Sentence alone exceeds budget: fall back to comma split, then to
        # word-by-word packing. This loses some prosody but never overflows.
        _flush()
        sub_parts = re.split(r"(?<=,)\s+", sent)
        tmp = ""
        for part in sub_parts:
            if len(part) > max_chars:
                words = part.split()
                for w in words:
                    if len(tmp) + 1 + len(w) <= max_chars:
                        tmp = f"{tmp} {w}".strip() if tmp else w
                    else:
                        if tmp:
                            chunks.append(tmp)
                        tmp = w
            else:
                if len(tmp) + 1 + len(part) <= max_chars:
                    tmp = f"{tmp} {part}".strip() if tmp else part
                else:
                    if tmp:
                        chunks.append(tmp)
                    tmp = part
        if tmp:
            chunks.append(tmp)
    _flush()
    return chunks


def _detect_language(text: str) -> str:
    """Quick heuristic: 'de' or 'en' for a voiceover script. Two signals:
    German-only chars (äöüß) → definitive German. Otherwise count common
    German stopwords against total wordcount. >10% hit rate → German."""
    t = (text or "").lower()
    if any(c in t for c in "äöüß"):
        return "de"
    words = re.findall(r"\b\w+\b", t)
    if not words:
        return "en"
    hits = sum(1 for w in words if w in _GERMAN_STOPWORDS)
    return "de" if (hits / len(words)) > 0.10 else "en"


def _download_piper_voice(model_name: str) -> Path:
    """Ensure {model_name}.onnx and {model_name}.onnx.json are cached on disk,
    download them if not. Returns the absolute path to the .onnx file."""
    base_url = _PIPER_MODEL_URLS.get(model_name)
    if not base_url:
        raise RuntimeError(
            f"Unknown Piper model {model_name!r}. Known: {sorted(_PIPER_MODEL_URLS)}"
        )
    model_dir = _PIPER_CACHE_DIR / model_name
    model_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = model_dir / f"{model_name}.onnx"
    json_path = model_dir / f"{model_name}.onnx.json"

    for url, dest in [(base_url, onnx_path), (base_url + ".json", json_path)]:
        if dest.is_file() and dest.stat().st_size > 1024:
            continue
        print(f"      downloading Piper voice file: {dest.name}")
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            tmp = dest.with_suffix(dest.suffix + ".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
            tmp.replace(dest)
    return onnx_path


def _piper_synthesize_to_wav(voice, text: str, wav_path: Path) -> None:
    """Write Piper synthesis of `text` to `wav_path`. Survives three known
    piper-tts API shapes so we don't have to pin a specific version:

      (A) piper-tts ≥1.3: `voice.synthesize_wav(text, wav_file)` — current.
      (B) piper-tts ≤1.2: `voice.synthesize(text, wav_file)` — old.
      (C) piper-tts ≥1.3 alt: `voice.synthesize(text)` returns an iterator
          of AudioChunk objects we have to drain ourselves into the wav.

    Without this dispatch, on a (A)-era install the old (B) call silently
    produced a generator that nothing consumed → empty wav file, pipeline
    hangs or fails downstream.
    """
    import wave

    # Path (A): synthesize_wav writes a fully-formed WAV into the open
    # wave.Wave_write handle. This is the canonical 1.3+ API.
    syn_wav = getattr(voice, "synthesize_wav", None)
    if callable(syn_wav):
        with wave.open(str(wav_path), "wb") as wav_file:
            syn_wav(text, wav_file)
        return

    # Path (B): old API took the wave handle as a second positional arg.
    # Probe the signature first so we don't half-open a wave file that
    # then can't be closed cleanly (wave.close() requires a header).
    import inspect
    try:
        sig = inspect.signature(voice.synthesize)
        accepts_two = len([p for p in sig.parameters.values()
                           if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                                         inspect.Parameter.POSITIONAL_OR_KEYWORD)]) >= 2
    except (TypeError, ValueError):
        accepts_two = False
    if accepts_two:
        wav_file = wave.open(str(wav_path), "wb")
        try:
            voice.synthesize(text, wav_file)
        finally:
            try:
                wav_file.close()
            except Exception:
                pass
        if wav_path.is_file() and wav_path.stat().st_size > 1024:
            return
        # File is empty/truncated → discard and try (C).
        try: wav_path.unlink()
        except Exception: pass

    # Path (C): synthesize(text) returns an iterator of AudioChunk objects.
    # Each chunk exposes audio_int16_bytes (raw PCM s16le), plus sample_rate
    # / sample_width / sample_channels metadata. Drain into a fresh WAV.
    audio_iter = voice.synthesize(text)
    sample_rate = None
    sample_width = 2
    channels = 1
    pcm_chunks: list[bytes] = []
    for chunk in audio_iter:
        if sample_rate is None:
            sample_rate = int(getattr(chunk, "sample_rate", 22050))
            sample_width = int(getattr(chunk, "sample_width", 2))
            channels = int(getattr(chunk, "sample_channels", 1))
        data = getattr(chunk, "audio_int16_bytes", None)
        if data is None:
            arr = getattr(chunk, "audio_int16_array", None)
            if arr is not None:
                data = arr.tobytes()
        if data:
            pcm_chunks.append(data)
    if not pcm_chunks or sample_rate is None:
        raise RuntimeError("Piper synthesize() returned no audio chunks")
    with wave.open(str(wav_path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"".join(pcm_chunks))


def _get_piper_voice(model_name: str):
    """Lazy-init the Piper voice. Returns None if piper-tts isn't installed
    or the download fails. Cached per model_name."""
    global _PIPER_VOICE, _PIPER_VOICE_NAME
    if _PIPER_VOICE is False:
        return None
    if _PIPER_VOICE is not None and _PIPER_VOICE_NAME == model_name:
        return _PIPER_VOICE
    try:
        from piper import PiperVoice  # type: ignore
    except Exception as e:
        print(f"      Piper TTS not installed: {e}")
        _PIPER_VOICE = False
        return None
    try:
        onnx_path = _download_piper_voice(model_name)
        print(f"      loading Piper voice {model_name} (CPU)")
        # Different piper-tts versions take different kwargs. Try the rich
        # form first, fall back to the minimal one if older.
        try:
            voice = PiperVoice.load(str(onnx_path), config_path=str(onnx_path) + ".json")
        except TypeError:
            voice = PiperVoice.load(str(onnx_path))
        _PIPER_VOICE = voice
        _PIPER_VOICE_NAME = model_name
        print("      Piper TTS ready")
    except Exception as e:
        print(f"      Piper TTS load failed: {e}")
        _PIPER_VOICE = False
        return None
    return _PIPER_VOICE


def _get_chatterbox_model():
    """Lazy-init Chatterbox TTS. ~3GB model download on first call, ~3-4GB
    VRAM resident. Returns None if chatterbox-tts isn't installed, the
    model download fails, or there's not enough VRAM. Cached at module
    scope so subsequent voiceovers don't re-load."""
    global _CHATTERBOX_MODEL
    if _CHATTERBOX_MODEL is False:
        return None
    if _CHATTERBOX_MODEL is not None:
        return _CHATTERBOX_MODEL
    try:
        import torch  # type: ignore
        from chatterbox.tts import ChatterboxTTS  # type: ignore
    except Exception as e:
        print(f"      Chatterbox TTS not installed: {e}")
        _CHATTERBOX_MODEL = False
        return None
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"      loading Chatterbox TTS into {device.upper()} VRAM "
              "(one-time ~3GB model download on the very first run only)")
        _CHATTERBOX_MODEL = ChatterboxTTS.from_pretrained(device=device)
        print(f"      Chatterbox TTS ready (sr={_CHATTERBOX_MODEL.sr})")
    except Exception as e:
        print(f"      Chatterbox TTS load failed: {e}")
        _CHATTERBOX_MODEL = False
        return None
    return _CHATTERBOX_MODEL


def _get_chatterbox_multilingual_model():
    """Lazy-init Chatterbox MULTILINGUAL TTS (German + 22 other langs, with
    zero-shot voice cloning). ~3GB extra download on first call, ~3-4GB VRAM.
    Returns None if unavailable. Cached at module scope. Tries the documented
    import paths across chatterbox-tts versions."""
    global _CHATTERBOX_ML_MODEL
    if _CHATTERBOX_ML_MODEL is False:
        return None
    if _CHATTERBOX_ML_MODEL is not None:
        return _CHATTERBOX_ML_MODEL
    try:
        import torch  # type: ignore
        try:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS  # type: ignore
        except Exception:
            # Older/newer packaging may expose it from the top-level module.
            from chatterbox import ChatterboxMultilingualTTS  # type: ignore
    except Exception as e:
        print(f"      Chatterbox Multilingual not installed: {e}")
        _CHATTERBOX_ML_MODEL = False
        return None
    try:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"      loading Chatterbox Multilingual into {device.upper()} VRAM "
              "(one-time ~3GB model download on the very first run only)")
        _CHATTERBOX_ML_MODEL = ChatterboxMultilingualTTS.from_pretrained(device=device)
        print(f"      Chatterbox Multilingual ready (sr={_CHATTERBOX_ML_MODEL.sr})")
    except Exception as e:
        print(f"      Chatterbox Multilingual load failed: {e}")
        _CHATTERBOX_ML_MODEL = False
        return None
    return _CHATTERBOX_ML_MODEL


def _resolve_clone_reference(ref: str) -> str:
    """Return a usable existing voice-reference path, or "" if none found.
    Tolerant: if the given path doesn't exist but it's a '.clone.wav', try the
    raw source beside it (any common audio ext); if it IS a raw file, also try
    an existing '.clone.wav' sibling. Lets the voice picker keep working even
    when only one of the two files exists on disk."""
    ref = (ref or "").strip()
    if not ref:
        return ""
    p = Path(ref).expanduser()
    if p.is_file():
        return str(p)
    name = p.name.lower()
    if name.endswith(".clone.wav"):
        stem = p.name[:-len(".clone.wav")]
        for ext in (".wav", ".mp3", ".m4a", ".mp4", ".ogg", ".flac"):
            cand = p.with_name(stem + ext)
            if cand.is_file():
                return str(cand)
    else:
        cand = p.with_suffix(".clone.wav")
        if cand.is_file():
            return str(cand)
    return ""


_DE_ONES = ["null", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben",
            "acht", "neun", "zehn", "elf", "zwölf", "dreizehn", "vierzehn",
            "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn"]
_DE_TENS = {20: "zwanzig", 30: "dreißig", 40: "vierzig", 50: "fünfzig",
            60: "sechzig", 70: "siebzig", 80: "achtzig", 90: "neunzig"}


def _de_below_1000(n: int) -> str:
    if n < 20:
        return _DE_ONES[n]
    if n < 100:
        t, o = (n // 10) * 10, n % 10
        if o == 0:
            return _DE_TENS[t]
        one = "ein" if o == 1 else _DE_ONES[o]
        return f"{one}und{_DE_TENS[t]}"
    h, rest = n // 100, n % 100
    hw = ("einhundert" if h == 1 else _DE_ONES[h] + "hundert")
    return hw if rest == 0 else hw + _de_below_1000(rest)


def _de_number(n: int) -> str:
    if n == 0:
        return "null"
    if n < 1000:
        return _de_below_1000(n)
    if n < 1_000_000:
        th, rest = n // 1000, n % 1000
        thw = ("eintausend" if th == 1 else _de_below_1000(th) + "tausend")
        return thw if rest == 0 else thw + _de_below_1000(rest)
    return str(n)  # >= 1M: leave as digits (rare in these scripts)


def _de_year(n: int) -> str:
    """German year reading: 1979 → 'neunzehnhundertneunundsiebzig',
    2010 → 'zweitausendzehn'."""
    if 1100 <= n < 2000:
        hi, lo = n // 100, n % 100
        base = _de_below_1000(hi) + "hundert"
        return base if lo == 0 else base + _de_below_1000(lo)
    return _de_number(n)  # 2000+ reads as cardinal ("zweitausend...")


_EN_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
            "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_EN_TENS = {20: "twenty", 30: "thirty", 40: "forty", 50: "fifty",
            60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety"}


def _en_below_1000(n: int) -> str:
    if n < 20:
        return _EN_ONES[n]
    if n < 100:
        t, o = (n // 10) * 10, n % 10
        return _EN_TENS[t] if o == 0 else f"{_EN_TENS[t]}-{_EN_ONES[o]}"
    h, rest = n // 100, n % 100
    hw = f"{_EN_ONES[h]} hundred"
    return hw if rest == 0 else f"{hw} {_en_below_1000(rest)}"


def _en_number(n: int) -> str:
    if n == 0:
        return "zero"
    if n < 1000:
        return _en_below_1000(n)
    if n < 1_000_000:
        th, rest = n // 1000, n % 1000
        thw = f"{_en_below_1000(th)} thousand"
        return thw if rest == 0 else f"{thw} {_en_below_1000(rest)}"
    return str(n)


def _en_year(n: int) -> str:
    if 1100 <= n < 2000 and n % 100 != 0:
        return f"{_en_below_1000(n // 100)} {_en_below_1000(n % 100)}"
    return _en_number(n)


def _spell_numbers_for_tts(text: str, lang: str) -> str:
    """Replace bare integers with spoken words so the TTS doesn't mangle them
    (e.g. German Chatterbox read '1979' as 'neunzehnhundert neunzehn
    siebenundneunzig'). 4-digit values that look like years use year reading.
    Decimals are read out properly ('3,5' → 'drei Komma fünf', '3.5' →
    'three point five') instead of collapsing to a wrong integer.
    Leaves numbers with adjacent letters/units untouched only loosely — runs
    of pure digits (optionally with a thousands dot) are converted."""
    de = (lang or "de").lower().startswith("de")
    num = _de_number if de else _en_number
    year = _de_year if de else _en_year
    # Decimal/thousands separators are swapped between the two languages.
    dec_sep = "," if de else "."
    thou_sep = "." if de else ","
    dec_word = " Komma " if de else " point "
    digit_words = _DE_ONES[:10] if de else _EN_ONES[:10]

    def repl(m: "re.Match") -> str:
        raw = m.group(0)
        # Decimal number ("3,5" de / "3.5" en): integer part + separator word
        # + fraction digits read one by one. Only for 1-3 fraction digits —
        # longer runs after the separator are usually thousands groups.
        if dec_sep in raw:
            int_part, _, frac_part = raw.partition(dec_sep)
            int_digits = int_part.replace(thou_sep, "")
            if (int_digits.isdigit() and frac_part.isdigit()
                    and 1 <= len(frac_part) <= 3
                    and not (de is False and len(frac_part) == 3)):
                try:
                    frac_words = " ".join(digit_words[int(d)] for d in frac_part)
                    return num(int(int_digits)) + dec_word + frac_words
                except Exception:
                    return raw
        digits = raw.replace(".", "").replace(",", "")
        if not digits.isdigit():
            return raw
        n = int(digits)
        try:
            if len(digits) == 4 and 1100 <= n <= 2099:
                return year(n)
            return num(n)
        except Exception:
            return raw

    # Pure-digit runs (allow German thousands dots / English commas inside).
    return re.sub(r"\d[\d.,]*\d|\d", repl, text)


# Abbreviations & symbols the TTS models reliably mumble. Spelled out before
# synthesis. German list is the important one (Chatterbox Multilingual garbles
# these the most); English gets a minimal set since that model is near-perfect.
_DE_TTS_ABBREV = [
    (re.compile(r"\bz\.\s?B\."), "zum Beispiel"),
    (re.compile(r"\bd\.\s?h\."), "das heißt"),
    (re.compile(r"\bu\.\s?a\."), "unter anderem"),
    (re.compile(r"\busw\."), "und so weiter"),
    (re.compile(r"\bbzw\."), "beziehungsweise"),
    (re.compile(r"\bca\."), "circa"),
    (re.compile(r"\bevtl\."), "eventuell"),
    (re.compile(r"\bggf\."), "gegebenenfalls"),
    (re.compile(r"\binkl\."), "inklusive"),
    (re.compile(r"\bMio\."), "Millionen"),
    (re.compile(r"\bMrd\."), "Milliarden"),
    (re.compile(r"\bNr\."), "Nummer"),
    (re.compile(r"\bkm/h\b"), "Kilometer pro Stunde"),
    (re.compile(r"°\s?C\b"), " Grad Celsius"),
    (re.compile(r"%"), " Prozent"),
    (re.compile(r"€"), " Euro"),
    (re.compile(r"\$"), " Dollar"),
    (re.compile(r"\s&\s"), " und "),
]

_EN_TTS_ABBREV = [
    (re.compile(r"\betc\."), "et cetera"),
    (re.compile(r"\be\.g\."), "for example"),
    (re.compile(r"\bi\.e\."), "that is"),
    (re.compile(r"%"), " percent"),
    (re.compile(r"€"), " euros"),
    (re.compile(r"\$"), " dollars"),
    (re.compile(r"\s&\s"), " and "),
]


def _spell_abbreviations_for_tts(text: str, lang: str) -> str:
    """Expand abbreviations and currency/unit symbols into spoken words.
    Must run BEFORE _spell_numbers_for_tts: currency symbols that PRECEDE a
    number ('$50', '€ 100') are first moved behind it so the spoken order is
    natural ('50 Dollar' instead of 'Dollar fünfzig')."""
    if not text:
        return text
    text = re.sub(r"([€$])\s*(\d[\d.,]*\d|\d)", r"\2 \1", text)
    rules = _DE_TTS_ABBREV if (lang or "de").lower().startswith("de") else _EN_TTS_ABBREV
    for pat, repl in rules:
        text = pat.sub(repl, text)
    # Tidy doubled spaces left behind by symbol replacements.
    return re.sub(r"[ \t]{2,}", " ", text)


def synthesize_voiceover(text: str, cfg: Config, out_path: Path) -> Path:
    """Dispatch to the right TTS engine based on `cfg.tts_language`:

      - "de"   → Piper TTS (offline, native German voice, fast on CPU,
                  no voice cloning, no length limit)
      - "en"   → Chatterbox TTS (offline GPU, zero-shot voice cloning,
                  English-primary, chunked to dodge its ~300-char limit)
      - "auto" → quick heuristic on `text` (German-only chars + stopword
                  ratio); falls back to English when ambiguous.

    Safety net: if the user explicitly chose EN but the text scans as
    German, we override to Piper. Otherwise the German text would crash
    Chatterbox's English-only tokenizer with a CUDA assertion that
    poisons the whole process — and the user would have to restart the
    GUI to recover.
    """
    # Universal guard: strip timestamps / markdown / stage directions so the
    # voice never reads "00_07" as "double-oh oh-seven". Covers every caller
    # (main script, long-form extension chunks, future ones).
    text = _sanitize_script_for_tts(text)
    lang = (getattr(cfg, "tts_language", "auto") or "auto").lower()
    detected = _detect_language(text)
    if lang == "auto":
        lang = detected
        print(f"      tts language auto-detected: {lang}")
    elif lang == "en" and detected == "de":
        print("      WARN: TTS set to English but text scans as German — "
              "overriding to Piper to avoid Chatterbox tokenizer crash.")
        lang = "de"
    elif lang == "de" and detected == "en":
        # Piper would speak the English text with German pronunciation
        # rules (e.g. "the" → "te"), which sounds broken. Switch to
        # Chatterbox so the English text is spoken correctly.
        print("      WARN: TTS set to German but text scans as English — "
              "overriding to Chatterbox so the pronunciation matches.")
        lang = "en"
    # Spell out abbreviations/symbols first (moves '€50' → '50 €' before the
    # digits get worded), then digits in the resolved language, so the TTS
    # doesn't garble either ("1979" → "neunzehnhundertneunundsiebzig",
    # "z.B. 3,5%" → "zum Beispiel drei Komma fünf Prozent").
    text = _spell_abbreviations_for_tts(text, lang)
    text = _spell_numbers_for_tts(text, lang)
    if lang == "de":
        # German voice cloning (opt-in) → Chatterbox Multilingual. Uses a
        # German-specific reference if set, else the general one. Falls back to
        # Piper if the multilingual model isn't available or errors.
        if bool(getattr(cfg, "tts_de_clone", False)):
            de_ref = _resolve_clone_reference(
                (getattr(cfg, "tts_reference_audio_de", "") or "").strip()
                or (getattr(cfg, "tts_reference_audio", "") or "").strip())
            if de_ref:
                print(f"      German voice cloning via Chatterbox Multilingual "
                      f"(ref: {Path(de_ref).name})")
                try:
                    return _synthesize_voiceover_chatterbox(
                        text, cfg, out_path, multilingual=True,
                        language_id="de", ref_override=de_ref)
                except Exception as e:
                    print(f"      WARN: German Chatterbox-clone failed ({str(e)[:160]}) "
                          "— falling back to Piper")
            else:
                raw = ((getattr(cfg, "tts_reference_audio_de", "") or "").strip()
                       or (getattr(cfg, "tts_reference_audio", "") or "").strip())
                print(f"      WARN: 'Deutsche Stimme klonen' ist an, aber die Referenz-Datei "
                      f"wurde nicht gefunden: {raw or '(leer)'} — nutze Piper. "
                      "Pruefe den Pfad im Stimm-Feld (existiert die .wav wirklich?).")
        return _synthesize_voiceover_piper(text, cfg, out_path)
    return _synthesize_voiceover_chatterbox(text, cfg, out_path)


def _synthesize_voiceover_piper(text: str, cfg: Config, out_path: Path) -> Path:
    """German TTS via Piper. Default voice is `de_DE-thorsten-medium` —
    the Thorsten Voice project, a native German linguist's open dataset.
    Override with cfg.tts_piper_model to pick a different one (see
    _PIPER_MODEL_URLS for the curated set)."""
    model_name = (getattr(cfg, "tts_piper_model", "") or "de_DE-thorsten-medium").strip()
    voice = _get_piper_voice(model_name)
    if voice is None:
        raise RuntimeError(
            "Piper TTS not available. Install with:\n"
            "  .venv\\Scripts\\python.exe -m pip install piper-tts"
        )
    import wave
    wav_path = out_path.with_suffix(".wav")
    try:
        _piper_synthesize_to_wav(voice, text, wav_path)
    except Exception as e:
        raise RuntimeError(f"Piper generation failed: {e}") from e
    run([
        "ffmpeg", "-y", "-i", str(wav_path),
        "-c:a", "libmp3lame", "-q:a", "2",
        str(out_path),
    ])
    try:
        wav_path.unlink()
    except Exception:
        pass
    if not out_path.is_file() or out_path.stat().st_size < 200:
        raise RuntimeError(f"Piper produced empty/missing output: {out_path}")
    return out_path


def _synthesize_voiceover_chatterbox(text: str, cfg: Config, out_path: Path, *,
                                     multilingual: bool = False,
                                     language_id: str | None = None,
                                     ref_override: str | None = None) -> Path:
    """Chatterbox TTS (Resemble AI, local on GPU). English by default; set
    multilingual=True + language_id (e.g. "de") for the multilingual model
    that clones a voice into another language.

    If a reference audio is given (ref_override, else cfg.tts_reference_audio)
    the output mimics that speaker (zero-shot voice cloning). Otherwise the
    built-in default voice is used.

    `cfg.tts_exaggeration` controls emotion (0=flat, 1=dramatic).
    `cfg.tts_cfg_weight` controls naturalness vs. text adherence.
    """
    if multilingual:
        model = _get_chatterbox_multilingual_model()
        if model is None:
            raise RuntimeError(
                "Chatterbox Multilingual not available. Install/upgrade with:\n"
                "  .venv\\Scripts\\python.exe -m pip install -U chatterbox-tts torchaudio"
            )
    else:
        model = _get_chatterbox_model()
    if model is None:
        raise RuntimeError(
            "Chatterbox TTS not available. Install with:\n"
            "  .venv\\Scripts\\python.exe -m pip install chatterbox-tts torchaudio"
        )
    try:
        import torchaudio as ta  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "torchaudio missing. Install with:\n"
            "  .venv\\Scripts\\python.exe -m pip install torchaudio"
        ) from e

    kwargs: dict = {
        "exaggeration": float(getattr(cfg, "tts_exaggeration", 0.5)),
        "cfg_weight": float(getattr(cfg, "tts_cfg_weight", 0.5)),
    }
    ref_path_str = (ref_override if ref_override is not None
                    else getattr(cfg, "tts_reference_audio", "") or "").strip()
    if ref_path_str:
        ref_path = Path(ref_path_str).expanduser()
        if ref_path.is_file():
            # Auto-clean the recording into a Chatterbox-friendly clone
            # reference (mono 24k, silence-trimmed, ~12s, normalized). Cached
            # next to the source; re-prepped only when the source changes.
            # autoprep can be disabled (cfg.tts_clone_autoprep=False) for a
            # sample that's already perfectly prepared.
            use_path = ref_path
            already_prepared = ref_path.name.lower().endswith(".clone.wav")
            if bool(getattr(cfg, "tts_clone_autoprep", True)) and not already_prepared:
                prepared = ref_path.with_suffix(".clone.wav")
                try:
                    if (not prepared.is_file()
                            or prepared.stat().st_mtime < ref_path.stat().st_mtime):
                        print(f"      preparing voice-clone sample from {ref_path.name}")
                        prepare_voice_sample(ref_path, prepared)
                    use_path = prepared
                except Exception as e:
                    print(f"      voice sample prep failed ({str(e)[:120]}); using raw file")
                    use_path = ref_path
            kwargs["audio_prompt_path"] = str(use_path)
        else:
            print(f"      WARN: voice reference audio not found: {ref_path} — using default voice")

    # Chunk to stay under Chatterbox's tokenizer limit. A single
    # `model.generate()` call on a long script triggers a CUDA embedding
    # OOB ("srcIndex < srcSelectDimSize") that poisons the process state.
    # Chunking + concatenation produces identical-sounding output without
    # the crash, at the cost of a couple of extra generate() calls.
    chunks = _split_sentences_for_tts(text, max_chars=_CHATTERBOX_MAX_CHARS)
    if not chunks:
        raise RuntimeError("Chatterbox: empty text after chunking")
    if len(chunks) > 1:
        print(f"      chatterbox: splitting into {len(chunks)} chunk(s) "
              f"to stay under tokenizer limit")
    try:
        import torch  # type: ignore
        gen_kwargs = dict(kwargs)
        if multilingual and language_id:
            gen_kwargs["language_id"] = language_id
        pieces = []
        for i, chunk_text in enumerate(chunks, 1):
            if len(chunks) > 1:
                print(f"      chatterbox chunk {i}/{len(chunks)} ({len(chunk_text)} chars)")
            piece = model.generate(chunk_text, **gen_kwargs)
            pieces.append(piece)
        wav = pieces[0] if len(pieces) == 1 else torch.cat(pieces, dim=-1)
    except Exception as e:
        raise RuntimeError(f"Chatterbox generation failed: {e}") from e

    # Chatterbox returns a torch tensor at model.sr. Save WAV, then transcode
    # to MP3 because the rest of the pipeline (ffmpeg mixers, captions
    # alignment, etc.) standardized on MP3.
    wav_path = out_path.with_suffix(".wav")
    try:
        ta.save(str(wav_path), wav, model.sr)
    except Exception as e:
        raise RuntimeError(f"Chatterbox WAV save failed: {e}") from e
    run([
        "ffmpeg", "-y", "-i", str(wav_path),
        "-c:a", "libmp3lame", "-q:a", "2",
        str(out_path),
    ])
    try:
        wav_path.unlink()
    except Exception:
        pass
    if not out_path.is_file() or out_path.stat().st_size < 200:
        raise RuntimeError(f"Chatterbox produced empty/missing output: {out_path}")
    return out_path


def prepare_voice_sample(src_path: Path, out_path: Path,
                         max_secs: float = 12.0) -> Path:
    """Turn an arbitrary recording (phone memo, video, any audio) into a
    clean Chatterbox voice-clone reference: mono 24 kHz, leading silence
    trimmed, capped to ~max_secs, lightly loudness-normalized. Chatterbox
    clones best from 7-12s of clean, single-speaker speech — this gives it
    exactly that without the user having to edit anything.

    Returns out_path. Raises if the result is empty (e.g. the source was
    pure silence)."""
    run([
        "ffmpeg", "-y", "-i", str(src_path),
        "-vn", "-ac", "1", "-ar", "24000",
        "-af",
        # strip leading silence, then gently even out the level
        "silenceremove=start_periods=1:start_duration=0.08:start_threshold=-45dB,"
        "loudnorm=I=-18:TP=-2:LRA=11",
        "-t", f"{max_secs:.1f}",          # cap to the first max_secs of speech
        str(out_path),
    ])
    if not out_path.is_file() or out_path.stat().st_size < 2000:
        raise RuntimeError(
            f"voice sample prep produced empty output from {src_path} "
            "(is the recording silent or unreadable?)"
        )
    return out_path


def trim_leading_silence(in_path: Path, out_path: Path,
                         threshold_db: float = -45.0,
                         keep_seconds: float = 0.05) -> Path:
    """Strip the TTS engine's leading dead air so the voiceover starts at t~=0."""
    run([
        "ffmpeg", "-y", "-i", str(in_path),
        "-af", f"silenceremove=start_periods=1:start_silence={keep_seconds}:start_threshold={threshold_db}dB",
        "-c:a", "libmp3lame", "-q:a", "4",
        str(out_path),
    ])
    return out_path


def _concat_audio(parts: list[Path], out_path: Path) -> Path:
    """Concatenate mp3 audio files in order into out_path (re-encoded so the
    join is clean regardless of per-file encoder settings)."""
    parts = [p for p in parts if p and Path(p).is_file()]
    if not parts:
        raise RuntimeError("concat_audio: no input files")
    if len(parts) == 1:
        if Path(parts[0]) != Path(out_path):
            run(["ffmpeg", "-y", "-i", str(parts[0]),
                 "-c:a", "libmp3lame", "-q:a", "2", str(out_path)])
        return out_path
    listing = out_path.with_suffix(".concat.txt")
    listing.write_text(
        "\n".join(f"file '{Path(p).resolve().as_posix()}'" for p in parts),
        encoding="utf-8",
    )
    run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
        "-c:a", "libmp3lame", "-q:a", "2", str(out_path),
    ])
    try: listing.unlink()
    except Exception: pass
    return out_path


def _grow_voiceover_to_target(script: str, vo: Path, vo_dur: float, cfg: "Config",
                              target_seconds: float, language: str, work: Path,
                              on_step=None, accept_frac: float = 0.92,
                              max_rounds: int = 8) -> tuple[Path, float, str]:
    """Close the loop on long-form length using the REAL spoken duration.

    The wps estimate is unreliable (Chatterbox at the viral preset speaks far
    faster than the 2.5 wps guess), so a script sized to 600s-of-estimate can
    come out as ~350s of actual audio. Here we measure the rendered voiceover,
    compute the speaker's true wps, extend the script by the genuinely-missing
    words, synthesize ONLY the addition, and append it to the audio — repeating
    until the real audio reaches accept_frac × target.

    Returns (voice_path, voice_duration, full_script). No-op (returns inputs)
    when already long enough or when there's no text backend."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass

    if target_seconds < 90:
        return vo, vo_dur, script
    have_backend = bool(cfg.gemini_api_key or getattr(cfg, "use_claude_cli", False))
    if not have_backend:
        return vo, vo_dur, script

    accept_secs = target_seconds * accept_frac
    parts = [vo]
    full_script = script
    for rnd in range(1, max_rounds + 1):
        if vo_dur >= accept_secs:
            break
        # Real measured speech rate from everything spoken so far.
        spoken_words = len(full_script.split())
        real_wps = spoken_words / vo_dur if vo_dur > 1 else (
            _WPS_EN if language == "en" else _WPS_DE)
        deficit_secs = target_seconds - vo_dur
        need_words = int(deficit_secs * real_wps)
        if need_words < 40:
            break
        log(f"      voice {vo_dur:.0f}s < target {target_seconds:.0f}s "
            f"(real {real_wps:.1f} w/s) — round {rnd}/{max_rounds}, "
            f"writing ~{need_words}w more")
        addition = _continuation_block(full_script, cfg, need_words, language,
                                       on_step=on_step)
        if not addition.strip():
            log("      no more script produced — stopping voice growth")
            break
        full_script = full_script.rstrip() + " " + addition.lstrip()
        # Synthesize ONLY the new text and append its audio.
        try:
            piece_raw = synthesize_voiceover(addition, cfg, work / f"voice_ext_{rnd}_raw.mp3")
            piece = trim_leading_silence(piece_raw, work / f"voice_ext_{rnd}.mp3")
        except Exception as e:
            log(f"      voice extension TTS failed: {str(e)[:120]} — stopping")
            break
        piece_dur = probe_duration(piece)
        if piece_dur < 0.5:
            break
        parts.append(piece)
        vo_dur += piece_dur

    if len(parts) == 1:
        return vo, vo_dur, full_script
    merged = _concat_audio(parts, work / "voice_full.mp3")
    merged_dur = probe_duration(merged)
    log(f"      final voice: {merged_dur:.0f}s (target ~{target_seconds:.0f}s, "
        f"{len(parts)} segments)")
    return merged, merged_dur, full_script


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


# Video encoder selection. NVENC (NVIDIA GPU) is 5-10x faster than libx264 for
# the final encode on an RTX card. Mode is set once per run from cfg.video_encoder.
_VIDEO_ENCODER_MODE = "auto"   # "auto" | "nvenc" | "cpu"
_NVENC_CACHED: bool | None = None


def set_video_encoder_mode(mode: str) -> None:
    """Called at the start of run_one/run_multiclip from cfg.video_encoder."""
    global _VIDEO_ENCODER_MODE
    _VIDEO_ENCODER_MODE = (mode or "auto").strip().lower()
    if _VIDEO_ENCODER_MODE not in ("auto", "nvenc", "cpu"):
        _VIDEO_ENCODER_MODE = "auto"


def _nvenc_available() -> bool:
    """True if h264_nvenc should be used. Honors the forced modes; in auto it
    probes `ffmpeg -encoders` once and caches the result."""
    global _NVENC_CACHED
    if _VIDEO_ENCODER_MODE == "cpu":
        return False
    if _VIDEO_ENCODER_MODE == "nvenc":
        return True
    if _NVENC_CACHED is None:
        try:
            proc = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=15,
            )
            _NVENC_CACHED = "h264_nvenc" in (proc.stdout or "")
        except Exception:
            _NVENC_CACHED = False
    return _NVENC_CACHED


def _vcodec(quality: str = "standard") -> list:
    """ffmpeg video-codec args, NVENC-first. `quality`: 'standard' (final
    output) or 'fast' (intermediate re-encodes). Does NOT emit -pix_fmt — call
    sites keep their own where needed."""
    if _nvenc_available():
        if quality == "standard":
            return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
        return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "26"]
    if quality == "standard":
        return ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]


def mix_voice_with_music(voice_path: Path, music_path: Path, volume_pct: float,
                         out_path: Path, start_offset: float = 0.0,
                         sidechain: bool = True) -> Path:
    """Loop music under voice at given volume (%). Output ends with the voice.
    `start_offset` skips into the music track before mixing.

    Polish:
    - Sidechain ducking: the music ducks DYNAMICALLY under the voice (pumps
      back up during silence/intro/image-only beats) instead of sitting at a
      flat low level the whole time. Makes the music breathe. Falls back to a
      plain static mix if the sidechain filter errors.
    - Intro swell + outro fade: 1.2s fade-in so the music establishes before
      the hook, and a fade-out over the last ~1.8s so the video ends clean
      instead of cutting the music dead.
    """
    pct = max(0.0, min(volume_pct, 100.0)) / 100.0
    # Quadratic taper: matches perceived loudness so low slider values are actually quiet.
    # e.g. 3% -> 0.0009 (~-60dB), 10% -> 0.01 (~-40dB), 30% -> 0.09 (~-21dB).
    vol = pct * pct
    music_args = ["-stream_loop", "-1"]
    if start_offset > 0.05:
        music_args = ["-ss", f"{start_offset:.2f}", "-stream_loop", "-1"]

    # Music fade chain (intro swell always; outro fade only if we know the
    # voice is long enough that a 1.8s tail won't eat the whole track).
    try:
        vdur = _media_duration(voice_path)
    except Exception:
        vdur = 0.0
    fades = ""
    if vdur > 2.0:
        fades += ",afade=t=in:st=0:d=1.2"
    if vdur > 4.0:
        fades += f",afade=t=out:st={max(0.0, vdur - 1.8):.2f}:d=1.8"

    base = ["ffmpeg", "-y", "-i", str(voice_path), *music_args, "-i", str(music_path)]
    tail = ["-map", "[mix]", "-c:a", "libmp3lame", "-q:a", "4", str(out_path)]

    if sidechain:
        # Normalize both signals to a common format so sidechaincompress can
        # key the music off the voice envelope.
        norm = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
        fc = (
            f"[0:a]{norm},asplit=2[vmain][vsc];"
            f"[1:a]{norm},volume={vol:.4f}{fades}[bgm];"
            f"[bgm][vsc]sidechaincompress=threshold=0.03:ratio=6:attack=5:release=250[bgmduck];"
            f"[vmain][bgmduck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]"
        )
        try:
            run(base + ["-filter_complex", fc] + tail)
            return out_path
        except Exception:
            pass  # fall through to the plain static mix below

    fc = (
        f"[1:a]volume={vol:.4f}{fades}[bgm];"
        f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]"
    )
    run(base + ["-filter_complex", fc] + tail)
    return out_path


def apply_voice_eq(voice_path: Path, out_path: Path, on_step=None) -> Path:
    """Broadcast-style voice chain on the raw TTS output: high-pass to kill
    rumble, a gentle presence lift around 3 kHz so the voice cuts through music,
    a soft de-ess at ~7 kHz, and a compressor to even out levels and add body.
    Makes free local TTS sound like a mixed voiceover. Falls back to the input
    on any ffmpeg error so it never blocks a render."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
    af = (
        "highpass=f=80,"
        "equalizer=f=3000:width_type=o:width=1.5:g=3,"
        "equalizer=f=7000:width_type=o:width=1.5:g=-3,"
        "acompressor=threshold=0.05:ratio=4:attack=5:release=80:makeup=2"
    )
    try:
        run([
            "ffmpeg", "-y", "-i", str(voice_path),
            "-af", af, "-c:a", "libmp3lame", "-q:a", "2", str(out_path),
        ])
    except Exception as e:
        log(f"      Voice-EQ fehlgeschlagen ({str(e)[:120]}) — Original behalten")
        return voice_path
    if not out_path.is_file() or out_path.stat().st_size < 200:
        return voice_path
    return out_path


def normalize_loudness(audio_path: Path, out_path: Path,
                       target_lufs: float = -14.0,
                       true_peak: float = -1.5) -> Path:
    """EBU R128 loudness normalization via ffmpeg's loudnorm filter. Brings
    the final mix up to a consistent broadcast-style loudness so our shorts
    are as punchy and even as the reference clips (which sit around
    -11..-14 LUFS with a tiny loudness range). Single-pass loudnorm — good
    enough for spoken-word + music shorts, and never clips above true_peak.

    target_lufs: integrated loudness target. -14 = YouTube/Spotify norm
    (louder uploads get turned down anyway); go to -11 for TikTok punch.
    """
    run([
        "ffmpeg", "-y", "-i", str(audio_path),
        "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11",
        "-c:a", "libmp3lame", "-q:a", "2",
        str(out_path),
    ])
    if not out_path.is_file() or out_path.stat().st_size < 200:
        raise RuntimeError(f"loudnorm produced empty output: {out_path}")
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
        *_vcodec("fast"),
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
            *_vcodec("fast"),
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
        *_vcodec("fast"),
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


def extract_thumbnail(source: Path, at_seconds: float, out_path: Path,
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
        if not extract_thumbnail(source, t, thumb, width=640):
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


def get_yolo_face_detector():
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


def get_insightface():
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


def get_mediapipe_detector():
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
    yolo = get_yolo_face_detector()
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
    app = get_insightface()
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
    fd = get_mediapipe_detector()
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


def _gemini_vision_score(thumb_path: Path, prompt: str, cfg) -> tuple:
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
        get_yolo_face_detector()
        or get_insightface()
        or get_mediapipe_detector()
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
    if not extract_thumbnail(source, at_time, sample_path, width=640):
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
        if extract_thumbnail(source, thumb_t, thumb_path):
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


def _fill_word_gaps(raw):
    """Turn WhisperX's raw word list into clean (start, end, word) tuples.

    WhisperX force-aligns most words, but a few tokens (digits, symbols, some
    punctuation) can come back WITHOUT start/end. Dropping them would lose words
    from the captions, so we interpolate timing from the neighbours instead:
    a gap inherits the previous word's end as its start and the next word's
    start as its end. Leading/trailing gaps borrow the adjacent timestamp.

    `raw` is a list of [start_or_None, end_or_None, word]. Returns a list of
    (float start, float end, str word) with start <= end and no None left.
    """
    items = [[s, e, str(w).strip()] for (s, e, w) in raw if str(w).strip()]
    n = len(items)
    if n == 0:
        return []

    # Forward fill missing starts from the previous word's END (its real
    # boundary), tracking the latest known end as we go.
    prev_end = 0.0
    for it in items:
        it[0] = prev_end if it[0] is None else float(it[0])
        prev_end = float(it[1]) if it[1] is not None else it[0]

    # Backward fill missing ends from the next word's START; clamp end >= start.
    next_start = items[-1][0]
    for i in range(n - 1, -1, -1):
        it = items[i]
        it[1] = next_start if it[1] is None else float(it[1])
        if it[1] < it[0]:
            it[1] = it[0]
        next_start = it[0]

    return [(float(a), float(b), c) for (a, b, c) in items]


def transcribe_words_whisperx_subprocess(audio_path: Path, model_name: str,
                                         device: str = "auto", language: str = "auto",
                                         python_exe: str = "", on_step=None):
    """Word-level transcription with sequential faster-whisper RECOGNITION +
    WhisperX wav2vec2 TIMING alignment.

    Recognition uses plain sequential faster-whisper (same engine/settings as
    transcribe_words_subprocess) so the recognized TEXT matches the non-whisperx
    path exactly — the batched whisperx pipeline recognizes words slightly
    worse. WhisperX is then used ONLY to force-align that text for tighter word
    boundaries; if alignment fails, faster-whisper's own word timestamps are
    used instead (= the old path). Same return shape (list[(start, end, word)],
    device_used). The child writes a JSON sidecar before any CUDA destructor
    runs.

    `python_exe` selects the interpreter for the child: point it at a SEPARATE
    venv that has whisperx + torch installed (cfg.whisperx_python), because
    whisperx's deps conflict with the main venv's Chatterbox stack. Empty =
    this interpreter (sys.executable).

    Raises RuntimeError on failure so the caller can fall back to plain
    faster-whisper. First run downloads a small wav2vec2 alignment model per
    language (free, cached by HuggingFace).
    """
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    exe = (python_exe or "").strip() or sys.executable
    if (python_exe or "").strip() and not Path(exe).exists():
        raise RuntimeError(
            f"whisperx_python points to a missing interpreter: {exe}")

    out_json = audio_path.with_suffix(".wxwords.json")
    if out_json.exists():
        try: out_json.unlink()
        except Exception: pass

    devices = (
        ["cuda", "cpu"] if device == "auto"
        else ["cuda"] if device == "cuda"
        else ["cpu"]
    )
    lang_arg = "" if language in ("auto", "", None) else str(language)
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
        "import whisperx\n"
        "from faster_whisper import WhisperModel\n"
        "audio_path, model_name, device, lang, out_json = sys.argv[1:6]\n"
        "ct = 'float16' if device == 'cuda' else 'int8'\n"
        # Recognition: use plain SEQUENTIAL faster-whisper (same engine/settings
        # as the non-whisperx path) so the TEXT quality matches exactly. The
        # batched whisperx pipeline is faster but recognizes words slightly
        # worse. We keep faster-whisper's own word timestamps as a fallback.
        "model = WhisperModel(model_name, device=device, compute_type=ct)\n"
        "seg_iter, info = model.transcribe(audio_path, word_timestamps=True, language=(lang or None))\n"
        "segs = []\n"
        "fw_words = []\n"
        "for s in seg_iter:\n"
        "    t = (s.text or '').strip()\n"
        "    if t:\n"
        "        segs.append({'start': float(s.start), 'end': float(s.end), 'text': t})\n"
        "    for w in (s.words or []):\n"
        "        ww = str(w.word).strip()\n"
        "        if ww:\n"
        "            fw_words.append([float(w.start), float(w.end), ww])\n"
        "detected = (lang or getattr(info, 'language', None) or 'en')\n"
        # Timing: force-align faster-whisper's exact text with whisperx (wav2vec2)
        # for tighter word boundaries. If alignment fails for any reason, we fall
        # back to faster-whisper's own word timestamps (= the old path).
        "out = []\n"
        "if segs:\n"
        "    try:\n"
        "        align_model, metadata = whisperx.load_align_model(language_code=detected, device=device)\n"
        "        audio = whisperx.load_audio(audio_path)\n"
        "        aligned = whisperx.align(segs, align_model, metadata, audio, device, return_char_alignments=False)\n"
        "        for seg in aligned.get('segments', []):\n"
        "            for w in seg.get('words', []):\n"
        "                word = str(w.get('word', '')).strip()\n"
        "                if not word:\n"
        "                    continue\n"
        "                s2 = w.get('start'); e2 = w.get('end')\n"
        "                out.append([None if s2 is None else float(s2), None if e2 is None else float(e2), word])\n"
        "    except Exception as align_err:\n"
        "        sys.stderr.write('whisperx align failed: ' + str(align_err) + '\\n')\n"
        "        out = []\n"
        "if not out:\n"
        "    out = fw_words\n"
        "with open(out_json, 'w', encoding='utf-8') as f:\n"
        "    json.dump(out, f)\n"
        "print(f'OK {len(out)} words', flush=True)\n"
    )
    last_err = None
    for dev in devices:
        try:
            proc = subprocess.run(
                [exe, "-c", child_code, str(audio_path), model_name, dev, lang_arg, str(out_json)],
                capture_output=True, text=True, timeout=900,
            )
        except subprocess.TimeoutExpired:
            last_err = f"timeout on {dev}"
            continue
        if out_json.exists() and out_json.stat().st_size > 2:
            try:
                arr = json.loads(out_json.read_text(encoding="utf-8"))
                words = _fill_word_gaps(arr)
                if words:
                    return words, dev
            except Exception as e:
                last_err = f"parse error on {dev}: {e}"
        err_tail = (proc.stderr or "").strip().splitlines()[-8:]
        last_err = f"subprocess exit {proc.returncode} on {dev}: " + " | ".join(err_tail)
        log(f"      whisperx {dev} failed: {last_err[:200]}")
    raise RuntimeError(f"transcribe_words_whisperx_subprocess failed: {last_err}")


def transcribe_words_best(audio_path: Path, model_name: str, device: str = "auto",
                          use_whisperx: bool = False, language: str = "auto",
                          whisperx_python: str = "", on_step=None):
    """Dispatcher: WhisperX (tight word alignment) when enabled, else plain
    faster-whisper. WhisperX runs in its own venv (whisperx_python). WhisperX
    failures fall back automatically so a render is never blocked by a missing
    dep or a bad align model. Returns the same (words, device) shape as the
    underlying transcribers."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    if use_whisperx:
        try:
            where = "eigenes venv" if (whisperx_python or "").strip() else "Haupt-venv"
            log(f"      WhisperX: word-level alignment aktiv ({where})")
            return transcribe_words_whisperx_subprocess(
                audio_path, model_name, device=device, language=language,
                python_exe=whisperx_python, on_step=on_step,
            )
        except Exception as e:
            log(f"      WhisperX nicht verfügbar/fehlgeschlagen ({str(e)[:160]}) "
                "→ Fallback auf faster-whisper")
    return transcribe_words_subprocess(
        audio_path, model_name, device=device, on_step=on_step,
    )


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


# Keyword → emoji map for caption decoration. When a caption chunk contains
# a trigger word, the matching emoji is placed on a line below it — exactly
# the pattern top Roblox shorts use (😱 on shock, 💰 on money, ⚠️ on a
# warning). Deterministic and cheap (no LLM call); only fires on a match, so
# most captions stay clean like the reference. German + English triggers.
# Order matters: first match wins, so put the most specific words first.
_CAPTION_EMOJI_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    # Order matters: first match wins, so strong/specific signals go first.
    (("geld", "reich", "money", "rich", "robux", "millionen", "million", "cash", "diamant", "gems", "dollar", "euro", "bezahlt", "kaufen"), "💰"),
    (("achtung", "warnung", "gefahr", "vorsicht", "warning", "danger", "verboten", "niemals", "never", "stop", "pass auf"), "⚠️"),
    (("getötet", "tötet", "tödlich", "gestorben", "stirbt", "ermordet", "killed", "kills", "death", "deadly", "murder"), "💀"),
    (("blut", "blutig", "blood", "bloody", "wunde"), "🩸"),
    (("messer", "mord", "mörder", "knife", "stab", "klinge", "waffe", "weapon"), "🔪"),
    (("geist", "gespenst", "ghost", "spuk", "haunted", "seele", "verflucht", "fluch", "cursed", "dämon", "demon"), "👻"),
    (("schock", "krass", "wahnsinn", "unglaublich", "shock", "insane", "crazy", "omg", "wtf", "was?", "plötzlich", "suddenly"), "😱"),
    (("mindblown", "verrückt", "unfassbar", "explodiert", "kopf", "mind blown", "speechless", "sprachlos"), "🤯"),
    (("angst", "gruselig", "creepy", "horror", "scary", "albtraum", "nightmare", "dunkel", "nacht", "night", "schatten", "shadow", "grusel"), "😨"),
    (("böse", "evil", "villain", "bösewicht", "teuflisch", "sinister", "grin"), "😈"),
    (("boss", "stark", "mächtig", "macht", "power", "strong", "legende", "legend", "episch", "epic"), "🔥"),
    (("krone", "crown", "royal", "vip", "könig", "king", "prinz", "queen", "königin"), "👑"),
    (("gewonnen", "sieg", "win", "gewinn", "champion", "best", "beste", "nummer eins", "number one", "gewinner", "winner"), "🏆"),
    (("selten", "rare", "diamond", "legendär", "legendary", "exklusiv", "exclusive", "wertvoll"), "💎"),
    (("lachen", "lustig", "funny", "lol", "haha", "witzig", "meme", "komisch"), "😂"),
    (("traurig", "weinen", "tränen", "sad", "crying", "tears", "heartbroken", "schluchz"), "😭"),
    (("wütend", "wut", "sauer", "angry", "rage", "hass", "hate", "zorn", "furious"), "😡"),
    (("liebe", "love", "herz", "heart", "süß", "cute", "verliebt"), "❤️"),
    (("lüge", "gelogen", "lie", "lying", "fake", "betrug", "scam", "betrüger", "liar", "fälschung"), "🤥"),
    (("geheim", "secret", "versteckt", "hidden", "trick", "hack", "cheat", "glitch", "exploit"), "🤫"),
    (("schau", "guck", "look", "watch", "sieh", "seht", "achte", "beobachte", "anschauen"), "👀"),
    (("schlau", "klug", "genie", "smart", "brain", "clever", "iq", "denk mal"), "🧠"),
    (("zeit", "schnell", "time", "hurry", "quick", "sekunden", "seconds", "sofort", "instantly", "eilig"), "⏰"),
    (("rennen", "flucht", "fliehen", "run", "escape", "weglaufen", "entkommen", "flee", "rennt"), "🏃"),
    (("gesperrt", "locked", "verschlossen", "tür", "door", "safe", "tresor", "schloss"), "🔒"),
    (("geschenk", "gratis", "kostenlos", "free", "gift", "gewinnspiel", "giveaway", "umsonst"), "🎁"),
    (("rakete", "rocket", "boost", "viral", "wachsen", "grow", "explodiert wachstum", "durchgestartet"), "🚀"),
    (("training", "muskel", "stärke", "muscle", "gym", "kraft", "workout", "grind"), "💪"),
    (("spiel", "game", "gaming", "roblox", "level", "noob", "gamer", "spielen", "runde"), "🎮"),
    (("welt", "world", "jeder", "everyone", "alle", "menschheit", "global"), "🌍"),
    (("bitte", "please", "hoffe", "hope", "beten", "pray", "wunsch", "wünsche"), "🙏"),
    (("richtig", "correct", "stimmt", "wahr", "true", "endlich", "geschafft", "erfolg", "success"), "✅"),
    (("falsch", "wrong", "fehler", "mistake", "schiefgelaufen", "kaputt", "failed", "versagt"), "❌"),
    (("freund", "friend", "teilen", "share", "schicken", "send", "abonnier", "subscribe"), "🤝"),
    (("denken", "überleg", "think", "frage", "warum", "why", "wie", "how"), "🤔"),
]


def _emoji_for_caption(text: str) -> str:
    """Return a single contextual emoji for a caption chunk, or '' if no
    trigger word matches."""
    low = text.lower()
    for keywords, emoji in _CAPTION_EMOJI_KEYWORDS:
        if any(k in low for k in keywords):
            return emoji
    return ""


# Hex-codepoint id per emoji (used only for stable cache filenames; FE0F
# variation selectors dropped). Our curated caption-emoji set. Anything missing
# falls back to ord() of the first codepoint in get_emoji_png, so this map is a
# nicety, not a requirement.
_EMOJI_TWEMOJI_CODE: dict[str, str] = {
    "💰": "1f4b0", "⚠️": "26a0", "😱": "1f631", "😨": "1f628",
    "🔥": "1f525", "🏆": "1f3c6", "😂": "1f602", "❤️": "2764",
    "🤫": "1f92b", "🤝": "1f91d", "🤔": "1f914", "🌙": "1f319",
    "😎": "1f60e",
    # Session-4 expansion (more coverage + variety, incl. horror set).
    "💀": "1f480", "🩸": "1fa78", "🔪": "1f52a", "👻": "1f47b",
    "🤯": "1f92f", "😈": "1f608", "👑": "1f451", "💎": "1f48e",
    "😭": "1f62d", "😡": "1f621", "🤥": "1f925", "👀": "1f440",
    "🧠": "1f9e0", "⏰": "23f0", "🏃": "1f3c3", "🔒": "1f512",
    "🎁": "1f381", "🚀": "1f680", "💪": "1f4aa", "🎮": "1f3ae",
    "🌍": "1f30d", "🙏": "1f64f", "✅": "2705", "❌": "274c",
}

_EMOJI_CACHE_DIR = Path.home() / ".cache" / "bezyzuta-emoji"

# Color emoji fonts, in preference order. Windows ships Segoe UI Emoji
# (scalable COLR — renders at any size); Linux usually has Noto Color Emoji
# (bitmap CBDT — only its built-in strike size, we resize after). First one
# that exists wins. cfg.emoji_font_path can override.
_COLOR_EMOJI_FONTS = [
    r"C:\Windows\Fonts\seguiemj.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
]
_EMOJI_FONT_CACHE: list | None = None   # [path] or [] once probed


def _find_emoji_font(override: str = "") -> str | None:
    """Return a usable color-emoji font path, or None. Cached."""
    global _EMOJI_FONT_CACHE
    if override:
        return override if Path(override).is_file() else None
    if _EMOJI_FONT_CACHE is not None:
        return _EMOJI_FONT_CACHE[0] if _EMOJI_FONT_CACHE else None
    for f in _COLOR_EMOJI_FONTS:
        if Path(f).is_file():
            _EMOJI_FONT_CACHE = [f]
            return f
    _EMOJI_FONT_CACHE = []
    return None


def _chunk_words(words, chunk_size: int):
    """Group timed words into chunks of `chunk_size`. Shared by the caption
    renderer and the emoji-overlay scheduler so their timing matches exactly."""
    chunks, buf = [], []
    for w in words:
        buf.append(w)
        if len(buf) >= chunk_size:
            chunks.append(buf)
            buf = []
    if buf:
        chunks.append(buf)
    return chunks


def get_emoji_png(emoji: str, font_path: str = "", px: int = 160) -> Path | None:
    """Render `emoji` to a transparent color PNG using a local color-emoji
    font (Segoe UI Emoji on Windows, Noto Color Emoji on Linux). No network.
    Cached on disk. Returns None if Pillow or a color font is unavailable, so
    the caller can fall back to the monochrome ASS-text emoji."""
    code = _EMOJI_TWEMOJI_CODE.get(emoji) or f"u{ord(emoji[0]):x}"
    _EMOJI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = _EMOJI_CACHE_DIR / f"{code}_{px}.png"
    if dest.is_file() and dest.stat().st_size > 200:
        return dest

    font_file = _find_emoji_font(font_path)
    if not font_file:
        return None
    try:
        from PIL import Image, ImageFont, ImageDraw  # type: ignore
    except Exception:
        return None

    try:
        # Scalable COLR fonts (Segoe) load at any size. Bitmap CBDT fonts
        # (Noto) only load at a built-in strike — load big, resize after.
        try:
            font = ImageFont.truetype(font_file, px)
        except OSError:
            font = ImageFont.truetype(font_file, 109)  # Noto's native strike

        img = Image.new("RGBA", (px * 2, px * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        try:
            draw.text((px // 2, px // 2), emoji, font=font, embedded_color=True)
        except TypeError:
            # Very old Pillow without embedded_color → monochrome, not useful.
            return None
        bbox = img.getbbox()
        if not bbox:
            return None
        img = img.crop(bbox)
        if max(img.size) != px:
            scale = px / max(img.size)
            img = img.resize((max(1, int(img.width * scale)),
                              max(1, int(img.height * scale))), Image.LANCZOS)
        tmp = dest.with_suffix(".part.png")
        img.save(tmp)
        tmp.replace(dest)
    except Exception as e:
        print(f"      emoji render failed for {emoji}: {str(e)[:120]}")
        return None
    return dest if dest.is_file() and dest.stat().st_size > 200 else None


def compute_caption_emoji_events(words, long_form: bool = False) -> list[tuple[float, float, str, str]]:
    """Replicate write_ass's chunking and return
    [(start, end, emoji, chunk_text), ...] for chunks whose text triggers an
    emoji. The chunk_text lets the caller estimate how many lines the caption
    wraps to, so the emoji can be placed tightly below it."""
    chunk_size = 8 if long_form else 3
    events: list[tuple[float, float, str, str]] = []
    for ch in _chunk_words(words, chunk_size):
        raw = " ".join(w[2] for w in ch)
        emo = _emoji_for_caption(raw)
        if emo:
            events.append((ch[0][0], ch[-1][1], emo, raw))
    return events


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
              subscribe_text: str = "SUBSCRIBE",
              total_duration: float = 0.0,
              enable_captions: bool = True,
              long_form: bool = False,
              caption_emojis: bool = False,
              caption_position: str = "bottom",
              emoji_overlay: bool = False,
              keyword_pop: bool = False,
              word_karaoke: bool = False,
              caption_polish: bool = False,
              caption_box: bool = False,
              caption_buildup: bool = False) -> Path:
    """Bold karaoke captions; styling exposed for the GUI.
    caption_polish: keep the 3-word chunk on screen but highlight the currently
    spoken word (bigger + yellow), walking word by word via the per-word timing
    — the modern viral look. Short-form only; takes precedence over word_karaoke.
    caption_box: like polish but the active word gets a filled yellow highlight
    box (black text). caption_buildup: the sentence types itself word by word.
    Both short-form only and take precedence over caption_polish when combined.
    Optional hook_text shown big at the top for the first hook_duration seconds.
    pop_captions: every chunk pops in with a scale animation (TikTok-style).
    subscribe_overlay: red SUBSCRIBE button in the last ~2.5s (needs total_duration).

    long_form: switches captions from TikTok-style (3-word ALL-CAPS karaoke
    pops anchored high in the frame) to readable long-video subtitles
    (~8-word phrases in original case, anchored near the bottom, no scale
    pop). Driven by landscape output — shorts (portrait) keep the punchy
    style unchanged.

    caption_position: "top" / "center" / "bottom". Top matches viral Roblox
    shorts (text above the center images). Forced to bottom for long_form.
    emoji_overlay: when True, emojis are rendered as color PNG overlays in
    compose_short, so we DON'T also bake the (monochrome) emoji into the ASS
    text here."""
    if font_size is None or font_size <= 0:
        # Portrait shorts: big chunky text sized off the tall dimension.
        # Landscape long-form: a calmer subtitle ~4.5% of frame height.
        font_size = max(40, int(video_h * 0.045)) if long_form else max(56, int(video_h * 0.048))
    primary = _hex_to_ass_color(primary_color)
    outline = _hex_to_ass_color(outline_color)
    hook_size = int(font_size * 1.4)
    sub_size = int(font_size * 1.2)
    # Caption anchor. Long-form is always bottom (normal subtitles); shorts
    # honor caption_position. ASS alignment: 2=bottom-center, 5=mid-center,
    # 8=top-center. MarginV is measured from the aligned edge.
    pos = "bottom" if long_form else (caption_position or "bottom").lower()
    if pos == "top":
        pop_align = 8
        pop_margin_v = max(40, int(video_h * 0.13))   # ~250px down on 1920
    elif pos == "center":
        pop_align = 5
        pop_margin_v = 0
    else:  # bottom
        pop_align = 2
        pop_margin_v = max(40, int(video_h * 0.06)) if long_form else 360
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
        f"1, 0, 0, 0, 100, 100, 0, 0, 1, {int(outline_width)}, 2, {pop_align}, 80, 80, {pop_margin_v}, 1\n"
        f"Style: Hook, {font_name}, {hook_size}, &H00FFFFFF, &H000000FF, &H00000000, &H64000000, "
        f"1, 0, 0, 0, 100, 100, 0, 0, 1, {int(outline_width) + 2}, 3, 8, 60, 60, 280, 1\n"
        # Red opaque box behind text (BorderStyle=3), white text. Sits above the captions.
        f"Style: Sub, {font_name}, {sub_size}, &H00FFFFFF, &H000000FF, &H000000FF, &H000000FF, "
        f"1, 0, 0, 0, 100, 100, 0, 0, 3, 12, 0, 2, 0, 0, 250, 1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    # Shorts: 3-word karaoke chunks (fast, punchy). Long-form: ~8-word
    # phrases that read like normal subtitles instead of flickering.
    chunk_size = 8 if long_form else 3
    chunks = _chunk_words(words, chunk_size)

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
    # Forced off in long-form — a scale-pop every 8 words for 10 minutes is
    # nauseating; long-form just fades.
    # accel < 1 = ease-out: the text snaps down fast then settles, reading as a
    # satisfying "pop" instead of a mechanical linear shrink.
    pop_tag = "\\fscx125\\fscy125\\t(0,150,0.6,\\fscx100\\fscy100)" if (pop_captions and not long_form) else ""

    # TikTok per-word karaoke: instead of 3-word chunks shown together,
    # emit ONE dialogue per word with a punchy pop+yellow-flash. Visually
    # this is the modern "single word reveals to the beat" style. Only for
    # short-form portrait (long-form keeps its 8-word readable lines).
    if enable_captions and (caption_buildup or caption_box) and not long_form:
        # Two opt-in caption styles that share the walking per-word highlight:
        #   caption_buildup: the sentence types itself word by word (each beat
        #     reveals one more word) instead of showing the whole chunk at once.
        #   caption_box: the active word gets a filled YELLOW HIGHLIGHT BOX
        #     (black text on a chunky opaque-yellow border that merges into a
        #     bar) — the Hormozi look. Combine them for a typed-out + boxed feel.
        # Takes precedence over caption_polish when several are ticked.
        box = bool(caption_box)
        buildup = bool(caption_buildup)
        if box:
            # Black text + thick opaque-yellow border ≈ a yellow box behind the
            # word. {\r} resets back to the Pop style (white text, normal border).
            hi_open = "\\1c&H000000&\\3c&H00FFFF&\\bord7\\shad0\\fscx110\\fscy110\\b1"
        else:
            hi_open = "\\c&H00FFFF&\\fscx116\\fscy116\\b1"
        for ch in chunks:
            cend = ch[-1][1]
            raw_full = " ".join(w[2] for w in ch).replace("{", "(").replace("}", ")")
            emo = _emoji_for_caption(raw_full) if (caption_emojis and not emoji_overlay) else ""
            n = len(ch)
            for i, w in enumerate(ch):
                ws = w[0]
                we = ch[i + 1][0] if i + 1 < n else cend
                if we <= ws:
                    we = w[1]
                # Buildup reveals words up to the current one; otherwise the
                # whole chunk stays and only the highlight walks.
                shown = ch[:i + 1] if buildup else ch
                parts = []
                for j, wj in enumerate(shown):
                    tok = (wj[2] or "").strip().upper().replace("{", "(").replace("}", ")")
                    if j == i:
                        parts.append("{" + hi_open + "}" + tok + "{\\r}")
                    else:
                        parts.append(tok)
                text = " ".join(parts)
                if emo:
                    text = f"{text}\\N{emo}"
                # Buildup grows the line each beat, so only fade the first word
                # in (later words just appear = typewriter). Static-box behaves
                # like polish: fade at the chunk's start/end, no mid-flicker.
                if buildup:
                    fade = "\\fad(50,0)" if i == 0 else ""
                elif n == 1:
                    fade = "\\fad(60,60)"
                elif i == 0:
                    fade = "\\fad(60,0)"
                elif i == n - 1:
                    fade = "\\fad(0,60)"
                else:
                    fade = ""
                lines.append(
                    f"Dialogue: 0,{_ass_time(ws)},{_ass_time(we)},Pop,,0,0,0,,"
                    f"{{{fade}}}{text}"
                )
    elif enable_captions and caption_polish and not long_form:
        # Caption-Polish: keep the readable 3-word chunk on screen, but light
        # up the CURRENTLY-spoken word (bigger + yellow) and let it walk word by
        # word using the tight per-word timing. The modern viral look. Uses the
        # whole chunk for context (better than single-word karaoke).
        hi_open = "\\c&H00FFFF&\\fscx116\\fscy116\\b1"   # active: yellow, bigger
        hi_close = "\\c&HFFFFFF&\\fscx100\\fscy100"        # rest: back to white
        for ch in chunks:
            cend = ch[-1][1]
            raw_full = " ".join(w[2] for w in ch).replace("{", "(").replace("}", ")")
            emo = _emoji_for_caption(raw_full) if (caption_emojis and not emoji_overlay) else ""
            n = len(ch)
            for i, w in enumerate(ch):
                ws = w[0]
                # Active word holds until the next word starts (highlight moves
                # exactly on the beat); the last word holds to the chunk end.
                we = ch[i + 1][0] if i + 1 < n else cend
                if we <= ws:
                    we = w[1]
                parts = []
                for j, wj in enumerate(ch):
                    tok = (wj[2] or "").strip().upper().replace("{", "(").replace("}", ")")
                    if j == i:
                        parts.append("{" + hi_open + "}" + tok + "{" + hi_close + "}")
                    else:
                        parts.append(tok)
                text = " ".join(parts)
                if emo:
                    text = f"{text}\\N{emo}"
                # Fade in only when the chunk first appears, fade out only on its
                # last word — middle slices cut cleanly so the line doesn't
                # flicker while the highlight walks across it.
                if n == 1:
                    fade = "\\fad(60,60)"
                elif i == 0:
                    fade = "\\fad(60,0)"
                elif i == n - 1:
                    fade = "\\fad(0,60)"
                else:
                    fade = ""
                lines.append(
                    f"Dialogue: 0,{_ass_time(ws)},{_ass_time(we)},Pop,,0,0,0,,"
                    f"{{{fade}}}{text}"
                )
    elif enable_captions and word_karaoke and not long_form:
        word_pop = "\\fscx150\\fscy150\\c&H00FFFF&\\t(0,160,0.6,\\fscx100\\fscy100\\c&HFFFFFF&)"
        for w in words:
            ws, we, wt = w[0], w[1], (w[2] or "").strip()
            if not wt:
                continue
            wt = wt.replace("{", "(").replace("}", ")").upper()
            lines.append(
                f"Dialogue: 0,{_ass_time(ws)},{_ass_time(we)},Pop,,0,0,0,,"
                f"{{{word_pop}\\fad(40,40)}}{wt}"
            )
    elif enable_captions:
        for ch in chunks:
            start, end = ch[0][0], ch[-1][1]
            raw = " ".join(w[2] for w in ch).replace("{", "(").replace("}", ")")
            # Shorts SHOUT in all-caps; long-form keeps Whisper's original
            # casing for comfortable reading over long durations.
            text = raw if long_form else raw.upper()
            # Optional contextual emoji on its own line below the caption,
            # mirroring the reference shorts. Only added when a trigger word
            # matches, so most captions stay clean. \\N = ASS hard newline.
            # Skipped when emoji_overlay is on — compose_short paints color
            # PNG emojis instead (libass would only render them monochrome).
            if caption_emojis and not emoji_overlay:
                emo = _emoji_for_caption(raw)
                if emo:
                    text = f"{text}\\N{emo}"
            # keyword_pop: chunks that hit a trigger word get a stronger,
            # briefly-yellow emphasis pop — draws the eye to the punchline.
            this_pop = pop_tag
            if keyword_pop and not long_form and _emoji_for_caption(raw):
                this_pop = ("\\fscx150\\fscy150\\c&H00FFFF&"
                            "\\t(0,180,\\fscx100\\fscy100\\c&HFFFFFF&)")
            lines.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Pop,,0,0,0,,"
                f"{{{this_pop}\\fad(80,80)}}{text}"
            )

    if subscribe_overlay and total_duration > 1.0:
        sub_start = max(0.0, total_duration - 2.5)
        sub_end = total_duration
        sub_txt = subscribe_text.strip().upper().replace("{", "(").replace("}", ")") or "SUBSCRIBE"
        lines.append(
            f"Dialogue: 2,{_ass_time(sub_start)},{_ass_time(sub_end)},Sub,,0,0,0,,"
            f"{{\\fad(180,0)\\fscx115\\fscy115\\t(0,250,\\fscx100\\fscy100)}}{sub_txt}"
        )

    out_path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return out_path


# Mandatory QUALITY suffix appended to every image prompt. Intentionally
# STYLE-NEUTRAL — it only nails render quality (lighting, detail, clean output),
# NOT the subject medium. Whether a beat looks like a blocky Roblox render or a
# photoreal shot is decided per-beat by the scene planner (see _SCENE_PLAN_PROMPT)
# or forced via cfg.image_style. Flux/Pollinations/Grok respond well to these.
_IMAGE_STYLE_SUFFIX = (
    "single subject centered, dramatic rim lighting, vibrant saturated colors, "
    "high detail, depth of field, no text, no watermark, no logos"
)

# Minimal suffix for FLAT styles (stickman / doodle) where the cinematic suffix
# above (rim lighting, saturated colors, depth of field) would fight the look.
_IMAGE_STYLE_SUFFIX_FLAT = "centered, no text, no watermark, no logos"

# Optional hard style override, keyed off cfg.image_style. "auto" (default) lets
# the scene planner pick the medium per beat. The named presets force one look
# for the whole video; any other non-empty value is used verbatim as the style.
_IMAGE_STYLE_PRESETS = {
    "roblox": "cinematic 3D render, Roblox blocky avatar character, dark atmospheric background, octane render",
    "realistic": "photorealistic, ultra-realistic photography, natural lighting, shot on a DSLR, 4k",
    "cinematic": "cinematic film still, dramatic composition, moody lighting, photorealistic",
    # Faceless / explainer styles (Danny-Why-style). These are FLAT — they use
    # _IMAGE_STYLE_SUFFIX_FLAT so the cinematic tokens don't pollute them.
    "ms_paint_stickman": (
        "The image must look like an extremely simple, poorly drawn stickman "
        "figure made in MS Paint. Sharp black lines, flat pure white background, "
        "absolutely no shading, no 3D effects, no professional digital art "
        "elements. It should look like it was drawn by a complete amateur in 10 seconds."
    ),
    "doodle_sketch": (
        "The image must be in a clean, hand-drawn doodle or pencil sketch style. "
        "Simple linework, white or very light background, minimalistic but "
        "aesthetic. It should look like a neat sketch from a notebook, not messy, "
        "but still maintaining a simple, flat minimalist cartoon vibe."
    ),
}

# Styles that are flat/hand-drawn → use the minimal suffix, never the cinematic
# one. Also drives the Roblox cap (these force 0 Roblox renders).
_FLAT_IMAGE_STYLES = {"ms_paint_stickman", "doodle_sketch"}


def _quality_suffix_for(cfg) -> str:
    """Pick the render-quality suffix that matches the chosen style: the flat
    minimal one for stickman/doodle, otherwise the cinematic default."""
    style = (getattr(cfg, "image_style", "auto") or "auto").strip().lower()
    return _IMAGE_STYLE_SUFFIX_FLAT if style in _FLAT_IMAGE_STYLES else _IMAGE_STYLE_SUFFIX


def _style_directive(cfg) -> str:
    """The forced style fragment for cfg.image_style, or "" for auto (the LLM's
    per-beat motif already carries its own medium)."""
    style = (getattr(cfg, "image_style", "auto") or "auto").strip()
    if not style or style.lower() == "auto":
        return ""
    return _IMAGE_STYLE_PRESETS.get(style.lower(), style)


def derive_image_prompt(seed_text: str, cfg=None) -> str:
    parts = [seed_text[:200].strip()]
    directive = _style_directive(cfg) if cfg is not None else ""
    if directive:
        parts.append(directive)
    parts.append(_quality_suffix_for(cfg) if cfg is not None else _IMAGE_STYLE_SUFFIX)
    return ", ".join(p for p in parts if p)


# Heuristic rewrite of a Roblox-flavored motif into a real-world one, so an AI
# beat can be rendered photoreal without the prompt fighting itself (a style
# suffix alone can't override "a Roblox blocky avatar" sitting in the motif).
# Longest phrases first so "roblox blocky avatar" wins over "avatar".
_DEROBLOX_REPL = [
    ("roblox blocky noob avatar", "person"),
    ("roblox blocky avatar", "person"),
    ("roblox noob avatar", "person"),
    ("blocky noob avatar", "person"),
    ("default noob avatar", "person"),
    ("roblox avatar", "person"),
    ("blocky avatar", "person"),
    ("noob avatar", "person"),
    ("default avatar", "person"),
    ("roblox character", "person"),
    ("game character", "person"),
    ("roblox map", "place"),
    ("roblox world", "place"),
    ("roblox game", "place"),
    ("roblox server", "room"),
    ("roblox 3d render", "cinematic photo"),
    ("3d render", "cinematic photo"),
    ("avatar", "person"),
    ("noob", "beginner"),
    ("blocky", ""),
    ("roblox", ""),
]


def _is_roblox_motif(motif: str) -> bool:
    m = (motif or "").lower()
    return any(tok in m for tok in ("roblox", "noob", "blocky"))


def _derobloxify(motif: str) -> str:
    """Turn a Roblox motif into a plausible real-world scene description."""
    s = motif or ""
    for a, b in _DEROBLOX_REPL:
        s = re.sub(re.escape(a), b, s, flags=re.IGNORECASE)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s+([,.])", r"\1", s)
    s = re.sub(r"(,\s*){2,}", ", ", s)
    s = s.strip(" ,.")
    return s or "a person in a dramatic cinematic scene"


def _roblox_cap(cfg) -> int:
    """Max number of Roblox-render AI beats allowed per video.
    image_style 'roblox' = unlimited; 'auto' = cfg.image_roblox_max (default 2);
    any other forced style (realistic/cinematic/custom) = 0 (no Roblox)."""
    style = (getattr(cfg, "image_style", "auto") or "auto").strip().lower()
    if style == "roblox":
        return 1_000_000
    if style == "auto":
        try:
            return max(0, int(getattr(cfg, "image_roblox_max", 2)))
        except (TypeError, ValueError):
            return 2
    return 0


def _enforce_roblox_cap(beats: list[dict], cfg) -> list[dict]:
    """Keep at most _roblox_cap(cfg) Roblox-render AI beats; rewrite the rest
    into non-Roblox scenes. The rewritten beat is re-finalized through the
    CHOSEN style (so a stickman video stays stickman, not photoreal). Mutates
    and returns the beat list."""
    cap = _roblox_cap(cfg)
    # When a style is forced (realistic/cinematic/flat), let it drive the look;
    # only fall back to the realistic preset in 'auto' mode.
    style = (getattr(cfg, "image_style", "auto") or "auto").strip().lower()
    seen = 0
    for b in beats:
        if b.get("source") != "ai":
            continue
        motif = b.get("motif", "")
        if not (motif and _is_roblox_motif(motif)):
            continue
        if seen < cap:
            seen += 1
            continue
        new_motif = _derobloxify(motif)
        b["motif"] = new_motif
        if style in ("auto", "roblox"):
            # auto: the cap exists to add photoreal variety, so force realistic.
            b["prompt"] = f"{new_motif}, {_IMAGE_STYLE_PRESETS['realistic']}, {_IMAGE_STYLE_SUFFIX}"
        else:
            # A forced style (incl. flat stickman/doodle) owns the look.
            b["prompt"] = _finalize_scene_prompt(new_motif, cfg)
    return beats


SCENE_PROMPT = """Du bekommst ein Voiceover-Skript fuer einen YouTube Short.

Finde die {n} staerksten visuellen Momente im Skript und schreibe pro Moment EINEN englischen Bild-Prompt. WICHTIG: Jeder Prompt muss zum konkret an dieser Stelle Gesagten passen und den Moment ILLUSTRIEREN. Waehle das Medium nach Inhalt: geht es um eine Roblox-/Spiel-Figur, beschreibe einen Roblox-3D-Render; geht es um etwas Reales oder Abstraktes (Person, Gefuehl, Geld, Stadt, Objekt, Ort), beschreibe ein FOTOREALISTISCHES/cinematisches Bild — KEINEN Roblox-Avatar erzwingen.

Beschreibe pro Prompt das HAUPTMOTIV konkret und bildhaft in Englisch, inklusive Medium (Roblox-Render ODER fotorealistisch). Den einheitlichen Qualitaets-Zusatz musst du NICHT dazuschreiben.

Beispiele fuer gute Motive:
- "a Roblox avatar in a golden suit wearing a diamond crown, surrounded by stacks of gold coins, triumphant pose"
- "a photorealistic shocked young man staring at a phone screen, hand over mouth, dramatic lighting"
- "a cinematic photo of stacks of cash and gold coins on a dark table, moody light"

Skript:
\"\"\"
{script}
\"\"\"

Antworte NUR mit einem gueltigen JSON-Array von genau {n} Strings (nur die Motive).
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


def _finalize_scene_prompt(motif: str, cfg=None) -> str:
    """Append the mandatory quality suffix (and any forced cfg.image_style
    directive) to an LLM-generated motif, unless already present. With
    image_style=auto the motif keeps the medium the planner chose for it.
    Flat styles (stickman/doodle) use the minimal suffix, not the cinematic one."""
    motif = motif.strip()
    suffix = _quality_suffix_for(cfg) if cfg is not None else _IMAGE_STYLE_SUFFIX
    if suffix in motif or _IMAGE_STYLE_SUFFIX in motif:
        return motif
    directive = _style_directive(cfg) if cfg is not None else ""
    parts = [motif]
    if directive:
        parts.append(directive)
    parts.append(suffix)
    return ", ".join(p for p in parts if p)


def generate_scene_prompts(script: str, n: int, cfg: Config) -> list[str]:
    base = derive_image_prompt(script[:200], cfg)
    raw: list[str] | None = None
    if cfg.gemini_api_key:
        try:
            raw = _scene_prompts_gemini(script, n, cfg, base)
        except _SceneGenError as e:
            print(f"      WARN: Gemini scene gen failed ({e})")
    if raw is None and cfg.cloudflare_account_id and cfg.cloudflare_api_token:
        try:
            print(f"      trying Cloudflare Llama for {n} scene prompts")
            raw = generate_scene_prompts_cloudflare(script, n, cfg)
        except Exception as e:
            print(f"      WARN: Cloudflare scene gen failed ({e}); falling back to single prompt")
    if raw is None:
        raw = [base] * n
    # Apply the quality/style suffix and pad/trim to exactly n.
    prompts = [_finalize_scene_prompt(p, cfg) for p in raw if p.strip()]
    while len(prompts) < n:
        prompts.append(base)
    return prompts[:n]


_SCENE_PLAN_PROMPT = """Du bist Editor fuer virale YouTube-Shorts. Plane die Bilder/Clips in der Mitte des Videos.

Teile dieses Skript in {n} chronologische Beats (Reihenfolge = Erzaehl-Reihenfolge). Fuer JEDEN Beat entscheide, welche Art Visual den gerade gesprochenen Satz am besten illustriert:

- "ai"    = ein generiertes Bild. WICHTIG zum Motiv: Das Bild muss zum konkret Gesagten passen. Geht es im Satz um eine Roblox-/Spiel-Figur (Avatar, Charakter, Item, Map), beschreibe einen Roblox-3D-Render. Geht es um etwas Reales oder Abstraktes (eine Person, ein Gefuehl, Geld, eine Stadt, ein Objekt, ein Ort), beschreibe ein passendes FOTOREALISTISCHES/cinematisches Bild — KEINEN Roblox-Avatar erzwingen. Waehle das Medium pro Beat nach dem Inhalt.
- "photo" = echtes Standbild {photo_hint}(Reaktion/Objekt: geschockte Person, Geldstapel, Pokal, Handschlag, usw.)
- "video" = echtes Stock-Video / B-Roll Clip {video_hint}fuer bewegte Action / Atmosphaere (rennen, klettern, Geld zaehlen, Explosion, Stadt bei Nacht, jubelnde Crowd, Lichter blitzen, usw.) — wenn Bewegung den Moment besser traegt als ein Standbild.

{mix_rule}

Fuer jeden Beat liefere:
- "source": "ai", "photo" oder "video"
- "motif": bei source=ai ein englischer Bild-Prompt. Beschreibe das HAUPTMOTIV konkret UND das Medium ("a Roblox blocky avatar ..." fuer Spiel-Figuren, sonst "a photorealistic ..." / "a cinematic photo of ..."). Keinen einheitlichen Render-Stil dazuschreiben — nur Motiv + ob Roblox-Render oder fotorealistisch. Sonst leer.
- "query": bei source=photo ODER video 2-4 englische Such-Stichworte (z.B. "shocked person face", "running fast pov", "money cash counting"). Sonst leer.

Skript:
\"\"\"
{script}
\"\"\"

Antworte NUR mit einem gueltigen JSON-Array von genau {n} Objekten. KEINE Markdown-Codebloecke, KEINE Kommentare."""


def generate_scene_plan(script: str, n: int, cfg: "Config",
                        allow_photos: bool = True, allow_videos: bool = False,
                        on_step=None) -> list[dict]:
    """Plan n chronological media beats, each tagged source=ai|photo|video
    with a motif (AI) or query (photo/video). Falls back to all-AI motifs
    from generate_scene_prompts if the structured call fails. Returns a list
    of dicts: {"source", "motif", "query", "prompt"}."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    def _fallback_ai() -> list[dict]:
        return [{"source": "ai", "motif": "", "query": "",
                 "prompt": p} for p in generate_scene_prompts(script, n, cfg)]

    if not (getattr(cfg, "use_claude_cli", False) or cfg.gemini_api_key):
        return _fallback_ai()

    video_hint = ("(z.B. action-clip, kein Standbild) " if allow_videos else "(NICHT VERWENDEN — deaktiviert) ")
    photo_hint = "" if allow_photos else "(NICHT VERWENDEN — deaktiviert) "
    if allow_photos or allow_videos:
        mix_rule = "Mische die Quellen wie echte virale Shorts. Faustregel: 30-50% ai, 30-50% photo/video, je nach Inhalt."
    else:
        # Photos AND videos are off → every beat MUST be source=ai with a real
        # motif. Without this the LLM still picks 'photo' for real-world stuff,
        # those beats get downgraded to empty AI beats, and the quality gate
        # wrongly retries with Gemini.
        mix_rule = ("WICHTIG: 'photo' und 'video' sind DEAKTIVIERT. Nutze fuer JEDEN "
                    "Beat ausschliesslich source='ai' und schreibe IMMER ein konkretes "
                    "englisches Motiv (auch fuer reale Dinge: dann fotorealistisch).")
    prompt_text = _SCENE_PLAN_PROMPT.format(
        n=n, script=script, video_hint=video_hint,
        photo_hint=photo_hint, mix_rule=mix_rule)
    body = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.7, "maxOutputTokens": 2048,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    def _attempt(prefer_claude: bool) -> tuple[list[dict], int] | None:
        """Run the planner once and return (normalized_beats, good_count), or
        None on a hard failure (LLM error / unparseable). A beat is "good" when
        it carries real content: a photo/video query, or an AI motif that isn't
        just the script text echoed back. good_count lets the caller decide
        whether the plan is worth keeping or should be retried with Gemini."""
        try:
            text = _complete_text(prompt_text, cfg, prefer_claude=prefer_claude,
                                  gemini_body=body, on_step=on_step)
        except Exception as e:
            log(f"      scene-plan LLM failed ({str(e)[:120]})")
            return None
        raw = text.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```\s*$", "", raw)
        s_idx, e_idx = raw.find("["), raw.rfind("]")
        if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
            raw = raw[s_idx:e_idx + 1]
        try:
            plan = json.loads(raw)
            assert isinstance(plan, list)
        except Exception as e:
            log(f"      scene-plan parse failed ({str(e)[:100]})")
            return None

        beats: list[dict] = []
        good = 0
        for beat in plan:
            if not isinstance(beat, dict):
                continue
            source = str(beat.get("source", "ai")).lower()
            if source not in ("ai", "photo", "video"):
                source = "ai"
            if source == "video" and not allow_videos:
                source = "photo" if allow_photos else "ai"
            if source == "photo" and not allow_photos:
                source = "ai"
            motif = str(beat.get("motif", "")).strip()
            query = str(beat.get("query", "")).strip()
            if source in ("photo", "video") and query:
                good += 1
                beats.append({"source": source, "motif": "", "query": query, "prompt": ""})
            else:
                # AI beat (or photo/video with no query → treat as AI). A motif
                # is only "good" if the LLM actually wrote one — an empty motif
                # falls back to the script text, which is the symptom we're
                # guarding against.
                if motif and motif[:60].lower() not in script.lower():
                    good += 1
                full = _finalize_scene_prompt(motif or script[:120], cfg)
                beats.append({"source": "ai", "motif": motif, "query": "", "prompt": full})
        return beats, good

    # Primary attempt (Claude first if enabled). If the plan comes back mostly
    # empty — the model answered but didn't actually fill in motifs/queries —
    # and Claude was the one used, explicitly retry with Gemini before giving
    # up to the all-AI fallback. Threshold: at least 60% of beats must be good.
    used_claude = bool(getattr(cfg, "use_claude_cli", False))
    result = _attempt(prefer_claude=True)
    min_good = max(1, round(n * 0.6))
    if result is not None and result[1] < min_good and used_claude and cfg.gemini_api_key:
        log(f"      scene-plan: only {result[1]}/{n} beats usable from Claude — "
            f"retrying with Gemini")
        gem = _attempt(prefer_claude=False)
        if gem is not None and gem[1] >= result[1]:
            result = gem
    if result is None or not result[0]:
        return _fallback_ai()
    out = result[0]
    # Limit how many AI beats may be Roblox renders; rewrite the rest photoreal.
    before = sum(1 for b in out if b.get("source") == "ai" and _is_roblox_motif(b.get("motif", "")))
    out = _enforce_roblox_cap(out, cfg)
    after = sum(1 for b in out if b.get("source") == "ai" and _is_roblox_motif(b.get("motif", "")))
    if before > after:
        log(f"      scene-plan: capped Roblox renders {before}→{after}, "
            f"rewrote {before - after} beat(s) photoreal")
    # pad/trim to n
    while len(out) < n:
        out.append({"source": "ai", "motif": "", "query": "",
                    "prompt": derive_image_prompt(script[:120], cfg)})
    return out[:n]


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


# Browser-like UA: Wikimedia rejects generic "python-requests", and some
# image hosts 403 datacenter/no-UA requests. A realistic UA maximizes the
# chance the free photo sources actually return an image.
_PHOTO_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 bezyzuta-shorts/1.0")


def _save_square_image(data: bytes, out_path: Path) -> bool:
    """Center-crop image bytes to a square RGBA PNG (<=1024). Returns True on
    success. Shared by all free-photo fetchers."""
    if not data or len(data) < 1024:
        return False
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(data)).convert("RGBA")
        w, h = im.size
        side = min(w, h)
        im = im.crop(((w - side) // 2, (h - side) // 2,
                      (w - side) // 2 + side, (h - side) // 2 + side))
        if side > 1024:
            im = im.resize((1024, 1024), Image.LANCZOS)
        im.save(out_path)
        return out_path.is_file() and out_path.stat().st_size > 512
    except Exception:
        return False


def _faceless_recrop(path: Path, ar: float = 16 / 9) -> None:
    """Best-effort re-crop an already-saved image file to `ar` in place. Used
    for faceless landscape when the generator (Grok / a size-ignoring API) put
    out a square — center-crop it to 16:9 so it fills the frame. Silent no-op
    on any error (the image still works, just not perfectly wide)."""
    try:
        data = path.read_bytes()
    except OSError:
        return
    tmp = path.with_suffix(".recrop.png")
    if _save_aspect_image(data, tmp, ar=ar):
        try:
            tmp.replace(path)
        except OSError:
            try: tmp.unlink()
            except OSError: pass


def _save_aspect_image(data: bytes, out_path: Path, ar: float = 16 / 9,
                       max_w: int = 1280) -> bool:
    """Center-crop image bytes to aspect ratio `ar` (default 16:9) and save as
    PNG. Used for faceless full-frame images so they fill a widescreen frame
    instead of being squared (which left white bars on the sides)."""
    if not data or len(data) < 1024:
        return False
    try:
        from PIL import Image
        import io
        im = Image.open(io.BytesIO(data)).convert("RGBA")
        w, h = im.size
        if w / h > ar:           # too wide → crop width
            new_w = int(round(h * ar))
            x0 = (w - new_w) // 2
            im = im.crop((x0, 0, x0 + new_w, h))
        else:                    # too tall → crop height
            new_h = int(round(w / ar))
            y0 = (h - new_h) // 2
            im = im.crop((0, y0, w, y0 + new_h))
        if im.width > max_w:
            im = im.resize((max_w, int(round(max_w / ar))), Image.LANCZOS)
        im.save(out_path)
        return out_path.is_file() and out_path.stat().st_size > 512
    except Exception:
        return False


def fetch_image_from_pexels(query: str, out_path: Path, cfg: "Config") -> Path:
    """Free real photo from Pexels (same API + key as the video endpoint).
    Often best-quality of the free sources — modern, well-shot, datacenter-
    friendly. Reuses cfg.pexels_api_key."""
    key = (getattr(cfg, "pexels_api_key", "") or "").strip()
    if not key:
        raise RuntimeError("pexels: no api key configured")
    q = (query or "").strip()
    if not q:
        raise RuntimeError("pexels: empty query")
    headers = {"Authorization": key, "User-Agent": _PHOTO_UA}
    params = {"query": q, "per_page": 12, "orientation": "portrait"}
    try:
        r = requests.get("https://api.pexels.com/v1/search",
                         params=params, headers=headers, timeout=30)
        r.raise_for_status()
        photos = (r.json() or {}).get("photos") or []
    except Exception as e:
        raise RuntimeError(f"pexels photo search failed: {str(e)[:160]}") from e
    if not photos:
        raise RuntimeError(f"pexels: no photo results for {q!r}")
    last_err = None
    for ph in photos:
        # Prefer large size; pexels gives multiple sizes per photo.
        src = (ph.get("src") or {})
        url = src.get("large") or src.get("large2x") or src.get("original")
        if not url:
            continue
        try:
            ir = requests.get(url, headers={"User-Agent": _PHOTO_UA}, timeout=30)
            ir.raise_for_status()
            if _save_square_image(ir.content, out_path):
                return out_path
        except Exception as e:
            last_err = str(e)[:140]
    raise RuntimeError(f"pexels: no usable photo for {q!r} ({last_err})")


def fetch_image_from_pixabay(query: str, out_path: Path, cfg: "Config") -> Path:
    """Free real photos via Pixabay. Needs a free API key (cfg.pixabay_api_key)
    — but it's the most reliable no-cost source: datacenter-friendly,
    hotlinkable URLs, generous limits. Get one in 30s at
    https://pixabay.com/api/docs/ (no credit card)."""
    key = (getattr(cfg, "pixabay_api_key", "") or "").strip()
    if not key:
        raise RuntimeError("pixabay: no api key configured")
    q = (query or "").strip()
    if not q:
        raise RuntimeError("pixabay: empty query")
    params = {
        "key": key, "q": q, "image_type": "photo",
        "per_page": 12, "safesearch": "true", "order": "popular",
    }
    try:
        r = requests.get("https://pixabay.com/api/", params=params,
                         headers={"User-Agent": _PHOTO_UA}, timeout=30)
        r.raise_for_status()
        hits = (r.json() or {}).get("hits") or []
    except Exception as e:
        raise RuntimeError(f"pixabay search failed: {str(e)[:160]}") from e
    if not hits:
        raise RuntimeError(f"pixabay: no results for {q!r}")
    last_err = None
    for hit in hits:
        img_url = hit.get("largeImageURL") or hit.get("webformatURL")
        if not img_url:
            continue
        try:
            ir = requests.get(img_url, headers={"User-Agent": _PHOTO_UA}, timeout=30)
            ir.raise_for_status()
            if _save_square_image(ir.content, out_path):
                return out_path
        except Exception as e:
            last_err = str(e)[:120]
    raise RuntimeError(f"pixabay: no usable image for {q!r} ({last_err})")


def fetch_video_from_pexels(query: str, out_path: Path, cfg: "Config",
                            max_dur: float = 6.0) -> Path:
    """Free stock B-roll video matching `query`, downloaded from Pexels.
    Needs a free key (cfg.pexels_api_key; https://www.pexels.com/api/).
    Picks the shortest HD (or best-available) clip that's long enough for
    our beat, downloads it, and ffmpeg-trims it to max_dur for fast loading.
    Raises so the caller can fall back to a photo/AI render."""
    key = (getattr(cfg, "pexels_api_key", "") or "").strip()
    if not key:
        raise RuntimeError("pexels: no api key configured")
    q = (query or "").strip()
    if not q:
        raise RuntimeError("pexels: empty query")
    api = "https://api.pexels.com/videos/search"
    params = {"query": q, "per_page": 12, "orientation": "portrait", "size": "medium"}
    headers = {"Authorization": key, "User-Agent": _PHOTO_UA}
    try:
        r = requests.get(api, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        videos = (r.json() or {}).get("videos") or []
    except Exception as e:
        raise RuntimeError(f"pexels search failed: {str(e)[:160]}") from e
    if not videos:
        raise RuntimeError(f"pexels: no results for {q!r}")

    # Prefer clips that are at least max_dur long, sorted by smallest
    # adequate file (cheapest download). Then pick HD where available.
    candidates = []
    for v in videos:
        dur = float(v.get("duration") or 0)
        if dur < max_dur:
            continue
        files = v.get("video_files") or []
        # Prefer HD (>=720p), portrait-ish, smaller bytes when in doubt.
        for f in files:
            w, h = int(f.get("width") or 0), int(f.get("height") or 0)
            link = f.get("link")
            if not link or h < 720:
                continue
            candidates.append((h, v.get("id"), link))
            break
    if not candidates:
        # Looser fallback: any video, any file with a link.
        for v in videos:
            for f in (v.get("video_files") or []):
                link = f.get("link")
                if link:
                    candidates.append((int(f.get("height") or 0), v.get("id"), link))
                    break
    if not candidates:
        raise RuntimeError(f"pexels: no usable file in results for {q!r}")
    candidates.sort(key=lambda c: (-c[0],))   # prefer larger
    _, vid_id, dl_url = candidates[0]

    raw = out_path.with_suffix(".raw.mp4")
    try:
        with requests.get(dl_url, headers=headers, stream=True, timeout=120) as ir:
            ir.raise_for_status()
            with open(raw, "wb") as fh:
                for chunk in ir.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        fh.write(chunk)
    except Exception as e:
        raise RuntimeError(f"pexels download failed: {str(e)[:160]}") from e
    if not raw.is_file() or raw.stat().st_size < 8192:
        raise RuntimeError("pexels: empty download")

    # Trim to max_dur + strip audio (we have our own voiceover/music) so the
    # compose-time overlay is small and decodes fast. Re-encode lightly so
    # later filters don't have to handle a hostile codec.
    try:
        run([
            "ffmpeg", "-y", "-i", str(raw), "-t", f"{max_dur:.2f}",
            "-an", *_vcodec("fast"),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path),
        ])
    finally:
        try: raw.unlink()
        except Exception: pass
    if not out_path.is_file() or out_path.stat().st_size < 4096:
        raise RuntimeError("pexels: trim produced empty mp4")
    return out_path


def _resolve_higgsfield_cli(hf_path: str = "higgsfield") -> str:
    """Absolute path to the `higgsfield` executable, or "" if not found.
    Cached. Mirrors _resolve_grok_cli (Windows .cmd/.exe needs the full path)."""
    global _HIGGSFIELD_CLI_PATH
    if _HIGGSFIELD_CLI_PATH is not None:
        return _HIGGSFIELD_CLI_PATH
    import shutil
    if hf_path and Path(hf_path).expanduser().is_file():
        _HIGGSFIELD_CLI_PATH = str(Path(hf_path).expanduser())
        return _HIGGSFIELD_CLI_PATH
    found = shutil.which(hf_path) or shutil.which("higgsfield")
    if found:
        _HIGGSFIELD_CLI_PATH = found
        return _HIGGSFIELD_CLI_PATH
    home = Path.home()
    appdata = os.environ.get("APPDATA", str(home / "AppData" / "Roaming"))
    for c in (
        Path(appdata) / "npm" / "higgsfield.cmd",
        Path(appdata) / "npm" / "higgsfield.exe",
        Path(appdata) / "npm" / "higgsfield",
        home / ".local" / "bin" / "higgsfield",
        Path("/usr/local/bin/higgsfield"),
        Path("/opt/homebrew/bin/higgsfield"),
    ):
        try:
            if c.is_file():
                _HIGGSFIELD_CLI_PATH = str(c)
                return _HIGGSFIELD_CLI_PATH
        except Exception:
            continue
    _HIGGSFIELD_CLI_PATH = ""
    return _HIGGSFIELD_CLI_PATH


def _higgsfield_result_url(stdout: str) -> str:
    """Pull the first result_url out of `higgsfield generate create --json`
    output. The CLI prints a JSON array of job objects, each with a
    'result_url' and 'status'. Returns "" if none completed."""
    try:
        data = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return ""
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return ""
    for job in data:
        if not isinstance(job, dict):
            continue
        url = job.get("result_url")
        status = str(job.get("status", "")).lower()
        if url and (status in ("completed", "succeeded", "success", "done") or not status):
            return str(url)
    return ""


def fetch_video_from_higgsfield(query: str, out_path: Path, cfg: "Config", *,
                                timeout: int = 600, on_step=None) -> Path:
    """Generate one AI B-roll video clip via the Higgsfield CLI, tapping the
    user's logged-in subscription (no API key). Writes the result mp4 to
    `out_path`. Raises on ANY failure so the caller falls back to Pexels.

    Model: cfg.higgsfield_video_model (config.json) — set it to the CLI's
    video job_set_type (e.g. from `higgsfield generate list` after a manual
    video job). Job flow: `generate create <model> --prompt "..." --wait
    --json` blocks until done and prints a JSON array with a result_url; we
    download that. Higgsfield video can take 1-3 min/clip, hence the long
    default timeout. Costs subscription credits, so it's opt-in."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass

    resolved = _resolve_higgsfield_cli(getattr(cfg, "higgsfield_cli_path", "") or "higgsfield")
    if not resolved:
        raise RuntimeError(
            "higgsfield CLI not found (installed? `higgsfield auth login` done? "
            "set higgsfield_cli_path in config.json)")
    model = (getattr(cfg, "higgsfield_video_model", "") or "").strip()
    if not model:
        raise RuntimeError(
            "higgsfield_video_model not set in config.json (run a video job once, "
            "then `higgsfield generate list` to see the model name)")
    q = (query or "").strip()
    if not q:
        raise RuntimeError("higgsfield: empty prompt")

    # Aspect ratio param name varies per model; pass it best-effort. If the
    # model rejects an unknown flag the whole call errors and we fall back —
    # so only send the prompt + portrait hint that the examples document.
    wait_min = max(1, int(timeout // 60))
    cmd = [resolved, "generate", "create", model,
           "--prompt", q, "--wait", "--wait-timeout", f"{wait_min}m", "--json"]
    extra = (getattr(cfg, "higgsfield_extra_args", "") or "").strip()
    if extra:
        import shlex
        cmd += shlex.split(extra)

    log(f"      higgsfield: generating video ({model}, up to {wait_min}m)…")
    try:
        proc = subprocess.run(cmd, input="", capture_output=True, text=True,
                              timeout=timeout + 60)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"higgsfield timed out after {timeout}s") from e
    except Exception as e:
        raise RuntimeError(f"higgsfield failed to start: {str(e)[:160]}") from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"higgsfield exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}")

    url = _higgsfield_result_url(proc.stdout or "")
    if not url:
        raise RuntimeError("higgsfield: no completed result_url in output")
    if not url.lower().split("?")[0].endswith((".mp4", ".mov", ".webm")):
        raise RuntimeError(f"higgsfield: result is not a video ({url[-40:]})")

    raw = out_path.with_suffix(".hf_raw.mp4")
    try:
        with requests.get(url, stream=True, timeout=180) as ir:
            ir.raise_for_status()
            with open(raw, "wb") as fh:
                for chunk in ir.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        fh.write(chunk)
    except Exception as e:
        raise RuntimeError(f"higgsfield download failed: {str(e)[:160]}") from e
    if not raw.is_file() or raw.stat().st_size < 8192:
        raise RuntimeError("higgsfield: empty download")

    # Strip audio + re-encode lightly so the compose-time overlay decodes fast
    # (same treatment as Pexels clips).
    try:
        run([
            "ffmpeg", "-y", "-i", str(raw),
            "-an", *_vcodec("fast"),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path),
        ])
    finally:
        try: raw.unlink()
        except Exception: pass
    if not out_path.is_file() or out_path.stat().st_size < 4096:
        raise RuntimeError("higgsfield: transcode produced empty mp4")
    log(f"      higgsfield video → {out_path.name}")
    return out_path


def fetch_image_from_higgsfield(prompt: str, out_path: Path, cfg: "Config", *,
                                faceless_wide: bool = False,
                                timeout: int = 240, on_step=None) -> Path:
    """Generate one IMAGE via the Higgsfield CLI (e.g. nano_banana_2), tapping
    the user's logged-in subscription (no API key). Writes the result to
    `out_path` (PNG). Raises on ANY failure so the caller can fall back.

    Model: cfg.higgsfield_image_model (config.json), default 'nano_banana_2'.
    Flow: `generate create <model> --prompt "..." --wait --json` blocks and
    prints a JSON array with a result_url; we download + crop it (16:9 for
    faceless landscape, else square — matching the rest of the image pipeline)."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass

    resolved = _resolve_higgsfield_cli(getattr(cfg, "higgsfield_cli_path", "") or "higgsfield")
    if not resolved:
        raise RuntimeError(
            "higgsfield CLI not found (installed? `higgsfield auth login` done? "
            "set higgsfield_cli_path in config.json)")
    model = (getattr(cfg, "higgsfield_image_model", "") or "nano_banana_2").strip()
    q = (prompt or "").strip()
    if not q:
        raise RuntimeError("higgsfield: empty prompt")

    wait_min = max(1, int(timeout // 60))
    cmd = [resolved, "generate", "create", model,
           "--prompt", q, "--wait", "--wait-timeout", f"{wait_min}m", "--json"]
    extra = (getattr(cfg, "higgsfield_image_extra_args", "") or "").strip()
    if extra:
        import shlex
        cmd += shlex.split(extra)

    log(f"      higgsfield: generating image ({model})…")
    try:
        proc = subprocess.run(cmd, input="", capture_output=True, text=True,
                              timeout=timeout + 60)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"higgsfield timed out after {timeout}s") from e
    except Exception as e:
        raise RuntimeError(f"higgsfield failed to start: {str(e)[:160]}") from e
    if proc.returncode != 0:
        raise RuntimeError(
            f"higgsfield exited {proc.returncode}: {(proc.stderr or '').strip()[:200]}")

    url = _higgsfield_result_url(proc.stdout or "")
    if not url:
        raise RuntimeError("higgsfield: no completed result_url in output")
    if not url.lower().split("?")[0].endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise RuntimeError(f"higgsfield: result is not an image ({url[-40:]})")

    try:
        ir = requests.get(url, timeout=120)
        ir.raise_for_status()
        data = ir.content
    except Exception as e:
        raise RuntimeError(f"higgsfield image download failed: {str(e)[:160]}") from e

    # Crop to the shape the rest of the pipeline expects: 16:9 for faceless
    # landscape (fills the frame), otherwise square (matches the photo cards).
    saved = (_save_aspect_image(data, out_path) if faceless_wide
             else _save_square_image(data, out_path))
    if not saved:
        raise RuntimeError("higgsfield image could not be decoded/saved")
    log(f"      higgsfield image → {out_path.name}")
    return out_path


def fetch_image_from_openverse(query: str, out_path: Path,
                               max_results: int = 8) -> Path:
    """Fetch a free, openly-licensed real photo matching `query` from the
    Openverse API (openverse.org). No API key required. Used for beats that
    a real photo fits better than an AI render (e.g. a shocked face, money,
    a trophy) — the "free images that match the topic" the reference shorts
    mix in alongside AI renders.

    Downloads the first result that actually decodes as an image, normalizes
    it to an RGBA PNG (max 1024px) so the compose overlay treats it like any
    other image. Raises on failure so the caller can fall back to AI."""
    q = (query or "").strip()
    if not q:
        raise RuntimeError("openverse: empty query")
    api = "https://api.openverse.org/v1/images/"
    params = {
        "q": q,
        "license_type": "all",
        "mature": "false",
        "page_size": max_results,
        # Prefer larger images; aspect handled on our side via crop.
        "size": "large",
    }
    headers = {"User-Agent": _PHOTO_UA}
    try:
        r = requests.get(api, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        results = (r.json() or {}).get("results") or []
    except Exception as e:
        raise RuntimeError(f"openverse search failed: {str(e)[:160]}") from e
    if not results:
        raise RuntimeError(f"openverse: no results for {q!r}")

    last_err = None
    for res in results:
        img_url = res.get("url") or res.get("thumbnail")
        if not img_url:
            continue
        try:
            ir = requests.get(img_url, headers=headers, timeout=30)
            ir.raise_for_status()
            if _save_square_image(ir.content, out_path):
                return out_path
        except Exception as e:
            last_err = str(e)[:160]
            continue
    raise RuntimeError(f"openverse: no usable image for {q!r} ({last_err})")


def fetch_image_from_wikimedia(query: str, out_path: Path,
                               max_results: int = 10) -> Path:
    """Fallback free-image source: Wikimedia Commons (no API key). Less
    meme-y than Openverse but huge and very reliable. Same normalize +
    center-crop as the Openverse fetcher."""
    q = (query or "").strip()
    if not q:
        raise RuntimeError("wikimedia: empty query")
    api = "https://commons.wikimedia.org/w/api.php"
    params = {
        "action": "query", "format": "json",
        "generator": "search", "gsrsearch": f"{q} filetype:bitmap",
        "gsrnamespace": "6", "gsrlimit": str(max_results),
        "prop": "imageinfo", "iiprop": "url", "iiurlwidth": "1024",
    }
    headers = {"User-Agent": _PHOTO_UA}
    try:
        r = requests.get(api, params=params, headers=headers, timeout=30)
        r.raise_for_status()
        pages = ((r.json() or {}).get("query") or {}).get("pages") or {}
    except Exception as e:
        raise RuntimeError(f"wikimedia search failed: {str(e)[:160]}") from e
    if not pages:
        raise RuntimeError(f"wikimedia: no results for {q!r}")

    last_err = None
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        img_url = info.get("thumburl") or info.get("url")
        if not img_url:
            continue
        try:
            ir = requests.get(img_url, headers=headers, timeout=30)
            ir.raise_for_status()
            if _save_square_image(ir.content, out_path):
                return out_path
        except Exception as e:
            last_err = str(e)[:160]
            continue
    raise RuntimeError(f"wikimedia: no usable image for {q!r} ({last_err})")


# Circuit breaker: once a source clearly says "rate limited / quota exceeded"
# in this process, skip it for the rest of the run so subsequent beats don't
# waste a slow failing call. Reset on process exit (the set lives in-memory).
_DISABLED_PHOTO_SOURCES: set[str] = set()


def _is_quota_error(err_msg: str) -> bool:
    """True if an error string indicates the source is rate-limited / out of
    quota — at which point retrying within the same run is pointless."""
    s = (err_msg or "").lower()
    return any(t in s for t in (
        "429", "rate limit", "ratelimit", "rate-limit",
        "quota", "too many requests", "limit exceeded", "403",
    ))


def fetch_free_photo(query: str, out_path: Path, cfg: "Config" = None,
                     on_step=None) -> Path:
    """Try the free photo sources in order: Pexels (if key — best quality)
    → Pixabay (if key) → Openverse → Wikimedia Commons.

    Process-wide circuit breaker: a source that fails with a clear rate-limit
    / quota error is SKIPPED for the rest of the run, so the next beat
    doesn't burn time on the same failing call (and you don't waste a slow
    upstream timeout per image). Other failures (no result, network blip,
    bad query) are local to this beat and don't disable the source.
    Logs each source's real error instead of a silent "miss". Raises only
    when all sources fail, so the caller can fall back to an AI render."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass

    def _try(name: str, fn) -> Path | None:
        if name in _DISABLED_PHOTO_SOURCES:
            return None  # already known dead for this run
        try:
            return fn()
        except Exception as e:
            err = f"{name}: {str(e)[:140]}"
            log(f"        {err}")
            if _is_quota_error(str(e)):
                _DISABLED_PHOTO_SOURCES.add(name)
                log(f"        → {name} skip für Rest des Runs (Rate-Limit/Quota)")
            raise

    has_pexels = cfg is not None and (getattr(cfg, "pexels_api_key", "") or "").strip()
    has_pixabay = cfg is not None and (getattr(cfg, "pixabay_api_key", "") or "").strip()
    chain: list[tuple[str, callable]] = []
    if has_pexels:
        chain.append(("pexels", lambda: fetch_image_from_pexels(query, out_path, cfg)))
    if has_pixabay:
        chain.append(("pixabay", lambda: fetch_image_from_pixabay(query, out_path, cfg)))
    chain.append(("openverse", lambda: fetch_image_from_openverse(query, out_path)))
    chain.append(("wikimedia", lambda: fetch_image_from_wikimedia(query, out_path)))

    errors = []
    for name, fn in chain:
        try:
            result = _try(name, fn)
            if result is not None:
                return result
        except Exception as e:
            errors.append(f"{name}: {str(e)[:140]}")
    raise RuntimeError("; ".join(errors) or "all photo sources unavailable")


def _image_schedule(n: int, duration: float, image_dur: float,
                    buffer: float = 1.0,
                    continuous: bool = False,
                    gap: float = 0.5) -> list[tuple[float, float]]:
    """Return [(start, end), ...] for n images.

    continuous=False: n images of image_dur evenly spread with gaps (the
    classic pop-in-then-gone look).
    continuous=True: one image per beat. Each image STARTS on its beat
    (i*slice, so it lines up with the narration) and ENDS `gap` seconds
    before the next one — leaving `gap`s of gameplay-only between images.
    """
    if n <= 0:
        return []
    if continuous:
        slice_dur = duration / n
        g = max(0.0, gap)
        out = []
        for i in range(n):
            start = i * slice_dur
            end = (i + 1) * slice_dur - g
            # If the slice is too short to leave a gap and still show the
            # image for a reasonable beat, keep it visible (drop the gap).
            if end - start < 0.8:
                end = (i + 1) * slice_dur
            out.append((start, end))
        return out
    usable = max(image_dur, duration - 2 * buffer)
    if n == 1:
        start = (duration - image_dur) / 2
        return [(start, start + image_dur)]
    step_gap = (usable - image_dur) / (n - 1) if n > 1 else 0
    out = []
    for i in range(n):
        start = buffer + i * step_gap
        out.append((start, start + image_dur))
    return out


def _ts_filename(seconds: float, ext: str) -> str:
    """Format a start time as a MM_SS filename stem (Danny-Why style), e.g.
    7.0 -> '00_07', 75.4 -> '01_15'. Clamps negatives to 0."""
    s = max(0, int(round(seconds)))
    return f"{s // 60:02d}_{s % 60:02d}{ext}"


def export_timestamped_images(image_paths: list, schedule: list,
                              out_dir: Path, on_step=None) -> Path:
    """Copy each generated image/clip into out_dir named after its on-screen
    START time (00_07.png, 00_15.png, ...) — the Danny-Why CapCut workflow:
    drag each onto the timeline at its timestamp. Runs ALONGSIDE the normal
    video render, never instead of it. Returns out_dir.

    On a timestamp collision (two beats round to the same second) a -2/-3
    suffix is added so nothing is silently overwritten."""
    import shutil
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass

    out_dir.mkdir(parents=True, exist_ok=True)
    used: dict[str, int] = {}
    written = 0
    for img, (start, _end) in zip(image_paths, schedule):
        src = Path(img)
        if not src.is_file():
            continue
        ext = src.suffix.lower() or ".png"
        name = _ts_filename(start, ext)
        if name in used:
            used[name] += 1
            name = f"{name[:-len(ext)]}-{used[name]}{ext}"
        else:
            used[name] = 1
        try:
            shutil.copy2(src, out_dir / name)
            written += 1
        except OSError as e:
            log(f"      timestamp-export: konnte {src.name} nicht kopieren ({str(e)[:80]})")
    log(f"      Zeitstempel-Bilder exportiert: {written} → {out_dir}")
    return out_dir


_TILT_ANGLES_DEG = [-3.0, 2.5, -2.0, 3.0, -2.5]


def _video_chain(idx_input: int, image_idx: int, image_dur: float, start: float,
                 overlay_w: int) -> str:
    """Filter chain for one B-roll video clip overlay: trim, white border,
    short fade-in/out. No rotate/pop (those would look weird on real footage).
    The clip plays at native speed; if shorter than image_dur, it just ends."""
    fade_in, fade_out = 0.15, 0.25
    fade_out_start = max(0.0, image_dur - fade_out)
    return (
        f"[{idx_input}:v]"
        f"trim=duration={image_dur:.2f},setpts=PTS-STARTPTS,"
        # Center-crop to a square, then scale to overlay_w x overlay_w so a
        # B-roll clip occupies the SAME footprint as a photo card (photos are
        # squared by _save_square_image). Without this, a portrait 9:16 Pexels
        # clip scaled to overlay_w width would be ~1.78x as tall and cover the
        # whole gameplay.
        f"crop=w='min(iw\\,ih)':h='min(iw\\,ih)',"
        f"scale=w={overlay_w}:h={overlay_w}:flags=bicubic,"
        f"format=yuva420p,pad=iw+18:ih+18:9:9:color=white@0.95,"
        f"fade=t=in:st=0:d={fade_in}:alpha=1,"
        f"fade=t=out:st={fade_out_start:.2f}:d={fade_out}:alpha=1,"
        f"tpad=start_duration={start:.2f}:color=black@0"
        f"[img{image_idx}]"
    )


def _image_chain(idx_input: int, image_idx: int, image_dur: float, start: float,
                 overlay_w: int, angle_deg: float, ken_burns: bool = False) -> str:
    """Filter chain for one image overlay: white border, tilt, pop-in scale, fades.
    ken_burns: after the pop, the image keeps zooming slowly (~6%) for the
    whole time it's shown, so the middle never feels static."""
    fade_in, fade_out, pop_dur = 0.2, 0.3, 0.25
    angle_rad = angle_deg * 3.14159265 / 180.0
    pop_start_w = int(overlay_w * 1.18)
    pop_delta = pop_start_w - overlay_w
    fade_out_start = max(0.0, image_dur - fade_out)
    # Post-pop width: fixed, or a slow Ken-Burns drift up to +6%.
    if ken_burns and image_dur > 0.1:
        settled_w = f"{overlay_w}*(1+0.06*(t/{image_dur:.2f}))"
    else:
        settled_w = f"{overlay_w}"
    return (
        f"[{idx_input}:v]"
        f"trim=duration={image_dur:.2f},setpts=PTS-STARTPTS,"
        f"format=rgba,"
        f"pad=iw+18:ih+18:9:9:color=white@0.95,"
        f"rotate={angle_rad:.4f}:c=black@0:ow=hypot(iw\\,ih):oh=ow,"
        f"scale=w='if(lt(t\\,{pop_dur:.2f})\\,{pop_start_w}-{pop_delta}*(t/{pop_dur:.2f})\\,{settled_w})'"
        f":h=-1:eval=frame:flags=bicubic,"
        f"fade=t=in:st=0:d={fade_in}:alpha=1,"
        f"fade=t=out:st={fade_out_start:.2f}:d={fade_out}:alpha=1,"
        f"tpad=start_duration={start:.2f}:color=black@0"
        f"[img{image_idx}]"
    )


def _fullframe_chain(idx_input: int, image_idx: int, image_dur: float, start: float,
                     target_w: int, target_h: int, is_video: bool = False) -> str:
    """Full-frame image/clip chain for faceless videos: cover the ENTIRE frame
    (no white border, no tilt, no pop-in), just a clean fade in/out. Eliminates
    the side bars that a centered square overlay produced on a 16:9 frame."""
    fade_in, fade_out = 0.25, 0.35
    fade_out_start = max(0.0, image_dur - fade_out)
    src = (f"[{idx_input}:v]trim=duration={image_dur:.2f},setpts=PTS-STARTPTS,"
           if is_video else f"[{idx_input}:v]")
    return (
        f"{src}"
        f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=bicubic,"
        f"crop={target_w}:{target_h},setsar=1,format=rgba,"
        f"fade=t=in:st=0:d={fade_in}:alpha=1,"
        f"fade=t=out:st={fade_out_start:.2f}:d={fade_out}:alpha=1,"
        f"tpad=start_duration={start:.2f}:color=black@0"
        f"[img{image_idx}]"
    )


def apply_playback_speed(video_path: Path, speed: float) -> None:
    """Re-time `video_path` in place: video and audio both sped up by
    `speed` (1.0 = no-op, 1.1 = 10% faster, 0.9 = 10% slower).

    Picture: setpts=PTS/speed compresses the presentation timestamps.
    Audio: atempo=speed pitches-preserved tempo shift (single atempo
    instance covers 0.5..2.0; we cap to that range so we never need
    to chain filters).
    """
    speed = max(0.5, min(2.0, float(speed)))
    if abs(speed - 1.0) < 0.01:
        return
    tmp = video_path.with_suffix(".speed.mp4")
    run([
        "ffmpeg", "-y", "-i", str(video_path),
        "-filter_complex",
        f"[0:v]setpts=PTS/{speed}[v];[0:a]atempo={speed}[a]",
        "-map", "[v]", "-map", "[a]",
        *_vcodec("standard"),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(tmp),
    ])
    tmp.replace(video_path)


def apply_auto_editor(video_path: Path, margin: float = 0.18,
                      threshold: float = 0.04, on_step=None) -> bool:
    """Cut silent/dead-air stretches out of the FINISHED video in place using
    the `auto-editor` package (https://github.com/WyattBlue/auto-editor).

    Runs on the fully composed mp4 (picture + voice + burned-in captions all
    cut together), so audio/caption sync can never drift. `margin` keeps a
    short pad of silence around each kept chunk so speech doesn't get clipped
    or feel machine-gun-tight; `threshold` is the loudness level below which a
    stretch counts as silence (0.04 = 4%).

    Best-effort: if auto-editor isn't installed or errors, the original video
    is left untouched and we return False — a render is never blocked by it.
    """
    def log(msg: str) -> None:
        if on_step:
            try:
                on_step(msg)
            except Exception:
                pass
        else:
            print(msg)

    margin = max(0.0, float(margin))
    threshold = max(0.0, min(1.0, float(threshold)))
    tmp = video_path.with_suffix(".autoedit.mp4")
    if tmp.exists():
        try:
            tmp.unlink()
        except Exception:
            pass
    cmd = [
        sys.executable, "-m", "auto_editor", str(video_path),
        "--edit", f"audio:threshold={threshold * 100:.0f}%",
        "--margin", f"{margin:.2f}sec",
        # NVENC if available, else x264 — matches the rest of the pipeline.
        "--video-codec", ("h264_nvenc" if _nvenc_available() else "libx264"),
        "--no-open",
        "--output", str(tmp),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        log("      auto-editor: nicht installiert — überspringe "
            "(installieren mit:  .venv\\Scripts\\python.exe -m pip install auto-editor )")
        return False
    except subprocess.TimeoutExpired:
        log("      auto-editor: Timeout (>15min) — behalte ungeschnittenes Video")
        return False
    except Exception as e:
        log(f"      auto-editor: Fehler ({str(e)[:160]}) — behalte ungeschnittenes Video")
        return False

    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < 1024:
        tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-4:])
        low = (proc.stderr or "").lower()
        # `python -m auto_editor` returns exit 1 (not FileNotFoundError) when
        # the package isn't installed — surface the install command instead.
        if "no module named auto_editor" in low:
            log("      auto-editor: nicht installiert — überspringe "
                "(installieren mit:  .venv\\Scripts\\python.exe -m pip install auto-editor )")
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            return False
        # auto-editor exits non-zero when it would output an EMPTY file (i.e.
        # the whole clip is "silent" by the threshold) — keep the original.
        if "resulted in an empty" in low or "empty" in tail.lower():
            log("      auto-editor: alles unter der Stille-Schwelle — behalte "
                "Original (Schwelle evtl. zu hoch / Musik zu leise)")
        else:
            log(f"      auto-editor fehlgeschlagen (exit {proc.returncode}): {tail[:200]} "
                "— behalte ungeschnittenes Video")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False

    old_dur = _media_duration(video_path)
    new_dur = _media_duration(tmp)
    tmp.replace(video_path)
    if old_dur > 0 and new_dur > 0:
        saved = old_dur - new_dur
        log(f"      auto-editor: Stille rausgeschnitten — {old_dur:.1f}s → "
            f"{new_dur:.1f}s ({saved:+.1f}s)")
    else:
        log("      auto-editor: Stille rausgeschnitten")
    return True


def apply_voice_tempo(voice_path: Path, tempo: float) -> Path:
    """Slow down / speed up just the VOICEOVER audio in place, pitch-preserved.
    tempo < 1.0 = slower (calmer, good for long-form), > 1.0 = faster.
    1.0 = no-op. atempo handles 0.5..2.0 in one pass. Done BEFORE the script
    length is measured, so the long-form auto-extend still targets real time."""
    tempo = max(0.5, min(2.0, float(tempo)))
    if abs(tempo - 1.0) < 0.01:
        return voice_path
    tmp = voice_path.with_suffix(".tempo.mp3")
    run([
        "ffmpeg", "-y", "-i", str(voice_path),
        "-filter:a", f"atempo={tempo:.3f}",
        "-c:a", "libmp3lame", "-q:a", "2",
        str(tmp),
    ])
    tmp.replace(voice_path)
    return voice_path


def _effects_final_vf(effects: dict | None, target_w: int, target_h: int) -> str:
    """Build a comma-chain of ffmpeg video filters for the global/timed
    effects, to append to the final composed frame. Returns "" if nothing is
    enabled. Order: geometry (shake/punch/creep) → color grade → pixel/overlay
    (glitch → flashes/pulses on top)."""
    if not effects:
        return ""
    chain: list[str] = []

    # Camera shake: brief positional jitter inside the LLM-chosen windows.
    shakes = effects.get("shakes") or []
    if shakes:
        win = "+".join(f"between(t\\,{s:.2f}\\,{e:.2f})" for s, e in shakes)
        amp = 14
        chain.append(
            f"crop=w=in_w-{amp*3}:h=in_h-{amp*3}:"
            f"x='{amp}+if(gt({win}\\,0)\\,{amp}*sin(t*90)\\,0)':"
            f"y='{amp}+if(gt({win}\\,0)\\,{amp}*cos(t*78)\\,0)',"
            f"scale={target_w}:{target_h}"
        )

    # Punch-in: quick centered zoom (~12%) at the LLM-chosen moments.
    punches = effects.get("punches") or []
    if punches:
        win = "+".join(f"between(t\\,{ts:.2f}\\,{ts + 0.25:.2f})" for ts in punches)
        z = f"(1+0.12*gt({win}\\,0))"
        chain.append(
            f"crop=w='iw/{z}':h='ih/{z}':x='(iw-ow)/2':y='(ih-oh)/2',"
            f"scale={target_w}:{target_h}"
        )

    # Creep-zoom (horror): a SLOW centered zoom that ramps up across each
    # window, building dread — distinct from punch's instant pop. Default
    # window ~2.5s, ramps 1.0 → ~1.15.
    creeps = effects.get("creeps") or []
    if creeps:
        terms = []
        for s, e in creeps:
            dur = max(0.2, e - s)
            terms.append(
                f"if(between(t\\,{s:.2f}\\,{e:.2f})\\,0.15*((t-{s:.2f})/{dur:.2f})\\,0)")
        z = f"(1+{'+'.join(terms)})"
        chain.append(
            f"crop=w='iw/{z}':h='ih/{z}':x='(iw-ow)/2':y='(ih-oh)/2',"
            f"scale={target_w}:{target_h}"
        )

    # Viral color grade: punchier contrast/saturation + gentle vignette.
    if effects.get("color_grade"):
        chain.append("eq=contrast=1.08:saturation=1.28:brightness=0.012")
        chain.append("vignette=PI/4.5")

    # Horror grade: cold, desaturated, crushed shadows + heavy vignette.
    # Mutually useful alongside color_grade but typically used instead of it.
    if effects.get("horror_grade"):
        chain.append("eq=contrast=1.14:saturation=0.55:brightness=-0.04:gamma=0.90")
        # colorbalance options are per-channel: rs/gs/bs (shadows), rm/gm/bm
        # (midtones), rh/gh/bh (highlights). Cold look = +blue / -red shadows.
        chain.append("colorbalance=rs=-0.05:bs=0.10:rm=-0.03:bm=0.05")
        chain.append("vignette=PI/3.2")

    # Glitch (horror): brief RGB channel split — "something's wrong"/supernatural.
    glitches = effects.get("glitches") or []
    if glitches:
        win = "+".join(f"between(t\\,{ts:.2f}\\,{ts + 0.18:.2f})" for ts in glitches)
        chain.append(
            f"rgbashift=rh=7:bh=-7:rv=3:bv=-3:enable='gt({win}\\,0)'")

    # Flash: full-frame white blips at the LLM-chosen timestamps.
    flashes = effects.get("flashes") or []
    if flashes:
        win = "+".join(f"between(t\\,{ts:.2f}\\,{ts + 0.10:.2f})" for ts in flashes)
        chain.append(
            f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.85:t=fill:enable='gt({win}\\,0)'"
        )

    # Red flash (horror): blood/jumpscare tint — lighter alpha so the frame
    # shows through red rather than blanking white.
    red_flashes = effects.get("red_flashes") or []
    if red_flashes:
        win = "+".join(f"between(t\\,{ts:.2f}\\,{ts + 0.12:.2f})" for ts in red_flashes)
        chain.append(
            f"drawbox=x=0:y=0:w=iw:h=ih:color=red@0.45:t=fill:enable='gt({win}\\,0)'"
        )

    # Dark pulse (horror): screen briefly darkens — dread / a presence appears.
    dark_pulses = effects.get("dark_pulses") or []
    if dark_pulses:
        win = "+".join(f"between(t\\,{ts:.2f}\\,{ts + 0.5:.2f})" for ts in dark_pulses)
        chain.append(
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.5:t=fill:enable='gt({win}\\,0)'"
        )
    return ",".join(chain)


_EFFECT_PLAN_PROMPT = """Du bist Editor fuer virale Roblox-Videos und entscheidest die "Effekt-Regie".

Skript-Dauer: ca. {duration} Sekunden.
Erlaubte Effekte: {allowed}

Finde {n_min}-{n_max} dramatische Momente im Skript und ordne jedem einen Effekt zu. Bedeutung der Effekte:
- "flash" = kurzer weisser Blitz, fuer Schock/Reveal/"ploetzlich"-Momente
- "shake" = kurzes Wackeln, fuer Impact/Action/"krass"-Momente
- "punch" = schneller Zoom-Stoss, fuer Betonung/Pointe/"DAS musst du sehen"
- "red_flash" = roter Blitz, fuer Horror-Jumpscare/Blut/Gefahr ("er war direkt hinter mir")
- "dark_pulse" = Bild wird kurz dunkel, fuer Bedrohung/"das Licht ging aus"/eine Praesenz erscheint
- "glitch" = kurzer Bild-Glitch (RGB-Versatz), fuer uebernatuerlich/"etwas stimmte nicht"/Realitaet bricht
- "creep" = langsamer, schleichender Zoom, fuer aufbauende Anspannung/"es kam naeher und naeher"

WICHTIG: Setze die Effekte GENAU auf die gemeinte Stelle im Skript. Bei Horror-Geschichten: red_flash/dark_pulse/glitch/creep an die gruseligen Hoehepunkte, nicht zufaellig. Nutze NUR die erlaubten Effekte.

Fuer jeden Moment:
- "position": Wert 0.0..1.0 (Anteil am Video, in Erzaehl-Reihenfolge)
- "type": einer der erlaubten Effekte

Skript:
\"\"\"
{script}
\"\"\"

Antworte NUR mit gueltigem JSON-Array, z.B. [{{"position":0.15,"type":"red_flash"}},{{"position":0.6,"type":"creep"}}]. KEINE Markdown."""


def generate_effect_plan(script: str, duration: float, enabled: list,
                         cfg: "Config", ai_direction: bool = True,
                         on_step=None) -> dict:
    """Decide which effects go where. Global effects (color_grade) are simply
    on/off. Timed effects (flash/shake) are placed by the LLM at dramatic
    beats when ai_direction is on; otherwise a couple are spread evenly.
    Returns {color_grade: bool, flashes: [ts], shakes: [(s,e)]}."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
    enabled = [str(e).lower() for e in (enabled or [])]
    plan = {
        "color_grade": "color_grade" in enabled,
        "horror_grade": "horror_grade" in enabled,
        "ken_burns": "ken_burns" in enabled,
        "slide_in": "slide_in" in enabled,
        "flashes": [], "shakes": [], "punches": [],
        "red_flashes": [], "dark_pulses": [], "glitches": [], "creeps": [],
    }
    # Map each timed effect type → the plan key it appends to and how its
    # window is built from a center timestamp.
    _TIMED = ("flash", "shake", "punch", "red_flash", "dark_pulse", "glitch", "creep")
    allowed_timed = [e for e in _TIMED if e in enabled]
    if not allowed_timed or duration <= 0:
        return plan

    beats = []
    have_llm = bool(getattr(cfg, "use_claude_cli", False) or cfg.gemini_api_key)
    if ai_direction and have_llm and script.strip():
        # More moments allowed for longer videos (horror stories run long).
        n_max = max(6, min(int(duration // 12), 20))
        prompt = _EFFECT_PLAN_PROMPT.format(
            duration=int(duration), allowed=", ".join(allowed_timed),
            n_min=3, n_max=n_max, script=script)
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.6, "maxOutputTokens": 1024,
                                     "thinkingConfig": {"thinkingBudget": 0}}}
        try:
            text = _complete_text(prompt, cfg, prefer_claude=True, gemini_body=body, on_step=on_step)
            raw = text.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```(?:json)?\s*", "", raw); raw = re.sub(r"\s*```\s*$", "", raw)
            s, e = raw.find("["), raw.rfind("]")
            if s != -1 and e != -1:
                raw = raw[s:e + 1]
            for it in json.loads(raw):
                if not isinstance(it, dict):
                    continue
                typ = str(it.get("type", "")).lower()
                pos = float(it.get("position", -1))
                if typ in allowed_timed and 0.0 <= pos <= 1.0:
                    beats.append((typ, pos * duration))
        except Exception as ex:
            log(f"      effect-plan LLM failed ({str(ex)[:90]}) — gleichmäßige Verteilung")
    if not beats:
        # Fallback: spread ~1 emphasis every ~8s using the allowed types.
        n = max(2, min(int(duration // 8), 6))
        for i in range(n):
            ts = (i + 0.5) * duration / n
            beats.append((allowed_timed[i % len(allowed_timed)], ts))

    for typ, ts in beats:
        ts = round(ts, 2)
        if typ == "flash":
            plan["flashes"].append(ts)
        elif typ == "shake":
            plan["shakes"].append((ts, round(ts + 0.4, 2)))
        elif typ == "punch":
            plan["punches"].append(ts)
        elif typ == "red_flash":
            plan["red_flashes"].append(ts)
        elif typ == "dark_pulse":
            plan["dark_pulses"].append(ts)
        elif typ == "glitch":
            plan["glitches"].append(ts)
        elif typ == "creep":
            plan["creeps"].append((ts, round(ts + 2.5, 2)))
    extras = [k for k in ("color_grade", "horror_grade", "ken_burns", "slide_in") if plan[k]]
    log(f"      effekt-regie: {len(plan['flashes'])} flash, {len(plan['shakes'])} shake, "
        f"{len(plan['punches'])} punch, {len(plan['red_flashes'])} red-flash, "
        f"{len(plan['dark_pulses'])} dark-pulse, {len(plan['glitches'])} glitch, "
        f"{len(plan['creeps'])} creep"
        f"{(' + ' + ', '.join(extras)) if extras else ''}")
    return plan


def compose_short(gameplay_clip: Path, voice_audio: Path, ass_path: Path,
                  cfg: Config, out_path: Path,
                  image_paths: list | None = None,
                  duration: float = 0.0,
                  image_duration: float = 1.5,
                  mute_source_audio: bool = False,
                  progress_bar: bool = False,
                  progress_color: str = "red",
                  progress_duration: float = 0.0,
                  crop_offset: float = 0.5,
                  image_tilt: bool = True,
                  images_continuous: bool = False,
                  image_gap: float = 0.5,
                  image_size: float = 0.92,
                  image_vpos: float = -0.03,
                  emoji_events: list | None = None,
                  caption_position: str = "bottom",
                  effects: dict | None = None,
                  faceless: bool = False) -> Path:
    image_paths = list(image_paths or [])
    emoji_events = list(emoji_events or [])
    if mute_source_audio:
        # ignore gameplay audio; output is just the voice/music track
        af = "[1:a]anull[a]"
    else:
        af = (
            f"[0:a]volume={cfg.ducking_db}dB[bg];"
            f"[bg][1:a]amix=inputs=2:duration=shortest:dropout_transition=0[a]"
        )
    cwd = ass_path.parent

    # Build the source→target visual chain. Two output orientations:
    #
    #   Portrait (target_h > target_w, i.e. 9:16 short): take a vertical
    #     strip out of the source via `crop=ih*9/16:ih:x=...:y=0`. The
    #     horizontal position is driven by `crop_offset` (auto-reframe).
    #
    #   Landscape (target_w >= target_h, i.e. 16:9 long video): source
    #     is almost always 16:9 already, so we just scale-cover-crop to
    #     target_w × target_h. `crop_offset` is ignored — there is no
    #     "where to crop horizontally" decision when input and output
    #     aspect match.
    is_portrait = cfg.target_h > cfg.target_w
    if is_portrait:
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
            crop_x = f"(iw-ih*9/16)*{offsets[-1][1]:.3f}"
            for i in range(len(offsets) - 2, -1, -1):
                next_t = offsets[i + 1][0]
                this_off = offsets[i][1]
                crop_x = (
                    f"if(lt(t\\,{next_t:.2f})\\,"
                    f"(iw-ih*9/16)*{this_off:.3f}\\,{crop_x})"
                )
        cover_chain = (
            f"crop=ih*9/16:ih:x='{crop_x}':y=0,"
            f"scale={cfg.target_w}:{cfg.target_h}:flags=lanczos,setsar=1"
        )
    else:
        # Landscape: scale-up enough to cover, then crop to exact target.
        # `force_original_aspect_ratio=increase` keeps the smaller dimension
        # >= target, so the subsequent crop never sees black bars.
        cover_chain = (
            f"scale={cfg.target_w}:{cfg.target_h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={cfg.target_w}:{cfg.target_h},setsar=1"
        )

    use_bar = bool(progress_bar and progress_duration > 0.5)
    bar_h = max(8, int(cfg.target_h * 0.008)) if use_bar else 0

    cmd = ["ffmpeg", "-y", "-i", str(gameplay_clip), "-i", str(voice_audio)]

    # Image inputs follow the gameplay(0)+voice(1); emoji PNGs follow those.
    # Media inputs: images get -loop 1 (still frame held for the chain's
    # trim duration); video clips (.mp4) get NO -loop because they already
    # have their own frames.
    for media in image_paths:
        if Path(str(media)).suffix.lower() == ".mp4":
            cmd += ["-i", str(media)]
        else:
            cmd += ["-loop", "1", "-i", str(media)]
    emoji_base_idx = 2 + len(image_paths)
    for ev in emoji_events:
        cmd += ["-loop", "1", "-i", str(ev[2])]  # ev = (start, end, png[, y])

    # ── background + centered image overlays → captioned base ──
    parts: list[str] = []
    if image_paths:
        # image_size = image width as a fraction of frame width.
        overlay_w = int(cfg.target_w * max(0.4, min(1.0, image_size)))
        # image_vpos = vertical offset from frame center as a fraction of
        # height (negative = up, 0 = dead center, positive = down).
        v_off = int(image_vpos * cfg.target_h)
        v_expr = f"(H-h)/2{v_off:+d}"
        schedule = _image_schedule(
            len(image_paths), duration or 25.0, image_duration,
            continuous=images_continuous, gap=image_gap,
        )
        eff = effects or {}
        ken_burns = bool(eff.get("ken_burns"))
        slide_in = bool(eff.get("slide_in"))
        parts.append(f"[{'0:v'}]{cover_chain}[bg0]")
        cur = "bg0"
        for i, (img_path, (start, end)) in enumerate(zip(image_paths, schedule)):
            is_video = Path(str(img_path)).suffix.lower() == ".mp4"
            if faceless:
                # Faceless: each image fills the WHOLE frame (no card, no border,
                # no tilt) and is overlaid at 0,0 — no side bars.
                parts.append(_fullframe_chain(
                    idx_input=2 + i, image_idx=i,
                    image_dur=end - start, start=start,
                    target_w=cfg.target_w, target_h=cfg.target_h, is_video=is_video,
                ))
                x_expr, this_v = "0", "0"
            elif is_video:
                parts.append(_video_chain(
                    idx_input=2 + i, image_idx=i,
                    image_dur=end - start, start=start, overlay_w=overlay_w,
                ))
                x_expr, this_v = "(W-w)/2", v_expr
            else:
                angle = _TILT_ANGLES_DEG[i % len(_TILT_ANGLES_DEG)] if image_tilt else 0.0
                parts.append(_image_chain(
                    idx_input=2 + i, image_idx=i,
                    image_dur=end - start, start=start,
                    overlay_w=overlay_w, angle_deg=angle, ken_burns=ken_burns,
                ))
                this_v = v_expr
                if slide_in:
                    x_expr = (f"'if(lt(t-{start:.2f}\\,0.3)\\,"
                              f"-w+(W/2+w/2)*((t-{start:.2f})/0.3)\\,(W-w)/2)'")
                else:
                    x_expr = "(W-w)/2"
            nxt = f"bg{i+1}"
            parts.append(
                f"[{cur}][img{i}]overlay={x_expr}:{this_v}:format=auto:eof_action=pass[{nxt}]"
            )
            cur = nxt
        parts.append(f"[{cur}]subtitles={ass_path.name}[capbase]")
    else:
        parts.append(f"[0:v]{cover_chain},subtitles={ass_path.name}[capbase]")
    vlabel = "capbase"

    # ── color emoji PNG overlays (sit just under the caption text) ──
    if emoji_events:
        emoji_w = max(48, int(cfg.target_w * 0.085))
        pos = (caption_position or "bottom").lower()
        # Fallback y if an event doesn't carry its own (older 3-tuples).
        if pos == "top":
            default_y = int(cfg.target_h * 0.21)
        elif pos == "center":
            default_y = int(cfg.target_h * 0.56)
        else:
            default_y = int(cfg.target_h * 0.80)
        for j, ev in enumerate(emoji_events):
            e_start, e_end = ev[0], ev[1]
            # 4th element = per-caption y computed in run_one (tight under the
            # actual 1- or 2-line caption); else the position-based default.
            emoji_y = int(ev[3]) if len(ev) > 3 else default_y
            in_idx = emoji_base_idx + j
            parts.append(f"[{in_idx}:v]scale={emoji_w}:-1[emo{j}]")
            nxt = f"emv{j}"
            parts.append(
                f"[{vlabel}][emo{j}]overlay=(W-w)/2:{emoji_y}:"
                f"enable='between(t\\,{e_start:.2f}\\,{e_end:.2f})':"
                f"format=auto:eof_action=pass[{nxt}]"
            )
            vlabel = nxt

    # ── progress bar ──
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
            f"[{vlabel}][bar]overlay=x=0:y=H-{bar_h}:eof_action=pass[vbar]"
        )
        vlabel = "vbar"

    # Final global/timed effects (color grade, flash, shake) on the composed
    # frame — toggled + timed by the effect plan. No-op when disabled.
    eff_vf = _effects_final_vf(effects, cfg.target_w, cfg.target_h)
    if eff_vf:
        parts.append(f"[{vlabel}]{eff_vf}[veff]")
        vlabel = "veff"

    parts.append(af)
    filter_complex = ";".join(parts)

    cmd += [
        "-filter_complex", filter_complex,
        "-map", f"[{vlabel}]", "-map", "[a]",
        *_vcodec("standard"), "-pix_fmt", "yuv420p",
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
        finals = _snap_and_dedupe_moments(all_moments, segments, n_clips, target_duration, on_step=log)
        return _regenerate_hooks_per_range(finals, segments, cfg, on_step=log)

    # Short video / few clips: single call as before
    ms = _find_moments_single_call(segments, n_clips, target_duration, cfg)
    finals = _snap_and_dedupe_moments(ms, segments, n_clips, target_duration, on_step=log)
    # 2-pass: regenerate hook/title/hashtags from the EXACT post-snap range text
    # so they can't drift from the actual clip content. Gracefully no-ops on per-
    # moment failures (keeps the original hook from the first pass).
    return _regenerate_hooks_per_range(finals, segments, cfg, on_step=log)


def _regenerate_hooks_per_range(moments: list, segments: list, cfg,
                                 on_step=None) -> list:
    """For each moment, ask Gemini to rewrite the hook/title/hashtags using
    ONLY the transcript inside [start, end]. Eliminates the common failure
    where the original single-pass hook describes something that isn't in
    the actual clip — typical Gemini 2.5 Flash hallucination at high
    n_clips. Falls back silently to the original values if the per-range
    call fails."""
    def log(msg):
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    if not getattr(cfg, "gemini_api_key", ""):
        return moments
    log(f"      regenerating hooks from per-range text (2-pass, {len(moments)} calls)")
    for i, m in enumerate(moments, 1):
        range_text = " ".join(
            t for s, e, t in segments
            if e > m["start"] and s < m["end"]
        ).strip()
        if not range_text:
            continue
        # Cap the snippet — full-minute clips can be huge and we don't need
        # every word for hook generation.
        snippet = range_text[:3500]
        old_hook = m.get("hook", "")
        try:
            new = _gemini_rewrite_hook(snippet, m.get("title", ""), cfg)
        except Exception as e:
            log(f"        clip {i}: hook regen failed ({str(e)[:120]}); keeping original")
            continue
        if new.get("hook"):
            m["hook"] = new["hook"][:80]
        if new.get("title"):
            m["title"] = new["title"][:120]
        if new.get("hashtags"):
            m["hashtags"] = [str(h).lstrip("#").strip()
                             for h in new["hashtags"] if h][:6]
        log(f"        clip {i}: '{old_hook[:40]}' → '{m['hook'][:40]}'")
    return moments


def _gemini_rewrite_hook(range_text: str, prior_title: str, cfg) -> dict:
    """Single Gemini call: 'here's the EXACT clip text, write hook/title/tags
    that describe THIS text specifically'. Returns a dict with hook/title/
    hashtags keys (may be missing if the model omitted them)."""
    prompt = (
        f"Du schreibst Hook + Titel + Hashtags für EINEN konkreten YouTube-Short.\n\n"
        f"=== EXAKTER CLIP-INHALT (das ist alles was im Video gesagt wird) ===\n"
        f"{range_text}\n"
        f"=== ENDE ===\n\n"
        f"Wichtig: Hook und Titel müssen SICH DIREKT AUF DIESEN TEXT BEZIEHEN — "
        f"nicht auf das große Thema des Podcasts, sondern auf das was in DIESEM "
        f"30-60 Sekunden-Clip wirklich gesagt wird. KEINE Halluzination, KEINE "
        f"erfundenen Details, KEINE allgemeinen Aussagen.\n\n"
        f"Liefere als JSON-Objekt (kein Array, kein Codeblock):\n"
        f"{{\n"
        f'  "hook": "<max 60 Zeichen, knackiger Aufmacher der den Clip-Kern '
        f'wiedergibt — z.B. eine zentrale Aussage daraus, eine Frage die der '
        f'Clip beantwortet, oder eine schockierende Stelle daraus>",\n'
        f'  "title": "<60-70 Zeichen YouTube-Titel mit Emoji am Ende>",\n'
        f'  "hashtags": ["<3-5 deutsche Tags ohne #>"]\n'
        f"}}\n\n"
        f"Antworte NUR mit dem JSON-Objekt."
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.6,
            "maxOutputTokens": 400,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{cfg.gemini_model}:generateContent")
    data = _gemini_post(url, {"key": cfg.gemini_api_key}, body, retries=2)
    candidate = data["candidates"][0]
    parts = candidate.get("content", {}).get("parts", []) or []
    text = "\n".join(p.get("text", "") for p in parts
                     if not p.get("thought")).strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:].strip()
    s_idx, e_idx = text.find("{"), text.rfind("}")
    if s_idx == -1 or e_idx <= s_idx:
        raise RuntimeError(f"no JSON object in response: {text[:200]}")
    return json.loads(text[s_idx:e_idx + 1])


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
    region_lo = min(s[0] for s in segments) if segments else 0.0
    if n_clips == 1:
        # Per-region call (transcript chunk): no distribution rule — it would
        # bias the single pick toward a fixed part of the region. Content only.
        rule1 = (
            f"REGEL 1 — AUSWAHL:\n"
            f"- Dieses Transkript deckt den Bereich {int(region_lo)}s bis {int(src_dur)}s ab.\n"
            f"- Finde den EINEN viralsten Moment irgendwo in diesem Bereich — "
            f"Anfang, Mitte oder Ende, rein nach Inhalt entscheiden.\n\n"
        )
    else:
        rule1 = (
            f"REGEL 1 — VERTEILUNG (kritisch!):\n"
            f"- Die {n_clips} Momente müssen ÜBER DAS GANZE VIDEO verteilt sein (0 bis {int(src_dur)}s).\n"
            f"- Picke NICHT alle nur aus dem Anfang. Auch der mittlere und späte Teil hat "
            f"  virale Momente — such sie aktiv.\n"
            f"- Faustregel: ~{max(1, n_clips//3)} Momente aus 0–{int(third):.0f}s, "
            f"~{max(1, n_clips//3)} aus {int(third):.0f}–{int(2*third):.0f}s, "
            f"~{max(1, n_clips - 2*(n_clips//3))} aus {int(2*third):.0f}–{int(src_dur):.0f}s.\n\n"
        )
    prompt = (
        f"Du analysierst ein deutsches Voll-Transkript eines Podcasts/Talks/Streams "
        f"und findest die {n_clips} viralsten Momente für YouTube Shorts.\n\n"
        f"GESAMTDAUER des Videos: {dur_min}:{dur_sec_rem:02d} Minuten ({int(src_dur)}s).\n\n"
        f"Transkript-Format pro Zeile: 'MM:SS.ss-MM:SS.ss  Text'\n\n"
        f"=== TRANSKRIPT ===\n{transcript}\n=== ENDE ===\n\n"
        f"Finde EXAKT {n_clips} Momente. Beachte BEIDE Regeln strikt:\n\n"
        f"{rule1}"
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
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    # Moment-picking is THE task where a stronger model pays off most
    # (Gemini Flash is documented-mediocre here). So when the local Claude
    # CLI is enabled, route this through it first; otherwise use the
    # dedicated Gemini moments model (defaults to gemini_model, can be set
    # to gemini-2.5-pro in config.json for better picks).
    moments_model = getattr(cfg, "gemini_moments_model", "") or cfg.gemini_model
    text = _complete_text(
        prompt, cfg, prefer_claude=True,
        gemini_body=body, gemini_model=moments_model,
    )
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
            if overlap / min(m_dur, p_dur) > 0.50:
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

    set_video_encoder_mode(getattr(cfg, "video_encoder", "auto"))
    resume_enabled = bool(job.get("resume", False))
    log = Logger(step_cb=on_step, level=str(job.get("log_level", "INFO")))

    base_slug = job.get("slug") or "multiclip"
    source_url = (job.get("source_url") or "").strip()
    if not source_url:
        raise RuntimeError("multi-clip mode needs source_url (channel scrape not yet supported)")

    n_clips = max(2, min(int(job.get("multiclip_count", 5)), 15))
    target_dur = float(job.get("target_duration", 30.0))

    work_root = cfg.output_dir / f"{base_slug}__multiclip_work"
    work_root.mkdir(parents=True, exist_ok=True)

    # Multi-clip state lives in the shared work_root (single source of truth
    # for the per-subclip status table). The per-subclip run_one calls each
    # get their own state file inside their own work dir.
    state: StateStore | None = None
    if resume_enabled:
        state = StateStore(work_root, base_slug, "multiclip", job, log=log)
        log.info(f"multiclip resume: {state.progress_summary()}")

    # [MULTI 1/4] Download (cached)
    if state and state.is_done(Step.MULTI_DOWNLOAD):
        raw = Path(state.get_artifact(Step.MULTI_DOWNLOAD, "raw_path"))
        step(f"[MULTI 1/4] resume: source already downloaded ({raw.name})")
    else:
        step(f"[MULTI 1/4] download source: {source_url}")
        raw = download_gameplay(source_url, work_root, cookies=ytdlp_cookie_args(cfg),
                                max_height=int(getattr(cfg, 'download_max_height', 1080)))
        if state:
            state.mark_done(Step.MULTI_DOWNLOAD, {"raw_path": raw})

    # [MULTI 2/4] Full-video transcription (cached to disk; expensive)
    seg_cache = work_root / "full_transcript.json"
    whisper_device = str(job.get("whisper_device", "auto"))
    if state and state.is_done(Step.MULTI_TRANSCRIBE) and seg_cache.is_file():
        try:
            segments = json.loads(seg_cache.read_text(encoding="utf-8"))
            step(f"[MULTI 2/4] resume: transcript cached ({len(segments)} segments)")
        except Exception:
            segments = transcribe_full_video(raw, cfg.whisper_model,
                                              device=whisper_device, on_step=step)
    else:
        step("[MULTI 2/4] full-video transcription (Whisper)")
        segments = transcribe_full_video(raw, cfg.whisper_model,
                                          device=whisper_device, on_step=step)
        _release_gpu_memory()
        try:
            seg_cache.write_text(json.dumps(segments), encoding="utf-8")
        except Exception:
            pass
        if state:
            state.mark_done(Step.MULTI_TRANSCRIBE, {
                "transcript_path": seg_cache,
                "segment_count": len(segments),
            })
    src_dur = segments[-1][1] if segments else 0.0
    step(f"      transcript: {len(segments)} segments, source ≈ {src_dur:.0f}s")

    # Auto-cap n_clips for short sources. A 60s video can't yield 5 distinct
    # viral moments — Gemini will return overlapping picks that even dedupe
    # can't fully separate. Floor the asked count at what the source can
    # plausibly support: roughly one distinct clip per 60s of content.
    capped = min(n_clips, max(1, int(src_dur // 60)))
    if capped < n_clips:
        step(f"      ⚠️  short source ({src_dur:.0f}s) — capping {n_clips} → {capped} clips")
        step(f"      (under ~60s per clip Gemini just returns overlapping picks)")
        n_clips = capped

    # [MULTI 3/4] Moments (cached in state metadata; small, structured)
    if state and state.is_done(Step.MULTI_MOMENTS):
        moments = state.get_meta("moments") or []
        step(f"[MULTI 3/4] resume: {len(moments)} moments cached from previous run")
    else:
        step(f"[MULTI 3/4] ask Gemini for the top {n_clips} viral moments")
        moments = find_best_moments(segments, n_clips, target_dur, cfg, on_step=step)
        if state:
            state.set_meta("moments", moments)
            state.mark_done(Step.MULTI_MOMENTS, {"count": len(moments)})
    step(f"      {len(moments)} moments:")
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

        # Per-subclip resume: if we already rendered this one and the file is
        # still on disk, skip it. The run_one call below also has its own
        # state file, so partial subclip work is recoverable too.
        if state:
            status = get_subclip_status(state, i)
            subs = state.get_meta("subclips", {}) or {}
            existing = subs.get(str(i), {}) or {}
            existing_path = Path(str(existing.get("out_path", "")))
            if status == "done" and existing_path.is_file():
                step(f"  ── Clip {i}/{len(moments)}: cached ({existing_path.name})")
                outputs.append(existing_path)
                continue

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
        # Propagate the parent's resume + v2 + YT-meta flags so each subclip
        # gets its own checkpointed run_one.
        sub_job["resume"] = resume_enabled
        try:
            out_mp4 = run_one(sub_job, cfg, on_step=step)
        except Exception as e:
            step(f"  ── Clip {i} FAILED: {e}")
            if state:
                set_subclip_failed(state, i, str(e))
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
        if state:
            set_subclip_done(state, i, out_mp4, title=m.get("title", ""))
        # Each sub-clip loads Whisper + YOLO + maybe FaceMesh; flush VRAM
        # between clips so accumulated CUDA state can't OOM the machine
        # halfway through a 5-clip render.
        _release_gpu_memory()

    if state and len(outputs) == len(moments):
        state.mark_done(Step.MULTI_RENDER, {"clip_count": len(outputs)})

    step(f"[MULTI DONE] {len(outputs)}/{len(moments)} clips rendered")
    return outputs


def _flow_motion_prompt(beat: dict, aspect: str) -> str:
    """Turn a scene-plan beat into a Google-Flow image-to-video prompt: keep the
    beat's motif and add a gentle, consistent camera-motion directive (Flow/Veo
    animate the supplied start image)."""
    motif = (beat.get("motif") or beat.get("prompt") or "").strip()
    motif = re.sub(r"\s+", " ", motif)[:300]
    return (f"{motif}. Cinematic image-to-video: slow camera push-in, subtle "
            f"parallax and ambient motion, consistent lighting and style, "
            f"{aspect} aspect, high detail. No text, no captions.")


def write_flow_export(export_dir: Path, slug: str, image_paths: list,
                      plan: list, voice: Path, voice_dur: float,
                      job: dict, cfg: "Config", on_step=None) -> Path:
    """Package a Google-Flow job: the per-beat START images + an image-to-video
    prompt list + the voiceover + a manifest, into `export_dir`. You feed the
    images/prompts into a Flow automation extension (Veo image-to-video),
    bulk-download the clips, then run `flow_clips.py assemble`.

    Returns export_dir. No ffmpeg/render — just copies + JSON, so it's cheap and
    runs right after the pipeline has generated the start images."""
    import shutil
    def log(m):
        (on_step or print)(m)

    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    voice_name = ""
    if voice and Path(voice).is_file():
        try:
            shutil.copyfile(voice, export_dir / "voice.mp3")
            voice_name = "voice.mp3"
        except Exception as e:
            log(f"      WARN: konnte voice nicht kopieren: {e}")

    is_wide = cfg.target_w >= cfg.target_h
    aspect = "16:9" if is_wide else "9:16"
    continuous = bool(job.get("images_continuous", False))
    change = max(1.0, float(job.get("image_change_secs", 3.5)))
    img_dur = float(job.get("image_duration", 1.5))
    gap = float(job.get("image_gap_secs", 0.5))
    sched = _image_schedule(len(image_paths), voice_dur or 25.0,
                            change if continuous else img_dur,
                            continuous=continuous, gap=gap)

    beats, prompts = [], []
    for i, img in enumerate(image_paths):
        beat = plan[i] if i < len(plan) else {}
        name = f"beat_{i + 1:02d}.png"
        try:
            shutil.copyfile(img, export_dir / name)
        except Exception:
            name = Path(img).name
        start, end = sched[i] if i < len(sched) else (0.0, 0.0)
        prompt = _flow_motion_prompt(beat, aspect)
        prompts.append(prompt)
        beats.append({"index": i + 1, "image": name,
                      "start": round(float(start), 2), "end": round(float(end), 2),
                      "dur": round(float(end) - float(start), 2),
                      "prompt": prompt, "motif": beat.get("motif", "")})

    (export_dir / "prompts.txt").write_text("\n".join(prompts), encoding="utf-8")
    # Snapshot the job so `assemble` rebuilds the exact same render (minus the
    # image generation — clips replace the start images).
    job_snapshot = {k: v for k, v in job.items()
                    if k not in ("flow_export_dir", "image_paths", "image_prompts",
                                 "image_path", "voice_path")}
    manifest = {
        "slug": slug, "voice": voice_name, "voice_duration": round(voice_dur, 2),
        "aspect": aspect, "target_w": cfg.target_w, "target_h": cfg.target_h,
        "config_path": str(job.get("_flow_config_path", "config.json")),
        "tts_language": getattr(cfg, "tts_language", "auto"),
        "image_style": getattr(cfg, "image_style", "auto"),
        "image_change_secs": change, "n_beats": len(beats), "beats": beats,
        "job": job_snapshot,
    }
    (export_dir / "beats.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    (export_dir / "README.txt").write_text(
        "Google-Flow Export\n"
        "==================\n\n"
        f"{len(beats)} Beats. Pro Beat: ein Start-Bild (beat_XX.png) + eine\n"
        "Image-to-Video-Prompt-Zeile (prompts.txt, gleiche Reihenfolge).\n\n"
        "1) Lade die beat_XX.png + prompts.txt in deine Flow-Automation-Extension\n"
        "   (Image-to-Video / Veo). Generiere die Clips.\n"
        "2) Lade die fertigen Clips in EINEN Ordner herunter (Reihenfolge = Beat-\n"
        "   Reihenfolge; alphabetische/natuerliche Sortierung wird gematcht).\n"
        "3) Bau das fertige Video:\n"
        "   python flow_clips.py assemble \"<dieser Ordner>\" \"<clips-Ordner>\"\n\n"
        "Die Stimme (voice.mp3) + Timing kommen aus diesem Export — die Clips\n"
        "werden auf die Voiceover-Laenge verteilt, Captions/Effekte ergaenzt.\n",
        encoding="utf-8")
    log(f"      Flow-Export: {len(beats)} Beats → {export_dir}")
    return export_dir


def run_one(job: dict, cfg: Config, on_step=None) -> Path:
    def step(msg: str) -> None:
        if on_step:
            try:
                on_step(msg)
            except Exception:
                pass
        print(msg)

    # Pick GPU vs CPU video encoder for this run (NVENC = 5-10x faster).
    set_video_encoder_mode(getattr(cfg, "video_encoder", "auto"))

    # Opt-in upgrades. When all flags are off, behavior is identical to the
    # legacy pipeline.
    resume_enabled    = bool(job.get("resume", False))
    use_reframe_v2    = bool(job.get("reframe_v2", False))
    yt_meta_enabled   = bool(job.get("youtube_metadata", False))
    log = Logger(step_cb=on_step, level=str(job.get("log_level", "INFO")))

    base_slug = job["slug"]
    source_url = (job.get("source_url") or "").strip()

    if bool(job.get("faceless_mode", False)):
        # No gameplay source at all — images sit on a generated background.
        slug = base_slug
    elif not source_url:
        channel_url = (job.get("channel_url") or "").strip()
        if not channel_url:
            raise RuntimeError(f"job {base_slug!r} needs either 'source_url' or 'channel_url'")
        used_path = cfg.output_dir / "used_videos.json"
        cfg.output_dir.mkdir(parents=True, exist_ok=True)
        title_filter = job.get("title_filter") or None
        scan_limit = int(job.get("channel_scan_limit", 200))
        pick = pick_unused_channel_video(channel_url, used_path, limit=scan_limit,
                                         title_filter=title_filter,
                                         cookies=ytdlp_cookie_args(cfg))
        source_url = pick["url"]
        slug = f"{base_slug}-{pick['id']}"
        step(f"      channel pick: {pick['title'][:60]} ({pick['id']})")
    else:
        slug = base_slug

    work = cfg.output_dir / slug
    work.mkdir(parents=True, exist_ok=True)

    # State store is opt-in; when None, all the `if state` guards below
    # are bypassed and the pipeline runs end-to-end as before.
    state: StateStore | None = None
    if resume_enabled:
        state = StateStore(work, slug, "single", job, log=log)
        log.info(f"resume: {state.progress_summary()}")

    pre_downloaded = job.get("source_file")
    faceless_mode = bool(job.get("faceless_mode", False))
    if faceless_mode:
        # Faceless/explainer videos have no gameplay — the generated images sit
        # on a plain colored background. Skip the YouTube download entirely.
        raw = None
        step("[1/5] Faceless-Modus: kein Gameplay-Download (einfacher Hintergrund)")
        if state:
            # No "*_path" key: an empty path string would make is_done() think a
            # file exists (Path("").exists() is True) and feed Path(".") into the
            # scene-picker on a non-faceless resume.
            state.mark_done(Step.DOWNLOAD, {"faceless": True})
    elif pre_downloaded and Path(pre_downloaded).is_file():
        raw = Path(pre_downloaded)
        step(f"[1/5] reusing pre-downloaded source: {raw.name}")
        if state:
            state.mark_done(Step.DOWNLOAD, {"raw_path": raw})
    elif state and state.is_done(Step.DOWNLOAD):
        raw = Path(state.get_artifact(Step.DOWNLOAD, "raw_path"))
        step(f"[1/5] resume: source already downloaded ({raw.name})")
    else:
        step(f"[1/5] download: {source_url}")
        raw = download_gameplay(source_url, work / "source", cookies=ytdlp_cookie_args(cfg),
                                max_height=int(getattr(cfg, 'download_max_height', 1080)))
        if state:
            state.mark_done(Step.DOWNLOAD, {"raw_path": raw})

    target_duration = float(job.get("target_duration", 30.0))

    enable_voice = bool(job.get("enable_voice", True))

    # ── Script ──
    if state and state.is_done(Step.SCRIPT):
        script = str(state.get_artifact(Step.SCRIPT, "script_text") or "")
        step(f"      resume: script cached ({len(script)} chars)")
    elif enable_voice:
        script = (job.get("script") or "").strip()
        if script:
            # Strip any LLM-assistant preamble ("Here is the script for X:")
            # that often comes along when the user pastes a chat response.
            cleaned = _clean_user_script(script)
            if cleaned != script:
                step(f"      stripped LLM preamble ({len(script) - len(cleaned)} chars removed)")
                script = cleaned

            # Quick duration estimate so the user sees BEFORE the long TTS
            # render whether the script will hit the target_duration they set.
            script_lang_hint = (getattr(cfg, "tts_language", "auto") or "auto").lower()
            if script_lang_hint not in ("de", "en"):
                script_lang_hint = _detect_language(script)
            est_secs = _estimate_script_seconds(script, script_lang_hint)
            step(f"      using user-provided script ({len(script)} chars, ~{est_secs:.0f}s estimated)")

            # If the script is meaningfully shorter than the requested
            # target, either auto-extend (opt-in toggle) or just warn loudly.
            if target_duration >= 90 and est_secs < 0.9 * target_duration:
                extend_on = bool(job.get("extend_script", False))
                have_backend = bool(cfg.gemini_api_key or getattr(cfg, "use_claude_cli", False))
                if extend_on and have_backend:
                    step(f"      extending script to ~{target_duration:.0f}s "
                         f"(from ~{est_secs:.0f}s)")
                    try:
                        script = _extend_script_to_target(
                            script, cfg, target_duration, script_lang_hint, on_step=step)
                    except Exception as e:
                        step(f"      extend failed: {e} — keeping original")
                else:
                    step(f"      WARN: script is ~{est_secs:.0f}s but target is "
                         f"{target_duration:.0f}s. Final video will be ~{est_secs:.0f}s "
                         f"(clip follows voice). Enable '🪶 Skript per AI verlängern' "
                         f"in the GUI if you want it extended.")
        else:
            topic = (job.get("topic") or "").strip()
            if not topic:
                raise RuntimeError(f"job {slug!r} has neither 'script' nor 'topic'")
            step(f"      generating script for topic: {topic!r} (target {target_duration:.0f}s)")
            # Pick script language from the TTS language toggle so Gemini
            # writes in the same language the voice engine will speak.
            # "auto" defaults to German because that's this channel's
            # primary content; users wanting English explicitly choose EN.
            script_lang = (getattr(cfg, "tts_language", "auto") or "auto").lower()
            if script_lang not in ("de", "en"):
                script_lang = "de"
            try:
                script = generate_script(topic, cfg, target_seconds=target_duration,
                                         on_step=step, language=script_lang)
            except RuntimeError as e:
                step(f"      WARN: script gen failed: {e}")
                step(f"      using template fallback script (pipeline continues)")
                script = fallback_template_script(topic)
        (work / "script.txt").write_text(script, encoding="utf-8")
        preview = script[:80].replace("\n", " ")
        step(f"      script: {preview}...")
        if state:
            state.mark_done(Step.SCRIPT, {
                "script_path": work / "script.txt",
                "script_text": script,
            })
    else:
        # Still need a non-empty seed for image prompt generation; fall back to
        # the topic field if there's no script.
        script = (job.get("topic") or "").strip() or "cinematic scene"
        if state:
            state.mark_done(Step.SCRIPT, {"script_text": script})

    # ── Voiceover ──
    voice_override = str(job.get("voice_path") or "").strip()
    if voice_override and Path(voice_override).expanduser().is_file():
        # BYO voiceover (used by the Flow assemble step to reuse the EXACT voice
        # from the export, so clip timing + captions line up).
        import shutil
        src = Path(voice_override).expanduser()
        vo = work / "voice.mp3"
        if src.resolve() != vo.resolve():
            shutil.copyfile(src, vo)
        vo_dur = probe_duration(vo)
        step(f"[2/5] using provided voice: {src.name} ({vo_dur:.1f}s)")
        if state:
            state.mark_done(Step.VOICEOVER, {"voice_path": vo, "voice_duration": vo_dur})
    elif state and state.is_done(Step.VOICEOVER):
        vo = Path(state.get_artifact(Step.VOICEOVER, "voice_path"))
        vo_dur = float(state.get_artifact(Step.VOICEOVER, "voice_duration") or 0.0)
        if vo_dur <= 0:
            vo_dur = probe_duration(vo)
        step(f"[2/5] resume: voice cached ({vo.name}, {vo_dur:.1f}s)")
    elif enable_voice:
        step("[2/5] voiceover")
        vo_raw = synthesize_voiceover(script, cfg, work / "voice_raw.mp3")
        vo = trim_leading_silence(vo_raw, work / "voice.mp3")
        # Broadcast voice chain (EQ + presence + de-ess + compression). DEFAULT
        # OFF — on Chatterbox (esp. high exaggeration) the compressor + presence
        # boost made the voice sound harsher, not better. Opt-IN via
        # job["voice_eq"]=True. Falls back to the input on any error.
        if bool(job.get("voice_eq", False)):
            step("      Voice-EQ (Highpass + Präsenz + Kompressor)")
            vo = apply_voice_eq(vo, work / "voice_eq.mp3", on_step=step)
        # Optional voice tempo (pitch-preserved). < 1.0 = calmer/slower, good
        # for long-form where the fast short-style delivery gets tiring. Applied
        # BEFORE measuring duration so the long-form auto-extend targets the
        # real, slowed-down time.
        voice_tempo = float(job.get("voice_tempo", 1.0))
        if abs(voice_tempo - 1.0) > 0.01:
            step(f"      voice tempo: {voice_tempo:.2f}x "
                 f"({'langsamer' if voice_tempo < 1 else 'schneller'})")
            apply_voice_tempo(vo, voice_tempo)
        vo_dur = probe_duration(vo)
        # Long-form length is only correct once we measure the REAL spoken
        # duration: the wps estimate that sized the script is unreliable (the
        # voice can speak ~4.5 w/s, not the assumed 2.5), so a "600s script"
        # may render as ~350s of audio. If the user enabled auto-extend, grow
        # the script + audio using the measured rate until it hits the target.
        if (target_duration >= 90 and vo_dur < 0.9 * target_duration
                and bool(job.get("extend_script", False))):
            vo_lang = (getattr(cfg, "tts_language", "auto") or "auto").lower()
            if vo_lang not in ("de", "en"):
                vo_lang = _detect_language(script)
            step(f"      voice {vo_dur:.0f}s under target {target_duration:.0f}s — "
                 f"extending to match (measured speech rate)")
            vo, vo_dur, script = _grow_voiceover_to_target(
                script, vo, vo_dur, cfg, target_duration, vo_lang, work, on_step=step)
            (work / "script.txt").write_text(script, encoding="utf-8")
        if state:
            state.mark_done(Step.VOICEOVER, {
                "voice_path": vo, "voice_duration": vo_dur,
            })
            if state.is_done(Step.SCRIPT):
                state.mark_done(Step.SCRIPT, {
                    "script_path": work / "script.txt", "script_text": script,
                })
    else:
        step("[2/5] voice disabled — generating silent base track")
        vo_dur = float(target_duration)
        vo = make_silent_track(vo_dur, work / "voice.mp3")
        if state:
            state.mark_done(Step.VOICEOVER, {
                "voice_path": vo, "voice_duration": vo_dur,
            })

    # Clip duration tracks the voiceover, not the requested target. If
    # Gemini wrote a 174s script for a 500s request, we render ~180s of
    # video — not 500s with 320s of silent gameplay. target_duration
    # only acts as an upper bound (in case the script came out longer).
    # Lower bound: vo_dur + 8s tail (room for outro / subscribe banner),
    # or 15s absolute minimum. Upper bound: target_duration + 12s.
    target = min(max(vo_dur + 8.0, 15.0), target_duration + 12.0)
    step(f"      voice {vo_dur:.1f}s -> clip {target:.1f}s (target {target_duration:.0f}s)")

    clip_segments = max(1, min(int(job.get("clip_segments", 1)), 24))
    mode = str(job.get("scene_pick_mode", "even")).lower()
    # Back-compat with the old smart_picking checkbox
    if mode == "even" and bool(job.get("smart_picking", False)):
        mode = "loud"

    if faceless_mode:
        # No gameplay: build a plain colored background to host the images.
        clip_segments = 1
        if state and state.is_done(Step.SCENE_PICK):
            clip = Path(state.get_artifact(Step.SCENE_PICK, "clip_path"))
            cached_target = state.get_artifact(Step.SCENE_PICK, "target")
            if cached_target is not None:
                target = float(cached_target)
            step(f"[3/5] resume: Faceless-Hintergrund gecacht ({clip.name})")
        else:
            bg_color = (job.get("faceless_bg_color") or "white").strip() or "white"
            step(f"[3/5] Faceless-Hintergrund ({bg_color}, {target:.1f}s)")
            clip = make_color_background(target, work / "clip.mp4",
                                         cfg.target_w, cfg.target_h, color=bg_color)
            if state:
                state.mark_done(Step.SCENE_PICK, {
                    "clip_path": clip, "target": target, "clip_segments": clip_segments,
                })
    elif state and state.is_done(Step.SCENE_PICK):
        clip = Path(state.get_artifact(Step.SCENE_PICK, "clip_path"))
        # Recover the post-mutation values so downstream stages match cache.
        cached_target = state.get_artifact(Step.SCENE_PICK, "target")
        cached_segs = state.get_artifact(Step.SCENE_PICK, "clip_segments")
        if cached_target is not None:
            target = float(cached_target)
        if cached_segs is not None:
            clip_segments = int(cached_segs)
        step(f"[3/5] resume: clip cached ({clip.name}, {target:.1f}s, {clip_segments} seg)")
    elif mode == "manual":
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
        if state:
            state.mark_done(Step.SCENE_PICK, {
                "clip_path": clip, "target": target, "clip_segments": clip_segments,
            })
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
        if state:
            state.mark_done(Step.SCENE_PICK, {
                "clip_path": clip, "target": target, "clip_segments": clip_segments,
            })
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
        if state:
            state.mark_done(Step.SCENE_PICK, {
                "clip_path": clip, "target": target, "clip_segments": clip_segments,
            })

    words_cache = work / "words.json"
    if state and state.is_done(Step.TRANSCRIBE) and words_cache.is_file():
        try:
            words = json.loads(words_cache.read_text(encoding="utf-8"))
            step(f"[4/5] resume: transcript cached ({len(words)} words)")
        except Exception:
            words = []
    elif enable_voice:
        whisper_device = str(job.get("whisper_device", "auto"))
        step(f"[4/5] transcribe + captions (device={whisper_device})")
        # Always subprocess-isolate Whisper on GPU. The in-process call leaks
        # CUDA state and can hard-freeze the whole machine after a few
        # sequential runs (especially in multi-clip mode). The subprocess
        # variant has lived in the codebase for the voice-disabled path
        # already; now we use it universally.
        words, used_dev = transcribe_words_best(
            vo, cfg.whisper_model, device=whisper_device,
            use_whisperx=bool(getattr(cfg, "use_whisperx", False)),
            whisperx_python=str(getattr(cfg, "whisperx_python", "")),
            language=str(job.get("tts_language", "auto")), on_step=step,
        )
        step(f"      whisper ran on {used_dev}")
        _release_gpu_memory()
        try:
            words_cache.write_text(json.dumps(words), encoding="utf-8")
        except Exception:
            pass
        if state:
            state.mark_done(Step.TRANSCRIBE, {
                "words_path": words_cache, "word_count": len(words),
            })
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
            words, used_dev = transcribe_words_best(
                clip_audio, cfg.whisper_model, device=whisper_device,
                use_whisperx=bool(getattr(cfg, "use_whisperx", False)),
                whisperx_python=str(getattr(cfg, "whisperx_python", "")),
                language="auto", on_step=step,
            )
            step(f"      whisper ran on {used_dev} — {len(words)} words from source audio")
            _release_gpu_memory()
            try:
                words_cache.write_text(json.dumps(words), encoding="utf-8")
            except Exception:
                pass
            if state:
                state.mark_done(Step.TRANSCRIBE, {
                    "words_path": words_cache, "word_count": len(words),
                })
        except Exception as e:
            step(f"      WARN: source transcription failed ({str(e)[:160]}); no captions")
            words = []
    else:
        step("[4/5] no voice + captions disabled — skipping transcription")
        words = []
        if state:
            state.mark_done(Step.TRANSCRIBE, {"word_count": 0})
    is_portrait_out = cfg.target_h > cfg.target_w
    # Continuous per-beat images are normally a portrait-only look. Faceless
    # mode is landscape but explicitly wants them too (it IS the look), so
    # treat it as eligible.
    allow_continuous = is_portrait_out or bool(job.get("faceless_mode", False))
    # Caption position: shorts default to "top" (text above the center
    # images, like viral Roblox shorts); landscape long-form is forced to
    # bottom inside write_ass regardless.
    cap_pos = str(job.get("caption_position", "top")).lower()

    # Contextual color-emoji overlays (portrait/shorts only). We compute the
    # schedule from `words` and pre-fetch each emoji's color PNG; if any are
    # available we tell write_ass to NOT bake the monochrome emoji into the
    # ASS text (compose_short paints the color PNGs instead). On fetch
    # failure we keep the events empty and fall back to the ASS text emoji.
    emoji_png_events: list = []
    # Color emoji overlays work in ANY orientation (it's just a PNG overlay).
    # Landscape/long-form captions are forced to the bottom, so derive the
    # effective position + chunking from the orientation, not just cap_pos —
    # otherwise long videos fell back to ugly monochrome ASS-text emojis.
    is_landscape_out = cfg.target_w >= cfg.target_h
    eff_cap_pos = "bottom" if is_landscape_out else cap_pos
    want_emojis = bool(job.get("caption_emojis", False)) and bool(words)
    if want_emojis:
        try:
            # Resolve the caption font size the same way write_ass does, so we
            # can place each emoji tightly under its caption (1 vs 2 lines)
            # instead of a fixed offset that leaves a big gap on 1-line chunks.
            resolved_fs = int(job.get("caption_font_size", 0)) or max(56, int(cfg.target_h * 0.048))
            line_h = resolved_fs * 1.15
            usable_w = max(200, cfg.target_w - 160)         # MarginL/R = 80 each
            per_line_chars = max(6, int(usable_w / (resolved_fs * 0.55)))
            emoji_h = max(48, int(cfg.target_w * 0.085))    # ~same as overlay width
            if eff_cap_pos == "top":
                cap_top = cfg.target_h * 0.13
            elif eff_cap_pos == "center":
                cap_top = cfg.target_h * 0.42
            else:
                cap_top = cfg.target_h * 0.72
            gap = int(resolved_fs * 0.22)                   # small gap to the text
            for (e_s, e_e, emo, text) in compute_caption_emoji_events(words, long_form=is_landscape_out):
                png = get_emoji_png(emo, font_path=getattr(cfg, "emoji_font_path", ""))
                if not png:
                    continue
                n_lines = 1 + (len(text) > per_line_chars)  # 1 or 2 lines
                if eff_cap_pos == "bottom":
                    # caption sits at the bottom → put the emoji ABOVE it,
                    # otherwise it lands under the text (and under the image)
                    # where it's barely visible.
                    y = int(cap_top - emoji_h - gap)
                else:
                    # emoji just below the caption text block
                    y = int(cap_top + n_lines * line_h + gap)
                # keep the emoji on-screen
                y = max(0, min(y, cfg.target_h - emoji_h))
                emoji_png_events.append((e_s, e_e, png, y))
            if emoji_png_events:
                step(f"      caption emojis: {len(emoji_png_events)} color overlay(s)")
        except Exception as e:
            log.warn(f"emoji overlay prep failed (using text fallback): {e}")
            emoji_png_events = []
    emoji_overlay_active = bool(emoji_png_events)

    ass_path = work / "captions.ass"
    if state and state.is_done(Step.CAPTIONS) and ass_path.is_file():
        ass = ass_path
        step("      resume: captions.ass cached")
    else:
        ass = write_ass(
            words, cfg.target_w, cfg.target_h, ass_path,
            font_name=str(job.get("caption_font", "Impact")),
            font_size=int(job.get("caption_font_size", 0)) or None,
            primary_color=str(job.get("caption_color", "#FFFFFF")),
            outline_color=str(job.get("caption_stroke_color", "#000000")),
            outline_width=int(job.get("caption_stroke_width", 5)),
            hook_text=str(job.get("hook_text", "")),
            hook_duration=float(job.get("hook_duration", 3.0)),
            pop_captions=bool(job.get("pop_captions", False)),
            subscribe_overlay=bool(job.get("subscribe_overlay", False)),
            subscribe_text=str(job.get("subscribe_text", "SUBSCRIBE")),
            total_duration=vo_dur,
            enable_captions=bool(job.get("enable_captions", True)),
            # Landscape output = the GUI's "Lang-Video" format → readable
            # subtitle styling instead of TikTok karaoke pops.
            long_form=(cfg.target_w >= cfg.target_h),
            caption_emojis=bool(job.get("caption_emojis", False)),
            caption_position=cap_pos,
            emoji_overlay=emoji_overlay_active,
            keyword_pop=("keyword_pop" in [str(e).lower() for e in (job.get("effects_enabled") or [])]),
            word_karaoke=("word_karaoke" in [str(e).lower() for e in (job.get("effects_enabled") or [])]),
            caption_polish=("caption_polish" in [str(e).lower() for e in (job.get("effects_enabled") or [])]),
            caption_box=("caption_box" in [str(e).lower() for e in (job.get("effects_enabled") or [])]),
            caption_buildup=("caption_buildup" in [str(e).lower() for e in (job.get("effects_enabled") or [])]),
        )
        if state:
            state.mark_done(Step.CAPTIONS, {"ass_path": ass})

    image_paths: list = []
    plan: list = []  # per-beat scene plan (also consumed by the Flow export hook)
    image_duration = float(job.get("image_duration", 1.5))
    # Free the ~3-4 GB Chatterbox model from VRAM before a LONG image run
    # (crash/thermal mitigation) — but NOT for small shorts, where unloading
    # just forces a slow reload of the model on the next video in a batch.
    # Cheap pre-estimate of the image count to decide.
    _cont = bool(job.get("images_continuous", False)) and (
        is_portrait_out or bool(job.get("faceless_mode", False)))
    if _cont and not (job.get("image_prompts") or []):
        _change = max(1.0, float(job.get("image_change_secs", 3.5)))
        _est_imgs = max(4, min(int(round((vo_dur or 25.0) / _change)), 120))
    else:
        _est_imgs = max(1, min(int(job.get("image_count", 3)), 50))
    if _est_imgs >= 12 or float(getattr(cfg, "image_cooldown_secs", 0.0) or 0.0) > 0:
        _unload_tts_model()
    if state and state.is_done(Step.IMAGES):
        cached_paths = state.get_artifact(Step.IMAGES, "paths") or []
        image_paths = [Path(p) for p in cached_paths if Path(p).is_file()]
        step(f"      resume: {len(image_paths)} image(s) cached")
    elif not job.get("no_image"):
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
            user_prompts = [p.strip() for p in (job.get("image_prompts") or []) if p and p.strip()]
            # Continuous mode (portrait): auto-derive the image count from the
            # voiceover length so a fresh image lands every ~image_change_secs,
            # like the reference (images change every 2-4s). Otherwise honor
            # the GUI's fixed count.
            continuous = bool(job.get("images_continuous", False)) and allow_continuous
            if continuous and not user_prompts:
                change_secs = max(1.0, float(job.get("image_change_secs", 3.5)))
                # Cap scales with length so long-form can use many images
                # (every ~change_secs) without exploding on a 10-minute video.
                cont_cap = max(14, min(int((vo_dur or 25.0) / 6.0), 120))
                n_images = max(4, min(int(round((vo_dur or 25.0) / change_secs)), cont_cap))
            else:
                n_images = max(1, min(int(job.get("image_count", 3)), 50))

            # Faceless = a pure hand-drawn slideshow: NO real photos, NO stock
            # video — every beat must be an AI render in the chosen flat style.
            allow_photos = bool(job.get("image_allow_photos", True)) and not faceless_mode
            # Videos need a source: Pexels stock (key) OR Higgsfield AI video.
            higgsfield_ready = bool(
                getattr(cfg, "use_higgsfield", False)
                and (getattr(cfg, "higgsfield_video_model", "") or "").strip()
                and _resolve_higgsfield_cli(getattr(cfg, "higgsfield_cli_path", "") or "higgsfield"))
            allow_videos = (bool(job.get("image_allow_videos", False))
                            and not faceless_mode
                            and (bool(getattr(cfg, "pexels_api_key", "")) or higgsfield_ready))
            if getattr(cfg, "use_higgsfield", False) and not higgsfield_ready:
                step("      WARN: use_higgsfield on, but CLI not found or "
                     "higgsfield_video_model unset — using Pexels for video beats")
            if user_prompts:
                step(f"      using {len(user_prompts)} user-provided image prompt(s)")
                # Finalize through the chosen style so user prompts also get the
                # stickman/doodle directive in faceless mode (not raw → mixed look).
                plan = [{"source": "ai", "motif": p, "query": "",
                         "prompt": _finalize_scene_prompt(p, cfg)} for p in user_prompts[:n_images]]
                if len(plan) < n_images:
                    step(f"      filling remaining {n_images - len(plan)} beat(s) via LLM")
                    plan.extend(generate_scene_plan(script, n_images - len(plan), cfg,
                                                    allow_photos=allow_photos,
                                                    allow_videos=allow_videos, on_step=step))
            else:
                kinds = ["AI"] + (["photos"] if allow_photos else []) + (["videos"] if allow_videos else [])
                step(f"      planning {n_images} beats ({' + '.join(kinds)}) via LLM")
                plan = generate_scene_plan(script, n_images, cfg,
                                           allow_photos=allow_photos,
                                           allow_videos=allow_videos, on_step=step)

            consecutive_failures = 0
            # Faceless landscape → generate/keep images at 16:9 so they fill the
            # widescreen frame (no squared cards, no side bars). Faceless PORTRAIT
            # (KI-Bild-Short) → 9:16 so they fill the vertical frame.
            faceless_wide = faceless_mode and not is_portrait_out
            faceless_tall = faceless_mode and is_portrait_out
            cloudflare_ready = bool(cfg.cloudflare_account_id and cfg.cloudflare_api_token)
            grok_ready = bool(getattr(cfg, "use_grok_cli", False)
                              and _resolve_grok_cli(getattr(cfg, "grok_cli_path", "") or "grok"))
            hf_img_ready = bool(getattr(cfg, "use_higgsfield_images", False)
                                and _resolve_higgsfield_cli(getattr(cfg, "higgsfield_cli_path", "") or "higgsfield"))
            if getattr(cfg, "use_higgsfield_images", False) and not hf_img_ready:
                step("      WARN: use_higgsfield_images on, but `higgsfield` CLI not found — "
                     "using Grok/Cloudflare/Pollinations for AI images")
            if getattr(cfg, "use_grok_cli", False) and not grok_ready:
                step("      WARN: use_grok_cli on, but `grok` CLI not found — "
                     "using Cloudflare/Pollinations for AI images")
            beat_dur = float(job.get("image_change_secs", 3.5))
            for i, beat in enumerate(plan, 1):
                source = beat.get("source", "ai")
                prompt = beat.get("prompt", "") or derive_image_prompt(script[:120], cfg)
                query = beat.get("query", "")
                # video beats get .mp4, others .png
                ext = "mp4" if source == "video" else "png"
                target_path = work / f"image_{i}.{ext}"
                label = f"{source}:{query}" if source in ("photo", "video") else prompt
                step(f"      [{i}/{len(plan)}] {source}: {label[:74]}")
                ok = False
                primary_err: str | None = None

                # Video beats → Higgsfield AI video first (opt-in), then Pexels
                # stock B-roll, then fall back to photo→AI.
                if source == "video" and query:
                    if higgsfield_ready:
                        try:
                            # Prefer the richer AI motif as the prompt; the
                            # search query is the fallback descriptor.
                            hf_prompt = (beat.get("motif") or "").strip() or query
                            fetch_video_from_higgsfield(hf_prompt, target_path, cfg, on_step=step)
                            image_paths.append(target_path)
                            ok = True
                        except Exception as e:
                            primary_err = f"Higgsfield: {e}"
                            step(f"      higgsfield miss ({str(e)[:120]}), versuche Pexels")
                    if not ok:
                        try:
                            fetch_video_from_pexels(query, target_path, cfg, max_dur=beat_dur + 0.6)
                            image_paths.append(target_path)
                            ok = True
                        except Exception as e:
                            primary_err = f"{primary_err}; Pexels: {e}" if primary_err else f"Pexels: {e}"
                            step(f"      pexels miss ({str(e)[:120]}), versuche Foto")
                            source = "photo"
                            target_path = target_path.with_suffix(".png")

                # Photo beats → free stock/photo sources first, AI fallback.
                if not ok and source == "photo" and query:
                    try:
                        fetch_free_photo(query, target_path, cfg=cfg, on_step=step)
                        image_paths.append(target_path)
                        ok = True
                    except Exception as e:
                        primary_err = f"FreePhoto: {e}"
                        step(f"      free-photo miss ({str(e)[:120]}), AI render instead")

                # AI render cascade: Higgsfield (e.g. nano_banana_2) first if
                # enabled, then Grok Build CLI, then Cloudflare Flux, then
                # Pollinations. Faceless landscape wants 16:9 — Cloudflare is
                # asked directly; Higgsfield/Grok/Pollinations are re-cropped.
                if faceless_wide:
                    cf_w, cf_h = 1280, 720
                elif faceless_tall:
                    cf_w, cf_h = 720, 1280
                else:
                    cf_w, cf_h = 1024, 1024
                if not ok and hf_img_ready:
                    try:
                        fetch_image_from_higgsfield(prompt, target_path, cfg,
                                                    faceless_wide=faceless_wide, on_step=step)
                        if faceless_tall:
                            _faceless_recrop(target_path, ar=9 / 16)
                        image_paths.append(target_path)
                        ok = True
                    except Exception as e:
                        primary_err = f"{primary_err}; Higgsfield: {e}" if primary_err else f"Higgsfield: {e}"
                        step(f"      Higgsfield image miss ({str(e)[:120]}), falling back")
                if not ok and grok_ready:
                    try:
                        grok_aspect = "9:16" if faceless_tall else ("16:9" if faceless_wide else "1:1")
                        fetch_image_from_grok_cli(prompt, target_path, cfg,
                                                  aspect=grok_aspect, on_step=step)
                        if faceless_wide:
                            _faceless_recrop(target_path)
                        elif faceless_tall:
                            _faceless_recrop(target_path, ar=9 / 16)
                        image_paths.append(target_path)
                        ok = True
                    except Exception as e:
                        primary_err = f"{primary_err}; Grok: {e}" if primary_err else f"Grok: {e}"
                        step(f"      Grok CLI miss ({str(e)[:120]}), falling back to Cloudflare/Pollinations")

                if not ok and cloudflare_ready:
                    try:
                        fetch_image_from_cloudflare(
                            prompt, target_path, cfg,
                            width=cf_w, height=cf_h,
                            seed=random.randint(1, 1_000_000),
                        )
                        image_paths.append(target_path)
                        ok = True
                    except Exception as e:
                        primary_err = f"{primary_err}; Cloudflare: {e}" if primary_err else f"Cloudflare: {e}"
                        step(f"      Cloudflare failed, falling back to Pollinations")

                if not ok:
                    try:
                        fetch_image_from_pollinations(
                            prompt, target_path, seed=random.randint(1, 1_000_000),
                            width=cf_w, height=cf_h,
                        )
                        if faceless_wide:
                            _faceless_recrop(target_path)
                        elif faceless_tall:
                            _faceless_recrop(target_path, ar=9 / 16)
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
                    if consecutive_failures >= 2 and i < len(plan):
                        step(
                            f"      image sources seem down, skipping remaining "
                            f"{len(plan) - i} image(s); pipeline continues without them"
                        )
                        break

                # Optional cooldown between images. On a marginal PSU/cooling
                # setup a long unbroken GPU image run can trip a thermal/over-
                # current shutdown; a short pause lets the GPU breathe. Opt-in
                # via cfg.image_cooldown_secs (0 = off, default). Local-image-gen
                # only — pointless for network sources (Cloudflare/Pollinations).
                cooldown = float(getattr(cfg, "image_cooldown_secs", 0.0) or 0.0)
                if ok and cooldown > 0 and i < len(plan):
                    time.sleep(min(cooldown, 10.0))

    if state and not state.is_done(Step.IMAGES):
        state.mark_done(Step.IMAGES, {
            "paths": [str(p) for p in image_paths],
            "count": len(image_paths),
        })

    # Optional: also export the generated images named by their on-screen
    # timestamp (00_07.png …) for manual CapCut editing — runs ALONGSIDE the
    # normal render, never instead of it (Danny-Why faceless workflow).
    if image_paths and bool(job.get("export_timestamp_images", False)):
        ts_continuous = bool(job.get("images_continuous", False)) and allow_continuous
        ts_schedule = _image_schedule(len(image_paths), target, image_duration,
                                      continuous=ts_continuous,
                                      gap=float(job.get("image_gap_secs", 0.5)))
        ts_dir = Path(cfg.output_dir).expanduser() / f"{slug}_timestamp_images"
        try:
            export_timestamped_images(image_paths, ts_schedule, ts_dir, on_step=step)
        except Exception as e:
            step(f"      WARN: Zeitstempel-Export fehlgeschlagen: {str(e)[:120]}")

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
            # MUST use the SAME schedule (incl. continuous flag) that
            # compose_short uses for the image overlays — otherwise the SFX
            # fires at the old gapped-schedule times and lands ~1s after the
            # image actually changes.
            sfx_continuous = bool(job.get("images_continuous", False)) and allow_continuous
            schedule = _image_schedule(len(image_paths), target, image_duration,
                                       continuous=sfx_continuous,
                                       gap=float(job.get("image_gap_secs", 0.5)))
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

    # Loudness-normalize the finished mix so output loudness is consistent
    # and punchy (reference shorts sit ~-11..-14 LUFS). Opt-out via
    # job["normalize_audio"]=False. Never fails the job — on error we keep
    # the un-normalized mix.
    if bool(job.get("normalize_audio", True)) and enable_voice:
        try:
            target_lufs = float(job.get("target_lufs", -14.0))
            step(f"      normalizing loudness to {target_lufs:.0f} LUFS")
            audio_for_compose = normalize_loudness(
                audio_for_compose, work / "audio_normalized.mp3",
                target_lufs=target_lufs,
            )
        except Exception as e:
            log.warn(f"loudness normalization failed (using un-normalized mix): {e}")

    crop_offset = 0.5
    if state and state.is_done(Step.REFRAME):
        cached = state.get_artifact(Step.REFRAME, "crop_offset")
        if isinstance(cached, list):
            crop_offset = [(float(t), float(o)) for t, o in cached]
        elif cached is not None:
            crop_offset = float(cached)
        step(f"      resume: reframe offset cached")
    elif cfg.target_w >= cfg.target_h:
        # Landscape output uses scale-cover-crop instead of a 9:16 strip,
        # so a horizontal crop offset would be ignored downstream — skip
        # the face-detect work to save GPU time.
        if bool(job.get("auto_reframe", False)):
            step("      auto-reframe skipped: landscape output ignores horizontal crop offsets")
    elif bool(job.get("auto_reframe", False)):
        if use_reframe_v2:
            seg_dur = target / clip_segments if clip_segments > 0 else target
            step(f"      auto-reframe v2: per-scene tracking "
                 f"({clip_segments} seg × {seg_dur:.1f}s)")
            offsets = _reframe2.detect_crop_offsets_v2(
                clip, cfg,
                n_segments=clip_segments,
                seg_duration=seg_dur,
                samples_per_segment=int(job.get("reframe_samples_per_seg", 3)),
                speaker_detection=bool(job.get("speaker_detection", False)),
                on_step=step,
            )
            if clip_segments > 1:
                crop_offset = offsets
            else:
                crop_offset = _reframe2.collapse_to_single_offset(offsets)
        elif clip_segments > 1:
            seg_dur = target / clip_segments
            step(f"      auto-reframe: per-scene detection ({clip_segments} segments)")
            crop_offset = detect_subjects_per_segment(
                clip, clip_segments, seg_dur, cfg, on_step=step
            )
        else:
            step("      auto-reframe: asking Cloudflare Vision where the subject is")
            crop_offset = detect_subject_x_position(clip, cfg, on_step=step)
        _release_gpu_memory()
        if state:
            state.mark_done(Step.REFRAME, {"crop_offset": crop_offset})

    # Google-Flow export hook: stop after the start images are generated and
    # package them + prompts + voice for a Flow image-to-video run. No compose.
    flow_export_dir = str(job.get("flow_export_dir") or "").strip()
    if flow_export_dir:
        return write_flow_export(
            Path(flow_export_dir).expanduser(), slug, image_paths, plan,
            vo, vo_dur, job, cfg, on_step=step)

    step("[5/5] compose final short")
    out = cfg.output_dir / f"{slug}.mp4"
    # KI-directed effects (color grade / flash / shake). Opt-in via the
    # effects list; the LLM places the timed ones at dramatic beats.
    effects_enabled = job.get("effects_enabled") or []
    effects_plan = None
    if effects_enabled:
        effects_plan = generate_effect_plan(
            script if enable_voice else "", target, effects_enabled, cfg,
            ai_direction=bool(job.get("effects_ai", True)), on_step=step,
        )
    if state and state.is_done(Step.COMPOSE) and out.is_file():
        step(f"      resume: final video already rendered: {out.name}")
    else:
        compose_short(
            clip, audio_for_compose, ass, cfg, out,
            image_paths=image_paths,
            duration=target,
            image_duration=image_duration,
            # The faceless color background has NO audio stream, so the amix
            # path (which references [0:a]) would abort ffmpeg — always mute it.
            mute_source_audio=using_bgm or faceless_mode,
            progress_bar=bool(job.get("progress_bar", False)),
            progress_color=str(job.get("progress_color", "red")),
            progress_duration=vo_dur,
            crop_offset=crop_offset,
            image_tilt=bool(job.get("image_tilt", True)),
            images_continuous=bool(job.get("images_continuous", False)) and allow_continuous,
            image_gap=float(job.get("image_gap_secs", 0.5)),
            image_size=float(job.get("image_size", 0.92)),
            image_vpos=float(job.get("image_vpos", -0.03)),
            emoji_events=emoji_png_events,
            caption_position=eff_cap_pos,
            effects=effects_plan,
            faceless=faceless_mode,
        )
        # Opt-in: cut silent/dead-air stretches out of the finished video.
        # Runs on the composed mp4 (picture+voice+captions cut together → no
        # sync drift), before the global speed pass.
        if bool(job.get("auto_editor", False)):
            step("      auto-editor: schneide Stille/Pausen raus")
            apply_auto_editor(
                out,
                margin=float(job.get("auto_editor_margin", 0.18)),
                threshold=float(job.get("auto_editor_threshold", 0.04)),
                on_step=step,
            )
        speed = float(job.get("playback_speed", 1.0))
        if abs(speed - 1.0) > 0.01:
            step(f"      retiming final video to {speed:.2f}x playback speed")
            apply_playback_speed(out, speed)
        if state:
            state.mark_done(Step.COMPOSE, {"out_path": out})
    step(f"      -> {out}")

    # ── Optional YouTube metadata sidecar ──
    if yt_meta_enabled:
        if state and state.is_done(Step.YT_METADATA):
            log.info("resume: youtube metadata already generated")
        else:
            step("[YT] generating youtube metadata")
            try:
                meta = _yt_opt.generate_youtube_metadata(
                    topic=str(job.get("topic", "")),
                    script=script,
                    cfg=cfg,
                    target_lang=str(job.get("youtube_lang", "auto")),
                    target_seconds=float(target),
                    orientation=("landscape" if cfg.target_w >= cfg.target_h
                                 else "portrait"),
                    on_step=step,
                )
                if bool(job.get("youtube_thumbnail", True)):
                    thumb_out = work / f"{slug}_thumb.png"
                    # Prefer a frame-from-video thumb (actual content, with
                    # the hook painted on) over a generic AI render; fall
                    # back to the AI thumb if the frame extractor fails.
                    use_frame_thumb = bool(job.get("youtube_thumb_from_video", True))
                    hook = str(job.get("hook_text", "")).strip() or meta.title
                    made = None
                    if use_frame_thumb:
                        try:
                            made = _yt_opt.generate_thumbnail_from_video(
                                out, hook, thumb_out, on_step=step,
                            )
                        except Exception as e:
                            step(f"      thumb-from-video failed ({str(e)[:120]}), AI fallback")
                    if not made or not Path(thumb_out).is_file():
                        _yt_opt.generate_thumbnail(meta, thumb_out, cfg, on_step=step)
                    if Path(thumb_out).is_file():
                        meta.thumbnail_path = str(thumb_out)
                json_path, txt_path = _yt_opt.write_metadata_sidecars(meta, out)
                step(f"      youtube: {json_path.name} + {txt_path.name}")
                if state:
                    state.mark_done(Step.YT_METADATA, {
                        "json_path": json_path,
                        "txt_path": txt_path,
                        "title": meta.title,
                    })
            except Exception as e:
                log.warn(f"youtube metadata failed (pipeline continues): {e}")
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
