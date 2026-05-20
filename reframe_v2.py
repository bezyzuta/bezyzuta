"""Auto-Reframe v2 — improved per-segment face tracking for 9:16 cropping.

Improvements over v1 (`detect_subject_x_position` / `detect_subjects_per_segment`
in pipeline.py):

  1. **Per-segment in single-clip mode too.** v1 averaged the whole clip,
     so a host who moves left-then-right got cropped at "middle of the
     motion" with both edges clipped. v2 always produces a per-segment
     timeline; pipeline.py decides whether to pass it as a list (multi-cut
     composer) or a single value (single-cut composer averages it).

  2. **Multiple samples per segment.** v1 sampled exactly one frame at the
     segment midpoint. A fast cut or motion blur there meant "no face → 0.5".
     v2 takes 3-5 samples spread across the segment and picks the best.

  3. **Confidence-weighted aggregation.** YOLO and InsightFace return box
     sizes — we use bigger box = higher confidence, so a 20-pixel
     background face doesn't outvote a 200-pixel foreground host.

  4. **Temporal smoothing.** If segment N's offset is 0.20 and segment
     N+1's is 0.85 (likely a detector error rather than two speakers
     swapping sides in 3 seconds), we pull N+1 toward N unless N+1 had
     a high-confidence detection.

  5. **Multi-face awareness.** If a segment has multiple comparable-size
     faces, that's a podcast layout — stay closer to centered rather than
     chasing the largest face to the side. v1 always chased the largest.

  6. **Hold-last semantics.** "No face in this segment" inherits the
     previous segment's offset instead of snapping to centered. (A speaker
     who briefly turns away or gets occluded doesn't jitter the frame.)

This module deliberately does NOT re-implement the detector adapters —
it imports the existing `_get_yolo_face_detector`, `_get_insightface`,
and `_get_mediapipe_detector` from pipeline.py so all CUDA / weight-cache /
license-agreement plumbing keeps working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Detector imports are done lazily inside functions so this module can
# be imported in environments where ultralytics / insightface aren't
# present (MediaPipe is always there as the floor).


@dataclass
class Detection:
    """One face-detector reading for a single frame."""
    center_x: float           # normalized 0..1 (in the source frame's width)
    confidence: float         # 0..1, derived from box area or detector score
    detector: str             # "yolo" | "insightface" | "mediapipe"
    n_faces: int = 1          # how many faces the detector found in the frame
    relative_top_face_area: float = 1.0  # largest / sum-of-all-faces, 0..1
    # Mouth-Aspect-Ratio for active-speaker detection. NaN = not measured
    # (speaker detection disabled or FaceMesh unavailable). Higher MAR
    # roughly means the mouth is more open ≈ the person is likely speaking.
    mouth_open: float = float("nan")


@dataclass
class SegmentResult:
    """Aggregated result for a single segment (one cut of the gameplay)."""
    start_time: float
    offset: float             # final crop offset 0..1 (0=left, 1=right)
    confidence: float         # aggregated 0..1
    label: str                # "yolo" | "insightface" | "mediapipe" | "no-face"
                              # | "smoothed" | "centered" | "held-prev"
    samples: list[Detection] = field(default_factory=list)


# ────────────────── Detector adapters (thin wrappers) ──────────────────

# Lazy-init holder for MediaPipe FaceMesh. False = tried and failed, None =
# not tried yet, otherwise the loaded mesh instance.
_FACE_MESH: object | None = None


def _get_face_mesh():
    """Lazy-load MediaPipe FaceMesh for active-speaker detection via the
    mouth-aspect-ratio of each detected face. Falls back to None on import
    error or init failure; callers must handle 'no mesh available' gracefully."""
    global _FACE_MESH
    if _FACE_MESH is False:
        return None
    if _FACE_MESH is not None:
        return _FACE_MESH
    try:
        import mediapipe as mp  # type: ignore
    except Exception:
        _FACE_MESH = False
        return None
    try:
        _FACE_MESH = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=4,
            refine_landmarks=False,
            min_detection_confidence=0.3,
        )
    except Exception:
        _FACE_MESH = False
        return None
    return _FACE_MESH


# FaceMesh landmark indices for the inner lip + mouth corners. MAR is
# computed as vertical_inner_lip_gap / horizontal_mouth_width. Empirically
# MAR > ~0.05 means "mouth visibly open", > ~0.10 means "speaking strongly".
_LIP_TOP_INNER    = 13
_LIP_BOTTOM_INNER = 14
_MOUTH_LEFT       = 61
_MOUTH_RIGHT      = 291


def _measure_mouths(img, boxes: list[tuple[float, float, float, float, float]]
                    ) -> list[float]:
    """For each (x1,y1,x2,y2,score) face box, return the MAR. NaN if FaceMesh
    couldn't find a mesh that sits inside that box."""
    mesh = _get_face_mesh()
    if not mesh or not boxes:
        return [float("nan")] * len(boxes)
    try:
        import cv2  # type: ignore
    except Exception:
        return [float("nan")] * len(boxes)
    h, w = img.shape[:2]
    mars: list[float] = [float("nan")] * len(boxes)
    try:
        results = mesh.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    except Exception:
        return mars
    mfl = getattr(results, "multi_face_landmarks", None) or []
    for landmarks in mfl:
        lm = landmarks.landmark
        # Use mesh center (avg of all landmarks) to find which face box this
        # mesh belongs to. FaceMesh sometimes detects faces that our face
        # detector missed and vice versa — we only attach MARs to boxes we
        # already know about.
        cx = sum(p.x for p in lm) / len(lm) * w
        cy = sum(p.y for p in lm) / len(lm) * h
        for bi, (x1, y1, x2, y2, _) in enumerate(boxes):
            if x1 <= cx <= x2 and y1 <= cy <= y2:
                vert = abs(lm[_LIP_TOP_INNER].y - lm[_LIP_BOTTOM_INNER].y) * h
                horiz = max(1.0, abs(lm[_MOUTH_LEFT].x - lm[_MOUTH_RIGHT].x) * w)
                mars[bi] = float(vert / horiz)
                break
    return mars


