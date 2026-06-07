"""Headless Autopilot — token-free batch runner + YouTube auto-upload.

WHY: when Claude (the chat/dispatch) drives each render it burns tokens. The
pipeline itself needs NO Claude — it runs on Gemini's free tier + local
TTS/ffmpeg. This script reads a `jobs.json` queue and renders every job via the
exact same `pipeline.run_one` / `run_multiclip` the GUI uses, then optionally
uploads the result to YouTube. Zero tokens. Meant to be started by a
double-click `start-autopilot.bat` (or Windows Task Scheduler) while you're away.

Usage:
    python autopilot.py [autopilot.jobs.json] [--force] [--no-upload] [--no-shutdown]

  queue file   default: autopilot.jobs.json next to this script
  --force      re-run jobs already marked done in autopilot_state.json
  --no-upload  render only, skip every YouTube upload this run
  --no-shutdown ignore "shutdown_when_done" in the queue file

See AUTOPILOT.md for the queue format and the one-time YouTube OAuth setup.
"""

import argparse
import json
import re
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from pipeline import Config, run_one, run_multiclip


# ── Job defaults ────────────────────────────────────────────────────────────
# Mirrors the GUI's default job dict so a jobs.json entry only needs to specify
# what differs. Anything here can be overridden per job via "overrides".
DEFAULT_JOB = {
    "target_duration": 60.0, "clip_segments": 4, "playback_speed": 1.0,
    "voice_tempo": 1.0, "scene_pick_mode": "even", "manual_ranges": "",
    "auto_reframe": True, "reframe_v2": True, "reframe_samples_per_seg": 3,
    "speaker_detection": False, "resume": False, "log_level": "INFO",
    "youtube_metadata": True, "youtube_thumbnail": False,
    "youtube_thumb_from_video": False, "youtube_lang": "auto",
    "enable_voice": True, "image_count": 6, "image_duration": 3.5,
    "image_size": 1.0, "image_vpos": -0.03, "no_image": False,
    "image_tilt": False, "images_continuous": True,
    "export_timestamp_images": False, "image_change_secs": 3.5,
    "image_gap_secs": 0.5, "image_allow_photos": True,
    "image_allow_videos": False, "caption_font": "Impact",
    "caption_font_size": 80, "caption_color": "#FFFFFF",
    "caption_stroke_color": "#000000", "caption_position": "top",
    "hook_text": "", "hook_duration": 2.5, "effects_enabled": [],
    "effects_ai": True, "pop_captions": True, "caption_emojis": True,
    "progress_bar": True, "subscribe_overlay": True,
    "subscribe_sting_file": "", "subscribe_sting_volume": 50.0,
    "whisper_device": "auto", "multiclip_enabled": False, "multiclip_count": 3,
    "enable_music": True, "music_dir": "", "music_volume_pct": 30.0,
    "music_track": "", "smart_music_start": True, "normalize_audio": True,
    "target_lufs": -14.0, "enable_sfx": True, "enable_captions": True,
    "sfx_dir": "", "sfx_volume_pct": 50.0, "sfx_track": "", "voice_eq": False,
}

# Convenience top-level entry keys that map straight onto the job dict (so you
# don't have to nest the common ones inside "overrides").
_JOB_PASSTHROUGH = {
    "target_duration", "multiclip_enabled", "multiclip_count", "enable_voice",
    "youtube_metadata", "hook_text", "auto_reframe", "reframe_v2",
    "caption_position", "effects_ai", "scene_pick_mode", "manual_ranges",
    "resume", "voice_eq",
}


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower())[:40].strip("-")
    return s or "video"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _apply_output_format(cfg: Config, fmt: str) -> dict:
    """Set cfg.target_w/h for the chosen format and return the flags the job
    dict needs. Mirrors gui.generate()'s orientation handling exactly."""
    fmt = (fmt or "portrait").lower()
    faceless = fmt == "faceless"
    ai_image_short = fmt == "ai_image_short"
    no_source = faceless or ai_image_short
    if fmt in ("landscape", "faceless"):
        cfg.target_w, cfg.target_h = 1920, 1080
    else:  # portrait OR ai_image_short
        cfg.target_w, cfg.target_h = 1080, 1920
    return {"faceless": faceless, "ai_image_short": ai_image_short,
            "no_source": no_source}


