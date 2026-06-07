"""Google Flow (Veo) integration — two phases, because Flow has no API.

Flow's free subscription credits are only reachable through its website, so we
DON'T try to drive it. Instead:

  PHASE 1  export   — the pipeline generates script + voiceover + per-beat START
                      images + image-to-video prompts, packaged into
                      <slug>_flow_export/. You feed the images/prompts into a
                      Flow automation extension (Veo image-to-video) and
                      bulk-download the clips.
  PHASE 2  assemble — hand the downloaded clips back; we stitch the final
                      landscape video reusing the EXACT same voiceover + adding
                      captions/effects (clips become the per-beat visuals).

Both phases reuse pipeline.run_one, so the look matches the normal output.

CLI:
    python flow_clips.py export   entry.json [--config config.json]
    python flow_clips.py assemble <export_dir> <clips_dir>

`entry.json` is one job in the SAME shape as an autopilot job, e.g.:
    { "topic": "Roblox Horror Story ...", "output_format": "faceless",
      "tts_language": "de" }
"""

import argparse
import json
import re
import sys
from pathlib import Path

import autopilot
from pipeline import Config, run_one


_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _natural_key(name: str):
    """Sort key so beat_2.mp4 < beat_10.mp4 (numbers compared as numbers)."""
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", name)]


def match_clips(clips_dir: Path, n_beats: int, on_step=None) -> list:
    """Natural-sorted list of video files in clips_dir. Order == beat order.
    Warns (does not fail) when the count differs from the expected beats."""
    log = on_step or print
    clips = sorted(
        (p for p in Path(clips_dir).iterdir()
         if p.is_file() and p.suffix.lower() in _VIDEO_EXTS),
        key=lambda p: _natural_key(p.name))
    if not clips:
        raise RuntimeError(f"keine Video-Clips in {clips_dir} gefunden "
                           f"(erwartet {_VIDEO_EXTS})")
    if n_beats and len(clips) != n_beats:
        log(f"      WARN: {len(clips)} Clips, aber {n_beats} Beats erwartet — "
            "werden trotzdem über die Voiceover-Länge verteilt.")
    return clips


# ── Phase 1: export ──────────────────────────────────────────────────────────
def export_for_flow(entry: dict, on_step=None) -> Path:
    """Generate the start images + prompts + voice for a Flow run. Returns the
    export directory."""
    log = on_step or print
    cfg = autopilot.build_cfg(entry, entry.get("config", "config.json"))
    fmt = entry.get("output_format") or "faceless"
    fmt_flags = autopilot._apply_output_format(cfg, fmt)
    job = autopilot.build_job(entry, cfg, fmt_flags)

    export_dir = Path(entry.get("flow_export_dir")
                      or Path(cfg.output_dir).expanduser() / f"{job['slug']}_flow_export")
    job["flow_export_dir"] = str(export_dir)
    job["_flow_config_path"] = entry.get("config", "config.json")
    log(f"[flow] export → {export_dir}")
    return Path(run_one(job, cfg, on_step=on_step))


# ── Phase 2: assemble ────────────────────────────────────────────────────────
def assemble_from_flow(export_dir: Path, clips_dir: Path, on_step=None) -> Path:
    """Stitch the final video from the Flow clips + the exported voiceover."""
    log = on_step or print
    export_dir = Path(export_dir)
    manifest = json.loads((export_dir / "beats.json").read_text(encoding="utf-8-sig"))

    voice = export_dir / (manifest.get("voice") or "voice.mp3")
    if not voice.is_file():
        raise RuntimeError(f"voice.mp3 fehlt im Export: {voice}")
    clips = match_clips(clips_dir, int(manifest.get("n_beats", 0)), on_step=log)

    cfg = Config.load(Path(manifest.get("config_path", "config.json")))
    cfg.target_w = int(manifest.get("target_w", cfg.target_w))
    cfg.target_h = int(manifest.get("target_h", cfg.target_h))
    if manifest.get("tts_language"):
        cfg.tts_language = manifest["tts_language"]
    if manifest.get("image_style"):
        cfg.image_style = manifest["image_style"]

    job = dict(manifest.get("job") or {})
    job["image_paths"] = [str(c) for c in clips]   # clips are the per-beat visuals
    job["voice_path"] = str(voice)                 # reuse the exact export voice
    job["images_continuous"] = True                # one clip per beat, back-to-back
    job["enable_voice"] = True                     # transcribe voice → captions
    job["no_image"] = False
    for k in ("flow_export_dir", "_flow_config_path", "image_prompts", "image_path"):
        job.pop(k, None)

    log(f"[flow] assemble: {len(clips)} Clips + {voice.name} → {manifest.get('slug')}")
    return Path(run_one(job, cfg, on_step=on_step))


# ── CLI ──────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Google Flow (Veo) export/assemble")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("export", help="generate start images + prompts + voice")
    pe.add_argument("entry", help="JSON file describing one job (like an autopilot job)")
    pe.add_argument("--config", default=None, help="override config.json path")

    pa = sub.add_parser("assemble", help="stitch final video from Flow clips")
    pa.add_argument("export_dir", help="the <slug>_flow_export folder")
    pa.add_argument("clips_dir", help="folder with the downloaded Flow clips")

    args = ap.parse_args(argv)
    if args.cmd == "export":
        p = Path(args.entry)
        if not p.is_file():
            print(f"entry-Datei nicht gefunden: {p}")
            return 2
        entry = json.loads(p.read_text(encoding="utf-8-sig"))
        if args.config:
            entry["config"] = args.config
        out = export_for_flow(entry)
        print(f"\nFertig. Export: {out}\n"
              "→ Bilder + prompts.txt in deine Flow-Extension, Clips runterladen,\n"
              f"  dann: python flow_clips.py assemble \"{out}\" \"<clips-Ordner>\"")
        return 0
    if args.cmd == "assemble":
        out = assemble_from_flow(Path(args.export_dir), Path(args.clips_dir))
        print(f"\nFertig. Video: {out}")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
