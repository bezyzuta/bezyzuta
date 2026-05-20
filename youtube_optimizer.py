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


def _try_gemini(topic: str, script: str, target_lang: str, cfg,
                log: Callable[[str], None]) -> dict | None:
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
    body = {
        "contents": [{"parts": [
            {"text": _PROMPT_INSTRUCTIONS + "\n\n" +
                     _build_user_prompt(topic, script, target_lang)},
        ]}],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 800,
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
                     log: Callable[[str], None]) -> dict | None:
    if not (getattr(cfg, "cloudflare_account_id", "") and
            getattr(cfg, "cloudflare_api_token", "")):
        return None
    import requests
    url = (
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{cfg.cloudflare_account_id}/ai/run/@cf/meta/llama-3.1-8b-instruct"
    )
    headers = {"Authorization": f"Bearer {cfg.cloudflare_api_token}"}
    body = {
        "messages": [
            {"role": "system", "content": _PROMPT_INSTRUCTIONS},
            {"role": "user",   "content": _build_user_prompt(topic, script, target_lang)},
        ],
        "max_tokens": 700,
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
    on_step: Callable[[str], None] | None = None,
) -> YouTubeMetadata:
    """Generate title / description / tags / thumbnail prompt for a short.

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

    for provider_name, fn in (
        ("gemini",     _try_gemini),
        ("cloudflare", _try_cloudflare),
    ):
        parsed = fn(topic, script, target_lang, cfg, log)
        if parsed:
            log(f"      youtube_optimizer: metadata via {provider_name}")
            return _coerce_metadata(parsed, topic, script)

    log("      youtube_optimizer: no LLM available, using template")
    return _template_metadata(topic, script)


# ────────────────── Thumbnail generation ──────────────────


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