def build_cfg(entry: dict, default_config: str) -> Config:
    """Load config.json and apply per-job cfg overrides (same fields the GUI
    can override per run)."""
    cfg = Config.load(Path(entry.get("config", default_config)))
    if entry.get("tts_language"):
        cfg.tts_language = str(entry["tts_language"]).lower()
    if entry.get("image_style"):
        cfg.image_style = str(entry["image_style"]).strip()
    if "use_claude_cli" in entry:
        cfg.use_claude_cli = bool(entry["use_claude_cli"])
    if entry.get("claude_cli_model"):
        cfg.claude_cli_model = str(entry["claude_cli_model"]).strip()
    # Arbitrary cfg attribute overrides for power users.
    for k, v in (entry.get("cfg_overrides") or {}).items():
        setattr(cfg, k, v)
    return cfg


def build_job(entry: dict, cfg: Config, fmt_flags: dict) -> dict:
    """Build the full run_one/run_multiclip job dict from a jobs.json entry."""
    topic = str(entry.get("topic") or entry.get("title") or "video").strip()
    job = dict(DEFAULT_JOB)
    job["slug"] = entry.get("slug") or slugify(topic)
    job["topic"] = topic

    no_source = fmt_flags["no_source"]
    # Format-derived flags, identical to the GUI.
    job["faceless_mode"] = bool(fmt_flags["faceless"] or fmt_flags["ai_image_short"])
    job["images_continuous"] = (bool(DEFAULT_JOB["images_continuous"])
                                or job["faceless_mode"])

    # Convenience passthrough keys.
    for k in _JOB_PASSTHROUGH:
        if k in entry:
            job[k] = entry[k]
    # Multiclip is meaningless without a gameplay source.
    job["multiclip_enabled"] = bool(job.get("multiclip_enabled")) and not no_source

    if entry.get("script"):
        job["script"] = str(entry["script"]).strip()
        job["extend_script"] = bool(entry.get("extend_script", False))
    if entry.get("image_prompts"):
        job["image_prompts"] = list(entry["image_prompts"])

    # Source: faceless/ai-image need none; otherwise URL or channel.
    if not no_source:
        if entry.get("source_url"):
            job["source_url"] = str(entry["source_url"]).strip()
        elif entry.get("channel_url"):
            job["channel_url"] = str(entry["channel_url"]).strip()
            kws = [k.strip() for k in str(entry.get("title_filter", "")).split(",") if k.strip()]
            if kws:
                job["title_filter"] = kws
            job["channel_scan_limit"] = int(entry.get("channel_scan_limit", 20))

    # Arbitrary job-field overrides (highest precedence).
    for k, v in (entry.get("overrides") or {}).items():
        job[k] = v

    # If we'll upload, make sure metadata is generated.
    if (entry.get("upload") or {}).get("enabled"):
        job["youtube_metadata"] = True
    return job


# ── YouTube upload ──────────────────────────────────────────────────────────
_YT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _client_id_secret(secret_path: Path):
    """Pull (client_id, client_secret) out of a Google OAuth client_secret.json
    (works for both 'installed' and 'web' client types)."""
    if not secret_path.is_file():
        return None, None
    try:
        data = json.loads(secret_path.read_text(encoding="utf-8-sig"))
        block = data.get("installed") or data.get("web") or data
        return block.get("client_id"), block.get("client_secret")
    except Exception:
        return None, None