def _detect_faces_in_frame(thumb_path: Path,
                           measure_speaker: bool = False
                           ) -> tuple[list[Detection], str]:
    """Run the full detector cascade against one frame, returning *all*
    detected faces (not just the largest) plus which detector handled it.

    Returns (detections, detector_label). `detections` may be empty if no
    detector found anything; in that case the label reflects which detector
    ran (so "ran YOLO, got nothing" is distinguishable from "no detector
    available"). Empty list + "none" label = no detector available at all.
    """
    try:
        import cv2  # type: ignore
    except Exception:
        return [], "none"

    img = cv2.imread(str(thumb_path))
    if img is None:
        return [], "none"
    h, w = img.shape[:2]
    if h <= 0 or w <= 0:
        return [], "none"

    # We import lazily because pipeline.py owns the model lifecycle (cache,
    # CUDA providers, license acceptance). Reimplementing that here would
    # double the bug surface for every detector quirk.
    try:
        from pipeline import (  # type: ignore
            _get_yolo_face_detector,
            _get_insightface,
            _get_mediapipe_detector,
        )
    except Exception:
        return [], "none"

    # ── YOLO (best on GPU, ~5ms/frame on RTX 3080) ──
    yolo = _get_yolo_face_detector()
    if yolo:
        boxes: list[tuple[float, float, float, float, float]] = []
        try:
            results = yolo(img, verbose=False, conf=0.30)
            for r in results or []:
                try:
                    confs = r.boxes.conf.cpu().tolist()
                    for b, c in zip(r.boxes, confs):
                        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0].cpu().tolist()]
                        boxes.append((x1, y1, x2, y2, float(c)))
                except Exception:
                    continue
        except Exception:
            boxes = []
        if boxes:
            mars = _measure_mouths(img, boxes) if measure_speaker else None
            return (_boxes_to_detections(boxes, w, "yolo", mars), "yolo")

    # ── InsightFace (RetinaFace, highest accuracy when present) ──
    app = _get_insightface()
    if app:
        try:
            faces = app.get(img)
        except Exception:
            faces = []
        boxes = []
        for f in faces or []:
            try:
                x1, y1, x2, y2 = [float(v) for v in f.bbox]
                conf = float(getattr(f, "det_score", 0.9))
                boxes.append((x1, y1, x2, y2, conf))
            except Exception:
                continue
        if boxes:
            mars = _measure_mouths(img, boxes) if measure_speaker else None
            return (_boxes_to_detections(boxes, w, "insightface", mars), "insightface")

    # ── MediaPipe (CPU fallback, always present) ──
    fd = _get_mediapipe_detector()
    if fd:
        try:
            results = fd.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        except Exception:
            results = None
        detections = getattr(results, "detections", None) or []
        boxes = []
        for d in detections:
            try:
                bb = d.location_data.relative_bounding_box
                x1 = bb.xmin * w
                y1 = bb.ymin * h
                x2 = (bb.xmin + bb.width) * w
                y2 = (bb.ymin + bb.height) * h
                conf = float(d.score[0]) if d.score else 0.5
                boxes.append((x1, y1, x2, y2, conf))
            except Exception:
                continue
        if boxes:
            mars = _measure_mouths(img, boxes) if measure_speaker else None
            return (_boxes_to_detections(boxes, w, "mediapipe", mars), "mediapipe")
        # Detector ran but found nothing — distinguishable from "no detector".
        return [], "mediapipe-empty"

    # Nothing available.
    return [], "none"


