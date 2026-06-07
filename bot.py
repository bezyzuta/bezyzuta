"""Telegram remote control for the shorts pipeline.

Run this on the PC that has the GPU + models + config.json. From your phone
you message the bot a job; it renders on the PC and sends the finished mp4
back into the chat. Handy while you're away — leave the PC on and this
running.

Setup (one time):
  1. Talk to @BotFather on Telegram → /newbot → copy the token.
  2. Get your own chat id: message @userinfobot, it replies with your id.
  3. In config.json add:
       "telegram_bot_token": "123456:ABC...",
       "telegram_allowed_chat_id": 12345678,
       (optional) "telegram_music_dir": "C:\\Users\\bezy\\Desktop\\music",
       (optional) "telegram_sfx_dir":   "C:\\Users\\bezy\\Desktop\\sfx"
  4. Start it:  .venv\\Scripts\\python.exe bot.py
  Leave that window open. The PC must stay awake (no sleep).

Message format (one job per message):
  url: https://youtube.com/watch?v=...     (leave out for a faceless video)
  format: short | long | faceless           (default: short)
  lang: de | en | auto                      (default: auto)
  effects: all-no-horror | all | horror | none | <comma list>  (default: all-no-horror)
  hook: HE KNEW MY NAME                      (optional, short on-screen text)
  music: <track filename in your music dir>  (optional)
  script:
  <everything after this line is the spoken script, can be multi-line>

Only ALL keys are optional except either url or (format: faceless). Send /help
for a reminder.

Security: only telegram_allowed_chat_id may trigger renders. Everyone else is
ignored.
"""

import json
import sys
import threading
import time
import traceback
from pathlib import Path

import requests

import pipeline
from pipeline import Config, run_one

_API = "https://api.telegram.org/bot{token}/{method}"

# Effect presets the message can name. Mirror the GUI effect keys.
_FX_ALL_NO_HORROR = ["color_grade", "flash", "shake", "punch",
                     "ken_burns", "slide_in", "keyword_pop", "word_karaoke"]
_FX_HORROR = ["horror_grade", "red_flash", "dark_pulse", "glitch", "creep", "shake"]
_FX_ALL = _FX_ALL_NO_HORROR + [e for e in _FX_HORROR if e not in _FX_ALL_NO_HORROR]


def _tg(token: str, method: str, **params):
    """Call a Telegram Bot API method (no file upload)."""
    r = requests.post(_API.format(token=token, method=method), data=params, timeout=60)
    return r.json()


def _send(token: str, chat_id, text: str):
    # Telegram caps a message at 4096 chars.
    _tg(token, "sendMessage", chat_id=chat_id, text=text[:4000])


def _send_video(token: str, chat_id, path: Path, caption: str = ""):
    """Send the finished mp4. Bot API uploads cap at ~50 MB — fall back to a
    plain document for anything in range, and warn (not crash) if too big."""
    size_mb = path.stat().st_size / 1e6
    method = "sendVideo" if size_mb <= 49 else "sendDocument"
    field = "video" if method == "sendVideo" else "document"
    if size_mb > 49:
        _send(token, chat_id,
              f"⚠️ Video ist {size_mb:.0f} MB — über Telegrams 50 MB-Bot-Limit. "
              f"Liegt auf dem PC: {path}")
        return
    with open(path, "rb") as fh:
        url = _API.format(token=token, method=method)
        requests.post(url, data={"chat_id": chat_id, "caption": caption[:1000]},
                      files={field: fh}, timeout=600)


def _parse_message(text: str) -> dict:
    """Parse the key:value message into a small spec dict. Everything after a
    'script:' line is the script (kept verbatim, multi-line)."""
    spec: dict = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        low = line.strip().lower()
        if low.startswith("script:"):
            after = line.split(":", 1)[1]
            rest = "\n".join([after] + lines[i + 1:]).strip()
            spec["script"] = rest
            break
        if ":" in line:
            k, v = line.split(":", 1)
            spec[k.strip().lower()] = v.strip()
        i += 1
    return spec


def _effects_from_spec(value: str) -> list:
    v = (value or "all-no-horror").strip().lower()
    if v in ("none", "keine", "aus", "off"):
        return []
    if v in ("all", "alle"):
        return list(_FX_ALL)
    if v in ("horror",):
        return list(_FX_HORROR)
    if v in ("all-no-horror", "alle-ausser-horror", "alle ausser horror", ""):
        return list(_FX_ALL_NO_HORROR)
    # explicit comma list of effect keys
    return [e.strip() for e in v.split(",") if e.strip()]


