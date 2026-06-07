"""Generate YouTube metadata (title / description / tags / thumbnail) for a
rendered short.

Designed to be opt-in: nothing here runs unless `job["youtube_metadata"]` is
truthy. Produces a sidecar `.youtube.json` next to the final mp4 with all
fields ready to copy-paste into the YouTube upload flow (the actual API
upload requires OAuth and is intentionally out of scope here — see
`upload_to_youtube` for the stub).

Provider order:
  1. Gemini (cheap, high free-tier limit) — used for text metadata
  2. Cloudflare Llama 3.1 — text fallback
  3. Template — last-resort fallback so the pipeline never breaks the
     whole job over metadata generation

For thumbnails we reuse the existing image generators
(`fetch_image_from_cloudflare`, `fetch_image_from_pollinations`) so we don't
duplicate the API plumbing — they live in pipeline.py and are passed in.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# ────────────────── Metadata generation (text) ──────────────────


@dataclass
class YouTubeMetadata:
    title: str
    description: str
    tags: list[str]
    thumbnail_prompt: str
    thumbnail_path: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "thumbnail_prompt": self.thumbnail_prompt,
            "thumbnail_path": self.thumbnail_path,
            **self.extra,
        }


_PROMPT_INSTRUCTIONS = """Du bist YouTube-Shorts-Optimierer. Für das gegebene Skript und Thema
sollst du eine perfekte YouTube-Shorts-Veröffentlichung vorbereiten.

Antworte AUSSCHLIESSLICH mit gültigem JSON, OHNE Markdown-Codeblock,
in genau diesem Schema:

{
  "title": "...",            // 60-70 Zeichen optimal (Mobile schneidet ab ~70), 100 absolutes Max
  "description": "...",       // 1-3 Absätze, mit Hook-Satz oben, dann Kontext, dann Call-to-action
  "tags": ["...", "..."],    // 8-15 Tags, klein­geschrieben, kein # davor
  "thumbnail_prompt": "..."  // 1-2 Sätze, beschreibt das Thumbnail-Bild für ein Vertical-Format (9:16)
}

Wichtig:
- Schreibe alles auf Deutsch wenn das Skript Deutsch ist, sonst auf Englisch.
- Title MUSS unter 70 Zeichen bleiben — YouTube schneidet sonst ab.
- Description darf #Shorts, Emojis und 1-3 Hashtags enthalten.
- Tags sollen Roblox / Gaming / das konkrete Spiel / Themen-Keywords abdecken.
- thumbnail_prompt soll visuell, konkret, bildhaft sein (Personen-Action,
  helles Licht, knallige Farben — wirkt am besten für Shorts-Thumbnails)."""


_PROMPT_INSTRUCTIONS_LONG_PORTRAIT = """Du bist YouTube-Optimierer fuer Lang-Videos (>1 min, Hochformat).
Bereite eine SEO-starke Veroeffentlichung vor — kein Shorts-Stil.

Antworte AUSSCHLIESSLICH mit gueltigem JSON, OHNE Markdown-Codeblock,
in genau diesem Schema:

{
  "title": "...",            // 50-70 Zeichen, informativ + suchbar (KEIN Clickbait-Spam)
  "description": "...",       // 3-6 Absaetze: Hook → Kontext → Was passiert im Video → CTA → Hashtags
  "tags": ["...", "..."],    // 10-15 Tags, kleingeschrieben, kein # davor
  "thumbnail_prompt": "..."  // 1-2 Saetze, fuer 9:16 Hochformat
}

Wichtig:
- Sprache: deutsch wenn Skript deutsch ist, sonst englisch.
- KEIN '#Shorts' — das ist ein langes Video.
- Description soll YouTube-SEO bedienen: relevante Keywords im ersten Absatz,
  dann ausfuehrlichere Beschreibung, am Ende 3-5 Hashtags + Abonnier-CTA.
- thumbnail_prompt fuer 9:16, dramatische Beleuchtung, klare Subjekt-Trennung."""


_PROMPT_INSTRUCTIONS_LONG_LANDSCAPE = """Du bist YouTube-Optimierer fuer normale Lang-Videos (Querformat).
Bereite eine SEO-starke Veroeffentlichung vor.

