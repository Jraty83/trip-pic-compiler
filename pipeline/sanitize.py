"""Sanitize: blur detection + near-duplicate removal (generic engine)."""

from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import imagehash
import numpy as np
from PIL import Image

from pipeline.config import Preferences
from pipeline.media import MediaItem

ProgressCb = Optional[Callable[[int, int, str, str, float], None]]


def sharpness_score(path: Path) -> float:
    """Variance of Laplacian on grayscale — higher = sharper."""
    with Image.open(path) as img:
        gray = np.asarray(img.convert("L"), dtype=np.float64)
    if gray.shape[0] < 16 or gray.shape[1] < 16:
        return 0.0
    max_side = 512
    h, w = gray.shape
    scale = min(1.0, max_side / max(h, w))
    if scale < 1.0:
        new_w = max(16, int(w * scale))
        new_h = max(16, int(h * scale))
        gray = np.array(
            Image.fromarray(gray.astype(np.uint8)).resize((new_w, new_h), Image.Resampling.BILINEAR),
            dtype=np.float64,
        )
    lap = (
        -4 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    return float(lap.var())


def compute_phash(path: Path) -> str:
    with Image.open(path) as img:
        return str(imagehash.phash(img.convert("RGB")))


def _mark_reject(item: MediaItem, reason: str) -> None:
    item.keep = False
    item.reject_reason = reason


def filter_blur(
    items: List[MediaItem],
    threshold: float,
    on_progress: ProgressCb = None,
) -> Tuple[List[MediaItem], List[MediaItem]]:
    kept: List[MediaItem] = []
    rejected: List[MediaItem] = []
    total = len(items)
    for idx, item in enumerate(items, start=1):
        t0 = time.monotonic()
        detail = "skip_video"
        if item.kind != "image":
            kept.append(item)
        else:
            try:
                score = sharpness_score(item.path)
                item.sharpness = score
                if score < threshold:
                    _mark_reject(item, f"blur:{score:.1f}<{threshold}")
                    rejected.append(item)
                    detail = "reject_blur"
                else:
                    kept.append(item)
                    detail = "keep"
            except Exception as exc:  # noqa: BLE001
                _mark_reject(item, f"sharpness_error:{exc}")
                rejected.append(item)
                detail = "error"
        elapsed = time.monotonic() - t0
        if on_progress:
            on_progress(idx, total, item.path.name, detail, elapsed)
    return kept, rejected


def filter_duplicates(
    items: List[MediaItem],
    max_distance: int,
    max_burst_keep: int,
    on_progress: ProgressCb = None,
) -> Tuple[List[MediaItem], List[MediaItem]]:
    ranked = sorted(
        items,
        key=lambda m: (m.sharpness if m.kind == "image" else 9999.0),
        reverse=True,
    )
    kept: List[MediaItem] = []
    rejected: List[MediaItem] = []
    kept_hashes: List[imagehash.ImageHash] = []
    cluster_counts: List[int] = []
    total = len(ranked)

    for idx, item in enumerate(ranked, start=1):
        t0 = time.monotonic()
        detail = "video"
        if item.kind != "image":
            kept.append(item)
        else:
            try:
                h = (
                    imagehash.hex_to_hash(item.phash)
                    if item.phash
                    else imagehash.hex_to_hash(compute_phash(item.path))
                )
                item.phash = str(h)
                matched_idx = None
                for i, existing in enumerate(kept_hashes):
                    if h - existing <= max_distance:
                        matched_idx = i
                        break
                if matched_idx is None:
                    kept.append(item)
                    kept_hashes.append(h)
                    cluster_counts.append(1)
                    detail = "unique"
                else:
                    cluster_counts[matched_idx] += 1
                    if cluster_counts[matched_idx] <= max_burst_keep:
                        kept.append(item)
                        detail = "burst_keep"
                    else:
                        _mark_reject(item, f"duplicate_of_cluster:{matched_idx}")
                        rejected.append(item)
                        detail = "duplicate"
            except Exception as exc:  # noqa: BLE001
                _mark_reject(item, f"phash_error:{exc}")
                rejected.append(item)
                detail = "error"
        elapsed = time.monotonic() - t0
        if on_progress:
            on_progress(idx, total, item.path.name, detail, elapsed)

    kept_sorted = sorted(kept, key=lambda m: (m.captured_at or datetime.min, m.path.name))
    return kept_sorted, rejected


def copy_rejects(rejected: List[MediaItem], rejects_dir: Path) -> None:
    rejects_dir.mkdir(parents=True, exist_ok=True)
    for item in rejected:
        dest = rejects_dir / item.path.name
        if item.path.exists() and item.path.resolve() != dest.resolve():
            shutil.copy2(item.path, dest)


def sanitize_all(
    items: List[MediaItem],
    prefs: Preferences,
    work_dir: Path,
    on_progress: ProgressCb = None,
) -> Tuple[List[MediaItem], List[MediaItem]]:
    after_blur, blur_rejected = filter_blur(items, prefs.blur_threshold, on_progress=on_progress)
    after_dedup, dup_rejected = filter_duplicates(
        after_blur,
        prefs.duplicate_hash_distance,
        prefs.max_burst_keep,
        on_progress=on_progress,
    )
    all_rejected = blur_rejected + dup_rejected
    copy_rejects(all_rejected, work_dir / "rejects")
    return after_dedup, all_rejected