def _boxes_to_detections(
    boxes: list[tuple[float, float, float, float, float]],
    frame_w: int,
    detector: str,
    mars: list[float] | None = None,
) -> list[Detection]:
    """Convert (x1,y1,x2,y2,score) tuples into Detection objects with
    normalized center_x and a derived confidence. `mars` is an optional
    parallel list of mouth-aspect-ratios for active-speaker detection."""
    if not boxes:
        return []
    areas = [max(0.0, (b[2] - b[0]) * (b[3] - b[1])) for b in boxes]
    max_area = max(areas) or 1.0
    total_area = sum(areas) or 1.0
    out: list[Detection] = []
    for i, ((x1, _y1, x2, _y2, score), area) in enumerate(zip(boxes, areas)):
        center_x = (x1 + x2) / 2.0 / max(1, frame_w)
        # Confidence blends the detector's own score with relative size.
        # A 200px host face anchors crop position more than a 20px crowd face.
        size_term = (area / max_area) ** 0.5
        score_term = max(0.0, min(1.0, score))
        confidence = 0.5 * size_term + 0.5 * score_term
        out.append(Detection(
            center_x=max(0.0, min(1.0, center_x)),
            confidence=confidence,
            detector=detector,
            n_faces=len(boxes),
            relative_top_face_area=area / total_area,
            mouth_open=(mars[i] if mars and i < len(mars) else float("nan")),
        ))
    return out


# ────────────────── Sampling + segment aggregation ──────────────────


def _extract_thumb(source: Path, t: float, out_path: Path, width: int = 640) -> bool:
    """Extract one JPEG at time t. Reuses pipeline.py's helper so we get the
    same ffmpeg flags / error handling."""
    try:
        from pipeline import _extract_thumbnail  # type: ignore
    except Exception:
        return False
    try:
        return bool(_extract_thumbnail(source, t, out_path, width=width))
    except Exception:
        return False


import math


def _pick_subject_offset(detections: list[Detection], source_aspect: float) -> tuple[float, float, bool]:
    """Pick the offset from a list of detections in one frame.

    Returns (offset_0_1, confidence_0_1, multi_face).

    `multi_face=True` means there are >=2 comparable-size faces (likely
    a podcast/interview layout) and the caller should be conservative about
    chasing the largest one off-center.

    When mouth-aspect-ratio data is present on multi-face frames, we prefer
    the face that's actively speaking (mouth most open) over the largest
    one. Falls back to the largest-face heuristic when MAR isn't available
    or all faces have similar MAR (nobody clearly speaking).
    """
    if not detections:
        return (0.5, 0.0, False)

    # Multi-face heuristic: at least one other face with >= 60% of the
    # primary's relative area.
    multi = False
    if len(detections) > 1:
        sizes = sorted([d.relative_top_face_area for d in detections], reverse=True)
        if len(sizes) >= 2 and sizes[1] >= 0.6 * sizes[0]:
            multi = True

    # Speaker-aware face pick (only meaningful when multi-face AND we have
    # MAR data). If one face has noticeably higher MAR than the others by at
    # least 0.03, that's the active speaker — pick them. Otherwise fall back
    # to confidence (size × detector score).
    primary = None
    if multi:
        mars = [(d.mouth_open, d) for d in detections
                if not math.isnan(d.mouth_open)]
        if len(mars) >= 2:
            mars.sort(key=lambda t: t[0], reverse=True)
            top_mar, top_face = mars[0]
            runner_mar, _ = mars[1]
            # Require a clear margin AND a minimum absolute openness, so
            # closed mouths at MAR ~0.02 don't fight over millimeters.
            if top_mar - runner_mar > 0.03 and top_mar > 0.05:
                primary = top_face
    if primary is None:
        primary = max(detections, key=lambda d: d.confidence)

    # Convert face center in source frame to crop offset in 9:16 window.
    # r = visible width fraction of the source we keep after cropping to 9:16.
    r = 9.0 / (16.0 * max(0.01, source_aspect))
    if r >= 0.99:
        # Source is already (near-)portrait; crop window covers it all.
        return (0.5, primary.confidence, multi)

    raw = (primary.center_x - r / 2.0) / max(0.001, (1.0 - r))
    offset = max(0.0, min(1.0, raw))

    # If multi-face AND we did NOT pick via speaker detection, pull toward
    # 0.5 a bit so the other person isn't cropped out entirely. When speaker
    # detection picked a clear winner, don't damp — chase the speaker.
    speaker_picked = (primary is not None
                      and not math.isnan(primary.mouth_open)
                      and primary.mouth_open > 0.05)
    if multi and not speaker_picked:
        offset = 0.5 + 0.65 * (offset - 0.5)

    return (offset, primary.confidence, multi)


