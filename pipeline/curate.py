"""Curate: build a timed selection using user preferences (taste layer input).

v0.2: duration-sized selection with day coverage and explicit video priority.
Videos were previously starved because sharp images scored higher and filled
the whole time budget first.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from pipeline.config import Preferences
from pipeline.media import MediaItem


def _item_duration(item: MediaItem, image_seconds: float) -> float:
    if item.kind == "video":
        # Prefer real duration; tiny clips still count as at least 1s
        return max(float(item.duration_sec or 0.0), 1.0)
    return image_seconds


def _day_key(dt: Optional[datetime]) -> str:
    if dt is None:
        return "unknown"
    return dt.strftime("%Y-%m-%d")


def assign_day_labels(items: List[MediaItem], day_format: str) -> None:
    prev_day: Optional[str] = None
    for item in sorted(items, key=lambda m: (m.captured_at or datetime.min, m.path.name)):
        if item.captured_at:
            label = item.captured_at.strftime(day_format)
            day = _day_key(item.captured_at)
        else:
            label = None
            day = "unknown"
        item.day_label = label
        item.show_day_label = bool(label) and day != prev_day and day != "unknown"
        if day != "unknown":
            prev_day = day


def heuristic_score(item: MediaItem) -> float:
    """Generic stand-in until vision scoring uses taste_prompt."""
    if item.kind == "video":
        d = float(item.duration_sec or 0.0)
        if d < 2:
            return 50.0
        if d > 180:
            return 70.0
        # Mid-length clips score well; keep comparable to images
        return 85.0 + min(d, 60) * 0.15
    # Cap sharpness influence so images don't always beat videos
    return min(95.0, 35.0 + min(item.sharpness, 400.0) / 8.0)


def _try_add(
    item: MediaItem,
    selected: List[MediaItem],
    selected_ids: set,
    total: float,
    target_sec: float,
    image_seconds: float,
) -> float:
    if id(item) in selected_ids:
        return total
    dur = _item_duration(item, image_seconds)
    if total >= target_sec:
        return total
    # Allow slight overrun for a video that mostly fits
    if total + dur > target_sec * 1.08 and total >= target_sec * 0.75:
        return total
    selected.append(item)
    selected_ids.add(id(item))
    return total + dur


def curate(
    candidates: List[MediaItem],
    prefs: Preferences,
) -> Tuple[List[MediaItem], dict]:
    """Select a subset that approximately fills target_duration_min."""
    target_sec = prefs.target_duration_min * 60.0
    image_seconds = prefs.image_seconds

    ranked = sorted(candidates, key=lambda m: (m.captured_at or datetime.min, m.path.name))
    for item in ranked:
        item.score = heuristic_score(item)

    by_day: dict = {}
    for item in ranked:
        key = _day_key(item.captured_at)
        by_day.setdefault(key, []).append(item)

    selected: List[MediaItem] = []
    selected_ids: set = set()
    total = 0.0

    # Pass 1: one representative per day (highest score — image or video)
    for _day, day_items in sorted(by_day.items()):
        best = max(day_items, key=lambda m: m.score)
        total = _try_add(best, selected, selected_ids, total, target_sec, image_seconds)

    leftovers = [m for m in ranked if id(m) not in selected_ids]
    videos = sorted(
        [m for m in leftovers if m.kind == "video"],
        key=lambda m: m.score,
        reverse=True,
    )
    images = sorted(
        [m for m in leftovers if m.kind == "image"],
        key=lambda m: m.score,
        reverse=True,
    )

    # Pass 2: videos get a capped share of the remaining budget so images
    # still fill the presentation (previously images starved videos;
    # uncapped video-first starved images).
    remaining = max(0.0, target_sec - total)
    video_cap = remaining * 0.55
    video_used = 0.0
    for item in videos:
        dur = _item_duration(item, image_seconds)
        if video_used >= video_cap:
            break
        # Skip a clip that alone would blow past the video share when we
        # already have some videos; try shorter ones later in the list.
        if video_used > 0 and video_used + dur > video_cap * 1.15:
            continue
        new_total = _try_add(item, selected, selected_ids, total, target_sec, image_seconds)
        if new_total > total:
            video_used += dur
            total = new_total
        if total >= target_sec:
            break

    # Pass 3: fill remaining budget with images
    if total < target_sec:
        for item in images:
            total = _try_add(item, selected, selected_ids, total, target_sec, image_seconds)
            if total >= target_sec:
                break

    # Pass 4: if still under target (few/short videos), allow more videos
    if total < target_sec * 0.9:
        for item in videos:
            total = _try_add(item, selected, selected_ids, total, target_sec, image_seconds)
            if total >= target_sec:
                break

    selected.sort(key=lambda m: (m.captured_at or datetime.min, m.path.name))
    assign_day_labels(selected, prefs.day_label_format)

    total = sum(_item_duration(m, image_seconds) for m in selected)
    n_img = sum(1 for m in selected if m.kind == "image")
    n_vid = sum(1 for m in selected if m.kind == "video")
    meta = {
        "target_duration_min": prefs.target_duration_min,
        "estimated_duration_sec": round(total, 1),
        "estimated_duration_min": round(total / 60.0, 1),
        "image_seconds": image_seconds,
        "selected_count": len(selected),
        "selected_images": n_img,
        "selected_videos": n_vid,
        "candidate_count": len(candidates),
        "candidate_images": sum(1 for m in candidates if m.kind == "image"),
        "candidate_videos": sum(1 for m in candidates if m.kind == "video"),
        "taste_prompt": prefs.taste_prompt,
        "curation_mode": "heuristic_v0.2_balanced_video",
        "note": (
            "Day coverage, then up to ~55% remaining budget for videos, "
            "then images to fill. taste_prompt stored for vision-API later."
        ),
    }
    return selected, meta