def _resolve_upload_paths(upload_cfg: dict, accounts: dict, project_dir: Path):
    """Resolve (token_file, client_secret) for a job's upload, honouring the
    per-job `account` name. Convention: youtube_tokens/<account>.json + a shared
    client_secret.json, both overridable per account or per job."""
    accounts = accounts or {}
    account = upload_cfg.get("account")
    acc = accounts.get(account, {}) if account else {}
    token_file = Path(
        upload_cfg.get("token_file") or acc.get("token_file")
        or (project_dir / "youtube_tokens" / f"{account}.json" if account
            else project_dir / "youtube_token.json"))
    secret = Path(
        upload_cfg.get("client_secret") or acc.get("client_secret")
        or project_dir / "client_secret.json")
    # Relative paths (e.g. from the accounts map) resolve against the project
    # dir, not the current working dir — so it works under Task Scheduler too.
    if not token_file.is_absolute():
        token_file = project_dir / token_file
    if not secret.is_absolute():
        secret = project_dir / secret
    return token_file, secret


def _load_credentials(token_file: Path, secret_file: Path, log,
                      allow_interactive: bool = False):
    """Build valid Google credentials. Accepts BOTH token formats:
      - the library's `authorized_user` format (client_id/client_secret/refresh_token)
      - a raw OAuth token dump (access_token/refresh_token/scope) — the
        client_id/client_secret are then pulled from client_secret.json so the
        token can be refreshed for unattended runs.
    When no usable token exists it raises (so an unattended run NEVER blocks on a
    browser) unless allow_interactive=True (the `--auth` flag), which then does
    the one-time browser authorization. Re-saves refreshed creds for next time.

    Google libs are imported lazily per branch so the no-token error path works
    even when they aren't installed."""
    creds = None
    if token_file.is_file():
        from google.oauth2.credentials import Credentials
        try:
            raw = json.loads(token_file.read_text(encoding="utf-8-sig"))
        except Exception:
            raw = {}
        scopes = (raw.get("scope") or "").split() or raw.get("scopes") or _YT_SCOPES
        if raw.get("client_id") and raw.get("client_secret") and raw.get("refresh_token"):
            creds = Credentials.from_authorized_user_info(raw, scopes)
        elif raw.get("refresh_token") or raw.get("access_token") or raw.get("token"):
            cid, csec = _client_id_secret(secret_file)
            creds = Credentials(
                token=raw.get("token") or raw.get("access_token"),
                refresh_token=raw.get("refresh_token"),
                token_uri="https://oauth2.googleapis.com/token",
                client_id=cid, client_secret=csec, scopes=scopes)

    if creds is None:
        if not allow_interactive:
            raise RuntimeError(
                f"Kein gültiges Token gefunden: {token_file}. Lege die Token-Datei "
                "dorthin (siehe AUTOPILOT.md) ODER autorisiere diesen Account "
                "EINMALIG interaktiv: `start-autopilot.bat --auth`. (Unbeaufsichtigt "
                "wird KEIN Browser geöffnet, damit der Lauf nicht hängt.)")
        if not secret_file.is_file():
            raise RuntimeError(
                f"Kein Token ({token_file.name}) und keine {secret_file.name} zum "
                "Autorisieren gefunden. Siehe AUTOPILOT.md.")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(secret_file), _YT_SCOPES)
        log("      YouTube: Browser öffnet sich zum Autorisieren (einmalig)…")
        creds = flow.run_local_server(port=0)

    if not creds.valid:
        if creds.refresh_token and creds.client_id and creds.client_secret:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
        elif not creds.token:
            raise RuntimeError(
                f"Token {token_file.name} ist abgelaufen und nicht erneuerbar "
                "(client_id/client_secret fehlen). Lege die passende "
                "client_secret.json daneben (selbes Google-Projekt wie beim "
                "Erstellen der Tokens) oder autorisiere neu.")

    try:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json(), encoding="utf-8")
    except Exception:
        pass
    return creds


def _load_sidecar_metadata(video_path: Path, topic: str) -> dict:
    """Read the pipeline's `{video}.youtube.json` sidecar (title/description/
    tags). Falls back to a bare title=topic when the sidecar is missing."""
    side = video_path.with_name(video_path.name + ".youtube.json")
    if side.is_file():
        try:
            data = json.loads(side.read_text(encoding="utf-8-sig"))
            return {
                "title": (data.get("title") or topic or video_path.stem)[:100],
                "description": data.get("description") or "",
                "tags": [str(t) for t in (data.get("tags") or [])][:30],
            }
        except Exception:
            pass
    return {"title": (topic or video_path.stem)[:100], "description": "", "tags": []}