def _analyze_segment(
    source: Path,
    seg_start: float,
    seg_dur: float,
    work_dir: Path,
    seg_idx: int,
    *,
    n_samples: int,
    source_aspect: float,
    speaker_detection: bool,
    log: Callable[[str], None],
) -> SegmentResult:
    """Sample N frames across a segment, detect faces, pick a weighted offset.
    When `speaker_detection=True`, additionally measure mouth-aspect-ratio
    per face so multi-face frames can prefer whoever is actively speaking."""
    # Sample at evenly-spaced times within the segment, skipping the very
    # first/last 5% to avoid hard cuts.
    if n_samples <= 1:
        sample_times = [seg_start + seg_dur / 2.0]
    else:
        pad = seg_dur * 0.05
        usable = max(0.1, seg_dur - 2 * pad)
        sample_times = [
            seg_start + pad + usable * i / (n_samples - 1)
            for i in range(n_samples)
        ]

    all_dets: list[Detection] = []
    last_label = "none"
    multi_seen = False
    sample_offsets: list[tuple[float, float, bool]] = []  # (offset, conf, multi)
    for j, t in enumerate(sample_times):
        thumb = work_dir / f"reframe_v2_seg{seg_idx:02d}_s{j}.jpg"
        if not _extract_thumb(source, t, thumb, width=640):
            continue
        dets, label = _detect_faces_in_frame(thumb, measure_speaker=speaker_detection)
        last_label = label
        if not dets:
            continue
        all_dets.extend(dets)
        off, conf, multi = _pick_subject_offset(dets, source_aspect)
        sample_offsets.append((off, conf, multi))
        if multi:
            multi_seen = True

    if not sample_offsets:
        # No face anywhere across all samples. If a detector actually ran,
        # this is authoritative ("no people here") → caller will hold-prev
        # or centered. If no detector ran at all, label as "none" so the
        # caller can decide to invoke an LLM fallback.
        detector_ran = last_label not in ("none",)
        return SegmentResult(
            start_time=seg_start,
            offset=0.5,
            confidence=0.0,
            label="no-face" if detector_ran else "none",
            samples=[],
        )

    # Confidence-weighted aggregation across the samples we got.
    total_w = sum(c for _, c, _ in sample_offsets) or 1.0
    weighted = sum(o * c for o, c, _ in sample_offsets) / total_w
    avg_conf = total_w / len(sample_offsets)

    # If the per-sample offsets disagree wildly (host is moving fast or
    # the detector picked different faces in different samples), lower the
    # confidence so smoothing damps this segment more.
    if len(sample_offsets) >= 2:
        offsets = sorted(o for o, _, _ in sample_offsets)
        spread = offsets[-1] - offsets[0]
        if spread > 0.30:
            avg_conf *= max(0.2, 1.0 - spread)

    # Decide label from majority detector (informational only).
    counts: dict[str, int] = {}
    for d in all_dets:
        counts[d.detector] = counts.get(d.detector, 0) + 1
    label = max(counts, key=counts.get) if counts else "no-face"
    if multi_seen:
        label = label + "+multi"

    return SegmentResult(
        start_time=seg_start,
        offset=max(0.0, min(1.0, weighted)),
        confidence=max(0.0, min(1.0, avg_conf)),
        label=label,
        samples=all_dets,
    )


