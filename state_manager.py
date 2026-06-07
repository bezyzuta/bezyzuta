"""Job state + checkpoint-based resume for the shorts pipeline.

A job's state lives in `{work_dir}/job_state.json` and tracks which pipeline
steps have completed plus the artifacts each step produced. On the next run
with the same slug, completed steps are skipped and their cached artifacts
are loaded back into local variables.

This module is opt-in: nothing happens unless the job dict carries
`"resume": True`. When disabled, the existing pipeline behavior is unchanged.

Also exposes a small leveled Logger that wraps the pipeline's existing
`step()` callback (kept compatible — the GUI still receives every line),
adding level tags and timestamps so console output is grepable.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


STATE_FILE_NAME = "job_state.json"
STATE_VERSION = 1


# ────────────────────────────── Logger ──────────────────────────────


class Logger:
    """Thin wrapper around the pipeline's step callback. Adds level tags,
    timestamps, and (optional) ANSI color when stdout is a TTY.

    The pipeline calls `step(msg)` everywhere; we keep that API but feed it
    formatted lines like `[12:43:01 WARN ] image gen failed: ...`.
    """

    LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
    _COLORS = {
        "DEBUG": "\x1b[90m",   # grey
        "INFO":  "",           # default
        "WARN":  "\x1b[33m",   # yellow
        "ERROR": "\x1b[31m",   # red
    }
    _RESET = "\x1b[0m"

    def __init__(
        self,
        step_cb: Callable[[str], None] | None = None,
        level: str = "INFO",
        color: bool | None = None,
        timestamps: bool = True,
    ) -> None:
        self._step = step_cb
        self.level = self.LEVELS.get(level.upper(), 20)
        self.timestamps = timestamps
        if color is None:
            color = bool(getattr(sys.stdout, "isatty", lambda: False)())
        self.color = color

    def _emit(self, level: str, msg: str) -> None:
        if self.LEVELS[level] < self.level:
            return
        ts = time.strftime("%H:%M:%S") + " " if self.timestamps else ""
        tag = f"[{ts}{level:<5}]"
        if self.color and self._COLORS.get(level):
            tag = f"{self._COLORS[level]}{tag}{self._RESET}"
        line = f"{tag} {msg}"
        if self._step is not None:
            try:
                self._step(line)
                return
            except Exception:
                pass
        print(line)

    def debug(self, msg: str) -> None: self._emit("DEBUG", msg)
    def info(self,  msg: str) -> None: self._emit("INFO",  msg)
    def warn(self,  msg: str) -> None: self._emit("WARN",  msg)
    def error(self, msg: str) -> None: self._emit("ERROR", msg)

    # Allow logger to be used as a drop-in `step()` callback (no level tag,
    # caller already formatted the string — typically the existing pipeline
    # `step("[3/5] ...")` lines we want to preserve verbatim).
    def __call__(self, msg: str) -> None:
        if self._step is not None:
            try:
                self._step(msg)
                return
            except Exception:
                pass
        print(msg)


# ─────────────────────────── Step constants ───────────────────────────
# Canonical step names for run_one and run_multiclip. Using constants keeps
# typos out of resume state files (the worst possible bug here would be a
# step silently never matching).


class Step:
    # Single-clip pipeline (run_one)
    DOWNLOAD     = "download"
    SCRIPT       = "script"
    VOICEOVER    = "voiceover"
    SCENE_PICK   = "scene_pick"
    TRANSCRIBE   = "transcribe"
    CAPTIONS     = "captions"
    IMAGES       = "images"
    AUDIO_MIX    = "audio_mix"
    REFRAME      = "reframe"
    COMPOSE      = "compose"
    YT_METADATA  = "youtube_metadata"

    # Multi-clip pipeline (run_multiclip)
    MULTI_DOWNLOAD   = "multi_download"
    MULTI_TRANSCRIBE = "multi_transcribe"
    MULTI_MOMENTS    = "multi_moments"
    MULTI_RENDER     = "multi_render"   # tracks per-subclip status in metadata.subclips

    ALL_SINGLE = (
        DOWNLOAD, SCRIPT, VOICEOVER, SCENE_PICK, TRANSCRIBE,
        CAPTIONS, IMAGES, AUDIO_MIX, REFRAME, COMPOSE, YT_METADATA,
    )
    ALL_MULTI = (
        MULTI_DOWNLOAD, MULTI_TRANSCRIBE, MULTI_MOMENTS, MULTI_RENDER,
    )


# Keys in the job dict that meaningfully affect the rendered output. If any
# of these changes between a run and a resume, we warn the user and prompt
# them via the spec_hash mismatch path. Things like the GUI's batch_count
# or status-only fields are deliberately omitted.
_SPEC_KEYS_FOR_HASH: tuple[str, ...] = (
    "source_url", "channel_url", "source_file", "title_filter",
    "topic", "script", "target_duration", "clip_segments",
    "scene_pick_mode", "manual_ranges", "auto_reframe", "enable_voice",
    "image_count", "image_duration", "image_prompts", "image_paths",
    "no_image", "hook_text", "pop_captions", "progress_bar",
    "subscribe_overlay", "multiclip_enabled", "multiclip_count",
    "reframe_v2", "youtube_metadata",
)


def _hash_spec(spec: dict) -> str:
    """Stable hash over the spec keys that affect output. Used to detect
    when a user resumed an existing job after editing parameters."""
    snap = {k: spec.get(k) for k in _SPEC_KEYS_FOR_HASH if k in spec}
    blob = json.dumps(snap, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ───────────────────────────── JobState ─────────────────────────────


@dataclass
class JobState:
    """In-memory representation of a job's persistent state."""

    job_id: str
    job_kind: str                      # "single" | "multiclip"
    work_dir: Path
    spec_hash: str
    started_at: float
    updated_at: float
    completed_steps: dict = field(default_factory=dict)
    # `metadata` is free-form scratch for things that don't fit "this step
    # produced this artifact": multiclip moment list, per-subclip status,
    # YouTube metadata blob, etc.
    metadata: dict = field(default_factory=dict)
    version: int = STATE_VERSION

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "job_id": self.job_id,
            "job_kind": self.job_kind,
            "work_dir": str(self.work_dir),
            "spec_hash": self.spec_hash,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_steps": self.completed_steps,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JobState":
        return cls(
            job_id=data["job_id"],
            job_kind=data.get("job_kind", "single"),
            work_dir=Path(data.get("work_dir", ".")),
            spec_hash=data.get("spec_hash", ""),
            started_at=float(data.get("started_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            completed_steps=dict(data.get("completed_steps", {})),
            metadata=dict(data.get("metadata", {})),
            version=int(data.get("version", STATE_VERSION)),
        )


# ───────────────────────────── StateStore ─────────────────────────────


class StateStore:
    """Loads, mutates, and persists a JobState to `{work_dir}/job_state.json`.

    Atomic writes via temp-file + rename so an interrupted save can't leave a
    partial JSON on disk (resume would then crash on load — bad).
    """

    def __init__(self, work_dir: Path, job_id: str, job_kind: str,
                 spec: dict, *, log: Logger | None = None) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.work_dir / STATE_FILE_NAME
        self.log = log or Logger()
        self._spec = spec
        self.state: JobState = self._load_or_create(job_id, job_kind, spec)

    # ── lifecycle ──

    def _load_or_create(self, job_id: str, job_kind: str, spec: dict) -> JobState:
        spec_hash = _hash_spec(spec)
        now = time.time()
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                state = JobState.from_dict(data)
            except Exception as e:
                self.log.warn(f"job_state.json unreadable ({e}); starting fresh")
                return JobState(
                    job_id=job_id, job_kind=job_kind, work_dir=self.work_dir,
                    spec_hash=spec_hash, started_at=now, updated_at=now,
                )
            # Compatibility checks.
            if state.job_kind != job_kind:
                self.log.warn(
                    f"resume: job kind changed ({state.job_kind!r} → "
                    f"{job_kind!r}); starting fresh"
                )
                return JobState(
                    job_id=job_id, job_kind=job_kind, work_dir=self.work_dir,
                    spec_hash=spec_hash, started_at=now, updated_at=now,
                )
            if state.spec_hash and state.spec_hash != spec_hash:
                self.log.warn(
                    "resume: job parameters changed since last run "
                    f"(hash {state.spec_hash} → {spec_hash}); "
                    "completed steps will still be reused — delete "
                    f"{self.path.name} to force a full re-render"
                )
                state.spec_hash = spec_hash
            return state
        return JobState(
            job_id=job_id, job_kind=job_kind, work_dir=self.work_dir,
            spec_hash=spec_hash, started_at=now, updated_at=now,
        )

    def save(self) -> None:
        self.state.updated_at = time.time()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            tmp.write_text(
                json.dumps(self.state.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, self.path)
        except Exception as e:
            self.log.warn(f"failed to persist job_state.json: {e}")

    # ── step queries / mutations ──

    def is_done(self, step: str) -> bool:
        """A step counts as done iff it's recorded AND any file artifacts it
        references still exist on disk. If an artifact file was deleted, we
        invalidate the step so it re-runs."""
        rec = self.state.completed_steps.get(step)
        if not rec:
            return False
        for key, val in (rec.get("artifacts") or {}).items():
            # Path-shaped artifacts: key ends with _path / _file or value
            # looks like an existing-ish path string.
            if isinstance(val, str) and (key.endswith("_path") or key.endswith("_file")):
                if not Path(val).exists():
                    self.log.warn(
                        f"resume: artifact missing for step {step!r} "
                        f"({key}={val}); will re-run this step"
                    )
                    self.state.completed_steps.pop(step, None)
                    self.save()
                    return False
        return True

    def mark_done(self, step: str, artifacts: dict | None = None) -> None:
        rec: dict[str, Any] = {"completed_at": time.time()}
        if artifacts:
            # Stringify Paths so they round-trip through JSON.
            rec["artifacts"] = {
                k: (str(v) if isinstance(v, Path) else v)
                for k, v in artifacts.items()
            }
        self.state.completed_steps[step] = rec
        self.save()

    def get_artifact(self, step: str, key: str, default: Any = None) -> Any:
        rec = self.state.completed_steps.get(step) or {}
        return (rec.get("artifacts") or {}).get(key, default)

    def invalidate(self, *steps: str) -> None:
        """Mark these steps incomplete. Saves immediately."""
        changed = False
        for s in steps:
            if s in self.state.completed_steps:
                self.state.completed_steps.pop(s)
                changed = True
        if changed:
            self.save()

    def invalidate_from(self, step: str, all_steps: Iterable[str]) -> None:
        """Invalidate `step` and every step that comes after it in the
        ordered `all_steps` iterable. Use when a key earlier artifact
        changed and downstream caches are now stale."""
        seen = False
        for s in all_steps:
            if s == step:
                seen = True
            if seen and s in self.state.completed_steps:
                self.state.completed_steps.pop(s)
        self.save()

    # ── metadata helpers (free-form) ──

    def set_meta(self, key: str, value: Any) -> None:
        self.state.metadata[key] = value
        self.save()

    def get_meta(self, key: str, default: Any = None) -> Any:
        return self.state.metadata.get(key, default)

    # ── progress summary (for GUI display) ──

    def progress_summary(self) -> str:
        all_steps = (Step.ALL_MULTI if self.state.job_kind == "multiclip"
                     else Step.ALL_SINGLE)
        done = sum(1 for s in all_steps if s in self.state.completed_steps)
        return f"{done}/{len(all_steps)} steps complete"


# ───────────────── Subclip tracking (multiclip resume) ─────────────────


def get_subclip_status(state: StateStore, idx: int) -> str:
    """`pending` | `done` | `failed`. Stored under metadata.subclips[idx]."""
    subs = state.get_meta("subclips", {}) or {}
    rec = subs.get(str(idx))
    if not rec:
        return "pending"
    return str(rec.get("status", "pending"))


def set_subclip_done(state: StateStore, idx: int, out_path: Path,
                      title: str = "") -> None:
    subs = state.get_meta("subclips", {}) or {}
    subs[str(idx)] = {
        "status": "done",
        "out_path": str(out_path),
        "title": title,
        "completed_at": time.time(),
    }
    state.set_meta("subclips", subs)


def set_subclip_failed(state: StateStore, idx: int, error: str) -> None:
    subs = state.get_meta("subclips", {}) or {}
    subs[str(idx)] = {
        "status": "failed",
        "error": error[:400],
        "failed_at": time.time(),
    }
    state.set_meta("subclips", subs)


def list_done_subclips(state: StateStore) -> list[tuple[int, Path]]:
    """Return [(idx, out_path), ...] for completed subclips whose file
    still exists. Missing files are treated as not-done."""
    subs = state.get_meta("subclips", {}) or {}
    out: list[tuple[int, Path]] = []
    for k, rec in subs.items():
        if rec.get("status") != "done":
            continue
        p = Path(str(rec.get("out_path", "")))
        if p.is_file():
            try:
                out.append((int(k), p))
            except ValueError:
                continue
    out.sort(key=lambda t: t[0])
    return out