def upload_to_youtube(video_path: Path, upload_cfg: dict, topic: str,
                      project_dir: Path, accounts: dict = None,
                      allow_interactive: bool = False, on_step=None) -> str:
    """Upload `video_path` to YouTube via the Data API v3. Returns the video id.

    Multi-account: `upload_cfg["account"]` picks which token to use
    (youtube_tokens/<account>.json by convention). Auth handles pre-made tokens
    (any format) and refreshes them; only a first-time account with no token
    needs an interactive browser auth.

    Raises RuntimeError with an actionable message on missing libs / secrets so
    the caller can log it and move on (the video is still rendered on disk).
    """
    def log(m):
        (on_step or print)(m)

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        raise RuntimeError(
            "YouTube upload needs google libs. Install into your venv:\n"
            "  .venv\\Scripts\\python.exe -m pip install "
            "google-api-python-client google-auth-oauthlib")

    token_file, secret = _resolve_upload_paths(upload_cfg, accounts or {}, project_dir)
    acct = upload_cfg.get("account")
    log(f"      YouTube-Account: {acct or '(default)'} → {token_file.name}")
    creds = _load_credentials(token_file, secret, log,
                              allow_interactive=allow_interactive)

    meta = _load_sidecar_metadata(video_path, topic)
    privacy = str(upload_cfg.get("privacy", "private")).lower()
    if privacy not in ("private", "unlisted", "public"):
        privacy = "private"
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    if upload_cfg.get("publish_at"):
        # Scheduled publish requires privacyStatus=private + an RFC3339 time.
        status["privacyStatus"] = "private"
        status["publishAt"] = str(upload_cfg["publish_at"])

    body = {
        "snippet": {
            "title": meta["title"],
            "description": meta["description"],
            "tags": meta["tags"],
            "categoryId": str(upload_cfg.get("category_id", "20")),  # 20 = Gaming
        },
        "status": status,
    }

    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024,
                            resumable=True, mimetype="video/*")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    log(f"      YouTube-Upload: {video_path.name} ({privacy})…")
    response = None
    while response is None:
        chunk_status, response = req.next_chunk()
        if chunk_status:
            log(f"        … {int(chunk_status.progress() * 100)}%")
    vid = response.get("id", "")
    log(f"      ✓ hochgeladen: https://youtu.be/{vid}")

    playlist_id = upload_cfg.get("playlist_id")
    if playlist_id and vid:
        try:
            yt.playlistItems().insert(
                part="snippet",
                body={"snippet": {"playlistId": playlist_id,
                                  "resourceId": {"kind": "youtube#video",
                                                 "videoId": vid}}}).execute()
            log(f"      ✓ zur Playlist hinzugefügt")
        except Exception as e:
            log(f"      WARN: Playlist-Zuordnung fehlgeschlagen: {str(e)[:120]}")
    return vid


# ── Runner ──────────────────────────────────────────────────────────────────
def _state_path(jobs_path: Path) -> Path:
    return jobs_path.with_name("autopilot_state.json")


def _load_state(jobs_path: Path) -> dict:
    p = _state_path(jobs_path)
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return {"done": {}}


def _save_state(jobs_path: Path, state: dict) -> None:
    try:
        _state_path(jobs_path).write_text(
            json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"WARN: konnte state nicht schreiben: {e}")