def _full_short_defaults() -> dict:
    """A maxed-out short: every engagement feature on, matching a fully-loaded
    GUI render. cfg-level stuff (Claude CLI, voice clone, image style,
    Higgsfield, …) comes from config.json automatically via run_one."""
    return {
        "scene_pick_mode": "even",
        "clip_segments": 1,
        "enable_voice": True,
        "voice_tempo": 1.0,
        # Images: continuous changing visuals, full-size centered.
        "images_continuous": True,
        "image_count": 6,
        "image_duration": 1.5,
        "image_size": 1.0,
        "image_vpos": -0.03,
        "image_change_secs": 3.5,
        "image_gap_secs": 0.5,
        "image_tilt": False,
        "image_allow_photos": False,
        "image_allow_videos": False,
        # Auto-reframe v2 so the speaker stays in the vertical crop.
        "auto_reframe": True,
        "reframe_v2": True,
        "reframe_samples_per_seg": 3,
        # Captions: TikTok karaoke + emojis + styling.
        "enable_captions": True,
        "caption_position": "top",
        "caption_emojis": True,
        "pop_captions": True,
        "caption_font": "Impact",
        "caption_font_size": 80,
        "caption_color": "#FFFFFF",
        "caption_stroke_color": "#000000",
        # Effects: KI-directed, all the non-horror engagement set.
        "effects_ai": True,
        "effects_enabled": list(_FX_ALL_NO_HORROR),
        # Audio polish.
        "normalize_audio": True,
        "target_lufs": -14.0,
        "enable_sfx": True,
        "sfx_volume_pct": 35.0,
        "enable_music": True,
        "music_volume_pct": 14.0,
        "smart_music_start": True,
        # End-screen subscribe banner.
        "subscribe_overlay": True,
        "progress_bar": True,
        "whisper_device": "auto",
    }


def _build_job_and_cfg(spec: dict, cfg: Config) -> dict:
    """Build a full-featured short job. Layering: built-in short defaults →
    config.json 'telegram_defaults' (your exact prefs) → per-message overrides."""
    fmt = (spec.get("format") or "short").strip().lower()
    faceless = fmt in ("faceless", "story")
    landscape = fmt in ("long", "landscape", "lang")
    if landscape or faceless:
        cfg.target_w, cfg.target_h = 1920, 1080
    else:
        cfg.target_w, cfg.target_h = 1080, 1920

    lang = (spec.get("lang") or spec.get("sprache") or "auto").strip().lower()
    if lang in ("de", "en", "auto"):
        cfg.tts_language = lang

    script = (spec.get("script") or "").strip()
    topic = (spec.get("topic") or spec.get("thema") or "").strip()
    if not script and not topic:
        topic = "ein krasser Roblox Moment" if lang == "de" else "an insane Roblox moment"

    # Layer 1: full built-in short defaults.
    job = _full_short_defaults()
    # Layer 2: your exact preferences from config.json.
    job.update(dict(getattr(cfg, "telegram_defaults", {}) or {}))

    # Format-specific tweaks (long/faceless differ from a short).
    if landscape or faceless:
        job["caption_position"] = "bottom"
        job["auto_reframe"] = False
        job["images_continuous"] = True
    job["faceless_mode"] = faceless
    if faceless:
        job["image_allow_photos"] = False
        job["image_allow_videos"] = False

    job["slug"] = pipeline._slugify_local((topic or script)[:40]) or "tg-short"
    job["topic"] = topic or script[:60]
    job["target_duration"] = float(
        spec.get("dauer") or spec.get("target")
        or job.get("target_duration") or (480 if (landscape or faceless) else 30))

    # Layer 3: per-message overrides.
    if "effects" in spec or "effekte" in spec:
        job["effects_enabled"] = _effects_from_spec(spec.get("effects") or spec.get("effekte"))
    if spec.get("hook"):
        job["hook_text"] = spec["hook"].strip()
        job.setdefault("hook_duration", 3.0)
    if script:
        job["script"] = script
        job["extend_script"] = bool(landscape or faceless)
    if spec.get("url"):
        job["source_url"] = spec["url"].strip()

    # Auto-wire music/SFX dirs (random track) when configured, unless the user's
    # telegram_defaults already pinned a specific track/dir.
    music_dir = (getattr(cfg, "telegram_music_dir", "") or "").strip()
    if job.get("enable_music") and music_dir and not job.get("music_dir"):
        job["music_dir"] = music_dir
        job.setdefault("music_track", "")  # "" = random pick from the dir
    music = (spec.get("music") or spec.get("musik") or "").strip()
    if music:
        if music.lower() in ("off", "aus", "none", "kein"):
            job["enable_music"] = False
        elif music.lower() not in ("on", "an", "random") and music_dir:
            job["enable_music"] = True
            job["music_dir"] = music_dir
            job["music_track"] = music
    sfx_dir = (getattr(cfg, "telegram_sfx_dir", "") or "").strip()
    if job.get("enable_sfx") and sfx_dir and not job.get("sfx_dir"):
        job["sfx_dir"] = sfx_dir
    if not job.get("music_dir"):
        job["enable_music"] = False   # no dir → can't play music, avoid a crash
    if not job.get("sfx_dir"):
        job["enable_sfx"] = False

    # Per-message volume control (percent). 'music_volume: 8' = quieter music.
    mvol = (spec.get("music_volume") or spec.get("musik_lautstärke")
            or spec.get("musik_lautstaerke") or "").strip()
    if mvol:
        try:
            job["music_volume_pct"] = max(0.0, min(100.0, float(mvol.replace("%", ""))))
        except ValueError:
            pass
    svol = (spec.get("sfx_volume") or spec.get("sfx_lautstärke")
            or spec.get("sfx_lautstaerke") or "").strip()
    if svol:
        try:
            job["sfx_volume_pct"] = max(0.0, min(100.0, float(svol.replace("%", ""))))
        except ValueError:
            pass
    return job