Antworte AUSSCHLIESSLICH mit gueltigem JSON, OHNE Markdown-Codeblock,
in genau diesem Schema:

{
  "title": "...",            // 50-70 Zeichen, informativ + suchbar (KEIN Clickbait-Spam)
  "description": "...",       // 3-6 Absaetze: Hook → Kontext → Was passiert im Video → CTA → Hashtags
  "tags": ["...", "..."],    // 10-15 Tags, kleingeschrieben, kein # davor
  "thumbnail_prompt": "..."  // 1-2 Saetze, fuer 16:9 Querformat-Thumbnail
}

Wichtig:
- Sprache: deutsch wenn Skript deutsch ist, sonst englisch.
- KEIN '#Shorts' — das ist ein langes Video im Querformat.
- Description soll YouTube-SEO bedienen: relevante Keywords im ersten Absatz,
  dann ausfuehrlichere Beschreibung, am Ende 3-5 Hashtags + Abonnier-CTA.
- thumbnail_prompt fuer 16:9, kinematische Beleuchtung, klare Hauptperson/Action,
  knallige Farben, im Stil von Roblox-/Gaming-Lang-Video-Thumbnails."""


_CHAPTER_PROMPT_DE = """Teile dieses YouTube-Skript in 4-8 Kapitel auf. Antworte AUSSCHLIESSLICH mit gueltigem JSON, OHNE Markdown:

[
  {{"title": "Intro", "position": 0.0}},
  {{"title": "Erstes Highlight", "position": 0.12}},
  ...
]

Regeln:
- Das erste Kapitel MUSS position=0.0 haben.
- position ist ein Wert 0.0..1.0, der Anteil am Skript wo das Kapitel beginnt.
- Kapitel-Titel: 2-5 Woerter, knackig, kein Punkt am Ende.
- Jedes Kapitel sollte deutlich vom naechsten getrennt sein (mind. ~30 Sekunden Abstand).
- Output: NUR der JSON-Array, sonst nichts.

Skript:
---
{script}
---"""


_CHAPTER_PROMPT_EN = """Split this YouTube script into 4-8 chapters. Reply ONLY with valid JSON, NO markdown:

[
  {{"title": "Intro", "position": 0.0}},
  {{"title": "First highlight", "position": 0.12}},
  ...
]

Rules:
- The first chapter MUST have position=0.0.
- position is a value 0.0..1.0 — the fraction of the script where the chapter starts.
- Chapter titles: 2-5 words, punchy, no trailing period.
- Each chapter should be well separated from the next (at least ~30 seconds apart).
- Output: ONLY the JSON array, nothing else.

