"""Sanitize: blur detection + near-duplicate removal (generic engine)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Tuple

import imagehash
import numpy as np
from PIL import Image

from pipeline.config import Preferences
from pipeline.media import MediaItem


def sharpness_score(path: Path) -> float:
    """Variance of Laplacian on grayscale — higher = sharper."""
    with Image.open(path) as img:
        gray = np.asarray(img.convert("L"), dtype=np.float64)
    # Simple Laplacian kernel
    # skip tiny images
    if gray.shape[0] < 16 or gray.shape[1] < 16:
        return 0.0
    # Downscale for speed
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


def filter_blur(items: List[MediaItem], threshold: float) -> Tuple[List[MediaItem], List[MediaItem]]:
    kept: List[MediaItem] = []
    rejected: List[MediaItem] = []
    for item in items:
        if item.kind != "image":
            # Videos: skip blur metric for now (could sample frames later)
            kept.append(item)
            continue
        try:
            score = sharpness_score(item.path)
        except Exception as exc:  # noqa: BLE001 — keep pipeline moving
            _mark_reject(item, f"sharpness_error:{exc}")
            rejected.append(item)
            continue
        item.sharpness = score
        if score < threshold:
            _mark_reject(item, f"blur:{score:.1f}<{threshold}")
            rejected.append(item)
        else:
            kept.append(item)
    return kept, rejected


def filter_duplicates(
    items: List[MediaItem],
    max_distance: int,
    max_burst_keep: int,
) -> Tuple[List[MediaItem], List[MediaItem]]:
    """Greedy near-duplicate removal using perceptual hash distance."""
    # Sort by sharpness desc so we keep the sharpest in a burst
    ranked = sorted(
        items,
        key=lambda m: (m.sharpness if m.kind == "image" else 9999.0),
        reverse=True,
    )
    kept: List[MediaItem] = []
    rejected: List[MediaItem] = []
    kept_hashes: List[imagehash.ImageHash] = []
    cluster_counts: List[int] = []

    for item in ranked:
        if item.kind != "image":
            kept.append(item)
            continue
        try:
            h = imagehash.hex_to_hash(compute_phash(item.path)) if not item.phash else imagehash.hex_to_hash(item.phash)
            item.phash = str(h)
        except Exception as exc:  # noqa: BLE001
            _mark_reject(item, f"phash_error:{exc}")
            rejected.append(item)
            continue

        matched_idx = None
        for idx, existing in enumerate(kept_hashes):
            if h - existing <= max_distance:
                matched_idx = idx
                break

        if matched_idx is None:
            kept.append(item)
            kept_hashes.append(h)
            cluster_counts.append(1)
        else:
            cluster_counts[matched_idx] += 1
            if cluster_counts[matched_idx] <= max_burst_keep:
                # Should not happen when max_burst_keep == 1 and we already kept one
                kept.append(item)
            else:
                _mark_reject(item, f"duplicate_of_cluster:{matched_idx}")
                rejected.append(item)

    # Restore chronological order for kept set
    kept_sorted = sorted(kept, key=lambda m: (m.captured_at or datetime_min(), m.path.name))
    return kept_sorted, rejected


def datetime_min():
    from datetime import datetime

    return datetime.min


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
) -> Tuple[List[MediaItem], List[MediaItem]]:
    after_blur, blur_rejected = filter_blur(items, prefs.blur_threshold)
    after_dedup, dup_rejected = filter_duplicates(
        after_blur,
        prefs.duplicate_hash_distance,
        prefs.max_burst_keep,
    )
    all_rejected = blur_rejected + dup_rejected
    copy_rejects(all_rejected, work_dir / "rejects")
    return after_dedup, all_rejected