def run_queue(jobs_path: Path, *, force: bool = False, do_upload: bool = True,
              allow_shutdown: bool = True, allow_interactive: bool = False) -> int:
    """Process every job in jobs.json. Returns the number of failed jobs."""
    data = json.loads(jobs_path.read_text(encoding="utf-8-sig"))
    default_config = data.get("config", "config.json")
    jobs = data.get("jobs", [])
    accounts = data.get("accounts", {})
    project_dir = jobs_path.resolve().parent
    state = _load_state(jobs_path)
    state.setdefault("done", {})

    print(f"[{_ts()}] Autopilot: {len(jobs)} Job(s) aus {jobs_path.name}")
    failures = 0

    for i, entry in enumerate(jobs):
        topic = str(entry.get("topic") or entry.get("title") or f"job-{i}").strip()
        key = str(entry.get("id") or f"{i}:{slugify(topic)}")
        if not force and state["done"].get(key, {}).get("status") == "done":
            print(f"[{_ts()}] ⏭  übersprungen (schon erledigt): {topic}")
            continue

        print(f"\n[{_ts()}] ▶ Job {i + 1}/{len(jobs)}: {topic}")
        rec = {"topic": topic, "started": _ts()}
        try:
            cfg = build_cfg(entry, default_config)
            fmt_flags = _apply_output_format(cfg, entry.get("output_format"))
            job = build_job(entry, cfg, fmt_flags)

            def step(m, _t=topic):
                print(f"   {m}")

            if job.get("multiclip_enabled"):
                outs = run_multiclip(job, cfg, on_step=step)
                videos = [Path(o) for o in (outs or [])]
            else:
                videos = [Path(run_one(job, cfg, on_step=step))]
            rec["videos"] = [str(v) for v in videos]
            print(f"[{_ts()}] ✓ gerendert: {len(videos)} Datei(en)")

            up = entry.get("upload") or {}
            rec["uploads"] = []
            if do_upload and up.get("enabled"):
                for v in videos:
                    if not v.is_file():
                        continue
                    try:
                        vid = upload_to_youtube(v, up, topic, project_dir,
                                                accounts=accounts,
                                                allow_interactive=allow_interactive,
                                                on_step=step)
                        rec["uploads"].append(vid)
                    except Exception as e:
                        print(f"[{_ts()}] ⚠ Upload fehlgeschlagen ({v.name}): {e}")
                        rec.setdefault("upload_errors", []).append(str(e)[:300])
            rec["status"] = "done"
            rec["finished"] = _ts()
        except Exception as e:
            failures += 1
            rec["status"] = "failed"
            rec["error"] = f"{type(e).__name__}: {e}"
            print(f"[{_ts()}] ✗ FEHLER bei '{topic}': {e}")
            traceback.print_exc()

        state["done"][key] = rec
        _save_state(jobs_path, state)

    ok = sum(1 for r in state["done"].values() if r.get("status") == "done")
    print(f"\n[{_ts()}] Fertig. {ok} erledigt, {failures} Fehler diese Runde.")

    if allow_shutdown and data.get("shutdown_when_done") and failures == 0:
        print(f"[{_ts()}] shutdown_when_done aktiv — PC fährt in 60s runter. "
              "Abbrechen: `shutdown /a`")
        try:
            subprocess.run(["shutdown", "/s", "/t", "60"], check=False)
        except Exception as e:
            print(f"WARN: shutdown-Befehl fehlgeschlagen: {e}")
    return failures


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Token-free batch renderer + YouTube uploader")
    ap.add_argument("jobs", nargs="?", default="autopilot.jobs.json", help="queue JSON file")
    ap.add_argument("--force", action="store_true", help="re-run jobs already marked done")
    ap.add_argument("--no-upload", action="store_true", help="render only, skip uploads")
    ap.add_argument("--no-shutdown", action="store_true", help="ignore shutdown_when_done")
    ap.add_argument("--auth", action="store_true",
                    help="allow one-time interactive browser auth for accounts "
                         "without a token (otherwise uploads never open a browser)")
    args = ap.parse_args(argv)

    jobs_path = Path(args.jobs)
    if not jobs_path.is_file():
        print(f"jobs-Datei nicht gefunden: {jobs_path.resolve()}")
        print("Lege eine an (Vorlage: autopilot.example.json) — siehe AUTOPILOT.md.")
        return 2
    return run_queue(jobs_path, force=args.force, do_upload=not args.no_upload,
                     allow_shutdown=not args.no_shutdown,
                     allow_interactive=args.auth)


if __name__ == "__main__":
    sys.exit(main())