Script:
---
{script}
---"""


def _format_chapter_timestamp(seconds: float) -> str:
    """Format a chapter timestamp the way YouTube expects: M:SS for <1h,
    H:MM:SS for ≥1h. YouTube refuses chapters where the first stamp isn't
    exactly '0:00' so always emit the minute-second form there."""
    secs = max(0, int(seconds))
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def generate_chapters(script: str, total_seconds: float, cfg,
                      target_lang: str = "auto",
                      on_step: Callable[[str], None] | None = None) -> str:
    """Ask Gemini for 4-8 chapter markers, return them as a YouTube-ready
    block ('0:00 Intro\\n1:30 ...'). Empty string on any failure — chapters
    are nice-to-have, the pipeline shouldn't fail without them.

    YouTube chapter rules: first stamp must be 0:00, ≥3 stamps, each
    chapter ≥10s long, ascending order. We post-process the model's
    output to enforce all of these."""
    def log(msg: str) -> None:
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    if not script.strip() or total_seconds < 90 or not getattr(cfg, "gemini_api_key", ""):
        return ""

    try:
        from pipeline import _gemini_post  # type: ignore
    except Exception:
        return ""

    # Pick prompt language from the same auto/de/en knob the metadata uses.
    lang = (target_lang or "auto").lower()
    if lang == "auto":
        # Cheap detection: umlauts → DE.
        lang = "de" if any(c in script.lower() for c in "äöüß") else "en"
    template = _CHAPTER_PROMPT_DE if lang == "de" else _CHAPTER_PROMPT_EN
    prompt_text = template.format(script=script[:8000])  # cap to fit context

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{cfg.gemini_model}:generateContent")
    body = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": 0.4,
            "maxOutputTokens": 1024,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        data = _gemini_post(url, {"key": cfg.gemini_api_key}, body, retries=2)
    except Exception as e:
        log(f"      chapters: gemini failed ({str(e)[:120]})")
        return ""

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        return ""

    # Loose JSON parse — Gemini sometimes wraps in ```json ... ```.
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        parsed = json.loads(raw)
    except Exception:
        log(f"      chapters: JSON parse failed, skipping")
        return ""
    if not isinstance(parsed, list) or len(parsed) < 3:
        return ""

    # Convert position → seconds → timestamp, enforce YouTube's rules.
    rows: list[tuple[float, str]] = []
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title", "")).strip().rstrip(".").rstrip(":")
        try:
            pos = float(entry.get("position", -1))
        except (TypeError, ValueError):
            continue
        if not (0.0 <= pos <= 1.0) or not title:
            continue
        rows.append((pos * total_seconds, title[:80]))

    if len(rows) < 3:
        return ""
    rows.sort(key=lambda x: x[0])
    # First chapter must be 0:00 exactly.
    rows[0] = (0.0, rows[0][1])
    # Enforce ≥10s gap between chapters; drop too-close ones.
    cleaned: list[tuple[float, str]] = []
    for ts, title in rows:
        if cleaned and ts - cleaned[-1][0] < 10:
            continue
        cleaned.append((ts, title))
    if len(cleaned) < 3:
        return ""

    block = "\n".join(f"{_format_chapter_timestamp(ts)} {title}" for ts, title in cleaned)
    log(f"      chapters: {len(cleaned)} markers")
    return block


def _build_user_prompt(topic: str, script: str, target_lang: str = "auto") -> str:
    lang_hint = ""
    if target_lang and target_lang != "auto":
        lang_hint = f"\n\nSprache: {target_lang}."
    return (
        f"Thema: {topic or '(kein Thema angegeben)'}\n\n"
        f"Skript:\n{script.strip()[:2400]}"
        f"{lang_hint}"
    )


def _parse_json_loose(text: str) -> dict | None:
    """Extract the first {...} block from `text` and parse it. Gemini and
    Llama both sometimes wrap JSON in ```json fences or add a leading
    comment line."""
    if not text:
        return None
    # Strip code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(),
                     flags=re.IGNORECASE | re.MULTILINE)
    # Find the outermost {...}
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    blob = cleaned[start:end + 1]
    try:
        return json.loads(blob)
    except Exception:
        # Last-ditch: remove trailing commas
        try:
            return json.loads(re.sub(r",(\s*[}\]])", r"\1", blob))
        except Exception:
            return None


def _coerce_metadata(parsed: dict, topic: str, script: str) -> YouTubeMetadata:
    """Coerce a maybe-shaped dict into a clean YouTubeMetadata."""
    title = str(parsed.get("title") or topic or "Neuer Short").strip()
    # YouTube's API rejects titles > 100 chars; clamp as a safety net even
    # though we ask the LLM for ~70 (mobile starts truncating around there).
    if len(title) > 100:
        title = title[:97] + "..."
    desc_raw = parsed.get("description") or ""
    if isinstance(desc_raw, list):
        desc_raw = "\n\n".join(str(x) for x in desc_raw)
    description = str(desc_raw).strip()
    if not description:
        description = (script[:300] + ("..." if len(script) > 300 else ""))

    raw_tags = parsed.get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = [t.strip() for t in re.split(r"[,;\n]+", raw_tags)]
    tags: list[str] = []
    seen: set[str] = set()
    for t in raw_tags:
        t = str(t).strip().lstrip("#").lower()
        if t and t not in seen and len(t) <= 40:
            seen.add(t)
            tags.append(t)
        if len(tags) >= 15:
            break

    thumb = str(parsed.get("thumbnail_prompt") or "").strip()
    if not thumb:
        thumb = _template_thumbnail_prompt(topic, script)

    # Ensure #Shorts is present somewhere — it noticeably helps the algo.
    if "#shorts" not in description.lower():
        description = description.rstrip() + "\n\n#Shorts"

    return YouTubeMetadata(
        title=title,
        description=description,
        tags=tags or _template_tags(topic),
        thumbnail_prompt=thumb,
    )


# ── Provider implementations ──


def _pick_instructions(target_seconds: float, orientation: str) -> str:
    """Choose the right system prompt for this video's format. Long-form
    gets a SEO-heavier instruction set with no '#Shorts'; orientation
    decides whether the thumbnail prompt should aim 9:16 or 16:9."""
    if target_seconds >= 90:
        if (orientation or "portrait").lower() == "landscape":
            return _PROMPT_INSTRUCTIONS_LONG_LANDSCAPE
        return _PROMPT_INSTRUCTIONS_LONG_PORTRAIT
    return _PROMPT_INSTRUCTIONS


def _try_gemini(topic: str, script: str, target_lang: str, cfg,
                log: Callable[[str], None],
                target_seconds: float = 0.0,
                orientation: str = "portrait") -> dict | None:
    if not getattr(cfg, "gemini_api_key", ""):
        return None
    # Imported lazily so the module is importable even if pipeline.py changes.
    try:
        from pipeline import _gemini_post  # type: ignore
    except Exception as e:
        log(f"      youtube_optimizer: gemini import failed: {e}")
        return None
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{cfg.gemini_model}:generateContent"
    )
    instructions = _pick_instructions(target_seconds, orientation)
    body = {
        "contents": [{"parts": [
            {"text": instructions + "\n\n" +
                     _build_user_prompt(topic, script, target_lang)},
        ]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 1200 if target_seconds >= 90 else 800,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    try:
        data = _gemini_post(url, {"key": cfg.gemini_api_key}, body, retries=2)
    except Exception as e:
        log(f"      youtube_optimizer: gemini failed: {str(e)[:200]}")
        return None
    try:
        cand = data["candidates"][0]
        parts = cand.get("content", {}).get("parts", []) or []
        text = "\n".join(p.get("text", "") for p in parts
                         if not p.get("thought")).strip()
    except Exception as e:
        log(f"      youtube_optimizer: gemini parse failed: {e}")
        return None
    return _parse_json_loose(text)


def _try_cloudflare(topic: str, script: str, target_lang: str, cfg,
                     log: Callable[[str], None],
                     target_seconds: float = 0.0,
                     orientation: str = "portrait") -> dict | None:
    if not (getattr(cfg, "cloudflare_account_id", "") and
            getattr(cfg, "cloudflare_api_token", "")):
        return None
    import requests
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{cfg.cloudflare_account_id}/ai/run/@cf/meta/llama-3.1-8b-instruct"
    )
    headers = {"Authorization": f"Bearer {cfg.cloudflare_api_token}"}
    instructions = _pick_instructions(target_seconds, orientation)
    body = {
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user",   "content": _build_user_prompt(topic, script, target_lang)},
        ],
        "max_tokens": 1000 if target_seconds >= 90 else 700,
        "temperature": 0.7,
    }
    try:
        r = requests.post(url, headers=headers, json=body, timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        log(f"      youtube_optimizer: cloudflare failed: {str(e)[:200]}")
        return None
    try:
        text = (data.get("result", {}) or {}).get("response", "")
    except Exception:
        return None
    return _parse_json_loose(text)


def _template_tags(topic: str) -> list[str]:
    base = ["shorts", "roblox", "gaming", "viral", "fyp", "trending"]
    if topic:
        for word in re.split(r"\W+", topic.lower()):
            if 3 <= len(word) <= 20 and word not in base:
                base.append(word)
            if len(base) >= 12:
                break
    return base


def _template_thumbnail_prompt(topic: str, script: str) -> str:
    seed = topic or script[:80] or "Roblox action"
    return (
        f"vertical 9:16 youtube short thumbnail, dramatic cartoon style, "
        f"bright neon colors, action scene about: {seed[:100]}, "
        f"surprised character expression, bold contrast, eye-catching"
    )


def _template_metadata(topic: str, script: str) -> YouTubeMetadata:
    """Last-resort fallback when both LLMs are unavailable. Builds something
    posting-ready from just the topic + first script line."""
    first_line = next((ln.strip() for ln in script.splitlines()
                       if ln.strip()), topic or "Neuer Roblox Short")
    title = (topic[:60].strip() or first_line[:60]).rstrip(".!? ") or "Neuer Short"
    description = (
        f"{first_line[:200]}\n\n"
        f"#Shorts #Roblox #Gaming"
    )
    return YouTubeMetadata(
        title=title,
        description=description,
        tags=_template_tags(topic),
        thumbnail_prompt=_template_thumbnail_prompt(topic, script),
    )


def generate_youtube_metadata(
    topic: str,
    script: str,
    cfg,
    *,
    target_lang: str = "auto",
    target_seconds: float = 0.0,
    orientation: str = "portrait",
    on_step: Callable[[str], None] | None = None,
) -> YouTubeMetadata:
    """Generate title / description / tags / thumbnail prompt.

    `target_seconds` ≥90 → long-form prompts (no '#Shorts', SEO-heavier
    description), and chapter markers get prepended to the description.
    `orientation` switches the thumbnail prompt between 9:16 and 16:9.

    Always returns a populated `YouTubeMetadata` — falls back to a template
    if both Gemini and Cloudflare are unavailable so the pipeline never
    fails the whole job over metadata.
    """
    def log(msg: str) -> None:
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    topic = (topic or "").strip()
    script = (script or "").strip()

    meta: YouTubeMetadata | None = None
    for provider_name, fn in (
        ("gemini",     _try_gemini),
        ("cloudflare", _try_cloudflare),
    ):
        parsed = fn(topic, script, target_lang, cfg, log,
                    target_seconds=target_seconds, orientation=orientation)
        if parsed:
            log(f"      youtube_optimizer: metadata via {provider_name}")
            meta = _coerce_metadata(parsed, topic, script)
            break
    if meta is None:
        log("      youtube_optimizer: no LLM available, using template")
        meta = _template_metadata(topic, script)

    # Chapter markers: long-form videos (≥90s) get a YouTube-parseable
    # timestamp block prepended to the description. The chapter call is
    # opt-in/no-op for short videos and silently no-ops on any error.
    if target_seconds >= 90:
        chapters = generate_chapters(script, target_seconds, cfg,
                                     target_lang=target_lang, on_step=on_step)
        if chapters:
            meta.description = chapters + "\n\n" + meta.description
    return meta


# ────────────────── Thumbnail generation ──────────────────


def generate_thumbnail_from_video(
    video_path: Path,
    hook_text: str,
    out_path: Path,
    *,
    on_step: Callable[[str], None] | None = None,
) -> Path | None:
    """Build a YouTube thumbnail from the FINISHED video: pick a strong
    frame from the first half (action / motion), then paint `hook_text` in
    big yellow with a thick black outline on top — exactly the typical
    Roblox-YouTube thumbnail style. Falls back gracefully if Pillow or
    ffmpeg are missing.

    Picks the frame with the highest pixel-variance (proxy for "interesting
    content, not a blank fade") among 8 candidates between 5%-55% of the
    video length, so the thumbnail isn't a black intro frame and isn't from
    the subscribe-banner outro.
    """
    def log(msg: str) -> None:
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageStat
    except Exception as e:
        log(f"      thumb-from-video: Pillow missing ({e})")
        return None

    import subprocess as _sp, tempfile, shutil
    dur_proc = _sp.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video_path)],
        capture_output=True, text=True,
    )
    try:
        dur = float((dur_proc.stdout or "0").strip())
    except ValueError:
        dur = 0.0
    if dur < 1.0:
        log("      thumb-from-video: video too short / unreadable duration")
        return None

    tmp = Path(tempfile.mkdtemp(prefix="thumb_"))
    try:
        candidates: list[tuple[float, Path]] = []
        for i in range(8):
            t = dur * (0.05 + 0.5 * (i / 7.0))
            fp = tmp / f"f{i}.jpg"
            r = _sp.run(["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{t:.2f}",
                         "-i", str(video_path), "-frames:v", "1", "-q:v", "3",
                         str(fp)], capture_output=True)
            if r.returncode == 0 and fp.is_file() and fp.stat().st_size > 1024:
                try:
                    stat = ImageStat.Stat(Image.open(fp).convert("L"))
                    candidates.append((stat.stddev[0], fp))
                except Exception:
                    pass
        if not candidates:
            log("      thumb-from-video: no usable frames")
            return None
        # Highest stddev = most visual variety. Beats picking a flat frame.
        candidates.sort(key=lambda x: -x[0])
        best = candidates[0][1]

        im = Image.open(best).convert("RGB")
        W, H = im.size
        # Slight punch: contrast + saturation boost, like the viral grading.
        from PIL import ImageEnhance
        im = ImageEnhance.Contrast(im).enhance(1.12)
        im = ImageEnhance.Color(im).enhance(1.25)
        # Add a subtle dark bottom gradient so text stays readable on busy
        # backgrounds — drawn as a stack of overlay strips.
        ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        odraw = ImageDraw.Draw(ov)
        for k in range(int(H * 0.45), H):
            a = int(180 * ((k - H * 0.45) / (H * 0.55)))
            odraw.line([(0, k), (W, k)], fill=(0, 0, 0, min(200, a)))
        im = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")

        # Find a system font; fall back to default (small) if none.
        font_candidates = [
            r"C:\Windows\Fonts\impact.ttf",
            r"C:\Windows\Fonts\arialbd.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Supplemental/Impact.ttf",
        ]
        font_path = next((p for p in font_candidates if Path(p).is_file()), None)
        text = (hook_text or "WATCH THIS").strip().upper()
        # Wrap to ~2 lines max so very long hooks don't run off the edge.
        words = text.split()
        max_chars = max(8, int(W / 50))
        lines: list[str] = []
        cur = ""
        for w in words:
            if len(cur) + 1 + len(w) <= max_chars:
                cur = (cur + " " + w).strip()
            else:
                if cur:
                    lines.append(cur)
                cur = w
            if len(lines) == 2:
                break
        if cur and len(lines) < 2:
            lines.append(cur)
        # Pick the biggest font size that fits.
        draw = ImageDraw.Draw(im)
        size = max(40, int(W * 0.18))
        while size > 20:
            try:
                font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()
            widths = [draw.textlength(l, font=font) for l in lines]
            if max(widths) <= W * 0.92:
                break
            size -= 6
        # Position toward the bottom-center, with breathing room.
        line_h = int(size * 1.15)
        total_h = line_h * len(lines)
        y0 = int(H * 0.7) - total_h // 2
        stroke_w = max(6, int(size * 0.10))
        for i, ln in enumerate(lines):
            tw = draw.textlength(ln, font=font)
            x = (W - tw) // 2
            y = y0 + i * line_h
            draw.text((x, y), ln, font=font, fill=(255, 230, 0),
                      stroke_width=stroke_w, stroke_fill=(0, 0, 0))

        im.save(out_path, quality=92)
        log(f"      thumb-from-video: {out_path.name} (frame stddev={candidates[0][0]:.0f})")
        return out_path
    finally:
        try: shutil.rmtree(tmp, ignore_errors=True)
        except Exception: pass


def generate_thumbnail(
    meta: YouTubeMetadata,
    out_path: Path,
    cfg,
    *,
    on_step: Callable[[str], None] | None = None,
) -> Path | None:
    """Render a 9:16 thumbnail image from `meta.thumbnail_prompt`. Returns
    the output path on success, None if all providers fail.

    Reuses the same Cloudflare-Flux → Pollinations cascade that pipeline.py
    uses for scene images, so we don't fork the API code.
    """
    def log(msg: str) -> None:
        if on_step:
            try: on_step(msg)
            except Exception: pass
        else:
            print(msg)

    try:
        from pipeline import (
            fetch_image_from_cloudflare, fetch_image_from_pollinations
        )
    except Exception as e:
        log(f"      thumbnail: image generators unavailable: {e}")
        return None

    prompt = meta.thumbnail_prompt.strip()
    if not prompt:
        log("      thumbnail: no prompt, skipping")
        return None

    cf_ok = bool(getattr(cfg, "cloudflare_account_id", "") and
                 getattr(cfg, "cloudflare_api_token", ""))
    if cf_ok:
        try:
            fetch_image_from_cloudflare(
                prompt, out_path, cfg,
                seed=random.randint(1, 1_000_000),
            )
            meta.thumbnail_path = str(out_path)
            log(f"      thumbnail: cloudflare flux -> {out_path.name}")
            return out_path
        except Exception as e:
            log(f"      thumbnail: cloudflare failed ({str(e)[:160]})")

    try:
        fetch_image_from_pollinations(
            prompt, out_path, seed=random.randint(1, 1_000_000)
        )
        meta.thumbnail_path = str(out_path)
        log(f"      thumbnail: pollinations -> {out_path.name}")
        return out_path
    except Exception as e:
        log(f"      thumbnail: pollinations failed ({str(e)[:160]})")
        return None


# ────────────────── Sidecar IO + Upload stub ──────────────────


def write_metadata_sidecars(meta: YouTubeMetadata, video_path: Path) -> tuple[Path, Path]:
    """Write `{video}.youtube.json` (machine-readable) and `{video}.youtube.txt`
    (copy-pasteable). Returns (json_path, txt_path)."""
    base = video_path.with_suffix("")
    json_path = base.with_name(base.name + ".youtube.json")
    txt_path = base.with_name(base.name + ".youtube.txt")
    json_path.write_text(
        json.dumps(meta.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    txt = (
        f"=== TITLE ({len(meta.title)}/100) ===\n{meta.title}\n\n"
        f"=== DESCRIPTION ===\n{meta.description}\n\n"
        f"=== TAGS ({len(meta.tags)}) ===\n{', '.join(meta.tags)}\n\n"
        f"=== THUMBNAIL PROMPT ===\n{meta.thumbnail_prompt}\n"
    )
    if meta.thumbnail_path:
        txt += f"\n=== THUMBNAIL FILE ===\n{meta.thumbnail_path}\n"
    txt_path.write_text(txt, encoding="utf-8")
    return (json_path, txt_path)


def upload_to_youtube(
    video_path: Path,
    meta: YouTubeMetadata,
    *,
    oauth_secrets_file: Path | str | None = None,
    category_id: str = "20",       # 20 = Gaming
    privacy_status: str = "private",
    publish_at: str | None = None,  # ISO-8601 UTC, schedule
) -> str:
    """Upload a finished short to YouTube via the Data API v3.

    Requires `google-auth`, `google-auth-oauthlib`, and
    `google-api-python-client` to be installed, plus a Google Cloud OAuth
    client secrets JSON. Returns the new video URL.

    If the libs aren't installed, raises RuntimeError with the pip command
    so the user can fix it without diving into the source.
    """
    try:
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        from googleapiclient.http import MediaFileUpload  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "YouTube upload requires extra packages. Install with:\n"
            "  .venv\\Scripts\\python.exe -m pip install "
            "google-auth google-auth-oauthlib google-api-python-client\n"
            f"(missing: {e.name})"
        ) from e

    if not oauth_secrets_file:
        raise RuntimeError(
            "YouTube upload needs an OAuth client_secrets.json. Create one at "
            "https://console.cloud.google.com → APIs & Services → Credentials "
            "→ OAuth client ID → Desktop application, then download the JSON."
        )

    secrets_path = Path(oauth_secrets_file).expanduser()
    if not secrets_path.is_file():
        raise RuntimeError(f"OAuth secrets file not found: {secrets_path}")

    # Cache the user token next to the secrets so we don't re-prompt every run.
    token_path = secrets_path.with_name(secrets_path.stem + ".token.json")
    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None
    if token_path.is_file():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        except Exception:
            creds = None
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes)
        creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    yt = build("youtube", "v3", credentials=creds)
    snippet = {
        "title": meta.title,
        "description": meta.description,
        "tags": meta.tags,
        "categoryId": category_id,
    }
    status = {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False}
    if publish_at:
        status["publishAt"] = publish_at
        status["privacyStatus"] = "private"

    media = MediaFileUpload(str(video_path), chunksize=-1,
                            resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(
        part="snippet,status",
        body={"snippet": snippet, "status": status},
        media_body=media,
    )
    response = None
    while response is None:
        _status, response = req.next_chunk()
    video_id = response["id"]
    url = f"https://youtu.be/{video_id}"

    # If we generated a thumbnail, attach it.
    if meta.thumbnail_path and Path(meta.thumbnail_path).is_file():
        try:
            yt.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(meta.thumbnail_path, mimetype="image/png"),
            ).execute()
        except Exception:
            pass
    return url