_HELP = (
    "🎬 Schick mir einen Job so:\n\n"
    "url: https://youtube.com/watch?v=...\n"
    "format: short | long | faceless\n"
    "lang: de | en | auto\n"
    "effects: all-no-horror | all | horror | none\n"
    "hook: HE KNEW MY NAME\n"
    "music: <trackname.mp3>  (oder 'off')\n"
    "music_volume: 14   (Prozent, Standard 14)\n"
    "script:\n"
    "<dein Skript hier, mehrzeilig>\n\n"
    "url weglassen = Faceless (kein Gameplay). Nur du kannst Videos auslösen."
)


def main():
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.json")
    cfg = Config.load(cfg_path)
    token = (getattr(cfg, "telegram_bot_token", "") or "").strip()
    allowed = getattr(cfg, "telegram_allowed_chat_id", 0)
    if not token:
        print("FEHLER: telegram_bot_token fehlt in config.json")
        return
    if not allowed:
        print("FEHLER: telegram_allowed_chat_id fehlt in config.json "
              "(message @userinfobot to get your id)")
        return

    print(f"Telegram-Bot läuft. Erlaubte Chat-ID: {allowed}. Strg+C zum Beenden.")
    busy = threading.Lock()
    offset = 0

    def handle(chat_id, text):
        # Reload cfg per job so config.json edits take effect without restart.
        job_cfg = Config.load(cfg_path)
        try:
            spec = _parse_message(text)
            job = _build_job_and_cfg(spec, job_cfg)
            _send(token, chat_id, f"🎬 Rendere '{job['slug']}' … (ein paar Minuten)")
            last = [0.0]

            def on_step(msg):
                # Throttle progress to ~1 msg / 6s so we don't spam / hit limits.
                now = time.time()
                if now - last[0] > 6 and str(msg).strip():
                    last[0] = now
                    _send(token, chat_id, str(msg)[:300])

            out = run_one(job, job_cfg, on_step=on_step)
            _send(token, chat_id, "✅ Fertig! Lade hoch …")
            _send_video(token, chat_id, Path(out), caption=job["slug"])
        except Exception as e:
            tb = traceback.format_exc()[-500:]
            _send(token, chat_id, f"❌ Fehler: {str(e)[:300]}\n\n{tb}")
        finally:
            busy.release()

    while True:
        try:
            resp = _tg(token, "getUpdates", timeout=50, offset=offset)
        except Exception as e:
            print(f"poll error: {str(e)[:120]}")
            time.sleep(5)
            continue
        for upd in resp.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat_id = (msg.get("chat") or {}).get("id")
            text = msg.get("text") or ""
            if not chat_id or not text:
                continue
            if str(chat_id) != str(allowed):
                _send(token, chat_id, "⛔ Nicht autorisiert.")
                continue
            if text.strip().lower() in ("/start", "/help", "help"):
                _send(token, chat_id, _HELP)
                continue
            if not busy.acquire(blocking=False):
                _send(token, chat_id, "⏳ Ich rendere gerade schon ein Video — "
                                      "warte bis das fertig ist und schick dann erneut.")
                continue
            threading.Thread(target=handle, args=(chat_id, text), daemon=True).start()


if __name__ == "__main__":
    main()