def _smooth(results: list[SegmentResult]) -> list[SegmentResult]:
    """Damp wild swings between adjacent segments using a confidence-aware
    1-step smoother. Also fills `no-face` segments by inheriting the
    previous segment's offset (hold-last)."""
    if len(results) <= 1:
        return results

    # First pass: hold-last for no-face segments.
    prev_off: float | None = None
    for r in results:
        if r.label.startswith("no-face") and prev_off is not None:
            r.offset = prev_off
            r.label = "held-prev"
        elif r.confidence > 0:
            prev_off = r.offset

    # Backfill from the front if the first segments had no face.
    next_off: float | None = None
    for r in reversed(results):
        if r.label == "held-prev" or r.confidence > 0:
            next_off = r.offset
        elif r.label.startswith("no-face") and next_off is not None:
            r.offset = next_off
            r.label = "held-next"

    # Second pass: damp jumps. We blend each segment toward the prior one
    # by `(1 - my_confidence)` — high-confidence segments resist smoothing.
    smoothed: list[SegmentResult] = []
    for i, r in enumerate(results):
        if i == 0 or r.confidence >= 0.6:
            smoothed.append(r)
            continue
        prev = smoothed[-1].offset
        # Resist big jumps when our confidence is low.
        blend = 1.0 - max(0.0, min(1.0, r.confidence))
        new_off = (1.0 - blend) * r.offset + blend * prev
        if abs(new_off - r.offset) > 0.001:
            r.offset = new_off
            if not r.label.endswith("+smoothed"):
                r.label = r.label + "+smoothed"
        smoothed.append(r)

    return smoothed


# ────────────────── Public entry point ──────────────────


def detect_crop_offsets_v2(
    clip: Path,
    cfg,
    *,
    n_segments: int = 1,
    seg_duration: float | None = None,
    samples_per_segment: int = 3,
    speaker_detection: bool = False,
    on_step: Callable[[str], None] | None = None,
) -> list[tuple[float, float]]:
    """Run improved per-segment face tracking. Always returns a list of
    `(segment_start_time, offset_0_1)` tuples — even for single-segment
    clips, so the composer can decide whether to use them as a per-segment
    timeline or collapse to a single value (median).

    `n_segments` * `seg_duration` should equal the clip length. If
    `seg_duration` is None we infer it from the clip's actual duration via
    ffprobe (single-segment mode).

    `samples_per_segment` controls how many frames per segment we score.
    The legacy implementation used 1; 3 is the sweet spot for short
    segments (3-5s), 5 for longer (>10s).
    """
    log_step = on_step or print

    work_dir = clip.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    # Source aspect ratio — needed to convert face center_x in source frame
    # space to crop offset in 9:16 target space. We approximate from the
    # most recently extracted frame later; for now assume 16:9 (the common
    # YouTube case). If we wanted exact, we'd ffprobe `streams.0.width/height`.
    source_aspect = 16.0 / 9.0

    # Resolve segment timing.
    if seg_duration is None:
        try:
            from pipeline import probe_duration  # type: ignore
            total_dur = probe_duration(clip)
        except Exception:
            total_dur = 0.0
        if total_dur <= 0:
            return [(0.0, 0.5)]
        if n_segments <= 1:
            # Auto-split into ~3s buckets for smoother per-segment tracking
            # in single-cut mode. Cap at 8 to avoid 30 ffmpeg calls.
            bucket_dur = 3.0
            n_buckets = max(1, min(8, int(round(total_dur / bucket_dur))))
            seg_duration = total_dur / n_buckets
            n_segments = n_buckets
        else:
            seg_duration = total_dur / n_segments

    samples_per_segment = max(1, min(int(samples_per_segment), 7))

    if speaker_detection:
        log_step(f"      reframe-v2: speaker-detection ON (MediaPipe FaceMesh)")

    results: list[SegmentResult] = []
    for i in range(n_segments):
        seg_start = i * seg_duration
        r = _analyze_segment(
            clip, seg_start, seg_duration, work_dir, i,
            n_samples=samples_per_segment,
            source_aspect=source_aspect,
            speaker_detection=speaker_detection,
            log=log_step,
        )
        results.append(r)

    results = _smooth(results)

    # Counts for logging.
    label_counts: dict[str, int] = {}
    for r in results:
        # Strip "+smoothed"/"+multi" suffixes for the headline count.
        base = r.label.split("+", 1)[0]
        label_counts[base] = label_counts.get(base, 0) + 1
    counts_str = ", ".join(f"{k}={v}" for k, v in label_counts.items())
    summary = ", ".join(
        f"{r.start_time:5.1f}s=crop@{int(r.offset*100):3d}%({r.label[:18]})"
        for r in results
    )
    log_step(f"      reframe-v2 ({counts_str}): {summary}")

    return [(r.start_time, r.offset) for r in results]


def collapse_to_single_offset(offsets: list[tuple[float, float]]) -> float:
    """For the single-cut composer that wants ONE crop offset for the whole
    output. We use the median over the per-segment offsets (robust to a
    single bad detection)."""
    if not offsets:
        return 0.5
    vals = sorted(o for _, o in offsets)
    mid = vals[len(vals) // 2]
    return float(max(0.0, min(1.0, mid)))
